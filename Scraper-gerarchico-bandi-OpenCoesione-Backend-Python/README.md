# Scraper gerarchico bandi OpenCoesione — Backend Python

## Panoramica
Questo progetto implementa un backend Python per lo scraping gerarchico dei bandi pubblicati tramite OpenCoesione 2021–2027.

---

## Avvio rapido

```bash
# 1. Crea ambiente virtuale
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS

# 2. Installa dipendenze
pip install -r requirements.txt

# 3. Configura variabili d'ambiente
cp .env.example .env
# → modifica .env con le credenziali reali

# 4. Test unitari (no DB richiesto)
pytest app/tests/test_milestone1.py -v -m "not integration"

# 5. Test di integrazione (richiede DB)
pytest app/tests/test_milestone1.py -v
```

## Comandi di esecuzione

### CLI (esecuzione manuale)

```powershell
# Run completo su tutte le fonti attive
.\.venv\Scripts\python.exe -m app.cli run

# Run limitato alle prime N fonti
.\.venv\Scripts\python.exe -m app.cli run --limit 3

# Run su singola fonte (per id)
.\.venv\Scripts\python.exe -m app.cli run-fonte --fonte-id 42

# Run solo sulle fonti in stato pending (retry scaduti)
.\.venv\Scripts\python.exe -m app.cli run-pending
```

### Scheduler (esecuzione pianificata)

```powershell
# Avvio scheduler bloccante — default: 02:00 run completo, ogni 4h pending
.\.venv\Scripts\python.exe -m app.scheduler start

# Con cron personalizzato
.\.venv\Scripts\python.exe -m app.scheduler start --cron-full "0 3 * * *" --cron-pending "0 */2 * * *"

# Esegue subito un ciclo completo e termina
.\.venv\Scripts\python.exe -m app.scheduler run-now

# Esegue subito solo la coda pending e termina
.\.venv\Scripts\python.exe -m app.scheduler run-pending-now
```

### Pipeline AI

```powershell
# Accoda manualmente bandi incompleti
.\.venv\Scripts\python.exe -m app.ai.run_ai_enqueue --limit 100

# Processa la coda AI
.\.venv\Scripts\python.exe -m app.ai.run_ai_worker --limit 10
```

### Discovery fonti

```powershell
.\.venv\Scripts\python.exe -m app.scrapers.run_fonte_discovery
```

Per la procedura operativa completa (smoke test, troubleshooting, esempi di output JSON) vedi [docs/avvio_manuale_scraper.md](docs/avvio_manuale_scraper.md).

---

## Avvio manuale reale dello scraper

Per la procedura operativa completa di discovery fonti, smoke test e run reale dei bandi, vedi [docs/avvio_manuale_scraper.md](docs/avvio_manuale_scraper.md).

## Struttura progetto

```
app/
├── config/       # settings, logging, session_id
├── db/           # connessione Supabase/PostgreSQL
├── models/       # Pydantic models che mappano le tabelle
├── repos/        # repository base per accesso dati
├── services/     # business logic
├── scrapers/     # scraper gerarchici (fonte → bando)
├── parsers/      # parsing HTML/PDF
├── ai/           # pipeline AI asincrona (OpenAI)
├── ocr/          # estrazione testo da PDF scansionati (Tesseract)
├── queues/       # worker Celery + Redis
└── tests/        # test unitari e di integrazione
```

## Variabili d'ambiente principali

