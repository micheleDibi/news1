# -*- coding: utf-8 -*-
"""Normalizzazione, impronte e diff delle pagine ufficiali (piano §6.2, §5).

Perche' esiste
--------------
Il monitor deve capire, con zero crediti e zero LLM, se una pagina e' cambiata
davvero. `descrizione_raw` e' NULL su tutto il corpus: senza un «prima» salvato
non esiste nessun diff, e senza una normalizzazione seria il «prima» cambia da
solo (il contatore delle visite, l'«aggiornato il», l'orologio in intestazione,
i `utm_*` che il CMS appiccica ai link). Le impronte di questo modulo sono cio'
che finisce in `bando_controllo` (`impronta_contenuto`, `impronte_sezioni`,
`testo_norm` zlib): se cambiano per un contatore, ogni giro paga una
classificazione LLM per niente.

Il modulo e' **puro**: niente rete, niente DB, niente Firecrawl. Riceve HTML (o
testo) e restituisce stringhe, impronte e diff. L'unico import interno e'
`date_validation.estrai_date_con_ruolo`, cioe' l'unico parser di date del
progetto: riconoscere le date con una regex propria qui significherebbe averne
due che divergono.

Cosa garantisce
---------------
1. `pulisci` toglie `script,style,nav,header,footer,aside,form,iframe,noscript`
   e i nodi il cui id/class/role parla di cookie, banner, condivisione, social,
   briciole, menu, sidebar, widget, correlati (`related` e `correlat`) o
   newsletter: e' la stessa ripulitura che `allegati.estrai` applica prima di
   guardare gli href, cosi' i PDF dei «bandi correlati» non diventano allegati
   del bando, nemmeno quando il loro riquadro sta dentro `<main>` (§5);
2. `ripulisci_testo` toglie contatori, «aggiornato il …» e gli orari che stanno
   fuori da una frase con una data o con una parola di ruolo (un «entro le ore
   12:00» non si tocca mai: e' la scadenza);
3. `diff_sezioni` produce un diff unificato limitato a 6 000 caratteri sulle
   sole sezioni cambiate, e dice se e' **rumore** (niente LLM) o no.
"""
from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass
from datetime import date as date_cls
from typing import Iterable, Mapping, Sequence

from .date_validation import estrai_date_con_ruolo
from .stato_bando import oggi_roma

# --- costanti di §6.2 -------------------------------------------------------

TAG_RIMOSSI: tuple[str, ...] = (
    "script", "style", "nav", "header", "footer", "aside", "form", "iframe", "noscript",
)

# Confronto su id, class, role e data-* del nodo: i CMS italiani marcano cosi'
# le parti di contorno. Volutamente senza `\b`: «main-menu» e «js-cookie-bar»
# devono cadere entrambi.
#
# `correlat` sta accanto a `related` perche' i «bandi correlati» in italiano si
# chiamano `bandi-correlati` / `box-correlati` (§5 elenca i due termini
# insieme): senza, i PDF di un altro bando dentro `<main>` diventano allegati di
# questo, e ogni pubblicazione altrui muove `impronta_contenuto` e paga una
# classificazione LLM per niente. `collegat` **non** e' qui di proposito: nei
# CMS italiani «documenti collegati» e' proprio la cassetta degli allegati del
# bando, e toglierla vorrebbe dire perdere gli atti.
NODI_RUMORE = re.compile(
    r"cookie|banner|share|social|breadcrumb|menu|sidebar|widget|related|correlat|"
    r"newsletter",
    re.IGNORECASE,
)

LIMITE_DIFF = 6000          # caratteri del diff passati al classificatore
SOGLIA_RUMORE = 80          # sotto questa dimensione il diff non vale un LLM
BUDGET_PREDEFINITO = 12000  # caratteri del testo ufficiale nel prompt SEO (§5)

# Parole che, se compaiono nelle righe cambiate, escludono il «rumore»: sono
# quelle di §6.2 con cui il monitor decide di chiamare il classificatore.
PAROLE_RILEVANTI = re.compile(
    r"prorog|differ|posticip|rettific|sospe|revoc|annull|ritir|graduator|esit|faq|"
    r"riapert|esaurim|nuov[oa]\s+(?:finestra|scadenz\w*|termin[ei])",
    re.IGNORECASE,
)

