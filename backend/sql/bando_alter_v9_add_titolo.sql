-- ---------------------------------------------------------------------------
-- v9: aggiunge la colonna `titolo` alla tabella bando.
--
-- Contesto: la skill SEO (step v8) emette un titolo SEO (H1, ≤80 char, sentence
-- case) tra i 14 campi obbligatori dell'output. Lo schema attuale ha solo
-- `titolo_breve` (occhiello) e `titolo_raw` (dal scraper). Serve quindi la
-- colonna `titolo` per la versione editoriale del titolo.
--
-- IDEMPOTENTE: ADD COLUMN IF NOT EXISTS.
-- DEVE ESSERE APPLICATA PRIMA di `bando_reset_for_v9.sql`.
-- ---------------------------------------------------------------------------

BEGIN;

ALTER TABLE public.bando
  ADD COLUMN IF NOT EXISTS titolo TEXT;

COMMIT;
