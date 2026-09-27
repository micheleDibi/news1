-- ============================================================================
-- bando_v11_11_traduzione_stato_proposto_rollback.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Rimette `bando_applica_evento` com'era nella 04 (senza la traduzione di
--   `stato_proposto`) e toglie il marcatore `bando_capacita_eventi()`.
--
-- Fase: (b) — rientro. Va applicato PRIMA di un eventuale rollback della 04.
--
-- Precondizioni
--   * nessuna oltre la 04 (la guardia qui sotto la controlla).
--
-- Rompe BandoFit? NO.
--
-- Effetto sul codice
--   Senza il marcatore la guardia di `applica-eventi` torna a SALTARE gli
--   eventi con `stato_proposto` (li conta come `in_attesa_traduzione`, non li
--   manda alla RPC e non li annota): nessuno li brucia. Torna anche a
--   considerare assente il CHECK a cinque stati, quindi i rifiuti non vengono
--   annotati nemmeno con MONITOR_STATI_ESTESI=true.
--
-- COSA NON È REVERSIBILE
--   I bandi già portati a `sospeso` o `revocato` da eventi tradotti restano
--   così, e quegli eventi restano applicati. Per riportarli indietro serve una
--   decisione del committente (vedi il rollback della 06).
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'INTERO file, poi il blocco «Verifica».
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
  IF to_regprocedure('public.bando_applica_evento(bigint)') IS NULL THEN
    RAISE EXCEPTION
      'manca bando_applica_evento: la 04 non è applicata, non c''è niente da rimettere';
  END IF;
END $$;

DROP FUNCTION IF EXISTS public.bando_capacita_eventi();

-- La funzione della 04, ricopiata carattere per carattere
-- (`tests/test_traduzione_stato_proposto_sql.py` lo controlla).

