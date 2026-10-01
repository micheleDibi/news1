# -*- coding: utf-8 -*-
"""Gemelli, doppioni e scelta del master (piano §5 passo 2, §14, §16.2 M9).

Perche' esiste
--------------
Lo stesso bando entra nel DB piu' volte: dall'aggregatore e dal sito dell'ente
(le 24 coppie a URL identico, il caso guida 942936 ↔ 905315), da due giri dello
stesso calendario, o con un URL cambiato dalla fonte. Riconoscerlo vale un
passo intero della cascata del resolver — la riga riconosciuta eredita la fonte
ufficiale senza spendere un credito — e vale i 301 verso il master.

La regola che tiene insieme tutto e' una sola: **fonde solo cio' che e' certo**.

  * `criteri_esatti` produce corrispondenze che autorizzano una fusione:
    URL normalizzato identico, stessa chiave esterna, stesso numero di atto
    sullo stesso dominio. Il criterio dell'URL **non** richiede la stessa fonte
    (§16.2 M9: le 24 coppie misurate e il caso guida sono tutte cross-fonte),
    ma pretende che almeno un lato della coincidenza sia un `link_bando`: due
    lotti dello stesso ente hanno la stessa `fonte_ufficiale_url` e non sono
    lo stesso bando;
  * `possibili_doppioni` produce **proposte** e nient'altro: il fuzzy sui titoli
    normalizzati da 0,98 su «edizione 2025» contro «edizione 2026» e su «lotto
    1» contro «lotto 2», che doppioni non sono. Per questo `Proposta.applicato`
    esiste, vale sempre False e non c'e' nessuna funzione che lo cambi: chi
    volesse fondere un doppione fuzzy deve passare da una persona.

Modulo puro: nessuna rete, nessun DB. Le righe sono i dizionari che arrivano
da PostgREST (o i record composti da `bando_runner._build_record`).
"""
from __future__ import annotations

import difflib
import math
import re
from collections import Counter
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from .date_validation import extract_date_from_quote
from .dominio_ufficiale import dominio_di, e_aggregatore, registrabile
from .impronte import normalizza_url
from .normalize import normalize_for_canonical

SOGLIA_FUZZY = 0.92


# --- memoizzazione delle normalizzazioni ------------------------------------
#
# Il confronto fra gemelli e' quadratico per costruzione: `fondi-doppioni`
# guarda ogni riga contro tutte le altre, e su 2 104 pubblicati sono ~4,4
# milioni di coppie. Titolo, ente, host e URL della riga «altra» venivano
# normalizzati una volta **per coppia**, cioe' 2 104 volte ciascuno, invece che
# una volta per riga.
#
# Le tre funzioni normalizzatrici sono pure (stringa -> stringa, nessuno stato,
# nessun I/O): memoizzarle non cambia un solo risultato, e le stringhe distinte
# restano quante sono le righe, quindi la cache costa quanto il corpus.

@lru_cache(maxsize=16384)
def _canonico(testo: str) -> str:
    """`normalize_for_canonical` memoizzata."""
    return normalize_for_canonical(testo)


@lru_cache(maxsize=32768)
def _url_normalizzato(url: str | None) -> str | None:
    """`impronte.normalizza_url` memoizzata."""
    return normalizza_url(url)


@lru_cache(maxsize=16384)
def _host(url: str) -> str:
    """`dominio_ufficiale.dominio_di` memoizzata, senza il `None`."""
    return dominio_di(url) or ""


# Le famiglie di fonte che sanno dire un identificativo stabile (§14).
FAMIGLIA_OE = "obiettivo_europa"
FAMIGLIA_INCENTIVI = "incentivi_gov_it"
FAMIGLIA_ITALIA_DOMANI = "italia_domani"
FAMIGLIA_CALENDARIO = "calendario"

# Fonti aggregatore del DB bandi: servono solo a riconoscere la famiglia di un
# record che non porta `raw_data['source']` (le righe vecchie).
FONTI_OE: frozenset[int] = frozenset({449, 450, 451})

_TIPI_ATTO = (
    (re.compile(r"^d\.?d\.?g", re.I), "ddg"),
    (re.compile(r"^d\.?p\.?g\.?r", re.I), "dpgr"),
    (re.compile(r"^d\.?g\.?r", re.I), "dgr"),
    (re.compile(r"^d\.?d", re.I), "dd"),
    (re.compile(r"^determin", re.I), "determina"),
    (re.compile(r"^decret", re.I), "decreto"),
    (re.compile(r"^deliber", re.I), "delibera"),
)

_RE_ATTO = re.compile(
    r"\b(?P<tipo>d\.?d\.?g\.?|d\.?p\.?g\.?r\.?|d\.?g\.?r\.?|d\.?d\.?|determin\w*|"
    r"decret\w*|deliber\w*)\s*"
    r"(?:dirigenzial\w*\s*)?(?:n[°.\s]*)?\s*"
    r"(?P<numero>\d{1,7})"
    r"(?:\s*/\s*(?P<anno1>\d{4}))?"
    r"(?:\s+del\s+(?P<giorno>\d{1,2})[/.\-](?P<mese>\d{1,2})[/.\-](?P<anno2>\d{2,4}))?",
    re.IGNORECASE,
)

# Token che, se differiscono, spiegano da soli perche' due titoli quasi uguali
# sono due bandi diversi. Non cambiano l'esito (il fuzzy non fonde mai): finiscono
# nel report, che e' dove qualcuno deve poter capire in due secondi.
_RE_ANNO = re.compile(r"\b(?:19|20)\d{2}\b")

# Le parole che numerano le parti di uno stesso avviso (revisione avversaria
# del 01/10, ciclo 2): «Lotto n. 1» e «Lotto n. 2», «Sportello 1» e
# «Sportello 2», «I edizione» e «II edizione» sono due bandi, non due copie.
# Forma -> famiglia, cosi' «lotti 1 e 2» si confronta con «lotto 1».
_FAMIGLIE_NUMERATE: tuple[tuple[str, str], ...] = (
    (r"lott[oi]|lot", "lotto"),
    (r"edizion[ei]", "edizione"),
    (r"sportell[oi]", "sportello"),
    (r"misur[ae]", "misura"),
    (r"azion[ei]", "azione"),
    (r"fas[ei]", "fase"),
    (r"line(?:a|e|ee)", "linea"),
    (r"ass[ei]", "asse"),
    (r"intervent[oi]", "intervento"),
    (r"modul[oi]", "modulo"),
    (r"annualit\w*", "annualita"),
    (r"finestr[ae]", "finestra"),
    (r"tranches?", "tranche"),
)
_PAROLA_NUMERATA = "|".join(forma for forma, _ in _FAMIGLIE_NUMERATE)
# L'avviso numerato («Avviso n. 3/2026»): il numero senza l'anno, che si
# confronta gia' con gli anni. Ha una sua espressione perche' la barra qui non
# separa un elenco.
FAMIGLIA_AVVISO = "avviso"
# I codici di programma: un titolo li cita, l'altro (spesso quello redazionale)
# li tace, e la coppia resta la stessa (la riga di calendario 5596/40744 ha
# «(Azione 4.6.1)» in un solo titolo). Contano solo se nominati in tutti e
# due i titoli. Lotto, edizione, sportello, annualita', finestra e tranche
# dicono quale istanza dell'avviso e': contano anche da una parte sola.
_FAMIGLIE_SOLO_SE_IN_ENTRAMBI: frozenset[str] = frozenset({
    "misura", "azione", "fase", "linea", "asse", "intervento", "modulo", FAMIGLIA_AVVISO})
# Le famiglie in cui una lettera maiuscola e' un numero («Lotto A», «Linea
# B», «Misura A/B»). Per le altre «A» sarebbe una preposizione.
_FAMIGLIE_CON_LETTERA: frozenset[str] = frozenset({"lotto", *_FAMIGLIE_SOLO_SE_IN_ENTRAMBI})
# I plurali: davanti a loro «I» e' l'articolo («I lotti»), non il numero romano.
_RE_PLURALE_NUMERATO = re.compile(
    r"^(?:lotti|edizioni|sportelli|misure|azioni|fasi|linee|assi|interventi|moduli|"
    r"finestre|tranches)$", re.I)
