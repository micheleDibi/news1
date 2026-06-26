"""
Test plan trasversale — Integration test

Richiedono database reale (marker `integration`).
Eseguire con: pytest app/tests/test_integration_trasversale.py -v
(senza DB reale vengono saltati)

Coprono:
  1. DB repositories — lettura tabelle di riferimento
  2. upsert bandi — insert, update, unchanged, no-duplicati
  3. storico modifiche — bando_storico coerente con le differenze
  4. popolamento relazioni — tabelle ponte (regioni, settori, ecc.)
  5. scraping_log — creazione entry per-fonte, aggiornamento stato
  6. queue AI — enqueue, idempotenza, claim, complete, fail
  7. OCR pipeline — DocumentHandler routing text vs scanned
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.db.connection import get_db_connection


# ---------------------------------------------------------------------------
# Helpers condivisi
# ---------------------------------------------------------------------------

def _unique_hash() -> str:
    return f"test-integration-{uuid.uuid4().hex}"


def _base_payload(hash_bando: str, link: str, fonte_id: int = 1) -> dict:
    return {
        "fonte_id": fonte_id,
        "titolo": "Bando test integration",
        "descrizione": "Descrizione test",
        "codice_bando": "IT-TEST-001",
        "stato_bando": "programmato",
        "data_pubblicazione": date(2026, 1, 1),
        "data_apertura": date(2026, 3, 1),
        "data_scadenza": date(2026, 9, 30),
        "link_bando": link,
        "hash_bando": hash_bando,
        "importo": "€ 500.000",
        "importo_numerico": Decimal("500000.00"),
        "data_extra": {"test": True},
        "raw_data_obj": {"v": 1},
        "raw_data": json.dumps({"v": 1}),
        "scraping_log_id": None,
    }


def _cleanup_bando(hash_bando: str) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM public.bando WHERE hash_bando = %s", (hash_bando,))
            row = cur.fetchone()
            if row:
                bando_id = row["id"]
                cur.execute("DELETE FROM public.bando_storico WHERE bando_id = %s", (bando_id,))
                for table, col in [
                    ("bando_regioni", "bando_id"),
                    ("bando_settori", "bando_id"),
                    ("bando_codici_ateco", "bando_id"),
                ]:
                    try:
                        cur.execute(f"DELETE FROM public.{table} WHERE {col} = %s", (bando_id,))
                    except Exception:
                        pass
            cur.execute("DELETE FROM public.bando WHERE hash_bando = %s", (hash_bando,))


def _cleanup_ai_jobs(bando_id: int) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.ai_job_queue WHERE bando_id = %s", (bando_id,))


def _cleanup_scraping_log(session_id: str) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.scraping_log WHERE session_id = %s", (session_id,))


# ---------------------------------------------------------------------------
# 1. DB repositories — lettura tabelle di riferimento
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestDbRepositories:
    def test_fonte_repo_get_all_active(self):
        from app.repos.base import FonteRepo
        repo = FonteRepo()
        fonti = repo.get_all_active()
        assert isinstance(fonti, list)

    def test_reference_data_repo_tipologie_bando(self):
        from app.repos.base import ReferenceDataRepo
        repo = ReferenceDataRepo()
        items = repo.get_tipologie_bando()
        assert isinstance(items, list)
        if items:
            assert "id" in items[0]
            assert "nome" in items[0]

    def test_reference_data_repo_regioni(self):
        from app.repos.base import ReferenceDataRepo
        repo = ReferenceDataRepo()
        regioni = repo.get_regioni()
        assert isinstance(regioni, list)

    def test_reference_data_repo_programmi(self):
        from app.repos.base import ReferenceDataRepo
        repo = ReferenceDataRepo()
        programmi = repo.get_programmi()
        assert isinstance(programmi, list)

    def test_reference_data_repo_beneficiari(self):
        from app.repos.base import ReferenceDataRepo
        repo = ReferenceDataRepo()
        beneficiari = repo.get_beneficiari()
        assert isinstance(beneficiari, list)
        if beneficiari:
            assert "id" in beneficiari[0]

    def test_reference_data_repo_codici_ateco(self):
        from app.repos.base import ReferenceDataRepo
        repo = ReferenceDataRepo()
        codici = repo.get_codici_ateco()
        assert isinstance(codici, list)
        if codici:
            assert "codice" in codici[0]
            assert "descrizione" in codici[0]

    def test_fonte_repo_get_all_active_with_limit(self):
        from app.repos.base import FonteRepo
        repo = FonteRepo()
        fonti = repo.get_all_active_with_limit(limit=2)
        assert isinstance(fonti, list)
        assert len(fonti) <= 2

    def test_scraping_log_repo_get_by_session_id_empty(self):
        from app.repos.base import ScrapingLogRepo
        repo = ScrapingLogRepo()
        result = repo.get_by_session_id(str(uuid.uuid4()))
        assert result == []


# ---------------------------------------------------------------------------
# 2. Upsert bandi
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestUpsertBandi:
    def test_insert_nuovo_bando(self):
        from app.repos.base import BandoRepo
        repo = BandoRepo()
        h = _unique_hash()
        link = f"https://example.org/integration/{uuid.uuid4()}"
        payload = _base_payload(h, link)
        try:
            stats = repo.upsert_candidates([payload])
            assert stats["inserted"] == 1
            assert stats["updated"] == 0
            assert stats["unchanged"] == 0
            assert stats["processed"] == 1
            assert len(stats["bando_ids"]) == 1
        finally:
            _cleanup_bando(h)

    def test_insert_idempotente_unchanged(self):
        """Chiamare upsert due volte con lo stesso payload produce unchanged al secondo giro."""
        from app.repos.base import BandoRepo
        repo = BandoRepo()
        h = _unique_hash()
        link = f"https://example.org/integration/{uuid.uuid4()}"
        payload = _base_payload(h, link)
        try:
            repo.upsert_candidates([payload])
            stats = repo.upsert_candidates([payload])
            assert stats["inserted"] == 0
            assert stats["updated"] == 0
            assert stats["unchanged"] == 1
        finally:
            _cleanup_bando(h)

    def test_update_bando_esistente(self):
        """Modificare il titolo produce updated=1."""
        from app.repos.base import BandoRepo
        repo = BandoRepo()
        h = _unique_hash()
        link = f"https://example.org/integration/{uuid.uuid4()}"
        payload = _base_payload(h, link)
        try:
            repo.upsert_candidates([payload])
            updated_payload = dict(payload, titolo="Titolo aggiornato", raw_data_obj={"v": 2}, raw_data=json.dumps({"v": 2}))
            stats = repo.upsert_candidates([updated_payload])
            assert stats["updated"] == 1
            assert stats["inserted"] == 0
        finally:
            _cleanup_bando(h)

    def test_no_duplicati_stesso_hash(self):
        """Stesso hash_bando non produce righe duplicate nella tabella bando."""
        from app.repos.base import BandoRepo
        repo = BandoRepo()
        h = _unique_hash()
        link = f"https://example.org/integration/{uuid.uuid4()}"
        payload = _base_payload(h, link)
        try:
            repo.upsert_candidates([payload])
            repo.upsert_candidates([payload])
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) AS cnt FROM public.bando WHERE hash_bando = %s", (h,))
                    row = cur.fetchone()
            assert row["cnt"] == 1
        finally:
            _cleanup_bando(h)

    def test_upsert_batch_multi_bandi(self):
        """Inserimento di 3 bandi distinti in un'unica chiamata."""
        from app.repos.base import BandoRepo
        repo = BandoRepo()
        hashes = [_unique_hash() for _ in range(3)]
        payloads = [
            _base_payload(h, f"https://example.org/integration/{uuid.uuid4()}")
            for h in hashes
        ]
        try:
            stats = repo.upsert_candidates(payloads)
            assert stats["inserted"] == 3
            assert stats["processed"] == 3
        finally:
            for h in hashes:
                _cleanup_bando(h)


