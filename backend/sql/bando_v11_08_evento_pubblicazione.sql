-- ============================================================================
-- bando_v11_08_evento_pubblicazione.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Chiude il buco che rende MUTO il flusso degli avvisi: l'evento
--   `pubblicazione` esisteva solo come backfill una tantum (sezione 8.b della
--   02) e come effetto della RPC `bando_pubblica` (2.g della 04), che però
--   nessuno chiama — la pubblicazione avviene da sola nel trigger BEFORE
--   `trg_bando_pubblica_al_completamento` della 01, appena una riga diventa
--   `completed` con slug e stato. Risultato misurato in produzione il
--   23/09/2026: 2124 righe con `pubblicato = true` e 2114 eventi di tipo
--   `pubblicazione`. Ricostruita l'ora esatta dai dati (il backfill scrive i
--   cursori in una sola transazione, quindi tutti gli eventi seminati hanno lo
--   stesso `pubblicato_at`): la 02 è stata applicata alle 16:14:28 di Roma e
--   fino a quell'istante la copertura era perfetta, 2114 eventi per 2114
--   pubblicati. Fra le 16:17:01 e le 16:18:30 la pipeline ne ha pubblicati
--   altri 10: nessuno dei 10 ha l'evento. Il buco è solo in avanti.
--
--   `trg_bando_promuovi_eventi` (02, 4.d) NON copre il caso: PROMUOVE gli
--   eventi già scritti che aspettano il cursore, non ne crea. Se nessuno
--   scrive l'evento, non c'è niente da promuovere.
--
--   Perché conta: il capitolo 6 del contratto (`docs/contratto-db-bandi.md`)
--   presenta `bando_evento` come il flusso che un consumatore segue con
--   `?cursore=gt.<ultimo>&order=cursore.asc`, e `pubblicazione` è il primo dei
--   tipi che ricevono il cursore. Senza un trigger che lo emetta, chi segue il
--   cursore non viene MAI a sapere dei bandi nuovi: è esattamente il caso
--   d'uso degli avvisi, ed è l'unico modo che BandoFit ha di accorgersi di un
--   bando nuovo senza rileggere l'intero archivio.
--
-- Fase: (b) — nessuna colonna nuova, nessuna riga di `bando` riscritta.
--
-- Precondizioni
--   * `bando_v11_01_pubblicazione.sql` applicata (serve `bando.pubblicato` e
--     `bando.pubblicato_at`);
--   * `bando_v11_02_tabelle_di_servizio.sql` applicata (servono la tabella
--     `bando_evento`, il trigger `a_evento_cursore` che assegna il cursore e
--     l'allowlist `bando_evento_tipo_pubblico`).
--   Le migrazioni 03, 04 e 05 non servono a questo file e non gli danno
--   fastidio; la 06 e la 07 nemmeno. Il file si applica sia prima sia dopo.
--
-- Rompe BandoFit? NO. Nessuno schema cambia: compaiono solo righe nuove in
--   `bando_evento`, con lo stesso tipo e gli stessi valori di quelle che il
--   backfill della 02 ha già seminato. Un consumatore fermo al suo cursore le
--   vede arrivare nell'ordine, che è precisamente ciò che gli è stato
--   promesso. Un consumatore che NON legge gli eventi non si accorge di nulla.
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'INTERO file, poi il blocco
--   «Verifica post-deploy». Il file è rieseguibile: `CREATE OR REPLACE
--   FUNCTION`, `DROP TRIGGER IF EXISTS` prima del `CREATE TRIGGER`, e il
--   recupero è un `INSERT … SELECT … WHERE NOT EXISTS` con `ON CONFLICT DO
--   NOTHING`.
--
--   Meglio FRA UN GIRO DI PIPELINE E L'ALTRO. Il `CREATE TRIGGER` vuole un
--   lock esclusivo su `bando`: con una scrittura concorrente in corso il file
--   si ferma o sul `lock_timeout` (5s, «canceling statement due to lock
--   timeout») o sul controllo M1 in fondo, che vede l'impronta di
--   `updated_at` cambiata da quell'altra transazione. In tutti e due i casi
--   si annulla l'INTERA transazione e non resta niente a metà — né il
--   trigger, né mezzo recupero: si ritenta a pipeline ferma.
--
-- COSA NON È REVERSIBILE
--   Gli eventi creati da qui in poi (e quelli recuperati dal punto 3: una
--   decina alla misura del 23/09/2026) ricevono un cursore, e un cursore
--   assegnato non si toglie mai: la policy di `anon` è `USING (cursore IS NOT
--   NULL)` e un consumatore può averli già letti.
--   Il rollback toglie trigger e funzione e lascia le righe dov'erano —
--   cancellarle romperebbe la monotonia del flusso, e `DELETE` su
--   `bando_evento` è revocato perfino a `service_role`.
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

  IF to_regclass('public.bando_evento') IS NULL THEN
    RAISE EXCEPTION 'manca bando_evento: applicare prima bando_v11_02_tabelle_di_servizio.sql';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_trigger
                  WHERE tgrelid = 'public.bando_evento'::regclass
                    AND tgname = 'a_evento_cursore') THEN
    RAISE EXCEPTION
      'manca il trigger a_evento_cursore su bando_evento: senza, gli eventi nascerebbero senza cursore e invisibili ad anon. Applicare bando_v11_02_tabelle_di_servizio.sql';
  END IF;

  -- Se qualcuno avesse stretto l'allowlist dei tipi pubblici, questo file
  -- produrrebbe in silenzio eventi `leggibile = false` senza cursore: cioè
  -- tornerebbe esattamente al difetto che sta chiudendo, ma in modo più
  -- difficile da vedere. Meglio non applicarlo affatto.
  IF NOT public.bando_evento_tipo_pubblico('pubblicazione') THEN
    RAISE EXCEPTION
      'bando_evento_tipo_pubblico non considera pubblico il tipo «pubblicazione»: l''evento nascerebbe senza cursore';
  END IF;
