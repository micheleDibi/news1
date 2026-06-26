"""
Repository base per l'accesso alle tabelle esistenti.
Regola: nessun INSERT nelle tabelle di riferimento (categoria_programma, fonte, beneficiari).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json
import re
from typing import Any, Optional

import psycopg2

from app.config.settings import settings
from app.db.connection import get_db_connection
from app.models.tables import CategoriaProgramma, Fonte, Bando, ScrapingLog


class CategoriaProgrammaRepo:
    """Lettura tabella `categoria_programma` (READ-ONLY)."""

    def get_all(self) -> list[CategoriaProgramma]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM public.categoria_programma ORDER BY id")
                rows = cur.fetchall()
        return [CategoriaProgramma(**dict(r)) for r in rows]

    def get_by_id(self, categoria_programma_id: int) -> Optional[CategoriaProgramma]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM public.categoria_programma WHERE id = %s", (categoria_programma_id,))
                row = cur.fetchone()
        return CategoriaProgramma(**dict(row)) if row else None

    def get_name_to_id_map(self) -> dict[str, int]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, nome FROM public.categoria_programma")
                rows = cur.fetchall()
        return {str(r["nome"]): int(r["id"]) for r in rows if r.get("nome")}


class TipologiaProgrammaRepo:
    """Lettura tabella `tipologia_programma` (READ-ONLY)."""

    def get_name_to_id_map(self) -> dict[str, int]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, nome FROM public.tipologia_programma")
                rows = cur.fetchall()
        return {str(r["nome"]): int(r["id"]) for r in rows if r.get("nome")}


class ReferenceDataRepo:
    """Lettura centralizzata delle anagrafiche usate per classificazione controllata."""

    def get_tipologie_bando(self) -> list[dict[str, Any]]:
        return self._fetch_named_table("tipologie_bando")

    def get_modalita_erogazione(self) -> list[dict[str, Any]]:
        return self._fetch_named_table("modalita_erogazione")

    def get_programmi(self) -> list[dict[str, Any]]:
        return self._fetch_named_table("programmi")

    def get_regioni(self) -> list[dict[str, Any]]:
        return self._fetch_named_table("regioni")

    def get_settori(self) -> list[dict[str, Any]]:
        return self._fetch_named_table("settori")

    def get_beneficiari(self) -> list[dict[str, Any]]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, nome FROM public.beneficiari ORDER BY id")
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_codici_ateco(self) -> list[dict[str, Any]]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, codice, descrizione FROM public.codici_ateco ORDER BY id"
                )
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_categorie_programma(self) -> list[dict[str, Any]]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, nome FROM public.categoria_programma ORDER BY id")
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_tipologie_programma(self) -> list[dict[str, Any]]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, nome FROM public.tipologia_programma ORDER BY id")
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def bridge_table_exists(table_name: str) -> bool:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXISTS(
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = %s
                    ) AS ok
                    """,
                    (table_name,),
                )
                row = cur.fetchone()
        return bool(row and row["ok"])

    @staticmethod
    def _fetch_named_table(table_name: str) -> list[dict[str, Any]]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT id, nome, slug FROM public.{table_name} ORDER BY id")
                rows = cur.fetchall()
        return [dict(row) for row in rows]


