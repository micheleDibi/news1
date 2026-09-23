-- ============================================================================
-- bando_v11_01_pubblicazione.sql — DB Supabase «bandi» (secondario)
-- ============================================================================
-- Scopo
--   Prima migrazione della serie v11. Aggiunge a `bando` TUTTE le colonne
--   nuove del contratto (§13 del piano) in un solo ALTER TABLE e separa le
--   quattro nozioni che oggi coincidono nel predicato di pubblicazione:
--   la coda di elaborazione (`stato_processing`), la pubblicazione
--   (`pubblicato`), lo stato del bando (`stato_bando`) e la freschezza
--   (`ultimo_cambiamento_at`). Chiude inoltre due buchi di scrittura
--   gratuiti: i cataloghi `categoria_programma`/`tipologia_programma` e le
--   tre RPC stale eseguibili con la anon key.
--
--   Perché TUTTE le colonne qui e non sparse nelle migrazioni successive:
--   plpgsql risolve i nomi di campo a runtime, quindi un trigger che citasse
--   una colonna creata da una migrazione successiva farebbe fallire OGNI
--   UPDATE della pipeline (upsert dello scrape compreso) nella finestra fra
--   le due applicazioni. È la regola di dipendenza B3 del piano.
--
-- Fase: (b) — solo aggiunte.
--
-- Precondizioni
--   * `bando.id` di tipo integer (guardia esplicita più sotto: se il tipo
--     fosse diverso andrebbero corretti `bando_master_id` qui e le FK della
--     migrazione 03);
--   * nessun pubblicato con `stato_bando` NULL (guardia esplicita: alla
--     misura del 22/09 erano 0 su 2104);
--   * finestra FUORI dai giri dello scheduler (00:00/06:00/12:00/18:00):
--     l'`ADD COLUMN … GENERATED … STORED` riscrive la tabella e i suoi 24
--     indici sotto ACCESS EXCLUSIVE (21 espliciti più i 3 impliciti di
--     `bando_pkey`, `bando_hash_unique`, `bando_slug_unique`).
--
-- Rompe BandoFit? NO.
--   Nessuna colonna cambia tipo o sparisce, il conteggio dei pubblicati
--   resta identico, i due cataloghi restano leggibili da anon e le 3 RPC
--   revocate non sono chiamate da BandoFit (che usa `.rpc` solo sul proprio
--   DB). Effetto collaterale dichiarato: blocco esclusivo di alcuni secondi
--   sulla tabella, quindi 57014/504 transitori sulle richieste in corso (è il
--   loro `statement_timeout` a scadere mentre aspettano in coda; 55P03 è
--   l'errore di QUESTO file se il lock non arriva entro 5 s).
--
-- Come si applica
--   Supabase Dashboard → SQL Editor → incollare ed eseguire l'INTERO file
--   (contiene BEGIN/COMMIT: o passa tutto o non passa niente). Se fallisce
--   per `lock_timeout` (55P03 `lock_not_available`, non 57014, che è lo
--   `statement_timeout`) non resta nulla a metà: rilanciare fuori dai
--   giri. Al termine eseguire il blocco «Verifica» in fondo.
--   Il file è rieseguibile: la seconda esecuzione non riscrive la tabella e
--   non tocca nessun valore già assestato.
-- ============================================================================

BEGIN;

-- `lock_timeout` breve: meglio fallire subito che tenere in coda tutte le
-- richieste di lettura dietro la ACCESS EXCLUSIVE (M2 del piano).
SET LOCAL lock_timeout = '5s';
-- La riscrittura di 5048 righe con 24 indici non deve cadere sul timeout di
-- default del SQL Editor.
SET LOCAL statement_timeout = '15min';

-- ---------------------------------------------------------------------------
-- 0. Guardie di precondizione (falliscono con un messaggio leggibile invece
--    che con un errore di CHECK a metà file)
-- ---------------------------------------------------------------------------

DO $$
DECLARE tipo_id text;
BEGIN
  SELECT format_type(a.atttypid, a.atttypmod) INTO tipo_id
    FROM pg_attribute a
   WHERE a.attrelid = 'public.bando'::regclass
     AND a.attname = 'id' AND a.attnum > 0 AND NOT a.attisdropped;

  IF tipo_id IS DISTINCT FROM 'integer' THEN
    RAISE EXCEPTION
      'bando.id è di tipo %, non integer: correggere il tipo di bando_master_id qui e delle FK della 03 prima di applicare',
      tipo_id;
  END IF;
END $$;

DO $$
DECLARE senza_stato bigint;
BEGIN
  SELECT count(*) INTO senza_stato
    FROM public.bando
   WHERE stato_processing::text = 'completed' AND slug IS NOT NULL AND stato_bando IS NULL;

  IF senza_stato > 0 THEN
    RAISE EXCEPTION
      '% righe completed+slug hanno stato_bando NULL: il CHECK bando_pubblicato_implica_completed le rifiuterebbe. Assegnare lo stato (o escluderle dal backfill) prima di applicare.',
      senza_stato;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 1. Colonne nuove — un solo ALTER TABLE, una sola riscrittura di tabella
-- ---------------------------------------------------------------------------
-- `ultimo_cambiamento_at` nasce nullable: il NOT NULL e il default arrivano
-- dopo il backfill, così una riesecuzione del file non ha modo di riportare
-- al vecchio `updated_at` un valore che nel frattempo la pipeline ha fatto
-- avanzare (il backfill filtra su IS NULL).

ALTER TABLE public.bando
  ADD COLUMN IF NOT EXISTS pubblicato                     boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS pubblicato_at                  timestamptz,
  ADD COLUMN IF NOT EXISTS ritirato_at                    timestamptz,
  ADD COLUMN IF NOT EXISTS ultimo_cambiamento_at          timestamptz,
  ADD COLUMN IF NOT EXISTS ora_apertura                   time,
  ADD COLUMN IF NOT EXISTS ora_scadenza                   time,
  ADD COLUMN IF NOT EXISTS data_pubblicazione_verificata  boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS data_apertura_verificata       boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS data_scadenza_verificata       boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS data_pubblicazione_evento_id   bigint,
  ADD COLUMN IF NOT EXISTS data_apertura_evento_id        bigint,
  ADD COLUMN IF NOT EXISTS data_scadenza_evento_id        bigint,
  ADD COLUMN IF NOT EXISTS stato_bando_evento_id          bigint,
  ADD COLUMN IF NOT EXISTS stato_bando_verificato         boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS bando_master_id                integer,
  ADD COLUMN IF NOT EXISTS chiave_esterna                 text,
  ADD COLUMN IF NOT EXISTS rielaborazione                 text,
  ADD COLUMN IF NOT EXISTS tentativi_seo                  smallint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS fonte_ufficiale_url            text,
  ADD COLUMN IF NOT EXISTS fonte_ufficiale_host           text,
  ADD COLUMN IF NOT EXISTS fonte_ufficiale_tipo           text,
  ADD COLUMN IF NOT EXISTS fonte_ufficiale_stato          text,
  ADD COLUMN IF NOT EXISTS fonte_ufficiale_confidenza     smallint,
  ADD COLUMN IF NOT EXISTS fonte_ufficiale_metodo         text,
  ADD COLUMN IF NOT EXISTS fonte_ufficiale_verificata_at  timestamptz,
  ADD COLUMN IF NOT EXISTS fonte_ufficiale_link_id        bigint,
  -- `to_tsvector(regconfig, text)` è IMMUTABLE: la colonna generata è legale
  -- e indipendente da `default_text_search_config`. Serve a sostituire l'`or`
  -- a 5 rami che oggi fa un Seq Scan con 5 `to_tsvector` per riga.
  ADD COLUMN IF NOT EXISTS ricerca tsvector GENERATED ALWAYS AS (
    to_tsvector(
      'italian'::regconfig,
      coalesce(titolo, '')            || ' ' ||
      coalesce(titolo_breve, '')      || ' ' ||
      coalesce(descrizione_breve, '') || ' ' ||
      coalesce(titolo_raw, '')
    )
  ) STORED;

COMMENT ON COLUMN public.bando.pubblicato IS
  'Pubblicazione: true solo per completed con slug. Torna false solo per fusione (bando_fondi) o ritiro scritto del committente, mai per rielaborazione.';
COMMENT ON COLUMN public.bando.ultimo_cambiamento_at IS
  'Avanza solo per modifiche pubbliche (testi, date, stato, fonte, allegati); mai per re-scrape o controlli. Valore iniziale = vecchio updated_at.';
COMMENT ON COLUMN public.bando.pubblicato_at IS
  'Istante di pubblicazione. Per le righe preesistenti è approssimato a created_at (dichiarato nel contratto).';
COMMENT ON COLUMN public.bando.ricerca IS
  'tsvector generato per la FTS: filtro PostgREST consigliato ricerca=wfts(italian).<termini>.';
COMMENT ON COLUMN public.bando.fonte_ufficiale_metodo IS
  'Passo della cascata del resolver che ha prodotto la fonte (link strutturato, gemello, sonda, ricerca): diagnostica, non fa parte del contratto pubblico.';

-- ---------------------------------------------------------------------------
-- 2. Vincoli
-- ---------------------------------------------------------------------------
-- `stato_processing` per primo: il loop dinamico sotto riconosce i CHECK dal
-- testo. Il criterio è `completed_duplicate`, non `stato_processing`: la
-- stringa compare nell'enumerazione dei valori — sia in quella a 6 valori del
-- DB (schema.sql:191) sia in quella a 7 qui sotto — e in nessun altro CHECK
-- di `bando`. Discriminare sul nome della COLONNA cancellerebbe invece il
-- primo vincolo nuovo che la cita: `bando_pubblicato_implica_completed`
-- (creato poco più avanti) la contiene già, e si salvava solo per
-- un'esclusione per nome. Stesso criterio robusto della migrazione 06.

DO $$
DECLARE c_name text;
BEGIN
  FOR c_name IN
    SELECT conname
      FROM pg_constraint
     WHERE conrelid = 'public.bando'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) ILIKE '%completed_duplicate%'
  LOOP
    EXECUTE format('ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS %I', c_name);
  END LOOP;
