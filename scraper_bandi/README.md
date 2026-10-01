# scraper_bandi

Nuovo scraper bandi per il progetto news1. Sostituisce il precedente subproject `Scraper-gerarchico-bandi-OpenCoesione-Backend-Python/` (rimosso in v5).

Costruito in **step incrementali**:

- **Step 1 (completato)**: discovery delle **fonti** dalla pagina indice di OpenCoesione → popola la tabella `fonte`.
- **Step 2 (completato)**: scraping di ogni fonte → popola la tabella `bando`. Strategia per fonte in `app/scraper_config.py`.
- **Step intermedio (questo)**: pre-processing via Claude Haiku 4.5 — valida ogni bando, calcola confidence + stato_bando.
- **Step 3+**: enrichment skill SEO (`bandi-seo-enricher/`).

## Stack

- Python 3.10+ con venv dedicato (no condivisione con `backend/venv`).
- `httpx[http2]` per le HTTP request (async + redirect follow + HTTP/2).
- `beautifulsoup4` + `lxml` per parsing HTML.
- `supabase-py` per scrittura DB.
- `loguru` per logging (DEBUG ovunque, console + file daily-rotated).

Niente Firecrawl: la pagina sorgente di OpenCoesione e' HTML statico, lo scraping classico basta e avanza.

## Setup

```bash
cd scraper_bandi
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# editare .env: SUPABASE_URL_BANDI + SUPABASE_SERVICE_KEY_BANDI (service key del DB bandi)
```

## Variabili d'ambiente

| Var | Default | Descrizione |
|---|---|---|
| `SUPABASE_URL_BANDI` | (obbl.) | URL del progetto Supabase DB B (bandi) |
| `SUPABASE_SERVICE_KEY_BANDI` | (obbl.) | Service-role key (write) del DB B |
| `OPENCOESIONE_URL` | `https://opencoesione.gov.it/it/opportunita_2021_2027/` | Override pagina sorgente |
| `REACHABILITY_TIMEOUT_S` | `15` | Timeout HEAD/GET per testare `attivo` |
| `REACHABILITY_CONCURRENCY` | `10` | Numero di test reachability paralleli |
| `HTTP_USER_AGENT` | browser realistico | UA inviato dalle request |
| `SORVEGLIA_SERVIZIO_SENDER` | `edunews-bandi-sender` | Servizio systemd del sender che `sorveglia` interroga; resta sul server, mai nel riepilogo |
| `PUBLIC_SUPABASE_BANDI_ANON_KEY` | assente | Facoltativa: con lei la lettura di prova di `bando_pubblico` (misura `vista_ms` di `salute`) si fa come anon, con la RLS del sito; senza, con la service key |
| `VERIFICA_STATO_MODALITA` | `ombra` | `ombra` \| `attivo` (giro 2, percorso A). Governa verifica dello stato, import di IndicePA e fusioni automatiche; un valore sconosciuto vale `ombra` e accende `configurazione:verifica_stato` |
| `VERIFICA_STATO_TETTO_LETTURE` | `40` | Letture per giro della fase controlli (1-200) |
| `VERIFICA_STATO_TETTO_S` | `900` | Secondi per giro della fase controlli (60-1800) |
| `VERIFICA_STATO_MAX_CHIUSURE` | `20` | Eventi `chiusura` per giro (0-50) |
| `VERIFICA_STATO_USA_MODELLO` | `true` | Il modello legge le pagine (i)-(iii) senza lettore per ente |
| `VERIFICA_STATO_TETTO_INGRESSO` | `30` | Letture per giro della fase ingresso (senza modello) |
| `INGRESSO_SOSTA_GIRI` | `4` | Giri di sosta di un «aperto» senza scadenza né prova prima della pubblicazione (0-12; 0 = niente sosta) |
| `GEMELLI_FUSIONI_PER_GIRO` | `10` | Fusioni automatiche dei doppioni certi nel giro delle 06 (0 = spento) |
| `INDICEPA_URL` | risorsa CKAN pubblica di `enti.xlsx` | Da cambiare solo se IndicePA sposta la risorsa |

## Comandi

### Step 1 — discovery fonti

```bash
cd scraper_bandi
.venv/bin/python -m app discover
```

