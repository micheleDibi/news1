-- ============================================================================
-- bando_v11_06_stati_cinque.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Estende il CHECK di `bando.stato_bando` da 3 a 5 valori, aggiungendo
--   `sospeso` e `revocato`. È una sola istruzione, ma è l'unica migrazione
--   della serie che può rompere un consumatore: per questo sta in un file da
--   sola, con una precondizione che non è tecnica ma organizzativa.
--
-- Fase: (b), ma SOLO DOPO la fase (a).
--
-- PRECONDIZIONE BLOCCANTE — R0-a di BandoFit in produzione, confermato per
--   iscritto dal committente. R0-a è la parte di R0 che non dipende dal DB:
--     * badge neutro per ogni `stato_bando` diverso da
--       aperto / chiuso / in apertura prossimamente;
--     * esclusione di `sospeso` e `revocato` da ENTRAMBI i segmenti
--       («aperti» e «chiusi») e dai candidati degli alert;
--     * filtro `stato` che non risponde 400 per valori sconosciuti;
--     * snapshot dei preferiti tolleranti (un miss non rompe la pagina).
--   Senza R0-a, il primo bando che diventa `sospeso` produce in BandoFit un
--   badge ambra «In apertura», un alert sbagliato e un 400 sul filtro.
--
-- Altre precondizioni
--   * migrazione 01 applicata (il CHECK `bando_pubblicato_implica_completed`
--     cita `stato_bando` e va preservato: il loop dinamico qui sotto lo
--     riconosce e lo esclude);
--   * migrazione 04 applicata, altrimenti nessuno può scrivere i due valori
--     nuovi (li scrive solo `bando_registra_evento`). Non è bloccante: il
--     CHECK più largo è innocuo anche da solo.
--
-- Rompe BandoFit? SÌ prima di R0-a. NO dopo.
--   news1 è già tollerante: `statoDaEventi()` mostra sospeso/revocato
--   leggendo gli eventi `applicato=false` fin dalla fase (b).
--
-- Cosa cambia per il resto del sistema
--   Dopo questo file gli eventi `sospensione` e `revoca` possono essere
--   applicati alla colonna (`MONITOR_STATI_ESTESI=true`,
--   `applica-eventi --tipo sospensione,revoca`). Prima restano
--   `applicato=false` con la colonna intatta.
--   La funzione `bando_stato_effettivo` (migrazione 02) gestisce già i due
--   valori: non va ritoccata.
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'intero file. Rieseguibile.
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';

-- ---------------------------------------------------------------------------
-- 0. Guardia: nessuna riga fuori dai 5 valori (dovrebbe essere impossibile,
--    ma un ADD CONSTRAINT che fallisce a metà file è più difficile da
--    leggere di un messaggio esplicito)
-- ---------------------------------------------------------------------------

DO $$
DECLARE fuori bigint; valori text;
BEGIN
  SELECT count(*) INTO fuori
    FROM public.bando
   WHERE stato_bando IS NOT NULL
     AND stato_bando NOT IN ('aperto', 'chiuso', 'in apertura prossimamente',
                             'sospeso', 'revocato');
  IF fuori > 0 THEN
    SELECT string_agg(DISTINCT stato_bando, ', ') INTO valori
      FROM public.bando
     WHERE stato_bando IS NOT NULL
       AND stato_bando NOT IN ('aperto', 'chiuso', 'in apertura prossimamente',
                               'sospeso', 'revocato');
    RAISE EXCEPTION '% righe hanno stato_bando fuori dai 5 valori (%)', fuori, valori;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 1. CHECK a 5 valori
-- ---------------------------------------------------------------------------
-- Il loop riconosce il vecchio CHECK dal testo dell'enumerazione («in
-- apertura prossimamente»), non dalla sola parola `stato_bando`: quest'ultima
-- comparirebbe anche in `bando_pubblicato_implica_completed` e in
-- `bando_provenienza_stato`, che NON vanno toccati.

DO $$
DECLARE c_name text;
BEGIN
  FOR c_name IN
    SELECT conname
      FROM pg_constraint
     WHERE conrelid = 'public.bando'::regclass
       AND contype = 'c'
       AND conname NOT IN ('bando_pubblicato_implica_completed', 'bando_provenienza_stato')
       AND pg_get_constraintdef(oid) ILIKE '%in apertura prossimamente%'
  LOOP
    EXECUTE format('ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS %I', c_name);
  END LOOP;
END $$;

ALTER TABLE public.bando
  ADD CONSTRAINT bando_stato_bando_check
  CHECK (stato_bando IS NULL OR stato_bando IN (
    'aperto',
    'chiuso',
    'in apertura prossimamente',
    'sospeso',    -- può riaprire: non è mai chiuso d'ufficio dalla scadenza
    'revocato'    -- terminale: si esce solo con un evento annullamento_revoca
  ));

