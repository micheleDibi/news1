# -*- coding: utf-8 -*-
"""Scheda di Obiettivo Europa: scarico autenticato e parser deterministico (§5).

Perche' esiste
--------------
L'API di Obiettivo Europa (`/api/call/`) non ha un endpoint di dettaglio: i link
verso il sito dell'ente — l'unica cosa che cerchiamo qui — stanno soltanto
nell'HTML della scheda, dentro la sezione «Link e Documenti». Sono ≈1 700
pagine: il passo 1 della cascata di §5 ne ricava, senza spendere un credito, la
fetta piu' grande delle fonti ufficiali.

Tre vincoli che il codice fa rispettare, non che il lettore deve ricordare:

1. **I cookie non escono da qui.** La sessione e' una `requests.Session`
   autenticata: va usata solo per il dominio OE e solo via `asyncio.to_thread`.
   Passarla (o passare i suoi cookie) a httpx o a Firecrawl significherebbe
   spedire `sessionid` a un terzo. `assicura_sessione_requests` e
   `assicura_niente_cookie` sono due assert, non due consigli, e il secondo ha
   un chiamante vero: `fonte_ufficiale.VerificaHttp`, che e' il punto in cui si
   compongono le intestazioni per httpx.

2. **L'HTML non viene mai persistito** fuori da `bando_controllo`: vive nella
   memoria del giro. Qui si restituisce una `Scheda` — impronta, candidati,
   offset — e mai il corpo della pagina.

3. **Regola unica di ri-scarico (§5, A29)**: si riscarica solo (a) alla
   scoperta, (b) quando il segnale C cambia `status` o `deadline_label`,
   (c) con `--forza`. `modified`, `on_arrival` e `sparito_dalla_fonte` alzano
   solo la priorita' del monitor. `deve_riscaricare()` e' l'unico posto che lo
   decide, cosi' non puo' nascere una seconda regola in un altro modulo.

Il parser e' **puro**: `analizza(html, url)` non tocca la rete e i test girano
su fixture HTML scritte a mano. Lo scarico sta in `ScaricoSchede`, che riceve
per iniezione la sessione, il validatore, l'attesa e l'esecutore del blocco
sincrono: anche li' nessun test raggiunge il portale.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence
from urllib.parse import urljoin, urlsplit
from xml.sax.saxutils import escape

from . import impronte
from .dominio_ufficiale import Tabella, classifica, dominio_di
from .logger import logger, redigi
from .telemetria import PREFISSO_ALLARME


# --- costanti ---------------------------------------------------------------

HOST_OE = "obiettivoeuropa.com"
BASE_OE = "https://www.obiettivoeuropa.com"

#: Tetto giornaliero delle schede (§5: `OE_SCHEDE_GIORNO`, default 850).
SCHEDE_GIORNO_PREDEFINITO = 850
#: Un secondo fra una scheda e l'altra: e' il throttle di §5, non una stima.
THROTTLE_S = 1.0
TIMEOUT_S = 30.0
#: Backoff del rinnovo sessione, identico a `scrapers/auth/obiettivo_europa.py`.
BACKOFF_S: tuple[int, ...] = (60, 120, 240)
TENTATIVI_SESSIONE = 3

#: Sotto questa quota di schede con la sezione «Link e Documenti» il giro alza
#: un allarme: vuol dire che il portale ha cambiato struttura e che il parser
#: sta restituendo zero candidati invece di sbagliare rumorosamente.
QUOTA_SEZIONE_ATTESA = 0.80

#: Gli stati su cui il lotto si ferma del tutto (§5): continuare significherebbe
#: farsi bloccare l'account.
STATI_DI_STOP = (403, 429)

#: I tre motivi ammessi di (ri)scarico. Nessun altro innesco esiste.
MOTIVO_SCOPERTA = "scoperta"
MOTIVO_STATO = "status"
MOTIVO_SCADENZA = "deadline_label"
MOTIVO_FORZA = "forza"
MOTIVI_RISCARICO: frozenset[str] = frozenset({
    MOTIVO_SCOPERTA, MOTIVO_STATO, MOTIVO_SCADENZA, MOTIVO_FORZA,
})

#: I campi del segnale C che NON autorizzano un ri-scarico (alzano solo la
#: priorita' del monitor). Elencarli serve al test: se domani qualcuno li
#: aggiunge alla regola, il test lo dice.
CAMPI_SOLO_PRIORITA: frozenset[str] = frozenset({
    "modified", "on_arrival", "updates_active", "budget", "published",
    "sparito_dalla_fonte",
})

_SCHEMI_VIETATI = ("mailto:", "tel:", "javascript:", "data:", "file:")

#: «Link e Documenti», con qualunque spaziatura e con o senza accento finale.
_RE_SEZIONE = re.compile(r"link\s*(?:e|&|ed)\s*documenti", re.IGNORECASE)
#: Il bottone «Vai al bando» in fondo alla scheda.
_RE_BOTTONE = re.compile(r"vai\s+al\s+bando", re.IGNORECASE)

#: Intestazioni che non devono MAI uscire verso httpx o Firecrawl.
_INTESTAZIONI_SEGRETE: frozenset[str] = frozenset({"cookie", "set-cookie", "authorization"})

ORIGINE_SEZIONE = "link_e_documenti"
ORIGINE_BOTTONE = "vai_al_bando"


class SchedaOEError(RuntimeError):
    """Il lotto delle schede non puo' partire o deve fermarsi.

    Il messaggio non contiene mai cookie, credenziali o token: il filtro di
    redazione del logger copre i log, questa classe copre le eccezioni.
    """


# --- tipi -------------------------------------------------------------------

@dataclass(frozen=True)
class Candidato:
    """Un link uscente dalla scheda, con la prova che lo giustifica.

    `prova` e' `sha256(scheda)#offset`: chi rilegge la riga puo' riscaricare la
    scheda, confrontare l'impronta e ritrovare l'href esattamente a
    quell'offset. E' cio' che rende il link una prova e non un'affermazione.
    """
    url: str
    ancora: str = ""
    offset: int = -1
    origine: str = ORIGINE_SEZIONE
    tipo: str = "sconosciuto"
    prova: str = ""
    host: str = ""


@dataclass(frozen=True)
class Scarto:
    url: str
    motivo: str


@dataclass(frozen=True)
class Scheda:
    """Esito del parsing di **una** scheda. Non contiene l'HTML: §5 lo vieta."""
    url: str
    impronta: str
    sezione_presente: bool = False
    candidati: tuple[Candidato, ...] = ()
    scartati: tuple[Scarto, ...] = ()

    @property
    def ha_candidati(self) -> bool:
        return bool(self.candidati)


