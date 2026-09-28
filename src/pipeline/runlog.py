from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from datetime import date

from src.storage.bronze_store import BronzeStore

SOURCE = "pipeline"
NIGHTLY = "nightly"
MANUAL = "manual"
SKIPPED = "skipped"

StoreFactory = Callable[[], BronzeStore]


def default_store() -> BronzeStore:
    return BronzeStore(os.environ["DATABASE_URL"])


def zero_counts() -> dict[str, int]:
    # Un run de pipeline ne collecte rien lui-même : chaque étape a son propre run.
    return {"fetched": 0, "new": 0, "changed": 0}


def start_pipeline_run(trigger: str, day: date, store_factory: StoreFactory = default_store) -> int:
    """Run en cours dans bronze.collection_runs ; date_type = nightly ou manual."""
    store = store_factory()
    try:
        return store.start_run(SOURCE, day, day, trigger)
    finally:
        store.close()


def finish_pipeline_run(
    run_id: int,
    status: str,
    error: str | None = None,
    store_factory: StoreFactory = default_store,
) -> None:
    store = store_factory()
    try:
        store.finish_run(run_id, status, zero_counts(), error=error)
    finally:
        store.close()


def skip_pipeline_run(
    run_id: int, holder: str | None, store_factory: StoreFactory = default_store
) -> None:
    finish_pipeline_run(run_id, SKIPPED, f"lock held by pipeline run {holder}", store_factory)


def non_blocking_note(failed: Sequence[str]) -> str | None:
    """Note écrite dans error d'un run réussi malgré l'échec d'étapes non bloquantes."""
    if not failed:
        return None
    label = "step" if len(failed) == 1 else "steps"
    return f"non-blocking {label} failed: {', '.join(failed)}"
