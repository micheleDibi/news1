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
import functools
import json
import random
import re
import sys
import time
import traceback
import zlib
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date as date_cls, datetime, timedelta
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

from . import bilancio, blocco, eventi as eventi_mod, impronte, rigenera as rigenera_mod, sedia, telemetria
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
#: `scarico.REDIRECT_STESSO_HOST` (un test li confronta): le pagine collegate e
#: le notizie seguono i redirect solo sullo stesso host (§19.6). Copiata e non
#: importata: `monitoraggio` non deve fallire per un import dello scarico.
REDIRECT_STESSO_HOST = "stesso_host"
#: Il motivo di un controllo interrotto da un'eccezione (§19.3): esito
#: `errore` di quel bando, che non conta fra i fatti della copertura.
PREFISSO_ECCEZIONE = "eccezione: "

MAX_PAGINE_COLLEGATE = 2

#: Quanti host irraggiungibili la riga del giro elenca per nome (come nel
#: resolver): oltre si legge solo il numero.
MAX_HOST_IRRAGGIUNGIBILI_ELENCO = 20

#: Il tetto di tempo del giro se `Settings.tempo_monitor_s` manca (giro 3, §3):
#: l'unico freno del monitor oltre alla spesa, con la rotazione.
TEMPO_MONITOR_S = 3600

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
        testo = valore.strip().replace("Z", "+00:00")
        # PostgREST manda anche frazioni a 1-5 cifre («…12.87927+00:00»), che
        # `fromisoformat` di Python 3.10 rifiuta: si portano a sei, come in
        # `telemetria._istante`. Un istante illeggibile varrebbe «mai
        # controllato» e scavalcherebbe la rotazione (giro 3, §5).
        testo = _FRAZIONE_RE.sub(lambda m: "." + (m.group(1) + "000000")[:6], testo, count=1)
        try:
            return adesso_roma(datetime.fromisoformat(testo))
        except ValueError:
            return None
    return None


_FRAZIONE_RE = re.compile(r"\.(\d+)")


def _giorno_di(valore: Any) -> date_cls | None:
    istante = _istante(valore)
    return istante.date() if istante else None


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


def selezionabile(
    riga: Mapping[str, Any], *, adesso: datetime | None = None, forza: bool = False,
) -> bool:
    """Il bando entra nella coda dei controlli? (§6.2, A33, giro 3 §5)

    Tre condizioni di base. La terza e' quella che tiene fuori i «solo-OE»: un
    bando la cui fonte ufficiale non e' `trovata` **non** si fetcha dal monitor,
    perche' l'unico URL che abbiamo e' quello dell'aggregatore. Quei bandi li
    ripassa il resolver, alla sua cadenza.

    Poi la fase (giro 3, §5, regola «niente lotti»):
    - aperto, in apertura (quindi anche «da verificare») e sospeso: **a ogni
      giro**, senza guardare `prossimo_controllo_at`;
    - chiuso: la cadenza decrescente (`giorni_chiuso`, 3/10/30 poi 30) fino a
      12 mesi, cioe' `prossimo_controllo_at`;
    - revocato, e chiuso da oltre 12 mesi (`frequenza` None): **fuori**. Prima
      rientravano a ogni giro, perche' una frequenza None non scriveva un
      prossimo controllo.

    `forza` toglie **solo** la cadenza dei chiusi. Il resto vale anche a mano:
    un non pubblicato, un doppione fuso o un bando senza fonte ufficiale non
    hanno niente di lecito da scaricare, e un revocato non si ricontrolla.
    Serve quando le regole sono cambiate sotto le righe — una correzione ai
    gate, alla whitelist o al payload — e aspettare la cadenza vorrebbe dire
    aspettare giorni: misurato il 25/09/2026, dopo la semina la coda era vuota
    fino al pomeriggio (0 candidati alle 09:15, 56 alle 18:00) e non c'era modo
    di verificare una correzione appena fatta.
    """
    if not riga.get("pubblicato", True):
        return False
    if riga.get("bando_master_id") is not None:
        return False
    if riga.get("fonte_ufficiale_stato") != STATO_FONTE_TROVATA:
        return False
    momento = adesso_roma(adesso)
    corrente = fase(riga, oggi=momento.date())
    if corrente == FASE_REVOCATO:
        return False
    if corrente != FASE_CHIUSO:
        return True
    if frequenza(riga, oggi=momento.date()) is None:
        return False
    if forza:
        return True
    quando = _istante(riga.get("prossimo_controllo_at"))
    return quando is None or quando <= momento


def seleziona(
    righe: Iterable[Mapping[str, Any]],
    *,
    tetto: int = 0,
    adesso: datetime | None = None,
    forza: bool = False,
) -> tuple[Mapping[str, Any], ...]:
    """I bandi da controllare in questo giro, nell'ordine del giro 3 (§5).

    `ORDER BY priorita DESC, ultimo_controllo_at (mai controllato primo), id`:
    la priorita' decide chi passa prima quando il tempo del giro
    (`TEMPO_MONITOR_S`) finisce, l'ultimo controllo fa la rotazione (chi resta
    fuori ha il controllo piu' vecchio e parte per primo al giro dopo), e `id`
    rende l'ordine riproducibile. `tetto` serve solo a `--limit` della riga di
    comando: il giro non lo passa (nessun tetto di numero, §1).
    """
    momento = adesso_roma(adesso)
    ammessi = [r for r in righe if selezionabile(r, adesso=momento, forza=forza)]

    def chiave(riga: Mapping[str, Any]) -> tuple[int, int, float, int]:
        ultimo = _istante(riga.get("ultimo_controllo_at"))
        try:
            identificativo = int(riga.get("id") or 0)
        except (TypeError, ValueError):
            identificativo = 0
        # Il confronto sull'istante, non sul testo: due offset diversi
        # (+00:00 e +02:00) ordinerebbero male come stringhe.
        return (-priorita(riga, oggi=momento.date()), 0 if ultimo is None else 1,
                ultimo.timestamp() if ultimo is not None else 0.0, identificativo)

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
    consumo: dict[str, float] | None = field(default_factory=dict)
    scritture: list[tuple[Any, dict[str, Any]]] = field(default_factory=list)
    registrati: list[dict[str, Any]] = field(default_factory=list)
    #: Allarmi raccolti durante la selezione (§6.2): finiscono nel riepilogo e
    #: quindi in `pipeline_run`, non solo in una riga di log che nessuno rilegge.
    allarmi: list[str] = field(default_factory=list)
    #: Le tre scritture dell'attivazione per tipo, nell'ordine in cui avvengono.
    registrati_rpc: list[dict[str, Any]] = field(default_factory=list)
    applicati: list[Any] = field(default_factory=list)
    #: La migrazione 14 c'e'? (`db.capacita_sospensioni`, giro 3 §3 e §14).
    sospensioni: bool = False
    #: I bandi rimessi in coda alla rielaborazione (`azzera_rielaborazione`).
    azzerati: list[Any] = field(default_factory=list)
    #: Le righe `bando_link` dei `nuovo_allegato` (giro 3, §6).
    link_allegati: list[dict[str, Any]] = field(default_factory=list)
    #: `scartato_per` degli eventi marcati dalla RPC della 14 (giro 3, §14).
    scartati: dict[Any, str] = field(default_factory=dict)
    resi_leggibili: list[tuple[Any, bool]] = field(default_factory=list)

    def disponibile(self) -> tuple[bool, str]:
        return True, ""

    def candidati(
        self, *, limite: int = 0, adesso: datetime | None = None, forza: bool = False,
    ) -> list[dict[str, Any]]:
        return [dict(r) for r in seleziona(
            self.righe, tetto=limite, adesso=adesso, forza=forza)]

    def eventi_recenti(self, bando_id: Any, giorni: int = 30) -> list[dict[str, Any]]:
        return list(self.eventi.get(bando_id, ()))

    def consumo_oggi(self) -> dict[str, float] | None:
        # None = lettura fallita (§18.5): i test lo simulano con `consumo=None`.
        return None if self.consumo is None else dict(self.consumo)

    def salva_controllo(self, bando_id: Any, payload: dict[str, Any]) -> bool:
        self.scritture.append((bando_id, dict(payload)))
        return True

    def registra_evento(self, riga: Mapping[str, Any]) -> bool:
        self.registrati.append(dict(riga))
        return True

    def registra_evento_esito(self, riga: Mapping[str, Any]) -> str:
        """Tre esiti invece di un booleano: chi conta il lavoro fatto deve
        distinguere «il database ha rifiutato» da «c'era gia'»."""
        from . import db
        return db.EVENTO_SCRITTO if self.registra_evento(riga) else db.EVENTO_RIFIUTATO

    # --- attivazione per tipo (MONITOR_TIPI_ATTIVI, contratto §3) -----------

    def registra_evento_rpc(self, riga: Mapping[str, Any]) -> dict[str, Any] | None:
        """Registra senza applicare: `{id, nuovo}`, None se la RPC non c'e'."""
        self.registrati_rpc.append(dict(riga))
        return {"id": len(self.registrati_rpc), "nuovo": True}

    def evento_verificato(self, evento_id: Any, riga: Mapping[str, Any]) -> bool | None:
        """`verificato` come l'ha calcolato il DB alla registrazione; None se
        non si puo' leggere. Qui: vero, se la riga lo era."""
        return bool(riga.get("verificato", True))

    def applica_evento(self, evento_id: Any) -> str:
        """`bando_applica_evento`: uno degli esiti di `db.applica_evento_esito`."""
        from . import db
        self.applicati.append(evento_id)
        return db.ESITO_APPLICATO

    def rendi_leggibile(self, evento_id: Any, *, in_aggiornamenti: bool = True) -> bool:
        """La seconda scrittura: `leggibile` fa scattare il cursore (RIPRESA §5.8)."""
        self.resi_leggibili.append((evento_id, bool(in_aggiornamenti)))
        return True

    def testi_del_bando(self, bando_id: Any) -> dict[str, Any] | None:
        """`contenuto` e `descrizione_breve` del bando, per la rigenerazione
        della prosa; None se non si leggono. Qui: quelli della riga in `righe`."""
        for riga in self.righe:
            if riga.get("id") == bando_id and "contenuto" in riga:
                return {"contenuto": riga.get("contenuto"),
                        "descrizione_breve": riga.get("descrizione_breve")}
        return None

    # --- giro 3 (contratto `bandi-giro-3` §3, §5, §9) ------------------------

    def capacita_sospensioni(self) -> bool:
        """La migrazione 14 e' applicata? Senza, sospensione, revoca e
        annullamento restano in ombra anche con `MONITOR_TIPI_ATTIVI=tutti`."""
        return bool(self.sospensioni)

    def azzera_rielaborazione(self, bando_id: Any) -> bool:
        """Rimette il bando in coda al passo `rielaborazione` (§5, §9)."""
        self.azzerati.append(bando_id)
        return True

    def registra_link_allegato(self, bando_id: Any, url: str, url_prova: str) -> bool:
        """Una riga `bando_link` `allegato` per un `nuovo_allegato` (§6)."""
        self.link_allegati.append(riga_link_allegato(bando_id, url, url_prova))
        return True

    def motivo_scarto(self, evento_id: Any) -> str | None:
        """`scartato_per` dell'evento (superato | transizione_non_ammessa), o None."""
        return self.scartati.get(evento_id)


def motivo_scarto_da_db(evento_id: Any, **kwargs: Any) -> str | None:
    """`bando_evento.scartato_per` di un evento: una GET (giro 3, §14).

    Dopo un `false` della RPC distingue l'evento marcato (superato,
    transizione non ammessa: non torna in coda) dal rifiuto di prima. Senza la
    14 la colonna non c'e' e la select non la chiede: None. Una lettura vuota o
    fallita vale None, cioe' «non applicato» come prima, senza eccezioni.
    """
    if evento_id is None:
        return None
    try:
        from . import db
        righe = db.select_eventi(ids=(evento_id,), colonne=("id", COLONNA_SCARTATO), **kwargs)
    except Exception as e:
        logger.warning("[monitor] scartato_per dell'evento {} non leggibile: {}", evento_id, e)
        return None
    for riga in righe or ():
        if riga.get("id") == evento_id and riga.get(COLONNA_SCARTATO):
            return str(riga[COLONNA_SCARTATO])
    return None


#: La colonna della 14 che marca un evento che la RPC non applichera' mai.
COLONNA_SCARTATO = "scartato_per"


def riga_link_allegato(bando_id: Any, url: str, url_prova: str) -> dict[str, Any]:
    """La riga `bando_link` di un documento comparso sulla pagina ufficiale.

    `origine='ente'` (l'abbiamo letto sulla pagina dell'ente), mai
    pubblicabile da qui: lo diventa solo dopo `link_verifica` (§10).
    """
    return {"bando_id": bando_id, "url": url, "tipo": "allegato", "origine": "ente",
            "url_prova": url_prova or None, "pubblicabile": False}


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

    def candidati(
        self, *, limite: int = 0, adesso: datetime | None = None, forza: bool = False,
    ) -> list[dict[str, Any]]:
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
        scelte = [dict(r) for r in seleziona(
            unite, tetto=limite, adesso=adesso, forza=forza)]
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

    def consumo_oggi(self) -> dict[str, float] | None:
        # None se la lettura fallisce (§18.5): per il monitor vale tetto
        # raggiunto, non «niente speso».
        from . import db
        try:
            return db.consumo_oggi(client=self._client, strumento=self._adattatore())
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[monitor] consumo di oggi non leggibile: {}", e)
            return None

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
        return self.registra_evento_esito(riga) == db.EVENTO_SCRITTO

    def registra_evento_esito(self, riga: Mapping[str, Any]) -> str:
        from . import db
        try:
            return db.registra_evento_esito(
                riga, client=self._client, strumento=self._adattatore())
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[monitor] evento {} non registrato: {}", riga.get("tipo"), e)
            return db.EVENTO_RIFIUTATO

    # Le tre scritture dell'attivazione per tipo: ridefinite anche queste, per
    # la stessa ragione della docstring.

    def registra_evento_rpc(self, riga: Mapping[str, Any]) -> dict[str, Any] | None:
        client = self._client
        rpc = (lambda nome, parametri: client.rpc(nome, parametri).execute()) if client else None
        return eventi_mod.registra_via_rpc(riga, rpc=rpc, controllo=self._adattatore())

    def evento_verificato(self, evento_id: Any, riga: Mapping[str, Any]) -> bool | None:
        # La RPC di registrazione restituisce {id, nuovo, applicato}, non
        # `verificato`: si rilegge la riga appena scritta, per id.
        from . import db
        try:
            righe = db.select_eventi(
                ids=(evento_id,), colonne=("id", "verificato"), client=self._client,
                strumento=self._adattatore())
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[monitor] verificato dell'evento {} illeggibile: {}", evento_id, e)
            return None
        for letta in righe:
            if letta.get("id") == evento_id:
                return bool(letta.get("verificato"))
        return None

    def applica_evento(self, evento_id: Any) -> str:
        from . import db
        return db.applica_evento_esito(
            evento_id, client=self._client, strumento=self._adattatore())

    def rendi_leggibile(self, evento_id: Any, *, in_aggiornamenti: bool = True) -> bool:
        from . import db
        try:
            esito = db.rendi_evento_leggibile(
                evento_id, in_aggiornamenti=in_aggiornamenti, strumento=self._adattatore())
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[monitor] evento {} non reso leggibile: {}", evento_id, e)
            return False
        return bool(esito.get("scritto"))

    def testi_del_bando(self, bando_id: Any) -> dict[str, Any] | None:
        # La stessa lettura del lotto L7 (`select_bandi_pubblicati_contenuto`),
        # per un solo id.
        from . import db
        try:
            righe = db.select_bandi_pubblicati_contenuto(
                bando_ids=[bando_id], client=self._client, strumento=self._adattatore())
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[monitor] contenuto del bando {} illeggibile: {}", bando_id, e)
            return None
        for riga in righe:
            if riga.get("id") == bando_id:
                return {"contenuto": riga.get("contenuto"),
                        "descrizione_breve": riga.get("descrizione_breve")}
        return None

    def capacita_sospensioni(self) -> bool:
        # `db.capacita_sospensioni` torna False se la RPC manca o fallisce.
        from . import db
        funzione = getattr(db, "capacita_sospensioni", None)
        if not callable(funzione):
            return False
        try:
            return funzione(client=self._client, strumento=self._adattatore()) is True
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[monitor] marcatore della migrazione 14 illeggibile: {}", e)
            return False

    def motivo_scarto(self, evento_id: Any) -> str | None:
        return motivo_scarto_da_db(evento_id, client=self._client, strumento=self._adattatore())

    def registra_link_allegato(self, bando_id: Any, url: str, url_prova: str) -> bool:
        # §18.6: il documento viene dal diff o dal `valore_dopo` del modello,
        # e `link_verifica` lo chiedera' con HEAD/GET a ogni giro. Un host che
        # risolve a loopback, rete privata, link-local o comunque non pubblico
        # non entra in `bando_link`. DNS sincrono: succede solo per un
        # `nuovo_allegato` applicato.
        from . import db, http as http_mod
        if not http_mod.indirizzo_pubblico(url):
            logger.warning("[monitor] allegato del bando {} non registrato: indirizzo non pubblico",
                           bando_id)
            return False
        try:
            return db.upsert_bando_link([riga_link_allegato(bando_id, url, url_prova)],
                                        client=self._client, strumento=self._adattatore()) > 0
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[monitor] link dell'allegato del bando {} non scritto: {}", bando_id, e)
            return False

    def azzera_rielaborazione(self, bando_id: Any) -> bool:
        # Arriva con B4 (`db.azzera_rielaborazione`): finche' manca, non si fa
        # niente e il bando aspetta la rielaborazione per id.
        from . import db
        funzione = getattr(db, "azzera_rielaborazione", None)
        if not callable(funzione):
            return False
        try:
            esito = funzione(bando_id)
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[monitor] marcatore della rielaborazione del bando {} non azzerato: {}",
                           bando_id, e)
            return False
        # `db.azzera_rielaborazione` risponde sempre con un dict: vero solo se
        # ha scritto davvero (§18.8), non se ha solo risposto.
        return isinstance(esito, Mapping) and bool(esito.get("scritto"))


