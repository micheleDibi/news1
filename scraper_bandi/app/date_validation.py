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


# ---------------------------------------------------------------------------
# Date presunte, ore e finestre (contratto `bandi-giro-2` §6.2)
# ---------------------------------------------------------------------------

#: Le parole di una data che non e' certa. A inizio parola: «imprevisto» non
#: e' una previsione.
_PRESUNTA_RE = re.compile(
    r"\b(?:presunt|indicativ|orientativ)\w*|\bsi\s+prevede\b",
    re.IGNORECASE)
_MESI_RE = (r"gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre"
            r"|novembre|dicembre")
#: «stimata», «trimestre», «semestre» valgono solo legate a una data: «data
#: stimata», «scadenza stimata», «stimata per il 30/10», «primo trimestre
#: 2026», «II semestre». «Importo stimato: 100.000 euro» non dice niente della
#: data che segue (revisione avversaria, ciclo 2).
_STIMA_DATA_RE = re.compile(
    r"\b(?:data|date|scadenz[ae]|apertur[ae]|termin[ei]|chiusur[ae]|pubblicazion[ei]|avvio)"
    r"\s+(?:\S+\s+){0,2}?stimat[oaie]\b"
    r"|\bstimat[oaie]\s+(?:per\s+(?:il\s+|l['’]\s*)?|al\s+|entro\s+(?:il\s+)?|nel\s+(?:mese\s+di\s+)?|a\s+)"
    r"(?:\d|" + _MESI_RE + r"|mese|prim|second|fine|met[aà])"
    r"|\b(?:prim[oa]|second[oa]|terz[oa]|quart[oa]|I{1,3}|IV|[1-4]\s*[°º^])\s+(?:trimestr|semestr)[ei]\b"
    r"|\b(?:trimestr|semestr)[ei]\s+(?:del(?:l['’])?\s+)?(?:anno\s+)?(?:20\d{2})\b",
    re.IGNORECASE)
#: Il soggetto di «previsto» nell'inciso: un termine (data certa) o
#: un'apertura (previsione). Conta il PRIMO dei due nell'inciso, cioe' il
#: soggetto della frase: in «L'apertura dei termini è prevista per…» i
#: termini sono un complemento (revisione #120).
_SOGGETTO_CERTO_RE = re.compile(r"\b(?:termin[ei]|scadenz[ae]|chiusur[ae])\b", re.IGNORECASE)
_SOGGETTO_PREVISTO_RE = re.compile(
    r"\b(?:(?:ri)?apertur[ae]|avvio|pubblicazion[ei]|uscit[ae])\b", re.IGNORECASE)
#: La fine di una frase per G10: l'inciso di «previsto» e il contesto di una
#: data non vanno oltre. Mai l'a capo: nel testo delle pagine l'etichetta
#: («Data presunta di apertura») sta spesso sulla riga sopra la data. Nome
#: proprio: `_FINE_FRASE_RE` piu' sotto e' quella di `termine_nel_testo`,
#: che chiude all'a capo (revisione #120).
_FINE_FRASE_G10_RE = re.compile(r"[.;!?](?=\s)")
#: Quanto indietro si cerca l'inizio della frase di una data.
_FINESTRA_FRASE = 200
#: «Previsto» in italiano vuol dire anche «stabilito»: vale come previsione
#: solo nelle forme di una previsione vera (decisione del lead, 30/09).
_PREVISTO_RE = re.compile(r"\bprevist[oaie]\b", re.IGNORECASE)
#: … e non lo e' mai dopo termine, scadenza, chiusura («Scadenza prevista dal
#: bando: 30/10/2026», «Termine ultimo previsto: …») ne' in «modalita'
#: previste» o «termini previsti».
_PREVISTO_STABILITO_RE = re.compile(
    r"(?:\b(?:termin[ei]|scadenz[ae]|chiusur[ae])(?:\s+ultim[oaie])?|\bmodalit[aà]"
    # formule di rinvio: «come previsto», «secondo quanto previsto» (revisione #91)
    r"|\bcome|\bsecondo\s+quanto)"
    r"\s+(?:(?:è|e['’])\s+)?$",
    re.IGNORECASE)
