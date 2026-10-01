# -*- coding: utf-8 -*-
"""Classificazione degli eventi e gate G1-G9 (piano §6.2, §4, §13.5).

Perche' esiste
--------------
Il monitor scarica una pagina, vede che e' cambiata e deve decidere **che cosa
e' successo**. La lettura la fa un modello (Haiku 4.5 con il tool
`salva_eventi`); la **decisione** no. Un modello che legge «la domanda va
presentata entro il 1 dicembre 2026» puo' sbagliare bando, sbagliare ruolo
della data, o citare una frase che nella pagina non c'e'. Se quella lettura
finisse in colonna, il sito pubblicherebbe una scadenza inventata e BandoFit
manderebbe un alert su di essa.

Per questo la parte che conta e' qui, in Python, deterministica: **nove gate
obbligatori**. Il modello propone; i gate dispongono. Un evento che non passa
resta interno, con il motivo scritto nel report d'ombra, e non tocca nessuna
colonna.

I nove gate (§6.2)
------------------
* **G1** la citazione e' sottostringa (`norm_cit`) del testo di una pagina
  scaricata **in questo controllo**;
* **G2** la citazione interseca le righe *aggiunte* del diff (>= 60 % dei
  token); per `graduatoria`/`esito`/`faq`/`nuovo_allegato` basta un link nuovo;
* **G2'** («G2 primo»: primo controllo, o mismatch senza diff) la coppia
  (data, ruolo) della citazione e' **assente** dalle colonne e, se esiste un
  `testo_prima`, anche dalle sue date. In G2' il G7 e' sempre obbligatorio e
  pretende **due** prove: la seconda opinione del modello grande **e** una
  prova indipendente;
* **G3** la data dichiarata compare nella citazione con un ruolo compatibile;
  le date normative («ai sensi del DD 12 del 18/09/2026») non valgono mai;
* **G4** `url_prova` e' una pagina **effettivamente scaricata** nel controllo,
  il cui testo contiene la citazione, su dominio ufficiale e mai aggregatore;
* **G5** coerenza direzionale (una proroga allunga, una chiusura anticipata non
  e' nel futuro, `check_dates_coherence` sulle date risultanti);
* **G6** parola chiave obbligatoria nella citazione, diversa per ogni tipo;
* **G7** seconda prova per ogni transizione di stato o di data;
* **G8** dedup a 30 giorni;
* **G9** la transizione esiste nella tabella di `stato_bando.TRANSIZIONI`.

Tutto l'I/O e' **iniettato**: il modulo non apre connessioni, non chiama il
modello e non scrive il DB da solo. `applica()` riceve la funzione RPC e la
usa solo se `bando_registra_evento` e' esposta; altrimenti degrada in ombra.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date as date_cls, datetime, timedelta
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import parse_qsl, unquote, urlsplit

from .date_validation import (
    check_dates_coherence,
    estrai_date_con_ruolo,
    norm_cit,
    parse_iso,
    ruolo_compatibile,
)
from . import impronte
from .dominio_ufficiale import TABELLA_SEED, dominio_di, e_aggregatore, verificabile
from .logger import logger
from .stato_bando import TRANSIZIONI, oggi_roma, transizione_ammessa

# --- vocabolario degli eventi (§13.5) ---------------------------------------

# Tipi che possono diventare leggibili (ricevere un cursore).
TIPI_LEGGIBILI: tuple[str, ...] = (
    "pubblicazione", "apertura_automatica", "chiusura_automatica", "apertura",
    "chiusura", "proroga", "riapertura", "rettifica", "sospensione", "revoca",
    "annullamento_revoca", "graduatoria", "esito", "faq", "nuovo_allegato",
    "fonte_ufficiale_verificata", "data_verificata", "preavviso_collegato",
    "fusione", "separazione", "cambio_slug", "ritiro", "correzione_redazionale",
)

# Tipi sempre interni: mai un cursore, mai leggibili (§13.5, §16.3 punto 4).
TIPI_INTERNI: tuple[str, ...] = (
    "segnale_fonte", "sparito_dalla_fonte", "elaborazione_bloccata",
    "fonte_ufficiale_non_trovata", "possibile_doppione",
)

# I soli tipi che il classificatore puo' proporre: `fusione`, `ritiro` e i
# tecnici non nascono mai da una lettura di pagina.
TIPI_PROPONIBILI: tuple[str, ...] = (
    "apertura", "chiusura", "proroga", "riapertura", "rettifica", "sospensione",
    "revoca", "annullamento_revoca", "graduatoria", "esito", "faq", "nuovo_allegato",
)

# Campi che una `rettifica` puo' dichiarare.
CAMPI_RETTIFICA: tuple[str, ...] = (
    "data_apertura", "data_scadenza", "contenuto", "allegati",
)

# Tipi per cui il link nuovo e' gia' la prova del cambiamento (§6.2, G2).
TIPI_DA_LINK: frozenset[str] = frozenset({"graduatoria", "esito", "faq", "nuovo_allegato"})

# Tipi che cambiano stato o date: per loro il G7 e' obbligatorio.
TIPI_CON_TRANSIZIONE: frozenset[str] = frozenset({
    "apertura", "chiusura", "proroga", "riapertura", "sospensione", "revoca",
    "annullamento_revoca",
})

MODALITA_OMBRA = "ombra"
MODALITA_ATTIVO = "attivo"

RPC_REGISTRA_EVENTO = "bando_registra_evento"

# `link_candidatura_source`: i soli valori ammessi dal CHECK gia' in tabella
# (§6.2, doppioni nell'interim). Scriverne uno fuori lista fa fallire l'intero
# UPDATE del doppione, non solo la colonna.
SORGENTE_CANDIDATURA_LINK = "extracted"
SORGENTE_CANDIDATURA_FONTE = "fallback_source"
SORGENTE_CANDIDATURA_ASSENTE = "missing"

FINESTRA_DEDUP_GIORNI = 30
QUOTA_TOKEN_G2 = 0.60
#: Un atto datato fino a tanti giorni prima dell'ultimo controllo e' ancora
#: una novita': la determina esce sul sito giorni dopo la sua data, e fra i
#: due controlli di un bando chiuso passano fino a 37 giorni.
MARGINE_ATTO_GIORNI = 15

# --- G6: parole chiave obbligatorie per tipo (§6.2) -------------------------
#
# Sono volutamente radici, non parole intere: «prorogato», «proroga»,
# «prorogando» devono cadere tutte dentro `prorog`. `nuovo_allegato` non ha
# parole chiave perche' la sua prova e' il link nuovo, non una frase.
PAROLE_G6: dict[str, re.Pattern[str]] = {
    "rettifica:data_apertura": re.compile(r"differ|posticip|rinvi|nuova data|a partire|\bdal\b", re.I),
    "rettifica:data_scadenza": re.compile(r"prorog|differ|nuovo termine|\bentro\b|scad", re.I),
    "rettifica:contenuto": re.compile(r"rettific|modific|integrat|aggiorna|errata", re.I),
    "rettifica:allegati": re.compile(r"allegat|document|modulistic|rettific", re.I),
    "rettifica": re.compile(r"rettific|modific|integrat|aggiorna|errata", re.I),
    "apertura": re.compile(r"apert|\bdal\b|a partire|attiv", re.I),
    "proroga": re.compile(r"prorog|differ|posticip|nuovo termine", re.I),
    "sospensione": re.compile(r"sospe", re.I),
    "revoca": re.compile(r"revoc|annull|ritir", re.I),
    "annullamento_revoca": re.compile(r"annullament\w* della revoca|revoca annullata|ripristin|riammess", re.I),
    "chiusura": re.compile(r"chius|esaurim", re.I),
    "riapertura": re.compile(r"riapert|riapre|riapri|ripres|riattiv|nuovamente apert", re.I),
    "graduatoria": re.compile(r"graduator", re.I),
    "esito": re.compile(r"esit|ammess|finanziat|beneficiar", re.I),
    "faq": re.compile(r"faq|domande frequenti|quesiti", re.I),
}

# Le prove indipendenti ammesse dal G7 (§6.2). `modified` e `ds_last_update`
# NON sono qui, ed e' il punto: sono il segnale che ha innescato il controllo,
# provano che la pagina e' cambiata, non che la lettura sia giusta.
PROVE_G7_AMMESSE: frozenset[str] = frozenset({
    "pagina_collegata", "deadline_label", "sedia",
})
PROVE_G7_VIETATE: frozenset[str] = frozenset({"modified", "ds_last_update", "updates_active"})


# --- tool per il classificatore --------------------------------------------

STRUMENTO_SALVA_EVENTI: dict[str, Any] = {
    "name": "salva_eventi",
    "description": (
        "Registra gli eventi che il diff della pagina ufficiale dimostra. "
        "Un evento va emesso SOLO se una frase della pagina lo dichiara: la "
        "citazione deve essere copiata alla lettera dal testo fornito, mai "
        "riassunta. Se il diff non dimostra nessun evento, chiama comunque lo "
        "strumento con eventi=[]."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "eventi": {
                "type": "array",
                "description": "Eventi dimostrati dal diff; vuoto se nessuno.",
                "items": {
                    "type": "object",
                    "properties": {
                        "tipo": {
                            "type": "string",
                            "enum": list(TIPI_PROPONIBILI),
                            "description": "Tipo di evento.",
                        },
                        "campo": {
                            "type": "string",
                            "enum": list(CAMPI_RETTIFICA),
                            "description": "Obbligatorio per tipo=rettifica: campo rettificato.",
                        },
                        "valore": {
                            "type": "string",
                            "description": (
                                "Nuovo valore del campo in formato ISO YYYY-MM-DD "
                                "per le date; assente per gli eventi senza data."
                            ),
                        },
                        "data_evento": {
                            "type": "string",
                            "description": "Data ISO in cui l'ente dichiara l'evento, se indicata.",
                        },
                        "citazione": {
                            "type": "string",
                            "description": (
                                "Frase copiata ALLA LETTERA dalla pagina (max 300 caratteri) "
                                "che dimostra l'evento."
                            ),
                        },
                        "url_prova": {
                            "type": "string",
                            "description": "URL, fra quelli forniti, della pagina che contiene la citazione.",
                        },
                        "confidenza": {
                            "type": "number",
                            "description": "0..1, quanto la citazione e' esplicita. Solo indicativa.",
                        },
                    },
                    "required": ["tipo", "citazione", "url_prova"],
                },
            }
        },
        "required": ["eventi"],
    },
}


ISTRUZIONI_CLASSIFICATORE = (
    "Sei un analista di bandi pubblici italiani. Ricevi il DIFF fra due letture "
    "della pagina ufficiale di un bando, i link comparsi o spariti, lo stato e le "
    "date che oggi risultano in archivio, e la data di oggi.\n\n"
    "Il tuo compito e' dire quali eventi il diff DIMOSTRA. Regole assolute:\n"
    "1. la citazione va copiata alla lettera dal testo fornito, mai riscritta;\n"
    "2. non dedurre: se la pagina non lo dice, l'evento non esiste;\n"
    "3. ignora le date che compaiono dentro riferimenti normativi "
    "(«ai sensi del DD 12 del 18/09/2026», «DGR 445/2026»): sono l'atto, non il bando;\n"
    "4. una scadenza che si allunga e' una `proroga`; una data che cambia prima "
    "dell'apertura e' una `rettifica` con campo=data_apertura;\n"
    "5. `url_prova` deve essere uno degli URL elencati, mai un link citato nel testo.\n"
    "Chiama sempre lo strumento salva_eventi, anche con eventi=[]."
)


# --- tipi -------------------------------------------------------------------

@dataclass(frozen=True)
class Pagina:
    """Una pagina scaricata **in questo controllo**. Nient'altro e' una prova."""
    url: str
    testo: str = ""
    impronta: str = ""
    collegata: bool = False          # pagina collegata (max 2 per bando, §6.2)


@dataclass(frozen=True)
class Prova:
    """Una prova indipendente per il G7."""
    genere: str                      # pagina_collegata | deadline_label | sedia
    data: date_cls | None = None
    ruolo: str = ""
    url: str = ""


@dataclass(frozen=True)
class Evento:
    """Un evento proposto dal classificatore, prima dei gate."""
    tipo: str
    citazione: str = ""
    url_prova: str = ""
    campo: str | None = None
    valore: str | None = None
    data_evento: date_cls | None = None
    confidenza_llm: float = 0.0

    @property
    def chiave_g6(self) -> str:
        return f"{self.tipo}:{self.campo}" if self.campo else self.tipo

    @property
    def data_valore(self) -> date_cls | None:
        """La data dichiarata come nuovo valore, se il campo e' una data."""
        if self.campo in ("data_apertura", "data_scadenza") or self.tipo in (
            "proroga", "apertura", "chiusura", "riapertura",
        ):
            return parse_iso(self.valore) if self.valore else None
        return None


