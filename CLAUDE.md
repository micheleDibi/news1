# Progetto: EduNews24

Testata online su scuola, università e formazione (edunews24.it): frontend Astro SSR, backend Python, due database
Supabase distinti. Produzione su servizi systemd (repo in `~/projects/news1`) dietro Cloudflare + nginx; sviluppo in
locale su macOS; nessuno staging documentato. Per architettura, pipeline e variabili d'ambiente in dettaglio:
`README.md` (riallineato al codice il 25/09/2026; in caso di contrasto vale il codice). Fonti aggiornate:
`docs/bandi-monitor/RIPRESA.md` (da leggere per primo nelle sessioni sui bandi), `docs/contratto-db-bandi.md`,
`docs/api-v1.md`, `.env.example`.

## Stack
- Linguaggio/versione: TypeScript `strict` (Node 22, in locale 22.14; i test usano `--experimental-strip-types`) e
  Python (README: 3.10+; in locale e nel venv di scraper_bandi 3.12).
- Framework: **Astro 5.4** con `output: "server"` e `@astrojs/node` standalone: tutte le rotte sono SSR on-demand,
  **nessun `getStaticPaths`, nessun `prerender = true`**. **Tailwind 3.4** (`font-heading` = League Spartan). **React
  18** nell'area admin e in alcune isole pubbliche (ContactForm, AudioPlayer, login/registrazione). Backend FastAPI +
  uvicorn.
- Database **principale** (`PUBLIC_SUPABASE_URL` / `PUBLIC_SUPABASE_ANON_KEY`, `src/lib/supabase.ts`): `articles`,
  `categories`, `profiles`, `podcasts`, **`interpelli`**, **`selezione_personale`**.
- Database **bandi** (`PUBLIC_SUPABASE_BANDI_URL` / `PUBLIC_SUPABASE_BANDI_ANON_KEY`, `src/lib/supabase-bandi.ts`,
  client + dominio bandi): `bando` + cataloghi (`regioni`, `settori`, `programmi`, `tipologie_bando`, `beneficiari`,
  `codici_ateco`, `modalita_erogazione`) e junction `bando_regioni` / `bando_settori` / `bando_beneficiari` /
  `bando_codici_ateco`.
- Le quattro variabili sono **bloccanti**: `createClient` è chiamato a livello di modulo e i due file sono importati
  top-level da rotte SSR e sitemap. **Il frontend legge e basta**: ogni scrittura sui bandi avviene dal backend con la
  service-role key.

## Mappa del codice
- `src/pages/{interpelli,selezione-personale,bandi}.astro`: le tre pagine elenco (logica in `src/lib/liste/`, card in
  `src/components/liste/Card*.astro`); `src/pages/{sezione}/[slug].astro`: schede di dettaglio.
- `src/pages/[category].astro`: elenco articoli. Il pattern di paginazione da riusare è `src/lib/paginazione.ts` (la
  guardia "pagina fuori range" di `[category].astro` è rotta).
- `src/layouts/Layout.astro`: canonical, meta, JSON-LD org, `<slot name="head" />`. `src/lib/seo.ts`: structured data
  Article / Breadcrumb / ItemList / FAQ.
- `src/lib/api-v1/`: API pubblica in sola lettura, moduli puri più `fonte-supabase.ts` e `rotta.ts` impuri;
  `src/pages/api/v1/**`: 13 rotte di poche righe (logica in `api-v1/risorse.ts`); documentazione pubblica in
  `src/pages/sviluppatori/api.astro` (contenuti in `api-v1/documentazione.ts`).
- Pagine filtro a tre segmenti (`/interpelli/regione/marche`, `/bandi/programma/fse-fondo-sociale-europeo`, …) e
  indici per dimensione (`/interpelli/regione`): **quali esistono si decide solo in `src/config/pagine-filtro.ts`**
  (soglia per dimensione, dimensioni abilitate, esclusioni, alias, etichette); sotto soglia → 404 reale. Conteggi da
  `src/lib/corpus.ts`, cache in memoria con TTL 15' riscaldata dal middleware.
