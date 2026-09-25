from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

BASE_URL = "https://www.autoritedelaconcurrence.fr"


class ParseError(ValueError):
    """La page ne ressemble plus à ce qu'attend le parser (refonte du site ?)."""


@dataclass(frozen=True)
class ListingItem:
    id_decision: str
    title: str
    url: str
    decision_type: str | None
    decision_date: date | None
    sectors: list[str] = field(default_factory=list)
    node_id: str | None = None


def parse_listing(html: str, base_url: str = BASE_URL) -> list[ListingItem]:
    """Extrait les décisions d'une page de liste. Échoue bruyamment si la structure a changé."""
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("div.views-row > div.search-index")
    if not cards:
        raise ParseError("aucune décision trouvée dans la page de liste")
    return [_parse_card(card, base_url) for card in cards]


def _parse_card(card: Tag, base_url: str) -> ListingItem:
    node_id = card.get("data-history-node-id")
    link = card.select_one("h2 a[href]")
    id_span = link.select_one(".field--name-field-id") if link else None
    if link is None or id_span is None:
        raise ParseError(f"lien ou numéro de décision introuvable (node {node_id})")

    id_decision = id_span.get_text(strip=True)
    title = " ".join(s for s in link.stripped_strings if s != id_decision)

    type_tag = card.select_one(".search-index__footer > p")
    time_tag = card.select_one(".search-index__footer time[datetime]")

    return ListingItem(
        id_decision=id_decision,
        title=title,
        url=urljoin(base_url, link["href"]),
        decision_type=type_tag.get_text(strip=True) if type_tag else None,
        decision_date=_parse_date(time_tag["datetime"]) if time_tag else None,
        sectors=[a.get_text(strip=True) for a in card.select(".field--name-field-sector a")],
        node_id=str(node_id) if node_id else None,
    )


def _parse_date(value: str) -> date:
    """Lit l'attribut datetime ISO (ex. 2026-07-17T12:00:00Z) plutôt que la date en texte."""
    return datetime.fromisoformat(value).date()
