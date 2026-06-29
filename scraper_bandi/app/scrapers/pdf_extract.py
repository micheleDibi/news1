"""Strategy `pdf_extract_tables_pdfplumber` e `pdf_extract_text`.

Usato per ~6 fonti che pubblicano calendari preavvisi come PDF.

`pdf_extract_tables_pdfplumber`: estrae tabelle pagina per pagina via
   pdfplumber. Ogni riga di tabella diventa un BandoItem SENZA link.
   Se la prima pagina non ha tabelle (PDF immagine), log WARNING e skip
   (OCR Tesseract sara' uno step futuro).

`pdf_extract_text`: estrae il testo grezzo e cerca pattern bando.
   Strategia di backup per PDF non tabellari (es. Italia-Slovenia).
   Per ora: un solo BandoItem con tutto il testo come raw_data.

Parametri (registry):
  - file_url_override: opzionale, scarica QUESTO URL invece di fonte.link.
  - titolo_column_index: indice colonna da usare come titolo (default sniff).
  - header_row: True se la prima riga e' header (default True).
  - skip_first_pages: numero pagine iniziali da saltare (default 0).
"""
from __future__ import annotations

import io
from typing import Any

from ..http import fetch_bytes
from ..logger import logger
from .base import BandoItem, BandoScraper


def _open_pdf(content: bytes):
    """Lazy import pdfplumber."""
    import pdfplumber  # type: ignore
    return pdfplumber.open(io.BytesIO(content))


def _looks_like_pdf(content: bytes) -> bool:
    """True se il contenuto inizia con il magic byte PDF (%PDF-)."""
    return content[:5] == b"%PDF-"


def _looks_like_html(content: bytes) -> bool:
    """True se il contenuto e' HTML invece di PDF (URL mal-mappato)."""
    head = content[:256].lstrip().lower()
    return (
        head.startswith(b"<!doctype html")
        or head.startswith(b"<html")
        or b"<head" in head[:200]
    )


def _looks_like_zip_or_xlsx(content: bytes) -> bool:
    """True se inizia con magic byte ZIP (PK\\x03\\x04). Tipico di XLSX,
    DOCX, ODS, o ZIP veri e propri."""
    return content[:4] == b"PK\x03\x04"


def _pick_titolo_index_from_header(header_row: list[str]) -> int | None:
    """Trova l'indice della colonna 'titolo'/'oggetto' nell'header."""
    if not header_row:
        return None
    candidates = ("titolo", "oggetto", "azione", "intervento", "denominazione", "avviso", "bando")
    for i, h in enumerate(header_row):
        if not h:
            continue
        h_lower = str(h).lower().strip()
        for cand in candidates:
            if cand in h_lower:
                return i
    # Fallback: prima colonna non numerica/non data
    for i, h in enumerate(header_row):
        if h and len(str(h).strip()) > 3:
            return i
    return None


class PdfTableScraper(BandoScraper):
    name = "pdf_extract_tables_pdfplumber"

    def __init__(
        self,
        file_url_override: str | None = None,
        titolo_column_index: int | None = None,
        header_row: bool = True,
        skip_first_pages: int = 0,
        **_extra: Any,
    ) -> None:
        self.file_url_override = file_url_override
        self.titolo_column_index = titolo_column_index
        self.header_row = header_row
        self.skip_first_pages = skip_first_pages

    async def scrape(self, fonte: dict[str, Any]) -> list[BandoItem]:
        url = self.file_url_override or fonte["link"]
        logger.info("[pdf_tab] fonte_id={} download url={}", fonte.get("id"), url)

        try:
            content = await fetch_bytes(url, timeout_s=120.0)
        except Exception as e:
            logger.exception("[pdf_tab] fonte_id={} download fallito: {}", fonte.get("id"), e)
            return []

        if _looks_like_html(content):
            logger.error(
                "[pdf_tab] fonte_id={} URL e' una pagina HTML, non un PDF. "
                "Registry mal-mappato: cambia strategy a hybrid_httpx_firecrawl. url={}",
                fonte.get("id"), url,
            )
            return []
        if _looks_like_zip_or_xlsx(content):
            # WPDM/endpoint download che consegna XLSX invece di PDF.
            # Delego al CsvParserScraper che gestisce XLSX via magic byte.
            logger.warning(
                "[pdf_tab] fonte_id={} content e' XLSX/ZIP (magic byte PK), non PDF. "
                "Delego a csv_parser. url={}",
                fonte.get("id"), url,
            )
            from .csv_parser import CsvParserScraper
            sub = CsvParserScraper(file_url_override=url)
            return await sub.scrape(fonte)
        if not _looks_like_pdf(content):
            logger.warning(
                "[pdf_tab] fonte_id={} content non sembra un PDF (magic byte non %PDF-). url={}",
                fonte.get("id"), url,
            )

        items: list[BandoItem] = []
        try:
            with _open_pdf(content) as pdf:
                logger.info("[pdf_tab] fonte_id={} aperto: {} pagine", fonte.get("id"), len(pdf.pages))
                for page_idx, page in enumerate(pdf.pages):
                    if page_idx < self.skip_first_pages:
                        continue
                    tables = page.extract_tables() or []
                    if not tables:
                        logger.debug("[pdf_tab] fonte_id={} page={} nessuna tabella", fonte.get("id"), page_idx + 1)
                        continue

                    for tbl_idx, tbl in enumerate(tables):
                        rows = [r for r in tbl if r and any((c or "").strip() for c in r)]
                        if not rows:
                            continue

                        # Identifica header se richiesto
                        data_rows = rows
                        titolo_idx = self.titolo_column_index
                        header: list[str] = []
                        if self.header_row:
                            header = [str(c or "").strip() for c in rows[0]]
                            data_rows = rows[1:]
                            if titolo_idx is None:
                                titolo_idx = _pick_titolo_index_from_header(header)

                        if titolo_idx is None:
                            titolo_idx = 0

                        for row_idx, row in enumerate(data_rows):
                            if titolo_idx >= len(row):
                                continue
                            titolo = str(row[titolo_idx] or "").strip()
                            if not titolo or len(titolo) < 3:
                                continue

                            raw: dict[str, Any] = {
                                "page": page_idx + 1,
                                "table_index": tbl_idx,
                                "row_index": row_idx,
                                "source_url": url,
                            }
                            for ci, val in enumerate(row):
                                if ci == titolo_idx or val is None:
                                    continue
                                val_s = str(val).strip()
                                if not val_s:
                                    continue
                                key = header[ci] if ci < len(header) and header[ci] else f"col_{ci}"
                                # Sanitizza key per JSONB
                                key = key.lower().replace(" ", "_").replace(".", "_")[:60]
                                raw[key] = val_s

                            items.append(BandoItem(
                                fonte_id=fonte["id"],
                                tipo_link=fonte["tipo_link"],
                                link_bando=None,
                                titolo_raw=titolo,
                                descrizione_raw=None,
                                raw_data=raw,
                            ))

        except Exception as e:
            logger.exception("[pdf_tab] fonte_id={} parse PDF fallito: {}", fonte.get("id"), e)
            return items

        if not items:
            logger.warning(
                "[pdf_tab] fonte_id={} nessuna tabella estraibile (possibile PDF immagine? OCR future step)",
                fonte.get("id"),
            )
        else:
            logger.info("[pdf_tab] fonte_id={} estratti {} bandi (righe tabella)", fonte.get("id"), len(items))
        return items


