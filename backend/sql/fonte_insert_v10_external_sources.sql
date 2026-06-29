-- ---------------------------------------------------------------------------
-- v10: registra le 3 fonti esterne migrate dal repo ScrapingBandi.
-- Idempotente via ON CONFLICT (link).
--
-- Le strategie associate sono mappate in scraper_bandi/app/scraper_config.py.
-- ---------------------------------------------------------------------------

BEGIN;

INSERT INTO public.fonte (link, tipo_link, formato_link, stato_processing, attivo)
VALUES
  ('https://www.obiettivoeuropa.com/api/call/',
   'Opportunità',
   'JSON',
   'ready',
   TRUE),
  ('https://www.italiadomani.gov.it/content/sogei-ng/it/it/opportunita/bandi-amministrazioni-titolari/',
   'Opportunità',
   'HTML',
   'ready',
   TRUE),
  ('https://www.incentivi.gov.it/solr/coredrupal/select',
   'Opportunità',
   'JSON',
   'ready',
   TRUE)
ON CONFLICT (link) DO UPDATE
  SET stato_processing = EXCLUDED.stato_processing,
      attivo = EXCLUDED.attivo;

COMMIT;

-- Verifica:
--   SELECT id, link, tipo_link, formato_link, stato_processing, attivo
--   FROM fonte WHERE link IN (
--     'https://www.obiettivoeuropa.com/api/call/',
--     'https://www.italiadomani.gov.it/content/sogei-ng/it/it/opportunita/bandi-amministrazioni-titolari/',
--     'https://www.incentivi.gov.it/solr/coredrupal/select'
--   );
--   -- atteso: 3 righe con stato_processing='ready' e attivo=TRUE
