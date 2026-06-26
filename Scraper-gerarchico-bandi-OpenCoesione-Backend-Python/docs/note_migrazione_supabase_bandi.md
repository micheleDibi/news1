# Note operative sulla migrazione Supabase

## Cosa aggiunge
Questa migrazione aggiunge:

- tabella ponte `bando_beneficiari`
- campi retry/pending su `bando`
- campi retry/pending su `fonte`
- tabella `scraping_errori_definitivi`
- tabella `ai_job_queue`
- tabella `ocr_job_queue`
- trigger per aggiornare automaticamente i timestamp
- indici utili per query operative

Nota: nel database corrente il livello sorgente e' la tabella `fonte`; `categoria_programma` classifica la fonte ma non e' il livello sorgente operativo.

---

## Perché questa scelta
Ho separato:

- **stato_bando** → stato funzionale del bando (`aperto`, `chiuso`, `programmato`, ecc.)
- **stato_processing** → stato tecnico del backend (`ready`, `pending`, `processing`, `failed_final`)

Questa distinzione evita confusione tra logica applicativa e stato di scraping.

---

## Come usarla nel backend Python

### Retry fonte
Se fallisce una fonte:
- `fonte.stato_processing = 'pending'`
- incremento `retry_count`
- imposto `next_retry_at`
- se supera `max_retry` → `failed_final` + insert in `scraping_errori_definitivi`

### Retry bando
Se fallisce un singolo bando o documento:
- `bando.stato_processing = 'pending'`
- incremento retry
- pianifico nuovo tentativo
- dopo soglia massima → `failed_final` + insert in `scraping_errori_definitivi`

### AI asincrona
Se servono classificazioni:
- `bando.ai_processing_required = true`
- `bando.ai_processing_status = 'queued'`
- inserimento in `ai_job_queue`

### OCR asincrono
Se il PDF è scansionato:
- `bando.ocr_required = true`
- `bando.ocr_status = 'queued'`
- inserimento in `ocr_job_queue`

---

## Primo controllo da fare dopo la migrazione
Verifica in Supabase:

- presenza nuove colonne su `bando`
- presenza nuove colonne su `fonte`
- creazione tabelle:
  - `bando_beneficiari`
  - `scraping_errori_definitivi`
  - `ai_job_queue`
  - `ocr_job_queue`

---

## Vista v_bando_stato_flusso

La view `public.v_bando_stato_flusso` espone per ogni bando un campo calcolato `stato_flusso_completo` che riassume in quale fase del pipeline end-to-end si trova il record.

### Applicare la view (SQL Editor Supabase)

```sql
CREATE OR REPLACE VIEW public.v_bando_stato_flusso AS
SELECT
  b.id,
  b.fonte_id,
  b.titolo,
  b.link_bando,
  b.stato_bando,
  b.stato_processing,
  b.ai_processing_required,
  b.ai_processing_status,
  b.is_bando_confermato,
  b.ocr_required,
  b.ocr_status,
  b.primo_scraping_at,
  b.ultimo_scraping_at,
  b.ai_last_attempt_at,
  CASE
    WHEN b.stato_processing = 'failed_final'                          THEN 'scraping_failed'
    WHEN b.ai_processing_status = 'failed'                            THEN 'ai_failed'
    WHEN b.ai_processing_status IN ('queued', 'processing')           THEN 'ai_in_corso'
    WHEN b.ai_processing_required = TRUE
      AND b.ai_processing_status = 'not_required'                     THEN 'ai_da_avviare'
    WHEN b.stato_processing IN ('pending', 'processing')              THEN 'scraping_in_corso'
    WHEN b.stato_processing = 'ready'
      AND b.ai_processing_status IN ('completed', 'not_required')
      AND b.ai_processing_required = FALSE                            THEN 'completo'
    ELSE 'pronto'
  END AS stato_flusso_completo
FROM public.bando b;
```

### Valori possibili di stato_flusso_completo

| Valore | Significato |
|---|---|
| `completo` | Scraping OK + AI completata (o non richiesta) — flusso terminato con successo |
| `ai_in_corso` | Job AI presente in coda o attualmente in esecuzione |
| `ai_da_avviare` | Il bando richiede classificazione AI ma non è ancora stato messo in coda |
| `ai_failed` | L'AI worker ha terminato con errore |
| `scraping_in_corso` | Scraping ancora in stato `pending` o `processing` |
| `scraping_failed` | Scraping fallito definitivamente (`failed_final`) |
| `pronto` | Tutti i flag a zero, nessuna elaborazione specifica necessaria |

### Query di utilizzo

```sql
-- Distribuzione per stato (panoramica rapida)
SELECT stato_flusso_completo, COUNT(*) AS totale
FROM public.v_bando_stato_flusso
GROUP BY stato_flusso_completo
ORDER BY totale DESC;

-- Solo bandi che hanno completato l'intero flusso
SELECT *
FROM public.v_bando_stato_flusso
WHERE stato_flusso_completo = 'completo';

-- Bandi che richiedono intervento (AI fallita o da avviare)
SELECT id, titolo, stato_flusso_completo, ai_processing_status, ai_last_attempt_at
FROM public.v_bando_stato_flusso
WHERE stato_flusso_completo IN ('ai_failed', 'ai_da_avviare')
ORDER BY ultimo_scraping_at DESC;

-- Bandi bloccati in scraping
SELECT id, titolo, stato_processing, next_retry_at
FROM public.v_bando_stato_flusso
WHERE stato_flusso_completo IN ('scraping_in_corso', 'scraping_failed')
ORDER BY ultimo_scraping_at DESC;
```

---

## Passo successivo consigliato
Dopo questa migrazione, il passo più utile è creare:

1. `models.py` / ORM mapping
2. repository layer
3. servizio `upsert_bando`
4. queue processor retry
5. worker AI
6. worker OCR
