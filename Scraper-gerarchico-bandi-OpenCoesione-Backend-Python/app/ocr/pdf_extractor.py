"""
Estrazione testo da PDF con layer testo nativo (pdfplumber).
Espone ExtractionResult, usato anche dagli altri moduli OCR.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any, Literal

import pdfplumber


@dataclass
class ExtractionResult:
    """Risultato unificato dell'estrazione testo da documento."""

    text: str | None
    method: Literal["text", "ocr", "failed"]
    page_count: int
    char_count: int
    extraction_time_ms: int
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class PdfTextExtractor:
    """
    Estrae testo da PDF nativi (con layer testo) usando pdfplumber.

    Restituisce il testo grezzo e contatori utili per decidere
    se è necessario passare all'OCR.
    """

    # Numero minimo di caratteri affinché una pagina sia considerata "con testo"
    MIN_CHARS_PER_PAGE: int = 50

    def extract(self, source: bytes | io.IOBase) -> tuple[str, int, int]:
        """
        Estrae testo dal PDF.

        Args:
            source: bytes del PDF oppure file-like object.

        Returns:
            Tupla (testo_completo, numero_pagine, pagine_con_testo).
            ``pagine_con_testo`` è usato dal chiamante per decidere se
            il documento è sostanzialmente privo di layer testo.

        Raises:
            pdfplumber.utils.exceptions.PDFSyntaxError: se il PDF è corrotto.
            Exception: qualsiasi altro errore di pdfplumber.
        """
        buf: io.IOBase
        if isinstance(source, (bytes, bytearray)):
            buf = io.BytesIO(source)
        else:
            buf = source

        with pdfplumber.open(buf) as pdf:
            page_count = len(pdf.pages)
            parts: list[str] = []
            text_pages = 0
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if len(page_text.strip()) >= self.MIN_CHARS_PER_PAGE:
                    text_pages += 1
                parts.append(page_text)

        full_text = "\n".join(parts)
        return full_text, page_count, text_pages
