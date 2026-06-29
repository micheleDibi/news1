# scraper_bandi

Nuovo scraper bandi per il progetto news1. Sostituisce il precedente subproject `Scraper-gerarchico-bandi-OpenCoesione-Backend-Python/` (rimosso in v5).

Costruito in **step incrementali**:

- **Step 1 (questo)**: discovery delle **fonti** dalla pagina indice di OpenCoesione (`https://opencoesione.gov.it/it/opportunita_2021_2027/`) → popola la tabella `fonte` su Supabase DB B.
- **Step 2 (prossimo)**: scraping di ogni fonte estratta → popola la tabella `bando`.
- **Step 3+**: TBD.

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

## Comando

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
   - `attivo = FALSE` (timeout/DNS/4xx/5xx) → `stato_processing = 'connection_error'`
6. **Mark deprecato**: per ogni record gia' in DB ma non piu' presente nella pagina sorgente → `stato_processing = 'deprecated'`.

Log finale: `{discovered, inserted, updated, deprecated, connection_error}`.

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
| `stato_processing` | text (`ready` \| `connection_error` \| `deprecated`) | Scraper |
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

## SQL migration prerequisito

Prima del primo run, applicare:

```bash
psql "$DATABASE_URL_BANDI" -f ../backend/sql/fonte_alter_v5_drop_legacy.sql
```

Droppa 8 colonne legacy (`titolo`, `note_aggiuntive`, retry_*, last_error_*) e crea l'UNIQUE index su `link`.
