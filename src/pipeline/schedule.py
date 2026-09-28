from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from celery import Celery
from celery.schedules import crontab

from .runlog import NIGHTLY

# Fuseau explicite : 03:33 reste 03:33 à Paris toute l'année. Hors de la plage 02:00-03:00
# des changements d'heure, l'horaire n'est ni sauté ni exécuté deux fois.
TIMEZONE = "Europe/Paris"
HOUR, MINUTE = 3, 33
BEAT_SCHEDULE = {
    "nightly-pipeline": {
        "task": "src.pipeline.tasks.start_pipeline",
        "schedule": crontab(hour=HOUR, minute=MINUTE),
        "kwargs": {"trigger": NIGHTLY},
    }
}


def next_run(app: Celery, now: datetime) -> datetime:
    """Prochaine exécution nocturne après now, dans le fuseau de l'application."""
    tz = ZoneInfo(app.conf.timezone)
    local_now = now.astimezone(tz)
    schedule = crontab(hour=HOUR, minute=MINUTE, app=app, nowfun=lambda: local_now)
    # Addition en UTC : en heure locale, elle ignorerait un changement d'heure intermédiaire.
    return (now.astimezone(UTC) + schedule.remaining_estimate(local_now)).astimezone(tz)
