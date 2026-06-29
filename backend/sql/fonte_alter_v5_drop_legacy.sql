-- v5: pulizia tabella `fonte` per il nuovo scraper.
--
-- Drop di 8 colonne legacy del vecchio scraper subproject (gestione retry,
-- error tracking + titolo ridondante con la classificazione
-- categoria_programma/tipologia_programma).
--
-- Colonne mantenute (post-drop):
--   id, categoria_programma_id, tipologia_programma_id, tipo_link, link,
--   formato_link, attivo, stato_processing, created_at, updated_at.
--
-- Inoltre crea un indice UNIQUE su `link` per garantire l'idempotenza
-- dell'UPSERT dello scraper (on_conflict='link').
--
-- IMPORTANTE: prima di applicare, esegui un backup:
--   pg_dump $DATABASE_URL_BANDI -t fonte -f /root/backups/fonte_pre_v5.sql

BEGIN;

ALTER TABLE public.fonte
  DROP COLUMN IF EXISTS titolo,
  DROP COLUMN IF EXISTS note_aggiuntive,
  DROP COLUMN IF EXISTS retry_count,
  DROP COLUMN IF EXISTS max_retry,
  DROP COLUMN IF EXISTS next_retry_at,
  DROP COLUMN IF EXISTS last_error_type,
  DROP COLUMN IF EXISTS last_error_message,
  DROP COLUMN IF EXISTS last_error_at;

-- UNIQUE constraint su `link` per supportare l'UPSERT idempotente del
-- nuovo scraper (ON CONFLICT='link' via supabase-py). Un proper constraint
-- (non un partial index) e' necessario perche' postgrest non passa il
-- predicate `WHERE link IS NOT NULL` nella sintassi ON CONFLICT.
--
-- Nota: in PostgreSQL standard UNIQUE constraint permette multipli NULL
-- (i NULL non sono considerati uguali), quindi non ci sono problemi con
-- righe esistenti che potrebbero avere link=NULL.
--
-- Drop di un eventuale partial index (versione precedente di questo file)
-- prima di aggiungere il constraint.
DROP INDEX IF EXISTS public.fonte_link_unique;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fonte_link_unique'
      AND conrelid = 'public.fonte'::regclass
  ) THEN
    ALTER TABLE public.fonte
      ADD CONSTRAINT fonte_link_unique UNIQUE (link);
  END IF;
END $$;

COMMIT;
