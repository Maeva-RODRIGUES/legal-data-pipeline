import pytest

from src.search.query import format_boost, number_query, search_body, title_query


def test_requete_numero_exacte():
    assert number_query("17-A-05") == {"term": {"decision_number": "17-A-05"}}


def test_requete_titre():
    assert title_query("Décision relative à l'acquisition", 3) == {
        "multi_match": {
            "query": "Décision relative à l'acquisition",
            "fields": ["title^3", "text"],
            "type": "best_fields",
        }
    }


@pytest.mark.parametrize(
    ("boost", "expected"), [(1, "title^1"), (3.0, "title^3"), (1.5, "title^1.5")]
)
def test_requete_titre_boost(boost, expected):
    assert title_query("titre", boost)["multi_match"]["fields"] == [expected, "text"]


def test_format_boost():
    assert format_boost(2.0) == "2"
    assert format_boost(0.25) == "0.25"


def test_corps_de_recherche():
    query = number_query("17-A-05")
    assert search_body(query) == {
        "query": query,
        "size": 10,
        "track_total_hits": True,
        "_source": False,
    }
