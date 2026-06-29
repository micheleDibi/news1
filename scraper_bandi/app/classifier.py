"""Classificazione fonti: mapping `categoria_programma_id` + `tipologia_programma_id`
+ `tipo_link`.

Mapping hardcoded basato sui valori che l'utente ha fornito per le tabelle
catalogo (vedi README). Se la pagina sorgente cambia un nome, il match per
nome esatto fallisce e l'id resta None (log WARNING dal chiamante).
"""
from __future__ import annotations

import re
import unicodedata


# --- categoria_programma ----------------------------------------------------

CATEGORIA_REGIONALE = 1                # "Programma Regionale"
CATEGORIA_NAZIONALE = 2                # "Programma Nazionale"
CATEGORIA_CTE_TITOLARITA = 3           # "Programma CTE a Titolarità Italiana"
CATEGORIA_CTE_PARTECIPAZIONE = 4       # "Programma CTE a Partecipazione Italiana"


# Le 20 regioni + 2 province autonome riconosciute come "Programma Regionale".
# Normalizzate in casefold ASCII per match robusto.
_REGIONI_ITALIA: frozenset[str] = frozenset({
    "abruzzo", "basilicata", "calabria", "campania", "emilia-romagna",
    "emilia romagna", "friuli-venezia giulia", "friuli venezia giulia",
    "lazio", "liguria", "lombardia", "marche", "molise", "piemonte",
    "puglia", "sardegna", "sicilia", "toscana", "umbria",
    "valle d'aosta", "valle daosta", "veneto",
    "provincia autonoma di bolzano", "bolzano",
    "provincia autonoma di trento", "trento",
})


# Marker testuali per riconoscere i 4 macro-blocchi nella pagina.
_HEADER_REGIONALE_MARKERS = ("programmi regionali",)
_HEADER_NAZIONALE_MARKERS = ("programmi nazionali",)
_HEADER_CTE_TITOLARITA_MARKERS = ("a titolarita italiana", "a titolarita' italiana")
_HEADER_CTE_PARTECIPAZIONE_MARKERS = ("a partecipazione italiana",)


def normalize(text: str) -> str:
    """NFKD + strip accents + casefold + collapse whitespace."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", no_accents.strip()).casefold()


def categoria_from_section_header(heading_text: str) -> int | None:
    """Da un heading testuale (es. 'Programmi Regionali', 'Programmi di
    Cooperazione Territoriale Europea a titolarità italiana') ritorna l'id
    della categoria_programma, o None se non riconosciuto."""
    n = normalize(heading_text)
    if not n:
        return None
    if any(m in n for m in _HEADER_CTE_TITOLARITA_MARKERS):
        return CATEGORIA_CTE_TITOLARITA
    if any(m in n for m in _HEADER_CTE_PARTECIPAZIONE_MARKERS):
        return CATEGORIA_CTE_PARTECIPAZIONE
    if any(m in n for m in _HEADER_NAZIONALE_MARKERS):
        return CATEGORIA_NAZIONALE
    if any(m in n for m in _HEADER_REGIONALE_MARKERS):
        return CATEGORIA_REGIONALE
    return None


def categoria_from_region_heading(heading_text: str) -> int | None:
    """Se il `<h3>` contiene il nome di una regione italiana, e' un Programma
    Regionale (id=1). Utile quando il macro-blocco non e' stato identificato."""
    n = normalize(heading_text)
    for regione in _REGIONI_ITALIA:
        if regione in n:
            return CATEGORIA_REGIONALE
    return None


# --- tipologia_programma ---------------------------------------------------

# L'utente ha fornito questi ID dalla tabella `tipologia_programma`.
# Mapping per chiave NORMALIZZATA (casefold + no accents + no whitespace
# eccessivi) del nome del programma estratto dalla pagina.
#
# NOTA typo DB: id=2 e' "PR FRE+" ma sulla pagina si chiama "PR FSE+";
# matchiamo l'input pagina (corretto) sull'id 2.
TIPOLOGIA_MAP: dict[str, int] = {
    "pr fesr": 1,
    "pr fse+": 2,           # typo DB ("PR FRE+") risolto qui
    "pr fesr e fse+": 3,
    "pn fesr e fse+": 4,
    "pn fesr": 5,
    "pn fse+": 6,
    "pn jtf": 7,
    "pn just transition fund": 7,
    "interreg fesr": 8,
    "interreg ipa": 9,
    "interreg next": 10,
}


def tipologia_from_program_name(program_name: str) -> int | None:
    """Match esatto (normalizzato) del nome del programma estratto dal `<li>`.

    Esempi di input riconosciuti:
        "PR FESR", "PR FSE+", "PN Just Transition Fund",
        "INTERREG FESR", "INTERREG NEXT MED" (matcha "interreg next").

    Se non c'e' match esatto, fa fallback "startswith" sulle chiavi piu'
    lunghe (per gestire "INTERREG NEXT MED" -> id=10).
    """
    n = normalize(program_name)
    if not n:
        return None

    # Match esatto
    if n in TIPOLOGIA_MAP:
        return TIPOLOGIA_MAP[n]

    # Fallback: startswith (ordina chiavi dalla piu' lunga alla piu' corta
    # per evitare collisioni tipo "pn fesr" vs "pn fesr e fse+").
    for key in sorted(TIPOLOGIA_MAP, key=len, reverse=True):
        if n.startswith(key):
            return TIPOLOGIA_MAP[key]

    return None


# --- tipo_link --------------------------------------------------------------

def tipo_link_from_anchor_text(text: str) -> str | None:
    """Restituisce 'Opportunità' o 'Preavviso' in base al testo del link `<a>`."""
    n = normalize(text)
    if not n:
        return None
    if "opportunita" in n:
        return "Opportunità"
    if "preavvis" in n:  # "preavviso" o "preavvisi"
        return "Preavviso"
    return None
