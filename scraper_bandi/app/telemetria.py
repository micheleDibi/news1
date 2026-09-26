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
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Mapping

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
        contatori = dict(self.contatori)
        contatori.update({
            "durata_s": self.durata_s,
            "crediti": self.crediti,
            "costo_usd": self.costo_usd,
            # `usd` e' il nome che `bilancio.verifica_giornalieri` cerca in
            # `gia_oggi`: scrivere solo `costo_usd` renderebbe il tetto
            # giornaliero in dollari sempre zero.
            "usd": self.costo_usd,
            "slug_modificati": list(self.slug_modificati),
            "saltato_per_lock": self.saltato_per_lock,
        })
        riga["contatori"] = contatori
        return riga


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
            "crediti": run.crediti,
            "usd": run.costo_usd,
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
LOCK_AVVISO_MIN = 60
LOCK_ALLARME_MIN = 180
#: «Nuovi» per la quota di `in_verifica`: pubblicati negli ultimi N giorni, e
#: solo se sono almeno M (con 4 bandi su 13 la quota e' rumore, non un segnale).
GIORNI_NUOVI = 7
MINIMO_NUOVI = 10
#: `controlli_falliti` da cui un bando conta come «bloccato» (piano §6.2).
SOGLIA_CONTROLLI_FALLITI = 5
#: Cio' che `salute` non puo' sapere dal DB: lo dice, invece di tacerlo.
NON_MISURABILI_DAL_DB: tuple[str, ...] = (
    "login Obiettivo Europa",
    "crediti residui Firecrawl",
    "schede OE con sezione «Link e Documenti»",
)


@dataclass(frozen=True)
class LockTenuto:
    """Un lock di `pipeline_lock` ancora valido e da quanto e' tenuto."""
    nome: str
    proprietario: str
    minuti: float


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
    #: Le misure sul DB non si sono potute fare: e' un allarme, non un silenzio.
    misure_db_errore: str | None = None
    #: Voci che questa esecuzione non ha misurato: finiscono negli avvisi.
    non_misurati: tuple[str, ...] = ()


@dataclass(frozen=True)
class Salute:
    allarmi: tuple[str, ...] = ()
    avvisi: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        """1 se c'e' almeno un allarme: `salute` e' pensata per un supervisor."""
        return 1 if self.allarmi else 0

    def come_dizionario(self) -> dict[str, Any]:
        return {
            "allarmi": list(self.allarmi),
            "avvisi": list(self.avvisi),
            "exit_code": self.exit_code,
        }


