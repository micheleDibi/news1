# -*- coding: utf-8 -*-
"""Resolver della fonte ufficiale di un bando (piano §5).

Che cosa risolve
----------------
Oggi `bando.link_bando` punta nell'80 % dei casi a un aggregatore: il lettore
che clicca «vai al bando» finisce su obiettivoeuropa.com, non sul sito
dell'ente. Questo modulo trova, per ogni bando, **la pagina dell'ente** — e
quando non la trova lo dice, invece di offrire un link qualunque.

La cascata (§5), in ordine di costo crescente. Si scende solo se il passo non
produce un candidato che superi la soglia di `trovata`:

  1. link strutturato dalla fonte      0 crediti, 0 LLM
  2. gemello esatto gia' risolto       0 crediti, 0 LLM
  3a. sonda gratuita sull'host          0 crediti (max 3 GET)
  3b. ricerca vincolata a pagamento     2 crediti, ultima spiaggia
  5. allegati deterministici            0 crediti, sulla pagina trovata

Le tre regole che questo file fa rispettare
-------------------------------------------
* **Nessun URL nasce dall'LLM** (§5, decisione 8). Ogni candidato viene da
  HTML scaricato (con sha256 + offset), da `raw_data`, dal DB, da SEDIA o dal
  motore di ricerca; l'arbitro sceglie **per indice** fra candidati gia'
  esistenti e non puo' proporne di nuovi.
* **L'arbitro non promuove.** In zona grigia decide *quale* candidato
  riverificare, ma l'esito resta `in_verifica` con `candidato_prioritario`:
  `trovata` richiede ≥ 70 punti **e** tre segnali indipendenti, che sono fatti
  misurati sulla pagina, non un parere.
* **Il resolver non tocca lo stato.** Scrive `fonte_ufficiale_*`,
  `bando_link`, `bando_controllo` ed eventi; mai `stato_processing`, `slug`,
  `contenuto`, `data_pubblicazione`, `updated_at`, mai `stato_bando`.

Tutto l'I/O e' iniettato (`Ambiente`): i test non fanno rete e non toccano il
DB. Le scritture passano da `db.controllo` e degradano con un log se le
migrazioni v11 non sono ancora applicate.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from urllib.parse import urljoin, urlsplit
from dataclasses import dataclass, field, replace
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import AbstractSet, Any, Awaitable, Callable, Iterable, Mapping, Sequence

from . import allegati as allegati_mod
from . import bilancio, blocco, db, gemelli, impronte, oe_scheda, sedia, telemetria
from .dominio_ufficiale import (
    TABELLA_SEED,
    Tabella,
    classifica,
    dominio_di,
    e_aggregatore,
    registrabile,
    scegli_fonte,
    tipo_fonte_ufficiale,
)
from .date_validation import estrai_date_con_ruolo, norm_cit, scadenza_provvisoria
from .logger import logger
from .normalize import normalize_for_canonical
from .preprocessor import _auto_reject, _is_likely_index_url
from .stato_bando import oggi_roma


# --- soglie e costanti di §5 ------------------------------------------------

STATO_TROVATA = "trovata"
STATO_IN_VERIFICA = "in_verifica"
STATO_NON_TROVATA = "non_trovata"
STATI: tuple[str, ...] = (STATO_TROVATA, STATO_IN_VERIFICA, STATO_NON_TROVATA)

#: Ordine dei tre esiti: serve a `min()` quando un gate morbido impone un tetto.
_FORZA_STATO: dict[str, int] = {STATO_TROVATA: 2, STATO_IN_VERIFICA: 1, STATO_NON_TROVATA: 0}

SOGLIA_TROVATA = 70
SOGLIA_VERIFICA = 40
#: Lunghezza minima del testo perche' una pagina valga come prova.
TESTO_MINIMO = 500
#: I tre segnali indipendenti richiesti da `trovata`.
SEGNALE_DOMINIO = "dominio"
SEGNALE_TITOLO = "titolo"
SEGNALE_CONTENUTO = "contenuto"
SEGNALI_RICHIESTI: frozenset[str] = frozenset({SEGNALE_DOMINIO, SEGNALE_TITOLO, SEGNALE_CONTENUTO})

#: Cadenze di ricontrollo (A33): una sola, per tutti.
GIORNI_RICONTROLLO_BREVE = 14
TENTATIVI_BREVI = 3
GIORNI_RICONTROLLO_LUNGO = 60

#: Tetto di tempo per un solo bando, nel resolver e nei ricontrolli. Il
#: 28/09/2026, con il DNS di regione.basilicata.it rotto, un bando ha impiegato
#: 247 secondi, e i 101 URL di quell'host rischiavano cento minuti di giro.
#: Oltre il tetto il bando passa al giro dopo senza consumare un tentativo.
TETTO_TEMPO_BANDO_S = 120.0

#: Quanti host irraggiungibili la riga del giro elenca per nome: oltre si
#: legge solo il numero (`host_irraggiungibili`).
MAX_HOST_IRRAGGIUNGIBILI_ELENCO = 20

PRIORITA_IN_VERIFICA = 70
PRIORITA_NON_TROVATA = 30
PRIORITA_TROVATA = 30
PRIORITA_404 = 90

#: Jaccard fra i token del titolo del bando e quelli di `<title>`/`h1`/`og:title`.
JACCARD_ALTO = 0.50
JACCARD_MEDIO = 0.30

#: Seconda strada per lo stesso segnale: la **copertura**
#: `|titolo ∩ intestazioni| / |titolo|`. Il Jaccard e' simmetrico, quindi si
#: dilui'sce quando la pagina ripete il titolo e ci aggiunge il nome del
#: portale: misurato il 24/09/2026 su `portalebandi.regione.basilicata.it`, la
#: pagina conteneva il titolo del bando **per intero** (copertura 1,00) e il
#: Jaccard valeva 0,16, sotto ogni soglia. Le soglie qui sono piu' severe di
#: quelle del Jaccard proprio perche' la copertura non penalizza il rumore: si
#: accende solo quando l'intestazione contiene quasi tutto il titolo.
COPERTURA_ALTA = 0.80
COPERTURA_MEDIA = 0.60
#: Sotto questo numero di token distintivi la copertura non si guarda: «bando
#: formazione 2026» sta dentro mezzo portale e non prova niente.
TOKEN_MINIMI_COPERTURA = 4

#: Punteggio, voce per voce (§5). Tenerli qui invece che sparsi nel codice e'
#: cio' che rende il totale verificabile a mano da chi rilegge un esito.
PUNTI: dict[str, int] = {
    "dominio_ente": 30,
    "dominio_pattern": 25,
    "dominio_portale": 20,
    "titolo_alto": 25,
    "titolo_medio": 12,
    "ente": 10,
    "scadenza": 15,
    "scadenza_diversa": -15,
    "importo": 5,
    "atto": 5,
    "pdf_atto": 10,
    "strutturata": 10,
}

#: Metodi che valgono «provenienza strutturata»: l'URL non e' stato cercato,
#: e' stato dichiarato dalla fonte o ricavato da una chiave verificata.
METODI_STRUTTURATI: frozenset[str] = frozenset({
    "link_strutturato", "oe_scheda", "sedia", "gemello", "raw", "contenuto",
})

METODO_SONDA = "sonda"
METODO_RICERCA = "ricerca"

#: Tipi di candidato che non possono mai diventare `trovata` (A11, A32).
TIPI_MAI_TROVATA: frozenset[str] = frozenset({"calendario"})

_RE_SOFT_404 = re.compile(r"non\s+trovat|not\s+found|pagina\s+inesistente|errore\s*404", re.I)
_RE_PROROGA = re.compile(r"prorog|riapert|differi|proroga(?:to|ta)", re.I)
_RE_PDF = re.compile(r"\.pdf(?:$|[?#])", re.I)
_RE_AVVISO = re.compile(r"avvis|bando|decret|determin|deliber|graduator|allegat", re.I)

#: Chiavi di `raw_data` che contengono, per le varie fonti, un link diretto
#: alla pagina dell'ente. L'ordine e' quello di §5, passo 1.
CHIAVI_LINK_STRUTTURATO: tuple[str, ...] = (
    "external_link", "link_bando", "url_bando", "LINK", "URL", "link", "url",
)
#: `source_url` e' il file del calendario: un candidato legittimo, ma di tipo
#: `calendario`, che non vale mai `trovata`.
CHIAVE_CALENDARIO = "source_url"


class FonteUfficialeError(RuntimeError):
    """Errore non recuperabile del resolver. Non viene mai sollevato dentro la
    pipeline: `run()` lo cattura e restituisce un dizionario (A15)."""


# --- tipi -------------------------------------------------------------------

@dataclass(frozen=True)
class Pagina:
    """Una pagina scaricata. `html` resta in memoria: non finisce mai a DB."""
    url: str
    stato: int | None = None
    html: str = ""
    testo: str = ""
    intestazioni: str = ""          # <title> + h1 + og:title, gia' concatenati
    #: L'host non risolve (DNS): la pagina non e' stata letta (`scarico.py`).
    host_irraggiungibile: bool = False

    @property
    def ok(self) -> bool:
        return self.stato is not None and 200 <= int(self.stato) < 300

    @property
    def abbastanza_lunga(self) -> bool:
        return len(self.testo.strip()) >= TESTO_MINIMO


@dataclass(frozen=True)
class Candidato:
    """Un URL da valutare, con la sua provenienza e la sua prova."""
    url: str
    metodo: str = "link_strutturato"
    origine: str = "raw"            # valore di `bando_link.origine`
    tipo_dichiarato: str = ""       # es. 'calendario'
    ancora: str = ""
    prova: str = ""                 # sha256(scheda)#offset, quando esiste
    url_prova: str = ""             # pagina in cui l'href e' stato trovato
    pagina: Pagina | None = None
    #: Falso solo per i risultati di una ricerca **senza** `include_domains`:
    #: §5 le ammette ma ne limita l'esito a `in_verifica`, perche' un risultato
    #: non vincolato non prova la provenienza. Tutto il resto nasce vincolato.
    vincolata: bool = True

    @property
    def host(self) -> str:
        return dominio_di(self.url) or ""


@dataclass(frozen=True)
class Gate:
    """Esito di un gate. `morbido` = non boccia, impone il tetto `in_verifica`."""
    nome: str
    superato: bool
    morbido: bool = False
    dettaglio: str = ""


@dataclass(frozen=True)
class Punteggio:
    """Il verdetto deterministico su un candidato: numeri e motivi, mai pareri."""
    valore: int = 0
    voci: tuple[tuple[str, int], ...] = ()
    segnali: frozenset[str] = frozenset()
    gate: tuple[Gate, ...] = ()
    tipo: str | None = None
    e_atto: bool = False
    host: str = ""
    proroga: bool = False

    @property
    def duri_superati(self) -> bool:
        return all(g.superato or g.morbido for g in self.gate)

    @property
    def tetto(self) -> str | None:
        """`in_verifica` se un gate morbido e' fallito, altrimenti None."""
        return STATO_IN_VERIFICA if any(
            g.morbido and not g.superato for g in self.gate
        ) else None

    @property
    def stato(self) -> str:
        return esito_da_punteggio(self)

    def falliti(self) -> tuple[str, ...]:
        return tuple(g.nome for g in self.gate if not g.superato)


@dataclass(frozen=True)
class Contesto:
    """Cio' che il bando dichiara di se'. Puro: nessun I/O, nessuno stato."""
    bando_id: Any = None
    titolo: str = ""
    ente: str = ""
    data_scadenza: date_cls | None = None
    importo: int | None = None
    identificatori: tuple[str, ...] = ()
    numero_atto: str | None = None
    #: `titolo_raw`: come il bando si chiama nella fonte, non come lo abbiamo
    #: intitolato noi. E' quello che la pagina dell'ente porta davvero.
    titolo_fonte: str = ""
    tabella: Tabella = TABELLA_SEED
    #: Giro 3 (§7): `data_scadenza` e' la scadenza PROVVISORIA di una riga
    #: appena entrata (`date_validation.scadenza_provvisoria`), non quella del
    #: preprocess. Vale solo come conferma (+15), mai come smentita.
    scadenza_provvisoria: bool = False

    @property
    def token_titolo(self) -> frozenset[str]:
        return token(self.titolo)

    @property
    def token_titolo_fonte(self) -> frozenset[str]:
        """I token del titolo **della fonte** (`titolo_raw`).

        Esiste perche' `titolo` non e' il titolo del bando: e' il titolo
        editoriale che la pipeline genera per i lettori. Misurato il 24/09/2026
        su un caso qualunque:

            titolo      Contributi fondo perduto per cortometraggi di interesse
                        regionale in Sardegna
            titolo_raw  Sardegna - Concessione di contributi finalizzati alla
                        produzione di cortometraggi di rilevante interesse
                        regionale

        La pagina dell'ente porta il secondo, non il primo. Confrontare le
        intestazioni con il solo titolo editoriale faceva mancare il segnale
        «titolo» quasi sempre, e senza quello i tre segnali non si completano
        mai: 437 bandi avevano un punteggio da `trovata` e restavano
        `in_verifica` per questo motivo, su 2 134 pubblicati.
        """
        return token(self.titolo_fonte)

    @property
    def token_titolo_qualsiasi(self) -> frozenset[str]:
        """L'unione dei due titoli, per i gate che chiedono «almeno un token».

        Li' l'unione e' la cosa giusta: una pagina che contiene il titolo
        ufficiale ma non la nostra riscrittura non e' un soft-404 ne' una
        pagina indice.
        """
        return self.token_titolo | self.token_titolo_fonte


@dataclass
class Contatori:
    """Contatori del giro del resolver: finiscono in `pipeline_run`."""
    esaminati: int = 0
    trovate: int = 0
    in_verifica: int = 0
    non_trovate: int = 0
    gemelli: int = 0
    sonde: int = 0
    ricerche: int = 0
    ricerche_da_segnale: int = 0
    #: Ricerche partite senza `include_domains` (ente non mappato): §5 le
    #: ammette ma il loro esito non puo' superare `in_verifica`.
    ricerche_libere: int = 0
    arbitri: int = 0
    allegati: int = 0
    link_scritti: int = 0
    scarti_blocklist: int = 0
    #: Righe attraversate dalla selezione e NON lavorate perche' il loro
    #: ricontrollo non e' ancora dovuto. Non consumano il `--limit`: sono qui
    #: perche' un giro che ne salta 800 e ne lavora 2 deve poterlo dire.
    saltate: int = 0
    errori: int = 0
    #: Bandi lasciati al giro dopo senza verdetto e senza tentativo: oltre il
    #: `TETTO_TEMPO_BANDO_S`, o senza `trovata` con un candidato su un host
    #: che non risolve. Non sono in `trovate`/`in_verifica`/`non_trovate`.
    rinviati_tempo: int = 0
    rinviati_dns: int = 0
    #: Gli host che non risolvevano (DNS) fra i candidati di questo step.
    host_morti: set[str] = field(default_factory=set)
    interrotto_per_tetto: bool = False
    motivo: str = ""
    #: Giro 3 (§4): nei ricontrolli, a tetto raggiunto si saltano solo i passi
    #: a pagamento (ricerca, arbitro); gli scarichi continuano e il passo non
    #: si ferma. Quanti passi a pagamento sono stati saltati, e il primo motivo.
    passi_saltati_per_spesa: int = 0
    motivo_spesa: str = ""
    #: Giro 3 (§7), resolver precoce: gli esiti diversi da `trovata`, che non
    #: lasciano traccia (li riprende la passata `nuovi`), e le righe tolte dalla
    #: selezione (`processed` chiusi o revocati, scarti di `_auto_reject`).
    senza_traccia: int = 0
    esclusi_chiusi: int = 0
    esclusi_auto_reject: int = 0

    def come_dizionario(self) -> dict[str, Any]:
        return {
            "esaminati": self.esaminati,
            "trovate": self.trovate,
            "in_verifica": self.in_verifica,
            "non_trovate": self.non_trovate,
            "gemelli": self.gemelli,
            "sonde": self.sonde,
            "ricerche": self.ricerche,
            "ricerche_da_segnale": self.ricerche_da_segnale,
            "ricerche_libere": self.ricerche_libere,
            "arbitri": self.arbitri,
            "allegati": self.allegati,
            "link_scritti": self.link_scritti,
            "scarti_blocklist": self.scarti_blocklist,
            "saltate": self.saltate,
            "errori": self.errori,
            "rinviati_tempo": self.rinviati_tempo,
            "rinviati_dns": self.rinviati_dns,
            # Il numero e i primi nomi: lo stesso host morto per giorni si vede
            # a DB, giro dopo giro, in `pipeline_run`.
            "host_irraggiungibili": len(self.host_morti),
            "host_irraggiungibili_elenco": sorted(self.host_morti)[
                :MAX_HOST_IRRAGGIUNGIBILI_ELENCO],
            "passi_saltati_per_spesa": self.passi_saltati_per_spesa,
            "senza_traccia": self.senza_traccia,
            "esclusi_chiusi": self.esclusi_chiusi,
            "esclusi_auto_reject": self.esclusi_auto_reject,
        }


#: Le voci dello scarico che entrano nella spesa di un passo (§19.1).
VOCI_SCARICO: tuple[str, ...] = ("fetch", "fetch_304", "crediti_firecrawl")


@dataclass
class Ambiente:
    """Tutto l'I/O del resolver, iniettato. Senza una funzione, il passo che la
    userebbe viene semplicemente saltato: il resolver degrada, non fallisce."""
    tabella: Tabella = TABELLA_SEED
    scarica: Callable[[str], Awaitable[Pagina]] | None = None
    sonda: Callable[[Contesto, str], Awaitable[Sequence[str]]] | None = None
    ricerca: Callable[[str, Sequence[str]], Awaitable[Sequence[str]]] | None = None
    arbitro: Callable[[Contesto, Sequence[Candidato]], Awaitable[int | None]] | None = None
    sedia_dettaglio: Callable[[str], tuple[int, Any] | None] | None = None
    scheda_oe: Callable[[Mapping[str, Any]], Awaitable[oe_scheda.Scheda | None]] | None = None
    verifica_allegato: Callable[[str], Any] | None = None
    #: Giro 3 (P2 della revisione #144): la stessa verifica degli allegati, ma
    #: cortese e asincrona — lucchetto per host, freno di 1 s e richiesta in
    #: un thread. Con questa, `_passo_allegati` non blocca piu' l'event loop
    #: dei bandi in parallelo. Senza (test), resta la chiamata sincrona.
    verifica_cortese: Callable[[str], Awaitable[Any]] | None = None
    #: Chiusura del client HTTP della verifica, se ne esiste uno da chiudere.
    chiudi_verifica: Callable[[], None] | None = None
    pubblicati: Sequence[Mapping[str, Any]] = ()
    contatori: Contatori = field(default_factory=Contatori)
    spesa: bilancio.Contatori = field(default_factory=bilancio.Contatori)
    tetti: bilancio.Tetti = field(default_factory=bilancio.Tetti)
    #: Contatori di `scarico.py` (fetch, 304, crediti del ripiego Firecrawl).
    #: Senza questa funzione i tetti vedrebbero solo la ricerca a pagamento e
    #: `fetch` resterebbe a zero per sempre: il tetto per giro non morderebbe
    #: mai e i crediti del ripiego non entrerebbero nel tetto giornaliero.
    spesa_scarico: Callable[[], Any] | None = None
    #: Id dei bandi la cui scheda OE e' gia' stata letta (regola A29).
    schede_lette: frozenset[Any] = frozenset()
    #: Le righe di `bando_link` gia' in tabella, per bando. Sono i candidati che
    #: un giro precedente ha estratto — quasi tutti dalle schede OE — e senza
    #: di esse il passo 1 non li vedrebbe: la regola A29 vieta di riscaricare
    #: una scheda gia' letta, quindi `candidati_da_scheda` restituisce vuoto e
    #: il `link_bando` di quei bandi e' l'URL dell'aggregatore, che viene
    #: scartato. Il lotto `oe-dettaglio` riempirebbe una tabella che nessuno
    #: legge, e 1 724 bandi scenderebbero fino alla ricerca a pagamento.
    link_registrati: Mapping[Any, Sequence[Mapping[str, Any]]] = field(
        default_factory=dict)
    step: str = "resolver"
    oggi: date_cls = field(default_factory=oggi_roma)
    attivo: bool = False
    da_segnale: bool = False        # su segnale C: solo passi 1, 2 e 3a
    #: Giro 3 (§7): il resolver precoce lavora con la scadenza provvisoria.
    scadenza_provvisoria: bool = False
    #: Il consumo dei giri precedenti della giornata e del mese
    #: (`db.consumo_oggi`): lo leggono i tetti della manutenzione (§4).
    gia_oggi: Mapping[str, float] | None = None
    #: §18.5: `db.consumo_oggi` non si e' letto. Per la manutenzione vale tetto
    #: raggiunto (niente ricerche ne' arbitro, i controlli gratuiti continuano);
    #: l'ingresso e il backfill non lo guardano.
    consumo_illeggibile: bool = False
    max_sonda: int = 3
    max_candidati: int = 12
    tetto_tempo_bando_s: float = TETTO_TEMPO_BANDO_S
    #: Quanto di `spesa_scarico()` e' gia' stato sommato in `spesa`: i contatori
    #: dello scarico sono cumulativi sul giro, quindi si somma solo il delta.
    #: In produzione parte dai contatori correnti (`parti_da_qui`, §19.1).
    assorbito: dict[str, int] = field(default_factory=dict)

    def _contatori_scarico(self) -> Any:
        if self.spesa_scarico is None:
            return None
        try:
            return self.spesa_scarico()
        except Exception as e:                           # pragma: no cover - difesa
            logger.debug("[resolver] contatori dello scarico non leggibili: {}", e)
            return None

    def parti_da_qui(self) -> None:
        """La passata conta solo cio' che lo scarico fa da adesso (§19.1).

        I contatori dello scarico si azzerano solo a inizio giro: con
        `assorbito` vuoto ognuna delle tre passate (precoce, nuovi,
        ricontrolli) riassorbiva tutto il giro, e i crediti del precoce
        finivano in tre righe. Preprocess, enrich e rielaborazione scrivono
        nella loro riga il proprio delta.
        """
        contatori = self._contatori_scarico()
        if contatori is None:
            return
        self.assorbito = {nome: int(getattr(contatori, nome, 0) or 0) for nome in VOCI_SCARICO}

    def assorbi_spesa(self) -> None:
        """Porta in `spesa` la parte non ancora contata dello scarico."""
        contatori = self._contatori_scarico()
        if contatori is None:
            return
        for nome in VOCI_SCARICO:
            attuale = int(getattr(contatori, nome, 0) or 0)
            gia = self.assorbito.get(nome, 0)
            # Contatori azzerati nel frattempo (`scarico.svuota`): conta da zero.
            delta = attuale - gia if attuale >= gia else attuale
            if delta > 0:
                setattr(self.spesa, nome, getattr(self.spesa, nome) + delta)
            self.assorbito[nome] = attuale

    def consentito(self) -> bilancio.Esito:
        """I tetti mordono qui, una volta per bando: §5 e M19.

        Giro 3 (§4): per la catena d'ingresso (`resolver_precoce`, `resolver`)
        `bilancio.verifica` dice sempre si': si conta e basta.
        """
        self.assorbi_spesa()
        if self.consumo_illeggibile:
            return bilancio.verifica_con_consumo(self.spesa, self.tetti, step=self.step,
                                                 consumo=None)
        return bilancio.verifica(self.spesa, self.tetti, step=self.step, gia_oggi=self.gia_oggi)

    def deve_fermarsi(self) -> bool:
        """Il passo si ferma del tutto? Solo un lotto di backfill a tetto (M19).

        La catena d'ingresso non si ferma mai e la manutenzione di regime (i
        ricontrolli) a tetto continua i controlli gratuiti (giro 3, §4): per
        loro i tetti mordono solo sui passi a pagamento (`puo_spendere`).
        """
        if not bilancio.e_backfill(self.step):
            return False
        esito = self.consentito()
        if esito.consentito:
            return False
        self.ferma_per_tetto(esito)
        return True

    def puo_spendere(self) -> bool:
        """Un passo a pagamento (ricerca, arbitro) puo' partire?

        A tetto raggiunto: un lotto di backfill si ferma (`ferma_per_tetto`),
        la manutenzione di regime salta solo questo passo e prosegue.
        """
        esito = self.consentito()
        if esito.consentito:
            return True
        if bilancio.e_backfill(self.step):
            self.ferma_per_tetto(esito)
        else:
            self.contatori.passi_saltati_per_spesa += 1
            if not self.contatori.motivo_spesa:
                self.contatori.motivo_spesa = esito.motivo
        return False

    def ferma_per_tetto(self, esito: bilancio.Esito) -> None:
        """Registra il motivo una volta sola: chi legge il dizionario finale
        deve trovare il primo tetto raggiunto, non l'ultimo controllato."""
        if not self.contatori.interrotto_per_tetto:
            self.contatori.interrotto_per_tetto = True
            self.contatori.motivo = esito.motivo


