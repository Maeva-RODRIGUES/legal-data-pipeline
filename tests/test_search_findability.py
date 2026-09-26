import pytest

from src.search.findability import (
    Evaluation,
    Metrics,
    Result,
    Target,
    ambiguous,
    build_targets,
    compute_metrics,
    extract_rank,
    format_report,
    group_metrics,
    number_key,
    targets_for,
    title_key,
    truncate,
)

INDEX = "decisions_20260925_162930"


def target(doc_id="adlc-opendata|a", **overrides):
    fields = {
        "doc_id": doc_id,
        "source": doc_id.partition("|")[0],
        "decision_number": "17-D-01",
        "title": "Décision relative à des pratiques",
        "has_text": True,
        "ambiguous_title": False,
        "ambiguous_number": False,
    }
    return Target(**(fields | overrides))


def response(ids, total=None, relation="eq"):
    return {
        "hits": {
            "total": {"value": len(ids) if total is None else total, "relation": relation},
            "hits": [{"_id": doc_id, "_score": 1.0} for doc_id in ids],
        }
    }


# Métriques ------------------------------------------------------------------


def test_metriques_trouvee_au_rang_1():
    assert compute_metrics([1]) == Metrics(1, 1.0, 1.0, 1.0)


def test_metriques_trouvee_au_rang_3():
    assert compute_metrics([3]) == Metrics(1, 0.0, 1.0, pytest.approx(1 / 3))


def test_metriques_absente():
    assert compute_metrics([None]) == Metrics(1, 0.0, 0.0, 0.0)


def test_metriques_melange():
    metrics = compute_metrics([1, 3, None, 2])
    assert metrics.sample_size == 4
    assert metrics.hit_at_1 == 0.25
    assert metrics.hit_at_10 == 0.75
    assert metrics.mrr == pytest.approx((1 + 1 / 3 + 0 + 1 / 2) / 4)


def test_metriques_echantillon_vide():
    assert compute_metrics([]) == Metrics(0, None, None, None)


# Ambiguïtés -----------------------------------------------------------------


def test_titre_partage_ambigu():
    assert ambiguous(["A", "A", "B"]) == {"A"}


def test_titre_egal_apres_trim_ambigu():
    assert ambiguous(title_key(t) for t in ["Avis 1 ", " Avis 1"]) == {"Avis 1"}


def test_apostrophes_ramenees_a_la_meme_cle():
    assert title_key("relative à l’acquisition") == title_key("relative à l'acquisition")
    assert ambiguous(title_key(t) for t in ["l'avis", "l’avis"]) == {"l'avis"}


def test_titre_vide_ou_null_ignore():
    assert title_key("   ") is None
    assert title_key(None) is None
    assert ambiguous(title_key(t) for t in [None, None, "", "  "]) == set()


def test_numero_partage_ambigu():
    assert ambiguous(number_key(n) for n in ["17-A-05", "17-A-05", "17-D-01"]) == {"17-a-05"}


def test_numero_casse_differente_ambigu():
    assert ambiguous(number_key(n) for n in ["17-a-05", "17-A-05"]) == {"17-a-05"}


def test_numero_unique_non_ambigu():
    assert ambiguous(number_key(n) for n in ["17-A-05", "17-D-01", None]) == set()


def silver_row(source, external_id, number, title, has_text=True):
    return {
        "source": source,
        "external_id": external_id,
        "decision_number": number,
        "title": title,
        "has_text": has_text,
    }


def test_ambiguites_calculees_sur_tout_silver():
    hors_echantillon = silver_row("adlc-opendata", "z", "17-A-05", "Avis sur l’eau")
    echantillon = silver_row("adlc-opendata", "a", "17-A-05", "Avis sur l'eau ", has_text=False)
    unique = silver_row("adlc-opendata", "b", "17-D-01", "Décision unique")
    targets = build_targets([hors_echantillon, echantillon, unique], [echantillon, unique])
    assert targets == [
        Target("adlc-opendata|a", "adlc-opendata", "17-A-05", "Avis sur l'eau ", False, True, True),
        Target(
            "adlc-opendata|b", "adlc-opendata", "17-D-01", "Décision unique", True, False, False
        ),
    ]


def test_cibles_par_mode():
    judilibre = target("judilibre|j", title=None, decision_number="26-83.146")
    sans_numero = target("adlc-opendata|n", decision_number=None)
    sans_titre = target("adlc-opendata|t", title="  ")
    adlc = target("adlc-opendata|a")
    targets = [judilibre, sans_numero, sans_titre, adlc]
    assert targets_for(targets, "number") == [judilibre, sans_titre, adlc]
    assert targets_for(targets, "title") == [sans_numero, adlc]


def test_mode_inconnu():
    with pytest.raises(ValueError, match="mode inconnu"):
        targets_for([], "texte")


