"""Loguru setup: console (colored) + file daily-rotated.

- stderr: livello da SCRAPER_BANDI_LOG_LEVEL (default INFO).
- file:   DEBUG, in SCRAPER_BANDI_LOG_DIR (default `scraper_bandi/logs/`);
          la cartella e il file vengono creati al primo messaggio
          (`delay=True`), non all'import. Rotation 00:00, retention 30 giorni.
- redazione: su ENTRAMBI i sink i valori dei segreti noti vengono sostituiti
  da [REDATTO] tramite il `patcher` di loguru, che modifica record['message']
  prima che qualunque handler lo formatti. L'elenco delle parole e'
  `_PAROLE_SEGRETE` e comprende i nomi realmente in uso in questo repo
  (`obiettivo_europa_password`, `supabase_service_key`, `anthropic_api_key`,
  `firecrawl_api_key`, l'header `apikey`), non solo quelli generici.
- `diagnose=False` su entrambi i sink: con `diagnose=True` loguru stampa sotto
  ogni riga di un traceback il repr delle variabili del frame, e il patcher
  lavora su `record['message']`, **non** su quell'annotazione. Un
  `logger.exception` dentro il monitor avrebbe stampato `Settings` intero.
"""
import os
import re
import sys
from pathlib import Path

from loguru import logger

_LIVELLI_NOTI = {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}
_LIVELLO_STDERR_DEFAULT = "INFO"
_CARTELLA_LOG_DEFAULT = Path(__file__).resolve().parent.parent / "logs"

REDATTO = "[REDATTO]"

# Le parole che fanno di una chiave un segreto. Sono quelle in uso qui dentro,
# non un elenco di scuola: `SUPABASE_SERVICE_KEY_BANDI`, `ANTHROPIC_API_KEY`,
# `FIRECRAWL_API_KEY`, `OBIETTIVO_EUROPA_PASSWORD`, l'header `apikey` che
# `db.py` costruisce, piu' i token delle sessioni scaricate.
_PAROLE_SEGRETE = (
    r"sessionid|csrf(?:middleware)?token|passw(?:or)?d|api[_-]?key|apikey|"
    r"service[_-]?key|secret|access[_-]?token|auth[_-]?token|refresh[_-]?token|"
    r"bearer"
)

# `chiave=valore`, `chiave: valore`, `'chiave': 'valore'` (query string,
# cookie, dict/JSON): restano la chiave, il separatore e l'eventuale apice di
# apertura; il valore diventa [REDATTO]. Il lookahead rende la sostituzione
# idempotente su testo gia' redatto.
#
# Niente `\b` davanti: `\b` non scatta dopo un underscore (`_` e `p` sono
# entrambi word char), quindi `obiettivo_europa_password=…` **non** veniva
# redatto benche' il docstring lo dichiarasse. Al suo posto si ammette
# qualunque prefisso e qualunque suffisso di nome: e' cosi' che entrano
# `supabase_service_key`, `anthropic_api_key`, `x-api-key`.
_PATTERN_CHIAVE_VALORE = re.compile(
    r"""(?P<prefisso>[A-Za-z0-9_.\-]*(?:""" + _PAROLE_SEGRETE + r""")[A-Za-z0-9_.\-]*['"]?\s*[=:]\s*['"]?)"""
    r"""(?!\[REDATTO\])(?P<valore>[^\s'",;&}\]]+)""",
    re.IGNORECASE,
)
# `Authorization: Bearer <token>` (anche Basic/Token; anche come `Authorization=`).
_PATTERN_AUTHORIZATION = re.compile(
    r"""(?P<prefisso>\bAuthorization['"]?\s*[=:]\s*['"]?(?:Bearer|Basic|Token)\s+)"""
    r"""(?!\[REDATTO\])(?P<valore>[^\s'",;&}\]]+)""",
    re.IGNORECASE,
)


def redigi(testo: str) -> str:
    """Sostituisce con [REDATTO] i valori dei segreti noti; il resto e' intatto."""
    testo = _PATTERN_CHIAVE_VALORE.sub(lambda m: m.group("prefisso") + REDATTO, testo)
    testo = _PATTERN_AUTHORIZATION.sub(lambda m: m.group("prefisso") + REDATTO, testo)
    return testo


def _redigi_record(record: dict) -> None:
    """Patcher loguru: applicato a ogni record prima di tutti i sink."""
    record["message"] = redigi(record["message"])


def cartella_log() -> Path:
    """Cartella dei file di log: SCRAPER_BANDI_LOG_DIR, se vuota il default."""
    valore = os.getenv("SCRAPER_BANDI_LOG_DIR", "").strip()
    return Path(valore).expanduser() if valore else _CARTELLA_LOG_DEFAULT


def livello_stderr() -> str:
    """Livello del sink stderr: SCRAPER_BANDI_LOG_LEVEL, se vuoto o ignoto INFO."""
    valore = os.getenv("SCRAPER_BANDI_LOG_LEVEL", "").strip().upper()
    return valore if valore in _LIVELLI_NOTI else _LIVELLO_STDERR_DEFAULT


# Rimuovi l'handler di default
logger.remove()

# Redazione dei segreti prima di qualunque handler (stderr e file)
logger.configure(patcher=_redigi_record)

# Console handler
logger.add(
    sys.stderr,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    ),
    level=livello_stderr(),
    colorize=True,
    backtrace=True,
    # Il patcher redige `record['message']`; l'annotazione di `diagnose`
    # e' un'altra cosa e stamperebbe il repr delle variabili di ogni frame,
    # `Settings` compreso. Il traceback resta (backtrace), i valori no.
    diagnose=False,
)

# File handler (cartella e file creati al primo messaggio: delay=True)
logger.add(
    str(cartella_log() / "scraper-bandi-{time:YYYY-MM-DD}.log"),
    format="[{time:YYYY-MM-DD HH:mm:ss.SSS}] [{level: <8}] [{name}:{function}:{line}] {message}",
    level="DEBUG",
    rotation="00:00",
    retention="30 days",
    enqueue=True,
    encoding="utf-8",
    delay=True,
    backtrace=True,
    diagnose=False,
)

__all__ = ["logger", "redigi", "cartella_log", "livello_stderr"]
