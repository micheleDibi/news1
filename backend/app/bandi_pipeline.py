"""Orchestratore completo del pipeline scraping bandi.

Chaining sequenziale degli step (la numerazione e' quella del piano §16.3.10):
  1. discover       — fonti da OpenCoesione → tabella `fonte`
  2. scrape-bandi   — scraping di ~108 fonti → tabella `bando`
  3. preprocess     — validazione + 3 date + reconciliation stato (Haiku + Sonnet fallback)
  4. enrich         — FK + junction tables (7 LLM call parallele)
  5. resolver       — fonte ufficiale del bando (modulo `app.fonte_ufficiale`):
                      cascata a 5 passi, lock `bandi_resolver` e riga propria in
                      `pipeline_run`; se il modulo manca, lo step e' saltato
  6. seo            — skill SEO (Opus 4.7) → contenuto editoriale + meta
  7. monitor        — ricontrollo delle pagine ufficiali (modulo `app.monitoraggio`):
                      coda per fase, eventi con i gate G1-G9, lock `monitor` e riga
                      propria in `pipeline_run`; se il modulo manca, lo step e' saltato

Giro esplicito (§16.2 M13): `run_bandi_pipeline(giro="06:00")`. Gli step che
girano solo in alcuni giri (il monitor) confrontano `giro` con
`settings.monitor_giri`; `giro=None` (CLI) vale «sempre».

IndexNow (§6.2, §7.5): il giro chiama `submit_to_indexnow` **una volta sola**,
in fondo, con gli `slug_modificati` che gli step hanno restituito — oggi solo il
monitor, e solo in modalita' attiva e solo per le pagine il cui testo e' stato
davvero rigenerato. Nessun modulo gemello: `backend/app/indexnow.py` e' lo
stesso di interpelli e selezione personale, qui si importa e basta.

Scarico (§6.2): il giro apre e chiude il client unico di `app/scarico.py`.
`svuota()` a inizio giro (cache e contatori per GIRO, non per processo) e
`chiudi()` nel `finally`, perche' il sender fa un `asyncio.run` per giro e un
client che sopravvive al proprio event loop rompe il giro successivo.

Lock (§16.2 M14): il giro prende `pipeline_lock` con tre esiti. Occupato →
nessuno step parte e lo stato dice `saltato_per_lock`; lock assente (migrazione
04 non ancora applicata) → si prosegue con un warning. **Nessun `SystemExit`**:
lo solleverebbe attraverso `_safe_run` e `_run_sync`, che catturano solo
`Exception`, e ucciderebbe il sender (§16, A15). Gli exit code 3 (lock) e 4
(tetto) esistono solo in `scraper_bandi/app/__main__.py`.

Importa direttamente le `run()` async di scraper_bandi via manipolazione sys.path.
Niente subprocess (log integrato, traceback Python, niente overhead processo).

Failure handling: ogni step viene wrappato in try/except. Se uno fallisce, il
pipeline CONTINUA con gli step successivi (sono tutti idempotenti e operano
solo sui record nella loro coda). Lo stato per step viene persistito in dict
di sintesi e loggato al termine.

Idempotenza: ogni step opera solo sui record nella propria coda
(stato_processing iniziale). Re-eseguire e' sicuro.

Tempi attesi per ciclo (~80 min totali):
  discover    ~1 min
  scrape      ~20-30 min
  preprocess  ~10 min
  enrich      ~8 min
  seo         ~30 min
"""
from __future__ import annotations

import functools
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# Aggiungi scraper_bandi al sys.path per importare i runner come moduli locali.
_SCRAPER_BANDI = Path(__file__).resolve().parents[2] / "scraper_bandi"
if str(_SCRAPER_BANDI) not in sys.path:
    sys.path.insert(0, str(_SCRAPER_BANDI))

# Import dei 5 step runner. NB: `app` qui si riferisce a scraper_bandi/app
# (grazie all'insert in sys.path sopra). Per non collidere con backend.app
# (questo modulo), li importiamo con alias.
from app.orchestrator import run as _discover_run  # type: ignore
from app.bando_runner import run as _scrape_run  # type: ignore
from app.bando_preprocess_runner import run as _preprocess_run  # type: ignore
from app.bando_enrich_runner import run as _enrich_run  # type: ignore
from app.bando_seo_runner import run as _seo_run  # type: ignore

