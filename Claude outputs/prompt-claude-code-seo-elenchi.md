# Prompt per Claude Code — SEO pagine elenco EduNews24 (interpelli, selezione personale, bandi)

> Copia tutto ciò che segue nella sessione Claude Code aperta nella root del repo `news1`.

---

Sei un senior engineer Astro/TypeScript incaricato di un intervento SEO sulle tre pagine elenco di edunews24.it: `/interpelli`, `/selezione-personale`, `/bandi`. Lavori in questo repo (`news1`): Astro 5 in modalità `output: "server"` con adapter `@astrojs/node` standalone, Tailwind, React solo nell'admin, due istanze Supabase (DB principale per articoli/interpelli/selezione_personale, DB "bandi" separato), backend Python FastAPI in `backend/` e scraper in `scraper_bandi/`.

Il lavoro è diviso in fasi. **La Fase 0 (analisi) è obbligatoria e si conclude con un checkpoint: presenti il piano e ti fermi finché non ti confermo.** Non modificare alcun file di progetto prima di quel via libera (l'unica eccezione sono i due documenti prodotti dalla Fase 0).

## Vincoli assoluti

1. **Niente git.** Non creare branch, non fare commit, stash, checkout o push. Modifica i file e basta; della cronologia mi occupo io.
2. **Non toccare `backend/`, `scraper_bandi/`, `backend/sql/`, `scripts/`.** Niente migrazioni, niente modifiche allo schema, niente script che scrivono su Supabase. Il DB lo usi in sola lettura, con le chiavi anon già presenti in `.env` (`PUBLIC_SUPABASE_URL`/`PUBLIC_SUPABASE_ANON_KEY` per interpelli e selezione_personale, `PUBLIC_SUPABASE_BANDI_URL`/`PUBLIC_SUPABASE_BANDI_ANON_KEY` per bandi). Non stampare mai i valori di `.env`.
3. **Non toccare le pagine di dettaglio** (`src/pages/interpelli/[slug].astro`, `src/pages/selezione-personale/[slug].astro`, `src/pages/bandi/[slug].astro`) salvo l'aggiunta di link interni verso le nuove pagine filtro, se previsto dal piano approvato.
4. **Non rompere la UX attuale**: i filtri istantanei e la paginazione senza reload devono continuare a funzionare; cambia il modo in cui sono costruiti, non il risultato per l'utente.
5. Rispetta lo stile del repo: commenti e naming in italiano, Tailwind, niente nuove dipendenze npm senza chiedermelo, TypeScript senza `any` nuovi dove evitabile.
6. Non inventare contenuti fattuali (date, normative, numeri). I testi introduttivi e le FAQ che scriverai devono essere generici, verificabili e corti; li rileggerò io.
7. Se durante il lavoro scopri qualcosa che contraddice questo prompt o l'analisi allegata, fermati e chiedi. Non "aggiustare" silenziosamente.

## Contesto: l'analisi SEO ricevuta (31/08/2026)

Metodo dell'analisi: HTML servito dal server (quello che vede Googlebot) delle tre pagine, più robots.txt, sitemap e una scheda di dettaglio a campione.

Stato sano di partenza: le tre pagine rispondono 200, canonical corretto verso se stesse, `index,follow`, i 20 annunci della prima pagina sono resi lato server, robots.txt pulito con sitemap dedicate, schede di dettaglio con `JobPosting`.

Problemi, in ordine di priorità:

**P1 — Paginazione invisibile a Google.** Nell'HTML non esiste alcun `<a href="?page=2">`; la paginazione è solo JS. `?page=2` chiamato direttamente restituisce lo stesso contenuto di pagina 1, canonical compreso. Google raggiunge via link interni solo ~20 annunci per sezione. Inoltre Selezione Personale dichiara 11.847 bandi ma `sitemap-selezione-personale.xml` ne contiene 1.000; Interpelli 1.003 dichiarati vs 1.103 in sitemap; Bandi 1.955 vs 1.955. Rimedio richiesto: link reali `?page=N` resi lato server, ogni pagina con canonical verso se stessa e title "… - Pagina N - EduNews24", sitemap spezzate in più file sotto un indice con TUTTE le schede attive.

**P2 — Manca l'architettura per il long-tail.** I filtri (regione, provincia, classe di concorso, categoria, settore, programma) sono solo client-side e non generano pagine indicizzabili. Le ricerche reali sono del tipo "interpelli DSGA Marche", "concorsi comuni Lombardia", "bandi FSE+ Valle d'Aosta", "interpelli classe di concorso A028". Rimedio: pagine statiche linkate per le combinazioni con contenuto, ognuna con H1, title, meta description, due righe di testo proprie e l'elenco filtrato. Pubblicare solo combinazioni con almeno qualche annuncio, non il prodotto cartesiano dei filtri.

**P3 — Title e meta description deboli.**
- Selezione Personale: title attuale "Selezione Personale - EduNews24"; proposta "Concorsi pubblici e selezione personale PA: bandi aggiornati ogni giorno - EduNews24". La description attuale parla di "migliori aziende private" ma la pagina contiene solo PA: da riscrivere sul contenuto reale.
- Interpelli: title attuale "Interpelli Scuola - EduNews24"; proposta "Interpelli scuola 2026/27: docenti, ATA e DSGA per regione e classe di concorso - EduNews24".
- Bandi: title attuale "Bandi e finanziamenti pubblici - EduNews24" va bene; la description elenca i filtri (scritta per chi ha già la pagina davanti). Meglio: aggiornamento quotidiano + i programmi (FESR, FSE+, PNRR, bandi regionali).

**P4 — Poco testo stabile.** Intro attuale: Bandi 39 parole, Interpelli e Selezione Personale una riga. Rimedio: 100-150 parole sotto l'H1 per pagina (cosa sono, a chi servono, frequenza di aggiornamento, 2-3 link alle pagine regionali/di categoria). Su Interpelli anche un blocco FAQ con schema `FAQPage` ("cos'è un interpello", "chi può candidarsi", "come si presenta la domanda").

**P5 — Dati strutturati incompleti.** Solo `/bandi` ha `ItemList` + `BreadcrumbList`; le altre due hanno solo `NewsMediaOrganization` (che viene dal layout). Portare `ItemList` + `BreadcrumbList` anche su Selezione Personale e Interpelli riusando il codice di bandi.

**P6 — Pulizie minori.**
- a) Nell'HTML di Selezione Personale compare la stringa `/selezione-personale/${item.slug}` (template literal non renderizzata) che Google crawla come URL rotto.
- b) Doppioni negli elenchi: su Interpelli "Interpello nazionale a Roma: cercasi docenti per le classi di concorso AAAA, ADAA, ADEE ed EEEE" compare due volte di fila; su Bandi "Voucher formativi a fondo perduto per microimprese in Valle d'Aosta" e "Avviso FSE+ Valle d'Aosta 2026: 1,5 milioni per politiche attive disoccupati" sono duplicati.
- c) Su Bandi le etichette di interfaccia ("Filtri", "Categorie", "Tipologia", "Stato bando", "Importo e scadenza", "Hai bisogno di un esperto…") sono H2/H3 come i titoli dei bandi: vanno declassate a `div`/`span`/`p`.
- d) L'unica immagine della pagina è senza `alt`.

