from __future__ import annotations

import json
import time
import traceback
from datetime import datetime, timezone
from typing import Any

from app.config.session import get_session_id, new_session_id
from app.db.connection import get_db_connection
from app.repos.base import CategoriaProgrammaRepo, FonteRepo, TipologiaProgrammaRepo
from app.scrapers.root_discovery import DiscoveredFonte, RootDiscovery


class FonteDiscoveryService:
    def __init__(self) -> None:
        self.discovery = RootDiscovery()
        self.fonte_repo = FonteRepo()
        self.categoria_repo = CategoriaProgrammaRepo()
        self.tipologia_repo = TipologiaProgrammaRepo()

    def run(self) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()

        session_id = get_session_id() or new_session_id()
        scraping_log_id = self._create_log_entry(session_id=str(session_id), started_at=started_at)

        try:
            discovered = self.discovery.run_records()
            payload = self._resolve_reference_ids(discovered)
            eligible = [
                row
                for row in payload
                if row.get("categoria_programma_id") is not None and row.get("tipologia_programma_id") is not None
            ]
            skipped_unmapped = len(payload) - len(eligible)

            sync_stats = self.fonte_repo.sync_discovered_sources(eligible)
            sync_stats["skipped_unmapped"] = skipped_unmapped

            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            self._finalize_log_success(
                scraping_log_id=scraping_log_id,
                elapsed_ms=elapsed_ms,
                processed=len(discovered),
                sync_stats=sync_stats,
            )

            return {
                "session_id": str(session_id),
                "scraping_log_id": scraping_log_id,
                "discovered": len(discovered),
                **sync_stats,
            }
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            self._finalize_log_error(
                scraping_log_id=scraping_log_id,
                elapsed_ms=elapsed_ms,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
                error_stack=traceback.format_exc(),
            )
            raise

    def _resolve_reference_ids(self, discovered: list[DiscoveredFonte]) -> list[dict[str, Any]]:
        categoria_map = self.categoria_repo.get_name_to_id_map()
        tipologia_map = self.tipologia_repo.get_name_to_id_map()

        resolved: list[dict[str, Any]] = []
        for item in discovered:
            categoria_id = categoria_map.get(item.categoria_programma_nome or "")
            tipologia_id = tipologia_map.get(item.tipologia_programma_nome or "")

            note_parts: list[str] = []
            if item.categoria_programma_nome and categoria_id is None:
                note_parts.append(f"categoria_non_trovata={item.categoria_programma_nome}")
            if item.tipologia_programma_nome and tipologia_id is None:
                note_parts.append(f"tipologia_non_trovata={item.tipologia_programma_nome}")
            if item.contesto:
                note_parts.append(f"contesto={item.contesto}")

            resolved.append(
                {
                    "link": item.link,
                    "titolo": item.titolo,
                    "categoria_programma_id": categoria_id,
                    "tipologia_programma_id": tipologia_id,
                    "tipo_link": item.tipo_link,
                    "formato_link": item.formato_link,
                    "note_aggiuntive": " | ".join(note_parts) if note_parts else None,
                }
            )

        return resolved

    def _create_log_entry(self, session_id: str, started_at: datetime) -> int:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.scraping_log (
                        fonte_id,
                        session_id,
                        tipo_operazione,
                        stato,
                        url_processato,
                        request_params,
                        started_at
                    ) VALUES (
                        NULL,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s::jsonb,
                        %s
                    )
                    RETURNING id
                    """,
                    (
                        session_id,
                        "discovery_fonti",
                        "processing",
                        self.discovery.root_url,
                        json.dumps({"root_url": self.discovery.root_url}),
                        started_at,
                    ),
                )
                row = cur.fetchone()
        return int(row["id"])

    @staticmethod
    def _finalize_log_success(
        scraping_log_id: int,
        elapsed_ms: int,
        processed: int,
        sync_stats: dict[str, Any],
    ) -> None:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.scraping_log
                    SET stato = %s,
                        bandi_trovati = %s,
                        tempo_esecuzione_ms = %s,
                        pagine_crawlate = %s,
                        response_summary = %s::jsonb,
                        completed_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        "completed",
                        processed,
                        elapsed_ms,
                        1,
                        json.dumps(sync_stats),
                        scraping_log_id,
                    ),
                )

    @staticmethod
    def _finalize_log_error(
        scraping_log_id: int,
        elapsed_ms: int,
        error_type: str,
        error_message: str,
        error_stack: str,
    ) -> None:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.scraping_log
                    SET stato = %s,
                        errore_tipo = %s,
                        errore_messaggio = %s,
                        errore_stack = %s,
                        tempo_esecuzione_ms = %s,
                        completed_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        "failed",
                        error_type,
                        error_message[:4000],
                        error_stack,
                        elapsed_ms,
                        scraping_log_id,
                    ),
                )
