# Avvio manuale reale dello scraper

Questa guida descrive come eseguire manualmente lo scraper contro il database reale e le fonti reali OpenCoesione.

## Quando usare questa procedura

Usa questa procedura quando vuoi:
- popolare o aggiornare la tabella `fonte`
- eseguire una scansione reale dei bandi
- verificare manualmente il comportamento end-to-end
- fare uno smoke test controllato prima di una run completa

## Prerequisiti

Dal root del repository:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Crea il file `.env` partendo da `.env.example` e valorizza almeno queste variabili:
- `DATABASE_URL`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SOURCE_ROOT_URL`

Variabili utili già supportate:
- `DATABASE_POOLER_HOST`
- `DATABASE_POOLER_PORT`
- `DATABASE_CONNECT_TIMEOUT_SECONDS`
- `DATABASE_SSLMODE`
- `SCRAPER_TIMEOUT_SECONDS`
- `SCRAPER_RETRY_MAX`
- `IMPORTO_PLAUSIBILE_THRESHOLD` (default `1000`): soglia usata dal parser quando deve scegliere tra piu candidati importo

Nota operativa:
- se la connessione diretta a Supabase non è disponibile, il progetto prova automaticamente il fallback tramite pooler

## Verifica minima prima della run reale

Per controllare rapidamente che ambiente e configurazione siano coerenti:

```powershell
.\.venv\Scripts\python.exe -m pytest app/tests/test_milestone1.py -v
```

Se vuoi solo una verifica veloce senza test di integrazione DB:

```powershell
.\.venv\Scripts\python.exe -m pytest app/tests/test_milestone1.py -v -m "not integration"
```

## Ordine corretto di esecuzione manuale

La sequenza reale da usare è questa:
1. discovery delle fonti
2. scansione delle fonti attive e identificazione bandi

## 1. Discovery reale delle fonti

Questo step legge `SOURCE_ROOT_URL`, estrae le fonti figlie e sincronizza la tabella `fonte`.

Comando:

```powershell
.\.venv\Scripts\python.exe -m app.scrapers.run_fonte_discovery
```

Effetti attesi:
- lettura della pagina principale OpenCoesione
- classificazione dei link trovati
- insert o update nella tabella `fonte`
- scrittura di un record in `scraping_log`

Output atteso:
- JSON finale stampato a console con contatori e `session_id`

## 2. Scan reale dei bandi

Questo step prende le fonti attive e prova a identificare i bandi, con parsing dei campi principali e upsert su `bando`.

### Smoke test limitato

Per una prima esecuzione controllata:

```powershell
.\.venv\Scripts\python.exe -m app.cli run --limit 3
```

Uso consigliato:
- prima run in un ambiente appena configurato
- verifica rapida della connettività e dei parser
- controllo dei log senza lanciare subito la scansione completa

### Run su singola fonte

Per processare solo una fonte specifica (utile per debug):

```powershell
.\.venv\Scripts\python.exe -m app.cli run-fonte --fonte-id 42
```

### Run completa

Quando lo smoke test è stabile:

```powershell
.\.venv\Scripts\python.exe -m app.cli run
```

Effetti attesi:
- fetch delle fonti attive
- identificazione candidati bando da HTML, CSV, PDF e ZIP supportati
- parsing di titolo, descrizione, codice, stato, date, importi
- upsert su `bando`
- scrittura storico su `bando_storico` quando ci sono modifiche
- scrittura del log di esecuzione su `scraping_log`

Output atteso:
- JSON finale con campi simili a:

```json
{
  "session_id": "...",
  "scraping_log_id": 9,
  "fonti_scansionate": 3,
  "bandi_identificati": 9,
  "errori_fonti": 0,
  "processed": 9,
  "inserted": 0,
  "updated": 0,
  "unchanged": 9,
  "ai_jobs": {
    "considered": 9,
    "enqueued": 4,
    "already_present": 2,
    "not_required": 3
  },
  "retry": {
    "fonti_pending": 1,
    "fonti_failed_final": 0,
    "bandi_pending": 2,
    "bandi_failed_final": 0,
    "errori_definitivi": 0
  },
  "page_fetch": {
    "attempted": 9,
    "failed": 1,
    "failure_rate": 0.1111
  }
}
```

Nota su `page_fetch`:
- `attempted`: numero tentativi fetch pagina dettaglio
- `failed`: fetch pagina fallite (timeout, SSL, rete, ecc.)
- `failure_rate`: rapporto `failed/attempted`
- i fallimenti fetch non bloccano la run: riducono solo l'enrichment del singolo bando

## 2.1 Retry, pending queue ed errori definitivi (Milestone 9)

La scan bandi ora gestisce retry automatici su errori recuperabili:
- `fonte.stato_processing` passa a `pending` con `next_retry_at` per errori temporanei
- `bando.stato_processing` passa a `pending` su errori temporanei di parsing/candidate extraction
- al superamento `max_retry`, lo stato diventa `failed_final`
- gli errori finali vengono registrati in `scraping_errori_definitivi` con contesto

Regole pratiche:
- errori timeout / rete / 5xx / 429 sono trattati come recuperabili
- errori non recuperabili passano subito a `failed_final`
- le entita in `failed_final` non vengono reinserite automaticamente nel run successivo
- `max_retry` e `retry_delay` sono configurati da `SCRAPER_RETRY_MAX` e `SCRAPER_RETRY_DELAY_SECONDS`

## 2.2 Backfill dataset (date/importi) su record esistenti

Questo step e' utile quando hai gia record nel DB e vuoi recuperare campi mancanti o migliorare importi sotto soglia senza rifare truncate.

### Dry-run (consigliato prima)

Mostra quanti record sarebbero aggiornati, senza scrivere nel DB:

```powershell
.\.venv\Scripts\python.exe -m app.scrapers.run_dataset_dates_backfill
```

### Apply standard

Compila solo i campi attualmente `NULL` (date/importo/importo_numerico):

```powershell
.\.venv\Scripts\python.exe -m app.scrapers.run_dataset_dates_backfill --apply
```

### Apply con upgrade importi sotto soglia

Oltre ai `NULL`, aggiorna anche `importo_numerico` gia presente ma `<= soglia` quando il parser trova un valore migliore sopra soglia:

```powershell
.\.venv\Scripts\python.exe -m app.scrapers.run_dataset_dates_backfill --apply --upgrade-low-importo
```

### Apply con soglia esplicita

Usa una soglia specifica (default: `IMPORTO_PLAUSIBILE_THRESHOLD`, tipicamente `1000`):

```powershell
.\.venv\Scripts\python.exe -m app.scrapers.run_dataset_dates_backfill --apply --upgrade-low-importo --importo-threshold 1000
```

### Limitare il campione (debug rapido)

```powershell
.\.venv\Scripts\python.exe -m app.scrapers.run_dataset_dates_backfill --apply --upgrade-low-importo --limit 200
```

## 3. Pipeline AI asincrona (Milestone 7)

La fase AI e' separata dal flusso principale:
- la scansione bandi mette in coda job AI quando restano campi mancanti
- il worker AI processa la coda in modo asincrono

Regole di ingresso al worker AI:
- i bandi con `stato_bando = 'sospetto'` non entrano proprio nel flusso AI
- per i bandi non sospetti, il worker verifica prima il titolo
- se il titolo è generico o poco specifico, prova a riformularlo usando descrizione, link e snippet testuali disponibili
- solo dopo questa normalizzazione passa alla classificazione dei campi mancanti

Prima della classificazione vera e propria, il worker esegue un gate iniziale sul titolo:
- blocca titoli troppo generici o navigazionali come `Bandi e Gare`, `Bandi e Opportunita`, `Avvisi`, `Call`, `Home`
- verifica che il titolo sia coerente almeno in parte con descrizione, link e snippet testuali disponibili
- se il titolo non supera il gate, il job viene chiuso senza chiamare OpenAI e non passa agli step successivi
- i record bloccati vengono marcati internamente come `title_gate_skipped` nel flusso AI

Questo evita che pagine indice o liste generiche arrivino alla classificazione AI come se fossero bandi già pronti.

### Enqueue manuale da bandi esistenti

Per accodare manualmente bandi incompleti:

```powershell
.\.venv\Scripts\python.exe -m app.ai.run_ai_enqueue --limit 100
```

Con log di avanzamento periodico:

```powershell
.\.venv\Scripts\python.exe -m app.ai.run_ai_enqueue --limit 1000 --report-every 50
```

Output atteso:
- contatori `considered`, `enqueued`, `already_present`, `not_required`
- log progressivi ogni `N` bandi quando usi `--report-every`
- log di avvio e fine enqueue con riepilogo contatori

Opzioni principali enqueue:
- `--limit` (default `100`): numero massimo di bandi da valutare
- `--report-every` (default `100`): frequenza log avanzamento (ogni N bandi)

### Esecuzione worker AI

Per processare i job in coda:

```powershell
.\.venv\Scripts\python.exe -m app.ai.run_ai_worker --limit 10
```

Nota ETA:
- l'ETA viene calcolata e loggata solo in modalita `--drain-all`
- senza `--drain-all` il worker processa un solo batch e termina

**Opzioni disponibili:**

| Flag | Default | Descrizione |
|------|---------|-------------|
| `--limit` | 100 | Numero di job da processare per batch |
| `--drain-all` | ❌ (assente) | Se presente, continua batch dopo batch fino a coda vuota. Senza questo flag, processa solo un batch e termina |
| `--call-delay` | 0.5 | Delay in secondi tra una chiamata OpenAI e la successiva (evita rate-limiting) |
| `--report-every` | 1 | Frequenza di reporting progress: stampa log ogni N batch |

**Esempi di utilizzo:**

```powershell
# Processa un singolo batch di 10 job
.\.venv\Scripts\python.exe -m app.ai.run_ai_worker --limit 10