## Cosa so già del codice (verifica tutto in Fase 0, non fidarti)

Queste sono osservazioni fatte leggendo il repo prima di scrivere questo prompt. Confermale o smentiscile una per una con evidenza (path + riga).

- `src/pages/selezione-personale.astro`, `src/pages/interpelli.astro`, `src/pages/bandi.astro`: ognuna fa la propria query Supabase nel frontmatter con `PAGE_SIZE = 20` e `.range(0, 19)`, ignora `Astro.url.searchParams`, e contiene uno `<script is:inline define:vars={...}>` che interroga PostgREST direttamente dal browser e ri-renderizza le card con `innerHTML`. Il markup della card esiste quindi **due volte**: in JSX nel template e come stringa nello script. Il P6a è esattamente questo: la stringa `/selezione-personale/${item.slug}` sta dentro lo script inline, non in un `href`.
- La paginazione è `<nav id="pagination">` con due `<button>` (`#prev-page`, `#next-page`), nessun `<a>`.
- `src/layouts/Layout.astro` calcola il canonical come `canonicalUrl || "https://edunews24.it" + Astro.url.pathname`: la query string viene scartata, per questo `?page=2` ha canonical verso pagina 1. Il layout accetta le prop `title`, `description`, `canonicalUrl`, `keywords`, `image`, `robots` e uno `<slot name="head" />` per JSON-LD aggiuntivo.
- `src/pages/sitemap-selezione-personale.xml.ts` fa UNA sola query senza loop: Supabase/PostgREST tronca a 1.000 righe di default. È questa la causa del "1.000 in sitemap" dell'analisi, non un limite di formato. `sitemap-interpelli.xml.ts` e `sitemap-bandi.xml.ts` hanno invece il loop a blocchi di 1.000.
- `sitemap-interpelli.xml.ts` NON filtra `link_type = 'single'` mentre `interpelli.astro` sì: probabile origine dello scarto 1.003 vs 1.103. La sitemap include quindi URL di interpelli "list" che il dettaglio potrebbe non risolvere: verifica.
- `src/pages/sitemap-index.xml.ts` è un indice statico che elenca le sitemap con `lastmod = oggi`. `public/robots.txt` elenca le stesse sitemap una per una. `src/pages/sitemap-pagine.xml.ts` include `/bandi` ma non `/interpelli` né `/selezione-personale`.
- `src/lib/seo.ts` esporta `generateBreadcrumbStructuredData({ category, category_slug, slug?, title? })`, `generateItemListStructuredData(items: {href, title, image?}[], listName, listUrl)` e `generateFAQStructuredData(faqItems)`. `bandi.astro` li usa già; le altre due pagine no.
- Interpelli: tabella `interpelli`, colonne `interpello_regione`, `interpello_provincia`, `interpello_citta`, `classe_concorso`, `link_type`, `interpello_date`; lo slug NON è salvato a DB ma ricalcolato da `generateInterpelloSlug()` (duplicata in almeno tre file). Selezione personale: tabella `selezione_personale`, `status = 'completed'`, array `sedi`, `categorie`, `settori`, `slug` a DB, tipo in `src/types/bandi.ts` (`SelezioneBando`). Bandi: tabella `bando` sul DB bandi, catalogo (`loadCatalogo()` in `src/lib/supabase-bandi.ts`) con `regioni`, `settori`, `programmi`, `tipologie`, `beneficiari`, `modalita`, `codici_ateco`; regioni/settori/beneficiari sono in junction table, `programma_id`/`tipologia_bando_id` sono FK sulla riga.
- Rotte esistenti che possono collidere con nuove pagine filtro: `src/pages/[category].astro`, `src/pages/[category]/[slug].astro`, e i tre `<sezione>/[slug].astro`. Un URL piatto come `/interpelli/marche` verrebbe catturato da `interpelli/[slug].astro`.
- `src/middleware.ts` fa content negotiation (`Accept: text/markdown`), serve well-known per agenti e blocca `google-credentials.json`. Non dovrebbe interferire con `?page=`, ma verificalo.
- Header in `src/components/Header.astro`: il logo è un SVG inline; l'`<img>` senza alt è più probabilmente il pixel Meta in `<noscript>` dentro `Layout.astro` (riga ~161) oppure l'immagine dello slider in Header. Individua quale immagine intende l'analisi e correggila (per un pixel di tracciamento `alt=""` è la scelta corretta).
- Non esiste `CLAUDE.md` nel repo. Esiste un `README.md` di ~600 righe con architettura, pipeline e variabili d'ambiente: leggilo per intero.

