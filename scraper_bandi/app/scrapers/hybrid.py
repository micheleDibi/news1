"""Strategy `hybrid_httpx_firecrawl`: discovery HTML + parse file allegato.

Usato per ~16 fonti dove la pagina indice e' HTML/JS ma i bandi reali
sono in file PDF/CSV scaricabili (es. Basilicata calendario preavvisi
che linka un PDF via download.php?id=N).

Flusso:
  1. Scarica la pagina HTML con httpx (o Firecrawl se JS).
  2. Trova i link a file (PDF, CSV, XLSX) via `discovery_selector`.
  3. Per ogni file scoperto: dispatch a CsvParserScraper o PdfTableScraper.
  4. Aggrega gli items.

Parametri (registry):
  - discovery_selector: CSS selector per i link ai file
                        (default: 'a[href$=".pdf"], a[href$=".csv"], a[href$=".xlsx"]').
  - file_strategy_default: strategia base per i file scoperti
                           (default: "pdf_extract_tables_pdfplumber").
                           Override automatico per estensione.
  - use_firecrawl: True se la pagina richiede rendering JS.
  - max_files: cap per evitare di scaricare decine di calendari datati
               (default 3 — tipicamente il piu' recente).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ..http import fetch_html
from ..logger import logger
from .base import BandoItem, BandoScraper


def _is_pdf(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return path.endswith(".pdf") or "/pdf" in path.lower()


def _is_csv_or_xlsx(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return path.endswith((".csv", ".xlsx", ".xls"))


class HybridScraper(BandoScraper):
    name = "hybrid_httpx_firecrawl"

    def __init__(
        self,
        discovery_selector: str = "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        url_pattern: str | None = None,
        file_strategy_default: str = "pdf_extract_tables_pdfplumber",
        use_firecrawl: bool = False,
        max_files: int = 3,
        firecrawl_options: dict | None = None,
        **_extra: Any,
    ) -> None:
        self.discovery_selector = discovery_selector
        self.url_pattern = re.compile(url_pattern) if url_pattern else None
        self.file_strategy_default = file_strategy_default
        self.use_firecrawl = use_firecrawl
        self.max_files = max_files
        self.firecrawl_options = firecrawl_options or {}

    async def _fetch_index_html(self, url: str) -> str:
        if self.use_firecrawl:
            import asyncio
            from .firecrawl import _scrape_url_sync
            return await asyncio.to_thread(_scrape_url_sync, url, **self.firecrawl_options)
        return await fetch_html(url)

    def _pick_file_strategy(self, file_url: str) -> str:
        if _is_csv_or_xlsx(file_url):
            return "csv_parser"
        if _is_pdf(file_url):
            return "pdf_extract_tables_pdfplumber"
        return self.file_strategy_default

    async def scrape(self, fonte: dict[str, Any]) -> list[BandoItem]:
        from . import get_scraper

        index_url = fonte["link"]
        logger.info("[hybrid] fonte_id={} discovery url={}", fonte.get("id"), index_url)

        try:
            html = await self._fetch_index_html(index_url)
        except Exception as e:
            logger.exception("[hybrid] fonte_id={} discovery GET fallita: {}", fonte.get("id"), e)
            return []

        soup = BeautifulSoup(html, "lxml")
        file_links: list[str] = []
        seen: set[str] = set()
        for a in soup.select(self.discovery_selector):
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("javascript:", "mailto:", "#")):
                continue
            abs_url = urljoin(index_url, href)
            if self.url_pattern and not self.url_pattern.match(abs_url):
                continue
            if abs_url in seen:
                continue
            seen.add(abs_url)
            file_links.append(abs_url)

        # Limita al numero piu' recente (tipicamente i primi nella lista)
        file_links = file_links[: self.max_files]
        logger.info("[hybrid] fonte_id={} files scoperti: {}", fonte.get("id"), len(file_links))

        all_items: list[BandoItem] = []
        for file_url in file_links:
            strategy = self._pick_file_strategy(file_url)
            try:
                sub_scraper = get_scraper(strategy, file_url_override=file_url)
                items = await sub_scraper.scrape(fonte)
                logger.info(
                    "[hybrid] fonte_id={} file={} strategy={} -> {} bandi",
                    fonte.get("id"), file_url, strategy, len(items),
                )
                all_items.extend(items)
            except Exception as e:
                logger.exception(
                    "[hybrid] fonte_id={} sub-scraper fallito file={}: {}",
                    fonte.get("id"), file_url, e,
                )

        logger.info("[hybrid] fonte_id={} totale items: {}", fonte.get("id"), len(all_items))
        return all_items
