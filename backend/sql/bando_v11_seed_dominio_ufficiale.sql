-- ============================================================================
-- bando_v11_seed_dominio_ufficiale.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Riempie `dominio_ufficiale` con la parte di whitelist e blocklist che si
--   scrive a mano: i portali pubblici versionati, i pattern istituzionali e
--   la blocklist degli aggregatori (che la migrazione 02 ha già seminato
--   nella sua parte minima, qui completata con social e video).
--
--   NON sta qui, ed è voluto:
--     * IndicePA (`enti.xlsx`, ~23 000 enti) e i 118 host di `fonte.link`:
--       li carica `python -m app domini --import`, mensile, con `--dry-run`
--       e `--limit`; un file SQL con 23 000 INSERT non è una migrazione;
--     * gli host `dedotto` (confidenza 0,60): nascono dalla misura in ombra
--       e non da una decisione a tavolino.
--
-- Fase: (b). Va applicato SUBITO DOPO la migrazione 02 e PRIMA della 03: il
--   trigger `trg_bando_fonte_ufficiale_dominio` e la semina di
--   `bando_controllo` leggono questa tabella.
--
-- Precondizioni
--   `bando_v11_02_tabelle_di_servizio.sql` applicata.
--
-- Rompe BandoFit? NO. La tabella è interna: nessun grant di lettura ad anon
--   né ad authenticated. La blocklist che il contratto pubblica in
--   `docs/contratto-db-bandi.md` è la proiezione testuale di queste righe, e
--   ogni modifica va comunicata a BandoFit prima di applicarla.
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'intero file. Rieseguibile: ogni
--   INSERT è `ON CONFLICT (host) DO NOTHING`, quindi una riga già corretta a
--   mano dal committente NON viene sovrascritta. Per cambiare davvero una
--   riga esistente si usa il blocco «Riconciliazione» in fondo.
--
-- Nota sulla semantica delle righe
--   `tipo`        ente | portale_pubblico | pattern | dedotto | aggregatore
--   `confidenza`  soglia: sotto 0,80 un url_prova non rende mai «verificato»
--                 un evento, quindi `dedotto` (0,60) porta al massimo a
--                 `in_verifica`.
--   `host`        con `*` la riga è un pattern (il jolly diventa % in LIKE);
--                 senza `*` vale l'host esatto e ogni suo sottodominio.
--   La blocklist prevale sempre su tutto il resto.
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
  IF to_regclass('public.dominio_ufficiale') IS NULL THEN
    RAISE EXCEPTION 'manca dominio_ufficiale: applicare prima bando_v11_02_tabelle_di_servizio.sql';
  END IF;
END $$;

-- Ripetuta anche qui: il file può essere applicato da solo, e una tabella
-- di questo genere non deve MAI essere leggibile con la anon key (che sta
-- nel bundle del frontend).
REVOKE ALL ON TABLE public.dominio_ufficiale FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------
-- 1. Blocklist: aggregatori
-- ---------------------------------------------------------------------------
-- Sono i siti che ripubblicano i bandi altrui. Un loro URL non può essere
-- una fonte ufficiale, non può essere la prova di un evento e non può
-- comparire in nessuna colonna leggibile da anon. Il confronto copre anche i
-- sottodomini.
--
-- RIPETIZIONE VOLUTAMENTE INERTE: queste dieci righe sono le stesse che la
-- migrazione 02 semina già (blocklist minima, le serve ai suoi trigger).
-- L'ordine è 02 → seed, e l'INSERT è `ON CONFLICT (host) DO NOTHING`: qui non
-- viene mai scritto nulla e vince sempre il testo della 02. Restano scritte
-- perché questo file deve leggersi come la blocklist completa; il `note` è
-- stato riallineato a quello della 02, così i due file non si contraddicono.

INSERT INTO public.dominio_ufficiale (host, tipo, confidenza, origine, note) VALUES
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

-- ---------------------------------------------------------------------------
-- 2. Blocklist: social e video
-- ---------------------------------------------------------------------------
-- Un post o un video non sono l'atto: non provano niente e non si linkano
-- come «fonte ufficiale», nemmeno quando li pubblica l'ente.

