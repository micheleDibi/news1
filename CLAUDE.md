# EduNews24 — contesto per le sessioni di lavoro

Testata su scuola, università e formazione. Frontend Astro SSR + backend Python + due database
Supabase distinti. Per architettura, pipeline e variabili d'ambiente in dettaglio: **`README.md`**
(attenzione: contiene sezioni disallineate dal codice — vedi §"Trappole note").

## Stack

- **Astro 5.4** con `output: "server"` e adapter `@astrojs/node` in modalità standalone.
  Tutte le rotte sono SSR on-demand: **nessun `getStaticPaths`, nessun `prerender = true`** nel repo.
- **Tailwind 3.4** (config in `tailwind.config.mjs`, utility `font-heading` = League Spartan).
- **React 18** usato **solo** nell'area admin.
- `astro.config.mjs`: `security.checkOrigin: false` (dietro Cloudflare + nginx), `server.port: 80`.

## Architettura dual-database

| | DB | Client | Contenuti |
|---|---|---|---|
| **Principale** | `PUBLIC_SUPABASE_URL` / `PUBLIC_SUPABASE_ANON_KEY` | `src/lib/supabase.ts` | `articles`, `categories`, `profiles`, `podcasts`, **`interpelli`**, **`selezione_personale`** |
| **Bandi** | `PUBLIC_SUPABASE_BANDI_URL` / `PUBLIC_SUPABASE_BANDI_ANON_KEY` | `src/lib/supabase-bandi.ts` | `bando` + cataloghi (`regioni`, `settori`, `programmi`, `tipologie_bando`, `beneficiari`, `codici_ateco`, `modalita_erogazione`) e junction `bando_regioni` / `bando_settori` / `bando_beneficiari` / `bando_codici_ateco` |

Le quattro variabili sono **bloccanti**: `createClient` viene chiamato a livello di modulo e i due
file sono importati top-level da rotte SSR e sitemap.

**Il frontend legge e basta.** Ogni scrittura sui bandi avviene dal backend con la service-role key.

## Avvio

```bash
npm run dev      # astro dev
npm run build    # astro build (pre/post-build copiano le credenziali Google)
node dist/server/entry.mjs   # produzione
```

Backend: `cd backend && uvicorn app.main:app --port 8000` (in produzione **senza** `--reload`).

## Dove sta cosa

```
src/pages/interpelli.astro            \
src/pages/selezione-personale.astro    >  le tre pagine elenco
src/pages/bandi.astro                 /
src/pages/{sezione}/[slug].astro         schede di dettaglio
src/pages/[category].astro               elenco articoli: pattern di paginazione riusabile
src/layouts/Layout.astro                 canonical, meta, JSON-LD org, <slot name="head" />
src/lib/seo.ts                           Article / Breadcrumb / ItemList / FAQ structured data
src/lib/supabase.ts, supabase-bandi.ts   i due client + dominio bandi
src/middleware.ts                        guardia sugli header di inoltro (prima istruzione,
                                         src/lib/intestazioni-inoltro.ts: X-Forwarded-Host/Proto/Port
                                         malformati → 400 su tutto il sito), content negotiation
                                         Markdown, well-known per agenti
src/pages/sitemap-*.xml.ts               ~17 rotte sitemap (vedi sotto)
src/lib/api-v1/                          API pubblica in sola lettura: moduli puri, più
                                         fonte-supabase.ts e rotta.ts impuri
src/pages/api/v1/**                      13 rotte di poche righe, logica in api-v1/risorse.ts
src/pages/sviluppatori/api.astro         documentazione pubblica (contenuti in api-v1/documentazione.ts)
public/robots.txt                        statico
docs/analisi-seo-elenchi.md              fotografia SEO delle tre liste, numeri reali dei DB
docs/report-seo-elenchi.md               intervento SEO: cosa è cambiato e cosa resta fuori scope
```

