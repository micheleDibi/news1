"""Strategy `httpx_bs4`: scraping classico SSR.

Adatto a indici di bandi statici renderizzati server-side (no JS dinamico,
no captcha). Usato per ~38 fonti.

Parametri (dal registry):
  - link_selector: CSS selector per i link da considerare (es. "a[href^='/avvisi/']").
  - url_pattern: regex per filtrare gli URL finali (es. r"^https://.../\\d+$").
  - pagination: dict per la paginazione:
      {"type": "url_param", "param": "page", "range": [0, 5]}
      {"type": "none"}
  - link_text_filter: opzionale, sub-stringa che deve essere nel testo del link.
  - max_pages: cap di sicurezza (default 20).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlsplit, parse_qs, urlencode, urlunsplit

import httpx
from bs4 import BeautifulSoup

from ..http import fetch_html
from ..logger import logger
from .base import BandoItem, BandoScraper


class HttpxBs4Scraper(BandoScraper):
    name = "httpx_bs4"

    def __init__(
        self,
        link_selector: str = "a[href]",
        url_pattern: str | None = None,
        pagination: dict | None = None,
        link_text_filter: str | None = None,
        max_pages: int = 20,
        **_extra: Any,  # tollera campi extra dal registry
    ) -> None:
        self.link_selector = link_selector
        self.url_pattern = re.compile(url_pattern) if url_pattern else None
        self.pagination = pagination or {"type": "none"}
        self.link_text_filter = link_text_filter
        self.max_pages = max_pages

    def _pagination_urls(self, base_url: str) -> list[str]:
        """Genera la lista di URL da scrappare in base alla config paginazione."""
        ptype = self.pagination.get("type", "none")
        if ptype == "none":
            return [base_url]
        if ptype == "url_param":
            param = self.pagination.get("param", "page")
            rng = self.pagination.get("range", [0, 5])
            start, end = int(rng[0]), int(rng[1])
            count = min(end - start + 1, self.max_pages)
            return [self._with_query_param(base_url, param, str(i))
                    for i in range(start, start + count)]
        logger.warning("[httpx_bs4] pagination type sconosciuto: {} (uso solo base URL)", ptype)
        return [base_url]

    @staticmethod
    def _with_query_param(url: str, param: str, value: str) -> str:
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        query[param] = [value]
        new_query = urlencode({k: v[0] if isinstance(v, list) else v
                                for k, v in query.items()})
        return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))

    async def scrape(self, fonte: dict[str, Any]) -> list[BandoItem]:
        base_url = fonte["link"]
        pages = self._pagination_urls(base_url)
        logger.info(
            "[httpx_bs4] fonte_id={} url={} pages={}",
            fonte.get("id"), base_url, len(pages),
        )

        items: list[BandoItem] = []
        seen_links: set[str] = set()

        for page_url in pages:
            try:
                html = await fetch_html(page_url)
            except httpx.HTTPError as e:
                logger.warning(
                    "[httpx_bs4] fonte_id={} page={} GET fallita: {}",
                    fonte.get("id"), page_url, e,
                )
                # Sulla prima pagina interrompo, sulle successive vado avanti
                if page_url == base_url:
                    break
                continue

            soup = BeautifulSoup(html, "lxml")
            anchors = soup.select(self.link_selector)
            page_count = 0
            for a in anchors:
                href = (a.get("href") or "").strip()
                if not href or href.startswith(("javascript:", "mailto:", "#")):
                    continue
                abs_url = urljoin(page_url, href)

                if self.url_pattern and not self.url_pattern.match(abs_url):
                    continue

                if self.link_text_filter and self.link_text_filter.lower() not in a.get_text(" ", strip=True).lower():
                    continue

                if abs_url in seen_links:
                    continue
                seen_links.add(abs_url)

                items.append(BandoItem(
                    fonte_id=fonte["id"],
                    tipo_link=fonte["tipo_link"],
                    link_bando=abs_url,
                    titolo_raw=(a.get_text(" ", strip=True) or None),
                    descrizione_raw=None,
                    raw_data=None,
                ))
                page_count += 1

            logger.debug(
                "[httpx_bs4] fonte_id={} page={} -> {} link candidati",
                fonte.get("id"), page_url, page_count,
            )

        logger.info(
            "[httpx_bs4] fonte_id={} estratti {} bandi distinti",
            fonte.get("id"), len(items),
        )
        return items
