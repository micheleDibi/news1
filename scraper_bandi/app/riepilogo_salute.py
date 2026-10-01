"""Riepilogo neutro v1 della salute, per il pannello di BandoFit (contratto `bandi-giro-2` §9).

`sorveglia` fotografa la salute del produttore e la scrive nella riga unica di
`monitoraggio_riepilogo`; il pannello la legge con `monitoraggio_catalogo`, che
copia solo le 11 chiavi di primo livello di `SCHEMA_V1`. Quello che esce da qui
lo legge un'altra applicazione, quindi:

* le stringhe vengono SOLO da un enum, da un istante ISO 8601 UTC o da
  `TESTI_NEUTRI`: mai un testo della CLI, un'eccezione, un motivo o una nota di
  `pipeline_run`, un host, un URL, un proprietario di lock (col PID), un titolo;
* niente consumo: i segnali di spesa restano codici senza misura (decisione
  del 30/09 sera), e nessun dollaro o credito esce;
* `valida_v1` controlla tutto prima della scrittura; se fallisce, `sorveglia`
  scrive `riepilogo_minimo` e il dettaglio va solo nel journal.

Modulo puro, sola stdlib: non importa nulla del progetto. Le poche costanti
che ricopia da `telemetria` (soglie dei lock, ore dei giri, testi dei non
misurati) sono confrontate con gli originali nei test.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

VERSIONE = 1

# --- schema v1 (§9.1) -------------------------------------------------------

#: Le 11 chiavi di primo livello, nell'ordine della busta della 12 (senza
#: `consumo`). Un test le confronta con quelle estratte dal SQL.
CHIAVI_V1: tuple[str, ...] = (
    "stato", "segnali", "non_misurati", "produttore", "giri", "controlli",
    "lavorazioni", "ingresso", "eventi", "da_verificare", "job_orario",
)
STATI = ("ok", "attenzione", "guasto")
LIVELLI = ("allarme", "avviso")
NON_MISURATI_V1: tuple[str, ...] = (
    "servizio", "job_orario", "accesso_fonte_riservata", "credito_ricerca",
    "schede_con_sezione", "da_verificare",
)
SERVIZIO_V1 = ("attivo", "non_attivo", "non_misurato")
GIRI_V1 = ("00", "06", "12", "18", "avvio", "manuale")
#: Gli esiti di `telemetria.esito_da_contatori`.
ESITI_V1 = ("ok", "errore", "saltato", "interrotto_per_tetto")
LAVORAZIONI_V1 = ("giro", "controllo_pagine", "ricerca_fonti", "altro")
STATI_LAVORAZIONE_V1 = ("regolare", "lunga", "probabile_orfana")
ESITI_JOB_V1 = ("succeeded", "failed", "non_misurato")

MAX_SEGNALI = 40
MAX_GIRI = 20
MAX_CONTROLLI = 10
MAX_LAVORAZIONI = 10

#: La forma di ogni chiave: le sottochiavi dei dizionari, e per le liste le
#: chiavi di ogni elemento e la lunghezza massima.
SCHEMA_V1: dict[str, Any] = {
    "versione": VERSIONE,
    "calcolato_at": "iso_utc",
    "stato": STATI,
    "segnali": {"max": MAX_SEGNALI, "voce": ("codice", "livello", "testo", "dal", "misura")},
    "non_misurati": NON_MISURATI_V1,
    "produttore": ("ultimo_giro_at", "ore_dall_ultimo_giro", "giri_24h", "riavvii_24h", "servizio"),
    "giri": {"max": MAX_GIRI, "voce": ("id", "giro", "avviato_at", "concluso_at", "durata_min",
                                       "esito", "interrotto_per_tetto", "passi_non_ok")},
    "controlli": {"max": MAX_CONTROLLI, "voce": ("avviato_at", "esito", "classificazioni",
                                                 "classificazioni_fallite", "eventi_non_applicati")},
    "lavorazioni": {"max": MAX_LAVORAZIONI, "voce": ("nome", "da_min", "ttl_min", "stato")},
    "ingresso": ("fermi_in_ingresso", "fermi_in_lavorazione", "ultimo_bando_nuovo_at"),
    "eventi": ("ammessi_non_applicati", "proposte_7g", "in_attesa_pubblicazione"),
    # null prima della 13 (percorso A).
    "da_verificare": ("in_apertura", "aperto", "proposte_in_ombra_per_tipo", "chiusure_applicate_7g",
                      "host_frenati", "pagine_rimosse", "forse_non_bandi"),
    "job_orario": ("ultimo_avvio_at", "ultimo_esito", "ultimo_ok_at", "falliti_24h"),
}
#: I motivi di `stato_da_verificare` (`stato_bando.MOTIVI_DA_VERIFICARE`) e i
#: tipi delle proposte del passo (`eventi.TIPI_VERIFICA`): copiati, un test li
#: confronta. Fuori elenco non escono.
MOTIVI_DA_VERIFICARE_V1: tuple[str, ...] = (
    "data_apertura_passata", "smentito_dalla_fonte", "previsione_scaduta",
    "senza_conferma", "termine_passato",
)
TIPI_PROPOSTA_V1: tuple[str, ...] = ("chiusura", "rettifica", "data_verificata", "apertura")

# --- testi e misure (§9.2) --------------------------------------------------

#: Una frase fissa per codice (senza suffisso), con i soli segnaposti {n},
#: {quota}, {ore}, {minuti}. Le chiavi coincidono con `telemetria.PREFISSI_SALUTE`.
#: Un codice che puo' arrivare senza misura ha una frase senza segnaposti.
TESTI_NEUTRI: dict[str, str] = {
    "monitor_fermo": "Il controllo delle pagine non si conclude da {ore} ore.",
    "misure_non_disponibili": "Le misure sul database non sono disponibili.",
    "ingresso_fermo": "{n} bandi sono fermi all'ingresso da più di mezza giornata.",
    "classificazione_non_disponibile":
        "La classificazione non è riuscita per {n} pagine nell'ultimo controllo.",
    "accesso_fonte_riservata": "Una fonte ad accesso riservato non si riesce a leggere.",
    "limite_di_spesa": "Un limite di spesa ha fermato più giri di fila.",
    "credito_ricerca_basso": "Il credito del servizio di lettura delle pagine è basso.",
    "consumo_mensile_alto": "Il consumo del mese è vicino al limite.",
    "fonti_da_verificare": "Fra i bandi nuovi, la quota con la fonte ufficiale da verificare è {quota}.",
    "schede_senza_sezione": "La quota di schede con la sezione dei documenti è {quota}.",
    "controlli_non_riusciti": "La quota di bandi con controlli falliti ripetuti è {quota}.",
    "scorta_piano_bassa": "La scorta del piano di lettura delle pagine è bassa.",
    "modello_fuori_listino": "Un modello in uso non ha un prezzo a listino.",
    "non_misurato": "Alcune misure non sono disponibili.",
    "produttore_fermo": "Nessun giro completato da {ore} ore.",
    "riavvii_ripetuti": "Il servizio si è riavviato {n} volte in poche ore.",
    "servizio_non_attivo": "Il servizio che esegue i giri non è attivo.",
    "fermi_in_lavorazione": "{n} bandi sono fermi in lavorazione da più di mezza giornata.",
    "ingresso_guasto": "Nell'ultimo giro nessuna fonte è stata letta: {n} fonti in errore.",
    "eventi_non_applicati": "{n} eventi ammessi non sono stati applicati nell'ultimo controllo.",
    "eventi_non_scritti": "{n} eventi non sono stati scritti nell'ultimo controllo.",
    "eventi_non_leggibili": "{n} eventi applicati non sono ancora visibili negli aggiornamenti.",
    "passi_ripetuti_non_ok": "{n} passi del giro non sono riusciti due volte di fila.",
    "job_orario": "Il job orario delle transizioni non ha esiti riusciti recenti o fallisce spesso.",
    "riepilogo_non_valido": "Il riepilogo non ha superato la validazione.",
    "lavorazione_lunga": "Una lavorazione è in corso da {minuti} minuti.",
    "lavorazione_orfana": "Una lavorazione risulta ferma da {minuti} minuti: probabilmente è orfana.",
    "configurazione": "Una variabile di configurazione ha un valore non valido.",
    "passo_degradato": "Un passo del giro non ha prodotto risultati: {n} elementi in errore.",
    # percorso A (§8 A e §19.6)
    "verifica_stato_ferma": "La verifica dello stato dei bandi non si conclude da oltre un giorno.",
    "leggibile_non_letto": "{n} bandi con una pagina leggibile non sono stati riletti da oltre due settimane.",
    "lettura_non_verificante": "{n} letture sono avvenute su pagine di domini non verificati.",
    "estrattore_muto": "Un lettore di pagine ha letto {n} pagine senza alcun esito in una settimana.",
    "freno_chiusure": "{n} chiusure sono trattenute dal freno di un lettore di pagine.",
    "prosa_non_riscritta": "{n} schede hanno date aggiornate e testo non ancora riscritto.",
    "aperti_senza_conferma": "La quota di bandi aperti senza conferma dalla fonte è {quota}.",
    "ingresso_trattenuti": "Molti bandi nuovi restano in attesa prima della pubblicazione.",
    "indicepa_non_aggiornato": "L'elenco ufficiale degli enti non è stato aggiornato di recente.",
    "indicepa_import_anomalo": "L'ultimo aggiornamento dell'elenco degli enti è anomalo.",
    "vista_lenta": "La lettura pubblica dei bandi è lenta.",
}
#: Il testo generico: per un codice senza frase (un prefisso nuovo arrivato
#: prima del suo testo) e per una frase con segnaposto arrivata senza misura.
#: Un codice non sparisce mai dal riepilogo per mancanza di testo.
#: Le frasi che cambiano col livello: lo stesso codice, due situazioni diverse.
#: `verifica_stato_ferma` come avviso vuol dire «nessuna riga del passo».
TESTI_NEUTRI_PER_LIVELLO: dict[tuple[str, str], str] = {
    ("verifica_stato_ferma", "avviso"): "La verifica dello stato dei bandi non è ancora stata eseguita.",
}
TESTO_SENZA_MISURA: dict[str, str] = {
    "allarme": "Segnale di allarme.",
    "avviso": "Segnale di avviso.",
}

UNITA = ("quota", "conteggio", "ore", "minuti", "nessuna")
#: L'unita' della misura di ogni codice (senza suffisso). 'nessuna' vuol dire
#: misura sempre null: i segnali di spesa non portano numeri nel pannello.
UNITA_MISURA: dict[str, str] = {
    "monitor_fermo": "ore", "produttore_fermo": "ore", "job_orario": "ore",
    "lavorazione_lunga": "minuti", "lavorazione_orfana": "minuti",
    "fonti_da_verificare": "quota", "schede_senza_sezione": "quota",
    "controlli_non_riusciti": "quota",
    "limite_di_spesa": "nessuna", "credito_ricerca_basso": "nessuna",
    "consumo_mensile_alto": "nessuna", "scorta_piano_bassa": "nessuna",
    "servizio_non_attivo": "nessuna", "configurazione": "nessuna",
    "misure_non_disponibili": "nessuna", "modello_fuori_listino": "nessuna",
    "non_misurato": "nessuna", "riepilogo_non_valido": "nessuna",
    "ingresso_fermo": "conteggio", "classificazione_non_disponibile": "conteggio",
    "accesso_fonte_riservata": "conteggio", "riavvii_ripetuti": "conteggio",
    "passo_degradato": "conteggio", "fermi_in_lavorazione": "conteggio",
    "ingresso_guasto": "conteggio", "eventi_non_applicati": "conteggio",
    "eventi_non_scritti": "conteggio", "eventi_non_leggibili": "conteggio",
    "passi_ripetuti_non_ok": "conteggio",
    # percorso A
    "verifica_stato_ferma": "ore", "leggibile_non_letto": "conteggio",
    "lettura_non_verificante": "conteggio", "estrattore_muto": "conteggio",
    "freno_chiusure": "conteggio", "prosa_non_riscritta": "conteggio",
    "aperti_senza_conferma": "quota", "ingresso_trattenuti": "conteggio",
    "indicepa_non_aggiornato": "nessuna", "indicepa_import_anomalo": "nessuna",
    "vista_lenta": "nessuna",
}

#: I nomi veri degli step della pipeline, tradotti. Un nome sconosciuto e' «altro».
NOMI_PASSI_NEUTRI: dict[str, str] = {
    "discover": "ingresso", "scrape": "lettura", "preprocess": "estrazione",
    "enrich": "arricchimento", "resolver": "ricerca_fonti", "seo": "redazione",
    "monitor": "controllo_pagine", "ricontrolli": "ricontrolli",
    "verifica_stato": "verifica_stato",
}
PASSO_SCONOSCIUTO = "altro"

#: I testi dei non misurati di `telemetria` che hanno una voce neutra; gli
#: altri si scartano, mai copiati.
NON_MISURATI_NEUTRI: dict[str, str] = {
    "servizio del produttore": "servizio",
    "job orario delle transizioni": "job_orario",
    "login Obiettivo Europa": "accesso_fonte_riservata",
    "crediti residui Firecrawl": "credito_ricerca",
    "schede OE con sezione «Link e Documenti»": "schede_con_sezione",
}

#: Nomi che non compaiono mai in quello che BandoFit legge (§1), piu' quelli di §9.2.
NOMI_VIETATI: tuple[str, ...] = (
    "edunews", "news1", "anthropic", "claude", "haiku", "firecrawl", "obiettivo",
    "indexnow", "supabase", "systemd", "bandi_pipeline",
)
#: URL, indirizzi, percorsi, host (`parola.dominio`) e nomi vietati, senza
#: distinguere maiuscole e minuscole.
_NON_NEUTRO_RE = re.compile(
    r"https?:|://|@|/|\w+\.[a-z]{2,}|" + "|".join(re.escape(n) for n in NOMI_VIETATI),
    re.IGNORECASE,
)
#: Le sigle di ambiente (`MONITOR_MODALITA`, `PID`...): solo maiuscole, a parte.
_MAIUSCOLE_RE = re.compile(r"[A-Z_]{4,}")
_ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_CODICE_RE = re.compile(r"^[a-z_]+(?::[a-z0-9_]{1,32})?$")


def testo_neutro(s: Any) -> bool:
    """Vero se la stringa non porta URL, host, indirizzi, sigle di ambiente o nomi vietati."""
    return (isinstance(s, str) and _MAIUSCOLE_RE.search(s) is None
            and _NON_NEUTRO_RE.search(s) is None)


# --- costanti ricopiate da `telemetria` (confrontate nei test) -----------------

_GIRI_DI_REGIME = {"00:00": "00", "06:00": "06", "12:00": "12", "18:00": "18"}
_GIRO_AVVIO = "boot"
_LAVORAZIONI_PER_LOCK = {
    "bandi_pipeline": "giro", "monitor": "controllo_pagine", "bandi_resolver": "ricerca_fonti",
}
_LOCK_AVVISO_MIN = 60
_LOCK_ALLARME_MIN = 180
_STATI_SERVIZIO_FERMO = ("failed", "inactive")


# --- utilita' ---------------------------------------------------------------

def _istante(valore: Any) -> datetime | None:
    """`timestamptz` di PostgREST -> datetime aware in UTC (None se illeggibile).

    Le frazioni di secondo si scartano prima del parsing: `fromisoformat` di
    Python 3.10 non accetta le frazioni a 5 cifre che PostgREST a volte manda.
    """
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
    if letto.tzinfo is None:
        letto = letto.replace(tzinfo=timezone.utc)
    return letto.astimezone(timezone.utc)


def _iso(valore: Any) -> str | None:
    """Un istante come ISO 8601 UTC con la Z, o None."""
    istante = _istante(valore)
    return istante.strftime("%Y-%m-%dT%H:%M:%SZ") if istante is not None else None


def _intero(valore: Any) -> int | None:
    """Un conteggio non negativo, o None se manca o non e' un numero."""
    if valore is None or isinstance(valore, bool):
        return None
    try:
        numero = int(float(valore))
    except (TypeError, ValueError):
        return None
    return max(0, numero)