from app import blocco as _blocco  # type: ignore
from app import scarico as _scarico  # type: ignore
from app import telemetria as _telemetria  # type: ignore
from app.settings import GIRI_SCHEDULER  # type: ignore  # noqa: F401 (riesportato)
from app.settings import get_settings as _get_settings  # type: ignore

from .indexnow import submit_to_indexnow
from .logger import logger

# Nome del lock: uno per l'intera pipeline. Un secondo processo che parta
# mentre il primo e' ancora dentro lo scrape trova la riga e si ferma.
LOCK_PIPELINE = "bandi_pipeline"
# TTL piu' lungo del giro piu' lento misurato (~80 minuti) con margine: se un
# processo muore senza rilasciare, il lock scade da solo invece di bloccare
# tutti i giri successivi.
LOCK_TTL_S = 4 * 3600

#: Base degli URL pubblici. `indexnow.submit_to_indexnow` scarta da se' tutto
#: cio' che non comincia cosi', ma comporre l'URL qui e' l'unico modo perche'
#: lo scarto non avvenga mai in silenzio su tutto il lotto.
BASE_PUBBLICA = "https://edunews24.it"
#: Il percorso della scheda di un bando su news1 (`src/pages/bandi/[slug].astro`).
PERCORSO_BANDO = "/bandi"


MODULO_ASSENTE = "modulo_assente"


def _passo_opzionale(modulo: str, funzione: str = "run") -> tuple[Callable | None, str]:
    """Import protetto di uno step non ancora scritto.

    Ritorna `(funzione, motivo)`: `motivo` e' vuoto se la funzione c'e',
    `MODULO_ASSENTE` se il modulo non e' ancora stato scritto, altrimenti la
    descrizione dell'errore.

    La distinzione conta. Resolver (step 5) e monitor (step 7) arrivano in
    tappe successive e la loro assenza e' attesa: un log INFO e si prosegue.
    Ma un modulo che ESISTE e non si importa (dipendenza mancante, errore a
    import-time, `run` rinominato) e' un guasto: se lo si trattasse allo stesso
    modo, il giro risulterebbe `completed` mentre uno step non e' mai partito e
    del motivo non resterebbe traccia da nessuna parte.
    """
    try:
        modulo_importato = __import__(modulo, fromlist=[funzione])
    except ModuleNotFoundError as e:
        if e.name == modulo or (e.name and modulo.startswith(f"{e.name}.")):
            return None, MODULO_ASSENTE
        logger.exception("[bandi_pipeline] {} non importabile: dipendenza {} mancante", modulo, e.name)
        return None, f"dipendenza mancante: {e}"
    except Exception as e:
        logger.exception("[bandi_pipeline] {} non importabile: {}", modulo, e)
        return None, f"errore di import: {e}"
    esecuzione = getattr(modulo_importato, funzione, None)
    if esecuzione is None:
        logger.error("[bandi_pipeline] {}.{} non esiste", modulo, funzione)
        return None, f"{modulo}.{funzione} non esiste"
    return esecuzione, ""


def _giro_previsto(giro: str | None) -> bool:
    """Il monitor gira solo alle ore di `MONITOR_GIRI`; da CLI (`giro=None`)
    gira sempre (§16.2 M13)."""
    if giro is None:
        return True
    try:
        return giro in _get_settings().monitor_giri
    except Exception:
        return False


