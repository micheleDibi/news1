-- ============================================================================
-- bando_v11_02_tabelle_di_servizio_rollback.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Annulla `bando_v11_02_tabelle_di_servizio.sql`: elimina le nove tabelle
--   nuove, la sequence del cursore, i trigger e le funzioni create lì,
--   `bando_stato_effettivo` compresa.
--
-- Fase: (b) — rientro.
--
-- Precondizioni
--   * la migrazione 03 deve essere già annullata: le sue FK
--     (`bando.fonte_ufficiale_link_id` → `bando_link`, `bando.*_evento_id` →
--     `bando_evento`) impedirebbero il DROP. Ordine di rientro:
--     07 → 06 → 05 → 04 → 03 → 02 → 01;
--   * la migrazione 05 deve essere già annullata: la vista `bando_pubblico`
--     legge `bando_controllo`, `bando_link` e `bando_host_aggregatore`;
--   * la migrazione 04 deve essere già annullata: le RPC scrivono su
--     `bando_evento` e `pipeline_lock`.
--   Le tre condizioni sono verificate dalle guardie qui sotto.
--
-- Rompe BandoFit? SÌ se BandoFit è già in fase (c), cioè se legge
--   `bando_evento`, `bando_link`, `bando_fusione` o `bando_slug_storico`:
--   quelle richieste diventerebbero PGRST205. Prima di eseguire questo file
--   in (c) serve la conferma scritta che BandoFit è tornato a leggere
--   soltanto `bando`.
--
-- COSA NON È REVERSIBILE
--   * gli eventi raccolti (`bando_evento`) e i cursori distribuiti ai
--     consumatori: un consumatore che ha salvato `ultimo_cursore = 5000`
--     non ritroverà mai quegli eventi, e dopo una nuova 02 la sequence
--     riparte da 1 → i cursori si riusano. Se la 02 è rimasta in produzione
--     e BandoFit ha già sincronizzato, esportare `bando_evento` PRIMA e
--     avvisare che la sincronizzazione va riavviata da 0;
--   * le fusioni (`bando_fusione`) e lo storico slug: i 301 di news1 e la
--     risoluzione dei miss di BandoFit smettono di funzionare. Le colonne
--     `bando.bando_master_id` restano valorizzate (sono della 01) ma senza
--     la mappa non c'è più lo slug originale;
--   * le impronte e il `testo_norm` di `bando_controllo`: senza «prima» il
--     monitor riparte in modalità G2' (primo controllo) su tutto il corpus.
--   Un DROP … CASCADE non è previsto di proposito: se qualcosa dipende
--   ancora da queste tabelle il file deve fallire, non trascinarselo dietro.
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'intero file.
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';

-- ---------------------------------------------------------------------------
-- 0. Guardie
-- ---------------------------------------------------------------------------

DO $$
DECLARE dipendenti text[] := ARRAY[]::text[];
BEGIN
  IF to_regclass('public.bando_pubblico') IS NOT NULL THEN
    dipendenti := dipendenti || 'vista bando_pubblico (05)';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_constraint
              WHERE conrelid = 'public.bando'::regclass AND contype = 'f'
                AND conname IN ('bando_fonte_ufficiale_link_fk',
                                'bando_data_pubblicazione_evento_fk',
                                'bando_data_apertura_evento_fk',
                                'bando_data_scadenza_evento_fk',
                                'bando_stato_bando_evento_fk')) THEN
    dipendenti := dipendenti || 'FK della migrazione 03';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
              WHERE n.nspname = 'public'
                AND p.proname IN ('bando_fondi', 'bando_separa', 'bando_registra_evento',
                                  'bando_applica_evento', 'lock_acquisisci', 'lock_rilascia')) THEN
    dipendenti := dipendenti || 'RPC della migrazione 04';
  END IF;

  IF array_length(dipendenti, 1) > 0 THEN
    RAISE EXCEPTION
      'esistono ancora oggetti che dipendono dalle tabelle della 02: %. Annullare prima 07 → 06 → 05 → 04 → 03.',
      array_to_string(dipendenti, ', ');
  END IF;
END $$;