| Variabile | Descrizione |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `SUPABASE_URL` | URL progetto Supabase |
| `SUPABASE_KEY` | Service-role key Supabase |
| `OPENAI_API_KEY` | API key OpenAI |
| `LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `LOG_JSON` | `true` per JSON strutturato, `false` per console colorata |

Il sistema esplora dinamicamente la struttura delle fonti, individua i bandi, estrae i dati principali, aggiorna il database Supabase/PostgreSQL esistente e traccia sia le modifiche sui bandi sia le anomalie riscontrate durante l’elaborazione.

Il backend è progettato per:
- lavorare in modo schedulato o manuale con comportamento identico
- evitare duplicazioni
- gestire storico modifiche
- usare OCR per PDF scansionati
- usare OpenAI in modo asincrono e controllato
- classificare solo attingendo ai valori già presenti nelle tabelle di riferimento
- gestire retry automatici per errori recuperabili

---

## Obiettivi funzionali
Il sistema deve:
1. leggere in modo dinamico la pagina principale delle opportunità
2. individuare le fonti figlie senza URL hardcoded
3. estrarre i bandi dalle fonti HTML, PDF, CSV e, se necessario, ZIP
4. salvare o aggiornare i bandi nel database
5. tracciare ogni variazione significativa
6. classificare i campi mancanti usando AI asincrona senza inventare dati
7. eseguire OCR sui PDF scansionati
8. mettere in pending gli errori recuperabili ed effettuare retry automatici
9. spostare gli elementi non recuperabili in una tabella dedicata dopo il superamento dei retry

---

## Vincoli principali
- Database già esistente su Supabase/PostgreSQL
- Lo scraper non deve inserire nuovi record nelle tabelle di riferimento
- Anche l’AI non deve inventare nuovi valori
- L’AI può solo scegliere tra i valori effettivamente presenti nel database
- I PDF scansionati devono passare da OCR
- Gli errori recuperabili devono essere riprocessati automaticamente
- Output iniziale di tipo tabellare

---

## Schema attuale rilevante
Le tabelle attualmente presenti includono:
- `bando`
- `bando_codici_ateco`
- `bando_regioni`
- `bando_settori`
- `bando_storico`
- `beneficiari`
- `categoria_programma`
- `codici_ateco`
- `fonte`
- `modalita_erogazione`
- `programmi`
- `regioni`
- `scraping_log`
- `settori`
- `tipologia_programma`
- `tipologie_bando`

### Osservazioni importanti sullo schema
Dalla struttura attuale emergono alcuni aspetti da verificare o estendere:
- potrebbe mancare una tabella ponte per i beneficiari, dato che il requisito è 1-N
- manca una struttura esplicita per la coda pending/retry, salvo decidere di gestirla con nuove colonne o tabella dedicata
- manca una tabella esplicita per errori definitivi / anomalie permanenti
- va definita con precisione la collocazione del tracking retry

---

## Architettura logica

### 1. Discovery delle fonti
Il sistema parte dalla pagina principale OpenCoesione e scopre dinamicamente le fonti figlie.  
Ogni fonte viene classificata e sincronizzata nella tabella `fonte`.

### 2. Estrazione dei bandi
Per ogni fonte attiva il sistema:
- scarica il contenuto
- individua i bandi
- produce una rappresentazione grezza (`raw_data`)
- genera una chiave univoca (`hash_bando`)

### 3. Parsing dettagli
Il sistema estrae i campi principali del bando:
- titolo
- descrizione
- codice
- stato
- date
- importo
- link
- metadati utili

### 4. Upsert e storico
Se il bando non esiste viene inserito.  
Se esiste, viene aggiornato solo dove necessario.  
Le differenze vengono registrate in `bando_storico`.

### 5. Classificazione relazionale
Il sistema tenta di popolare:
- tipologia bando
- modalità di erogazione
- programma
- codici ATECO
- regioni
- settori
- beneficiari

Questa fase può essere:
- deterministica, tramite matching su dizionari caricati dal DB
- supportata dall’AI in casi incerti o mancanti

### 6. Pipeline AI asincrona
L’AI non gira nel thread principale di scraping.
Riceve:
- testo estratto
- metadati
- link
- vocabolari già presenti nel DB

Restituisce esclusivamente valori compatibili con i record esistenti.

### 7. PDF e OCR
Se un PDF contiene testo selezionabile, viene usato parser testuale.  
Se il PDF è scansionato, viene attivata la pipeline OCR.  
Il testo OCR confluisce poi nel parser e nell’eventuale classificazione AI.

### 8. Retry e gestione errori
Se un bando o una fonte fallisce per errore recuperabile:
- va in pending
- viene incrementato il contatore retry
- viene pianificato un nuovo tentativo

Se supera la soglia massima:
- viene marcato come errore definitivo
- viene spostato o tracciato in una tabella dedicata

---

## Flusso operativo

```text
Pagina principale OpenCoesione
    ↓