def da_db() -> FonteDati:
    """La fonte dati di produzione."""
    return FonteDatiSupabase()


# --- esito di un singolo controllo ------------------------------------------

@dataclass
class EsitoControllo:
    """Che cosa e' successo su un bando. E' anche la riga del report d'ombra."""
    bando_id: Any = None
    fase: str = ""
    esito: str = "ok"            # ok | 304 | invariato | errore | saltato | rinviato
    motivo: str = ""
    fetch: int = 0
    diff_rilevante: bool = False
    classificato: bool = False
    #: La chiamata al modello e' partita ma e' fallita (credito esaurito, API
    #: giu'). Non e' una classificazione senza eventi: il controllo non salva
    #: niente, cosi' la modifica della pagina si ripresenta al giro dopo.
    classificazione_fallita: bool = False
    #: La pagina e' cambiata ma il tetto di spesa e' raggiunto (giro 3, §5): il
    #: modello non si chiama e, come per una classificazione fallita, nessuna
    #: colonna si salva, cosi' il cambiamento si rivede al giro dopo. Non e' un
    #: errore: non accende `classificazione_non_disponibile` in `salute`.
    classificazione_rinviata: bool = False
    #: A tetto raggiunto la pagina chiedeva il ripiego Firecrawl (WAF, JS): non
    #: si e' letta e non si e' salvato niente (giro 3, §4).
    scarico_rinviato: bool = False
    #: Un evento applicato ha rimesso il bando in coda alla rielaborazione
    #: (`azzera_rielaborazione`, giro 3 §5 e §9).
    rielaborazione_richiesta: bool = False
    #: Giro 3 (§6): le novita' di questo controllo che chiedono la riscrittura
    #: della scheda con Opus, e com'e' andata (`rigenera.ESITO_*`, oppure
    #: `abbandonata` dopo `TENTATIVI_RISCRITTURA` fallimenti).
    novita: list[dict[str, Any]] = field(default_factory=list)
    riscrittura: str = ""
    slug_riscritto: str | None = None
    #: `nuovo_allegato` applicati: righe `bando_link` scritte, e quelli di cui
    #: il diff non ha dato l'URL del documento.
    allegati_registrati: int = 0
    allegati_senza_url: int = 0
    #: Giro 3 (§14): eventi di un tipo attivo che la RPC ha marcato.
    eventi_scartati: int = 0
    #: Novita' oltre il limite del prompt, rimaste in coda dopo una
    #: riscrittura riuscita (si riscrivono al giro dopo).
    novita_rinviate: int = 0
    #: La riga era di una pulizia vecchia (`impronte.VERSIONE_PULIZIA`):
    #: impronte, `testo_norm` e link si sono riscritti senza diff ne'
    #: classificazione. E' il contatore `riallineate` del giro.
    riallineato: bool = False
    #: L'host della fonte non risolveva (DNS): controllo saltato, niente
    #: colonne. Finisce nell'elenco `host_irraggiungibili_elenco` del giro.
    host_irraggiungibile: str | None = None
    eventi: tuple[dict[str, Any], ...] = ()
    respinti: tuple[dict[str, Any], ...] = ()
    #: Quanti INSERT di evento il database ha rifiutato. Non e' una decorazione:
    #: e' il contatore che mancava il 25/09/2026, quando ogni evento del monitor
    #: veniva respinto da Postgres (`confidenza` float in una colonna smallint),
    #: `db.registra_evento` metteva l'errore in un warning e il giro si
    #: dichiarava riuscito. Due giorni di ombra a vuoto, e nessun numero che lo
    #: dicesse. Stesso difetto e stessa cura di `link-verifica`/`non_scritte`.
    eventi_non_scritti: int = 0
    #: Solo in attivo: gli eventi ammessi che la RPC ha applicato davvero, e
    #: quelli rimasti a DB non applicati (RPC fallita o evento respinto). Solo i
    #: primi cambiano la pagina, e quindi possono andare a IndexNow.
    eventi_applicati: int = 0
    eventi_non_applicati: int = 0
    #: Il tipo di ogni evento applicato (entrambi i percorsi): diventa
    #: `applicati_per_tipo` nella riga del giro.
    tipi_applicati: list[str] = field(default_factory=list)
    #: I tipi degli eventi non applicati e di quelli invisibili: servono al
    #: comando di ripresa scritto negli allarmi (`--tipo`).
    tipi_non_applicati: list[str] = field(default_factory=list)
    #: Gli id degli stessi eventi (None se la registrazione non l'ha dato): il
    #: comando di ripresa li riprende uno per uno (`applica-eventi --ids`).
    ids_non_applicati: list[Any] = field(default_factory=list)
    #: Attivazione per tipo: eventi applicati alle colonne ma non resi
    #: leggibili (seconda scrittura fallita). La pagina e' cambiata, il box no:
    #: li recupera `applica-eventi --attivo`.
    eventi_invisibili: int = 0
    #: Attivazione per tipo: eventi ammessi dai gate ma registrati dal DB come
    #: non verificati (dominio fuori da `dominio_ufficiale`). Restano in ombra.
    eventi_non_verificati: int = 0
    #: Attivazione per tipo: `verificato` non si e' potuto rileggere. Resta in
    #: ombra come il non verificato, ma e' un errore e si conta a parte.
    errori_verifica: int = 0
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
    #: Come `da_rigenerare`, ma solo per le date davvero APPLICATE (in attivo,
    #: o di un tipo attivo). In ombra `da_rigenerare` dice anche le date che si
    #: scriverebbero, per il report; IndexNow guarda questa.
    rigenerazione_dovuta: bool = False

    @property
    def rigenerato(self) -> bool:
        """Vero se la prosa dice davvero le date applicate: ogni rigenerazione
        ha scritto, oppure ha trovato il testo gia' in linea.

        Il ripiego sul box templato (`via="box"`, per contenuto assente o gate
        fallito) NON conta: la colonna e il box dicono la data nuova, la prosa
        la vecchia. Fino al 30/09/2026 contava come riuscito, e la riga del
        monitor senza `contenuto` lo produceva sempre (revisione avversaria,
        P1): nessun allarme, e lo slug andava a IndexNow.
        """
        return bool(self.rigenerazioni) and all(
            _rigenerazione_riuscita(r) for r in self.rigenerazioni)

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
    riscrittore: Callable[[Any, list[dict[str, Any]]], Awaitable[Any]] | None = None,
    **kwargs: Any,
) -> EsitoControllo:
    """Un controllo completo su un bando (`_controlla_pagina`), poi la
    riscrittura della scheda con Opus se le novita' la chiedono (giro 3, §6).

    `riscrittore(bando_id, novita)` e' `rigenera.riscrivi_scheda` con la spesa
    del giro; senza (ombra, dry-run, test) le novita' non si riscrivono. Le
    novita' di questo controllo si uniscono a quelle rimaste in coda
    (`impronte_sezioni["__riscrittura__"]`): una riscrittura per bando per
    giro, anche con piu' eventi. Rinviata (tetto di spesa) o fallita resta in
    coda per il giro dopo; dopo `TENTATIVI_RISCRITTURA` fallimenti si
    abbandona, e lo si dice. Non solleva mai.
    """
    esito = await _controlla_pagina(riga, **kwargs)
    scrittore = None if kwargs.get("dry_run") else kwargs.get("fonte_dati")
    try:
        await _riscrivi_se_serve(riga, esito, riscrittore=riscrittore, scrittore=scrittore,
                                 adesso=adesso_roma(kwargs.get("adesso")))
    except Exception as e:                                # pragma: no cover - difesa
        logger.warning("[monitor] riscrittura del bando {} non gestita: {}", riga.get("id"), e)
    return esito


