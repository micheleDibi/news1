"""Lettori dello stato di un bando sulle pagine ufficiali (contratto `bandi-giro-2` §6.1 e §19.5).

`leggi(html, url_finale, titolo)` restituisce la `Lettura` di una pagina, o
None se la pagina non ha niente di leggibile. Due famiglie di lettori:

* **per ente**: uno per host, sul markup che quel sito usa per dire lo stato
  (un badge, un campo, una classe). Sono i soli che possono dire «aperto» e,
  quando l'etichetta e' affidabile, «chiuso» con `puo_chiudere`;
* **generico**: sugli host senza lettore dedicato, legge le frasi compiute di
  chiusura («Bando chiuso», «Domande chiuse», «dotazione esaurita») nell'h1,
  nei badge e nell'inizio del corpo. E' asimmetrico per costruzione: dice solo
  «chiuso», sempre come segnale, mai «aperto» e mai una chiusura.

Regole comuni:
- «sospeso» strutturato e' un «chiuso» SOLO SEGNALE: mai `puo_chiudere`;
- le date vincono: un termine finale certo e gia' passato fa «chiuso» con
  `puo_chiudere=False` (la strada e' la rettifica della data, non la chiusura);
- con piu' finestre conta solo il termine FINALE; finestre periodiche senza un
  termine finale danno «non_decisiva»;
- nessuna data presunta diventa un termine (G10).

Modulo puro: niente rete, niente DB. L'unica dipendenza esterna e' bs4 con
lxml, gia' usata da `scarico` e `impronte`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, time, timedelta
from typing import Any, Callable, Mapping, NamedTuple
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from .date_validation import (
    e_presunta,
    estrai_date_con_ruolo,
    estrai_finestra,
    ora_nella_citazione,
    termine_nella_pagina,
)

STATI_LETTURA: tuple[str, ...] = ("in_apertura", "aperto", "chiuso", "uscito", "non_decisiva")

#: Le chiavi dei lettori: le nove di §6.1, le tre del secondo lotto
#: (`docs/bandi-monitor/lettori-secondo-lotto.md`) e il generico. Sono anche i
#: suffissi dei codici di salute del percorso A.
ESTRATTORI: tuple[str, ...] = (
    "piemonte", "lazioeuropa", "lombardia", "calabria", "calabria_rc", "puglia",
    "formazionelavoro_er", "fesr_er", "pninclusione",
    "invitalia", "toscana", "fvg",
    "generico",
)


class DataLetta(NamedTuple):
    """Una data della pagina, con il suo ruolo e la frase che la cita."""
    ruolo: str
    data: date
    ora: time | None
    citazione: str
    presunta: bool


class TermineFinale(NamedTuple):
    data: date
    ora: time | None
    citazione: str


@dataclass(frozen=True)
class Lettura:
    """Quello che una pagina dice dello stato del bando."""
    estrattore: str
    stato: str
    #: Il testo grezzo dell'etichetta («Chiuso», «Bando Aperto», «[BANDO APERTO]»).
    etichetta: str
    puo_chiudere: bool = False
    solo_segnale: bool = False
    date: tuple[DataLetta, ...] = ()
    termine_finale: TermineFinale | None = None
    #: La pagina dichiara una finestra di presentazione.
    finestra: bool = False
    citazione_stato: str = ""
    #: Un'altra pagina dello stesso host che la pagina indica come il bando vero.
    link_collegato: str | None = None


# --- utilita' ---------------------------------------------------------------

_SPAZI_RE = re.compile(r"\s+")


def _testo(el: Any) -> str:
    if el is None:
        return ""
    if isinstance(el, str):
        return _SPAZI_RE.sub(" ", el).strip()
    return _SPAZI_RE.sub(" ", el.get_text(" ", strip=True)).strip()


def _host(url: str | None) -> str:
    try:
        host = (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _zuppa(html: str) -> BeautifulSoup:
    try:
        zuppa = BeautifulSoup(html or "", "lxml")
    except Exception:                                   # pragma: no cover - lxml assente
        zuppa = BeautifulSoup(html or "", "html.parser")
    for inutile in zuppa(["script", "style", "noscript", "template"]):
        inutile.decompose()
    return zuppa


#: I contenitori che non sono il bando: menu, testate, piedi, colonne laterali,
#: elenchi di altri bandi. Si confronta ogni classe (o id) PER INTERO: una
#: sottostringa toglierebbe `elementor-widget-container`, cioe' tutta la pagina.
_NON_CORPO_RE = re.compile(
    r"^(?!(?:no|has|with|without)-)(?:(?:[\w-]+-)?(?:sidebar|menu|breadcrumbs?|navbar|carousel|slider|cookies?|social|share)"
    r"(?:-[\w-]+)?|related[\w-]*|correlat[\w-]*|altri-[\w-]+|widget-area|site-(?:header|footer)"
    r"|footer|header|list-item|elenco-bandi|ultime-notizie)$",
    re.IGNORECASE,
)


def _ripulita(zuppa: BeautifulSoup) -> BeautifulSoup:
    """Una copia della pagina senza nav, testate, piedi, colonne laterali e menu."""
    copia = BeautifulSoup(str(zuppa), "lxml")
    for tag in copia(["nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    for tag in copia.find_all(True):
        # Il contenitore della pagina non si toglie mai, qualunque classe porti
        # (il body di LazioEuropa ha `no-sidebar`).
        if tag.decomposed or tag.name in ("html", "body", "main", "article"):
            continue
        segni = [*(tag.get("class") or []), str(tag.get("id") or ""), str(tag.get("role") or "")]
        if any(segno and _NON_CORPO_RE.match(segno) for segno in segni):
            tag.decompose()
    return copia


def _corpo(zuppa: BeautifulSoup) -> Tag | BeautifulSoup:
    """Il contenuto principale: `main` o `article` se c'e', senza nav/aside."""
    copia = _ripulita(zuppa)
    return copia.find("main") or copia.find("article") or copia.body or copia


def _oggi(oggi: date | None) -> date:
    if oggi is not None:
        return oggi
    from .stato_bando import oggi_roma
    return oggi_roma()


_MESI = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}
_MESE_RE = "(?:" + "|".join(_MESI) + ")"
_ORDINALI = {"primo": 1, "i": 1, "1": 1, "1°": 1, "secondo": 2, "ii": 2, "2": 2, "2°": 2,
             "terzo": 3, "iii": 3, "3": 3, "3°": 3, "quarto": 4, "iv": 4, "4": 4, "4°": 4}


def _fine_mese(anno: int, mese: int) -> date:
    if mese == 12:
        return date(anno, 12, 31)
    return date(anno, mese + 1, 1) - timedelta(days=1)


# --- periodi indicativi -----------------------------------------------------

_PERIODO_INCERTO_RE = re.compile(
    r"finestr|\d\s*\^|sessioni|edizioni|primavera|estate|autunno|inverno|da\s+definire|"
    r"\b\d{4}\s*[-/–]\s*\d{4}\b|annual",
    re.IGNORECASE,
)
_EMANAZIONE_RE = re.compile(r"^\s*emanazione\s+(?P<mese>" + _MESE_RE + r")\s+(?P<anno>\d{4})\b",
                            re.IGNORECASE)
_MESI_ANNO_RE = re.compile(
    r"^\s*(?:(?:met[aà]|fine|inizio)\s+)?(?:(?P<m1>" + _MESE_RE + r")(?:\s+(?P<a1>\d{4}))?"
    r"\s*[-/–]\s*)?(?:(?:met[aà]|fine|inizio)\s+)?(?P<m2>" + _MESE_RE + r")\s+(?P<a2>\d{4})\s*$",
    re.IGNORECASE,
)
_FRAZIONE_ANNO_RE = re.compile(
    r"^\s*(?P<n>primo|secondo|terzo|quarto|i{1,3}|iv|[1-4]°?)\s+(?P<tipo>trimestre|semestre)\s+(?P<anno>\d{4})\s*$",
    re.IGNORECASE,
)


def _periodo(testo: str | None) -> date | None:
    """L'ultimo giorno di un periodo indicativo («ottobre-novembre 2026»,
    «Emanazione Settembre 2026 …», «II semestre 2025»), o None se incerto."""
    if not isinstance(testo, str) or not testo.strip():
        return None
    t = _SPAZI_RE.sub(" ", testo).strip()
    emanazione = _EMANAZIONE_RE.match(t)
    if emanazione:
        return _fine_mese(int(emanazione["anno"]), _MESI[emanazione["mese"].lower()])
    if _PERIODO_INCERTO_RE.search(t):
        return None
    mesi = _MESI_ANNO_RE.match(t)
    if mesi:
        return _fine_mese(int(mesi["a2"]), _MESI[mesi["m2"].lower()])
    frazione = _FRAZIONE_ANNO_RE.match(t)
    if frazione:
        n = _ORDINALI.get(frazione["n"].lower())
        if n is None:
            return None
        mesi_per = 3 if frazione["tipo"].lower() == "trimestre" else 6
        ultimo = n * mesi_per
        if ultimo > 12:
            return None
        return _fine_mese(int(frazione["anno"]), ultimo)
    return None


#: Le colonne dei calendari con il periodo di apertura (VdA: PDF e CSV).
_COLONNE_PERIODO: tuple[str, ...] = ("col_6", "Unnamed: 6", "periodo", "data_apertura_prevista")


def periodo_indicativo(raw_data: Any) -> date | None:
    """La fine del periodo di apertura indicato da un calendario, o None.

    Accetta il `raw_data` di una riga (le colonne di `_COLONNE_PERIODO`) o
    direttamente il testo del periodo. Restituisce None se il formato e'
    incerto: finestre multiple, stagioni, intervalli di anni, «da definire».
    """
    if isinstance(raw_data, str):
        return _periodo(raw_data)
    if not isinstance(raw_data, Mapping):
        return None
    for chiave in _COLONNE_PERIODO:
        periodo = _periodo(raw_data.get(chiave))
        if periodo is not None:
            return periodo
    return None


def sorella_preavviso(url: str | None) -> str | None:
    """`…/preavvisi/x` → `…/avvisi/x` sullo stesso host (pninclusione), o None."""
    if not url:
        return None
    try:
        parti = urlsplit(url)
    except ValueError:
        return None
    if _host(url) != "pninclusione21-27.lavoro.gov.it" or not parti.path.startswith("/preavvisi/"):
        return None
    percorso = "/avvisi/" + parti.path[len("/preavvisi/"):]
    return urlunsplit((parti.scheme, parti.netloc, percorso, "", ""))


# --- contesto dei lettori ------------------------------------------------------

@dataclass(frozen=True)
class _Pagina:
    zuppa: BeautifulSoup
    url: str
    titolo: str
    oggi: date
    #: Il testo visibile dell'intera pagina, calcolato una volta.
    testo: str


_Lettore = Callable[[_Pagina], "Lettura | None"]


def _termine(data: date | None, citazione: str, ora: time | None = None) -> TermineFinale | None:
    if data is None or e_presunta(citazione):
        return None
    return TermineFinale(data, ora if ora is not None else ora_nella_citazione(citazione, data), citazione)


def _termine_delle_finestre(testo: str) -> tuple[TermineFinale | None, bool]:
    """Il termine FINALE fra le finestre di presentazione certe, e se ce n'e' almeno una."""
    finestre = [f for f in estrai_finestra(testo) if f.per_presentare and not f.presunta and f.fine]
    if not finestre:
        return None, False
    ultima = max(finestre, key=lambda f: (f.fine, f.ora_fine or time(0, 0)))
    return TermineFinale(ultima.fine, ultima.ora_fine, ultima.citazione), True


#: Finestre che si ripetono: senza un termine finale non dicono niente.
_PERIODICO_RE = re.compile(
    r"finestr[ae]\s+(?:annual|semestral|trimestral|mensil|periodic)|sessioni\s+annual|ogni\s+anno",
    re.IGNORECASE,
)


# --- lettori per ente ----------------------------------------------------------

def _piemonte(p: _Pagina) -> Lettura | None:
    """dl.stato-*: pre-informazione, aperto, scaduto, concluso, attuato."""
    campo = p.zuppa.select_one("dl[class*='stato-']")
    if campo is None:
        return None
    etichetta = _testo(campo.select_one("dd") or campo)
    valore = etichetta.lower().strip()
    citazione = _testo(campo)
    if valore == "pre-informazione":
        presunta = next((_testo(dl) for dl in p.zuppa.select("dl.field")
                         if "data presunta" in _testo(dl).lower()), "")
        periodo = _periodo(re.sub(r"(?i)^.*?data presunta di apertura del bando\s*", "", presunta))
        stato = "non_decisiva" if periodo is not None and periodo < p.oggi else "in_apertura"
        return Lettura("piemonte", stato, etichetta, citazione_stato=citazione)
    if valore == "aperto":
        return Lettura("piemonte", "aperto", etichetta, citazione_stato=citazione)
    if valore == "scaduto":
        return Lettura("piemonte", "chiuso", etichetta, puo_chiudere=True, citazione_stato=citazione)
    if valore == "concluso":
        # Mai vista su una pagina vera (01/10): solo segnale finche' non entra
        # una fixture vera (decisione del lead, revisione del #73).
        return Lettura("piemonte", "chiuso", etichetta, solo_segnale=True, citazione_stato=citazione)
    if valore == "esito":
        # «Esito»: graduatoria pubblicata, quindi domande chiuse. Vista su una
        # pagina vera (il bando collegato di 150489), ma il significato e'
        # dedotto: solo segnale (decisione del lead, #76).
        return Lettura("piemonte", "chiuso", etichetta, solo_segnale=True, citazione_stato=citazione)
    if valore == "attuato":
        return Lettura("piemonte", "uscito", etichetta, citazione_stato=citazione,
                       link_collegato=_link_sullo_stesso_host(p, ("/contributi-finanziamenti/",)))
    if "sospes" in valore:
        return Lettura("piemonte", "chiuso", etichetta, solo_segnale=True, citazione_stato=citazione)
    return None


def _link_sullo_stesso_host(p: _Pagina, percorsi: tuple[str, ...]) -> str | None:
    """Il primo link del corpo verso un bando sullo stesso host, o None."""
    host = _host(p.url)
    for a in _corpo(p.zuppa).select("a[href]"):
        assoluto = urljoin(p.url, str(a.get("href")))
        if (_host(assoluto) == host and assoluto.split("#")[0] != p.url.split("#")[0]
                and any(urlsplit(assoluto).path.startswith(x) for x in percorsi)):
            return assoluto
    return None


def _lazioeuropa(p: _Pagina) -> Lettura | None:
    """div.single-bandi-status: Prossima Apertura, Aperto, Chiuso; finestre «a partire … entro …»."""
    badge = p.zuppa.select_one(".single-bandi-status")
    if badge is None:
        return None
    etichetta = _testo(badge)
    valore = etichetta.lower()
    termine, finestra = _termine_delle_finestre(p.testo)
    if termine is None:
        # «Termini per la presentazione delle domande: Entro le ore 12:00 del
        # 24 luglio 2026» (106753): il termine sta da solo, senza finestra.
        corpo = _testo(_corpo(p.zuppa))
        trovato = termine_nella_pagina(corpo)
        if trovato is not None:
            termine = TermineFinale(trovato[0], ora_nella_citazione(corpo, trovato[0]), "")
    comune = {"etichetta": etichetta, "termine_finale": termine, "finestra": finestra,
              "citazione_stato": etichetta}
    if valore == "prossima apertura":
        return Lettura("lazioeuropa", "in_apertura", **comune)
    if valore == "aperto":
        return Lettura("lazioeuropa", "aperto", **comune)
    if valore == "chiuso":
        return Lettura("lazioeuropa", "chiuso", puo_chiudere=True, **comune)
    if "sospes" in valore:
        return Lettura("lazioeuropa", "chiuso", solo_segnale=True, **comune)
    return None


_SCADE_IL_RE = re.compile(r"Scade il\s*:?\s*(?P<data>\d{1,2}/\d{1,2}/\d{4})(?:\s*,?\s*ore\s+\d{1,2}[:.]\d{2})?",
                          re.IGNORECASE)


def _lombardia(p: _Pagina) -> Lettura | None:
    """span.chip-label: Aperto, Chiuso; «Scade il: gg/mm/aaaa, ore hh:mm»."""
    chip = p.zuppa.select_one("span.chip-label")
    if chip is None:
        return None
    etichetta = _testo(chip)
    valore = etichetta.lower()
    termine = None
    scade = _SCADE_IL_RE.search(p.testo)
    if scade:
        date_lette = [d for d in estrai_date_con_ruolo(scade.group(0))]
        if date_lette:
            termine = _termine(date_lette[0].data, scade.group(0))
    if valore == "aperto":
        return Lettura("lombardia", "aperto", etichetta, termine_finale=termine, citazione_stato=etichetta)
    if valore == "chiuso":
        return Lettura("lombardia", "chiuso", etichetta, puo_chiudere=True, termine_finale=termine,
                       citazione_stato=etichetta)
    if "sospes" in valore:
        return Lettura("lombardia", "chiuso", etichetta, solo_segnale=True, citazione_stato=etichetta)
    return None


def _calabria(p: _Pagina) -> Lettura | None:
    """Il bottone `cem-btn-*` in testa alla scheda di calabriaeuropa."""
    bottone = p.zuppa.select_one("[class*='cem-btn-']")
    if bottone is None:
        return None
    etichetta = _testo(bottone)
    valore = etichetta.lower()
    if valore == "aperto":
        return Lettura("calabria", "aperto", etichetta, citazione_stato=etichetta)
    if valore == "chiuso":
        return Lettura("calabria", "chiuso", etichetta, puo_chiudere=True, citazione_stato=etichetta)
    if valore in ("conclusione", "concluso"):
        # Mai vista su una pagina vera (01/10): solo segnale.
        return Lettura("calabria", "chiuso", etichetta, solo_segnale=True, citazione_stato=etichetta)
    if valore == "valutazione" or re.search(r"sospes|sospensione|interrott|revoc", valore):
        # La valutazione dice che le domande non si presentano piu', ma non
        # e' una chiusura dichiarata: solo segnale. Sospensione e revoca idem.
        return Lettura("calabria", "chiuso", etichetta, solo_segnale=True, citazione_stato=etichetta)
    if valore in ("pre-informazione", "preinformazione"):
        # VERITA_NOTA (1261858): la pre-informazione conferma l'«in apertura».
        return Lettura("calabria", "in_apertura", etichetta, citazione_stato=etichetta)
    if valore == "pubblicazione":
        return Lettura("calabria", "non_decisiva", etichetta, citazione_stato=etichetta)
    return None


def _calabria_rc(p: _Pagina) -> Lettura | None:
    """#rc-status del secondo template: «Pubblicata» non decide; il resto e' None."""
    stato = p.zuppa.select_one("#rc-status")
    if stato is None:
        return None
    # «STATO» e' l'intestazione del blocco; il valore sta nello span colorato.
    valore = stato.select_one("span.rounded, [class*='procedure_status']")
    etichetta = _testo(valore) if valore is not None else re.sub(r"(?i)^stato\s*", "", _testo(stato))
    if etichetta.lower() == "pubblicata":
        return Lettura("calabria_rc", "non_decisiva", etichetta, citazione_stato=etichetta)
    return None