#: «previsto nel/dal/dalla/dall' bando|avviso|decreto|regolamento|disciplinare»:
#: il rinvio a un atto, non una previsione (revisione #91).
_PREVISTO_DALL_ATTO_RE = re.compile(
    r"\s+(?:nel|dal|dalla|dall['’])\s*(?:bando|avviso|decreto|regolamento|disciplinare)\b",
    re.IGNORECASE)
#: «apertura (è) prevista»: la data di un'apertura annunciata.
_APERTURA_PREVISTA_RE = re.compile(r"\bapertur[ae]\s+(?:(?:è|e['’])\s+)?$", re.IGNORECASE)
#: «prevista per / nel / nei / a partire / entro il mese | primo | secondo | fine».
_PREVISIONE_DOPO_RE = re.compile(
    r"\s+(?:per|nel|nei|a\s+partire|entro\s+(?:il\s+)?(?:mese|primo|secondo|fine))\b",
    re.IGNORECASE)


def e_presunta(citazione: str | None) -> bool:
    """Vero se la citazione dice che la data e' presunta, indicativa o prevista.

    «Previsto» e' ambiguo: «l'apertura e' prevista per il 15 novembre» e' una
    previsione, «Scadenza prevista dal bando: 30/10/2026» e' una data certa.
    Conta come previsione solo dopo «apertura» o prima di per, nel, nei, a
    partire, entro il mese/primo/secondo/fine; mai dopo termine, scadenza,
    chiusura, modalita'. Nel dubbio restante la data non si prende (G10).
    """
    if not citazione:
        return False
    if _PRESUNTA_RE.search(citazione) or _STIMA_DATA_RE.search(citazione):
        return True
    for m in _PREVISTO_RE.finditer(citazione):
        prima = citazione[max(0, m.start() - 30):m.start()]
        if _APERTURA_PREVISTA_RE.search(prima):
            return True
        if _PREVISTO_DALL_ATTO_RE.match(citazione, m.end()):
            continue
        soggetto = _soggetto_dell_inciso(citazione, m.start())
        if soggetto == "previsione":
            # Un'apertura, una pubblicazione, un avvio «previsti»: una
            # previsione anche con «termini» nel mezzo (revisione #120).
            return True
        if soggetto == "certo" or _PREVISTO_STABILITO_RE.search(prima):
            continue
        if _PREVISIONE_DOPO_RE.match(citazione, m.end()):
            return True
    return False


def _soggetto_dell_inciso(citazione: str, pos: int) -> str | None:
    """'certo', 'previsione' o None: il PRIMO soggetto dell'inciso prima di
    «previsto», dall'inizio della frase. «Il termine per la presentazione
    delle domande è previsto per il 30/10/2026» e' certo; «L'apertura dei
    termini è prevista per il 15/11/2026» e' una previsione."""
    inizio = 0
    for fine in _FINE_FRASE_G10_RE.finditer(citazione, 0, pos):
        inizio = fine.end()
    inciso = citazione[inizio:pos]
    certo = _SOGGETTO_CERTO_RE.search(inciso)
    previsione = _SOGGETTO_PREVISTO_RE.search(inciso)
    if certo is None and previsione is None:
        return None
    if previsione is None or (certo is not None and certo.start() < previsione.start()):
        return "certo"
    return "previsione"


def _intorno(testo: str, data: DataConRuolo) -> str:
    """Il contesto di una data per G10, fino alla data compresa. Parte dal
    punto piu' a destra fra: l'inizio della sua frase, la fine della data
    precedente nel testo e 200 caratteri prima (della data, o del costrutto
    «dal X al Y» che la contiene).

    Non i soli 40 caratteri di prima: «Il termine per la presentazione delle
    domande è previsto per il …» ha il soggetto lontano. Non la frase
    precedente («Importo stimato: … Scadenza: …») ne' la data precedente
    («Data indicativa di apertura: 15/11/2026 Data di scadenza: 30/11/2026»:
    l'«indicativa» e' dell'apertura). L'a capo non chiude: «Data presunta di
    apertura⏎15/11/2026» resta presunta (revisioni del ciclo 2 e #120).
    """
    inizio = data.inizio
    if data.citazione and _COSTRUTTO_RE.match(data.citazione):
        pos = testo.rfind(data.citazione, 0, data.fine)
        if pos >= 0:
            inizio = pos
    da = max(0, inizio - _FINESTRA_FRASE)
    for fine in _FINE_FRASE_G10_RE.finditer(testo, da, inizio):
        da = fine.end()
    for precedente in _DATA_RE.finditer(testo, da, inizio):
        if precedente.end() <= inizio:
            da = max(da, precedente.end())
    return testo[da:data.fine]


