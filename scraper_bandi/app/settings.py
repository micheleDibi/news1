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
  - MONITOR_GIRI             (ore dei giri, default tutte e quattro; M13: era MONITOR_ORE)
  - MONITOR_MODALITA / RESOLVER_MODALITA  (ombra|attivo, default ombra)
  - MONITOR_TIPI_ATTIVI      (tipi di evento applicati anche in ombra, "faq,proroga"
                              oppure "tutti"; default nessuno)
  - GEMELLI_MODALITA / DOMINI_MODALITA     (giro 3, §3: ombra|attivo, default ombra)
  - TEMPO_*_S                (giro 3, §3: secondi per passo, con intervallo)
  - MONITOR_SCENARIO         (economico|bilanciato|massimo, default bilanciato)
  - TETTO_* / BACKFILL_TETTO_*  (tetti giornalieri, mensili, backfill: spesa e
                              crediti, mai un numero di bandi — giro 3, §1)
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


#: La risorsa pubblica CKAN di IndicePA (`enti.xlsx`), misurata il 30/09/2026
#: (misure-giro-2-percorso-a.md, M10). `INDICEPA_URL` serve solo a cambiarla.
INDICEPA_URL_PREDEFINITO = (
    "https://indicepa.gov.it/ipa-dati/dataset/5baa3eb8-266e-455a-8de8-b1f434c279b2/"
    "resource/d09adf99-dc10-4349-8c53-27b1e5aa97b6/download/enti.xlsx"
)


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
    # v11: tetti di spesa e crediti, giornalieri, mensili e backfill separati
    # (A23: il backfill ha contatori propri e non entra nel mensile). Dal giro 3
    # nessun tetto di numero (§1): `TETTO_FETCH_GIRO` e
    # `TETTO_CLASSIFICAZIONI_GIORNO` sono dismessi (vedi `VARIABILI_DISMESSE`).
    tetto_ricerche_giorno: int
    tetto_crediti_giorno: int
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
    # L'interruttore per tipo (contratto di ottobre 2026, §3): con
    # MONITOR_MODALITA=ombra, gli eventi di questi tipi nati nel giro e ammessi
    # dai gate si applicano e si rendono leggibili; gli altri restano in ombra.
    # `_ignorati` sono i valori scartati perche' il monitor non li produce:
    # alimentano l'allarme del giro e di `salute`.
    monitor_tipi_attivi: tuple[str, ...] = ()
    monitor_tipi_attivi_ignorati: tuple[str, ...] = ()
    # Percorso A del giro 2 (contratto `bandi-giro-2` §12 e §19.11): il passo
    # verifica-stato, la sosta all'ingresso, i gemelli e IndicePA. Tutti con un
    # default, cosi' chi costruisce `Settings` a mano non deve conoscerli.
    verifica_stato_modalita: str = "ombra"         # ombra | attivo
    verifica_stato_tetto_s: int = 1800
    verifica_stato_usa_modello: bool = True
    ingresso_sosta_giri: int = 4
    indicepa_url: str = INDICEPA_URL_PREDEFINITO
    #: Le variabili di questo gruppo scartate perche' fuori enum o fuori
    #: intervallo (tornano al default): alimentano configurazione:verifica_stato.
    verifica_stato_scartate: tuple[str, ...] = ()
    # Giro 3 (contratto `bandi-giro-3` §3): interruttori propri di gemelli e
    # import di IndicePA (non piu' VERIFICA_STATO_MODALITA) e il tetto di
    # TEMPO di ogni passo della manutenzione, l'unico freno ammesso oltre a
    # cortesia, spesa e guardie (§1: niente lotti).
    gemelli_modalita: str = "ombra"                # ombra | attivo
    domini_modalita: str = "ombra"                 # ombra | attivo
    tempo_precoce_s: int = 600
    tempo_ricontrolli_s: int = 3600
    tempo_link_verifica_s: int = 1200
    tempo_rielaborazione_s: int = 3600
    tempo_monitor_s: int = 3600
    #: I NOMI (mai i valori) delle variabili del giro 3 scartate perche' fuori
    #: enum o fuori intervallo (tornano al default): `salute` li porta come
    #: allarme `configurazione:<nome>`.
    configurazione_scartate: tuple[str, ...] = ()
    #: I NOMI (mai i valori) delle variabili dismesse ancora presenti
    #: nell'ambiente (`VARIABILI_DISMESSE`): nessuno le legge piu', e `salute`
    #: lo dice come informazione, non come allarme (giro 3, §3).
    variabili_dismesse: tuple[str, ...] = ()

    @property
    def verifica_stato_config_valida(self) -> bool:
        return not self.verifica_stato_scartate

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


def _intero_in_intervallo(
    name: str, scartate: list[str],
    intervalli: Mapping[str, tuple[int, int, int]] | None = None,
) -> int:
    """Un intero di `INTERVALLI_VERIFICA` (o di `intervalli`): non numerico o
    fuori intervallo → default, e il nome finisce in `scartate` (mai
    un'eccezione all'avvio)."""
    default, minimo, massimo = (intervalli or INTERVALLI_VERIFICA)[name]
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        valore = int(raw.strip())
    except ValueError:
        scartate.append(name)
        return default
    if not minimo <= valore <= massimo:
        scartate.append(name)
        return default
    return valore


