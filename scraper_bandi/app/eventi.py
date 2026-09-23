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
from datetime import date as date_cls, datetime
from typing import Any, Callable, Mapping, Sequence

from .date_validation import (
    check_dates_coherence,
    estrai_date_con_ruolo,
    norm_cit,
    parse_iso,
    ruolo_compatibile,
)
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
    righe += ["", "DIFF", testo or "(nessun diff: e' il primo controllo di questa pagina)"]
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


def g1_citazione(evento: Evento, ctx: Contesto) -> tuple[bool, str]:
    """La citazione e' sottostringa di una pagina scaricata in questo controllo."""
    citazione = norm_cit(evento.citazione)
    if not citazione:
        return False, "citazione vuota"
    for pagina in ctx.pagine:
        if citazione in norm_cit(pagina.testo):
            return True, ""
    return False, "citazione non presente in nessuna pagina scaricata"


def g2_diff(evento: Evento, ctx: Contesto) -> tuple[bool, str]:
    """La citazione interseca le righe AGGIUNTE del diff (>= 60 % dei token).

    Per graduatoria/esito/faq/nuovo_allegato basta un link nuovo: quegli eventi
    si annunciano con un documento, non sempre con una frase.
    """
    diff = ctx.diff
    if diff is None:
        return False, "nessun diff disponibile"
    if evento.tipo in TIPI_DA_LINK and tuple(getattr(diff, "link_aggiunti", ()) or ()):
        return True, ""
    aggiunte = " ".join(getattr(diff, "righe_aggiunte", ()) or ())
    if not aggiunte.strip():
        return False, "nessuna riga aggiunta nel diff"
    token_citazione = _token(evento.citazione)
    if not token_citazione:
        return False, "citazione senza token"
    token_aggiunte = set(_token(aggiunte))
    comuni = sum(1 for t in token_citazione if t in token_aggiunte)
    quota = comuni / len(token_citazione)
    if quota < QUOTA_TOKEN_G2:
        return False, f"citazione fuori dalle righe aggiunte ({quota:.0%} < {QUOTA_TOKEN_G2:.0%})"
    return True, ""


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
            return True, ""
        data = evento.data_evento
    ruolo = _ruolo_atteso(evento)
    trovate = estrai_date_con_ruolo(evento.citazione)
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
    if norm_cit(evento.citazione) not in norm_cit(pagina.testo):
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


def g8_dedup(evento: Evento, ctx: Contesto, *, giorni: int = FINESTRA_DEDUP_GIORNI) -> tuple[bool, str]:
    """Nessun evento uguale negli ultimi 30 giorni (§6.2 G8, §16.2 M6).

    «Uguale» e' (tipo, campo, valore): la stessa proroga vista in due giri
    consecutivi e' un solo fatto, e due righe leggibili nel box «Aggiornamenti»
    sarebbero due volte la stessa notizia.
    """
    oggi = ctx.giorno
    for passato in ctx.eventi_recenti:
        if str(passato.get("tipo") or "") != evento.tipo:
            continue
        if (passato.get("campo") or None) != (evento.campo or None):
            continue
        if _valore_evento(passato) != (evento.valore or None):
            continue
        quando = _giorno_evento(passato)
        if quando is None:
            continue
        if 0 <= (oggi - quando).days <= giorni:
            return False, f"evento identico gia' registrato il {quando.isoformat()}"
    return True, ""


def _valore_evento(riga: Mapping[str, Any]) -> str | None:
    dopo = riga.get("valore_dopo")
    if isinstance(dopo, Mapping):
        for nome in ("valore", "data", "stato_proposto"):
            if riga.get("campo") and riga.get("campo") in dopo:
                return str(dopo[riga["campo"]])
            if nome in dopo:
                return str(dopo[nome])
    valore = riga.get("valore")
    return str(valore) if valore is not None else None


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


def transizione_evento(stato: str | None, evento: Evento) -> str | None:
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
        return "chiuso" if stato == "aperto" else None
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


def riga_evento(evento: Evento, ctx: Contesto, giudizio: Giudizio) -> dict[str, Any]:
    """Payload di `bando_evento` per questo evento."""
    proposto = stato_solo_proposto(evento, ctx)
    ombra = ctx.modalita != MODALITA_ATTIVO
    leggibile = giudizio.ammesso and not ombra
    valore_dopo: dict[str, Any] = {}
    if evento.valore:
        valore_dopo[evento.campo or "valore"] = evento.valore
    if proposto and giudizio.nuovo_stato:
        valore_dopo["stato_proposto"] = giudizio.nuovo_stato
    elif giudizio.nuovo_stato:
        valore_dopo["stato_bando"] = giudizio.nuovo_stato

    valore_prima: dict[str, Any] = {}
    if evento.campo == "data_apertura":
        valore_prima["data_apertura"] = ctx.data_apertura.isoformat() if ctx.data_apertura else None
    elif evento.campo == "data_scadenza" or evento.tipo == "proroga":
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
        "data_evento": (evento.data_evento or ctx.giorno).isoformat(),
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
        "confidenza": giudizio.confidenza,
        "gate": giudizio.gate,
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
        (rpc or _rpc_predefinita)(RPC_REGISTRA_EVENTO, parametri)
    except Exception as e:
        logger.warning("[eventi] {} fallita per il bando {}: {}", RPC_REGISTRA_EVENTO, ctx.bando_id, e)
        return Applicazione(riga=riga, colonne=colonne, applicato=False, scritto=False,
                            motivo=f"rpc fallita: {e}", giudizio=verdetto)

    return Applicazione(riga=riga, colonne=colonne,
                        applicato=bool(riga.get("applicato")), scritto=True,
                        motivo="", giudizio=verdetto)


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


__all__ = [
    "Allineamento", "Applicazione", "CAMPI_RETTIFICA", "Contesto", "Evento",
    "FINESTRA_DEDUP_GIORNI", "Giudizio", "ISTRUZIONI_CLASSIFICATORE",
    "MODALITA_ATTIVO", "MODALITA_OMBRA", "PAROLE_G6", "PARAMETRI_REGISTRA_EVENTO",
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
]