END $$;

-- `archiviato` = ramo terminale per i chiusi mai pubblicati (fuori dal lotto
-- L8). `completed_duplicate` resta ammesso ma non viene più scritto da
-- nessuno (DEDUP_CANONICAL=false).
ALTER TABLE public.bando
  ADD CONSTRAINT bando_stato_processing_check
  CHECK (stato_processing::text IN (
    'scraped', 'processed', 'rejected', 'enriched',
    'completed', 'completed_duplicate', 'archiviato'
  ));

-- Invariante UNIDIREZIONALE. Il bidirezionale («completed+slug ⇒ pubblicato»)
-- farebbe fallire ogni `bando_fondi`, che lascia il doppione completed+slug
-- con pubblicato=false.
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_pubblicato_implica_completed;
ALTER TABLE public.bando
  ADD CONSTRAINT bando_pubblicato_implica_completed
  CHECK (
    NOT pubblicato
    OR (stato_processing::text = 'completed' AND slug IS NOT NULL AND stato_bando IS NOT NULL)
  );

ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_master_diverso;
ALTER TABLE public.bando
  ADD CONSTRAINT bando_master_diverso
  CHECK (bando_master_id IS NULL OR bando_master_id <> id);

-- Opzione B: un doppione fuso esce dalla vista restando leggibile in `bando`.
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_master_non_pubblicato;
ALTER TABLE public.bando
  ADD CONSTRAINT bando_master_non_pubblicato
  CHECK (bando_master_id IS NULL OR NOT pubblicato);

