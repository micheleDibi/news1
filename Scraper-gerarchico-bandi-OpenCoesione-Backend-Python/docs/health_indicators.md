# Manuale degli indicatori di salute — Scraper Bandi OpenCoesione

Questo documento descrive tutti gli indicatori per monitorare lo stato di salute dello scraper in ogni fase del suo ciclo di vita: esecuzione, qualità dati, pipeline AI e gestione errori.

---

## 1. Indicatori di esecuzione

Leggibili da `public.scraping_log`.

| Indicatore | Campo / Query | Stato sano | Stato critico |
|---|---|---|---|
| **Ultimo run completato** | `MAX(completed_at) WHERE tipo_operazione='scan_fonti_livello2' AND stato='completed'` | ≤ 25 ore fa | > 25 ore fa |
| **Durata run** | `tempo_esecuzione_ms` | < 30 min | > 60 min |
| **Fonti processate** | `pagine_crawlate` | ≥ numero fonti attive | 0 o molto inferiore al totale |
| **Errori fonti per run** | `response_summary→>'fonti_error'` | 0–2 | > 10% delle fonti |
| **Stato run** | `stato` | `completed` | `failed` o bloccato in `processing` |

**Query diagnostica rapida:**
```sql
SELECT
    tipo_operazione,
    stato,
    bandi_trovati,
    bandi_nuovi,
    bandi_aggiornati,
    bandi_invariati,
    tempo_esecuzione_ms,
    completed_at,
    response_summary
FROM public.scraping_log
WHERE tipo_operazione = 'scan_fonti_livello2'
ORDER BY started_at DESC
LIMIT 5;
```

---

## 2. Indicatori di copertura fonti

Leggibili da `public.fonte`.

| Indicatore | Query | Stato sano | Stato critico |
|---|---|---|---|
| **Fonti attive** | `COUNT(*) WHERE attivo = TRUE` | > 0 | 0 |
| **Fonti in processing bloccato** | `COUNT(*) WHERE stato_processing = 'processing' AND last_error_at < NOW() - INTERVAL '2h'` | 0 | > 0 |
| **Fonti in failed_final** | `COUNT(*) WHERE stato_processing = 'failed_final'` | 0 | > 5% del totale |
| **Fonti in pending** | `COUNT(*) WHERE stato_processing = 'pending'` | 0–5 | > 20% del totale |
| **Fonti non scansionate nelle ultime 48h** | join con `scraping_log` per `completed_at` | 0 | > 0 fonti attive senza run recente |

**Query diagnostica:**
```sql
SELECT
    stato_processing,
    COUNT(*) AS n,
    MIN(last_error_at) AS prima_errore,
    MAX(last_error_at) AS ultimo_errore
FROM public.fonte
GROUP BY stato_processing
ORDER BY n DESC;
```

---

## 3. Indicatori di qualità bandi

Leggibili da `public.bando`.

| Indicatore | Query | Stato sano | Stato critico |
|---|---|---|---|
| **Record totali** | `COUNT(*)` | cresce nel tempo | stazionario per > 7 giorni |
| **Bandi senza descrizione** | `COUNT(*) WHERE descrizione IS NULL OR LENGTH(descrizione) < 30` | < 20% | > 60% |
| **Bandi senza data scadenza** | `COUNT(*) WHERE data_scadenza IS NULL` | < 50% | > 80% |
| **Bandi senza importo** | `COUNT(*) WHERE importo_numerico IS NULL` | < 60% (dati rari) | — |
| **Bandi senza classificazione** | `COUNT(*) WHERE tipologia_bando_id IS NULL AND programma_id IS NULL` | < 30% | > 70% |
| **Bandi in stato programmato** | `COUNT(*) WHERE stato_bando = 'programmato'` | variabile, ma < 80% | > 95% (segnale che stato non viene aggiornato) |
| **Duplicati hash** | `COUNT(*) - COUNT(DISTINCT hash_bando)` | 0 | > 0 |