@dataclass
class Contatori:
    """Contatori del lotto. Sono cio' che finisce in `pipeline_run`."""
    schede: int = 0
    senza_sezione: int = 0
    candidati: int = 0
    errori: int = 0
    saltate: int = 0
    anonime: int = 0
    fermato: str = ""

    def come_dizionario(self) -> dict[str, Any]:
        return {
            "schede": self.schede,
            "senza_sezione": self.senza_sezione,
            "candidati": self.candidati,
            "errori": self.errori,
            "saltate": self.saltate,
            "anonime": self.anonime,
            "fermato": self.fermato,
        }


# --- assert di sicurezza ----------------------------------------------------

def assicura_sessione_requests(sessione: Any) -> None:
    """La sessione OE e' una `requests.Session` e non finisce mai in httpx.

    E' un assert e non un `if`: il caso in cui fallisce non e' un errore da
    gestire, e' un errore di programmazione che deve fermare il giro prima di
    spedire un cookie di sessione a un terzo.
    """
    modulo = type(sessione).__module__.split(".", 1)[0]
    assert modulo != "httpx", "la sessione OE non va mai passata a httpx (§5)"
    assert hasattr(sessione, "cookies") and hasattr(sessione, "get"), (
        "sessione OE non valida: attesa una requests.Session"
    )


def assicura_niente_cookie(destinazione: str, intestazioni: Mapping[str, Any]) -> None:
    """Nessun cookie (ne' Authorization) verso httpx o Firecrawl.

    Chi compone le intestazioni per un client diverso da quello di OE passa di
    qui: e' il punto unico in cui la regola e' scritta.
    """
    colpevoli = sorted(
        str(chiave) for chiave in intestazioni if str(chiave).lower() in _INTESTAZIONI_SEGRETE
    )
    assert not colpevoli, (
        f"intestazioni di sessione verso {destinazione}: vietate (§5) — {colpevoli}"
    )


# --- regola unica di ri-scarico (§5, A29) -----------------------------------

