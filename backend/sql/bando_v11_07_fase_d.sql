-- ============================================================================
-- bando_v11_07_fase_d.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Chiude la fase (d): la vista `bando_pubblico` perde le colonne
--   deprecate, la RLS di `bando` passa da `stato_processing='completed' AND
--   slug IS NOT NULL` a `pubblicato`, e su `bando` anon conserva soltanto i
--   privilegi di colonna che servono alla vista e alle policy.
--
--   Da qui in poi «nessun link ad aggregatori in una colonna leggibile da
--   anon» è una proprietà verificabile, non una promessa: `link_bando`,
--   `link_candidatura` e `allegati` non sono più raggiungibili.
--
-- Fase: (d).
--
-- PRECONDIZIONE BLOCCANTE — conferma scritta del committente che BandoFit è
--   in fase (c) IN PRODUZIONE, cioè che ha già:
--     1. tolto da `DETAIL_SELECT` `descrizione_raw`, `titolo_raw`,
--        `link_bando`, `link_candidatura` e `allegati`, leggendo CTA e
--        allegati da `bando_link`;
--     2. spostato la FTS su `ricerca=wfts(italian).<termini>`;
--     3. tolto `stato_processing=eq.completed&slug=not.is.null` dai 7
--        predicati (la vista è già filtrata e dopo questo file la colonna
--        non esiste più);
--     4. iniziato a leggere `stato_effettivo` e `fonte_ufficiale_*`;
--     5. risolto i miss per id/slug su `bando_fusione`/`bando_slug_storico`.
--   Una sola colonna rimasta in una `select=` risponde 42501 sull'INTERA
--   richiesta: per PostgREST non è un campo mancante, è un errore, e
--   BandoFit lo vede come 502.
--   Anche news1 deve essere già su `PUBLIC_BANDI_FONTE_LETTURA=bando_pubblico`.
--
-- Altre precondizioni
--   migrazioni 01, 02, 03, 05 applicate (04 e 06 consigliate ma non
--   necessarie a questo file).
--
-- Rompe BandoFit? SÌ se la fase (c) non è davvero in produzione. NO dopo.
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'INTERO file, poi il blocco
--   «Verifica». Rieseguibile.
--   Se qualcosa va storto: `bando_v11_07_fase_d_rollback.sql` rimette la
--   vista e i grant della fase (b) in un colpo solo.
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
  IF to_regclass('public.bando_pubblico') IS NULL THEN
    RAISE EXCEPTION 'la vista bando_pubblico non esiste: applicare prima bando_v11_05_vista_pubblica.sql';
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 1. La vista senza le colonne deprecate
-- ---------------------------------------------------------------------------
-- Mai `CREATE OR REPLACE`: non può TOGLIERE colonne. DROP + CREATE nella
-- stessa transazione è atomico e nessun lettore vede la vista assente.

DROP VIEW IF EXISTS public.bando_pubblico;

CREATE VIEW public.bando_pubblico
WITH (security_invoker = true) AS
SELECT
  b.id,
  b.slug,
  b.titolo,
  b.titolo_breve,
  b.descrizione_breve,
  CASE WHEN jsonb_typeof(b.contenuto) = 'object' THEN b.contenuto END AS contenuto,
  b.livello,
  b.ente_erogatore,
  b.area_geografica,
  b.tematica,
  b.data_pubblicazione,
  b.data_apertura,
  b.data_scadenza,
  b.ora_apertura,
  b.ora_scadenza,
  b.data_pubblicazione_verificata,
  b.data_apertura_verificata,
  b.data_scadenza_verificata,
  b.importo_totale_eur,
  b.importo_max_per_progetto_eur,
  b.stato_bando,
  b.stato_bando_verificato,
  public.bando_stato_effettivo(
    b.stato_bando,
    b.data_apertura,
    b.data_apertura_verificata,
    b.ora_apertura,
    b.data_scadenza,
    b.ora_scadenza,
    now()
  ) AS stato_effettivo,
  b.tipologia_bando_id,
  b.modalita_erogazione_id,
  b.programma_id,
  b.fonte_ufficiale_stato,
  b.fonte_ufficiale_tipo,
  EXISTS (
    SELECT 1 FROM public.bando_link l
     WHERE l.id = b.fonte_ufficiale_link_id AND l.tipo = 'atto'
  ) AS fonte_ufficiale_e_atto,
  b.fonte_ufficiale_url,
  b.fonte_ufficiale_host,
  b.fonte_ufficiale_verificata_at,
  (SELECT c.ultimo_controllo_at
     FROM public.bando_controllo c
    WHERE c.bando_id = b.id) AS ultimo_controllo_at,
  b.ricerca,
  b.pubblicato_at,
  b.created_at,
  b.ultimo_cambiamento_at
