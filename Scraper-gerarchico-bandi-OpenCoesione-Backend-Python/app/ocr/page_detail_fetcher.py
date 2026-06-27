"""Fetch e parsing dettaglio pagina bando per enrichment descrizione/date/importo.

Firecrawl e' il fetcher primario dopo la batch 2 (vedi `app/scrapers/firecrawl_client.py`).
Gli output rimangono identici al pre-batch2 (page_title, page_dates, page_importo,
page_pdf_links) per non rompere `bando_parser.py`. In piu' aggiungiamo:
  - `page_markdown_snippet`: i primi 8000 char di markdown pulito di Firecrawl,
    utile alla skill di fase 2 come input meno rumoroso del raw HTML.
  - `fetched_via`: tracciamento della strategia (firecrawl_stealth/auto/httpx_fallback).
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.scrapers.firecrawl_client import get_firecrawl_client

logger = logging.getLogger(__name__)

_MARKDOWN_SNIPPET_MAX = 8000


def fetch_bando_detail_page(url: str) -> dict[str, Any]:
    """
    Fetch pagina dettaglio bando e estrae titolo reale, descrizione, date, importo.

    Restituisce dict con chiavi:
    - 'page_title': H1 o H2 trovato
    - 'page_description': primo paragrafo o meta description
    - 'page_importo': importo trovato nella pagina con token monetario
    - 'page_dates': lista di date trovate
    - 'page_content_snippet': primi 1000 char di testo
    - 'page_markdown_snippet': primi 8000 char di markdown Firecrawl (se disponibile)
    - 'page_pdf_links': link PDF allegati trovati
    - 'fetched_via': 'firecrawl_stealth' | 'firecrawl_auto' | 'httpx_fallback' | 'firecrawl_unavailable'
    - 'fetch_error': se presente, indica motivo fallimento (html assente)
    """

    result: dict[str, Any] = {}

    fetch = get_firecrawl_client().scrape(url)
    result["fetched_via"] = fetch.fetched_via
    if not fetch.html:
        err = fetch.error or "fetch fallita"
        result["fetch_error"] = err
        logger.warning("Fetch pagina %s fallito (%s): %s", url, fetch.fetched_via, err)
        return result

    try:
        soup = BeautifulSoup(fetch.html, "html.parser")
    except Exception as e:
        result["fetch_error"] = f"Parse HTML error: {e}"
        logger.warning("Parse HTML %s fallito: %s", url, e)
        return result

    if fetch.markdown:
        # Snippet markdown gia' "pulito" da Firecrawl, utile alla skill per regex
        # piu' robuste su date/importi senza il chrome della pagina.
        result["page_markdown_snippet"] = fetch.markdown[:_MARKDOWN_SNIPPET_MAX]
    
    # Estrai titolo reale
    page_title = _extract_page_title(soup)
    if page_title:
        result["page_title"] = page_title
    
    # Estrai descrizione
    page_desc = _extract_page_description(soup)
    if page_desc:
        result["page_description"] = page_desc
    
    # Estrai importo
    page_importo = _extract_page_importo(soup)
    if page_importo:
        result["page_importo"] = page_importo
    
    # Estrai date
    page_dates = _extract_page_dates(soup)
    if page_dates:
        result["page_dates"] = page_dates
    
    # Snippet del contenuto testuale
    text_content = _extract_text_content(soup)
    if text_content:
        result["page_content_snippet"] = text_content[:1000]

    # Link PDF allegati presenti nella pagina dettaglio.
    pdf_links = _extract_pdf_links(soup, url)
    if pdf_links:
        result["page_pdf_links"] = pdf_links
    
    return result


def _extract_page_title(soup: BeautifulSoup) -> str | None:
    """Estrae titolo reale da H1, H2 o meta."""
    
    # Preferenza: H1
    h1 = soup.find("h1")
    if h1:
        text = _clean_text(h1.get_text())
        if text and text.lower() != "vai al bando":
            return text[:500]
    
    # Fallback: H2
    h2 = soup.find("h2")
    if h2:
        text = _clean_text(h2.get_text())
        if text and text.lower() != "vai al bando":
            return text[:500]
    
    # Fallback: meta og:title
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return og_title["content"][:500]
    
    return None


def _extract_page_description(soup: BeautifulSoup) -> str | None:
    """Estrae descrizione da meta description o primo paragrafo."""
    
    # Meta description
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        desc = _clean_text(meta_desc["content"])
        if desc:
            return desc[:4000]
    
    # Primo paragrafo testuale dopo i titoli
    for p in soup.find_all("p"):
        text = _clean_text(p.get_text())
        if text and len(text) > 50:
            return text[:4000]
    
    # Primo div con testo
    for div in soup.find_all("div"):
        text = _clean_text(div.get_text())
        if text and len(text) > 100:
            return text[:4000]
    
    return None


def _extract_page_importo(soup: BeautifulSoup) -> str | None:
    """Estrae importo dalla pagina con pattern monetario."""
    
    text = _extract_text_content(soup)
    if not text:
        return None
    
    # Pattern: "23 million Euros" / "15 million EUR" (inglese)
    million_m = re.search(
        r"([0-9]+(?:[.,][0-9]+)?)\s+(?:millions?|mln)\s+(?:euros?|eur|\u20ac)",
        text,
        flags=re.IGNORECASE,
    )
    if million_m:
        raw_num = million_m.group(1).replace(",", ".")
        try:
            normalized = str(int(float(raw_num) * 1_000_000))
            if _is_valid_importo_amount(normalized):
                return normalized
        except (ValueError, OverflowError):
            pass

    billion_m = re.search(
        r"([0-9]+(?:[.,][0-9]+)?)\s+(?:billions?|bln)\s+(?:euros?|eur|\u20ac)",
        text,
        flags=re.IGNORECASE,
    )
    if billion_m:
        raw_num = billion_m.group(1).replace(",", ".")
        try:
            normalized = str(int(float(raw_num) * 1_000_000_000))
            if _is_valid_importo_amount(normalized):
                return normalized
        except (ValueError, OverflowError):
            pass

    # Pattern: € 1.234.567,89 oppure 1234567.89 euro oppure "importo ... 1000000"
    patterns = [
        r"(?:€|eur|euro)\s*([0-9][0-9\s\.,]{0,30})",
        r"([0-9][0-9\s\.,]{3,30})\s*(?:€|eur|euro)",
        r"(?:importo|dotazione|finanziamento)\s*[:\s]+\s*€?\s*([0-9][0-9\s\.,]{3,30})",
    ]
    
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            importo_raw = m.group(1).strip()
            # Validazione base: escludere numeri 4 cifre che potrebbero essere anni
            if _is_valid_importo_amount(importo_raw):
                return importo_raw
    
    return None


def _extract_page_dates(soup: BeautifulSoup) -> list[str]:
    """Estrae date dalla pagina."""
    
    text = _extract_text_content(soup)
    if not text:
        return []
    
    # Pattern date: 15/05/2026, 15-05-2026, 15 maggio 2026, 27 November 2025, 2026-05-15
    pattern = (
        r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
        r"|\d{4}[./-]\d{1,2}[./-]\d{1,2}"
        r"|\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|jun|jul|aug|sep|oct|dec|"
        r"gennaio|febbraio|marzo|aprile|maggio|giugno|"
        r"luglio|agosto|settembre|ottobre|novembre|dicembre|"
        r"gen|feb|mar|apr|mag|giu|lug|ago|set|ott|nov|dic)\.?\s+\d{4})"
    )
    
    matches = re.findall(pattern, text, flags=re.IGNORECASE)
    return list(set(matches))[:10]  # Unico, max 10


def _extract_text_content(soup: BeautifulSoup) -> str:
    """Estrae tutto il testo dalla pagina."""
    
    # Rimuovi script, style, etc
    for tag in soup(["script", "style", "meta", "link"]):
        tag.decompose()
    
    text = soup.get_text(separator=" ", strip=True)
    return _clean_text(text)


def _extract_pdf_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Estrae link PDF assoluti dalla pagina evitando duplicati."""
    links: list[str] = []
    seen: set[str] = set()
    base_host = (urlparse(base_url).netloc or "").lower()

    for anchor in soup.select("a[href]"):
        href = (anchor.get("href") or "").strip()
        if not href:
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        normalized = parsed._replace(fragment="").geturl()
        if ".pdf" not in (parsed.path or "").lower() and "pdf" not in (anchor.get_text(" ", strip=True) or "").lower():
            continue
        # Preferiamo PDF dello stesso dominio della pagina dettaglio.
        host = (parsed.netloc or "").lower()
        if base_host and host and host != base_host and not host.endswith("." + base_host):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        links.append(normalized)

    return links[:5]


def _clean_text(text: str) -> str:
    """Pulisci testo: rimuovi spazi multipli, newline, ecc."""
    
    s = str(text).strip()
    s = re.sub(r"\s+", " ", s)  # multiple spaces to single
    return s


def _is_valid_importo_amount(raw: str) -> bool:
    """Verifica se il raw importo è plausibile (non è un anno, ha lunghezza ragionevole)."""
    
    # Rimuovi spazi
    s = raw.replace(" ", "").replace(",", ".").replace(".", "", 1)  # primo punto è separatore, non migliaia
    
    # Escludere numeri 4 cifre (anni)
    if re.match(r"^\d{4}$", s):
        return False
    
    # Deve avere lunghezza tra 2 e 20 char (escludendo separatori)
    clean_digits = re.sub(r"[^\d]", "", raw)
    if len(clean_digits) < 2 or len(clean_digits) > 20:
        return False
    
    return True
