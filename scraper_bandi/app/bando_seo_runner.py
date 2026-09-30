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
import functools
import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

from . import bilancio, telemetria
from .db import (
    build_bando_input_context,
    load_catalogo,
    reconcile_canonical_key,
    select_bandi_to_complete,
    update_bando_completed,
)
from .db import controllo, select_link_da_verificare
from .db import rifiuta_doppione, select_pubblicati_per_doppioni_oe
from .gemelli import IndiceDoppioniOE, candidato_oe, doppione_oe, motivo_doppione
from .dominio_ufficiale import e_aggregatore
from .enricher import _firecrawl_scrape_markdown, _httpx_fetch_text
from .impronte import seleziona_sezioni
from .logger import logger
from .seo_skill import (
    DESCRIZIONE_MAX,
    DESCRIZIONE_MIN,
    affermazioni_del_payload,
    affermazioni_non_sostenute,
    degrada_link_non_ammessi,
    normalizza_ammessi,
    enrich_seo,
    fonte_del_bando,
    testo_del_contenuto,
)
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


@dataclass(frozen=True)
class Generazione:
    """Esito di `genera_per_bando`: il payload (None se la SEO e' fallita), il
    testo di pagina passato al modello e le forme di partecipazione che il
    payload afferma senza che la fonte le sostenga (contratto di ottobre, §7).
    """
    payload: dict[str, Any] | None
    markdown: str = ""
    ufficiale: bool = False
    affermazioni: tuple[tuple[str, str], ...] = ()
    #: Gli URL che il gate dei link ha ammesso (None = gate spento): la prova
    #: li salva, l'attivo li riusa per rifare il gate senza rete.
    link_ammessi: tuple[str, ...] | None = None
    #: Perche' `payload` e' None («titolo 88 caratteri (1-80)», …); vuoto se c'e'.
    motivo: str = ""


#: Quanti motivi di scarto entrano nella riga del giro; oltre si contano soli.
TETTO_MOTIVI = 50


def _chiave_id(valore: Any) -> tuple[int, int, str]:
    """Ordine degli id: prima i numeri in ordine numerico (18278 prima di
    1262408), poi il resto come testo."""
    try:
        return (0, int(valore), "")
    except (TypeError, ValueError):
        return (1, 0, str(valore))


def motivi_del_giro(motivi: Mapping[Any, str], tetto: int = TETTO_MOTIVI) -> dict[str, Any]:
    """`payload_failed_motivi` ({id: motivo}, al massimo `tetto` voci) e
    `payload_failed_altri` (quelli rimasti fuori) per i contatori SEO.

    Senza, la riga di `pipeline_run` diceva solo `payload_failed: 1` e il
    perche' del 772894 stava nel journal del server.
    """
    voci = sorted(motivi.items(), key=lambda voce: _chiave_id(voce[0]))
    return {
        "payload_failed_motivi": {str(chiave): motivo for chiave, motivo in voci[:tetto]},
        "payload_failed_altri": max(0, len(voci) - tetto),
    }


async def genera_per_bando(
    b: dict[str, Any],
    input_ctx: dict[str, Any],
    *,
    contatori: bilancio.Contatori | None = None,
    descrizione_facoltativa: bool = False,
) -> Generazione:
    """Testo della pagina, elenchi degli URL ammessi, chiamata alla skill SEO.

    E' il corpo di `_do_one`, fuori dalla chiusura perche' lo usa anche
    `seo-rigenera`. Non scrive niente. `contatori` raccoglie la spesa della
    chiamata: la pipeline non lo passa, e la sua riga di giro resta com'era.
    Titolo e descrizione troppo lunghi si tagliano solo se il bando non e'
    ancora pubblicato (T-C2).
    """
    bando_id = b["id"]
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
    diagnosi: dict[str, Any] = {}
    pubblicato = b.get("stato_processing") == "completed"
    try:
        payload = await enrich_seo(
            input_ctx, markdown,
            link_ammessi=link_provati,
            allegati_ammessi=documenti_provati,
            contatori=contatori,
            # Un pubblicato ha il titolo congelato: non si scrive (rerun dei
            # completed, seo-rigenera), quindi non si taglia e non si giudica.
            ripara_lunghezze=not pubblicato,
            titolo_congelato=pubblicato,
            # Solo `seo-rigenera` (che la descrizione la usa se e quando la
            # riscrive) e solo sui pubblicati: il rerun dei completed la
            # scrive sempre, quindi per lui si valida come prima.
            descrizione_facoltativa=descrizione_facoltativa and pubblicato,
            diagnosi=diagnosi,
        )
    except Exception as e:
        logger.exception("[seo] bando_id={} enrich_seo fallito: {}", bando_id, e)
        payload = None
        diagnosi["motivo"] = f"eccezione: {type(e).__name__}: {str(e)[:120]}"
    motivo = "" if payload else str(diagnosi.get("motivo") or "motivo sconosciuto")
    # Il controllo e' un avviso: se si rompe, non deve rompere il `gather` di
    # tutto lo step SEO.
    try:
        affermazioni = affermazioni_del_payload(payload, input_ctx, markdown) if payload else ()
    except Exception as e:                                # pragma: no cover - difesa
        logger.warning("[seo] bando_id={} controllo delle affermazioni fallito: {}", bando_id, e)
        affermazioni = ()
    return Generazione(
        payload, markdown, ufficiale, affermazioni,
        link_ammessi=None if link_provati is None else tuple(link_provati),
        motivo=motivo,
    )


