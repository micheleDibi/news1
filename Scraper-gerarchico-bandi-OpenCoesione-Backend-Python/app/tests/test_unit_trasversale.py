"""
Test plan trasversale — Unit test

Coprono i 7 ambiti del test plan trasversale:
  1. parser HTML  (estrazione bandi da HTML)
  2. parser PDF   (scan su singolo file PDF)
  3. parser CSV   (scan su fonte CSV)
  4. hash bando   (unicità e stabilità dell'hash)
  5. matching reference data  (classificazione deterministica)
  6. diff storico (rilevamento campi modificati)
  7. policy retry (_is_recoverable_error)
  8. validatore output AI  (AiClassificationOutputValidator)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 1. Parser HTML — parse_bando_fields
# ---------------------------------------------------------------------------

from app.parsers.bando_parser import (
    parse_bando_fields,
    _extract_stato_bando,
    _extract_all_dates,
    _extract_importo,
    _build_corpus,
)


class TestParserHtml:
    def test_stato_bando_testo_non_evita_sospetto_senza_campi_critici_aperto(self):
        f = parse_bando_fields("Bando aperto: contributi alle imprese", "https://x.org/b1", {})
        assert f.stato_bando == "sospetto"

    def test_stato_bando_testo_non_evita_sospetto_senza_campi_critici_chiuso(self):
        f = parse_bando_fields("Bando chiuso 2023", "https://x.org/b2", {})
        assert f.stato_bando == "sospetto"

    def test_stato_bando_testo_non_evita_sospetto_senza_campi_critici_programmato(self):
        f = parse_bando_fields("Prossimo avviso in arrivo", "https://x.org/b3", {})
        assert f.stato_bando == "sospetto"

    def test_titolo_troncato_a_4000_caratteri(self):
        lungo = "X" * 5000
        f = parse_bando_fields(lungo, "https://x.org/b4", {})
        assert len(f.titolo) == 4000

    def test_codice_bando_da_pattern_cod(self):
        f = parse_bando_fields("Codice bando: ABC-2024/001", "https://x.org/b5", {})
        assert f.codice_bando is not None
        assert "ABC" in f.codice_bando

    def test_data_pubblicazione_da_label(self):
        raw = {"parent_context": "Pubblicazione 15/03/2024"}
        f = parse_bando_fields("Avviso", "https://x.org/b6", raw)
        assert f.data_pubblicazione == date(2024, 3, 15)

    def test_data_scadenza_da_corpus(self):
        raw = {"parent_context": "Scadenza: 30/06/2025"}
        f = parse_bando_fields("Bando aperto", "https://x.org/b7", raw)
        assert f.data_scadenza == date(2025, 6, 30)

    def test_importo_estratto_formato_euro(self):
        raw = {"parent_context": "Dotazione finanziaria: € 1.500.000,00"}
        f = parse_bando_fields("Contributo", "https://x.org/b8", raw)
        assert f.importo is not None
        assert f.importo_numerico == Decimal("1500000.00")

    def test_importo_formato_valore_poi_simbolo(self):
        raw = {"parent_context": "Fino a 500.000 euro disponibili"}
        f = parse_bando_fields("Voucher", "https://x.org/b9", raw)
        assert f.importo_numerico is not None

    def test_importo_da_label_senza_simbolo_euro(self):
        raw = {"parent_context": "Dotazione finanziaria: 1.200.000,50"}
        f = parse_bando_fields("Voucher", "https://x.org/b9b", raw)
        assert f.importo_numerico == Decimal("1200000.50")

    def test_senza_dati_descrizione_nulla(self):
        f = parse_bando_fields("Titolo", "https://x.org/b10", {})
        assert f.descrizione is None

    def test_descrizione_da_parent_context_diverso_da_titolo(self):
        raw = {"candidate_title": "Titolo", "parent_context": "Contesto più lungo con dettagli"}
        f = parse_bando_fields("Titolo", "https://x.org/b11", raw)
        assert f.descrizione == "Contesto più lungo con dettagli"

    def test_data_iso_format_riconosciuta(self):
        raw = {"parent_context": "Apertura 2024-09-01"}
        f = parse_bando_fields("Bando", "https://x.org/b12", raw)
        assert f.data_apertura == date(2024, 9, 1)

    def test_data_testuale_italiana_riconosciuta(self):
        raw = {"parent_context": "Pubblicazione 15 marzo 2026"}
        f = parse_bando_fields("Bando", "https://x.org/b12b", raw)
        assert f.data_pubblicazione == date(2026, 3, 15)

    def test_data_con_punto_riconosciuta(self):
        raw = {"parent_context": "Scadenza: 30.06.2026"}
        f = parse_bando_fields("Bando", "https://x.org/b12c", raw)
        assert f.data_scadenza == date(2026, 6, 30)

    def test_data_extra_contiene_date_candidate(self):
        raw = {"parent_context": "01/01/2024 e 31/12/2025"}
        f = parse_bando_fields("Bando", "https://x.org/b13", raw)
        assert f.data_extra is not None
        assert "date_candidates" in f.data_extra


# ---------------------------------------------------------------------------
# 2. Parser PDF — FonteLevel2Scanner._scan_single_file
# ---------------------------------------------------------------------------

from app.scrapers.fonte_level2 import FonteLevel2Scanner, BandoCandidate, candidates_to_upsert_payload


class TestParserPdf:
    def test_scan_pdf_produce_un_candidato(self):
        """_scan_single_file (usato per PDF) restituisce sempre esattamente 1 candidato."""
        scanner = FonteLevel2Scanner()
        candidates = scanner._scan_single_file(
            fonte_id=10,
            source_url="https://example.org/avviso.pdf",
            fonte_format="PDF",
        )
        assert len(candidates) == 1
        assert candidates[0].formato_fonte == "PDF"
        assert candidates[0].fonte_id == 10
        assert candidates[0].link_bando == "https://example.org/avviso.pdf"

    def test_scan_pdf_hash_deterministo(self):
        """Lo stesso PDF sulla stessa fonte deve sempre produrre lo stesso hash."""
        scanner = FonteLevel2Scanner()
        c1 = scanner._scan_single_file(99, "https://example.org/doc.pdf", "PDF")
        c2 = scanner._scan_single_file(99, "https://example.org/doc.pdf", "PDF")
        assert c1[0].hash_bando == c2[0].hash_bando

    def test_scan_zip_produce_un_candidato(self):
        scanner = FonteLevel2Scanner()
        candidates = scanner._scan_single_file(
            fonte_id=11,
            source_url="https://example.org/dati.zip",
            fonte_format="ZIP",
        )
        assert len(candidates) == 1
        assert candidates[0].formato_fonte == "ZIP"

    def test_scan_pdf_raw_data_contiene_fonte_id(self):
        scanner = FonteLevel2Scanner()
        c = scanner._scan_single_file(55, "https://example.org/x.pdf", "PDF")[0]
        assert c.raw_data_obj["fonte_id"] == 55

    def test_candidates_to_upsert_payload_da_pdf(self):
        """candidates_to_upsert_payload deve funzionare correttamente con un candidato PDF."""
        scanner = FonteLevel2Scanner()
        candidate = scanner._scan_single_file(10, "https://example.org/avviso.pdf", "PDF")[0]
        payload = candidates_to_upsert_payload([candidate], scraping_log_id=42)
        assert len(payload) == 1
        assert payload[0]["hash_bando"] == candidate.hash_bando
        assert payload[0]["scraping_log_id"] == 42
        assert payload[0]["fonte_id"] == 10


# ---------------------------------------------------------------------------
# 3. Parser CSV — FonteLevel2Scanner._scan_csv
# ---------------------------------------------------------------------------

class TestParserCsv:
    def _make_csv_response(self, urls: list[str]) -> MagicMock:
        text = "\n".join(urls)
        resp = MagicMock()
        resp.text = text
        resp.raise_for_status = MagicMock()
        return resp

    def test_csv_con_url_validi_produce_candidati(self):
        scanner = FonteLevel2Scanner()
        urls = [
            "https://example.org/bando-a",
            "https://example.org/avviso-b",
        ]
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = self._make_csv_response(urls)
            mock_client_cls.return_value = mock_client

            candidates = scanner._scan_csv(1, "https://example.org/lista.csv", "CSV")

        assert len(candidates) == 2
        link_bandi = [c.link_bando for c in candidates]
        assert "https://example.org/bando-a" in link_bandi
        assert "https://example.org/avviso-b" in link_bandi

    def test_csv_vuoto_produce_fallback_candidato(self):
        """Se il CSV non contiene URL, il fallback produce 1 candidato sull'URL della fonte."""
        scanner = FonteLevel2Scanner()
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = self._make_csv_response(["non,un,url", "altra,riga"])
            mock_client_cls.return_value = mock_client

            candidates = scanner._scan_csv(2, "https://example.org/lista.csv", "CSV")

        assert len(candidates) == 1
        assert candidates[0].link_bando == "https://example.org/lista.csv"

    def test_csv_deduplicazione_url_duplicati(self):
        """URL duplicati nello stesso CSV devono produrre un solo candidato."""
        scanner = FonteLevel2Scanner()
        url = "https://example.org/bando"
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = self._make_csv_response([url, url, url])
            mock_client_cls.return_value = mock_client

            candidates = scanner._scan_csv(3, "https://example.org/lista.csv", "CSV")

        assert len(candidates) == 1


