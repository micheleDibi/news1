"""Lettura di `SCRAPER_CONFIG` per chiave normalizzata (fix 8.a.8).

Il problema: `bando_runner.py:88` cerca la configurazione con
`SCRAPER_CONFIG.get(fonte['link'])`, cioe' per uguaglianza esatta della stringa.
Ma i `link` in tabella `fonte` arrivano dallo scraper di OpenCoesione e
differiscono dalle chiavi del registro per dettagli che non cambiano la pagina:
slash finale, `%C3%A0` invece di `à`, ordine dei parametri, frammento `#sezione`,
maiuscole nell'host. Risultato misurato: 25 fonti senza configurazione e 13
chiavi del registro mai raggiunte.

Qui la chiave diventa una **forma normale**: niente frammento, percorso
decodificato, query ordinata, niente slash finale, poi `classifier.normalize`
(NFKD, via gli accenti, casefold, spazi compressi) — la stessa funzione che il
resto del package usa per confrontare i nomi, cosi' non nasce una seconda
nozione di «uguale».

**Non si normalizza a monte** (`discover.py` e `upsert_fonti` restano com'erano):
il `link` e' la chiave di conflitto dell'upsert di `fonte` ed entra in
`hash_bando`. Riscriverlo creerebbe fonti nuove e cambierebbe l'hash di tutti i
bandi gia' in tabella.

L'indice si costruisce una volta sola e **rifiuta le collisioni**: due chiavi
diverse che si riducono alla stessa forma normale con configurazioni diverse
sono un errore del registro, non una fusione da risolvere in silenzio.
In produzione, pero', una collisione non puo' spegnere lo scrape di tutte le
fonti: `indice()` la registra con `logger.error` e tiene la prima voce, mentre
`costruisci_indice()` resta severa (ed e' quella che il test interroga).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from .classifier import normalize
from .logger import logger
from .scraper_config import SCRAPER_CONFIG


class RegistroCollisioneError(RuntimeError):
    """Due voci diverse del registro con la stessa chiave normalizzata."""


def chiave(url: str) -> str:
    """Forma normale di un URL, usata come chiave dell'indice.

    Ordine delle operazioni: frammento via, percorso e query decodificati,
    parametri ordinati, slash finale via, infine `classifier.normalize` (che
    fa anche il casefold, quindi host e schema maiuscoli si allineano da soli).
    """
    if not url:
        return ""
    pezzi = urlsplit(url.strip())
    # L'host resta com'e' (`normalize` lo mettera' in minuscolo): `www.` NON si
    # toglie, perche' due host diversi possono servire pagine diverse e la
    # regola e' «mai fondere voci diverse».
    percorso = unquote(pezzi.path)
    if percorso.endswith("/") and percorso != "/":
        percorso = percorso.rstrip("/")
    # `keep_blank_values`: `?filtro=` e' un parametro presente, non assente.
    parametri = sorted(parse_qsl(unquote(pezzi.query), keep_blank_values=True))
    query = urlencode(parametri)
    senza_frammento = urlunsplit((pezzi.scheme, pezzi.netloc, percorso, query, ""))
    return normalize(senza_frammento)


@lru_cache(maxsize=1)
def indice() -> dict[str, dict[str, Any]]:
    """Chiave normalizzata -> voce del registro. Costruito una volta sola.

    Difensivo di proposito: il chiamante e' lo step di scrape, e una voce
    aggiunta male a `SCRAPER_CONFIG` non deve far fallire lo scrape di TUTTE
    le fonti (`lru_cache` non memorizza le eccezioni: la rialzerebbe a ogni
    chiamata). La collisione diventa un `logger.error` con le due chiavi e
    vince la prima voce. `costruisci_indice` resta severa: e' li' che il test
    pretende l'eccezione, cosi' un registro incoerente si scopre comunque.
    """
    try:
        return costruisci_indice(SCRAPER_CONFIG)
    except RegistroCollisioneError as e:
        logger.error("[registro] {} — si tiene la prima voce e si prosegue", e)
        return costruisci_indice(SCRAPER_CONFIG, severo=False)


def costruisci_indice(
    config: dict[str, dict[str, Any]], *, severo: bool = True,
) -> dict[str, dict[str, Any]]:
    """Come `indice()`, ma su una configurazione qualsiasi (test).

    Due chiavi che collassano sulla stessa forma normale sono tollerate solo se
    la voce e' identica (duplicato innocuo); altrimenti e' un errore: una
    fusione silenziosa assegnerebbe a una fonte la strategia di un'altra.
    Con `severo=False` la collisione viene registrata e vince la prima voce:
    e' il ripiego di `indice()` in produzione, mai il comportamento di default.
    """
    costruito: dict[str, dict[str, Any]] = {}
    originale: dict[str, str] = {}
    for url, voce in config.items():
        k = chiave(url)
        if k in costruito and costruito[k] != voce:
            messaggio = f"chiave normalizzata duplicata {k!r}: {originale[k]!r} e {url!r}"
            if severo:
                raise RegistroCollisioneError(messaggio)
            logger.error("[registro] {} — ignorata {!r}", messaggio, url)
            continue
        costruito[k] = voce
        originale.setdefault(k, url)
    return costruito


def trova(url: str) -> dict[str, Any] | None:
    """Voce del registro per `url`, o None. Mai eccezioni: un URL storto da'
    None e un registro incoerente degrada (vedi `indice()`)."""
    if not url:
        return None
    return indice().get(chiave(url))


def host_richiede_js() -> frozenset[str]:
    """Host che rispondono con una app-shell e per cui `scarico.py` puo' pagare
    il ripiego Firecrawl senza aspettare la prova a runtime.

    Sono solo quelli dichiarati esplicitamente con `richiede_js: True` nel
    registro: dedurlo dalla strategia (`firecrawl_*`) farebbe pagare un credito
    anche alle pagine di bando su host che il ripiego non aiuta.
    """
    host: set[str] = set()
    for url, voce in SCRAPER_CONFIG.items():
        if voce.get("richiede_js") is True:
            netloc = urlsplit(url).netloc.lower().split(":", 1)[0]
            host.add(netloc[4:] if netloc.startswith("www.") else netloc)
    return frozenset(host)


__all__ = ["RegistroCollisioneError", "chiave", "costruisci_indice", "host_richiede_js",
           "indice", "trova"]
