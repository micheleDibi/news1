# Contratto interno: giro 3 dei bandi (dall'01/10/2026)

Proprietario: il lead. Ogni modifica passa da lui (richiesta `CONTRATTO:`). Branch `claude/bandi-giro-3`.
Piano approvato da Michele l'01/10/2026. Per la logica di oggi: `docs/bandi-monitor/GUIDA-BANDI.md`. Per il
contratto verso BandoFit: `docs/contratto-db-bandi.md` (aggiornato dal lead per questo giro).

## 0. Regole che valgono per tutti
- **DB in sola lettura dal Mac**: solo GET PostgREST e comandi `--dry-run`. Mai RPC che scrivono. Mai `monitor`,
  `risolvi-fonte`, `seo`, `rielabora-fonte` o `gemelli` senza `--dry-run` dal Mac; `verifica-stato` solo con
  `--dry-run --senza-modello`. Mai stampare valori di `.env`, cookie, token.
- Le SQL le **scrive** `db` e le **applica Michele** nel SQL Editor. Righe di 45 caratteri al massimo; ogni file ha
  intestazione con data, ordine di applicazione e un blocco di verifica; provate su un Postgres 17 effimero
  (`/opt/homebrew/opt/postgresql@17`, porta alta, avvio e stop nello stesso comando).
- I moduli di `scraper_bandi` si importano nei test **per percorso** (c'è un altro package `app` sul `sys.path`).
- `PYTHONDONTWRITEBYTECODE=1`. Nessuna dipendenza nuova.
- Il DB bandi è letto anche da BandoFit: id mai riusati, nessuna riga di `bando` cancellata, slug dei pubblicati
  congelati, un pubblicato non esce mai da `completed`.

## 1. Regola «niente lotti» (permanente)
- **Nessun tetto sul numero di bandi** per giro o per lancio. Spariscono: `RICONTROLLI_PER_GIRO` (60),
  `GEMELLI_FUSIONI_PER_GIRO` (10), `VERIFICA_STATO_TETTO_LETTURE` (40), `VERIFICA_STATO_MAX_CHIUSURE` (20),
  `VERIFICA_STATO_TETTO_INGRESSO` (30), `TETTO_CLASSIFICAZIONI_GIORNO` (30), `TETTO_FETCH_GIRO` (420) come tetto di
  numero, `BLOCCO_APPLICAZIONE` (50), `TETTO_CODA_MONITOR` / `LIMITE_LETTURA_PUBBLICATI` / `TETTO_GEMELLI` (5 000:
  si legge tutto con `_scorri`).
- **Freni ammessi** (solo questi):
  1. cortesia per host: `HOST_THROTTLE_DELAY_S` (1 s) e i ritmi di ObiettivoEuropa già in codice;
  2. **tempo** di ogni passo (§3), con **rotazione**: chi resta fuori parte per primo al giro dopo, in ordine di
     ultimo controllo crescente (mai controllato = primo);
  3. **spesa**: $ (§4) e crediti Firecrawl (invariati);
  4. guardie contro gli errori: freno per host della verifica, prudenza dei gemelli, doppia lettura a 60 ore, gate
     degli eventi.
- **Copertura.** Ogni passo mette nei suoi contatori (riga del passo in `pipeline_run` e sezione nella riga del giro)
  la chiave `copertura`:
  ```json
  {"candidati": 0, "fatti": 0, "rimasti": 0, "motivo_rimasti": null}
  ```
  `rimasti = candidati - fatti`; `motivo_rimasti` ∈ `tempo` | `spesa` | `crediti` | `lock` | `errore` | null.
  Ogni passo mette `copertura` **al primo livello** del dizionario che restituisce; la riga del giro la conserva in
  `contatori.<passo>.copertura` (`bandi_pipeline.CHIAVI_PASSI_SOLO_CONTATORI` e `db.CONTATORI_PIPELINE`). Costruttore
  unico: `telemetria.copertura(candidati, fatti, motivo_rimasti=None) -> dict` (M1); chi scrive prima che esista
  costruisce lo stesso dizionario a mano.
  `salute` mostra la copertura dell'ultimo giro per passo e alza l'allarme `copertura_incompleta` se lo stesso passo
  ha `rimasti > 0` in 4 giri di fila.

## 2. Ordine nuovo del giro (`backend/app/bandi_pipeline.py`)
| N. | chiave in `state["steps"]` | modulo / funzione | quando |
|---|---|---|---|
| 1 | `discover` | come oggi | ogni giro |
| 2 | `scrape` | come oggi | ogni giro |
| 3 | `domini` | `app.fonte_ufficiale.run_domini_import(scarica_enti=True)` | solo giro 06, se nel mese non c'è un import `ok` (spostato prima del resolver precoce) |
| 4 | `resolver_precoce` | `app.fonte_ufficiale.run(modo="precoce")` | ogni giro |
| 5 | `preprocess` | come oggi, sulla fonte ufficiale (§8) | ogni giro |
| 6 | `enrich` | come oggi, sulla fonte ufficiale (§8) | ogni giro |
| 7 | `resolver` | `app.fonte_ufficiale.run(modo="nuovi")` | ogni giro (seconda passata) |
| 8 | `ricontrolli` | `app.fonte_ufficiale.run(modo="ricontrolli")`, **senza `limit`** | giri di `MONITOR_GIRI` |
| 9 | `verifica_stato_ingresso` | come oggi | ogni giro |
| 10 | `seo` | come oggi | ogni giro |
| 11 | `link_verifica` | `app.fonte_ufficiale.run_link_verifica(giro=…)` | giri di `MONITOR_GIRI` |
| 12 | `rielaborazione` | `app.rielabora_fonte.run(giro=…)` | giri di `MONITOR_GIRI` |
| 13 | `monitor` | come oggi | giri di `MONITOR_GIRI` |
| 14 | `verifica_stato` | come oggi | giri di `MONITOR_GIRI` |
| 15 | `gemelli` | `app.gemelli.esegui_passo` | giri di `MONITOR_GIRI` (non più solo 06) |

- `MONITOR_GIRI` vale per difetto **tutte e quattro** le ore (`00:00,06:00,12:00,18:00`). Il giro di avvio (`boot`) e
  il lancio da riga di comando restano come oggi: il `boot` non fa la manutenzione (8, 11-15).
- I passi nuovi (4, 11, 12) si caricano con `_passo_se_esiste`: un modulo assente vale «saltato, tutto bene».
- Lucchetto del giro: `LOCK_TTL_S` = 6 ore (oggi 4): la somma dei tempi massimi dei passi più la catena d'ingresso
  può superare 5 ore nel primo giro dopo il deploy. Lucchetto `bandi_resolver`: `TEMPO_RICONTROLLI_S + 1800`.
- Allarmi di configurazione: `Settings.configurazione_scartate` elenca i NOMI delle variabili di §3 scartate (fuori
  intervallo o fuori enum, tornate al default); `telemetria` emette `configurazione:<nome>` (M1).

## 3. Interruttori, tempi, tetti (`scraper_bandi/app/settings.py`)
**Nuovi** (un valore assente o sconosciuto vale il default; fuori intervallo → default + allarme
`configurazione:<nome>`, come `INTERVALLI_VERIFICA`):

| Variabile | campo `Settings` | default | ammessi |
|---|---|---|---|
| `GEMELLI_MODALITA` | `gemelli_modalita` | `ombra` | ombra, attivo |
| `DOMINI_MODALITA` | `domini_modalita` | `ombra` | ombra, attivo |
| `TEMPO_PRECOCE_S` | `tempo_precoce_s` | 600 | 60-7200 |
| `TEMPO_RICONTROLLI_S` | `tempo_ricontrolli_s` | 3600 | 60-7200 |
| `TEMPO_LINK_VERIFICA_S` | `tempo_link_verifica_s` | 1200 | 60-7200 |
| `TEMPO_RIELABORAZIONE_S` | `tempo_rielaborazione_s` | 3600 | 60-7200 |
| `TEMPO_MONITOR_S` | `tempo_monitor_s` | 3600 | 60-7200 |

**Cambiati:**
- `VERIFICA_STATO_TETTO_S`: default 1800 (60-3600). Resta l'unico freno di numero della verifica: il tempo.
- `MONITOR_TIPI_ATTIVI`: accetta `tutti` = i 12 tipi del monitor (`eventi.TIPI_MONITOR` o equivalente).
  `sospensione`, `revoca`, `annullamento_revoca` sono **attivi solo se** `db.capacita_sospensioni()` è vero
  (marcatore della migrazione 14, §14) **e** `MONITOR_STATI_ESTESI` è vero; altrimenti restano in ombra senza
  allarme (e `salute` dice «sospensioni in attesa della migrazione 14»).
- `MONITOR_GIRI`: default `00:00,06:00,12:00,18:00`.
- `TETTO_USD_GIORNO`: 5.0 nello scenario `bilanciato` (economico 3.0, massimo 10.0).
- `TETTO_USD_MESE`: 150.0 nello scenario `bilanciato` (economico 90.0, massimo 300.0), **applicato davvero** (§4).
- `VERIFICA_STATO_MODALITA` governa **solo** verifica (5-ter e 14) e sosta. Gemelli (passo 15 e fusione prima della
  pubblicazione) seguono `GEMELLI_MODALITA`; la scrittura dell'import IndicePA segue `DOMINI_MODALITA` (un `--attivo`
  esplicito sul comando vince ancora).

