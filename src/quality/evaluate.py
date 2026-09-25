from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg

from .checks import Check

PASS = "pass"
FAIL = "fail"
NO_DATA = "no_data"
UNCHECKED = "unchecked"
QUERY_ERROR = "query_error"
BLOCKING = {FAIL, NO_DATA, QUERY_ERROR}
EXPECTED_COLUMNS = ["source", "value"]

# fetch(sql) -> (noms de colonnes, lignes)
Fetch = Callable[[str], tuple[Sequence[str], Sequence[Sequence[Any]]]]


class QueryResultError(Exception):
    """Résultat de requête qui ne respecte pas le format (source, value)."""


@dataclass(frozen=True)
class CheckResult:
    """Une ligne de quality.check_results (run_id et checked_at sont ajoutés au stockage)."""

    check_name: str
    dimension: str
    severity: str
    source: str | None
    value: Decimal | None
    expected: str | None
    status: str
    error: str | None = None


def validate_rows(
    columns: Sequence[str], rows: Iterable[Sequence[Any]]
) -> dict[str, Decimal | int]:
    """Valeur par source ; lève QueryResultError si le résultat est mal formé."""
    if list(columns) != EXPECTED_COLUMNS:
        raise QueryResultError(f"expected columns (source, value), got ({', '.join(columns)})")
    values: dict[str, Decimal | int] = {}
    for source, value in rows:
        if not isinstance(source, str) or not source.strip():
            raise QueryResultError(f"invalid source {source!r}")
        if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
            raise QueryResultError(f"source {source}: non-numeric value {value!r}")
        if source in values:
            raise QueryResultError(f"source {source}: returned more than once")
        values[source] = Decimal(str(value)) if isinstance(value, float) else value
    return values


def result(check: Check, source: str | None, value: Any, expected: Any, status: str) -> CheckResult:
    return CheckResult(
        check_name=check.name,
        dimension=check.dimension,
        severity=check.severity,
        source=source,
        value=value,
        expected=None if expected is None else str(expected),
        status=status,
    )


def evaluate(check: Check, values: dict[str, Decimal | int]) -> list[CheckResult]:
    """Sources renvoyées (triées), puis sources déclarées absentes du résultat."""
    results = []
    for source in sorted(values):
        expectation = check.expectation_for(source)
        value = values[source]
        if expectation is None:
            status = UNCHECKED
        else:
            status = PASS if expectation.holds(value) else FAIL
        results.append(result(check, source, value, expectation, status))
    for source in check.declared_sources:
        if source not in values:
            results.append(result(check, source, None, check.expect[source], NO_DATA))
    return results


def query_error(check: Check, message: str) -> CheckResult:
    return CheckResult(
        check_name=check.name,
        dimension=check.dimension,
        severity=check.severity,
        source=None,
        value=None,
        expected=None,
        status=QUERY_ERROR,
        error=message,
    )


def run_check(check: Check, fetch: Fetch) -> list[CheckResult]:
    """Exécute et évalue un contrôle ; une erreur de requête ou de format donne query_error.

    L'erreur doit sortir de fetch (et donc du savepoint qu'il ouvre) avant d'être capturée ici,
    sinon la transaction resterait abandonnée pour les contrôles suivants.
    """
    try:
        columns, rows = fetch(check.sql)
        values = validate_rows(columns, rows)
    except (psycopg.Error, QueryResultError) as exc:
        return [query_error(check, str(exc).strip() or type(exc).__name__)]
    return evaluate(check, values)


def run_failed(results: Iterable[CheckResult]) -> bool:
    """Le run échoue sur un résultat bloquant d'un contrôle de sévérité error."""
    return any(r.severity == "error" and r.status in BLOCKING for r in results)
