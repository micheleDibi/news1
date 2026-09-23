-- ============================================================================
-- bando_v11_03_fonte_ufficiale.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Chiude l'anello fra `bando` e le tabelle della 02: le chiavi esterne
--   della provenienza (ogni data «verificata» deve avere l'evento che la
--   prova), la chiave esterna della fonte ufficiale, i vincoli di coerenza,
--   i trigger che congelano lo slug dei pubblicati e quelli che impediscono
--   a un aggregatore di diventare «fonte ufficiale». Semina infine
--   `bando_controllo` per i pubblicati, distribuendo i primi controlli su
--   14 giorni.
--
--   Le colonne esistono già tutte dalla 01: qui arrivano soltanto FK, CHECK,
--   indici e trigger. È la regola di dipendenza B3: un trigger che citasse
--   una colonna non ancora creata farebbe fallire ogni UPDATE della
--   pipeline.
--
-- Fase: (b).
--
-- Precondizioni
--   * `bando_v11_01_pubblicazione.sql` e `bando_v11_02_tabelle_di_servizio.sql`
--     applicate (guardie esplicite più sotto);
--   * `bando.id` integer, `bando_link.id` e `bando_evento.id` bigint: i tipi
--     delle colonne create dalla 01 devono corrispondere. Le guardie li
--     verificano e falliscono con un messaggio leggibile.
--
-- Rompe BandoFit? NO. Nessuna colonna cambia tipo o sparisce; i vincoli
--   nuovi riguardano solo combinazioni che oggi non esistono (nessuna riga
--   ha `fonte_ufficiale_*` valorizzato).
--   Cambia però il comportamento della PIPELINE: da qui in poi lo slug di un
--   bando pubblicato non si può più riscrivere senza dichiarare l'intenzione
--   nella GUC `bandi.slug_intent`.
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'INTERO file, dopo la 02 e dopo
--   `bando_v11_seed_dominio_ufficiale.sql` (il trigger anti-aggregatore
--   legge la blocklist). Rieseguibile.
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15min';

-- ---------------------------------------------------------------------------
-- 0. Guardie di precondizione
-- ---------------------------------------------------------------------------

DO $$
BEGIN
  IF to_regclass('public.bando_evento') IS NULL OR to_regclass('public.bando_link') IS NULL THEN
    RAISE EXCEPTION 'mancano bando_evento/bando_link: applicare prima bando_v11_02_tabelle_di_servizio.sql';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_attribute
                  WHERE attrelid = 'public.bando'::regclass
                    AND attname = 'fonte_ufficiale_link_id' AND NOT attisdropped) THEN
    RAISE EXCEPTION 'manca bando.fonte_ufficiale_link_id: applicare prima bando_v11_01_pubblicazione.sql';
  END IF;
END $$;

DO $$
DECLARE atteso text; trovato text;
BEGIN
  -- Le FK richiedono tipi compatibili: se il dump da cui è stata scritta la
  -- 01 non corrisponde al DB vivo, meglio saperlo qui che a metà file.
  SELECT format_type(atttypid, atttypmod) INTO atteso
    FROM pg_attribute WHERE attrelid = 'public.bando_evento'::regclass AND attname = 'id';
  SELECT format_type(atttypid, atttypmod) INTO trovato
    FROM pg_attribute WHERE attrelid = 'public.bando'::regclass AND attname = 'data_apertura_evento_id';
  IF atteso IS DISTINCT FROM trovato THEN
    RAISE EXCEPTION 'bando_evento.id è % ma bando.data_apertura_evento_id è %: allineare i tipi prima di creare le FK', atteso, trovato;
  END IF;

  SELECT format_type(atttypid, atttypmod) INTO atteso
    FROM pg_attribute WHERE attrelid = 'public.bando_link'::regclass AND attname = 'id';
  SELECT format_type(atttypid, atttypmod) INTO trovato
    FROM pg_attribute WHERE attrelid = 'public.bando'::regclass AND attname = 'fonte_ufficiale_link_id';
  IF atteso IS DISTINCT FROM trovato THEN
    RAISE EXCEPTION 'bando_link.id è % ma bando.fonte_ufficiale_link_id è %', atteso, trovato;
  END IF;

  SELECT format_type(atttypid, atttypmod) INTO atteso
    FROM pg_attribute WHERE attrelid = 'public.bando'::regclass AND attname = 'id';
  SELECT format_type(atttypid, atttypmod) INTO trovato
    FROM pg_attribute WHERE attrelid = 'public.bando'::regclass AND attname = 'bando_master_id';
  IF atteso IS DISTINCT FROM trovato THEN
    RAISE EXCEPTION 'bando.id è % ma bando.bando_master_id è %', atteso, trovato;
  END IF;
END $$;