#: L'ora prima della data: «ore 12 del», «ore 12:00 del giorno», «le 17.00 del».
_ORA_PRIMA_RE = re.compile(
    r"(?:\bore\s+(?P<h>\d{1,2})(?:[:.,](?P<m>\d{2}))?|\ble\s+(?P<h2>\d{1,2})[:.](?P<m2>\d{2}))"
    r"\s+(?:del(?:l[a'’])?\s+)?(?:giorno\s+)?$",
    re.IGNORECASE,
)
#: Tutte le ore di un segmento, per la prima di «dalle ore 9 alle ore 18 del X».
_ORE_RE = re.compile(
    r"\bore\s+(?P<h>\d{1,2})(?:[:.,](?P<m>\d{2}))?|\ble\s+(?P<h2>\d{1,2})[:.](?P<m2>\d{2})",
    re.IGNORECASE,
)
#: L'ora dopo la data: «30/10/2026, ore 18:00», «30/10/2026 alle ore 12», «20 ottobre 2026 12:00».
#: Senza `^`: si usa con `match(testo, pos)`, che ancora gia' in `pos` (e `^` li' non vale).
_ORA_DOPO_RE = re.compile(
    r"\s*,?\s*(?:(?:(?:alle|entro\s+le|fino\s+alle)\s+)?ore\s+(?P<h>\d{1,2})(?:[:.,](?P<m>\d{2}))?\b"
    r"|(?P<h2>\d{1,2}):(?P<m2>\d{2})\b)",
    re.IGNORECASE,
)


def _ora(m: re.Match[str] | None) -> time_cls | None:
    """L'ora di un match di `_ORA_*`. «24:00» e' la fine del giorno: 23:59."""
    if m is None:
        return None
    ore = m.group("h") or m.group("h2")
    minuti = m.group("m") or m.group("m2") or "0"
    if ore is None:
        return None
    h, mi = int(ore), int(minuti)
    if h == 0 and mi == 0 and m.group("h") is None:
        # «00:00» senza «ore»: e' l'orario vuoto dei CMS, non un'ora scritta.
        # Solo «ore 00:00» per esteso vale (revisione avversaria, ciclo 2).
        return None
    if h == 24 and mi == 0:
        return time_cls(23, 59)
    if h > 23 or mi > 59:
        return None
    return time_cls(h, mi)


def _ora_prima(segmento: str, *, prima_del_segmento: bool = False) -> time_cls | None:
    """L'ora che precede la data. Con `prima_del_segmento` e piu' ore nel
    segmento («dalle ore 9 alle ore 18 del X»), vale la prima."""
    ultima = _ora(_ORA_PRIMA_RE.search(segmento))
    if ultima is None:
        return None
    if prima_del_segmento:
        tutte = list(_ORE_RE.finditer(segmento))
        if len(tutte) >= 2:
            return _ora(tutte[0])
    return ultima


def ora_nella_citazione(citazione: str | None, data: date_cls, ruolo: str = "scadenza") -> time_cls | None:
    """L'ora legata a `data` nella citazione, o None.

    Cerca la data nella citazione e guarda subito prima («entro le ore 12:00
    del 30/10/2026», «le 17.00 del 30 giugno 2026») e subito dopo («30/10/2026,
    ore 18:00»). In una finestra dello stesso giorno («dalle ore 9 alle ore 18
    del 30/10/2026») l'apertura prende la prima ora e la scadenza l'ultima.
    """
    if not citazione:
        return None
    precedente = 0
    for m in _DATA_RE.finditer(citazione):
        comp = _componenti(m, "")
        trovata = (_componi(comp[2], comp[1], comp[0])
                   if comp and comp[1] is not None and comp[2] is not None else None)
        if trovata != data:
            precedente = m.end()
            continue
        segmento = citazione[max(precedente, m.start() - 2 * _FINESTRA_PAROLE):m.start()]
        ora = _ora_prima(segmento, prima_del_segmento=(ruolo == "apertura"))
        if ora is None:
            ora = _ora(_ORA_DOPO_RE.match(citazione, m.end()))
        if ora is not None:
            return ora
        precedente = m.end()
    return None