-- Gemello del precedente per la terza e ultima via d'uscita dalla vista.
-- Le condizioni di uscita sono tre (fusione, ritiro, spubblicazione) e la
-- vista filtra solo `WHERE pubblicato`: senza questo CHECK un `bando_ritira`
-- che scrivesse `ritirato_at` dimenticando `pubblicato = false` lascerebbe il
-- bando ritirato nella vista e nella sitemap, e nulla a DB lo impedirebbe.
-- Nessun attrito con `bando_pubblica_al_completamento`, che già esclude
-- `ritirato_at IS NOT NULL` dal ripescaggio.
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_ritirato_non_pubblicato;
ALTER TABLE public.bando
  ADD CONSTRAINT bando_ritirato_non_pubblicato
  CHECK (ritirato_at IS NULL OR NOT pubblicato);

ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_fonte_ufficiale_stato_check;
ALTER TABLE public.bando
  ADD CONSTRAINT bando_fonte_ufficiale_stato_check
  CHECK (fonte_ufficiale_stato IS NULL
         OR fonte_ufficiale_stato IN ('trovata', 'in_verifica', 'non_trovata'));

-- Due soli valori: «atto» è un sotto-tipo di `ente` e viaggia nel flag
-- `fonte_ufficiale_e_atto` della vista; «calendario» non vale mai `trovata`.
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_fonte_ufficiale_tipo_check;
ALTER TABLE public.bando
  ADD CONSTRAINT bando_fonte_ufficiale_tipo_check
  CHECK (fonte_ufficiale_tipo IS NULL
         OR fonte_ufficiale_tipo IN ('ente', 'portale_pubblico'));

-- ---------------------------------------------------------------------------
-- 3. Indici
-- ---------------------------------------------------------------------------
-- Il GIN su `ricerca` NON è utilizzabile da anon (sotto RLS l'operatore `@@`
-- non è LEAKPROOF): esiste per le letture con service_role. La garanzia
-- pubblica sulla FTS è il tempo, non il piano di esecuzione.
CREATE INDEX IF NOT EXISTS idx_bando_ricerca_gin
  ON public.bando USING gin (ricerca);