-- La guardia di esistenza rende il file rieseguibile: senza, una seconda
-- esecuzione (o una prima dopo un DROP parziale) morirebbe con
-- «relation public.bando_evento does not exist» invece del messaggio chiaro
-- che tutti gli altri file di questa serie danno.
DO $$
DECLARE n bigint;
BEGIN
  IF to_regclass('public.bando_evento') IS NULL THEN
    RAISE NOTICE 'bando_evento non esiste già più: niente cursori da segnalare.';
    RETURN;
  END IF;

  SELECT count(*) INTO n FROM public.bando_evento WHERE cursore IS NOT NULL;
  IF n > 0 THEN
    RAISE NOTICE
      'ATTENZIONE: % eventi hanno già un cursore. Se un consumatore ha sincronizzato, la sua posizione diventa inutilizzabile: esportare bando_evento e avvisare prima del COMMIT.',
      n;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 1. Trigger su `bando` creati dalla 02
-- ---------------------------------------------------------------------------

DROP TRIGGER IF EXISTS trg_bando_promuovi_eventi ON public.bando;

-- Prima del DROP TABLE: il trigger che protegge la blocklist del seed
-- rifiuterebbe ogni DELETE su `dominio_ufficiale` (un DROP TABLE non lo
-- attiva, ma toglierlo esplicitamente rende il rollback leggibile e permette
-- di ripulire la tabella a mano prima del DROP).
DROP TRIGGER IF EXISTS trg_dominio_ufficiale_blocklist_protetta ON public.dominio_ufficiale;

-- ---------------------------------------------------------------------------
-- 2. Tabelle (ordine inverso delle dipendenze)
-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS public.bando_controllo;
DROP TABLE IF EXISTS public.bando_slug_storico;
DROP TABLE IF EXISTS public.bando_fusione;
DROP TABLE IF EXISTS public.bando_link;
DROP TABLE IF EXISTS public.bando_evento;
DROP SEQUENCE IF EXISTS public.bando_evento_cursore_seq;
DROP TABLE IF EXISTS public.pipeline_lock;
DROP TABLE IF EXISTS public.fonte_run;
DROP TABLE IF EXISTS public.pipeline_run;
DROP INDEX IF EXISTS public.dominio_ufficiale_blocklist_idx;
DROP INDEX IF EXISTS public.dominio_ufficiale_tipo_idx;
DROP TABLE IF EXISTS public.dominio_ufficiale;

-- ---------------------------------------------------------------------------
-- 3. Funzioni
-- ---------------------------------------------------------------------------
-- `dominio_di` e `bando_host_aggregatore` vengono eliminate qui anche se la
-- 05 le concede ad anon: la 05 va annullata prima (guardia al punto 0).

DROP FUNCTION IF EXISTS public.dominio_ufficiale_blocklist_protetta();
DROP FUNCTION IF EXISTS public.bando_promuovi_eventi();
DROP FUNCTION IF EXISTS public.bando_link_url_immutabile();
DROP FUNCTION IF EXISTS public.bando_link_dominio();
DROP FUNCTION IF EXISTS public.bando_evento_immutabile();
DROP FUNCTION IF EXISTS public.bando_evento_prova_non_aggregatore();
DROP FUNCTION IF EXISTS public.bando_evento_cursore_non_esterno();
DROP FUNCTION IF EXISTS public.bando_evento_cursore();
DROP FUNCTION IF EXISTS public.bando_evento_tipo_pubblico(text);
DROP FUNCTION IF EXISTS public.bando_host_aggregatore(text);
DROP FUNCTION IF EXISTS public.bando_normalizza_url(text);
DROP FUNCTION IF EXISTS public.dominio_di(text);
-- Creata dalla 02 (la 04 la chiama, e la 04 precede la 05): la 05 le toglie
-- soltanto il GRANT EXECUTE ad anon.
DROP FUNCTION IF EXISTS public.bando_stato_effettivo(text, date, boolean, time, date, time, timestamptz);

COMMIT;

-- ============================================================================
-- Verifica post-rollback
-- ============================================================================
--   SELECT count(*) FROM information_schema.tables
--    WHERE table_schema='public'
--      AND table_name IN ('dominio_ufficiale','pipeline_run','fonte_run','pipeline_lock',
--                         'bando_evento','bando_link','bando_fusione','bando_slug_storico',
--                         'bando_controllo');
--   -- atteso: 0
--
--   SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
--    WHERE n.nspname='public'
--      AND p.proname IN ('dominio_di','bando_normalizza_url','bando_host_aggregatore',
--                        'bando_evento_tipo_pubblico','bando_evento_cursore',
--                        'bando_evento_prova_non_aggregatore','bando_evento_immutabile',
--                        'bando_link_dominio','bando_link_url_immutabile','bando_promuovi_eventi',
--                        'bando_stato_effettivo');
--   -- atteso: 0
--
--   SELECT count(*) FROM bando WHERE stato_processing='completed' AND slug IS NOT NULL;
--   -- atteso: invariato
-- ============================================================================