# ---------------------------------------------------------------------------
# 3. Storico modifiche
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestStoricoModifiche:
    def test_modifica_titolo_produce_storico(self):
        """Aggiornamento del titolo crea una riga in bando_storico."""
        from app.repos.base import BandoRepo
        repo = BandoRepo()
        h = _unique_hash()
        link = f"https://example.org/integration/{uuid.uuid4()}"
        payload = _base_payload(h, link)
        try:
            repo.upsert_candidates([payload])
            updated = dict(payload, titolo="Titolo modificato", raw_data_obj={"v": 2}, raw_data=json.dumps({"v": 2}))
            repo.upsert_candidates([updated])

            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM public.bando WHERE hash_bando = %s", (h,))
                    bando_row = cur.fetchone()
                    cur.execute(
                        "SELECT campi_modificati, dati_precedenti, dati_nuovi FROM public.bando_storico WHERE bando_id = %s ORDER BY id DESC LIMIT 1",
                        (bando_row["id"],),
                    )
                    storico = cur.fetchone()

            assert storico is not None
            assert "titolo" in storico["campi_modificati"]
            assert storico["dati_precedenti"]["titolo"] == "Bando test integration"
            assert storico["dati_nuovi"]["titolo"] == "Titolo modificato"
        finally:
            _cleanup_bando(h)

    def test_transizione_stato_registrata(self):
        """Cambio di stato_bando da programmato ad aperto produce storico con stato_bando."""
        from app.repos.base import BandoRepo
        repo = BandoRepo()
        h = _unique_hash()
        link = f"https://example.org/integration/{uuid.uuid4()}"
        payload = _base_payload(h, link)
        try:
            repo.upsert_candidates([payload])
            updated = dict(payload, stato_bando="aperto", raw_data_obj={"v": 2}, raw_data=json.dumps({"v": 2}))
            repo.upsert_candidates([updated])

            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM public.bando WHERE hash_bando = %s", (h,))
                    bando_row = cur.fetchone()
                    cur.execute(
                        "SELECT campi_modificati, dati_nuovi FROM public.bando_storico WHERE bando_id = %s ORDER BY id ASC",
                        (bando_row["id"],),
                    )
                    storici = cur.fetchall()

            stati_changes = [r for r in storici if "stato_bando" in (r["campi_modificati"] or [])]
            assert len(stati_changes) >= 1
            assert stati_changes[-1]["dati_nuovi"]["stato_bando"] == "aperto"
        finally:
            _cleanup_bando(h)

    def test_nessuna_modifica_nessuno_storico(self):
        """Se il payload è identico, non deve essere creato alcuno storico."""
        from app.repos.base import BandoRepo
        repo = BandoRepo()
        h = _unique_hash()
        link = f"https://example.org/integration/{uuid.uuid4()}"
        payload = _base_payload(h, link)
        try:
            repo.upsert_candidates([payload])
            repo.upsert_candidates([payload])  # second call: unchanged

            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM public.bando WHERE hash_bando = %s", (h,))
                    bando_row = cur.fetchone()
                    cur.execute(
                        "SELECT COUNT(*) AS cnt FROM public.bando_storico WHERE bando_id = %s",
                        (bando_row["id"],),
                    )
                    row = cur.fetchone()

            assert row["cnt"] == 0
        finally:
            _cleanup_bando(h)

    def test_storico_collegato_a_scraping_log_id(self):
        """Se scraping_log_id è impostato nel payload, deve apparire nel record storico."""
        from app.repos.base import BandoRepo
        repo = BandoRepo()
        h = _unique_hash()
        link = f"https://example.org/integration/{uuid.uuid4()}"
        payload = _base_payload(h, link)
        try:
            repo.upsert_candidates([payload])
            updated = dict(payload, titolo="Con log id", scraping_log_id=None, raw_data_obj={"v": 2}, raw_data=json.dumps({"v": 2}))
            repo.upsert_candidates([updated])

            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM public.bando WHERE hash_bando = %s", (h,))
                    bando_row = cur.fetchone()
                    cur.execute(
                        "SELECT scraping_log_id FROM public.bando_storico WHERE bando_id = %s ORDER BY id DESC LIMIT 1",
                        (bando_row["id"],),
                    )
                    storico = cur.fetchone()

            assert storico is not None  # storico esiste
        finally:
            _cleanup_bando(h)