_ORDINALI_IN_LETTERE: dict[str, int] = {
    "primo": 1, "prima": 1, "secondo": 2, "seconda": 2, "terzo": 3, "terza": 3,
    "quarto": 4, "quarta": 4, "quinto": 5, "quinta": 5, "sesto": 6, "sesta": 6,
    "settimo": 7, "settima": 7, "ottavo": 8, "ottava": 8, "nono": 9, "nona": 9,
    "decimo": 10, "decima": 10,
}
# Romani solo maiuscoli: in minuscolo «vi», «di»... sono parole.
_ROMANO = r"(?-i:[IVX]{1,6})(?![\w'’])"
_ARABO = r"\d{1,4}(?:\.\d{1,3})*"
_LETTERA = r"(?-i:[A-Z])(?![\w'’])"
# Dopo la parola: «Lotto 2», «Lotto n. 2», «Lotto nr.2», «Fase II», «Sportello
# 2°», «Linea B», «Linea di intervento A», «Asse prioritario 1», gli elenchi
# «lotti 1/2», «1, 2 e 3», «A/B». Le lettere valgono solo nelle
# `_FAMIGLIE_CON_LETTERA`.
_ELEMENTO = rf"(?:{_ARABO}(?:\s*[°ºª^])?|{_ROMANO}|{_LETTERA})"
_QUALIFICA = (r"(?:\s+(?:di|d['’])\s*(?:intervento|azione|attivit\w+|finanziamento)\b"
              r"|\s+prioritari[oa]\b)?")
_RE_NUMERATO_DOPO = re.compile(
    rf"\b(?P<parola>{_PAROLA_NUMERATA})\b{_QUALIFICA}\s*"
    r"(?:(?:numero|num|nr|n)\s*\.?\s*[°º]?\s*)?"
    rf"(?P<numeri>{_ELEMENTO})"
    rf"(?P<altri>(?:\s*(?:/|,|&|\be\b)\s*{_ELEMENTO})*)",
    re.I,
)
_RE_ALTRO = re.compile(rf"\s*(?:/|,|&|\be\b)\s*(?P<elemento>{_ELEMENTO})", re.I)
_RE_AVVISO = re.compile(
    r"\bavvis[oi](?:\s+pubblic[oi])?\s*(?:(?:numero|num|nr|n)\s*\.?\s*[°º]?\s*)?"
    r"(?P<numero>\d{1,4})(?:\s*/\s*(?:\d{4}|\d{2}))?\b",
    re.I,
)
# Prima della parola: «I edizione», «2ª edizione», «1° sportello», «seconda
# finestra».
_RE_NUMERATO_PRIMA = re.compile(
    rf"(?<![\w'])(?P<numero>\d{{1,3}}\s*[°ºª^]|\d{{1,3}}[ao](?=\s)|{_ROMANO}|"
    rf"{'|'.join(_ORDINALI_IN_LETTERE)})\s+(?P<parola>{_PAROLA_NUMERATA})\b",
    re.I,
)
_VALORI_ROMANI = {"I": 1, "V": 5, "X": 10}


# --- tipi -------------------------------------------------------------------

@dataclass(frozen=True)
class Corrispondenza:
    """Un gemello certo: autorizza `bando_fondi`, in modalita' attiva."""
    bando_id: Any
    criterio: str                      # url | chiave_esterna | atto | riga_calendario
    dettaglio: str = ""
    applicabile: bool = True


@dataclass(frozen=True)
class Proposta:
    """Un possibile doppione. Non e' mai applicabile: e' una riga di report."""
    bando_id: Any
    similarita: float
    blocco: str                        # regione | ente | host
    differenze: tuple[str, ...] = ()
    applicato: bool = False


# --- lettura tollerante delle righe ----------------------------------------

def _primo(riga: Mapping[str, Any], *nomi: str) -> Any:
    for nome in nomi:
        valore = riga.get(nome)
        if valore not in (None, "", [], {}):
            return valore
    return None


def _testo(riga: Mapping[str, Any], *nomi: str) -> str:
    valore = _primo(riga, *nomi)
    return str(valore).strip() if valore is not None else ""


def _raw(riga: Mapping[str, Any]) -> Mapping[str, Any]:
    grezzo = riga.get("raw_data")
    return grezzo if isinstance(grezzo, Mapping) else {}


def url_del_bando(riga: Mapping[str, Any]) -> tuple[str, ...]:
    """Gli URL con cui una riga puo' combaciare: il link della fonte e la fonte
    ufficiale (§16.2 M9). Normalizzati, senza vuoti, senza doppioni."""
    grezzi = (
        _testo(riga, "link_bando"),
        _testo(riga, "fonte_ufficiale_url"),
    )
    normalizzati = [_url_normalizzato(u) for u in grezzi if u]
    return tuple(dict.fromkeys(u for u in normalizzati if u))


def link_del_bando(riga: Mapping[str, Any]) -> str | None:
    """Il solo `link_bando` normalizzato: e' l'URL della riga presso la sua
    fonte, l'unico che identifica *quella* riga e non la pagina d'ente a cui
    puo' puntare insieme a molte altre."""
    return _url_normalizzato(_testo(riga, "link_bando"))


def coincidenze_url(
    candidato: Mapping[str, Any], riga: Mapping[str, Any]
) -> tuple[str, ...]:
    """Gli URL su cui due righe coincidono secondo §16.2 M9.

    M9 autorizza una coppia sola: «URL normalizzato **del candidato** =
    `link_bando` **o** `fonte_ufficiale_url` di qualunque pubblicato». Quindi
    almeno un lato della coincidenza dev'essere un `link_bando`: la coppia
    (fonte ufficiale del candidato, fonte ufficiale del pubblicato) non e' in
    M9 ed e' proprio quella che il passo 1 della cascata assegna uguale a due
    lotti o a due edizioni dello stesso ente — le righe che il piano ripete di
    non dover fondere mai.
    """
    tutti_candidato = set(url_del_bando(candidato))
    tutti_riga = set(url_del_bando(riga))
    trovati: set[str] = set()
    link_candidato = link_del_bando(candidato)
    if link_candidato and link_candidato in tutti_riga:
        trovati.add(link_candidato)
    link_riga = link_del_bando(riga)
    if link_riga and link_riga in tutti_candidato:
        trovati.add(link_riga)
    return tuple(sorted(trovati))


def titolo_normalizzato(riga: Mapping[str, Any]) -> str:
    return _canonico(_testo(riga, "titolo", "titolo_raw"))


# --- chiave esterna ---------------------------------------------------------

def famiglia(record: Mapping[str, Any], fonte: Mapping[str, Any] | None = None) -> str:
    """Famiglia della fonte: prima `raw_data['source']` (lo scrivono gli
    adapter), poi l'id della fonte, poi l'host di `fonte.link`."""
    sorgente = str(_raw(record).get("source") or "").strip()
    if sorgente:
        return sorgente
    identificativo = _primo(record, "fonte_id") or (fonte or {}).get("id")
    try:
        numero = int(identificativo)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        numero = None
    if numero is not None and numero in FONTI_OE:
        return FAMIGLIA_OE
    host = dominio_di(str((fonte or {}).get("link") or "")) or ""
    if "obiettivoeuropa" in host:
        return FAMIGLIA_OE
    if "incentivi.gov.it" in host:
        return FAMIGLIA_INCENTIVI
    if "italiadomani" in host:
        return FAMIGLIA_ITALIA_DOMANI
    return ""


def chiave_esterna(record: Mapping[str, Any], fonte: Mapping[str, Any] | None = None) -> str | None:
    """Identificativo stabile della riga presso la sua fonte (§14).

    E' cio' che permette di seguire un bando quando la fonte gli cambia l'URL:
    prima dell'upsert il runner cerca `(fonte_id, chiave_esterna)` e aggiorna la
    riga esistente invece di crearne una nuova. Il prefisso di famiglia rende la
    chiave leggibile nei report e impedisce che un `nid` e un `id` OE con lo
    stesso numero si somiglino per caso.

    `None` significa «questa riga non ha un identificativo di cui fidarsi»:
    meglio nessuna chiave che una chiave che cambia a ogni giro.
    """
    grezzo = _raw(record)
    genere = famiglia(record, fonte)

    if genere == FAMIGLIA_OE:
        identificativo = str(grezzo.get("id") or "").strip()
        if identificativo:
            return f"oe:{identificativo}"
        # Le righe OE senza `id` (comprese le 545 chiuse fuori listing) hanno
        # comunque un percorso stabile: `/bandi/<slug>`.
        percorso = urlsplit(_testo(record, "link_bando")).path.rstrip("/")
        return f"oe:{percorso}" if percorso else None

    if genere == FAMIGLIA_INCENTIVI:
        nid = str(grezzo.get("nid") or "").strip()
        return f"incentivi:{nid}" if nid else None

    if genere == FAMIGLIA_ITALIA_DOMANI:
        esterno = str(grezzo.get("external_id") or "").strip()
        return f"italiadomani:{esterno}" if esterno else None

    # Calendari e file (csv/pdf/hybrid): codice, altrimenti titolo + data,
    # altrimenti titolo + posizione nel file.
    codice = str(_primo(record, "codice", "codice_bando", "id_bando") or "").strip()
    if not codice:
        codice = str(grezzo.get("codice") or grezzo.get("codice_bando") or "").strip()
    if codice:
        return f"calendario:{codice}"

    titolo = titolo_normalizzato(record)
    if not titolo:
        return None
    data = str(_primo(record, "data_scadenza", "data_apertura") or "").strip()
    if not data:
        data = str(grezzo.get("data_scadenza") or grezzo.get("close_date") or "").strip()
    if data:
        return f"calendario:{titolo}|{data[:10]}"
    riga = grezzo.get("row_index")
    if riga is not None and str(riga).strip() != "":
        sorgente = str(grezzo.get("source_url") or "").strip()
        return f"calendario:{titolo}|{sorgente}|r{riga}"
    return None


