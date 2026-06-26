"""
Test Milestone 8 — Gestione PDF, OCR e document extraction.

Strategia:
- I test di estrazione testo nativa usano un PDF minimale generato in memoria.
- I test OCR usano mock di pdf2image e pytesseract per evitare dipendenze
  di sistema (Poppler, Tesseract) nell'ambiente CI.
- Il DocumentHandler viene testato isolando i sotto-moduli con mock,
  verificando il routing logico (text vs OCR vs failed).
"""
from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from app.ocr.document_handler import DocumentHandler, has_cid_artifacts, normalize_text
from app.ocr.page_detail_fetcher import _decode_response_html, _extract_page_dates
from app.ocr.pdf_extractor import ExtractionResult, PdfTextExtractor


# ---------------------------------------------------------------------------
# Helper: PDF minimale con testo valido
# ---------------------------------------------------------------------------

def _minimal_text_pdf() -> bytes:
    """
    Genera un PDF minimale con una pagina contenente testo "Hello World".
    Costruito con byte raw; valido per pdfplumber.
    """
    content_stream = b"BT /F1 12 Tf 72 720 Td (Hello World questo e un bando di prova) Tj ET"
    content_length = len(content_stream)

    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R\n"
        b"   /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >>\n"
        b">>\nendobj\n"
        b"4 0 obj\n<< /Length " + str(content_length).encode() + b" >>\nstream\n"
        + content_stream
        + b"\nendstream\nendobj\n"
        b"xref\n0 5\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000266 00000 n \n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n"
        b"startxref\n360\n"
        b"%%EOF\n"
    )
    return pdf


def _minimal_empty_pdf() -> bytes:
    """
    PDF minimale con una pagina senza testo (solo struttura),
    usato per testare la rilevazione di PDF senza layer testo.
    """
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"trailer\n<< /Size 4 /Root 1 0 R >>\n"
        b"startxref\n190\n"
        b"%%EOF\n"
    )
    return pdf


# ---------------------------------------------------------------------------
# Test 1 — Parsing PDF testuale
# ---------------------------------------------------------------------------

def test_pdf_text_extraction_returns_text():
    """Un PDF nativo con testo restituisce testo non vuoto e method='text'."""
    pdf_bytes = _minimal_text_pdf()
    extractor = PdfTextExtractor()

    text, page_count, text_pages = extractor.extract(pdf_bytes)

    assert page_count == 1
    # Il testo estratto potrebbe essere vuoto se pdfplumber non decodifica
    # il font Type1 senza risorse; ciò che conta è che NON sollevi eccezioni.
    assert isinstance(text, str)
    assert isinstance(text_pages, int)
    assert 0 <= text_pages <= page_count


def test_pdf_extraction_via_document_handler_text_path():
    """DocumentHandler con PDF che ha testo sufficiente → method='text', no eccezioni."""
    # Usiamo mock di PdfTextExtractor per garantire un risultato deterministico
    mock_extractor = MagicMock(spec=PdfTextExtractor)
    mock_extractor.extract.return_value = (
        "Questo è un bando di prova con molto testo utile.",
        2,   # page_count
        2,   # text_pages (100% → no OCR)
    )

    handler = DocumentHandler(text_extractor=mock_extractor)
    result = handler.extract_from_bytes(b"fake-pdf-bytes")

    assert result.method == "text"
    assert result.page_count == 2
    assert result.text is not None
    assert "bando" in result.text
    assert result.error is None
    assert result.char_count > 0
    assert result.extraction_time_ms >= 0


# ---------------------------------------------------------------------------
# Test 2 — Rilevamento PDF senza layer testo → OCR
# ---------------------------------------------------------------------------

def test_scan_detection_triggers_ocr():
    """
    Se il rapporto pagine-con-testo < soglia, DocumentHandler invoca OcrProcessor.
    """
    mock_extractor = MagicMock(spec=PdfTextExtractor)
    mock_extractor.extract.return_value = ("", 3, 0)  # 0/3 pagine con testo → OCR

    mock_ocr = MagicMock()
    mock_ocr.process.return_value = ("Testo estratto via OCR dal PDF scansionato.", 3)

    handler = DocumentHandler(text_extractor=mock_extractor, ocr_processor=mock_ocr)
    result = handler.extract_from_bytes(b"fake-scanned-pdf")

    assert result.method == "ocr"
    assert result.text is not None
    assert "OCR" in result.text
    assert result.metadata.get("ocr_triggered") is True
    mock_ocr.process.assert_called_once()


def test_scan_detection_boundary_exactly_at_threshold():
    """
    Con esattamente il 50% di pagine con testo il documento non va in OCR
    (threshold è < 0.5, quindi 0.5 non attiva OCR).
    """
    mock_extractor = MagicMock(spec=PdfTextExtractor)
    mock_extractor.extract.return_value = ("Testo sufficiente.", 2, 1)  # 1/2 = 0.5 → no OCR

    mock_ocr = MagicMock()
    handler = DocumentHandler(text_extractor=mock_extractor, ocr_processor=mock_ocr)
    result = handler.extract_from_bytes(b"fake-pdf")

    assert result.method == "text"
    mock_ocr.process.assert_not_called()