# ---------------------------------------------------------------------------
# 4. Hash bando
# ---------------------------------------------------------------------------

class TestHashBando:
    def test_hash_stesso_input_produce_stesso_hash(self):
        h1 = FonteLevel2Scanner._build_hash(1, "https://example.org/bando")
        h2 = FonteLevel2Scanner._build_hash(1, "https://example.org/bando")
        assert h1 == h2

    def test_hash_fonte_diversa_produce_hash_diverso(self):
        h1 = FonteLevel2Scanner._build_hash(1, "https://example.org/bando")
        h2 = FonteLevel2Scanner._build_hash(2, "https://example.org/bando")
        assert h1 != h2

    def test_hash_url_diverso_produce_hash_diverso(self):
        h1 = FonteLevel2Scanner._build_hash(1, "https://example.org/bando-a")
        h2 = FonteLevel2Scanner._build_hash(1, "https://example.org/bando-b")
        assert h1 != h2

    def test_hash_e_stringa_hex_di_64_caratteri(self):
        h = FonteLevel2Scanner._build_hash(1, "https://example.org/bando")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_case_sensitive_su_url(self):
        h1 = FonteLevel2Scanner._build_hash(1, "https://example.org/BANDO")
        h2 = FonteLevel2Scanner._build_hash(1, "https://example.org/bando")
        assert h1 != h2


