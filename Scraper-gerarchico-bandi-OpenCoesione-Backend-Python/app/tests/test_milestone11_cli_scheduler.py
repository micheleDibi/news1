"""
Test Milestone 11 — Scheduler ed esecuzione manuale

Verifica:
  1. Test run manuale completo (CLI cmd_run)
  2. Test run schedulato (job scheduler chiama stessa pipeline)
  3. Test run singola fonte (CLI cmd_run_fonte)
  4. Test run pending queue (CLI cmd_run_pending)
  5. Test comportamento identico tra modalità manuale e schedulata
"""
from __future__ import annotations

import argparse
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from app.cli import build_parser, cmd_run, cmd_run_fonte, cmd_run_pending
from app.scheduler import build_scheduler, _job_run_full, _job_run_pending, _parse_cron


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FULL_RESULT: dict[str, Any] = {
    "session_id": "aaaaaaaa-0000-0000-0000-000000000001",
    "scraping_log_id": 1,
    "fonti_scansionate": 3,
    "bandi_identificati": 12,
    "errori_fonti": 0,
    "processed": 12,
    "inserted": 4,
    "updated": 2,
    "unchanged": 6,
    "ai_jobs": {"considered": 4, "enqueued": 4, "already_present": 0, "not_required": 8},
    "retry": {
        "fonti_pending": 0,
        "fonti_failed_final": 0,
        "bandi_pending": 0,
        "bandi_failed_final": 0,
        "errori_definitivi": 0,
    },
}

_SINGLE_RESULT: dict[str, Any] = {
    **_FULL_RESULT,
    "fonte_id": 42,
    "fonti_scansionate": 1,
}

_PENDING_RESULT: dict[str, Any] = {
    "session_id": "aaaaaaaa-0000-0000-0000-000000000002",
    "scraping_log_id": 2,
    "fonti_pending_processate": 2,
    "bandi_identificati": 5,
    "errori_fonti": 0,
    "processed": 5,
    "inserted": 1,
    "updated": 1,
    "unchanged": 3,
    "ai_jobs": {"considered": 1, "enqueued": 1, "already_present": 0, "not_required": 4},
    "retry": {
        "fonti_pending": 0,
        "fonti_failed_final": 0,
        "bandi_pending": 0,
        "bandi_failed_final": 0,
        "errori_definitivi": 0,
    },
}


# ---------------------------------------------------------------------------
# Test 1 — Run manuale completo (CLI)
# ---------------------------------------------------------------------------

def test_run_manuale_completo_chiama_service_run():
    """cmd_run deve invocare BandoDiscoveryService.run() e restituire 0."""
    with patch("app.cli.BandoDiscoveryService") as mock_cls:
        mock_cls.return_value.run.return_value = _FULL_RESULT

        args = argparse.Namespace(limit=None)
        exit_code = cmd_run(args)

    assert exit_code == 0
    mock_cls.return_value.run.assert_called_once_with(limit=None)


def test_run_manuale_con_limit_passa_limit_al_service():
    """--limit deve essere passato a service.run(limit=N)."""
    with patch("app.cli.BandoDiscoveryService") as mock_cls:
        mock_cls.return_value.run.return_value = _FULL_RESULT

        args = argparse.Namespace(limit=5)
        cmd_run(args)

    mock_cls.return_value.run.assert_called_once_with(limit=5)


# ---------------------------------------------------------------------------
# Test 2 — Run schedulato: stessa pipeline del manuale
# ---------------------------------------------------------------------------

def test_run_schedulato_chiama_stessa_pipeline_del_manuale():
    """_job_run_full() deve chiamare BandoDiscoveryService().run() — identica al manuale."""
    with patch("app.scheduler.BandoDiscoveryService") as mock_cls:
        mock_cls.return_value.run.return_value = _FULL_RESULT

        _job_run_full()

    mock_cls.return_value.run.assert_called_once_with()


