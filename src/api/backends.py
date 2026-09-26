from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import urlsplit

import elasticsearch
import psycopg
from elasticsearch import Elasticsearch
from psycopg import IsolationLevel
from psycopg.rows import dict_row

from src.quality.checks import SEVERITIES
from src.quality.evaluate import CheckResult, run_failed
from src.quality.run import STATUS_ORDER
from src.search.document import has_text
from src.search.index import ALIAS

ENV_VARS = ("DATABASE_URL", "ELASTICSEARCH_URL")
ES_TIMEOUT = 5  # secondes
PG_CONNECT_TIMEOUT = 3  # secondes
PG_STATEMENT_TIMEOUT = 5000  # millisecondes

DECISION_SQL = """SELECT source, external_id, decision_number, issuer, decision_type,
       decision_date, title, text, sectors, url, attributes, built_at
FROM silver.decisions
WHERE source = %s AND external_id = %s"""
RUNS_SQL = """SELECT run_id, source, date_type, date_start, date_end, started_at, finished_at,
       status, nb_fetched, nb_new, nb_changed, error
FROM bronze.collection_runs
WHERE (%(sources)s::text[] IS NULL OR source = ANY(%(sources)s))
  AND (%(status)s::text IS NULL OR status = %(status)s)
ORDER BY run_id DESC
LIMIT %(limit)s"""
LATEST_QUALITY_RUN_SQL = """SELECT r.run_id, r.started_at, r.finished_at, r.status
FROM bronze.collection_runs r
WHERE r.run_id = (SELECT max(run_id) FROM quality.check_results)"""
QUALITY_RESULTS_SQL = """SELECT check_name, dimension, severity, source, value, expected,
       status, error, checked_at
FROM quality.check_results
WHERE run_id = %s"""
CHECK_FIELDS = ("check_name", "dimension", "severity", "source", "value", "expected", "status")


class ConfigError(RuntimeError):
    """Variable d'environnement manquante."""


class ServiceUnavailable(Exception):
    """Service injoignable ou trop lent : la route répond 503 avec ce code."""

    code = "service_unavailable"
    message = "service unavailable"


class ElasticsearchUnavailable(ServiceUnavailable):
    code = "elasticsearch_unavailable"
    message = "Elasticsearch is unavailable"


class SearchIndexUnavailable(ServiceUnavailable):
    code = "search_index_unavailable"
    message = f"the '{ALIAS}' alias does not exist"


class DatabaseUnavailable(ServiceUnavailable):
    code = "database_unavailable"
    message = "PostgreSQL is unavailable"


@dataclass(frozen=True)
class Settings:
    database_url: str
    elasticsearch_url: str


def load_settings(env: Mapping[str, str]) -> Settings:
    """Échec explicite au démarrage : le message nomme la variable, jamais sa valeur."""
    missing = [name for name in ENV_VARS if not env.get(name)]
    if missing:
        raise ConfigError(f"missing environment variable(s): {', '.join(missing)}")
    return Settings(env["DATABASE_URL"], env["ELASTICSEARCH_URL"])


def redact(message: str, url: str) -> str:
    """Retire d'un message d'erreur l'URL de connexion et son mot de passe."""
    password = urlsplit(url).password
    message = message.replace(url, "<url>")
    return message.replace(password, "***") if password else message


def short_error(exc: BaseException, url: str) -> str:
    if not str(exc).strip() and exc.__cause__ is not None:
        exc = exc.__cause__  # ServiceUnavailable sans message : la cause est plus parlante
    first_line = str(exc).strip().partition("\n")[0]
    text = f"{type(exc).__name__}: {first_line}" if first_line else type(exc).__name__
    return redact(text, url)


def timed(check: Callable[[], dict[str, Any]], url: str) -> dict[str, Any]:
    """Statut d'un service ; toute exception est rapportée, jamais propagée."""
    start = time.perf_counter()
    try:
        status = {"status": "ok", **check(), "error": None}
    except Exception as exc:
        status = {"status": "error", "error": short_error(exc, url)}
    status["latency_ms"] = round((time.perf_counter() - start) * 1000)
    return status