Scoperta dinamica fonti
    ↓
Scraping fonte
    ↓
Identificazione bandi
    ↓
Parsing contenuto (HTML / CSV / PDF)
    ↓
OCR se PDF scansionato
    ↓
Upsert su bando
    ↓
Classificazione relazionale
    ↓
AI asincrona per campi mancanti/ambigui
    ↓
Storico modifiche + logging
    ↓
Retry automatici se errore recuperabile
```

---

## Modello di esecuzione

### Esecuzione manuale
Tramite `app.cli` con i sottocomandi `run`, `run-fonte`, `run-pending`.

### Esecuzione schedulata
Tramite `app.scheduler` (APScheduler 3.x) con scheduler bloccante.
I parametri cron sono configurabili via flag `--cron-full` e `--cron-pending`.

### Requisito fondamentale
Il comportamento tra esecuzione manuale e schedulata è identico: entrambi chiamano la stessa `BandoDiscoveryService.run()` pipeline.

---

## Regole di business principali

### Unicità del bando
Ogni bando deve essere identificato in modo stabile tramite:
- hash derivato da URL e/o identificativo
- eventuale codice bando se affidabile

### Aggiornamento invece di duplicazione
Se il bando esiste:
- aggiornare i campi variati
- non creare un nuovo record

### Storico obbligatorio
Ogni modifica rilevante va tracciata.  
Le transizioni di stato devono essere sempre registrate.

### Priorità di stato
I bandi `aperto` e `programmato` sono prioritari, ma gli altri stati devono restare censiti.

### AI a dizionario chiuso
L’AI non può:
- inventare categorie
- inventare programmi
- inventare ATECO
- inventare regioni o settori
- inserire nuovi record

L’AI può solo:
- scegliere tra i valori esistenti
- restituire “nessuna corrispondenza valida” quando non trova match sicuri

---

## Struttura tecnica suggerita

```text
app/
  config/
  db/
  models/
  repos/
  services/
  scrapers/
  parsers/
  ai/
  ocr/
  queues/
  tests/
