"""Orologio, vocabolario e macchina a stati dei bandi (piano §4 e §13.3).

Prima di questo modulo esistevano tre definizioni di «oggi» (fix 8.a.15):
`date.today()` in date_validation, una copia inline nel safety net dell'enrich
runner e il cron SQL. Tutte le decisioni sullo stato di un bando (scadenza
passata, apertura futura) devono usare la stessa data civile italiana, che
non coincide con quella UTC della macchina tra le 22:00 e le 24:00 (ora
legale) o tra le 23:00 e le 24:00 (ora solare).

`stato_effettivo` e' il gemello di `statoEffettivo` in `src/lib/stato-bando.ts`
e della funzione SQL `bando_stato_effettivo`: la tabella di verita' condivisa e'
`tests/stato-bando/casi.json`, su cui girano i test dei tre linguaggi.

Solo stdlib (datetime, zoneinfo): nessun import interno al package, cosi' il
modulo resta importabile ovunque senza trascinare logger, settings o DB, e il
test TypeScript puo' eseguirlo con `runpy.run_path`.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

ROMA = ZoneInfo("Europe/Rome")

_MESI_IT = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)


def adesso_roma(adesso: datetime | None = None) -> datetime:
    """Istante corrente (o quello passato) come datetime AWARE in Europe/Rome.

    Un datetime naive viene interpretato come UTC, mai come ora locale della
    macchina: il risultato non deve dipendere dal fuso del server.
    """
    if adesso is None:
        adesso = datetime.now(tz=timezone.utc)
    elif adesso.tzinfo is None:
        adesso = adesso.replace(tzinfo=timezone.utc)
    return adesso.astimezone(ROMA)


def oggi_roma(adesso: datetime | None = None) -> date:
    """Data civile italiana dell'istante corrente (o di quello passato)."""
    return adesso_roma(adesso).date()


def data_italiana(giorno: date) -> str:
    """Formato esteso per i prompt: `22 settembre 2026` (senza zero iniziale)."""
    return f"{giorno.day} {_MESI_IT[giorno.month - 1]} {giorno.year}"


# ---------------------------------------------------------------------------
# Vocabolario e macchina a stati (piano §4)
# ---------------------------------------------------------------------------

# Cinque stati: i tre storici della colonna piu' `sospeso` e `revocato`, che la
# migrazione 06 aggiunge al CHECK. Finche' la 06 non e' applicata la pipeline
# non scrive mai gli ultimi due (nessuna transizione con attore `pipeline` li
# raggiunge), quindi il codice resta compatibile con il CHECK a tre valori.
# Chi deve validare un valore in ingresso usa STATI_BANDO_PERSISTITI.
STATI_BANDO: tuple[str, ...] = (
    "aperto",
    "chiuso",
    "in apertura prossimamente",
    "sospeso",
    "revocato",
)

# I soli valori ammessi dal CHECK finche' la 06 non e' applicata: e' questa la
# tupla con cui si valida un valore che arriva da fuori (LLM, CLI, query).
STATI_BANDO_PERSISTITI: tuple[str, ...] = ("aperto", "chiuso", "in apertura prossimamente")

# Chi puo' scrivere `stato_bando`: gli stessi valori di `bando_evento.origine`.
# Il resolver non compare di proposito: tocca fonte e link, mai lo stato.
ATTORI_TRANSIZIONE: tuple[str, ...] = ("cron", "worker", "pipeline", "redazione")

