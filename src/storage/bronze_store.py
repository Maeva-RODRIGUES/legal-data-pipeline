from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


def payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class BronzeStore:
    def __init__(self, dsn: str) -> None:
        self.conn = psycopg.connect(dsn)

    def last_successful_end(self, source: str, date_type: str) -> date | None:
        row = self.conn.execute(
            """SELECT max(date_end) FROM bronze.collection_runs
               WHERE source = %s AND status = 'success' AND date_type = %s""",
            (source, date_type),
        ).fetchone()
        return row[0] if row else None

    def start_run(self, source: str, date_start: date, date_end: date, date_type: str) -> int:
        run_id = self.conn.execute(
            """INSERT INTO bronze.collection_runs (source, date_start, date_end, date_type)
               VALUES (%s, %s, %s, %s) RETURNING run_id""",
            (source, date_start, date_end, date_type),
        ).fetchone()[0]
        self.conn.commit()
        return run_id

    def save(self, source: str, external_id: str, payload: dict[str, Any], run_id: int) -> str:
        """Insère ou met à jour un document. Renvoie 'new', 'changed' ou 'unchanged'."""
        new_hash = payload_hash(payload)
        row = self.conn.execute(
            "SELECT payload_hash FROM bronze.raw_documents WHERE source = %s AND external_id = %s",
            (source, external_id),
        ).fetchone()

        if row is None:
            self.conn.execute(
                """INSERT INTO bronze.raw_documents
                   (source, external_id, payload, payload_hash, first_seen_run, last_seen_run)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (source, external_id, Jsonb(payload), new_hash, run_id, run_id),
            )
            return "new"
        if row[0] != new_hash:
            self.conn.execute(
                """UPDATE bronze.raw_documents
                   SET payload = %s, payload_hash = %s, last_seen_run = %s, updated_at = now()
                   WHERE source = %s AND external_id = %s""",
                (Jsonb(payload), new_hash, run_id, source, external_id),
            )
            return "changed"
        self.conn.execute(
            """UPDATE bronze.raw_documents SET last_seen_run = %s
               WHERE source = %s AND external_id = %s""",
            (run_id, source, external_id),
        )
        return "unchanged"

    def finish_run(
        self, run_id: int, status: str, counts: dict[str, int], error: str | None = None
    ) -> None:
        self.conn.execute(
            """UPDATE bronze.collection_runs
               SET finished_at = now(), status = %s, nb_fetched = %s,
                   nb_new = %s, nb_changed = %s, error = %s
               WHERE run_id = %s""",
            (status, counts["fetched"], counts["new"], counts["changed"], error, run_id),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