---

## FASE 0 — Analisi e studio del progetto (obbligatoria, con checkpoint)

Obiettivo: capire il progetto abbastanza da progettare l'intervento senza sorprese, e lasciarne traccia scritta.

### 0.1 Studio del repo
- Leggi `README.md`, `astro.config.mjs`, `package.json`, `src/middleware.ts`, `src/layouts/Layout.astro`, `src/lib/seo.ts`, `src/lib/supabase.ts`, `src/lib/supabase-bandi.ts`, `src/types/bandi.ts`, `src/types/interpelli.ts` (se esiste).
- Leggi per intero le tre pagine elenco, le tre pagine di dettaglio, i componenti in `src/components/bandi/`, `src/components/BandiExpertCta.astro`, tutte le `sitemap-*.xml.ts`, `public/robots.txt`, `src/pages/api/sitemap.ts`, `src/lib/indexnow.ts`.
- Guarda come è fatta una pagina già "SEO-completa" del sito (`src/pages/[category].astro` e `src/pages/[category]/[slug].astro`) per riusare pattern esistenti invece di inventarne di nuovi.
- Elenca le rotte in `src/pages/` e verifica l'ordine di priorità di Astro (statiche > dinamiche `[x]` > rest `[...x]`) per ogni URL nuovo che intendi introdurre.