CREATE TEMP TABLE _v11_03_impronta ON COMMIT DROP AS
SELECT md5(string_agg(
         id::text || ':' || coalesce(updated_at::text, '') || ':' || coalesce(ultimo_cambiamento_at::text, ''),
         ',' ORDER BY id)) AS impronta
  FROM public.bando;

-- ---------------------------------------------------------------------------
-- 1. Chiavi esterne
-- ---------------------------------------------------------------------------
-- ON DELETE: nessuna. Su queste tabelle non si cancella nulla (gli eventi
-- sono immutabili, gli id dei bandi non vengono mai riusati), quindi la
-- RESTRICT implicita è esattamente la garanzia che serve.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'public.bando'::regclass AND conname = 'bando_fonte_ufficiale_link_fk') THEN
    ALTER TABLE public.bando
      ADD CONSTRAINT bando_fonte_ufficiale_link_fk
      FOREIGN KEY (fonte_ufficiale_link_id) REFERENCES public.bando_link(id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'public.bando'::regclass AND conname = 'bando_data_pubblicazione_evento_fk') THEN
    ALTER TABLE public.bando
      ADD CONSTRAINT bando_data_pubblicazione_evento_fk
      FOREIGN KEY (data_pubblicazione_evento_id) REFERENCES public.bando_evento(id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'public.bando'::regclass AND conname = 'bando_data_apertura_evento_fk') THEN
    ALTER TABLE public.bando
      ADD CONSTRAINT bando_data_apertura_evento_fk
      FOREIGN KEY (data_apertura_evento_id) REFERENCES public.bando_evento(id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'public.bando'::regclass AND conname = 'bando_data_scadenza_evento_fk') THEN
    ALTER TABLE public.bando
      ADD CONSTRAINT bando_data_scadenza_evento_fk
      FOREIGN KEY (data_scadenza_evento_id) REFERENCES public.bando_evento(id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'public.bando'::regclass AND conname = 'bando_stato_bando_evento_fk') THEN
    ALTER TABLE public.bando
      ADD CONSTRAINT bando_stato_bando_evento_fk
      FOREIGN KEY (stato_bando_evento_id) REFERENCES public.bando_evento(id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'public.bando'::regclass AND conname = 'bando_master_fk') THEN
    ALTER TABLE public.bando
      ADD CONSTRAINT bando_master_fk
      FOREIGN KEY (bando_master_id) REFERENCES public.bando(id);
  END IF;
END $$;

-- Le FK non creano indici: senza questi, ogni INSERT su `bando_evento`
-- costerebbe una scansione di `bando` per la verifica referenziale inversa.
CREATE INDEX IF NOT EXISTS idx_bando_data_pubblicazione_evento
  ON public.bando (data_pubblicazione_evento_id) WHERE data_pubblicazione_evento_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_bando_data_apertura_evento
  ON public.bando (data_apertura_evento_id) WHERE data_apertura_evento_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_bando_data_scadenza_evento
  ON public.bando (data_scadenza_evento_id) WHERE data_scadenza_evento_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_bando_stato_bando_evento
  ON public.bando (stato_bando_evento_id) WHERE stato_bando_evento_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_bando_fonte_ufficiale_link
  ON public.bando (fonte_ufficiale_link_id) WHERE fonte_ufficiale_link_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2. Vincoli di provenienza e coerenza
-- ---------------------------------------------------------------------------
-- Nessuna data può dirsi verificata senza la data stessa e senza l'evento
-- che la prova.

ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_provenienza_data_pubblicazione;
ALTER TABLE public.bando
  ADD CONSTRAINT bando_provenienza_data_pubblicazione
  CHECK (NOT data_pubblicazione_verificata
         OR (data_pubblicazione IS NOT NULL AND data_pubblicazione_evento_id IS NOT NULL));

ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_provenienza_data_apertura;
ALTER TABLE public.bando
  ADD CONSTRAINT bando_provenienza_data_apertura
  CHECK (NOT data_apertura_verificata
         OR (data_apertura IS NOT NULL AND data_apertura_evento_id IS NOT NULL));

ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_provenienza_data_scadenza;
ALTER TABLE public.bando
  ADD CONSTRAINT bando_provenienza_data_scadenza
  CHECK (NOT data_scadenza_verificata
         OR (data_scadenza IS NOT NULL AND data_scadenza_evento_id IS NOT NULL));

ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_provenienza_stato;
ALTER TABLE public.bando
  ADD CONSTRAINT bando_provenienza_stato
  CHECK (NOT stato_bando_verificato OR stato_bando_evento_id IS NOT NULL);

