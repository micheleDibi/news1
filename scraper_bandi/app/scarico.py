"""Unico punto di scarico della pipeline bandi (piano §6.2, fix 8.a.1 e 8.a.27).

Perche' esiste
--------------
Prima c'erano tre vie diverse per prendere una pagina: `enricher._FIRECRAWL_CACHE`
(cache a vita di processo che memorizzava anche i fallimenti e troncava il testo
a 4 000 caratteri *alla sorgente*), `http.fetch_html` (un `AsyncClient` nuovo a
ogni chiamata) e le chiamate diritte a `scrape_url` in `scrapers/` (senza
`proxy`, cioe' «auto»: fino a 5 crediti invece di 1, e fuori da ogni contatore).
Qui ne resta una sola, con quattro garanzie che il resto del codice da' per buone:

1. **un client per giro** — `httpx.AsyncClient` riusato (http2, keep-alive),
   timeout 20 s, 2 ritentativi con backoff su 5xx/timeout/429, throttle per host
   preso da `http.py` (stessa mappa: due moduli non devono martellare un host);
2. **cache per giro, non per processo** — TTL 3 600 s, `svuota()` a inizio giro;
   **mai** fallimenti ne' corpi vuoti in cache (un 500 passeggero non deve
   condannare un bando per tutto il processo, che e' il difetto 8.a.1);
3. **ripiego Firecrawl solo dove serve** — solo sulla pagina principale del
   bando (`principale=True`), solo se la pagina e' arrivata (2xx) o e' stata
   negata da un WAF (403/406), e solo per app-shell o host `richiede_js`;
   sempre `proxy='basic'`, `parsers=[]`, `max_age=0` (1 credito, mai stealth),
   sempre contato: `contatori.crediti_firecrawl` e' la voce che `bilancio.py`
   confronta con il consumo reale del team;
4. **blocklist a richiesta** — la denylist degli aggregatori vale per la
   **fonte ufficiale**, non per tutti gli scarichi: `scarica(..., come_fonte=True)`
   (o una `blocklist` iniettata nel costruttore) solleva `ScaricoVietatoError`
   sugli host di `AGGREGATORI`; il percorso predefinito non vieta niente.
   Fix 8.a.12 — «il **Firecrawl della FONTE** non si fa sugli aggregatori» —
   riguarda la risoluzione della fonte ufficiale (`bando_resolver`,
   `fonte_ufficiale_*`, `url_prova`, `bando_link.pubblicabile`). La pagina di
   un bando su `obiettivoeuropa.com` resta invece il `link_bando` di migliaia
   di righe: vietarla a tappeto manderebbe in `rejected` ogni bando OE nuovo.

Il testo non viene mai troncato qui: il budget e' una scelta del prompt che lo
consuma, non una proprieta' della pagina (fix 8.a.2).

Rete finta nei test: si passa `transport=httpx.MockTransport(...)` e
`firecrawl=<callable>`; nessun test tocca la rete o la chiave Firecrawl.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable, Iterable
from urllib.parse import urlsplit

import httpx

# Volutamente i nomi privati di http.py: il throttle deve restare UNO solo per
# tutto il processo (`_HOST_LAST_REQUEST` e' un dizionario di modulo). Copiarne
# la logica creerebbe due orologi indipendenti sullo stesso host.
from .http import _default_headers, _wait_for_host
from .logger import logger
from .settings import get_settings

# I 10 aggregatori del piano §5. Sono host da cui si possono leggere segnali
# (la scheda di un bando su un aggregatore e' spesso l'unica pagina che c'e'),
# mai la «fonte ufficiale» di un bando: chi prova a scaricarli COME FONTE
# sbaglia e deve accorgersene subito (eccezione), non trovarsi un testo
# plausibile. Per questo la lista si applica solo con `come_fonte=True`.
AGGREGATORI: frozenset[str] = frozenset({
    "obiettivoeuropa.com",
    "fasi.eu",
    "europafacile.net",
    "contributiregione.it",
    "finanziamentinews.it",
    "bandi.it",
    "infobandi.it",
    "ticonsiglio.com",
    "contributieuropa.com",
    "first.aster.it",
})

TTL_CACHE_S = 3600.0
LIMITE_BYTE = 5 * 1024 * 1024
TIMEOUT_S = 20.0
TENTATIVI = 2                     # ritentativi DOPO il primo tentativo
CREDITI_PER_SCRAPE = 1            # proxy='basic' + parsers=[] (§6.2)

# Soglie dell'app-shell: una pagina renderizzata dal browser arriva con poco
# testo e molto <script>. Sono i due numeri del piano, non euristiche nuove.
SOGLIA_TESTO_APP_SHELL = 500
QUOTA_SCRIPT_APP_SHELL = 0.30

_STATI_RIPIEGO = (403, 406)
_STATI_RITENTABILI = (429, 500, 502, 503, 504)

_RE_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_RE_TAG = re.compile(r"<[^>]+>")


class ScaricoVietatoError(RuntimeError):
    """Host in blocklist: la pagina non e' scaricabile come fonte (A35)."""