API v1: select esplicite solo in `api-v1/colonne.ts` (mai `*`), predicati di pubblicazione solo in
`api-v1/filtri.ts`, nessun testo integrale (solo sintesi e metadati), autore solo `public_name`
(mai `creator` né `full_name`). `tests/api-v1/contratto.test.ts` valida output ed esempi contro
gli schemi di `openapi.ts`.

### Pagine filtro e sitemap

Le tre sezioni hanno pagine filtro a tre segmenti (`/interpelli/regione/marche`,
`/bandi/programma/fse-fondo-sociale-europeo`, …) più un indice per dimensione
(`/interpelli/regione`). **Quali esistono si decide solo in `src/config/pagine-filtro.ts`**:
soglia per sezione, dimensioni abilitate, esclusioni, alias, etichette. Sotto soglia → 404 reale.
I conteggi vengono da `src/lib/corpus.ts`, cache in memoria con TTL 15' riscaldata dal middleware.

`sitemap-index.xml` è l'indice e elenca direttamente i blocchi da 1000 URL
(`/sitemap-<sezione>/N.xml`) più `sitemap-pagine-filtro.xml`. Le tre sitemap monolitiche storiche
rispondono 301 verso l'indice. Le tre landing di sezione stanno in `sitemap-categorie.xml.ts`.
Tutte le rotte sitemap sono SSR: il caching è solo via header `Cache-Control`.

### Pagine elenco

Lo stato della lista (filtri e `?page=N`) vive nell'URL ed è reso dal server: il form è un
`<form method="get">` che funziona senza JavaScript. Lo script in `src/scripts/lista.ts` è solo
progressive enhancement e chiede a `/api/lista/<sezione>` lo stesso frammento HTML che la pagina
renderebbe da sola — quindi il markup della card esiste una volta sola
(`src/components/liste/Card*.astro`). Pagina oltre l'ultima → 404; `?page=1` → 301.

## Pipeline (in due parole)

Scheduler Python in `backend/app/*_sender.py`, quattro esecuzioni al giorno (00:00/06:00/12:00/18:00).
Interpelli e selezione personale: scraping → classificazione → generazione articolo con Claude →
`status='completed'` (condizione di pubblicazione). Bandi: `scraper_bandi/` in 5 step
(discover → scrape → preprocess → enrich → seo) fino a `stato_processing='completed'`, che è la
condizione della RLS pubblica (`completed AND slug IS NOT NULL`).

## Convenzioni

- **Italiano** per commenti, naming dei moduli nuovi e testi visibili.
- **Tailwind**, niente CSS custom se evitabile. Declassare un heading richiede `font-heading`,
  altrimenti cambia il font (`Layout.astro` applica League Spartan a `h1,h2,h3`).
- **TypeScript** in `strict`, senza `any` nuovi dove evitabile.
- **Slug degli articoli: si genera una volta e poi è congelato.** Per i nuovi si usa
  `slugifica()` (`src/lib/slug.ts`, gemello di `backend/app/slug.py`), mai `slugify()` di
  `utils.ts`. Un update non può cambiare uno slug esistente senza l'header `X-Slug-Intent`, che
  deve contenere lo slug desiderato. L'intento **non** va in un campo del body: create/update
  passano il JSON grezzo a Supabase, e un campo estraneo fa fallire l'intero salvataggio.
- **URL pubblico di un articolo**: `getArticlePublicUrl()` di `src/lib/utils.ts`, che legge
  `category_slug` e `slug` dalle colonne. `getArticleUrl()` resta per i chiamanti storici ma
  slugifica il *nome* della categoria: non usarla per link nuovi.
- **Correzione ortografica**: `src/lib/ortografia.ts` e `backend/app/ortografia.py` sono gemelli e
  devono restare allineati. Si agganciano ai chokepoint con una **allowlist di campi**, mai con una
  ricorsione cieca sul payload (gli URL non vanno toccati). I test condivisi sono la difesa contro
  la divergenza: `npm test` e `npm run test:py`, entrambi su `tests/ortografia/casi.json`.
- **Niente git automatico**: modificare i file e basta, commit e branch li fa l'utente.
- **Niente nuove dipendenze npm** senza chiedere.
- **Mai stampare i valori di `.env`.**

