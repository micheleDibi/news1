-- ============================================================================
-- bando_v11_01_pubblicazione_rollback.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Annulla `bando_v11_01_pubblicazione.sql`: toglie le colonne nuove, i
--   vincoli, gli indici e i tre trigger, e riporta il CHECK di
--   `stato_processing` ai 6 valori precedenti.
--
-- Fase: (b) — rientro.
--
-- Precondizioni (verificate dalle guardie qui sotto, che fanno fallire il
-- file con un messaggio leggibile invece di lasciarlo a metà)
--   * le migrazioni 02, 03, 04, 05, 06 e 07 NON devono essere applicate:
--     le loro FK, i loro trigger e la vista `bando_pubblico` citano le
--     colonne che questo file elimina. L'ordine di rientro è 07 → 06 → 05
--     → 04 → 03 → 02 → 01;
--   * nessuna riga con `stato_processing='archiviato'`: il CHECK a 6 valori
--     la rifiuterebbe.
--
-- Rompe BandoFit? NO se eseguito quando 05 non è applicata (BandoFit non ha
--   mai visto le colonne nuove). Rompe news1 se il frontend è già passato a
--   `PUBLIC_BANDI_FONTE_LETTURA=bando_pubblico`: riportarlo prima a `bando`.
--
-- COSA NON È REVERSIBILE
--   * `pubblicato_at` (= `created_at` approssimato) e `ultimo_cambiamento_at`
--     (= vecchio `updated_at` al momento della 01, poi avanzato dalle
--     modifiche pubbliche): sono dati che nascono qui e che il DROP COLUMN
--     butta via. Se la 01 è rimasta in produzione per più di qualche ora,
--     esportare prima `id, pubblicato, pubblicato_at, ultimo_cambiamento_at`;
--   * le revoche del punto 6 della 01 (cataloghi e RPC stale) NON vengono
--     annullate: erano buchi di scrittura, non effetti della serie v11. Il
--     ri-GRANT è scritto in fondo, commentato, per chi lo volesse davvero.
--   * `updated_at` non viene toccato né qui né nella 01: dopo il rientro le
--     righe hanno gli stessi valori di prima.
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'intero file.
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15min';

-- ---------------------------------------------------------------------------
-- 0. Guardie
-- ---------------------------------------------------------------------------

DO $$
DECLARE dipendenti text[] := ARRAY[]::text[];
BEGIN
  IF to_regclass('public.bando_pubblico') IS NOT NULL THEN
    dipendenti := dipendenti || 'vista bando_pubblico (migrazione 05)';
  END IF;
  IF to_regclass('public.bando_evento') IS NOT NULL THEN
    dipendenti := dipendenti || 'tabella bando_evento (migrazione 02)';
  END IF;
  IF to_regclass('public.bando_link') IS NOT NULL THEN
    dipendenti := dipendenti || 'tabella bando_link (migrazione 02)';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_trigger
              WHERE tgrelid = 'public.bando'::regclass
                AND tgname IN ('trg_bando_slug_congelato', 'trg_bando_provenienza_date',
                               'trg_bando_fonte_ufficiale_copia', 'trg_bando_stato_solo_via_evento')) THEN
    dipendenti := dipendenti || 'trigger delle migrazioni 03/04';
  END IF;

  IF array_length(dipendenti, 1) > 0 THEN
    RAISE EXCEPTION
      'esistono ancora oggetti che dipendono dalle colonne della 01: %. Annullare prima 07 → 06 → 05 → 04 → 03 → 02.',
      array_to_string(dipendenti, ', ');
  END IF;
END $$;

DO $$
DECLARE n bigint;
BEGIN
  SELECT count(*) INTO n FROM public.bando WHERE stato_processing::text = 'archiviato';
  IF n > 0 THEN
    RAISE EXCEPTION
      '% righe hanno stato_processing=''archiviato'': il CHECK a 6 valori le rifiuterebbe. Riportarle a ''rejected'' (o tenere il CHECK a 7 valori) prima del rientro.',
      n;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 1. Trigger
-- ---------------------------------------------------------------------------

DROP TRIGGER IF EXISTS trg_bando_cambiamento_pubblico      ON public.bando;
DROP TRIGGER IF EXISTS trg_bando_pubblicato_resta_completed ON public.bando;
DROP TRIGGER IF EXISTS trg_bando_pubblica_al_completamento  ON public.bando;

DROP FUNCTION IF EXISTS public.bando_cambiamento_pubblico();
DROP FUNCTION IF EXISTS public.bando_pubblicato_resta_completed();
DROP FUNCTION IF EXISTS public.bando_pubblica_al_completamento();

-- ---------------------------------------------------------------------------
-- 2. Indici e vincoli
-- ---------------------------------------------------------------------------

DROP INDEX IF EXISTS public.idx_bando_ricerca_gin;
DROP INDEX IF EXISTS public.idx_bando_pub_data_pubblicazione;
DROP INDEX IF EXISTS public.idx_bando_pub_data_scadenza;
DROP INDEX IF EXISTS public.idx_bando_pub_data_apertura;
DROP INDEX IF EXISTS public.idx_bando_pub_ultimo_cambiamento;
DROP INDEX IF EXISTS public.idx_bando_master_id;

ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_pubblicato_implica_completed;
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_master_diverso;
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_master_non_pubblicato;
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_ritirato_non_pubblicato;
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_fonte_ufficiale_stato_check;
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_fonte_ufficiale_tipo_check;