@dataclass(frozen=True)
class Finestra:
    """Un periodo di presentazione con le ore, se il testo le dice.

    `presunta` e' vero se il contesto vicino dice che le date sono presunte o
    previste; `per_presentare` e' vero se la frase che la contiene parla di
    domande da presentare e non di fiere, eventi, spese o lavori (le regole
    del termine). Chi scrive una scadenza da una finestra (§6.3) vuole
    `per_presentare` e non `presunta`.
    """
    inizio: date_cls | None
    ora_inizio: time_cls | None
    fine: date_cls | None
    ora_fine: time_cls | None
    citazione: str
    presunta: bool = False
    per_presentare: bool = False


#: «a partire dalle ore 12:00 del 15/09/2026 ed entro le ore 18:00 del
#: 30/10/2026» (LazioEuropa): non e' un costrutto «dal X al Y», e resta fuori
#: da `_COSTRUTTO_RE`, che non cambia.
_A_PARTIRE_RE = re.compile(
    r"\ba\s+partire\s+dal(?:le|l['’])?\b" + _ORA_DEL + r"\s+(?:giorno\s+)?"
    r"(?P<x>" + _pattern_data("x") + r")"
    r"(?P<mezzo>[^.;\n]{0,160}?)"
    r"\b(?:entro|fino\s+al(?:le)?|sino\s+al(?:le)?)\b(?:\s+le)?" + _ORA_DEL
    + r"\s+(?:(?:il|giorno)\s+)?(?P<y>" + _pattern_data("y") + r")",
    re.IGNORECASE,
)


def estrai_finestra(testo: str | None) -> list[Finestra]:
    """Le finestre di presentazione del testo, in ordine di posizione.

    Due forme: il costrutto «dal X al Y» di sempre (anche «dalle ore … del X
    alle ore … del Y») e «a partire dal X … entro il Y» nella stessa frase. Le
    ore si catturano qui, senza toccare `_COSTRUTTO_RE`.
    """
    if not testo:
        return []
    trovate: list[tuple[int, Finestra]] = []
    occupati: list[tuple[int, int]] = []
    for m in _COSTRUTTO_RE.finditer(testo):
        coppia = _date_del_costrutto(m)
        if coppia is None:
            continue
        x, y = coppia
        ora_x = _ora_prima(testo[m.start():m.start("x")])
        ora_y = (_ora_prima(testo[m.end("x"):m.start("y")])
                 or _ora(_ORA_DOPO_RE.match(testo, m.end("y"))))
        contesto = testo[max(0, m.start() - _FINESTRA_PAROLE):m.end()]
        trovate.append((m.start(), Finestra(
            x, ora_x, y, ora_y, m.group(0), e_presunta(contesto),
            _per_presentare(_frase_intorno(testo, m.start(), m.end())))))
        occupati.append((m.start(), m.end()))
    for m in _A_PARTIRE_RE.finditer(testo):
        if any(m.start() < fine and m.end() > inizio for inizio, fine in occupati):
            continue
        cx, cy = _componenti(m, "x"), _componenti(m, "y")
        x = _componi(cx[2], cx[1], cx[0]) if cx and None not in cx else None
        y = _componi(cy[2], cy[1], cy[0]) if cy and None not in cy else None
        if x is None or y is None:
            continue
        ora_x = _ora_prima(testo[m.start():m.start("x")])
        ora_y = (_ora_prima(testo[m.end("mezzo"):m.start("y")])
                 or _ora(_ORA_DOPO_RE.match(testo, m.end("y"))))
        contesto = testo[max(0, m.start() - _FINESTRA_PAROLE):m.end()]
        trovate.append((m.start(), Finestra(
            x, ora_x, y, ora_y, m.group(0), e_presunta(contesto),
            _per_presentare(_frase_intorno(testo, m.start(), m.end())))))
    trovate.sort(key=lambda coppia: coppia[0])
    return [finestra for _, finestra in trovate]


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
    # G10 (contratto `bandi-giro-2` §6.2): una data presunta non e' una data.
    # Si guarda il contesto vicino a ogni data, non l'intera quote: un
    # «secondo le modalita' previste» lontano non deve far cadere il termine.
    if all(e_presunta(_intorno(quote, d)) for d in compatibili):
        logger.debug("[{}] bando_id={} {} data presunta nella quote: {}",
                     log_prefix, bando_id, label, parsed)
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