def _puglia(p: _Pagina) -> Lettura | None:
    """Calendario del PR Puglia: «Stato: Prossimo avvio» con la data presunta di apertura."""
    stato, presunta = None, ""
    for blocco in p.zuppa.select(".field-render-block"):
        etichetta_campo = _testo(blocco.select_one(".detail-field-label"))
        if etichetta_campo.lower() == "stato":
            stato = _testo(blocco)[len(etichetta_campo):].strip()
        elif "data presunta" in _testo(blocco).lower():
            presunta = _testo(blocco)
    if not stato:
        return None
    valore = stato.lower()
    if valore.startswith("prossimo avvi"):
        periodo = _periodo(re.sub(r"(?i)^.*?data presunta di apertura\s*:?\s*", "", presunta))
        esito = "non_decisiva" if periodo is not None and periodo < p.oggi else "in_apertura"
        return Lettura("puglia", esito, stato, citazione_stato=f"{stato} {presunta}".strip())
    if "sospes" in valore:
        return Lettura("puglia", "chiuso", stato, solo_segnale=True, citazione_stato=stato)
    return None


#: Il blocco «Tempi e scadenze» dei siti della Regione Emilia-Romagna:
#: «25 settembre 2026 16:00 - Scadenza dei termini per partecipare al bando».
_SCADENZA_ER_RE = re.compile(
    r"(?P<data>\d{1,2}\s+" + _MESE_RE + r"\s+\d{4})\s+(?P<ora>\d{1,2}:\d{2})\s*-\s*Scadenza dei termini",
    re.IGNORECASE,
)


