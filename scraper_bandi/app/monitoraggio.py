# -*- coding: utf-8 -*-
"""Monitor delle pagine ufficiali: step 7 della pipeline bandi (piano §6.2).

Che cosa fa
-----------
Riprende in mano i bandi gia' pubblicati e va a vedere se la loro pagina
ufficiale e' cambiata. Il giro tipico di un bando e': pre-filtro gratuito ->
GET condizionale -> diff locale -> (solo se il diff e' rilevante)
classificazione -> gate G1-G9 -> evento -> eventuale rigenerazione mirata.

Le tre cose che rendono questo modulo diverso da un cron qualunque:

1. **quasi tutti i controlli non costano niente.** L'ordine e' scelto perche'
   il caso frequente sia il piu' economico: un segnale macchina per host, poi
   un `If-None-Match` che risponde 304, poi un'impronta identica. Solo cio'
   che sopravvive a tutti e tre arriva al modello. L'atteso di §6.2 e' che
   >= 85 % dei controlli si fermi prima;
2. **il jitter non e' un dettaglio.** I 416 bandi a sportello hanno tutti la
   stessa cadenza e, se seminati insieme, scadrebbero tutti lo stesso giorno:
   643 fetch contro un tetto di 420, cioe' il tetto che scatta *per
   costruzione*, tutti i giorni, per sempre. Il jitter uniforme +-25 % su
   `prossimo_controllo_at` e' cio' che rende il piano eseguibile;
3. **niente qui solleva.** Tetto raggiunto, lock occupato, colonne assenti,
   host che risponde 500: sono tutti dizionari di ritorno. `bandi_pipeline.py`
   cattura solo `Exception`, e un `SystemExit` sollevato qui ucciderebbe il
   sender (A15).

L'I/O e' iniettabile per intero (`FonteDati`, `scarica`, `classifica`,
`seconda_opinione`, `pagine_collegate`, `rigenerazione`): i test girano senza
rete e senza DB.
"""
from __future__ import annotations

import csv
import json
import random
import sys
import time
import traceback
import zlib
from dataclasses import dataclass, field
from datetime import date as date_cls, datetime, timedelta
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

from . import bilancio, blocco, eventi as eventi_mod, impronte, sedia, telemetria
from .date_validation import estrai_date_con_ruolo, norm_cit
from .logger import logger
from .stato_bando import adesso_roma, oggi_roma, stato_effettivo

NOME_LOCK = "monitor"

#: Quanti eventi respinti per bando si registrano. Servono a misurare i gate
#: nel periodo d'ombra, non a tenere un registro completo: un modello che
#: proponesse cinquanta eventi su una pagina non deve poter scrivere cinquanta
#: righe. Il primo giro e' il picco per costruzione (nessun «prima» con cui
#: confrontare, quindi ogni data della pagina e' una proposta); dai successivi
#: il diff e' piccolo e le proposte poche.
RESPINTI_A_DB_PER_BANDO = 5
STEP = "monitor"

# --- fasi del ciclo di vita (§6.2) ------------------------------------------

FASE_IAP_IGNOTA = "iap_data_ignota"
FASE_IAP_VICINA = "iap_entro_7"
FASE_IAP_LONTANA = "iap_oltre_7"
FASE_IAP_RAGGIUNTA = "iap_raggiunta_non_verificata"
FASE_APERTO_VICINO = "aperto_entro_7"
FASE_APERTO_MEDIO = "aperto_8_30"
FASE_APERTO_LONTANO = "aperto_oltre_30"
FASE_SPORTELLO = "sportello"
FASE_SOSPESO = "sospeso"
FASE_CHIUSO = "chiuso"
FASE_REVOCATO = "revocato"

FASI: tuple[str, ...] = (
    FASE_IAP_IGNOTA, FASE_IAP_VICINA, FASE_IAP_LONTANA, FASE_IAP_RAGGIUNTA,
    FASE_APERTO_VICINO, FASE_APERTO_MEDIO, FASE_APERTO_LONTANO, FASE_SPORTELLO,
    FASE_SOSPESO, FASE_CHIUSO, FASE_REVOCATO,
)

# Giorni fra un controllo e il successivo, per fase e scenario (§6.2).
# `None` = non si ricontrolla piu' (il revocato e' terminale).
FREQUENZE: dict[str, dict[str, float | None]] = {
    "economico": {
        FASE_IAP_IGNOTA: 5, FASE_IAP_VICINA: 1, FASE_IAP_LONTANA: 3,
        FASE_IAP_RAGGIUNTA: 1, FASE_APERTO_VICINO: 2, FASE_APERTO_MEDIO: 5,
        FASE_APERTO_LONTANO: 14, FASE_SPORTELLO: 7, FASE_SOSPESO: 3,
        FASE_CHIUSO: 60, FASE_REVOCATO: None,
    },
    "bilanciato": {
        FASE_IAP_IGNOTA: 3, FASE_IAP_VICINA: 1, FASE_IAP_LONTANA: 3,
        FASE_IAP_RAGGIUNTA: 1, FASE_APERTO_VICINO: 1, FASE_APERTO_MEDIO: 3,
        FASE_APERTO_LONTANO: 7, FASE_SPORTELLO: 3, FASE_SOSPESO: 2,
        FASE_CHIUSO: 30, FASE_REVOCATO: None,
    },
    "massimo": {
        FASE_IAP_IGNOTA: 3, FASE_IAP_VICINA: 1, FASE_IAP_LONTANA: 3,
        FASE_IAP_RAGGIUNTA: 1, FASE_APERTO_VICINO: 1, FASE_APERTO_MEDIO: 3,
        FASE_APERTO_LONTANO: 7, FASE_SPORTELLO: 1.5, FASE_SOSPESO: 2,
        FASE_CHIUSO: 30, FASE_REVOCATO: None,
    },
}

# Coda del chiuso: gli scatti fissi dopo la scadenza, poi la cadenza di
# `FREQUENZE[...][FASE_CHIUSO]`, fino al limite in mesi. Dopo il limite il
# bando smette di essere ricontrollato: una graduatoria che esce due anni dopo
# non vale un fetch ogni mese per sempre.
CODA_CHIUSO: dict[str, tuple[tuple[int, ...], int]] = {
    "economico": ((3, 14, 45), 12),
    "bilanciato": ((3, 10, 30), 12),
    "massimo": ((3, 10, 30), 15),
}

# Priorita' di base per fase (0-100, §6.2).
PRIORITA_FASE: dict[str, int] = {
    FASE_IAP_RAGGIUNTA: 90,
    FASE_IAP_VICINA: 70,
    FASE_APERTO_VICINO: 70,
    FASE_SOSPESO: 60,
    FASE_APERTO_MEDIO: 50,
    FASE_IAP_IGNOTA: 50,
    FASE_IAP_LONTANA: 50,
    FASE_APERTO_LONTANO: 30,
    FASE_SPORTELLO: 30,
    FASE_CHIUSO: 10,
    FASE_REVOCATO: 0,
}

BONUS_SEGNALE_FONTE = 20      # un segnale C sul listing
BONUS_EVENTO_IN_ATTESA = 25   # un evento gia' raccolto e non ancora applicato
BONUS_SEGNALE_MACCHINA = 10   # `modified_gmt`, `ds_last_update`, HEAD cambiato

JITTER = 0.25                 # +-25 % su `prossimo_controllo_at`
VOLATILITA_MIN = 0.5
VOLATILITA_MAX = 2.0
VOLATILITA_EVENTO = 0.7       # un evento verificato avvicina il prossimo giro
VOLATILITA_CALMA = 1.3        # tre controlli senza diff lo allontanano
CONTROLLI_PER_CALMA = 3

BACKOFF_BASE_ORE = 6
BACKOFF_MASSIMO_ORE = 24 * 7
FALLIMENTI_PER_BLOCCO = 5

MAX_PAGINE_COLLEGATE = 2

STATO_FONTE_TROVATA = "trovata"

# Colonne di `bando_controllo` senza le quali il monitor non puo' lavorare.
# Le prime sei reggono la coda; le quattro che seguono sono la **memoria** del
# monitor e nascono tutte dalla stessa CREATE TABLE della migrazione 02. Senza
# `testo_norm` non esiste un «prima», quindi non esiste diff: ogni controllo
# arriverebbe al modello con `usa_g2_primo` vero, cioe' esattamente il caso che
# §6.2 vuole eccezionale. Senza `etag`/`last_modified` la GET condizionale non
# puo' ottenere un 304. Se mancano lo step degrada (§16.2 M12).
COLONNE_CONTROLLO: tuple[str, ...] = (
    "bando_id", "prossimo_controllo_at", "ultimo_controllo_at",
    "impronta_contenuto", "controlli_falliti", "priorita_controllo",
    "testo_norm", "impronte_sezioni", "etag", "last_modified",
)

#: Un giro senza la memoria di `bando_controllo` funziona, ma non ha un
#: «prima»: ogni controllo va al modello e nessun fallimento si accumula. E'
#: un allarme del giro, non un guasto.
ALLARME_MEMORIA_ASSENTE = (
    "memoria di bando_controllo non letta: giro senza baseline "
    "(nessun 304, nessun diff, i fallimenti non si accumulano)"
)

# `testo_norm` e' `bytea`: PostgREST lo vuole come letterale `\x<esadecimale>`.
PREFISSO_BYTEA = "\\x"
LIVELLO_ZLIB = 6

MODELLO_CLASSIFICATORE = "claude-haiku-4-5"
MAX_TOKEN_CLASSIFICATORE = 1500

# Seconda opinione del G7 (§6.2): un modello **diverso** e piu' capace di
# quello che ha proposto l'evento. Il nome sta a listino in `settings`
# (`claude-sonnet-4-6`), altrimenti `bilancio` alzerebbe «modello non a
# listino» e il costo della conferma conterebbe zero — cioe' il tetto in $ non
# vedrebbe proprio le chiamate piu' care del monitor.
MODELLO_SECONDA_OPINIONE = "claude-sonnet-4-6"
MAX_TOKEN_SECONDA_OPINIONE = 1500

# Pagine collegate (§6.2). La soglia sui titoli e' la stessa del piano: sotto
# 0,5 una notizia non parla di questo bando, e un `url_prova` sbagliato e' il
# modo piu' rapido di far passare il G4 a una data che non c'entra.
SOGLIA_TITOLI_COLLEGATE = 0.5
TOKEN_RICERCA_WP = 3
# Sul ramo WordPress il filtro di pertinenza c'e' ma **non** e' un Jaccard: e'
# la copertura dei token di ricerca, cioe' quanti dei token mandati a
# `?search=` compaiono nel titolo del post.
#
# Un filtro ci vuole perche' `?search=` e' un OR ordinato per pertinenza, non
# un AND: senza, i primi due post diventano prove del G7 qualunque cosa dicano,
# e su un portale regionale molti bandi condividono la stessa scadenza — una
# coincidenza di (data, ruolo) non e' remota.
#
# Non un Jaccard perche' dipende dalla LUNGHEZZA dei due titoli, e la notizia
# giusta e' quasi sempre piu' lunga della scheda: il caso guida di §6.2
# («Psicologia scolastica nelle scuole del Lazio: differimento dei termini di
# presentazione delle domande» contro «Avviso pubblico Psicologia scolastica»)
# vale 0,182 di Jaccard, cioe' verrebbe buttato da qualunque soglia sensata
# mentre la sagra di paese, che vale 0,0, passerebbe con una soglia piu' bassa.
# La copertura no: chiede che il post parli di almeno una delle parole
# distintive del bando, e quella misura non si accorcia se il titolo si allunga.
COPERTURA_RICERCA_WP = 1.0 / TOKEN_RICERCA_WP     # almeno uno dei tre token
PERCORSO_WP_POSTS = "/wp-json/wp/v2/posts"
# Finestra di ripiego di `?after=` al **primo** controllo di un bando, quando
# `ultimo_controllo_at` non c'e' ancora. Senza, la ricerca pescherebbe fra
# tutti i post di sempre proprio nel giro in cui il G7 gira in variante G2'
# (doppia prova) e conta di piu'.
GIORNI_RICERCA_WP = 90
# Parole che non restringono niente e che quindi non meritano uno dei tre
# token di `?search=`: quelle del dominio (stanno in quasi ogni titolo di
# bando) e le parole vuote italiane lunghe almeno tre lettere — le piu' corte
# cadono gia' per il filtro `len > 2`. Vale **solo** per la query di ricerca:
# la somiglianza fra titoli resta quella di `fonte_ufficiale.token`, che e' la
# nozione di «parola uguale» del resto del package.
PAROLE_VUOTE_RICERCA: frozenset[str] = frozenset({
    "avviso", "avvisi", "bando", "bandi",
    "agli", "alla", "alle", "che", "con", "dai", "dal", "dalla", "dalle",
    "degli", "dei", "del", "della", "delle", "gli", "negli", "nei", "nel",
    "nella", "nelle", "non", "per", "sui", "sul", "sulla", "sulle", "tra",
    "una", "uno",
})


def comprimi_testo(testo: str | None) -> str | None:
    r"""`testo_norm` pronto per la colonna: zlib, poi il letterale `\x...`.

    Il COMMENT della migrazione 02 dice «testo normalizzato compresso»: la
    pagina piena non va a DB, e su qualche migliaio di righe la differenza fra
    il testo e lo zlib e' l'ordine di grandezza della tabella.
    """
    if not testo:
        return None
    try:
        return PREFISSO_BYTEA + zlib.compress(testo.encode("utf-8"), LIVELLO_ZLIB).hex()
    except Exception as e:                                # pragma: no cover - ripiego
        logger.debug("[monitor] compressione del testo fallita: {}", e)
        return None


def testo_da_colonna(valore: Any) -> str | None:
    r"""Il «prima» letto da `bando_controllo.testo_norm`.

    Tre forme accettate, perche' la colonna puo' arrivare da tre strade: il
    letterale `\x...` di PostgREST, i byte gia' decodificati da un driver, e
    il testo in chiaro (righe scritte prima della compressione e fixture dei
    test). Una colonna illeggibile vale `None`: il controllo riparte dal primo
    giro invece di sollevare.
    """
    if valore is None:
        return None
    grezzi: bytes | None = None
    if isinstance(valore, (bytes, bytearray, memoryview)):
        grezzi = bytes(valore)
    elif isinstance(valore, str):
        if not valore.startswith(PREFISSO_BYTEA):
            return valore or None
        try:
            grezzi = bytes.fromhex(valore[len(PREFISSO_BYTEA):])
        except ValueError:
            return None
    if grezzi is None:
        return None
    try:
        return zlib.decompress(grezzi).decode("utf-8", "replace")
    except Exception:
        try:
            return grezzi.decode("utf-8")
        except Exception:                                 # pragma: no cover - ripiego
            return None


# --- fase, frequenza, priorita' (funzioni pure) -----------------------------

def _data(valore: Any) -> date_cls | None:
    if isinstance(valore, datetime):
        return valore.date()
    if isinstance(valore, date_cls):
        return valore
    if isinstance(valore, str) and len(valore) >= 10:
        try:
            return date_cls.fromisoformat(valore[:10])
        except ValueError:
            return None
    return None