# I due ruoli che muovono lo stato di un bando: una data passata con uno di
# questi ruoli non e' mai rumore (una rettifica retroattiva del termine e' un
# fatto, il timestamp di rigenerazione di un elenco no). Il ruolo lo decide
# `estrai_date_con_ruolo`, non una ricerca di parole: «rivista il 22/09 **dal**
# responsabile» contiene «dal» ma la sua data e' di ruolo ignoto.
RUOLI_CHE_CONTANO: frozenset[str] = frozenset({"apertura", "scadenza"})

# Parole di ruolo: un orario dentro una di queste frasi non e' l'orologio del
# sito, e' un termine. Non si tocca nemmeno se nella riga non c'e' una data.
PAROLE_RUOLO = re.compile(
    r"\bscadenz\w*|\bentro\b|\btermin[ei]\b|\bfino al\b|\bchius\w*|\bapertur\w*|"
    r"\ba partire\b|\bdecorr\w*|\bdal(?:le)?\b|\ball[ae]\s+ore\b",
    re.IGNORECASE,
)

# Punteggio di `seleziona_sezioni`: quanto vale una sezione per il prompt SEO.
PESI_PAROLE: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"scadenz\w*|termin[ei]|entro\b|fino al\b", re.I), 6),
    (re.compile(r"present\w*\s+(?:della\s+)?domand\w*|come\s+partecipare|modalit\w*", re.I), 5),
    (re.compile(r"beneficiar\w*|destinatar\w*|chi\s+pu[oò]", re.I), 4),
    (re.compile(r"requisit\w*|ammissibil\w*", re.I), 4),
    (re.compile(r"contribut\w*|agevolazion\w*|importi?\b|dotazion\w*|risorse", re.I), 4),
    (re.compile(r"apertur\w*|sportello|finestr\w*", re.I), 3),
    (re.compile(r"allegat\w*|modulistic\w*|document\w*", re.I), 2),
    (re.compile(r"prorog\w*|rettific\w*|differ\w*", re.I), 5),
)

_RE_SPAZI = re.compile(r"[ \t   ]+")
_RE_RIGHE_VUOTE = re.compile(r"\n{2,}")
_RE_TAG = re.compile(r"<\s*[a-zA-Z!/]")

# Contatori: «Visualizzazioni: 1.234», «1234 visite», «Download 12».
_RE_CONTATORI = (
    re.compile(
        r"\b(?:visualizzazion\w*|visite|letture|views|download|condivision\w*|commenti)\b"
        r"\s*[:\-–]?\s*\d[\d.,]*",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b\d[\d.,]*\s*(?:visualizzazion\w*|visite|letture|views|download|condivision\w*)\b",
        re.IGNORECASE,
    ),
)

# «Aggiornato il 12/09/2026 10:33», «Ultima modifica: 12 settembre 2026».
_RE_AGGIORNAMENTO = re.compile(
    r"\b(?:ultim[oa]\s+(?:aggiornamento|modifica|revisione)|aggiornat[oa]|"
    r"pubblicat[oa]\s+il|data\s+ultimo\s+aggiornamento)\b\s*[:\-–]?\s*"
    r"(?:il\s+)?[\w°]{0,12}[\s/.\-]*\d{1,4}[\w\s/.:\-°]{0,28}",
    re.IGNORECASE,
)

# Orologi: 12:00, 12.00, 12:00:30.
_RE_ORARIO = re.compile(r"\b\d{1,2}[:.]\d{2}(?::\d{2})?\b")

# Segnaposto dell'orario tolto, con i separatori che lo circondano: «sportello
# 09:00 - 13:00» deve diventare «sportello», non «sportello -».
_SEGNAPOSTO = "\x00"
_RE_SEGNAPOSTO = re.compile(
    r"\s*[-–—]?\s*" + _SEGNAPOSTO + r"(?:\s*[-–—]?\s*" + _SEGNAPOSTO + r")*\s*[-–—]?\s*"
)

# Token di tracciamento dentro gli URL che compaiono nel testo.
_RE_UTM_TESTO = re.compile(
    r"[?&](?:utm_[a-z0-9_]*|fbclid|gclid|msclkid|_ga)=[^\s&#]*", re.IGNORECASE
)


