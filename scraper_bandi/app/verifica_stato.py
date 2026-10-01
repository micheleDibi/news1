"""Passo verifica-stato (contratto `bandi-giro-2` §5 con §19.4, §19.6, §19.11).

Rilegge la pagina ufficiale dei bandi il cui stato pubblicato non ha prove —
«in apertura» e «aperto» senza scadenza — e ne scrive la lettura in
`bando_controllo`. Con `VERIFICA_STATO_MODALITA=attivo` registra anche gli
eventi che la lettura giustifica (chiusura, rettifica di data_scadenza,
data_verificata, apertura), dopo i gate del percorso verifica_stato
(`eventi.valuta_verifica`).

Due fasi, senza tetti di numero (giro 3, §1 e §13: solo tempo con rotazione,
freno per host e spesa del modello):
- **controlli** (dopo il monitor, nei giri di `MONITOR_GIRI`): i pubblicati,
  entro `VERIFICA_STATO_TETTO_S` (30 minuti per difetto);
- **ingresso** (prima della SEO, a ogni giro): le righe `enriched` non ancora
  pubblicate, senza modello, entro 300 s. In attivo scrive date e
  «chiuso» da un lettore per ente su `bando` (via `db.aggiorna_ingresso`, che
  rifiuta i pubblicati); in ombra solo `bando_controllo`. Semina la storia delle
  letture, cosi' la doppia lettura (G7e) puo' accoppiare dopo la pubblicazione.

Regole di scrittura (§5.7, §19.4): sempre `lettura_stato`, `lettura_stato_at`,
`prossima_lettura_at`, `letture_stato_nulle`, `previsto_entro`,
`termine_indicato` con la sua fonte; SOLO in attivo le sei colonne
`stato_letto*` e `esaminato_attivo_at` (per ogni candidato esaminato,
illeggibili compresi). Mai `prossimo_controllo_at`, testi, impronte, righe di
`bando` nella fase controlli: le colonne di `bando` le cambia solo un evento.

Nucleo puro piu' I/O iniettato, come `monitoraggio.py`: `FonteDati` per il DB,
`scarica` per le pagine (lo `Scarico` condiviso, redirect solo sullo stesso
host, mai Firecrawl), `leggi_modello` per il modello, `rigenerazione` per la
prosa. Non solleva mai.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Mapping, Sequence
from urllib.parse import urlsplit

from . import eventi as eventi_mod
from . import etichette_stato
from . import telemetria
from .date_validation import (
    e_presunta,
    termine_da_calendario,
    termine_da_etichetta_oe,
    termine_nel_testo,
    termine_nella_pagina,
    termine_per_precedenza,
)
from .dominio_ufficiale import ACCORCIATORI, dominio_di, e_aggregatore, verificabile
from .gemelli import FONTI_OE
from .logger import logger
from .stato_bando import adesso_roma, stato_da_verificare, stato_effettivo

STEP = "verifica_stato"
STEP_INGRESSO = "verifica_stato_ingresso"
FASE_CONTROLLI = "controlli"
FASE_INGRESSO = "ingresso"
FASI: tuple[str, ...] = (FASE_CONTROLLI, FASE_INGRESSO)
RAMO_I = "I"
RAMO_A = "A"
STATO_IN_APERTURA = "in apertura prossimamente"
STATO_APERTO = "aperto"
MODALITA_OMBRA = "ombra"
MODALITA_ATTIVO = "attivo"
MOTIVO_MIGRAZIONE_ASSENTE = "migrazione_assente"
ESTRATTORE_GENERICO = "generico"

#: Esiti di una lettura. `da_riprovare`: un primo 404/410 (la pagina rimossa
#: vuole due risposte di fila) o una risposta HTTP non 2xx: si rilegge domani,
#: senza contare un errore di rete ne' una lettura nulla.
ESITO_LETTA = "letta"
ESITO_NON_DECISIVA = "non_decisiva"
ESITO_PAGINA_RIMOSSA = "pagina_rimossa"
ESITO_ERRORE_RETE = "errore_rete"
ESITO_DA_RIPROVARE = "da_riprovare"
ESITO_ILLEGGIBILE = "illeggibile"

#: Tempo massimo per un bando (tutte le sue GET) e per la fase ingresso.
TETTO_TEMPO_BANDO_S = 120
TETTO_TEMPO_INGRESSO_S = 300
STORIA_MAX = 5
#: Le voci di `esito['proposte']` (la CLI le stampa una per riga).
PROPOSTE_MAX = 50
#: Freno per (host, estrattore) su una finestra mobile (§5.6).
GIORNI_FRENO = 7
FRENO_MIN_PASSAGGI = 5
FRENO_QUOTA = 0.5
#: Un aperto confermato si rilegge ogni 3 giorni se giovane o con una
#: finestra, altrimenti ogni 14 (§5.9).
GIORNI_APERTO_GIOVANE = 60
#: Una lettura leggibile piu' vecchia di cosi' e' «scaduta» (come
#: `db.GIORNI_LETTURA_SCADUTA`, codice `leggibile_non_letto`).
GIORNI_LETTURA_SCADUTA = 16
#: Gli eventi recenti del bando che i gate guardano (G5, G8).
GIORNI_EVENTI_RECENTI = 30
#: Le attese dopo la prima, la seconda e la terza risposta «da riprovare» di
#: fila sullo stesso url; dalla quarta 14 giorni, come un illeggibile
#: (revisione #96, decisione del lead: 1, 1, 3, poi 14).
CADENZA_DA_RIPROVARE: tuple[int, ...] = (1, 1, 3)
#: Nel riassunto della lettura vince l'evento piu' forte (revisione #96, P1-1):
#: uno di stato cambia la pagina piu' di una data, una data nuova piu' di una
#: data confermata.
FORZA_PROPOSTA: dict[str, int] = {"chiusura": 3, "apertura": 3, "rettifica": 2, "data_verificata": 1}

#: Priorita' dei candidati (§5.2 piu' §19.4). A parita' passa prima chi e'
#: stato letto meno di recente (mai letto per primo), poi l'id: e' la rotazione
#: del giro 3 (§1), chi resta fuori per il tempo parte per primo al giro dopo.
PRIORITA: dict[str, int] = {
    "data_apertura_passata": 90,
    "segnale": 88,
    "termine_passato": 85,
    "mai_letto": 80,
    "seconda_lettura": 75,
    "smentito_dalla_fonte": 70,
    "previsione_scaduta": 60,
    "senza_conferma": 50,
    "aperto_da_rinnovare": 45,
    "rinnovo": 40,
}
#: Cadenza delle riletture, in giorni (§5.9 con §19.4).
CADENZA_GIORNI: dict[str, int] = {
    "segnalato": 3,
    "seconda_lettura": 3,
    "aperto_giovane": 3,
    "aperto_confermato": 14,
    "in_apertura_confermato": 14,
    "non_decisive_ripetute": 14,
    "solo_segnale_ripetuto": 14,
    "pagina_rimossa": 14,
    "errore_rete": 1,
    "da_riprovare": 1,
    "da_riprovare_ripetuto": 14,
    "illeggibile": 14,
    "senza_conferma": 14,
    "trattenuta": 1,
    "predefinita": 3,
}
#: Lo stato letto da un lettore -> la colonna `stato_letto` (CHECK della 13).
STATO_LETTO: dict[str, str] = {
    "in_apertura": STATO_IN_APERTURA,
    "aperto": STATO_APERTO,
    "chiuso": "chiuso",
    "uscito": "uscito",
}
#: Pagine su cui il modello puo' leggere (§5.4).
PAGINE_MODELLO: tuple[str, ...] = ("i", "ii", "iii")

#: Gate di parola sulla lettura del modello (§5.4).
_PARTICIPIO_COMPIUTO_RE = re.compile(
    r"\besaurit[ae]\b|\bchius[oa]\b|\bscadut[oa]\b|\bsospes[oa]\b|\btermini\s+(?:sono\s+)?scaduti\b"
    r"|\bconclus[oa]\b",
    re.IGNORECASE,
)
_POTENZIALE_RE = re.compile(
    r"fino\s+a(?:d)?\s+esauriment|in\s+caso\s+di\s+esauriment|potr[aà]\s+essere\s+(?:sospes|chius)",
    re.IGNORECASE,
)

# --- verita' nota (§5.9 con §19.4 e le misure del 30/09-01/10) ---------------

#: Il vocabolario degli esiti del report: le date si scrivono «tipo:AAAA-MM-GG».
ESITI_VERITA: tuple[str, ...] = (
    "chiusura", "smentito", "confermato", "rettifica", "data_verificata", "apertura",
    "uscito", "non_decisiva", "forse_non_un_bando", "dalla_sorella", "termine_indicato",
    "segnalato", "illeggibile",
)
#: Gli esiti attesi con `--senza-modello`. Basta una lettura: anche una
#: proposta trattenuta dalla doppia lettura (G7e, due letture concordi a
#: distanza di almeno 60 ore) da' gia' l'esito del suo tipo (`esito_report`).
#: `report-verifica-stato --verita` stampa DIFFORME per ogni id diverso; con
#: una sola difformita' non si attiva. Un id uscito dai candidati perche' il suo
#: stato e' gia' quello atteso (`ESITO_STATO_ATTESO`) non e' difforme: e'
#: `confermato_da_stato` (giro 3, §13).
VERITA_NOTA: dict[int, str] = {
    # ramo A
    2387: "chiusura", 18344: "chiusura", 18444: "chiusura", 2919: "chiusura", 18400: "chiusura",
    18337: "smentito", 18357: "smentito",
    17903: "confermato", 18454: "confermato",
    2339: "rettifica:2027-01-19", 256211: "rettifica:2026-09-25",
    18315: "non_decisiva", 18387: "non_decisiva", 18423: "non_decisiva",
    3042: "non_decisiva", 110821: "non_decisiva",
    2448: "forse_non_un_bando", 2449: "forse_non_un_bando", 2621: "forse_non_un_bando",
    2622: "forse_non_un_bando",
    # ramo I
    2971: "uscito",
    # I «concluso» del Piemonte, rimisurati il 01/10 sulle pagine pubbliche:
    # tre chiusi confermati (2892 e 2893 dalla pagina collegata «Scaduto»,
    # 661135 dalla sua), 150489 solo segnale («Esito» sulla pagina collegata).
    # 661135 l'ha chiuso il job orario il 30/09 alle 22:05 UTC (scadenza del
    # 30/09, evento 12005): non e' piu' un candidato, e vale come chiusura
    # confermata dallo stato (`ESITO_STATO_ATTESO`), non come difforme.
    2892: "chiusura", 2893: "chiusura", 661135: "chiusura", 150489: "smentito",
    106753: "data_verificata", 2375: "data_verificata", 270806: "data_verificata",
    1072674: "apertura", 1072686: "apertura",
    17978: "chiusura",
    577475: "dalla_sorella",
    1261858: "confermato", 327381: "confermato",
    10258: "non_decisiva",
    # A+ (§19.4, misure M9)
    2475: "chiusura", 2520: "chiusura",
    5699: "smentito", 5700: "smentito",
    5698: "termine_indicato:2026-12-31",
    803614: "termine_indicato:2029-07-15", 803615: "termine_indicato:2026-12-31",
    803623: "termine_indicato:2026-10-30",
    562317: "termine_indicato:2026-09-08",
    17773: "segnalato", 18178: "segnalato",
    17883: "segnalato", 18186: "segnalato", 18312: "segnalato",
    18231: "smentito",
    18276: "smentito", 18262: "smentito",
    18407: "non_decisiva",
}
#: L'esito atteso -> lo stato effettivo che lo conferma quando il bando e'
#: uscito dai candidati (giro 3, §13; decisione del lead: solo questi due, gli
#: altri esiti usciti dai candidati restano difformi).
ESITO_STATO_ATTESO: dict[str, str] = {"chiusura": "chiuso", "apertura": STATO_APERTO}


# --- tipi -------------------------------------------------------------------

@dataclass(frozen=True)
class PaginaDaLeggere:
    """La pagina scelta per un candidato (§5.3 con §19.4)."""
    tipo: str                           # i | ii | ii-c | iii | iv | illeggibile
    url: str | None = None
    #: Il link e' un accorciatore (rpu.gl, bit.ly…): si segue con redirect
    #: 'tutti' e vale solo se l'URL finale e' verificante.
    accorciatore: bool = False
    #: La sorella /avvisi/ di un /preavvisi/ di pninclusione (iii).
    sorella: str | None = None


@dataclass(frozen=True)
class Candidato:
    riga: Mapping[str, Any]
    controllo: Mapping[str, Any]
    ramo: str
    stato_effettivo: str
    motivo: str | None
    pagina: PaginaDaLeggere
    priorita: int


@dataclass
class EsitoLettura:
    """Cio' che la lettura di una pagina ha dato."""
    esito: str
    pagina: PaginaDaLeggere
    url_finale: str | None = None
    testo: str = ""
    http: int | None = None
    lettura: Any = None                 # etichette_stato.Lettura | LetturaModello | None
    metodo: str | None = None           # 'estrattore' | 'modello'
    livello_titolo: str | None = None
    forse_non_un_bando: bool = False
    non_verificante: bool = False
    dalla_sorella: bool = False
    host_irraggiungibile: bool = False
    #: La chiave del lettore che ha guardato la pagina (per `esiti_per_estrattore`).
    chiave_lettore: str | None = None
    #: Quante risposte «da riprovare» di fila sullo stesso url, questa compresa.
    da_riprovare_di_fila: int = 0


