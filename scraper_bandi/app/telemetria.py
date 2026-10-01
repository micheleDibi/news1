"""Telemetria della pipeline bandi: `pipeline_run`, `fonte_run`, `salute`.

Fix 8.a.14: oggi di un giro non resta niente di interrogabile. Se lo scrape di
una fonte smette di produrre bandi, o se un tetto scatta due giri di fila, lo si
scopre leggendo i log a mano. Qui ogni giro lascia due righe:

  - `pipeline_run` — un giro di uno step: durata, esito, contatori, crediti,
    costo, `interrotto_per_tetto`, `slug_modificati`;
  - `fonte_run` — la stessa cosa per fonte, cosi' «la fonte 237 non trova piu'
    niente» diventa una query invece di una lettura di log.

Due scelte che vengono dai vincoli del piano:

* **le funzioni sono pure**, l'I/O sta in tre funzioni sole (`scrivi_*`), e
  passa da `db.controllo`: finche' la migrazione 02 non e' applicata le tabelle
  non esistono e la scrittura e' un no-op con log, non un errore che ferma lo
  step (§16.2 M12, A21);
* **`salute(stato)` e' pura** e ritorna allarmi + exit code atteso. Il codice di
  uscita lo applica `__main__.py`: dentro la pipeline non si esce mai (§16, A15).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from .bilancio import conta_nel_regime
from .logger import logger

TABELLA_RUN = "pipeline_run"
TABELLA_FONTE_RUN = "fonte_run"

ESITO_OK = "ok"
ESITO_ERRORE = "errore"
ESITO_SALTATO = "saltato"
ESITO_INTERROTTO = "interrotto_per_tetto"

PREFISSO_ALLARME = "[ALLARME]"

#: Campi di `PipelineRun` che `come_riga` rispecchia dentro `contatori`: la
#: colonna non esiste, ma il valore non si perde e `_inserisci` non deve
#: gridare. Sta qui e non dentro la dataclass perche' un attributo annotato
#: dentro un `@dataclass` diventa un campo, e finirebbe in `asdict()`.
RISPECCHIATI_PIPELINE_RUN: frozenset[str] = frozenset({
    "durata_s", "crediti", "costo_usd", "slug_modificati", "saltato_per_lock",
})


def _adesso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class PipelineRun:
    """Un giro di uno step. `giro` e' l'ora pianificata ("06:00") o None da CLI."""
    step: str
    giro: str | None = None
    avviato_at: str = field(default_factory=_adesso)
    concluso_at: str | None = None
    durata_s: float = 0.0
    esito: str = ESITO_OK
    contatori: Mapping[str, Any] = field(default_factory=dict)
    crediti: int = 0
    costo_usd: float = 0.0
    interrotto_per_tetto: bool = False
    motivo: str = ""
    slug_modificati: tuple[str, ...] = ()
    saltato_per_lock: bool = False

    def concludi(
        self,
        *,
        durata_s: float,
        esito: str = ESITO_OK,
        contatori: Mapping[str, Any] | None = None,
        crediti: int | None = None,
        costo_usd: float | None = None,
        interrotto_per_tetto: bool | None = None,
        motivo: str | None = None,
        slug_modificati: tuple[str, ...] | None = None,
        saltato_per_lock: bool | None = None,
    ) -> "PipelineRun":
        """Copia conclusa del giro (la dataclass e' immutabile per costruzione:
        una riga di telemetria non deve poter cambiare dopo essere stata letta)."""
        return replace(
            self,
            concluso_at=_adesso(),
            durata_s=round(durata_s, 1),
            esito=esito,
            contatori=dict(contatori if contatori is not None else self.contatori),
            crediti=self.crediti if crediti is None else crediti,
            costo_usd=self.costo_usd if costo_usd is None else round(costo_usd, 6),
            interrotto_per_tetto=(
                self.interrotto_per_tetto if interrotto_per_tetto is None else interrotto_per_tetto),
            motivo=self.motivo if motivo is None else motivo,
            slug_modificati=(
                self.slug_modificati if slug_modificati is None else tuple(slug_modificati)),
            saltato_per_lock=(
                self.saltato_per_lock if saltato_per_lock is None else saltato_per_lock),
        )

    def come_riga(self) -> dict[str, Any]:
        """Payload per `pipeline_run` (tutte le chiavi, filtrate da `db.controllo`).

        `pipeline_run` ha dieci colonne — `(id, step, giro, avviato_at,
        concluso_at, esito, interrotto_per_tetto, motivo, contatori, note)` —
        e cinque dei campi di questa dataclass non ne hanno una: `durata_s`,
        `crediti`, `costo_usd`, `slug_modificati`, `saltato_per_lock`. Sono
        proprio i numeri su cui §6.2 fonda il tetto mensile, quello giornaliero
        e due allarmi di `salute`: `_inserisci` li avrebbe filtrati via senza
        un errore e senza una riga di log.

        Si rispecchiano dentro `contatori`, che e' jsonb ed esiste: nessuna
        migrazione da riscrivere, e `db.consumo_oggi` legge di li'. Le chiavi
        di primo livello restano: il giorno in cui le colonne ci saranno,
        `_inserisci` le prendera' da sole.
        """
        riga = asdict(self)
        riga["slug_modificati"] = list(self.slug_modificati)
        crediti, usd = self.crediti_effettivi, self.usd_effettivo
        riga["crediti"], riga["costo_usd"] = crediti, usd
        contatori = dict(self.contatori)
        contatori.update({
            "durata_s": self.durata_s,
            "crediti": crediti,
            "costo_usd": usd,
            # `usd` e' il nome che `bilancio.verifica_giornalieri` cerca in
            # `gia_oggi`: scrivere solo `costo_usd` renderebbe il tetto
            # giornaliero in dollari sempre zero.
            "usd": usd,
            "slug_modificati": list(self.slug_modificati),
            "saltato_per_lock": self.saltato_per_lock,
        })
        riga["contatori"] = contatori
        return riga

    @property
    def usd_effettivo(self) -> float:
        """`costo_usd`, o il `usd` dei contatori se `costo_usd` non e' stato dato.

        Il meccanismo unico della spesa (contratto `bandi-giro-3` §4) scrive la
        riga con `contatori=spesa.come_dizionario()`, che porta gia' `usd`.
        Prima `come_riga` lo sovrascriveva con `costo_usd` (0 se non passato):
        un passo che dimenticava `costo_usd=` risultava gratis, e il tetto
        giornaliero non lo vedeva.
        """
        if self.costo_usd:
            return self.costo_usd
        return round(_numero(self.contatori.get("usd")), 6)

    @property
    def crediti_effettivi(self) -> int:
        """`crediti`, o quelli dei contatori (`crediti`, poi `crediti_firecrawl`)."""
        if self.crediti:
            return self.crediti
        for chiave in ("crediti", "crediti_firecrawl"):
            valore = int(_numero(self.contatori.get(chiave)))
            if valore:
                return valore
        return 0


# --- copertura (contratto `bandi-giro-3` §1) ----------------------------------

#: Perche' un passo ha lasciato fuori dei candidati. Nessun tetto di numero:
#: restano fuori solo per tempo (rotazione), spesa, crediti, lock o errori.
MOTIVI_RIMASTI: tuple[str, ...] = ("tempo", "spesa", "crediti", "lock", "errore")
#: Il motivo che prende un valore fuori elenco: un motivo inventato non deve
#: sparire, ne' far fallire il passo che lo scrive.
MOTIVO_RIMASTI_IGNOTO = "errore"


def _conteggio(valore: Any) -> int:
    """Un conteggio non negativo; ogni cosa che non e' un numero vale 0."""
    if isinstance(valore, bool):
        return int(valore)
    try:
        return max(0, int(valore or 0))
    except (TypeError, ValueError):
        return 0


def copertura(candidati: Any, fatti: Any, motivo_rimasti: str | None = None) -> dict[str, Any]:
    """La chiave `copertura` dei contatori di un passo. Funzione pura.

    `{"candidati", "fatti", "rimasti", "motivo_rimasti"}` con `rimasti =
    candidati - fatti`. Un passo non puo' aver fatto piu' dei suoi candidati:
    se succede (la coda e' cresciuta durante il giro), i candidati diventano
    i fatti. `motivo_rimasti` vale null se non resta niente; fuori da
    `MOTIVI_RIMASTI` diventa `errore`, con un warning. Ogni passo mette il
    risultato al primo livello del dizionario che restituisce: la riga del
    giro lo conserva in `contatori.<passo>.copertura`, e `salute` lo legge.
    """
    fatti_n = _conteggio(fatti)
    candidati_n = max(_conteggio(candidati), fatti_n)
    rimasti = candidati_n - fatti_n
    motivo: str | None = None
    if rimasti > 0 and motivo_rimasti is not None:
        motivo = str(motivo_rimasti)
        if motivo not in MOTIVI_RIMASTI:
            logger.warning("[telemetria] motivo dei rimasti fuori elenco: {}", motivo[:40])
            motivo = MOTIVO_RIMASTI_IGNOTO
    return {"candidati": candidati_n, "fatti": fatti_n, "rimasti": rimasti,
            "motivo_rimasti": motivo}


@dataclass(frozen=True)
class FonteRun:
    """Esito dello scrape di una fonte dentro un giro."""
    fonte_id: int
    step: str = "scrape"
    run_id: int | None = None
    esito: str = ESITO_OK
    elementi: int = 0
    nuovi: int = 0
    cambiati: int = 0
    errori: int = 0
    durata_s: float = 0.0
    motivo: str = ""
    troncato: bool = False

    def come_riga(self) -> dict[str, Any]:
        """Payload per `fonte_run`, con i nomi che la tabella ha davvero.

        La 02 crea `(fonte_id, pipeline_run_id, items, nuovi, cambiati,
        identici, segnalati, spariti, pagine, troncato, errore, login_ok,
        durata_s)`: `run_id`, `elementi` e `motivo` non esistono con quel
        nome, e senza questa traduzione sparivano tutti e tre.
        """
        riga = asdict(self)
        riga["pipeline_run_id"] = riga.pop("run_id", None)
        riga["items"] = riga.pop("elementi", 0)
        # `esito` e `errori` non hanno una colonna: l'unico posto in cui si
        # possono dire e' `errore`, che e' testo libero.
        motivo = riga.pop("motivo", "") or ""
        errori = int(riga.pop("errori", 0) or 0)
        esito = riga.pop("esito", ESITO_OK)
        pezzi = [p for p in (motivo, f"{errori} errori" if errori else "") if p]
        if esito != ESITO_OK and not pezzi:
            pezzi.append(esito)
        riga["errore"] = "; ".join(pezzi) or None
        # `step` non ha colonna e non e' rispecchiabile: `fonte_run` descrive
        # per definizione lo scrape di una fonte dentro un giro.
        riga.pop("step", None)
        return riga


#: Quota di righe fallite oltre la quale il giro e' un guasto e non una
#: giornata con qualche sito giu'. Sotto questa soglia gli errori restano nei
#: contatori (e `salute` li vede) ma l'esito resta `ok`.
QUOTA_ERRORI_GUASTO = 0.5