def deve_riscaricare(
    *,
    prima: Mapping[str, Any] | None = None,
    dopo: Mapping[str, Any] | None = None,
    forza: bool = False,
) -> tuple[bool, str]:
    """(si riscarica?, motivo). Unico posto che decide (§5, A29).

    `prima` e' il `raw_data` gia' in tabella, `dopo` quello appena letto dal
    listing. `prima is None` vale «scoperta». Un cambio di `modified`,
    `on_arrival` o `budget` **non** basta: alza solo la priorita' del monitor,
    e chi lo confonde con un innesco di scarico moltiplica per tre il traffico
    verso il portale senza aggiungere un solo link nuovo.
    """
    if forza:
        return True, MOTIVO_FORZA
    if prima is None:
        return True, MOTIVO_SCOPERTA
    if dopo is None:
        return False, ""
    for campo, motivo in ((MOTIVO_STATO, MOTIVO_STATO), (MOTIVO_SCADENZA, MOTIVO_SCADENZA)):
        if _valore(prima, campo) != _valore(dopo, campo):
            return True, motivo
    return False, ""


def _valore(riga: Mapping[str, Any], campo: str) -> str:
    valore = riga.get(campo)
    return "" if valore is None else str(valore).strip()


# --- parser deterministico --------------------------------------------------

def impronta_scheda(html: str | None) -> str:
    """sha256 dell'HTML della scheda: la meta' stabile della prova."""
    return hashlib.sha256((html or "").encode("utf-8", "replace")).hexdigest()


def e_host_oe(url: str | None) -> bool:
    """Vero per obiettivoeuropa.com e per ogni suo sottodominio."""
    host = dominio_di(url)
    return bool(host) and (host == HOST_OE or host.endswith("." + HOST_OE))


def _vietato(href: str) -> bool:
    pulito = href.strip()
    if not pulito or pulito.startswith("#"):
        return True
    return pulito.lower().startswith(_SCHEMI_VIETATI)


def _sezione_link_e_documenti(zuppa):
    """`h2` «Link e Documenti» → primo fratello `div.prose` prima del prossimo h2.

    Si scorre dentro i fratelli e ci si ferma alla prossima intestazione: senza
    quel limite la sezione successiva («Bandi correlati», che su OE e' un altro
    `div.prose`) entrerebbe nella stessa raccolta.
    """
    for intestazione in zuppa.find_all("h2"):
        if not _RE_SEZIONE.search(intestazione.get_text(" ", strip=True)):
            continue
        for fratello in intestazione.find_next_siblings():
            nome = getattr(fratello, "name", "")
            if nome in ("h1", "h2"):
                break
            if nome != "div":
                continue
            classi = fratello.get("class") or []
            if any("prose" in str(c) for c in classi):
                return intestazione, fratello
        return intestazione, None
    return None, None


def _forme_href(href: str) -> tuple[str, ...]:
    """L'href come sta nell'HTML, non come BeautifulSoup lo restituisce.

    Il parser risolve le entita': `href="...?id=1&amp;anno=2026"` — la forma
    corretta, e comunissima, di una query string — arriva qui come
    `...?id=1&anno=2026`, che nell'HTML originale non esiste. Cercare solo
    quella stringa darebbe offset -1 e una prova che non prova niente.
    """
    forme = [href]
    for candidata in (escape(href, {'"': "&quot;", "'": "&#39;"}), href.replace("&", "&amp;")):
        if candidata not in forme:
            forme.append(candidata)
    return tuple(forme)


def _offset(html: str, href: str, da: int) -> tuple[int, int]:
    """Offset dell'href nell'HTML originale, cercando avanti dall'ultimo trovato.

    Cercare sempre dall'inizio darebbe lo stesso offset a due link identici e
    la prova non distinguerebbe piu' le due occorrenze. Si prova prima l'href
    cosi' com'e', poi le forme con le entita' HTML (vedi `_forme_href`).
    """
    if not href:
        return -1, da
    for forma in _forme_href(href):
        posizione = html.find(forma, da)
        if posizione >= 0:
            return posizione, posizione + len(forma)
    for forma in _forme_href(href):
        posizione = html.find(forma)
        if posizione >= 0:
            return posizione, da
    return -1, da


