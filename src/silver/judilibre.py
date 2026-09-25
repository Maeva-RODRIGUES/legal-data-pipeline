from __future__ import annotations

import re
from typing import Any

from .common import SilverRow, TransformResult, dedupe, parse_iso_date, strip_or_none

SOURCE = "judilibre"
ISSUERS = {
    "cc": "Cour de cassation",
    "ca": "Cour d'appel",
    "tj": "Tribunal judiciaire",
}
NUMBER_RE = re.compile(r"^\d{2}-\d{2}\.\d{3}$")
# Format vérifié le 25/09/2026 avec la décision 19-24.008.
URL_TEMPLATE = "https://www.courdecassation.fr/decision/{id}"
ATTRIBUTE_FIELDS = ("ecli", "chamber", "formation", "solution", "publication", "themes")


def transform(external_id: str, payload: dict[str, Any]) -> TransformResult:
    ext_id = strip_or_none(external_id)
    if ext_id is None:
        return None, ["missing_external_id"]
    anomalies: list[str] = []

    # `number` est une concaténation corrompue de tous les numéros : seul `numbers` est lu.
    numbers = payload.get("numbers")
    if isinstance(numbers, list):
        numbers = dedupe(numbers)
    first = numbers[0] if isinstance(numbers, list) and numbers else None
    decision_number = first if isinstance(first, str) and NUMBER_RE.match(first) else None
    if decision_number is None:
        anomalies.append("invalid_decision_number")

    issuer = ISSUERS.get(payload.get("jurisdiction"))
    if issuer is None:
        anomalies.append("unknown_jurisdiction")

    decision_date = parse_iso_date(payload.get("decision_date"))
    if decision_date is None:
        anomalies.append("invalid_decision_date")

    attributes = {name: payload.get(name) for name in ATTRIBUTE_FIELDS}
    attributes["numbers"] = numbers
    if strip_or_none(payload.get("summary")):
        attributes["summary"] = payload["summary"]
    attributes["update_date"] = payload.get("update_date")
    # Le `type` de la source vaut `other` pour toutes les décisions : gardé ici, pas en colonne.
    attributes["judilibre_type"] = payload.get("type")

    row = SilverRow(
        source=SOURCE,
        external_id=ext_id,
        decision_number=decision_number,
        issuer=issuer,
        decision_type=None,
        decision_date=decision_date,
        title=None,
        text=payload.get("text"),
        sectors=[],
        url=URL_TEMPLATE.format(id=ext_id),
        attributes=attributes,
    )
    return row, anomalies
