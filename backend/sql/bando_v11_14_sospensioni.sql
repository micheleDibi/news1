-- ==========================================
-- bando_v11_14_sospensioni.sql
-- DB bandi: sospensione e revoca
-- ==========================================
-- Scritto l'01/10/2026 da «db» (giro 3,
-- G3-D2). Contratto interno:
-- docs/contracts/bandi-giro-3.md §14.
--
-- Ordine di applicazione: DOPO la 13
--   (01 → 02 → seed → 03 → 04 → 05 → 08 →
--   09 → 10 → 11 → 06 → 12 → 13 → 14).
--   La 07 resta indipendente.
--
-- Scopo
--   Chiude i buchi di RIPRESA §4.1 i
--   prima di attivare sospensione e
--   revoca:
--   1. lista bianca, quattro righe
--      (generate da tests/stato-bando/
--      casi.json): sospeso → chiuso con
--      `chiusura` del worker; revocato →
--      aperto | chiuso | in apertura con
--      `annullamento_revoca` del worker;
--   2. dal sospeso e dal revocato la RPC
--      esige anche l'evento della riga
--      (dal revocato si esce SOLO con
--      annullamento_revoca); per un
--      annullamento_revoca senza stato la
--      RPC calcola lo stato dalle date;
--   3. `bando_correggi_stato(id, stato,
--      nota)`: la correzione della
--      redazione fra i cinque stati di un
--      pubblicato, con un evento
--      `correzione_redazionale`. Nessuna
--      riga `redazione` in lista bianca: il
--      trigger la lascia passare solo se a
--      chiamarlo è questa RPC;
--   4. evento «superato»: un evento del
--      worker che cambia lo stato di un
--      pubblicato non si applica se lo
--      stesso bando ha già applicato un
--      evento di stato più recente del
--      worker o della redazione, per
--      (data_evento, id), con la data mai
--      oltre il giorno di rilevamento; il
--      cron non conta; una proroga, una
--      riapertura o una rettifica che porta
--      una scadenza non ancora passata non
--      la supera una chiusura;
--   5. tre colonne su bando_evento
--      (scartato_per, scartato_at,
--      scartato_dettaglio): un evento
--      superato o con una transizione non
--      ammessa resta NON applicato e viene
--      marcato, e la RPC risponde false
--      (prima: 23514 e l'evento tornava in
--      coda a ogni lancio);
--   6. `bando_capacita_sospensioni()`: il
--      marcatore che il codice legge prima
--      di attivare sospensione e revoca;
--   7. l'indice di dedup degli eventi
--      (stesso nome e stessa chiave della
--      02) esclude anche
--      correzione_redazionale.
--   La regola di stato_effettivo NON
--   cambia.
--
-- Precondizioni (le guardie le
--   controllano): 04, 06, 11 e 13
--   applicate.
--
-- Rompe BandoFit? NO. Le tre colonne
--   nuove non sono concesse ad anon;
--   nessuna colonna della vista cambia.
--   La correzione della redazione crea un
--   evento pubblico correzione_redazionale
--   con in_aggiornamenti=false, come già
--   previsto dal contratto.
--
-- Breaking change (voluto): una
--   transizione non ammessa da un
--   pubblicato NON solleva più 23514 dalla
--   RPC: l'evento resta, marcato
--   `transizione_non_ammessa`, e la RPC
--   risponde false. Un UPDATE diretto
--   dello stato solleva ancora 23514 (il
--   trigger non cambia per questo).
--
-- Come si applica
--   SQL Editor: incollare ed eseguire
--   l'INTERO file, fuori dai giri e senza
--   applica-eventi in corso (la guardia
--   rifiuta se il lock «monitor» è
--   tenuto). Rieseguibile. Poi il blocco
--   «Verifica post-deploy» e la
--   «Riconciliazione». Poi riavviare il
--   sender: lo schema (colonne e RPC
--   esposte) si legge una volta per
--   processo, e senza riavvio il codice
--   non vede né il marcatore né le
--   colonne. Basta il riavvio del deploy
--   del giro 3, se la 14 si applica
--   prima. Se bando_capacita_sospensioni
--   non compare fra le RPC di PostgREST:
--   NOTIFY pgrst, 'reload schema';
--
-- DOPO QUESTO FILE NON RIESEGUIRE:
--   * la 04 e la 11: rimettono la RPC (e
--     la 04 il trigger) senza i blocchi
--     v11_14. Niente si brucia, perché il
--     marcatore torna false e il codice
--     rimette sospensione e revoca in
--     ombra; si rimedia rieseguendo la 14;
--   * la 13: la sua verifica V2 conta 24
--     righe di lista bianca e
--     annullerebbe il file (dopo la 14
--     sono 28).
--   Rollback in ordine inverso: prima
--   quello della 14.
--
-- COSA NON È REVERSIBILE
--   Il rollback toglie le tre colonne:
--   le marcature si perdono e quegli
--   eventi tornano in coda. Gli stati già
--   cambiati da eventi o correzioni
--   restano come sono.
-- ==========================================