async def _safe_run(name: str, fn: Callable, **kwargs) -> dict[str, Any]:
    """Wrap un step async in try/except + timing.

    Ritorna sempre un dict (mai solleva), in modo che il pipeline continui
    con gli step successivi.
    """
    started = time.monotonic()
    logger.info("--- bandi_pipeline: STEP {} START ---", name)
    try:
        result = await fn(**kwargs)
        elapsed = time.monotonic() - started
        logger.info(
            "--- bandi_pipeline: STEP {} OK | elapsed={:.1f}s | counters={} ---",
            name, elapsed, result,
        )
        return {
            "status": "ok",
            "elapsed_s": round(elapsed, 1),
            "counters": result,
        }
    except Exception as e:
        elapsed = time.monotonic() - started
        logger.exception(
            "--- bandi_pipeline: STEP {} FAILED | elapsed={:.1f}s | error={} ---",
            name, elapsed, e,
        )
        return {
            "status": "error",
            "elapsed_s": round(elapsed, 1),
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def run_bandi_pipeline(giro: str | None = None) -> dict[str, Any]:
    """Esegue gli step in sequenza. Continue all'errore (steps idempotenti).

    Args:
        giro: ora pianificata del giro ("06:00"), oppure None se lanciata a mano.

    Ritorna lo stato completo:
        {
          "started_at": ISO,
          "finished_at": ISO,
          "total_elapsed_s": float,
          "giro": str | None,
          "lock": "acquisito" | "occupato" | "assente",
          "status": "completed" | "partial" | "saltato",
          "steps": {
            "discover":    {status, elapsed_s, counters? | error?},
            "scrape":      {...},
            "preprocess":  {...},
            "enrich":      {...},
            "resolver":    {...},
            "seo":         {...},
            "monitor":     {...},
          }
        }
    """
    pipeline_start = time.monotonic()
    state: dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "giro": giro,
        "steps": {},
    }
    logger.info("=" * 80)
    logger.info("=== BANDI PIPELINE START | {} | giro={} ===", state["started_at"], giro)
    logger.info("=" * 80)

    run_telemetria = _telemetria.PipelineRun(step="pipeline", giro=giro)
    proprietario = f"bandi_pipeline@{os.getpid()}"
    lock = _blocco.acquisisci(LOCK_PIPELINE, proprietario, LOCK_TTL_S)
    state["lock"] = lock.esito

    if not lock.proseguire:
        # Occupato: nessuno step parte. Non e' un errore del giro, e' un giro
        # che non serviva: `status` lo dice e il sender continua a vivere.
        state["finished_at"] = datetime.now().isoformat(timespec="seconds")
        state["total_elapsed_s"] = round(time.monotonic() - pipeline_start, 1)
        state["status"] = "saltato"
        state["saltato_per_lock"] = True
        _registra(run_telemetria, state, saltato_per_lock=True)
        logger.warning("=== BANDI PIPELINE SALTATA (lock occupato) | giro={} ===", giro)
        return state

    try:
        # Inizio giro: cache e contatori dello scarico azzerati. Il processo del
        # sender vive per giorni e fa un `asyncio.run` per giro: senza questo la
        # cache sarebbe di processo (una pagina di sei ore fa non e' una prova di
        # niente) e i contatori sommerebbero l'intera vita del processo, facendo
        # scattare i tetti per costruzione.
        _scarico.svuota()

        # Step 1: discover (no kwargs)
        state["steps"]["discover"] = await _safe_run("discover", _discover_run)

        # Step 2: scrape-bandi (no kwargs)
        state["steps"]["scrape"] = await _safe_run("scrape", _scrape_run)

        # Step 3: preprocess (parametri di default: tutti i 'scraped')
        state["steps"]["preprocess"] = await _safe_run("preprocess", _preprocess_run)

        # Step 4: enrich (no kwargs: opera su 'processed')
        state["steps"]["enrich"] = await _safe_run("enrich", _enrich_run)

        # Step 5: resolver della fonte ufficiale — fra enrich e seo, cosi' la
        # skill SEO puo' gia' leggere la pagina ufficiale invece di quella
        # dell'aggregatore (§5). Lo step prende il proprio lock
        # (`bandi_resolver`) e scrive la propria riga di `pipeline_run`: cosi'
        # vale anche quando lo stesso codice parte da `python -m app
        # risolvi-fonte`, dove il lock della pipeline non c'e'. Come tutti gli
        # step opzionali non solleva mai `SystemExit`: lock occupato e tetto
        # raggiunto tornano come chiavi del dizionario (A15).
        state["steps"]["resolver"] = await _passo_se_esiste(
            "resolver", "app.fonte_ufficiale", giro=giro,
        )

        # Step 6: seo (no kwargs: opera su 'enriched')
        state["steps"]["seo"] = await _safe_run("seo", _seo_run)

        # Step 7: monitor delle pagine ufficiali, solo nei giri di MONITOR_GIRI.
        # Dopo la SEO apposta: un bando appena pubblicato ha gia' il suo
        # `contenuto`, quindi la prima impronta che il monitor semina e'
        # quella della pagina vera e non di una riga a meta'.
        # Come lo step 5 non solleva mai: lock occupato e tetto raggiunto
        # tornano come chiavi del dizionario (A15).
        if _giro_previsto(giro):
            state["steps"]["monitor"] = await _passo_se_esiste(
                "monitor", "app.monitoraggio", giro=giro,
                rigenerazione=_rigenerazione_di_produzione(),
                **_adattatori_g7(),
            )
        else:
            logger.info("--- bandi_pipeline: STEP monitor SALTATO (giro {} non previsto) ---", giro)
            state["steps"]["monitor"] = {"status": "ok", "saltato": "giro_non_previsto"}
    finally:
        # Il client HTTP muore con il giro: `asyncio.run` chiude l'event loop
        # subito dopo, e un client sopravvissuto esploderebbe al giro seguente
        # con `RuntimeError: Event loop is closed` (che nessun ritentativo
        # intercetta) su tutte le connessioni rimaste nel pool keep-alive.
        try:
            await _scarico.chiudi()
        except Exception as e:                       # pragma: no cover - difesa
            logger.warning("[bandi_pipeline] chiusura dello scarico fallita: {}", e)
        # Il rilascio sta nel finally: un'eccezione inattesa non deve lasciare
        # il lock preso fino alla scadenza del TTL.
        _blocco.rilascia(lock)

    # IndexNow: fuori dal `finally`, quindi a lock gia' rilasciato. Una POST
    # con timeout di 10 s non deve tenere fermo il lock della pipeline, e gli
    # slug sono gia' scritti a DB: se la notifica fallisce, la pagina resta
    # corretta e il prossimo giro la ripropone.
    state["indexnow"] = _notifica_indexnow(state)

    # Sintesi finale
    state["finished_at"] = datetime.now().isoformat(timespec="seconds")
    state["total_elapsed_s"] = round(time.monotonic() - pipeline_start, 1)
    all_ok = all(s["status"] == "ok" for s in state["steps"].values())
    state["status"] = "completed" if all_ok else "partial"

    logger.info("=" * 80)
    logger.info(
        "=== BANDI PIPELINE {} | finished_at={} | total_elapsed={:.0f}s ===",
        state["status"].upper(), state["finished_at"], state["total_elapsed_s"],
    )
    for step_name, step in state["steps"].items():
        logger.info(
            "  - {:12s} {:>5s} {:>6.0f}s",
            step_name, step["status"], step.get("elapsed_s", 0),
        )
    logger.info("=" * 80)

    _registra(run_telemetria, state)
    return state


