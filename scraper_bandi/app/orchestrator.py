"""Orchestra l'intero flusso step 1: discover -> classify -> reachability ->
UPSERT in `fonte` + mark deprecated."""
from __future__ import annotations

import time
from typing import Any

from .db import mark_deprecated, select_known_links, upsert_fonti
from .discover import FonteCandidate, fetch_page, parse_page
from .logger import logger
from .reachability import check_many


def _records_from_results(
    candidates: list[FonteCandidate],
    reach_by_url: dict[str, Any],
) -> list[dict[str, Any]]:
    """Combina candidati + risultati reachability in record DB-ready."""
    records: list[dict[str, Any]] = []
    for c in candidates:
        r = reach_by_url.get(c.link)
        if r is None:
            # Fallback (non dovrebbe accadere): segnaliamo errore.
            attivo = False
            formato_link = "HTML"
            stato = "connection error"
        else:
            attivo = r.attivo
            formato_link = r.formato_link
            stato = "ready" if attivo else "connection error"

        records.append({
            "link": c.link,
            "categoria_programma_id": c.categoria_programma_id,
            "tipologia_programma_id": c.tipologia_programma_id,
            "tipo_link": c.tipo_link,
            "formato_link": formato_link,
            "attivo": attivo,
            "stato_processing": stato,
        })
    return records


async def run(dry_run: bool = False, limit: int | None = None) -> dict[str, int]:
    """Esegue il discover completo. Ritorna counters per il log finale.

    Args:
        dry_run: nessuna scrittura (ne' upsert_fonti ne' mark_deprecated):
            logga cosa farebbe e i contatori. Le letture restano.
        limit: considera solo le prime N fonti scoperte (smoke test). Con
            limit il mark deprecated e' SEMPRE saltato: l'elenco delle fonti
            attive e' parziale e marcherebbe deprecate fonti ancora vive.

    I default riproducono il comportamento storico: `run()` senza argomenti
    resta la firma usata da backend/app/bandi_pipeline.py.
    """
    started = time.monotonic()
    logger.info(
        "[orchestrator] === START discover fonti{} ===",
        " (DRY-RUN: nessuna scrittura)" if dry_run else "",
    )

    # 1. Fetch + parse
    html = await fetch_page()
    candidates = parse_page(html)
    if not candidates:
        logger.error(
            "[orchestrator] nessun candidato estratto dalla pagina sorgente. "
            "Possibile cambio della struttura HTML."
        )
        return {
            "discovered": 0, "new": 0, "updated": 0,
            "deprecated": 0, "connection_error": 0,
        }

    # 1-bis. --limit: tronca PRIMA della reachability (meno rete nello smoke test).
    if limit is not None:
        n_scoperte = len(candidates)
        candidates = candidates[:max(limit, 0)]
        logger.info(
            "[orchestrator] --limit {}: considero {} fonti su {} scoperte",
            limit, len(candidates), n_scoperte,
        )

    # 2. Reachability
    urls = [c.link for c in candidates]
    results = await check_many(urls)
    reach_by_url = {r.url: r for r in results}

    n_reachable = sum(1 for r in results if r.attivo)
    n_unreachable = len(results) - n_reachable
    logger.info(
        "[orchestrator] reachability: {} attivi, {} non raggiungibili",
        n_reachable, n_unreachable,
    )

    # 3. Compose records
    records = _records_from_results(candidates, reach_by_url)

    # 4. Snapshot dei link gia' in DB (per il conteggio new vs updated)
    known_links_before = select_known_links()
    new_links = {r["link"] for r in records} - known_links_before
    updated_links = {r["link"] for r in records} & known_links_before

    active_links = {r["link"] for r in records}

    if dry_run:
        # 5-6. DRY-RUN: nessuna scrittura, solo il resoconto di cosa farebbe
        # il giro reale. Il conteggio dei deprecati e' una stima per eccesso:
        # mark_deprecated esclude anche discoverable=false e le gia' deprecate.
        logger.info(
            "[orchestrator] DRY-RUN: upsert_fonti saltato per {} record "
            "({} nuovi, {} aggiornati)",
            len(records), len(new_links), len(updated_links),
        )
        logger.info(
            "[orchestrator] DRY-RUN: mark_deprecated saltato; link in DB ma non "
            "nella pagina: {} (stima per eccesso)",
            len(known_links_before - active_links),
        )
        n_deprecated = 0
    else:
        # 5. UPSERT
        upsert_fonti(records)

        # 6. Mark deprecated (link in DB ma non piu' nella pagina sorgente).
        # Con --limit l'elenco e' parziale: marcare i mancanti spegnerebbe
        # fonti vive, quindi si salta sempre.
        if limit is not None:
            logger.warning(
                "[orchestrator] --limit attivo: mark_deprecated saltato (elenco parziale)"
            )
            n_deprecated = 0
        else:
            n_deprecated = mark_deprecated(active_links)

    elapsed = time.monotonic() - started

    counters = {
        "discovered": len(records),
        "new": len(new_links),
        "updated": len(updated_links),
        "deprecated": n_deprecated,
        "connection_error": n_unreachable,
    }

    logger.info(
        "[orchestrator] === DONE in {:.1f}s | counters={} ===",
        elapsed, counters,
    )
    return counters
