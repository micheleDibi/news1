"""Rielaborazione dei pubblicati dalla fonte ufficiale (giro 3, contratto
`bandi-giro-3` §9). Passo 12 del giro e comando `rielabora-fonte`.

Chi: i pubblicati, non fusi, con la fonte `trovata`, la cui riga della fonte in
`bando_link` non porta ancora il marcatore `rielab:v1:` (`db.select_da_rielaborare`).
Tutti: nessun tetto di numero, solo il tempo `TEMPO_RIELABORAZIONE_S`, con la
rotazione per id che il marcatore fa da se' (chi e' fatto esce dalla coda).

Solo la fonte ufficiale (§18.1): se `scegli_fonte` non da' una pagina
ufficiale (PDF, ripiego su `link_bando`, URL vuoto) il bando si salta senza
scritture e senza marcatore (`senza_fonte_leggibile`, fuori dai candidati): lo
riprende il giro in cui la fonte diventa leggibile.

Cosa: la pagina ufficiale (`dominio_ufficiale.scegli_fonte`) passa da
`preprocessor.analyze_bando(url_lettura=...)` e da `enricher.enrich_bando`, come
un bando nuovo, ma **senza** scrivere `stato_processing` (mai
`update_bando_enriched`, `update_bandi_postanalysis`, `update_bando_refinement`):

- date: una `data_apertura` / `data_scadenza` nuova e diversa, su una colonna
  non verificata, diventa un evento `rettifica` (`origine='pipeline'`,
  `metodo='rielaborazione'`, citazione NULL quindi `verificato=false`,
  `in_aggiornamenti=false`) applicato dalla RPC `bando_registra_evento`. Solo se
  la sua citazione c'e', si ritrova nel testo letto e contiene la data
  (decisione del lead, guardia in piu': altrimenti `date_non_provate`) e se le
  date restano coerenti. Una data che chiederebbe una transizione di stato
  (§18.2): la scadenza nuova gia' passata su un aperto o un «in apertura» si
  applica da sola (la vista mostra subito `chiuso`, il job orario allinea
  `stato_bando`); ogni altro caso diventa una `rettifica` **non applicata e non
  leggibile** (`transizioni_da_decidere`), da decidere a mano: niente
  riaperture da una sola lettura. Mai `data_pubblicazione`, mai uno stato. Poi
  `rigenera.rigenera` porta la prosa sulla data nuova, senza modello; se non ci
  riesce, la data passa come novita' a `rigenera.riscrivi_scheda` (Opus, §6);
- classificazione: **due letture indipendenti** dell'enrich sulla stessa
  pagina, perche' le risposte di Haiku variano da una lettura all'altra (misura
  del dry-run dell'01/10). Una voce si aggiunge solo se compare in tutte e due,
  si toglie solo se manca in tutte e due; una FK cambia solo se le due letture
  danno lo stesso valore nuovo. Poi `db.allinea_junction` per regioni, settori,
  beneficiari e codici ATECO, e le tre FK con un UPDATE delle sole tre colonne.
  Una dimensione con una chiamata fallita (`_fallite`, in una delle due) o con
  zero voci in una lettura non si tocca mai. Ogni cambio finisce in `cambi` (prima e dopo, nel log e nella
  riga del passo) cosi' si torna indietro con SQL. Se una voce tolta e' nominata
  nel testo della scheda, la scheda si riscrive con `rigenera.riscrivi_scheda`
  (M3), se c'e';
- marcatore: a fine bando `impronta_contenuto = 'rielab:v1:<YYYY-MM-DD>:<sha256
  del testo letto>'` sulla riga della fonte, **solo a lavoro completo** (§18.3):
  una RPC fallita, una junction in errore o a meta', le FK non scritte, una
  dimensione saltata per una chiamata fallita o il marcatore stesso non scritto
  lasciano il bando fra i `rimasti` (motivo `errore`), e il giro dopo riprova.
  Il tentativo si annota come `rielab:v1:incompleto:<n>`; al terzo il bando si
  marca come fatto con il motivo (`abbandonati`, `motivi_abbandono`), cosi'
  un guasto che si ripete non ripaga letture ed enrich a ogni giro.
  `cambi` e `fk_cambiate` contano solo cio' che e' stato scritto. Una
  riscrittura con Opus non riuscita (o non disponibile) mette le novita' nella
  coda `__riscrittura__` del monitor, che le riprende.

Spesa: step `backfill:rielaborazione`, tetti del backfill (§4) sulla giornata di
Roma, cioe' la spesa del lancio piu' quella delle righe del passo gia' scritte
oggi (revisione #146: per lancio, quattro giri e un comando a mano valevano
cinque volte 60 $), con i crediti Firecrawl dello scarico (§18.4): a tetto il
passo si ferma. Fino a `PARALLELO` bandi insieme, mai due dello stesso host. In
`dry_run` non si scrive niente (ne' eventi, ne' junction, ne' marcatori, ne' la
riga di spesa): il risultato elenca le proposte.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, Mapping, Sequence

from . import bilancio, db, telemetria
from .date_validation import (
    check_dates_coherence,
    estrai_date_con_ruolo,
    norm_cit,
    parse_iso,
    reconcile_stato_bando,
)
from .dominio_ufficiale import dominio_di, scegli_fonte
from .logger import logger
from .preprocessor import conta_spesa
from .stato_bando import oggi_roma

#: Lo step della riga `pipeline_run` del passo: fuori dal regime, tetti del
#: backfill (§4).
STEP = "backfill:rielaborazione"
#: Fino a quanti bandi insieme (§9), mai due sullo stesso host.
PARALLELO = 5
#: Le date che la rielaborazione puo' correggere: mai `data_pubblicazione`.
COLONNE_DATA: tuple[tuple[str, str], ...] = (
    ("data_apertura", "apertura"), ("data_scadenza", "scadenza"),
)
#: Le quattro junction, con la chiave del risultato di `enrich_bando` e quella
#: del catalogo.
JUNCTION: tuple[tuple[str, str], ...] = (
    ("regioni", "regioni_ids"), ("settori", "settori_ids"),
    ("beneficiari", "beneficiari_ids"), ("codici_ateco", "codici_ateco_ids"),
)
#: Le tre FK con il nome della dimensione in `_fallite`.
FK: tuple[tuple[str, str], ...] = (
    ("tipologia_bando_id", "tipologia"), ("modalita_erogazione_id", "modalita"),
    ("programma_id", "programma"),
)
#: Gli stati su cui una scadenza nuova gia' passata si applica da sola (§18.2):
#: la vista calcola subito `chiuso`, il job orario allinea la colonna.
STATI_SOLA_DATA: frozenset[str] = frozenset({"aperto", "in apertura prossimamente"})
METODO = "rielaborazione"
#: Al terzo tentativo rimasto incompleto il bando si marca come fatto, con il
#: motivo (P2 di #160): come le riscritture del monitor (`TENTATIVI_RISCRITTURA`).
TENTATIVI_MASSIMI = 3

CONTATORI: tuple[str, ...] = (
    "esaminati", "rielaborati", "pagine_illeggibili", "non_validi", "errori",
    "date_proposte", "date_applicate", "date_non_applicate", "date_non_provate",
    "date_incoerenti", "discordanze_verificate", "transizioni_da_decidere",
    "prose_riallineate", "prose_non_riscritte", "junction_cambiate", "fk_cambiate", "junction_discordi", "fk_discordi",
    "junction_parziali", "senza_fonte_leggibile", "incompleti", "marcatori_non_scritti",
    "abbandonati", "riscritture_in_coda",
    "riscritture", "riscritture_non_disponibili", "riscritture_non_riuscite",
)


def tetto_tempo_s() -> float:
    """`TEMPO_RIELABORAZIONE_S` (§3), 3 600 s se `.env` non si legge."""
    try:
        from .settings import get_settings
        return float(get_settings().tempo_rielaborazione_s)
    except Exception:
        return 3600.0


def _tetti() -> bilancio.Tetti:
    try:
        from .settings import get_settings
        return bilancio.tetti_da_impostazioni(get_settings())
    except Exception:                                      # pragma: no cover - difesa
        return bilancio.Tetti()


def _crediti_scarico() -> int | None:
    """I crediti Firecrawl contati finora dallo scarico del processo (§18.4).
    None se non si leggono: quel giro di assorbimento si salta."""
    try:
        from . import scarico
        return int(getattr(scarico.contatori(), "crediti_firecrawl", 0) or 0)
    except Exception as e:                                # pragma: no cover - difesa
        logger.debug("[rielabora] contatori dello scarico non leggibili: {}", e)
        return None


def _consumo_di_oggi() -> dict[str, float] | None:
    """`{crediti, usd}` gia' spesi oggi dal passo; None se non si legge."""
    return db.consumo_passo_oggi(STEP)


