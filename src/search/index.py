from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from elasticsearch import Elasticsearch, helpers

ALIAS = "decisions"
INDEX_PREFIX = "decisions_"
INDEX_PATTERN = re.compile(r"^decisions_\d{8}_\d{6}$")
CHUNK_SIZE = 500
MAX_CHUNK_BYTES = 20 * 1024 * 1024  # textes jusqu'à 1,2 million de caractères


def index_name(now: datetime) -> str:
    """decisions_YYYYMMDD_HHMMSS en UTC : sans ambiguïté au changement d'heure."""
    return f"{INDEX_PREFIX}{now.astimezone(UTC):%Y%m%d_%H%M%S}"


def source_of(doc_id: str) -> str:
    return doc_id.partition("|")[0]


class IndexClient(Protocol):
    """Surface d'Elasticsearch utilisée par rebuild."""

    def alias_targets(self, alias: str) -> list[str]: ...

    def is_index(self, name: str) -> bool: ...

    def create_index(self, name: str, body: Mapping[str, Any]) -> None: ...

    def bulk_index(
        self, name: str, docs: Iterable[tuple[str, dict[str, Any]]], rejected: Counter[str]
    ) -> None: ...

    def refresh(self, name: str) -> None: ...

    def count_by_source(self, name: str) -> dict[str, int]: ...

    def switch_alias(self, alias: str, new: str, previous: list[str]) -> None: ...

    def list_indexes(self, prefix: str) -> list[str]: ...

    def delete_index(self, name: str) -> None: ...


def parse_count_response(response: Mapping[str, Any]) -> dict[str, int]:
    """Comptes par source d'une agrégation terms, refusés s'ils ne couvrent pas tout l'index."""
    total = response["hits"]["total"]
    agg = response["aggregations"]["by_source"]
    counts = {bucket["key"]: bucket["doc_count"] for bucket in agg["buckets"]}
    in_buckets = sum(counts.values())
    if total["relation"] != "eq" or in_buckets != total["value"]:
        raise ValueError(
            f"comptes par source incomplets : {in_buckets} dans les buckets, "
            f"{total['value']} ({total['relation']}) au total, "
            f"{agg['sum_other_doc_count']} hors buckets"
        )
    return counts


class ElasticsearchIndexClient:
    def __init__(self, es: Elasticsearch) -> None:
        self.es = es

    def alias_targets(self, alias: str) -> list[str]:
        if not self.es.indices.exists_alias(name=alias):
            return []
        return sorted(self.es.indices.get_alias(name=alias))

    def is_index(self, name: str) -> bool:
        # Un alias est résolu vers ses index : la clé n'est le nom demandé que pour un index.
        return name in self.es.indices.get(index=name, ignore_unavailable=True)

    def create_index(self, name: str, body: Mapping[str, Any]) -> None:
        self.es.indices.create(
            index=name, settings=body.get("settings"), mappings=body.get("mappings")
        )

    def bulk_index(
        self, name: str, docs: Iterable[tuple[str, dict[str, Any]]], rejected: Counter[str]
    ) -> None:
        """Envoi en masse ; un document refusé est compté, une erreur de transport lève."""
        actions = ({"_index": name, "_id": doc_id, "_source": doc} for doc_id, doc in docs)
        for ok, item in helpers.streaming_bulk(
            self.es,
            actions,
            chunk_size=CHUNK_SIZE,
            max_chunk_bytes=MAX_CHUNK_BYTES,
            raise_on_error=False,
            raise_on_exception=True,
        ):
            if not ok:
                rejected[source_of(item["index"]["_id"])] += 1

    def refresh(self, name: str) -> None:
        self.es.indices.refresh(index=name)

    def count_by_source(self, name: str) -> dict[str, int]:
        response = self.es.search(
            index=name,
            size=0,
            track_total_hits=True,
            aggs={"by_source": {"terms": {"field": "source", "size": 100}}},
        )
        return parse_count_response(response.body)

    def switch_alias(self, alias: str, new: str, previous: list[str]) -> None:
        # Un seul appel : Elasticsearch applique retraits et ajout de façon atomique.
        actions = [{"remove": {"index": old, "alias": alias}} for old in previous]
        actions.append({"add": {"index": new, "alias": alias}})
        self.es.indices.update_aliases(actions=actions)

    def list_indexes(self, prefix: str) -> list[str]:
        return sorted(self.es.indices.get(index=f"{prefix}*", expand_wildcards="open"))

    def delete_index(self, name: str) -> None:
        self.es.indices.delete(index=name)
