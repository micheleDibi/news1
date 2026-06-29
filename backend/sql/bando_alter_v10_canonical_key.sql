-- ---------------------------------------------------------------------------
-- v10: dedup cross-source via canonical_key + fonti_aggiuntive
--
-- Problema: il hash_bando attuale e' SHA256(fonte_id | link_bando) -> stesso
-- bando pubblicato da 2 fonti diverse risulta come 2 record duplicati.
--
-- Soluzione lightweight (no LLM, costo 0):
--   - colonna canonical_key TEXT UNIQUE = SHA256(norm_titolo|norm_ente|data_scad|importo)
--     calcolata DOPO la skill SEO (quando ente_erogatore + date + importo sono
--     popolati con qualita').
--   - colonna fonti_aggiuntive INTEGER[] = array di fonte_id che pubblicano lo
--     stesso bando. Quando si rileva un duplicato cross-source via UNIQUE,
--     il record vincitore raccoglie la fonte_id del duplicato nel suo array,
--     e il duplicato viene marcato stato_processing='completed_duplicate'.
--
-- Frontend (RLS): filtra solo stato_processing='completed' -> i duplicate sono
-- nascosti automaticamente.
-- ---------------------------------------------------------------------------

BEGIN;

-- 1. Aggiungi colonne (idempotente)
ALTER TABLE public.bando
  ADD COLUMN IF NOT EXISTS canonical_key TEXT,
  ADD COLUMN IF NOT EXISTS fonti_aggiuntive INTEGER[] DEFAULT '{}';

-- 2. UNIQUE index parziale: vincolo solo su record con canonical_key non NULL.
--    Permette ai bandi non ancora completed (canonical_key=NULL) di esistere
--    senza vincolo, ma garantisce univocita' tra i completed.
CREATE UNIQUE INDEX IF NOT EXISTS bando_canonical_key_unique
  ON public.bando(canonical_key)
  WHERE canonical_key IS NOT NULL;

-- 3. GIN index per query su fonti_aggiuntive (ARRAY containment)
CREATE INDEX IF NOT EXISTS idx_bando_fonti_aggiuntive_gin
  ON public.bando USING gin(fonti_aggiuntive);

-- 4. Estendi CHECK su stato_processing per ammettere 'completed_duplicate'.
--    Il valore segna i bandi-alias (duplicati cross-source mergiati nel master).
DO $$
DECLARE
  c_name text;
BEGIN
  FOR c_name IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'public.bando'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%stato_processing%'
  LOOP
    EXECUTE format('ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS %I', c_name);
  END LOOP;
END $$;

ALTER TABLE public.bando ADD CONSTRAINT bando_stato_processing_check
  CHECK (stato_processing IN (
    'scraped','processed','rejected','enriched','completed','completed_duplicate'
  ));

COMMIT;

-- Verifica post-deploy:
--   SELECT column_name FROM information_schema.columns
--   WHERE table_name='bando' AND column_name IN ('canonical_key','fonti_aggiuntive');
--   -- atteso: 2 righe
--
--   SELECT conname FROM pg_constraint
--   WHERE conrelid='public.bando'::regclass AND contype='c'
--     AND pg_get_constraintdef(oid) ILIKE '%stato_processing%';
--   -- atteso: 1 riga (bando_stato_processing_check)
