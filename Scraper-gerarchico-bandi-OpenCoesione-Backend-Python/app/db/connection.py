import logging
import random
import threading
import time
from contextlib import contextmanager
from typing import Generator
from urllib.parse import urlparse

import psycopg2
import psycopg2.extensions
import psycopg2.extras
import psycopg2.pool
from psycopg2.extensions import connection as Psycopg2Connection
from supabase import create_client, Client

from app.config.settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supabase client (per API REST / realtime se necessario)
# ---------------------------------------------------------------------------
_supabase_client: Client | None = None


def get_supabase_client() -> Client:
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(settings.supabase_url, settings.supabase_key)
        logger.debug("Supabase client inizializzato")
    return _supabase_client


# ---------------------------------------------------------------------------
# Connection pool client-side (psycopg2.pool.ThreadedConnectionPool)
# ---------------------------------------------------------------------------
_connection_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()

# Errori operativi che trattiamo come transienti e ritentiamo con backoff.
# In particolare il pooler Supabase, quando rate-limita o quando un backend
# node ha credenziali stale in cache, risponde con "password authentication
# failed" anche se le credenziali sono corrette: facciamo retry.
_TRANSIENT_ERROR_PATTERNS = (
    "password authentication failed",
    "no route to host",
    "connection reset",
    "server closed the connection",
    "timeout expired",
    "connection refused",
    "could not connect to server",
    "ssl syscall error",
    "eof detected",
)


def _is_dns_failure(exc: BaseException) -> bool:
    err = str(exc).lower()
    return (
        "could not translate host name" in err
        or "network is unreachable" in err
        or "getaddrinfo failed" in err
        or "nodename nor servname provided" in err
    )


def _pooler_connect_kwargs() -> dict:
    parsed_db = urlparse(settings.database_url)
    parsed_supabase = urlparse(settings.supabase_url)
    project_ref = (parsed_supabase.hostname or "").split(".")[0]
    base_user = parsed_db.username or "postgres"
    pooler_user = base_user if "." in base_user else f"{base_user}.{project_ref}"
    return dict(
        dbname=(parsed_db.path or "/postgres").lstrip("/"),
        user=pooler_user,
        password=parsed_db.password,
        host=settings.database_pooler_host,
        port=settings.database_pooler_port,
        sslmode=settings.database_sslmode,
    )


def _build_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Costruisce il pool, tentando prima la direct connection e cadendo sul
    pooler Supabase se l'host della direct non è raggiungibile."""
    minconn = settings.database_pool_min
    maxconn = settings.database_pool_max
    common_kwargs = dict(
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=settings.database_connect_timeout_seconds,
    )

    try:
        pool = psycopg2.pool.ThreadedConnectionPool(
            minconn,
            maxconn,
            dsn=settings.database_url,
            **common_kwargs,
        )
        logger.info(
            "Connection pool inizializzato (direct connection)",
            extra={"min": minconn, "max": maxconn},
        )
        return pool
    except psycopg2.OperationalError as exc:
        if not (settings.database_pooler_host and _is_dns_failure(exc)):
            raise
        parsed_db = urlparse(settings.database_url)
        logger.warning(
            "Connessione diretta non disponibile, attivo pooler-only mode",
            extra={
                "database_host": parsed_db.hostname,
                "pooler_host": settings.database_pooler_host,
                "pooler_port": settings.database_pooler_port,
            },
        )

    pool = psycopg2.pool.ThreadedConnectionPool(
        minconn,
        maxconn,
        **_pooler_connect_kwargs(),
        **common_kwargs,
    )
    logger.info(
        "Connection pool inizializzato (pooler)",
        extra={
            "min": minconn,
            "max": maxconn,
            "pooler_host": settings.database_pooler_host,
            "pooler_port": settings.database_pooler_port,
        },
    )
    return pool


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _connection_pool
    if _connection_pool is None:
        with _pool_lock:
            if _connection_pool is None:
                _connection_pool = _build_pool()
    return _connection_pool


def _is_transient_error(exc: BaseException) -> bool:
    err = str(exc).lower()
    return any(pattern in err for pattern in _TRANSIENT_ERROR_PATTERNS)


def _connection_is_broken(conn: Psycopg2Connection) -> bool:
    if conn.closed:
        return True
    try:
        status = conn.get_transaction_status()
    except psycopg2.Error:
        return True
    return status == psycopg2.extensions.TRANSACTION_STATUS_UNKNOWN


def _acquire_connection() -> Psycopg2Connection:
    """Acquisisce una connessione dal pool, con retry su errori transitori."""
    max_attempts = max(1, settings.database_connect_retry_max)
    base_delay = settings.database_connect_retry_base_delay_seconds
    last_exc: Exception | None = None

    for attempt in range(max_attempts):
        try:
            pool = _get_pool()
            conn = pool.getconn()
            if _connection_is_broken(conn):
                pool.putconn(conn, close=True)
                raise psycopg2.OperationalError("pooled connection is closed or stale")
            return conn
        except psycopg2.OperationalError as exc:
            last_exc = exc
            if attempt == max_attempts - 1 or not _is_transient_error(exc):
                raise
            sleep_for = base_delay * (2 ** attempt) + random.uniform(0, base_delay)
            logger.warning(
                "Errore transitorio acquisizione connessione, retry %d/%d tra %.2fs: %s",
                attempt + 1,
                max_attempts - 1,
                sleep_for,
                exc,
            )
            time.sleep(sleep_for)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("acquisizione connessione fallita senza eccezione registrata")


def get_raw_connection() -> Psycopg2Connection:
    """Apre una connessione NUOVA bypassando il pool. Il chiamante è
    responsabile di chiuderla con `conn.close()`. Per uso normale preferire
    `get_db_connection`, che usa il pool e ha retry su errori transitori."""
    common_kwargs = dict(
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=settings.database_connect_timeout_seconds,
    )
    try:
        return psycopg2.connect(settings.database_url, **common_kwargs)
    except psycopg2.OperationalError as exc:
        if not (settings.database_pooler_host and _is_dns_failure(exc)):
            raise
    return psycopg2.connect(**_pooler_connect_kwargs(), **common_kwargs)


def _release_connection(conn: Psycopg2Connection, *, broken: bool) -> None:
    pool = _get_pool()
    try:
        pool.putconn(conn, close=broken or bool(conn.closed))
    except Exception:
        logger.warning("Errore durante restituzione connessione al pool", exc_info=True)


@contextmanager
def get_db_connection() -> Generator[Psycopg2Connection, None, None]:
    """Context manager che acquisisce/rilascia una conn dal pool e gestisce
    commit/rollback. Connessioni in stato corrotto vengono chiuse anziché
    riciclate."""
    conn = _acquire_connection()
    broken = False
    try:
        try:
            yield conn
            conn.commit()
        except Exception:
            broken = _connection_is_broken(conn)
            if not broken:
                try:
                    conn.rollback()
                except psycopg2.Error:
                    broken = True
            raise
    finally:
        _release_connection(conn, broken=broken)


def close_pool() -> None:
    """Chiude tutte le connessioni nel pool. Utile a fine processo o nei test."""
    global _connection_pool
    with _pool_lock:
        if _connection_pool is not None:
            try:
                _connection_pool.closeall()
            finally:
                _connection_pool = None


def test_connection() -> bool:
    """Verifica la connessione al DB. Restituisce True se OK, solleva eccezione altrimenti."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            result = cur.fetchone()
    ok = result is not None
    if ok:
        logger.info("Connessione al database verificata con successo")
    return ok
