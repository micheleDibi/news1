-- ============================================================================
-- bando_v11_04_transizioni_rollback.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Annulla `bando_v11_04_transizioni.sql`: toglie il trigger che protegge
--   `stato_bando`, elimina le RPC e la lista bianca `bando_transizione`,
--   cancella il job orario e RIMETTE il job storico `chiudi-bandi-scaduti`
--   con il testo letterale di `bando_auto_chiusura_scaduti.sql`.
--
-- Fase: (b) — rientro.
--
-- Precondizioni
--   * nessuna: le migrazioni 01, 02, 03 e 05 restano valide senza questo
--     file. La 05 non chiama nessuna funzione della 04 (la vista usa
--     `bando_stato_effettivo`, che sta nella 02).
--   * `pg_cron` abilitata (lo è, altrimenti la 04 non sarebbe passata).
--
-- Rompe BandoFit? NO. Nessun oggetto pubblico cambia forma. Cambia però la
--   latenza: si torna al job giornaliero delle 23:20 UTC, cioè fino a ~24 h
--   perché `stato_bando` insegua la scadenza (la vista `bando_pubblico`
--   continua a dire la verità in tempo reale, perché calcola
--   `stato_effettivo` alla lettura).
--
-- COSA NON È REVERSIBILE
--   * gli eventi già scritti restano: `bando_evento` è immutabile e nemmeno
--     service_role può cancellarlo. È voluto: i consumatori li hanno già
--     letti per cursore e un buco nella sequenza sarebbe peggio;
--   * gli stati già applicati restano applicati (un bando chiuso dal job
--     orario resta chiuso: era comunque la risposta giusta);
--   * `bando_fusione`, `bando_slug_storico` e i `bando_link` uniti da
--     `bando_fondi` restano: per disfare una fusione si usa `bando_separa`
--     PRIMA di eseguire questo file, altrimenti la RPC non c'è più;
--   * le righe di `pipeline_lock` restano: senza `lock_rilascia` si
--     cancellano a mano (`DELETE FROM pipeline_lock WHERE nome = '…'`) o
--     scadono da sole.
--
-- COSA TORNA PEGGIO (dichiarato)
--   Il job storico è quello del 06/07/2026 e ha tre limiti che la 04 aveva
--   risolto: (a) ignora `ora_scadenza`, quindi chiude solo per data;
--   (b) non promuove mai un «in apertura prossimamente» ad «aperto»;
--   (c) NON esclude `sospeso` e `revocato` — il suo WHERE guarda solo la
--   scadenza. Per questo il file si ferma se esistono righe in quei due
--   stati: rimetterlo in servizio le trasformerebbe in «chiuso» alla prima
--   esecuzione, senza lasciare traccia.
--
-- Come si applica
--   1. fermare gli step che scrivono eventi (`monitor`, `applica-eventi`);
--   2. se serve, disfare le fusioni con `bando_separa` finché esiste;
--   3. SQL Editor → incollare ed eseguire l'intero file.
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';

-- ---------------------------------------------------------------------------
-- 0. Guardia: il job storico non sa cosa siano `sospeso` e `revocato`
-- ---------------------------------------------------------------------------

DO $$
DECLARE n bigint;
BEGIN
  SELECT count(*) INTO n
    FROM public.bando
   WHERE stato_bando IN ('sospeso', 'revocato');

  IF n > 0 THEN
    RAISE EXCEPTION
      '% righe sono sospese o revocate: il job chiudi-bandi-scaduti, che questo file rimette in servizio, le chiuderebbe alla prima esecuzione (il suo WHERE guarda solo data_scadenza). Decidere prima cosa farne — è una scelta editoriale — oppure rischedulare a mano il job con «AND stato_bando IN (''aperto'',''in apertura prossimamente'')», come mostrato in fondo a questo file. Elenco: SELECT id, slug, stato_bando FROM bando WHERE stato_bando IN (''sospeso'',''revocato'');',
      n;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 1. Il trigger per primo: finché c'è, nessun UPDATE diretto passa e il job
--    storico fallirebbe
-- ---------------------------------------------------------------------------

DROP TRIGGER IF EXISTS trg_bando_stato_solo_via_evento ON public.bando;
DROP FUNCTION IF EXISTS public.bando_stato_solo_via_evento();

-- ---------------------------------------------------------------------------
-- 2. Le RPC e le due funzioni di supporto
-- ---------------------------------------------------------------------------
-- DROP dinamico: le firme sono lunghe (17 parametri su
-- `bando_registra_evento`) e un solo default scritto male lascerebbe in piedi
-- una funzione che il file dice di aver tolto. `pg_get_function_identity_arguments`
-- le ricava dal catalogo, sovraccarichi compresi.

