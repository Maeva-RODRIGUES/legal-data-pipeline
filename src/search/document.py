from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

MAPPING_PATH = Path(__file__).with_name("mapping.json")
# Colonnes Silver recopiées telles quelles (built_at exclu : absent du mapping strict).
SILVER_FIELDS = (
    "source",
    "external_id",
    "decision_number",
    "issuer",
    "decision_type",
    "decision_date",
    "title",
    "text",
    "sectors",
    "url",
    "attributes",
)
# Champs du document, dans l'ordre du mapping.
FIELDS = (*SILVER_FIELDS[:8], "has_text", *SILVER_FIELDS[8:], "indexed_at")


def load_mapping(path: Path = MAPPING_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def has_text(text: str | None) -> bool:
    return text is not None and text.strip() != ""


def to_document(row: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Document Elasticsearch d'une ligne Silver : toutes les clés présentes, NULL en None.

    indexed_at vient de la requête (now() AS indexed_at), commun à tout le run.
    """
    doc = {field: row[field] for field in SILVER_FIELDS}
    doc["decision_date"] = isoformat(row["decision_date"])
    doc["has_text"] = has_text(row["text"])
    doc["sectors"] = None if row["sectors"] is None else list(row["sectors"])
    doc["attributes"] = None if row["attributes"] is None else dict(row["attributes"])
    doc["indexed_at"] = isoformat(row["indexed_at"])
    return f"{row['source']}|{row['external_id']}", {field: doc[field] for field in FIELDS}


def isoformat(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()