BEGIN;

SET LOCAL lock_timeout = '5s';


-- ------------------------------------------
-- 1. Guardie
-- ------------------------------------------
DO $$
BEGIN
  IF to_regprocedure(
       'public.bando_applica_evento'
       || '(bigint)') IS NULL
     OR to_regclass(
       'public.bando_transizione') IS NULL
  THEN
    RAISE EXCEPTION
      'manca la 04 '
      '(bando_v11_04_transizioni.sql)';
  END IF;
  IF to_regprocedure(
       'public.bando_capacita_eventi()')
     IS NULL THEN
    RAISE EXCEPTION
      'manca la 11 (bando_v11_11_'
      'traduzione_stato_proposto.sql)';
  END IF;
  IF NOT coalesce((
       public.bando_capacita_eventi()
       ->> 'stati_cinque')::boolean,
       false) THEN
    RAISE EXCEPTION
      'manca la 06: il CHECK di '
      'stato_bando non ammette sospeso '
      'e revocato';
  END IF;
  IF to_regprocedure(
       'public.bando_stato_da_verificare('
       || 'text, date, boolean, time, '
       || 'date, time, timestamptz, date, '
       || 'date, text, text, timestamptz, '
       || 'text, timestamptz, timestamptz, '
       || 'timestamptz)') IS NULL
     OR NOT EXISTS (
       SELECT 1
         FROM public.bando_transizione t
        WHERE t.da
              = 'in apertura prossimamente'
          AND t.a = 'chiuso'
          AND t.attore = 'worker'
          AND t.evento = 'chiusura')
  THEN
    RAISE EXCEPTION
      'manca la 13 (bando_v11_13_'
      'stato_da_verificare.sql)';
  END IF;
  -- applica-eventi e il monitor tengono
  -- il lock «monitor»: un lancio in corso
  -- ha letto i marcatori all'avvio. Due IF
  -- annidati: PL/pgSQL pianifica l'intera
  -- espressione.
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
-- 2. Le colonne della marcatura
-- ------------------------------------------
-- Nessun default: l'ALTER non riscrive la
-- tabella. z_evento_immutabile (02) è una
-- lista nera di colonne, quindi queste
-- restano modificabili: si rimette in coda
-- un evento azzerando le tre colonne.
-- Nessun grant ad anon: i grant di colonna
-- della 02 non le nominano.
ALTER TABLE public.bando_evento
  ADD COLUMN IF NOT EXISTS
    scartato_per text,
  ADD COLUMN IF NOT EXISTS
    scartato_at timestamptz,
  ADD COLUMN IF NOT EXISTS
    scartato_dettaglio jsonb;

ALTER TABLE public.bando_evento
  DROP CONSTRAINT IF EXISTS
    bando_evento_scartato_per_check;
ALTER TABLE public.bando_evento
  ADD CONSTRAINT
    bando_evento_scartato_per_check
  CHECK (scartato_per IS NULL
         OR scartato_per IN (
           'superato',
           'transizione_non_ammessa'));

ALTER TABLE public.bando_evento
  DROP CONSTRAINT IF EXISTS
    bando_evento_scartato_at_check;
ALTER TABLE public.bando_evento
  ADD CONSTRAINT
    bando_evento_scartato_at_check
  CHECK ((scartato_per IS NULL)
         = (scartato_at IS NULL));

COMMENT ON COLUMN
  public.bando_evento.scartato_per IS
  'Migrazione 14: superato | '
  'transizione_non_ammessa. Un evento '
  'marcato non si applica e non torna in '
  'coda; si rimette in coda azzerando '
  'scartato_per, scartato_at e '
  'scartato_dettaglio.';
COMMENT ON COLUMN
  public.bando_evento.scartato_dettaglio IS
  'Migrazione 14: da, a, attore, evento '
  'e (per superato) l''evento più '
  'recente che lo ha superato.';


-- ------------------------------------------
-- 2-bis. Dedup degli eventi senza le
--        correzioni della redazione
-- ------------------------------------------
-- Stessa chiave e stesso nome dell'indice
-- della 02, più correzione_redazionale fra
-- i tipi esclusi: due correzioni verso lo
-- stesso stato nello stesso giorno sono
-- legittime (corretto, ricorretto, poi di
-- nuovo), e con l'indice della 02 la terza
-- falliva con 23505. Ricostruito a ogni
-- esecuzione: la tabella è piccola.
DROP INDEX IF EXISTS
  public.bando_evento_dedup_uidx;
