"""
Test Milestone 2 — Schema, vincoli e migrazioni.

Richiede DB raggiungibile e migrazione applicata.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.db.connection import get_db_connection, get_raw_connection


@pytest.mark.integration
def test_migration_objects_exist():
    required_tables = [
        "bando_beneficiari",
        "scraping_errori_definitivi",
        "ai_job_queue",
        "ocr_job_queue",
    ]

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            for table_name in required_tables:
                cur.execute(
                    """
                    SELECT EXISTS(
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema='public' AND table_name=%s
                    ) AS ok
                    """,
                    (table_name,),
                )
                assert cur.fetchone()["ok"], f"Tabella mancante: {table_name}"


@pytest.mark.integration
def test_fk_constraints_exist():
    required_fks = [
        ("bando_beneficiari", "bando_beneficiari_bando_id_fkey"),
        ("bando_beneficiari", "bando_beneficiari_beneficiario_id_fkey"),
        ("scraping_errori_definitivi", "scraping_errori_definitivi_scraping_log_id_fkey"),
        ("scraping_errori_definitivi", "scraping_errori_definitivi_fonte_id_fkey"),
        ("scraping_errori_definitivi", "scraping_errori_definitivi_bando_id_fkey"),
        ("ai_job_queue", "ai_job_queue_bando_id_fkey"),
        ("ocr_job_queue", "ocr_job_queue_bando_id_fkey"),
        ("ocr_job_queue", "ocr_job_queue_fonte_id_fkey"),
    ]

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            for table_name, constraint_name in required_fks:
                cur.execute(
                    """
                    SELECT EXISTS(
                        SELECT 1
                        FROM information_schema.table_constraints
                        WHERE table_schema='public'
                          AND table_name=%s
                          AND constraint_name=%s
                          AND constraint_type='FOREIGN KEY'
                    ) AS ok
                    """,
                    (table_name, constraint_name),
                )
                assert cur.fetchone()["ok"], f"FK mancante: {table_name}.{constraint_name}"


@pytest.mark.integration
def test_indexes_exist():
    required_indexes = [
        "idx_bando_fonte_id",
        "idx_bando_hash_bando",
        "idx_bando_stato_bando",
        "idx_bando_data_scadenza",
        "idx_bando_ultimo_scraping_at",
        "idx_fonte_stato_processing",
        "idx_fonte_next_retry_at",
        "idx_fonte_categoria_programma_id",
        "idx_fonte_tipologia_programma_id",
        "idx_scraping_errori_definitivi_entity_type",
        "idx_ai_job_queue_stato",
        "idx_ocr_job_queue_stato",
    ]

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            for index_name in required_indexes:
                cur.execute(
                    """
                    SELECT EXISTS(
                        SELECT 1
                        FROM pg_indexes
                        WHERE schemaname='public' AND indexname=%s
                    ) AS ok
                    """,
                    (index_name,),
                )
                assert cur.fetchone()["ok"], f"Indice mancante: {index_name}"


@pytest.mark.integration
def test_insert_and_update_new_schema_rows():
    conn = get_raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM public.bando ORDER BY id LIMIT 1")
            bando_row = cur.fetchone()
            bando_id = bando_row["id"] if bando_row else None

            cur.execute("SELECT id FROM public.fonte ORDER BY id LIMIT 1")
            fonte_row = cur.fetchone()
            fonte_id = fonte_row["id"] if fonte_row else None

            if bando_id is not None:
                cur.execute(
                    """
                    INSERT INTO public.ai_job_queue (bando_id, payload)
                    VALUES (%s, %s::jsonb)
                    RETURNING id, stato
                    """,
                    (bando_id, "{}"),
                )
                ai_job = cur.fetchone()
                assert ai_job["stato"] == "queued"

                cur.execute(
                    """
                    UPDATE public.ai_job_queue
                    SET stato = 'processing'
                    WHERE id = %s
                    RETURNING stato
                    """,
                    (ai_job["id"],),
                )
                updated = cur.fetchone()
                assert updated["stato"] == "processing"

            cur.execute(
                """
                INSERT INTO public.ocr_job_queue (bando_id, fonte_id, url_documento)
                VALUES (%s, %s, %s)
                RETURNING id, stato
                """,
                (bando_id, fonte_id, "https://example.com/test.pdf"),
            )
            ocr_job = cur.fetchone()
            assert ocr_job["stato"] == "queued"

            cur.execute(
                """
                UPDATE public.ocr_job_queue
                SET stato = 'processing'
                WHERE id = %s
                RETURNING stato
                """,
                (ocr_job["id"],),
            )
            ocr_updated = cur.fetchone()
            assert ocr_updated["stato"] == "processing"

            cur.execute(
                """
                INSERT INTO public.scraping_errori_definitivi (
                    fonte_id,
                    bando_id,
                    entity_type,
                    errore_tipo,
                    errore_messaggio
                ) VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (fonte_id, bando_id, "bando", "test_error", "test migration milestone2"),
            )
            assert cur.fetchone()["id"] is not None

        # rollback esplicito per non sporcare i dati reali
        conn.rollback()
    finally:
        conn.close()


@pytest.mark.integration
def test_migration_sql_is_repeatable_script_exists():
    project_root = Path(__file__).resolve().parents[2]
    sql_path = project_root / "db" / "supabase_migration_bandi_opencoesione.sql"
    assert sql_path.exists(), "Script migrazione non trovato"

    sql_text = sql_path.read_text(encoding="utf-8")
    assert "IF NOT EXISTS" in sql_text, "La migrazione dovrebbe essere idempotente"