# --- numero di atto ---------------------------------------------------------

def numero_atto(riga: Mapping[str, Any]) -> str | None:
    """Atto numerato in forma canonica `tipo:numero/anno`, o None.

    L'anno e' obbligatorio: «DGR 123» senza anno combacerebbe con la delibera
    123 di qualunque altro anno, e una fusione sbagliata non si disfa da sola.
    """
    esplicito = _testo(riga, "numero_atto")
    testi = [t for t in (esplicito, _testo(riga, "titolo", "titolo_raw")) if t]
    for testo in testi:
        # Tutte le occorrenze, non la prima: «Avviso DD 12 - attuazione della
        # Determinazione n. 55/2026» comincia con un atto senza anno, e
        # fermarsi li' butterebbe via il criterio esatto piu' forte che il
        # titolo porta due parole dopo.
        for trovato in _RE_ATTO.finditer(testo):
            anno = trovato.group("anno1") or trovato.group("anno2")
            if not anno:
                continue
            if len(anno) == 2:
                anno = f"20{anno}"
            tipo = trovato.group("tipo")
            canonico = next((nome for regola, nome in _TIPI_ATTO if regola.match(tipo)), None)
            if not canonico:
                continue
            return f"{canonico}:{int(trovato.group('numero'))}/{anno}"
    return None


def dominio_ufficiale_riga(riga: Mapping[str, Any]) -> str | None:
    """Dominio registrabile su cui la riga dichiara il proprio atto. Gli
    aggregatori non contano: due bandi diversi stanno sullo stesso host OE.

    Il dominio e' quello di `dominio_ufficiale.registrabile()`, che sui domini
    geografici italiani tiene il prefisso dell'ente: senza,
    `comune.imola.bo.it` e `comune.casalecchio.bo.it` sarebbero lo stesso
    `bo.it` e due determine con lo stesso numero verrebbero fuse in automatico.
    """
    for campo in ("fonte_ufficiale_url", "fonte_ufficiale_host", "link_bando"):
        valore = _testo(riga, campo)
        if not valore:
            continue
        if e_aggregatore(valore):
            continue
        dominio = registrabile(valore)
        if dominio:
            return dominio
    return None


# --- riga di calendario (contratto `bandi-giro-2` §19.9) ---------------------
#
# Le righe dei calendari in PDF, CSV o foglio non hanno un `link_bando`: il
# criterio dell'URL non puo' vederle, e la stessa riga letta due volte (il PDF
# e il CSV dello stesso calendario di VdA, la stessa tabella su due pagine del
# documento Interreg) resta due bandi pubblicati. Qui la stessa riga si
# riconosce dal suo contenuto: stessa fonte, stessa descrizione e stesso file,
# oppure la stessa data di chiusura scritta nella riga.

#: Il nome del quarto criterio esatto.
CRITERIO_RIGA_CALENDARIO = "riga_calendario"
#: Chiavi di `raw_data` che dicono dove sta la riga, non che cosa dice: la
#: posizione nel file, il file stesso e le chiavi che scrive il nostro codice.
METADATI_CALENDARIO: frozenset[str] = frozenset({
    "row_index", "page", "riga", "pagina", "table_index", "source_url",
    "source", "hash_senza_link",
})
#: Sotto questo numero di parole una descrizione non distingue niente
#: (un'intestazione di tabella, un codice).
TOKEN_MINIMI_CALENDARIO = 3
#: Le parole dopo cui una riga di calendario scrive la sua chiusura.
_RE_CHIUSURA = re.compile(r"chius\w*|fino\s+al?\b|scadenz\w*|termine", re.IGNORECASE)
#: Quanti caratteri dopo la parola si cerca la data: oltre, la data e' di
#: un'altra frase della cella.
_FINESTRA_CHIUSURA = 60


@lru_cache(maxsize=16384)
def _testo_calendario(testo: str) -> str:
    """Minuscole, senza accenti, senza punteggiatura, spazi compattati.

    La punteggiatura si **cancella**, non si sostituisce con uno spazio: il PDF
    del calendario di VdA scrive «l’assegnazione» e “Avviso 23AF”, il CSV dello
    stesso calendario «lassegnazione» e nessuna virgoletta.
    """
    scomposto = unicodedata.normalize("NFKD", testo)
    senza_accenti = "".join(c for c in scomposto if not unicodedata.combining(c)).lower()
    pulito = "".join(c for c in senza_accenti if c.isalnum() or c.isspace())
    return " ".join(pulito.split())


