from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import psycopg
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from psycopg import IsolationLevel
from psycopg.rows import dict_row

from src.storage.bronze_store import BronzeStore

from .document import load_mapping, to_document
from .index import ALIAS, ElasticsearchIndexClient, IndexClient
from .rebuild import RebuildError, RebuildResult, rebuild

SOURCE = "search"
DATE_TYPE = "rebuild"
ITERSIZE = 200  # textes jusqu'à 1,2 million de caractères
SELECT_SQL = """SELECT source, external_id, decision_number, issuer, decision_type,
    decision_date, title, text, sectors, url, attributes, now() AS indexed_at
    FROM silver.decisions ORDER BY source, external_id"""
COUNT_SQL = "SELECT source, count(*) FROM silver.decisions GROUP BY source"
INSERT_STATS_SQL = """INSERT INTO search.index_stats
    (run_id, index_name, source, silver_count, indexed_count, rejected_count, alias_switched)
    VALUES (%s, %s, %s, %s, %s, %s, %s)"""


def count_silver(conn: psycopg.Connection) -> dict[str, int]:
    return dict(conn.execute(COUNT_SQL).fetchall())


def iter_silver(conn: psycopg.Connection, counts: dict[str, int]) -> Iterator[dict[str, Any]]:
    """Curseur côté serveur : les textes sont trop lourds pour tout charger."""
    with conn.cursor(name="search_silver_scan", row_factory=dict_row) as cur:
        cur.itersize = ITERSIZE
        cur.execute(SELECT_SQL)
        for row in cur:
            counts["fetched"] += 1
            yield row


def index_silver(
    conn: psycopg.Connection,
    client: IndexClient,
    mapping: dict[str, Any],
    counts: dict[str, int],
) -> RebuildResult:
    """Comptage et lecture de Silver sur un même instantané, en lecture seule, annulé à la fin.

    Un silver.run lancé en parallèle ne peut donc pas fausser la comparaison des comptes.
    """
    conn.isolation_level = IsolationLevel.REPEATABLE_READ  # connexion au repos : start_run
    conn.read_only = True  # vient de valider
    try:
        with conn.transaction(force_rollback=True):
            silver_counts = count_silver(conn)
            docs = (to_document(row) for row in iter_silver(conn, counts))
            return rebuild(client, docs, silver_counts, mapping, datetime.now(UTC))
    finally:
        conn.read_only = False
        conn.isolation_level = None


def stats_params(run_id: int, result: RebuildResult) -> list[tuple[Any, ...]]:
    """Une ligne par source présente dans Silver, dans l'index ou parmi les rejets."""
    indexed = result.indexed_counts
    sources = sorted(set(result.silver_counts) | set(indexed or {}) | set(result.rejected_counts))
    return [
        (
            run_id,
            result.index_name,
            source,
            result.silver_counts.get(source, 0),
            None if indexed is None else indexed.get(source, 0),
            result.rejected_counts[source],
            result.alias_switched,
        )
        for source in sources
    ]


def store_stats(conn: psycopg.Connection, run_id: int, result: RebuildResult) -> None:
    """Insère les statistiques sans valider : finish_run valide statistiques et fin de run."""
    with conn.cursor() as cur:
        cur.executemany(INSERT_STATS_SQL, stats_params(run_id, result))


def format_report(result: RebuildResult) -> str:
    rows = stats_params(0, result)
    width = max((len(row[2]) for row in rows), default=0)
    lines = [f"Index {result.index_name}"]
    for _, _, source, silver, indexed, rejected, _ in rows:
        done = "index non compté" if indexed is None else f"{indexed} indexée(s)"
        lines.append(f"  {source:<{width}} : {silver} dans Silver, {done}, {rejected} rejetée(s)")
    if not result.alias_switched:
        lines.append(f"Alias {ALIAS} non basculé : {result.reason}")
        return "\n".join(lines)
    previous = result.previous_index or "aucun"
    lines.append(
        f"Alias {ALIAS} basculé (index précédent conservé : {previous} ; "
        f"supprimé(s) : {len(result.deleted_indexes)})"
    )
    lines.extend(f"Avertissement : {warning}" for warning in result.warnings)
    return "\n".join(lines)


def exit_code(result: RebuildResult) -> int:
    return 0 if result.alias_switched else 1


def main() -> int:
    load_dotenv()
    mapping = load_mapping()  # mapping illisible : échec avant d'ouvrir un run
    store = BronzeStore(os.environ["DATABASE_URL"])
    es = Elasticsearch(os.environ["ELASTICSEARCH_URL"], request_timeout=60)
    today = date.today()
    run_id = store.start_run(SOURCE, today, today, DATE_TYPE)
    counts = {"fetched": 0, "new": 0, "changed": 0}
    print(f"Run {run_id} : reconstruction de l'index {ALIAS}")

    try:
        result = index_silver(store.conn, ElasticsearchIndexClient(es), mapping, counts)
        counts["new"] = sum((result.indexed_counts or {}).values())
        store_stats(store.conn, run_id, result)
    except Exception as exc:
        store.conn.rollback()
        if isinstance(exc, RebuildError):
            store_stats(store.conn, run_id, exc.result)  # ce qui est connu ; alias inchangé
        store.finish_run(run_id, "failed", counts, error=str(exc)[:1000])
        raise
    else:
        # Alias non basculé : la reconstruction n'a pas abouti, le run est en échec.
        status = "success" if result.alias_switched else "failed"
        store.finish_run(run_id, status, counts, error=result.reason)
    finally:
        store.close()
        es.close()

    print(format_report(result))
    return exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
