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

-- Indice UNIQUE partial (su righe con link non-NULL) per supportare
-- l'UPSERT idempotente del nuovo scraper. Idempotente.
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE schemaname = 'public'
      AND tablename = 'fonte'
      AND indexname = 'fonte_link_unique'
  ) THEN
    CREATE UNIQUE INDEX fonte_link_unique
      ON public.fonte(link)
      WHERE link IS NOT NULL;
  END IF;
END $$;

COMMIT;
