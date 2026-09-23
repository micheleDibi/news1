"""Login flow per https://www.obiettivoeuropa.com (Django CSRF).

Senza login l'API `/api/call/` ritorna max 5 risultati per pagina; con login
ne ritorna 50. Per questo una sessione e' considerata valida SOLO se la prima
pagina dell'API restituisce almeno RISULTATI_MINIMI_AUTENTICATO record: il
cookie `sessionid` da solo non basta (puo' essere scaduto o anonimo).

Flusso:
  1. GET /account/login/ con Accept: text/html → estrai csrfmiddlewaretoken
  2. POST /account/login/ con form-urlencoded {csrfmiddlewaretoken, login, password}
  3. Verifica 'sessionid' presente in session.cookies
  4. valida_sessione(): GET /api/call/?page=1 e len(results) >= 50
  5. Ritorna la requests.Session pronta (Accept: application/json per API)

Rinnovo: se login o validazione falliscono si riprova con backoff BACKOFF_S
(60/120/240 s) fino a TENTATIVI_MAX tentativi complessivi, poi si solleva
SessioneOEError. MAI ripiego su una sessione anonima: chi chiama deve far
fallire la fonte.

Cache in-process: ottenere una nuova sessione e' costoso (3 round-trip HTTP),
quindi memorizziamo la session per processo e la rivalidiamo con l'API a ogni
richiesta. Il sender 4x/day fa restart → si ottiene una session fresca ad ogni
ciclo; clear_cache() forza il rinnovo.

Segreti: username, password, CSRF e sessionid non compaiono mai nei log ne'
nei messaggi delle eccezioni. Attenzione anche ai traceback: loguru con
`diagnose=True` stampa i valori delle variabili citate sulla riga che
fallisce, quindi le credenziali viaggiano dentro oggetti con repr opaco
(Credenziali, _FormLogin) e mai come nomi semplici sulle righe che possono
sollevare.
"""
from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import requests

from ...logger import logger
from ...settings import get_settings


_BASE_URL = "https://www.obiettivoeuropa.com"
_LOGIN_URL = f"{_BASE_URL}/account/login/"
_API_PRIMA_PAGINA_URL = f"{_BASE_URL}/api/call/?page=1"

# Soglia di autenticazione: anonimo = 5 record/pagina, autenticato = 50.
RISULTATI_MINIMI_AUTENTICATO = 50
# Tentativi complessivi di login (il primo e' immediato, i successivi dopo
# l'attesa corrispondente in BACKOFF_S).
TENTATIVI_MAX = 3
BACKOFF_S: tuple[int, ...] = (60, 120, 240)


class SessioneOEError(RuntimeError):
    """Sessione Obiettivo Europa non ottenibile o non autenticata.

    Il messaggio non contiene mai credenziali, CSRF o cookie.
    """


@dataclass(frozen=True)
class Credenziali:
    """Coppia username/password con repr opaco.

    `repr=False` sui campi: i valori non devono comparire nemmeno nei
    traceback con `diagnose` di loguru. Iterabile per l'unpacking `*cred`.
    """
    username: str = field(repr=False)
    password: str = field(repr=False)

    def __iter__(self):
        yield self.username
        yield self.password

    def __bool__(self) -> bool:
        return bool(self.username) and bool(self.password)


class _FormLogin(dict):
    """Payload del POST di login: dict con repr che nasconde i valori."""

    def __repr__(self) -> str:  # pragma: no cover - solo per i traceback
        return "<form di login: valori nascosti>"


# Cache in-process (Credenziali → Session). Una sola coppia per processo, ma
# usiamo dict per gestire eventuali credenziali multiple.
_session_cache: dict[Credenziali, "requests.Session"] = {}
_cache_lock = threading.Lock()


def conta_risultati_prima_pagina(session: "requests.Session") -> int:
    """Numero di record nella prima pagina dell'API (5 anonimo, 50 autenticato).

    Raises:
        SessioneOEError se la chiamata fallisce o la risposta non e' leggibile.
    """
    try:
        resp = session.get(
            _API_PRIMA_PAGINA_URL, headers={"Accept": "application/json"}, timeout=30,
        )
    except Exception as e:
        raise SessioneOEError(f"GET {_API_PRIMA_PAGINA_URL} fallita: {e}") from e

    if resp.status_code != 200:
        raise SessioneOEError(
            f"GET {_API_PRIMA_PAGINA_URL} status {resp.status_code} (atteso 200)"
        )

    try:
        risultati = resp.json().get("results")
    except Exception as e:
        raise SessioneOEError(
            f"GET {_API_PRIMA_PAGINA_URL}: risposta non interpretabile ({e})"
        ) from e
    if not isinstance(risultati, list):
        raise SessioneOEError(
            f"GET {_API_PRIMA_PAGINA_URL}: campo 'results' assente o non lista"
        )
    return len(risultati)


def valida_sessione(session: "requests.Session") -> bool:
    """True solo se la sessione e' autenticata: prima pagina con >= 50 risultati."""
    try:
        n = conta_risultati_prima_pagina(session)
    except SessioneOEError as e:
        logger.warning("[obiettivo_europa/auth] validazione sessione fallita: {}", e)
        return False
    if n < RISULTATI_MINIMI_AUTENTICATO:
        logger.warning(
            "[obiettivo_europa/auth] sessione non autenticata: {} risultati in prima "
            "pagina (attesi >= {})", n, RISULTATI_MINIMI_AUTENTICATO,
        )
        return False
    return True


