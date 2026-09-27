from __future__ import annotations

import importlib
import os
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

OPENDATA_URL_VAR = "ADLC_OPENDATA_URL"


@dataclass(frozen=True)
class Step:
    """Une étape du pipeline : le point d'entrée d'un script existant."""

    name: str  # source du script dans bronze.collection_runs
    module: str
    blocking: bool
    network: bool
    takes_argv: bool  # main accepte-t-il argv ?


# Ordre de la chaîne ; l'open data n'y figure que la nuit du lundi ou sur demande.
STEPS: dict[str, Step] = {
    step.name: step
    for step in (
        Step("adlc-opendata", "src.collector.adlc_opendata.run", False, True, True),
        Step("judilibre", "src.collector.judilibre.run", True, True, True),
        Step("adlc-scraper", "src.collector.adlc_scraper.run", False, True, False),
        Step("silver", "src.silver.run", True, False, False),
        Step("search", "src.search.run", True, False, False),
        Step("search-eval", "src.search.evaluate", True, False, True),
        Step("quality", "src.quality.run", True, False, True),
    )
}
OPENDATA = "adlc-opendata"


class StepFailed(Exception):
    """Code de sortie non nul, ou configuration manquante."""


def step_names(with_opendata: bool) -> list[str]:
    return [name for name in STEPS if with_opendata or name != OPENDATA]


def step_argv(step: Step, env: Mapping[str, str]) -> list[str]:
    """Arguments de main : ceux par défaut, sauf l'URL de téléchargement de l'open data."""
    if step.name != OPENDATA:
        return []
    url = env.get(OPENDATA_URL_VAR, "").strip()
    if not url:
        # Sans --url, le script réingérerait en silence l'ancien fichier local.
        raise StepFailed(
            f"{OPENDATA_URL_VAR} manquante : ingestion open data impossible "
            "(aucune réingestion du fichier local)"
        )
    return ["--url", url]


def run_entry_point(step: Step, env: Mapping[str, str] = os.environ) -> None:
    """Appelle le main du script ; un code de sortie non nul fait échouer l'étape."""
    main = importlib.import_module(step.module).main
    try:
        code = main(argv=step_argv(step, env)) if step.takes_argv else main()
    except SystemExit as exc:  # argparse
        code = exc.code
    if code not in (None, 0):
        raise StepFailed(f"{step.name} : code de sortie {code}")


def is_network_error(exc: BaseException) -> bool:
    """Erreur de connexion ou délai dépassé, y compris enveloppée par un client HTTP."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, httpx.TransportError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False