async def _controlla_pagina(
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
    tipi_attivi: Iterable[str] = (),
    tabella_domini: Any = None,
    adesso: datetime | None = None,
    casuale: Callable[[], float] | None = None,
    dry_run: bool = False,
    rinvia_classificazione: bool = False,
    host_richiede_js: Iterable[str] = (),
    capacita_14: bool = False,
) -> EsitoControllo:
    """Un controllo completo su un bando. Non solleva mai.

    L'ordine dei passi e' l'ordine dei costi: prima cio' che e' gratis.

    `rinvia_classificazione` (tetto di spesa o di crediti raggiunto, giro 3
    §4 e §5): restano SOLO i controlli gratuiti. La pagina si scarica senza il
    ripiego Firecrawl (`principale=False`) e si confronta: invariato, 304 e
    rumore si salvano come sempre. Una pagina cambiata non va al modello, e
    una pagina che chiederebbe il ripiego a pagamento (WAF 403/406, app-shell,
    host `host_richiede_js`) non si legge: in tutti e due i casi non si salva
    niente (`classificazione_rinviata` / `scarico_rinviato`) e si rivede al
    giro dopo.

    `tipi_attivi` (`MONITOR_TIPI_ATTIVI`) vale solo in ombra: gli eventi di
    quei tipi, ammessi dai gate e nati in questo controllo, si applicano e si
    rendono leggibili (`_attiva_per_tipo`); gli altri restano in ombra.

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

    # Una riga salvata con una pulizia vecchia non si confronta: il «prima» e'
    # stato calcolato da un'altra `pulisci`, e il diff farebbe sembrare cambiata
    # ogni pagina (dal 30/09/2026 le 164 pagine cieche, tutte insieme). Si
    # riallinea, dentro il controllo normale: pagina scaricata per intero e
    # colonne riscritte senza diff (contratto di ottobre 2026, §4). La prima
    # lettura (nessun `testo_norm`) resta com'e'.
    testo_prima = testo_da_colonna(riga.get("testo_norm"))
    stantia = riga_stantia(riga)

    # 0. nessun classificatore, nessun controllo. La verifica sta PRIMA del
    #    fetch di proposito: un giro senza modello non deve pagare una GET per
    #    riga (e, sugli host `richiede_js`, un credito Firecrawl) per poi
    #    buttare via la pagina. E non si scrive nemmeno la baseline: avanzare
    #    l'impronta qui perderebbe per sempre il cambiamento appena visto.
    #    Una riga stantia invece passa: il riallineamento non chiama il modello
    #    (revisione del 30/09/2026).
    if classifica is None and not stantia:
        esito.esito = "saltato"
        esito.motivo = "nessun classificatore disponibile"
        return esito

    # 1. segnale macchina per host: 0 crediti, 0 LLM. `False` significa «la
    #    fonte dichiara che non e' cambiato niente»: si smette qui. Non su una
    #    riga stantia: rimanderebbe il riallineamento al primo cambiamento
    #    vero, cioe' proprio a quello che il riallineamento non vede.
    if segnale_macchina is not None and not stantia:
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

    # 2. GET condizionale: un 304 costa zero e chiude il controllo. Su una riga
    #    stantia la GET e' piena, per lo stesso motivo del segnale macchina.
    try:
        risposta = await scarica(
            url,
            # A tetto raggiunto niente ripiego a pagamento (giro 3, §4).
            principale=not rinvia_classificazione,
            etag=None if stantia else riga.get("etag"),
            modificata_dopo=None if stantia else riga.get("last_modified"),
        )
    except Exception as e:
        return _errore(riga, esito, str(e), momento, scrittore, modalita)

    esito.fetch = 1
    if getattr(risposta, "host_irraggiungibile", False):
        # DNS rotto: la pagina non si e' letta, e non e' colpa della pagina.
        # Niente `controlli_falliti`, che dopo cinque giri rimanderebbero la
        # fonte al resolver. L'unica colonna e' `prossimo_controllo_at` =
        # domani, come nel resolver: senza, la riga resterebbe in testa alla
        # coda a ogni giro. Non conta nel tetto dei fetch: lo scarico non
        # conta ne' le richieste saltate ne' i tentativi finiti per DNS, e qui
        # `fetch=0` vale per lo scarico iniettato (contratto di ottobre 2026,
        # §5; revisione #23).
        esito.esito = "saltato"
        esito.motivo = "host irraggiungibile (DNS)"
        esito.host_irraggiungibile = _host_senza_www(url)
        esito.fetch = 0
        esito.prossimo = _domani(momento)
        esito.colonne = {"prossimo_controllo_at": esito.prossimo.isoformat()}
        _salva(scrittore, esito)
        return esito
    stato_http = getattr(risposta, "stato", None)
    if rinvia_classificazione and richiederebbe_ripiego(url, risposta, host_richiede_js):
        # La pagina si legge solo col ripiego Firecrawl, che a tetto raggiunto
        # non si paga: niente colonne (ne' `controlli_falliti`, ne' una
        # baseline presa da uno scheletro JS), si riprova al giro dopo.
        return _scarico_rinviato(esito)
    if stato_http == 304:
        esito.esito = "304"
        esito.prossimo = prossimo_controllo(riga, scenario=scenario, adesso=momento, casuale=casuale)
        # Niente corpo, quindi niente `testo_norm`: si rinfrescano solo le
        # testate, che un 304 puo' comunque aggiornare. Una riga stantia (il
        # server ha risposto 304 anche senza etag) resta della versione vecchia
        # e si riallinea al controllo dopo.
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
    link_dopo = impronte.link_pagina(contenuto)
    sezioni_dopo: dict[str, Any] = dict(impronte.impronte_sezioni(contenuto))
    # I link di oggi sono il «prima» del giro dopo: il testo salvato e' testo
    # semplice e non li contiene.
    sezioni_dopo[impronte.CHIAVE_LINK] = list(link_dopo)
    sezioni_dopo[impronte.CHIAVE_VERSIONE] = impronte.VERSIONE_PULIZIA
    if stantia and not testo_dopo.strip():
        # Senza testo `comprimi_testo` non scrive `testo_norm`: si salverebbero
        # impronta e versione nuove con il «prima» della v1, e il primo
        # cambiamento vero produrrebbe il diff fra due pulizie (revisione
        # avversaria del 30/09/2026). La riga resta stantia e riprova dopo.
        esito.esito = "invariato"
        esito.motivo = "riallineamento rinviato: testo normalizzato vuoto"
        esito.prossimo = prossimo_controllo(riga, scenario=scenario, adesso=momento, casuale=casuale)
        esito.colonne = _colonne_invariato(riga, esito.prossimo, momento)
        _salva(scrittore, esito)
        return esito
    if stantia:
        # Il prezzo accettato: un cambiamento vero avvenuto fra l'ultimo
        # controllo e questo non si vede. Succede una volta per pagina.
        esito.esito = "invariato"
        esito.motivo = f"riallineamento alla pulizia v{impronte.VERSIONE_PULIZIA}"
        esito.riallineato = True
        esito.prossimo = prossimo_controllo(riga, scenario=scenario, adesso=momento, casuale=casuale)
        esito.colonne = _colonne_invariato(
            riga, esito.prossimo, momento, impronta=impronta_nuova,
            risposta=risposta, testo=testo_dopo, sezioni=sezioni_dopo)
        _salva(scrittore, esito)
        return esito
    if impronta_nuova == riga.get("impronta_contenuto") and testo_prima is not None:
        esito.esito = "invariato"
        esito.prossimo = prossimo_controllo(riga, scenario=scenario, adesso=momento, casuale=casuale)
        esito.colonne = _colonne_invariato(
            riga, esito.prossimo, momento, impronta=impronta_nuova,
            risposta=risposta, testo=testo_dopo, sezioni=sezioni_dopo)
        _salva(scrittore, esito)
        return esito

    # Testo con testo e link con link. Fino al 29/09/2026 qui si confrontava il
    # `testo_norm` salvato con l'HTML nuovo: la pagina intera risultava nuova a
    # ogni cambio d'impronta, e tutti i link «comparsi».
    # I link salvati con un'altra pulizia non sono un «prima»: una pagina cieca
    # con `testo_norm` NULL (quindi non stantia) aveva `__link__` della v1, e
    # tutti i link che la v2 ora vede risulterebbero «comparsi», cioe' falsi
    # `nuovo_allegato` (revisione avversaria del 30/09/2026).
    link_prima = (
        _link_salvati(riga)
        if impronte.versione_pulizia(riga.get("impronte_sezioni")) == impronte.VERSIONE_PULIZIA
        else None)
    diff = impronte.diff_testi(
        testo_prima, testo_dopo, link_prima=link_prima, link_dopo=link_dopo,
        oggi=momento.date())
    # Decide `rumore`, non la sola lista di parole: una scadenza spostata («entro
    # il 5 ottobre» → «entro il 30 ottobre») non contiene «proroga» ma non e'
    # rumore, e scartata qui si perdeva per sempre (revisione del 29/09/2026).
    esito.diff_rilevante = bool(diff.rilevante) or not diff.rumore or testo_prima is None
    if not esito.diff_rilevante:
        esito.esito = "invariato"
        esito.motivo = "diff classificato come rumore"
        esito.prossimo = prossimo_controllo(riga, scenario=scenario, adesso=momento, casuale=casuale)
        esito.colonne = _colonne_invariato(
            riga, esito.prossimo, momento, impronta=impronta_nuova,
            risposta=risposta, testo=testo_dopo, sezioni=sezioni_dopo)
        _salva(scrittore, esito)
        return esito

    # 3-bis. tetto di spesa raggiunto: la pagina e' cambiata, ma il modello non
    #    si chiama. Niente pagine collegate (servirebbero solo al modello) e
    #    niente colonne: impronta, `testo_norm` e `__link__` restano quelli di
    #    prima, e il cambiamento si rivede al giro dopo (giro 3, §5).
    if rinvia_classificazione:
        return _classificazione_rinviata(esito)

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
                # §19.6: i redirect solo sullo stesso host. La guardia sugli
                # indirizzi ha giudicato l'URL di partenza (adattatore di
                # produzione); un 3xx verso un altro host si ferma li'.
                secondaria = await scarica(collegato, principale=False,
                                           redirect=REDIRECT_STESSO_HOST)
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
        ultimo_controllo=_giorno_di(riga.get("ultimo_controllo_at")),
        stati_estesi=stati_estesi,
        modalita=modalita,
        capacita_14=capacita_14,
        ora_apertura=riga.get("ora_apertura"),
    )

    try:
        proposte = list(await classifica(ctx))
    except Exception as e:
        # Un errore, non «nessun evento». Fino al 28/09/2026 qui si proseguiva
        # con `proposte = []`: il controllo salvava la nuova impronta e il nuovo
        # `testo_norm`, e la modifica non si ripresentava piu' (col credito
        # Anthropic esaurito dal 26/09 se ne sono perse dieci, con `errori: 0`).
        # Nessuna colonna: impronta, testo e prossimo controllo restano quelli
        # di prima, la pagina risulta ancora cambiata e il giro dopo il modello
        # la rivede. Niente `controlli_falliti`: la pagina non ha colpa, e
        # cinque giri senza credito non devono bloccare il bando.
        logger.warning("[monitor] classificazione fallita per {}: {}", riga.get("id"), e)
        return _classificazione_fallita(esito, f"classificazione fallita: {e}")
    esito.classificato = True

    if proposte and seconda_opinione is not None:
        try:
            ctx = replace_contesto(ctx, seconda_opinione=await seconda_opinione(ctx))
        except Exception as e:
            # Stessa regola: senza la seconda opinione gli eventi che chiedono
            # la concordanza verrebbero respinti al G7 e l'impronta nuova
            # salvata, cioe' la modifica persa. Si rifa' tutto al giro dopo
            # (Haiku si ripaga, la notizia no).
            logger.warning("[monitor] seconda opinione fallita per {}: {}", riga.get("id"), e)
            return _classificazione_fallita(esito, f"seconda opinione fallita: {e}")

    ammessi: list[dict[str, Any]] = []
    respinti: list[dict[str, Any]] = []
    colonne: dict[str, Any] = {}
    date_cambiate: list[tuple[dict[str, Any], str, date_cls | None, date_cls]] = []
    # Le sole date APPLICATE: sono quelle che la prosa deve ripetere. In attivo
    # coincidono con `date_cambiate`; in ombra ci sono solo i tipi attivi.
    date_applicate: list[tuple[dict[str, Any], str, date_cls | None, date_cls]] = []
    tipi_da_attivare = (
        frozenset() if ctx.modalita == eventi_mod.MODALITA_ATTIVO or scrittore is None
        else frozenset(tipi_attivi))
    da_rielaborare = False
    for proposta in ordina_proposte(proposte):
        applicazione = eventi_mod.applica(proposta, ctx)
        if applicazione.giudizio and applicazione.giudizio.ammesso:
            tipo = str(applicazione.riga.get("tipo") or proposta.tipo)
            per_tipo = tipo in tipi_da_attivare
            stato_attivazione = ""
            if per_tipo:
                applicazione, stato_attivazione = _attiva_per_tipo(
                    scrittore, applicazione,
                    proposto=eventi_mod.stato_solo_proposto(proposta, ctx))
                if stato_attivazione == ATTIVAZIONE_INVISIBILE:
                    esito.eventi_invisibili += 1
                    esito.tipi_non_applicati.append(tipo)
                    esito.ids_non_applicati.append(applicazione.riga.get("id"))
                elif stato_attivazione == ATTIVAZIONE_NON_VERIFICATO:
                    esito.eventi_non_verificati += 1
                elif stato_attivazione == ATTIVAZIONE_VERIFICA_ILLEGGIBILE:
                    esito.errori_verifica += 1
                elif stato_attivazione == ATTIVAZIONE_SCARTATO:
                    esito.eventi_scartati += 1
            ammessi.append(applicazione.come_dizionario())
            attivo = ctx.modalita == eventi_mod.MODALITA_ATTIVO or per_tipo
            # In attivo contano solo le colonne che la RPC ha scritto davvero:
            # con la RPC fallita, o l'evento registrato ma non applicato, la
            # prosa rigenerata direbbe una data che la colonna non ha. In ombra
            # restano le colonne «che si scriverebbero», per il report.
            colonne_evento = applicazione.colonne if (applicazione.applicato or not attivo) else {}
            # Un evento gia' registrato prima (dedup della RPC) non e' nato in
            # questo giro: non si applica, e non e' un'applicazione fallita.
            # Nemmeno il non verificato: resta in ombra per scelta.
            if attivo and stato_attivazione not in (
                    ATTIVAZIONE_GIA_REGISTRATO, ATTIVAZIONE_NON_VERIFICATO,
                    ATTIVAZIONE_VERIFICA_ILLEGGIBILE, ATTIVAZIONE_SCARTATO):
                if applicazione.applicato:
                    esito.eventi_applicati += 1
                    esito.tipi_applicati.append(tipo)
                    da_rielaborare = da_rielaborare or rimette_in_rielaborazione(
                        tipo, applicazione.riga.get("campo"))
                    # Giro 3 (§6): le novita' che la sostituzione senza modello
                    # non sa rendere vanno alla riscrittura con Opus...
                    if rigenera_mod.chiede_riscrittura(tipo, applicazione.riga.get("campo")):
                        esito.novita.append(rigenera_mod.novita_da_evento(applicazione.riga))
                    # ...e un documento nuovo diventa una riga `bando_link`.
                    if tipo == "nuovo_allegato" and scrittore is not None:
                        _registra_allegato(scrittore, riga, applicazione.riga, diff, url, esito,
                                           html=contenuto)
                else:
                    esito.eventi_non_applicati += 1
                    esito.tipi_non_applicati.append(tipo)
                    esito.ids_non_applicati.append(applicazione.riga.get("id"))
            nuove_date = _date_da_rigenerare(ctx, colonne_evento, applicazione.riga)
            date_cambiate.extend(nuove_date)
            if attivo:
                date_applicate.extend(nuove_date)
            colonne.update(colonne_evento)
            # Il contesto avanza con l'evento appena accettato: il prossimo
            # deve essere giudicato sulle date NUOVE, non su quelle vecchie, e
            # deve vedere questo evento fra i recenti — senza, due proposte
            # identiche nella stessa risposta superano entrambe il G8 e il box
            # «Aggiornamenti» mostra due volte la stessa notizia.
            # Il contesto avanza con l'intenzione dell'evento, applicato o no:
            # serve a giudicare il secondo evento di una coppia (differimento).
            ctx = _ctx_aggiornato(ctx, applicazione.colonne, applicazione.riga)
            # L'INSERT diretto solo se la RPC non ha scritto la riga. In attivo
            # quella riga NON e' applicata ne' visibile (fino al 29/09/2026 lo
            # diventava anche con la RPC fallita): `applica-eventi` la riprende.
            if scrittore is not None and not applicazione.scritto:
                riga_db = dict(applicazione.riga)
                if attivo:
                    riga_db.update(applicato=False, leggibile=False, in_aggiornamenti=False)
                if _rifiutato(scrittore, riga_db):
                    esito.eventi_non_scritti += 1
        else:
            respinti.append(applicazione.come_dizionario())
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
            if (scrittore is not None and len(respinti) <= RESPINTI_A_DB_PER_BANDO
                    and _rifiutato(scrittore, applicazione.riga)):
                esito.eventi_non_scritti += 1

    esito.eventi = tuple(ammessi)
    esito.respinti = tuple(respinti)
    if da_rielaborare and scrittore is not None:
        # La pagina ufficiale ha detto qualcosa di nuovo sul contenuto, sugli
        # allegati o su una riapertura: il passo `rielaborazione` del giro dopo
        # rilegge la fonte e aggiorna date e classificazione (giro 3, §5 e §9).
        esito.rielaborazione_richiesta = bool(scrittore.azzera_rielaborazione(riga.get("id")))
    esito.da_rigenerare = bool(date_cambiate)
    # Da riscrivere in prosa solo le date che sostituiscono una data vecchia:
    # una data nuova dove prima non ce n'era (un'apertura fissata per la prima
    # volta) non puo' essere sbagliata nel testo, che non la diceva.
    date_da_riscrivere = [d for d in date_applicate if d[2] is not None]
    esito.rigenerazione_dovuta = bool(date_da_riscrivere)
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
    #    Solo sulle date APPLICATE (in attivo, o di un tipo attivo), e solo se
    #    il chiamante ha fornito il punto di iniezione. Senza, `run()` non mette
    #    lo slug fra quelli da notificare: avvisare Google di una pagina rimasta
    #    com'era e' peggio che non avvisarlo.
    if date_da_riscrivere and rigenerazione is not None and not dry_run:
        # La riga del monitor non porta `contenuto` ne' `descrizione_breve`:
        # si rileggono e si convertono come fa il lotto L7 (revisione
        # avversaria del 30/09/2026, P1). Senza, `rigenera` usciva «solo box»
        # e il giro lo contava come riscritto.
        preparata = _da_rigenerare(scrittore, riga, rigenerazione)
        if preparata is None:
            esito.rigenerazioni = ({"via": "box", "scritto": False,
                                    "motivi": ["contenuto del bando non leggibile"]},)
            _date_alla_riscrittura(esito, date_da_riscrivere)
            return esito
        corrente_riga, rigenerazione = preparata
        # Le rigenerazioni si INCATENANO. Il differimento arriva in coppia
        # (apertura e scadenza): se la seconda ripartisse dal contenuto
        # originale sovrascriverebbe la prima, e l'ultima scrittura
        # vincerebbe — cioe' una delle due date resterebbe vecchia in prosa
        # proprio mentre la colonna dice il contrario.
        for evento_riga, ruolo, vecchia, nuova in date_da_riscrivere:
            try:
                prodotto = await rigenerazione(
                    corrente_riga, evento_riga, vecchia=vecchia, nuova=nuova, ruolo=ruolo)
            except Exception as e:
                logger.warning("[monitor] rigenerazione del bando {} fallita: {}",
                               riga.get("id"), e)
                continue
            esito.rigenerazioni = esito.rigenerazioni + (_esito_rigenerazione(prodotto),)
            corrente_riga.update(_payload_rigenerazione(prodotto))
    # Giro 3 (§6): una data applicata che la sostituzione senza modello non ha
    # riallineato (controllo finale fallito, o nessun rigeneratore) va alla
    # riscrittura con Opus, invece di lasciare il testo vecchio.
    if date_da_riscrivere and not dry_run and not esito.rigenerato:
        _date_alla_riscrittura(esito, date_da_riscrivere)
    return esito


def _date_alla_riscrittura(
    esito: EsitoControllo,
    date: Sequence[tuple[Mapping[str, Any], str, date_cls | None, date_cls]],
) -> None:
    """Le date rimaste vecchie in prosa diventano novita' per Opus (§6)."""
    esito.novita = rigenera_mod.unisci_novita(
        esito.novita, (rigenera_mod.novita_da_evento(evento) for evento, *_ in date))


#: La chiave riservata di `impronte_sezioni` con le riscritture in coda (giro 3,
#: §6; decisione del lead: niente migrazione). Come `__link__` e `__versione__`
#: e' memoria del monitor: `{novita: [...], tentativi: n, dal: iso}`.
CHIAVE_RISCRITTURA = "__riscrittura__"
#: Dopo tanti fallimenti di fila una riscrittura si abbandona (si dice nel
#: riepilogo): senza, una scheda che la SEO non sa riscrivere ripagherebbe
#: Opus a ogni giro per sempre.
TENTATIVI_RISCRITTURA = 3
#: L'esito di una riscrittura abbandonata dopo `TENTATIVI_RISCRITTURA`.
RISCRITTURA_ABBANDONATA = "abbandonata"


def riscrittura_in_coda(riga: Mapping[str, Any]) -> dict[str, Any] | None:
    """La coda delle riscritture del bando, se c'e' (`impronte_sezioni`)."""
    sezioni = riga.get("impronte_sezioni")
    coda = sezioni.get(CHIAVE_RISCRITTURA) if isinstance(sezioni, Mapping) else None
    return dict(coda) if isinstance(coda, Mapping) and coda.get("novita") else None


async def _riscrivi_se_serve(
    riga: Mapping[str, Any],
    esito: EsitoControllo,
    *,
    riscrittore: Callable[[Any, list[dict[str, Any]]], Awaitable[Any]] | None,
    scrittore: FonteDati | None,
    adesso: datetime,
) -> None:
    """La riscrittura con Opus del bando, e la sua coda (giro 3, §6)."""
    coda = riscrittura_in_coda(riga)
    novita = rigenera_mod.unisci_novita((coda or {}).get("novita") or (), esito.novita)
    if not novita or scrittore is None:
        # In dry-run non si scrive niente, nemmeno la coda.
        return
    nuova: dict[str, Any] | None
    if riscrittore is None:
        # Nessuno puo' riscrivere adesso (adattatore assente): le novita'
        # nuove restano in coda per un giro che ce l'avra'.
        nuova = {"novita": novita, "tentativi": int((coda or {}).get("tentativi") or 0),
                 "dal": (coda or {}).get("dal") or adesso.isoformat()}
    else:
        # Il prompt ne mostra al massimo `MAX_NOVITA_PER_RISCRITTURA`: le altre
        # restano in coda per la riscrittura del giro dopo (P2 della revisione
        # #152), invece di sparire con la coda svuotata.
        prime = novita[:rigenera_mod.MAX_NOVITA_PER_RISCRITTURA]
        resto = novita[rigenera_mod.MAX_NOVITA_PER_RISCRITTURA:]
        risultato = await riscrittore(riga.get("id"), prime)
        esito.riscrittura = str(getattr(risultato, "esito", "") or rigenera_mod.ESITO_FALLITA)
        tentativi = int((coda or {}).get("tentativi") or 0)
        nuova = None
        if esito.riscrittura == rigenera_mod.ESITO_SCRITTA:
            esito.slug_riscritto = getattr(risultato, "slug", None) or riga.get("slug")
            if resto:
                esito.novita_rinviate = len(resto)
                nuova = {"novita": resto, "tentativi": 0, "dal": adesso.isoformat()}
        elif esito.riscrittura == rigenera_mod.ESITO_RINVIATA:
            nuova = {"novita": novita, "tentativi": tentativi,
                     "dal": (coda or {}).get("dal") or adesso.isoformat()}
        elif esito.riscrittura == rigenera_mod.ESITO_FALLITA:
            tentativi += 1
            if tentativi >= TENTATIVI_RISCRITTURA:
                logger.warning("[ALLARME] [monitor] riscrittura del bando {} abbandonata dopo {} "
                               "tentativi: {}", riga.get("id"), tentativi,
                               getattr(risultato, "motivo", ""))
                esito.riscrittura = RISCRITTURA_ABBANDONATA
            else:
                nuova = {"novita": novita, "tentativi": tentativi,
                         "dal": (coda or {}).get("dal") or adesso.isoformat()}
    if nuova != coda:
        _salva_coda(scrittore, riga, esito, nuova, adesso)