CREATE OR REPLACE FUNCTION public.bando_applica_evento(p_evento_id bigint)
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
  IF NOT ( session_user IN ('postgres','supabase_admin')
        OR coalesce(nullif(current_setting('request.jwt.claims', true),'')::json->>'role','') = 'service_role' )
  THEN RAISE EXCEPTION 'non autorizzato' USING ERRCODE = '42501'; END IF;

  SELECT * INTO e FROM public.bando_evento WHERE id = p_evento_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'evento % inesistente', p_evento_id USING ERRCODE = '23503';
  END IF;

  -- Idempotente: un evento si applica una volta sola.
  IF e.applicato THEN
    RETURN false;
  END IF;

  campi := CASE
    WHEN jsonb_typeof(e.valore_dopo) = 'object' THEN e.valore_dopo
    WHEN e.campo IS NOT NULL AND e.valore_dopo IS NOT NULL
      THEN jsonb_build_object(e.campo, e.valore_dopo)
    ELSE '{}'::jsonb
  END;

  campi := campi - ARRAY(
    SELECT k FROM jsonb_object_keys(campi) AS k
     WHERE k NOT IN ('stato_bando', 'data_pubblicazione',
                     'data_apertura', 'ora_apertura',
                     'data_scadenza', 'ora_scadenza')
  );

  -- Eventi senza effetto sulle colonne (graduatoria, esito, faq,
  -- nuovo_allegato, fusione…): si marcano applicati lo stesso, altrimenti
  -- tornerebbero in coda a ogni giro di `applica-eventi`.
  IF campi = '{}'::jsonb THEN
    UPDATE public.bando_evento
       SET applicato = true, applicato_at = now()
     WHERE id = e.id;
    RETURN true;
  END IF;

  stato_nuovo    := campi ->> 'stato_bando';
  tocca_apertura := campi ?| ARRAY['data_apertura', 'ora_apertura'];
  tocca_scadenza := campi ?| ARRAY['data_scadenza', 'ora_scadenza'];

  SELECT * INTO riga FROM public.bando WHERE id = e.bando_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'bando % inesistente', e.bando_id USING ERRCODE = '23503';
  END IF;

  -- La lista bianca si controlla QUI, prima dell'UPDATE: il messaggio è
  -- migliore di quello del trigger e — soprattutto — lascia al blocco
  -- EXCEPTION più sotto un solo caso possibile, il CHECK della colonna.
  -- Il trigger resta la garanzia per chi non passa da questa RPC.
  IF campi ? 'stato_bando'
     AND riga.pubblicato
     AND stato_nuovo IS DISTINCT FROM riga.stato_bando
     AND NOT public.bando_transizione_ammessa(riga.stato_bando, stato_nuovo, e.origine)
  THEN
    RAISE EXCEPTION
      'evento % (%): transizione non ammessa per «%»: % → % (bando %). La lista bianca è bando_transizione.',
      e.id, e.tipo, e.origine, riga.stato_bando, stato_nuovo, riga.id
      USING ERRCODE = '23514';
  END IF;

  -- §3.3: `pub <= scad` va verificata QUI. Il CHECK
  -- `bando_dates_consistency_check` è PREESISTENTE (schema.sql:187) e, se
  -- scatta dentro l'UPDATE qui sotto, risale al chiamante come 23514 e ferma
  -- l'intero lotto di `applica-eventi` — a ogni riesecuzione, perché l'evento
  -- resta non applicato e torna in coda. Con operandi NULL il confronto vale
  -- NULL e il controllo passa (una data mancante non è un'incoerenza).
  IF (CASE WHEN campi ? 'data_pubblicazione' THEN (campi ->> 'data_pubblicazione')::date
           ELSE riga.data_pubblicazione END)
     > (CASE WHEN campi ? 'data_scadenza' THEN (campi ->> 'data_scadenza')::date
             ELSE riga.data_scadenza END)
  THEN
    -- Una sola segnalazione per evento bloccato: `elaborazione_bloccata` è
    -- fuori dal dedup parziale della 02, quindi senza questa guardia ogni
    -- giro di `applica-eventi` ne aggiungerebbe una copia.
    IF NOT EXISTS (
      SELECT 1 FROM public.bando_evento x
       WHERE x.bando_id = e.bando_id
         AND x.tipo = 'elaborazione_bloccata'
         AND x.riferisce_a = e.id
    ) THEN
      PERFORM public.bando_registra_evento(
        e.bando_id, 'elaborazione_bloccata', 'pipeline', 'date',
        jsonb_build_object('evento_id', e.id, 'motivo', 'data_pubblicazione > data_scadenza'),
        NULL, NULL, NULL, false, p_riferisce_a => e.id);
    END IF;
    RAISE NOTICE 'evento % (%): date incoerenti (pubblicazione > scadenza). Evento lasciato non applicato.',
      e.id, e.tipo;
    RETURN false;
  END IF;

  PERFORM set_config('bandi.evento_id', e.id::text, true);
  PERFORM set_config('bandi.attore', e.origine, true);

  BEGIN
    UPDATE public.bando b SET
      stato_bando =
        CASE WHEN campi ? 'stato_bando' THEN stato_nuovo ELSE b.stato_bando END,
      stato_bando_evento_id =
        CASE WHEN campi ? 'stato_bando' THEN e.id ELSE b.stato_bando_evento_id END,
      stato_bando_verificato =
        CASE WHEN campi ? 'stato_bando' THEN (e.verificato AND stato_nuovo IS NOT NULL)
             ELSE b.stato_bando_verificato END,

      data_pubblicazione =
        CASE WHEN campi ? 'data_pubblicazione' THEN (campi ->> 'data_pubblicazione')::date
             ELSE b.data_pubblicazione END,
      data_pubblicazione_evento_id =
        CASE WHEN campi ? 'data_pubblicazione' THEN e.id ELSE b.data_pubblicazione_evento_id END,
      data_pubblicazione_verificata =
        CASE WHEN campi ? 'data_pubblicazione'
             THEN (e.verificato AND (campi ->> 'data_pubblicazione') IS NOT NULL)
             ELSE b.data_pubblicazione_verificata END,

      data_apertura =
        CASE WHEN campi ? 'data_apertura' THEN (campi ->> 'data_apertura')::date
             ELSE b.data_apertura END,
      ora_apertura =
        CASE WHEN campi ? 'ora_apertura' THEN (campi ->> 'ora_apertura')::time
             ELSE b.ora_apertura END,
      -- L'evento_id copre l'intero gruppo (data + ora): senza, il trigger
      -- `trg_bando_provenienza_date` della 03 azzererebbe il flag quando
      -- l'evento cambia solo l'ora.
      data_apertura_evento_id =
        CASE WHEN tocca_apertura THEN e.id ELSE b.data_apertura_evento_id END,
      data_apertura_verificata =
        CASE WHEN tocca_apertura
             THEN (e.verificato
                   AND (CASE WHEN campi ? 'data_apertura' THEN (campi ->> 'data_apertura')::date
                             ELSE b.data_apertura END) IS NOT NULL)
             ELSE b.data_apertura_verificata END,

      data_scadenza =
        CASE WHEN campi ? 'data_scadenza' THEN (campi ->> 'data_scadenza')::date
             ELSE b.data_scadenza END,
      ora_scadenza =
        CASE WHEN campi ? 'ora_scadenza' THEN (campi ->> 'ora_scadenza')::time
             ELSE b.ora_scadenza END,
      data_scadenza_evento_id =
        CASE WHEN tocca_scadenza THEN e.id ELSE b.data_scadenza_evento_id END,
      data_scadenza_verificata =
        CASE WHEN tocca_scadenza
             THEN (e.verificato
                   AND (CASE WHEN campi ? 'data_scadenza' THEN (campi ->> 'data_scadenza')::date
                             ELSE b.data_scadenza END) IS NOT NULL)
             ELSE b.data_scadenza_verificata END
    WHERE b.id = e.bando_id;
  EXCEPTION WHEN check_violation THEN
    -- PRIMA di qualunque altra cosa: le due GUC sono state accese fuori da
    -- questo blocco, quindi la sua rollback NON le spegne. Se il chiamante
    -- cattura l'eccezione in un blocco esterno restano accese fino a fine
    -- transazione, ed è esattamente ciò che il commento più sotto dice di
    -- voler evitare: un UPDATE diretto ne approfitterebbe.
    PERFORM set_config('bandi.evento_id', '', true);
    PERFORM set_config('bandi.attore', '', true);

    -- Prima della migrazione 06 il CHECK di `stato_bando` ha tre valori:
    -- `sospensione` e `revoca` restano `applicato=false` (§4, A30) e li
    -- riprenderà `applica-eventi` dopo la 06. La transizione è già stata
    -- controllata qui sopra, quindi questo è l'unico caso da assorbire: ogni
    -- altra violazione risale intatta al chiamante.
    IF campi ? 'stato_bando' AND stato_nuovo IN ('sospeso', 'revocato') THEN
      RAISE NOTICE
        'evento % (%): la colonna stato_bando non ammette ancora «%» (migrazione 06 non applicata). Evento lasciato non applicato.',
        e.id, e.tipo, stato_nuovo;
      RETURN false;
    END IF;
    RAISE;
  END;

  -- L'intenzione vale per una sola scrittura: si spegne subito, così nella
  -- stessa transazione un UPDATE diretto non può approfittarne.
  PERFORM set_config('bandi.evento_id', '', true);
  PERFORM set_config('bandi.attore', '', true);

  UPDATE public.bando_evento
     SET applicato = true, applicato_at = now()
   WHERE id = e.id;

  RETURN true;
END;
$$;

COMMENT ON FUNCTION public.bando_applica_evento(bigint) IS
  'Riversa valore_dopo nelle colonne di bando (stato, date, ore) e marca l''evento applicato. true = applicato adesso; false = già applicato o stato non ancora ammesso dal CHECK.';

REVOKE ALL ON FUNCTION public.bando_applica_evento(bigint) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_applica_evento(bigint) TO service_role;

COMMIT;

-- ============================================================================
-- Verifica
-- ============================================================================
-- 1) Il marcatore non c'è più.
--      SELECT to_regprocedure('public.bando_capacita_eventi()');
--      -- atteso: NULL
--
-- 2) La RPC non traduce più.
--      SELECT position('stato_proposto' IN prosrc) > 0 FROM pg_proc
--       WHERE oid = 'public.bando_applica_evento(bigint)'::regprocedure;
--      -- atteso: false
--
-- 3) Privilegi e overload come dopo la 04: query 3 e 4 della Verifica della 11
--    (senza la colonna del marcatore).
-- ============================================================================
