"""Strategy `firecrawl_scrape` e `firecrawl_extract`.

Usato per ~18 fonti con JS dinamico, anti-bot (Cloudflare, Radware),
o motori di ricerca client-side (Elastic/Swiftype).

`firecrawl_scrape`: scarica HTML renderizzato + filtra link via selector/regex
                    come HttpxBs4Scraper.
`firecrawl_extract`: estrazione strutturata via AI prompt (1 fonte:
                     interreg.net Italia-Austria).

Parametri (registry):
  - link_selector, url_pattern, link_text_filter come httpx_bs4.
  - firecrawl_options: dict opzionale passato a scrape_url
    (es. {"waitFor": 3000, "onlyMainContent": True}).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..logger import logger
from ..settings import get_settings
from .base import BandoItem, BandoScraper


def _get_firecrawl_client():
    """Lazy import + singleton del client Firecrawl."""
    from firecrawl import FirecrawlApp  # type: ignore
    settings = get_settings()
    if not settings.firecrawl_api_key:
        raise RuntimeError(
            "FIRECRAWL_API_KEY mancante in .env. La strategia firecrawl non puo' "
            "funzionare senza la chiave Firecrawl."
        )
    return FirecrawlApp(api_key=settings.firecrawl_api_key)


def _scrape_url_sync(url: str, **options: Any) -> str:
    """Wrapper sync su Firecrawl scrape_url. Ritorna HTML renderizzato."""
    app = _get_firecrawl_client()
    # Firecrawl SDK e' sync; lo chiamiamo dentro un thread executor per non
    # bloccare l'event loop (vedi scrape()).
    result = app.scrape_url(url, formats=["html"], **options)
    # Il formato del result puo' variare tra versioni della SDK:
    #   { "success": True, "data": { "html": "..." } }
    # oppure direttamente { "html": "..." }
    if isinstance(result, dict):
        data = result.get("data", result)
        html = data.get("html") or data.get("rawHtml")
        if html:
            return html
    # Object pydantic (versioni >=2)
    if hasattr(result, "html") and result.html:
        return result.html
    if hasattr(result, "data") and getattr(result.data, "html", None):
        return result.data.html
    raise RuntimeError(f"Firecrawl response inattesa per {url}: {type(result)}")


class FirecrawlScraper(BandoScraper):
    name = "firecrawl_scrape"

    def __init__(
        self,
        link_selector: str = "a[href]",
        url_pattern: str | None = None,
        link_text_filter: str | None = None,
        firecrawl_options: dict | None = None,
        **_extra: Any,
    ) -> None:
        self.link_selector = link_selector
        self.url_pattern = re.compile(url_pattern) if url_pattern else None
        self.link_text_filter = link_text_filter
        self.firecrawl_options = firecrawl_options or {}

    async def scrape(self, fonte: dict[str, Any]) -> list[BandoItem]:
        import asyncio

        url = fonte["link"]
        logger.info("[firecrawl] fonte_id={} url={} scrape...", fonte.get("id"), url)

        try:
            html = await asyncio.to_thread(_scrape_url_sync, url, **self.firecrawl_options)
        except Exception as e:
            logger.exception("[firecrawl] fonte_id={} scrape fallito: {}", fonte.get("id"), e)
            return []

        soup = BeautifulSoup(html, "lxml")
        anchors = soup.select(self.link_selector)
        seen: set[str] = set()
        items: list[BandoItem] = []

        for a in anchors:
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("javascript:", "mailto:", "#")):
                continue
            abs_url = urljoin(url, href)
            if self.url_pattern and not self.url_pattern.match(abs_url):
                continue
            if self.link_text_filter and self.link_text_filter.lower() not in a.get_text(" ", strip=True).lower():
                continue
            if abs_url in seen:
                continue
            seen.add(abs_url)

            items.append(BandoItem(
                fonte_id=fonte["id"],
                tipo_link=fonte["tipo_link"],
                link_bando=abs_url,
                titolo_raw=(a.get_text(" ", strip=True) or None),
                descrizione_raw=None,
                raw_data=None,
            ))

        logger.info("[firecrawl] fonte_id={} estratti {} bandi", fonte.get("id"), len(items))
        return items


class FirecrawlExtractScraper(BandoScraper):
    """Strategia di estrazione strutturata via AI prompt (1 fonte:
    interreg.net Italia-Austria). Usa Firecrawl extract con schema JSON."""
    name = "firecrawl_extract"

    DEFAULT_PROMPT = (
        "Estrai TUTTI i bandi/avvisi presenti nella pagina. Per ognuno: "
        "titolo (string), link (URL assoluto se presente, altrimenti null), "
        "scadenza (string o null), fondo (string o null)."
    )

    DEFAULT_SCHEMA = {
        "type": "object",
        "properties": {
            "bandi": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "titolo": {"type": "string"},
                        "link": {"type": ["string", "null"]},
                        "scadenza": {"type": ["string", "null"]},
                        "fondo": {"type": ["string", "null"]},
                    },
                    "required": ["titolo"],
                },
            },
        },
        "required": ["bandi"],
    }

    def __init__(
        self,
        prompt: str | None = None,
        schema: dict | None = None,
        **_extra: Any,
    ) -> None:
        self.prompt = prompt or self.DEFAULT_PROMPT
        self.schema = schema or self.DEFAULT_SCHEMA

    async def scrape(self, fonte: dict[str, Any]) -> list[BandoItem]:
        import asyncio

        url = fonte["link"]
        logger.info("[firecrawl_extract] fonte_id={} url={} extract...", fonte.get("id"), url)

        def _extract() -> Any:
            app = _get_firecrawl_client()
            return app.scrape_url(
                url,
                formats=["json"],
                json_options={
                    "prompt": self.prompt,
                    "schema": self.schema,
                },
            )

        try:
            result = await asyncio.to_thread(_extract)
        except Exception as e:
            logger.exception("[firecrawl_extract] fonte_id={} fallito: {}", fonte.get("id"), e)
            return []

        # Estrai il json dal result
        bandi_data: list[dict] = []
        if isinstance(result, dict):
            data = result.get("data", result)
            json_obj = data.get("json") or data.get("extract") or {}
            bandi_data = json_obj.get("bandi", []) or []
        elif hasattr(result, "json") and isinstance(result.json, dict):
            bandi_data = result.json.get("bandi", []) or []
        elif hasattr(result, "data") and hasattr(result.data, "json"):
            bandi_data = result.data.json.get("bandi", []) or []

        items: list[BandoItem] = []
        for b in bandi_data:
            titolo = (b.get("titolo") or "").strip() or None
            link = (b.get("link") or "").strip() or None
            if link and not link.startswith(("http://", "https://")):
                link = urljoin(url, link)

            items.append(BandoItem(
                fonte_id=fonte["id"],
                tipo_link=fonte["tipo_link"],
                link_bando=link,
                titolo_raw=titolo,
                descrizione_raw=None,
                raw_data={k: v for k, v in b.items() if k not in ("titolo", "link")} or None,
            ))

        logger.info("[firecrawl_extract] fonte_id={} estratti {} bandi", fonte.get("id"), len(items))
        return items