@dataclass(frozen=True)
class LetturaModello:
    """La lettura del modello, dopo i gate di parola (§5.4). Mai un evento."""
    stato: str
    citazione: str
    etichetta: str = ""
    estrattore: str | None = None
    puo_chiudere: bool = False
    solo_segnale: bool = True
    termine_finale: Any = None
    date: tuple = ()
    finestra: bool = False
    link_collegato: str | None = None

    @property
    def citazione_stato(self) -> str:
        return self.citazione


# --- utilita' pure --------------------------------------------------------------

_FRAZIONE_RE = re.compile(r"\.(\d+)")


def _istante(valore: Any) -> datetime | None:
    if isinstance(valore, datetime):
        return valore if valore.tzinfo else valore.replace(tzinfo=timezone.utc)
    if not valore:
        return None
    testo = str(valore).strip().replace("Z", "+00:00").replace(" ", "T", 1)
    testo = _FRAZIONE_RE.sub(lambda m: "." + (m.group(1) + "000000")[:6], testo, count=1)
    try:
        letto = datetime.fromisoformat(testo)
    except ValueError:
        return None
    return letto if letto.tzinfo else letto.replace(tzinfo=timezone.utc)


def _data(valore: Any) -> date | None:
    if isinstance(valore, datetime):
        return valore.date()
    if isinstance(valore, date):
        return valore
    if isinstance(valore, str) and len(valore) >= 10:
        try:
            return date.fromisoformat(valore[:10])
        except ValueError:
            return None
    return None


def _mappa(valore: Any) -> Mapping[str, Any]:
    return valore if isinstance(valore, Mapping) else {}


def normalizza_link_bando(testo: Any) -> list[str]:
    """Gli URL http(s) di un campo `link_bando`, che a volte ne contiene due (5699)."""
    if not isinstance(testo, str):
        return []
    return [p for p in testo.split() if p.lower().startswith(("http://", "https://"))]


def e_accorciatore(url: str | None) -> bool:
    host = dominio_di(url or "") or ""
    return any(host == a or host.endswith("." + a) for a in ACCORCIATORI)


def _leggibile(url: str | None, tabella: Any) -> bool:
    """Host verificante (tabella letta dal DB) e non aggregatore."""
    host = dominio_di(url or "")
    return bool(host) and verificabile(host, tabella) and not e_aggregatore(host, tabella)


def pagina_da_leggere(
    riga: Mapping[str, Any],
    controllo: Mapping[str, Any],
    pagine_bando: Sequence[str],
    tabella: Any,
) -> PaginaDaLeggere:
    """La pagina da leggere (§5.3 con §19.4), in ordine: (i) la fonte ufficiale
    trovata; (ii) il link_bando sull'host della fonte di scraping, fuori da OE;
    (ii-c) il candidato prioritario sullo stesso host; un accorciatore da
    seguire; (iv) un link verificabile su un altro host o una pagina_bando;
    altrimenti illeggibile, senza fetch. La pagina di un aggregatore non si
    legge mai."""
    fonte_oe = riga.get("fonte_id") in FONTI_OE
    host_fonte = riga.get("host_fonte")
    if riga.get("fonte_ufficiale_stato") == "trovata" and riga.get("fonte_ufficiale_url"):
        url = str(riga["fonte_ufficiale_url"])
        if _leggibile(url, tabella):
            return PaginaDaLeggere("i", url, sorella=etichette_stato.sorella_preavviso(url))
    altri: list[str] = []
    accorciatori: list[str] = []
    for url in normalizza_link_bando(riga.get("link_bando")):
        if e_accorciatore(url):
            accorciatori.append(url)
            continue
        if not _leggibile(url, tabella):
            continue
        if not fonte_oe and host_fonte and dominio_di(url) == host_fonte:
            return PaginaDaLeggere("ii", url, sorella=etichette_stato.sorella_preavviso(url))
        altri.append(url)
    prioritario = controllo.get("candidato_prioritario")
    if (isinstance(prioritario, str) and not fonte_oe and host_fonte
            and dominio_di(prioritario) == host_fonte and _leggibile(prioritario, tabella)):
        return PaginaDaLeggere("ii-c", prioritario)
    if accorciatori:
        # Il tipo vero si decide dall'URL finale (`leggi_pagina`).
        return PaginaDaLeggere("iv", accorciatori[0], accorciatore=True)
    for url in [*altri, *pagine_bando]:
        if _leggibile(url, tabella):
            return PaginaDaLeggere("iv", url)
    return PaginaDaLeggere("illeggibile")


def pagine_da_link(link: Mapping[Any, Sequence[Mapping[str, Any]]]) -> dict[Any, list[str]]:
    """{bando_id: url} delle righe `bando_link` di tipo 'pagina_bando'."""
    pagine: dict[Any, list[str]] = {}
    for bando_id, righe in link.items():
        for riga in righe:
            if riga.get("tipo") == "pagina_bando" and riga.get("url"):
                pagine.setdefault(bando_id, []).extend(normalizza_link_bando(riga["url"]))
    return pagine


