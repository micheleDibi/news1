-- ============================================================================
-- bando_v11_05_vista_pubblica.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Crea `bando_pubblico`, la vista che è il contratto di lettura per i due
--   consumatori (news1 e BandoFit), e concede ad anon l'esecuzione delle tre
--   sole funzioni dell'allowlist. Le tre funzioni NON nascono qui: sono tutte
--   della migrazione 02 (`bando_stato_effettivo` compresa, perché la
--   migrazione 04 la chiama e la 04 precede questo file).
--
--   Tre scelte da non toccare:
--   1) `WITH (security_invoker = true)`: la vista gira con i privilegi di
--      chi legge, quindi il guardiano resta la RLS di `bando` (in fase (b)
--      il predicato storico, in (d) `pubblicato`). Una vista con i
--      privilegi del proprietario scavalcherebbe la RLS.
--   2) Proprio per questo ogni funzione usata nel corpo della vista viene
--      eseguita COME anon e richiede EXECUTE, anche se il planner la inlina:
--      `bando_stato_effettivo`, `dominio_di` e `bando_host_aggregatore` sono
--      l'allowlist, e nessun'altra funzione di `public` va concessa ad anon.
--      Sono pure, non scrivono, non espongono righe non pubblicate e la
--      blocklist che leggono è già pubblicata nel contratto.
--   3) `ultimo_controllo_at` è una SOTTOQUERY SCALARE, non un LEFT JOIN: con
--      una policy `EXISTS` il join non è eliminabile e costerebbe anche nei
--      `count=exact`, che BandoFit chiede su ogni elenco.
--
-- Fase: (b) — oggetto nuovo.
--
-- Precondizioni
--   * migrazioni 01, 02 e 03 applicate (la vista legge `pubblicato`,
--     `ora_*`, `fonte_ufficiale_*`, `bando_link`, `bando_controllo`, e le tre
--     funzioni dell'allowlist sono create dalla 02);
--   * PostgreSQL ≥ 15 per `security_invoker` (guardia esplicita).
--   La migrazione 04 NON è una precondizione: la vista non usa nessuna RPC.
--
-- Rompe BandoFit? NO: è un oggetto nuovo. BandoFit continua a leggere
--   `bando` finché non decide di passare alla vista (fase (c)); quando lo
--   farà, le sue 8 richieste valgono con il solo cambio del nome della
--   tabella, perché fino alla fase (d) la vista espone anche
--   `stato_processing` (costante 'completed') e `link_bando`.
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'INTERO file, poi il blocco
--   «Verifica» (che include il controllo come ruolo anon). Rieseguibile:
--   la vista viene ricreata da zero.
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';

-- ---------------------------------------------------------------------------
-- 0. Guardie
-- ---------------------------------------------------------------------------

DO $$
BEGIN
  IF current_setting('server_version_num')::int < 150000 THEN
    RAISE EXCEPTION
      'security_invoker sulle viste richiede PostgreSQL 15 (qui: %). Senza, la vista scavalcherebbe la RLS di bando.',
      current_setting('server_version');
  END IF;
  IF to_regclass('public.bando_controllo') IS NULL OR to_regclass('public.bando_link') IS NULL THEN
    RAISE EXCEPTION 'mancano bando_link/bando_controllo: applicare prima la migrazione 02';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_attribute
                  WHERE attrelid = 'public.bando'::regclass
                    AND attname = 'ora_scadenza' AND NOT attisdropped) THEN
    RAISE EXCEPTION 'manca bando.ora_scadenza: applicare prima la migrazione 01';
  END IF;
  IF to_regprocedure('public.dominio_di(text)') IS NULL
     OR to_regprocedure('public.bando_host_aggregatore(text)') IS NULL THEN
    RAISE EXCEPTION 'mancano dominio_di/bando_host_aggregatore: applicare prima la migrazione 02';
  END IF;
  IF to_regprocedure(
       'public.bando_stato_effettivo(text,date,boolean,time,date,time,timestamptz)') IS NULL THEN
    RAISE EXCEPTION
      'manca bando_stato_effettivo: applicare prima la migrazione 02 (la funzione nasce lì perché la 04 la chiama)';
  END IF;
END $$;

