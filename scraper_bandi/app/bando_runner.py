"""Orchestratore step 2: scraping bandi da tutte le fonti `ready` + `attivo`.

Flusso:
  1. SELECT fonti ready+attivo dal DB (sequenziale).
  2. Per ogni fonte: lookup nel registro con `registro.trova` (chiave
     NORMALIZZATA: i `link` in tabella e le chiavi di SCRAPER_CONFIG
     differiscono per slash finale, percent-encoding, ordine dei parametri e
     frammento — fix 8.a.8, 25 fonti senza configurazione).
  3. Istanzia il scraper (factory get_scraper) + invoca scrape(fonte).
  4. Compose record con hash_bando (SHA256 fonte_id|link o fonte_id|titolo_norm;
     raw_data['hash_senza_link']=True forza la chiave «senza link» anche con link).
  5. **Segnali (v11, piano §6.1)**: si rileggono le righe gia' in tabella per
     `hash_bando` e si confronta il listing con `segnali.confronta`. Da qui
     escono due cose: i soli record **davvero** cambiati (gli altri non si
     riscrivono: su Obiettivo Europa erano ~1 419 UPDATE per giro per il solo
     `deadline_days_left`, che scala di 1 ogni notte) e gli eventi interni
     `segnale_fonte`, che alzano la priorita' del controllo del monitor.
     **Nessuna data e nessuno stato vengono scritti qui**: un diff di listing
     non e' una prova (§4).
  6. UPSERT in batch in `bando` (on_conflict=hash_bando). Saltato con dry_run.
  6-bis. `ultimo_visto_in_fonte_at` per ogni hash visto e `priorita_controllo`
     per ogni hash con un segnale, in `bando_controllo` (§6.1, passi 4 e 5).
     Sono i due passi senza i quali i segnali non arrivano da nessuna parte:
     la presenza nel listing e' il «prima» di `sparito_dalla_fonte`, e la
     priorita' e' cio' che il monitor legge per decidere chi guardare prima.
  7. Counters cumulativi loggati + una riga `fonte_run` per fonte.

Opzioni di `run(dry_run=False, limit=None)`: `limit` tronca la lista delle
fonti ready, `dry_run` non chiama upsert_bandi e logga i contatori per fonte.
I default riproducono il comportamento storico (`run()` senza argomenti e' la
firma usata da backend/app/bandi_pipeline.py).

Throttle: gestito a livello http.py (delay 1s tra request stesso host).
Concorrenza: sequenziale per fonte (1 alla volta).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from . import segnali as segnali_mod
from . import telemetria
from .db import select_fonti_ready, upsert_bandi
from .logger import logger
from .normalize import hash_bando, is_valid_http_url, normalize_titolo
from .registro import trova as trova_configurazione
from .scraper_config import SCRAPER_CONFIG
from .scrapers import BandoItem, get_scraper

# Colonne che servono al confronto dei segnali. Sono tutte gia' in tabella
# oggi, tranne le ultime due: quelle si chiedono solo se esistono davvero
# (`db.controllo`), altrimenti PostgREST risponde 42703 e il giro si ferma.
COLONNE_CONFRONTO: tuple[str, ...] = (
    "id", "fonte_id", "hash_bando", "tipo_link", "titolo_raw", "link_bando",
    "raw_data", "data_scadenza", "data_apertura", "ora_scadenza",
    "stato_bando", "stato_processing", "slug",
)
COLONNE_CONFRONTO_NUOVE: tuple[str, ...] = (
    "pubblicato", "data_apertura_verificata",
)
# Colonne che vivono in `bando_controllo`, non in `bando`: si leggono a parte e
# si fondono nelle righe passate a `segnali.confronta`. `ultimo_visto_in_fonte_at`
# e' quella senza la quale `segnali.spariti()` scarta ogni riga («ultimo IS NOT
# NULL»), quindi `sparito_dalla_fonte` non potrebbe mai essere emesso.
COLONNE_CONTROLLO_LETTE: tuple[str, ...] = (
    "bando_id", "ultimo_visto_in_fonte_at", "priorita_controllo",
)
TABELLA_CONTROLLO = "bando_controllo"
TABELLA_FONTE_RUN = "fonte_run"
BLOCCO_LETTURA = 200          # hash per richiesta: `in.()` ha un limite di URL


def _build_record(item: BandoItem) -> dict[str, Any]:
    """Compone il dict DB-ready per un BandoItem. Calcola hash_bando.

    Strategia hash:
      - Bando CON link  -> SHA256(fonte_id|link_bando)
      - Bando SENZA link -> SHA256(fonte_id|source_url|row_index|titolo_norm)
        I campi source_url e row_index sono presi da raw_data se presenti.
        Servono per evitare collisioni intra-batch quando titoli ripetuti
        (es. tutte le righe del PDF hanno titolo='Avviso pubblico').
        Idempotente al re-run dello stesso file (source_url + row_index stabili).
      - raw_data['hash_senza_link'] is True -> chiave «senza link» ANCHE se
        link_bando e' valorizzato. Serve ai parser dei calendari (CSV con
        colonna LINK|URL): la riga era gia' in DB con l'hash senza link, il
        link viene solo aggiunto e non nasce un doppione. Record senza la
        chiave: comportamento invariato. Se con la chiave mancano tutti i
        discriminatori si ripiega sull'hash del link (nessuna riga precedente
        puo' esistere: sarebbe stata scartata).
    """
    raw = item.raw_data or {}
    link_valido = bool(item.link_bando) and is_valid_http_url(item.link_bando)
    forza_senza_link = raw.get("hash_senza_link") is True

    if link_valido and not forza_senza_link:
        h = hash_bando(item.fonte_id, item.link_bando)
    else:
        # Bando senza link (o con link ma chiave forzata): hash con
        # discriminatori extra per evitare collisioni.
        source_url = str(raw.get("source_url") or "")
        row_index = str(raw.get("row_index") if raw.get("row_index") is not None else "")
        page = str(raw.get("page") if raw.get("page") is not None else "")
        t_norm = normalize_titolo(item.titolo_raw or "")

        # Necessario almeno uno tra: titolo significativo, row_index, source_url.
        if not t_norm and not row_index and not source_url:
            if link_valido:
                h = hash_bando(item.fonte_id, item.link_bando)  # ripiego sul link
            else:
                return {}  # skip: nessun discriminatore utile
        else:
            key = f"{source_url}|p={page}|r={row_index}|t={t_norm}"
            h = hash_bando(item.fonte_id, key)

    return {
        "fonte_id": item.fonte_id,
        "hash_bando": h,
        "tipo_link": item.tipo_link,
        "link_bando": item.link_bando,
        "titolo_raw": item.titolo_raw,
        "descrizione_raw": item.descrizione_raw,
        "raw_data": item.raw_data,
    }


def leggi_esistenti(hash_bandi: list[str]) -> dict[str, dict[str, Any]]:
    """`hash_bando -> riga di bando` per i record appena letti (sola lettura).

    Si chiedono le sole colonne che servono al confronto, e quelle nuove solo
    se `db.controllo` conferma che esistono: prima delle migrazioni una
    `select=pubblicato` risponderebbe 42703 e fermerebbe lo scrape di TUTTE le
    fonti per una colonna che serve a un'ottimizzazione.

    Un errore qui **non** e' fatale: si ritorna un dizionario vuoto, il
    confronto vede tutto come nuovo e il giro si comporta come prima di v11.
    """
    if not hash_bandi:
        return {}
    try:
        from .db import controllo, get_supabase
        colonne = list(COLONNE_CONFRONTO)
        for nome in COLONNE_CONFRONTO_NUOVE:
            if controllo.ha("bando", nome):
                colonne.append(nome)
        sb = get_supabase()
        righe: dict[str, dict[str, Any]] = {}
        for i in range(0, len(hash_bandi), BLOCCO_LETTURA):
            blocco = hash_bandi[i:i + BLOCCO_LETTURA]
            risposta = (
                sb.table("bando").select(",".join(colonne))
                .in_("hash_bando", blocco).execute()
            )
            for riga in getattr(risposta, "data", None) or []:
                chiave = riga.get("hash_bando")
                if chiave:
                    righe[str(chiave)] = riga
        _fondi_controlli(righe, controllo, sb)
        return righe
    except Exception as e:
        logger.warning("[bando_runner] rilettura per i segnali fallita, degrado: {}", e)
        return {}


def _fondi_controlli(righe: dict[str, dict[str, Any]], controllo: Any, sb: Any) -> None:
    """Porta dentro le colonne calde di `bando_controllo` (§6.1).

    Muta `righe` in luogo. Se la tabella non c'e' ancora non fa niente: il
    confronto perde la sparizione e i bonus di priorita', ma non la lettura.
    """
    try:
        if not controllo.tabella_esiste(TABELLA_CONTROLLO):
            return
        presenti = controllo.colonne(TABELLA_CONTROLLO)
        colonne = [c for c in COLONNE_CONTROLLO_LETTE if not presenti or c in presenti]
        if "bando_id" not in colonne or len(colonne) < 2:
            return
        per_id = {r["id"]: r for r in righe.values() if r.get("id") is not None}
        identificativi = list(per_id)
        for i in range(0, len(identificativi), BLOCCO_LETTURA):
            blocco = identificativi[i:i + BLOCCO_LETTURA]
            risposta = (
                sb.table(TABELLA_CONTROLLO).select(",".join(colonne))
                .in_("bando_id", blocco).execute()
            )
            for riga in getattr(risposta, "data", None) or []:
                destinazione = per_id.get(riga.get("bando_id"))
                if destinazione is None:
                    continue
                for nome, valore in riga.items():
                    if nome != "bando_id":
                        destinazione[nome] = valore
    except Exception as e:
        logger.warning("[bando_runner] colonne di {} non lette, degrado: {}",
                       TABELLA_CONTROLLO, e)


def scrivi_segnali(confronto: Any, fonte: Mapping[str, Any]) -> int:
    """Registra gli eventi interni del confronto. No-op finche' la 02 non c'e'.

    Gli eventi di §6.1 sono **sempre interni**: nessun cursore, `leggibile` e
    `in_aggiornamenti` a false. Non li vede nessuno fuori dalla pipeline, e
    servono solo a dire al monitor da dove cominciare.
    """
    righe = [s.come_riga() for s in confronto.segnali + confronto.spariti]
    if not righe:
        return 0
    try:
        from .db import controllo, get_supabase
        if not controllo.tabella_esiste("bando_evento"):
            logger.info(
                "[bando_runner] bando_evento non esiste ancora: {} segnali non scritti "
                "(fonte_id={})", len(righe), fonte.get("id"),
            )
            return 0
        colonne = controllo.colonne("bando_evento")
        payload = [{k: v for k, v in r.items() if k in colonne} for r in righe]
        payload = [p for p in payload if p.get("bando_id") is not None]
        if not payload:
            return 0
        get_supabase().table("bando_evento").insert(payload).execute()
        return len(payload)
    except Exception as e:
        logger.warning("[bando_runner] scrittura dei segnali fallita: {}", e)
        return 0


def aggiorna_controlli(
    confronto: Any,
    esistenti: Mapping[str, Mapping[str, Any]],
    *,
    adesso: datetime | None = None,
    client: Any | None = None,
    strumento: Any | None = None,
) -> int:
    """I due passi di §6.1 fra l'upsert e gli eventi. Ritorna le righe scritte.

    1. **`ultimo_visto_in_fonte_at`** per ogni hash visto in questo giro. E'
       il «prima» di `segnali.spariti()`: senza di esso la condizione
       «ultimo IS NOT NULL» scarta ogni riga e l'evento `sparito_dalla_fonte`
       non puo' nascere mai;
    2. **`priorita_controllo`** per ogni hash con un segnale, al massimo fra
       quella gia' scritta e quella nuova. E' cio' che porta il 90 del
       mismatch `deadline_label` e il bonus «+20 segnale C» dentro la coda di
       `monitoraggio.priorita()`. Calcolarla e buttarla, come faceva il
       runner, equivaleva a non avere i segnali C.

    Due UPSERT in blocco, non uno per riga, e chiavi uniformi in ciascuno:
    PostgREST aggiorna le sole colonne presenti nel payload, quindi mescolare
    righe con chiavi diverse scriverebbe NULL dove non c'era niente da dire.
    Degrada in silenzio (0) se `bando_controllo` non esiste ancora.
    """
    visti = list(getattr(confronto, "visti", ()) or ())
    priorita = dict(getattr(confronto, "priorita", {}) or {})
    if not visti and not priorita:
        return 0
    try:
        from .db import controllo as predefinito, get_supabase
        controllo = strumento if strumento is not None else predefinito
        if not controllo.tabella_esiste(TABELLA_CONTROLLO):
            logger.info(
                "[bando_runner] {} non esiste ancora: {} presenze e {} priorita' non scritte",
                TABELLA_CONTROLLO, len(visti), len(priorita),
            )
            return 0
        presenti = controllo.colonne(TABELLA_CONTROLLO)
        sb = client if client is not None else get_supabase()
        momento = (adesso or datetime.now(timezone.utc)).isoformat()
        scritte = 0

        if not presenti or "ultimo_visto_in_fonte_at" in presenti:
            righe = [
                {"bando_id": esistenti[h]["id"], "ultimo_visto_in_fonte_at": momento}
                for h in visti
                if h in esistenti and esistenti[h].get("id") is not None
            ]
            scritte += _upsert_controllo(sb, righe)

        if priorita and (not presenti or "priorita_controllo" in presenti):
            righe = []
            for chiave, valore in priorita.items():
                riga = esistenti.get(chiave)
                if not riga or riga.get("id") is None:
                    continue
                attuale = riga.get("priorita_controllo")
                try:
                    valore = max(int(valore), int(attuale))
                except (TypeError, ValueError):
                    valore = int(valore)
                righe.append({"bando_id": riga["id"],
                              "priorita_controllo": max(0, min(100, valore))})
            scritte += _upsert_controllo(sb, righe)
        return scritte
    except Exception as e:
        logger.warning("[bando_runner] aggiornamento di {} fallito: {}", TABELLA_CONTROLLO, e)
        return 0


def _upsert_controllo(sb: Any, righe: list[dict[str, Any]]) -> int:
    """UPSERT a blocchi su `bando_controllo`. Un errore vale 0, non un'eccezione."""
    scritte = 0
    for i in range(0, len(righe), BLOCCO_LETTURA):
        blocco = righe[i:i + BLOCCO_LETTURA]
        if not blocco:
            continue
        try:
            sb.table(TABELLA_CONTROLLO).upsert(blocco, on_conflict="bando_id").execute()
            scritte += len(blocco)
        except Exception as e:
            logger.warning("[bando_runner] upsert di {} righe in {} fallito: {}",
                           len(blocco), TABELLA_CONTROLLO, e)
    return scritte


