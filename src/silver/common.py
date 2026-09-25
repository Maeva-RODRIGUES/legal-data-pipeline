from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class SilverRow:
    """Une ligne de silver.decisions (built_at est rempli par la base)."""

    source: str
    external_id: str
    decision_number: str | None = None
    issuer: str | None = None
    decision_type: str | None = None
    decision_date: date | None = None
    title: str | None = None
    text: str | None = None
    sectors: list[str] = field(default_factory=list)
    url: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


# La ligne (None si elle est sans identifiant) et les anomalies rencontrées.
TransformResult = tuple[SilverRow | None, list[str]]


def strip_or_none(value: Any) -> str | None:
    """Chaîne sans espaces autour, None si elle est vide ou si ce n'est pas une chaîne."""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def parse_iso_date(value: Any) -> date | None:
    """Date ISO (YYYY-MM-DD) ou date-heure ISO, dont on garde la date. Sinon None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.strip()).date()
    except ValueError:
        return None


def parse_python_list(value: Any) -> list[str] | None:
    """Liste au format Python ("['BTP']"), éléments nettoyés, chaînes vides retirées.

    Renvoie None si le texte est mal formé ou n'est pas une liste de chaînes.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = ast.literal_eval(value.strip())
    except (ValueError, SyntaxError):
        return None
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        return None
    return [item.strip() for item in parsed if item.strip()]


def dedupe(items: Iterable[Any]) -> list[Any]:
    """Supprime les doublons en gardant l'ordre d'apparition."""
    return list(dict.fromkeys(items))