# --- normalizzazione degli URL ---------------------------------------------

_RE_SCHEMA = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://")
_RE_PORTA_DEFAULT = re.compile(r":(?:80|443)$")
_RE_WWW = re.compile(r"^www\.")
_RE_TRACCIAMENTO = re.compile(
    r"&(?:utm_[^&=]*|fbclid|gclid|msclkid|_ga)=[^&]*", re.IGNORECASE
)


def normalizza_url(url: str | None) -> str | None:
    """Forma canonica di un URL, gemella di `bando_normalizza_url` (migr. 02).

    Toglie frammento, userinfo, porta di default, `www.`, slash finale e i
    parametri di tracciamento. **Non** unifica lo schema: `http` e `https`
    restano URL diversi, perche' l'uguaglianza di questa stringa e' uno dei
    criteri di fusione di `gemelli.py` e una fusione sbagliata costa piu' di un
    doppione.
    """
    if not url:
        return None
    resto = url.strip()
    if not resto:
        return None
    resto = resto.split("#", 1)[0]
    trovato = _RE_SCHEMA.match(resto)
    schema = trovato.group(1).lower() if trovato else ""
    if trovato:
        resto = resto[trovato.end():]

    autorita = resto.split("/", 1)[0].split("?", 1)[0]
    resto = resto[len(autorita):] if len(autorita) < len(resto) else ""

    autorita = re.sub(r"^[^@]*@", "", autorita).lower()
    autorita = _RE_PORTA_DEFAULT.sub("", autorita)
    autorita = _RE_WWW.sub("", autorita)

    percorso = resto.split("?", 1)[0]
    parametri = resto.split("?", 1)[1] if "?" in resto else ""

    parametri = _RE_TRACCIAMENTO.sub("", "&" + parametri)
    parametri = parametri.strip("&").strip()

    percorso = re.sub(r"/+$", "", percorso)

    composto = (f"{schema}://" if schema else "") + autorita + percorso
    if parametri:
        composto += "?" + parametri
    return composto or None


# --- pulizia dell'HTML ------------------------------------------------------

def _zuppa(html: str):
    """BeautifulSoup con lxml; `html.parser` solo se lxml manca."""
    from bs4 import BeautifulSoup
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:                                   # pragma: no cover - ripiego
        return BeautifulSoup(html, "html.parser")


def _e_html(testo: str) -> bool:
    return bool(testo) and bool(_RE_TAG.search(testo))


def _attributi_rumore(nodo) -> bool:
    valori: list[str] = []
    for chiave, valore in (getattr(nodo, "attrs", None) or {}).items():
        if chiave not in ("id", "class", "role", "data-testid", "aria-label"):
            continue
        if isinstance(valore, (list, tuple)):
            valori.extend(str(v) for v in valore)
        else:
            valori.append(str(valore))
    return any(NODI_RUMORE.search(v) for v in valori)


def pulisci(html: str):
    """Zuppa ripulita: via i tag di contorno e i nodi di contorno (§6.2).

    Restituisce l'oggetto BeautifulSoup, non una stringa, perche' `allegati.py`
    deve poter cercare gli href **dentro** la stessa ripulitura: due pulizie
    diverse sui due lati rimetterebbero in gioco i link della sidebar.
    """
    from bs4 import Comment
    zuppa = _zuppa(html or "")
    for nodo in zuppa.find_all(TAG_RIMOSSI):
        nodo.decompose()
    for commento in zuppa.find_all(string=lambda t: isinstance(t, Comment)):
        commento.extract()
    for nodo in list(zuppa.find_all(True)):
        if nodo.decomposed or nodo.name in ("html", "body"):
            continue
        if _attributi_rumore(nodo):
            nodo.decompose()
    return zuppa