# Processa batch da 50 job fino a coda vuota, con delay 0.5s tra chiamate
.\.venv\Scripts\python.exe -m app.ai.run_ai_worker --limit 50 --drain-all

# Drain aggressivo: batch da 100, delay ridotto, report ogni 2 batch
.\.venv\Scripts\python.exe -m app.ai.run_ai_worker --limit 100 --drain-all --call-delay 0.3 --report-every 2

# Drain conservativo: batch da 30, delay alto per evitare rate-limit
.\.venv\Scripts\python.exe -m app.ai.run_ai_worker --limit 30 --drain-all --call-delay 1.0
```

**Output atteso (drain-all):**
```
batch=1/15 claimed=50 completed=50 failed=0 discarded=0 queued_remaining=449 elapsed=00:02:15 eta=00:31:45
batch=2/15 claimed=50 completed=50 failed=0 discarded=0 queued_remaining=399 elapsed=00:04:30 eta=00:28:30
...
batch=15/15 claimed=49 completed=49 failed=0 discarded=0 queued_remaining=0 elapsed=00:45:12 eta=00:00:00
{
  "batches": 15,
  "claimed": 749,
  "completed": 747,
  "failed": 2,
  "discarded_payloads": 0,
  "queue_status": {"queued": 0, "completed": 747, ...},
  "elapsed_hms": "00:45:12"
}
```

**Regole importanti:**
- il worker applica solo classificazioni validate contro i dizionari del DB
- valori AI fuori dizionario vengono scartati e loggati
- il flusso di scraping non viene bloccato dal worker AI
- ETA si adegua dinamicamente ogni 5 batch sulla base del throughput recente (rolling window) in modalita `--drain-all`

## Cosa aspettarsi nel database

Dopo la discovery:
- aggiornamenti in `fonte`
- un log in `scraping_log`

Dopo la scan bandi:
- insert o update in `bando`
- nuove righe in `bando_storico` solo se ci sono cambi reali
- nuovo log in `scraping_log`

Comportamento importante:
- se una run trova record invariati, `bando_storico` non cresce
- se cambia almeno un campo tracciato, viene scritto uno storico con `campi_modificati`
- le transizioni di `stato_bando` vengono registrate nello storico

## Bandi Sospetto (Candidati da Pagina Lista)

Quando il parser elabora un candidato estratto da una pagina di lista/elenco (non da pagina dettaglio), e tutti e quattro i campi critici rimangono NULL:
- `data_pubblicazione`, `data_apertura`, `data_scadenza`, `importo_numerico`

Il record viene salvato nel DB con **`stato_bando = 'sospetto'`**.

### Significato
- Il candidato è stato estratto correttamente e identificato come link a un bando
- Però la pagina scaricata non è la pagina di dettaglio vero, ma una pagina di lista/navigazione
- I dati non sono disponibili, quindi il record è incompleto

### Effetti sui KPI
- I record sospetto **non** vengono contati nel calcolo delle percentuali KPI
- Questo evita di inquinare le metriche con candidati incomplete
- Le query KPI hanno filtri `WHERE stato_bando != 'sospetto'` per escluderli

### Monitoraggio
Per visualizzare i bandi sospetto:

```sql
SELECT
  COUNT(*) AS totale_sospetti,
  COUNT(DISTINCT fonte_id) AS num_fonti_con_sospetti