@dataclass(frozen=True)
class Risposta:
    """Esito di uno scarico. `testo` e' sempre valorizzato per le pagine HTML."""
    url: str
    stato: int | None
    html: str = ""
    testo: str = ""
    markdown: str = ""
    via: str = "httpx"                  # httpx | firecrawl
    etag: str | None = None
    last_modified: str | None = None
    troncata: bool = False
    da_cache: bool = False

    @property
    def vuota(self) -> bool:
        return not (self.testo.strip() or self.markdown.strip() or self.html.strip())

    @property
    def ok(self) -> bool:
        return self.stato is not None and 200 <= self.stato < 300


@dataclass
class Contatori:
    """Contatori del giro. `bilancio.py` li legge e li confronta con i tetti."""
    fetch: int = 0
    fetch_304: int = 0
    da_cache: int = 0
    errori: int = 0
    ripieghi_firecrawl: int = 0
    crediti_firecrawl: int = 0
    vietati: int = 0
    sottopagine_saltate: int = 0

    def come_dizionario(self) -> dict[str, int]:
        return {
            "fetch": self.fetch,
            "fetch_304": self.fetch_304,
            "da_cache": self.da_cache,
            "errori": self.errori,
            "ripieghi_firecrawl": self.ripieghi_firecrawl,
            "crediti_firecrawl": self.crediti_firecrawl,
            "vietati": self.vietati,
            "sottopagine_saltate": self.sottopagine_saltate,
        }


def host_di(url: str) -> str:
    """Host in minuscolo, senza porta e senza `www.` (confronti con la blocklist)."""
    netloc = urlsplit(url).netloc.lower()
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[1]
    host = netloc.split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def in_blocklist(url_o_host: str, blocklist: Iterable[str] = AGGREGATORI) -> bool:
    """Vero se l'host e' in blocklist o ne e' un sottodominio.

    Accetta sia un URL completo sia un host nudo, anche con percorso o porta
    (`obiettivoeuropa.com/bandi/1`, `esempio.it:8080`): senza schema `urlsplit`
    metterebbe tutto nel path e l'host risulterebbe vuoto, cioe' mai vietato.
    """
    candidato = url_o_host.strip()
    if "://" not in candidato:
        candidato = "https://" + candidato.lstrip("/")
    host = host_di(candidato)
    for vietato in blocklist:
        vietato = vietato.lower()
        if host == vietato or host.endswith("." + vietato):
            return True
    return False


def testo_da_html(html: str) -> str:
    """Testo visibile della pagina. bs4+lxml quando disponibili, altrimenti una
    ripulitura a regex: il modulo non deve fallire se lxml manca."""
    if not html:
        return ""
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    except Exception:                                    # pragma: no cover - ripiego
        senza_script = _RE_SCRIPT.sub(" ", html)
        return re.sub(r"\s+", " ", _RE_TAG.sub(" ", senza_script)).strip()


def e_app_shell(html: str, testo: str) -> bool:
    """Pagina renderizzata lato client: poco testo e molto `<script>`.

    Senza questa prova il ripiego Firecrawl non partirebbe mai per i siti che
    rispondono 200 con uno scheletro vuoto (il caso piu' frequente, piu' del 403).
    """
    if not html:
        return False
    if len((testo or "").strip()) >= SOGLIA_TESTO_APP_SHELL:
        return False
    script = sum(len(m.group(0)) for m in _RE_SCRIPT.finditer(html))
    return script > QUOTA_SCRIPT_APP_SHELL * len(html)