def _istante(valore: Any) -> datetime | None:
    if isinstance(valore, datetime):
        return adesso_roma(valore)
    if isinstance(valore, str) and valore.strip():
        try:
            return adesso_roma(datetime.fromisoformat(valore.strip().replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def fase(riga: Mapping[str, Any], *, oggi: date_cls | None = None) -> str:
    """Fase del ciclo di vita del bando (§6.2).

    Si parte dallo **stato effettivo**, non dalla colonna: un bando con la
    scadenza di ieri e' chiuso anche se il cron non ha ancora girato, e
    ricontrollarlo come «aperto entro 7 giorni» sarebbe un fetch sprecato ogni
    giorno.
    """
    giorno = oggi or oggi_roma()
    effettivo = stato_effettivo(
        riga.get("stato_bando"),
        data_apertura=riga.get("data_apertura"),
        apertura_verificata=riga.get("data_apertura_verificata"),
        ora_apertura=riga.get("ora_apertura"),
        data_scadenza=riga.get("data_scadenza"),
        ora_scadenza=riga.get("ora_scadenza"),
        adesso=datetime.combine(giorno, datetime.min.time()),
    )
    if effettivo == "revocato":
        return FASE_REVOCATO
    if effettivo == "sospeso":
        return FASE_SOSPESO
    if effettivo == "chiuso":
        return FASE_CHIUSO

    apertura = _data(riga.get("data_apertura"))
    if riga.get("stato_bando") == "in apertura prossimamente":
        if apertura is None:
            return FASE_IAP_IGNOTA
        mancano = (apertura - giorno).days
        if mancano <= 0:
            # Apertura raggiunta ma non verificata: e' la fase piu' urgente del
            # piano, perche' la vista continua a dire «in apertura» mentre il
            # bando e' gia' aperto.
            return FASE_IAP_RAGGIUNTA
        return FASE_IAP_VICINA if mancano <= 7 else FASE_IAP_LONTANA

    scadenza = _data(riga.get("data_scadenza"))
    if scadenza is None:
        return FASE_SPORTELLO
    mancano = (scadenza - giorno).days
    if mancano <= 7:
        return FASE_APERTO_VICINO
    if mancano <= 30:
        return FASE_APERTO_MEDIO
    return FASE_APERTO_LONTANO


def _scenario(nome: str | None) -> str:
    return nome if nome in FREQUENZE else "bilanciato"


def giorni_chiuso(riga: Mapping[str, Any], scenario: str, *, oggi: date_cls | None = None) -> float | None:
    """Giorni al prossimo controllo di un bando chiuso, o None = basta cosi'.

    La coda e' a scatti (+3, +14, +45 ...) perche' graduatorie ed esiti escono
    quasi tutti nelle prime settimane. Il calcolo e' **senza stato**: si parte
    dai giorni trascorsi dalla scadenza, non da un contatore che potrebbe
    essere stato perso in un redeploy.
    """
    scadenza = _data(riga.get("data_scadenza"))
    giorno = oggi or oggi_roma()
    scatti, mesi = CODA_CHIUSO.get(scenario, CODA_CHIUSO["bilanciato"])
    cadenza = FREQUENZE[scenario][FASE_CHIUSO] or 30
    if scadenza is None:
        # Chiuso senza data di scadenza (chiusura anticipata): si usa la
        # cadenza piena, che e' la scelta piu' prudente delle due.
        return float(cadenza)
    trascorsi = (giorno - scadenza).days
    if trascorsi > mesi * 30:
        return None
    for scatto in scatti:
        if trascorsi < scatto:
            return float(scatto - trascorsi)
    # Dopo gli scatti fissi: la prossima tacca multipla della cadenza.
    oltre = trascorsi - scatti[-1]
    prossima = (int(oltre // cadenza) + 1) * cadenza
    return float(scatti[-1] + prossima - trascorsi)


def frequenza(
    riga: Mapping[str, Any], *, scenario: str = "bilanciato", oggi: date_cls | None = None,
) -> float | None:
    """Giorni nominali al prossimo controllo (prima di volatilita' e jitter)."""
    nome = _scenario(scenario)
    corrente = fase(riga, oggi=oggi)
    if corrente == FASE_REVOCATO:
        return None
    if corrente == FASE_CHIUSO:
        return giorni_chiuso(riga, nome, oggi=oggi)
    return FREQUENZE[nome][corrente]


def moltiplicatore_volatilita(
    corrente: float | None = None,
    *,
    eventi_verificati: int = 0,
    controlli_senza_diff: int = 0,
) -> float:
    """Il moltiplicatore `m` di §6.2, sempre dentro [0,5; 2,0].

    Un bando che cambia spesso si guarda piu' spesso; uno che non cambia mai si
    guarda meno. I limiti esistono perche' senza di essi un bando fermo da un
    anno finirebbe a una cadenza in cui non lo si ricontrolla piu'.
    """
    m = 1.0 if corrente is None else float(corrente)
    if eventi_verificati > 0:
        m *= VOLATILITA_EVENTO
    if controlli_senza_diff >= CONTROLLI_PER_CALMA:
        m *= VOLATILITA_CALMA
    return max(VOLATILITA_MIN, min(VOLATILITA_MAX, round(m, 4)))


def priorita(riga: Mapping[str, Any], *, oggi: date_cls | None = None) -> int:
    """Priorita' 0-100 del bando nella coda dei controlli (§6.2)."""
    punteggio = PRIORITA_FASE.get(fase(riga, oggi=oggi), 30)
    if riga.get("segnale_fonte"):
        punteggio += BONUS_SEGNALE_FONTE
    if riga.get("evento_in_attesa"):
        punteggio += BONUS_EVENTO_IN_ATTESA
    if riga.get("segnale_macchina"):
        punteggio += BONUS_SEGNALE_MACCHINA
    # Una priorita' gia' scritta dai segnali C (90 per `deadline_label`) non va
    # abbassata dalla fase: e' l'informazione piu' fresca che abbiamo.
    dichiarata = riga.get("priorita_controllo")
    try:
        punteggio = max(punteggio, int(dichiarata))
    except (TypeError, ValueError):
        pass
    return max(0, min(100, punteggio))


def prossimo_controllo(
    riga: Mapping[str, Any],
    *,
    scenario: str = "bilanciato",
    adesso: datetime | None = None,
    casuale: Callable[[], float] | None = None,
    semina: bool = False,
) -> datetime | None:
    """Istante del prossimo controllo, con jitter.

    Due dispersioni diverse, e la differenza e' la ragione per cui il piano
    sta in piedi:

      * **a regime** (`semina=False`) il jitter e' uniforme +-25 % attorno alla
        cadenza. Serve a non far ricadere insieme bandi che si erano gia'
        sparpagliati;
      * **alla semina** (`semina=True`, L6) la dispersione e' sull'INTERO
        periodo, cioe' `adesso + U(0, cadenza)`. Qui la coorte parte tutta
        dallo stesso istante: con il solo +-25 % i 416 bandi a sportello si
        distribuirebbero su una finestra di 1,5 giorni e mezza coorte cadrebbe
        comunque nello stesso giorno. §6.2 chiede che «nessun giorno superi il
        40 % della coorte», e solo la dispersione piena lo ottiene. E' anche
        la scelta piu' prudente delle due: sparpaglia di piu', non di meno, e
        nessun bando viene controllato piu' tardi della sua cadenza.

    `casuale()` restituisce un numero in [0, 1) ed e' iniettabile: il test
    della coorte di 416 deve poter riprodurre la distribuzione.

    Il giorno della scadenza, se l'ora e' nota, il controllo si mette **dopo**
    quell'ora: e' l'unico momento in cui la differenza fra «scaduto» e «non
    ancora scaduto» si gioca sulle ore, e controllare prima non direbbe niente.
    """
    momento = adesso_roma(adesso)
    giorni = frequenza(riga, scenario=scenario, oggi=momento.date())
    if giorni is None:
        return None

    m = moltiplicatore_volatilita(
        riga.get("volatilita"),
        eventi_verificati=int(riga.get("eventi_verificati") or 0),
        controlli_senza_diff=int(riga.get("controlli_senza_diff") or 0),
    )
    base = max(0.25, float(giorni) * m)
    sorteggio = (casuale or random.random)()
    fattore = sorteggio if semina else 1.0 + JITTER * (2.0 * sorteggio - 1.0)
    quando = momento + timedelta(days=base * fattore)

    scadenza = _data(riga.get("data_scadenza"))
    ora = riga.get("ora_scadenza")
    if scadenza is not None and isinstance(ora, str) and len(ora) >= 5:
        giorno_scadenza = adesso_roma(
            datetime.combine(scadenza, datetime.min.time())).replace(
            hour=int(ora[:2]), minute=int(ora[3:5]))
        dopo_ora = giorno_scadenza + timedelta(minutes=15)
        if momento < dopo_ora <= quando:
            return dopo_ora
    return quando


def prossimo_dopo_errore(controlli_falliti: int, *, adesso: datetime | None = None) -> datetime:
    """Backoff esponenziale sugli errori: `now + min(6h x 2^n, 7 giorni)`."""
    n = max(0, int(controlli_falliti))
    ore = min(BACKOFF_BASE_ORE * (2 ** n), BACKOFF_MASSIMO_ORE)
    return adesso_roma(adesso) + timedelta(hours=ore)


def selezionabile(riga: Mapping[str, Any], *, adesso: datetime | None = None) -> bool:
    """Il bando entra nella coda dei controlli? (§6.2, A33)

    Quattro condizioni. La terza e' quella che tiene fuori i «solo-OE»: un
    bando la cui fonte ufficiale non e' `trovata` **non** si fetcha dal monitor,
    perche' l'unico URL che abbiamo e' quello dell'aggregatore. Quei bandi li
    ripassa il resolver, alla sua cadenza.
    """
    if not riga.get("pubblicato", True):
        return False
    if riga.get("bando_master_id") is not None:
        return False
    if riga.get("fonte_ufficiale_stato") != STATO_FONTE_TROVATA:
        return False
    quando = _istante(riga.get("prossimo_controllo_at"))
    if quando is not None and quando > adesso_roma(adesso):
        return False
    return True


def seleziona(
    righe: Iterable[Mapping[str, Any]],
    *,
    tetto: int = 0,
    adesso: datetime | None = None,
) -> tuple[Mapping[str, Any], ...]:
    """I bandi da controllare in questo giro, nell'ordine di §6.2.

    `ORDER BY priorita DESC, prossimo_controllo_at, id`: la priorita' decide
    chi entra quando il tetto morde, e `id` e' il tiebreak che rende l'ordine
    riproducibile (senza, due giri con lo stesso timestamp NULL scelgono
    bandi diversi, come gia' succede su `data_pubblicazione`).
    """
    momento = adesso_roma(adesso)
    ammessi = [r for r in righe if selezionabile(r, adesso=momento)]
    lontano = momento + timedelta(days=3650)

    def chiave(riga: Mapping[str, Any]) -> tuple[int, str, int]:
        quando = _istante(riga.get("prossimo_controllo_at")) or lontano
        try:
            identificativo = int(riga.get("id") or 0)
        except (TypeError, ValueError):
            identificativo = 0
        return (-priorita(riga, oggi=momento.date()), quando.isoformat(), identificativo)

    ordinati = sorted(ammessi, key=chiave)
    return tuple(ordinati[:tetto] if tetto and tetto > 0 else ordinati)


def _motivo_prevalente(esiti: Sequence[Any]) -> str:
    """Il motivo piu' ricorrente fra quelli dichiarati. Stringa vuota se nessuno.

    Serve al riepilogo: «saltati: 50» senza il perche' non distingue un giro
    senza rete da un giro senza credenziali.
    """
    conteggio: dict[str, int] = {}
    for esito in esiti:
        motivo = str(getattr(esito, "motivo", "") or "")
        if motivo:
            conteggio[motivo] = conteggio.get(motivo, 0) + 1
    if not conteggio:
        return ""
    return max(conteggio.items(), key=lambda voce: voce[1])[0]


# --- I/O iniettabile --------------------------------------------------------

@dataclass
class FonteDati:
    """Confine di I/O del monitor. La versione base non tocca niente.

    Esiste perche' le migrazioni non sono applicate: `bando_controllo` non c'e'
    ancora, e il monitor deve poter essere rilasciato lo stesso. La versione
    reale (`FonteDatiSupabase`) si costruisce con `da_db()` e degrada da sola
    se le colonne non esistono.
    """

    righe: list[dict[str, Any]] = field(default_factory=list)
    eventi: dict[Any, list[dict[str, Any]]] = field(default_factory=dict)
    consumo: dict[str, float] = field(default_factory=dict)
    scritture: list[tuple[Any, dict[str, Any]]] = field(default_factory=list)
    registrati: list[dict[str, Any]] = field(default_factory=list)
    #: Allarmi raccolti durante la selezione (§6.2): finiscono nel riepilogo e
    #: quindi in `pipeline_run`, non solo in una riga di log che nessuno rilegge.
    allarmi: list[str] = field(default_factory=list)

    def disponibile(self) -> tuple[bool, str]:
        return True, ""

    def candidati(self, *, limite: int = 0, adesso: datetime | None = None) -> list[dict[str, Any]]:
        return [dict(r) for r in seleziona(self.righe, tetto=limite, adesso=adesso)]

    def eventi_recenti(self, bando_id: Any, giorni: int = 30) -> list[dict[str, Any]]:
        return list(self.eventi.get(bando_id, ()))

    def consumo_oggi(self) -> dict[str, float]:
        return dict(self.consumo)

    def salva_controllo(self, bando_id: Any, payload: dict[str, Any]) -> bool:
        self.scritture.append((bando_id, dict(payload)))
        return True

    def registra_evento(self, riga: Mapping[str, Any]) -> bool:
        self.registrati.append(dict(riga))
        return True


class FonteDatiSupabase(FonteDati):
    """Versione reale: passa sempre da `db.controllo` e non solleva mai.

    Tutti e cinque i metodi di `FonteDati` sono ridefiniti. Ereditarne anche
    uno solo sarebbe peggio che non averlo: la versione base accoda in una
    lista in memoria e ritorna `True`, quindi il giro direbbe «salvato,
    registrato» e il giro successivo non troverebbe ne' baseline ne' eventi,
    rendendo impossibile il diff — cioe' uno step muto che si dichiara vivo.
    """

    def __init__(self, controllo: Any = None, client: Any = None) -> None:
        super().__init__()
        self._controllo = controllo
        self._client = client

    def _adattatore(self) -> Any:
        if self._controllo is None:
            from .db import controllo
            self._controllo = controllo
        return self._controllo

    def disponibile(self) -> tuple[bool, str]:
        try:
            if not self._adattatore().ha_tutte("bando_controllo", COLONNE_CONTROLLO):
                return False, "colonne_assenti"
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[monitor] controllo dello schema fallito: {}", e)
            return False, "colonne_assenti"
        return True, ""

    def candidati(self, *, limite: int = 0, adesso: datetime | None = None) -> list[dict[str, Any]]:
        """I bandi del giro: `bando` + `bando_controllo`, ordinati da `seleziona`.

        Due letture e non un embed: la RLS di `bando_controllo` non concede il
        join, e `select_controlli` e' gia' la lettura per id.
        """
        from . import db
        # La lista riparte a ogni selezione: la stessa istanza puo' servire
        # due giri, e un allarme del giro scorso non e' un allarme di questo.
        self.allarmi = []
        try:
            righe = db.select_bandi_da_monitorare(
                client=self._client, strumento=self._adattatore())
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[monitor] lettura dei candidati fallita: {}", e)
            return []
        if len(righe) >= db.TETTO_CODA_MONITOR:
            # Il tetto di lettura ha morso: da qui in giu' la selezione per
            # priorita' sta ordinando una FETTA del corpus, non il corpus.
            # `db` lo scriveva solo nel log; qui diventa un allarme del giro.
            self.allarmi.append(db.ALLARME_CODA_TRONCATA)
        if not righe:
            return []
        try:
            controlli = db.select_controlli(
                [r.get("id") for r in righe],
                client=self._client, strumento=self._adattatore())
        except Exception as e:                            # pragma: no cover - ripiego
            # Senza le colonne calde ogni riga sembra «mai controllata» e
            # l'intero corpus entrerebbe in coda: meglio nessun candidato.
            logger.warning("[monitor] lettura di bando_controllo fallita: {}", e)
            return []
        unite = [dict(r, **dict(controlli.get(r.get("id")) or {})) for r in righe]
        scelte = [dict(r) for r in seleziona(unite, tetto=limite, adesso=adesso)]
        return self._con_memoria(scelte)

    def _con_memoria(self, scelte: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Aggiunge alle righe scelte le colonne CALDE di `bando_controllo`.

        Si legge in due tempi apposta: la prima lettura regge la coda ed e'
        leggera, questa porta la **memoria** del monitor (`testo_norm`, che e'
        `bytea` e su 1 683 righe pesa decine di MB, l'impronta, l'ETag,
        `controlli_falliti`) e si paga sulle sole righe che il giro lavorera'
        davvero. E' lo stesso schema dello scorrimento: si filtra sul leggero e
        si paga il peso solo su cio' che si lavora.

        Senza questa seconda lettura ogni giro ripartiva da zero: nessun
        «prima» quindi ogni controllo in variante G2', nessun 304 possibile, e
        soprattutto `controlli_falliti` sempre 1 — la promessa «cinque
        fallimenti e il bando esce dalla coda» non si avverava mai.

        **`volatilita` non si rilegge**, e non e' una dimenticanza. Il
        moltiplicatore ha due direzioni: un evento verificato lo abbassa
        (`VOLATILITA_EVENTO`), tre controlli senza diff lo rialzano
        (`VOLATILITA_CALMA`). La seconda non funziona: `controlli_senza_diff`
        **non esiste** in `bando_controllo` (02:1138-1163), `aggiorna_controllo`
        la scarta in silenzio e alla rilettura vale sempre 0, cioe' sotto la
        soglia di `CONTROLLI_PER_CALMA`. Rileggere la sola volatilita' fa
        comporre `m *= 0,7` giro dopo giro fino al pavimento `VOLATILITA_MIN`,
        e nulla puo' piu' riportarla su: ogni bando cambiato due volte
        resterebbe controllato al doppio della frequenza **per sempre**, cioe'
        piu' fetch e piu' classificazioni sul tetto giornaliero in dollari.
        Senza la rilettura si riparte da 1,0 a ogni giro e il peggio e' 0,7.
        Il giorno in cui `controlli_senza_diff` sara' in tabella (una
        migrazione che qui non si scrive), la colonna torna in questo elenco e
        la memoria della volatilita' ridiventa corretta.
        """
        if not scelte:
            return scelte
        from . import db
        try:
            calde = db.select_controlli(
                [r.get("id") for r in scelte],
                colonne=COLONNE_CONTROLLO,
                client=self._client, strumento=self._adattatore())
        except Exception as e:                            # pragma: no cover - ripiego
            # Degradare qui significa «giro senza memoria», che e' il
            # comportamento di prima: si dice e si prosegue, non si buttano
            # via i candidati.
            logger.warning("[monitor] memoria di bando_controllo non letta: {}", e)
            self.allarmi.append(ALLARME_MEMORIA_ASSENTE)
            return scelte
        return [dict(r, **dict(calde.get(r.get("id")) or {})) for r in scelte]

    def eventi_recenti(self, bando_id: Any, giorni: int = 30) -> list[dict[str, Any]]:
        """Gli eventi recenti del bando: e' la memoria su cui lavora il G8."""
        from . import db
        try:
            return list(db.select_eventi(
                bando_id=bando_id,
                dal=(adesso_roma() - timedelta(days=max(0, int(giorni)))).date(),
                client=self._client, strumento=self._adattatore()))
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[monitor] eventi recenti del bando {}: {}", bando_id, e)
            return []

    def consumo_oggi(self) -> dict[str, float]:
        from . import db
        try:
            return db.consumo_oggi(client=self._client, strumento=self._adattatore())
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[monitor] consumo di oggi non leggibile: {}", e)
            return {}

    def salva_controllo(self, bando_id: Any, payload: dict[str, Any]) -> bool:
        from . import db
        try:
            esito = db.aggiorna_controllo(
                bando_id, payload, client=self._client, strumento=self._adattatore())
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[monitor] salvataggio del controllo {}: {}", bando_id, e)
            return False
        return bool(esito.get("scritto"))

    def registra_evento(self, riga: Mapping[str, Any]) -> bool:
        from . import db
        try:
            return bool(db.registra_evento(
                riga, client=self._client, strumento=self._adattatore()))
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[monitor] evento {} non registrato: {}", riga.get("tipo"), e)
            return False


def da_db() -> FonteDati:
    """La fonte dati di produzione."""
    return FonteDatiSupabase()


# --- esito di un singolo controllo ------------------------------------------

@dataclass
class EsitoControllo:
    """Che cosa e' successo su un bando. E' anche la riga del report d'ombra."""
    bando_id: Any = None
    fase: str = ""
    esito: str = "ok"            # ok | 304 | invariato | errore | saltato
    motivo: str = ""
    fetch: int = 0
    diff_rilevante: bool = False
    classificato: bool = False
    eventi: tuple[dict[str, Any], ...] = ()
    respinti: tuple[dict[str, Any], ...] = ()
    slug: str | None = None
    prossimo: datetime | None = None
    #: Le colonne di **`bando_controllo`**: sono quelle che `_salva` scrive.
    colonne: dict[str, Any] = field(default_factory=dict)
    #: Le colonne di **`bando`** che gli eventi ammessi scriverebbero
    #: (`eventi.colonne_da_evento`). Stanno separate perche' sono di un'altra
    #: tabella e le scrive un'altra strada — la RPC `bando_registra_evento`,
    #: dentro `eventi.applica`. Mescolarle in `colonne` mandava `data_apertura`
    #: e `stato_bando` nell'upsert di `bando_controllo`, dove non esistono: a
    #: salvarci era solo il filtro di `db.controllo`, che le scartava in
    #: silenzio. Qui restano leggibili per il report d'ombra senza dipendere
    #: da quel filtro.
    colonne_bando: dict[str, Any] = field(default_factory=dict)
    # Aggiornamenti per `bando_link` dal pre-filtro HEAD (§6.2, §13.4).
    allegati: list[dict[str, Any]] = field(default_factory=list)
    # Rigenerazione mirata: `da_rigenerare` dice che una data in prosa e'
    # diventata falsa, `rigenerazioni` che cosa ha fatto il rigeneratore.
    # La differenza fra le due decide se lo slug va a IndexNow.
    da_rigenerare: bool = False
    rigenerazioni: tuple[dict[str, Any], ...] = ()

    @property
    def rigenerato(self) -> bool:
        """Vero se almeno una rigenerazione e' arrivata in fondo.

        «In fondo» comprende il ripiego sul box templato (`via="box"`): §6.2
        lo considera un esito legittimo, non un fallimento — il contenuto
        resta vecchio ma coerente, e il box dichiara la data nuova.
        """
        return any(
            bool(r.get("scritto")) or str(r.get("via") or "") == "box"
            for r in self.rigenerazioni
        )

    def come_dizionario(self) -> dict[str, Any]:
        return {
            "bando_id": self.bando_id,
            "fase": self.fase,
            "esito": self.esito,
            "motivo": self.motivo,
            "fetch": self.fetch,
            "diff_rilevante": self.diff_rilevante,
            "classificato": self.classificato,
            "eventi": [dict(e) for e in self.eventi],
            "respinti": [dict(e) for e in self.respinti],
            "allegati": [dict(a) for a in self.allegati],
            "da_rigenerare": self.da_rigenerare,
            "colonne_bando": dict(self.colonne_bando),
            "rigenerazioni": [dict(r) for r in self.rigenerazioni],
            "slug": self.slug,
            "prossimo": self.prossimo.isoformat() if self.prossimo else None,
        }


async def controlla(
    riga: Mapping[str, Any],
    *,
    scarica: Callable[..., Awaitable[Any]],
    classifica: Callable[[eventi_mod.Contesto], Awaitable[Sequence[eventi_mod.Evento]]] | None = None,
    seconda_opinione: Callable[[eventi_mod.Contesto], Awaitable[eventi_mod.Evento | None]] | None = None,
    pagine_collegate: Callable[[Mapping[str, Any]], Awaitable[Sequence[str]]] | None = None,
    rigenerazione: Callable[..., Awaitable[Any]] | None = None,
    fonte_dati: FonteDati | None = None,
    segnale_macchina: Callable[[Mapping[str, Any]], Awaitable[bool | None]] | None = None,
    head_allegati: Callable[[Mapping[str, Any]], Awaitable[Sequence[Any]]] | None = None,
    modalita: str = eventi_mod.MODALITA_OMBRA,
    scenario: str = "bilanciato",
    stati_estesi: bool = False,
    tabella_domini: Any = None,
    adesso: datetime | None = None,
    casuale: Callable[[], float] | None = None,
    dry_run: bool = False,
) -> EsitoControllo:
    """Un controllo completo su un bando. Non solleva mai.

    L'ordine dei passi e' l'ordine dei costi: prima cio' che e' gratis.

    `dry_run=True` legge tutto e **non scrive niente**: ne' `bando_controllo`
    ne' gli eventi interni. E' cio' che il vincolo del committente chiede a
    ogni sottocomando che scrive, e non coincide con la modalita' ombra —
    l'ombra registra gli eventi per misurarne la precisione, il dry-run no.
    """
    momento = adesso_roma(adesso)
    corrente = fase(riga, oggi=momento.date())
    esito = EsitoControllo(bando_id=riga.get("id"), fase=corrente, slug=riga.get("slug"))
    # Le scritture passano da qui: in dry-run non c'e' nessun destinatario, ma
    # le letture (`eventi_recenti`, per il G8) restano quelle vere.
    scrittore = None if dry_run else fonte_dati
    url = str(riga.get("fonte_ufficiale_url") or "")
    if not url:
        esito.esito = "saltato"
        esito.motivo = "nessuna fonte ufficiale"
        return esito

    # 0. nessun classificatore, nessun controllo. La verifica sta PRIMA del
    #    fetch di proposito: un giro senza modello non deve pagare una GET per
    #    riga (e, sugli host `richiede_js`, un credito Firecrawl) per poi
    #    buttare via la pagina. E non si scrive nemmeno la baseline: avanzare
    #    l'impronta qui perderebbe per sempre il cambiamento appena visto.
    if classifica is None:
        esito.esito = "saltato"
        esito.motivo = "nessun classificatore disponibile"
        return esito

    # 1. segnale macchina per host: 0 crediti, 0 LLM. `False` significa «la
    #    fonte dichiara che non e' cambiato niente»: si smette qui.
    if segnale_macchina is not None:
        try:
            cambiato = await segnale_macchina(riga)
        except Exception as e:
            logger.debug("[monitor] segnale macchina fallito per {}: {}", riga.get("id"), e)
            cambiato = None
        if cambiato is False:
            esito.esito = "invariato"
            esito.motivo = "segnale macchina: nessuna modifica"
            esito.prossimo = prossimo_controllo(
                riga, scenario=scenario, adesso=momento, casuale=casuale)
            esito.colonne = _colonne_invariato(riga, esito.prossimo, momento)
            _salva(scrittore, esito)
            return esito

    # 1-bis. HEAD sugli allegati gia' pubblicati: una richiesta per documento,
    #        zero token. Un 404 toglie subito la riga da `pubblicabile`, perche'
    #        §13.4 promette che ogni riga leggibile ha risposto 2xx all'ultimo
    #        controllo — e quella promessa non aspetta la lettura della pagina.
    if head_allegati is not None:
        try:
            esiti_allegati = list(await head_allegati(riga))
        except Exception as e:
            logger.debug("[monitor] HEAD sugli allegati fallita per {}: {}", riga.get("id"), e)
            esiti_allegati = []
        esito.allegati, interni = controlla_allegati(riga, esiti_allegati)
        if scrittore is not None:
            for interno in interni:
                scrittore.registra_evento(interno)

    # 2. GET condizionale: un 304 costa zero e chiude il controllo.
    try:
        risposta = await scarica(
            url,
            principale=True,
            etag=riga.get("etag"),
            modificata_dopo=riga.get("last_modified"),
        )
    except Exception as e:
        return _errore(riga, esito, str(e), momento, scrittore, modalita)

    esito.fetch = 1
    stato_http = getattr(risposta, "stato", None)
    if stato_http == 304:
        esito.esito = "304"
        esito.prossimo = prossimo_controllo(riga, scenario=scenario, adesso=momento, casuale=casuale)
        # Niente corpo, quindi niente `testo_norm`: si rinfrescano solo le
        # testate, che un 304 puo' comunque aggiornare.
        esito.colonne = _colonne_invariato(
            riga, esito.prossimo, momento, risposta=risposta)
        _salva(scrittore, esito)
        return esito
    if stato_http is not None and (stato_http >= 500 or stato_http == 429):
        return _errore(riga, esito, f"HTTP {stato_http}", momento, scrittore, modalita)
    if not getattr(risposta, "ok", False) or getattr(risposta, "vuota", True):
        return _errore(riga, esito, f"risposta inutilizzabile (HTTP {stato_http})",
                       momento, scrittore, modalita)

    # 3. impronta e diff: ancora zero crediti, zero token.
    contenuto = getattr(risposta, "html", "") or getattr(risposta, "testo", "")
    impronta_nuova = impronte.impronta_contenuto(contenuto)
    testo_dopo = impronte.testo_normalizzato(contenuto)
    sezioni_dopo = impronte.impronte_sezioni(contenuto)
    testo_prima = testo_da_colonna(riga.get("testo_norm"))
    if impronta_nuova == riga.get("impronta_contenuto") and testo_prima is not None:
        esito.esito = "invariato"
        esito.prossimo = prossimo_controllo(riga, scenario=scenario, adesso=momento, casuale=casuale)
        esito.colonne = _colonne_invariato(
            riga, esito.prossimo, momento, impronta=impronta_nuova,
            risposta=risposta, testo=testo_dopo, sezioni=sezioni_dopo)
        _salva(scrittore, esito)
        return esito

    diff = impronte.diff_sezioni(testo_prima, contenuto, oggi=momento.date())
    esito.diff_rilevante = bool(diff.rilevante) or testo_prima is None
    if not esito.diff_rilevante:
        esito.esito = "invariato"
        esito.motivo = "diff classificato come rumore"
        esito.prossimo = prossimo_controllo(riga, scenario=scenario, adesso=momento, casuale=casuale)
        esito.colonne = _colonne_invariato(
            riga, esito.prossimo, momento, impronta=impronta_nuova,
            risposta=risposta, testo=testo_dopo, sezioni=sezioni_dopo)
        _salva(scrittore, esito)
        return esito

    # 4. pagine collegate (massimo 2, httpx-only): servono al G4 e al G7.
    pagine = [eventi_mod.Pagina(
        url=url,
        testo=testo_dopo,
        impronta=impronta_nuova,
    )]
    if pagine_collegate is not None:
        try:
            collegate = list(await pagine_collegate(riga))[:MAX_PAGINE_COLLEGATE]
        except Exception as e:
            logger.debug("[monitor] pagine collegate fallite per {}: {}", riga.get("id"), e)
            collegate = []
        for collegato in collegate:
            # La scheda del bando non puo' rientrare come pagina collegata:
            # sarebbe la conferma di se stessa (vedi `_prove_da_pagine`), e il
            # G7 — il gate per cui tutto questo esiste — si soddisferebbe con
            # la pagina che ha generato l'evento. La guardia sta anche
            # nell'adattatore, ma la difesa dell'invariante appartiene a chi lo
            # dichiara: qui arriva anche cio' che scrive un altro chiamante.
            if _stessa_pagina(collegato, url):
                logger.debug(
                    "[monitor] pagina collegata {} e' la scheda stessa: scartata",
                    collegato)
                continue
            try:
                secondaria = await scarica(collegato, principale=False)
            except Exception:
                continue
            if not getattr(secondaria, "ok", False):
                continue
            testo = getattr(secondaria, "testo", "") or ""
            pagine.append(eventi_mod.Pagina(
                url=collegato,
                testo=testo,
                impronta=impronte.impronta_contenuto(testo),
                collegata=True,
            ))
            esito.fetch += 1

    # Prove indipendenti per il G7: le coppie (data, ruolo) lette dalle pagine
    # COLLEGATE, non dalla scheda. E' la definizione di «indipendente»: una
    # seconda pagina, scaricata davvero, che dice la stessa cosa. Le date della
    # scheda non entrano qui, altrimenti la pagina confermerebbe se stessa.
    prove = list(_prove(riga)) + _prove_da_pagine(pagine)

    ctx = eventi_mod.Contesto(
        bando_id=riga.get("id"),
        stato_bando=riga.get("stato_bando"),
        data_apertura=_data(riga.get("data_apertura")),
        data_scadenza=_data(riga.get("data_scadenza")),
        data_pubblicazione=_data(riga.get("data_pubblicazione")),
        ora_scadenza=riga.get("ora_scadenza"),
        pagine=tuple(pagine),
        diff=diff,
        testo_prima=testo_prima,
        eventi_recenti=tuple(
            (fonte_dati.eventi_recenti(riga.get("id")) if fonte_dati else ()) or ()),
        prove=tuple(prove),
        tabella_domini=tabella_domini,
        oggi=momento.date(),
        stati_estesi=stati_estesi,
        modalita=modalita,
    )

    try:
        proposte = list(await classifica(ctx))
    except Exception as e:
        logger.warning("[monitor] classificazione fallita per {}: {}", riga.get("id"), e)
        proposte = []
    esito.classificato = True

    if proposte and seconda_opinione is not None:
        try:
            ctx = replace_contesto(ctx, seconda_opinione=await seconda_opinione(ctx))
        except Exception as e:
            logger.debug("[monitor] seconda opinione fallita per {}: {}", riga.get("id"), e)

    ammessi: list[dict[str, Any]] = []
    respinti: list[dict[str, Any]] = []
    colonne: dict[str, Any] = {}
    date_cambiate: list[tuple[dict[str, Any], str, date_cls | None, date_cls]] = []
    for proposta in ordina_proposte(proposte):
        applicazione = eventi_mod.applica(proposta, ctx)
        voce = applicazione.come_dizionario()
        if applicazione.giudizio and applicazione.giudizio.ammesso:
            ammessi.append(voce)
            date_cambiate.extend(
                _date_da_rigenerare(ctx, applicazione.colonne, applicazione.riga))
            colonne.update(applicazione.colonne)
            # Il contesto avanza con l'evento appena accettato: il prossimo
            # deve essere giudicato sulle date NUOVE, non su quelle vecchie, e
            # deve vedere questo evento fra i recenti — senza, due proposte
            # identiche nella stessa risposta superano entrambe il G8 e il box
            # «Aggiornamenti» mostra due volte la stessa notizia.
            ctx = _ctx_aggiornato(ctx, applicazione.colonne, applicazione.riga)
            if scrittore is not None:
                scrittore.registra_evento(applicazione.riga)
        else:
            respinti.append(voce)
            # I respinti vanno **a DB**, non solo nel riepilogo del giro.
            # Difetto misurato il 24/09/2026 sulla semina: 390 classificazioni
            # pagate 5,17 dollari, 691 proposte, **zero** eventi registrati, e
            # `report-ombra` lanciato dopo non trova niente da misurare perche'
            # legge `bando_evento`. Il periodo d'ombra esiste per calcolare la
            # precisione su almeno cento eventi: se i respinti muoiono con il
            # processo, si spende a ogni giro senza imparare nulla, e i gate che
            # respingono restano ignoti.
            #
            # La riga e' già innocua per costruzione (`riga_evento`):
            # `verificato=false` la esclude da `applicabile()`, `leggibile=false`
            # le nega il cursore e quindi la RLS di anon, e `gate` porta quale
            # gate ha respinto — che e' l'unica informazione utile.
            if scrittore is not None and len(respinti) <= RESPINTI_A_DB_PER_BANDO:
                scrittore.registra_evento(applicazione.riga)

    esito.eventi = tuple(ammessi)
    esito.respinti = tuple(respinti)
    esito.da_rigenerare = bool(date_cambiate)
    esito.prossimo = prossimo_controllo(
        dict(riga, eventi_verificati=len(ammessi)),
        scenario=scenario, adesso=momento, casuale=casuale,
    )
    esito.colonne = _colonne_invariato(
        riga, esito.prossimo, momento, impronta=impronta_nuova, cambiato=True,
        risposta=risposta, testo=testo_dopo, sezioni=sezioni_dopo)
    # Le colonne degli eventi sono di `bando`, non di `bando_controllo`: qui
    # restano separate e non finiscono nell'upsert delle colonne calde. A
    # scriverle e' la RPC dentro `eventi.applica`, che e' gia' passata.
    esito.colonne_bando = dict(colonne)
    _salva(scrittore, esito)

    # 5. rigenerazione mirata: la prosa deve dire la stessa data delle colonne.
    #    Solo in attivo, solo sulle date, e solo se il chiamante ha fornito il
    #    punto di iniezione. Senza, `run()` non mette lo slug fra quelli da
    #    notificare: avvisare Google di una pagina rimasta com'era e' peggio
    #    che non avvisarlo.
    if date_cambiate and rigenerazione is not None and modalita == eventi_mod.MODALITA_ATTIVO \
            and not dry_run:
        # Le rigenerazioni si INCATENANO. Il differimento arriva in coppia
        # (apertura e scadenza): se la seconda ripartisse dal contenuto
        # originale sovrascriverebbe la prima, e l'ultima scrittura
        # vincerebbe — cioe' una delle due date resterebbe vecchia in prosa
        # proprio mentre la colonna dice il contrario.
        corrente_riga = dict(riga)
        for evento_riga, ruolo, vecchia, nuova in date_cambiate:
            try:
                prodotto = await rigenerazione(
                    corrente_riga, evento_riga, vecchia=vecchia, nuova=nuova, ruolo=ruolo)
            except Exception as e:
                logger.warning("[monitor] rigenerazione del bando {} fallita: {}",
                               riga.get("id"), e)
                continue
            esito.rigenerazioni = esito.rigenerazioni + (_esito_rigenerazione(prodotto),)
            corrente_riga.update(_payload_rigenerazione(prodotto))
    return esito


def _payload_rigenerazione(prodotto: Any) -> dict[str, Any]:
    """I campi che la rigenerazione ha riscritto (`contenuto`, `descrizione_breve`).

    Servono alla rigenerazione successiva, che deve partire dal testo gia'
    aggiornato e non da quello in archivio.
    """
    payload = getattr(prodotto, "payload", None)
    if payload is None and isinstance(prodotto, Mapping):
        payload = prodotto.get("payload")
    return dict(payload) if isinstance(payload, Mapping) else {}


def _date_da_rigenerare(
    ctx: eventi_mod.Contesto,
    colonne: Mapping[str, Any],
    riga_evento: Mapping[str, Any] | None = None,
) -> list[tuple[dict[str, Any], str, date_cls | None, date_cls]]:
    """(riga evento, ruolo, data vecchia, data nuova) per ogni data scritta.

    Solo `data_apertura` e `data_scadenza`: sono le due che compaiono in prosa
    e le uniche che, se restano vecchie nel testo, fanno dire alla pagina il
    contrario delle sue colonne.
    """
    trovate: list[tuple[dict[str, Any], str, date_cls | None, date_cls]] = []
    for colonna, ruolo, prima in (
        ("data_apertura", "apertura", ctx.data_apertura),
        ("data_scadenza", "scadenza", ctx.data_scadenza),
    ):
        nuova = _data(colonne.get(colonna))
        if nuova is None or nuova == prima:
            continue
        trovate.append((dict(riga_evento or {}), ruolo, prima, nuova))
    return trovate


def _esito_rigenerazione(prodotto: Any) -> dict[str, Any]:
    """Normalizza cio' che il rigeneratore ha restituito (dizionario o oggetto)."""
    if isinstance(prodotto, Mapping):
        return dict(prodotto)
    come = getattr(prodotto, "come_dizionario", None)
    if callable(come):
        try:
            return dict(come())
        except Exception:                                 # pragma: no cover - ripiego
            pass
    return {"scritto": bool(getattr(prodotto, "scritto", False)),
            "via": str(getattr(prodotto, "via", "") or "")}


def replace_contesto(ctx: eventi_mod.Contesto, **campi: Any) -> eventi_mod.Contesto:
    """`dataclasses.replace` su `Contesto`, isolato per leggibilita'."""
    from dataclasses import replace as _replace
    return _replace(ctx, **campi)


def ordina_proposte(
    proposte: Sequence[eventi_mod.Evento],
) -> tuple[eventi_mod.Evento, ...]:
    """Ordina gli eventi di un controllo dalla data piu' lontana alla piu' vicina.

    Serve al caso reale del differimento, che arriva **in coppia**: apertura al
    22 ottobre e scadenza al 1° dicembre. Valutando prima l'apertura, il gate
    G5 la confronterebbe con la scadenza ancora in colonna (6 ottobre) e la
    respingerebbe per incoerenza — pur essendo la lettura giusta. Valutando
    prima la scadenza, ogni evento successivo trova in contesto le date gia'
    aggiornate e la coppia passa intera.

    Non e' una scorciatoia: ogni evento deve comunque superare i nove gate per
    conto suo, e l'ordine non ne salta nessuno.
    """
    con_data: list[tuple[date_cls, int, eventi_mod.Evento]] = []
    senza_data: list[eventi_mod.Evento] = []
    for indice, evento in enumerate(proposte):
        data = evento.data_valore or evento.data_evento
        if data is None:
            # Gli eventi senza data (sospensione, revoca, FAQ) restano in coda,
            # nell'ordine in cui il modello li ha emessi.
            senza_data.append(evento)
        else:
            con_data.append((data, indice, evento))
    # Data decrescente, poi ordine originale: l'ordinamento e' deterministico.
    con_data.sort(key=lambda voce: (-voce[0].toordinal(), voce[1]))
    return tuple([e for _, _, e in con_data] + senza_data)


def _ctx_aggiornato(
    ctx: eventi_mod.Contesto,
    colonne: Mapping[str, Any],
    riga_evento: Mapping[str, Any] | None = None,
) -> eventi_mod.Contesto:
    """Contesto con le date, lo stato e l'evento appena accettati.

    L'evento entra fra i «recenti» perche' il G8 deve poter deduplicare anche
    **dentro** il giro: due proposte `faq` identiche nella stessa risposta del
    modello passano entrambe il G2 (basta il link nuovo) e non hanno una data
    che il G5 possa usare per respingere la seconda.
    """
    campi: dict[str, Any] = {}
    if "data_apertura" in colonne:
        campi["data_apertura"] = _data(colonne["data_apertura"])
    if "data_scadenza" in colonne:
        campi["data_scadenza"] = _data(colonne["data_scadenza"])
    if "stato_bando" in colonne:
        campi["stato_bando"] = colonne["stato_bando"]
    if riga_evento:
        campi["eventi_recenti"] = ctx.eventi_recenti + (dict(riga_evento),)
    return replace_contesto(ctx, **campi) if campi else ctx


def news_url_per_host() -> dict[str, str]:
    """`host -> news_url` dalle voci del registro (§6.2, pagine collegate).

    L'endpoint e' **per host**, non per fonte: due voci dello stesso host (la
    pagina FESR e l'indice dei bandi di lazioeuropa) condividono la stessa REST
    API, e una GET per giro le copre entrambe. Interrogare due volte lo stesso
    endpoint sarebbe un fetch buttato a ogni giro.
    """
    from urllib.parse import urlsplit

    from .scraper_config import SCRAPER_CONFIG

    mappa: dict[str, str] = {}
    for url, voce in SCRAPER_CONFIG.items():
        endpoint = voce.get("news_url")
        if not endpoint:
            continue
        host = urlsplit(url).netloc.lower().split(":", 1)[0]
        mappa.setdefault(host[4:] if host.startswith("www.") else host, str(endpoint))
    return mappa


# --- pre-filtro sugli allegati (§6.2) ---------------------------------------

@dataclass(frozen=True)
class EsitoAllegato:
    """Esito della HEAD su un allegato gia' pubblicato."""
    url: str
    esito_http: int | None = None
    sha256: str | None = None
    cambiato: bool = False


def controlla_allegati(
    riga: Mapping[str, Any], esiti: Iterable[Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(aggiornamenti di `bando_link`, eventi interni) dalle HEAD sugli allegati.

    Il pre-filtro costa una HEAD per allegato e zero token. Due esiti contano:

      * **404/410**: il documento non c'e' piu'. §13.4 promette a BandoFit che
        ogni riga leggibile ha risposto 2xx all'ultimo controllo, quindi la
        riga esce subito da `pubblicabile` — prima ancora che qualcuno decida
        se il bando e' cambiato;
      * **sha256 diverso**: il documento e' stato sostituito. E' un candidato
        `rettifica`, ma qui resta un evento **interno**: una HEAD non produce
        nessuna citazione, e senza citazione i gate G1 e G4 non possono
        passare. Alza la priorita' del prossimo controllo, che leggera' la
        pagina e, se c'e' una frase che lo dichiara, emettera' l'evento vero.
    """
    aggiornamenti: list[dict[str, Any]] = []
    interni: list[dict[str, Any]] = []
    for grezzo in esiti:
        esito = grezzo if isinstance(grezzo, EsitoAllegato) else EsitoAllegato(
            url=str((grezzo or {}).get("url") or ""),
            esito_http=(grezzo or {}).get("esito_http"),
            sha256=(grezzo or {}).get("sha256"),
            cambiato=bool((grezzo or {}).get("cambiato")),
        )
        if not esito.url:
            continue
        stato = esito.esito_http
        if stato is not None and stato in (404, 410):
            aggiornamenti.append({"url": esito.url, "pubblicabile": False,
                                  "esito_http": stato})
            interni.append({
                "bando_id": riga.get("id"),
                "tipo": "elaborazione_bloccata",
                "origine": "worker",
                "campo": "allegati",
                "valore_dopo": {"url": esito.url, "esito_http": stato},
                "leggibile": False, "in_aggiornamenti": False, "applicato": False,
            })
            continue
        if esito.cambiato:
            aggiornamenti.append({"url": esito.url, "sha256": esito.sha256,
                                  "esito_http": stato})
            interni.append({
                "bando_id": riga.get("id"),
                "tipo": "segnale_fonte",
                "origine": "worker",
                "campo": "allegati",
                "valore_dopo": {"url": esito.url, "sha256": esito.sha256},
                "leggibile": False, "in_aggiornamenti": False, "applicato": False,
            })
    return aggiornamenti, interni


def _prove_da_pagine(pagine: Sequence[eventi_mod.Pagina]) -> list[eventi_mod.Prova]:
    """Le coppie (data, ruolo) lette dalle pagine collegate scaricate.

    Solo le pagine `collegata=True`: la scheda del bando e' la lettura che il
    G7 deve confermare, non puo' essere la conferma di se stessa. I ruoli
    `normativa` e `ignoto` non diventano mai una prova — una data di cui non
    si sa il ruolo non conferma niente.
    """
    trovate: list[eventi_mod.Prova] = []
    for pagina in pagine:
        if not pagina.collegata or not pagina.testo:
            continue
        for lettura in estrai_date_con_ruolo(pagina.testo):
            if lettura.ruolo in ("normativa", "ignoto"):
                continue
            trovate.append(eventi_mod.Prova(
                genere="pagina_collegata",
                data=lettura.data,
                ruolo=lettura.ruolo,
                url=pagina.url,
            ))
    return trovate


def _prove(riga: Mapping[str, Any]) -> list[eventi_mod.Prova]:
    """Prove indipendenti gia' in mano (G7). Mai `modified`/`ds_last_update`."""
    trovate: list[eventi_mod.Prova] = []
    for voce in riga.get("prove") or ():
        if isinstance(voce, eventi_mod.Prova):
            trovate.append(voce)
        elif isinstance(voce, Mapping):
            trovate.append(eventi_mod.Prova(
                genere=str(voce.get("genere") or ""),
                data=_data(voce.get("data")),
                ruolo=str(voce.get("ruolo") or ""),
                url=str(voce.get("url") or ""),
            ))
    return trovate


def _colonne_invariato(
    riga: Mapping[str, Any],
    prossimo: datetime | None,
    adesso: datetime,
    *,
    impronta: str | None = None,
    cambiato: bool = False,
    risposta: Any = None,
    testo: str | None = None,
    sezioni: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Le colonne di `bando_controllo` dopo un controllo riuscito.

    Oltre ai contatori si scrive la **memoria** del monitor, e non e' un
    dettaglio: `testo_norm` e' il «prima» del prossimo diff, `etag` e
    `last_modified` sono cio' che rende possibile un 304, `impronte_sezioni`
    e' cio' che permette di dire *quale* pezzo di pagina e' cambiato. A DB e
    non in memoria, perche' devono sopravvivere al redeploy (§6.2).
    """
    # ATTENZIONE: `controlli_senza_diff` **non esiste** in `bando_controllo`
    # (02:1138-1163). `aggiorna_controllo` la scarta in silenzio, quindi alla
    # rilettura vale 0 e il fattore calma (`CONTROLLI_PER_CALMA` = 3) non si
    # applica mai. Si scrive lo stesso, cosi' il giorno in cui la colonna
    # arrivera' il conteggio sara' gia' giusto — ma finche' non arriva la
    # volatilita' puo' solo scendere, ed e' il motivo per cui `_con_memoria`
    # NON la rilegge: vedi li'.
    senza_diff = 0 if cambiato else int(riga.get("controlli_senza_diff") or 0) + 1
    colonne: dict[str, Any] = {
        "ultimo_controllo_at": adesso.isoformat(),
        "controlli_falliti": 0,
        "controlli_senza_diff": senza_diff,
        "volatilita": moltiplicatore_volatilita(
            riga.get("volatilita"),
            eventi_verificati=1 if cambiato else 0,
            controlli_senza_diff=senza_diff,
        ),
    }
    if prossimo is not None:
        colonne["prossimo_controllo_at"] = prossimo.isoformat()
    if impronta:
        colonne["impronta_contenuto"] = impronta
    # `ultimo_cambiamento_at` NON si scrive da qui, e non per dimenticanza:
    # quella colonna sta su `bando`, non su `bando_controllo`, ed e' il
    # `lastmod` della sitemap piu' l'`updated_since` dell'API. Finiva in questo
    # payload e `aggiorna_controllo` la scartava in silenzio (la scarta insieme
    # a ogni colonna che lo schema non espone), quindi il codice sembrava
    # mantenerla e non la toccava.
    # La mantiene il DB: `trg_bando_cambiamento_pubblico` (migrazione 01) la
    # muove a ogni UPDATE che cambia una colonna pubblica, cioe' quando un
    # evento viene davvero applicato. Ed e' la semantica giusta: «la pagina
    # dell'ente e' cambiata» non e' «la nostra scheda e' cambiata», e scriverla
    # su ogni diff avrebbe messo nella sitemap un `lastmod` nuovo per schede
    # identiche a prima.

    # Le due testate della GET condizionale. Si scrivono anche quando sono
    # diventate NULL: una pagina che smette di mandare l'ETag deve smettere di
    # farcelo inviare, altrimenti ogni `If-None-Match` successivo e' un 200
    # travestito da controllo gratuito.
    if risposta is not None:
        colonne["etag"] = getattr(risposta, "etag", None) or None
        colonne["last_modified"] = getattr(risposta, "last_modified", None) or None

    if testo is not None:
        compresso = comprimi_testo(testo)
        if compresso is not None:
            colonne["testo_norm"] = compresso
    if sezioni is not None:
        colonne["impronte_sezioni"] = dict(sezioni)
    return colonne


def _errore(
    riga: Mapping[str, Any],
    esito: EsitoControllo,
    motivo: str,
    adesso: datetime,
    fonte_dati: FonteDati | None,
    modalita: str = eventi_mod.MODALITA_OMBRA,
) -> EsitoControllo:
    """Errore di rete: backoff, e dopo cinque fallimenti si dichiara bloccato."""
    falliti = int(riga.get("controlli_falliti") or 0) + 1
    esito.esito = "errore"
    esito.motivo = motivo
    esito.prossimo = prossimo_dopo_errore(falliti, adesso=adesso)
    esito.colonne = {
        "ultimo_controllo_at": adesso.isoformat(),
        "controlli_falliti": falliti,
        "prossimo_controllo_at": esito.prossimo.isoformat(),
    }
    if falliti >= FALLIMENTI_PER_BLOCCO:
        # Cinque fallimenti di fila non sono un guasto di rete: la pagina non
        # c'e' piu'. Il bando esce dalla coda e torna al resolver.
        #
        # NON si scrivono qui `elaborazione_bloccata` ne' `fonte_ufficiale_stato`:
        # la prima in SQL e' un *tipo di evento*, non una colonna, e la seconda
        # sta su `bando`, non su `bando_controllo` (02:1138-1162). Scritte qui
        # venivano scartate in silenzio da `colonne_mancanti`, e la promessa
        # «cinque fallimenti e il bando esce dalla coda» non si avverava.
        # Uscire dalla coda si ottiene con le due cose che funzionano davvero:
        # `prossimo_controllo_at` lontano (lo fa gia' il backoff, qui si alza
        # al massimo) e `fonte_ufficiale_stato` scritta su `bando`.
        esito.prossimo = prossimo_dopo_errore(
            max(falliti, FALLIMENTI_PER_BLOCCO), adesso=adesso)
        esito.colonne["prossimo_controllo_at"] = esito.prossimo.isoformat()
        # `fonte_ufficiale_stato` e' una colonna **pubblica** di `bando`: in
        # ombra non si tocca, come nessun'altra. Il ricontrollo lontano, che
        # sta su `bando_controllo`, si scrive anche in ombra — senza, non
        # esisterebbe baseline e il giro dopo non avrebbe niente da
        # confrontare.
        if fonte_dati is not None and modalita == eventi_mod.MODALITA_ATTIVO:
            _sospendi_fonte(esito.bando_id)
        if fonte_dati is not None:
            fonte_dati.registra_evento({
                "bando_id": riga.get("id"),
                "tipo": "elaborazione_bloccata",
                "origine": "worker",
                "leggibile": False,
                "in_aggiornamenti": False,
                "applicato": False,
                "valore_dopo": {"motivo": motivo, "controlli_falliti": falliti},
            })
    _salva(fonte_dati, esito)
    return esito


def _sospendi_fonte(bando_id: Any) -> None:
    """`bando.fonte_ufficiale_stato = 'in_verifica'` dopo cinque fallimenti.

    E' l'unica scrittura che fa tornare il bando al resolver: la colonna sta
    su `bando`, e `bando_controllo` non ne ha una equivalente. Degrada con un
    log se la colonna non c'e' ancora: non e' una ragione per far fallire il
    giro.
    """
    if bando_id is None:
        return
    try:
        from . import db
        db.aggiorna_fonte_ufficiale(bando_id, {"fonte_ufficiale_stato": "in_verifica"})
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning(
            "[monitor] bando {}: fonte_ufficiale_stato non aggiornata: {}", bando_id, e)


def _salva(fonte_dati: FonteDati | None, esito: EsitoControllo) -> None:
    if fonte_dati is None or not esito.colonne:
        return
    try:
        fonte_dati.salva_controllo(esito.bando_id, esito.colonne)
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[monitor] salvataggio del controllo {} fallito: {}", esito.bando_id, e)


# --- giro completo ----------------------------------------------------------

def _modalita_richiesta(attivo: bool | None, impostazioni: Any) -> str:
    """Ombra per difetto; `--ombra` (False esplicito) vince sull'ambiente.

    Tre valori e non due: `None` e' «l'operatore non ha detto niente» e lascia
    decidere `MONITOR_MODALITA`; `False` e' «ha scritto `--ombra`» e allora si
    resta in ombra anche con `MONITOR_MODALITA=attivo`. Senza il terzo valore
    il flag che l'operatore scrive per iscritto non aveva alcun effetto.
    """
    if attivo is not None:
        return eventi_mod.MODALITA_ATTIVO if attivo else eventi_mod.MODALITA_OMBRA
    return getattr(impostazioni, "monitor_modalita", eventi_mod.MODALITA_OMBRA)


def _campi_g7(seconda_opinione: Any, pagine_collegate: Any) -> dict[str, bool]:
    """I tre campi del riepilogo che dicono se il G7 puo' passare.

    Il G7 ha due varianti e **non** chiede sempre la stessa cosa:
    `eventi.g7_seconda_prova(..., doppia=False)` si accontenta di una fra
    concordanza (seconda opinione) e prova indipendente (pagine collegate),
    mentre la variante G2' — primo controllo con mismatch e senza diff, il
    caso guida di §6.2 — le pretende **entrambe**. Un solo booleano in OR
    direbbe «G7 soddisfacibile» mentre ogni evento G2' viene respinto con
    «G2' richiede entrambe le prove»: esattamente l'equivoco che questo campo
    esiste per evitare. Da qui i due campi separati, e `g7_disponibile` come
    AND — la garanzia che deve dare e' «il G7 puo' passare in ogni sua
    variante».

    In produzione i due adattatori nascono e muoiono insieme (entrambi i
    chiamanti gattano sulla stessa `ANTHROPIC_API_KEY`), ma non sempre: senza
    il pacchetto `anthropic` la seconda opinione e' `None` e le pagine
    collegate no.
    """
    concordanza = seconda_opinione is not None
    indipendente = pagine_collegate is not None
    return {
        "g7_concordanza": concordanza,
        "g7_prova_indipendente": indipendente,
        "g7_disponibile": concordanza and indipendente,
    }


async def run(
    *,
    dry_run: bool = False,
    limit: int | None = None,
    attivo: bool | None = None,
    giro: str | None = None,
    impostazioni: Any = None,
    fonte_dati: FonteDati | None = None,
    scarica: Callable[..., Awaitable[Any]] | None = None,
    classifica: Callable[..., Awaitable[Sequence[eventi_mod.Evento]]] | None = None,
    seconda_opinione: Callable[..., Awaitable[eventi_mod.Evento | None]] | None = None,
    pagine_collegate: Callable[..., Awaitable[Sequence[str]]] | None = None,
    rigenerazione: Callable[..., Awaitable[Any]] | None = None,
    segnale_macchina: Callable[..., Awaitable[bool | None]] | None = None,
    head_allegati: Callable[..., Awaitable[Sequence[Any]]] | None = None,
    tabella_domini: Any = None,
    adesso: datetime | None = None,
    casuale: Callable[[], float] | None = None,
    senza_rete: bool = False,
    lotto: str | None = None,
    contatori: bilancio.Contatori | None = None,
    lock: Any = blocco,
) -> dict[str, Any]:
    """Un giro di monitoraggio. Ritorna i contatori; non solleva mai.

    Le chiavi che `bandi_pipeline.py` e `__main__.py` leggono:
    `status`, `saltato_per_lock`, `interrotto_per_tetto`, `slug_modificati`.

    `scarica` non iniettato significa «usa `scarico.py`», che e' il client
    unico del giro (http2, ripiego Firecrawl solo sulla pagina principale,
    contatori dei crediti). `senza_rete=True` lo disattiva del tutto: il giro
    seleziona, ordina e riepiloga senza fare una sola richiesta, che e' cio'
    che serve per provare la selezione su dati veri senza spendere niente.

    `classifica` non iniettato significa «costruisci Haiku dalle
    impostazioni»; se la chiave non c'e' il giro salta ogni riga **prima** del
    fetch, quindi non costa niente. `rigenerazione` e' il punto in cui la
    prosa viene portata in linea con le date nuove: senza, uno slug le cui
    date sono cambiate NON finisce in `slug_modificati`, perche' notificare
    Google una pagina il cui testo e' rimasto vecchio e' peggio che tacere.

    `dry_run=True` e' piu' forte di `attivo`: forza l'ombra **e** toglie ogni
    scrittura, comprese quelle su `bando_controllo` e gli eventi interni.

    `contatori` e' il punto delicato dell'innesto di produzione: la seconda
    opinione del G7 si costruisce nel **chiamante** (CLI e `bandi_pipeline`),
    quindi il suo `bilancio.registra_chiamata` scrive in un oggetto che esiste
    gia' prima di questo giro. Passando qui lo STESSO oggetto, il costo della
    conferma entra nel tetto giornaliero in $ mentre il giro corre — non a
    giro finito, quando un tetto non serve piu' a niente.
    """
    # Lo step nomina la riga di `pipeline_run` E decide quali tetti valgono:
    # `bilancio.e_backfill` guarda il prefisso. Senza `--lotto` il monitor
    # risponde ai tetti del regime (30 classificazioni e 1,5 dollari al
    # giorno), che sono giusti a regime e sbagliati per la **semina**: il primo
    # giro su un bando non ha un «prima» con cui confrontare, quindi passa dal
    # modello sempre, e con 213 bandi da seminare il tetto morde al trentesimo.
    # Misurato il 24/09/2026: `candidati: 50, controllati: 30`, fermato dal
    # tetto dopo tre minuti. Il piano lo prevedeva (il lotto L6 sta sui tetti
    # di backfill) e il comando non aveva il modo di dirlo.
    passo = f"backfill:{lotto}" if lotto else STEP
    avvio = time.monotonic()
    momento = adesso_roma(adesso)
    # Le chiavi che ogni uscita di `run` deve avere, comprese le quattro
    # anticipate: `allarmi` e i tre campi del G7 nascono per essere letti da
    # fuori (`pipeline_run`), e un consumatore che le trovasse solo nel
    # riepilogo completo andrebbe in KeyError proprio nei giri saltati.
    base: dict[str, Any] = {
        "status": "ok",
        "step": STEP,
        "giro": giro,
        "allarmi": [],
        "saltato_per_lock": False,
        "interrotto_per_tetto": False,
        "slug_modificati": [],
        **_campi_g7(seconda_opinione, pagine_collegate),
    }
    if impostazioni is None:
        from .settings import get_settings
        try:
            impostazioni = get_settings()
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[monitor] impostazioni non leggibili: {}", e)
            return dict(base, saltato="impostazioni_assenti", motivo=str(e))

    modalita = _modalita_richiesta(attivo, impostazioni)
    if dry_run:
        # `--dry-run` e' piu' forte di `--attivo`: non si scrive comunque.
        modalita = eventi_mod.MODALITA_OMBRA
    scenario = _scenario(getattr(impostazioni, "monitor_scenario", "bilanciato"))

    if giro is not None and giro not in (getattr(impostazioni, "monitor_giri", ()) or ()):
        logger.info("[monitor] giro {} non previsto da MONITOR_GIRI: salto", giro)
        return dict(base, saltato="giro_non_previsto")

    preso = lock.acquisisci(NOME_LOCK, f"{STEP}:{giro or 'cli'}", blocco.TTL_PREDEFINITO_S)
    if not preso.proseguire:
        return {**base, **lock.esito_saltato(preso)}

    try:
        dati = fonte_dati if fonte_dati is not None else da_db()
        pronto, motivo = dati.disponibile()
        if not pronto:
            logger.info("[monitor] schema incompleto ({}): step saltato", motivo)
            return dict(base, saltato=motivo)

        tetti = bilancio.tetti_da_impostazioni(impostazioni)
        if contatori is None:
            contatori = bilancio.Contatori()
        tetto = tetti.fetch_giro if limit is None else min(
            limit, tetti.fetch_giro or limit)
        righe = dati.candidati(limite=tetto, adesso=momento)
        # Gli allarmi del giro: quelli della selezione (coda troncata) piu'
        # quelli dei tetti. Vivono nel riepilogo e quindi in `pipeline_run`,
        # perche' un allarme che esiste solo in una riga di log e' un allarme
        # che nessuno legge il giorno in cui serve.
        allarmi: list[str] = list(getattr(dati, "allarmi", ()) or ())
        for allarme in allarmi:
            logger.warning("[ALLARME] [monitor] {}", allarme)

        scaricatore = None if senza_rete else (scarica or _scarico_predefinito())
        proprio = scarica is None and scaricatore is not None
        if proprio:
            # Il client del giro riparte pulito: una pagina di sei ore fa non
            # e' una prova di niente, e i crediti si contano da zero.
            _azzera_scarico()

        classificatore = classifica
        if classificatore is None and righe and scaricatore is not None:
            classificatore = classificatore_da_impostazioni(impostazioni, contatori)
            if classificatore is None:
                # Senza `ANTHROPIC_API_KEY` `controlla` esce al passo 0 su
                # OGNI riga e non salva niente: nessuna riga esce dalla coda,
                # due giri di fila guardano gli stessi id e l'esito era
                # `status: ok`, exit 0. E' esattamente il caso per cui esiste
                # `EXIT_NON_CONFIGURATO`, e la chiave `saltato` e' quella che
                # `__main__._codice_da_contatori` traduce in 5.
                logger.error(
                    "[monitor] nessun classificatore disponibile: {} candidati "
                    "non controllati, giro dichiarato non configurato", len(righe))
                return dict(base, saltato="scarico_non_configurato",
                            candidati=len(righe), controllati=0, allarmi=allarmi)

        # La whitelist dei domini si costruisce UNA volta per giro, e solo se
        # c'e' davvero qualcosa da controllare. Senza, `eventi.g4_prova`
        # ripiega sul seed compilato — 20 host e 7 pattern — e respinge quasi
        # ogni ente reale: `lazioeuropa.it`, il caso guida di §6.2, non c'e'.
        if tabella_domini is None and righe and classificatore is not None:
            tabella_domini = _tabella_domini_del_giro()

        esiti: list[EsitoControllo] = []
        interrotto = False
        motivo_tetto = ""
        for riga in righe:
            verifica = bilancio.verifica(
                contatori, tetti, step=passo, gia_oggi=dati.consumo_oggi())
            if not verifica.consentito:
                interrotto = True
                motivo_tetto = verifica.motivo
                allarmi.append(verifica.motivo)
                logger.warning("[ALLARME] [monitor] {}", verifica.motivo)
                break
            if scaricatore is None:
                esiti.append(EsitoControllo(
                    bando_id=riga.get("id"), fase=fase(riga, oggi=momento.date()),
                    esito="saltato",
                    motivo="senza rete" if senza_rete else "nessuno scarico disponibile"))
                continue
            esito = await controlla(
                riga,
                scarica=scaricatore,
                classifica=classificatore,
                seconda_opinione=seconda_opinione,
                pagine_collegate=pagine_collegate,
                rigenerazione=rigenerazione,
                segnale_macchina=segnale_macchina,
                head_allegati=head_allegati,
                fonte_dati=dati,
                modalita=modalita,
                scenario=scenario,
                stati_estesi=bool(getattr(impostazioni, "monitor_stati_estesi", False)),
                tabella_domini=tabella_domini,
                adesso=momento,
                casuale=casuale,
                dry_run=dry_run,
            )
            contatori.classificazioni += 1 if esito.classificato else 0
            contatori.eventi += len(esito.eventi)
            contatori.errori += 1 if esito.esito == "errore" else 0
            esiti.append(esito)
            if proprio:
                # Con il client unico i contatori veri sono i suoi: `fetch`,
                # `fetch_304` e soprattutto `crediti_firecrawl`, che senza
                # questa fusione resterebbe 0 e renderebbe il tetto dei crediti
                # incapace di mordere. Si fondono DENTRO il ciclo — un tetto
                # che se ne accorge a giro finito non e' un tetto — e si
                # azzerano subito dopo, perche' `unisci_scarico` somma.
                bilancio.unisci_scarico(contatori, _contatori_scarico())
                _azzera_contatori_scarico()
            else:
                # Scarico iniettato (test, `--senza-rete`): l'unico contatore
                # disponibile e' quello che il controllo ha dichiarato.
                contatori.fetch += esito.fetch

        # IndexNow riceve solo le pagine il cui **contenuto** e' cambiato: un
        # evento sulle date senza rigenerazione lascia la prosa com'era, e
        # notificare Google una pagina identica e' peggio che non notificarla.
        slug_modificati = tuple(
            e.slug for e in esiti
            if e.slug and e.eventi and modalita == eventi_mod.MODALITA_ATTIVO
            and (not e.da_rigenerare or e.rigenerato)
        )
        # Un giro `--senza-rete` (o senza uno scarico) accodava N esiti
        # `saltato` e riferiva `controllati: N, non_modificati: 0` con exit 0:
        # somigliava a un giro vero. `controllati` conta ora le righe davvero
        # controllate, e i saltati si dichiarano con il motivo prevalente.
        saltati = [e for e in esiti if e.esito == "saltato"]
        motivo_saltati = _motivo_prevalente(saltati)
        riepilogo = {
            **base,
            "modalita": modalita,
            "scenario": scenario,
            "candidati": len(righe),
            "controllati": len(esiti) - len(saltati),
            "saltati": len(saltati),
            "motivo_saltati": motivo_saltati,
            "fetch": contatori.fetch,
            "non_modificati": sum(1 for e in esiti if e.esito in ("304", "invariato")),
            "errori": contatori.errori,
            "classificazioni": contatori.classificazioni,
            "eventi": contatori.eventi,
            "respinti": sum(len(e.respinti) for e in esiti),
            "allegati_aggiornati": sum(len(e.allegati) for e in esiti),
            "interrotto_per_tetto": interrotto,
            "motivo": motivo_tetto,
            "allarmi": allarmi,
            "slug_modificati": list(slug_modificati),
            "durata_s": round(time.monotonic() - avvio, 1),
        }
        _scrivi_telemetria(riepilogo, contatori, giro, slug_modificati, interrotto,
                           tempo=time.monotonic() - avvio, passo=passo)
        logger.info("[monitor] {}", riepilogo)
        return riepilogo
    except Exception as e:
        # Un guasto imprevisto e' un contatore, non un'eccezione che risale
        # fino al sender: la pipeline deve poter proseguire con gli altri step.
        # `format_exception` dentro il messaggio, non `logger.exception`: il
        # traceback passa cosi' dalla redazione del patcher, che lavora su
        # `record["message"]`. I sink oggi nascono con `diagnose=False` (e
        # `Settings` ha un repr mascherante), quindi non e' piu' l'unica
        # difesa — ma resta la piu' diretta, e costa una riga.
        logger.error(
            "[monitor] giro fallito: {}\n{}", e,
            "".join(traceback.format_exception(type(e), e, e.__traceback__)).rstrip(),
        )
        return dict(base, status="errore", motivo=str(e))
    finally:
        lock.rilascia(preso)


def _scarico_predefinito() -> Callable[..., Awaitable[Any]] | None:
    """Lo scarico di produzione: il client unico del giro di `scarico.py`.

    Ritorna `None` (e lo step salta ogni riga con un motivo scritto) se il
    modulo non e' disponibile: il monitor non deve mai aprire una connessione
    per conto suo ne' fallire per un import.
    """
    try:
        from .scarico import scarico_corrente
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[monitor] scarico non disponibile: {}", e)
        return None
    return scarico_corrente().scarica


def _tabella_domini_del_giro() -> Any:
    """La whitelist dei domini ufficiali (§5), costruita una volta per giro.

    Sono le righe di `dominio_ufficiale` piu' gli host di `fonte` piu' il seed
    compilato: la stessa tabella che usa il resolver. Costruirla costa una
    SELECT; non costruirla costa il G4, che senza di essa conosce 20 host e 7
    pattern e boccia ogni ente fuori dal seed. Se la SELECT fallisce si
    ritorna `None` e `g4_prova` ripiega sul seed — degradato, ma non muto.
    """
    try:
        from . import db
        from .dominio_ufficiale import costruisci
        return costruisci(fonti=db.select_fonti_per_domini())
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning(
            "[monitor] tabella dei domini non costruita, resta il seed: {}", e)
        return None


def classificatore_da_impostazioni(
    impostazioni: Any, contatori: bilancio.Contatori,
) -> Callable[[eventi_mod.Contesto], Awaitable[Sequence[eventi_mod.Evento]]] | None:
    """Il classificatore di produzione: Haiku con lo strumento di `eventi.py`.

    Ritorna `None` — e il giro salta ogni riga **prima** del fetch — se la
    chiave non c'e' o il pacchetto non e' installato: un giro senza modello
    non deve pagare una GET per riga per poi buttare via la pagina.

    Ogni chiamata passa da `bilancio.registra_chiamata`, che e' cio' che
    alimenta il tetto giornaliero in $ e la riga `pipeline_run`.
    """
    chiave = str(getattr(impostazioni, "anthropic_api_key", "") or "")
    if not chiave:
        logger.info("[monitor] ANTHROPIC_API_KEY assente: nessuna classificazione")
        return None
    try:
        import anthropic
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[monitor] pacchetto anthropic non disponibile: {}", e)
        return None

    cliente = anthropic.AsyncAnthropic(api_key=chiave)
    modello = str(getattr(impostazioni, "monitor_modello", "") or MODELLO_CLASSIFICATORE)
    listino = getattr(impostazioni, "listino_modelli", None) or {}

    async def classifica(ctx: eventi_mod.Contesto) -> Sequence[eventi_mod.Evento]:
        risposta = await cliente.messages.create(
            model=modello,
            max_tokens=MAX_TOKEN_CLASSIFICATORE,
            system=eventi_mod.ISTRUZIONI_CLASSIFICATORE,
            tools=[eventi_mod.STRUMENTO_SALVA_EVENTI],
            tool_choice={"type": "tool", "name": eventi_mod.STRUMENTO_SALVA_EVENTI["name"]},
            messages=[{"role": "user", "content": eventi_mod.prompt_utente(ctx)}],
        )
        bilancio.registra_chiamata(
            contatori, modello, getattr(risposta, "usage", None), listino)
        return eventi_mod.leggi_eventi(risposta)

    return classifica


def seconda_opinione_da_impostazioni(
    impostazioni: Any, contatori: bilancio.Contatori,
) -> Callable[[eventi_mod.Contesto], Awaitable[Any]] | None:
    """La seconda opinione di produzione per il G7: Sonnet sullo stesso contesto.

    Gemella di `classificatore_da_impostazioni`, con tre differenze che sono
    tutto il senso del gate:

    1. **modello diverso.** Una conferma chiesta a chi ha gia' risposto non e'
       una prova: e' la stessa lettura due volte. §6.2 vuole Sonnet 4.6 dove il
       primo passaggio e' Haiku;
    2. **stesso contesto, mai l'evento proposto.** Il `Contesto` che arriva qui
       e' quello del primo modello — diff, pagine, stato, date — e nient'altro.
       Mostrare la proposta di Haiku trasformerebbe una prova indipendente in
       una domanda suggestiva («confermi?»), che un modello conferma quasi
       sempre. Per questo `Contesto.seconda_opinione` resta a `None` mentre
       questa funzione lavora: e' `controlla` a riempirlo DOPO;
    3. **un solo tentativo.** Un errore vale `None` (cioe' «nessuna
       concordanza»), non un ritentativo: il G7 ha la seconda strada della
       prova indipendente, e un retry per bando moltiplicherebbe il conto
       proprio sui giri in cui la rete va male.

    Ritorna `None` — e il comportamento resta quello di oggi, cioe' G7
    soddisfacibile solo con una prova indipendente — se la chiave o il
    pacchetto mancano. Ogni chiamata passa da `bilancio.registra_chiamata`:
    e' cio' che fa entrare il costo nel tetto giornaliero in $.

    Restituisce **tutti** gli eventi letti, non il primo: un differimento reale
    ne produce due (apertura e scadenza) e `eventi._concordanza` scorre la
    lista per far combaciare quello giusto. Tenere solo il primo bocciarebbe al
    G7 la seconda rettifica della stessa pagina — che e' esattamente il caso
    guida di §6.2 («Psicologia scolastica»).
    """
    chiave = str(getattr(impostazioni, "anthropic_api_key", "") or "")
    if not chiave:
        logger.info("[monitor] ANTHROPIC_API_KEY assente: nessuna seconda opinione (G7)")
        return None
    try:
        import anthropic
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[monitor] pacchetto anthropic non disponibile: {}", e)
        return None

    cliente = anthropic.AsyncAnthropic(api_key=chiave)
    modello = str(
        getattr(impostazioni, "monitor_modello_seconda", "") or MODELLO_SECONDA_OPINIONE)
    listino = getattr(impostazioni, "listino_modelli", None) or {}

    async def seconda_opinione(ctx: eventi_mod.Contesto) -> Any:
        try:
            risposta = await cliente.messages.create(
                model=modello,
                max_tokens=MAX_TOKEN_SECONDA_OPINIONE,
                system=eventi_mod.ISTRUZIONI_CLASSIFICATORE,
                tools=[eventi_mod.STRUMENTO_SALVA_EVENTI],
                tool_choice={"type": "tool", "name": eventi_mod.STRUMENTO_SALVA_EVENTI["name"]},
                # Il contesto NON porta la proposta del primo modello: e'
                # `replace` a metterla nel contesto solo dopo questa chiamata.
                messages=[{"role": "user", "content": eventi_mod.prompt_utente(ctx)}],
            )
        except Exception as e:
            # Nessun ritentativo: vedi il punto 3 del docstring.
            logger.warning(
                "[monitor] seconda opinione non ottenuta per il bando {}: {}",
                ctx.bando_id, e)
            return None
        bilancio.registra_chiamata(
            contatori, modello, getattr(risposta, "usage", None), listino)
        return eventi_mod.leggi_eventi(risposta) or None

    return seconda_opinione


# --- pagine collegate di produzione (§6.2) ----------------------------------

def _quota(valore: Any, predefinita: float) -> float:
    """Una quota 0..1 letta dalle impostazioni, con ripiego sul default."""
    try:
        quota = float(valore)
    except (TypeError, ValueError):
        return predefinita
    return quota if 0.0 <= quota <= 1.0 else predefinita


def _token_ricerca(titolo: str | None, quanti: int = TOKEN_RICERCA_WP) -> str:
    """I primi `quanti` token significativi del titolo, nell'ordine del titolo.

    In ordine e non come insieme: la stringa finisce in `?search=`, e una query
    che cambia a ogni giro per il capriccio dell'hash degli insiemi renderebbe
    inutile la cache dello scarico (e imprevedibile il test).

    «Significativi» esclude `PAROLE_VUOTE_RICERCA`: con «avviso» e «nelle»
    dentro, due dei tre token di «Avviso psicologia scolastica nelle scuole del
    Lazio» non restringono niente e la ricerca — che e' un OR ordinato per
    pertinenza — torna mezzo sito. Un titolo fatto di sole parole vuote non
    produce query, e quindi nemmeno una GET: e' il caso in cui una ricerca non
    potrebbe comunque dire niente di quel bando.
    """
    from .normalize import normalize_for_canonical
    parole = [
        t for t in normalize_for_canonical(titolo or "").split()
        if len(t) > 2 and t not in PAROLE_VUOTE_RICERCA
    ]
    return " ".join(parole[:max(0, quanti)])


def _somiglianza_titoli(uno: str | None, altro: str | None) -> float:
    """Jaccard sui token dei due titoli: la stessa coppia di funzioni del
    resolver (§5), cosi' non nasce una seconda nozione di «titolo uguale»."""
    from .fonte_ufficiale import jaccard, token
    return jaccard(token(uno), token(altro))


def _copertura_ricerca(ricerca: str, titolo_notizia: str | None) -> float:
    """Quota dei token di `?search=` che compaiono nel titolo del post (0..1).

    Stessa funzione `token` del Jaccard — la nozione di «parola uguale» resta
    una sola — ma misura asimmetrica: al denominatore stanno solo le parole
    distintive del bando, non l'unione dei due titoli. E' cio' che la rende
    insensibile alla lunghezza del titolo della notizia (vedi
    `COPERTURA_RICERCA_WP`).
    """
    from .fonte_ufficiale import token
    cercati = token(ricerca)
    if not cercati:
        return 0.0
    return len(cercati & token(titolo_notizia)) / len(cercati)


def _host_di(url: str) -> str:
    """Host senza `www.`: la funzione dello scarico, importata al volo.

    Al volo perche' `monitoraggio` non deve fallire per un import (la regola di
    `_scarico_predefinito`); il ripiego copre il caso in cui `httpx` non ci sia.
    """
    try:
        from .scarico import host_di
        return host_di(url)
    except Exception:                                     # pragma: no cover - ripiego
        host = urlsplit(url).netloc.lower().split(":", 1)[0]
        return host[4:] if host.startswith("www.") else host


def _e_wordpress(news_url: str) -> bool:
    """Vero se l'endpoint del registro e' la REST API di WordPress."""
    return PERCORSO_WP_POSTS in (news_url or "").lower()


def _chiave_pagina(url: str) -> str:
    """Forma normale di «stessa pagina»: host senza `www.`, percorso senza
    slash finale, query ordinata, schema e frammento via.

    Serve a una cosa sola: riconoscere la scheda del bando quando rientra come
    «pagina collegata» sotto un'altra spoglia (`www.` o no, `http` o `https`,
    con o senza slash finale). `registro.chiave` da sola non basta — tiene
    `www.` e lo schema **apposta**, perche' li' due host diversi possono
    servire configurazioni diverse e la regola e' «mai fondere voci diverse».
    Qui la domanda e' l'opposta: «e' la stessa pagina?», e va risposta larga.
    """
    if not url or not url.strip():
        return ""
    try:
        from .registro import chiave
    except Exception:                                     # pragma: no cover - ripiego
        def chiave(valore: str) -> str:
            return valore.strip().casefold()
    pezzi = urlsplit(url.strip())
    parametri = sorted(parse_qsl(unquote(pezzi.query), keep_blank_values=True))
    # Schema e host fuori dalla forma normale del percorso: l'host lo mette
    # `_host_di`, che e' gia' quello senza `www.` dello scarico.
    resto = urlunsplit(("", "", pezzi.path, urlencode(parametri), ""))
    return f"{_host_di(url)}|{chiave(resto)}"


def _stessa_pagina(uno: str, altro: str) -> bool:
    """Vero se i due URL indirizzano la stessa pagina (vedi `_chiave_pagina`).

    Due stringhe vuote **non** sono la stessa pagina: un bando senza fonte
    ufficiale non deve far sparire ogni candidato.
    """
    prima = _chiave_pagina(uno)
    return bool(prima) and prima == _chiave_pagina(altro)


def _url_ricerca_wp(
    news_url: str,
    ricerca: str,
    dopo: datetime | None,
    *,
    adesso: datetime | None = None,
) -> str | None:
    """`wp/v2/posts?search=<3 token>&after=<ultimo controllo>` (§6.2).

    `ricerca` sono i token gia' scelti da `_token_ricerca`: li sceglie il
    chiamante perche' gli servono due volte, per la query e per la copertura.
    Senza token non si interroga: `?search=` vuoto restituisce gli ultimi post
    del sito, cioe' un fetch per bando che non riguarda quel bando.

    `after=` c'e' **sempre**: quando `ultimo_controllo_at` manca — il primo
    controllo di un bando — si ripiega su `oggi - GIORNI_RICERCA_WP` invece di
    ometterlo. Ometterlo aprirebbe la ricerca a tutti i post di sempre proprio
    nel giro in cui il G7 gira in variante G2' e pretende ANCHE la prova
    indipendente: il momento peggiore per pescare dall'archivio intero.
    """
    if not ricerca:
        return None
    limite = dopo if dopo is not None else (
        adesso_roma(adesso) - timedelta(days=GIORNI_RICERCA_WP))
    parametri = [
        ("search", ricerca),
        ("per_page", str(MAX_PAGINE_COLLEGATE * 5)),
        # WordPress vuole un ISO 8601 **senza** fuso e lo legge nel fuso del
        # sito: `_istante` ha gia' portato l'istante a Europe/Rome, che per un
        # sito di un ente italiano e' il fuso giusto.
        ("after", limite.replace(tzinfo=None).isoformat(timespec="seconds")),
    ]
    separatore = "&" if urlsplit(news_url).query else "?"
    return f"{news_url}{separatore}{urlencode(parametri)}"


def _post_wp(corpo: str) -> list[tuple[str, str]]:
    """(link, titolo) dai post della REST API. Una risposta storta vale zero
    post: il monitor non si ferma perche' un sito ha cambiato formato."""
    try:
        dati = json.loads(corpo or "")
    except (TypeError, ValueError):
        return []
    if not isinstance(dati, list):
        return []
    letti: list[tuple[str, str]] = []
    for voce in dati:
        if not isinstance(voce, Mapping):
            continue
        link = str(voce.get("link") or "").strip()
        titolo = voce.get("title")
        if isinstance(titolo, Mapping):
            titolo = titolo.get("rendered")
        if link:
            letti.append((link, str(titolo or "")))
    return letti


def _ancore(html: str, base: str) -> list[tuple[str, str]]:
    """(URL assoluto, testo) dei link di una pagina di notizie."""
    try:
        zuppa = impronte._zuppa(html)
    except Exception as e:                                # pragma: no cover - ripiego
        logger.debug("[monitor] pagina di notizie non analizzabile: {}", e)
        return []
    if zuppa is None:
        return []
    trovate: list[tuple[str, str]] = []
    for ancora in zuppa.find_all("a", href=True):
        href = str(ancora.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        trovate.append((urljoin(base, href), ancora.get_text(" ", strip=True)))
    return trovate


def pagine_collegate_da_impostazioni(
    impostazioni: Any,
    *,
    scarica: Callable[..., Awaitable[Any]] | None = None,
    news_per_host: Mapping[str, str] | None = None,
    adesso: datetime | None = None,
) -> Callable[[Mapping[str, Any]], Awaitable[Sequence[str]]]:
    """Il raccoglitore di pagine collegate di produzione (§6.2).

    Una proroga viene annunciata in una notizia molto piu' spesso di quanto
    venga scritta nella scheda: il post 21558 del 18/09 su lazioeuropa e' il
    caso reale da cui nasce la regola. Tre strade, tutte GET:

    * **WordPress** (`news_url` che punta a `wp-json/wp/v2/posts`): una
      ricerca per bando, `?search=<3 token del titolo>&after=<ultimo controllo
      o oggi - GIORNI_RICERCA_WP>`. E' l'unica interrogazione mirata, e costa
      **fino a 3 richieste per bando**: una di ricerca piu' quelle delle due
      pagine, che pero' le scarica `controlla`. Il vincolo «al massimo 2
      pagine» e' sulle pagine date al modello, non sulle richieste. La
      pertinenza si filtra due volte, con la ricerca e poi con
      `COPERTURA_RICERCA_WP` sui titoli: `?search=` e' un OR ordinato per
      pertinenza, non un AND, e da solo non e' un filtro;
    * **`news_url` generico**: **una** GET per host per giro — la memoria del
      giro qui sotto la garantisce anche quando l'host e' muto, che e' il caso
      in cui la cache dello scarico non aiuta (memorizza solo le risposte
      buone) — e i link della pagina si associano al bando con Jaccard >= 0,5
      sui titoli;
    * **SEDIA** per i bandi europei: l'indirizzo deterministico del topic
      (`sedia.url_topic`), che e' il solo endpoint F&T raggiungibile con una
      GET. La ricerca SEDIA con `latestInfos` e' un POST multipart, e il client
      unico del giro fa GET: il topic JSON porta le stesse date ed e' gratuito.

    Vincoli di §6.2 rispettati qui dentro: **massimo 2 pagine per bando per
    giro**, **solo httpx** (`principale=False` e' cio' che vieta il ripiego
    Firecrawl: quel credito e' ammesso solo sulla pagina principale del bando),
    errori e host che non rispondono ignorati con un log.

    Un invariante che vale la pena scrivere due volte: **la scheda del bando
    non puo' essere una pagina collegata**. E' cio' che `_prove_da_pagine`
    dichiara («non puo' essere la conferma di se stessa») e che, senza guardia,
    una voce `news_url` generica romperebbe elencando la scheda con una
    variante di host o di slash. Il confronto e' su `_chiave_pagina`, non fra
    stringhe grezze; la stessa guardia sta in `controlla`, accanto a chi
    dichiara l'invariante.

    A differenza di `seconda_opinione_da_impostazioni` qui non c'e' niente
    che possa mancare — nessuna chiave, nessun SDK — quindi il costruttore
    ritorna sempre una funzione: e' il chiamante a decidere se costruirla.

    `scarica`, `news_per_host` e `adesso` esistono per i test: in produzione
    restano `None` e si risolvono al momento della chiamata, cosi' l'adattatore
    usa il client del giro e non uno costruito all'avvio.
    """
    # La soglia e' configurabile come il modello del classificatore, con lo
    # stesso `getattr`: un ente che titola le notizie in modo molto diverso
    # dalle schede si corregge senza toccare il codice.
    soglia_titoli = _quota(
        getattr(impostazioni, "monitor_soglia_titoli", None), SOGLIA_TITOLI_COLLEGATE)
    copertura_wp = _quota(
        getattr(impostazioni, "monitor_copertura_wp", None), COPERTURA_RICERCA_WP)
    # La memoria del giro. La chiusura nasce e muore con il giro (i due
    # chiamanti costruiscono gli adattatori una volta per giro), quindi vive
    # esattamente quanto deve. Serve perche' `scarico.Scarico.scarica`
    # memorizza **solo** le risposte buone: senza, un host muto o in 5xx si
    # ripagherebbe una GET (piu' i suoi ritentativi) per OGNI bando di
    # quell'host, a ogni giro, ed e' proprio il caso in cui quelle GET non
    # servono a niente.
    muti: set[str] = set()
    elenchi: dict[str, list[tuple[str, str]]] = {}

    def _scarico() -> Callable[..., Awaitable[Any]] | None:
        if scarica is not None:
            return scarica
        return _scarico_predefinito()

    def _registro() -> Mapping[str, str]:
        if news_per_host is not None:
            return news_per_host
        try:
            return news_url_per_host()
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[monitor] registro delle notizie non leggibile: {}", e)
            return {}

    async def _prendi(prendi: Callable[..., Awaitable[Any]], url: str) -> Any:
        """Una GET httpx-only. Mai un'eccezione: l'host muto si salta.

        L'host che non risponde (eccezione o risposta inutilizzabile) finisce
        in `muti` e per il resto del giro non costa piu' niente. E' una
        rinuncia volutamente larga: un errore singolo spegne le pagine
        collegate di quell'host fino al giro dopo, che costa molto meno di
        centinaia di GET buttate contro un host in avaria.
        """
        host = _host_di(url)
        if host in muti:
            return None
        try:
            # `principale=False`: niente ripiego Firecrawl (§6.2).
            risposta = await prendi(url, principale=False)
        except Exception as e:
            muti.add(host)
            logger.debug("[monitor] pagina collegata {} non scaricata: {}", url, e)
            return None
        if not getattr(risposta, "ok", False):
            muti.add(host)
            logger.debug("[monitor] host {} senza pagine collegate (HTTP {})",
                         host, getattr(risposta, "stato", None))
            return None
        return risposta

    async def pagine_collegate(riga: Mapping[str, Any]) -> tuple[str, ...]:
        prendi = _scarico()
        if prendi is None:
            return ()
        titolo = str(riga.get("titolo") or "")
        ufficiale = str(riga.get("fonte_ufficiale_url") or "")
        trovate: list[str] = []

        news = _registro().get(_host_di(ufficiale)) if ufficiale else None
        if news:
            if _e_wordpress(news):
                # La ricerca restringe, ma da sola non e' un filtro:
                # `?search=` e' un OR ordinato per pertinenza, quindi i primi
                # post possono parlare d'altro. Il filtro e' la copertura dei
                # token di ricerca (vedi `COPERTURA_RICERCA_WP`).
                ricerca = _token_ricerca(titolo)
                url_ricerca = _url_ricerca_wp(
                    news, ricerca, _istante(riga.get("ultimo_controllo_at")),
                    adesso=adesso)
                risposta = await _prendi(prendi, url_ricerca) if url_ricerca else None
                corpo = getattr(risposta, "html", "") or getattr(risposta, "testo", "")
                candidati = _post_wp(corpo) if risposta is not None else []

                def pertinenza(titolo_notizia: str, _r: str = ricerca) -> float:
                    return _copertura_ricerca(_r, titolo_notizia)

                soglia = copertura_wp
            else:
                # Pagina di notizie generica: **una** GET per host per giro.
                # L'URL e' lo stesso per tutti i bandi dell'host, quindi anche
                # l'elenco dei link lo e': lo si legge una volta e lo si tiene.
                # Qui il filtro serve davvero — la pagina elenca le notizie di
                # tutti, e senza Jaccard >= 0,5 sui titoli si scaricherebbe la
                # prima voce dell'elenco.
                if news in elenchi:
                    candidati = elenchi[news]
                else:
                    risposta = await _prendi(prendi, news)
                    candidati = (
                        _ancore(getattr(risposta, "html", "") or "", news)
                        if risposta is not None else []
                    )
                    elenchi[news] = candidati

                def pertinenza(titolo_notizia: str, _t: str = titolo) -> float:
                    return _somiglianza_titoli(_t, titolo_notizia)

                soglia = soglia_titoli
            for url_notizia, titolo_notizia in candidati:
                # La scheda del bando non conferma se stessa: il confronto e'
                # sulla forma normale, perche' fra `https://www.ente.it/x/` e
                # `https://ente.it/x` non c'e' nessuna differenza per chi legge
                # la pagina — e con il confronto fra stringhe grezze l'URL
                # passerebbe, diventerebbe la prova indipendente del G7 e in
                # piu' costerebbe una GET.
                if url_notizia in trovate or _stessa_pagina(url_notizia, ufficiale):
                    continue
                if soglia and pertinenza(titolo_notizia) < soglia:
                    continue
                trovate.append(url_notizia)
                if len(trovate) >= MAX_PAGINE_COLLEGATE:
                    return tuple(trovate)

        # F&T: l'identifier si legge dal titolo e dall'URL ufficiale, mai
        # inventato; `url_topic` rifiuta le stringhe che non sono identifier.
        for identifier in sedia.identificatori(f"{titolo} {ufficiale}"):
            url_topic = sedia.url_topic(identifier)
            if url_topic and url_topic not in trovate \
                    and not _stessa_pagina(url_topic, ufficiale):
                trovate.append(url_topic)
            if len(trovate) >= MAX_PAGINE_COLLEGATE:
                break
        return tuple(trovate[:MAX_PAGINE_COLLEGATE])

    return pagine_collegate


def _azzera_scarico() -> None:
    """Inizio giro sul client unico: cache vuota e contatori a zero."""
    try:
        from .scarico import svuota
        svuota()
    except Exception as e:                                # pragma: no cover - ripiego
        logger.debug("[monitor] azzeramento dello scarico fallito: {}", e)


def _contatori_scarico() -> Any:
    """I contatori del client unico (fetch, 304, crediti Firecrawl)."""
    try:
        from .scarico import contatori
        return contatori()
    except Exception as e:                                # pragma: no cover - ripiego
        logger.debug("[monitor] contatori dello scarico non leggibili: {}", e)
        return None


def _azzera_contatori_scarico() -> None:
    """Azzera i soli contatori (la cache del giro resta): `unisci_scarico`
    somma, e senza l'azzeramento ogni riga conterebbe anche le precedenti."""
    try:
        from .scarico import scarico_corrente
        scarico_corrente().azzera_contatori()
    except Exception as e:                                # pragma: no cover - ripiego
        logger.debug("[monitor] azzeramento dei contatori fallito: {}", e)


def _scrivi_telemetria(
    riepilogo: Mapping[str, Any],
    contatori: bilancio.Contatori,
    giro: str | None,
    slug: tuple[str, ...],
    interrotto: bool,
    *,
    tempo: float,
    passo: str = STEP,
) -> None:
    run_riga = telemetria.PipelineRun(step=passo, giro=giro).concludi(
        durata_s=tempo,
        esito=telemetria.esito_da_contatori(
            errori=int(riepilogo.get("errori") or 0),
            # Quante righe il giro ha davvero guardato: sei pagine morte su
            # 420 controllate sono una giornata normale, non un guasto.
            lavorate=int(riepilogo.get("controllati") or 0),
            interrotto_per_tetto=interrotto),
        contatori=dict(riepilogo),
        crediti=contatori.crediti_firecrawl,
        costo_usd=contatori.usd,
        interrotto_per_tetto=interrotto,
        slug_modificati=slug,
    )
    logger.info("[monitor] {}", telemetria.riepilogo(run_riga))
    try:
        telemetria.scrivi_pipeline_run(run_riga)
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[monitor] telemetria non scritta: {}", e)


# --- ombra: report e applicazione differita ---------------------------------

def report_ombra(
    esiti: Sequence[EsitoControllo], *, campione: int = 100, tipo: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Le righe del CSV di `report-ombra`: gate superati e falliti per evento.

    Serve a misurare la precisione prima di attivare: §6.2 chiede >= 95 % su
    >= 100 eventi, e senza i motivi dei respinti non si puo' capire quale gate
    e' troppo severo.
    """
    righe: list[dict[str, Any]] = []
    for esito in esiti:
        for voce in list(esito.eventi) + list(esito.respinti):
            giudizio = voce.get("giudizio") or {}
            riga_evento = voce.get("riga") or {}
            if tipo and riga_evento.get("tipo") != tipo:
                continue
            righe.append({
                "bando_id": esito.bando_id,
                "fase": esito.fase,
                "tipo": riga_evento.get("tipo"),
                "campo": riga_evento.get("campo"),
                "gate": giudizio.get("gate"),
                "ammesso": giudizio.get("ammesso"),
                "confidenza": giudizio.get("confidenza"),
                "superati": ",".join(giudizio.get("superati") or ()),
                "falliti": "; ".join(
                    f"{f.get('gate')}: {f.get('motivo')}" for f in giudizio.get("falliti") or ()),
                "url_prova": riga_evento.get("url_prova"),
                "citazione": norm_cit(str(riga_evento.get("citazione") or ""))[:160],
            })
            if len(righe) >= max(1, campione):
                return tuple(righe)
    return tuple(righe)


def applicabile(
    riga: Mapping[str, Any],
    *,
    dal: date_cls | None = None,
    tipo: str | None = None,
) -> bool:
    """C'e' davvero da applicare questo evento?

    E' il filtro che `applica_eventi` faceva riga per riga dentro il ciclo, e
    che ora serve **anche** alla scansione: solo cosi' il `--limit` conta gli
    eventi da applicare invece delle righe lette.
    """
    nome = str(riga.get("tipo") or "")
    if tipo and nome != tipo:
        return False
    # Gli eventi interni non hanno colonne da applicare e non sono mai
    # leggibili (§13.5, §16.3 punto 4): `elaborazione_bloccata` e
    # `segnale_fonte`, che lo stesso monitor registra, non sono candidati.
    if nome in eventi_mod.TIPI_INTERNI:
        return False
    # Un evento che non ha superato i gate non si applica mai, nemmeno a
    # posteriori: in ombra si raccoglie tutto, anche i respinti. Il default e'
    # **falso**, come `Controllo.ha`: una riga senza la chiave `verificato` e'
    # una riga di cui non si sa niente, e nel dubbio non si applica.
    if not riga.get("verificato"):
        return False
    if dal is not None:
        # Le due date si guardano **entrambe**, come fa `db.select_eventi` con
        # `or_(data_evento.gte, rilevato_at.gte)`: un evento datato dall'ente
        # prima dell'ombra ma rilevato dopo entra comunque. Guardare solo
        # `data_evento` quando c'e' rendeva il filtro Python piu' stretto di
        # quello del DB: quegli eventi consumavano il blocco da 50, venivano
        # scartati, e poiche' la lettura riparte sempre dagli `id` piu' bassi
        # non applicati, il comando ripresentava all'infinito lo stesso blocco
        # applicando zero.
        utili = [d for d in (_data(riga.get("data_evento")),
                             _data(riga.get("rilevato_at"))) if d is not None]
        if not utili or max(utili) < dal:
            return False
    return not riga.get("applicato")


#: Gli esiti di `db.applica_evento_esito`, ricopiati qui perche' questo modulo
#: importa `db` solo dentro le funzioni (il package non regge un import in
#: testa). `test_monitoraggio` verifica che le tre stringhe coincidano: se
#: divergessero, un non-tentativo tornerebbe a passare per rifiuto.
ESITO_APPLICATO = "applicato"
ESITO_RIFIUTATO = "rifiutato"
ESITO_NON_TENTATO = "non_tentato"

#: I tipi che `bando_applica_evento` respinge **per costruzione** finche' la
#: migrazione 06 non estende il CHECK di `stato_bando` a cinque valori. Il loro
#: rifiuto e' un calendario, non un giudizio: annotarlo li toglierebbe per
#: sempre dalla coda, e sono proprio gli eventi che la 06 serve ad applicare.
TIPI_IN_ATTESA_DI_MIGRAZIONE: tuple[str, ...] = (
    "sospensione", "revoca", "annullamento_revoca",
)


def _esito_applicazione(valore: Any) -> str:
    """Normalizza cio' che `applica` ha restituito.

    Il default di produzione torna uno dei tre esiti; i chiamanti storici e i
    test tornano un booleano, e per loro «falso» resta un rifiuto. Vale la pena
    ricordare perche' il booleano non basta: `False` copre sia «la RPC ha detto
    no» sia «la RPC non c'era», e annotare il secondo e' irreversibile.
    """
    if isinstance(valore, str):
        return valore
    return ESITO_APPLICATO if valore else ESITO_RIFIUTATO


def rifiuto_definitivo(
    riga: Mapping[str, Any],
    *,
    stati_estesi: bool = False,
) -> bool:
    """Vero se questo rifiuto va annotato, cioe' se non e' un'attesa.

    Un rifiuto annotato non si disfa: `bando_evento` non concede DELETE
    nemmeno a `service_role` (migrazione 02) e il trigger di immutabilita'
    vieta di cambiare `riferisce_a`. Quindi si annota solo cio' che nessuna
    migrazione futura potrebbe sbloccare.
    """
    if stati_estesi:
        return True
    tipo = str(riga.get("tipo") or "")
    if tipo in TIPI_IN_ATTESA_DI_MIGRAZIONE:
        return False
    # Anche una `rettifica` che propone uno dei due stati nuovi (§6.2, A30:
    # `valore_dopo = {"stato_proposto": ...}`) aspetta la 06.
    dopo = riga.get("valore_dopo")
    if isinstance(dopo, Mapping):
        proposto = str(dopo.get("stato_proposto") or "")
        if proposto in ("sospeso", "revocato"):
            return False
    return True


def applica_eventi(
    righe: Sequence[Mapping[str, Any]],
    *,
    dal: date_cls | None = None,
    tipo: str | None = None,
    limit: int = 50,
    dry_run: bool = True,
    applica: Callable[[Mapping[str, Any]], Any] | None = None,
    segnala: Callable[[Mapping[str, Any]], bool] | None = None,
    stati_estesi: bool = False,
) -> dict[str, Any]:
    """Applica a posteriori gli eventi raccolti in ombra (§6.2).

    Senza questo comando la baseline delle impronte li perderebbe: alla seconda
    lettura la pagina non e' piu' «cambiata», quindi l'evento non si ripresenta.
    Si lavora a blocchi di 50 per giro, e i tipi si attivano uno alla volta
    (prima proroga e rettifiche di data, poi chiusura, poi sospensione e revoca
    dopo R0).

    `segnala` annota il rifiuto in modo che sopravviva al processo (di norma
    `_segnala_rifiuto`): senza, un evento che la RPC non puo' applicare torna
    in testa al blocco al lancio successivo, e a quello dopo. Si chiama solo
    quando il giro scrive davvero: in `--dry-run` non si applica niente, quindi
    non c'e' niente da annotare.

    **E si chiama solo sui rifiuti definitivi.** L'annotazione non si puo'
    togliere (`bando_evento` non concede DELETE nemmeno a `service_role`, e
    `riferisce_a` e' immutabile), quindi annotare un evento che nessuno ha
    giudicato lo escluderebbe per sempre. Due casi vanno esclusi:

    * `db.ESITO_NON_TENTATO` — la RPC non c'e' (migrazione 04 non applicata) o
      la chiamata e' fallita. Senza questa distinzione un solo
      `applica-eventi --attivo` lanciato prima della 04 avrebbe bruciato tutto
      l'arretrato dell'ombra;
    * i tipi di `TIPI_IN_ATTESA_DI_MIGRAZIONE` quando `stati_estesi` e' falso:
      la 04 li respinge **per costruzione** finche' la 06 non estende il CHECK
      a cinque stati. Il loro rifiuto non e' un giudizio sull'evento, e' un
      calendario — e annotarlo toglierebbe dalla coda proprio gli eventi che la
      06 serve ad applicare.
    """
    scelte: list[Mapping[str, Any]] = []
    # `esaminati` e `ultimo_id` sono diagnostica: dicono quanto del blocco
    # letto e' stato guardato e fin dove. Servono a riconoscere il giro che
    # legge 50 righe e ne applica zero, che e' la forma che prende uno stallo.
    esaminati = 0
    ultimo_id: Any = None
    for riga in righe:
        esaminati += 1
        ultimo_id = riga.get("id", ultimo_id)
        if not applicabile(riga, dal=dal, tipo=tipo):
            continue
        scelte.append(riga)
        if len(scelte) >= max(1, limit):
            break

    applicati = 0
    rifiutati = 0
    non_tentati = 0
    segnalati = 0
    if not dry_run and applica is not None:
        for riga in scelte:
            try:
                esito = _esito_applicazione(applica(riga))
            except Exception as e:                        # pragma: no cover - ripiego
                # Un'eccezione non e' un rifiuto: nessuno ha giudicato
                # l'evento, e il lancio successivo deve poterlo riprovare.
                esito = ESITO_NON_TENTATO
                logger.warning("[monitor] applicazione dell'evento {} fallita: {}",
                               riga.get("id"), e)
            if esito == ESITO_APPLICATO:
                applicati += 1
                continue
            if esito == ESITO_NON_TENTATO:
                non_tentati += 1
                continue
            # La RPC ha risposto `false`: transizione non ammessa, stato che il
            # CHECK non ammette, data incoerente. L'evento resta
            # `applicato=false` all'id piu' basso, quindi si conta — un blocco
            # fermo deve vedersi in `pipeline_run` invece di somigliare a un
            # giro riuscito.
            rifiutati += 1
            if segnala is None or not rifiuto_definitivo(riga, stati_estesi=stati_estesi):
                continue
            # L'annotazione e' l'unica cosa che impedisce al lancio successivo
            # di ripresentare lo stesso evento: la RPC la scrive solo sul ramo
            # delle date, quindi qui la scrive Python.
            try:
                if segnala(riga):
                    segnalati += 1
            except Exception as e:                        # pragma: no cover - ripiego
                logger.warning(
                    "[monitor] rifiuto dell'evento {} non annotato: {}",
                    riga.get("id"), e)
    return {
        "status": "ok",
        "esaminati": esaminati,
        "candidati": len(scelte),
        "applicati": applicati,
        "rifiutati": rifiutati,
        "non_tentati": non_tentati,
        "segnalati": segnalati,
        "ultimo_id": ultimo_id,
        "dry_run": dry_run,
        "tipo": tipo,
    }


# --- ombra: ingressi della riga di comando (§6.2) ---------------------------

#: Intestazioni del CSV di `report-ombra`, nell'ordine in cui si leggono.
INTESTAZIONI_REPORT: tuple[str, ...] = (
    "bando_id", "fase", "tipo", "campo", "gate", "ammesso", "confidenza",
    "superati", "falliti", "url_prova", "citazione",
)

#: §6.2: si esce dall'ombra con precisione >= 95 % su >= 100 eventi. I due
#: numeri stanno qui e non nel comando perche' sono la regola, non un'opzione.
SOGLIA_PRECISIONE = 0.95
CAMPIONE_MINIMO = 100

#: Massimo di eventi applicati per giro (§6.2). `--limit` puo' solo abbassarlo:
#: un blocco piu' grande riverserebbe in una volta sola mesi di ombra, e se una
#: transizione fosse sbagliata non ci sarebbe un giro intermedio per accorgersene.
BLOCCO_APPLICAZIONE = 50

#: Quanti eventi si chiedono per pagina mentre si cerca che cosa applicare.
#: Non e' il blocco dell'operatore: e' la finestra su cui si scorre.
PAGINA_SELEZIONE_EVENTI = 200

#: Quanti `elaborazione_bloccata` si leggono per sapere quali eventi la RPC ha
#: gia' rifiutato. Sono pochi per costruzione (un rifiuto per evento, non uno
#: per giro): il tetto e' solo una difesa. Supera le 1 000 righe di
#: `PAGINA_POSTGREST`, quindi la lettura va **scorsa**: con una `.limit(2000)`
#: il server ne restituiva 1 000 senza dirlo e la lista dei rifiuti noti
#: diventava incompleta proprio quando serviva.
TETTO_RIFIUTI_NOTI = 2000

#: Le sole due colonne che servono a riconoscere un rifiuto. `riferisce_a` e'
#: il dato, `id` c'e' perche' `_colonne_disponibili` non restituisca una
#: select vuota su uno schema che non ha ancora la colonna.
COLONNE_RIFIUTO: tuple[str, ...] = ("id", "riferisce_a")

#: I rifiuti noti non entrano tutti nel tetto: da qui in giu' la lista e' una
#: FETTA, e gli eventi che ne restano fuori tornano in coda a ogni lancio.
ALLARME_RIFIUTI_TRONCATI = (
    f"rifiuti gia' noti troncati a {TETTO_RIFIUTI_NOTI} righe: gli eventi "
    "bloccati oltre il tetto riconsumeranno il blocco a ogni lancio"
)

STEP_APPLICA = "applica-eventi"


def _giudizio_da_colonna(valore: Any) -> dict[str, Any]:
    """`bando_evento.gate` letta com'e' scritta, oggi e domani.

    Oggi `riga_evento` ci mette la sola variante di G2 (`"G2"` / `"G2'"`); la
    colonna e' jsonb, quindi un giorno potrebbe contenere l'intero giudizio.
    Il report legge entrambe le forme invece di rompersi sulla seconda.
    """
    if isinstance(valore, Mapping):
        return dict(valore)
    if isinstance(valore, str) and valore:
        return {"gate": valore}
    return {}


def riga_report_da_evento(riga: Mapping[str, Any]) -> dict[str, Any]:
    """Una riga di `bando_evento` nella forma del CSV di `report-ombra`.

    `fase` resta vuota: la fase del ciclo di vita e' un calcolo del giro, non
    una colonna dell'evento, e inventarla qui la renderebbe falsa per ogni
    evento letto a giorni di distanza.
    """
    giudizio = _giudizio_da_colonna(riga.get("gate"))
    falliti = giudizio.get("falliti") or ()
    confidenza = giudizio.get("confidenza", riga.get("confidenza"))
    return {
        "bando_id": riga.get("bando_id"),
        "fase": "",
        "tipo": riga.get("tipo"),
        "campo": riga.get("campo"),
        "gate": giudizio.get("gate"),
        "ammesso": bool(riga.get("verificato")),
        "confidenza": confidenza,
        "superati": ",".join(giudizio.get("superati") or ()),
        "falliti": "; ".join(
            f"{f.get('gate')}: {f.get('motivo')}" for f in falliti
            if isinstance(f, Mapping)
        ),
        "url_prova": riga.get("url_prova"),
        "citazione": norm_cit(str(riga.get("citazione") or ""))[:160],
    }


def report_ombra_da_eventi(
    righe: Sequence[Mapping[str, Any]], *, campione: int = CAMPIONE_MINIMO,
    tipo: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Le righe del CSV a partire da `bando_evento` (comando autonomo).

    Il gemello `report_ombra` lavora sugli esiti in memoria di un giro appena
    concluso, e vede anche i **respinti**, che non arrivano mai a DB: quando
    `report-ombra` gira per conto suo, la misura possibile e' quella sugli
    eventi registrati, e il CSV lo dice senza fingere il resto.
    """
    scelte: list[dict[str, Any]] = []
    for riga in righe:
        if tipo and riga.get("tipo") != tipo:
            continue
        # Gli eventi interni non sono una proposta del classificatore e non
        # hanno mai `verificato`: entrerebbero tutti come `ammesso=False` e
        # affonderebbero la precisione. `applica_eventi` li esclude gia' —
        # l'asimmetria era il difetto, non l'esclusione. Con un
        # `segnale_fonte` per riga cambiata a ogni giro, il registro e' quasi
        # solo interno: misurare su quella popolazione non misura i gate.
        if riga.get("tipo") in eventi_mod.TIPI_INTERNI:
            continue
        scelte.append(riga_report_da_evento(riga))
        if len(scelte) >= max(1, campione):
            break
    return tuple(scelte)


def precisione(righe: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Precisione misurata sul campione e verdetto di §6.2.

    `sufficiente` e' vero solo con **entrambe** le condizioni: 95 % e almeno
    100 eventi. Una precisione del 100 % su tre eventi non apre niente.
    """
    totale = len(righe)
    ammessi = sum(1 for r in righe if r.get("ammesso"))
    quota = round(ammessi / totale, 4) if totale else 0.0
    return {
        "eventi": totale,
        "ammessi": ammessi,
        "respinti": totale - ammessi,
        "precisione": quota,
        "soglia": SOGLIA_PRECISIONE,
        "campione_minimo": CAMPIONE_MINIMO,
        "sufficiente": totale >= CAMPIONE_MINIMO and quota >= SOGLIA_PRECISIONE,
    }


def scrivi_csv(righe: Sequence[Mapping[str, Any]], uscita: Any) -> int:
    """Scrive il CSV con le intestazioni di `INTESTAZIONI_REPORT`.

    `extrasaction="ignore"` perche' le due sorgenti (esiti in memoria e righe di
    `bando_evento`) hanno chiavi leggermente diverse: il CSV resta lo stesso.
    """
    scrittore = csv.DictWriter(
        uscita, fieldnames=list(INTESTAZIONI_REPORT), extrasaction="ignore")
    scrittore.writeheader()
    for riga in righe:
        scrittore.writerow({k: riga.get(k) for k in INTESTAZIONI_REPORT})
    return len(righe)


async def run_report_ombra(
    dry_run: bool = False,
    limit: int | None = None,
    attivo: bool | None = None,
    *,
    campione: int = CAMPIONE_MINIMO,
    tipo: str | None = None,
    dal: date_cls | None = None,
    g7_disponibile: bool = True,
    righe: Sequence[Mapping[str, Any]] | None = None,
    esiti: Sequence[EsitoControllo] | None = None,
    uscita: Any = None,
) -> dict[str, Any]:
    """`report-ombra`: la misura che apre la tappa D (§6.2).

    Non scrive **niente**: legge gli eventi raccolti in ombra e stampa il CSV
    dei gate. `attivo` si accetta per uniformita' con gli altri sottocomandi e
    non ha effetto — un comando di misura che cambiasse comportamento in
    modalita' attiva non sarebbe piu' una misura.

    `--limit` limita le righe **lette**, `--campione` quelle del CSV: sono due
    cose diverse, e confonderle renderebbe impossibile leggere 1 000 eventi per
    campionarne 100.

    `esiti` e' la scorciatoia per chi ha appena finito un giro e ha in mano
    anche i respinti (che a DB non arrivano mai).

    `--dal` e' obbligatorio per misurare un periodo d'ombra: senza, la lettura
    parte dagli `id` piu' bassi e il campione resta per sempre quello dei
    primi 100 eventi mai registrati, cioe' non riflette mai il periodo in
    corso.

    `g7_disponibile=False` dice che il periodo misurato ha girato senza i due
    adattatori del G7. Non e' un default teorico: `_cmd_report_ombra` lo
    calcola (`--senza-g7`, altrimenti la presenza di `ANTHROPIC_API_KEY`, che
    e' la stessa condizione con cui `_adattatori_g7` li costruisce), cosi' la
    guardia qui sotto e' collegata a qualcosa invece di restare scritta.

    Il verdetto (`sufficiente`) si emette **solo** dalla sorgente `esiti`. Da
    `bando_evento` mancano per costruzione i respinti dei tipi proponibili
    (`eventi.applica` esce prima della RPC quando i gate non passano), quindi
    da li' la precisione e' misurata su una popolazione parziale: il CSV resta
    utile, il verdetto no. Stessa cosa se il G7 non e' disponibile: senza i
    due adattatori ogni evento con transizione o con una data e' respinto in
    partenza, e la misura direbbe soltanto questo.
    """
    if esiti is not None:
        elenco = report_ombra(esiti, campione=campione, tipo=tipo)
        sorgente = "esiti"
    else:
        if righe is None:
            from . import db
            # Senza `--limit` si legge quanto serve al campione e non una riga
            # di piu': `bando_evento` e' un registro che cresce e basta, e un
            # comando di misura non deve poterselo portare via tutto.
            righe = db.select_eventi(
                tipi=(tipo,) if tipo else (), dal=dal,
                limit=limit if limit is not None else max(1, campione))
        elenco = report_ombra_da_eventi(righe, campione=campione, tipo=tipo)
        sorgente = "bando_evento"

    try:
        scrivi_csv(elenco, uscita if uscita is not None else sys.stdout)
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[report-ombra] CSV non scritto: {}", e)

    riepilogo = {
        "status": "ok",
        "step": "report-ombra",
        "sorgente": sorgente,
        "campione": campione,
        "tipo": tipo,
        "dal": dal.isoformat() if dal else None,
        "g7_disponibile": bool(g7_disponibile),
        "dry_run": dry_run,
        **precisione(elenco),
    }
    avvertenze: list[str] = []
    if sorgente == "bando_evento" and not any(
            not r.get("ammesso") for r in elenco):
        # L'avvertenza vale solo se nel campione non c'e' **nessun** respinto:
        # da quando `controlla` li registra (con `verificato=false` e il campo
        # `gate`) la misura sui gate e' possibile anche per il comando
        # autonomo. Dirla sempre spegneva il verdetto anche quando i dati
        # c'erano: `sufficiente` sparisce in presenza di avvertenze, quindi
        # un'avvertenza falsa rendeva il periodo d'ombra impossibile da
        # chiudere. Restano fuori i giri precedenti alla correzione.
        avvertenze.append(
            "nel campione non ci sono respinti: i giri anteriori al 24/09/2026 "
            "non li registravano")
    if dal is None and sorgente == "bando_evento":
        avvertenze.append(
            "senza --dal il campione e' quello dei primi eventi registrati")
    if not g7_disponibile:
        avvertenze.append(
            "G7 non disponibile: nessun evento con transizione o con data puo' passare")
    if avvertenze:
        # Niente verdetto: `sufficiente` sparisce invece di valere `False`,
        # cosi' chi legge il JSON non puo' scambiare «non misurabile» per
        # «misurato e insufficiente».
        riepilogo.pop("sufficiente", None)
        riepilogo["avvertenza"] = "; ".join(avvertenze)
    if not elenco:
        # Non e' un errore: in ombra puo' semplicemente non esserci ancora
        # niente da misurare. Dirlo evita di leggere «precisione 0 %» come una
        # bocciatura del monitor.
        riepilogo["saltato"] = "nessun_evento"
    logger.info("[report-ombra] {}", riepilogo)
    return riepilogo


def eventi_gia_rifiutati() -> frozenset[Any]:
    """Gli id degli eventi gia' rifiutati, da `riferisce_a`.

    Il rifiuto e' annotato con un `elaborazione_bloccata` che punta
    all'evento: lo fa `bando_applica_evento` sul ramo delle date incoerenti
    (migrazione 04) e lo fa `_segnala_rifiuto` su tutti gli altri esiti, che in
    SQL non scrivono niente. Quei rifiuti sono **persistenti**: una revoca
    prima della 06, una transizione non ammessa, la RPC che non c'e' ancora —
    e l'evento resta `applicato=false` all'id piu' basso, in testa al blocco,
    a ogni lancio. Senza questa lettura, dodici eventi bloccati restringono il
    blocco da 50 a 38 per sempre.

    Si legge **una sola colonna**: la lettura parte a ogni lancio, anche in
    `--dry-run`, e portarsi dietro `valore_dopo`, `citazione` e il `gate`
    jsonb di duemila righe per estrarre un intero era la parte piu' cara del
    comando. Oltre `TETTO_RIFIUTI_NOTI` il troncamento si **dichiara**: una
    lista incompleta rimette in coda proprio gli eventi che non si possono
    applicare, ed e' il difetto che questa funzione esiste per evitare.
    """
    try:
        from . import db
        righe = db.select_eventi(
            tipi=("elaborazione_bloccata",), limit=TETTO_RIFIUTI_NOTI,
            # Solo le annotazioni di rifiuto: lo stesso tipo lo scrivono anche
            # il monitor dopo cinque fallimenti, i gemelli e
            # `rigenera --malformati`, tutti senza `riferisce_a`. Senza il
            # filtro consumerebbero il tetto e, con l'ordine per `id`
            # crescente, cadrebbero fuori le annotazioni piu' recenti.
            con_riferimento=True,
            colonne=COLONNE_RIFIUTO)
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[applica-eventi] rifiuti gia' noti non leggibili: {}", e)
        return frozenset()
    if len(righe) >= TETTO_RIFIUTI_NOTI:
        logger.warning("[ALLARME] [applica-eventi] {}", ALLARME_RIFIUTI_TRONCATI)
    return frozenset(
        r.get("riferisce_a") for r in righe if r.get("riferisce_a") is not None)


#: Motivo scritto nel `valore_dopo` dell'annotazione di rifiuto. Generico
#: apposta: la RPC risponde `false` (o solleva) senza dire quale dei suoi rami
#: ha preso, e inventare un motivo preciso sarebbe peggio che non darne uno.
MOTIVO_RIFIUTO = "bando_applica_evento non ha applicato l'evento"


def _segnala_rifiuto(riga: Mapping[str, Any]) -> bool:
    """Annota con un `elaborazione_bloccata` l'evento che la RPC non ha applicato.

    `bando_applica_evento` annota il rifiuto **solo** sul ramo delle date
    incoerenti (04:468-487). Gli altri tre esiti che lasciano `applicato=false`
    non scrivono niente: la transizione non ammessa solleva 23514 (che
    `db.applica_evento` cattura e trasforma in `False`), `sospeso`/`revocato`
    prima della migrazione 06 fanno `RETURN false` con la sola `RAISE NOTICE`,
    e se la 04 non e' applicata la RPC non viene nemmeno chiamata. Quegli
    eventi restano `applicato=false, verificato=true` agli id piu' bassi,
    passano `applicabile()` e riconsumano il blocco a **ogni** lancio: due
    `applica-eventi --tipo revoca --attivo --limit 50` di fila riferivano
    «letti: 50, candidati: 50, applicati: 0, rifiutati: 50, bloccati: 0»,
    identici.

    Fra le due strade possibili — tenere in memoria gli id del giro e
    ripartire da `ultimo_id`, oppure scrivere un marcatore — serve la seconda:
    il caso da rompere e' «due lanci di fila», cioe' due processi diversi, e
    un cursore in memoria muore col processo. `riferisce_a` e' anche la forma
    che la RPC usa gia', quindi `eventi_gia_rifiutati` ne legge una sola.

    La guardia di esistenza e' quella della RPC (`bando_id` + tipo +
    `riferisce_a`): senza, un evento respinto sul ramo delle date riceverebbe
    una seconda annotazione, perche' `elaborazione_bloccata` sta fuori dal
    dedup parziale della 02 e `db.registra_evento` e' un INSERT nudo.
    """
    evento_id = riga.get("id")
    bando_id = riga.get("bando_id")
    if evento_id is None or bando_id is None:
        return False
    from . import db
    try:
        if not db.controllo.ha(db.TABELLA_EVENTO, "riferisce_a"):
            # `db.registra_evento` scarta le chiavi che lo schema non espone:
            # un marcatore senza `riferisce_a` sarebbe invisibile a
            # `eventi_gia_rifiutati`, quindi `bando_evento` crescerebbe di una
            # riga per evento a **ogni** lancio senza sbloccare niente.
            logger.info(
                "[applica-eventi] {} senza colonna `riferisce_a`: rifiuto non annotato",
                db.TABELLA_EVENTO)
            return False
        gia = db.select_eventi(
            bando_id=bando_id, tipi=("elaborazione_bloccata",),
            colonne=COLONNE_RIFIUTO)
        if any(r.get("riferisce_a") == evento_id for r in gia):
            return False
        return bool(db.registra_evento({
            "bando_id": bando_id,
            "tipo": "elaborazione_bloccata",
            "origine": "pipeline",
            "campo": riga.get("campo"),
            "valore_dopo": {"evento_id": evento_id, "motivo": MOTIVO_RIFIUTO},
            "riferisce_a": evento_id,
            # Interno per definizione (§13.5): mai un cursore, mai leggibile,
            # mai verificato (il CHECK della 02 vorrebbe prova e citazione).
            "leggibile": False,
            "in_aggiornamenti": False,
            "verificato": False,
            "applicato": False,
        }))
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning(
            "[applica-eventi] rifiuto dell'evento {} non annotato: {}", evento_id, e)
        return False


def _da_applicare(
    righe: Sequence[Mapping[str, Any]] | None,
    *,
    tipi: Sequence[str],
    dal: date_cls | None,
    limit: int,
    offset: int,
    rifiutati: frozenset[Any],
    conto: dict[str, int],
) -> list[Mapping[str, Any]]:
    """Gli eventi su cui c'e' lavoro, scorrendo la selezione a pagine.

    Gemello di `fonte_ufficiale._da_leggere`. Il `--limit` era il limite della
    SELECT, cioe' contava le righe lette: gli eventi che la RPC rifiuta e
    quelli che i filtri Python scartano occupavano una fetta del blocco a ogni
    lancio, e con cinquanta eventi bloccati il comando riferiva
    «letti: 50, candidati: 50, applicati: 0» per sempre, con exit 0.
    """
    if righe is not None:
        return [dict(r) for r in righe]
    from . import db
    raccolti: list[Mapping[str, Any]] = []
    cursore = max(0, int(offset or 0))
    while True:
        try:
            pagina = db.select_eventi(
                tipi=tuple(tipi), dal=dal, applicato=False, verificato=True,
                limit=PAGINA_SELEZIONE_EVENTI, offset=cursore,
            )
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[applica-eventi] lettura degli eventi fallita: {}", e)
            break
        if not pagina:
            break
        cursore += len(pagina)
        for riga in pagina:
            conto["attraversati"] += 1
            if riga.get("id") in rifiutati:
                # Gia' rifiutato da un giro precedente e l'annotazione e' in
                # tabella: riproporlo significherebbe solo riconsumare il
                # blocco, giro dopo giro.
                conto["bloccati"] += 1
                continue
            if not applicabile(riga, dal=dal):
                conto["saltati"] += 1
                continue
            raccolti.append(riga)
            if len(raccolti) >= max(0, limit):
                return raccolti
        if len(pagina) < PAGINA_SELEZIONE_EVENTI:
            break
    return raccolti


async def run_applica_eventi(
    dry_run: bool = False,
    limit: int | None = None,
    attivo: bool | None = None,
    *,
    dal: date_cls | None = None,
    tipi: Sequence[str] = (),
    offset: int = 0,
    riprova_rifiutati: bool = False,
    righe: Sequence[Mapping[str, Any]] | None = None,
    applica: Callable[[Mapping[str, Any]], Any] | None = None,
    segnala: Callable[[Mapping[str, Any]], bool] | None = None,
    impostazioni: Any = None,
    lock: Any = blocco,
) -> dict[str, Any]:
    """`applica-eventi`: riversa a posteriori gli eventi raccolti in ombra (§6.2).

    Senza questo comando la baseline delle impronte li perderebbe: alla lettura
    successiva la pagina non e' piu' «cambiata», l'evento non si ripresenta e
    la proroga resterebbe fuori dalle colonne per sempre.

    Il `--limit` conta gli eventi da applicare: la selezione si scorre a
    pagine e gli eventi che la RPC ha gia' rifiutato — una revoca prima della
    migrazione 06, una `data_pubblicazione` dopo la scadenza — non consumano
    piu' il blocco a ogni lancio. `--offset N` fa ripartire lo scorrimento
    oltre i primi N eventi della selezione.

    Un rifiuto **nuovo** viene annotato (`segnalati` nel riepilogo): e' cosi'
    che il lancio successivo lo riconosce come `bloccati` invece di
    riproporlo. In `--dry-run` niente viene applicato e quindi niente viene
    annotato: il lancio dopo ripresenta gli stessi candidati, ed e' giusto,
    perche' nulla e' stato tentato.

    Tre cautele, tutte volute:
      * si lavora a blocchi di al massimo `BLOCCO_APPLICAZIONE`;
      * i tipi si attivano **uno alla volta** (`--tipo`): senza, il primo giro
        applicherebbe anche `sospensione` e `revoca`, che prima della 06 non
        hanno una colonna dove andare;
      * ombra per difetto: senza `--attivo` il comando dice che cosa
        applicherebbe e non tocca niente.

    Prende lo stesso lock del monitor: applicare un evento e ricontrollare la
    stessa pagina scrivono le stesse colonne, e due scrittori insieme
    renderebbero il diff del giro successivo illeggibile.
    """
    avvio = time.monotonic()
    if impostazioni is None:
        try:
            from .settings import get_settings
            impostazioni = get_settings()
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[applica-eventi] impostazioni non leggibili: {}", e)
            impostazioni = None
    modalita = _modalita_richiesta(attivo, impostazioni)
    if dry_run:
        modalita = eventi_mod.MODALITA_OMBRA
    scrive = modalita == eventi_mod.MODALITA_ATTIVO and not dry_run

    blocco_giro = BLOCCO_APPLICAZIONE if limit is None else max(
        0, min(int(limit), BLOCCO_APPLICAZIONE))

    preso = lock.acquisisci(NOME_LOCK, f"{STEP_APPLICA}:cli", blocco.TTL_PREDEFINITO_S)
    if not preso.proseguire:
        return lock.esito_saltato(preso)
    conto = {"attraversati": 0, "saltati": 0, "bloccati": 0}
    try:
        # Il `--limit` conta gli eventi da applicare, non le righe lette: la
        # selezione si scorre a pagine e gli eventi gia' rifiutati dalla RPC
        # (che restano `applicato=false` all'id piu' basso, per sempre) non
        # consumano il blocco.
        candidati = _da_applicare(
            righe, tipi=tipi, dal=dal, limit=blocco_giro, offset=offset,
            # Con `--limit 0` non si applica niente per costruzione (il ciclo
            # piu' sotto esce al primo giro): leggere i rifiuti noti sarebbe
            # una richiesta in piu' per un comando che e' un no-op.
            # `--riprova-rifiutati` e' la via di rientro, e serve perche'
            # l'annotazione non si puo' togliere: `bando_evento` non concede
            # DELETE nemmeno a `service_role` e `riferisce_a` e' immutabile.
            # Senza, un rifiuto annotato per sbaglio resterebbe tale per sempre.
            rifiutati=(eventi_gia_rifiutati()
                       if righe is None and blocco_giro > 0
                       and not riprova_rifiutati else frozenset()),
            conto=conto,
        )
        if applica is None and scrive:
            from . import db

            def applica(riga: Mapping[str, Any]) -> str:
                """L'unico scrittore: la RPC `bando_applica_evento` (§6.2).

                Si costruisce solo quando il giro scrive davvero, cosi' in
                ombra la RPC non e' nemmeno raggiungibile. Restituisce l'esito
                e non un booleano: chi annota il rifiuto deve poter distinguere
                «la RPC ha detto no» da «la RPC non c'era».
                """
                return db.applica_evento_esito(riga.get("id"))

            if segnala is None:
                # Chi inietta il proprio `applica` (i test, la pipeline) porta
                # anche la propria annotazione: qui non si scrive per lui.
                segnala = _segnala_rifiuto

        gruppi: tuple[str | None, ...] = tuple(tipi) if tipi else (None,)
        candidati_totali = 0
        applicati = 0
        rifiutati = 0
        non_tentati = 0
        segnalati = 0
        rimanenti = blocco_giro
        # Prima della 06 i due stati nuovi non hanno una colonna dove andare:
        # la RPC li respinge, e quel rifiuto non va annotato (vedi
        # `rifiuto_definitivo`).
        stati_estesi = bool(getattr(impostazioni, "monitor_stati_estesi", False))
        per_tipo: dict[str, int] = {}
        for nome in gruppi:
            if rimanenti <= 0:
                break
            esito = applica_eventi(
                candidati, dal=dal, tipo=nome, limit=rimanenti,
                dry_run=not scrive, applica=applica, segnala=segnala,
                stati_estesi=stati_estesi,
            )
            candidati_totali += int(esito.get("candidati") or 0)
            applicati += int(esito.get("applicati") or 0)
            rifiutati += int(esito.get("rifiutati") or 0)
            non_tentati += int(esito.get("non_tentati") or 0)
            segnalati += int(esito.get("segnalati") or 0)
            rimanenti -= int(esito.get("candidati") or 0)
            per_tipo[nome or "tutti"] = int(esito.get("candidati") or 0)

        riepilogo = {
            "status": "ok",
            "step": STEP_APPLICA,
            "modalita": modalita,
            "dry_run": dry_run,
            "dal": dal.isoformat() if dal else None,
            "tipi": list(tipi),
            "blocco": blocco_giro,
            "offset": max(0, int(offset or 0)),
            "riprova_rifiutati": bool(riprova_rifiutati),
            "letti": len(candidati),
            "candidati": candidati_totali,
            "applicati": applicati,
            # Un blocco fermo deve vedersi: `rifiutati` sono gli eventi che la
            # RPC non ha potuto applicare, `segnalati` quelli di cui il rifiuto
            # e' stato annotato adesso (e che al lancio successivo saranno
            # `bloccati`), `bloccati` quelli gia' rifiutati in un giro
            # precedente e quindi scavalcati dallo scorrimento.
            "rifiutati": rifiutati,
            # `non_tentati` sono gli eventi che nessuno ha giudicato: RPC
            # assente o chiamata fallita. Non vengono annotati e il lancio
            # successivo li ripresenta — se sono tanti, manca una migrazione.
            "non_tentati": non_tentati,
            "segnalati": segnalati,
            "attraversati": conto["attraversati"],
            "bloccati": conto["bloccati"],
            "saltati": conto["saltati"],
            "per_tipo": per_tipo,
            "saltato_per_lock": False,
            "interrotto_per_tetto": False,
            "durata_s": round(time.monotonic() - avvio, 1),
        }
        _scrivi_run(STEP_APPLICA, riepilogo, tempo=time.monotonic() - avvio)
        logger.info("[applica-eventi] {}", riepilogo)
        return riepilogo
    except Exception as e:
        # Come in `run()`: il traceback va dentro il messaggio, che e' l'unica
        # cosa che passa dalla redazione.
        logger.error(
            "[applica-eventi] giro fallito: {}\n{}", e,
            "".join(traceback.format_exception(type(e), e, e.__traceback__)).rstrip(),
        )
        return {"status": "errore", "motivo": str(e), "applicati": 0,
                "saltato_per_lock": False, "interrotto_per_tetto": False}
    finally:
        lock.rilascia(preso)


def _scrivi_run(step: str, riepilogo: Mapping[str, Any], *, tempo: float) -> None:
    """Una riga in `pipeline_run` per i comandi che non sono un giro di monitor."""
    riga = telemetria.PipelineRun(step=step).concludi(
        durata_s=tempo,
        esito=telemetria.esito_da_contatori(errori=int(riepilogo.get("errori") or 0)),
        contatori=dict(riepilogo),
    )
    try:
        telemetria.scrivi_pipeline_run(riga)
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[{}] telemetria non scritta: {}", step, e)


__all__ = [
    "ALLARME_RIFIUTI_TRONCATI", "BLOCCO_APPLICAZIONE", "CAMPIONE_MINIMO",
    "COLONNE_RIFIUTO", "INTESTAZIONI_REPORT", "MOTIVO_RIFIUTO",
    "TETTO_RIFIUTI_NOTI",
    "PAGINA_SELEZIONE_EVENTI", "SOGLIA_PRECISIONE", "STEP_APPLICA",
    "applicabile", "eventi_gia_rifiutati", "precisione", "report_ombra_da_eventi",
    "riga_report_da_evento", "run_applica_eventi", "run_report_ombra",
    "scrivi_csv",
    "BACKOFF_BASE_ORE", "BACKOFF_MASSIMO_ORE", "BONUS_EVENTO_IN_ATTESA",
    "BONUS_SEGNALE_FONTE", "BONUS_SEGNALE_MACCHINA", "CODA_CHIUSO",
    "COLONNE_CONTROLLO", "CONTROLLI_PER_CALMA", "EsitoControllo",
    "FALLIMENTI_PER_BLOCCO", "FASE_APERTO_LONTANO", "FASE_APERTO_MEDIO",
    "FASE_APERTO_VICINO", "FASE_CHIUSO", "FASE_IAP_IGNOTA",
    "FASE_IAP_LONTANA", "FASE_IAP_RAGGIUNTA", "FASE_IAP_VICINA",
    "FASE_REVOCATO", "FASE_SOSPESO", "FASE_SPORTELLO", "FASI", "FREQUENZE",
    "EsitoAllegato", "FonteDati", "FonteDatiSupabase", "JITTER",
    "MAX_PAGINE_COLLEGATE", "NOME_LOCK", "PRIORITA_FASE", "STEP",
    "STATO_FONTE_TROVATA", "VOLATILITA_MAX", "VOLATILITA_MIN",
    "MAX_TOKEN_CLASSIFICATORE", "MAX_TOKEN_SECONDA_OPINIONE",
    "MODELLO_CLASSIFICATORE", "MODELLO_SECONDA_OPINIONE", "PREFISSO_BYTEA",
    "COPERTURA_RICERCA_WP", "GIORNI_RICERCA_WP", "PAROLE_VUOTE_RICERCA",
    "SOGLIA_TITOLI_COLLEGATE", "TOKEN_RICERCA_WP",
    "applica_eventi", "classificatore_da_impostazioni", "comprimi_testo",
    "controlla", "controlla_allegati", "news_url_per_host",
    "pagine_collegate_da_impostazioni", "seconda_opinione_da_impostazioni",
    "da_db", "fase", "frequenza", "giorni_chiuso", "moltiplicatore_volatilita",
    "ordina_proposte", "priorita", "prossimo_controllo", "prossimo_dopo_errore",
    "replace_contesto", "report_ombra", "run", "seleziona", "selezionabile",
    "testo_da_colonna",
]