**Query diagnostica:**
```sql
SELECT
    COUNT(*) AS totale,
    COUNT(*) FILTER (WHERE descrizione IS NULL OR LENGTH(descrizione) < 30) AS senza_descrizione,
    COUNT(*) FILTER (WHERE data_scadenza IS NULL) AS senza_scadenza,
    COUNT(*) FILTER (WHERE importo_numerico IS NULL) AS senza_importo,
    COUNT(*) FILTER (WHERE tipologia_bando_id IS NULL AND programma_id IS NULL) AS senza_classificazione,
    COUNT(*) FILTER (WHERE stato_bando = 'programmato') AS stato_programmato,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE descrizione IS NOT NULL AND LENGTH(descrizione) >= 30)
        / NULLIF(COUNT(*), 0), 1
    ) AS pct_con_descrizione
FROM public.bando;
```

---

## 4. Indicatori della pipeline QualityGate

Leggibili da `public.scraping_log.response_summary` (campo JSONB).

| Indicatore | Path JSONB | Stato sano | Stato critico |
|---|---|---|---|
| **% record con descrizione** | `quality→>'descrizione_rate'` | ≥ 40% | < 10% |
| **% record con missing_fields** | `quality→>'missing_rate'` | < 40% | > 70% |
| **% miglioramento post-AI** | `quality→>'ai_improvement_rate'` | > 30% | < 5% (AI non aiuta) |
| **% record scartati per bassa qualità** | `quality→>'discard_rate'` | < 5% | > 15% |

**Gate 1 — Estrazione:**

| Indicatore | Stato sano | Stato critico |
|---|---|---|
| `extraction_status = 'ok'` per run | > 90% candidati | < 70% |
| Warning `EMPTY_TEXT` | < 2% | > 10% |
| Warning `LOW_ALPHA_RATIO` | < 5% | > 20% |
| Warning `NOISE_PATTERN` | < 5% | > 15% |

**Gate 2 — Parsing pre-AI:**

| Indicatore | Stato sano | Stato critico |
|---|---|---|
| `ai_required = false` (classificazione completa) | > 60% | < 20% |
| `missing_fields` include `descrizione` | < 40% | > 70% |
| `missing_fields` include `data_scadenza` | < 50% | > 80% |
| `invalid_fields` non vuoto | < 5% | > 15% |

**Gate 3 — Post-AI:**

| Indicatore | Stato sano | Stato critico |
|---|---|---|
| `ai_applied_fields` non vuoto | > 50% dei job AI | < 10% (AI non produce output utile) |
| `ai_rejected_fields` non vuoto | < 20% | > 50% |
| `quality_delta` medio per run | ≥ 1 campo migliorato | 0 |

---

## 5. Indicatori della coda AI

Leggibili da `public.ai_job_queue`.

| Indicatore | Query | Stato sano | Stato critico |
|---|---|---|---|
| **Job in coda** | `COUNT(*) WHERE stato = 'queued'` | < 100 | > 500 (worker bloccato) |
| **Job in processing > 10 min** | `COUNT(*) WHERE stato = 'processing' AND created_at < NOW() - INTERVAL '10m'` | 0 | > 0 |
| **Job failed** | `COUNT(*) WHERE stato = 'failed'` | 0–5 | cresce > 10 per run |
| **Tempo medio completamento** | `AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) WHERE stato = 'completed'` | < 30s | > 120s |

**Query diagnostica:**
```sql
SELECT
    stato,
    COUNT(*) AS n,
    MIN(creato_il) AS piu_vecchio,
    MAX(creato_il) AS piu_recente
FROM public.ai_job_queue
GROUP BY stato
ORDER BY n DESC;
```

---

## 6. Indicatori di errori e retry

Leggibili da `public.scraping_errori_definitivi` e `public.bando` / `public.fonte`.