# Tabella di §4, riga per riga; `da=None` e' la creazione della riga. E' una
# lista bianca, ed e' la stessa lista che la migrazione 04 semina in
# `bando_transizione` per autorizzare gli eventi sui bandi PUBBLICATI: una riga
# di troppo qui e' un varco nella guardia a DB. Quattro assenze volute:
#   - `revocato` non ha transizioni in uscita (§4 lo dichiara terminale);
#   - nessuna riga chiude un `sospeso` (A3: mai chiuso d'ufficio);
#   - nessuna riga ha attore `redazione`, perche' §4 non concede alla redazione
#     nessuna scrittura automatica su `stato_bando`;
#   - l'attore `pipeline` compare SOLO nelle righe di creazione (`da=None`): la
#     pipeline LLM tocca solo le righe non ancora pubblicate, che non passano
#     dal trigger, e §4 non le concede nessun passaggio fra stati. Concederglielo
#     farebbe riaprire un `chiuso` pubblicato senza le prove G1-G9 + G7, che §4 e
#     §13.3 dichiarano l'unico modo.
# Le righe di §4 che non cambiano `stato_bando` (rettifica/FAQ/allegato,
# fusione, ritiro) non stanno qui: agiscono su altre colonne.
TRANSIZIONI: tuple[dict[str, str | None], ...] = (
    {
        "da": None,
        "a": "aperto",
        "attore": "pipeline",
        "evento": "pubblicazione",
        "condizione": (
            "riga nuova non ancora pubblicata: lo stato lo decide il preprocess/enrich con la guardia reconcile_stato_bando; nessun evento leggibile prima della pubblicazione"
        ),
    },
    {
        "da": None,
        "a": "chiuso",
        "attore": "pipeline",
        "evento": "pubblicazione",
        "condizione": (
            "riga nuova non ancora pubblicata: lo stato lo decide il preprocess/enrich con la guardia reconcile_stato_bando; nessun evento leggibile prima della pubblicazione"
        ),
    },
    {
        "da": None,
        "a": "in apertura prossimamente",
        "attore": "pipeline",
        "evento": "pubblicazione",
        "condizione": (
            "riga nuova non ancora pubblicata: lo stato lo decide il preprocess/enrich con la guardia reconcile_stato_bando; nessun evento leggibile prima della pubblicazione"
        ),
    },
    {
        "da": "in apertura prossimamente",
        "a": "aperto",
        "attore": "cron",
        "evento": "apertura_automatica",
        "condizione": (
            "data_apertura_verificata=true e apertura raggiunta (data, e ora se presente); job orario 5 * * * *, evento con in_aggiornamenti=false"
        ),
    },
    {
        "da": "aperto",
        "a": "chiuso",
        "attore": "cron",
        "evento": "chiusura_automatica",
        "condizione": (
            "data_scadenza < oggi, oppure = oggi con ora_scadenza passata; job orario 5 * * * *, eventi con verificato=false e url_prova NULL; non tocca mai sospeso ne revocato"
        ),
    },
    {
        "da": "in apertura prossimamente",
        "a": "chiuso",
        "attore": "cron",
        "evento": "chiusura_automatica",
        "condizione": (
            "data_scadenza < oggi, oppure = oggi con ora_scadenza passata; job orario 5 * * * *, eventi con verificato=false e url_prova NULL; non tocca mai sospeso ne revocato"
        ),
    },
    {
        "da": "in apertura prossimamente",
        "a": "aperto",
        "attore": "worker",
        "evento": "apertura",
        "condizione": (
            "la pagina ufficiale dichiara apertura entro oggi; gate G1-G9 (citazione, url_prova scaricato, G6 su apert|dal|a partire|attiv, G7)"
        ),
    },
    {
        "da": "in apertura prossimamente",
        "a": "in apertura prossimamente",
        "attore": "worker",
        "evento": "rettifica",
        "condizione": (
            "differimento: date nuove di apertura e scadenza; gate G1-G9, G2 rafforzato al primo controllo; campo=data_apertura"
        ),
    },
    {
        "da": "aperto",
        "a": "aperto",
        "attore": "worker",
        "evento": "proroga",
        "condizione": (
            "scadenza posticipata; gate G1-G9 e vecchia data non NULL, nuova maggiore della vecchia e non anteriore a oggi"
        ),
    },
    {
        "da": "aperto",
        "a": "aperto",
        "attore": "worker",
        "evento": "rettifica",
        "condizione": (
            "sportello senza scadenza a cui compare una data_scadenza; gate G1-G9 come rettifica, G7 obbligatorio; campo=data_scadenza"
        ),
    },
    {
        "da": "aperto",
        "a": "chiuso",
        "attore": "worker",
        "evento": "chiusura",
        "condizione": (
            "esaurimento risorse o chiusura anticipata non successiva a oggi; gate G1-G9; data_scadenza resta intatta, non si scrive mai oggi"
        ),
    },
    {
        "da": "chiuso",
        "a": "aperto",
        "attore": "worker",
        "evento": "proroga",
        "condizione": (
            "proroga verificata; gate G1-G9 piu G7: unico modo per riaprire un chiuso"
        ),
    },
    {
        "da": "chiuso",
        "a": "aperto",
        "attore": "worker",
        "evento": "riapertura",
        "condizione": (
            "riapertura verificata; gate G1-G9 piu G7: unico modo per riaprire un chiuso"
        ),
    },
    {
        "da": "aperto",
        "a": "sospeso",
        "attore": "worker",
        "evento": "sospensione",
        "condizione": (
            "sospensione dichiarata dalla fonte ufficiale (G1-G9 su sospe); prima di R0 evento con applicato=false"
        ),
    },
    {
        "da": "in apertura prossimamente",
        "a": "sospeso",
        "attore": "worker",
        "evento": "sospensione",
        "condizione": (
            "sospensione dichiarata dalla fonte ufficiale (G1-G9 su sospe); prima di R0 evento con applicato=false"
        ),
    },
    {
        "da": "sospeso",
        "a": "aperto",
        "attore": "worker",
        "evento": "riapertura",
        "condizione": (
            "ripresa dichiarata dalla fonte ufficiale; gate G1-G9"
        ),
    },
    {
        "da": "sospeso",
        "a": "in apertura prossimamente",
        "attore": "worker",
        "evento": "riapertura",
        "condizione": (
            "ripresa con nuova data di apertura dichiarata dalla fonte ufficiale; gate G1-G9"
        ),
    },
    {
        "da": "aperto",
        "a": "revocato",
        "attore": "worker",
        "evento": "revoca",
        "condizione": (
            "revoca, annullamento o ritiro dichiarati dalla fonte ufficiale (G1-G9 su revoc|annull|ritir); stato terminale; prima di R0 evento con applicato=false"
        ),
    },
    {
        "da": "chiuso",
        "a": "revocato",
        "attore": "worker",
        "evento": "revoca",
        "condizione": (
            "revoca, annullamento o ritiro dichiarati dalla fonte ufficiale (G1-G9 su revoc|annull|ritir); stato terminale; prima di R0 evento con applicato=false"
        ),
    },
    {
        "da": "in apertura prossimamente",
        "a": "revocato",
        "attore": "worker",
        "evento": "revoca",
        "condizione": (
            "revoca, annullamento o ritiro dichiarati dalla fonte ufficiale (G1-G9 su revoc|annull|ritir); stato terminale; prima di R0 evento con applicato=false"
        ),
    },
    {
        "da": "sospeso",
        "a": "revocato",
        "attore": "worker",
        "evento": "revoca",
        "condizione": (
            "revoca, annullamento o ritiro dichiarati dalla fonte ufficiale (G1-G9 su revoc|annull|ritir); stato terminale; prima di R0 evento con applicato=false"
        ),
    },
    {
        "da": "chiuso",
        "a": "chiuso",
        "attore": "worker",
        "evento": "graduatoria",
        "condizione": (
            "pubblicazione della graduatoria: link nuovo scaricato con esito 2xx; in_aggiornamenti=true, lo stato non cambia"
        ),
    },
    {
        "da": "chiuso",
        "a": "chiuso",
        "attore": "worker",
        "evento": "esito",
        "condizione": (
            "pubblicazione degli esiti: link nuovo scaricato con esito 2xx; in_aggiornamenti=true, lo stato non cambia"
        ),
    },
)


