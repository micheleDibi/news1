-- ==========================================
-- bando_v11_13_stato_da_verificare.sql
-- DB bandi: certezza dello stato
-- ==========================================
-- Scopo
--   Dice quando lo stato mostrato di un
--   bando non è certo e perché. Il motivo
--   si calcola alla lettura, come
--   stato_effettivo: nessuna riga di bando
--   cambia.
--
--   Il file:
--   1. aggiunge a bando_controllo 17
--      colonne della verifica dello stato,
--      con i loro CHECK e un trigger che
--      scarta le letture su domini non
--      verificanti;
--   2. concede ad anon 9 di quelle colonne
--      (la vista è security_invoker);
--   3. crea bando_stato_da_verificare(),
--      pura, gemella di stato_bando.py e di
--      stato-bando.ts (regola v2);
--   4. aggiunge alla vista bando_pubblico
--      cinque colonne in coda;
--   5. aggiunge alla lista bianca la riga
--      24 (chiusura del worker da «in
--      apertura»);
--   6. si controlla da solo: casi della
--      regola (blocco CERTEZZA), funzioni
--      di anon, conteggi, colonne.
--
-- Base della vista: la 05. Il 30/09/2026
--   la vista viva aveva le 44 colonne
--   della 05, nello stesso ordine, e la 07
--   non era applicata. La guardia lo
--   ricontrolla.
--
-- Fase: (b), additiva. Nessuna riga di
--   bando toccata, bando_applica_evento
--   non ridefinita, la 04 non rieseguita.
--
-- Precondizioni: la 12 (la guardia la
--   controlla), la 04 e la 05. Dopo questo
--   file la 07 e il suo rollback
--   richiedono la 13.
--
-- Rompe BandoFit? NO. La vista guadagna
--   cinque colonne in coda: una select con
--   colonne esplicite non cambia, e le
--   colonne nuove non si calcolano se non
--   si chiedono. Nessuna funzione nuova
--   diventa eseguibile oltre a
--   bando_stato_da_verificare, che serve
--   alla vista.
--
-- Come si applica
--   SQL Editor: incollare ed eseguire
--   l'INTERO file. Rieseguibile. Dopo,
--   riavviare il sender (lo schema si
--   legge una volta per processo).
--
-- Non rieseguire la 02 dopo la 13: il suo
--   REVOKE ALL toglie i 9 grant di colonna
--   e la vista risponde 42501 a ogni
--   select che nomina le sue cinque
--   colonne nuove (il sito le chiede). Se
--   è successo, rieseguire la 13: li
--   rimette.
--
-- COSA NON È REVERSIBILE
--   Il rollback toglie le 17 colonne:
--   le letture raccolte si perdono.
-- ==========================================

BEGIN;

SET LOCAL lock_timeout = '5s';


-- ------------------------------------------
-- 1. Guardie
-- ------------------------------------------
DO $$
DECLARE
  v_col text[];
  v_05 text[] := ARRAY[
    'id', 'slug', 'titolo',
    'titolo_breve', 'descrizione_breve',
    'contenuto', 'livello',
    'ente_erogatore', 'area_geografica',
    'tematica', 'data_pubblicazione',
    'data_apertura', 'data_scadenza',
    'ora_apertura', 'ora_scadenza',
    'data_pubblicazione_verificata',
    'data_apertura_verificata',
    'data_scadenza_verificata',
    'importo_totale_eur',
    'importo_max_per_progetto_eur',
    'stato_bando',
    'stato_bando_verificato',
    'stato_effettivo',
    'tipologia_bando_id',
    'modalita_erogazione_id',
    'programma_id',
    'fonte_ufficiale_stato',
    'fonte_ufficiale_tipo',
    'fonte_ufficiale_e_atto',
    'fonte_ufficiale_url',
    'fonte_ufficiale_host',
    'fonte_ufficiale_verificata_at',
    'ultimo_controllo_at',
    'link_candidatura',
    'link_candidatura_source',
    'allegati', 'titolo_raw',
    'descrizione_raw', 'stato_processing',
    'link_bando', 'ricerca',
    'pubblicato_at', 'created_at',
    'ultimo_cambiamento_at'];
  v_13 text[] := ARRAY[
    'stato_da_verificare', 'stato_letto',
    'stato_letto_at', 'termine_indicato',
    'termine_indicato_fonte'];
  v_def text;
  v_pezzo text;
BEGIN
  IF to_regclass(
       'public.monitoraggio_riepilogo')
     IS NULL THEN
    RAISE EXCEPTION
      'applicare prima la 12 '
      '(bando_v11_12_monitoraggio.sql)';
  END IF;
  IF to_regprocedure(
       'public.bando_dominio_verificante'
       || '(text)') IS NULL
     OR to_regprocedure(
       'public.dominio_di(text)') IS NULL
     OR to_regclass(
       'public.bando_transizione') IS NULL
  THEN
    RAISE EXCEPTION
      'mancano oggetti della 02 o della '
      '04: applicarle prima';
  END IF;

  SELECT array_agg(c.column_name::text
           ORDER BY c.ordinal_position)
    INTO v_col
    FROM information_schema.columns c
   WHERE c.table_schema = 'public'
     AND c.table_name = 'bando_pubblico';
  IF v_col IS NULL THEN
    RAISE EXCEPTION
      'la vista bando_pubblico non esiste:'
      ' applicare prima la 05';
  END IF;
  IF NOT ('link_bando' = ANY (v_col)) THEN
    RAISE EXCEPTION
      'la 07 è applicata (la vista non ha '
      'link_bando): questo file ricreerebbe'
      ' le colonne deprecate. Fermarsi e '
      'scrivere al produttore.';
  END IF;
  IF v_col <> v_05
     AND v_col <> v_05 || v_13 THEN
    RAISE EXCEPTION
      'colonne della vista inattese: %',
      array_to_string(v_col, ', ');
  END IF;

  v_def := pg_get_viewdef(
    'public.bando_pubblico'::regclass);
  FOREACH v_pezzo IN ARRAY ARRAY[
    'bando_stato_effettivo(',
    'bando_host_aggregatore(',
    'ultimo_controllo_at',
    'fonte_ufficiale_link_id',
    'FROM bando b']
  LOOP
    IF position(v_pezzo IN v_def) = 0
    THEN
      RAISE EXCEPTION
        'la vista viva non contiene %: '
        'non è quella della 05', v_pezzo;
    END IF;
  END LOOP;
  -- pg_get_viewdef toglie il prefisso b.
  -- quando non serve.
  IF v_def !~ 'WHERE\s+(b\.)?pubblicato'
  THEN
    RAISE EXCEPTION
      'la vista viva non filtra su '
      'pubblicato: non è quella della 05';
  END IF;
END
$$;

-- Fotografie per il blocco di verifica.
DROP TABLE IF EXISTS pg_temp._m13_anon;
CREATE TEMP TABLE _m13_anon AS
SELECT p.oid AS f
  FROM pg_proc p
  JOIN pg_namespace n
    ON n.oid = p.pronamespace
 WHERE n.nspname = 'public'
   AND has_function_privilege(
         'anon', p.oid, 'EXECUTE');