def _lettura_stato(controllo: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mappa(controllo.get("lettura_stato"))


def _storia(controllo: Mapping[str, Any]) -> tuple[eventi_mod.LetturaStato, ...]:
    voci = _lettura_stato(controllo).get("storia") or ()
    if not isinstance(voci, (list, tuple)):
        return ()
    letture = (eventi_mod.LetturaStato.da(v) for v in voci)
    return tuple(sorted((l for l in letture if l is not None), key=lambda l: l.at))


def motivo_di(riga: Mapping[str, Any], controllo: Mapping[str, Any], adesso: datetime) -> str | None:
    """Il motivo di `stato_da_verificare` con le colonne di oggi (§3, §19.3)."""
    return stato_da_verificare(
        riga.get("stato_bando"), riga.get("data_apertura"), riga.get("data_apertura_verificata"),
        riga.get("ora_apertura"), riga.get("data_scadenza"), riga.get("ora_scadenza"),
        riga.get("pubblicato_at"), controllo.get("previsto_entro"), controllo.get("termine_indicato"),
        controllo.get("stato_letto"), controllo.get("stato_letto_su"), controllo.get("stato_letto_at"),
        controllo.get("stato_letto_metodo"), controllo.get("esaminato_attivo_at"),
        controllo.get("segnale_aggregatore_at"), adesso=adesso,
    )


def ramo_di(riga: Mapping[str, Any], adesso: datetime) -> tuple[str | None, str | None]:
    """(ramo, stato_effettivo): I per «in apertura», A per «aperto» senza scadenza."""
    effettivo = stato_effettivo(
        riga.get("stato_bando"), riga.get("data_apertura"), riga.get("data_apertura_verificata"),
        riga.get("ora_apertura"), riga.get("data_scadenza"), riga.get("ora_scadenza"), adesso=adesso)
    if effettivo == STATO_IN_APERTURA:
        return RAMO_I, effettivo
    if effettivo == STATO_APERTO and not riga.get("data_scadenza"):
        return RAMO_A, effettivo
    return None, effettivo


def priorita_di(
    controllo: Mapping[str, Any], motivo: str | None, pagina: PaginaDaLeggere, ramo: str,
) -> int:
    lettura = _lettura_stato(controllo)
    segnale = _istante(controllo.get("segnale_aggregatore_at"))
    letta_at = _istante(controllo.get("lettura_stato_at"))
    valori = [PRIORITA["rinnovo"]]
    if motivo in PRIORITA:
        valori.append(PRIORITA[motivo])
    if segnale is not None and (letta_at is None or letta_at < segnale):
        valori.append(PRIORITA["segnale"])
    if letta_at is None and pagina.tipo != "illeggibile":
        valori.append(PRIORITA["mai_letto"])
    if _mappa(lettura.get("proposta")).get("trattenuta") == "g7e":
        valori.append(PRIORITA["seconda_lettura"])
    if ramo == RAMO_A and pagina.tipo != "illeggibile":
        valori.append(PRIORITA["aperto_da_rinnovare"])
    return max(valori)


def scegli_candidati(
    righe: Sequence[Mapping[str, Any]],
    letture: Mapping[Any, Mapping[str, Any]],
    pagine_bando: Mapping[Any, Sequence[str]],
    tabella: Any,
    adesso: datetime,
    *,
    ids: Sequence[int] = (),
) -> list[Candidato]:
    """I candidati di §5.2, ordinati per priorita' e poi per id.

    Pubblicati non fusi, nel ramo I o A secondo lo stato effettivo, con
    `prossima_lettura_at` vuota o passata. Con `ids` si prendono quelli e basta
    (la cadenza non conta: e' la rilettura a mano).
    """
    scelti: list[Candidato] = []
    for riga in righe:
        if riga.get("bando_master_id") is not None or riga.get("pubblicato") is False:
            continue
        bando_id = riga.get("id")
        if ids and bando_id not in ids:
            continue
        ramo, effettivo = ramo_di(riga, adesso)
        if ramo is None:
            continue
        controllo = letture.get(bando_id) or {}
        prossima = _istante(controllo.get("prossima_lettura_at"))
        if not ids and prossima is not None and prossima > adesso:
            continue
        pagina = pagina_da_leggere(riga, controllo, list(pagine_bando.get(bando_id) or ()), tabella)
        motivo = motivo_di(riga, controllo, adesso)
        scelti.append(Candidato(riga, controllo, ramo, effettivo or "", motivo, pagina,
                                priorita_di(controllo, motivo, pagina, ramo)))
    scelti.sort(key=lambda c: (-c.priorita, *_chiave_rotazione(c.controllo), c.riga.get("id") or 0))
    return scelti


_MAI = datetime.min.replace(tzinfo=timezone.utc)


def _chiave_rotazione(controllo: Mapping[str, Any]) -> tuple[int, datetime]:
    """La rotazione del giro 3 (§1): mai letto per primo, poi la lettura piu' vecchia."""
    letta = _istante(controllo.get("lettura_stato_at"))
    return (0, _MAI) if letta is None else (1, letta)


# --- lettura --------------------------------------------------------------------

def livello_titolo(riga: Mapping[str, Any], html: str) -> str:
    """G3v: 'alto' | 'medio' | 'basso' dalla somiglianza del titolo con le
    intestazioni della pagina (`fonte_ufficiale.somiglianza_titolo`)."""
    from . import fonte_ufficiale as fu
    valore, _ = fu.somiglianza_titolo(fu.contesto_da_bando(riga), fu.token(fu.intestazioni_pagina(html)))
    if valore >= fu.JACCARD_ALTO:
        return "alto"
    return "medio" if valore >= fu.JACCARD_MEDIO else "basso"


def lettura_modello_valida(testo: str, lettura: Mapping[str, Any] | None) -> LetturaModello | None:
    """I gate di parola sulla lettura del modello (§5.4): citazione presente,
    participio compiuto per le chiusure, niente formule potenziali, niente
    date presunte. Il modello legge lo stato; non propone mai eventi e un suo
    'aperto' non conferma (A2 vuole un estrattore)."""
    if not isinstance(lettura, Mapping):
        return None
    stato = str(lettura.get("stato") or "")
    citazione = str(lettura.get("citazione") or "")
    if stato not in STATO_LETTO or not citazione:
        return None
    if not eventi_mod.citazione_in(citazione, testo):
        return None
    if _POTENZIALE_RE.search(citazione) or e_presunta(citazione):
        return None
    if stato == "chiuso" and not _PARTICIPIO_COMPIUTO_RE.search(citazione):
        return None
    return LetturaModello(stato=stato, citazione=citazione[:300], etichetta=citazione[:80])


def _pagina_rimossa(url_richiesto: str, url_finale: str | None) -> bool:
    """Un redirect verso la radice dell'host o verso una pagina indice."""
    if not url_finale or url_finale.rstrip("/") == url_richiesto.rstrip("/"):
        return False
    percorso = urlsplit(url_finale).path or "/"
    if percorso in ("", "/"):
        return True
    from .preprocessor import _is_likely_index_url
    return bool(_is_likely_index_url(url_finale))


def _chiave_lettore(url: str | None) -> str:
    """Il lettore dedicato dell'host, o il generico."""
    host = (urlsplit(url or "").hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    chiavi = etichette_stato.LETTORI_PER_HOST.get(host)
    return chiavi[0] if chiavi else ESTRATTORE_GENERICO


async def leggi_pagina(
    candidato: Candidato,
    scarica: Callable[..., Awaitable[Any]],
    tabella: Any,
    oggi: date,
    *,
    leggi_modello: Callable[..., Awaitable[Any]] | None = None,
) -> EsitoLettura:
    """Scarica e legge la pagina scelta. Mai Firecrawl: `principale=False`.

    Il modello gira solo se c'e' (`leggi_modello`), l'estrattore non ha
    trovato niente e la pagina e' di tipo (i), (ii) o (iii).
    """
    pagina = candidato.pagina
    if pagina.tipo == "illeggibile" or not pagina.url:
        return EsitoLettura(ESITO_ILLEGGIBILE, pagina)
    redirect = "tutti" if pagina.accorciatore else "stesso_host"
    risposta = await scarica(pagina.url, principale=False, redirect=redirect)
    url_finale = getattr(risposta, "url_finale", None) or pagina.url
    stato_http = getattr(risposta, "stato", None)
    if getattr(risposta, "host_irraggiungibile", False) or stato_http is None:
        return EsitoLettura(ESITO_ERRORE_RETE, pagina, url_finale=url_finale,
                            host_irraggiungibile=bool(getattr(risposta, "host_irraggiungibile", False)))
    if pagina.accorciatore:
        # Un accorciatore vale solo se porta su un dominio verificante (5698).
        if not _leggibile(url_finale, tabella):
            return EsitoLettura(ESITO_ILLEGGIBILE, pagina, url_finale=url_finale, non_verificante=True)
        riga = candidato.riga
        tipo = ("ii" if riga.get("host_fonte") and dominio_di(url_finale) == riga.get("host_fonte")
                and riga.get("fonte_id") not in FONTI_OE else "iv")
        pagina = replace(pagina, tipo=tipo)
    precedente = _lettura_stato(candidato.controllo)
    stesso_url = precedente.get("url") in (url_finale, pagina.url)
    if stato_http in (404, 410) and precedente.get("http") in (404, 410) and stesso_url:
        return EsitoLettura(ESITO_PAGINA_RIMOSSA, pagina, url_finale=url_finale, http=stato_http)
    if not 200 <= stato_http < 300:
        prima = (int(precedente.get("da_riprovare_di_fila") or 0)
                 if precedente.get("esito") == ESITO_DA_RIPROVARE and stesso_url else 0)
        return EsitoLettura(ESITO_DA_RIPROVARE, pagina, url_finale=url_finale, http=stato_http,
                            da_riprovare_di_fila=prima + 1)
    if _pagina_rimossa(pagina.url, url_finale):
        return EsitoLettura(ESITO_PAGINA_RIMOSSA, pagina, url_finale=url_finale, http=stato_http)
    html = getattr(risposta, "html", "") or ""
    testo = getattr(risposta, "testo", "") or ""
    livello = livello_titolo(candidato.riga, html)
    esito = EsitoLettura(ESITO_LETTA, pagina, url_finale=url_finale, testo=testo, http=stato_http,
                         livello_titolo=livello)
    if pagina.tipo in ("ii", "ii-c") and livello == "basso":
        # Una pagina d'origine che non parla del bando (regione.lazio.it/documenti),
        # o un candidato (ii-c) che il resolver non ha verificato e che parla
        # d'altro: la lettura non decide (§19.4: le (ii-c) vogliono G3v medio).
        # Solo per la (ii) il bando stesso e' forse non un bando.
        esito.esito, esito.forse_non_un_bando = ESITO_NON_DECISIVA, pagina.tipo == "ii"
        return esito
    lettura = etichette_stato.leggi(html, url_finale, str(candidato.riga.get("titolo") or ""), oggi=oggi)
    esito.chiave_lettore = lettura.estrattore if lettura is not None else _chiave_lettore(url_finale)
    if lettura is not None:
        esito.lettura, esito.metodo = lettura, "estrattore"
        if lettura.stato not in STATO_LETTO:
            esito.esito = ESITO_NON_DECISIVA
        return esito
    if leggi_modello is not None and pagina.tipo in PAGINE_MODELLO:
        try:
            grezza = await leggi_modello(testo, candidato.riga)
        except Exception as e:
            logger.warning("[verifica_stato] modello non disponibile per {}: {}", candidato.riga.get("id"), e)
            grezza = None
        valida = lettura_modello_valida(testo, grezza)
        if valida is not None:
            esito.lettura, esito.metodo = valida, "modello"
            return esito
    esito.esito = ESITO_NON_DECISIVA
    return esito


async def leggi_con_collegate(
    candidato: Candidato,
    scarica: Callable[..., Awaitable[Any]],
    tabella: Any,
    oggi: date,
    *,
    leggi_modello: Callable[..., Awaitable[Any]] | None = None,
) -> EsitoLettura:
    """La pagina scelta, piu' le pagine di tipo (iii) sullo stesso host (§5.3).

    - La sorella `/avvisi/x` di un `/preavvisi/x`: se risponde e parla dello
      stesso bando, vince lei (`dalla_sorella`).
    - Il `link_collegato` di una lettura (Piemonte «Attuato» → il bando vero):
      se il lettore ci trova uno stato e la pagina parla dello stesso bando,
      vince quella lettura.
    """
    letto = await leggi_pagina(candidato, scarica, tabella, oggi, leggi_modello=leggi_modello)
    pagina = candidato.pagina
    if pagina.sorella and letto.esito in (ESITO_LETTA, ESITO_NON_DECISIVA, ESITO_PAGINA_RIMOSSA,
                                          ESITO_DA_RIPROVARE):
        sorella = await leggi_pagina(replace(candidato, pagina=PaginaDaLeggere("iii", pagina.sorella)),
                                     scarica, tabella, oggi, leggi_modello=leggi_modello)
        if sorella.esito in (ESITO_LETTA, ESITO_NON_DECISIVA) and sorella.livello_titolo != "basso":
            sorella.dalla_sorella = True
            return sorella
    collegato = getattr(letto.lettura, "link_collegato", None) if letto.metodo == "estrattore" else None
    if (collegato and letto.url_finale and dominio_di(collegato) == dominio_di(letto.url_finale)
            and collegato.rstrip("/") != letto.url_finale.rstrip("/")):
        seconda = await leggi_pagina(replace(candidato, pagina=PaginaDaLeggere("iii", collegato)),
                                     scarica, tabella, oggi)
        if seconda.esito == ESITO_LETTA and seconda.metodo == "estrattore" and seconda.livello_titolo != "basso":
            return seconda
    return letto


# --- freno ------------------------------------------------------------------------

@dataclass
class Freno:
    """Il freno per (host, estrattore) su 7 giorni mobili (§5.6).

    Scatta con almeno 5 passaggi «aperto» → «chiuso» dello stesso estrattore
    e piu' della meta' delle sue letture: un lettore che all'improvviso legge
    tutto chiuso e' piu' probabilmente rotto (sito rifatto) che sincero. Si
    aggiorna anche dentro il giro e si sblocca da solo quando la finestra
    torna sotto soglia.
    """
    adesso: datetime
    passaggi: dict[tuple[str, str], int] = field(default_factory=dict)
    letture: dict[tuple[str, str], int] = field(default_factory=dict)

    @staticmethod
    def chiave(lettura: eventi_mod.LetturaStato) -> tuple[str, str]:
        return dominio_di(lettura.url) or "", str(lettura.estrattore)

    def aggiungi(self, lettura: eventi_mod.LetturaStato,
                 precedente: eventi_mod.LetturaStato | None) -> None:
        if lettura.estrattore in (None, ESTRATTORE_GENERICO):
            return
        if lettura.at < self.adesso - timedelta(days=GIORNI_FRENO):
            return
        chiave = self.chiave(lettura)
        self.letture[chiave] = self.letture.get(chiave, 0) + 1
        if (precedente is not None and precedente.estrattore == lettura.estrattore
                and precedente.stato == "aperto" and lettura.stato == "chiuso"):
            self.passaggi[chiave] = self.passaggi.get(chiave, 0) + 1

    def frenato(self, host: str, estrattore: str | None) -> bool:
        chiave = (host or "", str(estrattore))
        passaggi, letture = self.passaggi.get(chiave, 0), self.letture.get(chiave, 0)
        return passaggi >= FRENO_MIN_PASSAGGI and letture > 0 and passaggi / letture > FRENO_QUOTA

    def frenati(self) -> frozenset[tuple[str, str]]:
        return frozenset(k for k in self.letture if self.frenato(*k))

    @classmethod
    def da_letture(cls, letture: Mapping[Any, Mapping[str, Any]], adesso: datetime) -> "Freno":
        freno = cls(adesso)
        for controllo in letture.values():
            ultima: dict[str | None, eventi_mod.LetturaStato] = {}
            for lettura in _storia(controllo):
                freno.aggiungi(lettura, ultima.get(lettura.estrattore))
                ultima[lettura.estrattore] = lettura
        return freno


# --- decisioni --------------------------------------------------------------------

def cadenza(
    candidato: Candidato, esito: EsitoLettura, *, trattenuta: str | None, g7e_in_attesa: bool,
    motivo: str | None, adesso: datetime,
) -> datetime:
    """`prossima_lettura_at` secondo §5.9 con §19.4."""
    def fra(chiave: str) -> datetime:
        return adesso + timedelta(days=CADENZA_GIORNI[chiave])

    if trattenuta in ("tetto", "freno"):
        return fra("trattenuta")
    if esito.esito == ESITO_DA_RIPROVARE:
        di_fila = max(1, esito.da_riprovare_di_fila)
        if di_fila > len(CADENZA_DA_RIPROVARE):
            return fra("da_riprovare_ripetuto")
        return adesso + timedelta(days=CADENZA_DA_RIPROVARE[di_fila - 1])
    if esito.esito in (ESITO_ERRORE_RETE, ESITO_DA_RIPROVARE, ESITO_PAGINA_RIMOSSA, ESITO_ILLEGGIBILE):
        return fra(esito.esito)
    if g7e_in_attesa:
        return fra("seconda_lettura")
    if motivo in ("smentito_dalla_fonte", "termine_passato") or candidato.controllo.get("segnale_aggregatore_at"):
        return fra("segnalato")
    if esito.esito == ESITO_NON_DECISIVA:
        nulle = int(candidato.controllo.get("letture_stato_nulle") or 0) + 1
        return fra("non_decisive_ripetute") if nulle >= 3 else fra("predefinita")
    lettura = esito.lettura
    if lettura is not None and getattr(lettura, "solo_segnale", False) and esito.metodo == "estrattore":
        stesse = [l for l in _storia(candidato.controllo) if l.estrattore == lettura.estrattore]
        uguali = [l for l in stesse[-2:]
                  if eventi_mod.norm_cit(l.etichetta) == eventi_mod.norm_cit(lettura.etichetta)]
        return fra("solo_segnale_ripetuto") if len(uguali) >= 2 else fra("segnalato")
    if lettura is not None and lettura.stato in ("chiuso", "uscito"):
        # La fonte smentisce lo stato pubblicato, letta da un estrattore o dal
        # modello: si rilegge presto (§5.9).
        return fra("segnalato")
    if lettura is not None and esito.metodo == "estrattore" and lettura.stato == "aperto":
        creato = _istante(candidato.riga.get("created_at"))
        giovane = creato is not None and adesso - creato <= timedelta(days=GIORNI_APERTO_GIOVANE)
        return fra("aperto_giovane") if giovane or getattr(lettura, "finestra", False) else fra("aperto_confermato")
    if lettura is not None and lettura.stato == "in_apertura":
        return fra("in_apertura_confermato")
    if motivo == "senza_conferma":
        return fra("senza_conferma")
    return fra("predefinita")


def termine_indicato_di(
    riga: Mapping[str, Any], tabella: Any, testo_pagina: str | None,
) -> tuple[date, str] | None:
    """Il termine indicato dalle quattro fonti, con la precedenza di §19.5."""
    host_fonte = riga.get("host_fonte")
    calendario = termine_da_calendario(
        riga.get("raw_data"), riga.get("fonte_id"),
        bool(host_fonte) and _leggibile(f"https://{host_fonte}/", tabella))
    pagina = termine_nella_pagina(testo_pagina) if testo_pagina else None
    testo = termine_nel_testo(riga.get("titolo"), riga.get("descrizione_breve"))
    aggregatore = termine_da_etichetta_oe(riga.get("raw_data"))
    return termine_per_precedenza(calendario, pagina, (testo, "testo") if testo else None, aggregatore)


def _lettura_attuale(esito: EsitoLettura, adesso: datetime) -> eventi_mod.LetturaStato | None:
    """La voce di storia della lettura di adesso: solo i lettori strutturati."""
    lettura = esito.lettura
    if lettura is None or esito.metodo != "estrattore" or not getattr(lettura, "estrattore", None):
        return None
    return eventi_mod.LetturaStato(
        adesso, lettura.estrattore, esito.url_finale or "", lettura.etichetta or "", lettura.stato,
        tuple((d.ruolo, d.data) for d in getattr(lettura, "date", ()) or () if not getattr(d, "presunta", False)))


def lettura_stato_json(
    candidato: Candidato, esito: EsitoLettura, proposta: Mapping[str, Any] | None, adesso: datetime,
) -> dict[str, Any]:
    """`lettura_stato` nella forma di §5.8, con la storia (≤5) delle letture strutturate."""
    storia = list(_storia(candidato.controllo))
    attuale = _lettura_attuale(esito, adesso)
    if attuale is not None:
        storia.append(attuale)
    lettura = esito.lettura
    termine = getattr(lettura, "termine_finale", None) if lettura is not None else None
    return {
        "pagina": esito.pagina.tipo,
        "estrattore": getattr(lettura, "estrattore", None) if esito.metodo == "estrattore" else None,
        "metodo": esito.metodo,
        "etichetta": getattr(lettura, "etichetta", None) if lettura is not None else None,
        "stato": getattr(lettura, "stato", None) if lettura is not None else None,
        "puo_chiudere": bool(getattr(lettura, "puo_chiudere", False)),
        "solo_segnale": bool(getattr(lettura, "solo_segnale", False)),
        "termine_finale": ({"data": termine.data.isoformat(),
                            "ora": termine.ora.strftime("%H:%M") if termine.ora else None,
                            "citazione": termine.citazione[:300]} if termine is not None else None),
        "esito": esito.esito,
        "http": esito.http,
        "url": esito.url_finale,
        "da_riprovare_di_fila": esito.da_riprovare_di_fila,
        "livello_titolo": esito.livello_titolo,
        "forse_non_un_bando": esito.forse_non_un_bando,
        "dalla_sorella": esito.dalla_sorella,
        "proposta": dict(proposta) if proposta else None,
        "storia": [l.come_voce() for l in storia[-STORIA_MAX:]],
    }


def _conferma_valida(candidato: Candidato, esito: EsitoLettura) -> bool:
    """Una lettura 'aperto'/'in apertura' che puo' finire in `stato_letto`.

    Mai dal generico (non dice mai 'aperto', ma per costruzione non deve
    poterlo fare); da una pagina (iv) solo con un lettore per ente, titolo
    'alto' e nessun segnale dell'aggregatore (§19.4).
    """
    lettura = esito.lettura
    if esito.metodo == "estrattore" and getattr(lettura, "estrattore", None) == ESTRATTORE_GENERICO:
        return False
    if esito.pagina.tipo == "iv":
        return (esito.metodo == "estrattore" and esito.livello_titolo == "alto"
                and not candidato.controllo.get("segnale_aggregatore_at"))
    if esito.pagina.tipo == "ii-c":
        # Un candidato non verificato conferma solo se parla del bando (§19.4).
        return esito.livello_titolo in ("alto", "medio")
    return True


def colonne_lettura(
    candidato: Candidato,
    esito: EsitoLettura,
    proposta: Mapping[str, Any] | None,
    *,
    attivo: bool,
    termine: tuple[date, str] | None,
    previsto_entro: date | None,
    prossima: datetime,
    adesso: datetime,
    testo_letto: bool = True,
) -> dict[str, Any]:
    """Le colonne di `bando_controllo` da scrivere per un candidato (§5.7, §19.4).

    `testo_letto` falso (errore di rete, da riprovare, titolo basso): la
    pagina oggi non si e' letta, quindi un termine trovato sulla pagina non si
    perde; lo sostituisce solo un calendario ufficiale (revisione avversaria).
    Con la pagina rimossa invece si perde: ricade sulle altre fonti o va a
    NULL (revisione #114).
    """
    controllo = candidato.controllo
    nulle = int(controllo.get("letture_stato_nulle") or 0)
    if esito.esito == ESITO_NON_DECISIVA:
        nulle += 1
    elif esito.esito == ESITO_LETTA:
        nulle = 0
    colonne: dict[str, Any] = {
        "lettura_stato": lettura_stato_json(candidato, esito, proposta, adesso),
        "lettura_stato_at": adesso.isoformat(),
        "prossima_lettura_at": prossima.isoformat(),
        "letture_stato_nulle": nulle,
    }
    nuovo = (termine[0].isoformat(), termine[1]) if termine else (None, None)
    attuale = ((str(controllo["termine_indicato"])[:10] if controllo.get("termine_indicato") else None),
               controllo.get("termine_indicato_fonte") or None)
    conserva = (not testo_letto and attuale[1] == "pagina" and esito.esito != ESITO_PAGINA_RIMOSSA
                and (termine is None or termine[1] != "calendario_ufficiale"))
    if nuovo != attuale and not conserva:
        # La coppia cambia se cambia la data o la fonte; il CHECK della 13 le
        # vuole insieme, o nessuna delle due.
        colonne["termine_indicato"], colonne["termine_indicato_fonte"] = nuovo
    previsto_iso = previsto_entro.isoformat() if previsto_entro else None
    if previsto_iso != (str(controllo["previsto_entro"])[:10] if controllo.get("previsto_entro") else None):
        colonne["previsto_entro"] = previsto_iso
    if not attivo:
        return colonne
    # Solo in attivo: l'esame (anche degli illeggibili) e le sei colonne.
    colonne["esaminato_attivo_at"] = adesso.isoformat()
    lettura = esito.lettura
    if esito.esito != ESITO_LETTA or lettura is None or lettura.stato not in STATO_LETTO:
        return colonne
    if lettura.stato in ("aperto", "in_apertura") and not _conferma_valida(candidato, esito):
        return colonne
    colonne.update({
        "stato_letto": STATO_LETTO[lettura.stato],
        "stato_letto_su": candidato.riga.get("stato_bando"),
        "stato_letto_at": adesso.isoformat(),
        "stato_letto_url": esito.url_finale,
        "stato_letto_citazione": (getattr(lettura, "citazione_stato", "") or lettura.etichetta or "")[:300],
        "stato_letto_metodo": esito.metodo,
    })
    return colonne


# --- I/O ------------------------------------------------------------------------

class FonteDati:
    """Le letture e le scritture del passo. I test ne passano una finta."""

    def migrazione_presente(self) -> bool: raise NotImplementedError
    def candidati(self) -> list[dict[str, Any]]: raise NotImplementedError
    def enriched(self) -> list[dict[str, Any]]: raise NotImplementedError
    def letture(self, ids: Sequence[Any] | None = None, dal: datetime | None = None
                ) -> dict[Any, dict[str, Any]]: raise NotImplementedError
    def link_bando(self, ids: Sequence[Any]) -> dict[Any, list[dict[str, Any]]]: raise NotImplementedError

    def pagine_bando(self, ids: Sequence[Any]) -> dict[Any, list[str]]:
        """Le URL delle righe `bando_link` di tipo 'pagina_bando' (pagina iv)."""
        return pagine_da_link(self.link_bando(ids))
    def tabella_domini(self) -> Any: raise NotImplementedError
    def eventi_recenti(self, bando_id: Any, dal: datetime) -> list[dict[str, Any]]: raise NotImplementedError
    def stato_attuale(self, bando_id: Any) -> str | None: raise NotImplementedError
    def scrivi_lettura(self, bando_id: Any, colonne: Mapping[str, Any]) -> bool: raise NotImplementedError
    def scrivi_ingresso(self, bando_id: Any, colonne_bando: Mapping[str, Any] | None,
                        colonne_controllo: Mapping[str, Any] | None) -> dict[str, Any]: raise NotImplementedError
    def registra(self, riga: Mapping[str, Any]) -> dict[str, Any] | None: raise NotImplementedError
    def applica(self, evento_id: Any) -> str: raise NotImplementedError
    def rendi_leggibile(self, evento_id: Any, in_aggiornamenti: bool) -> bool: raise NotImplementedError
    def testi_del_bando(self, bando_id: Any) -> dict[str, Any] | None: raise NotImplementedError
    def scrivi_run(self, riga: telemetria.PipelineRun) -> None: raise NotImplementedError
    def consumo_oggi(self) -> dict[str, float] | None: raise NotImplementedError


class FonteDatiSupabase(FonteDati):
    """Le funzioni di `db` (§14 e §19.13), chiamate per nome."""

    def migrazione_presente(self) -> bool:
        from . import db
        return bool(db.controllo.ha("bando_controllo", "lettura_stato"))

    def candidati(self) -> list[dict[str, Any]]:
        from . import db
        return db.select_da_verificare()

    def enriched(self) -> list[dict[str, Any]]:
        from . import db
        return db.select_enriched_da_leggere()

    def letture(self, ids: Sequence[Any] | None = None, dal: datetime | None = None) -> dict[Any, dict[str, Any]]:
        from . import db
        if ids is not None and not ids:
            return {}
        return db.select_letture_stato(ids=list(ids) if ids is not None else None, dal=dal)

    def link_bando(self, ids: Sequence[Any]) -> dict[Any, list[dict[str, Any]]]:
        from . import db
        link: dict[Any, list[dict[str, Any]]] = {}
        for riga in db.select_link_da_verificare(bando_ids=list(ids)) if ids else ():
            link.setdefault(riga.get("bando_id"), []).append(dict(riga))
        return link

    def tabella_domini(self) -> Any:
        # La tabella letta dal DB (righe di `dominio_ufficiale` in testa), non il seed.
        from . import fonte_ufficiale
        return fonte_ufficiale._tabella_corrente()

    def eventi_recenti(self, bando_id: Any, dal: datetime) -> list[dict[str, Any]]:
        from . import db
        return db.select_eventi(bando_id=bando_id, dal=dal.isoformat())

    def stato_attuale(self, bando_id: Any) -> str | None:
        from . import db
        righe = (db.get_supabase().table("bando").select("stato_bando")
                 .eq("id", bando_id).limit(1).execute().data) or []
        return (righe[0] or {}).get("stato_bando") if righe else None

    def scrivi_lettura(self, bando_id: Any, colonne: Mapping[str, Any]) -> bool:
        from . import db
        return db.aggiorna_lettura_stato(bando_id, colonne)

    def scrivi_ingresso(self, bando_id, colonne_bando, colonne_controllo) -> dict[str, Any]:
        from . import db
        return db.aggiorna_ingresso(bando_id, colonne_bando, colonne_controllo)

    def registra(self, riga: Mapping[str, Any]) -> dict[str, Any] | None:
        return eventi_mod.registra_via_rpc(riga)

    def applica(self, evento_id: Any) -> str:
        from . import db
        return db.applica_evento_esito(evento_id)

    def rendi_leggibile(self, evento_id: Any, in_aggiornamenti: bool) -> bool:
        """Vero solo se l'UPDATE e' partito: colonne mancanti o errore → False."""
        from . import db
        try:
            esito = db.rendi_evento_leggibile(evento_id, in_aggiornamenti=in_aggiornamenti)
        except Exception as e:                            # pragma: no cover - db non solleva
            logger.warning("[verifica_stato] evento {}: leggibile non scritto: {}", evento_id, e)
            return False
        return bool(_mappa(esito).get("scritto"))

    def testi_del_bando(self, bando_id: Any) -> dict[str, Any] | None:
        from . import db
        try:
            righe = db.select_bandi_pubblicati_contenuto(bando_ids=[bando_id])
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[verifica_stato] contenuto del bando {} illeggibile: {}", bando_id, e)
            return None
        for riga in righe:
            if riga.get("id") == bando_id:
                return {"contenuto": riga.get("contenuto"), "descrizione_breve": riga.get("descrizione_breve")}
        return None

    def scrivi_run(self, riga: telemetria.PipelineRun) -> None:
        telemetria.scrivi_pipeline_run(riga)

    def consumo_oggi(self) -> dict[str, float] | None:
        # None se la lettura fallisce (§18.5): tetto raggiunto per il modello.
        from . import db
        try:
            return db.consumo_oggi()
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[verifica_stato] consumo di oggi non leggibile: {}", e)
            return None


def _scarica_predefinito() -> Callable[..., Awaitable[Any]]:
    from .scarico import scarico_corrente, svuota
    # Cache pulita a inizio passo, host morti conservati (§5.3).
    svuota(host_morti=False)
    return scarico_corrente().scarica


def modello_da_impostazioni(impostazioni: Any, contatori: Any) -> Callable[..., Awaitable[Any]] | None:
    """La lettura dello stato col modello del classificatore, contata in bilancio.

    Una sola chiamata con lo strumento `leggi_stato`: stato e citazione. Il
    risultato passa poi dai gate di parola (`lettura_modello_valida`). None
    senza chiave o senza pacchetto: il passo legge solo con i lettori.
    """
    chiave = str(getattr(impostazioni, "anthropic_api_key", "") or "")
    if not chiave:
        return None
    try:
        import anthropic
    except Exception:                                     # pragma: no cover - ripiego
        return None
    from . import bilancio
    from .monitoraggio import MODELLO_CLASSIFICATORE
    cliente = anthropic.AsyncAnthropic(api_key=chiave)
    modello = str(getattr(impostazioni, "monitor_modello", "") or MODELLO_CLASSIFICATORE)
    listino = getattr(impostazioni, "listino_modelli", None) or {}
    strumento = {
        "name": "leggi_stato",
        "description": "Lo stato del bando come lo dichiara la pagina, con la frase esatta che lo dice.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stato": {"type": "string", "enum": ["in_apertura", "aperto", "chiuso", "uscito", "non_decisiva"]},
                "citazione": {"type": "string", "description": "La frase della pagina, copiata alla lettera."},
            },
            "required": ["stato", "citazione"],
        },
    }

    async def leggi(testo: str, riga: Mapping[str, Any]) -> Mapping[str, Any] | None:  # pragma: no cover - rete
        risposta = await cliente.messages.create(
            model=modello, max_tokens=300, tools=[strumento],
            tool_choice={"type": "tool", "name": "leggi_stato"},
            system=("Leggi lo stato del bando SOLO da una frase della pagina che lo dichiara. "
                    "Se la pagina non lo dice in modo esplicito rispondi non_decisiva."),
            messages=[{"role": "user", "content": f"Bando: {riga.get('titolo')}\n\nPagina:\n{testo[:6000]}"}],
        )
        bilancio.registra_chiamata(contatori, modello, getattr(risposta, "usage", None), listino)
        for blocco in getattr(risposta, "content", ()) or ():
            if getattr(blocco, "type", "") == "tool_use":
                return dict(getattr(blocco, "input", {}) or {})
        return None

    return leggi


