from __future__ import annotations

import argparse
import os
from datetime import date, timedelta

from dotenv import load_dotenv

from .bronze_store import BronzeStore
from .judilibre_client import JudilibreClient

SOURCE = "judilibre"
DEFAULT_WINDOW_DAYS = 7


def resolve_dates(args: argparse.Namespace, store: BronzeStore) -> tuple[date, date]:
    end = date.fromisoformat(args.end) if args.end else date.today()
    if args.start:
        return date.fromisoformat(args.start), end
    last_end = store.last_successful_end(SOURCE, args.date_type)
    start = last_end + timedelta(days=1) if last_end else end - timedelta(days=DEFAULT_WINDOW_DAYS)
    return start, end


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Collecte Judilibre -> Bronze")
    parser.add_argument("--start", help="date de début AAAA-MM-JJ (sinon : incrémental)")
    parser.add_argument("--end", help="date de fin AAAA-MM-JJ (défaut : aujourd'hui)")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--date-type",
        choices=["update", "creation"],
        default="update",
        help=(
            "date filtrée par l'API (défaut : update, pour ne pas rater les publications tardives)"
        ),
    )
    args = parser.parse_args()

    store = BronzeStore(os.environ["DATABASE_URL"])
    start, end = resolve_dates(args, store)
    if start > end:
        print("Rien à collecter : déjà à jour.")
        return

    run_id = store.start_run(SOURCE, start, end, args.date_type)
    counts = {"fetched": 0, "new": 0, "changed": 0, "unchanged": 0, "missing_id": 0}
    print(f"Run {run_id} : collecte du {start} au {end} (date_type={args.date_type})")

    try:
        with JudilibreClient(os.environ["JUDILIBRE_API_KEY"]) as client:
            for decision in client.scan(
                start.isoformat(),
                end.isoformat(),
                batch_size=args.batch_size,
                date_type=args.date_type,
            ):
                counts["fetched"] += 1
                external_id = decision.get("id")
                if not external_id:
                    counts["missing_id"] += 1
                    continue
                counts[store.save(SOURCE, str(external_id), decision, run_id)] += 1
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