def _termine_er(testo: str) -> TermineFinale | None:
    """La scadenza del blocco strutturato «Tempi e scadenze», con l'ora."""
    trovate = []
    for m in _SCADENZA_ER_RE.finditer(testo):
        date_lette = estrai_date_con_ruolo(m["data"])
        if date_lette:
            ore, minuti = (int(x) for x in m["ora"].split(":"))
            if ore < 24 and minuti < 60:
                trovate.append(TermineFinale(date_lette[0].data, time(ore, minuti), m.group(0)))
    return max(trovate, key=lambda t: t.data, default=None)


_ENTRO_E_NON_OLTRE_RE = re.compile(r"entro e non oltre|termine ultimo", re.IGNORECASE)


def _formazionelavoro_er(p: _Pagina) -> Lettura | None:
    """div.bando_state: «Bando Aperto»; termine = la data piu' tarda con «entro e non oltre»."""
    stato = p.zuppa.select_one("div.bando_state")
    if stato is None:
        return None
    etichetta = _testo(stato)
    valore = etichetta.lower()
    corpo = p.testo
    termini = []
    for frase in re.split(r"(?<=[.;])\s+", corpo):
        if _ENTRO_E_NON_OLTRE_RE.search(frase):
            trovato = termine_nella_pagina(frase)
            if trovato is not None:
                termini.append(_termine(trovato[0], frase))
    termine = max((t for t in termini if t is not None), key=lambda t: t.data, default=None)
    termine = termine or _termine_er(corpo)
    if valore == "bando aperto":
        return Lettura("formazionelavoro_er", "aperto", etichetta, termine_finale=termine,
                       citazione_stato=etichetta)
    if valore == "bando chiuso":
        # Decisione del lead (30/09): solo segnale, perche' sullo stesso CMS
        # l'etichetta di fesr non e' affidabile.
        return Lettura("formazionelavoro_er", "chiuso", etichetta, solo_segnale=True,
                       termine_finale=termine, citazione_stato=etichetta)
    return None