def test_scheduler_build_produce_due_job():
    """build_scheduler deve produrre esattamente 2 job configurati."""
    scheduler = build_scheduler(
        cron_full="0 2 * * *",
        cron_pending="0 */4 * * *",
    )
    jobs = scheduler.get_jobs()
    assert len(jobs) == 2
    job_ids = {j.id for j in jobs}
    assert "run_full" in job_ids
    assert "run_pending" in job_ids


def test_parse_cron_valido():
    """_parse_cron deve restituire i 5 campi corretti."""
    result = _parse_cron("30 6 * * 1-5")
    assert result == {
        "minute": "30",
        "hour": "6",
        "day": "*",
        "month": "*",
        "day_of_week": "1-5",
    }


# ---------------------------------------------------------------------------
# Test 3 — Run singola fonte (CLI)
# ---------------------------------------------------------------------------

def test_run_singola_fonte_chiama_run_single_fonte():
    """cmd_run_fonte deve invocare service.run_single_fonte(fonte_id=42)."""
    with patch("app.cli.BandoDiscoveryService") as mock_cls:
        mock_cls.return_value.run_single_fonte.return_value = _SINGLE_RESULT

        args = argparse.Namespace(fonte_id=42)
        exit_code = cmd_run_fonte(args)

    assert exit_code == 0
    mock_cls.return_value.run_single_fonte.assert_called_once_with(fonte_id=42)


def test_cli_parser_run_fonte_parsa_fonte_id():
    """Il parser CLI deve associare --fonte-id al namespace correttamente."""
    parser = build_parser()
    args = parser.parse_args(["run-fonte", "--fonte-id", "99"])
    assert args.fonte_id == 99
    assert args.command == "run-fonte"


# ---------------------------------------------------------------------------
# Test 4 — Run pending queue (CLI)
# ---------------------------------------------------------------------------

def test_run_pending_chiama_run_pending_queue():
    """cmd_run_pending deve invocare service.run_pending_queue()."""
    with patch("app.cli.BandoDiscoveryService") as mock_cls:
        mock_cls.return_value.run_pending_queue.return_value = _PENDING_RESULT

        args = argparse.Namespace()
        exit_code = cmd_run_pending(args)

    assert exit_code == 0
    mock_cls.return_value.run_pending_queue.assert_called_once_with()


def test_job_run_pending_chiama_run_pending_queue():
    """Il job schedulato _job_run_pending deve invocare run_pending_queue()."""
    with patch("app.scheduler.BandoDiscoveryService") as mock_cls:
        mock_cls.return_value.run_pending_queue.return_value = _PENDING_RESULT

        _job_run_pending()

    mock_cls.return_value.run_pending_queue.assert_called_once_with()


# ---------------------------------------------------------------------------
# Test 5 — Comportamento identico tra manuale e schedulato
# ---------------------------------------------------------------------------

def test_comportamento_identico_manuale_e_schedulato():
    """
    La modalità manuale (CLI) e schedulata devono chiamare lo stesso metodo
    del service (run) e produrre lo stesso tipo di risultato.
    CLI chiama run(limit=None), scheduler chiama run() — entrambi equivalenti
    poiché limit=None è il default del metodo.
    """
    with patch("app.cli.BandoDiscoveryService") as cli_cls:
        cli_cls.return_value.run.return_value = _FULL_RESULT
        cmd_run(argparse.Namespace(limit=None))
        cli_call_args = cli_cls.return_value.run.call_args

    with patch("app.scheduler.BandoDiscoveryService") as sched_cls:
        sched_cls.return_value.run.return_value = _FULL_RESULT
        _job_run_full()
        sched_call_args = sched_cls.return_value.run.call_args

    # Entrambi devono chiamare run() — CLI con limit=None, scheduler senza args
    # I kwargs rilevanti coincidono: limit=None è il valore di default
    cli_limit = cli_call_args.kwargs.get("limit")
    sched_limit = sched_call_args.kwargs.get("limit") if sched_call_args.kwargs else None

    assert cli_limit == sched_limit, (
        f"Parametri non equivalenti — CLI limit={cli_limit!r}, Scheduler limit={sched_limit!r}"
    )