-- «trovata» e «esiste il link» sono la stessa cosa: se uno dei due manca, il
-- pulsante pubblico punterebbe al nulla. Il coalesce rende il vincolo
-- deciso anche sulle righe nuove dello scrape, che nascono con lo stato NULL.
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_fonte_coerente;
ALTER TABLE public.bando
  ADD CONSTRAINT bando_fonte_coerente
  CHECK ((coalesce(fonte_ufficiale_stato, 'in_verifica') = 'trovata')
         = (fonte_ufficiale_link_id IS NOT NULL));

-- Identità delle righe sulle fonti che espongono una chiave (OE `raw_data.id`,
-- `nid`, `external_id`): due righe della stessa fonte non possono condividerla.
CREATE UNIQUE INDEX IF NOT EXISTS bando_fonte_chiave_esterna_uidx
  ON public.bando (fonte_id, chiave_esterna)
  WHERE chiave_esterna IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 3. Backfill — PRIMA dei trigger, e fra la disattivazione e la
--    riattivazione dei trigger che scrivono `updated_at` e
--    `ultimo_cambiamento_at` (M1)
-- ---------------------------------------------------------------------------
-- `trg_bando_cambiamento_pubblico` (migrazione 01) considera
-- `fonte_ufficiale_stato` una colonna pubblica: senza disattivarlo, il
-- backfill sposterebbe `ultimo_cambiamento_at` — e quindi il `lastmod` della
-- sitemap — su tutte le 5048 righe in un colpo solo.

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['trg_bando_set_updated_at', 'update_bando_updated_at', 'trg_bando_cambiamento_pubblico'] LOOP
    IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'public.bando'::regclass AND tgname = t) THEN
      EXECUTE format('ALTER TABLE public.bando DISABLE TRIGGER %I', t);
    END IF;
  END LOOP;
END $$;

-- 3.a Nessuna data è verificata finché non c'è un evento che lo prova: le
--     date che oggi vengono dall'aggregatore restano al loro posto (la
--     scadenza deve poter chiudere) ma non sono «verificate».
--     Il predicato è legato all'EVENTO, non al flag: una riesecuzione del
--     file non può più cancellare la provenienza già accumulata dal resolver.
UPDATE public.bando
   SET data_pubblicazione_verificata = (data_pubblicazione_verificata AND data_pubblicazione_evento_id IS NOT NULL),
       data_apertura_verificata      = (data_apertura_verificata      AND data_apertura_evento_id      IS NOT NULL),
       data_scadenza_verificata      = (data_scadenza_verificata      AND data_scadenza_evento_id      IS NOT NULL),
       stato_bando_verificato        = (stato_bando_verificato        AND stato_bando_evento_id        IS NOT NULL)
 WHERE (data_pubblicazione_verificata AND data_pubblicazione_evento_id IS NULL)
    OR (data_apertura_verificata      AND data_apertura_evento_id      IS NULL)
    OR (data_scadenza_verificata      AND data_scadenza_evento_id      IS NULL)
    OR (stato_bando_verificato        AND stato_bando_evento_id        IS NULL);

-- 3.b Tutto parte da «in verifica»: il resolver promuoverà a `trovata` o
--     `non_trovata`.
UPDATE public.bando
   SET fonte_ufficiale_stato = 'in_verifica'
 WHERE fonte_ufficiale_stato IS NULL;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['trg_bando_set_updated_at', 'update_bando_updated_at', 'trg_bando_cambiamento_pubblico'] LOOP
    IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'public.bando'::regclass AND tgname = t) THEN
      EXECUTE format('ALTER TABLE public.bando ENABLE TRIGGER %I', t);
    END IF;
  END LOOP;
END $$;

DO $$
DECLARE prima text; dopo text;
BEGIN
  SELECT impronta INTO prima FROM _v11_03_impronta;
  SELECT md5(string_agg(
           id::text || ':' || coalesce(updated_at::text, '') || ':' || coalesce(ultimo_cambiamento_at::text, ''),
           ',' ORDER BY id)) INTO dopo FROM public.bando;
  IF dopo IS DISTINCT FROM prima THEN
    RAISE EXCEPTION
      'il backfill della 03 ha mosso updated_at o ultimo_cambiamento_at: i trigger non erano disattivati. Transazione annullata.';
  END IF;
END $$;