def analizza(
    html: str | None,
    url_scheda: str,
    *,
    tabella: Tabella | Iterable[Any] | None = None,
) -> Scheda:
    """Parsing puro della scheda OE. Nessuna rete, nessuna scrittura.

    Raccoglie i `p > a[href]` della sezione «Link e Documenti» piu' il bottone
    «Vai al bando», scarta gli host OE e gli schemi non navigabili, e classifica
    ogni host con la whitelist. La classificazione qui e' solo un'etichetta:
    l'esito della fonte lo decide `fonte_ufficiale.punteggia()`, dopo il fetch.
    """
    impronta = impronta_scheda(html)
    if not html:
        return Scheda(url=url_scheda, impronta=impronta)

    tab = Tabella.da(tabella) if tabella is not None else None
    zuppa = impronte._zuppa(html)
    intestazione, prosa = _sezione_link_e_documenti(zuppa)

    candidati: list[Candidato] = []
    scartati: list[Scarto] = []
    viste: set[str] = set()
    cursore = 0

    def aggiungi(nodo, origine: str) -> None:
        nonlocal cursore
        href = (nodo.get("href") or "").strip()
        if _vietato(href):
            return
        assoluto = urljoin(url_scheda or BASE_OE, href)
        if urlsplit(assoluto).scheme not in ("http", "https"):
            return
        if e_host_oe(assoluto):
            scartati.append(Scarto(assoluto, "host obiettivoeuropa"))
            return
        chiave = impronte.normalizza_url(assoluto) or assoluto
        if chiave in viste:
            return
        viste.add(chiave)
        posizione, cursore = _offset(html, href, cursore)
        if posizione < 0:
            # Senza offset la prova non e' verificabile: meglio nessuna prova
            # che una stringa che sembra una prova. Il candidato resta (l'URL
            # e' vero), ma `bando_link.impronta_pagina` restera' NULL.
            logger.debug("[oe_scheda] href non ritrovato nell'HTML di {}: prova assente", url_scheda)
        host = dominio_di(assoluto) or ""
        candidati.append(Candidato(
            url=assoluto,
            ancora=nodo.get_text(" ", strip=True),
            offset=posizione,
            origine=origine,
            tipo=classifica(host, tab) if tab is not None else classifica(host, None),
            prova=f"{impronta}#{posizione}" if posizione >= 0 else "",
            host=host,
        ))

    if prosa is not None:
        for nodo in prosa.select("p > a[href]"):
            aggiungi(nodo, ORIGINE_SEZIONE)

    # Il bottone «Vai al bando» sta fuori dalla sezione e va cercato in tutta la
    # pagina: e' l'unico link presente anche sulle schede senza «Link e Documenti».
    for nodo in zuppa.find_all("a", href=True):
        testo = nodo.get_text(" ", strip=True)
        if _RE_BOTTONE.search(testo or ""):
            aggiungi(nodo, ORIGINE_BOTTONE)

    return Scheda(
        url=url_scheda,
        impronta=impronta,
        sezione_presente=intestazione is not None and prosa is not None,
        candidati=tuple(candidati),
        scartati=tuple(scartati),
    )


def quota_con_sezione(schede: Sequence[Scheda]) -> float:
    """Quota di schede in cui «Link e Documenti» e' stata trovata."""
    if not schede:
        return 1.0
    return sum(1 for s in schede if s.sezione_presente) / len(schede)


def allarme_sezione(schede: Sequence[Scheda], soglia: float = QUOTA_SEZIONE_ATTESA) -> str:
    """Riga di allarme se il portale ha cambiato struttura, altrimenti "".

    Un parser che smette di trovare la sezione non solleva: restituisce zero
    candidati, e senza questo controllo un giro «riuscito» produrrebbe zero
    fonti ufficiali senza che nessuno se ne accorga.
    """
    quota = quota_con_sezione(schede)
    if quota >= soglia:
        return ""
    return (
        f"{PREFISSO_ALLARME} schede OE con sezione «Link e Documenti» al "
        f"{quota:.0%} (attese >= {soglia:.0%}): struttura del portale cambiata?"
    )


# --- scarico ----------------------------------------------------------------