## Trappole note

- Lo **slug degli interpelli non è a DB**: si ricalcola da `interpello_name + provincia|città +
  regione + id`. Le copie sono **due**, una per linguaggio (`slugInterpello` in
  `src/lib/liste/slug-interpello.ts`, ri-esportato da `src/lib/liste/interpelli.ts`;
  `_generate_interpello_slug` in `backend/app/interpelli.py`): devono restare identiche byte per
  byte, e `tests/estrazioni/slug-interpello.test.ts` lo verifica eseguendo la funzione Python.
  Per questo la correzione ortografica **non** tocca `interpello_name` né i campi geografici.
- **`scripts/migrate-slugs.ts` non va eseguito alla leggera**: riempie solo gli slug mancanti e
  pretende `MIGRAZIONE_SLUG=si` più `SCRIVI=si`. Nella versione precedente riscriveva lo slug di
  *tutte* le righe ed era l'unico punto capace di mandare in 410 l'intero archivio in un colpo solo.
- **Non esiste nessuna service-role key nel repo**: `backend/app/database.py` usa
  `PUBLIC_SUPABASE_ANON_KEY` malgrado il commento dica il contrario. Tutte le scritture su
  `articles` passano dalla anon key.
- `backend/app/sender.py` gira **ogni ora dalle 03:00 alle 19:00**, non quattro volte al giorno, e
  la sua pipeline **si ferma alla sintesi**: la generazione dell'articolo (skill base) parte solo a
  mano dall'admin, via `POST /api/news/reconstruct/{id}`.
- Su questa macchina esiste un **altro package Python chiamato `app`** sul `sys.path`: i test
  importano i moduli per percorso, non con `from app import ...`, altrimenti vince l'altro.
- `src/lib/utils.ts` → `slugify()` **non è accent-safe** (`città`→`citt`, `Valle d'Aosta`→`valle daosta`):
  non usarla per slug geografici.
- Le regioni hanno **grafie diverse nelle tre fonti**: `Emilia-Romagna` / `Emilia Romagna`,
  `Valle d'Aosta` / `Valle d'Aosta/Vallée d'Aoste`, `Trentino Alto Adige` / `Trentino-Alto Adige/Südtirol`.
- `selezione_personale.calculated_status` vale `OPEN` su **tutte** le righe: lo stato reale va
  ricalcolato da `data_scadenza` (90% del corpus è scaduto).
- `bando.data_pubblicazione` è NULL sul 92% delle righe: ogni query paginata **deve** avere un
  tiebreak `.order('id')`, altrimenti le pagine si sovrappongono.
- `src/pages/api/interpelli/refresh.ts` importa file inesistenti: endpoint scollegato.
- Il `README.md` è disallineato su `scraper_bandi/` (descritto "in costruzione", in realtà completo),
  sui nomi delle junction (al plurale nel DB), sulla RLS e su alcuni comandi che non esistono più.

## Test

Non c'è un test runner installato e non se ne aggiungono: si usano quelli della piattaforma.

```bash
npm test        # node --test, gemello TypeScript
npm run test:py # unittest della stdlib, gemello Python
npm run test:py:bandi # unittest di scraper_bandi (richiede scraper_bandi/.venv)
```

Entrambi leggono `tests/ortografia/casi.json`, che contiene i casi di `correggi()` e quelli di
`slugifica()` con lo `sha256` atteso e un conteggio minimo: nessuno può cancellare casi in
silenzio. `npx astro check` **non** è disponibile (richiederebbe `@astrojs/check`): per il
controllo dei tipi si usa `npx tsc --noEmit -p tsconfig.json`, che ha errori preesistenti.