class Scarico:
    """Client unico del giro. Non e' thread-safe: vive dentro un solo event loop."""

    def __init__(
        self,
        *,
        blocklist: Iterable[str] = (),
        host_richiede_js: Iterable[str] = (),
        ttl_s: float = TTL_CACHE_S,
        limite_byte: int = LIMITE_BYTE,
        timeout_s: float = TIMEOUT_S,
        tentativi: int = TENTATIVI,
        transport: httpx.AsyncBaseTransport | None = None,
        firecrawl: Callable[[str], Awaitable[dict[str, str]]] | None = None,
        orologio: Callable[[], float] = time.monotonic,
        dormi: Callable[[float], Awaitable[None]] = asyncio.sleep,
        throttle: Callable[[str], Awaitable[None]] = _wait_for_host,
    ) -> None:
        # Vuota per difetto: la denylist e' una scelta del chiamante (la fonte
        # ufficiale), non una proprieta' dello scarico. Vedi `scarica(come_fonte=)`.
        self.blocklist = frozenset(h.lower() for h in blocklist)
        self.host_richiede_js = frozenset(h.lower() for h in host_richiede_js)
        self.ttl_s = ttl_s
        self.limite_byte = limite_byte
        self.timeout_s = timeout_s
        self.tentativi = max(0, tentativi)
        self.contatori = Contatori()
        self._transport = transport
        self._firecrawl = firecrawl
        self._orologio = orologio
        self._dormi = dormi
        self._throttle = throttle
        self._client: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._cache: dict[str, tuple[float, Risposta]] = {}

    # --- ciclo di vita -----------------------------------------------------

    def client(self) -> httpx.AsyncClient:
        """Il client del giro, creato alla prima richiesta e poi riusato.

        Il client e' legato all'event loop in cui e' nato (il pool keep-alive
        contiene socket registrati su quel loop). `bandi_sender` fa un
        `asyncio.run` per giro: alla fine del giro il loop viene chiuso e un
        client sopravvissuto esploderebbe al giro dopo con
        `RuntimeError: Event loop is closed` — che non e' un `TransportError`,
        quindi nessun ritentativo lo intercetterebbe e le pagine sparirebbero
        in silenzio. Qui il loop viene ricordato e il client ricostruito se il
        loop e' cambiato o e' stato chiuso.
        """
        loop = self._loop_corrente()
        if self._client is not None and not self._loop_valido(loop):
            # Il loop di nascita e' morto: non si puo' fare `aclose()` su di
            # esso, si abbandona il client (i socket sono gia' chiusi con lui).
            logger.debug("[scarico] client abbandonato: event loop cambiato o chiuso")
            self._client = None
        if self._client is None:
            self._client = httpx.AsyncClient(
                http2=True,
                timeout=httpx.Timeout(self.timeout_s),
                follow_redirects=True,
                headers=_default_headers(),
                transport=self._transport,
            )
            self._loop = loop
        return self._client

    @staticmethod
    def _loop_corrente() -> asyncio.AbstractEventLoop | None:
        try:
            return asyncio.get_running_loop()
        except RuntimeError:                              # fuori da un loop
            return None

    def _loop_valido(self, loop: asyncio.AbstractEventLoop | None) -> bool:
        """Vero se il client puo' ancora essere usato nel loop corrente."""
        if self._loop is None:
            return True
        return loop is self._loop and not self._loop.is_closed()

    def svuota(self) -> None:
        """Butta la cache. Va chiamata a inizio giro: una pagina di sei ore fa
        non e' una prova di niente."""
        self._cache.clear()

    def azzera_contatori(self) -> None:
        self.contatori = Contatori()

    def nuovo_giro(self) -> None:
        self.svuota()
        self.azzera_contatori()

    async def chiudi(self) -> None:
        """Chiude il client del giro. Va chiamata nel `finally` del giro, cosi'
        le connessioni non sopravvivono all'event loop che le ha aperte."""
        client = self._client
        self._client = None
        if client is None:
            return
        if not self._loop_valido(self._loop_corrente()):
            # Loop di nascita gia' chiuso: `aclose()` solleverebbe. Le socket
            # sono morte con il loop, non c'e' niente da chiudere.
            self._loop = None
            return
        try:
            await client.aclose()
        except Exception as e:                            # pragma: no cover - ripiego
            logger.debug("[scarico] chiusura del client fallita: {}", e)
        finally:
            self._loop = None

    # --- scarico -----------------------------------------------------------

    async def scarica(
        self,
        url: str,
        *,
        principale: bool = False,
        come_fonte: bool = False,
        etag: str | None = None,
        modificata_dopo: str | None = None,
        usa_cache: bool = True,
    ) -> Risposta:
        """Scarica `url`.

        `principale=True` autorizza il ripiego Firecrawl: vale solo per la
        pagina principale del bando, cosi' il ripiego resta contato per bando e
        non per URL (sottopagine e allegati restano httpx-only, §6.2).
        `come_fonte=True` dice «questa pagina la sto prendendo come FONTE
        UFFICIALE»: solo allora vale la denylist degli aggregatori
        (`AGGREGATORI`) e un host vietato solleva `ScaricoVietatoError`.
        Scaricare la scheda di un bando su un aggregatore resta lecito.
        `etag`/`modificata_dopo` fanno la GET condizionale: un 304 costa zero e
        significa «niente e' cambiato».
        """
        # Una blocklist iniettata nel costruttore vale sempre (e' una scelta
        # esplicita del chiamante e sostituisce `AGGREGATORI`); altrimenti la
        # denylist degli aggregatori entra in gioco solo per la fonte ufficiale.
        vietati: Iterable[str] = self.blocklist or (AGGREGATORI if come_fonte else ())
        if vietati and in_blocklist(url, vietati):
            self.contatori.vietati += 1
            raise ScaricoVietatoError(f"host in blocklist, scarico rifiutato: {host_di(url)}")

        if usa_cache and not (etag or modificata_dopo):
            in_cache = self._da_cache(url)
            if in_cache is not None:
                self.contatori.da_cache += 1
                return in_cache

        risposta = await self._via_httpx(url, etag=etag, modificata_dopo=modificata_dopo)

        if principale and self._serve_ripiego(url, risposta):
            ripiego = await self._via_firecrawl(url)
            if ripiego is not None and not ripiego.vuota:
                risposta = ripiego

        # Sottopagine e allegati sono httpx-only: se non si prendono si saltano
        # e basta, ma il salto si conta (§6.2). Il 304 non e' un salto: e' la
        # risposta «non e' cambiato niente», che e' un successo.
        if not principale and risposta.stato != 304 and (not risposta.ok or risposta.vuota):
            self.contatori.sottopagine_saltate += 1

        # In cache solo cio' che e' servito a qualcosa: mai un errore, mai un
        # corpo vuoto (e' il difetto della vecchia `_FIRECRAWL_CACHE`).
        if usa_cache and risposta.ok and not risposta.vuota:
            self._cache[url] = (self._orologio() + self.ttl_s, risposta)
        return risposta

    async def testo(self, url: str, *, principale: bool = False, **kwargs: Any) -> str:
        """Solo il testo visibile; stringa vuota se la pagina non si e' presa."""
        risposta = await self.scarica(url, principale=principale, **kwargs)
        return risposta.testo

    async def markdown(self, url: str, **kwargs: Any) -> str:
        """Markdown della pagina principale del bando (Firecrawl se serve);
        se il ripiego non e' disponibile ritorna il testo visibile."""
        risposta = await self.scarica(url, principale=True, **kwargs)
        return risposta.markdown or risposta.testo

    # --- interni -----------------------------------------------------------

    def _da_cache(self, url: str) -> Risposta | None:
        voce = self._cache.get(url)
        if voce is None:
            return None
        scadenza, risposta = voce
        if scadenza <= self._orologio():
            del self._cache[url]
            return None
        return replace(risposta, da_cache=True)

    def _serve_ripiego(self, url: str, risposta: Risposta) -> bool:
        """Tre sole ragioni per pagare un credito: WAF, app-shell, host noto.

        L'ordine conta. Prima si scartano gli esiti su cui il ripiego non puo'
        aiutare — 304 (non e' cambiato niente), 404/410 e gli altri 4xx che non
        sono il WAF, i 5xx e i fallimenti di rete: Firecrawl vedrebbe la stessa
        pagina morta e il credito e' gia' contato prima di saperlo. Solo dopo
        si guarda `richiede_js`, altrimenti nel monitor ogni 404 confermato su
        un host a JS costerebbe un credito a ogni controllo.
        """
        if self._firecrawl is None and not get_settings().firecrawl_api_key:
            return False
        if risposta.stato in _STATI_RIPIEGO:
            return True                       # 403/406: la pagina c'e', la nega il filtro
        if not risposta.ok:
            return False                      # 304, 404/410, 5xx, rete caduta
        if host_di(url) in self.host_richiede_js:
            return True
        return e_app_shell(risposta.html, risposta.testo)

    async def _via_httpx(
        self, url: str, *, etag: str | None, modificata_dopo: str | None,
    ) -> Risposta:
        intestazioni: dict[str, str] = {}
        if etag:
            intestazioni["If-None-Match"] = etag
        if modificata_dopo:
            intestazioni["If-Modified-Since"] = modificata_dopo

        ultimo_errore: Exception | None = None
        for tentativo in range(self.tentativi + 1):
            await self._throttle(urlsplit(url).netloc)
            # Il fetch si conta PRIMA della risposta: `tetto_fetch_giro` e'
            # l'unico tetto per giro (§6.2) e deve contare le richieste
            # effettivamente inviate, timeout compresi. Contarle dopo avrebbe
            # lasciato una fonte irraggiungibile bussare a costo zero.
            self.contatori.fetch += 1
            try:
                stato, corpo, testata, troncata = await self._una_get(url, intestazioni)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                ultimo_errore = e
                if tentativo < self.tentativi:
                    await self._dormi(self._attesa(tentativo))
                    continue
                self.contatori.errori += 1
                logger.warning("[scarico] {} fallito dopo {} tentativi: {}", url, tentativo + 1, e)
                return Risposta(url=url, stato=None)

            if stato == 304:
                self.contatori.fetch_304 += 1
                return Risposta(
                    url=url, stato=304,
                    etag=testata.get("etag"), last_modified=testata.get("last-modified"),
                )
            if stato in _STATI_RITENTABILI and tentativo < self.tentativi:
                await self._dormi(self._attesa(tentativo))
                continue
            if stato >= 400:
                self.contatori.errori += 1
                logger.debug("[scarico] {} stato={}", url, stato)
                return Risposta(url=url, stato=stato, troncata=troncata)

            html = corpo
            return Risposta(
                url=url,
                stato=stato,
                html=html,
                testo=testo_da_html(html),
                etag=testata.get("etag"),
                last_modified=testata.get("last-modified"),
                troncata=troncata,
            )

        self.contatori.errori += 1
        if ultimo_errore is not None:
            logger.warning("[scarico] {} fallito: {}", url, ultimo_errore)
        return Risposta(url=url, stato=None)

    async def _una_get(
        self, url: str, intestazioni: dict[str, str],
    ) -> tuple[int, str, dict[str, str], bool]:
        """GET in streaming: il corpo si legge fino al limite e poi si tronca,
        cosi' un PDF da 200 MB non entra mai in memoria."""
        client = self.client()
        richiesta = client.build_request("GET", url, headers=intestazioni or None)
        risposta = await client.send(richiesta, stream=True, follow_redirects=True)
        try:
            pezzi: list[bytes] = []
            letti = 0
            troncata = False
            async for blocco in risposta.aiter_bytes():
                pezzi.append(blocco)
                letti += len(blocco)
                if letti >= self.limite_byte:
                    troncata = True
                    break
            grezzo = b"".join(pezzi)[: self.limite_byte]
            testate = {k.lower(): v for k, v in risposta.headers.items()}
            codifica = risposta.encoding or "utf-8"
            return risposta.status_code, grezzo.decode(codifica, "replace"), testate, troncata
        finally:
            await risposta.aclose()

    def _attesa(self, tentativo: int) -> float:
        """Backoff esponenziale: 0,5 s, 1 s, 2 s..."""
        return 0.5 * (2 ** tentativo)

    async def _via_firecrawl(self, url: str) -> Risposta | None:
        chiamata = self._firecrawl or _firecrawl_reale
        self.contatori.ripieghi_firecrawl += 1
        # Il credito si conta PRIMA della risposta: anche una chiamata fallita
        # puo' essere stata fatturata, e il tetto deve essere pessimista.
        self.contatori.crediti_firecrawl += CREDITI_PER_SCRAPE
        try:
            dati = await chiamata(url)
        except Exception as e:
            self.contatori.errori += 1
            logger.warning("[scarico] ripiego Firecrawl fallito per {}: {}", url, e)
            return None
        html = (dati or {}).get("html", "") or ""
        markdown = (dati or {}).get("markdown", "") or ""
        return Risposta(
            url=url,
            stato=200,
            html=html,
            testo=testo_da_html(html) or markdown,
            markdown=markdown,
            via="firecrawl",
        )


