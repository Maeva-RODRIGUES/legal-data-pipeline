import pytest

from src.search.evaluate import (
    alias_index,
    check_alias_unchanged,
    evaluate,
    evaluate_all,
    parse_args,
    result_params,
    run_params,
)
from src.search.findability import Evaluation, Result, Target

INDEX = "decisions_20260925_162930"
ADLC = Target("adlc-opendata|a", "adlc-opendata", "17-A-05", "Avis sur l'eau", True, False, True)
EMPTY = Target("adlc-opendata|b", "adlc-opendata", "17-D-01", "Décision X", False, True, False)
JUDILIBRE = Target("judilibre|j", "judilibre", "26-83.146", None, True, False, False)


class FakeSearch:
    """Réponses programmées par identifiant attendu ; mémorise les corps de requête."""

    def __init__(self, ranking):
        self.ranking = ranking  # doc_id -> liste d'identifiants renvoyés
        self.bodies = []

    def __call__(self, body):
        self.bodies.append(body)
        query = body["query"]
        if "term" in query:
            key = query["term"]["decision_number"]
        else:
            key = query["multi_match"]["query"]
        ids = self.ranking.get(key, [])
        return {
            "hits": {
                "total": {"value": len(ids) + 5, "relation": "eq"},
                "hits": [{"_id": doc_id} for doc_id in ids],
            }
        }


class FakeAliasClient:
    def __init__(self, *targets):
        self.targets = list(targets)

    def is_index(self, name):
        return False

    def alias_targets(self, alias):
        return list(self.targets)


# Arguments ------------------------------------------------------------------


def test_boost_par_defaut():
    assert parse_args([]).title_boost == [3.0]


def test_plusieurs_boosts_doublons_retires():
    assert parse_args(["--title-boost", "1", "2", "3", "2"]).title_boost == [1.0, 2.0, 3.0]


def test_boost_decimal():
    assert parse_args(["--title-boost", "1.5", "0.25"]).title_boost == [1.5, 0.25]


@pytest.mark.parametrize("boost", ["0", "-1", "1000", "1.555", "abc", "nan", "inf"])
def test_boost_invalide(boost, capsys):
    with pytest.raises(SystemExit):
        parse_args(["--title-boost", boost])
    assert "boost invalide" in capsys.readouterr().err


# Évaluation -----------------------------------------------------------------


def test_mode_number():
    search = FakeSearch({"17-A-05": ["adlc-opendata|z", "adlc-opendata|a"], "26-83.146": []})
    evaluation = evaluate(search, [ADLC, JUDILIBRE], "number", 3.0)
    assert evaluation.title_boost is None
    assert evaluation.results == [Result(ADLC, 2, 7), Result(JUDILIBRE, None, 5)]
    assert search.bodies[0] == {
        "query": {"term": {"decision_number": "17-A-05"}},
        "size": 10,
        "track_total_hits": True,
        "_source": False,
    }


def test_mode_title_exclut_judilibre():
    search = FakeSearch({"Avis sur l'eau": ["adlc-opendata|a"]})
    evaluation = evaluate(search, [ADLC, EMPTY, JUDILIBRE], "title", 1.5)
    assert evaluation.title_boost == 1.5
    assert evaluation.results == [Result(ADLC, 1, 6), Result(EMPTY, None, 5)]
    assert search.bodies[0]["query"] == {
        "multi_match": {
            "query": "Avis sur l'eau",
            "fields": ["title^1.5", "text"],
            "type": "best_fields",
        }
    }


def test_number_une_fois_title_par_boost():
    evaluations = evaluate_all(FakeSearch({}), [ADLC, JUDILIBRE], [1.0, 2.0, 3.0])
    assert [(e.mode, e.title_boost) for e in evaluations] == [
        ("number", None),
        ("title", 1.0),
        ("title", 2.0),
        ("title", 3.0),
    ]
    assert [len(e.results) for e in evaluations] == [2, 1, 1, 1]


# Alias ----------------------------------------------------------------------


def test_alias_resolu():
    assert alias_index(FakeAliasClient(INDEX)) == INDEX


def test_alias_absent():
    with pytest.raises(ValueError, match="n'existe pas"):
        alias_index(FakeAliasClient())


def test_alias_plusieurs_cibles():
    with pytest.raises(ValueError, match="plusieurs index"):
        alias_index(FakeAliasClient(INDEX, "decisions_20260926_090000"))


def test_alias_inchange():
    check_alias_unchanged(FakeAliasClient(INDEX), INDEX)


def test_alias_bascule_pendant_l_evaluation():
    with pytest.raises(RuntimeError, match="a basculé"):
        check_alias_unchanged(FakeAliasClient("decisions_20260926_090000"), INDEX)


# Paramètres d'insertion -----------------------------------------------------


def test_parametres_number():
    evaluation = Evaluation("number", None, [Result(ADLC, 1, 2), Result(JUDILIBRE, None, 0)])
    assert run_params(7, INDEX, evaluation) == (7, INDEX, "number", None, 2, 0.5, 0.5, 0.5)
    assert result_params(11, 7, evaluation) == [
        (11, 7, "number", None, "adlc-opendata|a", True, False, True, 1, 2),
        (11, 7, "number", None, "judilibre|j", True, False, False, None, 0),
    ]


def test_parametres_title():
    evaluation = Evaluation("title", 2.5, [Result(EMPTY, 4, 30)])
    assert run_params(7, INDEX, evaluation) == (7, INDEX, "title", 2.5, 1, 0.0, 1.0, 0.25)
    assert result_params(12, 7, evaluation) == [
        (12, 7, "title", 2.5, "adlc-opendata|b", False, True, False, 4, 30),
    ]


def test_parametres_echantillon_vide():
    evaluation = Evaluation("title", 3.0, [])
    assert run_params(7, INDEX, evaluation) == (7, INDEX, "title", 3.0, 0, None, None, None)
    assert result_params(12, 7, evaluation) == []
