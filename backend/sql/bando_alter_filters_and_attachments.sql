-- Estende la tabella `bando` con:
-- 1. Colonna JSONB `allegati` per i link a documenti estratti dalla skill bandi-seo-enricher
-- 2. Colonne denormalizzate per i filtri avanzati del frontend (`codici_ateco_norm`,
--    `programma_nome`, `modalita_erogazione_nome`) cosi' da evitare embed PostgREST
--    complicati e riusare il pattern array-contains gia' valido per tematica/beneficiari_norm.
--
-- Idempotente: ADD COLUMN IF NOT EXISTS, CREATE INDEX IF NOT EXISTS.
-- Eseguire una tantum sul DB Supabase B (qggfoubllzeojxqlguef.supabase.co).

ALTER TABLE bando
  ADD COLUMN IF NOT EXISTS allegati JSONB,
  ADD COLUMN IF NOT EXISTS codici_ateco_norm TEXT[],
  ADD COLUMN IF NOT EXISTS programma_nome TEXT,
  ADD COLUMN IF NOT EXISTS modalita_erogazione_nome TEXT;

CREATE INDEX IF NOT EXISTS idx_bando_codici_ateco_norm_gin
  ON bando USING gin(codici_ateco_norm);
CREATE INDEX IF NOT EXISTS idx_bando_programma_nome
  ON bando(programma_nome);
CREATE INDEX IF NOT EXISTS idx_bando_modalita_erog
  ON bando(modalita_erogazione_nome);

-- Backfill istantaneo dei 3 campi denormalizzati per i bandi gia' arricchiti.
-- Sfrutta i lookup gia' popolati dallo scraper (programmi, modalita_erogazione,
-- bando_codici_ateco → codici_ateco). Nessuna ri-elaborazione skill richiesta.

UPDATE bando b
   SET programma_nome = p.nome
  FROM programmi p
 WHERE b.programma_id = p.id
   AND b.programma_nome IS NULL;

UPDATE bando b
   SET modalita_erogazione_nome = m.nome
  FROM modalita_erogazione m
 WHERE b.modalita_erogazione_id = m.id
   AND b.modalita_erogazione_nome IS NULL;

UPDATE bando b
   SET codici_ateco_norm = sub.codici
  FROM (
    SELECT bca.bando_id,
           array_agg(DISTINCT ca.codice || ' — ' || coalesce(ca.descrizione, '')) AS codici
      FROM bando_codici_ateco bca
      JOIN codici_ateco ca ON ca.id = bca.codice_ateco_id
     GROUP BY bca.bando_id
  ) sub
 WHERE b.id = sub.bando_id
   AND b.codici_ateco_norm IS NULL;

-- Nota: la colonna `allegati` resta NULL su tutti i bandi gia' arricchiti.
-- La skill estesa (bandi-seo-enricher) la popolera' solo sui bandi processati
-- DOPO il deploy. Per backfill opzionale futuro:
--   UPDATE bando SET skill_processing_status='queued', skill_attempts=0
--    WHERE allegati IS NULL AND skill_processing_status='completed';
