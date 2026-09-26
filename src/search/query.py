from __future__ import annotations

from typing import Any

TOP_K = 10
DEFAULT_TITLE_BOOST = 2.0  # choisi après évaluation : égal à 3 sur l'échantillon, plus petit


def number_query(number: str) -> dict[str, Any]:
    """Numéro exact ; le normaliseur folded du mapping s'applique aussi à la valeur cherchée."""
    return {"term": {"decision_number": number}}


def title_query(text: str, boost: float) -> dict[str, Any]:
    """Requête plein texte de la future API : titre pondéré, texte intégral."""
    return {
        "multi_match": {
            "query": text,
            "fields": [f"title^{format_boost(boost)}", "text"],
            "type": "best_fields",  # valeur par défaut, explicite pour figer la requête
        }
    }


def format_boost(boost: float) -> str:
    """3.0 -> "3", 1.5 -> "1.5"."""
    return f"{boost:g}"


def search_body(query: dict[str, Any]) -> dict[str, Any]:
    """Top 10, total exact (sinon plafonné à 10 000), identifiants seuls."""
    return {"query": query, "size": TOP_K, "track_total_hits": True, "_source": False}
