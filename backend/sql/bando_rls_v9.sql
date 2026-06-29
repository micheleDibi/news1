-- ---------------------------------------------------------------------------
-- v9 RLS: policy public read aggiornata allo schema corrente.
--
-- La policy legacy filtrava su `state = 'confirmed'`, ma `state` e' stato
-- droppato nella migration v6 (sostituito da `stato_processing`). Risultato:
-- in produzione il frontend ottiene 0 bandi via anon key.
--
-- Nuova policy: bando_processing='completed' AND slug NOT NULL.
--
-- Inoltre: abilita read pubblico sulle 4 junction tables + 7 catalogo tables
-- (servono al frontend per fare i join nei dettagli del bando).
-- ---------------------------------------------------------------------------

BEGIN;

-- =========================================================================
-- 1. Tabella `bando` — policy public read aggiornata
-- =========================================================================

ALTER TABLE public.bando ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bando_public_read ON public.bando;
CREATE POLICY bando_public_read ON public.bando
  FOR SELECT
  TO anon
  USING (
    stato_processing = 'completed'
    AND slug IS NOT NULL
  );

-- =========================================================================
-- 2. Junction tables — read pubblico (anon legge per fare i join)
-- =========================================================================

ALTER TABLE public.bando_beneficiari ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS bando_beneficiari_public_read ON public.bando_beneficiari;
CREATE POLICY bando_beneficiari_public_read ON public.bando_beneficiari
  FOR SELECT TO anon USING (TRUE);

ALTER TABLE public.bando_codici_ateco ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS bando_codici_ateco_public_read ON public.bando_codici_ateco;
CREATE POLICY bando_codici_ateco_public_read ON public.bando_codici_ateco
  FOR SELECT TO anon USING (TRUE);

ALTER TABLE public.bando_regioni ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS bando_regioni_public_read ON public.bando_regioni;
CREATE POLICY bando_regioni_public_read ON public.bando_regioni
  FOR SELECT TO anon USING (TRUE);

ALTER TABLE public.bando_settori ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS bando_settori_public_read ON public.bando_settori;
CREATE POLICY bando_settori_public_read ON public.bando_settori
  FOR SELECT TO anon USING (TRUE);

-- =========================================================================
-- 3. Tabelle catalogo — read pubblico (servono per lookup nomi)
-- =========================================================================

ALTER TABLE public.tipologie_bando ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tipologie_bando_public_read ON public.tipologie_bando;
CREATE POLICY tipologie_bando_public_read ON public.tipologie_bando
  FOR SELECT TO anon USING (TRUE);

ALTER TABLE public.programmi ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS programmi_public_read ON public.programmi;
CREATE POLICY programmi_public_read ON public.programmi
  FOR SELECT TO anon USING (TRUE);

ALTER TABLE public.modalita_erogazione ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS modalita_erogazione_public_read ON public.modalita_erogazione;
CREATE POLICY modalita_erogazione_public_read ON public.modalita_erogazione
  FOR SELECT TO anon USING (TRUE);

ALTER TABLE public.beneficiari ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS beneficiari_public_read ON public.beneficiari;
CREATE POLICY beneficiari_public_read ON public.beneficiari
  FOR SELECT TO anon USING (TRUE);

ALTER TABLE public.codici_ateco ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS codici_ateco_public_read ON public.codici_ateco;
CREATE POLICY codici_ateco_public_read ON public.codici_ateco
  FOR SELECT TO anon USING (TRUE);

ALTER TABLE public.regioni ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS regioni_public_read ON public.regioni;
CREATE POLICY regioni_public_read ON public.regioni
  FOR SELECT TO anon USING (TRUE);

ALTER TABLE public.settori ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS settori_public_read ON public.settori;
CREATE POLICY settori_public_read ON public.settori
  FOR SELECT TO anon USING (TRUE);

COMMIT;

-- =========================================================================
-- Verifica post-deploy:
--   SELECT count(*) FROM bando WHERE stato_processing='completed' AND slug IS NOT NULL;
--   -- atteso: ~450
--
-- Test anon access via Supabase dashboard (Authentication -> Policies).
-- =========================================================================
