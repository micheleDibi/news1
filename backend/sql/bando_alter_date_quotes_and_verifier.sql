-- Pipeline Bandi v3 — Hardening anti-hallucination + verifier adversarial.
--
-- Aggiunge alla tabella `bando` i campi che la skill (Opus 4.7) deve emettere
-- come PROVA del dato + i campi che il verifier adversarial (Haiku 4.5) compila:
--
--   data_scadenza_quote          TEXT (max 300 char) — frammento letterale del
--                                  markdown/PDF sorgente che contiene la scadenza.
--   data_pubblicazione_quote     TEXT (max 300 char) — idem per la data di pubblicazione.
--   skill_verifier_verdict       TEXT — verdetto del verifier (verified|refuted|skipped).
--   skill_verifier_notes         TEXT — note in chiaro del verifier.
--   skill_verifier_refuted_fields TEXT[] — lista campi bocciati ("scadenza","is_valid_bando",...).
--
-- Aggiunge tre CHECK constraint:
--   bando_skill_verifier_verdict_check  — enum verdetto
--   bando_dates_consistency_check       — data_pubblicazione <= data_scadenza
--   bando_quote_length_check            — lunghezza quote <= 300 char
--
-- Aggiorna la policy RLS `bando_public_read` perche' nasconda anche i record
-- con `rejection_category` non-null (defense in depth) e i record che il verifier
-- ha bocciato come 'refuted'. NON nasconde 'verified'/'skipped' — il verifier
-- "skipped" significa errore transient API, non un giudizio negativo.
--
-- Idempotente: ADD COLUMN IF NOT EXISTS, DO blocks per i CHECK, DROP/CREATE policy.
-- Eseguire una tantum sul DB Supabase B (qggfoubllzeojxqlguef.supabase.co).

-- 1. Nuove colonne
ALTER TABLE bando
  ADD COLUMN IF NOT EXISTS data_scadenza_quote TEXT,
  ADD COLUMN IF NOT EXISTS data_pubblicazione_quote TEXT,
  ADD COLUMN IF NOT EXISTS skill_verifier_verdict TEXT,
  ADD COLUMN IF NOT EXISTS skill_verifier_notes TEXT,
  ADD COLUMN IF NOT EXISTS skill_verifier_refuted_fields TEXT[];

-- 2. CHECK enum verdict del verifier
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'bando_skill_verifier_verdict_check'
  ) THEN
    ALTER TABLE bando ADD CONSTRAINT bando_skill_verifier_verdict_check
      CHECK (skill_verifier_verdict IS NULL OR skill_verifier_verdict IN ('verified','refuted','skipped'));
  END IF;
END $$;

-- 3. Sanitizza i record esistenti con date INCOERENTI prima di aggiungere il CHECK.
-- Se data_pubblicazione > data_scadenza, almeno una delle due e' un'allucinazione
-- del passato: azzera entrambe + marca source='missing'. NON tocca rejection_category
-- ne' is_bando_confermato: lascia che la prossima rielaborazione skill+verifier
-- faccia il vero verdetto (col backfill SQL del deploy: skill_processing_status='queued').
UPDATE bando
   SET data_pubblicazione = NULL,
       data_pubblicazione_source = 'missing',
       data_scadenza = NULL,
       data_scadenza_source = 'missing'
 WHERE data_pubblicazione IS NOT NULL
   AND data_scadenza IS NOT NULL
   AND data_pubblicazione > data_scadenza;

-- 4. CHECK consistenza date (post-sanitizzazione)
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'bando_dates_consistency_check'
  ) THEN
    ALTER TABLE bando ADD CONSTRAINT bando_dates_consistency_check
      CHECK (data_pubblicazione IS NULL OR data_scadenza IS NULL OR data_pubblicazione <= data_scadenza);
  END IF;
END $$;

-- 5. CHECK lunghezza quote (consistente con QUOTE_MAX_LEN nel validator Python e nella skill).
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'bando_quote_length_check'
  ) THEN
    ALTER TABLE bando ADD CONSTRAINT bando_quote_length_check
      CHECK (
        (data_scadenza_quote IS NULL OR length(data_scadenza_quote) <= 300)
        AND (data_pubblicazione_quote IS NULL OR length(data_pubblicazione_quote) <= 300)
      );
  END IF;
END $$;

-- 6. RLS aggiornata — defense in depth.
-- Un record e' visibile al pubblico SOLO se:
--   - skill_processing_status='completed'
--   - slug presente (necessario per il dettaglio /bandi/<slug>)
--   - is_bando_confermato=true (verdetto skill autoritativo)
--   - rejection_category IS NULL (defense in depth: se la skill confonde i due,
--     nasconde comunque il record)
--   - verifier non ha esplicitamente bocciato (NULL/verified/skipped sono OK; refuted NO)
DROP POLICY IF EXISTS bando_public_read ON bando;
CREATE POLICY bando_public_read ON bando
  FOR SELECT
  TO anon
  USING (
    skill_processing_status = 'completed'
    AND slug IS NOT NULL
    AND is_bando_confermato IS TRUE
    AND rejection_category IS NULL
    AND (skill_verifier_verdict IS NULL OR skill_verifier_verdict <> 'refuted')
  );

-- 7. Index per audit query frequenti (verifier monitoring)
CREATE INDEX IF NOT EXISTS idx_bando_verifier_verdict
  ON bando(skill_verifier_verdict)
  WHERE skill_verifier_verdict IS NOT NULL;