def _tetti(impostazioni: Any) -> Any:
    from . import bilancio
    try:
        return bilancio.tetti_da_impostazioni(impostazioni)
    except AttributeError:
        # Impostazioni parziali (prove): nessun tetto. `Settings` li ha tutti.
        return bilancio.Tetti()


def con_bilancio(
    leggi_modello: Callable[..., Awaitable[Any]], fonte_dati: FonteDati, contatori: dict[str, Any],
    bilancio_giro: Any, tetti: Any,
) -> Callable[..., Awaitable[Any]]:
    """Il modello dietro `bilancio.verifica`, come il monitor (revisione #96).

    Prima di ogni chiamata: se un tetto e' raggiunto si salta solo il modello
    (la lettura resta ai lettori) e si conta `modello_saltato_per_bilancio`.
    Il consumo dei giri precedenti di oggi si legge una volta per giro: la riga
    di questo giro si scrive alla fine, quindi non cambierebbe.
    """
    from . import bilancio
    letto: list[dict[str, float] | None] = []

    async def leggi(testo: str, riga: Mapping[str, Any]) -> Any:
        if not letto:
            consumo = fonte_dati.consumo_oggi()
            letto.append(None if consumo is None else dict(consumo))
        # §18.5: un consumo illeggibile (None) vale tetto raggiunto: niente
        # modello, la lettura resta ai lettori per ente (gratuiti).
        esito = bilancio.verifica_con_consumo(bilancio_giro, tetti, step=STEP, consumo=letto[0])
        if not esito.consentito:
            contatori["modello_saltato_per_bilancio"] += 1
            logger.warning("[verifica_stato] modello saltato: {}", esito.motivo)
            return None
        return await leggi_modello(testo, riga)

    return leggi