@dataclass
class ScaricoSchede:
    """Scarico del lotto di schede. Tutto l'I/O e' iniettato.

    `fornitore_sessione` produce la `requests.Session` autenticata (in
    produzione: `auth.obtain_session`), `validatore` dice se e' davvero
    autenticata (`auth.valida_sessione`), `azzera_cache` e' `auth.clear_cache`.
    `esegui` e' cio' che porta la chiamata bloccante fuori dall'event loop: il
    default e' `asyncio.to_thread`, nei test e' una funzione sincrona.
    """
    fornitore_sessione: Callable[[], Any]
    validatore: Callable[[Any], bool] | None = None
    azzera_cache: Callable[[], None] | None = None
    fornitore_anonima: Callable[[], Any] | None = None
    tabella: Tabella | None = None
    tetto: int = SCHEDE_GIORNO_PREDEFINITO
    gia_oggi: int = 0
    throttle_s: float = THROTTLE_S
    tentativi: int = TENTATIVI_SESSIONE
    backoff: tuple[int, ...] = BACKOFF_S
    esegui: Callable[[Callable[[], Any]], Awaitable[Any]] | None = None
    dormi: Callable[[float], Awaitable[None]] = asyncio.sleep
    orologio: Callable[[], float] = time.monotonic
    contatori: Contatori = field(default_factory=Contatori)
    _sessione: Any = None
    _anonima: Any = None
    _ultima: float | None = None

    # --- ciclo di vita -----------------------------------------------------

    async def prepara(self) -> Any:
        """Valida la sessione PRIMA del lotto. Mai un ripiego anonimo (§5).

        Se dopo `tentativi` rinnovi la prima pagina dell'API resta sotto i 50
        record, il lotto non parte: `SchedaOEError` con `[ALLARME]`. Scaricare
        1 700 schede con una sessione anonima significherebbe riempire il DB di
        pagine vuote e non accorgersene fino al giro dopo.
        """
        if self._sessione is not None:
            return self._sessione
        ultimo = ""
        for tentativo in range(1, max(1, self.tentativi) + 1):
            try:
                sessione = self.fornitore_sessione()
            except Exception as e:                       # credenziali o rete
                ultimo = str(e)
                sessione = None
            if sessione is not None:
                assicura_sessione_requests(sessione)
                if self.validatore is None or await self._nel_thread(
                    lambda s=sessione: bool(self.validatore(s))          # type: ignore[misc]
                ):
                    self._sessione = sessione
                    return sessione
                ultimo = "sessione non autenticata (prima pagina sotto i 50 record)"
            if self.azzera_cache is not None:
                self.azzera_cache()
            if tentativo < max(1, self.tentativi):
                await self.dormi(self.backoff[min(tentativo - 1, len(self.backoff) - 1)])
        self.contatori.fermato = "sessione"
        raise SchedaOEError(
            f"{PREFISSO_ALLARME} sessione Obiettivo Europa non autenticata dopo "
            f"{self.tentativi} tentativi: lotto delle schede fermo ({redigi(ultimo)})"
        )

    def anonima(self) -> Any:
        """Sessione anonima, deliberata e solo per gli «Archiviato» (§5)."""
        if self._anonima is None and self.fornitore_anonima is not None:
            self._anonima = self.fornitore_anonima()
            assicura_sessione_requests(self._anonima)
            assert self._anonima is not self._sessione, (
                "la sessione anonima non puo' essere quella autenticata"
            )
        return self._anonima

    @property
    def fermato(self) -> str:
        return self.contatori.fermato

    def residue(self) -> int:
        """Quante schede restano prima del tetto giornaliero."""
        return max(0, int(self.tetto) - int(self.gia_oggi) - self.contatori.schede)

    # --- una scheda --------------------------------------------------------

    async def scheda(self, url: str, *, archiviato: bool = False) -> Scheda | None:
        """Scarica e analizza **una** scheda. `None` se non e' stata presa.

        Non solleva per un 404 o un 500: conta l'errore e prosegue. Si ferma —
        per tutto il lotto — solo su 403/429, che sono la risposta «stai
        chiedendo troppo» e che continuare trasformerebbe in un blocco.
        """
        if self.contatori.fermato:
            self.contatori.saltate += 1
            return None
        if self.tetto and self.residue() <= 0:
            self.contatori.fermato = "tetto"
            self.contatori.saltate += 1
            logger.warning("[oe_scheda] tetto giornaliero {} raggiunto: lotto fermo", self.tetto)
            return None
        assert e_host_oe(url), f"oe_scheda scarica solo schede OE, non {dominio_di(url)}"

        sessione = self.anonima() if archiviato else None
        if sessione is None:
            sessione = await self.prepara()
        else:
            self.contatori.anonime += 1
        assicura_sessione_requests(sessione)

        await self._attendi()
        try:
            risposta = await self._nel_thread(
                lambda: sessione.get(url, timeout=TIMEOUT_S, allow_redirects=True)
            )
        except Exception as e:
            self.contatori.errori += 1
            logger.warning("[oe_scheda] scheda non presa ({}): {}", url, e)
            return None

        stato = int(getattr(risposta, "status_code", 0) or 0)
        if stato in STATI_DI_STOP:
            self.contatori.fermato = f"http {stato}"
            logger.warning(
                "[oe_scheda] risposta {} dal portale: lotto fermo, si riprende al giro dopo", stato,
            )
            return None
        if not 200 <= stato < 300:
            self.contatori.errori += 1
            return None

        scheda = analizza(getattr(risposta, "text", "") or "", url, tabella=self.tabella)
        self.contatori.schede += 1
        self.contatori.candidati += len(scheda.candidati)
        if not scheda.sezione_presente:
            self.contatori.senza_sezione += 1
        return scheda

    async def lotto(
        self,
        url_e_archiviati: Iterable[tuple[str, bool]],
    ) -> tuple[Scheda, ...]:
        """Scarica un elenco di schede, fermandosi ai primi 403/429 o al tetto."""
        raccolte: list[Scheda] = []
        for url, archiviato in url_e_archiviati:
            scheda = await self.scheda(url, archiviato=archiviato)
            if scheda is not None:
                raccolte.append(scheda)
            if self.contatori.fermato:
                break
        riga = allarme_sezione(raccolte)
        if riga:
            logger.warning("[oe_scheda] {}", riga)
        return tuple(raccolte)

    # --- interni -----------------------------------------------------------

    async def _nel_thread(self, chiamata: Callable[[], Any]) -> Any:
        if self.esegui is not None:
            return await self.esegui(chiamata)
        return await asyncio.to_thread(chiamata)

    async def _attendi(self) -> None:
        """Throttle di 1 s fra una richiesta e l'altra, misurato sull'orologio
        e non sommato ciecamente: se il parsing ha gia' preso mezzo secondo si
        aspetta solo il mezzo che manca."""
        adesso = self.orologio()
        if self._ultima is not None:
            resta = self.throttle_s - (adesso - self._ultima)
            if resta > 0:
                await self.dormi(resta)
                adesso = self.orologio()
        self._ultima = adesso