# ---------------------------------------------------------------------------
# 5. Matching reference data (classificazione deterministica)
# ---------------------------------------------------------------------------

from app.services.classification_service import (
    ControlledClassificationService,
    ReferenceCatalog,
    ReferenceOption,
    _build_option,
    _normalize_text,
)


def _make_catalog(**kwargs) -> ReferenceCatalog:
    defaults = {
        "tipologie_bando": (),
        "modalita_erogazione": (),
        "programmi": (),
        "regioni": (),
        "settori": (),
        "beneficiari": (),
        "codici_ateco": (),
        "categoria_programma": (),
        "tipologia_programma": (),
    }
    defaults.update(kwargs)
    return ReferenceCatalog(**defaults)


def _make_service(catalog: ReferenceCatalog) -> ControlledClassificationService:
    svc = ControlledClassificationService.__new__(ControlledClassificationService)
    svc.reference_repo = None
    svc.catalog = catalog
    return svc


class TestMatchingReferenceData:
    def test_match_esatto_tipologia_bando(self):
        opt = _build_option(1, "Bando nazionale")
        catalog = _make_catalog(tipologie_bando=(opt,))
        svc = _make_service(catalog)
        result = svc.classify_candidate({"titolo": "Bando nazionale per le PMI"})
        assert result.get("tipologia_bando_id") == 1

    def test_nessun_match_non_propaga_id(self):
        opt = _build_option(1, "Bando europeo")
        catalog = _make_catalog(tipologie_bando=(opt,))
        svc = _make_service(catalog)
        result = svc.classify_candidate({"titolo": "Finanziamento completamente diverso xyz"})
        # nessun match → il campo non è nel risultato
        assert "tipologia_bando_id" not in result

    def test_match_regione_da_titolo(self):
        opt = _build_option(10, "Toscana")
        catalog = _make_catalog(regioni=(opt,))
        svc = _make_service(catalog)
        result = svc.classify_candidate({"titolo": "Avviso Regione Toscana 2024"})
        assert 10 in result.get("regione_ids", [])

    def test_match_piu_regioni(self):
        r1 = _build_option(1, "Lombardia")
        r2 = _build_option(2, "Veneto")
        catalog = _make_catalog(regioni=(r1, r2))
        svc = _make_service(catalog)
        result = svc.classify_candidate({"titolo": "Bando Lombardia e Veneto"})
        regioni = result.get("regione_ids", [])
        assert 1 in regioni
        assert 2 in regioni

    def test_classify_candidates_lista_preserva_ordine(self):
        opt = _build_option(5, "Contributo a fondo perduto")
        catalog = _make_catalog(modalita_erogazione=(opt,))
        svc = _make_service(catalog)
        payloads = [
            {"titolo": "Avviso alfa"},
            {"titolo": "Contributo a fondo perduto per imprese"},
            {"titolo": "Avviso beta"},
        ]
        results = svc.classify_candidates(payloads)
        assert len(results) == 3
        assert "modalita_erogazione_id" not in results[0]
        assert results[1].get("modalita_erogazione_id") == 5
        assert "modalita_erogazione_id" not in results[2]

    def test_valore_fuori_dizionario_non_inserito(self):
        """Il classificatore non deve mai inserire un id non presente nel catalogo."""
        opt = _build_option(99, "Bando noto")
        catalog = _make_catalog(tipologie_bando=(opt,))
        svc = _make_service(catalog)
        result = svc.classify_candidate({"titolo": "Tipologia inventata XYZ-123"})
        assert result.get("tipologia_bando_id") != 999
        assert "tipologia_bando_id" not in result or result["tipologia_bando_id"] == 99


