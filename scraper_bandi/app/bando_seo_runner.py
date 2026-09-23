"""Orchestratore step v8: skill SEO (enriched -> completed).

Per ogni bando con stato_processing='enriched':
  1. SELECT row + lookup catalogo FK/junction -> nomi
  2. Testo della **pagina ufficiale** (§5): prima `fonte_ufficiale_url`, poi
     `link_bando` non aggregatore, mai Obiettivo Europa. Il testo passa da
     `impronte.seleziona_sezioni(..., 12000)` e porta in testa l'intestazione
     che dice al modello che cosa sta leggendo
  3. enrich_seo() -> payload validato (slug, titolo, contenuto, ecc.), con il
     gate degli URL alimentato da fonte ufficiale + allegati + bando_link
  4. update_bando_completed() -> 14 campi + stato_processing='completed'

Concorrenza: Semaphore(SEO_CONCURRENCY=3) per Opus rate-limit.
Idempotente: re-run salta i gia' 'completed' (default). Opt-in
--rerun-completed include anche i completati.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Sequence

from .db import (
    build_bando_input_context,
    load_catalogo,
    reconcile_canonical_key,
    select_bandi_to_complete,
    update_bando_completed,
)
from .db import controllo, select_link_da_verificare
from .dominio_ufficiale import e_aggregatore
from .enricher import _firecrawl_scrape_markdown, _httpx_fetch_text
from .impronte import seleziona_sezioni
from .logger import logger
from .seo_skill import enrich_seo
from .settings import bool_env, get_settings


# Budget del testo di pagina che entra nel prompt della skill SEO (fix 8.a.2:
# il troncamento sta qui, dove il testo entra nel prompt, non nella cache di
# `scarico.py`). `seo_skill._build_seo_prompt` ne ritaglia altri 8 000: questo
# e' la cintura esterna, che limita anche i controlli di validazione del
# payload svolti sul markdown.
BUDGET_PROMPT_CHAR = 12000

# Le due intestazioni di §5. Sono testo del prompt, non commenti: la prima
# autorizza il modello a citare e a linkare la pagina, la seconda glielo vieta.
INTESTAZIONE_UFFICIALE = "PAGINA UFFICIALE: {url}"
INTESTAZIONE_RIPIEGO = "TESTO DELL'AGGREGATORE (ripiego, non citare, non linkare)"


def scegli_fonte(bando: dict[str, Any]) -> tuple[str, bool]:
    """(URL da cui prendere il testo, e' una pagina ufficiale?).

    Ordine di §5: `fonte_ufficiale_url` quando la fonte e' `trovata`, poi
    `link_bando` se non e' un aggregatore. Se resta solo l'aggregatore il testo
    si prende lo stesso — e' l'unico che esiste — ma con l'intestazione di
    ripiego, che dice al modello di non citarlo e di non linkarlo. **Non** si
    preferisce mai la scheda dell'aggregatore a una pagina d'ente.
    """
    ufficiale = str(bando.get("fonte_ufficiale_url") or "").strip()
    stato = str(bando.get("fonte_ufficiale_stato") or "trovata")
    if ufficiale and stato == "trovata" and not e_aggregatore(ufficiale):
        return ufficiale, True
    link = str(bando.get("link_bando") or "").strip()
    if not link:
        return "", False
    return link, not e_aggregatore(link)


def componi_testo(
    testo: str,
    url: str,
    ufficiale: bool,
    *,
    allegati: Sequence[dict[str, Any]] = (),
    budget: int = BUDGET_PROMPT_CHAR,
) -> str:
    """Intestazione + selezione per sezioni entro il budget (§5).

    Il budget si applica al corpo, non all'intestazione: l'intestazione e' la
    riga che cambia il significato di tutto il resto e non puo' essere la prima
    cosa che un troncamento butta via.
    """
    if not testo.strip():
        return ""
    corpo = seleziona_sezioni(testo, budget, allegati=allegati)
    intestazione = INTESTAZIONE_UFFICIALE.format(url=url) if ufficiale else INTESTAZIONE_RIPIEGO
    return f"{intestazione}\n\n{corpo}".strip()


def elenco_conoscibile(bando: dict[str, Any], *, link_leggibili: bool) -> bool:
    """Sappiamo davvero quali URL sono stati provati per questo bando?

    Se `bando_link` non e' leggibile (migrazione 02 non applicata) **e** la riga
    non ha una `fonte_ufficiale_url`, nessuno ha ancora guardato: l'elenco non
    e' vuoto, e' ignoto. La differenza non e' accademica — `None` spegne il
    gate, `[]` lo accende con l'insieme vuoto e degrada a testo ogni link e
    ogni allegato del payload — e confonderle significherebbe pubblicare tutto
    il corpus senza collegamenti dal primo giro.
    """
    if link_leggibili:
        return True
    return bool(str(bando.get("fonte_ufficiale_url") or "").strip())


def url_ammessi(
    bando: dict[str, Any],
    link: Sequence[dict[str, Any]] = (),
    *,
    link_leggibili: bool = True,
) -> list[str] | None:
    """L'unione di §5: fonte ufficiale + allegati + `bando_link` pubblicabili.

    E' cio' che il gate di `seo_skill` confronta con gli URL dei segmenti
    `link`. Un elenco vuoto non e' «nessun vincolo»: e' «il resolver ha
    guardato e non ha trovato nulla», e il gate degradera' tutti i link a
    testo. `None` e' l'altra risposta — «non lo so» — e spegne il gate.
    """
    if not elenco_conoscibile(bando, link_leggibili=link_leggibili):
        return None
    urls: list[str] = []
    ufficiale = str(bando.get("fonte_ufficiale_url") or "").strip()
    if ufficiale:
        urls.append(ufficiale)
    for allegato in bando.get("allegati") or []:
        if isinstance(allegato, dict) and allegato.get("url"):
            urls.append(str(allegato["url"]))
    for riga in link:
        if riga.get("pubblicabile") and riga.get("url"):
            urls.append(str(riga["url"]))
    return list(dict.fromkeys(urls))


def allegati_ammessi(
    bando: dict[str, Any],
    link: Sequence[dict[str, Any]] = (),
    *,
    link_leggibili: bool = True,
) -> list[str] | None:
    """Gli URL dei soli documenti verificati: `bando.allegati` piu' le righe
    `tipo='allegato'` pubblicabili di `bando_link`.

    Stessa distinzione di `url_ammessi`: `None` quando nessuno ha verificato
    niente, elenco (anche vuoto) quando la verifica c'e' stata.
    """
    if not elenco_conoscibile(bando, link_leggibili=link_leggibili):
        return None
    urls: list[str] = []
    for allegato in bando.get("allegati") or []:
        if isinstance(allegato, dict) and allegato.get("url"):
            urls.append(str(allegato["url"]))
    for riga in link:
        if riga.get("pubblicabile") and riga.get("tipo") == "allegato" and riga.get("url"):
            urls.append(str(riga["url"]))
    return list(dict.fromkeys(urls))


def elenchi_ammessi(
    bando: dict[str, Any],
    link: Sequence[dict[str, Any]] = (),
    *,
    link_leggibili: bool = True,
) -> tuple[list[str] | None, list[str] | None]:
    """(URL ammessi, allegati ammessi) per un bando: cio' che `_do_one` passa a
    `enrich_seo`. Sta qui, fuori dalla chiusura, perche' sia collaudabile su
    una riga nella forma di `select_bandi_to_complete`."""
    return (
        url_ammessi(bando, link, link_leggibili=link_leggibili),
        allegati_ammessi(bando, link, link_leggibili=link_leggibili),
    )


def _dedup_canonical_attivo() -> bool:
    """Fix 8.a.10: la fusione per canonical_key resta dietro DEDUP_CANONICAL
    (default 'false'). Marcare un bando 'completed_duplicate' lo
    spubblicherebbe (RLS: completed AND slug IS NOT NULL) mentre BandoFit lo
    legge, e la chiave non e' stabile: nessuna fusione automatica."""
    return bool_env("DEDUP_CANONICAL", False)


def _link_del_bando(bando_id: int) -> tuple[list[dict[str, Any]], bool]:
    """(righe di `bando_link` del bando, la tabella era leggibile?).

    Passa da `db.controllo`: prima della migrazione 02 la tabella non esiste e
    una select ferma non lo step ma tutto il giro SEO. Il secondo valore e' cio'
    che distingue «nessun link» da «non so»: senza di lui il gate degli URL
    nascerebbe acceso con l'insieme vuoto su tutto il corpus.
    """
    try:
        if not controllo.tabella_esiste("bando_link"):
            return [], False
        return select_link_da_verificare(bando_id=bando_id), True
    except Exception as e:                               # pragma: no cover - difesa
        logger.warning("[seo] bando_link non leggibile per {}: {}", bando_id, e)
        return [], False


async def run(
    dry_run: bool = False,
    limit: int | None = None,
    include_completed: bool = False,
) -> dict[str, Any]:
    """Esegue la skill SEO su tutti i bandi 'enriched'.

    Args:
        dry_run: se True, NON scrive il DB.
        limit: cap totale candidati (smoke test).
        include_completed: se True, include anche 'completed' (re-run).
    """
    settings = get_settings()
    started = time.monotonic()
    logger.info(
        "[seo] === START | model={} concurrency={} dry_run={} include_completed={} ===",
        settings.seo_model,
        settings.seo_concurrency,
        dry_run,
        include_completed,
    )

    # 1. SELECT candidati
    bandi = select_bandi_to_complete(limit=limit, include_completed=include_completed)
    if not bandi:
        logger.info("[seo] nessun bando candidato")
        return {"selected": 0, "elapsed_s": 0}

    # 2. Pre-load catalogo (lru_cache singleton)
    catalogo = load_catalogo()
    logger.info(
        "[seo] catalogo: tipologie={} programmi={} modalita={} "
        "beneficiari={} ateco={} regioni={} settori={}",
        len(catalogo.get("tipologie", [])),
        len(catalogo.get("programmi", [])),
        len(catalogo.get("modalita", [])),
        len(catalogo.get("beneficiari", [])),
        len(catalogo.get("codici_ateco", [])),
        len(catalogo.get("regioni", [])),
        len(catalogo.get("settori", [])),
    )

    # 3. Loop con Semaphore
    sem = asyncio.Semaphore(max(1, settings.seo_concurrency))
    progress = {"done": 0}
    total = len(bandi)

    async def _do_one(
        b: dict[str, Any],
    ) -> tuple[int, dict[str, Any] | None, bool, str | None]:
        """Ritorna (bando_id, payload_validato_o_None, db_ok, canonical_action).

        Tutte le uscite hanno 4 elementi: il chiamante spacchetta 4 (fix 8.a.9).
        """
        bando_id = b["id"]
        async with sem:
            try:
                input_ctx = build_bando_input_context(b, catalogo)
            except Exception as e:
                logger.exception("[seo] bando_id={} build_input_context fallito: {}", bando_id, e)
                progress["done"] += 1
                return (bando_id, None, False, None)

            # Testo della pagina UFFICIALE quando esiste (§5): markdown (con
            # ripiego Firecrawl se serve), poi httpx puro. Con la cache per giro
            # di `scarico.py` il secondo tentativo non ripaga un credito.
            link, ufficiale = scegli_fonte(b)
            markdown = ""
            if link:
                try:
                    markdown = await _firecrawl_scrape_markdown(link)
                except Exception:
                    markdown = ""
                if not markdown:
                    try:
                        markdown = await _httpx_fetch_text(link)
                    except Exception:
                        markdown = ""
            # La selezione per sezioni sostituisce il troncamento cieco: titolo e
            # lead ci sono sempre, poi le sezioni con date e parole chiave, e in
            # coda l'elenco deterministico degli allegati.
            righe_link, link_leggibili = _link_del_bando(bando_id)
            markdown = componi_testo(
                markdown, link, ufficiale,
                allegati=[a for a in (b.get("allegati") or []) if isinstance(a, dict)],
            )

            # Skill LLM call + validation
            link_provati, documenti_provati = elenchi_ammessi(
                b, righe_link, link_leggibili=link_leggibili,
            )
            try:
                payload = await enrich_seo(
                    input_ctx, markdown,
                    link_ammessi=link_provati,
                    allegati_ammessi=documenti_provati,
                )
            except Exception as e:
                logger.exception("[seo] bando_id={} enrich_seo fallito: {}", bando_id, e)
                payload = None

            db_ok = False
            canonical_action = None
            if payload and not dry_run:
                # Riga gia' pubblicata (re-run): slug e titolo congelati,
                # stato_processing intatto (vincolo 12: BandoFit legge la riga).
                gia_pubblicato = b.get("stato_processing") == "completed"
                try:
                    db_ok = await update_bando_completed(
                        bando_id, payload, gia_pubblicato=gia_pubblicato,
                    )
                except Exception as e:
                    logger.exception("[seo] bando_id={} update_bando_completed fallito: {}", bando_id, e)
                    db_ok = False
                # v10: dedup cross-source via canonical_key, SOLO dietro la
                # guardia DEDUP_CANONICAL (fix 8.a.10).
                if db_ok and _dedup_canonical_attivo():
                    try:
                        result = await reconcile_canonical_key(bando_id, payload)
                        canonical_action = result.get("action")
                    except Exception as e:
                        logger.warning("[seo] bando_id={} reconcile_canonical_key fallito: {}", bando_id, e)
            elif payload and dry_run:
                db_ok = True  # consideriamo OK in dry-run

            progress["done"] += 1
            if progress["done"] % 25 == 0 or progress["done"] == total:
                logger.info("[seo] progress {}/{}", progress["done"], total)
            return (bando_id, payload, db_ok, canonical_action)

    results = await asyncio.gather(*[_do_one(b) for b in bandi])

    # 4. Counters
    selected = len(bandi)
    payloads_ok = [p for _, p, _, _ in results if p is not None]
    completed_db_ok = sum(1 for _, _, ok, _ in results if ok)
    payload_failed = sum(1 for _, p, _, _ in results if p is None)
    payload_ok_db_failed = sum(1 for _, p, ok, _ in results if p is not None and not ok)
    # v10: dedup cross-source
    canonical_created = sum(1 for _, _, _, ca in results if ca == "created")
    canonical_merged_duplicates = sum(1 for _, _, _, ca in results if ca == "merged_into_master")
    canonical_skipped = sum(1 for _, _, _, ca in results if ca == "skipped")

    livello_flash = sum(1 for p in payloads_ok if p.get("livello") == "flash_bando")
    livello_guida = sum(1 for p in payloads_ok if p.get("livello") == "guida_bando")
    with_link_candidatura = sum(1 for p in payloads_ok if p.get("link_candidatura"))
    with_importo_totale = sum(1 for p in payloads_ok if p.get("importo_totale_eur") is not None)
    with_importo_max = sum(1 for p in payloads_ok if p.get("importo_max_per_progetto_eur") is not None)
    sum_allegati = sum(len(p.get("allegati") or []) for p in payloads_ok)
    sum_tematica = sum(len(p.get("tematica") or []) for p in payloads_ok)

    n_p = len(payloads_ok) or 1
    elapsed = time.monotonic() - started
    counters: dict[str, Any] = {
        "selected": selected,
        "payload_ok": len(payloads_ok),
        "payload_failed": payload_failed,
        "completed_db_ok": completed_db_ok,
        "payload_ok_db_failed": payload_ok_db_failed,
        "canonical_created": canonical_created,
        "canonical_merged_duplicates": canonical_merged_duplicates,
        "canonical_skipped": canonical_skipped,
        "livello_flash": livello_flash,
        "livello_guida": livello_guida,
        "with_link_candidatura": with_link_candidatura,
        "with_importo_totale": with_importo_totale,
        "with_importo_max": with_importo_max,
        "avg_allegati": round(sum_allegati / n_p, 2),
        "avg_tematica": round(sum_tematica / n_p, 2),
        "dry_run": dry_run,
        "elapsed_s": round(elapsed, 1),
    }
    logger.info("[seo] === DONE | {} ===", counters)
    return counters
