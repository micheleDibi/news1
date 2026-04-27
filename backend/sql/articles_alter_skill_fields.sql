-- Estensione della tabella `articles` (Supabase) per ospitare l'output completo
-- della skill news-angle-rewriter quando si clicca "Genera articolo".
-- Tutti i campi sono NULLABLE per non rompere le righe esistenti.
-- Eseguire una sola volta dalla Supabase SQL Editor.

ALTER TABLE articles
  ADD COLUMN IF NOT EXISTS skill_generated_at      timestamptz,
  ADD COLUMN IF NOT EXISTS skill_livello           text,     -- flash | editoriale | evergreen
  ADD COLUMN IF NOT EXISTS skill_keyword           text,
  ADD COLUMN IF NOT EXISTS skill_meta_title        text,
  ADD COLUMN IF NOT EXISTS skill_meta_description  text,
  ADD COLUMN IF NOT EXISTS skill_angolo            text,
  ADD COLUMN IF NOT EXISTS skill_competitor_report jsonb,    -- [{fonte, angolo_usato, gap}]
  ADD COLUMN IF NOT EXISTS skill_factcheck_report  jsonb,    -- [{dato, stato, fonte_primaria}]
  ADD COLUMN IF NOT EXISTS skill_article_sections  jsonb,    -- array sezioni strutturate (paragraph/h2/h3/bullet_list/numbered_list)
  ADD COLUMN IF NOT EXISTS skill_fonti             jsonb,    -- [{dato, fonte_url}]
  ADD COLUMN IF NOT EXISTS skill_validation        jsonb,    -- {passed, warnings[], word_count, title_length, description_length, h1_length, keyword_count}
  ADD COLUMN IF NOT EXISTS skill_raw_payload       jsonb;    -- backup completo del JSON skill (future-proof)
