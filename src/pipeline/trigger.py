from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime

from .app import app
from .runlog import MANUAL
from .schedule import next_run
from .tasks import start_pipeline


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lance le pipeline complet sans attendre 03:33")
    parser.add_argument(
        "--with-opendata",
        action="store_true",
        help="ingérer l'open data en tête de chaîne (sinon : seulement la nuit du lundi)",
    )
    parser.add_argument(
        "--next-run",
        action="store_true",
        help="afficher la prochaine exécution planifiée, sans rien lancer",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.next_run:
        run = next_run(app, datetime.now(UTC))
        print(f"Prochaine exécution planifiée : {run:%Y-%m-%d %H:%M} ({run.tzinfo})")
        return
    result = start_pipeline.delay(trigger=MANUAL, with_opendata=args.with_opendata)
    opendata = "avec" if args.with_opendata else "sans"
    print(f"Pipeline déclenché ({opendata} open data), tâche {result.id}")
    print("Suivi : podman logs -f legal-data-pipeline-worker-1")


if __name__ == "__main__":
    main()
