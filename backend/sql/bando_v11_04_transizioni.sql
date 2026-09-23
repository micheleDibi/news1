-- ============================================================================
-- bando_v11_04_transizioni.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Chiude l'ultimo buco del ciclo di vita: da qui in avanti lo stato di un
--   bando PUBBLICATO non si cambia più con un UPDATE, ma solo registrando un
--   evento. Il file porta, nell'ordine:
--     1. `bando_transizione` — la lista bianca delle transizioni ammesse,
--        seminata dalla stessa tabella di verità dei tre linguaggi
--        (`tests/stato-bando/casi.json`), e `bando_transizione_ammessa()`;
--     2. le RPC di servizio (`lock_acquisisci`/`lock_rilascia`), quelle degli
--        eventi (`bando_registra_evento`, `bando_applica_evento`) e quelle
--        del ciclo di vita (`bando_fondi`, `bando_separa`, `bando_pubblica`,
--        `bando_ritira`, `bando_cambia_slug`), tutte SECURITY DEFINER, con
--        REVOKE EXECUTE e la guardia di ruolo nel corpo;
--     3. `bando_transizioni_automatiche()`, il corpo del job orario;
--     4. il trigger `trg_bando_stato_solo_via_evento` e — nella STESSA
--        transazione — la sostituzione del job `chiudi-bandi-scaduti` con
--        `bandi-transizioni-orarie` (`5 * * * *`).
--
--   Il cron NON fa più UPDATE diretti (Verify-2 M3): scorre le righe con
--   `FOR UPDATE SKIP LOCKED` e chiama `bando_registra_evento(origine='cron',
--   applica=true)`. Così rispetta anche `ora_apertura`/`ora_scadenza`, che il
--   vecchio job ignorava, e ogni riga toccata lascia un evento leggibile.
--
-- Fase: (b). Nessuna colonna nuova, nessun dato di `bando` riscritto: il
--   controllo dell'impronta in fondo alla transazione lo dimostra (M1).
--
-- Precondizioni
--   * `bando_v11_01_pubblicazione.sql` (colonne `pubblicato`,
--     `stato_bando_evento_id`, `ritirato_at`, `bando_master_id`);
--   * `bando_v11_02_tabelle_di_servizio.sql` (`bando_evento`, `bando_link`,
--     `bando_fusione`, `bando_slug_storico`, `pipeline_lock`,
--     `bando_stato_effettivo`, `bando_evento_tipo_pubblico`,
--     `bando_host_aggregatore`, `dominio_di`);
--   * `bando_v11_03_fonte_ufficiale.sql` (le RPC scrivono gli `*_evento_id`
--     contando sui CHECK di provenienza, e `bando_cambia_slug` conta sul
--     trigger dello slug congelato);
--   * estensione `pg_cron` già abilitata (lo è: ci gira
--     `chiudi-bandi-scaduti`).
--
-- Rompe BandoFit? NO. Nessun oggetto pubblico cambia forma e `stato_bando`
--   resta allineato come oggi — anzi meglio, perché il job orario chiude
--   entro 65' invece che entro 24 h e tiene conto delle ore.
--
-- COSA CAMBIA PER CHI SCRIVE
--   Dopo questo file, su una riga `pubblicato`:
--     UPDATE bando SET stato_bando = 'chiuso' WHERE id = 123;
--   fallisce con 23514. La via è:
--     SELECT bando_registra_evento(123, 'chiusura', 'worker', 'stato_bando',
--              to_jsonb('chiuso'::text), '<url_prova>', '<citazione>',
--              current_date, true);
--   Sulle righe non ancora pubblicate non cambia nulla: lo stato lo decide la
--   pipeline (sono le righe `da IS NULL` della lista bianca).
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'INTERO file. È rieseguibile
--   (`CREATE TABLE IF NOT EXISTS`, `CREATE OR REPLACE FUNCTION`,
--   `DROP TRIGGER IF EXISTS`, seed con `where not exists` + `on conflict do
--   nothing`, `cron.schedule` idempotente per nome).
--   L'ULTIMA query del file è l'unica istruzione viva dopo il COMMIT: è il
--   blocco CASI generato da `tests/stato-bando/genera-sql.ts` e DEVE tornare
--   ZERO righe. Se ne torna anche una sola, `bando_stato_effettivo` (02) non
--   è d'accordo con i gemelli TypeScript e Python: fermarsi lì.
--
-- AVVERTENZA sulla riesecuzione: i due blocchi generati non vanno MAI
--   ritoccati a mano. `tests/estrazioni/stato-bando.test.ts` li confronta
--   byte per byte con l'uscita del generatore e `npm test` fallisce.
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15min';

-- ---------------------------------------------------------------------------
-- 0. Guardie di precondizione (un messaggio leggibile vale più di un 42P01 a
--    metà file)
-- ---------------------------------------------------------------------------

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_attribute
                  WHERE attrelid = 'public.bando'::regclass
                    AND attname = 'pubblicato' AND NOT attisdropped) THEN
    RAISE EXCEPTION 'manca bando.pubblicato: applicare prima bando_v11_01_pubblicazione.sql';
  END IF;

  IF to_regclass('public.bando_evento') IS NULL
     OR to_regclass('public.bando_link') IS NULL
     OR to_regclass('public.bando_fusione') IS NULL
     OR to_regclass('public.bando_slug_storico') IS NULL
     OR to_regclass('public.pipeline_lock') IS NULL THEN
    RAISE EXCEPTION 'mancano le tabelle di servizio: applicare prima bando_v11_02_tabelle_di_servizio.sql';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                  WHERE n.nspname = 'public' AND p.proname = 'bando_stato_effettivo') THEN
    RAISE EXCEPTION 'manca public.bando_stato_effettivo: applicare prima bando_v11_02_tabelle_di_servizio.sql';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_trigger
                  WHERE tgrelid = 'public.bando'::regclass
                    AND tgname = 'trg_bando_slug_congelato') THEN
    RAISE EXCEPTION 'manca trg_bando_slug_congelato: applicare prima bando_v11_03_fonte_ufficiale.sql';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
    RAISE EXCEPTION
      'pg_cron non è abilitata: Dashboard → Database → Extensions → pg_cron, poi rieseguire';
  END IF;
END $$;

-- Impronta di `updated_at`: questo file non aggiorna nessuna riga di `bando`
-- e il controllo in fondo alla transazione lo dimostra (M1).
CREATE TEMP TABLE _v11_04_impronta ON COMMIT DROP AS
SELECT md5(string_agg(id::text || ':' || coalesce(updated_at::text, ''), ',' ORDER BY id)) AS impronta
  FROM public.bando;

-- ===========================================================================
-- 1. `bando_transizione` — la lista bianca, e la funzione che la interroga
-- ===========================================================================
-- Tabella INTERNA: nessun consumatore la legge, ma è il documento che spiega
-- perché un UPDATE è stato rifiutato. Il contenuto arriva dalla stessa
-- tabella di verità dei tre linguaggi (`tests/stato-bando/casi.json`, §4):
-- il blocco del seed è GENERATO e confrontato byte per byte dal test TS.
--
-- Il CHECK sui cinque stati segue l'elenco `stati` del fixture. Non è il
-- CHECK di `bando.stato_bando` (che fino alla migrazione 06 ne ammette tre):
-- qui si descrivono le transizioni possibili, non i valori già scrivibili.

CREATE TABLE IF NOT EXISTS public.bando_transizione (
  id         bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  da         text,
  a          text        NOT NULL,
  attore     text        NOT NULL,
  evento     text        NOT NULL,
  condizione text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT bando_transizione_stati_check CHECK (
    (da IS NULL OR da IN ('aperto', 'chiuso', 'in apertura prossimamente', 'sospeso', 'revocato'))
    AND a IN ('aperto', 'chiuso', 'in apertura prossimamente', 'sospeso', 'revocato')
  ),
  CONSTRAINT bando_transizione_attore_check
    CHECK (attore IN ('cron', 'worker', 'pipeline', 'redazione'))
);

COMMENT ON TABLE public.bando_transizione IS
  'Lista bianca delle transizioni di stato_bando. Quello che non c''è non è ammesso. Seed generato da tests/stato-bando/casi.json: non si modifica a mano.';
COMMENT ON COLUMN public.bando_transizione.da IS
  'NULL = creazione della riga: lo stato iniziale lo decide la pipeline sulle righe non ancora pubblicate.';

REVOKE ALL ON TABLE public.bando_transizione FROM PUBLIC, anon, authenticated;
DO $$
DECLARE s text;
BEGIN
  s := pg_get_serial_sequence('public.bando_transizione', 'id');
  IF s IS NOT NULL THEN
    EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM PUBLIC, anon, authenticated', s);
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO service_role', s);
  END IF;
END $$;
GRANT SELECT ON TABLE public.bando_transizione TO service_role;

ALTER TABLE public.bando_transizione ENABLE ROW LEVEL SECURITY;
-- Nessuna policy per anon: senza grant e senza policy la tabella è invisibile.
DROP POLICY IF EXISTS bando_transizione_service_read ON public.bando_transizione;
CREATE POLICY bando_transizione_service_read ON public.bando_transizione
  FOR SELECT TO service_role USING (true);

-- `coalesce(da, '')` e non `(da, a, attore, evento)`: con la UNIQUE semplice
-- le tre righe di creazione (`da IS NULL`) non collidono mai fra loro, perché
-- due NULL non sono uguali, e una riesecuzione le duplicherebbe.
CREATE UNIQUE INDEX IF NOT EXISTS bando_transizione_uidx
  ON public.bando_transizione (coalesce(da, ''), a, attore, evento);