def _fesr_er(p: _Pagina) -> Lettura | None:
    """Etichetta IGNORATA («In corso» anche a termini chiusi): solo le date."""
    corpo = p.testo
    termine = _termine_er(corpo)
    finestra_termine, finestra = _termine_delle_finestre(corpo)
    if finestra_termine is not None and (termine is None or finestra_termine.data > termine.data):
        termine = finestra_termine
    if termine is None:
        return None
    etichetta = _testo(p.zuppa.select_one("div.bando_state"))
    # Lo stato viene dalle date; «le date vincono» lo porta a chiuso se il
    # termine e' passato, altrimenti la pagina non decide niente da sola.
    return Lettura("fesr_er", "non_decisiva", etichetta, termine_finale=termine,
                   finestra=True, citazione_stato=termine.citazione)


_PRESUNTA_PNI_RE = re.compile(r"Data presunta apertura bando/avviso\s*:\s*(?P<periodo>[^:]{3,40}?)\s+(?:Fondo|Priorit|Obiettivo|$)",
                              re.IGNORECASE)


def _pninclusione(p: _Pagina) -> Lettura | None:
    """/preavvisi/: in apertura (non decisiva se la data presunta e' passata);
    /avvisi/: nessuna etichetta, solo l'eventuale termine."""
    percorso = urlsplit(p.url).path
    if percorso.startswith("/preavvisi/"):
        m = _PRESUNTA_PNI_RE.search(p.testo)
        periodo = _periodo(m["periodo"]) if m else None
        stato = "non_decisiva" if periodo is not None and periodo < p.oggi else "in_apertura"
        return Lettura("pninclusione", stato, "preavviso", citazione_stato=m.group(0) if m else "")
    if percorso.startswith("/avvisi/"):
        trovato = termine_nella_pagina(_testo(_corpo(p.zuppa)))
        if trovato is None:
            return None
        return Lettura("pninclusione", "non_decisiva", "avviso",
                       termine_finale=TermineFinale(trovato[0], None, ""), citazione_stato="avviso")
    return None


