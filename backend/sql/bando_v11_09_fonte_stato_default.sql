-- ============================================================================
-- bando_v11_09_fonte_stato_default.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Chiude un buco silenzioso nella selezione del resolver: `bando` nasce
--   con `fonte_ufficiale_stato` a NULL e il resolver cerca le righe «senza
--   fonte» con `neq('fonte_ufficiale_stato', 'trovata')`. In SQL `<>` su NULL
--   non è vero, quindi una riga con la colonna vuota NON viene mai
--   selezionata: un bando pubblicato dopo il backfill della 03 non riceverà
--   mai una fonte ufficiale, e nessun contatore lo dice.
--
--   La migrazione 03 (sezione 3.b) fa già questo stesso UPDATE, ma una volta
--   sola: senza un DEFAULT, ogni riga creata DOPO quel momento ricomincia da
--   NULL. È il motivo per cui il buco si è riaperto nel giro di due ore.
--
--   Misurato in produzione il 23/09/2026, poche ore dopo le migrazioni:
--   9 righe pubblicate con `fonte_ufficiale_stato` NULL, tutte create dopo il
--   backfill della 03; il resolver ne «vedeva» 2 125 su 2 134 pubblicate. Al
--   ritmo di ingresso misurato (circa 11 bandi nuovi al giorno) il buco
--   cresce di 11 righe al giorno e non si richiude da solo.
--
--   Il codice ha la sua difesa (la selezione accetta anche il NULL), ma la
--   colonna resta fuori contratto: `docs/contratto-db-bandi.md` promette ai
--   consumatori tre valori, `trovata | in_verifica | non_trovata`, e la vista
--   `bando_pubblico` espone quella colonna così com'è. Una riga a NULL è una
--   promessa non mantenuta, non solo un problema di selezione.
--
-- Che cosa fa
--   1. mette il DEFAULT 'in_verifica' sulla colonna (è un cambio di soli
--      metadati: nessuna riscrittura di tabella, nessun blocco lungo);
--   2. riempie le righe rimaste a NULL con lo stesso valore;
--   3. NON mette NOT NULL: la colonna resta nullable per non trasformare un
--      errore di scrittura futuro in un fallimento dell'INSERT dello scrape,
--      che pubblicherebbe meno bandi invece di pubblicarli senza fonte.
--
-- Fase: (b). Nessuna colonna nuova, nessun dato editoriale toccato.
--
-- Precondizioni
--   * `bando_v11_01_pubblicazione.sql` applicata (crea la colonna);
--   * nessun'altra: 02, seed, 03, 04, 05 non c'entrano e non danno fastidio.
--
-- Rompe BandoFit? NO. La colonna non è fra quelle che legge oggi, e il valore
--   che compare è uno dei tre già dichiarati nel contratto. Semmai toglie un
--   NULL che il contratto non prevedeva.
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'INTERO file, poi il blocco
--   «Verifica». Rieseguibile: il DEFAULT si riscrive uguale e l'UPDATE tocca
--   solo le righe ancora a NULL (zero righe alla seconda esecuzione).
--   NON serve riavviare il sender: nessuna colonna e nessuna tabella nuova.
--
-- COSA NON È REVERSIBILE
--   Le righe riempite non tornano a NULL: il rollback toglie il DEFAULT ma
--   lascia i valori, perché distinguerli da quelli scritti dal resolver
--   richiederebbe un'informazione che non abbiamo. È voluto: 'in_verifica' è
--   esattamente ciò che quelle righe sono.
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';

-- ---------------------------------------------------------------------------
-- 0. Precondizione
-- ---------------------------------------------------------------------------

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_schema = 'public' AND table_name = 'bando'
       AND column_name = 'fonte_ufficiale_stato'
  ) THEN
    RAISE EXCEPTION
      'manca bando.fonte_ufficiale_stato: applicare prima bando_v11_01_pubblicazione.sql';
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 1. DEFAULT sulla colonna (solo metadati: nessuna riscrittura)
-- ---------------------------------------------------------------------------

ALTER TABLE public.bando
  ALTER COLUMN fonte_ufficiale_stato SET DEFAULT 'in_verifica';

COMMENT ON COLUMN public.bando.fonte_ufficiale_stato IS
  'trovata | in_verifica | non_trovata. Nasce a in_verifica: una riga senza valore sparirebbe dalla selezione del resolver, perché <> su NULL non è vero.';

-- ---------------------------------------------------------------------------
-- 2. Riconciliazione (rieseguibile: la seconda volta tocca zero righe)
-- ---------------------------------------------------------------------------
-- Tre trigger, non due: oltre ai due `updated_at` identici c'è
-- `trg_bando_cambiamento_pubblico` (migrazione 01), che considera
-- `fonte_ufficiale_stato` una colonna PUBBLICA e sposterebbe
-- `ultimo_cambiamento_at`, cioè il `lastmod` della sitemap, su righe che per
-- chi legge non sono cambiate. È la stessa lista, e lo stesso motivo, della
-- sezione 3.b della migrazione 03 — che fa esattamente questo UPDATE.
-- I nomi si cercano invece di darli per scontati: se un trigger non ci fosse,
-- un `ALTER TABLE … DISABLE TRIGGER` con nome fisso farebbe fallire il file.

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['trg_bando_set_updated_at', 'update_bando_updated_at', 'trg_bando_cambiamento_pubblico'] LOOP
    IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'public.bando'::regclass AND tgname = t) THEN
      EXECUTE format('ALTER TABLE public.bando DISABLE TRIGGER %I', t);
    END IF;
  END LOOP;
END $$;

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

COMMIT;

-- ============================================================================
-- Verifica post-deploy (eseguire dopo il COMMIT)
-- ============================================================================
-- 1) Nessuna riga senza stato della fonte.
--      SELECT count(*) FROM public.bando WHERE fonte_ufficiale_stato IS NULL;
--      -- atteso: 0
--
-- 2) Il DEFAULT c'è.
--      SELECT column_default FROM information_schema.columns
--       WHERE table_schema='public' AND table_name='bando'
--         AND column_name='fonte_ufficiale_stato';
--      -- atteso: 'in_verifica'::text
--
-- 3) Il resolver le vede tutte: i due conteggi devono coincidere.
--      SELECT count(*) FILTER (WHERE pubblicato)                                  AS pubblicati,
--             count(*) FILTER (WHERE pubblicato AND fonte_ufficiale_stato <> 'trovata'
--                                 AND fonte_ufficiale_stato IS NOT NULL)          AS viste_dal_resolver
--        FROM public.bando;
--      -- atteso: i due valori coincidono finché nessuna fonte è 'trovata';
--      -- dopo, la differenza è esattamente il numero di fonti trovate.
--
-- 4) Nessun `updated_at` mosso dal riempimento. Sostituire :inizio con
--    l'istante in cui è partita l'esecuzione.
--      SELECT count(*) FROM public.bando WHERE updated_at >= :inizio;
--      -- atteso: 0 (a pipeline ferma; con la pipeline attiva, solo le righe
--      -- che lo scrape ha davvero toccato nel frattempo)
-- ============================================================================