def verifica_giornata(spesa: bilancio.Contatori, tetti: bilancio.Tetti,
                      gia_oggi: Mapping[str, Any]) -> bilancio.Esito:
    """I tetti del backfill sulla giornata: questo lancio piu' i precedenti di oggi."""
    crediti = spesa.crediti_firecrawl + float(gia_oggi.get("crediti") or 0)
    usd = round(spesa.usd + float(gia_oggi.get("usd") or 0), 6)
    if tetti.backfill_crediti > 0 and crediti >= tetti.backfill_crediti:
        return bilancio.Esito(
            False, True, f"tetto backfill crediti della giornata raggiunto "
                         f"({crediti:g}/{tetti.backfill_crediti})", voce="crediti")
    if tetti.backfill_usd > 0 and usd >= tetti.backfill_usd:
        return bilancio.Esito(
            False, True, f"tetto backfill $ della giornata raggiunto "
                         f"({usd:g}/{tetti.backfill_usd:g})", voce="usd")
    return bilancio.OK


def rielaborazione_incompleta(marcatore_attuale: Any) -> bool:
    """Il bando torna da un tentativo rimasto incompleto (`rielab:v1:incompleto:<n>`)?"""
    return str(marcatore_attuale or "").startswith(db.MARCATORE_INCOMPLETO)


def tentativi_falliti(marcatore_attuale: Any) -> int:
    """I tentativi gia' rimasti incompleti (`rielab:v1:incompleto:<n>`), o 0."""
    testo = str(marcatore_attuale or "")
    if not testo.startswith(db.MARCATORE_INCOMPLETO):
        return 0
    try:
        return max(0, int(testo[len(db.MARCATORE_INCOMPLETO):]))
    except ValueError:
        return 0


def marcatore(testo: str, giorno: Any) -> str:
    """`rielab:v1:<YYYY-MM-DD>:<sha256 del testo letto>`."""
    impronta = hashlib.sha256((testo or "").encode("utf-8", "replace")).hexdigest()
    return f"{db.MARCATORE_RIELABORAZIONE}{giorno.isoformat()}:{impronta}"


def citazione_provata(citazione: Any, data: Any, testo: str) -> bool:
    """La guardia sulle date (decisione del lead): la citazione c'e', si
    ritrova nel testo letto (normalizzato) e contiene la data."""
    if not citazione or data is None:
        return False
    frase = str(citazione)
    if norm_cit(frase) not in norm_cit(testo):
        return False
    return any(d.data == data for d in estrai_date_con_ruolo(frase))


def serve_transizione(stato: Any, apertura: Any, scadenza: Any, oggi: Any) -> bool:
    """La data nuova chiederebbe di cambiare lo stato? Allora non si applica
    qui (§9): un chiuso con la scadenza nel futuro, un «in apertura» con
    l'apertura passata, o qualunque stato che le date nuove porterebbero
    altrove (anche sospeso e revocato, che nessuna data cambia da sola)."""
    if stato in ("sospeso", "revocato"):
        # Fuori dal vocabolario di `reconcile_stato_bando`: qualunque data
        # nuova su un sospeso o un revocato la guarda il monitor.
        return True
    if stato == "chiuso" and scadenza is not None and scadenza >= oggi:
        return True
    if stato == "in apertura prossimamente" and apertura is not None and apertura <= oggi:
        return True
    calcolato = reconcile_stato_bando(stato, apertura, scadenza, today=oggi)
    return calcolato is not None and calcolato != stato


def concordi(prima: Sequence[int], lettura_a: set[int], lettura_b: set[int]) -> list[int]:
    """La dimensione dopo due letture (§9): una voce si aggiunge solo se c'e' in
    tutte e due, si toglie solo se manca in tutte e due, altrimenti resta com'e'."""
    attuale = set(prima)
    restano = attuale & (lettura_a | lettura_b)
    aggiunte = (lettura_a & lettura_b) - attuale
    return sorted(restano | aggiunte)