def _valori_calendario(riga: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Le coppie (chiave, valore) del contenuto della riga, senza i metadati."""
    coppie: list[tuple[str, str]] = []
    for chiave, valore in _raw(riga).items():
        if chiave in METADATI_CALENDARIO or isinstance(valore, bool):
            continue
        if isinstance(valore, (str, int, float)):
            coppie.append((str(chiave), str(valore)))
    return coppie


def descrizione_calendario(riga: Mapping[str, Any]) -> str:
    """Il contenuto normalizzato della riga di calendario, o "".

    `titolo_raw` piu' tutti i valori di `raw_data` tranne i metadati, ognuno
    normalizzato, **ordinati** (il PDF chiama le colonne `col_N`, il CSV
    `Unnamed: N`) e uniti. Con meno di `TOKEN_MINIMI_CALENDARIO` parole vale
    "": non basta a dire che due righe sono la stessa.
    """
    valori = [_testo_calendario(_testo(riga, "titolo_raw"))]
    valori.extend(_testo_calendario(valore) for _chiave, valore in _valori_calendario(riga))
    pieni = sorted(v for v in valori if v)
    if sum(len(v.split()) for v in pieni) < TOKEN_MINIMI_CALENDARIO:
        return ""
    return " | ".join(pieni)


def data_chiusura_calendario(riga: Mapping[str, Any]) -> Any:
    """La data di chiusura scritta nella riga di calendario, o None.

    In una colonna di chiusura (`DATA_CHIUSURA`, «Scadenza») vale la data della
    cella; altrove la prima data **dopo** «chiusura», «fino a», «scadenza» o
    «termine», entro `_FINESTRA_CHIUSURA` caratteri: «apertura 01/01 chiusura
    31/03» deve dare il 31/03, non l'apertura. Con piu' date, la piu' tarda.
    """
    trovate = []
    for chiave, valore in _valori_calendario(riga):
        if _RE_CHIUSURA.search(chiave.replace("_", " ")):
            data = extract_date_from_quote(valore)
            if data is not None:
                trovate.append(data)
            continue
        for parola in _RE_CHIUSURA.finditer(valore):
            data = extract_date_from_quote(valore[parola.end():parola.end() + _FINESTRA_CHIUSURA])
            if data is not None:
                trovate.append(data)
    return max(trovate) if trovate else None


def _sorgente_calendario(riga: Mapping[str, Any]) -> str:
    return str(_raw(riga).get("source_url") or "").strip()


def _riga_calendario(
    candidato: Mapping[str, Any],
    descrizione: str,
    riga: Mapping[str, Any],
) -> str | None:
    """Il dettaglio della coincidenza `riga_calendario`, o None.

    Stessa `fonte_id`, nessun `link_bando` su tutte e due, stessa descrizione
    non vuota, e poi lo stesso file (`source_url`) oppure la stessa data di
    chiusura. Una riga senza file comune e senza data non basta: due edizioni
    annuali dello stesso avviso in due calendari si scrivono uguali.
    """
    if not descrizione or not _stessa_fonte(candidato, riga):
        return None
    if _testo(riga, "link_bando") or descrizione_calendario(riga) != descrizione:
        return None
    sorgente = _sorgente_calendario(candidato)
    if sorgente and sorgente == _sorgente_calendario(riga):
        return f"stesso file|{sorgente}"
    chiusura = data_chiusura_calendario(candidato)
    if chiusura is not None and chiusura == data_chiusura_calendario(riga):
        return f"stessa chiusura|{chiusura.isoformat()}"
    return None


# --- criteri esatti ---------------------------------------------------------

def criteri_esatti(
    candidato: Mapping[str, Any],
    pubblicati: Iterable[Mapping[str, Any]],
) -> tuple[Corrispondenza, ...]:
    """I gemelli certi del candidato fra le righe pubblicate.

    Quattro criteri, tutti esatti e tutti verificabili da chiunque rilegga la riga:
      1. `url`  — un URL normalizzato del candidato (`link_bando` o
         `fonte_ufficiale_url`) coincide con uno di un pubblicato e almeno uno
         dei due e' un `link_bando`. **Nessun vincolo di stessa fonte**
         (§16.2 M9), ma nemmeno la coppia fonte ufficiale contro fonte
         ufficiale, che due lotti dello stesso ente condividono;
      2. `chiave_esterna` — stessa fonte e stessa chiave: e' la stessa riga
         presso la fonte, con l'URL cambiato;
      3. `atto` — stesso atto numerato sullo stesso dominio ufficiale;
      4. `riga_calendario` — stessa fonte, nessun `link_bando`, stessa
         descrizione del calendario e stesso file o stessa data di chiusura
         (contratto `bandi-giro-2` §19.9). Serve a `raw_data`: chi legge le
         righe senza, non lo vede scattare.

    Il candidato viene «preparato» una volta sola prima del ciclo: chiave,
    atto, dominio e i suoi URL normalizzati non dipendono dalla riga con cui lo
    si confronta, e ricalcolarli a ogni coppia costava un fattore n su un
    confronto gia' quadratico (`coincidenze_url` normalizzava i due URL del
    candidato 2 104 volte su un corpus di 2 104 righe).

    `riga is candidato` sta nella guardia accanto al confronto sugli id: cosi'
    il chiamante puo' passare l'elenco intero invece di ricostruirne una copia
    senza il candidato.
    """
    chiave = chiave_esterna(candidato)
    atto = numero_atto(candidato)
    dominio = dominio_ufficiale_riga(candidato)
    identificativo = candidato.get("id")
    urls_candidato = frozenset(url_del_bando(candidato))
    link_candidato = link_del_bando(candidato)
    # La descrizione serve solo alle righe senza link: le altre non la pagano.
    descrizione = "" if _testo(candidato, "link_bando") else descrizione_calendario(candidato)

    trovate: list[Corrispondenza] = []
    for riga in pubblicati:
        if riga is candidato:
            continue
        if identificativo is not None and riga.get("id") == identificativo:
            continue
        comuni = _coincidenze(urls_candidato, link_candidato, riga)
        if comuni:
            trovate.append(Corrispondenza(riga.get("id"), "url", comuni[0]))
            continue
        if chiave and chiave_esterna(riga) == chiave and _stessa_fonte(candidato, riga):
            trovate.append(Corrispondenza(riga.get("id"), "chiave_esterna", chiave))
            continue
        if atto and dominio and numero_atto(riga) == atto and dominio_ufficiale_riga(riga) == dominio:
            trovate.append(Corrispondenza(riga.get("id"), "atto", f"{atto}@{dominio}"))
            continue
        dettaglio = _riga_calendario(candidato, descrizione, riga)
        if dettaglio:
            trovate.append(Corrispondenza(riga.get("id"), CRITERIO_RIGA_CALENDARIO, dettaglio))
    return tuple(trovate)


def _coincidenze(
    urls_candidato: frozenset[str],
    link_candidato: str | None,
    riga: Mapping[str, Any],
) -> tuple[str, ...]:
    """`coincidenze_url` con il lato candidato gia' normalizzato.

    Stessa regola, stesso risultato: serve solo a non rinormalizzare gli URL
    del candidato una volta per ogni riga del corpus.
    """
    tutti_riga = set(url_del_bando(riga))
    trovati: set[str] = set()
    if link_candidato and link_candidato in tutti_riga:
        trovati.add(link_candidato)
    link_riga = link_del_bando(riga)
    if link_riga and link_riga in urls_candidato:
        trovati.add(link_riga)
    return tuple(sorted(trovati))


def _stessa_fonte(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """La chiave esterna e' unica **per fonte** (UNIQUE (fonte_id, chiave_esterna)):
    fuori da quella coppia non dimostra niente."""
    return a.get("fonte_id") is not None and a.get("fonte_id") == b.get("fonte_id")


# --- fuzzy: solo proposte ---------------------------------------------------

def _chiavi_blocco(riga: Mapping[str, Any]) -> tuple[str, str, str]:
    """Regione, ente e host normalizzati: le tre chiavi del blocking."""
    return (
        _canonico(_testo(riga, "regione", "area_geografica")),
        _canonico(_testo(riga, "ente_erogatore", "ente")),
        _host(_testo(riga, "link_bando")),
    )


def _blocco_con(chiavi: tuple[str, str, str], riga: Mapping[str, Any]) -> str:
    """Il blocco fra un candidato gia' preparato e una riga.

    Le chiavi della riga si calcolano **una alla volta e solo se servono**: se
    il candidato non ha regione — e le colonne che `select_pubblicati_per_gemelli`
    legge non comprendono `regione` ne' `ente_erogatore` — quel confronto non
    puo' riuscire e normalizzare la regione della riga e' lavoro buttato,
    moltiplicato per il numero di coppie.
    """
    regione_a, ente_a, host_a = chiavi
    if regione_a and regione_a == _canonico(_testo(riga, "regione", "area_geografica")):
        return "regione"
    if ente_a and ente_a == _canonico(_testo(riga, "ente_erogatore", "ente")):
        return "ente"
    if host_a and host_a == _host(_testo(riga, "link_bando")):
        return "host"
    return ""


def _famiglia(parola: str) -> str:
    for forma, famiglia in _FAMIGLIE_NUMERATE:
        if re.fullmatch(forma, parola, re.I):
            return famiglia
    return parola.lower()


def _romano(testo: str) -> int | None:
    """Il valore di un numero romano fatto di I, V e X, o None se non e' ben formato."""
    valori = [_VALORI_ROMANI.get(c) for c in testo]
    if not valori or None in valori:
        return None
    totale = 0
    for i, valore in enumerate(valori):
        prossimo = valori[i + 1] if i + 1 < len(valori) else 0
        totale += -valore if valore < prossimo else valore
    return totale if totale > 0 else None


def _numero_canonico(testo: str) -> str | None:
    """«02» -> «2», «II» -> «2», «2°» -> «2», «seconda» -> «2», «1.01» -> «1.1»,
    «A» -> «A». None se non e' un numero."""
    pulito = re.sub(r"[\s°ºª^]+$", "", testo.strip())
    if not pulito:
        return None
    ordinale = _ORDINALI_IN_LETTERE.get(pulito.lower())
    if ordinale is not None:
        return str(ordinale)
    if re.fullmatch(r"\d{1,3}[ao]", pulito, re.I):
        pulito = pulito[:-1]
    if re.fullmatch(_ARABO, pulito):
        return ".".join(str(int(parte)) for parte in pulito.split("."))
    if re.fullmatch(r"[IVX]{1,6}", pulito):
        valore = _romano(pulito)
        return str(valore) if valore is not None else None
    if re.fullmatch(r"[A-Z]", pulito):
        return pulito
    return None


def _numerazioni(testo: str) -> set[str]:
    """Le parti numerate nominate nel titolo, come «famiglia numero»: «Lotto
    n. 2» -> {"lotto 2"}, «lotti 1/2» -> {"lotto 1", "lotto 2"}, «II edizione»
    -> {"edizione 2"}, «Linea di intervento A/B» -> {"linea A", "linea B"},
    «Avviso n. 3/2026» -> {"avviso 3"}. Numeri arabi, romani e ordinali; la
    lettera maiuscola solo nelle `_FAMIGLIE_CON_LETTERA`."""
    trovate: set[str] = set()
    for m in _RE_NUMERATO_DOPO.finditer(testo):
        famiglia = _famiglia(m.group("parola"))
        grezzi = [m.group("numeri"),
                  *(a.group("elemento") for a in _RE_ALTRO.finditer(m.group("altri") or ""))]
        for grezzo in grezzi:
            lettera = re.fullmatch(r"[A-Z]", grezzo.strip()) and grezzo.strip() not in "IVX"
            if lettera and famiglia not in _FAMIGLIE_CON_LETTERA:
                continue
            numero = _numero_canonico(grezzo)
            if numero is not None:
                trovate.add(f"{famiglia} {numero}")
    for m in _RE_AVVISO.finditer(testo):
        numero = m.group("numero")
        if _RE_ANNO.fullmatch(numero):
            continue                      # «Avviso 2026»: e' un anno, non un numero
        trovate.add(f"{FAMIGLIA_AVVISO} {int(numero)}")
    for m in _RE_NUMERATO_PRIMA.finditer(testo):
        parola = m.group("parola")
        # «I lotti» e' l'articolo, non «primo lotto».
        if m.group("numero") == "I" and _RE_PLURALE_NUMERATO.match(parola):
            continue
        numero = _numero_canonico(m.group("numero"))
        if numero is not None:
            trovate.add(f"{_famiglia(parola)} {numero}")
    return trovate


