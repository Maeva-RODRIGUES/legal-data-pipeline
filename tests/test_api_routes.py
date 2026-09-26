from datetime import UTC, date, datetime
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from src.api.backends import (
    DatabaseUnavailable,
    ElasticsearchUnavailable,
    SearchIndexUnavailable,
)
from src.api.main import app, get_database, get_search
from src.api.models import CheckStatus, DecisionType, Source
from src.api.search import HIGHLIGHT
from src.quality.run import STATUS_ORDER
from src.search.query import DEFAULT_TITLE_BOOST, number_query, title_query
from src.silver import adlc_opendata, judilibre

NOW = datetime(2026, 9, 26, 13, 54, tzinfo=UTC)
ADLC_ID = (
    "https://www.autoritedelaconcurrence.fr/fr/avis/"
    "concernant-leffacement-de-consommation-dans-le-secteur-de-lelectricite"
)
JUDILIBRE_ID = "6a6c3834d6da041962933bac"
HIT = {
    "_score": 11.95,
    "_source": {
        "source": "adlc-opendata",
        "external_id": ADLC_ID,
        "decision_number": "12-A-19",
        "issuer": "Autorité de la concurrence",
        "decision_type": "avis",
        "decision_date": "2012-07-26",
        "title": "concernant l’effacement de consommation dans le secteur de l’électricité",
        "sectors": ["Energie / Environnement"],
        "url": ADLC_ID,
        "has_text": True,
    },
    "highlight": {"title": ["dans le secteur de <mark>l’électricité</mark>"]},
}
JUDILIBRE_ROW = {
    "source": "judilibre",
    "external_id": JUDILIBRE_ID,
    "decision_number": "26-83.146",
    "issuer": "Cour de cassation",
    "decision_type": None,
    "decision_date": date(2026, 7, 29),
    "title": None,
    "text": "LA COUR DE CASSATION, CHAMBRE CRIMINELLE, a rendu l'arrêt suivant",
    "has_text": True,
    "sectors": [],
    "url": f"https://www.courdecassation.fr/decision/{JUDILIBRE_ID}",
    "attributes": {"ecli": "ECLI:FR:CCASS:2026:CR01159", "chamber": "cr"},
    "built_at": NOW,
}
RUN_ROW = {
    "run_id": 33,
    "source": "quality",
    "date_type": "checks",
    "date_start": date(2026, 9, 26),
    "date_end": date(2026, 9, 26),
    "started_at": NOW,
    "finished_at": NOW,
    "status": "success",
    "nb_fetched": 24,
    "nb_new": 0,
    "nb_changed": 0,
    "error": None,
}


def check(status, name="empty_text"):
    return {
        "check_name": name,
        "dimension": "completeness",
        "severity": "warning",
        "source": "adlc-opendata",
        "value": 30,
        "expected": "<= 30",
        "status": status,
        "error": None,
        "checked_at": NOW,
    }


QUALITY = {
    "run": {"run_id": 35, "started_at": NOW, "finished_at": NOW, "status": "success"},
    "verdict": "success",
    "counts": {"fail": 1, "no_data": 0, "query_error": 0, "unchecked": 0, "pass": 1},
    "results": [check("fail", "a"), check("pass", "b")],
}
OK_PG = {"status": "ok", "latency_ms": 3, "error": None}
OK_ES = {"status": "ok", "latency_ms": 5, "index": "decisions_20260926_135231", "error": None}


class FakeSearch:
    def __init__(self, hits=(), total=None, error=None, health=OK_ES):
        self.hits = list(hits)
        self.total = len(self.hits) if total is None else total
        self.error = error
        self.status = health
        self.bodies = []

    def search(self, body):
        self.bodies.append(body)
        if self.error:
            raise self.error
        return {"hits": {"total": {"value": self.total, "relation": "eq"}, "hits": self.hits}}

    def health(self):
        return dict(self.status)


class FakeDatabase:
    def __init__(self, decisions=None, runs=(), quality=QUALITY, error=None, health=OK_PG):
        self.decisions = decisions or {}
        self.run_rows = list(runs)
        self.quality = quality
        self.error = error
        self.status = health
        self.calls = []

    def fail(self):
        if self.error:
            raise self.error

    def decision(self, source, external_id):
        self.calls.append(("decision", source, external_id))
        self.fail()
        return self.decisions.get((source, external_id))

    def runs(self, sources, status, limit):
        self.calls.append(("runs", sources, status, limit))
        self.fail()
        return self.run_rows

    def latest_quality(self):
        self.fail()
        return None if self.quality is None else {**self.quality}

    def health(self):
        return dict(self.status)


