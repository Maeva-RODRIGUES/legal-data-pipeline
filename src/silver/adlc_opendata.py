from __future__ import annotations

import json
from typing import Any

from .common import SilverRow, TransformResult, parse_iso_date, parse_str_list, strip_or_none

SOURCE = "adlc-opendata"
ISSUER = "Autorité de la concurrence"
MAIN_TYPES = {
    "Décision": "decision",
    "Avis": "avis",
    "DCC": "concentration",
    "Lettre du minsitre de l'économie": "lettre_ministre",  # faute présente dans la source
}
# Champs repris en colonnes, donc absents de `attributes`.
COLUMN_FIELDS = frozenset(
    {
        "id_decision",
        "type_decision",
        "date_decision_datetime",
        "titre_decision",
        "texte_complet_decision",
        "secteur_activite",
        "url_site",
    }
)
SIMPLIFIEE = {"Oui": True, "Non": False}


def parse_type_decision(raw: Any) -> tuple[str | None, list[str], list[str]]:
    """Type principal (vocabulaire contrôlé), sous-types et anomalies.

    `type_decision` est soit un libellé (`Avis`), soit une vraie liste (`["Avis", "SOA"]`) :
    type principal puis sous-types. Une liste encodée en texte JSON est lue en secours.
    Une valeur inconnue n'est jamais rabattue sur un type connu.
    """
    value = raw.strip() if isinstance(raw, str) else raw
    subtypes: list[str] = []
    if isinstance(value, str) and value.startswith("["):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None, [], ["malformed_type_decision"]
    if isinstance(value, list):
        if not value or not all(isinstance(item, str) for item in value):
            return None, [], ["malformed_type_decision"]
        value, subtypes = value[0], [item.strip() for item in value[1:]]
    main = MAIN_TYPES.get(value.strip()) if isinstance(value, str) else None
    return main, subtypes, [] if main else ["unknown_decision_type"]


def normalize_attributes(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Champs hors colonnes : chaînes nettoyées, listes et booléens convertis."""
    anomalies: list[str] = []
    attributes: dict[str, Any] = {}
    for name, value in payload.items():
        if name in COLUMN_FIELDS:
            continue
        if name == "entreprises_concernees" and value is not None:
            parsed = parse_str_list(value)
            if parsed is None:
                anomalies.append("malformed_entreprises")
            value = parsed or []
        elif name == "decision_simplifiee" and value is not None:
            # Champ propre aux concentrations : absent ailleurs, ce qui n'est pas une anomalie.
            value = SIMPLIFIEE.get(value.strip() if isinstance(value, str) else value)
            if value is None:
                anomalies.append("invalid_decision_simplifiee")
        elif isinstance(value, str):
            value = value.strip()
        attributes[name] = value
    return attributes, anomalies


def transform(external_id: str, payload: dict[str, Any]) -> TransformResult:
    ext_id = strip_or_none(external_id)
    if ext_id is None:
        return None, ["missing_external_id"]

    decision_type, subtypes, anomalies = parse_type_decision(payload.get("type_decision"))

    # La date en toutes lettres (`date_decision`) n'est pas analysée : elle reste en attribut.
    decision_date = parse_iso_date(payload.get("date_decision_datetime"))
    if decision_date is None:
        anomalies.append("invalid_decision_date")

    sectors: list[str] = []
    if payload.get("secteur_activite") is not None:
        parsed = parse_str_list(payload["secteur_activite"])
        if parsed is None:
            anomalies.append("malformed_sectors")
        sectors = parsed or []

    attributes, attribute_anomalies = normalize_attributes(payload)
    anomalies.extend(attribute_anomalies)
    attributes["subtypes"] = subtypes

    row = SilverRow(
        source=SOURCE,
        external_id=ext_id,
        decision_number=strip_or_none(payload.get("id_decision")),
        issuer=ISSUER,
        decision_type=decision_type,
        decision_date=decision_date,
        title=strip_or_none(payload.get("titre_decision")),
        text=payload.get("texte_complet_decision"),
        sectors=sectors,
        url=strip_or_none(payload.get("url_site")),
        attributes=attributes,
    )
    return row, anomalies