def _differenze(a: str, b: str) -> tuple[str, ...]:
    """Anni e parti numerate (lotto, edizione, sportello, misura, azione,
    fase, linea, annualita', finestra, tranche) che compaiono in un titolo e
    non nell'altro: il motivo per cui una proposta quasi certa va guardata, e
    per cui il passo automatico non fonde (`motivo_di_prudenza`). E' la
    differenza simmetrica dei due insiemi; per misura, azione, fase, linea,
    asse, intervento, modulo e avviso solo se la parola e' numerata in tutti e
    due i titoli (`_FAMIGLIE_SOLO_SE_IN_ENTRAMBI`)."""
    trovate: list[str] = []
    anni_a, anni_b = set(_RE_ANNO.findall(a)), set(_RE_ANNO.findall(b))
    for anno in sorted(anni_a ^ anni_b):
        trovate.append(f"anno {anno}")
    parti_a, parti_b = _numerazioni(a), _numerazioni(b)
    famiglie_a = {parte.split(" ", 1)[0] for parte in parti_a}
    famiglie_b = {parte.split(" ", 1)[0] for parte in parti_b}
    for parte in sorted(parti_a ^ parti_b):
        famiglia = parte.split(" ", 1)[0]
        if famiglia in _FAMIGLIE_SOLO_SE_IN_ENTRAMBI and not (
                famiglia in famiglie_a and famiglia in famiglie_b):
            continue
        trovate.append(parte)
    return tuple(trovate)


def possibili_doppioni(
    candidato: Mapping[str, Any],
    pubblicati: Iterable[Mapping[str, Any]],
    *,
    soglia: float = SOGLIA_FUZZY,
    esatti: Iterable[Any] | None = None,
) -> tuple[Proposta, ...]:
    """Proposte `possibile_doppione`, mai applicate (§5 passo 2, §14).

    Blocking obbligatorio (regione, ente o host: senza, si confronterebbero
    2 100 titoli con 2 100 titoli) e `difflib.SequenceMatcher` ≥ 0,92 sui titoli
    normalizzati. I gemelli certi sono esclusi: li ha gia' detti `criteri_esatti`
    e qui farebbero solo rumore nel report.

    `esatti` sono gli id dei gemelli certi, se il chiamante li ha gia'. Senza,
    si chiama `criteri_esatti`: e' cio' che faceva sempre, e in
    `run_fondi_doppioni` — che li aveva appena calcolati — voleva dire
    ripassare l'intero corpus una seconda volta per ogni riga.

    `real_quick_ratio`/`quick_ratio` sono i **maggioranti** documentati di
    `ratio()` (li usa `difflib.get_close_matches`): scartare con loro una
    coppia sotto soglia non puo' cambiare l'esito, e risparmia la parte cara
    dell'algoritmo sulle coppie che non c'entrano niente.
    """
    titolo = titolo_normalizzato(candidato)
    if not titolo:
        return ()
    righe = list(pubblicati)
    if esatti is None:
        esatti = {c.bando_id for c in criteri_esatti(candidato, righe)}
    else:
        esatti = set(esatti)
    identificativo = candidato.get("id")
    chiavi = _chiavi_blocco(candidato)
    confronto = difflib.SequenceMatcher(None)
    confronto.set_seq1(titolo)

    proposte: list[Proposta] = []
    for riga in righe:
        if riga is candidato:
            continue
        if riga.get("id") in esatti:
            continue
        if identificativo is not None and riga.get("id") == identificativo:
            continue
        blocco = _blocco_con(chiavi, riga)
        if not blocco:
            continue
        altro = titolo_normalizzato(riga)
        if not altro:
            continue
        confronto.set_seq2(altro)
        if confronto.real_quick_ratio() < soglia or confronto.quick_ratio() < soglia:
            continue
        similarita = confronto.ratio()
        if similarita < soglia:
            continue
        proposte.append(Proposta(
            bando_id=riga.get("id"),
            similarita=round(similarita, 4),
            blocco=blocco,
            differenze=_differenze(
                _testo(candidato, "titolo", "titolo_raw"),
                _testo(riga, "titolo", "titolo_raw"),
            ),
        ))
    proposte.sort(key=lambda p: (-p.similarita, str(p.bando_id)))
    return tuple(proposte)


# --- master -----------------------------------------------------------------

def _chiave_master(riga: Mapping[str, Any]) -> tuple:
    """Ordine di §14, dal criterio piu' forte al piu' debole. `False` ordina
    prima di `True`, quindi le condizioni sono negate."""
    stato = _testo(riga, "fonte_ufficiale_stato")
    tipo = _testo(riga, "fonte_ufficiale_tipo")
    e_atto = bool(riga.get("fonte_ufficiale_e_atto"))
    fonte_forte = stato == "trovata" and (tipo == "ente" or e_atto)

    link = _testo(riga, "link_bando")
    non_aggregatore = bool(link) and not e_aggregatore(link)

    opportunita = _testo(riga, "tipo_link") == "Opportunità"

    try:
        eventi = int(riga.get("eventi_verificati") or 0)
    except (TypeError, ValueError):
        eventi = 0

    pubblicato = _testo(riga, "pubblicato_at", "created_at") or "9999"
    contenuto = riga.get("contenuto")
    lunghezza = len(contenuto) if isinstance(contenuto, (str, list, dict)) else 0

    return (
        not fonte_forte,
        not non_aggregatore,
        not opportunita,
        -eventi,
        pubblicato,
        -lunghezza,
        str(riga.get("id")),
    )


