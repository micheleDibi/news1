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
src/middleware.ts                        content negotiation Markdown, well-known per agenti
src/pages/sitemap-*.xml.ts               ~17 rotte sitemap (vedi sotto)
public/robots.txt                        statico
docs/analisi-seo-elenchi.md              fotografia SEO delle tre liste, numeri reali dei DB
docs/report-seo-elenchi.md               intervento SEO: cosa è cambiato e cosa resta fuori scope
```

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
- **Niente git automatico**: modificare i file e basta, commit e branch li fa l'utente.
- **Niente nuove dipendenze npm** senza chiedere.
- **Mai stampare i valori di `.env`.**

## Trappole note

- Lo **slug degli interpelli non è a DB**: si ricalcola da `interpello_name + provincia|città +
  regione + id` con `generateInterpelloSlug`, duplicata in 4 file (3 nel frontend, 1 in
  `backend/app/interpelli.py`). Qualsiasi modifica va sincronizzata su tutti.
- `src/lib/utils.ts` → `slugify()` **non è accent-safe** (`città`→`citt`, `Valle d'Aosta`→`valle daosta`):
  non usarla per slug geografici.
- Le regioni hanno **grafie diverse nelle tre fonti**: `Emilia-Romagna` / `Emilia Romagna`,
  `Valle d'Aosta` / `Valle d'Aosta/Vallée d'Aoste`, `Trentino Alto Adige` / `Trentino-Alto Adige/Südtirol`.
- `selezione_personale.calculated_status` vale `OPEN` su **tutte** le righe: lo stato reale va
  ricalcolato da `data_scadenza` (90% del corpus è scaduto).
- `bando.data_pubblicazione` è NULL sul 92% delle righe: ogni query paginata **deve** avere un
  tiebreak `.order('id')`, altrimenti le pagine si sovrappongono.
- `src/components/bandi/` è **codice morto** (nessun import da `src/pages/`) e diverge dal markup vivo.
- `src/pages/api/interpelli/refresh.ts` importa file inesistenti: endpoint scollegato.
- Il `README.md` è disallineato su `scraper_bandi/` (descritto "in costruzione", in realtà completo),
  sui nomi delle junction (al plurale nel DB), sulla RLS e su alcuni comandi che non esistono più.

## Cosa NON toccare

`backend/`, `scraper_bandi/`, `backend/sql/`, `scripts/`, l'area admin. Niente migrazioni, niente
scritture su Supabase dal frontend, niente operazioni git.