-- >>> TRANSIZIONI v1 (generato da tests/stato-bando/genera-sql.ts: non modificare a mano)
-- Seed di public.bando_transizione dalla tabella di §4 (tests/stato-bando/casi.json).
-- da IS NULL = creazione della riga. Quello che non c'è non è ammesso.
-- Rieseguibile senza vincoli: il where not exists tratta come uguali anche
-- le righe con da IS NULL, che ON CONFLICT DO NOTHING non deduplicherebbe.
insert into public.bando_transizione (da, a, attore, evento, condizione)
select v.da, v.a, v.attore, v.evento, v.condizione
from (values
  (NULL::text, 'aperto'::text, 'pipeline'::text, 'pubblicazione'::text, 'riga nuova non ancora pubblicata: lo stato lo decide il preprocess/enrich con la guardia reconcile_stato_bando; nessun evento leggibile prima della pubblicazione'::text),
  (NULL, 'chiuso', 'pipeline', 'pubblicazione', 'riga nuova non ancora pubblicata: lo stato lo decide il preprocess/enrich con la guardia reconcile_stato_bando; nessun evento leggibile prima della pubblicazione'),
  (NULL, 'in apertura prossimamente', 'pipeline', 'pubblicazione', 'riga nuova non ancora pubblicata: lo stato lo decide il preprocess/enrich con la guardia reconcile_stato_bando; nessun evento leggibile prima della pubblicazione'),
  ('in apertura prossimamente', 'aperto', 'cron', 'apertura_automatica', 'data_apertura_verificata=true e apertura raggiunta (data, e ora se presente); job orario 5 * * * *, evento con in_aggiornamenti=false'),
  ('aperto', 'chiuso', 'cron', 'chiusura_automatica', 'data_scadenza < oggi, oppure = oggi con ora_scadenza passata; job orario 5 * * * *, eventi con verificato=false e url_prova NULL; non tocca mai sospeso ne revocato'),
  ('in apertura prossimamente', 'chiuso', 'cron', 'chiusura_automatica', 'data_scadenza < oggi, oppure = oggi con ora_scadenza passata; job orario 5 * * * *, eventi con verificato=false e url_prova NULL; non tocca mai sospeso ne revocato'),
  ('in apertura prossimamente', 'aperto', 'worker', 'apertura', 'la pagina ufficiale dichiara apertura entro oggi; gate G1-G9 (citazione, url_prova scaricato, G6 su apert|dal|a partire|attiv, G7)'),
  ('in apertura prossimamente', 'in apertura prossimamente', 'worker', 'rettifica', 'differimento: date nuove di apertura e scadenza; gate G1-G9, G2 rafforzato al primo controllo; campo=data_apertura'),
  ('aperto', 'aperto', 'worker', 'proroga', 'scadenza posticipata; gate G1-G9 e vecchia data non NULL, nuova maggiore della vecchia e non anteriore a oggi'),
  ('aperto', 'aperto', 'worker', 'rettifica', 'sportello senza scadenza a cui compare una data_scadenza; gate G1-G9 come rettifica, G7 obbligatorio; campo=data_scadenza'),
  ('aperto', 'chiuso', 'worker', 'chiusura', 'esaurimento risorse o chiusura anticipata non successiva a oggi; gate G1-G9; data_scadenza resta intatta, non si scrive mai oggi'),
  ('chiuso', 'aperto', 'worker', 'proroga', 'proroga verificata; gate G1-G9 piu G7: unico modo per riaprire un chiuso'),
  ('chiuso', 'aperto', 'worker', 'riapertura', 'riapertura verificata; gate G1-G9 piu G7: unico modo per riaprire un chiuso'),
  ('aperto', 'sospeso', 'worker', 'sospensione', 'sospensione dichiarata dalla fonte ufficiale (G1-G9 su sospe); prima di R0 evento con applicato=false'),
  ('in apertura prossimamente', 'sospeso', 'worker', 'sospensione', 'sospensione dichiarata dalla fonte ufficiale (G1-G9 su sospe); prima di R0 evento con applicato=false'),
  ('sospeso', 'aperto', 'worker', 'riapertura', 'ripresa dichiarata dalla fonte ufficiale; gate G1-G9'),
  ('sospeso', 'in apertura prossimamente', 'worker', 'riapertura', 'ripresa con nuova data di apertura dichiarata dalla fonte ufficiale; gate G1-G9'),
  ('aperto', 'revocato', 'worker', 'revoca', 'revoca, annullamento o ritiro dichiarati dalla fonte ufficiale (G1-G9 su revoc|annull|ritir); stato terminale; prima di R0 evento con applicato=false'),
  ('chiuso', 'revocato', 'worker', 'revoca', 'revoca, annullamento o ritiro dichiarati dalla fonte ufficiale (G1-G9 su revoc|annull|ritir); stato terminale; prima di R0 evento con applicato=false'),
  ('in apertura prossimamente', 'revocato', 'worker', 'revoca', 'revoca, annullamento o ritiro dichiarati dalla fonte ufficiale (G1-G9 su revoc|annull|ritir); stato terminale; prima di R0 evento con applicato=false'),
  ('sospeso', 'revocato', 'worker', 'revoca', 'revoca, annullamento o ritiro dichiarati dalla fonte ufficiale (G1-G9 su revoc|annull|ritir); stato terminale; prima di R0 evento con applicato=false'),
  ('chiuso', 'chiuso', 'worker', 'graduatoria', 'pubblicazione della graduatoria: link nuovo scaricato con esito 2xx; in_aggiornamenti=true, lo stato non cambia'),
  ('chiuso', 'chiuso', 'worker', 'esito', 'pubblicazione degli esiti: link nuovo scaricato con esito 2xx; in_aggiornamenti=true, lo stato non cambia')
) as v (da, a, attore, evento, condizione)
where not exists (
  select 1 from public.bando_transizione t
  where t.da is not distinct from v.da
    and t.a = v.a and t.attore = v.attore and t.evento = v.evento
)
on conflict do nothing;
-- <<< TRANSIZIONI

-- La interroga il trigger, che gira con i privilegi di chi scrive: senza
-- SECURITY DEFINER un service_role senza SELECT su questa tabella vedrebbe
-- ogni transizione come «non ammessa». Nessuna guardia di ruolo qui dentro
-- (stessa scelta di `bando_host_aggregatore` nella 02): è una lettura di una
-- lista bianca pubblica nei fatti, e una guardia bloccherebbe il trigger.
CREATE OR REPLACE FUNCTION public.bando_transizione_ammessa(
  p_da     text,
  p_a      text,
  p_attore text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
PARALLEL SAFE
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
      FROM public.bando_transizione t
     WHERE t.da IS NOT DISTINCT FROM p_da
       AND t.a = p_a
       AND t.attore = p_attore
  );
$$;

COMMENT ON FUNCTION public.bando_transizione_ammessa(text, text, text) IS
  'Gemella di transizioneAmmessa() in src/lib/stato-bando.ts e di transizione_ammessa() in scraper_bandi/app/stato_bando.py. p_da NULL = creazione.';