def _salva_coda(
    scrittore: FonteDati,
    riga: Mapping[str, Any],
    esito: EsitoControllo,
    coda: Mapping[str, Any] | None,
    adesso: datetime,
) -> None:
    """Scrive (o toglie) la coda delle riscritture in `impronte_sezioni`.

    Si parte dalle impronte appena salvate da questo controllo, o da quelle
    della riga: le altre chiavi restano com'erano. Un chiuso con una
    riscrittura in coda torna al giro dopo invece di aspettare la sua cadenza.
    """
    sezioni = dict(esito.colonne.get("impronte_sezioni") or riga.get("impronte_sezioni") or {})
    if coda:
        sezioni[CHIAVE_RISCRITTURA] = dict(coda)
    else:
        sezioni.pop(CHIAVE_RISCRITTURA, None)
    colonne: dict[str, Any] = {"impronte_sezioni": sezioni}
    if coda and fase(riga, oggi=adesso.date()) == FASE_CHIUSO:
        colonne["prossimo_controllo_at"] = adesso.isoformat()
    try:
        scrittore.salva_controllo(riga.get("id"), colonne)
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[monitor] coda delle riscritture del bando {} non salvata: {}",
                       riga.get("id"), e)


_RE_HREF = re.compile(r"""href\s*=\s*["']([^"'<>]+)["']""", re.IGNORECASE)


def href_originale(html: str | None, normalizzato: str, base: str = "") -> str:
    """L'href com'e' scritto nella pagina per un link normalizzato (`www.`,
    slash finale...), cosi' la riga `bando_link` porta l'URL vero. Se non si
    ritrova, il normalizzato."""
    for trovato in _RE_HREF.finditer(html or ""):
        # §19.3: un href malformato (`http://[object Object]`,
        # `https://www.ente.it]/x`) fa sollevare `urljoin`: si salta lui, non
        # il giro.
        try:
            grezzo = urljoin(base, trovato.group(1).strip()) if base else trovato.group(1).strip()
            if impronte.normalizza_url(grezzo) == normalizzato:
                return grezzo
        except ValueError:
            continue
    return normalizzato


def url_allegato(evento: Mapping[str, Any], diff: Any, *, html: str | None = None,
                 base: str = "") -> str | None:
    """L'URL del documento di un `nuovo_allegato`, o None. Pura.

    `url_prova` dell'evento e' la PAGINA dove l'abbiamo visto, non il
    documento (regola 5 del classificatore). Il documento e' un link comparso
    nel diff: quello di cui la citazione nomina le parole (la stessa misura
    del G2, `eventi.QUOTA_TOKEN_G2`), oppure l'unico comparso. In ripiego un
    URL http(s) in `valore_dopo`.
    """
    nuovi = [str(l) for l in (getattr(diff, "link_aggiunti", ()) or ()) if str(l).startswith("http")]
    parole = [t for t in eventi_mod._token(str(evento.get("citazione") or ""))
              if len(t) >= 3 and not t.isdigit()]
    migliore, quota_migliore = None, 0.0
    for link in nuovi:
        nel_link = eventi_mod._token_link(link)
        if not parole or not nel_link:
            continue
        quota = sum(1 for t in parole if t in nel_link) / len(parole)
        if quota >= eventi_mod.QUOTA_TOKEN_G2 and quota > quota_migliore:
            migliore, quota_migliore = link, quota
    if migliore:
        return href_originale(html, migliore, base)
    if len(nuovi) == 1:
        return href_originale(html, nuovi[0], base)
    dopo = evento.get("valore_dopo")
    for valore in (dopo.values() if isinstance(dopo, Mapping) else ()):
        if isinstance(valore, str) and valore.startswith(("http://", "https://")):
            return valore
    return None


def _registra_allegato(
    scrittore: FonteDati,
    riga: Mapping[str, Any],
    evento: Mapping[str, Any],
    diff: Any,
    url_pagina: str,
    esito: EsitoControllo,
    *,
    html: str | None = None,
) -> None:
    """`nuovo_allegato` applicato → riga `bando_link` `allegato` (giro 3, §6).

    `url` e' il documento, `url_prova` la pagina dove e' comparso; non
    pubblicabile finche' `link_verifica` non la verifica (§10).
    """
    documento = url_allegato(evento, diff, html=html, base=url_pagina)
    if not documento:
        esito.allegati_senza_url += 1
        logger.info("[monitor] nuovo_allegato del bando {}: URL del documento non trovato nel diff",
                    riga.get("id"))
        return
    pagina = str(evento.get("url_prova") or url_pagina or "")
    if scrittore.registra_link_allegato(riga.get("id"), documento, pagina):
        esito.allegati_registrati += 1


def _da_rigenerare(
    scrittore: FonteDati | None,
    riga: Mapping[str, Any],
    rigenerazione: Callable[..., Awaitable[Any]],
) -> tuple[dict[str, Any], Callable[..., Awaitable[Any]]] | None:
    """(riga con `contenuto` come testo, adattatore) per `rigenera`, o None.

    Stessa conversione del lotto L7 (`rigenera._lotto_date`): il `contenuto`
    e' un jsonb con `sections`, `rigenera` lavora sul testo dei soli nodi, e
    lo scrittore lo rimonta in jsonb un attimo prima dell'UPDATE. Aggiungere
    la colonna alla select del monitor non basterebbe: si scriverebbe il
    testo, o `str(dict)`, dentro il jsonb.

    Lo scrittore di produzione e' il `scrivi` dell'adattatore
    (`functools.partial(rigenera.rigenera, attivo=True, scrivi=…)`, costruito
    dalla pipeline e dalla CLI): lo si avvolge con `_scrittore_json`. Un
    adattatore senza `scrivi` (i test) riceve il testo e basta.

    None se il contenuto non si legge o non si scompone in nodi: la prosa non
    si riscrive, e il giro lo conta in `prosa_non_riscritta`.
    """
    if scrittore is None:
        return None
    testi = scrittore.testi_del_bando(riga.get("id"))
    if not testi or not testi.get("contenuto"):
        logger.warning("[monitor] bando {}: contenuto non leggibile, prosa non riscritta",
                       riga.get("id"))
        return None
    from . import rigenera as rigenera_mod
    trasformato = rigenera_mod._testo_del_contenuto(dict(riga, **testi))
    if trasformato is None:
        return None
    corrente, struttura, era_stringa = trasformato
    if not str(corrente.get("contenuto") or "").strip():
        # Un jsonb senza nodi di testo: non c'e' prosa da riscrivere.
        return None
    scrivi = (getattr(rigenerazione, "keywords", None) or {}).get("scrivi")
    if scrivi is not None:
        rigenerazione = functools.partial(
            rigenerazione, scrivi=rigenera_mod._scrittore_json(scrivi, struttura, era_stringa))
    return corrente, rigenerazione


#: Il motivo con cui `rigenera` dice «niente da scrivere, il testo dice gia'
#: la data giusta»: e' l'unico `via="box"` che non e' un ripiego.
_GIA_IN_LINEA = "contenuto gia' in linea"


def _rigenerazione_riuscita(esito: Mapping[str, Any]) -> bool:
    """Una rigenerazione ha portato la prosa sulla data nuova (o ce l'ha trovata)."""
    if esito.get("scritto"):
        return True
    return any(str(m).startswith(_GIA_IN_LINEA) for m in (esito.get("motivi") or ()))


#: Esiti di `_attiva_per_tipo`.
ATTIVAZIONE_APPLICATO = "applicato"
ATTIVAZIONE_NON_APPLICATO = "non_applicato"
ATTIVAZIONE_INVISIBILE = "invisibile"
ATTIVAZIONE_GIA_REGISTRATO = "gia_registrato"
ATTIVAZIONE_IN_OMBRA = "in_ombra"
ATTIVAZIONE_NON_VERIFICATO = "non_verificato"
ATTIVAZIONE_VERIFICA_ILLEGGIBILE = "verifica_illeggibile"
#: Giro 3 (§14): la RPC ha marcato l'evento (`scartato_per`): non si riprende.
ATTIVAZIONE_SCARTATO = "scartato"


def _comando_di_ripresa(ids: Iterable[Any], tipi: Iterable[str], giorno: date_cls) -> str:
    """Il comando che riprende SOLO gli eventi di questo giro.

    Con gli id il filtro e' esatto (`--ids`). Un filtro per tipo e giorno
    prenderebbe anche l'arretrato: le righe d'ombra dello stesso giorno scritte
    prima del deploy e quelle con `data_evento` futura, contro T-D5 (revisione
    avversaria del 30/09/2026). Se anche un solo evento non ha l'id (il monitor
    attivo del rilascio 2, la cui RPC unica qui non lo restituisce) si ripiega
    su `--tipo` e `--dal`, e il testo chiede prima un `--dry-run`.
    """
    elenco_ids = list(ids)
    if elenco_ids and all(i is not None for i in elenco_ids):
        voci = ",".join(str(i) for i in sorted(set(elenco_ids), key=str))
        return f"applica-eventi --ids {voci} --attivo"
    elenco = ",".join(sorted(set(tipi))) or "<tipo>"
    return (f"applica-eventi --tipo {elenco} --dal {giorno.isoformat()} --dry-run, "
            f"controllare che siano solo gli eventi di oggi, poi --attivo")


def _attiva_per_tipo(
    scrittore: FonteDati,
    applicazione: eventi_mod.Applicazione,
    *,
    proposto: bool = False,
) -> tuple[eventi_mod.Applicazione, str]:
    """Un evento di un tipo attivo, ammesso dai gate: applicato e leggibile.

    Contratto di ottobre 2026, §3. Tre scritture, in quest'ordine:

    1. `bando_registra_evento` con la riga d'ombra (non applicata, non
       leggibile), che restituisce `{id, nuovo}`;
    2. `bando_applica_evento(id)`, che scrive le colonne di `bando`;
    3. `leggibile=true`, che fa scattare il cursore (RIPRESA §5.8).

    Solo gli eventi NATI in questo giro: con `nuovo=false` l'indice di dedup
    ha riconosciuto un evento registrato prima, e l'arretrato si decide a
    parte (T-D5). La RPC unica del monitor attivo non va bene per questo: sul
    ramo della dedup applicherebbe proprio quell'evento, lasciandolo
    invisibile.

    Mai un evento «applicato» dopo una RPC fallita: se il passo 2 non riesce
    (5xx, 23514) l'evento resta registrato, non applicato e invisibile, e il
    giro alza l'allarme degli eventi non applicati. Se fallisce il passo 1
    l'evento torna all'INSERT d'ombra (`scritto=False`) e non si perde.
    Un evento solo «proposto» (sospensione e revoca senza la 06) si rende
    leggibile senza applicarlo, come nel monitor attivo.

    Si applica solo cio' che il DB registra come **verificato**, come fa
    `applica-eventi`. Il G4 di Python accetta anche gli host delle fonti,
    `bando_dominio_verificante` guarda solo `dominio_ufficiale`: applicare un
    evento non verificato scriverebbe la colonna, e poi `leggibile` con il box
    violerebbe il CHECK (23514), lasciando la colonna cambiata e l'evento
    invisibile (revisione avversaria del 30/09/2026). Il non verificato resta
    registrato in ombra, e si conta.
    """
    from . import db
    riga = applicazione.riga
    registrato = scrittore.registra_evento_rpc(riga)
    if registrato is None:
        logger.warning("[monitor] evento {} del bando {} non registrato via RPC: resta in ombra",
                       riga.get("tipo"), riga.get("bando_id"))
        return replace(applicazione, applicato=False, scritto=False,
                       motivo="registrazione fallita: evento in ombra"), ATTIVAZIONE_IN_OMBRA
    # L'id sta nella riga da qui in poi: finisce nel report e nel comando di
    # ripresa degli allarmi (`applica-eventi --ids`).
    applicazione = replace(applicazione, riga=dict(riga, id=registrato.get("id")))
    if registrato.get("nuovo") is not True:
        # `False`: la dedup ha riconosciuto un evento registrato prima. `None`:
        # la risposta non lo dice, e nel dubbio non si applica.
        if registrato.get("nuovo") is None:
            logger.warning("[monitor] evento {} del bando {} (id {}): la RPC non dice se e' "
                           "nuovo, resta in ombra", riga.get("tipo"), riga.get("bando_id"),
                           registrato.get("id"))
            motivo = "la RPC non dice se e' nuovo: evento in ombra"
        else:
            logger.info("[monitor] evento {} del bando {} gia' registrato (id {}): non si tocca",
                        riga.get("tipo"), riga.get("bando_id"), registrato.get("id"))
            motivo = "gia' registrato prima: non nato in questo giro"
        return replace(applicazione, applicato=False, scritto=True, motivo=motivo), \
            ATTIVAZIONE_GIA_REGISTRATO
    evento_id = registrato["id"]
    verificato = scrittore.evento_verificato(evento_id, riga)
    if verificato is None:
        # Lettura fallita: in ombra anche lui, ma e' un errore, non un «non
        # verificato» vero, e si conta a parte.
        logger.warning("[monitor] verificato dell'evento {} ({}) illeggibile: resta in ombra",
                       evento_id, riga.get("tipo"))
        return replace(applicazione, applicato=False, scritto=True,
                       motivo="verificato illeggibile: evento in ombra"), \
            ATTIVAZIONE_VERIFICA_ILLEGGIBILE
    if not verificato:
        logger.info("[monitor] evento {} ({}) del bando {} non verificato per il DB: resta in ombra",
                    evento_id, riga.get("tipo"), riga.get("bando_id"))
        return replace(applicazione, applicato=False, scritto=True,
                       motivo="non verificato per il DB: evento in ombra"), \
            ATTIVAZIONE_NON_VERIFICATO
    if not proposto:
        esito_rpc = scrittore.applica_evento(evento_id)
        if esito_rpc != db.ESITO_APPLICATO:
            # Giro 3 (§14): un evento che la RPC ha marcato (superato o
            # transizione non ammessa) non tornera' mai in coda e resta
            # invisibile: non e' un «non applicato» da riprendere.
            marcato = (scrittore.motivo_scarto(evento_id)
                       if esito_rpc == db.ESITO_RIFIUTATO else None)
            if marcato:
                logger.info("[monitor] evento {} ({}) scartato dalla RPC: {}",
                            evento_id, riga.get("tipo"), marcato)
                return replace(applicazione, applicato=False, scritto=True,
                               motivo=f"scartato: {marcato}"), ATTIVAZIONE_SCARTATO
            logger.warning("[monitor] evento {} ({}) non applicato: {}",
                           evento_id, riga.get("tipo"), esito_rpc)
            return replace(applicazione, applicato=False, scritto=True,
                           motivo=f"bando_applica_evento: {esito_rpc}"), ATTIVAZIONE_NON_APPLICATO
    if not scrittore.rendi_leggibile(evento_id, in_aggiornamenti=True):
        if proposto:
            return replace(applicazione, applicato=False, scritto=True,
                           motivo="stato solo proposto, non reso leggibile"), \
                ATTIVAZIONE_NON_APPLICATO
        logger.warning("[ALLARME] [monitor] evento {} ({}) applicato ma NON reso leggibile: "
                       "il box non lo mostra, lanciare {}",
                       evento_id, riga.get("tipo"),
                       _comando_di_ripresa((evento_id,), (str(riga.get("tipo") or ""),),
                                           oggi_roma()))
        return replace(applicazione, applicato=True, scritto=True,
                       motivo="applicato ma non leggibile"), ATTIVAZIONE_INVISIBILE
    if proposto:
        return replace(applicazione, applicato=False, scritto=True,
                       motivo="stato solo proposto: leggibile, non applicato"), \
            ATTIVAZIONE_NON_APPLICATO
    return replace(applicazione, applicato=True, scritto=True, motivo=""), ATTIVAZIONE_APPLICATO


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
        recente = dict(riga_evento)
        # Un evento «da link» puo' non avere `data_evento` (dal 29/09/2026 non
        # ripiega piu' sul giorno del controllo): per il G8 vale il giorno in
        # cui e' stato rilevato, come a DB (`rilevato_at`).
        recente.setdefault("rilevato_at", ctx.giorno.isoformat())
        campi["eventi_recenti"] = ctx.eventi_recenti + (recente,)
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
        # La coda delle riscritture (giro 3, §6) e' memoria del monitor come i
        # link: riscrivere le impronte non deve perderla.
        coda = riscrittura_in_coda(riga)
        if coda:
            colonne["impronte_sezioni"][CHIAVE_RISCRITTURA] = coda
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
        # Il blocco si annota una volta sola, al passaggio da 4 a 5 (§18.8):
        # aperti e sospesi tornano a ogni giro anche con la pagina morta, e un
        # `elaborazione_bloccata` per giro (fuori dal dedup, `valore_dopo`
        # sempre diverso) sarebbe solo rumore.
        if fonte_dati is not None and falliti == FALLIMENTI_PER_BLOCCO:
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