| Indicatore | Query | Stato sano | Stato critico |
|---|---|---|---|
| **Errori definitivi non risolti** | `COUNT(*) WHERE risolto = FALSE` | 0–5 | > 20 (o in crescita) |
| **Bandi in failed_final** | `COUNT(*) FROM bando WHERE stato_processing = 'failed_final'` | 0 | > 0 |
| **Tipo errore più frequente** | `GROUP BY errore_tipo ORDER BY COUNT(*) DESC` | — | verifica se sistemico |
| **Retry esauriti per fonte** | `COUNT(*) FROM fonte WHERE retry_count >= max_retry` | 0 | > 0 |

**Query diagnostica:**
```sql
SELECT
    entity_type,
    errore_tipo,
    COUNT(*) AS n,
    MAX(creato_il) AS ultimo_errore,
    SUM(CASE WHEN risolto THEN 1 ELSE 0 END) AS risolti
FROM public.scraping_errori_definitivi
GROUP BY entity_type, errore_tipo
ORDER BY n DESC
LIMIT 20;
```

---

## 7. Indicatori di storico e consistenza

Leggibili da `public.bando_storico`.

| Indicatore | Query | Stato sano | Stato critico |
|---|---|---|---|
| **Righe storico per run** | `COUNT(*) WHERE scraping_log_id = <id run>` | > 0 se ci sono aggiornamenti | 0 per run con `bandi_aggiornati > 0` |
| **Campi modificati più frequenti** | `jsonb_array_elements_text(campi_modificati)` aggregate | — | se `stato_bando` è sempre modificato → instabilità parser |
| **Bandi con storico incoerente** | bandi con `primo_scraping_at > ultimo_scraping_at` | 0 | > 0 |

---

## 8. Indicatori infrastrutturali

| Indicatore | Come verificare | Stato sano | Stato critico |
|---|---|---|---|
| **Connessione DB** | `test_db_connection` + test pooler | OK | timeout o SSL error |
| **Raggiungibilità SOURCE_ROOT_URL** | fetch HEAD su `SOURCE_ROOT_URL` | HTTP 200 | 4xx / 5xx / timeout |
| **Tesseract disponibile** | `tesseract --version` | versione ≥ 4.0 | non trovato |
| **Spazio disco** (se applicabile) | `df -h` sul server | > 1 GB libero | < 200 MB |
| **Dipendenze Python** | `pip check` | no conflitti | conflitti di versione |

---

## 9. Semaforo salute complessivo

Usare questo schema di sintesi per valutare rapidamente lo stato dello scraper.

| Colore | Condizione |
|---|---|
| 🟢 **Verde** | ultimo run completato, 0 errori definitivi, qualità bandi ≥ soglie, AI attiva |
| 🟡 **Giallo** | run completato con warning, ≤ 5 errori definitivi, qualità tra soglie warning e critiche |
| 🔴 **Rosso** | run fallito o > 25h fa, errori definitivi in crescita, qualità sotto soglie critiche, AI bloccata |

**Query semaforo (da eseguire manualmente o schedulare):**
```sql
WITH last_run AS (
    SELECT stato, completed_at, bandi_trovati, bandi_nuovi
    FROM public.scraping_log
    WHERE tipo_operazione = 'scan_fonti_livello2'
    ORDER BY started_at DESC
    LIMIT 1
),
quality AS (
    SELECT
        ROUND(100.0 * COUNT(*) FILTER (WHERE descrizione IS NOT NULL AND LENGTH(descrizione) >= 30) / NULLIF(COUNT(*), 0), 1) AS pct_descrizione,
        COUNT(*) FILTER (WHERE stato_processing = 'failed_final') AS bandi_failed,
        COUNT(*) - COUNT(DISTINCT hash_bando) AS duplicati
    FROM public.bando
),
errors AS (
    SELECT COUNT(*) FILTER (WHERE risolto = FALSE) AS errori_aperti
    FROM public.scraping_errori_definitivi
)
SELECT
    lr.stato AS ultimo_run_stato,
    lr.completed_at AS ultimo_run_at,
    lr.bandi_trovati,
    lr.bandi_nuovi,
    q.pct_descrizione,
    q.bandi_failed,
    q.duplicati,
    e.errori_aperti,
    CASE
        WHEN lr.stato = 'failed' OR lr.completed_at < NOW() - INTERVAL '25h' THEN 'ROSSO'
        WHEN e.errori_aperti > 5 OR q.pct_descrizione < 10 OR q.duplicati > 0 THEN 'GIALLO'
        ELSE 'VERDE'
    END AS semaforo
FROM last_run lr, quality q, errors e;
```

