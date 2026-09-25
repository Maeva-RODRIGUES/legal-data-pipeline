from collections import Counter
from datetime import UTC, datetime, timedelta, timezone

import pytest

from src.search.index import index_name, parse_count_response, source_of
from src.search.rebuild import RebuildError, counts_match, rebuild

NOW = datetime(2026, 9, 25, 14, 30, 0, tzinfo=UTC)
NEW = "decisions_20260925_143000"
MAPPING = {"mappings": {"dynamic": "strict"}}
SILVER = {"adlc-opendata": 2, "judilibre": 1}


def docs():
    return [
        ("adlc-opendata|a", {"source": "adlc-opendata"}),
        ("adlc-opendata|b", {"source": "adlc-opendata"}),
        ("judilibre|c", {"source": "judilibre"}),
    ]


class FakeIndexClient:
    """Elasticsearch en mémoire : rejets et pannes programmables."""

    def __init__(self, indexes=(), alias=()):
        self.indexes = {name: {} for name in indexes}
        self.alias = list(alias)
        self.reject = set()  # identifiants refusés par l'envoi en masse
        self.fail_on = set()  # méthodes qui lèvent
        self.fail_delete = set()  # index dont la suppression échoue
        self.switch_calls = []

    def _maybe_fail(self, method):
        if method in self.fail_on:
            raise RuntimeError(f"panne {method}")

    def alias_targets(self, alias):
        self._maybe_fail("alias_targets")
        return sorted(self.alias)

    def is_index(self, name):
        return name in self.indexes

    def create_index(self, name, body):
        self._maybe_fail("create_index")
        assert name not in self.indexes
        self.indexes[name] = {}

    def bulk_index(self, name, docs, rejected):
        self._maybe_fail("bulk_index")
        for doc_id, doc in docs:
            if doc_id in self.reject:
                rejected[source_of(doc_id)] += 1
            else:
                self.indexes[name][doc_id] = doc

    def refresh(self, name):
        self._maybe_fail("refresh")

    def count_by_source(self, name):
        self._maybe_fail("count_by_source")
        return dict(Counter(doc["source"] for doc in self.indexes[name].values()))

    def switch_alias(self, alias, new, previous):
        self._maybe_fail("switch_alias")
        assert sorted(previous) == sorted(self.alias)
        self.switch_calls.append((alias, new, previous))
        self.alias = [new]

    def list_indexes(self, prefix):
        self._maybe_fail("list_indexes")
        return sorted(name for name in self.indexes if name.startswith(prefix))

    def delete_index(self, name):
        if name in self.fail_delete:
            raise RuntimeError(f"suppression de {name} refusée")
        assert name not in self.alias, "un index derrière l'alias ne doit jamais être supprimé"
        del self.indexes[name]


def test_nom_d_index_en_utc():
    assert index_name(NOW) == NEW
    paris = timezone(timedelta(hours=2))
    assert index_name(datetime(2026, 9, 25, 16, 30, tzinfo=paris)) == NEW


def test_premier_run_pose_l_alias():
    client = FakeIndexClient()
    result = rebuild(client, docs(), SILVER, MAPPING, NOW)
    assert result.alias_switched
    assert result.indexed_counts == SILVER
    assert result.previous_index is None
    assert client.alias == [NEW]
    assert list(client.indexes) == [NEW]
    assert client.switch_calls == [("decisions", NEW, [])]
    assert result.deleted_indexes == []


def test_comptes_identiques_bascule_en_un_seul_appel():
    old = "decisions_20260924_090000"
    client = FakeIndexClient(indexes=[old], alias=[old])
    result = rebuild(client, docs(), SILVER, MAPPING, NOW)
    assert result.alias_switched
    assert result.previous_index == old
    assert client.switch_calls == [("decisions", NEW, [old])]
    assert sorted(client.indexes) == [old, NEW]


@pytest.mark.parametrize(
    "silver",
    [
        {"adlc-opendata": 3, "judilibre": 1},  # un compte différent
        {"adlc-opendata": 2, "judilibre": 1, "autre": 4},  # source absente de l'index
        {"adlc-opendata": 3},  # source absente de Silver
    ],
)
def test_comptes_differents_pas_de_bascule(silver):
    old = "decisions_20260924_090000"
    client = FakeIndexClient(indexes=[old], alias=[old])
    result = rebuild(client, docs(), silver, MAPPING, NOW)
    assert not result.alias_switched
    assert result.reason.startswith("comptes différents")
    assert client.alias == [old]
    assert list(client.indexes) == [old]


def test_document_rejete_pas_de_bascule_meme_si_comptes_egaux():
    client = FakeIndexClient()
    client.reject = {"judilibre|c"}
    # Comptes Silver alignés sur les documents acceptés : seul le rejet bloque la bascule.
    result = rebuild(client, docs(), {"adlc-opendata": 2}, MAPPING, NOW)
    assert result.indexed_counts == {"adlc-opendata": 2}
    assert result.rejected_counts == Counter({"judilibre": 1})
    assert not result.alias_switched
    assert "judilibre : 0 attendue(s), 0 indexée(s), 1 rejetée(s)" in result.reason
    assert client.indexes == {}
    assert client.alias == []


