-- Pipeline Bandi v4 — Riorganizzazione: skill autoritativa totale + schema collapse.
--
-- Cambiamenti principali (vedi piano completo in /Users/.../.claude/plans/snug-toasting-minsky.md):
--
--   1. Una sola state machine `state` (enum bando_state) sostituisce 11 colonne di "validità"
--      sparpagliate (is_bando_confermato, rejection_category, validation_reason,
--      skill_processing_status, skill_attempts, skill_last_error, skill_verifier_*,
--      stato_processing, ai_processing_status, scadenza_stato, stato_bando).
--   2. `state_detail` JSONB raccoglie il "perche'" (rejection_category, verifier_verdict, ecc.).
--   3. Citation strict per le date: collassate in `date_quotes` JSONB
--      (sostituisce data_*_source + data_*_quote flat).
--   4. Editorial rinominata: seo_titolo→titolo, seo_descrizione_breve→descrizione_breve,
--      seo_occhiello→titolo_breve, seo_contenuto→contenuto, seo_livello→livello.
--      seo_meta_title / seo_meta_description / seo_factcheck / seo_fonti / seo_validation
--      droppate (i meta sono calcolati al render, factcheck/fonti erano campi morti).
--   5. Classification rinominata: tipologia_normalizzata→tipologia, programma_nome→programma,
--      modalita_erogazione_nome→modalita_erogazione, beneficiari_norm→beneficiari,
--      codici_ateco_norm→codici_ateco.
--   6. Importo string + importo_numerico droppati (autoritativi: importo_totale_eur,
--      importo_max_per_progetto_eur skill-side).
--   7. RLS semplificata: `state = 'confirmed' AND slug IS NOT NULL` (defense in depth
--      perche' lo `state` enum impedisce gia' valori non-confirmed alla skill).
--
-- ⚠️ DESTRUCTIVE: Drop di ~40 colonne. Eseguire pg_dump backup PRIMA:
--   pg_dump $DATABASE_URL_BANDI -t bando -f /root/backups/bando_pre_v4_$(date +%Y%m%d_%H%M).sql
--
-- Idempotente: ADD/UPDATE prima di DROP. Lo step 6 RESET state='discovered' su TUTTI
-- i record per drenare via sender col nuovo flow.

-- 1. Enum nuovo
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'bando_state') THEN
    CREATE TYPE bando_state AS ENUM
      ('discovered','enriching','confirmed','rejected','refuted','error','stale');
  END IF;
END $$;

-- 2. Aggiungi colonne nuove (idempotente)
ALTER TABLE bando
  ADD COLUMN IF NOT EXISTS state bando_state NOT NULL DEFAULT 'discovered',
  ADD COLUMN IF NOT EXISTS state_detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS state_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS livello TEXT,
  ADD COLUMN IF NOT EXISTS titolo_breve TEXT,
  ADD COLUMN IF NOT EXISTS descrizione_breve TEXT,
  ADD COLUMN IF NOT EXISTS contenuto JSONB,
  ADD COLUMN IF NOT EXISTS date_quotes JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS tipologia TEXT,
  ADD COLUMN IF NOT EXISTS programma TEXT,
  ADD COLUMN IF NOT EXISTS modalita_erogazione TEXT,
  ADD COLUMN IF NOT EXISTS beneficiari TEXT[],
  ADD COLUMN IF NOT EXISTS codici_ateco TEXT[],
  ADD COLUMN IF NOT EXISTS link_candidatura_source TEXT;