# Rang -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ids", "expected"),
    [
        (["x|a", "x|b", "x|c"], 1),
        (["x|b", "x|c", "x|a"], 3),
        (["x|b", "x|c"], None),
        ([], None),
    ],
)
def test_rang(ids, expected):
    assert extract_rank(response(ids, total=42), "x|a") == (expected, 42)


def test_rang_au_dela_du_top_10_ignore():
    ids = [f"x|{i}" for i in range(11)] + ["x|a"]
    assert extract_rank(response(ids), "x|a") == (None, 12)


def test_total_inexact_refuse():
    with pytest.raises(ValueError, match="inexact"):
        extract_rank(response(["x|a"], total=10000, relation="gte"), "x|a")


# Groupes et rapport ---------------------------------------------------------


def test_groupe_vide_present():
    groups = group_metrics([Result(target(), 1, 3)])
    assert groups[("has_text", True)] == Metrics(1, 1.0, 1.0, 1.0)
    assert groups[("has_text", False)] == Metrics(0, None, None, None)
    assert groups[("ambiguous_number", True)].sample_size == 0
    assert len(groups) == 6


def test_troncature_du_titre():
    assert truncate("court") == "court"
    assert truncate("x" * 100, width=10) == "x" * 9 + "…"


def test_rapport():
    found = target("adlc-opendata|a", decision_number="17-D-01", title="Titre trouvé")
    missed = target(
        "adlc-opendata|b", decision_number="05-D-12", title="Titre raté", has_text=False
    )
    evaluations = [
        Evaluation("number", None, [Result(found, 1, 1), Result(missed, 1, 1)]),
        Evaluation("title", 1.0, [Result(found, 1, 30), Result(missed, None, 30)]),
        Evaluation("title", 2.5, [Result(found, 2, 30), Result(missed, 7, 30)]),
    ]
    assert format_report(INDEX, evaluations).splitlines() == [
        f"Index {INDEX} (alias decisions), 2 décision(s) évaluée(s)",
        "number : 2 cherchée(s) ; hit@1 = 1,000 ; hit@10 = 1,000 ; MRR = 1,000",
        "  texte oui : 1 ; hit@1 = 1,000 ; hit@10 = 1,000 ; MRR = 1,000",
        "  texte non : 1 ; hit@1 = 1,000 ; hit@10 = 1,000 ; MRR = 1,000",
        "  titre ambigu oui : 0 ; hit@1 = - ; hit@10 = - ; MRR = -",
        "  titre ambigu non : 2 ; hit@1 = 1,000 ; hit@10 = 1,000 ; MRR = 1,000",
        "  numéro ambigu oui : 0 ; hit@1 = - ; hit@10 = - ; MRR = -",
        "  numéro ambigu non : 2 ; hit@1 = 1,000 ; hit@10 = 1,000 ; MRR = 1,000",
        "title (boost 1) : 2 cherchée(s) ; hit@1 = 0,500 ; hit@10 = 0,500 ; MRR = 0,500",
        "  texte oui : 1 ; hit@1 = 1,000 ; hit@10 = 1,000 ; MRR = 1,000",
        "  texte non : 1 ; hit@1 = 0,000 ; hit@10 = 0,000 ; MRR = 0,000",
        "  titre ambigu oui : 0 ; hit@1 = - ; hit@10 = - ; MRR = -",
        "  titre ambigu non : 2 ; hit@1 = 0,500 ; hit@10 = 0,500 ; MRR = 0,500",
        "  numéro ambigu oui : 0 ; hit@1 = - ; hit@10 = - ; MRR = -",
        "  numéro ambigu non : 2 ; hit@1 = 0,500 ; hit@10 = 0,500 ; MRR = 0,500",
        "title (boost 2.5) : 2 cherchée(s) ; hit@1 = 0,000 ; hit@10 = 1,000 ; MRR = 0,321",
        "  texte oui : 1 ; hit@1 = 0,000 ; hit@10 = 1,000 ; MRR = 0,500",
        "  texte non : 1 ; hit@1 = 0,000 ; hit@10 = 1,000 ; MRR = 0,143",
        "  titre ambigu oui : 0 ; hit@1 = - ; hit@10 = - ; MRR = -",
        "  titre ambigu non : 2 ; hit@1 = 0,000 ; hit@10 = 1,000 ; MRR = 0,321",
        "  numéro ambigu oui : 0 ; hit@1 = - ; hit@10 = - ; MRR = -",
        "  numéro ambigu non : 2 ; hit@1 = 0,000 ; hit@10 = 1,000 ; MRR = 0,321",
        "Décisions absentes du top 10 par numéro : aucune",
        "Décisions absentes du top 10 par titre (1) :",
        "  numéro   title (boost 1)  title (boost 2.5)  titre",
        "  05-D-12  absente          7                  Titre raté",
    ]