def ripulisci_testo(testo: str | None, *, oggi: date_cls | None = None) -> str:
    """Testo stabile fra un controllo e l'altro (§6.2).

    Toglie, in quest'ordine: token di tracciamento negli URL, contatori,
    «aggiornato il …» (con la sua data: cambia ogni giorno) e infine gli orari
    delle sole righe che non contengono ne' una data ne' una parola di ruolo.
    L'ordine conta: se si togliessero prima gli orari, «aggiornato il 12/09
    10:33» resterebbe meta' dentro.
    """
    if not testo:
        return ""
    del oggi  # la data del giorno serve al diff, non qui: si toglie la frase intera
    ripulito = _RE_UTM_TESTO.sub("", testo)
    ripulito = _RE_AGGIORNAMENTO.sub(" ", ripulito)
    for regola in _RE_CONTATORI:
        ripulito = regola.sub(" ", ripulito)

    righe: list[str] = []
    for riga in ripulito.splitlines():
        riga = _RE_SPAZI.sub(" ", riga).strip()
        if not riga:
            continue
        if not estrai_date_con_ruolo(riga) and not PAROLE_RUOLO.search(riga):
            riga = _RE_SEGNAPOSTO.sub(" ", _RE_ORARIO.sub(_SEGNAPOSTO, riga))
            riga = _RE_SPAZI.sub(" ", riga).strip()
        if riga:
            righe.append(riga)
    return "\n".join(righe)


def testo_normalizzato(html_o_testo: str | None) -> str:
    """Testo visibile e stabile di una pagina (o di un testo gia' estratto)."""
    if not html_o_testo:
        return ""
    if _e_html(html_o_testo):
        return ripulisci_testo(pulisci(html_o_testo).get_text("\n"))
    return ripulisci_testo(html_o_testo)


# --- sezioni ----------------------------------------------------------------

TITOLI = ("h1", "h2", "h3", "h4")


@dataclass(frozen=True)
class Sezione:
    """Un blocco della pagina: il titolo h1-h4 e tutto cio' che lo segue fino al
    titolo successivo. `indice` 0 e' il preambolo (titolo della pagina e lead)."""
    indice: int
    titolo: str
    livello: int
    testo: str
    link: tuple[str, ...] = ()

    @property
    def chiave(self) -> str:
        return _RE_SPAZI.sub(" ", self.titolo).strip().casefold()

    @property
    def righe(self) -> tuple[str, ...]:
        return tuple(r for r in self.testo.splitlines() if r.strip())


def _eventi(nodo):
    """Titoli, testo e link in ordine di documento, ogni nodo una volta sola."""
    from bs4 import NavigableString
    for figlio in getattr(nodo, "children", ()):
        if isinstance(figlio, NavigableString):
            testo = str(figlio)
            if testo.strip():
                yield ("testo", testo)
            continue
        nome = getattr(figlio, "name", None)
        if nome in TITOLI:
            yield ("titolo", figlio.get_text(" ", strip=True), int(nome[1]))
            continue
        if nome == "a":
            href = (figlio.get("href") or "").strip()
            if href:
                yield ("link", href)
        if nome in ("br", "p", "li", "tr", "div", "section", "article", "table"):
            yield ("testo", "\n")
        yield from _eventi(figlio)


def sezioni(html_o_testo: str | None) -> tuple[Sezione, ...]:
    """Le sezioni della pagina. Con un testo gia' estratto (niente tag) usa i
    paragrafi: una riga corta e senza punto finale vale da titolo."""
    if not html_o_testo:
        return ()
    if not _e_html(html_o_testo):
        return _sezioni_da_testo(html_o_testo)

    zuppa = pulisci(html_o_testo)
    radice = zuppa.body or zuppa
    corrente_titolo, corrente_livello = "", 0
    pezzi: list[str] = []
    link: list[str] = []
    raccolte: list[Sezione] = []

    def chiudi() -> None:
        testo = ripulisci_testo("".join(pezzi))
        if testo or corrente_titolo or link:
            raccolte.append(Sezione(
                indice=len(raccolte),
                titolo=corrente_titolo,
                livello=corrente_livello,
                testo=testo,
                link=tuple(dict.fromkeys(link)),
            ))

    for evento in _eventi(radice):
        if evento[0] == "titolo":
            chiudi()
            corrente_titolo, corrente_livello = evento[1], evento[2]
            pezzi, link = [], []
        elif evento[0] == "link":
            link.append(evento[1])
        else:
            pezzi.append(evento[1])
    chiudi()
    return tuple(raccolte)