END $$;

-- Impronta di `updated_at`: questo file NON aggiorna nessuna riga di `bando`
-- — scrive solo in `bando_evento` — e il controllo in fondo alla transazione
-- lo dimostra (M1). Se l'impronta cambia, la transazione si annulla da sola.
CREATE TEMP TABLE _v11_08_impronta ON COMMIT DROP AS
SELECT md5(string_agg(id::text || ':' || coalesce(updated_at::text, ''), ',' ORDER BY id)) AS impronta
  FROM public.bando;

-- ===========================================================================
-- 1. La funzione trigger
-- ===========================================================================
-- Gli stessi identici valori del backfill 8.b della 02, perché sono la stessa
-- riga vista da due momenti diversi: origine `pipeline` (la pubblicazione
-- nasce dalla pipeline, non dal cron né dalla redazione), `data_evento` nel
-- calendario di Roma, `leggibile = true`, `in_aggiornamenti = false` (la
-- nascita di un bando non è un «aggiornamento» da mostrare nel box: lo dice
-- anche `bando_registra_evento` della 04, che abbassa `in_aggiornamenti` per
-- `pubblicazione`), `verificato = false` e nessun `url_prova` — non c'è
-- niente da provare, e con `verificato = true` senza prova il CHECK
-- `bando_evento_verificato_prova_check` respingerebbe la riga.
--
-- Il cursore NON si scrive qui: lo assegna `a_evento_cursore` sotto advisory
-- lock. Scriverlo farebbe scattare `a0_evento_cursore_non_esterno` (23514).
--
-- SECURITY DEFINER come i due trigger gemelli (`bando_promuovi_eventi` della
-- 02, `bando_crea_controllo` della 03): chi pubblica un bando non deve avere
-- bisogno di privilegi propri su `bando_evento`.
CREATE OR REPLACE FUNCTION public.bando_evento_pubblicazione()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  momento timestamptz;
BEGIN
  -- Solo la TRANSIZIONE a pubblicato. Una riga già pubblicata viene riscritta
  -- di continuo (re-scrape, monitor, enrichment, `ultimo_controllo_at`): senza
  -- questa riga ogni UPDATE ritenterebbe l'INSERT, e la difesa sarebbe il solo
  -- `NOT EXISTS`, cioè una query su `bando_evento` per ogni scrittura di ogni
  -- pubblicato.
  -- Il confronto sta QUI e non nella clausola WHEN del trigger per un motivo
  -- preciso: un trigger dichiarato anche su INSERT non può nominare `OLD`
  -- nella WHEN — PostgreSQL lo rifiuta al `CREATE TRIGGER`, non a runtime. E
  -- `TG_OP` nella WHEN non esiste. Elencare le colonne con `UPDATE OF
  -- pubblicato` sarebbe peggio: `UPDATE OF` guarda la SET list del comando,
  -- non il valore finale, e `pubblicato` non lo scrive mai chi fa l'UPDATE —
  -- lo alza il trigger BEFORE della 01. È lo stesso no-op silenzioso già
  -- trovato due volte in questo progetto (02 §4.d, 03 §4.a).
  IF TG_OP = 'UPDATE' AND OLD.pubblicato THEN
    RETURN NULL;
  END IF;

  -- Stessa espressione del backfill: `pubblicato_at` quando c'è (lo scrive il
  -- trigger della 01 nello stesso comando, quindi in NEW c'è già), altrimenti
  -- `created_at` per le righe storiche, altrimenti adesso.
  momento := coalesce(NEW.pubblicato_at, NEW.created_at, now());

  BEGIN
    INSERT INTO public.bando_evento
      (bando_id, tipo, origine, data_evento, rilevato_at,
       leggibile, in_aggiornamenti, verificato)
    SELECT NEW.id,
           'pubblicazione',
           'pipeline',
           -- `timestamptz::date` dipenderebbe da TimeZone: la zona va detta.
           (momento AT TIME ZONE 'Europe/Rome')::date,
           momento,
           true,
           false,
           false
     -- Un bando si pubblica una volta sola. La riga può però tornare
     -- `pubblicato = false` per una fusione (`bando_fondi`) o un ritiro, e poi
     -- essere ripubblicata: allora `OLD.pubblicato` è di nuovo false e senza
     -- questo NOT EXISTS nascerebbe un secondo evento `pubblicazione`. È lo
     -- stesso predicato del backfill 8.b della 02 — sul TIPO, non sul giorno.
     WHERE NOT EXISTS (
       SELECT 1 FROM public.bando_evento e
        WHERE e.bando_id = NEW.id
          AND e.tipo = 'pubblicazione'
     )
    -- Cintura: l'indice parziale `bando_evento_dedup_uidx` copre anche
    -- `pubblicazione`, e due scritture concorrenti sulla stessa riga
    -- potrebbero superare entrambe il NOT EXISTS.
    ON CONFLICT DO NOTHING;

  EXCEPTION WHEN OTHERS THEN
    -- La pubblicazione di un bando non deve MAI fallire per colpa del suo
    -- evento: il bando pubblicato è il valore, l'evento è la notifica. Il
    -- blocco EXCEPTION apre una sotto-transazione che annulla il solo INSERT
    -- e lascia intatta la riga di `bando` (siamo in un AFTER: la riga è già
    -- scritta). L'evento perso si recupera con il blocco «Riconciliazione» in
    -- fondo a questo file, che è la stessa query del punto 3.
    --
    -- Costo, misurato: il blocco EXCEPTION apre una sotto-transazione e
    -- consuma un XID per ogni riga che PUBBLICA (301 XID per un UPDATE che ne
    -- pubblica 300 in un colpo solo; oltre 64 sotto-transazioni nella stessa
    -- transazione lo snapshot va in suboverflow e gli altri backend pagano
    -- `pg_subtrans`). Non riguarda questa pipeline, che pubblica una riga per
    -- statement, né il re-scrape di massa, che esce dal `RETURN NULL` di sopra
    -- senza entrare qui (misurato: 1 solo XID per un UPDATE su oltre 1500
    -- righe già pubblicate).
    -- Da ricordare solo se un giorno si pubblicasse in blocco.
    RAISE WARNING
      'bando %: evento «pubblicazione» non registrato (% — %). La pubblicazione resta; recuperare con il blocco Riconciliazione della 08.',
      NEW.id, SQLSTATE, SQLERRM;
  END;

  RETURN NULL;   -- AFTER FOR EACH ROW: il valore di ritorno viene ignorato