- Sitemap: 21 rotte (`src/pages/sitemap*.xml.ts`, le sottocartelle `sitemap-*/`, `recent-news-sitemap.xml.ts`), tutte
  SSR, caching solo via header `Cache-Control`. `sitemap-index.xml` elenca i blocchi da 1000 URL
  (`/sitemap-<sezione>/N.xml`) più `sitemap-pagine-filtro.xml`; le tre monolitiche storiche → 301 all'indice; le
  landing di sezione in `sitemap-categorie.xml.ts`. `public/robots.txt` è statico.
- `backend/app/*_sender.py`: scheduler. Interpelli e selezione personale alle 00/06/12/18: scraping → classificazione
  → articolo con Claude → `status='completed'` (condizione di pubblicazione).
- `scraper_bandi/` (venv proprio): giro alle 00/06/12/18 da `backend/app/bandi_sender.py` (step in
  `bandi_pipeline.py`): discover → scrape → preprocess → enrich → resolver → seo (più ricontrolli e monitor alle 06 e
  18) fino a `stato_processing='completed'`, condizione della RLS pubblica (`completed AND slug IS NOT NULL`).
- `docs/analisi-seo-elenchi.md`: fotografia SEO delle tre liste, numeri reali dei DB. `docs/report-seo-elenchi.md`:
  intervento SEO, cosa è cambiato e cosa resta fuori scope.
- Punto di ingresso: `dist/server/entry.mjs` (build) o `astro dev`; ogni richiesta passa prima da `src/middleware.ts`,
  che come prima istruzione applica la guardia sugli header di inoltro (`src/lib/intestazioni-inoltro.ts`:
  `X-Forwarded-Host/Proto/Port` malformati → 400 su tutto il sito), poi content negotiation Markdown e well-known per
  agenti. Backend: `backend/app/main.py`.
- Configurazione: `astro.config.mjs` (`security.checkOrigin: false` perché dietro Cloudflare + nginx,
  `server.port: 80`), `tsconfig.json`, `tailwind.config.mjs`, `.env` e `scraper_bandi/.env`: NON modificare senza
  chiedere.

## Comandi
- Avvio locale: `npm run dev`, sulla porta 80: `server.port` di `astro.config.mjs` vale anche per `astro dev`
  (verificato nel sorgente di Astro, non avviando il server). Il backend però assume `FRONTEND_URL` =
  `http://localhost:4321` e in CORS ammette solo `localhost:3000` e `localhost:4321`. Build: `npm run build` (pre/post-build copiano le credenziali Google ed escono con errore se
  manca `src/pages/api/tts/google-credentials.json`; in locale `npx astro build`). Produzione:
  `node dist/server/entry.mjs`.
- Backend: `cd backend && uvicorn app.main:app --port 8000` (in produzione **senza** `--reload`). In locale così non
  parte: `backend/` non ha un venv e da lì `app` risolve sul package omonimo (vedi "Trappole note").
- Bandi: `cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app <comando> --dry-run --limit N`
  (comandi in RIPRESA §6). Senza `--dry-run` scrivono sul DB vero: gli step base (`discover`, `scrape-bandi`,
  `preprocess`, `enrich`, `seo`) non hanno modalità ombra; i comandi v11 accettano `--ombra`/`--attivo` e, senza,
  decide la variabile `*_MODALITA` dell'ambiente.
- Test singolo TS:
  `TZ=Asia/Kathmandu node --experimental-strip-types --disable-warning=ExperimentalWarning --import ./tests/supporto/registra-risolutore.mjs --test <file>`.
  Python: `cd backend && python3 -m unittest tests.test_<nome>`; per scraper_bandi
  `cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_<nome>`.