`npm test` carica il resolve hook `tests/supporto/registra-risolutore.mjs` (i moduli di `src/`
importano senza estensione) ed esegue `tests/**/*.test.ts` con `TZ=Asia/Kathmandu` (fuso fisso
+05:45, smaschera l'ora locale). Per un solo file:
`TZ=Asia/Kathmandu node --experimental-strip-types --disable-warning=ExperimentalWarning --import ./tests/supporto/registra-risolutore.mjs --test <file>`.

## Cosa NON toccare

`backend/`, `scraper_bandi/`, `backend/sql/`, `scripts/`, l'area admin. Niente migrazioni, niente
scritture su Supabase dal frontend, niente operazioni git.

> **Deroga registrata (intervento "URL copiabile, slug congelato, accenti").** Su richiesta esplicita
> dell'utente sono stati modificati: `backend/app/` (nuovi `ortografia.py`, `slug.py`, `llm_json.py`;
> modificati `main.py`, `interpelli.py`, `selezione_personale.py`, `variables_edunews.py`),
> `backend/skill/` e `backend/news-angle-rewriter-persona/scripts/firecrawl_scrape.py`,
> `scraper_bandi/app/{seo_skill,bando_resolver,preprocessor,enricher}.py` (solo ortografia dei
> prompt), `scripts/migrate-slugs.ts` (guardia), l'area admin
> (`src/components/ArticleForm.tsx`, `src/pages/admin.astro`, `src/pages/admin/articles/index.astro`,
> `src/pages/api/articles/**`). La deroga vale per quell'intervento: fuori da lì la regola sopra
> resta in vigore.

> **Deroga registrata (intervento "fonti ufficiali e bandi attivi", 22-23/09/2026).** Su richiesta
> esplicita dell'utente, e limitatamente a questo intervento, sono stati modificati: tutto
> `scraper_bandi/` (moduli nuovi `stato_bando, scarico, bilancio, blocco, registro, telemetria,
> dominio_ufficiale, impronte, allegati, gemelli, sedia, oe_scheda, fonte_ufficiale, segnali, eventi,
> monitoraggio, rigenera`; bug fix su adapter, login OE, logger, date, runner, CLI, db, seo;
> `scraper_bandi/tests/` creata; `README.md` bonificato dalle credenziali), `backend/app/{bandi_pipeline,bandi_sender}.py`,
> `backend/sql/bando_v11_01..07_*.sql` + rollback + seed (**scritti e mai eseguiti**: li applica
> l'utente nel SQL Editor), la parte bandi di `src/` (`src/lib/bandi/**`,
> `src/config/domini-aggregatori.ts`, `stato-bando.ts`, `supabase-bandi.ts`, `liste/bandi.ts`,
> `corpus.ts`, scheda e card, sitemap dei bandi, `api-v1/**` per la v1.1,
> `src/pages/api/indexnow-notify.ts`), le rimozioni di `/eu-funding` (compresi i due file dell'area
> admin e `backend/app/ScrapingBandiEuropeiFinal/`), `package.json` (script `test:py:bandi`),
> `tests/**` e `docs/{contratto-db-bandi.md,bandi-monitor/AVANZAMENTO.md,api-v1.md}`.
> `backend/app/indexnow.py` e `src/lib/indexnow.ts` **non** sono stati toccati. Fuori da questo
> elenco la regola sopra resta in vigore.
>
> Conseguenze operative: lo stato di un bando si calcola in un solo posto per linguaggio a partire da
> `tests/stato-bando/casi.json` (`src/lib/stato-bando.ts`, `scraper_bandi/app/stato_bando.py`, blocco
> CASI della migrazione 04): cambiare la regola in un solo linguaggio fa fallire i test. Le migrazioni
> `backend/sql/bando_v11_*` vanno applicate in ordine (01 → 02 → seed → 03 → 04 → 05 — è l'ordine
> scritto nelle intestazioni dei file SQL, e il seed fallisce con un `RAISE EXCEPTION` se la 02 non
> c'è; poi 06 solo dopo
> il rilascio difensivo di BandoFit e 07 solo dopo la sua migrazione al contratto
> `docs/contratto-db-bandi.md`). Finché non sono applicate, il codice nuovo degrada da solo
> (`db.controllo` rileva le colonne assenti) e monitor e resolver restano in modalità ombra.
