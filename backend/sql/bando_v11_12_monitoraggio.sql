-- ==========================================
-- bando_v11_12_monitoraggio.sql
-- DB bandi: riepilogo di monitoraggio
-- ==========================================
-- Scopo
--   Un riepilogo neutro della salute dei
--   bandi. Lo scrive il sorvegliante con la
--   service key (upsert della riga id=1) e
--   lo legge un pannello esterno con la
--   anon key, SOLO attraverso la funzione a
--   chiave monitoraggio_catalogo().
--
--   Il file crea cinque oggetti:
--   1. la tabella monitoraggio_riepilogo
--      (una sola riga, id=1);
--   2. il trigger monitoraggio_riepilogo_ora
--      (aggiornato_at = orologio del DB);
--   3. la tabella monitoraggio_chiave (le
--      impronte delle chiavi, mai le
--      chiavi);
--   4. monitoraggio_job_orario(), per il
--      sorvegliante (solo service_role);
--   5. monitoraggio_catalogo(p_chiave), la
--      sola funzione nuova per anon.
--
-- Fase: solo oggetti nuovi. Nessuna
--   colonna, tabella, funzione o riga
--   esistente viene toccata.
--
-- Precondizioni: solo la tabella bando
--   (serve al conteggio della verifica).
--   Si applica dopo la 11 e prima della
--   13, ma non dipende da nessuna delle due
--   né dalla 07.
--
-- Rompe BandoFit? NO. Nessun oggetto che
--   BandoFit legge oggi cambia. La funzione
--   nuova risponde solo in POST e solo con
--   una chiave valida.
--
-- Come si applica
--   SQL Editor: incollare ed eseguire
--   l'INTERO file. Rieseguibile, anche dopo
--   la 13. Poi inserire l'impronta della
--   chiave come in «Dopo l'applicazione»,
--   in fondo. Il sender non va riavviato:
--   il sorvegliante è un processo nuovo a
--   ogni lancio.
--
-- COSA NON È REVERSIBILE
--   Il rollback cancella il riepilogo e le
--   impronte. Dopo un rollback e una nuova
--   applicazione l'impronta va reinserita.
-- ==========================================


-- ------------------------------------------
-- 1. Fotografia iniziale
-- ------------------------------------------
-- Le funzioni di public eseguibili da anon
-- e il numero di bandi, PRIMA di questo
-- file. Il blocco di verifica le confronta
-- con quelle DOPO: la 12 può aggiungere
-- ad anon solo monitoraggio_catalogo. Una
-- fotografia e non un elenco scritto a
-- mano, così la 12 si riesegue anche dopo
-- la 13 e con le funzioni storiche.
DROP TABLE IF EXISTS pg_temp._m12_prima;
CREATE TEMP TABLE _m12_prima AS
SELECT p.oid AS f
  FROM pg_proc p
  JOIN pg_namespace n
    ON n.oid = p.pronamespace
 WHERE n.nspname = 'public'
   AND has_function_privilege(
         'anon', p.oid, 'EXECUTE');

DROP TABLE IF EXISTS pg_temp._m12_bandi;
CREATE TEMP TABLE _m12_bandi AS
SELECT count(*) AS n FROM public.bando;