-- 3. Backfill loss-less dai vecchi nomi ai nuovi (solo se le colonne legacy esistono).
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bando' AND column_name='seo_titolo') THEN
    UPDATE bando SET titolo = COALESCE(seo_titolo, titolo) WHERE seo_titolo IS NOT NULL;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bando' AND column_name='seo_livello') THEN
    UPDATE bando SET livello = seo_livello WHERE livello IS NULL;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bando' AND column_name='seo_occhiello') THEN
    UPDATE bando SET titolo_breve = seo_occhiello WHERE titolo_breve IS NULL;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bando' AND column_name='seo_descrizione_breve') THEN
    UPDATE bando SET descrizione_breve = seo_descrizione_breve WHERE descrizione_breve IS NULL;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bando' AND column_name='seo_contenuto') THEN
    UPDATE bando SET contenuto = seo_contenuto WHERE contenuto IS NULL;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bando' AND column_name='tipologia_normalizzata') THEN
    UPDATE bando SET tipologia = tipologia_normalizzata WHERE tipologia IS NULL;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bando' AND column_name='programma_nome') THEN
    UPDATE bando SET programma = programma_nome WHERE programma IS NULL;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bando' AND column_name='modalita_erogazione_nome') THEN
    UPDATE bando SET modalita_erogazione = modalita_erogazione_nome WHERE modalita_erogazione IS NULL;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bando' AND column_name='beneficiari_norm') THEN
    UPDATE bando SET beneficiari = beneficiari_norm WHERE beneficiari IS NULL;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bando' AND column_name='codici_ateco_norm') THEN
    UPDATE bando SET codici_ateco = codici_ateco_norm WHERE codici_ateco IS NULL;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bando' AND column_name='link_candidatura_verified') THEN
    UPDATE bando SET link_candidatura_source = CASE
      WHEN link_candidatura_verified IS TRUE THEN 'extracted'
      WHEN link_candidatura IS NOT NULL THEN 'fallback_source'
      ELSE 'missing'
    END WHERE link_candidatura_source IS NULL;
  END IF;
END $$;

-- 4. Backfill date_quotes JSONB dai 4 campi flat (sources + quotes).
-- Idempotente: solo se le colonne legacy esistono e date_quotes non e' gia' popolato.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bando' AND column_name='data_pubblicazione_source')
     AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bando' AND column_name='data_scadenza_source')
  THEN
    UPDATE bando SET date_quotes = jsonb_build_object(
      'pubblicazione', jsonb_build_object(
        'value', data_pubblicazione,
        'source', data_pubblicazione_source,
        'quote', COALESCE(
          (SELECT data_pubblicazione_quote FROM bando b2 WHERE b2.id = bando.id),
          NULL
        )
      ),
      'scadenza', jsonb_build_object(
        'value', data_scadenza,
        'source', data_scadenza_source,
        'quote', COALESCE(
          (SELECT data_scadenza_quote FROM bando b2 WHERE b2.id = bando.id),
          NULL
        )
      )
    ) WHERE date_quotes = '{}'::jsonb;
  END IF;
END $$;

-- 5. Backfill state machine da vecchi campi (defense in depth: anche se la colonna non esiste,
-- mantieni 'discovered' come default).
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bando' AND column_name='skill_verifier_verdict')
     AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bando' AND column_name='rejection_category')
     AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bando' AND column_name='is_bando_confermato')
     AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bando' AND column_name='skill_processing_status')
  THEN
    UPDATE bando SET
      state = CASE
        WHEN skill_verifier_verdict = 'refuted' THEN 'refuted'::bando_state
        WHEN rejection_category IS NOT NULL THEN 'rejected'::bando_state
        WHEN is_bando_confermato IS TRUE AND skill_processing_status = 'completed' THEN 'confirmed'::bando_state
        WHEN skill_processing_status = 'failed' THEN 'error'::bando_state
        ELSE 'discovered'::bando_state
      END,
      state_detail = jsonb_build_object(
        'rejection_category', rejection_category,
        'validation_reason', validation_reason,
        'verifier_verdict', skill_verifier_verdict,
        'verifier_notes', skill_verifier_notes,
        'refuted_fields', skill_verifier_refuted_fields,
        'last_error', skill_last_error,
        'last_error_at', skill_last_processed_at
      ),
      attempts = COALESCE(skill_attempts, 0);
  END IF;
END $$;