def esito_da_contatori(
    *,
    errori: int = 0,
    lavorate: int | None = None,
    interrotto_per_tetto: bool = False,
    saltato_per_lock: bool = False,
) -> str:
    """Un solo posto che decide l'esito, cosi' i tre stati non divergono.

    `lavorate` e' quante righe il giro ha davvero guardato, e serve a
    distinguere «qualche sito era giu'» da «il giro e' fallito». Difetto
    misurato in produzione il 24/09/2026: la semina del monitor ha controllato
    420 bandi, 6 pagine non hanno risposto, e la riga di `pipeline_run` e'
    stata scritta `esito='errore'` mentre il riepilogo dello step diceva
    `status: ok` — due verdetti opposti sulla stessa riga. Un giro dichiarato
    fallito fa scattare `salute` e, se qualcuno lo automatizza, fa ripetere un
    lavoro riuscito: 1,4% di pagine morte e' la normalita' di un corpus di
    bandi pubblici, non un guasto.

    Senza `lavorate` il comportamento resta quello di prima (un errore = esito
    errore): i chiamanti che non sanno quante righe hanno lavorato non devono
    diventare piu' indulgenti per una firma nuova.
    """
    if saltato_per_lock:
        return ESITO_SALTATO
    if interrotto_per_tetto:
        return ESITO_INTERROTTO
    if not errori:
        return ESITO_OK
    if lavorate is None:
        return ESITO_ERRORE
    if int(lavorate) <= 0:
        # Nessuna riga lavorata e almeno un errore: non c'e' nient'altro che
        # possa aver funzionato.
        return ESITO_ERRORE
    return (ESITO_ERRORE if errori / int(lavorate) >= QUOTA_ERRORI_GUASTO
            else ESITO_OK)