- Test completi (misurati il 25/09/2026: circa 2 s, 0,4 s e 3 s): `npm test` (node --test, gemello TypeScript;
  controllare anche `# skipped 0`), `npm run test:py` (unittest della stdlib, gemello Python), `npm run test:py:bandi`
  (unittest di scraper_bandi, richiede `scraper_bandi/.venv`). Non c'è un test runner installato e non se ne
  aggiungono: si usano quelli della piattaforma. `npm test` carica il resolve hook
  `tests/supporto/registra-risolutore.mjs` (i moduli di `src/` importano senza estensione) ed esegue
  `tests/**/*.test.ts` con `TZ=Asia/Kathmandu` (fuso fisso +05:45, smaschera l'ora locale).
- Lint/format: nessuno. Tipi: `npx --no-install tsc --noEmit -p tsconfig.json`, con errori preesistenti (51 al
  25/09/2026); `npx astro check` **non** è disponibile (richiederebbe `@astrojs/check`).

## Convenzioni
- **Italiano** per commenti, naming dei moduli nuovi e testi visibili.
- **Tailwind**, niente CSS custom se evitabile. Declassare un heading richiede `font-heading`, altrimenti cambia il
  font (`Layout.astro` applica League Spartan a `h1,h2,h3`).
- **TypeScript** in `strict`, senza `any` nuovi dove evitabile. La logica testabile va in moduli puri (chi importa
  `supabase*.ts` non si carica sotto `node --test`), senza `enum`, `namespace`, parameter properties.
- **Slug degli articoli: si genera una volta e poi è congelato.** Per i nuovi `slugifica()` (`src/lib/slug.ts`,
  gemello di `backend/app/slug.py`), mai `slugify()` di `utils.ts`. Un update non può cambiare uno slug esistente
  senza l'header `X-Slug-Intent` con lo slug desiderato. L'intento **non** va nel body: create/update passano il JSON
  grezzo a Supabase, e un campo estraneo fa fallire l'intero salvataggio.
- **URL pubblico di un articolo**: `getArticlePublicUrl()` di `src/lib/utils.ts` (legge `category_slug` e `slug`).
  `getArticleUrl()` resta per i chiamanti storici ma slugifica il *nome* della categoria: non usarla per link nuovi.
- **Correzione ortografica**: `src/lib/ortografia.ts` e `backend/app/ortografia.py` sono gemelli e devono restare
  allineati. Si agganciano ai chokepoint con una **allowlist di campi**, mai con una ricorsione cieca sul payload (gli
  URL non vanno toccati). Difesa contro la divergenza: `npm test` e `npm run test:py` leggono
  `tests/ortografia/casi.json` (casi di `slugifica()` e di `correggi()`, questi con `sha256` atteso e conteggio
  minimo: nessuno può cancellarli in silenzio).
- **API v1**: select esplicite solo in `api-v1/colonne.ts` (mai `*`), predicati di pubblicazione solo in
  `api-v1/filtri.ts`, nessun testo integrale (solo sintesi e metadati), autore solo `public_name` (mai `creator` né
  `full_name`). `tests/api-v1/contratto.test.ts` valida output ed esempi contro gli schemi di `openapi.ts`.
- **Pagine elenco**: stato (filtri e `?page=N`) nell'URL, reso dal server; `<form method="get">` che funziona senza
  JavaScript. `src/scripts/lista.ts` è solo progressive enhancement e chiede a `/api/lista/<sezione>` lo stesso
  frammento HTML, quindi il markup della card esiste una volta sola. Pagina oltre l'ultima → 404; `?page=1` → 301.
- **Git**: vale la regola globale (`~/.claude/CLAUDE.md` §3: branch `claude/<descrizione>`, commit locali a ogni passo
  funzionante, mai push).
- **Niente nuove dipendenze npm** senza chiedere. **Mai stampare i valori di `.env`.** (RIPRESA §7 estende: niente
  pip; niente cookie e token.)

## Da non toccare
`backend/`, `scraper_bandi/`, `backend/sql/`, `scripts/`, l'area admin. Niente migrazioni, niente scritture su
Supabase dal frontend. Per git vale la regola globale (vedi "Convenzioni").

> **Deroga registrata (intervento "URL copiabile, slug congelato, accenti").** Su richiesta esplicita dell'utente sono
> stati modificati: `backend/app/` (nuovi `ortografia.py`, `slug.py`, `llm_json.py`; modificati `main.py`,
> `interpelli.py`, `selezione_personale.py`, `variables_edunews.py`), `backend/skill/` e
> `backend/news-angle-rewriter-persona/scripts/firecrawl_scrape.py`,
> `scraper_bandi/app/{seo_skill,bando_resolver,preprocessor,enricher}.py` (solo ortografia dei prompt),
> `scripts/migrate-slugs.ts` (guardia), l'area admin (`src/components/ArticleForm.tsx`, `src/pages/admin.astro`,
> `src/pages/admin/articles/index.astro`, `src/pages/api/articles/**`). La deroga vale per quell'intervento: fuori da
> lì la regola sopra resta in vigore.