def _modalita_verifica(scartate: list[str], name: str = "VERIFICA_STATO_MODALITA") -> str:
    """`VERIFICA_STATO_MODALITA` (o `name`): ombra | attivo; un valore
    sconosciuto vale ombra e il nome finisce in `scartate`."""
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return "ombra"
    if raw in MODALITA:
        return raw
    scartate.append(name)
    return "ombra"


def _indicepa_url(scartate: list[str]) -> str:
    raw = os.getenv("INDICEPA_URL", "").strip()
    if not raw:
        return INDICEPA_URL_PREDEFINITO
    if not raw.startswith("https://"):
        scartate.append("INDICEPA_URL")
        return INDICEPA_URL_PREDEFINITO
    return raw


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# --- v11: default per scenario, listino e parsing ---------------------------

# Tetti per scenario (§6.2 e A23): spesa e crediti. Fino al giro 2 c'era anche
# un tetto per giro sul fetch, dismesso con la regola «niente lotti».
#
# I $ sono quelli del giro 3 (contratto `bandi-giro-3` §3 e §4): 5 $ al giorno
# e 150 al mese nel bilanciato, su tutto cio' che chiama un modello in regime.
_TETTI_SCENARIO: dict[str, dict[str, float]] = {
    "economico":  {"usd_giorno": 3.0, "crediti_mese": 3800, "usd_mese": 90.0},
    "bilanciato": {"usd_giorno": 5.0, "crediti_mese": 5000, "usd_mese": 150.0},
    "massimo":    {"usd_giorno": 10.0, "crediti_mese": 6500, "usd_mese": 300.0},
}
SCENARI = tuple(_TETTI_SCENARIO)
MODALITA = ("ombra", "attivo")

#: Intervalli ammessi delle variabili del percorso A (§12, §19.11): fuori
#: intervallo si torna al default e si dice (configurazione:verifica_stato).
INTERVALLI_VERIFICA: dict[str, tuple[int, int, int]] = {
    # nome: (default, minimo, massimo)
    # Giro 3 (§3, §13): l'unico freno della verifica e' il tempo.
    "VERIFICA_STATO_TETTO_S": (1800, 60, 3600),
    "INGRESSO_SOSTA_GIRI": (4, 0, 12),
}

#: Le variabili dismesse con il giro 3 (§1 «niente lotti», §3): nessun modulo
#: le legge piu'. Se una e' ancora nell'ambiente, `Settings.variabili_dismesse`
#: ne riporta il NOME (mai il valore) e `salute` lo dice come informazione.
VARIABILI_DISMESSE: tuple[str, ...] = (
    "TETTO_CLASSIFICAZIONI_GIORNO", "TETTO_FETCH_GIRO", "VERIFICA_STATO_TETTO_LETTURE",
    "VERIFICA_STATO_MAX_CHIUSURE", "VERIFICA_STATO_TETTO_INGRESSO", "GEMELLI_FUSIONI_PER_GIRO",
)

#: Il tetto di tempo di ogni passo del giro 3 (§1 punto 2, §3), in secondi:
#: chi resta fuori parte per primo al giro dopo. Fuori intervallo si torna al
#: default e si dice (`configurazione_scartate` → configurazione:<nome>).
INTERVALLI_TEMPI: dict[str, tuple[int, int, int]] = {
    # nome: (default, minimo, massimo)
    "TEMPO_PRECOCE_S": (600, 60, 7200),
    "TEMPO_RICONTROLLI_S": (3600, 60, 7200),
    "TEMPO_LINK_VERIFICA_S": (1200, 60, 7200),
    "TEMPO_RIELABORAZIONE_S": (3600, 60, 7200),
    "TEMPO_MONITOR_S": (3600, 60, 7200),
}

#: Gli interruttori del giro 3 (§3): ombra | attivo, default ombra.
MODALITA_GIRO_3: tuple[str, ...] = ("GEMELLI_MODALITA", "DOMINI_MODALITA")

#: Il valore di `MONITOR_TIPI_ATTIVI` che vale «tutti i tipi del monitor».
TUTTI_I_TIPI = "tutti"

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

# Contatore separato del backfill (A23): non entra nel tetto mensile.
_BACKFILL_CREDITI = 8000
_BACKFILL_USD = 60.0

# Le quattro ore dello scheduler (`backend/app/bandi_sender.py`). Vivono qui e
# non la' perche' `MONITOR_GIRI` si confronta con questo insieme: un giro
# dichiarato a un'ora in cui la pipeline non parte mai e' uno step di
# monitoraggio spento in silenzio, cioe' il guasto peggiore del piano.
GIRI_SCHEDULER: tuple[str, ...] = ("00:00", "06:00", "12:00", "18:00")