-- ------------------------------------------
-- 2. monitoraggio_riepilogo
-- ------------------------------------------
-- calcolato_at è l'ora del sorvegliante,
-- solo informativa; aggiornato_at la mette
-- il trigger del punto 3. memoria è lo
-- stato del sorvegliante fra due lanci: la
-- funzione di lettura non la restituisce
-- mai.
CREATE TABLE IF NOT EXISTS
  public.monitoraggio_riepilogo (
  id smallint PRIMARY KEY DEFAULT 1,
  calcolato_at timestamptz NOT NULL,
  aggiornato_at timestamptz NOT NULL
    DEFAULT now(),
  intervallo_ritardo interval NOT NULL
    DEFAULT '45 minutes',
  versione smallint NOT NULL,
  riepilogo jsonb NOT NULL,
  memoria jsonb NOT NULL DEFAULT '{}',
  CONSTRAINT monitoraggio_riepilogo_uno
    CHECK (id = 1),
  CONSTRAINT
    monitoraggio_riepilogo_ritardo
    CHECK (intervallo_ritardo
      BETWEEN interval '15 minutes'
          AND interval '6 hours'),
  CONSTRAINT
    monitoraggio_riepilogo_versione
    CHECK (versione = 1),
  CONSTRAINT monitoraggio_riepilogo_forma
    CHECK (
      jsonb_typeof(riepilogo) = 'object'
      AND octet_length(riepilogo::text)
          < 65536
      AND riepilogo ->> 'versione' = '1'),
  CONSTRAINT
    monitoraggio_riepilogo_memoria
    CHECK (
      jsonb_typeof(memoria) = 'object'
      AND octet_length(memoria::text)
          < 16384)
);

-- I privilegi di default del progetto
-- danno ALL ad anon, authenticated e
-- service_role: si toglie tutto a tutti e
-- si ridanno a service_role solo i tre
-- privilegi dell'upsert di PostgREST.
REVOKE ALL
  ON TABLE public.monitoraggio_riepilogo
  FROM PUBLIC, anon, authenticated,
       service_role;
GRANT SELECT, INSERT, UPDATE
  ON TABLE public.monitoraggio_riepilogo
  TO service_role;

ALTER TABLE public.monitoraggio_riepilogo
  ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS
  monitoraggio_riepilogo_servizio
  ON public.monitoraggio_riepilogo;
CREATE POLICY
  monitoraggio_riepilogo_servizio
  ON public.monitoraggio_riepilogo
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);


-- ------------------------------------------
-- 3. Trigger monitoraggio_riepilogo_ora
-- ------------------------------------------
-- aggiornato_at è l'orologio del DB, mai
-- quello di chi scrive: in_ritardo non
-- dipende dall'ora del server.
CREATE OR REPLACE FUNCTION
  public.monitoraggio_riepilogo_ora()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  NEW.aggiornato_at := now();
  RETURN NEW;
END
$$;

REVOKE ALL ON FUNCTION
  public.monitoraggio_riepilogo_ora()
  FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE TRIGGER
  monitoraggio_riepilogo_ora
  BEFORE INSERT OR UPDATE
  ON public.monitoraggio_riepilogo
  FOR EACH ROW EXECUTE FUNCTION
  public.monitoraggio_riepilogo_ora();


-- ------------------------------------------
-- 4. monitoraggio_chiave
-- ------------------------------------------
-- Una riga per chiave del pannello, con la
-- sola impronta sha256. valida_fino resta
-- NULL in via ordinaria: serve solo a
-- chiudere la chiave vecchia durante una
-- rotazione. Nessuno la legge via API:
-- RLS senza policy e nessun privilegio,
-- nemmeno a service_role.
CREATE TABLE IF NOT EXISTS
  public.monitoraggio_chiave (
  nome text PRIMARY KEY,
  impronta bytea NOT NULL,
  valida_fino timestamptz,
  creata_at timestamptz DEFAULT now(),
  CONSTRAINT monitoraggio_chiave_nome
    CHECK (nome ~ '^[a-z0-9_-]{1,32}$'),
  CONSTRAINT
    monitoraggio_chiave_impronta
    CHECK (length(impronta) = 32)
);

REVOKE ALL
  ON TABLE public.monitoraggio_chiave
  FROM PUBLIC, anon, authenticated,
       service_role;

ALTER TABLE public.monitoraggio_chiave
  ENABLE ROW LEVEL SECURITY;