def _sezioni_da_testo(testo: str) -> tuple[Sezione, ...]:
    """Sezioni da un testo senza tag: blocchi separati da righe vuote."""
    # I blocchi si tagliano sul testo GREZZO: `ripulisci_testo` toglie le righe
    # vuote, che qui sono l'unico confine fra un paragrafo e il successivo.
    blocchi = [b for b in _RE_RIGHE_VUOTE.split(testo) if b.strip()]
    if len(blocchi) <= 1:
        pulito = ripulisci_testo(testo)
        blocchi = [b for b in pulito.split("\n") if b.strip()] or [pulito]
    raccolte: list[Sezione] = []
    for blocco in blocchi:
        righe = [r for r in ripulisci_testo(blocco).splitlines() if r.strip()]
        if not righe:
            continue
        prima = righe[0].strip()
        e_titolo = len(righe) > 1 and len(prima) <= 90 and not prima.endswith((".", ";", ","))
        raccolte.append(Sezione(
            indice=len(raccolte),
            titolo=prima if e_titolo else "",
            livello=2 if e_titolo else 0,
            testo="\n".join(righe[1:] if e_titolo else righe),
        ))
    return tuple(raccolte)


# --- impronte ---------------------------------------------------------------

def impronta(testo: str | None) -> str:
    """sha256 esadecimale del testo normalizzato (stringa vuota compresa)."""
    return hashlib.sha256((testo or "").encode("utf-8")).hexdigest()


def impronta_sezione(sezione: Sezione) -> str:
    """Impronta di una sezione: livello, titolo e testo. I link non entrano,
    cosi' un `utm_` aggiunto a un href non fa «cambiare» la prosa."""
    return impronta(f"{sezione.livello}|{sezione.chiave}\n{sezione.testo}")


def impronta_link(link: Iterable[str]) -> str:
    """Impronta dell'insieme dei link di una pagina: URL normalizzati, unici e
    ordinati. L'ordine del markup non conta, l'insieme si'."""
    normalizzati = sorted({u for u in (normalizza_url(l) for l in link) if u})
    return impronta("\n".join(normalizzati))


def impronte_sezioni(html_o_testo: str | None) -> dict[str, str]:
    """`{chiave della sezione: impronta}`. Le sezioni con lo stesso titolo (o
    senza titolo) ricevono un suffisso posizionale, altrimenti sparirebbero."""
    esito: dict[str, str] = {}
    for sezione in sezioni(html_o_testo):
        chiave = sezione.chiave or f"#{sezione.indice}"
        if chiave in esito:
            chiave = f"{chiave}#{sezione.indice}"
        esito[chiave] = impronta_sezione(sezione)
    return esito


def impronta_contenuto(html_o_testo: str | None) -> str:
    """Impronta dell'intera pagina: testo normalizzato piu' insieme dei link.

    E' il valore di `bando_controllo.impronta_contenuto`: se non cambia, il
    controllo finisce qui (niente diff, niente LLM, §6.2).
    """
    if not html_o_testo:
        return impronta("")
    if _e_html(html_o_testo):
        zuppa = pulisci(html_o_testo)
        testo = ripulisci_testo(zuppa.get_text("\n"))
        link = [(a.get("href") or "").strip() for a in zuppa.find_all("a")]
    else:
        testo, link = ripulisci_testo(html_o_testo), []
    return impronta(testo + "\n--link--\n" + impronta_link(link))


# --- diff -------------------------------------------------------------------

@dataclass(frozen=True)
class Diff:
    """Esito del confronto fra due versioni della stessa pagina."""
    testo: str = ""
    troncato: bool = False
    rumore: bool = True
    rilevante: bool = False
    sezioni_cambiate: tuple[str, ...] = ()
    righe_aggiunte: tuple[str, ...] = ()
    righe_rimosse: tuple[str, ...] = ()
    link_aggiunti: tuple[str, ...] = ()
    link_rimossi: tuple[str, ...] = ()

    @property
    def vuoto(self) -> bool:
        return not (self.righe_aggiunte or self.righe_rimosse
                    or self.link_aggiunti or self.link_rimossi)