Esegue:
1. GET pagina indice OpenCoesione, parsing BS4.
2. Estrazione di ~200 link organizzati per `categoria_programma` + `tipologia_programma` + `tipo_link`.
3. Test di reachability su ogni link (HEAD → fallback GET, follow_redirects=True).
4. Detect del `formato_link` (HTML / PDF / CSV) via estensione URL o Content-Type.
5. **UPSERT** in tabella `fonte` (on_conflict=`link`):
   - `attivo = TRUE` → `stato_processing = 'ready'`
   - `attivo = FALSE` (timeout/DNS/4xx/5xx) → `stato_processing = 'connection error'`
6. **Mark deprecato**: per ogni record gia' in DB ma non piu' presente nella pagina sorgente → `stato_processing = 'deprecated'`.

Log finale: `{discovered, inserted, updated, deprecated, connection error}`.

## Tabella `fonte` (schema post-v5)

| Colonna | Tipo | Origine |
|---|---|---|
| `id` | bigserial PK | DB |
| `categoria_programma_id` | int FK → `categoria_programma` | Scraper |
| `tipologia_programma_id` | int FK → `tipologia_programma` | Scraper |
| `tipo_link` | text (`Opportunità` \| `Preavviso`) | Scraper (testo del link `<a>`) |
| `link` | text UNIQUE | Scraper (URL originale, no redirect) |
| `formato_link` | text (`HTML` \| `PDF` \| `CSV`) | Scraper (estensione + Content-Type) |
| `attivo` | bool | Scraper (HEAD/GET 2xx) |
| `stato_processing` | text (`ready` \| `connection error` \| `deprecated`) | Scraper |
| `created_at`, `updated_at` | timestamptz | DB triggers |

## Mapping classificazioni

Hardcoded nel codice (`app/classifier.py`), basato sull'organizzazione della pagina OpenCoesione:

**`categoria_programma`** (4 valori):
- id=1 → "Programma Regionale" (sezioni `<h3>` con nome di regione)
- id=2 → "Programma Nazionale" (PN Cultura, PN Equita', ...)
- id=3 → "Programma CTE a Titolarita' Italiana"
- id=4 → "Programma CTE a Partecipazione Italiana"

**`tipologia_programma`** (10 valori, match per nome programma):
- PR FESR, PR FSE+ (typo DB: "PR FRE+"), PR FESR e FSE+
- PN FESR, PN FSE+, PN FESR e FSE+, PN Just Transition Fund
- INTERREG FESR, INTERREG IPA, INTERREG NEXT

### Step 2 — scraping bandi

```bash
cd scraper_bandi
.venv/bin/python -m app scrape-bandi
```

### Step v7 — enrichment FK + junction

```bash
cd scraper_bandi
.venv/bin/python -m app enrich

# Smoke su 5 bandi senza scrivere DB:
.venv/bin/python -m app enrich --dry-run --limit 5
```

Due fasi interne:

**PHASE A** — Refinement (per bandi con `stato_bando=NULL`):
- Firecrawl scrape della pagina del bando.
- Claude Haiku 4.5 determina lo stato: `aperto` / `chiuso` / `in apertura prossimamente`.
- I bandi che risultano `chiuso` restano in `stato_processing='processed'` (saltati).

**PHASE B** — Classificazione FK + junction + date (per `aperto` o `in apertura prossimamente`):
- 8 LLM call **PARALLELE** per bando (asyncio.gather):
  - `tipologia_bando_id` (single)
  - `modalita_erogazione_id` (single)
  - `programma_id` (single)
  - `bando_beneficiari` (multi)
  - `bando_codici_ateco` (multi)
  - `bando_regioni` (multi)
  - `bando_settori` (multi)
  - `data_pubblicazione`, `data_apertura`, `data_scadenza` (1 sola call, 3 date)
- Tool use API forza `enum` sui valori catalogo (no nuovi valori).
- Date con citation: la LLM emette `{date, source, quote}` per ognuna; gate Python verifica che `quote` sia substring letterale del markdown, che `source ∈ {official_pdf, official_page}` e che il valore `date` corrisponda al frammento. Se anche solo una condizione fallisce → la data resta `None` (scraper vince, niente UPDATE). Coerenza `pubblicazione ≤ apertura ≤ scadenza`: se violata, tutte e tre vengono coercite a `None`.
- UPDATE bando + DELETE/INSERT junction tables. Le 3 date sono incluse nel payload UPDATE **solo se non-None**.
- Stato finale: `stato_processing='enriched'`.

**Concorrenza**: `ENRICH_CONCURRENCY_REFINE=3` (Firecrawl rate-limit), `ENRICH_CONCURRENCY=5` (5 bandi × 8 call = 40 in-flight Anthropic).
**Costo**: ~$3.5-4 totali su ~450 bandi.
**Durata**: ~10-15 min.
**Idempotente**: re-run salta i già `enriched`.

### Step v10 — fonti esterne + dedup cross-source

Tre nuove strategie scraper generiche per portali con API REST/Solr e HTML offset-based:

- **`json_api_paginated`** — REST/Algolia/Solr con paginazione configurabile (`page`/`solr_start`/`offset`/`cursor`). Usata per Incentivi Gov IT.
- **`json_api_paginated_login`** — Variante con `auth_provider` registry-based (`scrapers/auth/`). Usata per Obiettivo Europa con login Django CSRF.
- **`html_paginated_offset`** — HTML server-side con offset-based pagination + BS4 parsing. Usata per Italia Domani PNRR.

Mapping JSON/HTML → `BandoItem` via adapter dedicato per fonte (`scrapers/adapters/{obiettivo_europa,incentivi_gov_it,italia_domani}.py`). I 20+ campi ricchi (sectors, beneficiaries, programs, regions, ateco, budget, dimensioni_impresa, focus_pnrr, ecc.) finiscono in `raw_data` JSONB e vengono mappati al catalogo via enricher LLM esistente.

**Credenziali Obiettivo Europa** (richieste in `.env`):
```
OBIETTIVO_EUROPA_USERNAME="<email dell'account>"
OBIETTIVO_EUROPA_PASSWORD="<password dell'account>"
```
Senza login l'API ritorna max 5 bandi/pagina; con login si accede a ~1133 bandi totali.
> **Le credenziali non si scrivono mai in questo file né in altri file tracciati**: vivono solo in `scraper_bandi/.env` (ignorato da git). Quelle che comparivano qui fino al 23/09/2026 sono nella history di `origin/main` e vanno considerate compromesse: vanno ruotate sul portale, aggiornate in `.env` e verificate con `python -m app salute` (login OK e 50 record per pagina).

**Dedup cross-source via `canonical_key`**: lo stesso bando pubblicato su 2 portali diversi (es. Obiettivo Europa + Incentivi Gov IT) genera 2 record nel DB con hash diversi (perché il hash_bando attuale include `fonte_id`). La skill SEO al termine calcola `canonical_key = SHA256(norm_titolo|norm_ente|data_scadenza|importo)`. Se collide con un master esistente: il master raccoglie la fonte aggiuntiva in `fonti_aggiuntive INT[]`, il nuovo record passa a `stato_processing='completed_duplicate'` (nascosto dal frontend tramite RLS). Coverage attesa: ~70% (titolo+ente+data sono molto specifici).

**Smoke test rapido**:
```bash
# 1. Login + 1 pagina API Obiettivo Europa (50 bandi/pagina con login)
.venv/bin/python -c "
import os, asyncio
from app.settings import get_settings
from app.scrapers.auth.obiettivo_europa import obtain_session
cfg = get_settings()  # le credenziali arrivano da scraper_bandi/.env
s = obtain_session(cfg.obiettivo_europa_username, cfg.obiettivo_europa_password)
r = s.get('https://www.obiettivoeuropa.com/api/call/?page=1&ordering=-published', timeout=20)
print(r.json().get('count'))
"
```

### Step v8 — skill SEO `enriched → completed`

```bash
cd scraper_bandi
.venv/bin/python -m app seo

# Smoke su 3 bandi senza scrivere DB:
.venv/bin/python -m app seo --dry-run --limit 3

# Re-run su bandi già completed (utile per riapplicare prompt aggiornati):
.venv/bin/python -m app seo --rerun-completed --limit 10
```

Per ogni bando in `stato_processing='enriched'`:

1. **Load context**: SELECT bando + lookup catalogo (FK risolte a nomi, junction risolte a nomi via `bando_beneficiari`/`bando_regioni`/`bando_settori`/`bando_codici_ateco`).
2. **Markdown Firecrawl** (cache LRU condivisa con enricher).
3. **Single LLM call** Claude Opus 4.7 con tool use `save_seo_bando` (schema strict + enum forced).
4. **Validation Python**: slug kebab-case fallback + collision resolver, lunghezze hard (titolo ≤80, descrizione_breve 180-320, titolo_breve ≤100), enum re-check, link_candidatura HEAD reachability (graceful demote a `missing` se broken), ente_erogatore substring check (warning, no block), allegati filter URL + dedup, importi normalize.
5. **UPDATE bando** con 14 campi + `stato_processing='completed'`.

**14 campi scritti dalla skill** (e SOLO questi): `slug`, `titolo`, `titolo_breve`, `descrizione_breve`, `contenuto` (JSONB sections), `livello` (flash_bando|guida_bando), `allegati` (JSONB array), `ente_erogatore`, `area_geografica`, `tematica` (text[]), `importo_totale_eur`, `importo_max_per_progetto_eur`, `link_candidatura`, `link_candidatura_source` (extracted|fallback_source|missing).

**Cosa NON fa**:
- Non estrae date (già fatto dall'enricher v7).
- Non popola FK / junction (già fatti dall'enricher v7).
- Non decide validità del bando (già fatto dal preprocess).
- Non fa discovery sub-link.
- Niente verifier post-skill.

**Concorrenza**: `SEO_CONCURRENCY=3` (Opus rate limit più stretto di Haiku). Retry exponential su 429/5xx.
**Costo**: ~$0.15/bando media → ~$60-80 su ~450 bandi.
**Durata**: ~30 min.
**Idempotente**: default opera solo su `enriched`. `--rerun-completed` opt-in include i già completed.

### Step intermedio — pre-processing v2 (Firecrawl + Haiku + Sonnet fallback)

```bash
cd scraper_bandi
.venv/bin/python -m app preprocess

# Smoke test su 10 record senza scrivere DB:
.venv/bin/python -m app preprocess --dry-run --limit 10
```

Per ogni bando in `stato_processing='scraped'`, due path:

**Primary path** (link_bando disponibile + Firecrawl OK):
1. Firecrawl markdown del link_bando (cache LRU condivisa con enricher).
2. Single LLM call **Claude Haiku 4.5** via Anthropic SDK + tool use esteso.
3. Output: `{is_valid_bando, confidence_score, rejection_reason, stato_bando, data_pubblicazione, data_apertura, data_scadenza}` con citation obbligatoria (`source` + `quote`).
4. **Triple-gate validation** sulle date (substring + source autoritativo + regex date in quote = data dichiarata). Date che falliscono il gate → None.
5. **Reconciliation guard data-driven**: se `data_scadenza < today` → forza `stato_bando='chiuso'`; se `data_apertura > today` → `'in apertura prossimamente'`. Questo elimina i falsi positivi 'aperto' su bandi scaduti.

**Fallback path** (`bando_resolver.py`, trigger: link_bando=NULL, Firecrawl fail, o markdown < 200 char):
1. Firecrawl markdown della **FONTE** (pagina indice del programma/regione).
2. LLM **Claude Sonnet 4.6** con extended reasoning sul contesto fonte.
3. Stesso schema output, stesso triple-gate + reconciliation.

**UPDATE DB**:
- `is_valid_bando=true` → `stato_processing='processed'` + `stato_bando` + 3 date (se passate il gate) + `confidence_score`.
- `is_valid_bando=false` → `stato_processing='rejected'` + `rejection_reason` + `confidence_score`.

**Concorrenza**: `PREPROCESS_CONCURRENCY=20` LLM, `PREPROCESS_FIRECRAWL_CONCURRENCY=5` (bottleneck). Effective = min(20, 5) = 5.
**Costo**: ~$4 Primary (Haiku + Firecrawl) + ~$22 Fallback (Sonnet su ~33% bandi) = **~$26 totali** su ~3000 bandi.
**Durata**: ~10 min (Firecrawl bottleneck).
**Idempotente**: re-eseguendo, solo i record ancora 'scraped' vengono presi.

Esegue:
1. SELECT `fonte` WHERE `stato_processing='ready' AND attivo=TRUE` (~108).
2. Per ogni fonte: lookup in `app/scraper_config.py` -> strategia + parametri.
3. Istanzia uno scraper (8 strategie disponibili):
   - `httpx_bs4` (~38) — indici SSR semplici (httpx + BeautifulSoup)
   - `firecrawl_scrape` (~18) — JS dinamico / anti-bot (Cloudflare, Radware)
   - `firecrawl_extract` (1) — estrazione AI strutturata
   - `hybrid_httpx_firecrawl` (~16) — discovery HTML + parse PDF/CSV allegati
   - `csv_parser` (~8) — CSV/XLSX direct download
   - `pdf_extract_tables_pdfplumber` (~5) — tabelle PDF
   - `pdf_extract_text` (1) — testo PDF
   - `skip_no_bandi` (~19) — pagine hub/404, no-op
4. Per ogni bando trovato: compone record con `hash_bando = SHA256(fonte_id|link_bando)` (o `SHA256(fonte_id|titolo_normalizzato)` per bandi senza link).
5. UPSERT in `bando` (on_conflict='hash_bando'), chunk da 500.

Counters finali: `{fonti_totali, fonti_processate, fonti_skipped_*, fonti_errors, bandi_estratti, bandi_con_link, bandi_senza_link, bandi_upsert_processed}`.

Stima durata: ~18-30 min totali (sequenziale + throttle 1s/host).

## Sender automatico 4x/day

Per eseguire l'intero pipeline (5 step) **4 volte al giorno** (00:00, 06:00, 12:00, 18:00):

```bash
# Foreground (con visualizzazione log live)
cd /Users/micheledibisceglia/Developer/news1
scraper_bandi/.venv/bin/python -m backend.app.bandi_sender

# Background con log persistito (consigliato per produzione)
nohup scraper_bandi/.venv/bin/python -m backend.app.bandi_sender > /dev/null 2>&1 &
echo $! > /tmp/bandi_sender.pid
# I log finiscono in logs/backend-YYYY-MM-DD.log (loguru daily-rotated)
```

> **Nota venv**: il sender importa moduli da `scraper_bandi/app/` + `schedule` library. Usa il venv di scraper_bandi (`scraper_bandi/.venv/`) che ha già supabase/anthropic/firecrawl/loguru. È stato installato anche `schedule` (`pip install schedule`).

**Flusso**:
1. `backend/app/bandi_sender.py` parte → run immediato della pipeline.
2. `backend/app/bandi_pipeline.py` esegue in sequenza: `discover` → `scrape-bandi` → `preprocess` → `enrich` → `seo`.
3. Ogni step in try/except: se uno fallisce, gli altri continuano (sono tutti idempotenti).
4. Al termine: log esauriente con stato per step + counter.
5. `schedule` library: re-esegue automaticamente alle 4 ore prefissate.

**Timing atteso per ciclo**: ~70-80 min totali.
Tra cicli (6h interval): ~4h libere = margine 5× sul tempo richiesto.

**Esempio systemd unit file** (produzione, da adattare). In produzione il servizio si chiama
`edunews-bandi-sender` e il repo sta in `~/projects/news1`:

```ini
# /etc/systemd/system/edunews-bandi-sender.service
[Unit]
Description=EduNews24 Bandi Pipeline Sender (4x/day)
After=network.target

[Service]
Type=simple
User=<UTENTE>
WorkingDirectory=/home/<UTENTE>/projects/news1
ExecStart=/home/<UTENTE>/projects/news1/scraper_bandi/.venv/bin/python -m backend.app.bandi_sender
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

La politica di riavvio sta nel drop-in `deploy/edunews-bandi-sender-riavvio.conf` (giro 2):
`Restart=on-failure`, `RestartSec=20min`, `StartLimitIntervalSec=0`. Un errore fatale dello
scheduler fa uscire il sender con 1, e systemd lo riavvia dopo 20 minuti. Se il processo precedente è
morto a metà giro (all'avvio viene rilasciato il suo lock del giro), il sender non rifà il giro di
boot: scrive una riga `riavvio_dopo_crash` in `pipeline_run` e aspetta lo scheduler.

```bash
sudo mkdir -p /etc/systemd/system/edunews-bandi-sender.service.d
sudo cp scraper_bandi/deploy/edunews-bandi-sender-riavvio.conf \
  /etc/systemd/system/edunews-bandi-sender.service.d/riavvio.conf
sudo systemctl daemon-reload
sudo systemctl enable --now edunews-bandi-sender.service   # solo la prima volta
sudo journalctl -u edunews-bandi-sender -f
```

Dopo un cambio del drop-in basta **un solo** `systemctl restart edunews-bandi-sender`, nella
finestra sicura (12:30-16:30 o 19:00-22:30).

**Test smoke (un giro singolo, senza schedule)**:
```bash
scraper_bandi/.venv/bin/python -m backend.app.bandi_pipeline
```

## Sorveglianza (`sorveglia`, giro 2)

Niente notifiche (scelta del committente, confermata il 30/09): chi vuole sapere se il produttore dei
bandi è vivo guarda il pannello di BandoFit. Il pannello legge un **riepilogo neutro** con la chiave
di `monitoraggio_catalogo` (migrazione 12, contratto DB §14); `sorveglia` è il comando che lo scrive.

```bash
cd scraper_bandi
# dal Mac o sul server: legge (anche la memoria), stampa il JSON e i codici, NON scrive
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app sorveglia --dry-run
# sul server lo lancia il timer, ogni 15 minuti
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app sorveglia
```

Un giro di `sorveglia`:
1. legge la memoria della volta prima dalla riga del riepilogo;
2. fa la fotografia di `salute` (misure del DB, `systemctl show` del sender, job orario della 12);
3. costruisce il riepilogo v1 (`app/riepilogo_salute.py`): codici stabili, testi senza nomi di
   fornitori, host, URL né dollari;
4. lo valida; se non passa scrive il riepilogo minimo con il codice `riepilogo_non_valido`, e il
   dettaglio va solo nel journal;
5. fa l'upsert della riga unica (`id = 1`).

Exit code: **0 anche con allarmi** (li mostra il pannello); **1** su un errore interno o un upsert
fallito. Senza la migrazione 12 scrive un warning ed esce con 0. Nessun file di stato (niente
`StateDirectory`, niente flock): la memoria (`nrestarts` delle ultime 6 ore e il `dal` di ogni codice)
sta nella riga. Nessuna chiamata di rete oltre a PostgREST del DB bandi. Il servizio sorvegliato si
cambia con `SORVEGLIA_SERVIZIO_SENDER` (default `edunews-bandi-sender`), che non esce mai nel
riepilogo.

**Installazione** (una volta sola, sul server; le unit di esempio sono in `deploy/`, con percorsi
assoluti e `<UTENTE>` da sostituire):

```bash
sudo cp scraper_bandi/deploy/edunews-bandi-sorveglianza.service \
  scraper_bandi/deploy/edunews-bandi-sorveglianza.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now edunews-bandi-sorveglianza.timer
systemctl list-timers edunews-bandi-sorveglianza.timer
journalctl -u edunews-bandi-sorveglianza --since -1h
```

Il timer gira ai minuti 05, 20, 35 e 50 (`Persistent=true`). Se il pannello non vede una riga nuova
da 45 minuti mostra «in ritardo» da solo. I codici, cosa significano e cosa fare sono in
`docs/bandi-monitor/RIPRESA.md` §3.1.

## Stato da verificare (`verifica-stato`, giro 2 percorso A)

Un bando «in apertura» o «aperto» senza scadenza non resta per sempre in quello stato senza che
nessuno lo controlli: il passo `verifica_stato` rilegge la pagina ufficiale e, alla lettura, la vista
`bando_pubblico` dice nella colonna `stato_da_verificare` perché lo stato non è certo (migrazione 13,
contratto DB §4.1). Nessuna chiusura a tempo: si chiude solo con un evento provato.

- **Fase controlli**, nei giri delle 06 e delle 18, dopo il monitor: al massimo 40 letture e 900 s,
  al massimo 20 chiusure per giro, con un freno per ente.
- **Fase ingresso**, in ogni giro prima della SEO, senza modello: cerca la scadenza dei bandi nuovi e
  trattiene per al massimo 4 giri un «aperto» senza scadenza né prova (`app/ingresso.py`).
- **Domini**: import completo di IndicePA nel primo giro delle 06 del mese (solo host assenti).
- **Gemelli**: fusione automatica dei doppioni certi fra pubblicati nel giro delle 06, al massimo 10;
  una riga nuova gemella di un pubblicato si fonde nella SEO, a ogni giro e senza tetto.

Tutto segue `VERIFICA_STATO_MODALITA`. In `ombra` (il default) legge, calcola e conta, ma qualcosa
di pubblico cambia già: il motivo `data_apertura_passata` nella vista e, sui bandi nuovi, le date del
preprocess a 8 000 caratteri. Solo in `attivo` arrivano lo stato letto, gli altri motivi, il termine
indicato (il passo lo scrive anche in ombra, ma la vista lo espone solo per i bandi esaminati in
attivo), gli eventi, le fusioni, la scrittura dell'import e la sosta (RIPRESA §1, «Giro 2»).

```bash
cd scraper_bandi
# il report per bando e la verità nota: «difformi: 0» prima di attivare (exit 1 se ce ne sono)
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app report-verifica-stato --verita
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app report-verifica-stato --json --ramo aperto --motivo senza_conferma
# prova del passo: solo --dry-run, niente lock né scritture; dal Mac sempre --senza-modello
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app verifica-stato --dry-run --senza-modello --limit 20
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app verifica-stato --dry-run --senza-modello --fase ingresso
# le fusioni che il giro delle 06 farebbe (solo --dry-run; quelle a mano restano fondi-doppioni)
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app gemelli --dry-run
# import completo di IndicePA: lo fa il giro delle 06 una volta al mese; a mano solo per provarlo.
# Anche `domini --import --attivo [--enti PATH]` aggiunge solo host nuovi e non modifica righe esistenti.
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app domini --import --scarica-enti --dry-run
```

Senza la migrazione 13 il passo non parte (`motivo_saltato: migrazione_assente` nella riga
`verifica_stato` di `pipeline_run`). Finché la verifica non è attiva, anche con la 13 applicata,
`salute` dà l'avviso «non misurato da salute: … stato da verificare (verifica non attiva o
migrazione 13 assente)», e nel riepilogo (`sorveglia --dry-run`) `da_verificare` è null e compare
in `non_misurati`: in ombra è normale. I codici di salute del passo e cosa fare sono in
`docs/bandi-monitor/RIPRESA.md` §3.1.

## SQL migration prerequisito

Prima del primo run, applicare in Supabase SQL editor:

**Step 1** — `backend/sql/fonte_alter_v5_drop_legacy.sql`
Droppa 8 colonne legacy (`titolo`, `note_aggiuntive`, retry_*, last_error_*), crea UNIQUE constraint su `fonte.link` + CHECK su `stato_processing`.

**Step 2** — `backend/sql/bando_alter_v5_for_new_scraper.sql`
Rinomina `titolo`→`titolo_raw`, `descrizione`→`descrizione_raw`. Aggiunge `tipo_link` con CHECK. Droppa 12 colonne legacy (codice_bando, scraping_at, retry, ocr). UNIQUE constraint su `hash_bando` + INDEX su `fonte_id`.

**Step intermedio** — `backend/sql/bando_alter_v6_preprocessing.sql`
Droppa 4 colonne v4 (`data_extra`, `state`, `state_detail`, `state_updated_at`). Aggiunge `stato_bando` (CHECK aperto/chiuso/in apertura prossimamente), `confidence_score REAL [0,1]`, `rejection_reason TEXT`. Cambia default `stato_processing` da `'ready'` a `'scraped'` + CHECK nuovi 5 valori (`scraped`, `processed`, `rejected`, `enriched`, `completed`).

**Step v7** — `backend/sql/bando_alter_v7_enrichment.sql`
Droppa 11 colonne string/array/denormalized (`programma`, `modalita_erogazione`, `beneficiari`, `codici_ateco`, `fondo`, `programma_nome`, `modalita_erogazione_nome`, `codici_ateco_norm`, `beneficiari_norm`, `tipologia`, `tipologia_normalizzata`). Le 3 FK `tipologia_bando_id`, `modalita_erogazione_id`, `programma_id` sono assicurate nullable + INDEX su `(stato_processing, stato_bando)`.

**Step v8** — `backend/sql/bando_alter_v8_skill_cleanup.sql`
Droppa `attempts` (era retry counter v4 collapse, mai più scritto) e `date_quotes` JSONB (era backend rotto; CHECK constraint `bando_date_quotes_length_check` droppato prima).

**Step v9 (add column)** — `backend/sql/bando_alter_v9_add_titolo.sql`
Aggiunge la colonna `titolo TEXT` se non esiste. La skill SEO v8 emette un titolo H1 ≤80 char tra i 14 campi obbligatori; lo schema legacy non aveva questa colonna. **Va applicato prima del reset.**

**Step v9 (reset)** — `backend/sql/bando_reset_for_v9.sql`
Reset per rerun completo della pipeline con preprocess v2: porta tutti i bandi non-rejected a `stato_processing='scraped'`, azzera FK/date/SEO/junction. Idempotente. **Operazione distruttiva**: backup snapshot Supabase consigliato prima di applicare.

**Step v9 (RLS)** — `backend/sql/bando_rls_v9.sql`
Aggiorna RLS policy per il frontend pubblico: `stato_processing='completed' AND slug IS NOT NULL`. Abilita read pubblico su junction tables e tabelle catalogo. Sostituisce la policy legacy `state='confirmed'` (colonna droppata v6). Senza questa migration il frontend mostra 0 bandi.

**Step v10 (dedup cross-source + fonti esterne)** — `backend/sql/bando_alter_v10_canonical_key.sql` + `fonte_insert_v10_external_sources.sql`
- ADD COLUMN `canonical_key TEXT` (UNIQUE partial index) + `fonti_aggiuntive INTEGER[]` per dedup bandi pubblicati da più portali. Calcolata dalla skill SEO con `SHA256(norm_titolo|norm_ente|data_scadenza|importo)`. Quando un nuovo bando collide con un master esistente, il master raccoglie la `fonte_id` aggiuntiva e il duplicato passa a `stato_processing='completed_duplicate'` (nascosto dal frontend via RLS).
- ALTER constraint `bando_stato_processing_check` per includere `'completed_duplicate'`.
- INSERT 3 fonti nuove migrate dal repo esterno ScrapingBandi:
  - Obiettivo Europa (API JSON con login Django CSRF, 1133+ bandi)
  - Italia Domani PNRR (HTML offset-based, amministrazioni titolari)
  - Incentivi Gov IT (Solr API Drupal, 20+ campi finanziari per bando)

## Tabella `bando` — schema corrente + ordine logico

Lo schema fisico delle colonne nel DB Supabase **non corrisponde** all'ordine logico raccomandato (PostgreSQL non riordina senza rebuild table). L'ordine logico qui sotto è il riferimento per documentazione e query SELECT mirate.

| Gruppo | Colonna | Tipo | Origine | Note |
|---|---|---|---|---|
| **Identità + scraper** | `id` | bigserial PK | DB | |
| | `fonte_id` | int FK → `fonte` | Scraper | |
| | `hash_bando` | text UNIQUE | Scraper (SHA256) | dedup key |
| | `tipo_link` | text (`Opportunità`\|`Preavviso`) | Scraper (da fonte) | |
| | `raw_data` | jsonb nullable | Scraper | metadati (NULL se link presente) |
| | `link_bando` | text nullable | Scraper | URL dettaglio |
| | `titolo_raw` | text | Scraper | |
| | `descrizione_raw` | text | Scraper | |
| **Pipeline state** | `stato_processing` | text | preprocess/enrich/seo | `scraped` → `processed` → `enriched` → `completed` (oppure `rejected`) |
| | `stato_bando` | text nullable | preprocess + enrich PHASE A | `aperto` \| `chiuso` \| `in apertura prossimamente` |
| | `confidence_score` | real [0,1] | preprocess | confidenza LLM validazione |
| | `rejection_reason` | text nullable | preprocess | motivo `rejected` |
| **Classification (FK)** | `tipologia_bando_id` | int FK | enrich PHASE B | → `tipologie_bando` |
| | `modalita_erogazione_id` | int FK | enrich PHASE B | → `modalita_erogazione` |
| | `programma_id` | int FK | enrich PHASE B | → `programmi` |
| **Date (enricher v7)** | `data_pubblicazione` | date nullable | enrich PHASE B | gate substring + source autoritativo |
| | `data_apertura` | date nullable | enrich PHASE B | |
| | `data_scadenza` | date nullable | enrich PHASE B | CHECK: pub ≤ scad |
| **Skill output (v8)** | `slug` | varchar(255) UNIQUE | skill SEO | kebab-case |
| | `titolo` | text | skill SEO | H1 ≤80 char sentence case |
| | `titolo_breve` | text nullable | skill SEO | occhiello ≤100 char |
| | `descrizione_breve` | text | skill SEO | 180-320 char |
| | `contenuto` | jsonb | skill SEO | `{sections: [...]}` |
| | `livello` | text | skill SEO | `flash_bando` \| `guida_bando` |
| | `allegati` | jsonb | skill SEO | array `{label, url, tipo}` |
| | `ente_erogatore` | text | skill SEO | substring-validated |
| | `area_geografica` | text nullable | skill SEO | |
| | `tematica` | text[] | skill SEO | 1-3 tag |
| | `importo_totale_eur` | bigint nullable | skill SEO | |
| | `importo_max_per_progetto_eur` | bigint nullable | skill SEO | |
| | `link_candidatura` | text nullable | skill SEO | reachability-checked |
| | `link_candidatura_source` | text | skill SEO | `extracted` \| `fallback_source` \| `missing` |
| **Audit** | `created_at`, `updated_at` | timestamptz | DB | |

### Junction tables (popolate dall'enricher v7)

- `bando_beneficiari` (PK `(bando_id, beneficiario_id)`)
- `bando_codici_ateco` (PK `(bando_id, codice_ateco_id)`)
- `bando_regioni` (PK `(bando_id, regione_id)`)
- `bando_settori` (PK `(bando_id, settore_id)`)

## Strategie di scraping

Vedi `app/scraper_config.py` per il mapping completo delle 108 fonti. Distribuzione:

| Strategia | N fonti |
|---|---|
| httpx_bs4 | 38 |
| firecrawl_scrape | 18 |
| firecrawl_extract | 1 |
| hybrid_httpx_firecrawl | 16 |
| csv_parser | 8 |
| pdf_extract_tables_pdfplumber | 5 |
| pdf_extract_text | 1 |
| skip_no_bandi | 19 |