**Dismessi** (tolti in B6, dopo che nessuno li legge più): `TETTO_CLASSIFICAZIONI_GIORNO`, `TETTO_FETCH_GIRO`,
`VERIFICA_STATO_TETTO_LETTURE`, `VERIFICA_STATO_MAX_CHIUSURE`, `VERIFICA_STATO_TETTO_INGRESSO`,
`GEMELLI_FUSIONI_PER_GIRO`. Se uno di questi nomi è nel `.env`, `Settings.variabili_dismesse` ne elenca il **nome**
(mai il valore) e `salute` lo stampa come informazione, non come allarme.

**Invariati:** crediti Firecrawl (`TETTO_CREDITI_GIORNO` 120, `TETTO_CREDITI_MESE` per scenario), ricerche (50),
backfill (8 000 crediti, 60 $), `OE_SCHEDE_GIORNO` 850, `HOST_THROTTLE_DELAY_S`, `MONITOR_MODALITA` (resta `ombra`:
l'attivazione passa da `MONITOR_TIPI_ATTIVI=tutti`, che usa la strada prudente a tre scritture).

## 4. Spesa
- **Meccanismo unico**: ogni passo che chiama un modello conta con `bilancio.Contatori` e
  `bilancio.registra_chiamata(contatori, modello, response.usage, listino)` e scrive la **propria riga**
  `pipeline_run` (`step` = la chiave di §2: `preprocess`, `enrich`, `seo`, `rielaborazione`, …) con
  `contatori.come_dizionario()` più `copertura`. `consumo_oggi` le somma (giornata di Roma).
- **Tetto giornaliero 5 $** e **mensile 150 $** su tutto ciò che è contato in regime (righe non `backfill:*`).
  `db.consumo_oggi()` restituisce anche `crediti_mese` e `usd_mese` (mese di calendario di Roma, stesso filtro
  `conta_nel_regime`, una sola lettura). `telemetria.PipelineRun.come_riga` prende `usd` e `crediti` dai contatori
  quando non sono passati a parte.
- **Chi si ferma e chi no.** La catena d'ingresso (`bilancio.PASSI_INGRESSO` = preprocess, enrich, seo,
  resolver_precoce, resolver) **non si ferma mai** per nessun tetto (né $ né crediti né ricerche): conta e basta. La manutenzione (monitor, ricontrolli, verifica, rigenerazioni
  della scheda di §6) **smette di chiamare il modello** a tetto raggiunto, ma **continua i controlli gratuiti** e non
  perde niente (§5). Motivo nella copertura: `spesa`.
- **Rielaborazione** (§9): step `backfill:rielaborazione`, tetti del backfill (60 $, 8 000 crediti) applicati sulla
  **giornata di Roma** (`db.consumo_passo_oggi(step)` più il lancio), non sul singolo lancio; fuori dal regime. Se la
  lettura del consumo fallisce il passo non parte. Il comando `rielabora-fonte` fuori dal dry-run prende il lucchetto
  `bandi_pipeline` (proprietario `rielabora-fonte:cli`); il passo del giro è già sotto il lucchetto del giro.
- Il tetto mensile si applica sommando le righe del mese di Roma (`bilancio.verifica_mensili` oggi non è chiamata da
  nessuno: va collegata). Allarme `consumo_mensile_alto` all'80 % come oggi.

## 5. Monitor (`app/monitoraggio.py`)
- **Selezione** (in `monitoraggio.seleziona`, sui dati di `db.select_bandi_da_monitorare` senza troncamento):
  - pubblicati, non fusi, fonte `trovata`, stato effettivo `aperto` o `in apertura prossimamente` (anche «da
    verificare»): **tutti, a ogni giro**, senza guardare `prossimo_controllo_at`;
  - `chiuso`: la cadenza decrescente di oggi (3/10/30 giorni, poi 30) fino a 12 mesi;
  - `revocato`, e `chiuso` da più di 12 mesi: **fuori** dalla selezione (oggi rientrano a ogni giro);
  - `sospeso`: come gli aperti (a ogni giro).
- **Ordine**: priorità decrescente, poi ultimo controllo crescente (mai controllato primo), poi `id`. Tetto di tempo
  `TEMPO_MONITOR_S`, rotazione.
- **Spesa finita o modello giù**: la pagina si scarica e si confronta lo stesso. Se è cambiata e non si può
  classificare, **non** si aggiorna l'impronta salvata (né `testo_norm`, né `__link__`): il diff si rivede al giro
  dopo. `classificazioni_rinviate` nei contatori.
- **Tipi**: `MONITOR_TIPI_ATTIVI=tutti` (§3). Strada a tre scritture di oggi (registra → applica se verificato →
  leggibile).
- **Marcatore della rielaborazione**: quando il monitor applica una `rettifica` con `campo` `contenuto` o
  `allegati`, oppure una `riapertura`, chiama `db.azzera_rielaborazione(bando_id)` (§9), così il bando viene
  rielaborato al passo 12 del giro dopo.

## 6. Eventi → bando e scheda (`app/rigenera.py`, `app/bando_seo_runner.py`, `app/seo_skill.py`)
- **Date** (`apertura`, `riapertura`, `proroga`, `rettifica` di data): RPC come oggi, poi la sostituzione senza
  modello di `rigenera.rigenera`. Se il controllo finale fallisce, **riscrittura con Opus** (sotto) invece di lasciare
  il testo vecchio.
- **`nuovo_allegato`**: oltre all'evento, una riga `bando_link` `tipo='allegato'` con l'URL della prova, scritta con
  `db.upsert_bando_link` (non pubblicabile finché `link_verifica` non la verifica, §10).
- **Riscrittura con Opus** per `faq`, `graduatoria`, `esito`, `rettifica` di `contenuto`/`allegati`, `apertura` e
  `riapertura` con testo nuovo: `genera_per_bando` con, in più, l'informazione nuova (tipo, citazione, `url_prova`) e
  la pagina ufficiale; scrive **solo** `contenuto` e `descrizione_breve`; slug e titolo congelati; **una riscrittura
  per bando per giro** anche con più eventi (si uniscono). Conta nei 5 $ (step `rigenerazione_scheda`). A tetto
  raggiunto la riscrittura resta in coda (contatore `riscritture_rinviate`) e si fa al giro dopo.
- Un cambio di **solo stato** non tocca la prosa (il prompt vieta già di nominare lo stato).
- Gli slug delle schede riscritte vanno in `slug_modificati` (IndexNow, oggi rotto sul server: fuori perimetro).

