-- =============================================
-- Tabella: interpelli_link_giornalieri (NUOVA)
-- Contiene i link alle pagine giornaliere di scuolainterpelli.it
-- =============================================

CREATE TABLE IF NOT EXISTS interpelli_link_giornalieri (
    id BIGSERIAL PRIMARY KEY,
    link_name TEXT NOT NULL,
    link_date DATE,
    link_url TEXT NOT NULL UNIQUE,
    status TEXT DEFAULT 'pending',  -- pending | scraped | error
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================
-- Tabella: interpelli (GIA ESISTENTE)
-- Aggiunta colonne per pipeline automatizzata
-- =============================================

ALTER TABLE interpelli ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';
ALTER TABLE interpelli ADD COLUMN IF NOT EXISTS classe_concorso TEXT;
ALTER TABLE interpelli ADD COLUMN IF NOT EXISTS source_daily_link TEXT;
ALTER TABLE interpelli ADD COLUMN IF NOT EXISTS link_type TEXT DEFAULT 'single';
ALTER TABLE interpelli ADD COLUMN IF NOT EXISTS interpello_citta TEXT;
ALTER TABLE interpelli ADD COLUMN IF NOT EXISTS interpello_provincia TEXT;
ALTER TABLE interpelli ADD COLUMN IF NOT EXISTS interpello_regione TEXT;

-- Rimuovi colonna deprecata
ALTER TABLE interpelli DROP COLUMN IF EXISTS article_generated;
