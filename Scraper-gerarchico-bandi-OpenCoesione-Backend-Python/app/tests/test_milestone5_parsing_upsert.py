"""
Test Milestone 5 — Parsing dettagli bando, upsert e storico modifiche.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
import os
import uuid

import pytest

from app.db.connection import get_db_connection
from app.parsers.bando_parser import parse_bando_fields
from app.repos.base import BandoRepo


def test_parse_bando_fields_estrazione_principale():
    raw = {
        "candidate_title": "Avviso pubblico codice ABC-123 apertura 01/05/2026 scadenza 30/06/2026 importo € 1.234.567,89",
        "candidate_url": "https://example.org/bandi/avviso-abc",
        "parent_context": "Pubblicazione 20/04/2026",
        "source_url": "https://example.org/fonte",
    }

    parsed = parse_bando_fields("Avviso pubblico ABC-123", raw["candidate_url"], raw)

    assert parsed.titolo.startswith("Avviso pubblico")
    assert parsed.codice_bando is not None
    assert parsed.stato_bando in {"aperto", "programmato", "chiuso"}
    assert parsed.data_apertura == date(2026, 5, 1)
    assert parsed.data_scadenza == date(2026, 6, 30)
    assert parsed.importo_numerico == Decimal("1234567.89")


def test_parse_bando_fields_importo_da_page_content_snippet():
    raw = {
        "candidate_title": "Avviso pubblico investimenti",
        "candidate_url": "https://example.org/bandi/xyz",
        "parent_context": "Dettagli bando",
        "source_url": "https://example.org/fonte",
        "page_content_snippet": "Dotazione finanziaria complessiva pari a euro 1.250.000 per il triennio.",
    }

    parsed = parse_bando_fields("Avviso investimenti", raw["candidate_url"], raw)

    assert parsed.importo_numerico == Decimal("1250000")


def test_parse_bando_fields_importo_dot_thousands_normalization():
    raw = {
        "candidate_title": "Avviso pubblico",
        "candidate_url": "https://example.org/bandi/abc",
        "parent_context": "Importo massimo euro 12.500",
        "source_url": "https://example.org/fonte",
    }

    parsed = parse_bando_fields("Avviso dotazione", raw["candidate_url"], raw)

    assert parsed.importo_numerico == Decimal("12500")


def test_parse_bando_fields_importo_fallback_to_corpus_when_page_importo_not_parsable():
    raw = {
        "candidate_title": "Avviso pubblico incentivi",
        "candidate_url": "https://example.org/bandi/importo-fallback",
        "parent_context": "Contesto",
        "source_url": "https://example.org/fonte",
        "page_importo": "importo da definire",
        "page_content_snippet": "Contributo massimo concedibile euro 750.000 per progetto.",
    }

    parsed = parse_bando_fields("Avviso fallback importo", raw["candidate_url"], raw)

    assert parsed.importo_numerico == Decimal("750000")


def test_parse_bando_fields_importo_prefers_larger_corpus_value_over_small_page_importo():
    raw = {
        "candidate_title": "Avviso pubblico investimento strategico",
        "candidate_url": "https://example.org/bandi/avviso-investimento",
        "parent_context": "Contesto",
        "source_url": "https://example.org/fonte",
        "page_importo": "2026",
        "page_content_snippet": "Dotazione finanziaria complessiva pari a euro 850.000 per interventi ammessi.",
    }

    parsed = parse_bando_fields("Avviso investimento", raw["candidate_url"], raw)

    assert parsed.importo_numerico == Decimal("850000")


def test_parse_bando_fields_discards_noisy_micro_import_without_strong_economic_context():
    raw = {
        "candidate_title": "Apply for the call",
        "candidate_url": "https://example.org/apply-for-call",
        "parent_context": "Contesto generico",
        "source_url": "https://example.org/fonte",
        "page_pdf_importo": "3 94.5",
        "page_content_snippet": "Apply for the call | Go to main menu | Go to search",
    }

    parsed = parse_bando_fields("Apply for the call", raw["candidate_url"], raw)

    assert parsed.importo_numerico is None


def test_parse_bando_fields_importo_with_multiplier_units():
    raw = {
        "candidate_title": "Contributo fino a 1,5 milioni di euro per progetti strategici",
        "candidate_url": "https://example.org/bandi/importo-milioni",
        "parent_context": "Dotazione complessiva 250 mila euro per micro-imprese",
        "source_url": "https://example.org/fonte",
    }

    parsed = parse_bando_fields("Avviso contributi", raw["candidate_url"], raw)

    assert parsed.importo_numerico == Decimal("1500000")


def test_parse_bando_fields_date_fallback_from_url_when_text_missing():
    raw = {
        "candidate_title": "Avviso pubblico senza data nel testo",
        "candidate_url": "https://example.org/bandi/2026/07/15/avviso-imprese",
        "parent_context": "Contesto senza date",
        "source_url": "https://example.org/fonte/news/20260710",
    }

    parsed = parse_bando_fields("Avviso senza date", raw["candidate_url"], raw)

    assert parsed.data_pubblicazione == date(2026, 7, 15)


def test_parse_bando_fields_pdf_fallback_description_dates_importo():
    raw = {
        "candidate_title": "Avviso integrativo",
        "candidate_url": "https://example.org/bandi/p4",
        "parent_context": "Contesto minimale",
        "source_url": "https://example.org/fonte",
        "pdf_text_snippet": "Testo estratto da PDF allegato con dettagli operativi.",
        "page_pdf_dates": ["15/06/2026", "30/09/2026"],
        "page_pdf_importo": "2.500.000",
    }

    parsed = parse_bando_fields("Avviso P4", raw["candidate_url"], raw)

    assert parsed.descrizione is not None
    assert "PDF" in parsed.descrizione
    assert parsed.data_pubblicazione == date(2026, 6, 15)
    assert parsed.importo_numerico == Decimal("2500000")


def test_parse_bando_fields_uses_unlabeled_page_dates_for_apertura_and_scadenza():
    raw = {
        "candidate_title": "Avviso multi-data",
        "candidate_url": "https://example.org/bandi/multi-date",
        "parent_context": "Contesto",
        "source_url": "https://example.org/fonte",
        "page_dates": ["15/06/2026", "01/07/2026", "30/09/2026"],
    }

    parsed = parse_bando_fields("Avviso multi-data", raw["candidate_url"], raw)

    assert parsed.data_pubblicazione == date(2026, 6, 15)
    assert parsed.data_apertura == date(2026, 7, 1)
    assert parsed.data_scadenza == date(2026, 9, 30)


def test_parse_bando_fields_prefers_candidate_title_over_generic_page_title():
    raw = {
        "candidate_title": "Call for pilot actions 2024",
        "candidate_url": "https://example.org/call-for-pilot-actions",
        "parent_context": "Contesto",
        "source_url": "https://example.org/fonte",
        "page_title": "Ask us a question | Interreg Europe",
    }

    parsed = parse_bando_fields("Call for pilot actions 2024", raw["candidate_url"], raw)

    assert parsed.titolo == "Call for pilot actions 2024"


def test_parse_bando_fields_builds_title_from_snippet_and_link_slug():
    raw = {
        "candidate_title": "Bandi e Opportunita",
        "candidate_url": "https://calabria.example.org/bandi/avviso-sostegno-imprese-innovazione",
        "parent_context": "Bandi e Opportunita",
        "source_url": "https://calabria.example.org/bandi",
        "page_title": "Bandi e Opportunita",
        "page_content_snippet_300": "Bandi e Opportunita | Avviso pubblico per il sostegno alle imprese innovative 2026 | Cerca Dipartimento",
    }

    parsed = parse_bando_fields("Bandi e Opportunita", raw["candidate_url"], raw)

    assert parsed.titolo == "Avviso pubblico per il sostegno alle imprese innovative 2026"


def test_parse_bando_fields_never_returns_raw_link_as_title():
    raw = {
        "candidate_title": "",
        "candidate_url": "https://example.org/bandi/fondo-startup-giovani",
        "parent_context": "",
        "source_url": "https://example.org/bandi",
    }

    parsed = parse_bando_fields("", raw["candidate_url"], raw)

    assert parsed.titolo == "Fondo Startup Giovani"


def test_parse_bando_fields_piemonte_prefers_slug_when_title_is_raw_url():
    raw = {
        "candidate_title": "https://www.regione.piemonte.it/web/temi/istruzione-formazione-lavoro/istruzione/voucher-scuola",
        "candidate_url": "https://www.regione.piemonte.it/web/temi/istruzione-formazione-lavoro/istruzione/voucher-scuola",
        "parent_context": "Bandi e finanziamenti",
        "source_url": "https://www.regione.piemonte.it/web/temi/fondi-progetti-europei/fondo-sociale-europeo-fse",
        "page_title": "Bandi e finanziamenti",
    }

    parsed = parse_bando_fields(raw["candidate_title"], raw["candidate_url"], raw)

    assert parsed.titolo == "Voucher Scuola"


def test_parse_bando_fields_marks_as_suspicious_when_all_critical_fields_null():
    raw = {
        "candidate_title": "Bandi e Gare",
        "candidate_url": "https://www.regione.liguria.it/homepage-bandi-e-avvisi/publiccompetition",
        "parent_context": "Bandi e Gare",
        "source_url": "https://www.regione.liguria.it/bandi",
    }

    parsed = parse_bando_fields("Bandi e Gare", raw["candidate_url"], raw)

    assert parsed.data_pubblicazione is None
    assert parsed.data_apertura is None
    assert parsed.data_scadenza is None
    assert parsed.importo_numerico is None
    assert parsed.stato_bando == "sospetto"


@pytest.mark.integration
def test_upsert_bando_crea_storico_su_modifica():
    if os.getenv("ENABLE_DB_WRITE_TESTS", "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip("DB write test disabled. Set ENABLE_DB_WRITE_TESTS=1 to run.")

    repo = BandoRepo()
    unique_hash = f"test-hash-{uuid.uuid4()}"
    link = f"https://example.org/bandi/{uuid.uuid4()}"

    payload_insert = {
        "fonte_id": 1,
        "titolo": "Titolo iniziale",
        "descrizione": "Descrizione iniziale",
        "codice_bando": "COD-INIT",
        "stato_bando": "programmato",
        "data_pubblicazione": date(2026, 4, 20),
        "data_apertura": date(2026, 5, 1),
        "data_scadenza": date(2026, 6, 1),
        "link_bando": link,
        "hash_bando": unique_hash,
        "importo": "1000",
        "importo_numerico": Decimal("1000"),
        "data_extra": {"source": "test"},
        "raw_data_obj": {"v": 1},
        "raw_data": json.dumps({"v": 1}),
        "scraping_log_id": None,
    }

    payload_update = {
        **payload_insert,
        "titolo": "Titolo aggiornato",
        "codice_bando": "COD-UPD",
        "stato_bando": "aperto",
        "raw_data_obj": {"v": 2},
        "raw_data": json.dumps({"v": 2}),
    }

    try:
        stats_insert = repo.upsert_candidates([payload_insert])
        assert stats_insert["inserted"] == 1

        stats_update = repo.upsert_candidates([payload_update])
        assert stats_update["updated"] == 1

        payload_close = {
            **payload_update,
            "stato_bando": "chiuso",
            "raw_data_obj": {"v": 3},
            "raw_data": json.dumps({"v": 3}),
        }
        stats_close = repo.upsert_candidates([payload_close])
        assert stats_close["updated"] == 1

        repo.upsert_candidates([payload_close])

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM public.bando WHERE hash_bando = %s", (unique_hash,))
                bando = cur.fetchone()
                assert bando is not None

                cur.execute(
                    """
                    SELECT campi_modificati, dati_precedenti, dati_nuovi
                    FROM public.bando_storico
                    WHERE bando_id = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (bando["id"],),
                )
                row = cur.fetchone()

                cur.execute(
                    """
                    SELECT campi_modificati, dati_precedenti, dati_nuovi
                    FROM public.bando_storico
                    WHERE bando_id = %s
                    ORDER BY id ASC
                    """,
                    (bando["id"],),
                )
                all_rows = cur.fetchall()

                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM public.bando WHERE hash_bando = %s",
                    (unique_hash,),
                )
                count_row = cur.fetchone()

        assert row is not None
        stato_changes = [
            r for r in all_rows if "stato_bando" in (r.get("campi_modificati") or [])
        ]
        assert len(stato_changes) >= 1
        assert stato_changes[-1]["dati_nuovi"]["stato_bando"] == "chiuso"
        assert count_row["cnt"] == 1
    finally:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM public.bando_storico WHERE bando_id IN (SELECT id FROM public.bando WHERE hash_bando = %s)",
                    (unique_hash,),
                )
                cur.execute("DELETE FROM public.bando WHERE hash_bando = %s", (unique_hash,))