### 0.2 Studio dei dati (sola lettura)
Con uno script Node temporaneo (in `/tmp` o comunque fuori dal repo; cancellalo alla fine) o con `curl` verso PostgREST usando le chiavi anon di `.env`, raccogli per ciascuna sezione:
- conteggio totale e conteggio degli item "attivi" secondo la definizione usata oggi dalla pagina elenco (`status='completed'`, `link_type='single'`, RLS bandi);
- per interpelli: distribuzione per `interpello_regione`, `interpello_provincia`, `classe_concorso` (valori distinti, conteggi, valori sporchi/varianti tipo "Marche" vs "MARCHE", null);
- per selezione personale: distribuzione di `sedi`, `categorie`, `settori` — in particolare capire **cosa contiene `sedi`** (città? province? regioni? misto?) perché da questo dipende se si può fare `/selezione-personale/<regione>` senza una mappatura città→regione; quanti item hanno `data_scadenza` passata;
- per bandi: conteggi per regione (junction), programma, settore, tipologia, e quanti bandi sono `aperto` vs `chiuso`;
- i doppioni del P6b: trova le righe corrispondenti ai titoli citati, capisci se sono righe distinte con contenuto identico (stesso link?) o lo stesso record in due pagine, e da quale campo si può deduplicare in modo sicuro (link, codice, hash) senza toccare il backend.

### 0.3 Verifica dell'HTML servito
Avvia `npm run dev` (o `npm run build && node dist/server/entry.mjs`, vedi README) e con `curl` verifica su ognuna delle tre pagine: title, meta description, canonical, presenza di `?page=` negli `<a>`, JSON-LD presenti, heading (`grep -o '<h[1-6][^>]*>[^<]*'`), presenza della stringa `${item.slug}` nell'HTML, comportamento di `?page=2` e `?page=9999`. Salva l'output come baseline "prima".

### 0.4 Deliverable della Fase 0
1. `docs/analisi-seo-elenchi.md` (la cartella `docs/` non esiste, creala): cosa hai verificato, tabella "affermazione del prompt → confermata/smentita → evidenza (file:riga)", i numeri raccolti al punto 0.2, la baseline HTML del punto 0.3, i rischi individuati, e il **piano di implementazione dettagliato** per le fasi 1-6: file da creare/modificare, schema URL definitivo, config delle pagine filtro, decisioni prese e alternative scartate con motivo.
2. `CLAUDE.md` nella root del repo: contesto per le sessioni future — stack, architettura dual-database, come si avvia, dove stanno le pagine elenco e le sitemap, convenzioni (italiano, Tailwind, niente git automatico, DB in sola lettura dal frontend), pipeline backend in due parole, cosa NON toccare. Massimo ~120 righe, niente segreti, niente contenuti copiati dal README: linka il README per i dettagli.