REVOKE ALL ON FUNCTION public.bando_transizione_ammessa(text, text, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_transizione_ammessa(text, text, text) TO service_role;

-- Un `url_prova` rende «verificato» un evento solo se sta su un dominio di
-- tipo ente / portale pubblico / pattern con confidenza ≥ 0,8 (§13.5). Mai
-- un dominio `dedotto`, mai un aggregatore. Stesse ragioni di
-- `bando_host_aggregatore` per SECURITY DEFINER e per l'assenza di guardia.
CREATE OR REPLACE FUNCTION public.bando_dominio_verificante(nome_host text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
PARALLEL SAFE
SET search_path = public, pg_temp
AS $$
  SELECT nome_host IS NOT NULL
     AND NOT public.bando_host_aggregatore(nome_host)
     AND EXISTS (
       SELECT 1
         FROM public.dominio_ufficiale d
        WHERE d.attivo
          AND d.tipo IN ('ente', 'portale_pubblico', 'pattern')
          AND d.confidenza >= 0.80
          AND CASE
                WHEN d.host LIKE '%*%'
                  THEN lower(nome_host) LIKE replace(d.host, '*', '%')
                ELSE lower(nome_host) = d.host
                     OR right(lower(nome_host), length(d.host) + 1) = '.' || d.host
              END
     );
$$;

COMMENT ON FUNCTION public.bando_dominio_verificante(text) IS
  'true se l''host può rendere «verificato» un evento: ente/portale_pubblico/pattern attivo con confidenza >= 0,8 e mai in blocklist.';

REVOKE ALL ON FUNCTION public.bando_dominio_verificante(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_dominio_verificante(text) TO service_role;

-- ===========================================================================
-- 2. RPC
-- ===========================================================================
-- Tutte con lo stesso preambolo (C2 / Verify-2 B1). La guardia è scritta per
-- esteso in ogni corpo e non delegata a una funzione: è di due righe, si
-- legge dove serve e non può essere disattivata sostituendo un solo oggetto.
-- `session_user` resta quello della sessione anche dentro una SECURITY
-- DEFINER, quindi riconosce pg_cron e il SQL Editor, che non hanno JWT;
-- `nullif(..., '')` evita il 22P02 su una connessione PostgREST riusata, dove
-- la GUC esiste ma è vuota.

-- ---------------------------------------------------------------------------
-- 2.a Lock applicativo (M14: tre esiti lato Python, due soli lato DB)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.lock_acquisisci(
  p_nome         text,
  p_proprietario text,
  p_ttl_s        integer DEFAULT 10800
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE preso boolean;
BEGIN
  IF NOT ( session_user IN ('postgres','supabase_admin')
        OR coalesce(nullif(current_setting('request.jwt.claims', true),'')::json->>'role','') = 'service_role' )
  THEN RAISE EXCEPTION 'non autorizzato' USING ERRCODE = '42501'; END IF;

  IF p_ttl_s IS NULL OR p_ttl_s <= 0 THEN
    RAISE EXCEPTION 'p_ttl_s deve essere positivo' USING ERRCODE = '22023';
  END IF;

  -- Rientrante per lo stesso proprietario: un giro che ripassa dallo stesso
  -- step rinnova la scadenza invece di trovarsi il lock occupato da sé.
  INSERT INTO public.pipeline_lock (nome, acquisito_at, scade_at, proprietario)
  VALUES (p_nome, now(), now() + make_interval(secs => p_ttl_s), p_proprietario)
  ON CONFLICT (nome) DO UPDATE
     SET acquisito_at = now(),
         scade_at     = excluded.scade_at,
         proprietario = excluded.proprietario
   WHERE pipeline_lock.scade_at < now()
      OR pipeline_lock.proprietario = excluded.proprietario
  RETURNING true INTO preso;

  RETURN coalesce(preso, false);
END;
$$;

COMMENT ON FUNCTION public.lock_acquisisci(text, text, integer) IS
  'true = lock preso (o rinnovato dallo stesso proprietario). false = occupato da un altro giro ancora valido.';

REVOKE ALL ON FUNCTION public.lock_acquisisci(text, text, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.lock_acquisisci(text, text, integer) TO service_role;

CREATE OR REPLACE FUNCTION public.lock_rilascia(
  p_nome         text,
  p_proprietario text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE righe integer;
BEGIN
  IF NOT ( session_user IN ('postgres','supabase_admin')
        OR coalesce(nullif(current_setting('request.jwt.claims', true),'')::json->>'role','') = 'service_role' )
  THEN RAISE EXCEPTION 'non autorizzato' USING ERRCODE = '42501'; END IF;

  -- Solo il proprietario rilascia: un giro non può liberare il lock di un
  -- altro. Quello scaduto lo riprende `lock_acquisisci`.
  DELETE FROM public.pipeline_lock
   WHERE nome = p_nome AND proprietario = p_proprietario;
  GET DIAGNOSTICS righe = ROW_COUNT;

  RETURN righe > 0;
END;
$$;

REVOKE ALL ON FUNCTION public.lock_rilascia(text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.lock_rilascia(text, text) TO service_role;

-- ---------------------------------------------------------------------------
-- 2.b `bando_applica_evento` — l'unico posto che scrive stato e date
-- ---------------------------------------------------------------------------
-- Riversa `valore_dopo` nelle colonne. Due forme:
--   * scalare + `campo`  → una sola colonna (il caso normale);
--   * oggetto            → più colonne insieme (differimento: data_apertura e
--                          data_scadenza nello stesso evento).
-- Le chiavi ammesse sono solo quelle sotto: un evento non può scrivere il
-- titolo, lo slug o `pubblicato`, che hanno RPC proprie.
--
-- Le due GUC (`bandi.evento_id`, `bandi.attore`) sono l'intenzione dichiarata
-- fuori dal payload, come `bandi.slug_intent` per lo slug: è quello che il
-- trigger `trg_bando_stato_solo_via_evento` controlla.

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

-- ---------------------------------------------------------------------------
-- 2.c `bando_registra_evento` — la porta d'ingresso di ogni cambiamento
-- ---------------------------------------------------------------------------
-- Ritorna `{"id": …, "nuovo": …, "applicato": …}`. `nuovo=false` significa
-- che l'indice di dedup (02) ha riconosciuto un evento identico dello stesso
-- giorno: in quel caso NON nasce una riga nuova e l'id è quello esistente
-- (M6: un evento che ha già un cursore non torna mai come «nuovo»).
--
-- `verificato` NON è un parametro: lo decide il dominio della prova, come
-- vuole §13.5. Senza `url_prova` e `citazione` nessun evento è verificato —
-- lo impone anche il CHECK `bando_evento_verificato_prova_check` della 02.

CREATE OR REPLACE FUNCTION public.bando_registra_evento(
  p_bando_id         integer,
  p_tipo             text,
  p_origine          text,
  p_campo            text     DEFAULT NULL,
  p_valore_dopo      jsonb    DEFAULT NULL,
  p_url_prova        text     DEFAULT NULL,
  p_citazione        text     DEFAULT NULL,
  p_data_evento      date     DEFAULT NULL,
  p_applica          boolean  DEFAULT false,
  p_in_aggiornamenti boolean  DEFAULT NULL,
  p_leggibile        boolean  DEFAULT NULL,
  p_impronta_pagina  text     DEFAULT NULL,
  p_gate             jsonb    DEFAULT NULL,
  p_confidenza       smallint DEFAULT NULL,
  p_metodo           text     DEFAULT NULL,
  p_run_id           bigint   DEFAULT NULL,
  p_riferisce_a      bigint   DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
-- I nomi con suffisso `_calcolato` (e `prima`) non sono un vezzo: una
-- variabile plpgsql che si chiama come una colonna della tabella scritta
-- rende ambiguo ogni riferimento non qualificato nella stessa istruzione.
DECLARE
  b                       public.bando;
  evento_id               bigint;
  nuovo                   boolean := true;
  applicato_ora           boolean := false;
  verificato_calcolato    boolean;
  leggibile_calcolato     boolean;
  aggiornamenti_calcolato boolean;
  prima                   jsonb;
BEGIN
  IF NOT ( session_user IN ('postgres','supabase_admin')
        OR coalesce(nullif(current_setting('request.jwt.claims', true),'')::json->>'role','') = 'service_role' )
  THEN RAISE EXCEPTION 'non autorizzato' USING ERRCODE = '42501'; END IF;

  SELECT * INTO b FROM public.bando WHERE id = p_bando_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'bando % inesistente', p_bando_id USING ERRCODE = '23503';
  END IF;

  -- La prova decide: dominio di tipo ente/portale/pattern con confidenza
  -- >= 0,8, citazione presente. Il trigger `b_evento_prova_non_aggregatore`
  -- della 02 è la seconda cintura (azzera `url_prova` sugli aggregatori).
  verificato_calcolato := p_url_prova IS NOT NULL
                AND p_citazione IS NOT NULL
                AND public.bando_dominio_verificante(public.dominio_di(p_url_prova));

  leggibile_calcolato := coalesce(p_leggibile, public.bando_evento_tipo_pubblico(p_tipo));

  -- Nel box «Aggiornamenti» ci vanno i cambiamenti che il pubblico deve
  -- vedere, non le transizioni automatiche né gli eventi tecnici (§4).
  aggiornamenti_calcolato := coalesce(
    p_in_aggiornamenti,
    p_tipo NOT IN ('pubblicazione', 'apertura_automatica', 'chiusura_automatica',
                   'data_verificata', 'fonte_ufficiale_verificata',
                   'fusione', 'separazione', 'cambio_slug')
  );
  -- I due CHECK della 02 (`..._aggiornamenti_leggibile_check` e
  -- `..._aggiornamenti_prova_check`) sollevano invece di degradare: meglio
  -- abbassare qui che restituire un 23514 a chi registra un evento onesto.
  aggiornamenti_calcolato := aggiornamenti_calcolato
                      AND leggibile_calcolato
                      AND (verificato_calcolato OR p_origine = 'redazione');

  -- `prima` solo per gli eventi a campo singolo: sugli oggetti
  -- (fusione, ritiro) non significherebbe nulla.
  prima := CASE p_campo
    WHEN 'stato_bando'        THEN to_jsonb(b.stato_bando)
    WHEN 'data_pubblicazione' THEN to_jsonb(b.data_pubblicazione)
    WHEN 'data_apertura'      THEN to_jsonb(b.data_apertura)
    WHEN 'ora_apertura'       THEN to_jsonb(b.ora_apertura)
    WHEN 'data_scadenza'      THEN to_jsonb(b.data_scadenza)
    WHEN 'ora_scadenza'       THEN to_jsonb(b.ora_scadenza)
    WHEN 'slug'               THEN to_jsonb(b.slug)
    ELSE NULL
  END;

  INSERT INTO public.bando_evento (
    bando_id, tipo, origine, campo, valore_prima, valore_dopo, data_evento,
    leggibile, in_aggiornamenti, verificato, url_prova,
    citazione, impronta_pagina, gate, confidenza, metodo, run_id, riferisce_a
  ) VALUES (
    p_bando_id, p_tipo, p_origine, p_campo, prima, p_valore_dopo, p_data_evento,
    leggibile_calcolato, aggiornamenti_calcolato, verificato_calcolato, p_url_prova,
    p_citazione, p_impronta_pagina, p_gate, p_confidenza, p_metodo, p_run_id, p_riferisce_a
  )
  ON CONFLICT DO NOTHING
  RETURNING id INTO evento_id;

  IF evento_id IS NULL THEN
    -- Dedup: stesso bando, stesso tipo, stesso campo, stesso valore, stesso
    -- giorno di Roma. Stessa chiave dell'indice parziale `bando_evento_dedup_uidx`.
    nuovo := false;
    SELECT e.id, e.applicato
      INTO evento_id, applicato_ora
      FROM public.bando_evento e
     WHERE e.bando_id = p_bando_id
       AND e.tipo = p_tipo
       AND coalesce(e.campo, '') = coalesce(p_campo, '')
       AND md5(coalesce(e.valore_dopo::text, '')) = md5(coalesce(p_valore_dopo::text, ''))
       AND coalesce(e.data_evento, (e.rilevato_at AT TIME ZONE 'Europe/Rome')::date)
           = coalesce(p_data_evento, (now() AT TIME ZONE 'Europe/Rome')::date)
     ORDER BY e.id DESC
     LIMIT 1;

    IF evento_id IS NULL THEN
      RAISE EXCEPTION
        'bando %: INSERT dell''evento % rifiutato da un vincolo che non è il dedup', p_bando_id, p_tipo
        USING ERRCODE = '23505';
    END IF;
  END IF;

  IF p_applica AND NOT applicato_ora THEN
    applicato_ora := public.bando_applica_evento(evento_id);
  END IF;

  RETURN jsonb_build_object('id', evento_id, 'nuovo', nuovo, 'applicato', applicato_ora);
END;
$$;

COMMENT ON FUNCTION public.bando_registra_evento(integer, text, text, text, jsonb, text, text, date, boolean, boolean, boolean, text, jsonb, smallint, text, bigint, bigint) IS
  'Unica porta d''ingresso degli eventi. Ritorna {id, nuovo, applicato}: nuovo=false quando l''indice di dedup riconosce un evento identico dello stesso giorno.';

REVOKE ALL ON FUNCTION public.bando_registra_evento(integer, text, text, text, jsonb, text, text, date, boolean, boolean, boolean, text, jsonb, smallint, text, bigint, bigint)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_registra_evento(integer, text, text, text, jsonb, text, text, date, boolean, boolean, boolean, text, jsonb, smallint, text, bigint, bigint)
  TO service_role;

-- ---------------------------------------------------------------------------
-- 2.d `bando_scegli_master` — i sei criteri di §14, a DB
-- ---------------------------------------------------------------------------
-- Il piano la chiama `scegli_master()`: qui porta il prefisso `bando_` come
-- tutto il resto dello schema. La copia applicativa (pura, testata) vive nel
-- runner; questa serve a `bando_fondi` per avvisare quando la direzione
-- scelta a mano non è quella che i criteri preferirebbero — avvisare, non
-- impedire: la fusione preavviso → avviso ha il master più recente e sarebbe
-- respinta dal criterio (5).

CREATE OR REPLACE FUNCTION public.bando_scegli_master(p_a integer, p_b integer)
RETURNS integer
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE scelto integer;
BEGIN
  IF NOT ( session_user IN ('postgres','supabase_admin')
        OR coalesce(nullif(current_setting('request.jwt.claims', true),'')::json->>'role','') = 'service_role' )
  THEN RAISE EXCEPTION 'non autorizzato' USING ERRCODE = '42501'; END IF;

  SELECT b.id INTO scelto
    FROM public.bando b
   WHERE b.id IN (p_a, p_b)
   ORDER BY
     -- (1) fonte ufficiale trovata di tipo ente
     (b.fonte_ufficiale_stato = 'trovata' AND b.fonte_ufficiale_tipo = 'ente') DESC NULLS LAST,
     -- (2) la riga che non viene da un aggregatore
     (NOT coalesce(public.bando_host_aggregatore(public.dominio_di(b.link_bando)), false)) DESC,
     -- (3) opportunità prima del preavviso
     (b.tipo_link = 'Opportunità') DESC NULLS LAST,
     -- (4) più eventi verificati
     (SELECT count(*) FROM public.bando_evento e WHERE e.bando_id = b.id AND e.verificato) DESC,
     -- (5) pubblicato da più tempo
     b.pubblicato_at ASC NULLS LAST,
     -- (6) più contenuto
     length(coalesce(b.contenuto::text, '') || coalesce(b.descrizione_breve, '')) DESC,
     b.id ASC
   LIMIT 1;

  RETURN scelto;
END;
$$;

COMMENT ON FUNCTION public.bando_scegli_master(integer, integer) IS
  'I sei criteri di §14 applicati a una coppia. Diagnostica: bando_fondi la usa solo per avvisare, mai per rifiutare.';

REVOKE ALL ON FUNCTION public.bando_scegli_master(integer, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_scegli_master(integer, integer) TO service_role;

-- ---------------------------------------------------------------------------
-- 2.e `bando_fondi` — doppione → master, con le catene appiattite (M7)
-- ---------------------------------------------------------------------------
-- Una transazione sola, idempotente. Il doppione resta `completed` con il suo
-- slug (opzione B, A25): esce dalla vista perché `pubblicato=false`, e chi lo
-- cerca lo ritrova in `bando_fusione`/`bando_slug_storico`.
-- Date e stato del master NON vengono copiati: se il doppione aveva una data
-- migliore, è il worker a registrarla come evento con la sua prova.

CREATE OR REPLACE FUNCTION public.bando_fondi(
  p_dup    integer,
  p_master integer,
  p_motivo text
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  d          public.bando;
  m          public.bando;
  master     integer;
  successivo integer;
  passi      integer := 0;
  figli      integer[];
  figlio     integer;
  preferito  integer;
BEGIN
  IF NOT ( session_user IN ('postgres','supabase_admin')
        OR coalesce(nullif(current_setting('request.jwt.claims', true),'')::json->>'role','') = 'service_role' )
  THEN RAISE EXCEPTION 'non autorizzato' USING ERRCODE = '42501'; END IF;

  IF p_dup IS NULL OR p_master IS NULL OR p_dup = p_master THEN
    RAISE EXCEPTION 'bando_fondi: doppione e master devono essere due righe diverse'
      USING ERRCODE = '22023';
  END IF;
  IF coalesce(btrim(p_motivo), '') = '' THEN
    RAISE EXCEPTION 'bando_fondi: il motivo è obbligatorio (finisce in bando_fusione)'
      USING ERRCODE = '22023';
  END IF;

  SELECT * INTO d FROM public.bando WHERE id = p_dup FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'bando % inesistente', p_dup USING ERRCODE = '23503';
  END IF;

  -- Catene: il master di un master è il master. Dieci passi sono più che
  -- abbondanti e trasformano un ciclo in un errore invece che in un loop.
  master := p_master;
  LOOP
    SELECT b.bando_master_id INTO successivo FROM public.bando b WHERE b.id = master;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'bando % inesistente', master USING ERRCODE = '23503';
    END IF;
    EXIT WHEN successivo IS NULL;
    master := successivo;
    passi  := passi + 1;
    IF passi > 10 OR master = p_dup THEN
      RAISE EXCEPTION 'catena di fusioni troppo lunga o ciclica a partire da %', p_master
        USING ERRCODE = '23514';
    END IF;
  END LOOP;

  IF master = p_dup THEN
    RAISE EXCEPTION 'bando_fondi: % sarebbe il master di sé stesso', p_dup USING ERRCODE = '23514';
  END IF;

  SELECT * INTO m FROM public.bando WHERE id = master FOR UPDATE;

  -- Già fuso su quel master: non c'è nulla da fare (rieseguibile).
  IF d.bando_master_id IS NOT DISTINCT FROM master THEN
    RETURN master;
  END IF;
  IF d.bando_master_id IS NOT NULL THEN
    RAISE EXCEPTION 'bando % è già fuso su %: separarlo prima con bando_separa', p_dup, d.bando_master_id
      USING ERRCODE = '23514';
  END IF;

  preferito := public.bando_scegli_master(p_dup, master);
  IF preferito IS DISTINCT FROM master THEN
    RAISE NOTICE
      'bando_fondi: i criteri di §14 preferirebbero % come master, non % (fusione eseguita lo stesso)',
      preferito, master;
  END IF;

  -- Il doppione poteva essere a sua volta master di altre righe: quelle
  -- passano al master nuovo, ognuna con il suo evento (M7).
  SELECT array_agg(b.id ORDER BY b.id) INTO figli
    FROM public.bando b WHERE b.bando_master_id = p_dup;

  IF figli IS NOT NULL THEN
    UPDATE public.bando SET bando_master_id = master WHERE bando_master_id = p_dup;
    UPDATE public.bando_fusione
       SET master_id = master, master_slug = m.slug
     WHERE master_id = p_dup;
    UPDATE public.bando_slug_storico
       SET bando_id = master
     WHERE bando_id = p_dup AND esito = '301';

    FOREACH figlio IN ARRAY figli LOOP
      PERFORM public.bando_registra_evento(
        figlio, 'fusione', 'worker', 'bando_master_id',
        jsonb_build_object('master_id', master, 'master_slug', m.slug),
        NULL, NULL, NULL, false);
    END LOOP;
  END IF;

  -- `pubblicato=false` e `bando_master_id` nello STESSO UPDATE: il trigger
  -- `trg_bando_pubblica_al_completamento` della 01 ripubblicherebbe la riga
  -- se trovasse il master ancora NULL.
  UPDATE public.bando
     SET pubblicato = false, bando_master_id = master
   WHERE id = p_dup;

  IF d.slug IS NOT NULL THEN
    INSERT INTO public.bando_slug_storico (slug, bando_id, esito, motivo)
    VALUES (d.slug, master, '301', p_motivo)
    ON CONFLICT (slug) DO UPDATE
       SET bando_id = excluded.bando_id,
           esito    = '301',
           motivo   = excluded.motivo
     WHERE bando_slug_storico.esito <> '410';
  END IF;

  INSERT INTO public.bando_fusione (bando_id, slug_originale, master_id, master_slug, motivo)
  VALUES (p_dup, d.slug, master, m.slug, p_motivo)
  ON CONFLICT (bando_id) DO UPDATE
     SET master_id   = excluded.master_id,
         master_slug = excluded.master_slug,
         motivo      = excluded.motivo,
         fuso_at     = now();

  -- Unione dei link: `url` è immutabile, quindi si COPIA (mai si sposta).
  INSERT INTO public.bando_link (
    bando_id, url, tipo, origine, etichetta, content_type, esito_http,
    ultimo_visto_at, trovato_in_fonte_at, impronta_pagina, url_prova, pubblicabile
  )
  SELECT master, l.url, l.tipo, l.origine, l.etichetta, l.content_type, l.esito_http,
         l.ultimo_visto_at, l.trovato_in_fonte_at, l.impronta_pagina, l.url_prova, l.pubblicabile
    FROM public.bando_link l
   WHERE l.bando_id = p_dup
  ON CONFLICT (bando_id, url_normalizzato) DO NOTHING;

  PERFORM public.bando_registra_evento(
    p_dup, 'fusione', 'worker', 'bando_master_id',
    jsonb_build_object('master_id', master, 'master_slug', m.slug),
    NULL, NULL, NULL, false);
  PERFORM public.bando_registra_evento(
    master, 'fusione', 'worker', 'bando_master_id',
    jsonb_build_object('master_id', master, 'master_slug', m.slug, 'fuso_id', p_dup),
    NULL, NULL, NULL, false);

  -- Il master è cambiato agli occhi del pubblico (ha inglobato un doppione):
  -- il bump esplicito serve perché le sue colonne non sono state toccate.
  UPDATE public.bando SET ultimo_cambiamento_at = now() WHERE id = master;

  RETURN master;
END;
$$;

COMMENT ON FUNCTION public.bando_fondi(integer, integer, text) IS
  'Fonde un doppione nel master: pubblicato=false, bando_master_id, 301 nello storico, riga in bando_fusione, link uniti, eventi su entrambe le righe. Ritorna il master effettivo.';

REVOKE ALL ON FUNCTION public.bando_fondi(integer, integer, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_fondi(integer, integer, text) TO service_role;

-- ---------------------------------------------------------------------------
-- 2.f `bando_separa` — l'inverso esatto
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.bando_separa(p_dup integer)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE f public.bando_fusione;
BEGIN
  IF NOT ( session_user IN ('postgres','supabase_admin')
        OR coalesce(nullif(current_setting('request.jwt.claims', true),'')::json->>'role','') = 'service_role' )
  THEN RAISE EXCEPTION 'non autorizzato' USING ERRCODE = '42501'; END IF;

  SELECT * INTO f FROM public.bando_fusione WHERE bando_id = p_dup FOR UPDATE;
  IF NOT FOUND THEN
    RETURN false;
  END IF;

  -- Lo slug torna disponibile: senza l'«annullato» il trigger
  -- `trg_bando_slug_non_storico` della 03 impedirebbe alla riga di tornare
  -- pubblica con il suo stesso slug.
  UPDATE public.bando_slug_storico
     SET esito = 'annullato'
   WHERE slug = f.slug_originale AND esito = '301';

  DELETE FROM public.bando_fusione WHERE bando_id = p_dup;

  -- Togliere il master basta: `trg_bando_pubblica_al_completamento` (01)
  -- ripubblica da sé la riga se è ancora completed, con slug e non ritirata.
  UPDATE public.bando SET bando_master_id = NULL WHERE id = p_dup;

  PERFORM public.bando_registra_evento(
    p_dup, 'separazione', 'redazione', 'bando_master_id',
    jsonb_build_object('master_id', NULL, 'separato_da', f.master_id),
    NULL, NULL, NULL, false);

  RETURN true;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_separa(integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_separa(integer) TO service_role;

-- ---------------------------------------------------------------------------
-- 2.g `bando_pubblica` e `bando_ritira`
-- ---------------------------------------------------------------------------
-- La pubblicazione avviene già da sola al completamento (trigger 5.a della
-- 01): questa RPC serve a pubblicare con l'EVENTO, che è ciò che i
-- consumatori leggono per cursore.

CREATE OR REPLACE FUNCTION public.bando_pubblica(p_bando_id integer)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE b public.bando;
BEGIN
  IF NOT ( session_user IN ('postgres','supabase_admin')
        OR coalesce(nullif(current_setting('request.jwt.claims', true),'')::json->>'role','') = 'service_role' )
  THEN RAISE EXCEPTION 'non autorizzato' USING ERRCODE = '42501'; END IF;

  SELECT * INTO b FROM public.bando WHERE id = p_bando_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'bando % inesistente', p_bando_id USING ERRCODE = '23503';
  END IF;

  IF b.bando_master_id IS NOT NULL OR b.ritirato_at IS NOT NULL THEN
    RAISE EXCEPTION 'bando % è fuso o ritirato: non si pubblica', p_bando_id USING ERRCODE = '23514';
  END IF;
  IF b.stato_processing::text <> 'completed' OR b.slug IS NULL OR b.stato_bando IS NULL THEN
    RAISE EXCEPTION
      'bando %: si pubblica solo una riga completed con slug e stato_bando (ora: %, slug %, stato %)',
      p_bando_id, b.stato_processing, b.slug, b.stato_bando
      USING ERRCODE = '23514';
  END IF;

  IF NOT b.pubblicato THEN
    UPDATE public.bando
       SET pubblicato = true, pubblicato_at = coalesce(pubblicato_at, now())
     WHERE id = p_bando_id;
  END IF;

  -- `data_evento` = il giorno della PUBBLICAZIONE, non quello di oggi: così
  -- la chiave di dedup coincide con quella degli eventi seminati dal backfill
  -- 8.b della 02 e una chiamata tardiva non crea un secondo evento.
  PERFORM public.bando_registra_evento(
    p_bando_id, 'pubblicazione', 'pipeline', NULL, NULL, NULL, NULL,
    (coalesce(b.pubblicato_at, now()) AT TIME ZONE 'Europe/Rome')::date, false);

  RETURN NOT b.pubblicato;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_pubblica(integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_pubblica(integer) TO service_role;

-- Il ritiro è l'unica via al 410 e nasce SOLO da una richiesta scritta del
-- committente (obbligo legale o richiesta dell'ente): nessuno step della
-- pipeline lo emette. Per questo il motivo è obbligatorio.
CREATE OR REPLACE FUNCTION public.bando_ritira(p_bando_id integer, p_motivo text)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE b public.bando;
BEGIN
  IF NOT ( session_user IN ('postgres','supabase_admin')
        OR coalesce(nullif(current_setting('request.jwt.claims', true),'')::json->>'role','') = 'service_role' )
  THEN RAISE EXCEPTION 'non autorizzato' USING ERRCODE = '42501'; END IF;

  IF coalesce(btrim(p_motivo), '') = '' THEN
    RAISE EXCEPTION 'bando_ritira: il motivo è obbligatorio (finisce in bando_slug_storico)'
      USING ERRCODE = '22023';
  END IF;

  SELECT * INTO b FROM public.bando WHERE id = p_bando_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'bando % inesistente', p_bando_id USING ERRCODE = '23503';
  END IF;
  IF b.ritirato_at IS NOT NULL THEN
    RETURN false;
  END IF;

  UPDATE public.bando
     SET ritirato_at = now(), pubblicato = false
   WHERE id = p_bando_id;

  IF b.slug IS NOT NULL THEN
    INSERT INTO public.bando_slug_storico (slug, bando_id, esito, motivo)
    VALUES (b.slug, p_bando_id, '410', p_motivo)
    ON CONFLICT (slug) DO UPDATE
       SET bando_id = excluded.bando_id,
           esito    = '410',
           motivo   = excluded.motivo;
  END IF;

  PERFORM public.bando_registra_evento(
    p_bando_id, 'ritiro', 'redazione', NULL,
    jsonb_build_object('motivo', p_motivo, 'slug', b.slug),
    NULL, NULL, (now() AT TIME ZONE 'Europe/Rome')::date, false);

  RETURN true;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_ritira(integer, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_ritira(integer, text) TO service_role;

-- ---------------------------------------------------------------------------
-- 2.h `bando_cambia_slug` — l'unico modo di rinominare un pubblicato
-- ---------------------------------------------------------------------------
-- Dichiara l'intenzione nella GUC che il trigger della 03 controlla, scrive
-- il 301 nello storico e registra l'evento. Lo storico si scrive PRIMA
-- dell'UPDATE: il trigger `trg_bando_slug_non_storico` guarda lo slug NUOVO,
-- non quello vecchio.

CREATE OR REPLACE FUNCTION public.bando_cambia_slug(
  p_bando_id   integer,
  p_slug_nuovo text,
  p_motivo     text DEFAULT NULL
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE b public.bando;
BEGIN
  IF NOT ( session_user IN ('postgres','supabase_admin')
        OR coalesce(nullif(current_setting('request.jwt.claims', true),'')::json->>'role','') = 'service_role' )
  THEN RAISE EXCEPTION 'non autorizzato' USING ERRCODE = '42501'; END IF;

  IF coalesce(btrim(p_slug_nuovo), '') = '' THEN
    RAISE EXCEPTION 'bando_cambia_slug: lo slug nuovo non può essere vuoto' USING ERRCODE = '22023';
  END IF;

  SELECT * INTO b FROM public.bando WHERE id = p_bando_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'bando % inesistente', p_bando_id USING ERRCODE = '23503';
  END IF;
  IF b.slug IS NOT DISTINCT FROM p_slug_nuovo THEN
    RETURN false;
  END IF;

  IF b.slug IS NOT NULL THEN
    INSERT INTO public.bando_slug_storico (slug, bando_id, esito, motivo)
    VALUES (b.slug, p_bando_id, '301', coalesce(p_motivo, 'cambio slug'))
    ON CONFLICT (slug) DO UPDATE
       SET bando_id = excluded.bando_id,
           esito    = '301',
           motivo   = excluded.motivo
     WHERE bando_slug_storico.esito <> '410';
  END IF;

  -- L'evento va registrato PRIMA dell'UPDATE: `bando_registra_evento` ricava
  -- `valore_prima` rileggendo la riga, e dopo l'UPDATE troverebbe lo slug
  -- nuovo in tutti e due i campi.
  PERFORM public.bando_registra_evento(
    p_bando_id, 'cambio_slug', 'redazione', 'slug', to_jsonb(p_slug_nuovo),
    NULL, NULL, (now() AT TIME ZONE 'Europe/Rome')::date, false);

  PERFORM set_config('bandi.slug_intent', p_slug_nuovo, true);
  UPDATE public.bando SET slug = p_slug_nuovo WHERE id = p_bando_id;
  PERFORM set_config('bandi.slug_intent', '', true);

  RETURN true;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_cambia_slug(integer, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_cambia_slug(integer, text, text) TO service_role;

-- ===========================================================================
-- 3. `bando_transizioni_automatiche()` — il corpo del job orario
-- ===========================================================================
-- Il cron NON fa UPDATE diretti (M3): il trigger glielo vieterebbe, e un
-- UPDATE cieco ignorerebbe `ora_apertura`/`ora_scadenza`. Scorre le righe in
-- disaccordo con `bando_stato_effettivo` e per ciascuna registra l'evento che
-- applica il cambiamento. `SKIP LOCKED`: se la riga è in mano alla pipeline,
-- il giro dopo la riprende — mai un'attesa, mai un deadlock.
-- `sospeso` e `revocato` sono esclusi dal predicato, non solo dalla lista
-- bianca: il cron non li tocca in nessun caso (§13.3).

CREATE OR REPLACE FUNCTION public.bando_transizioni_automatiche()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  r            record;
  tipo_evento  text;
  esito        jsonb;
  esaminati    integer := 0;
  chiusi       integer := 0;
  aperti       integer := 0;
  saltati      integer := 0;
BEGIN
  IF NOT ( session_user IN ('postgres','supabase_admin')
        OR coalesce(nullif(current_setting('request.jwt.claims', true),'')::json->>'role','') = 'service_role' )
  THEN RAISE EXCEPTION 'non autorizzato' USING ERRCODE = '42501'; END IF;

  FOR r IN
    SELECT b.id,
           b.stato_bando,
           public.bando_stato_effettivo(
             b.stato_bando, b.data_apertura, b.data_apertura_verificata, b.ora_apertura,
             b.data_scadenza, b.ora_scadenza, now()
           ) AS effettivo
      FROM public.bando b
     WHERE b.pubblicato
       AND b.stato_bando IS NOT NULL
       AND b.stato_bando NOT IN ('sospeso', 'revocato')
       AND public.bando_stato_effettivo(
             b.stato_bando, b.data_apertura, b.data_apertura_verificata, b.ora_apertura,
             b.data_scadenza, b.ora_scadenza, now()
           ) IS DISTINCT FROM b.stato_bando
     ORDER BY b.id
     FOR UPDATE SKIP LOCKED
  LOOP
    esaminati := esaminati + 1;

    IF r.effettivo IS NULL OR r.effettivo NOT IN ('aperto', 'chiuso') THEN
      saltati := saltati + 1;
      CONTINUE;
    END IF;

    tipo_evento := CASE r.effettivo WHEN 'chiuso' THEN 'chiusura_automatica'
                                    ELSE 'apertura_automatica' END;

    -- Il trigger la rifiuterebbe con un'eccezione, e un'eccezione qui
    -- farebbe fallire l'intero giro: meglio contarla e passare oltre.
    IF NOT public.bando_transizione_ammessa(r.stato_bando, r.effettivo, 'cron') THEN
      saltati := saltati + 1;
      CONTINUE;
    END IF;

    esito := public.bando_registra_evento(
      r.id, tipo_evento, 'cron', 'stato_bando', to_jsonb(r.effettivo),
      NULL, NULL, (now() AT TIME ZONE 'Europe/Rome')::date, true);

    IF coalesce((esito ->> 'applicato')::boolean, false) THEN
      IF r.effettivo = 'chiuso' THEN chiusi := chiusi + 1; ELSE aperti := aperti + 1; END IF;
    ELSE
      saltati := saltati + 1;
    END IF;
  END LOOP;

  RETURN jsonb_build_object(
    'esaminati', esaminati, 'chiusi', chiusi, 'aperti', aperti, 'saltati', saltati,
    'istante', now()
  );
END;
$$;

COMMENT ON FUNCTION public.bando_transizioni_automatiche() IS
  'Corpo del job bandi-transizioni-orarie. Nessun UPDATE diretto: registra un evento chiusura_automatica/apertura_automatica per ogni riga in disaccordo con bando_stato_effettivo.';

REVOKE ALL ON FUNCTION public.bando_transizioni_automatiche() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_transizioni_automatiche() TO service_role;

-- ===========================================================================
-- 4. Il trigger e il job, nella stessa transazione
-- ===========================================================================
-- Non si possono separare: fra il `CREATE TRIGGER` e l'`unschedule` il
-- vecchio job `chiudi-bandi-scaduti` farebbe un UPDATE diretto di
-- `stato_bando` e fallirebbe, lasciando un errore in
-- `cron.job_run_details` e i bandi scaduti aperti.

-- 4.a La guardia. Nome scelto anche per l'ordine: fra i BEFORE UPDATE di
--     `bando` questo scatta per ultimo (alfabetico), quindi vede NEW già
--     assestato da `trg_bando_provenienza_date` della 03.
CREATE OR REPLACE FUNCTION public.bando_stato_solo_via_evento()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  evento_dichiarato text;
  attore            text;
BEGIN
  IF NEW.stato_bando IS NOT DISTINCT FROM OLD.stato_bando THEN
    RETURN NEW;
  END IF;

  -- Riga non ancora pubblicata: lo stato lo decide la pipeline (sono le
  -- righe `da IS NULL` della lista bianca). Nessun consumatore la vede.
  IF NOT OLD.pubblicato THEN
    RETURN NEW;
  END IF;

  evento_dichiarato := nullif(current_setting('bandi.evento_id', true), '');
  attore            := nullif(current_setting('bandi.attore', true), '');

  IF evento_dichiarato IS NULL OR attore IS NULL THEN
    RAISE EXCEPTION
      'lo stato del bando % è pubblico (% → %): si cambia solo con bando_registra_evento/bando_applica_evento, mai con un UPDATE diretto',
      OLD.id, OLD.stato_bando, NEW.stato_bando
      USING ERRCODE = '23514';
  END IF;

  IF NEW.stato_bando_evento_id IS DISTINCT FROM evento_dichiarato::bigint THEN
    RAISE EXCEPTION
      'bando %: bandi.evento_id dichiara % ma stato_bando_evento_id vale %',
      OLD.id, evento_dichiarato, NEW.stato_bando_evento_id
      USING ERRCODE = '23514';
  END IF;

  IF NOT public.bando_transizione_ammessa(OLD.stato_bando, NEW.stato_bando, attore) THEN
    RAISE EXCEPTION
      'transizione non ammessa per «%»: % → % (bando %). La lista bianca è bando_transizione.',
      attore, OLD.stato_bando, NEW.stato_bando, OLD.id
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_stato_solo_via_evento() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_bando_stato_solo_via_evento ON public.bando;
CREATE TRIGGER trg_bando_stato_solo_via_evento
  BEFORE UPDATE OF stato_bando ON public.bando
  FOR EACH ROW EXECUTE FUNCTION public.bando_stato_solo_via_evento();

-- 4.b Il job. `cron.unschedule` guardato (solleva se il nome non c'è) e
--     `cron.schedule` idempotente per nome. `5 * * * *` = entro 65' dalla
--     mezzanotte di Roma qualunque sia `cron.timezone`, che è la latenza
--     dichiarata nel contratto §13.5.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'chiudi-bandi-scaduti') THEN
    PERFORM cron.unschedule('chiudi-bandi-scaduti');
  END IF;
END $$;

SELECT cron.schedule(
  'bandi-transizioni-orarie',
  '5 * * * *',
  $cron$SELECT public.bando_transizioni_automatiche();$cron$
);

-- ---------------------------------------------------------------------------
-- 5. Controllo M1: nessuna riga di `bando` toccata da questo file
-- ---------------------------------------------------------------------------

DO $$
DECLARE prima text; dopo text;
BEGIN
  SELECT impronta INTO prima FROM _v11_04_impronta;
  SELECT md5(string_agg(id::text || ':' || coalesce(updated_at::text, ''), ',' ORDER BY id))
    INTO dopo FROM public.bando;
  IF dopo IS DISTINCT FROM prima THEN
    RAISE EXCEPTION 'la migrazione 04 ha mosso updated_at su bando. Transazione annullata.';
  END IF;
END $$;

COMMIT;

-- ============================================================================
-- Riconciliazione (rieseguibile da sola)
-- ============================================================================
-- 1) Primo allineamento dopo l'applicazione, senza aspettare il minuto 5.
--    Va lanciata a mano UNA volta: il giro normale è il job.
--
--      SELECT public.bando_transizioni_automatiche();
--      -- atteso in (b): qualche decina di `chiusi`, 0 `saltati`
--
-- 2) Evento `pubblicazione` per i bandi pubblicati dal trigger della 01 senza
--    passare da `bando_pubblica` (stessa query del backfill 8.b della 02:
--    non tocca `bando`, quindi non servono DISABLE/ENABLE):
--
--      INSERT INTO bando_evento
--        (bando_id, tipo, origine, data_evento, rilevato_at, leggibile,
--         in_aggiornamenti, verificato)
--      SELECT b.id, 'pubblicazione', 'pipeline',
--             (coalesce(b.pubblicato_at, b.created_at, now()) AT TIME ZONE 'Europe/Rome')::date,
--             coalesce(b.pubblicato_at, b.created_at, now()), true, false, false
--        FROM bando b
--       WHERE b.pubblicato
--         AND NOT EXISTS (SELECT 1 FROM bando_evento e
--                          WHERE e.bando_id = b.id AND e.tipo = 'pubblicazione')
--       ORDER BY b.id
--      ON CONFLICT DO NOTHING;
--
-- 3) Eventi verificati ma non ancora applicati (fra la fase (b) e R0 sono
--    `sospensione` e `revoca`; dopo la 06 vanno applicati):
--
--      SELECT public.bando_applica_evento(e.id)
--        FROM bando_evento e
--       WHERE NOT e.applicato AND e.verificato
--         AND e.tipo IN ('sospensione','revoca')
--       ORDER BY e.id;
--
-- 4) Se il seed di `bando_transizione` è stato modificato nel fixture, si
--    riapplica rieseguendo l'INTERO file: il blocco è `where not exists` +
--    `on conflict do nothing` e non duplica nulla. Le righe TOLTE dal
--    fixture non vengono cancellate: vanno eliminate a mano, e solo dopo
--    aver verificato che nessuna riga di `bando` sia in quello stato.
-- ============================================================================

-- ============================================================================
-- Verifica post-deploy
-- ============================================================================
-- 1) Lista bianca seminata:
--      SELECT count(*) FROM bando_transizione;            -- atteso: 23
--      SELECT count(*) FROM bando_transizione WHERE da IS NULL;  -- atteso: 3
--      SELECT attore, count(*) FROM bando_transizione GROUP BY 1 ORDER BY 1;
--      -- atteso: cron 3, pipeline 3, worker 17
--
-- 2) Un solo job dei bandi, e non è più quello vecchio:
--      SELECT jobid, jobname, schedule, active FROM cron.job ORDER BY jobname;
--      -- atteso: bandi-transizioni-orarie | 5 * * * * | t
--      --         NESSUN chiudi-bandi-scaduti
--
-- 3) Nessuna RPC eseguibile da anon (C15, §13.10):
--      SELECT p.proname,
--             has_function_privilege('anon', p.oid, 'EXECUTE')          AS anon,
--             has_function_privilege('authenticated', p.oid, 'EXECUTE') AS auth,
--             has_function_privilege('service_role', p.oid, 'EXECUTE')  AS servizio
--        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
--       WHERE n.nspname = 'public'
--         AND p.proname IN ('bando_registra_evento','bando_applica_evento','bando_fondi',
--                           'bando_separa','bando_pubblica','bando_ritira','bando_cambia_slug',
--                           'lock_acquisisci','lock_rilascia','bando_transizioni_automatiche',
--                           'bando_transizione_ammessa','bando_dominio_verificante','bando_scegli_master')
--       ORDER BY 1;
--      -- atteso: anon=false e auth=false su TUTTE, servizio=true
--
-- 4) UPDATE diretto rifiutato (da annullare):
--      BEGIN;
--        UPDATE bando SET stato_bando = 'chiuso'
--         WHERE id = (SELECT id FROM bando WHERE pubblicato AND stato_bando = 'aperto'
--                      ORDER BY id LIMIT 1);
--        -- atteso: 23514 «si cambia solo con bando_registra_evento…»
--      ROLLBACK;
--
-- 5) Transizione non ammessa rifiutata (da annullare):
--      BEGIN;
--        SELECT bando_registra_evento(
--                 (SELECT id FROM bando WHERE pubblicato AND stato_bando = 'chiuso' ORDER BY id LIMIT 1),
--                 'chiusura_automatica', 'cron', 'stato_bando', to_jsonb('aperto'::text),
--                 NULL, NULL, NULL, true);
--        -- atteso: 23514 «transizione non ammessa per «cron»: chiuso → aperto»
--      ROLLBACK;
--
-- 6) La via giusta funziona e lascia l'evento (da annullare):
--      BEGIN;
--        SELECT bando_registra_evento(
--                 (SELECT id FROM bando WHERE pubblicato AND stato_bando = 'aperto' ORDER BY id LIMIT 1),
--                 'chiusura_automatica', 'cron', 'stato_bando', to_jsonb('chiuso'::text),
--                 NULL, NULL, current_date, true);
--        -- atteso: {"id": …, "nuovo": true, "applicato": true}
--        SELECT id, tipo, origine, cursore, in_aggiornamenti, verificato, applicato
--          FROM bando_evento ORDER BY id DESC LIMIT 1;
--        -- atteso: cursore NOT NULL, in_aggiornamenti=false, verificato=false, applicato=true
--      ROLLBACK;
--
-- 7) Dedup (M6): la stessa chiamata due volte nella stessa giornata
--      BEGIN;
--        SELECT bando_registra_evento(<id>, 'graduatoria', 'worker', NULL,
--                 '{"url":"https://esempio.it/g"}'::jsonb, NULL, NULL, current_date, false);
--        SELECT bando_registra_evento(<id>, 'graduatoria', 'worker', NULL,
--                 '{"url":"https://esempio.it/g"}'::jsonb, NULL, NULL, current_date, false);
--        -- atteso: stesso "id", il secondo con "nuovo": false
--      ROLLBACK;
--
-- 8) Lock (da annullare):
--      BEGIN;
--        SELECT lock_acquisisci('prova', 'a', 60);   -- atteso: true
--        SELECT lock_acquisisci('prova', 'b', 60);   -- atteso: false
--        SELECT lock_acquisisci('prova', 'a', 60);   -- atteso: true (rientrante)
--        SELECT lock_rilascia('prova', 'b');         -- atteso: false
--        SELECT lock_rilascia('prova', 'a');         -- atteso: true
--      ROLLBACK;
--
-- 9) Nessun `updated_at` mosso dall'applicazione (sostituire :inizio):
--      SELECT count(*) FROM bando WHERE updated_at >= :inizio;   -- atteso: 0
-- ============================================================================

-- ============================================================================
-- Verifica OBBLIGATORIA — il blocco qui sotto è generato da
-- `tests/stato-bando/genera-sql.ts` dalla tabella di verità
-- `tests/stato-bando/casi.json` ed è l'UNICA istruzione viva dopo il COMMIT.
-- Confronta `bando_stato_effettivo` (migrazione 02) con i 77 casi che girano
-- anche su `src/lib/stato-bando.ts` e su `scraper_bandi/app/stato_bando.py`.
-- DEVE tornare ZERO righe: ogni riga è un disaccordo fra il DB e i due
-- gemelli, cioè un badge sbagliato sulla scheda o nel filtro.
-- Non modificarlo a mano: `npm test` lo confronta byte per byte.
-- ============================================================================

-- >>> CASI v1 (generato da tests/stato-bando/genera-sql.ts: non modificare a mano)
-- Confronta public.bando_stato_effettivo() con tests/stato-bando/casi.json.
-- Da eseguire nel SQL Editor a ogni applicazione della 04: atteso 0 righe.
-- Firma attesa (posizionale, in quest'ordine): public.bando_stato_effettivo(
--   stato text, data_apertura date, data_apertura_verificata boolean,
--   ora_apertura time, data_scadenza date, ora_scadenza time,
--   adesso timestamptz) returns text.
with casi (id, stato, data_apertura, data_apertura_verificata, ora_apertura, data_scadenza, ora_scadenza, adesso, atteso) as (
  values
    ('precedenza-revocato-batte-tutto'::text, 'revocato'::text, '2026-09-01'::date, true::boolean, NULL::time, '2030-01-01'::date, NULL::time, '2026-09-22T12:00:00+02:00'::timestamptz, 'revocato'::text),
    ('precedenza-revocato-batte-scadenza', 'revocato', NULL, NULL, NULL, '2020-01-01', NULL, '2026-09-22T12:00:00+02:00', 'revocato'),
    ('precedenza-sospeso-batte-scadenza', 'sospeso', NULL, NULL, NULL, '2020-01-01', NULL, '2026-09-22T12:00:00+02:00', 'sospeso'),
    ('precedenza-sospeso-batte-apertura', 'sospeso', '2026-09-01', true, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', 'sospeso'),
    ('precedenza-scadenza-batte-apertura', 'in apertura prossimamente', '2026-09-01', true, NULL, '2026-09-21', NULL, '2026-09-22T12:00:00+02:00', 'chiuso'),
    ('precedenza-apertura-batte-stato-salvato', 'in apertura prossimamente', '2026-09-22', true, '08:00:00', '2026-12-31', NULL, '2026-09-22T12:00:00+02:00', 'aperto'),
    ('precedenza-stato-salvato-ultimo', 'aperto', NULL, NULL, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', 'aperto'),
    ('scadenza-oggi-senza-ora-mattina', 'aperto', NULL, NULL, NULL, '2026-09-22', NULL, '2026-09-22T09:00:00+02:00', 'aperto'),
    ('scadenza-oggi-senza-ora-ultimo-secondo', 'aperto', NULL, NULL, NULL, '2026-09-22', NULL, '2026-09-22T23:59:59+02:00', 'aperto'),
    ('scadenza-ieri', 'aperto', NULL, NULL, NULL, '2026-09-21', NULL, '2026-09-22T00:00:01+02:00', 'chiuso'),
    ('scadenza-domani', 'aperto', NULL, NULL, NULL, '2026-09-23', NULL, '2026-09-22T23:59:59+02:00', 'aperto'),
    ('scadenza-timestamp-conta-solo-il-giorno', 'aperto', NULL, NULL, NULL, '2026-09-22T00:00:00', NULL, '2026-09-22T23:00:00+02:00', 'aperto'),
    ('scadenza-oggi-ora-non-passata', 'aperto', NULL, NULL, NULL, '2026-09-22', '12:00:00', '2026-09-22T11:59:59+02:00', 'aperto'),
    ('scadenza-oggi-ora-esatta', 'aperto', NULL, NULL, NULL, '2026-09-22', '12:00:00', '2026-09-22T12:00:00+02:00', 'aperto'),
    ('scadenza-oggi-ora-passata-di-un-secondo', 'aperto', NULL, NULL, NULL, '2026-09-22', '12:00:00', '2026-09-22T12:00:01+02:00', 'chiuso'),
    ('scadenza-oggi-ora-passata', 'aperto', NULL, NULL, NULL, '2026-09-22', '12:00:00', '2026-09-22T18:30:00+02:00', 'chiuso'),
    ('scadenza-oggi-ora-senza-secondi', 'aperto', NULL, NULL, NULL, '2026-09-22', '12:00', '2026-09-22T12:30:00+02:00', 'chiuso'),
    ('scadenza-domani-ora-gia-passata-oggi', 'aperto', NULL, NULL, NULL, '2026-09-23', '12:00:00', '2026-09-22T18:00:00+02:00', 'aperto'),
    ('scadenza-ieri-ora-tarda', 'aperto', NULL, NULL, NULL, '2026-09-21', '23:59:00', '2026-09-22T00:10:00+02:00', 'chiuso'),
    ('scadenza-oggi-ora-mezzanotte-esatta', 'aperto', NULL, NULL, NULL, '2026-09-22', '00:00:00', '2026-09-22T00:00:00+02:00', 'aperto'),
    ('scadenza-oggi-ora-mezzanotte-superata', 'aperto', NULL, NULL, NULL, '2026-09-22', '00:00:00', '2026-09-22T00:00:30+02:00', 'chiuso'),
    ('scadenza-oggi-ora-fine-giornata', 'aperto', NULL, NULL, NULL, '2026-09-22', '23:59:59', '2026-09-22T23:59:58+02:00', 'aperto'),
    ('apertura-raggiunta-e-verificata', 'in apertura prossimamente', '2026-09-01', true, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', 'aperto'),
    ('apertura-raggiunta-non-verificata', 'in apertura prossimamente', '2026-09-01', false, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', 'in apertura prossimamente'),
    ('apertura-raggiunta-verifica-nulla', 'in apertura prossimamente', '2026-09-01', NULL, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', 'in apertura prossimamente'),
    ('apertura-futura-verificata', 'in apertura prossimamente', '2026-12-01', true, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', 'in apertura prossimamente'),
    ('apertura-oggi-verificata-senza-ora', 'in apertura prossimamente', '2026-09-22', true, NULL, NULL, NULL, '2026-09-22T00:30:00+02:00', 'aperto'),
    ('apertura-oggi-ora-non-raggiunta', 'in apertura prossimamente', '2026-09-22', true, '10:00:00', NULL, NULL, '2026-09-22T09:59:59+02:00', 'in apertura prossimamente'),
    ('apertura-oggi-ora-esatta', 'in apertura prossimamente', '2026-09-22', true, '10:00:00', NULL, NULL, '2026-09-22T10:00:00+02:00', 'aperto'),
    ('apertura-oggi-ora-superata', 'in apertura prossimamente', '2026-09-22', true, '10:00:00', NULL, NULL, '2026-09-22T10:00:01+02:00', 'aperto'),
    ('apertura-senza-data-verificata', 'in apertura prossimamente', NULL, true, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', 'in apertura prossimamente'),
    ('apertura-verificata-su-stato-aperto', 'aperto', '2026-09-01', true, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', 'aperto'),
    ('apertura-verificata-su-stato-chiuso', 'chiuso', '2026-09-01', true, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', 'chiuso'),
    ('apertura-raggiunta-ma-scadenza-oggi-passata', 'in apertura prossimamente', '2026-09-01', true, NULL, '2026-09-22', '08:00:00', '2026-09-22T12:00:00+02:00', 'chiuso'),
    ('apertura-ieri-ora-futura', 'in apertura prossimamente', '2026-09-21', true, '23:00:00', NULL, NULL, '2026-09-22T00:30:00+02:00', 'aperto'),
    ('sportello-aperto-senza-scadenza', 'aperto', NULL, NULL, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', 'aperto'),
    ('sportello-aperto-molti-anni-dopo', 'aperto', NULL, NULL, NULL, NULL, NULL, '2099-06-15T12:00:00+02:00', 'aperto'),
    ('sportello-in-apertura-raggiunta', 'in apertura prossimamente', '2026-01-01', true, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', 'aperto'),
    ('sportello-ora-scadenza-senza-data', 'aperto', NULL, NULL, NULL, NULL, '12:00:00', '2026-09-22T18:00:00+02:00', 'aperto'),
    ('sospeso-senza-date', 'sospeso', NULL, NULL, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', 'sospeso'),
    ('sospeso-scadenza-passata', 'sospeso', NULL, NULL, NULL, '2026-09-01', NULL, '2026-09-22T12:00:00+02:00', 'sospeso'),
    ('sospeso-scadenza-oggi-ora-passata', 'sospeso', NULL, NULL, NULL, '2026-09-22', '08:00:00', '2026-09-22T12:00:00+02:00', 'sospeso'),
    ('sospeso-apertura-raggiunta-verificata', 'sospeso', '2026-09-01', true, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', 'sospeso'),
    ('revocato-senza-date', 'revocato', NULL, NULL, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', 'revocato'),
    ('revocato-scadenza-futura', 'revocato', NULL, NULL, NULL, '2030-01-01', NULL, '2026-09-22T12:00:00+02:00', 'revocato'),
    ('revocato-apertura-raggiunta', 'revocato', '2026-09-01', true, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', 'revocato'),
    ('revocato-scadenza-oggi-ora-passata', 'revocato', NULL, NULL, NULL, '2026-09-22', '08:00:00', '2026-09-22T12:00:00+02:00', 'revocato'),
    ('mezzanotte-legale-un-secondo-prima', 'aperto', NULL, NULL, NULL, '2026-09-22', NULL, '2026-09-22T21:59:59+00:00', 'aperto'),
    ('mezzanotte-legale-esatta', 'aperto', NULL, NULL, NULL, '2026-09-22', NULL, '2026-09-22T22:00:00+00:00', 'chiuso'),
    ('mezzanotte-solare-un-secondo-prima', 'aperto', NULL, NULL, NULL, '2026-11-10', NULL, '2026-11-10T22:59:59+00:00', 'aperto'),
    ('mezzanotte-solare-esatta', 'aperto', NULL, NULL, NULL, '2026-11-10', NULL, '2026-11-10T23:00:00+00:00', 'chiuso'),
    ('mezzanotte-utc-non-e-mezzanotte-a-roma', 'aperto', NULL, NULL, NULL, '2026-09-22', NULL, '2026-09-22T23:30:00+00:00', 'chiuso'),
    ('capodanno-roma', 'aperto', NULL, NULL, NULL, '2026-12-31', NULL, '2026-12-31T23:00:00+00:00', 'chiuso'),
    ('capodanno-roma-non-ancora', 'aperto', NULL, NULL, NULL, '2026-12-31', NULL, '2026-12-31T22:59:59+00:00', 'aperto'),
    ('inizio-ora-legale-mezzanotte', 'aperto', NULL, NULL, NULL, '2026-03-28', NULL, '2026-03-28T23:00:00+00:00', 'chiuso'),
    ('inizio-ora-legale-un-secondo-prima', 'aperto', NULL, NULL, NULL, '2026-03-28', NULL, '2026-03-28T22:59:59+00:00', 'aperto'),
    ('inizio-ora-legale-ora-inesistente', 'aperto', NULL, NULL, NULL, '2026-03-29', '02:30:00', '2026-03-29T01:30:00+00:00', 'chiuso'),
    ('inizio-ora-legale-prima-del-salto', 'aperto', NULL, NULL, NULL, '2026-03-29', '02:30:00', '2026-03-29T00:30:00+00:00', 'aperto'),
    ('fine-ora-legale-mezzanotte', 'aperto', NULL, NULL, NULL, '2026-10-24', NULL, '2026-10-24T22:00:00+00:00', 'chiuso'),
    ('fine-ora-legale-ora-ripetuta-primo-passaggio', 'aperto', NULL, NULL, NULL, '2026-10-25', '03:00:00', '2026-10-25T00:30:00+00:00', 'aperto'),
    ('fine-ora-legale-ora-ripetuta-secondo-passaggio', 'aperto', NULL, NULL, NULL, '2026-10-25', '03:00:00', '2026-10-25T01:30:00+00:00', 'aperto'),
    ('fine-ora-legale-dopo-il-cambio', 'aperto', NULL, NULL, NULL, '2026-10-25', '03:00:00', '2026-10-25T02:30:00+00:00', 'chiuso'),
    ('fine-ora-legale-ultimo-secondo', 'aperto', NULL, NULL, NULL, '2026-10-25', NULL, '2026-10-25T22:59:59+00:00', 'aperto'),
    ('fine-ora-legale-giorno-dopo', 'aperto', NULL, NULL, NULL, '2026-10-25', NULL, '2026-10-25T23:00:00+00:00', 'chiuso'),
    ('offset-roma-esplicito', 'aperto', NULL, NULL, NULL, '2026-09-22', NULL, '2026-09-22T23:30:00+02:00', 'aperto'),
    ('offset-altro-fuso-stesso-giorno', 'aperto', NULL, NULL, NULL, '2026-09-22', NULL, '2026-09-23T06:30:00+09:00', 'aperto'),
    ('offset-altro-fuso-oltre-mezzanotte', 'aperto', NULL, NULL, NULL, '2026-09-22', NULL, '2026-09-23T07:30:00+09:00', 'chiuso'),
    ('stato-nullo-senza-date', NULL, NULL, NULL, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', NULL),
    ('stato-nullo-scadenza-passata', NULL, NULL, NULL, NULL, '2020-01-01', NULL, '2026-09-22T12:00:00+02:00', 'chiuso'),
    ('stato-nullo-scadenza-futura', NULL, NULL, NULL, NULL, '2030-01-01', NULL, '2026-09-22T12:00:00+02:00', NULL),
    ('stato-nullo-apertura-raggiunta-verificata', NULL, '2026-09-01', true, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', NULL),
    ('stato-vuoto', '', NULL, NULL, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', NULL),
    ('stato-sconosciuto', 'unknown', NULL, NULL, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', NULL),
    ('stato-sconosciuto-scadenza-passata', 'unknown', NULL, NULL, NULL, '2020-01-01', NULL, '2026-09-22T12:00:00+02:00', 'chiuso'),
    ('chiuso-scadenza-futura', 'chiuso', NULL, NULL, NULL, '2030-01-01', NULL, '2026-09-22T12:00:00+02:00', 'chiuso'),
    ('chiuso-senza-date', 'chiuso', NULL, NULL, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', 'chiuso'),
    ('in-apertura-senza-date', 'in apertura prossimamente', NULL, NULL, NULL, NULL, NULL, '2026-09-22T12:00:00+02:00', 'in apertura prossimamente')
)
select
  c.id,
  c.atteso,
  public.bando_stato_effettivo(c.stato, c.data_apertura, c.data_apertura_verificata, c.ora_apertura, c.data_scadenza, c.ora_scadenza, c.adesso) as ottenuto
from casi c
where public.bando_stato_effettivo(c.stato, c.data_apertura, c.data_apertura_verificata, c.ora_apertura, c.data_scadenza, c.ora_scadenza, c.adesso) is distinct from c.atteso
order by c.id;
-- <<< CASI