def nomi_nel_testo(ids: Sequence[int], voci: Sequence[Mapping[str, Any]], testo: str) -> list[str]:
    """I nomi delle voci di catalogo `ids` che compaiono nel testo."""
    normale = norm_cit(testo)
    per_id = {int(v.get("id")): v for v in voci if v.get("id") is not None}
    nomi: list[str] = []
    for i in ids:
        voce = per_id.get(int(i)) or {}
        nome = str(voce.get("nome") or voce.get("descrizione") or "").strip()
        if len(nome) >= 3 and norm_cit(nome) in normale:
            nomi.append(nome)
    return nomi


# --- I/O sostituibile nei test ------------------------------------------------

async def _analizza(bando: Mapping[str, Any], fonte_ctx: Mapping[str, Any], url: str) -> dict:
    from .preprocessor import analyze_bando
    return await analyze_bando(dict(bando), dict(fonte_ctx), url_lettura=url)


async def _testo_letto(url: str) -> str:
    """Lo stesso testo che `analyze_bando` ha dato al modello (cache del giro)."""
    from .enricher import _firecrawl_scrape_markdown
    from .preprocessor import _pagina_in_cache, testo_strutturato
    markdown = await _firecrawl_scrape_markdown(url)
    pagina = await _pagina_in_cache(url)
    return testo_strutturato(markdown or "", getattr(pagina, "html", None))


async def _classifica(bando: Mapping[str, Any], fonte_ctx: Mapping[str, Any], testo: str,
                      catalogo: Mapping[str, Any]) -> dict:
    from .enricher import enrich_bando
    return await enrich_bando(dict(bando), dict(fonte_ctx), testo, dict(catalogo))


async def _rigenera_prosa(
    bando: Mapping[str, Any],
    evento: Mapping[str, Any],
    *,
    vecchia: Any,
    nuova: Any,
    ruolo: str,
    scrivi_db: Any = None,
) -> tuple[Any, Any] | None:
    """La prosa sulla data nuova, senza modello: `(esito, campi scritti)`.

    `contenuto` e' un jsonb con `sections`: `rigenera` lavora sul testo dei
    soli nodi (`rigenera._testo_del_contenuto`) e lo scrittore lo rimonta in
    jsonb un attimo prima dell'UPDATE (`rigenera._scrittore_json`), come fa il
    monitor in `monitoraggio._da_rigenerare`. Passargli la riga cosi' com'e'
    faceva scrivere `str(dict)` dentro la colonna (revisione #146, P0). Il
    secondo valore sono i campi davvero scritti (`contenuto` nella sua forma di
    colonna, `descrizione_breve` se cambiata), per chi continua a lavorare sulla
    stessa riga: la seconda data non deve riportare indietro la prima. None se
    il contenuto non si scompone in nodi o non ha testo: la prosa non si tocca.
    """
    from . import rigenera
    trasformato = rigenera._testo_del_contenuto(dict(bando))
    if trasformato is None:
        return None
    corrente, struttura, era_stringa = trasformato
    if not str(corrente.get("contenuto") or "").strip():
        return None
    base = scrivi_db or rigenera.scrivi_su_db
    scritto: dict[str, Any] = {}

    async def scrivi_e_ricorda(bando_id: Any, payload: dict[str, Any]) -> bool:
        riuscito = bool(await base(bando_id, payload))
        if riuscito:
            scritto.update({k: payload[k] for k in ("contenuto", "descrizione_breve")
                            if k in payload})
        return riuscito

    esito = await rigenera.rigenera(
        corrente, evento, vecchia=vecchia, nuova=nuova, ruolo=ruolo, attivo=True,
        scrivi=rigenera._scrittore_json(scrivi_e_ricorda, struttura, era_stringa))
    return esito, scritto


def _riscrittore() -> Any:
    """`rigenera.riscrivi_scheda` di M3, se c'e' (§6)."""
    try:
        from . import rigenera
    except Exception:                                      # pragma: no cover - difesa
        return None
    return getattr(rigenera, "riscrivi_scheda", None)


def _contesto_fonti(righe: Sequence[Mapping[str, Any]]) -> dict[Any, dict[str, Any]]:
    ids = list({r.get("fonte_id") for r in righe if r.get("fonte_id") is not None})
    try:
        return db.enrich_fonti_with_names(db.select_fonti_by_ids(ids)) if ids else {}
    except Exception as e:
        logger.warning("[rielabora] fonti non lette: {}", e)
        return {}


def _catalogo() -> dict[str, Any]:
    try:
        return dict(db.load_catalogo())
    except Exception as e:
        logger.warning("[rielabora] catalogo non letto: {}", e)
        return {}


# --- il passo ------------------------------------------------------------------

