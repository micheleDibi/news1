"""Scheduler per la pipeline bandi.

Schedula:
  - 00:00, 06:00, 12:00, 18:00 -> pipeline FULL (scraper completo + skill enrichment)
  -                ogni 4 ore  -> pipeline PENDING (retry scraper + skill enrichment)
  -                ogni 30 min -> SOLO skill enrichment (backfill storico)
  -                ogni 5 min  -> HEARTBEAT (sender alive + ultimo job + prossimo)

Logging: DEBUG ovunque (richiesta utente). Ogni job e' wrappato in `_run_job`
per loggare START/DONE/EXCEPTION; `_heartbeat` da' visibilita' quando idle.

Uso: `python -m app.bandi_sender` (dalla cartella backend/, con `.env` caricato
nel processo — di solito via `env` di systemd o `python-dotenv` in `__main__`).

Pattern identico a `interpelli_sender.py` e `selezione_personale_sender.py`.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Any, Callable

import schedule

from .bandi import (
    run_full_pipeline,
    run_pending_pipeline,
    run_skill_only_pipeline,
)
from .logger import logger


_HOURS_FULL = ("00:00", "06:00", "12:00", "18:00")

# Stato condiviso usato dal heartbeat per riportare l'ultimo job eseguito.
# `schedule` esegue tutti i callback nello stesso thread (run_pending in
# foreground), quindi nessuna race da gestire.
_last_job: dict[str, Any] = {
    "name": None,
    "started_at": None,
    "ended_at": None,
    "ok": None,
    "elapsed_s": None,
}


def _run_job(name: str, fn: Callable[[], Any]) -> None:
    """Wrap di ogni job schedulato: logga START / DONE / EXCEPTION e aggiorna
    `_last_job` per il prossimo heartbeat."""
    started = dt.datetime.now()
    logger.info("[sender/job] {} -> START at {}", name, started.isoformat(timespec="seconds"))
    _last_job["name"] = name
    _last_job["started_at"] = started
    _last_job["ended_at"] = None
    _last_job["ok"] = None
    _last_job["elapsed_s"] = None
    try:
        fn()
        ended = dt.datetime.now()
        elapsed = (ended - started).total_seconds()
        _last_job["ended_at"] = ended
        _last_job["ok"] = True
        _last_job["elapsed_s"] = elapsed
        logger.info("[sender/job] {} -> DONE in {:.1f}s", name, elapsed)
    except Exception:
        ended = dt.datetime.now()
        elapsed = (ended - started).total_seconds()
        _last_job["ended_at"] = ended
        _last_job["ok"] = False
        _last_job["elapsed_s"] = elapsed
        # logger.exception emette stacktrace completo a livello ERROR.
        logger.exception("[sender/job] {} -> FAILED after {:.1f}s", name, elapsed)


def _format_next_run() -> str:
    """Formatta il prossimo job schedulato ('HH:MM (tra Xm)') o 'n/a'."""
    nxt = schedule.next_run()
    if nxt is None:
        return "n/a"
    delta = nxt - dt.datetime.now()
    delta_min = max(0, int(delta.total_seconds() / 60))
    return f"{nxt.strftime('%H:%M')} (tra {delta_min}m)"


def _format_last_job() -> str:
    """Formatta l'ultimo job per il heartbeat."""
    name = _last_job["name"]
    if not name:
        return "nessuno ancora"
    ended = _last_job["ended_at"]
    if ended is None:
        # Job ancora in corso.
        run_s = (dt.datetime.now() - _last_job["started_at"]).total_seconds()
        return f"{name} IN-CORSO da {run_s:.0f}s"
    outcome = "OK" if _last_job["ok"] else "FAIL"
    elapsed_s = _last_job["elapsed_s"] or 0.0
    age_min = (dt.datetime.now() - ended).total_seconds() / 60
    return f"{name} {outcome} ({elapsed_s:.1f}s, {age_min:.1f}m fa)"


def _heartbeat() -> None:
    """Log INFO ogni 5 min: alive + prossimo job + ultimo job."""
    logger.info(
        "[sender/heartbeat] alive - prossimo: {} - ultimo: {}",
        _format_next_run(),
        _format_last_job(),
    )


def schedule_bandi_pipeline() -> None:
    for hour in _HOURS_FULL:
        schedule.every().day.at(hour).do(_run_job, "full", run_full_pipeline)
    schedule.every(4).hours.do(_run_job, "pending", run_pending_pipeline)
    schedule.every(30).minutes.do(_run_job, "skill-only", run_skill_only_pipeline)
    # Heartbeat ogni 5 min — visibilita' che il loop e' vivo.
    schedule.every(5).minutes.do(_heartbeat)

    logger.info(
        "[sender] schedulato: full @ {} | pending ogni 4h | skill-only ogni 30 min | heartbeat ogni 5 min",
        ", ".join(_HOURS_FULL),
    )
    # Riassunto puntuale di tutti i prossimi run noti.
    for j in schedule.get_jobs():
        logger.info("[sender/schedule] job={} next_run={}", getattr(j, "job_func", j), j.next_run)

    # Primo heartbeat immediato cosi' c'e' subito una riga "alive" senza dover aspettare 5 min.
    _heartbeat()

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    try:
        logger.info("[sender] boot - avvio immediato pipeline FULL")
        _run_job("full (boot)", run_full_pipeline)
        logger.info("[sender] avvio scheduler")
        schedule_bandi_pipeline()
    except KeyboardInterrupt:
        logger.info("[sender] shutdown (KeyboardInterrupt)")
    except Exception:
        logger.exception("[sender] errore fatale scheduler")