# ---------------------------------------------------------------------------
# Termini indicati (contratto `bandi-giro-2` §6.2 e §19.5)
# ---------------------------------------------------------------------------
#
# Un termine indicato e' un indizio, mai una prova: non produce eventi, dice
# solo «da qualche parte c'e' scritto che le domande chiudono il …». Ogni
# funzione restituisce (data, fonte), e la precedenza fra le fonti e' fissa.

#: Le fonti di un termine, dalla piu' affidabile (`termine_indicato_fonte`).
FONTI_TERMINE: tuple[str, ...] = ("calendario_ufficiale", "pagina", "testo", "aggregatore")

#: Un termine vale solo nella frase di una domanda da presentare.
_PRESENTAZIONE_RE = re.compile(r"domand|candidatur|presentaz|invi|istanz|iscrizion", re.IGNORECASE)
#: Le frasi che parlano d'altro: eventi e fiere (la data e' quella della
#: manifestazione), spese, progetti da concludere, rendiconti, lavori, avvio
#: delle attivita'. «Manifestazione di interesse» e' il nome di un avviso, non
#: un evento; «eventuale» non e' un evento.
_ESCLUSIONI_TERMINE_RE = re.compile(
    r"\bfier|\bevent[oi]\b|\bmanifestazion[ei]\b(?!\s+(?:di\s+|d['’]\s*)interess)"
    r"|spes[ae]\s+ammissibil|realizzazion|conclusion|ultimazion|rendicontaz|\blavori\b"
    r"|\bavvi(?:o|at[aeio])\b",
    re.IGNORECASE,
)
#: Senza verbo di presentazione un termine vale solo in due forme strette
#: (decisione del lead, 30/09): l'etichetta «Scadenza[ domande|presentazione|
#: candidature]» a inizio frase o dopo una punteggiatura, con la data subito
#: dopo (al massimo 20 caratteri, solo separatori, «il», «del», «entro» e
#: l'ora), e lo sportello «(aperto) fino al <data>» o «chiude il <data>».
_ETICHETTA_SCADENZA_RE = re.compile(
    r"(?:^|[.;:!?(\-–—,]\s*)scadenz[ae]"
    r"(?:\s+(?:domand[ae]|presentazion[ei]|candidatur[ae]))?"
    r"(?P<tra>[\s:\-–]*(?:(?:il|del|entro(?:\s+il)?|alle|ore\s+\d{1,2}(?:[:.]\d{2})?)\s+)*)$",
    re.IGNORECASE,
)
_MAX_TRA_ETICHETTA = 20
_SPORTELLO_RE = re.compile(
    r"\bsportello\s+(?:aperto\s+)?(?:dal(?:le|l['’])?\s+[^.;]{1,40}?\s+)?fino\s+al(?:le)?\s+$",
    re.IGNORECASE,
)
#: «lo sportello chiude il <data>»: la chiusura la dice la forma stessa, e
#: «chiude» non e' fra le parole di scadenza, quindi qui vale anche il ruolo
#: «ignoto».
_SPORTELLO_CHIUDE_RE = re.compile(r"\blo\s+sportello\s+chiude\s+il\s+$", re.IGNORECASE)
#: Una frase finisce a un punto, punto e virgola, punto esclamativo o
#: interrogativo seguito da una maiuscola, o a un a capo: «D.P.R. 445» e
#: «entro le 17.00» non spezzano niente.
_FINE_FRASE_RE = re.compile(r"(?<=[.;!?])\s+(?=[A-ZÀ-ÖØ-Þ«\"“(])|\n+")


