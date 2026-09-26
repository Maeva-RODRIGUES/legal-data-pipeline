from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import quote

from src.search.query import DEFAULT_TITLE_BOOST, number_query, search_body, title_query

from .display import display_title

MAX_RESULT_WINDOW = 10_000  # index.max_result_window d'Elasticsearch (valeur par défaut)
# Champs renvoyés par la recherche : ni le texte intégral ni les attributs.
SOURCE_FIELDS = [
    "source",
    "external_id",
    "decision_number",
    "issuer",
    "decision_type",
    "decision_date",
    "title",
    "sectors",
    "url",
    "has_text",
]
HIGHLIGHT = {
    "encoder": "html",  # texte source échappé : seules les balises <mark> sont du HTML
    "pre_tags": ["<mark>"],
    "post_tags": ["</mark>"],
    "fields": {
        "title": {"number_of_fragments": 0},
        "text": {"fragment_size": 150, "number_of_fragments": 3},
    },
}


@dataclass(frozen=True)
class Filters:
    """Plusieurs valeurs d'un même filtre : OU ; filtres différents : ET."""

    source: Sequence[str] = field(default_factory=tuple)
    decision_type: Sequence[str] = field(default_factory=tuple)
    date_from: date | None = None
    date_to: date | None = None
    sector: Sequence[str] = field(default_factory=tuple)

    def clauses(self) -> list[dict[str, Any]]:
        clauses: list[dict[str, Any]] = []
        for index_field, values in (
            ("source", self.source),
            ("decision_type", self.decision_type),
            ("sectors", self.sector),
        ):
            if values:
                clauses.append({"terms": {index_field: list(values)}})
        if self.date_from is not None or self.date_to is not None:
            bounds = {}
            if self.date_from is not None:
                bounds["gte"] = self.date_from.isoformat()
            if self.date_to is not None:
                bounds["lte"] = self.date_to.isoformat()
            clauses.append({"range": {"decision_date": bounds}})
        return clauses


def build_query(q: str | None, number: str | None, filters: Filters) -> dict[str, Any]:
    """Requête évaluée de query.py, inchangée ; les filtres l'entourent sans toucher au score."""
    query = title_query(q, DEFAULT_TITLE_BOOST) if number is None else number_query(number)
    clauses = filters.clauses()
    if clauses:
        query = {"bool": {"must": [query], "filter": clauses}}
    return query


def build_body(
    q: str | None, number: str | None, filters: Filters, page: int, page_size: int
) -> dict[str, Any]:
    """Corps de search_body, complété par la pagination, les champs et le surlignage."""
    body = search_body(build_query(q, number, filters))
    body |= {"from": (page - 1) * page_size, "size": page_size, "_source": SOURCE_FIELDS}
    if number is None:
        body["highlight"] = HIGHLIGHT  # la recherche par numéro n'a rien à surligner
    return body


def detail_path(source: str, external_id: str) -> str:
    """Identifiant en paramètre de requête : les URL ADLC (/, //) ne passent pas dans un chemin."""
    return f"/decisions/{source}?id={quote(external_id, safe='')}"


def format_hit(hit: Mapping[str, Any]) -> dict[str, Any]:
    doc = hit["_source"]
    decision_date = (
        None if doc.get("decision_date") is None else date.fromisoformat(doc["decision_date"])
    )
    highlight = hit.get("highlight", {})
    return {
        "source": doc["source"],
        "external_id": doc["external_id"],
        "decision_number": doc.get("decision_number"),
        "issuer": doc.get("issuer"),
        "decision_type": doc.get("decision_type"),
        "decision_date": decision_date,
        "title": doc.get("title"),
        "display_title": display_title(
            doc.get("title"),
            doc.get("issuer"),
            decision_date,
            doc.get("decision_number"),
            doc["external_id"],
        ),
        "sectors": doc.get("sectors") or [],
        "url": doc.get("url"),
        "has_text": doc.get("has_text", False),
        "score": hit.get("_score"),
        "highlights": {
            "title": highlight.get("title", []),
            "text": highlight.get("text", []),
        },
        "detail_path": detail_path(doc["source"], doc["external_id"]),
    }


def total_hits(response: Mapping[str, Any]) -> int:
    return response["hits"]["total"]["value"]  # exact : track_total_hits de search_body


def format_hits(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [format_hit(hit) for hit in response["hits"]["hits"]]