DROP TABLE IF EXISTS pg_temp._m13_conti;
CREATE TEMP TABLE _m13_conti AS
SELECT v.stato_effettivo AS s,
       count(*) AS n
  FROM public.bando_pubblico v
 GROUP BY 1;

DROP TABLE IF EXISTS pg_temp._m13_bandi;
CREATE TEMP TABLE _m13_bandi AS
SELECT count(*) AS n FROM public.bando;


-- ------------------------------------------
-- 2. Colonne di bando_controllo
-- ------------------------------------------
-- Nell'ordine di db.COLONNE_LETTURA_STATO.
-- stato_letto* è l'ultima lettura della
-- pagina ufficiale; lettura_stato è il
-- dettaglio interno (storia comprese);
-- esaminato_attivo_at si scrive solo in
-- attivo; segnale_aggregatore* lo scrive
-- la lettura del listing.
ALTER TABLE public.bando_controllo
  ADD COLUMN IF NOT EXISTS
    stato_letto text,
  ADD COLUMN IF NOT EXISTS
    stato_letto_su text,
  ADD COLUMN IF NOT EXISTS
    stato_letto_at timestamptz,
  ADD COLUMN IF NOT EXISTS
    stato_letto_url text,
  ADD COLUMN IF NOT EXISTS
    stato_letto_citazione text,
  ADD COLUMN IF NOT EXISTS
    stato_letto_metodo text,
  ADD COLUMN IF NOT EXISTS
    lettura_stato jsonb,
  ADD COLUMN IF NOT EXISTS
    lettura_stato_at timestamptz,
  ADD COLUMN IF NOT EXISTS
    prossima_lettura_at timestamptz,
  ADD COLUMN IF NOT EXISTS
    letture_stato_nulle smallint
    NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS
    previsto_entro date,
  ADD COLUMN IF NOT EXISTS
    termine_indicato date,
  ADD COLUMN IF NOT EXISTS
    esaminato_attivo_at timestamptz,
  ADD COLUMN IF NOT EXISTS
    termine_indicato_fonte text,
  ADD COLUMN IF NOT EXISTS
    segnale_aggregatore text,
  ADD COLUMN IF NOT EXISTS
    segnale_aggregatore_at timestamptz,
  ADD COLUMN IF NOT EXISTS
    trattenuto_dal timestamptz;

-- I CHECK si tolgono e si rimettono: così
-- una riesecuzione li riporta al testo di
-- questo file.
ALTER TABLE public.bando_controllo
  DROP CONSTRAINT IF EXISTS
    bando_controllo_stato_letto_check,
  DROP CONSTRAINT IF EXISTS
    bando_controllo_metodo_check,
  DROP CONSTRAINT IF EXISTS
    bando_controllo_termine_fonte_check,
  DROP CONSTRAINT IF EXISTS
    bando_controllo_segnale_check,
  DROP CONSTRAINT IF EXISTS
    bando_controllo_lettura_completa,
  DROP CONSTRAINT IF EXISTS
    bando_controllo_termine_con_fonte;

ALTER TABLE public.bando_controllo
  ADD CONSTRAINT
    bando_controllo_stato_letto_check
    CHECK (stato_letto IN (
      'in apertura prossimamente',
      'aperto', 'chiuso', 'uscito')),
  ADD CONSTRAINT
    bando_controllo_metodo_check
    CHECK (stato_letto_metodo IN (
      'estrattore', 'modello')),
  ADD CONSTRAINT
    bando_controllo_termine_fonte_check
    CHECK (termine_indicato_fonte IN (
      'calendario_ufficiale', 'pagina',
      'testo', 'aggregatore')),
  ADD CONSTRAINT
    bando_controllo_segnale_check
    CHECK (segnale_aggregatore IN (
      'assente_dal_listing', 'in_uscita',
      'scadenza_passata')),
  ADD CONSTRAINT
    bando_controllo_lettura_completa
    CHECK (stato_letto IS NULL
      OR (stato_letto_su IS NOT NULL
      AND stato_letto_at IS NOT NULL
      AND stato_letto_url IS NOT NULL
      AND stato_letto_citazione
          IS NOT NULL
      AND stato_letto_metodo
          IS NOT NULL)),
  ADD CONSTRAINT
    bando_controllo_termine_con_fonte
    CHECK ((termine_indicato IS NULL)
      = (termine_indicato_fonte IS NULL));


-- ------------------------------------------
-- 3. Trigger: solo letture verificanti
-- ------------------------------------------
-- Una lettura vale solo se la pagina sta
-- su un dominio verificante (stessa regola
-- del trigger di bando_evento). Altrimenti
-- le sei colonne stato_letto* tornano
-- NULL, prima dei CHECK. Scrivono solo
-- service_role e il proprietario.
CREATE OR REPLACE FUNCTION
  public.bando_lettura_verificante()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NEW.stato_letto IS NOT NULL
     AND public.bando_dominio_verificante(
           public.dominio_di(
             NEW.stato_letto_url))
         IS NOT TRUE
  THEN
    NEW.stato_letto := NULL;
    NEW.stato_letto_su := NULL;
    NEW.stato_letto_at := NULL;
    NEW.stato_letto_url := NULL;
    NEW.stato_letto_citazione := NULL;
    NEW.stato_letto_metodo := NULL;
  END IF;
  RETURN NEW;
END
$$;

REVOKE ALL ON FUNCTION
  public.bando_lettura_verificante()
  FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE TRIGGER
  bando_controllo_lettura_verificante
  BEFORE INSERT OR UPDATE
  ON public.bando_controllo
  FOR EACH ROW EXECUTE FUNCTION
  public.bando_lettura_verificante();


-- ------------------------------------------
-- 4. Colonne leggibili da anon
-- ------------------------------------------
-- Le nove che la vista legge. Si aggiungono
-- a bando_id e ultimo_controllo_at (05).
GRANT SELECT (
  stato_letto,
  stato_letto_su,
  stato_letto_at,
  stato_letto_metodo,
  previsto_entro,
  termine_indicato,
  esaminato_attivo_at,
  segnale_aggregatore_at,
  termine_indicato_fonte
) ON TABLE public.bando_controllo
  TO anon;


