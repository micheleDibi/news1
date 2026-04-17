-- Correzione da eseguire SOLO se hai gia' applicato la prima versione di
-- `articles_alter_skill_fields.sql` (quella con 15 colonne + indice
-- idx_articles_source_news_id).
-- Rimuove le 3 colonne e l'indice che non sono piu' usati dal flusso
-- "Genera articolo" dopo la rivisitazione della mappatura:
--   - skill_source_url  -> sostituito da articles.source (gia' esistente)
--   - skill_h1          -> ridondante con title e skill_meta_title
--   - source_news_id    -> idempotenza ora via news.is_published + proposed_slug

DROP INDEX IF EXISTS idx_articles_source_news_id;

ALTER TABLE articles
  DROP COLUMN IF EXISTS skill_source_url,
  DROP COLUMN IF EXISTS skill_h1,
  DROP COLUMN IF EXISTS source_news_id;
