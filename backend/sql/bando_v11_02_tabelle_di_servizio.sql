-- ============================================================================
-- bando_v11_02_tabelle_di_servizio.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Crea gli oggetti nuovi della serie v11 che non stanno su `bando`:
--   le due funzioni pure di normalizzazione degli URL, `bando_stato_effettivo`
--   (che sta qui e non nella 05 perché la migrazione 04 la chiama), la
--   whitelist interna
--   `dominio_ufficiale` (con la sola blocklist degli aggregatori: il seed
--   completo è nel file `bando_v11_seed_dominio_ufficiale.sql`), la
--   telemetria (`pipeline_run`, `fonte_run`, `pipeline_lock`), il registro
--   degli eventi `bando_evento` con il suo cursore, i link `bando_link`,
--   la mappa delle fusioni, lo storico degli slug e la tabella di controllo
--   1:1 `bando_controllo`.
--
--   Regola che governa tutto il file: i privilegi di default del progetto
--   concedono ALL ad anon E authenticated su tabelle, sequence e funzioni
--   (schema.sql:1850, 1860, 1870). Ogni CREATE è quindi seguito subito da
--   `REVOKE ALL … FROM PUBLIC, anon, authenticated`, e i soli GRANT che
--   restano sono quelli scritti nel contratto §13. Senza le revoche, ogni
--   tabella nuova nascerebbe scrivibile con la anon key, che sta nel bundle
--   del frontend.
--
-- Fase: (b) — solo oggetti nuovi, nessuna colonna di `bando` toccata.
--
-- Precondizioni
--   * `bando_v11_01_pubblicazione.sql` applicata (le policy e i trigger di
--     questo file leggono `bando.pubblicato`, `bando.bando_master_id`,
--     `bando.ritirato_at`);
--   * `bando.id` integer (le FK qui sotto lo assumono; la 01 lo verifica).
--
-- Rompe BandoFit? NO. Tutti gli oggetti sono nuovi. Le tabelle del contratto
--   (`bando_evento`, `bando_link`, `bando_fusione`, `bando_slug_storico`)
--   nascono già leggibili da anon con le colonne e le policy definitive;
--   `pipeline_run`, `fonte_run`, `pipeline_lock`, `dominio_ufficiale` e
--   `bando_controllo` restano interne.
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'INTERO file, poi
--   `bando_v11_seed_dominio_ufficiale.sql`. Il file è rieseguibile: le
--   tabelle usano `IF NOT EXISTS`, le funzioni `CREATE OR REPLACE`, i
--   trigger `DROP … IF EXISTS` e i backfill `ON CONFLICT DO NOTHING`.
--
--   TRE AVVERTENZE sulla riesecuzione, le prime due dovute a `IF NOT EXISTS`:
--   a) se la migrazione 05 è già applicata, le revoche incondizionate di
--      questo file tolgono ad anon l'EXECUTE su `dominio_di`,
--      `bando_host_aggregatore` e `bando_stato_effettivo` E il GRANT di
--      COLONNA `(bando_id, ultimo_controllo_at)` su `bando_controllo` della
--      05:114 — in PostgreSQL `REVOKE ALL ON TABLE` revoca anche i privilegi
--      di colonna — e la vista risponde 42501. Il punto 9 in fondo al file
--      rimette da sé tutti e quattro i grant se la vista esiste, quindi la
--      riesecuzione è sicura; se il punto 9 venisse tolto, NON basterebbero i
--      tre GRANT EXECUTE: il rimedio sarebbe rieseguire subito dopo l'INTERO
--      file 05 in fase (b)/(c), la 07 in fase (d);
--   b) `CREATE TABLE IF NOT EXISTS` non aggiunge vincoli a una tabella che
--      esiste già: se questo file viene modificato dopo la prima
--      applicazione, i vincoli nuovi vanno aggiunti a mano con un ALTER;
--   c) pg_dump emette i CHECK e le colonne generate inline dentro il
--      `CREATE TABLE`, senza ordinare prima le funzioni di `public`: un
--      restore del dump su un DB vuoto (branch Supabase, `db reset`)
--      fallisce con 42883 su `bando_link` e `bando_evento`, che chiamano
--      `bando_normalizza_url` e `dominio_di`. Rimedio: applicare le
--      migrazioni nell'ordine, non ripristinare un dump.
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15min';

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_attribute
                  WHERE attrelid = 'public.bando'::regclass
                    AND attname = 'pubblicato' AND NOT attisdropped) THEN
    RAISE EXCEPTION 'manca bando.pubblicato: applicare prima bando_v11_01_pubblicazione.sql';
  END IF;
END $$;

-- Impronta di `updated_at`: questo file non aggiorna nessuna riga di `bando`,
-- e il controllo in fondo lo dimostra (M1).
CREATE TEMP TABLE _v11_02_impronta ON COMMIT DROP AS
SELECT md5(string_agg(id::text || ':' || coalesce(updated_at::text, ''), ',' ORDER BY id)) AS impronta
  FROM public.bando;

-- ===========================================================================
-- 1. Funzioni pure sugli URL
-- ===========================================================================
-- Entrambe IMMUTABLE perché alimentano colonne generate STORED, e nessuna
-- delle due solleva mai: un URL malformato vale NULL, non un errore che
-- farebbe fallire l'upsert dello scrape.
-- Attenzione a riscriverle: i valori delle colonne generate sono già
-- memorizzati e NON vengono ricalcolati da un CREATE OR REPLACE. Cambiare il
-- corpo di queste due funzioni richiede un backfill esplicito
-- (`UPDATE … SET url = url`) sulle tabelle che le usano.

