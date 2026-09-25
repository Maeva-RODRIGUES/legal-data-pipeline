from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .index import ALIAS, INDEX_PATTERN, INDEX_PREFIX, IndexClient, index_name


@dataclass
class RebuildResult:
    index_name: str
    silver_counts: dict[str, int]
    indexed_counts: dict[str, int] | None = None  # None : index non compté
    rejected_counts: Counter[str] = field(default_factory=Counter)
    alias_switched: bool = False
    previous_index: str | None = None
    deleted_indexes: list[str] = field(default_factory=list)
    reason: str | None = None  # pourquoi l'alias n'a pas été basculé
    warnings: list[str] = field(default_factory=list)  # échecs du nettoyage après bascule


class RebuildError(Exception):
    """Échec avant la bascule : l'alias n'a pas bougé ; result porte ce qui est connu."""

    def __init__(self, message: str, result: RebuildResult) -> None:
        super().__init__(message)
        self.result = result


def counts_match(
    silver: Mapping[str, int], indexed: Mapping[str, int] | None, rejected: Counter[str]
) -> bool:
    return bool(silver) and indexed == silver and not any(rejected.values())


def mismatch_reason(result: RebuildResult) -> str:
    if not result.silver_counts:
        return "Silver est vide"
    indexed = result.indexed_counts or {}
    sources = sorted(set(result.silver_counts) | set(indexed) | set(result.rejected_counts))
    details = [
        f"{source} : {result.silver_counts.get(source, 0)} attendue(s), "
        f"{indexed.get(source, 0)} indexée(s), {result.rejected_counts[source]} rejetée(s)"
        for source in sources
        if result.silver_counts.get(source) != indexed.get(source) or result.rejected_counts[source]
    ]
    return "comptes différents (" + " ; ".join(details) + ")"


def previous_index(client: IndexClient) -> str | None:
    if client.is_index(ALIAS):
        raise ValueError(f"{ALIAS} est un index et non un alias : à renommer à la main")
    targets = client.alias_targets(ALIAS)
    if len(targets) > 1:
        raise ValueError(f"l'alias {ALIAS} pointe vers plusieurs index : {', '.join(targets)}")
    return targets[0] if targets else None


def discard(client: IndexClient, name: str) -> None:
    """Supprime le nouvel index au mieux, jamais s'il est déjà derrière l'alias."""
    try:
        if name not in client.alias_targets(ALIAS):
            client.delete_index(name)
    except Exception:
        pass  # l'erreur d'origine reste celle à signaler


def rebuild(
    client: IndexClient,
    docs: Iterable[tuple[str, dict[str, Any]]],
    silver_counts: Mapping[str, int],
    mapping: Mapping[str, Any],
    now: datetime,
) -> RebuildResult:
    """Construit un nouvel index et y bascule l'alias seulement si les comptes concordent."""
    result = RebuildResult(index_name(now), dict(silver_counts))
    name = result.index_name
    created = False
    try:
        result.previous_index = previous_index(client)
        client.create_index(name, mapping)
        created = True
        client.bulk_index(name, docs, result.rejected_counts)
        client.refresh(name)
        result.indexed_counts = client.count_by_source(name)
        if not counts_match(result.silver_counts, result.indexed_counts, result.rejected_counts):
            result.reason = mismatch_reason(result)
            client.delete_index(name)
            return result
        previous = [result.previous_index] if result.previous_index else []
        client.switch_alias(ALIAS, name, previous)
    except Exception as exc:
        if created:
            discard(client, name)
        raise RebuildError(str(exc), result) from exc
    result.alias_switched = True
    clean_up(client, result)
    return result


def clean_up(client: IndexClient, result: RebuildResult) -> None:
    """Garde le nouvel index et le précédent ; un index hors motif n'est jamais touché."""
    keep = {result.index_name, result.previous_index}
    try:
        names = client.list_indexes(INDEX_PREFIX)
    except Exception as exc:
        result.warnings.append(f"liste des index impossible : {exc}")
        return
    for name in names:
        if name in keep or not INDEX_PATTERN.match(name):
            continue
        try:
            client.delete_index(name)
        except Exception as exc:
            result.warnings.append(f"suppression de {name} impossible : {exc}")
        else:
            result.deleted_indexes.append(name)