END;
$$;

COMMENT ON FUNCTION public.bando_evento_pubblicazione() IS
  'Emette l''evento `pubblicazione` quando una riga di bando diventa pubblicata. Stessi valori del backfill 8.b della 02. Non solleva mai: un errore diventa WARNING e la pubblicazione resta.';

-- I privilegi di default del progetto concedono ALL ad anon E authenticated
-- sulle funzioni nuove (schema.sql:1870). Una funzione SECURITY DEFINER
-- eseguibile con la anon key, che sta nel bundle del frontend, scriverebbe in
-- `bando_evento` per conto del proprietario. Va revocata, sempre.
REVOKE ALL ON FUNCTION public.bando_evento_pubblicazione() FROM PUBLIC, anon, authenticated;
-- Nessun GRANT a service_role: il privilegio di eseguire una funzione trigger
-- si controlla al `CREATE TRIGGER`, non a ogni scatto. Stessa scelta di
-- `bando_promuovi_eventi` (02) e `bando_crea_controllo` (03).

-- ===========================================================================
-- 2. Il trigger
-- ===========================================================================
-- Forma già collaudata da `trg_bando_crea_controllo` (03, §4.a): AFTER INSERT
-- OR UPDATE, WHEN (NEW.pubblicato), nessuna lista di colonne.
--   * AFTER e non BEFORE: l'evento cita un bando che deve già esistere, e
--     `a_evento_cursore` va a cercarlo in tabella (`SELECT 1 FROM bando WHERE
--     id = NEW.bando_id AND pubblicato`) per decidere il cursore. In un BEFORE
--     INSERT quella riga non ci sarebbe ancora e l'evento resterebbe in attesa.
--   * anche su INSERT: la pipeline può scrivere una riga già `completed` con
--     slug e stato, e il trigger BEFORE della 01 la pubblica al volo. Quel
--     percorso non passa da nessun UPDATE ed è proprio il buco che la
--     Riconciliazione della 02 documentava come «da promuovere a mano».
--   * `WHEN (NEW.pubblicato)` e non `WHEN (NEW.pubblicato AND NOT
--     OLD.pubblicato)`: su INSERT `OLD` non esiste e PostgreSQL rifiuta il
--     `CREATE TRIGGER`. La seconda metà della condizione è la prima istruzione
--     della funzione.
--
-- ORDINE. I trigger AFTER di pari livello scattano in ordine ALFABETICO di
-- nome. Su `bando` diventano tre:
--     trg_bando_crea_controllo        (03)  → riga in `bando_controllo`
--     trg_bando_evento_pubblicazione  (qui) → evento `pubblicazione`
--     trg_bando_promuovi_eventi       (02)  → cursore agli eventi in attesa
-- Il nome è scelto per stare in mezzo, e non è un dettaglio: un bando
-- pubblicato può avere eventi in attesa emessi dal resolver mentre era ancora
-- `enriched`. Scattando PRIMA di `trg_bando_promuovi_eventi`, l'evento
-- `pubblicazione` prende il cursore più basso, e un consumatore che legge per
-- cursore crescente scopre il bando PRIMA di ricevere notizie su di esso.
-- All'inverso vedrebbe una `fonte_ufficiale_verificata` per un bando di cui
-- non sa ancora niente. I due trigger convivono senza toccarsi: questo INSERISCE
-- una riga nuova (che nasce già con il cursore, perché `bando` a quel punto
-- risulta pubblicato), l'altro fa UPDATE sulle righe rimaste senza.
DROP TRIGGER IF EXISTS trg_bando_evento_pubblicazione ON public.bando;
CREATE TRIGGER trg_bando_evento_pubblicazione
  AFTER INSERT OR UPDATE ON public.bando
  FOR EACH ROW
  WHEN (NEW.pubblicato)
  EXECUTE FUNCTION public.bando_evento_pubblicazione();

