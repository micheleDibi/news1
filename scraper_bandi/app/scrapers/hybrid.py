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
               (default 3). Prima del taglio i file scoperti vengono
               ordinati con `ordina_file_scoperti`: data nel nome del file
               (il piu' recente prima), a parita' data di modifica dichiarata
               nel markup dell'anchor, a parita' ordine DOM (deterministico).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

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


# --- Ordinamento dei file scoperti -------------------------------------------

_MESI_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
}
_ANNO = r"(20\d\d)"
_MESE = r"(0[1-9]|1[0-2])"
_GIORNO = r"(0[1-9]|[12]\d|3[01])"
_SEP = r"[-_./ ]?"
# YYYY-MM-DD, YYYY_MM_DD, YYYYMMDD, /2026/03/ (upload WordPress)
_RE_AAAA_MM_GG = re.compile(rf"(?<!\d){_ANNO}{_SEP}{_MESE}(?:{_SEP}{_GIORNO})?(?!\d)")
# DD-MM-YYYY, DD_MM_YYYY, DD.MM.YYYY, DDMMYYYY
_RE_GG_MM_AAAA = re.compile(rf"(?<!\d){_GIORNO}{_SEP}{_MESE}{_SEP}{_ANNO}(?!\d)")
# marzo-2026, settembre_2025
_RE_MESE_IT = re.compile(
    r"(" + "|".join(_MESI_IT) + r")" + _SEP + _ANNO, re.IGNORECASE,
)
# anno isolato (calendario-2026.pdf, programmazione 2021-2027 → 2027)
_RE_ANNO = re.compile(rf"(?<!\d){_ANNO}(?!\d)")


def _data_sicura(anno: int, mese: int, giorno: int) -> date | None:
    try:
        return date(anno, mese, giorno)
    except ValueError:
        return None


def _data_da_nome_file(url: str) -> date | None:
    """Data piu' recente riconoscibile nel percorso del file (query esclusa).

    Riconosce YYYY-MM-DD / YYYYMMDD / /YYYY/MM/, DD-MM-YYYY / DDMMYYYY,
    «marzo-2026» e l'anno isolato (→ 1° gennaio). Piu' candidati → il massimo.
    None se il nome non contiene alcuna data.
    """
    percorso = unquote(urlsplit(url).path)
    candidati: list[date] = []
    for m in _RE_AAAA_MM_GG.finditer(percorso):
        d = _data_sicura(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
        if d:
            candidati.append(d)
    for m in _RE_GG_MM_AAAA.finditer(percorso):
        d = _data_sicura(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if d:
            candidati.append(d)
    for m in _RE_MESE_IT.finditer(percorso):
        d = _data_sicura(int(m.group(2)), _MESI_IT[m.group(1).lower()], 1)
        if d:
            candidati.append(d)
    for m in _RE_ANNO.finditer(percorso):
        d = _data_sicura(int(m.group(1)), 1, 1)
        if d:
            candidati.append(d)
    return max(candidati) if candidati else None


def _normalizza_datetime(dt: datetime) -> datetime:
    """Datetime naive in UTC, cosi' i confronti non mescolano aware e naive."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _parse_data_modifica(testo: str | None) -> datetime | None:
    """Interpreta una data di modifica: ISO 8601 o formato HTTP (RFC 1123)."""
    if not testo:
        return None
    testo = testo.strip()
    if not testo:
        return None
    try:
        return _normalizza_datetime(datetime.fromisoformat(testo))
    except ValueError:
        pass
    try:
        return _normalizza_datetime(parsedate_to_datetime(testo))
    except (TypeError, ValueError, IndexError):
        return None


# Attributi in cui il markup puo' dichiarare la data di modifica del file.
_ATTRIBUTI_MODIFICA = ("data-last-modified", "data-modified", "data-date", "datetime")


def _data_modifica_da_tag(a) -> datetime | None:
    """Last-Modified «nell'oggetto»: attributi dell'anchor o di un <time>
    al suo interno. Nessuna richiesta HTTP: la discovery non scarica i file."""
    for attr in _ATTRIBUTI_MODIFICA:
        dt = _parse_data_modifica(a.get(attr))
        if dt:
            return dt
    time_tag = a.find("time") if hasattr(a, "find") else None
    if time_tag is not None:
        return _parse_data_modifica(time_tag.get("datetime") or time_tag.get_text(strip=True))
    return None


def ordina_file_scoperti(
    file_links: list[str],
    modifiche: dict[str, datetime | None] | None = None,
) -> list[str]:
    """Ordina i file scoperti: data nel nome (piu' recente prima), a parita'
    data di modifica dichiarata (piu' recente prima), a parita' ordine DOM.

    I file senza alcuna data nel nome vanno dopo quelli datati; tra loro
    l'ordine DOM e' conservato (sort stabile). Non fa rete.
    """
    modifiche = modifiche or {}

    def chiave(url: str) -> tuple[date, datetime]:
        return (
            _data_da_nome_file(url) or date.min,
            modifiche.get(url) or datetime.min,
        )

    return sorted(file_links, key=chiave, reverse=True)


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
        modifiche: dict[str, datetime | None] = {}
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
            modifiche[abs_url] = _data_modifica_da_tag(a)

        # Limita ai piu' recenti: data nel nome del file, poi data di modifica
        # dichiarata nel markup, poi ordine DOM (mai dipendente dal caso).
        file_links = ordina_file_scoperti(file_links, modifiche)[: self.max_files]
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