def _invitalia(p: _Pagina) -> Lettura | None:
    """«Stato incentivo o strumento» + p.active-panel: Attivo, Chiuso; «Data chiusura»."""
    riquadro = next((box for box in p.zuppa.select("div.pagetabctabox")
                     if "stato incentivo" in _testo(box.select_one("h2")).lower()), None)
    if riquadro is None:
        return None
    etichetta = _testo(riquadro.select_one("p.active-panel"))
    valore = etichetta.lower()
    termine = None
    for h3 in riquadro.select("h3"):
        if _testo(h3).lower() == "data chiusura":
            valore_data = _testo(h3.find_next_sibling("p"))
            date_lette = estrai_date_con_ruolo(valore_data)
            if date_lette:
                termine = _termine(date_lette[0].data, f"Data chiusura {valore_data}")
    if valore == "attivo":
        return Lettura("invitalia", "aperto", etichetta, termine_finale=termine, citazione_stato=etichetta)
    if valore == "chiuso":
        return Lettura("invitalia", "chiuso", etichetta, puo_chiudere=True, termine_finale=termine,
                       citazione_stato=etichetta)
    if "sospes" in valore:
        return Lettura("invitalia", "chiuso", etichetta, solo_segnale=True, citazione_stato=etichetta)
    return None


