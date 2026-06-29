"""Scrapers sub-package.

Dispatcher per istanziare la strategia di scraping corretta da nome.

Strategie disponibili:
  - httpx_bs4                  -> HttpxBs4Scraper
  - firecrawl_scrape           -> FirecrawlScraper (scrape standard)
  - firecrawl_extract          -> FirecrawlExtractScraper (AI extraction)
  - hybrid_httpx_firecrawl     -> HybridScraper (HTML discovery + file parse)
  - csv_parser                 -> CsvParserScraper
  - pdf_extract_tables_pdfplumber -> PdfTableScraper
  - pdf_extract_text           -> PdfTextScraper
  - skip_no_bandi              -> SkipScraper
  - json_api_paginated         -> JsonApiPaginatedScraper (v10: REST/Solr)
  - json_api_paginated_login   -> JsonApiPaginatedLoginScraper (v10: + auth)
  - html_paginated_offset      -> HtmlPaginatedOffsetScraper (v10: HTML offset)
"""
from __future__ import annotations

from typing import Any

from .base import BandoItem, BandoScraper


def get_scraper(strategy: str, **kwargs: Any) -> BandoScraper:
    """Factory: ritorna l'istanza dello scraper per la strategia richiesta."""
    # Import lazy per non pagare deps non installate (es. pandas) se non servono.
    if strategy == "skip_no_bandi":
        from .skip import SkipScraper
        return SkipScraper(reason=kwargs.get("reason"))
    if strategy == "httpx_bs4":
        from .httpx_bs4 import HttpxBs4Scraper
        return HttpxBs4Scraper(**kwargs)
    if strategy == "firecrawl_scrape":
        from .firecrawl import FirecrawlScraper
        return FirecrawlScraper(**kwargs)
    if strategy == "firecrawl_extract":
        from .firecrawl import FirecrawlExtractScraper
        return FirecrawlExtractScraper(**kwargs)
    if strategy == "hybrid_httpx_firecrawl":
        from .hybrid import HybridScraper
        return HybridScraper(**kwargs)
    if strategy == "csv_parser":
        from .csv_parser import CsvParserScraper
        return CsvParserScraper(**kwargs)
    if strategy == "pdf_extract_tables_pdfplumber":
        from .pdf_extract import PdfTableScraper
        return PdfTableScraper(**kwargs)
    if strategy == "pdf_extract_text":
        from .pdf_extract import PdfTextScraper
        return PdfTextScraper(**kwargs)
    if strategy == "json_api_paginated":
        from .api_paginated import JsonApiPaginatedScraper
        return JsonApiPaginatedScraper(**kwargs)
    if strategy == "json_api_paginated_login":
        from .api_paginated_login import JsonApiPaginatedLoginScraper
        return JsonApiPaginatedLoginScraper(**kwargs)
    if strategy == "html_paginated_offset":
        from .html_paginated_offset import HtmlPaginatedOffsetScraper
        return HtmlPaginatedOffsetScraper(**kwargs)
    raise ValueError(f"Strategy sconosciuta: {strategy!r}")


__all__ = ["BandoItem", "BandoScraper", "get_scraper"]
