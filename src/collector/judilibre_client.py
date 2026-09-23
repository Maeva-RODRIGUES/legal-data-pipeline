from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx

BASE_URL = "https://api.piste.gouv.fr/cassation/judilibre/v1.0"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class JudilibreError(Exception):

    class JudilibreClient:
        def __init__(
            self,
            api_key: str,
            base_url: str = BASE_URL,
            max_retries: int = 5,
            timeout: float = 30.0,
            transport: httpx.BaseTransport | None = None,  # inject for tests
            sleep=time.sleep,                               # inject for tests
        ) -> None:
            self._http = httpx.Client(
                base_url=base_url,
                headers={"KeyId": api_key, "Accept": "application/json"},
                timeout=timeout,
                transport=transport,
            )
            self.max_retries = max_retries
            self._sleep = sleep

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._http.get(path, params=params)
            except httpx.TransportError as exc:  # coupure réseau, timeout…
                last_error = exc
                wait = min(2 ** attempt, 60)
            else:
                if response.status_code == 200:
                    return response.json()
                if response.status_code not in RETRYABLE_STATUS:
                    raise JudilibreError(
                        f"HTTP {response.status_code} sur {path} : {response.text[:200]}"
                    )
                last_error = JudilibreError(f"HTTP {response.status_code} sur {path}")
                retry_after = response.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 60)
            self._sleep(wait)
        raise JudilibreError(f"Échec après {self.max_retries} tentatives sur {path}") from last_error

    def export(
        self,
        date_start: str,
        date_end: str,
        batch_size: int = 100,
        **filters: Any,
    ) -> Iterator[dict[str, Any]]:

        batch = 0
        while True:
            params = {
                "date_start": date_start,
                "date_end": date_end,
                "batch": batch,
                "batch_size": batch_size,
                **filters,
            }
            data = self._get("/export", params)
            results = data.get("results", [])
            yield from results
            if not results or not data.get("next_batch"):
                return
            batch += 1

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "JudilibreClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