CREATE UNIQUE INDEX bando_evento_dedup_uidx
  ON public.bando_evento (
    bando_id,
    tipo,
    coalesce(campo, ''),
    md5(coalesce(valore_dopo::text, '')),
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
    'preavviso_collegato',
    'correzione_redazionale');


-- ------------------------------------------
-- 3. Lista bianca: le righe della 14
-- ------------------------------------------
-- >>> TRANSIZIONI delta 14
-- Generato da tests/stato-bando/
-- genera-sql.ts: non modificare a mano.
-- Righe di public.bando_transizione che
-- entrano con la migrazione 14 (campo
-- migrazione di tests/stato-bando/
-- casi.json). Rieseguibile: where not
-- exists come nel seed della 04.
insert into public.bando_transizione
  (da, a, attore, evento, condizione)
select v.da, v.a, v.attore, v.evento,
  v.condizione
from (values
  ('sospeso'::text, 'chiuso'::text,
   'worker'::text, 'chiusura'::text,
   'la pagina ufficiale dichiara '
    || 'chiuso il bando sospeso '
    || '(chiusura dell''ente o termine '
    || 'senza ripresa); gate G1-G9, G7; '
    || 'mai d''ufficio: il cron non '
    || 'tocca un sospeso'),
  ('revocato', 'aperto', 'worker',
   'annullamento_revoca',
   'la fonte ufficiale annulla la '
    || 'revoca; stato di arrivo '
    || 'calcolato dalle date: apertura '
    || 'raggiunta e scadenza non '
    || 'passata; gate G1-G9'),
  ('revocato', 'chiuso', 'worker',
   'annullamento_revoca',
   'la fonte ufficiale annulla la '
    || 'revoca; stato di arrivo '
    || 'calcolato dalle date: scadenza '
    || 'gia passata; gate G1-G9'),
  ('revocato', 'in apertura prossimamente',
   'worker', 'annullamento_revoca',
   'la fonte ufficiale annulla la '
    || 'revoca; stato di arrivo '
    || 'calcolato dalle date: apertura '
    || 'futura; gate G1-G9')
) as v (da, a, attore, evento, condizione)
where not exists (
  select 1 from public.bando_transizione t
  where t.da is not distinct from v.da
    and t.a = v.a
    and t.attore = v.attore
    and t.evento = v.evento
)
on conflict do nothing;
-- <<< TRANSIZIONI delta 14