@dataclass(frozen=True)
class Esito:
    """Verdetto su un bando: cio' che `scrivi_esito` traduce in colonne."""
    bando_id: Any
    stato: str = STATO_NON_TROVATA
    url: str | None = None
    host: str | None = None
    tipo: str | None = None
    e_atto: bool = False
    confidenza: int = 0
    metodo: str = ""
    candidato_prioritario: str | None = None
    prova: str = ""
    url_prova: str = ""
    gemello: Any = None
    allegati: tuple[Mapping[str, str], ...] = ()
    #: Stato HTTP **osservato** sulla pagina scelta e, per ogni allegato, sul
    #: documento verificato. Il CHECK della 02 pretende un 2xx per ogni riga
    #: `pubblicabile`: scriverci un 200 di convenzione significherebbe
    #: registrare come misura una cosa che nessuno ha misurato.
    esito_http: int | None = None
    stati_allegati: tuple[tuple[str, int | None], ...] = ()
    valutati: tuple[tuple[Candidato, Punteggio], ...] = ()
    proroga: bool = False
    tentativi: int = 0
    prossimo_controllo: date_cls | None = None
    priorita: int = PRIORITA_NON_TROVATA
    motivo: str = ""


# --- helper puri ------------------------------------------------------------

def token(testo: str | None) -> frozenset[str]:
    """Token confrontabili: la stessa normalizzazione di `canonical_key`, cosi'
    non nasce una seconda nozione di «parola uguale»."""
    return frozenset(t for t in normalize_for_canonical(testo or "").split() if len(t) > 2)


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    """|A∩B| / |A∪B|. Zero se uno dei due insiemi e' vuoto."""
    insieme_a, insieme_b = frozenset(a), frozenset(b)
    if not insieme_a or not insieme_b:
        return 0.0
    return len(insieme_a & insieme_b) / len(insieme_a | insieme_b)


def copertura(a: Iterable[str], b: Iterable[str]) -> float:
    """|A∩B| / |A|: quanta parte di `a` compare in `b`. Zero se `a` e' vuoto.

    Non e' simmetrica, ed e' il punto: `a` e' il titolo del bando, `b` sono le
    intestazioni della pagina, e una pagina ha tutto il diritto di dire piu'
    cose del titolo (il nome del portale, la sezione, il titolo ripetuto due
    volte fra `<title>` e `h1`).
    """
    insieme_a, insieme_b = frozenset(a), frozenset(b)
    if not insieme_a:
        return 0.0
    return len(insieme_a & insieme_b) / len(insieme_a)


def somiglianza_titolo(
    contesto: "Contesto", intestazioni: Iterable[str],
) -> tuple[float, str]:
    """La somiglianza del titolo, e con quale metrica e' stata ottenuta.

    Si prende il migliore fra quattro numeri: il Jaccard e la copertura, ognuno
    sul titolo editoriale e su quello della fonte. La copertura entra sulla
    scala del Jaccard (`JACCARD_ALTO`/`JACCARD_MEDIO`) solo dopo aver superato
    le proprie soglie, piu' severe: cosi' le due metriche restano confrontabili
    dal chiamante senza che la piu' generosa abbassi la soglia dell'altra.
    """
    ints = frozenset(intestazioni)
    migliore, metrica = 0.0, ""
    for nome, titolo in (("titolo", contesto.token_titolo),
                         ("titolo_fonte", contesto.token_titolo_fonte)):
        valore = jaccard(titolo, ints)
        if valore > migliore:
            migliore, metrica = valore, f"jaccard/{nome}"
        if len(titolo) < TOKEN_MINIMI_COPERTURA:
            continue
        cop = copertura(titolo, ints)
        # La copertura non porta un valore proprio: porta il verdetto. Sotto
        # `COPERTURA_MEDIA` non dice niente, e non deve poter abbassare un
        # Jaccard piu' alto.
        promosso = (JACCARD_ALTO if cop >= COPERTURA_ALTA
                    else JACCARD_MEDIO if cop >= COPERTURA_MEDIA else 0.0)
        if promosso > migliore:
            migliore, metrica = promosso, f"copertura/{nome}"
    return migliore, metrica


def intestazioni_pagina(html: str | None) -> str:
    """`<title>` + `h1` + `og:title`, e **mai** il corpo (§5).

    Il vincolo e' il punto: un ente che elenca cento bandi in home ha nel corpo
    i token di tutti, e un Jaccard sul corpo darebbe 25 punti a chiunque.
    """
    if not html:
        return ""
    pezzi: list[str] = []
    try:
        zuppa = impronte._zuppa(html)
    except Exception:                                   # pragma: no cover - ripiego
        return ""
    if zuppa.title and zuppa.title.string:
        pezzi.append(str(zuppa.title.string))
    for h1 in zuppa.find_all("h1"):
        pezzi.append(h1.get_text(" ", strip=True))
    for meta in zuppa.find_all("meta"):
        proprieta = str(meta.get("property") or meta.get("name") or "").lower()
        if proprieta in ("og:title", "twitter:title"):
            pezzi.append(str(meta.get("content") or ""))
    return " ".join(p.strip() for p in pezzi if p and p.strip())


def pagina_da_risposta(risposta: Any) -> Pagina:
    """Adattatore da `scarico.Risposta` a `Pagina`. Tollerante di proposito:
    i test costruiscono oggetti finti e non l'intera dataclass dello scarico."""
    html = getattr(risposta, "html", "") or ""
    return Pagina(
        url=getattr(risposta, "url", "") or "",
        stato=getattr(risposta, "stato", None),
        html=html,
        testo=getattr(risposta, "testo", "") or "",
        intestazioni=intestazioni_pagina(html),
        host_irraggiungibile=bool(getattr(risposta, "host_irraggiungibile", False)),
    )


def e_soft_404(pagina: Pagina, contesto: Contesto) -> bool:
    """Pagina «non trovato» servita con 200: e' un 404 travestito (§5).

    Le due condizioni sono entrambe necessarie: la sola parola «non trovato»
    compare anche in pagine legittime («documentazione non trovata? scrivici»),
    ed e' l'assenza dei token del titolo a dire che non e' la pagina del bando.
    """
    if not _RE_SOFT_404.search(pagina.testo or ""):
        return False
    return not (contesto.token_titolo_qualsiasi
                & token(f"{pagina.intestazioni} {pagina.testo[:2000]}"))


def e_pagina_indice(candidato: Candidato, contesto: Contesto) -> bool:
    """Pagina di elenco invece che del bando.

    Due indizi, quello dell'URL (riusando `preprocessor._is_likely_index_url`,
    che gia' conosce `/bandi`, `/avvisi`, `?page=`) e quello delle
    intestazioni: un `<title>` che non contiene nemmeno un token del titolo del
    bando e' un titolo di sezione.
    """
    if _is_likely_index_url(candidato.url):
        return True
    intestazioni = token(candidato.pagina.intestazioni if candidato.pagina else "")
    if not intestazioni or not contesto.token_titolo_qualsiasi:
        return False
    return not (contesto.token_titolo_qualsiasi & intestazioni)


def punti_dominio(tipo: str) -> int:
    """Punti del dominio per tipo. `dedotto` e `sconosciuto` valgono zero: un
    host dedotto non e' una prova, e infatti porta al massimo a `in_verifica`."""
    return {
        "ente": PUNTI["dominio_ente"],
        "pattern": PUNTI["dominio_pattern"],
        "portale_pubblico": PUNTI["dominio_portale"],
    }.get(tipo, 0)


def date_nel_ruolo(testo: str, ruolo: str = "scadenza") -> tuple[date_cls, ...]:
    """Le date che il testo assegna a quel ruolo (mai tutte le date trovate)."""
    return tuple(d.data for d in estrai_date_con_ruolo(testo) if d.ruolo == ruolo)


def _importo_coerente(pagina: Pagina, importo: int | None) -> bool:
    """L'importo a DB compare nel testo, in una delle grafie italiane usuali."""
    if not importo or importo <= 0 or not pagina.testo:
        return False
    normalizzato = norm_cit(pagina.testo)
    for grafia in (
        f"{importo:,}".replace(",", "."),
        f"{importo:,}".replace(",", " "),
        str(importo),
    ):
        if grafia and grafia in normalizzato:
            return True
    # Milioni scritti a parole: «10 milioni» per 10 000 000.
    if importo % 1_000_000 == 0 and f"{importo // 1_000_000} milion" in normalizzato:
        return True
    return False


def _pdf_atto_sul_dominio(candidato: Candidato) -> bool:
    """Un PDF di avviso/atto sullo stesso dominio registrabile della pagina."""
    pagina = candidato.pagina
    if pagina is None or not pagina.html:
        return False
    dominio = registrabile(candidato.url)
    if not dominio:
        return False
    for trovato in re.finditer(r'href\s*=\s*["\']([^"\']+)["\']', pagina.html, re.I):
        href = trovato.group(1)
        if not _RE_PDF.search(href):
            continue
        assoluto = href if href.startswith("http") else candidato.url.rsplit("/", 1)[0] + "/" + href.lstrip("/")
        if registrabile(assoluto) == dominio:
            return True
    return False


def _e_atto(candidato: Candidato, contesto: Contesto, tipo: str | None) -> bool:
    """`fonte_ufficiale_e_atto`: il PDF dell'atto sul dominio dell'ente (A11)."""
    if tipo != "ente" or not _RE_PDF.search(candidato.url):
        return False
    testo = f"{candidato.ancora} {candidato.url}"
    return bool(contesto.numero_atto) or bool(_RE_AVVISO.search(testo))


# --- gate e punteggio -------------------------------------------------------

def gate_duri(candidato: Candidato, contesto: Contesto) -> tuple[Gate, ...]:
    """I gate di §5, nell'ordine in cui vanno applicati.

    I primi quattro sono **duri**: un candidato che ne fallisce uno non e' la
    fonte, punto. Gli ultimi tre sono **morbidi**: non bocciano, ma impongono
    il tetto `in_verifica`, perche' il candidato e' plausibile e merita un
    ricontrollo, non una condanna a sessanta giorni. Il terzo morbido e' il
    tetto di §5 sulla ricerca non vincolata: «ente non mappato -> ricerca senza
    `include_domains` ma esito massimo `in_verifica`».
    """
    host = candidato.host
    tipo_dominio = classifica(host, contesto.tabella)
    pagina = candidato.pagina
    gate: list[Gate] = [
        Gate("blocklist", not e_aggregatore(host, contesto.tabella), dettaglio=host),
        Gate("whitelist", tipo_dominio != "sconosciuto", dettaglio=tipo_dominio),
        Gate(
            "http_2xx_500",
            bool(pagina and pagina.ok and pagina.abbastanza_lunga),
            dettaglio=f"stato={getattr(pagina, 'stato', None)} "
                      f"caratteri={len(pagina.testo) if pagina else 0}",
        ),
        Gate(
            "non_soft_404",
            not (pagina is not None and e_soft_404(pagina, contesto)),
        ),
        Gate(
            "non_indice",
            not e_pagina_indice(candidato, contesto),
            morbido=True,
        ),
        Gate(
            "dominio_provato",
            tipo_dominio != "dedotto",
            morbido=True,
            dettaglio=tipo_dominio,
        ),
        Gate(
            "tipo_ammesso",
            candidato.tipo_dichiarato not in TIPI_MAI_TROVATA,
            morbido=True,
            dettaglio=candidato.tipo_dichiarato,
        ),
        Gate(
            "ricerca_vincolata",
            candidato.vincolata,
            morbido=True,
            dettaglio=candidato.metodo,
        ),
    ]
    return tuple(gate)


def punteggia(candidato: Candidato, contesto: Contesto) -> Punteggio:
    """Il punteggio 0-100 di §5, con i gate e i tre segnali.

    Il totale e' la somma delle `voci`: chi rilegge un esito puo' rifare il
    conto a mano. L'unica voce negativa e' `scadenza_diversa`, che e' anche il
    segnale di una proroga da passare al monitor.
    """
    host = candidato.host
    gate = gate_duri(candidato, contesto)
    tipo_dominio = classifica(host, contesto.tabella)
    if not all(g.superato for g in gate if not g.morbido):
        return Punteggio(gate=gate, host=host, tipo=None)

    pagina = candidato.pagina or Pagina(url=candidato.url)
    voci: list[tuple[str, int]] = []
    segnali: set[str] = set()

    punti = punti_dominio(tipo_dominio)
    if punti:
        voci.append(("dominio", punti))
        segnali.add(SEGNALE_DOMINIO)

    # Il migliore di quattro confronti: Jaccard e copertura, ognuno sul titolo
    # editoriale e su quello della fonte. Il solo Jaccard sul solo titolo
    # editoriale faceva scattare il segnale quasi mai, per due motivi diversi:
    # il titolo editoriale e' scritto per i lettori (vedi
    # `Contesto.token_titolo_fonte`) e il Jaccard si diluisce quando la pagina
    # ripete il titolo e ci aggiunge il nome del portale (vedi `copertura`).
    intestazioni = token(pagina.intestazioni)
    somiglianza, _metrica = somiglianza_titolo(contesto, intestazioni)
    if somiglianza >= JACCARD_ALTO:
        voci.append(("titolo", PUNTI["titolo_alto"]))
        segnali.add(SEGNALE_TITOLO)
    elif somiglianza >= JACCARD_MEDIO:
        voci.append(("titolo", PUNTI["titolo_medio"]))

    if contesto.ente and norm_cit(contesto.ente) in norm_cit(
            f"{pagina.intestazioni} {pagina.testo}"):
        voci.append(("ente", PUNTI["ente"]))

    proroga = False
    if contesto.data_scadenza:
        scadenze = date_nel_ruolo(pagina.testo, "scadenza")
        if contesto.data_scadenza in scadenze:
            voci.append(("scadenza", PUNTI["scadenza"]))
            segnali.add(SEGNALE_CONTENUTO)
        elif contesto.scadenza_provvisoria:
            # Una scadenza provvisoria (giro 3, §7) conferma e non smentisce:
            # una data diversa sulla pagina non toglie punti e non e' una
            # proroga, perche' la data vera la decide il preprocess.
            pass
        elif scadenze and not _RE_PROROGA.search(pagina.testo or ""):
            # Data diversa nello stesso ruolo e nessuna parola di proroga: il
            # candidato perde punti ed entra nella coda del monitor come
            # possibile proroga, che solo lui puo' verificare con i gate G1-G9.
            voci.append(("scadenza_diversa", PUNTI["scadenza_diversa"]))
            proroga = True
        elif scadenze:
            proroga = True

    if _importo_coerente(pagina, contesto.importo):
        voci.append(("importo", PUNTI["importo"]))
        segnali.add(SEGNALE_CONTENUTO)

    if contesto.numero_atto and gemelli.numero_atto(
            {"titolo": f"{pagina.intestazioni} {pagina.testo[:4000]}"}) == contesto.numero_atto:
        voci.append(("atto", PUNTI["atto"]))
        segnali.add(SEGNALE_CONTENUTO)

    if contesto.identificatori and any(
            i.casefold() in (pagina.testo or "").casefold() for i in contesto.identificatori):
        segnali.add(SEGNALE_CONTENUTO)

    if _pdf_atto_sul_dominio(candidato):
        voci.append(("pdf_atto", PUNTI["pdf_atto"]))

    if candidato.metodo in METODI_STRUTTURATI:
        voci.append(("strutturata", PUNTI["strutturata"]))

    totale = max(0, min(100, sum(p for _, p in voci)))
    tipo = tipo_fonte_ufficiale(host, contesto.tabella)
    return Punteggio(
        valore=totale,
        voci=tuple(voci),
        segnali=frozenset(segnali),
        gate=gate,
        tipo=tipo,
        e_atto=_e_atto(candidato, contesto, tipo),
        host=host,
        proroga=proroga,
    )


def esito_da_punteggio(punteggio: Punteggio) -> str:
    """Soglie di §5. Un gate morbido fallito e' un **tetto**, non un voto.

    `trovata` pretende due cose insieme: 70 punti e i tre segnali indipendenti.
    Il **tipo non entra** nella condizione: il CHECK della 01
    (`fonte_ufficiale_tipo IS NULL OR IN ('ente','portale_pubblico')`) ammette
    NULL, e §13 lo elenca fra i valori validi. Un host riconosciuto solo per
    forma (`regione.*.it`, `*.gov.it`, `*.camcom.it`, …) vale 25 punti di
    dominio proprio perche' possa arrivare a 70: pretendere anche il tipo
    bloccherebbe a `in_verifica` tutta la fetta regionale, che e' la piu'
    grande. I soli tetti sono quelli dei gate morbidi (`dedotto`, `calendario`,
    ricerca non vincolata, pagina indice).
    """
    if not punteggio.duri_superati:
        return STATO_NON_TROVATA
    if punteggio.valore >= SOGLIA_TROVATA and SEGNALI_RICHIESTI <= punteggio.segnali:
        stato = STATO_TROVATA
    elif punteggio.valore >= SOGLIA_VERIFICA:
        stato = STATO_IN_VERIFICA
    else:
        stato = STATO_NON_TROVATA
    tetto = punteggio.tetto
    if tetto is not None and _FORZA_STATO[stato] > _FORZA_STATO[tetto]:
        return tetto
    return stato


def zona_grigia(
    valutati: Sequence[tuple[Candidato, Punteggio]],
) -> tuple[tuple[Candidato, Punteggio], ...]:
    """I candidati 40-69 che superano i gate duri: la zona dell'arbitro."""
    return tuple(
        (c, p) for c, p in valutati
        if p.duri_superati and SOGLIA_VERIFICA <= p.valore < SOGLIA_TROVATA
    )


# --- cadenze di ricontrollo (A33) -------------------------------------------

def prossimo_controllo(
    stato: str, tentativi: int, oggi: date_cls,
) -> tuple[date_cls, int, int]:
    """(data del prossimo controllo, priorita', tentativi aggiornati).

    Una sola cadenza in tutto il piano: `in_verifica` a 14 giorni per tre
    tentativi e poi ogni 60; `non_trovata` ogni 60. `trovata` non ha un
    ricontrollo del resolver: la pagina passa al monitor.

    E «passa al monitor» ha una conseguenza sulla data, che il codice sbagliava.
    `prossimo_controllo_at` e' **una sola colonna per due mestieri**: il
    resolver ci scrive quando tornare a cercare la fonte, il monitor ci legge la
    sua coda (`select_bandi_da_monitorare` piu' il filtro di scadenza). Mettere
    sessanta giorni su un bando appena risolto significava chiudere fuori il
    monitor proprio dai bandi che in quel momento diventavano controllabili.

    Misurato il 24/09/2026: risolte 213 fonti, e `monitor --ombra` rispondeva
    `candidati: 0` perche' tutti e 213 avevano il prossimo controllo a piu' di
    due settimane. La catena resolver -> monitor -> eventi -> box
    «Aggiornamenti» era interrotta al primo anello, e nessun contatore lo
    diceva: il monitor riferiva un giro riuscito con zero candidati.

    Quindi per `trovata` la data e' **oggi**: la riga resta dovuta e il primo
    giro del monitor la prende e da li' in poi la cadenza la decide lui, per
    fase. Il resolver non la riprendera' comunque, perche' la sua selezione
    esclude le righe `trovata` (`_filtra_selezione`), tranne con `--forza`, che
    ha la sua guardia sul giorno.
    """
    prossimi = max(0, int(tentativi)) + 1
    if stato == STATO_TROVATA:
        return oggi, PRIORITA_TROVATA, prossimi
    if stato == STATO_IN_VERIFICA:
        giorni = (
            GIORNI_RICONTROLLO_BREVE if prossimi <= TENTATIVI_BREVI else GIORNI_RICONTROLLO_LUNGO
        )
        return oggi + timedelta(days=giorni), PRIORITA_IN_VERIFICA, prossimi
    return oggi + timedelta(days=GIORNI_RICONTROLLO_LUNGO), PRIORITA_NON_TROVATA, prossimi


def scaduto(
    controllo: Mapping[str, Any] | None, oggi: date_cls, forza: bool = False,
) -> bool:
    """Il ricontrollo e' dovuto? Una riga senza `bando_controllo` lo e' sempre.

    Il filtro sta qui e non nella query perche' `prossimo_controllo_at` vive in
    `bando_controllo` e un embed PostgREST sulla tabella con la RLS piu' stretta
    del DB costerebbe un 42501 ogni volta. `--forza` salta il controllo: e'
    l'unico modo di ricontrollare un bando prima della sua data, e infatti si
    chiede a mano.
    """
    if forza or not controllo:
        return True
    quando = controllo.get("prossimo_controllo_at")
    if not quando:
        return True
    try:
        return date_cls.fromisoformat(str(quando)[:10]) <= oggi
    except ValueError:
        # Data illeggibile: si ricontrolla. Saltare una riga per colpa di un
        # formato inatteso significherebbe non guardarla mai piu'.
        return True


# --- costruzione dei candidati (passo 1, puro) ------------------------------

def contesto_da_bando(
    bando: Mapping[str, Any], *, tabella: Tabella = TABELLA_SEED, provvisoria: bool = False,
) -> Contesto:
    """`Contesto` da una riga di `bando`. Nessun I/O.

    `provvisoria=True` (il resolver precoce, giro 3 §7): la scadenza e' quella
    che la riga dichiara prima del preprocess (`scadenza_provvisoria`), con
    `data_scadenza` come ripiego, e vale solo come conferma.
    """
    titolo = str(bando.get("titolo") or bando.get("titolo_raw") or "").strip()
    scadenza = bando.get("data_scadenza")
    if isinstance(scadenza, str):
        try:
            scadenza = date_cls.fromisoformat(scadenza[:10])
        except ValueError:
            scadenza = None
    if provvisoria:
        scadenza = scadenza_provvisoria(dict(bando)) or scadenza
    importo = bando.get("importo_totale_eur")
    try:
        importo = int(importo) if importo is not None else None
    except (TypeError, ValueError):
        importo = None
    grezzo = bando.get("raw_data") if isinstance(bando.get("raw_data"), Mapping) else {}
    identificatori = sedia.identificatori(
        " ".join(str(v) for v in (titolo, bando.get("titolo_raw"), grezzo.get("identifier")) if v)
    )
    return Contesto(
        bando_id=bando.get("id"),
        titolo=titolo,
        titolo_fonte=str(bando.get("titolo_raw") or "").strip(),
        ente=str(bando.get("ente_erogatore") or "").strip(),
        data_scadenza=scadenza if isinstance(scadenza, date_cls) else None,
        importo=importo,
        identificatori=identificatori,
        numero_atto=gemelli.numero_atto(bando),
        tabella=tabella,
        scadenza_provvisoria=provvisoria,
    )


def _url_validi(valore: Any) -> tuple[str, ...]:
    if not valore:
        return ()
    testo = str(valore).strip()
    if testo.startswith(("http://", "https://")):
        return (testo,)
    return ()


def _link_dal_contenuto(contenuto: Any) -> tuple[tuple[str, str], ...]:
    """I deep link dei segmenti `link` del `contenuto` (i 104 C-deep di §5)."""
    trovati: list[tuple[str, str]] = []

    def visita(nodo: Any) -> None:
        if isinstance(nodo, Mapping):
            if nodo.get("kind") == "link":
                for url in _url_validi(nodo.get("url")):
                    trovati.append((url, str(nodo.get("text") or "")))
            for valore in nodo.values():
                visita(valore)
        elif isinstance(nodo, (list, tuple)):
            for valore in nodo:
                visita(valore)

    visita(contenuto)
    return tuple(dict.fromkeys(trovati))