def test_silver_vide_pas_de_bascule():
    old = "decisions_20260924_090000"
    client = FakeIndexClient(indexes=[old], alias=[old])
    result = rebuild(client, [], {}, MAPPING, NOW)
    assert not result.alias_switched
    assert result.reason == "Silver est vide"
    assert client.alias == [old]


@pytest.mark.parametrize("method", ["bulk_index", "refresh", "count_by_source", "switch_alias"])
def test_panne_avant_bascule_supprime_le_nouvel_index(method):
    old = "decisions_20260924_090000"
    client = FakeIndexClient(indexes=[old], alias=[old])
    client.fail_on = {method}
    with pytest.raises(RebuildError, match=f"panne {method}") as info:
        rebuild(client, docs(), SILVER, MAPPING, NOW)
    assert isinstance(info.value.__cause__, RuntimeError)
    assert info.value.result.index_name == NEW
    assert not info.value.result.alias_switched
    assert client.alias == [old]
    assert list(client.indexes) == [old]


def test_panne_de_suppression_ne_masque_pas_l_erreur_d_origine():
    client = FakeIndexClient()
    client.fail_on = {"refresh"}
    client.fail_delete = {NEW}
    with pytest.raises(RebuildError, match="panne refresh"):
        rebuild(client, docs(), SILVER, MAPPING, NOW)


def test_panne_a_la_creation_ne_supprime_rien():
    other = NEW  # index d'un autre run lancé dans la même seconde
    client = FakeIndexClient(indexes=[other])
    client.fail_on = {"create_index"}
    with pytest.raises(RebuildError):
        rebuild(client, docs(), SILVER, MAPPING, NOW)
    assert list(client.indexes) == [other]


def test_nettoyage_garde_le_nouveau_et_le_precedent():
    old = [
        "decisions_20260921_090000",
        "decisions_20260922_090000",
        "decisions_20260923_090000",
    ]
    previous = "decisions_20260924_090000"
    client = FakeIndexClient(indexes=[*old, previous, "decisions_backup"], alias=[previous])
    result = rebuild(client, docs(), SILVER, MAPPING, NOW)
    assert result.alias_switched
    assert result.deleted_indexes == old
    assert sorted(client.indexes) == ["decisions_20260924_090000", NEW, "decisions_backup"]
    assert result.warnings == []


def test_echec_du_nettoyage_en_avertissement_alias_bascule():
    stale = ["decisions_20260922_090000", "decisions_20260923_090000"]
    previous = "decisions_20260924_090000"
    client = FakeIndexClient(indexes=[*stale, previous], alias=[previous])
    client.fail_delete = {stale[0]}
    result = rebuild(client, docs(), SILVER, MAPPING, NOW)
    assert result.alias_switched
    assert result.deleted_indexes == [stale[1]]
    assert result.warnings == [
        "suppression de decisions_20260922_090000 impossible : "
        "suppression de decisions_20260922_090000 refusée"
    ]


def test_liste_des_index_impossible_en_avertissement():
    client = FakeIndexClient()
    client.fail_on = {"list_indexes"}
    result = rebuild(client, docs(), SILVER, MAPPING, NOW)
    assert result.alias_switched
    assert result.warnings == ["liste des index impossible : panne list_indexes"]


def test_alias_vers_plusieurs_index_erreur_avant_creation():
    a, b = "decisions_20260923_090000", "decisions_20260924_090000"
    client = FakeIndexClient(indexes=[a, b], alias=[a, b])
    with pytest.raises(RebuildError, match="plusieurs index"):
        rebuild(client, docs(), SILVER, MAPPING, NOW)
    assert sorted(client.indexes) == [a, b]


def test_index_nomme_decisions_erreur_avant_creation():
    client = FakeIndexClient(indexes=["decisions"])
    with pytest.raises(RebuildError, match="est un index et non un alias"):
        rebuild(client, docs(), SILVER, MAPPING, NOW)
    assert list(client.indexes) == ["decisions"]


@pytest.mark.parametrize(
    "silver, indexed, rejected, expected",
    [
        (SILVER, dict(SILVER), Counter(), True),
        (SILVER, None, Counter(), False),
        (SILVER, dict(SILVER), Counter({"judilibre": 1}), False),
        (SILVER, dict(SILVER), Counter({"judilibre": 0}), True),
        ({}, {}, Counter(), False),
        ({"judilibre": 0}, {}, Counter(), False),
    ],
)
def test_counts_match(silver, indexed, rejected, expected):
    assert counts_match(silver, indexed, rejected) is expected


def count_response(buckets, total, other=0, relation="eq"):
    return {
        "hits": {"total": {"value": total, "relation": relation}},
        "aggregations": {
            "by_source": {
                "sum_other_doc_count": other,
                "buckets": [{"key": k, "doc_count": n} for k, n in buckets.items()],
            }
        },
    }


def test_parse_count_response():
    assert parse_count_response(count_response(SILVER, 3)) == SILVER


@pytest.mark.parametrize(
    "response",
    [
        count_response({"adlc-opendata": 2}, 3, other=1),
        count_response(SILVER, 4),  # document sans source
        count_response(SILVER, 3, relation="gte"),
    ],
)
def test_parse_count_response_refuse_des_comptes_incomplets(response):
    with pytest.raises(ValueError, match="comptes par source incomplets"):
        parse_count_response(response)
