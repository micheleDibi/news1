# -*- coding: utf-8 -*-
"""Lotti di backfill una tantum: L7 e L8 del piano (§6.4).

Due comandi, due problemi diversi, una sola regola comune: si passa una volta
sola sul corpus, in ombra per difetto, con `--dry-run` e `--limit` obbligatori,
e ogni giro scrive la propria riga su `pipeline_run` con
`step='backfill:Lx'` — cosi' i crediti e i dollari del backfill non finiscono
nel tetto mensile del regime (§16.2 M19).

`pulisci-contenuto` (L7)
------------------------
Il contenuto editoriale gia' generato contiene 115 segmenti `link` che puntano
all'aggregatore — in almeno 31 casi con l'anchor «scheda ufficiale del bando»,
cioe' l'aggregatore presentato come fonte — e 94 CTA su 230 fanno lo stesso.
Il filtro a render (§7) li nasconde da oggi, ma il dato resta sbagliato in
tabella, e ogni consumatore che non sia la nostra scheda continuerebbe a
leggerli. Qui si sostituiscono **in modo deterministico**, senza modello:

* segmento `link` verso un aggregatore -> la fonte ufficiale se `trovata`,
  altrimenti il segmento si declassa a testo (il testo dell'anchor resta, il
  link sparisce). Mai un link inventato;
* `link_candidatura` verso un aggregatore -> il `bando_link` di tipo
  `candidatura` pubblicabile, altrimenti la fonte ufficiale, altrimenti NULL.
  `link_candidatura_source` segue il valore scelto e resta dentro i tre valori
  che il CHECK in tabella ammette gia' (`extracted`, `fallback_source`,
  `missing`): scriverne un quarto farebbe fallire l'intero UPDATE.

`archivia-processed` (L8)
-------------------------
558 righe sono ferme a `processed` e chiuse: non le vedra' mai nessuno e
continuano a essere ripescate a ogni giro della pipeline. Solo quelle chiuse da
**non piu' di 90 giorni e con la fonte ufficiale trovata** valgono il costo di
enrich + SEO; le altre vanno allo stato terminale `archiviato`. Nessuna riga
viene ricreata, nessun id riusato e — la regola che questo modulo non puo'
violare — **nessuna riga pubblicata viene toccata**: la selezione le esclude e
`destinazione()` le esclude una seconda volta.

Niente qui solleva: un lotto e' un comando che gira su 2 000 righe, e una
riga storta non deve fermare le altre.
"""
from __future__ import annotations

import time
from datetime import date as date_cls
from typing import Any, Awaitable, Callable, Mapping, Sequence

from . import bilancio, telemetria
from .dominio_ufficiale import dominio_di, e_aggregatore
from .eventi import (
    SORGENTE_CANDIDATURA_ASSENTE,
    SORGENTE_CANDIDATURA_FONTE,
    SORGENTE_CANDIDATURA_LINK,
)
from .logger import logger
from .stato_bando import oggi_roma

LOTTO_CONTENUTO = "L7"
LOTTO_PROCESSED = "L8"
STEP_CONTENUTO = "pulisci-contenuto"
STEP_PROCESSED = "archivia-processed"

#: Solo una fonte `trovata` e' un rimpiazzo legittimo di un link
#: all'aggregatore: `in_verifica` e `non_trovata` sono ipotesi, e mettere
#: un'ipotesi dentro il testo pubblicato e' peggio che togliere il link.
STATO_FONTE_TROVATA = "trovata"

#: §6.4 L8: chiuso da non piu' di 90 giorni = vale ancora la lavorazione.
GIORNI_LAVORABILI = 90

DESTINAZIONE_LAVORAZIONE = "lavorazione"
DESTINAZIONE_ARCHIVIO = "archiviato"
DESTINAZIONE_SALTA = "salta"


# --- L7: contenuto e CTA (funzioni pure) ------------------------------------

def _url_aggregatore(url: Any, tabella: Any = None) -> bool:
    """Vero solo per un URL non vuoto il cui host e' in blocklist."""
    if not isinstance(url, str) or not url.strip():
        return False
    return e_aggregatore(dominio_di(url), tabella)