def candidati_strutturati(
    bando: Mapping[str, Any], *, tabella: Tabella = TABELLA_SEED,
) -> tuple[Candidato, ...]:
    """Passo 1 di §5: i link che la fonte ha gia' dichiarato. Zero crediti.

    Gli host aggregatori non entrano: da loro si leggono segnali, mai la fonte
    ufficiale (e' la stessa regola del trigger a DB).
    """
    grezzo = bando.get("raw_data") if isinstance(bando.get("raw_data"), Mapping) else {}
    proposte: list[tuple[str, str, str, str]] = []      # url, origine, tipo, ancora
    for chiave in CHIAVI_LINK_STRUTTURATO:
        for url in _url_validi(grezzo.get(chiave)):
            proposte.append((url, "raw", "", chiave))
    for url in _url_validi(grezzo.get(CHIAVE_CALENDARIO)):
        proposte.append((url, "raw", "calendario", CHIAVE_CALENDARIO))
    for url in _url_validi(bando.get("link_bando")):
        proposte.append((url, "raw", "", "link_bando"))
    for url, ancora in _link_dal_contenuto(bando.get("contenuto")):
        proposte.append((url, "contenuto", "", ancora))

    candidati: list[Candidato] = []
    viste: set[str] = set()
    for url, origine, tipo, ancora in proposte:
        if e_aggregatore(url, tabella):
            continue
        chiave = impronte.normalizza_url(url) or url
        if chiave in viste:
            continue
        viste.add(chiave)
        candidati.append(Candidato(
            url=url,
            metodo="contenuto" if origine == "contenuto" else "link_strutturato",
            origine=_origine_link(url, tabella),
            tipo_dichiarato=tipo,
            ancora=ancora,
        ))
    return tuple(candidati)


def candidati_da_scheda(
    scheda: oe_scheda.Scheda | None, *, tabella: Tabella = TABELLA_SEED,
) -> tuple[Candidato, ...]:
    """I candidati della scheda OE, con la prova `sha256#offset` gia' dentro."""
    if scheda is None:
        return ()
    prodotti: list[Candidato] = []
    for voce in scheda.candidati:
        if e_aggregatore(voce.url, tabella):
            continue
        prodotti.append(Candidato(
            url=voce.url,
            metodo="oe_scheda",
            origine="aggregatore",     # l'href e' stato trovato sulla scheda OE
            ancora=voce.ancora,
            prova=voce.prova,
            url_prova=scheda.url,
        ))
    return tuple(prodotti)


def candidati_da_link_registrati(
    righe: Sequence[Mapping[str, Any]], *, tabella: Tabella = TABELLA_SEED,
) -> tuple[Candidato, ...]:
    """I candidati che stanno gia' in `bando_link`, messi li' da un giro prima.

    Sono la memoria del lotto `oe-dettaglio`: l'href all'ente trovato sulla
    scheda dell'aggregatore, con la prova `sha256#offset` e l'URL della scheda
    da cui viene. Il resolver li rivaluta da se' — scarica la pagina, applica i
    gate, assegna il punteggio — quindi **non serve** che la riga sia gia'
    `pubblicabile`: quella colonna la decide `link-verifica`, che e' un altro
    mestiere.

    Senza questa funzione la catena si spezzava in silenzio nel punto peggiore:
    `oe-dettaglio` scriveva 3 887 link, la regola A29 vietava (giustamente) di
    riscaricare le schede gia' lette, e al passo 1 non arrivava niente.

    Le righe `raw` del backfill della 02 non si escludono: sono `link_bando` e
    allegati che il passo 1 guarda comunque, e il dedup per URL normalizzato le
    fa collassare.
    """
    prodotti: list[Candidato] = []
    viste: set[str] = set()
    for riga in righe:
        url = str(riga.get("url") or "")
        if not url or e_aggregatore(url, tabella):
            continue
        chiave = impronte.normalizza_url(url) or url
        if chiave in viste:
            continue
        viste.add(chiave)
        prova = riga.get("impronta_pagina")
        prodotti.append(Candidato(
            url=url,
            # Con la prova della scheda il metodo e' quello: vale il punteggio
            # «provenienza strutturata», come se la scheda fosse stata letta in
            # questo giro. Senza prova e' un link grezzo del backfill.
            metodo="oe_scheda" if prova else "link_strutturato",
            origine=str(riga.get("origine") or _origine_link(url, tabella)),
            tipo_dichiarato=str(riga.get("tipo") or ""),
            ancora=str(riga.get("etichetta") or ""),
            prova=str(prova) if prova else "",
            url_prova=str(riga.get("url_prova") or ""),
        ))
    return tuple(prodotti)


def _origine_da_metodo(url: str, metodo: str, tabella: Tabella) -> str:
    """Valore di `bando_link.origine` (CHECK della 02), dal metodo o dal dominio.

    `ricerca` e `contenuto` sono valori ammessi dal CHECK e dicono una cosa che
    il dominio non sa: che quell'URL e' costato crediti, o che veniva da un
    deep link del testo. Ricalcolarlo dall'host li perderebbe entrambi, e la
    provenienza «ricerca» e' l'unico modo, a posteriori, di sapere quali fonti
    sono state pagate.
    """
    if metodo in ("ricerca", "contenuto"):
        return metodo
    if metodo == "oe_scheda":
        # L'href e' stato trovato sulla scheda dell'aggregatore: e' cio' che
        # `origine` registra (la 02: «i ~1360 link all'ente estratti dalle
        # schede dell'aggregatore nascono con origine='aggregatore'»). La
        # pubblicabilita' la decide il dominio del link, non questa colonna.
        return "aggregatore"
    return _origine_link(url, tabella)


def _origine_link(url: str, tabella: Tabella) -> str:
    """Valore di `bando_link.origine` dedotto dal dominio (CHECK della 02)."""
    tipo = classifica(url, tabella)
    if tipo in ("ente", "pattern"):
        return "ente"
    if tipo == "portale_pubblico":
        return "portale_pubblico"
    if tipo == "aggregatore":
        return "aggregatore"
    return "raw"


def query_ricerca(contesto: Contesto, *, filetype_pdf: bool = False) -> str:
    """Le due query vincolate di §5. La seconda si usa solo se la prima ha
    prodotto un candidato 40-69: cercare due volte per niente costa il doppio."""
    parole = [p for p in normalize_for_canonical(contesto.titolo).split() if len(p) > 2][:10]
    pezzi: list[str] = []
    if contesto.numero_atto:
        pezzi.append(f'"{contesto.numero_atto.split(":", 1)[0]}"')
    pezzi.extend(parole)
    if contesto.data_scadenza:
        pezzi.append(str(contesto.data_scadenza.year))
    query = " ".join(pezzi).strip()
    return f"{query} filetype:pdf" if filetype_pdf else query


def domini_ammessi(contesto: Contesto, bando: Mapping[str, Any]) -> tuple[str, ...]:
    """I domini a cui vincolare la ricerca (max 20, §5).

    Senza domini la ricerca resta lecita ma l'esito massimo e' `in_verifica`:
    un risultato non vincolato non e' una prova di provenienza. Il tetto non
    vive qui — questa funzione e' pura — ma sul `Candidato` (`vincolata=False`)
    e sul gate morbido `ricerca_vincolata` di `gate_duri`.
    """
    host: list[str] = []
    for riga in contesto.tabella.attive():
        if riga.e_pattern or riga.tipo == "aggregatore":
            continue
        if riga.ente and contesto.ente and token(riga.ente) & token(contesto.ente):
            host.append(riga.host)
    for campo in ("link_bando", "fonte_ufficiale_url"):
        valore = bando.get(campo)
        if valore and not e_aggregatore(str(valore), contesto.tabella):
            dominio = dominio_di(str(valore))
            if dominio:
                host.append(dominio)
    return tuple(dict.fromkeys(host))[:20]


# --- cascata ----------------------------------------------------------------

async def _valuta(
    candidati: Sequence[Candidato],
    contesto: Contesto,
    ambiente: Ambiente,
) -> list[tuple[Candidato, Punteggio]]:
    """Scarica e punteggia i candidati, fermandosi al primo `trovata`.

    Fermarsi e' l'ottimizzazione che conta: il passo 1 produce spesso cinque
    candidati e il primo e' quasi sempre quello giusto; scaricarli tutti
    moltiplicherebbe il traffico senza cambiare l'esito.
    """
    valutati: list[tuple[Candidato, Punteggio]] = []
    if ambiente.scarica is None:
        return valutati
    # Fino a `max_candidati` scarichi per bando, piu' sonda e gemello. Gli
    # scarichi del resolver sono gratuiti (niente ripiego Firecrawl): li ferma
    # solo un lotto di backfill a tetto, mai l'ingresso ne' i ricontrolli
    # (giro 3, §4).
    if ambiente.deve_fermarsi():
        return valutati
    for candidato in candidati[: ambiente.max_candidati]:
        if e_aggregatore(candidato.url, ambiente.tabella):
            ambiente.contatori.scarti_blocklist += 1
            continue
        try:
            pagina = await ambiente.scarica(candidato.url)
        except Exception as e:
            ambiente.contatori.errori += 1
            logger.info("[resolver] {} non scaricato: {}", candidato.url, e)
            continue
        con_pagina = replace(candidato, pagina=pagina)
        punteggio = punteggia(con_pagina, contesto)
        valutati.append((con_pagina, punteggio))
        if punteggio.stato == STATO_TROVATA:
            break
    return valutati


def _migliore(
    valutati: Sequence[tuple[Candidato, Punteggio]],
) -> tuple[Candidato, Punteggio] | None:
    """Il candidato con l'esito piu' forte; a parita', il punteggio piu' alto."""
    ammessi = [(c, p) for c, p in valutati if p.duri_superati]
    if not ammessi:
        return None
    return max(ammessi, key=lambda voce: (_FORZA_STATO[voce[1].stato], voce[1].valore))


async def _passo_gemello(
    bando: Mapping[str, Any], ambiente: Ambiente,
) -> tuple[Mapping[str, Any], Any] | None:
    """Passo 2: un gemello **esatto** gia' risolto regala la sua fonte.

    Solo criteri esatti (`gemelli.trova_master`): il fuzzy produce proposte da
    leggere, non fonti da ereditare.
    """
    if not ambiente.pubblicati:
        return None
    trovato = gemelli.trova_master(bando, ambiente.pubblicati)
    if trovato is None:
        return None
    master, corrispondenza = trovato
    if str(master.get("fonte_ufficiale_stato") or "") != STATO_TROVATA:
        return None
    if not master.get("fonte_ufficiale_url"):
        return None
    ambiente.contatori.gemelli += 1
    return master, corrispondenza


async def _passo_sonda(
    contesto: Contesto, bando: Mapping[str, Any], ambiente: Ambiente,
) -> tuple[Candidato, ...]:
    """Passo 3a: sonda gratuita sull'host dell'ente (max 3 GET, zero crediti)."""
    if ambiente.sonda is None:
        return ()
    host = ""
    for campo in ("fonte_ufficiale_host", "link_bando"):
        valore = bando.get(campo)
        if valore and not e_aggregatore(str(valore), ambiente.tabella):
            host = dominio_di(str(valore)) or ""
            if host:
                break
    if not host:
        return ()
    try:
        urls = await ambiente.sonda(contesto, host)
    except Exception as e:
        ambiente.contatori.errori += 1
        logger.info("[resolver] sonda su {} fallita: {}", host, e)
        return ()
    ambiente.contatori.sonde += 1
    return tuple(
        Candidato(url=u, metodo=METODO_SONDA, origine=_origine_link(u, ambiente.tabella))
        for u in list(urls)[: ambiente.max_sonda]
        if _url_validi(u) and not e_aggregatore(u, ambiente.tabella)
    )


async def _passo_ricerca(
    contesto: Contesto,
    bando: Mapping[str, Any],
    ambiente: Ambiente,
    *,
    filetype_pdf: bool = False,
) -> tuple[Candidato, ...]:
    """Passo 3b: ricerca vincolata a pagamento. L'ultima, e con i tetti davanti."""
    if ambiente.ricerca is None:
        return ()
    if ambiente.da_segnale:
        # Su segnale C il resolver rifa' solo i passi 1-2 e 3a: la ricerca
        # resta legata alla cadenza dei ricontrolli (§5). Il contatore e'
        # atteso a zero: se cresce, qualcuno ha aggirato la regola.
        ambiente.contatori.ricerche_da_segnale += 1
        return ()
    if not ambiente.puo_spendere():
        return ()
    domini = domini_ammessi(contesto, bando)
    try:
        urls = await ambiente.ricerca(query_ricerca(contesto, filetype_pdf=filetype_pdf), domini)
    except Exception as e:
        ambiente.contatori.errori += 1
        logger.info("[resolver] ricerca fallita per bando {}: {}", contesto.bando_id, e)
        return ()
    ambiente.contatori.ricerche += 1
    ambiente.spesa.ricerche += 1
    ambiente.spesa.crediti_firecrawl += 2               # 2 crediti a blocco (§5)
    if not domini:
        ambiente.contatori.ricerche_libere += 1
    return tuple(
        Candidato(
            url=u, metodo=METODO_RICERCA, origine="ricerca", vincolata=bool(domini),
        )
        for u in list(urls)[:5]
        if _url_validi(u) and not e_aggregatore(u, ambiente.tabella)
    )


async def _passo_arbitro(
    contesto: Contesto,
    valutati: Sequence[tuple[Candidato, Punteggio]],
    ambiente: Ambiente,
) -> str | None:
    """L'arbitro LLM sceglie **per indice** in zona grigia, e non promuove.

    Il valore di ritorno e' un `candidato_prioritario` da riverificare al
    ricontrollo successivo: l'esito del bando resta `in_verifica`. E' la
    differenza fra «il modello ha un'opinione» e «la pagina lo dimostra».
    """
    grigi = zona_grigia(valutati)
    if ambiente.arbitro is None or len(grigi) < 2:
        return None
    # L'arbitro chiama un modello: a tetto la manutenzione lo salta (§4).
    if not ambiente.puo_spendere():
        return None
    try:
        indice = await ambiente.arbitro(contesto, [c for c, _ in grigi])
    except Exception as e:
        ambiente.contatori.errori += 1
        logger.info("[resolver] arbitro non disponibile: {}", e)
        return None
    ambiente.contatori.arbitri += 1
    if indice is None:
        return None
    try:
        posizione = int(indice)
    except (TypeError, ValueError):
        return None
    if not 0 <= posizione < len(grigi):
        # Un indice fuori intervallo e' un'allucinazione: si scarta, non si
        # «aggiusta» con un clamp, che darebbe per buona una scelta mai fatta.
        logger.info("[resolver] arbitro: indice {} fuori intervallo, ignorato", indice)
        return None
    return grigi[posizione][0].url


async def _passo_allegati(
    candidato: Candidato, contesto: Contesto, ambiente: Ambiente,
) -> tuple[tuple[Mapping[str, str], ...], tuple[tuple[str, int | None], ...]]:
    """Passo 5: allegati deterministici della pagina ufficiale (0 crediti).

    Restituisce la forma fissa `{label, url, tipo}` di §13.4 **e**, a parte, lo
    stato HTTP osservato su ciascun documento: la forma e' un contratto con
    BandoFit e non puo' crescere di una chiave, ma `bando_link.esito_http` deve
    dire cio' che la verifica ha visto.
    """
    pagina = candidato.pagina
    if pagina is None or not pagina.html or ambiente.verifica_allegato is None:
        return (), ()
    try:
        if ambiente.verifica_cortese is not None:
            # Giro 3: `estrai` (sincrono) gira in un thread, e ogni sua verifica
            # torna sull'event loop per prendere il lucchetto dell'host e il
            # freno (`verifica_sincrona_cortese`). Il loop resta libero perche'
            # qui si fa `await` sul thread, mai una chiamata sincrona.
            verifica = verifica_sincrona_cortese(
                ambiente.verifica_cortese, asyncio.get_running_loop())
            estrazione = await asyncio.to_thread(
                allegati_mod.estrai, pagina.html, candidato.url, contesto.titolo,
                verifica=verifica, blocklist=ambiente.tabella,
            )
        else:
            estrazione = allegati_mod.estrai(
                pagina.html, candidato.url, contesto.titolo,
                verifica=ambiente.verifica_allegato,
                blocklist=ambiente.tabella,
            )
    except Exception as e:
        ambiente.contatori.errori += 1
        logger.info("[resolver] allegati di {} non estratti: {}", candidato.url, e)
        return (), ()
    ambiente.contatori.allegati += len(estrazione.allegati)
    stati = tuple(
        (a.url, a.verifica.esito_http if a.verifica is not None else None)
        for a in estrazione.allegati
    )
    return tuple(estrazione.forma()), stati


#: Quanto un thread di `allegati.estrai` aspetta una verifica cortese: il
#: lucchetto dell'host puo' essere preso da un altro bando, ma un host appeso
#: non deve tenere fermo il thread per sempre. Oltre, la verifica vale «nessuna
#: risposta» (None), come quando la richiesta non arriva.
TIMEOUT_VERIFICA_CORTESE_S = 90.0


def verifica_sincrona_cortese(
    cortese: Callable[[str], Awaitable[Any]],
    ciclo: asyncio.AbstractEventLoop,
    *,
    timeout_s: float = TIMEOUT_VERIFICA_CORTESE_S,
) -> Callable[[str], Any]:
    """Il `verifica(url)` sincrono che `allegati.estrai` si aspetta, da
    chiamare **da un thread**: rimanda la coroutine cortese sull'event loop
    (`run_coroutine_threadsafe`) e ne aspetta il risultato con un timeout.
    Un errore o il timeout valgono None («nessuna risposta»): un'eccezione
    qui farebbe fallire l'estrazione di tutti gli allegati della pagina."""
    def verifica(url: str) -> Any:
        futuro = asyncio.run_coroutine_threadsafe(cortese(url), ciclo)
        try:
            return futuro.result(timeout=timeout_s)
        except Exception as e:
            futuro.cancel()
            logger.info("[resolver] verifica di {} senza risposta: {}", url, type(e).__name__)
            return None
    return verifica


async def risolvi(bando: Mapping[str, Any], ambiente: Ambiente) -> Esito:
    """La cascata a cinque passi di §5 su **un** bando. Non solleva mai.

    L'ordine e' quello del costo: si scende solo se il passo precedente non ha
    prodotto una fonte `trovata`. La ricerca a pagamento e' l'ultima e passa
    dai tetti; gli allegati si estraggono solo sulla pagina effettivamente
    scelta, mai sui candidati scartati.
    """
    contesto = contesto_da_bando(
        bando, tabella=ambiente.tabella, provvisoria=ambiente.scadenza_provvisoria)
    ambiente.contatori.esaminati += 1
    tentativi = int(bando.get("tentativi_resolver") or 0)

    scheda: oe_scheda.Scheda | None = None
    if ambiente.scheda_oe is not None:
        try:
            scheda = await ambiente.scheda_oe(bando)
        except Exception as e:
            ambiente.contatori.errori += 1
            logger.info("[resolver] scheda OE non letta per {}: {}", contesto.bando_id, e)

    # Passo 1 — link strutturati, scheda OE e cio' che un giro precedente ha
    # gia' registrato in `bando_link` (senza questi ultimi il lotto delle
    # schede non alimenta niente: vedi `candidati_da_link_registrati`).
    candidati = list(candidati_strutturati(bando, tabella=ambiente.tabella))
    candidati.extend(candidati_da_scheda(scheda, tabella=ambiente.tabella))
    candidati.extend(candidati_da_link_registrati(
        ambiente.link_registrati.get(bando.get("id")) or (),
        tabella=ambiente.tabella,
    ))
    candidati.extend(_candidati_sedia(contesto, ambiente))
    valutati = await _valuta(candidati, contesto, ambiente)
    migliore = _migliore(valutati)

    # Passo 2 — gemello esatto gia' risolto.
    gemello = None
    if migliore is None or migliore[1].stato != STATO_TROVATA:
        trovato = await _passo_gemello(bando, ambiente)
        if trovato is not None:
            master, corrispondenza = trovato
            gemello = corrispondenza
            ereditato = Candidato(
                url=str(master.get("fonte_ufficiale_url")),
                metodo="gemello",
                origine=_origine_link(str(master.get("fonte_ufficiale_url")), ambiente.tabella),
            )
            nuovi = await _valuta([ereditato], contesto, ambiente)
            valutati.extend(nuovi)
            migliore = _migliore(valutati)

    # Passo 3a — sonda gratuita.
    if migliore is None or migliore[1].stato != STATO_TROVATA:
        sondati = await _passo_sonda(contesto, bando, ambiente)
        if sondati:
            valutati.extend(await _valuta(sondati, contesto, ambiente))
            migliore = _migliore(valutati)

    # Passo 3b — ricerca vincolata. La seconda query parte solo se la prima ha
    # prodotto un candidato in zona grigia (§5): senza quella condizione si
    # pagherebbero due ricerche anche quando la prima non ha trovato nulla.
    if migliore is None or migliore[1].stato != STATO_TROVATA:
        cercati = await _passo_ricerca(contesto, bando, ambiente)
        if cercati:
            valutati.extend(await _valuta(cercati, contesto, ambiente))
            migliore = _migliore(valutati)
        if (migliore is None or migliore[1].stato != STATO_TROVATA) and zona_grigia(valutati):
            cercati = await _passo_ricerca(contesto, bando, ambiente, filetype_pdf=True)
            if cercati:
                valutati.extend(await _valuta(cercati, contesto, ambiente))
                migliore = _migliore(valutati)

    prioritario = None
    if migliore is None or migliore[1].stato != STATO_TROVATA:
        prioritario = await _passo_arbitro(contesto, valutati, ambiente)

    allegati: tuple[Mapping[str, str], ...] = ()
    stati_allegati: tuple[tuple[str, int | None], ...] = ()
    if migliore is not None and migliore[1].stato == STATO_TROVATA:
        allegati, stati_allegati = await _passo_allegati(migliore[0], contesto, ambiente)

    return _componi_esito(
        contesto, valutati, migliore, ambiente,
        gemello=gemello, prioritario=prioritario, tentativi=tentativi,
        allegati=allegati, stati_allegati=stati_allegati,
    )


def _candidati_sedia(contesto: Contesto, ambiente: Ambiente) -> tuple[Candidato, ...]:
    """URL deterministico di SEDIA, accettato solo con l'identifier nel JSON.

    Due gate, entrambi obbligatori (§5): il topic risponde 200 e l'identifier
    compare davvero nel payload. Un URL costruito da un identifier non
    verificato sarebbe un URL inventato con un'altra grammatica.
    """
    if ambiente.sedia_dettaglio is None or not contesto.identificatori:
        return ()
    prodotti: list[Candidato] = []
    for identifier in contesto.identificatori[:3]:
        try:
            esito = sedia.dettaglio(identifier, ambiente.sedia_dettaglio)
        except Exception as e:
            ambiente.contatori.errori += 1
            logger.info("[resolver] SEDIA {} non interrogabile: {}", identifier, e)
            continue
        if esito is None:
            continue
        url, _payload = esito
        prodotti.append(Candidato(url=url, metodo="sedia", origine="portale_pubblico"))
    return tuple(prodotti)


#: Stati HTTP che dicono «riprova», non «non esiste». Un 5xx e' un guasto del
#: server dell'ente, un 429 e' un nostro eccesso, e nessuna risposta e' la
#: nostra rete: in tutti e tre i casi del bando non sappiamo niente.
_STATI_RIPROVABILI: frozenset[int] = frozenset({429, 500, 502, 503, 504, 408, 425})


def _non_giudicabile(candidato: Candidato) -> bool:
    """Questo candidato non e' stato giudicato: non e' arrivata una risposta.

    Un 404 e' un giudizio (quella pagina non c'e'), e una pagina scaricata che
    non parla del nostro bando e' un giudizio. Un timeout, un 503 o un 429 no:
    sono notizie sulla rete, non sul bando.
    """
    pagina = candidato.pagina
    if pagina is None or pagina.stato is None:
        return True
    return int(pagina.stato) in _STATI_RIPROVABILI


def _esito_senza_candidato_valido(
    valutati: Sequence[tuple[Candidato, Punteggio]],
) -> tuple[str, str]:
    """Lo stato e il motivo quando nessun candidato ha superato i gate.

    `non_trovata` significa «cercato e non c'e'», e costa sessanta giorni di
    attesa prima del ricontrollo (A33). Darlo quando le pagine non si sono
    potute scaricare sarebbe registrare come assenza un guasto nostro o
    dell'ente: e' lo stesso difetto che `link-verifica` aveva sui link morti.
    Se c'erano candidati e **nessuno** di loro ha risposto, l'esito e'
    `in_verifica`, che torna in coda in quattordici giorni.
    """
    if not valutati:
        return STATO_NON_TROVATA, "nessun candidato"
    if all(_non_giudicabile(c) for c, _ in valutati):
        return (STATO_IN_VERIFICA,
                "nessuna risposta dai candidati: guasto di rete, non assenza della fonte")
    return STATO_NON_TROVATA, "nessun candidato ha superato i gate"


