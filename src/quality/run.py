from __future__ import annotations

import argparse
import os
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv

from src.storage.bronze_store import BronzeStore

from .checks import CHECKS_PATH, SEVERITIES, Check, load_checks
from .evaluate import (
    FAIL,
    NO_DATA,
    PASS,
    QUERY_ERROR,
    UNCHECKED,
    CheckResult,
    run_check,
    run_failed,
)

SOURCE = "quality"
DATE_TYPE = "checks"
# Ordre du rapport : les échecs d'abord.
STATUS_ORDER = (FAIL, NO_DATA, QUERY_ERROR, UNCHECKED, PASS)
INSERT_SQL = """INSERT INTO quality.check_results
    (run_id, check_name, dimension, source, value, expected, severity, status, error)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Contrôles qualité -> quality.check_results")
    parser.add_argument(
        "--checks", type=Path, default=CHECKS_PATH, help="catalogue YAML des contrôles"
    )
    return parser.parse_args(argv)


def execute_checks(conn: psycopg.Connection, checks: Iterable[Check]) -> list[CheckResult]:
    """Exécute les contrôles dans une transaction en lecture seule, annulée à la fin."""

    def fetch(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
        # Savepoint par contrôle : une erreur l'annule en sortant du bloc, avant d'être
        # capturée par run_check, et les contrôles suivants s'exécutent normalement.
        with conn.transaction():
            cur = conn.execute(sql)
            columns = [column.name for column in cur.description or []]
            return columns, cur.fetchall()

    conn.read_only = True  # connexion au repos : start_run vient de valider
    try:
        with conn.transaction(force_rollback=True):
            return [r for check in checks for r in run_check(check, fetch)]
    finally:
        conn.read_only = False


def to_params(run_id: int, result: CheckResult) -> tuple[Any, ...]:
    return (
        run_id,
        result.check_name,
        result.dimension,
        result.source,
        result.value,
        result.expected,
        result.severity,
        result.status,
        result.error,
    )


def store_results(conn: psycopg.Connection, run_id: int, results: Iterable[CheckResult]) -> None:
    """Insère les résultats sans valider : finish_run valide résultats et fin de run ensemble."""
    with conn.cursor() as cur:
        cur.executemany(INSERT_SQL, [to_params(run_id, r) for r in results])


def format_line(result: CheckResult) -> str:
    target = (
        result.check_name if result.source is None else f"{result.check_name} / {result.source}"
    )
    if result.status == QUERY_ERROR:
        detail = (result.error or "").partition("\n")[0]  # message complet stocké dans error
    elif result.status == NO_DATA:
        detail = f"aucune ligne (attendu {result.expected})"
    elif result.status == UNCHECKED:
        detail = f"{result.value} (sans attente)"
    else:
        detail = f"{result.value} (attendu {result.expected})"
    return f"  {f'[{result.severity}]':<9} {target} : {detail}"


def format_report(results: Sequence[CheckResult]) -> str:
    lines = []
    for status in STATUS_ORDER:
        group = sorted(
            (r for r in results if r.status == status),
            key=lambda r: (SEVERITIES.index(r.severity), r.check_name, r.source or ""),
        )
        if group:
            lines.append(f"{status.upper()} ({len(group)})")
            lines.extend(format_line(r) for r in group)
    blocking = sum(1 for r in results if run_failed([r]))
    if blocking:
        lines.append(f"Verdict : échec ({blocking} résultat(s) bloquant(s) de sévérité error)")
    else:
        lines.append("Verdict : succès")
    return "\n".join(lines)


def main() -> int:
    load_dotenv()
    args = parse_args()
    checks = load_checks(args.checks)  # catalogue invalide : échec avant d'ouvrir un run
    store = BronzeStore(os.environ["DATABASE_URL"])
    today = date.today()
    run_id = store.start_run(SOURCE, today, today, DATE_TYPE)
    counts = {"fetched": 0, "new": 0, "changed": 0}
    print(f"Run {run_id} : {len(checks)} contrôle(s) de {args.checks}")

    try:
        results = execute_checks(store.conn, checks)
        store_results(store.conn, run_id, results)
        counts["fetched"] = len(results)
    except Exception as exc:
        store.conn.rollback()
        store.finish_run(run_id, "failed", counts, error=str(exc)[:1000])
        raise
    else:
        # Le run est un succès dès que le moteur a tout exécuté : le verdict est le code de sortie.
        store.finish_run(run_id, "success", counts)
    finally:
        store.close()

    print(format_report(results))
    return 1 if run_failed(results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