-- ------------------------------------------
-- 5. bando_stato_da_verificare (regola v2)
-- ------------------------------------------
-- Gemella di stato_da_verificare() in
-- scraper_bandi/app/stato_bando.py e di
-- statoDaVerificare() in
-- src/lib/stato-bando.ts; i casi sono la
-- sezione certezza di
-- tests/stato-bando/casi.json (blocco
-- CERTEZZA qui sotto).
-- Vince la prima regola, nell'ordine
-- definitivo (contratto del giro 2,
-- §19.3): le etichette restano quelle di
-- sempre, cambia solo l'ordine.
-- R0: stato effettivo «in apertura» ->
--   ramo I; «aperto» senza scadenza ->
--   ramo A; altrimenti NULL.
-- I1 apertura verificata con data -> NULL
-- I2 data_apertura < oggi
--    -> data_apertura_passata
-- I3 lettura aperto|chiuso|uscito
--    -> smentito_dalla_fonte
-- I6bis mai esaminato in attivo -> NULL
-- I4 previsto_entro < oggi
--    -> previsione_scaduta
-- I5 lettura «in apertura» di al massimo
--    30 giorni fa -> NULL
-- I6 pubblicato da al massimo 3 giorni
--    -> NULL
-- I7 -> senza_conferma
-- A1 lettura chiuso|uscito|in apertura
--    -> smentito_dalla_fonte
-- A2 lettura «aperto» dell'estrattore di
--    al massimo 30 giorni fa, più recente
--    del segnale dell'aggregatore -> NULL
-- A4 mai esaminato in attivo -> NULL
-- A3 termine_indicato < oggi
--    -> termine_passato
-- A5 segnale dell'aggregatore
--    -> senza_conferma
-- A6 termine_indicato da oggi -> NULL
-- A7 pubblicato da al massimo 7 giorni
--    -> NULL
-- A8 -> senza_conferma
-- Lettura valida: stato_letto fra i
-- quattro, stato_letto_su = stato e
-- stato_letto_at presente. «Giorni fa» è
-- la differenza fra date civili di Roma.
CREATE OR REPLACE FUNCTION
  public.bando_stato_da_verificare(
    p_stato text,
    p_data_apertura date,
    p_apertura_verificata boolean,
    p_ora_apertura time,
    p_data_scadenza date,
    p_ora_scadenza time,
    p_pubblicato_at timestamptz,
    p_previsto_entro date,
    p_termine_indicato date,
    p_stato_letto text,
    p_stato_letto_su text,
    p_stato_letto_at timestamptz,
    p_stato_letto_metodo text,
    p_esaminato_attivo_at timestamptz,
    p_segnale_aggregatore_at timestamptz,
    p_adesso timestamptz DEFAULT now())
RETURNS text
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
  SELECT CASE
    WHEN x.se = 'in apertura prossimamente'
    THEN CASE
      WHEN p_apertura_verificata IS TRUE
       AND p_data_apertura IS NOT NULL
        THEN NULL
      WHEN p_data_apertura < x.oggi
        THEN 'data_apertura_passata'
      WHEN x.lettura IN (
             'aperto', 'chiuso', 'uscito')
        THEN 'smentito_dalla_fonte'
      WHEN p_esaminato_attivo_at IS NULL
        THEN NULL
      WHEN p_previsto_entro < x.oggi
        THEN 'previsione_scaduta'
      WHEN x.lettura
           = 'in apertura prossimamente'
       AND x.oggi - x.letto_il <= 30
        THEN NULL
      WHEN x.oggi - x.pubblicato_il <= 3
        THEN NULL
      ELSE 'senza_conferma'
    END
    WHEN x.se = 'aperto'
     AND p_data_scadenza IS NULL
    THEN CASE
      WHEN x.lettura IN (
             'chiuso', 'uscito',
             'in apertura prossimamente')
        THEN 'smentito_dalla_fonte'
      WHEN x.lettura = 'aperto'
       AND p_stato_letto_metodo
           = 'estrattore'
       AND x.oggi - x.letto_il <= 30
       AND (p_segnale_aggregatore_at
              IS NULL
         OR p_stato_letto_at
              > p_segnale_aggregatore_at)
        THEN NULL
      WHEN p_esaminato_attivo_at IS NULL
        THEN NULL
      WHEN p_termine_indicato < x.oggi
        THEN 'termine_passato'
      WHEN p_segnale_aggregatore_at
           IS NOT NULL
        THEN 'senza_conferma'
      WHEN p_termine_indicato IS NOT NULL
        THEN NULL
      WHEN x.oggi - x.pubblicato_il <= 7
        THEN NULL
      ELSE 'senza_conferma'
    END
  END
  FROM (
    SELECT
      public.bando_stato_effettivo(
        p_stato, p_data_apertura,
        p_apertura_verificata,
        p_ora_apertura, p_data_scadenza,
        p_ora_scadenza, p_adesso) AS se,
      (p_adesso AT TIME ZONE
        'Europe/Rome')::date AS oggi,
      CASE
        WHEN p_stato_letto IN (
               'in apertura prossimamente',
               'aperto', 'chiuso',
               'uscito')
         AND p_stato_letto_su = p_stato
         AND p_stato_letto_at IS NOT NULL
        THEN p_stato_letto
      END AS lettura,
      (p_stato_letto_at AT TIME ZONE
        'Europe/Rome')::date AS letto_il,
      (p_pubblicato_at AT TIME ZONE
        'Europe/Rome')::date
        AS pubblicato_il
  ) x
$$;

COMMENT ON FUNCTION
  public.bando_stato_da_verificare(
    text, date, boolean, time, date,
    time, timestamptz, date, date, text,
    text, timestamptz, text, timestamptz,
    timestamptz, timestamptz)
  IS 'Perché lo stato mostrato va '
     'verificato (regola v2), o NULL. '
     'Gemella di stato_bando.py e di '
     'stato-bando.ts: i casi sono in '
     'tests/stato-bando/casi.json.';

REVOKE ALL ON FUNCTION
  public.bando_stato_da_verificare(
    text, date, boolean, time, date,
    time, timestamptz, date, date, text,
    text, timestamptz, text, timestamptz,
    timestamptz, timestamptz)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
  public.bando_stato_da_verificare(
    text, date, boolean, time, date,
    time, timestamptz, date, date, text,
    text, timestamptz, text, timestamptz,
    timestamptz, timestamptz)
  TO anon, service_role;


