from __future__ import annotations

import os
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from datetime import date
from itertools import batched
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from src.storage.bronze_store import BronzeStore

from . import adlc_opendata, judilibre
from .common import SilverRow, TransformResult

SOURCE = "silver"
# adlc-scraper est un contrôle de fraîcheur, pas une source de contenu : absent de Silver.
TRANSFORMS: dict[str, Callable[[str, dict[str, Any]], TransformResult]] = {
    judilibre.SOURCE: judilibre.transform,
    adlc_opendata.SOURCE: adlc_opendata.transform,
}
BATCH_SIZE = 500
INSERT_SQL = """INSERT INTO silver.decisions
    (source, external_id, decision_number, issuer, decision_type, decision_date,
     title, text, sectors, url, attributes)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""


def build_rows(
    records: Iterable[tuple[str, dict[str, Any]]],
    transform: Callable[[str, dict[str, Any]], TransformResult],
    counts: Counter[str],
    anomalies: Counter[str],
) -> Iterator[SilverRow]:
    """Transforme les documents Bronze ; seule une ligne sans identifiant est sautée."""
    for external_id, payload in records:
        counts["read"] += 1
        row, row_anomalies = transform(external_id, payload)
        anomalies.update(row_anomalies)
        if row is None:
            counts["skipped"] += 1
            continue
        counts["written"] += 1
        yield row


def to_params(row: SilverRow) -> tuple[Any, ...]:
    return (
        row.source,
        row.external_id,
        row.decision_number,
        row.issuer,
        row.decision_type,
        row.decision_date,
        row.title,
        row.text,
        row.sectors,
        row.url,
        Jsonb(row.attributes),
    )


def iter_bronze(
    conn: psycopg.Connection, source: str, itersize: int = 200
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Curseur côté serveur : les payloads adlc-opendata sont trop lourds pour tout charger."""
    with conn.cursor(name="silver_bronze_scan") as cur:
        cur.itersize = itersize
        cur.execute(
            """SELECT external_id, payload FROM bronze.raw_documents
               WHERE source = %s ORDER BY external_id""",
            (source,),
        )
        yield from cur


def rebuild(conn: psycopg.Connection) -> tuple[dict[str, Counter], dict[str, Counter]]:
    """Vide puis remplit silver.decisions dans la transaction en cours, sans la valider.

    DELETE plutôt que TRUNCATE : les lecteurs voient l'ancien contenu jusqu'au commit.
    """
    counts: dict[str, Counter] = {}
    anomalies: dict[str, Counter] = {}
    conn.execute("DELETE FROM silver.decisions")
    for source, transform in TRANSFORMS.items():
        counts[source], anomalies[source] = Counter(), Counter()
        rows = build_rows(iter_bronze(conn, source), transform, counts[source], anomalies[source])
        with conn.cursor() as cur:
            for batch in batched(rows, BATCH_SIZE):
                cur.executemany(INSERT_SQL, [to_params(row) for row in batch])
    return counts, anomalies


def main() -> None:
    load_dotenv()
    store = BronzeStore(os.environ["DATABASE_URL"])
    today = date.today()
    run_id = store.start_run(SOURCE, today, today, "rebuild")
    run_counts = {"fetched": 0, "new": 0, "changed": 0}
    print(f"Run {run_id} : reconstruction de silver.decisions")

    try:
        counts, anomalies = rebuild(store.conn)
        run_counts["fetched"] = sum(c["read"] for c in counts.values())
        run_counts["new"] = sum(c["written"] for c in counts.values())
    except Exception as exc:
        store.conn.rollback()  # l'ancien contenu de Silver reste intact
        store.finish_run(run_id, "failed", run_counts, error=str(exc)[:1000])
        raise
    else:
        # finish_run valide dans la même transaction la reconstruction et la fin du run.
        store.finish_run(run_id, "success", run_counts)
    finally:
        store.close()

    print(f"Run {run_id} terminé")
    for source in TRANSFORMS:
        c = counts[source]
        print(f"  {source} : {c['written']} ligne(s) écrite(s) sur {c['read']} lue(s)")
        for kind, n in sorted(anomalies[source].items()):
            print(f"    {kind} : {n}")


if __name__ == "__main__":
    main()