## 7. Resolver (`app/fonte_ufficiale.py`, `app/date_validation.py`)
- **Modo `precoce`** (passo 4):
  - selezione: `stato_processing in ('scraped','processed')`, fonte non `trovata`, dopo il filtro
    `preprocessor._auto_reject`; esclusi i `processed` con `stato_bando` chiuso o revocato (491 righe morte che
    l'enrich non prende mai, misura del 01/10);
  - contesto con una **scadenza provvisoria** da `date_validation.scadenza_provvisoria(bando) -> date | None`,
    funzione pura, senza modello né rete: OE (`deadline_label` via `termine_da_etichetta_oe`), Incentivi
    (`close_date`), Italia Domani (`data_chiusura` via `estrai_date_con_ruolo`), calendari (chiavi con
    scad/chiusur/termine/deadline). Vale **solo il +15**, mai il −15 di `scadenza_diversa`, mai `proroga=True`;
  - niente ricerca a pagamento né arbitro (`ambiente.da_segnale=True`, `arbitro=None`);
  - esito `trovata` → si scrive come oggi; qualsiasi altro esito → **nessuna traccia** (`_togli_verdetto`, niente
    `scrivi_esito`, niente evento `fonte_ufficiale_non_trovata`), così la passata `nuovi` lo riprende con la scadenza
    vera;
  - tempo `TEMPO_PRECOCE_S`; chi resta fuori lo prende la passata `nuovi`.
- **Modo `nuovi`** (passo 7): come oggi.
- **Modo `ricontrolli`** (passo 8):
  - selezione: fonte `in_verifica` o `non_trovata`, pubblicato o `enriched`, e stato **non** `chiuso` né `revocato`;
  - **niente data del prossimo controllo** e niente `limit`: tutti a ogni giro dei `MONITOR_GIRI`, in ordine di
    ultimo controllo crescente; il contatore dei tentativi resta come informazione e non decide più niente;
  - `prossimo_controllo_at` dei bandi `trovata` **resta** quella del monitor (colonna condivisa: non toccarla). Un
    bando che diventa `trovata` adesso riceve `oggi` (seme della coda del monitor), come oggi; uno già `trovata`
    (`--forza`, `--id`) non si tocca;
  - fino a **5 bandi in parallelo**; la cortesia la garantisce il freno per host condiviso fra i lavori paralleli
    (mai due richieste contemporanee allo stesso host, 1 s fra due richieste): non serve raggruppare i bandi per host.
    Misura D1: 698 dei 960 candidati hanno `link_bando` su obiettivoeuropa.com, quindi le schede OE restano in fila;
  - la scheda OE di un bando si legge **al massimo una volta al giorno** (cache per bando e giornata di Roma);
  - tempo `TEMPO_RICONTROLLI_S`, rotazione; lucchetto `bandi_resolver` lungo `TEMPO_RICONTROLLI_S + 1800`.

## 8. Preprocess ed enrich sulla fonte ufficiale
- `dominio_ufficiale.scegli_fonte(bando) -> tuple[str, bool]`: stessa firma e stessa regola di
  `bando_seo_runner.scegli_fonte`, più una guardia: un URL ufficiale che è un PDF (`_RE_PDF`) → si torna a
  `link_bando`. `bando_seo_runner` la **importa** da lì (M3) e la ri-esporta.
- `select_bandi_scraped` e `select_bandi_to_enrich` leggono anche `fonte_ufficiale_url` e `fonte_ufficiale_stato`.
- Preprocess: `analyze_bando(..., url_lettura=...)` scarica `url_lettura` (download, cache, provenienza, lettore per
  ente); il prompt continua a mostrare `link_bando`; l'uscita contiene anche le **citazioni** delle date
  (`_citazioni`). Ripiego: prima l'URL ufficiale, poi `link_bando`, poi `resolve_bando`. Per OE, se la scadenza
  resta vuota, si rilegge `link_bando` dalla cache e si chiama solo `_scadenza_oe_citata` (senza modello).
- Enrich: `scegli_fonte(b)[0]` per il testo; `refine_stato_bando` riceve `{**b, "link_bando": url}`. Le chiamate
  restituiscono un **flag di fallimento** distinto da «nessuna voce» (serve a §9).
- **Cache dello scarico** (`scarico.py`): su un colpo di cache di una risposta httpx «semplice» quando il chiamante
  chiede la pagina principale con ripiego, la voce si **promuove** al ripiego (niente seconda GET verso l'ente).
- **B29**: `analizza_indicepa` scarta gli host di una sola etichetta e i fornitori di posta e hosting di privati
  (almeno `libero.it`, `yahoo.it`, `gmail.com`, `register.it`, più gli equivalenti già noti come condivisi).
  L'01/10 Michele ha importato IndicePA (22 355 righe) e spento con SQL questi 16 host.
- Preprocess ed enrich scrivono la loro riga di spesa (§4).

## 9. Rielaborazione dei pubblicati (`app/rielabora_fonte.py`, nuovo)
- **Chi**: pubblicati, non fusi, con fonte `trovata`, la cui riga `bando_link` della fonte
  (`fonte_ufficiale_link_id`) ha `impronta_contenuto` NULL o non nella forma `rielab:v1:…`. Tutti, tempo
  `TEMPO_RIELABORAZIONE_S`, rotazione per id, fino a 5 in parallelo su host diversi.
- **Cosa**: scarica la pagina ufficiale (`scegli_fonte`), `analyze_bando(url_lettura=…)` e `enrich_bando` senza
  scrivere `stato_processing` (mai `update_bando_enriched`, `update_bandi_postanalysis`, `update_bando_refinement`).
- **Date**: `data_apertura` / `data_scadenza` diverse e **non verificate** (`*_verificata` falso) → evento `rettifica`
  via `bando_registra_evento` con `tipo='rettifica'`, `origine='pipeline'`, `campo` la colonna, `url_prova` la pagina,
  `citazione` NULL (quindi `verificato=false`), `in_aggiornamenti=false`, `metodo='rielaborazione'`, citazione e
  contesto in `gate`; applicato con `p_applica=true`. Coerenza apertura ≤ scadenza con
  `date_validation.check_dates_coherence` prima di proporre. **Mai** `data_pubblicazione`, **mai** uno stato: se la
  data nuova richiede una transizione (chiuso con scadenza futura, in apertura con apertura passata) non si applica,
  si annota (contatore `transizioni_rinviate`) e il bando va in testa alla coda del monitor
  (`db.aggiorna_controllo(id, {"prossimo_controllo_at": adesso, "priorita_controllo": 90})`). Date verificate: non
  si toccano, si annota `discordanze_verificate`.
- **Classificazione** (decisione del lead dopo il dry-run dell'01/10: le letture di Haiku variano): due letture
  indipendenti dell'enrich; un id si aggiunge solo se c'è in tutte e due e si toglie solo se manca in tutte e due; una
  FK cambia solo se le due letture concordano; una dimensione con una chiamata fallita non si tocca.
  `db.allinea_junction(bando_id, dimensione, ids)` per regioni, settori, beneficiari, codici
  ATECO: inserisce gli id nuovi, poi toglie quelli usciti; **non svuota mai** una dimensione piena se la chiamata
  dell'enrich è fallita o ha dato zero voci; aggiorna le tre FK con un UPDATE delle sole tre colonne. Ogni cambio
  resta registrato con prima e dopo (proposta del `PIANO:` di B4, approvata dal lead: per esempio un evento interno o
  le chiavi in `gate`), così si torna indietro con SQL.
- **Scheda**: date cambiate → `rigenera.rigenera` (senza modello) con la stessa conversione del monitor
  (`_testo_del_contenuto` e `_scrittore_json`: il jsonb `contenuto` non si scrive mai come stringa); junction
  cambiate e nominate nel testo →
  riscrittura con Opus come §6. Slug e titolo congelati.
- **Marcatore**: a fine bando `impronta_contenuto = 'rielab:v1:<YYYY-MM-DD>:<sha256 del testo letto>'` sulla riga
  della fonte; `db.azzera_rielaborazione(bando_id)` lo rimette a NULL (§5). Una fonte nuova = riga nuova = marcatore
  NULL: la rielaborazione riparte da sola.
- **Spesa**: step `backfill:rielaborazione` (§4). Comando `python -m app rielabora-fonte --dry-run [--ids 1,2]`
  (dal Mac solo `--dry-run`: stampa le proposte, non scrive).

## 10. Link per la 07 (`app/fonte_ufficiale.py`, `app/bando_seo_runner.py`)
- `link_verifica` diventa il passo 11 del giro, senza tetto di numero, tempo `TEMPO_LINK_VERIFICA_S`, rotazione
  `_da_verificare_ora`.
- **Quarta prova** in `_verifica_link`: l'URL compare nell'HTML della pagina di riferimento scelta con
  `scegli_fonte` (forme di `oe_scheda._forme_href`); scrive `impronta_pagina`, `url_prova`, `trovato_in_fonte_at`.
  **Decisione del lead (01/10, misura D1):** quando la fonte non è `trovata`, la pagina di riferimento può essere
  `link_bando` anche se è un aggregatore (120 dei 160 aperti con righe non pubblicabili sono in questo caso). La
  prova vale solo se il link stesso NON è su un dominio aggregatore o illeggibile (lo garantisce già il trigger di
  `bando_link`) e risponde 2xx; in `url_prova` va la pagina effettiva. È la stessa informazione che il sito mostra
  oggi dalle colonne: la 07 non deve toglierla. Quando la fonte diventa `trovata`, la prova si rifà sulla pagina
  ufficiale al giro successivo di `link_verifica`.
- `fonte_ufficiale.righe_link_da_payload(bando, payload, html_riferimento) -> list[dict]` (B5): righe
  `candidatura` (solo `link_candidatura_source='extracted'`) e `allegato` dal payload SEO validato, con la prova
  calcolata sulla pagina. `bando_seo_runner._do_one` (M3) la chiama dopo un `update_bando_completed` riuscito e
  scrive con `db.upsert_bando_link`. Le colonne vecchie di `bando` restano scritte fino alla 07.
- `db.py:2677-2678` (B30) non legge più dalla vista le tre colonne che la 07 toglie.
- Il sito **non** cambia in questo giro: smette di chiedere le tre colonne solo dopo la misura (fuori giro).

## 11. Gemelli (`app/gemelli.py`)
- Interruttore `GEMELLI_MODALITA`; a ogni giro dei `MONITOR_GIRI`; **senza tetto** di fusioni; si leggono tutti i
  pubblicati. Le guardie di prudenza restano tutte (solo criteri `url` e `riga_calendario`, coppie dirette, titoli
  senza differenze di anno/lotto/edizione, lettura troncata = errore).
- La fusione prima della pubblicazione (`bando_seo_runner`) segue `GEMELLI_MODALITA`.
- **B4**: il conteggio dei link condivisi esclude le righe già fuse.
- Nessuna `fondi-doppioni` come scorciatoia.

## 12. IndicePA (`app/fonte_ufficiale.py`, `app/dominio_ufficiale.py`)
- Già importato l'01/10 da Michele. In codice: la scrittura dell'import segue `DOMINI_MODALITA`; calendario mensile
  invariato (giro 06); il passo si sposta prima del resolver precoce. B29 come §8.

## 13. Verifica dello stato (`app/verifica_stato.py`, `app/ingresso.py`)
- Resta **in ombra** fino al controllo dell'08/10 (Michele). Niente tetti di numero (letture, chiusure, ingresso):
  solo `VERIFICA_STATO_TETTO_S` con rotazione e il freno per host.
- `VERITA_NOTA`: 661135 è stato chiuso dal job orario il 30/09 → va trattato come «chiusura confermata». Regola
  strutturale: `report-verifica-stato --verita` **non** conta come difforme un bando della tabella che è uscito dai
  candidati perché il suo stato effettivo è già quello atteso (es. atteso «chiusura», stato `chiuso`); lo conta come
  `confermato_da_stato`. Test dedicato.

## 14. Sospensione e revoca (i 7 problemi di RIPRESA §4.1 i)
**Migrazione 14** (`backend/sql/bando_v11_14_sospensioni.sql` + rollback, `db`):
1. transizioni ammesse in più: `sospeso → chiuso` (evento `chiusura`), `sospeso → aperto` (evento `riapertura`
   o la fine della sospensione), uscita dal `revocato` con `annullamento_revoca` verso lo stato calcolato dalle date;
2. percorso di correzione: con `origine='redazione'` ogni transizione fra i 5 stati di un pubblicato è ammessa
   (RPC esistente o una nuova `bando_correggi_stato(p_bando_id, p_stato, p_nota)` solo per il ruolo di servizio);
3. `bando_applica_evento` rifiuta (risposta `false`, motivo `superato`) un evento di transizione con `data_evento`
   più vecchia dell'ultima transizione applicata allo stesso bando;
4. un evento rifiutato per transizione non più ammessa (23514) o `superato` viene **marcato** in modo che non torni in
   coda (colonna o chiave da proporre nel `PIANO:` di D2, concordata con M4);
5. marcatore `public.bando_capacita_sospensioni()` → `true` (letto da `db.capacita_sospensioni()`, B1);
6. se cambia la regola di `stato_effettivo` (`tests/stato-bando/casi.json`), cambiano insieme i due gemelli
   (`stato_bando.py` in M4, `stato-bando.ts` in F2). Se `casi.json` non cambia, i gemelli non si toccano.

**Decisioni sul PIANO di D2 (01/10, lead):**
- lista bianca, delta 14 (attore worker): `sospeso → chiuso` (solo con evento `chiusura`), `revocato → aperto | chiuso |
  in apertura prossimamente` (solo con `annullamento_revoca`, stato di arrivo calcolato dalla RPC dalle date se manca
  in `valore_dopo`; M4 passa comunque `{"stato_bando": X}` calcolato col gemello). `sospeso → aperto/in apertura` con
  `riapertura` esistono già: il buco è G5. La regola di `stato_effettivo` NON cambia.
- correzione: RPC `bando_correggi_stato(p_bando_id, p_stato, p_nota) -> jsonb` (solo service_role, solo pubblicati,
  nota obbligatoria, evento `correzione_redazionale` origine `redazione`, `in_aggiornamenti=false`); nessuna riga
  `redazione` nella lista bianca.
- superato: un evento `worker` che cambia lo stato di un pubblicato è superato se esiste un evento dello stesso bando
  già applicato, non scartato, di origine `worker` o `redazione`, che porta uno stato ed è più recente per
  `(least(coalesce(data_evento, giorno_rilevato), giorno_rilevato), id)`, con `giorno_rilevato` = giorno di Roma di
  `rilevato_at`, per tutti e due gli eventi: una data dichiarata nel futuro non rende «superati» gli eventi veri
  arrivati dopo (P1 della revisione #141). Il cron non conta; cron e redazione non sono mai superati.
- marcatura: colonne nuove su `bando_evento`: `scartato_per` (`superato` | `transizione_non_ammessa`),
  `scartato_at`, `scartato_dettaglio` jsonb; nessun grant ad anon. La RPC con `scartato_per` non NULL risponde
  `false`; una transizione non ammessa da un pubblicato viene marcata e risponde `false` invece del 23514
  (breaking change voluto: l'evento nasce e resta marcato). Si rimette in coda a mano azzerando le tre colonne.
- `bando_capacita_sospensioni()` vale true solo se RPC e trigger vivi contengono `v11_14`, le colonne `scartato_*`
  e `bando_correggi_stato` esistono, le 4 righe sono nella lista bianca e c'è la 06. Dopo la 14 non si rieseguono
  né la 04, né la 11, né la 13; il rollback va in ordine inverso, prima la 14.
- `casi.json` e i gemelli `TRANSIZIONI` (`stato_bando.py`, `stato-bando.ts`) con i test relativi li aggiorna `db` in
  D2, in un solo passo atomico (solo dati e test).

**Proroga su un sospeso** (decisione del lead, revisione #153): è ammessa come **sola data**: aggiorna
`data_scadenza` e lo stato resta `sospeso` (nessuna transizione). Una notizia nuova non si perde.

**Codice** (M4): G5 accetta una `riapertura` datata al passato per un bando `sospeso`; G9 accetta
`annullamento_revoca` come uscita dal `revocato` e respinge gli eventi incompatibili con sospeso/revocato; G8
deduplica anche la forma `stato_proposto`; `applica_evento_esito` non rimette in coda un evento marcato (punto 4);
revocati fuori dal monitor (§5).

**Sito** (F2): nella scheda lo stato viene **solo** dalla colonna (`stato_effettivo`), non più da `statoDaEventi`; il
feed RSS/JSON riporta lo stato dei revocati; il testo della documentazione dell'API su `suspended` non consiglia più di
ricalcolare lo stato da `deadline_on`; la chip «Stato: Sospeso» non compare sopra una lista non filtrata.

## 15. Storico nella scheda (F1)
- Nella scheda `src/pages/bandi/[slug].astro`: **tutti** gli eventi pubblici del bando (quelli che la anon key legge,
  cioè con cursore), dal più recente, con data, frase per tipo (`src/lib/bandi/aggiornamenti.ts`) e link alla prova
  quando c'è. Le correzioni (`in_aggiornamenti=false` sui tipi che cambiano una data o uno stato: apertura,
  chiusura, proroga, riapertura, rettifica, sospensione, revoca, annullamento_revoca; e `correzione_redazionale`
  sempre) si mostrano con l'etichetta «Correzione»; gli eventi tecnici e automatici (pubblicazione,
  apertura/chiusura automatica, fonte_ufficiale_verificata, data_verificata, fusione, separazione, cambio_slug,
  ritiro) e quelli documentali (faq, nuovo_allegato, graduatoria, esito) compaiono senza etichetta. Il box
  «Aggiornamenti» in alto resta (solo `in_aggiornamenti=true`, senza il tetto di 20); lo storico è una sezione a
  parte in fondo alla scheda. Funziona senza
  JavaScript (per esempio i primi 10 visibili e il resto in un `<details>`). Nessuna pagina globale.
- Colonne lette: solo quelle concesse ad anon (§6.1 di `docs/contratto-db-bandi.md`), select esplicita.

## 16. Chi fornisce cosa a chi
| interfaccia | chi la scrive (task) | chi la usa |
|---|---|---|
| campi `Settings` di §3 | backend-b (B1) | tutti |
| `db.capacita_sospensioni()` | backend-b (B1) | backend (M2, M4) |
| `db.select_bandi_da_monitorare` senza troncamento | backend-b (B1) | backend (M2) |
| `date_validation.scadenza_provvisoria` | backend-b (B2) | backend-b |
| `dominio_ufficiale.scegli_fonte` | backend-b (B3) | backend (M3), backend-b |
| `fonte_ufficiale.righe_link_da_payload(bando, payload, html_riferimento, *, url_riferimento=None)`: HTML = `Risposta.html` della pagina letta dalla SEO (cache del giro), URL = `Risposta.url_finale` | backend-b (B5) | backend (M3) |
| `db.allinea_junction`, `db.azzera_rielaborazione` | backend-b (B4) | backend-b, backend (M3) |
| righe di spesa con `bilancio.Contatori` | ciascun passo | backend (M1: `consumo_oggi`, `salute`) |
| SQL migrazione 14 + `casi.json` | db (D2) | backend (M4), frontend (F2) |
| `db.consumo_oggi()` con `crediti_mese`/`usd_mese`; `db.CONTATORI_PIPELINE` con la copertura | backend-b (B1) | backend (M1) |
| `db.select_pubblicati_per_gemelli(limit=None)` | backend-b (B1) | backend (M5, M3) |
| `telemetria.copertura`, `telemetria.MOTIVI_RIMASTI` | backend (M1) | tutti i passi |

Una funzione che serve e non è in tabella: richiesta `CONTRATTO:` al lead.

## 17. Verifiche
- Suite: `test:py:bandi` ≥ 2540, `npm test` ≥ 473 con 0 skipped, `test:py` ≥ 77, `tsc` fermo a 51.
- Dal Mac, solo `--dry-run`: `domini`, `gemelli` (52 fusioni elencate), `rielabora-fonte` su 5 bandi scelti a mano
  per varietà, `verifica-stato --dry-run --senza-modello`, `report-verifica-stato --verita` (661135 non difforme).
- Test di orchestrazione aggiornati (`scraper_bandi/tests/test_orchestrazione_pipeline.py`): ordine di §2, tre
  chiamate al resolver (`precoce`, `nuovi`, `ricontrolli`), passi a ogni giro.

## 18. Correzioni dopo la revisione avversaria, ciclo 1 (01/10, decisioni del lead)
Report: `.cteam/review/20261001-173312/final.md` (BLOCCANTE, 4 P1 tutti in `rielabora_fonte.py`).
1. **Solo fonte ufficiale.** La rielaborazione lavora solo se `scegli_fonte(bando)` dice `ufficiale=True` (vale anche un
   `link_bando` che non è un aggregatore quando la fonte ufficiale è un PDF: stessa regola della SEO; 0 casi l'01/10).
   Altrimenti (aggregatore, URL vuoto) il bando si salta senza scritture e senza marcatore (contatore `senza_fonte_leggibile`):
   lo riprende il giro in cui la fonte diventa leggibile.
2. **Date che chiedono una transizione.**
   - Scadenza nuova **già passata** su un `aperto` o `in apertura prossimamente`: si applica la sola data (rettifica, nessuno
     stato); la vista mostra subito `chiuso` e il job orario allinea `stato_bando` entro 65 minuti (contratto DB §4).
   - Ogni altro caso (un `chiuso` con scadenza futura, un «in apertura» con apertura passata e non verificata, sospesi e
     revocati): si registra l'evento `rettifica` **non applicato e non leggibile** (`p_applica=false`, `p_leggibile=false`,
     `metodo='rielaborazione'`, citazione e pagina in `gate`), contatore `transizioni_da_decidere`, e `salute` lo mostra
     come informazione con il numero. Il bando si marca. Niente riaperture automatiche da una sola lettura.
3. **Marcatore solo a lavoro completo.** Non si scrive il marcatore (e il bando resta fra i `rimasti`, motivo `errore`)
   se: la RPC della rettifica è fallita; `allinea_junction` ha restituito un errore o un parziale; `aggiorna_fk_bando` non
   ha scritto; una dimensione è stata saltata perché una delle due chiamate è fallita; `aggiorna_link` del marcatore non
   ha scritto. `fk_cambiate` e `cambi` contano solo ciò che è stato scritto davvero. Se la data è applicata ma la prosa
   non si riallinea, la data passa come novità a `rigenera.riscrivi_scheda` (Opus), come fa il monitor (§6).
4. **Crediti della rielaborazione.** Per ogni bando si somma alla spesa del passo la differenza di
   `scarico.contatori().crediti_firecrawl` prima e dopo, prima del controllo dei tetti.
5. **`db.consumo_oggi()` restituisce `None` se la lettura fallisce** (come `consumo_passo_oggi`). La manutenzione
   tratta `None` come tetto raggiunto: niente modello né crediti, i controlli gratuiti continuano. L'ingresso lo ignora.
6. **Indirizzi interni.** Prima di ogni richiesta verso un URL che non sia di una fonte nota (verifica dei link e degli
   allegati, HEAD/GET del monitor sugli allegati) e su ogni redirect: si rifiutano gli host che risolvono a loopback, IP
   privati, link-local, multicast o non pubblici (`http.indirizzo_pubblico(url) -> bool`, backend-b). Le righe con URL
   così non si scrivono in `bando_link`.
7. **Cache delle schede OE.** In cache per la giornata solo le schede lette o un 404 vero; mai i `None` da 403/429,
   tetto, rete o 5xx.
8. **Rumore e falsi allarmi.** `elaborazione_bloccata` del monitor solo al passaggio da 4 a 5 fallimenti;
   `azzera_rielaborazione` vera solo se ha scritto; `passo_degradato:redazione` e l'esito dell'import IndicePA in
   `telemetria` leggono `gemelli_modalita` e `domini_modalita`.
9. **Revocati.** Restano fuori dal monitor: `annullamento_revoca` oggi non ha un produttore automatico; l'uscita da un
   revocato sbagliato è `bando_correggi_stato`. G9 e la lista bianca della 14 restano pronti per il futuro.
10. **Testi.** La documentazione dell'API non dice più «revoked … stato definitivo»; frasi neutre per la chiusura senza
    scadenza e per `correzione_redazionale` con lo stato nuovo.
I P2 non elencati qui restano aperti e vanno nel report finale.

## 19. Correzioni dopo la revisione avversaria, ciclo 2 (01/10 sera, decisioni del lead; Michele: «Correggi e 3° giro»)
Report: `.cteam/review/20261001-183800/final.md` (BLOCCANTE, 7 P1).
1. **Crediti contati una volta sola.** Ogni passata del resolver (precoce, nuovi, ricontrolli) assorbe solo il delta dei
   contatori dello scarico dal suo inizio (`assorbito` inizializzato con i contatori correnti). Preprocess, enrich e SEO
   scrivono nella loro riga il proprio delta di crediti, come la rielaborazione.
2. **Una proroga vera non è mai «superata» da una chiusura.** Nella regola del superato (§14), un evento `proroga` o
   `riapertura` (o una `rettifica` di `data_scadenza`) con scadenza nuova futura non è superato da un evento `chiusura`
   più recente. `salute` mostra come informazione quanti eventi sono marcati `superato` e `transizione_non_ammessa`.
3. **Un href malformato non ferma il monitor.** `urljoin` protetto; un'eccezione su un singolo bando diventa esito
   `errore` di quel bando e il giro continua (la riga `pipeline_run` con la spesa si scrive sempre).
4. **Catalogo illeggibile.** Un catalogo con tabelle fallite non si mette in cache; una dimensione con catalogo vuoto è
   una dimensione fallita (il bando resta incompleto, niente marcatore).
5. **Ogni tentativo conta.** Pagina illeggibile ed eccezione nella rielaborazione contano come tentativo
   (`incompleto:<n>`) con abbandono al terzo.
6. **Redirect del monitor.** Pagine collegate e pagine di notizie seguono i redirect solo con la guardia sugli indirizzi
   su ogni salto (o solo sullo stesso host); lo stesso per HEAD/GET del `link_candidatura` in `seo_skill`.
7. **API.** `GUIDA_SINCRONIZZAZIONE` non dice più di ricalcolare lo stato da `deadline_on` (stessa regola di
   `PARAGRAFO_STATUS`), con un test.
Inoltre, perché costano poco: nella 14 le query R1/R2 della verifica filtrano gli eventi senza stato, e l'indice di dedup
esclude `correzione_redazionale`.

## 20. Correzioni dopo la revisione avversaria, ciclo 3 (01/10 sera; Michele: «Correggi i 2 e committa»)
Report: `.cteam/review/20261001-193614/final.md` (BLOCCANTE, 2 P1). Dopo queste due correzioni, verificate dal revisore
interno, si committa senza un quarto ciclo; i P2 vanno nel report finale.
1. **Junction e `ultimo_cambiamento_at`.** Quando `allinea_junction` cambia davvero le righe di un pubblicato, il bando
   prende `ultimo_cambiamento_at = now()` (nuova `db.segna_cambiamento_pubblico(bando_id)`, che aggiorna solo quella
   colonna), così API (`updated_since`), sitemap e BandoFit vedono il cambio.
2. **G9 e gli eventi di solo stato.** Un evento di `chiusura`, `sospensione`, `revoca` o `annullamento_revoca` per cui
   `transizione_evento` non dà uno stato di arrivo si respinge, salvo che il bando sia già nello stato naturale di
   arrivo del tipo (chiuso, sospeso, revocato). Restano ammessi gli eventi che portano date (proroga su un sospeso come
   sola data, §14; apertura/riapertura con data), come oggi.

## 21. Correzioni dopo il primo giro in produzione (01/10 notte; Michele: ok alle due correzioni)
Trovate leggendo il giro di avvio e `salute` dopo il deploy delle 21:27. Nessuna migrazione.
1. **Il «chiuso» del modello con la scadenza futura non vale.** Tre bandi aperti (2773, 1262487, 1262812, pagine
   ufficiali lette l'01/10 sera: «Aperto», scadenze 26/07/2027, 01/11/2026, 06/10/2026) erano `processed` e `chiuso`:
   il preprocess aveva accettato lo stato proposto dal modello perché `reconcile_stato_bando` forza «chiuso» solo con la
   scadenza passata, non il contrario. Un `processed` chiuso non passa da enrich e SEO: resta nascosto per sempre.
   Regola nuova, **solo nel preprocess** (dove lo stato viene dal modello):
   - se il modello dice `chiuso` e la scadenza che la riga avrà (validata dal triplo controllo, oppure trovata dal
     lettore, dalla finestra di presentazione o dall'etichetta OE) è oggi o nel futuro (Roma), il «chiuso» del modello
     si scarta e vale come `aperto`; poi la riconciliazione di sempre (apertura futura → «in apertura
     prossimamente»);
   - un «chiuso» con prova resta: `chiuso_da_lettore` (lettura con `puo_chiudere`) vince come oggi, anche con la
     scadenza futura (la chiusura anticipata con citazione è la strada giusta per chiudere prima della scadenza);
   - con la scadenza assente o passata non cambia niente;
   - il prompt del preprocess lo dice al modello (una riga), senza altre modifiche.
   **Non si tocca** `reconcile_stato_bando`: la usano anche enrich (rete di sicurezza sullo stato salvato) e
   rielaborazione (`serve_transizione`) su stati che possono venire da una prova; riaprire lì un chiuso salvato sarebbe
   un errore. `tests/stato-bando/casi.json` e i gemelli TS e SQL non cambiano. Vale anche per il ripiego del
   preprocess se passa dalla stessa funzione; `bando_resolver.py` (il resolver vecchio) si allinea solo se il suo stato
   viene dal modello e la riga non è pubblicata. Il registro conta i casi (`chiuso_modello_scartato`).
   **Estensione (revisione interna, 01/10 notte):** la stessa regola vale nella **fase A di enrich**
   (`refine_stato_bando` sulle righe `processed` con stato NULL), che oggi scrive il «chiuso» del modello senza
   guardare la scadenza: dopo la risposta del modello, `preprocessor.scarta_chiuso_del_modello` sulla `data_scadenza`
   della riga e `oggi_roma()`, poi `reconcile_stato_bando` (apertura futura → «in apertura prossimamente»), poi la
   scrittura e la promozione alla fase B come per un «aperto». Il contatore `chiuso_modello_scartato` sta anche fra
   quelli di enrich. La rete di sicurezza della fase B (stato salvato) **non** cambia. Effetto voluto: un «aperto» o
   «in apertura» del modello con la scadenza della riga già passata si scrive «chiuso» in fase A e non va alla fase B,
   come nel preprocess (l'ingresso non pubblica i bandi già chiusi); prima arrivava alla SEO come chiuso.
   Il confronto è sulla sola data: il giorno della scadenza un «chiuso» del modello vale «aperto» anche dopo l'ora
   dichiarata. È voluto: la lettura (`stato_effettivo`) lo mostra comunque chiuso dopo l'ora, e il bando pubblicato con
   la scadenza passata è il caso normale di ogni bando scaduto.
   Le tre righe sono state corrette a mano (`docs/bandi-monitor/correzioni-giro-3-sera.sql`, eseguito da Michele
   l'01/10 alle 22 circa). Restano 300 `processed` chiusi **senza** scadenza (quasi tutti di giugno): fuori da questa
   correzione, annotati in RIPRESA.
2. **Doppioni in `bando_controllo`.** `bando_runner.aggiorna_controlli` mandava nello stesso UPSERT due righe con lo
   stesso `bando_id` quando una fonte produce lo stesso elemento due volte (fonte 276: 2 blocchi da 200 falliti con
   21000 «ON CONFLICT DO UPDATE command cannot affect row a second time»). Ora le righe si raccolgono per `bando_id`
   prima dell'UPSERT: una sola per bando; per `priorita_controllo` vale il massimo fra le chiavi dello stesso bando e
   quello già scritto. Fuori dal perimetro del giro 3: Michele ha dato l'ok l'01/10 notte (deroga in CLAUDE.md).
3. **Chiave IndexNow.** L'allarme `configurazione:indicizzazione` di `salute` è vecchio e vero: la chiave non esiste
   in nessun `.env` e IndexNow non è mai stato attivo sul sito (`/api/indexnow-key` risponde 404 «not configured»,
   controllato l'01/10 notte guardando solo lo stato HTTP). Michele ha scelto di attivarlo il 02/10: una chiave nuova
   di 32 caratteri esadecimali (`openssl rand -hex 16`), generata **una volta** in una variabile di shell e scritta con
   `>>` nel `.env` del sito e in `scraper_bandi/.env` senza mai stamparla (prima un `echo >>` per l'a capo finale), poi
   `unset`; subito dopo il confronto delle due righe senza stamparle (`cmp` fra i due `grep '^INDEXNOW_API_KEY='`, che
   dice solo «uguali» o «diverse»); poi `npm run build` (il sito
   la legge da `import.meta.env`, inlineata alla build) e il riavvio di sito e sender. Verifica: `/api/indexnow-key` e
   `/<chiave>.txt` rispondono 200 (la chiave è pubblica per protocollo, ma qui non si stampa lo stesso); nel journal
   del sender `[IndexNow] POST batch (… URL) → 200` o `202` dopo un giro con schede cambiate.
4. **Revisione avversaria, ciclo 1** (`.cteam/review/20261001-222723/final.md`, BLOCCANTE, 2 P1). Decisioni del lead:
   - **P1 «il chiuso del modello trasformato in aperto»: misurato, la regola resta.** Fra i non pubblicati «chiuso»
     con la scadenza futura **al momento dell'ingresso** ce ne sono 45 in tutta la storia: 42 all'ultimo giorno (la
     scadenza il giorno stesso o il dopo; con la regola nuova escono «aperti» per quell'ultimo giorno e poi
     `stato_effettivo` li mostra chiusi), 3 con la scadenza lontana, cioè i tre di §21.1, tutti aperti davvero. Nessuna
     chiusura anticipata vera sarebbe stata pubblicata come aperta. Nessuna euristica sulla motivazione del modello: non
     è una prova (non è verificata nel testo). **L'estensione alla fase A di enrich** non era fra le due correzioni
     approvate da Michele: sta in un **commit a parte** sul branch (solo `bando_enrich_runner.py` e
     `tests/test_chiuso_modello_enrich.py`) e si unisce a `main` solo con il suo ok. Se dice no: `git revert` di quel
     commit **e** riallineare i testi che la descrivono (qui §21.1 «Estensione» ed «Effetto voluto»; GUIDA §3.7 fase A e
     sue Fonti, M12, riga B13 del cap. 8), che stanno nel commit comune.
   - **P1 «correzione all'indietro su 3 id»: misurato, niente da fare.** I non pubblicati «chiuso» con la scadenza da
     oggi (Roma) in poi sono 0 dopo la correzione (misura delle 22:50 dell'01/10); i 42 storici dell'ultimo giorno hanno
     ormai la scadenza passata.
   - P2 sistemati: `bando_resolver.py` nella deroga di CLAUDE.md; la riga del prompt dice il vero («un 'chiuso' vale
     'aperto'»); RIPRESA con i numeri giusti e il controllo del giro finito prima del riavvio; la procedura IndexNow con
     il confronto delle due chiavi; GUIDA allineata.
   - **Aperti** (P2, non in questo intervento): (a) i 300 `processed` «chiuso» **senza** scadenza: nessun passo li
     rilegge; proposta per un giro successivo: un passo una tantum della verifica dello stato (dopo l'08/10) sui soli
     non pubblicati, con la stessa regola delle prove; responsabile il lead, decisione di Michele; (b)
     `segnali.confronta` non toglie i doppioni per `hash_bando`: con lo stesso elemento ripetuto nascono due eventi di
     servizio `segnale_fonte` e il contatore `identici` conta doppio (correzione: deduplica in `bando_runner.run`
     prima di `confronta`); (c) `src/pages/api/indexnow-key.ts` restituisce la chiave a chiunque: con IndexNow attivo
     chiunque può segnalare URL del sito a nome della chiave (rischio basso: la chiave è pubblica per protocollo nel
     file `/<chiave>.txt`, ma lì bisogna già conoscerla); correzione proposta, fuori deroga: risposta 200/404 senza
     corpo. **Chiuso il 02/10** (Michele: «sì, sistemala e poi attiva»): `/api/indexnow-key` risponde 200 con corpo
     fisso `ok` se la chiave c'è e 404 «IndexNow key not configured» se no, sempre con `Cache-Control: no-store`; la
     logica sta nella funzione pura `src/lib/indexnow-chiave.ts` con i suoi test. `/<chiave>.txt` non cambia.
   - P2 rimasti dopo il ciclo 2 (`.cteam/review/20261001-225006/final.md`, ESITO OK), per un giro successivo:
     `fermi_in_lavorazione` conta anche i `processed` chiusi (avviso rumoroso: escluderli o contarli a parte); nel
     ripiego (`bando_resolver`) la scadenza che scarta il «chiuso» è validata solo sulla pagina elenco (0 casi falsi su
     45 storici; stessa debolezza che aveva già un «aperto» con data sbagliata); la docstring della regola dice «righe
     mai pubblicate» ma `analyze_bando` gira anche nella rielaborazione dei pubblicati (effetto nullo: lì lo stato
     dell'analisi non si legge); chiavi a 0 nel ritorno anticipato del preprocess; numeri di riga nelle Fonti della
     GUIDA; `AGENTS.md` e `Claude outputs/` non tracciati e non ignorati (decide Michele).
5. **Chiarimento a BandoFit (01/10 notte, §10.1 del contratto DB).** Il «degrado su 42703/PGRST senza 5xx» della
   conferma scritta del c2 riguarda solo gli errori dovuti a un cambio di schema (colonna o funzione tolta: 42703,
   PGRST103/200/201/204/205). I guasti veri (PGRST000-002, rete, 57014) restano 502/504. Le richieste R1-R8: la stampa
   del codice reale (`--come-inviata`, con commit e data) più, quando Michele lo apre, un estratto dei log del gateway
   del DB bandi con una richiesta per ciascuna.

## 22. Precedenza del monitor sulla spesa giornaliera (02/10; Michele: «Monitor prima, poi indagine», piano T1+T2 approvato)
Misura del 02/10 (giro delle 00:00): le riscritture delle schede hanno preso 4,46 $ dei 5 $ (89%), il monitor ha fatto
10 classificazioni e ne ha rinviate 14; alle 06 zero classificazioni. Indagine (workflow
`indagine-spesa-riscritture` del 02/10). Cause: le riscritture girano dentro il ciclo del monitor bando per bando, con lo
stesso tetto e nessuna precedenza; la coda (`bando_controllo.impronte_sezioni.__riscrittura__`) l'ha riempita la
rielaborazione, che manda a Opus anche le date messe per la prima volta (da NULL) e il «contenuto già in linea», contro
§18.3 («come fa il monitor»).
1. **Due fasi nel giro del monitor** (`monitoraggio.run`). Fase 1: controllo e classificazione di tutti i bandi
   selezionati, come oggi, con il tetto intero. Fase 2, solo dopo e nel tempo che resta di `TEMPO_MONITOR_S`: le
   riscritture dei bandi controllati in fase 1 che hanno una coda o novità nuove, in ordine di `dal` crescente e poi
   `id` (chi è rinviato conserva `dal` e passa per primo al giro dopo: rotazione di §1). Nessun tetto sul numero.
2. **Riserva per i giri che restano.** Una riscrittura parte solo se
   `spesa di regime di oggi (già scritta + monitor di questo giro + riscritture di questo giro) + costo massimo di una
   riscrittura ≤ TETTO_USD_GIORNO − riserva`, con `riserva = 0,20 × TETTO_USD_GIORNO` per ogni giro di `MONITOR_GIRI`
   che resta oggi dopo l'ora attuale (Roma) più 0,25 $ per il resto del giro corrente; `costo massimo` = 12 000 token
   d'ingresso più `SEO_MAX_TOKENS` d'uscita al listino del modello SEO. Stessa regola sul mese con
   `TETTO_USD_MESE − (1 $ × giri che restano nel mese + 0,25 $)`. Se non vale: riscrittura **rinviata** (resta in coda,
   tentativi invariati, motivo `spesa`). Tetto a 0 = nessun tetto e nessuna riserva (come `bilancio._supera`); consumo
   non leggibile = nessuna riscrittura (§18.5). La riserva non si passa come `Tetti` ridotti (un tetto che scende a 0
   diventerebbe «nessun tetto»): è un controllo prima della chiamata. Tempo finito: chi resta fuori rimane in coda, le
   novità del giro si salvano comunque, motivo `tempo`. Telemetria nella riga `rigenerazione_scheda`: `riserva_usd`,
   `rinviate_per_riserva`, motivo `tempo` accanto a `spesa`.
3. **Rielaborazione come §18.3.** Le date messe per la prima volta (valore prima NULL) e il caso «contenuto già in linea»
   (`rigenera` che risponde «nessuna data da sostituire: solo box») non vanno a Opus e non finiscono in coda: valgono
   come riallineamento riuscito, come nel monitor (`date_da_riscrivere`, `_rigenerazione_riuscita`). Il monitor, in fase
   2, chiude **senza modello** le voci della coda esistente che contengono solo novità di questo tipo, contandole
   (`chiuse_senza_modello`).
4. **Risposte tagliate.** Una riscrittura fallita con «risposta troncata: max_tokens» si conta (`riscritture_troncate`)
   e si scrive nel log con il motivo, nel monitor e nella rielaborazione. Serve a decidere se alzare `SEO_MAX_TOKENS`
   (decisione di Michele, dopo la misura; nessun cambio oggi).
5. **Non si toccano**: `rigenera.py` (riscrittura e controlli), `seo_skill.py`, `bando_seo_runner.py`, `bilancio.py`,
   `settings.py`, `.env`, l'ordine dei passi in `bandi_pipeline.py`, i tetti di 5 $ e 150 $, `seleziona`, il rinvio delle
   classificazioni, `TENTATIVI_RISCRITTURA`, schema e migrazioni, `src/`. `monitoraggio.controlla()` resta (la usano i
   test). Fuori perimetro e annotato: nel monitor `interrotto` non diventa mai vero, quindi `interrotto_per_tetto`
   resta falso anche quando il tetto scatta.
6. **Verifica dopo il rilascio** (solo GET su `pipeline_run`): al giro delle 00 la riga del monitor ha
   `classificazioni_rinviate` = 0 (salvo un monitor che da solo superi il tetto) e `rigenerazione_scheda` ha `usd` entro
   il limite e `riserva_usd` ≈ 3,25; alle 06, 12 e 18 il monitor ha classificazioni > 0. La quota di 1 $ per giro si
   rilegge dopo 2-3 giorni.
7. **Come è stato realizzato (02/10, workflow `spesa-precedenza-monitor`, verifica avversaria a tre lenti).**
   `monitoraggio.run`: fase 1 con `_controlla_pagina`, fase 2 `_fase_riscritture` (in dry-run non gira); funzioni pure
   `giri_rimasti`, `costo_massimo_riscrittura` (oggi 0,16 $), `riscrittura_consentita`, `riserva_usd`; la coda si chiude
   senza modello solo se **ogni** voce è una data messa da NULL o, con la data vecchia nota, la rigenerazione senza
   modello risponde «già in linea» o scrive (la stessa scrittura senza modello che il monitor fa già in fase 1); code
   miste vanno intere a Opus. Due difetti trovati dalla verifica e corretti: i crediti Firecrawl delle riscritture in
   fase 2 si uniscono di nuovo ai contatori del monitor dopo ogni bando; un chiuso con coda rinviato in fase 2 torna
   al giro dopo (`_salva_coda` anche a coda invariata). `rielabora_fonte`: le date da NULL e il «già in linea» valgono
   come riallineamento riuscito (`date_senza_riscrittura`), lo slug va in `slug_modificati`; log del motivo di ogni
   riscrittura non riuscita e `riscritture_troncate`. P2 aperti: il «costo massimo» non è un massimo stretto (il
   prompt può superare 12 000 token: la riserva può essere sforata di poco); la riserva mensile usa
   `0,20 × TETTO_USD_GIORNO` per giro, uguale a «1 $» con i 5 $ di oggi; il ritorno al giro dopo di un chiuso rinviato
   annulla il backoff degli errori di rete di quel bando; con più date incatenate una scrittura intermedia senza modello
   può restare fuori da `slug_modificati` (`ultimo_cambiamento_at` avanza comunque dal trigger); un caso «già in linea»
   con la data vecchia ancora nella `descrizione_breve`; buchi di test segnalati dai mutanti.
8. **Revisione avversaria finale (02/10 11:27, `.cteam/review/20261002-112743/final.md`): ESITO OK.** P2 per un giro
   successivo: (a) `_chiudi_senza_modello` non ricontrolla che la data nuova sia ancora quella della colonna (serve un
   ritorno della stessa colonna alla data di prima); (b) `date_della_novita` non legge il `valore_prima` scalare
   scritto dalla RPC, quindi le voci del monitor non si chiudono mai senza modello (effetto prudente; stesso limite in
   `rigenera.date_da_evento`); (c) un chiuso con riscrittura rinviata per riserva viene riscaricato a ogni giro (GET e
   a volte un credito Firecrawl) finché la riserva non si libera: proposta, tornare al giro dopo solo per il rinvio
   per tempo; (d) `PROSA_GIA_IN_LINEA` accetta anche «nessuna data da sostituire», che il monitor non accetta (ramo oggi
   irraggiungibile) e §22.3 cita il messaggio sbagliato; (e) `riscritture_troncate` non conta «stop_reason=max_tokens»;
   (f) §23: il confronto c1/c2 usa la anon key, ma gli id delle righe che non passano la prova e la riga di
   `pipeline_run` richiedono la service-role, da dire nel piano; (g) `AGENTS.md` non tracciato e vecchio.

## 23. Misura automatica del c2 (02/10; da realizzare)
Decisione di Michele del 02/10: c2 in parallelo, interruttore «zero perdite su tutti i pubblicati», misura ogni sera
(contratto DB §5.1 punto 1). Regola permanente «tutto automatico»: la misura non può essere un passo a mano. Si
realizza un comando di `scraper_bandi` in **sola lettura con la anon key** (nessuna scrittura sul DB tranne la propria
riga in `pipeline_run`), lanciato dal giro delle 18, che fa il confronto c1/c2 di §5.1 punto 1 («Come si misura») e
scrive nella riga del giro i conteggi per stato e gli id. Modulo nuovo, passo nuovo in `bandi_pipeline.py`, comando in
`__main__.py`, test con dati finti. Piano e perimetri da approvare con Michele prima del codice. Fino ad allora la misura
la fa il lead in sola lettura (la prima la sera del 02/10).
