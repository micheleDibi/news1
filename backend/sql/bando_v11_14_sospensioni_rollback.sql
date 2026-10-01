-- ==========================================
-- bando_v11_14_sospensioni_rollback.sql
-- DB bandi: rientro dalla migrazione 14
-- ==========================================
-- Scritto l'01/10/2026 da «db» (giro 3,
-- G3-D2).
--
-- Scopo
--   Rimette bando_applica_evento com'era
--   con la 11 e il trigger
--   bando_stato_solo_via_evento com'era
--   con la 04 (stessi token: righe corte,
--   stringhe spezzate in letterali
--   adiacenti), toglie
--   bando_correggi_stato e
--   bando_capacita_sospensioni, le quattro
--   righe della lista bianca della 14 e le
--   tre colonne scartato_* di
--   bando_evento, e rimette l'indice di
--   dedup degli eventi com'era con la 02
--   (vedi sotto).
--
-- Ordine: va applicato PRIMA di un
--   eventuale rollback della 13 (che
--   pretende 23 righe di lista bianca) e
--   della 11.
--
-- Rompe BandoFit? NO: le colonne tolte
--   non erano concesse ad anon.
--
-- Effetto sul codice
--   Il marcatore sparisce: il codice
--   rimette sospensione e revoca in ombra
--   (contratto interno bandi-giro-3 §3).
--   Gli eventi con una transizione non
--   ammessa tornano a sollevare 23514.
--
-- COSA NON È REVERSIBILE
--   Le marcature (scartato_*) si perdono:
--   quegli eventi tornano in coda. Gli
--   stati già cambiati da eventi della 14
--   o da correzioni della redazione
--   restano come sono, e i loro eventi
--   restano applicati. Se dopo la 14 sono
--   nate due correzioni identiche della
--   redazione nello stesso giorno (lo
--   stesso bando verso lo stesso stato),
--   l'indice della 02 non si può
--   ricostruire senza cancellare eventi:
--   in quel caso resta quello della 14, e
--   il file lo dice con una NOTICE.
--
-- Come si applica
--   Fuori dai giri e senza applica-eventi
--   in corso (la guardia rifiuta se il
--   lock «monitor» è tenuto): SQL Editor,
--   l'INTERO file. Rieseguibile.
--   Poi riavviare il sender: lo schema si
--   legge una volta per processo, e fino
--   al riavvio il codice crederebbe ancora
--   presenti le colonne scartato_* e le
--   due RPC. Se PostgREST espone ancora
--   le RPC tolte:
--   NOTIFY pgrst, 'reload schema';
-- ==========================================

BEGIN;

SET LOCAL lock_timeout = '5s';


-- ------------------------------------------
-- 1. Guardie
-- ------------------------------------------
DO $$
BEGIN
  IF to_regprocedure(
       'public.bando_capacita_eventi()')
     IS NULL THEN
    RAISE EXCEPTION
      'manca la 11: il rientro dalla 14 '
      'rimette la RPC della 11';
  END IF;
  IF to_regclass('public.pipeline_lock')
     IS NOT NULL THEN
    IF EXISTS (
      SELECT 1 FROM public.pipeline_lock
       WHERE nome = 'monitor'
         AND scade_at > now()) THEN
      RAISE EXCEPTION
        'il lock «monitor» è tenuto '
        '(applica-eventi o il monitor '
        'sono in corso): riprovare a '
        'lock libero';
    END IF;
  END IF;
END $$;


-- ------------------------------------------
-- 2. Le due funzioni nuove
-- ------------------------------------------
DROP FUNCTION IF EXISTS
  public.bando_capacita_sospensioni();
DROP FUNCTION IF EXISTS
  public.bando_correggi_stato(
    integer, text, text);


-- ------------------------------------------
-- 3. bando_applica_evento della 11
-- ------------------------------------------
CREATE OR REPLACE FUNCTION
  public.bando_applica_evento(
    p_evento_id bigint)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  e                public.bando_evento;
  riga             public.bando;
  campi            jsonb;
  stato_nuovo      text;
  tocca_apertura   boolean;
  tocca_scadenza   boolean;
