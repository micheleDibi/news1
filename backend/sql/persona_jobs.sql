-- Persistenza job generazione articoli (skill persona).
-- Sostituisce il dict in-memory `_persona_jobs` di backend/app/main.py:
-- senza persistenza, ogni restart del backend perdeva i job in volo e
-- generava 404 a ripetizione sul polling del frontend.

CREATE TABLE IF NOT EXISTS persona_jobs (
  job_id              uuid PRIMARY KEY,
  status              text NOT NULL CHECK (status IN ('pending','running','done','blocked','failed')),
  mode                text NOT NULL CHECK (mode IN ('create','edit')),
  creator             text,
  article_id          bigint,                -- edit mode: id articolo originale
  supabase_article_id bigint,                -- create mode: id bozza inserita
  slug                text,
  started_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  payload             jsonb,                 -- {article, skill_fields, base_fields}
  error               text,
  detail              text                   -- messaggio STEP 1.5 per "blocked"
);

CREATE INDEX IF NOT EXISTS idx_persona_jobs_updated_at
  ON persona_jobs(updated_at);

CREATE INDEX IF NOT EXISTS idx_persona_jobs_status_updated
  ON persona_jobs(status, updated_at);

-- Recovery race condition: se il backend crasha tra l'INSERT della bozza
-- (articles) e l'UPDATE del job (persona_jobs), il polling fa SELECT su
-- articles.persona_job_id per ritrovare la bozza ed evitare duplicati.
ALTER TABLE articles
  ADD COLUMN IF NOT EXISTS persona_job_id uuid;

CREATE INDEX IF NOT EXISTS idx_articles_persona_job_id
  ON articles(persona_job_id)
  WHERE persona_job_id IS NOT NULL;