-- ------------------------------------------
-- 4. bando_applica_evento: la 11 più i
--    blocchi v11_14
-- ------------------------------------------
-- Stessa firma (un overload renderebbe
-- ambigua la chiamata dentro
-- bando_registra_evento). Fuori dai tre
-- blocchi fra `-- >>> v11_14` e
-- `-- <<< v11_14` il corpo è quello della
-- 11, riscritto a righe corte: stessi
-- token, stringhe lunghe spezzate in
-- letterali adiacenti su righe diverse
-- (PostgreSQL li unisce).
-- scraper_bandi/tests/
-- test_sospensioni_sql.py lo controlla.
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

  -- >>> v11_14 (a): evento marcato
  -- Superato o non più ammesso: non si
  -- riprova. false, come per un evento già
  -- applicato.
  IF e.scartato_per IS NOT NULL THEN
    RETURN false;
  END IF;
  -- <<< v11_14 (a)

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

  -- >>> v11_14 (b): annullamento_revoca
  -- Senza uno stato esplicito lo stato di
  -- arrivo si calcola dalle date con la
  -- regola di stato_effettivo: «in
  -- apertura» se c'è una data di apertura
  -- non ancora raggiunta, «chiuso» se la
  -- scadenza è passata, altrimenti
  -- «aperto». Solo se il bando è ancora
  -- revocato; altrimenti campi resta
  -- vuoto e l'evento si marca applicato
  -- senza effetto.
  IF e.tipo = 'annullamento_revoca'
     AND NOT (campi ? 'stato_bando')
  THEN
    campi := campi || coalesce((
      SELECT jsonb_build_object(
               'stato_bando',
               public.bando_stato_effettivo(
                 CASE
                   WHEN x.data_apertura
                        IS NULL
                   THEN 'aperto'
                   ELSE 'in apertura '
                        'prossimamente'
                 END,
                 x.data_apertura,
                 true,
                 x.ora_apertura,
                 x.data_scadenza,
                 x.ora_scadenza,
                 now()))
        FROM public.bando x
       WHERE x.id = e.bando_id
         AND x.stato_bando = 'revocato'),
      '{}'::jsonb);
  END IF;
  -- <<< v11_14 (b)

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

  -- >>> v11_14 (c): superato e non ammessa
  -- Solo per un evento che cambia lo stato
  -- di un pubblicato. Nei due casi
  -- l'evento resta non applicato, si
  -- marca e la RPC risponde false: un
  -- RAISE annullerebbe anche la marcatura
  -- e l'evento tornerebbe in coda a ogni
  -- lancio (RIPRESA §4.1 i, punto 6).
  IF campi ? 'stato_bando'
     AND riga.pubblicato
     AND stato_nuovo
         IS DISTINCT FROM riga.stato_bando
  THEN
    DECLARE
      v_dopo   public.bando_evento;
      -- Un fatto non è più recente del
      -- giorno in cui lo abbiamo visto:
      -- una data_evento nel futuro vale il
      -- giorno di rilevamento (LEAST salta
      -- i NULL).
      v_giorno date := least(
        e.data_evento,
        (e.rilevato_at AT TIME ZONE
         'Europe/Rome')::date);
      v_motivo text;
      v_dett   jsonb;
      v_ok     boolean;
      -- Proroga, riapertura o rettifica
      -- che porta una scadenza non ancora
      -- passata: una chiusura più recente
      -- non la supera, perché chi ha letto
      -- la chiusura non sapeva della
      -- proroga (revisione avversaria,
      -- ciclo 2).
      v_scad   boolean :=
        e.tipo IN ('proroga',
                   'riapertura',
                   'rettifica')
        AND campi ? 'data_scadenza'
        AND (campi ->> 'data_scadenza')
              ::date
            >= (now() AT TIME ZONE
                'Europe/Rome')::date;
    BEGIN
      -- Superato: solo un evento del
      -- worker, e solo da un evento di
      -- stato del worker o della redazione
      -- già applicato. Il cron non conta:
      -- le sue transizioni seguono le date,
      -- e una proroga vera datata prima di
      -- una chiusura automatica deve
      -- riaprire.
      IF e.origine = 'worker' THEN
        SELECT x.* INTO v_dopo
          FROM public.bando_evento x
         WHERE x.bando_id = e.bando_id
           AND x.id <> e.id
           AND x.applicato
           AND x.scartato_per IS NULL
           AND x.origine
               IN ('worker', 'redazione')
           AND (x.campo = 'stato_bando'
                OR x.tipo
                   = 'annullamento_revoca'
                OR (jsonb_typeof(
                      x.valore_dopo)
                      = 'object'
                    AND (x.valore_dopo
                         ? 'stato_bando'
                         OR x.valore_dopo
                         ? 'stato_proposto'
                        )))
           AND NOT (v_scad
                    AND x.tipo = 'chiusura')
           AND (least(
                  x.data_evento,
                  (x.rilevato_at
                   AT TIME ZONE
                   'Europe/Rome')::date),
                x.id)
               > (v_giorno, e.id)
         ORDER BY least(
                    x.data_evento,
                    (x.rilevato_at
                     AT TIME ZONE
                     'Europe/Rome')::date)
                    DESC,
                  x.id DESC
         LIMIT 1;
        IF FOUND THEN
          v_motivo := 'superato';
          v_dett := jsonb_build_object(
            'da', riga.stato_bando,
            'a', stato_nuovo,
            'attore', e.origine,
            'evento', e.tipo,
            'superato_da', v_dopo.id,
            'tipo_dopo', v_dopo.tipo,
            'data_dopo', least(
              v_dopo.data_evento,
              (v_dopo.rilevato_at
               AT TIME ZONE
               'Europe/Rome')::date));
        END IF;
      END IF;

      -- Non ammessa: la lista bianca per
      -- (da, a, attore); dal sospeso e dal
      -- revocato anche per l'evento.
      v_ok :=
        public.bando_transizione_ammessa(
          riga.stato_bando, stato_nuovo,
          e.origine);
      IF v_ok AND riga.stato_bando
                  IN ('sospeso', 'revocato')
      THEN
        v_ok := EXISTS (
          SELECT 1
            FROM public.bando_transizione t
           WHERE t.da = riga.stato_bando
             AND t.a = stato_nuovo
             AND t.attore = e.origine
             AND t.evento = e.tipo);
      END IF;
      IF v_motivo IS NULL AND NOT v_ok THEN
        v_motivo :=
          'transizione_non_ammessa';
        v_dett := jsonb_build_object(
          'da', riga.stato_bando,
          'a', stato_nuovo,
          'attore', e.origine,
          'evento', e.tipo);
      END IF;

      IF v_motivo IS NOT NULL THEN
        UPDATE public.bando_evento
           SET scartato_per = v_motivo,
               scartato_at = now(),
               scartato_dettaglio = v_dett
         WHERE id = e.id;
        RAISE NOTICE
          'evento % (%): % (bando %), '
          'lasciato non applicato e '
          'marcato.',
          e.id, e.tipo, v_motivo, riga.id;
        RETURN false;
      END IF;
    END;
  END IF;
  -- <<< v11_14 (c)

  -- La lista bianca della 04: dopo il
  -- blocco (c) per un pubblicato non
  -- scatta più, resta come cintura.
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
  'l''evento applicato. Dalla 11 traduce '
  'stato_proposto; dalla 14 calcola lo '
  'stato di un annullamento_revoca dalle '
  'date e marca (scartato_per) invece di '
  'sollevare gli eventi superati o con '
  'una transizione non ammessa. true = '
  'applicato adesso; false = già '
  'applicato, marcato, date incoerenti o '
  'stato non ammesso dal CHECK.';