@dataclass(frozen=True)
class Contesto:
    """Tutto cio' che i gate devono sapere. Nessun accesso esterno da qui."""
    bando_id: int | None = None
    stato_bando: str | None = None
    data_apertura: date_cls | None = None
    data_scadenza: date_cls | None = None
    data_pubblicazione: date_cls | None = None
    ora_scadenza: str | None = None
    pagine: tuple[Pagina, ...] = ()
    diff: Any = None                                  # impronte.Diff | None
    testo_prima: str | None = None
    eventi_recenti: tuple[Mapping[str, Any], ...] = ()
    prove: tuple[Prova, ...] = ()
    # Il secondo modello risponde con una LISTA di eventi, non con uno solo:
    # un differimento reale ne produce due (apertura e scadenza). Si accetta
    # anche un singolo `Evento` per comodita' dei chiamanti e dei test.
    seconda_opinione: Any = None
    tabella_domini: Any = None
    oggi: date_cls | None = None
    ultimo_controllo: date_cls | None = None          # giorno del controllo precedente
    stati_estesi: bool = False                        # migrazione 06 applicata
    modalita: str = MODALITA_OMBRA

    @property
    def giorno(self) -> date_cls:
        return self.oggi or oggi_roma()

    def pagina(self, url: str) -> Pagina | None:
        for p in self.pagine:
            if p.url == url:
                return p
        return None


@dataclass(frozen=True)
class Giudizio:
    """Esito dei gate. `gate` dice quale variante di G2 e' stata applicata."""
    ammesso: bool = False
    gate: str = "G2"
    superati: tuple[str, ...] = ()
    falliti: tuple[tuple[str, str], ...] = ()
    confidenza: float = 0.0
    leggibile: bool = False
    nuovo_stato: str | None = None
    note: tuple[str, ...] = ()

    @property
    def motivo(self) -> str:
        return "; ".join(f"{g}: {m}" for g, m in self.falliti)

    def come_dizionario(self) -> dict[str, Any]:
        return {
            "ammesso": self.ammesso,
            "gate": self.gate,
            "superati": list(self.superati),
            "falliti": [{"gate": g, "motivo": m} for g, m in self.falliti],
            "confidenza": self.confidenza,
            "leggibile": self.leggibile,
            "nuovo_stato": self.nuovo_stato,
            "note": list(self.note),
        }


# --- lettura della risposta del modello -------------------------------------

def leggi_eventi(risposta: Any) -> tuple[Evento, ...]:
    """Eventi dal `tool_use` del modello. Mai eccezioni: una risposta storta
    vale «nessun evento», non un giro interrotto."""
    blocchi = getattr(risposta, "content", None)
    if blocchi is None and isinstance(risposta, Mapping):
        blocchi = risposta.get("content")
    proposte: list[Any] = []
    for blocco in blocchi or []:
        nome = getattr(blocco, "name", None) or (
            blocco.get("name") if isinstance(blocco, Mapping) else None)
        if nome != STRUMENTO_SALVA_EVENTI["name"]:
            continue
        ingresso = getattr(blocco, "input", None) or (
            blocco.get("input") if isinstance(blocco, Mapping) else None)
        if isinstance(ingresso, str):
            try:
                ingresso = json.loads(ingresso)
            except ValueError:
                continue
        if isinstance(ingresso, Mapping):
            voci = ingresso.get("eventi")
            if isinstance(voci, list):
                proposte.extend(voci)
    return tuple(e for e in (evento_da(v) for v in proposte) if e is not None)


def evento_da(voce: Any) -> Evento | None:
    """`Evento` da un dizionario del tool. None se il tipo non e' proponibile."""
    if not isinstance(voce, Mapping):
        return None
    tipo = str(voce.get("tipo") or "").strip()
    if tipo not in TIPI_PROPONIBILI:
        return None
    campo = str(voce.get("campo") or "").strip() or None
    if campo is not None and campo not in CAMPI_RETTIFICA:
        campo = None
    try:
        confidenza = float(voce.get("confidenza") or 0.0)
    except (TypeError, ValueError):
        confidenza = 0.0
    return Evento(
        tipo=tipo,
        citazione=str(voce.get("citazione") or ""),
        url_prova=str(voce.get("url_prova") or "").strip(),
        campo=campo,
        valore=str(voce.get("valore") or "").strip() or None,
        data_evento=parse_iso(str(voce.get("data_evento") or "")) or None,
        confidenza_llm=max(0.0, min(1.0, confidenza)),
    )


def prompt_utente(ctx: Contesto, *, diff_testo: str | None = None) -> str:
    """Il messaggio utente del classificatore: diff + link + stato/date + oggi.

    Volutamente compatto (~2 000-2 500 token, §6.2): il costo del monitor e'
    dominato dal numero di classificazioni, non dalla loro lunghezza, ma un
    prompt che raddoppia raddoppia anche il conto a fine mese.
    """
    diff = ctx.diff
    testo = diff_testo if diff_testo is not None else getattr(diff, "testo", "") or ""
    aggiunti = tuple(getattr(diff, "link_aggiunti", ()) or ())
    rimossi = tuple(getattr(diff, "link_rimossi", ()) or ())

    righe = [
        f"OGGI (calendario di Roma): {ctx.giorno.isoformat()}",
        "",
        "STATO IN ARCHIVIO",
        f"- stato_bando: {ctx.stato_bando or 'ignoto'}",
        f"- data_apertura: {ctx.data_apertura.isoformat() if ctx.data_apertura else 'assente'}",
        f"- data_scadenza: {ctx.data_scadenza.isoformat() if ctx.data_scadenza else 'assente'}",
        "",
        "PAGINE SCARICATE IN QUESTO CONTROLLO (url_prova ammessi)",
    ]
    righe += [f"- {p.url}" for p in ctx.pagine] or ["- (nessuna)"]
    if aggiunti:
        righe += ["", "LINK COMPARSI"] + [f"- {u}" for u in aggiunti[:20]]
    if rimossi:
        righe += ["", "LINK SPARITI"] + [f"- {u}" for u in rimossi[:20]]
    if testo:
        vuoto = testo
    elif ctx.testo_prima is None or diff is None:
        vuoto = "(nessun diff: e' il primo controllo di questa pagina)"
    else:
        vuoto = "(nessuna riga di testo cambiata: sono cambiati solo i link, vedi sopra)"
    righe += ["", "DIFF", vuoto]
    return "\n".join(righe)


# --- gate -------------------------------------------------------------------

def usa_g2_primo(ctx: Contesto) -> bool:
    """Vero quando va applicata la variante G2' («G2 primo»).

    Due casi, entrambi di §6.2: il **primo controllo** (non esiste nessun
    `testo_prima`, quindi nessun diff puo' esistere) e il **mismatch senza
    diff** (la pagina non e' cambiata ma le sue date non coincidono con le
    colonne: e' il caso L6 della semina, e il caso «Psicologia scolastica»,
    dove il differimento e' anteriore alla prima lettura).
    """
    if ctx.testo_prima is None:
        return True
    diff = ctx.diff
    if diff is None:
        return True
    return bool(getattr(diff, "vuoto", False))


def _token(testo: str) -> tuple[str, ...]:
    return tuple(t for t in re.split(r"[^0-9a-zà-ÿ]+", norm_cit(testo)) if t)


def _compatto(testo: str) -> str:
    # Gli spazi si tolgono solo accanto a una non-cifra: «3» e «1/12» su due
    # righe non devono diventare «31/12» (revisione del 29/09/2026).
    return re.sub(r"(?<=\D)\s+|\s+(?=\D)", "", testo)


def citazione_in(citazione: str, testo: str) -> bool:
    """La citazione sta nel testo, anche a spazi diversi.

    `testo_normalizzato` va a capo a ogni tag inline («dell'8/11/2026</strong>.»
    diventa «dell'8/11/2026 .»), e il modello a volte ricompone la frase o
    incolla due parole («Aperturavenerdi'»). Confrontare anche senza spazi
    salva le citazioni vere senza far passare un riassunto: le parole devono
    esserci tutte, nello stesso ordine. Misurato il 28/09/2026: 3 dei 5
    respinti per G1 erano citazioni vere, fra cui una proroga reale.
    """
    citazione, testo = norm_cit(citazione), norm_cit(testo)
    if not citazione:
        return False
    return citazione in testo or _compatto(citazione) in _compatto(testo)


def g1_citazione(evento: Evento, ctx: Contesto) -> tuple[bool, str]:
    """La citazione e' sottostringa di una pagina scaricata in questo controllo."""
    if not norm_cit(evento.citazione):
        return False, "citazione vuota"
    for pagina in ctx.pagine:
        if citazione_in(evento.citazione, pagina.testo):
            return True, ""
    return False, "citazione non presente in nessuna pagina scaricata"


def g2_diff(evento: Evento, ctx: Contesto) -> tuple[bool, str]:
    """La citazione interseca le righe AGGIUNTE del diff (>= 60 % dei token).

    Per graduatoria/esito/faq/nuovo_allegato vale anche il nome di un link
    nuovo: quegli eventi si annunciano con un documento, non sempre con una
    frase. Ma la citazione deve parlare di QUEL documento. Fino al 29/09/2026
    bastava che un link nuovo qualsiasi esistesse, e col diff che dava per
    «comparsi» tutti i link della pagina il gate passava sempre (19 su 19).
    """
    diff = ctx.diff
    if diff is None:
        return False, "nessun diff disponibile"
    aggiunte = " ".join(getattr(diff, "righe_aggiunte", ()) or ())
    link_nuovi = tuple(getattr(diff, "link_aggiunti", ()) or ()) if evento.tipo in TIPI_DA_LINK else ()
    if not aggiunte.strip() and not link_nuovi:
        return False, "nessuna riga aggiunta nel diff"
    token_citazione = _token(evento.citazione)
    if not token_citazione:
        return False, "citazione senza token"
    # Il nome di un documento nuovo vale, ma link per link e sulle sole parole
    # di contenuto: host, anno e mese del percorso («uploads/2026/09») facevano
    # passare qualunque citazione (revisione del 29/09/2026).
    contenuto = [t for t in token_citazione if len(t) >= 3 and not t.isdigit()]
    for link in link_nuovi:
        parole = _token_link(link)
        if contenuto and parole and \
                sum(1 for t in contenuto if t in parole) / len(contenuto) >= QUOTA_TOKEN_G2:
            return True, ""
    if not aggiunte.strip():
        return False, "citazione estranea ai link nuovi"
    token_aggiunte = set(_token(aggiunte))
    comuni = sum(1 for t in token_citazione if t in token_aggiunte)
    quota = comuni / len(token_citazione)
    if quota < QUOTA_TOKEN_G2:
        return False, f"citazione fuori dalle righe aggiunte ({quota:.0%} < {QUOTA_TOKEN_G2:.0%})"
    return True, ""


def _token_link(url: str) -> set[str]:
    """Le parole di contenuto di un link: percorso e valori della query.
    Niente schema, host, chiavi della query, cifre ne' parole di due lettere.

    I valori della query contano perche' molti enti mettono li' il nome del
    file (`download.php?file=graduatoria.pdf`, `nomeFile=Decreto+n.…`).
    """
    try:
        parti = urlsplit(url)
        valori = [v for _, v in parse_qsl(parti.query, keep_blank_values=False)]
    except ValueError:
        return set()
    testo = " ".join([unquote(parti.path), *valori])
    return {t for t in _token(testo) if len(t) >= 3 and not t.isdigit()}