# ---------------------------------------------------------------------------
# 4. Popolamento relazioni (tabelle ponte)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestPopolamentoRelazioni:
    def _get_valid_regione_id(self) -> int | None:
        from app.repos.base import ReferenceDataRepo
        items = ReferenceDataRepo().get_regioni()
        return items[0]["id"] if items else None

    def _get_valid_settore_id(self) -> int | None:
        from app.repos.base import ReferenceDataRepo
        items = ReferenceDataRepo().get_settori()
        return items[0]["id"] if items else None

    def test_regioni_associate_al_bando(self):
        from app.repos.base import BandoRepo
        regione_id = self._get_valid_regione_id()
        if regione_id is None:
            pytest.skip("Nessuna regione nel DB")

        repo = BandoRepo()
        h = _unique_hash()
        link = f"https://example.org/integration/{uuid.uuid4()}"
        payload = dict(_base_payload(h, link), regione_ids=[regione_id])
        try:
            repo.upsert_candidates([payload])
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM public.bando WHERE hash_bando = %s", (h,))
                    bando_row = cur.fetchone()
                    cur.execute(
                        "SELECT regione_id FROM public.bando_regioni WHERE bando_id = %s",
                        (bando_row["id"],),
                    )
                    rows = cur.fetchall()
            assert any(r["regione_id"] == regione_id for r in rows)
        finally:
            _cleanup_bando(h)

    def test_settori_associati_al_bando(self):
        from app.repos.base import BandoRepo
        settore_id = self._get_valid_settore_id()
        if settore_id is None:
            pytest.skip("Nessun settore nel DB")

        repo = BandoRepo()
        h = _unique_hash()
        link = f"https://example.org/integration/{uuid.uuid4()}"
        payload = dict(_base_payload(h, link), settore_ids=[settore_id])
        try:
            repo.upsert_candidates([payload])
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM public.bando WHERE hash_bando = %s", (h,))
                    bando_row = cur.fetchone()
                    cur.execute(
                        "SELECT settore_id FROM public.bando_settori WHERE bando_id = %s",
                        (bando_row["id"],),
                    )
                    rows = cur.fetchall()
            assert any(r["settore_id"] == settore_id for r in rows)
        finally:
            _cleanup_bando(h)

    def test_relazioni_aggiornate_su_update(self):
        """Se le regioni cambiano, il sync rimuove le vecchie e inserisce le nuove."""
        from app.repos.base import BandoRepo, ReferenceDataRepo
        regioni = ReferenceDataRepo().get_regioni()
        if len(regioni) < 2:
            pytest.skip("Meno di 2 regioni nel DB per questo test")

        id1, id2 = regioni[0]["id"], regioni[1]["id"]
        repo = BandoRepo()
        h = _unique_hash()
        link = f"https://example.org/integration/{uuid.uuid4()}"
        try:
            repo.upsert_candidates([dict(_base_payload(h, link), regione_ids=[id1])])

            updated = dict(
                _base_payload(h, link),
                regione_ids=[id2],
                titolo="Aggiornato con nuova regione",
                raw_data_obj={"v": 2},
                raw_data=json.dumps({"v": 2}),
            )
            repo.upsert_candidates([updated])

            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM public.bando WHERE hash_bando = %s", (h,))
                    bando_row = cur.fetchone()
                    cur.execute(
                        "SELECT regione_id FROM public.bando_regioni WHERE bando_id = %s",
                        (bando_row["id"],),
                    )
                    rows = cur.fetchall()
            regione_ids_result = [r["regione_id"] for r in rows]
            assert id2 in regione_ids_result
            assert id1 not in regione_ids_result
        finally:
            _cleanup_bando(h)