def _frasi(testo: str) -> list[str]:
    return [f for f in (p.strip() for p in _FINE_FRASE_RE.split(testo)) if f]


def _frase_intorno(testo: str, inizio: int, fine: int) -> str:
    """La frase di `testo` che contiene l'intervallo [inizio, fine)."""
    da, a = 0, len(testo)
    for confine in _FINE_FRASE_RE.finditer(testo):
        if confine.end() <= inizio:
            da = confine.end()
        elif confine.start() >= fine:
            a = confine.start()
            break
    return testo[da:a]


def _per_presentare(frase: str) -> bool:
    """La frase parla di domande da presentare e non d'altro."""
    return (_PRESENTAZIONE_RE.search(frase) is not None
            and _ESCLUSIONI_TERMINE_RE.search(frase) is None)


def _forma_stretta(frase: str, data: DataConRuolo) -> bool:
    """La data di una frase senza verbo e' in una delle due forme strette."""
    prima = frase[:data.inizio]
    if data.ruolo == "ignoto":
        return _SPORTELLO_CHIUDE_RE.search(prima[-80:]) is not None
    etichetta = _ETICHETTA_SCADENZA_RE.search(prima)
    if etichetta is not None and len(etichetta.group("tra")) <= _MAX_TRA_ETICHETTA:
        return True
    return _SPORTELLO_RE.search(prima[-80:]) is not None


def _termini_della_frase(frase: str) -> list[date_cls]:
    """Le date di scadenza certe di una frase, con le regole del termine."""
    if _ESCLUSIONI_TERMINE_RE.search(frase):
        return []
    con_verbo = _PRESENTAZIONE_RE.search(frase) is not None
    termini = []
    for data in estrai_date_con_ruolo(frase):
        if data.ruolo not in ("scadenza", "ignoto"):
            continue
        # Con il verbo vale ogni scadenza; il resto (e il ruolo «ignoto», che
        # vale solo per «lo sportello chiude il») passa dalle forme strette.
        if not (con_verbo and data.ruolo == "scadenza") and not _forma_stretta(frase, data):
            continue
        # Un solo percorso di validazione: substring, ruolo e G10 (date presunte).
        candidata = {"date": data.data.isoformat(), "source": "official_page", "quote": frase}
        if validate_date_candidate(candidata, frase, None, "scadenza", log_prefix="termine"):
            termini.append(data.data)
    return termini


def _termine_dei_testi(*testi: str | None) -> date_cls | None:
    """La data di scadenza piu' tarda fra le frasi dei testi, o None."""
    termini = [d for testo in testi if testo for frase in _frasi(testo)
               for d in _termini_della_frase(frase)]
    return max(termini, default=None)


def termine_nel_testo(titolo: str | None, descrizione_breve: str | None) -> date_cls | None:
    """Il termine che titolo e descrizione breve indicano, o None (§6.2).

    Regole: solo il ruolo «scadenza» di `estrai_date_con_ruolo`; nella stessa
    frase un verbo di presentazione (oppure una delle due forme strette); via le
    frasi di fiere, eventi, spese, progetti, rendiconti, lavori e avvio
    attivita'; niente date presunte; con piu' date, la piu' tarda. Non e' MAI
    una prova e non produce eventi. I due testi si leggono separati: il titolo
    non ha il punto finale e si incollerebbe alla prima frase.
    """
    return _termine_dei_testi(titolo, descrizione_breve)


def termine_nella_pagina(testo: str | None) -> tuple[date_cls, str] | None:
    """Le regole di `termine_nel_testo` sul testo della pagina: (data, 'pagina')."""
    data = _termine_dei_testi(testo)
    return (data, "pagina") if data is not None else None