COMMENT ON COLUMN public.bando.stato_bando IS
  'Stato persistito a 5 valori, allineato dal cron entro 65 minuti. La verità sullo stato è bando_pubblico.stato_effettivo, non questa colonna.';

COMMIT;

-- ============================================================================
-- Riconciliazione (rieseguibile da sola)
-- ============================================================================
-- Applica alla colonna gli eventi verificati di sospensione/revoca rimasti
-- in attesa fra la fase (b) e R0. NON si fa con un UPDATE diretto: il
-- trigger `trg_bando_stato_solo_via_evento` (migrazione 04) lo rifiuterebbe,
-- e giustamente. Si fa dalla CLI, a blocchi, con il dry-run per primo:
--
--   python -m app applica-eventi --tipo sospensione,revoca --dry-run --limit 50
--   python -m app applica-eventi --tipo sospensione,revoca --limit 50
--
-- Eventi ancora in attesa:
--   SELECT tipo, count(*) FROM bando_evento
--    WHERE tipo IN ('sospensione','revoca') AND verificato AND NOT applicato
--    GROUP BY 1;
-- ============================================================================

-- ============================================================================
-- Verifica post-deploy
-- ============================================================================
-- 1) Il CHECK è uno solo e ha 5 valori.
--      SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
--       WHERE conrelid='public.bando'::regclass AND contype='c'
--         AND pg_get_constraintdef(oid) ILIKE '%in apertura prossimamente%';
--      -- atteso: 1 riga, bando_stato_bando_check, con sospeso e revocato
--
-- 2) I CHECK della 01 e della 03 sono ancora al loro posto.
--      SELECT conname FROM pg_constraint
--       WHERE conrelid='public.bando'::regclass AND contype='c'
--         AND conname IN ('bando_pubblicato_implica_completed','bando_provenienza_stato');
--      -- atteso: 2 righe
--
-- 3) Nessuna riga fuori dai 5 valori.
--      SELECT stato_bando, count(*) FROM bando GROUP BY 1 ORDER BY 2 DESC;
--      -- atteso: solo i 5 valori (più NULL sui non pubblicati)
--
-- 4) Il valore nuovo è accettato. NON usare `ALTER TABLE bando DISABLE
--    TRIGGER USER`: prende una ACCESS EXCLUSIVE su `bando` e la tiene per
--    tutta la transazione, quindi finché si legge il risultato prima di
--    digitare ROLLBACK ogni lettura di news1 e di BandoFit resta in coda e va
--    in 57014 contro lo `statement_timeout` di 3 s di anon; e spegnerebbe in
--    un colpo solo anche slug congelato, provenienza e cambiamento pubblico,
--    cioè proprio ciò che la prova dovrebbe lasciare in piedi.
--    Il CHECK si legge senza toccare né i trigger né la tabella:
--      SELECT 'sospeso'  = ANY (ARRAY['aperto','chiuso','in apertura prossimamente','sospeso','revocato']),
--             'revocato' = ANY (ARRAY['aperto','chiuso','in apertura prossimamente','sospeso','revocato']);
--      -- atteso: true, true — e il testo esatto del CHECK è al punto 1
--    Per provarlo davvero su una riga, una riga finta NON pubblicata, in
--    transazione da annullare. `fonte_id` e `hash_bando` sono NOT NULL nel
--    DB reale e vanno valorizzati; `stato_processing='scraped'` tiene la riga
--    fuori dalla pubblicazione automatica, e su un INSERT il trigger
--    `trg_bando_stato_solo_via_evento` della 04 (BEFORE UPDATE) non entra in
--    gioco:
--      BEGIN;
--        INSERT INTO bando (fonte_id, hash_bando, titolo, stato_processing, stato_bando)
--        SELECT f.id, 'prova-v11-06-' || md5(random()::text), 'prova v11-06',
--               'scraped', 'sospeso'
--          FROM fonte f ORDER BY f.id LIMIT 1
--        RETURNING id, stato_bando, pubblicato;
--        -- atteso: 1 riga con stato_bando 'sospeso' e pubblicato false,
--        --   nessun 23514
--      ROLLBACK;
--
-- 5) La vista lo rende senza inventare nulla.
--      SELECT stato_bando, stato_effettivo, count(*) FROM bando_pubblico
--       WHERE stato_bando IN ('sospeso','revocato') GROUP BY 1,2;
--      -- atteso: stato_effettivo = stato_bando (precedenze 1 e 2 di §13.3),
--      --   anche con la scadenza passata
-- ============================================================================