def _contatori_vuoti(fase: str, modalita: str) -> dict[str, Any]:
    comuni: dict[str, Any] = {
        "modalita": modalita, "fase": fase, "candidati": 0, "lavorati": 0, "letti": 0, "illeggibili": 0,
        "errori_rete": 0, "da_riprovare": 0, "pagine_rimosse": 0, "host_irraggiungibili": 0,
        "esiti_per_estrattore": {}, "letture_non_verificanti": 0, "forse_non_bandi": 0,
        "interrotto_per_tetto_tempo": False, "costo_usd": 0.0, "crediti": 0, "motivo_saltato": None,
    }
    if fase == FASE_INGRESSO:
        comuni.update({"ingresso_letti": 0, "ingresso_date_scritte": 0, "ingresso_chiusi": 0,
                       "trattenuti": 0, "rilasciati_a_tempo": 0, "trattenuti_senza_appiglio": 0,
                       "fusi_prima_della_pubblicazione": 0})
        return comuni
    comuni.update({"confermati": 0, "smentiti": 0, "smentiti_generico": 0, "non_decisivi": 0,
                   "senza_conferma": 0, "segnalati": 0, "termini_calcolati": 0, "termini_per_fonte": {},
                   "pagine_ii_c": 0, "link_normalizzati": 0, "proposte_per_tipo": {},
                   "applicati_per_tipo": {}, "trattenute_per_freno": {},
                   "letture_scadute": 0, "eventi_non_scritti": 0, "eventi_non_leggibili": 0,
                   "prosa_non_riscritta": 0, "modello_saltato_per_bilancio": 0})
    return comuni


def _conta(mappa: dict[str, int], chiave: str) -> None:
    mappa[chiave] = mappa.get(chiave, 0) + 1


@dataclass
class _Giro:
    """Lo stato di un giro del passo, condiviso dalle funzioni della fase."""
    fonte_dati: FonteDati
    scarica: Callable[..., Awaitable[Any]]
    contatori: dict[str, Any]
    esito: dict[str, Any]
    adesso: datetime
    attivo: bool
    dry_run: bool
    orologio: Callable[[], float]
    tabella: Any = None
    leggi_modello: Callable[..., Awaitable[Any]] | None = None
    rigenerazione: Callable[..., Awaitable[Any]] | None = None
    freno: Freno | None = None

    @property
    def oggi(self) -> date:
        return adesso_roma(self.adesso).date()


# --- punto d'ingresso ---------------------------------------------------------