-- 6. RESET state='discovered' per drain via sender col nuovo flow.
-- Utente: "in-place, drenata dal sender". Tutti i record (compresi quelli
-- che erano gia' confirmed in v3) vengono re-elaborati per beneficiare:
--   - fase 1 di discovery puro (recupero falsi negativi);
--   - schema nuovo (titolo/descrizione_breve/contenuto puliti);
--   - state machine + verifier adversarial.
UPDATE bando SET
  state = 'discovered',
  attempts = 0,
  state_detail = '{}'::jsonb,
  state_updated_at = NOW();

-- 7. CHECK constraints (idempotenti).
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='bando_date_quotes_length_check') THEN
    ALTER TABLE bando ADD CONSTRAINT bando_date_quotes_length_check CHECK (
      (date_quotes->'pubblicazione'->>'quote' IS NULL
        OR length(date_quotes->'pubblicazione'->>'quote') <= 300)
      AND (date_quotes->'scadenza'->>'quote' IS NULL
        OR length(date_quotes->'scadenza'->>'quote') <= 300)
    );
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='bando_dates_consistency_check') THEN
    ALTER TABLE bando ADD CONSTRAINT bando_dates_consistency_check CHECK (
      data_pubblicazione IS NULL OR data_scadenza IS NULL OR data_pubblicazione <= data_scadenza
    );
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='bando_tipologia_check_v4') THEN
    ALTER TABLE bando ADD CONSTRAINT bando_tipologia_check_v4 CHECK (
      tipologia IS NULL OR tipologia IN ('FESR','FSE','Interreg','nazionale','regionale','misto','JTF')
    );
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='bando_link_candidatura_source_check') THEN
    ALTER TABLE bando ADD CONSTRAINT bando_link_candidatura_source_check CHECK (
      link_candidatura_source IS NULL OR link_candidatura_source IN ('extracted','fallback_source','missing')
    );
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='bando_livello_check_v4') THEN
    ALTER TABLE bando ADD CONSTRAINT bando_livello_check_v4 CHECK (
      livello IS NULL OR livello IN ('flash_bando','guida_bando')
    );
  END IF;
END $$;

-- 8. Index per query frontend e monitoring.
CREATE INDEX IF NOT EXISTS idx_bando_state ON bando(state);
CREATE INDEX IF NOT EXISTS idx_bando_state_confirmed_slug ON bando(slug) WHERE state = 'confirmed';
CREATE INDEX IF NOT EXISTS idx_bando_data_scadenza_v4 ON bando(data_scadenza) WHERE state = 'confirmed';
CREATE INDEX IF NOT EXISTS idx_bando_discovered ON bando(state_updated_at) WHERE state = 'discovered';

-- 9. RLS — semplice e diretta. Solo `state='confirmed'` arriva al frontend.
DROP POLICY IF EXISTS bando_public_read ON bando;
CREATE POLICY bando_public_read ON bando FOR SELECT TO anon
  USING (state = 'confirmed' AND slug IS NOT NULL);