FROM public.bando
WHERE stato_bando = 'sospetto';
```

Per vedere un campione:

```sql
SELECT id, fonte_id, titolo, link_bando, primo_scraping_at
FROM public.bando
WHERE stato_bando = 'sospetto'
ORDER BY id ASC
LIMIT 50;
```

### Azioni Consigliate
- **Se totale_sospetti < 2% dell'universo**: ignora, è accettabile.
- **Se totale_sospetti > 5%**: considera di migliorare la logica di fetch per scendere un livello più in basso (da lista a dettaglio).
- **Per fonte specifica problematica**: rivedi il formato/struttura della fonte in questione.
- **Esclusione dai KPI**: è già automatica nelle query di monitoraggio.

## Procedura pratica consigliata

Per un avvio manuale pulito:

```powershell
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m app.scrapers.run_fonte_discovery
.\.venv\Scripts\python.exe -m app.cli run --limit 3
.\.venv\Scripts\python.exe -m app.cli run
.\.venv\Scripts\python.exe -m app.ai.run_ai_enqueue --limit 1000 --report-every 50
.\.venv\Scripts\python.exe -m app.ai.run_ai_worker --limit 50 --drain-all --call-delay 0.5
```

**Versione ridotta (solo complete run senza test):**

```powershell
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m app.scrapers.run_fonte_discovery
.\.venv\Scripts\python.exe -m app.cli run
.\.venv\Scripts\python.exe -m app.ai.run_ai_enqueue --limit 1000 --report-every 50
.\.venv\Scripts\python.exe -m app.ai.run_ai_worker --limit 50 --drain-all
```

## Troubleshooting rapido

### Messaggio di fallback sul pooler

Messaggio tipico:

```text
Connessione diretta non disponibile, fallback su pooler Supabase
```

Significato:
- non è un errore bloccante se la run prosegue
- la connessione diretta non era disponibile, ma il fallback ha funzionato

### Nessuna riga nuova in `bando_storico`

Possibili cause normali:
- i bandi erano invariati
- la run era solo uno smoke test su record già sincronizzati

### Warning fetch dettaglio pagina (SSL/timeout/rete)

Messaggio tipico:

```text
WARNING app.ocr.page_detail_fetcher Fetch pagina ... fallito: ...
```

Significato:
- non è un errore bloccante
- il bando viene comunque processato con fallback
- il caso viene contato in `page_fetch.failed` (non in `errori_fonti`)

### Errori subito in avvio

Controlla nell'ordine:
1. file `.env` presente
2. `DATABASE_URL` valida
3. credenziali Supabase corrette
4. ambiente virtuale attivo o uso esplicito di `.\.venv\Scripts\python.exe`
5. `SOURCE_ROOT_URL` raggiungibile

## Entry point disponibili

Discovery fonti:

```powershell
.\.venv\Scripts\python.exe -m app.scrapers.run_fonte_discovery
```

Scan bandi — run completa:

```powershell
.\.venv\Scripts\python.exe -m app.cli run
```

Scan bandi — limitata:

```powershell
.\.venv\Scripts\python.exe -m app.cli run --limit 3
```

Scan bandi — singola fonte:

```powershell
.\.venv\Scripts\python.exe -m app.cli run-fonte --fonte-id <ID>
```

Run coda pending (retry scaduti):

```powershell
.\.venv\Scripts\python.exe -m app.cli run-pending
```

Scheduler (bloccante, cron configurabile):

```powershell
# Default: run completa alle 02:00, pending ogni 4 ore
.\.venv\Scripts\python.exe -m app.scheduler start

# Personalizzato
.\.venv\Scripts\python.exe -m app.scheduler start --cron-full "0 3 * * *" --cron-pending "0 */2 * * *"

# Esegue subito un ciclo e termina (utile per test/cron esterni)
.\.venv\Scripts\python.exe -m app.scheduler run-now
.\.venv\Scripts\python.exe -m app.scheduler run-pending-now
```

Enqueue AI:

```powershell
.\.venv\Scripts\python.exe -m app.ai.run_ai_enqueue --limit 100
```

Enqueue AI con log progressivo:

```powershell
.\.venv\Scripts\python.exe -m app.ai.run_ai_enqueue --limit 1000 --report-every 50
```

Worker AI:

```powershell
# Processa un singolo batch (default 100 job)
.\.venv\Scripts\python.exe -m app.ai.run_ai_worker

# Processa batch da 50 job fino a coda vuota
.\.venv\Scripts\python.exe -m app.ai.run_ai_worker --limit 50 --drain-all

# Con control su delay e reporting
.\.venv\Scripts\python.exe -m app.ai.run_ai_worker --limit 50 --drain-all --call-delay 0.5 --report-every 1
```