CREATE OR REPLACE FUNCTION public.dominio_di(url text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE STRICT PARALLEL SAFE
SET search_path = public, pg_temp
AS $$
DECLARE autorita text;
BEGIN
  autorita := regexp_replace(btrim(url), '^[A-Za-z][A-Za-z0-9+.-]*://', '');
  -- l'autorità finisce al primo '/', '?' o '#'
  autorita := split_part(split_part(split_part(autorita, '/', 1), '?', 1), '#', 1);
  autorita := regexp_replace(autorita, '^[^@]*@', '');   -- userinfo
  autorita := split_part(autorita, ':', 1);              -- porta
  autorita := lower(btrim(autorita));
  autorita := regexp_replace(autorita, '^www\.', '');
  autorita := regexp_replace(autorita, '\.$', '');       -- radice DNS esplicita

  -- Host non ASCII (IDN non convertiti) o spazzatura: meglio NULL che un
  -- valore che poi non corrisponde a nessuna riga di `dominio_ufficiale`.
  IF autorita !~ '^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$' THEN
    RETURN NULL;
  END IF;

  RETURN nullif(autorita, '');
END;
$$;

COMMENT ON FUNCTION public.dominio_di(text) IS
  'Host registrabile-per-confronto di un URL: minuscolo, senza schema, userinfo, porta, www. e punto finale. NULL se non è un host ASCII.';

REVOKE ALL ON FUNCTION public.dominio_di(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.dominio_di(text) TO service_role;

CREATE OR REPLACE FUNCTION public.bando_normalizza_url(url text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE STRICT PARALLEL SAFE
SET search_path = public, pg_temp
AS $$
DECLARE
  resto text;
  schema_ text;
  autorita text;
  percorso text;
  parametri text;
BEGIN
  resto := btrim(url);
  IF resto = '' THEN RETURN NULL; END IF;

  resto := split_part(resto, '#', 1);   -- il frammento non identifica una risorsa

  schema_ := lower(coalesce((regexp_match(resto, '^([A-Za-z][A-Za-z0-9+.-]*)://'))[1], ''));
  IF schema_ <> '' THEN
    resto := regexp_replace(resto, '^[A-Za-z][A-Za-z0-9+.-]*://', '');
  END IF;

  autorita := split_part(split_part(resto, '/', 1), '?', 1);
  IF length(autorita) < length(resto) THEN
    resto := substr(resto, length(autorita) + 1);
  ELSE
    resto := '';
  END IF;

  autorita := regexp_replace(autorita, '^[^@]*@', '');
  autorita := lower(autorita);
  autorita := regexp_replace(autorita, ':(80|443)$', '');
  autorita := regexp_replace(autorita, '^www\.', '');

  percorso  := split_part(resto, '?', 1);
  parametri := CASE WHEN position('?' in resto) > 0
                    THEN substr(resto, position('?' in resto) + 1)
                    ELSE '' END;

  -- parametri di tracciamento: cambiano l'URL ma non la risorsa
  parametri := regexp_replace('&' || parametri,
                              '&(utm_[^&=]*|fbclid|gclid|msclkid|_ga)=[^&]*', '', 'gi');
  parametri := btrim(regexp_replace(regexp_replace(parametri, '^&+', ''), '&+$', ''));

  percorso := regexp_replace(percorso, '/+$', '');   -- lo slash finale non distingue

  RETURN nullif(
    CASE WHEN schema_ = '' THEN '' ELSE schema_ || '://' END
    || autorita || percorso
    || CASE WHEN parametri = '' THEN '' ELSE '?' || parametri END,
    '');
END;
$$;

COMMENT ON FUNCTION public.bando_normalizza_url(text) IS
  'Forma canonica di un URL per la deduplicazione: schema e host minuscoli, niente www./porta di default/frammento/parametri di tracciamento/slash finale. Lo schema NON viene unificato (http e https restano distinti): l''uguaglianza di questa colonna è uno dei criteri di fusione, e una fusione sbagliata costa più di un doppione.';

REVOKE ALL ON FUNCTION public.bando_normalizza_url(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_normalizza_url(text) TO service_role;

-- ---------------------------------------------------------------------------
-- 1.c `bando_stato_effettivo` — la verità sullo stato, calcolata alla lettura
-- ---------------------------------------------------------------------------
-- Vive QUI e non nella 05 per la regola B3 (nessun file può citare un oggetto
-- creato da un file successivo): la migrazione 04 la chiama due volte — nel
-- blocco «CASI» generato da `tests/stato-bando/genera-sql.ts` e dentro
-- `bando_transizioni_automatiche()` — e la 04 si applica PRIMA della 05.
-- Creandola qui, la 05 aggiunge soltanto il GRANT EXECUTE ad anon, come già
-- fa per `dominio_di` e `bando_host_aggregatore`.
--
-- LANGUAGE sql e STABLE perché il planner la inlini nella vista: diventa il
-- CASE scritto qui sotto, senza una chiamata di funzione per riga. In plpgsql
-- costerebbe una chiamata a riga su ogni elenco e su ogni count.
-- Le precedenze sono quelle del contratto §13.3 e non sono commutabili:
-- (1) revocato, (2) sospeso, (3) scadenza passata, (4) apertura raggiunta e
-- verificata, (5) lo stato persistito.
-- Il giorno di scadenza senza ora il bando è ancora aperto (regola identica a
-- quella di oggi). Un `chiuso` persistito non riapre alla lettura: riapre solo
-- un evento `proroga`/`riapertura` verificato, che riscrive le colonne.
CREATE OR REPLACE FUNCTION public.bando_stato_effettivo(
  stato               text,
  apertura            date,
  apertura_verificata boolean,
  ora_apertura        time,
  scadenza            date,
  ora_scadenza        time,
  adesso              timestamptz
)
RETURNS text
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
  SELECT CASE
    WHEN stato = 'revocato' THEN 'revocato'
    WHEN stato = 'sospeso'  THEN 'sospeso'
    WHEN scadenza IS NOT NULL
         AND (scadenza < (adesso AT TIME ZONE 'Europe/Rome')::date
              OR (scadenza = (adesso AT TIME ZONE 'Europe/Rome')::date
                  AND ora_scadenza IS NOT NULL
                  AND ora_scadenza < (adesso AT TIME ZONE 'Europe/Rome')::time))
      THEN 'chiuso'
    WHEN stato = 'in apertura prossimamente'
         AND coalesce(apertura_verificata, false)
         AND apertura IS NOT NULL
         AND (apertura < (adesso AT TIME ZONE 'Europe/Rome')::date
              OR (apertura = (adesso AT TIME ZONE 'Europe/Rome')::date
                  AND (ora_apertura IS NULL
                       OR ora_apertura <= (adesso AT TIME ZONE 'Europe/Rome')::time)))
      THEN 'aperto'
    -- §13.3 regola 5: lo stato salvato, ma SOLO se è uno dei cinque. Senza
    -- questa riga il blocco CASI della 04 torna 2 righe (stato-vuoto e
    -- stato-sconosciuto) e la vista espone un valore fuori contratto.
    -- Gemelli: statoValido() in src/lib/stato-bando.ts, _stato_valido() in
    -- scraper_bandi/app/stato_bando.py.
    WHEN stato IN ('aperto', 'chiuso', 'in apertura prossimamente',
                   'sospeso', 'revocato')
      THEN stato
    ELSE NULL
  END;
$$;

COMMENT ON FUNCTION public.bando_stato_effettivo(text, date, boolean, time, date, time, timestamptz) IS
  'La verità sullo stato di un bando, calcolata alla lettura sul calendario di Roma. Gemella di src/lib/stato-bando.ts e di scraper_bandi/app/stato_bando.py: i casi sono in tests/stato-bando/casi.json.';

REVOKE ALL ON FUNCTION public.bando_stato_effettivo(text, date, boolean, time, date, time, timestamptz)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_stato_effettivo(text, date, boolean, time, date, time, timestamptz)
  TO service_role;
-- Il GRANT EXECUTE ad anon lo aggiunge la migrazione 05 insieme alla vista.

-- ===========================================================================
-- 2. `dominio_ufficiale` — whitelist e blocklist, tabella INTERNA
-- ===========================================================================
-- Creata per prima fra le tabelle (il piano la elenca per ultima, ma i
-- trigger di `bando_evento` e `bando_link` la interrogano e il backfill in
-- fondo al file li fa scattare: tenerla davanti evita di dipendere
-- dall'ordine di risoluzione a runtime di plpgsql).
-- Nessun GRANT di lettura: la blocklist è pubblicata in
-- docs/contratto-db-bandi.md, ma gli host «dedotti» non sono
-- un'informazione pubblica.

CREATE TABLE IF NOT EXISTS public.dominio_ufficiale (
  id          bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  host        text        NOT NULL,
  tipo        text        NOT NULL,
  confidenza  numeric(3,2) NOT NULL DEFAULT 0.60,
  ente        text,
  codice_ipa  text,
  fonte_id    integer     REFERENCES public.fonte(id) ON DELETE SET NULL,
  origine     text        NOT NULL DEFAULT 'seed',
  note        text,
  attivo      boolean     NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT dominio_ufficiale_host_uq UNIQUE (host),
  CONSTRAINT dominio_ufficiale_tipo_check
    CHECK (tipo IN ('ente', 'portale_pubblico', 'pattern', 'dedotto', 'aggregatore')),
  CONSTRAINT dominio_ufficiale_confidenza_check
    CHECK (confidenza >= 0 AND confidenza <= 1)
);

COMMENT ON TABLE public.dominio_ufficiale IS
  'Whitelist/blocklist dei domini. `pattern` usa * come jolly (es. *.gov.it). La blocklist (tipo=aggregatore) prevale sempre sul resto.';
COMMENT ON COLUMN public.dominio_ufficiale.confidenza IS
  'Un url_prova su dominio con confidenza < 0,8 non può mai rendere verificato un evento.';

-- `bando_host_aggregatore` confronta con `right(lower(host), length(d.host)+1)`
-- e quindi NON può usare la UNIQUE su `host`: senza un indice parziale la
-- funzione scandisce l'INTERA tabella a ogni chiamata, e la vista la invoca
-- una volta per riga. Finché ci sono 25 righe non si nota; dopo
-- `python -m app domini --import` (IndicePA, ~23.000 enti) la stessa query
-- diventa 1000 × 23.000 valutazioni e mette a rischio lo `statement_timeout`
-- di 3 s garantito ad anon dal contratto §13.7. I due indici parziali
-- riducono la scansione alle sole righe che le funzioni guardano davvero.
CREATE INDEX IF NOT EXISTS dominio_ufficiale_blocklist_idx
  ON public.dominio_ufficiale (host) WHERE attivo AND tipo = 'aggregatore';

CREATE INDEX IF NOT EXISTS dominio_ufficiale_tipo_idx
  ON public.dominio_ufficiale (tipo) WHERE attivo;

REVOKE ALL ON TABLE public.dominio_ufficiale FROM PUBLIC, anon, authenticated;
DO $$
DECLARE s text;
BEGIN
  s := pg_get_serial_sequence('public.dominio_ufficiale', 'id');
  IF s IS NOT NULL THEN
    EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM PUBLIC, anon, authenticated', s);
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO service_role', s);
  END IF;
END $$;
GRANT SELECT, INSERT, UPDATE ON TABLE public.dominio_ufficiale TO service_role;

ALTER TABLE public.dominio_ufficiale ENABLE ROW LEVEL SECURITY;
-- Nessuna policy per anon: senza policy e senza grant la tabella è invisibile.
DROP POLICY IF EXISTS dominio_ufficiale_service_all ON public.dominio_ufficiale;
CREATE POLICY dominio_ufficiale_service_all ON public.dominio_ufficiale
  FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP TRIGGER IF EXISTS trg_dominio_ufficiale_updated_at ON public.dominio_ufficiale;
CREATE TRIGGER trg_dominio_ufficiale_updated_at
  BEFORE UPDATE ON public.dominio_ufficiale
  FOR EACH ROW EXECUTE FUNCTION public.set_current_timestamp_updated_at();

-- La blocklist del seed non si spegne con un UPDATE. Tutta la difesa
-- anti-aggregatore (vista pubblica, `bando_link.pubblicabile`, prova degli
-- eventi, fonte ufficiale) poggia su `bando_host_aggregatore`, che torna
-- false su una riga con `attivo = false` o con un `tipo` diverso: un solo
-- `UPDATE dominio_ufficiale SET attivo = false WHERE host='obiettivoeuropa.com'`
-- ripubblicherebbe il link dell'aggregatore su ~1700 bandi senza un errore e
-- senza una riga di log, perché il mascheramento avviene ALLA LETTURA.
-- Restano ammessi gli aggregatori scoperti in ombra (`origine <> 'seed'`) e
-- ogni modifica di `confidenza`, `note`, `ente`, `codice_ipa`.
-- Il blocco «Riconciliazione» del seed dice come si disattiva un host della
-- whitelist (ente / portale_pubblico), che non passa di qui.
CREATE OR REPLACE FUNCTION public.dominio_ufficiale_blocklist_protetta()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  IF OLD.tipo <> 'aggregatore' OR OLD.origine IS DISTINCT FROM 'seed' THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;

  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION
      'l''host «%» è nella blocklist del seed e non si cancella: toglierlo ripubblicherebbe i suoi link su tutti i bandi che lo citano, in silenzio. Se la decisione è presa, va tolto prima il trigger trg_dominio_ufficiale_blocklist_protetta e comunicata a BandoFit.',
      OLD.host USING ERRCODE = '23514';
  END IF;

  IF (OLD.attivo AND NOT NEW.attivo)
     OR NEW.tipo <> OLD.tipo
     OR NEW.host <> OLD.host THEN
    RAISE EXCEPTION
      'l''host «%» è nella blocklist del seed: non si disattiva, non cambia tipo e non cambia host. Toglierlo ripubblicherebbe i suoi link su tutti i bandi che lo citano, in silenzio (il mascheramento avviene alla lettura). Se la decisione è presa, va tolto prima il trigger trg_dominio_ufficiale_blocklist_protetta e comunicata a BandoFit.',
      OLD.host USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.dominio_ufficiale_blocklist_protetta()
  FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_dominio_ufficiale_blocklist_protetta ON public.dominio_ufficiale;
CREATE TRIGGER trg_dominio_ufficiale_blocklist_protetta
  BEFORE UPDATE OR DELETE ON public.dominio_ufficiale
  FOR EACH ROW EXECUTE FUNCTION public.dominio_ufficiale_blocklist_protetta();

-- Blocklist minima: serve già ai trigger di questo file. Il resto del seed
-- (portali pubblici, pattern, social) sta nel file dedicato.
INSERT INTO public.dominio_ufficiale (host, tipo, confidenza, origine, note)
VALUES
  ('obiettivoeuropa.com',  'aggregatore', 1.00, 'seed', 'fonte 449: è l''aggregatore da cui viene l''80% del corpus'),
  ('fasi.eu',              'aggregatore', 1.00, 'seed', NULL),
  ('europafacile.net',     'aggregatore', 1.00, 'seed', NULL),
  ('contributiregione.it', 'aggregatore', 1.00, 'seed', NULL),
  ('finanziamentinews.it', 'aggregatore', 1.00, 'seed', NULL),
  ('bandi.it',             'aggregatore', 1.00, 'seed', NULL),
  ('infobandi.it',         'aggregatore', 1.00, 'seed', NULL),
  ('ticonsiglio.com',      'aggregatore', 1.00, 'seed', NULL),
  ('contributieuropa.com', 'aggregatore', 1.00, 'seed', NULL),
  ('first.aster.it',       'aggregatore', 1.00, 'seed', NULL)
ON CONFLICT (host) DO NOTHING;

-- SECURITY DEFINER: le funzioni trigger NON girano come proprietario, e
-- `dominio_ufficiale` non è leggibile da nessuno tranne il proprietario e
-- service_role. Senza DEFINER la vista pubblica (security_invoker) non
-- potrebbe mascherare `link_bando`.
CREATE OR REPLACE FUNCTION public.bando_host_aggregatore(nome_host text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
PARALLEL SAFE
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
      FROM public.dominio_ufficiale d
     WHERE d.attivo
       AND d.tipo = 'aggregatore'
       AND CASE
             WHEN d.host LIKE '%*%'
               THEN lower(coalesce(nome_host, '')) LIKE replace(d.host, '*', '%')
             ELSE lower(coalesce(nome_host, '')) = d.host
                  OR right(lower(coalesce(nome_host, '')), length(d.host) + 1) = '.' || d.host
           END
  );
$$;

COMMENT ON FUNCTION public.bando_host_aggregatore(text) IS
  'true se l''host (o un suo sottodominio) è nella blocklist degli aggregatori. Unica funzione che legge dominio_ufficiale per conto di anon.';

REVOKE ALL ON FUNCTION public.bando_host_aggregatore(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_host_aggregatore(text) TO service_role;
-- Il GRANT EXECUTE ad anon lo aggiunge la migrazione 05 insieme alla vista:
-- è una delle tre sole funzioni dell'allowlist.

-- ===========================================================================
-- 3. Telemetria e lock
-- ===========================================================================

CREATE TABLE IF NOT EXISTS public.pipeline_run (
  id                   bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  step                 text        NOT NULL,
  giro                 text,
  avviato_at           timestamptz NOT NULL DEFAULT now(),
  concluso_at          timestamptz,
  esito                text,
  interrotto_per_tetto boolean     NOT NULL DEFAULT false,
  motivo               text,
  contatori            jsonb       NOT NULL DEFAULT '{}'::jsonb,
  note                 text
);

COMMENT ON TABLE public.pipeline_run IS
  'Un record per esecuzione di step. `step` vale ''backfill:Lx'' per i lotti una tantum, che hanno contatori e tetti separati dal mensile.';

REVOKE ALL ON TABLE public.pipeline_run FROM PUBLIC, anon, authenticated;
DO $$
DECLARE s text;
BEGIN
  s := pg_get_serial_sequence('public.pipeline_run', 'id');
  IF s IS NOT NULL THEN
    EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM PUBLIC, anon, authenticated', s);
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO service_role', s);
  END IF;
END $$;
GRANT SELECT, INSERT, UPDATE ON TABLE public.pipeline_run TO service_role;

ALTER TABLE public.pipeline_run ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pipeline_run_service_all ON public.pipeline_run;
CREATE POLICY pipeline_run_service_all ON public.pipeline_run
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE INDEX IF NOT EXISTS pipeline_run_step_avviato_idx
  ON public.pipeline_run (step, avviato_at DESC);

CREATE TABLE IF NOT EXISTS public.fonte_run (
  id              bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  fonte_id        integer NOT NULL REFERENCES public.fonte(id) ON DELETE CASCADE,
  pipeline_run_id bigint  REFERENCES public.pipeline_run(id) ON DELETE SET NULL,
  items           integer,
  nuovi           integer,
  cambiati        integer,
  identici        integer,
  segnalati       integer,
  spariti         integer,
  pagine          integer,
  troncato        boolean,
  errore          text,
  login_ok        boolean,
  durata_s        numeric(10,3),
  creato_at       timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.fonte_run IS
  'Copertura per fonte di un giro: serve a decidere se un bando è davvero sparito dal listing o se lo scrape era troncato.';

REVOKE ALL ON TABLE public.fonte_run FROM PUBLIC, anon, authenticated;
DO $$
DECLARE s text;
BEGIN
  s := pg_get_serial_sequence('public.fonte_run', 'id');
  IF s IS NOT NULL THEN
    EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM PUBLIC, anon, authenticated', s);
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO service_role', s);
  END IF;
END $$;
GRANT SELECT, INSERT, UPDATE ON TABLE public.fonte_run TO service_role;

ALTER TABLE public.fonte_run ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fonte_run_service_all ON public.fonte_run;
CREATE POLICY fonte_run_service_all ON public.fonte_run
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE INDEX IF NOT EXISTS fonte_run_fonte_creato_idx
  ON public.fonte_run (fonte_id, creato_at DESC);

CREATE TABLE IF NOT EXISTS public.pipeline_lock (
  nome          text        PRIMARY KEY,
  acquisito_at  timestamptz NOT NULL DEFAULT now(),
  scade_at      timestamptz NOT NULL,
  proprietario  text        NOT NULL
);

COMMENT ON TABLE public.pipeline_lock IS
  'Lock applicativo con scadenza. Le RPC lock_acquisisci/lock_rilascia arrivano con la migrazione 04: finché non esistono, gli step proseguono senza lock con un warning.';

REVOKE ALL ON TABLE public.pipeline_lock FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.pipeline_lock TO service_role;

ALTER TABLE public.pipeline_lock ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pipeline_lock_service_all ON public.pipeline_lock;
CREATE POLICY pipeline_lock_service_all ON public.pipeline_lock
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- ===========================================================================
-- 4. `bando_evento` — il registro leggibile per cursore
-- ===========================================================================

-- Elenco unico dei tipi che possono diventare leggibili. È una allowlist:
-- un tipo nuovo nasce interno, non pubblico per distrazione.
CREATE OR REPLACE FUNCTION public.bando_evento_tipo_pubblico(tipo text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT tipo IN (
    'pubblicazione', 'apertura_automatica', 'chiusura_automatica',
    'apertura', 'chiusura', 'proroga', 'riapertura', 'rettifica',
    'sospensione', 'revoca', 'annullamento_revoca',
    'graduatoria', 'esito', 'faq', 'nuovo_allegato',
    'fonte_ufficiale_verificata', 'data_verificata',
    'fusione', 'separazione', 'cambio_slug', 'ritiro',
    'correzione_redazionale'
  );
$$;

COMMENT ON FUNCTION public.bando_evento_tipo_pubblico(text) IS
  'Sede unica della lista dei tipi pubblici. Sempre interni: segnale_fonte, sparito_dalla_fonte, elaborazione_bloccata, fonte_ufficiale_non_trovata, possibile_doppione, preavviso_collegato.';

REVOKE ALL ON FUNCTION public.bando_evento_tipo_pubblico(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_evento_tipo_pubblico(text) TO service_role;

-- Il cursore ha una sequence propria: non è l'id, perché un evento nasce
-- spesso su un bando non ancora pubblicato e riceve il cursore più tardi.
CREATE SEQUENCE IF NOT EXISTS public.bando_evento_cursore_seq AS bigint START WITH 1 INCREMENT BY 1;
REVOKE ALL ON SEQUENCE public.bando_evento_cursore_seq FROM PUBLIC, anon, authenticated;

CREATE TABLE IF NOT EXISTS public.bando_evento (
  id               bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  bando_id         integer     NOT NULL REFERENCES public.bando(id),
  tipo             text        NOT NULL,
  origine          text        NOT NULL,
  campo            text,
  valore_prima     jsonb,
  valore_dopo      jsonb,
  data_evento      date,
  rilevato_at      timestamptz NOT NULL DEFAULT now(),
  pubblicato_at    timestamptz,
  cursore          bigint,
  leggibile        boolean     NOT NULL DEFAULT false,
  in_aggiornamenti boolean     NOT NULL DEFAULT false,
  verificato       boolean     NOT NULL DEFAULT false,
  url_prova        text,
  dominio_prova    text GENERATED ALWAYS AS (public.dominio_di(url_prova)) STORED,
  applicato        boolean     NOT NULL DEFAULT false,
  applicato_at     timestamptz,
  riferisce_a      bigint      REFERENCES public.bando_evento(id),
  -- colonne interne, mai concesse ad anon
  citazione        text,
  impronta_pagina  text,
  gate             jsonb,
  confidenza       smallint,
  metodo           text,
  run_id           bigint      REFERENCES public.pipeline_run(id) ON DELETE SET NULL,
  CONSTRAINT bando_evento_origine_check
    CHECK (origine IN ('cron', 'worker', 'pipeline', 'redazione')),
  -- niente stato verificato senza la prova che lo dimostra
  CONSTRAINT bando_evento_verificato_prova_check
    CHECK (NOT verificato OR (url_prova IS NOT NULL AND citazione IS NOT NULL)),
  CONSTRAINT bando_evento_aggiornamenti_leggibile_check
    CHECK (NOT in_aggiornamenti OR leggibile),
  CONSTRAINT bando_evento_aggiornamenti_prova_check
    CHECK (NOT in_aggiornamenti OR verificato OR origine = 'redazione'),
  CONSTRAINT bando_evento_confidenza_check
    CHECK (confidenza IS NULL OR (confidenza >= 0 AND confidenza <= 100))
);

COMMENT ON TABLE public.bando_evento IS
  'Registro immutabile degli eventi. Sincronizzazione dei consumatori: ?cursore=gt.<ultimo>&order=cursore.asc&limit=1000, rileggendo da ultimo-100 con dedup per id.';
COMMENT ON COLUMN public.bando_evento.cursore IS
  'Assegnato dal trigger sotto advisory lock: monotono anche con cron e RPC concorrenti. Una volta assegnato non viene mai tolto.';
COMMENT ON COLUMN public.bando_evento.applicato IS
  'false = evento verificato ma non ancora riversato nella colonna. Fra la fase (b) e R0 vale per sospensione e revoca.';

REVOKE ALL ON TABLE public.bando_evento FROM PUBLIC, anon, authenticated;
DO $$
DECLARE s text;
BEGIN
  s := pg_get_serial_sequence('public.bando_evento', 'id');
  IF s IS NOT NULL THEN
    EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM PUBLIC, anon, authenticated', s);
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO service_role', s);
  END IF;
END $$;

-- Gli eventi non si cancellano: una correzione o un ritiro sono righe nuove
-- con `riferisce_a`. Nemmeno service_role può cancellarli.
GRANT SELECT, INSERT, UPDATE ON TABLE public.bando_evento TO service_role;
REVOKE DELETE, TRUNCATE ON TABLE public.bando_evento FROM service_role;

-- Colonne del contratto §13.5 (+ applicato/applicato_at, M22). Restano fuori
-- citazione, impronta_pagina, gate, confidenza, metodo, run_id e leggibile:
-- `select=*` su questa tabella risponde 42501, ed è voluto.
GRANT SELECT (
  id, bando_id, tipo, origine, campo, valore_prima, valore_dopo,
  data_evento, rilevato_at, pubblicato_at, cursore, in_aggiornamenti,
  verificato, url_prova, dominio_prova, applicato, applicato_at, riferisce_a
) ON TABLE public.bando_evento TO anon;

ALTER TABLE public.bando_evento ENABLE ROW LEVEL SECURITY;
-- Forma definitiva già qui: il cursore è l'unico cancello. Un evento
-- visibile resta visibile dopo una fusione, un ritiro e anche in fase (d),
-- così la rimappatura dei doppioni non perde mai l'evento `fusione`.
DROP POLICY IF EXISTS bando_evento_public_read ON public.bando_evento;
CREATE POLICY bando_evento_public_read ON public.bando_evento
  FOR SELECT TO anon USING (cursore IS NOT NULL);

DROP POLICY IF EXISTS bando_evento_service_all ON public.bando_evento;
CREATE POLICY bando_evento_service_all ON public.bando_evento
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE UNIQUE INDEX IF NOT EXISTS bando_evento_cursore_uidx
  ON public.bando_evento (cursore) WHERE cursore IS NOT NULL;

CREATE INDEX IF NOT EXISTS bando_evento_bando_data_idx
  ON public.bando_evento (bando_id, data_evento DESC);

-- Eventi in attesa di cursore: letti a ogni pubblicazione e a ogni fusione.
CREATE INDEX IF NOT EXISTS bando_evento_in_attesa_idx
  ON public.bando_evento (bando_id) WHERE leggibile AND cursore IS NULL;

-- Dedup PARZIALE: solo i tipi ripetibili con prova. Fusioni, separazioni,
-- cambi di slug, ritiri e i tipi interni possono legittimamente ripetersi
-- con lo stesso valore.
-- `rilevato_at` va portato al calendario di Roma con la zona esplicita:
-- `timestamptz::date` dipende da TimeZone e non sarebbe IMMUTABLE.
CREATE UNIQUE INDEX IF NOT EXISTS bando_evento_dedup_uidx
  ON public.bando_evento (
    bando_id,
    tipo,
    coalesce(campo, ''),
    md5(coalesce(valore_dopo::text, '')),
    coalesce(data_evento, (rilevato_at AT TIME ZONE 'Europe/Rome')::date)
  )
  WHERE tipo NOT IN (
    'fusione', 'separazione', 'cambio_slug', 'ritiro',
    'segnale_fonte', 'sparito_dalla_fonte', 'elaborazione_bloccata',
    'fonte_ufficiale_non_trovata', 'possibile_doppione', 'preavviso_collegato'
  );

-- 4.a Cursore. Questo trigger NON solleva mai: un tipo interno viene
--     riportato a leggibile=false, un evento su bando non ancora pubblicato
--     resta in attesa. Sollevare farebbe fallire il resolver, che emette
--     eventi su righe ancora `enriched`.
CREATE OR REPLACE FUNCTION public.bando_evento_cursore()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NOT public.bando_evento_tipo_pubblico(NEW.tipo) THEN
    NEW.leggibile := false;
    -- Va abbassato anche `in_aggiornamenti`: `bando_evento_aggiornamenti_leggibile_check`
    -- impone `NOT in_aggiornamenti OR leggibile`, quindi senza questa riga la
    -- degradazione silenziosa diventerebbe un 23514 in faccia al chiamante.
    NEW.in_aggiornamenti := false;
    RETURN NEW;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM public.bando b
     WHERE b.id = NEW.bando_id
       AND (b.pubblicato OR b.bando_master_id IS NOT NULL OR b.ritirato_at IS NOT NULL)
  ) THEN
    RETURN NEW;   -- in attesa: lo promuove la pubblicazione o la fusione
  END IF;

  -- Il lock prima di nextval garantisce che un cursore minore non diventi
  -- mai visibile dopo uno maggiore, anche con cron e RPC concorrenti.
  -- I buchi lasciati dai rollback sono innocui con `cursore=gt.X`.
  PERFORM pg_advisory_xact_lock(hashtext('bando_evento_cursore'));
  NEW.cursore       := nextval('public.bando_evento_cursore_seq');
  NEW.pubblicato_at := coalesce(NEW.pubblicato_at, now());
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_evento_cursore() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS a_evento_cursore ON public.bando_evento;
CREATE TRIGGER a_evento_cursore
  BEFORE INSERT OR UPDATE OF leggibile ON public.bando_evento
  FOR EACH ROW
  WHEN (NEW.leggibile AND NEW.cursore IS NULL)
  EXECUTE FUNCTION public.bando_evento_cursore();

-- 4.a-bis Il cursore lo assegna SOLO `a_evento_cursore`, sotto advisory lock.
--     Un INSERT che lo porti già scritto scavalcherebbe il lock e potrebbe
--     rendere visibile un valore minore dopo uno maggiore, rompendo la
--     sincronizzazione `?cursore=gt.<ultimo>` di §13.5. Il nome inizia con
--     `a0_` perché i trigger scattano in ordine alfabetico e questo deve
--     precedere `a_evento_cursore`.
--     Solo sull'INSERT: sull'UPDATE la protezione esiste già, perché
--     `a_evento_cursore` ha `WHEN (NEW.leggibile AND NEW.cursore IS NULL)` e
--     riempie lui il valore prima che `z_evento_immutabile` lo veda, e
--     quest'ultimo rifiuta qualunque cambio di un cursore già assegnato.
CREATE OR REPLACE FUNCTION public.bando_evento_cursore_non_esterno()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  RAISE EXCEPTION
    'il cursore di bando_evento non si scrive dall''esterno: lo assegna il trigger a_evento_cursore sotto advisory lock, alla pubblicazione'
    USING ERRCODE = '23514';
END;
$$;

REVOKE ALL ON FUNCTION public.bando_evento_cursore_non_esterno()
  FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS a0_evento_cursore_non_esterno ON public.bando_evento;
CREATE TRIGGER a0_evento_cursore_non_esterno
  BEFORE INSERT ON public.bando_evento
  FOR EACH ROW
  WHEN (NEW.cursore IS NOT NULL)
  EXECUTE FUNCTION public.bando_evento_cursore_non_esterno();

-- 4.b Nessuna prova su dominio aggregatore, e nessun link ad aggregatore
--     dentro `valore_dopo`. Solo all'INSERT: dall'UPDATE in poi `url_prova` e
--     `valore_dopo` sono immutabili (di `url_prova` si può solo TOGLIERE il
--     valore, vedi 4.c), quindi non c'è modo di introdurne uno.
CREATE OR REPLACE FUNCTION public.bando_evento_prova_non_aggregatore()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  -- `dominio_di` è FAIL-OPEN (NULL su un URL che non riconosce) e
  -- `bando_host_aggregatore(NULL)` vale false: una prova con l'host in
  -- escape percentuale o protocol-relative passerebbe intatta. Una prova
  -- che non si sa leggere non è una prova.
  IF NEW.url_prova IS NOT NULL
     AND (public.dominio_di(NEW.url_prova) IS NULL
          OR public.bando_host_aggregatore(public.dominio_di(NEW.url_prova))) THEN
    NEW.url_prova  := NULL;
    NEW.verificato := false;
    -- Senza la prova l'evento non può stare negli aggiornamenti pubblici:
    -- `bando_evento_aggiornamenti_prova_check` (NOT in_aggiornamenti OR
    -- verificato OR origine='redazione') farebbe fallire l'INSERT invece di
    -- lasciarlo degradare in silenzio.
    NEW.in_aggiornamenti := false;
  END IF;

  -- `valore_dopo` è fra le colonne concesse ad anon ed è immutabile come
  -- `url_prova`: gli eventi `graduatoria`, `esito`, `nuovo_allegato` e `faq`
  -- ci portano dentro il link nuovo, e nessun'altra guardia lo guarda. Le
  -- chiavi il cui valore è un URL su dominio aggregatore si tolgono qui,
  -- prima che la riga diventi immutabile.
  IF jsonb_typeof(NEW.valore_dopo) = 'object' THEN
    NEW.valore_dopo := NEW.valore_dopo - ARRAY(
      SELECT kv.key
        FROM jsonb_each_text(NEW.valore_dopo) kv
       WHERE kv.value ~* '^https?://'
         AND public.bando_host_aggregatore(public.dominio_di(kv.value))
    );
  END IF;

  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_evento_prova_non_aggregatore() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS b_evento_prova_non_aggregatore ON public.bando_evento;
CREATE TRIGGER b_evento_prova_non_aggregatore
  BEFORE INSERT ON public.bando_evento
  FOR EACH ROW EXECUTE FUNCTION public.bando_evento_prova_non_aggregatore();

-- 4.c Immutabilità. Mutabili: leggibile, in_aggiornamenti, applicato,
--     applicato_at, e il passaggio da NULL a valore di cursore e
--     pubblicato_at. Tutto il resto no.
--     Due eccezioni ASIMMETRICHE su `verificato` e `url_prova`: si può solo
--     TOGLIERE una prova (portare `verificato` a false, `url_prova` a NULL),
--     mai cambiarla né aggiungerne una. Senza, una riga scritta quando la
--     blocklist era più stretta resta leggibile ad anon per sempre —
--     `b_evento_prova_non_aggregatore` è BEFORE INSERT soltanto, l'UPDATE è
--     bloccato qui, il DELETE è revocato anche a service_role, e
--     `url_prova`/`dominio_prova` sono fra le colonne concesse ad anon.
--     Allargare la blocklist è un'operazione che il seed documenta come
--     normale: deve poter essere seguita da una ripulitura.
CREATE OR REPLACE FUNCTION public.bando_evento_immutabile()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NEW.id           IS DISTINCT FROM OLD.id
  OR NEW.bando_id     IS DISTINCT FROM OLD.bando_id
  OR NEW.tipo         IS DISTINCT FROM OLD.tipo
  OR NEW.origine      IS DISTINCT FROM OLD.origine
  OR NEW.campo        IS DISTINCT FROM OLD.campo
  OR NEW.valore_prima IS DISTINCT FROM OLD.valore_prima
  OR NEW.valore_dopo  IS DISTINCT FROM OLD.valore_dopo
  OR NEW.data_evento  IS DISTINCT FROM OLD.data_evento
  OR NEW.rilevato_at  IS DISTINCT FROM OLD.rilevato_at
  OR (NEW.verificato IS DISTINCT FROM OLD.verificato AND NEW.verificato)
  OR (NEW.url_prova  IS DISTINCT FROM OLD.url_prova  AND NEW.url_prova IS NOT NULL)
  OR NEW.riferisce_a  IS DISTINCT FROM OLD.riferisce_a
  OR NEW.citazione    IS DISTINCT FROM OLD.citazione
  OR NEW.impronta_pagina IS DISTINCT FROM OLD.impronta_pagina
  OR NEW.gate         IS DISTINCT FROM OLD.gate
  OR NEW.confidenza   IS DISTINCT FROM OLD.confidenza
  OR NEW.metodo       IS DISTINCT FROM OLD.metodo
  OR NEW.run_id       IS DISTINCT FROM OLD.run_id
  THEN
    RAISE EXCEPTION
      'evento % immutabile: si possono cambiare solo leggibile, in_aggiornamenti, applicato, applicato_at (e assegnare cursore/pubblicato_at). Una correzione è un evento nuovo con riferisce_a.',
      OLD.id
      USING ERRCODE = '23514';
  END IF;

  IF OLD.cursore IS NOT NULL AND NEW.cursore IS DISTINCT FROM OLD.cursore THEN
    RAISE EXCEPTION 'il cursore dell''evento % non si cambia né si revoca', OLD.id
      USING ERRCODE = '23514';
  END IF;

  IF OLD.pubblicato_at IS NOT NULL AND NEW.pubblicato_at IS DISTINCT FROM OLD.pubblicato_at THEN
    RAISE EXCEPTION 'pubblicato_at dell''evento % è già assegnato', OLD.id
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_evento_immutabile() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS z_evento_immutabile ON public.bando_evento;
CREATE TRIGGER z_evento_immutabile
  BEFORE UPDATE ON public.bando_evento
  FOR EACH ROW EXECUTE FUNCTION public.bando_evento_immutabile();

-- 4.d Promozione degli eventi in attesa quando il bando diventa pubblico
--     (pubblicazione), fuso o ritirato. `SET leggibile = leggibile` sembra
--     un no-op ma fa scattare `a_evento_cursore` (UPDATE OF leggibile).
CREATE OR REPLACE FUNCTION public.bando_promuovi_eventi()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  UPDATE public.bando_evento
     SET leggibile = leggibile
   WHERE bando_id = NEW.id AND leggibile AND cursore IS NULL;
  RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_promuovi_eventi() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_bando_promuovi_eventi ON public.bando;
CREATE TRIGGER trg_bando_promuovi_eventi
  AFTER UPDATE ON public.bando
  FOR EACH ROW
  -- NIENTE lista di colonne: `pubblicato` lo alza il trigger BEFORE della 01,
  -- e `UPDATE OF` guarda la SET list del comando, non il valore finale. Senza
  -- questa correzione gli eventi emessi dal resolver su righe ancora
  -- `enriched` non ricevono mai il cursore e restano invisibili ad anon per
  -- sempre (la policy bando_evento_public_read è `USING (cursore IS NOT NULL)`).
  -- La WHEN usa OLD, quindi il trigger resta solo su UPDATE e il costo non cambia.
  WHEN (
    (NEW.pubblicato AND NOT OLD.pubblicato)
    OR (NEW.bando_master_id IS NOT NULL AND OLD.bando_master_id IS NULL)
    OR (NEW.ritirato_at IS NOT NULL AND OLD.ritirato_at IS NULL)
  )
  EXECUTE FUNCTION public.bando_promuovi_eventi();

-- ===========================================================================
-- 5. `bando_link` — allegati, CTA e prove, con la pubblicabilità decisa dal
--    DOMINIO e non dall'origine
-- ===========================================================================
-- `origine` registra DOVE l'URL è stato trovato. I ~1360 link all'ente
-- estratti dalle schede dell'aggregatore nascono con origine='aggregatore':
-- legare la pubblicabilità all'origine renderebbe impubblicabile l'80% del
-- corpus. Conta il dominio del link, non quello della pagina che lo conteneva.

CREATE TABLE IF NOT EXISTS public.bando_link (
  id                  bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  bando_id            integer NOT NULL REFERENCES public.bando(id),
  url                 text    NOT NULL,
  url_normalizzato    text GENERATED ALWAYS AS (public.bando_normalizza_url(url)) STORED,
  dominio             text GENERATED ALWAYS AS (public.dominio_di(url)) STORED,
  tipo                text    NOT NULL,
  origine             text    NOT NULL,
  etichetta           text,
  content_type        text,
  esito_http          smallint,
  ultimo_visto_at     timestamptz,
  trovato_in_fonte_at timestamptz,
  impronta_pagina     text,
  impronta_contenuto  text,
  -- pagina in cui il link è stato trovato: può legittimamente essere la
  -- scheda dell'aggregatore, e per questo non è mai concessa ad anon
  url_prova           text,
  pubblicabile        boolean NOT NULL DEFAULT false,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT bando_link_tipo_check CHECK (tipo IN (
    'pagina_bando', 'atto', 'allegato', 'candidatura',
    'faq', 'graduatoria', 'portale', 'altro'
  )),
  CONSTRAINT bando_link_origine_check CHECK (origine IN (
    'ente', 'portale_pubblico', 'aggregatore', 'ricerca', 'raw', 'contenuto', 'redazione'
  )),
  CONSTRAINT bando_link_pubblicabile_http_check
    CHECK (NOT pubblicabile OR (esito_http IS NOT NULL AND esito_http BETWEEN 200 AND 299)),
  CONSTRAINT bando_link_pubblicabile_fonte_check
    CHECK (NOT pubblicabile OR trovato_in_fonte_at IS NOT NULL),
  -- Se `url_normalizzato` fosse NULL la UNIQUE non varrebbe (i NULL non
  -- collidono) e l'upsert `on_conflict=bando_id,url_normalizzato`
  -- duplicherebbe la riga a ogni giro invece di aggiornarla.
  CONSTRAINT bando_link_url_valido
    CHECK (public.bando_normalizza_url(url) IS NOT NULL),
  CONSTRAINT bando_link_url_uq UNIQUE (bando_id, url_normalizzato)
);

COMMENT ON TABLE public.bando_link IS
  'Ogni riga leggibile ha risposto 2xx all''ultimo controllo e compare nell''HTML della pagina di riferimento. Upsert su (bando_id, url_normalizzato).';
COMMENT ON COLUMN public.bando_link.origine IS
  'Dove l''URL è stato trovato. NON governa la pubblicabilità: quella dipende dal dominio del link.';

REVOKE ALL ON TABLE public.bando_link FROM PUBLIC, anon, authenticated;
DO $$
DECLARE s text;
BEGIN
  s := pg_get_serial_sequence('public.bando_link', 'id');
  IF s IS NOT NULL THEN
    EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM PUBLIC, anon, authenticated', s);
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO service_role', s);
  END IF;
END $$;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.bando_link TO service_role;

GRANT SELECT (
  id, bando_id, url, dominio, tipo, etichetta, content_type, ultimo_visto_at
) ON TABLE public.bando_link TO anon;

ALTER TABLE public.bando_link ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS bando_link_public_read ON public.bando_link;
CREATE POLICY bando_link_public_read ON public.bando_link
  FOR SELECT TO anon
  USING (
    pubblicabile
    AND EXISTS (SELECT 1 FROM public.bando b WHERE b.id = bando_link.bando_id AND b.pubblicato)
  );

DROP POLICY IF EXISTS bando_link_service_all ON public.bando_link;
CREATE POLICY bando_link_service_all ON public.bando_link
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE INDEX IF NOT EXISTS bando_link_pubblicabili_idx
  ON public.bando_link (bando_id) WHERE pubblicabile;

CREATE INDEX IF NOT EXISTS bando_link_url_normalizzato_idx
  ON public.bando_link (url_normalizzato);

-- 5.a Pubblicabilità per dominio. Il trigger non tocca mai `url_prova`.
CREATE OR REPLACE FUNCTION public.bando_link_dominio()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  -- L'host si RICAVA dall'URL e NON si legge da `NEW.dominio`: quella è una
  -- colonna generata STORED, e PostgreSQL calcola le colonne generate DOPO
  -- i trigger BEFORE. Dentro questo trigger `NEW.dominio` varrebbe sempre
  -- NULL, `bando_host_aggregatore(NULL)` sempre false, e la guardia non
  -- scatterebbe mai: un link su un aggregatore con 2xx e `trovato_in_fonte_at`
  -- diventerebbe leggibile da anon. Il trigger gemello di `bando_evento`
  -- calcola l'host allo stesso modo.
  -- `dominio_di` è FAIL-OPEN: torna NULL su un URL che il suo regex non
  -- riconosce (host in escape percentuale, protocol-relative) e
  -- `bando_host_aggregatore(NULL)` vale false. Host non riconoscibile ⇒ non
  -- pubblicabile: su un link pubblico la regola è fail-closed.
  IF NEW.pubblicabile
     AND (public.dominio_di(NEW.url) IS NULL
          OR public.bando_host_aggregatore(public.dominio_di(NEW.url))) THEN
    NEW.pubblicabile := false;
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_link_dominio() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_bando_link_dominio ON public.bando_link;
CREATE TRIGGER trg_bando_link_dominio
  BEFORE INSERT OR UPDATE ON public.bando_link
  FOR EACH ROW EXECUTE FUNCTION public.bando_link_dominio();

-- 5.b `url` immutabile: è la chiave insieme a bando_id (via url_normalizzato)
--     e cambiarlo trasformerebbe silenziosamente un link in un altro.
CREATE OR REPLACE FUNCTION public.bando_link_url_immutabile()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NEW.url IS DISTINCT FROM OLD.url THEN
    RAISE EXCEPTION 'bando_link %: url immutabile (inserire una riga nuova)', OLD.id
      USING ERRCODE = '23514';
  END IF;
  IF NEW.bando_id IS DISTINCT FROM OLD.bando_id THEN
    RAISE EXCEPTION 'bando_link %: bando_id immutabile', OLD.id
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_link_url_immutabile() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_bando_link_url_immutabile ON public.bando_link;
CREATE TRIGGER trg_bando_link_url_immutabile
  BEFORE UPDATE ON public.bando_link
  FOR EACH ROW EXECUTE FUNCTION public.bando_link_url_immutabile();

DROP TRIGGER IF EXISTS trg_bando_link_updated_at ON public.bando_link;
CREATE TRIGGER trg_bando_link_updated_at
  BEFORE UPDATE ON public.bando_link
  FOR EACH ROW EXECUTE FUNCTION public.set_current_timestamp_updated_at();

-- ===========================================================================
-- 6. Mappa delle fusioni e storico degli slug (leggibili da anon su TUTTE le
--    righe: sono il modo in cui un consumatore risolve un id o uno slug che
--    non trova più)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS public.bando_fusione (
  bando_id       integer     PRIMARY KEY REFERENCES public.bando(id),
  slug_originale text,
  master_id      integer     NOT NULL REFERENCES public.bando(id),
  master_slug    text,
  motivo         text        NOT NULL,
  fuso_at        timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT bando_fusione_master_diverso CHECK (master_id <> bando_id)
);

COMMENT ON TABLE public.bando_fusione IS
  'Da un bando_id o da uno slug salvato prima della fusione si risale al master. La riga resta finché esiste il master; le catene le appiattisce bando_fondi.';

REVOKE ALL ON TABLE public.bando_fusione FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.bando_fusione TO service_role;
GRANT SELECT (bando_id, slug_originale, master_id, master_slug, motivo, fuso_at)
  ON TABLE public.bando_fusione TO anon;

ALTER TABLE public.bando_fusione ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS bando_fusione_public_read ON public.bando_fusione;
CREATE POLICY bando_fusione_public_read ON public.bando_fusione
  FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS bando_fusione_service_all ON public.bando_fusione;
CREATE POLICY bando_fusione_service_all ON public.bando_fusione
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE INDEX IF NOT EXISTS bando_fusione_slug_originale_idx
  ON public.bando_fusione (slug_originale);
CREATE INDEX IF NOT EXISTS bando_fusione_master_idx
  ON public.bando_fusione (master_id);

CREATE TABLE IF NOT EXISTS public.bando_slug_storico (
  slug       text        PRIMARY KEY,
  bando_id   integer     NOT NULL REFERENCES public.bando(id),
  esito      text        NOT NULL,
  motivo     text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT bando_slug_storico_esito_check CHECK (esito IN ('301', '410', 'annullato'))
);

COMMENT ON TABLE public.bando_slug_storico IS
  '301 → bando_id è il master corrente (mai catene). 410 → bando ritirato su richiesta scritta del committente. annullato → riga chiusa da bando_separa.';

REVOKE ALL ON TABLE public.bando_slug_storico FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.bando_slug_storico TO service_role;
GRANT SELECT (slug, bando_id, esito, motivo, created_at)
  ON TABLE public.bando_slug_storico TO anon;

ALTER TABLE public.bando_slug_storico ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS bando_slug_storico_public_read ON public.bando_slug_storico;
CREATE POLICY bando_slug_storico_public_read ON public.bando_slug_storico
  FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS bando_slug_storico_service_all ON public.bando_slug_storico;
CREATE POLICY bando_slug_storico_service_all ON public.bando_slug_storico
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE INDEX IF NOT EXISTS bando_slug_storico_bando_idx
  ON public.bando_slug_storico (bando_id);

-- ===========================================================================
-- 7. `bando_controllo` — tutte le colonne «calde» del monitor, fuori da
--    `bando`
-- ===========================================================================
-- Sta a parte per non far scattare i due trigger `updated_at` e per non
-- riscrivere righe con 24 indici a ogni controllo. Nessuna colonna di testo
-- o di impronta va su `bando`.

CREATE TABLE IF NOT EXISTS public.bando_controllo (
  bando_id                 integer  PRIMARY KEY REFERENCES public.bando(id),
  ultimo_controllo_at      timestamptz,
  prossimo_controllo_at    timestamptz,
  priorita_controllo       smallint NOT NULL DEFAULT 30,
  volatilita               numeric(3,2) NOT NULL DEFAULT 1.00,
  controlli_falliti        smallint NOT NULL DEFAULT 0,
  tentativi_resolver       smallint NOT NULL DEFAULT 0,
  tentativi_pipeline       smallint NOT NULL DEFAULT 0,
  candidato_prioritario    text,
  impronta_contenuto       text,
  impronte_sezioni         jsonb,
  testo_norm               bytea,
  impronta_raw             text,
  ultimo_visto_in_fonte_at timestamptz,
  rigenerazioni_fallite    smallint NOT NULL DEFAULT 0,
  richiede_js              boolean  NOT NULL DEFAULT false,
  etag                     text,
  last_modified            text,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT bando_controllo_priorita_check
    CHECK (priorita_controllo >= 0 AND priorita_controllo <= 100),
  CONSTRAINT bando_controllo_volatilita_check
    CHECK (volatilita >= 0.5 AND volatilita <= 2.0)
);

COMMENT ON COLUMN public.bando_controllo.ultimo_visto_in_fonte_at IS
  'Ultima presenza nel listing della fonte. Diverso da bando_link.ultimo_visto_at, che è l''ultimo 2xx di un link.';
COMMENT ON COLUMN public.bando_controllo.testo_norm IS
  'Testo normalizzato compresso: senza un «prima» non esiste diff, e descrizione_raw è NULL ovunque.';

REVOKE ALL ON TABLE public.bando_controllo FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.bando_controllo TO service_role;
-- Il GRANT di colonna (bando_id, ultimo_controllo_at) ad anon arriva con la
-- migrazione 05, insieme alla vista che è l'unica a usarlo.

ALTER TABLE public.bando_controllo ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS bando_controllo_public_read ON public.bando_controllo;
CREATE POLICY bando_controllo_public_read ON public.bando_controllo
  FOR SELECT TO anon
  USING (EXISTS (SELECT 1 FROM public.bando b WHERE b.id = bando_controllo.bando_id AND b.pubblicato));
DROP POLICY IF EXISTS bando_controllo_service_all ON public.bando_controllo;
CREATE POLICY bando_controllo_service_all ON public.bando_controllo
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE INDEX IF NOT EXISTS bando_controllo_coda_idx
  ON public.bando_controllo (priorita_controllo DESC, prossimo_controllo_at);

DROP TRIGGER IF EXISTS trg_bando_controllo_updated_at ON public.bando_controllo;
CREATE TRIGGER trg_bando_controllo_updated_at
  BEFORE UPDATE ON public.bando_controllo
  FOR EACH ROW EXECUTE FUNCTION public.set_current_timestamp_updated_at();

-- ===========================================================================
-- 8. Backfill (idempotente; nessuna riga di `bando` viene aggiornata, quindi
--    non serve disattivare i trigger `updated_at` — il controllo in fondo lo
--    dimostra)
-- ===========================================================================

-- 8.a Un `bando_link` per ogni URL già presente sulle righe. Tutti
--     `pubblicabile=false`: la pubblicabilità la conquista `link-verifica`
--     con un 2xx e la presenza nell'HTML della pagina di riferimento.
INSERT INTO public.bando_link (bando_id, url, tipo, origine, pubblicabile)
SELECT DISTINCT ON (b.id, public.bando_normalizza_url(btrim(b.link_bando)))
       b.id, btrim(b.link_bando), 'pagina_bando', 'raw', false
  FROM public.bando b
 WHERE b.link_bando IS NOT NULL
   AND btrim(b.link_bando) <> ''
   AND public.bando_normalizza_url(btrim(b.link_bando)) IS NOT NULL
 ORDER BY b.id, public.bando_normalizza_url(btrim(b.link_bando))
ON CONFLICT DO NOTHING;

INSERT INTO public.bando_link (bando_id, url, tipo, origine, pubblicabile)
SELECT DISTINCT ON (b.id, public.bando_normalizza_url(btrim(b.link_candidatura)))
       b.id, btrim(b.link_candidatura), 'candidatura', 'raw', false
  FROM public.bando b
 WHERE b.link_candidatura IS NOT NULL
   AND btrim(b.link_candidatura) <> ''
   AND public.bando_normalizza_url(btrim(b.link_candidatura)) IS NOT NULL
 ORDER BY b.id, public.bando_normalizza_url(btrim(b.link_candidatura))
ON CONFLICT DO NOTHING;

INSERT INTO public.bando_link (bando_id, url, tipo, origine, pubblicabile, etichetta)
SELECT DISTINCT ON (x.bando_id, x.url_norm)
       x.bando_id, x.url, 'allegato', 'raw', false, x.etichetta
  FROM (
    SELECT b.id AS bando_id,
           btrim(e.value ->> 'url') AS url,
           public.bando_normalizza_url(btrim(e.value ->> 'url')) AS url_norm,
           nullif(btrim(coalesce(e.value ->> 'label', e.value ->> 'nome', '')), '') AS etichetta
      FROM public.bando b
           CROSS JOIN LATERAL jsonb_array_elements(
             CASE WHEN jsonb_typeof(b.allegati) = 'array' THEN b.allegati ELSE '[]'::jsonb END
           ) AS e(value)
     WHERE jsonb_typeof(e.value) = 'object'
  ) x
 WHERE x.url IS NOT NULL AND x.url <> '' AND x.url_norm IS NOT NULL
 ORDER BY x.bando_id, x.url_norm
ON CONFLICT DO NOTHING;

-- 8.b Un evento `pubblicazione` leggibile per ogni pubblicato: è il flusso
--     iniziale del cursore, quello da cui un consumatore parte.
--     ORDER BY id: i cursori nascono nell'ordine degli id, non a caso.
INSERT INTO public.bando_evento
  (bando_id, tipo, origine, data_evento, rilevato_at, leggibile, in_aggiornamenti, verificato)
SELECT b.id,
       'pubblicazione',
       'pipeline',
       (coalesce(b.pubblicato_at, b.created_at, now()) AT TIME ZONE 'Europe/Rome')::date,
       coalesce(b.pubblicato_at, b.created_at, now()),
       true,
       false,
       false
  FROM public.bando b
 WHERE b.pubblicato
   AND NOT EXISTS (
     SELECT 1 FROM public.bando_evento e
      WHERE e.bando_id = b.id AND e.tipo = 'pubblicazione'
   )
 ORDER BY b.id
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 9. Auto-riparazione dei privilegi della 05 (riesecuzione)
-- ---------------------------------------------------------------------------
-- Riesecuzione con la 05 già applicata: le revoche di questo file sono
-- incondizionate e toglierebbero ad anon l'EXECUTE sull'allowlist e il GRANT
-- di COLONNA su `bando_controllo` (in PostgreSQL `REVOKE ALL ON TABLE` revoca
-- anche i privilegi di colonna), mandando la vista in 42501 — la sottoquery
-- scalare su `bando_controllo` c'è sia nella 05 sia nella 07. Se la vista
-- esiste, i grant si rimettono qui e basta: così la 02 è davvero rieseguibile
-- da sola. Solo ad `anon`: la 07 revoca tutto ad `authenticated` (D3).
DO $$
DECLARE fase_d boolean;
BEGIN
  IF to_regclass('public.bando_pubblico') IS NULL THEN
    RETURN;
  END IF;

  -- `bando_stato_effettivo` e il grant di colonna servono in ogni fase: la
  -- vista li usa anche dopo la 07.
  GRANT EXECUTE ON FUNCTION
    public.bando_stato_effettivo(text, date, boolean, time, date, time, timestamptz) TO anon;
  GRANT SELECT (bando_id, ultimo_controllo_at) ON TABLE public.bando_controllo TO anon;

  -- `dominio_di` e `bando_host_aggregatore` servono solo finché la vista
  -- maschera i link, cioè fino alla fase (c): in fase (d) la 07 li toglie
  -- (D6) e rimetterli qui sarebbe un privilegio di troppo. La fase (d) si
  -- riconosce dalla policy, come nella guardia della 05.
  SELECT EXISTS (SELECT 1 FROM pg_policies
                  WHERE schemaname = 'public' AND tablename = 'bando'
                    AND policyname = 'bando_public_read'
                    AND qual ILIKE '%pubblicato%'
                    AND qual NOT ILIKE '%stato_processing%')
    INTO fase_d;

  IF NOT fase_d THEN
    GRANT EXECUTE ON FUNCTION public.dominio_di(text) TO anon;
    GRANT EXECUTE ON FUNCTION public.bando_host_aggregatore(text) TO anon;
  END IF;

  RAISE NOTICE
    'vista bando_pubblico presente: ripristinati i grant della 05 revocati da questo file (fase (d): %)',
    fase_d;
END $$;

DO $$
DECLARE prima text; dopo text;
BEGIN
  SELECT impronta INTO prima FROM _v11_02_impronta;
  SELECT md5(string_agg(id::text || ':' || coalesce(updated_at::text, ''), ',' ORDER BY id))
    INTO dopo FROM public.bando;
  IF dopo IS DISTINCT FROM prima THEN
    RAISE EXCEPTION 'il backfill della 02 ha mosso updated_at su bando. Transazione annullata.';
  END IF;
END $$;

COMMIT;

-- ============================================================================
-- Riconciliazione (rieseguibile da sola)
-- ============================================================================
-- Recupera i link e gli eventi delle righe pubblicate dopo l'applicazione.
-- Sono gli stessi INSERT del punto 8: nessuno di loro tocca `bando`, quindi
-- non serve disattivare i trigger `updated_at`.
--
-- Promozione manuale degli eventi rimasti in attesa (se un bando è stato
-- pubblicato con un percorso che non passa da un UPDATE, per esempio un
-- INSERT già completed):
--
--   UPDATE bando_evento e
--      SET leggibile = leggibile
--     FROM bando b
--    WHERE b.id = e.bando_id
--      AND e.leggibile AND e.cursore IS NULL
--      AND (b.pubblicato OR b.bando_master_id IS NOT NULL OR b.ritirato_at IS NOT NULL);
--
-- Rivalutazione della pubblicabilità per dominio. Il trigger
-- `trg_bando_link_dominio` vale solo sulle scritture: le righe già inserite
-- NON vengono rivalutate. Va eseguita dopo ogni aggiunta alla blocklist e una
-- volta dopo questa migrazione (è la stessa query della Riconciliazione del
-- file `bando_v11_seed_dominio_ufficiale.sql`):
--
--   UPDATE bando_link SET pubblicabile = false
--    WHERE pubblicabile AND bando_host_aggregatore(dominio);
-- ============================================================================

-- ============================================================================
-- Verifica post-deploy
-- ============================================================================
-- 1) Oggetti creati.
--      SELECT table_name FROM information_schema.tables
--       WHERE table_schema='public'
--         AND table_name IN ('dominio_ufficiale','pipeline_run','fonte_run','pipeline_lock',
--                            'bando_evento','bando_link','bando_fusione','bando_slug_storico',
--                            'bando_controllo')
--       ORDER BY 1;
--      -- atteso: 9 righe
--
-- 2) Cursore assegnato a tutti gli eventi di pubblicazione.
--      SELECT count(*) AS eventi, count(cursore) AS con_cursore FROM bando_evento;
--      -- atteso: 2104 e 2104 (= count(*) from bando where pubblicato)
--      SELECT count(*) FROM bando WHERE pubblicato;
--
-- 3) Il cursore è monotono e senza duplicati.
--      SELECT count(*) - count(DISTINCT cursore) FROM bando_evento WHERE cursore IS NOT NULL;
--      -- atteso: 0
--
-- 4) Nessuna prova su aggregatore, e la degradazione è SILENZIOSA: l'INSERT
--    deve passare, non sollevare (in transazione, da annullare):
--      BEGIN;
--        INSERT INTO bando_evento (bando_id, tipo, origine, url_prova, citazione,
--                                  verificato, leggibile, in_aggiornamenti)
--        SELECT id, 'rettifica', 'worker', 'https://www.obiettivoeuropa.com/bandi/x', 'prova',
--               true, true, true
--          FROM bando WHERE pubblicato ORDER BY id LIMIT 1
--        RETURNING id, url_prova, verificato, in_aggiornamenti, cursore;
--        -- atteso: url_prova NULL, verificato false, in_aggiornamenti false,
--        --   cursore NON nullo. NESSUN errore 23514.
--      ROLLBACK;
--
-- 5) Un evento di tipo interno non diventa mai leggibile, e nemmeno qui si
--    solleva (da annullare):
--      BEGIN;
--        INSERT INTO bando_evento (bando_id, tipo, origine, leggibile, in_aggiornamenti)
--        SELECT id, 'segnale_fonte', 'worker', true, true
--          FROM bando WHERE pubblicato ORDER BY id LIMIT 1
--        RETURNING leggibile, in_aggiornamenti, cursore;
--        -- atteso: false, false, NULL. NESSUN errore 23514.
--      ROLLBACK;
--
-- 6) Un link su dominio aggregatore non è mai pubblicabile, qualunque sia
--    l'origine (è la garanzia §13.4; da annullare):
--      BEGIN;
--        INSERT INTO bando_link (bando_id, url, tipo, origine, esito_http,
--                                trovato_in_fonte_at, pubblicabile)
--        SELECT id, 'https://www.obiettivoeuropa.com/bandi/x', 'pagina_bando',
--               'aggregatore', 200, now(), true
--          FROM bando WHERE pubblicato ORDER BY id LIMIT 1
--        RETURNING pubblicabile, dominio;
--        -- atteso: pubblicabile false, dominio 'obiettivoeuropa.com'
--      ROLLBACK;
--    E il contro-esempio, che deve invece restare pubblicabile:
--      BEGIN;
--        INSERT INTO bando_link (bando_id, url, tipo, origine, esito_http,
--                                trovato_in_fonte_at, pubblicabile)
--        SELECT id, 'https://www.regione.marche.it/bandi/x', 'pagina_bando',
--               'aggregatore', 200, now(), true
--          FROM bando WHERE pubblicato ORDER BY id LIMIT 1
--        RETURNING pubblicabile;   -- atteso: true (conta il dominio, non l'origine)
--      ROLLBACK;
--
-- 7) Immutabilità (da annullare):
--      BEGIN;
--        UPDATE bando_evento SET tipo='proroga' WHERE id=(SELECT min(id) FROM bando_evento);
--        -- atteso: 23514
--      ROLLBACK;
--
-- 8) Privilegi. Per anon devono comparire SOLO le colonne del contratto.
--      SELECT table_name, grantee, privilege_type
--        FROM information_schema.role_table_grants
--       WHERE table_schema='public' AND grantee IN ('anon','authenticated')
--         AND table_name IN ('dominio_ufficiale','pipeline_run','fonte_run','pipeline_lock','bando_controllo')
--       ORDER BY 1,2;
--      -- atteso: 0 righe
--      SELECT table_name, column_name FROM information_schema.column_privileges
--       WHERE table_schema='public' AND grantee='anon'
--         AND table_name IN ('bando_evento','bando_link','bando_fusione','bando_slug_storico')
--       ORDER BY 1,2;
--      -- atteso: 18 colonne su bando_evento, 8 su bando_link, 6 su bando_fusione, 5 su bando_slug_storico
--      SELECT has_table_privilege('service_role','public.bando_evento','DELETE');
--      -- atteso: false
--      -- `bando_stato_effettivo` esiste ma NON è ancora eseguibile da anon
--      -- (il GRANT arriva con la 05):
--      SELECT has_function_privilege('anon',
--        'public.bando_stato_effettivo(text,date,boolean,time,date,time,timestamptz)', 'EXECUTE');
--      -- atteso: false
--
-- 9) Come anon. Il blocco è AUTO-CONTENUTO di proposito: `SET LOCAL` ha
--    effetto solo dentro una transazione, e fuori si limita a un WARNING
--    lasciando la query girare come `postgres` — cioè come proprietario delle
--    tabelle, che scavalca la RLS e rende VERI tutti gli esiti attesi. Vanno
--    incollate tutte e cinque le righe insieme; il ROLLBACK ripristina il ruolo.
--      BEGIN;
--        SET LOCAL ROLE anon;
--        SELECT count(*) FROM bando_evento;        -- atteso: = numero di eventi con cursore
--        SELECT count(*) FROM bando_link;          -- atteso: 0 (nessun link è ancora pubblicabile)
--        SELECT * FROM bando_evento LIMIT 1;       -- atteso: 42501 (select=* non è concesso)
--      ROLLBACK;
--
-- 10) Nessun `updated_at` mosso (sostituire :inizio):
--      SELECT count(*) FROM bando WHERE updated_at >= :inizio;   -- atteso: 0
-- ============================================================================