async def _passo_se_esiste(
    nome: str, modulo: str, *, giro: str | None, **extra: Any,
) -> dict[str, Any]:
    """Esegue uno step opzionale, o lo dichiara saltato se il modulo non c'e'.

    Modulo assente = `status: ok` (e' la tappa successiva del piano); modulo
    rotto = `status: error`, cosi' `_registra` lo conta fra gli errori e il
    giro risulta `partial` invece di `completed`.

    `extra` sono i parametri del singolo step (il monitor riceve
    `rigenerazione=`, i due adattatori del G7 e i `contatori` del giro):
    restano qui e non nel corpo comune perche' passarli a tutti significherebbe
    offrire al resolver argomenti che non conosce.
    """
    funzione, motivo = _passo_opzionale(modulo)
    if funzione is None:
        if motivo == MODULO_ASSENTE:
            logger.info(
                "--- bandi_pipeline: STEP {} SALTATO ({} non disponibile) ---", nome, modulo,
            )
            return {"status": "ok", "saltato": MODULO_ASSENTE, "modulo": modulo}
        logger.error(
            "--- bandi_pipeline: STEP {} NON PARTITO ({} rotto: {}) ---", nome, modulo, motivo,
        )
        return {"status": "error", "saltato": "modulo_rotto", "modulo": modulo, "error": motivo}
    return await _safe_run(nome, funzione, giro=giro, **extra)


def _rigenerazione_di_produzione() -> Callable | None:
    """L'adattatore che porta la prosa in linea con le date nuove (§6.2, §12).

    Gemello di `_rigenerazione_di_produzione` in
    `scraper_bandi/app/__main__.py`: i chiamanti del monitor sono due, e un
    modulo condiviso per tre righe legherebbe la pipeline alla CLI.

    Si costruisce solo con `MONITOR_MODALITA=attivo`. In ombra il monitor non
    lo chiamerebbe comunque (il gate e' dentro `controlla`), ma costruirlo
    lascerebbe raggiungibile `scrivi_su_db` da un giro che ha promesso di non
    scrivere. Senza adattatore uno slug le cui date sono cambiate **non**
    finisce in `slug_modificati`: e' la scelta del monitor, ed e' quella
    giusta — notificare a Google una pagina che dice ancora la data vecchia e'
    peggio che tacere.
    """
    try:
        if _get_settings().monitor_modalita != "attivo":
            return None
        from app import rigenera as _rigenera  # type: ignore
        return functools.partial(
            _rigenera.rigenera, attivo=True, scrivi=_rigenera.scrivi_su_db)
    except Exception as e:
        # Anche l'AttributeError sta dentro: un pezzo mancante non deve poter
        # far fallire il giro. Senza adattatore il monitor lavora lo stesso e
        # semplicemente non restituisce slug da notificare.
        logger.warning("[bandi_pipeline] rigenerazione non disponibile: {}", e)
        return None