-- ------------------------------------------
-- 6. La vista: la 05 più cinque colonne
-- ------------------------------------------
-- Il corpo è quello della 05, riscritto in
-- righe corte e identico nel significato.
-- Le colonne nuove stanno in coda: una
-- select esplicita non cambia.
-- stato_da_verificare NON dipende
-- dall'esistenza della riga di controllo:
-- la sottoquery parte da una riga fissa e
-- la unisce con LEFT JOIN, così un bando
-- senza controllo ha comunque il suo
-- motivo (per esempio un «in apertura»
-- con la data passata). Sottoquery
-- scalari e non LEFT JOIN nel FROM, come
-- ultimo_controllo_at nella 05: una
-- colonna non chiesta non costa, e i
-- count=exact non cambiano.
-- stato_letto e stato_letto_at valgono
-- NULL se la lettura riguarda uno stato
-- diverso da quello di oggi o se non
-- viene da un estrattore: il sito non
-- mostra come «letto sulla pagina» una
-- lettura del modello.
CREATE OR REPLACE VIEW public.bando_pubblico
WITH (security_invoker = true) AS
SELECT
  b.id,
  b.slug,
  b.titolo,
  b.titolo_breve,
  b.descrizione_breve,
  CASE
    WHEN jsonb_typeof(b.contenuto)
         = 'object'
      THEN b.contenuto
  END AS contenuto,
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
     WHERE l.id = b.fonte_ufficiale_link_id
       AND l.tipo = 'atto'
  ) AS fonte_ufficiale_e_atto,
  b.fonte_ufficiale_url,
  b.fonte_ufficiale_host,
  b.fonte_ufficiale_verificata_at,
  (SELECT c.ultimo_controllo_at
     FROM public.bando_controllo c
    WHERE c.bando_id = b.id)
    AS ultimo_controllo_at,
  CASE
    WHEN b.link_candidatura IS NULL
      THEN NULL
    WHEN public.dominio_di(
           b.link_candidatura) IS NULL
      THEN NULL
    WHEN public.bando_host_aggregatore(
           public.dominio_di(
             b.link_candidatura))
      THEN NULL
    ELSE b.link_candidatura
  END AS link_candidatura,
  CASE
    WHEN b.link_candidatura IS NULL
      OR public.dominio_di(
           b.link_candidatura) IS NULL
      OR public.bando_host_aggregatore(
           public.dominio_di(
             b.link_candidatura))
      THEN NULL
    ELSE b.link_candidatura_source
  END AS link_candidatura_source,
  CASE
    WHEN jsonb_typeof(b.allegati)
         <> 'array'
      THEN b.allegati
    ELSE (
      SELECT coalesce(
               jsonb_agg(e.value),
               '[]'::jsonb)
        FROM jsonb_array_elements(
               b.allegati) AS e(value)
       WHERE NOT
         public.bando_host_aggregatore(
           public.dominio_di(
             e.value ->> 'url'))
    )
  END AS allegati,
  b.titolo_raw,
  b.descrizione_raw,
  'completed'::character varying
    AS stato_processing,
  CASE
    WHEN public.dominio_di(b.link_bando)
         IS NULL
      THEN NULL
    WHEN public.bando_host_aggregatore(
           public.dominio_di(
             b.link_bando))
      THEN NULL
    ELSE b.link_bando
  END AS link_bando,
  b.ricerca,
  b.pubblicato_at,
  b.created_at,
  b.ultimo_cambiamento_at,
  (SELECT
     public.bando_stato_da_verificare(
       b.stato_bando,
       b.data_apertura,
       b.data_apertura_verificata,
       b.ora_apertura,
       b.data_scadenza,
       b.ora_scadenza,
       b.pubblicato_at,
       c.previsto_entro,
       c.termine_indicato,
       c.stato_letto,
       c.stato_letto_su,
       c.stato_letto_at,
       c.stato_letto_metodo,
       c.esaminato_attivo_at,
       c.segnale_aggregatore_at,
       now())
     FROM (SELECT 1) AS uno
     LEFT JOIN public.bando_controllo c
       ON c.bando_id = b.id)
    AS stato_da_verificare,
  (SELECT CASE
            WHEN c.stato_letto_su
                 = b.stato_bando
             AND c.stato_letto_metodo
                 = 'estrattore'
              THEN c.stato_letto
          END
     FROM public.bando_controllo c
    WHERE c.bando_id = b.id)
    AS stato_letto,
  (SELECT CASE
            WHEN c.stato_letto_su
                 = b.stato_bando
             AND c.stato_letto_metodo
                 = 'estrattore'
              THEN c.stato_letto_at
          END
     FROM public.bando_controllo c
    WHERE c.bando_id = b.id)
    AS stato_letto_at,
  -- Il termine indicato si scrive anche in
  -- ombra: si espone solo dopo il primo
  -- esame in attivo. Il motivo qui sopra
  -- lo legge comunque (A3, A6).
  (SELECT CASE
            WHEN c.esaminato_attivo_at
                 IS NOT NULL
              THEN c.termine_indicato
          END
     FROM public.bando_controllo c
    WHERE c.bando_id = b.id)
    AS termine_indicato,
  (SELECT CASE
            WHEN c.termine_indicato
                 IS NOT NULL
             AND c.esaminato_attivo_at
                 IS NOT NULL
              THEN c.termine_indicato_fonte
          END
     FROM public.bando_controllo c
    WHERE c.bando_id = b.id)
    AS termine_indicato_fonte
FROM public.bando b
WHERE b.pubblicato;

COMMENT ON VIEW public.bando_pubblico IS
  'Contratto di lettura del DB bandi '
  '(§13). Contiene i soli pubblicati non '
  'fusi. La verità sullo stato è '
  'stato_effettivo, non stato_bando. Un '
  'id o uno slug che qui non si trova si '
  'risolve su bando_fusione / '
  'bando_slug_storico. '
  '`fonte_ufficiale_e_atto` è true solo '
  'se il link dell''atto è a sua volta '
  'PUBBLICABILE: la vista è '
  'security_invoker, quindi il flag '
  'dipende anche dalla RLS di bando_link '
  'e un ruolo interno può leggerlo true '
  'dove anon lo legge false. '
  'stato_da_verificare dice perché lo '
  'stato mostrato non è certo (NULL: '
  'nessuna prova contraria).';

REVOKE ALL ON TABLE public.bando_pubblico
  FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.bando_pubblico
  TO anon;
GRANT SELECT ON TABLE public.bando_pubblico
  TO service_role;


