-- Estende la tabella `bando` del Supabase dello scraper (DB B) con i campi
-- prodotti dalla skill `bandi-seo-enricher` (livello flash_bando / guida_bando)
-- e con lo stato del processing della skill stessa.
--
-- Migration idempotente: usa ADD COLUMN IF NOT EXISTS e CREATE INDEX IF NOT EXISTS.
-- Eseguire una tantum sul DB del progetto Scraper-gerarchico-bandi-OpenCoesione-Backend-Python
-- (URL: https://qggfoubllzeojxqlguef.supabase.co).

ALTER TABLE bando
  ADD COLUMN IF NOT EXISTS slug VARCHAR(255),
  ADD COLUMN IF NOT EXISTS seo_livello VARCHAR(20),
  ADD COLUMN IF NOT EXISTS seo_titolo TEXT,
  ADD COLUMN IF NOT EXISTS seo_occhiello TEXT,
  ADD COLUMN IF NOT EXISTS seo_descrizione_breve TEXT,
  ADD COLUMN IF NOT EXISTS seo_meta_title TEXT,
  ADD COLUMN IF NOT EXISTS seo_meta_description TEXT,
  ADD COLUMN IF NOT EXISTS seo_contenuto JSONB,
  ADD COLUMN IF NOT EXISTS seo_factcheck JSONB,
  ADD COLUMN IF NOT EXISTS seo_fonti JSONB,
  ADD COLUMN IF NOT EXISTS seo_validation JSONB,
  ADD COLUMN IF NOT EXISTS ente_erogatore TEXT,
  ADD COLUMN IF NOT EXISTS tipologia_normalizzata VARCHAR(50),
  ADD COLUMN IF NOT EXISTS area_geografica TEXT,
  ADD COLUMN IF NOT EXISTS tematica TEXT[],
  ADD COLUMN IF NOT EXISTS beneficiari_norm TEXT[],
  ADD COLUMN IF NOT EXISTS scadenza_stato VARCHAR(20),
  ADD COLUMN IF NOT EXISTS importo_totale_eur BIGINT,
  ADD COLUMN IF NOT EXISTS importo_max_per_progetto_eur BIGINT,
  ADD COLUMN IF NOT EXISTS link_candidatura TEXT,
  ADD COLUMN IF NOT EXISTS riferimento_normativo TEXT,
  ADD COLUMN IF NOT EXISTS skill_processing_status VARCHAR(20) NOT NULL DEFAULT 'queued',
  ADD COLUMN IF NOT EXISTS skill_processing_at TIMESTAMP,
  ADD COLUMN IF NOT EXISTS skill_last_error TEXT,
  ADD COLUMN IF NOT EXISTS skill_attempts INTEGER NOT NULL DEFAULT 0;

-- Vincoli CHECK (idempotenti)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bando_seo_livello_check') THEN
    ALTER TABLE bando ADD CONSTRAINT bando_seo_livello_check
      CHECK (seo_livello IS NULL OR seo_livello IN ('flash_bando','guida_bando'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bando_tipologia_norm_check') THEN
    ALTER TABLE bando ADD CONSTRAINT bando_tipologia_norm_check
      CHECK (tipologia_normalizzata IS NULL OR tipologia_normalizzata IN
        ('FESR','FSE','Interreg','nazionale','regionale','misto','JTF'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bando_scadenza_stato_check') THEN
    ALTER TABLE bando ADD CONSTRAINT bando_scadenza_stato_check
      CHECK (scadenza_stato IS NULL OR scadenza_stato IN ('aperto','in_scadenza','scaduto'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bando_skill_status_check') THEN
    ALTER TABLE bando ADD CONSTRAINT bando_skill_status_check
      CHECK (skill_processing_status IN ('queued','processing','completed','failed','skipped'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bando_slug_unique') THEN
    ALTER TABLE bando ADD CONSTRAINT bando_slug_unique UNIQUE (slug);
  END IF;
END $$;

-- Indici per le query del frontend e del backfill
CREATE INDEX IF NOT EXISTS idx_bando_slug ON bando(slug);
CREATE INDEX IF NOT EXISTS idx_bando_skill_status ON bando(skill_processing_status);
CREATE INDEX IF NOT EXISTS idx_bando_scadenza_stato ON bando(scadenza_stato);
CREATE INDEX IF NOT EXISTS idx_bando_tipologia_norm ON bando(tipologia_normalizzata);
CREATE INDEX IF NOT EXISTS idx_bando_importo_totale ON bando(importo_totale_eur);
CREATE INDEX IF NOT EXISTS idx_bando_tematica_gin ON bando USING gin(tematica);
CREATE INDEX IF NOT EXISTS idx_bando_beneficiari_norm_gin ON bando USING gin(beneficiari_norm);

-- Indice composito per il batch loader della skill
-- (bandi che hanno completato la classificazione AI e attendono enrichment SEO)
CREATE INDEX IF NOT EXISTS idx_bando_skill_pending
  ON bando(skill_processing_status, ultimo_scraping_at DESC)
  WHERE skill_processing_status IN ('queued','failed');

-- RLS: anon legge solo i bandi pubblicabili (skill completata + slug presente)
ALTER TABLE bando ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bando_public_read ON bando;
CREATE POLICY bando_public_read ON bando
  FOR SELECT
  TO anon
  USING (skill_processing_status = 'completed' AND slug IS NOT NULL);

-- Lookup leggibili dall'anon per popolare i filtri del frontend
ALTER TABLE regioni ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS regioni_public_read ON regioni;
CREATE POLICY regioni_public_read ON regioni FOR SELECT TO anon USING (TRUE);

ALTER TABLE settori ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS settori_public_read ON settori;
CREATE POLICY settori_public_read ON settori FOR SELECT TO anon USING (TRUE);

ALTER TABLE beneficiari ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS beneficiari_public_read ON beneficiari;
CREATE POLICY beneficiari_public_read ON beneficiari FOR SELECT TO anon USING (TRUE);

ALTER TABLE codici_ateco ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS codici_ateco_public_read ON codici_ateco;
CREATE POLICY codici_ateco_public_read ON codici_ateco FOR SELECT TO anon USING (TRUE);

ALTER TABLE tipologie_bando ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tipologie_bando_public_read ON tipologie_bando;
CREATE POLICY tipologie_bando_public_read ON tipologie_bando FOR SELECT TO anon USING (TRUE);

ALTER TABLE bando_beneficiari ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS bando_beneficiari_public_read ON bando_beneficiari;
CREATE POLICY bando_beneficiari_public_read ON bando_beneficiari FOR SELECT TO anon USING (TRUE);

-- Nota: se esistono tabelle di join `bando_regioni`, `bando_settori`, `bando_codici_ateco`
-- nel dump dello scraper, abilitare RLS analoga. Verificare con \dt nel DB B.