def _componi_esito(
    contesto: Contesto,
    valutati: Sequence[tuple[Candidato, Punteggio]],
    migliore: tuple[Candidato, Punteggio] | None,
    ambiente: Ambiente,
    *,
    gemello: Any = None,
    prioritario: str | None = None,
    tentativi: int = 0,
    allegati: tuple[Mapping[str, str], ...] = (),
    stati_allegati: tuple[tuple[str, int | None], ...] = (),
) -> Esito:
    """Dal miglior candidato all'`Esito`, con cadenza e priorita' gia' dentro."""
    senza_candidato, motivo_senza = _esito_senza_candidato_valido(valutati)
    stato = migliore[1].stato if migliore is not None else senza_candidato
    data, priorita, tentativi_nuovi = prossimo_controllo(stato, tentativi, ambiente.oggi)
    if stato == STATO_TROVATA:
        ambiente.contatori.trovate += 1
    elif stato == STATO_IN_VERIFICA:
        ambiente.contatori.in_verifica += 1
    else:
        ambiente.contatori.non_trovate += 1

    if migliore is None:
        return Esito(
            bando_id=contesto.bando_id,
            stato=senza_candidato,
            candidato_prioritario=prioritario,
            valutati=tuple(valutati),
            tentativi=tentativi_nuovi,
            prossimo_controllo=data,
            priorita=priorita,
            motivo=motivo_senza,
        )
    candidato, punteggio = migliore
    trovata = stato == STATO_TROVATA
    return Esito(
        bando_id=contesto.bando_id,
        stato=stato,
        url=candidato.url if trovata else None,
        host=punteggio.host if trovata else None,
        tipo=punteggio.tipo if trovata else None,
        e_atto=punteggio.e_atto if trovata else False,
        confidenza=punteggio.valore,
        metodo=candidato.metodo,
        candidato_prioritario=prioritario or (None if trovata else candidato.url),
        prova=candidato.prova,
        url_prova=candidato.url_prova,
        gemello=gemello,
        allegati=allegati,
        stati_allegati=stati_allegati,
        esito_http=candidato.pagina.stato if candidato.pagina is not None else None,
        valutati=tuple(valutati),
        proroga=punteggio.proroga,
        tentativi=tentativi_nuovi,
        prossimo_controllo=data,
        priorita=priorita,
        motivo="" if trovata else f"gate falliti: {punteggio.falliti() or '(nessuno)'}",
    )


# --- scrittura --------------------------------------------------------------

def _adesso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _e_2xx(stato: Any) -> bool:
    """Il CHECK della 02 pretende `esito_http BETWEEN 200 AND 299` su ogni riga
    pubblicabile: senza stato osservato la riga non e' pubblicabile."""
    try:
        return 200 <= int(stato) < 300
    except (TypeError, ValueError):
        return False


def payload_fonte(esito: Esito, *, link_id: Any = None) -> dict[str, Any]:
    """Le colonne `fonte_ufficiale_*` che corrispondono all'esito.

    `trovata` senza `fonte_ufficiale_link_id` viola il CHECK della 03: se il
    link non e' stato scritto (tabella assente), l'esito si degrada a
    `in_verifica` invece di produrre una riga che il DB rifiuterebbe.

    `fonte_ufficiale_e_atto` non compare: la vista lo calcola da
    `bando_link.tipo = 'atto'` (migrazione 05), quindi il resolver lo esprime
    con il tipo della riga di link, non con una colonna che non esiste.
    """
    trovata = esito.stato == STATO_TROVATA and link_id is not None
    stato = esito.stato if trovata or esito.stato != STATO_TROVATA else STATO_IN_VERIFICA
    return {
        "fonte_ufficiale_stato": stato,
        "fonte_ufficiale_url": esito.url if trovata else None,
        "fonte_ufficiale_host": esito.host if trovata else None,
        "fonte_ufficiale_tipo": esito.tipo if trovata else None,
        "fonte_ufficiale_confidenza": int(esito.confidenza),
        "fonte_ufficiale_metodo": esito.metodo or None,
        "fonte_ufficiale_verificata_at": _adesso() if trovata else None,
        "fonte_ufficiale_link_id": link_id if trovata else None,
    }


def righe_link(esito: Esito, *, tabella: Tabella = TABELLA_SEED) -> list[dict[str, Any]]:
    """Le righe di `bando_link` che l'esito produce.

    `pubblicabile` e' vero solo per la fonte `trovata` e per gli allegati gia'
    verificati 2xx: e' la promessa di §13.4 a BandoFit, e qui e' una condizione
    di codice prima che un trigger a DB. Lo stato HTTP e' quello **osservato**:
    il CHECK `bando_link_pubblicabile_http_check` della 02 rifiuta una riga
    pubblicabile senza un 2xx, quindi le due cose devono nascere insieme.
    """
    stati = dict(esito.stati_allegati)
    righe: list[dict[str, Any]] = []
    if esito.url:
        righe.append({
            "bando_id": esito.bando_id,
            "url": esito.url,
            "tipo": "atto" if esito.e_atto else "pagina_bando",
            "origine": _origine_da_metodo(esito.url, esito.metodo, tabella),
            "etichetta": None,
            "esito_http": esito.esito_http,
            "ultimo_visto_at": _adesso(),
            "trovato_in_fonte_at": _adesso(),
            "url_prova": esito.url_prova or None,
            "impronta_pagina": esito.prova or None,
            "pubblicabile": esito.stato == STATO_TROVATA and _e_2xx(esito.esito_http),
        })
    for allegato in esito.allegati:
        url = str(allegato.get("url") or "")
        stato = stati.get(url)
        righe.append({
            "bando_id": esito.bando_id,
            "url": allegato.get("url"),
            "tipo": "allegato",
            "origine": _origine_link(url, tabella),
            "etichetta": allegato.get("label"),
            "content_type": allegato.get("tipo"),
            "esito_http": stato,
            "ultimo_visto_at": _adesso(),
            "trovato_in_fonte_at": _adesso(),
            "pubblicabile": _e_2xx(stato),
        })
    return righe


# --- la prova di provenienza di un link (giro 3, §10) -------------------------

def _forme_relative(url: str, url_pagina: str | None) -> tuple[str, ...]:
    """Gli `href` relativi con cui la pagina puo' citare `url` quando stanno
    sullo stesso host: `href="/path?query"` (fra virgolette, perche' un
    percorso nudo come «/bandi» comparirebbe ovunque)."""
    if not url_pagina or dominio_di(url) != dominio_di(url_pagina):
        return ()
    parti = urlsplit(url)
    relativo = parti.path + (f"?{parti.query}" if parti.query else "")
    if not relativo or relativo == "/":
        return ()
    forme: list[str] = []
    for forma in oe_scheda._forme_href(relativo):
        for virgolette in ('"', "'"):
            candidata = f"href={virgolette}{forma}{virgolette}"
            if candidata not in forme:
                forme.append(candidata)
    return tuple(forme)


#: I caratteri che possono chiudere un URL nell'HTML: virgolette, i bordi di
#: un tag, uno spazio, e il frammento (`#sezione` e' la stessa risorsa).
#: Tutto il resto lo continua: `?id=1` non e' `?id=12`, `avviso` non e'
#: `avviso-2024.pdf` (revisione #147, P1).
_FINE_URL = frozenset('"\'<> \t\r\n#')


def _occorrenza_intera(html: str, forma: str) -> int:
    """La prima posizione di `forma` nell'HTML seguita da un confine
    (`_FINE_URL` o la fine del testo), o -1. Senza confine un URL
    risulterebbe «trovato» dentro un URL piu' lungo che lo contiene."""
    inizio = html.find(forma)
    while inizio >= 0:
        fine = inizio + len(forma)
        if fine >= len(html) or html[fine] in _FINE_URL:
            return inizio
        inizio = html.find(forma, inizio + 1)
    return -1


def prova_nella_pagina(url: str, html: str | None, url_pagina: str | None = None) -> str | None:
    """`"<sha256 della pagina>#<offset>"` se `url` compare nell'HTML, o None.

    La stessa forma della prova delle schede OE (`oe_scheda.analizza`): il
    primo valore identifica la pagina, il secondo dice dove sta il link. Si
    cerca l'URL assoluto nelle forme di `oe_scheda._forme_href` (anche con le
    entita' HTML), poi l'`href` relativo quando link e pagina stanno sullo
    stesso host, che e' il caso comune degli allegati sul sito dell'ente.
    """
    if not url or not html:
        return None
    for forma in oe_scheda._forme_href(url):
        posizione = _occorrenza_intera(html, forma)
        if posizione >= 0:
            return f"{oe_scheda.impronta_scheda(html)}#{posizione}"
    for forma in _forme_relative(url, url_pagina):
        posizione = html.find(forma)
        if posizione >= 0:
            # L'offset e' quello del valore dell'attributo, come per le schede.
            return f"{oe_scheda.impronta_scheda(html)}#{posizione + len('href=') + 1}"
    return None


def pagina_di_riferimento(bando: Mapping[str, Any]) -> str:
    """La pagina in cui un link del bando deve comparire (giro 3, §10).

    Con la fonte `trovata`, la pagina scelta da `scegli_fonte` (l'ufficiale,
    o `link_bando` se l'ufficiale e' un PDF). Altrimenti `link_bando`, anche
    se e' un aggregatore (decisione del lead dell'01/10, misura D1: la stessa
    informazione che il sito mostra oggi dalle colonne).
    """
    if str(bando.get("fonte_ufficiale_stato") or "") == STATO_TROVATA:
        url, _ufficiale = scegli_fonte(bando)
        if url:
            return url
    return str(bando.get("link_bando") or "").strip()


#: Le sole fonti del link di candidatura che diventano una riga (§10): un
#: `fallback_source` e' l'URL della fonte rimesso li' dalla skill, non un link
#: trovato nella pagina.
SORGENTE_CANDIDATURA_ESTRATTA = "extracted"