def salute(stato: Stato) -> Salute:
    """Allarmi e avvisi dello stato corrente (§6.2, A24, M15). Funzione pura."""
    allarmi: list[str] = []
    avvisi: list[str] = []

    if stato.ore_dall_ultimo_monitor_ok is not None and stato.ore_dall_ultimo_monitor_ok >= 24:
        allarmi.append(f"nessun monitor OK da {stato.ore_dall_ultimo_monitor_ok:.0f} h")
    if stato.misure_db_errore:
        allarmi.append(f"misure sul DB non disponibili: {stato.misure_db_errore}")
    if not stato.login_oe_ok:
        allarmi.append("login Obiettivo Europa fallito")
    if stato.giri_consecutivi_a_tetto >= 2:
        motivo = f" (l'ultimo: {stato.motivo_ultimo_tetto})" if stato.motivo_ultimo_tetto else ""
        allarmi.append(f"tetto raggiunto in {stato.giri_consecutivi_a_tetto} giri consecutivi{motivo}")
    for lock in stato.lock_tenuti:
        # RIPRESA §3.2 punto 10: un lock orfano ferma tutti i giri successivi
        # fino alla scadenza, e fino al 26/09/2026 nessun controllo lo vedeva.
        testo = (f"lock «{lock.nome}» tenuto da «{lock.proprietario}» da "
                 f"{lock.minuti:.0f} min")
        if lock.minuti >= LOCK_ALLARME_MIN:
            allarmi.append(f"{testo}: probabilmente orfano (lock_rilascia se nessun processo gira)")
        elif lock.minuti >= LOCK_AVVISO_MIN:
            avvisi.append(testo)
    if stato.crediti_residui_quota is not None and stato.crediti_residui_quota < 0.15:
        allarmi.append(f"crediti residui {stato.crediti_residui_quota:.0%} (< 15%)")
    if stato.consumo_mensile_quota is not None and stato.consumo_mensile_quota >= 0.80:
        allarmi.append(f"consumo mensile {stato.consumo_mensile_quota:.0%} (>= 80%)")
    if stato.quota_in_verifica_nuovi is not None and stato.quota_in_verifica_nuovi > 0.30:
        allarmi.append(f"fonti in verifica sui nuovi {stato.quota_in_verifica_nuovi:.0%} (> 30%)")
    if (stato.quota_schede_oe_con_sezione is not None
            and stato.quota_schede_oe_con_sezione < 0.80):
        allarmi.append(
            f"schede OE con sezione «Link e Documenti» {stato.quota_schede_oe_con_sezione:.0%} (< 80%)")
    if stato.quota_controlli_falliti is not None and stato.quota_controlli_falliti > 0.02:
        allarmi.append(f"controlli falliti >= 5 sul {stato.quota_controlli_falliti:.0%} dei vivi (> 2%)")
    # A24: nessun cambio automatico di scenario, solo la proposta.
    if (stato.residuo_piano_su_tetto_mensile is not None
            and stato.residuo_piano_su_tetto_mensile < 3):
        allarmi.append(
            "residuo del piano Firecrawl < 3x il tetto mensile: valutare MONITOR_SCENARIO=economico")
    # M15: la chiave IndexNow serve solo quando il monitor pubblica davvero.
    if stato.modalita_monitor == "attivo" and not stato.indexnow_configurata:
        allarmi.append("INDEXNOW_API_KEY assente con MONITOR_MODALITA=attivo")
    # M13: un `MONITOR_GIRI` che non coincide con le ore dello scheduler e' un
    # monitor spento in silenzio. Si dice subito, senza aspettare le 24 h di
    # «nessun monitor OK» (che oggi nessuno misura ancora).
    if not stato.monitor_giri_validi:
        allarmi.append(
            "MONITOR_GIRI contiene ore fuori dallo scheduler: voci ignorate, "
            "il monitor potrebbe non partire mai")

    for modello in stato.modelli_fuori_listino:
        avvisi.append(f"modello non a listino: {modello}")
    if stato.non_misurati:
        avvisi.append("non misurato da salute: " + ", ".join(stato.non_misurati))

    return Salute(tuple(allarmi), tuple(avvisi))


def _istante(valore: Any) -> datetime | None:
    """`timestamptz` di PostgREST -> datetime aware (None se illeggibile)."""
    if isinstance(valore, datetime):
        return valore if valore.tzinfo else valore.replace(tzinfo=timezone.utc)
    if not valore:
        return None
    try:
        letto = datetime.fromisoformat(str(valore).replace("Z", "+00:00"))
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
    - `lock`: righe di `pipeline_lock`.
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
    else:
        non_misurati.append("monitor di regime (nessun giro registrato)")

    pipeline = misure.get("pipeline")
    if pipeline is not None:
        consecutivi = 0
        for riga in pipeline:
            if not riga.get("interrotto_per_tetto"):
                break
            consecutivi += 1
        campi["giri_consecutivi_a_tetto"] = consecutivi
        if consecutivi:
            campi["motivo_ultimo_tetto"] = _motivo_del_tetto(pipeline[0])
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
        # I lotti hanno tetti propri e non consumano il mensile di regime (M19).
        regime = [r for r in mese if not str(r.get("step") or "").startswith("backfill:")]
        quote = []
        if tetto_crediti_mese > 0:
            quote.append(sum(_numero(r.get("crediti")) for r in regime) / tetto_crediti_mese)
        if tetto_usd_mese > 0:
            quote.append(sum(_numero(r.get("usd")) for r in regime) / tetto_usd_mese)
        campi["consumo_mensile_quota"] = max(quote)
    else:
        non_misurati.append("consumo mensile")

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
            ))
        campi["lock_tenuti"] = tuple(tenuti)
    else:
        non_misurati.append("lock di esecuzione")

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
    "ESITO_ERRORE", "ESITO_INTERROTTO", "ESITO_OK", "ESITO_SALTATO", "FonteRun",
    "GIORNI_NUOVI", "LOCK_ALLARME_MIN", "LOCK_AVVISO_MIN", "LockTenuto",
    "MINIMO_NUOVI", "NON_MISURABILI_DAL_DB",
    "PREFISSO_ALLARME", "PipelineRun", "RISPECCHIATI_PIPELINE_RUN", "Salute",
    "SOGLIA_CONTROLLI_FALLITI", "Stato", "TABELLA_FONTE_RUN",
    "QUOTA_ERRORI_GUASTO", "TABELLA_RUN", "esito_da_contatori", "riepilogo",
    "righe_allarme", "salute", "stato_da_misure",
    "scrivi_fonte_run", "scrivi_pipeline_run",
]