def g2_primo(evento: Evento, ctx: Contesto) -> tuple[bool, str]:
    """G2': la coppia (data, ruolo) della citazione e' NUOVA.

    Senza un «prima» non esiste nessun diff da intersecare, quindi la novita'
    si dimostra in un altro modo: la data letta non e' quella che abbiamo in
    colonna e — se una lettura precedente esiste — non era nemmeno nel testo
    di allora. E' il gate della semina (L6) e dei bandi mai controllati.
    """
    data = evento.data_valore or evento.data_evento
    if data is None:
        # Un evento senza data al primo controllo non e' dimostrabile: non c'e'
        # niente da confrontare con le colonne.
        return False, "G2' richiede una data: evento senza data al primo controllo"
    ruolo = _ruolo_atteso(evento)
    in_colonna = {
        "apertura": ctx.data_apertura,
        "scadenza": ctx.data_scadenza,
        "pubblicazione": ctx.data_pubblicazione,
    }.get(ruolo)
    if in_colonna == data:
        return False, f"la data {data.isoformat()} e' gia' in colonna ({ruolo})"
    if ctx.testo_prima:
        for trovata in estrai_date_con_ruolo(ctx.testo_prima):
            if trovata.data == data and ruolo_compatibile(trovata.ruolo, ruolo):
                return False, f"la data {data.isoformat()} era gia' nel testo precedente"
    return True, ""


def _ruolo_atteso(evento: Evento) -> str:
    """Ruolo della data dichiarata: e' il campo, o il verso dell'evento."""
    if evento.campo == "data_apertura":
        return "apertura"
    if evento.campo == "data_scadenza":
        return "scadenza"
    if evento.tipo in ("proroga", "chiusura"):
        return "scadenza"
    if evento.tipo in ("apertura", "riapertura"):
        return "apertura"
    return "scadenza"


def g3_ruolo(evento: Evento, ctx: Contesto) -> tuple[bool, str]:
    """La data dichiarata compare nella citazione con un ruolo compatibile.

    Le date normative non valgono mai: «ai sensi del DD 12 del 18/09/2026» e'
    l'atto che dispone, non una data del bando. E' il caso reale che ha
    prodotto la regola.
    """
    data = evento.data_valore
    if data is None:
        # Eventi senza data (sospensione, revoca, faq...): niente da validare,
        # ma una `data_evento` normativa resta inammissibile.
        if evento.data_evento is None:
            if evento.tipo in TIPI_DA_LINK:
                # `data_evento` e' facoltativa: senza, l'atto vecchio passava.
                # Si guardano le date d'atto della citazione (revisione del
                # 29/09/2026: 9750 e 9834 citavano una determina di luglio).
                atti = [c.data for c in estrai_date_con_ruolo(evento.citazione)
                        if c.ruolo == "normativa"]
                if atti and not any(_atto_recente(d, ctx) for d in atti):
                    return False, f"l'atto citato ({max(atti).isoformat()}) non e' recente"
            return True, ""
        data = evento.data_evento
    ruolo = _ruolo_atteso(evento)
    trovate = estrai_date_con_ruolo(evento.citazione)
    if evento.tipo in TIPI_DA_LINK and data == evento.data_evento:
        # Graduatorie, esiti, FAQ e allegati si pubblicano con «Determinazione
        # n. X del <data>»: la data dell'atto E' la data dell'evento. Col ruolo
        # «normativa» il G3 respingeva proprio le graduatorie vere (evento
        # 9747, 28/09/2026). Ma solo un atto recente: uno di mesi fa non e' una
        # novita' (revisione del 29/09/2026).
        recente = _atto_recente(data, ctx)
        if recente and any(c.data == data for c in trovate):
            return True, ""
        if not recente:
            return False, f"la data dell'atto {data.isoformat()} non e' recente"
    for candidata in trovate:
        if candidata.data != data:
            continue
        if candidata.ruolo == "normativa":
            continue
        if ruolo_compatibile(candidata.ruolo, ruolo):
            return True, ""
    if any(c.data == data and c.ruolo == "normativa" for c in trovate):
        return False, f"la data {data.isoformat()} nella citazione e' un riferimento normativo"
    return False, f"la data {data.isoformat()} non compare nella citazione con ruolo {ruolo}"


def g4_prova(evento: Evento, ctx: Contesto) -> tuple[bool, str]:
    """`url_prova` e' una pagina scaricata, ufficiale e non aggregatore.

    Gli href presenti nell'HTML ma mai scaricati **non** sono ammessi: un link
    in sidebar non dimostra niente, e sarebbe il modo piu' facile per far
    passare una prova che nessuno ha letto.
    """
    if not evento.url_prova:
        return False, "url_prova assente"
    pagina = ctx.pagina(evento.url_prova)
    if pagina is None:
        return False, "url_prova non e' una pagina scaricata in questo controllo"
    if not citazione_in(evento.citazione, pagina.testo):
        return False, "la citazione non e' nella pagina indicata da url_prova"
    host = dominio_di(evento.url_prova)
    if not host:
        return False, "url_prova senza host"
    # Senza tabella iniettata vale il seed compilato nel codice, lo stesso che
    # la migrazione 02 semina: `Tabella.da(None)` sarebbe invece una tabella
    # VUOTA, e con una tabella vuota nessun dominio e' verificante — il gate
    # respingerebbe tutto per un'omissione del chiamante.
    tabella = ctx.tabella_domini if ctx.tabella_domini is not None else TABELLA_SEED
    if e_aggregatore(host, tabella):
        return False, f"url_prova su dominio aggregatore ({host})"
    if not verificabile(host, tabella):
        return False, f"url_prova su dominio non verificabile ({host})"
    if not pagina.impronta:
        return False, "impronta della pagina di prova non registrata"
    return True, ""


def g5_direzione(evento: Evento, ctx: Contesto) -> tuple[bool, str]:
    """Coerenza direzionale dell'evento (§4, §6.2).

    Il caso piu' insidioso e' la proroga: senza `vecchia IS NOT NULL` una
    scadenza che compare per la prima volta su uno dei 416 bandi a sportello
    verrebbe letta come proroga, e la vista chiuderebbe un bando che non ha
    mai avuto una scadenza. Quella non e' una proroga: e' una
    `rettifica campo=data_scadenza`, con G6 proprio e G7 obbligatorio.
    """
    oggi = ctx.giorno
    data = evento.data_valore

    if evento.tipo == "proroga":
        if ctx.data_scadenza is None:
            return False, "proroga senza scadenza precedente: e' una rettifica data_scadenza"
        if data is None:
            return False, "proroga senza nuova data"
        if data <= ctx.data_scadenza:
            return False, f"proroga non posticipa ({data} <= {ctx.data_scadenza})"
        if data < oggi:
            return False, f"proroga a una data gia' passata ({data} < {oggi})"

    elif evento.tipo == "chiusura":
        if data is not None and data > oggi:
            return False, f"chiusura anticipata nel futuro ({data} > {oggi})"

    elif evento.tipo == "apertura":
        if data is not None and data > oggi:
            return False, f"apertura dichiarata nel futuro ({data} > {oggi}): e' una rettifica"

    elif evento.tipo == "riapertura":
        if data is not None and data < oggi:
            return False, f"riapertura a una data gia' passata ({data} < {oggi})"

    elif evento.tipo == "rettifica" and evento.campo == "data_apertura":
        if data is None:
            return False, "rettifica data_apertura senza data"
        if ctx.stato_bando == "in apertura prossimamente" and data < oggi:
            return False, f"differimento a una data gia' passata ({data} < {oggi})"

    elif evento.tipo == "rettifica" and evento.campo == "data_scadenza":
        if data is None:
            return False, "rettifica data_scadenza senza data"

    # `check_dates_coherence` sulle date RISULTANTI. Una violazione rende
    # l'evento non leggibile; non si azzerano mai tutte le date (il difetto
    # storico che il piano vieta esplicitamente).
    apertura, scadenza = _date_risultanti(evento, ctx)
    if not check_dates_coherence(ctx.data_pubblicazione, apertura, scadenza):
        return False, "le date risultanti violano pubblicazione <= apertura <= scadenza"
    return True, ""


def _date_risultanti(evento: Evento, ctx: Contesto) -> tuple[date_cls | None, date_cls | None]:
    """Le date come sarebbero dopo l'evento (senza scriverle)."""
    apertura = ctx.data_apertura
    scadenza = ctx.data_scadenza
    data = evento.data_valore
    if data is None:
        return apertura, scadenza
    if evento.campo == "data_apertura" or evento.tipo in ("apertura", "riapertura"):
        apertura = data
    elif evento.campo == "data_scadenza" or evento.tipo == "proroga":
        scadenza = data
    # `chiusura`: la scadenza resta INTATTA (§4). Scrivere «oggi» fabbricherebbe
    # una data che nessuno ha dichiarato.
    return apertura, scadenza


def g6_parola(evento: Evento, ctx: Contesto) -> tuple[bool, str]:
    """Parola chiave obbligatoria nella citazione, per tipo (§6.2)."""
    if evento.tipo == "nuovo_allegato":
        return True, ""
    modello = PAROLE_G6.get(evento.chiave_g6) or PAROLE_G6.get(evento.tipo)
    if modello is None:
        return False, f"nessuna parola chiave definita per {evento.chiave_g6}"
    if modello.search(norm_cit(evento.citazione)):
        return True, ""
    return False, f"citazione senza parola chiave per {evento.chiave_g6}"


def g7_seconda_prova(evento: Evento, ctx: Contesto, *, doppia: bool) -> tuple[bool, str]:
    """Seconda prova per ogni transizione di stato o di data.

    Due modi: la concordanza del modello grande sullo stesso diff, oppure una
    prova indipendente (pagina collegata scaricata con la stessa coppia
    (data, ruolo), `deadline_label` di OE concorde, `latestInfos` SEDIA).
    In G2' servono **entrambe**: senza un «prima» la lettura e' l'unica cosa
    che abbiamo, e una sola conferma sarebbe il modello che conferma se stesso.
    """
    concorde = _concordanza(evento, ctx.seconda_opinione)
    indipendente = _prova_indipendente(evento, ctx)

    if doppia:
        if concorde and indipendente is not None:
            return True, ""
        mancanti = []
        if not concorde:
            mancanti.append("seconda opinione")
        if indipendente is None:
            mancanti.append("prova indipendente")
        return False, "G2' richiede entrambe le prove, mancano: " + " e ".join(mancanti)

    if concorde or indipendente is not None:
        return True, ""
    return False, "nessuna seconda prova (ne' concordanza ne' prova indipendente)"


def _concordanza(evento: Evento, seconda: Any) -> bool:
    """Il secondo modello dice la stessa cosa su tipo, campo e data?

    `seconda` puo' essere un evento solo o la lista che il secondo modello ha
    prodotto: basta che **uno** dei suoi eventi combaci, perche' una lettura
    che ne trova tre e ne azzecca uno conferma quell'uno, non gli altri.
    """
    if seconda is None:
        return False
    candidati = seconda if isinstance(seconda, (list, tuple)) else (seconda,)
    for altro in candidati:
        if not isinstance(altro, Evento):
            continue
        if altro.tipo != evento.tipo:
            continue
        if (altro.campo or None) != (evento.campo or None):
            continue
        if (altro.data_valore or altro.data_evento) == (
                evento.data_valore or evento.data_evento):
            return True
    return False


def _prova_indipendente(evento: Evento, ctx: Contesto) -> Prova | None:
    """La prima prova indipendente che conferma la stessa (data, ruolo).

    Senza una data da confrontare non esiste conferma indipendente. Prima
    questa funzione, con `data=None`, accettava QUALUNQUE prova di ruolo
    compatibile: una `chiusura` senza valore — su cui G3 esce subito e G5 non
    ha niente da confrontare — passava il G7 con una scadenza qualsiasi letta
    su una pagina collegata, e «lo sportello e' chiuso il martedi» sarebbe
    bastato a portare `stato_bando` a `chiuso`. Per gli eventi senza data
    resta l'altra strada del G7, la concordanza del secondo modello.
    """
    data = evento.data_valore or evento.data_evento
    if data is None:
        return None
    ruolo = _ruolo_atteso(evento)
    for prova in ctx.prove:
        if prova.genere in PROVE_G7_VIETATE:
            continue
        if prova.genere not in PROVE_G7_AMMESSE:
            continue
        if prova.data != data:
            continue
        if prova.ruolo and not ruolo_compatibile(prova.ruolo, ruolo):
            continue
        return prova
    return None