def ripulisci_segmenti(
    segmenti: Any, *, fonte_url: str | None, tabella: Any = None,
) -> tuple[list[Any], int, int]:
    """(segmenti nuovi, sostituiti, declassati) su una lista di segmenti.

    Un segmento che non e' un oggetto passa intatto: il contenuto e' scritto da
    un modello e il backfill non e' il posto dove irrigidire lo schema.
    """
    nuovi: list[Any] = []
    sostituiti = 0
    declassati = 0
    for segmento in segmenti if isinstance(segmenti, list) else []:
        if not isinstance(segmento, Mapping) or segmento.get("kind") != "link":
            nuovi.append(segmento)
            continue
        if not _url_aggregatore(segmento.get("url"), tabella):
            nuovi.append(segmento)
            continue
        voce = dict(segmento)
        if fonte_url:
            voce["url"] = fonte_url
            sostituiti += 1
        else:
            # Il testo dell'anchor resta: toglierlo cancellerebbe una frase
            # scritta per essere letta. Sparisce solo il link.
            voce = {"kind": "text", "text": str(segmento.get("text") or "")}
            declassati += 1
        nuovi.append(voce)
    return nuovi, sostituiti, declassati


def ripulisci_contenuto(
    contenuto: Any, *, fonte_url: str | None = None, tabella: Any = None,
) -> tuple[Any, dict[str, int]]:
    """(contenuto nuovo, contatori) sulle sezioni di un `contenuto` jsonb.

    Attraversa le tre forme che la skill SEO produce — `segments` diretti,
    `items[].segments` delle liste e `items[].a.segments` delle FAQ — e lascia
    tutto il resto dov'e'. Se non c'e' niente da cambiare ritorna **lo stesso
    oggetto**, cosi' il chiamante puo' distinguere «pulito» da «ripulito» senza
    confrontare due dizionari.
    """
    conto = {"sostituiti": 0, "declassati": 0}
    if not isinstance(contenuto, Mapping):
        return contenuto, conto
    sezioni = contenuto.get("sections")
    if not isinstance(sezioni, list):
        return contenuto, conto

    nuove: list[Any] = []
    for sezione in sezioni:
        if not isinstance(sezione, Mapping):
            nuove.append(sezione)
            continue
        voce = dict(sezione)
        if isinstance(sezione.get("segments"), list):
            voce["segments"], a, b = ripulisci_segmenti(
                sezione["segments"], fonte_url=fonte_url, tabella=tabella)
            conto["sostituiti"] += a
            conto["declassati"] += b
        if isinstance(sezione.get("items"), list):
            voce["items"] = [
                _ripulisci_voce(v, fonte_url=fonte_url, tabella=tabella, conto=conto)
                for v in sezione["items"]
            ]
        nuove.append(voce)

    if not conto["sostituiti"] and not conto["declassati"]:
        return contenuto, conto
    return dict(contenuto, sections=nuove), conto


def _ripulisci_voce(
    voce: Any, *, fonte_url: str | None, tabella: Any, conto: dict[str, int],
) -> Any:
    """Una voce di lista (`{segments}`) o di FAQ (`{q, a:{segments}}`)."""
    if not isinstance(voce, Mapping):
        return voce
    nuova = dict(voce)
    if isinstance(voce.get("segments"), list):
        nuova["segments"], a, b = ripulisci_segmenti(
            voce["segments"], fonte_url=fonte_url, tabella=tabella)
        conto["sostituiti"] += a
        conto["declassati"] += b
    risposta = voce.get("a")
    if isinstance(risposta, Mapping) and isinstance(risposta.get("segments"), list):
        segmenti, a, b = ripulisci_segmenti(
            risposta["segments"], fonte_url=fonte_url, tabella=tabella)
        nuova["a"] = dict(risposta, segments=segmenti)
        conto["sostituiti"] += a
        conto["declassati"] += b
    return nuova