class FonteRepo:
    """Lettura tabella `fonte` (READ-ONLY per i campi di riferimento)."""

    def get_all_active(self) -> list[Fonte]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM public.fonte WHERE attivo = TRUE ORDER BY id")
                rows = cur.fetchall()
        return [Fonte(**dict(r)) for r in rows]

    def get_all_active_with_limit(self, limit: int | None = None) -> list[Fonte]:
        query = """
            SELECT *
            FROM public.fonte
            WHERE attivo = TRUE
              AND stato_processing <> 'failed_final'
              AND (
                stato_processing = 'ready'
                OR (
                    stato_processing = 'pending'
                    AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                )
              )
            ORDER BY
                CASE WHEN stato_processing = 'pending' THEN 0 ELSE 1 END,
                next_retry_at ASC NULLS FIRST,
                id ASC
        """
        params: tuple[Any, ...] = ()
        if limit is not None and limit > 0:
            query += " LIMIT %s"
            params = (limit,)

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return [Fonte(**dict(r)) for r in rows]

    def get_by_id(self, fonte_id: int) -> Optional[Fonte]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM public.fonte WHERE id = %s", (fonte_id,))
                row = cur.fetchone()
        return Fonte(**dict(row)) if row else None

    def get_pending(self) -> list[Fonte]:
        """Fonti in stato pending pronte per il retry."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        SELECT * FROM public.fonte
                        WHERE stato_processing = 'pending'
                          AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                        ORDER BY next_retry_at ASC NULLS FIRST
                        """
                    )
                    rows = cur.fetchall()
                except psycopg2.Error:
                    # Colonne di retry non disponibili finché la migrazione non è applicata.
                    rows = []
        return [Fonte(**dict(r)) for r in rows]

    def mark_processing_started(self, fonte_id: int) -> None:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.fonte
                    SET stato_processing = 'processing'
                    WHERE id = %s
                    """,
                    (fonte_id,),
                )

    def mark_processing_success(self, fonte_id: int) -> None:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.fonte
                    SET stato_processing = 'ready',
                        retry_count = 0,
                        max_retry = %s,
                        next_retry_at = NULL,
                        last_error_type = NULL,
                        last_error_message = NULL,
                        last_error_at = NULL
                    WHERE id = %s
                    """,
                    (settings.scraper_retry_max, fonte_id),
                )

    def register_processing_error(
        self,
        fonte_id: int,
        *,
        error_type: str,
        error_message: str,
        recoverable: bool,
        retry_delay_seconds: int,
    ) -> dict[str, Any]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, link, retry_count, max_retry
                    FROM public.fonte
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (fonte_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return {
                        "found": False,
                        "stato_processing": "unknown",
                        "retry_count": 0,
                        "max_retry": settings.scraper_retry_max,
                    }

                retry_count = int(row.get("retry_count") or 0) + 1
                max_retry = int(row.get("max_retry") or settings.scraper_retry_max)
                if max_retry <= 0:
                    max_retry = settings.scraper_retry_max

                should_retry = recoverable and retry_count < max_retry
                next_state = "pending" if should_retry else "failed_final"

                cur.execute(
                    """
                    UPDATE public.fonte
                    SET stato_processing = %s,
                        retry_count = %s,
                        max_retry = %s,
                        next_retry_at = CASE
                            WHEN %s THEN NOW() + (%s || ' seconds')::interval
                            ELSE NULL
                        END,
                        last_error_type = %s,
                        last_error_message = %s,
                        last_error_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        next_state,
                        retry_count,
                        max_retry,
                        should_retry,
                        int(retry_delay_seconds),
                        error_type[:255],
                        error_message[:4000],
                        fonte_id,
                    ),
                )

        return {
            "found": True,
            "fonte_id": int(row["id"]),
            "entity_url": row.get("link"),
            "stato_processing": next_state,
            "retry_count": retry_count,
            "max_retry": max_retry,
            "recoverable": recoverable,
        }

    def sync_discovered_sources(self, discovered_sources: list[dict[str, Any]]) -> dict[str, int]:
        """Sincronizza le fonti scoperte dinamicamente.

        Regole:
        - update se la stessa `link` esiste gia'
        - insert se la `link` non esiste
        - non crea nuove righe nelle tabelle di riferimento
        """
        if not discovered_sources:
            return {
                "processed": 0,
                "inserted": 0,
                "updated": 0,
                "unchanged": 0,
                "duplicates_existing": 0,
                "unexpected_links": 0,
            }

        links = [str(item["link"]) for item in discovered_sources if item.get("link")]
        if not links:
            return {
                "processed": 0,
                "inserted": 0,
                "updated": 0,
                "unchanged": 0,
                "duplicates_existing": 0,
                "unexpected_links": len(discovered_sources),
            }

        inserted = 0
        updated = 0
        unchanged = 0
        duplicates_existing = 0
        unexpected_links = 0

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT link, COUNT(*) AS cnt
                    FROM public.fonte
                    WHERE link = ANY(%s)
                    GROUP BY link
                    HAVING COUNT(*) > 1
                    """,
                    (links,),
                )
                duplicate_rows = cur.fetchall()
                duplicates_existing = len(duplicate_rows)

                cur.execute(
                    """
                    SELECT id, link, categoria_programma_id, tipologia_programma_id,
                           tipo_link, formato_link, titolo, attivo
                    FROM public.fonte
                    WHERE link = ANY(%s)
                    ORDER BY id
                    """,
                    (links,),
                )
                existing_rows = cur.fetchall()

                existing_by_link: dict[str, dict[str, Any]] = {}
                for row in existing_rows:
                    link = str(row["link"])
                    if link not in existing_by_link:
                        existing_by_link[link] = dict(row)

                for item in discovered_sources:
                    link = item.get("link")
                    if not link:
                        unexpected_links += 1
                        continue

                    existing = existing_by_link.get(str(link))
                    if existing:
                        categoria_id = item.get("categoria_programma_id")
                        tipologia_id = item.get("tipologia_programma_id")
                        if categoria_id is None:
                            categoria_id = existing.get("categoria_programma_id")
                        if tipologia_id is None:
                            tipologia_id = existing.get("tipologia_programma_id")

                        changed = any(
                            [
                                existing.get("categoria_programma_id") != categoria_id,
                                existing.get("tipologia_programma_id") != tipologia_id,
                                existing.get("tipo_link") != item.get("tipo_link"),
                                existing.get("formato_link") != item.get("formato_link"),
                                existing.get("titolo") != item.get("titolo"),
                                existing.get("attivo") is not True,
                            ]
                        )
                        if changed:
                            cur.execute(
                                """
                                UPDATE public.fonte
                                SET categoria_programma_id = %s,
                                    tipologia_programma_id = %s,
                                    tipo_link = %s,
                                    formato_link = %s,
                                    titolo = %s,
                                    attivo = TRUE,
                                    note_aggiuntive = %s
                                WHERE id = %s
                                """,
                                (
                                    categoria_id,
                                    tipologia_id,
                                    item.get("tipo_link"),
                                    item.get("formato_link"),
                                    item.get("titolo"),
                                    item.get("note_aggiuntive"),
                                    existing["id"],
                                ),
                            )
                            updated += 1
                        else:
                            unchanged += 1
                    else:
                        if item.get("categoria_programma_id") is None or item.get("tipologia_programma_id") is None:
                            unexpected_links += 1
                            continue
                        cur.execute(
                            """
                            INSERT INTO public.fonte (
                                categoria_programma_id,
                                tipologia_programma_id,
                                tipo_link,
                                titolo,
                                link,
                                formato_link,
                                attivo,
                                note_aggiuntive
                            ) VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s)
                            """,
                            (
                                item.get("categoria_programma_id"),
                                item.get("tipologia_programma_id"),
                                item.get("tipo_link"),
                                item.get("titolo"),
                                item.get("link"),
                                item.get("formato_link"),
                                item.get("note_aggiuntive"),
                            ),
                        )
                        inserted += 1

        return {
            "processed": len(discovered_sources),
            "inserted": inserted,
            "updated": updated,
            "unchanged": unchanged,
            "duplicates_existing": duplicates_existing,
            "unexpected_links": unexpected_links,
        }


class BandoRepo:
    """Accesso alla tabella `bando`."""

    def get_by_id(self, bando_id: int) -> Optional[Bando]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM public.bando WHERE id = %s", (bando_id,))
                row = cur.fetchone()
        return Bando(**dict(row)) if row else None

    def get_pending(self) -> list[Bando]:
        """Bandi in stato pending pronti per il retry."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM public.bando
                    WHERE stato_processing = 'pending'
                      AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                    ORDER BY next_retry_at ASC NULLS FIRST
                    """
                )
                rows = cur.fetchall()
        return [Bando(**dict(r)) for r in rows]

    def register_processing_error_by_hash(
        self,
        hash_bando: str,
        *,
        error_type: str,
        error_message: str,
        recoverable: bool,
        retry_delay_seconds: int,
    ) -> dict[str, Any]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, fonte_id, link_bando, retry_count, max_retry
                    FROM public.bando
                    WHERE hash_bando = %s
                    FOR UPDATE
                    """,
                    (hash_bando,),
                )
                row = cur.fetchone()
                if row is None:
                    return {
                        "found": False,
                        "stato_processing": "unknown",
                        "retry_count": 0,
                        "max_retry": settings.scraper_retry_max,
                    }

                retry_count = int(row.get("retry_count") or 0) + 1
                max_retry = int(row.get("max_retry") or settings.scraper_retry_max)
                if max_retry <= 0:
                    max_retry = settings.scraper_retry_max

                should_retry = recoverable and retry_count < max_retry
                next_state = "pending" if should_retry else "failed_final"

                cur.execute(
                    """
                    UPDATE public.bando
                    SET stato_processing = %s,
                        retry_count = %s,
                        max_retry = %s,
                        next_retry_at = CASE
                            WHEN %s THEN NOW() + (%s || ' seconds')::interval
                            ELSE NULL
                        END,
                        last_error_type = %s,
                        last_error_message = %s,
                        last_error_at = NOW(),
                        ultimo_scraping_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        next_state,
                        retry_count,
                        max_retry,
                        should_retry,
                        int(retry_delay_seconds),
                        error_type[:255],
                        error_message[:4000],
                        int(row["id"]),
                    ),
                )

        return {
            "found": True,
            "bando_id": int(row["id"]),
            "fonte_id": int(row["fonte_id"]) if row.get("fonte_id") is not None else None,
            "entity_url": row.get("link_bando"),
            "stato_processing": next_state,
            "retry_count": retry_count,
            "max_retry": max_retry,
            "recoverable": recoverable,
        }

    def set_ai_processing_flags(
        self,
        bando_id: int,
        *,
        required: bool,
        status: str,
        attempted: bool = False,
    ) -> None:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.bando
                    SET ai_processing_required = %s,
                        ai_processing_status = %s,
                        ai_last_attempt_at = CASE WHEN %s THEN NOW() ELSE ai_last_attempt_at END
                    WHERE id = %s
                    """,
                    (required, status, attempted, bando_id),
                )

    def get_candidates_for_ai_enqueue(self, limit: int | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT id, fonte_id, titolo, descrizione, codice_bando, fondo, link_bando,
                   raw_data, data_extra, tipologia_bando_id, modalita_erogazione_id, programma_id,
                   is_bando_confermato,
                   ai_processing_required, ai_processing_status
            FROM public.bando
            WHERE stato_processing = 'ready'
                            AND stato_bando <> 'sospetto'
              AND (
                tipologia_bando_id IS NULL
                OR modalita_erogazione_id IS NULL
                OR programma_id IS NULL
                OR is_bando_confermato IS NULL
              )
              AND (
                ai_processing_status IN ('not_required', 'failed')
                OR ai_processing_required = TRUE
              )
            ORDER BY ultimo_scraping_at DESC NULLS LAST, id DESC
        """
        params: tuple[Any, ...] = ()
        if limit is not None and limit > 0:
            query += " LIMIT %s"
            params = (limit,)

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def apply_ai_classification(
        self,
        bando_id: int,
        validated_classification: dict[str, Any],
        *,
        ai_job_id: int | None = None,
    ) -> dict[str, Any]:
        if not validated_classification:
            self.set_ai_processing_flags(
                bando_id,
                required=False,
                status="completed",
                attempted=True,
            )
            return {"applied": False, "changed_fields": []}

        changed_fields: list[str] = []

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, tipologia_bando_id, modalita_erogazione_id, programma_id,
                           is_bando_confermato
                    FROM public.bando
                    WHERE id = %s
                    """,
                    (bando_id,),
                )
                existing = cur.fetchone()
                if existing is None:
                    return {"applied": False, "changed_fields": []}

                new_tipologia = validated_classification.get("tipologia_bando_id", existing.get("tipologia_bando_id"))
                new_modalita = validated_classification.get(
                    "modalita_erogazione_id",
                    existing.get("modalita_erogazione_id"),
                )
                new_programma = validated_classification.get("programma_id", existing.get("programma_id"))
                new_is_bando = validated_classification.get("is_bando_confermato", existing.get("is_bando_confermato"))

                if existing.get("tipologia_bando_id") != new_tipologia:
                    changed_fields.append("tipologia_bando_id")
                if existing.get("modalita_erogazione_id") != new_modalita:
                    changed_fields.append("modalita_erogazione_id")
                if existing.get("programma_id") != new_programma:
                    changed_fields.append("programma_id")
                if existing.get("is_bando_confermato") != new_is_bando:
                    changed_fields.append("is_bando_confermato")

                bridge_specs = [
                    ("codice_ateco_ids", "bando_codici_ateco", "codice_ateco_id"),
                    ("regione_ids", "bando_regioni", "regione_id"),
                    ("settore_ids", "bando_settori", "settore_id"),
                    ("beneficiario_ids", "bando_beneficiari", "beneficiario_id"),
                ]

                old_bridge_values: dict[str, list[int]] = {}
                new_bridge_values: dict[str, list[int]] = {}
                for payload_key, table_name, related_column in bridge_specs:
                    if payload_key not in validated_classification:
                        continue

                    old_ids = self._current_bridge_ids(cur, table_name, related_column, bando_id)
                    new_ids = sorted(
                        {
                            int(value)
                            for value in (validated_classification.get(payload_key) or [])
                            if value is not None
                        }
                    )

                    old_bridge_values[payload_key] = old_ids
                    new_bridge_values[payload_key] = new_ids

                    if old_ids != new_ids:
                        changed_fields.append(payload_key)
                    self._sync_bridge_table(cur, table_name, related_column, bando_id, new_ids)

                cur.execute(
                    """
                    UPDATE public.bando
                    SET tipologia_bando_id = %s,
                        modalita_erogazione_id = %s,
                        programma_id = %s,
                        is_bando_confermato = COALESCE(%s, is_bando_confermato),
                        ai_processing_required = FALSE,
                        ai_processing_status = 'completed',
                        ai_last_attempt_at = NOW()
                    WHERE id = %s
                    """,
                    (new_tipologia, new_modalita, new_programma, new_is_bando, bando_id),
                )

                if changed_fields:
                    old_json: dict[str, Any] = {
                        "tipologia_bando_id": existing.get("tipologia_bando_id"),
                        "modalita_erogazione_id": existing.get("modalita_erogazione_id"),
                        "programma_id": existing.get("programma_id"),
                        "is_bando_confermato": existing.get("is_bando_confermato"),
                    }
                    new_json: dict[str, Any] = {
                        "tipologia_bando_id": new_tipologia,
                        "modalita_erogazione_id": new_modalita,
                        "programma_id": new_programma,
                        "is_bando_confermato": new_is_bando,
                    }
                    for payload_key in old_bridge_values:
                        old_json[payload_key] = old_bridge_values[payload_key]
                        new_json[payload_key] = new_bridge_values.get(payload_key, [])

                    cur.execute(
                        """
                        INSERT INTO public.bando_storico (
                            bando_id,
                            dati_precedenti,
                            dati_nuovi,
                            campi_modificati,
                            scraping_log_id
                        ) VALUES (%s, %s::jsonb, %s::jsonb, %s, NULL)
                        """,
                        (
                            bando_id,
                            _safe_json_dumps(old_json),
                            _safe_json_dumps(new_json),
                            changed_fields,
                        ),
                    )

        return {
            "applied": len(changed_fields) > 0,
            "changed_fields": changed_fields,
            "ai_job_id": ai_job_id,
        }

    def upsert_candidates(self, candidates: list[dict[str, Any]]) -> dict[str, int]:
        if not candidates:
            return {"processed": 0, "inserted": 0, "updated": 0, "unchanged": 0, "bando_ids": []}

        inserted = 0
        updated = 0
        unchanged = 0
        bando_ids: list[int] = []

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for item in candidates:
                    hash_bando = str(item["hash_bando"])
                    cur.execute(
                        """
                        SELECT id, titolo, descrizione, codice_bando, stato_bando,
                               data_pubblicazione, data_apertura, data_scadenza,
                               link_bando, importo, importo_numerico, data_extra, raw_data,
                               tipologia_bando_id, modalita_erogazione_id, programma_id,
                               is_bando_confermato
                        FROM public.bando
                        WHERE hash_bando = %s
                        """,
                        (hash_bando,),
                    )
                    existing = cur.fetchone()

                    tipologia_bando_id = item.get("tipologia_bando_id")
                    modalita_erogazione_id = item.get("modalita_erogazione_id")
                    programma_id = item.get("programma_id")
                    if existing is not None:
                        if tipologia_bando_id is None:
                            tipologia_bando_id = existing.get("tipologia_bando_id")
                        if modalita_erogazione_id is None:
                            modalita_erogazione_id = existing.get("modalita_erogazione_id")
                        if programma_id is None:
                            programma_id = existing.get("programma_id")

                    raw_data_json = _safe_json_dumps(item.get("raw_data_obj") or {})

                    if existing is None:
                        cur.execute(
                            """
                            INSERT INTO public.bando (
                                fonte_id,
                                hash_bando,
                                titolo,
                                descrizione,
                                codice_bando,
                                stato_bando,
                                data_pubblicazione,
                                data_apertura,
                                data_scadenza,
                                link_bando,
                                importo,
                                importo_numerico,
                                tipologia_bando_id,
                                modalita_erogazione_id,
                                programma_id,
                                is_bando_confermato,
                                data_extra,
                                raw_data,
                                primo_scraping_at,
                                ultimo_scraping_at,
                                stato_processing,
                                retry_count,
                                max_retry
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                                NOW(), NOW(), 'ready', 0, %s
                            )
                            RETURNING id
                            """,
                            (
                                item["fonte_id"],
                                hash_bando,
                                item["titolo"],
                                item.get("descrizione"),
                                item.get("codice_bando"),
                                item.get("stato_bando", "programmato"),
                                item.get("data_pubblicazione"),
                                item.get("data_apertura"),
                                item.get("data_scadenza"),
                                item["link_bando"],
                                item.get("importo"),
                                item.get("importo_numerico"),
                                tipologia_bando_id,
                                modalita_erogazione_id,
                                programma_id,
                                item.get("is_bando_confermato"),
                                _safe_json_dumps(item.get("data_extra") or {}),
                                raw_data_json,
                                settings.scraper_retry_max,
                            ),
                        )
                        inserted_row = cur.fetchone()
                        bando_id = int(inserted_row["id"])
                        bando_ids.append(bando_id)
                        self._sync_candidate_relationships(cur, bando_id, item)
                        inserted += 1
                        continue

                    changed_fields: list[str] = []
                    compare_fields = {
                        "titolo": item.get("titolo"),
                        "descrizione": item.get("descrizione"),
                        "codice_bando": item.get("codice_bando"),
                        "stato_bando": item.get("stato_bando", "programmato"),
                        "data_pubblicazione": item.get("data_pubblicazione"),
                        "data_apertura": item.get("data_apertura"),
                        "data_scadenza": item.get("data_scadenza"),
                        "link_bando": item.get("link_bando"),
                        "importo": item.get("importo"),
                        "importo_numerico": item.get("importo_numerico"),
                        "tipologia_bando_id": tipologia_bando_id,
                        "modalita_erogazione_id": modalita_erogazione_id,
                        "programma_id": programma_id,
                        "is_bando_confermato": item.get("is_bando_confermato"),
                        "data_extra": item.get("data_extra") or {},
                        "raw_data": item.get("raw_data_obj") or {},
                    }

                    for field, new_val in compare_fields.items():
                        old_val = existing.get(field)
                        if field in {"data_pubblicazione", "data_apertura", "data_scadenza"}:
                            old_val = _date_to_iso(old_val)
                            new_val = _date_to_iso(new_val)
                        elif field == "importo_numerico":
                            old_val = _decimal_to_str(old_val)
                            new_val = _decimal_to_str(new_val)

                        if old_val != new_val:
                            changed_fields.append(field)

                    should_update = len(changed_fields) > 0

                    if should_update:
                        cur.execute(
                            """
                            UPDATE public.bando
                            SET titolo = %s,
                                descrizione = %s,
                                codice_bando = %s,
                                stato_bando = %s,
                                data_pubblicazione = %s,
                                data_apertura = %s,
                                data_scadenza = %s,
                                link_bando = %s,
                                importo = %s,
                                importo_numerico = %s,
                                tipologia_bando_id = %s,
                                modalita_erogazione_id = %s,
                                programma_id = %s,
                                is_bando_confermato = %s,
                                data_extra = %s::jsonb,
                                raw_data = %s::jsonb,
                                ultimo_scraping_at = NOW(),
                                stato_processing = 'ready',
                                retry_count = 0,
                                max_retry = %s,
                                next_retry_at = NULL,
                                last_error_type = NULL,
                                last_error_message = NULL,
                                last_error_at = NULL
                            WHERE id = %s
                            """,
                            (
                                item["titolo"],
                                item.get("descrizione"),
                                item.get("codice_bando"),
                                item.get("stato_bando", "programmato"),
                                item.get("data_pubblicazione"),
                                item.get("data_apertura"),
                                item.get("data_scadenza"),
                                item["link_bando"],
                                item.get("importo"),
                                item.get("importo_numerico"),
                                tipologia_bando_id,
                                modalita_erogazione_id,
                                programma_id,
                                item.get("is_bando_confermato"),
                                _safe_json_dumps(item.get("data_extra") or {}),
                                raw_data_json,
                                settings.scraper_retry_max,
                                existing["id"],
                            ),
                        )

                        old_json = {
                            k: _jsonable(existing.get(k))
                            for k in [
                                "titolo",
                                "descrizione",
                                "codice_bando",
                                "stato_bando",
                                "data_pubblicazione",
                                "data_apertura",
                                "data_scadenza",
                                "link_bando",
                                "importo",
                                "importo_numerico",
                                "tipologia_bando_id",
                                "modalita_erogazione_id",
                                "programma_id",
                                "is_bando_confermato",
                                "data_extra",
                                "raw_data",
                            ]
                        }
                        new_json = {
                            "titolo": _jsonable(item.get("titolo")),
                            "descrizione": _jsonable(item.get("descrizione")),
                            "codice_bando": _jsonable(item.get("codice_bando")),
                            "stato_bando": _jsonable(item.get("stato_bando", "programmato")),
                            "data_pubblicazione": _jsonable(item.get("data_pubblicazione")),
                            "data_apertura": _jsonable(item.get("data_apertura")),
                            "data_scadenza": _jsonable(item.get("data_scadenza")),
                            "link_bando": _jsonable(item.get("link_bando")),
                            "importo": _jsonable(item.get("importo")),
                            "importo_numerico": _jsonable(item.get("importo_numerico")),
                            "tipologia_bando_id": _jsonable(tipologia_bando_id),
                            "modalita_erogazione_id": _jsonable(modalita_erogazione_id),
                            "programma_id": _jsonable(programma_id),
                            "is_bando_confermato": _jsonable(item.get("is_bando_confermato")),
                            "data_extra": _jsonable(item.get("data_extra") or {}),
                            "raw_data": _jsonable(item.get("raw_data_obj") or {}),
                        }

                        cur.execute(
                            """
                            INSERT INTO public.bando_storico (
                                bando_id,
                                dati_precedenti,
                                dati_nuovi,
                                campi_modificati,
                                scraping_log_id
                            ) VALUES (%s, %s::jsonb, %s::jsonb, %s, %s)
                            """,
                            (
                                existing["id"],
                                _safe_json_dumps(old_json),
                                _safe_json_dumps(new_json),
                                changed_fields,
                                item.get("scraping_log_id"),
                            ),
                        )
                        updated += 1
                    else:
                        cur.execute(
                            """
                            UPDATE public.bando
                            SET ultimo_scraping_at = NOW()
                            WHERE id = %s
                            """,
                            (existing["id"],),
                        )
                        unchanged += 1

                    self._sync_candidate_relationships(cur, int(existing["id"]), item)
                    bando_ids.append(int(existing["id"]))

        return {
            "processed": len(candidates),
            "inserted": inserted,
            "updated": updated,
            "unchanged": unchanged,
            "bando_ids": bando_ids,
        }

    @staticmethod
    def _sync_candidate_relationships(cur: Any, bando_id: int, item: dict[str, Any]) -> None:
        bridge_specs = [
            ("codice_ateco_ids", "bando_codici_ateco", "codice_ateco_id"),
            ("regione_ids", "bando_regioni", "regione_id"),
            ("settore_ids", "bando_settori", "settore_id"),
            ("beneficiario_ids", "bando_beneficiari", "beneficiario_id"),
        ]
        for payload_key, table_name, related_column in bridge_specs:
            if payload_key not in item:
                continue
            related_ids = item.get(payload_key)
            if related_ids is None:
                continue
            BandoRepo._sync_bridge_table(cur, table_name, related_column, bando_id, related_ids)

    @staticmethod
    def _sync_bridge_table(
        cur: Any,
        table_name: str,
        related_column: str,
        bando_id: int,
        related_ids: list[int],
    ) -> None:
        normalized_ids = sorted({int(value) for value in related_ids if value is not None})

        cur.execute(
            f"SELECT {related_column} FROM public.{table_name} WHERE bando_id = %s",
            (bando_id,),
        )
        existing_ids = {int(row[related_column]) for row in cur.fetchall()}

        new_ids = set(normalized_ids)
        to_insert = sorted(new_ids - existing_ids)
        to_delete = sorted(existing_ids - new_ids)

        if to_delete:
            cur.execute(
                f"DELETE FROM public.{table_name} WHERE bando_id = %s AND {related_column} = ANY(%s)",
                (bando_id, to_delete),
            )

        for related_id in to_insert:
            cur.execute(
                f"INSERT INTO public.{table_name} (bando_id, {related_column}) VALUES (%s, %s)",
                (bando_id, related_id),
            )

    @staticmethod
    def _current_bridge_ids(cur: Any, table_name: str, related_column: str, bando_id: int) -> list[int]:
        cur.execute(
            f"SELECT {related_column} FROM public.{table_name} WHERE bando_id = %s ORDER BY {related_column}",
            (bando_id,),
        )
        return [int(row[related_column]) for row in cur.fetchall()]


class AiJobQueueRepo:
    """Gestione coda AI asincrona su tabella `ai_job_queue`."""

    def enqueue_classification_job(
        self,
        bando_id: int,
        payload: dict[str, Any],
        *,
        priorita: int = 100,
    ) -> dict[str, Any]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id
                    FROM public.ai_job_queue
                    WHERE bando_id = %s
                      AND tipo_job = 'classificazione'
                      AND stato IN ('queued', 'processing')
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (bando_id,),
                )
                existing = cur.fetchone()
                if existing is not None:
                    return {
                        "enqueued": False,
                        "job_id": int(existing["id"]),
                        "already_present": True,
                    }

                cur.execute(
                    """
                    INSERT INTO public.ai_job_queue (
                        bando_id,
                        tipo_job,
                        stato,
                        priorita,
                        payload
                    ) VALUES (%s, 'classificazione', 'queued', %s, %s::jsonb)
                    RETURNING id, job_uuid
                    """,
                    (bando_id, priorita, _safe_json_dumps(payload)),
                )
                row = cur.fetchone()

        return {
            "enqueued": True,
            "job_id": int(row["id"]),
            "job_uuid": str(row["job_uuid"]),
            "already_present": False,
        }

    def claim_jobs(self, *, limit: int = 10) -> list[dict[str, Any]]:
        limit = max(1, int(limit))
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH picked AS (
                        SELECT id
                        FROM public.ai_job_queue
                        WHERE stato = 'queued'
                                                    AND (disponibile_da IS NULL OR disponibile_da <= NOW())
                        ORDER BY priorita ASC, disponibile_da ASC, id ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT %s
                    )
                    UPDATE public.ai_job_queue q
                    SET stato = 'processing',
                        started_at = NOW(),
                        tentativi = tentativi + 1
                    WHERE q.id IN (SELECT id FROM picked)
                    RETURNING q.*
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_status_counts(self) -> dict[str, int]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT stato, COUNT(*) AS n
                    FROM public.ai_job_queue
                    GROUP BY stato
                    """
                )
                rows = cur.fetchall()
        return {str(row["stato"]): int(row["n"]) for row in rows}

    def get_queued_count(self) -> int:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM public.ai_job_queue WHERE stato = 'queued'")
                row = cur.fetchone()
        return int(row["n"] if row else 0)

    def complete_job(self, job_id: int, result_payload: dict[str, Any]) -> None:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.ai_job_queue
                    SET stato = 'completed',
                        risultato = %s::jsonb,
                        errore_tipo = NULL,
                        errore_messaggio = NULL,
                        completed_at = NOW()
                    WHERE id = %s
                    """,
                    (_safe_json_dumps(result_payload), job_id),
                )

    def fail_job(
        self,
        job_id: int,
        *,
        errore_tipo: str,
        errore_messaggio: str,
        retry_delay_seconds: int,
    ) -> dict[str, Any]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.ai_job_queue
                    SET stato = CASE WHEN tentativi >= max_tentativi THEN 'failed' ELSE 'queued' END,
                        errore_tipo = %s,
                        errore_messaggio = %s,
                        disponibile_da = CASE
                            WHEN tentativi >= max_tentativi THEN disponibile_da
                            ELSE NOW() + (%s || ' seconds')::interval
                        END,
                        completed_at = CASE WHEN tentativi >= max_tentativi THEN NOW() ELSE completed_at END
                    WHERE id = %s
                    RETURNING stato, tentativi, max_tentativi
                    """,
                    (errore_tipo, errore_messaggio[:4000], int(retry_delay_seconds), job_id),
                )
                row = cur.fetchone()
        return dict(row) if row else {"stato": "unknown", "tentativi": 0, "max_tentativi": 0}

    def log_discarded_classification(
        self,
        *,
        bando_id: int,
        ai_job_id: int,
        discarded_payload: dict[str, Any],
    ) -> None:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.scraping_errori_definitivi (
                        bando_id,
                        entity_type,
                        errore_tipo,
                        errore_messaggio,
                        contesto
                    ) VALUES (%s, 'ai_job', %s, %s, %s::jsonb)
                    """,
                    (
                        bando_id,
                        "ai_output_scartato",
                        "Output AI non applicato per valori fuori dizionario",
                        _safe_json_dumps(
                            {
                                "ai_job_id": ai_job_id,
                                "discarded": discarded_payload,
                            }
                        ),
                    ),
                )


class ScrapingErrorRepo:
    """Persistenza errori definitivi su `scraping_errori_definitivi`."""

    def insert_definitive_error(
        self,
        *,
        entity_type: str,
        errore_tipo: str,
        errore_messaggio: str,
        session_id: str | None = None,
        scraping_log_id: int | None = None,
        fonte_id: int | None = None,
        bando_id: int | None = None,
        entity_url: str | None = None,
        retry_count: int = 0,
        http_status_code: int | None = None,
        errore_stack: str | None = None,
        contesto: dict[str, Any] | None = None,
    ) -> None:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.scraping_errori_definitivi (
                        session_id,
                        scraping_log_id,
                        fonte_id,
                        bando_id,
                        entity_type,
                        entity_url,
                        errore_tipo,
                        errore_messaggio,
                        errore_stack,
                        http_status_code,
                        retry_count,
                        contesto
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        session_id,
                        scraping_log_id,
                        fonte_id,
                        bando_id,
                        entity_type,
                        entity_url,
                        errore_tipo[:255],
                        errore_messaggio[:4000],
                        (errore_stack or "")[:16000] or None,
                        http_status_code,
                        int(retry_count),
                        _safe_json_dumps(contesto or {}),
                    ),
                )


def _date_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _decimal_to_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


_INVALID_JSON_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def _sanitize_text_for_json(value: str) -> str:
    """Remove control chars that break PostgreSQL jsonb parsing."""
    cleaned = _INVALID_JSON_CONTROL_CHARS_RE.sub(" ", value)
    return cleaned.encode("utf-8", errors="replace").decode("utf-8")


def _sanitize_for_json(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_text_for_json(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_json(v) for v in value]
    return value


def _safe_json_dumps(value: Any) -> str:
    return json.dumps(_sanitize_for_json(value), ensure_ascii=True)


class ScrapingLogRepo:
    """Accesso alla tabella `scraping_log`."""

    def get_by_session_id(self, session_id: str) -> list[ScrapingLog]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM public.scraping_log WHERE session_id = %s ORDER BY started_at DESC",
                    (session_id,),
                )
                rows = cur.fetchall()
        return [ScrapingLog(**dict(r)) for r in rows]

    def create_fonte_log_entry(
        self,
        session_id: str,
        parent_log_id: int,
        fonte_id: int,
        fonte_url: str | None,
        started_at: datetime,
    ) -> int:
        """Crea un log entry per una singola fonte. Restituisce il nuovo id."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.scraping_log (
                        session_id,
                        fonte_id,
                        tipo_operazione,
                        stato,
                        url_processato,
                        started_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        session_id,
                        fonte_id,
                        "scan_fonte",
                        "processing",
                        fonte_url,
                        started_at,
                    ),
                )
                row = cur.fetchone()
        return int(row["id"])

    def update_fonte_log_success(
        self,
        log_id: int,
        elapsed_ms: int,
        bandi_trovati: int,
        bandi_nuovi: int,
        bandi_aggiornati: int,
        bandi_invariati: int,
        ai_calls_count: int = 0,
        ai_tokens_used: int = 0,
    ) -> None:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.scraping_log
                    SET stato = 'completed',
                        tempo_esecuzione_ms = %s,
                        bandi_trovati = %s,
                        bandi_nuovi = %s,
                        bandi_aggiornati = %s,
                        bandi_invariati = %s,
                        completed_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        elapsed_ms,
                        bandi_trovati,
                        bandi_nuovi,
                        bandi_aggiornati,
                        bandi_invariati,
                        log_id,
                    ),
                )

    def update_fonte_log_error(
        self,
        log_id: int,
        elapsed_ms: int,
        error_type: str,
        error_message: str,
        error_stack: str | None = None,
    ) -> None:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.scraping_log
                    SET stato = 'failed',
                        tempo_esecuzione_ms = %s,
                        errore_tipo = %s,
                        errore_messaggio = %s,
                        errore_stack = %s,
                        completed_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        elapsed_ms,
                        error_type[:255],
                        error_message[:4000],
                        (error_stack or "")[:16000] or None,
                        log_id,
                    ),
                )

    def get_run_tabular_report(self, session_id: str) -> list[dict[str, Any]]:
        """Restituisce il riepilogo per-fonte di una sessione come lista di dict."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        sl.id,
                        sl.fonte_id,
                        f.titolo                AS fonte_titolo,
                        f.link                  AS fonte_link,
                        sl.tipo_operazione,
                        sl.stato,
                        sl.started_at,
                        sl.completed_at,
                        sl.tempo_esecuzione_ms,
                        sl.bandi_trovati,
                        sl.bandi_nuovi,
                        sl.bandi_aggiornati,
                        sl.bandi_invariati,
                        sl.errore_tipo,
                        sl.errore_messaggio
                    FROM public.scraping_log sl
                    LEFT JOIN public.fonte f ON sl.fonte_id = f.id
                    WHERE sl.session_id = %s
                      AND sl.fonte_id IS NOT NULL
                    ORDER BY sl.started_at ASC
                    """,
                    (session_id,),
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]


