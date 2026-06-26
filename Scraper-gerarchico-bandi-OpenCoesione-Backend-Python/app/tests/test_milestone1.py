"""
Test Milestone 1 — Fondamenta infrastrutturali.

Richiede un file .env valido con DATABASE_URL, SUPABASE_URL, SUPABASE_KEY.
SOURCE_ROOT_URL ha un default in settings ma puo' essere sovrascritta via .env.
Eseguire con:  pytest app/tests/test_milestone1.py -v
"""
import uuid

import pytest

from app.config.session import new_session_id, get_session_id, reset_session_id


# ---------------------------------------------------------------------------
# Test 1: caricamento variabili ambiente
# ---------------------------------------------------------------------------
def test_env_variables_loaded():
    from app.config.settings import settings
    assert settings.database_url, "DATABASE_URL non impostata"
    assert settings.supabase_url, "SUPABASE_URL non impostata"
    assert settings.supabase_key, "SUPABASE_KEY non impostata"
    assert settings.source_root_url, "SOURCE_ROOT_URL non impostata"


# ---------------------------------------------------------------------------
# Test 2: inizializzazione logger
# ---------------------------------------------------------------------------
def test_logger_init():
    from app.config.logging import configure_logging, get_logger
    configure_logging()
    log = get_logger(__name__)
    # Non deve sollevare eccezioni
    log.info("test log milestone 1", test_case="logger_init")


# ---------------------------------------------------------------------------
# Test 3: creazione e recupero session_id
# ---------------------------------------------------------------------------
def test_session_id_creation():
    reset_session_id()
    sid = new_session_id()
    assert isinstance(sid, uuid.UUID)
    assert get_session_id() == sid


def test_session_id_reset():
    new_session_id()
    reset_session_id()
    assert get_session_id() is None


# ---------------------------------------------------------------------------
# Test 4: connessione DB (richiede .env con DATABASE_URL valido)
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_db_connection():
    from app.db.connection import test_connection
    assert test_connection() is True


# ---------------------------------------------------------------------------
# Test 5: lettura tabelle di riferimento
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_read_categoria_programma():
    from app.repos.base import CategoriaProgrammaRepo
    repo = CategoriaProgrammaRepo()
    categorie = repo.get_all()
    # Può essere lista vuota se il DB è vuoto, ma non deve sollevare eccezioni
    assert isinstance(categorie, list)


@pytest.mark.integration
def test_read_fonte():
    from app.repos.base import FonteRepo
    repo = FonteRepo()
    fonti = repo.get_all_active()
    assert isinstance(fonti, list)
