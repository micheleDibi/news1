-- ============================================================================
-- bando_v11_05_vista_pubblica_rollback.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Annulla `bando_v11_05_vista_pubblica.sql`: elimina la vista
--   `bando_pubblico` e i permessi di esecuzione concessi ad anon sulle tre
--   funzioni dell'allowlist, più il grant di colonna su `bando_controllo`.
--   Le tre funzioni NON vengono eliminate: appartengono tutte alla
--   migrazione 02 (`bando_stato_effettivo` compresa, perché la 04 la chiama)
--   e le elimina il rollback della 02.
--
-- Fase: (b) — rientro.
--
-- Precondizioni
--   * la migrazione 07 NON deve essere applicata: dopo la 07 la vista è
--     l'UNICO modo in cui anon legge i bandi (su `bando` restano solo i
--     grant di colonna), quindi eliminarla lascerebbe entrambi i
--     consumatori senza dati. Se la 07 è applicata, annullare prima quella.
--     Guardia esplicita qui sotto;
--   * news1 deve essere tornato a `PUBLIC_BANDI_FONTE_LETTURA=bando` e
--     BandoFit deve essere fuori dalla fase (c).
--
-- Rompe BandoFit? SÌ se BandoFit è in fase (c) (legge la vista): le sue
--   richieste diventerebbero PGRST205 → 502. In fase (b) no: nessuno la
--   legge ancora.
--
-- COSA NON È REVERSIBILE
--   Nulla: la vista non ha stato. L'unico effetto duraturo è che un
--   consumatore già passato alla vista va riportato a `bando`, e i due
--   predicati non sono identici (la vista esclude i doppioni fusi, il
--   predicato storico no). Dopo il rientro un id fuso torna visibile in
--   `bando` con `pubblicato=false`: è il comportamento di prima della v11.
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'intero file.
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
DECLARE policy_pubblicato boolean;
BEGIN
  -- Il testo esatto di `qual` dipende dal deparse di PostgreSQL: si
  -- riconosce la policy della fase (d) dal fatto che cita `pubblicato` e non
  -- cita più `stato_processing`.
  SELECT EXISTS (
    SELECT 1 FROM pg_policies
     WHERE schemaname = 'public' AND tablename = 'bando'
       AND policyname = 'bando_public_read'
       AND qual ILIKE '%pubblicato%'
       AND qual NOT ILIKE '%stato_processing%'
  ) INTO policy_pubblicato;

  IF policy_pubblicato THEN
    RAISE EXCEPTION
      'la policy di bando è già quella della fase (d): eliminare bando_pubblico lascerebbe i consumatori senza dati. Annullare prima bando_v11_07_fase_d_rollback.sql.';
  END IF;

  IF NOT has_table_privilege('anon', 'public.bando', 'SELECT') THEN
    RAISE EXCEPTION
      'anon non ha più SELECT su tutta la tabella bando (fase (d) applicata): annullare prima la 07.';
  END IF;
END $$;

DROP VIEW IF EXISTS public.bando_pubblico;

-- Le tre funzioni dell'allowlist restano tutte (sono della 02, e la 04 usa
-- `bando_stato_effettivo`): si toglie soltanto il permesso concesso qui.
REVOKE EXECUTE ON FUNCTION
  public.bando_stato_effettivo(text, date, boolean, time, date, time, timestamptz)
  FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.dominio_di(text) FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.bando_host_aggregatore(text) FROM anon, authenticated;

REVOKE SELECT (bando_id, ultimo_controllo_at) ON TABLE public.bando_controllo FROM anon;

COMMIT;

-- ============================================================================
-- Verifica post-rollback
-- ============================================================================
--   SELECT to_regclass('public.bando_pubblico');   -- atteso: NULL
--
--   SELECT p.oid::regprocedure FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
--    WHERE n.nspname='public' AND has_function_privilege('anon', p.oid, 'EXECUTE')
--      AND p.proname IN ('bando_stato_effettivo','dominio_di','bando_host_aggregatore');
--   -- atteso: 0 righe
--
--   SELECT count(*) FROM information_schema.column_privileges
--    WHERE table_schema='public' AND table_name='bando_controllo' AND grantee='anon';
--   -- atteso: 0
--
--   Blocco auto-contenuto: fuori da una transazione `SET LOCAL` dà solo un
--   WARNING e la query gira come proprietario, che scavalca la RLS.
--   BEGIN; SET LOCAL ROLE anon; SELECT count(*) FROM bando; ROLLBACK;
--   -- atteso: 2104 (il predicato storico è di nuovo l'unica porta)
-- ============================================================================