async def _firecrawl_reale(url: str) -> dict[str, str]:
    """Unica chiamata a `scrape_url` del package (fix 8.a.27).

    `proxy='basic'` evita lo stealth a 5 crediti, `parsers=[]` evita il parsing
    dei PDF (che facciamo con pdfplumber) e `max_age=0` vieta la cache di
    Firecrawl: un controllo deve vedere la pagina di adesso, non quella di ieri.
    """
    def _sincrono() -> dict[str, str]:
        from firecrawl import FirecrawlApp
        impostazioni = get_settings()
        if not impostazioni.firecrawl_api_key:
            raise RuntimeError("FIRECRAWL_API_KEY mancante")
        app = FirecrawlApp(api_key=impostazioni.firecrawl_api_key)
        risultato = app.scrape_url(
            url,
            formats=["html", "markdown"],
            only_main_content=False,
            max_age=0,
            proxy="basic",
            parsers=[],
        )
        if isinstance(risultato, dict):
            dati = risultato.get("data", risultato)
            return {"html": dati.get("html") or "", "markdown": dati.get("markdown") or ""}
        return {
            "html": getattr(risultato, "html", "") or "",
            "markdown": getattr(risultato, "markdown", "") or "",
        }

    return await asyncio.to_thread(_sincrono)