-- 10. DROP colonne vecchie (DESTRUCTIVE — fare DOPO il pg_dump backup!).
-- Tutte le colonne sostituite o non piu' necessarie.
ALTER TABLE bando
  -- Validation/state collassate in state + state_detail
  DROP COLUMN IF EXISTS is_bando_confermato CASCADE,
  DROP COLUMN IF EXISTS rejection_category CASCADE,
  DROP COLUMN IF EXISTS validation_reason CASCADE,
  DROP COLUMN IF EXISTS skill_processing_status CASCADE,
  DROP COLUMN IF EXISTS skill_attempts CASCADE,
  DROP COLUMN IF EXISTS skill_last_error CASCADE,
  DROP COLUMN IF EXISTS skill_last_processed_at CASCADE,
  DROP COLUMN IF EXISTS skill_processing_at CASCADE,
  DROP COLUMN IF EXISTS skill_verifier_verdict CASCADE,
  DROP COLUMN IF EXISTS skill_verifier_notes CASCADE,
  DROP COLUMN IF EXISTS skill_verifier_refuted_fields CASCADE,
  DROP COLUMN IF EXISTS ai_processing_status CASCADE,
  DROP COLUMN IF EXISTS ai_processing_required CASCADE,
  DROP COLUMN IF EXISTS ai_last_attempt_at CASCADE,
  DROP COLUMN IF EXISTS stato_bando CASCADE,
  DROP COLUMN IF EXISTS scadenza_stato CASCADE,
  -- Date sources/quotes spostate in date_quotes JSONB
  DROP COLUMN IF EXISTS data_pubblicazione_source CASCADE,
  DROP COLUMN IF EXISTS data_scadenza_source CASCADE,
  DROP COLUMN IF EXISTS data_pubblicazione_quote CASCADE,
  DROP COLUMN IF EXISTS data_scadenza_quote CASCADE,
  -- Editorial duplicati (backfillati in titolo/titolo_breve/descrizione_breve/contenuto/livello)
  DROP COLUMN IF EXISTS seo_titolo CASCADE,
  DROP COLUMN IF EXISTS seo_descrizione_breve CASCADE,
  DROP COLUMN IF EXISTS seo_meta_title CASCADE,
  DROP COLUMN IF EXISTS seo_meta_description CASCADE,
  DROP COLUMN IF EXISTS seo_livello CASCADE,
  DROP COLUMN IF EXISTS seo_occhiello CASCADE,
  DROP COLUMN IF EXISTS seo_contenuto CASCADE,
  DROP COLUMN IF EXISTS seo_validation CASCADE,
  DROP COLUMN IF EXISTS seo_factcheck CASCADE,
  DROP COLUMN IF EXISTS seo_fonti CASCADE,
  -- Importi string raw scraper (autoritativo: importo_totale_eur, importo_max_per_progetto_eur)
  DROP COLUMN IF EXISTS importo CASCADE,
  DROP COLUMN IF EXISTS importo_numerico CASCADE,
  -- Classification duplicati (rinominati in tipologia/programma/modalita_erogazione/beneficiari/codici_ateco)
  DROP COLUMN IF EXISTS tipologia_normalizzata CASCADE,
  DROP COLUMN IF EXISTS programma_nome CASCADE,
  DROP COLUMN IF EXISTS modalita_erogazione_nome CASCADE,
  DROP COLUMN IF EXISTS beneficiari_norm CASCADE,
  DROP COLUMN IF EXISTS codici_ateco_norm CASCADE,
  -- Altri campi morti
  DROP COLUMN IF EXISTS riferimento_normativo CASCADE,
  DROP COLUMN IF EXISTS link_candidatura_verified CASCADE;

-- NOTA: NON droppate (rimangono per coesistenza scraper):
--   - titolo, descrizione (raw scraper; titolo gia' backfillato dalla skill via UPDATE)
--   - link_bando (URL del bando — rimasto col nome legacy)
--   - codice_bando, fondo (metadati scraper)
--   - data_pubblicazione, data_apertura, data_scadenza (sovrascritti dalla skill se source ∈ official_*)
--   - data_extra, raw_data (JSONB scraper-side)
--   - importo_totale_eur, importo_max_per_progetto_eur (skill autoritativi)
--   - ente_erogatore, area_geografica, tematica
--   - allegati JSONB
--   - link_candidatura (URL skill-emitted)
--   - tipologia_bando_id, modalita_erogazione_id, programma_id, regione_id (FK legacy — drop futuro)
--   - fonte_id, hash_bando, primo_scraping_at, ultimo_scraping_at
--   - stato_processing (scraper retry queue), retry_count, max_retry, next_retry_at, last_error_*
--
-- Tabelle catalogo (regioni, settori, beneficiari, codici_ateco, programma, modalita_erogazione,
-- tipologia_bando) restano come dizionari read-only per dropdown filtri frontend.