#: Le fonti di scraping che sono calendari ufficiali degli inviti: Valle
#: d'Aosta FSE+ (280) e JTF (296). Un altro raw_data non e' un calendario.
FONTI_CALENDARIO: frozenset[int] = frozenset({280, 296})
#: La colonna di chiusura del calendario JTF, a spazi tolti: nel DB la
#: chiave e' «DATA_CHIUSUR A», spezzata dall'intestazione dell'xlsx.
_COLONNA_CHIUSURA = "DATA_CHIUSURA"
#: Le frasi di chiusura del calendario VdA: «chiusura domande: 15 luglio
#: 2029», «chiusura: 30 ottobre 2026», «in corso fino a 31 dicembre 2026»,
#: «aperta fino al 31 dicembre 2025». La data deve seguire subito ed essere
#: completa: «chiusura domande: 2029» e «chiusura a marzo 2030» non valgono.
_FRASE_CHIUSURA_RE = re.compile(
    r"(?:\bchiusura(?:\s+(?:delle\s+)?domande)?\s*:?|\bin\s+corso\s+fino\s+al?|\baperta\s+fino\s+al)"
    r"\s+(?:il\s+)?",
    re.IGNORECASE,
)
_ISO_INIZIO_RE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})(?:[T\s]|$)")


def _data_completa_in(valore: str, pos: int) -> tuple[date_cls, int] | None:
    """La data completa che comincia in `pos`, con la sua fine."""
    m = _DATA_RE.match(valore, pos)
    if m is None:
        return None
    comp = _componenti(m, "")
    if not comp or comp[1] is None or comp[2] is None:
        return None
    data = _componi(comp[2], comp[1], comp[0])
    return (data, m.end()) if data is not None else None


def _data_di_colonna(valore: Any) -> date_cls | None:
    """«2026-12-31 00:00:00» o «31/12/2026»; «da definire» e il resto: None."""
    if not isinstance(valore, str) or e_presunta(valore):
        return None
    iso = _ISO_INIZIO_RE.match(valore)
    if iso:
        return parse_iso(iso.group(1))
    trovata = _data_completa_in(valore.strip(), 0)
    return trovata[0] if trovata else None


def termine_da_calendario(
    raw_data: Any, fonte_id: Any, host_verificante: bool,
) -> tuple[date_cls, str] | None:
    """Il termine di una riga di calendario ufficiale: (data, 'calendario_ufficiale').

    Solo per le fonti di `FONTI_CALENDARIO` e solo se l'host della fonte e'
    verificante: un calendario letto da un aggregatore non e' ufficiale. Con
    piu' date di chiusura nella riga, vale la piu' tarda.
    """
    try:
        fonte = int(str(fonte_id).strip())
    except (TypeError, ValueError):
        return None
    if not host_verificante or fonte not in FONTI_CALENDARIO or not isinstance(raw_data, dict):
        return None
    date: list[date_cls] = []
    for chiave, valore in raw_data.items():
        if re.sub(r"\s+", "", str(chiave)).upper() == _COLONNA_CHIUSURA:
            data = _data_di_colonna(valore)
            if data is not None:
                date.append(data)
            continue
        if not isinstance(valore, str):
            continue
        for frase in _FRASE_CHIUSURA_RE.finditer(valore):
            trovata = _data_completa_in(valore, frase.end())
            if trovata is None:
                continue
            data, fine = trovata
            if not e_presunta(valore[max(0, frase.start() - _FINESTRA_PAROLE):fine]):
                date.append(data)
    return (max(date), "calendario_ufficiale") if date else None


def termine_da_etichetta_oe(raw_data: Any) -> tuple[date_cls, str] | None:
    """La data del `deadline_label` di OE: (data, 'aggregatore'), o None.

    Riusa `segnali.scadenza_da_label` senza modificarlo (import tardivo:
    `segnali` importa gia' questo modulo).
    """
    if not isinstance(raw_data, dict):
        return None
    etichetta = raw_data.get("deadline_label")
    if not isinstance(etichetta, str) or e_presunta(etichetta):
        return None
    from .segnali import scadenza_da_label
    data = scadenza_da_label(etichetta)
    return (data, "aggregatore") if data is not None else None


