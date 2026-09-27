from datetime import UTC, datetime
from decimal import Decimal

import elastic_transport
import elasticsearch
import psycopg
import pytest

from src.api import backends
from src.api.backends import (
    ConfigError,
    DatabaseUnavailable,
    ElasticsearchBackend,
    ElasticsearchUnavailable,
    PostgresDatabase,
    SearchIndexUnavailable,
    load_settings,
    number,
    quality_report,
    redact,
)

ES_URL = "http://elastic:s3cret@127.0.0.1:9200"
PG_URL = "postgresql://legal:s3cret@127.0.0.1:5432/legal"
NOW = datetime(2026, 9, 26, 13, 54, tzinfo=UTC)


def api_error(cls, status):
    meta = elastic_transport.ApiResponseMeta(
        status=status,
        http_version="1.1",
        headers=elastic_transport.HttpHeaders(),
        duration=0.0,
        node=elastic_transport.NodeConfig("http", "127.0.0.1", 9200),
    )
    return cls("error", meta, {})


class FakeIndices:
    def __init__(self, aliases):
        self.aliases = aliases

    def get_alias(self, name):
        if self.aliases is None:
            raise api_error(elasticsearch.NotFoundError, 404)
        return self.aliases


class FakeEs:
    def __init__(self, error=None, ping=True, aliases=None):
        self.error = error
        self.pong = ping
        self.indices = FakeIndices(aliases)
        self.calls = []

    def search(self, index, body):
        self.calls.append((index, body))
        if self.error:
            raise self.error
        return elastic_transport.ObjectApiResponse(body={"hits": {}}, meta=None)

    def ping(self):
        return self.pong


# Configuration ------------------------------------------------------------------


def test_configuration_complete():
    settings = load_settings({"DATABASE_URL": PG_URL, "ELASTICSEARCH_URL": ES_URL})
    assert settings.database_url == PG_URL
    assert settings.elasticsearch_url == ES_URL


def test_variable_manquante_nommee_sans_valeur():
    with pytest.raises(ConfigError) as exc:
        load_settings({"DATABASE_URL": PG_URL, "ELASTICSEARCH_URL": ""})
    assert "ELASTICSEARCH_URL" in str(exc.value)
    assert "s3cret" not in str(exc.value)


def test_url_et_mot_de_passe_retires_des_messages():
    assert redact(f"cannot reach {ES_URL}", ES_URL) == "cannot reach <url>"
    assert redact("password s3cret rejected", PG_URL) == "password *** rejected"
    assert redact("refused", "http://127.0.0.1:9200") == "refused"


# Elasticsearch ------------------------------------------------------------------


def test_recherche_sur_l_alias():
    es = FakeEs()
    assert ElasticsearchBackend(es, ES_URL).search({"query": {}}) == {"hits": {}}
    assert es.calls == [("decisions", {"query": {}})]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (elasticsearch.ConnectionError("refused"), ElasticsearchUnavailable),
        (elasticsearch.ConnectionTimeout("timeout"), ElasticsearchUnavailable),
        (api_error(elasticsearch.ApiError, 503), ElasticsearchUnavailable),
        (api_error(elasticsearch.NotFoundError, 404), SearchIndexUnavailable),
    ],
)
def test_erreurs_elasticsearch_converties(error, expected):
    with pytest.raises(expected):
        ElasticsearchBackend(FakeEs(error=error), ES_URL).search({})


def test_erreur_de_requete_propagee():
    backend = ElasticsearchBackend(
        FakeEs(error=api_error(elasticsearch.BadRequestError, 400)), ES_URL
    )
    with pytest.raises(elasticsearch.BadRequestError):  # bug de requête : 500, pas 503
        backend.search({})


def test_sante_elasticsearch_ok():
    es = FakeEs(aliases={"decisions_20260926_135231": {"aliases": {"decisions": {}}}})
    health = ElasticsearchBackend(es, ES_URL).health()
    assert health["status"] == "ok"
    assert health["index"] == "decisions_20260926_135231"
    assert health["error"] is None
    assert isinstance(health["latency_ms"], int)