async def escludi_doppioni_oe(
    bandi: Sequence[dict[str, Any]],
    *,
    dry_run: bool = False,
    leggi_pubblicati: Callable[[], Sequence[Mapping[str, Any]]] | None = None,
    rifiuta: Callable[[Any, str], bool] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(bandi da mandare alla SEO, contatori del controllo dei doppioni OE).

    Guarda solo i bandi OE `enriched` non annullati a mano (`gemelli.candidato_oe`);
    le altre fonti passano intatte. Un doppione probabile diventa `rejected` con
    il motivo del §6 (in `dry_run` no), finisce nel journal con i due id ed esce
    dal giro: niente Opus. Mai una fusione.

    Il controllo non ferma mai lo step: se i pubblicati non si leggono, avvisa,
    lo dice nei contatori e lascia passare tutti, come prima del §6.
    """
    contatori: dict[str, Any] = {
        "doppioni_oe": 0, "doppioni_oe_non_scritti": 0, "doppioni_oe_controllo_saltato": False,
        "doppioni_oe_errori": 0,
    }
    candidati = [b for b in bandi if candidato_oe(b)]
    if not candidati:
        return list(bandi), contatori
    try:
        righe = await asyncio.to_thread(leggi_pubblicati or select_pubblicati_per_doppioni_oe)
        indice = IndiceDoppioniOE.da_pubblicati(righe)
    except Exception as e:
        logger.warning("[seo] controllo dei doppioni OE saltato: {}", e)
        contatori["doppioni_oe_controllo_saltato"] = True
        return list(bandi), contatori
    esclusi: set[Any] = set()
    for bando in candidati:
        # Un record strano non deve fermare lo step per tutti: il controllo
        # salta quel bando, che va alla SEO come prima del §6.
        try:
            trovato = doppione_oe(bando, indice)
        except Exception as e:
            contatori["doppioni_oe_errori"] += 1
            logger.warning("[seo] controllo doppioni OE del bando {} non riuscito: {}",
                           bando.get("id"), e)
            continue
        if not trovato:
            continue
        master_id, criterio = trovato
        esclusi.add(bando["id"])
        contatori["doppioni_oe"] += 1
        logger.warning(
            "[seo] doppione OE: bando {} probabile doppione del pubblicato {} ({})",
            bando["id"], master_id, criterio,
        )
        if dry_run:
            continue
        try:
            scritto = await asyncio.to_thread(
                rifiuta or rifiuta_doppione, bando["id"], motivo_doppione(master_id, criterio),
            )
        except Exception as e:
            logger.warning("[seo] rifiuto del doppione OE {} non scritto: {}", bando["id"], e)
            scritto = False
        if not scritto:
            # Fuori dal giro lo stesso: il doppione e' probabile, e pagare Opus
            # per pubblicarlo sarebbe peggio che riprovare il rifiuto al giro dopo.
            contatori["doppioni_oe_non_scritti"] += 1
    return [b for b in bandi if b["id"] not in esclusi], contatori


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
    selezionati = len(bandi)

    # 1-bis. Doppioni ObiettivoEuropa (contratto di ottobre, §6): escono dal
    # giro prima di Opus, e non tornano finche' qualcuno non li annulla a mano.
    bandi, doppioni = await escludi_doppioni_oe(bandi, dry_run=dry_run)
    if not bandi:
        logger.info("[seo] nessun bando da generare dopo il controllo dei doppioni OE")
        return {"selected": selezionati, "elapsed_s": round(time.monotonic() - started, 1),
                **doppioni}

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
    # Bandi il cui testo afferma forme di partecipazione che la fonte non
    # sostiene (contratto di ottobre, §7). Si contano e si scrivono nel
    # journal, ma non bloccano: un bando bloccato resterebbe `enriched` e
    # ripagherebbe Opus a ogni giro, senza tetto ai tentativi.
    non_sostenuti: list[int] = []
    # Perche' ogni bando fallito e' fallito: finisce nella riga del giro.
    motivi: dict[int, str] = {}

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
                motivi[bando_id] = f"contesto non costruito: {type(e).__name__}"
                progress["done"] += 1
                return (bando_id, None, False, None)

            generazione = await genera_per_bando(b, input_ctx)
            payload = generazione.payload
            if payload is None:
                motivi[bando_id] = generazione.motivo
            if generazione.affermazioni:
                non_sostenuti.append(bando_id)
                logger.warning(
                    "[seo] bando_id={} affermazioni non sostenute dalla fonte: {}",
                    bando_id, _descrivi(generazione.affermazioni),
                )

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
    selected = selezionati
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
        "affermazioni_non_sostenute": len(non_sostenuti),
        **doppioni,
        **motivi_del_giro(motivi),
        "dry_run": dry_run,
        "elapsed_s": round(elapsed, 1),
    }
    logger.info("[seo] === DONE | {} ===", counters)
    return counters


# ---------------------------------------------------------------------------
# seo-rigenera (contratto di ottobre, §7)
# ---------------------------------------------------------------------------
#
# Riscrive il testo di schede GIA' pubblicate con il prompt di oggi, in due
# tempi: si paga una volta sola, e si scrive esattamente il testo che Michele
# ha letto (aggiunta al §7 del 30/09). Tre modi:
#
#   * `solo_controllo` — il detector sui testi attuali, senza modello, lock,
#     scritture ne' spesa. La fonte sono i campi grezzi e i beneficiari
#     collegati, non la pagina: la stima e' per eccesso, e serve a dare a
#     Michele un numero prima di spendere;
#   * prova (`--dry-run`, o nessun flag) — chiama Opus e scarica la pagina,
#     quindi SPENDE; stampa vecchio e nuovo con il costo e salva le PROPOSTE in
#     un file JSON (`--uscita`, di default `~/seo-proposte-<data>.json`). Non
#     scrive sul DB, non prende lock e non scrive `pipeline_run`;
#   * attivo (`--attivo --proposte FILE`) — scrive le proposte del file SENZA
#     richiamare il modello: `contenuto`, e `descrizione_breve` quando la prova
#     ha deciso di riscriverla. Salta, contandoli, i bandi non piu' pubblicati,
#     quelli il cui testo e' cambiato dopo la prova (sha256 salvato) e quelli
#     con affermazioni ancora segnalate. Mai altro: slug, titolo, date,
#     importi, stato e junction restano quelli di prima.
#
# Cosa il controllo automatico NON vede: il rilevatore conosce solo le forme di
# partecipazione. Beneficiari e requisiti inventati («enti no profit e del Terzo
# Settore», «sede in Sicilia da almeno tre anni», i casi 1262398, 1262402 e
# 1262412 del 29/09) non si riconoscono in automatico: `--solo-controllo` non li
# conta e il salto «ancora segnalato» non li ferma. Li' contano la regola 18
# del prompt e la lettura della prova prima di `--attivo`.
#
# L'attivo va lanciato solo nella finestra sicura (contratto §9: 12:30-16:30 o
# 19:00-22:30): prende il lock del giro del sender, e un giro che parte mentre
# il comando lavora salta per intero.

#: La riga di `pipeline_run` del comando. Il prefisso `backfill:` la tiene
#: fuori dai consumi di regime (`bilancio.conta_nel_regime`, RIPRESA §5.10):
#: una rigenerazione lanciata la mattina non deve fermare il monitor la sera.
STEP_SEO_RIGENERA = "backfill:seo-rigenera"

#: Il lock e' quello del giro del sender, sotto cui gira lo step SEO e la
#: riscrittura della prosa del monitor: un lock `seo` che il sender non prende
#: non escluderebbe niente. Il proprietario finisce in `:cli`, quindi il sender
#: non lo rilascia mai all'avvio (§8). Un'ora basta per qualche decina di
#: schede; se il processo muore, il lock scade da solo.
LOCK_SEO_RIGENERA = "bandi_pipeline"
PROPRIETARIO_SEO_RIGENERA = "seo-rigenera:cli"
TTL_SEO_RIGENERA_S = 3600

MODO_CONTROLLO = "solo_controllo"
MODO_PROVA = "prova"
MODO_ATTIVO = "attivo"

#: Versione del file delle proposte: l'attivo rifiuta un file di forma diversa.
VERSIONE_PROPOSTE = 3

#: I tre motivi per cui l'attivo salta una proposta: sono anche i contatori.
SALTO_NON_PUBBLICATO = "saltati_non_pubblicati"
SALTO_CAMBIATO = "saltati_cambiati"
SALTO_FORMA = "saltati_forma_non_valida"
SALTO_ALTERATO = "saltati_testo_alterato"
SALTO_LINK = "saltati_link_non_ammessi"
SALTO_NON_SOSTENUTO = "saltati_non_sostenuti"


def _descrivi(affermazioni: Sequence[Sequence[str]]) -> str:
    """`forma singola o associata («in forma singola o associata»), …`."""
    return ", ".join(f"{famiglia} («{parole}»)" for famiglia, parole in affermazioni) or "nessuna"


def motivo_rifiuto(riga: Mapping[str, Any]) -> str | None:
    """Perche' `seo-rigenera` non tocca questa riga, o None se la puo' toccare.

    Si lavora solo sui pubblicati non fusi: un non pubblicato e' affare dello
    step SEO, e un fuso risponde 301 verso il master. La colonna `pubblicato`
    (migrazione 01) vale quando c'e'; altrimenti vale il predicato storico
    `completed AND slug`. `completed` si pretende comunque, perche' e' anche il
    filtro della scrittura (`db.aggiorna_testo_seo`).
    """
    if riga.get("bando_master_id") is not None:
        return f"fuso nel {riga['bando_master_id']}"
    completato = riga.get("stato_processing") == "completed"
    if "pubblicato" in riga:
        pubblicato = bool(riga.get("pubblicato")) and completato
    else:
        pubblicato = completato and bool(riga.get("slug"))
    return None if pubblicato else f"non pubblicato ({riga.get('stato_processing')})"


def testo_scheda(riga: Mapping[str, Any]) -> str:
    """Descrizione breve e testo del contenuto di una scheda, in un pezzo solo."""
    return " ".join((
        str(riga.get("descrizione_breve") or ""),
        testo_del_contenuto(riga.get("contenuto")),
    ))


def contesto_grezzo(riga: Mapping[str, Any], beneficiari: Sequence[str] = ()) -> dict[str, Any]:
    """Il contesto di `--solo-controllo`: i campi grezzi e i nomi dei
    beneficiari collegati, senza le altre junction e senza la pagina."""
    return {
        "titolo_raw": riga.get("titolo_raw"),
        "descrizione_raw": riga.get("descrizione_raw"),
        "raw_data": riga.get("raw_data") or {},
        "beneficiari": list(beneficiari),
    }


def impronta_testo(valore: Any) -> str:
    """sha256 di un testo della scheda, indipendente da come arriva.

    PostgREST restituisce il `contenuto` come oggetto, ma una riga vecchia puo'
    averlo come stringa JSON: le due forme dello stesso testo devono dare la
    stessa impronta, altrimenti l'attivo salterebbe schede mai toccate.
    """
    if isinstance(valore, str):
        try:
            valore = json.loads(valore)
        except ValueError:
            pass
    if valore is None:
        testo = ""
    elif isinstance(valore, str):
        testo = valore
    else:
        testo = json.dumps(valore, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(testo.encode("utf-8")).hexdigest()


def percorso_proposte(
    cartella: Path, adesso: datetime, *, esiste: Callable[[Path], bool] = Path.exists,
) -> Path:
    """`<cartella>/seo-proposte-AAAA-MM-GG.json`, con l'ora in coda se c'e' gia':
    una seconda prova nello stesso giorno non cancella la prima."""
    base = cartella / f"seo-proposte-{adesso.date().isoformat()}.json"
    if not esiste(base):
        return base
    return cartella / f"seo-proposte-{adesso.date().isoformat()}-{adesso:%H%M%S}.json"


def _percorso_predefinito() -> Path:  # pragma: no cover - dipende dalla macchina
    from .stato_bando import adesso_roma
    return percorso_proposte(Path.home(), adesso_roma())


def salva_proposte(percorso: Path, dati: Mapping[str, Any]) -> None:
    """Scrittura atomica del file delle proposte.

    Si riscrive dopo ogni proposta: un'interruzione a meta' lascia sul disco
    quelle gia' pagate invece di buttarle.
    """
    provvisorio = percorso.with_name(percorso.name + ".tmp")
    provvisorio.write_text(
        json.dumps(dati, ensure_ascii=False, indent=1, default=str), encoding="utf-8",
    )
    os.replace(provvisorio, percorso)


def leggi_proposte(percorso: str | Path) -> dict[str, Any]:
    """Il file di una prova. Forma sbagliata -> ValueError con un messaggio."""
    percorso = Path(percorso).expanduser()
    dati = json.loads(percorso.read_text(encoding="utf-8"))
    if (not isinstance(dati, dict) or dati.get("versione") != VERSIONE_PROPOSTE
            or not isinstance(dati.get("proposte"), list)):
        raise ValueError(
            f"{percorso}: non e' un file di proposte di seo-rigenera "
            f"(versione {VERSIONE_PROPOSTE}; un file di una versione precedente va rifatto "
            "con una nuova prova)"
        )
    for voce in dati["proposte"]:
        # La forma del testo si giudica voce per voce (`forma_valida`): una
        # proposta ritoccata male si salta e si conta, senza buttare le altre.
        if (not isinstance(voce, dict) or not isinstance(voce.get("id"), int)
                or not voce.get("sha256_contenuto") or not voce.get("sha256_proposta")):
            raise ValueError(f"{percorso}: proposta malformata: {str(voce)[:120]}")
    return dati


def forma_valida(voce: Mapping[str, Any]) -> bool:
    """Il testo di una proposta rispetta la forma del contratto DB (§3)?

    `contenuto` e' un oggetto `{sections: [...]}` con almeno una sezione, ogni
    sezione un oggetto con il suo `type`; mai una stringa. `descrizione_breve`
    e' None (resta la vecchia) oppure testo di 180-320 caratteri, i limiti
    della skill SEO. Il file delle proposte
    si puo' aprire e ritoccare a mano: senza questo controllo un ritocco
    sbagliato arriverebbe sul sito e a BandoFit.
    """
    contenuto = voce.get("contenuto")
    if not isinstance(contenuto, Mapping):
        return False
    sezioni = contenuto.get("sections")
    if not isinstance(sezioni, list) or not sezioni:
        return False
    if not all(isinstance(s, Mapping) and isinstance(s.get("type"), str) for s in sezioni):
        return False
    descrizione = voce.get("descrizione_breve")
    return descrizione is None or (
        isinstance(descrizione, str)
        and DESCRIZIONE_MIN <= len(descrizione.strip()) <= DESCRIZIONE_MAX
    )


def impronta_proposta(voce: Mapping[str, Any]) -> str:
    """sha256 di cio' che la prova ha deciso: i due testi proposti, la fonte
    su cui sono stati giudicati e gli URL ammessi. Qualunque ritocco a uno di
    questi (a mano, o un file mescolato con un altro) la cambia."""
    return impronta_testo({
        "contenuto": voce.get("contenuto"),
        "descrizione_breve": voce.get("descrizione_breve"),
        "fonte": voce.get("fonte"),
        "link_ammessi": voce.get("link_ammessi"),
    })


def proposta(
    riga: Mapping[str, Any],
    campi: Mapping[str, Any],
    vecchie: Sequence[Sequence[str]],
    nuove: Sequence[Sequence[str]],
    usd: float,
    *,
    fonte: str = "",
    link_ammessi: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Una voce del file: cosa scrivere e su quale testo e' stata decisa.

    `fonte` e `link_ammessi` servono all'attivo per RIFARE i controlli senza
    rete e senza modello; `sha256_proposta` lega testi, fonte e link, cosi' un
    ritocco al file non passa (§7: si scrive esattamente il testo provato).
    """
    voce = {
        "id": riga["id"],
        "slug": riga.get("slug"),
        "sha256_contenuto": impronta_testo(riga.get("contenuto")),
        "sha256_descrizione_breve": impronta_testo(riga.get("descrizione_breve")),
        "contenuto": campi["contenuto"],
        # None = la descrizione attuale resta: la prova non l'ha trovata sbagliata.
        "descrizione_breve": campi.get("descrizione_breve"),
        "affermazioni_vecchie": [list(a) for a in vecchie],
        "affermazioni_nuove": [list(a) for a in nuove],
        "costo_usd": round(usd, 6),
        "fonte": fonte,
        "link_ammessi": None if link_ammessi is None else list(link_ammessi),
        # Lo muove il trigger della 01 a ogni cambio pubblico (testi, date,
        # stato): l'attivo lo pretende uguale, quindi un bando cambiato dopo la
        # prova non riceve un testo pensato per il bando di prima (R1).
        "ultimo_cambiamento_at": riga.get("ultimo_cambiamento_at"),
    }
    voce["sha256_proposta"] = impronta_proposta(voce)
    return voce


def campi_della_proposta(voce: Mapping[str, Any]) -> dict[str, Any]:
    """Le colonne che l'attivo scrive per una proposta, e nient'altro."""
    campi: dict[str, Any] = {"contenuto": voce["contenuto"]}
    if voce.get("descrizione_breve") is not None:
        campi["descrizione_breve"] = voce["descrizione_breve"]
    return campi


def motivo_salto(
    voce: Mapping[str, Any], riga: Mapping[str, Any] | None,
) -> tuple[str, str] | None:
    """(contatore, spiegazione) se l'attivo non deve scrivere questa proposta.

    Le condizioni del §7, tutte RIFATTE qui invece di fidarsi del file: il
    bando e' ancora pubblicato; il testo proposto e' quello della prova
    (`sha256_proposta`); ha la forma del contratto DB e la descrizione nei
    limiti; il gate dei link non degrada niente; il bando non e' cambiato dopo
    la prova (`ultimo_cambiamento_at`: testi, date, stato) e il testo a DB e'
    quello della prova (anche la descrizione, se la si riscrive); il testo
    nuovo non afferma forme di partecipazione assenti dalla fonte salvata.
    """
    if riga is None:
        return SALTO_NON_PUBBLICATO, "non si trova piu' a DB"
    rifiuto = motivo_rifiuto(riga)
    if rifiuto:
        return SALTO_NON_PUBBLICATO, rifiuto
    if impronta_proposta(voce) != voce.get("sha256_proposta"):
        return SALTO_ALTERATO, "testo proposto diverso da quello della prova (sha256)"
    if not forma_valida(voce):
        return SALTO_FORMA, ("testo proposto fuori forma (contenuto senza sections, "
                             "o descrizione fuori da 180-320)")
    _pulito, degradati = degrada_link_non_ammessi(
        voce.get("contenuto"), normalizza_ammessi(voce.get("link_ammessi")),
    )
    if degradati:
        return SALTO_LINK, f"{degradati} link del testo proposto non ammessi dal gate"
    salvato = voce.get("ultimo_cambiamento_at")
    if salvato is not None and riga.get("ultimo_cambiamento_at") != salvato:
        return SALTO_CAMBIATO, "bando cambiato dopo la prova (date, stato o testi)"
    if impronta_testo(riga.get("contenuto")) != voce.get("sha256_contenuto"):
        return SALTO_CAMBIATO, "contenuto cambiato dopo la prova"
    if (voce.get("descrizione_breve") is not None
            and impronta_testo(riga.get("descrizione_breve")) != voce.get("sha256_descrizione_breve")):
        return SALTO_CAMBIATO, "descrizione_breve cambiata dopo la prova"
    nuove = affermazioni_non_sostenute(
        testo_scheda(campi_della_proposta(voce)), str(voce.get("fonte") or ""),
    )
    if nuove:
        return SALTO_NON_SOSTENUTO, f"testo nuovo ancora segnalato: {_descrivi(nuove)}"
    return None


def _beneficiari_per_bando(
    ids: Sequence[Any], catalogo: Mapping[str, Any],
) -> dict[Any, list[str]]:  # pragma: no cover - I/O
    from .db import select_junction_per_bandi
    nomi = {r.get("id"): r.get("nome") for r in catalogo.get("beneficiari", [])}
    collegati = select_junction_per_bandi("bando_beneficiari", "beneficiario_id", ids)
    return {
        bando_id: [nomi[i] for i in fk if nomi.get(i)]
        for bando_id, fk in collegati.items()
    }


def _scrivi_su_db(
    bando_id: Any, campi: dict[str, Any], *, ultimo_cambiamento_at: Any | None = None,
) -> bool:  # pragma: no cover - I/O
    from .db import aggiorna_testo_seo
    return aggiorna_testo_seo(bando_id, campi, ultimo_cambiamento_at=ultimo_cambiamento_at)


def _leggi_righe(ids: Sequence[Any]) -> list[dict[str, Any]]:  # pragma: no cover - I/O
    from .db import select_bandi_per_rigenera_seo
    return select_bandi_per_rigenera_seo(ids)


def _modello_seo() -> str:
    try:
        return get_settings().seo_model
    except Exception:                                     # pragma: no cover - ripiego
        return ""


def _stampa_confronto(
    stampa: Callable[[str], None],
    riga: Mapping[str, Any],
    generazione: Generazione,
    campi: Mapping[str, Any],
    vecchie: Sequence[Sequence[str]],
    nuove: Sequence[Sequence[str]],
    usd: float,
) -> None:
    payload = generazione.payload or {}
    fonte = "pagina ufficiale" if generazione.ufficiale else "testo dell'aggregatore o nessuna pagina"
    riscritta = "descrizione_breve" in campi
    stampa(f"=== bando {riga.get('id')} · {riga.get('slug')} · fonte letta: {fonte}")
    stampa(f"forme di partecipazione non sostenute — vecchio: {_descrivi(vecchie)}"
           f" | nuovo: {_descrivi(nuove)}")
    stampa("--- descrizione_breve, vecchia")
    stampa(str(riga.get("descrizione_breve") or ""))
    stampa("--- descrizione_breve, nuova " + ("(si riscrive)" if riscritta else "(resta la vecchia)"))
    stampa(str(payload.get("descrizione_breve") or ""))
    stampa("--- contenuto, vecchio")
    stampa(testo_del_contenuto(riga.get("contenuto")))
    stampa("--- contenuto, nuovo")
    stampa(testo_del_contenuto(payload.get("contenuto")))
    stampa(f"--- costo della chiamata: {usd:.4f} USD")


async def run_seo_rigenera(
    ids: Sequence[Any] = (),
    *,
    dry_run: bool = False,
    attivo: bool = False,
    solo_controllo: bool = False,
    limit: int | None = None,
    uscita: str | Path | None = None,
    proposte: str | Path | Mapping[str, Any] | None = None,
    righe: Sequence[Mapping[str, Any]] | None = None,
    catalogo: Mapping[str, Any] | None = None,
    beneficiari: Mapping[Any, Sequence[str]] | None = None,
    contesto: Callable[[dict[str, Any], Any], dict[str, Any]] | None = None,
    generatore: Callable[..., Awaitable[Generazione]] | None = None,
    scrivi: Callable[[Any, dict[str, Any]], bool] | None = None,
    lock: Any | None = None,
    registra_run: Callable[[Any], Any] | None = None,
    stampa: Callable[[str], None] = print,
) -> dict[str, Any]:
    """`seo-rigenera`: vedi l'intestazione di questa sezione.

    `--dry-run` e' piu' forte di `--attivo` (la riga di comando li rifiuta
    insieme); `limit` conta le schede lavorate, non quelle lette. Gli argomenti
    dopo `proposte` servono ai test: senza, si legge e si scrive il DB vero.
    """
    avvio = time.monotonic()
    scrive = bool(attivo) and not dry_run and not solo_controllo
    modo = MODO_CONTROLLO if solo_controllo else (MODO_ATTIVO if scrive else MODO_PROVA)
    spesa = bilancio.Contatori()
    riepilogo: dict[str, Any] = {
        "status": "ok", "step": STEP_SEO_RIGENERA, "modo": modo,
        "dry_run": dry_run, "attivo": scrive, "richiesti": len(ids),
        "esaminati": 0, "rifiutati": [], "segnalati": 0, "per_famiglia": {},
        "generati": 0, "falliti": 0, "ancora_non_sostenuti": 0, "proposte_salvate": 0,
        "descrizioni_fuori_misura": 0,
        "scritti": 0, "descrizioni_riscritte": 0,
        SALTO_NON_PUBBLICATO: 0, SALTO_CAMBIATO: 0, SALTO_FORMA: 0, SALTO_NON_SOSTENUTO: 0,
        SALTO_ALTERATO: 0, SALTO_LINK: 0,
        "errori": 0, "saltato_per_lock": False, "esiti": [],
    }

    if not scrive:
        try:
            if solo_controllo:
                await _controlla(riepilogo, ids, limit=limit, righe=righe, catalogo=catalogo,
                                 beneficiari=beneficiari, stampa=stampa)
            else:
                percorso = Path(uscita).expanduser() if uscita else _percorso_predefinito()
                riepilogo["uscita"] = str(percorso)
                await _prova(riepilogo, ids, percorso, spesa=spesa, limit=limit, righe=righe,
                             catalogo=catalogo, contesto=contesto, generatore=generatore,
                             stampa=stampa)
        except Exception as e:
            _interrotto(riepilogo, e)
        _concludi(riepilogo, spesa, avvio, registra_run, scrive=False)
        return riepilogo

    # Attivo: prima il file (un file sbagliato non deve prendere il lock),
    # poi il lock, poi le scritture. Nessuna chiamata al modello.
    if proposte is None:
        riepilogo["status"] = "errore"
        riepilogo["motivo"] = "--attivo scrive le proposte di una prova: serve --proposte FILE"
        _concludi(riepilogo, spesa, avvio, registra_run, scrive=False)
        return riepilogo
    try:
        dati = dict(proposte) if isinstance(proposte, Mapping) else leggi_proposte(proposte)
        if not isinstance(proposte, Mapping):
            riepilogo["proposte"] = str(Path(proposte).expanduser())
    except Exception as e:
        _interrotto(riepilogo, e)
        _concludi(riepilogo, spesa, avvio, registra_run, scrive=False)
        return riepilogo

    if lock is None:
        from . import blocco as lock
    preso = lock.acquisisci(LOCK_SEO_RIGENERA, PROPRIETARIO_SEO_RIGENERA, TTL_SEO_RIGENERA_S)
    if not preso.proseguire:
        riepilogo["saltato_per_lock"] = True
        riepilogo["lock"] = LOCK_SEO_RIGENERA
        _concludi(riepilogo, spesa, avvio, registra_run, scrive=True)
        return riepilogo
    try:
        await _scrivi_proposte(riepilogo, dati, ids, limit=limit, righe=righe,
                               scrivi=scrivi, stampa=stampa)
    except Exception as e:
        _interrotto(riepilogo, e)
    finally:
        lock.rilascia(preso)
    _concludi(riepilogo, spesa, avvio, registra_run, scrive=True)
    return riepilogo


def _interrotto(riepilogo: dict[str, Any], errore: Exception) -> None:
    logger.error("[seo-rigenera] interrotto: {}", errore)
    riepilogo["status"] = "errore"
    riepilogo["motivo"] = str(errore)
    riepilogo["errori"] += 1


def _valide(
    riepilogo: dict[str, Any],
    ids: Sequence[Any],
    righe: Sequence[Mapping[str, Any]] | None,
    limit: int | None,
    stampa: Callable[[str], None],
) -> list[dict[str, Any]]:
    """Le righe su cui lavorare; i rifiuti finiscono nel riepilogo e a video."""
    lette = [dict(r) for r in (righe if righe is not None else _leggi_righe(ids))]
    trovati = {r.get("id") for r in lette}
    for mancante in [i for i in ids if i not in trovati]:
        riepilogo["rifiutati"].append({"id": mancante, "motivo": "inesistente"})
    valide: list[dict[str, Any]] = []
    for riga in lette:
        motivo = motivo_rifiuto(riga)
        if motivo:
            riepilogo["rifiutati"].append({"id": riga.get("id"), "motivo": motivo})
        else:
            valide.append(riga)
    for rifiuto in riepilogo["rifiutati"]:
        stampa(f"rifiutato {rifiuto['id']}: {rifiuto['motivo']}")
    if limit is not None:
        valide = valide[:max(0, int(limit))]
    return valide


async def _controlla(
    riepilogo: dict[str, Any],
    ids: Sequence[Any],
    *,
    limit: int | None,
    righe: Sequence[Mapping[str, Any]] | None,
    catalogo: Mapping[str, Any] | None,
    beneficiari: Mapping[Any, Sequence[str]] | None,
    stampa: Callable[[str], None],
) -> None:
    valide = _valide(riepilogo, ids, righe, limit, stampa)
    if beneficiari is None:
        beneficiari = _beneficiari_per_bando(
            [r["id"] for r in valide], catalogo if catalogo is not None else load_catalogo())
    for riga in valide:
        riepilogo["esaminati"] += 1
        fonte = fonte_del_bando(contesto_grezzo(riga, beneficiari.get(riga["id"], ())))
        vecchie = affermazioni_non_sostenute(testo_scheda(riga), fonte)
        if vecchie:
            _segna(riepilogo, vecchie)
            stampa(f"{riga['id']}\t{riga.get('slug')}\t{_descrivi(vecchie)}")
    stampa(
        f"solo controllo: {riepilogo['segnalati']} schede su {riepilogo['esaminati']} "
        "con forme di partecipazione assenti dai campi grezzi. Stima per eccesso: "
        "la pagina ufficiale non e' stata letta, la prova con il modello si'."
    )


async def _prova(
    riepilogo: dict[str, Any],
    ids: Sequence[Any],
    percorso: Path,
    *,
    spesa: bilancio.Contatori,
    limit: int | None,
    righe: Sequence[Mapping[str, Any]] | None,
    catalogo: Mapping[str, Any] | None,
    contesto: Callable[[dict[str, Any], Any], dict[str, Any]] | None,
    generatore: Callable[..., Awaitable[Generazione]] | None,
    stampa: Callable[[str], None],
) -> None:
    valide = _valide(riepilogo, ids, righe, limit, stampa)
    if catalogo is None:
        catalogo = load_catalogo()
    contesto = contesto or build_bando_input_context
    generatore = generatore or genera_per_bando
    from .stato_bando import adesso_roma
    dati: dict[str, Any] = {
        "versione": VERSIONE_PROPOSTE,
        "creato_at": adesso_roma().isoformat(timespec="seconds"),
        "modello": _modello_seo(),
        "ids": list(ids),
        "costo_usd": 0.0,
        "proposte": [],
    }
    # Il file nasce subito: se non si puo' scrivere, ci si ferma PRIMA di
    # spendere la prima chiamata.
    salva_proposte(percorso, dati)
    stampa(f"proposte in {percorso}")
    for riga in valide:
        riepilogo["esaminati"] += 1
        bando_id = riga["id"]
        try:
            input_ctx = contesto(dict(riga), catalogo)
            prima = spesa.usd
            generazione = await generatore(
                dict(riga), input_ctx, contatori=spesa, descrizione_facoltativa=True,
            )
            fonte = fonte_del_bando(input_ctx, generazione.markdown)
            vecchie = affermazioni_non_sostenute(testo_scheda(riga), fonte)
            if vecchie:
                _segna(riepilogo, vecchie)
            if generazione.payload is None:
                riepilogo["falliti"] += 1
                riepilogo["esiti"].append({"id": bando_id, "esito": "fallito"})
                stampa(f"=== bando {bando_id}: SEO fallita ({generazione.motivo}), "
                       "niente da proporre")
                continue
            riepilogo["generati"] += 1
            campi: dict[str, Any] = {"contenuto": generazione.payload["contenuto"]}
            nota_descrizione = ""
            if affermazioni_non_sostenute(str(riga.get("descrizione_breve") or ""), fonte):
                nuova = str(generazione.payload.get("descrizione_breve") or "").strip()
                if DESCRIZIONE_MIN <= len(nuova) <= DESCRIZIONE_MAX:
                    campi["descrizione_breve"] = nuova
                else:
                    # La lunghezza si giudica solo qui, dove la descrizione si
                    # userebbe: fuori misura, la proposta resta senza, e la
                    # vecchia resta sulla scheda.
                    nota_descrizione = (
                        f"descrizione nuova di {len(nuova)} caratteri, fuori da "
                        f"{DESCRIZIONE_MIN}-{DESCRIZIONE_MAX}: resta la vecchia"
                    )
                    riepilogo["descrizioni_fuori_misura"] += 1
                    stampa(f"--- bando {bando_id}: {nota_descrizione}")
            nuove = affermazioni_non_sostenute(testo_scheda(campi), fonte)
            usd = spesa.usd - prima
            _stampa_confronto(stampa, riga, generazione, campi, vecchie, nuove, usd)
            if nuove:
                # Il testo nuovo sbaglia ancora: la proposta si salva perche'
                # Michele la veda, ma l'attivo non la scrivera'.
                riepilogo["ancora_non_sostenuti"] += 1
            voce = proposta(riga, campi, vecchie, nuove, usd, fonte=fonte,
                            link_ammessi=generazione.link_ammessi)
            if nota_descrizione:
                voce["nota_descrizione"] = nota_descrizione
            dati["proposte"].append(voce)
            dati["costo_usd"] = round(spesa.usd, 6)
            salva_proposte(percorso, dati)
            riepilogo["proposte_salvate"] += 1
            riepilogo["esiti"].append({"id": bando_id, "esito": "proposta",
                                       "non_sostenuto": bool(nuove)})
        except Exception as e:
            riepilogo["errori"] += 1
            riepilogo["esiti"].append({"id": bando_id, "esito": "errore", "motivo": str(e)})
            logger.warning("[seo-rigenera] bando_id={} fallito: {}", bando_id, e)
    stampa(f"costo totale di questo lancio: {spesa.usd:.4f} USD ({spesa.chiamate} chiamate)")
    stampa(f"{riepilogo['proposte_salvate']} proposte salvate in {percorso}")
    stampa(f"per scriverle, senza richiamare il modello: seo-rigenera --attivo --proposte {percorso}")


async def _scrivi_proposte(
    riepilogo: dict[str, Any],
    dati: Mapping[str, Any],
    ids: Sequence[Any],
    *,
    limit: int | None,
    righe: Sequence[Mapping[str, Any]] | None,
    scrivi: Callable[[Any, dict[str, Any]], bool] | None,
    stampa: Callable[[str], None],
) -> None:
    voci = [v for v in dati["proposte"] if not ids or v["id"] in ids]
    presenti = {v["id"] for v in dati["proposte"]}
    for mancante in [i for i in ids if i not in presenti]:
        riepilogo["rifiutati"].append({"id": mancante, "motivo": "assente dalle proposte"})
        stampa(f"rifiutato {mancante}: assente dalle proposte")
    if limit is not None:
        voci = voci[:max(0, int(limit))]
    riepilogo["richiesti"] = len(ids) or len(voci)
    lette = righe if righe is not None else _leggi_righe([v["id"] for v in voci])
    per_id = {r.get("id"): dict(r) for r in lette}
    scrivi = scrivi or _scrivi_su_db
    for voce in voci:
        riepilogo["esaminati"] += 1
        bando_id = voce["id"]
        salto = motivo_salto(voce, per_id.get(bando_id))
        if salto:
            contatore, spiegazione = salto
            riepilogo[contatore] += 1
            riepilogo["esiti"].append({"id": bando_id, "esito": contatore, "motivo": spiegazione})
            stampa(f"saltato {bando_id}: {spiegazione}")
            continue
        campi = campi_della_proposta(voce)
        try:
            scritto = await asyncio.to_thread(
                functools.partial(
                    scrivi, bando_id, campi,
                    # Il valore della PROVA, non quello letto adesso: cosi'
                    # anche un cambio arrivato fra la prova e l'attivo, o fra
                    # il controllo e l'UPDATE, ferma la scrittura.
                    ultimo_cambiamento_at=voce.get("ultimo_cambiamento_at"),
                ),
            )
        except AssertionError:
            # Il chokepoint della scrittura ha trovato una chiave vietata:
            # errore di programmazione, il comando si ferma.
            raise
        except Exception as e:
            riepilogo["errori"] += 1
            riepilogo["esiti"].append({"id": bando_id, "esito": "errore", "motivo": str(e)})
            logger.warning("[seo-rigenera] bando_id={} non scritto: {}", bando_id, e)
            continue
        if scritto:
            riepilogo["scritti"] += 1
            riepilogo["descrizioni_riscritte"] += int("descrizione_breve" in campi)
            riepilogo["esiti"].append({"id": bando_id, "esito": "scritto", "campi": sorted(campi)})
            stampa(f"scritto {bando_id}: {', '.join(sorted(campi))}")
        else:
            # Nessuna riga aggiornata: il testo e' cambiato fra il controllo e
            # la scrittura (filtro su `ultimo_cambiamento_at`), o la riga non e'
            # piu' `completed`. In tutti e due i casi non si sovrascrive niente.
            riepilogo[SALTO_CAMBIATO] += 1
            riepilogo["esiti"].append({"id": bando_id, "esito": SALTO_CAMBIATO,
                                       "motivo": "cambiato fra il controllo e la scrittura"})
            stampa(f"saltato {bando_id}: cambiato fra il controllo e la scrittura "
                   "(o non piu' completed)")
    stampa(
        f"scritti {riepilogo['scritti']}, saltati: non pubblicati "
        f"{riepilogo[SALTO_NON_PUBBLICATO]}, cambiati {riepilogo[SALTO_CAMBIATO]}, "
        f"fuori forma {riepilogo[SALTO_FORMA]}, ancora segnalati {riepilogo[SALTO_NON_SOSTENUTO]}, "
        f"alterati {riepilogo[SALTO_ALTERATO]}, link non ammessi {riepilogo[SALTO_LINK]}"
    )


def _segna(riepilogo: dict[str, Any], affermazioni: Sequence[tuple[str, str]]) -> None:
    riepilogo["segnalati"] += 1
    for famiglia, _parole in affermazioni:
        riepilogo["per_famiglia"][famiglia] = riepilogo["per_famiglia"].get(famiglia, 0) + 1


def _concludi(
    riepilogo: dict[str, Any],
    spesa: bilancio.Contatori,
    avvio: float,
    registra_run: Callable[[Any], Any] | None,
    *,
    scrive: bool,
) -> None:
    """Spesa nel riepilogo; riga di `pipeline_run` solo nel modo attivo.

    La prova e il controllo promettono di non scrivere niente, e una riga di
    telemetria e' una scrittura. La spesa della prova resta nel riepilogo e
    nel journal.
    """
    riepilogo["chiamate"] = spesa.chiamate
    riepilogo["usd"] = spesa.usd
    riepilogo["costo_usd"] = spesa.usd
    logger.info("[seo-rigenera] {}", {k: v for k, v in riepilogo.items() if k != "esiti"})
    if not scrive:
        return
    riga = telemetria.PipelineRun(step=STEP_SEO_RIGENERA).concludi(
        durata_s=time.monotonic() - avvio,
        esito=telemetria.esito_da_contatori(
            errori=int(riepilogo.get("errori") or 0),
            saltato_per_lock=bool(riepilogo.get("saltato_per_lock")),
        ),
        contatori={k: v for k, v in riepilogo.items() if k != "esiti"},
        costo_usd=spesa.usd,
        saltato_per_lock=bool(riepilogo.get("saltato_per_lock")),
    )
    try:
        (registra_run or telemetria.scrivi_pipeline_run)(riga)
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[seo-rigenera] telemetria non scritta: {}", e)
