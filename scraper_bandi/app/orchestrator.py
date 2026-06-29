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


async def run() -> dict[str, int]:
    """Esegue il discover completo. Ritorna counters per il log finale."""
    started = time.monotonic()
    logger.info("[orchestrator] === START discover fonti ===")

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

    # 5. UPSERT
    upsert_fonti(records)

    # 6. Mark deprecated (link in DB ma non piu' nella pagina sorgente)
    active_links = {r["link"] for r in records}
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
