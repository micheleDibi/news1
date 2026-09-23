"""Configurazione runtime: legge .env e fornisce singleton `settings`.

Variabili obbligatorie:
  - SUPABASE_URL_BANDI
  - SUPABASE_SERVICE_KEY_BANDI

Variabili opzionali (con default):
  - OPENCOESIONE_URL         (pagina sorgente)
  - REACHABILITY_TIMEOUT_S   (timeout HEAD/GET per testare attivo)
  - REACHABILITY_CONCURRENCY (concorrenza asyncio per reachability)
  - HTTP_USER_AGENT          (UA delle request)

Variabili v11 (piano §6.2, §16.2 M13/M15/M19; tutte con default sicuri: il
codice non ne pretende nessuna in `.env`, cosi' un deploy che non le imposta
continua a funzionare in modalita' ombra e con i tetti dello scenario
bilanciato):
  - MONITOR_GIRI             (ore dei giri, "06:00,18:00"; M13: era MONITOR_ORE)
  - MONITOR_MODALITA / RESOLVER_MODALITA  (ombra|attivo, default ombra)
  - MONITOR_SCENARIO         (economico|bilanciato|massimo, default bilanciato)
  - TETTO_* / BACKFILL_TETTO_*  (tetti per giro, giornalieri, mensili, backfill)
  - OE_SCHEDE_GIORNO         (tetto schede Obiettivo Europa al giorno)
  - INDEXNOW_API_KEY         (M15: vive qui, non nel backend)
  - LISTINO_MODELLI          (listino $/Mtoken "model_id=in/out,...", A36)
  - DEDUP_CANONICAL          (fix 8.a.10, default false)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from dotenv import load_dotenv

from .logger import logger


_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.6 Safari/605.1.15 EduNews24-ScraperBandi/1.0"
)

_DEFAULT_OPENCOESIONE_URL = "https://opencoesione.gov.it/it/opportunita_2021_2027/"


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_service_key: str
    opencoesione_url: str
    reachability_timeout_s: float
    reachability_concurrency: int
    http_user_agent: str
    # Step 2 (scraping bandi)
    firecrawl_api_key: str        # vuota se non impostata: strategie firecrawl_* falliranno
    host_throttle_delay_s: float  # delay min tra request stesso host
    # Step intermedio: pre-processing via LLM
    anthropic_api_key: str        # obbligatoria per preprocess
    preprocess_model: str
    preprocess_concurrency: int
    preprocess_max_tokens: int
    # Step v7: enrichment via LLM + Firecrawl
    enrich_model: str
    enrich_concurrency: int
    enrich_concurrency_refine: int
    enrich_max_tokens: int
    # Step v8: skill SEO (enriched -> completed) via Claude Opus 4.7
    seo_model: str
    seo_concurrency: int
    seo_max_tokens: int
    seo_reachability_check: bool
    # Step v9: preprocess v2 (Firecrawl + Haiku + Sonnet fallback)
    preprocess_firecrawl_concurrency: int
    resolver_model: str
    resolver_max_tokens: int
    # Step v10: credenziali fonti esterne autenticate
    obiettivo_europa_username: str
    obiettivo_europa_password: str
    # v11: giri, modalita' e scenario (§6.2; M13: il giro e' esplicito)
    monitor_giri: tuple[str, ...]
    monitor_giri_validi: bool      # False se MONITOR_GIRI conteneva voci scartate
    monitor_modalita: str          # ombra | attivo
    resolver_modalita: str         # ombra | attivo
    monitor_scenario: str          # economico | bilanciato | massimo
    # v11: tetti. Per giro solo sul fetch; giornalieri, mensili e backfill
    # separati (A23: il backfill ha contatori propri e non entra nel mensile).
    tetto_fetch_giro: int
    tetto_ricerche_giorno: int
    tetto_crediti_giorno: int
    tetto_classificazioni_giorno: int
    tetto_usd_giorno: float
    tetto_crediti_mese: int
    tetto_usd_mese: float
    backfill_tetto_crediti: int
    backfill_tetto_usd: float
    # v11: varie
    oe_schede_giorno: int
    indexnow_api_key: str
    listino_modelli: Mapping[str, tuple[float, float]]   # $/Mtoken (in, out)
    # Fotografia di DEDUP_CANONICAL al primo `get_settings()` (la cache la
    # congela). La lettura VIVA, quella che decide davvero in
    # `bando_seo_runner._dedup_canonical_attivo()`, e' `bool_env`: i due valori
    # coincidono sempre, tranne se la variabile cambia a processo avviato —
    # allora fa fede `bool_env`. Chi legge questo campo per decidere qualcosa
    # usi `bool_env("DEDUP_CANONICAL", ...)` o chiami `get_settings.cache_clear()`.
    dedup_canonical: bool
    # Gli stati `sospeso` e `revocato` esistono nella colonna solo dopo la
    # migrazione 06 (CHECK a 5 valori), che a sua volta richiede il rilascio
    # difensivo R0-a del consumatore. Finche' e' falsa, gli eventi verificati di
    # sospensione e revoca restano leggibili ma non applicati alla colonna.
    monitor_stati_estesi: bool

    def __repr__(self) -> str:
        """Repr mascherante: un `Settings` non deve poter finire in un log.

        Il repr generato da `@dataclass` stampa **tutti** i campi, chiavi
        comprese. Basta un `logger.warning("... {}", impostazioni)`, un
        `print` in un runner o un traceback con `diagnose=True` perche'
        `SUPABASE_SERVICE_KEY_BANDI` e `ANTHROPIC_API_KEY` finiscano in
        chiaro su stderr e dentro `logs/`. Qui i campi segreti diventano
        `***` (o `''` se vuoti, che e' un'informazione utile e non un
        segreto); tutto il resto resta leggibile, perche' questo repr serve a
        diagnosticare una configurazione sbagliata.
        """
        pezzi = []
        for campo in fields(self):
            valore = getattr(self, campo.name)
            if campo.name in CAMPI_SEGRETI:
                valore = "***" if valore else ""
            pezzi.append(f"{campo.name}={valore!r}")
        return f"Settings({', '.join(pezzi)})"


#: I campi di `Settings` che non devono comparire in nessun repr, log o
#: traceback. L'elenco e' esplicito e non dedotto dal nome: un campo nuovo che
#: contiene un segreto va aggiunto qui, e il test `test_logger_redazione` lo
#: ricorda confrontando questo insieme con i nomi che finiscono in `-key`,
#: `-secret` o `-password`.
CAMPI_SEGRETI: frozenset[str] = frozenset({
    "supabase_service_key", "firecrawl_api_key", "anthropic_api_key",
    "obiettivo_europa_password", "indexnow_api_key",
})


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# --- v11: default per scenario, listino e parsing ---------------------------

# Tetti per scenario (§6.2 e A23). Il tetto per giro e' solo sul fetch: gli
# scenari piu' ricchi fanno piu' giri, quindi il tetto per giro SCENDE.
_TETTI_SCENARIO: dict[str, dict[str, float]] = {
    "economico":  {"fetch_giro": 460, "usd_giorno": 1.0, "crediti_mese": 3800, "usd_mese": 12.0},
    "bilanciato": {"fetch_giro": 420, "usd_giorno": 1.5, "crediti_mese": 5000, "usd_mese": 16.0},
    "massimo":    {"fetch_giro": 270, "usd_giorno": 3.0, "crediti_mese": 6500, "usd_mese": 30.0},
}
SCENARI = tuple(_TETTI_SCENARIO)
MODALITA = ("ombra", "attivo")

# Tetti giornalieri di regime, uguali in tutti gli scenari: sono una cintura
# contro il consumo anomalo, non la stima del consumo atteso.
#
# ATTENZIONE, il piano dice due numeri diversi: §6.2 fissa ricerche e crediti
# resolver a 30/60 («atteso x 3»), §16.2 M19 li porta a 50/120 «a regime».
# Qui si seguono quelli di M19, perche' la consegna indica §16 come insieme
# delle regole operative vincolanti; restano sovrascrivibili con
# TETTO_RICERCHE_GIORNO / TETTO_CREDITI_GIORNO senza toccare il codice.
# La divergenza fra le due sezioni del piano e' da sanare a monte.
_RICERCHE_GIORNO = 50
_CREDITI_GIORNO = 120
_CLASSIFICAZIONI_GIORNO = 30

# Contatore separato del backfill (A23): non entra nel tetto mensile.
_BACKFILL_CREDITI = 8000
_BACKFILL_USD = 60.0

# Le quattro ore dello scheduler (`backend/app/bandi_sender.py`). Vivono qui e
# non la' perche' `MONITOR_GIRI` si confronta con questo insieme: un giro
# dichiarato a un'ora in cui la pipeline non parte mai e' uno step di
# monitoraggio spento in silenzio, cioe' il guasto peggiore del piano.
GIRI_SCHEDULER: tuple[str, ...] = ("00:00", "06:00", "12:00", "18:00")

_GIRI_DEFAULT = ("06:00", "18:00")

# Listino $/Mtoken (in, out) come MAPPA model_id -> prezzi (A36): un modello
# non a listino non viene indovinato, `bilancio` alza l'allarme.
_LISTINO_DEFAULT: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-7": (5.0, 25.0),
}


def bool_env(name: str, default: bool = False) -> bool:
    """Lettura booleana condivisa: una sola nozione di «vero» in tutto il package.

    Legge l'ambiente a ogni chiamata (non la cache di `get_settings`), cosi'
    chi deve reagire a un cambio di variabile senza riavviare puo' usarla.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "si", "sì")


