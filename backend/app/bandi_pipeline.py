"""Orchestratore completo del pipeline scraping bandi.

Ordine del giro 3 (contratto `bandi-giro-3` §2; la chiave e' quella di
`state["steps"]`):
   1. discover               — fonti da OpenCoesione → tabella `fonte`
   2. scrape                 — scraping delle fonti → tabella `bando`
   3. domini                 — import completo di IndicePA, solo alle 06 e se
                               nel mese non ce n'e' uno fatto (`domini_dovuto`)
   4. resolver_precoce       — fonte ufficiale dei bandi appena entrati
                               (`fonte_ufficiale.run(modo="precoce")`), cosi'
                               preprocess ed enrich leggono gia' l'ente
   5. preprocess             — validazione + date + stato, sulla fonte ufficiale
   6. enrich                 — FK + junction, sulla fonte ufficiale
   7. resolver               — seconda passata, `modo="nuovi"`
   8. ricontrolli            — fonti `in_verifica`/`non_trovata`, senza limit
   9. verifica_stato_ingresso — fase ingresso di verifica-stato, prima della SEO
  10. seo                    — skill SEO → contenuto editoriale + meta
  11. link_verifica          — `fonte_ufficiale.run_link_verifica`
  12. rielaborazione         — `rielabora_fonte.run`, i pubblicati sulla fonte
  13. monitor                — ricontrollo delle pagine ufficiali
  14. verifica_stato         — fase controlli, dopo il monitor
  15. gemelli                — fusioni dei gemelli certi

I passi 8 e 11-15 sono la manutenzione: girano solo nei giri di
`MONITOR_GIRI` (per difetto tutte e quattro le ore dello scheduler); il giro
di avvio (`boot`) non la fa. Nessun passo ha un tetto sul numero di bandi
(§1): ciascuno ha il proprio tempo, con rotazione. I passi opzionali passano
da `_passo_se_esiste`: un modulo assente vale «saltato, tutto bene».

Giro esplicito (§16.2 M13): `run_bandi_pipeline(giro="06:00")`. Gli step che
girano solo in alcuni giri confrontano `giro` con `settings.monitor_giri`;
`giro=None` (CLI) vale «sempre».

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

Tempi attesi per ciclo: la catena d'ingresso (discover, scrape, preprocess,
enrich, seo) ~80 min; la manutenzione al massimo la somma dei suoi tempi
(`TEMPO_*_S` e `VERIFICA_STATO_TETTO_S`, 4 h con i default), da cui
`LOCK_TTL_S` di 6 ore.
"""
from __future__ import annotations

import functools
import inspect
import os
import sys
import time
from datetime import datetime, timezone
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

from . import lock_orfani as _lock_orfani
from .indexnow import submit_to_indexnow
from .logger import logger

# Nome del lock: uno per l'intera pipeline. Un secondo processo che parta
# mentre il primo e' ancora dentro lo scrape trova la riga e si ferma.
LOCK_PIPELINE = "bandi_pipeline"
# TTL piu' lungo del giro piu' lento possibile: se un processo muore senza
# rilasciare, il lock scade da solo invece di bloccare tutti i giri
# successivi. Giro 3 (§2): la somma dei tempi dei passi della manutenzione
# (4 h con i default) piu' la catena d'ingresso (~80') supera 5 ore nel primo
# giro dopo il deploy, quindi 6 ore, cioe' la distanza fra due giri.
LOCK_TTL_S = 6 * 3600

#: Base degli URL pubblici. `indexnow.submit_to_indexnow` scarta da se' tutto
#: cio' che non comincia cosi', ma comporre l'URL qui e' l'unico modo perche'
#: lo scarto non avvenga mai in silenzio su tutto il lotto.
BASE_PUBBLICA = "https://edunews24.it"
#: Il percorso della scheda di un bando su news1 (`src/pages/bandi/[slug].astro`).
PERCORSO_BANDO = "/bandi"


MODULO_ASSENTE = "modulo_assente"