def _login(cred: Credenziali) -> "requests.Session":
    """Esegue il login (CSRF + POST) e ritorna la Session con il cookie.

    Non valida la sessione con l'API: lo fa obtain_session().
    """
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
        raise SessioneOEError(f"Impossibile raggiungere {_LOGIN_URL}: {e}") from e

    if login_page.status_code != 200:
        raise SessioneOEError(
            f"GET {_LOGIN_URL} status {login_page.status_code} (atteso 200)"
        )

    # CSRF token estratto da HTML senza quote: <input name=csrfmiddlewaretoken type=hidden value=XXX>
    csrf_match = re.search(
        r'<input[^>]*name=["\']?csrfmiddlewaretoken["\']?[^>]*value=["\']?([A-Za-z0-9]+)',
        login_page.text,
    )
    if not csrf_match:
        raise SessioneOEError(
            "CSRF token non trovato nel form di login. "
            "Il portale potrebbe aver cambiato struttura."
        )
    # Il token NON va loggato, nemmeno troncato.
    form = _FormLogin(
        csrfmiddlewaretoken=csrf_match.group(1),
        login=cred.username,
        password=cred.password,
    )

    # Step 2: POST login (form-urlencoded). Headers gia' settati sopra.
    try:
        response = session.post(_LOGIN_URL, data=form, timeout=30, allow_redirects=True)
    except Exception as e:
        raise SessioneOEError(f"POST login fallito: {e}") from e

    # Step 3: verifica sessionid in cookie
    if "sessionid" not in session.cookies:
        raise SessioneOEError(
            f"Login fallito: sessionid non in cookies "
            f"(status={response.status_code}, url={response.url}). "
            f"Verifica credenziali OBIETTIVO_EUROPA_USERNAME/PASSWORD."
        )

    # Step 4: ripristina Accept JSON per API successive
    session.headers["Accept"] = "application/json"
    return session


def obtain_session(
    username: str,
    password: str,
    *,
    attesa: Callable[[float], None] = time.sleep,
    tentativi_max: int = TENTATIVI_MAX,
) -> "requests.Session":
    """Ritorna una requests.Session autenticata e validata con l'API.

    Args:
        username: email account.
        password: password account.
        attesa: funzione di attesa per il backoff (iniettabile nei test).
        tentativi_max: tentativi complessivi di login prima di arrendersi.

    Raises:
        SessioneOEError se le credenziali mancano o se, dopo tentativi_max
        tentativi, il login fallisce oppure la prima pagina dell'API resta
        sotto RISULTATI_MINIMI_AUTENTICATO (sessione anonima). Il messaggio
        non contiene mai username/password.

    Note: la session resta in cache per il processo e viene rivalidata con
    l'API a ogni chiamata; se non e' piu' valida si rinnova. Per forzare un
    refresh chiama clear_cache().
    """
    cred = Credenziali(username or "", password or "")
    if not cred:
        raise SessioneOEError(
            "Credenziali Obiettivo Europa mancanti. "
            "Imposta OBIETTIVO_EUROPA_USERNAME e OBIETTIVO_EUROPA_PASSWORD in .env"
        )

    with _cache_lock:
        cached = _session_cache.get(cred)
    if cached is not None:
        # La validazione fa una GET: fuori dal lock.
        if valida_sessione(cached):
            return cached
        logger.info("[obiettivo_europa/auth] sessione in cache non piu' valida: rinnovo")
        with _cache_lock:
            if _session_cache.get(cred) is cached:
                _session_cache.pop(cred, None)

    ultimo_errore: SessioneOEError | None = None
    for tentativo in range(1, tentativi_max + 1):
        try:
            session = _login(cred)
            n = conta_risultati_prima_pagina(session)
            if n < RISULTATI_MINIMI_AUTENTICATO:
                raise SessioneOEError(
                    f"sessione non autenticata: la prima pagina dell'API restituisce "
                    f"{n} risultati (attesi >= {RISULTATI_MINIMI_AUTENTICATO})"
                )
        except SessioneOEError as e:
            ultimo_errore = e
            logger.warning(
                "[obiettivo_europa/auth] login tentativo {}/{} fallito: {}",
                tentativo, tentativi_max, e,
            )
            if tentativo < tentativi_max:
                pausa = BACKOFF_S[min(tentativo - 1, len(BACKOFF_S) - 1)]
                logger.info("[obiettivo_europa/auth] nuovo tentativo tra {} s", pausa)
                attesa(pausa)
            continue

        logger.info(
            "[obiettivo_europa/auth] login OK | sessione autenticata ({} risultati in prima pagina)",
            n,
        )
        with _cache_lock:
            _session_cache[cred] = session
        return session

    raise SessioneOEError(
        f"login Obiettivo Europa fallito dopo {tentativi_max} tentativi: {ultimo_errore}"
    ) from ultimo_errore


def clear_cache() -> None:
    """Svuota la cache delle sessioni (utile per testing o force-refresh)."""
    with _cache_lock:
        _session_cache.clear()