def _toscana(p: _Pagina) -> Lettura | None:
    """span.rtds-chip--status (is-open, is-in-progress, chiuso) e la scadenza con `<time>`."""
    chip = p.zuppa.select_one("span.rtds-chip--status")
    if chip is None:
        return None
    for nascosto in chip.select(".rtds-sr-only"):
        nascosto.decompose()
    etichetta = _testo(chip)
    valore = etichetta.lower()
    classi = " ".join(chip.get("class") or [])
    termine = None
    for paragrafo in p.zuppa.find_all("p"):
        testo = _testo(paragrafo)
        if testo.lower().startswith("data di scadenza presentazione domande"):
            tempo = paragrafo.find("time")
            valore_tempo = _testo(tempo)
            m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2}))?", valore_tempo)
            if m:
                try:
                    giorno = date(int(m[3]), int(m[2]), int(m[1]))
                    ora = time(int(m[4]), int(m[5])) if m[4] and int(m[4]) < 24 else None
                except ValueError:
                    continue
                if not e_presunta(testo):
                    termine = TermineFinale(giorno, ora, testo)
    if "is-open" in classi or valore == "aperto":
        return Lettura("toscana", "aperto", etichetta, termine_finale=termine, citazione_stato=etichetta)
    if "is-in-progress" in classi or valore == "in corso":
        return Lettura("toscana", "non_decisiva", etichetta, termine_finale=termine,
                       citazione_stato=etichetta)
    if "is-closed" in classi or valore in ("chiuso", "scaduto", "concluso"):
        # Mai vista su una pagina vera (01/10): solo segnale; il termine
        # passato, se c'e', chiude comunque per date.
        return Lettura("toscana", "chiuso", etichetta, solo_segnale=True, termine_finale=termine,
                       citazione_stato=etichetta)
    if "sospes" in valore:
        return Lettura("toscana", "chiuso", etichetta, solo_segnale=True, citazione_stato=etichetta)
    return None


