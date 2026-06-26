"""
OCR su PDF scansionati: converte le pagine in immagini e applica pytesseract.
Usato da DocumentHandler quando il PDF non ha layer testo sufficiente.
"""
from __future__ import annotations

import io

import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image

from app.config.settings import settings


class OcrProcessor:
    """
    Converte un PDF in immagini (pdf2image / Poppler) e ne estrae il testo
    tramite Tesseract OCR.

    Prerequisiti di sistema:
    - Poppler installato e nel PATH (per pdf2image)
    - Tesseract OCR installato e nel PATH (per pytesseract)
    """

    DEFAULT_LANG = "ita+eng"

    def __init__(self, lang: str | None = None) -> None:
        self.lang = lang or self.DEFAULT_LANG
        if settings.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

    def process(self, source: bytes | io.IOBase) -> tuple[str, int]:
        """
        Esegue OCR su tutte le pagine del PDF.

        Args:
            source: bytes del PDF oppure file-like object.

        Returns:
            Tupla (testo_ocr, numero_pagine).

        Raises:
            Exception: errori di Poppler, Tesseract o I/O.
        """
        if isinstance(source, io.IOBase):
            data = source.read()
        else:
            data = bytes(source)

        images: list[Image.Image] = convert_from_bytes(data)
        parts: list[str] = []
        for img in images:
            page_text: str = pytesseract.image_to_string(img, lang=self.lang)
            parts.append(page_text)

        return "\n".join(parts), len(images)