-- news1 ordina `data_pubblicazione DESC NULLS LAST, id DESC` (il tiebreak su
-- id è obbligatorio: data_pubblicazione è NULL sul 92% delle righe).
CREATE INDEX IF NOT EXISTS idx_bando_pub_data_pubblicazione
  ON public.bando (data_pubblicazione DESC NULLS LAST, id DESC)
  WHERE pubblicato;

CREATE INDEX IF NOT EXISTS idx_bando_pub_data_scadenza
  ON public.bando (data_scadenza)
  WHERE pubblicato;

CREATE INDEX IF NOT EXISTS idx_bando_pub_data_apertura
  ON public.bando (data_apertura)
  WHERE pubblicato;

CREATE INDEX IF NOT EXISTS idx_bando_pub_ultimo_cambiamento
  ON public.bando (ultimo_cambiamento_at DESC)
  WHERE pubblicato;

-- NON `WHERE pubblicato`: il CHECK bando_master_non_pubblicato rende vuoto
-- per costruzione l'insieme «pubblicato con master». L'indice serve alla
-- rimappatura dei doppioni, che lavora proprio sui non pubblicati.
CREATE INDEX IF NOT EXISTS idx_bando_master_id
  ON public.bando (bando_master_id)
  WHERE bando_master_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 4. Backfill — fra la disattivazione e la riattivazione dei due trigger
--    `updated_at` (M1)
-- ---------------------------------------------------------------------------
-- I due trigger sono identici e bumperebbero `updated_at` su tutte le righe
-- toccate, distruggendo `lastmod` della sitemap e `updated_since` dell'API.
-- `session_replication_role` non è usabile: su Supabase `postgres` non è
-- superuser.

-- Impronta di controllo: serve a dimostrare, dopo il backfill, che nessun
-- `updated_at` si è mosso.
CREATE TEMP TABLE _v11_01_impronta ON COMMIT DROP AS
SELECT md5(string_agg(id::text || ':' || coalesce(updated_at::text, ''), ',' ORDER BY id)) AS impronta
  FROM public.bando;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_trigger
              WHERE tgrelid = 'public.bando'::regclass AND tgname = 'trg_bando_set_updated_at') THEN
    ALTER TABLE public.bando DISABLE TRIGGER trg_bando_set_updated_at;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_trigger
              WHERE tgrelid = 'public.bando'::regclass AND tgname = 'update_bando_updated_at') THEN
    ALTER TABLE public.bando DISABLE TRIGGER update_bando_updated_at;
  END IF;
END $$;

-- 4.a `pubblicato` dal predicato attuale della RLS, escluse le righe fuse o
--     ritirate (alla prima applicazione non ce ne sono: il filtro serve alle
--     riesecuzioni).
UPDATE public.bando
   SET pubblicato    = true,
       pubblicato_at = coalesce(pubblicato_at, created_at)
 WHERE NOT pubblicato
   AND stato_processing::text = 'completed'
   AND slug IS NOT NULL
   AND stato_bando IS NOT NULL
   AND bando_master_id IS NULL
   AND ritirato_at IS NULL;

-- 4.b `pubblicato_at` approssimato a `created_at`: è una dichiarazione del
--     contratto, non una misura. `created_at` non viene mai toccato.
UPDATE public.bando
   SET pubblicato_at = created_at
 WHERE pubblicato AND pubblicato_at IS NULL;

-- 4.c `ultimo_cambiamento_at` parte dal vecchio `updated_at`: da qui in poi
--     avanza solo per modifiche pubbliche.
UPDATE public.bando
   SET ultimo_cambiamento_at = coalesce(updated_at, created_at, now())
 WHERE ultimo_cambiamento_at IS NULL;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_trigger
              WHERE tgrelid = 'public.bando'::regclass AND tgname = 'trg_bando_set_updated_at') THEN
    ALTER TABLE public.bando ENABLE TRIGGER trg_bando_set_updated_at;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_trigger
              WHERE tgrelid = 'public.bando'::regclass AND tgname = 'update_bando_updated_at') THEN
    ALTER TABLE public.bando ENABLE TRIGGER update_bando_updated_at;
  END IF;
END $$;

DO $$
DECLARE prima text; dopo text;
BEGIN
  SELECT impronta INTO prima FROM _v11_01_impronta;
  SELECT md5(string_agg(id::text || ':' || coalesce(updated_at::text, ''), ',' ORDER BY id))
    INTO dopo FROM public.bando;

  IF dopo IS DISTINCT FROM prima THEN
    RAISE EXCEPTION
      'il backfill ha mosso updated_at: i trigger non erano disattivati. Transazione annullata.';
  END IF;
