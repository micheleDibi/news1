"""Test di raggiungibilita' degli URL estratti + detect del `formato_link`.

Strategia:
  1. HEAD request con follow_redirects=True, timeout configurabile.
  2. Se HEAD ritorna 405/501 -> fallback GET con stream=True (legge solo
     gli header HTTP, non scarica il body intero).
  3. Status 2xx -> attivo=True. Altrimenti attivo=False con motivo.

Detect formato:
  - Estensione URL (.pdf -> PDF, .csv -> CSV, default -> HTML).
  - Override via Content-Type response (application/pdf, text/csv).

Concorrenza:
  - asyncio.Semaphore(REACHABILITY_CONCURRENCY) per non sovraccaricare i
    server target.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlsplit

import httpx

from .logger import logger
from .settings import get_settings


@dataclass(frozen=True)
class ReachabilityResult:
    url: str
    attivo: bool
    formato_link: str       # 'HTML' | 'PDF' | 'CSV'
    final_url: str | None   # URL dopo redirect (None se non raggiungibile)
    error: str | None       # motivazione se attivo=False


_EXT_TO_FORMATO = {
    ".pdf": "PDF",
    ".csv": "CSV",
}

_CT_TO_FORMATO = {
    "application/pdf": "PDF",
    "text/csv": "CSV",
    "application/csv": "CSV",
}


def _formato_from_url(url: str) -> str:
    """Detect formato_link da estensione URL. Default HTML."""
    path = urlsplit(url).path.lower()
    for ext, fmt in _EXT_TO_FORMATO.items():
        if path.endswith(ext):
            return fmt
    return "HTML"


def _formato_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    ct_main = content_type.split(";", 1)[0].strip().lower()
    return _CT_TO_FORMATO.get(ct_main)


async def _check_one(client: httpx.AsyncClient, url: str) -> ReachabilityResult:
    """Test reachability di un singolo URL."""
    formato_url = _formato_from_url(url)

    async def _try_method(method: str) -> httpx.Response | None:
        try:
            return await client.request(method, url, follow_redirects=True)
        except httpx.HTTPError as e:
            logger.debug("[reachability] {} {} -> {}: {}", method, url, type(e).__name__, e)
            return None

    # Prova HEAD
    resp = await _try_method("HEAD")
    error: str | None = None

    # Fallback GET se HEAD fallisce o ritorna 405/501
    if resp is None or resp.status_code in (405, 501):
        if resp is None:
            error = "HEAD network error"
        resp = await _try_method("GET")

    if resp is None:
        # Doppio fallimento di rete: probabilmente DNS / SSL / timeout
        return ReachabilityResult(
            url=url, attivo=False, formato_link=formato_url,
            final_url=None,
            error=error or "GET network error",
        )

    # 2xx = attivo
    if 200 <= resp.status_code < 300:
        # Override formato se Content-Type lo dichiara
        formato = _formato_from_content_type(resp.headers.get("content-type")) or formato_url
        return ReachabilityResult(
            url=url, attivo=True, formato_link=formato,
            final_url=str(resp.url),
            error=None,
        )

    # 3xx (improbabile con follow_redirects=True, ma per completezza)
    # 4xx / 5xx -> non attivo
    return ReachabilityResult(
        url=url, attivo=False, formato_link=formato_url,
        final_url=str(resp.url) if resp else None,
        error=f"HTTP {resp.status_code}",
    )


async def check_many(urls: Iterable[str]) -> list[ReachabilityResult]:
    """Test reachability su una lista di URL con concorrenza limitata."""
    settings = get_settings()
    urls_list = list(urls)
    if not urls_list:
        return []

    logger.info(
        "[reachability] testo {} URL (concurrency={}, timeout={}s)",
        len(urls_list), settings.reachability_concurrency, settings.reachability_timeout_s,
    )

    sem = asyncio.Semaphore(settings.reachability_concurrency)
    timeout = httpx.Timeout(settings.reachability_timeout_s)
    headers = {"User-Agent": settings.http_user_agent}

    results: list[ReachabilityResult] = []

    async with httpx.AsyncClient(
        http2=True,
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
    ) as client:
        async def _bounded(url: str) -> ReachabilityResult:
            async with sem:
                return await _check_one(client, url)

        coros = [_bounded(u) for u in urls_list]
        for idx, coro in enumerate(asyncio.as_completed(coros), start=1):
            res = await coro
            results.append(res)
            if idx % 25 == 0 or idx == len(urls_list):
                logger.info(
                    "[reachability] progress {}/{}",
                    idx, len(urls_list),
                )

    # Riordina secondo l'ordine di input (asyncio.as_completed non lo garantisce)
    by_url = {r.url: r for r in results}
    return [by_url[u] for u in urls_list if u in by_url]