def _adattatori_g7() -> dict[str, Any]:
    """La seconda prova del G7 (§6.2): seconda opinione Sonnet e pagine collegate.

    Gemello di `_adattatori_g7` in `scraper_bandi/app/__main__.py`.

    Senza questi due adattatori il G7 non e' soddisfacibile: il monitor
    respinge **ogni** evento con una transizione di stato o una data, cioe'
    proprio quelli che deve raccogliere, e il riepilogo esce con
    `g7_disponibile=false`. Si costruiscono **anche in ombra**, al contrario
    della rigenerazione: l'ombra serve a misurare la precisione dei gate su
    eventi veri, e un G7 spento misurerebbe un monitor che non esiste.

    Senza `ANTHROPIC_API_KEY` restano `None` e il comportamento resta quello di
    oggi: senza chiave non c'e' nemmeno il classificatore, quindi `controlla`
    esce prima del fetch e le pagine collegate sarebbero GET preparate per
    nessuno.

    `contatori` e' l'oggetto che la seconda opinione usa per
    `bilancio.registra_chiamata` **e** quello che `run()` confronta con i
    tetti: e' lo stesso apposta, altrimenti il costo della conferma non
    entrerebbe nel tetto giornaliero in $.
    """
    vuoto: dict[str, Any] = {
        "contatori": None, "seconda_opinione": None, "pagine_collegate": None,
    }
    try:
        impostazioni = _get_settings()
        if not getattr(impostazioni, "anthropic_api_key", ""):
            logger.info("[bandi_pipeline] ANTHROPIC_API_KEY assente: G7 non soddisfacibile")
            return vuoto
        from app import bilancio as _bilancio            # type: ignore
        from app import monitoraggio as _monitoraggio    # type: ignore
        costruisci_seconda = getattr(
            _monitoraggio, "seconda_opinione_da_impostazioni", None)
        costruisci_collegate = getattr(
            _monitoraggio, "pagine_collegate_da_impostazioni", None)
        if costruisci_seconda is None or costruisci_collegate is None:
            logger.info("[bandi_pipeline] costruttori del G7 non ancora disponibili")
            return vuoto
        contatori = _bilancio.Contatori()
        return {
            "contatori": contatori,
            "seconda_opinione": costruisci_seconda(impostazioni, contatori),
            "pagine_collegate": costruisci_collegate(impostazioni),
        }
    except Exception as e:
        # Come per la rigenerazione: un pezzo mancante non deve poter far
        # fallire il giro. Il monitor lavora lo stesso, con il G7 spento.
        logger.warning("[bandi_pipeline] adattatori del G7 non costruiti: {}", e)
        return vuoto


def _slug_da_notificare(state: dict[str, Any]) -> list[str]:
    """Gli slug che questo giro ha davvero cambiato, senza doppioni.

    Si guardano i contatori di **tutti** gli step, non solo del monitor: oggi
    e' l'unico a restituirli, ma la chiave e' del contratto di `pipeline_run`
    (`telemetria.PipelineRun.slug_modificati`) e un secondo produttore non
    deve costringere a toccare di nuovo questa funzione.
    """
    slug: list[str] = []
    for passo in state.get("steps", {}).values():
        if not isinstance(passo, dict):
            continue
        contatori = passo.get("counters")
        if not isinstance(contatori, dict):
            continue
        for voce in contatori.get("slug_modificati") or ():
            testo = str(voce).strip().strip("/")
            if testo and testo not in slug:
                slug.append(testo)
    return slug


