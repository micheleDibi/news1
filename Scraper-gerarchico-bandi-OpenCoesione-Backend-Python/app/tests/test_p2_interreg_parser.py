"""
Test P2 — Parser famiglia Interreg (siti in lingua inglese).

Copre:
- estrazione date con mesi inglesi scritti ("27 November 2025")
- estrazione importi "X million EUR/Euros"
- etichette data inglesi (deadline, closing, opening)
- stato bando "closed" → chiuso
- stato bando "is open" → aperto
- titoli generici inglesi ("calls for proposals")
- integrazione simulata pagina call Interreg Central
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.parsers.bando_parser import (
    _extract_stato_bando,
    _is_generic_title,
    _parse_date,
    parse_bando_fields,
)
from app.ocr.page_detail_fetcher import _extract_page_dates, _extract_page_importo


# ---------------------------------------------------------------------------
# _parse_date — mesi inglesi
# ---------------------------------------------------------------------------

def test_parse_date_english_full_month():
    assert _parse_date("27 November 2025") == date(2025, 11, 27)


def test_parse_date_english_full_month_december():
    assert _parse_date("10 December 2024") == date(2024, 12, 10)


def test_parse_date_english_full_month_march():
    assert _parse_date("1 March 2026") == date(2026, 3, 1)


def test_parse_date_english_abbrev_month():
    assert _parse_date("15 Sep 2025") == date(2025, 9, 15)


def test_parse_date_english_may():
    assert _parse_date("3 May 2026") == date(2026, 5, 3)


def test_parse_date_dd_mm_yyyy_dot():
    # formato già supportato, verifica non regresso
    assert _parse_date("27.11.2025") == date(2025, 11, 27)


# ---------------------------------------------------------------------------
# _extract_page_dates — mesi inglesi
# ---------------------------------------------------------------------------

class _FakeSoup:
    """Minimal stub per _extract_page_dates che non richiede BeautifulSoup reale."""

    def __init__(self, text: str) -> None:
        self._text = text

    def __call__(self, *args, **kwargs):
        return []

    def get_text(self, *args, **kwargs) -> str:
        return self._text

    def find_all(self, *args, **kwargs):
        return []

    def select(self, *args, **kwargs):
        return []


def _make_soup(text: str):
    """Crea un soup BeautifulSoup minimale per i test page_detail_fetcher."""
    from bs4 import BeautifulSoup
    return BeautifulSoup(f"<html><body><p>{text}</p></body></html>", "html.parser")


def test_extract_page_dates_english_month():
    soup = _make_soup("The call closed on 27 November 2025.")
    dates = _extract_page_dates(soup)
    assert "27 November 2025" in dates


def test_extract_page_dates_english_month_december():
    soup = _make_soup("Third call closed on 10 December 2024.")
    dates = _extract_page_dates(soup)
    assert "10 December 2024" in dates


def test_extract_page_dates_numeric_format():
    # formato numerico già supportato, verifica non regresso
    soup = _make_soup("Date: 27.11.2025")
    dates = _extract_page_dates(soup)
    assert "27.11.2025" in dates


# ---------------------------------------------------------------------------
# _extract_page_importo — "X million EUR"
# ---------------------------------------------------------------------------

def test_extract_page_importo_million_euros():
    soup = _make_soup(
        "The call budget of around 23 million Euros from the European Regional Development Fund."
    )
    importo = _extract_page_importo(soup)
    assert importo == "23000000"


def test_extract_page_importo_million_eur_uppercase():
    soup = _make_soup("co-finance 47 new transnational projects with a budget of 76 million EUR.")
    importo = _extract_page_importo(soup)
    assert importo == "76000000"


def test_extract_page_importo_million_with_decimal():
    soup = _make_soup("A total budget of 1.5 million euros is available.")
    importo = _extract_page_importo(soup)
    assert importo == "1500000"


def test_extract_page_importo_billion_euros():
    soup = _make_soup("The fund provides 2 billion euros across all regions.")
    importo = _extract_page_importo(soup)
    assert importo == "2000000000"


# ---------------------------------------------------------------------------
# _extract_importo (corpus) — English "million EUR" in bando_parser
# ---------------------------------------------------------------------------

def test_parse_bando_fields_importo_million_english():
    raw = {
        "candidate_title": "Third call for proposals",
        "candidate_url": "https://www.interreg-central.eu/calls-for-proposals/third-call/",
        "parent_context": (
            "budget of around 15 million EUR from the European Regional Development Fund."
        ),
        "source_url": "https://www.interreg-central.eu/calls-for-proposals/",
    }
    parsed = parse_bando_fields("Third call for proposals", raw["candidate_url"], raw)
    assert parsed.importo_numerico == Decimal("15000000")


# ---------------------------------------------------------------------------
# _extract_stato_bando — inglese
# ---------------------------------------------------------------------------

def test_stato_bando_closed_english():
    assert _extract_stato_bando("The strategic call closed on 27 November.") == "chiuso"


def test_stato_bando_is_open_english():
    assert _extract_stato_bando("The call is open for applications.") == "aperto"


def test_stato_bando_upcoming_english():
    assert _extract_stato_bando("The upcoming third call will open in spring.") == "programmato"


def test_stato_bando_no_regression_chiuso_italian():
    assert _extract_stato_bando("bando chiuso al 30/06/2025") == "chiuso"


def test_stato_bando_no_regression_aperto_italian():
    assert _extract_stato_bando("bando aperto fino al 31/12/2026") == "aperto"


# ---------------------------------------------------------------------------
# _is_generic_title — nuovi pattern inglesi
# ---------------------------------------------------------------------------

def test_generic_title_calls_for_proposals():
    assert _is_generic_title("calls for proposals") is True


def test_generic_title_call_for_proposals():
    assert _is_generic_title("call for proposals") is True


def test_generic_title_timeline_of_calls():
    assert _is_generic_title("timeline of calls") is True


def test_generic_title_specific_call_not_generic():
    assert _is_generic_title("Third call for proposals – Central Europe 2024") is False


# ---------------------------------------------------------------------------
# Integrazione simulata — pagina call Interreg Central
# ---------------------------------------------------------------------------

def test_parse_bando_fields_interreg_central_strategic_call():
    """
    Simula il flusso completo per un record Interreg Central con dati
    estratti dalla pagina di dettaglio (come farebbe candidates_to_upsert_payload).
    """
    raw = {
        "candidate_title": "Strategic call for capitalisation",
        "candidate_url": "https://www.interreg-central.eu/calls-for-proposals/strategic-call-for-capitalisation/",
        "parent_context": (
            "Strategic call for capitalisation closed with 73 submissions. "
            "The call budget of around 23 million Euros from the ERDF."
        ),
        "source_url": "https://www.interreg-central.eu/calls-for-proposals/",
        # simulazione output fetch_bando_detail_page
        "page_title": "Strategic call for capitalisation closed with 73 submissions",
        "page_description": (
            "Our strategic call for capitalisation closed on 27 November 2025. "
            "The call budget of around 23 million Euros from the ERDF will be allocated "
            "to the best project proposals."
        ),
        "page_dates": ["27.11.2025"],
        "page_importo": "23000000",
        "page_content_snippet": (
            "Strategic call for capitalisation closed with 73 submissions. "
            "Date: 27.11.2025. Budget: 23 million Euros."
        ),
    }

    parsed = parse_bando_fields(
        "Strategic call for capitalisation",
        raw["candidate_url"],
        raw,
    )

    assert parsed.stato_bando == "chiuso"
    assert parsed.data_pubblicazione == date(2025, 11, 27)
    assert parsed.importo_numerico == Decimal("23000000")
    assert parsed.titolo != ""
    assert "sospetto" not in parsed.stato_bando


def test_parse_bando_fields_interreg_no_sospetto_with_date_only():
    """
    Un record con solo la data (senza importo) NON deve essere sospetto.
    """
    raw = {
        "candidate_title": "First call for proposals",
        "candidate_url": "https://www.interreg-central.eu/calls-for-proposals/first-call/",
        "parent_context": "First call closed on 23 February 2022.",
        "source_url": "https://www.interreg-central.eu/calls-for-proposals/",
        "page_dates": ["23.02.2022"],
    }

    parsed = parse_bando_fields("First call for proposals", raw["candidate_url"], raw)

    assert parsed.stato_bando != "sospetto"
    assert parsed.data_pubblicazione == date(2022, 2, 23)


def test_parse_bando_fields_interreg_deadline_label():
    """
    Estrae data_scadenza da etichetta 'deadline' in inglese.
    """
    raw = {
        "candidate_title": "Open call for projects",
        "candidate_url": "https://www.interreg-italiasvizzera.eu/wps/portal/site/avvisi/open-call",
        "parent_context": "Deadline: 30 June 2026 Submit your application.",
        "source_url": "https://www.interreg-italiasvizzera.eu/wps/portal/site/avvisi",
    }

    parsed = parse_bando_fields("Open call for projects", raw["candidate_url"], raw)

    assert parsed.data_scadenza == date(2026, 6, 30)
    assert parsed.stato_bando != "sospetto"