REVOKE ALL ON FUNCTION
  public.bando_applica_evento(bigint)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
  public.bando_applica_evento(bigint)
  TO service_role;


-- ------------------------------------------
-- 5. Il trigger dello stato: la 04 più il
--    blocco v11_14
-- ------------------------------------------
-- Stessi token della 04 fuori dal blocco.
-- Il blocco lascia passare la sola
-- correzione della redazione fatta da
-- bando_correggi_stato, che accende
-- bandi.correzione con l'id dell'evento
-- che dichiara.
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

  -- >>> v11_14: correzione della redazione
  -- Solo bando_correggi_stato accende
  -- bandi.correzione, con lo stesso id
  -- dell'evento dichiarato.
  IF attore = 'redazione'
     AND nullif(current_setting(
           'bandi.correzione', true), '')
         = evento_dichiarato
  THEN
    RETURN NEW;
  END IF;
  -- <<< v11_14

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
-- 6. bando_correggi_stato: la correzione
--    della redazione
-- ------------------------------------------
-- Uso (SQL Editor o service_role):
--   select public.bando_correggi_stato(
--     12345, 'aperto',
--     'sospensione letta male: ...');
-- Ritorna {evento_id, da, a, cambiato}.
-- Lo stato effettivo segue sempre le
-- date: un bando corretto ad «aperto» con
-- la scadenza passata il cron lo richiude
-- entro un'ora. Per riaprire si corregge
-- prima la data (evento rettifica).
CREATE OR REPLACE FUNCTION
  public.bando_correggi_stato(
    p_bando_id integer,
    p_stato    text,
    p_nota     text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  b      public.bando;
  v_id   bigint;
  v_nota text := nullif(
    btrim(coalesce(p_nota, '')), '');
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

  IF p_stato IS NULL
     OR p_stato NOT IN (
       'aperto', 'chiuso',
       'in apertura prossimamente',
       'sospeso', 'revocato') THEN
    RAISE EXCEPTION
      'stato «%» non valido: uno dei '
      'cinque stati', p_stato
      USING ERRCODE = '22023';
  END IF;
  IF v_nota IS NULL THEN
    RAISE EXCEPTION
      'la nota è obbligatoria: perché '
      'si corregge'
      USING ERRCODE = '22023';
  END IF;

  SELECT * INTO b FROM public.bando
   WHERE id = p_bando_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION
      'bando % inesistente', p_bando_id
      USING ERRCODE = '23503';
  END IF;
  IF NOT b.pubblicato THEN
    RAISE EXCEPTION
      'bando % non pubblicato: lo stato '
      'lo decide la pipeline', b.id
      USING ERRCODE = '23514';
  END IF;

  IF b.stato_bando
     IS NOT DISTINCT FROM p_stato THEN
    RETURN jsonb_build_object(
      'evento_id', NULL,
      'da', b.stato_bando,
      'a', p_stato,
      'cambiato', false);
  END IF;

  INSERT INTO public.bando_evento (
    bando_id, tipo, origine, campo,
    valore_prima, valore_dopo,
    data_evento, leggibile,
    in_aggiornamenti, verificato,
    gate, metodo)
  VALUES (
    b.id, 'correzione_redazionale',
    'redazione', 'stato_bando',
    to_jsonb(b.stato_bando),
    to_jsonb(p_stato),
    (now() AT TIME ZONE
     'Europe/Rome')::date,
    true, false, false,
    jsonb_build_object('nota', v_nota),
    'correzione_redazionale')
  ON CONFLICT DO NOTHING
  RETURNING id INTO v_id;

  -- Il dedup della 2-bis esclude questo
  -- tipo: un rifiuto qui viene da un altro
  -- vincolo, e va detto com'è.
  IF v_id IS NULL THEN
    RAISE EXCEPTION
      'bando %: INSERT della correzione '
      '(→ %) rifiutato da un vincolo che '
      'non è il dedup',
      b.id, p_stato
      USING ERRCODE = '23505';
  END IF;

  PERFORM set_config('bandi.evento_id',
                     v_id::text, true);
  PERFORM set_config('bandi.attore',
                     'redazione', true);
  PERFORM set_config('bandi.correzione',
                     v_id::text, true);

  UPDATE public.bando
     SET stato_bando = p_stato,
         stato_bando_evento_id = v_id,
         stato_bando_verificato = false
   WHERE id = b.id;

  PERFORM set_config('bandi.evento_id',
                     '', true);
  PERFORM set_config('bandi.attore',
                     '', true);
  PERFORM set_config('bandi.correzione',
                     '', true);

  UPDATE public.bando_evento
     SET applicato = true,
         applicato_at = now()
   WHERE id = v_id;

  RETURN jsonb_build_object(
    'evento_id', v_id,
    'da', b.stato_bando,
    'a', p_stato,
    'cambiato', true);
END;
$$;

COMMENT ON FUNCTION
  public.bando_correggi_stato(
    integer, text, text) IS
  'Migrazione 14: correzione della '
  'redazione fra i cinque stati di un '
  'pubblicato, con un evento '
  'correzione_redazionale (origine '
  'redazione, in_aggiornamenti=false, '
  'nota in gate). Solo service_role.';

REVOKE ALL ON FUNCTION
  public.bando_correggi_stato(
    integer, text, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
  public.bando_correggi_stato(
    integer, text, text)
  TO service_role;


-- ------------------------------------------
-- 7. Il marcatore
-- ------------------------------------------
-- Vero solo se tutto ciò che la 14 porta è
-- vivo: i blocchi v11_14 nei corpi della
-- RPC e del trigger (la 04 e la 11 sono
-- rieseguibili e li toglierebbero), le
-- colonne, la RPC di correzione, le
-- quattro righe e i cinque stati della
-- 06. SECURITY INVOKER: service_role legge
-- pg_proc e bando_transizione.
CREATE OR REPLACE FUNCTION
  public.bando_capacita_sospensioni()
RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
  SELECT
    coalesce((
      SELECT position('v11_14' IN p.prosrc)
             > 0
        FROM pg_catalog.pg_proc p
       WHERE p.oid = to_regprocedure(
               'public.bando_applica_evento'
               || '(bigint)')::oid
    ), false)
    AND coalesce((
      SELECT position('v11_14' IN p.prosrc)
             > 0
        FROM pg_catalog.pg_proc p
       WHERE p.oid = to_regprocedure(
               'public.bando_stato_solo_'
               || 'via_evento()')::oid
    ), false)
    AND to_regprocedure(
          'public.bando_correggi_stato('
          || 'integer, text, text)')
        IS NOT NULL
    AND (SELECT count(*)
           FROM pg_catalog.pg_attribute a
          WHERE a.attrelid
                = 'public.bando_evento'
                  ::regclass
            AND a.attname IN (
                  'scartato_per',
                  'scartato_at',
                  'scartato_dettaglio')
            AND NOT a.attisdropped) = 3
    AND (SELECT count(*)
           FROM public.bando_transizione t
          WHERE t.attore = 'worker'
            AND ((t.da = 'sospeso'
                  AND t.a = 'chiuso'
                  AND t.evento = 'chiusura')
                 OR (t.da = 'revocato'
                  AND t.evento
                    = 'annullamento_revoca'
                  AND t.a IN (
                    'aperto', 'chiuso',
                    'in apertura '
                    'prossimamente'))))
        = 4
    AND coalesce((
          public.bando_capacita_eventi()
          ->> 'stati_cinque')::boolean,
          false);
$$;

COMMENT ON FUNCTION
  public.bando_capacita_sospensioni() IS
  'Migrazione 14: true se RPC e trigger '
  'vivi hanno i blocchi v11_14, le '
  'colonne scartato_* e '
  'bando_correggi_stato esistono, le '
  'quattro righe della 14 sono nella '
  'lista bianca e il CHECK ammette i '
  'cinque stati. Lo legge '
  'db.capacita_sospensioni().';

REVOKE ALL ON FUNCTION
  public.bando_capacita_sospensioni()
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
  public.bando_capacita_sospensioni()
  TO service_role;


-- ------------------------------------------
-- 8. Verifica (si ferma al primo errore)
-- ------------------------------------------
DO $$
DECLARE
  v_n bigint;
  r   text;
BEGIN
  SELECT count(*) INTO v_n
    FROM public.bando_transizione;
  IF v_n <> 28 THEN
    RAISE EXCEPTION
      'V1: la lista bianca ha % righe, '
      'attese 28', v_n;
  END IF;

  IF NOT public.bando_capacita_sospensioni()
  THEN
    RAISE EXCEPTION
      'V2: il marcatore risponde false';
  END IF;

  IF NOT coalesce((
       public.bando_capacita_eventi()
       ->> 'traduce_stato_proposto')
       ::boolean, false) THEN
    RAISE EXCEPTION
      'V3: la RPC non traduce più '
      'stato_proposto';
  END IF;

  SELECT count(*) INTO v_n
    FROM pg_catalog.pg_proc p
    JOIN pg_catalog.pg_namespace n
      ON n.oid = p.pronamespace
   WHERE n.nspname = 'public'
     AND p.proname
         = 'bando_applica_evento';
  IF v_n <> 1 THEN
    RAISE EXCEPTION
      'V4: % versioni di '
      'bando_applica_evento', v_n;
  END IF;

  FOREACH r IN ARRAY
    ARRAY['anon', 'authenticated'] LOOP
    IF has_function_privilege(r,
         'public.bando_correggi_stato('
         || 'integer, text, text)',
         'EXECUTE')
       OR has_function_privilege(r,
         'public.bando_capacita_'
         || 'sospensioni()', 'EXECUTE')
       OR has_column_privilege(r,
         'public.bando_evento',
         'scartato_per', 'SELECT') THEN
      RAISE EXCEPTION
        'V5: % ha un privilegio nuovo', r;
    END IF;
  END LOOP;

  IF coalesce(position(
       'correzione_redazionale' IN
       pg_catalog.pg_get_indexdef(
         to_regclass('public.'
           || 'bando_evento_dedup_uidx'))),
       0) = 0 THEN
    RAISE EXCEPTION
      'V6: l''indice di dedup non esclude '
      'correzione_redazionale';
  END IF;

  RAISE NOTICE
    'migrazione 14: verifica superata';
END $$;

COMMIT;

-- ==========================================
-- Riconciliazione (sola lettura)
-- ==========================================
-- Il 01/10/2026 a DB non c'è nessun evento
-- sospensione, revoca, annullamento_revoca
-- o correzione_redazionale, nessun bando
-- sospeso o revocato, e due soli eventi
-- di stato verificati e non applicati
-- (9749 e 11299, aperture che ripetono
-- quelle già applicate: non cambiano lo
-- stato, quindi la 14 non le marca).
--
-- R1) Eventi in coda che la RPC marcherà
--     «superato» al prossimo
--     applica-eventi: solo quelli del
--     worker che cambiano lo stato.
--      with coda as (
--        select e.id, e.bando_id, e.tipo,
--          b.stato_bando as ora,
--          coalesce(
--            e.valore_dopo
--              ->> 'stato_bando',
--            e.valore_dopo
--              ->> 'stato_proposto',
--            case when e.campo
--                   = 'stato_bando'
--                 then e.valore_dopo
--                        #>> '{}'
--            end) as proposto,
--          least(e.data_evento,
--            (e.rilevato_at at time
--             zone 'Europe/Rome')::date)
--            as giorno,
--          coalesce(e.tipo in (
--              'proroga', 'riapertura',
--              'rettifica')
--            and (e.valore_dopo
--                 ->> 'data_scadenza')
--                 ::date
--              >= (now() at time zone
--                  'Europe/Rome')::date,
--            false) as scad
--          from bando_evento e
--          join bando b
--            on b.id = e.bando_id
--         where e.origine = 'worker'
--           and e.verificato
--           and not e.applicato
--           and e.scartato_per is null
--           and b.pubblicato)
--      select c.id, c.bando_id, c.tipo,
--             d.id as dopo,
--             d.tipo as tipo_dopo
--        from coda c
--        join lateral (
--          select x.id, x.tipo
--            from bando_evento x
--           where x.bando_id = c.bando_id
--             and x.id <> c.id
--             and x.applicato
--             and x.scartato_per is null
--             and x.origine in
--                 ('worker', 'redazione')
--             and (x.campo = 'stato_bando'
--                  or x.tipo =
--                  'annullamento_revoca'
--                  or x.valore_dopo
--                     ? 'stato_bando'
--                  or x.valore_dopo
--                     ? 'stato_proposto')
--             and not (c.scad and x.tipo
--                        = 'chiusura')
--             and (least(x.data_evento,
--                    (x.rilevato_at at time
--                     zone 'Europe/Rome')
--                    ::date), x.id)
--               > (c.giorno, c.id)
--           limit 1) d on true
--       where c.proposto is not null
--         and c.proposto
--             is distinct from c.ora;
--      -- atteso il 01/10/2026: 0 righe
--
-- R2) Eventi in coda con una transizione
--     che la lista bianca non ammette più
--     (la query 7 della 11, per tutti i
--     tipi e con la regola della 14 sul
--     sospeso e sul revocato): saranno
--     marcati «transizione_non_ammessa».
--      with coda as (
--        select e.id, e.bando_id, e.tipo,
--          e.origine,
--          b.stato_bando as ora,
--          coalesce(
--            e.valore_dopo
--              ->> 'stato_bando',
--            e.valore_dopo
--              ->> 'stato_proposto',
--            case when e.campo
--                   = 'stato_bando'
--                 then e.valore_dopo
--                        #>> '{}'
--            end) as proposto
--          from bando_evento e
--          join bando b
--            on b.id = e.bando_id
--         where e.verificato
--           and not e.applicato
--           and e.scartato_per is null
--           and b.pubblicato)
--      select c.id, c.bando_id, c.tipo,
--             c.ora, c.proposto
--        from coda c
--       where c.proposto is not null
--         and c.proposto
--             is distinct from c.ora
--         and (not public
--               .bando_transizione_ammessa(
--                 c.ora, c.proposto,
--                 c.origine)
--              or (c.ora in ('sospeso',
--                            'revocato')
--                  and not exists (
--                    select 1 from
--                      bando_transizione t
--                     where t.da = c.ora
--                       and t.a = c.proposto
--                       and t.attore
--                           = c.origine
--                       and t.evento
--                           = c.tipo)));
--      -- atteso il 01/10/2026: 0 righe
--
-- R3) Dopo il primo applica-eventi: gli
--     eventi marcati, per motivo.
--      select scartato_per, tipo, count(*)
--        from bando_evento
--       where scartato_per is not null
--       group by 1, 2 order by 1, 2;
--     Rimettere in coda un evento marcato
--     (decisione della redazione):
--      update bando_evento
--         set scartato_per = null,
--             scartato_at = null,
--             scartato_dettaglio = null
--       where id = <id>;
-- ==========================================