def transizione_ammessa(da: str | None, a: str, attore: str) -> bool:
    """La transizione e' prevista dalla macchina a stati?

    Lista bianca: `False` e' la risposta di default, anche per un attore che
    non scrive mai lo stato.
    """
    for transizione in TRANSIZIONI:
        if transizione["da"] == da and transizione["a"] == a and transizione["attore"] == attore:
            return True
    return False


# ---------------------------------------------------------------------------
# Stato effettivo alla lettura (piano §13.3)
# ---------------------------------------------------------------------------

_CIFRE = frozenset("0123456789")


def _cifre(testo: str) -> bool:
    """Solo cifre ASCII: `str.isdigit()` accetterebbe anche i numeri arabi."""
    return bool(testo) and all(carattere in _CIFRE for carattere in testo)


def _solo_giorno(valore: object) -> str | None:
    """Giorno YYYY-MM-DD da una `date`, da un timestamp o da una stringa."""
    if isinstance(valore, datetime):
        return valore.date().isoformat()
    if isinstance(valore, date):
        return valore.isoformat()
    if not isinstance(valore, str):
        return None
    giorno = valore[:10]
    if len(giorno) != 10 or giorno[4] != "-" or giorno[7] != "-":
        return None
    if not (_cifre(giorno[:4]) and _cifre(giorno[5:7]) and _cifre(giorno[8:10])):
        return None
    return giorno


