CREATE TABLE selezione_personale (
    id BIGSERIAL PRIMARY KEY,
    codice TEXT NOT NULL UNIQUE,
    titolo TEXT,
    descrizione TEXT,
    descrizione_breve TEXT,
    figura_ricercata TEXT,
    num_posti INTEGER,
    tipo_procedura TEXT,
    data_pubblicazione TIMESTAMPTZ,
    data_scadenza TIMESTAMPTZ,
    data_visibilita TIMESTAMPTZ,
    sedi TEXT[],
    categorie TEXT[],
    settori TEXT[],
    enti_riferimento TEXT[],
    salary_min NUMERIC,
    salary_max NUMERIC,
    link_reindirizzamento TEXT,
    calculated_status TEXT,
    status_label TEXT,
    allegato_media_id TEXT,
    -- Pipeline fields
    status TEXT DEFAULT 'pending',
    article_title TEXT,
    article_subtitle TEXT,
    article_content TEXT,
    article_keywords TEXT[],
    slug TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for slug lookups (detail page)
CREATE INDEX idx_selezione_personale_slug ON selezione_personale(slug);

-- Index for status filtering (pipeline + frontend)
CREATE INDEX idx_selezione_personale_status ON selezione_personale(status);

-- Index for date ordering
CREATE INDEX idx_selezione_personale_data_pub ON selezione_personale(data_pubblicazione DESC);

-- Enable RLS
ALTER TABLE selezione_personale ENABLE ROW LEVEL SECURITY;

-- Allow anonymous read access (for frontend)
CREATE POLICY "Allow anonymous read access" ON selezione_personale
    FOR SELECT USING (true);

-- Allow authenticated insert/update (for backend pipeline)
CREATE POLICY "Allow authenticated write access" ON selezione_personale
    FOR ALL USING (true) WITH CHECK (true);