# Giro 3 (§2): la manutenzione gira a ogni giro dello scheduler.
_GIRI_DEFAULT = GIRI_SCHEDULER

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


def _tipi_attivi_env(name: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """"faq,proroga" -> ((tipi ammessi), (valori ignorati)).

    Ammessi sono solo i tipi che il monitor produce (`eventi.TIPI_PROPONIBILI`).
    Un valore sconosciuto si scarta con un allarme e non ferma niente: un
    `profroga` scritto male non deve impedire l'avvio del sender, ma nemmeno
    passare inosservato, perche' vorrebbe dire un tipo rimasto in ombra.

    `tutti` (giro 3, §3), anche in mezzo ad altre voci, vale i 12 tipi del
    monitor nell'ordine di `TIPI_PROPONIBILI`. Il filtro su sospensione,
    revoca e annullamento della revoca (migrazione 14 e
    `MONITOR_STATI_ESTESI`) non sta qui: lo fa il monitor, che legge il DB.
    """
    grezzo = os.getenv(name, "").strip()
    if not grezzo:
        return (), ()
    # Import pigro: `settings` lo importano quasi tutti, `eventi` no.
    from .eventi import TIPI_PROPONIBILI
    validi: list[str] = []
    ignorati: list[str] = []
    voci = [pezzo.strip().lower() for pezzo in grezzo.split(",")]
    for tipo in voci:
        if tipo and tipo != TUTTI_I_TIPI:
            (validi if tipo in TIPI_PROPONIBILI else ignorati).append(tipo)
    if TUTTI_I_TIPI in voci:
        # L'ordine resta quello del monitor, non quello in cui li ha scritti
        # chi ha compilato il `.env`; un refuso accanto a `tutti` resta un
        # allarme, perche' qualcuno credeva di scrivere un tipo.
        validi = list(TIPI_PROPONIBILI)
    if ignorati:
        logger.warning(
            "[ALLARME] [settings] {}: valori ignorati {} (ammessi solo i tipi del monitor {})",
            name, ignorati, list(TIPI_PROPONIBILI),
        )
    return tuple(dict.fromkeys(validi)), tuple(dict.fromkeys(ignorati))


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
    tipi_attivi, tipi_ignorati = _tipi_attivi_env("MONITOR_TIPI_ATTIVI")
    scartate_verifica: list[str] = []
    modalita_verifica = _modalita_verifica(scartate_verifica)
    interi_verifica = {nome: _intero_in_intervallo(nome, scartate_verifica)
                       for nome in INTERVALLI_VERIFICA}
    indicepa = _indicepa_url(scartate_verifica)
    scartate_giro_3: list[str] = []
    modalita_giro_3 = {nome: _modalita_verifica(scartate_giro_3, nome) for nome in MODALITA_GIRO_3}
    tempi = {nome: _intero_in_intervallo(nome, scartate_giro_3, INTERVALLI_TEMPI)
             for nome in INTERVALLI_TEMPI}
    if scartate_giro_3:
        # Solo i nomi: il valore di una variabile scritta male puo' essere
        # qualunque cosa, anche un segreto incollato nella riga sbagliata.
        logger.warning(
            "[ALLARME] [settings] variabili non valide, tornate al default: {}",
            scartate_giro_3,
        )

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
        tetto_ricerche_giorno=max(0, _int_env("TETTO_RICERCHE_GIORNO", _RICERCHE_GIORNO)),
        tetto_crediti_giorno=max(0, _int_env("TETTO_CREDITI_GIORNO", _CREDITI_GIORNO)),
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
        monitor_tipi_attivi=tipi_attivi,
        monitor_tipi_attivi_ignorati=tipi_ignorati,
        verifica_stato_modalita=modalita_verifica,
        verifica_stato_tetto_s=interi_verifica["VERIFICA_STATO_TETTO_S"],
        verifica_stato_usa_modello=bool_env("VERIFICA_STATO_USA_MODELLO", True),
        ingresso_sosta_giri=interi_verifica["INGRESSO_SOSTA_GIRI"],
        indicepa_url=indicepa,
        verifica_stato_scartate=tuple(scartate_verifica),
        gemelli_modalita=modalita_giro_3["GEMELLI_MODALITA"],
        domini_modalita=modalita_giro_3["DOMINI_MODALITA"],
        tempo_precoce_s=tempi["TEMPO_PRECOCE_S"],
        tempo_ricontrolli_s=tempi["TEMPO_RICONTROLLI_S"],
        tempo_link_verifica_s=tempi["TEMPO_LINK_VERIFICA_S"],
        tempo_rielaborazione_s=tempi["TEMPO_RIELABORAZIONE_S"],
        tempo_monitor_s=tempi["TEMPO_MONITOR_S"],
        configurazione_scartate=tuple(scartate_giro_3),
        # Solo i nomi, e solo di quelle presenti: il valore non serve a niente
        # (nessuno lo legge) e potrebbe essere qualunque cosa.
        variabili_dismesse=tuple(nome for nome in VARIABILI_DISMESSE if nome in os.environ),
    )
