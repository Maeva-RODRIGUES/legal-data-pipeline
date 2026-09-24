from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from src.storage.bronze_store import BronzeStore

from .ingest import SOURCE, download, external_id, iter_decisions

DEFAULT_FILE = Path("data/raw/adlc-texte-complet-publications.json")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Open data ADLC -> Bronze")
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE, help="fichier JSON local")
    parser.add_argument(
        "--url",
        help="URL de la ressource data.gouv.fr à télécharger avant l'ingestion",
    )
    args = parser.parse_args()

    if args.url:
        print(f"Téléchargement de {args.url}…")
        download(args.url, args.file)

    store = BronzeStore(os.environ["DATABASE_URL"])
    today = date.today()
    run_id = store.start_run(SOURCE, today, today, "snapshot")
    counts = {"fetched": 0, "new": 0, "changed": 0, "unchanged": 0, "missing_id": 0}
    print(f"Run {run_id} : ingestion de {args.file}")

    try:
        with args.file.open("rb") as f:
            for decision in iter_decisions(f):
                counts["fetched"] += 1
                ext_id = external_id(decision)
                if ext_id is None:
                    counts["missing_id"] += 1
                    continue
                counts[store.save(SOURCE, ext_id, decision, run_id)] += 1
                if counts["fetched"] % 500 == 0:
                    store.conn.commit()
                    print(f"  {counts['fetched']} décisions traitées…")
    except Exception as exc:
        store.conn.rollback()
        store.finish_run(run_id, "failed", counts, error=str(exc)[:1000])
        raise
    else:
        store.finish_run(run_id, "success", counts)
        print(f"Run {run_id} terminé : {counts}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