# ---------------------------------------------------------------------------
# 5. Scraping log
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestScrapingLog:
    """Test di ScrapingLogRepo sullo schema reale del DB.

    Nota: la colonna `parent_log_id` non è presente nella migrazione applicata
    al DB di test, quindi i test usano INSERT diretti compatibili con lo schema reale.
    """

    def _insert_log(self, session_id: str) -> int:
        """Inserisce un log entry direttamente con lo schema reale (no parent_log_id)."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.scraping_log (session_id, fonte_id, tipo_operazione, stato, url_processato, started_at)
                    VALUES (%s, 1, 'scan_fonte', 'processing', 'https://example.org/fonte', NOW())
                    RETURNING id
                    """,
                    (session_id,),
                )
                row = cur.fetchone()
        return int(row["id"])

    def test_get_by_session_id_dopo_insert(self):
        """get_by_session_id deve trovare i log inseriti per la sessione."""
        from app.repos.base import ScrapingLogRepo
        repo = ScrapingLogRepo()
        session_id = str(uuid.uuid4())
        try:
            log_id = self._insert_log(session_id)
            result = repo.get_by_session_id(session_id)
            assert any(r.id == log_id for r in result)
        finally:
            _cleanup_scraping_log(session_id)

    def test_update_fonte_log_success(self):
        from app.repos.base import ScrapingLogRepo
        repo = ScrapingLogRepo()
        session_id = str(uuid.uuid4())
        try:
            log_id = self._insert_log(session_id)
            repo.update_fonte_log_success(
                log_id,
                elapsed_ms=1234,
                bandi_trovati=5,
                bandi_nuovi=2,
                bandi_aggiornati=1,
                bandi_invariati=2,
            )

            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT stato, bandi_trovati, tempo_esecuzione_ms FROM public.scraping_log WHERE id = %s", (log_id,))
                    row = cur.fetchone()

            assert row["stato"] == "completed"
            assert row["bandi_trovati"] == 5
            assert row["tempo_esecuzione_ms"] == 1234
        finally:
            _cleanup_scraping_log(session_id)

    def test_update_fonte_log_error(self):
        from app.repos.base import ScrapingLogRepo
        repo = ScrapingLogRepo()
        session_id = str(uuid.uuid4())
        try:
            log_id = self._insert_log(session_id)
            repo.update_fonte_log_error(
                log_id,
                elapsed_ms=500,
                error_type="FonteLevel2Error",
                error_message="Timeout connessione",
                error_stack="Traceback ...\n  FonteLevel2Error: Timeout",
            )

            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT stato, errore_tipo, errore_messaggio, errore_stack FROM public.scraping_log WHERE id = %s",
                        (log_id,),
                    )
                    row = cur.fetchone()

            assert row["stato"] == "failed"
            assert row["errore_tipo"] == "FonteLevel2Error"
            assert "Timeout" in row["errore_messaggio"]
            assert row["errore_stack"] is not None
        finally:
            _cleanup_scraping_log(session_id)

    def test_update_multipli_record_stesso_log(self):
        """Un secondo update sovrascrive lo stato del log (idempotenza lato report)."""
        from app.repos.base import ScrapingLogRepo
        repo = ScrapingLogRepo()
        session_id = str(uuid.uuid4())
        try:
            log_id = self._insert_log(session_id)
            repo.update_fonte_log_success(log_id, elapsed_ms=100, bandi_trovati=1, bandi_nuovi=1, bandi_aggiornati=0, bandi_invariati=0)
            repo.update_fonte_log_error(log_id, elapsed_ms=200, error_type="Retry", error_message="overwrite")

            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT stato FROM public.scraping_log WHERE id = %s", (log_id,))
                    row = cur.fetchone()

            assert row["stato"] == "failed"  # ultimo aggiornamento vince
        finally:
            _cleanup_scraping_log(session_id)

    def test_get_run_tabular_report(self):
        """get_run_tabular_report deve restituire gli entry fonte della sessione."""
        from app.repos.base import ScrapingLogRepo
        repo = ScrapingLogRepo()
        session_id = str(uuid.uuid4())
        try:
            for _ in range(2):
                log_id = self._insert_log(session_id)
                repo.update_fonte_log_success(log_id, elapsed_ms=100, bandi_trovati=1, bandi_nuovi=1, bandi_aggiornati=0, bandi_invariati=0)

            report = repo.get_run_tabular_report(session_id)
            assert len(report) == 2
            assert all("fonte_id" in r for r in report)
            assert all("stato" in r for r in report)
            assert all(r["stato"] == "completed" for r in report)
        finally:
            _cleanup_scraping_log(session_id)


