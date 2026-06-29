-- ---------------------------------------------------------------------------
-- v8 skill cleanup: drop colonne legacy `attempts` e `date_quotes`.
--
-- Contesto:
--   - `attempts` (INTEGER NOT NULL DEFAULT 0): era il retry counter della
--     state machine v4 collapse. Il backend rotto (backend/app/bandi.py) lo
--     incrementava ad ogni errore skill. Nuovo stack v8 non lo usa.
--   - `date_quotes` (JSONB DEFAULT '{}'): era usato dal backend rotto per
--     persistere {pubblicazione,scadenza}: {value,source,quote}. Sostituito
--     da date_pubblicazione/data_scadenza nude (timestamp) gia' v7 enricher.
--     Il CHECK constraint `bando_date_quotes_length_check` (length <= 300)
--     dipende dalla colonna -> droppato prima della colonna.
--
-- Idempotente: IF EXISTS su tutto.
-- ---------------------------------------------------------------------------

BEGIN;

-- 1. Drop CHECK constraint che dipende da date_quotes
ALTER TABLE public.bando
  DROP CONSTRAINT IF EXISTS bando_date_quotes_length_check;

-- 2. Drop colonne legacy
ALTER TABLE public.bando
  DROP COLUMN IF EXISTS attempts,
  DROP COLUMN IF EXISTS date_quotes;

COMMIT;