def _scelta_env(name: str, ammessi: tuple[str, ...], default: str) -> str:
    """Valore di un'enumerazione: fuori enum -> default (mai un'eccezione qui:
    una variabile scritta male non deve impedire l'avvio del sender)."""
    valore = os.getenv(name, "").strip().lower()
    return valore if valore in ammessi else default


def _giri_env(
    name: str, default: tuple[str, ...], ammessi: tuple[str, ...] = GIRI_SCHEDULER,
) -> tuple[tuple[str, ...], bool]:
    """"06:00,18:00" -> (("06:00", "18:00"), tutto_valido).

    Scarta le voci non HH:MM **e** quelle fuori dalle ore dello scheduler: un
    `MONITOR_GIRI=07:00` non farebbe mai partire il monitor, e l'unica traccia
    sarebbe una riga INFO per giro. Qui la voce viene scartata con un warning e
    il secondo valore di ritorno (`tutto_valido`) alimenta l'allarme di
    `telemetria.salute`. Se non resta niente si ricade sul default, dicendolo.
    """
    grezzo = os.getenv(name, "").strip()
    if not grezzo:
        return default, True
    giri: list[str] = []
    scartate: list[str] = []
    for pezzo in grezzo.split(","):
        pezzo = pezzo.strip()
        if not pezzo:
            continue
        ore, _, minuti = pezzo.partition(":")
        if ore.isdigit() and minuti.isdigit() and 0 <= int(ore) <= 23 and 0 <= int(minuti) <= 59:
            normalizzato = f"{int(ore):02d}:{int(minuti):02d}"
            if normalizzato in ammessi:
                giri.append(normalizzato)
                continue
        scartate.append(pezzo)
    if scartate:
        logger.warning(
            "[settings] {}: voci ignorate {} (ammesse solo le ore dello scheduler {})",
            name, scartate, list(ammessi),
        )
    if not giri:
        logger.warning("[settings] {}: nessuna voce valida, si usa il default {}", name, list(default))
        return default, False
    return tuple(dict.fromkeys(giri)), not scartate