_FVG_RE = re.compile(r"\[\s*BANDO\s+(?P<stato>APERTO|CHIUSO|SOSPESO|SCADUTO)\s*\]", re.IGNORECASE)


def _fvg(p: _Pagina) -> Lettura | None:
    """Il tag «[BANDO APERTO]» nel sottotitolo della pagina."""
    sottotitolo = p.zuppa.select_one("div.subtitle")
    m = _FVG_RE.search(_testo(sottotitolo)) if sottotitolo is not None else None
    if m is None:
        return None
    valore = m["stato"].lower()
    if valore == "aperto":
        return Lettura("fvg", "aperto", m.group(0), citazione_stato=m.group(0))
    # Decisione del lead (30/09): «chiuso» solo segnale finche' non c'e' una
    # pagina vera chiusa fra le fixture.
    return Lettura("fvg", "chiuso", m.group(0), solo_segnale=True, citazione_stato=m.group(0))


#: host (senza www.) → lettori da provare in ordine; il primo che risponde vince.
LETTORI_PER_HOST: dict[str, tuple[str, ...]] = {
    "bandi.regione.piemonte.it": ("piemonte",),
    "lazioeuropa.it": ("lazioeuropa",),
    "bandi.regione.lombardia.it": ("lombardia",),
    "calabriaeuropa.regione.calabria.it": ("calabria", "calabria_rc"),
    "regione.calabria.it": ("calabria_rc", "calabria"),
    "pr2127.regione.puglia.it": ("puglia",),
    "formazionelavoro.regione.emilia-romagna.it": ("formazionelavoro_er",),
    "fesr.regione.emilia-romagna.it": ("fesr_er",),
    "pninclusione21-27.lavoro.gov.it": ("pninclusione",),
    "invitalia.it": ("invitalia",),
    "regione.toscana.it": ("toscana",),
    "regione.fvg.it": ("fvg",),
}
_LETTORI: dict[str, _Lettore] = {
    "piemonte": _piemonte, "lazioeuropa": _lazioeuropa, "lombardia": _lombardia,
    "calabria": _calabria, "calabria_rc": _calabria_rc, "puglia": _puglia,
    "formazionelavoro_er": _formazionelavoro_er, "fesr_er": _fesr_er,
    "pninclusione": _pninclusione, "invitalia": _invitalia, "toscana": _toscana, "fvg": _fvg,
}


# --- generico ------------------------------------------------------------------

_SOGGETTO = r"\b(?:bando|avviso|sportello|domand[ae])\b"
_CHIUSURA = (r"\b(?:chius[oaie]|scadut[oaie]|sospes[oaie]|esaurit[aeio])\b"
             r"|\bnon\s+(?:è|e['’])\s+pi[uù]\s+possibile\s+presentare\b")
_FRASE_CHIUSURA_RE = re.compile(
    rf"(?:{_SOGGETTO}[^.!?]{{0,60}}?(?:{_CHIUSURA}))|(?:(?:{_CHIUSURA})[^.!?]{{0,60}}?{_SOGGETTO})",
    re.IGNORECASE,
)
#: Le formule potenziali di §5.4 e i futuri: non dicono che e' chiuso oggi.
_POTENZIALE_RE = re.compile(
    r"fino\s+a(?:d|ll['’])?\s*(?:l['’]\s*)?esauriment|ad\s+esauriment|in\s+caso\s+di\s+esauriment|"
    r"salvo\s+(?:esauriment|chiusur)|(?:potr|sar|verr|dovr)[aà]\s+(?:essere\s+)?(?:sospes|chius|esaurit)|"
    r"si\s+chiuder|chiusura\s+anticipata",
    re.IGNORECASE,
)
_CLASSI_ETICHETTA_RE = re.compile(r"badge|label|chip|stato|status|tag|pill|etichett", re.IGNORECASE)
_PRIMI_CARATTERI = 2000