-- 3.c Semina di `bando_controllo` per i pubblicati.
--     `prossimo_controllo_at = now() + (id % 336) ore` distribuisce i primi
--     controlli su 14 giorni in modo deterministico e rieseguibile: senza,
--     i 416 bandi a sportello scadrebbero tutti lo stesso giorno e il tetto
--     di fetch scatterebbe per costruzione.
INSERT INTO public.bando_controllo (bando_id, priorita_controllo, prossimo_controllo_at)
SELECT b.id,
       CASE
         -- in apertura con la data di apertura già passata: o è aperto e non
         -- lo sappiamo, o la data è sbagliata
         WHEN b.stato_bando = 'in apertura prossimamente'
              AND b.data_apertura IS NOT NULL
              AND b.data_apertura <= (now() AT TIME ZONE 'Europe/Rome')::date THEN 90
         -- scadenza entro 3 giorni: è la finestra in cui una proroga cambia
         -- tutto per il lettore
         WHEN b.data_scadenza IS NOT NULL
              AND b.data_scadenza BETWEEN (now() AT TIME ZONE 'Europe/Rome')::date
                                      AND ((now() AT TIME ZONE 'Europe/Rome')::date + 3) THEN 90
         -- link già istituzionale: il resolver chiude in un passo, a costo zero
         WHEN b.link_bando IS NOT NULL
              AND public.dominio_di(b.link_bando) IS NOT NULL
              AND NOT public.bando_host_aggregatore(public.dominio_di(b.link_bando)) THEN 70
         -- chiuso da oltre 180 giorni: interessa solo la graduatoria
         WHEN b.data_scadenza IS NOT NULL
              AND b.data_scadenza < ((now() AT TIME ZONE 'Europe/Rome')::date - 180) THEN 10
         ELSE 30
       END,
       now() + ((b.id % 336) * interval '1 hour')
  FROM public.bando b
 WHERE b.pubblicato
ON CONFLICT (bando_id) DO NOTHING;

-- 3.d Priorità delle righe create dal trigger 4.a. `bando_crea_controllo`
--     inserisce con la sola `prossimo_controllo_at` e lascia
--     `priorita_controllo` al DEFAULT 30: a una riesecuzione il 3.c non le
--     tocca (`ON CONFLICT DO NOTHING`), e un bando in scadenza fra due giorni
--     resterebbe in coda dietro a uno chiuso da un anno. Si riallineano solo
--     quelle mai controllate, con lo stesso CASE del 3.c.
UPDATE public.bando_controllo c
   SET priorita_controllo = x.priorita
  FROM (
    SELECT b.id AS bando_id,
           CASE
             WHEN b.stato_bando = 'in apertura prossimamente'
                  AND b.data_apertura IS NOT NULL
                  AND b.data_apertura <= (now() AT TIME ZONE 'Europe/Rome')::date THEN 90
             WHEN b.data_scadenza IS NOT NULL
                  AND b.data_scadenza BETWEEN (now() AT TIME ZONE 'Europe/Rome')::date
                                          AND ((now() AT TIME ZONE 'Europe/Rome')::date + 3) THEN 90
             WHEN b.link_bando IS NOT NULL
                  AND public.dominio_di(b.link_bando) IS NOT NULL
                  AND NOT public.bando_host_aggregatore(public.dominio_di(b.link_bando)) THEN 70
             WHEN b.data_scadenza IS NOT NULL
                  AND b.data_scadenza < ((now() AT TIME ZONE 'Europe/Rome')::date - 180) THEN 10
             ELSE 30
           END AS priorita
      FROM public.bando b
     WHERE b.pubblicato
  ) x
 WHERE c.bando_id = x.bando_id
   AND c.ultimo_controllo_at IS NULL
   AND c.priorita_controllo IS DISTINCT FROM x.priorita;

-- ---------------------------------------------------------------------------
-- 4. Trigger — solo ora che il backfill è chiuso
-- ---------------------------------------------------------------------------

-- 4.a Riga di controllo per ogni bando che diventa pubblico. Senza, un bando
--     nuovo non entrerebbe mai nella coda del monitor.
CREATE OR REPLACE FUNCTION public.bando_crea_controllo()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  INSERT INTO public.bando_controllo (bando_id, prossimo_controllo_at)
  VALUES (NEW.id, now() + ((NEW.id % 336) * interval '1 hour'))
  ON CONFLICT (bando_id) DO NOTHING;
  RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_crea_controllo() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_bando_crea_controllo ON public.bando;
CREATE TRIGGER trg_bando_crea_controllo
  AFTER INSERT OR UPDATE ON public.bando
  FOR EACH ROW
  -- NIENTE `OF pubblicato`: il flag non lo scrive mai chi fa l'UPDATE, lo alza
  -- il trigger BEFORE della 01, e `UPDATE OF` guarda la SET list, non il valore.
  WHEN (NEW.pubblicato)
  EXECUTE FUNCTION public.bando_crea_controllo();

