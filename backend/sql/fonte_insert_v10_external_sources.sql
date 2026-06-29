-- ---------------------------------------------------------------------------
-- v10: registra le 3 fonti esterne migrate dal repo ScrapingBandi.
-- Idempotente via ON CONFLICT (link).
--
-- Adattamenti schema esistente:
--   - categoria_programma_id NOT NULL: CTE con COALESCE su fallback id minimo.
--   - tipologia_programma_id NOT NULL: idem.
--   - formato_link CHECK constraint (HTML|PDF|CSV legacy): esteso con 'JSON'
--     per supportare le API REST/Solr che ritornano JSON.
--
-- Le strategie associate sono mappate in scraper_bandi/app/scraper_config.py.
-- ---------------------------------------------------------------------------

BEGIN;

-- 0. Estendi formato_link CHECK per ammettere 'JSON'.
--    Il constraint legacy ammette solo {HTML, PDF, CSV}; ora ci sono fonti
--    che ritornano JSON nativo (Obiettivo Europa, Incentivi Gov IT).
DO $$
DECLARE
  c_name text;
BEGIN
  FOR c_name IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'public.fonte'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%formato_link%'
  LOOP
    EXECUTE format('ALTER TABLE public.fonte DROP CONSTRAINT IF EXISTS %I', c_name);
  END LOOP;
END $$;

ALTER TABLE public.fonte ADD CONSTRAINT fonte_formato_link_check
  CHECK (formato_link IN ('HTML', 'PDF', 'CSV', 'JSON'));

-- 1. INSERT delle 3 fonti.
WITH
  cat_nazionale AS (
    SELECT COALESCE(
      (SELECT id FROM categoria_programma WHERE nome ILIKE '%nazionale%' ORDER BY id LIMIT 1),
      (SELECT id FROM categoria_programma WHERE nome ILIKE '%italia%' ORDER BY id LIMIT 1),
      (SELECT id FROM categoria_programma ORDER BY id LIMIT 1)
    ) AS id
  ),
  cat_europeo AS (
    SELECT COALESCE(
      (SELECT id FROM categoria_programma WHERE nome ILIKE '%europe%' ORDER BY id LIMIT 1),
      (SELECT id FROM categoria_programma WHERE nome ILIKE '%CTE%' ORDER BY id LIMIT 1),
      (SELECT id FROM categoria_programma WHERE nome ILIKE '%comunitar%' ORDER BY id LIMIT 1),
      (SELECT id FROM categoria_programma ORDER BY id LIMIT 1)
    ) AS id
  ),
  tip_default AS (
    SELECT COALESCE(
      (SELECT id FROM tipologia_programma WHERE nome ILIKE '%altro%' ORDER BY id LIMIT 1),
      (SELECT id FROM tipologia_programma WHERE nome ILIKE '%generic%' ORDER BY id LIMIT 1),
      (SELECT id FROM tipologia_programma ORDER BY id LIMIT 1)
    ) AS id
  ),
  tip_pnrr AS (
    SELECT COALESCE(
      (SELECT id FROM tipologia_programma WHERE nome ILIKE '%pnrr%' ORDER BY id LIMIT 1),
      (SELECT id FROM tip_default)
    ) AS id
  )

INSERT INTO public.fonte (
  link, tipo_link, formato_link, stato_processing, attivo,
  categoria_programma_id, tipologia_programma_id
)
SELECT
  v.link,
  v.tipo_link::text,
  v.formato_link::text,
  v.stato_processing::text,
  v.attivo,
  v.categoria_id,
  v.tipologia_id
FROM (
  VALUES
    -- Obiettivo Europa: aggregatore europeo + nazionale (API JSON)
    (
      'https://www.obiettivoeuropa.com/api/call/',
      'Opportunità',
      'JSON',
      'ready',
      TRUE,
      (SELECT id FROM cat_europeo),
      (SELECT id FROM tip_default)
    ),
    -- Italia Domani: nazionale, PNRR (HTML server-side)
    (
      'https://www.italiadomani.gov.it/content/sogei-ng/it/it/opportunita/bandi-amministrazioni-titolari/',
      'Opportunità',
      'HTML',
      'ready',
      TRUE,
      (SELECT id FROM cat_nazionale),
      (SELECT id FROM tip_pnrr)
    ),
    -- Incentivi Gov IT: portale governo nazionale (Solr JSON)
    (
      'https://www.incentivi.gov.it/solr/coredrupal/select',
      'Opportunità',
      'JSON',
      'ready',
      TRUE,
      (SELECT id FROM cat_nazionale),
      (SELECT id FROM tip_default)
    )
) AS v(link, tipo_link, formato_link, stato_processing, attivo, categoria_id, tipologia_id)
ON CONFLICT (link) DO UPDATE
  SET stato_processing = EXCLUDED.stato_processing,
      attivo = EXCLUDED.attivo,
      formato_link = EXCLUDED.formato_link;

COMMIT;

-- Verifica:
--   SELECT f.id, f.link, f.formato_link, f.stato_processing, f.attivo,
--          cp.nome AS categoria, tp.nome AS tipologia
--   FROM fonte f
--   LEFT JOIN categoria_programma cp ON cp.id = f.categoria_programma_id
--   LEFT JOIN tipologia_programma tp ON tp.id = f.tipologia_programma_id
--   WHERE f.link IN (
--     'https://www.obiettivoeuropa.com/api/call/',
--     'https://www.italiadomani.gov.it/content/sogei-ng/it/it/opportunita/bandi-amministrazioni-titolari/',
--     'https://www.incentivi.gov.it/solr/coredrupal/select'
--   );
--   -- atteso: 3 righe con categoria + tipologia non-NULL e formato_link in {HTML, JSON}