class HealthRepo:
    """Raccolta di query diagnostiche per gli indicatori di salute dello scraper."""

    _SUSPECT_DENY_HOST = (
        "COALESCE(link_bando, '') ~* "
        "'(facebook\\.com|instagram\\.com|linkedin\\.com|twitter\\.com|x\\.com|youtube\\.com|t\\.me|wa\\.me)'"
    )
    _SUSPECT_DENY_PATH = (
        "COALESCE(link_bando, '') ~* "
        "'(/privacy|/cookie|/contatti|/login|/logout|/rss|/feed|/tag/|/category/|/author/)'"
    )
    _SUSPECT_DENY_KEYWORD = (
        "CONCAT_WS(' ', titolo, descrizione, link_bando) ~* "
        "'(privacy|cookie|note legali|contatti|facebook|instagram|linkedin|twitter|youtube|whatsapp|telegram|feed|rss|wp-content|wp-json|wordpress\\.org|login|logout|amministrazione trasparente|mappa del sito|newsletter|lavora con noi)'"
    )
    _SUSPECT_BANDO_PREDICATE = (
        f"({_SUSPECT_DENY_HOST} OR {_SUSPECT_DENY_PATH} OR {_SUSPECT_DENY_KEYWORD})"
    )

    # ------------------------------------------------------------------ #
    # Sezione 1 — Ultimo run                                               #
    # ------------------------------------------------------------------ #

    def get_last_run(self) -> dict[str, Any]:
        """Restituisce i dati dell'ultimo run scan_fonti_livello2."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        stato,
                        started_at,
                        completed_at,
                        tempo_esecuzione_ms,
                        bandi_trovati,
                        bandi_nuovi,
                        bandi_aggiornati,
                        bandi_invariati,
                        errore_tipo,
                        response_summary
                    FROM public.scraping_log
                    WHERE tipo_operazione = 'scan_fonti_livello2'
                    ORDER BY started_at DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
        return dict(row) if row else {}

    # ------------------------------------------------------------------ #
    # Sezione 2 — Copertura fonti                                          #
    # ------------------------------------------------------------------ #

    def get_fonti_stats(self) -> dict[str, Any]:
        """Contatori per stato_processing di tutte le fonti attive."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT stato_processing, COUNT(*) AS n
                    FROM public.fonte
                    WHERE attivo = TRUE
                    GROUP BY stato_processing
                    ORDER BY n DESC
                    """
                )
                rows = cur.fetchall()

                cur.execute(
                    """
                    SELECT COUNT(*) AS stuck
                    FROM public.fonte
                    WHERE stato_processing = 'processing'
                      AND last_error_at < NOW() - INTERVAL '2 hours'
                    """
                )
                stuck_row = cur.fetchone()

        by_stato = {str(r["stato_processing"]): int(r["n"]) for r in rows}
        return {
            "by_stato": by_stato,
            "totale_attive": sum(by_stato.values()),
            "failed_final": by_stato.get("failed_final", 0),
            "pending": by_stato.get("pending", 0),
            "processing_stuck": int(stuck_row["stuck"]) if stuck_row else 0,
        }

    # ------------------------------------------------------------------ #
    # Sezione 3 — Qualità bandi                                            #
    # ------------------------------------------------------------------ #

    def get_bandi_quality(self) -> dict[str, Any]:
        """Contatori di completezza e pertinenza sulla tabella bando."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        COUNT(*) AS totale,
                        COUNT(*) FILTER (
                            WHERE descrizione IS NULL OR LENGTH(descrizione) < 30
                        ) AS senza_descrizione,
                        COUNT(*) FILTER (WHERE data_scadenza IS NULL) AS senza_scadenza,
                        COUNT(*) FILTER (WHERE importo_numerico IS NULL) AS senza_importo,
                        COUNT(*) FILTER (
                            WHERE tipologia_bando_id IS NULL AND programma_id IS NULL
                        ) AS senza_classificazione,
                        COUNT(*) FILTER (WHERE stato_bando = 'programmato') AS stato_programmato,
                        COUNT(*) FILTER (WHERE stato_processing = 'failed_final') AS failed_final,
                        COUNT(*) FILTER (WHERE {self._SUSPECT_BANDO_PREDICATE}) AS sospetti_rumore,
                        COUNT(*) - COUNT(DISTINCT hash_bando) AS duplicati
                    FROM public.bando
                    """
                )
                row = cur.fetchone()

                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS ultime_3_run_totale,
                        COUNT(*) FILTER (WHERE stato = 'completed') AS ultime_3_run_completed
                    FROM (
                        SELECT stato
                        FROM public.scraping_log
                        WHERE tipo_operazione = 'scan_fonti_livello2'
                        ORDER BY started_at DESC
                        LIMIT 3
                    ) last_runs
                    """
                )
                run_row = cur.fetchone()
        if not row:
            return {}
        totale = int(row["totale"]) or 1
        result = {k: int(row[k]) for k in row.keys()}
        result["pct_con_descrizione"] = round(
            100.0 * (totale - result["senza_descrizione"]) / totale, 1
        )
        result["pct_con_classificazione"] = round(
            100.0 * (totale - result["senza_classificazione"]) / totale, 1
        )
        result["pct_sospetti_rumore"] = round(
            100.0 * result["sospetti_rumore"] / totale, 1
        )
        result["ultime_3_run_totale"] = int(run_row["ultime_3_run_totale"]) if run_row else 0
        result["ultime_3_run_completed"] = int(run_row["ultime_3_run_completed"]) if run_row else 0
        return result

    def get_dataset_review_summary(self) -> dict[str, Any]:
        """Sintesi diagnostica per review manuale e pre-bonifica dei record sospetti."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        COUNT(*) AS totale_bandi,
                        COUNT(*) FILTER (WHERE {self._SUSPECT_BANDO_PREDICATE}) AS sospetti_totali,
                        COUNT(*) FILTER (WHERE {self._SUSPECT_DENY_HOST}) AS sospetti_host,
                        COUNT(*) FILTER (WHERE {self._SUSPECT_DENY_PATH}) AS sospetti_path,
                        COUNT(*) FILTER (WHERE {self._SUSPECT_DENY_KEYWORD}) AS sospetti_keyword
                    FROM public.bando
                    """
                )
                totals_row = cur.fetchone()

                cur.execute(
                    f"""
                    SELECT
                        fonte_id,
                        COUNT(*) AS sospetti
                    FROM public.bando
                    WHERE {self._SUSPECT_BANDO_PREDICATE}
                    GROUP BY fonte_id
                    ORDER BY sospetti DESC, fonte_id ASC
                    LIMIT 10
                    """
                )
                top_fonti_rows = cur.fetchall()

        totals = dict(totals_row) if totals_row else {}
        totale_bandi = int(totals.get("totale_bandi", 0) or 0)
        sospetti_totali = int(totals.get("sospetti_totali", 0) or 0)
        totals["pct_sospetti_totali"] = round(
            100.0 * sospetti_totali / totale_bandi, 1
        ) if totale_bandi else 0.0
        totals["field_completeness"] = self.get_dataset_field_completeness()
        totals["top_fonti_sospette"] = [dict(row) for row in top_fonti_rows]
        return totals

    def get_dataset_field_completeness(self) -> dict[str, Any]:
        """Metriche operative per checklist Go-Live punto 3."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS totale,
                        COUNT(*) FILTER (
                            WHERE COALESCE(TRIM(titolo), '') <> ''
                              AND COALESCE(TRIM(link_bando), '') <> ''
                              AND COALESCE(TRIM(hash_bando), '') <> ''
                              AND stato_bando IN ('aperto', 'chiuso', 'programmato')
                        ) AS required_complete,
                        COUNT(*) FILTER (WHERE COALESCE(TRIM(titolo), '') = '') AS missing_titolo,
                        COUNT(*) FILTER (WHERE COALESCE(TRIM(link_bando), '') = '') AS missing_link_bando,
                        COUNT(*) FILTER (WHERE COALESCE(TRIM(hash_bando), '') = '') AS missing_hash_bando,
                        COUNT(*) FILTER (
                            WHERE stato_bando IS NULL
                               OR stato_bando NOT IN ('aperto', 'chiuso', 'programmato')
                        ) AS invalid_stato_bando,
                        COUNT(*) FILTER (
                            WHERE raw_data IS NOT NULL
                              AND TRIM(raw_data::text) NOT IN ('', '{}', 'null')
                        ) AS with_raw_data,
                        COUNT(*) FILTER (
                            WHERE data_pubblicazione IS NOT NULL
                               OR data_apertura IS NOT NULL
                               OR data_scadenza IS NOT NULL
                        ) AS with_any_date,
                        COUNT(*) FILTER (WHERE importo_numerico IS NOT NULL) AS with_importo_numerico
                    FROM public.bando
                    """
                )
                row = cur.fetchone()
        if not row:
            return {}
        result = {k: int(row[k]) for k in row.keys()}
        totale = result.get("totale", 0)
        if totale > 0:
            result["pct_required_complete"] = round(100.0 * result["required_complete"] / totale, 1)
            result["pct_with_raw_data"] = round(100.0 * result["with_raw_data"] / totale, 1)
            result["pct_with_any_date"] = round(100.0 * result["with_any_date"] / totale, 1)
            result["pct_with_importo_numerico"] = round(100.0 * result["with_importo_numerico"] / totale, 1)
        else:
            result["pct_required_complete"] = 0.0
            result["pct_with_raw_data"] = 0.0
            result["pct_with_any_date"] = 0.0
            result["pct_with_importo_numerico"] = 0.0
        return result

    def list_suspect_bando_ids(self) -> list[int]:
        """Elenco completo degli ID sospetti per preview bonifica."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id
                    FROM public.bando
                    WHERE {self._SUSPECT_BANDO_PREDICATE}
                    ORDER BY id ASC
                    """
                )
                rows = cur.fetchall()
        return [int(r["id"]) for r in rows]

    def list_suspect_bandi(self, limit: int = 50) -> list[dict[str, Any]]:
        """Restituisce un campione di record sospetti per review manuale."""
        safe_limit = max(1, min(int(limit), 500))
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        id,
                        fonte_id,
                        titolo,
                        link_bando,
                        stato_bando,
                        stato_processing,
                        TRIM(BOTH '|' FROM CONCAT_WS('|',
                            CASE WHEN {self._SUSPECT_DENY_HOST} THEN 'deny_host' END,
                            CASE WHEN {self._SUSPECT_DENY_PATH} THEN 'deny_path' END,
                            CASE WHEN {self._SUSPECT_DENY_KEYWORD} THEN 'deny_keyword' END
                        )) AS motivi_sospetto
                    FROM public.bando
                    WHERE {self._SUSPECT_BANDO_PREDICATE}
                    ORDER BY fonte_id ASC, id ASC
                    LIMIT %s
                    """,
                    (safe_limit,),
                )
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------ #
    # Sezione 4 — Coda AI                                                  #
    # ------------------------------------------------------------------ #

    def get_ai_queue_stats(self) -> dict[str, Any]:
        """Contatori per stato della coda AI e job bloccati."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT stato, COUNT(*) AS n
                    FROM public.ai_job_queue
                    GROUP BY stato
                    ORDER BY n DESC
                    """
                )
                rows = cur.fetchall()

                cur.execute(
                    """
                    SELECT COUNT(*) AS stuck
                    FROM public.ai_job_queue
                    WHERE stato = 'processing'
                      AND started_at < NOW() - INTERVAL '10 minutes'
                    """
                )
                stuck_row = cur.fetchone()

                cur.execute(
                    """
                    SELECT ROUND(
                        AVG(EXTRACT(EPOCH FROM (completed_at - creato_il))), 1
                    ) AS avg_seconds
                    FROM public.ai_job_queue
                    WHERE stato = 'completed'
                      AND completed_at > NOW() - INTERVAL '24 hours'
                    """
                )
                avg_row = cur.fetchone()

        by_stato = {str(r["stato"]): int(r["n"]) for r in rows}
        return {
            "by_stato": by_stato,
            "queued": by_stato.get("queued", 0),
            "failed": by_stato.get("failed", 0),
            "processing_stuck": int(stuck_row["stuck"]) if stuck_row else 0,
            "avg_completion_seconds": float(avg_row["avg_seconds"]) if avg_row and avg_row["avg_seconds"] is not None else None,
        }

    # ------------------------------------------------------------------ #
    # Sezione 5 — Errori definitivi                                        #
    # ------------------------------------------------------------------ #

    def get_error_stats(self) -> dict[str, Any]:
        """Contatori errori definitivi e top-5 tipologie non risolte."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS totale,
                        COUNT(*) FILTER (WHERE risolto = FALSE) AS aperti,
                        COUNT(*) FILTER (WHERE risolto = TRUE)  AS risolti
                    FROM public.scraping_errori_definitivi
                    """
                )
                totals = cur.fetchone()

                cur.execute(
                    """
                    SELECT entity_type, errore_tipo, COUNT(*) AS n
                    FROM public.scraping_errori_definitivi
                    WHERE risolto = FALSE
                    GROUP BY entity_type, errore_tipo
                    ORDER BY n DESC
                    LIMIT 5
                    """
                )
                top_rows = cur.fetchall()

        return {
            "totale": int(totals["totale"]) if totals else 0,
            "aperti": int(totals["aperti"]) if totals else 0,
            "risolti": int(totals["risolti"]) if totals else 0,
            "top_tipi": [dict(r) for r in top_rows],
        }

    # ------------------------------------------------------------------ #
    # Sezione 6 — Storico consistenza                                      #
    # ------------------------------------------------------------------ #

    def get_storico_stats(self) -> dict[str, Any]:
        """Verifica di base sulla tabella bando_storico."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS righe_ultime_24h
                    FROM public.bando_storico
                    WHERE modificato_at > NOW() - INTERVAL '24 hours'
                    """
                )
                recent_row = cur.fetchone()

                cur.execute(
                    """
                    SELECT COUNT(*) AS incoerenti
                    FROM public.bando
                    WHERE primo_scraping_at > ultimo_scraping_at
                    """
                )
                incoerenti_row = cur.fetchone()

        return {
            "righe_ultime_24h": int(recent_row["righe_ultime_24h"]) if recent_row else 0,
            "bandi_incoerenti_date": int(incoerenti_row["incoerenti"]) if incoerenti_row else 0,
        }