def scegli_master(righe: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """Il master di un gruppo di gemelli, con l'ordine di §14: fonte ufficiale
    di tipo ente o atto, fonte non aggregatore, `tipo_link='Opportunità'`, piu'
    eventi verificati, `pubblicato_at` piu' vecchio, piu' contenuto.

    L'ultimo criterio e' l'id: a parita' di tutto il resto la scelta deve
    restare la stessa fra un giro e l'altro, altrimenti due esecuzioni dello
    stesso comando proporrebbero due 301 opposti.
    """
    valide = [r for r in righe if r]
    if not valide:
        return None
    return min(valide, key=_chiave_master)


def trova_master(
    riga: Mapping[str, Any],
    candidati: Iterable[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], Corrispondenza] | None:
    """Riconoscimento post-scrape di §14: il master della riga fra i candidati,
    **solo** con criteri esatti. None se nessun criterio esatto combacia (il
    fuzzy non entra qui: produce proposte, e la riga prosegue nella pipeline).
    """
    elenco = list(candidati)
    corrispondenze = criteri_esatti(riga, elenco)
    if not corrispondenze:
        return None
    per_id = {c.bando_id: c for c in corrispondenze}
    scelte = [r for r in elenco if r.get("id") in per_id]
    master = scegli_master(scelte)
    if master is None:
        return None
    return master, per_id[master.get("id")]


# --- doppioni ObiettivoEuropa prima della SEO (contratto di ottobre, §6) -----
#
# Il 29/09 quattro dei venti bandi pubblicati dal giro delle 12 erano schede di
# ObiettivoEuropa di avvisi gia' pubblicati dalla fonte dell'ente (F3-F6 di
# `docs/bandi-monitor/correzioni-2026-09-29.sql`). Qui li si riconosce PRIMA
# della chiamata a Opus: un bando OE non ancora pubblicato e' un «doppione
# probabile» se esiste un pubblicato non fuso di una fonte NON OE con
#
#   1. la stessa `fonte_ufficiale_url` normalizzata, oppure
#   2. lo stesso ente normalizzato, lo stesso importo e la stessa scadenza.
#
# La controparte non OE e' una correzione del 30/09: OE contro OE dava circa un
# falso su tre (lotti diversi sulla stessa pagina elenco, come la formazione
# della Toscana 759891-759895). E all'ingresso della SEO un bando OE ha
# `ente_erogatore` e `importo_totale_eur` NULL, perche' li scrive la SEO: per il
# candidato l'ente viene dal prefisso del titolo OE («Piemonte - …») e
# l'importo da `raw_data.budget`.
#
# L'esito e' un rifiuto con motivo, **mai una fusione**: le fusioni restano a
# Michele, con `bando_fondi`. Un rifiuto sbagliato si annulla con un UPDATE:
#
#   update bando
#      set stato_processing = 'enriched',
#          rejection_reason = 'doppione escluso a mano'
#    where id = <id> and stato_processing = 'rejected';
#
# e da quel momento il controllo non lo rifiuta piu' (`candidato_oe`).

CRITERIO_URL = "url"
CRITERIO_CHIAVE = "ente-importo-scadenza"
MOTIVO_ESCLUSO_A_MANO = "doppione escluso a mano"

_RE_SEPARATORE_ENTE = re.compile(r"\s[-–—]\s")
#: «di» e le preposizioni articolate, dopo la normalizzazione («dell'» -> «dell»).
_ARTICOLATE = r"(?:di|del|dello|della|dell|dei|degli|delle)"
_RE_GENERICI_ENTE = re.compile(
    r"^(?:"
    # «Regione Piemonte», «Regione Autonoma della Sardegna», «Regione del Veneto».
    rf"regione(?: autonoma)?(?: {_ARTICOLATE})? "
    # «Provincia autonoma di Trento», «Provincia di Cuneo».
    rf"|provincia(?: autonoma)?(?: {_ARTICOLATE})? "
    rf"|comune {_ARTICOLATE} "
    # Tutto fino al primo «di» (o articolata): la ragione sociale della camera
    # varia («Industria Artigianato e Agricoltura», con o senza «e»).
    rf"|camera di commercio (?:(?:[a-z0-9]+ )*?{_ARTICOLATE} )?"
    # «CCIAA» e «C.C.I.A.A.», che la normalizzazione rende «c c i a a».
    rf"|(?:cciaa|c c i a a)(?: {_ARTICOLATE})? "
    r"|gal "
    r")+"
)


def ente_normalizzato(testo: Any) -> str:
    """«Regione Piemonte - Direzione Welfare» e «Piemonte» -> «piemonte».

    Minuscole, niente accenti, taglio a « - » o «(», via le parole generiche
    in testa (regione, provincia, comune, camera di commercio fino al primo
    «di», cciaa o c.c.i.a.a., gal) con la preposizione che le segue.
    Vuoto se non resta niente: un ente vuoto non fa scattare il criterio 2.
    """
    if not testo:
        return ""
    s = unicodedata.normalize("NFKD", str(testo))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = _RE_SEPARATORE_ENTE.split(s, maxsplit=1)[0].split("(", 1)[0]
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return _RE_GENERICI_ENTE.sub("", s + " ").strip()


def _e_oe(riga: Mapping[str, Any]) -> bool:
    try:
        return int(riga.get("fonte_id")) in FONTI_OE
    except (TypeError, ValueError):
        return False


def _importo(valore: Any) -> int | None:
    """Un importo positivo e finito, o None.

    Il `budget` arriva dall'API di ObiettivoEuropa: un «Infinity» o un 1e400
    (che il JSON legge come infinito) facevano sollevare a `int()` un
    OverflowError, e lo step SEO si fermava a ogni giro finche' il record
    restava com'era (revisione avversaria, S3).
    """
    try:
        decimale = float(valore)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(decimale):
        return None
    try:
        numero = int(decimale)
    except (OverflowError, ValueError):                   # pragma: no cover - difesa
        return None
    return numero if numero > 0 else None


def ente_del_candidato(riga: Mapping[str, Any]) -> str:
    """L'ente del bando OE: la colonna, oppure il prefisso del titolo OE."""
    ente = _testo(riga, "ente_erogatore")
    if ente:
        return ente
    pezzi = _RE_SEPARATORE_ENTE.split(_testo(riga, "titolo_raw"), maxsplit=1)
    return pezzi[0] if len(pezzi) == 2 else ""


def importo_del_candidato(riga: Mapping[str, Any]) -> int | None:
    """L'importo del bando OE: la colonna, oppure `raw_data.budget`."""
    importo = _importo(riga.get("importo_totale_eur"))
    return importo if importo is not None else _importo(_raw(riga).get("budget"))


def chiave_doppione(ente: Any, importo: Any, scadenza: Any) -> tuple[str, int, str] | None:
    """(ente normalizzato, importo, scadenza), o None se ne manca uno."""
    ente_n = ente_normalizzato(ente)
    importo_n = _importo(importo)
    giorno = str(scadenza or "")[:10]
    if not (ente_n and importo_n and giorno):
        return None
    return ente_n, importo_n, giorno


def candidato_oe(riga: Mapping[str, Any]) -> bool:
    """Il controllo guarda questa riga? Solo OE, `enriched`, non annullata a mano.

    Annullamento di un rifiuto sbagliato (contratto di ottobre, §6), un solo
    UPDATE nel SQL Editor:

        update bando
           set stato_processing = 'enriched',
               rejection_reason = 'doppione escluso a mano'
         where id = <id> and stato_processing = 'rejected';

    Da quel momento la riga non e' piu' candidata, e al giro dopo va alla SEO.
    """
    return (
        _e_oe(riga)
        and riga.get("stato_processing") == "enriched"
        and not riga.get("pubblicato")
        and riga.get("rejection_reason") != MOTIVO_ESCLUSO_A_MANO
    )


@dataclass(frozen=True)
class IndiceDoppioniOE:
    """Le controparti possibili: pubblicati non fusi di fonti NON OE."""
    per_url: Mapping[str, Any]
    per_chiave: Mapping[tuple[str, int, str], Any]

    @classmethod
    def da_pubblicati(cls, righe: Iterable[Mapping[str, Any]]) -> "IndiceDoppioniOE":
        """A parita' di URL o di chiave vince l'id piu' basso: la scelta non
        deve cambiare fra un giro e l'altro."""
        per_url: dict[str, Any] = {}
        per_chiave: dict[tuple[str, int, str], Any] = {}
        for riga in righe:
            if _e_oe(riga) or riga.get("bando_master_id") is not None:
                continue
            if "pubblicato" in riga and not riga.get("pubblicato"):
                continue
            bando_id = riga.get("id")
            if bando_id is None:
                continue
            url = _url_normalizzato(_testo(riga, "fonte_ufficiale_url") or None)
            if url and (url not in per_url or bando_id < per_url[url]):
                per_url[url] = bando_id
            chiave = chiave_doppione(
                riga.get("ente_erogatore"), riga.get("importo_totale_eur"), riga.get("data_scadenza"),
            )
            if chiave and (chiave not in per_chiave or bando_id < per_chiave[chiave]):
                per_chiave[chiave] = bando_id
        return cls(per_url, per_chiave)


def doppione_oe(
    candidato: Mapping[str, Any], indice: IndiceDoppioniOE,
) -> tuple[Any, str] | None:
    """(id del pubblicato, criterio) se il candidato ne e' un doppione probabile.

    L'URL si guarda prima della chiave: e' la prova piu' forte, e il motivo
    scritto nel rifiuto deve dire quella.
    """
    url = _url_normalizzato(_testo(candidato, "fonte_ufficiale_url") or None)
    if url and url in indice.per_url:
        return indice.per_url[url], CRITERIO_URL
    chiave = chiave_doppione(
        ente_del_candidato(candidato), importo_del_candidato(candidato),
        candidato.get("data_scadenza"),
    )
    if chiave and chiave in indice.per_chiave:
        return indice.per_chiave[chiave], CRITERIO_CHIAVE
    return None


def motivo_doppione(master_id: Any, criterio: str) -> str:
    """Il `rejection_reason` del §6."""
    return f"doppione probabile di {master_id}: {criterio}"


# --- passo `gemelli` (contratti `bandi-giro-2` §19.9 e `bandi-giro-3` §11) ----
#
# Le fusioni automatiche dei gemelli certi, decise da Michele il 30/09 (D2):
# solo con `criteri_esatti`, mai con il fuzzy; in ombra si elencano e si
# contano, in attivo si fondono con `bando_fondi`. Dal giro 3: a ogni giro dei
# `MONITOR_GIRI`, su tutti i pubblicati e **senza tetto di fusioni** (regola
# «niente lotti», §1); l'interruttore e' `GEMELLI_MODALITA`, non piu'
# `VERIFICA_STATO_MODALITA`. Le guardie di prudenza restano tutte.
#
# L'I/O e' iniettato (`leggi`, `fondi`): il modulo resta puro e il passo si
# prova senza rete.

MODALITA_OMBRA = "ombra"
MODALITA_ATTIVO = "attivo"
#: Quante fusioni si elencano nei contatori della riga del giro: la riga di
#: `pipeline_run` resta piccola. E' solo un elenco: si fondono tutte, e la CLI
#: le mostra tutte (`elenco_max=None`).
TETTO_ELENCO_FUSIONI = 50
#: Il motivo scritto in `bando_fusione`, che BandoFit legge: niente nomi interni.
MOTIVO_FUSIONE = "gemello esatto"
CRITERI_ESATTI: tuple[str, ...] = ("url", "chiave_esterna", "atto", CRITERIO_RIGA_CALENDARIO)


def _ordine_id(identificativo: Any) -> tuple:
    """Ordine degli id: i numeri per valore, poi il resto come testo."""
    numero = isinstance(identificativo, int) and not isinstance(identificativo, bool)
    return (not numero, identificativo if numero else 0, str(identificativo))


def _indici_dei_gemelli(righe: Sequence[Mapping[str, Any]]) -> list[tuple[int, int]]:
    """Le coppie (i, j), i < j, che **potrebbero** essere gemelle.

    Un indice per criterio al posto del confronto di ogni riga con tutte le
    altre: su 2 100 pubblicati sono 2 100 righe invece di 4,4 milioni di
    coppie. Le chiavi sono le stesse di `criteri_esatti`, che poi conferma ogni
    coppia: l'indice sceglie chi confrontare, non decide niente.
    """
    per_url: dict[str, list[int]] = {}
    per_chiave: dict[tuple[Any, str], list[int]] = {}
    per_atto: dict[tuple[str, str], list[int]] = {}
    per_calendario: dict[tuple[Any, str], list[int]] = {}
    for indice, riga in enumerate(righe):
        for url in url_del_bando(riga):
            per_url.setdefault(url, []).append(indice)
        fonte = riga.get("fonte_id")
        chiave = chiave_esterna(riga)
        if chiave and fonte is not None:
            per_chiave.setdefault((fonte, chiave), []).append(indice)
        atto, dominio = numero_atto(riga), dominio_ufficiale_riga(riga)
        if atto and dominio:
            per_atto.setdefault((atto, dominio), []).append(indice)
        if fonte is not None and not _testo(riga, "link_bando"):
            descrizione = descrizione_calendario(riga)
            if descrizione:
                per_calendario.setdefault((fonte, descrizione), []).append(indice)

    coppie: set[tuple[int, int]] = set()
    for indice, riga in enumerate(righe):
        link = link_del_bando(riga)
        for altro in per_url.get(link, ()) if link else ():
            if altro != indice:
                coppie.add((min(indice, altro), max(indice, altro)))
    for gruppo in (*per_chiave.values(), *per_atto.values(), *per_calendario.values()):
        for posizione, primo in enumerate(gruppo):
            for secondo in gruppo[posizione + 1:]:
                coppie.add((min(primo, secondo), max(primo, secondo)))
    return sorted(coppie)


def coppie_certe(
    righe: Sequence[Mapping[str, Any]],
) -> list[tuple[Mapping[str, Any], Mapping[str, Any], Corrispondenza]]:
    """Le coppie di gemelli certi fra `righe`, confermate da `criteri_esatti`.

    Righe senza `id` escluse. L'ordine e' quello degli id: due esecuzioni sulle
    stesse righe danno le stesse coppie.
    """
    valide = sorted((r for r in righe if r.get("id") is not None),
                    key=lambda r: _ordine_id(r.get("id")))
    trovate = []
    for primo, secondo in _indici_dei_gemelli(valide):
        a, b = valide[primo], valide[secondo]
        conferme = criteri_esatti(a, [b])
        if conferme:
            trovate.append((a, b, conferme[0]))
    return trovate


def gruppi_di_gemelli(
    coppie: Sequence[tuple[Mapping[str, Any], Mapping[str, Any], Corrispondenza]],
) -> list[tuple[Mapping[str, Any], list[tuple[Mapping[str, Any], str]]]]:
    """(master, [(doppione, criterio)…]) per ogni gruppo di gemelli.

    Un gruppo e' una componente connessa delle coppie: se A=B e B=C sono certe,
    C e' lo stesso bando di A anche senza una coppia A=C. Il master e'
    `scegli_master` (ordine di §14); il criterio di un doppione e' quello della
    sua prima coppia. Gruppi in ordine di id minimo, doppioni in ordine di id.
    """
    padre: dict[Any, Any] = {}
    righe: dict[Any, Mapping[str, Any]] = {}
    criterio: dict[Any, str] = {}

    def radice(chiave: Any) -> Any:
        while padre[chiave] != chiave:
            padre[chiave] = padre[padre[chiave]]
            chiave = padre[chiave]
        return chiave

    for a, b, corrispondenza in coppie:
        for riga in (a, b):
            identificativo = riga.get("id")
            righe.setdefault(identificativo, riga)
            padre.setdefault(identificativo, identificativo)
            criterio.setdefault(identificativo, corrispondenza.criterio)
        ra, rb = radice(a.get("id")), radice(b.get("id"))
        if ra != rb:
            padre[max(ra, rb, key=_ordine_id)] = min(ra, rb, key=_ordine_id)

    componenti: dict[Any, list[Any]] = {}
    for identificativo in padre:
        componenti.setdefault(radice(identificativo), []).append(identificativo)
    gruppi = []
    for membri in componenti.values():
        master = scegli_master([righe[m] for m in membri])
        if master is None:
            continue
        doppioni = sorted((m for m in membri if m != master.get("id")), key=_ordine_id)
        primo = min(membri, key=_ordine_id)
        gruppi.append((primo, master, [(righe[m], criterio[m]) for m in doppioni]))
    gruppi.sort(key=lambda g: _ordine_id(g[0]))
    return [(master, doppioni) for _primo, master, doppioni in gruppi]


#: Perche' il passo automatico non fonde una coppia **per URL** (decisione del
#: lead del 30/09 notte, dopo la prova sul corpus: 76 coppie per URL). Il
#: criterio resta esatto per `criteri_esatti` e per chi fonde a mano; una
#: fusione che nessuno guarda chiede tre prove in piu':
#:   - l'URL comune sta in **esattamente due** righe pubblicate: con tre o piu'
#:     e' una pagina hub o una pagina di lotti, non la pagina di un bando;
#:   - i titoli si somigliano almeno al livello «medio» del gate G3v
#:     (`fonte_ufficiale.somiglianza_titolo`, nei due versi);
#:   - le scadenze sono uguali, oppure una delle due manca.
PRUDENZA_URL_CONDIVISO = "url_condiviso"
PRUDENZA_TITOLI_DIVERSI = "titoli_diversi"
PRUDENZA_SCADENZE_DIVERSE = "scadenze_diverse"
#: Per TUTTI i criteri del passo (revisione del 30/09 notte): anni o lotti che
#: compaiono nel titolo di una riga e non dell'altra. «… - Lotto 1» e
#: «… - Lotto 2» con la pagina del lotto 1 come fonte ufficiale del lotto 2
#: passavano le altre tre prove, ed erano due bandi.
PRUDENZA_ANNI_O_LOTTI = "anni_o_lotti_diversi"
#: I soli criteri con cui si fonde IN AUTOMATICO (D2 del 30/09 e contratto DB:
#: «stesso URL, oppure stessa riga di calendario»). `chiave_esterna` e `atto`
#: restano criteri esatti per il resolver e per `fondi-doppioni` a mano, ma una
#: stessa delibera che approva piu' avvisi sullo stesso dominio basterebbe a
#: fondere due bandi diversi, e una fusione sbagliata non si disfa da sola
#: (revisione avversaria del 01/10, P1).
CRITERI_AUTOMATICI: tuple[str, ...] = ("url", CRITERIO_RIGA_CALENDARIO)
PRUDENZA_CRITERIO_NON_AUTOMATICO = "criterio_non_automatico"
# Il vecchio `LIMITE_LETTURA_PUBBLICATI` (5 000, il `TETTO_GEMELLI` del
# resolver) non c'e' piu': il passo e la fusione prima della pubblicazione
# leggono tutti i pubblicati (`limit=None`, giro 3 §1 e §11).


def somiglianza_fra_righe(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    """La somiglianza dei titoli di due righe, con la funzione del gate G3v.

    Il titolo editoriale e quello della fonte di una riga contro le parole dei
    due titoli dell'altra, nei due versi; vale il migliore.
    """
    from .fonte_ufficiale import contesto_da_bando, somiglianza_titolo, token

    def parole(riga: Mapping[str, Any]) -> frozenset[str]:
        return token(_testo(riga, "titolo")) | token(_testo(riga, "titolo_raw"))

    return max(somiglianza_titolo(contesto_da_bando(a), parole(b))[0],
               somiglianza_titolo(contesto_da_bando(b), parole(a))[0])


def motivo_di_prudenza(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    corrispondenza: Corrispondenza,
    righe_per_url: Mapping[str, int],
) -> str | None:
    """Il motivo per cui il passo automatico NON fonde la coppia, o None.

    Prima di tutto il criterio: in automatico solo `CRITERI_AUTOMATICI`.
    Anni o parti numerate diverse nei titoli (`_differenze` su `titolo` e su
    `titolo_raw`, ciascuno solo se pieno su tutte e due) valgono per ogni
    criterio; le altre tre prove solo per il
    criterio `url`. `righe_per_url` conta, per ogni URL normalizzato, le righe
    pubblicate che lo portano (`url_del_bando`).
    """
    if corrispondenza.criterio not in CRITERI_AUTOMATICI:
        return PRUDENZA_CRITERIO_NON_AUTOMATICO
    # L'hub per primo: e' il motivo piu' forte e `hub_esclusi` lo conta.
    if corrispondenza.criterio == "url" and righe_per_url.get(corrispondenza.dettaglio, 0) != 2:
        return PRUDENZA_URL_CONDIVISO
    for campo in ("titolo", "titolo_raw"):
        # Un campo si confronta solo se e' pieno su tutte e due le righe: uno
        # vuoto non dice che anni e lotti siano diversi.
        testo_a, testo_b = _testo(a, campo), _testo(b, campo)
        if testo_a and testo_b and _differenze(testo_a, testo_b):
            return PRUDENZA_ANNI_O_LOTTI
    if corrispondenza.criterio != "url":
        return None
    from .fonte_ufficiale import JACCARD_MEDIO
    if somiglianza_fra_righe(a, b) < JACCARD_MEDIO:
        return PRUDENZA_TITOLI_DIVERSI
    scadenza_a = str(a.get("data_scadenza") or "")[:10]
    scadenza_b = str(b.get("data_scadenza") or "")[:10]
    if scadenza_a and scadenza_b and scadenza_a != scadenza_b:
        return PRUDENZA_SCADENZE_DIVERSE
    return None


def _impostazione(nome: str, predefinito: Any) -> Any:
    """Un valore di `Settings` (§19.11), o il predefinito finche' non c'e'."""
    try:
        from .settings import get_settings
        return getattr(get_settings(), nome, predefinito)
    except Exception:
        return predefinito


def esegui_passo(
    giro: str | None = None,
    *,
    modalita: str | None = None,
    leggi: Any = None,
    fondi: Any = None,
    limite_lettura: int | None = None,
    elenco_max: int | None = TETTO_ELENCO_FUSIONI,
) -> dict[str, Any]:
    """Il passo `gemelli`: trova i gemelli certi fra i pubblicati e li fonde.

    Nessun tetto di fusioni (giro 3, §1 e §11): si fondono tutte quelle che
    passano le guardie, a ogni giro.

    - `modalita`: 'attivo' fonde, qualunque altro valore vale 'ombra' (elenca e
      conta). Senza, `settings.gemelli_modalita` (`GEMELLI_MODALITA`);
    - `leggi()`: TUTTI i pubblicati (`db.select_pubblicati_per_gemelli` con
      `limit=None`), con `raw_data` delle righe senza link e
      `bando_master_id` (le righe gia' fuse restano fuori: altrimenti ogni giro
      ritroverebbe le stesse coppie);
    - `fondi(master_id, doppione_id, motivo)`: l'id del master effettivo, o
      None se la fusione non e' riuscita (`db.fondi_bandi`);
    - `limite_lettura`: se la lettura restituisce tante righe o piu', il corpus
      e' tagliato (vedi sotto). None, il default, perche' la lettura e' intera;
    - `elenco_max`: quante fusioni elencare in `fusioni` (None = tutte, per la
      CLI). Non limita le fusioni, solo l'elenco.

    Ogni coppia passa da `motivo_di_prudenza`: quelle scartate non si fondono
    e si contano in `coppie_scartate_per_prudenza` (per motivo) e, se l'URL e'
    condiviso da piu' di due righe, in `hub_esclusi`. Si fondono poi solo i
    gruppi di **due** righe, cioe' un doppione con una coppia prudente diretta
    col master: una catena A=B=C non si fonde in automatico e si conta in
    `gruppi_oltre_due`. `coppie_per_criterio` conta le coppie dei gruppi che il
    passo fonderebbe. Lettura troncata = errore: se la lettura fallisce (o
    restituisce `limite_lettura` righe o piu'), `status='errore'` e nessuna
    fusione, perche' le righe per URL sarebbero sottostimate.

    `copertura` (§1): candidati le fusioni previste, fatti quelle fuse (in
    attivo) o elencate (in ombra); le fusioni non riuscite restano fuori, con
    motivo `errore`. Su un errore del passo non c'e' copertura: lo dice
    `passi_non_ok`.

    Non solleva: un errore diventa `status='errore'` con il solo tipo
    dell'eccezione (il messaggio puo' portarsi dietro URL o chiavi).
    """
    try:
        return _esegui_passo(giro, modalita=modalita, leggi=leggi, fondi=fondi,
                             limite_lettura=limite_lettura, elenco_max=elenco_max)
    except Exception as e:
        return {"status": "errore", "giro": giro, "motivo": type(e).__name__}


def _esegui_passo(
    giro: str | None,
    *,
    modalita: str | None,
    leggi: Any,
    fondi: Any,
    limite_lettura: int | None = None,
    elenco_max: int | None = TETTO_ELENCO_FUSIONI,
) -> dict[str, Any]:
    if modalita is None:
        modalita = _impostazione("gemelli_modalita", MODALITA_OMBRA)
    modalita = MODALITA_ATTIVO if str(modalita).strip().lower() == MODALITA_ATTIVO else MODALITA_OMBRA

    if leggi is None or fondi is None:
        from . import db
        leggi = leggi or (lambda: db.select_pubblicati_per_gemelli(limit=None, con_calendario=True))
        fondi = fondi or db.fondi_bandi

    lette = list(leggi())
    if limite_lettura is not None and len(lette) >= limite_lettura:
        # Corpus tagliato: le righe per URL sarebbero sottostimate e un hub
        # potrebbe sembrare una coppia. Meglio nessuna fusione.
        return {"status": "errore", "giro": giro, "modalita": modalita,
                "motivo": "lettura_troncata", "lette": len(lette)}
    righe = [r for r in lette if r.get("bando_master_id") is None]
    # Le righe per URL si contano solo sui pubblicati NON fusi (B4, giro 3
    # §11): un doppione gia' fuso nel master non e' un'altra pagina che porta
    # l'URL, e contarlo farebbe sembrare un hub la coppia rimasta. Oggi la
    # lettura prende solo `pubblicato=true` e `bando_fondi` spegne il doppione,
    # quindi il risultato non cambia: la regola sta qui, non nel filtro di db.
    righe_per_url = Counter(url for riga in righe for url in url_del_bando(riga))
    coppie = []
    scartate: dict[str, int] = {}
    hub: set[str] = set()
    for a, b, corrispondenza in coppie_certe(righe):
        motivo = motivo_di_prudenza(a, b, corrispondenza, righe_per_url)
        if motivo is None:
            coppie.append((a, b, corrispondenza))
            continue
        scartate[motivo] = scartate.get(motivo, 0) + 1
        if motivo == PRUDENZA_URL_CONDIVISO:
            hub.add(corrispondenza.dettaglio)
    tutti = gruppi_di_gemelli(coppie)
    # Solo i gruppi di due righe: il doppione ha una coppia prudente diretta
    # col master. Una catena si guarda a mano (`fondi-doppioni`).
    gruppi = [g for g in tutti if len(g[1]) == 1]
    in_gruppi = {r.get("id") for master, doppioni in gruppi for r in [master, *(d for d, _ in doppioni)]}
    coppie = [c for c in coppie if c[0].get("id") in in_gruppi]

    contatori: dict[str, Any] = {
        "status": "ok", "giro": giro, "modalita": modalita,
        "esaminati": len(righe),
        "coppie_per_criterio": {nome: 0 for nome in CRITERI_ESATTI},
        "coppie_scartate_per_prudenza": scartate,
        "hub_esclusi": len(hub),
        "gruppi": len(gruppi),
        "gruppi_oltre_due": len(tutti) - len(gruppi),
        "fusioni_previste": sum(len(doppioni) for _master, doppioni in gruppi),
        "fusi": 0, "fusioni_non_riuscite": 0, "master_corretti": 0,
        "fusioni": [],
    }
    for _a, _b, corrispondenza in coppie:
        per_criterio = contatori["coppie_per_criterio"]
        per_criterio[corrispondenza.criterio] = per_criterio.get(corrispondenza.criterio, 0) + 1

    for master, doppioni in gruppi:
        for doppione, criterio in doppioni:
            voce = [doppione.get("id"), master.get("id"), criterio]
            if elenco_max is None or len(contatori["fusioni"]) < elenco_max:
                contatori["fusioni"].append(voce)
            if modalita != MODALITA_ATTIVO:
                continue
            effettivo = fondi(master.get("id"), doppione.get("id"), f"{MOTIVO_FUSIONE}: {criterio}")
            if effettivo is None:
                contatori["fusioni_non_riuscite"] += 1
                continue
            contatori["fusi"] += 1
            if effettivo != master.get("id"):
                contatori["master_corretti"] += 1
    from .telemetria import copertura
    previste = contatori["fusioni_previste"]
    fatti = contatori["fusi"] if modalita == MODALITA_ATTIVO else previste
    contatori["copertura"] = copertura(previste, fatti, "errore")
    return contatori