-- ===========================================================================
-- 3. Recupero dei mancanti
-- ===========================================================================
-- Le righe pubblicate DOPO il backfill 8.b della 02 e prima di questo file:
-- alla misura del 23/09/2026 erano una decina (2124 pubblicati, 2114 eventi),
-- e la pipeline ne aggiunge a ogni giro — all'atto dell'applicazione saranno
-- di più. È letteralmente lo stesso INSERT del backfill, ed è rieseguibile.
--
-- Il solito ordine «prima il backfill, poi i trigger» qui non serve: questo
-- INSERT scrive in `bando_evento` e non tocca nemmeno una riga di `bando`,
-- quindi il trigger appena creato non ha modo di scattare e non c'è niente da
-- disattivare. `ORDER BY b.id`: QUI i cursori nascono nell'ordine degli id,
-- non a caso — un consumatore che parte adesso legge l'archivio in ordine.
-- Vale per questo INSERT soltanto: dentro un UPDATE multi-riga il trigger
-- scatta nell'ordine in cui il piano tocca le righe, che non è quello degli id
-- (misurato). Non è un problema — il contratto promette che il cursore sia
-- monotono, non che segua gli id, e la pipeline pubblica una riga per volta.
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
-- 4. Controllo M1: nessuna riga di `bando` toccata da questo file
-- ---------------------------------------------------------------------------
-- L'impronta guarda l'INTERA tabella, quindi vede anche l'UPDATE di un'altra
-- transazione committata nel frattempo: in quel caso il file si annulla pur
-- non avendo sbagliato niente. È il motivo della raccomandazione in testa
-- («fra un giro di pipeline e l'altro»); si ritenta e basta.

DO $$
DECLARE prima text; dopo text;
BEGIN
  SELECT impronta INTO prima FROM _v11_08_impronta;
  SELECT md5(string_agg(id::text || ':' || coalesce(updated_at::text, ''), ',' ORDER BY id))
    INTO dopo FROM public.bando;
  IF dopo IS DISTINCT FROM prima THEN
    RAISE EXCEPTION
      'il recupero della 08 ha mosso updated_at su bando, oppure una scrittura concorrente lo ha fatto mentre il file girava. Transazione annullata: ritentare a pipeline ferma.';
  END IF;
END $$;

COMMIT;

-- ============================================================================
-- Riconciliazione (rieseguibile da sola)
-- ============================================================================
-- 1) Eventi `pubblicazione` mancanti. Da rilanciare se il WARNING della
--    funzione compare nei log, o dopo un ripristino parziale. È la stessa
--    query del punto 3 e non tocca `bando`: niente DISABLE/ENABLE dei trigger
--    `updated_at`.
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
-- 2) Eventi rimasti senza cursore su bandi ormai pubblici (li promuove il
--    trigger della 02, ma solo se il bando passa da un UPDATE: questo li
--    recupera comunque). È la Riconciliazione della 02, ripetuta qui perché
--    dopo questo file va lanciata insieme alla 1).
--
--      UPDATE bando_evento e
--         SET leggibile = leggibile
--        FROM bando b
--       WHERE b.id = e.bando_id
--         AND e.leggibile AND e.cursore IS NULL
--         AND (b.pubblicato OR b.bando_master_id IS NOT NULL OR b.ritirato_at IS NOT NULL);
-- ============================================================================