def scegli_candidatura(
    riga: Mapping[str, Any],
    *,
    candidatura_url: str | None = None,
    tabella: Any = None,
) -> tuple[str | None, str, str]:
    """(url, source, motivo) della CTA dopo la pulizia.

    L'ordine e' quello di §5: il `bando_link` di tipo `candidatura` verificato,
    altrimenti la fonte ufficiale `trovata`, altrimenti nessun pulsante. Un
    aggregatore non e' mai un ripiego — e' proprio il difetto che il lotto
    toglie — e `link_bando` non entra affatto nella scelta.

    `source` resta dentro i tre valori che il CHECK gia' in tabella ammette:
    un quarto valore farebbe fallire l'intero UPDATE, non solo la colonna.
    """
    attuale = riga.get("link_candidatura")
    attuale = attuale if isinstance(attuale, str) and attuale.strip() else None
    sorgente = str(riga.get("link_candidatura_source") or "")
    fonte = riga.get("fonte_ufficiale_url")
    fonte = fonte if isinstance(fonte, str) and fonte.strip() else None
    trovata = str(riga.get("fonte_ufficiale_stato") or "") == STATO_FONTE_TROVATA

    if candidatura_url and not _url_aggregatore(candidatura_url, tabella):
        return candidatura_url, SORGENTE_CANDIDATURA_LINK, "bando_link candidatura"
    if attuale and not _url_aggregatore(attuale, tabella):
        # Gia' buona: resta com'e', ma la `source` va riallineata quando mente
        # (sono le 28 incoerenze «URL valorizzato con source=missing»).
        corretta = (
            sorgente if sorgente in (SORGENTE_CANDIDATURA_LINK, SORGENTE_CANDIDATURA_FONTE)
            else SORGENTE_CANDIDATURA_FONTE
        )
        motivo = "" if corretta == sorgente else "source incoerente"
        return attuale, corretta, motivo
    if trovata and fonte:
        return fonte, SORGENTE_CANDIDATURA_FONTE, "fonte ufficiale"
    return None, SORGENTE_CANDIDATURA_ASSENTE, "nessun link pubblicabile"


