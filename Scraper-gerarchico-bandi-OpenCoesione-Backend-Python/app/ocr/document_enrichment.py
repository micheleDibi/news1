from __future__ import annotations

import logging
import re
from typing import Any

from app.ocr.document_handler import DocumentHandler

logger = logging.getLogger(__name__)

_DATE_PATTERN = (
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|"
    r"luglio|agosto|settembre|ottobre|novembre|dicembre)\s+\d{4})"
)


def enrich_from_pdf_links(
    pdf_links: list[str],
    *,
    max_pdfs: int = 1,
    min_text_chars: int = 120,
) -> dict[str, Any]:
    """Arricchisce il raw_data con testo e segnali estratti da PDF allegati.

    Non solleva eccezioni: in caso di errori restituisce campi diagnostici.
    """
    if not pdf_links:
        return {}

    handler = DocumentHandler()
    selected_links = [str(link) for link in pdf_links if link][: max(1, max_pdfs)]
    result: dict[str, Any] = {
        "pdf_enrichment_attempted": len(selected_links),
        "pdf_source_links": selected_links,
    }

    last_error: str | None = None
    for pdf_url in selected_links:
        extraction = handler.extract_from_url(pdf_url)
        if extraction.method == "failed" or not extraction.text:
            last_error = extraction.error or "pdf_extraction_failed"
            continue

        text = _clean_text(extraction.text)
        if len(text) < min_text_chars:
            last_error = "pdf_text_too_short"
            continue

        result.update(
            {
                "pdf_enrichment_used": True,
                "pdf_selected_url": pdf_url,
                "pdf_extraction_method": extraction.method,
                "pdf_char_count": int(extraction.char_count),
                "pdf_text_snippet": text[:4000],
            }
        )

        importo = _extract_importo(text)
        if importo:
            result["page_pdf_importo"] = importo

        dates = _extract_dates(text)
        if dates:
            result["page_pdf_dates"] = dates

        return result

    if last_error:
        result["pdf_enrichment_error"] = last_error
    return result


def _extract_importo(text: str) -> str | None:
    patterns = [
        r"(?:€|eur|euro)\s*([0-9][0-9\s\.,]{0,30})",
        r"([0-9][0-9\s\.,]{3,30})\s*(?:€|eur|euro)",
        r"(?:importo|dotazione(?:\s+finanziaria)?|finanziamento(?:\s+massimo)?|contributo(?:\s+massimo)?)"
        r"[^0-9]{0,20}([0-9][0-9\s\.,]{3,30})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        return match.group(1).strip()
    return None


def _extract_dates(text: str) -> list[str]:
    matches = re.findall(_DATE_PATTERN, text, flags=re.IGNORECASE)
    out: list[str] = []
    seen: set[str] = set()
    for value in matches:
        normalized = _clean_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out[:10]


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())