def _mappa_sezioni(pagina: str | None) -> dict[str, Sezione]:
    mappa: dict[str, Sezione] = {}
    for sezione in sezioni(pagina):
        chiave = sezione.chiave or f"#{sezione.indice}"
        if chiave in mappa:
            chiave = f"{chiave}#{sezione.indice}"
        mappa[chiave] = sezione
    return mappa


def _link_normalizzati(pagina: str | None) -> set[str]:
    insieme: set[str] = set()
    for sezione in sezioni(pagina):
        for href in sezione.link:
            normalizzato = normalizza_url(href)
            if normalizzato:
                insieme.add(normalizzato)
    return insieme


def diff_sezioni(
    prima: str | None,
    dopo: str | None,
    *,
    limite: int = LIMITE_DIFF,
    oggi: date_cls | None = None,
) -> Diff:
    """Diff unificato delle sole sezioni cambiate, al massimo `limite` caratteri.

    `rumore=True` significa «non vale un LLM»: nessun link aggiunto o rimosso,
    nessuna parola di §6.2 fra le righe cambiate, nessuna data diversa da quella
    di oggi, e differenze fatte solo di cifre, spazi, punteggiatura o riordini
    di elenco (oppure meno di 80 caratteri in tutto).

    Le righe aggiunte e rimosse si calcolano sul diff **intero**: il gate G2 del
    monitor le confronta con la citazione, e troncarle nasconderebbe proprio la
    riga che prova l'evento.
    """
    giorno = oggi or oggi_roma()
    a = _mappa_sezioni(prima)
    b = _mappa_sezioni(dopo)

    chiavi: list[str] = [k for k in b if k not in a or a[k].testo != b[k].testo]
    chiavi += [k for k in a if k not in b]

    blocchi: list[str] = []
    aggiunte: list[str] = []
    rimosse: list[str] = []
    cambiate: list[str] = []
    for chiave in chiavi:
        vecchia = a.get(chiave)
        nuova = b.get(chiave)
        righe = list(difflib.unified_diff(
            list(vecchia.righe) if vecchia else [],
            list(nuova.righe) if nuova else [],
            fromfile=f"prima:{chiave}", tofile=f"dopo:{chiave}", lineterm="", n=2,
        ))
        if not righe:
            continue
        cambiate.append(chiave)
        blocchi.extend(righe)
        for riga in righe:
            if riga.startswith("+++") or riga.startswith("---"):
                continue
            if riga.startswith("+"):
                aggiunte.append(riga[1:].strip())
            elif riga.startswith("-"):
                rimosse.append(riga[1:].strip())

    link_prima = _link_normalizzati(prima)
    link_dopo = _link_normalizzati(dopo)
    link_aggiunti = tuple(sorted(link_dopo - link_prima))
    link_rimossi = tuple(sorted(link_prima - link_dopo))

    testo = "\n".join(blocchi)
    troncato = len(testo) > limite
    if troncato:
        testo = testo[:limite]

    rilevante = bool(link_aggiunti or link_rimossi) or any(
        PAROLE_RILEVANTI.search(r) for r in aggiunte + rimosse
    )
    return Diff(
        testo=testo,
        troncato=troncato,
        rumore=_e_rumore(aggiunte, rimosse, link_aggiunti, link_rimossi, giorno),
        rilevante=rilevante,
        sezioni_cambiate=tuple(cambiate),
        righe_aggiunte=tuple(aggiunte),
        righe_rimosse=tuple(rimosse),
        link_aggiunti=link_aggiunti,
        link_rimossi=link_rimossi,
    )


def _scheletro(riga: str) -> str:
    """Solo lettere: e' cio' che resta quando si toglie ogni cifra, spazio e
    segno. Due righe con lo stesso scheletro differiscono solo per numeri."""
    return re.sub(r"[^a-zA-Zàèéìòùáíóúü]+", "", riga).casefold()