def _valore_rpc(risposta: Any) -> bool:
    """Il booleano restituito da `lock_rilascia` (true = riga cancellata).

    PostgREST lo incapsula in `.data`, che puo' essere il booleano, una lista o
    un dizionario `{"lock_rilascia": …}`. Qui conta il valore vero: dire
    «rilasciato» quando la RPC non ha cancellato niente (lock gia' scaduto e
    ripreso, proprietario cambiato) farebbe mentire il journal. Pura, senza
    dipendenze: il test la estrae dal sorgente.
    """
    dati = getattr(risposta, "data", risposta)
    if isinstance(dati, list):
        dati = dati[0] if dati else False
    if isinstance(dati, dict):
        dati = dati.get("lock_rilascia", next(iter(dati.values()), False))
    return dati is True or (isinstance(dati, str) and dati.lower() == "true")


def rilascia_lock_orfani(avvio: datetime | None = None) -> dict[str, Any]:
    """All'avvio del sender: rilascia i lock dei suoi processi precedenti morti.

    Le regole stanno in `lock_orfani` (contratto di ottobre, §8); qui c'e' solo
    l'I/O: la lettura di `pipeline_lock` e il rilascio con la RPC
    `lock_rilascia`, mai con un DELETE. La RPC si chiama direttamente, e non
    con `blocco.rilascia`, per leggerne il risultato (`_valore_rpc`). Va
    chiamata prima del giro di boot, quando questo processo non ha ancora preso
    nessun lock. Non solleva: un errore diventa un avviso e il sender parte
    comunque.
    """
    try:
        from app import db as _db  # type: ignore
    except Exception as e:                                # pragma: no cover - difesa
        logger.warning("[bandi_pipeline] lock orfani non controllati: {}", e)
        return {"letti": 0, "rilasciati": [], "falliti": [], "errore": str(e)}

    def _rilascia(nome: str, proprietario: str) -> bool:
        risposta = _db.get_supabase().rpc(
            _blocco.RPC_RILASCIA, {"p_nome": nome, "p_proprietario": proprietario},
        ).execute()
        return _valore_rpc(risposta)

    return _lock_orfani.rilascia_orfani(
        leggi=_db.select_lock,
        rilascia=_rilascia,
        pid_corrente=os.getpid(),
        avvio=avvio or datetime.now(timezone.utc),
        registro=logger,
    )


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
    """La manutenzione (ricontrolli, link, rielaborazione, monitor, verifica,
    gemelli) gira solo alle ore di `MONITOR_GIRI`; da CLI (`giro=None`) gira
    sempre (§16.2 M13), al giro di avvio (`boot`) mai."""
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
        # Anche le funzioni sincrone (il passo `gemelli`): si attende solo cio'
        # che e' davvero attendibile.
        result = fn(**kwargs)
        if inspect.isawaitable(result):
            result = await result
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
            ...            (le chiavi di §2, nell'ordine del giro)
            "gemelli":     {...},
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
        # Giro 2 (§19.8): la whitelist dei domini si rilegge dal DB una volta
        # per giro, non una volta per processo.
        _azzera_tabella_domini()

        # Step 1: discover (no kwargs)
        state["steps"]["discover"] = await _safe_run("discover", _discover_run)

        # Step 2: scrape-bandi (no kwargs)
        state["steps"]["scrape"] = await _safe_run("scrape", _scrape_run)

        # Step 3 (giro 2 §19.8, spostato dal giro 3 §2): l'import COMPLETO di
        # IndicePA, nel giro delle 06 se nel mese di calendario non ce n'e'
        # ancora uno fatto. Prima del resolver precoce, perche' entrambe le
        # passate del resolver vedano gli host nuovi (l'import azzera da se'
        # la tabella in memoria).
        if giro == GIRO_DELLE_06:
            if _import_domini_dovuto():
                state["steps"]["domini"] = await _passo_se_esiste(
                    "domini", "app.fonte_ufficiale", giro=giro,
                    funzione="run_domini_import", scarica_enti=True,
                )
            else:
                state["steps"]["domini"] = {"status": "ok", "saltato": "gia_fatto_nel_mese"}

        # Step 4 (giro 3, §7): il resolver precoce, sui bandi appena entrati
        # (`scraped`/`processed`), con una scadenza provvisoria senza modello:
        # cosi' preprocess ed enrich leggono gia' la pagina dell'ente invece di
        # quella dell'aggregatore. Chi non trova la fonte qui non lascia
        # traccia e lo riprende la passata `nuovi` (step 7). Ogni passata
        # prende il proprio lock (`bandi_resolver`) e scrive la propria riga
        # di `pipeline_run`; come tutti gli step opzionali non solleva mai
        # `SystemExit`: lock occupato e tetto tornano come dati (A15).
        state["steps"]["resolver_precoce"] = await _passo_se_esiste(
            "resolver_precoce", "app.fonte_ufficiale", giro=giro, modo="precoce",
        )

        # Step 5: preprocess (parametri di default: tutti i 'scraped')
        state["steps"]["preprocess"] = await _safe_run("preprocess", _preprocess_run)

        # Step 6: enrich (no kwargs: opera su 'processed')
        state["steps"]["enrich"] = await _safe_run("enrich", _enrich_run)

        # Step 7: la seconda passata del resolver, sulle righe appena arrivate
        # a `enriched` senza fonte, con la scadenza vera del preprocess. Fra
        # enrich e seo, cosi' la skill SEO legge la pagina ufficiale (§5).
        state["steps"]["resolver"] = await _passo_se_esiste(
            "resolver", "app.fonte_ufficiale", giro=giro, modo="nuovi",
        )

        # Step 8: i ricontrolli delle fonti `in_verifica`/`non_trovata`, nei
        # giri di MONITOR_GIRI. Senza `limit` (giro 3, §1 e §7: niente
        # lotti): tutti a ogni giro, in ordine di ultimo controllo, con il
        # solo tetto di tempo `TEMPO_RICONTROLLI_S` e la rotazione. Viene
        # dopo la passata `nuovi`: la manutenzione non ruba la finestra ai
        # bandi del giorno.
        if _giro_previsto(giro):
            state["steps"]["ricontrolli"] = await _passo_se_esiste(
                "ricontrolli", "app.fonte_ufficiale", giro=giro, modo="ricontrolli",
            )
        else:
            state["steps"]["ricontrolli"] = {
                "status": "ok", "saltato": "giro_non_previsto",
            }

        # Step 9 (giro 2, §19.4 §5.10): la fase ingresso di verifica-stato,
        # in ogni giro, prima della SEO: cerca una scadenza ai bandi nuovi che
        # la SEO altrimenti pubblicherebbe «aperti» senza data. Senza modello.
        state["steps"]["verifica_stato_ingresso"] = await _passo_se_esiste(
            "verifica_stato_ingresso", "app.verifica_stato", giro=giro, fase="ingresso",
        )

        # Step 10: seo (opera su 'enriched'). Il giro arriva alla riga di spesa
        # della SEO (giro 3, §4; `bando_seo_runner.run(giro=None)`, M3).
        state["steps"]["seo"] = await _safe_run("seo", _seo_run, giro=giro)

        # Step 11 (giro 3, §10): la verifica delle righe di `bando_link`,
        # senza tetto di numero, con il tempo `TEMPO_LINK_VERIFICA_S`. Dopo la
        # SEO, che scrive le righe dei bandi appena pubblicati.
        if _giro_previsto(giro):
            state["steps"]["link_verifica"] = await _passo_se_esiste(
                "link_verifica", "app.fonte_ufficiale", giro=giro,
                funzione="run_link_verifica",
            )
        else:
            state["steps"]["link_verifica"] = {"status": "ok", "saltato": "giro_non_previsto"}

        # Step 12 (giro 3, §9): la rielaborazione dei pubblicati sulla fonte
        # ufficiale. Prima del monitor: un bando rielaborato ha gia' le date
        # e la scheda nuove quando il monitor ne semina l'impronta.
        if _giro_previsto(giro):
            state["steps"]["rielaborazione"] = await _passo_se_esiste(
                "rielaborazione", "app.rielabora_fonte", giro=giro,
            )
        else:
            state["steps"]["rielaborazione"] = {"status": "ok", "saltato": "giro_non_previsto"}

        # Step 13: monitor delle pagine ufficiali, solo nei giri di MONITOR_GIRI.
        # Dopo la SEO apposta: un bando appena pubblicato ha gia' il suo
        # `contenuto`, quindi la prima impronta che il monitor semina e'
        # quella della pagina vera e non di una riga a meta'.
        # Come il resolver non solleva mai: lock occupato e tetto raggiunto
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

        # Step 14 (giro 2, §11 e §19.10): verifica-stato, fase controlli. Come
        # il monitor, solo nei giri di MONITOR_GIRI. La prosa la riallinea il
        # passo con lo stesso adattatore del monitor; gli slug degli eventi
        # applicati li legge `_slug_da_notificare`.
        if _giro_previsto(giro):
            state["steps"]["verifica_stato"] = await _passo_se_esiste(
                "verifica_stato", "app.verifica_stato", giro=giro, fase="controlli",
                rigenerazione=_rigenerazione_di_produzione(per_verifica=True),
            )
        else:
            state["steps"]["verifica_stato"] = {"status": "ok", "saltato": "giro_non_previsto"}

        # Step 15 (giro 3, §11): le fusioni dei gemelli certi, a ogni giro di
        # MONITOR_GIRI (non piu' solo alle 06). La modalita' la legge il passo
        # (`GEMELLI_MODALITA`): in ombra elenca e conta.
        if _giro_previsto(giro):
            state["steps"]["gemelli"] = await _passo_se_esiste(
                "gemelli", "app.gemelli", giro=giro, funzione="esegui_passo",
            )
        else:
            state["steps"]["gemelli"] = {"status": "ok", "saltato": "giro_non_previsto"}
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
    nome: str, modulo: str, *, giro: str | None, funzione: str = "run", **extra: Any,
) -> dict[str, Any]:
    """Esegue uno step opzionale, o lo dichiara saltato se il modulo non c'e'.

    Modulo assente = `status: ok` (e' la tappa successiva del piano); modulo
    rotto = `status: error`, cosi' `_registra` lo conta fra gli errori e il
    giro risulta `partial` invece di `completed`.

    `extra` sono i parametri del singolo step (il monitor riceve
    `rigenerazione=`, i due adattatori del G7 e i `contatori` del giro):
    restano qui e non nel corpo comune perche' passarli a tutti significherebbe
    offrire al resolver argomenti che non conosce.

    `funzione` e' il nome dell'ingresso nel modulo (`run` per resolver,
    rielaborazione e monitor, `run_domini_import`, `run_link_verifica` ed
    `esegui_passo` per gli altri passi). Uno
    step che non solleva ma dice `status: 'errore'` nei suoi contatori
    (`gemelli`, `verifica_stato`) diventa `status: error` qui: altrimenti un
    guasto interno contava come un giro riuscito e non entrava in
    `passi_non_ok`.
    """
    ingresso = funzione
    funzione, motivo = _passo_opzionale(modulo, ingresso)
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
    esito = await _safe_run(nome, funzione, giro=giro, **extra)
    contatori = esito.get("counters")
    if esito.get("status") == "ok" and isinstance(contatori, dict) \
            and contatori.get("status") == STATUS_ERRORE_INTERNO:
        esito["status"] = "error"
        esito["error"] = "errore interno del passo"
    return esito


