from __future__ import annotations

from datetime import date

# Table fixe : le résultat ne dépend pas de la locale du système.
MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def french_date(value: date) -> str:
    """16 septembre 2026 ; 1er octobre 2026, selon l'usage des citations."""
    day = "1er" if value.day == 1 else str(value.day)
    return f"{day} {MONTHS[value.month - 1]} {value.year}"


def display_title(
    title: str | None,
    issuer: str | None,
    decision_date: date | None,
    decision_number: str | None,
    external_id: str,
) -> str:
    """Titre de la décision s'il existe, sinon citation : « Cour de cassation, 29 juillet 2026,
    n° 26-83.146 ». Un segment manquant est omis ; calculé à l'affichage, jamais stocké."""
    if title is not None and title.strip():
        return title
    parts = []
    if issuer:
        parts.append(issuer)
    if decision_date is not None:
        parts.append(french_date(decision_date))
    if decision_number:
        parts.append(f"n° {decision_number}")
    return ", ".join(parts) if parts else f"Décision {external_id}"
