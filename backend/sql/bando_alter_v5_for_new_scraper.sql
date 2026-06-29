-- Step 2 nuovo scraper bandi: rinomina, drop e add colonne di `bando`.
--
-- Modifiche:
--   - RENAME titolo -> titolo_raw, descrizione -> descrizione_raw
--     (chiarisce che sono i valori grezzi dello scraper, NON quelli
--      della skill di enrichment)
--   - ADD tipo_link TEXT con CHECK ('Opportunita'/'Preavviso')
--     (duplicato da fonte.tipo_link per query rapide)
--   - DROP 12 colonne legacy del vecchio scraper (retry/OCR/scraping_at)
--   - UNIQUE su hash_bando (idempotente; serve per ON CONFLICT='hash_bando')
--   - INDEX su fonte_id
--
-- raw_data NON viene droppata: cambia scopo. Sara' NULL per bandi con link
-- e contenra' un JSONB con titolo + metadata per bandi senza link
-- (estratti da PDF/CSV calendari).
--
-- IMPORTANTE: backup prima di applicare:
--   pg_dump $DATABASE_URL_BANDI -t bando -f /tmp/bando_pre_v5_step2.sql

BEGIN;

-- 1. Rinomine (idempotenti via DO block: rinomina solo se la colonna sorgente
--    esiste E quella di destinazione no).
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='bando' AND column_name='titolo')
  AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema='public' AND table_name='bando' AND column_name='titolo_raw')
  THEN
    ALTER TABLE public.bando RENAME COLUMN titolo TO titolo_raw;
  END IF;
END $$;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='bando' AND column_name='descrizione')
  AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema='public' AND table_name='bando' AND column_name='descrizione_raw')
  THEN
    ALTER TABLE public.bando RENAME COLUMN descrizione TO descrizione_raw;
  END IF;
END $$;

-- 2. Aggiungi tipo_link + CHECK constraint
ALTER TABLE public.bando
  ADD COLUMN IF NOT EXISTS tipo_link TEXT;

ALTER TABLE public.bando
  DROP CONSTRAINT IF EXISTS bando_tipo_link_check;
ALTER TABLE public.bando
  ADD CONSTRAINT bando_tipo_link_check
  CHECK (tipo_link IS NULL OR tipo_link IN ('Opportunità', 'Preavviso'));

-- 3. Drop 12 colonne legacy (gestione retry + scraping_at + OCR)
ALTER TABLE public.bando
  DROP COLUMN IF EXISTS codice_bando,
  DROP COLUMN IF EXISTS primo_scraping_at,
  DROP COLUMN IF EXISTS ultimo_scraping_at,
  DROP COLUMN IF EXISTS retry_count,
  DROP COLUMN IF EXISTS max_retry,
  DROP COLUMN IF EXISTS next_retry_at,
  DROP COLUMN IF EXISTS last_error_type,
  DROP COLUMN IF EXISTS last_error_message,
  DROP COLUMN IF EXISTS last_error_at,
  DROP COLUMN IF EXISTS ocr_required,
  DROP COLUMN IF EXISTS ocr_status,
  DROP COLUMN IF EXISTS ocr_last_attempt_at;

-- 4. UNIQUE su hash_bando (necessario per ON CONFLICT='hash_bando').
--    Drop di eventuali constraint/index pre-esistenti (anche partial).
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_hash_unique;
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_hash_bando_key;
DROP INDEX IF EXISTS public.bando_hash_unique;
DROP INDEX IF EXISTS public.bando_hash_bando_key;

ALTER TABLE public.bando
  ADD CONSTRAINT bando_hash_unique UNIQUE (hash_bando);

-- 5. Index su fonte_id per query veloci (join, conteggi per fonte)
CREATE INDEX IF NOT EXISTS bando_fonte_id_idx ON public.bando(fonte_id);

-- 6. link_bando deve poter essere NULL (bandi estratti da PDF/CSV calendari
--    non hanno URL individuale, solo titolo + metadata in raw_data).
ALTER TABLE public.bando ALTER COLUMN link_bando DROP NOT NULL;

-- 7. titolo_raw nullable: in alcuni casi la riga PDF/CSV potrebbe avere
--    solo metadati e nessun titolo distinto (raro).
ALTER TABLE public.bando ALTER COLUMN titolo_raw DROP NOT NULL;

COMMIT;