def _solo_ora(valore: object) -> str | None:
    """Ora normalizzata a HH:MM:SS (i secondi mancanti valgono 00), o None."""
    if isinstance(valore, time):
        return valore.strftime("%H:%M:%S")
    if not isinstance(valore, str):
        return None
    testo = valore.strip()
    if len(testo) < 5 or testo[2] != ":":
        return None
    if not (_cifre(testo[:2]) and _cifre(testo[3:5])):
        return None
    secondi = "00"
    if len(testo) >= 8 and testo[5] == ":" and _cifre(testo[6:8]):
        secondi = testo[6:8]
    return f"{testo[:2]}:{testo[3:5]}:{secondi}"


def _stato_valido(valore: object) -> str | None:
    return valore if valore in STATI_BANDO else None


def stato_effettivo(
    stato: str | None,
    data_apertura: object = None,
    apertura_verificata: object = None,
    ora_apertura: object = None,
    data_scadenza: object = None,
    ora_scadenza: object = None,
    adesso: datetime | None = None,
) -> str | None:
    """Stato da mostrare all'utente, in ordine di precedenza (§13.3):

      1. `revocato` resta `revocato` (terminale);
      2. `sospeso` resta `sospeso` anche con la scadenza passata (A3);
      3. scadenza passata (`data_scadenza` < oggi, oppure = oggi con
         `ora_scadenza` passata) -> `chiuso`;
      4. `in apertura prossimamente` con apertura VERIFICATA e raggiunta ->
         `aperto` (`apertura_verificata` e' il nome breve del fixture per la
         colonna `data_apertura_verificata` di §13.0);
      5. altrimenti lo stato salvato (NULL se non e' uno dei cinque).

    Due asimmetrie volute sull'istante esatto: la scadenza e' passata solo DOPO
    l'ora dichiarata (alle 12:00:00 in punto si e' ancora in tempo), l'apertura
    e' raggiunta A PARTIRE dall'ora dichiarata. In entrambi i casi l'istante di
    confine sta dentro la finestra di partecipazione.

    Il giorno di scadenza senza `ora_scadenza` il bando resta aperto fino a
    mezzanotte di Roma.
    """
    stato_salvato = _stato_valido(stato)
    if stato_salvato == "revocato":
        return "revocato"
    if stato_salvato == "sospeso":
        return "sospeso"

    scadenza = _solo_giorno(data_scadenza)
    apertura = (
        _solo_giorno(data_apertura)
        if stato_salvato == "in apertura prossimamente" and apertura_verificata is True
        else None
    )
    # Senza date da confrontare non serve nemmeno leggere l'orologio.
    if scadenza is None and apertura is None:
        return stato_salvato

    momento = adesso_roma(adesso)
    oggi = momento.date().isoformat()
    ora_adesso = momento.strftime("%H:%M:%S")

    if scadenza is not None:
        if scadenza < oggi:
            return "chiuso"
        ora_scad = _solo_ora(ora_scadenza) if scadenza == oggi else None
        if ora_scad is not None and ora_scad < ora_adesso:
            return "chiuso"

    if apertura is not None and apertura <= oggi:
        ora_apert = _solo_ora(ora_apertura) if apertura == oggi else None
        if ora_apert is None or ora_apert <= ora_adesso:
            return "aperto"

    return stato_salvato