> **Deroga registrata (intervento "fonti ufficiali e bandi attivi", 22-23/09/2026).** Su richiesta esplicita
> dell'utente, e limitatamente a questo intervento, sono stati modificati: tutto `scraper_bandi/` (moduli nuovi
> `stato_bando, scarico, bilancio, blocco, registro, telemetria, dominio_ufficiale, impronte, allegati, gemelli, sedia, oe_scheda, fonte_ufficiale, segnali, eventi, monitoraggio, rigenera`;
> bug fix su adapter, login OE, logger, date, runner, CLI, db, seo; `scraper_bandi/tests/` creata; `README.md`
> bonificato dalle credenziali), `backend/app/{bandi_pipeline,bandi_sender}.py`,
> `backend/sql/bando_v11_01..07_*.sql` + rollback + seed (**scritti e mai eseguiti**: li applica l'utente nel SQL
> Editor), la parte bandi di `src/` (`src/lib/bandi/**`, `src/config/domini-aggregatori.ts`, `stato-bando.ts`,
> `supabase-bandi.ts`, `liste/bandi.ts`, `corpus.ts`, scheda e card, sitemap dei bandi, `api-v1/**` per la v1.1,
> `src/pages/api/indexnow-notify.ts`), le rimozioni di `/eu-funding` (compresi i due file dell'area admin e
> `backend/app/ScrapingBandiEuropeiFinal/`), `package.json` (script `test:py:bandi`), `tests/**` e
> `docs/{contratto-db-bandi.md,bandi-monitor/AVANZAMENTO.md,api-v1.md}`. `backend/app/indexnow.py` e
> `src/lib/indexnow.ts` **non** sono stati toccati. Fuori da questo elenco la regola sopra resta in vigore.
>
> Conseguenze operative: lo stato di un bando si calcola in un solo posto per linguaggio a partire da
> `tests/stato-bando/casi.json` (`src/lib/stato-bando.ts`, `scraper_bandi/app/stato_bando.py`, blocco CASI della
> migrazione 04): cambiare la regola in un solo linguaggio fa fallire i test. Le migrazioni `backend/sql/bando_v11_*`
> vanno applicate in ordine (01 → 02 → seed → 03 → 04 → 05 — è l'ordine scritto nelle intestazioni dei file SQL, e il
> seed fallisce con un `RAISE EXCEPTION` se la 02 non c'è; poi 06 solo dopo il rilascio difensivo di BandoFit e 07
> solo dopo la sua migrazione al contratto `docs/contratto-db-bandi.md`). Finché non sono applicate, il codice nuovo
> degrada da solo (`db.controllo` rileva le colonne assenti) e monitor e resolver restano in modalità ombra.

> Stato al 25/09/2026 (RIPRESA §1, che resta la fonte aggiornata): applicate 01, 02, seed, 03, 04, 05, 08, 09, 10;
> mancano 06 e 07; resolver attivo, monitor in ombra salvo due tipi di evento attivati a mano.