def _notifica_indexnow(state: dict[str, Any]) -> dict[str, Any]:
    """Una sola POST per giro (§7.5). Non solleva mai.

    `submit_to_indexnow` e' gia' fire-and-forget, ma un errore a monte (URL
    non componibile, chiave assente) non deve poter trasformare un giro
    riuscito in un giro fallito: la notifica e' un di piu', la scrittura a DB
    era il lavoro.
    """
    slug = _slug_da_notificare(state)
    if not slug:
        return {"inviati": 0}
    url = [f"{BASE_PUBBLICA}{PERCORSO_BANDO}/{s}" for s in slug]
    try:
        submit_to_indexnow(url)
    except Exception as e:                               # pragma: no cover - difesa
        logger.warning("[bandi_pipeline] IndexNow non notificato: {}", e)
        return {"inviati": 0, "slug": len(slug), "errore": str(e)}
    logger.info("[bandi_pipeline] IndexNow: {} URL notificati", len(url))
    return {"inviati": len(url), "slug": len(slug)}


def _interrotto_per_tetto(state: dict[str, Any]) -> bool:
    """Vero se almeno uno step si e' fermato su un tetto (§6.2).

    Non e' un errore — lo step ha fatto la cosa giusta fermandosi — ma la riga
    di `pipeline_run` deve dirlo, altrimenti un giro dimezzato dai tetti e un
    giro completo si somigliano e `salute` non ha come accorgersi di due giri
    a tetto consecutivi.
    """
    for passo in state.get("steps", {}).values():
        if not isinstance(passo, dict):
            continue
        contatori = passo.get("counters")
        if isinstance(contatori, dict) and contatori.get("interrotto_per_tetto"):
            return True
    return False


def _consumo(state: dict[str, Any]) -> tuple[int, float]:
    """(crediti, dollari) sommati sugli step che li dichiarano.

    Resolver e monitor tengono ciascuno la propria riga di `pipeline_run`; la
    riga del giro somma, cosi' il tetto mensile di §6.2 ha un solo posto da
    leggere invece di tre.
    """
    crediti = 0.0
    dollari = 0.0
    for passo in state.get("steps", {}).values():
        if not isinstance(passo, dict):
            continue
        contatori = passo.get("counters")
        if not isinstance(contatori, dict):
            continue
        crediti += _numero(contatori.get("crediti"))
        dollari += _numero(contatori.get("costo_usd"))
    return int(crediti), round(dollari, 6)


def _numero(valore: Any) -> float:
    """`float(valore)` solo se e' davvero un numero. `True` non vale 1: un
    contatore booleano finito qui per sbaglio non deve diventare un credito."""
    if isinstance(valore, bool) or not isinstance(valore, (int, float)):
        return 0.0
    return float(valore)


def _registra(
    run: "_telemetria.PipelineRun",
    state: dict[str, Any],
    *,
    saltato_per_lock: bool = False,
) -> None:
    """Riga in `pipeline_run` + riepilogo JSON. Non solleva mai: la telemetria
    non deve poter far fallire un giro (le tabelle potrebbero non esistere)."""
    try:
        contatori = {
            nome: passo.get("counters") or {} for nome, passo in state.get("steps", {}).items()
        }
        errori = sum(1 for passo in state.get("steps", {}).values() if passo.get("status") != "ok")
        interrotto = _interrotto_per_tetto(state)
        crediti, dollari = _consumo(state)
        concluso = run.concludi(
            durata_s=float(state.get("total_elapsed_s") or 0.0),
            esito=_telemetria.esito_da_contatori(
                errori=errori,
                interrotto_per_tetto=interrotto,
                saltato_per_lock=saltato_per_lock,
            ),
            contatori=contatori,
            crediti=crediti,
            costo_usd=dollari,
            interrotto_per_tetto=interrotto,
            slug_modificati=tuple(_slug_da_notificare(state)),
            saltato_per_lock=saltato_per_lock,
        )
        logger.info("[bandi_pipeline] riepilogo {}", _telemetria.riepilogo(concluso))
        _telemetria.scrivi_pipeline_run(concluso)
    except Exception as e:
        logger.warning("[bandi_pipeline] telemetria non registrata: {}", e)


# ---------------------------------------------------------------------------
# CLI invocation diretto (utile per test smoke senza scheduler)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio
    giro_cli = sys.argv[1] if len(sys.argv) > 1 else None
    final_state = asyncio.run(run_bandi_pipeline(giro_cli))
    print(f"\n=== FINAL STATE ===\n{final_state}\n")