-- ------------------------------------------
-- 7. Casi della regola (generati)
-- ------------------------------------------
-- Il blocco qui sotto è generato da
-- tests/stato-bando/genera-sql.ts e npm
-- test lo confronta byte per byte. La
-- riga CREATE TEMP VIEW lo trasforma in
-- una vista temporanea: il blocco di
-- verifica si ferma se ha righe.
CREATE TEMP VIEW _m13_certezza AS
-- >>> CERTEZZA v2
-- Generato da tests/stato-bando/
-- genera-sql.ts: non modificare a mano.
-- Confronta la funzione
-- public.bando_stato_da_verificare()
-- con la sezione certezza di
-- tests/stato-bando/casi.json (127 casi).
-- Da eseguire nel SQL Editor dopo la 13:
-- atteso 0 righe.
with casi (
  id, stato, data_apertura,
  apertura_verificata, ora_apertura,
  data_scadenza, ora_scadenza, pubblicato_at,
  previsto_entro, termine_indicato,
  stato_letto, stato_letto_su,
  stato_letto_at, stato_letto_metodo,
  esaminato_attivo_at,
  segnale_aggregatore_at, adesso, atteso
) as (
  values
    ('r0-aperto-con-scadenza', 'aperto',
     NULL, NULL, NULL, '2026-10-31', NULL,
     '2026-09-01T10:00:00+00:00', NULL,
     '2026-09-01', 'chiuso', 'aperto',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('r0-aperto-scadenza-oggi', 'aperto',
     NULL, NULL, NULL, '2026-09-30', NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('r0-aperto-scaduto-oggi-ora', 'aperto',
     NULL, NULL, NULL, '2026-09-30', '10:00',
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('r0-aperto-scaduto', 'aperto', NULL,
     NULL, NULL, '2026-09-29', NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('r0-chiuso-letto-aperto', 'chiuso',
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'chiuso',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('r0-sospeso', 'sospeso', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('r0-sospeso-letto-chiuso', 'sospeso',
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'chiuso', 'sospeso',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('r0-revocato', 'revocato', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('r0-stato-null', NULL, NULL, NULL, NULL,
     NULL, NULL, '2026-09-01T10:00:00+00:00',
     NULL, NULL, NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('r0-stato-sconosciuto', 'boh', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('r0-in-apertura-scaduto',
     'in apertura prossimamente',
     '2026-09-01', NULL, NULL, '2026-09-29',
     NULL, '2026-09-01T10:00:00+00:00', NULL,
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('r0-in-apertura-raggiunto-scad',
     'in apertura prossimamente',
     '2026-09-20', true, NULL, '2026-10-31',
     NULL, '2026-09-01T10:00:00+00:00', NULL,
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('a4-in-apertura-raggiunto',
     'in apertura prossimamente',
     '2026-09-20', true, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL, NULL, NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('a1-in-apertura-raggiunto',
     'in apertura prossimamente',
     '2026-09-20', true, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'chiuso', 'in apertura prossimamente',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'smentito_dalla_fonte'),
    ('a8-in-apertura-raggiunto',
     'in apertura prossimamente',
     '2026-09-20', true, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a4-in-apertura-raggiunto-ora',
     'in apertura prossimamente',
     '2026-09-30', true, '09:00', NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL, NULL, NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i1-verificata-futura',
     'in apertura prossimamente',
     '2026-10-15', true, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i1-batte-smentita',
     'in apertura prossimamente',
     '2026-10-15', true, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00',
     '2026-09-01', NULL, 'chiuso',
     'in apertura prossimamente',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i1-oggi-ora-futura',
     'in apertura prossimamente',
     '2026-09-30', true, '18:00', NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i7-verificata-senza-data',
     'in apertura prossimamente', NULL, true,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('i2-data-passata',
     'in apertura prossimamente',
     '2026-09-29', false, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'data_apertura_passata'),
    ('i2-data-passata-verif-null',
     'in apertura prossimamente',
     '2026-09-01', NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'data_apertura_passata'),
    ('i2-batte-smentita',
     'in apertura prossimamente',
     '2026-09-29', NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'in apertura prossimamente',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'data_apertura_passata'),
    ('i2-batte-grazia',
     'in apertura prossimamente',
     '2026-09-29', NULL, NULL, NULL, NULL,
     '2026-09-29T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'data_apertura_passata'),
    ('i6-data-apertura-oggi',
     'in apertura prossimamente',
     '2026-09-30', NULL, NULL, NULL, NULL,
     '2026-09-29T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i2-mezzanotte-roma',
     'in apertura prossimamente',
     '2026-09-29', NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T00:30:00+02:00',
     'data_apertura_passata'),
    ('i6-apertura-ultimo-istante',
     'in apertura prossimamente',
     '2026-09-29', NULL, NULL, NULL, NULL,
     '2026-09-28T08:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-29T23:59:59+02:00', NULL),
    ('i3-letto-aperto',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'in apertura prossimamente',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'smentito_dalla_fonte'),
    ('i3-letto-chiuso-modello',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'chiuso', 'in apertura prossimamente',
     '2026-09-28T08:00:00+00:00', 'modello',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'smentito_dalla_fonte'),
    ('i3-letto-uscito',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'uscito', 'in apertura prossimamente',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'smentito_dalla_fonte'),
    ('i3-lettura-vecchia',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'in apertura prossimamente',
     '2026-05-01T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'smentito_dalla_fonte'),
    ('i3-batte-grazia',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-29T10:00:00+00:00', NULL, NULL,
     'aperto', 'in apertura prossimamente',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'smentito_dalla_fonte'),
    ('i3-batte-previsione',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00',
     '2026-09-01', NULL, 'chiuso',
     'in apertura prossimamente',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'smentito_dalla_fonte'),
    ('i7-letto-su-diverso',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('i6-letto-sconosciuto',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-29T10:00:00+00:00', NULL, NULL,
     'boh', 'in apertura prossimamente',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i6-lettura-senza-data',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-29T10:00:00+00:00', NULL, NULL,
     'aperto', 'in apertura prossimamente',
     NULL, 'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i4-previsione-scaduta',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00',
     '2026-09-29', NULL, NULL, NULL, NULL,
     NULL, '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'previsione_scaduta'),
    ('i4-batte-conferma',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00',
     '2026-09-29', NULL,
     'in apertura prossimamente',
     'in apertura prossimamente',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'previsione_scaduta'),
    ('i4-batte-grazia',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-29T10:00:00+00:00',
     '2026-09-29', NULL, NULL, NULL, NULL,
     NULL, '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'previsione_scaduta'),
    ('i5-previsione-oggi',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00',
     '2026-09-30', NULL,
     'in apertura prossimamente',
     'in apertura prossimamente',
     '2026-09-20T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i7-previsione-futura',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00',
     '2026-12-31', NULL, NULL, NULL, NULL,
     NULL, '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('i4-mezzanotte-roma',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00',
     '2026-09-29', NULL, NULL, NULL, NULL,
     NULL, '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T00:30:00+02:00',
     'previsione_scaduta'),
    ('i5-conferma-recente',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'in apertura prossimamente',
     'in apertura prossimamente',
     '2026-09-20T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i5-conferma-modello',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'in apertura prossimamente',
     'in apertura prossimamente',
     '2026-09-20T08:00:00+00:00', 'modello',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i5-confine-30-dentro',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'in apertura prossimamente',
     'in apertura prossimamente',
     '2026-08-31T00:10:00+02:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T23:30:00+02:00', NULL),
    ('i7-confine-31-fuori',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'in apertura prossimamente',
     'in apertura prossimamente',
     '2026-08-30T23:50:00+02:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T00:30:00+02:00',
     'senza_conferma'),
    ('i5-conferma-futura',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'in apertura prossimamente',
     'in apertura prossimamente',
     '2026-10-05T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i7-conferma-scaduta',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'in apertura prossimamente',
     'in apertura prossimamente',
     '2026-08-01T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('i6-pubblicato-recente',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-29T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i6-confine-3-dentro',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-27T00:10:00+02:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T23:30:00+02:00', NULL),
    ('i7-confine-4-fuori',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-26T23:50:00+02:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T00:30:00+02:00',
     'senza_conferma'),
    ('i6-ora-solare-dentro',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-10-24T00:10:00+02:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-10-27T23:50:00+01:00', NULL),
    ('i7-ora-solare-fuori',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-10-23T23:50:00+02:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-10-27T00:10:00+01:00',
     'senza_conferma'),
    ('i6-pubblicato-futuro',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-10-02T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i6-segnale-ignorato',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-29T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00',
     '2026-09-29T12:00:00+00:00',
     '2026-09-30T12:00:00+02:00', NULL),
    ('i6-termine-ignorato',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-29T10:00:00+00:00', NULL,
     '2026-09-01', NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i7-senza-conferma',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('i7-in-ombra',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL, NULL, NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i6bis-ombra-pubblicato-null',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL, NULL, NULL, NULL,
     NULL, NULL, NULL, NULL, NULL, NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i6bis-ombra-conferma-scaduta',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'in apertura prossimamente',
     'in apertura prossimamente',
     '2026-08-01T08:00:00+00:00',
     'estrattore', NULL, NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i6bis-ombra-scadenza-futura',
     'in apertura prossimamente', NULL, NULL,
     NULL, '2026-12-31', NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL, NULL, NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i6bis-ombra-previsione-futura',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00',
     '2026-12-31', NULL, NULL, NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i6bis-ombra-confine-4-fuori',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-26T23:50:00+02:00', NULL, NULL,
     NULL, NULL, NULL, NULL, NULL, NULL,
     '2026-09-30T00:30:00+02:00', NULL),
    ('i2-in-ombra',
     'in apertura prossimamente',
     '2026-09-29', NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL, NULL, NULL,
     '2026-09-30T12:00:00+02:00',
     'data_apertura_passata'),
    ('i3-in-ombra',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'chiuso', 'in apertura prossimamente',
     '2026-09-28T08:00:00+00:00',
     'estrattore', NULL, NULL,
     '2026-09-30T12:00:00+02:00',
     'smentito_dalla_fonte'),
    ('i4-in-ombra',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00',
     '2026-09-29', NULL, NULL, NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i4-in-attivo',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00',
     '2026-09-29', NULL, NULL, NULL, NULL,
     NULL, '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'previsione_scaduta'),
    ('i5-in-ombra',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'in apertura prossimamente',
     'in apertura prossimamente',
     '2026-09-20T08:00:00+00:00',
     'estrattore', NULL, NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i6-in-ombra',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-29T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL, NULL, NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('i7-pubblicato-null',
     'in apertura prossimamente', NULL, NULL,
     NULL, NULL, NULL, NULL, NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('i7-scadenza-futura',
     'in apertura prossimamente', NULL, NULL,
     NULL, '2026-12-31', NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a1-letto-chiuso', 'aperto', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'chiuso', 'aperto',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'smentito_dalla_fonte'),
    ('a1-letto-uscito-modello', 'aperto',
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'uscito', 'aperto',
     '2026-09-28T08:00:00+00:00', 'modello',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'smentito_dalla_fonte'),
    ('a1-letto-in-apertura', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'in apertura prossimamente', 'aperto',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'smentito_dalla_fonte'),
    ('a1-lettura-vecchia', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'chiuso', 'aperto',
     '2026-05-01T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'smentito_dalla_fonte'),
    ('a1-in-ombra', 'aperto', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'chiuso', 'aperto',
     '2026-09-28T08:00:00+00:00',
     'estrattore', NULL, NULL,
     '2026-09-30T12:00:00+02:00',
     'smentito_dalla_fonte'),
    ('a1-batte-termine-futuro', 'aperto',
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL,
     '2026-12-31', 'chiuso', 'aperto',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'smentito_dalla_fonte'),
    ('a1-batte-grazia', 'aperto', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-29T10:00:00+00:00', NULL, NULL,
     'chiuso', 'aperto',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'smentito_dalla_fonte'),
    ('a8-letto-su-diverso', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'chiuso', 'in apertura prossimamente',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a8-letto-sconosciuto', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'boh', 'aperto',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a2-conferma', 'aperto', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-09-25T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('a2-batte-termine-passato', 'aperto',
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL,
     '2026-09-01', 'aperto', 'aperto',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('a2-confine-30-dentro', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-08-31T00:10:00+02:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T23:30:00+02:00', NULL),
    ('a8-confine-31-fuori', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-08-30T23:50:00+02:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T00:30:00+02:00',
     'senza_conferma'),
    ('a3-modello-termine-passato', 'aperto',
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL,
     '2026-09-29', 'aperto', 'aperto',
     '2026-09-28T08:00:00+00:00', 'modello',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'termine_passato'),
    ('a8-modello-non-conferma', 'aperto',
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-09-28T08:00:00+00:00', 'modello',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a2-segnale-prima', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-09-25T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00',
     '2026-09-20T08:00:00+00:00',
     '2026-09-30T12:00:00+02:00', NULL),
    ('a5-segnale-dopo', 'aperto', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-09-25T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00',
     '2026-09-27T08:00:00+00:00',
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a5-segnale-uguale', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-09-25T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00',
     '2026-09-25T08:00:00+00:00',
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a5-segnale-offset', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-09-25T12:30:00+02:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00',
     '2026-09-25T11:00:00+00:00',
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a2-segnale-offset-inverso', 'aperto',
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-09-25T11:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00',
     '2026-09-25T12:30:00+02:00',
     '2026-09-30T12:00:00+02:00', NULL),
    ('a5-segnale-dopo-termine-fut', 'aperto',
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL,
     '2026-12-31', 'aperto', 'aperto',
     '2026-09-25T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00',
     '2026-09-27T08:00:00+00:00',
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a8-conferma-su-diverso', 'aperto',
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'in apertura prossimamente',
     '2026-09-28T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a8-metodo-sconosciuto', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-09-28T08:00:00+00:00', 'boh',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a8-metodo-null', 'aperto', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-09-28T08:00:00+00:00', NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a2-conferma-futura', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-10-02T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('a4-ombra-segnale-dopo', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-09-25T08:00:00+00:00',
     'estrattore', NULL,
     '2026-09-27T08:00:00+00:00',
     '2026-09-30T12:00:00+02:00', NULL),
    ('a3-termine-ieri', 'aperto', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL,
     '2026-09-29', NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'termine_passato'),
    ('a6-termine-oggi', 'aperto', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL,
     '2026-09-30', NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('a3-in-ombra', 'aperto', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL,
     '2026-09-29', NULL, NULL, NULL, NULL,
     NULL, NULL, '2026-09-30T12:00:00+02:00',
     NULL),
    ('a3-in-attivo', 'aperto', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL,
     '2026-09-29', NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'termine_passato'),
    ('a3-mezzanotte-roma', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL,
     '2026-09-29', NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T00:30:00+02:00',
     'termine_passato'),
    ('a6-termine-ultimo-istante', 'aperto',
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL,
     '2026-09-29', NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-29T23:59:59+02:00', NULL),
    ('a3-batte-segnale', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL,
     '2026-09-29', NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00',
     '2026-09-27T08:00:00+00:00',
     '2026-09-30T12:00:00+02:00',
     'termine_passato'),
    ('a3-batte-grazia', 'aperto', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-29T10:00:00+00:00', NULL,
     '2026-09-29', NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'termine_passato'),
    ('a4-ombra', 'aperto', NULL, NULL, NULL,
     NULL, NULL, '2026-08-31T10:00:00+00:00',
     NULL, NULL, NULL, NULL, NULL, NULL,
     NULL, NULL, '2026-09-30T12:00:00+02:00',
     NULL),
    ('a4-ombra-segnale', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-27T08:00:00+00:00',
     '2026-09-30T12:00:00+02:00', NULL),
    ('a4-ombra-modello', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-09-28T08:00:00+00:00', 'modello',
     NULL, NULL, '2026-09-30T12:00:00+02:00',
     NULL),
    ('a4-ombra-pubblicato-null', 'aperto',
     NULL, NULL, NULL, NULL, NULL, NULL,
     NULL, NULL, NULL, NULL, NULL, NULL,
     NULL, NULL, '2026-09-30T12:00:00+02:00',
     NULL),
    ('a5-segnale', 'aperto', NULL, NULL,
     NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00',
     '2026-09-27T08:00:00+00:00',
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a5-segnale-termine-futuro', 'aperto',
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL,
     '2026-12-31', NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00',
     '2026-09-27T08:00:00+00:00',
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a5-segnale-batte-grazia', 'aperto',
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-29T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00',
     '2026-09-29T12:00:00+00:00',
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a5-segnale-conferma-vecchia', 'aperto',
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-08-01T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00',
     '2026-07-01T08:00:00+00:00',
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a6-termine-futuro', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL,
     '2026-10-31', NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('a6-termine-futuro-modello', 'aperto',
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL,
     '2026-10-31', 'aperto', 'aperto',
     '2026-09-28T08:00:00+00:00', 'modello',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('a7-grazia', 'aperto', NULL, NULL, NULL,
     NULL, NULL, '2026-09-29T10:00:00+00:00',
     NULL, NULL, NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('a7-confine-7-dentro', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-23T00:10:00+02:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T23:30:00+02:00', NULL),
    ('a8-confine-8-fuori', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-22T23:50:00+02:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T00:30:00+02:00',
     'senza_conferma'),
    ('a7-ora-solare-dentro', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-10-23T00:10:00+02:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-10-30T23:50:00+01:00', NULL),
    ('a8-ora-solare-fuori', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-10-23T23:50:00+02:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-10-31T00:10:00+01:00',
     'senza_conferma'),
    ('a7-pubblicato-futuro', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-10-02T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('a7-previsto-ignorato', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T10:00:00+00:00',
     '2026-09-01', NULL, NULL, NULL, NULL,
     NULL, '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('a8-senza-conferma', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a8-pubblicato-null', 'aperto', NULL,
     NULL, NULL, NULL, NULL, NULL, NULL,
     NULL, NULL, NULL, NULL, NULL,
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a8-conferma-scaduta', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-08-15T08:00:00+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00',
     'senza_conferma'),
    ('a2-frazione-5-cifre', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-09-25T08:00:00.87927+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00', NULL,
     '2026-09-30T12:00:00+02:00', NULL),
    ('a5-frazione-1-cifra', 'aperto', NULL,
     NULL, NULL, NULL, NULL,
     '2026-09-01T10:00:00+00:00', NULL, NULL,
     'aperto', 'aperto',
     '2026-09-25T08:00:00.87927+00:00',
     'estrattore',
     '2026-09-29T08:00:00+00:00',
     '2026-09-25T08:00:00.9+00:00',
     '2026-09-30T12:00:00+02:00',
     'senza_conferma')
), esiti as (
  select
    c.id,
    c.atteso,
    public.bando_stato_da_verificare(
      c.stato::text,
      c.data_apertura::date,
      c.apertura_verificata::boolean,
      c.ora_apertura::time,
      c.data_scadenza::date,
      c.ora_scadenza::time,
      c.pubblicato_at::timestamptz,
      c.previsto_entro::date,
      c.termine_indicato::date,
      c.stato_letto::text,
      c.stato_letto_su::text,
      c.stato_letto_at::timestamptz,
      c.stato_letto_metodo::text,
      c.esaminato_attivo_at::timestamptz,
      c.segnale_aggregatore_at::timestamptz,
      c.adesso::timestamptz
    ) as ottenuto
  from casi c
)
select e.id, e.atteso, e.ottenuto
from esiti e
where e.ottenuto is distinct from e.atteso
order by e.id;
-- <<< CERTEZZA v2


-- ------------------------------------------
-- 8. Lista bianca: la riga 24 (generata)
-- ------------------------------------------
-- >>> TRANSIZIONI delta 13
-- Generato da tests/stato-bando/
-- genera-sql.ts: non modificare a mano.
-- Righe di public.bando_transizione che
-- entrano con la migrazione 13 (campo
-- migrazione di tests/stato-bando/
-- casi.json). Rieseguibile: where not
-- exists come nel seed della 04.
insert into public.bando_transizione
  (da, a, attore, evento, condizione)
select v.da, v.a, v.attore, v.evento,
  v.condizione
from (values
  ('in apertura prossimamente'::text,
   'chiuso'::text, 'worker'::text,
   'chiusura'::text,
   'la pagina ufficiale dichiara '
    || 'chiuso, scaduto o concluso con '
    || 'etichetta strutturata; gate '
    || 'G1-G9, G7 per doppia lettura '
    || 'strutturata (contratto 6.1)')
) as v (da, a, attore, evento, condizione)
where not exists (
  select 1 from public.bando_transizione t
  where t.da is not distinct from v.da
    and t.a = v.a
    and t.attore = v.attore
    and t.evento = v.evento
)
on conflict do nothing;
-- <<< TRANSIZIONI delta 13


-- ------------------------------------------
-- 9. Verifica (si ferma al primo errore)
-- ------------------------------------------
DO $$
DECLARE
  v_f oid := to_regprocedure(
    'public.bando_stato_da_verificare('
    || 'text, date, boolean, time, '
    || 'date, time, timestamptz, date, '
    || 'date, text, text, timestamptz, '
    || 'text, timestamptz, timestamptz, '
    || 'timestamptz)');
  v_cat oid := to_regprocedure(
    'public.monitoraggio_catalogo(text)');
  v_elenco text;
  v_n bigint;
BEGIN
  IF v_f IS NULL THEN
    RAISE EXCEPTION
      'V1: manca bando_stato_da_verificare';
  END IF;

  SELECT count(*) INTO v_n
    FROM public.bando_transizione;
  IF v_n <> 24 THEN
    RAISE EXCEPTION
      'V2: la lista bianca ha % righe, '
      'attese 24', v_n;
  END IF;

  -- Funzioni di anon: DOPO = PRIMA più
  -- bando_stato_da_verificare.
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
       SELECT f FROM pg_temp._m13_anon
       EXCEPT
       SELECT v_f)
      UNION ALL
      (SELECT f FROM pg_temp._m13_anon
       EXCEPT
       SELECT p.oid
         FROM pg_proc p
        WHERE has_function_privilege(
                'anon', p.oid,
                'EXECUTE'))
    ) x;
  IF v_elenco IS NOT NULL THEN
    RAISE EXCEPTION
      'V3: funzioni di anon cambiate '
      'oltre la 13: %', v_elenco;
  END IF;
  IF v_cat IS NULL
     OR NOT has_function_privilege(
       'anon', v_cat, 'EXECUTE')
     OR NOT has_function_privilege(
       'anon', v_f, 'EXECUTE')
     OR has_function_privilege(
       'authenticated', v_f, 'EXECUTE')
     OR has_function_privilege('anon',
       'public.bando_lettura_verificante()',
       'EXECUTE')
  THEN
    RAISE EXCEPTION
      'V4: esecuzione delle funzioni '
      'sbagliata per anon o '
      'authenticated';
  END IF;

  -- anon legge di bando_controllo solo le
  -- 2 colonne della 05 più le 9 di qui;
  -- authenticated nessuna nuova.
  SELECT string_agg(a.attname::text, ', '
           ORDER BY a.attname)
    INTO v_elenco
    FROM pg_attribute a
   WHERE a.attrelid =
     'public.bando_controllo'::regclass
     AND a.attnum > 0
     AND NOT a.attisdropped
     AND has_column_privilege('anon',
       a.attrelid, a.attnum, 'SELECT');
  IF v_elenco IS DISTINCT FROM
       'bando_id, esaminato_attivo_at, '
    || 'previsto_entro, '
    || 'segnale_aggregatore_at, '
    || 'stato_letto, stato_letto_at, '
    || 'stato_letto_metodo, '
    || 'stato_letto_su, '
    || 'termine_indicato, '
    || 'termine_indicato_fonte, '
    || 'ultimo_controllo_at'
  THEN
    RAISE EXCEPTION
      'V5: colonne di bando_controllo '
      'leggibili da anon: %', v_elenco;
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_attribute a
     WHERE a.attrelid =
       'public.bando_controllo'::regclass
       AND a.attnum > 0
       AND NOT a.attisdropped
       AND has_column_privilege(
         'authenticated', a.attrelid,
         a.attnum, 'SELECT'))
  THEN
    RAISE EXCEPTION
      'V6: authenticated legge '
      'bando_controllo';
  END IF;

  -- Nessun bando toccato, conteggi della
  -- vista per stato invariati e uguali a
  -- quelli della tabella.
  IF (SELECT count(*) FROM public.bando)
     <> (SELECT n FROM pg_temp._m13_bandi)
  THEN
    RAISE EXCEPTION
      'V7: il numero di bandi è cambiato';
  END IF;
  SELECT string_agg(coalesce(d.s, '?'),
           ', ')
    INTO v_elenco
    FROM (
      (SELECT v.stato_effettivo AS s,
              count(*) AS n
         FROM public.bando_pubblico v
        GROUP BY 1
       EXCEPT
       SELECT s, n FROM pg_temp._m13_conti)
      UNION ALL
      (SELECT public.bando_stato_effettivo(
                b.stato_bando,
                b.data_apertura,
                b.data_apertura_verificata,
                b.ora_apertura,
                b.data_scadenza,
                b.ora_scadenza, now()),
              count(*)
         FROM public.bando b
        WHERE b.pubblicato
        GROUP BY 1
       EXCEPT
       SELECT s, n FROM pg_temp._m13_conti)
    ) d;
  IF v_elenco IS NOT NULL THEN
    RAISE EXCEPTION
      'V8: conteggi per stato diversi: %',
      v_elenco;
  END IF;

  -- Colonne della vista: le 44 della 05
  -- più le cinque in coda.
  SELECT count(*) INTO v_n
    FROM information_schema.columns c
   WHERE c.table_schema = 'public'
     AND c.table_name = 'bando_pubblico';
  IF v_n <> 49 OR (
    SELECT array_agg(c.column_name::text
             ORDER BY c.ordinal_position)
      FROM information_schema.columns c
     WHERE c.table_schema = 'public'
       AND c.table_name = 'bando_pubblico'
       AND c.ordinal_position > 44)
    <> ARRAY['stato_da_verificare',
       'stato_letto', 'stato_letto_at',
       'termine_indicato',
       'termine_indicato_fonte']
  THEN
    RAISE EXCEPTION
      'V9: colonne della vista inattese';
  END IF;

  -- I casi della regola: nessuna riga
  -- discordante.
  SELECT string_agg(k.id::text, ', ')
    INTO v_elenco
    FROM pg_temp._m13_certezza k;
  IF v_elenco IS NOT NULL THEN
    RAISE EXCEPTION
      'V10: casi di certezza discordanti:'
      ' %', v_elenco;
  END IF;

  -- Colonne, vincoli e trigger.
  SELECT count(*) INTO v_n
    FROM pg_constraint
   WHERE conrelid =
     'public.bando_controllo'::regclass
     AND conname IN (
       'bando_controllo_stato_letto_check',
       'bando_controllo_metodo_check',
       'bando_controllo_termine_fonte_check',
       'bando_controllo_segnale_check',
       'bando_controllo_lettura_completa',
       'bando_controllo_termine_con_fonte');
  IF v_n <> 6 OR NOT EXISTS (
    SELECT 1 FROM pg_trigger t
     WHERE t.tgrelid =
       'public.bando_controllo'::regclass
       AND t.tgname =
         'bando_controllo_lettura_'
         || 'verificante'
       AND NOT t.tgisinternal)
  THEN
    RAISE EXCEPTION
      'V11: mancano vincoli o trigger';
  END IF;

  RAISE NOTICE
    'migrazione 13: verifica superata';
END
$$;

DROP VIEW IF EXISTS pg_temp._m13_certezza;
DROP TABLE IF EXISTS pg_temp._m13_anon;
DROP TABLE IF EXISTS pg_temp._m13_conti;
DROP TABLE IF EXISTS pg_temp._m13_bandi;

NOTIFY pgrst, 'reload schema';

COMMIT;


-- ------------------------------------------
-- Verifica a mano (dopo il COMMIT)
-- ------------------------------------------
-- 1) Come anon, la vista risponde con le
--    colonne nuove. Incollare il blocco
--    intero: senza BEGIN, SET LOCAL non
--    vale e la query gira come
--    proprietario.
--      BEGIN;
--        SET LOCAL ROLE anon;
--        SELECT stato_da_verificare,
--               count(*)
--          FROM bando_pubblico
--         GROUP BY 1;
--      ROLLBACK;
--    In ombra (nessuna lettura in
--    attivo) l'unico motivo possibile è
--    data_apertura_passata.
--
-- 2) Verifica 7 della 05, prestazioni,
--    come anon (R1 del contratto DB §12,
--    prima pagina dei non chiusi). Da
--    rifare dopo il primo import completo
--    di IndicePA. Criterio: < 3 s, e
--    nessun Seq Scan su dominio_ufficiale.
--      BEGIN;
--        SET LOCAL ROLE anon;
--        EXPLAIN (ANALYZE, BUFFERS)
--        SELECT id, slug, titolo,
--               stato_effettivo,
--               data_scadenza, link_bando,
--               link_candidatura,
--               allegati,
--               stato_da_verificare
--          FROM bando_pubblico
--         WHERE stato_effettivo
--               IN ('aperto',
--               'in apertura prossimamente')
--         ORDER BY data_pubblicazione
--                  DESC NULLS LAST, id
--         LIMIT 20;
--      ROLLBACK;