def _atto_recente(data: date_cls, ctx: Contesto) -> bool:
    """L'atto e' una novita' per questo controllo: non futuro, e datato negli
    ultimi 30 giorni oppure dopo l'ultimo controllo (meno un margine).

    Contare solo da oggi respingeva le graduatorie vere dei bandi chiusi, che
    si ricontrollano ogni 22-37 giorni: la pagina nuova arrivava al modello
    con l'atto gia' vecchio di 35 giorni, e la memoria salvata la faceva
    sparire per sempre (revisione del 29/09/2026).
    """
    if data > ctx.giorno:
        return False
    if (ctx.giorno - data).days <= FINESTRA_DEDUP_GIORNI:
        return True
    return ctx.ultimo_controllo is not None and \
        data >= ctx.ultimo_controllo - timedelta(days=MARGINE_ATTO_GIORNI)


def g8_dedup(
    evento: Evento, ctx: Contesto, *, giorni: int = FINESTRA_DEDUP_GIORNI,
    giorno_di: Callable[[Mapping[str, Any]], date_cls | None] | None = None,
) -> tuple[bool, str]:
    """Nessun evento uguale negli ultimi 30 giorni (§6.2 G8, §16.2 M6).

    «Uguale» e' (tipo, campo, valore): la stessa proroga vista in due giri
    consecutivi e' un solo fatto, e due righe leggibili nel box «Aggiornamenti»
    sarebbero due volte la stessa notizia. `giorno_di` sceglie da quale data
    si misura la finestra (il monitor: `_giorno_evento`).
    """
    giorno_di = giorno_di or _giorno_evento
    oggi = ctx.giorno
    for passato in ctx.eventi_recenti:
        if str(passato.get("tipo") or "") != evento.tipo:
            continue
        if (passato.get("campo") or None) != (evento.campo or None):
            continue
        if _valore_evento(passato) != (evento.valore or None):
            continue
        quando = giorno_di(passato)
        if quando is None:
            continue
        if 0 <= (oggi - quando).days <= giorni:
            return False, f"evento identico gia' registrato il {quando.isoformat()}"
    return True, ""


def _valore_evento(riga: Mapping[str, Any]) -> str | None:
    dopo = riga.get("valore_dopo")
    if isinstance(dopo, Mapping):
        # «data_scadenza» e «data_apertura» dal 29/09/2026: e' la forma che
        # `riga_evento` scrive per le date, senza `campo`.
        for nome in ("valore", "data", "data_scadenza", "data_apertura", "stato_proposto"):
            if riga.get("campo") and riga.get("campo") in dopo:
                return str(dopo[riga["campo"]])
            if nome in dopo:
                return str(dopo[nome])
    valore = riga.get("valore")
    return str(valore) if valore is not None else None


def _giorno_registrato(riga: Mapping[str, Any]) -> date_cls | None:
    """Il giorno in cui l'evento e' stato registrato (`rilevato_at`); senza,
    come il monitor. Serve al G8 del percorso verifica: una chiusura ha come
    `data_evento` il termine letto, che puo' essere di mesi prima."""
    return _giorno_evento({"rilevato_at": riga.get("rilevato_at")}) or _giorno_evento(riga)


def _giorno_evento(riga: Mapping[str, Any]) -> date_cls | None:
    for nome in ("data_evento", "rilevato_at", "pubblicato_at"):
        valore = riga.get(nome)
        if isinstance(valore, datetime):
            return valore.date()
        if isinstance(valore, date_cls):
            return valore
        if isinstance(valore, str) and len(valore) >= 10:
            letta = parse_iso(valore[:10])
            if letta is not None:
                return letta
    return None


def transizione_evento(
    stato: str | None, evento: Evento, *, percorso: str = "monitor",
) -> str | None:
    """Stato di destinazione dell'evento, o None se lo stato non cambia (§4).

    E' la tabella di §4 riga per riga. `chiusura` porta a `chiuso` **senza**
    toccare `data_scadenza`; `graduatoria`/`esito`/`faq`/`nuovo_allegato` e le
    `rettifica` non cambiano mai stato.
    """
    tipo = evento.tipo
    if tipo == "revoca":
        return "revocato"
    if tipo == "sospensione":
        return "sospeso" if stato in ("aperto", "in apertura prossimamente") else None
    if tipo == "apertura":
        return "aperto" if stato == "in apertura prossimamente" else None
    if tipo == "proroga":
        return "aperto" if stato in ("aperto", "chiuso") else None
    if tipo == "riapertura":
        if stato == "chiuso":
            return "aperto"
        if stato == "sospeso":
            # Torna dove era prima: con un'apertura futura resta «in apertura».
            return "in apertura prossimamente" if evento.campo == "data_apertura" else "aperto"
        return None
    if tipo == "chiusura":
        if stato == "aperto":
            return "chiuso"
        # Riga 24 della lista bianca (contratto `bandi-giro-2` §4): da «in
        # apertura» chiude solo il percorso verifica_stato, con i suoi gate.
        # Il monitor resta com'era.
        if stato == "in apertura prossimamente" and percorso == PERCORSO_VERIFICA:
            return "chiuso"
        return None
    if tipo == "annullamento_revoca":
        # §4: la revoca e' terminale; l'annullamento esiste solo con nuova prova
        # e non e' nella lista bianca delle transizioni: G9 lo fermera'.
        return "aperto" if stato == "revocato" else None
    return None


def g9_transizione(evento: Evento, ctx: Contesto) -> tuple[bool, str]:
    """La transizione e' nella lista bianca di `stato_bando.TRANSIZIONI`."""
    nuovo = transizione_evento(ctx.stato_bando, evento)
    if nuovo is None or nuovo == ctx.stato_bando:
        return True, ""
    if transizione_ammessa(ctx.stato_bando, nuovo, "worker"):
        return True, ""
    return False, f"transizione {ctx.stato_bando!r} -> {nuovo!r} non prevista dalla macchina a stati"


# Peso di ogni gate nella confidenza deterministica. La confidenza dichiarata
# dal modello NON entra nella somma: e' solo il tiebreak fra due eventi che
# hanno superato gli stessi gate (§6.2).
PESI_GATE: dict[str, float] = {
    "G1": 0.15, "G2": 0.15, "G3": 0.15, "G4": 0.20,
    "G5": 0.10, "G6": 0.10, "G7": 0.10, "G8": 0.025, "G9": 0.025,
}


def valuta(evento: Evento, ctx: Contesto) -> Giudizio:
    """Applica i nove gate e ritorna il giudizio. Non scrive niente.

    La variante di G2 si sceglie **per prima** (§6.2, «G2 primo»), perche'
    decide anche la severita' di G7: in G2' servono due prove, non una.
    """
    primo = usa_g2_primo(ctx)
    nome_g2 = "G2'" if primo else "G2"
    richiede_g7 = (
        primo
        or evento.tipo in TIPI_CON_TRANSIZIONE
        or evento.data_valore is not None
    )

    controlli: list[tuple[str, Callable[[], tuple[bool, str]]]] = [
        ("G1", lambda: g1_citazione(evento, ctx)),
        (nome_g2, lambda: g2_primo(evento, ctx) if primo else g2_diff(evento, ctx)),
        ("G3", lambda: g3_ruolo(evento, ctx)),
        ("G4", lambda: g4_prova(evento, ctx)),
        ("G5", lambda: g5_direzione(evento, ctx)),
        ("G6", lambda: g6_parola(evento, ctx)),
        ("G8", lambda: g8_dedup(evento, ctx)),
        ("G9", lambda: g9_transizione(evento, ctx)),
    ]
    if richiede_g7:
        controlli.insert(6, ("G7", lambda: g7_seconda_prova(evento, ctx, doppia=primo)))

    superati: list[str] = []
    falliti: list[tuple[str, str]] = []
    punteggio = 0.0
    for nome, prova in controlli:
        ok, motivo = prova()
        if ok:
            superati.append(nome)
            punteggio += PESI_GATE.get(nome.rstrip("'"), 0.0)
        else:
            falliti.append((nome, motivo))

    ammesso = not falliti
    nuovo_stato = transizione_evento(ctx.stato_bando, evento) if ammesso else None
    note: list[str] = []
    if ammesso and not richiede_g7:
        note.append("G7 non richiesto: l'evento non cambia stato ne' date")

    return Giudizio(
        ammesso=ammesso,
        gate=nome_g2,
        superati=tuple(superati),
        falliti=tuple(falliti),
        confidenza=round(min(1.0, punteggio), 4),
        leggibile=ammesso,
        nuovo_stato=nuovo_stato if nuovo_stato != ctx.stato_bando else None,
        note=tuple(note),
    )


# --- applicazione -----------------------------------------------------------

@dataclass(frozen=True)
class Applicazione:
    """Che cosa e' stato fatto (o che cosa si sarebbe fatto, in ombra)."""
    riga: dict[str, Any] = field(default_factory=dict)
    colonne: dict[str, Any] = field(default_factory=dict)
    applicato: bool = False
    scritto: bool = False
    motivo: str = ""
    giudizio: Giudizio | None = None

    def come_dizionario(self) -> dict[str, Any]:
        return {
            "riga": dict(self.riga),
            "colonne": dict(self.colonne),
            "applicato": self.applicato,
            "scritto": self.scritto,
            "motivo": self.motivo,
            "giudizio": self.giudizio.come_dizionario() if self.giudizio else None,
        }


def stato_solo_proposto(evento: Evento, ctx: Contesto) -> bool:
    """Regola A30: prima della migrazione 06 `sospeso` e `revocato` non sono
    valori ammessi dal CHECK della colonna.

    L'evento resta **leggibile** e **in_aggiornamenti** (il box di news1 dice
    «Bando sospeso secondo <ente> il <data>» e disattiva la CTA) ma
    `applicato=false` e la colonna non si tocca. Nessun proxy: scrivere
    «chiuso» al posto di «revocato» direbbe al lettore una cosa falsa.
    """
    return evento.tipo in ("sospensione", "revoca") and not ctx.stati_estesi


def colonne_da_evento(evento: Evento, ctx: Contesto, giudizio: Giudizio) -> dict[str, Any]:
    """Le colonne di `bando` che l'evento scriverebbe. Mai `slug`, mai `titolo`.

    `chiusura` non scrive `data_scadenza`: §4 e' esplicito, la scadenza resta
    quella dichiarata dall'ente e lo stato basta a chiudere il bando.
    """
    if not giudizio.ammesso:
        return {}
    if stato_solo_proposto(evento, ctx):
        return {}

    colonne: dict[str, Any] = {}
    data = evento.data_valore
    if data is not None:
        if evento.campo == "data_apertura" or evento.tipo in ("apertura", "riapertura"):
            colonne["data_apertura"] = data.isoformat()
            colonne["data_apertura_verificata"] = True
        elif evento.campo == "data_scadenza" or evento.tipo == "proroga":
            colonne["data_scadenza"] = data.isoformat()
            colonne["data_scadenza_verificata"] = True
    if giudizio.nuovo_stato:
        colonne["stato_bando"] = giudizio.nuovo_stato
    return colonne


def chiave_del_valore(evento: Evento) -> str:
    """La chiave di `valore_dopo` per il valore dell'evento.

    Per una data e' la colonna che `colonne_da_evento` scrive, con la stessa
    precedenza: e' l'unica chiave che `bando_applica_evento` riconosce. Fino
    al 29/09/2026 una proroga senza `campo` finiva in `{"valore": …}`, la RPC
    la scartava e l'evento risultava applicato con la scadenza vecchia
    (evento 9786). La `chiusura` resta su «valore» apposta (§4: la scadenza
    resta quella dichiarata dall'ente).
    """
    if evento.data_valore is not None:
        if evento.campo == "data_apertura" or evento.tipo in ("apertura", "riapertura"):
            return "data_apertura"
        if evento.campo == "data_scadenza" or evento.tipo == "proroga":
            return "data_scadenza"
    return evento.campo or "valore"