-- ============================================================================
-- Verifica post-deploy
-- ============================================================================
-- I NUMERI ASSOLUTI qui sotto (2124 e compagnia) sono la fotografia della
-- misura del 23/09/2026: la pipeline pubblica quattro volte al giorno, quindi
-- all'atto dell'applicazione saranno più alti e uno scostamento NON è un
-- fallimento. Le invarianti che non invecchiano sono tre: il punto 1 vale 0,
-- il punto 3 vale 0, e al punto 4 `con_evento = pubblicati + spubblicati`.
--
-- 1) Nessun pubblicato senza il suo evento. È l'invariante che questo file
--    introduce.
--      SELECT count(*) FROM bando b
--       WHERE b.pubblicato
--         AND NOT EXISTS (SELECT 1 FROM bando_evento e
--                          WHERE e.bando_id = b.id AND e.tipo = 'pubblicazione');
--      -- atteso: 0
--
-- 2) Tutti gli eventi `pubblicazione` hanno il cursore: senza cursore la
--    policy di anon (`USING (cursore IS NOT NULL)`) li nasconde e l'evento
--    non esiste per chi lo aspetta.
--      SELECT count(*) FILTER (WHERE cursore IS NULL) AS senza_cursore,
--             count(*)                                AS totali
--        FROM bando_evento WHERE tipo = 'pubblicazione';
--      -- atteso: senza_cursore = 0, sempre. `totali` è quanti sono: 2124
--      --   alla misura del 23/09/2026, di più dopo ogni giro di pipeline.
--
-- 3) Un evento per bando, non due.
--      SELECT count(*) FROM (
--        SELECT bando_id FROM bando_evento WHERE tipo='pubblicazione'
--         GROUP BY bando_id HAVING count(*) > 1) x;
--      -- atteso: 0
--
-- 4) Il conteggio torna. Attenzione all'unica asimmetria legittima: un
--    doppione FUSO o un bando RITIRATO torna `pubblicato = false` ma conserva
--    il suo evento (il cursore non si revoca mai), quindi l'uguaglianza vale
--    finché nessuna fusione e nessun ritiro sono stati eseguiti. La forma
--    giusta dell'invariante è la terza colonna.
--      SELECT (SELECT count(*) FROM bando WHERE pubblicato)                    AS pubblicati,
--             (SELECT count(DISTINCT bando_id) FROM bando_evento
--               WHERE tipo='pubblicazione')                                    AS con_evento,
--             (SELECT count(*) FROM bando b WHERE NOT b.pubblicato
--                AND EXISTS (SELECT 1 FROM bando_evento e
--                             WHERE e.bando_id=b.id AND e.tipo='pubblicazione')) AS spubblicati;
--      -- fotografia del 23/09/2026: 2124, 2124, 0 — le prime due colonne
--      --   crescono insieme a ogni giro di pipeline
--      -- atteso sempre: con_evento = pubblicati + spubblicati
--
-- 5) I tre trigger AFTER su `bando`, nell'ordine in cui scattano.
--      SELECT tgname FROM pg_trigger
--       WHERE tgrelid='public.bando'::regclass AND NOT tgisinternal
--         AND (tgtype & 2) = 0
--       ORDER BY tgname;
--      -- atteso: trg_bando_crea_controllo, trg_bando_evento_pubblicazione,
--      --         trg_bando_promuovi_eventi
--
-- 6) Il trigger emette davvero, e l'evento nasce leggibile con il cursore.
--    Da ANNULLARE: pubblica un bando vero. Lo slug e lo stato si riempiono
--    solo se mancano — su una riga NON pubblicata è lecito
--    (`trg_bando_slug_congelato` guarda `OLD.pubblicato`), e serve perché il
--    trigger della 01 pubblica solo un `completed` con slug e stato.
--      BEGIN;
--        UPDATE bando
--           SET slug             = coalesce(slug, 'verifica-08-' || id),
--               stato_bando      = coalesce(stato_bando, 'aperto'),
--               stato_processing = 'completed'
--         WHERE id = (SELECT id FROM bando
--                      WHERE NOT pubblicato AND bando_master_id IS NULL
--                        AND ritirato_at IS NULL
--                      ORDER BY id LIMIT 1);
--        SELECT bando_id, tipo, origine, data_evento, in_aggiornamenti,
--               verificato, url_prova, cursore IS NOT NULL AS ha_cursore
--          FROM bando_evento ORDER BY id DESC LIMIT 1;
--        -- atteso: tipo 'pubblicazione', origine 'pipeline', data di oggi a
--        --   Roma, in_aggiornamenti false, verificato false, url_prova NULL,
--        --   ha_cursore true
--      ROLLBACK;
--
-- 7) Un UPDATE qualunque su una riga GIÀ pubblicata non emette niente: è la
--    condizione che evita un evento a ogni re-scrape (da annullare). Una riga
--    sola: non serve bloccarne 2124 per una verifica.
--      BEGIN;
--        SELECT count(*) AS prima FROM bando_evento WHERE tipo='pubblicazione';
--        UPDATE bando SET titolo = titolo || ''
--         WHERE id = (SELECT id FROM bando WHERE pubblicato ORDER BY id LIMIT 1);
--        SELECT count(*) AS dopo FROM bando_evento WHERE tipo='pubblicazione';
--        -- atteso: dopo = prima
--      ROLLBACK;
--
-- 8) La funzione non è eseguibile con la anon key.
--      SELECT has_function_privilege('anon',
--        'public.bando_evento_pubblicazione()', 'EXECUTE') AS anon,
--             has_function_privilege('authenticated',
--        'public.bando_evento_pubblicazione()', 'EXECUTE') AS authenticated;
--      -- atteso: false, false
--
-- 9) Come anon: il flusso del cursore contiene i bandi nuovi. Il blocco è
--    AUTO-CONTENUTO di proposito — `SET LOCAL` fuori da una transazione dà
--    solo un WARNING e la query girerebbe come `postgres`, che scavalca la
--    RLS e renderebbe veri tutti gli esiti attesi. Incollare tutte le righe
--    insieme.
--      BEGIN;
--        SET LOCAL ROLE anon;
--        SELECT id, bando_id, tipo, cursore FROM bando_evento
--         WHERE tipo='pubblicazione' ORDER BY cursore DESC LIMIT 5;
--        -- atteso: 5 righe, i cursori più alti del flusso
--      ROLLBACK;
--
-- 10) Nessun `updated_at` mosso (sostituire :inizio con l'istante prima
--     dell'applicazione):
--      SELECT count(*) FROM bando WHERE updated_at >= :inizio;   -- atteso: 0
-- ============================================================================
