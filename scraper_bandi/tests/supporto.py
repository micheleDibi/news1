# -*- coding: utf-8 -*-
"""Supporto ai test di scraper_bandi: carica il package `app` per percorso con
alias `scraper_app`, senza toccare `sys.path` e senza importare il logger reale.

Perche' cosi':
  - su questa macchina esiste un altro package chiamato `app` sul sys.path
    (altro progetto): `from app import ...` prenderebbe quello;
  - `app/logger.py` crea `logs/` e apre un file di log al primo import: nei
    test lo sostituiamo con uno stub che scrive solo su stderr (WARNING+);
  - `app/settings.py` pretende le variabili del DB: mettiamo valori fittizi
    PRIMA di ogni import, cosi' `load_dotenv` (override=False) non carica
    quelli veri e nessun test puo' raggiungere il DB per sbaglio.

Uso nei test:

    from tests.supporto import carica_modulo
    date_validation = carica_modulo("date_validation")
    csv_parser = carica_modulo("scrapers.csv_parser")

Comando (dalla cartella scraper_bandi, con il venv):

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import types
from pathlib import Path

sys.dont_write_bytecode = True

RADICE = Path(__file__).resolve().parents[1]          # scraper_bandi/
APP = RADICE / "app"
REPO = RADICE.parent                                   # news1/
ALIAS = "scraper_app"

# Valori fittizi, mai usati per la rete: servono solo a superare i controlli
# di settings.py. Non sovrascrivono variabili gia' presenti nell'ambiente.
_ENV_FITTIZIO = {
    "SUPABASE_URL_BANDI": "https://test.invalid",
    "SUPABASE_SERVICE_KEY_BANDI": "chiave-di-test-non-valida",
    "FIRECRAWL_API_KEY": "",
    "ANTHROPIC_API_KEY": "",
    "OBIETTIVO_EUROPA_USERNAME": "",
    "OBIETTIVO_EUROPA_PASSWORD": "",
    "SCRAPER_BANDI_LOG_DIR": "",
}


def _stub_logger() -> types.ModuleType:
    """Modulo `scraper_app.logger` di test: loguru su stderr, solo WARNING+.

    `redigi` e' quello vero, importato dal file per percorso: e' la funzione che
    toglie sessionid, token e password dai messaggi, e uno stub che la
    sostituisse con l'identita' renderebbe verdi proprio i test che la
    verificano.
    """
    from loguru import logger as _logger

    # Il modulo vero si carica PRIMA della riconfigurazione: all'import
    # aggiunge i propri sink (stderr e file, quest'ultimo con `delay=True`,
    # quindi nessuna cartella `logs/` viene creata) e installa il patcher di
    # redazione. La `remove()` subito dopo li toglie tutti e lascia in piedi
    # solo lo stderr dei test; il patcher, che e' cio' che vogliamo, resta.
    vero = carica_per_percorso("_logger_vero", APP / "logger.py")
    _logger.remove()
    _logger.add(sys.stderr, level=os.environ.get("SCRAPER_BANDI_TEST_LOG", "WARNING"))
    modulo = types.ModuleType(f"{ALIAS}.logger")
    modulo.logger = _logger
    modulo.redigi = vero.redigi
    modulo.__all__ = ["logger", "redigi"]
    return modulo


def _registra_package() -> None:
    if ALIAS in sys.modules:
        return
    for chiave, valore in _ENV_FITTIZIO.items():
        os.environ.setdefault(chiave, valore)
    spec = importlib.util.spec_from_file_location(
        ALIAS, APP / "__init__.py", submodule_search_locations=[str(APP)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[ALIAS] = package
    # Lo stub del logger va registrato PRIMA di eseguire qualunque sottomodulo:
    # `from .logger import logger` trova `scraper_app.logger` in sys.modules.
    sys.modules[f"{ALIAS}.logger"] = _stub_logger()
    spec.loader.exec_module(package)


def carica_modulo(nome_relativo: str) -> types.ModuleType:
    """Importa `app.<nome_relativo>` (con i punti) sotto l'alias `scraper_app`."""
    _registra_package()
    return importlib.import_module(f"{ALIAS}.{nome_relativo}")


def carica_per_percorso(nome: str, percorso: Path) -> types.ModuleType:
    """Carica un singolo file Python senza package (per i gemelli senza import
    interni, es. backend/app/slug.py)."""
    spec = importlib.util.spec_from_file_location(nome, percorso)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo
