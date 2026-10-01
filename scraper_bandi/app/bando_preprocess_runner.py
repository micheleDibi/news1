"""Orchestratore step intermedio: pre-processing bandi via LLM.

Flusso:
  1. SELECT WHERE stato_processing='scraped' (cap a batch_size)
  2. Pre-load fonti + lookup categoria/tipologia (cache LRU)
  3. asyncio.gather su tutti i bandi (Semaphore=PREPROCESS_CONCURRENCY)
  4. Compose updates: valid -> stato_processing='processed' + stato_bando;
     invalid -> stato_processing='rejected' + rejection_reason
  5. Batch UPDATE (chunk 100)
  6. Counters cumulativi loggati

Idempotente: ri-eseguendo, solo i record ancora 'scraped' vengono presi
(quelli gia' processed/rejected restano).
"""
from __future__ import annotations

import asyncio
import time
from collections import Counter
from typing import Any

from . import bilancio, telemetria
from .bando_resolver import resolve_bando
from .db import (
    enrich_fonti_with_names,
    select_bandi_scraped,
    select_fonti_by_ids,
    update_bandi_postanalysis,
)
from .dominio_ufficiale import scegli_fonte
from .logger import logger
from .preprocessor import aggiungi_delta_scarico, analyze_bando, conta_spesa, istantanea_scarico
from .settings import get_settings

#: Lo step della riga di spesa del passo (contratto `bandi-giro-3` §4).
STEP = "preprocess"


def url_da_leggere(bando: dict[str, Any]) -> str | None:
    """La pagina ufficiale da leggere al posto di `link_bando`, o None.

    Giro 3 (§8): `dominio_ufficiale.scegli_fonte`; None quando la scelta e'
    `link_bando` stesso (nessuna fonte trovata, oppure la fonte e' un PDF).
    """
    url, _ufficiale = scegli_fonte(bando)
    link = str(bando.get("link_bando") or "").strip()
    return url if url and url != link else None


def _registra_spesa(spesa: bilancio.Contatori, copertura: dict[str, Any],
                    durata_s: float, errori: int) -> None:
    """La riga `pipeline_run` del passo (§4): spesa e copertura. Non solleva."""
    try:
        riga = telemetria.PipelineRun(step=STEP).concludi(
            durata_s=durata_s,
            esito=telemetria.esito_da_contatori(errori=errori),
            contatori={**spesa.come_dizionario(), "copertura": copertura},
        )
        telemetria.scrivi_pipeline_run(riga)
    except Exception as e:                                # pragma: no cover - difesa
        logger.warning("[preprocess] riga di spesa non registrata: {}", e)


def _build_update(bando_id: int, analysis: dict[str, Any]) -> dict[str, Any]:
    """Compose un record di UPDATE dal risultato dell'analisi.

    Include le 3 date estratte (data_pubblicazione, data_apertura, data_scadenza)
    se presenti — sono gia' state validate (triple-gate) + reconciled (data-driven
    forza stato_bando).
    """
    update: dict[str, Any] = {
        "id": bando_id,
        "confidence_score": float(analysis["confidence_score"]),
    }
    if analysis["is_valid_bando"]:
        update["stato_processing"] = "processed"
        # stato_bando puo' essere None (LLM='unknown' o reconciliation a None)
        st = analysis["stato_bando"]
        update["stato_bando"] = st if st in ("aperto", "chiuso", "in apertura prossimamente") else None
        update["rejection_reason"] = None
        # 3 date (None se non passate il triple-gate)
        update["data_pubblicazione"] = analysis.get("data_pubblicazione")
        update["data_apertura"] = analysis.get("data_apertura")
        update["data_scadenza"] = analysis.get("data_scadenza")
        # Le ore solo quando la citazione le contiene: una chiave assente non
        # tocca la colonna. `data_scadenza_verificata` non si scrive mai qui:
        # la governa un evento (CHECK della 03).
        for campo in ("ora_apertura", "ora_scadenza"):
            if analysis.get(campo):
                update[campo] = analysis[campo]
    else:
        update["stato_processing"] = "rejected"
        update["stato_bando"] = None
        update["rejection_reason"] = analysis.get("rejection_reason") or "non classificato come bando"
        update["data_pubblicazione"] = None
        update["data_apertura"] = None
        update["data_scadenza"] = None
    return update