def _rendi_visibili_gli_applicati(
    *,
    tipi: Sequence[str] = (),
    dal: date_cls | None = None,
    scrive: bool = False,
    limite: int | None = None,
    ids: Sequence[Any] = (),
) -> int:
    """Chiude le attivazioni rimaste a meta': applicate e invisibili.

    `bando_applica_evento` marca l'evento `applicato` e non tocca `leggibile`;
    se il secondo UPDATE non parte — un giro interrotto, un codice senza quella
    scrittura — l'evento resta applicato alle colonne e assente dal box, e
    nessun lancio successivo lo ripesca: la selezione cerca `applicato=false`.
    Misurato il 25/09/2026 su cinque eventi (una `faq` e quattro
    `nuovo_allegato`) che il comando aveva dichiarato applicati.

    Ritorna quanti sono stati resi visibili. In `--dry-run` e in ombra non
    scrive e ritorna zero: e' una scrittura come le altre.
    """
    if not scrive:
        return 0
    from . import db
    try:
        righe = db.select_eventi(
            tipi=tuple(tipi), dal=dal, applicato=True, verificato=True,
            leggibile=False, limit=None if limite is None else max(0, int(limite)), ids=tuple(ids),
        )
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[applica-eventi] lettura degli applicati invisibili fallita: {}", e)
        return 0
    fatti = 0
    for riga in righe:
        tipo = str(riga.get("tipo") or "")
        if tipo not in eventi_mod.TIPI_PROPONIBILI:
            # Gli eventi di sistema non vanno nel box e non si toccano.
            continue
        esito = db.rendi_evento_leggibile(
            riga.get("id"),
            in_aggiornamenti=tipo not in ("apertura_automatica", "chiusura_automatica"),
        )
        if esito.get("scritto"):
            fatti += 1
            logger.info("[applica-eventi] evento {} ({}) reso visibile: "
                        "era applicato e invisibile", riga.get("id"), tipo)
        else:
            logger.warning("[applica-eventi] evento {} resta invisibile: {}",
                           riga.get("id"), esito.get("motivo"))
    return fatti


def _rifiutato(scrittore: Any, riga: Mapping[str, Any]) -> bool:
    """Vero solo se il database ha **rifiutato** la riga.

    Un evento che c'era gia' non e' un rifiuto: e' il caso normale quando si
    rifa' un giro sulle stesse righe (`--forza`), e contarlo come fallimento
    faceva gridare un allarme su un lavoro riuscito. Le fonti dati che non
    espongono `registra_evento_esito` ricadono sul booleano.
    """
    from . import db
    esito = getattr(scrittore, "registra_evento_esito", None)
    if esito is None:
        return not scrittore.registra_evento(riga)
    return esito(riga) == db.EVENTO_RIFIUTATO


def riga_stantia(riga: Mapping[str, Any]) -> bool:
    """Vero se la riga ha un «prima» calcolato con una pulizia vecchia
    (`impronte.VERSIONE_PULIZIA`): al prossimo scarico buono si riallinea."""
    return (
        testo_da_colonna(riga.get("testo_norm")) is not None
        and impronte.versione_pulizia(riga.get("impronte_sezioni")) != impronte.VERSIONE_PULIZIA
    )


def _pagina_cambiata(esito: EsitoControllo) -> bool:
    """La scheda pubblica e' cambiata: un evento applicato e visibile, oppure
    una data applicata con la prosa riscritta."""
    visibili = esito.eventi_applicati - esito.eventi_invisibili
    return visibili > 0 or (esito.rigenerazione_dovuta and esito.rigenerato)


def _domani(momento: datetime) -> datetime:
    """La mezzanotte di domani, ora di Roma: la riga torna dovuta al primo giro."""
    return momento.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


def _host_senza_www(url: str) -> str:
    """L'host per l'elenco della riga del giro: minuscolo, senza porta e `www.`,
    come nel resolver (`scarico.host_di`). Lo scarico invece segna il nome DNS
    esatto (`scarico.nome_host`), perche' e' quello che salta; per contare gli
    host del giro si uniscono le due forme con `_senza_www`."""
    return _senza_www((urlsplit(url).hostname or url).lower())