# --- composizione di produzione ---------------------------------------------

def scarico_predefinito(
    impostazioni: Any = None,
    *,
    tabella: Tabella | None = None,
    gia_oggi: int = 0,
) -> "ScaricoSchede | None":
    """Lo `ScaricoSchede` di produzione, o `None` se mancano le credenziali.

    E' l'unico punto che sa da dove arrivano sessione, validatore e
    `clear_cache`: senza, `fonte_ufficiale` costruirebbe la sua copia e la
    regola «mai un ripiego anonimo» avrebbe due versioni. Gli import sono
    locali perche' `scrapers.auth.obiettivo_europa` tira dentro `requests` e
    `settings`, che in un modulo di parsing non devono entrare.

    Credenziali assenti non e' un errore da sollevare: e' un lotto che non puo'
    partire, e chi chiama lo traduce in `saltato='scarico_non_configurato'`.
    """
    from .scrapers.auth import obiettivo_europa as auth
    from .settings import get_settings

    impostazioni = impostazioni if impostazioni is not None else get_settings()
    utente = str(getattr(impostazioni, "obiettivo_europa_username", "") or "").strip()
    chiave = str(getattr(impostazioni, "obiettivo_europa_password", "") or "").strip()
    if not utente or not chiave:
        logger.warning(
            "[oe_scheda] credenziali Obiettivo Europa assenti: nessuna scheda scaricabile"
        )
        return None
    return ScaricoSchede(
        fornitore_sessione=lambda: auth.obtain_session(utente, chiave),
        validatore=auth.valida_sessione,
        azzera_cache=auth.clear_cache,
        tabella=tabella,
        tetto=int(getattr(impostazioni, "oe_schede_giorno", SCHEDE_GIORNO_PREDEFINITO) or 0),
        gia_oggi=max(0, int(gia_oggi)),
    )


__all__ = [
    "BASE_OE", "CAMPI_SOLO_PRIORITA", "Candidato", "Contatori", "HOST_OE",
    "MOTIVI_RISCARICO", "MOTIVO_FORZA", "MOTIVO_SCADENZA", "MOTIVO_SCOPERTA",
    "MOTIVO_STATO", "ORIGINE_BOTTONE", "ORIGINE_SEZIONE", "QUOTA_SEZIONE_ATTESA",
    "SCHEDE_GIORNO_PREDEFINITO", "STATI_DI_STOP", "Scarto", "Scheda",
    "SchedaOEError", "ScaricoSchede", "THROTTLE_S", "allarme_sezione", "analizza",
    "assicura_niente_cookie", "assicura_sessione_requests", "deve_riscaricare",
    "e_host_oe", "impronta_scheda", "quota_con_sezione", "scarico_predefinito",
]
