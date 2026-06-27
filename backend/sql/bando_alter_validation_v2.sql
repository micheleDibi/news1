-- Estende la tabella `bando` con i campi che permettono alla skill
-- `bandi-seo-enricher` (fase 2) di diventare la fonte autoritativa per:
--   - validita' del record ("e' davvero un bando?"): is_bando_confermato (gia' esistente)
--     viene ora sovrascritto dalla skill in `update_bando_from_payload`.
--   - scadenza autoritativa: la skill estrae `data_scadenza` da PDF/pagina ufficiale e
--     puo' sovrascriverla. `data_scadenza_source` traccia la provenienza.
--   - link candidatura verificato: `link_candidatura_verified` distingue link veri da
--     fallback ricavati dal source_url (che NON deve piu' essere usato come fallback).
--
-- Contesto: pre-skill v2, pagine indice (ricerca, categoria, archivio) finivano nel
-- listing con date residue catturate dallo scraper come fallback "ultima data trovata".
-- La fase 1 ora e' piu' conservativa; la fase 2 ha l'autorita' finale.
--
-- Idempotente: ADD COLUMN IF NOT EXISTS, DO blocks per i vincoli CHECK, CREATE INDEX IF NOT EXISTS.
-- Eseguire una tantum sul DB Supabase B (qggfoubllzeojxqlguef.supabase.co).

ALTER TABLE bando
  ADD COLUMN IF NOT EXISTS data_scadenza_source TEXT,
  ADD COLUMN IF NOT EXISTS validation_reason TEXT,
  ADD COLUMN IF NOT EXISTS rejection_category TEXT,
  ADD COLUMN IF NOT EXISTS link_candidatura_verified BOOLEAN DEFAULT FALSE;

-- Vincoli CHECK (idempotenti)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bando_data_scadenza_source_check') THEN
    ALTER TABLE bando ADD CONSTRAINT bando_data_scadenza_source_check
      CHECK (data_scadenza_source IS NULL OR data_scadenza_source IN
        ('official_pdf','official_page','inferred','missing','scraper_fallback'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bando_rejection_category_check') THEN
    ALTER TABLE bando ADD CONSTRAINT bando_rejection_category_check
      CHECK (rejection_category IS NULL OR rejection_category IN
        ('index_page','search_results','category_page','expired_archive','not_a_funding_call','unreachable'));
  END IF;
END $$;

-- Index composito per il filtro di visibilita' del frontend (RLS + query Astro).
CREATE INDEX IF NOT EXISTS idx_bando_visible
  ON bando(is_bando_confermato, skill_processing_status, slug)
  WHERE is_bando_confermato IS TRUE AND skill_processing_status = 'completed';

-- RLS: aggiorna la policy anon per filtrare anche i record che la skill ha bocciato
-- (is_bando_confermato = false). Il record resta in DB (no DELETE) per:
--   - evitare ri-scraping infinito (URL gia' visto);
--   - mantenere lo storico per audit;
--   - rispondere 404 invece di errori incoerenti su URL Google-indicizzati.
DROP POLICY IF EXISTS bando_public_read ON bando;
CREATE POLICY bando_public_read ON bando
  FOR SELECT
  TO anon
  USING (
    skill_processing_status = 'completed'
    AND slug IS NOT NULL
    AND is_bando_confermato IS TRUE
  );