#: Il giro dell'import mensile di IndicePA (giro 2 §19.8, giro 3 §12). I
#: gemelli, che fino al giro 2 giravano solo qui, seguono ora `MONITOR_GIRI`.
GIRO_DELLE_06 = "06:00"
#: Il valore di `status` con cui un passo che non solleva dice «guasto».
STATUS_ERRORE_INTERNO = "errore"
#: Gli esiti dell'import di IndicePA che contano come «fatto nel mese»: in
#: ombra anche 'ombra' (altrimenti il foglio si riscaricherebbe ogni mattina),
#: in attivo solo 'ok'.
ESITI_IMPORT_FATTO_OMBRA: tuple[str, ...] = ("ok", "ombra")
ESITI_IMPORT_FATTO_ATTIVO: tuple[str, ...] = ("ok",)


def domini_dovuto(
    adesso_roma: datetime,
    ultimi: list[dict[str, Any]],
    attivo: bool,
) -> bool:
    """Vero se nel mese di calendario di Roma non c'e' un import «fatto». Pura.

    `ultimi` sono le righe `pipeline_run` step='domini' (`avviato_at` e
    `esito`, cioe' `indicepa_esito`). Copre il primo giro delle 06 del mese e
    il primo dopo il deploy; un import fallito si ritenta al giro delle 06
    seguente.
    """
    fatti = ESITI_IMPORT_FATTO_ATTIVO if attivo else ESITI_IMPORT_FATTO_OMBRA
    inizio_mese = adesso_roma.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for riga in ultimi:
        if riga.get("esito") not in fatti:
            continue
        # `lock_orfani.istante`, non `fromisoformat`: su Python 3.10 le frazioni
        # a cinque cifre di PostgREST («…12.87927+00:00») non si leggerebbero, e
        # l'import ripartirebbe ogni mattina.
        quando = _lock_orfani.istante(riga.get("avviato_at"))
        if quando is not None and quando >= inizio_mese:
            return False
    return True


