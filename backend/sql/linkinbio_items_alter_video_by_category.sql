-- ---------------------------------------------------------------------------
-- v11: introduce il tipo `video_by_category` nella tabella `linkinbio_items`.
--
-- La colonna `type` in `linkinbio_items` è una TEXT libera. Il codice usa già
-- article/link/social/header/separator/breaking/category/video; ora aggiungiamo
-- 'video_by_category' che riusa `category_slug` + `article_count` + `title`.
--
-- Idempotente. Se in Supabase esiste già un CHECK constraint su `type` che NON
-- include 'video_by_category', questo script lo rimuove (le stringhe restano
-- libere, coerenti col codice front-end che è single source of truth).
-- ---------------------------------------------------------------------------

BEGIN;

DO $$
DECLARE
  c_name text;
BEGIN
  FOR c_name IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'public.linkinbio_items'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%type%'
  LOOP
    EXECUTE format('ALTER TABLE public.linkinbio_items DROP CONSTRAINT IF EXISTS %I', c_name);
  END LOOP;
END $$;

COMMIT;

-- Verifica:
--   SELECT DISTINCT type FROM public.linkinbio_items;
--   -- dopo aver aggiunto item dall'admin, deve comparire 'video_by_category'.
