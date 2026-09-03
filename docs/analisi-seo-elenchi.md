# Analisi SEO delle pagine elenco — /interpelli, /selezione-personale, /bandi

Data dell'analisi: **3 settembre 2026**. Repo: `news1` (Astro 5.4.2, `output: "server"`, adapter `@astrojs/node` standalone).

Questo documento è il deliverable della Fase 0: cosa è stato verificato, con quale metodo, che cosa
delle osservazioni di partenza ha retto e che cosa no, i numeri reali dei due database, la baseline
dell'HTML servito, i rischi e il piano di implementazione delle fasi successive.

---

## 1. Metodo

1. **Lettura integrale del repo**: le tre pagine elenco, le tre pagine di dettaglio, `Layout.astro`,
   `seo.ts`, `middleware.ts`, tutte le `sitemap-*.xml.ts`, `robots.txt`, `supabase.ts`,
   `supabase-bandi.ts`, `types/bandi.ts`, i componenti in `src/components/bandi/`, `README.md`
   (696 righe), più il sorgente di Astro installato e il manifest compilato in `dist/server/` per
   la parte di routing.
2. **Introspezione dei due database in sola lettura**, via PostgREST con le chiavi anon.
   Nessuna scrittura, nessuna migrazione. Lo schema è stato ricavato campionando le righe, non dai
   file in `backend/sql/` (che non sono fonte di verità).
3. **Baseline dell'HTML servito** da produzione (`https://edunews24.it`), cioè esattamente quello
   che vede Googlebot: title, description, canonical, robots, link di paginazione, JSON-LD,
   struttura degli heading, comportamento di `?page=N`, contenuto e conteggi delle sitemap.

### Nota sulle credenziali