---

## 10. Frequenza consigliata di monitoraggio

| Indicatore | Frequenza |
|---|---|
| Completamento run e stato | dopo ogni run schedulato (quotidiano) |
| Errori definitivi e retry | giornaliero |
| Qualità bandi (descrizione, classificazione) | settimanale |
| Storico e consistenza | settimanale |
| Semaforo complessivo | dopo ogni run schedulato |
| Verifica infrastrutturale | mensile o dopo deploy |

---

## 11. Utilizzo pratico — runner CLI

Il report di salute è eseguibile direttamente da riga di comando tramite `app.scrapers.run_health_check`.

### Panoramica testuale (default)

```bash
python -m app.scrapers.run_health_check
```

Output con emoji semaforo per ogni indicatore:

```
🟢  SALUTE SCRAPER: VERDE
   Generato: 2026-04-22T10:00:00+00:00

  🟢 Esecuzione
       🟢 Stato ultimo run: completed
       🟢 Ore dall'ultimo run completato: 1.0ore
       ...
```

### Output JSON (per integrazioni e log)

```bash
python -m app.scrapers.run_health_check --format json
```

Restituisce un oggetto strutturato:

```json
{
  "generated_at": "2026-04-22T10:00:00+00:00",
  "semaforo": "VERDE",
  "sections": {
    "esecuzione": {
      "semaforo": "VERDE",
      "indicators": [ ... ],
      "raw": { ... }
    },
    ...
  }
}
```

### Solo una sezione

```bash
python -m app.scrapers.run_health_check --section bandi
python -m app.scrapers.run_health_check --section ai_queue
python -m app.scrapers.run_health_check --section errori
```

Sezioni disponibili: `esecuzione`, `fonti`, `bandi`, `ai_queue`, `errori`, `storico`.

### Exit code per alert automatici

```bash
python -m app.scrapers.run_health_check --fail-on-red
echo $LASTEXITCODE   # 0 = ok/giallo, 1 = rosso
```

Utile in script di monitoraggio o pipeline CI/CD: esce con codice `1` se il semaforo complessivo è **ROSSO**.

### Combinazioni utili

```bash
# JSON solo sezione errori, per parsing automatico
python -m app.scrapers.run_health_check --section errori --format json

# Controllo post-run in script bash (exit 1 se critico)
python -m app.scrapers.run_health_check --fail-on-red

# Riepilogo completo in testo
python -m app.scrapers.run_health_check --format text
```

### Soglie di allerta (configurate in `health_service._Thresholds`)

| Parametro | Warning | Critico |
|---|---|---|
| Ore dall'ultimo run | > 25h | > 48h |
| Durata run | > 30 min | > 60 min |
| Fonti failed_final | ≥ 1 | ≥ 5 |
| Fonti bloccate in processing | — | ≥ 1 |
| % bandi con descrizione | < 30% | < 10% |
| % bandi classificati | < 50% | < 30% |
| Duplicati hash_bando | — | ≥ 1 |
| Job AI in coda | > 100 | > 500 |
| Job AI bloccati in processing | — | ≥ 1 |
| Tempo medio job AI | > 30s | > 120s |
| Errori definitivi non risolti | > 5 | > 20 |
| Bandi con date incoerenti | — | ≥ 1 |