def _senza_www(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def _link_salvati(riga: Mapping[str, Any]) -> tuple[str, ...] | None:
    """I link della pagina al controllo precedente; None se non salvati."""
    sezioni = riga.get("impronte_sezioni")
    if not isinstance(sezioni, Mapping):
        return None
    link = sezioni.get(impronte.CHIAVE_LINK)
    if not isinstance(link, (list, tuple)):
        return None
    return tuple(str(u) for u in link)


#: Gli eventi applicati che rimettono il bando in coda alla rielaborazione
#: (giro 3, §5): `rettifica` del contenuto o degli allegati, e `riapertura`.
CAMPI_RETTIFICA_DA_RIELABORARE: frozenset[str] = frozenset({"contenuto", "allegati"})


def rimette_in_rielaborazione(tipo: str, campo: Any) -> bool:
    """Un evento applicato di questo tipo (e campo) azzera il marcatore della rielaborazione?"""
    if tipo == "riapertura":
        return True
    return tipo == "rettifica" and campo in CAMPI_RETTIFICA_DA_RIELABORARE


#: Gli stati HTTP per cui lo scarico pagherebbe il ripiego Firecrawl (il WAF
#: nega la pagina): copiati da `scarico._STATI_RIPIEGO`, un test li confronta.
STATI_RIPIEGO: tuple[int, ...] = (403, 406)


def richiederebbe_ripiego(url: str, risposta: Any, host_richiede_js: Iterable[str] = ()) -> bool:
    """La pagina si leggerebbe solo con il ripiego Firecrawl? Pura.

    Le stesse tre ragioni di `scarico.Scarico._serve_ripiego`: WAF (403/406),
    host noto per il JS, app-shell (200 con uno scheletro). Un 304, un 404 o
    un 5xx no: il ripiego non li cambierebbe.
    """
    from .scarico import e_app_shell, host_di
    stato = getattr(risposta, "stato", None)
    if stato in STATI_RIPIEGO:
        return True
    if not getattr(risposta, "ok", False):
        return False
    if host_di(url) in {str(h).lower() for h in host_richiede_js}:
        return True
    return bool(e_app_shell(getattr(risposta, "html", "") or "", getattr(risposta, "testo", "") or ""))


def _scarico_rinviato(esito: EsitoControllo) -> EsitoControllo:
    """Tetto raggiunto e pagina leggibile solo a pagamento: nessuna colonna."""
    esito.esito = "rinviato"
    esito.scarico_rinviato = True
    esito.motivo = "lettura rinviata: servirebbe il ripiego a pagamento, tetto raggiunto"
    esito.colonne = {}
    return esito


def _classificazione_rinviata(esito: EsitoControllo) -> EsitoControllo:
    """Tetto di spesa: la pagina cambiata non si classifica e non si salva niente.

    Come `_classificazione_fallita`, ma non e' un errore: nessuna chiamata e'
    partita. Il prossimo controllo resta quello di prima, quindi la pagina
    risulta ancora cambiata al giro dopo.
    """
    esito.esito = "rinviato"
    esito.classificazione_rinviata = True
    esito.motivo = "classificazione rinviata: tetto di spesa raggiunto"
    esito.colonne = {}
    return esito


def _classificazione_fallita(esito: EsitoControllo, motivo: str) -> EsitoControllo:
    """Il modello non ha risposto: errore, e nessuna colonna salvata.

    Impronta, `testo_norm` e prossimo controllo restano quelli di prima, quindi
    la pagina risulta ancora cambiata e il giro dopo il modello la rivede.
    Niente `controlli_falliti`: la pagina non ha colpa, e qualche giro senza
    credito non deve bloccare il bando.
    """
    esito.esito = "errore"
    esito.classificazione_fallita = True
    esito.motivo = motivo[:300]
    esito.colonne = {}
    return esito


#: Dopo tanti fallimenti del modello di fila, nel resto del giro non lo si
#: chiama piu'. Col credito esaurito ogni chiamata fallisce: continuare non
#: salva niente, e le pagine cambiate restano comunque in coda per il giro dopo.
FALLIMENTI_MODELLO_DI_FILA = 3


async def _nessuna_concordanza(*_args: Any, **_kwargs: Any) -> None:
    return None


def _sospeso(*_args: Any, **_kwargs: Any) -> Awaitable[Any]:
    raise RuntimeError(
        f"chiamate al modello sospese per il resto del giro dopo "
        f"{FALLIMENTI_MODELLO_DI_FILA} fallimenti di fila")


def _con_interruttore(
    stato: dict[str, int],
    funzione: Callable[..., Awaitable[Any]],
    *,
    aperto: Callable[..., Awaitable[Any]] = _sospeso,
):
    """Avvolge una chiamata al modello con un interruttore per giro.

    Un successo azzera il conto, quindi un errore isolato (un 529) non spegne
    niente. Ad interruttore aperto si chiama `aperto` invece del modello.
    """
    async def chiama(*args: Any, **kwargs: Any) -> Any:
        if stato["di_fila"] >= FALLIMENTI_MODELLO_DI_FILA:
            return await aperto(*args, **kwargs)
        try:
            risultato = await funzione(*args, **kwargs)
        except Exception:
            stato["di_fila"] += 1
            raise
        stato["di_fila"] = 0
        return risultato
    return chiama


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
    #: Ignora la cadenza e prende tutti i bandi con una fonte trovata. Le altre
    #: tre condizioni di `selezionabile` restano: non si controlla un non
    #: pubblicato, un doppione fuso o un bando senza fonte ufficiale.
    forza: bool = False,
    contatori: bilancio.Contatori | None = None,
    lock: Any = blocco,
    orologio: Callable[[], float] | None = None,
    riscrittore: Callable[[Any, list[dict[str, Any]]], Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Un giro di monitoraggio. Ritorna i contatori; non solleva mai.

    Le chiavi che `bandi_pipeline.py` e `__main__.py` leggono:
    `status`, `saltato_per_lock`, `interrotto_per_tetto`, `slug_modificati`.

    Giro 3 (§1, §5): nessun tetto di numero. Tutti gli aperti a ogni giro,
    nell'ordine di `seleziona`, entro `TEMPO_MONITOR_S` (`orologio` si inietta
    nei test); chi resta fuori parte per primo al giro dopo. A tetto di spesa
    raggiunto il giro NON si ferma: le pagine si scaricano e si confrontano, e
    quelle cambiate aspettano il giro dopo (`classificazioni_rinviate`).
    `copertura` sta al primo livello del riepilogo.

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
    # risponde ai tetti di spesa del regime (dal giro 3: 5 $ al giorno e 150 al
    # mese; il tetto delle 30 classificazioni non c'e' piu'), che sono giusti a
    # regime e stretti per la **semina**: il primo giro su un bando non ha un
    # «prima» con cui confrontare, quindi passa dal modello sempre. Misurato il
    # 24/09/2026, col vecchio tetto: `candidati: 50, controllati: 30`. Il lotto
    # L6 sta sui tetti di backfill.
    passo = f"backfill:{lotto}" if lotto else STEP
    orologio = orologio or time.monotonic
    avvio = orologio()
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
    # L'interruttore per tipo (contratto §3). `--ombra` e `--dry-run` lo
    # spengono: chi li scrive vuole un giro che non tocchi niente di pubblico.
    # In attivo non serve, perche' ogni tipo e' gia' attivo.
    tipi_attivi: tuple[str, ...] = ()
    if not dry_run and attivo is not False and modalita != eventi_mod.MODALITA_ATTIVO:
        tipi_attivi = tuple(getattr(impostazioni, "monitor_tipi_attivi", ()) or ())
    tipi_ignorati = tuple(getattr(impostazioni, "monitor_tipi_attivi_ignorati", ()) or ())
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
        # Nessun tetto di numero (giro 3, §1): `limit` vale solo da riga di
        # comando. Il freno e' il tempo, con la rotazione di `seleziona`.
        tetto = max(0, int(limit)) if limit is not None else 0
        tempo_s = float(getattr(impostazioni, "tempo_monitor_s", TEMPO_MONITOR_S) or TEMPO_MONITOR_S)
        righe = dati.candidati(limite=tetto, adesso=momento, forza=forza)
        # Sospensione, revoca e annullamento solo con la migrazione 14 e gli
        # stati estesi (§3): altrimenti restano in ombra, senza allarme.
        tipi_in_attesa: tuple[str, ...] = ()
        # La migrazione 14 (§14), letta una volta per giro: decide i tipi
        # attivi e quali righe della lista bianca valgono per G9.
        capacita_14 = bool(dati.capacita_sospensioni())
        if tipi_attivi:
            tipi_attivi, tipi_in_attesa = eventi_mod.tipi_attivi_effettivi(
                tipi_attivi, capacita=capacita_14,
                stati_estesi=bool(getattr(impostazioni, "monitor_stati_estesi", False)))
        # Gli allarmi del giro: quelli della selezione piu' quelli dei tetti di
        # spesa. Vivono nel riepilogo e quindi in `pipeline_run`,
        # perche' un allarme che esiste solo in una riga di log e' un allarme
        # che nessuno legge il giorno in cui serve.
        allarmi: list[str] = list(getattr(dati, "allarmi", ()) or ())
        if tipi_ignorati:
            # Un tipo scritto male resta in ombra senza che nessuno lo decida:
            # l'allarme si ripete a ogni giro, finche' non si corregge `.env`.
            allarmi.append(
                f"MONITOR_TIPI_ATTIVI: valori ignorati {', '.join(tipi_ignorati)} "
                "(il monitor non produce questi tipi)")
        for allarme in allarmi:
            logger.warning("[ALLARME] [monitor] {}", allarme)

        scaricatore = None if senza_rete else (scarica or _scarico_predefinito())
        proprio = scarica is None and scaricatore is not None
        if proprio:
            # Il client del giro riparte pulito: una pagina di sei ore fa non
            # e' una prova di niente, e i crediti si contano da zero.
            _azzera_scarico()

        classificatore = classifica
        solo_riallineamenti = False
        if classificatore is None and righe and scaricatore is not None:
            classificatore = classificatore_da_impostazioni(impostazioni, contatori)
            if classificatore is None:
                # Senza `ANTHROPIC_API_KEY` `controlla` esce al passo 0 su
                # OGNI riga e non salva niente: nessuna riga esce dalla coda,
                # due giri di fila guardano gli stessi id e l'esito era
                # `status: ok`, exit 0. E' esattamente il caso per cui esiste
                # `EXIT_NON_CONFIGURATO`, e la chiave `saltato` e' quella che
                # `__main__._codice_da_contatori` traduce in 5.
                stantie = [r for r in righe if riga_stantia(r)]
                if not stantie:
                    logger.error(
                        "[monitor] nessun classificatore disponibile: {} candidati "
                        "non controllati, giro dichiarato non configurato", len(righe))
                    return dict(base, saltato="scarico_non_configurato",
                                candidati=len(righe), controllati=0, allarmi=allarmi)
                # Il riallineamento non chiama il modello: le righe stantie si
                # riallineano lo stesso (revisione del 30/09/2026). Il giro
                # resta dichiarato non configurato, con l'exit 5 di sempre.
                logger.error(
                    "[monitor] nessun classificatore disponibile: si riallineano solo "
                    "le {} righe stantie su {} candidati", len(stantie), len(righe))
                candidati_senza_modello = len(righe)
                righe = stantie
                solo_riallineamenti = True

        # Due interruttori, uno per modello: un successo di Haiku non deve
        # azzerare il conto degli errori di Sonnet. Dopo
        # FALLIMENTI_MODELLO_DI_FILA errori di fila il classificatore smette di
        # essere chiamato (le pagine restano da rifare), la seconda opinione
        # torna a valere «nessuna concordanza» per il resto del giro (il G7
        # passa solo con la prova indipendente, come prima del 28/09).
        if classificatore is not None:
            classificatore = _con_interruttore({"di_fila": 0}, classificatore)
        if seconda_opinione is not None:
            seconda_opinione = _con_interruttore(
                {"di_fila": 0}, seconda_opinione, aperto=_nessuna_concordanza)

        # La whitelist dei domini si costruisce UNA volta per giro, e solo se
        # c'e' davvero qualcosa da controllare. Senza, `eventi.g4_prova`
        # ripiega sul seed compilato — 20 host e 7 pattern — e respinge quasi
        # ogni ente reale: `lazioeuropa.it`, il caso guida di §6.2, non c'e'.
        if tabella_domini is None and righe and classificatore is not None:
            tabella_domini = _tabella_domini_del_giro()

        esiti: list[EsitoControllo] = []
        interrotto = False
        motivo_tetto = ""
        # Il consumo dei passi gia' scritti (oggi e mese di Roma) si legge una
        # volta: quello di questo giro e' in `contatori`, che crescono qui.
        # §18.5: None = lettura fallita, e per la manutenzione vale tetto
        # raggiunto (niente modello, niente crediti; i controlli gratuiti sì).
        consumo_letto = dati.consumo_oggi()
        gia_oggi = dict(consumo_letto or {})
        # La riscrittura delle schede con Opus (giro 3, §6) ha la sua spesa
        # (step `rigenerazione_scheda`), che conta nel tetto insieme a quella
        # del monitor. Si costruisce solo nel giro di produzione che scrive:
        # mai in dry-run, mai in ombra senza tipi attivi, mai con lo scarico
        # iniettato (i test passano il proprio `riscrittore`).
        spesa_riscritture = bilancio.Contatori()
        if riscrittore is None and proprio and not dry_run and (
                modalita == eventi_mod.MODALITA_ATTIVO or tipi_attivi):
            async def riscrittore(bando_id: Any, novita: list[dict[str, Any]]) -> Any:
                if consumo_letto is None:
                    # Consumo illeggibile (§18.5): Opus non si chiama, le
                    # novita' restano in coda per il giro dopo.
                    controllo = bilancio.verifica_con_consumo(
                        spesa_riscritture, tetti, step=rigenera_mod.STEP_RISCRITTURA, consumo=None)
                    if not controllo.consentito:
                        return rigenera_mod.Riscrittura(
                            bando_id=bando_id, esito=rigenera_mod.ESITO_RINVIATA,
                            motivo=controllo.motivo)
                return await rigenera_mod.riscrivi_scheda(
                    bando_id, novita, spesa=spesa_riscritture, tetti=tetti,
                    gia_oggi=_gia_con(gia_oggi, contatori))
        rinvia = False
        motivo_rinvio = "spesa"
        fuori_tempo = False
        # Gli host che lo scarico legge solo col ripiego: a tetto raggiunto le
        # loro pagine si rinviano invece di pagarlo (giro 3, §4).
        host_js = _host_richiede_js_dello_scarico() if proprio else frozenset()
        for riga in righe:
            if orologio() - avvio > tempo_s:
                # Tetto di tempo (§1 punto 2): chi resta fuori ha l'ultimo
                # controllo piu' vecchio e parte per primo al giro dopo.
                fuori_tempo = True
                break
            if not rinvia:
                verifica = bilancio.verifica_con_consumo(
                    contatori, tetti, step=passo,
                    consumo=None if consumo_letto is None else _gia_con(gia_oggi, spesa_riscritture))
                if not verifica.consentito:
                    # Il giro non si ferma (§4, §5): da qui in poi il modello
                    # non si chiama, le pagine si controllano lo stesso.
                    rinvia = True
                    motivo_tetto = verifica.motivo
                    motivo_rinvio = verifica.motivo_rimasti or "spesa"
                    avviso = (f"{verifica.motivo}: il modello non si chiama piu' in questo giro, "
                              f"le pagine cambiate si rivedono al giro dopo")
                    allarmi.append(avviso)
                    logger.warning("[ALLARME] [monitor] {}", avviso)
            if scaricatore is None:
                esiti.append(EsitoControllo(
                    bando_id=riga.get("id"), fase=fase(riga, oggi=momento.date()),
                    esito="saltato",
                    motivo="senza rete" if senza_rete else "nessuno scarico disponibile"))
                continue
            try:
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
                    tipi_attivi=tipi_attivi,
                    tabella_domini=tabella_domini,
                    adesso=momento,
                    casuale=casuale,
                    dry_run=dry_run,
                    rinvia_classificazione=rinvia,
                    host_richiede_js=host_js,
                    capacita_14=capacita_14,
                    riscrittore=None if dry_run else riscrittore,
                )
            except Exception as e:
                # §19.3: un'eccezione su un bando e' l'errore di quel bando, non
                # del giro. Niente colonne (la pagina non ha colpa: niente
                # `controlli_falliti`): il bando torna al giro dopo, e la riga
                # del giro con la spesa si scrive lo stesso.
                logger.warning("[monitor] bando {}: controllo interrotto da un'eccezione: {}",
                               riga.get("id"), f"{type(e).__name__}: {e}"[:200])
                esito = EsitoControllo(
                    bando_id=riga.get("id"), fase=fase(riga, oggi=momento.date()),
                    esito="errore", motivo=f"{PREFISSO_ECCEZIONE}{type(e).__name__}"[:200])
            contatori.classificazioni += 1 if esito.classificato else 0
            contatori.classificazioni_fallite += 1 if esito.classificazione_fallita else 0
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
        # Solo gli esiti con almeno un evento APPLICATO: un evento ammesso che la
        # RPC non ha scritto non cambia la pagina (revisione del 29/09/2026).
        # Vale anche per i tipi attivi in ombra (contratto §3): conta l'evento
        # applicato, non la modalita' del giro. In ombra senza tipi attivi
        # `eventi_applicati` e' sempre zero. Un evento applicato ma invisibile
        # non cambia la pagina (faq e allegati non toccano `bando`): conta solo
        # se ha portato una data nuova in prosa (revisione del 30/09/2026).
        slug_modificati = tuple(dict.fromkeys([
            *(e.slug for e in esiti
              if e.slug and _pagina_cambiata(e)
              and (not e.rigenerazione_dovuta or e.rigenerato)),
            # Giro 3 (§6): una scheda riscritta con Opus e' una pagina nuova.
            *(e.slug_riscritto for e in esiti if e.slug_riscritto),
        ]))
        # Date applicate e prosa rimasta vecchia: rigenerazione mancante o
        # fallita. La colonna e il box sono giusti, il testo no, e lo slug non
        # va a IndexNow. Senza questa riga non lo diceva nessuno.
        prosa_vecchia = sum(1 for e in esiti if e.rigenerazione_dovuta and not e.rigenerato)
        oggi_giro = momento.date()
        # Un giro `--senza-rete` (o senza uno scarico) accodava N esiti
        # `saltato` e riferiva `controllati: N, non_modificati: 0` con exit 0:
        # somigliava a un giro vero. `controllati` conta ora le righe davvero
        # controllate, e i saltati si dichiarano con il motivo prevalente.
        saltati = [e for e in esiti if e.esito == "saltato"]
        motivo_saltati = _motivo_prevalente(saltati)
        host_morti = sorted({e.host_irraggiungibile for e in esiti if e.host_irraggiungibile})
        if host_morti:
            logger.warning("[monitor] host irraggiungibili (DNS) in questo giro: {}",
                           ", ".join(host_morti))
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
            # Di cui: righe di una pulizia vecchia riscritte senza diff ne'
            # modello (`impronte.VERSIONE_PULIZIA`). Dopo un cambio di pulizia
            # scendono a zero man mano che le righe tornano in coda.
            "riallineate": sum(1 for e in esiti if e.riallineato),
            # Fonti con il DNS rotto: saltate senza consumare `controlli_falliti`.
            # Il numero e i primi nomi: lo stesso host morto per giorni si vede
            # a DB, giro dopo giro.
            "host_irraggiungibili": len(host_morti),
            "host_irraggiungibili_elenco": host_morti[:MAX_HOST_IRRAGGIUNGIBILI_ELENCO],
            "errori": contatori.errori,
            "classificazioni": contatori.classificazioni,
            # Controlli rimasti a meta' perche' il modello non ha risposto: NON
            # sono in `classificazioni`, che conta le chiamate riuscite e
            # alimenta i tetti. Maggiori di zero vuol dire credito esaurito o
            # API giu': `salute` lo legge da qui.
            "classificazioni_fallite": contatori.classificazioni_fallite,
            # Solo in attivo: ammessi ma non applicati dalla RPC. Restano a DB
            # non applicati e invisibili: li riprende `applica-eventi --attivo`.
            "eventi_non_applicati": sum(e.eventi_non_applicati for e in esiti),
            # L'interruttore per tipo (contratto §3): la lista che questo giro ha
            # usato (vuota con `--ombra`, `--dry-run` o in attivo) e cio' che ha
            # applicato, per tipo, in entrambi i percorsi.
            "tipi_attivi": list(tipi_attivi),
            "applicati_per_tipo": dict(sorted(Counter(
                tipo for e in esiti for tipo in e.tipi_applicati).items())),
            # Applicati alle colonne ma non resi leggibili: la pagina e'
            # cambiata, il box no.
            "eventi_invisibili": sum(e.eventi_invisibili for e in esiti),
            # Tipi attivi ammessi dai gate ma non verificati per il DB: restano
            # in ombra, come fa `applica-eventi`.
            "eventi_non_verificati": sum(e.eventi_non_verificati for e in esiti),
            # Di questi tipi, quelli di cui `verificato` non si e' potuto
            # rileggere: in ombra anche loro, ma sono errori, non giudizi.
            "errori_verifica": sum(e.errori_verifica for e in esiti),
            "prosa_non_riscritta": prosa_vecchia,
            # Di cui: Haiku ha risposto (e sta in `classificazioni`), Sonnet no.
            # `salute` le toglie dalle riuscite per non contarle due volte.
            "seconde_opinioni_fallite": sum(
                1 for e in esiti if e.classificato and e.classificazione_fallita),
            "eventi": contatori.eventi,
            "respinti": sum(len(e.respinti) for e in esiti),
            # Un giro che propone eventi e non riesce a scriverne nemmeno uno
            # non e' un giro riuscito, e finche' questo numero non c'era
            # nessuno poteva accorgersene.
            "eventi_non_scritti": sum(e.eventi_non_scritti for e in esiti),
            "allegati_aggiornati": sum(len(e.allegati) for e in esiti),
            # Giro 3 (§5): pagine cambiate non classificate per il tetto di
            # spesa (nessuna colonna salvata: si rivedono al giro dopo), bandi
            # rimessi in coda alla rielaborazione, giro tagliato dal tempo, e i
            # tipi che restano in ombra in attesa della migrazione 14.
            "classificazioni_rinviate": sum(1 for e in esiti if e.classificazione_rinviata),
            "scarichi_rinviati": sum(1 for e in esiti if e.scarico_rinviato),
            "rielaborazioni_richieste": sum(1 for e in esiti if e.rielaborazione_richiesta),
            # Giro 3 (§6): riscritture delle schede con Opus e documenti nuovi.
            "riscritture": sum(1 for e in esiti if e.riscrittura == rigenera_mod.ESITO_SCRITTA),
            "riscritture_rinviate": sum(
                1 for e in esiti if e.riscrittura == rigenera_mod.ESITO_RINVIATA),
            "riscritture_fallite": sum(
                1 for e in esiti if e.riscrittura == rigenera_mod.ESITO_FALLITA),
            "riscritture_abbandonate": sum(
                1 for e in esiti if e.riscrittura == RISCRITTURA_ABBANDONATA),
            "allegati_registrati": sum(e.allegati_registrati for e in esiti),
            "eventi_scartati": sum(e.eventi_scartati for e in esiti),
            "novita_rinviate": sum(e.novita_rinviate for e in esiti),
            "allegati_senza_url": sum(e.allegati_senza_url for e in esiti),
            "interrotto_per_tempo": fuori_tempo,
            "tipi_in_attesa_migrazione_14": list(tipi_in_attesa),
            "interrotto_per_tetto": interrotto,
            "motivo": motivo_tetto,
            "allarmi": allarmi,
            "slug_modificati": list(slug_modificati),
            "durata_s": round(orologio() - avvio, 1),
        }
        non_scritti = int(riepilogo["eventi_non_scritti"])
        if non_scritti:
            # Allarme e non riga di log: un giro che valuta le pagine, paga il
            # modello e non riesce a scrivere gli eventi sta girando a vuoto, e
            # il periodo d'ombra non misura niente. Il 25/09/2026 e' andata
            # avanti cosi' per due giorni perche' nessuno guardava i warning di
            # `db.registra_evento`.
            avviso = (f"{non_scritti} eventi non scritti: il database li ha "
                      f"rifiutati, l'ombra non sta misurando niente")
            allarmi.append(avviso)
            logger.warning("[ALLARME] [monitor] {}", avviso)
            riepilogo["allarmi"] = allarmi
        # Il comando di ripresa porta `--tipo` e `--dal`: senza, applicherebbe
        # l'arretrato verificato di ogni tipo (T-D5).
        ripresa = _comando_di_ripresa(
            [i for e in esiti for i in e.ids_non_applicati],
            (t for e in esiti for t in e.tipi_non_applicati), oggi_giro)
        if riepilogo["eventi_non_applicati"]:
            avviso = (f"{riepilogo['eventi_non_applicati']} eventi ammessi non applicati dalla RPC: "
                      f"restano in coda, lanciare {ripresa}")
            allarmi.append(avviso)
            logger.warning("[ALLARME] [monitor] {}", avviso)
            riepilogo["allarmi"] = allarmi
        if riepilogo["eventi_invisibili"]:
            avviso = (f"{riepilogo['eventi_invisibili']} eventi applicati ma non resi leggibili: "
                      f"il box non li mostra, lanciare {ripresa}")
            allarmi.append(avviso)
            logger.warning("[ALLARME] [monitor] {}", avviso)
            riepilogo["allarmi"] = allarmi
        # Tanti host morti nello stesso giro: piu' probabile il resolver del
        # server che tanti enti col DNS rotto (decisione del lead del
        # 30/09/2026). Con lo scarico di produzione contano anche quelli trovati
        # da resolver e ricontrolli nello stesso giro.
        morti_nel_giro = set(host_morti) | {
            _senza_www(h) for h in (_host_morti_dello_scarico() if proprio else ())}
        from .scarico import SOGLIA_RESOLVER_LOCALE
        if len(morti_nel_giro) >= SOGLIA_RESOLVER_LOCALE:
            avviso = (f"resolver locale? {len(morti_nel_giro)} host irraggiungibili (DNS) in "
                      f"questo giro: " + ", ".join(sorted(morti_nel_giro)[
                          :MAX_HOST_IRRAGGIUNGIBILI_ELENCO]))
            allarmi.append(avviso)
            logger.warning("[ALLARME] [monitor] {}", avviso)
            riepilogo["allarmi"] = allarmi
        if prosa_vecchia:
            avviso = (f"{prosa_vecchia} schede con date applicate e prosa non riscritta: "
                      f"rigenerazione assente o fallita, lo slug non va a IndexNow "
                      f"(lanciare rigenera sui bandi del giro)")
            allarmi.append(avviso)
            logger.warning("[ALLARME] [monitor] {}", avviso)
            riepilogo["allarmi"] = allarmi
        fallite = contatori.classificazioni_fallite
        if fallite:
            # Il controllo quotidiano di RIPRESA §3.1 cerca «[ALLARME]» nel
            # journal: senza questa riga il credito esaurito passava di li'.
            # Stessa soglia di `salute`: qualche errore isolato fra tante
            # riuscite e' un warning, non un allarme sul credito.
            riuscite = max(0, contatori.classificazioni - riepilogo["seconde_opinioni_fallite"])
            avviso = (f"{fallite} classificazioni fallite su {fallite + riuscite}: credito "
                      f"Anthropic esaurito o API giu' (le pagine si rifanno al giro dopo)")
            if fallite >= riuscite:
                allarmi.append(avviso)
                logger.warning("[ALLARME] [monitor] {}", avviso)
                riepilogo["allarmi"] = allarmi
            else:
                logger.warning("[monitor] {}", avviso)
        if solo_riallineamenti:
            # Il giro ha lavorato solo le righe stantie: resta un giro «non
            # configurato» (exit 5), e l'allarme lo dice nel journal e a DB.
            avviso = (f"nessun classificatore disponibile: solo {riepilogo['riallineate']} "
                      f"riallineamenti su {candidati_senza_modello} candidati, "
                      f"gli altri non controllati")
            allarmi.append(avviso)
            logger.warning("[ALLARME] [monitor] {}", avviso)
            riepilogo.update(allarmi=allarmi, saltato="scarico_non_configurato",
                             candidati=candidati_senza_modello)
        # Copertura (§1): fatti i bandi controllati fino in fondo; restano
        # fuori quelli oltre il tempo, le pagine cambiate rinviate per spesa,
        # quelle che il modello non ha classificato e i saltati senza nemmeno
        # un tentativo (senza rete, senza classificatore). Un host morto (DNS)
        # e' stato tentato: conta fra i fatti.
        rinviate = int(riepilogo["classificazioni_rinviate"]) + int(riepilogo["scarichi_rinviati"])
        non_classificate = sum(1 for e in esiti if e.classificazione_fallita)
        non_tentati = sum(1 for e in esiti if e.esito == "saltato" and not e.host_irraggiungibile)
        # §19.3: un controllo interrotto da un'eccezione non e' fatto.
        interrotti = sum(1 for e in esiti if e.esito == "errore"
                         and str(e.motivo).startswith(PREFISSO_ECCEZIONE))
        motivo_rimasti = ("tempo" if fuori_tempo else motivo_rinvio if rinviate
                          else "errore" if (non_classificate or non_tentati or interrotti
                                            or solo_riallineamenti)
                          else None)
        riepilogo["copertura"] = telemetria.copertura(
            riepilogo["candidati"],
            len(esiti) - rinviate - non_classificate - non_tentati - interrotti,
            motivo_rimasti)
        if not dry_run:
            _scrivi_telemetria_riscritture(esiti, spesa_riscritture, giro,
                                           tempo=orologio() - avvio)
        _scrivi_telemetria(riepilogo, contatori, giro, slug_modificati, interrotto,
                           tempo=orologio() - avvio, passo=passo)
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
    3. **un solo tentativo.** Niente ritentativi qui: un retry per bando
       moltiplicherebbe il conto proprio sui giri in cui la rete va male.
       L'errore pero' risale a `controlla` (dal 28/09/2026: prima valeva
       `None`, cioe' «nessuna concordanza», e con Sonnet giu' gli eventi
       venivano respinti al G7 mentre l'impronta nuova si salvava), che lascia
       la pagina da rifare al giro dopo.

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
            # Nessun ritentativo, ma l'errore risale: vedi il punto 3.
            logger.warning(
                "[monitor] seconda opinione non ottenuta per il bando {}: {}",
                ctx.bando_id, e)
            raise
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
    # §19.3: gli URL arrivano dalle pagine (ancore, `link` dei post WP). Uno
    # malformato (`http://[object Object]`) fa sollevare `urlsplit` e
    # `host_di`: non e' nessuna pagina, e lo scarta poi la guardia sugli
    # indirizzi.
    try:
        pezzi = urlsplit(url.strip())
        parametri = sorted(parse_qsl(unquote(pezzi.query), keep_blank_values=True))
        # Schema e host fuori dalla forma normale del percorso: l'host lo mette
        # `_host_di`, che e' gia' quello senza `www.` dello scarico.
        resto = urlunsplit(("", "", pezzi.path, urlencode(parametri), ""))
        return f"{_host_di(url)}|{chiave(resto)}"
    except ValueError:
        return ""


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
        # §19.3: un href malformato fa sollevare `urljoin`; si salta lui, non
        # le pagine collegate di tutto l'host.
        try:
            assoluto = urljoin(base, href)
        except ValueError:
            continue
        trovate.append((assoluto, ancora.get_text(" ", strip=True)))
    return trovate


def pagine_collegate_da_impostazioni(
    impostazioni: Any,
    *,
    scarica: Callable[..., Awaitable[Any]] | None = None,
    news_per_host: Mapping[str, str] | None = None,
    adesso: datetime | None = None,
    pubblico: Callable[[str], Awaitable[bool]] | None = None,
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

    Indirizzi interni (§18.6): la pagina di notizie, la ricerca WordPress e
    ogni pagina collegata proposta (ancore e `link` dei post, che possono
    puntare a qualunque host) passano da `http.indirizzo_pubblico_async` prima
    della GET. Un host che risolve a loopback, rete privata, link-local o
    comunque non pubblico non si chiede: il registro delle notizie finisce in
    `muti`, la pagina collegata non si propone. Il giudizio si tiene per host
    per tutto il giro (una risoluzione DNS sola). `pubblico` e' per i test (un
    DNS finto); in produzione resta `None`.
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
    giudicati: dict[tuple[str, str], bool] = {}

    async def _pubblico(url: str) -> bool:
        """`http.indirizzo_pubblico_async`, una volta per (schema, host) per giro.
        Nel dubbio (errore della guardia) no."""
        try:
            parti = urlsplit(url)
            chiave = (parti.scheme.lower(), (parti.hostname or "").lower())
        except ValueError:
            return False
        if chiave not in giudicati:
            try:
                if pubblico is not None:
                    esito = await pubblico(url)
                else:
                    from . import http as http_mod
                    esito = await http_mod.indirizzo_pubblico_async(url)
            except Exception as e:
                logger.debug("[monitor] guardia sugli indirizzi fallita per {}: {}", chiave[1], e)
                esito = False
            giudicati[chiave] = bool(esito)
            if not esito:
                logger.info("[monitor] host {} non pubblico: nessuna pagina collegata da li'",
                            chiave[1] or "?")
        return giudicati[chiave]

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
        if not await _pubblico(url):
            # §18.6: niente richiesta verso un host interno, e niente altri
            # tentativi per il resto del giro.
            muti.add(host)
            return None
        try:
            # `principale=False`: niente ripiego Firecrawl (§6.2).
            # §19.6: redirect solo sullo stesso host, gia' giudicato da
            # `_pubblico`: un 302 verso un host interno non si segue.
            risposta = await prendi(url, principale=False, redirect=REDIRECT_STESSO_HOST)
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
                # §18.6: `controlla` la scarichera' con una GET.
                if not await _pubblico(url_notizia):
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
    """Inizio giro sul client unico: cache vuota e contatori a zero.

    Gli host irraggiungibili restano: il monitor parte a meta' pipeline, e un
    host trovato morto da resolver o ricontrolli dello stesso giro si salta
    anche qui. Li azzera solo `svuota()` a inizio pipeline.
    """
    try:
        from .scarico import svuota
        svuota(host_morti=False)
    except Exception as e:                                # pragma: no cover - ripiego
        logger.debug("[monitor] azzeramento dello scarico fallito: {}", e)


def _host_richiede_js_dello_scarico() -> frozenset[str]:
    """Gli host che il client unico legge solo col ripiego Firecrawl."""
    try:
        from .scarico import scarico_corrente
        return frozenset(scarico_corrente().host_richiede_js)
    except Exception as e:                                # pragma: no cover - ripiego
        logger.debug("[monitor] host richiede_js dello scarico non leggibili: {}", e)
        return frozenset()


def _host_morti_dello_scarico() -> tuple[str, ...]:
    """Gli host irraggiungibili che il client unico ha segnato in questo giro."""
    try:
        from .scarico import scarico_corrente
        return scarico_corrente().host_irraggiungibili
    except Exception as e:                                # pragma: no cover - ripiego
        logger.debug("[monitor] host morti dello scarico non leggibili: {}", e)
        return ()


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


def _gia_con(gia_oggi: Mapping[str, Any] | None, *altri: bilancio.Contatori) -> dict[str, Any]:
    """Il consumo gia' scritto piu' quello di altri contatori di questo giro.

    Il monitor e le riscritture spendono nello stesso giro con contatori
    separati (righe `pipeline_run` diverse): ciascuno, per il tetto, deve
    vedere anche la spesa dell'altro, sul giorno e sul mese.
    """
    somma = dict(gia_oggi or {})
    for contatori in altri:
        for voce, valore in (("usd", contatori.usd), ("crediti", contatori.crediti_firecrawl),
                             ("ricerche", contatori.ricerche)):
            somma[voce] = float(somma.get(voce) or 0) + valore
        for voce, valore in (("usd_mese", contatori.usd), ("crediti_mese", contatori.crediti_firecrawl)):
            if voce in somma:
                somma[voce] = float(somma.get(voce) or 0) + valore
    return somma


def _scrivi_telemetria_riscritture(
    esiti: Sequence[EsitoControllo],
    spesa: bilancio.Contatori,
    giro: str | None,
    *,
    tempo: float,
) -> None:
    """La riga `pipeline_run` step `rigenerazione_scheda` (giro 3, §4 e §6).

    Solo se nel giro c'era almeno una scheda da riscrivere. Candidati i bandi
    con novita', fatti quelli riscritti; rimasti per spesa (rinviate) o per
    errore (fallite, abbandonate).
    """
    tentate = [e for e in esiti if e.riscrittura]
    if not tentate:
        return
    scritte = sum(1 for e in tentate if e.riscrittura == rigenera_mod.ESITO_SCRITTA)
    rinviate = sum(1 for e in tentate if e.riscrittura == rigenera_mod.ESITO_RINVIATA)
    saltate = sum(1 for e in tentate if e.riscrittura == rigenera_mod.ESITO_SALTATA)
    motivo = "spesa" if rinviate else "errore"
    contatori = {
        **spesa.come_dizionario(),
        "riscritture": scritte, "riscritture_rinviate": rinviate, "riscritture_saltate": saltate,
        "riscritture_fallite": sum(1 for e in tentate if e.riscrittura in (
            rigenera_mod.ESITO_FALLITA, RISCRITTURA_ABBANDONATA)),
        "copertura": telemetria.copertura(len(tentate) - saltate, scritte, motivo),
    }
    riga = telemetria.PipelineRun(step=rigenera_mod.STEP_RISCRITTURA, giro=giro).concludi(
        durata_s=tempo, contatori=contatori,
        slug_modificati=tuple(e.slug_riscritto for e in tentate if e.slug_riscritto))
    logger.info("[monitor] {}", telemetria.riepilogo(riga))
    try:
        telemetria.scrivi_pipeline_run(riga)
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[monitor] telemetria delle riscritture non scritta: {}", e)


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
#: Vale per gli eventi che portano `stato_bando`. Quelli con `stato_proposto`
#: la RPC della 04 non li respinge affatto, li brucia: li ferma prima
#: `attende_traduzione`.
TIPI_IN_ATTESA_DI_MIGRAZIONE: tuple[str, ...] = (
    "sospensione", "revoca", "annullamento_revoca",
)

#: Le coppie tipo → stato che la migrazione 11 traduce da `stato_proposto` a
#: `stato_bando` dentro `bando_applica_evento` (blocco v11_11). Gemelle di
#: quel blocco e di `eventi.transizione_evento`:
#: `test_traduzione_stato_proposto_sql` confronta le tre.
TRADUZIONI_STATO_PROPOSTO: dict[str, str] = {
    "sospensione": "sospeso",
    "revoca": "revocato",
}


def attende_traduzione(riga: Mapping[str, Any], *, traduzione: bool) -> bool:
    """Vero se mandare questo evento alla RPC lo brucerebbe.

    Finche' `MONITOR_STATI_ESTESI` e' falso il monitor registra sospensione e
    revoca con `valore_dopo = {"stato_proposto": …}` (A30). La RPC della 04
    tiene solo sei chiavi, fra cui non c'e' `stato_proposto`: trova
    `campi = {}`, marca l'evento applicato e risponde true con la colonna
    intatta. Poi `applica-eventi` lo rende leggibile, e l'evento non torna piu'
    in coda (`valore_dopo` e' immutabile).

    `traduzione` dice se la RPC puo' applicare la traduzione: il corpo vivo
    contiene il blocco della 11 e il CHECK ha i cinque stati della 06 (senza,
    l'evento tradotto verrebbe respinto e ripresentato a ogni lancio). Anche
    allora passano solo le coppie di `TRADUZIONI_STATO_PROPOSTO`, perche' solo
    quelle la RPC traduce. Uno `stato_bando` esplicito vince: la RPC
    applica quello e `stato_proposto` non conta.
    """
    dopo = riga.get("valore_dopo")
    if not isinstance(dopo, Mapping) or "stato_proposto" not in dopo:
        return False
    if "stato_bando" in dopo:
        return False
    if not traduzione:
        return True
    tipo = str(riga.get("tipo") or "")
    return TRADUZIONI_STATO_PROPOSTO.get(tipo) != dopo.get("stato_proposto")


#: I tipi il cui valore e' una data che la RPC deve scrivere in colonna.
TIPI_CON_DATA_IN_COLONNA: tuple[str, ...] = ("proroga", "apertura", "riapertura")


def valore_non_applicabile(riga: Mapping[str, Any]) -> bool:
    """Vero se la RPC applicherebbe l'evento perdendone la data.

    Gli eventi registrati prima del 29/09/2026 portano la data di una proroga
    o di un'apertura senza `campo` in `{"valore": …}`, chiave che
    `bando_applica_evento` scarta: l'evento risulterebbe applicato con la data
    vecchia, e `valore_dopo` e' immutabile. Non si mandano alla RPC: restano in
    coda, contati in `in_attesa_valore`, per una correzione decisa a mano.
    """
    if str(riga.get("tipo") or "") not in TIPI_CON_DATA_IN_COLONNA:
        return False
    dopo = riga.get("valore_dopo")
    if not isinstance(dopo, Mapping) or "valore" not in dopo:
        return False
    return "data_scadenza" not in dopo and "data_apertura" not in dopo


def _capacita_eventi() -> tuple[bool, bool]:
    """(traduzione, stati_cinque) dal marcatore della migrazione 11.

    Nel dubbio `(False, False)`: un falso fa solo aspettare un evento, un vero
    sbagliato lo brucerebbe o annoterebbe per sempre un rifiuto che la 06
    avrebbe sbloccato.
    """
    try:
        from . import db
        capacita = db.capacita_eventi()
        return (capacita.get(db.CAPACITA_TRADUZIONE) is True,
                capacita.get(db.CAPACITA_STATI_CINQUE) is True)
    except Exception as e:
        logger.warning("[applica-eventi] marcatore della migrazione 11 illeggibile: {}", e)
        return False, False


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
    limit: int | None = None,
    dry_run: bool = True,
    applica: Callable[[Mapping[str, Any]], Any] | None = None,
    segnala: Callable[[Mapping[str, Any]], bool] | None = None,
    stati_estesi: bool = False,
    traduzione: bool = False,
    motivo_scarto: Callable[[Any], str | None] | None = None,
) -> dict[str, Any]:
    """Applica a posteriori gli eventi raccolti in ombra (§6.2).

    Giro 3 (§14): dopo un `false` della RPC, `motivo_scarto(id)` rilegge
    `scartato_per`. Un evento marcato (superato, transizione non ammessa) si
    conta in `scartati` e NON si annota: la marcatura basta a tenerlo fuori
    dalla coda. Senza marcatura (o senza la 14) resta il rifiuto di sempre.

    Senza questo comando la baseline delle impronte li perderebbe: alla seconda
    lettura la pagina non e' piu' «cambiata», quindi l'evento non si ripresenta.
    Nessun blocco (giro 3, §1): `limit` None vuol dire tutti; i tipi si attivano uno alla volta
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

    Gli eventi che la RPC brucerebbe (`attende_traduzione`: `stato_proposto`
    senza la migrazione 11) non le arrivano nemmeno: si contano in
    `in_attesa_traduzione`, non si applicano e non si annotano. Il filtro sta
    qui e non solo nella selezione perche' le righe iniettate non passano da
    `_da_applicare`.
    """
    scelte: list[Mapping[str, Any]] = []
    # `esaminati` e `ultimo_id` sono diagnostica: dicono quanto del blocco
    # letto e' stato guardato e fin dove. Servono a riconoscere il giro che
    # legge 50 righe e ne applica zero, che e' la forma che prende uno stallo.
    esaminati = 0
    ultimo_id: Any = None
    in_attesa_traduzione = 0
    in_attesa_valore = 0
    for riga in righe:
        esaminati += 1
        ultimo_id = riga.get("id", ultimo_id)
        if not applicabile(riga, dal=dal, tipo=tipo):
            continue
        if attende_traduzione(riga, traduzione=traduzione):
            in_attesa_traduzione += 1
            continue
        if valore_non_applicabile(riga):
            in_attesa_valore += 1
            continue
        scelte.append(riga)
        if limit is not None and len(scelte) >= max(1, limit):
            break

    applicati = 0
    rifiutati = 0
    non_tentati = 0
    segnalati = 0
    scartati: dict[str, int] = {}
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
            marcato = None
            if motivo_scarto is not None:
                try:
                    marcato = motivo_scarto(riga.get("id"))
                except Exception as e:                    # pragma: no cover - ripiego
                    logger.warning("[monitor] scartato_per dell'evento {} non letto: {}",
                                   riga.get("id"), e)
            if marcato:
                scartati[marcato] = scartati.get(marcato, 0) + 1
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
        "scartati_per_motivo": dict(sorted(scartati.items())),
        "in_attesa_traduzione": in_attesa_traduzione,
        "in_attesa_valore": in_attesa_valore,
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