def leggi_generico(html: str, url_finale: str = "", titolo: str = "", *, oggi: date | None = None) -> Lettura | None:
    """Le frasi compiute di chiusura nell'h1, nei badge e nell'inizio del corpo.

    Solo «chiuso», sempre `solo_segnale=True` e `puo_chiudere=False`: il
    generico puo' accendere un «da verificare», mai confermare un «aperto» e
    mai chiudere un bando. Menu, testate, colonne laterali ed elenchi di altri
    bandi non si leggono; le formule potenziali («fino ad esaurimento», «potra'
    essere sospeso») e le frasi con una data futura non contano.
    """
    zuppa = _zuppa(html)
    giorno = _oggi(oggi)
    pulita = _ripulita(zuppa)
    corpo = pulita.find("main") or pulita.find("article") or pulita.body or pulita
    zone = [_testo(h1) for h1 in pulita.select("h1")]
    zone += [_testo(el) for el in corpo.find_all(True)
             if _CLASSI_ETICHETTA_RE.search(" ".join(el.get("class") or [])) and len(_testo(el)) <= 80]
    zone.append(_testo(corpo)[:_PRIMI_CARATTERI])
    for zona in zone:
        for m in _FRASE_CHIUSURA_RE.finditer(zona):
            contesto = zona[max(0, m.start() - 60):m.end() + 60]
            if _POTENZIALE_RE.search(contesto):
                continue
            if any(d.data >= giorno for d in estrai_date_con_ruolo(contesto)):
                continue
            return Lettura("generico", "chiuso", m.group(0), puo_chiudere=False, solo_segnale=True,
                           citazione_stato=m.group(0))
    return None


# --- punto d'ingresso ---------------------------------------------------------------

def _le_date_vincono(lettura: Lettura, oggi: date) -> Lettura:
    """Un termine finale certo e passato fa «chiuso», senza `puo_chiudere`.

    Vale quando l'etichetta dice altro («Aperto», «In corso», un «chiuso» solo
    segnale): la strada e' la rettifica della data. Un «Chiuso» con
    `puo_chiudere` resta com'e': e' la chiusura di §5.6 (e), con la data letta
    come `p_data_evento`.

    Il termine entra anche fra le `date` della lettura (ruolo «scadenza»):
    e' su quelle che la doppia lettura strutturata (G7e) confronta le date.
    """
    termine = lettura.termine_finale
    if termine is None:
        return lettura
    if not lettura.date:
        lettura = replace(lettura, date=(DataLetta("scadenza", termine.data, termine.ora,
                                                   termine.citazione, False),))
    if termine.data < oggi and not (lettura.stato == "chiuso" and lettura.puo_chiudere):
        return replace(lettura, stato="chiuso", puo_chiudere=False, solo_segnale=False)
    if lettura.estrattore == "fesr_er":
        # Senza etichetta affidabile, un termine futuro dice solo che la
        # finestra e' ancora aperta: aperto, con il termine per la rettifica.
        return replace(lettura, stato="aperto")
    return lettura


def leggi(html: str, url_finale: str, titolo: str = "", *, oggi: date | None = None) -> Lettura | None:
    """La lettura della pagina, o None se non c'e' niente di leggibile.

    Sceglie i lettori dall'host di `url_finale`; senza lettore per l'host gira
    il generico. `titolo` e' il titolo del bando: la somiglianza con la pagina
    la giudica il passo (G3v), qui non serve. `oggi` (data civile di Roma) si
    passa nei test; senza, vale oggi.
    """
    giorno = _oggi(oggi)
    chiavi = LETTORI_PER_HOST.get(_host(url_finale))
    if not chiavi:
        return leggi_generico(html, url_finale, titolo, oggi=giorno)
    zuppa = _zuppa(html)
    pagina = _Pagina(zuppa, url_finale, titolo or "", giorno, _testo(zuppa.body or zuppa))
    for chiave in chiavi:
        lettura = _LETTORI[chiave](pagina)
        if lettura is None:
            continue
        # Finestre che si ripetono senza un termine finale: la pagina non decide.
        if (lettura.termine_finale is None and lettura.stato in ("aperto", "in_apertura")
                and _PERIODICO_RE.search(pagina.testo)):
            lettura = replace(lettura, stato="non_decisiva")
        return _le_date_vincono(lettura, giorno)
    return None


__all__ = [
    "DataLetta", "ESTRATTORI", "LETTORI_PER_HOST", "Lettura", "STATI_LETTURA", "TermineFinale",
    "leggi", "leggi_generico", "periodo_indicativo", "sorella_preavviso",
]