-- ------------------------------------------
-- 5. monitoraggio_job_orario()
-- ------------------------------------------
-- Esito del job orario delle transizioni
-- (04), letto dal sorvegliante. La guardia
-- di ruolo è quella della 04.
--
-- Risposta:
--   {misurato, ultimo_avvio_at,
--    ultimo_esito, ultimo_ok_at,
--    falliti_24h}
-- ultimo_esito è l'ultima esecuzione
-- CONCLUSA (succeeded|failed); se non ce
-- n'è, non_misurato.
-- Senza lo schema cron: {misurato:false}.
-- Con lo schema ma senza il job:
-- misurato:true, esito non_misurato e
-- nessun avvio, così l'allarme job_orario
-- scatta invece di tacere.
-- Le tabelle di cron hanno una RLS per
-- utente: la funzione è del proprietario
-- che ha creato il job (lo stesso che
-- applica le migrazioni), quindi lo vede.
CREATE OR REPLACE FUNCTION
  public.monitoraggio_job_orario()
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_job bigint;
  v jsonb;
BEGIN
  IF NOT (
       session_user IN
         ('postgres', 'supabase_admin')
    OR coalesce(nullif(current_setting(
         'request.jwt.claims', true), '')
         ::json ->> 'role', '')
       = 'service_role')
  THEN
    RAISE EXCEPTION 'non autorizzato'
      USING ERRCODE = '42501';
  END IF;

  IF to_regclass('cron.job') IS NULL
     OR to_regclass(
          'cron.job_run_details') IS NULL
  THEN
    RETURN jsonb_build_object(
      'misurato', false);
  END IF;

  SELECT j.jobid INTO v_job
    FROM cron.job j
   WHERE j.jobname =
         'bandi-transizioni-orarie'
   ORDER BY j.jobid DESC
   LIMIT 1;

  IF v_job IS NULL THEN
    RETURN jsonb_build_object(
      'misurato', true,
      'ultimo_avvio_at', NULL,
      'ultimo_esito', 'non_misurato',
      'ultimo_ok_at', NULL,
      'falliti_24h', 0);
  END IF;

  SELECT jsonb_build_object(
    'misurato', true,
    'ultimo_avvio_at', max(d.start_time),
    'ultimo_esito', coalesce((
      SELECT u.status
        FROM cron.job_run_details u
       WHERE u.jobid = v_job
         AND u.status IN
             ('succeeded', 'failed')
       ORDER BY u.start_time DESC
                NULLS LAST,
                u.runid DESC
       LIMIT 1), 'non_misurato'),
    'ultimo_ok_at', max(d.end_time)
      FILTER (WHERE d.status
              = 'succeeded'),
    'falliti_24h', count(*)
      FILTER (WHERE d.status = 'failed'
        AND d.start_time
          > now() - interval '24 hours'))
    INTO v
    FROM cron.job_run_details d
   WHERE d.jobid = v_job;

  RETURN v;
END
$$;

REVOKE ALL ON FUNCTION
  public.monitoraggio_job_orario()
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
  public.monitoraggio_job_orario()
  TO service_role;


-- ------------------------------------------
-- 6. monitoraggio_catalogo(p_chiave)
-- ------------------------------------------
-- La sola porta del pannello. VOLATILE
-- serve solo a evitare cache e inlining:
-- NON impedisce a PostgREST una GET, e per
-- questo il metodo si controlla qui come
-- prima istruzione.
-- Ogni rifiuto è lo stesso RAISE 42501
-- 'non autorizzato': metodo sbagliato,
-- chiave assente, corta, lunga, errata o
-- scaduta non si distinguono. La chiave
-- non entra mai in un messaggio.
-- Del riepilogo si copiano UNA PER UNA le
-- 11 chiavi di primo livello dello schema
-- v1: una chiave in più scritta dal
-- sorvegliante non esce da qui.
CREATE OR REPLACE FUNCTION
  public.monitoraggio_catalogo(
    p_chiave text)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  r public.monitoraggio_riepilogo;