FROM public.bando b
WHERE b.pubblicato;

-- Uscite dalla vista con questo file: stato_processing, link_bando,
-- link_candidatura, link_candidatura_source, allegati, titolo_raw,
-- descrizione_raw. CTA e allegati si leggono da `bando_link`.
COMMENT ON VIEW public.bando_pubblico IS
  'Contratto di lettura del DB bandi, fase (d): senza le colonne deprecate. CTA e allegati stanno in bando_link, la cronologia in bando_evento.';

REVOKE ALL ON TABLE public.bando_pubblico FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.bando_pubblico TO anon;
GRANT SELECT ON TABLE public.bando_pubblico TO service_role;

-- ---------------------------------------------------------------------------
-- 2. RLS di `bando` sulla pubblicazione
-- ---------------------------------------------------------------------------
-- Il predicato storico e `pubblicato` coincidono su tutte le righe tranne i
-- doppioni fusi e i ritirati, che da qui in poi spariscono anche da `bando`
-- (restano in `bando_fusione` e `bando_slug_storico`, che sono leggibili).

ALTER TABLE public.bando ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bando_public_read ON public.bando;
CREATE POLICY bando_public_read ON public.bando
  FOR SELECT TO anon
  USING (pubblicato);

-- ---------------------------------------------------------------------------
-- 3. Privilegi di colonna su `bando`
-- ---------------------------------------------------------------------------
-- Oggi anon e authenticated hanno ALL sulla tabella. Con `security_invoker`
-- anon deve poter leggere OGNI colonna che la vista referenzia, compresa
-- quella del `WHERE`, e le policy di `bando_link`, `bando_evento` e
-- `bando_controllo` interrogano `bando.id`, `bando.pubblicato` e
-- `bando.bando_master_id`: revocarle spegnerebbe la vista insieme alle
-- colonne deprecate.

-- `PUBLIC` compreso: è l'unica REVOKE della serie che lo ometteva, e un
-- privilegio concesso a PUBLIC arriva ad anon per altra strada.
REVOKE ALL ON TABLE public.bando FROM PUBLIC, anon, authenticated;

GRANT SELECT (
  id,
  slug,
  titolo,
  titolo_breve,
  descrizione_breve,
  contenuto,
  livello,
  ente_erogatore,
  area_geografica,
  tematica,
  data_pubblicazione,
  data_apertura,
  data_scadenza,
  ora_apertura,
  ora_scadenza,
  data_pubblicazione_verificata,
  data_apertura_verificata,
  data_scadenza_verificata,
  importo_totale_eur,
  importo_max_per_progetto_eur,
  stato_bando,
  stato_bando_verificato,
  tipologia_bando_id,
  modalita_erogazione_id,
  programma_id,
  fonte_ufficiale_stato,
  fonte_ufficiale_tipo,
  fonte_ufficiale_url,
  fonte_ufficiale_host,
  fonte_ufficiale_verificata_at,
  -- referenziata dall'EXISTS che calcola `fonte_ufficiale_e_atto`
  fonte_ufficiale_link_id,
  ricerca,
  pubblicato_at,
  created_at,
  ultimo_cambiamento_at,
  -- non nella vista, ma indispensabili: il WHERE e le policy delle altre
  -- tabelle del contratto
  pubblicato,
  bando_master_id,
  ritirato_at
) ON TABLE public.bando TO anon;