async def run(
    *,
    giro: str | None = None,
    dry_run: bool = False,
    ids: Sequence[Any] | None = None,
    tempo_s: float | None = None,
    parallelo: int | None = None,
) -> dict[str, Any]:
    """Il passo 12 del giro (e `rielabora-fonte`). Non solleva mai."""
    avvio = time.monotonic()
    contatori = {nome: 0 for nome in CONTATORI}
    cambi: list[dict[str, Any]] = []
    proposte: list[dict[str, Any]] = []
    slug_modificati: list[str] = []
    spesa = bilancio.Contatori()
    tetti = _tetti()
    if tempo_s is None:
        tempo_s = tetto_tempo_s()
    try:
        righe = db.select_da_rielaborare(ids=list(ids) if ids else None)
        junction = db.select_junction([r.get("id") for r in righe]) if righe else {}
    except Exception as e:
        logger.exception("[rielabora] selezione fallita: {}", e)
        return {"status": "errore", "error": str(e), "copertura": telemetria.copertura(0, 0)}
    # §18.1: si lavora solo sulla pagina ufficiale. Un PDF, il ripiego su
    # `link_bando` (spesso un aggregatore) o un URL vuoto non sono una prova
    # per correggere un pubblicato: niente scritture, niente marcatore, e il
    # bando resta in coda per il giro in cui la fonte diventa leggibile. Non e'
    # un candidato di questo passo, quindi non entra nella copertura.
    lavorabili: list[tuple[dict[str, Any], str]] = []
    for riga in righe:
        url, ufficiale = scegli_fonte(riga)
        if ufficiale and url:
            lavorabili.append((riga, url))
            continue
        contatori["senza_fonte_leggibile"] += 1
        proposte.append({"bando_id": riga.get("id"), "url": url or None, "date": [],
                         "cambi": [], "riscrittura": None, "fatto": False,
                         "motivo": "senza fonte leggibile"})
    gia_oggi = _consumo_di_oggi() if lavorabili else {}
    if gia_oggi is None:
        # Non si sa quanto si e' gia' speso oggi: per un tetto di spesa la
        # scelta prudente e' non partire. Il giro dopo riprova.
        logger.warning("[rielabora] consumo di oggi illeggibile: il passo non parte")
        return {"status": "ok", "dry_run": dry_run, "giro": giro,
                **contatori, "interrotto_per_tetto": True,
                "motivo": "consumo di oggi illeggibile",
                "copertura": telemetria.copertura(len(lavorabili), 0, "spesa")}
    fonti = _contesto_fonti([riga for riga, _url in lavorabili])
    catalogo = _catalogo() if lavorabili else {}
    giorno = oggi_roma()
    # §18.4: i crediti Firecrawl dello scarico (preprocess ed enrich leggono
    # la pagina con il ripiego a pagamento) entrano nella spesa del passo. Si
    # assorbe il delta dall'inizio del passo, prima di ogni controllo dei
    # tetti e a fine bando: con piu' bandi in parallelo la differenza «prima e
    # dopo» del singolo bando conterebbe due volte i crediti degli altri.
    crediti_letti: list[int | None] = [_crediti_scarico()]

    def assorbi_crediti() -> None:
        attuale, precedente = _crediti_scarico(), crediti_letti[0]
        if attuale is None:
            return
        if precedente is None or attuale < precedente:
            # Contatori azzerati nel frattempo (`scarico.svuota`): conta da zero.
            delta = attuale if precedente is not None else 0
        else:
            delta = attuale - precedente
        if delta > 0:
            spesa.crediti_firecrawl += delta
        crediti_letti[0] = attuale

    lucchetti: dict[str, asyncio.Lock] = {}
    semaforo = asyncio.Semaphore(max(1, int(parallelo or PARALLELO)))
    fatti = 0
    motivo_stop: str | None = None

    async def lavora(bando: dict[str, Any], url: str) -> None:
        nonlocal fatti
        host = dominio_di(url) or url
        async with lucchetti.setdefault(host, asyncio.Lock()):
            try:
                esito = await _rielabora_uno(
                    bando, url, fonti.get(bando.get("fonte_id"), {}), catalogo,
                    junction.get(bando.get("id"), {}), contatori, cambi, slug_modificati,
                    spesa=spesa, giorno=giorno, dry_run=dry_run)
            except Exception as e:
                contatori["errori"] += 1
                logger.exception("[rielabora] bando {} saltato per un errore: {}", bando.get("id"), e)
                # §19.5: anche un'eccezione e' un tentativo, con l'abbandono al
                # terzo: un bando che solleva sempre non si ripaga a ogni giro.
                esito = {"bando_id": bando.get("id"), "url": url, "date": [], "cambi": [],
                         "riscrittura": None, "fatto": False,
                         "incompleto": [f"errore {type(e).__name__}"]}
                try:
                    _concludi(bando, "", giorno, dry_run, contatori, esito, rielaborato=False)
                except Exception as e2:                   # pragma: no cover - difesa
                    logger.warning("[rielabora] tentativo del bando {} non annotato: {}",
                                   bando.get("id"), e2)
        proposte.append(esito)
        if esito.get("fatto"):
            fatti += 1

    in_corso: set[asyncio.Future[Any]] = set()
    with conta_spesa(spesa):
        for bando, url in lavorabili:
            await semaforo.acquire()
            assorbi_crediti()
            controllo = verifica_giornata(spesa, tetti, gia_oggi)
            if not controllo.consentito:
                semaforo.release()
                motivo_stop = "crediti" if controllo.voce == "crediti" else "spesa"
                logger.warning("[rielabora] {}", controllo.motivo)
                break
            if time.monotonic() - avvio >= tempo_s:
                semaforo.release()
                motivo_stop = "tempo"
                break
            contatori["esaminati"] += 1

            async def _uno(b: dict[str, Any] = bando, u: str = url) -> None:
                try:
                    await lavora(b, u)
                finally:
                    assorbi_crediti()
                    semaforo.release()

            compito = asyncio.ensure_future(_uno())
            in_corso.add(compito)
            compito.add_done_callback(in_corso.discard)
        if in_corso:
            await asyncio.gather(*in_corso)
    assorbi_crediti()

    motivo = motivo_stop or ("errore" if contatori["errori"] or contatori["pagine_illeggibili"]
                             or contatori["incompleti"] else None)
    copertura = telemetria.copertura(len(lavorabili), fatti, motivo)
    durata = time.monotonic() - avvio
    # Perche' si e' abbandonato, contato per motivo (il bando e' nel log): un
    # dizionario piccolo invece di un elenco per bando nella riga.
    motivi_abbandono: dict[str, int] = {}
    for proposta in proposte:
        for motivo_bando in proposta.get("abbandonato") or ():
            motivi_abbandono[motivo_bando] = motivi_abbandono.get(motivo_bando, 0) + 1
    risultato: dict[str, Any] = {
        "status": "ok", "dry_run": dry_run, "giro": giro, **contatori,
        "motivi_abbandono": motivi_abbandono,
        "cambi": cambi, "slug_modificati": slug_modificati, "copertura": copertura,
        "costo_usd": spesa.usd, "spesa": spesa.come_dizionario(),
        "consumo_oggi_prima": dict(gia_oggi), "elapsed_s": round(durata, 1),
    }
    if motivo_stop in ("spesa", "crediti"):
        risultato["interrotto_per_tetto"] = True
    if dry_run:
        risultato["proposte"] = sorted(proposte, key=lambda p: str(p.get("bando_id")))
    else:
        _registra(risultato, durata)
    logger.info("[rielabora] === DONE | {} ===",
                {k: v for k, v in risultato.items() if k not in ("cambi", "proposte", "spesa")})
    return risultato


