-- ============================================================================
-- bando_v11_11_traduzione_stato_proposto.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   `bando_applica_evento` (04) riversa in colonna solo sei chiavi di
--   `valore_dopo`: stato_bando, data_pubblicazione, data_apertura,
--   ora_apertura, data_scadenza, ora_scadenza. Finché MONITOR_STATI_ESTESI è
--   falso, però, il monitor registra sospensione e revoca con
--   `valore_dopo = {"stato_proposto": "sospeso"|"revocato"}` (A30). La RPC
--   scarta quella chiave, trova `campi = {}`, marca l'evento `applicato=true`
--   e restituisce true: lo stato del bando non cambia, `applica-eventi` conta
--   l'evento come applicato e lo rende leggibile, e l'evento non torna più in
--   coda. `valore_dopo` è immutabile (z_evento_immutabile, 02), quindi la
--   correzione non può stare nella riga: deve stare nella RPC.
--
--   Questo file fa due cose:
--     1. ridefinisce `bando_applica_evento` identica alla 04 più un solo
--        blocco (fra `-- >>> v11_11` e `-- <<< v11_11`) che traduce
--        `stato_proposto` in `stato_bando` per le coppie sospensione/sospeso e
--        revoca/revocato, e solo se l'evento non porta già uno `stato_bando`;
--     2. crea `bando_capacita_eventi()`, il marcatore che la guardia di
--        `applica-eventi` legge prima di mandare alla RPC un evento con
--        `stato_proposto` (senza la 11 lo salta, lo conta e non lo annota), e
--        che le dice anche se il CHECK a cinque stati della 06 c'è.
--
-- Fase: (b). Nessuna colonna, nessuna tabella, nessuna riga toccata.
--
-- Precondizioni
--   * `bando_v11_04_transizioni.sql` applicata (la guardia qui sotto lo
--     controlla);
--   * la 06 NON serve. Prima della 06 la traduzione è innocua: il CHECK a tre
--     valori rifiuta `sospeso` e `revocato`, il ramo check_violation della
--     RPC restituisce false e l'evento resta NON applicato, come già succede
--     agli eventi che portano `stato_bando`. Applicare la 11 prima della 06 è
--     l'ordine consigliato.
--
-- Rompe BandoFit? NO. Nessuna colonna cambia prima della 06; dopo la 06 la
--   RPC scrive `sospeso`/`revocato`, che è il contratto della 06 (R0-a,
--   confermato il 27/09/2026). news1 non legge nessuno dei due oggetti nuovi.
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'INTERO file, poi il blocco
--   «Verifica post-deploy». Rieseguibile. NON serve riavviare il sender: il
--   marcatore lo legge `applica-eventi`, che è un processo nuovo a ogni
--   lancio. Se `bando_capacita_eventi` non compare fra le RPC di PostgREST,
--   `NOTIFY pgrst, 'reload schema';`.
--
-- AVVERTENZA — la 04 è rieseguibile (04:57-60). Rieseguirla dopo questo file
--   toglie la traduzione. Il marcatore legge il corpo vivo della funzione,
--   quindi in quel caso risponde `traduce_stato_proposto: false` e la guardia
--   torna a saltare gli eventi con `stato_proposto`: niente si brucia, ma va
--   riapplicata la 11.
--
-- COSA NON È REVERSIBILE
--   Niente di questo file. Gli eventi «bruciati» PRIMA della 11 (applicato=true
--   con lo stato intatto) non si recuperano da qui: vedi la Verifica 5. Il
--   27/09/2026 non ce n'era nessuno (0 eventi con `stato_proposto` a DB).
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';

-- ---------------------------------------------------------------------------
-- 0. Precondizione
-- ---------------------------------------------------------------------------