BEGIN
  IF coalesce(current_setting(
       'request.method', true), '')
     <> 'POST'
  THEN
    RAISE EXCEPTION 'non autorizzato'
      USING ERRCODE = '42501';
  END IF;

  IF p_chiave IS NULL
     OR length(p_chiave) < 32
     OR length(p_chiave) > 256
     OR NOT EXISTS (
       SELECT 1
         FROM public.monitoraggio_chiave k
        WHERE k.impronta = sha256(
                convert_to(
                  p_chiave, 'UTF8'))
          AND (k.valida_fino IS NULL
               OR k.valida_fino > now()))
  THEN
    RAISE EXCEPTION 'non autorizzato'
      USING ERRCODE = '42501';
  END IF;

  SELECT * INTO r
    FROM public.monitoraggio_riepilogo
   WHERE id = 1;

  IF NOT FOUND THEN
    RETURN jsonb_build_object(
      'versione', 1,
      'generato_at', now(),
      'calcolato_at', NULL,
      'aggiornato_at', NULL,
      'minuti_dal_calcolo', NULL,
      'in_ritardo', true,
      'orologio_disallineato', NULL,
      'riepilogo', NULL);
  END IF;

  RETURN jsonb_build_object(
    'versione', 1,
    'generato_at', now(),
    'calcolato_at', r.calcolato_at,
    'aggiornato_at', r.aggiornato_at,
    'minuti_dal_calcolo',
      floor(extract(epoch FROM
        now() - r.aggiornato_at)
        / 60)::int,
    'in_ritardo',
      now() > r.aggiornato_at
              + r.intervallo_ritardo,
    'orologio_disallineato',
      abs(extract(epoch FROM
        r.calcolato_at
        - r.aggiornato_at)) > 300,
    'riepilogo', jsonb_build_object(
      'stato',
        r.riepilogo -> 'stato',
      'segnali',
        r.riepilogo -> 'segnali',
      'non_misurati',
        r.riepilogo -> 'non_misurati',
      'produttore',
        r.riepilogo -> 'produttore',
      'giri',
        r.riepilogo -> 'giri',
      'controlli',
        r.riepilogo -> 'controlli',
      'lavorazioni',
        r.riepilogo -> 'lavorazioni',
      'ingresso',
        r.riepilogo -> 'ingresso',
      'eventi',
        r.riepilogo -> 'eventi',
      'da_verificare',
        r.riepilogo -> 'da_verificare',
      'job_orario',
        r.riepilogo -> 'job_orario'));
END
$$;

