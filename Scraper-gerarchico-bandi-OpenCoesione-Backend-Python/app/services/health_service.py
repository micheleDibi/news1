"""
Servizio indicatori di salute dello scraper.

Raccoglie le metriche da HealthRepo e le classifica con un semaforo
(VERDE / GIALLO / ROSSO) a livello di singolo indicatore e complessivo.

Uso:
    service = HealthService()
    report = service.get_report()
    print(report["semaforo"])        # VERDE / GIALLO / ROSSO
    print(report["sections"])        # dict per sezione
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.repos.base import HealthRepo


# ---------------------------------------------------------------------------
# Soglie
# ---------------------------------------------------------------------------

class _Thresholds:
    # Esecuzione
    RUN_MAX_AGE_HOURS_WARNING = 25
    RUN_MAX_AGE_HOURS_CRITICAL = 48
    RUN_MAX_DURATION_MS_WARNING = 30 * 60 * 1000   # 30 min
    RUN_MAX_DURATION_MS_CRITICAL = 60 * 60 * 1000  # 60 min

    # Fonti
    FONTI_FAILED_FINAL_WARNING = 1
    FONTI_FAILED_FINAL_CRITICAL = 5
    FONTI_PENDING_WARNING_PCT = 0.20  # 20% del totale
    FONTI_STUCK_CRITICAL = 1

    # Bandi — qualità campi
    DESCRIZIONE_RATE_WARNING = 0.30   # 30% con descrizione → warning
    DESCRIZIONE_RATE_CRITICAL = 0.10  # 10% → critico
    CLASSIFICAZIONE_RATE_WARNING = 0.50
    CLASSIFICAZIONE_RATE_CRITICAL = 0.30
    RUMORE_RATE_WARNING = 0.05
    RUMORE_RATE_CRITICAL = 0.15
    DUPLICATI_CRITICAL = 1
    BANDI_FAILED_CRITICAL = 1

    # AI
    AI_QUEUED_WARNING = 100
    AI_QUEUED_CRITICAL = 500
    AI_STUCK_CRITICAL = 1
    AI_FAILED_WARNING = 5
    AI_AVG_SECONDS_WARNING = 30
    AI_AVG_SECONDS_CRITICAL = 120

    # Errori
    ERRORI_APERTI_WARNING = 5
    ERRORI_APERTI_CRITICAL = 20

    # Storico
    INCOERENTI_CRITICAL = 1


T = _Thresholds


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _semaforo_value(values: list[str]) -> str:
    if "ROSSO" in values:
        return "ROSSO"
    if "GIALLO" in values:
        return "GIALLO"
    return "VERDE"


def _indicator(
    label: str,
    value: Any,
    status: str,
    *,
    threshold_warning: Any = None,
    threshold_critical: Any = None,
    unit: str = "",
) -> dict[str, Any]:
    return {
        "label": label,
        "value": value,
        "unit": unit,
        "status": status,
        "threshold_warning": threshold_warning,
        "threshold_critical": threshold_critical,
    }


def _age_hours(dt: Any) -> float | None:
    """Ore trascorse da un datetime (stringa ISO o datetime). None se assente."""
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    return delta.total_seconds() / 3600


# ---------------------------------------------------------------------------
# Servizio
# ---------------------------------------------------------------------------

class HealthService:
    """Aggrega le metriche di salute e produce un report strutturato."""

    def __init__(self) -> None:
        self._repo = HealthRepo()

    # ------------------------------------------------------------------ #
    # Entry point pubblico                                                 #
    # ------------------------------------------------------------------ #

    def get_report(self) -> dict[str, Any]:
        """Restituisce il report completo con semaforo."""
        sections: dict[str, dict[str, Any]] = {}

        sections["esecuzione"] = self._section_esecuzione()
        sections["fonti"] = self._section_fonti()
        sections["bandi"] = self._section_bandi()
        sections["ai_queue"] = self._section_ai_queue()
        sections["errori"] = self._section_errori()
        sections["storico"] = self._section_storico()

        all_statuses = [
            ind["status"]
            for sec in sections.values()
            for ind in sec.get("indicators", [])
        ]
        overall = _semaforo_value(all_statuses)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "semaforo": overall,
            "sections": sections,
        }

    # ------------------------------------------------------------------ #
    # Sezioni                                                              #
    # ------------------------------------------------------------------ #

    def _section_esecuzione(self) -> dict[str, Any]:
        raw = self._repo.get_last_run()
        indicators: list[dict[str, Any]] = []

        if not raw:
            indicators.append(_indicator("Nessun run trovato", None, "ROSSO"))
            return {"indicators": indicators, "semaforo": "ROSSO", "raw": {}}

        stato = raw.get("stato")
        completed_at = raw.get("completed_at")
        age_h = _age_hours(completed_at)
        duration_ms = raw.get("tempo_esecuzione_ms")

        # Completamento run
        if stato == "completed":
            ind_stato = _indicator("Stato ultimo run", stato, "ok")
        elif stato == "failed":
            ind_stato = _indicator("Stato ultimo run", stato, "ROSSO")
        else:
            ind_stato = _indicator("Stato ultimo run", stato, "GIALLO")
        indicators.append(ind_stato)

        # Età run
        if age_h is None:
            age_status = "ROSSO"
        elif age_h <= T.RUN_MAX_AGE_HOURS_WARNING:
            age_status = "ok"
        elif age_h <= T.RUN_MAX_AGE_HOURS_CRITICAL:
            age_status = "GIALLO"
        else:
            age_status = "ROSSO"
        indicators.append(_indicator(
            "Ore dall'ultimo run completato",
            round(age_h, 1) if age_h is not None else None,
            age_status,
            threshold_warning=T.RUN_MAX_AGE_HOURS_WARNING,
            threshold_critical=T.RUN_MAX_AGE_HOURS_CRITICAL,
            unit="ore",
        ))

        # Durata
        if duration_ms is None:
            dur_status = "ok"
        elif duration_ms <= T.RUN_MAX_DURATION_MS_WARNING:
            dur_status = "ok"
        elif duration_ms <= T.RUN_MAX_DURATION_MS_CRITICAL:
            dur_status = "GIALLO"
        else:
            dur_status = "ROSSO"
        indicators.append(_indicator(
            "Durata ultimo run",
            round(duration_ms / 60000, 1) if duration_ms else None,
            dur_status,
            threshold_warning=round(T.RUN_MAX_DURATION_MS_WARNING / 60000, 0),
            threshold_critical=round(T.RUN_MAX_DURATION_MS_CRITICAL / 60000, 0),
            unit="min",
        ))

        # Contatori bandi
        for key, label in [
            ("bandi_trovati", "Bandi trovati"),
            ("bandi_nuovi", "Bandi nuovi"),
            ("bandi_aggiornati", "Bandi aggiornati"),
        ]:
            indicators.append(_indicator(label, raw.get(key), "ok"))

        section_statuses = [i["status"] for i in indicators]
        return {
            "indicators": indicators,
            "semaforo": _semaforo_value(section_statuses),
            "raw": {
                "stato": stato,
                "completed_at": completed_at.isoformat() if isinstance(completed_at, datetime) else completed_at,
                "bandi_trovati": raw.get("bandi_trovati"),
                "bandi_nuovi": raw.get("bandi_nuovi"),
            },
        }

    def _section_fonti(self) -> dict[str, Any]:
        raw = self._repo.get_fonti_stats()
        indicators: list[dict[str, Any]] = []

        totale = raw.get("totale_attive", 0)
        failed_final = raw.get("failed_final", 0)
        pending = raw.get("pending", 0)
        stuck = raw.get("processing_stuck", 0)

        # Fonti attive
        indicators.append(_indicator("Fonti attive", totale, "ok"))

        # Failed final
        if failed_final == 0:
            ff_status = "ok"
        elif failed_final < T.FONTI_FAILED_FINAL_CRITICAL:
            ff_status = "GIALLO"
        else:
            ff_status = "ROSSO"
        indicators.append(_indicator(
            "Fonti failed_final",
            failed_final,
            ff_status,
            threshold_warning=T.FONTI_FAILED_FINAL_WARNING,
            threshold_critical=T.FONTI_FAILED_FINAL_CRITICAL,
        ))

        # Pending %
        pct_pending = round(100.0 * pending / totale, 1) if totale else 0
        if pct_pending <= T.FONTI_PENDING_WARNING_PCT * 100:
            p_status = "ok"
        elif pct_pending <= 30:
            p_status = "GIALLO"
        else:
            p_status = "ROSSO"
        indicators.append(_indicator(
            "Fonti in pending (%)",
            pct_pending,
            p_status,
            threshold_warning=T.FONTI_PENDING_WARNING_PCT * 100,
            unit="%",
        ))

        # Stuck processing
        if stuck >= T.FONTI_STUCK_CRITICAL:
            indicators.append(_indicator("Fonti bloccate in processing", stuck, "ROSSO"))
        else:
            indicators.append(_indicator("Fonti bloccate in processing", stuck, "ok"))

        section_statuses = [i["status"] for i in indicators]
        return {
            "indicators": indicators,
            "semaforo": _semaforo_value(section_statuses),
            "raw": raw,
        }

    def _section_bandi(self) -> dict[str, Any]:
        raw = self._repo.get_bandi_quality()
        indicators: list[dict[str, Any]] = []

        if not raw:
            indicators.append(_indicator("Nessun bando trovato", None, "GIALLO"))
            return {"indicators": indicators, "semaforo": "GIALLO", "raw": {}}

        totale = raw.get("totale", 0)
        pct_descrizione = raw.get("pct_con_descrizione", 0.0)
        pct_class = raw.get("pct_con_classificazione", 0.0)
        pct_noise = raw.get("pct_sospetti_rumore", 0.0)
        duplicati = raw.get("duplicati", 0)
        failed_final = raw.get("failed_final", 0)
        recent_runs_total = raw.get("ultime_3_run_totale", 0)
        recent_runs_completed = raw.get("ultime_3_run_completed", 0)

        indicators.append(_indicator("Bandi totali", totale, "ok"))

        # Descrizione
        if pct_descrizione / 100 >= T.DESCRIZIONE_RATE_WARNING:
            d_status = "ok"
        elif pct_descrizione / 100 >= T.DESCRIZIONE_RATE_CRITICAL:
            d_status = "GIALLO"
        else:
            d_status = "ROSSO"
        indicators.append(_indicator(
            "Bandi con descrizione (%)",
            pct_descrizione,
            d_status,
            threshold_warning=T.DESCRIZIONE_RATE_WARNING * 100,
            threshold_critical=T.DESCRIZIONE_RATE_CRITICAL * 100,
            unit="%",
        ))

        # Classificazione
        if pct_class / 100 >= T.CLASSIFICAZIONE_RATE_WARNING:
            c_status = "ok"
        elif pct_class / 100 >= T.CLASSIFICAZIONE_RATE_CRITICAL:
            c_status = "GIALLO"
        else:
            c_status = "ROSSO"
        indicators.append(_indicator(
            "Bandi classificati (programma o tipologia) (%)",
            pct_class,
            c_status,
            threshold_warning=T.CLASSIFICAZIONE_RATE_WARNING * 100,
            threshold_critical=T.CLASSIFICAZIONE_RATE_CRITICAL * 100,
            unit="%",
        ))

        # Rumore stimato dataset
        if pct_noise / 100 <= T.RUMORE_RATE_WARNING:
            noise_status = "ok"
        elif pct_noise / 100 <= T.RUMORE_RATE_CRITICAL:
            noise_status = "GIALLO"
        else:
            noise_status = "ROSSO"
        indicators.append(_indicator(
            "Bandi sospetti rumore (%)",
            pct_noise,
            noise_status,
            threshold_warning=T.RUMORE_RATE_WARNING * 100,
            threshold_critical=T.RUMORE_RATE_CRITICAL * 100,
            unit="%",
        ))

        # Duplicati
        dup_status = "ROSSO" if duplicati >= T.DUPLICATI_CRITICAL else "ok"
        indicators.append(_indicator("Duplicati hash_bando", duplicati, dup_status, threshold_critical=1))

        # Failed final
        ff_status = "ROSSO" if failed_final >= T.BANDI_FAILED_CRITICAL else "ok"
        indicators.append(_indicator("Bandi failed_final", failed_final, ff_status, threshold_critical=1))

        # Senza scadenza (informativo)
        indicators.append(_indicator(
            "Bandi senza data_scadenza",
            raw.get("senza_scadenza"),
            "ok",
        ))

        # Stabilità minima osservata sulle ultime run.
        stability_status = "ok" if recent_runs_total >= 3 and recent_runs_completed == 3 else "GIALLO"
        indicators.append(_indicator(
            "Ultime 3 run completate",
            f"{recent_runs_completed}/{recent_runs_total}",
            stability_status,
            threshold_warning="3/3 richieste",
        ))

        section_statuses = [i["status"] for i in indicators]
        return {
            "indicators": indicators,
            "semaforo": _semaforo_value(section_statuses),
            "raw": raw,
        }

    def _section_ai_queue(self) -> dict[str, Any]:
        raw = self._repo.get_ai_queue_stats()
        indicators: list[dict[str, Any]] = []

        queued = raw.get("queued", 0)
        failed = raw.get("failed", 0)
        stuck = raw.get("processing_stuck", 0)
        avg_sec = raw.get("avg_completion_seconds")

        # Coda
        if queued <= T.AI_QUEUED_WARNING:
            q_status = "ok"
        elif queued <= T.AI_QUEUED_CRITICAL:
            q_status = "GIALLO"
        else:
            q_status = "ROSSO"
        indicators.append(_indicator(
            "Job AI in coda",
            queued,
            q_status,
            threshold_warning=T.AI_QUEUED_WARNING,
            threshold_critical=T.AI_QUEUED_CRITICAL,
        ))

        # Failed
        if failed <= T.AI_FAILED_WARNING:
            f_status = "ok"
        else:
            f_status = "GIALLO"
        indicators.append(_indicator(
            "Job AI failed",
            failed,
            f_status,
            threshold_warning=T.AI_FAILED_WARNING,
        ))

        # Stuck
        stuck_status = "ROSSO" if stuck >= T.AI_STUCK_CRITICAL else "ok"
        indicators.append(_indicator("Job AI bloccati in processing", stuck, stuck_status, threshold_critical=1))

        # Tempo medio completamento
        if avg_sec is None:
            avg_status = "ok"
        elif avg_sec <= T.AI_AVG_SECONDS_WARNING:
            avg_status = "ok"
        elif avg_sec <= T.AI_AVG_SECONDS_CRITICAL:
            avg_status = "GIALLO"
        else:
            avg_status = "ROSSO"
        indicators.append(_indicator(
            "Tempo medio completamento job AI (ultime 24h)",
            avg_sec,
            avg_status,
            threshold_warning=T.AI_AVG_SECONDS_WARNING,
            threshold_critical=T.AI_AVG_SECONDS_CRITICAL,
            unit="s",
        ))

        section_statuses = [i["status"] for i in indicators]
        return {
            "indicators": indicators,
            "semaforo": _semaforo_value(section_statuses),
            "raw": raw,
        }

    def _section_errori(self) -> dict[str, Any]:
        raw = self._repo.get_error_stats()
        indicators: list[dict[str, Any]] = []

        aperti = raw.get("aperti", 0)

        if aperti == 0:
            e_status = "ok"
        elif aperti <= T.ERRORI_APERTI_WARNING:
            e_status = "GIALLO"
        else:
            e_status = "ROSSO"
        indicators.append(_indicator(
            "Errori definitivi non risolti",
            aperti,
            e_status,
            threshold_warning=T.ERRORI_APERTI_WARNING,
            threshold_critical=T.ERRORI_APERTI_CRITICAL,
        ))
        indicators.append(_indicator("Errori definitivi totali", raw.get("totale", 0), "ok"))
        indicators.append(_indicator("Errori definitivi risolti", raw.get("risolti", 0), "ok"))

        section_statuses = [i["status"] for i in indicators]
        return {
            "indicators": indicators,
            "semaforo": _semaforo_value(section_statuses),
            "raw": raw,
        }

    def _section_storico(self) -> dict[str, Any]:
        raw = self._repo.get_storico_stats()
        indicators: list[dict[str, Any]] = []

        incoerenti = raw.get("bandi_incoerenti_date", 0)
        incoerenti_status = "ROSSO" if incoerenti >= T.INCOERENTI_CRITICAL else "ok"
        indicators.append(_indicator(
            "Bandi con date incoerenti (primo > ultimo scraping)",
            incoerenti,
            incoerenti_status,
            threshold_critical=1,
        ))
        indicators.append(_indicator(
            "Righe storico nelle ultime 24h",
            raw.get("righe_ultime_24h"),
            "ok",
        ))

        section_statuses = [i["status"] for i in indicators]
        return {
            "indicators": indicators,
            "semaforo": _semaforo_value(section_statuses),
            "raw": raw,
        }