def test_sante_elasticsearch_injoignable():
    health = ElasticsearchBackend(FakeEs(ping=False), ES_URL).health()
    assert health["status"] == "error"
    assert health["index"] is None
    assert health["error"] == "ElasticsearchUnavailable: ping failed"


def test_sante_elasticsearch_sans_alias():
    health = ElasticsearchBackend(FakeEs(aliases=None), ES_URL).health()
    assert health["status"] == "error"
    assert "alias 'decisions' not found" in health["error"]


# PostgreSQL ---------------------------------------------------------------------


def test_base_injoignable(monkeypatch):
    def refuse(*args, **kwargs):
        raise psycopg.OperationalError(f"connection to {PG_URL} failed: Connection refused")

    monkeypatch.setattr(backends.psycopg, "connect", refuse)
    database = PostgresDatabase(PG_URL)
    with pytest.raises(DatabaseUnavailable):
        database.decision("judilibre", "x")
    health = database.health()
    assert health["status"] == "error"
    assert health["error"] == "OperationalError: connection to <url> failed: Connection refused"


class FakeConnection:
    """Connexion psycopg minimale : mémorise l'état au moment de la requête."""

    def __init__(self, error=None):
        self.error = error
        self.read_only = False
        self.isolation_level = None
        self.read_only_at_query = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.read_only_at_query = self.read_only
        if self.error:
            raise self.error
        return self

    def fetchone(self):
        return None


def test_delai_de_requete_depasse(monkeypatch):
    timeout = psycopg.errors.QueryCanceled("canceling statement due to statement timeout")
    monkeypatch.setattr(backends.psycopg, "connect", lambda url, **kw: FakeConnection(timeout))
    with pytest.raises(DatabaseUnavailable):
        PostgresDatabase(PG_URL).runs([], None, 20)


def test_connexion_en_lecture_seule(monkeypatch):
    conn = FakeConnection()
    options = {}

    def connect(url, **kwargs):
        options.update(kwargs)
        return conn

    monkeypatch.setattr(backends.psycopg, "connect", connect)
    assert PostgresDatabase(PG_URL).decision("judilibre", "absent") is None
    assert conn.read_only_at_query is True
    assert options["connect_timeout"] == 3
    assert options["options"] == "-c statement_timeout=5000"


# Qualité ------------------------------------------------------------------------


def row(check_name, severity, status, source="adlc-opendata", value=Decimal("0")):
    return {
        "check_name": check_name,
        "dimension": "completeness",
        "severity": severity,
        "source": source,
        "value": value,
        "expected": "== 0",
        "status": status,
        "error": None,
        "checked_at": NOW,
    }


RUN = {"run_id": 33, "started_at": NOW, "finished_at": NOW, "status": "success"}


def test_verdict_succes_et_comptes():
    report = quality_report(
        RUN,
        [row("empty_text", "warning", "fail", value=Decimal("31")), row("a", "error", "pass")],
    )
    assert report["verdict"] == "success"  # un échec warning n'est jamais bloquant
    assert report["counts"] == {
        "fail": 1,
        "no_data": 0,
        "query_error": 0,
        "unchecked": 0,
        "pass": 1,
    }
    assert report["run"] == RUN


@pytest.mark.parametrize("status", ["fail", "no_data", "query_error"])
def test_verdict_echec_sur_un_controle_error(status):
    report = quality_report(RUN, [row("missing_decision_date", "error", status)])
    assert report["verdict"] == "failure"


def test_ordre_du_rapport_qualite():
    rows = [
        row("b", "warning", "pass"),
        row("a", "error", "pass", source="judilibre"),
        row("a", "error", "pass", source="adlc-opendata"),
        row("z", "warning", "fail"),
        row("q", "error", "query_error", source=None, value=None),
    ]
    order = [(r["check_name"], r["source"]) for r in quality_report(RUN, rows)["results"]]
    assert order == [
        ("z", "adlc-opendata"),
        ("q", None),
        ("a", "adlc-opendata"),
        ("a", "judilibre"),
        ("b", "adlc-opendata"),
    ]


def test_valeurs_numeriques():
    assert number(None) is None
    assert number(Decimal("1.0000")) == 1 and isinstance(number(Decimal("1.0000")), int)
    assert number(Decimal("0.9812")) == 0.9812
