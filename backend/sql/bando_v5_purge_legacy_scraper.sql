-- Pulizia legacy scraper subproject (v5).
--
-- Il subproject `Scraper-gerarchico-bandi-OpenCoesione-Backend-Python` e' stato
-- rimosso. Le sue tabelle scraper-internal non hanno piu' consumer:
--
--   - scraping_log               (log run scraper)
--   - scraping_errori_definitivi (errori non-retryable post-N tentativi)
--   - ai_job_queue               (worker AI Opus pre-skill, gia' deprecato v4)
--   - ocr_job_queue              (worker OCR per PDF allegati)
--   - bando_storico              (audit delta classifications)
--
-- Vengono droppate. Lo schema editorial (bando, fonte, catalogo) resta intatto.
-- Reversibile via pg_dump backup eseguito prima (vedi piano).
--
-- ⚠️ DESTRUCTIVE: Eseguire pg_dump backup PRIMA:
--   pg_dump $DATABASE_URL_BANDI \
--     -t scraping_log -t scraping_errori_definitivi \
--     -t ai_job_queue -t ocr_job_queue -t bando_storico \
--     -f /root/backups/bandi_legacy_dropped_$(date +%Y%m%d_%H%M).sql

BEGIN;

DROP TABLE IF EXISTS public.scraping_log CASCADE;
DROP TABLE IF EXISTS public.scraping_errori_definitivi CASCADE;
DROP TABLE IF EXISTS public.ai_job_queue CASCADE;
DROP TABLE IF EXISTS public.ocr_job_queue CASCADE;
DROP TABLE IF EXISTS public.bando_storico CASCADE;

COMMIT;

-- NOTE: Le colonne legacy in `bando` e `fonte` (stato_processing, retry_count,
-- max_retry, next_retry_at, last_error_*, ai_*, ocr_*) NON sono droppate qui.
-- Potrebbero servire al nuovo scraper. Decisione rimandata al prossimo plan.