def riga_evento(evento: Evento, ctx: Contesto, giudizio: Giudizio) -> dict[str, Any]:
    """Payload di `bando_evento` per questo evento."""
    proposto = stato_solo_proposto(evento, ctx)
    ombra = ctx.modalita != MODALITA_ATTIVO
    leggibile = giudizio.ammesso and not ombra
    valore_dopo: dict[str, Any] = {}
    if evento.valore:
        chiave = chiave_del_valore(evento)
        valore_dopo[chiave] = (
            evento.data_valore.isoformat()
            if chiave in ("data_apertura", "data_scadenza") and evento.data_valore is not None
            else evento.valore)
    if proposto and giudizio.nuovo_stato:
        valore_dopo["stato_proposto"] = giudizio.nuovo_stato
    elif giudizio.nuovo_stato:
        valore_dopo["stato_bando"] = giudizio.nuovo_stato

    valore_prima: dict[str, Any] = {}
    # La stessa colonna di `valore_dopo`: `rigenera.date_da_evento` cerca la
    # data vecchia li'.
    colonna = chiave_del_valore(evento) if evento.valore else evento.campo
    if colonna == "data_apertura" or evento.campo == "data_apertura":
        valore_prima["data_apertura"] = ctx.data_apertura.isoformat() if ctx.data_apertura else None
    elif colonna == "data_scadenza" or evento.campo == "data_scadenza" or evento.tipo == "proroga":
        valore_prima["data_scadenza"] = ctx.data_scadenza.isoformat() if ctx.data_scadenza else None
    if giudizio.nuovo_stato:
        valore_prima["stato_bando"] = ctx.stato_bando

    return {
        "bando_id": ctx.bando_id,
        "tipo": evento.tipo,
        "origine": "worker",
        "campo": evento.campo,
        "valore_prima": valore_prima,
        "valore_dopo": valore_dopo,
        # QUANDO l'ente ha dichiarato l'evento, mai il nuovo valore della data:
        # quello sta in `valore_dopo`. Con il ripiego su `data_valore` una
        # proroga al 1/12 letta il 23/9 usciva datata 1/12, cioe' nel futuro —
        # e il G8, che deduplica su `0 <= (oggi - quando).days <= 30`, non
        # scattava piu' (la differenza era negativa): la stessa proroga
        # ripassava a ogni giro. Stesso difetto nell'indice di dedup a DB
        # (§16.2 M6), che usa `coalesce(data_evento, rilevato_at::date)`.
        # Per i tipi «da link» nessun ripiego sul giorno del controllo: un
        # documento di luglio letto il 25/09 non e' «nuovo del 25/09» (tre
        # eventi pubblici cosi' il 28/09/2026). Meglio nessuna data.
        "data_evento": (
            evento.data_evento.isoformat() if evento.data_evento
            else None if evento.tipo in TIPI_DA_LINK
            else ctx.giorno.isoformat()),
        "citazione": evento.citazione[:300],
        "url_prova": evento.url_prova,
        # `dominio_prova` NON entra: in tabella e' `GENERATED ALWAYS AS
        # (dominio_di(url_prova)) STORED` (02:581), e un INSERT che la
        # valorizzi risponde 428C9. In lettura resta corretta.
        "verificato": giudizio.ammesso,
        "leggibile": leggibile,
        # A30: sospensione e revoca restano visibili nel box ma non applicate.
        "in_aggiornamenti": leggibile and evento.tipo != "apertura_automatica",
        "applicato": giudizio.ammesso and not proposto and not ombra,
        # `bando_evento.confidenza` e' uno **smallint**, e il resolver ci
        # scrive un punteggio 0-100 (`int(esito.confidenza)`): il giudizio
        # degli eventi tiene invece una frazione 0-1, e scriverla cosi' com'e'
        # faceva rifiutare l'INSERT da Postgres con 22P02 («invalid input
        # syntax for type smallint: "0.65"»). `db.registra_evento` cattura
        # l'eccezione e la mette in un warning, quindi il giro si dichiarava
        # riuscito: misurato il 25/09/2026, **nessun evento del monitor era
        # mai arrivato a DB** in due giorni di ombra, e il periodo di misura
        # girava a vuoto. Una colonna, una sola scala: 0-100 come il resolver.
        "confidenza": int(round(max(0.0, min(1.0, giudizio.confidenza)) * 100)),
        # Non il nome del G2 applicato ma il **verdetto**: senza i falliti, un
        # respinto registrato non dice quale gate lo ha respinto, che e' la
        # sola informazione per cui vale la pena registrarlo. La colonna e'
        # jsonb e non e' concessa ad anon (§13.5): resta interna.
        "gate": {
            "g2": giudizio.gate,
            "superati": list(giudizio.superati),
            "falliti": [{"gate": g, "motivo": m} for g, m in giudizio.falliti],
            "confidenza_gate": giudizio.confidenza,
        },
    }


def applica(
    evento: Evento,
    ctx: Contesto,
    *,
    giudizio: Giudizio | None = None,
    rpc: Callable[[str, dict[str, Any]], Any] | None = None,
    controllo: Any = None,
) -> Applicazione:
    """Registra l'evento (e le sue colonne) via RPC, o lo lascia in ombra.

    Tre ragioni per NON scrivere, tutte volute:
      * i gate non sono passati — l'evento resta nel report d'ombra;
      * la modalita' e' `ombra` (default) — si registra tutto, non si applica
        niente: e' cosi' che si misura la precisione prima di attivare;
      * la RPC `bando_registra_evento` non esiste ancora (migrazione 02/04 non
        applicata) — si degrada con un log, non si solleva.
    """
    verdetto = giudizio if giudizio is not None else valuta(evento, ctx)
    riga = riga_evento(evento, ctx, verdetto)
    colonne = colonne_da_evento(evento, ctx, verdetto)

    if not verdetto.ammesso:
        return Applicazione(riga=riga, colonne={}, applicato=False, scritto=False,
                            motivo=verdetto.motivo or "gate non superati", giudizio=verdetto)

    if ctx.modalita != MODALITA_ATTIVO:
        return Applicazione(riga=riga, colonne=colonne, applicato=False, scritto=False,
                            motivo="modalita ombra", giudizio=verdetto)

    if not _rpc_disponibile(controllo):
        logger.info(
            "[eventi] RPC {} assente: evento {} del bando {} resta in ombra",
            RPC_REGISTRA_EVENTO, evento.tipo, ctx.bando_id,
        )
        return Applicazione(riga=riga, colonne=colonne, applicato=False, scritto=False,
                            motivo="rpc_assente", giudizio=verdetto)

    parametri = parametri_registra_evento(riga)
    try:
        risposta = (rpc or _rpc_predefinita)(RPC_REGISTRA_EVENTO, parametri)
    except Exception as e:
        logger.warning("[eventi] {} fallita per il bando {}: {}", RPC_REGISTRA_EVENTO, ctx.bando_id, e)
        return Applicazione(riga=riga, colonne=colonne, applicato=False, scritto=False,
                            motivo=f"rpc fallita: {e}", giudizio=verdetto)

    return Applicazione(riga=riga, colonne=colonne,
                        applicato=_applicato_dalla_rpc(risposta, bool(riga.get("applicato"))),
                        scritto=True, motivo="", giudizio=verdetto)


def _applicato_dalla_rpc(risposta: Any, predefinito: bool) -> bool:
    """`applicato` come lo dice `bando_registra_evento` ({id, nuovo, applicato}).

    Con date incoerenti, o uno stato che il CHECK non ammette, l'evento si
    registra ma non si applica: contarlo applicato faceva contare colonne e
    rigenerare la prosa con una data che la colonna non ha. Se la risposta non
    dice niente (RPC iniettata dai test) vale l'intenzione della riga.
    """
    dati = getattr(risposta, "data", risposta)
    if isinstance(dati, Mapping) and "applicato" in dati:
        return bool(dati["applicato"])
    return predefinito


#: I parametri di `bando_registra_evento` come la migrazione 04 li dichiara
#: (04:600-618), nell'ordine in cui li scrive. PostgREST risolve le RPC **per
#: nome**: un solo nome sbagliato e' un PGRST202 su tutta la chiamata, cioe'
#: un evento che resta in ombra senza che nessuno se ne accorga.
#: `p_run_id` e `p_riferisce_a` esistono ma qui non si passano: il primo lo
#: scrivera' chi lega l'evento alla riga di `pipeline_run`, il secondo serve
#: alle catene di eventi, che il monitor non produce.
PARAMETRI_REGISTRA_EVENTO: tuple[str, ...] = (
    "p_bando_id", "p_tipo", "p_origine", "p_campo", "p_valore_dopo",
    "p_url_prova", "p_citazione", "p_data_evento", "p_applica",
    "p_in_aggiornamenti", "p_leggibile", "p_impronta_pagina", "p_gate",
    "p_confidenza", "p_metodo",
)


def parametri_registra_evento(riga: Mapping[str, Any]) -> dict[str, Any]:
    """Una riga di `bando_evento` nei parametri della RPC.

    `colonne` non si passa: la RPC ricava da sola i campi da applicare
    leggendo `valore_dopo` (04:412-424). `verificato` nemmeno: lo decide il
    dominio della prova dentro la funzione, come vuole §13.5.
    """
    return {
        "p_bando_id": riga.get("bando_id"),
        "p_tipo": riga.get("tipo"),
        "p_origine": riga.get("origine"),
        "p_campo": riga.get("campo"),
        "p_valore_dopo": riga.get("valore_dopo"),
        "p_url_prova": riga.get("url_prova"),
        "p_citazione": riga.get("citazione"),
        "p_data_evento": riga.get("data_evento"),
        "p_applica": bool(riga.get("applicato")),
        "p_in_aggiornamenti": riga.get("in_aggiornamenti"),
        "p_leggibile": riga.get("leggibile"),
        "p_impronta_pagina": riga.get("impronta_pagina"),
        "p_gate": riga.get("gate"),
        "p_confidenza": riga.get("confidenza"),
        "p_metodo": riga.get("metodo"),
    }


def registra_via_rpc(
    riga: Mapping[str, Any],
    *,
    rpc: Callable[[str, dict[str, Any]], Any] | None = None,
    controllo: Any = None,
) -> dict[str, Any] | None:
    """Registra la riga con `bando_registra_evento`, **senza** applicarla ne'
    renderla leggibile, e ne restituisce `{id, nuovo}`.

    E' il primo dei tre passi dell'attivazione per tipo (`MONITOR_TIPI_ATTIVI`,
    contratto di ottobre 2026, §3); gli altri due sono quelli di
    `applica-eventi`: `bando_applica_evento`, poi `leggibile` (RIPRESA §5.8).
    La RPC unica del monitor attivo (`p_applica` e `p_leggibile` veri) qui non
    va bene: sul ramo della dedup applicherebbe un evento registrato prima,
    lasciandolo invisibile. `nuovo=false` dice proprio questo: l'indice di
    dedup ha riconosciuto un evento identico dello stesso giorno, che non e'
    nato in questo giro e non si tocca.

    None se la RPC non c'e', fallisce o non restituisce un id: il chiamante
    ripiega sull'INSERT d'ombra e l'evento non si perde.
    """
    if not _rpc_disponibile(controllo):
        return None
    parametri = parametri_registra_evento(riga)
    parametri.update(p_applica=False, p_leggibile=False, p_in_aggiornamenti=False)
    try:
        risposta = (rpc or _rpc_predefinita)(RPC_REGISTRA_EVENTO, parametri)
    except Exception as e:
        logger.warning("[eventi] {} fallita per il bando {}: {}",
                       RPC_REGISTRA_EVENTO, riga.get("bando_id"), e)
        return None
    dati = getattr(risposta, "data", risposta)
    if not isinstance(dati, Mapping) or dati.get("id") is None:
        logger.warning("[eventi] {} senza id per il bando {}: {}",
                       RPC_REGISTRA_EVENTO, riga.get("bando_id"), dati)
        return None
    # Senza la chiave `nuovo` non si sa se l'evento e' nato adesso: None, e il
    # chiamante lo lascia in ombra (revisione avversaria del 30/09/2026). Il
    # default «vero» sceglieva proprio il ramo che applica.
    nuovo = dati.get("nuovo")
    return {"id": dati["id"], "nuovo": nuovo if isinstance(nuovo, bool) else None}


def _rpc_disponibile(controllo: Any) -> bool:
    adattatore = controllo
    if adattatore is None:
        from .db import controllo as predefinito
        adattatore = predefinito
    try:
        return bool(adattatore.rpc_disponibile(RPC_REGISTRA_EVENTO))
    except Exception as e:                               # pragma: no cover - ripiego
        logger.warning("[eventi] controllo RPC fallito: {}", e)
        return False


def _rpc_predefinita(nome: str, parametri: dict[str, Any]) -> Any:   # pragma: no cover - I/O
    from .db import get_supabase
    return get_supabase().rpc(nome, parametri).execute()


# --- doppioni nell'interim (§6.2) -------------------------------------------