> **Deroga registrata (intervento "documentazione allineata al codice", 25/09/2026).** Su richiesta esplicita
> dell'utente è stato modificato solo il commento in testa a `scripts/migrate-slugs.ts` (il lancio documentato non
> esisteva), senza toccare il codice. Fuori da questo elenco la regola sopra resta in vigore.

Inoltre, sempre (non toccati dalle deroghe):
- Credenziali mai in file tracciati (vivono in `.env`, `scraper_bandi/.env`,
  `src/pages/api/tts/google-credentials.json`, tutti ignorati da git); `google-credentials.json` mai in `public/`.
- Slug pubblicati di pagine filtro e regioni: congelati (per rinominare, `slugAlias` con 301).
- DB bandi, letto anche da BandoFit: id mai riusati, nessuna riga cancellata, slug dei pubblicati congelati, un
  pubblicato non esce mai da `completed` (`docs/contratto-db-bandi.md`).

## Trappole note
- Lo **slug degli interpelli non è a DB**: si ricalcola da `interpello_name + provincia|città + regione + id`. Le
  copie sono **due**, una per linguaggio (`slugInterpello` in `src/lib/liste/slug-interpello.ts`, ri-esportato da
  `src/lib/liste/interpelli.ts`; `_generate_interpello_slug` in `backend/app/interpelli.py`): devono restare identiche
  byte per byte nell'output, e `tests/estrazioni/slug-interpello.test.ts` lo verifica eseguendo la funzione Python.
  Per questo la correzione ortografica **non** tocca `interpello_name` né i campi geografici.
- **`scripts/migrate-slugs.ts` non va eseguito alla leggera**: tocca solo gli slug mancanti o non conformi e pretende
  `MIGRAZIONE_SLUG=si` (altrimenti non parte) più `SCRIVI=si` (senza, stampa solo cosa farebbe). Nella versione
  precedente riscriveva lo slug di *tutte* le righe ed era l'unico punto capace di mandare in 410 l'intero archivio in
  un colpo solo. Oggi non ha un lancio funzionante (vedi il commento in testa al file).
- **Nessuna service-role key del DB principale nel repo**: `backend/app/database.py` usa `PUBLIC_SUPABASE_ANON_KEY`
  malgrado il commento dica il contrario. Tutte le scritture su `articles` passano dalla anon key.
- `backend/app/sender.py` gira **ogni ora dalle 03:00 alle 19:00**, non quattro volte al giorno, e la sua pipeline
  **si ferma alla sintesi**: la generazione dell'articolo (skill base) parte solo a mano dall'admin, via
  `POST /api/news/reconstruct/{id}`. `backend/test.py` **non è un test**: scrive sul Supabase vero.
- Su questa macchina esiste un **altro package Python chiamato `app`** sul `sys.path`: i test importano i moduli per
  percorso, non con `from app import ...`, altrimenti vince l'altro.
- `src/lib/utils.ts` → `slugify()` **non è accent-safe** (`città`→`citt`, `Valle d'Aosta`→`valle-daosta`): non usarla
  per slug geografici.
- Le regioni hanno **grafie diverse nelle tre fonti**: `Emilia-Romagna` / `Emilia Romagna`, `Valle d'Aosta` /
  `Valle d'Aosta/Vallée d'Aoste`, `Trentino Alto Adige` / `Trentino-Alto Adige/Südtirol` (lo slug viene da
  `src/lib/regioni.ts`).
- `selezione_personale.calculated_status` vale `OPEN` su **tutte** le righe: lo stato reale va ricalcolato da
  `data_scadenza` (90% del corpus è scaduto).
- `bando.data_pubblicazione` è NULL sul 92% delle righe: ogni query paginata **deve** avere un tiebreak
  `.order('id')`, altrimenti le pagine si sovrappongono.
- PostgREST restituisce al massimo 1000 righe senza dirlo (in `scraper_bandi` si legge con `_scorri()`/`_per_id()` di
  `app/db.py`).
- `src/pages/api/interpelli/refresh.ts` importa un file di tipi inesistente e scrive in `src/data/`, che non esiste:
  endpoint scollegato.