@pytest.fixture
def fakes():
    search, database = FakeSearch(hits=[HIT], total=457), FakeDatabase()
    app.dependency_overrides[get_search] = lambda: search
    app.dependency_overrides[get_database] = lambda: database
    yield search, database
    app.dependency_overrides.clear()


@pytest.fixture
def client(fakes):
    return TestClient(app, raise_server_exceptions=False)  # sans lifespan : aucun vrai client


def use(search=None, database=None):
    if search is not None:
        app.dependency_overrides[get_search] = lambda: search
    if database is not None:
        app.dependency_overrides[get_database] = lambda: database


def assert_error(response, status, code):
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    return body["error"]


# Vocabulaires -------------------------------------------------------------------


def test_vocabulaires_alignes_sur_silver_et_la_qualite():
    assert set(Source.__args__) == {judilibre.SOURCE, adlc_opendata.SOURCE}
    assert set(DecisionType.__args__) == set(adlc_opendata.MAIN_TYPES.values())
    assert set(CheckStatus.__args__) == set(STATUS_ORDER)


# /search ------------------------------------------------------------------------


def test_recherche_meme_requete_que_query_py(client, fakes):
    response = client.get("/search", params={"q": "  electricite "})
    assert response.status_code == 200
    body = fakes[0].bodies[0]
    assert body["query"] == title_query("electricite", DEFAULT_TITLE_BOOST)
    assert body["highlight"] == HIGHLIGHT
    assert (body["from"], body["size"], body["track_total_hits"]) == (0, 10, True)


def test_recherche_reponse(client):
    body = client.get("/search", params={"q": "electricite"}).json()
    assert body["query"] == "electricite"
    assert body["number"] is None
    assert body["total"] == 457
    assert (body["page"], body["page_size"]) == (1, 10)
    assert body["filters"] == {
        "source": [],
        "decision_type": [],
        "date_from": None,
        "date_to": None,
        "sector": [],
    }
    [hit] = body["results"]
    assert hit["decision_date"] == "2012-07-26"
    assert hit["display_title"] == HIT["_source"]["title"]
    assert hit["highlights"] == {
        "title": ["dans le secteur de <mark>l’électricité</mark>"],
        "text": [],
    }
    assert hit["detail_path"] == f"/decisions/adlc-opendata?id={quote(ADLC_ID, safe='')}"


def test_recherche_avec_filtres_et_pagination(client, fakes):
    response = client.get(
        "/search",
        params=[
            ("q", "electricite"),
            ("source", "adlc-opendata"),
            ("decision_type", "avis"),
            ("decision_type", "decision"),
            ("date_from", "2010-01-01"),
            ("date_to", "2015-12-31"),
            ("sector", "Energie / Environnement"),
            ("page", "3"),
            ("page_size", "20"),
        ],
    )
    assert response.status_code == 200
    body = fakes[0].bodies[0]
    assert body["query"]["bool"]["must"] == [title_query("electricite", DEFAULT_TITLE_BOOST)]
    assert body["query"]["bool"]["filter"] == [
        {"terms": {"source": ["adlc-opendata"]}},
        {"terms": {"decision_type": ["avis", "decision"]}},
        {"terms": {"sectors": ["Energie / Environnement"]}},
        {"range": {"decision_date": {"gte": "2010-01-01", "lte": "2015-12-31"}}},
    ]
    assert (body["from"], body["size"]) == (40, 20)
    assert response.json()["filters"]["decision_type"] == ["avis", "decision"]


def test_recherche_par_numero_sans_surlignage(client, fakes):
    response = client.get("/search", params={"number": "12-A-19", "source": "adlc-opendata"})
    assert response.status_code == 200
    body = fakes[0].bodies[0]
    assert body["query"]["bool"]["must"] == [number_query("12-A-19")]
    assert "highlight" not in body
    assert response.json()["query"] is None
    assert response.json()["number"] == "12-A-19"


def test_recherche_par_numero_sans_filtre(client, fakes):
    client.get("/search", params={"number": "26-83.146"})
    assert fakes[0].bodies[0]["query"] == number_query("26-83.146")