@dataclass(frozen=True)
class Allineamento:
    """Esito di `allinea_doppioni` per un singolo doppione."""
    bando_id: Any
    colonne: dict[str, Any] = field(default_factory=dict)
    evento: dict[str, Any] = field(default_factory=dict)
    scritto: bool = False
    bloccato: bool = False
    motivo: str = ""


def sorgente_candidatura(
    link_candidatura: str | None, fonte_ufficiale_url: str | None,
) -> tuple[str | None, str]:
    """(link scelto, `link_candidatura_source`) secondo il CHECK gia' in tabella.

    I tre valori sono gli unici ammessi: un valore inventato farebbe fallire
    **tutto** l'UPDATE del doppione, non solo questa colonna.
    """
    if link_candidatura:
        return link_candidatura, SORGENTE_CANDIDATURA_LINK
    if fonte_ufficiale_url:
        return fonte_ufficiale_url, SORGENTE_CANDIDATURA_FONTE
    return None, SORGENTE_CANDIDATURA_ASSENTE


def allinea_doppioni(
    master: Mapping[str, Any],
    doppioni: Sequence[Mapping[str, Any]],
    *,
    attivo: bool = False,
    evento_master: Mapping[str, Any] | None = None,
    scrivi: Callable[[Any, dict[str, Any]], bool] | None = None,
) -> tuple[Allineamento, ...]:
    """Copia stato, date e CTA del master sui doppioni ancora `completed`.

    Fra la fase (b) e la (c) i doppioni sono ancora leggibili in `bando` con il
    loro slug: se il master viene prorogato e il doppione no, il sito mostra due
    verita' diverse sullo stesso bando. Qui il doppione riceve le stesse date,
    e un evento `rettifica` con `riferisce_a` che punta all'evento del master.

    **Lo stesso `check_dates_coherence` del master vale anche qui**: se le date
    copiate violerebbero l'ordine sul doppione (per esempio perche' il doppione
    ha una `data_pubblicazione` posteriore), non si scrive niente e si emette
    un `elaborazione_bloccata` sul doppione. Una copia «quasi giusta» sarebbe
    peggio di nessuna copia.
    """
    apertura = _data(master.get("data_apertura"))
    scadenza = _data(master.get("data_scadenza"))
    stato = master.get("stato_bando")
    link, sorgente = sorgente_candidatura(
        master.get("link_candidatura"), master.get("fonte_ufficiale_url"),
    )

    esiti: list[Allineamento] = []
    for doppione in doppioni:
        identificativo = doppione.get("id")
        if doppione.get("stato_processing") != "completed":
            esiti.append(Allineamento(identificativo, motivo="doppione non completed"))
            continue

        pubblicazione = _data(doppione.get("data_pubblicazione"))
        if not check_dates_coherence(pubblicazione, apertura, scadenza):
            esiti.append(Allineamento(
                identificativo,
                evento={
                    "bando_id": identificativo,
                    "tipo": "elaborazione_bloccata",
                    "origine": "worker",
                    "leggibile": False,
                    "in_aggiornamenti": False,
                    "applicato": False,
                    "valore_dopo": {"motivo": "date del master incoerenti sul doppione"},
                },
                bloccato=True,
                motivo="date del master incoerenti sul doppione",
            ))
            continue

        colonne: dict[str, Any] = {
            "stato_bando": stato,
            "data_apertura": apertura.isoformat() if apertura else None,
            "data_scadenza": scadenza.isoformat() if scadenza else None,
            "link_candidatura": link,
            "link_candidatura_source": sorgente,
        }
        evento = {
            "bando_id": identificativo,
            "tipo": "rettifica",
            "origine": "worker",
            "campo": "contenuto",
            "valore_dopo": {"allineato_al_master": master.get("id")},
            "riferisce_a": (evento_master or {}).get("id"),
            "leggibile": False,
            "in_aggiornamenti": False,
            "applicato": False,
        }
        scritto = False
        if attivo and scrivi is not None:
            try:
                scritto = bool(scrivi(identificativo, colonne))
            except Exception as e:                       # pragma: no cover - ripiego
                logger.warning("[eventi] allineamento del doppione {} fallito: {}", identificativo, e)
                scritto = False
        esiti.append(Allineamento(identificativo, colonne=colonne, evento=evento, scritto=scritto))
    return tuple(esiti)


def _data(valore: Any) -> date_cls | None:
    if isinstance(valore, datetime):
        return valore.date()
    if isinstance(valore, date_cls):
        return valore
    if isinstance(valore, str) and len(valore) >= 10:
        return parse_iso(valore[:10])
    return None


def tabella_transizioni() -> tuple[dict[str, Any], ...]:
    """La tabella di §4 vista dagli eventi: (stato, evento) -> stato.

    E' derivata da `stato_bando.TRANSIZIONI`, non ricopiata: una seconda copia
    diverge al primo cambio, ed e' esattamente il difetto che §4 vieta.
    """
    righe: list[dict[str, Any]] = []
    for transizione in TRANSIZIONI:
        if transizione.get("attore") != "worker":
            continue
        righe.append({
            "da": transizione.get("da"),
            "a": transizione.get("a"),
            "evento": transizione.get("evento"),
        })
    return tuple(righe)


# --- percorso verifica_stato (contratto `bandi-giro-2` §5.5, §5.6, §4, §19.4) --
#
# Il passo verifica-stato legge la pagina ufficiale con un lettore strutturato
# (o col modello) e propone eventi: chiusura, rettifica di data_scadenza,
# data_verificata, apertura. Non passa da `valuta()` del monitor: ha gate
# propri, piu' severi sulla provenienza (G2v, G3v) e con una seconda prova
# diversa, la doppia lettura strutturata ad almeno 60 ore (G7e).

PERCORSO_MONITOR = "monitor"
PERCORSO_VERIFICA = "verifica_stato"

TIPI_VERIFICA: tuple[str, ...] = ("chiusura", "rettifica", "data_verificata", "apertura")
#: I campi che `data_verificata` puo' dichiarare (mai stato, mai pubblicazione).
CAMPI_DATA_VERIFICATA: tuple[str, ...] = ("data_apertura", "ora_apertura", "data_scadenza", "ora_scadenza")
#: Pagine che ammettono eventi: (i) fonte ufficiale, (ii) pagina d'origine,
#: (ii-c) candidato prioritario sullo stesso host, (iii) sorella. La (iv) mai.
PAGINE_CON_EVENTI: tuple[str, ...] = ("i", "ii", "ii-c", "iii")
LIVELLI_TITOLO_AMMESSI: tuple[str, ...] = ("alto", "medio")
ORE_DOPPIA_LETTURA = 60
#: Una chiusura e' una notizia solo se una lettura «aperto» dello stesso
#: estrattore la precede di al massimo tanti giorni, e la data non e' piu'
#: vecchia di tanti giorni (§5.6).
GIORNI_NOTIZIA = 30
GIORNI_RETROATTIVITA = 14
#: Le letture del modello non producono mai questi tipi (§5.5).
TIPI_MAI_DAL_MODELLO: frozenset[str] = frozenset({
    "chiusura", "sospensione", "riapertura", "revoca", "proroga",
})
ESTRATTORE_GENERICO = "generico"
METODO_MODELLO = "modello"
G7_DOPPIA_LETTURA = "doppia_lettura_strutturata"
G7_DOPPIO_MODELLO = "doppio_modello"
#: G6 della chiusura nel percorso verifica (§5.5).
PAROLE_G6_CHIUSURA_VERIFICA = re.compile(r"chius|scadut|conclus", re.I)
#: «Data chiusura 23/6/2026» (Invitalia): nel solo percorso verifica e solo da
#: un lettore strutturato, la chiusura vale come parola della scadenza
#: (decisione del lead, 30/09). Il monitor resta invariato.
PAROLE_G6_SCADENZA_ESTRATTORE = re.compile(r"chius", re.I)
_PESI_VERIFICA: dict[str, float] = {
    "G1": 0.15, "G2v": 0.15, "G3v": 0.10, "G5": 0.10, "G6": 0.10,
    "G7e": 0.20, "G8": 0.05, "G9": 0.05, "G10": 0.10,
}


def _istante_verifica(valore: Any) -> datetime | None:
    """Un istante ISO (anche con le frazioni a 5 cifre di PostgREST) -> aware."""
    if isinstance(valore, datetime):
        letto = valore
    elif isinstance(valore, str) and valore.strip():
        testo = re.sub(r"(\d{2}:\d{2}:\d{2})\.\d+", r"\1", valore.strip()).replace("Z", "+00:00")
        try:
            letto = datetime.fromisoformat(testo)
        except ValueError:
            return None
    else:
        return None
    from datetime import timezone as _tz
    return letto if letto.tzinfo else letto.replace(tzinfo=_tz.utc)


@dataclass(frozen=True)
class LetturaStato:
    """Una lettura di stato: quella di adesso o una voce di `lettura_stato.storia` (§5.8)."""
    at: datetime
    estrattore: str | None
    url: str
    etichetta: str
    stato: str
    #: (ruolo, data) delle date certe lette.
    date: tuple[tuple[str, date_cls], ...] = ()

    @classmethod
    def da(cls, voce: Any) -> "LetturaStato | None":
        """Da una voce della storia: `{at, estrattore, url, etichetta, stato, date}`."""
        if isinstance(voce, LetturaStato):
            return voce
        if not isinstance(voce, Mapping):
            return None
        quando = _istante_verifica(voce.get("at"))
        if quando is None:
            return None
        date_lette: list[tuple[str, date_cls]] = []
        grezze = voce.get("date") or ()
        if isinstance(grezze, Mapping):
            grezze = [{"ruolo": k, "data": v} for k, v in grezze.items()]
        for d in grezze if isinstance(grezze, (list, tuple)) else ():
            ruolo, valore = (d.get("ruolo"), d.get("data")) if isinstance(d, Mapping) else (
                (d[0], d[1]) if isinstance(d, (list, tuple)) and len(d) >= 2 else (None, None))
            giorno = valore if isinstance(valore, date_cls) else parse_iso(str(valore)[:10]) if valore else None
            if ruolo and giorno is not None:
                date_lette.append((str(ruolo), giorno))
        return cls(quando, voce.get("estrattore") or None, str(voce.get("url") or ""),
                   str(voce.get("etichetta") or ""), str(voce.get("stato") or ""), tuple(date_lette))

    def come_voce(self) -> dict[str, Any]:
        """La voce da scrivere in `lettura_stato.storia` (la forma che `da` rilegge)."""
        return {"at": self.at.isoformat(), "estrattore": self.estrattore, "url": self.url,
                "etichetta": self.etichetta, "stato": self.stato,
                "date": [{"ruolo": r, "data": d.isoformat()} for r, d in self.date]}


@dataclass(frozen=True)
class Proposta:
    """Un evento proposto dal passo verifica-stato, prima dei gate."""
    tipo: str
    ramo: str                                  # 'I' («in apertura») | 'A' («aperto» senza scadenza)
    citazione: str
    url_prova: str
    metodo: str                                # 'estrattore:<chiave>' | 'modello'
    campo: str | None = None
    valore_dopo: Mapping[str, Any] = field(default_factory=dict)
    data_evento: date_cls | None = None
    etichetta: str = ""
    in_aggiornamenti: bool = False

    @property
    def estrattore(self) -> str | None:
        return self.metodo.split(":", 1)[1] if self.metodo.startswith("estrattore:") else None

    @property
    def da_modello(self) -> bool:
        return self.metodo == METODO_MODELLO

    @property
    def data(self) -> date_cls | None:
        """La data che la proposta dichiara (nuova scadenza o data verificata)."""
        if self.campo in ("data_apertura", "data_scadenza"):
            valore = self.valore_dopo.get(self.campo)
            return valore if isinstance(valore, date_cls) else parse_iso(str(valore)) if valore else None
        return self.data_evento