BEGIN
  IF NOT ( session_user IN
           ('postgres','supabase_admin')
        OR coalesce(nullif(
             current_setting(
               'request.jwt.claims', true),
             '')::json->>'role','')
           = 'service_role' )
  THEN RAISE EXCEPTION 'non autorizzato'
         USING ERRCODE = '42501';
  END IF;

  SELECT * INTO e
    FROM public.bando_evento
   WHERE id = p_evento_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION
      'evento % inesistente', p_evento_id
      USING ERRCODE = '23503';
  END IF;

  -- Idempotente: un evento si applica una
  -- volta sola.
  IF e.applicato THEN
    RETURN false;
  END IF;

  campi := CASE
    WHEN jsonb_typeof(e.valore_dopo)
         = 'object' THEN e.valore_dopo
    WHEN e.campo IS NOT NULL
         AND e.valore_dopo IS NOT NULL
      THEN jsonb_build_object(
             e.campo, e.valore_dopo)
    ELSE '{}'::jsonb
  END;

  campi := campi - ARRAY(
    SELECT k
      FROM jsonb_object_keys(campi) AS k
     WHERE k NOT IN ('stato_bando',
                     'data_pubblicazione',
                     'data_apertura',
                     'ora_apertura',
                     'data_scadenza',
                     'ora_scadenza')
  );

  -- v11_11: traduzione di stato_proposto
  -- (sospensione e revoca registrate in
  -- ombra), mai sopra uno stato_bando.
  IF jsonb_typeof(e.valore_dopo) = 'object'
     AND NOT (campi ? 'stato_bando')
     AND (   (e.tipo = 'sospensione'
              AND e.valore_dopo
                  ->> 'stato_proposto'
                  = 'sospeso')
          OR (e.tipo = 'revoca'
              AND e.valore_dopo
                  ->> 'stato_proposto'
                  = 'revocato'))
  THEN
    campi := campi || jsonb_build_object(
      'stato_bando',
      e.valore_dopo ->> 'stato_proposto');
  END IF;

  -- Eventi senza effetto sulle colonne
  -- (graduatoria, esito, faq,
  -- nuovo_allegato, fusione…): si marcano
  -- applicati lo stesso.
  IF campi = '{}'::jsonb THEN
    UPDATE public.bando_evento
       SET applicato = true,
           applicato_at = now()
     WHERE id = e.id;
    RETURN true;
  END IF;

  stato_nuovo    := campi ->> 'stato_bando';
  tocca_apertura := campi ?| ARRAY[
    'data_apertura', 'ora_apertura'];
  tocca_scadenza := campi ?| ARRAY[
    'data_scadenza', 'ora_scadenza'];

  SELECT * INTO riga
    FROM public.bando
   WHERE id = e.bando_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION
      'bando % inesistente', e.bando_id
      USING ERRCODE = '23503';
  END IF;

  -- La lista bianca si controlla QUI,
  -- prima dell'UPDATE; il trigger resta
  -- la garanzia per chi non passa da
  -- questa RPC.
  IF campi ? 'stato_bando'
     AND riga.pubblicato
     AND stato_nuovo
         IS DISTINCT FROM riga.stato_bando
     AND NOT
         public.bando_transizione_ammessa(
           riga.stato_bando, stato_nuovo,
           e.origine)
  THEN
    RAISE EXCEPTION
      'evento % (%): transizione non '
      'ammessa per «%»: % → % (bando %). '
      'La lista bianca è '
      'bando_transizione.',
      e.id, e.tipo, e.origine,
      riga.stato_bando, stato_nuovo,
      riga.id
      USING ERRCODE = '23514';
  END IF;

  -- §3.3: pubblicazione <= scadenza, qui e
  -- non nel CHECK, che fermerebbe l'intero
  -- lotto di applica-eventi.
  IF (CASE WHEN campi ? 'data_pubblicazione'
           THEN (campi
                 ->> 'data_pubblicazione'
                )::date
           ELSE riga.data_pubblicazione END)
     > (CASE WHEN campi ? 'data_scadenza'
             THEN (campi
                   ->> 'data_scadenza'
                  )::date
             ELSE riga.data_scadenza END)
  THEN
    IF NOT EXISTS (
      SELECT 1 FROM public.bando_evento x
       WHERE x.bando_id = e.bando_id
         AND x.tipo = 'elaborazione_bloccata'
         AND x.riferisce_a = e.id
    ) THEN
      PERFORM public.bando_registra_evento(
        e.bando_id, 'elaborazione_bloccata',
        'pipeline', 'date',
        jsonb_build_object(
          'evento_id', e.id,
          'motivo', 'data_pubblicazione > '
                    'data_scadenza'),
        NULL, NULL, NULL, false,
        p_riferisce_a => e.id);
    END IF;
    RAISE NOTICE
      'evento % (%): date incoerenti '
      '(pubblicazione > scadenza). Evento '
      'lasciato non applicato.',
      e.id, e.tipo;
    RETURN false;
  END IF;

  PERFORM set_config('bandi.evento_id',
                     e.id::text, true);
  PERFORM set_config('bandi.attore',
                     e.origine, true);

  BEGIN
    UPDATE public.bando b SET
      stato_bando =
        CASE WHEN campi ? 'stato_bando'
             THEN stato_nuovo
             ELSE b.stato_bando END,
      stato_bando_evento_id =
        CASE WHEN campi ? 'stato_bando'
             THEN e.id
             ELSE b.stato_bando_evento_id
        END,
      stato_bando_verificato =
        CASE WHEN campi ? 'stato_bando'
             THEN (e.verificato
                   AND stato_nuovo
                       IS NOT NULL)
             ELSE b.stato_bando_verificato
        END,

      data_pubblicazione =
        CASE WHEN campi
                  ? 'data_pubblicazione'
             THEN (campi
                   ->> 'data_pubblicazione'
                  )::date
             ELSE b.data_pubblicazione END,
      data_pubblicazione_evento_id =
        CASE WHEN campi
                  ? 'data_pubblicazione'
             THEN e.id
             ELSE
               b.data_pubblicazione_evento_id
        END,
      data_pubblicazione_verificata =
        CASE WHEN campi
                  ? 'data_pubblicazione'
             THEN (e.verificato
                   AND (campi
                     ->> 'data_pubblicazione'
                       ) IS NOT NULL)
             ELSE
              b.data_pubblicazione_verificata
        END,

      data_apertura =
        CASE WHEN campi ? 'data_apertura'
             THEN (campi
                   ->> 'data_apertura'
                  )::date
             ELSE b.data_apertura END,
      ora_apertura =
        CASE WHEN campi ? 'ora_apertura'
             THEN (campi
                   ->> 'ora_apertura'
                  )::time
             ELSE b.ora_apertura END,
      -- L'evento_id copre il gruppo data
      -- più ora (trigger della 03).
      data_apertura_evento_id =
        CASE WHEN tocca_apertura
             THEN e.id
             ELSE b.data_apertura_evento_id
        END,
      data_apertura_verificata =
        CASE WHEN tocca_apertura
        THEN (e.verificato AND (
          CASE WHEN campi ? 'data_apertura'
               THEN (campi
                     ->> 'data_apertura'
                    )::date
               ELSE b.data_apertura
          END) IS NOT NULL)
        ELSE b.data_apertura_verificata
        END,

      data_scadenza =
        CASE WHEN campi ? 'data_scadenza'
             THEN (campi
                   ->> 'data_scadenza'
                  )::date
             ELSE b.data_scadenza END,
      ora_scadenza =
        CASE WHEN campi ? 'ora_scadenza'
             THEN (campi
                   ->> 'ora_scadenza'
                  )::time
             ELSE b.ora_scadenza END,
      data_scadenza_evento_id =
        CASE WHEN tocca_scadenza
             THEN e.id
             ELSE b.data_scadenza_evento_id
        END,
      data_scadenza_verificata =
        CASE WHEN tocca_scadenza
        THEN (e.verificato AND (
          CASE WHEN campi ? 'data_scadenza'
               THEN (campi
                     ->> 'data_scadenza'
                    )::date
               ELSE b.data_scadenza
          END) IS NOT NULL)
        ELSE b.data_scadenza_verificata
        END
    WHERE b.id = e.bando_id;
  EXCEPTION WHEN check_violation THEN
    -- Prima di tutto: le GUC sono state
    -- accese fuori da questo blocco e la
    -- sua rollback non le spegne.
    PERFORM set_config('bandi.evento_id',
                       '', true);
    PERFORM set_config('bandi.attore',
                       '', true);

    IF campi ? 'stato_bando'
       AND stato_nuovo
           IN ('sospeso', 'revocato') THEN
      RAISE NOTICE
        'evento % (%): la colonna '
        'stato_bando non ammette ancora '
        '«%» (migrazione 06 non '
        'applicata). Evento lasciato non '
        'applicato.',
        e.id, e.tipo, stato_nuovo;
      RETURN false;
    END IF;
    RAISE;
  END;

  -- L'intenzione vale per una sola
  -- scrittura.
  PERFORM set_config('bandi.evento_id',
                     '', true);
  PERFORM set_config('bandi.attore',
                     '', true);

  UPDATE public.bando_evento
     SET applicato = true,
         applicato_at = now()
   WHERE id = e.id;

  RETURN true;
