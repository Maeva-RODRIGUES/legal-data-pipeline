from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

CHECKS_PATH = Path(__file__).with_name("checks.yml")
DIMENSIONS = ("completeness", "validity", "uniqueness", "consistency", "freshness")
SEVERITIES = ("error", "warning")
OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "==": operator.eq,
    "<=": operator.le,
    ">=": operator.ge,
    "<": operator.lt,
    ">": operator.gt,
}
DEFAULT_KEY = "default"
TEXT_FIELDS = ("name", "dimension", "severity", "description", "sql")


class CheckConfigError(ValueError):
    """Catalogue de contrôles invalide."""


@dataclass(frozen=True)
class Expectation:
    op: str
    value: Decimal

    def holds(self, value: Decimal | int) -> bool:
        return OPERATORS[self.op](value, self.value)

    def __str__(self) -> str:
        return f"{self.op} {self.value}"


@dataclass(frozen=True)
class Check:
    name: str
    dimension: str
    severity: str
    description: str
    sql: str
    expect: dict[str, Expectation]

    @property
    def declared_sources(self) -> list[str]:
        return [source for source in self.expect if source != DEFAULT_KEY]

    def expectation_for(self, source: str) -> Expectation | None:
        """L'attente propre à la source l'emporte sur `default` ; None si aucune ne s'applique."""
        return self.expect.get(source, self.expect.get(DEFAULT_KEY))


def to_decimal(value: Any) -> Decimal:
    """Nombre YAML en Decimal, pour une comparaison exacte avec les numeric de PostgreSQL."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"value must be a number, got {value!r}")
    return Decimal(str(value))


def parse_expectation(raw: Any) -> Expectation:
    if not isinstance(raw, dict) or set(raw) != {"op", "value"}:
        raise ValueError(f"expected {{op, value}}, got {raw!r}")
    if raw["op"] not in OPERATORS:
        raise ValueError(f"unknown operator {raw['op']!r} (allowed: {', '.join(OPERATORS)})")
    return Expectation(raw["op"], to_decimal(raw["value"]))


def parse_check(raw: Any, index: int) -> Check:
    if not isinstance(raw, dict):
        raise CheckConfigError(f"check #{index}: must be a mapping, got {type(raw).__name__}")
    name = raw.get("name")
    label = name.strip() if isinstance(name, str) and name.strip() else f"#{index}"

    for key in TEXT_FIELDS:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise CheckConfigError(f"check {label}: missing or empty '{key}'")
    if raw["dimension"] not in DIMENSIONS:
        raise CheckConfigError(
            f"check {label}: unknown dimension {raw['dimension']!r} "
            f"(allowed: {', '.join(DIMENSIONS)})"
        )
    if raw["severity"] not in SEVERITIES:
        raise CheckConfigError(
            f"check {label}: unknown severity {raw['severity']!r} "
            f"(allowed: {', '.join(SEVERITIES)})"
        )

    raw_expect = raw.get("expect")
    if not isinstance(raw_expect, dict) or not raw_expect:
        raise CheckConfigError(f"check {label}: 'expect' must contain at least one entry")
    expect = {}
    for source, raw_expectation in raw_expect.items():
        try:
            expect[str(source)] = parse_expectation(raw_expectation)
        except ValueError as exc:
            raise CheckConfigError(f"check {label}: expect.{source}: {exc}") from None

    return Check(
        name=raw["name"],
        dimension=raw["dimension"],
        severity=raw["severity"],
        description=raw["description"],
        sql=raw["sql"],
        expect=expect,
    )


def load_checks(path: Path = CHECKS_PATH) -> list[Check]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, list) or not raw:
        raise CheckConfigError(f"{path}: expected a non-empty list of checks")

    checks = [parse_check(item, index) for index, item in enumerate(raw, start=1)]
    seen: set[str] = set()
    for check in checks:
        if check.name in seen:
            raise CheckConfigError(f"check {check.name}: duplicate name")
        seen.add(check.name)
    return checks
