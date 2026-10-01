"""Contatori e tetti di spesa del giro (piano §6.2, §6.3, A23, A36, §16.2 M19).

La pipeline spende due valute — crediti Firecrawl e dollari di token — su una
chiave condivisa con il resto del backend. Qui vivono i contatori del giro, il
listino e le funzioni che decidono se si puo' continuare.

Tre regole che vengono da altrettanti incidenti evitati:

* **mai `SystemExit`** (§16, A15). `_safe_run` e `_run_sync` catturano solo
  `Exception`: un `SystemExit` alzato dentro uno step attraverserebbe entrambi
  e ucciderebbe il sender. Al superamento di un tetto le funzioni qui ritornano
  un `Esito` con `interrotto_per_tetto=True`; gli exit code esistono solo in
  `app/__main__.py`.
* **il modello non a listino non si indovina** (A36). Il listino e' una mappa
  `model_id -> ($/Mtoken in, $/Mtoken out)`; se `response.model` non c'e', il
  costo conta 0 e si alza l'allarme «modello non a listino»: meglio un allarme
  che un numero inventato su cui si basa un tetto.
* **il backfill ha contatori propri** (A23, M19). I lotti una tantum scrivono su
  `pipeline_run.step='backfill:Lx'` e rispondono solo ai tetti di backfill: non
  devono consumare il mensile di regime ne' esserne fermati.

Dal giro 3 (contratto `bandi-giro-3` §1 e §4, regola «niente lotti»):

* **nessun tetto di numero**: niente tetto delle classificazioni (decide la
  spesa) e niente fetch per giro. I tetti sono solo spesa in $ (5 al giorno,
  150 al mese nello scenario bilanciato), crediti e ricerche;
* **il mensile si applica davvero**: `verifica` lo controlla quando conosce il
  consumo del mese (`crediti_mese`/`usd_mese`, anche dentro `gia_oggi`, che
  `db.consumo_oggi` porta con se');
* **la catena d'ingresso non si ferma mai** (`PASSI_INGRESSO`): conta e basta.
  La manutenzione risponde a tutti i tetti, smette di chiamare il modello e
  continua i controlli gratuiti.

Le funzioni sono pure: leggono contatori e tetti e ritornano un esito. La
scrittura su `pipeline_run` e' di `telemetria.py`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

MODELLO_FUORI_LISTINO = "modello non a listino"
PREFISSO_BACKFILL = "backfill:"


@dataclass(frozen=True)
class Tetti:
    """Tetti di un giro. `0` significa «nessun tetto» (cosi' un comando di
    diagnosi puo' disattivarli senza codice condizionale sparso).

    Nessun tetto di numero (giro 3, §1): il fetch per giro e le
    classificazioni al giorno non ci sono piu'.
    """
    ricerche_giorno: int = 0
    crediti_giorno: int = 0
    usd_giorno: float = 0.0
    crediti_mese: int = 0
    usd_mese: float = 0.0
    backfill_crediti: int = 0
    backfill_usd: float = 0.0


@dataclass(frozen=True)
class UsoModello:
    """Quanto e' costato un modello nel giro."""
    chiamate: int = 0
    token_ingresso: int = 0
    token_uscita: int = 0
    usd: float = 0.0


@dataclass
class Contatori:
    """Contatori del giro. Sono l'unica fonte del riepilogo e dei tetti."""
    fetch: int = 0
    fetch_304: int = 0
    crediti_firecrawl: int = 0
    ricerche: int = 0
    classificazioni: int = 0
    #: Controlli rimasti a meta' perche' il modello non ha risposto (credito
    #: esaurito, API giu'): li legge `salute`. NON sono in `classificazioni`,
    #: che conta le chiamate riuscite (un'informazione: dal giro 3 non c'e'
    #: piu' un tetto delle classificazioni, decide la spesa).
    classificazioni_fallite: int = 0
    eventi: int = 0
    rigenerazioni: int = 0
    errori: int = 0
    modelli: dict[str, UsoModello] = field(default_factory=dict)
    fuori_listino: tuple[str, ...] = ()

    @property
    def usd(self) -> float:
        """Spesa in token del giro, arrotondata al centesimo di cent."""
        return round(sum(u.usd for u in self.modelli.values()), 6)

    @property
    def chiamate(self) -> int:
        return sum(u.chiamate for u in self.modelli.values())

    def come_dizionario(self) -> dict[str, Any]:
        dati = asdict(self)
        dati["modelli"] = {nome: asdict(uso) for nome, uso in self.modelli.items()}
        dati["usd"] = self.usd
        dati["chiamate"] = self.chiamate
        return dati


@dataclass(frozen=True)
class Esito:
    """Risposta di ogni verifica di tetto. Mai un'eccezione, mai un exit."""
    consentito: bool = True
    interrotto_per_tetto: bool = False
    motivo: str = ""
    #: La voce del tetto raggiunto (`usd`, `crediti`, `ricerche`), ''
    #: se consentito.
    voce: str = ""

    @property
    def motivo_rimasti(self) -> str | None:
        """Il `motivo_rimasti` della copertura (§1): `crediti` per i crediti,
        `spesa` per ogni altro tetto, None se non c'e' tetto raggiunto."""
        if self.consentito:
            return None
        return "crediti" if self.voce == "crediti" else "spesa"

    def come_dizionario(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "interrotto_per_tetto": self.interrotto_per_tetto,
            "motivo": self.motivo,
        }


OK = Esito()


# --- listino ---------------------------------------------------------------

def costo_usd(
    token_ingresso: int,
    token_uscita: int,
    modello: str,
    listino: Mapping[str, tuple[float, float]],
) -> tuple[float, bool]:
    """($ del messaggio, «fuori listino»). Il listino e' in $/milione di token."""
    prezzi = listino.get(modello)
    if prezzi is None:
        return (0.0, True)
    ingresso, uscita = prezzi
    return (
        (max(0, token_ingresso) * ingresso + max(0, token_uscita) * uscita) / 1_000_000,
        False,
    )


def token_da_uso(uso: Any) -> tuple[int, int]:
    """(ingresso, uscita) da `response.usage` dell'SDK Anthropic.

    Accetta sia l'oggetto sia un dizionario: i test non devono costruire un
    oggetto dell'SDK per verificare un conto. La cache, quando c'e', e' token
    in ingresso a tutti gli effetti.
    """
    def _leggi(nome: str) -> int:
        if uso is None:
            return 0
        valore = uso.get(nome) if isinstance(uso, Mapping) else getattr(uso, nome, 0)
        try:
            return max(0, int(valore or 0))
        except (TypeError, ValueError):
            return 0

    ingresso = (
        _leggi("input_tokens")
        + _leggi("cache_creation_input_tokens")
        + _leggi("cache_read_input_tokens")
    )
    return (ingresso, _leggi("output_tokens"))


def registra_chiamata(
    contatori: Contatori,
    modello: str,
    uso: Any,
    listino: Mapping[str, tuple[float, float]],
) -> Contatori:
    """Somma una chiamata LLM ai contatori (muta e ritorna `contatori`)."""
    ingresso, uscita = token_da_uso(uso)
    usd, fuori = costo_usd(ingresso, uscita, modello, listino)
    precedente = contatori.modelli.get(modello, UsoModello())
    contatori.modelli[modello] = UsoModello(
        chiamate=precedente.chiamate + 1,
        token_ingresso=precedente.token_ingresso + ingresso,
        token_uscita=precedente.token_uscita + uscita,
        usd=round(precedente.usd + usd, 10),
    )
    if fuori and modello not in contatori.fuori_listino:
        contatori.fuori_listino = contatori.fuori_listino + (modello,)
    return contatori


def allarmi_listino(contatori: Contatori) -> tuple[str, ...]:
    """Un allarme per ogni modello usato e non presente a listino."""
    return tuple(f"{MODELLO_FUORI_LISTINO}: {m}" for m in contatori.fuori_listino)


# --- tetti -----------------------------------------------------------------

def e_backfill(step: str) -> bool:
    """`backfill:L2` risponde solo ai tetti di backfill (M19)."""
    return (step or "").startswith(PREFISSO_BACKFILL)


#: La riga del giro del sender (`bandi_pipeline._consumo`): somma i crediti e i
#: dollari degli step, che hanno gia' ciascuno la propria riga.
STEP_GIRO = "pipeline"


#: La catena d'ingresso (contratto `bandi-giro-3` §4): i passi che portano un
#: bando nuovo fino alla pubblicazione. Contano la spesa e non si fermano mai
#: per nessun tetto (ne' $, ne' crediti, ne' ricerche): un bando nuovo non
#: resta fuori perche' la giornata e' stata cara.
PASSI_INGRESSO: frozenset[str] = frozenset({
    "preprocess", "enrich", "seo", "resolver_precoce", "resolver",
})


def e_ingresso(step: str) -> bool:
    """Il passo e' della catena d'ingresso (`PASSI_INGRESSO`)?"""
    return (step or "") in PASSI_INGRESSO


def conta_nel_regime(step: str) -> bool:
    """Una riga di `pipeline_run` entra nei consumi di regime?

    No i lotti (M19), e no la riga del giro: e' un riassunto delle righe degli
    step, e sommarla con loro contava due volte i crediti del resolver. Si
    tengono le righe degli step perche' sono le sole che esistono anche per i
    lanci da riga di comando.
    """
    passo = step or ""
    return passo != STEP_GIRO and not e_backfill(passo)


def _supera(valore: float, tetto: float) -> bool:
    return tetto > 0 and valore >= tetto


def verifica_giornalieri(
    contatori: Contatori,
    tetti: Tetti,
    *,
    gia_oggi: Mapping[str, float] | None = None,
) -> Esito:
    """Tetti giornalieri: ricerche, crediti, $ (le classificazioni non piu': §1).

    `gia_oggi` e' il consumo dei giri precedenti della giornata (da
    `pipeline_run`): senza, con due giri al giorno il tetto varrebbe il doppio.
    """
    prima = gia_oggi or {}
    voci: tuple[tuple[str, float, float], ...] = (
        ("ricerche", contatori.ricerche + _valore(prima, "ricerche"), tetti.ricerche_giorno),
        ("crediti", contatori.crediti_firecrawl + _valore(prima, "crediti"), tetti.crediti_giorno),
        ("usd", contatori.usd + _valore(prima, "usd"), tetti.usd_giorno),
    )
    for nome, valore, tetto in voci:
        if _supera(valore, tetto):
            return Esito(False, True, f"tetto giornaliero {nome} raggiunto ({valore:g}/{tetto:g})",
                         voce=nome)
    return OK


def _valore(mappa: Mapping[str, Any], chiave: str) -> float:
    """Una voce di consumo letta da `pipeline_run`: un valore illeggibile vale 0."""
    valore = mappa.get(chiave)
    if isinstance(valore, bool):
        return 0.0
    try:
        return float(valore or 0)
    except (TypeError, ValueError):
        return 0.0


def consumo_mensile(somma_contatori: float, consumo_reale: float, baseline_altri: float) -> float:
    """`max(Σ contatore, consumo reale − baseline degli altri consumatori)`.

    La chiave Firecrawl e' condivisa con news/interpelli: il contatore da solo
    sottostima (le chiamate fuori pipeline non lo toccano) e il consumo reale da
    solo sovrastima (comprende gli altri). Si prende il peggiore dei due (§6.2).
    """
    return max(float(somma_contatori), float(consumo_reale) - float(baseline_altri))


def verifica_mensili(
    *,
    crediti_mese: float,
    usd_mese: float,
    tetti: Tetti,
    riserva: float = 0.0,
) -> Esito:
    """Tetto mensile del mese di calendario di Roma: si ferma la manutenzione.

    La `riserva` (quota del tetto tenuta da parte, A23) valeva 10 % per il
    resolver sui nuovi: dal giro 3 la catena d'ingresso non si ferma mai
    (`PASSI_INGRESSO`), quindi il default e' 0 e il tetto morde al 100 %.
    """
    quota = max(0.0, 1.0 - riserva)
    if tetti.crediti_mese > 0 and crediti_mese >= tetti.crediti_mese * quota:
        return Esito(False, True,
                     f"tetto mensile crediti raggiunto ({crediti_mese:g}/{tetti.crediti_mese:g})",
                     voce="crediti")
    if tetti.usd_mese > 0 and usd_mese >= tetti.usd_mese * quota:
        return Esito(False, True, f"tetto mensile $ raggiunto ({usd_mese:g}/{tetti.usd_mese:g})",
                     voce="usd")
    return OK


def verifica_backfill(contatori: Contatori, tetti: Tetti) -> Esito:
    """Tetti del lotto una tantum: contatore separato, fuori dal mensile."""
    if _supera(contatori.crediti_firecrawl, tetti.backfill_crediti):
        return Esito(False, True,
                     f"tetto backfill crediti raggiunto "
                     f"({contatori.crediti_firecrawl}/{tetti.backfill_crediti})", voce="crediti")
    if _supera(contatori.usd, tetti.backfill_usd):
        return Esito(False, True,
                     f"tetto backfill $ raggiunto ({contatori.usd:g}/{tetti.backfill_usd:g})",
                     voce="usd")
    return OK


def verifica(
    contatori: Contatori,
    tetti: Tetti,
    *,
    step: str = "",
    gia_oggi: Mapping[str, float] | None = None,
    crediti_mese: float | None = None,
    usd_mese: float | None = None,
) -> Esito:
    """Verifica completa nell'ordine in cui i tetti mordono.

    - un lotto di backfill risponde SOLO ai propri tetti (M19): passargli
      quelli di regime lo bloccherebbe al primo giro;
    - un passo della catena d'ingresso (`PASSI_INGRESSO`) non si ferma mai:
      sempre `OK`, la spesa la conta chi chiama (contratto §4);
    - la manutenzione risponde ai giornalieri e, se il consumo del mese e'
      noto, al mensile. Il consumo del mese dei giri precedenti arriva da
      `crediti_mese`/`usd_mese` oppure dalle stesse chiavi di `gia_oggi`
      (`db.consumo_oggi`); si somma quello del giro, che non e' ancora scritto.
    """
    if e_backfill(step):
        return verifica_backfill(contatori, tetti)
    if e_ingresso(step):
        return OK
    esito = verifica_giornalieri(contatori, tetti, gia_oggi=gia_oggi)
    if not esito.consentito:
        return esito
    prima = gia_oggi or {}
    if crediti_mese is None and "crediti_mese" in prima:
        crediti_mese = _valore(prima, "crediti_mese")
    if usd_mese is None and "usd_mese" in prima:
        usd_mese = _valore(prima, "usd_mese")
    if crediti_mese is not None or usd_mese is not None:
        return verifica_mensili(
            crediti_mese=float(crediti_mese or 0.0) + contatori.crediti_firecrawl,
            usd_mese=float(usd_mese or 0.0) + contatori.usd,
            tetti=tetti,
        )
    return OK


#: Il motivo con cui la manutenzione si ferma quando il consumo gia' speso non
#: si legge (contratto `bandi-giro-3` §18.5).
MOTIVO_CONSUMO_ILLEGGIBILE = "consumo di oggi non leggibile: tetto considerato raggiunto"


def _ha_tetti_di_regime(tetti: Tetti) -> bool:
    return any(valore > 0 for valore in (
        tetti.ricerche_giorno, tetti.crediti_giorno, tetti.usd_giorno,
        tetti.crediti_mese, tetti.usd_mese))


def verifica_con_consumo(
    contatori: Contatori,
    tetti: Tetti,
    *,
    step: str = "",
    consumo: Mapping[str, Any] | None,
) -> Esito:
    """`verifica` con il consumo letto da `db.consumo_oggi()` (§18.5).

    `consumo` None vuol dire «lettura fallita»: per la manutenzione vale tetto
    raggiunto (niente modello, niente crediti; i controlli gratuiti
    continuano), perche' un consumo ignoto non deve diventare un tetto che vale
    solo per il giro. L'ingresso e il backfill lo ignorano (non hanno i tetti di
    regime), e senza tetti di regime configurati non c'e' niente da superare.
    """
    if (consumo is None and not e_backfill(step) and not e_ingresso(step)
            and _ha_tetti_di_regime(tetti)):
        return Esito(False, True, MOTIVO_CONSUMO_ILLEGGIBILE, voce="usd")
    return verifica(contatori, tetti, step=step, gia_oggi=consumo)


def tetti_da_impostazioni(impostazioni: Any) -> Tetti:
    """`Settings` -> `Tetti`. Un solo punto che sa i nomi delle variabili.

    `TETTO_FETCH_GIRO` e `TETTO_CLASSIFICAZIONI_GIORNO` sono dismessi (giro 3,
    §3): non si leggono piu', e B6 li toglie da `Settings`.
    """
    return Tetti(
        ricerche_giorno=impostazioni.tetto_ricerche_giorno,
        crediti_giorno=impostazioni.tetto_crediti_giorno,
        usd_giorno=impostazioni.tetto_usd_giorno,
        crediti_mese=impostazioni.tetto_crediti_mese,
        usd_mese=impostazioni.tetto_usd_mese,
        backfill_crediti=impostazioni.backfill_tetto_crediti,
        backfill_usd=impostazioni.backfill_tetto_usd,
    )


def unisci_scarico(contatori: Contatori, contatori_scarico: Any) -> Contatori:
    """Porta dentro i contatori di `scarico.py` (fetch, 304, crediti)."""
    contatori.fetch += getattr(contatori_scarico, "fetch", 0)
    contatori.fetch_304 += getattr(contatori_scarico, "fetch_304", 0)
    contatori.crediti_firecrawl += getattr(contatori_scarico, "crediti_firecrawl", 0)
    contatori.errori += getattr(contatori_scarico, "errori", 0)
    return contatori


__all__ = [
    "Contatori", "Esito", "MODELLO_FUORI_LISTINO", "OK", "PASSI_INGRESSO", "PREFISSO_BACKFILL",
    "Tetti", "UsoModello", "allarmi_listino", "consumo_mensile", "costo_usd",
    "e_backfill", "e_ingresso", "registra_chiamata", "tetti_da_impostazioni", "token_da_uso",
    "MOTIVO_CONSUMO_ILLEGGIBILE", "verifica_con_consumo",
    "unisci_scarico", "verifica", "verifica_backfill",
    "verifica_giornalieri", "verifica_mensili",
]
