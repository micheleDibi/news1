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
-- Ordine importante: il constraint UNIQUE in PostgreSQL e' supportato
-- da un index, e PG non permette di droppare l'index se e' "behind" un
-- constraint. Quindi droppiamo PRIMA il constraint (che droppa anche
-- l'indice associato) e POI un eventuale indice residuo (solo se era
-- stato creato come index standalone nella v1 di questo file).
ALTER TABLE public.fonte DROP CONSTRAINT IF EXISTS fonte_link_unique;
DROP INDEX IF EXISTS public.fonte_link_unique;

ALTER TABLE public.fonte
  ADD CONSTRAINT fonte_link_unique UNIQUE (link);

-- CHECK constraint su `stato_processing`: ammette solo i 3 valori usati
-- dal nuovo scraper. Il vecchio constraint del subproject rimosso aveva
-- valori diversi (es. 'ready', 'pending', 'failed_final', ...) che ora
-- non vogliamo piu'.
ALTER TABLE public.fonte
  DROP CONSTRAINT IF EXISTS fonte_stato_processing_check;

ALTER TABLE public.fonte
  ADD CONSTRAINT fonte_stato_processing_check
  CHECK (stato_processing IN ('ready', 'connection error', 'deprecated'));

COMMIT;
