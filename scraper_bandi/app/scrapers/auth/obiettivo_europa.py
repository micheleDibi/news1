"""Login flow per https://www.obiettivoeuropa.com (Django CSRF).

Senza login l'API `/api/call/` ritorna max 5 risultati per pagina; con login
si accede all'intero dataset.

Flusso:
  1. GET /account/login/ con Accept: text/html → estrai csrfmiddlewaretoken
  2. POST /account/login/ con form-urlencoded {csrfmiddlewaretoken, login, password}
  3. Verifica 'sessionid' presente in session.cookies
  4. Ritorna la requests.Session pronta (Accept: application/json per API)

Cache in-process: ottenere una nuova sessione e' costoso (2 round-trip HTTP),
quindi memorizziamo la session per processo. Il sender 4x/day fa restart →
si ottiene una session fresca ad ogni ciclo.
"""
from __future__ import annotations

import re
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import requests

from ...logger import logger
from ...settings import get_settings


_LOGIN_URL = "https://www.obiettivoeuropa.com/account/login/"
_BASE_URL = "https://www.obiettivoeuropa.com"

# Cache in-process (key=(username,password) → Session). Una sola coppia per
# processo, ma usiamo dict per gestire eventuali credenziali multiple.
_session_cache: dict[tuple[str, str], "requests.Session"] = {}
_cache_lock = threading.Lock()


def obtain_session(username: str, password: str) -> "requests.Session":
    """Ritorna una requests.Session autenticata.

    Args:
        username: email account.
        password: password account.

    Raises:
        RuntimeError se login fallisce (credenziali errate, CSRF cambiato,
        portale irraggiungibile).

    Note: la session resta in cache per il processo. Se vuoi forzare un
    refresh (es. dopo session expire), chiama clear_cache().
    """
    if not username or not password:
        raise RuntimeError(
            "Credenziali Obiettivo Europa mancanti. "
            "Imposta OBIETTIVO_EUROPA_USERNAME e OBIETTIVO_EUROPA_PASSWORD in .env"
        )

    cache_key = (username, password)
    with _cache_lock:
        cached = _session_cache.get(cache_key)
        if cached is not None:
            # Sanity check: cookie ancora valido?
            if "sessionid" in cached.cookies:
                return cached
            # Cookie scaduto → drop e ri-autentica
            _session_cache.pop(cache_key, None)

    import requests
    settings = get_settings()

    session = requests.Session()
    session.headers.update({
        "User-Agent": settings.http_user_agent,
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": _LOGIN_URL,
        "Origin": _BASE_URL,
    })

    # Step 1: GET pagina login per CSRF token. Necessitiamo Accept=html qui.
    try:
        session.headers["Accept"] = "text/html,application/xhtml+xml"
        login_page = session.get(_LOGIN_URL, timeout=30)
    except Exception as e:
        raise RuntimeError(f"Impossibile raggiungere {_LOGIN_URL}: {e}") from e

    if login_page.status_code != 200:
        raise RuntimeError(
            f"GET {_LOGIN_URL} status {login_page.status_code} (atteso 200)"
        )

    # CSRF token estratto da HTML senza quote: <input name=csrfmiddlewaretoken type=hidden value=XXX>
    csrf_match = re.search(
        r'<input[^>]*name=["\']?csrfmiddlewaretoken["\']?[^>]*value=["\']?([A-Za-z0-9]+)',
        login_page.text,
    )
    if not csrf_match:
        raise RuntimeError(
            "CSRF token non trovato nel form di login. "
            "Il portale potrebbe aver cambiato struttura."
        )
    csrf_token = csrf_match.group(1)
    logger.debug("[obiettivo_europa/auth] CSRF token ottenuto: {}", csrf_token[:12] + "...")

    # Step 2: POST login (form-urlencoded). Headers gia' settati sopra.
    try:
        response = session.post(
            _LOGIN_URL,
            data={
                "csrfmiddlewaretoken": csrf_token,
                "login": username,
                "password": password,
            },
            timeout=30,
            allow_redirects=True,
        )
    except Exception as e:
        raise RuntimeError(f"POST login fallito: {e}") from e

    # Step 3: verifica sessionid in cookie
    if "sessionid" not in session.cookies:
        raise RuntimeError(
            f"Login fallito: sessionid non in cookies "
            f"(status={response.status_code}, url={response.url}). "
            f"Verifica credenziali OBIETTIVO_EUROPA_USERNAME/PASSWORD."
        )

    # Step 4: ripristina Accept JSON per API successive
    session.headers["Accept"] = "application/json"

    logger.info("[obiettivo_europa/auth] login OK | sessionid acquisito")

    with _cache_lock:
        _session_cache[cache_key] = session
    return session


def clear_cache() -> None:
    """Svuota la cache delle sessioni (utile per testing o force-refresh)."""
    with _cache_lock:
        _session_cache.clear()