END $$;

-- Il DEFAULT è solo catalogo: non tocca nessuna riga esistente.
ALTER TABLE public.bando
  ALTER COLUMN ultimo_cambiamento_at SET DEFAULT now();

-- Ora che nessuna riga è NULL il vincolo si può stringere. Non è una
-- riscrittura: solo una scansione di validazione, sotto il lock già preso.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_attribute
              WHERE attrelid = 'public.bando'::regclass
                AND attname = 'ultimo_cambiamento_at'
                AND NOT attnotnull) THEN
    ALTER TABLE public.bando ALTER COLUMN ultimo_cambiamento_at SET NOT NULL;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 5. Trigger — SOLO dopo il backfill, altrimenti riscriverebbero le righe
--    che il backfill sta assestando
-- ---------------------------------------------------------------------------

-- 5.a Pubblicazione automatica al completamento.
--     Non spubblica MAI: la sola direzione è false → true. Toglie la
--     pubblicazione solo `bando_fondi` (master) o il ritiro (ritirato_at),
--     entrambi esclusi dal predicato.
CREATE OR REPLACE FUNCTION public.bando_pubblica_al_completamento()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NOT NEW.pubblicato
     AND NEW.stato_processing::text = 'completed'
     AND NEW.slug IS NOT NULL
     AND NEW.stato_bando IS NOT NULL
     AND NEW.bando_master_id IS NULL
     AND NEW.ritirato_at IS NULL
  THEN
    NEW.pubblicato    := true;
    NEW.pubblicato_at := coalesce(NEW.pubblicato_at, now());
    -- Questo trigger gira DOPO bando_cambiamento_pubblico (ordine
    -- alfabetico dei nomi), quindi il salto di stato pubblico lo registra qui.
    NEW.ultimo_cambiamento_at := now();
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_pubblica_al_completamento() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_bando_pubblica_al_completamento ON public.bando;
CREATE TRIGGER trg_bando_pubblica_al_completamento
  BEFORE INSERT OR UPDATE ON public.bando
  FOR EACH ROW EXECUTE FUNCTION public.bando_pubblica_al_completamento();

-- 5.b Un pubblicato non esce da `completed` e non perde lo slug, in nessuna
--     fase e per nessuna rielaborazione (garanzia del contratto verso
--     BandoFit, che tiene `bando_id` e slug in 6 tabelle senza FK).
CREATE OR REPLACE FUNCTION public.bando_pubblicato_resta_completed()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  IF OLD.pubblicato AND NEW.stato_processing::text IS DISTINCT FROM 'completed' THEN
    RAISE EXCEPTION
      'bando % è pubblicato: stato_processing non può passare da completed a %',
      OLD.id, NEW.stato_processing
      USING ERRCODE = '23514';
  END IF;

  IF OLD.pubblicato AND NEW.slug IS NULL THEN
    RAISE EXCEPTION 'bando % è pubblicato: lo slug non può essere azzerato', OLD.id
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_pubblicato_resta_completed() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_bando_pubblicato_resta_completed ON public.bando;
CREATE TRIGGER trg_bando_pubblicato_resta_completed
  BEFORE UPDATE ON public.bando
  FOR EACH ROW EXECUTE FUNCTION public.bando_pubblicato_resta_completed();