INSERT INTO public.dominio_ufficiale (host, tipo, confidenza, origine, note) VALUES
  ('facebook.com',  'aggregatore', 1.00, 'seed', 'social'),
  ('instagram.com', 'aggregatore', 1.00, 'seed', 'social'),
  ('x.com',         'aggregatore', 1.00, 'seed', 'social'),
  ('twitter.com',   'aggregatore', 1.00, 'seed', 'social'),
  ('linkedin.com',  'aggregatore', 1.00, 'seed', 'social'),
  ('threads.net',   'aggregatore', 1.00, 'seed', 'social'),
  ('pinterest.com', 'aggregatore', 1.00, 'seed', 'social'),
  ('tiktok.com',    'aggregatore', 1.00, 'seed', 'video'),
  ('youtube.com',   'aggregatore', 1.00, 'seed', 'video'),
  ('youtu.be',      'aggregatore', 1.00, 'seed', 'video'),
  ('vimeo.com',     'aggregatore', 1.00, 'seed', 'video'),
  ('t.me',          'aggregatore', 1.00, 'seed', 'messaggistica'),
  ('telegram.me',   'aggregatore', 1.00, 'seed', 'messaggistica'),
  ('wa.me',         'aggregatore', 1.00, 'seed', 'messaggistica'),
  ('whatsapp.com',  'aggregatore', 1.00, 'seed', 'messaggistica')