def payload_pulizia(
    riga: Mapping[str, Any],
    *,
    candidatura_url: str | None = None,
    tabella: Any = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """(payload da scrivere, contatori) per una riga. Payload vuoto = niente da fare."""
    fonte = riga.get("fonte_ufficiale_url")
    fonte = fonte if isinstance(fonte, str) and fonte.strip() else None
    if str(riga.get("fonte_ufficiale_stato") or "") != STATO_FONTE_TROVATA:
        fonte = None

    contenuto, conto = ripulisci_contenuto(
        riga.get("contenuto"), fonte_url=fonte, tabella=tabella)
    payload: dict[str, Any] = {}
    if conto["sostituiti"] or conto["declassati"]:
        payload["contenuto"] = contenuto

    url, sorgente, motivo = scegli_candidatura(
        riga, candidatura_url=candidatura_url, tabella=tabella)
    attuale = riga.get("link_candidatura") or None
    # `source` NULL e `source='missing'` dicono la stessa cosa: trattarle come
    # diverse riscriverebbe 1 900 righe per cambiare NULL in «missing».
    sorgente_attuale = str(riga.get("link_candidatura_source") or SORGENTE_CANDIDATURA_ASSENTE)
    if url != attuale or sorgente != sorgente_attuale:
        payload["link_candidatura"] = url
        payload["link_candidatura_source"] = sorgente
        conto["cta"] = 1
        if motivo:
            logger.debug("[pulisci-contenuto] bando {}: CTA {}", riga.get("id"), motivo)
    return payload, conto


# --- L8: destinazione di un `processed` (funzione pura) ---------------------

def _data(valore: Any) -> date_cls | None:
    if isinstance(valore, date_cls):
        return valore
    if isinstance(valore, str) and len(valore) >= 10:
        try:
            return date_cls.fromisoformat(valore[:10])
        except ValueError:
            return None
    return None


def destinazione(
    riga: Mapping[str, Any],
    *,
    oggi: date_cls | None = None,
    giorni: int = GIORNI_LAVORABILI,
) -> tuple[str, str]:
    """(destinazione, motivo) di una riga del lotto L8.

    Tre esiti soltanto: `lavorazione` (vale ancora enrich + SEO), `archiviato`
    (ramo terminale) e `salta` — che comprende **ogni** riga pubblicata e ogni
    riga che non sia `processed`. La riga pubblicata e' il caso che conta: il
    comando non deve poter spubblicare niente, e la selezione da sola non
    basta come garanzia.
    """
    if riga.get("pubblicato"):
        return DESTINAZIONE_SALTA, "riga pubblicata"
    stato = str(riga.get("stato_processing") or "")
    if stato != "processed":
        return DESTINAZIONE_SALTA, f"stato_processing={stato or 'ignoto'}"

    giorno = oggi or oggi_roma()
    scadenza = _data(riga.get("data_scadenza"))
    chiuso_per_stato = str(riga.get("stato_bando") or "").lower() == "chiuso"
    if scadenza is None:
        if not chiuso_per_stato:
            # Senza scadenza e senza stato chiuso non si puo' dire che sia
            # finito: resta dov'e' e lo lavora la pipeline normale. Archiviare
            # per il solo fatto che la data manca chiuderebbe righe vive.
            return DESTINAZIONE_SALTA, "senza scadenza e non chiuso"
        # Chiuso ma senza data: non e' databile, quindi non puo' entrare nella
        # corsia dei «chiusi da <= 90 giorni». Ramo terminale.
        return DESTINAZIONE_ARCHIVIO, "chiuso senza scadenza"
    if scadenza >= giorno and not chiuso_per_stato:
        return DESTINAZIONE_SALTA, "ancora aperto"

    eta = (giorno - scadenza).days
    trovata = str(riga.get("fonte_ufficiale_stato") or "") == STATO_FONTE_TROVATA
    if eta <= giorni and trovata:
        return DESTINAZIONE_LAVORAZIONE, f"chiuso da {eta} giorni con fonte"
    if eta <= giorni:
        return DESTINAZIONE_ARCHIVIO, f"chiuso da {eta} giorni senza fonte"
    return DESTINAZIONE_ARCHIVIO, f"chiuso da {eta} giorni"


# --- runner comune ----------------------------------------------------------

def _attivo(attivo: bool | None) -> bool:
    """Ombra per difetto; `--ombra` (False esplicito) vince sull'ambiente.

    `None` e' «l'operatore non ha detto niente»: decide `MONITOR_MODALITA`.
    `False` e' «ha scritto `--ombra`», e allora non si scrive comunque: una
    variabile d'ambiente non puo' annullare cio' che l'operatore ha scritto
    per iscritto sulla riga di comando (vincolo 3).
    """
    if attivo is not None:
        return bool(attivo)
    try:
        from .settings import get_settings
        return get_settings().monitor_modalita == "attivo"
    except Exception:
        return False


def _tetti() -> bilancio.Tetti:
    """I tetti del lotto. Senza impostazioni leggibili, nessun tetto (0)."""
    try:
        from .settings import get_settings
        return bilancio.tetti_da_impostazioni(get_settings())
    except Exception as e:                                # pragma: no cover - ripiego
        logger.info("[backfill] tetti non leggibili ({}): giro senza tetti", e)
        return bilancio.Tetti()


def _scrivi_run(step: str, riepilogo: Mapping[str, Any], *, tempo: float) -> None:
    """La riga `pipeline_run` del lotto (M19). Non fa mai fallire il giro."""
    riga = telemetria.PipelineRun(step=step).concludi(
        durata_s=tempo,
        esito=telemetria.esito_da_contatori(
            errori=int(riepilogo.get("errori") or 0),
            interrotto_per_tetto=bool(riepilogo.get("interrotto_per_tetto")),
        ),
        contatori=dict(riepilogo),
        interrotto_per_tetto=bool(riepilogo.get("interrotto_per_tetto")),
    )
    try:
        telemetria.scrivi_pipeline_run(riga)
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[{}] telemetria non scritta: {}", step, e)


def _evento_rettifica(bando_id: Any, conto: Mapping[str, int]) -> dict[str, Any]:
    """`rettifica campo=contenuto` del lotto L7 (§5, §7).

    `in_aggiornamenti=false`: non e' una notizia per il lettore, e' una
    correzione nostra. `leggibile=true` perche' e' proprio il cursore che fa
    invalidare la cache ai consumatori; `verificato=false` perche' non c'e'
    nessuna citazione di una pagina ufficiale a dimostrarla — e il CHECK in
    tabella pretende la prova solo per gli eventi verificati.
    """
    return {
        "bando_id": bando_id,
        "tipo": "rettifica",
        "origine": "pipeline",
        "campo": "contenuto",
        "valore_dopo": {
            "link_sostituiti": int(conto.get("sostituiti") or 0),
            "link_declassati": int(conto.get("declassati") or 0),
            "cta": int(conto.get("cta") or 0),
        },
        "leggibile": True,
        "in_aggiornamenti": False,
        "verificato": False,
        "applicato": True,
    }


# --- L7: `pulisci-contenuto` ------------------------------------------------

async def run_pulisci_contenuto(
    dry_run: bool = False,
    limit: int | None = None,
    attivo: bool | None = None,
    *,
    lotto: str | None = None,
    offset: int = 0,
    righe: Sequence[Mapping[str, Any]] | None = None,
    link: Sequence[Mapping[str, Any]] | None = None,
    tabella_domini: Any = None,
    scrivi: Callable[[Any, dict[str, Any]], Awaitable[bool]] | None = None,
    registra: Callable[[Mapping[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """`pulisci-contenuto`: L7 di §6.4. Zero crediti, zero token, non solleva mai.

    In ombra (il difetto) dice quante righe cambierebbe e quali link
    sostituirebbe, senza toccare niente. In attivo scrive con
    `update_bando_completed(gia_pubblicato=True)`, che tiene congelati `slug` e
    `titolo` e non muove `stato_processing`: nessuna riga puo' uscire dalla
    pubblicazione per colpa di questo comando.

    E proprio perche' non muove `pubblicato` ne' `stato_processing`, **niente**
    fa uscire una riga dalla selezione dopo che e' stata ripulita: il `--limit`
    contava le righe guardate e due lanci di fila ripassavano sugli stessi id
    piu' bassi (lancio 1: cambiati 40; lancio 2: cambiati 0, che somiglia a
    «finito» ed e' invece «ho riletto le stesse 800»). Ora la selezione si
    scorre a pagine e il `--limit` conta le righe che hanno davvero qualcosa da
    cambiare; le altre finiscono in `saltate`, e `attraversate` dice quante ne
    sono state guardate. Il filtro e' puro (si legge dal `contenuto`), quindi
    funziona anche in ombra.
    """
    avvio = time.monotonic()
    lotto = lotto or LOTTO_CONTENUTO
    step = f"backfill:{lotto}"
    scrive = _attivo(attivo) and not dry_run
    contatori = bilancio.Contatori()
    tetti = _tetti()
    conto = {
        "esaminati": 0, "cambiati": 0, "scritti": 0, "sostituiti": 0,
        "declassati": 0, "cta": 0, "attraversate": 0, "saltate": 0,
        "errori": 0, "eventi": 0,
    }
    interrotto = False
    motivo_tetto = ""
    try:
        lavoro = _da_ripulire(
            righe, link, limit=limit, offset=offset,
            tabella_domini=tabella_domini, conto=conto,
        )
        if scrive and scrivi is None:
            from .db import update_bando_completed
            scrivi = _scrittore(update_bando_completed)

        for riga, payload, dettaglio in lavoro:
            verifica = bilancio.verifica(contatori, tetti, step=step)
            if not verifica.consentito:
                interrotto = True
                motivo_tetto = verifica.motivo
                logger.warning("[ALLARME] [{}] {}", STEP_CONTENUTO, verifica.motivo)
                break
            conto["esaminati"] += 1
            conto["sostituiti"] += dettaglio.get("sostituiti", 0)
            conto["declassati"] += dettaglio.get("declassati", 0)
            conto["cta"] += dettaglio.get("cta", 0)
            conto["cambiati"] += 1
            if not scrive:
                continue
            try:
                scritto = bool(await scrivi(riga.get("id"), payload))
            except Exception as e:
                conto["errori"] += 1
                logger.warning("[{}] bando {} non scritto: {}",
                               STEP_CONTENUTO, riga.get("id"), e)
                continue
            if not scritto:
                conto["errori"] += 1
                continue
            conto["scritti"] += 1
            if _registra(registra, _evento_rettifica(riga.get("id"), dettaglio)):
                conto["eventi"] += 1
    except Exception as e:
        logger.error("[{}] lotto {} fallito: {}", STEP_CONTENUTO, lotto, e)
        return {"status": "errore", "step": step, "motivo": str(e), **conto}

    riepilogo = {
        "status": "ok",
        "step": step,
        "lotto": lotto,
        "dry_run": dry_run,
        "attivo": scrive,
        "offset": max(0, int(offset or 0)),
        "interrotto_per_tetto": interrotto,
        "motivo": motivo_tetto,
        "saltato_per_lock": False,
        **conto,
        "durata_s": round(time.monotonic() - avvio, 1),
    }
    _scrivi_run(step, riepilogo, tempo=time.monotonic() - avvio)
    logger.info("[{}] {}", STEP_CONTENUTO, riepilogo)
    return riepilogo


# --- L8: `archivia-processed` -----------------------------------------------

async def run_archivia_processed(
    dry_run: bool = False,
    limit: int | None = None,
    attivo: bool | None = None,
    *,
    lotto: str | None = None,
    offset: int = 0,
    righe: Sequence[Mapping[str, Any]] | None = None,
    archivia: Callable[[Any], Mapping[str, Any]] | None = None,
    oggi: date_cls | None = None,
) -> dict[str, Any]:
    """`archivia-processed`: L8 di §6.4. Non solleva mai, non spubblica mai.

    Le righe che valgono ancora enrich + SEO (chiuse da <= 90 giorni e con
    fonte ufficiale trovata) vengono soltanto **contate ed elencate**: le
    lavorano `risolvi-fonte`, `enrich` e `seo`, ognuno con i propri tetti. Qui
    si chiude solo il ramo terminale.

    Il `--limit` conta le **archiviazioni**, non le occhiate: le righe che
    restano `processed` per sempre (saltate e lavorabili) stanno in testa
    all'ordinamento per `id` e prima riconsumavano il limite a ogni lancio —
    su 558 righe con `--limit 100` l'avanzamento era di una trentina di righe
    per giro e si fermava del tutto quando le righe appiccicose in testa
    arrivavano a cento. Ora la selezione si scorre (`--offset N` per lanciare
    un blocco preciso) e `attraversati` dice quante righe sono state guardate.
    """
    avvio = time.monotonic()
    lotto = lotto or LOTTO_PROCESSED
    step = f"backfill:{lotto}"
    scrive = _attivo(attivo) and not dry_run
    giorno = oggi or oggi_roma()
    conto = {
        "esaminati": 0, "archiviabili": 0, "archiviati": 0,
        "lavorabili": 0, "saltati": 0, "attraversati": 0, "errori": 0,
    }
    da_lavorare: list[Any] = []
    degradato = ""
    try:
        elenco = _da_archiviare(
            righe, limit=limit, offset=offset, oggi=giorno,
            conto=conto, da_lavorare=da_lavorare,
        )
        if scrive and archivia is None:
            from .db import archivia_bando
            archivia = archivia_bando

        for riga in elenco:
            conto["esaminati"] += 1
            conto["archiviabili"] += 1
            if not scrive:
                continue
            try:
                esito = archivia(riga.get("id"))
            except Exception as e:
                conto["errori"] += 1
                logger.warning("[{}] bando {} non archiviato: {}",
                               STEP_PROCESSED, riga.get("id"), e)
                continue
            if isinstance(esito, Mapping) and not esito.get("scritto"):
                conto["saltati"] += 1
                if esito.get("saltato") == "colonne_assenti":
                    # La migrazione 01 non c'e': `archiviato` non e' ancora
                    # ammesso dal CHECK e **nessuna** riga potra' essere
                    # scritta. Proseguire significherebbe contare 558 «saltati»
                    # e restituire un giro verde che non ha fatto niente.
                    degradato = "colonne_assenti"
                    logger.warning(
                        "[{}] migrazione 01 non applicata: giro interrotto "
                        "invece di attraversare il corpus a vuoto", STEP_PROCESSED)
                    break
                continue
            conto["archiviati"] += 1
    except Exception as e:
        logger.error("[{}] lotto {} fallito: {}", STEP_PROCESSED, lotto, e)
        return {"status": "errore", "step": step, "motivo": str(e), **conto}

    if da_lavorare:
        # Gli id servono a chi lancia `risolvi-fonte`/`enrich`/`seo` sul
        # residuo: dire «150» senza dire quali non basta a nessuno.
        logger.info("[{}] da lavorare (enrich + seo): {}", STEP_PROCESSED, da_lavorare)
    riepilogo = {
        "status": "ok",
        "step": step,
        "lotto": lotto,
        "dry_run": dry_run,
        "attivo": scrive,
        "offset": max(0, int(offset or 0)),
        "interrotto_per_tetto": False,
        "saltato_per_lock": False,
        **conto,
        "ids_lavorabili": da_lavorare,
        "durata_s": round(time.monotonic() - avvio, 1),
    }
    if degradato:
        # `colonne_assenti` resta una degradazione prevista (exit 0, §16.2):
        # qui si dichiara nel riepilogo, cosi' chi legge `pipeline_run` vede
        # perche' il giro si e' fermato.
        riepilogo["saltato"] = degradato
    _scrivi_run(step, riepilogo, tempo=time.monotonic() - avvio)
    logger.info("[{}] {}", STEP_PROCESSED,
                {k: v for k, v in riepilogo.items() if k != "ids_lavorabili"})
    return riepilogo


# --- confine di I/O ---------------------------------------------------------

#: Quante righe si chiedono per pagina mentre si cerca che cosa lavorare.
#: Non e' il `--limit` dell'operatore: e' la finestra su cui si scorre.
PAGINA_SELEZIONE = 500


def _pagine(
    righe: Sequence[Mapping[str, Any]] | None,
    leggi: Callable[..., Sequence[Mapping[str, Any]]],
    *,
    offset: int,
    passo: str,
) -> Any:
    """Le pagine della selezione, o l'unica pagina iniettata dal chiamante.

    Generatore: chi scorre decide quando fermarsi, e le pagine oltre quella in
    cui il `--limit` si riempie non vengono nemmeno chieste.
    """
    if righe is not None:
        yield [dict(r) for r in righe]
        return
    cursore = max(0, int(offset or 0))
    while True:
        try:
            blocco = list(leggi(limit=PAGINA_SELEZIONE, offset=cursore))
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[{}] lettura della selezione fallita: {}", passo, e)
            return
        if not blocco:
            return
        cursore += len(blocco)
        yield [dict(r) for r in blocco]
        if len(blocco) < PAGINA_SELEZIONE:
            return


def _da_ripulire(
    righe: Sequence[Mapping[str, Any]] | None,
    link: Sequence[Mapping[str, Any]] | None,
    *,
    limit: int | None,
    offset: int,
    tabella_domini: Any,
    conto: dict[str, int],
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, int]]]:
    """Le righe che hanno davvero qualcosa da cambiare, a pagine.

    Ritorna `(riga, payload, dettaglio)` con il payload **gia' calcolato**: e'
    lo stesso lavoro che farebbe il ciclo, e rifarlo raddoppierebbe il costo
    della scansione. Le righe con payload vuoto si contano in `saltate` e non
    consumano il `--limit`; `attraversate` dice quante ne sono state guardate.
    """
    def _leggi(**filtri: Any) -> Sequence[Mapping[str, Any]]:
        from . import db
        return db.select_bandi_pubblicati_contenuto(**filtri)

    raccolte: list[tuple[dict[str, Any], dict[str, Any], dict[str, int]]] = []
    for pagina in _pagine(righe, _leggi, offset=offset, passo=STEP_CONTENUTO):
        # I `bando_link` si chiedono una pagina alla volta: con `--limit 2000`
        # un solo `in_()` diventava una URL PostgREST con duemila id.
        candidature = _candidature(link, [r.get("id") for r in pagina])
        for riga in pagina:
            conto["attraversate"] += 1
            payload, dettaglio = payload_pulizia(
                riga, candidatura_url=candidature.get(riga.get("id")),
                tabella=tabella_domini,
            )
            if not payload:
                conto["saltate"] += 1
                continue
            raccolte.append((riga, payload, dettaglio))
            if limit is not None and len(raccolte) >= limit:
                return raccolte
    return raccolte


def _da_archiviare(
    righe: Sequence[Mapping[str, Any]] | None,
    *,
    limit: int | None,
    offset: int,
    oggi: date_cls,
    conto: dict[str, int],
    da_lavorare: list[Any],
) -> list[dict[str, Any]]:
    """Le sole righe destinate all'archivio, a pagine.

    Solo il ramo `archiviato` fa uscire una riga dalla selezione: `salta` e
    `lavorazione` restano `processed` per sempre e, stando in testa
    all'ordinamento per `id`, riconsumavano il `--limit` a ogni lancio. Qui
    consumano zero: vanno nei rispettivi contatori mentre la scansione
    prosegue, cosi' `--limit 100` significa «cento archiviazioni» e l'elenco
    dei lavorabili copre finalmente tutto il corpus.
    """
    raccolte: list[dict[str, Any]] = []
    for pagina in _pagine(righe, _leggi_processed, offset=offset, passo=STEP_PROCESSED):
        for riga in pagina:
            conto["attraversati"] += 1
            scelta, motivo = destinazione(riga, oggi=oggi)
            if scelta == DESTINAZIONE_SALTA:
                conto["saltati"] += 1
                logger.debug("[{}] bando {} saltato: {}",
                             STEP_PROCESSED, riga.get("id"), motivo)
                continue
            if scelta == DESTINAZIONE_LAVORAZIONE:
                conto["lavorabili"] += 1
                da_lavorare.append(riga.get("id"))
                continue
            raccolte.append(riga)
            if limit is not None and len(raccolte) >= limit:
                return raccolte
    return raccolte


def _leggi_processed(**filtri: Any) -> Sequence[Mapping[str, Any]]:
    from . import db
    return db.select_processed_da_archiviare(**filtri)


def _candidature(
    link: Sequence[Mapping[str, Any]] | None, bando_ids: Sequence[Any],
) -> dict[Any, str]:
    """`bando_id -> url` del solo `bando_link` di tipo `candidatura` pubblicabile.

    Una richiesta per l'intero lotto, non una per bando: a 2 000 righe la
    differenza e' fra un comando che gira e uno che non finisce.
    """
    righe = link
    if righe is None:
        identificativi = [i for i in bando_ids if i is not None]
        if not identificativi:
            return {}
        try:
            from . import db
            righe = db.select_link_da_verificare(bando_ids=identificativi)
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[{}] lettura di bando_link fallita: {}", STEP_CONTENUTO, e)
            return {}
    scelte: dict[Any, str] = {}
    for riga in righe:
        if riga.get("tipo") != "candidatura" or not riga.get("pubblicabile"):
            continue
        url = riga.get("url")
        chiave = riga.get("bando_id")
        if chiave is None or not isinstance(url, str) or not url.strip():
            continue
        scelte.setdefault(chiave, url)
    return scelte


def _scrittore(
    aggiorna: Callable[..., Awaitable[bool]],
) -> Callable[[Any, dict[str, Any]], Awaitable[bool]]:
    """Adattatore di produzione: `slug` e `titolo` restano congelati (§6.2.4)."""
    async def scrivi(bando_id: Any, payload: dict[str, Any]) -> bool:
        return bool(await aggiorna(bando_id, dict(payload), gia_pubblicato=True))
    return scrivi


def _registra(
    registra: Callable[[Mapping[str, Any]], bool] | None, evento: Mapping[str, Any],
) -> bool:
    if registra is not None:
        try:
            return bool(registra(evento))
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[{}] evento non registrato: {}", STEP_CONTENUTO, e)
            return False
    try:
        from . import db
        return bool(db.registra_evento(evento))
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[{}] evento non registrato: {}", STEP_CONTENUTO, e)
        return False


__all__ = [
    "DESTINAZIONE_ARCHIVIO", "DESTINAZIONE_LAVORAZIONE", "DESTINAZIONE_SALTA",
    "GIORNI_LAVORABILI", "LOTTO_CONTENUTO", "LOTTO_PROCESSED",
    "STATO_FONTE_TROVATA", "STEP_CONTENUTO", "STEP_PROCESSED",
    "destinazione", "payload_pulizia", "ripulisci_contenuto",
    "ripulisci_segmenti", "run_archivia_processed", "run_pulisci_contenuto",
    "scegli_candidatura",
]