def righe_link_da_payload(
    bando: Mapping[str, Any],
    payload: Mapping[str, Any],
    html_riferimento: str | None,
    *,
    url_riferimento: str | None = None,
    tabella: Tabella = TABELLA_SEED,
    guardia: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """Le righe di `bando_link` di un bando appena pubblicato (giro 3, §10).

    Dal payload SEO validato: la candidatura, solo se
    `link_candidatura_source='extracted'`, e gli allegati. Le chiama
    `bando_seo_runner._do_one` (M3) dopo un `update_bando_completed` riuscito e
    le scrive con `db.upsert_bando_link`; le colonne vecchie di `bando` restano
    scritte fino alla migrazione 07.

    Ogni riga nasce `pubblicabile=false` e senza `esito_http`: la
    pubblicabilita' la decide solo `link-verifica`. La prova si calcola qui
    sull'HTML della pagina da cui la SEO ha preso il testo
    (`html_riferimento`, l'HTML grezzo); `url_riferimento` e' l'URL effettivo
    di quella pagina (di norma `url_finale`), con `pagina_di_riferimento` come
    ripiego. Niente URL non http(s) (il CHECK `bando_link_url_valido` farebbe
    fallire l'upsert dell'intero lotto) ne' su un aggregatore (non sarebbero
    mai pubblicabili). `tabella` decide `origine` (di norma la whitelist del
    DB, `_tabella_corrente()`; il seed per difetto).

    §18.6: un URL che risolve a un indirizzo interno non entra in `bando_link`
    (`guardia`, di norma `http.classifica_indirizzo`). Un DNS che non risponde
    non basta a scartare: la riga nasce non pubblicabile e la verifica dei link
    la guarda di nuovo prima di ogni richiesta.
    """
    bando_id = bando.get("id")
    if bando_id is None:
        return []
    if guardia is None:
        from .http import classifica_indirizzo as guardia
    pagina = str(url_riferimento or pagina_di_riferimento(bando) or "") or None
    adesso = _adesso()
    righe: list[dict[str, Any]] = []
    visti: set[str] = set()

    def aggiungi(url: Any, tipo: str, etichetta: Any = None, content_type: Any = None) -> None:
        testo = str(url or "").strip()
        if not testo.lower().startswith(("http://", "https://")) or e_aggregatore(testo, tabella):
            return
        if guardia(testo) == _RIFIUTATO:
            logger.warning("[seo] link {} del bando {} scartato: indirizzo non pubblico",
                           testo, bando_id)
            return
        chiave = impronte.normalizza_url(testo) or testo
        if chiave in visti:
            return
        visti.add(chiave)
        prova = prova_nella_pagina(testo, html_riferimento, pagina)
        righe.append({
            "bando_id": bando_id,
            "url": testo,
            "tipo": tipo,
            "origine": _origine_link(testo, tabella),
            "etichetta": (str(etichetta).strip() or None) if etichetta else None,
            "content_type": content_type or None,
            "esito_http": None,
            "pubblicabile": False,
            "impronta_pagina": prova,
            "url_prova": pagina if prova else None,
            "trovato_in_fonte_at": adesso if prova else None,
        })

    if payload.get("link_candidatura_source") == SORGENTE_CANDIDATURA_ESTRATTA:
        aggiungi(payload.get("link_candidatura"), "candidatura")
    for allegato in payload.get("allegati") or ():
        if isinstance(allegato, Mapping):
            aggiungi(allegato.get("url"), "allegato", allegato.get("label"), allegato.get("tipo"))
    return righe


def payload_controllo(esito: Esito, *, gia_trovata: bool = False) -> dict[str, Any]:
    """Le colonne calde di `bando_controllo`. Mai su `bando` (§5, A8/A27).

    Giro 3 (§7): `prossimo_controllo_at` e `priorita_controllo` di un bando
    che era GIA' `trovata` (`--forza`, `--id`) sono del monitor e non si
    toccano. Un bando che diventa `trovata` adesso riceve `oggi`, il seme della
    coda del monitor.
    """
    payload = {
        "ultimo_controllo_at": _adesso(),
        "prossimo_controllo_at": (
            esito.prossimo_controllo.isoformat() if esito.prossimo_controllo else None
        ),
        "priorita_controllo": int(esito.priorita),
        "tentativi_resolver": int(esito.tentativi),
        "candidato_prioritario": esito.candidato_prioritario,
    }
    if gia_trovata and esito.stato == STATO_TROVATA:
        del payload["prossimo_controllo_at"]
        del payload["priorita_controllo"]
    return payload


def eventi(esito: Esito, *, attivo: bool) -> list[dict[str, Any]]:
    """Gli eventi che l'esito genera. In ombra sono muti (`leggibile=false`).

    `fonte_ufficiale_non_trovata` e' un tipo **sempre interno** (§13.5): non
    riceve mai un cursore e nessun consumatore lo vede.
    """
    if esito.stato == STATO_TROVATA:
        return [{
            "bando_id": esito.bando_id,
            "tipo": "fonte_ufficiale_verificata",
            "origine": "pipeline",
            "campo": "fonte_ufficiale_url",
            "valore_dopo": {"url": esito.url, "host": esito.host, "tipo": esito.tipo},
            "url_prova": esito.url,
            "citazione": esito.prova or esito.url,
            "confidenza": int(esito.confidenza),
            "metodo": esito.metodo or None,
            "leggibile": bool(attivo),
            "in_aggiornamenti": False,
            "applicato": bool(attivo),
        }]
    return [{
        "bando_id": esito.bando_id,
        "tipo": "fonte_ufficiale_non_trovata",
        "origine": "pipeline",
        "valore_dopo": {
            "stato": esito.stato, "candidato": esito.candidato_prioritario,
            "motivo": esito.motivo,
        },
        "confidenza": int(esito.confidenza),
        "leggibile": False,
        "in_aggiornamenti": False,
        "applicato": False,
    }]


def scrivi_esito(
    esito: Esito,
    *,
    attivo: bool = False,
    dry_run: bool = False,
    tabella: Tabella = TABELLA_SEED,
    strumento: Any | None = None,
    client: Any | None = None,
    gia_trovata: bool = False,
) -> dict[str, Any]:
    """Riversa l'esito su `bando`, `bando_link`, `bando_controllo` ed eventi.

    In ombra (`attivo=False`) le colonne pubbliche **non** si toccano: si
    scrivono solo `bando_controllo` (che nessuno legge) e gli eventi muti, cosi'
    il committente puo' misurare la resa prima di cambiare una riga visibile.
    `gia_trovata`: la fonte era gia' `trovata` prima del giro (vedi
    `payload_controllo`).
    """
    scritture: dict[str, Any] = {
        "bando": False, "link": 0, "link_promosso": False,
        "controllo": False, "eventi": 0,
    }
    if dry_run:
        return {"status": "ok", "dry_run": True, **scritture}

    link_id = None
    righe = righe_link(esito, tabella=tabella)
    if attivo and righe:
        scritture["link"] = db.upsert_bando_link(righe, client=client, strumento=strumento)

    if attivo:
        # Senza `fonte_ufficiale_link_id` una riga `trovata` viola il CHECK
        # della 03: `payload_fonte` degrada da solo, qui basta passargli cio'
        # che il DB ha davvero accettato.
        riga_fonte = _riga_link_di(esito, client=client, strumento=strumento)
        link_id = riga_fonte.get("id") if riga_fonte else None
        if _promuovi_riga_fonte(esito, riga_fonte, strumento=strumento):
            scritture["link_promosso"] = True
        esito_scrittura = db.aggiorna_fonte_ufficiale(
            esito.bando_id, payload_fonte(esito, link_id=link_id), strumento=strumento,
        )
        scritture["bando"] = bool(esito_scrittura.get("scritto"))

    controllo_scritto = db.aggiorna_controllo(
        esito.bando_id, payload_controllo(esito, gia_trovata=gia_trovata),
        client=client, strumento=strumento,
    )
    scritture["controllo"] = bool(controllo_scritto.get("scritto"))
    scritture["eventi"] = sum(
        1 for evento in eventi(esito, attivo=attivo)
        if db.registra_evento(evento, client=client, strumento=strumento)
    )
    return {"status": "ok", "dry_run": False, **scritture}


def _riga_link_di(
    esito: Esito, *, client: Any, strumento: Any,
) -> dict[str, Any] | None:
    """La riga di `bando_link` della fonte, riletta dopo l'upsert."""
    if not esito.url:
        return None
    atteso = impronte.normalizza_url(esito.url)
    for riga in db.select_link_da_verificare(
            bando_id=esito.bando_id, client=client, strumento=strumento):
        if impronte.normalizza_url(str(riga.get("url"))) == atteso:
            return dict(riga)
    return None


def _promuovi_riga_fonte(
    esito: Esito, riga: Mapping[str, Any] | None, *, strumento: Any,
) -> bool:
    """Porta a `pubblicabile` la riga di link che era gia' a DB.

    `upsert_bando_link` usa `ignore_duplicates=True` perche' `url` e'
    immutabile (§16.3.3): una riga che esiste **non viene riscritta**. Ma la
    migrazione 02 ha creato una riga di backfill per ogni `link_bando`
    (`origine='raw'`, `trovato_in_fonte_at` NULL, `pubblicabile=false`), e
    quando la fonte ufficiale e' proprio quell'URL il resolver ne adotta l'id
    senza promuoverla: misurato in produzione su 137 delle 495 fonti
    `trovata`. Il risultato e' una fonte dichiarata trovata che punta a una
    riga che anon non puo' leggere, contro la promessa di §13.4 (ogni riga
    leggibile ha risposto 2xx ed e' stata vista nella fonte).

    Si scrivono solo i campi della promessa, mai `url` ne' `url_normalizzato`
    (il trigger li rifiuta), e solo quando cambiano davvero: il CHECK
    `bando_link_pubblicabile_http_check` pretende che `pubblicabile`,
    `esito_http` 2xx e `trovato_in_fonte_at` nascano insieme.
    """
    if not riga or esito.stato != STATO_TROVATA or not _e_2xx(esito.esito_http):
        return False
    link_id = riga.get("id")
    if link_id is None:
        return False
    tipo = "atto" if esito.e_atto else "pagina_bando"
    payload: dict[str, Any] = {}
    if not riga.get("pubblicabile"):
        payload["pubblicabile"] = True
    if riga.get("esito_http") != esito.esito_http:
        payload["esito_http"] = esito.esito_http
    if not riga.get("trovato_in_fonte_at"):
        payload["trovato_in_fonte_at"] = _adesso()
    if riga.get("tipo") != tipo:
        payload["tipo"] = tipo
    if esito.prova and not riga.get("impronta_pagina"):
        payload["impronta_pagina"] = esito.prova
    if esito.url_prova and not riga.get("url_prova"):
        payload["url_prova"] = esito.url_prova
    if not payload:
        return False
    # `pubblicabile` senza i suoi due presupposti fa fallire il CHECK: se la
    # riga non li ha e questo giro non li porta, si rinuncia alla promozione.
    if payload.get("pubblicabile"):
        if not (payload.get("trovato_in_fonte_at") or riga.get("trovato_in_fonte_at")):
            return False
    payload["ultimo_visto_at"] = _adesso()
    return bool(db.aggiorna_link(link_id, payload, strumento=strumento).get("scritto"))


# --- runner: `python -m app risolvi-fonte` ----------------------------------

LOCK_RESOLVER = "bandi_resolver"
#: Il margine del lucchetto oltre il tempo dei ricontrolli (giro 3, §7): un
#: bando gia' partito finisce anche a tempo scaduto.
MARGINE_LOCK_S = 1800
#: Il TTL quando `.env` non si legge: il default di TEMPO_RICONTROLLI_S piu'
#: il margine.
LOCK_TTL_S = 3600 + MARGINE_LOCK_S


def ttl_lock_resolver() -> int:
    """Il TTL del lucchetto `bandi_resolver`: `TEMPO_RICONTROLLI_S + 1800`."""
    try:
        from .settings import get_settings
        return int(get_settings().tempo_ricontrolli_s) + MARGINE_LOCK_S
    except Exception:
        return LOCK_TTL_S
#: Le tre fonti Obiettivo Europa (449/450/451), escluse dalla whitelist.
FONTI_OE: tuple[int, ...] = (449, 450, 451)


def _modalita_attiva(attivo: bool | None) -> bool:
    """Ombra per difetto; `--ombra` (False esplicito) vince sull'ambiente.

    `None` e' «l'operatore non ha detto niente»: decide `RESOLVER_MODALITA`.
    `False` e' «ha scritto `--ombra`», e allora non si scrive comunque (§5).
    """
    if attivo is not None:
        return bool(attivo)
    try:
        from .settings import get_settings
        return get_settings().resolver_modalita == "attivo"
    except Exception:
        return False


#: Quante righe si chiedono per pagina mentre si cercano quelle da risolvere.
#: Non e' il `--limit` dell'operatore: e' la finestra su cui si scorre.
PAGINA_SELEZIONE_RESOLVER = 500


def _lavorata_oggi(controllo: Mapping[str, Any] | None, oggi: date_cls) -> bool:
    """La riga e' gia' stata guardata OGGI? (`bando_controllo.ultimo_controllo_at`).

    E' il marcatore giusto per lo scorrimento perche' e' l'unico che viene
    scritto **anche in ombra**: `payload_controllo` sta fuori dal ramo
    `if attivo:` di `scrivi_esito`, mentre `fonte_ufficiale_stato` — l'unico
    predicato della query capace di far uscire una riga — in ombra non viene
    scritto mai. Appoggiare l'avanzamento sullo stato pubblico significherebbe
    non avanzare affatto nella modalita' predefinita.
    """
    if not controllo:
        return False
    quando = controllo.get("ultimo_controllo_at")
    if not quando:
        return False
    try:
        return date_cls.fromisoformat(str(quando)[:10]) >= oggi
    except ValueError:
        return False


def _da_risolvere_ora(
    controllo: Mapping[str, Any] | None, oggi: date_cls, forza: bool,
    anche_oggi: bool = False,
) -> bool:
    """Su questa riga c'e' davvero lavoro da fare in questo giro?

    Mai vista (`ultimo_controllo_at` NULL) -> si lavora, sempre: e' il motivo
    per cui la cadenza non puo' essere l'unico criterio (la migrazione 03
    semina `prossimo_controllo_at` su tutte le righe, comprese quelle che il
    resolver non ha mai guardato, e senza questa clausola i `nuovi`
    aspetterebbero fino a due settimane).

    Gia' vista: vale la cadenza di `scaduto()`, nei modi `nuovi` e `backlog`
    (dal giro 3 i `ricontrolli` non hanno cadenza e il `precoce` non lascia
    traccia: hanno selezioni proprie). Prima una riga finita `non_trovata` restava in
    testa alla coda e veniva rilavorata a ogni lancio, con il costo pieno
    della cascata (fino a 4 crediti Firecrawl a bando) per rifare una ricerca
    gia' fallita.

    Con `--forza` la cadenza non c'e' («rifai» e' il suo scopo), ma una riga
    lavorata **oggi** si salta lo stesso: senza, due lanci di fila nella stessa
    giornata ripeterebbero lo stesso blocco di id, che e' il difetto misurato.

    `anche_oggi` toglie anche quella guardia, e serve a un caso solo: **le
    regole sono cambiate sotto le righe**. Succede quando si corregge il
    punteggio o la whitelist e il lavoro fatto poche ore prima e' stato fatto
    con criteri diversi — il 24/09/2026 sono stati 1 923 bandi, risolti prima
    che la regola dei sottodomini fosse attiva. Senza questa via d'uscita
    l'unica alternativa era aspettare il giorno dopo, oppure falsificare
    `ultimo_controllo_at` a mano, che e' peggio. Si chiede a mano e non e' mai
    il default, perche' il suo effetto e' rifare lavoro gia' fatto.
    """
    if not controllo or not controllo.get("ultimo_controllo_at"):
        return True
    if forza:
        return anche_oggi or not _lavorata_oggi(controllo, oggi)
    return scaduto(controllo, oggi, forza=False)


def _da_risolvere(
    *,
    limit: int | None,
    offset: int,
    modo: str,
    solo_oe: bool,
    solo_in_verifica: bool,
    forza: bool,
    oggi: date_cls,
    contatori: Contatori,
    anche_oggi: bool = False,
) -> tuple[list[Mapping[str, Any]], dict[Any, Mapping[str, Any]]]:
    """Le righe su cui c'e' lavoro, scorrendo la selezione a pagine.

    Ritorna `(righe, controlli)`; incrementa `contatori.saltate` per ogni riga
    attraversata e non lavorata. Si ferma quando ha raccolto `limit` righe da
    lavorare davvero, o quando la selezione finisce.

    E' il gemello di `_da_leggere` (`oe-dettaglio`), e nasce dallo stesso
    difetto: `select_bandi_da_risolvere` ordina per `id` e prende i primi N,
    e il `--limit` contava le righe GUARDATE, non quelle da lavorare.
    """
    # `--limit 0` e' un limite, ed e' quello che un operatore mette per non
    # toccare niente (la convenzione e' scritta in `db._pagina`). Il
    # controllo del limite sta DOPO l'append, quindi senza questa uscita un
    # giro da zero righe ne lavorava una — e con `--attivo` era una
    # scrittura vera.
    if limit is not None and int(limit) <= 0:
        return [], {}
    raccolte: list[Mapping[str, Any]] = []
    controlli: dict[Any, Mapping[str, Any]] = {}
    cursore = max(0, int(offset or 0))
    while True:
        blocco = db.select_bandi_da_risolvere(
            limit=PAGINA_SELEZIONE_RESOLVER, offset=cursore, modo=modo,
            solo_oe=solo_oe, solo_in_verifica=solo_in_verifica,
            forza=forza, fonti_oe=FONTI_OE,
        )
        if not blocco:
            break
        cursore += len(blocco)
        pagina = db.select_controlli([b.get("id") for b in blocco])
        controlli.update(pagina)
        for bando in blocco:
            if not _da_risolvere_ora(
                    pagina.get(bando.get("id")), oggi, forza, anche_oggi):
                contatori.saltate += 1
                continue
            raccolte.append(bando)
            if limit is not None and len(raccolte) >= limit:
                return raccolte, controlli
        if len(blocco) < PAGINA_SELEZIONE_RESOLVER:
            break
    return raccolte, controlli


#: Fino a quanti bandi i ricontrolli lavorano insieme (giro 3, §7). La cortesia
#: verso gli enti non dipende da questo numero: la garantiscono il freno per
#: host condiviso (`http._wait_for_host`, 1 s fra due richieste) e il lucchetto
#: per host del resolver (mai due richieste insieme allo stesso host).
PARALLELO_RICONTROLLI = 5

#: Lo step di `pipeline_run` per modo: la chiave del giro (contratto
#: `bandi-giro-3` §2 e §4). `resolver_precoce` e `resolver` sono catena
#: d'ingresso e non si fermano per nessun tetto; `ricontrolli` e' manutenzione.
STEP_PER_MODO: dict[str, str] = {
    "precoce": "resolver_precoce", "nuovi": "resolver", "backlog": "resolver",
    "ricontrolli": "ricontrolli",
}

#: Il tetto di tempo per modo (§3): il campo di `Settings` e il suo default.
#: I `nuovi` non ne hanno uno (§7: «come oggi»).
_TEMPO_PER_MODO: dict[str, tuple[str, float]] = {
    "precoce": ("tempo_precoce_s", 600.0),
    "ricontrolli": ("tempo_ricontrolli_s", 3600.0),
}


def tetto_tempo_s(modo: str) -> float | None:
    """I secondi che il modo puo' lavorare in un giro, o None (nessun tetto)."""
    voce = _TEMPO_PER_MODO.get(modo)
    if voce is None:
        return None
    campo, predefinito = voce
    try:
        from .settings import get_settings
        return float(getattr(get_settings(), campo, predefinito))
    except Exception:
        return predefinito


def _scorri_selezione(
    *, modo: str, offset: int, solo_oe: bool, solo_in_verifica: bool, forza: bool,
) -> list[Mapping[str, Any]]:
    """Tutta la selezione di un modo, a pagine (giro 3: niente lotti)."""
    righe: list[Mapping[str, Any]] = []
    cursore = max(0, int(offset or 0))
    while True:
        blocco = db.select_bandi_da_risolvere(
            limit=PAGINA_SELEZIONE_RESOLVER, offset=cursore, modo=modo,
            solo_oe=solo_oe, solo_in_verifica=solo_in_verifica,
            forza=forza, fonti_oe=FONTI_OE,
        )
        righe.extend(blocco)
        cursore += len(blocco)
        if len(blocco) < PAGINA_SELEZIONE_RESOLVER:
            return righe


def _da_risolvere_precoce(
    *, limit: int | None, offset: int, solo_oe: bool, forza: bool, contatori: Contatori,
) -> tuple[list[Mapping[str, Any]], dict[Any, Mapping[str, Any]]]:
    """Le righe del resolver precoce (giro 3, §7): `scraped` e `processed`
    senza fonte, tolti i `processed` chiusi o revocati (l'enrich non li prende
    mai: 491 righe morte misurate il 01/10) e cio' che `_auto_reject`
    scarterebbe al preprocess. Nessuna cadenza: chi non trova la fonte non
    lascia traccia, e lo riprende la passata `nuovi`."""
    if limit is not None and int(limit) <= 0:
        return [], {}
    scelte: list[Mapping[str, Any]] = []
    for bando in _scorri_selezione(modo="precoce", offset=offset, solo_oe=solo_oe,
                                   solo_in_verifica=False, forza=forza):
        if (bando.get("stato_processing") == "processed"
                and bando.get("stato_bando") in db.STATI_FUORI_RICONTROLLI):
            contatori.esclusi_chiusi += 1
            continue
        if _auto_reject(dict(bando)) is not None:
            contatori.esclusi_auto_reject += 1
            continue
        scelte.append(bando)
        if limit is not None and len(scelte) >= int(limit):
            break
    controlli = db.select_controlli([b.get("id") for b in scelte]) if scelte else {}
    return scelte, controlli


def _chiave_rotazione(bando: Mapping[str, Any], controllo: Mapping[str, Any] | None) -> tuple:
    """Mai controllato per primo, poi dal controllo piu' vecchio, poi per id.

    Gli istanti di PostgREST sono tutti in UTC con lo stesso formato: l'ordine
    del testo e' quello del tempo (anche con frazioni di lunghezza diversa,
    perche' `+` viene prima di `.`).
    """
    ultimo = (controllo or {}).get("ultimo_controllo_at")
    testo = str(ultimo).replace("Z", "+00:00") if ultimo else ""
    identificativo = bando.get("id")
    try:
        numero = int(identificativo)
    except (TypeError, ValueError):
        numero = 0
    return (bool(testo), testo, numero, str(identificativo))


def _da_risolvere_ricontrolli(
    *, limit: int | None, offset: int, solo_oe: bool, solo_in_verifica: bool,
) -> tuple[list[Mapping[str, Any]], dict[Any, Mapping[str, Any]]]:
    """I ricontrolli del giro 3 (§7): TUTTE le fonti `in_verifica` e
    `non_trovata` dei pubblicati e degli `enriched` non chiusi ne' revocati,
    senza guardare `prossimo_controllo_at`, in ordine di ultimo controllo
    crescente (rotazione: chi resta fuori per tempo parte per primo al giro
    dopo). `limit` resta solo per chi lancia a mano."""
    if limit is not None and int(limit) <= 0:
        return [], {}
    righe = _scorri_selezione(modo="ricontrolli", offset=offset, solo_oe=solo_oe,
                              solo_in_verifica=solo_in_verifica, forza=False)
    controlli = db.select_controlli([b.get("id") for b in righe]) if righe else {}
    ordinate = sorted(righe, key=lambda b: _chiave_rotazione(b, controlli.get(b.get("id"))))
    if limit is not None:
        ordinate = ordinate[: int(limit)]
    return ordinate, controlli


async def _lavora_tutti(
    bandi: Sequence[Mapping[str, Any]],
    lavora: Callable[[Mapping[str, Any]], Awaitable[None]],
    *,
    parallelo: int,
    tempo_s: float | None,
    avvio: float,
    ferma: Callable[[], bool],
) -> tuple[int, str | None]:
    """Lavora i bandi, fino a `parallelo` insieme, finche' c'e' tempo.

    Ritorna `(avviati, motivo)`: `motivo` e' `tempo` se il tetto di tempo ha
    lasciato fuori qualcuno, `tetto` se si e' fermato un lotto di backfill,
    None se tutti sono partiti. Un bando gia' partito finisce comunque (al
    massimo `TETTO_TEMPO_BANDO_S`). Con `parallelo=1` e' il ciclo di sempre:
    un bando per volta, e il controllo prima di ognuno.
    """
    semaforo = asyncio.Semaphore(max(1, int(parallelo)))
    in_corso: set[asyncio.Future[Any]] = set()
    avviati = 0
    motivo: str | None = None

    async def _uno(bando: Mapping[str, Any]) -> None:
        try:
            await lavora(bando)
        finally:
            semaforo.release()

    for bando in bandi:
        await semaforo.acquire()
        if ferma():
            semaforo.release()
            motivo = "tetto"
            break
        if tempo_s is not None and time.monotonic() - avvio >= tempo_s:
            semaforo.release()
            motivo = "tempo"
            break
        avviati += 1
        compito = asyncio.ensure_future(_uno(bando))
        in_corso.add(compito)
        compito.add_done_callback(in_corso.discard)
    if in_corso:
        await asyncio.gather(*in_corso)
    return avviati, motivo


def _copertura_del_giro(
    candidati: int, avviati: int, motivo_stop: str | None, contatori: Contatori,
    *, selezione_fallita: bool = False,
) -> dict[str, Any]:
    """La copertura del resolver (§1). Un bando rinviato per tempo (oltre
    `TETTO_TEMPO_BANDO_S`) o per DNS e' partito ma non ha un verdetto: e' fra i
    rimasti, non fra i fatti (P2 della revisione #144), cosi' `salute` vede un
    host morto da giorni invece di «tutto fatto»."""
    rinviati = contatori.rinviati_tempo + contatori.rinviati_dns
    fatti = max(0, avviati - rinviati)
    if selezione_fallita:
        motivo: str | None = "errore"
    elif motivo_stop == "tempo" or contatori.rinviati_tempo:
        motivo = "tempo"
    elif contatori.rinviati_dns:
        motivo = "errore"
    else:
        motivo = _motivo_rimasti(motivo_stop, contatori)
    return telemetria.copertura(candidati, fatti, motivo)


def _motivo_rimasti(motivo: str | None, contatori: Contatori) -> str | None:
    """Il motivo di §1 per chi e' rimasto fuori."""
    if motivo == "tempo":
        return "tempo"
    if motivo == "tetto":
        return "crediti" if "crediti" in (contatori.motivo or "") else "spesa"
    return None


async def run(
    dry_run: bool = False,
    limit: int | None = None,
    attivo: bool | None = None,
    *,
    giro: str | None = None,
    modo: str = "nuovi",
    solo_oe: bool = False,
    solo_in_verifica: bool = False,
    bando_id: Any = None,
    forza: bool = False,
    anche_oggi: bool = False,
    offset: int = 0,
    lotto: str | None = None,
    ambiente: Ambiente | None = None,
    tempo_s: float | None = None,
    parallelo: int | None = None,
) -> dict[str, Any]:
    """Step 5 della pipeline. **Non solleva e non chiama mai `sys.exit`** (A15).

    Il lock e i tetti sono dati, non eccezioni: `saltato_per_lock` e
    `interrotto_per_tetto` tornano nel dizionario e `app/__main__.py` li
    traduce in exit code 3 e 4.

    Tre modi nel giro (contratto `bandi-giro-3` §2 e §7):
      - `precoce` (passo 4): le righe appena entrate, con la scadenza
        provvisoria, senza ricerca ne' arbitro; solo un `trovata` si scrive,
        il resto non lascia traccia. Tempo `TEMPO_PRECOCE_S`;
      - `nuovi` (passo 7): come prima del giro 3, con la sua cadenza;
      - `ricontrolli` (passo 8): tutte le fonti da ritrovare, senza cadenza
        ne' `limit`, in ordine di ultimo controllo, fino a
        `PARALLELO_RICONTROLLI` insieme. Tempo `TEMPO_RICONTROLLI_S`.
    `tempo_s` e `parallelo` sostituiscono quelli del modo (test, CLI).

    `--limit` conta le righe da **lavorare**, non quelle guardate. `--offset N`
    fa partire lo scorrimento oltre le prime N righe della selezione.
    """
    avvio = time.monotonic()
    if modo not in db.MODI_RESOLVER:
        logger.error("[resolver] modo sconosciuto: {!r}", modo)
        return {"status": "errore", "error": f"modo sconosciuto: {modo}", "modo": modo}
    attivo = _modalita_attiva(attivo)
    step = f"backfill:{lotto}" if lotto else STEP_PER_MODO[modo]
    run_telemetria = telemetria.PipelineRun(step=step, giro=giro)
    proprietario = f"resolver@{os.getpid()}"
    lock = blocco.acquisisci(LOCK_RESOLVER, proprietario, ttl_lock_resolver())
    if not lock.proseguire:
        return blocco.esito_saltato(lock)

    ambiente = ambiente or _ambiente_predefinito(step=step, attivo=attivo)
    if modo == "precoce":
        # §7: niente ricerca a pagamento ne' arbitro, e la scadenza e' quella
        # provvisoria della riga, che conferma e non smentisce.
        ambiente.da_segnale = True
        ambiente.arbitro = None
        ambiente.ricerca = None
        ambiente.scadenza_provvisoria = True
    if tempo_s is None:
        tempo_s = tetto_tempo_s(modo)
    if parallelo is None:
        parallelo = PARALLELO_RICONTROLLI if modo == "ricontrolli" else 1
    contatori = ambiente.contatori
    bandi: list[Mapping[str, Any]] = []
    controlli: Mapping[Any, Mapping[str, Any]] = {}
    selezione_fallita = False
    try:
        if bando_id is not None:
            # `--id X` e' una riga sola, chiesta a mano: nessuno scorrimento e
            # nessuna cadenza. Saltarla perche' e' stata guardata stamattina
            # renderebbe il comando inutile proprio quando serve.
            bandi = db.select_bandi_da_risolvere(
                limit=limit, modo=modo, solo_oe=solo_oe,
                solo_in_verifica=solo_in_verifica, bando_id=bando_id,
                forza=forza, fonti_oe=FONTI_OE,
            )
            controlli = db.select_controlli([b.get("id") for b in bandi]) if bandi else {}
        elif modo == "precoce":
            bandi, controlli = _da_risolvere_precoce(
                limit=limit, offset=offset, solo_oe=solo_oe, forza=forza, contatori=contatori)
        elif modo == "ricontrolli":
            bandi, controlli = _da_risolvere_ricontrolli(
                limit=limit, offset=offset, solo_oe=solo_oe,
                solo_in_verifica=solo_in_verifica)
        else:
            # La selezione ordina per `id` e prende i primi N: senza scorrere,
            # ogni lancio ripeterebbe le stesse righe. Il filtro di data sta
            # dentro lo scorrimento: e' cio' che fa avanzare la selezione
            # anche in ombra, dove `fonte_ufficiale_stato` non viene scritto.
            bandi, controlli = _da_risolvere(
                limit=limit, offset=offset, modo=modo, solo_oe=solo_oe,
                solo_in_verifica=solo_in_verifica, forza=forza,
                oggi=ambiente.oggi, contatori=contatori, anche_oggi=anche_oggi,
            )
        if bandi:
            ambiente.pubblicati = ambiente.pubblicati or db.select_pubblicati_per_gemelli()
            # Una lettura sola di `bando_link` per il lotto, non una per bando:
            # serve a due cose insieme, e la seconda e' quella che tiene in
            # piedi la catena.
            righe_link = db.select_link_da_verificare(
                bando_ids=[b.get("id") for b in bandi])
            # Regola A29: la scheda OE si riscarica solo alla scoperta o su un
            # cambio dichiarato. Chi l'ha gia' letta si riconosce dalla prova
            # in `bando_link`.
            ambiente.schede_lette = ambiente.schede_lette or schede_gia_lette(
                [b.get("id") for b in bandi], righe=righe_link,
            )
            # E i link di quelle schede sono i candidati del passo 1. Senza
            # questa riga il lotto `oe-dettaglio` riempiva una tabella che
            # nessuno rileggeva: la regola A29 vieta di riscaricare la scheda,
            # quindi `candidati_da_scheda` tornava vuoto, il `link_bando` di
            # quei bandi e' l'URL dell'aggregatore e veniva scartato, e 1 724
            # bandi scendevano fino alla ricerca a pagamento.
            if not ambiente.link_registrati:
                per_bando: dict[Any, list[Mapping[str, Any]]] = {}
                for riga in righe_link:
                    per_bando.setdefault(riga.get("bando_id"), []).append(riga)
                ambiente.link_registrati = per_bando
    except Exception as e:                               # pragma: no cover - difesa
        contatori.errori += 1
        selezione_fallita = True
        logger.exception("[resolver] selezione dei candidati fallita: {}", e)
        bandi = []

    if not bandi:
        logger.info(
            "[resolver] nessun bando candidato (modo={}, saltate={}): la selezione "
            "e' stata attraversata ma nessuna riga aveva lavoro da fare",
            modo, contatori.saltate,
        )

    async def _lavora(bando: Mapping[str, Any]) -> None:
        # Un bando per volta, e ogni bando protetto: una pagina malformata
        # alla riga 500 di un backfill da 1 702 righe non puo' buttare via le
        # altre 1 200. `risolvi()` protegge i suoi passi, ma le funzioni pure a
        # valle (estrazione delle date, numero di atto) girano su testo
        # arbitrario e `scrivi_esito` puo' sollevare `PayloadBandoVietato`.
        try:
            riga_controllo = controlli.get(bando.get("id")) or {}
            arricchito = dict(bando)
            arricchito.setdefault(
                "tentativi_resolver", riga_controllo.get("tentativi_resolver") or 0)
            try:
                esito = await asyncio.wait_for(
                    risolvi(arricchito, ambiente), timeout=ambiente.tetto_tempo_bando_s)
            except asyncio.TimeoutError:
                # Il tetto morde al primo `await`: la verifica degli allegati
                # e' sincrona, e una in corso finisce prima.
                contatori.rinviati_tempo += 1
                _rinvia(bando, motivo=f"oltre {ambiente.tetto_tempo_bando_s:g} s", avviso=True)
                return
            morti = _host_irraggiungibili(esito)
            contatori.host_morti.update(morti)
            if morti and esito.stato != STATO_TROVATA:
                # Un candidato non letto per un DNS rotto non dice niente del
                # bando: nessun verdetto, nessun tentativo, stato della fonte
                # invariato. Se un altro candidato e' `trovata`, il verdetto
                # c'e' e si scrive come sempre.
                contatori.rinviati_dns += 1
                _togli_verdetto(contatori, esito.stato)
                _rinvia(bando, motivo=f"host irraggiungibile (DNS): {', '.join(sorted(morti))}")
                return
            if contatori.interrotto_per_tetto:
                # Cascata monca (solo un lotto di backfill si ferma): scrivere
                # un `non_trovata` ricavato da mezzo giro condannerebbe il
                # bando per colpa di un tetto, non di una verifica.
                logger.warning(
                    "[resolver] bando {} lasciato intatto: {}", bando.get("id"), contatori.motivo,
                )
                return
            if modo == "precoce" and esito.stato != STATO_TROVATA:
                # §7: nessuna traccia (niente verdetto, niente evento, niente
                # tentativo): la passata `nuovi` lo riprende con la scadenza
                # vera del preprocess.
                _togli_verdetto(contatori, esito.stato)
                contatori.senza_traccia += 1
                return
            scrivi_esito(
                esito, attivo=attivo, dry_run=dry_run, tabella=ambiente.tabella,
                gia_trovata=str(bando.get("fonte_ufficiale_stato") or "") == STATO_TROVATA,
            )
        except Exception as e:
            contatori.errori += 1
            logger.exception("[resolver] bando {} saltato per un errore: {}", bando.get("id"), e)

    avviati = 0
    motivo_stop: str | None = None
    try:
        avviati, motivo_stop = await _lavora_tutti(
            bandi, _lavora, parallelo=parallelo, tempo_s=tempo_s, avvio=avvio,
            ferma=lambda: contatori.interrotto_per_tetto or ambiente.deve_fermarsi(),
        )
        if motivo_stop == "tetto":
            logger.warning("[resolver] {}", contatori.motivo)
        elif motivo_stop == "tempo":
            logger.info("[resolver] tempo finito ({:g} s): {} bandi al giro dopo",
                        tempo_s, len(bandi) - avviati)
    finally:
        if ambiente.chiudi_verifica is not None:
            ambiente.chiudi_verifica()
        blocco.rilascia(lock)

    if contatori.host_morti:
        logger.warning(
            "[resolver] host irraggiungibili (DNS) in questo giro: {} (bandi rinviati: {})",
            ", ".join(sorted(contatori.host_morti)), contatori.rinviati_dns)
    copertura = _copertura_del_giro(len(bandi), avviati, motivo_stop, contatori,
                                    selezione_fallita=selezione_fallita)
    durata = time.monotonic() - avvio
    risultato: dict[str, Any] = {
        "status": "ok",
        **contatori.come_dizionario(),
        "dry_run": dry_run,
        "attivo": attivo,
        "modo": modo,
        "offset": offset,
        "elapsed_s": round(durata, 1),
        "copertura": copertura,
    }
    if contatori.interrotto_per_tetto:
        risultato["interrotto_per_tetto"] = True
        risultato["motivo"] = contatori.motivo
    if contatori.motivo_spesa:
        risultato["motivo_spesa"] = contatori.motivo_spesa
    ambiente.assorbi_spesa()
    risultato["crediti"] = ambiente.spesa.crediti_firecrawl
    risultato["fetch"] = ambiente.spesa.fetch
    _registra(run_telemetria, durata, contatori, ambiente.spesa, copertura=copertura)
    logger.info("[resolver] === DONE | {} ===", risultato)
    return risultato


def _host_irraggiungibili(esito: Esito) -> set[str]:
    """Gli host dei candidati che non hanno risolto il DNS, scritti come li
    scrive `scarico.py` (minuscolo, senza porta ne' `www.`)."""
    from .scarico import host_di
    return {
        host_di(candidato.url) or candidato.url
        for candidato, _punteggio in esito.valutati
        if candidato.pagina is not None and candidato.pagina.host_irraggiungibile
    }


def _togli_verdetto(contatori: Contatori, stato: str) -> None:
    """`_componi_esito` ha gia' contato il verdetto: un bando rinviato non ne
    ha uno, e i contatori dicono cio' che e' stato scritto (RIPRESA §5.4)."""
    nome = {STATO_TROVATA: "trovate", STATO_IN_VERIFICA: "in_verifica"}.get(stato, "non_trovate")
    setattr(contatori, nome, max(0, getattr(contatori, nome) - 1))


def _rinvia(bando: Mapping[str, Any], *, motivo: str, avviso: bool = False) -> None:
    """Il bando passa al giro dopo: niente verdetto, niente tentativo, stato
    della fonte invariato (contratto di ottobre 2026, §5).

    Dal giro 3 (§7) non si scrive piu' niente, nemmeno nei ricontrolli: la
    loro selezione non guarda `prossimo_controllo_at` e li prende tutti a ogni
    giro, in ordine di ultimo controllo, quindi un host morto non blocca gli
    altri.

    `avviso=True` (il rinvio per tempo) scrive un WARNING con l'id: un bando
    lento ma sano verrebbe rinviato a ogni giro, e non lascia traccia a DB
    (revisione #23). Il rinvio per DNS resta a INFO: il giro ha gia' la sua
    riga WARNING con l'elenco degli host.
    """
    scrivi = logger.warning if avviso else logger.info
    scrivi("[resolver] bando {} rinviato al giro dopo: {}", bando.get("id"), motivo)


def _registra(
    run_telemetria: Any,
    durata: float,
    contatori: Contatori,
    spesa: bilancio.Contatori | None = None,
    *,
    copertura: Mapping[str, Any] | None = None,
) -> None:
    """Riga in `pipeline_run`. Non solleva: la telemetria non fa fallire un giro.

    I crediti e i dollari arrivano da `spesa`, non da zero: il `gia_oggi` dei
    tetti giornalieri legge proprio queste righe, e registrare zero renderebbe
    il tetto inefficace il giorno in cui verra' collegato.
    """
    spesa = spesa if spesa is not None else bilancio.Contatori()
    try:
        concluso = run_telemetria.concludi(
            durata_s=durata,
            esito=telemetria.esito_da_contatori(
                errori=contatori.errori, interrotto_per_tetto=contatori.interrotto_per_tetto,
            ),
            contatori={**contatori.come_dizionario(),
                       **({"copertura": dict(copertura)} if copertura is not None else {})},
            crediti=spesa.crediti_firecrawl,
            costo_usd=spesa.usd,
            interrotto_per_tetto=contatori.interrotto_per_tetto,
            motivo=contatori.motivo,
        )
        logger.info("[resolver] riepilogo {}", telemetria.riepilogo(concluso))
        telemetria.scrivi_pipeline_run(concluso)
    except Exception as e:
        logger.warning("[resolver] telemetria non registrata: {}", e)


# --- verifica HTTP sincrona -------------------------------------------------

TIMEOUT_VERIFICA_S = 20.0
#: sha256 dei primi 64 KB (§5): identifica il documento senza scaricarlo tutto.
BYTE_IMPRONTA = 64 * 1024
#: Quanti redirect segue una verifica (§18.6): li segue a mano, per poter
#: guardare ogni salto prima di farlo.
MAX_REDIRECT_VERIFICA = 5


#: L'esito «rifiutato» di `http.classifica_indirizzo` (§18.6).
_RIFIUTATO = "rifiutato"


class IndirizzoNonPubblico(Exception):
    """Un URL (o un suo redirect) risolve a un indirizzo interno (§18.6)."""


class VerificaHttp:
    """Verifica sincrona di un URL: HEAD, con ripiego GET su 405/501.

    La regola e' quella di `reachability._check_one`, ma l'esito che §5 chiede
    e' piu' ricco (content-type, ETag, Last-Modified, sha256 dei primi 64 KB) e
    i due chiamanti — `allegati.estrai` e `run_link_verifica` — sono sincroni,
    mentre `_check_one` e' una coroutine che pretende un `httpx.AsyncClient`.
    Un client solo per tutto il giro: una connessione riusata invece di un
    handshake TLS per allegato.

    Restituisce il dizionario che `allegati.Verifica.da()` sa leggere, o `None`
    se la richiesta non e' mai arrivata a destinazione.
    """

    def __init__(
        self,
        user_agent: str = "",
        timeout_s: float = TIMEOUT_VERIFICA_S,
        *,
        guardia: Callable[[str], bool] | None = None,
        transport: Any = None,
    ) -> None:
        intestazioni = {"User-Agent": user_agent} if user_agent else {}
        # Chokepoint di §5: qui si compongono le intestazioni per httpx, e qui
        # l'assert dice che nessun cookie di sessione OE puo' uscire.
        oe_scheda.assicura_niente_cookie("httpx", intestazioni)
        self._intestazioni = intestazioni
        self._timeout = timeout_s
        self._client: Any = None
        # §18.6: gli URL da verificare vengono da pagine e da un modello, non
        # da fonti note. Prima di ogni richiesta e di ogni redirect si guarda
        # l'host risolto (`http.indirizzo_pubblico`); `guardia` e `transport`
        # sono i punti di iniezione dei test (nessuna rete, nessun DNS).
        if guardia is None:
            from .http import indirizzo_pubblico as guardia
        self._guardia = guardia
        self._transport = transport
        #: Quante verifiche la guardia ha rifiutato (indirizzi interni).
        self.rifiutati = 0

    def _cliente(self) -> Any:
        if self._client is None:
            import httpx
            # Niente `follow_redirects`: i redirect li segue `_richiesta`, uno
            # per uno, dopo la guardia.
            self._client = httpx.Client(
                timeout=self._timeout, headers=self._intestazioni, follow_redirects=False,
                transport=self._transport,
            )
        return self._client

    def _richiesta(self, metodo: str, url: str, *, stream: bool = False) -> Any:
        """La risposta finale di `metodo url`, seguendo i redirect a mano.

        Solleva `IndirizzoNonPubblico` se l'URL o un salto risolve a un
        indirizzo interno: la richiesta non parte. Oltre `MAX_REDIRECT_VERIFICA`
        salti solleva un errore qualunque (verifica non arrivata).
        """
        cliente = self._cliente()
        attuale = str(url)
        for _ in range(MAX_REDIRECT_VERIFICA + 1):
            if not self._guardia(attuale):
                self.rifiutati += 1
                raise IndirizzoNonPubblico(attuale)
            risposta = cliente.send(cliente.build_request(metodo, attuale), stream=stream)
            posizione = risposta.headers.get("location") if risposta.is_redirect else None
            if not posizione:
                return risposta
            risposta.close()
            attuale = urljoin(attuale, posizione)
        raise RuntimeError(f"oltre {MAX_REDIRECT_VERIFICA} redirect")

    def __call__(self, url: str) -> dict[str, Any] | None:
        risposta = self._testa(url)
        if risposta is None:
            return None
        stato, intestazioni, primi_byte = risposta
        return {
            "esito_http": stato,
            "content_type": intestazioni.get("content-type"),
            "sha256": hashlib.sha256(primi_byte).hexdigest() if primi_byte else None,
            "etag": intestazioni.get("etag"),
            "last_modified": intestazioni.get("last-modified"),
        }

    def _testa(self, url: str) -> tuple[int, Mapping[str, str], bytes] | None:
        """(stato, intestazioni, primi 64 KB). HEAD, poi GET su 405/501.

        None se la richiesta non e' arrivata, o se la guardia l'ha rifiutata
        (§18.6): un indirizzo interno non si chiede ne' in HEAD ne' in GET.
        """
        try:
            risposta = self._richiesta("HEAD", url)
            stato = int(getattr(risposta, "status_code", 0) or 0)
            if stato not in (405, 501):
                return stato, dict(risposta.headers), b""
        except IndirizzoNonPubblico as e:
            logger.warning("[resolver] verifica rifiutata, indirizzo non pubblico: {}", e)
            return None
        except Exception as e:
            logger.debug("[resolver] HEAD {} fallita: {}", url, e)
        try:
            # In streaming: l'impronta di §5 sono i primi 64 KB, e un allegato
            # puo' pesare decine di MB. Scaricarlo tutto per hasharne una
            # frazione sarebbe banda spesa per niente.
            risposta = self._richiesta("GET", url, stream=True)
            try:
                primi = b""
                for pezzo in risposta.iter_bytes(BYTE_IMPRONTA):
                    primi = pezzo
                    break
                return (
                    int(getattr(risposta, "status_code", 0) or 0),
                    dict(risposta.headers),
                    primi,
                )
            finally:
                risposta.close()
        except IndirizzoNonPubblico as e:
            logger.warning("[resolver] verifica rifiutata, indirizzo non pubblico: {}", e)
            return None
        except Exception as e:
            logger.debug("[resolver] GET {} fallita: {}", url, e)
            return None

    def chiudi(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:                            # pragma: no cover - difesa
                pass
            self._client = None


#: Le schede OE lette oggi, per bando (giro 3, §7): `{bando_id: (giorno di
#: Roma, Scheda | None)}`. Una scheda si legge al massimo una volta al giorno
#: anche con quattro giri e tre passate del resolver per giro (precoce, nuovi,
#: ricontrolli): le passate successive riusano la stessa Scheda, e quindi gli
#: stessi candidati. Vive nel processo: un riavvio la svuota.
_SCHEDE_OE_DEL_GIORNO: dict[Any, tuple[date_cls, Any]] = {}


def scheda_oe_del_giorno(bando_id: Any, oggi: date_cls) -> tuple[bool, Any]:
    """(trovata, scheda) dalla cache del giorno; dimentica i giorni passati."""
    for chiave in [k for k, (giorno, _s) in _SCHEDE_OE_DEL_GIORNO.items() if giorno != oggi]:
        del _SCHEDE_OE_DEL_GIORNO[chiave]
    voce = _SCHEDE_OE_DEL_GIORNO.get(bando_id)
    if voce is None:
        return False, None
    return True, voce[1]


def ricorda_scheda_oe(bando_id: Any, oggi: date_cls, scheda: Any) -> bool:
    """Mette in cache la scheda **letta** oggi. Vero se l'ha ricordata.

    §18.7: un `None` non si ricorda mai. Oggi `oe_scheda` restituisce None per
    403/429 (lotto fermo), tetto, rete, 5xx e anche 404, senza dire quale:
    ricordarlo voleva dire lasciare senza scheda, fino all'indomani, tutti i
    bandi OE rimasti dopo un 429. Il passaggio successivo riprova; il freno
    del portale lo fanno `fermato` e il tetto dello scarico autenticato.
    """
    if scheda is None:
        return False
    _SCHEDE_OE_DEL_GIORNO[bando_id] = (oggi, scheda)
    return True


def lucchetto_host(lucchetti: dict[str, asyncio.Lock], url: str) -> asyncio.Lock:
    """Il lucchetto dell'host di `url` (giro 3, §7): con i ricontrolli in
    parallelo, mai due richieste insieme allo stesso host. I lucchetti vivono
    in un dizionario per `Ambiente`, cioe' per giro: un `asyncio.Lock` resta
    legato all'event loop in cui e' nato, e il sender ne apre uno per giro."""
    from .scarico import host_di
    return lucchetti.setdefault(host_di(url) or url, asyncio.Lock())


def _ambiente_predefinito(*, step: str, attivo: bool) -> Ambiente:
    """L'ambiente di produzione: scarico reale, whitelist dal DB, tetti da `.env`.

    Qui vengono collegate le due cose senza cui il resolver girerebbe a vuoto:
    lo **scarico delle schede OE** (il passo che §5 accredita di ≈1 360
    `trovata` su ≈1 790) e la **verifica degli allegati** (senza la quale il
    passo 5 non produce mai una riga). Sonda, ricerca e arbitro restano invece
    assenti finche' il committente non li attiva: senza di loro la cascata si
    ferma ai passi gratuiti, che e' il comportamento giusto in ombra.

    Giro 3 (§7): scarichi e schede passano dal lucchetto del loro host, la
    scheda OE di un bando si legge al massimo una volta al giorno, e la
    manutenzione (non l'ingresso ne' i lotti) conosce il consumo del giorno e
    del mese (§4).
    """
    from . import scarico as scarico_mod
    from .settings import get_settings

    impostazioni = get_settings()
    tabella = _tabella_corrente()
    schede = oe_scheda.scarico_predefinito(impostazioni, tabella=tabella)
    verifica = VerificaHttp(user_agent=getattr(impostazioni, "http_user_agent", ""))
    lucchetti: dict[str, asyncio.Lock] = {}

    async def scarica(url: str) -> Pagina:
        async with lucchetto_host(lucchetti, url):
            risposta = await scarico_mod.scarico_corrente().scarica(url, come_fonte=True)
        return pagina_da_risposta(risposta)

    async def verifica_cortese(url: str) -> Any:
        # Stesso lucchetto per host degli scarichi e stesso freno di 1 s: con
        # cinque bandi in parallelo una HEAD non parte mai mentre un altro
        # bando ha una GET in volo sullo stesso host (P2 della revisione #144).
        from . import http as http_mod
        async with lucchetto_host(lucchetti, url):
            await http_mod._wait_for_host(urlsplit(url).netloc)
            return await asyncio.to_thread(verifica, url)

    ambiente = Ambiente(
        tabella=tabella,
        scarica=scarica,
        verifica_allegato=verifica,
        verifica_cortese=verifica_cortese,
        spesa_scarico=lambda: scarico_mod.scarico_corrente().contatori,
        tetti=bilancio.tetti_da_impostazioni(impostazioni),
        step=step,
        attivo=attivo,
    )
    # §19.1: la passata conta solo il proprio delta, non il giro fin qui.
    ambiente.parti_da_qui()
    if not bilancio.e_ingresso(step) and not bilancio.e_backfill(step):
        try:
            consumo = db.consumo_oggi()
        except Exception as e:                           # pragma: no cover - difesa
            logger.warning("[resolver] consumo di oggi non leggibile: {}", e)
            consumo = None
        if consumo is None:
            # §18.5: un consumo ignoto non e' «niente speso».
            ambiente.consumo_illeggibile = True
            logger.warning("[resolver] consumo di oggi illeggibile: {} senza passi a pagamento",
                           step)
        else:
            ambiente.gia_oggi = consumo

    async def scheda_oe(bando: Mapping[str, Any]) -> oe_scheda.Scheda | None:
        """La scheda OE del bando, quando la regola A29 la autorizza, e al
        massimo una volta al giorno."""
        url = str(bando.get("link_bando") or "")
        if schede is None or not oe_scheda.e_host_oe(url):
            return None
        oggi = oggi_roma()
        in_cache, gia_letta = scheda_oe_del_giorno(bando.get("id"), oggi)
        if in_cache:
            return gia_letta
        grezzo = bando.get("raw_data") if isinstance(bando.get("raw_data"), Mapping) else {}
        letta = bando.get("id") in ambiente.schede_lette
        riscarica, _motivo = oe_scheda.deve_riscaricare(
            prima=grezzo if letta else None, dopo=grezzo,
        )
        if not riscarica:
            return None
        async with lucchetto_host(lucchetti, url):
            scheda = await schede.scheda(url)
        # Solo le schede lette (§18.7): un None (429, tetto, rete, 5xx) si
        # riprova alla passata dopo.
        ricorda_scheda_oe(bando.get("id"), oggi, scheda)
        return scheda

    ambiente.scheda_oe = scheda_oe
    ambiente.chiudi_verifica = verifica.chiudi
    return ambiente


#: Quanto vive in memoria la tabella letta dal DB: un giro la legge una volta
#: sola (contratto `bandi-giro-2` §19.8), e il giro dopo, sei ore piu' tardi, la
#: rilegge. Il sender vive per giorni: senza scadenza un import di IndicePA non
#: entrerebbe mai in un processo gia' avviato.
TTL_TABELLA_S = 45 * 60
_CACHE_TABELLA: dict[str, tuple[float, Tabella]] = {}


def azzera_tabella_corrente() -> None:
    """Dimentica la tabella in memoria: a inizio giro, dopo un import, nei test."""
    _CACHE_TABELLA.clear()


def _tabella_corrente() -> Tabella:
    """La whitelist in memoria: le righe di `dominio_ufficiale` in testa, poi
    gli host di `fonte`, poi il seed compilato.

    Le righe del DB **vincono** (§19.8): una confidenza corretta a mano, una
    riga disattivata o l'import di IndicePA valgono piu' del seed che sta nel
    codice. Fino al 30/09 qui entravano solo `fonte` e seed, e la tabella a DB
    non la leggeva nessuno. Una lettura vuota (tabella assente o errore) non va
    in memoria: il giro dopo riprova.
    """
    adesso = time.monotonic()
    voce = _CACHE_TABELLA.get("tabella")
    if voce is not None and adesso - voce[0] < TTL_TABELLA_S:
        return voce[1]
    from .dominio_ufficiale import costruisci, da_righe_db
    righe_db = db.select_domini_ufficiali()
    tabella = costruisci(da_righe_db(righe_db), fonti=db.select_fonti_per_domini())
    if righe_db:
        _CACHE_TABELLA["tabella"] = (adesso, tabella)
    return tabella


# --- runner: `oe-dettaglio` -------------------------------------------------

def schede_gia_lette(
    bando_ids: Sequence[Any],
    *,
    righe: Sequence[Mapping[str, Any]] | None = None,
) -> frozenset[Any]:
    """Gli id che hanno gia' un `bando_link` con la prova della scheda OE.

    La prova (`impronta_pagina` = `sha256#offset`) e' cio' che distingue «la
    scheda l'ho gia' letta» da «il bando esiste nel listing»: `raw_data` c'e'
    sempre, anche il primo giro.
    """
    elenco = list(righe) if righe is not None else db.select_link_da_verificare(
        bando_ids=[i for i in bando_ids if i is not None],
    )
    return frozenset(
        riga.get("bando_id") for riga in elenco
        if riga.get("impronta_pagina") and riga.get("bando_id") is not None
    )


#: Quante righe si chiedono per pagina mentre si cercano quelle da leggere.
#: Non e' il `--limit` dell'operatore: e' la finestra su cui si scorre.
PAGINA_SELEZIONE_OE = 500


def _da_leggere(
    *,
    limit: int | None,
    offset: int = 0,
    modo: str,
    solo_oe: bool,
    bando_id: Any,
    forza: bool,
    contatori: dict[str, int],
) -> tuple[list[Mapping[str, Any]], frozenset[Any]]:
    """Le righe che hanno bisogno della scheda, scorrendo la selezione.

    Ritorna `(righe, gia_lette)`; incrementa `contatori['saltate']` per ogni
    riga scartata perche' la sua scheda e' gia' stata letta. Si ferma quando ha
    raccolto `limit` righe, quando la selezione finisce, o dopo un numero di
    pagine che non puo' degenerare (la selezione e' al massimo l'intero corpus
    pubblicato).
    """
    # `--limit 0` e' un limite, ed e' quello che un operatore mette per non
    # toccare niente (la convenzione e' scritta in `db._pagina`). Il
    # controllo del limite sta DOPO l'append, quindi senza questa uscita un
    # giro da zero righe ne lavorava una — e con `--attivo` era una
    # scrittura vera.
    if limit is not None and int(limit) <= 0:
        return [], frozenset()
    raccolte: list[Mapping[str, Any]] = []
    lette_viste: set[Any] = set()
    offset = max(0, int(offset or 0))
    while True:
        blocco = db.select_bandi_da_risolvere(
            limit=PAGINA_SELEZIONE_OE, offset=offset, modo=modo, solo_oe=solo_oe,
            bando_id=bando_id, forza=forza, fonti_oe=FONTI_OE,
        )
        if not blocco:
            break
        offset += len(blocco)
        gia = schede_gia_lette([b.get("id") for b in blocco])
        lette_viste |= set(gia)
        for bando in blocco:
            grezzo = bando.get("raw_data") if isinstance(bando.get("raw_data"), Mapping) else {}
            letta = bando.get("id") in gia
            riscarica, _motivo = oe_scheda.deve_riscaricare(
                prima=grezzo if letta else None, dopo=grezzo, forza=forza,
            )
            if not riscarica or not oe_scheda.e_host_oe(str(bando.get("link_bando") or "")):
                contatori["saltate"] += 1
                continue
            raccolte.append(bando)
            if limit is not None and len(raccolte) >= limit:
                return raccolte, frozenset(lette_viste)
        if len(blocco) < PAGINA_SELEZIONE_OE:
            break
    return raccolte, frozenset(lette_viste)


async def run_oe_dettaglio(
    dry_run: bool = False,
    limit: int | None = None,
    attivo: bool | None = None,
    *,
    forza: bool = False,
    solo_oe: bool = True,
    modo: str = "nuovi",
    bando_id: Any = None,
    offset: int = 0,
    scarico: oe_scheda.ScaricoSchede | None = None,
    bandi: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Scarica le schede OE e registra i candidati in `bando_link`.

    La regola unica di ri-scarico (§5, A29) vive in `oe_scheda.deve_riscaricare`
    e viene applicata qui. «Scoperta» significa «nessun link con la prova della
    scheda»: un bando ha sempre un `raw_data` (viene dal listing), quindi
    dedurre la scoperta da quello direbbe «gia' letta» anche la prima volta.
    Senza `--forza` e senza un cambio di `status`/`deadline_label` non si
    riscarica. Il backfill L2 delle 1 702 schede e' una deroga una tantum e si
    chiede con `--backlog --forza`: `--forza` scavalca la regola di ri-scarico,
    `--backlog` cambia la SELEZIONE (i pubblicati senza fonte, non la coda dei
    `enriched`). Senza `--backlog` il comando vede solo i bandi nuovi del giro,
    che in regime sono una manciata: e' il comportamento giusto tutti i giorni
    e quello sbagliato per il lotto.

    Senza uno scarico configurato (credenziali assenti) il comando **non**
    risponde «ok» a vuoto: restituisce `saltato='scarico_non_configurato'`, che
    `app/__main__.py` traduce in un exit code diverso da zero. Un cron che
    scarica zero schede e resta verde e' peggio di un cron che fallisce.

    `--dry-run` non scarica niente: le schede consumano il tetto
    `OE_SCHEDE_GIORNO` e passano da una sessione autenticata che un 403 puo'
    far bloccare. Una prova a vuoto conta cio' che avrebbe scaricato.

    `--offset N` fa partire lo scorrimento oltre le prime N righe della
    selezione. Serve proprio al caso che ha fatto emergere il difetto: con
    `--forza` nessuna riga e' «gia' letta» per definizione, quindi lo
    scorrimento non scarta niente e il lotto ripartirebbe ogni volta dalla
    prima pagina. I blocchi si lanciano a mano: `--offset 0`, `800`, `1600`.
    """
    attivo = _modalita_attiva(attivo)
    if scarico is None:
        scarico = oe_scheda.scarico_predefinito(tabella=_tabella_corrente())
    if scarico is None:
        logger.error(
            "[oe-dettaglio] scarico delle schede non configurato: nessuna scheda letta"
        )
        return {
            "status": "ok", "saltato": "scarico_non_configurato",
            "dry_run": dry_run, "attivo": attivo,
        }

    tabella = _tabella_corrente() if bandi is None else TABELLA_SEED
    contatori = {
        "esaminati": 0, "scaricate": 0, "saltate": 0, "candidati": 0, "link": 0,
        "da_scaricare": 0,
    }
    if bandi is not None:
        righe = list(bandi)
        if limit is not None:
            righe = righe[:limit]
        gia_lette = schede_gia_lette([b.get("id") for b in righe])
    else:
        # La selezione ordina per `id` e prende i primi N: senza scorrere oltre,
        # ogni lancio ripeterebbe le stesse righe. Misurato il 23/09/2026: due
        # giri da 800 di fila, numeri identici (800 esaminati, 1866 link) e 799
        # bandi coperti in tutto. Qui si scorre la selezione a pagine finche'
        # non si sono raccolte `limit` righe che hanno DAVVERO bisogno della
        # scheda; le gia' lette si contano in `saltate` e non consumano il
        # limite. Con `--forza` nessuna riga e' «gia' letta» per definizione:
        # il flag vuol dire «rifai», e allora si riparte dalla prima pagina.
        righe, gia_lette = _da_leggere(
            limit=limit, offset=offset, modo=modo, solo_oe=solo_oe,
            bando_id=bando_id, forza=forza, contatori=contatori,
        )
    for bando in righe:
        contatori["esaminati"] += 1
        grezzo = bando.get("raw_data") if isinstance(bando.get("raw_data"), Mapping) else {}
        letta = bando.get("id") in gia_lette
        riscarica, _motivo = oe_scheda.deve_riscaricare(
            prima=grezzo if letta else None, dopo=grezzo, forza=forza,
        )
        url = str(bando.get("link_bando") or "")
        if not riscarica or not oe_scheda.e_host_oe(url):
            contatori["saltate"] += 1
            continue
        if dry_run:
            contatori["da_scaricare"] += 1
            continue
        scheda = await scarico.scheda(url)
        if scheda is None:
            continue
        contatori["scaricate"] += 1
        candidati = candidati_da_scheda(scheda, tabella=tabella)
        contatori["candidati"] += len(candidati)
        if not attivo:
            continue
        contatori["link"] += db.upsert_bando_link([
            {
                "bando_id": bando.get("id"),
                "url": c.url,
                "tipo": "pagina_bando",
                "origine": "aggregatore",
                "etichetta": c.ancora or None,
                "url_prova": scheda.url,
                # Senza offset la prova non e' verificabile: meglio NULL che
                # una stringa che sembra una prova (`oe_scheda._offset`).
                "impronta_pagina": c.prova or None,
                # Questo href e' stato trovato ADESSO nell'HTML della scheda:
                # e' esattamente cio' che la colonna registra, ed e' quello che
                # il CHECK della 02 pretende da una riga pubblicabile
                # (`NOT pubblicabile OR trovato_in_fonte_at IS NOT NULL`).
                # Senza, `link-verifica` non poteva rendere pubblicabile
                # nemmeno una riga: l'UPDATE veniva rifiutato dal vincolo e
                # `db.controllo.aggiorna` lo inghiottiva con un warning, quindi
                # il comando riferiva «pubblicabili: 847» e scriveva zero.
                "trovato_in_fonte_at": _adesso(),
                # Mai pubblicabile finche' `link-verifica` non conferma il 2xx.
                "pubblicabile": False,
            }
            for c in candidati
        ])
        if scarico.fermato:
            break
    return {"status": "ok", "dry_run": dry_run, "attivo": attivo,
            "offset": offset, **contatori}


# --- runner: `link-verifica` ------------------------------------------------

#: Quante righe di `bando_link` si chiedono per pagina mentre si cerca che
#: cosa verificare. Non e' il `--limit` dell'operatore.
PAGINA_SELEZIONE_LINK = 500

#: `esito_http` scritto quando la richiesta non arriva a destinazione (DNS che
#: non risolve, TLS rifiutato, timeout, connessione chiusa) o quando il
#: verificatore solleva. Non e' un codice HTTP: e' il marcatore che dice
#: «guardato, non risponde».
#:
#: Serve perche' `_da_verificare_ora` legge `esito_http` NULL come «mai
#: verificato». Riscrivere NULL su un link morto lo rimetteva in coda a ogni
#: lancio: `link-verifica --attivo --limit 200` su una fetta con 200 link morti
#: in testa rifaceva gli stessi 200 HEAD, `saltate: 0`, e le righe successive
#: non venivano guardate mai. Con il marcatore la riga esce dalla coda per la
#: giornata e torna domani, quando `updated_at` sara' di ieri.
#:
#: Zero e' il valore che `VerificaHttp._testa` gia' usa per «risposta senza
#: stato», sta in uno `smallint` e non e' un 2xx: il CHECK
#: `bando_link_pubblicabile_http_check` resta soddisfatto perche' la riga viene
#: scritta `pubblicabile=false` insieme al marcatore.
ESITO_IRRAGGIUNGIBILE = 0


def _da_verificare_ora(riga: Mapping[str, Any], oggi: date_cls) -> bool:
    """Su questa riga di `bando_link` c'e' da fare una verifica, adesso?

    Mai verificata (`esito_http` NULL) -> si', sempre: sono le righe che
    `oe-dettaglio` scrive, che nascono `pubblicabile=false` e che senza questo
    giro non diventerebbero pubblicabili mai. Perche' questo ramo resti
    «mai verificata» e non diventi «sempre da verificare», ogni tentativo deve
    lasciare un `esito_http`: se ne occupa `ESITO_IRRAGGIUNGIBILE`.

    Gia' verificata: si salta se il suo `updated_at` e' di oggi. E' l'unico
    marcatore che la tabella porta (il trigger `trg_bando_link_updated_at` lo
    mantiene su ogni UPDATE) e non esiste nessun predicato in `bando_link` che
    faccia uscire una riga dalla selezione: senza questo scarto, due lanci di
    fila rifarebbero gli stessi N HEAD sugli stessi id.
    """
    if riga.get("esito_http") is None:
        return True
    quando = riga.get("updated_at")
    if not quando:
        return True
    try:
        return date_cls.fromisoformat(str(quando)[:10]) < oggi
    except ValueError:
        return True


def _da_verificare(
    *,
    limit: int | None,
    offset: int,
    bando_id: Any,
    oggi: date_cls,
    contatori: dict[str, int],
    solo: AbstractSet[Any] | None = None,
) -> list[Mapping[str, Any]]:
    """Le righe di `bando_link` da verificare, scorrendo la selezione a pagine.

    Gemello di `_da_leggere`: le righe gia' verificate oggi si contano in
    `saltate` e non consumano il `--limit`, che torna a significare «verificane
    N» invece di «guardane N».

    `solo` e' l'insieme di id di `--solo-fonti`: scarta qui, dentro lo
    scorrimento, cosi' il `--limit` continua a contare le righe che il comando
    verifichera' davvero.
    """
    # `--limit 0` e' un limite, ed e' quello che un operatore mette per non
    # toccare niente (la convenzione e' scritta in `db._pagina`). Il
    # controllo del limite sta DOPO l'append, quindi senza questa uscita un
    # giro da zero righe ne lavorava una — e con `--attivo` era una
    # scrittura vera.
    if limit is not None and int(limit) <= 0:
        return []
    raccolte: list[Mapping[str, Any]] = []
    cursore = max(0, int(offset or 0))
    while True:
        blocco = db.select_link_da_verificare(
            limit=PAGINA_SELEZIONE_LINK, offset=cursore, bando_id=bando_id,
        )
        if not blocco:
            break
        cursore += len(blocco)
        for riga in blocco:
            # `--id X` e' un bando solo, chiesto a mano: saltarne i link
            # perche' sono stati guardati stamattina renderebbe il comando
            # inutile proprio quando serve.
            if solo is not None and riga.get("id") not in solo:
                contatori["saltate"] += 1
                continue
            if bando_id is None and not _da_verificare_ora(riga, oggi):
                contatori["saltate"] += 1
                continue
            raccolte.append(riga)
        if len(blocco) < PAGINA_SELEZIONE_LINK:
            break
    # Giro 3 (§1, revisione #147): la rotazione e' «ultimo controllo
    # crescente, mai controllato per primo». Con l'ordine per id, se il tempo
    # del passo non bastava per tutta la tabella, le righe con id alto — cioe'
    # le candidature e gli allegati dei bandi nuovi, `esito_http` NULL — non
    # arrivavano mai. Il `--limit` si applica dopo l'ordine.
    raccolte.sort(key=_chiave_rotazione_link)
    return raccolte[: int(limit)] if limit is not None else raccolte


def _chiave_rotazione_link(riga: Mapping[str, Any]) -> tuple:
    """Mai verificata (`esito_http` NULL) per prima, poi dalla verifica piu'
    vecchia (`updated_at`, che il trigger aggiorna a ogni scrittura), poi per
    id. Gli istanti di PostgREST hanno tutti lo stesso formato UTC: l'ordine
    del testo e' quello del tempo."""
    verificata = riga.get("esito_http") is not None
    quando = str(riga.get("updated_at") or "").replace("Z", "+00:00")
    identificativo = riga.get("id")
    try:
        numero = int(identificativo)
    except (TypeError, ValueError):
        numero = 0
    return (verificata, quando, numero)


def tetto_tempo_link_s() -> float:
    """`TEMPO_LINK_VERIFICA_S` (giro 3, §3 e §10), 1 200 s se `.env` non si legge."""
    try:
        from .settings import get_settings
        return float(get_settings().tempo_link_verifica_s)
    except Exception:
        return 1200.0


async def run_link_verifica(
    dry_run: bool = False,
    limit: int | None = None,
    attivo: bool | None = None,
    *,
    bando_id: Any = None,
    offset: int = 0,
    verifica: Callable[[str], Any] | None = None,
    righe: Sequence[Mapping[str, Any]] | None = None,
    solo_fonti: bool = False,
    giro: str | None = None,
    tempo_s: float | None = None,
    riferimenti: Mapping[Any, Mapping[str, Any]] | None = None,
    scarica_pagina: Callable[[str], Awaitable[Any]] | None = None,
    guardia: Callable[[str], Awaitable[str]] | None = None,
) -> dict[str, Any]:
    """Ricontrolla le righe di `bando_link` e decide la pubblicabilita'.

    §18.6: prima di ogni riga, la guardia degli indirizzi
    (`http.classifica_indirizzo`). Un URL che risolve a un indirizzo interno
    non si chiede e la riga si ritira (`indirizzi_rifiutati`); un DNS che non
    risponde non e' un giudizio sul link e segue la strada di «nessuna
    risposta». In produzione la guardia c'e' sempre; con un `verifica`
    iniettato (i test) solo se la si passa.

    Una riga diventa `pubblicabile` solo con un 2xx e con un dominio non
    aggregatore: sono le due condizioni che §13.4 promette ai consumatori. E'
    l'**unico** promotore di `bando_link.pubblicabile`: le righe scritte da
    `oe-dettaglio` nascono `pubblicabile=false` e senza questo giro non lo
    diventerebbero mai.

    `--id X` restringe a un solo bando: senza, `--id` sarebbe un'opzione
    documentata e ignorata, e chi credesse di ricontrollare una riga
    riscriverebbe `esito_http`/`pubblicabile` su tutta la tabella.

    Qui `--dry-run` non sopprime la verifica — che e' una lettura, ed e' il
    punto del comando — ma solo la scrittura.

    La selezione di `bando_link` non ha **nessun** predicato: niente puo' far
    uscire una riga dopo che e' stata verificata, nemmeno in modalita' attiva.
    Per questo il `--limit` conta le righe da verificare davvero e la
    selezione si scorre (`_da_verificare`); `--offset N` fa partire lo
    scorrimento oltre le prime N, ed e' il modo di lanciare i blocchi a mano
    quando `--dry-run` o l'ombra non scrivono il marcatore.

    Giro 3 (contratto `bandi-giro-3` §10), passo 11 del giro:
      - nessun tetto di numero: solo il tempo `TEMPO_LINK_VERIFICA_S`
        (`tempo_s` lo sostituisce). La rotazione e' `_da_verificare_ora`: le
        righe gia' verificate oggi si saltano, quindi il giro dopo riprende da
        dove questo si e' fermato. `copertura` nel risultato;
      - la quarta prova di provenienza (vedi `_verifica_link`), con i bandi
        letti da `db.select_riferimenti_bandi` e le pagine dallo scarico del
        giro. Con `righe` iniettate (test) servono `riferimenti` e
        `scarica_pagina` espliciti, altrimenti la quarta prova non si fa;
      - in produzione (nessun `verifica` iniettato) ogni verifica passa dal
        freno per host (`http._wait_for_host`) e da `asyncio.to_thread`: 1 s
        fra due richieste allo stesso host e nessun event loop bloccato.
    """
    avvio = time.monotonic()
    attivo = _modalita_attiva(attivo)
    if tempo_s is None:
        tempo_s = tetto_tempo_link_s()
    # `rimandati` sono le righe gia' pubblicabili su cui il verificatore non ha
    # avuto risposta: si lasciano come sono (vedi `_verifica_link`) e tornano al
    # giro dopo. Se e' un numero alto, il problema e' la nostra rete.
    # `non_scritte` e `senza_prova` non sono decorazioni: sono i due modi in cui
    # questo comando poteva dichiarare un lavoro che non aveva fatto.
    contatori = {"esaminati": 0, "pubblicabili": 0, "ritirati": 0,
                 "rimandati": 0, "senza_prova": 0, "non_scritte": 0,
                 "saltate": 0, "errori": 0,
                 # Giro 3 (§10): la quarta prova e il suo rifacimento sulla
                 # pagina ufficiale; `solo_aggregatore` sono le righe che dopo
                 # il rifacimento restano provate solo dalla scheda
                 # dell'aggregatore (la misura del dopo-deploy).
                 "prove_trovate": 0, "prove_mancate": 0, "prove_rifatte": 0,
                 "solo_aggregatore": 0, "indirizzi_rifiutati": 0}
    # Il filtro `--solo-fonti` va dato alla selezione, non applicato dopo:
    # `--limit` conta le righe da verificare davvero, e filtrare a valle
    # significherebbe prendere le prime N righe della tabella e buttarle quasi
    # tutte.
    solo = db.select_link_delle_fonti() if solo_fonti else None
    if righe is None:
        elenco = _da_verificare(
            limit=limit, offset=offset, bando_id=bando_id,
            oggi=oggi_roma(), contatori=contatori, solo=solo,
        )
        if riferimenti is None:
            riferimenti = db.select_riferimenti_bandi([r.get("bando_id") for r in elenco])
        if scarica_pagina is None:
            scarica_pagina = _pagina_dallo_scarico
    else:
        elenco = list(righe)
        if solo is not None:
            prima = len(elenco)
            elenco = [r for r in elenco if r.get("id") in solo]
            contatori["saltate"] += prima - len(elenco)
    # Le righe che il resolver ha scelto come fonte ufficiale: hanno la prova
    # di provenienza anche quando la riga di link non se la porta dietro.
    fonti = solo if solo is not None else db.select_link_delle_fonti()
    chiudi: Callable[[], None] | None = None
    verifica_async: Callable[[str], Awaitable[Any]] | None = None
    if verifica is None:
        from . import http as http_mod
        from .settings import get_settings
        verificatore = VerificaHttp(
            user_agent=getattr(get_settings(), "http_user_agent", ""),
        )
        verifica, chiudi = verificatore, verificatore.chiudi

        async def verifica_async(url: str) -> Any:
            await http_mod._wait_for_host(urlsplit(url).netloc)
            return await asyncio.to_thread(verificatore, url)

        if guardia is None:
            guardia = http_mod.classifica_indirizzo_async
    try:
        esito = await _verifica_link(
            elenco, verifica, contatori, dry_run, attivo, fonti_ufficiali=fonti,
            riferimenti=riferimenti or {}, scarica_pagina=scarica_pagina,
            verifica_async=verifica_async, tempo_s=tempo_s, avvio=avvio, guardia=guardia,
        )
    finally:
        if chiudi is not None:
            chiudi()
    esito["copertura"] = telemetria.copertura(
        len(elenco), contatori["esaminati"],
        "tempo" if esito.pop("_tempo_finito", False) else None)
    esito["giro"] = giro
    return esito


async def _pagina_dallo_scarico(url: str) -> Any:
    """La pagina di riferimento dallo scarico del giro (cache per giro), come
    lettura semplice: niente ripiego a pagamento, e un aggregatore e' lecito."""
    from . import scarico as scarico_mod
    return await scarico_mod.scarico_corrente().scarica(url)


async def _prova_dal_riferimento(
    url: str,
    riferimento: Mapping[str, Any],
    scarica_pagina: Callable[[str], Awaitable[Any]],
    pagine: dict[str, Any],
    *,
    url_pagina: str | None = None,
) -> tuple[str, str] | None:
    """(impronta, url della pagina) se `url` compare nella pagina di riferimento
    del bando, o None. La pagina si scarica una volta per giro (`pagine`) e
    vale solo se ha risposto 2xx."""
    pagina_url = url_pagina or pagina_di_riferimento(riferimento)
    if not pagina_url:
        return None
    if pagina_url not in pagine:
        try:
            pagine[pagina_url] = await scarica_pagina(pagina_url)
        except Exception as e:
            logger.info("[link-verifica] pagina di riferimento {} non letta: {}", pagina_url, e)
            pagine[pagina_url] = None
    pagina = pagine[pagina_url]
    if pagina is None or not getattr(pagina, "ok", False):
        return None
    effettiva = str(getattr(pagina, "url_finale", "") or pagina_url)
    prova = prova_nella_pagina(url, getattr(pagina, "html", ""), effettiva)
    return (prova, effettiva) if prova else None


def _da_rifare_sull_ufficiale(riga: Mapping[str, Any], riferimento: Mapping[str, Any] | None) -> str:
    """La pagina ufficiale su cui rifare la prova di una riga provata solo
    dall'aggregatore, o "" (giro 3, §10): la fonte e' `trovata`, la pagina
    ufficiale e' un'altra, e la prova di oggi viene da `link_bando` su un
    aggregatore."""
    if not riferimento or not riga.get("impronta_pagina"):
        return ""
    ufficiale = pagina_di_riferimento(riferimento)
    link_bando = str(riferimento.get("link_bando") or "")
    prova_da = str(riga.get("url_prova") or "")
    if (str(riferimento.get("fonte_ufficiale_stato") or "") == STATO_TROVATA
            and ufficiale and ufficiale != link_bando and link_bando
            and e_aggregatore(link_bando)
            and impronte.normalizza_url(prova_da) == impronte.normalizza_url(link_bando)):
        return ufficiale
    return ""


async def _verifica_link(
    elenco: Sequence[Mapping[str, Any]],
    verifica: Callable[[str], Any],
    contatori: dict[str, int],
    dry_run: bool,
    attivo: bool,
    *,
    fonti_ufficiali: AbstractSet[Any] = frozenset(),
    riferimenti: Mapping[Any, Mapping[str, Any]] | None = None,
    scarica_pagina: Callable[[str], Awaitable[Any]] | None = None,
    verifica_async: Callable[[str], Awaitable[Any]] | None = None,
    tempo_s: float | None = None,
    avvio: float | None = None,
    guardia: Callable[[str], Awaitable[str]] | None = None,
) -> dict[str, Any]:
    """Il ciclo di `run_link_verifica`, separato per tenere la chiusura del
    client fuori dal corpo e il corpo leggibile.

    Regola del ciclo: **ogni riga guardata deve uscirne con un `esito_http`**.
    Prima il fallimento non lasciava traccia — il verificatore che solleva
    faceva `continue` senza scrivere, e quello che torna `None` riscriveva
    `esito_http` NULL — quindi la riga tornava «mai verificata» al lancio
    successivo e il comando rifaceva per sempre gli stessi HEAD sulla stessa
    testa della tabella. Vedi `ESITO_IRRAGGIUNGIBILE`.

    Con un'eccezione, e pesa: **un link gia' pubblicabile non si ritira quando
    il fallimento e' nostro.** «Non ho ricevuto risposta» non e' una prova sul
    link, e' una notizia sulla nostra rete; e il CHECK della 02 vieta una riga
    pubblicabile senza un 2xx, quindi scrivere il marcatore vorrebbe dire
    scrivere anche `pubblicabile=false`. Con la rete giu' un solo giro avrebbe
    tolto dalle schede tutti i link verificati — circa 1 360 — per il resto
    della giornata di calendario, e nessuno li avrebbe rimessi prima di domani.
    Su quelle righe non si scrive niente e si conta `errori`: tornano al giro
    successivo (lo scheduler ne fa quattro al giorno). Il marcatore resta dove
    serviva davvero, cioe' sulle righe nate da `oe-dettaglio`, che sono gia'
    `pubblicabile=false` e che senza di esso si ripresentavano per sempre.

    Giro 3 (§10), la **quarta prova**: una riga senza prova che risponde 2xx e
    non sta su un aggregatore si cerca nell'HTML della pagina di riferimento
    del bando (`pagina_di_riferimento`: l'ufficiale con la fonte `trovata`,
    altrimenti `link_bando` anche se aggregatore, purche' risponda 2xx). Se
    c'e', la riga riceve `impronta_pagina`, `url_prova` (la pagina effettiva)
    e `trovato_in_fonte_at`, e puo' diventare pubblicabile. Una riga provata
    solo da `link_bando` su un aggregatore, il cui bando ha ora la fonte
    `trovata`, si riprova sulla pagina ufficiale: trovata, la prova si
    aggiorna; mancata, **non si ritira niente** (la prova vecchia resta vera)
    e la riga si conta in `solo_aggregatore`. A tempo scaduto non parte
    nessuna riga nuova.
    """
    riferimenti = riferimenti or {}
    pagine: dict[str, Any] = {}
    tempo_finito = False
    for riga in elenco:
        if tempo_s is not None and avvio is not None and time.monotonic() - avvio >= tempo_s:
            tempo_finito = True
            break
        contatori["esaminati"] += 1
        url = str(riga.get("url") or "")
        if not url:
            continue
        if guardia is not None and await guardia(url) == _RIFIUTATO:
            # §18.6: un indirizzo interno non si chiede, e non e' la nostra
            # rete: e' l'URL. La riga esce dai pubblicabili (mai cancellata).
            contatori["indirizzi_rifiutati"] = contatori.get("indirizzi_rifiutati", 0) + 1
            logger.warning("[link-verifica] {} rifiutato: indirizzo non pubblico", url)
            if dry_run or not attivo:
                continue
            scritto = db.aggiorna_link(riga.get("id"), {
                "esito_http": ESITO_IRRAGGIUNGIBILE, "content_type": None, "pubblicabile": False})
            if isinstance(scritto, Mapping) and not scritto.get("scritto"):
                contatori["non_scritte"] = contatori.get("non_scritte", 0) + 1
            continue
        errore = False
        try:
            grezzo = await verifica_async(url) if verifica_async is not None else verifica(url)
            esito = allegati_mod.Verifica.da(grezzo)
        except Exception as e:
            # Si continua fino alla scrittura invece di saltare: e' l'unico
            # modo di far avanzare la coda. I contatori pero' restano quelli di
            # prima — un'eccezione e' un `errori`, non un `ritirati`.
            errore = True
            esito = None
            contatori["errori"] += 1
            logger.info("[link-verifica] {} non verificato: {}", url, e)
        # La pubblicabilita' pretende una prova di provenienza: il CHECK della
        # 02 rifiuta una riga pubblicabile senza `trovato_in_fonte_at`, e §13.4
        # promette a chi legge che ogni riga leggibile compare nell'HTML della
        # pagina di riferimento. `impronta_pagina` (lo `sha256#offset` della
        # scheda) e' quella prova; le righe `raw` del backfill della 02 non ce
        # l'hanno, e restano non pubblicabili invece di far fallire l'UPDATE.
        prova = riga.get("impronta_pagina")
        trovato = riga.get("trovato_in_fonte_at")
        # Terza forma di prova: la riga **e'** la fonte ufficiale di un bando
        # `trovata`. Il resolver ha scaricato quell'URL, l'ha valutato e ci ha
        # puntato `fonte_ufficiale_link_id`; la prova esiste, e' solo rimasta
        # su `bando` invece che sulla riga di link. Senza questo ramo le 137
        # righe di backfill adottate dal resolver (misura del 24/09/2026)
        # restavano non pubblicabili per sempre: `risolvi-fonte` non ripassa
        # su un bando gia' `trovata`, e qui finivano in `senza_prova`.
        ha_prova = bool(prova or trovato or riga.get("id") in fonti_ufficiali)
        risponde = bool(esito and esito.ok) and not e_aggregatore(url)
        nuova_prova: tuple[str, str] | None = None
        riferimento = riferimenti.get(riga.get("bando_id"))
        if risponde and riferimento is not None and scarica_pagina is not None:
            if not ha_prova:
                # Quarta prova (§10).
                nuova_prova = await _prova_dal_riferimento(url, riferimento, scarica_pagina, pagine)
                chiave = "prove_trovate" if nuova_prova else "prove_mancate"
                contatori[chiave] = contatori.get(chiave, 0) + 1
                ha_prova = nuova_prova is not None
            else:
                ufficiale = _da_rifare_sull_ufficiale(riga, riferimento)
                if ufficiale:
                    nuova_prova = await _prova_dal_riferimento(
                        url, riferimento, scarica_pagina, pagine, url_pagina=ufficiale)
                    chiave = "prove_rifatte" if nuova_prova else "solo_aggregatore"
                    contatori[chiave] = contatori.get(chiave, 0) + 1
        pubblicabile = risponde and ha_prova
        if risponde and not ha_prova:
            contatori["senza_prova"] = contatori.get("senza_prova", 0) + 1
        stato = esito.esito_http if esito is not None else None
        # «Non ho ricevuto risposta»: l'eccezione, oppure un verificatore che
        # torna `None` o senza codice. Non e' un giudizio sul link.
        senza_risposta = errore or stato is None
        if not errore:
            contatori["pubblicabili" if pubblicabile else "ritirati"] += 1
        if dry_run or not attivo:
            continue
        if senza_risposta and riga.get("pubblicabile"):
            # Si lascia stare: ritirarla vorrebbe dire togliere dalle schede un
            # link che ha risposto 2xx l'ultima volta che qualcuno ha potuto
            # chiedere. Torna al giro successivo.
            contatori["rimandati"] = contatori.get("rimandati", 0) + 1
            continue
        payload = {
            # Mai NULL: NULL vuol dire «mai verificata» e rimetterebbe in coda
            # un link morto a ogni lancio. `pubblicabile` viaggia insieme allo
            # stato perche' il CHECK della 02 rifiuta una riga pubblicabile
            # senza un 2xx: le due colonne non possono divergere nemmeno per
            # un istante.
            "esito_http": stato if stato is not None else ESITO_IRRAGGIUNGIBILE,
            "content_type": esito.content_type if esito else None,
            "pubblicabile": pubblicabile,
        }
        if nuova_prova is not None:
            payload["impronta_pagina"], payload["url_prova"] = nuova_prova
            payload["trovato_in_fonte_at"] = _adesso()
        # `ultimo_visto_at` e' «l'ultimo 2xx», non «l'ultimo controllo»:
        # azzerarlo su un 500 transitorio cancellerebbe l'unica prova che quel
        # link ha funzionato.
        if pubblicabile:
            payload["ultimo_visto_at"] = _adesso()
            if not trovato and "trovato_in_fonte_at" not in payload:
                # La riga porta la prova ma non l'istante: e' il caso delle
                # 3 887 righe scritte da `oe-dettaglio` prima della correzione.
                # Si colma qui invece che con una migrazione.
                payload["trovato_in_fonte_at"] = _adesso()
        scritto = db.aggiorna_link(riga.get("id"), payload)
        if isinstance(scritto, Mapping) and not scritto.get("scritto"):
            # Non si conta come verificata una riga che non e' stata scritta.
            # Era il difetto piu' insidioso del comando: l'UPDATE rifiutato dal
            # vincolo tornava dentro un warning, il contatore diceva
            # «pubblicabili» e la riga restava con `esito_http` NULL — cioe'
            # «mai verificata» — quindi il lancio successivo la ripresentava, e
            # un ciclo «finche' esaminati non arriva a zero» non finiva mai.
            contatori["non_scritte"] = contatori.get("non_scritte", 0) + 1
            if pubblicabile:
                contatori["pubblicabili"] -= 1
            else:
                contatori["ritirati"] -= 1
    return {"status": "ok", "dry_run": dry_run, "attivo": attivo, **contatori,
            "_tempo_finito": tempo_finito}


# --- runner: `fondi-doppioni` -----------------------------------------------

ALLARME_GEMELLI_BUDGET = (
    "confronto fermato dal budget delle fusioni: il report copre solo le righe "
    "guardate prima del taglio, rilanciare per il resto"
)


async def run_fondi_doppioni(
    dry_run: bool = False,
    limit: int | None = None,
    attivo: bool | None = None,
    *,
    righe: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Doppioni esatti (fusione) e possibili doppioni (solo report), §14.

    Nessun arbitro LLM decide una fusione e il fuzzy non fonde mai: produce
    proposte con `applicato=false`, che restano nel report.

    Qui — unico fra i comandi a lotti — il `--limit` **non** impagina la
    lettura: il confronto e' fra righe dello stesso elenco, e una coppia con
    un id in pagina 1 e l'altro in pagina 3 non verrebbe trovata da nessuna
    delle due. Si legge sempre il corpus intero e il
    `--limit` diventa il budget di fusioni **applicate**: `--limit 0` vuol dire
    «solo report», che e' cio' che un operatore intende scrivendolo. Prima
    valeva `limit or 5000`, cioe' l'esatto contrario: `--limit 0 --attivo`
    leggeva l'intero corpus e applicava tutte le fusioni.

    La lettura e' l'intero corpus, il **confronto** no: e' quadratico, e a
    forza di ricalcolare per ogni coppia cio' che dipende da una riga sola
    costava 411 s su un corpus finto di 2 104 pubblicati, ora 87 s con gli
    stessi contatori (misura alternata sulla stessa macchina: 577 s -> 90 s).
    Qui i criteri esatti si calcolano una volta per riga e il loro esito viaggia
    dentro `possibili_doppioni`, che prima li rifaceva da capo; l'elenco si
    passa per intero invece di ricostruirne una copia senza la riga corrente
    (2 104 liste da 2 103 dizionari). Il resto del guadagno sta in `gemelli.py`.

    Quando il budget delle fusioni e' esaurito **e le fusioni sono il prodotto
    del lancio** (`--attivo`, senza `--dry-run`, con un budget maggiore di
    zero) il giro si ferma: continuare voleva dire pagare per intero il
    confronto quadratico per un report che quel lancio non stava chiedendo. Il
    troncamento non e' silenzioso, sta negli `allarmi`. Con `--limit 0` o in
    ombra il report **e'** il prodotto e il corpus si guarda tutto.
    """
    attivo = _modalita_attiva(attivo)
    # Giro 3 (§1): tutti i pubblicati, senza tetto di lettura (prima 5 000).
    elenco = list(righe) if righe is not None else db.select_pubblicati_per_gemelli(limit=None)
    # `rimandati` sono le righe con gemelli trovate a budget esaurito. In modo
    # report (`--dry-run`, ombra, `--limit 0`) il corpus si guarda tutto e il
    # numero e' quello vero; quando il lancio fonde davvero il confronto si
    # ferma al budget, quindi `rimandati` vale 1 e la misura di cio' che resta
    # fuori e' `non_esaminati`.
    contatori = {"esaminati": 0, "esatti": 0, "proposte": 0, "fusi": 0,
                 "rimandati": 0, "non_esaminati": 0}
    allarmi: list[str] = []
    # Il lancio fonde davvero? Solo allora il report smette di essere il
    # prodotto e il budget puo' fermare il confronto. `--limit 0` e' «solo
    # report» per definizione e non entra qui.
    fonde = bool(attivo) and not dry_run and limit is not None and limit > 0
    for riga in elenco:
        contatori["esaminati"] += 1
        # L'elenco si passa per intero: `criteri_esatti` e `possibili_doppioni`
        # saltano da soli la riga corrente (per identita' e per id), e
        # ricostruire la copia senza di lei costava 2 104 liste da 2 103
        # elementi. Le righe **senza** `id` sono l'eccezione: la copia filtrata
        # le escludeva tutte insieme, e questa correzione non cambia cio' che
        # facevano.
        altri = elenco if riga.get("id") is not None else [
            r for r in elenco if r.get("id") is not None
        ]
        corrispondenze = gemelli.criteri_esatti(riga, altri)
        contatori["esatti"] += len(corrispondenze)
        # I gemelli certi si passano gia' fatti: `possibili_doppioni` li
        # ricalcolava, cioe' ripassava il corpus una seconda volta per riga.
        contatori["proposte"] += len(gemelli.possibili_doppioni(
            riga, altri, esatti=[c.bando_id for c in corrispondenze],
        ))
        if corrispondenze and limit is not None and contatori["fusi"] >= limit:
            # Budget finito.
            contatori["rimandati"] += 1
            if fonde:
                # Il confronto e' quadratico: proseguirlo per un report che
                # questo lancio non sta chiedendo costa quanto tutto il resto
                # del comando (misurato: 176 s contro 19 s su 1 200 righe).
                # Quindi si esce, e da qui in poi `rimandati` non e' piu' «le
                # righe che restano da fondere» — vale 1 e basta. Il numero che
                # dice quanto e' rimasto fuori e' `non_esaminati`, e il fatto
                # che il report sia parziale lo dice l'allarme: senza uscire, a
                # dire «finito» o «fermato» bastava il contatore.
                contatori["non_esaminati"] = len(elenco) - contatori["esaminati"]
                allarmi.append(ALLARME_GEMELLI_BUDGET)
                logger.warning("[ALLARME] [resolver] {}", ALLARME_GEMELLI_BUDGET)
                break
            continue
        if not corrispondenze or dry_run or not attivo:
            continue
        gruppo = [riga] + [r for r in altri if r.get("id") in {c.bando_id for c in corrispondenze}]
        master = gemelli.scegli_master(gruppo)
        if master is None:
            continue
        for candidato in gruppo:
            if candidato.get("id") == master.get("id"):
                continue
            # `fondi_bandi` ritorna l'id del master **effettivo** (la RPC
            # appiattisce le catene e puo' sceglierne un altro), o None se non
            # ha scritto: un id diverso da quello proposto si annota, perche'
            # e' l'unico segnale che `bando_scegli_master` ha corretto la
            # scelta di `gemelli.scegli_master`.
            effettivo = db.fondi_bandi(master.get("id"), candidato.get("id"), "gemello esatto")
            if effettivo is None:
                continue
            contatori["fusi"] += 1
            if effettivo != master.get("id"):
                contatori["master_corretti"] = contatori.get("master_corretti", 0) + 1
                logger.info(
                    "[resolver] fusione {} -> master {} (proposto {})",
                    candidato.get("id"), effettivo, master.get("id"))
    return {"status": "ok", "dry_run": dry_run, "attivo": attivo,
            "allarmi": allarmi, **contatori}


# --- runner: `domini --import` ----------------------------------------------

async def run_domini_import(
    dry_run: bool = False,
    limit: int | None = None,
    attivo: bool | None = None,
    *,
    enti: str | None = None,
    fonti: Sequence[Mapping[str, Any]] | None = None,
    indicepa: Sequence[Mapping[str, Any]] | None = None,
    scarica_enti: bool = False,
    scarica: Callable[[str], bytes] | None = None,
    soglia_righe: int | None = None,
    giro: str | None = None,
) -> dict[str, Any]:
    """Compone la whitelist e la scrive in `dominio_ufficiale`.

    Le sorgenti sono quelle di §5: gli host di `fonte.link` `discoverable`, il
    foglio IndicePA (`--enti PATH`, letto con `openpyxl`, gia' installato) e il
    seed compilato. Senza `--enti` l'import fa comunque il suo lavoro con le
    altre due: e' meglio di non poterlo lanciare affatto.

    In attivo scrive **solo host assenti** (`db.inserisci_domini_nuovi`): una
    riga esistente non si modifica mai, come nell'import completo.

    Con `scarica_enti=True` e' invece l'import **completo** e automatico di
    IndicePA (contratto `bandi-giro-2` §19.8, `_importa_indicepa_completo`):
    scarica il foglio, lo controlla e inserisce i soli host assenti.
    """
    if scarica_enti:
        return _importa_indicepa_completo(
            dry_run=dry_run, attivo=attivo, indicepa=indicepa, scarica=scarica,
            soglia_righe=SOGLIA_RIGHE_INDICEPA if soglia_righe is None else soglia_righe,
            giro=giro,
        )
    from .dominio_ufficiale import analizza_indicepa, costruisci, da_fonti

    attivo = _modalita_attiva(attivo)
    righe_fonte = list(fonti) if fonti is not None else db.select_fonti_per_domini()
    righe_enti = list(indicepa) if indicepa is not None else _leggi_enti(enti)
    # Le righe IndicePA passano dalle stesse esclusioni dell'import completo
    # (§19.8): piattaforme condivise, host con 3 o piu' codici, e la
    # blocklist della tabella corrente (DB piu' seed), non del solo seed.
    analisi = analizza_indicepa(righe_enti, tabella=_tabella_corrente()) if righe_enti else None
    tabella = costruisci(
        [*da_fonti(righe_fonte), *(analisi.domini if analisi is not None else ())])
    attive = tabella.attive()
    composte = len(attive)
    # `limit is not None` e non `if limit`: uno zero e' un limite (la
    # convenzione di `db._pagina`), e `--limit 0 --attivo` scriveva invece
    # l'intera whitelist — l'esatto contrario di cio' che ha chiesto.
    if limit is not None:
        attive = attive[: int(limit)]
    payload = [
        {
            "host": riga.host, "tipo": riga.tipo, "confidenza": riga.confidenza,
            "ente": riga.ente, "codice_ipa": riga.codice_ipa, "fonte_id": riga.fonte_id,
            "origine": riga.origine, "attivo": riga.attivo,
        }
        for riga in attive
    ]
    scritte = 0
    gia_presenti = 0
    if payload and not dry_run and attivo:
        # Solo host assenti (§19.8): una riga che c'e' gia' (seed, fonte,
        # manuale, un import precedente) non si aggiorna mai. Prima qui c'era
        # `upsert_domini`, che riscriveva tipo e confidenza corretti a mano.
        esito_scrittura = db.inserisci_domini_nuovi(payload, lotto=LOTTO_DOMINI)
        scritte = int(esito_scrittura.get("inserite") or 0)
        gia_presenti = int(esito_scrittura.get("gia_presenti") or 0)
        azzera_tabella_corrente()
    troncati = composte - len(payload)
    if troncati > 0:
        # Il `--limit` qui e' un troncamento del PREFISSO, non un cursore: la
        # composizione ha sempre lo stesso ordine, quindi due lanci con lo
        # stesso limite riscrivono gli stessi host e gli altri non arrivano
        # mai. Una whitelist parziale che risponde «ok» e' il modo piu' rapido
        # di far passare un aggregatore per dominio non classificato.
        logger.warning(
            "[ALLARME] [domini] whitelist troncata da --limit: {} host su {} "
            "non importati (il limite taglia sempre lo stesso prefisso)",
            troncati, composte,
        )
    return {
        "status": "ok", "dry_run": dry_run, "attivo": attivo,
        "fonti": len(righe_fonte), "indicepa": len(righe_enti),
        "domini": len(payload), "composti": composte, "troncati": troncati,
        "scritte": scritte, "gia_presenti": gia_presenti,
        "indicepa_esclusi": dict(analisi.esclusi) if analisi is not None else {},
    }


def _leggi_enti(percorso: str | None) -> list[dict[str, Any]]:
    """`enti.xlsx` di IndicePA, o lista vuota. Nessuna dipendenza nuova."""
    if not percorso:
        return []
    try:
        from openpyxl import load_workbook  # noqa: F401
    except Exception as e:                               # pragma: no cover - ambiente
        logger.warning("[domini] openpyxl non disponibile ({}): IndicePA saltato", e)
        return []
    try:
        return _righe_del_foglio(percorso)
    except Exception as e:
        logger.warning("[domini] {} non leggibile: {}", percorso, e)
        return []


def _righe_del_foglio(sorgente: Any) -> list[dict[str, Any]]:
    """Le righe del primo foglio di un xlsx (percorso o file in memoria), per intestazione."""
    from openpyxl import load_workbook
    foglio = load_workbook(sorgente, read_only=True, data_only=True).active
    righe = foglio.iter_rows(values_only=True)
    intestazioni = [str(c or "") for c in next(righe, ())]
    return [dict(zip(intestazioni, valori)) for valori in righe]


# --- import completo di IndicePA (contratto `bandi-giro-2` §19.8) ----------

#: La risorsa pubblica di IndicePA (CKAN, dataset «enti», XLSX), misurata il
#: 30/09/2026 (`docs/bandi-monitor/misure-giro-2-percorso-a.md`, M10). La
#: variabile `INDICEPA_URL` serve solo a cambiarla. Se un giorno la risorsa
#: cambiasse id, la si ritrova con
#: `https://indicepa.gov.it/ipa-dati/api/3/action/package_show?id=enti`.
INDICEPA_URL_PREDEFINITO = (
    "https://indicepa.gov.it/ipa-dati/dataset/5baa3eb8-266e-455a-8de8-b1f434c279b2"
    "/resource/d09adf99-dc10-4349-8c53-27b1e5aa97b6/download/enti.xlsx"
)
#: Sotto queste righe utili il foglio e' anomalo e non si scrive niente: il 30/09
#: erano 22 891 su 23 750.
SOGLIA_RIGHE_INDICEPA = 15_000
#: Il foglio pesa 4,3 MB: oltre questo tetto non e' il foglio che ci aspettiamo.
TETTO_BYTE_INDICEPA = 20 * 1024 * 1024
TIMEOUT_INDICEPA_S = 60.0
#: Righe per INSERT in `dominio_ufficiale`.
LOTTO_DOMINI = 500
#: Lo step della riga di `pipeline_run` dell'import: il posto fisso dove la
#: salute cerca l'ultimo import (codici `indicepa_non_aggiornato` e
#: `indicepa_import_anomalo`).
STEP_DOMINI = "domini"
ESITO_INDICEPA_OK = "ok"
ESITO_INDICEPA_OMBRA = "ombra"
ESITO_INDICEPA_ANOMALO = "anomalo"
ESITO_INDICEPA_DOWNLOAD_FALLITO = "download_fallito"
ESITO_INDICEPA_SCRITTURA_PARZIALE = "scrittura_parziale"


def scarica_indicepa(
    url: str,
    *,
    transport: Any = None,
    timeout: float = TIMEOUT_INDICEPA_S,
    tetto_byte: int = TETTO_BYTE_INDICEPA,
) -> bytes:
    """GET del foglio IndicePA. Solleva su un errore HTTP o oltre `tetto_byte`."""
    import httpx

    with httpx.Client(transport=transport, timeout=timeout, follow_redirects=True) as client:
        with client.stream("GET", url) as risposta:
            risposta.raise_for_status()
            dati = bytearray()
            for pezzo in risposta.iter_bytes():
                dati.extend(pezzo)
                if len(dati) > tetto_byte:
                    raise ValueError(f"foglio IndicePA oltre {tetto_byte} byte")
    return bytes(dati)


def _modalita_indicepa(attivo: bool | None) -> bool:
    """La scrittura dell'import segue `DOMINI_MODALITA` (giro 3, §3 e §12; fino
    al giro 2 `VERIFICA_STATO_MODALITA`); un `attivo` esplicito vince."""
    if attivo is not None:
        return bool(attivo)
    try:
        from .settings import get_settings
        valore = getattr(get_settings(), "domini_modalita", "ombra")
    except Exception:
        return False
    return str(valore).strip().lower() == "attivo"


def _importa_indicepa_completo(
    *,
    dry_run: bool,
    attivo: bool | None,
    indicepa: Sequence[Mapping[str, Any]] | None,
    scarica: Callable[[str], bytes] | None,
    soglia_righe: int,
    giro: str | None,
) -> dict[str, Any]:
    """Import completo di IndicePA, con le regole prudenti di §19.8.

    - si inseriscono **solo host assenti** (`db.inserisci_domini_nuovi`): una
      riga esistente non si modifica mai e niente si cancella;
    - host condivisi, piattaforme e blocklist restano fuori
      (`dominio_ufficiale.analizza_indicepa`), ognuno col suo motivo;
    - un foglio con meno di `soglia_righe` righe utili, o senza una colonna
      attesa, e' anomalo: non si scrive niente;
    - un download fallito lascia la tabella com'e';
    - in ombra si scarica, si compone e si conta; con `dry_run` non si scrive
      niente di niente, nemmeno la riga di `pipeline_run`.
    L'esito (`indicepa_*`) va anche in una riga `pipeline_run` step='domini'.
    """
    from .dominio_ufficiale import analizza_indicepa

    attivo = _modalita_indicepa(attivo)
    avvio = time.monotonic()
    contatori: dict[str, Any] = {
        "indicepa_esito": None,
        "indicepa_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "indicepa_modalita": "attivo" if attivo else "ombra",
        "indicepa_righe_lette": 0, "indicepa_righe_utili": 0, "indicepa_ammessi": 0,
        "indicepa_gia_presenti": 0, "indicepa_inseriti": 0, "indicepa_esclusi": {},
        "indicepa_lotti_falliti": 0, "indicepa_colonne_mancanti": [],
    }

    def chiudi(esito: str) -> dict[str, Any]:
        contatori["indicepa_esito"] = esito
        if not dry_run:
            guasto = esito in (ESITO_INDICEPA_ANOMALO, ESITO_INDICEPA_DOWNLOAD_FALLITO)
            riga = telemetria.PipelineRun(step=STEP_DOMINI, giro=giro).concludi(
                durata_s=time.monotonic() - avvio,
                esito=telemetria.esito_da_contatori(errori=1 if guasto else 0),
                contatori=contatori,
            )
            telemetria.scrivi_pipeline_run(riga)
        return {"status": "ok", "dry_run": dry_run, "attivo": attivo, **contatori}

    righe = indicepa
    if righe is None:
        try:
            from .settings import get_settings
            url = getattr(get_settings(), "indicepa_url", "") or INDICEPA_URL_PREDEFINITO
        except Exception:
            url = INDICEPA_URL_PREDEFINITO
        try:
            dati = (scarica or scarica_indicepa)(url)
            from io import BytesIO
            righe = _righe_del_foglio(BytesIO(dati))
        except Exception as e:
            logger.warning("[domini] IndicePA non scaricato o non leggibile: {}", type(e).__name__)
            return chiudi(ESITO_INDICEPA_DOWNLOAD_FALLITO)

    analisi = analizza_indicepa(righe, tabella=_tabella_corrente())
    contatori.update({
        "indicepa_righe_lette": analisi.righe_lette,
        "indicepa_righe_utili": analisi.righe_utili,
        "indicepa_ammessi": len(analisi.domini),
        "indicepa_esclusi": dict(analisi.esclusi),
        "indicepa_colonne_mancanti": list(analisi.colonne_mancanti),
    })
    if analisi.colonne_mancanti or analisi.righe_utili < soglia_righe:
        logger.warning(
            "[ALLARME] [domini] foglio IndicePA anomalo: {} righe utili (soglia {}), "
            "colonne mancanti {}: nessuna scrittura",
            analisi.righe_utili, soglia_righe, list(analisi.colonne_mancanti))
        return chiudi(ESITO_INDICEPA_ANOMALO)

    payload = [
        {"host": d.host, "tipo": d.tipo, "confidenza": d.confidenza, "ente": d.ente,
         "codice_ipa": d.codice_ipa, "origine": d.origine, "attivo": True}
        for d in analisi.domini
    ]
    if dry_run or not attivo:
        presenti = {str(r.get("host") or "").strip().lower()
                    for r in db.select_domini_ufficiali()}
        contatori["indicepa_gia_presenti"] = sum(1 for r in payload if r["host"] in presenti)
        return chiudi(ESITO_INDICEPA_OMBRA)

    scritte = db.inserisci_domini_nuovi(payload, lotto=LOTTO_DOMINI)
    contatori["indicepa_gia_presenti"] = int(scritte.get("gia_presenti") or 0)
    contatori["indicepa_inseriti"] = int(scritte.get("inserite") or 0)
    contatori["indicepa_lotti_falliti"] = int(scritte.get("lotti_falliti") or 0)
    # La tabella in memoria e' cambiata: il resto del giro deve vedere l'import.
    azzera_tabella_corrente()
    if scritte.get("errore") or contatori["indicepa_lotti_falliti"]:
        return chiudi(ESITO_INDICEPA_SCRITTURA_PARZIALE)
    return chiudi(ESITO_INDICEPA_OK)


__all__ = [
    "Ambiente", "Candidato", "Contatori", "Contesto", "Esito", "FonteUfficialeError",
    "FONTI_OE", "Gate", "JACCARD_ALTO", "JACCARD_MEDIO", "LOCK_RESOLVER",
    "METODI_STRUTTURATI", "Pagina", "PUNTI", "Punteggio", "SEGNALE_CONTENUTO",
    "SEGNALE_DOMINIO", "SEGNALE_TITOLO", "SEGNALI_RICHIESTI", "SOGLIA_TROVATA",
    "SOGLIA_VERIFICA", "STATI", "STATO_IN_VERIFICA", "STATO_NON_TROVATA",
    "STATO_TROVATA", "TESTO_MINIMO", "TIPI_MAI_TROVATA", "candidati_da_scheda",
    "candidati_strutturati", "contesto_da_bando", "domini_ammessi", "e_pagina_indice",
    "e_soft_404", "esito_da_punteggio", "eventi", "gate_duri", "intestazioni_pagina",
    "copertura", "somiglianza_titolo", "COPERTURA_ALTA", "COPERTURA_MEDIA",
    "TOKEN_MINIMI_COPERTURA",
    "jaccard", "pagina_da_risposta", "payload_controllo", "payload_fonte",
    "prossimo_controllo", "punteggia", "punti_dominio", "query_ricerca", "righe_link",
    "scaduto",
    "risolvi", "run", "run_domini_import", "run_fondi_doppioni", "run_link_verifica",
    "azzera_tabella_corrente", "scarica_indicepa", "INDICEPA_URL_PREDEFINITO",
    "schede_gia_lette",
    "run_oe_dettaglio", "scrivi_esito", "token", "zona_grigia",
]