ON CONFLICT (host) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. Portali pubblici versionati (confidenza 1,00)
-- ---------------------------------------------------------------------------
-- Non sono «l'ente» ma sono pubblici e autorevoli: una pagina qui vale
-- `trovata` con tipo `portale_pubblico`, che nella gerarchia sta sotto
-- `ente` (e sotto il sotto-tipo `atto`, cioè il PDF dell'atto sul dominio
-- dell'ente).
-- Gli host `.gov.it` sarebbero già coperti dal pattern del punto 4 con
-- confidenza 0,80: qui vengono elencati per alzarli a 1,00.

INSERT INTO public.dominio_ufficiale (host, tipo, confidenza, origine, ente) VALUES
  ('incentivi.gov.it',       'portale_pubblico', 1.00, 'seed', 'MIMIT — Incentivi.gov.it'),
  ('italiadomani.gov.it',    'portale_pubblico', 1.00, 'seed', 'PNRR — Italia Domani'),
  ('opencoesione.gov.it',    'portale_pubblico', 1.00, 'seed', 'OpenCoesione'),
  ('agenziacoesione.gov.it', 'portale_pubblico', 1.00, 'seed', 'Agenzia per la coesione territoriale'),
  ('gazzettaufficiale.it',   'portale_pubblico', 1.00, 'seed', 'Gazzetta Ufficiale della Repubblica Italiana'),
  ('ec.europa.eu',           'portale_pubblico', 1.00, 'seed', 'Commissione europea'),
  ('mimit.gov.it',           'portale_pubblico', 1.00, 'seed', 'Ministero delle imprese e del made in Italy'),
  ('mur.gov.it',             'portale_pubblico', 1.00, 'seed', 'Ministero dell''università e della ricerca'),
  ('istruzione.gov.it',      'portale_pubblico', 1.00, 'seed', 'Ministero dell''istruzione e del merito'),
  ('lavoro.gov.it',          'portale_pubblico', 1.00, 'seed', 'Ministero del lavoro e delle politiche sociali'),
  ('invitalia.it',           'portale_pubblico', 1.00, 'seed', 'Invitalia'),
  ('inps.it',                'portale_pubblico', 1.00, 'seed', 'INPS'),
  ('consip.it',              'portale_pubblico', 1.00, 'seed', 'Consip'),
  ('unioncamere.it',         'portale_pubblico', 1.00, 'seed', 'Unioncamere'),
  ('anpal.gov.it',           'portale_pubblico', 1.00, 'seed', 'ANPAL'),
  ('lazioinnova.it',         'portale_pubblico', 1.00, 'seed', 'Lazio Innova'),
  ('finlombarda.it',         'portale_pubblico', 1.00, 'seed', 'Finlombarda'),
  ('artea.toscana.it',       'portale_pubblico', 1.00, 'seed', 'ARTEA — Regione Toscana'),
  ('sviluppumbria.it',       'portale_pubblico', 1.00, 'seed', 'Sviluppumbria'),
  ('filse.it',               'portale_pubblico', 1.00, 'seed', 'FILSE — Regione Liguria')
ON CONFLICT (host) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. Pattern istituzionali (confidenza 0,80)
-- ---------------------------------------------------------------------------
-- 0,80 è esattamente la soglia sopra la quale un url_prova può rendere
-- «verificato» un evento: un dominio istituzionale riconosciuto per forma
-- basta, ma senza margine. Il `*` diventa `%` in un LIKE, quindi
-- `regione.*.it` copre regione.lombardia.it, regione.marche.it e simili.

INSERT INTO public.dominio_ufficiale (host, tipo, confidenza, origine, note) VALUES
  ('*.gov.it',      'pattern', 0.80, 'seed', 'amministrazioni centrali'),
  ('*.edu.it',      'pattern', 0.80, 'seed', 'istituzioni scolastiche'),
  ('*.camcom.it',   'pattern', 0.80, 'seed', 'camere di commercio'),
  ('*.europa.eu',   'pattern', 0.80, 'seed', 'istituzioni europee'),
  ('regione.*.it',  'pattern', 0.80, 'seed', 'regioni'),
  ('provincia.*.it','pattern', 0.80, 'seed', 'province'),
  ('comune.*.it',   'pattern', 0.80, 'seed', 'comuni')
ON CONFLICT (host) DO NOTHING;

COMMIT;

-- ============================================================================
-- Riconciliazione (rieseguibile da sola)
-- ============================================================================
-- Gli INSERT qui sopra non sovrascrivono nulla, di proposito: una riga
-- corretta a mano resta com'è. Per cambiare DAVVERO una riga esistente
-- (tipicamente per alzare o abbassare una confidenza, o per disattivare un
-- host senza perderne la storia):
--
--   UPDATE dominio_ufficiale SET confidenza = 1.00, note = '<perché>'
--    WHERE host = '<host>';
--
-- Disattivare un host, SOLO se è `ente` o `portale_pubblico` (cioè parte
-- della whitelist): serve quando un dominio cambia o viene dismesso e non si
-- vuole perderne la storia.
--
--   UPDATE dominio_ufficiale SET attivo = false, note = '<perché e quando>'
--    WHERE host = '<host>' AND tipo IN ('ente', 'portale_pubblico');
--
-- NON vale per la BLOCKLIST. Disattivare un aggregatore del seed, cambiarne
-- il `tipo` o l'`host` ripubblicherebbe i suoi link su ~1700 bandi in
-- silenzio, senza errori e senza log, perché la vista maschera alla lettura:
-- il trigger `trg_dominio_ufficiale_blocklist_protetta` (migrazione 02) lo
-- rifiuta con 23514, e toglierlo deve restare un atto deliberato e visibile.
-- Se un host della blocklist va davvero tolto, è una decisione da comunicare
-- a BandoFit come tutte le altre modifiche del contratto.
--
-- Aggiungere un aggregatore scoperto in ombra (host trovato dalla ricerca
-- per ≥5 bandi di ≥3 enti diversi). ATTENZIONE: la blocklist è parte del
-- contratto pubblico, quindi va comunicata a BandoFit PRIMA:
--
--   INSERT INTO dominio_ufficiale (host, tipo, confidenza, origine, note)
--   VALUES ('<host>', 'aggregatore', 1.00, 'scoperta', '<n bandi, n enti, data>')
--   ON CONFLICT (host) DO UPDATE SET tipo='aggregatore', confidenza=1.00, attivo=true;
--
-- Dopo ogni modifica della blocklist, i link già pubblicabili su quel
-- dominio vanno chiusi (il trigger vale solo sulle scritture nuove):
--
--   UPDATE bando_link SET pubblicabile = false
--    WHERE pubblicabile AND bando_host_aggregatore(dominio);
--   SELECT id, slug, fonte_ufficiale_host FROM bando
--    WHERE fonte_ufficiale_host IS NOT NULL AND bando_host_aggregatore(fonte_ufficiale_host);
--   -- le righe trovate vanno riportate a fonte_ufficiale_link_id = NULL e
--   -- fonte_ufficiale_stato = 'in_verifica' (il trigger della 03 rifiuta
--   -- qualunque altro UPDATE che le lasci com'erano)
--
-- TERZA query obbligatoria dopo ogni modifica della blocklist: le prove già
-- scritte in `bando_evento`. `b_evento_prova_non_aggregatore` è BEFORE INSERT
-- soltanto, quindi non le tocca, e `url_prova`/`dominio_prova` sono fra le
-- colonne che anon legge. L'immutabilità dell'evento è ASIMMETRICA apposta
-- (migrazione 02, 4.c): una prova si può solo togliere, mai cambiare.
--
--   UPDATE bando_evento SET url_prova = NULL, verificato = false, in_aggiornamenti = false
--    WHERE url_prova IS NOT NULL AND bando_host_aggregatore(dominio_prova);
--   SELECT count(*) FROM bando_evento WHERE url_prova IS NOT NULL
--     AND bando_host_aggregatore(dominio_prova);   -- atteso: 0
--
-- E il corpo degli eventi, dove `graduatoria`/`esito`/`nuovo_allegato`/`faq`
-- portano il link nuovo. `valore_dopo` resta IMMUTABILE anche dopo la 4.c
-- della 02, quindi questa è una RILEVAZIONE, non una ripulitura: se torna
-- più di 0, le righe vanno sostituite con eventi nuovi collegati da
-- `riferisce_a`, ed è una decisione da prendere con BandoFit.
--
--   SELECT count(*) FROM bando_evento WHERE valore_dopo::text ILIKE '%obiettivoeuropa%';
--   -- atteso: 0
-- ============================================================================

-- ============================================================================
-- Verifica post-deploy
-- ============================================================================
-- 1) Conteggi per tipo.
--      SELECT tipo, count(*) FROM dominio_ufficiale GROUP BY 1 ORDER BY 1;
--      -- attesi: aggregatore 25, pattern 7, portale_pubblico 20
--      --   (più ente/dedotto dopo `python -m app domini --import`)
--
-- 2) La funzione riconosce host e sottodomini.
--      SELECT bando_host_aggregatore('obiettivoeuropa.com')       AS esatto,      -- true
--             bando_host_aggregatore('www.obiettivoeuropa.com')   AS con_www,     -- true
--             bando_host_aggregatore('cdn.obiettivoeuropa.com')   AS sottodominio,-- true
--             bando_host_aggregatore('obiettivoeuropa.com.evil.it') AS finto,     -- false
--             bando_host_aggregatore('lazioeuropa.it')            AS ente,        -- false
--             bando_host_aggregatore(NULL)                        AS nullo;       -- false
--
-- 3) `dominio_di` normalizza come ci si aspetta.
--      SELECT dominio_di('https://WWW.Regione.Marche.it/bandi/x?y=1#z'),  -- regione.marche.it
--             dominio_di('http://user:pw@incentivi.gov.it:8080/a'),       -- incentivi.gov.it
--             dominio_di('non un url'),                                   -- NULL
--             dominio_di(NULL);                                           -- NULL
--
-- 4) La tabella resta invisibile ad anon.
--      SELECT count(*) FROM information_schema.role_table_grants
--       WHERE table_schema='public' AND table_name='dominio_ufficiale'
--         AND grantee IN ('anon','authenticated');
--      -- atteso: 0
--      Blocco auto-contenuto: fuori da una transazione `SET LOCAL` dà solo un
--      WARNING e la query gira come proprietario, che legge la tabella senza
--      alcun ostacolo — l'esito atteso non potrebbe mai verificarsi.
--      BEGIN; SET LOCAL ROLE anon; SELECT count(*) FROM dominio_ufficiale; ROLLBACK;
--      -- atteso: 42501
--
-- 5) Nessun aggregatore cade dentro un pattern istituzionale. La blocklist
--    prevarrebbe comunque, ma una sovrapposizione è quasi sempre il segno di
--    un pattern scritto troppo largo:
--      SELECT a.host AS aggregatore, p.host AS pattern
--        FROM dominio_ufficiale a, dominio_ufficiale p
--       WHERE a.tipo = 'aggregatore' AND p.tipo = 'pattern' AND p.attivo
--         AND a.host LIKE replace(p.host, '*', '%');
--      -- atteso: 0 righe
-- ============================================================================
