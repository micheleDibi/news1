# Report dell'intervento SEO sulle pagine elenco

Data: **3 settembre 2026**. Riferimenti: `docs/analisi-seo-elenchi.md` (Fase 0) e il piano approvato
in `~/.claude/plans/sei-un-senior-engineer-gleaming-crescent.md`.

`npx astro build` esce 0. `npm run build` fallisce sul **prebuild**, che cerca
`src/pages/api/tts/google-credentials.json`, file gitignorato e assente da questa working copy:
è un difetto preesistente, indipendente da queste modifiche. `npx astro check` **non è
configurato** nel repo (richiederebbe `@astrojs/check` e `typescript`, due dipendenze nuove che non
ho installato): il controllo dei tipi resta quello del build.

---

## 1. Prima e dopo, misurato

Baseline: HTML servito da `https://edunews24.it` il 31/08-03/09. Dopo: server di produzione locale
(`node dist/server/entry.mjs`) sugli stessi dati.

| | `/interpelli` | `/selezione-personale` | `/bandi` |
|---|---|---|---|
| Link `?page=N` crawlabili | 0 → **5** | 0 → **5** | 0 → **5** |
| `?page=2` | contenuto identico a p.1 → **20 schede diverse** | idem | idem |
| canonical di `?page=2` | `/interpelli` → **`/interpelli?page=2`** | idem | idem |
| title di `?page=2` | invariato → **"pagina 2 di 53"** | **"pagina 2 di 623"** | **"pagina 2 di 99"** |
| `?page=9999` | 200 → **404** | 200 → **404** | 200 → **404** |
| `?page=1` | 200 → **301** all'URL pulito | idem | idem |
| JSON-LD | solo `NewsMediaOrganization` → **+ BreadcrumbList + ItemList + FAQPage** | **+ BreadcrumbList + ItemList** | Breadcrumb/ItemList ora con `@id` valido e posizioni assolute |
| h1/h2/h3 | 1/21/0 → 1/25/4 | 1/21/0 → 1/23/0 | 1/23/**4** → 1/25/**0** |
| `<img>` senza alt | 1 → **0** | 1 → **0** | 1 → **0** |
| `${item.slug}` nell'HTML | 0 | **1 → 0** | 0 |
| chiave anon Supabase nell'HTML | presente → **assente** | presente → **assente** | presente → **assente** |
| peso HTML | 113 → 134 KB | 157 → 168 KB | 178 → 194 KB |
| TTFB (produzione locale) | — | — | 0,10-0,20 s su tutte e tre |

Sitemap: **interpelli 1046** (era 1152, con dentro 101 record `link_type='list'` e 5 in errore),
**selezione personale 12.441** (era **1000**, troncata), **bandi 1972**. Ogni conteggio coincide
esattamente con il conteggio a DB e con il numero mostrato nell'hero. Tutti i file `xmllint`-validi.

Pagine nuove: **295 URL** (286 pagine filtro + 9 indici di dimensione), tutte in
`sitemap-pagine-filtro.xml`; su un campione casuale di 25, 25 rispondono 200.

Sweep di regressione finale: **32 casi su 32** con lo status atteso.

**Un bug trovato collaudando nel browser, e corretto.** Con un filtro attivo il link di paginazione
produceva `?regione=marche?page=2` — due punti interrogativi — e la lista si svuotava: `hrefPagina`
in `src/lib/paginazione.ts` appendeva sempre `?page=`, cosa corretta per le pagine filtro (dove il
percorso non ha query) ma sbagliata per le pagine elenco, dove `base` porta già i filtri. I test con
`curl` non l'avevano intercettato perché avevo provato `?page=N` solo senza filtri. Ora il parametro
si aggiunge con `&` quando serve, ed è verificato su sette combinazioni: link, status, numero di
schede e canonical corretti in tutte.

---

## 2. Tre bug che erano già in produzione

**Paginazione dei bandi non deterministica.** `data_pubblicazione` è NULL su 1823 righe su 1972 e la
lista ordinava senza tiebreak: su 40 pagine consecutive, 800 slot restituivano **714 id distinti** e
pagina 1 e 2 condividevano 5 schede su 20. Con `.order('id')` come secondo criterio: 800 su 800.
Senza questa correzione, ogni URL `?page=N` pubblicato sarebbe stato un danno netto.

**152 URL della sitemap rispondevano 200 con "Interpello non Trovato".**
`interpelli/[slug].astro` caricava l'intera tabella con `select('*')` senza `.range()`: PostgREST
tronca a 1000 righe su 1152, e lo slug veniva cercato in memoria. Ora la scheda si recupera con una
query mirata sull'id, che lo slug contiene già in coda; se lo slug canonico è cambiato si fa 301.
Effetto collaterale: ogni visualizzazione di scheda scaricava ~8 MB di JSON, ora ne scarica uno.

**Il `noindex` non funzionava.** `Layout.astro` emetteva `<meta name="googlebot">` e `bingbot` con
`index, follow` hardcoded mentre parametrizzava solo `robots`: per Google la direttiva specifica
prevale su quella generica. `/scuola?secondary_filter=x` serviva `robots: noindex` insieme a
`googlebot: index`. Ora i tre meta derivano dalla stessa fonte; senza la prop l'output è invariato.

---

## 3. File creati

### Configurazione e dominio
| File | Perché |
|---|---|
| `src/config/pagine-filtro.ts` | **L'unico punto da cui regoli quali pagine filtro esistono**: soglie per sezione, dimensioni abilitate, esclusioni, alias, etichette |
| `src/lib/regioni.ts` | Registro delle 20 regioni: le tre fonti scrivono gli stessi nomi in modo diverso (`Emilia-Romagna`/`Emilia Romagna`, `Valle d'Aosta/Vallée d'Aoste`) |
| `src/lib/slug.ts` | Slug accent-safe: `slugify` di `utils.ts` fa `città`→`citt` e `Valle d'Aosta`→`valle daosta` |
| `src/lib/corpus.ts` | Aggregazione delle faccette con cache TTL 15' e stale-while-revalidate; sostituisce le due `loadFilterOptions()` che ricalcolavano tutto a ogni pageview troncando a 1000 righe |
| `src/lib/pagine-filtro.ts` | Risoluzione URL→pagina, soglie, sorelle, incroci, elenco per la sitemap |
| `src/lib/seo-filtro.ts` | Title, description, H1 e introduzioni delle pagine filtro, generati solo da numeri reali |
| `src/lib/paginazione.ts` | Numeri con ellissi (portati da `[category].astro`), lettura di `?page=`, 404 con `X-Robots-Tag` |
| `src/lib/sitemap.ts` | Primitive XML condivise, incluso un `lastmod` che non lancia mai |
| `src/lib/liste/parametri.ts` | Stato della lista nell'URL: lettura, validazione, serializzazione in ordine fisso, canonical, regola noindex |
| `src/lib/liste/{interpelli,selezione-personale,bandi}.ts` | Query server-side per sezione, con le colonne necessarie invece di `select('*')` |
| `src/lib/liste/postgrest.ts` | Sanificazione del termine di ricerca, che prima veniva interpolato grezzo dentro `or=(...)` |
| `src/lib/liste/formato.ts` | Formattazione date e importi, prima triplicata nelle pagine |
| `src/lib/liste/testi.ts` | Introduzioni e FAQ: un solo array per il testo visibile e per il JSON-LD |

### Componenti
| File | Perché |
|---|---|
| `src/components/liste/Card{Interpello,Selezione,Bando}.astro` | Un solo template di card per sezione, usato da pagina, pagine filtro e frammento |
| `src/components/liste/Lista{Interpelli,Selezione,Bandi}.astro` | Contenitore della lista, condiviso fra pagina e frammento |
| `src/components/liste/IntroSezione.astro` | Testo introduttivo, completo su pagina 1 e ridotto a una riga oltre |
| `src/components/liste/FaqInterpelli.astro` | FAQ visibili, dallo stesso array del JSON-LD |
| `src/components/filtro/PaginaFiltro.astro` | Guscio delle pagine filtro: hero, breadcrumb, intro, elenco, paginazione, linking |
| `src/components/filtro/HubDimensione.astro` | Pagine indice di dimensione |
| `src/components/filtro/PaginazioneLinks.astro` | Paginazione con `<a href>` reali |
| `src/components/filtro/Sorelle.astro` | Blocchi "Esplora per…" |

### Rotte
| File | Perché |
|---|---|
| `src/pages/{sezione}/[dimensione]/[valore].astro` (×3) | Le pagine filtro. Tre segmenti: nessuna collisione con `{sezione}/[slug]`, che ne ha due |
| `src/pages/{sezione}/{dimensione}/index.astro` (×9) | Gli indici di dimensione. Chiudono anche il soft-404 di `/interpelli/regione`, che rispondeva 200 |
| `src/pages/api/lista/{sezione}.astro` (×3) | Frammento della lista per il JS, con gli stessi componenti della pagina |
| `src/pages/sitemap-{sezione}/[pagina].xml.ts` (×3) | Sitemap a blocchi da 1000 URL |
| `src/pages/sitemap-pagine-filtro.xml.ts` | Le 295 pagine filtro, calcolate dai dati |
| `src/scripts/lista.ts`, `src/scripts/bandi-filtri.ts` | Miglioramento progressivo: una sola implementazione per tre pagine |

## 4. File modificati

| File | Perché |
|---|---|
| `src/pages/interpelli.astro` | 465→211 righe: stato nell'URL, form GET, paginazione a link, niente più chiavi anon |
| `src/pages/selezione-personale.astro` | 578→197 righe, idem; ordinamento con i non scaduti in cima |
| `src/pages/bandi.astro` | 1059→310 righe, idem; le 290 opzioni delle tendine ora sono checkbox reali |
| `src/pages/interpelli/[slug].astro` | Query mirata invece del caricamento dell'intera tabella; 404 reale; badge → link |
| `src/pages/selezione-personale/[slug].astro` | 404 reale al posto del soft-404; chip categorie → link |
| `src/pages/bandi/[slug].astro` | Tipologia e programma → link verso le pagine filtro |
| `src/layouts/Layout.astro` | `googlebot`/`bingbot` derivati da `robots`; `alt=""` sul pixel Meta |
| `src/lib/seo.ts` | `"id"`→`"@id"` e `Thing`→`WebPage` nei breadcrumb; `voceExtra` e `posizioneIniziale` |
| `src/lib/supabase-bandi.ts` | `slug` aggiunto alla select del catalogo regioni |
| `src/middleware.ts` | Riscaldamento della cache delle faccette al primo hit, senza bloccare la richiesta |
| `src/components/BandiExpertCta.astro` | H2 promozionale declassato a `<p>` con `font-heading` |
| `src/pages/sitemap-{interpelli,selezione-personale,bandi}.xml.ts` | Diventano 301 verso l'indice |
| `src/pages/sitemap-index.xml.ts` | Dinamico, elenca i blocchi con `lastmod` reale invece di "oggi" per tutti |
| `src/pages/sitemap-{pagine,categorie}.xml.ts` | `/bandi` spostata accanto alle altre due landing di sezione |
| `public/robots.txt`, `src/lib/api-catalog.ts` | Allineati alla nuova struttura |

---

## 5. Decisioni prese, e dove si discostano dal mandato

1. **Filtri via query string: `noindex` + canonical su sé stessa**, non verso la pagina base. Un
   `noindex` con canonical che punta altrove fa propagare il noindex al bersaglio: canonicalizzare
   `?q=dsga` verso `/interpelli` rischierebbe di far uscire `/interpelli` dall'indice. L'equivalente
   indicizzabile si raggiunge prima, con un **302** quando è attiva una sola dimensione pubblicata.
2. **301 solo su `?page=1` e sui parametri noti vuoti.** I parametri sconosciuti (`utm_*`, `fbclid`)
   vengono ignorati e non causano redirect: farli sparire romperebbe il tracciamento delle campagne.
3. **Nessuna deduplica sugli interpelli.** I 16 titoli ripetuti sono documenti realmente distinti
   (protocolli, sottotitoli e `interpello_link` diversi) con un titolo boilerplate: deduplicare
   cancellerebbe interpelli veri. Sui bandi la sola chiave sicura sarebbe `link_bando` non-NULL, che
   copre metà dei 19 casi; `canonical_key` è NULL su tutte le 1972 righe. Vedi §7.
4. **Sitemap monolitiche → 301 verso l'indice**, non "stesso contenuto all'URL vecchio": quell'URL è
   elencato dentro `sitemap-index.xml`, e un file indice non può elencarne un altro.
5. **`/interpelli` e `/selezione-personale` NON aggiunte a `sitemap-pagine.xml`**: ci sono già in
   `sitemap-categorie.xml`. Ho spostato lì anche `/bandi`, così le tre landing stanno insieme e
   nessun `<loc>` è dichiarato due volte.
6. **Interpelli: solo le 18 regioni con annunci** (tua decisione). Trentino-Alto Adige e Valle
   d'Aosta compariranno da sole appena superano la soglia.
7. **Title dell'analisi accorciati.** Quelli proposti superavano i 65 caratteri
   ("Interpelli scuola 2026/27: docenti, ATA e DSGA per regione e classe di concorso - EduNews24"
   sono 90). Ho tenuto i termini chiave dentro il limite: `Interpelli scuola: docenti, ATA e DSGA
   per regione` (62) e `Concorsi pubblici e selezione personale PA` (54). **Ho anche omesso
   "2026/27"**: i dati coprono febbraio-settembre 2026, cioè due anni scolastici, e non posso
   affermare che la pagina riguardi solo il 2026/27.
8. **Testo introduttivo sotto la lista, non sotto l'H1.** Centotrenta parole fra intestazione e
   filtri spingerebbero controlli e primi risultati sotto la piega su mobile; per un motore di
   ricerca la posizione nel documento non cambia nulla.
9. **Lista interpelli filtrata anche su `status='completed'`.** Cinque righe in errore, prive di
   articolo, comparivano in lista e nel conteggio. L'hero passa da 1051 a **1046**, che è ora lo
   stesso numero di lista, sitemap e pagine filtro.
10. **Il conteggio hero di `/bandi` ora riflette i filtri.** Prima contava sempre 1972 anche a
    filtri attivi.

---

## 6. Frasi da rileggere e approvare

- **"L'elenco viene aggiornato più volte al giorno"**, su `/interpelli` e `/selezione-personale` e
  nella quarta FAQ. Il codice schedula quattro esecuzioni giornaliere
  (`backend/app/interpelli_sender.py:17`, `backend/app/selezione_personale_sender.py:17`), ma da qui
  non è verificabile quali sender girino davvero in produzione: la formula è volutamente vaga.
- **Su `/bandi` la frase c'è** ("aggiornati ogni giorno" nella description, "aggiornato più volte al
  giorno" nell'introduzione): il sender bandi è confermato attivo in produzione. Ne consegue che
  `README.md:618` ("`edunews-bandi-sender.service` disabilitato in v5") e `README.md:285` sono
  **disallineati dalla realtà** e andrebbero corretti.
- **Le quattro FAQ di `/interpelli`** (`src/lib/liste/testi.ts`): rimandano sempre al testo
  dell'avviso e non affermano nulla di normativo, ma sono testo tuo e vanno riletti.
- **Le tre introduzioni** (125, 115 e 135 parole): descrivono cosa contiene la pagina e rimandano
  alla fonte ufficiale. Nessun numero, nessuna data, nessun riferimento normativo.
- **Etichetta `FSE+ — Fondo Sociale Europeo Plus`** in `src/config/pagine-filtro.ts`: sostituisce il
  nome a catalogo `FSE+ - Fondo Sociale Europeo +`, che a video legge male. Verifica che ti vada.
- **`DSGA — Direttore dei Servizi Generali e Amministrativi`** e **`Personale ATA`** sono le uniche
  due etichette di classe di concorso compilate. Le altre mostrano il codice: non ho inventato
  denominazioni ministeriali. Se vuoi completarle, il posto è `etichette` nel config.

---

## 7. Fuori scope: cosa resta da fare altrove

**Deduplica a monte (backend).**
- *Interpelli* — il problema non sono record duplicati ma il **generatore di titoli**, che produce
  boilerplate: 16 titoli identici su documenti diversi. Il punto è il prompt di generazione in
  `backend/app/interpelli.py` (`ARTICLE_PROMPT`, righe ~703-731): il titolo deve contenere un
  discriminante (numero di protocollo, scuola, classe di concorso, data). La chiave di unicità già
  affidabile è `interpello_link` (2 duplicati su 1051).
- *Bandi* — la colonna `canonical_key` esiste ed è progettata per questo, ma è **NULL su tutte le
  1972 righe**: `reconcile_canonical_key` in `scraper_bandi/app/db.py:848-968` non sta popolando.
  Chiave suggerita: normalizzazione di `link_bando`, con fallback su
  `(ente, titolo normalizzato, data_scadenza)`. Il suffisso `-2` già presente in alcuni slug è il
  marcatore delle collisioni.

**Annunci scaduti e `JobPosting`.** Su selezione personale **11.222 righe su 12.441 (90,2%)** hanno
`data_scadenza` passata, e `calculated_status` vale `OPEN` su tutte: la colonna è scorrelata dalla
data e ho dovuto ricalcolare lo stato da `data_scadenza` ovunque. Hai scelto di indicizzarle tutte,
con i non scaduti in cima. Sul markup è stata scelta l'opzione intermedia e **è implementata**:
`selezione-personale/[slug].astro` emette il `JobPosting` **solo finché l'annuncio è aperto**. Le
schede scadute restano visibili e indicizzabili — non perdono traffico — ma non dichiarano più a
Google un'offerta di lavoro attiva, che è ciò che espone a un'azione manuale sul rich result.
Verificato su tre schede aperte (JobPosting presente) e tre scadute (assente), tutte 200 e
`index, follow`.
Nota collaterale: **36 righe hanno date implausibili** (massimo `5026-06-22`).

**`JobPosting` degli interpelli senza `validThrough`** (`interpelli/[slug].astro`): dichiariamo 1046
offerte senza data di chiusura, e solo il 9% è degli ultimi 30 giorni. Serve una politica, non una
data inventata.

**`generateInterpelloSlug`**: da 4 copie a 1 (`slugInterpello` in `src/lib/liste/interpelli.ts`).
Resta la replica Python in `backend/app/interpelli.py:46-59`: se tocchi l'algoritmo, vanno allineate
entrambe.

**Altri difetti trovati e non toccati.**
- `trailingSlash` non è configurato: `/interpelli` e `/interpelli/` rispondono entrambe 200 con
  canonical diversi. La correzione minima è `trailingSlash: 'never'` in `astro.config.mjs`, ma cambia
  il routing di tutto il sito.
- La guardia "pagina fuori range" di `[category].astro:173-176` è rotta (`totalCount` resta `null`
  quando PostgREST risponde `PGRST103`, `totalPages` collassa a 1): `/scuola?page=99999` risponde
  200. Ho riusato l'algoritmo dei numeri di paginazione di quel file, **non** la sua guardia.
- `middleware.ts` imposta `Vary: Accept` solo sul ramo Markdown. Oggi è innocuo perché nulla è in
  cache, ma **va sistemato prima di introdurre qualsiasi `Cache-Control`** sulle pagine: Cloudflare
  potrebbe servire Markdown a Googlebot.
- ~121 URL della sitemap interpelli hanno slug `visualizza-interpelli-…`: sono record legittimi il
  cui `interpello_name` vale letteralmente "VISUALIZZA INTERPELLI". È un difetto dello scraper a
  monte; cambiare gli slug significherebbe 301 su URL già indicizzati.
- `src/components/bandi/` è codice morto (nessun import da `src/pages/`) e diverge dal markup vivo.
  `BandoCard.astro` non ha nemmeno la classe hook `bando-item`. L'ho lasciato dov'è.
- `src/pages/api/interpelli/refresh.ts` importa `../../../types/interpelli`, file che non esiste.
- `src/pages/api/sitemap.ts` è orfano e dichiara `/terms`, `/about`, `/contact`, rotte inesistenti.

---

## 7-bis. Collaudo con JavaScript attivo

Eseguito nel browser il 03/09/2026, senza mai un ricaricamento di pagina:

| Passo | Esito |
|---|---|
| Cambio Regione su `/interpelli` | 1046 → 32 risultati, URL `?regione=marche`, select Provincia da disabilitato a 6 opzioni |
| Click su "2" nella paginazione | 12 schede (32 = 20 + 12), `aria-current="page"` su 2 |
| Tasto Indietro | torna a pagina 1 con 20 schede, il form resta su "Marche" |
| Tasto Avanti | torna a pagina 2 |
| Ricerca "dsga" con regione attiva | 7 risultati, pagina riportata a 1 |
| `/bandi`: apertura tendina Settore | 90 opzioni, rese dal server |
| Ricerca interna "turismo" | 1 opzione visibile |
| Spunta "Turismo" | 1972 → **196**, etichetta "Turismo", contatore "1", badge "1 attivo" |
| Aggiunta chip "Aperto" | 196 → **142**, badge "2 attivi", URL `?settore=87&stato=aperto` |

I due conteggi finali sono stati incrociati con il database: 196 e 142 esatti.

Il percorso senza JavaScript è quello verificato con `curl`, che è esattamente una GET del form
senza esecuzione di script: filtri singoli e multipli, chip e tendine funzionano tutti.

---

## 8. Cosa resta a te

1. **Search Console.** Invia `sitemap-index.xml` (ora elenca 23 file). Le tre sitemap vecchie
   rispondono 301 e vanno **rimosse a mano** dall'elenco, altrimenti restano lì come redirect.
2. **Monitora la copertura** delle 295 pagine nuove. Se dopo 60 giorni compare "Pagina alternativa
   con tag canonical appropriato" o "Duplicata" su `/bandi/regione/*`, la leva è documentata nel
   config: ogni bando è agganciato in media a 3-4 regioni e i bandi nazionali a tutte e 20, quindi
   le prime schede di regioni diverse si somigliano. Si può restringere la dimensione ai soli
   `Bandi regionali / locali` (1443 righe).
3. **Verifica la corretta indicizzazione dei breadcrumb**: la correzione `"id"`→`"@id"` sblocca un
   rich result su ~5.000 URL già esistenti. In Search Console, Miglioramenti → Breadcrumb.
4. **IndexNow.** `src/lib/indexnow.ts` accetta liste di URL e non è mai stato usato per bandi,
   interpelli o pagine filtro. Le 295 pagine nuove si possono notificare in un colpo solo con
   `POST /api/indexnow-notify` (protetto da `API_SECRET_KEY`).
5. **Regola le soglie** in `src/config/pagine-filtro.ts` se vuoi più o meno pagine. Con soglia 3 su
   interpelli e 5 su bandi e selezione, oggi escono 286 pagine.
6. **Correggi il README** su `edunews-bandi-sender.service`: dice disabilitato, ma è attivo.
