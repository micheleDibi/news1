-- ==========================================
-- bando_v11_13_stato_da_verificare_
--   rollback.sql
-- DB bandi: rollback della migrazione 13
-- ==========================================
-- Toglie quello che la 13 ha aggiunto e
-- nient'altro:
--   la vista torna quella della 05 (senza
--   le cinque colonne in coda), con gli
--   stessi GRANT e lo stesso COMMENT;
--   bando_stato_da_verificare();
--   il trigger
--   bando_controllo_lettura_verificante e
--   la sua funzione
--   bando_lettura_verificante();
--   i sei CHECK e le 17 colonne di
--   bando_controllo (con i loro GRANT di
--   colonna ad anon);
--   la riga 24 della lista bianca,
--   identificata da (da, a, attore,
--   evento).
--
-- Si rifiuta se la 07 è applicata: prima
--   il rollback della 07.
--
-- PRIMA del rollback, se il sito legge
--   dalla vista: BANDI_FONTE_LETTURA=bando
--   nell'unit del frontend e riavvio del
--   frontend. Il sito chiede alla vista le
--   cinque colonne della 13: senza questo
--   passo scheda, liste, corpus e API
--   rispondono 42703.
--
-- ATTENZIONE: le letture raccolte nelle
--   17 colonne si perdono. Dopo il
--   rollback riavviare il sender.
-- Rieseguibile.
-- ==========================================

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
  IF to_regclass('public.bando_pubblico')
     IS NULL THEN
    RAISE EXCEPTION
      'la vista bando_pubblico non esiste';
  END IF;
  IF NOT EXISTS (
    SELECT 1
      FROM information_schema.columns c
     WHERE c.table_schema = 'public'
       AND c.table_name = 'bando_pubblico'
       AND c.column_name = 'link_bando')
  THEN
    RAISE EXCEPTION
      'la 07 è applicata: eseguire prima '
      'bando_v11_07_fase_d_rollback.sql';
  END IF;
END
$$;


-- ------------------------------------------
-- 1. La vista della 05
-- ------------------------------------------
-- DROP e CREATE nella stessa transazione:
-- CREATE OR REPLACE non può togliere
-- colonne.
DROP VIEW IF EXISTS public.bando_pubblico;

CREATE VIEW public.bando_pubblico
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
  b.ultimo_cambiamento_at
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
  'dove anon lo legge false.';

REVOKE ALL ON TABLE public.bando_pubblico
  FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.bando_pubblico
  TO anon;
GRANT SELECT ON TABLE public.bando_pubblico
  TO service_role;


-- ------------------------------------------
-- 2. Funzione, trigger, vincoli, colonne
-- ------------------------------------------
DROP FUNCTION IF EXISTS
  public.bando_stato_da_verificare(
    text, date, boolean, time, date,
    time, timestamptz, date, date, text,
    text, timestamptz, text, timestamptz,
    timestamptz, timestamptz);

DROP TRIGGER IF EXISTS
  bando_controllo_lettura_verificante
  ON public.bando_controllo;
DROP FUNCTION IF EXISTS
  public.bando_lettura_verificante();

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
  DROP COLUMN IF EXISTS stato_letto,
  DROP COLUMN IF EXISTS stato_letto_su,
  DROP COLUMN IF EXISTS stato_letto_at,
  DROP COLUMN IF EXISTS stato_letto_url,
  DROP COLUMN IF EXISTS
    stato_letto_citazione,
  DROP COLUMN IF EXISTS
    stato_letto_metodo,
  DROP COLUMN IF EXISTS lettura_stato,
  DROP COLUMN IF EXISTS
    lettura_stato_at,
  DROP COLUMN IF EXISTS
    prossima_lettura_at,
  DROP COLUMN IF EXISTS
    letture_stato_nulle,
  DROP COLUMN IF EXISTS previsto_entro,
  DROP COLUMN IF EXISTS
    termine_indicato,
  DROP COLUMN IF EXISTS
    esaminato_attivo_at,
  DROP COLUMN IF EXISTS
    termine_indicato_fonte,
  DROP COLUMN IF EXISTS
    segnale_aggregatore,
  DROP COLUMN IF EXISTS
    segnale_aggregatore_at,
  DROP COLUMN IF EXISTS trattenuto_dal;


-- ------------------------------------------
-- 3. La riga 24 della lista bianca
-- ------------------------------------------
DELETE FROM public.bando_transizione
 WHERE da = 'in apertura prossimamente'
   AND a = 'chiuso'
   AND attore = 'worker'
   AND evento = 'chiusura';


-- ------------------------------------------
-- 4. Verifica
-- ------------------------------------------
DO $$
DECLARE
  v_n bigint;
BEGIN
  SELECT count(*) INTO v_n
    FROM information_schema.columns c
   WHERE c.table_schema = 'public'
     AND c.table_name = 'bando_pubblico';
  IF v_n <> 44 THEN
    RAISE EXCEPTION
      'rollback 13: la vista ha % '
      'colonne, attese 44', v_n;
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_proc
     WHERE proname IN (
       'bando_stato_da_verificare',
       'bando_lettura_verificante'))
  THEN
    RAISE EXCEPTION
      'rollback 13: una funzione è rimasta';
  END IF;
  IF EXISTS (
    SELECT 1
      FROM information_schema.columns c
     WHERE c.table_schema = 'public'
       AND c.table_name = 'bando_controllo'
       AND c.column_name IN (
         'stato_letto', 'lettura_stato',
         'termine_indicato',
         'esaminato_attivo_at',
         'segnale_aggregatore',
         'trattenuto_dal'))
  THEN
    RAISE EXCEPTION
      'rollback 13: una colonna è rimasta';
  END IF;
  SELECT count(*) INTO v_n
    FROM public.bando_transizione;
  IF v_n <> 23 THEN
    RAISE EXCEPTION
      'rollback 13: la lista bianca ha % '
      'righe, attese 23', v_n;
  END IF;
  RAISE NOTICE
    'rollback 13: verifica superata';
END
$$;

NOTIFY pgrst, 'reload schema';

COMMIT;