# ---------------------------------------------------------------------------
# Singleton di processo: i wrapper storici e i runner passano di qui
# ---------------------------------------------------------------------------

_SCARICO: Scarico | None = None


def scarico_corrente() -> Scarico:
    """Lo `Scarico` del giro. Gli host `richiede_js` arrivano dal registro."""
    global _SCARICO
    if _SCARICO is None:
        try:
            from .registro import host_richiede_js
            host = host_richiede_js()
        except Exception:                                 # pragma: no cover - ripiego
            host = frozenset()
        _SCARICO = Scarico(host_richiede_js=host)
    return _SCARICO


def imposta_scarico(scarico: Scarico | None) -> None:
    """Sostituisce il singleton (test e comandi con `--senza-rete`)."""
    global _SCARICO
    _SCARICO = scarico


def svuota() -> None:
    """Inizio giro: cache vuota e contatori azzerati."""
    scarico_corrente().nuovo_giro()


def contatori() -> Contatori:
    return scarico_corrente().contatori


async def chiudi() -> None:
    globale = _SCARICO
    if globale is not None:
        await globale.chiudi()


async def scarica_testo(url: str, *, principale: bool = False, **kwargs: Any) -> str:
    return await scarico_corrente().testo(url, principale=principale, **kwargs)


async def scarica_markdown(url: str, **kwargs: Any) -> str:
    return await scarico_corrente().markdown(url, **kwargs)


__all__ = [
    "AGGREGATORI", "Contatori", "Risposta", "Scarico", "ScaricoVietatoError",
    "chiudi", "contatori", "e_app_shell", "host_di", "imposta_scarico",
    "in_blocklist", "scarica_markdown", "scarica_testo", "scarico_corrente",
    "svuota", "testo_da_html",
]
