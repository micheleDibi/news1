# -*- coding: utf-8 -*-
"""Sorveglianza del produttore dei bandi: `python -m app sorveglia` (contratto `bandi-giro-2` §10).

Perche' esiste
--------------
Michele non vuole notifiche (decisione B del 30/09: niente Telegram, niente
email): al loro posto c'e' il pannello di BandoFit, che legge un riepilogo
neutro con una chiave (`monitoraggio_catalogo`, migrazione 12). Questo modulo
e' chi scrive quel riepilogo: un timer di systemd lo lancia ogni 15 minuti, e
dopo 45 minuti senza una riga nuova il pannello mostra «in ritardo» da solo.

Il giro di `esegui`:
  1. la memoria della volta prima (`db.leggi_memoria_riepilogo`);
  2. la fotografia (`fotografa`): le misure del DB, lo stato del servizio del
     sender letto da systemd, il job orario e la memoria, giudicate da
     `telemetria.salute`;
  3. il riepilogo neutro (`riepilogo_salute.riepilogo_pannello`), validato
     (`valida_v1`); se non passa si scrive il riepilogo minimo e il dettaglio
     va solo nel journal;
  4. l'upsert della riga unica (`db.scrivi_riepilogo_monitoraggio`).

Nessun file di stato (niente StateDirectory, niente flock): la memoria sta
nella riga del riepilogo. Nessuna chiamata di rete oltre a PostgREST del DB
bandi. Exit 0 anche con allarmi (li mostra il pannello); 1 su un errore interno,
se l'upsert fallisce o se il DB non risponde (misure o schema non leggibili):
un DB giu' non deve sembrare «migrazione 12 non applicata».
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from .logger import logger, redigi

#: Il servizio del sender, se `SORVEGLIA_SERVIZIO_SENDER` non dice altro (§12).
#: Resta sul server: non entra mai nel riepilogo.
SERVIZIO_PREDEFINITO = "edunews-bandi-sender"
VARIABILE_SERVIZIO = "SORVEGLIA_SERVIZIO_SENDER"
#: Nomi di unit ammessi: niente spazi, niente caratteri da shell, e il primo
#: carattere alfanumerico, cosi' un valore come «-Hutente@host» non diventa
#: un'opzione di systemctl (in piu' c'e' il `--` prima del nome).
_RE_SERVIZIO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@_.:-]{0,127}$")
TIMEOUT_SYSTEMCTL_S = 5
#: Dopo quanto il pannello considera il riepilogo in ritardo.
INTERVALLO_RITARDO = "45 minutes"
VERSIONE_RIGA = 1
#: La serie di NRestarts in memoria: le ultime 6 ore, al massimo 30 punti.
ORE_MEMORIA_NRESTARTS = 6
MAX_PUNTI_NRESTARTS = 30

#: Valore dei parametri di `fotografa` quando la misura va letta qui.
_DA_LEGGERE: Any = object()


@dataclass(frozen=True)
class Fotografia:
    """Lo `Stato` che `salute` giudica e le misure da cui viene."""
    stato: Any
    misure: Mapping[str, Any] = field(default_factory=dict)
    adesso: datetime | None = None


def _iso(istante: datetime) -> str:
    """ISO 8601 UTC con la Z: la forma di tutti gli istanti del riepilogo."""
    return istante.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nome_servizio() -> str:
    """Il servizio del sender da sorvegliare (`SORVEGLIA_SERVIZIO_SENDER`)."""
    try:
        from .settings import get_settings
        valore = getattr(get_settings(), "sorveglia_servizio_sender", None)
    except Exception:
        valore = None
    return str(valore or os.environ.get(VARIABILE_SERVIZIO) or SERVIZIO_PREDEFINITO).strip()


def stato_servizio(
    nome: str | None = None,
    *,
    esegui: Callable[..., Any] | None = None,
) -> dict[str, Any] | None:
    """`{active_state, sub_state, n_restarts}` del servizio, da systemd.

    `systemctl show -p ActiveState,SubState,NRestarts -- <nome>`, senza shell e
    con un timeout di 5 secondi. None sul Mac (niente systemctl), con un nome non
    valido, un codice d'uscita diverso da 0, un timeout o una risposta senza
    `ActiveState`: il servizio allora e' «non misurato», non «fermo».
    """
    nome = nome if nome is not None else nome_servizio()
    if not _RE_SERVIZIO.match(nome or ""):
        logger.warning("[sorveglia] nome del servizio non valido: stato non misurato")
        return None
    if esegui is None:
        if shutil.which("systemctl") is None:
            return None
        esegui = subprocess.run
    try:
        risultato = esegui(
            ["systemctl", "show", "-p", "ActiveState,SubState,NRestarts", "--", nome],
            capture_output=True, text=True, timeout=TIMEOUT_SYSTEMCTL_S, check=False,
        )
    except Exception as e:
        logger.warning("[sorveglia] systemctl non ha risposto: {}", type(e).__name__)
        return None
    if getattr(risultato, "returncode", 1) != 0:
        return None
    valori: dict[str, str] = {}
    for riga in str(getattr(risultato, "stdout", "") or "").splitlines():
        chiave, _, valore = riga.partition("=")
        valori[chiave.strip()] = valore.strip()
    if not valori.get("ActiveState"):
        return None
    try:
        riavvii: int | None = int(valori.get("NRestarts", ""))
    except ValueError:
        riavvii = None
    return {"active_state": valori["ActiveState"], "sub_state": valori.get("SubState") or None,
            "n_restarts": riavvii}


def fotografa(
    *,
    adesso: datetime | None = None,
    memoria: Any = _DA_LEGGERE,
    servizio: Any = _DA_LEGGERE,
) -> Fotografia:
    """La fotografia che `salute` giudica: la configurazione piu' le misure.

    E' il corpo di `__main__._stato_salute` (che la richiama). Alle misure di
    `db.misure_salute` si aggiungono, PRIMA di `telemetria.stato_da_misure`,
    `servizio` (systemd), `memoria` (la riga del riepilogo) e `job_orario` (la
    RPC di lettura della 12): e' `stato_da_misure` che li mette nei non
    misurati quando mancano. Se il DB non risponde non si solleva: diventa
    l'allarme `misure_non_disponibili`, col messaggio passato da `redigi`, e
    il servizio si giudica lo stesso (e' una lettura locale).
    """
    from .settings import get_settings
    from .telemetria import Stato, stato_da_misure

    impostazioni = get_settings()
    adesso = adesso or datetime.now(tz=timezone.utc)
    if servizio is _DA_LEGGERE:
        servizio = stato_servizio()
    tetti = {"tetto_crediti_mese": impostazioni.tetto_crediti_mese,
             "tetto_usd_mese": impostazioni.tetto_usd_mese}
    try:
        from . import db
        if memoria is _DA_LEGGERE:
            memoria = db.leggi_memoria_riepilogo()
        misure = dict(db.misure_salute(adesso=adesso))
        misure["servizio"] = servizio
        misure["memoria"] = memoria
        misure["job_orario"] = db.job_orario()
        campi = dict(stato_da_misure(misure, adesso=adesso, **tetti))
    except Exception as e:
        misure = {"servizio": servizio, "memoria": None if memoria is _DA_LEGGERE else memoria}
        try:
            campi = dict(stato_da_misure(misure, adesso=adesso, **tetti))
        except Exception:                                  # pragma: no cover - difesa
            campi = {}
        campi["misure_db_errore"] = redigi(f"{type(e).__name__}: {e}")[:240]
    stato = Stato(
        modalita_monitor=impostazioni.monitor_modalita,
        indexnow_configurata=bool(impostazioni.indexnow_api_key),
        monitor_giri_validi=impostazioni.monitor_giri_validi,
        tipi_attivi=impostazioni.monitor_tipi_attivi,
        tipi_attivi_ignorati=impostazioni.monitor_tipi_attivi_ignorati,
        # Percorso A (§19.11): la modalita' del passo verifica-stato decide quali
        # esiti contano come riusciti, e una variabile scartata e' l'allarme
        # `configurazione:verifica_stato`. Con getattr: impostazioni di prima
        # del percorso A non li hanno, e valgono i default dello Stato.
        verifica_stato_modalita=str(getattr(impostazioni, "verifica_stato_modalita", "ombra") or "ombra"),
        verifica_stato_config_valida=bool(getattr(impostazioni, "verifica_stato_config_valida", True)),
        **campi,
    )
    return Fotografia(stato=stato, misure=misure, adesso=adesso)


def memoria_nuova(
    precedente: Mapping[str, Any] | None,
    servizio: Mapping[str, Any] | None,
    riepilogo: Mapping[str, Any],
    adesso: datetime,
) -> dict[str, Any]:
    """La memoria da salvare con il riepilogo (§10).

    - `nrestarts`: i punti `[iso, n]` delle ultime 6 ore, al massimo 30, piu'
      quello di adesso se systemd l'ha detto. `telemetria` ci conta gli
      aumenti per `riavvii_ripetuti`;
    - `dal`: da quando e' acceso ogni codice del riepilogo. Un codice ancora
      acceso tiene il suo `dal`, uno spento sparisce, uno nuovo prende adesso
      (lo decide `riepilogo_pannello`; qui si ricopia).
    """
    dal_minimo = adesso - timedelta(hours=ORE_MEMORIA_NRESTARTS)
    punti: list[list[Any]] = []
    vecchi = precedente.get("nrestarts") if isinstance(precedente, Mapping) else None
    for punto in vecchi if isinstance(vecchi, (list, tuple)) else ():
        if not isinstance(punto, (list, tuple)) or len(punto) != 2:
            continue
        try:
            quando = datetime.fromisoformat(str(punto[0]).replace("Z", "+00:00"))
            valore = int(punto[1])
        except (TypeError, ValueError):
            continue
        if quando.tzinfo is not None and dal_minimo <= quando <= adesso:
            punti.append([_iso(quando), valore])
    if isinstance(servizio, Mapping) and isinstance(servizio.get("n_restarts"), int):
        punti.append([_iso(adesso), servizio["n_restarts"]])
    segnali = riepilogo.get("segnali") if isinstance(riepilogo, Mapping) else None
    return {
        "nrestarts": punti[-MAX_PUNTI_NRESTARTS:],
        "dal": {
            s["codice"]: s["dal"] for s in (segnali if isinstance(segnali, list) else ())
            if isinstance(s, Mapping) and s.get("codice") and s.get("dal")
        },
    }


def esegui(
    dry_run: bool = False,
    *,
    adesso: datetime | None = None,
    stampa: Callable[[str], None] = print,
) -> int:
    """Un giro di sorveglianza. Exit code: 0 (anche con allarmi) o 1.

    Con `dry_run` legge tutto (memoria compresa), stampa il JSON validato e i
    codici e non scrive niente. Senza la migrazione 12 (schema leggibile, tabella
    assente): un warning ed exit 0. Con il DB che non risponde (misure fallite o
    schema non leggibile): un errore nel journal ed exit 1, anche in dry-run.
    """
    try:
        return _esegui(dry_run, adesso=adesso or datetime.now(tz=timezone.utc), stampa=stampa)
    except Exception as e:
        logger.exception("[sorveglia] errore interno: {}", redigi(f"{type(e).__name__}: {e}"))
        return 1


def _esegui(dry_run: bool, *, adesso: datetime, stampa: Callable[[str], None]) -> int:
    from . import db, riepilogo_salute
    from .telemetria import salute

    # 1. La memoria prima di tutto: la fotografia la usa per i riavvii.
    memoria = db.leggi_memoria_riepilogo()
    # 2-3. Fotografia, giudizio e riepilogo con lo stesso istante.
    foto = fotografa(adesso=adesso, memoria=memoria)
    esito = salute(foto.stato, adesso=adesso)
    misure = dict(foto.misure)
    misure["memoria"] = memoria if isinstance(memoria, Mapping) else {}
    riepilogo = riepilogo_salute.riepilogo_pannello(esito, misure, adesso)
    # 4. Validazione: un riepilogo che non passa non esce mai, nemmeno a pezzi.
    errori = riepilogo_salute.valida_v1(riepilogo)
    if errori:
        logger.warning("[sorveglia] riepilogo non valido, scrivo il minimo: {}",
                       redigi("; ".join(errori))[:1000])
        dal = (misure["memoria"].get("dal") or {}) if isinstance(misure["memoria"], Mapping) else {}
        riepilogo = riepilogo_salute.riepilogo_minimo(
            adesso, dal=dal.get("riepilogo_non_valido") if isinstance(dal, Mapping) else None)
    riga = {
        "calcolato_at": _iso(adesso),
        "intervallo_ritardo": INTERVALLO_RITARDO,
        "versione": VERSIONE_RIGA,
        "riepilogo": riepilogo,
        "memoria": memoria_nuova(memoria, foto.misure.get("servizio"), riepilogo, adesso),
    }
    codici = [f"{s.get('livello')} {s.get('codice')}" for s in riepilogo.get("segnali") or ()]
    # Gia' redatto da `fotografa`: le misure del DB non sono arrivate.
    errore_db = getattr(foto.stato, "misure_db_errore", None)

    if dry_run:
        stampa(json.dumps(riepilogo, ensure_ascii=False, indent=2, sort_keys=True))
        stampa("sorveglia: stato " + str(riepilogo.get("stato")))
        stampa("sorveglia: codici: " + (", ".join(codici) or "nessuno"))
        stampa("sorveglia: --dry-run, niente scritto")
        return _esito_db(errore_db)
    # 5. La riga unica. Tre casi: tabella presente, assente (la 12 non e'
    # applicata: niente da scrivere e non e' un errore) o schema non leggibile
    # (il DB non risponde: e' un errore, non una migrazione mancante).
    disponibile = db.riepilogo_disponibile()
    if disponibile is None:
        logger.error("[sorveglia] schema del DB non leggibile: niente scritto")
        return 1
    if disponibile:
        if not db.scrivi_riepilogo_monitoraggio(riga):
            logger.error("[sorveglia] riepilogo non scritto")
            return 1
        logger.info("[sorveglia] riepilogo scritto: stato {}, codici {}",
                    riepilogo.get("stato"), ", ".join(codici) or "nessuno")
    elif errore_db is None:
        logger.warning("[sorveglia] tabella del riepilogo assente (migrazione 12 non applicata): "
                       "niente scritto")
    return _esito_db(errore_db)


def _esito_db(errore_db: Any) -> int:
    """1 con un errore nel journal se le misure del DB non sono arrivate, altrimenti 0.

    Il riepilogo con l'allarme `misure_non_disponibili` e' gia' stato scritto,
    se si poteva: l'exit 1 serve al journal e a systemd, non al pannello.
    """
    if errore_db:
        logger.error("[sorveglia] misure del DB non disponibili: {}", errore_db)
        return 1
    return 0


__all__ = [
    "Fotografia", "INTERVALLO_RITARDO", "SERVIZIO_PREDEFINITO", "esegui", "fotografa",
    "memoria_nuova", "nome_servizio", "stato_servizio",
]