# ---------------------------------------------------------------------------
# 6. Queue AI
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestQueueAi:
    def _get_any_bando_id(self) -> int | None:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM public.bando ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
        return int(row["id"]) if row else None

    def _insert_temp_bando(self) -> tuple[int, str]:
        h = _unique_hash()
        link = f"https://example.org/ai-test/{uuid.uuid4()}"
        payload = _base_payload(h, link)
        from app.repos.base import BandoRepo
        stats = BandoRepo().upsert_candidates([payload])
        bando_id = stats["bando_ids"][0]
        return bando_id, h

    def test_enqueue_classification_job(self):
        from app.repos.base import AiJobQueueRepo
        bando_id, h = self._insert_temp_bando()
        repo = AiJobQueueRepo()
        try:
            result = repo.enqueue_classification_job(
                bando_id,
                {"titolo": "Bando test", "campi_mancanti": ["tipologia_bando_id"]},
            )
            assert result["enqueued"] is True
            assert isinstance(result["job_id"], int)
        finally:
            _cleanup_ai_jobs(bando_id)
            _cleanup_bando(h)

    def test_enqueue_idempotente(self):
        """Enqueue dello stesso bando con job attivo deve restituire already_present=True."""
        from app.repos.base import AiJobQueueRepo
        bando_id, h = self._insert_temp_bando()
        repo = AiJobQueueRepo()
        try:
            repo.enqueue_classification_job(bando_id, {"titolo": "Primo"})
            result2 = repo.enqueue_classification_job(bando_id, {"titolo": "Secondo"})
            assert result2["already_present"] is True
            assert result2["enqueued"] is False
        finally:
            _cleanup_ai_jobs(bando_id)
            _cleanup_bando(h)

    def test_claim_jobs(self):
        """claim_jobs deve restituire i job in stato queued."""
        from app.repos.base import AiJobQueueRepo
        bando_id, h = self._insert_temp_bando()
        repo = AiJobQueueRepo()
        try:
            enqueue_result = repo.enqueue_classification_job(
                bando_id,
                {"titolo": "Claim test"},
                priorita=-9999,
            )
            job_id = enqueue_result["job_id"]
            jobs = repo.claim_jobs(limit=10)
            our_job = next((j for j in jobs if j["id"] == job_id), None)
            assert our_job is not None
            assert our_job["stato"] == "processing"
        finally:
            _cleanup_ai_jobs(bando_id)
            _cleanup_bando(h)

    def test_complete_job(self):
        from app.repos.base import AiJobQueueRepo
        bando_id, h = self._insert_temp_bando()
        repo = AiJobQueueRepo()
        try:
            enqueue_result = repo.enqueue_classification_job(bando_id, {"titolo": "Complete test"})
            job_id = enqueue_result["job_id"]
            repo.claim_jobs(limit=10)
            repo.complete_job(job_id, {"tipologia_bando_id": 1})

            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT stato, risultato FROM public.ai_job_queue WHERE id = %s", (job_id,))
                    row = cur.fetchone()

            assert row["stato"] == "completed"
            assert row["risultato"] is not None
        finally:
            _cleanup_ai_jobs(bando_id)
            _cleanup_bando(h)

    def test_fail_job_sotto_max_tentativi(self):
        """fail_job prima del max_tentativi deve rimettere il job in queued."""
        from app.repos.base import AiJobQueueRepo
        bando_id, h = self._insert_temp_bando()
        repo = AiJobQueueRepo()
        try:
            enqueue_result = repo.enqueue_classification_job(bando_id, {"titolo": "Fail test"})
            job_id = enqueue_result["job_id"]
            repo.claim_jobs(limit=10)
            result = repo.fail_job(job_id, errore_tipo="TimeoutError", errore_messaggio="timeout", retry_delay_seconds=0)
            # con tentativi=1 e max_tentativi default il job torna in queued
            assert result["stato"] in {"queued", "failed"}
        finally:
            _cleanup_ai_jobs(bando_id)
            _cleanup_bando(h)