REVOKE ALL ON FUNCTION
  public.monitoraggio_catalogo(text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
  public.monitoraggio_catalogo(text)
  TO anon, service_role;


-- ------------------------------------------
-- 7. PostgREST
-- ------------------------------------------
NOTIFY pgrst, 'reload schema';


-- ------------------------------------------
-- 8. Verifica (si ferma al primo errore)
-- ------------------------------------------
-- Non inserisce chiavi.
DO $$
DECLARE
  v_cat oid := to_regprocedure(
    'public.monitoraggio_catalogo(text)');
  v_job oid := to_regprocedure(
    'public.monitoraggio_job_orario()');
  v_ora oid := to_regprocedure(
    'public.monitoraggio_riepilogo_ora()');
  v_elenco text;
BEGIN
  IF v_cat IS NULL OR v_job IS NULL
     OR v_ora IS NULL THEN
    RAISE EXCEPTION
      'V1: manca una delle tre funzioni';
  END IF;

  -- anon e authenticated: niente sulle
  -- due tabelle, nemmeno per colonna.
  IF EXISTS (
    SELECT 1
      FROM unnest(ARRAY['anon',
             'authenticated']) AS ru(r)
     CROSS JOIN unnest(ARRAY[
       'public.monitoraggio_riepilogo',
       'public.monitoraggio_chiave'])
       AS ta(t)
     WHERE has_table_privilege(ru.r, ta.t,
             'SELECT,INSERT,UPDATE,'
             || 'DELETE,TRUNCATE,'
             || 'REFERENCES,TRIGGER')
        OR has_any_column_privilege(
             ru.r, ta.t,
             'SELECT,INSERT,UPDATE,'
             || 'REFERENCES'))
  THEN
    RAISE EXCEPTION
      'V2: anon o authenticated hanno '
      'privilegi sulle tabelle nuove';
  END IF;

  -- service_role: niente sulle chiavi,
  -- solo SELECT, INSERT, UPDATE sul
  -- riepilogo.
  IF has_table_privilege('service_role',
       'public.monitoraggio_chiave',
       'SELECT,INSERT,UPDATE,DELETE,'
       || 'TRUNCATE,REFERENCES,TRIGGER')
     OR has_any_column_privilege(
       'service_role',
       'public.monitoraggio_chiave',
       'SELECT,INSERT,UPDATE,REFERENCES')
  THEN
    RAISE EXCEPTION
      'V3: service_role vede '
      'monitoraggio_chiave';
  END IF;
  IF NOT has_table_privilege(
       'service_role',
       'public.monitoraggio_riepilogo',
       'SELECT')
     OR NOT has_table_privilege(
       'service_role',
       'public.monitoraggio_riepilogo',
       'INSERT')
     OR NOT has_table_privilege(
       'service_role',
       'public.monitoraggio_riepilogo',
       'UPDATE')
     OR has_table_privilege(
       'service_role',
       'public.monitoraggio_riepilogo',
       'DELETE,TRUNCATE')
  THEN
    RAISE EXCEPTION
      'V4: privilegi di service_role '
      'sul riepilogo diversi da '
      'SELECT, INSERT, UPDATE';
  END IF;

  -- Funzioni: chi le esegue.
  IF has_function_privilege('anon',
       v_job, 'EXECUTE')
     OR has_function_privilege('anon',
       v_ora, 'EXECUTE')
     OR has_function_privilege(
       'authenticated', v_cat, 'EXECUTE')
     OR has_function_privilege(
       'authenticated', v_job, 'EXECUTE')
     OR has_function_privilege(
       'authenticated', v_ora, 'EXECUTE')
     OR NOT has_function_privilege(
       'anon', v_cat, 'EXECUTE')
     OR NOT has_function_privilege(
       'service_role', v_cat, 'EXECUTE')
     OR NOT has_function_privilege(
       'service_role', v_job, 'EXECUTE')
  THEN
    RAISE EXCEPTION
      'V5: privilegi di esecuzione '
      'delle funzioni nuove sbagliati';
  END IF;

  -- Nessun GRANT ad authenticated su
  -- oggetti monitoraggio_*.
  IF EXISTS (
    SELECT 1 FROM pg_class c
      JOIN pg_namespace n
        ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relname LIKE 'monitoraggio%'
       AND EXISTS (
         SELECT 1 FROM aclexplode(
           c.relacl) a
          WHERE a.grantee =
            'authenticated'::regrole))
  THEN
    RAISE EXCEPTION
      'V6: GRANT ad authenticated';
  END IF;

  -- RLS attiva sulle due tabelle.
  IF EXISTS (
    SELECT 1 FROM pg_class c
     WHERE c.oid IN (
       'public.monitoraggio_riepilogo'
         ::regclass,
       'public.monitoraggio_chiave'
         ::regclass)
       AND NOT c.relrowsecurity)
  THEN
    RAISE EXCEPTION 'V7: RLS spenta';
  END IF;

  -- SECURITY DEFINER e search_path fisso.
  IF EXISTS (
    SELECT 1 FROM pg_proc p
     WHERE p.oid IN (v_cat, v_job)
       AND (NOT p.prosecdef
         OR p.proconfig IS NULL
         OR NOT EXISTS (
           SELECT 1
             FROM unnest(p.proconfig) c
            WHERE c LIKE 'search_path=%')))
  THEN
    RAISE EXCEPTION
      'V8: funzione senza SECURITY '
      'DEFINER o senza search_path';
  END IF;

  -- I sette vincoli e il trigger.
  IF (SELECT count(*)
        FROM pg_constraint
       WHERE conname IN (
         'monitoraggio_riepilogo_uno',
         'monitoraggio_riepilogo_ritardo',
         'monitoraggio_riepilogo_versione',
         'monitoraggio_riepilogo_forma',
         'monitoraggio_riepilogo_memoria',
         'monitoraggio_chiave_nome',
         'monitoraggio_chiave_impronta'))
     <> 7
  THEN
    RAISE EXCEPTION
      'V9: manca un vincolo CHECK';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger t
     WHERE t.tgrelid =
       'public.monitoraggio_riepilogo'
         ::regclass
       AND t.tgname =
         'monitoraggio_riepilogo_ora'
       AND NOT t.tgisinternal)
  THEN
    RAISE EXCEPTION
      'V10: manca il trigger';
  END IF;

  -- Insieme delle funzioni di anon: DOPO
  -- = PRIMA più monitoraggio_catalogo.
  SELECT string_agg(
           x.f::regprocedure::text, ', ')
    INTO v_elenco
    FROM (
      (SELECT p.oid AS f
         FROM pg_proc p
         JOIN pg_namespace n
           ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND has_function_privilege(
                'anon', p.oid,
                'EXECUTE')
       EXCEPT
       SELECT f FROM pg_temp._m12_prima
       EXCEPT
       SELECT v_cat)
      UNION ALL
      (SELECT f FROM pg_temp._m12_prima
       EXCEPT
       SELECT p.oid
         FROM pg_proc p
        WHERE has_function_privilege(
                'anon', p.oid,
                'EXECUTE'))
    ) x;
  IF v_elenco IS NOT NULL THEN
    RAISE EXCEPTION
      'V11: funzioni di anon cambiate '
      'oltre il catalogo: %', v_elenco;
  END IF;

  -- Controllo assoluto: di monitoraggio_*
  -- anon esegue solo il catalogo.
  IF EXISTS (
    SELECT 1 FROM pg_proc p
      JOIN pg_namespace n
        ON n.oid = p.pronamespace
     WHERE n.nspname = 'public'
       AND p.proname LIKE 'monitoraggio%'
       AND p.oid <> v_cat
       AND has_function_privilege(
             'anon', p.oid, 'EXECUTE'))
  THEN
    RAISE EXCEPTION
      'V12: anon esegue una funzione '
      'monitoraggio_* diversa dal '
      'catalogo';
  END IF;

  -- Nessun bando toccato.
  IF (SELECT count(*) FROM public.bando)
     <> (SELECT n FROM pg_temp._m12_bandi)
  THEN
    RAISE EXCEPTION
      'V13: il numero di bandi è cambiato';
  END IF;

  RAISE NOTICE
    'migrazione 12: verifica superata';