END;
$$;

COMMENT ON FUNCTION
  public.bando_applica_evento(bigint) IS
  'Riversa valore_dopo nelle colonne di '
  'bando (stato, date, ore) e marca '
  'l''evento applicato. Dalla migrazione '
  '11 traduce stato_proposto in '
  'stato_bando per sospensione/sospeso e '
  'revoca/revocato. true = applicato '
  'adesso; false = già applicato o stato '
  'non ancora ammesso dal CHECK.';

REVOKE ALL ON FUNCTION
  public.bando_applica_evento(bigint)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
  public.bando_applica_evento(bigint)
  TO service_role;


-- ------------------------------------------
-- 4. Il trigger dello stato della 04
-- ------------------------------------------
CREATE OR REPLACE FUNCTION
  public.bando_stato_solo_via_evento()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  evento_dichiarato text;
  attore            text;
BEGIN
  IF NEW.stato_bando IS NOT DISTINCT FROM
     OLD.stato_bando THEN
    RETURN NEW;
  END IF;

  -- Riga non ancora pubblicata: lo stato
  -- lo decide la pipeline.
  IF NOT OLD.pubblicato THEN
    RETURN NEW;
  END IF;

  evento_dichiarato := nullif(
    current_setting('bandi.evento_id',
                    true), '');
  attore            := nullif(
    current_setting('bandi.attore',
                    true), '');

  IF evento_dichiarato IS NULL
     OR attore IS NULL THEN
    RAISE EXCEPTION
      'lo stato del bando % è pubblico '
      '(% → %): si cambia solo con '
      'bando_registra_evento/'
      'bando_applica_evento, mai con un '
      'UPDATE diretto',
      OLD.id, OLD.stato_bando,
      NEW.stato_bando
      USING ERRCODE = '23514';
  END IF;

  IF NEW.stato_bando_evento_id
     IS DISTINCT FROM
     evento_dichiarato::bigint THEN
    RAISE EXCEPTION
      'bando %: bandi.evento_id dichiara '
      '% ma stato_bando_evento_id vale %',
      OLD.id, evento_dichiarato,
      NEW.stato_bando_evento_id
      USING ERRCODE = '23514';
  END IF;

  IF NOT public.bando_transizione_ammessa(
           OLD.stato_bando,
           NEW.stato_bando, attore) THEN
    RAISE EXCEPTION
      'transizione non ammessa per «%»: '
      '% → % (bando %). La lista bianca è '
      'bando_transizione.',
      attore, OLD.stato_bando,
      NEW.stato_bando, OLD.id
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION
  public.bando_stato_solo_via_evento()
  FROM PUBLIC, anon, authenticated;