def _import_domini_dovuto() -> bool:
    """`domini_dovuto` con le ultime righe dell'import lette dal DB (solo GET).

    Se la lettura fallisce non si importa: il DB non risponde, e l'import
    fallirebbe comunque. Non solleva.
    """
    try:
        from app import db as _db  # type: ignore
        from app.stato_bando import adesso_roma  # type: ignore
        risposta = (
            _db.get_supabase().table("pipeline_run")
            .select("avviato_at,esito:contatori->>indicepa_esito")
            .eq("step", "domini").order("avviato_at", desc=True).limit(5).execute()
        )
        ultimi = list(getattr(risposta, "data", None) or [])
        # Giro 3 (§3, §12): la scrittura dell'import segue DOMINI_MODALITA,
        # non piu' VERIFICA_STATO_MODALITA.
        modalita = str(getattr(_get_settings(), "domini_modalita", "ombra") or "")
        return domini_dovuto(adesso_roma(), ultimi, modalita.strip().lower() == "attivo")
    except Exception as e:
        logger.warning("[bandi_pipeline] ultimo import dei domini non letto, niente import: {}", e)
        return False


def _azzera_tabella_domini() -> None:
    """Dimentica la whitelist in memoria (`fonte_ufficiale.azzera_tabella_corrente`).

    Non solleva: senza, al peggio il giro usa la tabella letta al giro prima.
    """
    try:
        from app import fonte_ufficiale as _fonte  # type: ignore
        _fonte.azzera_tabella_corrente()
    except Exception as e:
        logger.warning("[bandi_pipeline] whitelist dei domini non azzerata: {}", e)


