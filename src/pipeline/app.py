from __future__ import annotations

import os

from celery import Celery

from .schedule import BEAT_SCHEDULE, TIMEZONE

# Hors Compose (tests, Windows) : aucune connexion n'est ouverte à l'import.
DEFAULT_BROKER_URL = "redis://127.0.0.1:6379/0"

app = Celery(
    "legal-data-pipeline",
    broker=os.environ.get("CELERY_BROKER_URL", DEFAULT_BROKER_URL),
    include=["src.pipeline.tasks"],
)
app.conf.update(
    timezone=TIMEZONE,
    enable_utc=True,
    beat_schedule=BEAT_SCHEDULE,
    # La chaîne transmet ses résultats dans les messages : pas de backend de résultats.
    task_ignore_result=True,
    # Étapes lourdes et séquentielles : une à la fois, chacune dans un processus neuf.
    worker_concurrency=1,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1,
    # Un worker tué en cours d'étape ne la rejoue pas ; le verrou expire.
    task_acks_late=False,
    # Les print des scripts sont des logs d'information, pas des avertissements.
    worker_redirect_stdouts_level="INFO",
    broker_connection_retry_on_startup=True,
)