-- ------------------------------------------
-- 5. Le quattro righe della lista bianca
-- ------------------------------------------
DELETE FROM public.bando_transizione
 WHERE da = 'sospeso'
   AND a = 'chiuso'
   AND attore = 'worker'
   AND evento = 'chiusura';
DELETE FROM public.bando_transizione
 WHERE da = 'revocato'
   AND a = 'aperto'
   AND attore = 'worker'
   AND evento = 'annullamento_revoca';
DELETE FROM public.bando_transizione
 WHERE da = 'revocato'
   AND a = 'chiuso'
   AND attore = 'worker'
   AND evento = 'annullamento_revoca';
DELETE FROM public.bando_transizione
 WHERE da = 'revocato'
   AND a = 'in apertura prossimamente'
   AND attore = 'worker'
   AND evento = 'annullamento_revoca';


-- ------------------------------------------
-- 5-bis. L'indice di dedup della 02
-- ------------------------------------------
-- Con correzione_redazionale di nuovo
-- dentro il dedup, solo se nessun gruppo
-- di correzioni lo violerebbe (gli eventi
-- non si cancellano).
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
      FROM public.bando_evento
     WHERE tipo = 'correzione_redazionale'
     GROUP BY bando_id, tipo,
       coalesce(campo, ''),
       md5(coalesce(valore_dopo::text,
                    '')),
       coalesce(data_evento,
         (rilevato_at AT TIME ZONE
          'Europe/Rome')::date)
    HAVING count(*) > 1)
  THEN
    RAISE NOTICE
      'rollback 14: correzioni della '
      'redazione ripetute nello stesso '
      'giorno, resta l''indice di dedup '
      'della 14';
  ELSE
    DROP INDEX IF EXISTS
      public.bando_evento_dedup_uidx;
    CREATE UNIQUE INDEX
      bando_evento_dedup_uidx
      ON public.bando_evento (
        bando_id,
        tipo,
        coalesce(campo, ''),
        md5(coalesce(valore_dopo::text,
                     '')),
        coalesce(data_evento,
          (rilevato_at AT TIME ZONE
           'Europe/Rome')::date)
      )
      WHERE tipo NOT IN (
        'fusione', 'separazione',
        'cambio_slug', 'ritiro',
        'segnale_fonte',
        'sparito_dalla_fonte',
        'elaborazione_bloccata',
        'fonte_ufficiale_non_trovata',
        'possibile_doppione',
        'preavviso_collegato');
  END IF;