-- 4.b Slug congelato. L'unico modo per rinominarlo è dichiarare lo slug
--     desiderato nella GUC `bandi.slug_intent` (è quello che fa
--     `bando_cambia_slug`, migrazione 04, che scrive anche il 301 nello
--     storico). Stessa filosofia dell'header X-Slug-Intent degli articoli:
--     l'intenzione si dichiara fuori dal payload, così un campo di troppo
--     non può rinominare mezzo archivio.
CREATE OR REPLACE FUNCTION public.bando_slug_congelato()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE intento text;
BEGIN
  IF NOT OLD.pubblicato OR OLD.slug IS NULL OR NEW.slug IS NOT DISTINCT FROM OLD.slug THEN
    RETURN NEW;
  END IF;

  intento := nullif(current_setting('bandi.slug_intent', true), '');

  IF intento IS NULL OR intento IS DISTINCT FROM NEW.slug THEN
    RAISE EXCEPTION
      'lo slug del bando % è congelato (% → %): serve set_config(''bandi.slug_intent'', <slug nuovo>, true) e la riga 301 nello storico',
      OLD.id, OLD.slug, NEW.slug
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_slug_congelato() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_bando_slug_congelato ON public.bando;
CREATE TRIGGER trg_bando_slug_congelato
  BEFORE UPDATE OF slug ON public.bando
  FOR EACH ROW EXECUTE FUNCTION public.bando_slug_congelato();

-- 4.c Uno slug ritirato o redirezionato non torna corrente. `_resolve_slug_collision`
--     dello step SEO legge anche lo storico, ma la garanzia deve stare a DB:
--     riusare uno slug 301 creerebbe un ciclo di redirect, riusarne uno 410
--     resusciterebbe una pagina che il committente ha chiesto di togliere.
CREATE OR REPLACE FUNCTION public.bando_slug_non_storico()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE esito_storico text;
BEGIN
  IF NEW.slug IS NULL THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE' AND NEW.slug IS NOT DISTINCT FROM OLD.slug THEN
    RETURN NEW;
  END IF;

  SELECT s.esito INTO esito_storico
    FROM public.bando_slug_storico s
   WHERE s.slug = NEW.slug AND s.esito IN ('301', '410');

  IF esito_storico IS NOT NULL THEN
    RAISE EXCEPTION
      'lo slug «%» è nello storico con esito %: non può tornare corrente finché la riga ha quell''esito',
      NEW.slug, esito_storico
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_slug_non_storico() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_bando_slug_non_storico ON public.bando;
CREATE TRIGGER trg_bando_slug_non_storico
  BEFORE INSERT OR UPDATE OF slug ON public.bando
  FOR EACH ROW EXECUTE FUNCTION public.bando_slug_non_storico();

-- 4.d Provenienza delle date. Se la data (o la sua ora) cambia senza che
--     cambi l'evento che la prova, la prova non vale più: il flag torna
--     false e il riferimento si azzera. È il motivo per cui `verificata` non
--     può essere scritta a mano da nessuno step.
CREATE OR REPLACE FUNCTION public.bando_provenienza_date()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NEW.data_pubblicazione IS DISTINCT FROM OLD.data_pubblicazione
     AND NEW.data_pubblicazione_evento_id IS NOT DISTINCT FROM OLD.data_pubblicazione_evento_id THEN
    NEW.data_pubblicazione_verificata := false;
    NEW.data_pubblicazione_evento_id  := NULL;
  END IF;

  IF (NEW.data_apertura IS DISTINCT FROM OLD.data_apertura
      OR NEW.ora_apertura IS DISTINCT FROM OLD.ora_apertura)
     AND NEW.data_apertura_evento_id IS NOT DISTINCT FROM OLD.data_apertura_evento_id THEN
    NEW.data_apertura_verificata := false;
    NEW.data_apertura_evento_id  := NULL;
  END IF;

  IF (NEW.data_scadenza IS DISTINCT FROM OLD.data_scadenza
      OR NEW.ora_scadenza IS DISTINCT FROM OLD.ora_scadenza)
     AND NEW.data_scadenza_evento_id IS NOT DISTINCT FROM OLD.data_scadenza_evento_id THEN
    NEW.data_scadenza_verificata := false;
    NEW.data_scadenza_evento_id  := NULL;
  END IF;

  IF NEW.stato_bando IS DISTINCT FROM OLD.stato_bando
     AND NEW.stato_bando_evento_id IS NOT DISTINCT FROM OLD.stato_bando_evento_id THEN
    NEW.stato_bando_verificato := false;
    NEW.stato_bando_evento_id  := NULL;
  END IF;

  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_provenienza_date() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_bando_provenienza_date ON public.bando;
CREATE TRIGGER trg_bando_provenienza_date
  BEFORE UPDATE ON public.bando
  FOR EACH ROW EXECUTE FUNCTION public.bando_provenienza_date();