#: Il lock del comando fuori dal dry-run: quello del giro, come `seo-rigenera`
#: (revisione #146). Il passo 12 gira gia' sotto il lock del giro, quindi un
#: comando a mano non deve poter rielaborare gli stessi bandi in parallelo.
#: Il proprietario finisce in `:cli`, cosi' il sender non lo rilascia mai
#: all'avvio; dura il tempo del passo piu' mezz'ora, poi scade da solo.
LOCK_COMANDO = "bandi_pipeline"
PROPRIETARIO_COMANDO = "rielabora-fonte:cli"
MARGINE_LOCK_S = 1800


async def run_comando(
    *,
    dry_run: bool = False,
    ids: Sequence[Any] | None = None,
    lock: Any | None = None,
) -> dict[str, Any]:
    """`rielabora-fonte`: il dry-run gira senza lock (non scrive), il resto
    solo con il lock del giro. Lock occupato: niente lavoro, `saltato_per_lock`."""
    if dry_run:
        return await run(dry_run=True, ids=ids)
    if lock is None:
        from . import blocco as lock
    preso = lock.acquisisci(LOCK_COMANDO, PROPRIETARIO_COMANDO,
                            int(tetto_tempo_s()) + MARGINE_LOCK_S)
    if not preso.proseguire:
        logger.warning("[rielabora] lock {} occupato (giro in corso?): non parto", LOCK_COMANDO)
        return {"status": "ok", "dry_run": False, **{nome: 0 for nome in CONTATORI},
                "saltato_per_lock": True, "lock": LOCK_COMANDO,
                "copertura": telemetria.copertura(0, 0, "lock")}
    try:
        return await run(dry_run=False, ids=ids)
    finally:
        lock.rilascia(preso)


def _registra(risultato: Mapping[str, Any], durata: float) -> None:
    """La riga `pipeline_run` del passo (step `backfill:rielaborazione`). Non solleva."""
    try:
        contatori = {k: v for k, v in risultato.items()
                     if k in CONTATORI or k in ("cambi", "copertura", "consumo_oggi_prima",
                                                "motivi_abbandono")}
        contatori.update(dict(risultato.get("spesa") or {}))
        riga = telemetria.PipelineRun(step=STEP, giro=risultato.get("giro")).concludi(
            durata_s=durata,
            esito=telemetria.esito_da_contatori(
                errori=int(risultato.get("errori") or 0),
                interrotto_per_tetto=bool(risultato.get("interrotto_per_tetto"))),
            contatori=contatori,
            interrotto_per_tetto=bool(risultato.get("interrotto_per_tetto")),
            slug_modificati=tuple(risultato.get("slug_modificati") or ()),
        )
        telemetria.scrivi_pipeline_run(riga)
    except Exception as e:                                # pragma: no cover - difesa
        logger.warning("[rielabora] riga del passo non registrata: {}", e)


async def _rielabora_uno(
    bando: dict[str, Any],
    url: str,
    fonte_ctx: Mapping[str, Any],
    catalogo: Mapping[str, Any],
    attuali: Mapping[str, Sequence[int]],
    contatori: dict[str, int],
    cambi: list[dict[str, Any]],
    slug_modificati: list[str],
    *,
    spesa: bilancio.Contatori,
    giorno: Any,
    dry_run: bool,
) -> dict[str, Any]:
    """Un bando. Ritorna la proposta (`fatto` vero se il marcatore e' scritto).

    `proposta["incompleto"]` raccoglie cio' che non e' andato a buon fine
    (§18.3): se non e' vuoto il marcatore non si scrive e il bando resta fra i
    `rimasti`, cosi' il giro dopo lo riprende.
    """
    bando_id = bando.get("id")
    proposta: dict[str, Any] = {"bando_id": bando_id, "url": url, "date": [], "cambi": [],
                                "riscrittura": None, "fatto": False, "incompleto": []}
    analisi = await _analizza(bando, fonte_ctx, url)
    if analisi.get("_needs_fallback"):
        # Pagina illeggibile oggi: niente marcatore, si riprova al giro dopo.
        # §19.5: e' un tentativo; al terzo il bando si abbandona, cosi' una
        # pagina dell'ente morta non si riscarica (e si ripaga) per sempre.
        contatori["pagine_illeggibili"] += 1
        proposta["incompleto"].append("pagina illeggibile")
        _concludi(bando, "", giorno, dry_run, contatori, proposta, rielaborato=False)
        return proposta
    testo = await _testo_letto(url)
    if not analisi.get("is_valid_bando"):
        # Un pubblicato che la rilettura dice «non valido» non si tocca, ma si
        # marca e si conta (decisione del lead, D2): e' un caso da guardare.
        contatori["non_validi"] += 1
        proposta["motivo"] = "lettura: non valido"
        _concludi(bando, testo, giorno, dry_run, contatori, proposta, rielaborato=False)
        return proposta

    novita = await _date(bando, url, analisi, testo, contatori, proposta, slug_modificati,
                         giorno=giorno, dry_run=dry_run)
    nominati = await _classificazione(bando, url, fonte_ctx, testo, catalogo, attuali, contatori,
                                      cambi, proposta, slug_modificati, dry_run=dry_run)
    await _riscrivi(bando, url, novita, nominati, contatori, proposta, slug_modificati,
                    spesa=spesa, dry_run=dry_run)
    _concludi(bando, testo, giorno, dry_run, contatori, proposta, rielaborato=True)
    return proposta


