from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

import httpx
import ijson

SOURCE = "adlc-opendata"


def download(url: str, dest: Path, timeout: float = 120.0) -> Path:
    """Télécharge le fichier en flux, via un fichier temporaire renommé à la fin."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=timeout) as response:
        response.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)
    tmp.replace(dest)
    return dest


def iter_decisions(f: BinaryIO) -> Iterator[dict[str, Any]]:
    """Parcourt le tableau JSON décision par décision, sans le charger en mémoire."""
    yield from ijson.items(f, "item", use_float=True)


def external_id(decision: dict[str, Any]) -> str | None:
    """Identifiant stable : l'URL, unique, contrairement à id_decision (doublons observés)."""
    url = (decision.get("url_site") or "").strip()
    return url or None