def _rigenerazione_di_produzione(*, per_verifica: bool = False) -> Callable | None:
    """L'adattatore che porta la prosa in linea con le date nuove (§6.2, §12).

    Gemello di `_rigenerazione_di_produzione` in
    `scraper_bandi/app/__main__.py`: i chiamanti del monitor sono due, e un
    modulo condiviso per tre righe legherebbe la pipeline alla CLI.

    Si costruisce con `MONITOR_MODALITA=attivo` **e** con `MONITOR_TIPI_ATTIVI`
    non vuota: in ombra, una proroga di un tipo attivo cambia `data_scadenza`,
    e senza adattatore la prosa resterebbe con la data vecchia (revisione
    avversaria del 30/09/2026, P1). In ombra senza tipi attivi il monitor non
    applica niente, e costruirlo lascerebbe raggiungibile `scrivi_su_db` da un
    giro che ha promesso di non scrivere. Senza adattatore uno slug le cui date
    sono cambiate **non** finisce in `slug_modificati`: e' la scelta del
    monitor, ed e' quella giusta — notificare a Google una pagina che dice
    ancora la data vecchia e' peggio che tacere.

    `per_verifica` (il passo `verifica_stato`): si costruisce **anche** con
    `VERIFICA_STATO_MODALITA=attivo`, che sostituisce date pure con il monitor
    in ombra (revisione avversaria del 01/10). Al monitor la condizione resta
    la sua: la verifica attiva non gli rende raggiungibile `scrivi_su_db`.
    """
    try:
        impostazioni = _get_settings()
        verifica_attiva = per_verifica and getattr(
            impostazioni, "verifica_stato_modalita", "ombra") == "attivo"
        if (impostazioni.monitor_modalita != "attivo"
                and not getattr(impostazioni, "monitor_tipi_attivi", ())
                and not verifica_attiva):
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
        contatori = _contatori_della_riga(state)
        # Quali step non sono andati, per nome: `errori` li conta e basta, e
        # la sorveglianza deve poter dire «lo stesso passo, due giri di fila».
        contatori["passi_non_ok"] = _passi_non_ok(state)
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


#: Gli step il cui risultato porta elenchi per bando (`proposte`,
#: `ids_da_rigenerare`): nella riga 'pipeline' entrano solo esito, contatori e
#: copertura (giro 3, §1), gli elenchi stanno nelle righe proprie del passo
#: (revisione del 01/10).
PASSI_SOLO_CONTATORI: tuple[str, ...] = ("verifica_stato", "verifica_stato_ingresso")
CHIAVI_PASSI_SOLO_CONTATORI: tuple[str, ...] = ("status", "counters", "copertura")