@dataclass(frozen=True)
class ContestoVerifica:
    """Quello che i gate del percorso verifica devono sapere. Nessun accesso esterno."""
    bando_id: int | None = None
    #: Lo stato di `bando` riletto dal DB subito prima (G9).
    stato: str | None = None
    data_apertura: date_cls | None = None
    data_scadenza: date_cls | None = None
    data_pubblicazione: date_cls | None = None
    apertura_verificata: bool = False
    scadenza_verificata: bool = False
    #: 'i' | 'ii' | 'ii-c' | 'iii' | 'iv' | 'illeggibile' (§5.3, §19.4).
    pagina_tipo: str = "illeggibile"
    url_finale: str = ""
    #: Il testo visibile della pagina letta (`scarico.testo_da_html`).
    testo_pagina: str = ""
    #: 'alto' | 'medio' | 'basso' dalla somiglianza del titolo (G3v), calcolata dal passo.
    livello_titolo: str | None = None
    lettura: LetturaStato | None = None
    storia: tuple[LetturaStato, ...] = ()
    eventi_recenti: tuple[Mapping[str, Any], ...] = ()
    seconda_opinione: Any = None
    prove: tuple[Prova, ...] = ()
    tabella_domini: Any = None
    adesso: datetime | None = None
    #: Le altre proposte dello stesso bando in questo giro (G5-dv).
    proposte_insieme: tuple["Proposta", ...] = ()

    @property
    def giorno(self) -> date_cls:
        if self.adesso is None:
            return oggi_roma()
        from .stato_bando import adesso_roma
        return adesso_roma(self.adesso).date()


def _evento_equivalente(proposta: Proposta) -> Evento:
    """L'`Evento` del monitor con la stessa semantica, per riusare G5, G7 e G8."""
    if proposta.tipo in ("rettifica", "data_verificata") and proposta.campo in ("data_apertura", "data_scadenza"):
        data = proposta.data
        return Evento("rettifica", proposta.citazione, proposta.url_prova, campo=proposta.campo,
                      valore=data.isoformat() if data else None)
    if proposta.tipo == "chiusura":
        return Evento("chiusura", proposta.citazione, proposta.url_prova)
    return Evento(proposta.tipo, proposta.citazione, proposta.url_prova, campo=proposta.campo)


def _contesto_monitor(ctx: ContestoVerifica) -> Contesto:
    return Contesto(
        bando_id=ctx.bando_id, stato_bando=ctx.stato, data_apertura=ctx.data_apertura,
        data_scadenza=ctx.data_scadenza, data_pubblicazione=ctx.data_pubblicazione,
        pagine=(Pagina(ctx.url_finale, ctx.testo_pagina),), eventi_recenti=ctx.eventi_recenti,
        prove=ctx.prove, seconda_opinione=ctx.seconda_opinione,
        tabella_domini=ctx.tabella_domini, oggi=ctx.giorno,
    )


def gv1_citazione(proposta: Proposta, ctx: ContestoVerifica) -> tuple[bool, str]:
    """G1: la citazione sta nel testo della pagina letta."""
    if not norm_cit(proposta.citazione):
        return False, "citazione vuota"
    if citazione_in(proposta.citazione, ctx.testo_pagina):
        return True, ""
    return False, "citazione non presente nella pagina letta"


def gv2_pagina(proposta: Proposta, ctx: ContestoVerifica) -> tuple[bool, str]:
    """G2v: pagina (i), (ii), (ii-c) o (iii), su un dominio verificabile e non aggregatore."""
    if ctx.pagina_tipo not in PAGINE_CON_EVENTI:
        return False, f"pagina di tipo {ctx.pagina_tipo!r}: non ammette eventi"
    tabella = ctx.tabella_domini if ctx.tabella_domini is not None else TABELLA_SEED
    host = dominio_di(ctx.url_finale)
    if not host or e_aggregatore(host, tabella):
        return False, f"host {host!r} aggregatore o illeggibile"
    if not verificabile(host, tabella):
        return False, f"host {host!r} non verificabile"
    return True, ""


def gv3_titolo(proposta: Proposta, ctx: ContestoVerifica) -> tuple[bool, str]:
    """G3v: il titolo della pagina somiglia al bando almeno al livello «medio»."""
    if ctx.livello_titolo in LIVELLI_TITOLO_AMMESSI:
        return True, ""
    return False, f"titolo {ctx.livello_titolo or 'non misurato'}: serve almeno medio"


def gv5_direzione(proposta: Proposta, ctx: ContestoVerifica) -> tuple[bool, str]:
    """G5: direzione con la logica del monitor, piu' le regole di `data_verificata`."""
    if proposta.tipo not in TIPI_VERIFICA:
        return False, f"tipo {proposta.tipo!r} non previsto dal percorso verifica"
    oggi = ctx.giorno
    if proposta.tipo == "data_verificata":
        if proposta.campo not in CAMPI_DATA_VERIFICATA:
            return False, f"data_verificata su un campo non ammesso: {proposta.campo!r}"
        gia = (ctx.apertura_verificata if proposta.campo in ("data_apertura", "ora_apertura")
               else ctx.scadenza_verificata)
        if gia:
            return False, f"{proposta.campo} gia' verificata: non si sovrascrive"
        # G5-dv: un'apertura passata vale solo insieme a una scadenza verificata.
        if (proposta.campo == "data_apertura" and proposta.data is not None and proposta.data < oggi
                and not ctx.scadenza_verificata
                and not any(p.tipo == "data_verificata" and p.campo == "data_scadenza"
                            for p in ctx.proposte_insieme)):
            return False, "apertura passata senza una scadenza verificata"
    if proposta.tipo == "chiusura" and proposta.data_evento is not None and proposta.data_evento > oggi:
        return False, f"chiusura datata nel futuro ({proposta.data_evento} > {oggi})"
    if proposta.tipo == "rettifica" and proposta.campo in ("data_apertura", "data_scadenza"):
        return g5_direzione(_evento_equivalente(proposta), _contesto_monitor(ctx))
    if proposta.tipo == "data_verificata" and proposta.campo in ("data_apertura", "data_scadenza"):
        # Una data verificata non e' un differimento: niente regole di
        # direzione del monitor, solo la coerenza delle date risultanti.
        apertura, scadenza = _date_risultanti(_evento_equivalente(proposta), _contesto_monitor(ctx))
        altre = {p.campo: p.data for p in ctx.proposte_insieme if p.tipo == "data_verificata"}
        apertura = altre.get("data_apertura") or apertura
        scadenza = altre.get("data_scadenza") or scadenza
        if not check_dates_coherence(ctx.data_pubblicazione, apertura, scadenza):
            return False, "le date risultanti violano pubblicazione <= apertura <= scadenza"
    return True, ""


def gv6_parola(proposta: Proposta, ctx: ContestoVerifica) -> tuple[bool, str]:
    """G6: la parola che il tipo richiede, nella citazione."""
    citazione = norm_cit(proposta.citazione)
    if proposta.tipo == "chiusura":
        modello = PAROLE_G6_CHIUSURA_VERIFICA
    elif proposta.tipo == "apertura":
        modello = PAROLE_G6["apertura"]
    elif proposta.campo in ("data_apertura", "ora_apertura"):
        modello = PAROLE_G6["rettifica:data_apertura"]
    else:
        modello = PAROLE_G6["rettifica:data_scadenza"]
        if proposta.estrattore and PAROLE_G6_SCADENZA_ESTRATTORE.search(citazione):
            return True, ""
    if modello.search(citazione):
        return True, ""
    return False, f"citazione senza parola chiave per {proposta.tipo}:{proposta.campo or ''}"


def _stessa_etichetta(a: str, b: str) -> bool:
    return norm_cit(a) == norm_cit(b)


def gv7_seconda_prova(proposta: Proposta, ctx: ContestoVerifica) -> tuple[bool, str]:
    """G7e: doppia lettura strutturata; per il modello, G7 doppio invariato."""
    if proposta.da_modello:
        if proposta.tipo in TIPI_MAI_DAL_MODELLO:
            return False, f"il modello non produce mai {proposta.tipo}"
        return g7_seconda_prova(_evento_equivalente(proposta), _contesto_monitor(ctx), doppia=True)
    estrattore = proposta.estrattore
    if not estrattore:
        return False, f"metodo sconosciuto: {proposta.metodo!r}"
    if estrattore == ESTRATTORE_GENERICO:
        return False, "il lettore generico non produce eventi"
    attuale = ctx.lettura
    if attuale is None or attuale.estrattore != estrattore:
        return False, "manca la lettura attuale dello stesso estrattore"
    url_attuale = impronte.normalizza_url(attuale.url)
    data = proposta.data if proposta.campo in ("data_apertura", "data_scadenza") else None
    stesso_estrattore = [l for l in ctx.storia if l.estrattore == estrattore and l.at < attuale.at]
    precedenti = sorted((l for l in stesso_estrattore if impronte.normalizza_url(l.url) == url_attuale),
                        key=lambda l: l.at, reverse=True)
    if not precedenti:
        if stesso_estrattore:
            return False, "nessuna lettura precedente concorde (url diverso)"
        return False, "una sola lettura strutturata: serve la seconda"
    # Si risale dall'ULTIMA lettura (revisione del #74): la prima discordante
    # interrompe la catena. Con Chiuso, Aperto, Chiuso la chiusura non passa
    # finche' due letture concordi di fila non distano almeno 60 ore.
    for precedente in precedenti:
        if not _stessa_etichetta(precedente.etichetta, attuale.etichetta):
            return False, "nessuna lettura precedente concorde (etichetta diversa)"
        if data is not None and data not in {d for _, d in precedente.date}:
            return False, "nessuna lettura precedente concorde (data diversa)"
        if attuale.at - precedente.at >= timedelta(hours=ORE_DOPPIA_LETTURA):
            return True, ""
    return False, f"nessuna lettura precedente concorde (letture a meno di {ORE_DOPPIA_LETTURA} h)"


def gv8_dedup(proposta: Proposta, ctx: ContestoVerifica) -> tuple[bool, str]:
    """G8: nessun evento uguale (stesso TIPO vero, campo e valore) negli ultimi 30 giorni.

    Col tipo vero, non con quello equivalente: una `data_verificata` gia'
    registrata non e' una `rettifica`, e il confronto per tipo la mancherebbe.
    """
    equivalente = _evento_equivalente(proposta)
    evento = Evento(proposta.tipo, proposta.citazione, proposta.url_prova,
                    campo=equivalente.campo, valore=equivalente.valore)
    # La finestra si misura su quando l'evento e' stato registrato, non sulla
    # sua data_evento (decisione del lead, nota di #76).
    return g8_dedup(evento, _contesto_monitor(ctx), giorno_di=_giorno_registrato)


def gv9_transizione(proposta: Proposta, ctx: ContestoVerifica) -> tuple[bool, str]:
    """G9: la transizione e' nella lista bianca, dallo stato riletto dal DB."""
    nuovo = transizione_evento(ctx.stato, _evento_equivalente(proposta), percorso=PERCORSO_VERIFICA)
    if nuovo is None or nuovo == ctx.stato:
        return True, ""
    if transizione_ammessa(ctx.stato, nuovo, "worker"):
        return True, ""
    return False, f"transizione {ctx.stato!r} -> {nuovo!r} non prevista dalla lista bianca"


def gv10_presunta(proposta: Proposta, ctx: ContestoVerifica) -> tuple[bool, str]:
    """G10: nessuna data presunta."""
    from .date_validation import e_presunta
    if e_presunta(proposta.citazione):
        return False, "data presunta nella citazione"
    return True, ""


def valuta_verifica(proposta: Proposta, ctx: ContestoVerifica) -> Giudizio:
    """I gate del percorso verifica_stato (§5.5). Non scrive niente.

    Una proposta e' ammessa solo se passa TUTTI i gate. `gate` del giudizio
    vale «G2v»; il formato da registrare in `p_gate` lo da' `gate_verifica`.
    """
    controlli: list[tuple[str, Callable[[], tuple[bool, str]]]] = [
        ("G1", lambda: gv1_citazione(proposta, ctx)),
        ("G2v", lambda: gv2_pagina(proposta, ctx)),
        ("G3v", lambda: gv3_titolo(proposta, ctx)),
        ("G5", lambda: gv5_direzione(proposta, ctx)),
        ("G6", lambda: gv6_parola(proposta, ctx)),
        ("G7e", lambda: gv7_seconda_prova(proposta, ctx)),
        ("G8", lambda: gv8_dedup(proposta, ctx)),
        ("G9", lambda: gv9_transizione(proposta, ctx)),
        ("G10", lambda: gv10_presunta(proposta, ctx)),
    ]
    superati: list[str] = []
    falliti: list[tuple[str, str]] = []
    for nome, prova in controlli:
        ok, motivo = prova()
        if ok:
            superati.append(nome)
        else:
            falliti.append((nome, motivo))
    ammesso = not falliti
    nuovo = (transizione_evento(ctx.stato, _evento_equivalente(proposta), percorso=PERCORSO_VERIFICA)
             if ammesso else None)
    return Giudizio(
        ammesso=ammesso, gate="G2v", superati=tuple(superati), falliti=tuple(falliti),
        confidenza=round(min(1.0, sum(_PESI_VERIFICA.get(n, 0.0) for n in superati)), 4),
        leggibile=ammesso, nuovo_stato=nuovo if nuovo != ctx.stato else None,
    )


