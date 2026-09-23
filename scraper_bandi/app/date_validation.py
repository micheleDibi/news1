"""Validation helpers per date estratte da LLM (preprocess + bando_resolver + enricher).

Triple-gate sulle date:
  1. ISO format check (YYYY-MM-DD)
  2. Source autoritativo (official_pdf | official_page)
  3. Quote sottostringa del markdown (confronto normalizzato con `norm_cit`)
     E la data dichiarata coincide con UNA delle date della quote che abbia un
     ruolo compatibile con il campo (`estrai_date_con_ruolo`, fix 8.a.24:
     prima si confrontava solo la PRIMA data, quindi «dal 01/03/2026 al
     30/09/2026» non poteva mai validare la scadenza 30/09).

Le date che falliscono il gate vengono coercite a None.
Originariamente in enricher.py (v7); estratto qui per riuso da preprocess v2.

Regole di ruolo (piano §6.2, Verify-1 A4):
  (1) i costrutti «dal X al Y» / «dalle ore … del X alle ore … del Y» si
      valutano PER PRIMI: X = apertura, Y = scadenza (anno o mese di X
      ereditati da Y se elisi: «dal 22 ottobre al 1° dicembre 2026»);
  (2) per le altre date si cercano parole chiave con confini di parola e
      forme flesse nei 40 caratteri precedenti la data;
  (3) la parola chiave PIU' VICINA decide se e' normativa (la data di un atto
      citato non e' mai una data del bando);
  (4) parole di ruoli DIVERSI del bando nella stessa finestra, senza
      costrutto, danno ruolo `ignoto` (il testo non basta a decidere).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date as date_cls, datetime as datetime_cls, time as time_cls
from typing import Any

from .logger import logger
from .stato_bando import ROMA, oggi_roma, stato_effettivo


_AUTHORITATIVE_SOURCES = {"official_pdf", "official_page"}

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_DATE_IN_QUOTE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})"                                  # ISO
    r"|(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})"               # DD/MM/YYYY o DD-MM-YYYY o DD.MM.YYYY
    r"|(\d{1,2})\s+(gen(?:naio)?|feb(?:braio)?|mar(?:zo)?|apr(?:ile)?|mag(?:gio)?|giu(?:gno)?|"
    r"lug(?:lio)?|ago(?:sto)?|set(?:tembre)?|ott(?:obre)?|nov(?:embre)?|dic(?:embre)?)\s+(\d{4})",  # 31 dicembre 2026
    re.IGNORECASE,
)

_MONTH_IT = {
    "gen": 1, "gennaio": 1,
    "feb": 2, "febbraio": 2,
    "mar": 3, "marzo": 3,
    "apr": 4, "aprile": 4,
    "mag": 5, "maggio": 5,
    "giu": 6, "giugno": 6,
    "lug": 7, "luglio": 7,
    "ago": 8, "agosto": 8,
    "set": 9, "sett": 9, "settembre": 9,
    "ott": 10, "ottobre": 10,
    "nov": 11, "novembre": 11,
    "dic": 12, "dicembre": 12,
}


def parse_iso(s: str | None) -> date_cls | None:
    if not s or not _ISO_DATE_RE.match(s):
        return None
    try:
        return date_cls.fromisoformat(s)
    except ValueError:
        return None


def extract_date_from_quote(quote: str) -> date_cls | None:
    """Cerca UNA data nella quote (ISO, DD/MM/YYYY, '31 dicembre 2026'). Prima match.

    Mantenuta per compatibilita': la validazione usa `estrai_date_con_ruolo`.
    """
    m = _DATE_IN_QUOTE_RE.search(quote)
    if not m:
        return None
    if m.group(1):  # ISO
        return parse_iso(m.group(1))
    if m.group(2):  # DD/MM/YYYY
        try:
            return date_cls(int(m.group(4)), int(m.group(3)), int(m.group(2)))
        except ValueError:
            return None
    if m.group(5):  # 31 dicembre 2026
        month_key = m.group(6).lower()
        month = _MONTH_IT.get(month_key) or _MONTH_IT.get(month_key[:3])
        if not month:
            return None
        try:
            return date_cls(int(m.group(7)), month, int(m.group(5)))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Normalizzazione delle citazioni (gate G1 del monitor e confronto quote/testo)
# ---------------------------------------------------------------------------

_APOSTROFI_RE = re.compile("[\u2019\u2018\u00b4`]")   # ’ ‘ ´ `
_TRATTINI_RE = re.compile("[\u2013\u2014]")           # – —
_SPAZI_RE = re.compile(r"\s+")


def norm_cit(testo: str | None) -> str:
    """Forma canonica di una citazione: NFKC, casefold, NBSP -> spazio, spazi
    compressi, apostrofi tipografici -> ', trattini lunghi -> -.

    Le sostituzioni di apostrofi e trattini precedono NFKC perche' NFKC
    scompone «´» in spazio + accento combinante.
    """
    if not testo:
        return ""
    t = _APOSTROFI_RE.sub("'", testo)
    t = _TRATTINI_RE.sub("-", t)
    t = unicodedata.normalize("NFKC", t)
    t = t.replace("\u00a0", " ")
    t = t.casefold()
    return _SPAZI_RE.sub(" ", t).strip()


# ---------------------------------------------------------------------------
# Date con ruolo
# ---------------------------------------------------------------------------

RUOLI_DATA = frozenset({"apertura", "scadenza", "pubblicazione", "normativa", "ignoto"})

_FINESTRA_PAROLE = 40  # caratteri prima della data in cui cercare le parole chiave

_MESE_RE = (
    r"(?:gen(?:naio)?|feb(?:braio)?|mar(?:zo)?|apr(?:ile)?|mag(?:gio)?|giu(?:gno)?|"
    r"lug(?:lio)?|ago(?:sto)?|sett?(?:embre)?|ott(?:obre)?|nov(?:embre)?|dic(?:embre)?)"
)


def _pattern_data(prefisso: str, anno_opzionale: bool = False, solo_giorno: bool = False) -> str:
    """Regex di una data nei formati ISO, DD/MM/YYYY (anche . e -), «1° dicembre 2026».

    I gruppi sono prefissati per poter combinare due date nello stesso pattern.
    Con anno_opzionale la data puo' essere «22 ottobre» / «22/10» (anno eliso);
    con solo_giorno anche «22» (per «dal 22 al 30 settembre 2026»).
    """
    anno_num = r"[/.\-](?P<P_an>\d{4})"
    anno_txt = r"\s+(?P<P_at>\d{4})"
    if anno_opzionale:
        anno_num = "(?:" + anno_num + ")?"
        anno_txt = "(?:" + anno_txt + ")?"
    rami = [
        r"(?P<P_iso>\d{4}-\d{2}-\d{2})",
        r"(?P<P_gn>\d{1,2})[/.\-](?P<P_mn>\d{1,2})" + anno_num,
        r"(?P<P_gt>\d{1,2})(?:\s*[°º])?\s+(?P<P_mt>" + _MESE_RE + r")\b\.?" + anno_txt,
    ]
    if solo_giorno:
        rami.append(r"(?P<P_g>\d{1,2})(?:\s*[°º])?")
    return (r"(?<!\d)(?:" + "|".join(rami) + r")(?!\d)").replace("P_", prefisso)


_DATA_RE = re.compile(_pattern_data(""), re.IGNORECASE)

# «dalle ore 12:00 del X» / «alle ore 12:00 del Y»: l'orario e' opzionale.
_ORA_DEL = r"(?:\s+(?:le\s+)?ore\s+\d{1,2}(?:[:.,]\d{2})?\s+del)?"

# Costrutto «dal X al Y» (regola 1). X puo' avere anno o mese elisi, Y no.
_COSTRUTTO_RE = re.compile(
    r"\b(?:dal|dalle)\b" + _ORA_DEL + r"\s+(?:giorno\s+)?"
    r"(?P<x>" + _pattern_data("x", anno_opzionale=True, solo_giorno=True) + r")"
    r"\s*,?\s+(?:e\s+)?(?:fino\s+|sino\s+)?(?:al|alle)\b" + _ORA_DEL + r"\s+(?:giorno\s+)?"
    r"(?P<y>" + _pattern_data("y") + r")",
    re.IGNORECASE,
)

# Parole chiave per ruolo (regola 2): confini di parola e forme flesse. Le
# sigle (BUR*, GURI, DD, DGR) restano sensibili alle maiuscole.
_PAROLE_RUOLO: dict[str, re.Pattern[str]] = {
    "scadenza": re.compile(r"(?i:\bscadenz\w*|\bentro\b|\btermin[ei]\b|\bfino al\b|\bchius\w*)"),
    "apertura": re.compile(r"(?i:\bapertur\w*|\ba partire\b|\bdecorr\w*|\bdal(?:le)?\b)"),
    "pubblicazione": re.compile(r"(?i:\bpubblicat\w*)|\bBUR\w*|\bGURI\b"),
    "normativa": re.compile(
        r"(?i:\bDet\.|\bDeterminazion\w*|\bDecret\w*|\bDeliber\w*|\bai sensi\b)|\bDD\b|\bDGR\b"
    ),
}


@dataclass(frozen=True)
class DataConRuolo:
    """Una data trovata nel testo, con il ruolo dedotto dal contesto.

    inizio/fine sono gli offset della data nel testo di partenza; citazione e'
    il frammento di testo (parole chiave + data, o l'intero costrutto) che
    giustifica il ruolo.
    """
    data: date_cls
    ruolo: str
    inizio: int
    fine: int
    citazione: str


def _componi(anno: int, mese: int, giorno: int) -> date_cls | None:
    try:
        return date_cls(anno, mese, giorno)
    except (TypeError, ValueError):
        return None


def _mese_da_nome(nome: str) -> int | None:
    chiave = nome.lower()
    return _MONTH_IT.get(chiave) or _MONTH_IT.get(chiave[:3])


def _componenti(m: re.Match[str], p: str) -> tuple[int, int | None, int | None] | None:
    """(giorno, mese, anno) dai gruppi con prefisso p; None se nessun ramo ha
    fatto match o il mese testuale non e' riconosciuto. Le parti elise sono None."""
    g = m.groupdict()
    if g.get(p + "iso"):
        d = parse_iso(g[p + "iso"])
        return (d.day, d.month, d.year) if d else None
    if g.get(p + "gn"):
        anno = g.get(p + "an")
        return (int(g[p + "gn"]), int(g[p + "mn"]), int(anno) if anno else None)
    if g.get(p + "gt"):
        mese = _mese_da_nome(g[p + "mt"])
        if mese is None:
            return None
        anno = g.get(p + "at")
        return (int(g[p + "gt"]), mese, int(anno) if anno else None)
    if g.get(p + "g"):
        return (int(g[p + "g"]), None, None)
    return None


def _date_del_costrutto(m: re.Match[str]) -> tuple[date_cls, date_cls] | None:
    """(X, Y) di un costrutto «dal X al Y»; X eredita da Y l'anno (o mese e
    anno) elisi. Se cosi' X > Y si arretra di un anno (o di un mese):
    «dal 15 dicembre al 31 gennaio 2027», «dal 25 al 5 ottobre 2026»."""
    cy = _componenti(m, "y")
    if not cy or cy[1] is None or cy[2] is None:
        return None
    y = _componi(cy[2], cy[1], cy[0])
    if y is None:
        return None
    cx = _componenti(m, "x")
    if not cx:
        return None
    gx, mx, ax = cx
    if mx is None:
        x = _componi(y.year, y.month, gx)
        if x is not None and x > y:
            mese_prec = y.month - 1 or 12
            anno_prec = y.year if y.month > 1 else y.year - 1
            x = _componi(anno_prec, mese_prec, gx)
    elif ax is None:
        x = _componi(y.year, mx, gx)
        if x is not None and x > y:
            x = _componi(y.year - 1, mx, gx)
    else:
        x = _componi(ax, mx, gx)
    if x is None:
        return None
    return (x, y)


def _ruolo_dalla_finestra(testo: str, inizio: int) -> tuple[str, int]:
    """Ruolo di una data isolata dai <=40 caratteri che la precedono (regole 2-4).

    Ritorna (ruolo, offset di inizio della finestra) per costruire la citazione.
    """
    da = max(0, inizio - _FINESTRA_PAROLE)
    finestra = testo[da:inizio]
    distanze: dict[str, int] = {}
    for ruolo, pattern in _PAROLE_RUOLO.items():
        fine = max((mm.end() for mm in pattern.finditer(finestra)), default=None)
        if fine is not None:
            distanze[ruolo] = len(finestra) - fine
    if not distanze:
        return ("ignoto", da)
    # Regola 3: la parola piu' vicina decide se la data e' di un atto citato.
    piu_vicino = min(distanze, key=lambda r: distanze[r])
    if piu_vicino == "normativa":
        return ("normativa", da)
    # Regola 4: ruoli diversi del bando nella stessa finestra -> ignoto.
    ruoli_bando = [r for r in distanze if r != "normativa"]
    if len(ruoli_bando) == 1:
        return (ruoli_bando[0], da)
    return ("ignoto", da)


def estrai_date_con_ruolo(testo: str | None) -> list[DataConRuolo]:
    """Tutte le date del testo con il ruolo dedotto, ordinate per posizione.

    Riconosce ISO, DD/MM/YYYY (anche . e -), «1° dicembre 2026», «1 dicembre
    2026», «dal 22 ottobre al 1° dicembre 2026» (anno eliso sulla prima data),
    «entro le ore 12:00 del 30/09/2026». Le date senza anno fuori da un
    costrutto non vengono estratte (troppo ambigue).
    """
    if not testo:
        return []
    trovate: list[DataConRuolo] = []
    occupati: list[tuple[int, int]] = []

    # Regola 1: i costrutti «dal X al Y» prima di tutto.
    for m in _COSTRUTTO_RE.finditer(testo):
        coppia = _date_del_costrutto(m)
        if coppia is None:
            continue
        x, y = coppia
        citazione = m.group(0)
        trovate.append(DataConRuolo(x, "apertura", m.start("x"), m.end("x"), citazione))
        trovate.append(DataConRuolo(y, "scadenza", m.start("y"), m.end("y"), citazione))
        occupati.append((m.start(), m.end()))

    # Regole 2-4: le date rimanenti, con la finestra di parole chiave.
    for m in _DATA_RE.finditer(testo):
        if any(m.start() < fine and m.end() > inizio for inizio, fine in occupati):
            continue
        comp = _componenti(m, "")
        if not comp or comp[1] is None or comp[2] is None:
            continue
        d = _componi(comp[2], comp[1], comp[0])
        if d is None:
            continue
        ruolo, da = _ruolo_dalla_finestra(testo, m.start())
        trovate.append(DataConRuolo(d, ruolo, m.start(), m.end(), testo[da:m.end()].strip()))

    trovate.sort(key=lambda dr: dr.inizio)
    return trovate


_RUOLI_COMPATIBILI: dict[str, frozenset[str]] = {
    "apertura": frozenset({"apertura", "ignoto"}),
    "scadenza": frozenset({"scadenza", "ignoto"}),
    "pubblicazione": frozenset({"pubblicazione", "ignoto"}),
}


def ruolo_compatibile(ruolo: str, label: str) -> bool:
    """True se una data con quel ruolo puo' valere per il campo `label`:
    'ignoto' vale per tutto, 'normativa' mai; una label non standard (solo
    per log) accetta qualunque ruolo non normativo."""
    if ruolo == "normativa":
        return False
    ammessi = _RUOLI_COMPATIBILI.get(label)
    return True if ammessi is None else ruolo in ammessi


def validate_date_candidate(
    candidate: dict[str, Any] | None,
    html_text: str,
    bando_id: Any,
    label: str,
    log_prefix: str = "date",
    provenienza: str | None = None,
) -> date_cls | None:
    """Triple-gate sulla candidata date emessa dal LLM.

    Ritorna la data parsed se passa, altrimenti None.
    Argomenti:
      candidate: {date: ISO, source: enum, quote: str} dal tool_use
      html_text: markdown contro cui verificare substring (richiesto)
      bando_id: per logging
      label: 'pubblicazione' | 'apertura' | 'scadenza' (decide il ruolo ammesso)
      log_prefix: prefix nei log debug (es. 'preprocess/date' o 'enricher/date')
      provenienza: classificazione dell'host da cui viene html_text decisa dal
        codice (fix 8.a.23), es. 'ente' | 'aggregatore'. Con 'aggregatore' la
        data viene comunque ritornata ma segnalata nel log: andra' scritta con
        data_*_verificata=false quando le colonne esisteranno.
    """
    if not candidate or not isinstance(candidate, dict):
        return None
    raw_date = candidate.get("date")
    source = candidate.get("source") or ""
    quote = candidate.get("quote") or ""

    if not raw_date or not isinstance(raw_date, str):
        return None
    parsed = parse_iso(raw_date)
    if parsed is None:
        logger.debug("[{}] bando_id={} {} date non ISO: {!r}", log_prefix, bando_id, label, raw_date)
        return None
    if source not in _AUTHORITATIVE_SOURCES:
        logger.debug("[{}] bando_id={} {} source non autoritativa: {!r}", log_prefix, bando_id, label, source)
        return None
    if not quote or not isinstance(quote, str):
        logger.debug("[{}] bando_id={} {} quote vuota", log_prefix, bando_id, label)
        return None
    quote_norm = norm_cit(quote)
    if not quote_norm or quote_norm not in norm_cit(html_text):
        logger.debug("[{}] bando_id={} {} quote NON substring del markdown", log_prefix, bando_id, label)
        return None
    date_quote = estrai_date_con_ruolo(quote)
    compatibili = [d for d in date_quote if d.data == parsed and ruolo_compatibile(d.ruolo, label)]
    if not compatibili:
        logger.debug(
            "[{}] bando_id={} {} nessuna data compatibile nella quote: declared={} trovate={}",
            log_prefix, bando_id, label, parsed,
            [(d.data.isoformat(), d.ruolo) for d in date_quote],
        )
        return None
    if provenienza == "aggregatore":
        logger.info(
            "[{}] bando_id={} {} data {} letta da host aggregatore: da registrare con "
            "verificata=false (colonna non ancora a DB)",
            log_prefix, bando_id, label, parsed,
        )
    return parsed


def check_dates_coherence(
    pub: date_cls | None,
    apt: date_cls | None,
    scad: date_cls | None,
) -> bool:
    """True se l'ordine pub <= apt <= scad e' rispettato tra le date non-None.
    False se almeno una coppia viola l'ordine.
    """
    if pub and apt and pub > apt:
        return False
    if apt and scad and apt > scad:
        return False
    if pub and scad and pub > scad:
        return False
    return True


def reconcile_stato_bando(
    stato_llm: str | None,
    data_apertura: date_cls | None,
    data_scadenza: date_cls | None,
    today: date_cls | None = None,
) -> str | None:
    """Reconciliation guard data-driven.

    Forza:
      - data_scadenza < today -> 'chiuso' (ignora LLM)
      - data_apertura > today -> 'in apertura prossimamente'
      - stato_llm in ('aperto','chiuso','in apertura prossimamente') -> ritorna tale
      - stato_llm == 'unknown' -> None (NULL in DB)
      - altrimenti None

    `today` e' la data civile italiana (`oggi_roma`), non quella UTC della
    macchina (fix 8.a.15).

    Wrapper di `stato_bando.stato_effettivo` (piano §4: una sola regola in tre
    linguaggi). Qui restano le due specificita' della SCRITTURA, che la lettura
    non ha: lo stato dell'LLM fuori vocabolario diventa NULL PRIMA del calcolo
    (altrimenti un 'sospeso' allucinato passerebbe come stato salvato) e
    un'apertura futura porta a 'in apertura prossimamente' anche quando l'LLM
    diceva altro. La precedenza resta quella di sempre: la scadenza passata
    vince sull'apertura futura.
    """
    if today is None:
        today = oggi_roma()

    stato = stato_llm if stato_llm in ("aperto", "chiuso", "in apertura prossimamente") else None
    if data_apertura is not None and data_apertura > today:
        stato = "in apertura prossimamente"
    # Mezzogiorno di Roma: questa firma non ha le ore (le colonne ora_* non
    # esistono a monte) e a mezzogiorno nessun cambio d'ora e' ambiguo.
    adesso = datetime_cls.combine(today, time_cls(12, 0), tzinfo=ROMA)
    return stato_effettivo(
        stato,
        data_apertura=None,
        apertura_verificata=False,
        ora_apertura=None,
        data_scadenza=data_scadenza,
        ora_scadenza=None,
        adesso=adesso,
    )