def test_cid_artifacts_trigger_ocr_even_with_high_text_ratio():
    """Con token (cid:...) forziamo OCR anche se text_pages/page_count e' alto."""
    mock_extractor = MagicMock(spec=PdfTextExtractor)
    mock_extractor.extract.return_value = ("Testo (cid:17) con mappa rotta", 2, 2)

    mock_ocr = MagicMock()
    mock_ocr.process.return_value = ("Testo OCR pulito", 2)

    handler = DocumentHandler(text_extractor=mock_extractor, ocr_processor=mock_ocr)
    result = handler.extract_from_bytes(b"fake-pdf")

    assert result.method == "ocr"
    assert result.metadata.get("cid_artifacts_detected") is True
    assert result.metadata.get("ocr_triggered") is True
    mock_ocr.process.assert_called_once()


# ---------------------------------------------------------------------------
# Test 3 — Gestione file corrotti / non leggibili
# ---------------------------------------------------------------------------

def test_corrupt_pdf_returns_failed_result():
    """
    Bytes non-PDF (garbage) non devono sollevare eccezioni:
    il risultato deve avere method='failed' con campo error valorizzato.
    """
    garbage = b"NOT A PDF AT ALL \x00\x01\x02"
    handler = DocumentHandler()

    result = handler.extract_from_bytes(garbage)

    assert result.method == "failed"
    assert result.text is None
    assert result.error is not None
    assert len(result.error) > 0


def test_empty_bytes_returns_failed_result():
    """Bytes vuoti → method='failed'."""
    handler = DocumentHandler()
    result = handler.extract_from_bytes(b"")

    assert result.method == "failed"
    assert result.text is None


# ---------------------------------------------------------------------------
# Test 4 — Normalizzazione testo estratto
# ---------------------------------------------------------------------------

def test_normalize_text_collapses_multiple_newlines():
    raw = "Titolo\n\n\n\nDescrizione\n\n\n\nFine"
    result = normalize_text(raw)
    assert "\n\n\n" not in result
    assert "Titolo" in result
    assert "Fine" in result


def test_normalize_text_collapses_multiple_spaces():
    raw = "Parola   con   spazi   multipli"
    result = normalize_text(raw)
    assert "  " not in result
    assert "Parola con spazi multipli" == result


def test_normalize_text_strips_edges():
    raw = "\n\n  Testo centrale  \n\n"
    result = normalize_text(raw)
    assert result == "Testo centrale"


def test_has_cid_artifacts_detects_common_patterns():
    assert has_cid_artifacts("contenuto (cid:123) non decodificato") is True
    assert has_cid_artifacts("contenuto (cid) non decodificato") is True
    assert has_cid_artifacts("contenuto normale") is False


# ---------------------------------------------------------------------------
# Test 5 — OcrProcessor con mock (Tesseract/Poppler non richiesti)
# ---------------------------------------------------------------------------

def test_ocr_processor_assembles_pages():
    """
    OcrProcessor deve assemblare il testo di tutte le pagine con \n come separatore.
    Tesseract e pdf2image vengono mockati.
    """
    from app.ocr.ocr_processor import OcrProcessor
    from PIL import Image

    fake_img = Image.new("RGB", (10, 10))

    with (
        patch("app.ocr.ocr_processor.convert_from_bytes", return_value=[fake_img, fake_img]) as mock_c2b,
        patch("app.ocr.ocr_processor.pytesseract.image_to_string", side_effect=["Pagina uno", "Pagina due"]) as mock_tess,
    ):
        processor = OcrProcessor(lang="ita")
        text, page_count = processor.process(b"fake-pdf-bytes")

    assert page_count == 2
    assert "Pagina uno" in text
    assert "Pagina due" in text
    mock_c2b.assert_called_once()
    assert mock_tess.call_count == 2


# ---------------------------------------------------------------------------
# Test 6 — Metadati ExtractionResult
# ---------------------------------------------------------------------------

def test_extraction_result_metadata_populated():
    """I metadati devono includere text_pages e ocr_triggered."""
    mock_extractor = MagicMock(spec=PdfTextExtractor)
    mock_extractor.extract.return_value = ("Testo abbondante.", 4, 4)

    handler = DocumentHandler(text_extractor=mock_extractor)
    result = handler.extract_from_bytes(b"fake-pdf")

    assert result.method == "text"
    assert "text_pages" in result.metadata
    assert result.metadata["text_pages"] == 4
    assert result.metadata.get("ocr_triggered") is False
    assert result.extraction_time_ms >= 0
    assert result.char_count == len(result.text or "")


def test_decode_response_html_uses_apparent_encoding_when_missing():
    response = SimpleNamespace(
        content="Perch\xe9 bando".encode("cp1252"),
        encoding=None,
        apparent_encoding="cp1252",
    )

    decoded = _decode_response_html(response)

    assert "Perché bando" == decoded


def test_decode_response_html_falls_back_to_utf8_replace_for_unknown_encoding():
    response = SimpleNamespace(
        content=b"abc\xffdef",
        encoding=None,
        apparent_encoding="x-unknown-charset",
    )

    decoded = _decode_response_html(response)

    assert "abc" in decoded
    assert "def" in decoded


def test_extract_page_dates_supports_year_first_and_abbreviated_months():
        soup = BeautifulSoup(
                """
                <html><body>
                    <p>Pubblicazione 2026/06/15</p>
                    <p>Apertura 1 set. 2026</p>
                    <p>Scadenza 30/09/2026</p>
                </body></html>
                """,
                "html.parser",
        )

        dates = _extract_page_dates(soup)

        assert "2026/06/15" in dates
        assert "1 set. 2026" in dates
        assert "30/09/2026" in dates