def conteggi_da_fonte_run(
    fonti: Sequence[Mapping[str, Any]],
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> dict[Any, int]:
    """`fonte_id -> elementi dell'ultimo giro`, dalla tabella `fonte_run`.

    Alimenta la guardia di §6.1 «la fonte non si e' dimezzata»: senza un
    «prima» quella guardia non scatta mai, e un listing che collassa a meta'
    produce centinaia di `sparito_dalla_fonte` per un guasto della fonte.

    `items` e' la colonna del conteggio; se e' NULL si ripiega sulla somma di
    cio' che c'e' (nuovi + cambiati + identici), che e' una sottostima — e una
    sottostima e' il verso prudente: la guardia scatta prima, non dopo.
    """
    identificativi = [f.get("id") for f in fonti if f.get("id") is not None]
    if not identificativi:
        return {}
    try:
        from .db import controllo as predefinito, get_supabase
        controllo = strumento if strumento is not None else predefinito
        if not controllo.tabella_esiste(TABELLA_FONTE_RUN):
            return {}
        presenti = controllo.colonne(TABELLA_FONTE_RUN)
        volute = ("fonte_id", "items", "nuovi", "cambiati", "identici", "creato_at")
        colonne = [c for c in volute if not presenti or c in presenti]
        if "fonte_id" not in colonne:
            return {}
        sb = client if client is not None else get_supabase()
        righe = (
            sb.table(TABELLA_FONTE_RUN).select(",".join(colonne))
            .in_("fonte_id", identificativi)
            .order("creato_at", desc=True).limit(len(identificativi) * 4)
            .execute().data or []
        )
    except Exception as e:
        logger.warning("[bando_runner] conteggi da {} non letti: {}", TABELLA_FONTE_RUN, e)
        return {}

    conteggi: dict[Any, int] = {}
    for riga in righe:                       # ordinate dal piu' recente
        fonte_id = riga.get("fonte_id")
        if fonte_id is None or fonte_id in conteggi:
            continue
        elementi = riga.get("items")
        if not isinstance(elementi, int):
            elementi = sum(
                int(riga.get(c) or 0) for c in ("nuovi", "cambiati", "identici"))
        conteggi[fonte_id] = int(elementi)
    return conteggi


async def run(
    dry_run: bool = False,
    limit: int | None = None,
    *,
    leggi: Callable[[list[str]], dict[str, dict[str, Any]]] | None = None,
    scrivi: Callable[[Any, Mapping[str, Any]], int] | None = None,
    marca: Callable[[Any, Mapping[str, Mapping[str, Any]]], int] | None = None,
    conteggi_precedenti: Mapping[Any, int] | None = None,
) -> dict[str, int]:
    """Esegue lo scraping completo. Ritorna counters per il log finale.

    Args:
        dry_run: non chiama upsert_bandi; logga i contatori per fonte.
        limit: considera solo le prime N fonti ready+attivo (smoke test).
        leggi/scrivi/marca: punti di iniezione dell'I/O dei segnali (test).
            `marca` scrive `ultimo_visto_in_fonte_at` e `priorita_controllo`
            in `bando_controllo`.
        conteggi_precedenti: `fonte_id -> elementi dell'ultimo giro`, per la
            guardia di §6.1 («la fonte non si e' dimezzata»). Se non passato
            si legge da `fonte_run`.
    """
    started = time.monotonic()
    logger.info(
        "[bando_runner] === START scraping bandi{} ===",
        " (DRY-RUN: nessuna scrittura)" if dry_run else "",
    )

    fonti = select_fonti_ready()
    if limit is not None:
        n_ready = len(fonti)
        fonti = fonti[:max(limit, 0)]
        logger.info(
            "[bando_runner] --limit {}: considero {} fonti su {} ready+attivo",
            limit, len(fonti), n_ready,
        )
    logger.info("[bando_runner] processero' {} fonti ready+attivo", len(fonti))

    overall = {
        "fonti_totali": len(fonti),
        "fonti_processate": 0,
        "fonti_skipped_no_strategy": 0,
        "fonti_skipped_skip_strategy": 0,
        "fonti_errors": 0,
        "bandi_estratti": 0,
        "bandi_con_link": 0,
        "bandi_senza_link": 0,
        "bandi_upsert_processed": 0,
        # v11 (§6.1): il risparmio e' misurabile solo se lo si conta.
        "bandi_identici": 0,
        "bandi_cambiati": 0,
        "bandi_nuovi": 0,
        "segnali": 0,
        "spariti": 0,
        "controlli_aggiornati": 0,
    }

    lettore = leggi if leggi is not None else leggi_esistenti
    scrittore = scrivi if scrivi is not None else scrivi_segnali
    marcatore = marca if marca is not None else aggiorna_controlli
    # La guardia «la fonte non si e' dimezzata» ha bisogno di un «prima»: se
    # il chiamante non lo passa, lo si va a prendere in `fonte_run`.
    precedenti = dict(conteggi_precedenti or {})
    if not precedenti and not dry_run and fonti:
        precedenti = conteggi_da_fonte_run(fonti)

    for idx, fonte in enumerate(fonti, start=1):
        url = fonte["link"]
        fonte_id = fonte["id"]
        avvio_fonte = time.monotonic()
        # Chiave NORMALIZZATA, non uguaglianza di stringa (fix 8.a.8).
        cfg = trova_configurazione(url)

        if not cfg:
            logger.warning(
                "[bando_runner] {}/{} fonte_id={} url={} -- NO CONFIG IN REGISTRY, skip",
                idx, len(fonti), fonte_id, url,
            )
            overall["fonti_skipped_no_strategy"] += 1
            continue

        strategy_name = cfg.get("strategy", "skip_no_bandi")
        params = {k: v for k, v in cfg.items() if k != "strategy"}

        if strategy_name == "skip_no_bandi":
            logger.info(
                "[bando_runner] {}/{} fonte_id={} url={} strategy=skip ({})",
                idx, len(fonti), fonte_id, url, params.get("reason", ""),
            )
            overall["fonti_skipped_skip_strategy"] += 1
            continue

        logger.info(
            "[bando_runner] {}/{} fonte_id={} strategy={} url={}",
            idx, len(fonti), fonte_id, strategy_name, url,
        )

        # Istanzia scraper
        try:
            scraper = get_scraper(strategy_name, **params)
        except Exception as e:
            logger.exception(
                "[bando_runner] fonte_id={} get_scraper fallito strategy={}: {}",
                fonte_id, strategy_name, e,
            )
            overall["fonti_errors"] += 1
            continue

        # Esegui scraping
        try:
            items = await scraper.scrape(fonte)
        except Exception as e:
            logger.exception(
                "[bando_runner] fonte_id={} scrape fallito: {}",
                fonte_id, e,
            )
            overall["fonti_errors"] += 1
            continue

        # Compose record + counters
        records: list[dict[str, Any]] = []
        n_con_link = 0
        n_senza_link = 0
        for it in items:
            rec = _build_record(it)
            if not rec:
                continue
            records.append(rec)
            if rec["link_bando"]:
                n_con_link += 1
            else:
                n_senza_link += 1

        # --- segnali (§6.1): fra la composizione dei record e l'upsert ------
        #
        # L'ordine e' quello del piano: rilettura per hash -> confronto ->
        # upsert dei soli cambiati -> eventi. Se la rilettura degrada (tabella
        # irraggiungibile) il confronto vede tutto come nuovo e il giro si
        # comporta esattamente come prima di v11: nessuna riga persa.
        esistenti: dict[str, dict[str, Any]] = {}
        if records:
            try:
                esistenti = lettore([r["hash_bando"] for r in records if r.get("hash_bando")])
            except Exception as e:
                logger.warning("[bando_runner] fonte_id={} rilettura fallita: {}", fonte_id, e)
                esistenti = {}

        confronto = segnali_mod.confronta(
            fonte, records, esistenti,
            esito=getattr(scraper, "ultimo_esito", None),
            elementi_giro_precedente=precedenti.get(fonte_id),
        )
        da_scrivere = list(confronto.da_scrivere)

        if records and dry_run:
            # Nessuna scrittura: solo i contatori che il giro reale scriverebbe.
            logger.info(
                "[bando_runner] DRY-RUN fonte_id={} -> upsert_bandi saltato per {} record "
                "({} con link, {} senza link)",
                fonte_id, len(records), n_con_link, n_senza_link,
            )
        elif da_scrivere:
            try:
                res = upsert_bandi(da_scrivere)
                overall["bandi_upsert_processed"] += res["processed"]
            except Exception as e:
                logger.exception("[bando_runner] fonte_id={} upsert fallito: {}", fonte_id, e)
                overall["fonti_errors"] += 1
                continue
        elif records:
            logger.info(
                "[bando_runner] fonte_id={} -> nessuna riga cambiata: {} record identici, "
                "upsert saltato", fonte_id, confronto.identici,
            )

        # Passi 4 e 5 di §6.1, dopo l'upsert e prima degli eventi: la presenza
        # nel listing e la priorita' del prossimo controllo. Senza, meta' dei
        # segnali si ferma qui e il monitor non li vede mai.
        marcati = 0
        if not dry_run and (confronto.visti or confronto.priorita):
            try:
                marcati = marcatore(confronto, esistenti)
            except Exception as e:
                logger.warning(
                    "[bando_runner] fonte_id={} presenze/priorita' non scritte: {}",
                    fonte_id, e)

        segnalati = 0
        if not dry_run and (confronto.segnali or confronto.spariti):
            try:
                segnalati = scrittore(confronto, fonte)
            except Exception as e:
                logger.warning("[bando_runner] fonte_id={} segnali non scritti: {}", fonte_id, e)

        overall["fonti_processate"] += 1
        overall["bandi_estratti"] += len(records)
        overall["bandi_con_link"] += n_con_link
        overall["bandi_senza_link"] += n_senza_link
        overall["bandi_identici"] += confronto.identici
        overall["bandi_cambiati"] += len(confronto.cambiati)
        overall["bandi_nuovi"] += len(confronto.nuovi)
        overall["segnali"] += len(confronto.segnali)
        overall["spariti"] += len(confronto.spariti)
        overall["controlli_aggiornati"] += marcati

        _telemetria_fonte(fonte_id, confronto, scraper, time.monotonic() - avvio_fonte, dry_run)

        logger.info(
            "[bando_runner] fonte_id={} -> {} bandi ({} con link, {} senza link) "
            "| nuovi={} cambiati={} identici={} segnali={} spariti={} scritti={} "
            "controlli={}",
            fonte_id, len(records), n_con_link, n_senza_link,
            len(confronto.nuovi), len(confronto.cambiati), confronto.identici,
            len(confronto.segnali), len(confronto.spariti), segnalati, marcati,
        )

    elapsed = time.monotonic() - started
    logger.info(
        "[bando_runner] === DONE in {:.1f}s | counters={} ===",
        elapsed, overall,
    )
    return overall


def _telemetria_fonte(
    fonte_id: Any, confronto: Any, scraper: Any, durata: float, dry_run: bool,
) -> None:
    """Una riga `fonte_run` per fonte (§6.1). Degrada da sola se la 02 non c'e'.

    Serve a rispondere con una query, invece che leggendo i log, alla domanda
    «da quando la fonte 237 non trova piu' niente?».
    """
    if dry_run:
        return
    esito = segnali_mod.esito_da(getattr(scraper, "ultimo_esito", None))
    riga = telemetria.FonteRun(
        fonte_id=int(fonte_id) if isinstance(fonte_id, int) else 0,
        elementi=len(confronto.nuovi) + len(confronto.cambiati) + confronto.identici,
        nuovi=len(confronto.nuovi),
        cambiati=len(confronto.cambiati),
        durata_s=round(durata, 1),
        troncato=bool(esito.troncato) if esito is not None else True,
    )
    try:
        telemetria.scrivi_fonte_run(riga)
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[bando_runner] fonte_run non scritta: {}", e)