async def run(
    batch_size: int | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Esegue il pre-processing su tutti i bandi 'scraped'.

    Args:
        batch_size: cap del SELECT iniziale. None = nessun cap (TUTTI i scraped).
        dry_run: se True, NON scrive il DB, ritorna solo i counter.
        limit: alternativo a batch_size per smoke test (es. limit=10).
    """
    settings = get_settings()
    started = time.monotonic()
    logger.info(
        "[preprocess] === START | model={} concurrency_llm={} concurrency_firecrawl={} "
        "resolver_model={} dry_run={} ===",
        settings.preprocess_model,
        settings.preprocess_concurrency,
        settings.preprocess_firecrawl_concurrency,
        settings.resolver_model,
        dry_run,
    )

    # Se non viene passato ne' limit ne' batch_size, processa TUTTI i scraped.
    select_limit = limit if limit is not None else batch_size
    rows = select_bandi_scraped(limit=select_limit)
    if not rows:
        logger.info("[preprocess] nessun bando in stato 'scraped': nulla da fare")
        return {
            "processed_total": 0, "valid": 0, "rejected": 0,
            "errors": 0, "elapsed_s": 0, "copertura": telemetria.copertura(0, 0),
        }

    # Pre-load fonti + arricchimento nomi categoria/tipologia
    fonte_ids = list({r["fonte_id"] for r in rows if r.get("fonte_id") is not None})
    fonti_by_id = select_fonti_by_ids(fonte_ids)
    fonti_by_id = enrich_fonti_with_names(fonti_by_id)
    logger.info("[preprocess] preload: {} fonti uniche", len(fonti_by_id))

    # Concorrenza split: Firecrawl (rate-limit) e LLM (rate-limit Anthropic) sono
    # bottleneck distinti. La Firecrawl call sta DENTRO analyze_bando, quindi un
    # singolo semaforo intorno a _analyze_one limita entrambi. Tieni il piu'
    # restrittivo dei due: Firecrawl di solito ~5.
    effective_concurrency = min(
        settings.preprocess_concurrency,
        settings.preprocess_firecrawl_concurrency,
    )
    logger.info(
        "[preprocess] effective concurrency (min of LLM/Firecrawl) = {}",
        effective_concurrency,
    )

    sem = asyncio.Semaphore(effective_concurrency)
    progress = {"done": 0}
    total = len(rows)

    letture = Counter()

    async def _analyze_one(bando: dict[str, Any]) -> tuple[int, dict[str, Any] | Exception]:
        async with sem:
            bando_id = bando["id"]
            fonte_ctx = fonti_by_id.get(bando.get("fonte_id"), {})
            try:
                # Giro 3 (§8): prima la pagina ufficiale, poi `link_bando`,
                # poi il ripiego del resolver.
                ufficiale = url_da_leggere(bando)
                if ufficiale:
                    letture["letti_da_ufficiale"] += 1
                    analysis = await analyze_bando(bando, fonte_ctx, url_lettura=ufficiale)
                    if analysis.get("_needs_fallback"):
                        letture["ripiego_su_link_bando"] += 1
                        analysis = await analyze_bando(bando, fonte_ctx)
                    elif not analysis.get("is_valid_bando"):
                        # Revisione #145: la pagina scelta dal resolver precoce
                        # (con la sola scadenza provvisoria) puo' essere una
                        # pagina generica dell'ente, e un bando vero non deve
                        # finire `rejected` per questo. Si rilegge `link_bando`
                        # e si scarta solo se anche li' il bando non e' valido;
                        # se `link_bando` non si legge, decide il ripiego.
                        letture["riletti_prima_dello_scarto"] += 1
                        seconda = await analyze_bando(bando, fonte_ctx)
                        if seconda.get("is_valid_bando") or seconda.get("_needs_fallback"):
                            if seconda.get("is_valid_bando"):
                                letture["scarti_evitati_con_link_bando"] += 1
                            analysis = seconda
                else:
                    analysis = await analyze_bando(bando, fonte_ctx)
                # Trigger fallback se markdown bando vuoto
                if analysis.get("_needs_fallback"):
                    logger.info(
                        "[preprocess/{}] -> fallback bando_resolver (Sonnet+Firecrawl fonte)",
                        bando_id,
                    )
                    analysis = await resolve_bando(bando, fonte_ctx)
                progress["done"] += 1
                if progress["done"] % 50 == 0 or progress["done"] == total:
                    logger.info("[preprocess] progress {}/{}", progress["done"], total)
                return bando_id, analysis
            except Exception as e:
                progress["done"] += 1
                logger.exception("[preprocess] bando_id={} fallito: {}", bando_id, e)
                return bando_id, e

    # La spesa del passo (§4): ogni chiamata al modello fatta qui dentro, ripiego
    # del resolver compreso, finisce in `spesa`. L'ingresso conta e non si
    # ferma mai.
    spesa = bilancio.Contatori()
    # §19.1: i crediti Firecrawl (e i fetch) scaricati da questo passo vanno
    # nella sua riga, e solo nella sua: il resolver dopo conta dal suo inizio.
    scarico_prima = istantanea_scarico()
    with conta_spesa(spesa):
        results = await asyncio.gather(*[_analyze_one(b) for b in rows])
    aggiungi_delta_scarico(spesa, scarico_prima)

    # Compose updates
    valid_updates: list[dict[str, Any]] = []
    rejected_updates: list[dict[str, Any]] = []
    errors = 0
    stato_bando_dist: Counter[str | None] = Counter()
    confidence_sum = 0.0
    confidence_n = 0
    fallback_used = 0
    fallback_failed = 0
    fallback_rinviati = 0
    with_pub = 0
    with_apt = 0
    with_scad = 0
    with_ora_apt = 0
    with_ora_scad = 0
    date_presunte_respinte = 0
    origini_scadenza: Counter[str] = Counter()
    chiusi_da_lettore = 0
    status2_in_apertura = 0
    chiuso_modello_scartato = 0

    for bid, res in results:
        if isinstance(res, Exception):
            errors += 1
            continue
        analysis = res
        if analysis.get("_errore_transitorio"):
            # Errore passeggero del ripiego (rete, credito, API): nessuna
            # scrittura, il bando resta `scraped` e il giro dopo riprova. Come
            # un'eccezione del percorso principale, e contato con lei.
            errors += 1
            fallback_used += 1
            fallback_rinviati += 1
            continue
        update = _build_update(bid, analysis)
        date_presunte_respinte += int(analysis.get("_date_presunte_respinte") or 0)
        confidence_sum += update["confidence_score"]
        confidence_n += 1
        if analysis.get("_fallback_used"):
            fallback_used += 1
            if analysis.get("_fallback_failed"):
                fallback_failed += 1
        if update["stato_processing"] == "processed":
            valid_updates.append(update)
            stato_bando_dist[update.get("stato_bando")] += 1
            if update.get("data_pubblicazione"):
                with_pub += 1
            if update.get("data_apertura"):
                with_apt += 1
            if update.get("data_scadenza"):
                with_scad += 1
                origini_scadenza[analysis.get("_origine_scadenza") or "altro"] += 1
            if update.get("ora_apertura"):
                with_ora_apt += 1
            if update.get("ora_scadenza"):
                with_ora_scad += 1
            if analysis.get("_chiuso_da_lettore"):
                chiusi_da_lettore += 1
            if analysis.get("_status2_in_apertura"):
                status2_in_apertura += 1
            if analysis.get("_chiuso_modello_scartato"):
                chiuso_modello_scartato += 1
        else:
            rejected_updates.append(update)

    # UPDATE DB (async: UPDATE per id con concorrenza interna)
    n_updated = 0
    n_failed = 0
    if not dry_run:
        all_updates = valid_updates + rejected_updates
        res_upd = await update_bandi_postanalysis(all_updates)
        n_updated = res_upd.get("updated", 0)
        n_failed = res_upd.get("failed", 0)

    avg_conf = confidence_sum / confidence_n if confidence_n else 0.0
    elapsed = time.monotonic() - started
    copertura = telemetria.copertura(total, total - errors, "errore" if errors else None)

    counters: dict[str, Any] = {
        "processed_total": total,
        "valid": len(valid_updates),
        "rejected": len(rejected_updates),
        "errors": errors,
        "by_stato_bando": dict(stato_bando_dist),
        "avg_confidence": round(avg_conf, 3),
        "with_data_pubblicazione": with_pub,
        "with_data_apertura": with_apt,
        "with_data_scadenza": with_scad,
        "with_ora_apertura": with_ora_apt,
        "with_ora_scadenza": with_ora_scad,
        # da dove viene la scadenza scritta (§6.3, §19.5): il modello resta la
        # fonte principale, gli altri sono i ripieghi del giro 2
        "scadenze_da_lettore": origini_scadenza["lettore"],
        "scadenze_da_finestra": origini_scadenza["finestra"],
        "scadenze_da_etichetta_oe": origini_scadenza["etichetta_oe"],
        "chiusi_da_lettore": chiusi_da_lettore,
        "status2_in_apertura": status2_in_apertura,
        # §21.1: i 'chiuso' del modello scartati perche' la scadenza era da
        # oggi in poi (la riga va avanti a enrich e SEO invece di restare nascosta)
        "chiuso_modello_scartato": chiuso_modello_scartato,
        # date che G10 ha respinto perche' presunte: nei 7 giorni d'ombra
        # separa l'effetto del prompt a 8 000 caratteri da quello di G10
        "date_presunte_respinte": date_presunte_respinte,
        "fallback_used": fallback_used,
        "fallback_failed": fallback_failed,
        "fallback_rinviati": fallback_rinviati,
        "db_updated": n_updated,
        "db_failed": n_failed,
        "dry_run": dry_run,
        "elapsed_s": round(elapsed, 1),
        # Giro 3 (§8): quante righe hanno letto la pagina ufficiale, e quante
        # sono ripiegate su `link_bando` perche' la pagina ufficiale non bastava.
        "letti_da_ufficiale": letture["letti_da_ufficiale"],
        "ripiego_su_link_bando": letture["ripiego_su_link_bando"],
        # Revisione #145: le righe che la pagina ufficiale scartava, rilette su
        # `link_bando`, e quante di quelle erano bandi veri.
        "riletti_prima_dello_scarto": letture["riletti_prima_dello_scarto"],
        "scarti_evitati_con_link_bando": letture["scarti_evitati_con_link_bando"],
        # §4: la spesa del passo e la copertura (§1). La riga di spesa si
        # scrive solo fuori dal dry-run: dal Mac nessuna scrittura (§0).
        "costo_usd": spesa.usd,
        "spesa": spesa.come_dizionario(),
        "copertura": copertura,
    }
    if not dry_run:
        _registra_spesa(spesa, copertura, elapsed, errors)
    logger.info("[preprocess] === DONE | {} ===", counters)
    return counters