END $$;


-- ------------------------------------------
-- 6. Le colonne della marcatura
-- ------------------------------------------
ALTER TABLE public.bando_evento
  DROP CONSTRAINT IF EXISTS
    bando_evento_scartato_at_check,
  DROP CONSTRAINT IF EXISTS
    bando_evento_scartato_per_check,
  DROP COLUMN IF EXISTS
    scartato_dettaglio,
  DROP COLUMN IF EXISTS scartato_at,
  DROP COLUMN IF EXISTS scartato_per;


-- ------------------------------------------
-- 7. Verifica (si ferma al primo errore)
-- ------------------------------------------
DO $$
DECLARE
  v_n bigint;
BEGIN
  SELECT count(*) INTO v_n
    FROM public.bando_transizione;
  IF v_n <> 24 THEN
    RAISE EXCEPTION
      'rollback 14: la lista bianca ha % '
      'righe, attese 24', v_n;
  END IF;
  IF to_regprocedure(
       'public.bando_correggi_stato('
       || 'integer, text, text)')
     IS NOT NULL
     OR to_regprocedure(
       'public.bando_capacita_'
       || 'sospensioni()') IS NOT NULL
  THEN
    RAISE EXCEPTION
      'rollback 14: una funzione è '
      'rimasta';
  END IF;
  IF EXISTS (
    SELECT 1
      FROM information_schema.columns c
     WHERE c.table_schema = 'public'
       AND c.table_name = 'bando_evento'
       AND c.column_name LIKE 'scartato%')
  THEN
    RAISE EXCEPTION
      'rollback 14: una colonna è '
      'rimasta';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_catalog.pg_proc p
     WHERE p.oid IN (
       to_regprocedure(
         'public.bando_applica_evento'
         || '(bigint)'),
       to_regprocedure(
         'public.bando_stato_solo_'
         || 'via_evento()'))
       AND position('v11_14' IN p.prosrc)
           > 0)
  THEN
    RAISE EXCEPTION
      'rollback 14: un blocco v11_14 è '
      'rimasto';
  END IF;
  IF NOT coalesce((
       public.bando_capacita_eventi()
       ->> 'traduce_stato_proposto')
       ::boolean, false) THEN
    RAISE EXCEPTION
      'rollback 14: la RPC non traduce '
      'più stato_proposto';
  END IF;
  IF to_regclass(
       'public.bando_evento_dedup_uidx')
     IS NULL THEN
    RAISE EXCEPTION
      'rollback 14: manca l''indice di '
      'dedup degli eventi';
  END IF;
  RAISE NOTICE
    'rollback 14: verifica superata';
END $$;

COMMIT;

-- ==========================================
-- Verifica (sola lettura)
-- ==========================================
-- 1) select count(*)
--      from bando_transizione;
--    -- atteso: 24
-- 2) select public.bando_capacita_eventi();
--    -- atteso: {"stati_cinque": true,
--    --   "traduce_stato_proposto": true}
-- 3) select to_regprocedure(
--      'public.bando_capacita_'
--      || 'sospensioni()');
--    -- atteso: NULL
-- ==========================================