def termine_per_precedenza(
    *candidati: tuple[date_cls, str] | None,
) -> tuple[date_cls, str] | None:
    """Il termine della fonte piu' affidabile fra i candidati (`FONTI_TERMINE`).

    calendario_ufficiale > pagina > testo > aggregatore; un candidato None o
    con una fonte sconosciuta non conta.
    """
    validi = [c for c in candidati if c is not None and c[1] in FONTI_TERMINE and c[0] is not None]
    if not validi:
        return None
    return min(validi, key=lambda c: FONTI_TERMINE.index(c[1]))


# --- scadenza provvisoria per il resolver precoce (giro 3, §7) ----------------

#: Le chiavi di una riga di calendario che portano il termine (contratto
#: `bandi-giro-3` §7): scad, chiusur, termine, deadline.
_CHIAVE_TERMINE_RE = re.compile(r"scad|chiusur|termine|deadline", re.IGNORECASE)
#: Le chiavi che somigliano a un termine e non lo sono: una data «indicativa»
#: o «presunta» per intestazione, i giorni che mancano (`deadline_days_left`
#: di OE), l'etichetta di OE (gia' letta con la sua regola).
_CHIAVE_NON_TERMINE_RE = re.compile(r"indicativ|presunt|previst|days_left|giorni", re.IGNORECASE)
_CHIAVI_GIA_LETTE: frozenset[str] = frozenset({"deadline_label", "close_date", "data_chiusura"})
#: Il valore di `raw_data.source` delle righe di Italia Domani.
_SOURCE_ITALIA_DOMANI = "italia_domani"
#: I ruoli che una data di Italia Domani puo' avere per valere come termine.
_RUOLI_TERMINE: frozenset[str] = frozenset({"scadenza", "ignoto"})


def _termine_italia_domani(valore: Any) -> date_cls | None:
    """La data di chiusura di Italia Domani («31/12/2026», «31 dicembre
    2026»), letta con `estrai_date_con_ruolo`: mai una data d'apertura, mai
    una presunta. Con piu' date nel campo vale la piu' tarda."""
    if not isinstance(valore, str) or e_presunta(valore):
        return None
    date_trovate = [d.data for d in estrai_date_con_ruolo(valore) if d.ruolo in _RUOLI_TERMINE]
    return max(date_trovate) if date_trovate else None


def scadenza_provvisoria(bando: Any) -> date_cls | None:
    """La scadenza che la riga dichiara prima del preprocess. Pura: niente
    modello, niente rete (contratto `bandi-giro-3` §7).

    Serve al resolver precoce, che gira sui bandi appena entrati: senza una
    scadenza il segnale «contenuto» della pagina ufficiale si accende di rado.
    Per questo vale solo come **conferma** (+15 se la pagina la riporta), mai
    come smentita: la decide `fonte_ufficiale.punteggia` con
    `Contesto.scadenza_provvisoria`.

    Nell'ordine, la prima che c'e':
      1. Obiettivo Europa: `deadline_label` (`termine_da_etichetta_oe`);
      2. Incentivi: `close_date` (ISO);
      3. Italia Domani: `data_chiusura` (`estrai_date_con_ruolo`);
      4. calendari: le chiavi con scad/chiusur/termine/deadline, solo date
         complete e non presunte; con piu' date vale la piu' tarda.
    None se nessuna c'e' o nessuna si legge («da definire», «feb-25»).
    """
    raw = bando.get("raw_data") if isinstance(bando, dict) else None
    if not isinstance(raw, dict):
        return None
    oe = termine_da_etichetta_oe(raw)
    if oe is not None:
        return oe[0]
    incentivi = _data_di_colonna(raw.get("close_date"))
    if incentivi is not None:
        return incentivi
    if raw.get("source") == _SOURCE_ITALIA_DOMANI or "data_chiusura" in raw:
        italia_domani = _termine_italia_domani(raw.get("data_chiusura"))
        if italia_domani is not None:
            return italia_domani
    date_calendario: list[date_cls] = []
    for chiave, valore in raw.items():
        nome = str(chiave)
        if (nome in _CHIAVI_GIA_LETTE or not _CHIAVE_TERMINE_RE.search(nome)
                or _CHIAVE_NON_TERMINE_RE.search(nome)):
            continue
        data = _data_di_colonna(valore)
        if data is not None:
            date_calendario.append(data)
    return max(date_calendario) if date_calendario else None
