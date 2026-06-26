"""
Orchestratore principale per l'estrazione testo da documenti PDF.

Flusso:
1. Scarica il PDF (se passato come URL) oppure usa i bytes già in memoria.
2. Tenta estrazione testo nativo via PdfTextExtractor.
3. Se il rapporto pagine-con-testo / totale-pagine è sotto soglia → OCR.
4. Normalizza il testo e restituisce ExtractionResult con metadati.
5. In caso di errore (PDF corrotto, timeout, ecc.) restituisce
   ExtractionResult(method="failed") senza propagare l'eccezione.
"""
from __future__ import annotations

import io
import re
import time
from typing import Literal

import httpx

from app.ocr.pdf_extractor import ExtractionResult, PdfTextExtractor
from app.ocr.ocr_processor import OcrProcessor


# Percentuale minima di pagine con testo per evitare OCR
TEXT_PAGE_RATIO_THRESHOLD: float = 0.5

# Timeout HTTP predefinito per il download PDF
DEFAULT_HTTP_TIMEOUT: int = 30


def normalize_text(text: str) -> str:
    """
    Normalizza il testo estratto:
    - Collassa sequenze di newline multiple in al massimo due.
    - Collassa spazi multipli in uno solo.
    - Rimuove spazi/newline a inizio/fine.
    """
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def has_cid_artifacts(text: str) -> bool:
    """Rileva artefatti tipici di mappatura ToUnicode rotta (es. '(cid:123)')."""
    if not text:
        return False
    return bool(re.search(r"\(cid(?::\d+)?\)", text, flags=re.IGNORECASE))


class DocumentHandler:
    """
    Entry point unificato per l'estrazione testo da PDF.

    Uso tipico::

        handler = DocumentHandler()

        # Da URL
        result = handler.extract_from_url("https://example.com/bando.pdf")

        # Da bytes (già scaricati o in memoria)
        result = handler.extract_from_bytes(pdf_bytes)

        if result.method != "failed":
            print(result.text)
    """

    def __init__(
        self,
        *,
        text_extractor: PdfTextExtractor | None = None,
        ocr_processor: OcrProcessor | None = None,
        text_page_ratio: float = TEXT_PAGE_RATIO_THRESHOLD,
        http_timeout: int = DEFAULT_HTTP_TIMEOUT,
    ) -> None:
        self._text_extractor = text_extractor or PdfTextExtractor()
        self._ocr_processor = ocr_processor or OcrProcessor()
        self._text_page_ratio = text_page_ratio
        self._http_timeout = http_timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_from_url(self, url: str) -> ExtractionResult:
        """
        Scarica il PDF dall'URL e ne estrae il testo.
        Non propaga eccezioni: gli errori sono catturati in ExtractionResult.
        """
        t0 = time.perf_counter()
        try:
            resp = httpx.get(url, timeout=self._http_timeout, follow_redirects=True)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "pdf" not in content_type.lower() and not url.lower().split("?")[0].endswith(".pdf"):
                return self._failed(
                    t0,
                    f"Risposta non-PDF: content-type='{content_type}', url='{url}'",
                )
            return self.extract_from_bytes(resp.content, _t0=t0)
        except Exception as exc:  # noqa: BLE001
            return self._failed(t0, str(exc))

    def extract_from_bytes(
        self,
        data: bytes,
        *,
        _t0: float | None = None,
    ) -> ExtractionResult:
        """
        Estrae testo da bytes PDF già in memoria.
        Non propaga eccezioni: gli errori sono catturati in ExtractionResult.
        """
        t0 = _t0 if _t0 is not None else time.perf_counter()
        try:
            text, page_count, text_pages = self._text_extractor.extract(data)

            if page_count == 0:
                return self._failed(t0, "PDF senza pagine o struttura non valida.")

            cid_artifacts_detected = has_cid_artifacts(text)
            needs_ocr = (text_pages / page_count) < self._text_page_ratio or cid_artifacts_detected

            if needs_ocr:
                ocr_text, _ = self._ocr_processor.process(data)
                final_text = normalize_text(ocr_text)
                method: Literal["text", "ocr", "failed"] = "ocr"
            else:
                final_text = normalize_text(text)
                method = "text"

            return ExtractionResult(
                text=final_text or None,
                method=method,
                page_count=page_count,
                char_count=len(final_text),
                extraction_time_ms=int((time.perf_counter() - t0) * 1000),
                metadata={
                    "text_pages": text_pages,
                    "ocr_triggered": needs_ocr,
                    "cid_artifacts_detected": cid_artifacts_detected,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return self._failed(t0, str(exc))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _failed(self, t0: float, error: str) -> ExtractionResult:
        return ExtractionResult(
            text=None,
            method="failed",
            page_count=0,
            char_count=0,
            extraction_time_ms=int((time.perf_counter() - t0) * 1000),
            error=error,
        )
