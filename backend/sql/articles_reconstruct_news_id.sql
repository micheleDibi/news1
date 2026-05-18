-- Recovery anti-race per la skill di reconstruct (sezione "Articoli da Generare").
-- Se il backend muore tra l'INSERT su `articles` e il commit di
-- `news.is_published = True`, l'articolo c'e' su Supabase ma la news torna in
-- "Da Generare" → rigenerazione → duplicato.
-- Popolare `articles.reconstruct_news_id` durante l'INSERT permette al
-- pending-review endpoint di recuperare la bozza esistente e segnare la news
-- come pubblicata senza duplicati.

ALTER TABLE articles
  ADD COLUMN IF NOT EXISTS reconstruct_news_id integer;

CREATE INDEX IF NOT EXISTS idx_articles_reconstruct_news_id
  ON articles(reconstruct_news_id)
  WHERE reconstruct_news_id IS NOT NULL;