def _concludi(bando: Mapping[str, Any], testo: str, giorno: Any, dry_run: bool,
              contatori: dict[str, int], proposta: dict[str, Any], *, rielaborato: bool) -> None:
    """Il marcatore, solo a lavoro completo e solo se scritto davvero (§18.3).

    Un lavoro incompleto annota il tentativo (`rielab:v1:incompleto:<n>`) e il
    bando resta in coda; al `TENTATIVI_MASSIMI`-esimo si marca come fatto con
    il motivo (`abbandonati`), cosi' un guasto che si ripete non si ripaga a
    ogni giro (P2 di #160).
    """
    abbandonato = False
    if proposta["incompleto"]:
        motivi = list(proposta["incompleto"])
        tentativo = tentativi_falliti(bando.get("_marcatore")) + 1
        if tentativo < TENTATIVI_MASSIMI:
            contatori["incompleti"] += 1
            proposta["motivo"] = f"incompleto (tentativo {tentativo}): " + ", ".join(motivi)
            logger.warning("[rielabora] bando {} non marcato: {}", bando.get("id"),
                           proposta["motivo"])
            _annota_tentativo(bando, tentativo, dry_run)
            return
        abbandonato = True
        contatori["abbandonati"] += 1
        proposta["abbandonato"] = motivi
        proposta["motivo"] = f"abbandonato dopo {tentativo} tentativi: " + ", ".join(motivi)
        logger.warning("[ALLARME] [rielabora] bando {} {}", bando.get("id"), proposta["motivo"])
    if not _marca(bando, testo, giorno, dry_run):
        contatori["marcatori_non_scritti"] += 1
        contatori["incompleti"] += 1
        proposta["incompleto"].append("marcatore")
        proposta["motivo"] = "incompleto: marcatore"
        return
    if rielaborato and not abbandonato:
        contatori["rielaborati"] += 1
    proposta["fatto"] = True


def _annota_tentativo(bando: Mapping[str, Any], tentativo: int, dry_run: bool) -> None:
    """`rielab:v1:incompleto:<n>` sulla riga della fonte: il bando resta in coda
    (`db.da_rielaborare`) e il giro dopo sa a che tentativo e'."""
    link_id = bando.get("fonte_ufficiale_link_id")
    if dry_run or link_id is None:
        return
    esito = db.aggiorna_link(link_id, {"impronta_contenuto": f"{db.MARCATORE_INCOMPLETO}{tentativo}"})
    if not (esito or {}).get("scritto"):
        logger.warning("[rielabora] tentativo {} del bando {} non annotato", tentativo,
                       bando.get("id"))


def _marca(bando: Mapping[str, Any], testo: str, giorno: Any, dry_run: bool) -> bool:
    """Scrive il marcatore sulla riga della fonte. Vero se e' scritto (in
    `dry_run` non si scrive niente e vale come fatto)."""
    if dry_run:
        return True
    link_id = bando.get("fonte_ufficiale_link_id")
    if link_id is None:
        return False
    esito = db.aggiorna_link(link_id, {"impronta_contenuto": marcatore(testo, giorno)})
    return bool((esito or {}).get("scritto"))


def _sola_data(stato: Any, candidate: Mapping[str, Any], giorno: Any) -> bool:
    """§18.2: una scadenza nuova gia' passata su un aperto o un «in apertura»
    si applica da sola; la vista mostra subito `chiuso`."""
    if stato not in STATI_SOLA_DATA or "data_scadenza" not in candidate:
        return False
    nuova = candidate["data_scadenza"][1]
    return nuova is not None and nuova < giorno


def _parametri_rettifica(bando: Mapping[str, Any], colonna: str, vecchia: Any, nuova: Any,
                         citazione: str, url: str, giorno: Any, *, applica: bool) -> dict[str, Any]:
    parametri = {
        "p_bando_id": bando.get("id"),
        "p_tipo": "rettifica",
        "p_origine": "pipeline",
        "p_campo": colonna,
        "p_valore_dopo": {colonna: nuova.isoformat()},
        "p_url_prova": url,
        # NULL: la prova e' la pagina, ma la correzione non passa dai gate
        # del monitor, quindi `verificato` resta falso (§9).
        "p_citazione": None,
        "p_data_evento": giorno.isoformat(),
        "p_applica": applica,
        "p_in_aggiornamenti": False,
        "p_gate": {"citazione": citazione, "contesto": METODO, "pagina": url,
                   "prima": vecchia.isoformat() if vecchia else None},
        "p_metodo": METODO,
    }
    if not applica:
        # §18.2: da decidere a mano, quindi invisibile finche' qualcuno non la
        # applica. Lo stato di oggi entra nel gate per chi la guarda.
        parametri["p_leggibile"] = False
        parametri["p_gate"]["stato_bando"] = bando.get("stato_bando")
    return parametri