```

### Moduli chiave
- `scrapers/`: navigazione dei livelli e discovery fonti/bandi
- `parsers/`: estrazione dati da HTML, CSV, PDF
- `ocr/`: OCR e text extraction fallback
- `services/`: orchestrazione business
- `repos/`: accesso a Supabase/PostgreSQL
- `ai/`: prompt building, validazione output, orchestration async
- `queues/`: gestione pending, retry, job AI

---

## Dati principali da estrarre

### Campi diretti
- titolo
- codice identificativo
- descrizione
- stato bando
- data apertura
- data scadenza
- data pubblicazione
- link diretto
- importo
- importo numerico
- raw data
- eventuali dati extra

### Relazioni
- fonte
- tipo fondo
- beneficiari
- categoria programma
- codici ATECO
- modalità erogazione
- programma
- tipologia programma
- tipologia bando
- regioni
- settori

---

## Gestione AI

### Quando si attiva
L’AI viene invocata solo quando:
- un campo non è estraibile in modo certo
- la classificazione richiede inferenza controllata
- servono match tra testo e reference data

### Input AI
- testo estratto dalla pagina o dal documento
- metadati del bando
- contesto della fonte
- elenchi aggiornati dal DB

### Output AI atteso
Un payload strutturato che contenga solo:
- ID o nomi presenti nei dizionari del database
- confidenza o spiegazione della scelta
- eventuale assenza di match

### Validazione
Ogni output AI deve essere validato server-side prima della persistenza.

---

## Gestione OCR

### Casi previsti
1. PDF testuale → parsing diretto  
2. PDF scansionato → OCR  
3. PDF corrotto/non leggibile → errore recuperabile o definitivo

### Obiettivo OCR
Convertire un documento scansionato in testo utile per:
- parsing base
- classificazione AI
- audit/debug

---

## Gestione retry

### Errori recuperabili
Esempi:
- timeout HTTP
- 503/504
- file temporaneamente irraggiungibile
- OCR fallito per errore infrastrutturale
- parsing momentaneamente non riuscito per problema di download

### Errori non recuperabili
Esempi:
- 404 persistente
- file strutturalmente corrotto
- contenuto non supportato
- output AI sempre invalido e non risolvibile

### Politica
- incremento retry count
- pianificazione prossimo tentativo
- soglia configurabile
- superata la soglia → errore definitivo

---

## Logging e audit

### Scraping log
La tabella `scraping_log` consente di tracciare:
- sessione
- fonte
- URL
- stato run
- conteggi
- errori
- tempi
- metadati request/response

### Storico bandi
La tabella `bando_storico` tiene traccia di:
- dati precedenti
- dati nuovi
- campi modificati
- riferimento al log di scraping
- timestamp modifica

---

## Testing

### Unit test
- parser HTML
- parser PDF
- parser CSV
- generazione hash
- matching reference data
- validazione output AI
- policy retry

### Integration test
- repository DB
- upsert bandi
- storico
- relazioni
- log scraping
- coda AI
- OCR pipeline

### End-to-end
- pagina principale → fonte → bando → DB
- PDF scansionato → OCR → AI → classificazione
- pending → retry → successo
- pending → retry max → errore definitivo

---

## Stato di implementazione

| Area | Stato | Note |
|---|---|---|
| Discovery fonti | ✅ Implementato | `app.scrapers.run_fonte_discovery` |
| Scraping HTML/CSV/PDF/ZIP | ✅ Implementato | `FonteLevel2Scanner` |
| Parsing bandi | ✅ Implementato | `app/parsers/bando_parser.py` |
| Upsert + storico | ✅ Implementato | `BandoRepo.upsert_candidates` |
| Classificazione deterministica | ✅ Implementato | `ControlledClassificationService` |
| Pipeline AI asincrona | ✅ Implementato | `AiPipelineService`, `app.ai.run_ai_worker` |
| OCR PDF scansionati | ✅ Implementato | `app/ocr/`, Tesseract |
| Retry / pending queue | ✅ Implementato | `stato_processing`, `next_retry_at`, `scraping_errori_definitivi` |
| Logging / observability | ✅ Implementato | `scraping_log` per-sessione e per-fonte, `v_scraping_log_run` |
| CLI entry-point | ✅ Implementato | `app.cli` (run, run-fonte, run-pending) |
| Scheduler | ✅ Implementato | `app.scheduler` (APScheduler 3.x) |
| Test suite | ✅ Implementato | Milestone 1–12, 50+ test |
| Documentazione | ✅ Completata | README, `docs/avvio_manuale_scraper.md`, `docs/installazione.md` |


## Requisiti non funzionali
- robustezza ai cambi di struttura HTML
- idempotenza degli aggiornamenti
- tracciabilità delle modifiche
- separazione tra scraping e AI
- nessuna scrittura impropria nelle tabelle di riferimento
- possibilità di riesecuzione sicura

---

## Deliverable attesi
- backend Python modulare
- integrazione Supabase/PostgreSQL
- pipeline scraping
- pipeline OCR
- pipeline AI asincrona
- retry e pending management
- test suite
- documentazione tecnica

---

## Definizione di successo
Il progetto è considerato riuscito quando:
- i bandi vengono acquisiti senza duplicazione
- i cambiamenti vengono storicizzati
- i PDF scansionati sono gestiti
- l’AI lavora solo su valori esistenti nel DB
- i retry recuperano gli errori temporanei
- gli errori definitivi restano auditabili
- il sistema può essere eseguito manualmente o schedulato senza differenze di comportamento