-- 5.c `ultimo_cambiamento_at` avanza solo se cambia qualcosa che il pubblico
--     vede. Il re-scrape riscrive le stesse colonne con gli stessi valori:
--     `IS DISTINCT FROM` rende gratuite le riscritture identiche.
--     `fonte_ufficiale_link_id` è nell'elenco perché il trigger che copia
--     url/host dal link (migrazione 03) gira DOPO questo, in ordine
--     alfabetico: senza il link_id un cambio di fonte passerebbe inosservato.
CREATE OR REPLACE FUNCTION public.bando_cambiamento_pubblico()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NEW.titolo                        IS DISTINCT FROM OLD.titolo
  OR NEW.titolo_breve                  IS DISTINCT FROM OLD.titolo_breve
  OR NEW.descrizione_breve             IS DISTINCT FROM OLD.descrizione_breve
  OR NEW.contenuto                     IS DISTINCT FROM OLD.contenuto
  OR NEW.livello                       IS DISTINCT FROM OLD.livello
  OR NEW.ente_erogatore                IS DISTINCT FROM OLD.ente_erogatore
  OR NEW.area_geografica               IS DISTINCT FROM OLD.area_geografica
  OR NEW.tematica                      IS DISTINCT FROM OLD.tematica
  OR NEW.data_pubblicazione            IS DISTINCT FROM OLD.data_pubblicazione
  OR NEW.data_apertura                 IS DISTINCT FROM OLD.data_apertura
  OR NEW.data_scadenza                 IS DISTINCT FROM OLD.data_scadenza
  OR NEW.ora_apertura                  IS DISTINCT FROM OLD.ora_apertura
  OR NEW.ora_scadenza                  IS DISTINCT FROM OLD.ora_scadenza
  OR NEW.data_pubblicazione_verificata IS DISTINCT FROM OLD.data_pubblicazione_verificata
  OR NEW.data_apertura_verificata      IS DISTINCT FROM OLD.data_apertura_verificata
  OR NEW.data_scadenza_verificata      IS DISTINCT FROM OLD.data_scadenza_verificata
  OR NEW.importo_totale_eur            IS DISTINCT FROM OLD.importo_totale_eur
  OR NEW.importo_max_per_progetto_eur  IS DISTINCT FROM OLD.importo_max_per_progetto_eur
  OR NEW.stato_bando                   IS DISTINCT FROM OLD.stato_bando
  OR NEW.stato_bando_verificato        IS DISTINCT FROM OLD.stato_bando_verificato
  OR NEW.tipologia_bando_id            IS DISTINCT FROM OLD.tipologia_bando_id
  OR NEW.modalita_erogazione_id        IS DISTINCT FROM OLD.modalita_erogazione_id
  OR NEW.programma_id                  IS DISTINCT FROM OLD.programma_id
  OR NEW.fonte_ufficiale_stato         IS DISTINCT FROM OLD.fonte_ufficiale_stato
  OR NEW.fonte_ufficiale_tipo          IS DISTINCT FROM OLD.fonte_ufficiale_tipo
  OR NEW.fonte_ufficiale_url           IS DISTINCT FROM OLD.fonte_ufficiale_url
  OR NEW.fonte_ufficiale_host          IS DISTINCT FROM OLD.fonte_ufficiale_host
  OR NEW.fonte_ufficiale_link_id       IS DISTINCT FROM OLD.fonte_ufficiale_link_id
  OR NEW.link_candidatura              IS DISTINCT FROM OLD.link_candidatura
  OR NEW.link_candidatura_source       IS DISTINCT FROM OLD.link_candidatura_source
  OR NEW.link_bando                    IS DISTINCT FROM OLD.link_bando
  OR NEW.allegati                      IS DISTINCT FROM OLD.allegati
  OR NEW.slug                          IS DISTINCT FROM OLD.slug
  OR NEW.pubblicato                    IS DISTINCT FROM OLD.pubblicato
  OR NEW.ritirato_at                   IS DISTINCT FROM OLD.ritirato_at
  OR NEW.bando_master_id               IS DISTINCT FROM OLD.bando_master_id
  THEN
    NEW.ultimo_cambiamento_at := now();
  END IF;

  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.bando_cambiamento_pubblico() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_bando_cambiamento_pubblico ON public.bando;
CREATE TRIGGER trg_bando_cambiamento_pubblico
  BEFORE UPDATE ON public.bando
  FOR EACH ROW EXECUTE FUNCTION public.bando_cambiamento_pubblico();

-- ---------------------------------------------------------------------------
-- 6. Buchi di scrittura chiusi subito (nessun riferimento né in BandoFit né
--    in `src/`: costo zero, beneficio immediato)
-- ---------------------------------------------------------------------------

-- 6.a Cataloghi dei programmi: oggi anon e authenticated hanno ALL e non c'è
--     RLS, cioè chiunque abbia la anon key può riscriverli.
--     REVOKE ALL e poi il solo SELECT: elencare i privilegi da togliere
--     lascerebbe fuori quelli che PostgreSQL aggiunge nelle versioni nuove
--     (per esempio MAINTAIN).
--     La policy è concessa anche ad `authenticated`: le due tabelle non sono
--     citate né in BandoFit né in `src/`, ma abilitare la RLS senza policy
--     spegnerebbe in silenzio un lettore che oggi legge. Qui va chiuso il
--     buco di SCRITTURA, non la lettura.
ALTER TABLE public.categoria_programma ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS categoria_programma_public_read ON public.categoria_programma;
CREATE POLICY categoria_programma_public_read ON public.categoria_programma
  FOR SELECT TO anon, authenticated USING (true);
REVOKE ALL ON TABLE public.categoria_programma FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.categoria_programma TO anon, authenticated;

ALTER TABLE public.tipologia_programma ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tipologia_programma_public_read ON public.tipologia_programma;
CREATE POLICY tipologia_programma_public_read ON public.tipologia_programma
  FOR SELECT TO anon, authenticated USING (true);