def riepilogo(run: PipelineRun) -> str:
    """Una riga JSON per il log (§6.2: «Riepilogo in pipeline_run + 1 riga INFO»).

    Ordinata e senza spazi superflui: serve a essere grepata e incollata, non
    a essere bella.
    """
    return json.dumps(
        {
            "step": run.step,
            "giro": run.giro,
            "esito": run.esito,
            "durata_s": run.durata_s,
            "crediti": run.crediti_effettivi,
            "usd": run.usd_effettivo,
            "interrotto_per_tetto": run.interrotto_per_tetto,
            "saltato_per_lock": run.saltato_per_lock,
            "motivo": run.motivo,
            "slug_modificati": len(run.slug_modificati),
            "contatori": dict(run.contatori),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


# --- salute ----------------------------------------------------------------

#: Un lock di esecuzione tenuto piu' a lungo di cosi' merita uno sguardo; oltre
#: la seconda soglia e' quasi certamente orfano (un giro di regime dura minuti,
#: e un `systemctl restart` durante un giro lascia il lock fino alla scadenza).
#: Le soglie valgono anche in proporzione al TTL del lock (un terzo e due terzi):
#: un lock valido e' sempre piu' giovane del suo TTL, e con i TTL veri (monitor
#: 180', resolver 120') una soglia fissa a 180' non sarebbe mai scattata.
LOCK_AVVISO_MIN = 60
LOCK_ALLARME_MIN = 180
#: «Nuovi» per la quota di `in_verifica`: pubblicati negli ultimi N giorni, e
#: solo se sono almeno M (con 4 bandi su 13 la quota e' rumore, non un segnale).
GIORNI_NUOVI = 7
MINIMO_NUOVI = 10
#: `controlli_falliti` da cui un bando conta come «bloccato» (piano §6.2).
SOGLIA_CONTROLLI_FALLITI = 5
#: Cio' che `salute` non puo' sapere dal DB: lo dice, invece di tacerlo.
NON_MISURATO_ACCESSO_RISERVATO = "login Obiettivo Europa"
NON_MISURABILI_DAL_DB: tuple[str, ...] = (
    NON_MISURATO_ACCESSO_RISERVATO,
    "crediti residui Firecrawl",
    "schede OE con sezione «Link e Documenti»",
)
#: Le voci dei non misurati che non vengono dal DB ma dalla macchina
#: (`systemctl`) o dalla 12 (`monitoraggio_job_orario`).
NON_MISURATO_SERVIZIO = "servizio del produttore"
NON_MISURATO_JOB_ORARIO = "job orario delle transizioni"


# --- codici stabili (contratto `bandi-giro-2` §8) --------------------------

LIVELLO_ALLARME = "allarme"
LIVELLO_AVVISO = "avviso"
LIVELLI: tuple[str, ...] = (LIVELLO_ALLARME, LIVELLO_AVVISO)

#: Che cosa tiene un lock, in parole che non nominano i processi: la chiave e'
#: il `nome` in `pipeline_lock`, un nome non elencato vale «altro».
LAVORAZIONI_PER_LOCK: dict[str, str] = {
    "bandi_pipeline": "giro",
    "monitor": "controllo_pagine",
    "bandi_resolver": "ricerca_fonti",
}
SUFFISSI_LAVORAZIONE: tuple[str, ...] = ("giro", "controllo_pagine", "ricerca_fonti", "altro")
#: Le chiavi dei lettori dedicati (`etichette_stato.ESTRATTORI` senza il
#: generico), copiate qui per non importare bs4: un test le confronta.
ESTRATTORI_SALUTE: tuple[str, ...] = (
    "piemonte", "lazioeuropa", "lombardia", "calabria", "calabria_rc", "puglia",
    "formazionelavoro_er", "fesr_er", "pninclusione", "invitalia", "toscana", "fvg",
)
#: I passi del giro (contratto `bandi-giro-3` §2) col loro nome neutro: e' il
#: suffisso di `copertura_incompleta`, che arriva al pannello (niente nomi di
#: processi). Le chiavi sono `db.PASSI_DEL_GIRO`, i nomi gli stessi di
#: `riepilogo_salute.NOMI_PASSI_NEUTRI`: un test confronta tutti e due.
PASSI_NEUTRI: dict[str, str] = {
    "discover": "ingresso", "scrape": "lettura", "domini": "elenco_enti",
    "resolver_precoce": "ricerca_fonti_precoce", "preprocess": "estrazione",
    "enrich": "arricchimento", "resolver": "ricerca_fonti", "ricontrolli": "ricontrolli",
    "verifica_stato_ingresso": "verifica_ingresso", "seo": "redazione",
    "link_verifica": "verifica_link", "rielaborazione": "rielaborazione",
    "monitor": "controllo_pagine", "verifica_stato": "verifica_stato", "gemelli": "doppioni",
}
#: Le variabili del giro 3 che `Settings.configurazione_scartate` puo' nominare
#: (`settings.INTERVALLI_TEMPI` e `MODALITA_GIRO_3`, copiate: un test le
#: confronta), in minuscolo: sono il suffisso di `configurazione:<nome>`.
VARIABILI_GIRO_3: tuple[str, ...] = (
    "gemelli_modalita", "domini_modalita", "tempo_precoce_s", "tempo_ricontrolli_s",
    "tempo_link_verifica_s", "tempo_rielaborazione_s", "tempo_monitor_s",
)
#: I suffissi ammessi, per prefisso: una lista chiusa, come i codici.
SUFFISSI_CODICE: dict[str, tuple[str, ...]] = {
    "lavorazione_lunga": SUFFISSI_LAVORAZIONE,
    "lavorazione_orfana": SUFFISSI_LAVORAZIONE,
    "configurazione": ("modalita", "tipi_attivi", "giri", "indicizzazione", "verifica_stato",
                       *VARIABILI_GIRO_3),
    "passo_degradato": ("estrazione", "arricchimento", "redazione"),
    # percorso A: i lettori dedicati di `etichette_stato.ESTRATTORI` (il
    # generico no: ha di regola zero esiti, e sarebbe «muto» per sempre).
    "estrattore_muto": ESTRATTORI_SALUTE,
    "freno_chiusure": ESTRATTORI_SALUTE,
    # giro 3 (§1): un passo che lascia fuori dei bandi per GIRI_COPERTURA_INCOMPLETA giri di fila.
    "copertura_incompleta": tuple(PASSI_NEUTRI.values()),
}
#: I codici senza suffisso. Quelli del percorso A («stato da verificare»)
#: arrivano con il percorso A: qui non ci sono di proposito.
CODICI_SEMPLICI: tuple[str, ...] = (
    # rami di prima del giro 2
    "monitor_fermo", "misure_non_disponibili", "ingresso_fermo",
    "classificazione_non_disponibile", "accesso_fonte_riservata", "limite_di_spesa",
    "credito_ricerca_basso", "consumo_mensile_alto", "fonti_da_verificare",
    "schede_senza_sezione", "controlli_non_riusciti", "scorta_piano_bassa",
    "modello_fuori_listino", "non_misurato",
    # rami del giro 2
    "produttore_fermo", "riavvii_ripetuti", "servizio_non_attivo", "fermi_in_lavorazione",
    "ingresso_guasto", "eventi_non_applicati", "eventi_non_scritti", "eventi_non_leggibili",
    "passi_ripetuti_non_ok", "job_orario",
    # percorso A (§8 A e §19.6)
    "verifica_stato_ferma", "leggibile_non_letto", "lettura_non_verificante",
    "prosa_non_riscritta", "aperti_senza_conferma", "ingresso_trattenuti",
    "indicepa_non_aggiornato", "indicepa_import_anomalo", "vista_lenta",
    # lo scrive solo `sorveglia`, quando il riepilogo non passa la validazione
    "riepilogo_non_valido",
)
#: L'elenco chiuso dei codici: un codice fuori elenco fa fallire `_voce`.
CODICI_SALUTE: tuple[str, ...] = CODICI_SEMPLICI + tuple(
    f"{prefisso}:{suffisso}"
    for prefisso, suffissi in SUFFISSI_CODICE.items() for suffisso in suffissi
)
#: I codici senza il suffisso: le chiavi di `riepilogo_salute.TESTI_NEUTRI`.
PREFISSI_SALUTE: tuple[str, ...] = CODICI_SEMPLICI + tuple(SUFFISSI_CODICE)


def prefisso_codice(codice: str) -> str:
    """`passo_degradato:redazione` -> `passo_degradato`."""
    return codice.split(":", 1)[0]


def lavorazione_del_lock(nome: str) -> str:
    """Il suffisso neutro di un lock: `bandi_pipeline` -> `giro`."""
    return LAVORAZIONI_PER_LOCK.get(nome, "altro")


@dataclass(frozen=True)
class Voce:
    """Un segnale di `salute` con un codice stabile.

    `testo_cli` e' il testo di sempre (CLI e `--json`), che puo' nominare
    processi e fornitori; chi scrive per BandoFit usa il `codice`, mai questo
    testo. `misura` e' il numero che ha fatto scattare la voce, o None.
    """
    codice: str
    livello: str
    testo_cli: str
    misura: float | int | None = None


def _voce(
    voci: list[Voce], codice: str, livello: str, testo_cli: str,
    misura: float | int | None = None,
) -> None:
    """L'unico punto da cui passa ogni ramo di `salute`."""
    if codice not in CODICI_SALUTE:
        raise ValueError(f"codice di salute fuori elenco: {codice}")
    if livello not in LIVELLI:
        raise ValueError(f"livello di salute sconosciuto: {livello}")
    voci.append(Voce(codice, livello, testo_cli, misura))


@dataclass(frozen=True)
class LockTenuto:
    """Un lock di `pipeline_lock` ancora valido e da quanto e' tenuto."""
    nome: str
    proprietario: str
    minuti: float
    #: `scade_at - acquisito_at`: la durata che chi l'ha preso si era dato.
    ttl_min: float | None = None


@dataclass(frozen=True)
class Stato:
    """Fotografia che `salute` giudica. Chi la costruisce legge il DB; qui no."""
    ore_dall_ultimo_monitor_ok: float | None = None
    login_oe_ok: bool = True
    giri_consecutivi_a_tetto: int = 0
    crediti_residui_quota: float | None = None        # 0..1
    consumo_mensile_quota: float | None = None        # 0..1
    quota_in_verifica_nuovi: float | None = None      # 0..1
    quota_schede_oe_con_sezione: float | None = None  # 0..1
    quota_controlli_falliti: float | None = None      # 0..1
    residuo_piano_su_tetto_mensile: float | None = None
    modalita_monitor: str = "ombra"
    indexnow_configurata: bool = True
    monitor_giri_validi: bool = True
    modelli_fuori_listino: tuple[str, ...] = ()
    motivo_ultimo_tetto: str = ""
    lock_tenuti: tuple[LockTenuto, ...] = ()
    #: Classificazioni fallite nell'ultimo giro di monitor di regime: credito
    #: Anthropic esaurito o API giu'. Ogni giro cosi' e' lavoro da rifare.
    classificazioni_fallite_ultimo_monitor: int | None = None
    #: Le riuscite dello stesso giro: un errore isolato (un 529) fra tante
    #: riuscite e' un avviso, non un allarme sul credito.
    classificazioni_riuscite_ultimo_monitor: int | None = None
    #: Bandi entrati da oltre ORE_SCRAPED_FERMO ore e mai passati dal
    #: preprocess: l'ingresso e' fermo (credito Anthropic, API, preprocess).
    bandi_scraped_fermi: int | None = None
    #: Le misure sul DB non si sono potute fare: e' un allarme, non un silenzio.
    misure_db_errore: str | None = None
    #: Voci che questa esecuzione non ha misurato: finiscono negli avvisi.
    non_misurati: tuple[str, ...] = ()
    #: `MONITOR_TIPI_ATTIVI` come letta (contratto di ottobre 2026, §3), e i
    #: valori scartati perche' il monitor non li produce.
    tipi_attivi: tuple[str, ...] = ()
    tipi_attivi_ignorati: tuple[str, ...] = ()
    # --- giro 2 (§8): righe grezze, giudicate da `voci_sorveglianza` ---------
    #: Ultime righe `step='pipeline'` (anche saltate e di boot), con i soli
    #: contatori mirati annidati sotto `contatori`, come nel jsonb.
    ultime_pipeline: tuple[Mapping[str, Any], ...] | None = None
    #: Ultime righe del monitor di regime, con i contatori degli eventi.
    ultimi_monitor: tuple[Mapping[str, Any], ...] | None = None
    #: Righe di `pipeline_lock` (nome, proprietario, acquisito_at, scade_at).
    lock: tuple[Mapping[str, Any], ...] | None = None
    fermi_in_lavorazione: int | None = None
    ultimo_bando_nuovo_at: str | None = None
    #: La risposta di `monitoraggio_job_orario` (solo se `misurato`).
    job_orario: Mapping[str, Any] | None = None
    #: `{active_state, sub_state, n_restarts}` del servizio del produttore.
    servizio: Mapping[str, Any] | None = None
    #: La memoria di `sorveglia`: `{nrestarts: [[iso, n], ...], dal: {...}}`.
    memoria: Mapping[str, Any] | None = None
    # --- percorso A (§8 A, §19.6): None finche' nessuno li misura -----------
    da_verificare: Mapping[str, Any] | None = None
    letture_scadute: int | None = None
    #: `{estrattore: {letture, esiti}}` sommati sui 7 giorni.
    verifica_7g: Mapping[str, Mapping[str, Any]] | None = None
    vista_ms: float | None = None
    vista_ms_ruolo: str | None = None
    ultimi_import_indicepa: tuple[Mapping[str, Any], ...] | None = None
    ultime_verifiche: tuple[Mapping[str, Any], ...] | None = None
    ultimi_ingressi: tuple[Mapping[str, Any], ...] | None = None
    aperti_senza_scadenza: int | None = None
    verifica_stato_modalita: str = "ombra"
    verifica_stato_config_valida: bool = True
    # --- giro 3 (contratto `bandi-giro-3` §1, §3, §14) ----------------------
    #: `Settings.configurazione_scartate`: i NOMI delle variabili del giro 3
    #: fuori intervallo o fuori elenco (tornate al default). Mai i valori.
    configurazione_scartate: tuple[str, ...] = ()
    #: `Settings.variabili_dismesse`: i NOMI delle variabili dismesse ancora
    #: nel `.env`. Un'informazione, non un allarme.
    variabili_dismesse: tuple[str, ...] = ()
    #: `db.capacita_sospensioni()`: la migrazione 14 c'e'? None = non misurato.
    sospensioni_attive: bool | None = None
    #: `GEMELLI_MODALITA` e `DOMINI_MODALITA` (§18.8): la fusione prima della
    #: pubblicazione e l'import di IndicePA seguono questi interruttori, non
    #: quello della verifica.
    gemelli_modalita: str = "ombra"
    domini_modalita: str = "ombra"
    #: `transizioni_da_decidere` dell'ultima riga `backfill:rielaborazione`
    #: (§18.2): date che chiedono un cambio di stato, lasciate alla redazione.
    #: None = non misurato.
    transizioni_da_decidere: int | None = None
    #: Eventi marcati dalla 14 (`scartato_per`) per motivo: `{superato,
    #: transizione_non_ammessa}` (§19.2). None = non misurato.
    eventi_marcati: Mapping[str, int] | None = None


@dataclass(frozen=True)
class Salute:
    allarmi: tuple[str, ...] = ()
    avvisi: tuple[str, ...] = ()
    #: I tipi di evento che il monitor applica anche in ombra: non e' un
    #: giudizio, e' cio' che chi legge `salute` deve sapere per leggere il box.
    tipi_attivi: tuple[str, ...] = ()
    #: Le stesse voci di `allarmi` e `avvisi`, nello stesso ordine, con il codice.
    voci: tuple[Voce, ...] = ()
    #: La copertura dell'ultimo giro per passo (§1): `{passo: {candidati,
    #: fatti, rimasti, motivo_rimasti}}`, dalla riga piu' recente che la porta.
    copertura: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    #: Righe da mostrare che non sono ne' allarmi ne' avvisi (giro 3): la
    #: copertura per passo, le variabili dismesse, le sospensioni in attesa.
    informazioni: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        """1 se c'e' almeno un allarme: `salute` e' pensata per un supervisor."""
        return 1 if self.allarmi else 0

    def come_dizionario(self) -> dict[str, Any]:
        return {
            "allarmi": list(self.allarmi),
            "avvisi": list(self.avvisi),
            "exit_code": self.exit_code,
            "tipi_attivi": list(self.tipi_attivi),
            "voci": [asdict(voce) for voce in self.voci],
            "copertura": {passo: dict(valore) for passo, valore in self.copertura.items()},
            "informazioni": list(self.informazioni),
        }


def salute(stato: Stato, *, adesso: datetime | None = None) -> Salute:
    """Allarmi e avvisi dello stato corrente (§6.2, A24, M15). Funzione pura.

    Ogni ramo passa da `_voce` con un codice stabile (contratto `bandi-giro-2`
    §8): `allarmi` e `avvisi` restano gli stessi testi di prima, nello stesso
    ordine, e `voci` li ripete con il codice e la misura. `adesso` serve solo
    ai rami del giro 2 che guardano l'eta' di una riga; senza, vale l'ora
    corrente.
    """
    momento = adesso if adesso is not None else datetime.now(tz=timezone.utc)
    voci: list[Voce] = []

    if stato.ore_dall_ultimo_monitor_ok is not None and stato.ore_dall_ultimo_monitor_ok >= 24:
        _voce(voci, "monitor_fermo", LIVELLO_ALLARME,
              f"nessun monitor OK da {stato.ore_dall_ultimo_monitor_ok:.0f} h",
              stato.ore_dall_ultimo_monitor_ok)
    if stato.misure_db_errore:
        _voce(voci, "misure_non_disponibili", LIVELLO_ALLARME,
              f"misure sul DB non disponibili: {stato.misure_db_errore}")
    if stato.bandi_scraped_fermi:
        _voce(voci, "ingresso_fermo", LIVELLO_ALLARME,
              f"{stato.bandi_scraped_fermi} bandi fermi in scraped da oltre {ORE_SCRAPED_FERMO} ore: "
              f"ingresso bloccato (credito Anthropic esaurito o preprocess in errore)",
              stato.bandi_scraped_fermi)
    fallite = stato.classificazioni_fallite_ultimo_monitor or 0
    riuscite = stato.classificazioni_riuscite_ultimo_monitor or 0
    if fallite:
        testo = (f"classificazioni fallite nell'ultimo monitor: {fallite} su "
                 f"{fallite + riuscite} (credito Anthropic esaurito o API giu')")
        _voce(voci, "classificazione_non_disponibile",
              LIVELLO_ALLARME if fallite >= riuscite else LIVELLO_AVVISO, testo, fallite)
    if not stato.login_oe_ok:
        _voce(voci, "accesso_fonte_riservata", LIVELLO_ALLARME, "login Obiettivo Europa fallito")
    if stato.giri_consecutivi_a_tetto >= 2:
        motivo = f" (l'ultimo: {stato.motivo_ultimo_tetto})" if stato.motivo_ultimo_tetto else ""
        # Segnale di spesa: nel pannello niente numeri (decisione del 30/09 sera).
        _voce(voci, "limite_di_spesa", LIVELLO_ALLARME,
              f"tetto raggiunto in {stato.giri_consecutivi_a_tetto} giri consecutivi{motivo}")
    for lock in stato.lock_tenuti:
        # RIPRESA §3.2 punto 10: un lock orfano ferma tutti i giri successivi
        # fino alla scadenza, e fino al 26/09/2026 nessun controllo lo vedeva.
        testo = (f"lock «{lock.nome}» tenuto da «{lock.proprietario}» da "
                 f"{lock.minuti:.0f} min")
        soglia_allarme, soglia_avviso = LOCK_ALLARME_MIN, LOCK_AVVISO_MIN
        if lock.ttl_min:
            soglia_allarme = min(soglia_allarme, lock.ttl_min * 2 / 3)
            soglia_avviso = min(soglia_avviso, lock.ttl_min / 3)
        lavorazione = lavorazione_del_lock(lock.nome)
        if lock.minuti >= soglia_allarme:
            _voce(voci, f"lavorazione_orfana:{lavorazione}", LIVELLO_ALLARME,
                  f"{testo}: probabilmente orfano (lock_rilascia se nessun processo gira)",
                  lock.minuti)
        elif lock.minuti >= soglia_avviso:
            _voce(voci, f"lavorazione_lunga:{lavorazione}", LIVELLO_AVVISO, testo, lock.minuti)
    if stato.crediti_residui_quota is not None and stato.crediti_residui_quota < 0.15:
        _voce(voci, "credito_ricerca_basso", LIVELLO_ALLARME,
              f"crediti residui {stato.crediti_residui_quota:.0%} (< 15%)")
    if stato.consumo_mensile_quota is not None and stato.consumo_mensile_quota >= 0.80:
        _voce(voci, "consumo_mensile_alto", LIVELLO_ALLARME,
              f"consumo mensile {stato.consumo_mensile_quota:.0%} (>= 80%)")
    if stato.quota_in_verifica_nuovi is not None and stato.quota_in_verifica_nuovi > 0.30:
        _voce(voci, "fonti_da_verificare", LIVELLO_ALLARME,
              f"fonti in verifica sui nuovi {stato.quota_in_verifica_nuovi:.0%} (> 30%)",
              stato.quota_in_verifica_nuovi)
    if (stato.quota_schede_oe_con_sezione is not None
            and stato.quota_schede_oe_con_sezione < 0.80):
        # Avviso e non allarme (decisione del lead, 30/09): oggi nessuno la misura.
        _voce(voci, "schede_senza_sezione", LIVELLO_AVVISO,
              f"schede OE con sezione «Link e Documenti» {stato.quota_schede_oe_con_sezione:.0%} (< 80%)",
              stato.quota_schede_oe_con_sezione)
    if stato.quota_controlli_falliti is not None and stato.quota_controlli_falliti > 0.02:
        _voce(voci, "controlli_non_riusciti", LIVELLO_ALLARME,
              f"controlli falliti >= 5 sul {stato.quota_controlli_falliti:.0%} dei vivi (> 2%)",
              stato.quota_controlli_falliti)
    # A24: nessun cambio automatico di scenario, solo la proposta.
    if (stato.residuo_piano_su_tetto_mensile is not None
            and stato.residuo_piano_su_tetto_mensile < 3):
        _voce(voci, "scorta_piano_bassa", LIVELLO_ALLARME,
              "residuo del piano Firecrawl < 3x il tetto mensile: valutare MONITOR_SCENARIO=economico")
    # M15: la chiave IndexNow serve solo quando il monitor pubblica davvero:
    # in attivo, o in ombra con almeno un tipo attivo.
    if stato.modalita_monitor == "attivo" and not stato.indexnow_configurata:
        _voce(voci, "configurazione:modalita", LIVELLO_ALLARME,
              "INDEXNOW_API_KEY assente con MONITOR_MODALITA=attivo")
    elif stato.tipi_attivi and not stato.indexnow_configurata:
        _voce(voci, "configurazione:indicizzazione", LIVELLO_ALLARME,
              "INDEXNOW_API_KEY assente con MONITOR_TIPI_ATTIVI valorizzata")
    if stato.tipi_attivi_ignorati:
        _voce(voci, "configurazione:tipi_attivi", LIVELLO_ALLARME,
              "MONITOR_TIPI_ATTIVI contiene valori che il monitor non produce: "
              f"{', '.join(stato.tipi_attivi_ignorati)} (ignorati, quei tipi restano in ombra)")
    # M13: un `MONITOR_GIRI` che non coincide con le ore dello scheduler e' un
    # monitor spento in silenzio. Si dice subito, senza aspettare le 24 h di
    # «nessun monitor OK» (che oggi nessuno misura ancora).
    if not stato.monitor_giri_validi:
        _voce(voci, "configurazione:giri", LIVELLO_ALLARME,
              "MONITOR_GIRI contiene ore fuori dallo scheduler: voci ignorate, "
              "il monitor potrebbe non partire mai")
    # Giro 3 (§3): una variabile nuova fuori intervallo o fuori elenco torna al
    # default, e si dice. Il nome si', il valore mai.
    for nome in stato.configurazione_scartate:
        suffisso = str(nome).strip().lower()
        if suffisso in VARIABILI_GIRO_3:
            _voce(voci, f"configurazione:{suffisso}", LIVELLO_ALLARME,
                  f"{suffisso.upper()} non valida: vale il default")

    voci.extend(voci_sorveglianza(stato, momento))
    voci.extend(allarmi_verifica_stato(stato, momento))
    copertura_giro = copertura_dei_passi(stato.ultime_pipeline)
    voci.extend(voci_copertura(stato.ultime_pipeline))

    for modello in stato.modelli_fuori_listino:
        _voce(voci, "modello_fuori_listino", LIVELLO_AVVISO, f"modello non a listino: {modello}")
    if stato.non_misurati:
        _voce(voci, "non_misurato", LIVELLO_AVVISO,
              "non misurato da salute: " + ", ".join(stato.non_misurati))

    return Salute(
        tuple(v.testo_cli for v in voci if v.livello == LIVELLO_ALLARME),
        tuple(v.testo_cli for v in voci if v.livello == LIVELLO_AVVISO),
        tipi_attivi=tuple(stato.tipi_attivi),
        voci=tuple(voci),
        copertura=copertura_giro,
        informazioni=informazioni(stato, copertura_giro),
    )


# --- giro 3: copertura e informazioni (contratto `bandi-giro-3` §1, §3, §14) --

#: Quanti giri di fila con dei bandi lasciati fuori fanno `copertura_incompleta`.
GIRI_COPERTURA_INCOMPLETA = 4
#: L'informazione di `salute` finche' la migrazione 14 non c'e' (§3).
INFO_SOSPENSIONI_IN_ATTESA = "sospensioni in attesa della migrazione 14"


def _copertura_valida(valore: Any) -> dict[str, Any] | None:
    """La copertura di un passo, normalizzata, o None se non ha la forma di §1."""
    if not isinstance(valore, Mapping):
        return None
    if not all(isinstance(valore.get(k), (int, float)) and not isinstance(valore.get(k), bool)
               for k in ("candidati", "fatti", "rimasti")):
        return None
    motivo = valore.get("motivo_rimasti")
    return {"candidati": int(valore["candidati"]), "fatti": int(valore["fatti"]),
            "rimasti": int(valore["rimasti"]),
            "motivo_rimasti": motivo if isinstance(motivo, str) else None}


def _coperture_per_passo(
    righe: Sequence[Mapping[str, Any]] | None,
) -> dict[str, list[tuple[Mapping[str, Any], dict[str, Any]]]]:
    """Per ogni passo di `PASSI_NEUTRI`, le (riga, copertura) delle righe del
    giro eseguite che la portano, la piu' recente prima."""
    per_passo: dict[str, list[tuple[Mapping[str, Any], dict[str, Any]]]] = {}
    for riga in _eseguite(righe):
        for passo in PASSI_NEUTRI:
            valore = _copertura_valida(_passo(riga, passo).get("copertura"))
            if valore is not None:
                per_passo.setdefault(passo, []).append((riga, valore))
    return per_passo


def copertura_dei_passi(righe: Sequence[Mapping[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """La copertura piu' recente di ogni passo, nell'ordine di §2. Pura.

    Una riga di boot o un giro che non prevede il passo non porta la sua
    copertura: vale quella del giro piu' recente che l'ha.
    """
    per_passo = _coperture_per_passo(righe)
    return {passo: per_passo[passo][0][1] for passo in PASSI_NEUTRI if passo in per_passo}


def voci_copertura(righe: Sequence[Mapping[str, Any]] | None) -> list[Voce]:
    """`copertura_incompleta:<passo>`: rimasti > 0 nelle ultime 4 coperture del passo.

    Contano solo le righe del giro eseguite che portano la copertura di quel
    passo: il boot e i giri che il passo non fa si saltano, invece di
    azzerare il conto. La misura e' quanti bandi l'ultimo giro ha lasciato fuori.
    """
    voci: list[Voce] = []
    for passo, coperture in _coperture_per_passo(righe).items():
        ultime = [valore for _riga, valore in coperture[:GIRI_COPERTURA_INCOMPLETA]]
        if len(ultime) < GIRI_COPERTURA_INCOMPLETA or not all(v["rimasti"] > 0 for v in ultime):
            continue
        motivo = ultime[0]["motivo_rimasti"] or "senza motivo"
        _voce(voci, f"copertura_incompleta:{PASSI_NEUTRI[passo]}", LIVELLO_ALLARME,
              f"{passo}: bandi lasciati fuori in {GIRI_COPERTURA_INCOMPLETA} giri di fila "
              f"(l'ultimo: {ultime[0]['rimasti']} su {ultime[0]['candidati']}, {motivo})",
              ultime[0]["rimasti"])
    return voci


def informazioni(stato: Stato, copertura_giro: Mapping[str, Mapping[str, Any]]) -> tuple[str, ...]:
    """Le righe informative di `salute` (giro 3). Pura; mai valori del `.env`."""
    righe: list[str] = []
    for passo, valore in copertura_giro.items():
        testo = f"copertura {passo}: {valore['fatti']}/{valore['candidati']}"
        if valore["rimasti"]:
            testo += f" (rimasti {valore['rimasti']}: {valore['motivo_rimasti'] or 'senza motivo'})"
        righe.append(testo)
    if stato.variabili_dismesse:
        righe.append("variabili dismesse nel .env (non piu' lette): "
                     + ", ".join(sorted(str(n) for n in stato.variabili_dismesse)))
    if stato.sospensioni_attive is False:
        righe.append(INFO_SOSPENSIONI_IN_ATTESA)
    if stato.transizioni_da_decidere:
        righe.append(f"rielaborazione: {int(stato.transizioni_da_decidere)} transizioni di stato "
                     "da decidere nell'ultimo giro (rettifiche registrate e non applicate)")
    if stato.eventi_marcati is not None:
        superati = int(stato.eventi_marcati.get("superato") or 0)
        non_ammessi = int(stato.eventi_marcati.get("transizione_non_ammessa") or 0)
        if superati or non_ammessi:
            righe.append(f"eventi marcati e non applicati: {superati} superati, "
                         f"{non_ammessi} con transizione non ammessa")
    return tuple(righe)


# --- rami del giro 2 (§8): il produttore visto da fuori ----------------------

#: Le ore dello scheduler del sender (`settings.GIRI_SCHEDULER`), sempre
#: nell'ora di Roma: e' li' che gira il server, e il fuso va scritto, non
#: dedotto dall'orologio della macchina che misura.
GIRI_DI_REGIME: tuple[str, ...] = ("00:00", "06:00", "12:00", "18:00")
FUSO_SCHEDULER = ZoneInfo("Europe/Rome")
#: Il giro lanciato all'avvio del sender (`bandi_sender.GIRO_BOOT`).
GIRO_AVVIO = "boot"
#: Il lock del giro e la sua durata (`bandi_pipeline.LOCK_PIPELINE` e
#: `LOCK_TTL_S = 6 * 3600`: giro 3, §2, perche' i tempi dei passi della
#: manutenzione piu' la catena d'ingresso possono superare 5 ore).
LOCK_GIRO = "bandi_pipeline"
#: Il proprietario del lock del giro (`bandi_pipeline._proprietario`): pid del sender.
PROPRIETARIO_GIRO = "bandi_pipeline@"
ORE_TTL_LOCK_GIRO = 6
#: Nessun giro di regime completato da tante ore: ne e' saltato almeno uno.
ORE_PRODUTTORE_FERMO = 7
#: Oltre questa soglia l'allarme scatta anche con un giro in corso: un giro
#: vero non tiene il lock oltre il suo TTL.
ORE_PRODUTTORE_FERMO_COMUNQUE = ORE_PRODUTTORE_FERMO + ORE_TTL_LOCK_GIRO
#: Riavvii: almeno 3 giri di avvio, o NRestarts salito di 2, in 6 ore.
ORE_FINESTRA_RIAVVII = 6
MINIMO_AVVII_RIPETUTI = 3
MINIMO_AUMENTO_NRESTARTS = 2
#: Stati di systemd di un servizio che non sta girando.
STATI_SERVIZIO_FERMO: tuple[str, ...] = ("failed", "inactive")
#: La redazione e' degradata solo con almeno tanti bandi da scrivere e nessuna
#: scheda prodotta: un solo bando bloccato (il 772894, per 17 giri su 19) non
#: e' un passo guasto (decisione del lead, 30/09).
MINIMO_DA_REDIGERE = 3
#: Le fonti ad accesso riservato (`fonte_ufficiale.FONTI_OE`) e in quante
#: righe `pipeline` di fila devono risultare in errore.
FONTI_ACCESSO_RISERVATO: frozenset[int] = frozenset({449, 450, 451})
RIGHE_ACCESSO_RISERVATO = 2
#: Il job orario delle transizioni: nessun esito riuscito da 3 ore, o almeno
#: 2 fallimenti nelle ultime 24.
ORE_JOB_ORARIO = 3
FALLIMENTI_JOB_24H = 2


def _contatori(riga: Mapping[str, Any]) -> Mapping[str, Any]:
    contatori = riga.get("contatori")
    return contatori if isinstance(contatori, Mapping) else {}


def _passo(riga: Mapping[str, Any], nome: str) -> Mapping[str, Any]:
    """I contatori di uno step dentro la riga `pipeline` (`{}` se assenti)."""
    passo = _contatori(riga).get(nome)
    return passo if isinstance(passo, Mapping) else {}


def _saltata(riga: Mapping[str, Any]) -> bool:
    """Una riga senza step: saltata per lock o avvio saltato dopo un crash."""
    return riga.get("esito") == ESITO_SALTATO or bool(_contatori(riga).get("saltato_per_lock"))


_INIZIO_DEI_TEMPI = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _dalla_piu_recente(righe: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Righe ordinate per `avviato_at` e poi `id`, la piu' recente prima."""
    def chiave(riga: Mapping[str, Any]) -> tuple[datetime, float]:
        return (_istante(riga.get("avviato_at")) or _INIZIO_DEI_TEMPI, _numero(riga.get("id")))
    return sorted(righe, key=chiave, reverse=True)


def _eseguite(righe: Sequence[Mapping[str, Any]] | None) -> list[Mapping[str, Any]]:
    """Le righe non saltate, la piu' recente prima."""
    return [r for r in _dalla_piu_recente(righe or ()) if not _saltata(r)]


def _ultima_ora_di_schedulazione(adesso: datetime) -> datetime:
    """L'ultima ora di `GIRI_DI_REGIME` gia' passata, nell'ora di Roma."""
    locale = adesso.astimezone(FUSO_SCHEDULER)
    candidati = []
    for giorno in (locale.date(), locale.date() - timedelta(days=1)):
        for giro in GIRI_DI_REGIME:
            ore, minuti = (int(p) for p in giro.split(":"))
            istante = datetime(giorno.year, giorno.month, giorno.day, ore, minuti,
                               tzinfo=FUSO_SCHEDULER)
            if istante <= locale:
                candidati.append(istante)
    return max(candidati)


def _ore_dall_ultimo_giro(righe: Sequence[Mapping[str, Any]], adesso: datetime) -> float | None:
    """Ore dall'ultimo giro di regime completato (non saltato).

    Senza nessun giro completato fra le righe lette, il produttore e' fermo
    almeno da quando parte la finestra: si conta dalla riga piu' vecchia.
    """
    conclusi = [
        t for t in (_istante(r.get("concluso_at")) for r in righe
                    if r.get("giro") in GIRI_DI_REGIME and not _saltata(r))
        if t is not None
    ]
    if conclusi:
        ultimo = max(conclusi)
    else:
        avvii = [t for t in (_istante(r.get("avviato_at")) for r in righe) if t is not None]
        if not avvii:
            return None
        ultimo = min(avvii)
    return round(max(0.0, (adesso - ultimo).total_seconds() / 3600), 1)


def _giro_in_corso(lock: Sequence[Mapping[str, Any]] | None, adesso: datetime) -> bool:
    """Il lock del giro e' valido ed e' stato preso dopo l'ultima ora di schedulazione."""
    dal = _ultima_ora_di_schedulazione(adesso)
    for riga in lock or ():
        # Lo stesso nome lo prende anche `seo-rigenera` (proprietario
        # `seo-rigenera:cli`): quello non e' un giro in corso.
        if (riga.get("nome") != LOCK_GIRO
                or not str(riga.get("proprietario") or "").startswith(PROPRIETARIO_GIRO)):
            continue
        preso, scade = _istante(riga.get("acquisito_at")), _istante(riga.get("scade_at"))
        if preso is not None and scade is not None and scade > adesso and preso >= dal:
            return True
    return False


def _aumento_nrestarts(
    memoria: Mapping[str, Any] | None, servizio: Mapping[str, Any] | None, adesso: datetime,
) -> int | None:
    """Di quanto e' salito NRestarts nelle ultime 6 ore (None se non misurabile).

    La serie e' quella che `sorveglia` tiene in memoria, piu' il valore letto
    adesso. Si sommano solo gli aumenti: un `systemctl restart` a mano azzera
    il contatore, e un calo non e' un riavvio.
    """
    dal = adesso - timedelta(hours=ORE_FINESTRA_RIAVVII)
    serie: list[tuple[datetime, int]] = []
    voci = memoria.get("nrestarts") if isinstance(memoria, Mapping) else None
    for voce in voci if isinstance(voci, (list, tuple)) else ():
        if not isinstance(voce, (list, tuple)) or len(voce) != 2:
            continue
        quando = _istante(voce[0])
        if quando is not None and dal <= quando <= adesso:
            serie.append((quando, int(_numero(voce[1]))))
    if isinstance(servizio, Mapping) and servizio.get("n_restarts") is not None:
        serie.append((adesso, int(_numero(servizio.get("n_restarts")))))
    if len(serie) < 2:
        return None
    serie.sort(key=lambda punto: punto[0])
    return sum(max(0, dopo[1] - prima[1]) for prima, dopo in zip(serie, serie[1:]))


def _fonti_in_errore(riga: Mapping[str, Any]) -> frozenset[int] | None:
    """`scrape.fonti_in_errore` della riga, o None se la riga non lo porta."""
    valori = _passo(riga, "scrape").get("fonti_in_errore")
    if not isinstance(valori, (list, tuple)):
        return None
    return frozenset(
        int(v) for v in valori
        if (isinstance(v, int) and not isinstance(v, bool)) or (isinstance(v, str) and v.isdigit())
    )


def accesso_riservato_misurato(righe: Sequence[Mapping[str, Any]] | None) -> bool:
    """Le ultime righe eseguite portano tutte `fonti_in_errore`: il login si misura."""
    ultime = _eseguite(righe)[:RIGHE_ACCESSO_RISERVATO]
    return (len(ultime) == RIGHE_ACCESSO_RISERVATO
            and all(_fonti_in_errore(r) is not None for r in ultime))


def voci_sorveglianza(stato: Stato, adesso: datetime) -> list[Voce]:
    """I rami del giro 2 sul produttore (§8, percorso B). Funzione pura.

    Ogni ramo guarda un campo che resta None finche' nessuno lo misura: una
    fotografia di prima del giro 2 non produce voci nuove.
    """
    voci: list[Voce] = []
    righe = list(stato.ultime_pipeline or ())
    eseguite = _eseguite(righe)

    # produttore_fermo: nessun giro di regime completato da 7 h, salvo un giro
    # in corso partito dopo l'ultima ora di schedulazione; da 13 h comunque
    # (7 + `ORE_TTL_LOCK_GIRO`).
    if righe:
        ore = _ore_dall_ultimo_giro(righe, adesso)
        if ore is not None and ore >= ORE_PRODUTTORE_FERMO and (
                ore >= ORE_PRODUTTORE_FERMO_COMUNQUE or not _giro_in_corso(stato.lock, adesso)):
            _voce(voci, "produttore_fermo", LIVELLO_ALLARME,
                  f"nessun giro di regime completato da {ore:.0f} h", ore)

    # riavvii_ripetuti: le righe di avvio (anche saltate dopo un crash) e
    # l'aumento di NRestarts. Solo righe `pipeline`: il resolver scrive una
    # sua riga `boot` a ogni avvio (misure del giro 2).
    dal = adesso - timedelta(hours=ORE_FINESTRA_RIAVVII)
    avvii = sum(
        1 for r in righe
        if r.get("giro") == GIRO_AVVIO and r.get("step", "pipeline") == "pipeline"
        and (_istante(r.get("avviato_at")) or _INIZIO_DEI_TEMPI) >= dal
    )
    aumento = _aumento_nrestarts(stato.memoria, stato.servizio, adesso)
    if avvii >= MINIMO_AVVII_RIPETUTI or (aumento or 0) >= MINIMO_AUMENTO_NRESTARTS:
        pezzi = []
        if avvii >= MINIMO_AVVII_RIPETUTI:
            pezzi.append(f"{avvii} giri di avvio")
        if (aumento or 0) >= MINIMO_AUMENTO_NRESTARTS:
            pezzi.append(f"NRestarts +{aumento}")
        _voce(voci, "riavvii_ripetuti", LIVELLO_ALLARME,
              f"riavvii ripetuti del sender in {ORE_FINESTRA_RIAVVII} h: {', '.join(pezzi)}",
              max(avvii, aumento or 0))

    if stato.servizio is not None:
        attivo = str(stato.servizio.get("active_state") or "").lower()
        sotto = str(stato.servizio.get("sub_state") or "").lower()
        if attivo in STATI_SERVIZIO_FERMO or (attivo == "activating" and sotto == "auto-restart"):
            _voce(voci, "servizio_non_attivo", LIVELLO_ALLARME,
                  f"servizio del sender non attivo: {attivo or '?'}/{sotto or '?'}")

    if eseguite:
        ultima = eseguite[0]
        preprocess = _passo(ultima, "preprocess")
        errori, lavorati = _numero(preprocess.get("errors")), _numero(preprocess.get("processed_total"))
        if lavorati > 0 and errori == lavorati:
            _voce(voci, "passo_degradato:estrazione", LIVELLO_ALLARME,
                  f"preprocess: {errori:.0f} errori su {lavorati:.0f} bandi nell'ultimo giro",
                  int(errori))
        enrich = _passo(ultima, "enrich")
        arricchiti = _numero(enrich.get("enriched_total"))
        # `enriched_db_ok` compare solo con `enriched_total > 0`: assente vale 0.
        if arricchiti > 0 and _numero(enrich.get("enriched_db_ok")) == 0:
            _voce(voci, "passo_degradato:arricchimento", LIVELLO_ALLARME,
                  f"enrich: {arricchiti:.0f} bandi arricchiti e nessuno salvato nell'ultimo giro",
                  int(arricchiti))
        seo = _passo(ultima, "seo")
        # `doppioni_oe` manca sulle righe di prima del 30/09 sera: vale 0. Le
        # righe trattenute dalla sosta (§5.10) non si redigono per scelta solo
        # con la verifica attiva, quelle fuse con un gemello solo con i gemelli
        # attivi (§18.8): in ombra la SEO le redige lo stesso, e toglierle
        # nasconderebbe un guasto vero.
        chiavi = contatori_seo_non_da_redigere(stato)
        da_redigere = _numero(seo.get("selected")) - sum(_numero(seo.get(chiave)) for chiave in chiavi)
        if da_redigere >= MINIMO_DA_REDIGERE and _numero(seo.get("payload_ok")) == 0:
            _voce(voci, "passo_degradato:redazione", LIVELLO_ALLARME,
                  f"seo: {da_redigere:.0f} bandi da redigere e nessuna scheda prodotta "
                  "nell'ultimo giro", int(da_redigere))
        # ingresso_guasto: fonti tentate = processate + in errore (misure M6).
        scrape = _passo(ultima, "scrape")
        in_errore = _numero(scrape.get("fonti_errors"))
        if (in_errore > 0 and scrape.get("fonti_processate") is not None
                and _numero(scrape.get("fonti_processate")) == 0):
            _voce(voci, "ingresso_guasto", LIVELLO_ALLARME,
                  f"scrape: tutte le {in_errore:.0f} fonti tentate in errore nell'ultimo giro",
                  int(in_errore))

    if stato.fermi_in_lavorazione:
        _voce(voci, "fermi_in_lavorazione", LIVELLO_AVVISO,
              f"{stato.fermi_in_lavorazione} bandi fermi in processed o enriched da oltre "
              f"{ORE_SCRAPED_FERMO} ore", stato.fermi_in_lavorazione)

    # accesso_fonte_riservata: una fonte OE in errore in tutte e due le ultime
    # righe eseguite (un errore isolato e' un sito giu', due di fila no). Se
    # c'e' gia' la voce del login, non si ripete.
    ultime = eseguite[:RIGHE_ACCESSO_RISERVATO]
    if stato.login_oe_ok and accesso_riservato_misurato(righe):
        per_riga = [(_fonti_in_errore(r) or frozenset()) & FONTI_ACCESSO_RISERVATO for r in ultime]
        if all(per_riga):
            fonti = sorted(per_riga[0])
            _voce(voci, "accesso_fonte_riservata", LIVELLO_ALLARME,
                  f"fonti ad accesso riservato in errore negli ultimi {len(ultime)} giri: "
                  f"{', '.join(str(f) for f in fonti)}", len(fonti))

    monitor = _eseguite(stato.ultimi_monitor)
    contatori_monitor = _contatori(monitor[0]) if monitor else {}
    if monitor:
        non_applicati = int(_numero(contatori_monitor.get("eventi_non_applicati")))
        if non_applicati > 0:
            _voce(voci, "eventi_non_applicati", LIVELLO_ALLARME,
                  f"eventi ammessi e non applicati nell'ultimo monitor: {non_applicati}",
                  non_applicati)
    # Gli eventi li scrivono due produttori: il monitor e il passo
    # verifica-stato (ultima riga della fase controlli, `ultime_verifiche`).
    verifiche = [r for r in _eseguite(stato.ultime_verifiche) if _fase_controlli(r)]
    contatori_verifica = _contatori(verifiche[0]) if verifiche else {}
    _voce_per_produttore(voci, "eventi_non_scritti", LIVELLO_ALLARME, "eventi non scritti",
                         int(_numero(contatori_monitor.get("eventi_non_scritti"))),
                         int(_numero(contatori_verifica.get("eventi_non_scritti"))))
    # Applicati alle colonne ma senza cursore: la pagina e' cambiata, il box
    # «Aggiornamenti» no. Li riprende `applica-eventi --attivo`: e' un avviso.
    _voce_per_produttore(voci, "eventi_non_leggibili", LIVELLO_AVVISO, "eventi applicati e non resi leggibili",
                         int(_numero(contatori_monitor.get("eventi_invisibili"))),
                         int(_numero(contatori_verifica.get("eventi_non_leggibili"))))

    # passi_ripetuti_non_ok: lo stesso passo non ok nelle due ultime righe eseguite.
    if len(eseguite) >= 2:
        coppia = [_contatori(r).get("passi_non_ok") for r in eseguite[:2]]
        if all(isinstance(p, (list, tuple)) for p in coppia):
            ripetuti = sorted({str(p) for p in coppia[0]} & {str(p) for p in coppia[1]})
            if ripetuti:
                _voce(voci, "passi_ripetuti_non_ok", LIVELLO_ALLARME,
                      f"passi non ok in due giri consecutivi: {', '.join(ripetuti)}",
                      len(ripetuti))

    job = stato.job_orario
    if isinstance(job, Mapping) and job.get("misurato"):
        ultimo_ok = _istante(job.get("ultimo_ok_at"))
        ore_ok = (round(max(0.0, (adesso - ultimo_ok).total_seconds() / 3600), 1)
                  if ultimo_ok is not None else None)
        falliti = int(_numero(job.get("falliti_24h")))
        pezzi = []
        if ore_ok is None:
            pezzi.append("nessun esito riuscito registrato")
        elif ore_ok >= ORE_JOB_ORARIO:
            pezzi.append(f"nessun esito riuscito da {ore_ok:.0f} h")
        if falliti >= FALLIMENTI_JOB_24H:
            pezzi.append(f"{falliti} fallimenti in 24 h")
        if pezzi:
            _voce(voci, "job_orario", LIVELLO_ALLARME,
                  f"job orario delle transizioni: {', '.join(pezzi)}", ore_ok)

    return voci


# --- percorso A (§8 A e §19.6): il passo verifica-stato visto da fuori -------

#: Nessun passo di verifica riuscito da tante ore: ne sono saltati quattro.
#: I contatori della seo che tolgono righe da `selected` senza che sia un
#: guasto: doppioni OE (sempre, per primi), sosta dell'ingresso (solo con
#: VERIFICA_STATO_MODALITA=attivo) e fusioni con un gemello (solo con
#: GEMELLI_MODALITA=attivo, giro 3 §11 e §18.8).
CONTATORI_SEO_NON_DA_REDIGERE: tuple[str, ...] = (
    "doppioni_oe", "trattenuti", "trattenuti_senza_appiglio",
    "fusi_prima_della_pubblicazione", "fusioni_non_riuscite",
)
CONTATORI_SEO_SOSTA: tuple[str, ...] = ("trattenuti", "trattenuti_senza_appiglio")
CONTATORI_SEO_FUSIONI: tuple[str, ...] = ("fusi_prima_della_pubblicazione", "fusioni_non_riuscite")


def contatori_seo_non_da_redigere(stato: Stato) -> tuple[str, ...]:
    """Le chiavi di `CONTATORI_SEO_NON_DA_REDIGERE` che valgono con le
    modalita' dello stato: ognuna segue il proprio interruttore."""
    chiavi = list(CONTATORI_SEO_NON_DA_REDIGERE[:1])
    if stato.verifica_stato_modalita == "attivo":
        chiavi.extend(CONTATORI_SEO_SOSTA)
    if stato.gemelli_modalita == "attivo":
        chiavi.extend(CONTATORI_SEO_FUSIONI)
    return tuple(chiavi)
ORE_VERIFICA_FERMA = 26
#: Un estrattore con almeno tante letture e nessun esito in 7 giorni e' muto.
MINIMO_LETTURE_MUTO = 5
#: Quota di «senza_conferma» sugli aperti senza scadenza oltre cui si avvisa.
SOGLIA_QUOTA_SENZA_CONFERMA = 0.60
#: Righe senza appiglio trattenute nell'ultimo giro, e quota dei rilasciati a
#: tempo sui trattenuti dei 7 giorni, oltre cui si avvisa.
SOGLIA_SENZA_APPIGLIO = 10
#: Rilasciati a tempo nei 7 giorni oltre i quali la sosta e' un collo di
#: bottiglia (revisione avversaria: il rapporto coi trattenuti, contati a ogni
#: giro, non superava mai il 25%).
SOGLIA_RILASCIATI_7G = 10
#: IndicePA: ultimo import riuscito, soglie di sanita' dell'ultimo import.
GIORNI_INDICEPA = 40
SOGLIA_RIGHE_INDICEPA = 15_000
SOGLIA_QUOTA_ESCLUSI_INDICEPA = 0.20
#: La lettura di prova della vista pubblica, in millisecondi.
SOGLIA_VISTA_MS = 2000.0
MOTIVO_MIGRAZIONE_ASSENTE = "migrazione_assente"
#: In ombra resta accesa anche con la 13 applicata: l'etichetta non deve far
#: pensare che manchi la migrazione (nota di db, #117).
NON_MISURATO_DA_VERIFICARE = "stato da verificare (verifica non attiva o migrazione 13 assente)"


def _voce_per_produttore(voci: list[Voce], codice: str, livello: str, cosa: str,
                         nel_monitor: int, nella_verifica: int) -> None:
    """Una voce sola per il monitor e il passo verifica-stato, con la somma come misura."""
    totale = max(0, nel_monitor) + max(0, nella_verifica)
    if totale <= 0:
        return
    pezzi = []
    if nel_monitor > 0:
        pezzi.append(f"nell'ultimo monitor: {nel_monitor}")
    if nella_verifica > 0:
        pezzi.append(f"nell'ultima verifica dello stato: {nella_verifica}")
    _voce(voci, codice, livello, f"{cosa} {'; '.join(pezzi)}", totale)


def _fase_controlli(riga: Mapping[str, Any]) -> bool:
    return _contatori(riga).get("fase") in (None, "controlli")


def allarmi_verifica_stato(stato: Stato, adesso: datetime) -> list[Voce]:
    """I codici del percorso A (§8 A e §19.6). Funzione pura.

    Come `voci_sorveglianza`: ogni ramo guarda un campo che resta None finche'
    nessuno lo misura, quindi una fotografia senza le misure A non produce voci.
    """
    voci: list[Voce] = []

    if not stato.verifica_stato_config_valida:
        _voce(voci, "configurazione:verifica_stato", LIVELLO_ALLARME,
              "VERIFICA_STATO_* / INGRESSO_* / GEMELLI_* / INDICEPA_URL con valori non validi: "
              "tornati al default")

    verifiche = [r for r in _dalla_piu_recente(stato.ultime_verifiche or ()) if _fase_controlli(r)]
    if stato.ultime_verifiche is not None and not verifiche:
        # Nessuna riga del passo: dopo un deploy il primo giro dei controlli
        # (06 o 18) puo' essere lontano fino a 11 ore. Non e' un guasto: avviso
        # (revisione #108).
        _voce(voci, "verifica_stato_ferma", LIVELLO_AVVISO, "verifica dello stato non ancora eseguita")
    elif stato.ultime_verifiche is not None:
        dal = adesso - timedelta(hours=ORE_VERIFICA_FERMA)
        ultima = verifiche[0] if verifiche else None
        saltata_per_migrazione = (ultima is not None and ultima.get("esito") == ESITO_SALTATO
                                  and _contatori(ultima).get("motivo_saltato") == MOTIVO_MIGRAZIONE_ASSENTE)
        # Un giro fermato dal tetto di tempo e' un passo vivo: conta come riuscito.
        riuscite = [t for t in (_istante(r.get("concluso_at")) or _istante(r.get("avviato_at"))
                                for r in verifiche if r.get("esito") in (ESITO_OK, ESITO_INTERROTTO)) if t is not None]
        if not saltata_per_migrazione and not any(t >= dal for t in riuscite):
            dall_ultima = max(riuscite, default=None)
            ore = (round(max(0.0, (adesso - dall_ultima).total_seconds() / 3600), 1)
                   if dall_ultima is not None else None)
            testo = (f"verifica dello stato ferma: nessun passo riuscito da {ore:.0f} h" if ore is not None
                     else "verifica dello stato ferma: nessun passo riuscito registrato")
            _voce(voci, "verifica_stato_ferma", LIVELLO_ALLARME, testo, ore)

    if stato.letture_scadute:
        _voce(voci, "leggibile_non_letto", LIVELLO_AVVISO,
              f"{stato.letture_scadute} bandi con una pagina leggibile non riletti da oltre 16 giorni",
              stato.letture_scadute)

    if verifiche:
        contatori = _contatori(verifiche[0])
        non_verificanti = int(_numero(contatori.get("letture_non_verificanti")))
        if non_verificanti > 0:
            _voce(voci, "lettura_non_verificante", LIVELLO_AVVISO,
                  f"{non_verificanti} letture su pagine non verificanti nell'ultimo passo", non_verificanti)
        freno = contatori.get("trattenute_per_freno")
        for chiave, n in sorted((freno or {}).items() if isinstance(freno, Mapping) else ()):
            if chiave in ESTRATTORI_SALUTE and int(_numero(n)) > 0:
                _voce(voci, f"freno_chiusure:{chiave}", LIVELLO_AVVISO,
                      f"chiusure del lettore {chiave} trattenute dal freno: {int(_numero(n))}",
                      int(_numero(n)))

    if stato.verifica_7g is not None:
        for chiave, valori in sorted(stato.verifica_7g.items()):
            if chiave not in ESTRATTORI_SALUTE or not isinstance(valori, Mapping):
                continue
            letture, esiti = int(_numero(valori.get("letture"))), int(_numero(valori.get("esiti")))
            if letture >= MINIMO_LETTURE_MUTO and esiti == 0:
                _voce(voci, f"estrattore_muto:{chiave}", LIVELLO_ALLARME,
                      f"lettore {chiave} muto: {letture} letture e nessun esito in 7 giorni", letture)

    prosa = 0
    monitor = _eseguite(stato.ultimi_monitor)
    if monitor:
        prosa += int(_numero(_contatori(monitor[0]).get("prosa_non_riscritta")))
    if verifiche:
        prosa += int(_numero(_contatori(verifiche[0]).get("prosa_non_riscritta")))
    if prosa > 0:
        _voce(voci, "prosa_non_riscritta", LIVELLO_AVVISO,
              f"{prosa} schede con date applicate e prosa non riscritta (monitor o verifica)", prosa)

    da_verificare = stato.da_verificare
    if isinstance(da_verificare, Mapping) and stato.aperti_senza_scadenza:
        aperto = da_verificare.get("aperto")
        senza = int(_numero(aperto.get("senza_conferma"))) if isinstance(aperto, Mapping) else 0
        quota = senza / stato.aperti_senza_scadenza
        if quota > SOGLIA_QUOTA_SENZA_CONFERMA:
            _voce(voci, "aperti_senza_conferma", LIVELLO_AVVISO,
                  f"aperti senza conferma {quota:.0%} degli aperti senza scadenza (> 60%)", round(quota, 3))

    ingressi = _dalla_piu_recente(stato.ultimi_ingressi or ())
    if ingressi:
        senza_appiglio = int(_numero(_contatori(ingressi[0]).get("trattenuti_senza_appiglio")))
        rilasciati = int(sum(_numero(_contatori(r).get("rilasciati_a_tempo")) for r in ingressi))
        pezzi, misure = [], []
        if senza_appiglio > SOGLIA_SENZA_APPIGLIO:
            pezzi.append(f"{senza_appiglio} righe senza appiglio trattenute")
            misure.append(senza_appiglio)
        if rilasciati > SOGLIA_RILASCIATI_7G:
            pezzi.append(f"{rilasciati} bandi rilasciati a tempo in 7 giorni")
            misure.append(rilasciati)
        if pezzi:
            _voce(voci, "ingresso_trattenuti", LIVELLO_AVVISO, "ingresso: " + "; ".join(pezzi), max(misure))

    if stato.ultimi_import_indicepa is not None:
        # La scrittura dei domini segue DOMINI_MODALITA (§18.8): solo con i
        # domini attivi un import in ombra non e' riuscito.
        riusciti_ammessi = ("ok", "ombra") if stato.domini_modalita != "attivo" else ("ok",)
        imports = _dalla_piu_recente(stato.ultimi_import_indicepa)
        riusciti = [
            t for t in (_istante(_contatori(r).get("indicepa_at")) or _istante(r.get("concluso_at"))
                        for r in imports if _contatori(r).get("indicepa_esito") in riusciti_ammessi)
            if t is not None]
        ultimo = max(riusciti, default=None)
        if ultimo is None or adesso - ultimo > timedelta(days=GIORNI_INDICEPA):
            _voce(voci, "indicepa_non_aggiornato", LIVELLO_AVVISO,
                  "IndicePA: nessun import riuscito da oltre 40 giorni" if ultimo is not None
                  else "IndicePA: nessun import riuscito registrato")
        if imports:
            contatori = _contatori(imports[0])
            lette = _numero(contatori.get("indicepa_righe_lette"))
            utili = contatori.get("indicepa_righe_utili")
            esclusi = contatori.get("indicepa_esclusi")
            quota_esclusi = (sum(_numero(v) for v in esclusi.values()) / lette
                             if isinstance(esclusi, Mapping) and lette > 0 else 0.0)
            anomalo = (contatori.get("indicepa_esito") == "anomalo"
                       or (utili is not None and _numero(utili) < SOGLIA_RIGHE_INDICEPA)
                       or quota_esclusi > SOGLIA_QUOTA_ESCLUSI_INDICEPA)
            if anomalo:
                _voce(voci, "indicepa_import_anomalo", LIVELLO_AVVISO,
                      f"IndicePA: ultimo import anomalo (righe utili {int(_numero(utili))}, "
                      f"esclusi {quota_esclusi:.0%})")

    if stato.vista_ms is not None and stato.vista_ms > SOGLIA_VISTA_MS:
        # Solo come anon la misura e' quella che paga il sito: con la service
        # key la RLS non c'e', e la lentezza e' un indizio, non un guasto.
        livello = LIVELLO_ALLARME if stato.vista_ms_ruolo == "anon" else LIVELLO_AVVISO
        _voce(voci, "vista_lenta", livello,
              f"vista bando_pubblico lenta: {stato.vista_ms:.0f} ms come {stato.vista_ms_ruolo or '?'} "
              f"(> {SOGLIA_VISTA_MS:.0f})")
    return voci


_FRAZIONE_RE = re.compile(r"\.(\d+)")


def _istante(valore: Any) -> datetime | None:
    """`timestamptz` di PostgREST -> datetime aware (None se illeggibile).

    `fromisoformat` di Python 3.10 non accetta la «Z» ne' le frazioni con meno
    di sei cifre («…12.87927+00:00»), che PostgREST restituisce: si portano a
    sei cifre, come `lock_orfani.istante`.
    """
    if isinstance(valore, datetime):
        return valore if valore.tzinfo else valore.replace(tzinfo=timezone.utc)
    if not valore:
        return None
    testo = str(valore).strip().replace("Z", "+00:00").replace(" ", "T", 1)
    testo = _FRAZIONE_RE.sub(lambda m: "." + (m.group(1) + "000000")[:6], testo, count=1)
    try:
        letto = datetime.fromisoformat(testo)
    except ValueError:
        return None
    return letto if letto.tzinfo else letto.replace(tzinfo=timezone.utc)


def _numero(valore: Any) -> float:
    try:
        return float(valore or 0)
    except (TypeError, ValueError):
        return 0.0


def _motivo_del_tetto(riga: Mapping[str, Any]) -> str:
    """Il motivo di un giro a tetto: la colonna, o quello dello step che l'ha preso.

    La riga `pipeline` di un giro fermato dal monitor ha `motivo` vuoto e il
    motivo vero dentro `contatori.monitor.motivo`.
    """
    if riga.get("motivo"):
        return str(riga["motivo"])
    contatori = riga.get("contatori")
    if isinstance(contatori, Mapping):
        for valore in contatori.values():
            if isinstance(valore, Mapping) and valore.get("motivo"):
                return str(valore["motivo"])
    return ""


#: Un bando `scraped` da piu' di tante ore ha saltato almeno due giri (uno ogni
#: 6 ore): non e' un bando appena entrato, e' un ingresso fermo.
ORE_SCRAPED_FERMO = 13


def _classificazioni(riga: Mapping[str, Any]) -> tuple[int, int]:
    """(fallite, riuscite) di un giro di monitor.

    Il contatore delle fallite esiste dal 28/09/2026, e da allora
    `classificazioni` conta solo le riuscite. Sulle righe precedenti vale la
    firma che RIPRESA §4.2 indicava come unico indizio: classificazioni tentate
    e costo zero, perche' una chiamata riuscita a un modello a listino costa
    sempre qualcosa.
    """
    classificazioni = int(_numero(riga.get("classificazioni")))
    fallite = riga.get("classificazioni_fallite")
    if fallite is not None:
        # Le pagine con Haiku riuscito e Sonnet fallito stanno in tutti e due i
        # contatori: fra le riuscite non vanno contate.
        doppie = int(_numero(riga.get("seconde_opinioni_fallite")))
        return int(_numero(fallite)), max(0, classificazioni - doppie)
    if classificazioni > 0 and riga.get("usd") is not None and _numero(riga.get("usd")) == 0:
        return classificazioni, 0
    return 0, classificazioni


def _giri_a_tetto(righe: list[Mapping[str, Any]]) -> int:
    """Quante righe, dalla piu' recente, sono state fermate da un tetto."""
    consecutivi = 0
    for riga in righe:
        if not (riga.get("interrotto_per_tetto") or riga.get("esito") == ESITO_INTERROTTO):
            break
        consecutivi += 1
    return consecutivi


def stato_da_misure(
    misure: Mapping[str, Any],
    *,
    adesso: datetime,
    tetto_crediti_mese: float = 0,
    tetto_usd_mese: float = 0.0,
) -> dict[str, Any]:
    """Campi di `Stato` dalle righe lette da `db.misure_salute`. Funzione pura.

    Una chiave assente o `None` in `misure` vuol dire «tabella non disponibile»:
    il campo resta `None` (nessun allarme) e la voce finisce in `non_misurati`,
    cosi' un exit 0 non promette piu' di quello che ha controllato.

    - `monitor`: righe del monitor **di regime** (`giro` valorizzato), recenti
      prima. Un giro lanciato a mano con `--forza` non prova che lo scheduler
      funzioni;
    - `pipeline`: righe `step='pipeline'`, recenti prima;
    - `nuovi`: pubblicati negli ultimi `GIORNI_NUOVI` giorni, con lo stato della fonte;
    - `vivi`: id dei pubblicati non chiusi; `falliti`: id con `controlli_falliti`
      oltre soglia;
    - `mese`: `step`, `crediti`, `usd` delle righe del mese di calendario romano;
    - `lock`: righe di `pipeline_lock`;
    - giro 2 (§14): `ultime_pipeline` e `ultimi_monitor` (contatori mirati
      annidati sotto `contatori`), `fermi_in_lavorazione` (un conteggio),
      `ultimo_bando_nuovo_at`; e, aggiunte da chi fotografa, `servizio`,
      `job_orario` e `memoria`.
    """
    campi: dict[str, Any] = {}
    non_misurati: list[str] = list(NON_MISURABILI_DAL_DB)

    monitor = misure.get("monitor")
    if monitor:
        ok = next((r for r in monitor if r.get("esito") == ESITO_OK), None)
        if ok is not None:
            quando = _istante(ok.get("concluso_at")) or _istante(ok.get("avviato_at"))
        else:
            # Nessun OK fra le righe lette: il monitor e' fermo almeno da
            # quando parte la finestra.
            quando = min((t for t in (_istante(r.get("avviato_at")) for r in monitor) if t),
                         default=None)
        if quando is not None:
            campi["ore_dall_ultimo_monitor_ok"] = round(
                max(0.0, (adesso - quando).total_seconds() / 3600), 1)
        # L'ultimo giro che ha provato a classificare: uno fermato dal tetto o
        # senza pagine cambiate non dice niente sul credito, e leggerlo
        # spegnerebbe l'allarme senza che niente sia cambiato.
        provato = next((r for r in monitor if sum(_classificazioni(r)) > 0), None)
        fallite, riuscite = _classificazioni(provato) if provato is not None else (0, 0)
        campi["classificazioni_fallite_ultimo_monitor"] = fallite
        campi["classificazioni_riuscite_ultimo_monitor"] = riuscite
    else:
        non_misurati.append("monitor di regime (nessun giro registrato)")

    # Giri a tetto: sulle righe del giro e su quelle del monitor di regime. Il
    # monitor gira solo alle 06 e alle 18, quindi fra i suoi due giri a tetto del
    # 25/09 il giro delle 12 (senza monitor) azzerava il conto sulle righe `pipeline`.
    pipeline = misure.get("pipeline")
    if pipeline is not None or monitor is not None:
        serie = [s for s in (pipeline or [], monitor or []) if s]
        migliore = max(serie, key=_giri_a_tetto, default=[])
        consecutivi = _giri_a_tetto(migliore)
        campi["giri_consecutivi_a_tetto"] = consecutivi
        if consecutivi:
            campi["motivo_ultimo_tetto"] = _motivo_del_tetto(migliore[0])
    else:
        non_misurati.append("giri a tetto")

    nuovi = misure.get("nuovi")
    if nuovi is not None and len(nuovi) >= MINIMO_NUOVI:
        in_verifica = sum(1 for r in nuovi if r.get("fonte_ufficiale_stato") == "in_verifica")
        campi["quota_in_verifica_nuovi"] = in_verifica / len(nuovi)
    else:
        non_misurati.append(
            f"fonti in verifica sui nuovi (meno di {MINIMO_NUOVI} pubblicati "
            f"in {GIORNI_NUOVI} giorni)" if nuovi is not None else "fonti in verifica sui nuovi")

    vivi, falliti = misure.get("vivi"), misure.get("falliti")
    if vivi and falliti is not None:
        insieme_vivi = set(vivi)
        bloccati = sum(1 for bando_id in set(falliti) if bando_id in insieme_vivi)
        campi["quota_controlli_falliti"] = bloccati / len(insieme_vivi)
    else:
        non_misurati.append("controlli falliti")

    mese = misure.get("mese")
    if mese is not None and (tetto_crediti_mese > 0 or tetto_usd_mese > 0):
        # Fuori i lotti (M19) e la riga del giro, che risomma gli step.
        regime = [r for r in mese if conta_nel_regime(str(r.get("step") or ""))]
        quote = []
        if tetto_crediti_mese > 0:
            quote.append(sum(_numero(r.get("crediti")) for r in regime) / tetto_crediti_mese)
        if tetto_usd_mese > 0:
            quote.append(sum(_numero(r.get("usd")) for r in regime) / tetto_usd_mese)
        campi["consumo_mensile_quota"] = max(quote)
    else:
        non_misurati.append("consumo mensile")

    fermi = misure.get("scraped_fermi")
    if fermi is not None:
        campi["bandi_scraped_fermi"] = len(fermi)
    else:
        non_misurati.append("bandi fermi in scraped")

    lock = misure.get("lock")
    if lock is not None:
        tenuti = []
        for riga in lock:
            scade, preso = _istante(riga.get("scade_at")), _istante(riga.get("acquisito_at"))
            if scade is None or preso is None or scade <= adesso:
                continue
            tenuti.append(LockTenuto(
                nome=str(riga.get("nome") or ""),
                proprietario=str(riga.get("proprietario") or ""),
                minuti=round((adesso - preso).total_seconds() / 60, 1),
                ttl_min=round((scade - preso).total_seconds() / 60, 1),
            ))
        campi["lock_tenuti"] = tuple(tenuti)
        campi["lock"] = tuple(lock)
    else:
        non_misurati.append("lock di esecuzione")

    # --- giro 2 (§8, §14): righe grezze per `voci_sorveglianza` -------------
    ultime = misure.get("ultime_pipeline")
    if ultime is not None:
        campi["ultime_pipeline"] = tuple(ultime)
        if not ultime:
            non_misurati.append("giri del produttore (nessun giro registrato)")
        elif accesso_riservato_misurato(ultime):
            # Le fonti OE in errore si leggono nelle righe: il login e' misurato.
            non_misurati.remove(NON_MISURATO_ACCESSO_RISERVATO)
    else:
        non_misurati.append("giri del produttore")

    ultimi_monitor = misure.get("ultimi_monitor")
    if ultimi_monitor is not None:
        campi["ultimi_monitor"] = tuple(ultimi_monitor)
    else:
        non_misurati.append("eventi dell'ultimo monitor")

    in_lavorazione = misure.get("fermi_in_lavorazione")
    if in_lavorazione is not None:
        campi["fermi_in_lavorazione"] = (
            len(in_lavorazione) if isinstance(in_lavorazione, (list, tuple))
            else int(_numero(in_lavorazione)))
    else:
        non_misurati.append("bandi fermi in lavorazione")
    if misure.get("ultimo_bando_nuovo_at") is not None:
        campi["ultimo_bando_nuovo_at"] = str(misure["ultimo_bando_nuovo_at"])

    # Queste tre non vengono da `db.misure_salute`: le aggiunge chi fotografa
    # (`sorveglianza.fotografa`) prima di chiamare questa funzione.
    servizio = misure.get("servizio")
    if isinstance(servizio, Mapping) and servizio.get("active_state"):
        campi["servizio"] = dict(servizio)
    else:
        non_misurati.append(NON_MISURATO_SERVIZIO)
    job = misure.get("job_orario")
    if isinstance(job, Mapping) and job.get("misurato"):
        campi["job_orario"] = dict(job)
    else:
        non_misurati.append(NON_MISURATO_JOB_ORARIO)
    memoria = misure.get("memoria")
    if isinstance(memoria, Mapping):
        campi["memoria"] = dict(memoria)

    # --- percorso A (§8 A, §19.6): le misure della 13 e del passo ------------
    da_verificare = misure.get("da_verificare")
    if isinstance(da_verificare, Mapping):
        campi["da_verificare"] = dict(da_verificare)
    else:
        non_misurati.append(NON_MISURATO_DA_VERIFICARE)
    for chiave in ("letture_scadute", "aperti_senza_scadenza"):
        if misure.get(chiave) is not None:
            campi[chiave] = int(_numero(misure[chiave]))
    if isinstance(misure.get("verifica_7g"), Mapping):
        campi["verifica_7g"] = dict(misure["verifica_7g"])
    if misure.get("vista_ms") is not None:
        campi["vista_ms"] = _numero(misure["vista_ms"])
        campi["vista_ms_ruolo"] = str(misure.get("vista_ms_ruolo") or "")
    for chiave in ("ultimi_import_indicepa", "ultime_verifiche", "ultimi_ingressi"):
        if misure.get(chiave) is not None:
            campi[chiave] = tuple(misure[chiave])

    campi["non_misurati"] = tuple(non_misurati)
    return campi


def righe_allarme(salute_corrente: Salute) -> tuple[str, ...]:
    """Righe pronte per il log, con il prefisso che il supervisor cerca."""
    return tuple(f"{PREFISSO_ALLARME} {a}" for a in salute_corrente.allarmi)


# --- scrittura (l'unico I/O del modulo) ------------------------------------

def _controllo_predefinito() -> Any:
    from .db import controllo
    return controllo


def scrivi_pipeline_run(
    run: PipelineRun, *, controllo: Any | None = None, client: Any | None = None,
) -> int | None:
    """INSERT in `pipeline_run`; ritorna l'id, o None se la tabella non c'e'.

    Degrada in silenzio (log INFO): la telemetria non deve mai essere la ragione
    per cui un giro fallisce.
    """
    return _inserisci(TABELLA_RUN, run.come_riga(), controllo=controllo, client=client,
                      rispecchiati=RISPECCHIATI_PIPELINE_RUN)


def scrivi_fonte_run(
    fonte_run: FonteRun, *, controllo: Any | None = None, client: Any | None = None,
) -> int | None:
    return _inserisci(TABELLA_FONTE_RUN, fonte_run.come_riga(), controllo=controllo,
                      client=client)


def _inserisci(
    tabella: str, riga: dict[str, Any], *, controllo: Any | None, client: Any | None,
    rispecchiati: frozenset[str] = frozenset(),
) -> int | None:
    adattatore = controllo if controllo is not None else _controllo_predefinito()
    colonne = adattatore.colonne(tabella)
    if not colonne:
        logger.info("[telemetria] {} non esiste ancora: riga non scritta", tabella)
        return None
    payload = {k: v for k, v in riga.items() if k in colonne}
    # Un valore che nessuna colonna accoglie e che nessuna copia conserva
    # sparisce senza errore: e' cosi' che cinque numeri su cui si fondano i
    # tetti se ne andavano in silenzio. Almeno si dice quali.
    perduti = sorted(set(riga) - set(colonne) - set(rispecchiati))
    if perduti:
        logger.warning(
            "[telemetria] {}: nessuna colonna per {} — valori non scritti",
            tabella, perduti)
    if not payload:
        logger.info("[telemetria] {}: nessuna colonna compatibile, riga non scritta", tabella)
        return None
    try:
        if client is None:
            from .db import get_supabase
            client = get_supabase()
        risposta = client.table(tabella).insert(payload).execute()
    except Exception as e:
        logger.warning("[telemetria] insert in {} fallito: {}", tabella, e)
        return None
    dati = getattr(risposta, "data", None)
    if isinstance(dati, list) and dati and isinstance(dati[0], dict):
        valore = dati[0].get("id")
        return int(valore) if isinstance(valore, int) else None
    return None


__all__ = [
    "CODICI_SALUTE", "CODICI_SEMPLICI",
    "ESITO_ERRORE", "ESITO_INTERROTTO", "ESITO_OK", "ESITO_SALTATO", "FonteRun",
    "GIORNI_NUOVI", "LIVELLI", "LIVELLO_ALLARME", "LIVELLO_AVVISO",
    "LOCK_ALLARME_MIN", "LOCK_AVVISO_MIN", "LockTenuto", "ORE_SCRAPED_FERMO",
    "MINIMO_NUOVI", "NON_MISURABILI_DAL_DB", "NON_MISURATO_ACCESSO_RISERVATO",
    "NON_MISURATO_JOB_ORARIO", "NON_MISURATO_SERVIZIO", "PREFISSI_SALUTE",
    "PREFISSO_ALLARME", "PipelineRun", "RISPECCHIATI_PIPELINE_RUN", "Salute",
    "SOGLIA_CONTROLLI_FALLITI", "SUFFISSI_CODICE", "Stato", "TABELLA_FONTE_RUN",
    "QUOTA_ERRORI_GUASTO", "TABELLA_RUN", "Voce", "accesso_riservato_misurato",
    "esito_da_contatori", "lavorazione_del_lock", "prefisso_codice", "riepilogo",
    "righe_allarme", "salute", "stato_da_misure",
    "scrivi_fonte_run", "scrivi_pipeline_run", "voci_sorveglianza",
]