END
$$;

DROP TABLE IF EXISTS pg_temp._m12_prima;
DROP TABLE IF EXISTS pg_temp._m12_bandi;


-- ------------------------------------------
-- Dopo l'applicazione (una volta)
-- ------------------------------------------
-- La chiave non si stampa mai e non entra
-- mai nella history: né nel terminale né
-- nel SQL Editor.
-- 1. Sul server dove gira il backend del
--    pannello (dove vive il suo file
--    protetto), senza eco a schermo:
--      umask 077
--      CHIAVE=$(openssl rand -hex 32)
--      printf 'NOME=%s\n' "$CHIAVE" \
--        >> <file protetto>
--    NOME è la variabile che il pannello
--    legge.
-- 2. Stesso terminale: si stampa SOLO
--    l'impronta, poi la chiave si toglie:
--      printf %s "$CHIAVE" \
--        | sha256sum | cut -c1-64
--      unset CHIAVE
-- 3. Nel SQL Editor, con i 64 caratteri
--    esadecimali dell'impronta:
--      INSERT INTO
--        public.monitoraggio_chiave
--        (nome, impronta)
--      VALUES ('pannello', decode(
--        '<impronta>', 'hex'));
--
-- Rotazione: una riga nuova con un altro
-- nome; quando il pannello usa la nuova,
-- chiudere la vecchia:
--      UPDATE public.monitoraggio_chiave
--         SET valida_fino = now()
--       WHERE nome = '<vecchia>';