def _e_rumore(
    aggiunte: Sequence[str],
    rimosse: Sequence[str],
    link_aggiunti: Sequence[str],
    link_rimossi: Sequence[str],
    giorno: date_cls,
) -> bool:
    if link_aggiunti or link_rimossi:
        return False
    if not aggiunte and not rimosse:
        return True
    if any(PAROLE_RILEVANTI.search(r) for r in list(aggiunte) + list(rimosse)):
        return False

    # Le date. Una data **futura** o una data dentro una frase di ruolo («entro
    # il», «scadenza», «a partire dal») non e' mai rumore: e' esattamente il
    # cambiamento che il monitor esiste per vedere. Restano rumore le date
    # amministrative del passato — «pagina rivista il …», il timestamp di
    # rigenerazione dell'elenco — che cambiano da sole tutti i giorni.
    for riga in list(aggiunte) + list(rimosse):
        for trovata in estrai_date_con_ruolo(riga):
            if trovata.data > giorno:
                return False
            if trovata.ruolo in RUOLI_CHE_CONTANO:
                return False

    if sorted(aggiunte) == sorted(rimosse):     # elenco riordinato
        return True
    corpo = "".join(aggiunte) + "".join(rimosse)
    if len(corpo.strip()) < SOGLIA_RUMORE:
        return True
    return sorted(_scheletro(r) for r in aggiunte) == sorted(_scheletro(r) for r in rimosse)


# --- selezione per il prompt SEO -------------------------------------------

def _punteggio(sezione: Sezione) -> int:
    corpo = f"{sezione.titolo}\n{sezione.testo}"
    punti = sum(peso for regola, peso in PESI_PAROLE if regola.search(corpo))
    if estrai_date_con_ruolo(corpo):
        punti += 8
    return punti


def _riga_allegato(allegato: Mapping[str, object]) -> str:
    etichetta = str(allegato.get("label") or allegato.get("etichetta") or "").strip()
    url = str(allegato.get("url") or "").strip()
    tipo = str(allegato.get("tipo") or "").strip()
    pezzi = [p for p in (etichetta, f"[{tipo}]" if tipo else "", url) if p]
    return "- " + " ".join(pezzi)


def seleziona_sezioni(
    testo: str | None,
    budget: int = BUDGET_PREDEFINITO,
    *,
    allegati: Iterable[Mapping[str, object]] = (),
) -> str:
    """Il testo ufficiale ridotto a `budget` caratteri per il prompt SEO (§5).

    Regole, nell'ordine: titolo e lead ci sono sempre; poi le sezioni con date e
    quelle con le parole che contano, dalla piu' utile alla meno utile; in coda
    l'elenco deterministico degli allegati, che si prenota il suo spazio prima
    che le sezioni riempiano il budget (altrimenti non entrerebbe mai).
    L'ordine finale e' quello del documento: al modello serve un testo leggibile,
    non una classifica.
    """
    if not testo:
        return ""
    budget = max(int(budget), 0)
    coda = ""
    elenco = [_riga_allegato(a) for a in allegati]
    if elenco:
        coda = "\nAllegati:\n" + "\n".join(elenco)
    disponibile = max(budget - len(coda), 0)

    blocchi = sezioni(testo)
    if not blocchi:
        return (ripulisci_testo(testo)[:disponibile] + coda).strip()

    resi: dict[int, str] = {}
    usati = 0
    for sezione in blocchi[:1]:                       # titolo + lead: sempre
        reso = _rendi(sezione)
        resi[sezione.indice] = reso[:disponibile]
        usati += len(resi[sezione.indice])

    ordinate = sorted(blocchi[1:], key=lambda s: (-_punteggio(s), s.indice))
    for sezione in ordinate:
        reso = _rendi(sezione)
        if not reso.strip():
            continue
        # La giunzione e' `\n\n`: due caratteri, non uno. Addebitarne uno solo
        # sfora il budget di tante unita' quante sono le sezioni scelte, e con
        # molte sezioni corte diventa visibile.
        if usati + len(reso) + 2 > disponibile:
            continue
        resi[sezione.indice] = reso
        usati += len(reso) + 2

    corpo = "\n\n".join(resi[i] for i in sorted(resi) if resi[i].strip())
    # Il taglio finale e' la rete di sicurezza: il budget e' una promessa sul
    # prompt, e nessuna aritmetica di giunzioni deve poterla smentire.
    return (corpo + coda)[:budget].strip()


def _rendi(sezione: Sezione) -> str:
    if sezione.titolo and sezione.testo:
        return f"{sezione.titolo}\n{sezione.testo}"
    return sezione.titolo or sezione.testo