def test_resultat_judilibre_titre_de_citation(client):
    judilibre_hit = {
        "_score": 2.0,
        "_source": {
            **{k: JUDILIBRE_ROW[k] for k in ("source", "external_id", "decision_number")},
            "issuer": "Cour de cassation",
            "decision_type": None,
            "decision_date": "2026-07-29",
            "title": None,
            "sectors": [],
            "url": JUDILIBRE_ROW["url"],
            "has_text": True,
        },
    }
    use(search=FakeSearch(hits=[judilibre_hit]))
    [hit] = client.get("/search", params={"number": "26-83.146"}).json()["results"]
    assert hit["display_title"] == "Cour de cassation, 29 juillet 2026, n° 26-83.146"
    assert hit["title"] is None


def test_page_au_dela_des_resultats(client):
    use(search=FakeSearch(hits=[], total=457))
    body = client.get("/search", params={"q": "electricite", "page": "100"}).json()
    assert body["results"] == []
    assert body["total"] == 457


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({}, None),
        ({"q": "electricite", "number": "12-A-19"}, None),
        ({"q": "   "}, "q"),
        ({"number": " "}, "number"),
        ({"q": "x" * 501}, "q"),
        ({"q": "a", "source": "cour-des-comptes"}, "source.0"),
        ({"q": "a", "decision_type": "arret"}, "decision_type.0"),
        ({"q": "a", "date_from": "2026-13-01"}, "date_from"),
        ({"q": "a", "date_from": "2020-01-02", "date_to": "2020-01-01"}, "date_from"),
        ({"q": "a", "page": "0"}, "page"),
        ({"q": "a", "page_size": "51"}, "page_size"),
        ({"q": "a", "page": "201", "page_size": "50"}, "page"),
    ],
)
def test_recherche_parametre_invalide(client, fakes, params, field):
    error = assert_error(client.get("/search", params=params), 422, "invalid_parameter")
    assert [detail["field"] for detail in error["details"]] == [field]
    assert fakes[0].bodies == []  # rien n'est envoyé à Elasticsearch


def test_derniere_page_autorisee(client):
    assert client.get("/search", params={"q": "a", "page": "200", "page_size": "50"}).is_success


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ElasticsearchUnavailable(), "elasticsearch_unavailable"),
        (SearchIndexUnavailable(), "search_index_unavailable"),
    ],
)
def test_recherche_elasticsearch_indisponible(client, error, code):
    use(search=FakeSearch(error=error))
    assert_error(client.get("/search", params={"q": "electricite"}), 503, code)


def test_recherche_sans_postgresql(client):
    use(database=FakeDatabase(error=DatabaseUnavailable()))
    assert client.get("/search", params={"q": "electricite"}).status_code == 200


def test_erreur_imprevue_500_generique(client):
    use(search=FakeSearch(error=RuntimeError("secret detail")))
    error = assert_error(client.get("/search", params={"q": "a"}), 500, "internal_error")
    assert "secret" not in error["message"]


# /decisions ---------------------------------------------------------------------


def test_detail_judilibre(client):
    database = FakeDatabase(decisions={("judilibre", JUDILIBRE_ID): JUDILIBRE_ROW})
    use(database=database)
    response = client.get("/decisions/judilibre", params={"id": JUDILIBRE_ID})
    assert response.status_code == 200
    body = response.json()
    assert body["display_title"] == "Cour de cassation, 29 juillet 2026, n° 26-83.146"
    assert body["title"] is None
    assert body["text"] == JUDILIBRE_ROW["text"]
    assert body["attributes"]["ecli"] == "ECLI:FR:CCASS:2026:CR01159"
    assert body["decision_date"] == "2026-07-29"


def test_detail_adlc_identifiant_url_via_detail_path(client):
    row = {
        **JUDILIBRE_ROW,
        "source": "adlc-opendata",
        "external_id": ADLC_ID,
        "title": "concernant l’effacement de consommation dans le secteur de l’électricité",
    }
    database = FakeDatabase(decisions={("adlc-opendata", ADLC_ID): row})
    use(database=database)
    [hit] = client.get("/search", params={"q": "electricite"}).json()["results"]
    response = client.get(hit["detail_path"])
    assert response.status_code == 200
    assert database.calls == [("decision", "adlc-opendata", ADLC_ID)]
    assert response.json()["display_title"] == row["title"]


def test_detail_introuvable(client):
    response = client.get("/decisions/judilibre", params={"id": "absent"})
    assert_error(response, 404, "decision_not_found")


@pytest.mark.parametrize(
    ("url", "field"),
    [
        ("/decisions/judilibre", "id"),
        ("/decisions/judilibre?id=", "id"),
        ("/decisions/cour-des-comptes?id=x", "source"),
    ],
)
def test_detail_parametre_invalide(client, url, field):
    error = assert_error(client.get(url), 422, "invalid_parameter")
    assert [detail["field"] for detail in error["details"]] == [field]