REVOKE ALL ON TABLE public.tipologia_programma FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.tipologia_programma TO anon, authenticated;
-- Le sequence delle due tabelle le copre il loop del punto 6.c insieme a
-- tutte le altre: elencarle a una a una lasciava fuori le altre tredici.

-- 6.b RPC stale: `get_scraping_stats` e `refresh_materialized_views`
--     referenziano oggetti che non esistono più; `generate_bando_hash` è
--     l'hash di deduplicazione. Nessuna delle tre va esposta alla anon key.
--     (Il DROP resta una valutazione del committente: qui si revoca e basta.)
--
--     Le altre tre sono FUNZIONI TRIGGER, e il progetto le ha concesse ad
--     anon con `GRANT ALL` (schema.sql:1518, 1524, 1607). Non fanno danno da
--     sole, ma sporcano l'allowlist: senza queste revoche la verifica #6
--     della migrazione 05 torna 6 righe invece di 3 e l'operatore si ferma su
--     un falso allarme. Revocarle NON rompe i trigger esistenti: il
--     privilegio EXECUTE di una funzione trigger si controlla al
--     `CREATE TRIGGER`, non a ogni scatto.
DO $$
DECLARE f text;
BEGIN
  FOREACH f IN ARRAY ARRAY[
    'public.get_scraping_stats(integer)',
    'public.refresh_materialized_views()',
    'public.generate_bando_hash(text, text)',
    'public.set_current_timestamp_aggiornato_il()',
    'public.set_current_timestamp_updated_at()',
    'public.update_updated_at_column()'
  ] LOOP
    IF to_regprocedure(f) IS NOT NULL THEN
      EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC, anon, authenticated', f);
    ELSE
      RAISE NOTICE 'funzione % assente: nessuna revoca necessaria', f;
    END IF;
  END LOOP;
END $$;

-- 6.c Sequence: il progetto ne concede 15 ad anon con `GRANT ALL`,
--     `bando_id_seq` compresa. `ALL` include UPDATE, cioè `setval()`, e il
--     contratto §1.3 promette che la sequence degli id non viene mai
--     riavviata. Lo sfruttamento pratico è remoto (PostgREST non espone
--     `setval`), ma è un privilegio che il contratto dichiara impossibile.
--     Loop e non elenco: revocarle a una a una lasciava fuori le altre
--     tredici, e ne nascono di nuove a ogni tabella.
--     Precondizione verificata: nessuno scrittore del DB bandi usa la anon
--     key — `scraper_bandi/app/settings.py` legge SUPABASE_SERVICE_KEY_BANDI,
--     cioè la service-role key, che questo loop non tocca.
DO $$
DECLARE s text;
BEGIN
  FOR s IN
    SELECT format('%I.%I', n.nspname, c.relname)
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.relkind = 'S' AND n.nspname = 'public'
     ORDER BY 1
  LOOP
    EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM PUBLIC, anon, authenticated', s);
  END LOOP;
END $$;

COMMIT;

-- ============================================================================
-- Riconciliazione (rieseguibile da sola, anche a distanza di settimane)
-- ============================================================================
-- Allinea `pubblicato` alle righe che nel frattempo sono diventate
-- completed+slug senza passare da un UPDATE (per esempio importate a mano).
--
-- Due colonne, due regole diverse, da non confondere:
--   * `updated_at` è un dato interno e NON deve muoversi: per questo i due
--     trigger omonimi vanno disattivati intorno all'UPDATE;
--   * `ultimo_cambiamento_at` è il `lastmod` della sitemap e l'`updated_since`
--     dell'API (§13.2), e qui si muove DI PROPOSITO. `trg_bando_cambiamento_pubblico`
--     resta attivo e lo porta a `now()` sulle righe che vengono pubblicate,
--     perché la pubblicazione È una modifica pubblica: un bando che compare
--     oggi deve avere il lastmod di oggi.
--   Se invece si vuole una riconciliazione muta (per esempio per correggere
--   un errore che non cambia nulla per i lettori), va disattivato anche
--   `trg_bando_cambiamento_pubblico`, come fa la Riconciliazione della 03.
--
-- BEGIN;
--   ALTER TABLE public.bando DISABLE TRIGGER trg_bando_set_updated_at;
--   ALTER TABLE public.bando DISABLE TRIGGER update_bando_updated_at;
--
--   UPDATE public.bando
--      SET pubblicato    = true,
--          pubblicato_at = coalesce(pubblicato_at, created_at)
--    WHERE NOT pubblicato
--      AND stato_processing::text = 'completed'
--      AND slug IS NOT NULL
--      AND stato_bando IS NOT NULL
--      AND bando_master_id IS NULL
--      AND ritirato_at IS NULL;
--
--   ALTER TABLE public.bando ENABLE TRIGGER trg_bando_set_updated_at;
--   ALTER TABLE public.bando ENABLE TRIGGER update_bando_updated_at;
-- COMMIT;
--
-- (Il vecchio secondo UPDATE su `ultimo_cambiamento_at IS NULL` è stato
-- tolto: dopo questa migrazione la colonna è NOT NULL, quindi non poteva
-- toccare nessuna riga.)
-- ============================================================================