Il `.env` locale conteneva **solo** `WEB_BOT_AUTH_PRIVATE_KEY`: le quattro variabili Supabase non
c'erano, e la build presente in `dist/` era stata prodotta con valori fittizi (`dummy….supabase.co`).
L'introspezione è stata quindi fatta con le chiavi anon **già pubbliche nell'HTML di produzione**
(lo script inline delle tre pagine le passa al browser per forza di cose — è il problema P5 osservato
dall'interno). Successivamente sono state aggiunte al `.env` locale `PUBLIC_SUPABASE_URL` e
`PUBLIC_SUPABASE_ANON_KEY`; **mancano ancora `PUBLIC_SUPABASE_BANDI_URL` e
`PUBLIC_SUPABASE_BANDI_ANON_KEY`**, senza le quali `/bandi`, `/bandi/[slug]` e `sitemap-bandi.xml`
non sono verificabili in locale.

---

## 2. Verifica delle affermazioni di partenza

| # | Affermazione | Esito | Evidenza |
|---|---|---|---|
| 1 | Le tre pagine fanno la propria query nel frontmatter con `PAGE_SIZE = 20` e `.range(0, 19)` | **Confermata** | `interpelli.astro:40,47` · `selezione-personale.astro:12,34` · `bandi.astro:21,65` |
| 2 | Ignorano `Astro.url.searchParams` | **Confermata** | Nessuna occorrenza nei tre frontmatter; le uniche `searchParams` sono su `URL` di PostgREST lato client (`interpelli.astro:274`, `selezione-personale.astro:351`, `bandi.astro:750`) |
| 3 | Uno `<script is:inline define:vars>` interroga PostgREST dal browser e ricostruisce le card con `innerHTML` | **Confermata** | `interpelli.astro:271,359-374` · `selezione-personale.astro:348,440-470` · `bandi.astro:466,831-852` |
| 4 | Il markup della card esiste due volte | **Confermata** | SSR `interpelli.astro:188-244` vs stringa `:346-376`; `selezione-personale.astro:218-321` vs `:412-472`; `bandi.astro:378-440` vs `:827-854` |
| 5 | P6a: la stringa `/selezione-personale/${item.slug}` finisce nell'HTML | **Confermata, ma da riqualificare** | `selezione-personale.astro:441`. È dentro `<script>`, **non** è un `href` del documento: il template SSR (`:219`) è corretto. Nell'HTML servito compare 1 volta sola. Sparisce comunque con la rimozione del renderer client |
| 6 | La paginazione è `<nav id="pagination">` con due `<button>`, nessun `<a>` | **Confermata** | `interpelli.astro:252-266` · `selezione-personale.astro:329-343` · `bandi.astro:447-461` |
| 7 | `Layout.astro` calcola il canonical scartando la query string | **Confermata** | `Layout.astro:43-45` usa `Astro.url.pathname`; emesso a `:67`. `/interpelli?page=2` → canonical `https://edunews24.it/interpelli` |
| 8 | Il layout accetta `title, description, canonicalUrl, keywords, image, robots` e ha `<slot name="head" />` | **Confermata** | `Layout.astro:6-18` (più `ogType, author, publishedTime, modifiedTime, section`), slot a `:119` |
| 9 | `sitemap-selezione-personale.xml.ts` fa una sola query senza loop → troncata a 1000 | **Confermata** | `sitemap-selezione-personale.xml.ts:14-18`: nessun `.range()`. In produzione la sitemap ha esattamente 1000 `<loc>` contro 12.441 attesi |
| 10 | `sitemap-interpelli.xml.ts` e `sitemap-bandi.xml.ts` hanno il loop a blocchi di 1000 | **Confermata** | `sitemap-interpelli.xml.ts:31-57` · `sitemap-bandi.xml.ts:12-38` |
| 11 | `sitemap-interpelli.xml.ts` NON filtra `link_type='single'` mentre la lista sì | **Confermata** | Sitemap `:37-41` senza `.eq()`; lista `interpelli.astro:46,47`. In produzione: 1152 `<loc>` contro 1051 righe `single` |
| 12 | La sitemap include URL di interpelli "list" che il dettaglio potrebbe non risolvere | **Smentita nella conseguenza** | Il dettaglio **non filtra affatto** (`interpelli/[slug].astro:57-60`), quindi quegli URL rispondono 200 e producono anche un `JobPosting`. Sono pagine orfane, non URL rotti |
| 13 | `sitemap-index.xml.ts` è statico con `lastmod = oggi` | **Confermata** | `sitemap-index.xml.ts:26,33-61`: `getTodayDateWithItalianTimezone()` per tutte e 8 le voci |
| 14 | `sitemap-pagine.xml.ts` include `/bandi` ma non `/interpelli` né `/selezione-personale` | **Confermata a metà** | `sitemap-pagine.xml.ts:15` ha `/bandi`; ma `/interpelli` e `/selezione-personale` **ci sono già** in `sitemap-categorie.xml.ts:12,18`. Non mancano dal sito: sono in un altro file |
| 15 | `src/lib/seo.ts` esporta breadcrumb / itemList / faq e `bandi.astro` le usa già | **Confermata** | `seo.ts:142,192,219`; usi in `bandi.astro:162-176`. `/interpelli` e `/selezione-personale` non emettono alcun JSON-LD |
| 16 | Lo slug interpelli non è a DB ed è ricalcolato da `generateInterpelloSlug()` duplicata | **Confermata, sono 4 copie** | `interpelli.astro:22-36` · `interpelli/[slug].astro:28-42` · `sitemap-interpelli.xml.ts:13-27` · `backend/app/interpelli.py:46-59`. In più una quinta copia client-side (`interpelli.astro:322-325`) |
| 17 | Selezione personale: `status='completed'`, array `sedi/categorie/settori`, `slug` a DB | **Confermata** | `selezione-personale.astro:27,32`; `types/bandi.ts:13-15,28` |
| 18 | Bandi: `loadCatalogo()` con regioni/settori/programmi/…, junction per regioni-settori-beneficiari, FK per programma e tipologia | **Confermata** | `supabase-bandi.ts:160-191`, junction `:209-214` (`bando_regioni`, `bando_settori`, `bando_beneficiari`, `bando_codici_ateco`) |
| 19 | Un URL piatto come `/interpelli/marche` sarebbe catturato da `interpelli/[slug].astro` | **Confermata per 2 segmenti, non per 3** | Un segmento dinamico compila a `([^/]+?)`, che non attraversa lo slash: `/interpelli/regione/marche` (3 segmenti) oggi è un **404 pulito**. Il problema è l'hub a 2 segmenti `/interpelli/regione` |
| 20 | Il middleware non dovrebbe interferire con `?page=` | **Confermata** | `middleware.ts` legge solo `url.pathname` (`:13,14,21,33,42`); `url.search` non compare mai. Il ramo Markdown (`:51-64`) scatta solo con `Accept: text/markdown` |
| 21 | L'immagine senza `alt` è il pixel Meta in `<noscript>` | **Confermata** | `Layout.astro:161-162`, unica `<img>` del layout. L'`<img>` di `Header.astro:247` ha `alt` ed è resa solo in home |
| 22 | `src/components/bandi/BandoCard.astro` esiste ma nessuno lo importa | **Confermata, ed è peggio** | Tutti e 5 i file di `src/components/bandi/` sono codice morto. `BandoCard.astro` diverge dal markup vivo: palette `slate-*`, `<a>` solo sul titolo, **manca la classe hook `bando-item`**, badge da `computeScadenzaStato` invece di `effectiveStatoBando` |
| 23 | Non esiste `CLAUDE.md` | **Confermata** (creato ora) | — |
| 24 | `src/pages/[category].astro` è la pagina elenco "SEO-completa" da cui riusare i pattern | **Confermata in parte** | Ha davvero paginazione server-side con `<a href>` reali (`:13-18, 173-221, 535-600`), ma il canonical punta sempre a pagina 1 (`:296`) e **la guardia out-of-range è rotta** (vedi §5, R3) |

---

## 3. I numeri reali (introspezione del 3 settembre 2026)

### 3.1 Interpelli — DB principale, tabella `interpelli`

Colonne reali: `id, interpello_name, interpello_date, interpello_description, interpello_link,
city_name, article_content, article_title, article_subtitle, status, classe_concorso,
source_daily_link, link_type, interpello_citta, interpello_provincia, interpello_regione`.
**Non esistono `created_at`/`updated_at`**: l'unico segnale temporale è `interpello_date`.

- Totale **1152**; `link_type`: `single` **1051**, `list` **101**.
- Fra i `single`, `status`: `completed` **1046**, `error` **5**. La lista **non filtra `status`**.
- `interpello_date`: da `2026-02-20` a `2026-09-02`.

Distribuzione `interpello_regione` (solo `single`):

```
Lazio 296 · Lombardia 124 · Emilia-Romagna 79 · Toscana 65 · Puglia 64 · Sicilia 56
Veneto 56 · Abruzzo 55 · <NULL> 52 · Campania 33 · Marche 32 · Liguria 32
Sardegna 31 · Calabria 30 · Friuli Venezia Giulia 13 · Piemonte 8 · Umbria 8
Molise 7 · Basilicata 6 · "Emilia Romagna" 4  (variante senza trattino)
```

**Mancano del tutto Trentino-Alto Adige e Valle d'Aosta.** Fra le righe `list` compaiono valori
sporchi da scraping (`Interpellilazio`, `Interpelliveneto`, …) che non entrano mai nella lista.

- `interpello_provincia`: 99 valori distinti, 68 NULL. Roma 274, L'Aquila 37, poi coda sotto 26.
- `classe_concorso`: 94 valori distinti, 248 NULL. `EEEE` 169, `ADEE` 166, `AAAA` 85, `ADAA` 59,
  `DSGA` 26, `ADMM` 21, `A027` 17, `A041` 15, `AD0J` 15, `A042` 13, `KB` 12, `A028` 11.
  **36 valori hanno ≥3 occorrenze.** Presenti valori non-classe: `Sostegno`, `ATA`, `PER`, `IC`, `KB`.
- **Duplicati (P6b)**: 16 `article_title` ripetuti fra i `single`, 27 righe in eccesso. I record sono
  **realmente distinti**: `interpello_link`, protocolli e sottotitoli diversi. Lo slug termina con
  l'`id`, quindi sono URL distinti con contenuto quasi identico, non lo stesso URL due volte.
  `interpello_link` è quasi-unico (2 duplicati su 1051).

### 3.2 Selezione personale — DB principale, tabella `selezione_personale`

- Totale **13.291**; `status='completed'` **12.441**.
- `slug` duplicati: **2**. `codice`: UNIQUE, 0 duplicati.
- `sedi` (array, media 1,92 elementi, 129 valori distinti): la struttura reale è
  **`[Regione, Provincia]`** nella grande maggioranza — `["Lombardia","Milano"]`,
  `["Emilia Romagna","Piacenza"]`, `["Marche"]`, `["Nazionale"]`. Su 1000 righe recenti, **980**
  contengono una regione canonica, 20 sono solo `["Nazionale"]`; lunghezze `{1:178, 2:794, 3:6, 4:7, 6:10, 7:3}`.
  **Tutte e 20 le regioni sono presenti**: Lombardia 2391, Veneto 1392, "Emilia Romagna" 1079 (senza
  trattino), Piemonte 819, Lazio 788, Campania 788, Toscana 784, Puglia 702, Calabria 602, Sicilia 567,
  Sardegna 566, Marche 550, Liguria 450, Abruzzo 395, Friuli Venezia Giulia 331, Umbria 297,
  Basilicata 209, Molise 152, "Trentino Alto Adige" 65, "Valle d'Aosta" 8. In più `Nazionale` 502 e le province.
- `categorie` (8 valori): `Concorso` 8159 · `Avvisi di mobilità` 3050 ·
  `Selezione Professionisti ed Esperti` 1098 · `"Avviso OIV "` 92 **(spazio finale)** ·
  `"Bando Apprendistato "` 16 **(spazio finale)** · `Concorsi DFP – Formez Pa` 14 ·
  `Scelta PA/sede` 7 · `Procedure Straordinarie` 7.
- `settori` (31 valori): **vuoto su 9738 righe (78%)**. Amministrazione 1560, Edilizia e urbanistica 309, …
- **Scadenze**: `data_scadenza` passata su **11.222 righe (90,2%)**; ≥ oggi 1219, di cui 36 con date
  implausibili (massimo reale `5026-06-22`). `calculated_status` vale `OPEN` e `status_label` `Aperto`
  su **tutte e 12.441**: le due colonne sono scorrelate dalla data e inutilizzabili.

### 3.3 Bandi — DB bandi, tabella `bando` (RLS anon)

- **1972** righe visibili, tutte `stato_processing='completed'`.
- `stato_bando`: `aperto` 1388, `chiuso` 397, `in apertura prossimamente` 187.
- **`data_pubblicazione` è NULL su 1823 righe (92,4%)** — è la causa di B1 (§5).
- `slug`: 0 null, 0 duplicati. `hash_bando`: unico per riga. **`canonical_key`: NULL su tutte le 1972 righe.**
  `link_bando`: 104 null, 19 valori duplicati.
- Duplicati: 19 titoli ripetuti, con slug diversi (suffisso `-2` già applicato dalla pipeline) e in
  parte lo stesso `link_bando`.
- Bandi per regione (junction, solo visibili): Piemonte 518 · Lombardia 479 · Emilia-Romagna 443 ·
  Lazio 440 · Toscana 392 · Puglia 381 · Veneto 377 · Sardegna 376 · Valle d'Aosta 372 · Calabria 360 ·
  Liguria 351 · Friuli-Venezia Giulia 350 · Marche 343 · Sicilia 337 · Abruzzo 333 · Basilicata 331 ·
  Campania 327 · Umbria 324 · Trentino-Alto Adige 309 · Molise 304. **Tutte e 20 ampiamente sopra soglia.**
- Programmi: `programma_id` NULL su **810** bandi; 25 programmi con ≥3 bandi.
  `FSE+ - Fondo Sociale Europeo +` 292 e `FSE+` 59 sono **due righe distinte del catalogo**.
  FESR 159, AGRIP 151, Horizon Europe 82, PNRR 73, CREA 63, LIFE 48.
- Settori: 89 su 90 hanno ≥3 bandi. Tipologie: regionali/locali 1443, nazionali/PNRR 211,
  fondazioni 166, europei 151, internazionali 1.
- Cataloghi: **solo `regioni` ha la colonna `slug` popolata** (20 su 20, già nella forma pulita
  `trentino-alto-adige`, `valle-d-aosta`). `programmi`, `settori`, `tipologie_bando`,
  `modalita_erogazione` hanno `slug` NULL su tutte le righe.

### 3.4 Sintassi PostgREST verificata lato server

```
bando?select=id,bando_regioni!inner(regione_id)&bando_regioni.regione_id=eq.13   -> 381    OK
bando?select=id,regioni!inner(slug)&regioni.slug=eq.marche                       -> 400 PGRST200 (nessuna FK diretta)
selezione_personale?status=eq.completed&sedi=cs.{Lombardia}                      -> 2391   OK
selezione_personale?status=eq.completed&sedi=cs.{"Valle d'Aosta"}                -> 8      OK
interpelli?link_type=eq.single&classe_concorso=eq.A028                           -> 11     OK
interpelli?link_type=eq.single&interpello_regione=ilike.emilia*                  -> 83     OK (unisce le due varianti)
```

---

## 4. Baseline dell'HTML servito (produzione, 3 settembre 2026)

| | `/interpelli` | `/selezione-personale` | `/bandi` |
|---|---|---|---|
| Title | `Interpelli Scuola - EduNews24` | `Selezione Personale - EduNews24` | `Bandi e finanziamenti pubblici - EduNews24` |
| Description | "Trova tutti gli interpelli per la scuola divisi per regione, provincia e classe di concorso…" | "…della pubblica amministrazione e delle **migliori aziende private**" (la pagina contiene solo PA) | "Trova bandi di finanziamento europei, nazionali e regionali. Filtra per regione, settore, beneficiari…" |
| Canonical | `/interpelli` | `/selezione-personale` | `/bandi` |
| robots | `index, follow` | `index, follow` | `index, follow` |
| Link `?page=` | **0** | **0** | **0** |
| `rel=prev/next` | 0 | 0 | 0 |
| JSON-LD | solo `NewsMediaOrganization` | solo `NewsMediaOrganization` | `NewsMediaOrganization` + `BreadcrumbList` + `ItemList` + 22 `ListItem` |
| H1 / H2 / H3 | 1 / 21 / 0 | 1 / 21 / 0 | 1 / 23 / **4** |
| `<img>` senza alt | 1 (pixel Meta) | 1 | 1 |
| `${item.slug}` nell'HTML | 0 | **1** | 0 |
| Byte HTML | 113 KB | 157 KB | 178 KB |
| TTFB (3 misure) | 0,72 / 0,71 / 1,13 s | 0,78 / 0,83 / 0,95 s | 0,70 / 0,54 / 0,66 s |

Heading di interfaccia marcati come titoli, solo su `/bandi`: `Filtri` (h2, `bandi.astro:239`),
`Categorie` (h3, `:273`), `Tipologia` (h3, `:304`), `Stato bando` (h3, `:314`),
`Importo e scadenza` (h3, `:327`), più l'h2 della CTA esperto (`BandiExpertCta.astro:39`).

### Comportamento delle query string

```
/interpelli?page=2       200, contenuto identico a pagina 1, canonical /interpelli, title invariato
/interpelli?page=9999    200, idem
/bandi?page=2            200, idem
/interpelli?regione=Marche  200, nessun filtro applicato, canonical /interpelli
```

### Rotte e sitemap

```
/interpelli/regione/marche          404   (spazio a 3 segmenti libero)
/interpelli/regione                 200   "Interpello non Trovato"  <- soft 404
/selezione-personale/regione        200   "Bando non Trovato"       <- soft 404
/bandi/regione                      404   (corretto)
/interpelli/slug-inesistente        200   "Interpello non Trovato"  <- soft 404
/bandi/slug-inesistente             404   (corretto)

sitemap-index.xml                   8 loc,  lastmod = oggi per tutte
sitemap-interpelli.xml           1152 loc,  di cui 177 con slug "visualizza-interpelli-*"
sitemap-selezione-personale.xml  1000 loc,  troncata (attesi 12.441)
sitemap-bandi.xml                1972 loc
sitemap-pagine.xml                  4 loc   (privacy, chi-siamo, collaborazione, bandi)
```

Tutti i file sono well-formed (`xmllint --noout`) e senza `<loc>` duplicati.

---

## 5. Rischi individuati

### Bloccanti, già in produzione

**B1 — `/bandi` ha una paginazione non deterministica.** `data_pubblicazione` è NULL su 1823 righe
su 1972 e la lista ordina senza tiebreak (`bandi.astro:64`). Misurato su 40 pagine consecutive
(800 slot): **714 id distinti, 86 righe duplicate (10,8%)**; pagina 1 e pagina 2 condividono **5
schede su 20**. La sitemap non ne soffre perché ha `.order('id')` (`sitemap-bandi.xml.ts:23`).
Con il tiebreak: **800 id distinti su 800, 0 duplicati**. Rendere `?page=N` crawlabile senza
correggere questo significherebbe pubblicare pagine che si contraddicono a ogni ricrawl.

**B2 — 152 URL già dichiarati in sitemap rispondono 200 "Interpello non Trovato".**
`interpelli/[slug].astro:57-60` fa `select('*')` senza `.range()`: PostgREST tronca a 1000 righe su
1152, e lo slug viene cercato in memoria (`:75`). Le 152 righe più vecchie sono irraggiungibili, e il
ramo "non trovato" (`:251-257`) risponde **HTTP 200** con canonical su sé stesso e `index, follow`.
Verificato sui `loc` #1100 e #1150 della sitemap. Il numero cresce a ogni nuovo interpello.

**B3 — il `noindex` non funziona.** `Layout.astro:62-63` emette `<meta name="googlebot">` e
`bingbot` con `index, follow` hardcoded, mentre `:61` parametrizza `robots`. In presenza di una
direttiva specifica per user-agent, Google segue quella e ignora la generica. `/scuola?secondary_filter=test`
serve oggi `robots: noindex, follow` insieme a `googlebot: index, follow`: la regola noindex di
`[category].astro:325` non ha mai avuto effetto, e non ne avrebbe la regola prevista per le liste filtrate.

### Alti

- **R1 — Selezione personale, scaduti.** 90,2% del corpus ha scadenza passata ma badge "Aperto", e
  la scheda di dettaglio emette un `JobPosting` con `validThrough` nel passato
  (`selezione-personale/[slug].astro:125`). Portare tutti i 12.441 URL in sitemap significa
  dichiarare ~11.200 annunci di lavoro scaduti. Decisione presa: **non scaduti in cima, tutti
  indicizzati**; il `noindex` + omissione del `JobPosting` sulle schede scadute resta una proposta
  separata da approvare.
- **R2 — Sovrapposizione dei contenuti su `/bandi/regione/*`.** Ogni bando è agganciato in media a
  ~3,6 regioni e i bandi nazionali/europei a tutte e 20: ordinando per data, le prime schede di
  `/bandi/regione/molise` e `/bandi/regione/valle-d-aosta` saranno in larga parte le stesse.
  Mitigazione: intro con numeri realmente diversi per regione e blocco incrociato regione×settore;
  leva di riserva documentata in config (restringere ai soli `Bandi regionali / locali`, 1443 righe).
- **R3 — La guardia out-of-range di `[category].astro:173-176` è rotta.** Quando PostgREST risponde
  `PGRST103` il `count` resta `null`, `totalPages` collassa a 1 e la condizione non scatta:
  `/scuola?page=99999` risponde 200. Si riusano `getPaginationItems` e il markup `<nav>` di quel
  file, **non** la sua logica di guardia.
- **R4 — `Vary: Accept` assente sul ramo HTML del middleware.** `middleware.ts:51-64` imposta
  `Vary: Accept` solo sulla risposta Markdown. Oggi è innocuo (`cf-cache-status: DYNAMIC`), ma
  diventa pericoloso appena si introduce un `Cache-Control` sulle liste: Cloudflare potrebbe servire
  Markdown a Googlebot. Va sistemato **prima** di qualsiasi intervento sulla cache.

### Medi

- `trailingSlash` non configurato (default `ignore`): `/interpelli` e `/interpelli/` rispondono
  entrambe 200 e `Layout.astro:43-45` replica lo slash ricevuto nel canonical.
- Tutti i `BreadcrumbList` del sito usano `"id"` invece di `"@id"` (`seo.ts:152,161,176`): l'`item`
  è privo di identificatore valido su ~5.000 URL.
- `interpelli.astro:53-74` e `selezione-personale.astro:53-56` calcolano le faccette con una select
  senza `.range()`: troncate a 1000 righe (per selezione personale è l'8% del corpus), a ogni pageview.
- Interpelli e selezione personale interpolano HTML non escapato nel renderer client
  (`interpelli.astro:364,372`; `selezione-personale.astro:445,456-465`); solo `bandi.astro:475-479`
  ha `escapeHtml`. La fonte è testo generato da LLM su pagine scrapate.
- Le tre pagine condividono 13 id DOM (`#search-filter`, `#pagination`, `#hero-count`, …) e
  `selezione-personale` e `bandi` usano entrambe `id="bandi-list"`: da tenere presente estraendo
  componenti condivisi.
- `src/pages/api/interpelli/refresh.ts:2` importa `../../../types/interpelli`, file che non esiste,
  e scrive su `src/data/interpelli.json`, anch'esso inesistente. Endpoint morto.

---

## 6. Piano di implementazione (fasi 1-6)

Il piano approvato in forma estesa è in `~/.claude/plans/sei-un-senior-engineer-gleaming-crescent.md`.
Sintesi operativa.

### 6.1 Decisioni prese, e alternative scartate

| Decisione | Alternativa scartata |
|---|---|
| Il JS fa `fetch` di una rotta frammento `/api/lista/<sezione>.astro` che importa gli **stessi** componenti della pagina | Fetch della pagina intera + `DOMParser`: costerebbe 3 query Supabase in più (Header + ticker) a ogni battuta. Endpoint JSON + template JS: reintrodurrebbe la doppia copia del markup |
| Filtro via query string non promosso a pagina statica → `noindex, follow` + canonical **su sé stessa**; una sola dimensione pubblicata → **302** verso l'URL statico | Canonical verso la pagina base come da prompt: `noindex` + canonical cross-URL fa propagare il noindex al bersaglio |
| `?page=1` e parametri noti vuoti → **301**; parametri sconosciuti (`utm_*`, `fbclid`) ignorati senza redirect | Redirect anche sugli sconosciuti: distruggerebbe i link di tracciamento |
| `page` oltre l'ultima → **404** + `X-Robots-Tag: noindex` | Il 302 di `[category].astro:174`, che oltretutto non scatta mai (R3) |
| Sitemap: indici per sezione, file da 1000 URL, monolitiche → **301** verso `/sitemap-index.xml` | Servire l'indice all'URL vecchio: `sitemap-index.xml` lo elenca già, e un `<sitemapindex>` non può annidarne un altro |
| `/bandi` spostata in `sitemap-categorie.xml` accanto alle altre due landing | Aggiungere `/interpelli` e `/selezione-personale` a `sitemap-pagine.xml`: creerebbe `<loc>` duplicati su due file |
| `slugifica()` nuova e accent-safe + registro statico delle 20 regioni con le varianti di grafia | `slugify` di `utils.ts:2`: distrugge accenti e apostrofi |
| Nessuna deduplica su interpelli; sui bandi solo su `link_bando` non-NULL | Deduplica per titolo: cancellerebbe documenti realmente distinti |
| `BandoCard.astro` riscritto dal markup vivo di `bandi.astro:378-440` | Riusare il componente esistente: diverge e non ha la classe hook `bando-item` |

### 6.2 Schema URL

```
/{sezione}                                lista base            (esistente)
/{sezione}/{dimensione}                   hub                   (nuovo, 2 segmenti, file statico)
/{sezione}/{dimensione}/{valore}          pagina filtro         (nuovo, 3 segmenti)
/{sezione}/{dimensione}/{valore}?page=N   pagina N              (pagina 1 senza query)
/{sezione}/{slug-record}                  dettaglio             (esistente, invariato)

interpelli           regione · provincia · classe
selezione-personale  regione · categoria          (settore disabilitata: 78% delle righe vuote)
bandi                regione · settore · programma · tipologia
```

Rotte: `src/pages/{sezione}/[dimensione]/[valore].astro` + 9 hub `.../{dimensione}/index.astro`.
`[dimensione]/index.astro` è escluso perché collide con `{sezione}/[slug].astro`.

### 6.3 File da creare

```
src/lib/slug.ts · src/lib/regioni.ts · src/lib/corpus.ts · src/lib/sitemap.ts
src/lib/liste/{parametri,paginazione,seo-lista,postgrest,risposte}.ts
src/lib/liste/{interpelli,selezione-personale,bandi}.ts
src/config/pagine-filtro.ts
src/components/liste/{Paginazione,CardInterpello,CardSelezione,CardBando,Lista*}.astro
src/components/filtro/{PaginaFiltro,Sorelle,HubDimensione}.astro
src/pages/api/lista/{interpelli,selezione-personale,bandi}.astro
src/pages/{sezione}/[dimensione]/[valore].astro  ×3
src/pages/{sezione}/{dimensione}/index.astro     ×9
src/pages/sitemap-{sezione}/[pagina].xml.ts      ×3
src/pages/sitemap-pagine-filtro.xml.ts
src/scripts/lista.ts
```

### 6.4 File da modificare

`interpelli.astro`, `selezione-personale.astro`, `bandi.astro` (frontmatter SSR, form GET,
paginazione a link, blocchi di linking, rimozione del `define:vars` con le chiavi) ·
`Layout.astro` (meta bot derivati da `robots`, `alt=""` sul pixel) · `seo.ts` (`@id`, `WebPage`,
`voceExtra`, `posizioneIniziale`) · le tre `sitemap-*.xml.ts` di sezione ·
`sitemap-index.xml.ts`, `sitemap-pagine.xml.ts`, `sitemap-categorie.xml.ts` ·
`public/robots.txt` · `src/lib/api-catalog.ts:24` · `supabase-bandi.ts` (`slug` nel catalogo regioni) ·
`BandiExpertCta.astro:39` · le tre pagine di dettaglio (query mirata, 404 reale, link interni).

### 6.5 Configurazione delle pagine filtro

`src/config/pagine-filtro.ts` è l'unico punto da cui si regola cosa esiste: soglia per sezione
(3 su interpelli, 5 su bandi e selezione), dimensioni abilitate, `esclusi`, `alias` (valori DB
diversi → stesso URL), `slugAlias` (slug vecchio → 301), `etichette`, override di title/description/H1.

Bilancio iniziale: interpelli 18 regioni + ~35 classi + ~45 province; selezione 20 regioni +
8 categorie; bandi 20 regioni + ~89 settori + 25 programmi + 4 tipologie. **~265 pagine + 9 hub.**
Casi speciali già codificati: `FSE+` e `FSE+ - Fondo Sociale Europeo +` confluiscono in un solo URL
(351 bandi); categorie con spazio finale usate esatte nella query e ripulite nello slug;
`PER`/`IC`/`KB` esclusi come rumore di scraping; `Nazionale` escluso dalle sedi.