DO $$
DECLARE f record;
BEGIN
  FOR f IN
    SELECT p.oid,
           format('%I.%I(%s)', n.nspname, p.proname,
                  pg_get_function_identity_arguments(p.oid)) AS firma
      FROM pg_proc p
      JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'public'
       AND p.proname IN (
             'bando_registra_evento', 'bando_applica_evento',
             'bando_fondi', 'bando_separa', 'bando_scegli_master',
             'bando_pubblica', 'bando_ritira', 'bando_cambia_slug',
             'bando_transizioni_automatiche', 'bando_transizione_ammessa',
             'bando_dominio_verificante',
             'lock_acquisisci', 'lock_rilascia'
           )
  LOOP
    EXECUTE format('DROP FUNCTION IF EXISTS %s', f.firma);
  END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- 3. La lista bianca
-- ---------------------------------------------------------------------------
-- Si può cancellare senza rimpianti: è generata da
-- `tests/stato-bando/casi.json` e rinasce identica rieseguendo la 04.

DROP TABLE IF EXISTS public.bando_transizione;

-- ---------------------------------------------------------------------------
-- 4. I job: via l'orario, torna il giornaliero
-- ---------------------------------------------------------------------------
-- Stessa transazione del DROP TRIGGER, per la ragione simmetrica a quella
-- della 04: fra i due comandi il job orario chiamerebbe una funzione che non
-- esiste più.

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'bandi-transizioni-orarie') THEN
    PERFORM cron.unschedule('bandi-transizioni-orarie');
  END IF;
END $$;

-- Testo LETTERALE di backend/sql/bando_auto_chiusura_scaduti.sql (righe
-- 35-40): il job com'era prima della 04, senza una virgola di differenza.
-- pg_cron gira in UTC: 23:20 UTC = 00:20 a Roma d'inverno, 01:20 d'estate.
select cron.schedule(
  'chiudi-bandi-scaduti',
  '20 23 * * *',
  $$
  update bando
     set stato_bando = 'chiuso'
   where data_scadenza < (now() at time zone 'Europe/Rome')::date
     and stato_bando is distinct from 'chiuso'
  $$
);

COMMIT;

-- ============================================================================
-- Verifica post-rollback
-- ============================================================================
-- 1) Un solo job dei bandi, ed è quello storico:
--      SELECT jobname, schedule, active FROM cron.job ORDER BY jobname;
--      -- atteso: chiudi-bandi-scaduti | 20 23 * * * | t
--      --         NESSUN bandi-transizioni-orarie
--
-- 2) Nessuna funzione della 04 rimasta:
--      SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
--       WHERE n.nspname = 'public'
--         AND p.proname IN ('bando_registra_evento','bando_applica_evento','bando_fondi',
--                           'bando_separa','bando_pubblica','bando_ritira','bando_cambia_slug',
--                           'lock_acquisisci','lock_rilascia','bando_transizioni_automatiche',
--                           'bando_transizione_ammessa','bando_dominio_verificante','bando_scegli_master');
--      -- atteso: 0 righe
--      SELECT to_regclass('public.bando_transizione');   -- atteso: NULL
--
-- 3) L'UPDATE diretto torna possibile (è il difetto che la 04 chiudeva;
--    da annullare):
--      BEGIN;
--        UPDATE bando SET stato_bando = stato_bando
--         WHERE id = (SELECT id FROM bando WHERE pubblicato ORDER BY id LIMIT 1);
--        -- atteso: UPDATE 1, nessuna eccezione
--      ROLLBACK;
--
-- 4) Gli eventi sono rimasti tutti (e devono):
--      SELECT count(*), max(cursore) FROM bando_evento;
--
-- 5) Recupero del pregresso, se il job orario era fermo da un po'
--    (stessa UPDATE del file storico, una tantum):
--      UPDATE bando SET stato_bando = 'chiuso'
--       WHERE data_scadenza < (now() at time zone 'Europe/Rome')::date
--         AND stato_bando IS DISTINCT FROM 'chiuso';
-- ============================================================================

-- ============================================================================
-- Variante del job per un DB che ha già la migrazione 06 applicata e righe
-- sospese o revocate (la guardia in testa al file rimanda qui). Non è il
-- testo storico: esclude esplicitamente i due stati nuovi, che il job del
-- 06/07/2026 non conosceva.
--
--   select cron.schedule(
--     'chiudi-bandi-scaduti',
--     '20 23 * * *',
--     $job$
--     update bando
--        set stato_bando = 'chiuso'
--      where data_scadenza < (now() at time zone 'Europe/Rome')::date
--        and stato_bando in ('aperto', 'in apertura prossimamente')
--     $job$
--   );
-- ============================================================================