**Checkpoint:** presentami in chat una sintesi del piano (10-20 righe) e le domande aperte. Aspetta il mio OK. Se nel piano proponi qualcosa di diverso da questo prompt, dillo esplicitamente e motiva.

---

## FASE 1 — Paginazione e filtri via URL, resi lato server (P1, P6a)

Decisione già presa: **lo stato della lista vive nell'URL e il server lo rende; il JS è solo un enhancement.**

1. In ciascuna delle tre pagine elenco, leggi da `Astro.url.searchParams` `page` e i parametri filtro (interpelli: `regione`, `provincia`, `classe`, `q`; selezione personale: `categoria`, `settore`, `sede`, `q`; bandi: gli stessi filtri che lo script client già invia a PostgREST — ricavali dallo script esistente). Valida: `page` intero ≥ 1, altrimenti 1; `page` oltre l'ultima → risposta **404** (non redirect, non pagina vuota indicizzabile). Esegui la query filtrata e paginata nel frontmatter riusando la logica di filtro già presente nello script client (stessi operatori PostgREST: `cs.{}`, `ilike`, FK/junction per bandi).
2. Sposta il markup della card in un componente Astro per sezione (`src/components/interpelli/InterpelloCard.astro`, `src/components/selezione-personale/SelezioneCard.astro`; per bandi esiste già `src/components/bandi/BandoCard.astro` ma nessun file lo importa: verifica se è codice morto allineabile al markup attuale di `bandi.astro` o se va riscritto). Il template della card deve esistere **una sola volta**.
3. Paginazione con veri link: `<nav aria-label="Paginazione">` con `<a href="?page=N">` (conservando gli altri parametri di filtro nell'URL), precedente/successiva più un range di numeri; pagina corrente come `<span aria-current="page">`. Niente `rel="nofollow"`. Pagina 1 linkata come URL pulito (senza `?page=1`): `?page=1` deve avere canonical verso l'URL senza parametro.
4. `<head>` per le pagine N ≥ 2: title "<Titolo sezione> - Pagina N - EduNews24", meta description con "Pagina N di M", canonical **verso se stessa** con `?page=N` (usa la prop `canonicalUrl` di `Layout.astro`, costruendo l'URL assoluto e includendo solo i parametri canonici, in ordine fisso). `index,follow` anche per le pagine N. Aggiungi `<link rel="prev">`/`<link rel="next">` (Google non li usa più ma non costano nulla e Bing sì).
5. Combinazioni filtro via query string (`?regione=Marche`, `?q=…`): sono pagine utili all'utente ma **non** devono generare indicizzazione infinita. Regola: se l'URL contiene `q` o una combinazione di filtri che NON corrisponde a una pagina filtro statica della Fase 3, metti `robots: "noindex, follow"` e canonical verso la pagina elenco base (o verso la pagina filtro statica equivalente se esiste una sola dimensione attiva). Documenta la regola in un'unica funzione riusabile (es. `src/lib/elenco-seo.ts`) invece di ripeterla tre volte.
6. JS come enhancement: il form dei filtri diventa un `<form method="get">` che funziona senza JS. Lo script client (spostalo in uno `<script>` Astro normale o in un file sotto `src/scripts/`, **non** più `is:inline` con template literal di HTML) intercetta `submit`/`change`, aggiorna l'URL con `history.pushState`, e ricarica **l'HTML della lista dal server** (fetch della stessa pagina con `?…` e sostituzione del nodo `#bandi-list` + `#pagination`, oppure un endpoint che restituisce solo il frammento — scegli in Fase 0 e motiva). Così le card hanno un solo template e `${item.slug}` sparisce dall'HTML. Le chiamate PostgREST dirette dal browser vengono rimosse.
7. Gestisci il `back/forward` del browser (`popstate`) ricaricando la lista dall'URL.
8. Interpelli: il `<select>` provincia dipende dalla regione (oggi via `provinceByRegione` serializzato nello script). Mantieni il comportamento; il dato può restare serializzato in un `<script type="application/json">` letto dal client, non in `define:vars` con HTML.

Criteri di accettazione Fase 1: `curl -s https://…/interpelli?page=2` mostra 20 item diversi da pagina 1, canonical `…/interpelli?page=2`, title con "Pagina 2", link `<a href="?page=3">`; `?page=9999` → 404; la stringa `${item.slug}` non compare più in nessun HTML servito; con JS disabilitato filtri e paginazione funzionano; con JS attivo non c'è reload di pagina.

## FASE 2 — Sitemap complete e spezzate (P1)

1. Correggi `sitemap-selezione-personale.xml.ts` aggiungendo il loop a blocchi da 1.000 come nelle altre due (causa del troncamento a 1.000).
2. Allinea `sitemap-interpelli.xml.ts` ai criteri della pagina elenco (`link_type='single'`) — verifica in Fase 0 che il dettaglio risolva solo quelli; se il dettaglio risolve anche i "list", tienili e dimmelo.
3. Per ciascuna delle tre sezioni: un indice `sitemap-<sezione>-index.xml` che elenca file `sitemap-<sezione>-N.xml` (rotta dinamica `src/pages/sitemap-<sezione>-[n].xml.ts`), ognuno con al massimo 1.000 URL, ordinati per data decrescente così che il file 1 contenga sempre i più recenti. Le sitemap monolitiche attuali devono continuare a rispondere (Search Console le conosce) ma restituendo un redirect 301 verso l'indice oppure lo stesso contenuto dell'indice: scegli e motiva.
4. `lastmod` reale per URL (`updated_at` o data di pubblicazione), e per gli indici il `lastmod` più recente del blocco, non "oggi". Mantieni `Cache-Control` coerente con le altre sitemap.
5. Aggiorna `sitemap-index.xml.ts` e `public/robots.txt` con i nuovi indici; aggiungi `/interpelli` e `/selezione-personale` a `sitemap-pagine.xml.ts`. Le pagine `?page=N` NON vanno in sitemap (le pagine filtro della Fase 3 sì, vedi sotto).
6. Verifica: ogni file XML deve essere well-formed (`xmllint --noout`), il totale degli URL nell'indice di selezione personale deve corrispondere al conteggio "attivi" della Fase 0.2.

## FASE 3 — Pagine filtro indicizzabili per il long-tail (P2)

Decisione già presa: **si pubblica solo ciò che ha contenuto, con soglia configurabile; le regioni sono sempre pubblicate.**

1. Schema URL a sotto-percorso, per evitare la collisione con `<sezione>/[slug].astro`:
   - `/interpelli/regione/<regione>`, `/interpelli/classe/<classe>` (es. `/interpelli/classe/a028`), valuta `/interpelli/regione/<regione>/provincia/<provincia>` solo se i numeri della Fase 0.2 lo giustificano;
   - `/selezione-personale/regione/<regione>` **solo se `sedi` è mappabile a regioni in modo affidabile** (Fase 0.2); altrimenti `/selezione-personale/categoria/<categoria>` e `/selezione-personale/settore/<settore>`, e dimmelo al checkpoint;
   - `/bandi/regione/<regione>`, `/bandi/programma/<programma>` (FESR, FSE+, PNRR…), eventualmente `/bandi/settore/<settore>`.
   Slug: minuscolo, senza accenti, trattini (`valle-d-aosta`, `friuli-venezia-giulia`, `a028`). Serve una funzione di slugify unica (`src/lib/slug.ts` o simile) e una mappa slug↔valore DB per le regioni (20 regioni fisse) e per i valori dinamici (classi, categorie, programmi) derivata dai dati con normalizzazione delle varianti trovate in Fase 0.2.
2. Config in un file solo, `src/config/pagine-filtro.ts`: soglia minima di annunci attivi per pubblicare (default 3), lista delle 20 regioni sempre pubblicate, eventuali esclusioni/alias, dimensioni abilitate per sezione. Deve essere il punto unico da cui io regolo cosa esiste.
3. Comportamento: combinazione sotto soglia (e non in whitelist) → 404. Combinazione pubblicata → pagina con H1 proprio ("Interpelli scuola in Marche", "Bandi FSE+ in Valle d'Aosta"), title, meta description, 2-3 righe di testo generate da template (non prosa libera: pattern con nome regione/classe, conteggio, data ultimo aggiornamento), breadcrumb (Home > Sezione > Filtro), elenco filtrato con la stessa paginazione `?page=N` della Fase 1, canonical verso se stessa, `ItemList` + `BreadcrumbList`.
4. Linking interno, altrimenti le pagine non servono a niente: blocco "Esplora per regione" / "per classe di concorso" / "per programma" nelle pagine elenco base (lista di link, solo combinazioni pubblicate), 2-3 link nel testo introduttivo della Fase 4, e nelle pagine filtro i link alle "sorelle" (altre regioni). Valuta un link dalla scheda di dettaglio alla pagina regione corrispondente: è l'unica modifica ammessa alle pagine di dettaglio, e solo se il piano approvato la include.
5. Sitemap `sitemap-pagine-filtro.xml` con tutte le pagine filtro pubblicate (calcolata dai dati, non hardcoded), inserita in `sitemap-index.xml` e `robots.txt`.
6. Il form filtri delle pagine elenco (Fase 1) deve portare, quando è attiva una sola dimensione con pagina filtro pubblicata, all'URL statico corrispondente e non a `?regione=…` (fallo lato server con un redirect 302 oppure lato client nel submit: scegli e motiva; se lo fai solo lato client, la variante `?regione=` resta comunque `noindex` con canonical verso la pagina statica).

## FASE 4 — Title, meta description, testi introduttivi, FAQ (P3, P4)

1. Applica i title proposti dall'analisi per Selezione Personale e Interpelli; per Bandi tieni il title e riscrivi la description (aggiornamento quotidiano + programmi FESR, FSE+, PNRR, bandi regionali). Riscrivi la description di Selezione Personale sul contenuto reale (solo PA: rimuovi "aziende private"). Tutti i title ≤ 60-65 caratteri visibili, description 140-160.
2. Testo introduttivo 100-150 parole sotto l'H1 di ciascuna pagina elenco (solo su pagina 1 e sulle pagine filtro con la loro variante; su `?page≥2` un'unica riga): cosa sono, a chi servono, frequenza di aggiornamento (ricava la frequenza reale dalla pipeline descritta nel README, non inventarla), 2-3 link alle pagine filtro. Tono informativo, niente marketing, niente promesse.
3. Interpelli: blocco FAQ visibile (3-4 domande: cos'è un interpello, chi può candidarsi, come si presenta la domanda, ogni quanto vengono aggiornati) con `FAQPage` tramite `generateFAQStructuredData`. Le risposte devono essere generiche e prudenti (rimandano sempre al testo dell'interpello). Il JSON-LD deve rispecchiare esattamente il testo visibile.
4. Segnala nel report finale ogni frase che contiene un'affermazione fattuale da verificare da parte mia.

## FASE 5 — Dati strutturati (P5)

1. `BreadcrumbList` + `ItemList` su Interpelli e Selezione Personale riusando `src/lib/seo.ts` come già fa `bandi.astro` (ItemList degli item resi sulla pagina corrente, `url` della lista = canonical della pagina, pagina N inclusa).
2. Verifica che `generateBreadcrumbStructuredData` produca `item.id` corretti per le sezioni (oggi assume `/<category_slug>`); se serve una variante per le pagine filtro a tre livelli, estendi la funzione senza rompere gli usi esistenti negli articoli.
3. Non aggiungere `JobPosting` alle liste (va solo nel dettaglio, dove c'è già).

## FASE 6 — Pulizie (P6)

- b) Dedup in lettura: in base a quanto trovato in Fase 0.2, deduplica in fase di rendering (e nelle sitemap) sulla chiave sicura individuata (es. `interpello_link` per interpelli, `link_bando`/`canonical_key` per bandi), mantenendo il record più recente. La dedup a monte nel backend è **fuori scope**: nel report indica precisamente in quali funzioni di `backend/app/interpelli.py` e `scraper_bandi/` andrebbe fatta e con quale chiave, così me ne occupo io.
- c) Heading su Bandi: etichette UI da H2/H3 a `p`/`span`/`div` (mantenendo classi e aspetto); stessa verifica sulle altre due pagine. Alla fine ogni pagina elenco deve avere un solo H1 e H2 solo per i titoli degli annunci e per le sezioni di contenuto reale (intro, FAQ, "Esplora per regione").
- d) `alt` sull'immagine individuata in Fase 0.
- Verifica che il conteggio nell'hero ("N bandi disponibili") sia coerente con quello che la sitemap dichiara: se il conteggio include annunci scaduti/chiusi, dimmelo nel report (la gestione degli scaduti è fuori scope, ma non voglio numeri che si contraddicono senza saperlo).

