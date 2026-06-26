# Fase 2 Con P3 - Procedura Esecuzione

## Obiettivo
Re-eseguire pipeline completa (discovery → scan → enqueue → worker) con P3 implementato (fetch pagina di dettaglio + parsing enrichito).

## Prerequisiti
- Worker precedente fermato (Ctrl+C o finito)
- venv attivato
- DB connesso e accessible

## Comandi (eseguire in sequenza)

### Step 1: TRUNCATE tabelle del ciclo discovery→scan→enqueue→worker

**Via DBeaver/psql:**
```sql
BEGIN;

TRUNCATE TABLE
  public.bando_storico,
  public.bando_beneficiari,
  public.bando_settori,
  public.bando_codici_ateco,
  public.bando_regioni,
  public.ai_job_queue,
  public.scraping_errori_definitivi,
  public.scraping_log,
  public.bando
RESTART IDENTITY CASCADE;

COMMIT;
```

**Note:**
- `fonte` **non** truncare (tabella di setup, serve per discovery)
- `ocr_job_queue` **non** truncare (non usata in Fase 2, è per pipeline OCR)

**Tempo atteso:** < 1 secondo

---

### Step 2: Discovery Fonti

```powershell
.\.venv\Scripts\python.exe -m app.scrapers.run_fonte_discovery
```

**Output aspettato:**
- Inserite ~65 fonti
- Log: "Fonte X/65 completata..."

**Tempo atteso:** 2-3 minuti

---

### Step 3: Scan Bandi (con P3 - fetch pagina)

```powershell
.\.venv\Scripts\python.exe -m app.cli run
```

**Output aspettato:**
- Scansionate ~750 link candidati
- Inseriti ~750 bandi in `bando` table
- Log: "Fonte X/65..." con conteggi candidati/inseriti

**Tempo atteso:** 10-15 minuti (più lento di prima perché ogni bando fa fetch della pagina di dettaglio)

**⚠️ Nota:** Se vedi timeout o errori di rete su alcuni bandi è NORMALE — il fetcher ha timeout 10s e fallback graceful

---

### Step 4: Enqueue AI Jobs

```powershell
.\.venv\Scripts\python.exe -m app.ai.run_ai_enqueue --limit 1000
```

**Output aspettato:**
- Considerate ~750 righe `bando`
- Enqueuati ~700-750 job in `ai_job_queue`
- Log: `{"considered": 750, "enqueued": 747, ...}`

**Tempo atteso:** < 1 minuto

---

### Step 5: Worker Drain (con --call-delay per evitare rate limit)

```powershell
.\.venv\Scripts\python.exe -m app.ai.run_ai_worker --limit 50 --drain-all --call-delay 0.5
```

**Output aspettato:**
- Batch progress: `batch=1/15 claimed=50 completed=50 ...`
- ETA adattivo ogni 5 batch
- Final: `completed=747, queued=0`

**Tempo atteso:** 30-45 minuti (747 job × ~3-4s per job + 0.5s delay)

---

## Step 6: Verificare KPI Finali

Dopo worker termina, esegui le query di monitoraggio:

### Query 2: Stato Coda (deve essere tutto completed)
```sql
SELECT stato, COUNT(*) FROM public.ai_job_queue GROUP BY stato;
```
Aspettato: `completed=747, queued=0`

### Query 1: KPI Finali
```sql
SELECT
  COUNT(*) AS totale,
  ROUND(100.0 * COUNT(*) FILTER (WHERE titolo IS NOT NULL AND btrim(titolo) <> '') / NULLIF(COUNT(*),0), 2) AS pct_with_titolo,
  ROUND(100.0 * COUNT(*) FILTER (WHERE descrizione IS NOT NULL AND btrim(descrizione) <> '') / NULLIF(COUNT(*),0), 2) AS pct_with_descrizione,
  ROUND(100.0 * COUNT(*) FILTER (
    WHERE data_pubblicazione IS NOT NULL OR data_apertura IS NOT NULL OR data_scadenza IS NOT NULL
  ) / NULLIF(COUNT(*),0), 2) AS pct_with_any_date,
  ROUND(100.0 * COUNT(*) FILTER (WHERE importo_numerico IS NOT NULL AND importo_numerico > 1000) / NULLIF(COUNT(*),0), 2) AS pct_with_importo_plausibile,
  ROUND(100.0 * COUNT(*) FILTER (WHERE is_bando_confermato IS NULL) / NULLIF(COUNT(*),0), 2) AS pct_is_bando_null
FROM public.bando;
```

**Confronta con target:**
| KPI | Target | Status |
|-----|--------|--------|
| pct_with_titolo | >= 98% | ✅ se >= 98 |
| pct_with_descrizione | >= 85% | ✅ se >= 85 (prima era 25%) |
| pct_with_any_date | >= 75% | ✅ se >= 75 (prima era 4%) |
| pct_with_importo_plausibile | >= 60% | ✅ se >= 60 (prima era 22%) |
| pct_is_bando_null | <= 5% | ✅ se <= 5 (prima era 31%) |

---

## Timeline Totale

| Step | Tempo |
|------|-------|
| 1. TRUNCATE | < 1 min |
| 2. Discovery | 2-3 min |
| 3. Scan (con P3) | 10-15 min |
| 4. Enqueue | < 1 min |
| 5. Worker drain | 30-45 min |
| **TOTALE** | **~45-60 min** |

---

## Troubleshooting

### Se Scan è molto lento (> 20 min)
- Molti timeout su fetcher → URL non raggiungibili
- Normale, il fetcher skippa i fallimenti

### Se Worker si ferma con errori
- Aumentare `--call-delay 1.0` se vedi "Retrying" OpenAI
- Controllare log per errori specifici

### Se KPI non migliorano come aspettato
- Analizzare campione di bandi con `descrizione IS NULL`
- Verificare se `page_description` è stata estratta (`SELECT raw_data FROM bando LIMIT 1`)
- Potrebbe servire hardening aggiuntivo nel fetcher per alcuni siti

---

## Dopo Questa Run

**Se KPI migliori:**
- ✅ P3 funziona → documentare risultati
- ✅ Fase 2 completata
- ➡️ Prossimo: P2 (classificazione confermato) e P4 (PDF enrichment)

**Se KPI non migliori:**
- Investigare cause nei dati
- Possibili fix aggiuntivi al fetcher o parser
- Ripetere con miglioramenti

