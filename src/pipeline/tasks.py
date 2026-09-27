from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from celery import chain
from celery.utils.log import get_task_logger

from .app import app
from .lock import PipelineLock, redis_client
from .runlog import (
    NIGHTLY,
    finish_pipeline_run,
    non_blocking_note,
    skip_pipeline_run,
    start_pipeline_run,
)
from .schedule import TIMEZONE
from .steps import STEPS, Step, is_network_error, run_entry_point, step_names

logger = get_task_logger(__name__)

MAX_RETRIES = 3
BACKOFF_SECONDS = 60
SUNDAY = 6

Decision = Literal["retry", "continue", "fail"]


def paris_today() -> date:
    return datetime.now(ZoneInfo(TIMEZONE)).date()


def includes_opendata(trigger: str, day: date, with_opendata: bool) -> bool:
    """Le run nocturne du dimanche ingère l'open data ; un run manuel, sur demande seulement."""
    return with_opendata or (trigger == NIGHTLY and day.weekday() == SUNDAY)


def backoff(retries: int) -> int:
    """60, 120 puis 240 secondes."""
    return BACKOFF_SECONDS * 2**retries


def handle_failure(step: Step, exc: BaseException, retries: int) -> Decision:
    if step.network and is_network_error(exc) and retries < MAX_RETRIES:
        return "retry"
    return "fail" if step.blocking else "continue"


def pipeline_lock() -> PipelineLock:
    return PipelineLock(redis_client(app.conf.broker_url))


def fail_pipeline(run_id: int, error: str) -> None:
    try:
        finish_pipeline_run(run_id, "failed", error)
    finally:
        pipeline_lock().release(str(run_id))


def build_chain(run_id: int, names: Sequence[str]) -> chain:
    """Chaque étape reçoit de la précédente la liste des étapes non bloquantes en échec."""
    first, *rest = names
    return chain(
        run_step.si([], first, run_id),
        *(run_step.s(name, run_id) for name in rest),
        finish_pipeline.s(run_id),
    )


@app.task
def start_pipeline(trigger: str = NIGHTLY, with_opendata: bool = False) -> int:
    day = paris_today()
    run_id = start_pipeline_run(trigger, day)  # son identifiant sert de jeton au verrou
    lock = pipeline_lock()
    if not lock.acquire(str(run_id)):
        holder = lock.holder()
        skip_pipeline_run(run_id, holder)
        logger.warning("Run pipeline %s ignoré : le run %s est en cours", run_id, holder)
        return run_id

    names = step_names(includes_opendata(trigger, day, with_opendata))
    try:
        build_chain(run_id, names).apply_async()
    except Exception:
        fail_pipeline(run_id, "start")
        raise
    logger.info("Run pipeline %s (%s) : %s", run_id, trigger, ", ".join(names))
    return run_id


@app.task(bind=True, max_retries=MAX_RETRIES)
def run_step(self, failed: list[str], name: str, run_id: int) -> list[str]:
    step = STEPS[name]
    logger.info("Run pipeline %s : étape %s", run_id, name)
    try:
        run_entry_point(step)
    except Exception as exc:
        retries = self.request.retries
        decision = handle_failure(step, exc, retries)
        if decision == "retry":
            countdown = backoff(retries)
            logger.warning(
                "Étape %s : erreur réseau (%s), tentative %d/%d dans %d s",
                name,
                exc,
                retries + 1,
                MAX_RETRIES,
                countdown,
            )
            raise self.retry(exc=exc, countdown=countdown) from exc
        if decision == "continue":
            logger.warning("Étape non bloquante %s en échec : %s", name, exc, exc_info=True)
            return [*failed, name]
        logger.error("Étape %s en échec : arrêt du run pipeline %s", name, run_id)
        fail_pipeline(run_id, name)
        raise
    return failed


@app.task
def finish_pipeline(failed: list[str], run_id: int) -> None:
    try:
        finish_pipeline_run(run_id, "success", non_blocking_note(failed))
    finally:
        pipeline_lock().release(str(run_id))
    logger.info("Run pipeline %s terminé", run_id)