-- ==========================================
-- Verifica post-deploy (sola lettura)
-- ==========================================
-- 1) Il marcatore.
--      select public
--        .bando_capacita_sospensioni();
--      -- atteso: true
--
-- 2) La lista bianca.
--      select count(*)
--        from bando_transizione;
--      -- atteso: 28
--      select da, a, evento
--        from bando_transizione
--       where da in ('sospeso', 'revocato')
--       order by 1, 2, 3;
--      -- atteso 7 righe: revocato →
--      --   aperto, chiuso, in apertura
--      --   (annullamento_revoca);
--      --   sospeso → aperto, in apertura
--      --   (riapertura), chiuso
--      --   (chiusura), revocato (revoca)
--
-- 3) Il marcatore della 11 resta vero.
--      select public
--        .bando_capacita_eventi();
--      -- atteso: {"stati_cinque": true,
--      --   "traduce_stato_proposto": true}
--
-- 4) Le colonne nuove, invisibili ad anon.
--      select column_name,
--             has_column_privilege('anon',
--               'public.bando_evento',
--               column_name, 'SELECT')
--        from information_schema.columns
--       where table_name = 'bando_evento'
--         and column_name like 'scartato%'
--       order by 1;
--      -- atteso: 3 righe, tutte false
--
-- 5) Solo service_role esegue le due
--    funzioni nuove.
--      select r,
--        has_function_privilege(r,
--          'public.bando_correggi_stato('
--          || 'integer,text,text)',
--          'EXECUTE') as correggi,
--        has_function_privilege(r,
--          'public.bando_capacita_'
--          || 'sospensioni()',
--          'EXECUTE') as marcatore
--        from unnest(array['anon',
--          'authenticated',
--          'service_role']) as r;
--      -- atteso: anon f f;
--      --   authenticated f f;
--      --   service_role t t
--
-- 6) Prova facoltativa su una riga vera, a
--    traffico basso: finisce SEMPRE con un
--    errore che riporta i valori letti, e
--    il SQL Editor annulla tutto. Mettere
--    al posto di 0 l'id di un bando
--    pubblicato e aperto. Il cursore degli
--    eventi salta un numero: è innocuo.
--      do $$
--      declare b integer := 0;
--        j jsonb; s text; u text;
--      begin
--        j := public.bando_correggi_stato(
--               b, 'sospeso', 'prova 14');
--        select stato_bando into s
--          from public.bando where id = b;
--        begin
--          update public.bando
--             set stato_bando = 'aperto'
--           where id = b;
--          u := 'aggiornato';
--        exception when others then
--          u := sqlstate;
--        end;
--        raise exception
--          'prova annullata: % stato=% '
--          'update=%', j, s, u;
--      end $$;
--      -- atteso: «prova annullata:
--      --   {"a": "sospeso", "da":
--      --   "aperto", "cambiato": true,
--      --   "evento_id": …} stato=sospeso
--      --   update=23514»
-- ==========================================
