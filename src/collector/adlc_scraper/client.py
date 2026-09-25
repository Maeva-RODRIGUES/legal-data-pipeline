from __future__ import annotations

import time
from urllib.parse import urljoin

import httpx
from protego import Protego

from .parsers import BASE_URL

USER_AGENT = "legal-data-pipeline (+https://github.com/Maeva-RODRIGUES/legal-data-pipeline)"
MIN_DELAY = 2.0  # secondes entre deux requêtes, quel que soit le robots.txt
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class AdlcError(Exception):
    """URL interdite par robots.txt, erreur HTTP permanente, ou trop d'échecs."""


class AdlcClient:
    """Client HTTP poli : respecte robots.txt, espace les requêtes, ne suit pas les redirections."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        min_delay: float = MIN_DELAY,
        max_retries: int = 5,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,  # inject for tests
        sleep=time.sleep,  # inject for tests
        clock=time.monotonic,  # inject for tests
    ) -> None:
        # Pas de redirection automatique : la cible pourrait être interdite par robots.txt.
        self._http = httpx.Client(
            base_url=base_url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
        )
        self.base_url = base_url
        self.min_delay = min_delay
        self.max_retries = max_retries
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None
        self._robots: Protego | None = None

    @property
    def delay(self) -> float:
        """Délai entre requêtes : le plus long entre le minimum et le Crawl-delay du site."""
        crawl_delay = self._robots.crawl_delay(USER_AGENT) if self._robots else None
        return max(self.min_delay, crawl_delay or 0)

    def can_fetch(self, url: str) -> bool:
        return self._load_robots().can_fetch(urljoin(self.base_url, url), USER_AGENT)

    def get_html(self, url: str) -> str:
        """Récupère une page autorisée par robots.txt et renvoie son HTML."""
        if not self.can_fetch(url):
            raise AdlcError(f"URL interdite par robots.txt : {url}")
        response = self._get(url)
        if response.status_code != 200:
            raise AdlcError(f"HTTP {response.status_code} sur {url}")
        return response.content.decode("utf-8")

    def _load_robots(self) -> Protego:
        if self._robots is None:
            response = self._get("/robots.txt")
            if response.status_code == 404:
                self._robots = Protego.parse("")  # pas de robots.txt : tout est autorisé
            elif response.status_code == 200:
                self._robots = Protego.parse(response.content.decode("utf-8"))
            else:
                raise AdlcError(f"robots.txt illisible (HTTP {response.status_code})")
        return self._robots

    def _throttle(self) -> None:
        if self._last_request is not None:
            remaining = self.delay - (self._clock() - self._last_request)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request = self._clock()

    def _get(self, url: str) -> httpx.Response:
        """GET avec retries sur 429, 5xx et erreurs réseau ; renvoie les autres réponses."""
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                response = self._http.get(url)
            except httpx.TransportError as exc:  # network failure, timeout...
                last_error = exc
                wait = min(2**attempt, 60)
            else:
                if response.status_code not in RETRYABLE_STATUS:
                    return response
                last_error = AdlcError(f"HTTP {response.status_code} sur {url}")
                retry_after = response.headers.get("Retry-After")
                wait = (
                    int(retry_after)
                    if retry_after and retry_after.isdigit()
                    else min(2**attempt, 60)
                )
            self._sleep(wait)
        raise AdlcError(f"Échec après {self.max_retries} tentatives sur {url}") from last_error

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> AdlcClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
