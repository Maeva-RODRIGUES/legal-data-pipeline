from __future__ import annotations

from typing import Any

import redis

LOCK_KEY = "legal-data-pipeline:pipeline-lock"
LOCK_TTL = 6 * 3600  # secondes : libère le verrou d'un worker tombé en cours de run


def redis_client(url: str) -> redis.Redis:
    """Même Redis que le broker Celery."""
    return redis.Redis.from_url(url, decode_responses=True)


class PipelineLock:
    """Un seul run du pipeline à la fois ; le jeton est l'identifiant du run pipeline."""

    def __init__(self, client: Any, key: str = LOCK_KEY, ttl: int = LOCK_TTL) -> None:
        self.client = client
        self.key = key
        self.ttl = ttl

    def acquire(self, token: str) -> bool:
        return bool(self.client.set(self.key, token, nx=True, ex=self.ttl))

    def holder(self) -> str | None:
        return self.client.get(self.key)

    def release(self, token: str) -> None:
        """Ne libère que son propre verrou, pas celui d'un run lancé après son expiration.

        GET puis DELETE, non atomiques : seul le détenteur libère, avec un TTL de plusieurs
        heures, la fenêtre de course est négligeable.
        """
        if self.holder() == token:
            self.client.delete(self.key)