-- 4.e `fonte_ufficiale_url`/`_host` sono una copia derivata dal link: la
--     verità è `fonte_ufficiale_link_id`. Le due colonne testuali restano
--     perché la vista e l'API le espongono, ma nessuno le scrive a mano.
--     Nome scelto perché in ordine alfabetico questo trigger precede
--     `..._dominio`, che controlla il risultato.
CREATE OR REPLACE FUNCTION public.bando_fonte_ufficiale_copia()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE url_link text;
BEGIN
  IF NEW.fonte_ufficiale_link_id IS NULL THEN
    NEW.fonte_ufficiale_url  := NULL;
    NEW.fonte_ufficiale_host := NULL;
    RETURN NEW;
  END IF;

  SELECT l.url INTO url_link
    FROM public.bando_link l
   WHERE l.id = NEW.fonte_ufficiale_link_id;

  IF url_link IS NULL THEN
    RAISE EXCEPTION 'bando %: fonte_ufficiale_link_id % non esiste', NEW.id, NEW.fonte_ufficiale_link_id
      USING ERRCODE = '23503';
  END IF;

  NEW.fonte_ufficiale_url  := url_link;
  NEW.fonte_ufficiale_host := public.dominio_di(url_link);
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_fonte_ufficiale_copia() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_bando_fonte_ufficiale_copia ON public.bando;
-- Le tre colonne nell'`UPDATE OF`, non solo `fonte_ufficiale_link_id`: un
-- trigger `UPDATE OF fonte_ufficiale_link_id` scatta SOLO quando quella
-- colonna compare nella SET list, quindi un UPDATE che scrivesse a mano
-- `fonte_ufficiale_url` (o `_host`) senza toccare il link passerebbe
-- indisturbato e lascerebbe una riga con `fonte_ufficiale_stato='in_verifica'`,
-- `fonte_ufficiale_link_id` NULL e un `fonte_ufficiale_url` esposto dalla
-- vista — contro §13.2. `bando_fonte_coerente` non lo vedrebbe (vincola
-- stato ↔ link_id, non l'url) e `..._dominio` interviene solo se l'host è in
-- blocklist. Il corpo è già idempotente: o ricopia da `bando_link`, o azzera.
-- CONSEGUENZA da conoscere: scrivere a mano `fonte_ufficiale_url` o
-- `fonte_ufficiale_host` su una riga con `fonte_ufficiale_link_id` NULL NON
-- solleva — degrada in silenzio a NULL, perché questo trigger precede
-- `..._dominio` e azzera entrambe le colonne prima che l'altro le guardi.
-- L'esito è sicuro (niente aggregatore esposto), ma la guardia di 4.f si
-- esercita solo passando dal link: vedi la verifica #5 in fondo al file.
CREATE TRIGGER trg_bando_fonte_ufficiale_copia
  BEFORE INSERT OR UPDATE OF fonte_ufficiale_link_id, fonte_ufficiale_url, fonte_ufficiale_host
  ON public.bando
  FOR EACH ROW EXECUTE FUNCTION public.bando_fonte_ufficiale_copia();

-- 4.f Un aggregatore non è mai una fonte ufficiale. Qui si SOLLEVA (a
--     differenza di `bando_evento`, dove la prova si azzera in silenzio):
--     una fonte ufficiale sbagliata diventa un pulsante pubblico, e il
--     chiamante deve accorgersene.
CREATE OR REPLACE FUNCTION public.bando_fonte_ufficiale_dominio()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE host_effettivo text;
BEGIN
  -- Si controllano entrambi: l'host dichiarato e quello che si ricava
  -- dall'URL, perché un UPDATE può toccare l'uno senza l'altro.
  host_effettivo := coalesce(NEW.fonte_ufficiale_host,
                             public.dominio_di(NEW.fonte_ufficiale_url));

  IF host_effettivo IS NOT NULL AND public.bando_host_aggregatore(host_effettivo) THEN
    RAISE EXCEPTION
      'bando %: «%» è un aggregatore e non può essere la fonte ufficiale',
      NEW.id, host_effettivo
      USING ERRCODE = '23514';
  END IF;

  -- `dominio_di` è FAIL-OPEN: su un URL che il suo regex non riconosce torna
  -- NULL, e `bando_host_aggregatore(NULL)` vale false. Un URL con l'host in
  -- escape percentuale (`obiettivoeuropa%2ecom`, che il browser
  -- percent-decodifica prima di IDNA) o protocol-relative passerebbe quindi
  -- indisturbato. Qui si chiude: host non riconoscibile ⇒ non è una fonte
  -- ufficiale. È anche l'unico ramo di questo blocco davvero raggiungibile —
  -- `..._copia` gira prima (ordine alfabetico) e tiene `_host` allineato a
  -- `dominio_di(_url)`, per cui l'aggregatore lo intercetta già il primo IF.
  IF NEW.fonte_ufficiale_url IS NOT NULL THEN
    IF public.dominio_di(NEW.fonte_ufficiale_url) IS NULL THEN
      RAISE EXCEPTION
        'bando %: l''URL della fonte ufficiale non ha un host riconoscibile (%). La blocklist non può pronunciarsi su un URL che non sa leggere.',
        NEW.id, NEW.fonte_ufficiale_url
        USING ERRCODE = '23514';
    END IF;

    IF public.bando_host_aggregatore(public.dominio_di(NEW.fonte_ufficiale_url)) THEN
      RAISE EXCEPTION
        'bando %: l''URL della fonte ufficiale punta a un aggregatore (%)',
        NEW.id, public.dominio_di(NEW.fonte_ufficiale_url)
        USING ERRCODE = '23514';
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_fonte_ufficiale_dominio() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_bando_fonte_ufficiale_dominio ON public.bando;
CREATE TRIGGER trg_bando_fonte_ufficiale_dominio
  BEFORE INSERT OR UPDATE ON public.bando
  FOR EACH ROW
  -- La WHEN evita di interrogare la blocklist sulle 5000 righe che lo
  -- scrape riscrive a ogni giro senza toccare la fonte ufficiale.
  WHEN (NEW.fonte_ufficiale_host IS NOT NULL OR NEW.fonte_ufficiale_url IS NOT NULL)
  EXECUTE FUNCTION public.bando_fonte_ufficiale_dominio();

COMMIT;

-- ============================================================================
-- Riconciliazione (rieseguibile da sola)
-- ============================================================================
-- Riga di controllo per i pubblicati che non ce l'hanno (per esempio se il
-- trigger 4.a è stato disattivato per un lotto). Non tocca `bando`, quindi
-- non serve disattivare nessun trigger.
--
--   INSERT INTO bando_controllo (bando_id, prossimo_controllo_at)
--   SELECT b.id, now() + ((b.id % 336) * interval '1 hour')
--     FROM bando b WHERE b.pubblicato
--   ON CONFLICT (bando_id) DO NOTHING;
--
-- Priorità delle righe create dal trigger 4.a (DEFAULT 30) e non ancora
-- controllate: è il 3.d, e va rieseguito ogni volta che si riesegue l'INSERT
-- qui sopra, altrimenti un bando in scadenza resta dietro a uno chiuso.
--
--   UPDATE bando_controllo c SET priorita_controllo = x.priorita
--     FROM (SELECT b.id AS bando_id,
--                  CASE
--                    WHEN b.stato_bando = 'in apertura prossimamente'
--                         AND b.data_apertura IS NOT NULL
--                         AND b.data_apertura <= (now() AT TIME ZONE 'Europe/Rome')::date THEN 90
--                    WHEN b.data_scadenza BETWEEN (now() AT TIME ZONE 'Europe/Rome')::date
--                                             AND ((now() AT TIME ZONE 'Europe/Rome')::date + 3) THEN 90
--                    WHEN b.link_bando IS NOT NULL AND dominio_di(b.link_bando) IS NOT NULL
--                         AND NOT bando_host_aggregatore(dominio_di(b.link_bando)) THEN 70
--                    WHEN b.data_scadenza < ((now() AT TIME ZONE 'Europe/Rome')::date - 180) THEN 10
--                    ELSE 30
--                  END AS priorita
--             FROM bando b WHERE b.pubblicato) x
--    WHERE c.bando_id = x.bando_id AND c.ultimo_controllo_at IS NULL
--      AND c.priorita_controllo IS DISTINCT FROM x.priorita;
--
-- Stato della fonte per le righe nuove entrate dopo l'applicazione (va fra
-- DISABLE e ENABLE dei tre trigger, come il punto 3):
--
--   UPDATE bando SET fonte_ufficiale_stato = 'in_verifica' WHERE fonte_ufficiale_stato IS NULL;
--
-- Flag «verificata» rimasti senza evento che li provi (stessa forma del 3.a:
-- il predicato guarda l'EVENTO, così la riesecuzione non cancella mai la
-- provenienza già accumulata dal resolver). Va fra DISABLE e ENABLE dei tre
-- trigger, come il punto 3:
--
--   UPDATE bando
--      SET data_pubblicazione_verificata = (data_pubblicazione_verificata AND data_pubblicazione_evento_id IS NOT NULL),
--          data_apertura_verificata      = (data_apertura_verificata      AND data_apertura_evento_id      IS NOT NULL),
--          data_scadenza_verificata      = (data_scadenza_verificata      AND data_scadenza_evento_id      IS NOT NULL),
--          stato_bando_verificato        = (stato_bando_verificato        AND stato_bando_evento_id        IS NOT NULL)
--    WHERE (data_pubblicazione_verificata AND data_pubblicazione_evento_id IS NULL)
--       OR (data_apertura_verificata      AND data_apertura_evento_id      IS NULL)
--       OR (data_scadenza_verificata      AND data_scadenza_evento_id      IS NULL)
--       OR (stato_bando_verificato        AND stato_bando_evento_id        IS NULL);
-- ============================================================================

