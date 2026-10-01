"""HTTP client condiviso con throttling per host.

Garantisce un delay minimo (default 1s) tra request consecutive verso
lo stesso host, indipendentemente da quante fonti stiano scrappando.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

import httpx

from .logger import logger
from .settings import get_settings


# Timestamp ultima request per host (monotonic time)
_HOST_LAST_REQUEST: dict[str, float] = {}


def _throttle_delay_s() -> float:
    return get_settings().host_throttle_delay_s


async def _wait_for_host(host: str) -> None:
    """Aspetta il proprio turno sull'host: fra due richieste almeno `delay`.

    Lo slot si **prenota prima di dormire** (giro 3, contratto §7): fra la
    lettura dell'ultimo slot e la scrittura del proprio non c'e' nessun
    `await`, quindi due coroutine in parallelo non possono leggere lo stesso
    valore. Prima l'aggiornamento avveniva dopo il sonno: due coroutine entrate
    mentre una terza dormiva leggevano lo stesso «ultimo» e partivano insieme.
    """
    delay = _throttle_delay_s()
    if delay <= 0:
        return
    adesso = time.monotonic()
    ultimo = _HOST_LAST_REQUEST.get(host)
    slot = adesso if ultimo is None else max(adesso, ultimo + delay)
    _HOST_LAST_REQUEST[host] = slot
    sleep_s = slot - adesso
    if sleep_s > 0:
        logger.debug("[http] throttle host={} sleep={:.2f}s", host, sleep_s)
        await asyncio.sleep(sleep_s)


# --- indirizzi interni (giro 3, contratto §18.6) ------------------------------

#: Gli schemi che si possono chiedere: tutto il resto (file:, ftp:, gopher:…) no.
SCHEMI_AMMESSI: frozenset[str] = frozenset({"http", "https"})

#: I tre esiti di `classifica_indirizzo`.
PUBBLICO = "pubblico"
#: Schema non http(s), host mancante, o almeno un indirizzo interno: e' un
#: giudizio sull'URL, non cambia al giro dopo.
RIFIUTATO = "rifiutato"
#: Il DNS non ha risposto (o ha risposto vuoto): una notizia sulla rete, non
#: sull'URL. Non si chiede, ma un link gia' pubblicato non si ritira per questo.
IRRISOLTO = "irrisolto"

#: Risoluzioni riuscite per host, per `TTL_DNS_S`: la verifica dei link chiede
#: molte volte gli stessi host, e `righe_link_da_payload` gira nel loop della
#: SEO. I fallimenti non si ricordano: al giro dopo si riprova.
TTL_DNS_S = 600.0
_DNS_RECENTI: dict[str, tuple[float, tuple[str, ...]]] = {}


def _risolvi(host: str) -> list[str]:
    """Gli indirizzi (IPv4 e IPv6) a cui `host` risolve. Solleva se il DNS fallisce."""
    adesso = time.monotonic()
    ricordato = _DNS_RECENTI.get(host)
    if ricordato is not None and ricordato[0] > adesso:
        return list(ricordato[1])
    indirizzi = tuple(info[4][0] for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP))
    if indirizzi:
        _DNS_RECENTI[host] = (adesso + TTL_DNS_S, indirizzi)
    return list(indirizzi)


def ip_pubblico(indirizzo: str) -> bool:
    """Un indirizzo IP e' pubblico: niente loopback, privati, link-local,
    multicast, riservati, non specificati o comunque non globali. Un IPv6 che
    incapsula un IPv4 (`::ffff:127.0.0.1`) vale quanto l'IPv4 che porta."""
    try:
        ip = ipaddress.ip_address(indirizzo.split("%", 1)[0])
    except ValueError:
        return False
    mappato = getattr(ip, "ipv4_mapped", None)
    if mappato is not None:
        ip = mappato
    return bool(ip.is_global) and not (
        ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified)


def classifica_indirizzo(
    url: str,
    *,
    risolvi: Callable[[str], Iterable[str]] | None = None,
) -> str:
    """`PUBBLICO`, `RIFIUTATO` o `IRRISOLTO` (§18.6).

    Pubblico solo se lo schema e' http/https, l'host c'e' e **tutti** gli
    indirizzi a cui risolve sono pubblici (`ip_pubblico`): un nome con un
    record pubblico e uno interno si rifiuta. Un IP scritto nell'URL si giudica
    senza DNS. Limite noto: fra questa risoluzione e la connessione il DNS puo'
    cambiare (rebinding); la guardia chiude i casi statici, che sono quelli dei
    link scritti in una pagina o da un modello.
    """
    try:
        parti = urlsplit(str(url or "").strip())
        host = parti.hostname
    except ValueError:
        return RIFIUTATO
    if parti.scheme.lower() not in SCHEMI_AMMESSI or not host:
        return RIFIUTATO
    host = host.rstrip(".")
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        indirizzi: list[str] = [host]
    except ValueError:
        try:
            indirizzi = [str(i) for i in (risolvi or _risolvi)(host)]
        except Exception as e:
            logger.debug("[http] DNS di {} fallito: {}", host, e)
            return IRRISOLTO
        if not indirizzi:
            return IRRISOLTO
    return PUBBLICO if all(ip_pubblico(i) for i in indirizzi) else RIFIUTATO


def indirizzo_pubblico(
    url: str,
    *,
    risolvi: Callable[[str], Iterable[str]] | None = None,
) -> bool:
    """Si puo' chiedere `url` senza toccare la rete interna? (§18.6)

    Vero solo se `classifica_indirizzo` dice `PUBBLICO`: un indirizzo interno,
    uno schema non http(s) o un DNS fallito valgono False. Va chiamata prima di
    ogni richiesta verso un URL che non sia di una fonte nota, e su ogni
    redirect. Sincrona (il DNS blocca): dal codice asincrono si usa
    `indirizzo_pubblico_async`.
    """
    return classifica_indirizzo(url, risolvi=risolvi) == PUBBLICO


async def indirizzo_pubblico_async(url: str) -> bool:
    """`indirizzo_pubblico` senza bloccare il loop (DNS in un thread)."""
    return await asyncio.to_thread(indirizzo_pubblico, url)


async def classifica_indirizzo_async(url: str) -> str:
    """`classifica_indirizzo` senza bloccare il loop (DNS in un thread)."""
    return await asyncio.to_thread(classifica_indirizzo, url)


def _default_headers() -> dict[str, str]:
    return {
        "User-Agent": get_settings().http_user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    }


async def fetch_html(url: str, *, timeout_s: float = 30.0) -> str:
    """GET una pagina HTML con throttle per host. Solleva su 4xx/5xx."""
    host = urlsplit(url).netloc
    await _wait_for_host(host)

    async with httpx.AsyncClient(
        http2=True,
        timeout=httpx.Timeout(timeout_s),
        follow_redirects=True,
        headers=_default_headers(),
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text


async def fetch_bytes(url: str, *, timeout_s: float = 60.0) -> bytes:
    """GET il contenuto binario (per CSV/PDF/XLSX). Solleva su 4xx/5xx."""
    host = urlsplit(url).netloc
    await _wait_for_host(host)

    async with httpx.AsyncClient(
        http2=True,
        timeout=httpx.Timeout(timeout_s),
        follow_redirects=True,
        headers=_default_headers(),
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content