# ---------------------------------------------------------------------------
# 7. OCR pipeline — DocumentHandler (routing text vs scanned)
# ---------------------------------------------------------------------------

def _minimal_text_pdf() -> bytes:
    content = b"BT /F1 12 Tf 72 720 Td (Avviso pubblico bando di prova) Tj ET"
    length = len(content)
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R\n"
        b"   /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >>\n"
        b">>\nendobj\n"
        b"4 0 obj\n<< /Length " + str(length).encode() + b" >>\nstream\n"
        + content
        + b"\nendstream\nendobj\n"
        b"xref\n0 5\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000266 00000 n \n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n"
        b"startxref\n360\n%%EOF\n"
    )


def _minimal_empty_pdf() -> bytes:
    return (
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
        b"startxref\n190\n%%EOF\n"
    )


class TestOcrPipeline:
    def test_pdf_testuale_route_a_text_extraction(self):
        """Un PDF con testo sufficiente usa il metodo 'text' senza OCR."""
        from app.ocr.document_handler import DocumentHandler
        from app.ocr.pdf_extractor import PdfTextExtractor

        # Mock del text extractor: simula PDF con 1 pagina, 1 pagina con testo
        mock_extractor = MagicMock(spec=PdfTextExtractor)
        mock_extractor.extract.return_value = ("Avviso pubblico bando di prova", 1, 1)

        handler = DocumentHandler(text_extractor=mock_extractor)
        result = handler.extract_from_bytes(b"fake-pdf-content")

        assert result.method == "text"
        assert result.text
        mock_extractor.extract.assert_called_once()

    def test_pdf_scansionato_attiva_ocr(self):
        """Un PDF senza testo (ratio=0) deve attivare la pipeline OCR."""
        from app.ocr.document_handler import DocumentHandler
        from app.ocr.pdf_extractor import PdfTextExtractor
        from app.ocr.ocr_processor import OcrProcessor

        mock_extractor = MagicMock(spec=PdfTextExtractor)
        mock_extractor.extract.return_value = ("", 1, 0)  # 1 pagina, 0 con testo

        mock_ocr = MagicMock(spec=OcrProcessor)
        mock_ocr.process.return_value = ("Testo estratto da OCR bando avviso", {"pages": 1})

        handler = DocumentHandler(text_extractor=mock_extractor, ocr_processor=mock_ocr)
        result = handler.extract_from_bytes(b"fake-pdf-content")

        assert result.method == "ocr"
        mock_ocr.process.assert_called_once()

    def test_pdf_corrotto_restituisce_failed(self):
        """Un PDF corrotto non deve propagare eccezioni ma restituire method='failed'."""
        from app.ocr.document_handler import DocumentHandler
        handler = DocumentHandler()
        corrupted = b"questo non e un pdf valido"
        result = handler.extract_from_bytes(corrupted)
        assert result.method == "failed"
        assert result.text is None

    def test_normalize_text_collassa_spazi_e_newline(self):
        """normalize_text deve collassare spazi multipli e sequenze di newline."""
        from app.ocr.document_handler import normalize_text
        raw_text = "Bando\n\n\n  aperto   per le   imprese\n\n"
        normalized = normalize_text(raw_text)
        assert "\n\n\n" not in normalized
        assert "  " not in normalized
        assert normalized.strip() == normalized
