-- ---------------------------------------------------------------------------
-- v10: aggiunge colonna `discoverable` per proteggere le fonti manuali
--      dal mark_deprecated() del discover.
--
-- Problema: lo step `discover` (orchestrator.py) marca come 'deprecated' ogni
-- fonte CON link non presente nella pagina sorgente OpenCoesione. Le fonti
-- esterne migrate in v10 (Obiettivo Europa, Italia Domani, Incentivi Gov IT)
-- non sono in OpenCoesione e ad ogni ciclo vengono marcate deprecated.
--
-- Soluzione: colonna `discoverable BOOLEAN DEFAULT TRUE`. Le fonti v10 hanno
-- discoverable=FALSE e mark_deprecated() le ignora.
-- ---------------------------------------------------------------------------

BEGIN;

ALTER TABLE public.fonte
  ADD COLUMN IF NOT EXISTS discoverable BOOLEAN NOT NULL DEFAULT TRUE;

-- Le 3 fonti v10 NON sono in OpenCoesione → non scoperti automaticamente.
UPDATE public.fonte
   SET discoverable = FALSE,
       stato_processing = 'ready',
       attivo = TRUE
 WHERE link IN (
   'https://www.obiettivoeuropa.com/api/call/',
   'https://www.italiadomani.gov.it/content/sogei-ng/it/it/opportunita/bandi-amministrazioni-titolari/',
   'https://www.incentivi.gov.it/solr/coredrupal/select'
 );

COMMIT;

-- Verifica:
--   SELECT id, link, stato_processing, attivo, discoverable FROM fonte
--   WHERE link IN (
--     'https://www.obiettivoeuropa.com/api/call/',
--     'https://www.italiadomani.gov.it/content/sogei-ng/it/it/opportunita/bandi-amministrazioni-titolari/',
--     'https://www.incentivi.gov.it/solr/coredrupal/select'
--   );
--   -- atteso: 3 righe stato='ready', attivo=TRUE, discoverable=FALSE