def _mappa(valore: Any) -> Mapping[str, Any]:
    return valore if isinstance(valore, Mapping) else {}


def _righe(valore: Any) -> list[Mapping[str, Any]]:
    if not isinstance(valore, (list, tuple)):
        return []
    return [r for r in valore if isinstance(r, Mapping)]


def _saltata(riga: Mapping[str, Any]) -> bool:
    return riga.get("esito") == "saltato" or bool(_mappa(riga.get("contatori")).get("saltato_per_lock"))


def _dalla_piu_recente(righe: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    zero = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def chiave(riga: Mapping[str, Any]) -> tuple[datetime, int]:
        return (_istante(riga.get("avviato_at")) or zero, _intero(riga.get("id")) or 0)
    return sorted(righe, key=chiave, reverse=True)


def prefisso(codice: str) -> str:
    return codice.split(":", 1)[0]


def _misura(codice: str, valore: Any) -> float | int | None:
    """La misura nella sua unita': 'nessuna' e' sempre null."""
    unita = UNITA_MISURA.get(prefisso(codice), "nessuna")
    if unita == "nessuna" or valore is None or isinstance(valore, bool):
        return None
    try:
        numero = float(valore)
    except (TypeError, ValueError):
        return None
    if unita == "quota":
        return round(min(1.0, max(0.0, numero)), 3)
    if unita == "ore":
        return round(max(0.0, numero), 1)
    return int(round(max(0.0, numero)))


def _testo(codice: str, livello: str, misura: float | int | None) -> str:
    """La frase neutra del codice, con la misura al posto del segnaposto."""
    modello = TESTI_NEUTRI_PER_LIVELLO.get((prefisso(codice), livello)) or TESTI_NEUTRI.get(prefisso(codice))
    if modello is None:
        return TESTO_SENZA_MISURA[livello]
    if "{" not in modello:
        return modello
    if misura is None:
        return TESTO_SENZA_MISURA[livello]
    valori = {
        "n": str(int(misura)), "ore": f"{float(misura):.0f}", "minuti": f"{float(misura):.0f}",
        "quota": f"{float(misura):.0%}",
    }
    return modello.format(**valori)


# --- composizione -------------------------------------------------------------

def _segnali(salute: Any, memoria: Mapping[str, Any], adesso: datetime) -> list[dict[str, Any]]:
    """Le voci della salute, una per codice, senza `non_misurato` (§9.1: i
    non misurati non cambiano lo stato). Gli allarmi prima, poi gli avvisi."""
    dal_prima = _mappa(memoria.get("dal"))
    per_codice: dict[str, dict[str, Any]] = {}
    for voce in getattr(salute, "voci", ()) or ():
        codice = getattr(voce, "codice", None)
        livello = getattr(voce, "livello", None)
        if not isinstance(codice, str) or codice == "non_misurato" or livello not in LIVELLI:
            continue
        # Un prefisso senza frase resta, col testo generico: sparire in
        # silenzio sarebbe peggio di un testo povero.
        if not _CODICE_RE.match(codice):
            continue
        misura = _misura(codice, getattr(voce, "misura", None))
        gia = per_codice.get(codice)
        if gia is None:
            dal = _istante(dal_prima.get(codice))
            per_codice[codice] = {
                "codice": codice, "livello": livello,
                "dal": _iso(dal if dal is not None and dal <= adesso else adesso),
                "misura": misura,
            }
            continue
        # Lo stesso codice due volte (due lock «altro», due modelli): il
        # livello piu' grave e la misura piu' alta.
        if livello == "allarme":
            gia["livello"] = "allarme"
        if misura is not None and (gia["misura"] is None or misura > gia["misura"]):
            gia["misura"] = misura
    segnali = sorted(per_codice.values(), key=lambda s: LIVELLI.index(s["livello"]))[:MAX_SEGNALI]
    for segnale in segnali:
        segnale["testo"] = _testo(segnale["codice"], segnale["livello"], segnale["misura"])
    return [{k: s[k] for k in SCHEMA_V1["segnali"]["voce"]} for s in segnali]


def _non_misurati(salute: Any, misure: Mapping[str, Any]) -> list[str]:
    """Solo le voci neutre di §9.1: gli altri testi dei non misurati si scartano."""
    trovati: set[str] = set()
    for voce in getattr(salute, "voci", ()) or ():
        if getattr(voce, "codice", None) != "non_misurato":
            continue
        testo_cli = str(getattr(voce, "testo_cli", "") or "")
        for testo, neutro in NON_MISURATI_NEUTRI.items():
            if testo in testo_cli:
                trovati.add(neutro)
    if misure.get("da_verificare") is None:
        trovati.add("da_verificare")
    return [n for n in NON_MISURATI_V1 if n in trovati]


def _stato_servizio(servizio: Any) -> str:
    servizio = _mappa(servizio)
    attivo = str(servizio.get("active_state") or "").lower()
    sotto = str(servizio.get("sub_state") or "").lower()
    if not attivo:
        return "non_misurato"
    if attivo in _STATI_SERVIZIO_FERMO or (attivo == "activating" and sotto == "auto-restart"):
        return "non_attivo"
    return "attivo"


def _produttore(misure: Mapping[str, Any], adesso: datetime) -> dict[str, Any]:
    righe = _righe(misure.get("ultime_pipeline"))
    conclusi = [
        t for t in (_istante(r.get("concluso_at")) for r in righe
                    if r.get("giro") in _GIRI_DI_REGIME and not _saltata(r))
        if t is not None
    ]
    ultimo = max(conclusi) if conclusi else None
    dal_24h = adesso - timedelta(hours=24)

    def nelle_24h(riga: Mapping[str, Any]) -> bool:
        avvio = _istante(riga.get("avviato_at"))
        return avvio is not None and dal_24h <= avvio <= adesso

    misurate = misure.get("ultime_pipeline") is not None
    return {
        "ultimo_giro_at": _iso(ultimo),
        "ore_dall_ultimo_giro": (round(max(0.0, (adesso - ultimo).total_seconds() / 3600), 1)
                                 if ultimo is not None else None),
        "giri_24h": sum(1 for r in righe if nelle_24h(r) and not _saltata(r)) if misurate else None,
        "riavvii_24h": (sum(1 for r in righe if nelle_24h(r) and r.get("giro") == _GIRO_AVVIO)
                        if misurate else None),
        "servizio": _stato_servizio(misure.get("servizio")),
    }


def _giro_neutro(giro: Any) -> str:
    if giro in _GIRI_DI_REGIME:
        return _GIRI_DI_REGIME[giro]
    return "avvio" if giro == _GIRO_AVVIO else "manuale"


def _esito(valore: Any) -> str:
    """L'esito della riga se e' nell'enum; qualunque altra cosa vale «errore»."""
    return valore if valore in ESITI_V1 else "errore"


def _giri(misure: Mapping[str, Any]) -> list[dict[str, Any]]:
    uscita = []
    for riga in _dalla_piu_recente(_righe(misure.get("ultime_pipeline")))[:MAX_GIRI]:
        avvio, fine = _istante(riga.get("avviato_at")), _istante(riga.get("concluso_at"))
        passi = _mappa(riga.get("contatori")).get("passi_non_ok")
        uscita.append({
            "id": _intero(riga.get("id")),
            "giro": _giro_neutro(riga.get("giro")),
            "avviato_at": _iso(avvio),
            "concluso_at": _iso(fine),
            "durata_min": (round(max(0.0, (fine - avvio).total_seconds() / 60), 1)
                           if avvio is not None and fine is not None else None),
            "esito": _esito(riga.get("esito")),
            "interrotto_per_tetto": bool(riga.get("interrotto_per_tetto")),
            "passi_non_ok": sorted({NOMI_PASSI_NEUTRI.get(str(p), PASSO_SCONOSCIUTO)
                                    for p in passi}) if isinstance(passi, (list, tuple)) else [],
        })
    return uscita


def _controlli(misure: Mapping[str, Any]) -> list[dict[str, Any]]:
    uscita = []
    for riga in _dalla_piu_recente(_righe(misure.get("ultimi_monitor")))[:MAX_CONTROLLI]:
        contatori = _mappa(riga.get("contatori"))
        uscita.append({
            "avviato_at": _iso(riga.get("avviato_at")),
            "esito": _esito(riga.get("esito")),
            "classificazioni": _intero(contatori.get("classificazioni")),
            "classificazioni_fallite": _intero(contatori.get("classificazioni_fallite")),
            "eventi_non_applicati": _intero(contatori.get("eventi_non_applicati")),
        })
    return uscita


def _lavorazioni(misure: Mapping[str, Any], adesso: datetime) -> list[dict[str, Any]]:
    """I lock validi, con le soglie di `salute`. Mai il proprietario (porta il PID)."""
    uscita = []
    for riga in _righe(misure.get("lock")):
        preso, scade = _istante(riga.get("acquisito_at")), _istante(riga.get("scade_at"))
        if preso is None or scade is None or scade <= adesso:
            continue
        da_min = round(max(0.0, (adesso - preso).total_seconds() / 60), 1)
        ttl_min = round(max(0.0, (scade - preso).total_seconds() / 60), 1)
        soglia_allarme, soglia_avviso = _LOCK_ALLARME_MIN, _LOCK_AVVISO_MIN
        if ttl_min:
            soglia_allarme = min(soglia_allarme, ttl_min * 2 / 3)
            soglia_avviso = min(soglia_avviso, ttl_min / 3)
        stato = ("probabile_orfana" if da_min >= soglia_allarme
                 else "lunga" if da_min >= soglia_avviso else "regolare")
        uscita.append({
            "nome": _LAVORAZIONI_PER_LOCK.get(str(riga.get("nome") or ""), "altro"),
            "da_min": da_min, "ttl_min": ttl_min, "stato": stato,
        })
    return sorted(uscita, key=lambda l: -l["da_min"])[:MAX_LAVORAZIONI]


def _job_orario(misure: Mapping[str, Any]) -> dict[str, Any]:
    job = _mappa(misure.get("job_orario"))
    if not job.get("misurato"):
        return {"ultimo_avvio_at": None, "ultimo_esito": "non_misurato",
                "ultimo_ok_at": None, "falliti_24h": None}
    esito = job.get("ultimo_esito")
    return {
        "ultimo_avvio_at": _iso(job.get("ultimo_avvio_at")),
        "ultimo_esito": esito if esito in ESITI_JOB_V1 else "non_misurato",
        "ultimo_ok_at": _iso(job.get("ultimo_ok_at")),
        "falliti_24h": _intero(job.get("falliti_24h")),
    }


def _conteggi(valore: Any, ammessi: Sequence[str]) -> dict[str, int]:
    """I conteggi di un oggetto `{chiave: n}`, solo per le chiavi dell'elenco."""
    valore = _mappa(valore)
    uscita = {}
    for chiave in ammessi:
        n = _intero(valore.get(chiave))
        if n:
            uscita[chiave] = n
    return uscita


def _da_verificare(misura: Any) -> dict[str, Any] | None:
    """La sezione `da_verificare` di §9.1 da `misure_salute['da_verificare']`, o null."""
    if not isinstance(misura, Mapping):
        return None
    return {
        "in_apertura": _conteggi(misura.get("in_apertura"), MOTIVI_DA_VERIFICARE_V1),
        "aperto": _conteggi(misura.get("aperto"), MOTIVI_DA_VERIFICARE_V1),
        "proposte_in_ombra_per_tipo": _conteggi(misura.get("proposte_in_ombra_per_tipo"), TIPI_PROPOSTA_V1),
        "chiusure_applicate_7g": _intero(misura.get("chiusure_applicate_7g")) or 0,
        "host_frenati": _intero(misura.get("host_frenati")) or 0,
        "pagine_rimosse": _intero(misura.get("pagine_rimosse")) or 0,
        "forse_non_bandi": _intero(misura.get("forse_non_bandi")) or 0,
    }


def _stato(segnali: Sequence[Mapping[str, Any]]) -> str:
    livelli = {s.get("livello") for s in segnali}
    if "allarme" in livelli:
        return "guasto"
    return "attenzione" if "avviso" in livelli else "ok"


def riepilogo_pannello(salute: Any, misure: Mapping[str, Any] | None, adesso: datetime) -> dict[str, Any]:
    """Il riepilogo v1 dalla salute e dalle misure della stessa fotografia.

    `salute` e' una `telemetria.Salute` (se ne leggono solo le `voci`);
    `misure` e' il dizionario di `db.misure_salute` con `servizio`, `memoria`
    e `job_orario` aggiunti da `sorveglia`. La `memoria.dal` di prima dice da
    quando un codice e' acceso: `sorveglia` la aggiorna con i `dal` dei
    `segnali` di questo riepilogo.
    """
    misure = _mappa(misure)
    momento = _istante(adesso) or datetime.now(tz=timezone.utc)
    segnali = _segnali(salute, _mappa(misure.get("memoria")), momento)
    fermi_ingresso = misure.get("scraped_fermi")
    return {
        "versione": VERSIONE,
        "calcolato_at": _iso(momento),
        "stato": _stato(segnali),
        "segnali": segnali,
        "non_misurati": _non_misurati(salute, misure),
        "produttore": _produttore(misure, momento),
        "giri": _giri(misure),
        "controlli": _controlli(misure),
        "lavorazioni": _lavorazioni(misure, momento),
        "ingresso": {
            "fermi_in_ingresso": (len(fermi_ingresso) if isinstance(fermi_ingresso, (list, tuple))
                                  else _intero(fermi_ingresso)),
            "fermi_in_lavorazione": _intero(misure.get("fermi_in_lavorazione")),
            "ultimo_bando_nuovo_at": _iso(misure.get("ultimo_bando_nuovo_at")),
        },
        "eventi": {
            "ammessi_non_applicati": _intero(misure.get("ammessi_non_applicati")),
            "proposte_7g": _intero(misure.get("proposte_7g")),
            "in_attesa_pubblicazione": _intero(misure.get("in_attesa_pubblicazione")),
        },
        # Prima della 13 (percorso A) non si misura: null, e fra i non misurati.
        "da_verificare": _da_verificare(misure.get("da_verificare")),
        "job_orario": _job_orario(misure),
    }


def riepilogo_minimo(adesso: datetime, *, dal: Any = None) -> dict[str, Any]:
    """Il riepilogo che `sorveglia` scrive quando `valida_v1` fallisce.

    Uno stato «guasto» con il solo segnale `riepilogo_non_valido` e tutte le
    altre chiavi vuote: il pannello sa che qualcosa non va senza leggere niente
    di quello che non ha passato la validazione.
    """
    momento = _istante(adesso) or datetime.now(tz=timezone.utc)
    inizio = _istante(dal)
    return {
        "versione": VERSIONE,
        "calcolato_at": _iso(momento),
        "stato": "guasto",
        "segnali": [{
            "codice": "riepilogo_non_valido", "livello": "allarme",
            "testo": TESTI_NEUTRI["riepilogo_non_valido"],
            "dal": _iso(inizio if inizio is not None and inizio <= momento else momento),
            "misura": None,
        }],
        "non_misurati": [],
        "produttore": {"ultimo_giro_at": None, "ore_dall_ultimo_giro": None, "giri_24h": None,
                       "riavvii_24h": None, "servizio": "non_misurato"},
        "giri": [],
        "controlli": [],
        "lavorazioni": [],
        "ingresso": {"fermi_in_ingresso": None, "fermi_in_lavorazione": None,
                     "ultimo_bando_nuovo_at": None},
        "eventi": {"ammessi_non_applicati": None, "proposte_7g": None,
                   "in_attesa_pubblicazione": None},
        "da_verificare": None,
        "job_orario": {"ultimo_avvio_at": None, "ultimo_esito": "non_misurato",
                       "ultimo_ok_at": None, "falliti_24h": None},
    }


# --- validazione ------------------------------------------------------------

def _e_iso(valore: Any, *, nullo: bool = True) -> bool:
    return (valore is None and nullo) or (isinstance(valore, str) and bool(_ISO_UTC_RE.match(valore)))


def _e_conteggio(valore: Any) -> bool:
    return valore is None or (isinstance(valore, int) and not isinstance(valore, bool) and valore >= 0)


def _e_numero(valore: Any) -> bool:
    return valore is None or (isinstance(valore, (int, float)) and not isinstance(valore, bool)
                              and valore >= 0)


def _chiavi(errori: list[str], dove: str, valore: Any, attese: Sequence[str]) -> bool:
    if not isinstance(valore, Mapping):
        errori.append(f"{dove}: non e' un oggetto")
        return False
    if set(valore) != set(attese):
        errori.append(f"{dove}: chiavi {sorted(valore)} invece di {sorted(attese)}")
        return False
    return True


def _lista(errori: list[str], dove: str, valore: Any, massimo: int) -> list[Any]:
    if not isinstance(valore, list):
        errori.append(f"{dove}: non e' una lista")
        return []
    if len(valore) > massimo:
        errori.append(f"{dove}: {len(valore)} elementi, massimo {massimo}")
    return valore


def _stringhe(valore: Any) -> list[str]:
    if isinstance(valore, str):
        return [valore]
    if isinstance(valore, Mapping):
        return [s for k, v in valore.items() for s in [str(k), *_stringhe(v)]]
    if isinstance(valore, (list, tuple)):
        return [s for v in valore for s in _stringhe(v)]
    return []


def valida_v1(d: Any) -> list[str]:
    """Gli errori del riepilogo rispetto allo schema v1 (lista vuota = valido)."""
    errori: list[str] = []
    if not _chiavi(errori, "riepilogo", d, ("versione", "calcolato_at", *CHIAVI_V1)):
        return errori
    if d["versione"] != VERSIONE or isinstance(d["versione"], bool):
        errori.append("versione diversa da 1")
    if not _e_iso(d["calcolato_at"], nullo=False):
        errori.append("calcolato_at non ISO 8601 UTC")

    segnali = _lista(errori, "segnali", d["segnali"], MAX_SEGNALI)
    codici = []
    for i, s in enumerate(segnali):
        dove = f"segnali[{i}]"
        if not _chiavi(errori, dove, s, SCHEMA_V1["segnali"]["voce"]):
            continue
        codice = s["codice"]
        if not (isinstance(codice, str) and _CODICE_RE.match(codice)):
            errori.append(f"{dove}: codice non ammesso")
            continue
        if prefisso(codice) not in TESTI_NEUTRI and (
                s["testo"] not in TESTO_SENZA_MISURA.values() or s["misura"] is not None):
            # Un prefisso senza frase esce solo col testo generico, senza misura.
            errori.append(f"{dove}: prefisso senza testo neutro e testo non generico")
        codici.append(codice)
        if codice == "non_misurato":
            errori.append(f"{dove}: non_misurato non e' un segnale")
        if s["livello"] not in LIVELLI:
            errori.append(f"{dove}: livello non ammesso")
        if not testo_neutro(s["testo"]):
            errori.append(f"{dove}: testo non neutro")
        if not _e_iso(s["dal"], nullo=False):
            errori.append(f"{dove}: dal non ISO 8601 UTC")
        unita = UNITA_MISURA.get(prefisso(codice), "nessuna")
        misura = s["misura"]
        if unita == "nessuna" and misura is not None:
            errori.append(f"{dove}: misura con unita' 'nessuna'")
        elif not _e_numero(misura):
            errori.append(f"{dove}: misura non numerica")
        elif unita == "quota" and misura is not None and not 0 <= misura <= 1:
            errori.append(f"{dove}: quota fuori da 0..1")
    if len(set(codici)) != len(codici):
        errori.append("segnali: codici ripetuti")
    atteso = _stato([s for s in segnali if isinstance(s, Mapping)])
    if d["stato"] not in STATI or d["stato"] != atteso:
        errori.append(f"stato {d['stato']!r} incoerente con i segnali ({atteso})")

    non_misurati = d["non_misurati"]
    if (not isinstance(non_misurati, list) or any(n not in NON_MISURATI_V1 for n in non_misurati)
            or len(set(non_misurati)) != len(non_misurati)):
        errori.append("non_misurati fuori dall'elenco o ripetuti")

    p = d["produttore"]
    if _chiavi(errori, "produttore", p, SCHEMA_V1["produttore"]):
        if not (_e_iso(p["ultimo_giro_at"]) and _e_numero(p["ore_dall_ultimo_giro"])
                and _e_conteggio(p["giri_24h"]) and _e_conteggio(p["riavvii_24h"])
                and p["servizio"] in SERVIZIO_V1):
            errori.append("produttore: valori non ammessi")

    for i, g in enumerate(_lista(errori, "giri", d["giri"], MAX_GIRI)):
        if _chiavi(errori, f"giri[{i}]", g, SCHEMA_V1["giri"]["voce"]):
            passi = g["passi_non_ok"]
            nomi = set(NOMI_PASSI_NEUTRI.values()) | {PASSO_SCONOSCIUTO}
            if not (_e_conteggio(g["id"]) and g["giro"] in GIRI_V1 and _e_iso(g["avviato_at"])
                    and _e_iso(g["concluso_at"]) and _e_numero(g["durata_min"])
                    and g["esito"] in ESITI_V1 and isinstance(g["interrotto_per_tetto"], bool)
                    and isinstance(passi, list) and all(p in nomi for p in passi)):
                errori.append(f"giri[{i}]: valori non ammessi")

    for i, c in enumerate(_lista(errori, "controlli", d["controlli"], MAX_CONTROLLI)):
        if _chiavi(errori, f"controlli[{i}]", c, SCHEMA_V1["controlli"]["voce"]):
            if not (_e_iso(c["avviato_at"]) and c["esito"] in ESITI_V1
                    and all(_e_conteggio(c[k]) for k in ("classificazioni",
                            "classificazioni_fallite", "eventi_non_applicati"))):
                errori.append(f"controlli[{i}]: valori non ammessi")

    for i, lav in enumerate(_lista(errori, "lavorazioni", d["lavorazioni"], MAX_LAVORAZIONI)):
        if _chiavi(errori, f"lavorazioni[{i}]", lav, SCHEMA_V1["lavorazioni"]["voce"]):
            if not (lav["nome"] in LAVORAZIONI_V1 and _e_numero(lav["da_min"])
                    and _e_numero(lav["ttl_min"]) and lav["stato"] in STATI_LAVORAZIONE_V1):
                errori.append(f"lavorazioni[{i}]: valori non ammessi")

    ingresso = d["ingresso"]
    if _chiavi(errori, "ingresso", ingresso, SCHEMA_V1["ingresso"]):
        if not (_e_conteggio(ingresso["fermi_in_ingresso"])
                and _e_conteggio(ingresso["fermi_in_lavorazione"])
                and _e_iso(ingresso["ultimo_bando_nuovo_at"])):
            errori.append("ingresso: valori non ammessi")
    eventi = d["eventi"]
    if _chiavi(errori, "eventi", eventi, SCHEMA_V1["eventi"]):
        if not all(_e_conteggio(v) for v in eventi.values()):
            errori.append("eventi: valori non ammessi")
    dv = d["da_verificare"]
    if dv is not None and _chiavi(errori, "da_verificare", dv, SCHEMA_V1["da_verificare"]):
        for chiave, ammessi in (("in_apertura", MOTIVI_DA_VERIFICARE_V1), ("aperto", MOTIVI_DA_VERIFICARE_V1),
                                ("proposte_in_ombra_per_tipo", TIPI_PROPOSTA_V1)):
            voce = dv[chiave]
            if not (isinstance(voce, Mapping) and all(k in ammessi and _e_conteggio(v) and v is not None
                                                      for k, v in voce.items())):
                errori.append(f"da_verificare.{chiave}: chiavi o valori non ammessi")
        for chiave in ("chiusure_applicate_7g", "host_frenati", "pagine_rimosse", "forse_non_bandi"):
            if dv[chiave] is None or not _e_conteggio(dv[chiave]):
                errori.append(f"da_verificare.{chiave}: non e' un conteggio")
    job = d["job_orario"]
    if _chiavi(errori, "job_orario", job, SCHEMA_V1["job_orario"]):
        if not (_e_iso(job["ultimo_avvio_at"]) and job["ultimo_esito"] in ESITI_JOB_V1
                and _e_iso(job["ultimo_ok_at"]) and _e_conteggio(job["falliti_24h"])):
            errori.append("job_orario: valori non ammessi")

    # Ultima rete: nessuna stringa, in nessun punto, porta host, URL, PID o nomi vietati.
    for s in _stringhe(d):
        if not (_ISO_UTC_RE.match(s) or testo_neutro(s)):
            errori.append(f"stringa non neutra: {s[:40]!r}")
            break
    return errori


__all__ = [
    "CHIAVI_V1", "MAX_SEGNALI", "NOMI_PASSI_NEUTRI", "NON_MISURATI_NEUTRI", "NON_MISURATI_V1",
    "SCHEMA_V1", "TESTI_NEUTRI", "TESTI_NEUTRI_PER_LIVELLO", "UNITA", "UNITA_MISURA", "VERSIONE",
    "riepilogo_minimo", "riepilogo_pannello", "testo_neutro", "valida_v1",
]
