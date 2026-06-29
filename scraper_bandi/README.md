# scraper_bandi

Nuovo scraper bandi per il progetto news1. Sostituisce il precedente subproject `Scraper-gerarchico-bandi-OpenCoesione-Backend-Python/` (rimosso in v5).

Costruito in **step incrementali**:

- **Step 1 (completato)**: discovery delle **fonti** dalla pagina indice di OpenCoesione (`https://opencoesione.gov.it/it/opportunita_2021_2027/`) → popola la tabella `fonte` su Supabase DB B.
- **Step 2 (questo)**: scraping di ogni fonte estratta → popola la tabella `bando`. Strategia per fonte mappata in `app/scraper_config.py` (108 entry).
- **Step 3+**: enrichment skill SEO (gia' esistente in `bandi-seo-enricher/`).

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

## SQL migration prerequisito

Prima del primo run, applicare in Supabase SQL editor:

**Step 1** — `backend/sql/fonte_alter_v5_drop_legacy.sql`
Droppa 8 colonne legacy (`titolo`, `note_aggiuntive`, retry_*, last_error_*), crea UNIQUE constraint su `fonte.link` + CHECK su `stato_processing`.

**Step 2** — `backend/sql/bando_alter_v5_for_new_scraper.sql`
Rinomina `titolo`→`titolo_raw`, `descrizione`→`descrizione_raw`. Aggiunge `tipo_link` con CHECK. Droppa 12 colonne legacy (codice_bando, scraping_at, retry, ocr). UNIQUE constraint su `hash_bando` + INDEX su `fonte_id`.

## Tabella `bando` (schema post-Step 2)

| Colonna | Tipo | Origine |
|---|---|---|
| `id` | bigserial PK | DB |
| `fonte_id` | int FK → `fonte` | Scraper |
| `hash_bando` | text UNIQUE | Scraper (SHA256) |
| `tipo_link` | text (`Opportunità` \| `Preavviso`) | Da fonte.tipo_link |
| `link_bando` | text nullable | Scraper (URL dettaglio bando, null per bandi senza link) |
| `titolo_raw` | text | Scraper (testo del link / titolo da CSV/PDF) |
| `descrizione_raw` | text | Scraper |
| `raw_data` | jsonb nullable | NULL se ha link; JSONB con info estratte se non ha link |
| `created_at`, `updated_at` | timestamptz | DB |

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
