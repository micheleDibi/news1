-- Batch 2: traccia la provenienza di `data_pubblicazione` e prepara il nuovo
-- ordinamento default del listing `/bandi` (data di pubblicazione DESC NULLS LAST).
--
-- La skill estrae ora la data di pubblicazione del bando dalla fonte ufficiale
-- (NON la data in cui noi l'abbiamo scrapato) — pattern analogo a
-- `data_scadenza_source` aggiunto in `bando_alter_validation_v2.sql`.
-- L'orchestrator (`backend/app/bandi.py::update_bando_from_payload`) sovrascrive
-- `data_pubblicazione` SOLO se source ∈ {official_pdf, official_page}.
--
-- Idempotente. Eseguire una tantum sul DB Supabase B (qggfoubllzeojxqlguef.supabase.co).

ALTER TABLE bando
  ADD COLUMN IF NOT EXISTS data_pubblicazione_source TEXT;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bando_data_pubblicazione_source_check') THEN
    ALTER TABLE bando ADD CONSTRAINT bando_data_pubblicazione_source_check
      CHECK (data_pubblicazione_source IS NULL OR data_pubblicazione_source IN
        ('official_pdf','official_page','inferred','missing','scraper_fallback'));
  END IF;
END $$;

-- Index per il nuovo ordinamento default del listing `/bandi`:
--   ORDER BY data_pubblicazione DESC NULLS LAST
-- Lo scopo del WHERE parziale e' restringere l'indice ai soli record visibili al
-- frontend (gli stessi gia' filtrati da RLS e dalla query Astro).
CREATE INDEX IF NOT EXISTS idx_bando_data_pubblicazione_desc
  ON bando(data_pubblicazione DESC NULLS LAST)
  WHERE is_bando_confermato IS TRUE AND skill_processing_status = 'completed';
