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
    diagnosi puo' disattivarli senza codice condizionale sparso)."""
    fetch_giro: int = 0
    ricerche_giorno: int = 0
    crediti_giorno: int = 0
    classificazioni_giorno: int = 0
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


def _supera(valore: float, tetto: float) -> bool:
    return tetto > 0 and valore >= tetto


def verifica_fetch(contatori: Contatori, tetti: Tetti) -> Esito:
    """Unico tetto *per giro*: il fetch (§6.2)."""
    if _supera(contatori.fetch, tetti.fetch_giro):
        return Esito(False, True, f"tetto fetch per giro raggiunto ({contatori.fetch}/{tetti.fetch_giro})")
    return OK


def verifica_giornalieri(
    contatori: Contatori,
    tetti: Tetti,
    *,
    gia_oggi: Mapping[str, float] | None = None,
) -> Esito:
    """Tetti giornalieri: ricerche, crediti, classificazioni, $.

    `gia_oggi` e' il consumo dei giri precedenti della giornata (da
    `pipeline_run`): senza, con due giri al giorno il tetto varrebbe il doppio.
    """
    prima = gia_oggi or {}
    voci: tuple[tuple[str, float, float], ...] = (
        ("ricerche", contatori.ricerche + prima.get("ricerche", 0), tetti.ricerche_giorno),
        ("crediti", contatori.crediti_firecrawl + prima.get("crediti", 0), tetti.crediti_giorno),
        ("classificazioni",
         contatori.classificazioni + prima.get("classificazioni", 0), tetti.classificazioni_giorno),
        ("usd", contatori.usd + prima.get("usd", 0.0), tetti.usd_giorno),
    )
    for nome, valore, tetto in voci:
        if _supera(valore, tetto):
            return Esito(False, True, f"tetto giornaliero {nome} raggiunto ({valore:g}/{tetto:g})")
    return OK


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
    riserva: float = 0.10,
) -> Esito:
    """Tetto mensile: si fermano monitor e ricontrolli.

    La `riserva` e' la quota che resta al resolver sui nuovi `enriched` anche a
    tetto raggiunto (A23): un bando nuovo non deve uscire senza fonte solo
    perche' il mese e' stato caro. Chi la usa passa `riserva=0.0`.
    """
    quota = max(0.0, 1.0 - riserva)
    if tetti.crediti_mese > 0 and crediti_mese >= tetti.crediti_mese * quota:
        return Esito(False, True,
                     f"tetto mensile crediti raggiunto ({crediti_mese:g}/{tetti.crediti_mese:g})")
    if tetti.usd_mese > 0 and usd_mese >= tetti.usd_mese * quota:
        return Esito(False, True, f"tetto mensile $ raggiunto ({usd_mese:g}/{tetti.usd_mese:g})")
    return OK


def verifica_backfill(contatori: Contatori, tetti: Tetti) -> Esito:
    """Tetti del lotto una tantum: contatore separato, fuori dal mensile."""
    if _supera(contatori.crediti_firecrawl, tetti.backfill_crediti):
        return Esito(False, True,
                     f"tetto backfill crediti raggiunto "
                     f"({contatori.crediti_firecrawl}/{tetti.backfill_crediti})")
    if _supera(contatori.usd, tetti.backfill_usd):
        return Esito(False, True,
                     f"tetto backfill $ raggiunto ({contatori.usd:g}/{tetti.backfill_usd:g})")
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

    Un lotto di backfill risponde SOLO ai propri tetti (M19): passargli quelli
    di regime lo bloccherebbe al primo giro.
    """
    if e_backfill(step):
        return verifica_backfill(contatori, tetti)
    esito = verifica_fetch(contatori, tetti)
    if not esito.consentito:
        return esito
    esito = verifica_giornalieri(contatori, tetti, gia_oggi=gia_oggi)
    if not esito.consentito:
        return esito
    if crediti_mese is not None or usd_mese is not None:
        return verifica_mensili(
            crediti_mese=crediti_mese or 0.0, usd_mese=usd_mese or 0.0, tetti=tetti,
        )
    return OK


def tetti_da_impostazioni(impostazioni: Any) -> Tetti:
    """`Settings` -> `Tetti`. Un solo punto che sa i nomi delle variabili."""
    return Tetti(
        fetch_giro=impostazioni.tetto_fetch_giro,
        ricerche_giorno=impostazioni.tetto_ricerche_giorno,
        crediti_giorno=impostazioni.tetto_crediti_giorno,
        classificazioni_giorno=impostazioni.tetto_classificazioni_giorno,
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
    "Contatori", "Esito", "MODELLO_FUORI_LISTINO", "OK", "PREFISSO_BACKFILL",
    "Tetti", "UsoModello", "allarmi_listino", "consumo_mensile", "costo_usd",
    "e_backfill", "registra_chiamata", "tetti_da_impostazioni", "token_da_uso",
    "unisci_scarico", "verifica", "verifica_backfill", "verifica_fetch",
    "verifica_giornalieri", "verifica_mensili",
]