DO $$
BEGIN
  IF to_regprocedure('public.bando_applica_evento(bigint)') IS NULL
     OR to_regclass('public.bando_transizione') IS NULL THEN
    RAISE EXCEPTION
      'manca bando_applica_evento o bando_transizione: applicare prima bando_v11_04_transizioni.sql';
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 1. `bando_applica_evento`: la 04 più il blocco v11_11
-- ---------------------------------------------------------------------------
-- Stessa firma: una firma diversa creerebbe un overload e renderebbe ambigua
-- la chiamata `bando_applica_evento(evento_id)` dentro `bando_registra_evento`
-- (04:719). Tutto il resto è ricopiato dalla 04 carattere per carattere:
-- `tests/test_traduzione_stato_proposto_sql.py` lo controlla.

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

  -- >>> v11_11 — traduzione di `stato_proposto` (A30, §6.2)
  -- Finché MONITOR_STATI_ESTESI è falso il monitor registra sospensione e
  -- revoca con `valore_dopo = {"stato_proposto": …}` e non con `stato_bando`
  -- (scraper_bandi/app/eventi.py, riga_evento). Il filtro qui sopra toglie
  -- quella chiave: senza questo blocco l'evento cadrebbe nel ramo «senza
  -- effetto sulle colonne», verrebbe marcato applicato con lo stato intatto e
  -- non tornerebbe più in coda (`valore_dopo` è immutabile). Solo sugli
  -- oggetti, solo le due coppie che la macchina a stati produce, e mai sopra
  -- uno `stato_bando` esplicito.
  -- Prima della 06 il CHECK a tre valori rifiuta `sospeso` e `revocato`: il
  -- ramo check_violation più sotto restituisce false e l'evento resta NON
  -- applicato, come già succede agli eventi che portano `stato_bando`.
  IF jsonb_typeof(e.valore_dopo) = 'object'
     AND NOT (campi ? 'stato_bando')
     AND (   (e.tipo = 'sospensione' AND e.valore_dopo ->> 'stato_proposto' = 'sospeso')
          OR (e.tipo = 'revoca'      AND e.valore_dopo ->> 'stato_proposto' = 'revocato'))
  THEN
    campi := campi || jsonb_build_object('stato_bando', e.valore_dopo ->> 'stato_proposto');
  END IF;
  -- <<< v11_11

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
  'Riversa valore_dopo nelle colonne di bando (stato, date, ore) e marca l''evento applicato. Dalla migrazione 11 traduce stato_proposto in stato_bando per sospensione/sospeso e revoca/revocato. true = applicato adesso; false = già applicato o stato non ancora ammesso dal CHECK.';

REVOKE ALL ON FUNCTION public.bando_applica_evento(bigint) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_applica_evento(bigint) TO service_role;

-- ---------------------------------------------------------------------------
-- 2. Il marcatore che legge `applica-eventi`
-- ---------------------------------------------------------------------------
-- Via PostgREST, con la service key, si vedono solo tabelle, colonne e
-- `/rpc/<nome>` eseguibili: `pg_proc` e i CHECK no. Per questo le due
-- informazioni che servono alla guardia passano da una funzione in sola
-- lettura. `SECURITY INVOKER` (il default): `pg_proc` e `pg_constraint` sono
-- leggibili da ogni ruolo.

CREATE OR REPLACE FUNCTION public.bando_capacita_eventi()
RETURNS jsonb
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
  SELECT jsonb_build_object(
    -- La traduzione c'è se il corpo VIVO della RPC la contiene. La 04 è
    -- rieseguibile: rilanciata dopo questo file toglierebbe il blocco v11_11
    -- senza avvisare, e un marcatore che si limitasse a esistere mentirebbe.
    'traduce_stato_proposto', coalesce((
      SELECT position('stato_proposto' IN p.prosrc) > 0
        FROM pg_catalog.pg_proc p
       WHERE p.oid = to_regprocedure('public.bando_applica_evento(bigint)')::oid
    ), false),
    -- I cinque stati ci sono se OGNI CHECK dello stato, riconosciuto dal testo
    -- dell'enumerazione come fa la 06, ammette `sospeso` e `revocato`. Senza
    -- righe `bool_and` vale NULL: nel dubbio, falso.
    'stati_cinque', (
      SELECT coalesce(bool_and(v.d ILIKE '%''sospeso''%' AND v.d ILIKE '%''revocato''%'), false)
        FROM (SELECT pg_catalog.pg_get_constraintdef(c.oid) AS d
                FROM pg_catalog.pg_constraint c
               WHERE c.conrelid = 'public.bando'::regclass
                 AND c.contype = 'c'
                 AND c.conname NOT IN ('bando_pubblicato_implica_completed', 'bando_provenienza_stato')
             ) AS v
       WHERE v.d ILIKE '%in apertura prossimamente%'
    )
  );
$$;

COMMENT ON FUNCTION public.bando_capacita_eventi() IS
  'Marcatore per applica-eventi: traduce_stato_proposto = il corpo vivo di bando_applica_evento traduce stato_proposto (migrazione 11); stati_cinque = il CHECK di stato_bando ammette sospeso e revocato (migrazione 06).';

REVOKE ALL ON FUNCTION public.bando_capacita_eventi() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_capacita_eventi() TO service_role;

