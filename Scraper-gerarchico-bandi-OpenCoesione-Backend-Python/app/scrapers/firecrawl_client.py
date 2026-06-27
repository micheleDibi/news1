"""Client Firecrawl per il scraper di fase 1.

Firecrawl e' la fonte primaria di scraping HTML: gestisce JS-render, Cloudflare,
waitFor, anti-bot. Se Firecrawl non e' disponibile (chiave assente in dev) o
fallisce, ricadiamo su httpx per non bloccare lo scraper.

API esposta:

    client = get_firecrawl_client()
    result = client.scrape(url)
    # result e' un FetchResult con html / markdown / status_code / fetched_via / error

`fetched_via` permette di tracciare nei log da quale strategia e' arrivato il
contenuto della pagina, utile per capire dove Firecrawl aggiunge valore.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchResult:
    """Risultato normalizzato di una fetch HTML.

    `fetched_via` (enum di stringhe):
      - 'firecrawl_stealth': stealth proxy ha funzionato
      - 'firecrawl_auto': auto proxy ha funzionato dopo retry
      - 'httpx_fallback': Firecrawl ha esaurito i tentativi, httpx ha salvato il giorno
      - 'firecrawl_unavailable': chiave non configurata, usato direttamente httpx
    """

    html: str | None
    markdown: str | None
    status_code: int | None
    fetched_via: str
    error: str | None


class FirecrawlClient:
    """Wrapper attorno a `firecrawl-py` con retry stealth → auto → httpx.

    Costruito una volta sola (singleton via `get_firecrawl_client()`). Se la
    chiave API e' assente, l'oggetto e' un passthrough che usa SEMPRE httpx,
    cosi' il dev locale e i test continuano a girare.
    """

    def __init__(self, api_key: str | None, timeout_seconds: int = 30) -> None:
        self._api_key = (api_key or "").strip() or None
        self._timeout_seconds = timeout_seconds
        self._firecrawl_app: Any | None = None
        if self._api_key:
            try:
                from firecrawl import Firecrawl  # type: ignore

                self._firecrawl_app = Firecrawl(api_key=self._api_key)
            except Exception as e:  # pragma: no cover — import fallback
                logger.warning("Firecrawl SDK non disponibile, ricado su httpx: %s", e)
                self._firecrawl_app = None
        else:
            logger.info("FIRECRAWL_API_KEY non configurata: scraper usa httpx-only")

    @property
    def available(self) -> bool:
        return self._firecrawl_app is not None

    # ------------------------------------------------------------------
    # API pubblica
    # ------------------------------------------------------------------

    def scrape(self, url: str) -> FetchResult:
        """Scarica una pagina HTML provando in ordine: stealth, auto, httpx.

        Ritorna SEMPRE un FetchResult (anche in caso di fallimento totale —
        `html` puo' essere None e `error` valorizzato).
        """
        if not self.available:
            return self._httpx_fetch(url, fetched_via="firecrawl_unavailable")

        # Strategia 1: stealth proxy. Buon compromesso qualita'/velocita'.
        result = self._firecrawl_attempt(
            url,
            fetched_via="firecrawl_stealth",
            kwargs={"proxy": "stealth", "timeout": 30000, "wait_for": 1500},
        )
        if result.html:
            return result

        # Strategia 2: auto proxy con waitFor piu' lungo (siti SPA pesanti).
        result = self._firecrawl_attempt(
            url,
            fetched_via="firecrawl_auto",
            kwargs={"proxy": "auto", "timeout": 45000, "wait_for": 2500},
        )
        if result.html:
            return result

        # Hard fallback: httpx come faceva lo scraper prima della batch 2.
        logger.warning("Firecrawl esaurito per %s: fallback httpx", url)
        return self._httpx_fetch(url, fetched_via="httpx_fallback")

    # ------------------------------------------------------------------
    # Implementazione interna
    # ------------------------------------------------------------------

    def _firecrawl_attempt(
        self,
        url: str,
        *,
        fetched_via: str,
        kwargs: dict[str, Any],
    ) -> FetchResult:
        assert self._firecrawl_app is not None  # garantito da scrape()
        try:
            try:
                raw = self._firecrawl_app.scrape(url, formats=["markdown", "html"], **kwargs)
            except TypeError as e:
                # Versioni vecchie dell'SDK non accettano tutte le opzioni: retry "plain".
                logger.warning(
                    "Firecrawl scrape ha rifiutato kwargs %s per %s: %s — retry plain",
                    kwargs, url, e,
                )
                raw = self._firecrawl_app.scrape(url, formats=["markdown", "html"])
        except Exception as e:
            logger.warning("Firecrawl %s eccezione per %s: %s", fetched_via, url, e)
            return FetchResult(
                html=None, markdown=None, status_code=None,
                fetched_via=fetched_via, error=str(e),
            )

        success = bool(getattr(raw, "success", True))
        html = getattr(raw, "html", None)
        markdown = getattr(raw, "markdown", None)
        status_code = self._extract_status_code(raw)

        if not success or not html:
            err = str(getattr(raw, "error", "") or "empty html")
            logger.info("Firecrawl %s senza contenuto per %s: %s", fetched_via, url, err)
            return FetchResult(
                html=None, markdown=markdown, status_code=status_code,
                fetched_via=fetched_via, error=err,
            )

        return FetchResult(
            html=html, markdown=markdown, status_code=status_code,
            fetched_via=fetched_via, error=None,
        )

    def _httpx_fetch(self, url: str, *, fetched_via: str) -> FetchResult:
        """Backup: scarica la pagina con httpx (no JS render, niente markdown)."""
        try:
            with httpx.Client(timeout=self._timeout_seconds, follow_redirects=True) as client:
                response = client.get(url)
        except httpx.TimeoutException as e:
            return FetchResult(
                html=None, markdown=None, status_code=None,
                fetched_via=fetched_via, error=f"httpx timeout: {e}",
            )
        except httpx.HTTPError as e:
            return FetchResult(
                html=None, markdown=None, status_code=None,
                fetched_via=fetched_via, error=f"httpx error: {e}",
            )

        status_code = int(response.status_code)
        if status_code >= 400:
            return FetchResult(
                html=None, markdown=None, status_code=status_code,
                fetched_via=fetched_via, error=f"HTTP {status_code}",
            )

        encoding = getattr(response, "charset_encoding", None) or "utf-8"
        try:
            html = response.content.decode(encoding, errors="replace")
        except (LookupError, UnicodeDecodeError):
            html = response.content.decode("utf-8", errors="replace")

        return FetchResult(
            html=html, markdown=None, status_code=status_code,
            fetched_via=fetched_via, error=None,
        )

    @staticmethod
    def _extract_status_code(raw: Any) -> int | None:
        # L'SDK Firecrawl espone lo status code in posizioni leggermente diverse
        # tra versioni: tentiamo metadata.statusCode, status_code, metadata['statusCode'].
        meta = getattr(raw, "metadata", None)
        if meta is not None:
            sc = getattr(meta, "statusCode", None) or getattr(meta, "status_code", None)
            if isinstance(sc, int):
                return sc
            if isinstance(meta, dict):
                sc = meta.get("statusCode") or meta.get("status_code")
                if isinstance(sc, int):
                    return sc
        sc = getattr(raw, "status_code", None)
        return sc if isinstance(sc, int) else None


# ---------------------------------------------------------------------------
# Singleton lazy
# ---------------------------------------------------------------------------

_CLIENT: FirecrawlClient | None = None


def get_firecrawl_client() -> FirecrawlClient:
    """Istanza condivisa del client. Legge FIRECRAWL_API_KEY da settings/env."""
    global _CLIENT
    if _CLIENT is None:
        # Lettura via settings.py se disponibile, altrimenti fallback su env.
        api_key: str | None = None
        try:
            from app.config.settings import settings  # type: ignore

            api_key = getattr(settings, "firecrawl_api_key", None)
            timeout = int(getattr(settings, "scraper_timeout_seconds", 30) or 30)
        except Exception:
            timeout = int(os.getenv("BANDI_SCRAPER_TIMEOUT", "30") or 30)
        if not api_key:
            api_key = os.getenv("FIRECRAWL_API_KEY") or None
        _CLIENT = FirecrawlClient(api_key=api_key, timeout_seconds=timeout)
    return _CLIENT