async def _date(
    bando: dict[str, Any],
    url: str,
    analisi: Mapping[str, Any],
    testo: str,
    contatori: dict[str, int],
    proposta: dict[str, Any],
    slug_modificati: list[str],
    *,
    giorno: Any,
    dry_run: bool,
) -> list[dict[str, Any]]:
    """Le date nuove. Ritorna le novita' per `riscrivi_scheda`: le date
    applicate la cui prosa non si e' riallineata senza modello (§18.3)."""
    novita: list[dict[str, Any]] = []
    citazioni = analisi.get("_citazioni") if isinstance(analisi.get("_citazioni"), Mapping) else {}
    candidate: dict[str, tuple[Any, Any, str, str]] = {}
    for colonna, ruolo in COLONNE_DATA:
        nuova = parse_iso(str(analisi.get(colonna) or "")[:10])
        vecchia = parse_iso(str(bando.get(colonna) or "")[:10])
        if nuova is None or nuova == vecchia:
            continue
        if bando.get(f"{colonna}_verificata"):
            contatori["discordanze_verificate"] += 1
            continue
        citazione = citazioni.get(colonna)
        if not citazione_provata(citazione, nuova, testo):
            contatori["date_non_provate"] += 1
            continue
        candidate[colonna] = (vecchia, nuova, str(citazione), ruolo)
    if not candidate:
        return novita
    pubblicazione = parse_iso(str(bando.get("data_pubblicazione") or "")[:10])
    apertura = candidate.get("data_apertura", (None, parse_iso(str(bando.get("data_apertura") or "")[:10])))[1]
    scadenza = candidate.get("data_scadenza", (None, parse_iso(str(bando.get("data_scadenza") or "")[:10])))[1]
    if not check_dates_coherence(pubblicazione, apertura, scadenza):
        contatori["date_incoerenti"] += len(candidate)
        return novita
    stato = bando.get("stato_bando")
    if serve_transizione(stato, apertura, scadenza, giorno) and not _sola_data(stato, candidate, giorno):
        # §18.2: un chiuso con la scadenza nel futuro, un «in apertura» con
        # l'apertura passata, un sospeso o un revocato. Una sola lettura non
        # basta a riaprire o a cambiare uno stato: la rettifica si registra non
        # applicata e non leggibile, da decidere a mano, e il bando si marca.
        contatori["transizioni_da_decidere"] += 1
        proposta["transizione_da_decidere"] = True
        for colonna, (vecchia, nuova, citazione, _ruolo) in candidate.items():
            proposta["date"].append({"campo": colonna, "prima": vecchia.isoformat() if vecchia else None,
                                     "dopo": nuova.isoformat(), "citazione": citazione,
                                     "da_decidere": True})
            if dry_run:
                continue
            risposta = db.registra_evento_rpc(_parametri_rettifica(
                bando, colonna, vecchia, nuova, citazione, url, giorno, applica=False))
            if not risposta or risposta.get("id") is None:
                proposta["incompleto"].append(f"evento {colonna}")
        return novita
    for colonna, (vecchia, nuova, citazione, ruolo) in candidate.items():
        contatori["date_proposte"] += 1
        proposta["date"].append({"campo": colonna, "prima": vecchia.isoformat() if vecchia else None,
                                 "dopo": nuova.isoformat(), "citazione": citazione})
        if dry_run:
            continue
        risposta = db.registra_evento_rpc(_parametri_rettifica(
            bando, colonna, vecchia, nuova, citazione, url, giorno, applica=True))
        if not risposta:
            # La RPC e' fallita: la data non e' scritta e il bando si riprende.
            contatori["date_non_applicate"] += 1
            proposta["incompleto"].append(f"evento {colonna}")
            continue
        if not risposta.get("applicato"):
            contatori["date_non_applicate"] += 1
            continue
        contatori["date_applicate"] += 1
        evento = {"id": risposta.get("id"), "tipo": "rettifica", "campo": colonna,
                  "data_evento": giorno.isoformat(), "citazione": citazione,
                  "valore_prima": {colonna: vecchia.isoformat() if vecchia else None},
                  "valore_dopo": {colonna: nuova.isoformat()}, "url_prova": url}
        try:
            riallineata = await _rigenera_prosa(bando, evento, vecchia=vecchia, nuova=nuova,
                                                ruolo=ruolo)
        except Exception as e:
            logger.warning("[rielabora] prosa del bando {} non riallineata: {}", bando.get("id"), e)
            riallineata = None
        if riallineata is None or not getattr(riallineata[0], "scritto", False):
            # La data e' in colonna ma la prosa dice ancora quella vecchia: la
            # riscrive Opus, come fa il monitor (§6, §18.3).
            contatori["prose_non_riscritte"] += 1
            novita.append(_novita_data(evento))
            continue
        contatori["prose_riallineate"] += 1
        # La forma di colonna (jsonb rimontato), non il testo dei nodi: la data
        # dopo, o la riscrittura, lavorano su questa.
        bando.update(riallineata[1] or {})
        if bando.get("slug") and bando["slug"] not in slug_modificati:
            slug_modificati.append(str(bando["slug"]))
    return novita


def _novita_data(evento: Mapping[str, Any]) -> dict[str, Any]:
    """La novita' di una data per `riscrivi_scheda`, nella forma del monitor."""
    try:
        from . import rigenera
        return rigenera.novita_da_evento(evento)
    except Exception:                                      # pragma: no cover - difesa
        return {"evento_id": evento.get("id"), "tipo": evento.get("tipo"),
                "campo": evento.get("campo"), "citazione": str(evento.get("citazione") or "")[:400],
                "url_prova": evento.get("url_prova")}


async def _classificazione(
    bando: dict[str, Any],
    url: str,
    fonte_ctx: Mapping[str, Any],
    testo: str,
    catalogo: Mapping[str, Any],
    attuali: Mapping[str, Sequence[int]],
    contatori: dict[str, int],
    cambi: list[dict[str, Any]],
    proposta: dict[str, Any],
    slug_modificati: list[str],
    *,
    dry_run: bool,
) -> list[str]:
    """Junction e FK dalle due letture. Ritorna i nomi delle voci tolte che la
    scheda nomina ancora (per la riscrittura)."""
    # Due letture indipendenti (decisione del lead, §9): le risposte del
    # modello variano, e una voce cambia solo se le due letture concordano.
    prima_lettura, seconda_lettura = await asyncio.gather(
        _classifica(bando, fonte_ctx, testo, catalogo),
        _classifica(bando, fonte_ctx, testo, catalogo),
    )
    fallite = set(prima_lettura.get("_fallite") or ()) | set(seconda_lettura.get("_fallite") or ())
    bando_id = bando.get("id")
    nominati: list[str] = []
    junction_toccate = False
    for dimensione, chiave in JUNCTION:
        if dimensione in fallite:
            # §18.3: la dimensione non si tocca, ma il lavoro non e' completo.
            proposta["incompleto"].append(f"lettura {dimensione}")
            continue
        lettura_a = {int(i) for i in (prima_lettura.get(chiave) or ()) if i is not None}
        lettura_b = {int(i) for i in (seconda_lettura.get(chiave) or ()) if i is not None}
        if not lettura_a or not lettura_b:
            # Zero voci in una lettura non dice niente del bando: non si tocca.
            continue
        if lettura_a != lettura_b:
            contatori["junction_discordi"] += 1
        prima = sorted({int(i) for i in (attuali.get(dimensione) or ())})
        nuovi = concordi(prima, lettura_a, lettura_b)
        if not nuovi or nuovi == prima:
            continue
        if dry_run:
            esito: Mapping[str, Any] = {"cambiato": True, "prima": prima, "dopo": nuovi,
                                        "tolti": [i for i in prima if i not in nuovi]}
        else:
            esito = db.allinea_junction(bando_id, dimensione, nuovi)
        if esito.get("errore") and not esito.get("cambiato"):
            proposta["incompleto"].append(f"junction {dimensione}")
            continue
        if not esito.get("cambiato"):
            continue
        junction_toccate = True
        cambio = {"bando_id": bando_id, "dimensione": dimensione,
                  "prima": list(esito.get("prima") or prima), "dopo": list(esito.get("dopo") or nuovi)}
        if esito.get("parziale"):
            # INSERT fatto, DELETE no: il cambio c'e' (si registra per poterlo
            # togliere con SQL), ma il lavoro non e' completo.
            cambio["parziale"] = True
            contatori["junction_parziali"] += 1
            proposta["incompleto"].append(f"junction {dimensione} a meta'")
        cambi.append(cambio)
        proposta["cambi"].append(cambio)
        contatori["junction_cambiate"] += 1
        logger.info("[rielabora] junction bando={} dim={} prima={} dopo={}",
                    bando_id, dimensione, cambio["prima"], cambio["dopo"])
        nominati.extend(nomi_nel_testo(list(esito.get("tolti") or ()),
                                       list(catalogo.get(dimensione) or ()),
                                       str(bando.get("contenuto") or "")))
    # Un bando che torna da un tentativo incompleto puo' avere le junction gia'
    # allineate e il segno mancato (P2 di #173): si segna comunque, perche' un
    # segno in piu' non fa danni e uno perso nasconde il cambio per sempre.
    gia_incompleto = rielaborazione_incompleta(bando.get("_marcatore"))
    if (junction_toccate or gia_incompleto) and not dry_run:
        # §20.1: le junction sono altre tabelle e il trigger di `bando` non le
        # vede: senza questo l'API (`updated_since`), le sitemap e BandoFit non
        # saprebbero del cambio. Una volta per bando, anche a meta' (le righe
        # inserite ci sono); se non si scrive, il lavoro non e' completo.
        segnato = db.segna_cambiamento_pubblico(bando_id)
        if not (segnato or {}).get("scritto"):
            proposta["incompleto"].append("ultimo_cambiamento_at")
    payload: dict[str, Any] = {}
    for colonna, dimensione in FK:
        if dimensione in fallite:
            proposta["incompleto"].append(f"lettura {dimensione}")
            continue
        valore = prima_lettura.get(colonna)
        if valore != seconda_lettura.get(colonna):
            contatori["fk_discordi"] += 1
            continue
        if valore is None or valore == bando.get(colonna):
            continue
        payload[colonna] = valore
    scritte: list[str] = list(payload)
    if payload and not dry_run:
        esito_fk = db.aggiorna_fk_bando(bando_id, payload) or {}
        ignorate = set(esito_fk.get("ignorate") or ())
        scritte = [c for c in payload if c not in ignorate] if esito_fk.get("scritto") else []
        if len(scritte) < len(payload):
            proposta["incompleto"].append("fk")
    for colonna in scritte:
        # §18.3: `cambi` e `fk_cambiate` dicono solo cio' che e' stato scritto
        # (nel dry-run: cio' che si scriverebbe).
        cambio = {"bando_id": bando_id, "dimensione": colonna,
                  "prima": bando.get(colonna), "dopo": payload[colonna]}
        cambi.append(cambio)
        proposta["cambi"].append(cambio)
        contatori["fk_cambiate"] += 1
        logger.info("[rielabora] fk bando={} {} prima={} dopo={}",
                    bando_id, colonna, cambio["prima"], payload[colonna])
        bando[colonna] = payload[colonna]
    return nominati