def _contatori_della_riga(state: dict[str, Any]) -> dict[str, Any]:
    """I contatori dei passi per la riga 'pipeline' di `pipeline_run`. Pura."""
    contatori: dict[str, Any] = {}
    for nome, passo in state.get("steps", {}).items():
        valore = passo.get("counters") or {}
        if nome in PASSI_SOLO_CONTATORI and isinstance(valore, dict):
            valore = {k: valore[k] for k in CHIAVI_PASSI_SOLO_CONTATORI if k in valore}
        elif nome == "rielaborazione" and isinstance(valore, dict):
            # I contatori della rielaborazione sono piatti e restano; l'elenco
            # dei `cambi` (prima/dopo per bando) sta solo nella riga del passo,
            # `backfill:rielaborazione` (revisione #146).
            valore = {k: v for k, v in valore.items() if k not in ("cambi", "proposte")}
        contatori[nome] = valore
    return contatori


def _passi_non_ok(state: dict[str, Any]) -> list[str]:
    """I nomi, ordinati, degli step con `status` diverso da `ok`. Pura.

    Solo i nomi veri degli step, mai il testo dell'errore: la riga di
    `pipeline_run` finisce nel riepilogo per il pannello, e un messaggio
    d'eccezione puo' portarsi dietro host, URL o chiavi.
    """
    passi = state.get("steps") if isinstance(state, dict) else None
    if not isinstance(passi, dict):
        return []
    return sorted(
        str(nome) for nome, passo in passi.items()
        if not isinstance(passo, dict) or passo.get("status") != "ok"
    )


#: Il contatore della riga scritta al posto del giro di boot saltato.
MOTIVO_RIAVVIO_DOPO_CRASH = "riavvio_dopo_crash"


def lock_del_giro_rilasciato(esito: Any, nome: str = LOCK_PIPELINE) -> bool:
    """Vero se `rilascia_lock_orfani` ha rilasciato il lock del giro. Pura.

    Il lock del giro di un processo morto vuol dire che il processo precedente
    e' morto a meta' giro (crash, OOM, `systemctl restart` durante un giro).
    Ripartire subito con un giro di boot rifarebbe lo stesso lavoro nello
    stesso stato, e con `Restart=on-failure` un giro che fa cadere il processo
    diventerebbe un ciclo di riavvii. Contano solo i `rilasciati`: un rilascio
    fallito lascia il lock preso, e il giro di boot si salta da solo per lock.
    """
    if not isinstance(esito, dict):
        return False
    rilasciati = esito.get("rilasciati")
    if not isinstance(rilasciati, list):
        return False
    return any(isinstance(voce, dict) and voce.get("nome") == nome for voce in rilasciati)


def registra_avvio_saltato(
    motivo: str = MOTIVO_RIAVVIO_DOPO_CRASH,
    *,
    giro: str = "boot",
) -> None:
    """Riga di `pipeline_run` per il giro di boot NON eseguito. Non solleva mai.

    Senza questa riga un riavvio dopo un crash non lascerebbe traccia nel DB, e
    la sorveglianza non potrebbe contare i riavvii ripetuti. L'esito e' quello
    di un giro saltato; i contatori dicono perche'. `giro` arriva dal sender
    (`GIRO_BOOT`): importarlo da qui sarebbe un import circolare.
    """
    try:
        riga = _telemetria.PipelineRun(step="pipeline", giro=giro).concludi(
            durata_s=0.0,
            esito=_telemetria.esito_da_contatori(saltato_per_lock=True),
            contatori={motivo: 1},
        )
        _telemetria.scrivi_pipeline_run(riga)
    except Exception as e:
        logger.warning("[bandi_pipeline] giro di boot saltato non registrato: {}", e)


# ---------------------------------------------------------------------------
# CLI invocation diretto (utile per test smoke senza scheduler)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio
    giro_cli = sys.argv[1] if len(sys.argv) > 1 else None
    final_state = asyncio.run(run_bandi_pipeline(giro_cli))
    print(f"\n=== FINAL STATE ===\n{final_state}\n")
