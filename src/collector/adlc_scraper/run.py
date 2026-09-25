from __future__ import annotations

import os
from dataclasses import asdict
from datetime import date
from typing import Any

from dotenv import load_dotenv

from src.collector.adlc_opendata.ingest import SOURCE as OPENDATA_SOURCE
from src.storage.bronze_store import BronzeStore

from .client import AdlcClient
from .parsers import ListingItem, parse_listing

SOURCE = "adlc-scraper"
# Seule page visitée : ni pagination, ni liens de secteur, ni pages de détail.
LISTING_PATH = "/fr/liste-des-decisions-et-avis"


def to_payload(item: ListingItem) -> dict[str, Any]:
    """Payload JSON déterministe (pas d'horodatage de collecte) : deux runs donnent le même hash."""
    payload = asdict(item)
    payload["decision_date"] = item.decision_date.isoformat() if item.decision_date else None
    return payload


def normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


def save_items(store: BronzeStore, items: list[ListingItem], run_id: int) -> dict[str, int]:
    counts = {"fetched": 0, "new": 0, "changed": 0, "unchanged": 0}
    for item in items:
        counts["fetched"] += 1
        counts[store.save(SOURCE, item.url, to_payload(item), run_id)] += 1
    return counts


def opendata_urls(store: BronzeStore) -> set[str]:
    rows = store.conn.execute(
        "SELECT external_id FROM bronze.raw_documents WHERE source = %s", (OPENDATA_SOURCE,)
    ).fetchall()
    return {normalize_url(row[0]) for row in rows}


def find_missing(items: list[ListingItem], known_urls: set[str]) -> list[ListingItem]:
    """Décisions listées sur le site mais absentes de l'open data, dans l'ordre de la page."""
    return [item for item in items if normalize_url(item.url) not in known_urls]


def main() -> None:
    load_dotenv()
    store = BronzeStore(os.environ["DATABASE_URL"])
    today = date.today()
    run_id = store.start_run(SOURCE, today, today, "listing")
    print(f"Run {run_id} : première page de {LISTING_PATH}")

    counts = {"fetched": 0, "new": 0, "changed": 0}
    try:
        with AdlcClient() as client:
            items = parse_listing(client.get_html(LISTING_PATH))
        counts = save_items(store, items, run_id)
        missing = find_missing(items, opendata_urls(store))
    except Exception as exc:
        store.conn.rollback()
        store.finish_run(run_id, "failed", counts, error=str(exc)[:1000])
        raise
    else:
        store.finish_run(run_id, "success", counts)
        print(f"Run {run_id} terminé : {counts}")
    finally:
        store.close()

    print(f"{len(missing)} décision(s) sur le site absente(s) de {OPENDATA_SOURCE} :")
    for item in missing:
        print(f"  {item.id_decision} ({item.decision_date}) {item.url}")


if __name__ == "__main__":
    main()