async def _riscrivi(
    bando: Mapping[str, Any],
    url: str,
    novita_date: Sequence[Mapping[str, Any]],
    nominati: Sequence[str],
    contatori: dict[str, int],
    proposta: dict[str, Any],
    slug_modificati: list[str],
    *,
    spesa: bilancio.Contatori,
    dry_run: bool,
) -> None:
    """Una sola riscrittura per bando con la skill SEO di M3 (§6, §9): le date
    che la sostituzione senza modello non ha portato in prosa, e le voci tolte
    che la scheda nomina ancora (la prosa direbbe una cosa che la pagina non
    dice piu')."""
    novita = [dict(v) for v in novita_date]
    if nominati:
        novita.append({"tipo": "rettifica", "campo": "classificazione", "url_prova": url,
                       "citazione": None, "non_piu_valide": list(nominati)})
    if not novita:
        return
    proposta["riscrittura"] = {"nominati": list(nominati)}
    if novita_date:
        proposta["riscrittura"]["date"] = [str(v.get("campo")) for v in novita_date]
    if dry_run:
        # Nel dry-run la riscrittura si elenca e non si fa: Opus costa, e la
        # prova serve a vedere le proposte, non a pagarle.
        return
    bando_id = bando.get("id")
    riscrivi = _riscrittore()
    if riscrivi is None:
        contatori["riscritture_non_disponibili"] += 1
        _accoda(bando_id, novita, contatori, proposta)
        return
    try:
        # `riscrivi_scheda` conta da se' la spesa su `spesa`: qui il contesto di
        # `conta_spesa` si spegne, altrimenti l'involucro del client la
        # conterebbe una seconda volta. I tetti sono vuoti perche' quello del
        # backfill lo controlla `run` prima di ogni bando.
        with conta_spesa(None):
            esito_riscrittura = await riscrivi(bando_id, novita, spesa=spesa,
                                               tetti=bilancio.Tetti())
    except Exception as e:
        contatori["riscritture_non_riuscite"] += 1
        logger.warning("[rielabora] scheda del bando {} non riscritta: {}", bando_id, e)
        _accoda(bando_id, novita, contatori, proposta)
        return
    if getattr(esito_riscrittura, "scritto", False) or getattr(esito_riscrittura, "esito", "") == "scritta":
        contatori["riscritture"] += 1
        slug = getattr(esito_riscrittura, "slug", None) or bando.get("slug")
        if slug and slug not in slug_modificati:
            slug_modificati.append(str(slug))
    else:
        # Fallita, rinviata per spesa o saltata: le novita' vanno al monitor.
        contatori["riscritture_non_riuscite"] += 1
        _accoda(bando_id, novita, contatori, proposta)


def _accoda(bando_id: Any, novita: Sequence[Mapping[str, Any]], contatori: dict[str, int],
            proposta: dict[str, Any]) -> None:
    """Le novita' di una riscrittura non riuscita nella coda `__riscrittura__`
    del monitor (P2 di #160): al giro dopo la data e' gia' in colonna e la
    rielaborazione non la rivedrebbe piu', quindi senza la coda la prosa
    resterebbe vecchia per sempre. Una coda non scritta lascia il lavoro
    incompleto (§18.3)."""
    esito = db.accoda_riscrittura(bando_id, list(novita))
    if (esito or {}).get("scritto"):
        contatori["riscritture_in_coda"] += 1
        return
    proposta["incompleto"].append("coda riscrittura")


__all__ = ["run", "run_comando", "marcatore", "citazione_provata", "serve_transizione",
           "nomi_nel_testo", "concordi", "STEP", "PARALLELO"]
