from datetime import date

from src.api.search import (
    HIGHLIGHT,
    SOURCE_FIELDS,
    Filters,
    build_body,
    build_query,
    detail_path,
    format_hit,
)
from src.search.query import DEFAULT_TITLE_BOOST, number_query, search_body, title_query

ADLC_ID = (
    "https://www.autoritedelaconcurrence.fr/fr/avis/"
    "concernant-leffacement-de-consommation-dans-le-secteur-de-lelectricite"
)

# Requête ------------------------------------------------------------------------


def test_sans_filtre_requete_identique_a_l_evaluation():
    assert build_query("electricite", None, Filters()) == title_query(
        "electricite", DEFAULT_TITLE_BOOST
    )


def test_par_numero_requete_identique_a_query_py():
    assert build_query(None, "12-A-19", Filters()) == number_query("12-A-19")


def test_filtres_autour_de_la_requete_evaluee():
    filters = Filters(
        source=["adlc-opendata"],
        decision_type=["avis", "decision"],
        date_from=date(2010, 1, 1),
        date_to=date(2015, 12, 31),
        sector=["Energie / Environnement"],
    )
    query = build_query("electricite", None, filters)
    assert query["bool"]["must"] == [title_query("electricite", DEFAULT_TITLE_BOOST)]
    assert query["bool"]["filter"] == [
        {"terms": {"source": ["adlc-opendata"]}},
        {"terms": {"decision_type": ["avis", "decision"]}},
        {"terms": {"sectors": ["Energie / Environnement"]}},
        {"range": {"decision_date": {"gte": "2010-01-01", "lte": "2015-12-31"}}},
    ]
    assert set(query["bool"]) == {"must", "filter"}


def test_une_seule_borne_de_date():
    query = build_query(None, "12-A-19", Filters(date_to=date(2015, 12, 31)))
    assert query["bool"]["must"] == [number_query("12-A-19")]
    assert query["bool"]["filter"] == [{"range": {"decision_date": {"lte": "2015-12-31"}}}]


def test_corps_complete_search_body():
    body = build_body("electricite", None, Filters(), page=3, page_size=20)
    expected = search_body(title_query("electricite", DEFAULT_TITLE_BOOST))
    assert body["query"] == expected["query"]
    assert body["track_total_hits"] is True
    assert body["from"] == 40
    assert body["size"] == 20
    assert body["_source"] == SOURCE_FIELDS
    assert "text" not in body["_source"] and "attributes" not in body["_source"]
    assert body["highlight"] == HIGHLIGHT


def test_pas_de_surlignage_par_numero():
    body = build_body(None, "12-A-19", Filters(), page=1, page_size=10)
    assert body["query"] == number_query("12-A-19")
    assert body["from"] == 0
    assert "highlight" not in body


def test_surlignage_html_echappe():
    assert HIGHLIGHT["encoder"] == "html"
    assert HIGHLIGHT["fields"]["title"] == {"number_of_fragments": 0}
    assert HIGHLIGHT["fields"]["text"] == {"fragment_size": 150, "number_of_fragments": 3}


# Résultats ----------------------------------------------------------------------


def test_chemin_de_detail_encode():
    assert detail_path("adlc-opendata", ADLC_ID) == (
        "/decisions/adlc-opendata?id=https%3A%2F%2Fwww.autoritedelaconcurrence.fr%2Ffr%2Favis%2F"
        "concernant-leffacement-de-consommation-dans-le-secteur-de-lelectricite"
    )
    assert detail_path("judilibre", "a b&c") == "/decisions/judilibre?id=a%20b%26c"


def test_resultat_adlc():
    hit = {
        "_id": f"adlc-opendata|{ADLC_ID}",
        "_score": 11.95,
        "_source": {
            "source": "adlc-opendata",
            "external_id": ADLC_ID,
            "decision_number": "12-A-19",
            "issuer": "Autorité de la concurrence",
            "decision_type": "avis",
            "decision_date": "2012-07-26",
            "title": "concernant l’effacement … de l’électricité",
            "sectors": ["Energie / Environnement"],
            "url": ADLC_ID,
            "has_text": True,
        },
        "highlight": {"text": ["<mark>d&#x27;électricité</mark>"]},
    }
    result = format_hit(hit)
    assert result["decision_date"] == date(2012, 7, 26)
    assert result["display_title"] == "concernant l’effacement … de l’électricité"
    assert result["score"] == 11.95
    assert result["highlights"] == {"title": [], "text": ["<mark>d&#x27;électricité</mark>"]}
    assert result["detail_path"] == detail_path("adlc-opendata", ADLC_ID)


def test_resultat_judilibre_sans_titre_ni_secteur():
    hit = {
        "_score": 3.2,
        "_source": {
            "source": "judilibre",
            "external_id": "6a6c3834d6da041962933bac",
            "decision_number": "26-83.146",
            "issuer": "Cour de cassation",
            "decision_type": None,
            "decision_date": "2026-07-29",
            "title": None,
            "sectors": None,
            "url": "https://www.courdecassation.fr/decision/6a6c3834d6da041962933bac",
            "has_text": True,
        },
    }
    result = format_hit(hit)
    assert result["title"] is None
    assert result["display_title"] == "Cour de cassation, 29 juillet 2026, n° 26-83.146"
    assert result["sectors"] == []
    assert result["highlights"] == {"title": [], "text": []}