DO $$
BEGIN
  -- La fase (d) si riconosce dalla policy: cita `pubblicato` e non più
  -- `stato_processing`. Rimettere qui la vista della fase (b) referenzierebbe
  -- sette colonne su cui anon non ha più SELECT → 42501 su ogni lettura.
  -- Serve perché rieseguire questo file è il rimedio prescritto
  -- dall'avvertenza (a) della 02, e prima di questa guardia niente lo legava
  -- alla fase in corso.
  IF EXISTS (SELECT 1 FROM pg_policies
              WHERE schemaname = 'public' AND tablename = 'bando'
                AND policyname = 'bando_public_read'
                AND qual ILIKE '%pubblicato%'
                AND qual NOT ILIKE '%stato_processing%') THEN
    RAISE EXCEPTION
      'la fase (d) è già applicata: rieseguire la 05 rimetterebbe nella vista link_bando, link_candidatura, link_candidatura_source, allegati, titolo_raw, descrizione_raw e stato_processing, su cui anon non ha più SELECT (42501 su ogni lettura di bando_pubblico). Rieseguire bando_v11_07_fase_d.sql, non questo file.';
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 1. Allowlist: le tre sole funzioni eseguibili con la anon key
-- ---------------------------------------------------------------------------

-- Le TRE funzioni dell'allowlist esistono tutte dalla migrazione 02: qui si
-- aggiunge soltanto il permesso di esecuzione per anon.
-- Nessuna viene ridefinita di proposito:
--   * `bando_stato_effettivo` è citata dalla migrazione 04 (dal blocco «CASI»
--     generato da tests/stato-bando/genera-sql.ts e da
--     `bando_transizioni_automatiche()`), e la 04 si applica PRIMA di questo
--     file: crearla qui violerebbe la regola B3 e lascerebbe il cron della 04
--     in 42883 nella finestra fra le due migrazioni;
--   * `dominio_di` alimenta due colonne generate STORED, e riscriverla qui
--     significherebbe rischiare di disallinearne il corpo dai valori già
--     memorizzati (un CREATE OR REPLACE non li ricalcola);
--   * `bando_host_aggregatore` è usata dai trigger della 02 e della 03.
-- `authenticated` NON compare fra i beneficiari: questo file non gli dà
-- SELECT sulla vista (vedi in fondo) e la 07 gli revoca tutto su `bando`
-- (sua verifica #5, atteso 0). Dargli l'EXECUTE sarebbe un privilegio senza
-- un uso, e in fase (d) resterebbe l'unico appiglio rimasto.
REVOKE ALL ON FUNCTION public.bando_stato_effettivo(text, date, boolean, time, date, time, timestamptz)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_stato_effettivo(text, date, boolean, time, date, time, timestamptz)
  TO anon, service_role;

REVOKE ALL ON FUNCTION public.dominio_di(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.dominio_di(text) TO anon, service_role;

REVOKE ALL ON FUNCTION public.bando_host_aggregatore(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bando_host_aggregatore(text) TO anon, service_role;

-- ---------------------------------------------------------------------------
-- 2. Il grant di colonna su `bando_controllo`
-- ---------------------------------------------------------------------------
-- Unico appiglio di anon su una tabella interna, e solo per la colonna che
-- la vista espone. La policy (migrazione 02) limita già le righe ai bandi
-- pubblicati.
GRANT SELECT (bando_id, ultimo_controllo_at) ON TABLE public.bando_controllo TO anon;

-- ---------------------------------------------------------------------------
-- 3. La vista
-- ---------------------------------------------------------------------------
-- DROP + CREATE invece di CREATE OR REPLACE: la REPLACE non può cambiare
-- l'insieme o l'ordine delle colonne, e questo file deve restare
-- rieseguibile anche dopo una correzione. Dentro la transazione il cambio è
-- atomico e nessun lettore vede la vista assente.

DROP VIEW IF EXISTS public.bando_pubblico;

CREATE VIEW public.bando_pubblico
WITH (security_invoker = true) AS
SELECT
  b.id,
  b.slug,
  b.titolo,
  b.titolo_breve,
  b.descrizione_breve,
  -- 9 righe hanno `contenuto` salvato come stringa JSON (doppia codifica):
  -- esporle come stringa farebbe cercare invano `sections` a entrambi i
  -- consumatori. NULL è un'assenza leggibile, una stringa no.
  CASE WHEN jsonb_typeof(b.contenuto) = 'object' THEN b.contenuto END AS contenuto,
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
  -- «atto» non è un valore della colonna `tipo` ma una proprietà del link:
  -- il PDF dell'atto sul dominio dell'ente.
  -- ATTENZIONE: la vista è `security_invoker`, quindi questa sottoquery passa
  -- per la policy `bando_link_public_read`, che pretende `pubblicabile`. Il
  -- flag vale dunque «l'atto esiste ED È PUBBLICABILE»: su un atto non ancora
  -- verificato anon legge false mentre service_role legge true. È voluto —
  -- il flag accende un pulsante pubblico, e un pulsante verso un link non
  -- pubblicabile non va acceso — ma va dichiarato, perché non è una proprietà
  -- della sola fonte. Vedi il COMMENT della vista.
  EXISTS (
    SELECT 1 FROM public.bando_link l
     WHERE l.id = b.fonte_ufficiale_link_id AND l.tipo = 'atto'
  ) AS fonte_ufficiale_e_atto,
  b.fonte_ufficiale_url,
  b.fonte_ufficiale_host,
  b.fonte_ufficiale_verificata_at,
  -- sottoquery scalare, non LEFT JOIN: vedi l'intestazione
  (SELECT c.ultimo_controllo_at
     FROM public.bando_controllo c
    WHERE c.bando_id = b.id) AS ultimo_controllo_at,
  -- --- deprecate: presenti fino alla fase (d), poi tolte dalla 07 ---------
  -- Stesso trattamento di `link_bando`: la CTA non può portare
  -- all'aggregatore. Il contratto (docs/contratto-db-bandi.md §1.3 e §7) lo
  -- promette per TUTTE le colonne di link leggibili con la anon key, non per
  -- la sola `link_bando`. La sostituzione con il link istituzionale la fa il
  -- resolver, che arriva dopo la fase (c): fino ad allora meglio NULL che un
  -- link verso chi ci ha fornito il dato.
  CASE
    WHEN b.link_candidatura IS NULL THEN NULL
    WHEN public.dominio_di(b.link_candidatura) IS NULL THEN NULL
    WHEN public.bando_host_aggregatore(public.dominio_di(b.link_candidatura)) THEN NULL
    ELSE b.link_candidatura
  END AS link_candidatura,
  -- la provenienza segue il link: senza link non dice nulla di utile e
  -- lascerebbe intendere che il link c'è
  CASE
    WHEN b.link_candidatura IS NULL
      OR public.dominio_di(b.link_candidatura) IS NULL
      OR public.bando_host_aggregatore(public.dominio_di(b.link_candidatura)) THEN NULL
    ELSE b.link_candidatura_source
  END AS link_candidatura_source,
  -- gli allegati sono un array di oggetti con `url`: si filtrano elemento per
  -- elemento, così un allegato istituzionale non viene perso insieme a uno
  -- sull'aggregatore. Se `allegati` non è un array si lascia com'è (stessa
  -- logica difensiva di `contenuto`).
  CASE
    WHEN jsonb_typeof(b.allegati) <> 'array' THEN b.allegati
    ELSE (
      SELECT coalesce(jsonb_agg(e.value), '[]'::jsonb)
        FROM jsonb_array_elements(b.allegati) AS e(value)
       WHERE NOT public.bando_host_aggregatore(public.dominio_di(e.value ->> 'url'))
    )
  END AS allegati,
  b.titolo_raw,
  b.descrizione_raw,
  -- costante: tutte le righe della vista sono `completed`, così i predicati
  -- `stato_processing=eq.completed&slug=not.is.null` restano validi tali e quali
  'completed'::character varying AS stato_processing,
  -- il valore grezzo se l'host non è un aggregatore, altrimenti NULL:
  -- nessun link ad aggregatori esce dalle colonne pubbliche.
  -- `dominio_di` è fail-open (NULL su un URL che non riconosce, per esempio
  -- con l'host in escape percentuale o protocol-relative) e
  -- `bando_host_aggregatore(NULL)` vale false: senza la riga qui sotto un URL
  -- che il regex non riconosce ma che un browser risolve sull'aggregatore
  -- uscirebbe intatto. Host non riconosciuto ⇒ non si pubblica.
  CASE
    WHEN public.dominio_di(b.link_bando) IS NULL THEN NULL
    WHEN public.bando_host_aggregatore(public.dominio_di(b.link_bando)) THEN NULL
    ELSE b.link_bando
  END AS link_bando,
  -- ------------------------------------------------------------------------
  b.ricerca,
  b.pubblicato_at,
  b.created_at,
  b.ultimo_cambiamento_at
FROM public.bando b
WHERE b.pubblicato;

COMMENT ON VIEW public.bando_pubblico IS
  'Contratto di lettura del DB bandi (§13). Contiene i soli pubblicati non fusi. La verità sullo stato è stato_effettivo, non stato_bando. Un id o uno slug che qui non si trova si risolve su bando_fusione / bando_slug_storico. `fonte_ufficiale_e_atto` è true solo se il link dell''atto è a sua volta PUBBLICABILE: la vista è security_invoker, quindi il flag dipende anche dalla RLS di bando_link e un ruolo interno può leggerlo true dove anon lo legge false.';

REVOKE ALL ON TABLE public.bando_pubblico FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.bando_pubblico TO anon;
GRANT SELECT ON TABLE public.bando_pubblico TO service_role;

-- ---------------------------------------------------------------------------
-- 4. Controllo automatico dentro la transazione
-- ---------------------------------------------------------------------------
-- Il confronto come ruolo anon è nel blocco Verifica (richiede SET LOCAL ROLE
-- dentro una transazione a sé, da eseguire dopo il COMMIT): qui si verifica
-- almeno che la vista e il predicato coincidano.
DO $$
DECLARE n_vista bigint; n_pub bigint; n_predicato bigint;
BEGIN
  SELECT count(*) INTO n_vista FROM public.bando_pubblico;
  SELECT count(*) INTO n_pub   FROM public.bando WHERE pubblicato;
  SELECT count(*) INTO n_predicato
    FROM public.bando
   WHERE stato_processing::text = 'completed' AND slug IS NOT NULL
     AND bando_master_id IS NULL AND ritirato_at IS NULL;

  IF n_vista <> n_pub THEN
    RAISE EXCEPTION 'bando_pubblico ha % righe ma i pubblicati sono %', n_vista, n_pub;
  END IF;

  IF n_pub <> n_predicato THEN
    RAISE NOTICE
      'pubblicati % ≠ completed+slug non fusi né ritirati %: la differenza va spiegata riga per riga prima di procedere',
      n_pub, n_predicato;
  END IF;
END $$;

COMMIT;

-- ============================================================================
-- Riconciliazione (rieseguibile da sola)
-- ============================================================================
-- La vista non ha stato da riconciliare. Quello che va riverificato dopo
-- ogni fusione o ritiro è l'uguaglianza fra i tre conteggi:
--
--   SELECT
--     (SELECT count(*) FROM bando_pubblico)                                   AS vista,
--     (SELECT count(*) FROM bando WHERE pubblicato)                           AS pubblicati,
--     (SELECT count(*) FROM bando
--       WHERE stato_processing='completed' AND slug IS NOT NULL
--         AND bando_master_id IS NULL AND ritirato_at IS NULL)                AS predicato;
--   -- attesi tutti e tre uguali
--
-- Se `pubblicati` < `predicato`, la differenza deve corrispondere alle righe
-- in `bando_fusione` più quelle con `ritirato_at IS NOT NULL`:
--
--   SELECT count(*) FROM bando WHERE NOT pubblicato
--     AND stato_processing='completed' AND slug IS NOT NULL
--     AND bando_master_id IS NULL AND ritirato_at IS NULL;
--   -- atteso: 0 (qualunque altra riga è un errore, non una fusione)
-- ============================================================================

-- ============================================================================
-- Verifica post-deploy
-- ============================================================================
-- 1) La vista risponde come anon e i conteggi coincidono. Il blocco è
--    AUTO-CONTENUTO: `SET LOCAL` fuori da una transazione dà solo un WARNING e
--    la query gira come `postgres`, cioè come proprietario, che scavalca la
--    RLS e rende vero qualunque esito atteso. Incollare tutte e tre le righe
--    insieme; il ROLLBACK ripristina il ruolo.
--      BEGIN;
--        SET LOCAL ROLE anon;
--        SELECT count(*), count(link_bando), count(fonte_ufficiale_url) FROM bando_pubblico;
--      ROLLBACK;
--      SELECT count(*) FROM bando WHERE pubblicato;
--      -- atteso: il primo count uguale a quest'ultimo, nessun 42501
--
-- 2) Nessun aggregatore nelle colonne pubbliche. Le colonne di link sono
--    quattro, non una: `link_bando`, `link_candidatura`,
--    `fonte_ufficiale_url`/`_host` e gli `url` dentro `allegati`.
--      SELECT count(*) FROM bando_pubblico WHERE link_bando ILIKE '%obiettivoeuropa%';
--      -- atteso: 0
--      SELECT count(*) FROM bando_pubblico WHERE fonte_ufficiale_host ILIKE '%obiettivoeuropa%';
--      -- atteso: 0
--      SELECT count(*) FROM bando_pubblico WHERE link_candidatura ILIKE '%obiettivoeuropa%';
--      -- atteso: 0
--      SELECT count(*) FROM bando_pubblico, jsonb_array_elements(coalesce(allegati,'[]'::jsonb)) a
--       WHERE bando_host_aggregatore(dominio_di(a ->> 'url'));
--      -- atteso: 0
--    E la provenienza non resta orfana del link che descrive:
--      SELECT count(*) FROM bando_pubblico
--       WHERE link_candidatura IS NULL AND link_candidatura_source IS NOT NULL;
--      -- atteso: 0
--
-- 2-bis) La blocklist è accesa. `bando_host_aggregatore` torna false su una
--    riga disattivata, e il mascheramento avviene alla lettura: se questo
--    conteggio cala, i link dell'aggregatore sono tornati pubblici in
--    silenzio (la migrazione 02 protegge le righe del seed con
--    `trg_dominio_ufficiale_blocklist_protetta`, ma il conteggio resta
--    l'unica prova a posteriori).
--      SELECT count(*) FROM dominio_ufficiale WHERE tipo='aggregatore' AND attivo;
--      -- atteso: 25
--
-- 3) `contenuto` mai stringa.
--      SELECT count(*) FROM bando_pubblico WHERE contenuto IS NULL;
--      -- atteso: 9 (le righe a doppia codifica; erano già illeggibili)
--
-- 4) `stato_effettivo` coerente con la regola.
--      SELECT stato_bando, stato_effettivo, count(*) FROM bando_pubblico GROUP BY 1,2 ORDER BY 1,2;
--      -- atteso: nessuna riga con stato_effettivo='aperto' e data_scadenza < oggi
--      SELECT count(*) FROM bando_pubblico
--       WHERE stato_effettivo <> 'chiuso'
--         AND data_scadenza < (now() AT TIME ZONE 'Europe/Rome')::date;
--      -- atteso: solo i sospeso/revocato (0 prima della migrazione 06)
--
-- 5) Compatibilità con i predicati di BandoFit.
--      SELECT count(*) FROM bando_pubblico WHERE stato_processing = 'completed' AND slug IS NOT NULL;
--      -- atteso: = count(*) della vista
--
-- 6) Allowlist delle funzioni: per anon devono risultare eseguibili solo le
--    tre della vista e quelle di pg_trgm.
--      SELECT p.oid::regprocedure AS funzione
--        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
--       WHERE n.nspname='public'
--         AND has_function_privilege('anon', p.oid, 'EXECUTE')
--         AND p.proname NOT LIKE '%trgm%' AND p.proname NOT LIKE 'gtrgm%'
--         AND p.proname NOT LIKE 'similarity%' AND p.proname NOT LIKE 'word_similarity%'
--         AND p.proname NOT LIKE 'strict_word_similarity%' AND p.proname NOT LIKE 'set_limit%'
--         AND p.proname NOT LIKE 'show_limit%' AND p.proname NOT LIKE 'show_trgm%'
--       ORDER BY 1;
--      -- attese esattamente 3 righe: bando_stato_effettivo, dominio_di,
--      --   bando_host_aggregatore
--
-- 7) Prestazioni: rieseguire la query G1 di §2.a-bis del piano come anon con
--    EXPLAIN (ANALYZE, BUFFERS). Criterio: < 3 s (statement_timeout di anon).
--      BEGIN;
--        SET LOCAL ROLE anon;
--        EXPLAIN (ANALYZE, BUFFERS) <query G1>;
--      ROLLBACK;
--    Da rifare DOPO `python -m app domini --import` (IndicePA porta
--    `dominio_ufficiale` a ~23.000 righe): `bando_host_aggregatore` è
--    SECURITY DEFINER e quindi NON inlinabile, e la vista la chiama una volta
--    per riga. Con i due indici parziali della 02 la scansione resta sulle
--    poche righe `tipo='aggregatore'`; se il piano mostrasse un Seq Scan su
--    `dominio_ufficiale`, l'indice non sta venendo usato e va indagato prima
--    di passare alla fase (c).
-- ============================================================================