def test_detail_postgresql_indisponible(client):
    use(database=FakeDatabase(error=DatabaseUnavailable()))
    response = client.get("/decisions/judilibre", params={"id": JUDILIBRE_ID})
    assert_error(response, 503, "database_unavailable")


def test_detail_sans_elasticsearch(client):
    database = FakeDatabase(decisions={("judilibre", JUDILIBRE_ID): JUDILIBRE_ROW})
    use(search=FakeSearch(error=ElasticsearchUnavailable()), database=database)
    assert client.get("/decisions/judilibre", params={"id": JUDILIBRE_ID}).status_code == 200


# /runs --------------------------------------------------------------------------


def test_runs(client, fakes):
    use(database=(database := FakeDatabase(runs=[RUN_ROW])))
    response = client.get("/runs")
    assert response.status_code == 200
    [run] = response.json()["runs"]
    assert run["run_id"] == 33
    assert run["started_at"] == "2026-09-26T13:54:00Z"
    assert database.calls == [("runs", [], None, 20)]


def test_runs_filtres(client):
    use(database=(database := FakeDatabase()))
    params = [("source", "search"), ("source", "quality"), ("status", "failed"), ("limit", "5")]
    assert client.get("/runs", params=params).json() == {"runs": []}
    assert database.calls == [("runs", ["search", "quality"], "failed", 5)]


@pytest.mark.parametrize(
    "params", [{"limit": "0"}, {"limit": "101"}, {"status": "done"}, {"limit": "x"}]
)
def test_runs_parametre_invalide(client, params):
    assert_error(client.get("/runs", params=params), 422, "invalid_parameter")


def test_runs_postgresql_indisponible(client):
    use(database=FakeDatabase(error=DatabaseUnavailable()))
    assert_error(client.get("/runs"), 503, "database_unavailable")


# /quality/latest ----------------------------------------------------------------


def test_qualite(client):
    body = client.get("/quality/latest").json()
    assert body["run"]["run_id"] == 35
    assert body["verdict"] == "success"
    assert body["counts"]["fail"] == 1
    assert [r["check_name"] for r in body["results"]] == ["a", "b"]


def test_qualite_filtre_les_resultats_pas_le_verdict(client):
    body = client.get("/quality/latest", params={"status": "pass"}).json()
    assert [r["status"] for r in body["results"]] == ["pass"]
    assert body["counts"]["fail"] == 1
    assert body["verdict"] == "success"


def test_qualite_verdict_echec(client):
    use(database=FakeDatabase(quality={**QUALITY, "verdict": "failure"}))
    assert client.get("/quality/latest").json()["verdict"] == "failure"


def test_qualite_sans_resultat(client):
    use(database=FakeDatabase(quality=None))
    assert_error(client.get("/quality/latest"), 404, "quality_results_not_found")


def test_qualite_statut_invalide(client):
    response = client.get("/quality/latest", params={"status": "ok"})
    assert_error(response, 422, "invalid_parameter")


def test_qualite_postgresql_indisponible(client):
    use(database=FakeDatabase(error=DatabaseUnavailable()))
    assert_error(client.get("/quality/latest"), 503, "database_unavailable")


# /health ------------------------------------------------------------------------


def test_sante_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "services": {"postgres": OK_PG, "elasticsearch": OK_ES},
    }


def test_sante_postgresql_en_panne(client):
    down = {"status": "error", "latency_ms": 3000, "error": "ConnectionTimeout: expired"}
    use(database=FakeDatabase(health=down))
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["services"]["postgres"] == down
    assert response.json()["services"]["elasticsearch"]["status"] == "ok"


def test_sante_elasticsearch_sans_alias(client):
    down = {"status": "error", "latency_ms": 4, "index": None, "error": "alias not found"}
    use(search=FakeSearch(health=down))
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["services"]["elasticsearch"] == down
    assert response.json()["services"]["postgres"]["status"] == "ok"


# Divers -------------------------------------------------------------------------


def test_route_inconnue(client):
    assert_error(client.get("/inconnue"), 404, "not_found")


def test_methode_non_autorisee(client):
    assert_error(client.post("/search"), 405, "method_not_allowed")


def test_documentation_generee(client):
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths) == {"/search", "/decisions/{source}", "/runs", "/quality/latest", "/health"}
    assert all(set(operation) == {"get"} for operation in paths.values())  # lecture seule
    assert "ErrorResponse" in str(paths["/search"]["get"]["responses"]["422"])