## FASE 7 — Verifica e report

1. `npm run build` deve passare senza errori né nuovi warning. `npx astro check` (se configurato) senza nuovi errori.
2. Ripeti il protocollo della Fase 0.3 su: le tre pagine base, `?page=2`, `?page=9999`, una pagina filtro pubblicata, una sotto soglia (404), una combinazione `?q=…` (noindex), tutte le sitemap (well-formed, conteggi). Confronta con la baseline e riporta "prima/dopo" in tabella.
3. Valida i JSON-LD estraendoli dall'HTML e facendo almeno il parse JSON + controllo dei campi obbligatori; se hai rete, usa il validator di schema.org.
4. Test manuale con JS disabilitato e abilitato: filtri, paginazione, back/forward, provincia dipendente dalla regione.
5. Report finale `docs/report-seo-elenchi.md`: file modificati/creati con una riga di motivazione ciascuno; decisioni prese; cose fuori scope trovate (almeno: dedup backend, `interpelli/[slug].astro` che carica l'intera tabella a ogni richiesta e trova lo slug in memoria, annunci scaduti e `validThrough`, la funzione `generateInterpelloSlug` duplicata in più file); frasi fattuali da verificare; passi che restano a me (applicare in Search Console i nuovi indici sitemap, monitorare la copertura, eventuale IndexNow per le pagine filtro tramite `src/lib/indexnow.ts`).

## Fuori scope (non farlo, anche se sembra facile)

Modifiche a `backend/`, `scraper_bandi/`, SQL, dati su Supabase; salvataggio dello slug degli interpelli a DB; gestione degli annunci scaduti; refactoring delle pagine di dettaglio; qualsiasi operazione git; nuove dipendenze; modifiche all'admin.

## Come lavorare

- Una fase alla volta, nell'ordine dato. Alla fine di ogni fase: `npm run build`, curl di verifica, riepilogo in 5 righe di cosa hai fatto e cosa hai lasciato in sospeso. Se una fase richiede una decisione non coperta dal prompt, chiedi prima di procedere.
- Quando riusi pattern del repo, cita il file da cui li prendi. Quando scarti un'alternativa, di' perché.
- Non cambiare l'aspetto grafico delle pagine oltre a quanto strettamente necessario (blocchi intro/FAQ/esplora vanno inseriti con lo stesso linguaggio visivo delle pagine).