async def esegui_passo(
    giro: str | None,
    *,
    fase: str = FASE_CONTROLLI,
    modalita: str | None = None,
    dry_run: bool = False,
    senza_modello: bool = False,
    ids: Sequence[int] = (),
    limit: int | None = None,
    adesso: datetime | None = None,
    fonte_dati: FonteDati | None = None,
    scarica: Callable[..., Awaitable[Any]] | None = None,
    leggi_modello: Callable[..., Awaitable[Any]] | None = None,
    impostazioni: Any = None,
    pubblicabile: Callable[..., tuple[bool, str | None]] | None = None,
    rigenerazione: Callable[..., Awaitable[Any]] | None = None,
    orologio: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Un giro del passo: `{status, counters, slug_modificati, ids_da_rigenerare,
    proposte, copertura}`. Non solleva mai (un'eccezione e' `status='errore'`).

    Nessun tetto di numero (giro 3, §13): il tempo con la rotazione, il freno
    per host e la spesa del modello. `limit` resta solo per la riga di comando
    (il giro non lo passa mai). `copertura` (§1) sta in cima al risultato e nei
    contatori: candidati, lavorati, motivo `tempo` o `errore`.

    `dry_run` (la CLI): legge e decide, non scrive niente, neanche la riga di
    `pipeline_run`. `rigenerazione` e' l'adattatore della prosa del monitor
    ((bando, evento, vecchia=, nuova=, ruolo=)): si usa solo in attivo, sugli
    eventi applicati che sostituiscono una data.
    """
    orologio = orologio or time.monotonic
    inizio = orologio()
    momento = adesso or datetime.now(tz=timezone.utc)
    if impostazioni is None:
        from .settings import get_settings
        impostazioni = get_settings()
    if modalita not in (MODALITA_OMBRA, MODALITA_ATTIVO):
        modalita = getattr(impostazioni, "verifica_stato_modalita", MODALITA_OMBRA)
        modalita = modalita if modalita in (MODALITA_OMBRA, MODALITA_ATTIVO) else MODALITA_OMBRA
    fase = fase if fase in FASI else FASE_CONTROLLI
    passo = STEP_INGRESSO if fase == FASE_INGRESSO else STEP
    contatori = _contatori_vuoti(fase, modalita)
    esito: dict[str, Any] = {"status": "ok", "counters": contatori, "slug_modificati": [],
                             "ids_da_rigenerare": [], "proposte": []}
    fonte_dati = fonte_dati or FonteDatiSupabase()
    bilancio_giro = None
    try:
        if not fonte_dati.migrazione_presente():
            contatori["motivo_saltato"] = MOTIVO_MIGRAZIONE_ASSENTE
            esito["status"] = "saltato"
        else:
            giro_stato = _Giro(fonte_dati, scarica or _scarica_predefinito(), contatori, esito, momento,
                               modalita == MODALITA_ATTIVO, dry_run, orologio)
            if fase == FASE_INGRESSO:
                await _fase_ingresso(giro_stato, impostazioni, ids=ids, limit=limit, pubblicabile=pubblicabile)
            else:
                usa_modello = bool(getattr(impostazioni, "verifica_stato_usa_modello", False)) and not senza_modello
                if usa_modello:
                    from . import bilancio
                    bilancio_giro = bilancio.Contatori()
                    if leggi_modello is None:
                        leggi_modello = modello_da_impostazioni(impostazioni, bilancio_giro)
                    if leggi_modello is not None:
                        leggi_modello = con_bilancio(leggi_modello, fonte_dati, contatori, bilancio_giro,
                                                     _tetti(impostazioni))
                giro_stato.leggi_modello = leggi_modello if usa_modello else None
                giro_stato.rigenerazione = rigenerazione
                await _fase_controlli(giro_stato, impostazioni, ids=ids, limit=limit)
    except Exception as e:
        logger.exception("[verifica_stato] passo fallito: {}", e)
        esito["status"] = "errore"
        contatori["errore"] = type(e).__name__
    if esito["status"] != "saltato":
        motivo = ("errore" if esito["status"] == "errore"
                  else "tempo" if contatori.get("interrotto_per_tetto_tempo") else None)
        esito["copertura"] = contatori["copertura"] = telemetria.copertura(
            contatori["candidati"], contatori["lavorati"], motivo)
    if bilancio_giro is not None:
        contatori["costo_usd"] = round(float(bilancio_giro.usd), 6)
    # `_slug_da_notificare` della pipeline legge gli slug dentro `counters`.
    contatori["slug_modificati"] = list(esito["slug_modificati"])
    if not dry_run:
        _registra_telemetria(fonte_dati, passo, giro, contatori, status=esito["status"],
                             tempo=orologio() - inizio, slug=esito["slug_modificati"])
    return esito


async def run(
    *, giro: str | None = None, fase: str = FASE_CONTROLLI,
    rigenerazione: Callable[..., Awaitable[Any]] | None = None, **kwargs: Any,
) -> dict[str, Any]:
    """L'ingresso che `bandi_pipeline._passo_se_esiste` chiama (`run`)."""
    return await esegui_passo(giro, fase=fase, rigenerazione=rigenerazione, **kwargs)


def _registra_telemetria(fonte_dati: FonteDati, passo: str, giro: str | None, contatori: Mapping[str, Any],
                         *, status: str, tempo: float, slug: Sequence[str]) -> None:
    """La riga `pipeline_run` del passo (step 'verifica_stato' o
    'verifica_stato_ingresso'), con i contatori in cima. Non solleva."""
    interrotto = bool(contatori.get("interrotto_per_tetto_tempo"))
    if status == "errore":
        esito = telemetria.ESITO_ERRORE
    elif status == "saltato":
        esito = telemetria.ESITO_SALTATO
    else:
        esito = telemetria.esito_da_contatori(
            errori=int(contatori.get("errori_rete") or 0), lavorate=int(contatori.get("letti") or 0),
            interrotto_per_tetto=interrotto)
    try:
        riga = telemetria.PipelineRun(step=passo, giro=giro).concludi(
            durata_s=round(tempo, 3), esito=esito, contatori=dict(contatori),
            costo_usd=float(contatori.get("costo_usd") or 0.0), interrotto_per_tetto=interrotto,
            motivo=str(contatori.get("motivo_saltato") or ""), slug_modificati=tuple(slug),
        )
        logger.info("[verifica_stato] {}", telemetria.riepilogo(riga))
        fonte_dati.scrivi_run(riga)
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[verifica_stato] telemetria non scritta: {}", e)


async def _con_tetto(corutina: Awaitable[Any], secondi: float) -> Any:
    return await asyncio.wait_for(corutina, timeout=secondi)


def _conta_lettura(contatori: dict[str, Any], letto: EsitoLettura) -> None:
    """I contatori comuni alle due fasi."""
    if letto.esito == ESITO_ILLEGGIBILE:
        contatori["illeggibili"] += 1
    elif letto.esito == ESITO_ERRORE_RETE:
        contatori["errori_rete"] += 1
    elif letto.esito == ESITO_DA_RIPROVARE:
        contatori["da_riprovare"] += 1
    elif letto.esito == ESITO_PAGINA_RIMOSSA:
        contatori["pagine_rimosse"] += 1
    if letto.host_irraggiungibile:
        contatori["host_irraggiungibili"] += 1
    if letto.non_verificante:
        contatori["letture_non_verificanti"] += 1
    if letto.forse_non_un_bando:
        contatori["forse_non_bandi"] += 1
    if letto.chiave_lettore:
        # «esiti» = letture in cui il lettore ha restituito una Lettura (#98).
        voce = contatori["esiti_per_estrattore"].setdefault(letto.chiave_lettore, {"letture": 0, "esiti": 0})
        voce["letture"] += 1
        if letto.metodo == "estrattore" and letto.lettura is not None:
            voce["esiti"] += 1


async def _leggi_candidato(giro: _Giro, candidato: Candidato) -> EsitoLettura:
    try:
        return await _con_tetto(
            leggi_con_collegate(candidato, giro.scarica, giro.tabella, giro.oggi,
                                leggi_modello=giro.leggi_modello),
            TETTO_TEMPO_BANDO_S)
    except asyncio.TimeoutError:
        logger.warning("[verifica_stato] bando {}: tetto di {} s per la lettura",
                       candidato.riga.get("id"), TETTO_TEMPO_BANDO_S)
        return EsitoLettura(ESITO_ERRORE_RETE, candidato.pagina)


async def _fase_controlli(giro: _Giro, impostazioni: Any, *, ids: Sequence[int], limit: int | None) -> None:
    """I candidati in ordine di priorita' e di rotazione, finche' dura il tempo.

    Nessun tetto di letture ne' di chiusure (giro 3, §13): solo
    `VERIFICA_STATO_TETTO_S`. `limit` (solo riga di comando) conta le letture
    leggibili, come prima.
    """
    contatori = giro.contatori
    limite = None if limit is None else max(0, int(limit))
    tetto_s = float(getattr(impostazioni, "verifica_stato_tetto_s", 1800))
    inizio = giro.orologio()

    righe = giro.fonte_dati.candidati()
    ids_righe = [r.get("id") for r in righe if r.get("id") is not None]
    letture = giro.fonte_dati.letture(ids_righe)
    giro.tabella = giro.fonte_dati.tabella_domini()
    pagine = giro.fonte_dati.pagine_bando(ids_righe)
    candidati = scegli_candidati(righe, letture, pagine, giro.tabella, giro.adesso, ids=tuple(ids))
    contatori["candidati"] = len(candidati)
    scadenza = giro.adesso - timedelta(days=GIORNI_LETTURA_SCADUTA)
    contatori["letture_scadute"] = sum(
        1 for c in candidati if c.pagina.tipo != "illeggibile"
        and (_istante(c.controllo.get("lettura_stato_at")) or datetime.min.replace(tzinfo=timezone.utc)) < scadenza)
    # Il freno guarda anche i bandi gia' usciti dai candidati (chiusi in
    # questi 7 giorni): le loro letture restano in `bando_controllo`.
    finestra = dict(giro.fonte_dati.letture(None, giro.adesso - timedelta(days=GIORNI_FRENO)))
    finestra.update(letture)
    giro.freno = Freno.da_letture(finestra, giro.adesso)

    letti = 0
    for candidato in candidati:
        if giro.orologio() - inizio > tetto_s:
            contatori["interrotto_per_tetto_tempo"] = True
            break
        leggibile = candidato.pagina.tipo != "illeggibile"
        if leggibile and limite is not None and letti >= limite:
            continue
        contatori["lavorati"] += 1
        link = candidato.riga.get("link_bando")
        if isinstance(link, str) and normalizza_link_bando(link) and normalizza_link_bando(link) != [link.strip()]:
            contatori["link_normalizzati"] += 1
        if candidato.pagina.tipo == "ii-c":
            contatori["pagine_ii_c"] += 1
        letto = await _leggi_candidato(giro, candidato)
        if letto.esito != ESITO_ILLEGGIBILE:
            letti += 1
            contatori["letti"] += 1
        _conta_lettura(contatori, letto)
        _conta_controlli(contatori, candidato, letto)
        await _gestisci_candidato(giro, candidato, letto)


def _conta_controlli(contatori: dict[str, Any], candidato: Candidato, letto: EsitoLettura) -> None:
    if candidato.motivo == "senza_conferma":
        contatori["senza_conferma"] += 1
    if candidato.controllo.get("segnale_aggregatore_at"):
        contatori["segnalati"] += 1
    lettura = letto.lettura
    if letto.esito == ESITO_NON_DECISIVA:
        contatori["non_decisivi"] += 1
    if letto.esito != ESITO_LETTA or lettura is None:
        return
    if lettura.stato in ("chiuso", "uscito"):
        contatori["smentiti"] += 1
        if letto.metodo == "estrattore" and lettura.estrattore == ESTRATTORE_GENERICO:
            contatori["smentiti_generico"] += 1
    elif lettura.stato in ("aperto", "in_apertura") and _conferma_valida(candidato, letto):
        contatori["confermati"] += 1


async def _gestisci_candidato(giro: _Giro, candidato: Candidato, letto: EsitoLettura) -> None:
    """Decisioni, colonne e scrittura di un candidato."""
    contatori = giro.contatori
    attuale = _lettura_attuale(letto, giro.adesso)
    if attuale is not None and giro.freno is not None:
        precedenti = [l for l in _storia(candidato.controllo) if l.estrattore == attuale.estrattore]
        giro.freno.aggiungi(attuale, precedenti[-1] if precedenti else None)
    proposta_json, trattenuta, g7e_in_attesa = await _decidi(giro, candidato, letto, attuale)
    testo_pagina = (letto.testo if letto.esito in (ESITO_LETTA, ESITO_NON_DECISIVA)
                    and letto.livello_titolo != "basso" else None)
    termine = termine_indicato_di(candidato.riga, giro.tabella, testo_pagina)
    if termine is not None:
        contatori["termini_calcolati"] += 1
        _conta(contatori["termini_per_fonte"], termine[1])
    previsto = (etichette_stato.periodo_indicativo(candidato.riga.get("raw_data"))
                if candidato.ramo == RAMO_I else None)
    prossima = cadenza(candidato, letto, trattenuta=trattenuta, g7e_in_attesa=g7e_in_attesa,
                       motivo=candidato.motivo, adesso=giro.adesso)
    colonne = colonne_lettura(candidato, letto, proposta_json, attivo=giro.attivo, termine=termine,
                              previsto_entro=previsto, prossima=prossima, adesso=giro.adesso,
                              testo_letto=testo_pagina is not None)
    if not giro.dry_run:
        giro.fonte_dati.scrivi_lettura(candidato.riga.get("id"), colonne)


def _piu_forte(voce: Mapping[str, Any], riassunto: Mapping[str, Any]) -> bool:
    """La proposta `voce` sostituisce il riassunto? Prima le ammesse, poi la
    forza del tipo (`FORZA_PROPOSTA`): con data_verificata e apertura vince
    l'apertura, che e' cio' che il report deve dire."""
    def chiave(v: Mapping[str, Any]) -> tuple[bool, int]:
        return bool(v.get("ammessa")), FORZA_PROPOSTA.get(str(v.get("tipo")), 0)
    return chiave(voce) > chiave(riassunto)


def _esito_proposta(ammessa: bool, trattenuta: str | None) -> str:
    if trattenuta in ("tetto", "freno", "g7e"):
        return "in_coda"
    return "ammessa" if ammessa else "scartata"


async def _decidi(
    giro: _Giro, candidato: Candidato, letto: EsitoLettura, attuale: eventi_mod.LetturaStato | None,
) -> tuple[dict[str, Any] | None, str | None, bool]:
    """Proposte, gate e (in attivo) registrazione. Ritorna (proposta per
    `lettura_stato`, trattenuta per tetto o freno, seconda lettura in attesa).

    Solo le letture di un lettore strutturato propongono: il modello e il
    generico no (§5.4, §5.6). In ombra una proposta non si registra MAI.
    """
    lettura = letto.lettura
    if letto.esito != ESITO_LETTA or attuale is None:
        return None, None, False
    contatori = giro.contatori
    riga = candidato.riga
    ctx = eventi_mod.ContestoVerifica(
        bando_id=riga.get("id"), stato=riga.get("stato_bando"),
        data_apertura=_data(riga.get("data_apertura")), data_scadenza=_data(riga.get("data_scadenza")),
        data_pubblicazione=_data(riga.get("data_pubblicazione")),
        apertura_verificata=bool(riga.get("data_apertura_verificata")),
        scadenza_verificata=bool(riga.get("data_scadenza_verificata")),
        pagina_tipo=letto.pagina.tipo, url_finale=letto.url_finale or "", testo_pagina=letto.testo,
        livello_titolo=letto.livello_titolo, lettura=attuale, storia=_storia(candidato.controllo),
        tabella_domini=giro.tabella, adesso=giro.adesso,
    )
    proposte = eventi_mod.proposte_verifica(candidato.ramo, lettura, ctx)
    if not proposte:
        return None, None, False
    # G9 sullo stato riletto adesso; G5 e G8 sugli eventi degli ultimi 30
    # giorni. Anche in ombra (sono GET): l'ombra deve decidere come l'attivo.
    ctx = replace(ctx, proposte_insieme=tuple(proposte),
                  stato=giro.fonte_dati.stato_attuale(riga.get("id")) or ctx.stato,
                  eventi_recenti=tuple(giro.fonte_dati.eventi_recenti(
                      riga.get("id"), giro.adesso - timedelta(days=GIORNI_EVENTI_RECENTI))))
    riassunto: dict[str, Any] | None = None
    trattenuta_giro: str | None = None
    g7e_in_attesa = False
    applicati, prosa_vecchia = 0, False
    host = dominio_di(letto.url_finale or "") or ""
    for proposta in proposte:
        giudizio = eventi_mod.valuta_verifica(proposta, ctx)
        falliti = tuple(g for g, _ in giudizio.falliti)
        trattenuta: str | None = None
        if not giudizio.ammesso and falliti == ("G7e",):
            trattenuta, g7e_in_attesa = "g7e", True
        if giudizio.ammesso:
            _conta(contatori["proposte_per_tipo"], proposta.tipo)
            # Nessun tetto di chiusure per giro (giro 3, §13): resta il freno
            # per host ed estrattore.
            if proposta.tipo == "chiusura" and giro.freno is not None \
                    and giro.freno.frenato(host, lettura.estrattore):
                trattenuta = "freno"
                _conta(contatori["trattenute_per_freno"], lettura.estrattore)
            if trattenuta is None and not giro.attivo:
                trattenuta = "ombra"
        if trattenuta in ("tetto", "freno"):
            trattenuta_giro = trattenuta
        voce = {"tipo": proposta.tipo, "campo": proposta.campo,
                "valore_dopo": {k: (v.isoformat() if isinstance(v, date) else v)
                                for k, v in proposta.valore_dopo.items()},
                "gate": eventi_mod.gate_verifica(giudizio, proposta), "trattenuta": trattenuta,
                "ammessa": giudizio.ammesso, "in_aggiornamenti": proposta.in_aggiornamenti}
        if riassunto is None or _piu_forte(voce, riassunto):
            riassunto = voce
        if len(giro.esito["proposte"]) < PROPOSTE_MAX:
            giro.esito["proposte"].append({
                "bando_id": riga.get("id"), "tipo": proposta.tipo, "campo": proposta.campo,
                "gate": {"superati": list(giudizio.superati), "falliti": list(falliti)},
                "esito": _esito_proposta(giudizio.ammesso, trattenuta), "trattenuta": trattenuta,
            })
        if not giudizio.ammesso or trattenuta is not None or not giro.attivo or giro.dry_run:
            continue
        applicato, prosa_ok = await _registra_e_applica(giro, candidato, proposta, ctx, giudizio)
        applicati += applicato
        prosa_vecchia = prosa_vecchia or (applicato and not prosa_ok)
    slug = riga.get("slug")
    # IndexNow solo se la pagina dice per intero cio' che le colonne dicono:
    # basta un evento con la prosa rimasta vecchia per tenere fuori lo slug.
    if applicati and not prosa_vecchia and slug and slug not in giro.esito["slug_modificati"]:
        giro.esito["slug_modificati"].append(slug)
    return riassunto, trattenuta_giro, g7e_in_attesa


async def _registra_e_applica(
    giro: _Giro, candidato: Candidato, proposta: eventi_mod.Proposta,
    ctx: eventi_mod.ContestoVerifica, giudizio: eventi_mod.Giudizio,
) -> tuple[bool, bool]:
    """In attivo: RPC → applica → leggibile, poi la prosa (§5.6).

    Ritorna (applicato, prosa riallineata).
    """
    contatori, esito, riga = giro.contatori, giro.esito, candidato.riga
    riga_evento = eventi_mod.riga_verifica(proposta, ctx, giudizio, modalita=MODALITA_ATTIVO)
    registrato = giro.fonte_dati.registra(riga_evento)
    if not registrato or registrato.get("id") is None:
        # Nessun ripiego su un INSERT diretto: l'evento non si scrive (§5.6).
        contatori["eventi_non_scritti"] += 1
        return False, True
    if registrato.get("nuovo") is not True:
        return False, True
    if giro.fonte_dati.applica(registrato["id"]) != "applicato":
        return False, True
    if not giro.fonte_dati.rendi_leggibile(registrato["id"], proposta.in_aggiornamenti):
        # Applicato ma senza cursore (anche per colonne mancanti): la pagina e'
        # cambiata, il box no. Lo ripesca `applica-eventi --ids <id> --attivo`.
        contatori["eventi_non_leggibili"] += 1
        logger.warning("[verifica_stato] evento {} applicato ma non leggibile (bando {})",
                       registrato["id"], riga.get("id"))
    _conta(contatori["applicati_per_tipo"], proposta.tipo)
    if riga.get("id") not in esito["ids_da_rigenerare"]:
        esito["ids_da_rigenerare"].append(riga.get("id"))
    if await _riallinea_prosa(giro, riga, dict(riga_evento, id=registrato["id"]), proposta):
        return True, True
    contatori["prosa_non_riscritta"] += 1
    return True, False


async def _riallinea_prosa(
    giro: _Giro, riga: Mapping[str, Any], riga_evento: Mapping[str, Any], proposta: eventi_mod.Proposta,
) -> bool:
    """La prosa dice la data applicata? Vero anche quando non c'e' niente da
    riscrivere: un evento di stato, o una data nuova dove prima non ce n'era
    (la prosa non la diceva). Stessa regola e stesso adattatore del monitor."""
    campo = proposta.campo
    if campo not in ("data_apertura", "data_scadenza"):
        return True
    nuova, vecchia = _data(proposta.valore_dopo.get(campo)), _data(riga.get(campo))
    if nuova is None or vecchia is None or nuova == vecchia:
        return True
    if giro.rigenerazione is None:
        return False
    from .monitoraggio import _da_rigenerare, _esito_rigenerazione, _rigenerazione_riuscita
    preparata = _da_rigenerare(giro.fonte_dati, riga, giro.rigenerazione)
    if preparata is None:
        return False
    corrente, adattatore = preparata
    try:
        prodotto = await adattatore(corrente, dict(riga_evento), vecchia=vecchia, nuova=nuova,
                                    ruolo="apertura" if campo == "data_apertura" else "scadenza")
    except Exception as e:
        logger.warning("[verifica_stato] rigenerazione del bando {} fallita: {}", riga.get("id"), e)
        return False
    return _rigenerazione_riuscita(_esito_rigenerazione(prodotto))


async def _fase_ingresso(
    giro: _Giro, impostazioni: Any, *, ids: Sequence[int], limit: int | None,
    pubblicabile: Callable[..., tuple[bool, str | None]] | None,
) -> None:
    """Le righe `enriched`: lettore per ente, senza modello (§5.10, §19.4).

    In ombra non tocca MAI le colonne di `bando`: solo `bando_controllo`
    (storia delle letture, `trattenuto_dal`) e i contatori. Ogni scrittura passa
    da `scrivi_ingresso` (`db.aggiorna_ingresso`), che rifiuta le righe
    pubblicate.
    """
    contatori = giro.contatori
    sosta_giri = int(getattr(impostazioni, "ingresso_sosta_giri", 4))
    from .ingresso import senza_appiglio
    if pubblicabile is None:
        from .ingresso import pubblicabile as _pubblicabile
        pubblicabile = _pubblicabile
    inizio = giro.orologio()
    tutte = [r for r in giro.fonte_dati.enriched()
             if r.get("pubblicato") is not True and (not ids or r.get("id") in ids)]
    if not tutte:
        return
    id_tutte = [r.get("id") for r in tutte]
    letture = giro.fonte_dati.letture(id_tutte)
    link = giro.fonte_dati.link_bando(id_tutte)
    # Le righe senza appiglio (nessun link, compresi i `bando_link`, e nessuna
    # data) non hanno niente da leggere: restano ferme, si contano a parte e
    # non occupano il tetto delle letture (revisione avversaria).
    righe = []
    for riga in tutte:
        if senza_appiglio(riga, {**(letture.get(riga.get("id")) or {}), "bando_link": link.get(riga.get("id"), [])}):
            contatori["trattenuti"] += 1
            contatori["trattenuti_senza_appiglio"] += 1
        else:
            righe.append(riga)
    # Nessun tetto di numero (giro 3, §13): il tempo, con la rotazione. Prima
    # chi non e' mai stato letto, poi la lettura piu' vecchia, poi l'id.
    righe.sort(key=lambda r: (*_chiave_rotazione(letture.get(r.get("id")) or {}), r.get("id") or 0))
    if limit is not None:
        # Solo da riga di comando.
        righe = righe[:max(0, int(limit))]
    contatori["candidati"] = len(righe)
    if not righe:
        return
    giro.tabella = giro.fonte_dati.tabella_domini()
    pagine = pagine_da_link(link)
    for riga in righe:
        if giro.orologio() - inizio > TETTO_TEMPO_INGRESSO_S:
            contatori["interrotto_per_tetto_tempo"] = True
            break
        bando_id = riga.get("id")
        contatori["lavorati"] += 1
        controllo = dict(letture.get(bando_id) or {})
        pagina = pagina_da_leggere(riga, controllo, list(pagine.get(bando_id) or ()), giro.tabella)
        candidato = Candidato(riga, controllo, RAMO_A, STATO_APERTO, None, pagina, 0)
        letto = await _leggi_candidato(giro, candidato)
        if letto.esito != ESITO_ILLEGGIBILE:
            contatori["letti"] += 1
            contatori["ingresso_letti"] += 1
        _conta_lettura(contatori, letto)
        colonne_bando = colonne_ingresso(riga, letto)
        controllo_nuovo: dict[str, Any] = {
            "lettura_stato": lettura_stato_json(candidato, letto, None, giro.adesso),
            "lettura_stato_at": giro.adesso.isoformat(),
        }
        # La sosta si decide sulla riga come sara' dopo questa lettura.
        riga_dopo = {**riga, **colonne_bando} if giro.attivo else dict(riga)
        _, motivo = pubblicabile(riga_dopo, {**controllo, **controllo_nuovo, "bando_link": link.get(bando_id, [])},
                                 giro.adesso, sosta_giri=sosta_giri)
        if motivo == "sosta":
            contatori["trattenuti"] += 1
            if not controllo.get("trattenuto_dal"):
                controllo_nuovo["trattenuto_dal"] = giro.adesso.isoformat()
        elif motivo == "rilasciato_a_tempo":
            contatori["rilasciati_a_tempo"] += 1
        elif motivo == "senza_appiglio":
            contatori["trattenuti"] += 1
            contatori["trattenuti_senza_appiglio"] += 1
        if giro.dry_run:
            continue
        risultato = giro.fonte_dati.scrivi_ingresso(
            bando_id, colonne_bando if giro.attivo and colonne_bando else None, controllo_nuovo)
        if giro.attivo and colonne_bando and _mappa(risultato).get("bando"):
            if "data_scadenza" in colonne_bando:
                contatori["ingresso_date_scritte"] += 1
            if colonne_bando.get("stato_bando") == "chiuso":
                contatori["ingresso_chiusi"] += 1


def colonne_ingresso(riga: Mapping[str, Any], letto: EsitoLettura) -> dict[str, Any]:
    """Le colonne di `bando` che la fase ingresso scriverebbe (§5.7): la
    scadenza se manca e «chiuso» se l'etichetta puo' chiudere. Solo da un
    lettore per ente, su una pagina che ammette eventi e parla del bando."""
    lettura = letto.lettura
    if (letto.esito != ESITO_LETTA or lettura is None or letto.metodo != "estrattore"
            or lettura.estrattore == ESTRATTORE_GENERICO
            or letto.pagina.tipo not in eventi_mod.PAGINE_CON_EVENTI or letto.livello_titolo == "basso"):
        return {}
    colonne: dict[str, Any] = {}
    termine = getattr(lettura, "termine_finale", None)
    if termine is not None and not riga.get("data_scadenza"):
        colonne["data_scadenza"] = termine.data.isoformat()
        if termine.ora is not None:
            colonne["ora_scadenza"] = termine.ora.strftime("%H:%M")
    if lettura.stato == "chiuso" and getattr(lettura, "puo_chiudere", False):
        colonne["stato_bando"] = "chiuso"
    return colonne


# --- report e verita' nota (§13, §19.12) ---------------------------------------------

def esito_report(controllo: Mapping[str, Any]) -> str:
    """L'esito di un bando nel vocabolario di `ESITI_VERITA`, dalla sua lettura."""
    lettura = _lettura_stato(controllo)
    proposta = _mappa(lettura.get("proposta"))
    if lettura.get("forse_non_un_bando"):
        return "forse_non_un_bando"
    if lettura.get("dalla_sorella"):
        return "dalla_sorella"
    if proposta.get("ammessa") or proposta.get("trattenuta") in ("ombra", "tetto", "freno", "g7e"):
        tipo = str(proposta.get("tipo") or "")
        if tipo == "rettifica":
            valore = _mappa(proposta.get("valore_dopo")).get("data_scadenza")
            return f"rettifica:{str(valore)[:10]}" if valore else "rettifica"
        if tipo:
            return tipo
    stato = lettura.get("stato")
    if lettura.get("esito") == ESITO_LETTA:
        if stato == "chiuso":
            return "smentito"
        if stato == "uscito":
            return "uscito"
        if stato in ("aperto", "in_apertura"):
            return "confermato"
    if controllo.get("termine_indicato"):
        return f"termine_indicato:{str(controllo['termine_indicato'])[:10]}"
    if controllo.get("segnale_aggregatore"):
        return "segnalato"
    if lettura.get("pagina") == "illeggibile" or lettura.get("esito") == ESITO_ILLEGGIBILE:
        return "illeggibile"
    return "non_decisiva"


def righe_report(
    righe: Sequence[Mapping[str, Any]],
    letture: Mapping[Any, Mapping[str, Any]],
    *,
    adesso: datetime | None = None,
    ramo: str | None = None,
    motivo: str | None = None,
) -> list[dict[str, Any]]:
    """Una riga per candidato con le chiavi di §13 (pura: le righe le legge il chiamante).

    `ramo`: 'aperto' | 'apertura'; `motivo`: uno dei motivi di `stato_da_verificare`.
    """
    momento = adesso or datetime.now(tz=timezone.utc)
    uscita = []
    for riga in righe:
        ramo_riga, effettivo = ramo_di(riga, momento)
        if ramo_riga is None:
            continue
        if (ramo == "aperto" and ramo_riga != RAMO_A) or (ramo == "apertura" and ramo_riga != RAMO_I):
            continue
        controllo = letture.get(riga.get("id")) or {}
        motivo_riga = motivo_di(riga, controllo, momento)
        if motivo and motivo_riga != motivo:
            continue
        lettura = _lettura_stato(controllo)
        proposta = _mappa(lettura.get("proposta"))
        uscita.append({
            "id": riga.get("id"),
            "stato_effettivo": effettivo,
            "motivo": motivo_riga,
            "pagina": lettura.get("pagina"),
            "metodo": lettura.get("metodo"),
            "estrattore": lettura.get("estrattore"),
            "etichetta": lettura.get("etichetta"),
            "termine_indicato": controllo.get("termine_indicato"),
            "termine_indicato_fonte": controllo.get("termine_indicato_fonte"),
            "proposta": proposta.get("tipo"),
            "trattenuta": proposta.get("trattenuta"),
            "forse_non_un_bando": bool(lettura.get("forse_non_un_bando")),
            "esito": esito_report(controllo),
        })
    return uscita


def _confermato_da_stato(atteso: str, stato: Any) -> bool:
    """Lo stato effettivo e' gia' quello che l'esito atteso annunciava?"""
    tipo = str(atteso or "").split(":", 1)[0]
    return tipo in ESITO_STATO_ATTESO and stato == ESITO_STATO_ATTESO[tipo]


def confronta_verita(
    report: Sequence[Mapping[str, Any]], verita: Mapping[int, str] = VERITA_NOTA,
    *, stati: Mapping[Any, Any] | None = None,
) -> list[dict[str, Any]]:
    """I difformi `{id, atteso, trovato}`.

    Un id assente dal report e' difforme, salvo che sia uscito dai candidati
    perche' il suo stato effettivo (`stati`, da `stati_effettivi`) e' gia'
    quello atteso: per esempio atteso «chiusura» e stato `chiuso` (661135,
    chiuso dal job orario). Quelli li conta `confermati_da_stato`.
    """
    per_id = {r.get("id"): r.get("esito") for r in report}
    stati = stati or {}
    return [{"id": bando_id, "atteso": atteso, "trovato": per_id.get(bando_id)}
            for bando_id, atteso in sorted(verita.items())
            if per_id.get(bando_id) != atteso
            and not (bando_id not in per_id and _confermato_da_stato(atteso, stati.get(bando_id)))]


def confermati_da_stato(
    report: Sequence[Mapping[str, Any]], verita: Mapping[int, str] = VERITA_NOTA,
    *, stati: Mapping[Any, Any] | None = None,
) -> list[dict[str, Any]]:
    """`{id, atteso, stato}` degli id usciti dai candidati con lo stato atteso (§13)."""
    presenti = {r.get("id") for r in report}
    stati = stati or {}
    return [{"id": bando_id, "atteso": atteso, "stato": stati.get(bando_id)}
            for bando_id, atteso in sorted(verita.items())
            if bando_id not in presenti and _confermato_da_stato(atteso, stati.get(bando_id))]


#: Le colonne che servono a `stato_effettivo`.
COLONNE_STATO_EFFETTIVO: tuple[str, ...] = (
    "id", "stato_bando", "data_apertura", "data_apertura_verificata", "ora_apertura",
    "data_scadenza", "ora_scadenza",
)


def stati_effettivi(
    ids: Sequence[Any],
    *,
    leggi: Callable[[list[Any]], Sequence[Mapping[str, Any]]] | None = None,
    adesso: datetime | None = None,
) -> dict[Any, str | None]:
    """`{id: stato effettivo}` dei bandi dati, calcolato con `stato_effettivo`.

    Solo lettura (una GET su `bando` per blocchi di id, come `stato_attuale`);
    `leggi(ids)` la sostituisce nei test. Un id che non si legge resta fuori:
    per `confronta_verita` vale ancora difforme.
    """
    elenco = [i for i in dict.fromkeys(ids) if i is not None]
    if not elenco:
        return {}
    if leggi is None:
        def leggi(blocco: list[Any]) -> Sequence[Mapping[str, Any]]:
            from . import db
            return (db.get_supabase().table("bando").select(",".join(COLONNE_STATO_EFFETTIVO))
                    .in_("id", blocco).execute().data) or []
    momento = adesso or datetime.now(tz=timezone.utc)
    stati: dict[Any, str | None] = {}
    for inizio in range(0, len(elenco), 100):
        for riga in leggi(elenco[inizio:inizio + 100]):
            stati[riga.get("id")] = stato_effettivo(
                riga.get("stato_bando"), riga.get("data_apertura"), riga.get("data_apertura_verificata"),
                riga.get("ora_apertura"), riga.get("data_scadenza"), riga.get("ora_scadenza"),
                adesso=momento)
    return stati


__all__ = [
    "CADENZA_GIORNI", "Candidato", "ESITI_VERITA", "ESITO_STATO_ATTESO", "EsitoLettura",
    "FASE_CONTROLLI", "FASE_INGRESSO",
    "FonteDati", "FonteDatiSupabase", "Freno", "LetturaModello", "PRIORITA", "PaginaDaLeggere", "STEP",
    "STEP_INGRESSO", "VERITA_NOTA", "cadenza", "colonne_ingresso", "colonne_lettura",
    "confermati_da_stato", "confronta_verita",
    "esegui_passo", "esito_report", "leggi_con_collegate", "leggi_pagina", "lettura_modello_valida",
    "normalizza_link_bando", "pagina_da_leggere", "righe_report", "run", "scegli_candidati",
    "stati_effettivi",
    "termine_indicato_di",
]