class PdfTextScraper(BandoScraper):
    """Estrazione testo grezzo PDF. Usato come fallback su PDF non tabellari.

    Strategia base: produce 1 BandoItem con titolo = filename + raw_data
    con il testo completo (primi 8KB). L'enrichment skill puo' poi estrarre
    i dettagli dal testo.
    """
    name = "pdf_extract_text"

    def __init__(
        self,
        file_url_override: str | None = None,
        max_text_chars: int = 8000,
        **_extra: Any,
    ) -> None:
        self.file_url_override = file_url_override
        self.max_text_chars = max_text_chars

    async def scrape(self, fonte: dict[str, Any]) -> list[BandoItem]:
        from urllib.parse import urlsplit, unquote

        url = self.file_url_override or fonte["link"]
        logger.info("[pdf_txt] fonte_id={} download url={}", fonte.get("id"), url)

        try:
            content = await fetch_bytes(url, timeout_s=120.0)
        except Exception as e:
            logger.exception("[pdf_txt] fonte_id={} download fallito: {}", fonte.get("id"), e)
            return []

        if _looks_like_html(content):
            logger.error(
                "[pdf_txt] fonte_id={} URL e' una pagina HTML, non un PDF. "
                "Registry mal-mappato: cambia strategy a hybrid_httpx_firecrawl. url={}",
                fonte.get("id"), url,
            )
            return []
        if _looks_like_zip_or_xlsx(content):
            logger.warning(
                "[pdf_txt] fonte_id={} content e' XLSX/ZIP, non PDF. Delego a csv_parser. url={}",
                fonte.get("id"), url,
            )
            from .csv_parser import CsvParserScraper
            sub = CsvParserScraper(file_url_override=url)
            return await sub.scrape(fonte)

        text_pages: list[str] = []
        try:
            with _open_pdf(content) as pdf:
                for page in pdf.pages:
                    t = page.extract_text() or ""
                    if t.strip():
                        text_pages.append(t)
        except Exception as e:
            logger.exception("[pdf_txt] fonte_id={} parse PDF fallito: {}", fonte.get("id"), e)
            return []

        if not text_pages:
            logger.warning("[pdf_txt] fonte_id={} nessun testo estraibile (PDF immagine?)", fonte.get("id"))
            return []

        full_text = "\n\n".join(text_pages)[: self.max_text_chars]

        # Titolo: nome file pulito
        path = unquote(urlsplit(url).path)
        filename = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        titolo = filename.replace("_", " ").replace("-", " ").strip() or "Bando PDF"

        item = BandoItem(
            fonte_id=fonte["id"],
            tipo_link=fonte["tipo_link"],
            link_bando=None,
            titolo_raw=titolo,
            descrizione_raw=full_text[:500],
            raw_data={
                "source_url": url,
                "n_pages": len(text_pages),
                "text_excerpt": full_text,
            },
        )
        logger.info("[pdf_txt] fonte_id={} estratto 1 bando (text={} chars)", fonte.get("id"), len(full_text))
        return [item]