def gate_verifica(giudizio: Giudizio, proposta: Proposta) -> dict[str, Any]:
    """L'esito dei gate nel formato di `p_gate` (§5.5)."""
    return {
        "percorso": PERCORSO_VERIFICA,
        "superati": list(giudizio.superati),
        "falliti": [{"gate": g, "motivo": m} for g, m in giudizio.falliti],
        "g7": G7_DOPPIO_MODELLO if proposta.da_modello else G7_DOPPIA_LETTURA,
    }


# --- proposte (§5.6) -----------------------------------------------------------

_FINE_FRASE_VERIFICA_RE = re.compile(r"(?<=[.;!?])\s+(?=[A-ZÀ-ÖØ-Þ«\"“(])|\n+")


_CONTESTO_CITAZIONE = 200


def _citazione_della_data(testo: str, data: date_cls) -> str:
    """Il pezzo di frase che finisce con `data`, per il G1 (o "").

    Al massimo 200 caratteri prima della data, da un inizio di parola: una
    frase di pagina puo' essere lunghissima, e tagliarla da capo lascerebbe
    fuori proprio la data. Vince la citazione piu' corta; e' sempre una
    sottostringa del testo.
    """
    migliore = ""
    for frase in _FINE_FRASE_VERIFICA_RE.split(testo or ""):
        frase = frase.strip()
        for trovata in estrai_date_con_ruolo(frase):
            if trovata.data != data:
                continue
            inizio = max(0, trovata.inizio - _CONTESTO_CITAZIONE)
            if inizio > 0:
                spazio = frase.find(" ", inizio)
                inizio = spazio + 1 if 0 <= spazio < trovata.inizio else inizio
            pezzo = frase[inizio:trovata.fine].strip()
            if pezzo and (not migliore or len(pezzo) < len(migliore)):
                migliore = pezzo
    return migliore


def _e_notizia(ctx: ContestoVerifica, estrattore: str | None, data: date_cls | None) -> bool:
    """`in_aggiornamenti`: vero solo per una notizia nuova (§5.6).

    Servono entrambe: una lettura strutturata «aperto» (o «in apertura») dello
    stesso estrattore al massimo 30 giorni prima della PRIMA lettura di
    chiusura, e una data (se c'e') non piu' vecchia di 14 giorni. Il resto e'
    una correzione: leggibile per lo stato, fuori dal box Aggiornamenti.
    """
    oggi = ctx.giorno
    if data is not None and data < oggi - timedelta(days=GIORNI_RETROATTIVITA):
        return False
    tutte = [*ctx.storia, ctx.lettura] if ctx.lettura is not None else list(ctx.storia)
    letture = sorted((l for l in tutte if l.estrattore == estrattore), key=lambda l: l.at)
    if not letture or letture[-1].stato != "chiuso":
        return False
    prima_chiusura = letture[-1]
    for lettura in reversed(letture[:-1]):
        if lettura.stato != "chiuso":
            break
        prima_chiusura = lettura
    for lettura in letture:
        if (lettura.stato in ("aperto", "in_apertura")
                and lettura.at < prima_chiusura.at
                and prima_chiusura.at - lettura.at <= timedelta(days=GIORNI_NOTIZIA)):
            return True
    return False


def _valore_data(campo: str, data: date_cls, ora: Any) -> dict[str, Any]:
    valore: dict[str, Any] = {campo: data.isoformat()}
    if ora is not None:
        valore["ora_" + campo.split("_", 1)[1]] = ora.strftime("%H:%M") if hasattr(ora, "strftime") else str(ora)
    return valore


def proposte_verifica(ramo: str, lettura: Any, ctx: ContestoVerifica) -> list[Proposta]:
    """Le proposte di §5.6 da una `etichette_stato.Lettura` (letta per attributi).

    Ramo I («in apertura»): (a) date certe → `data_verificata`; (b) «aperto»
    con una scadenza futura certa → `data_verificata` della scadenza e poi
    `apertura`; (c) etichetta che puo' chiudere, senza termine futuro e senza
    una scadenza da verificare → `chiusura` (riga 24). Ramo A («aperto» senza
    scadenza): (e) etichetta che puo' chiudere senza termine futuro →
    `chiusura` con la data letta se <= oggi; altrimenti (d) un termine certo →
    `rettifica` di data_scadenza. Il generico, le letture solo segnale senza
    date, «uscito» e «non decisiva» non propongono niente.
    """
    if lettura is None or getattr(lettura, "estrattore", None) in (None, ESTRATTORE_GENERICO):
        return []
    oggi = ctx.giorno
    metodo = f"estrattore:{lettura.estrattore}"
    stato = getattr(lettura, "stato", "")
    etichetta = getattr(lettura, "etichetta", "") or ""
    citazione_stato = getattr(lettura, "citazione_stato", "") or etichetta
    termine = getattr(lettura, "termine_finale", None)
    comune = {"url_prova": ctx.url_finale, "metodo": metodo, "etichetta": etichetta, "ramo": ramo}

    def citazione_di(data: date_cls, citazione: str) -> str:
        return citazione if citazione_in(citazione, ctx.testo_pagina) else _citazione_della_data(ctx.testo_pagina, data)

    # Le date certe della lettura: il termine finale come scadenza, le altre dal ruolo.
    certe: dict[str, tuple[date_cls, Any, str]] = {}
    if termine is not None:
        certe["data_scadenza"] = (termine.data, termine.ora, citazione_di(termine.data, termine.citazione))
    for voce in getattr(lettura, "date", ()) or ():
        if getattr(voce, "presunta", False):
            continue
        campo = {"scadenza": "data_scadenza", "apertura": "data_apertura"}.get(getattr(voce, "ruolo", ""))
        if campo and campo not in certe:
            certe[campo] = (voce.data, voce.ora, citazione_di(voce.data, voce.citazione))
    scadenza = certe.get("data_scadenza")
    termine_futuro = scadenza is not None and scadenza[0] >= oggi
    puo_chiudere = bool(getattr(lettura, "puo_chiudere", False))
    proposte: list[Proposta] = []

    if ramo == "I":
        for campo in ("data_scadenza", "data_apertura"):
            if campo not in certe:
                continue
            gia = ctx.scadenza_verificata if campo == "data_scadenza" else ctx.apertura_verificata
            if gia:
                continue
            data, ora, citazione = certe[campo]
            proposte.append(Proposta("data_verificata", campo=campo, valore_dopo=_valore_data(campo, data, ora),
                                     citazione=citazione, in_aggiornamenti=False, **comune))
        if stato == "aperto" and termine_futuro:
            proposte.append(Proposta("apertura", citazione=citazione_stato, in_aggiornamenti=True,
                                     valore_dopo={"stato_bando": "aperto"}, **comune))
        elif (stato == "chiuso" and puo_chiudere and not termine_futuro
              and not any(p.campo == "data_scadenza" for p in proposte)):
            data = termine.data if termine is not None and termine.data <= oggi else None
            proposte.append(Proposta("chiusura", citazione=citazione_stato, data_evento=data,
                                     valore_dopo={"stato_bando": "chiuso"},
                                     in_aggiornamenti=_e_notizia(ctx, lettura.estrattore, data), **comune))
        return proposte

    if ramo == "A":
        if stato == "chiuso" and puo_chiudere and not termine_futuro:
            data = termine.data if termine is not None and termine.data <= oggi else None
            return [Proposta("chiusura", citazione=citazione_stato, data_evento=data,
                             valore_dopo={"stato_bando": "chiuso"},
                             in_aggiornamenti=_e_notizia(ctx, lettura.estrattore, data), **comune)]
        if scadenza is not None:
            data, ora, citazione = scadenza
            return [Proposta("rettifica", campo="data_scadenza", valore_dopo=_valore_data("data_scadenza", data, ora),
                             citazione=citazione, in_aggiornamenti=_e_notizia(ctx, lettura.estrattore, data),
                             **comune)]
    return []


def riga_verifica(
    proposta: Proposta, ctx: ContestoVerifica, giudizio: Giudizio, *, modalita: str = MODALITA_OMBRA,
) -> dict[str, Any]:
    """La riga di `bando_evento` per una proposta del percorso verifica.

    Stessa forma di `riga_evento`: `registra_via_rpc` la accetta cosi'. In
    ombra nessun evento e' leggibile; `applicato` resta falso, perche' l'evento
    si applica dopo, con `bando_applica_evento` (§5.6).
    """
    attivo = modalita == MODALITA_ATTIVO
    leggibile = giudizio.ammesso and attivo
    valore_prima: dict[str, Any] = {}
    if proposta.campo in ("data_apertura", "ora_apertura"):
        valore_prima["data_apertura"] = ctx.data_apertura.isoformat() if ctx.data_apertura else None
    elif proposta.campo in ("data_scadenza", "ora_scadenza"):
        valore_prima["data_scadenza"] = ctx.data_scadenza.isoformat() if ctx.data_scadenza else None
    if proposta.tipo in ("chiusura", "apertura"):
        valore_prima["stato_bando"] = ctx.stato
    if proposta.tipo == "chiusura":
        data_evento = proposta.data_evento.isoformat() if proposta.data_evento else None
    else:
        data_evento = (proposta.data_evento or ctx.giorno).isoformat()
    return {
        "bando_id": ctx.bando_id,
        "tipo": proposta.tipo,
        "origine": "worker",
        "campo": proposta.campo,
        "valore_prima": valore_prima,
        "valore_dopo": dict(proposta.valore_dopo),
        "data_evento": data_evento,
        "citazione": proposta.citazione[:300],
        "url_prova": proposta.url_prova,
        "verificato": giudizio.ammesso,
        "leggibile": leggibile,
        "in_aggiornamenti": leggibile and proposta.in_aggiornamenti,
        "applicato": False,
        "confidenza": int(round(max(0.0, min(1.0, giudizio.confidenza)) * 100)),
        "gate": gate_verifica(giudizio, proposta),
        "metodo": proposta.metodo,
    }


__all__ = [
    "Allineamento", "Applicazione", "CAMPI_RETTIFICA", "Contesto", "Evento",
    "FINESTRA_DEDUP_GIORNI", "Giudizio", "ISTRUZIONI_CLASSIFICATORE",
    "MARGINE_ATTO_GIORNI", "MODALITA_ATTIVO", "MODALITA_OMBRA", "PAROLE_G6", "PARAMETRI_REGISTRA_EVENTO",
    "PESI_GATE", "Pagina", "parametri_registra_evento",
    "PROVE_G7_AMMESSE", "PROVE_G7_VIETATE", "Prova", "QUOTA_TOKEN_G2",
    "RPC_REGISTRA_EVENTO", "SORGENTE_CANDIDATURA_ASSENTE",
    "SORGENTE_CANDIDATURA_FONTE", "SORGENTE_CANDIDATURA_LINK",
    "STRUMENTO_SALVA_EVENTI", "TIPI_CON_TRANSIZIONE", "TIPI_DA_LINK",
    "TIPI_INTERNI", "TIPI_LEGGIBILI", "TIPI_PROPONIBILI", "allinea_doppioni",
    "applica", "colonne_da_evento", "evento_da", "g1_citazione", "g2_diff",
    "g2_primo", "g3_ruolo", "g4_prova", "g5_direzione", "g6_parola",
    "g7_seconda_prova", "g8_dedup", "g9_transizione", "leggi_eventi",
    "prompt_utente", "riga_evento", "sorgente_candidatura",
    "stato_solo_proposto", "tabella_transizioni", "transizione_evento",
    "usa_g2_primo", "valuta",
    # percorso verifica_stato
    "CAMPI_DATA_VERIFICATA", "ContestoVerifica", "LetturaStato", "ORE_DOPPIA_LETTURA",
    "PAGINE_CON_EVENTI", "PERCORSO_MONITOR", "PERCORSO_VERIFICA", "Proposta", "TIPI_VERIFICA",
    "gate_verifica", "proposte_verifica", "riga_verifica", "valuta_verifica",
]
