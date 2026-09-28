from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from datetime import date, timedelta

from dotenv import load_dotenv

from src.storage.bronze_store import BronzeStore

from .client import JudilibreClient

SOURCE = "judilibre"
DEFAULT_WINDOW_DAYS = 7
DEFAULT_LOOKBACK_DAYS = 14


def compute_window(
    last_end: date | None,
    today: date,
    lookback_days: int,
    start: date | None = None,
    end: date | None = None,
) -> tuple[date, date]:
    """Collection window. Without an explicit start, resume lookback_days before the last end.

    The returned start may be after the end: there is then nothing to collect.
    """
    if lookback_days < 0:
        raise ValueError(f"lookback_days doit être positif ou nul (reçu : {lookback_days})")
    end = end or today
    if start:
        return start, end
    if last_end is None:
        return end - timedelta(days=DEFAULT_WINDOW_DAYS), end
    return last_end + timedelta(days=1) - timedelta(days=lookback_days), end


def resolve_dates(args: argparse.Namespace, store: BronzeStore) -> tuple[date, date]:
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None
    last_end = None if start else store.last_successful_end(SOURCE, args.date_type)
    lookback = DEFAULT_LOOKBACK_DAYS if args.lookback_days is None else args.lookback_days
    return compute_window(last_end, date.today(), lookback, start, end)


def non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"entier attendu, reçu : {value!r}") from None
    if number < 0:
        raise argparse.ArgumentTypeError(f"doit être positif ou nul, reçu : {number}")
    return number


def build_parser() -> argparse.ArgumentParser:
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
    parser.add_argument(
        "--lookback-days",
        type=non_negative_int,
        default=None,
        help=(
            "sans --start, reprendre N jours avant la fin du dernier run réussi "
            f"(défaut : {DEFAULT_LOOKBACK_DAYS}, ignoré avec --start)"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    load_dotenv()
    args = build_parser().parse_args(argv)
    if args.start and args.lookback_days is not None:
        print("--lookback-days ignoré : --start est fourni.")

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
