-- Step intermedio v6: pre-processing dei bandi.
--
-- Modifiche:
--   - DROP 4 colonne legacy v4 (state machine sostituita da stato_processing):
--       data_extra, state, state_detail, state_updated_at
--   - ADD stato_bando TEXT con CHECK ('chiuso','aperto','in apertura prossimamente')
--   - ADD confidence_score REAL con CHECK [0,1]
--   - ADD rejection_reason TEXT
--   - ALTER stato_processing DEFAULT 'scraped' (era 'ready')
--   - REPLACE CHECK constraint stato_processing con 5 nuovi valori:
--       'scraped' | 'processed' | 'rejected' | 'enriched' | 'completed'
--   - MIGRA i record esistenti: stato_processing='ready' -> 'scraped'
--
-- IMPORTANTE: backup prima di applicare.
--   pg_dump $DATABASE_URL_BANDI -t bando -f /tmp/bando_pre_v6.sql

BEGIN;

-- 1. Drop colonne legacy v4 (state machine sostituita da stato_processing).
ALTER TABLE public.bando
  DROP COLUMN IF EXISTS data_extra,
  DROP COLUMN IF EXISTS state,
  DROP COLUMN IF EXISTS state_detail,
  DROP COLUMN IF EXISTS state_updated_at;

-- 2. Drop ENUM bando_state se non piu' usato (best-effort, no-op se fallisce
--    perche' qualche altra colonna lo referenzia ancora).
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'bando_state') THEN
    BEGIN
      DROP TYPE bando_state;
    EXCEPTION WHEN OTHERS THEN
      NULL;
    END;
  END IF;
END $$;

-- 3. ADD stato_bando + CHECK
ALTER TABLE public.bando
  ADD COLUMN IF NOT EXISTS stato_bando TEXT;

ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_stato_bando_check;
ALTER TABLE public.bando
  ADD CONSTRAINT bando_stato_bando_check
  CHECK (stato_bando IS NULL OR stato_bando IN ('chiuso', 'aperto', 'in apertura prossimamente'));

-- 4. ADD confidence_score (0.0 - 1.0)
ALTER TABLE public.bando
  ADD COLUMN IF NOT EXISTS confidence_score REAL;

ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_confidence_score_check;
ALTER TABLE public.bando
  ADD CONSTRAINT bando_confidence_score_check
  CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1));

-- 5. ADD rejection_reason (motivo se LLM scarta il bando)
ALTER TABLE public.bando
  ADD COLUMN IF NOT EXISTS rejection_reason TEXT;

-- 6. stato_processing: default 'scraped', nuovi 5 valori ammessi.
ALTER TABLE public.bando ALTER COLUMN stato_processing SET DEFAULT 'scraped';

-- 7. Migra record esistenti PRIMA di mettere il CHECK constraint (altrimenti
--    fallisce su righe gia' 'ready').
UPDATE public.bando SET stato_processing = 'scraped' WHERE stato_processing = 'ready';

ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_stato_processing_check;
ALTER TABLE public.bando
  ADD CONSTRAINT bando_stato_processing_check
  CHECK (stato_processing IN ('scraped', 'processed', 'rejected', 'enriched', 'completed'));

-- 8. Indici utili per il pre-processor (SELECT WHERE stato_processing='scraped')
CREATE INDEX IF NOT EXISTS bando_stato_processing_idx ON public.bando(stato_processing);

COMMIT;
