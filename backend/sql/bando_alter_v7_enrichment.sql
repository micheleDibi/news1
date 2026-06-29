-- v7: enrichment dei bandi (FK + junction).
--
-- Modifiche:
--   - DROP 5 colonne string sostituite da FK / junction:
--       programma, modalita_erogazione, beneficiari, codici_ateco, fondo
--   - DROP 6 colonne denormalized v4/v5 (programma_nome, ecc.)
--   - ALTER FK columns esistenti a NULLABLE (per coerenza con l'enricher)
--   - INDEX su (stato_processing, stato_bando) per il SELECT enricher
--
-- Le FK columns (tipologia_bando_id, modalita_erogazione_id, programma_id)
-- esistono gia' dalla v4 (collapse): vengono solo assicurate NULLABLE.
--
-- IMPORTANTE: backup prima di applicare.
--   pg_dump $DATABASE_URL_BANDI -t bando -f /tmp/bando_pre_v7.sql

BEGIN;

-- 1. Drop colonne string/array sostituite da FK e junction
ALTER TABLE public.bando
  DROP COLUMN IF EXISTS programma CASCADE,
  DROP COLUMN IF EXISTS modalita_erogazione CASCADE,
  DROP COLUMN IF EXISTS beneficiari CASCADE,
  DROP COLUMN IF EXISTS codici_ateco CASCADE,
  DROP COLUMN IF EXISTS fondo CASCADE;

-- 2. Drop colonne denormalized v4/v5 (sostituite da FK + junction tables)
ALTER TABLE public.bando
  DROP COLUMN IF EXISTS programma_nome CASCADE,
  DROP COLUMN IF EXISTS modalita_erogazione_nome CASCADE,
  DROP COLUMN IF EXISTS codici_ateco_norm CASCADE,
  DROP COLUMN IF EXISTS beneficiari_norm CASCADE,
  DROP COLUMN IF EXISTS tipologia CASCADE,
  DROP COLUMN IF EXISTS tipologia_normalizzata CASCADE;

-- 3. Assicura che le 3 FK columns esistano e siano nullable.
--    DO block perche' ALTER COLUMN ... DROP NOT NULL fallisce se la colonna
--    non esiste; le DDR potrebbero essere state droppate da v5/v6.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='bando'
               AND column_name='tipologia_bando_id') THEN
    ALTER TABLE public.bando ALTER COLUMN tipologia_bando_id DROP NOT NULL;
  ELSE
    ALTER TABLE public.bando ADD COLUMN tipologia_bando_id INTEGER;
  END IF;
END $$;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='bando'
               AND column_name='modalita_erogazione_id') THEN
    ALTER TABLE public.bando ALTER COLUMN modalita_erogazione_id DROP NOT NULL;
  ELSE
    ALTER TABLE public.bando ADD COLUMN modalita_erogazione_id INTEGER;
  END IF;
END $$;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='bando'
               AND column_name='programma_id') THEN
    ALTER TABLE public.bando ALTER COLUMN programma_id DROP NOT NULL;
  ELSE
    ALTER TABLE public.bando ADD COLUMN programma_id INTEGER;
  END IF;
END $$;

-- 4. Index utile per il SELECT del enricher
--    (WHERE stato_processing='processed' AND stato_bando IN (...) OR NULL).
CREATE INDEX IF NOT EXISTS bando_processing_stato_idx
  ON public.bando(stato_processing, stato_bando);

COMMIT;