-- ============================================================================
-- Verifica post-deploy
-- ============================================================================
-- 1) FK create.
--      SELECT conname FROM pg_constraint
--       WHERE conrelid='public.bando'::regclass AND contype='f' ORDER BY 1;
--      -- attese, fra le altre: bando_fonte_ufficiale_link_fk,
--      --   bando_data_{pubblicazione,apertura,scadenza}_evento_fk,
--      --   bando_stato_bando_evento_fk, bando_master_fk
--
-- 2) Backfill.
--      SELECT count(*) FILTER (WHERE fonte_ufficiale_stato='in_verifica') AS in_verifica,
--             count(*) FILTER (WHERE data_scadenza_verificata)            AS scadenze_verificate
--        FROM bando;
--      -- atteso: 5048 e 0
--      SELECT count(*) FROM bando_controllo;
--      -- atteso: 2104 (= count(*) from bando where pubblicato)
--      SELECT min(prossimo_controllo_at), max(prossimo_controllo_at) FROM bando_controllo;
--      -- attesa: una finestra di ~14 giorni
--      SELECT priorita_controllo, count(*) FROM bando_controllo GROUP BY 1 ORDER BY 1 DESC;
--
-- 3) Nessun `updated_at` né `ultimo_cambiamento_at` mosso (sostituire :inizio):
--      SELECT count(*) FROM bando WHERE updated_at >= :inizio OR ultimo_cambiamento_at >= :inizio;
--      -- atteso: 0
--
-- 4) Slug congelato (da annullare):
--      BEGIN;
--        UPDATE bando SET slug = slug || '-x'
--         WHERE id = (SELECT id FROM bando WHERE pubblicato ORDER BY id LIMIT 1);
--        -- atteso: 23514 «lo slug del bando … è congelato»
--      ROLLBACK;
--
-- 5) Host aggregatore rifiutato (da annullare). La prova va fatta PASSANDO
--    DAL LINK: `trg_bando_fonte_ufficiale_copia` precede `..._dominio`
--    nell'ordine alfabetico e, con `fonte_ufficiale_link_id` NULL, azzera sia
--    `_url` sia `_host` prima che l'altro trigger li guardi — un UPDATE
--    diretto su `fonte_ufficiale_host` NON solleva, degrada in silenzio a
--    NULL (esito sicuro, ma non è questa la guardia che si vuole esercitare).
--    Il blocco è AUTO-CONTENUTO: eseguirlo per intero, il ROLLBACK annulla
--    sia il link sia l'UPDATE.
--      BEGIN;
--        WITH b AS (SELECT id FROM bando WHERE pubblicato ORDER BY id LIMIT 1)
--        INSERT INTO bando_link (bando_id, url, tipo, origine)
--        SELECT id, 'https://www.obiettivoeuropa.com/bando/prova-guardia', 'pagina_bando', 'aggregatore'
--          FROM b;
--        UPDATE bando SET fonte_ufficiale_link_id = (
--                 SELECT id FROM bando_link
--                  WHERE url = 'https://www.obiettivoeuropa.com/bando/prova-guardia'),
--               fonte_ufficiale_stato = 'trovata'
--         WHERE id = (SELECT id FROM bando WHERE pubblicato ORDER BY id LIMIT 1);
--        -- atteso: 23514 «è un aggregatore»
--      ROLLBACK;
--
--    Controprova della degradazione silenziosa (nessun errore, host a NULL):
--      BEGIN;
--        UPDATE bando SET fonte_ufficiale_host = 'www.obiettivoeuropa.com'
--         WHERE id = (SELECT id FROM bando WHERE pubblicato ORDER BY id LIMIT 1)
--        RETURNING fonte_ufficiale_host, fonte_ufficiale_url;
--        -- atteso: NULL, NULL — nessuna eccezione
--      ROLLBACK;
--
-- 6) Provenienza (da annullare):
--      BEGIN;
--        UPDATE bando SET data_scadenza = data_scadenza + 1
--         WHERE id = (SELECT id FROM bando WHERE pubblicato AND data_scadenza IS NOT NULL ORDER BY id LIMIT 1)
--        RETURNING data_scadenza_verificata, data_scadenza_evento_id;
--        -- atteso: false, NULL
--      ROLLBACK;
--
-- 7) `trovata` senza link rifiutato (da annullare):
--      BEGIN;
--        UPDATE bando SET fonte_ufficiale_stato='trovata'
--         WHERE id = (SELECT id FROM bando WHERE pubblicato ORDER BY id LIMIT 1);
--        -- atteso: violazione di bando_fonte_coerente
--      ROLLBACK;
-- ============================================================================