-- ---------------------------------------------------------------------------
-- 4. Allowlist ridotta a una funzione sola
-- ---------------------------------------------------------------------------
-- In fase (d) la vista non chiama più `dominio_di` né
-- `bando_host_aggregatore`: le colonne di link che mascheravano
-- (`link_bando`, `link_candidatura`, `allegati`) non ci sono più.
-- `bando_host_aggregatore` è SECURITY DEFINER e legge `dominio_ufficiale`,
-- cioè una tabella interna: lasciarla eseguibile ad anon significherebbe
-- lasciargli un oracolo sulla blocklist senza che nulla la usi.
-- `bando_stato_effettivo` resta: la vista la chiama ancora.
REVOKE EXECUTE ON FUNCTION public.dominio_di(text) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.bando_host_aggregatore(text) FROM PUBLIC, anon, authenticated;

COMMIT;

-- ============================================================================
-- Riconciliazione (rieseguibile da sola)
-- ============================================================================
-- Non c'è stato da riconciliare: la 07 tocca solo definizioni e privilegi.
-- Quello che va riverificato è che nessuna colonna deprecata sia rimasta
-- concessa:
--
--   SELECT column_name FROM information_schema.column_privileges
--    WHERE table_schema='public' AND table_name='bando' AND grantee='anon'
--      AND column_name IN ('link_bando','link_candidatura','link_candidatura_source',
--                          'allegati','titolo_raw','descrizione_raw','stato_processing',
--                          'raw_data','hash_bando','canonical_key','confidence_score',
--                          'rejection_reason','fonti_aggiuntive','updated_at','fonte_id');
--   -- atteso: 0 righe
-- ============================================================================

-- ============================================================================
-- Verifica post-deploy
-- ============================================================================
-- 1) Le colonne deprecate non sono più raggiungibili. I blocchi «come anon»
--    di questo file sono AUTO-CONTENUTI: `SET LOCAL` fuori da una transazione
--    dà solo `WARNING: SET LOCAL can only be used in transaction blocks` e la
--    query gira come `postgres`, cioè come proprietario delle tabelle, che
--    scavalca la RLS e ha ogni privilegio — tutti gli esiti attesi
--    diventerebbero falsi positivi. Incollare ogni blocco per intero; il
--    ROLLBACK ripristina il ruolo.
--      BEGIN;
--        SET LOCAL ROLE anon;
--        SELECT link_bando FROM bando LIMIT 1;          -- atteso: 42501
--        SELECT id, slug FROM bando_pubblico LIMIT 1;   -- atteso: 200
--        SELECT count(*) FROM bando_pubblico;           -- atteso: = count(pubblicato)
--        SELECT count(*) FROM bando;                    -- atteso: = count(pubblicato)
--      ROLLBACK;
--
-- 2) Le 8 richieste di riferimento di BandoFit (R1…R8 di §13.11), rieseguite
--    sulla vista: tutte 200, con gli stessi `Content-Range` della fase (c).
--
-- 3) Un doppione fuso non è più leggibile in `bando` ma resta nella mappa.
--      BEGIN;
--        SET LOCAL ROLE anon;
--        SELECT count(*) FROM bando b
--          JOIN bando_fusione f ON f.bando_id = b.id;   -- atteso: 0
--        SELECT count(*) FROM bando_fusione;            -- atteso: > 0
--      ROLLBACK;
--
-- 4) Privilegi di scrittura di anon azzerati. `PUBLIC` incluso: un privilegio
--    concesso a PUBLIC arriverebbe ad anon per altra strada.
--      SELECT grantee, privilege_type FROM information_schema.role_table_grants
--       WHERE table_schema='public' AND table_name='bando'
--         AND grantee IN ('anon','PUBLIC');
--      -- atteso: 0 righe (restano solo i privilegi di COLONNA)
--      SELECT count(DISTINCT column_name) FROM information_schema.column_privileges
--       WHERE table_schema='public' AND table_name='bando' AND grantee='anon';
--      -- atteso: 38
--
-- 5) `authenticated` non legge più nulla di `bando`.
--      SELECT count(*) FROM information_schema.column_privileges
--       WHERE table_schema='public' AND table_name='bando' AND grantee='authenticated';
--      -- atteso: 0
--
-- 6) Prestazioni invariate: rieseguire G1 di §2.a-bis come anon, < 3 s.
--      BEGIN; SET LOCAL ROLE anon; EXPLAIN (ANALYZE, BUFFERS) <query G1>; ROLLBACK;
-- ============================================================================