class SearchBackend(Protocol):
    def search(self, body: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def health(self) -> dict[str, Any]: ...


class Database(Protocol):
    def decision(self, source: str, external_id: str) -> dict[str, Any] | None: ...

    def runs(self, sources: Sequence[str], status: str | None, limit: int) -> list[dict]: ...

    def latest_quality(self) -> dict[str, Any] | None: ...

    def health(self) -> dict[str, Any]: ...


class ElasticsearchBackend:
    """Recherche sur l'alias decisions ; seuls search, ping et la lecture d'alias sont appelés."""

    def __init__(self, es: Elasticsearch, url: str) -> None:
        self.es = es
        self.url = url

    @classmethod
    def from_url(cls, url: str) -> ElasticsearchBackend:
        # Un seul nœud : une nouvelle tentative ne ferait que retarder la 503.
        return cls(Elasticsearch(url, request_timeout=ES_TIMEOUT, max_retries=0), url)

    def search(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            return self.es.search(index=ALIAS, body=dict(body)).body
        except elasticsearch.NotFoundError as exc:
            raise SearchIndexUnavailable() from exc
        except (elasticsearch.ConnectionError, elasticsearch.ConnectionTimeout) as exc:
            raise ElasticsearchUnavailable() from exc
        except elasticsearch.ApiError as exc:
            if exc.meta.status >= 500:  # cluster pas prêt, shards indisponibles
                raise ElasticsearchUnavailable() from exc
            raise

    def health(self) -> dict[str, Any]:
        def check() -> dict[str, Any]:
            if not self.es.ping():
                raise ElasticsearchUnavailable("ping failed")
            try:
                targets = sorted(self.es.indices.get_alias(name=ALIAS))
            except elasticsearch.NotFoundError:
                raise SearchIndexUnavailable(f"alias '{ALIAS}' not found") from None
            return {"index": ", ".join(targets)}  # un seul index après une bascule

        return {"index": None, **timed(check, self.url)}

    def close(self) -> None:
        self.es.close()


def number(value: Decimal | None) -> int | float | None:
    """NUMERIC PostgreSQL en nombre JSON : entier s'il n'a pas de partie décimale."""
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


def sort_key(row: Mapping[str, Any]) -> tuple[int, int, str, str]:
    """Ordre du rapport de src.quality.run : statut, sévérité, contrôle, source."""
    return (
        STATUS_ORDER.index(row["status"]),
        SEVERITIES.index(row["severity"]),
        row["check_name"],
        row["source"] or "",
    )


class PostgresDatabase:
    """Une connexion par appel, en lecture seule, avec délais de connexion et de requête."""

    def __init__(self, url: str) -> None:
        self.url = url

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        try:
            with psycopg.connect(
                self.url,
                connect_timeout=PG_CONNECT_TIMEOUT,
                options=f"-c statement_timeout={PG_STATEMENT_TIMEOUT}",
                row_factory=dict_row,
            ) as conn:
                conn.read_only = True
                conn.isolation_level = IsolationLevel.REPEATABLE_READ  # un seul instantané
                yield conn
        except psycopg.OperationalError as exc:  # connexion refusée, délai dépassé
            raise DatabaseUnavailable() from exc

    def decision(self, source: str, external_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(DECISION_SQL, (source, external_id)).fetchone()
        if row is None:
            return None
        return {**row, "has_text": has_text(row["text"])}

    def runs(self, sources: Sequence[str], status: str | None, limit: int) -> list[dict]:
        params = {"sources": list(sources) or None, "status": status, "limit": limit}
        with self.connect() as conn:
            return conn.execute(RUNS_SQL, params).fetchall()

    def latest_quality(self) -> dict[str, Any] | None:
        """Dernier run présent dans quality.check_results, ses résultats et son verdict."""
        with self.connect() as conn:
            run = conn.execute(LATEST_QUALITY_RUN_SQL).fetchone()
            if run is None:
                return None
            rows = conn.execute(QUALITY_RESULTS_SQL, (run["run_id"],)).fetchall()
        return quality_report(run, rows)

    def health(self) -> dict[str, Any]:
        def check() -> dict[str, Any]:
            with self.connect() as conn:
                conn.execute("SELECT 1")
            return {}

        return timed(check, self.url)


def quality_report(run: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Verdict recalculé par run_failed, sans dupliquer la règle de src.quality."""
    checks = [CheckResult(**{name: row[name] for name in CHECK_FIELDS}) for row in rows]
    counts = dict.fromkeys(STATUS_ORDER, 0)
    for row in rows:
        counts[row["status"]] += 1
    results = [{**row, "value": number(row["value"])} for row in sorted(rows, key=sort_key)]
    return {
        "run": dict(run),
        "verdict": "failure" if run_failed(checks) else "success",
        "counts": counts,
        "results": results,
    }