def _listino_env(name: str, default: dict[str, tuple[float, float]]) -> Mapping[str, tuple[float, float]]:
    """"id=in/out,id2=in/out" -> mappa. Le voci malformate sono ignorate; le
    valide si SOMMANO al default (un listino parziale non cancella gli altri)."""
    listino = dict(default)
    grezzo = os.getenv(name, "").strip()
    for pezzo in grezzo.split(","):
        chiave, _, prezzi = pezzo.partition("=")
        ingresso, _, uscita = prezzi.partition("/")
        try:
            listino[chiave.strip()] = (float(ingresso), float(uscita))
        except ValueError:
            continue
    return MappingProxyType(listino)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # Carica .env dal CWD e dalla root del sub-progetto.
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
    load_dotenv()  # fallback CWD

    supabase_url = os.getenv("SUPABASE_URL_BANDI", "").strip()
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY_BANDI", "").strip()

    if not supabase_url or not supabase_key:
        raise RuntimeError(
            "Mancano SUPABASE_URL_BANDI / SUPABASE_SERVICE_KEY_BANDI in .env. "
            "Copia .env.example -> .env e compila le credenziali del DB B."
        )

    scenario = _scelta_env("MONITOR_SCENARIO", SCENARI, "bilanciato")
    tetti = _TETTI_SCENARIO[scenario]
    giri, giri_validi = _giri_env("MONITOR_GIRI", _GIRI_DEFAULT)

    return Settings(
        supabase_url=supabase_url,
        supabase_service_key=supabase_key,
        opencoesione_url=os.getenv("OPENCOESIONE_URL", _DEFAULT_OPENCOESIONE_URL).strip()
            or _DEFAULT_OPENCOESIONE_URL,
        reachability_timeout_s=_float_env("REACHABILITY_TIMEOUT_S", 15.0),
        reachability_concurrency=max(1, _int_env("REACHABILITY_CONCURRENCY", 10)),
        http_user_agent=os.getenv("HTTP_USER_AGENT", _DEFAULT_USER_AGENT).strip()
            or _DEFAULT_USER_AGENT,
        firecrawl_api_key=os.getenv("FIRECRAWL_API_KEY", "").strip(),
        host_throttle_delay_s=_float_env("HOST_THROTTLE_DELAY_S", 1.0),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        preprocess_model=os.getenv("PREPROCESS_MODEL", "claude-haiku-4-5-20251001").strip()
            or "claude-haiku-4-5-20251001",
        preprocess_concurrency=max(1, _int_env("PREPROCESS_CONCURRENCY", 20)),
        preprocess_max_tokens=max(64, _int_env("PREPROCESS_MAX_TOKENS", 256)),
        enrich_model=os.getenv("ENRICH_MODEL", "claude-haiku-4-5-20251001").strip()
            or "claude-haiku-4-5-20251001",
        enrich_concurrency=max(1, _int_env("ENRICH_CONCURRENCY", 5)),
        enrich_concurrency_refine=max(1, _int_env("ENRICH_CONCURRENCY_REFINE", 3)),
        enrich_max_tokens=max(64, _int_env("ENRICH_MAX_TOKENS", 200)),
        seo_model=os.getenv("SEO_MODEL", "claude-opus-4-7").strip()
            or "claude-opus-4-7",
        seo_concurrency=max(1, _int_env("SEO_CONCURRENCY", 3)),
        seo_max_tokens=max(512, _int_env("SEO_MAX_TOKENS", 4000)),
        seo_reachability_check=os.getenv("SEO_REACHABILITY_CHECK", "true").strip().lower()
            not in ("false", "0", "no", "off"),
        preprocess_firecrawl_concurrency=max(1, _int_env("PREPROCESS_FIRECRAWL_CONCURRENCY", 5)),
        resolver_model=os.getenv("RESOLVER_MODEL", "claude-sonnet-4-6").strip()
            or "claude-sonnet-4-6",
        resolver_max_tokens=max(256, _int_env("RESOLVER_MAX_TOKENS", 1024)),
        obiettivo_europa_username=os.getenv("OBIETTIVO_EUROPA_USERNAME", "").strip(),
        obiettivo_europa_password=os.getenv("OBIETTIVO_EUROPA_PASSWORD", "").strip(),
        monitor_giri=giri,
        monitor_giri_validi=giri_validi,
        monitor_modalita=_scelta_env("MONITOR_MODALITA", MODALITA, "ombra"),
        resolver_modalita=_scelta_env("RESOLVER_MODALITA", MODALITA, "ombra"),
        monitor_scenario=scenario,
        tetto_fetch_giro=max(0, _int_env("TETTO_FETCH_GIRO", int(tetti["fetch_giro"]))),
        tetto_ricerche_giorno=max(0, _int_env("TETTO_RICERCHE_GIORNO", _RICERCHE_GIORNO)),
        tetto_crediti_giorno=max(0, _int_env("TETTO_CREDITI_GIORNO", _CREDITI_GIORNO)),
        tetto_classificazioni_giorno=max(
            0, _int_env("TETTO_CLASSIFICAZIONI_GIORNO", _CLASSIFICAZIONI_GIORNO)),
        tetto_usd_giorno=max(0.0, _float_env("TETTO_USD_GIORNO", tetti["usd_giorno"])),
        tetto_crediti_mese=max(0, _int_env("TETTO_CREDITI_MESE", int(tetti["crediti_mese"]))),
        tetto_usd_mese=max(0.0, _float_env("TETTO_USD_MESE", tetti["usd_mese"])),
        backfill_tetto_crediti=max(0, _int_env("BACKFILL_TETTO_CREDITI", _BACKFILL_CREDITI)),
        backfill_tetto_usd=max(0.0, _float_env("BACKFILL_TETTO_USD", _BACKFILL_USD)),
        oe_schede_giorno=max(0, _int_env("OE_SCHEDE_GIORNO", 850)),
        indexnow_api_key=os.getenv("INDEXNOW_API_KEY", "").strip(),
        listino_modelli=_listino_env("LISTINO_MODELLI", _LISTINO_DEFAULT),
        dedup_canonical=bool_env("DEDUP_CANONICAL", False),
        monitor_stati_estesi=bool_env("MONITOR_STATI_ESTESI", False),
    )
