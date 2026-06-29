"""HTTP client condiviso con throttling per host.

Garantisce un delay minimo (default 1s) tra request consecutive verso
lo stesso host, indipendentemente da quante fonti stiano scrappando.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from .logger import logger
from .settings import get_settings


# Timestamp ultima request per host (monotonic time)
_HOST_LAST_REQUEST: dict[str, float] = {}


def _throttle_delay_s() -> float:
    return get_settings().host_throttle_delay_s


async def _wait_for_host(host: str) -> None:
    delay = _throttle_delay_s()
    if delay <= 0:
        return
    last = _HOST_LAST_REQUEST.get(host, 0.0)
    elapsed = time.monotonic() - last
    if elapsed < delay:
        sleep_s = delay - elapsed
        logger.debug("[http] throttle host={} sleep={:.2f}s", host, sleep_s)
        await asyncio.sleep(sleep_s)
    _HOST_LAST_REQUEST[host] = time.monotonic()


def _default_headers() -> dict[str, str]:
    return {
        "User-Agent": get_settings().http_user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    }


async def fetch_html(url: str, *, timeout_s: float = 30.0) -> str:
    """GET una pagina HTML con throttle per host. Solleva su 4xx/5xx."""
    host = urlsplit(url).netloc
    await _wait_for_host(host)

    async with httpx.AsyncClient(
        http2=True,
        timeout=httpx.Timeout(timeout_s),
        follow_redirects=True,
        headers=_default_headers(),
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text


async def fetch_bytes(url: str, *, timeout_s: float = 60.0) -> bytes:
    """GET il contenuto binario (per CSV/PDF/XLSX). Solleva su 4xx/5xx."""
    host = urlsplit(url).netloc
    await _wait_for_host(host)

    async with httpx.AsyncClient(
        http2=True,
        timeout=httpx.Timeout(timeout_s),
        follow_redirects=True,
        headers=_default_headers(),
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content
