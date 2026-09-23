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
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from .dominio_ufficiale import dominio_di, e_aggregatore, registrabile
from .impronte import normalizza_url
from .normalize import normalize_for_canonical

SOGLIA_FUZZY = 0.92

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
_RE_LOTTO = re.compile(r"\b(?:lotto|lot|edizion\w*|annualit\w*|finestra|tranche)\s+([\w°]+)", re.I)


# --- tipi -------------------------------------------------------------------

@dataclass(frozen=True)
class Corrispondenza:
    """Un gemello certo: autorizza `bando_fondi`, in modalita' attiva."""
    bando_id: Any
    criterio: str                      # url | chiave_esterna | atto
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
    normalizzati = [normalizza_url(u) for u in grezzi if u]
    return tuple(dict.fromkeys(u for u in normalizzati if u))


def link_del_bando(riga: Mapping[str, Any]) -> str | None:
    """Il solo `link_bando` normalizzato: e' l'URL della riga presso la sua
    fonte, l'unico che identifica *quella* riga e non la pagina d'ente a cui
    puo' puntare insieme a molte altre."""
    return normalizza_url(_testo(riga, "link_bando"))


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
    return normalize_for_canonical(_testo(riga, "titolo", "titolo_raw"))


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


# --- criteri esatti ---------------------------------------------------------

def criteri_esatti(
    candidato: Mapping[str, Any],
    pubblicati: Iterable[Mapping[str, Any]],
) -> tuple[Corrispondenza, ...]:
    """I gemelli certi del candidato fra le righe pubblicate.

    Tre criteri, tutti esatti e tutti verificabili da chiunque rilegga la riga:
      1. `url`  — un URL normalizzato del candidato (`link_bando` o
         `fonte_ufficiale_url`) coincide con uno di un pubblicato e almeno uno
         dei due e' un `link_bando`. **Nessun vincolo di stessa fonte**
         (§16.2 M9), ma nemmeno la coppia fonte ufficiale contro fonte
         ufficiale, che due lotti dello stesso ente condividono;
      2. `chiave_esterna` — stessa fonte e stessa chiave: e' la stessa riga
         presso la fonte, con l'URL cambiato;
      3. `atto` — stesso atto numerato sullo stesso dominio ufficiale.
    """
    chiave = chiave_esterna(candidato)
    atto = numero_atto(candidato)
    dominio = dominio_ufficiale_riga(candidato)
    identificativo = candidato.get("id")

    trovate: list[Corrispondenza] = []
    for riga in pubblicati:
        if identificativo is not None and riga.get("id") == identificativo:
            continue
        comuni = coincidenze_url(candidato, riga)
        if comuni:
            trovate.append(Corrispondenza(riga.get("id"), "url", comuni[0]))
            continue
        if chiave and chiave_esterna(riga) == chiave and _stessa_fonte(candidato, riga):
            trovate.append(Corrispondenza(riga.get("id"), "chiave_esterna", chiave))
            continue
        if atto and dominio and numero_atto(riga) == atto and dominio_ufficiale_riga(riga) == dominio:
            trovate.append(Corrispondenza(riga.get("id"), "atto", f"{atto}@{dominio}"))
    return tuple(trovate)


def _stessa_fonte(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """La chiave esterna e' unica **per fonte** (UNIQUE (fonte_id, chiave_esterna)):
    fuori da quella coppia non dimostra niente."""
    return a.get("fonte_id") is not None and a.get("fonte_id") == b.get("fonte_id")


# --- fuzzy: solo proposte ---------------------------------------------------

def _blocco(candidato: Mapping[str, Any], riga: Mapping[str, Any]) -> str:
    regione_a = normalize_for_canonical(_testo(candidato, "regione", "area_geografica"))
    regione_b = normalize_for_canonical(_testo(riga, "regione", "area_geografica"))
    if regione_a and regione_a == regione_b:
        return "regione"
    ente_a = normalize_for_canonical(_testo(candidato, "ente_erogatore", "ente"))
    ente_b = normalize_for_canonical(_testo(riga, "ente_erogatore", "ente"))
    if ente_a and ente_a == ente_b:
        return "ente"
    host_a = dominio_di(_testo(candidato, "link_bando"))
    host_b = dominio_di(_testo(riga, "link_bando"))
    if host_a and host_a == host_b:
        return "host"
    return ""


def _differenze(a: str, b: str) -> tuple[str, ...]:
    """Anni e numeri di lotto/edizione che compaiono in un titolo e non
    nell'altro: il motivo per cui una proposta quasi certa va guardata."""
    trovate: list[str] = []
    anni_a, anni_b = set(_RE_ANNO.findall(a)), set(_RE_ANNO.findall(b))
    for anno in sorted(anni_a ^ anni_b):
        trovate.append(f"anno {anno}")
    lotti_a = {m.group(0).lower() for m in _RE_LOTTO.finditer(a)}
    lotti_b = {m.group(0).lower() for m in _RE_LOTTO.finditer(b)}
    for lotto in sorted(lotti_a ^ lotti_b):
        trovate.append(re.sub(r"\s+", " ", lotto))
    return tuple(trovate)


def possibili_doppioni(
    candidato: Mapping[str, Any],
    pubblicati: Iterable[Mapping[str, Any]],
    *,
    soglia: float = SOGLIA_FUZZY,
) -> tuple[Proposta, ...]:
    """Proposte `possibile_doppione`, mai applicate (§5 passo 2, §14).

    Blocking obbligatorio (regione, ente o host: senza, si confronterebbero
    2 100 titoli con 2 100 titoli) e `difflib.SequenceMatcher` ≥ 0,92 sui titoli
    normalizzati. I gemelli certi sono esclusi: li ha gia' detti `criteri_esatti`
    e qui farebbero solo rumore nel report.
    """
    titolo = titolo_normalizzato(candidato)
    if not titolo:
        return ()
    righe = list(pubblicati)
    esatti = {c.bando_id for c in criteri_esatti(candidato, righe)}
    identificativo = candidato.get("id")

    proposte: list[Proposta] = []
    for riga in righe:
        if riga.get("id") in esatti:
            continue
        if identificativo is not None and riga.get("id") == identificativo:
            continue
        blocco = _blocco(candidato, riga)
        if not blocco:
            continue
        altro = titolo_normalizzato(riga)
        if not altro:
            continue
        similarita = difflib.SequenceMatcher(None, titolo, altro).ratio()
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