COMMIT;

-- ============================================================================
-- Verifica post-deploy
-- ============================================================================
-- 1) Il marcatore risponde.
--      SELECT public.bando_capacita_eventi();
--      -- atteso: {"stati_cinque": false, "traduce_stato_proposto": true}
--      --   prima della 06; dopo la 06 anche "stati_cinque": true
--
-- 2) La RPC è ancora SECURITY DEFINER con il search_path della 04.
--      SELECT p.prosecdef, p.proconfig FROM pg_proc p
--       WHERE p.oid = 'public.bando_applica_evento(bigint)'::regprocedure;
--      -- atteso: true, {"search_path=public, pg_temp"}
--
-- 3) Solo service_role esegue le due funzioni.
--      SELECT r,
--             has_function_privilege(r, 'public.bando_applica_evento(bigint)', 'EXECUTE') AS rpc,
--             has_function_privilege(r, 'public.bando_capacita_eventi()', 'EXECUTE') AS marcatore
--        FROM unnest(ARRAY['anon','authenticated','service_role']) AS r;
--      -- atteso: anon f f; authenticated f f; service_role t t
--      -- e la query 9 di RIPRESA §3.2 dà ancora le sole 3 righe della vista
--
-- 4) Nessun overload.
--      SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
--       WHERE n.nspname = 'public' AND p.proname = 'bando_applica_evento';
--      -- atteso: 1
--
-- 5) Eventi già «bruciati» prima della 11: applicati con lo stato intatto.
--      SELECT e.id, e.bando_id, e.tipo, e.valore_dopo, e.applicato_at, b.stato_bando
--        FROM bando_evento e JOIN bando b ON b.id = e.bando_id
--       WHERE jsonb_typeof(e.valore_dopo) = 'object' AND e.valore_dopo ? 'stato_proposto'
--         AND e.applicato AND b.stato_bando_evento_id IS DISTINCT FROM e.id;
--      -- atteso: 0 righe (0 anche il 27/09/2026). Se ce ne sono: NON si
--      --   rimettono in coda da soli; è una decisione del committente
--      --   (`applicato` e `applicato_at` sono fra le colonne che
--      --   z_evento_immutabile lascia cambiare, il cursore invece resta).
--
-- 6) Coda che la 11 sblocca (informativa).
--      SELECT tipo, valore_dopo ->> 'stato_proposto' AS proposto, leggibile, count(*)
--        FROM bando_evento
--       WHERE jsonb_typeof(valore_dopo) = 'object' AND valore_dopo ? 'stato_proposto'
--         AND verificato AND NOT applicato
--       GROUP BY 1, 2, 3;
--
-- 7) Eventi che la RPC rifiuterà con 23514 perché lo stato del bando è cambiato
--    nel frattempo (per esempio il cron lo ha chiuso). `applica-eventi` li
--    conterebbe come `non_tentati` a ogni lancio: vanno guardati a mano.
--      SELECT e.id, e.bando_id, e.tipo, b.stato_bando
--        FROM bando_evento e JOIN bando b ON b.id = e.bando_id
--       WHERE e.tipo IN ('sospensione', 'revoca') AND e.verificato AND NOT e.applicato
--         AND b.pubblicato
--         AND b.stato_bando IS DISTINCT FROM coalesce(e.valore_dopo ->> 'stato_bando',
--                                                     e.valore_dopo ->> 'stato_proposto')
--         AND NOT public.bando_transizione_ammessa(
--               b.stato_bando,
--               coalesce(e.valore_dopo ->> 'stato_bando', e.valore_dopo ->> 'stato_proposto'),
--               e.origine);
--      -- atteso: 0
--
-- 8) Prova facoltativa su una riga vera, in una transazione da ANNULLARE e a
--    traffico basso (la riga del bando resta bloccata fino al ROLLBACK). :b è
--    un bando pubblicato e aperto; :id è l'id restituito dalla prima SELECT.
--      BEGIN;
--        SELECT public.bando_registra_evento(:b, 'sospensione', 'worker', NULL,
--               '{"stato_proposto": "sospeso"}'::jsonb, NULL, NULL, current_date,
--               false, false, false);
--        SELECT public.bando_applica_evento(:id);
--        SELECT stato_bando FROM bando WHERE id = :b;
--        SELECT applicato FROM bando_evento WHERE id = :id;
--        -- atteso prima della 06: false, 'aperto', false
--        -- atteso dopo la 06:     true,  'sospeso', true
--      ROLLBACK;
-- ============================================================================