-- CHECK di `stato_processing` ai 6 valori di prima della v11. Il criterio è
-- `completed_duplicate` e non il nome della colonna: le righe qui sopra hanno
-- già tolto i vincoli nuovi che citano `stato_processing`, e un ILIKE su quel
-- nome colpirebbe il primo che venisse aggiunto in futuro.
DO $$
DECLARE c_name text;
BEGIN
  FOR c_name IN
    SELECT conname FROM pg_constraint
     WHERE conrelid = 'public.bando'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) ILIKE '%completed_duplicate%'
  LOOP
    EXECUTE format('ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS %I', c_name);
  END LOOP;
END $$;

ALTER TABLE public.bando
  ADD CONSTRAINT bando_stato_processing_check
  CHECK (stato_processing::text IN (
    'scraped', 'processed', 'rejected', 'enriched', 'completed', 'completed_duplicate'
  ));

-- ---------------------------------------------------------------------------
-- 3. Colonne (una sola riscrittura: il DROP della colonna generata la impone)
-- ---------------------------------------------------------------------------

ALTER TABLE public.bando
  DROP COLUMN IF EXISTS ricerca,
  DROP COLUMN IF EXISTS fonte_ufficiale_link_id,
  DROP COLUMN IF EXISTS fonte_ufficiale_verificata_at,
  DROP COLUMN IF EXISTS fonte_ufficiale_metodo,
  DROP COLUMN IF EXISTS fonte_ufficiale_confidenza,
  DROP COLUMN IF EXISTS fonte_ufficiale_stato,
  DROP COLUMN IF EXISTS fonte_ufficiale_tipo,
  DROP COLUMN IF EXISTS fonte_ufficiale_host,
  DROP COLUMN IF EXISTS fonte_ufficiale_url,
  DROP COLUMN IF EXISTS tentativi_seo,
  DROP COLUMN IF EXISTS rielaborazione,
  DROP COLUMN IF EXISTS chiave_esterna,
  DROP COLUMN IF EXISTS bando_master_id,
  DROP COLUMN IF EXISTS stato_bando_verificato,
  DROP COLUMN IF EXISTS stato_bando_evento_id,
  DROP COLUMN IF EXISTS data_scadenza_evento_id,
  DROP COLUMN IF EXISTS data_apertura_evento_id,
  DROP COLUMN IF EXISTS data_pubblicazione_evento_id,
  DROP COLUMN IF EXISTS data_scadenza_verificata,
  DROP COLUMN IF EXISTS data_apertura_verificata,
  DROP COLUMN IF EXISTS data_pubblicazione_verificata,
  DROP COLUMN IF EXISTS ora_scadenza,
  DROP COLUMN IF EXISTS ora_apertura,
  DROP COLUMN IF EXISTS ultimo_cambiamento_at,
  DROP COLUMN IF EXISTS ritirato_at,
  DROP COLUMN IF EXISTS pubblicato_at,
  DROP COLUMN IF EXISTS pubblicato;

COMMIT;

-- ============================================================================
-- Verifica post-rollback
-- ============================================================================
--   SELECT count(*) FROM information_schema.columns
--    WHERE table_schema='public' AND table_name='bando'
--      AND column_name LIKE ANY (ARRAY['pubblicato%','ultimo_cambiamento%','fonte_ufficiale%','ricerca','ora_%','%_evento_id','bando_master_id','chiave_esterna','rielaborazione','tentativi_seo','ritirato_at','data_%_verificata']);
--   -- atteso: 0
--
--   SELECT count(*) FROM pg_trigger
--    WHERE tgrelid='public.bando'::regclass AND tgname LIKE 'trg_bando_%' AND NOT tgisinternal;
--   -- atteso: 1 (resta solo trg_bando_set_updated_at)
--
--   SELECT count(*) FROM bando WHERE stato_processing='completed' AND slug IS NOT NULL;
--   -- atteso: invariato rispetto a prima della 01
-- ============================================================================

-- ============================================================================
-- NON annullato di proposito: le revoche del punto 6 della 01.
-- Il ri-GRANT, se davvero richiesto, è questo (rimette i buchi di scrittura):
--
--   ALTER TABLE public.categoria_programma DISABLE ROW LEVEL SECURITY;
--   ALTER TABLE public.tipologia_programma DISABLE ROW LEVEL SECURITY;
--   GRANT ALL ON TABLE public.categoria_programma TO anon, authenticated;
--   GRANT ALL ON TABLE public.tipologia_programma TO anon, authenticated;
--   -- e le 15 sequence di `public` che il punto 6.c revoca in blocco
--   -- (bando_id_seq compresa): `ALL` includeva UPDATE, cioè setval().
--   DO $$ DECLARE s text; BEGIN
--     FOR s IN SELECT format('%I.%I', n.nspname, c.relname)
--                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
--               WHERE c.relkind = 'S' AND n.nspname = 'public' LOOP
--       EXECUTE format('GRANT ALL ON SEQUENCE %s TO anon, authenticated', s);
--     END LOOP; END $$;
--   GRANT ALL ON FUNCTION public.get_scraping_stats(integer)        TO anon, authenticated;
--   GRANT ALL ON FUNCTION public.refresh_materialized_views()       TO anon, authenticated;
--   GRANT ALL ON FUNCTION public.generate_bando_hash(text, text)    TO anon, authenticated;
--   GRANT ALL ON FUNCTION public.set_current_timestamp_aggiornato_il() TO anon, authenticated;
--   GRANT ALL ON FUNCTION public.set_current_timestamp_updated_at()    TO anon, authenticated;
--   GRANT ALL ON FUNCTION public.update_updated_at_column()            TO anon, authenticated;
-- ============================================================================
