# -*- coding: utf-8 -*-
"""Segnali gratuiti dal re-scrape (piano §6.1). Modulo **puro**.

Perche' esiste
--------------
Ogni giro lo scrape rilegge l'intero listing di ogni fonte e riscrive in `bando`
tutto cio' che ha letto. Due conseguenze misurate e costose:

1. **riscritture identiche**: su Obiettivo Europa ~1 419 righe per giro
   cambiano soltanto perche' l'API emette `deadline_days_left`, che scala di 1
   ogni notte. Sono UPDATE veri (con trigger, indici e `updated_at` che
   avanza) in cambio di zero informazione;
2. **informazione buttata**: quando `deadline_label` o `status` cambiano
   davvero, quel cambiamento e' la cosa piu' economica che il sistema possa
   sapere — e' gia' in RAM, non costa ne' un credito ne' un token — e oggi
   finisce sovrascritto senza che nessuno lo guardi.

Questo modulo confronta il listing appena letto con cio' che c'e' in tabella e
produce due cose: l'elenco dei record **davvero** cambiati (quelli da mandare
all'upsert) e gli eventi interni `segnale_fonte` con una **priorita'**, che il
monitor usa per decidere chi ricontrollare per primo.

Regola non negoziabile (§6.1, §4)
---------------------------------
**Nessuna data e nessuno stato vengono scritti da qui.** Un diff di listing non
e' una prova: nessuna transizione della macchina a stati puo' nascere da un
segnale. I segnali alzano solo la priorita' di un controllo, che poi dovra'
superare i gate G1-G9 di `eventi.py`. Vale anche per i preavvisi di §14.

Il modulo e' puro: niente rete, niente DB, niente orologio implicito (l'istante
si passa). Gli unici import interni sono `gemelli` (per la famiglia della
fonte), `date_validation` (unico parser di date del progetto) e `stato_bando`
(unica definizione di «oggi» e di stato effettivo).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date as date_cls, datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

from .date_validation import estrai_date_con_ruolo
from .gemelli import (
    FAMIGLIA_CALENDARIO,
    FAMIGLIA_INCENTIVI,
    FAMIGLIA_ITALIA_DOMANI,
    FAMIGLIA_OE,
    famiglia,
)
from .stato_bando import adesso_roma, stato_effettivo

# --- tipi di evento (sempre interni: §13.5) ---------------------------------

TIPO_SEGNALE = "segnale_fonte"
TIPO_SPARITO = "sparito_dalla_fonte"

# --- priorita' di §6.1 ------------------------------------------------------

PRIORITA_ALTA = 90      # stato o scadenza cambiati: e' il segnale che conta
PRIORITA_SPARITO = 80   # la riga non compare piu' nel listing
PRIORITA_MEDIA = 60     # la fonte dichiara «ho toccato questa scheda»
PRIORITA_BASSA = 40     # dotazione o data di pubblicazione

# Chiave del listing -> priorita' del segnale che il suo cambiamento genera.
# I nomi sono quelli che gli adapter scrivono in `raw_data`, piu' `tipo_link`
# che e' una colonna di `bando` ricalcolata da `on_arrival`.
PRIORITA_CHIAVE: dict[str, int] = {
    # 90
    "deadline_label": PRIORITA_ALTA,
    "close_date": PRIORITA_ALTA,
    "data_chiusura": PRIORITA_ALTA,
    "status": PRIORITA_ALTA,
    "stato": PRIORITA_ALTA,
    "tipo_link": PRIORITA_ALTA,
    # 60
    "modified": PRIORITA_MEDIA,
    "ds_last_update": PRIORITA_MEDIA,
    "updates_active": PRIORITA_MEDIA,
    # 40
    "budget": PRIORITA_BASSA,
    "published": PRIORITA_BASSA,
}

# Le chiavi che, cambiando su una riga di Obiettivo Europa, giustificano di
# ri-scaricare la scheda OE (§6.2, «solo-OE»): e' l'unico modo di sapere di piu'
# su un bando la cui fonte ufficiale non e' ancora stata trovata.
CHIAVI_SCHEDA_OE: frozenset[str] = frozenset({"status", "deadline_label", "tipo_link", "on_arrival"})

# Priorita' di una chiave non elencata: e' un cambiamento reale, ma di cui non
# sappiamo l'importanza. Si registra con la priorita' piu' bassa invece di
# inventargliene una alta.
PRIORITA_PREDEFINITA = PRIORITA_BASSA


# --- chiavi confrontate, per famiglia di fonte (§6.1) -----------------------

# Obiettivo Europa: `status` e' un intero 1/2 (NON un flag aperto/chiuso) e
# `tipo_link` si ricalcola da `on_arrival` — sono la stessa informazione vista
# da due lati, e vanno confrontate entrambe perche' `tipo_link` e' una colonna
# di `bando` mentre `on_arrival` sta in `raw_data`.
CHIAVI_OE: tuple[str, ...] = (
    "status", "deadline_label", "on_arrival", "published", "budget",
    "modified", "updates_active", "tipo_link",
)

# Volatili di OE: cambiano da soli ogni notte e non dicono niente.
# `deadline_days_left` da solo spiega ~1 419 riscritture per giro.
VOLATILI_OE: frozenset[str] = frozenset({
    "deadline_days_left", "is_recent", "like", "visited", "is_copiloted",
})

CHIAVI_INCENTIVI: tuple[str, ...] = (
    "open_date", "close_date", "external_link", "budget_allocation", "ds_last_update",
)

CHIAVI_ITALIA_DOMANI: tuple[str, ...] = (
    "stato", "data_apertura", "data_chiusura", "amministrazione_titolare",
)

# httpx_bs4 / firecrawl_scrape: dal listing esce solo il link e l'ancora.
CHIAVI_HTML: tuple[str, ...] = ("titolo_raw", "link_bando")

# Calendari (csv/hybrid/pdf): si confronta **tutto** il `raw_data` tranne i
# campi posizionali, che dipendono da come il file e' stato impaginato e non
# dal bando. `source_url` NON e' posizionale: un `source_url` diverso significa
# che l'ente ha pubblicato un file nuovo del calendario, ed e' un segnale.
POSIZIONALI_CALENDARIO: frozenset[str] = frozenset({"row_index", "page", "riga", "pagina"})

# Chiavi che non sono mai un segnale: le scrive il nostro codice, non la fonte.
CHIAVI_INTERNE: frozenset[str] = frozenset({"source", "hash_senza_link"})

CHIAVI_PER_FAMIGLIA: dict[str, tuple[str, ...]] = {
    FAMIGLIA_OE: CHIAVI_OE,
    FAMIGLIA_INCENTIVI: CHIAVI_INCENTIVI,
    FAMIGLIA_ITALIA_DOMANI: CHIAVI_ITALIA_DOMANI,
}

VOLATILI_PER_FAMIGLIA: dict[str, frozenset[str]] = {
    FAMIGLIA_OE: VOLATILI_OE,
}

# Colonne di `bando` (fuori da `raw_data`) che entrano nel confronto: sono le
# sole che il listing scrive davvero.
COLONNE_CONFRONTATE: tuple[str, ...] = ("tipo_link", "titolo_raw", "link_bando")


def chiavi_confrontate(genere: str) -> tuple[str, ...] | None:
    """Chiavi da confrontare per quella famiglia, o None = «tutte tranne le
    volatili» (e' il caso dei calendari e delle fonti HTML miste)."""
    return CHIAVI_PER_FAMIGLIA.get(genere)


def volatili(genere: str) -> frozenset[str]:
    """Chiavi escluse dal confronto per quella famiglia."""
    escluse = VOLATILI_PER_FAMIGLIA.get(genere, frozenset())
    if genere in (FAMIGLIA_CALENDARIO, ""):
        return escluse | POSIZIONALI_CALENDARIO | CHIAVI_INTERNE
    return escluse | CHIAVI_INTERNE


def estratto(record: Mapping[str, Any], genere: str | None = None) -> dict[str, Any]:
    """Le sole chiavi confrontabili del record, in forma normalizzata.

    Il record e' quello che `bando_runner._build_record` manda all'upsert:
    colonne di `bando` in cima e `raw_data` annidato. L'estratto le appiattisce
    in un solo dizionario, cosi' `tipo_link` (colonna) e `on_arrival`
    (`raw_data`) si confrontano allo stesso modo.
    """
    if genere is None:
        genere = famiglia(record)
    grezzo = record.get("raw_data") or {}
    if not isinstance(grezzo, Mapping):
        grezzo = {}

    ammesse = chiavi_confrontate(genere)
    escluse = volatili(genere)

    piatto: dict[str, Any] = {}
    for nome in COLONNE_CONFRONTATE:
        if nome in record:
            piatto[nome] = record.get(nome)
    for nome, valore in grezzo.items():
        piatto.setdefault(str(nome), valore)

    if ammesse is not None:
        # Famiglia nota: si guarda solo l'elenco di §6.1. Una chiave nuova
        # dell'API non deve diventare un segnale finche' qualcuno non ha deciso
        # che cosa significa.
        return {k: _normalizza(piatto.get(k)) for k in ammesse if k in piatto}
    return {k: _normalizza(v) for k, v in piatto.items() if k not in escluse}


def _normalizza(valore: Any) -> Any:
    """Forma canonica di un valore del listing.

    Stringhe: spazi ai bordi via; `""` diventa None, cosi' «campo assente» e
    «campo vuoto» non generano un segnale l'uno contro l'altro (gli adapter
    tolgono le stringhe vuote da `raw_data`, il DB le puo' aver conservate).
    Liste e dizionari: ricorsione, cosi' l'impronta non dipende dall'ordine
    delle chiavi di un dizionario annidato.
    """
    if isinstance(valore, str):
        pulito = valore.strip()
        return pulito or None
    if isinstance(valore, Mapping):
        return {str(k): _normalizza(v) for k, v in sorted(valore.items(), key=lambda kv: str(kv[0]))}
    if isinstance(valore, (list, tuple)):
        return [_normalizza(v) for v in valore]
    if isinstance(valore, (date_cls, datetime)):
        return valore.isoformat()
    return valore


def impronta_raw(record: Mapping[str, Any], genere: str | None = None) -> str:
    """sha256 del JSON canonico dell'estratto (§6.1).

    Canonico = chiavi ordinate, nessuno spazio, `ensure_ascii=False`: due
    letture della stessa riga danno la stessa impronta anche se l'API ha
    cambiato l'ordine dei campi o il DB ha riscritto il JSONB.
    """
    dati = estratto(record, genere)
    canonico = json.dumps(dati, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                          default=str)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


# --- esito dello scraper (copertura, §6.1) ----------------------------------

@dataclass(frozen=True)
class EsitoFonte:
    """`scraper.ultimo_esito`: quanto della fonte abbiamo davvero visto.

    Tre campi soli, perche' tre bastano a decidere e piu' campi sarebbero tre
    modi diversi di sbagliarsi:
      * `pagine`   — pagine effettivamente lette;
      * `troncato` — vero se la lettura si e' fermata prima della fine (tetto
        `max_pages`, early-stop sui duplicati, errore HTTP, pagina saltata);
      * `count`    — totale **dichiarato dalla fonte** (`numFound` di Solr,
        `count` di OE); 0 = la fonte non lo dichiara.
    """
    pagine: int = 0
    troncato: bool = True
    count: int = 0

    def come_dizionario(self) -> dict[str, Any]:
        return {"pagine": self.pagine, "troncato": self.troncato, "count": self.count}


def esito_da(valore: Any) -> EsitoFonte | None:
    """`EsitoFonte` da un dizionario, da un oggetto con gli attributi, o None.

    None significa «lo scraper non lo dichiara»: senza dichiarazione la
    copertura non e' piena e nessun «sparito dalla fonte» viene emesso.
    """
    if valore is None:
        return None
    if isinstance(valore, EsitoFonte):
        return valore
    if isinstance(valore, Mapping):
        letti = valore
    else:
        letti = {
            "pagine": getattr(valore, "pagine", None),
            "troncato": getattr(valore, "troncato", None),
            "count": getattr(valore, "count", None),
        }
    try:
        pagine = int(letti.get("pagine") or 0)
    except (TypeError, ValueError):
        pagine = 0
    try:
        count = int(letti.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    # Assente = troncato: nel dubbio si suppone di non aver visto tutto.
    troncato = bool(letti.get("troncato", True))
    return EsitoFonte(pagine=pagine, troncato=troncato, count=count)


def copertura_piena(esito: Any, elementi: int) -> bool:
    """La fonte e' stata letta per intero? (§6.1)

    Le regole di §6.1 sono per-fonte («OE `pagine×50 >= count`», «incentivi
    `counter >= numFound`», «html `pagine < max_pages`», «httpx_bs4 tutte le
    pagine riuscite») ma dicono tutte la stessa cosa in tre modi: *la lettura
    non si e' fermata prima della fine, e abbiamo in mano almeno tutti gli
    elementi che la fonte dichiara*. Concentrare la regola qui, e lasciare a
    ogni scraper il compito di alzare `troncato`, evita di avere quattro
    definizioni di «completo» che divergono al primo cambio di paginazione.

    Nel dubbio la risposta e' **False**: senza copertura piena non si emette
    nessun «sparito dalla fonte», e nessuna riga viva viene sospettata per un
    guasto nostro.
    """
    letto = esito_da(esito)
    if letto is None or letto.troncato:
        return False
    if letto.count > 0 and elementi < letto.count:
        return False
    return True


# --- segnali ----------------------------------------------------------------

@dataclass(frozen=True)
class Segnale:
    """Un evento interno prodotto dal confronto. Mai leggibile, mai un cursore."""
    tipo: str
    hash_bando: str | None = None
    bando_id: int | None = None
    fonte_id: int | None = None
    priorita: int = PRIORITA_BASSA
    campi: tuple[str, ...] = ()
    valore_prima: dict[str, Any] = field(default_factory=dict)
    valore_dopo: dict[str, Any] = field(default_factory=dict)
    oe_scheda_da_riscaricare: bool = False
    motivo: str = ""

    def come_riga(self) -> dict[str, Any]:
        """Payload per `bando_evento`. `cursore` non compare: §13.5 vieta che
        un tipo interno ne riceva uno, e ometterlo qui e' la prima difesa."""
        return {
            "bando_id": self.bando_id,
            "tipo": self.tipo,
            "origine": "worker",
            "campo": ",".join(self.campi) or None,
            "valore_prima": dict(self.valore_prima),
            "valore_dopo": dict(self.valore_dopo),
            "leggibile": False,
            "in_aggiornamenti": False,
            "applicato": False,
            "verificato": False,
        }


@dataclass(frozen=True)
class Confronto:
    """Esito di `confronta`. E' tutto cio' che il runner deve sapere."""
    cambiati: tuple[dict[str, Any], ...] = ()
    nuovi: tuple[dict[str, Any], ...] = ()
    identici: int = 0
    segnali: tuple[Segnale, ...] = ()
    spariti: tuple[Segnale, ...] = ()
    visti: tuple[str, ...] = ()
    copertura_piena: bool = False

    @property
    def da_scrivere(self) -> tuple[dict[str, Any], ...]:
        """I soli record che vale la pena mandare a `upsert_bandi`."""
        return self.nuovi + self.cambiati

    @property
    def priorita(self) -> dict[str, int]:
        """hash_bando -> priorita' massima fra i suoi segnali."""
        massime: dict[str, int] = {}
        for segnale in self.segnali + self.spariti:
            chiave = segnale.hash_bando
            if not chiave:
                continue
            if segnale.priorita > massime.get(chiave, -1):
                massime[chiave] = segnale.priorita
        return massime

    @property
    def schede_oe_da_riscaricare(self) -> tuple[str, ...]:
        """Senza duplicati: due segnali sulla stessa riga (chiave cambiata e
        mismatch dell'etichetta) restano una sola scheda da ri-scaricare, e
        ogni scheda OE in piu' e' un fetch in piu' contro il tetto del giro."""
        visti: list[str] = []
        for segnale in self.segnali:
            if segnale.oe_scheda_da_riscaricare and segnale.hash_bando not in visti:
                if segnale.hash_bando:
                    visti.append(segnale.hash_bando)
        return tuple(visti)

    def come_contatori(self) -> dict[str, int]:
        return {
            "nuovi": len(self.nuovi),
            "cambiati": len(self.cambiati),
            "identici": self.identici,
            "segnalati": len(self.segnali),
            "spariti": len(self.spariti),
        }


def differenze(prima: Mapping[str, Any], dopo: Mapping[str, Any]) -> tuple[str, ...]:
    """Chiavi con valore diverso fra due estratti, in ordine alfabetico.

    Una chiave presente solo in uno dei due conta come differenza **solo** se il
    valore dell'altro non e' None: gli adapter tolgono i vuoti da `raw_data`,
    quindi «chiave assente» e «chiave a None» sono lo stesso fatto.
    """
    nomi = set(prima) | set(dopo)
    return tuple(sorted(n for n in nomi if prima.get(n) != dopo.get(n)))


def priorita_di(campi: Iterable[str]) -> int:
    """Priorita' del segnale: la piu' alta fra quelle dei campi cambiati."""
    valori = [PRIORITA_CHIAVE.get(c, PRIORITA_PREDEFINITA) for c in campi]
    return max(valori) if valori else PRIORITA_PREDEFINITA


def scadenza_da_label(etichetta: Any) -> date_cls | None:
    """La data dentro un `deadline_label` di OE («Scade il 30/09/2026»).

    Si usa l'unico parser di date del progetto: una regex propria qui sarebbe
    la seconda definizione di «data» e divergerebbe al primo caso strano.
    Si accetta solo una data di ruolo scadenza o ignoto, e solo se ce n'e' una
    sola: due date in un'etichetta non sono una scadenza, sono una frase.
    """
    if not isinstance(etichetta, str) or not etichetta.strip():
        return None
    trovate = [d for d in estrai_date_con_ruolo(etichetta) if d.ruolo in ("scadenza", "ignoto")]
    if len(trovate) != 1:
        return None
    return trovate[0].data


def _data_colonna(valore: Any) -> date_cls | None:
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


def mismatch_scadenza_oe(
    record: Mapping[str, Any], riga: Mapping[str, Any] | None,
) -> tuple[date_cls, date_cls] | None:
    """(scadenza in colonna, scadenza nell'etichetta) se non coincidono.

    E' il controllo piu' economico del piano: copre 1 419 righe su 1 702 senza
    una richiesta di rete, e il suo accordo misurato e' il 95,5 %. Un mismatch
    **non** scrive niente: alza la priorita' a 90 e basta, perche' l'etichetta
    di un aggregatore non e' una prova (§4: solo il monitor con G1-G9 scrive).
    """
    if not riga:
        return None
    grezzo = record.get("raw_data") or {}
    etichetta = grezzo.get("deadline_label") if isinstance(grezzo, Mapping) else None
    dalla_label = scadenza_da_label(etichetta)
    if dalla_label is None:
        return None
    in_colonna = _data_colonna(riga.get("data_scadenza"))
    if in_colonna is None or in_colonna == dalla_label:
        return None
    return (in_colonna, dalla_label)


def confronta(
    fonte: Mapping[str, Any] | None,
    records: Sequence[Mapping[str, Any]],
    esistenti: Mapping[str, Mapping[str, Any]],
    *,
    esito: Any = None,
    elementi_giro_precedente: int | None = None,
    adesso: datetime | None = None,
    ore_per_giro: float = 6.0,
    giri_assenza: int = 3,
) -> Confronto:
    """Confronta il listing appena letto con le righe gia' in tabella.

    `records` sono i record composti da `bando_runner._build_record`;
    `esistenti` e' `hash_bando -> riga di bando` (colonne utili: `id`,
    `raw_data`, `tipo_link`, `titolo_raw`, `link_bando`, `data_scadenza`,
    `stato_bando`, `pubblicato`, `ultimo_visto_in_fonte_at`).

    Ritorna i record da scrivere, i segnali e gli eventuali «spariti». Non
    scrive niente e non solleva mai: un confronto che fallisce non deve poter
    fermare lo scrape.
    """
    genere = ""
    if records:
        genere = famiglia(records[0], fonte)
    elif fonte:
        genere = famiglia({}, fonte)

    nuovi: list[dict[str, Any]] = []
    cambiati: list[dict[str, Any]] = []
    segnali: list[Segnale] = []
    identici = 0
    visti: list[str] = []
    fonte_id = (fonte or {}).get("id")

    for record in records:
        chiave = str(record.get("hash_bando") or "")
        if not chiave:
            # Senza hash il record non e' indirizzabile: lo si manda comunque
            # all'upsert, che lo scartera' con il suo log.
            nuovi.append(dict(record))
            continue
        visti.append(chiave)
        riga = esistenti.get(chiave)
        if riga is None:
            nuovi.append(dict(record))
            continue

        prima = estratto(riga, genere)
        dopo = estratto(record, genere)
        campi = differenze(prima, dopo)

        mismatch = mismatch_scadenza_oe(record, riga) if genere == FAMIGLIA_OE else None

        if not campi and mismatch is None:
            identici += 1
            continue

        if campi:
            cambiati.append(dict(record))
            segnali.append(Segnale(
                tipo=TIPO_SEGNALE,
                hash_bando=chiave,
                bando_id=_intero(riga.get("id")),
                fonte_id=_intero(fonte_id),
                priorita=priorita_di(campi),
                campi=campi,
                valore_prima={c: prima.get(c) for c in campi},
                valore_dopo={c: dopo.get(c) for c in campi},
                oe_scheda_da_riscaricare=(
                    genere == FAMIGLIA_OE and bool(set(campi) & CHIAVI_SCHEDA_OE)
                ),
                motivo="chiavi cambiate nel listing",
            ))

        if mismatch is not None:
            in_colonna, dalla_label = mismatch
            segnali.append(Segnale(
                tipo=TIPO_SEGNALE,
                hash_bando=chiave,
                bando_id=_intero(riga.get("id")),
                fonte_id=_intero(fonte_id),
                priorita=PRIORITA_ALTA,
                campi=("deadline_label",),
                valore_prima={"data_scadenza": in_colonna.isoformat()},
                valore_dopo={"deadline_label": dalla_label.isoformat()},
                oe_scheda_da_riscaricare=True,
                motivo="deadline_label discorde da data_scadenza",
            ))

    piena = copertura_piena(esito, len(records))
    # §6.1: la fonte non deve essersi dimezzata. Un listing che cala oltre la
    # meta' e' un guasto della fonte (o nostro), non 800 bandi spariti.
    if (
        elementi_giro_precedente is not None
        and elementi_giro_precedente > 0
        and len(records) < 0.5 * elementi_giro_precedente
    ):
        piena = False

    spariti_ = (
        spariti(
            esistenti, visti,
            fonte_id=_intero(fonte_id),
            adesso=adesso,
            ore_per_giro=ore_per_giro,
            giri_assenza=giri_assenza,
        )
        if piena else ()
    )

    return Confronto(
        cambiati=tuple(cambiati),
        nuovi=tuple(nuovi),
        identici=identici,
        segnali=tuple(segnali),
        spariti=spariti_,
        visti=tuple(visti),
        copertura_piena=piena,
    )


def spariti(
    esistenti: Mapping[str, Mapping[str, Any]],
    visti: Iterable[str],
    *,
    fonte_id: int | None = None,
    adesso: datetime | None = None,
    ore_per_giro: float = 6.0,
    giri_assenza: int = 3,
) -> tuple[Segnale, ...]:
    """Righe pubblicate e vive che non compaiono piu' nel listing (§6.1).

    Quattro condizioni, tutte necessarie, e la quarta e' quella che evita 545
    falsi positivi noti:
      1. la riga e' **pubblicata** (una riga in lavorazione non interessa);
      2. il suo stato effettivo e' vivo: un `chiuso` o un `revocato` fuori
         listing e' la normalita', non una sparizione (su OE sono 545 righe);
      3. non l'abbiamo vista in **questo** giro;
      4. non la vediamo da piu' di `giri_assenza` giri: una fonte che nasconde
         una pagina per qualche ora non deve produrre un evento.

    Chi non ha mai avuto un `ultimo_visto_in_fonte_at` non genera evento: senza
    un «prima» non c'e' nessuna sparizione da dichiarare, solo una colonna che
    non e' ancora stata seminata.
    """
    momento = adesso_roma(adesso)
    soglia = momento - timedelta(hours=max(0.0, ore_per_giro) * max(1, giri_assenza))
    gia_visti = set(visti)

    trovati: list[Segnale] = []
    for chiave, riga in esistenti.items():
        if chiave in gia_visti:
            continue
        if not _pubblicata(riga):
            continue
        if not _viva(riga, momento):
            continue
        ultimo = _istante(riga.get("ultimo_visto_in_fonte_at"))
        if ultimo is None or ultimo >= soglia:
            continue
        trovati.append(Segnale(
            tipo=TIPO_SPARITO,
            hash_bando=chiave,
            bando_id=_intero(riga.get("id")),
            fonte_id=fonte_id if fonte_id is not None else _intero(riga.get("fonte_id")),
            priorita=PRIORITA_SPARITO,
            campi=("ultimo_visto_in_fonte_at",),
            valore_prima={"ultimo_visto_in_fonte_at": ultimo.isoformat()},
            valore_dopo={},
            motivo=f"assente dal listing da oltre {giri_assenza} giri",
        ))
    return tuple(trovati)


def _pubblicata(riga: Mapping[str, Any]) -> bool:
    """Pubblicata secondo la colonna nuova, o secondo il criterio storico.

    `pubblicato` arriva con la migrazione 01: finche' non c'e', il criterio e'
    quello che la RLS usa oggi (`completed` con slug).
    """
    if "pubblicato" in riga:
        return bool(riga.get("pubblicato"))
    return riga.get("stato_processing") == "completed" and bool(riga.get("slug"))


def _viva(riga: Mapping[str, Any], adesso: datetime) -> bool:
    effettivo = stato_effettivo(
        riga.get("stato_bando"),
        data_apertura=riga.get("data_apertura"),
        apertura_verificata=riga.get("data_apertura_verificata"),
        ora_apertura=riga.get("ora_apertura"),
        data_scadenza=riga.get("data_scadenza"),
        ora_scadenza=riga.get("ora_scadenza"),
        adesso=adesso,
    )
    return effettivo not in ("chiuso", "revocato")


def _istante(valore: Any) -> datetime | None:
    if isinstance(valore, datetime):
        return adesso_roma(valore)
    if isinstance(valore, str) and valore.strip():
        testo = valore.strip().replace("Z", "+00:00")
        try:
            return adesso_roma(datetime.fromisoformat(testo))
        except ValueError:
            return None
    return None


def _intero(valore: Any) -> int | None:
    try:
        return int(valore)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


__all__ = [
    "CHIAVI_HTML", "CHIAVI_INCENTIVI", "CHIAVI_ITALIA_DOMANI", "CHIAVI_OE",
    "CHIAVI_SCHEDA_OE", "COLONNE_CONFRONTATE", "Confronto", "EsitoFonte",
    "PRIORITA_ALTA", "PRIORITA_BASSA", "PRIORITA_CHIAVE", "PRIORITA_MEDIA",
    "PRIORITA_SPARITO", "POSIZIONALI_CALENDARIO", "Segnale", "TIPO_SEGNALE",
    "TIPO_SPARITO", "VOLATILI_OE", "chiavi_confrontate", "confronta",
    "copertura_piena", "differenze", "esito_da", "estratto", "impronta_raw",
    "mismatch_scadenza_oe", "priorita_di", "scadenza_da_label", "spariti",
    "volatili",
]