# Nessun blocco di applicazione (giro 3, §1, «niente lotti»): `applica-eventi`
# applica tutti gli eventi in coda; `--limit` resta solo come scelta esplicita
# di chi lancia il comando. Il vecchio `BLOCCO_APPLICAZIONE` (50) non c'e' piu'.

#: Quanti eventi si chiedono per pagina mentre si cerca che cosa applicare.
#: Non e' il blocco dell'operatore: e' la finestra su cui si scorre.
PAGINA_SELEZIONE_EVENTI = 200

# I rifiuti gia' noti (`elaborazione_bloccata` con `riferisce_a`) si leggono
# TUTTI, scorrendo le pagine (`db.select_eventi(limit=None)`): il vecchio tetto
# di 2 000 righe lasciava fuori proprio gli ultimi rifiuti, che tornavano in
# coda a ogni lancio (giro 3, §1).

#: Le sole due colonne che servono a riconoscere un rifiuto. `riferisce_a` e'
#: il dato, `id` c'e' perche' `_colonne_disponibili` non restituisca una
#: select vuota su uno schema che non ha ancora la colonna.
COLONNE_RIFIUTO: tuple[str, ...] = ("id", "riferisce_a")

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
        # Si misura **solo** cio' che il classificatore ha proposto. Escludere
        # i soli `TIPI_INTERNI` non bastava: restavano dentro `pubblicazione`
        # (2 143 righe scritte dal backfill della 02), `fonte_ufficiale_*` e le
        # transizioni automatiche del cron, che sono eventi di sistema con
        # `verificato=false` per costruzione. Misurato il 25/09/2026: il
        # campione da 100 era fatto di 100 `pubblicazione` e la precisione
        # usciva 0 su un monitor che aveva appena ammesso 6 eventi su 17.
        # `TIPI_PROPONIBILI` e' lo stesso insieme che il tool del modello
        # ammette: la popolazione giusta e' quella, non «tutto tranne gli
        # interni».
        if riga.get("tipo") not in eventi_mod.TIPI_PROPONIBILI:
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
            # I tipi si filtrano **nella query**, non a valle. Altrimenti il
            # `--limit` conta le righe lette e non quelle misurate: il
            # 25/09/2026 il registro aveva 336 `segnale_fonte` e 16
            # `chiusura_automatica` davanti a 17 proposte, e un campione da 100
            # righe non ne conteneva nemmeno una — il report diceva
            # `eventi: 0` su un giro che aveva appena ammesso sei eventi.
            righe = db.select_eventi(
                tipi=(tipo,) if tipo else eventi_mod.TIPI_PROPONIBILI, dal=dal,
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
    comando. Si leggono tutti, a pagine (giro 3, §1): una lista incompleta
    rimetterebbe in coda proprio gli eventi che non si possono applicare, ed
    e' il difetto che questa funzione esiste per evitare.
    """
    try:
        from . import db
        righe = db.select_eventi(
            tipi=("elaborazione_bloccata",), limit=None,
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
    limit: int | None,
    offset: int,
    rifiutati: frozenset[Any],
    conto: dict[str, int],
    traduzione: bool = False,
    ids: Sequence[Any] = (),
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
        # Giro 3 (§14): anche `scartato_per`; senza la 14 la colonna non c'e'
        # e la select non la chiede (`_colonne_disponibili`).
        colonne = getattr(db, "COLONNE_EVENTO", None)
        extra = {"colonne": tuple(colonne) + (COLONNA_SCARTATO,)} if colonne else {}
        try:
            pagina = db.select_eventi(
                tipi=tuple(tipi), dal=dal, applicato=False, verificato=True,
                limit=PAGINA_SELEZIONE_EVENTI, offset=cursore, ids=tuple(ids), **extra,
            )
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[applica-eventi] lettura degli eventi fallita: {}", e)
            break
        if not pagina:
            break
        cursore += len(pagina)
        for riga in pagina:
            conto["attraversati"] += 1
            if riga.get(COLONNA_SCARTATO):
                # Marcato dalla RPC della 14 (superato, transizione non
                # ammessa): non torna in coda, si rimette a mano.
                conto["scartati"] = conto.get("scartati", 0) + 1
                continue
            if riga.get("id") in rifiutati:
                # Gia' rifiutato da un giro precedente e l'annotazione e' in
                # tabella: riproporlo significherebbe solo riconsumare il
                # blocco, giro dopo giro.
                conto["bloccati"] += 1
                continue
            if not applicabile(riga, dal=dal):
                conto["saltati"] += 1
                continue
            if attende_traduzione(riga, traduzione=traduzione):
                # Senza la migrazione 11 la RPC lo brucerebbe: non consuma il
                # blocco e resta in coda, intatto, per quando la 11 ci sara'.
                conto["in_attesa_traduzione"] += 1
                continue
            if valore_non_applicabile(riga):
                # La RPC ne perderebbe la data: non consuma il blocco e resta
                # in coda, intatto.
                conto["in_attesa_valore"] += 1
                continue
            raccolti.append(riga)
            if limit is not None and len(raccolti) >= max(0, limit):
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
    ids: Sequence[Any] = (),
    righe: Sequence[Mapping[str, Any]] | None = None,
    applica: Callable[[Mapping[str, Any]], Any] | None = None,
    segnala: Callable[[Mapping[str, Any]], bool] | None = None,
    impostazioni: Any = None,
    lock: Any = blocco,
    motivo_scarto: Callable[[Any], str | None] | None = None,
) -> dict[str, Any]:
    """`applica-eventi`: riversa a posteriori gli eventi raccolti in ombra (§6.2).

    `ids` (`--ids 12,13`) e' il filtro esatto che gli allarmi del monitor
    scrivono: riprende soltanto gli eventi di quel giro, mai l'arretrato
    dell'ombra (T-D5), che un filtro per tipo e per giorno invece prenderebbe.

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
      * nessun blocco (giro 3, §1): tutti gli eventi in coda; `--limit` e'
        solo una scelta esplicita di chi lancia;
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

    # Nessun blocco (giro 3, §1): None = tutti. `--limit` resta esplicito.
    blocco_giro: int | None = None if limit is None else max(0, int(limit))

    preso = lock.acquisisci(NOME_LOCK, f"{STEP_APPLICA}:cli", blocco.TTL_PREDEFINITO_S)
    if not preso.proseguire:
        return lock.esito_saltato(preso)
    conto = {"attraversati": 0, "saltati": 0, "bloccati": 0, "scartati": 0, "in_attesa_traduzione": 0,
             "in_attesa_valore": 0}
    try:
        # Il marcatore della migrazione 11, letto anche in `--dry-run` (e' una
        # lettura). Con le righe iniettate non c'e' un DB da interrogare: nel
        # dubbio, niente traduzione e niente cinque stati.
        traduzione, stati_cinque = _capacita_eventi() if righe is None else (False, False)
        # Prima della 06 anche un evento tradotto viene respinto dal CHECK a tre
        # valori: mandarlo alla RPC non applicherebbe niente e riconsumerebbe il
        # blocco a ogni lancio. Gli eventi con `stato_proposto` passano solo
        # quando ci sono tutte e due, la traduzione (11) e i cinque stati (06).
        proposti_applicabili = traduzione and stati_cinque
        # Il `--limit` conta gli eventi da applicare, non le righe lette: la
        # selezione si scorre a pagine e gli eventi gia' rifiutati dalla RPC
        # (che restano `applicato=false` all'id piu' basso, per sempre) non
        # consumano il blocco.
        candidati = _da_applicare(
            righe, tipi=tipi, dal=dal, limit=blocco_giro, offset=offset, ids=ids,
            # Con `--limit 0` non si applica niente per costruzione (il ciclo
            # piu' sotto esce al primo giro): leggere i rifiuti noti sarebbe
            # una richiesta in piu' per un comando che e' un no-op.
            # `--riprova-rifiutati` e' la via di rientro, e serve perche'
            # l'annotazione non si puo' togliere: `bando_evento` non concede
            # DELETE nemmeno a `service_role` e `riferisce_a` e' immutabile.
            # Senza, un rifiuto annotato per sbaglio resterebbe tale per sempre.
            rifiutati=(eventi_gia_rifiutati()
                       if righe is None and (blocco_giro is None or blocco_giro > 0)
                       and not riprova_rifiutati else frozenset()),
            conto=conto,
            traduzione=proposti_applicabili,
        )
        if applica is None and scrive:
            from . import db

            def applica(riga: Mapping[str, Any]) -> str:
                """L'unico scrittore: la RPC `bando_applica_evento` (§6.2).

                Si costruisce solo quando il giro scrive davvero, cosi' in
                ombra la RPC non e' nemmeno raggiungibile. Restituisce l'esito
                e non un booleano: chi annota il rifiuto deve poter distinguere
                «la RPC ha detto no» da «la RPC non c'era».

                **Due scritture, non una.** La RPC riversa `valore_dopo` nelle
                colonne di `bando` e marca l'evento `applicato`, ma non tocca
                `leggibile`: senza il secondo UPDATE il trigger del cursore non
                scatta, la RLS di anon nasconde la riga e il box
                «Aggiornamenti» resta vuoto. Misurato il 25/09/2026:
                `applica-eventi` riferiva `applicati: 5` su cinque righe
                rimaste invisibili — attivare un tipo significa renderlo
                **visibile**, non solo scriverne le colonne.
                """
                esito = db.applica_evento_esito(riga.get("id"))
                if esito == ESITO_APPLICATO:
                    visibile = db.rendi_evento_leggibile(
                        riga.get("id"),
                        # Le transizioni automatiche del cron non vanno nel box
                        # (§13.5): quelle non passano da qui, ma la regola
                        # resta scritta dove si decide.
                        in_aggiornamenti=str(riga.get("tipo") or "") not in (
                            "apertura_automatica", "chiusura_automatica"),
                    )
                    if not visibile.get("scritto"):
                        logger.warning(
                            "[applica-eventi] evento {} applicato ma NON reso "
                            "leggibile ({}): il box non lo mostrera'",
                            riga.get("id"), visibile.get("motivo"))
                return esito

            if segnala is None:
                # Chi inietta il proprio `applica` (i test, la pipeline) porta
                # anche la propria annotazione: qui non si scrive per lui.
                segnala = _segnala_rifiuto
            if motivo_scarto is None:
                # Giro 3 (§14): la rilettura di `scartato_per` dopo un `false`.
                motivo_scarto = motivo_scarto_da_db

        gruppi: tuple[str | None, ...] = tuple(tipi) if tipi else (None,)
        candidati_totali = 0
        applicati = 0
        rifiutati = 0
        non_tentati = 0
        segnalati = 0
        rimanenti = blocco_giro
        # Prima della 06 i due stati nuovi non hanno una colonna dove andare:
        # la RPC li respinge, e quel rifiuto non va annotato (vedi
        # `rifiuto_definitivo`). Il flag dell'ambiente da solo non basta: alzato
        # prima della 06 (o lasciato acceso dopo il suo rollback) renderebbe
        # definitivi, e irreversibili, rifiuti che sono solo un'attesa. Vale
        # solo se anche il DB dichiara il CHECK a cinque stati.
        stati_estesi_richiesti = bool(getattr(impostazioni, "monitor_stati_estesi", False))
        stati_estesi = stati_estesi_richiesti and stati_cinque
        if stati_estesi_richiesti and not stati_cinque:
            logger.warning(
                "[applica-eventi] MONITOR_STATI_ESTESI=true ma il DB non dichiara il "
                "CHECK a cinque stati (migrazioni 06 e 11): i rifiuti di sospensione "
                "e revoca non vengono annotati")
        in_attesa_traduzione = conto["in_attesa_traduzione"]
        in_attesa_valore = conto["in_attesa_valore"]
        scartati_per_motivo: dict[str, int] = {}
        per_tipo: dict[str, int] = {}
        for nome in gruppi:
            if rimanenti is not None and rimanenti <= 0:
                break
            esito = applica_eventi(
                candidati, dal=dal, tipo=nome, limit=rimanenti,
                dry_run=not scrive, applica=applica, segnala=segnala,
                stati_estesi=stati_estesi, traduzione=proposti_applicabili,
                motivo_scarto=motivo_scarto,
            )
            candidati_totali += int(esito.get("candidati") or 0)
            applicati += int(esito.get("applicati") or 0)
            rifiutati += int(esito.get("rifiutati") or 0)
            non_tentati += int(esito.get("non_tentati") or 0)
            segnalati += int(esito.get("segnalati") or 0)
            for motivo, quanti in (esito.get("scartati_per_motivo") or {}).items():
                scartati_per_motivo[motivo] = scartati_per_motivo.get(motivo, 0) + int(quanti)
            in_attesa_traduzione += int(esito.get("in_attesa_traduzione") or 0)
            in_attesa_valore += int(esito.get("in_attesa_valore") or 0)
            if rimanenti is not None:
                rimanenti -= int(esito.get("candidati") or 0)
            per_tipo[nome or "tutti"] = int(esito.get("candidati") or 0)

        # Riparazione: gli eventi **applicati e mai resi visibili**. Nascono
        # solo da un'attivazione interrotta a meta' — o dal difetto del
        # 25/09/2026, quando la seconda scrittura non c'era affatto — e la
        # selezione normale non li vede, perche' cerca `applicato=false`:
        # restano invisibili per sempre, applicati alle colonne e assenti dal
        # box. Il recupero e' idempotente e si conta a parte: non e' lavoro
        # nuovo, e' lavoro finito a meta' che si chiude.
        resi_visibili = _rendi_visibili_gli_applicati(
            tipi=tipi, dal=dal, scrive=scrive, limite=blocco_giro, ids=ids)

        riepilogo = {
            "status": "ok",
            "step": STEP_APPLICA,
            "modalita": modalita,
            "dry_run": dry_run,
            "dal": dal.isoformat() if dal else None,
            "tipi": list(tipi),
            "ids": list(ids),
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
            # Giro 3 (§14): eventi marcati dalla RPC della 14 (superato,
            # transizione non ammessa): fuori dalla coda e non annotati.
            "scartati": conto.get("scartati", 0),
            "scartati_per_motivo": dict(sorted(scartati_per_motivo.items())),
            "attraversati": conto["attraversati"],
            "bloccati": conto["bloccati"],
            "saltati": conto["saltati"],
            # Eventi con `stato_proposto` che la RPC senza la migrazione 11
            # brucerebbe, o che senza la 06 respingerebbe: non applicati, non
            # annotati, restano in coda.
            "in_attesa_traduzione": in_attesa_traduzione,
            # Eventi con la data in `{"valore": …}`: la RPC la perderebbe.
            "in_attesa_valore": in_attesa_valore,
            "traduzione_stato_proposto": traduzione,
            "stati_estesi": stati_estesi,
            "per_tipo": per_tipo,
            # Eventi applicati in un giro precedente che non erano mai diventati
            # visibili: se questo numero non e' zero, un'attivazione era rimasta
            # a meta' e adesso e' chiusa.
            "resi_visibili": resi_visibili,
            "saltato_per_lock": False,
            "interrotto_per_tetto": False,
            "durata_s": round(time.monotonic() - avvio, 1),
        }
        if in_attesa_traduzione:
            logger.warning(
                "[applica-eventi] {} eventi con stato_proposto in attesa delle "
                "migrazioni 11 e 06: non applicati, non annotati", in_attesa_traduzione)
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
    "CAMPIONE_MINIMO",
    "COLONNE_RIFIUTO", "FALLIMENTI_MODELLO_DI_FILA", "INTESTAZIONI_REPORT", "MOTIVO_RIFIUTO",
    "TIPI_CON_DATA_IN_COLONNA", "TRADUZIONI_STATO_PROPOSTO",
    "PAGINA_SELEZIONE_EVENTI", "SOGLIA_PRECISIONE", "STEP_APPLICA",
    "applicabile", "attende_traduzione", "eventi_gia_rifiutati", "valore_non_applicabile", "precisione", "report_ombra_da_eventi",
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