# ---------------------------------------------------------------------------
# 6. Diff storico — logica di rilevamento campi modificati
# ---------------------------------------------------------------------------
#
# Il diff è implementato direttamente nel metodo upsert_candidates di BandoRepo.
# Lo testiamo attraverso la funzione di confronto equivalente inline.

def _compute_changed_fields(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Replica la logica di diff in BandoRepo.upsert_candidates."""
    from app.repos.base import _date_to_iso, _decimal_to_str

    compare_keys = [
        "titolo", "descrizione", "codice_bando", "stato_bando",
        "data_pubblicazione", "data_apertura", "data_scadenza",
        "link_bando", "importo", "importo_numerico",
    ]
    changed: list[str] = []
    for field in compare_keys:
        old_val = old.get(field)
        new_val = new.get(field)
        if field in {"data_pubblicazione", "data_apertura", "data_scadenza"}:
            old_val = _date_to_iso(old_val)
            new_val = _date_to_iso(new_val)
        elif field == "importo_numerico":
            old_val = _decimal_to_str(old_val)
            new_val = _decimal_to_str(new_val)
        if old_val != new_val:
            changed.append(field)
    return changed


class TestDiffStorico:
    def test_nessuna_modifica_lista_vuota(self):
        bando = {"titolo": "T", "stato_bando": "aperto", "link_bando": "http://x"}
        changed = _compute_changed_fields(bando, bando.copy())
        assert changed == []

    def test_titolo_cambiato_rilevato(self):
        old = {"titolo": "Vecchio titolo", "stato_bando": "programmato"}
        new = {"titolo": "Nuovo titolo", "stato_bando": "programmato"}
        changed = _compute_changed_fields(old, new)
        assert "titolo" in changed

    def test_stato_cambiato_rilevato(self):
        old = {"stato_bando": "programmato"}
        new = {"stato_bando": "aperto"}
        changed = _compute_changed_fields(old, new)
        assert "stato_bando" in changed

    def test_data_scadenza_cambiata_rilevata(self):
        old = {"data_scadenza": date(2024, 6, 30)}
        new = {"data_scadenza": date(2024, 12, 31)}
        changed = _compute_changed_fields(old, new)
        assert "data_scadenza" in changed

    def test_data_scadenza_identica_non_rilevata(self):
        d = date(2024, 6, 30)
        old = {"data_scadenza": d}
        new = {"data_scadenza": d}
        changed = _compute_changed_fields(old, new)
        assert "data_scadenza" not in changed

    def test_importo_numerico_cambiato_rilevato(self):
        old = {"importo_numerico": Decimal("1000.00")}
        new = {"importo_numerico": Decimal("2000.00")}
        changed = _compute_changed_fields(old, new)
        assert "importo_numerico" in changed

    def test_importo_numerico_identico_non_rilevato(self):
        d = Decimal("1500.00")
        old = {"importo_numerico": d}
        new = {"importo_numerico": d}
        changed = _compute_changed_fields(old, new)
        assert "importo_numerico" not in changed

    def test_da_none_a_valore_rilevato(self):
        old = {"codice_bando": None}
        new = {"codice_bando": "ABC-001"}
        changed = _compute_changed_fields(old, new)
        assert "codice_bando" in changed

    def test_da_valore_a_none_rilevato(self):
        old = {"importo": "€ 500.000"}
        new = {"importo": None}
        changed = _compute_changed_fields(old, new)
        assert "importo" in changed

    def test_piu_campi_cambiati_tutti_rilevati(self):
        old = {"titolo": "A", "stato_bando": "programmato", "importo": None}
        new = {"titolo": "B", "stato_bando": "aperto", "importo": "€ 1.000"}
        changed = _compute_changed_fields(old, new)
        assert "titolo" in changed
        assert "stato_bando" in changed
        assert "importo" in changed


# ---------------------------------------------------------------------------
# 7. Policy retry — _is_recoverable_error
# ---------------------------------------------------------------------------

from app.services.bando_discovery_service import BandoDiscoveryService
from app.scrapers.fonte_level2 import FonteLevel2Error


class TestPolicyRetry:
    def test_timeout_exception_recuperabile(self):
        import httpx
        exc = httpx.TimeoutException("timeout")
        assert BandoDiscoveryService._is_recoverable_error(exc) is True

    def test_fonte_level2_error_recuperabile(self):
        exc = FonteLevel2Error("timeout", recoverable=True)
        assert BandoDiscoveryService._is_recoverable_error(exc) is True

    def test_fonte_level2_error_non_recuperabile(self):
        exc = FonteLevel2Error("404 not found", recoverable=False)
        assert BandoDiscoveryService._is_recoverable_error(exc) is False

    def test_messaggio_timeout_recuperabile(self):
        exc = RuntimeError("connection timeout while reading")
        assert BandoDiscoveryService._is_recoverable_error(exc) is True

    def test_messaggio_service_unavailable_recuperabile(self):
        exc = RuntimeError("service unavailable")
        assert BandoDiscoveryService._is_recoverable_error(exc) is True

    def test_messaggio_rate_limit_recuperabile(self):
        exc = RuntimeError("rate limit exceeded")
        assert BandoDiscoveryService._is_recoverable_error(exc) is True

    def test_messaggio_connection_reset_recuperabile(self):
        exc = RuntimeError("connection reset by peer")
        assert BandoDiscoveryService._is_recoverable_error(exc) is True

    def test_errore_generico_non_recuperabile(self):
        exc = ValueError("campo obbligatorio mancante")
        assert BandoDiscoveryService._is_recoverable_error(exc) is False

    def test_errore_parsing_non_recuperabile(self):
        exc = KeyError("hash_bando")
        assert BandoDiscoveryService._is_recoverable_error(exc) is False

    def test_fonte_level2_recoverable_default_true(self):
        """FonteLevel2Error senza argomenti ha recoverable=True di default."""
        exc = FonteLevel2Error("errore generico")
        assert BandoDiscoveryService._is_recoverable_error(exc) is True


# ---------------------------------------------------------------------------
# 8. Validatore output AI — AiClassificationOutputValidator
# ---------------------------------------------------------------------------

from app.ai.output_validator import AiClassificationOutputValidator, AllowedValue


def _make_validator(**fields: list[tuple[int, str]]) -> AiClassificationOutputValidator:
    allowed = {
        field: [AllowedValue(id=i, label=label) for i, label in values]
        for field, values in fields.items()
    }
    return AiClassificationOutputValidator(allowed)


class TestValidatoreOutputAI:
    def test_id_valido_passa(self):
        v = _make_validator(tipologia_bando_id=[(1, "Bando nazionale"), (2, "Bando europeo")])
        result = v.validate({"tipologia_bando_id": 1})
        assert result == {"tipologia_bando_id": 1}

    def test_id_non_presente_scartato(self):
        v = _make_validator(tipologia_bando_id=[(1, "Bando nazionale")])
        result = v.validate({"tipologia_bando_id": 999})
        assert "tipologia_bando_id" not in result

    def test_label_stringa_valida_convertita_in_id(self):
        v = _make_validator(tipologia_bando_id=[(1, "Bando nazionale")])
        result = v.validate({"tipologia_bando_id": "Bando nazionale"})
        assert result.get("tipologia_bando_id") == 1

    def test_label_case_insensitive(self):
        v = _make_validator(tipologia_bando_id=[(1, "Bando Nazionale")])
        result = v.validate({"tipologia_bando_id": "bando nazionale"})
        assert result.get("tipologia_bando_id") == 1

    def test_id_numerico_come_stringa_valido(self):
        v = _make_validator(tipologia_bando_id=[(5, "Voucher")])
        result = v.validate({"tipologia_bando_id": "5"})
        assert result.get("tipologia_bando_id") == 5

    def test_campo_sconosciuto_ignorato(self):
        v = _make_validator(tipologia_bando_id=[(1, "Nazionale")])
        result = v.validate({"campo_inventato": "valore"})
        assert "campo_inventato" not in result

    def test_lista_valori_validi(self):
        v = _make_validator(regione_ids=[(1, "Toscana"), (2, "Veneto"), (3, "Lazio")])
        result = v.validate({"regione_ids": [1, 2]})
        assert result.get("regione_ids") == [1, 2]

    def test_lista_con_valori_misti_validi_e_non(self):
        v = _make_validator(regione_ids=[(1, "Toscana"), (2, "Veneto")])
        result = v.validate({"regione_ids": [1, 99, 2, 100]})
        assert result.get("regione_ids") == [1, 2]

    def test_lista_vuota_dopo_filtraggio_non_inclusa(self):
        v = _make_validator(regione_ids=[(1, "Toscana")])
        result = v.validate({"regione_ids": [999, 888]})
        assert "regione_ids" not in result

    def test_output_none_restituisce_dizionario_vuoto(self):
        v = _make_validator(tipologia_bando_id=[(1, "Nazionale")])
        result = v.validate(None)
        assert result == {}

    def test_output_vuoto_restituisce_dizionario_vuoto(self):
        v = _make_validator(tipologia_bando_id=[(1, "Nazionale")])
        result = v.validate({})
        assert result == {}

    def test_duplicati_in_lista_deduplicati(self):
        v = _make_validator(regione_ids=[(1, "Toscana")])
        result = v.validate({"regione_ids": [1, 1, 1]})
        assert result.get("regione_ids") == [1]

    def test_piu_campi_validati_insieme(self):
        v = _make_validator(
            tipologia_bando_id=[(1, "Nazionale")],
            regione_ids=[(10, "Toscana"), (11, "Veneto")],
        )
        result = v.validate({"tipologia_bando_id": 1, "regione_ids": [10, 999]})
        assert result.get("tipologia_bando_id") == 1
        assert result.get("regione_ids") == [10]