-- ============================================================================
-- Verifica post-deploy (eseguire nel SQL Editor dopo il COMMIT)
-- ============================================================================
-- 1) Nessun `updated_at` mosso dalla migrazione. Sostituire :inizio con
--    l'istante in cui è partita l'esecuzione.
--      SELECT count(*) FROM bando WHERE updated_at >= :inizio;
--      -- atteso: 0
--
-- 2) Pubblicati = predicato storico.
--      SELECT count(*) FILTER (WHERE pubblicato)                                        AS pubblicati,
--             count(*) FILTER (WHERE stato_processing = 'completed' AND slug IS NOT NULL) AS completed_slug
--        FROM bando;
--      -- atteso: 2104 e 2104 (i due valori divergono solo dopo la prima fusione)
--
-- 3) Colonne e colonna generata.
--      SELECT count(*) FROM information_schema.columns
--       WHERE table_schema='public' AND table_name='bando'
--         AND column_name IN ('pubblicato','pubblicato_at','ritirato_at','ultimo_cambiamento_at',
--                             'ora_apertura','ora_scadenza','ricerca','bando_master_id','chiave_esterna');
--      -- atteso: 9
--      SELECT count(*) FROM bando WHERE ricerca IS NULL;
--      -- atteso: 0
--
-- 4) CHECK di `stato_processing` unico e con 7 valori.
--      SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
--       WHERE conrelid='public.bando'::regclass AND contype='c'
--         AND pg_get_constraintdef(oid) ILIKE '%stato_processing%';
--      -- atteso: 2 righe (bando_stato_processing_check e
--      --          bando_pubblicato_implica_completed)
--
-- 5) `ultimo_cambiamento_at` = vecchio `updated_at`.
--      SELECT count(*) FROM bando WHERE ultimo_cambiamento_at <> coalesce(updated_at, created_at);
--      -- atteso: 0 subito dopo la migrazione
--
-- 6) Cataloghi: per anon e authenticated deve restare solo SELECT.
--      SELECT grantee, privilege_type FROM information_schema.role_table_grants
--       WHERE table_schema='public' AND table_name IN ('categoria_programma','tipologia_programma')
--         AND grantee IN ('anon','authenticated') ORDER BY 1,2;
--      -- atteso: solo SELECT (4 righe)
--
-- 7) RPC stale non eseguibili da anon.
--      SELECT p.oid::regprocedure AS funzione,
--             has_function_privilege('anon', p.oid, 'EXECUTE') AS anon_execute
--        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
--       WHERE n.nspname='public'
--         AND p.proname IN ('get_scraping_stats','refresh_materialized_views','generate_bando_hash',
--                           'set_current_timestamp_aggiornato_il','set_current_timestamp_updated_at',
--                           'update_updated_at_column');
--      -- atteso: anon_execute = false su tutte
--      (le ultime tre sono funzioni trigger: revocarle non le ferma, il
--       privilegio si controlla al CREATE TRIGGER. Senza, la verifica #6
--       della 05 torna 6 righe invece di 3.)
--
-- 7-bis) Nessuna sequence resta scrivibile con la anon key (`ALL` includeva
--    UPDATE, cioè `setval()`).
--      SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
--       WHERE c.relkind='S' AND n.nspname='public'
--         AND (has_sequence_privilege('anon', c.oid, 'USAGE')
--              OR has_sequence_privilege('anon', c.oid, 'SELECT')
--              OR has_sequence_privilege('anon', c.oid, 'UPDATE'));
--      -- atteso: 0 (erano 15, bando_id_seq compresa)
--      La stessa query con 'service_role' deve restare > 0: la pipeline scrive.
--
-- 8) Prova del trigger anti-declassamento (da annullare):
--      BEGIN;
--        UPDATE bando SET stato_processing='enriched'
--         WHERE id = (SELECT id FROM bando WHERE pubblicato ORDER BY id LIMIT 1);  -- atteso: 23514
--      ROLLBACK;
-- ============================================================================
