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
# `bando_transizione` per autorizzare gli eventi sui bandi PUBBLICATI (le righe
# con `migrazione` le aggiunge il delta di quella migrazione): una riga di
# troppo qui e' un varco nella guardia a DB. Assenze e limiti voluti:
#   - dal `revocato` si esce solo con `annullamento_revoca` del worker (14);
#   - un `sospeso` si chiude solo con una `chiusura` letta dal worker (14), mai
#     d'ufficio: il cron non tocca un sospeso (A3);
#   - nessuna riga ha attore `redazione`, perche' §4 non concede alla redazione
#     nessuna scrittura automatica su `stato_bando`; la correzione a mano passa
#     dalla RPC `bando_correggi_stato` della migrazione 14, fuori lista;
#   - l'attore `pipeline` compare SOLO nelle righe di creazione (`da=None`): la
#     pipeline LLM tocca solo le righe non ancora pubblicate, che non passano
#     dal trigger, e §4 non le concede nessun passaggio fra stati. Concederglielo
#     farebbe riaprire un `chiuso` pubblicato senza le prove G1-G9 + G7, che §4 e
#     §13.3 dichiarano l'unico modo.
# Le righe di §4 che non cambiano `stato_bando` (rettifica/FAQ/allegato,
# fusione, ritiro) non stanno qui: agiscono su altre colonne.
TRANSIZIONI: tuple[dict[str, str | int | None], ...] = (
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
    # `migrazione`: la riga entra in `bando_transizione` con quella migrazione
    # (blocco «delta»), non con il seed della 04, che resta identico.
    {
        "da": "in apertura prossimamente",
        "a": "chiuso",
        "attore": "worker",
        "evento": "chiusura",
        "condizione": (
            "la pagina ufficiale dichiara chiuso, scaduto o concluso con etichetta strutturata; gate G1-G9, G7 per doppia lettura strutturata (contratto 6.1)"
        ),
        "migrazione": 13,
    },
    # Migrazione 14 (giro 3, contratto interno §14): il sospeso si chiude con
    # una chiusura letta dal worker, e dal revocato si esce solo con
    # `annullamento_revoca`, verso lo stato che la RPC calcola dalle date.
    {
        "da": "sospeso",
        "a": "chiuso",
        "attore": "worker",
        "evento": "chiusura",
        "condizione": (
            "la pagina ufficiale dichiara chiuso il bando sospeso (chiusura dell'ente o termine senza ripresa); gate G1-G9, G7; mai d'ufficio: il cron non tocca un sospeso"
        ),
        "migrazione": 14,
    },
    {
        "da": "revocato",
        "a": "aperto",
        "attore": "worker",
        "evento": "annullamento_revoca",
        "condizione": (
            "la fonte ufficiale annulla la revoca; stato di arrivo calcolato dalle date: apertura raggiunta e scadenza non passata; gate G1-G9"
        ),
        "migrazione": 14,
    },
    {
        "da": "revocato",
        "a": "chiuso",
        "attore": "worker",
        "evento": "annullamento_revoca",
        "condizione": (
            "la fonte ufficiale annulla la revoca; stato di arrivo calcolato dalle date: scadenza gia passata; gate G1-G9"
        ),
        "migrazione": 14,
    },
    {
        "da": "revocato",
        "a": "in apertura prossimamente",
        "attore": "worker",
        "evento": "annullamento_revoca",
        "condizione": (
            "la fonte ufficiale annulla la revoca; stato di arrivo calcolato dalle date: apertura futura; gate G1-G9"
        ),
        "migrazione": 14,
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


# ---------------------------------------------------------------------------
# Stato da verificare (contratto interno del giro 2, §3 con §19.3)
# ---------------------------------------------------------------------------

# Perche' lo stato mostrato non e' certo. Elenco chiuso, lo stesso della sezione
# `certezza` di `tests/stato-bando/casi.json`, di `statoDaVerificare` in
# `src/lib/stato-bando.ts`, della funzione SQL `bando_stato_da_verificare` e
# dell'enum dell'API v1. None vuol dire «nessuna prova contraria».
MOTIVI_DA_VERIFICARE: tuple[str, ...] = (
    "data_apertura_passata",
    "smentito_dalla_fonte",
    "previsione_scaduta",
    "senza_conferma",
    "termine_passato",
)

# Gli stati che la verifica sa leggere sulla pagina ufficiale e chi li legge.
STATI_LETTI: tuple[str, ...] = ("in apertura prossimamente", "aperto", "chiuso", "uscito")
METODI_LETTURA: tuple[str, ...] = ("estrattore", "modello")

GIORNI_GRAZIA_PUBBLICAZIONE = 3  # ramo I, I6
GIORNI_VALIDITA_CONFERMA = 30  # I5 e A2
GIORNI_GRAZIA_RAMO_A = 7  # ramo A, A7


def _istante(valore: object) -> datetime | None:
    """Istante AWARE da un datetime, una date o un testo ISO 8601 (come lo
    restituisce PostgREST), o None se manca o e' malformato. Un naive vale UTC,
    come in `adesso_roma`: mai l'ora locale della macchina."""
    if isinstance(valore, datetime):
        momento = valore
    elif isinstance(valore, date):
        momento = datetime(valore.year, valore.month, valore.day)
    elif isinstance(valore, str):
        testo = valore.strip()
        if _solo_giorno(testo) is None:
            return None
        try:
            momento = datetime.fromisoformat(_iso_per_fromisoformat(testo))
        except ValueError:
            return None
    else:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento


def _iso_per_fromisoformat(testo: str) -> str:
    """Il testo ISO nella forma che anche `fromisoformat` di Python 3.10 legge.

    Il 3.10 non accetta la «Z», i fusi senza i due punti (`+00`, `+0000`) ne'
    le frazioni di secondo diverse da 3 o 6 cifre, che PostgREST restituisce
    (`08:00:00.87927+00:00`: PostgreSQL toglie gli zeri in coda). La frazione
    si porta a 6 cifre come in `backend/app/lock_orfani.istante`; senza `re`,
    perche' il modulo resta solo stdlib di data e ora.
    """
    testo = testo.replace("Z", "+00:00")
    if len(testo) > 10 and testo[10] == " ":
        testo = testo[:10] + "T" + testo[11:]
    corpo, fuso = testo, ""
    # Il fuso sta in coda, dopo l'ora: i trattini della data sono prima del decimo carattere.
    for indice in range(len(testo) - 1, 10, -1):
        if testo[indice] in "+-":
            corpo, fuso = testo[:indice], testo[indice:]
            break
    if len(fuso) == 3 and _cifre(fuso[1:]):
        fuso += ":00"
    elif len(fuso) == 5 and _cifre(fuso[1:]):
        fuso = f"{fuso[:3]}:{fuso[3:]}"
    punto = corpo.find(".", 10)
    if punto != -1 and _cifre(corpo[punto + 1:]):
        corpo = corpo[:punto + 1] + (corpo[punto + 1:] + "000000")[:6]
    return corpo + fuso


def _giorni_fa(momento: datetime, oggi: date) -> int:
    """Giorni civili di Roma fra l'istante e `oggi`; negativi se nel futuro."""
    return (oggi - momento.astimezone(ROMA).date()).days


def stato_da_verificare(
    stato: str | None,
    data_apertura: object,
    apertura_verificata: object,
    ora_apertura: object,
    data_scadenza: object,
    ora_scadenza: object,
    pubblicato_at: object,
    previsto_entro: object,
    termine_indicato: object,
    stato_letto: object,
    stato_letto_su: object,
    stato_letto_at: object,
    stato_letto_metodo: object,
    esaminato_attivo_at: object,
    segnale_aggregatore_at: object,
    adesso: datetime | None = None,
) -> str | None:
    """Motivo per cui lo stato mostrato va verificato, o None (gemello di
    `statoDaVerificare`; casi nella sezione `certezza` di casi.json). Vince la
    prima regola che si applica, nell'ordine definitivo di §19.3: in ombra (mai
    esaminato in attivo) conta solo cio' che il bando dice di se', quindi
    l'unico motivo pubblico e' data_apertura_passata.

    R0: stato effettivo «in apertura» -> ramo I; «aperto» senza
    `data_scadenza` -> ramo A; altrimenti None.

    Ramo I, nell'ordine I1, I2, I3, I6-bis, I4, I5, I6, I7: I1 apertura
    verificata con data -> None; I2 `data_apertura` < oggi ->
    data_apertura_passata; I3 lettura valida aperto/chiuso/uscito ->
    smentito_dalla_fonte; I6-bis mai esaminato in attivo -> None; I4
    `previsto_entro` < oggi -> previsione_scaduta; I5 lettura valida «in
    apertura» di al massimo 30 giorni fa -> None; I6 pubblicato da al massimo 3
    giorni -> None; I7 -> senza_conferma.

    Ramo A, nell'ordine A1, A2, A4, A3, A5, A6, A7, A8: A1 lettura valida
    chiuso/uscito/in apertura -> smentito_dalla_fonte; A2 lettura valida
    «aperto» dell'estrattore di al massimo 30 giorni fa e successiva al segnale
    dell'aggregatore -> None; A4 mai esaminato in attivo -> None; A3
    `termine_indicato` < oggi -> termine_passato; A5 segnale dell'aggregatore ->
    senza_conferma; A6 termine indicato da oggi in poi -> None; A7 pubblicato da
    al massimo 7 giorni -> None; A8 -> senza_conferma.

    Lettura valida: `stato_letto` fra STATI_LETTI, `stato_letto_su` uguale allo
    stato salvato e `stato_letto_at` presente. «Giorni fa» e' la differenza fra
    date civili di Roma, non fra ore.
    """
    momento = adesso_roma(adesso)
    effettivo = stato_effettivo(
        stato, data_apertura, apertura_verificata, ora_apertura, data_scadenza, ora_scadenza,
        momento,
    )
    ramo_a = effettivo == "aperto" and _solo_giorno(data_scadenza) is None
    if effettivo != "in apertura prossimamente" and not ramo_a:
        return None

    oggi = momento.date()
    oggi_iso = oggi.isoformat()

    def entro(istante: datetime | None, giorni: int) -> bool:
        return istante is not None and _giorni_fa(istante, oggi) <= giorni

    letto = stato_letto if stato_letto in STATI_LETTI else None
    letto_at = _istante(stato_letto_at)
    lettura = letto if letto is not None and letto_at is not None and stato_letto_su == stato else None
    pubblicato = _istante(pubblicato_at)

    if not ramo_a:
        apertura = _solo_giorno(data_apertura)
        if apertura_verificata is True and apertura is not None:
            return None
        if apertura is not None and apertura < oggi_iso:
            return "data_apertura_passata"
        if lettura is not None and lettura != "in apertura prossimamente":
            return "smentito_dalla_fonte"
        if _istante(esaminato_attivo_at) is None:
            return None
        previsto = _solo_giorno(previsto_entro)
        if previsto is not None and previsto < oggi_iso:
            return "previsione_scaduta"
        if lettura == "in apertura prossimamente" and entro(letto_at, GIORNI_VALIDITA_CONFERMA):
            return None
        if entro(pubblicato, GIORNI_GRAZIA_PUBBLICAZIONE):
            return None
        return "senza_conferma"

    if lettura is not None and lettura != "aperto":
        return "smentito_dalla_fonte"
    segnale = _istante(segnale_aggregatore_at)
    metodo = stato_letto_metodo if stato_letto_metodo in METODI_LETTURA else None
    if (
        lettura == "aperto"
        and letto_at is not None
        and metodo == "estrattore"
        and entro(letto_at, GIORNI_VALIDITA_CONFERMA)
        and (segnale is None or letto_at > segnale)
    ):
        return None
    if _istante(esaminato_attivo_at) is None:
        return None
    termine = _solo_giorno(termine_indicato)
    if termine is not None and termine < oggi_iso:
        return "termine_passato"
    if segnale is not None:
        return "senza_conferma"
    if termine is not None:
        return None
    if entro(pubblicato, GIORNI_GRAZIA_RAMO_A):
        return None
    return "senza_conferma"
