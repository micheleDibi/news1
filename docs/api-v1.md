# API pubblica `/api/v1`: guida di implementazione

> Versione del contratto: **1.1** (additiva; `VERSIONE_API` in `costanti.ts`, OpenAPI `1.1.0`).
> La 1.1 aggiunge ai bandi `details.official_source`, `details.opens_on_verified`,
> `details.deadline_verified`, `details.last_checked_at` e due valori di `status`
> (`suspended`, `revoked`). Nessun campo rimosso o rinominato.

Per chi mantiene o estende l'API (sviluppatori e sessioni AI). Chi la **usa** trova il contratto in
`https://edunews24.it/api/v1/openapi.json` e la guida in `https://edunews24.it/sviluppatori/api`
(anche in Markdown con `Accept: text/markdown`).

In produzione dal **21 settembre 2026** (commit `53534ea`). Il piano approvato, con l'analisi dei dati
e le revisioni avversariali, è in `~/.claude/plans/humble-frolicking-moth.md`, fuori dal repo: questo
documento contiene quello che serve per lavorare sul codice. I numeri sui dati sono misure del
21/09/2026.

---

## 1. In una pagina

- **Pubblica, senza chiave, in sola lettura.** Rate limit per IP, cache, CORS aperto (`GET`, `HEAD`,
  `OPTIONS`, niente credenziali).
- **Perimetro:** articoli, categorie, interpelli, selezione personale, bandi. **Mai il testo
  integrale**: solo campi di sintesi, e ogni elemento porta l'URL canonico della scheda sul sito.
  L'unico URL esterno è `details.official_source.url` dei bandi (dalla 1.1): la pagina o l'atto
  dell'ente, mai un sito che ripubblica bandi altrui.
- **Formati:** REST JSON versionato, JSON Feed 1.1, RSS 2.0, OpenAPI 3.1.
- **Contratto stabile:** in v1 si aggiunge soltanto (campi, parametri, valori di enum). Le modifiche
  incompatibili vanno in `/api/v2`, con almeno 6 mesi di coesistenza e gli header `Deprecation` e
  `Sunset` sulla v1: è un impegno pubblico (`testi-doc.ts`, `PARAGRAFI_EVOLUZIONE`).

| Path | Cosa | Parametri |
|---|---|---|
| `/api/v1` | indice (senza DB) | query ignorata |
| `/api/v1/openapi.json` | specifica | query ignorata |
| `/api/v1/articles`, `/{id}` | articoli | `category`, `has_video`, `since`, `until`, `limit`, `cursor` |
| `/api/v1/categories` | categorie con secondarie | nessuno (400 con parametri) |
| `/api/v1/interpelli`, `/{id}` | interpelli | `region`, `since`, `until`, `limit`, `cursor` |
| `/api/v1/selezione-personale`, `/{id}` | concorsi e selezioni | `region`, `national`, `since`, `until`, `updated_since`, `limit`, `cursor` |
| `/api/v1/bandi`, `/{id}` | bandi | come la selezione |
| `/api/v1/feeds/{articles\|interpelli\|selezione-personale\|bandi}.{json\|xml}` | feed, fino a 50 elementi (selezione: solo annunci non scaduti, ordinati per `updated_at`) | query ignorata |
| `/api/v1/feeds/articles/{categoria}.{json\|xml}` | feed per categoria | query ignorata |
| qualunque altro path sotto `/api/v1` | 404 problem+json, senza DB | — |

I dettagli (`/{id}`) e `/categories` non accettano parametri: qualunque parametro dà 400
`unknown-parameter`; una query oltre 2048 caratteri dà un solo errore `(query)`.

---

## 2. Architettura

Tre livelli, pensati perché quasi tutto si possa testare con `node --test` senza DB né variabili
d'ambiente.

```
src/pages/api/v1/**            13 rotte di 10 righe: definisciRotta(DESCRITTORE) ed export
                               GET, HEAD (= GET), OPTIONS, ALL (imposti da rotte.test.ts)
        │
src/lib/api-v1/rotta.ts        IMPURO: singleton del processo, configurazione, corpus, log
        │
src/lib/api-v1/gestore.ts      puro: limitatore → validazione → cache → semaforo → produzione → 200/304
src/lib/api-v1/risorse.ts      puro: un descrittore per rotta (prepara senza DB, produci con FonteDati)
        │
src/lib/api-v1/fonte-supabase.ts  IMPURO: esegue un PianoQuery su supabase / supabaseBandi, con
                                  timeout di 5 s per query, e traduce gli errori PostgREST in
                                  ErroreDati; nessun filtro, ordinamento o limite proprio
```

### Moduli (`src/lib/api-v1/`)

| Modulo | Ruolo |
|---|---|
| `costanti.ts` | URL, limiti, timeout, range IP di Cloudflare (con data e fonte), `ID_MASSIMO_INT4` |
| `contratto.ts` | solo tipi: DTO in uscita, righe del DB (`unknown`), riferimenti, `PianoQuery`, `FonteDati` |
| `errori.ts` | `ProblemaApi` (tutti i problem+json: 400, 404, 405, 429, 500, 503), `ErroreDati` con classe, `classificaErrore` |
| `tempo.ts` | tutte le date: euristica di `published_at`, Europe/Rome esplicito, RFC 3339/822, parametri istante |
| `testo.ts` | testo semplice: entità, tag, markdown, URL esterni ridotti al nome host, sintesi a 600 caratteri |
| `url.ts` | URL dei media, degli articoli (`getArticlePublicUrl`), delle schede, dell'API |
| `parametri.ts` | `SPEC_PARAMETRI`, validazione rigorosa, query canonica, `meta.filters` |
| `cursore.ts` | cursore opaco base64url legato ai filtri (hash), `idMassimo` |
| `filtri.ts` | **piano delle query**: condizioni di pubblicazione, ordinamenti, filtri, keyset, limiti; `pianoRiferimento` |
| `colonne.ts` | **select esplicite** (mai `*`) |
| `riferimenti.ts` | riferimenti validati di categorie e profili, `CacheRiferimento` (TTL 10') |
| `mappa-articoli.ts`, `mappa-categorie.ts`, `mappa-opportunita.ts` | righe → DTO, campo per campo |
| `sezioni.ts` | le tre sezioni (etichetta da `config/pagine-filtro.ts`, colore da `category-colors.ts`) |
| `feed.ts` | JSON Feed e RSS (XML solo tramite il costruttore `elemento()`, con escape) |
| `http.ts` | header comuni, profili di Cache-Control, ETag/304, problem+json, preflight |
| `limitatore.ts`, `semaforo.ts`, `cache.ts` | token bucket per IP, concorrenza verso il DB, cache in memoria |
| `openapi.ts`, `testi-doc.ts`, `documentazione.ts` | contratto pubblico; `documentazione.ts` alimenta la pagina `src/pages/sviluppatori/api.astro` (che si limita a renderla) |
| `indice.ts` | dati di `GET /api/v1` |
| `risorse.ts`, `gestore.ts` | orchestrazione (vedi sopra) |
| `fonte-supabase.ts`, `rotta.ts` | gli unici due moduli impuri |

Fuori da `api-v1/`, il dominio dei bandi vive in `src/lib/bandi/` (moduli puri, un test omonimo
ciascuno in `tests/estrazioni/`): `pubblicazione.ts` (il predicato e la fonte di lettura),
`domini.ts` (denylist degli aggregatori, `urlPubblicabile`), `testi-stato.ts`, `filtro-stato.ts`,
`contenuto.ts`, `cta.ts`, `jsonld.ts`, `slug-storico.ts`, `tipi.ts`. L'API ne usa
`pubblicazione.ts`; gli altri servono alle pagine.

**Moduli estratti** per renderli testabili, ri-esportati dai file originali (i chiamanti non cambiano):

- `src/lib/liste/slug-interpello.ts` ← `liste/interpelli.ts`. **Gemello Python**:
  `_generate_interpello_slug` in `backend/app/interpelli.py`. La parità è verificata da
  `tests/estrazioni/slug-interpello.test.ts`, che esegue la funzione Python in un `python3` isolato:
  **senza `python3` il test viene saltato** (controllare `# skipped 0`).
- `src/lib/stato-bando.ts` ← `supabase-bandi.ts` (`STATI_BANDO`, `StatoBando`, `todayRomeISO`,
  `effectiveStatoBando`).

**Modulo nuovo del sito:** `src/lib/intestazioni-inoltro.ts`, la guardia importata da
`src/middleware.ts` (§7).

**Dipendenze dal resto del sito.** I moduli puri usano: `getArticlePublicUrl` (`utils.ts`) e
`locSicura`/`escapeXml` (`sitemap.ts`) in `url.ts` e `feed.ts`; `config/pagine-filtro.ts` e
`category-colors.ts` in `sezioni.ts` e `feed.ts`; `regioni.ts` e `slug.ts` in parametri e mapper;
`liste/formato.ts` in `feed.ts`. Un cambiamento lì cambia URL e testi dell'API, e quei file non devono
importare Supabase, altrimenti i test dell'API non si caricano più.

### Flusso di una richiesta (`gestore.ts`)

1. `OPTIONS` → 204 CORS, senza limitatore né DB.
2. Chiave del client e token bucket (anche HEAD e metodi non ammessi). Secchio vuoto → 429 `no-store`.
3. `descrittore.prepara(url, params)`: validazione sintattica **senza DB** (parametri, id, percorso del
   feed, cursore) → 400/404 immediati. L'esistenza della categoria e del dettaglio si verifica in
   produzione.
4. Cache in memoria, chiave = path + query canonica (+ data di Roma per selezione e bandi, che
   espongono `status`): fresca (60 s, 300 s per categorie/indice/openapi) → servita; in
   stale-while-revalidate (altri 120 s) → servita e rinfrescata in background; produzione in volo per
   la stessa chiave → aggancio. **Si salvano solo le risposte riuscite**: i 400/404 prodotti in
   `produci` (categoria sconosciuta, id inesistente) interrogano il DB a ogni richiesta; in HTTP sono
   cacheabili 60 s.
5. Miss: semaforo globale (8 slot, coda 32, attesa massima 2 s; con la coda piena il rifiuto è
   immediato). Saturazione → copia stantia se c'è, altrimenti 503 `Retry-After: 5`. Il rinfresco in
   background non entra in coda: salta se il semaforo è occupato.
6. Produzione con budget di 10 s (dal momento in cui si ottiene lo slot) e timeout di 5 s per query
   (in `fonte-supabase.ts` e nel caricamento dei riferimenti).
7. Esiti:
   - `ProblemaApi` → il suo status;
   - errore di disponibilità (rete, timeout/abort, 5xx, 401, 408, 429, 57014, semaforo saturo) →
     copia stantia entro freschezza + 1 h (`X-EduNews24-Cache: STALE`,
     `Cache-Control: public, max-age=30, s-maxage=60`), altrimenti 503 `Retry-After: 30` (5 per il
     semaforo);
   - 22007/8/9 con cursore → 400 `invalid-cursor`;
   - ogni altro errore, compresi gli errori del DB di classe programmazione, permesso (42501) e
     non-trovato (PGRST116) → 500 `no-store`, con log campionato (uno al minuto per tipo di evento).
     Eccezione: un 42501 su `profiles` non è un guasto, e tutti gli autori diventano "Redazione
     EduNews24" (`rotta.ts`).
8. Corpo ed ETag debole (SHA-256) si calcolano in produzione e si salvano in cache insieme; il gestore
   fa il confronto debole con `If-None-Match` → 304 (anche sulle copie stantie), altrimenti 200.

**Niente deve uscire dal gestore come eccezione**: in Astro un'eccezione non gestita in una rotta
diventa la pagina 410 HTML di `[category].astro`. Per lo stesso motivo ogni rotta esporta `ALL`
(405 JSON) e **`HEAD` esplicito**: con `ALL` presente Astro manderebbe HEAD su `ALL`.

---

## 3. Regole che non si toccano

Sono le invarianti dell'API, con i test che le difendono. Dove il test copre solo in parte,
la tabella lo dice: il resto tocca alla revisione del codice.

| Regola | Dove | Test |
|---|---|---|
| Solo le colonne elencate, mai `*`, mai embed di `profiles` | `colonne.ts` | `rotte.test.ts` (insieme esatto per ogni select + lista nera per tabella) |
| Condizioni di pubblicazione in **ogni** modo (elenco, dettaglio, feed) | `filtri.ts` | `filtri.test.ts`, `gestore.test.ts` |
| `fonte-supabase.ts` non filtra, non ordina, non limita | `fonte-supabase.ts` | `purezza.test.ts`, **solo in parte**: vieta i metodi di filtro diretti (`.eq(`, `.in(`…) e le stringhe `isdraft`/`stato_processing`/`completed`/`'*'`, ma non vede un `.filter/.or/.order/.limit` in più aggiunto fuori dall'adattatore |
| Nessun testo integrale; testo semplice senza markup | mapper + `testo.ts` | `mappa-*.test.ts`, `testo.test.ts` |
| Autore solo `public_name`, mai `creator` né `full_name` | `mappa-articoli.ts` | `mappa-articoli.test.ts` (non fuga) |
| URL costruiti dall'API (`url`, `links`, `section`, `instance`) sempre assoluti su `https://edunews24.it`, mai l'host della richiesta; i campi media sono assoluti ma possono stare su host di terzi | `url.ts`, `http.ts` | `url.test.ts`, `http.test.ts` |
| Nessun URL esterno nei testi, fuori dai campi URI | `testo.ts` | `contratto.test.ts` |
| Output valido contro `openapi.ts` | tutto | `contratto.test.ts` (validatore JSON Schema) |
| Moduli puri: niente `import.meta.env` né `process.env`, niente import di supabase/supabase-bandi/corpus/categories/logger, niente getter locali di Date né `toLocale*`, niente `enum`/`namespace`/`any` | `src/lib/api-v1/*` tranne `fonte-supabase.ts` e `rotta.ts`, più le tre foglie | `purezza.test.ts` (scansione statica + import sotto node senza env) e `TZ=Asia/Kathmandu` |
| Nessuna stringa del client come chiave di oggetto (solo Map/Set/array; il cursore accetta esattamente `v`/`r`/`f`/`k`) | `parametri.ts`, `feed.ts`, `cursore.ts` | `parametri.test.ts`, `feed.test.ts`, `cursore.test.ts` (`constructor`, `__proto__`) |

### Condizioni di pubblicazione (in `filtri.ts`)

| Risorsa | Condizione | Note |
|---|---|---|
| articles | `isdraft eq false`, `category_slug` fra le categorie del riferimento, `published_at not is null` | come il sito: le 1.256 righe con `isdraft` NULL restano fuori. Non usare `not.is.true` né controlli `!== true` lato app, che le includerebbero |
| interpelli | `link_type eq single`, `status eq completed`, `interpello_date not is null` | il dettaglio del sito è più permissivo; l'API no |
| selezione-personale | `status eq completed`, `data_pubblicazione not is null` | |
| bandi | il predicato di `FONTI_BANDI` (`src/lib/bandi/pubblicazione.ts`) più `created_at not is null` | oggi `stato_processing eq completed` e `slug not is null`: ripetono la RLS apposta (restano corretti anche se la policy cambia), ma sono scritti in un posto solo, condiviso con liste, corpus e scheda. Sulla vista `bando_pubblico` il predicato è dentro la vista e le operazioni sono zero |

Ogni risorsa ha `<colonna di ordinamento> not is null`: serve al keyset. Senza, una riga con chiave
NULL in posizione `limit` fa rispondere 500 all'intera pagina (`posizioneDi` in `risorse.ts`).

**Categorie ed esclusioni implicite.** Gli articoli escono solo se `category_slug` è nel riferimento
delle categorie. Così oggi restano fuori i 9 articoli con categoria `bandi`, il cui URL è oscurato da
`src/pages/bandi/[slug].astro`. L'esclusione **non è codificata**: vale finché `categories` non ha una
riga `bandi` (o `interpelli`, `selezione-personale`). Il riferimento tiene al massimo 30 categorie
valide e scarta quelle con slug o nome non validi: gli articoli di una categoria scartata spariscono
dall'API senza errore (resta solo il log `riferimento-categorie`).

**La RLS non protegge.** La chiave anon legge bozze, `profiles` (con le email) e le colonne interne
dei bandi, e con ogni probabilità può anche scrivere su `articles`, `categories` e `profiles`. Righe e
riferimenti sono quindi **input non fidato**. Le barriere sono le condizioni qui sopra, le select di
`colonne.ts` e i mapper campo per campo, con `testo.ts` (regex lineari) e `url.ts`.

**Cache e ritiri.** Una bozza non viene mai *prodotta*, ma un contenuto già servito che torna bozza
resta visibile fino a 3 minuti dalla cache in memoria (60 s + 120 s di SWR: il rinfresco che trova un
404 non sostituisce la voce) e, all'edge, fino a `s-maxage` + `stale-while-revalidate` del profilo
(dettaglio: 900 + 900 s).

---

## 4. Decisioni ed euristiche (e i loro limiti)

**`articles.published_at` è `timestamp` senza fuso e mescola due convenzioni.** L'editor scrive
`toISOString()` (UTC, 0-3 decimali). Il backend Python scrive `datetime.now(ITALY_TZ)` (Roma, 6
decimali, 4-6 dopo che Postgres toglie gli zeri finali; circa un valore su 1000 ne ha 3 o meno e cade
nel ramo UTC). `istantePublishedAt` in `tempo.ts` applica: offset presente → si usa; 0-3 decimali →
UTC; 4-6 → Europe/Rome. **Errore noto:** ~436 articoli scritti dall'editor precedente (circa
05-12/2025) sono in ora di Roma con millisecondi e risultano spostati avanti di 1-2 h. Conseguenze:
- l'ordinamento e il cursore usano il valore **grezzo** (come il sito): sulle righe storiche l'ordine
  può non essere monotono entro 2 h;
- `since`/`until` filtrano sul DB un superinsieme (`published_at >= muroUtc(since)`,
  `< muroUtc(until + 2h)`) e tagliano esattamente nell'app: le pagine possono essere corte (anche
  vuote) con `has_more` vero; i client si fermano solo quando `links.next` è null;
- quando la colonna diventerà `timestamptz`, il ramo "offset presente" rende l'euristica inerte: si
  può togliere.

**Altre date.** `interpello_date` è il giorno della fonte (mezzanotte di Roma). Per la selezione
`published_at` è `data_pubblicazione` (inPA); per i bandi è `created_at` (inserimento:
`data_pubblicazione` è NULL al 92% e metterebbe in cima un bando del 2009). Gli istanti escono in RFC
3339 con l'offset di Roma, troncati al secondo; le date di calendario (`deadline_on`, `opens_on`,
`source_published_on`) in `YYYY-MM-DD`; l'RSS in RFC 822.

**Scadenze e `status`.**
- Selezione: `deadline_on` è il **giorno UTC** di `data_scadenza` (convenzione del sito, `corpus.ts`);
  `status = deadline_on >= oggi(Roma) ? open : closed`. Per le scadenze fra 00:00 e 01:59 di Roma con
  l'ora legale (00:00-00:59 con l'ora solare) `deadline_on` precede di un giorno la data locale di
  `deadline_at`: è voluto (è il giorno che la fonte intende con «ore 24:00»).
- Bandi: `effectiveStatoBando` come il sito (anche i 14 "in apertura prossimamente" con apertura
  già passata restano `upcoming`): è la firma con `oggi` passato dal chiamante, che l'API fissa una
  volta per richiesta.
- Bandi, da 1.1: `status` ammette anche `suspended` (bando fermato dall'ente) e `revoked`
  (annullato, stato definitivo). Su questi due non si può partecipare **qualunque** sia
  `deadline_on`, e la scadenza passata non li trasforma in `closed` (garanzia A3: un sospeso non si
  chiude mai d'ufficio). Chi deduceva "si può partecipare" da `status !== 'closed'` sbaglia.
  I due valori non compariranno finché il CHECK della colonna non li ammette (migrazione 06).
- Scadenza oltre 8 anni dalla pubblicazione → implausibile: `deadline_*` null (selezione: `status`
  `open`; bandi: lo stato della fonte). Oggi 22 righe della selezione (fino al 5026, sentinella
  2099-12-30).
- Interpelli: nessuna scadenza, `status` sempre null.
- Il feed della selezione contiene solo annunci non scaduti (giorno UTC ≥ oggi di Roma; le scadenze
  NULL restano fuori, come nella lista del sito) ed è ordinato per `updated_at desc, id desc`: è l'unico
  piano che non usa la colonna di ordinamento della risorsa.

**Autore.** Il lookup replica la pagina: `creator` come id di profilo, poi come `full_name` univoco.
Si espone `public_name` solo se il profilo è visualizzabile e il nome ha al massimo 80 caratteri;
altrimenti (e per "Admin", "AI News Generator…", `creator` NULL, `profiles` illeggibile) "Redazione
EduNews24".

**Riferimenti troncati.** `pianoRiferimento` legge al massimo 500 profili, 100 categorie e 300
categorie secondarie. Se le tabelle crescono oltre, alzare i limiti: altrimenti autori e categorie
spariscono senza errori.

**Testi.** `summary` degli articoli (`sintesiDaMarkdown`): markdown rimosso, intestazioni di servizio
del generatore ("Paragrafo 1", "Primo paragrafo (200 parole)") tolte, titoli chiusi da un punto,
taglio all'ultima fine frase fra 300 e 600 caratteri (esclusi i punti delle abbreviazioni), altrimenti
all'ultima parola con `…`. Titolo, `title_summary` ed excerpt degli articoli passano da
`pulisciTestoMarkdown`; i testi ufficiali delle opportunità da `pulisciTesto` (lì `_` e `*` possono
essere testo). Gli URL esterni con `http(s)://` o `www.` diventano il solo nome host (`inpa.gov.it`);
email, domini senza schema e URL di edunews24.it restano; un campo fatto solo di un URL esterno diventa
null; i link markdown diventano il loro testo, le immagini markdown spariscono.
**Le regex di `testo.ts` devono restare lineari**: due ReDoS sono già stati trovati e corretti, e i test
di regressione girano su input da 200.000 caratteri. Qualunque regex nuova va controllata allo stesso
modo.

**Immagini.** Tutti gli URL http(s) validi, anche di host di terzi (circa 800 articoli). `blob:`,
`data:`, stringhe vuote, credenziali, host non validi e URL oltre 2048 caratteri → null;
`/percorso` → `https://edunews24.it/percorso`; `//host/x` → `https://host/x`; relativi senza barra
iniziale → null.

**`has_video`** filtra sul DB con `video_url like http*`, mentre il campo `video` segue
`urlMediaAssoluto`: sugli URL relativi o non validi i due possono divergere.

**Regioni.** Unica fonte: `src/lib/regioni.ts`. `region` significa "l'array `regions` contiene la
regione". Per interpelli e selezione i valori DB ammessi sono le varianti del registro più quelle
viste nel corpus (solo se il registro le riconosce), sempre fra doppi apici con escape: `listaInPg`
per `interpello_regione in (…)`, `letteraleArrayPg` per `sedi ov {…}`. I valori del corpus si usano
solo se `corpusSeCaldo` li ha già, senza attenderli: a freddo il filtro può perdere righe scritte con
grafie assenti da `varianti` (che pure mostrano la regione in `regions`). Per un risultato stabile,
aggiungere a `varianti` le grafie viste nel DB. Per i bandi il filtro passa dall'embed
`filtro_regione:bando_regioni!inner(regioni!inner(slug))`. `national` è separato: le 540 selezioni
"Nazionale" non escono con `region`; i bandi nazionali collegati a tutte le regioni sì.

**Identificatori.** I dettagli usano l'id numerico: gli slug non sono univoci (4 duplicati fra gli
articoli pubblicati, 2 coppie fra le schede pubblicate della selezione) e quello degli interpelli è
calcolato. `bando.id` è **int4**: un id oltre 2.147.483.647 risponde 404 (e 400 nel cursore) senza
interrogare il DB (`idMassimo` in `cursore.ts`).

**Paginazione.** Solo keyset `(colonna desc, id desc)`, `limit` 20 (max 100), si leggono `limit + 1`
righe, niente count né offset. Il cursore è `base64url({v, r, f, k:[grezzo, id]})`: `f` è l'hash dei
filtri (cambiare `limit` è lecito, cambiare i filtri no). Non è firmato: forgiarlo equivale a un
`until` lecito. Il `next` riparte dall'ultima riga *letta*, anche se scartata dal post-filtro o dal
mapper: niente buchi né duplicati.

---

## 5. Come si fa

Per ogni aggiunta compatibile: una voce in `CHANGELOG` (`testi-doc.ts`, mostrato in
`/sviluppatori/api`) e l'aumento della versione minore in `VERSIONE_OPENAPI` (`costanti.ts`). Poi
`npm test` e `npx --no-install tsc --noEmit -p tsconfig.json`.

### Aggiungere un campo a un DTO

1. `colonne.ts`: aggiungere la colonna alla select. **Controllare che non sia interna o sensibile.**
2. `contratto.ts`: il campo nella `Riga*` (come `unknown`) e nel DTO, nella posizione giusta.
3. Il mapper: costruirlo campo per campo, con `null` se assente; testi da `pulisciTesto`.
4. `openapi.ts`: la proprietà nello schema, `required`, con la nullabilità (`type: ['string','null']`),
   nella stessa posizione del DTO.
5. Test:
   - `rotte.test.ts`: insieme esatto delle colonne (se la colonna era nella lista nera, toglierla solo
     di proposito);
   - il test del mapper: chiavi attese e fixture in `tests/api-v1/fixture/`;
   - gli esempi in `testi-doc.ts`;
   - `openapi.test.ts`: il campo va nel DTO di prova in `COPPIE`, nella stessa posizione dello schema,
     e, se è nullabile, nella mappa `nullabili`;
   - `contratto.test.ts` fallisce se l'output ha un campo non dichiarato o se lo schema richiede un
     campo assente.

Un campo nuovo è compatibile; rinominarne o toglierne uno no (va in v2).

### Aggiungere un filtro

1. `parametri.ts`: il nome in `NomeParametro`, `ORDINE_PARAMETRI` e `SPEC_PARAMETRI`, con lo stesso
   ordine relativo; il campo in `FiltriElenco` e il valore iniziale `null` nell'oggetto `filtri` di
   `validaQueryElenco`; la validazione nello `switch`; `valoreCanonico` (link, chiave di cache, hash del
   cursore). Per un filtro non stringa aggiornare anche `filtriMeta`, che deve restituire il tipo
   dichiarato nello schema.
2. `filtri.ts`: l'operazione nel piano della risorsa. **A PostgREST arrivano solo valori validati o
   presi da whitelist**; dentro `or()` solo costanti e cursori validati.
3. `openapi.ts`: da `SPEC_PARAMETRI` si generano solo l'elenco e l'ordine dei parametri e le chiavi di
   `Filtri*`. Per un nome nuovo aggiungere il `case` in `parametroQuery` (schema del parametro) e in
   `schemaFiltro` (schema in `meta.filters`), altrimenti tsc dà TS2366. Se il filtro vale per gli
   articoli, aggiornare anche `filters` nell'esempio `ElencoArticoli`. Aggiungere la regola in
   `REGOLE_PARAMETRI` (`testi-doc.ts`).
4. Test nuovi in `parametri.test.ts` e `filtri.test.ts`; aggiornare le attese scritte a mano in
   `gestore.test.ts` (`meta.filters`), `openapi.test.ts` (esempi) e `parametri.test.ts` (query
   canonica e `meta.filters`).

Il **filtro** `status` (aperto/scaduto) non esiste ancora: la 1.1 ha aggiunto due valori al campo,
non un parametro per filtrarci. Va progettato da zero, e la chiave di cache deve dipendere da `oggi`
(come già fa `dipendeDaOggi`).

### Aggiungere una risorsa

Molte liste sono scritte a mano e tsc non le controlla tutte:
- `contratto.ts`: `Risorsa`, `Tabella`, `NomeSelect`, `RighePerSelect`, i DTO;
- `colonne.ts`: la select e `SELECT_PER_NOME`;
- `parametri.ts`: `SPEC_PARAMETRI` e `COLONNA_DATA` (senza la voce, qualunque parametro, anche
  `limit`, dà 400);
- `filtri.ts`: il piano (condizioni di pubblicazione in ogni modo, dettaglio compreso),
  `COLONNA_ORDINAMENTO`, `TABELLA`, `selectDi`;
- `risorse.ts`: `PERCORSO`, `dipendeDaOggi`, gli switch di `leggiEMappa`, i descrittori;
- il mapper;
- le rotte in `src/pages/api/v1/` (copiando una esistente: le quattro esportazioni);
- `openapi.ts` (`RISORSE`, `DESCRITTORI`, schemi e path), `documentazione.ts` (`RISORSE` e la tabella
  di `risorse()`), `indice.ts` (`RISORSE_INDICE`), eventualmente `feed.ts`.

Nei test: `rotte.test.ts` confronta i file delle rotte e i path OpenAPI con `MAPPA_ROTTE`, scritta a
mano; la select nuova va aggiunta anche in `attese` e `TABELLA` dello stesso test, con le colonne
vietate della tabella nella lista nera, **altrimenti il controllo dell'insieme esatto viene saltato**.
Aggiornare anche le liste di `openapi.test.ts` e `documentazione.test.ts`.

### Cambiare limiti e cache

- **Rate limit del processo:** `API_V1_RL_CAPACITA` e `API_V1_RL_RICARICA` (§7). Cambiano il
  limitatore, gli header e l'indice `/api/v1`, **non** la documentazione pubblica né OpenAPI, che
  citano i default di `costanti.ts`. Per un cambio permanente modificare `RATE_LIMIT_CAPACITA` e
  `RATE_LIMIT_RICARICA` in `costanti.ts`, correggendo anche `RATE_LIMIT_POLICY`, che ha `w=60` fisso.
  Tenere coerenti i limiti di nginx e Cloudflare.
- **Cache HTTP:** `CACHE_CONTROL` in `http.ts` e, a mano, la tabella pubblica `PROFILI_CACHE` in
  `testi-doc.ts`; i test che fissano i valori sono `documentazione.test.ts`, `gestore.test.ts` e
  `http.test.ts`. Il preflight è in `rispostaPreflight`.
- **Cache in memoria:** `POLITICHE` in `gestore.ts`; dimensioni (1000 voci, 16 MiB) in `rotta.ts`.
- **Timeout, semaforo, TTL dei riferimenti:** `costanti.ts`. Vincolo: attesa del semaforo + budget
  (2 s + 10 s) deve restare sotto il `proxy_read_timeout` di nginx. I `Retry-After` del 503 (5 e
  30 s) sono in `gestore.ts`.
- **Pagine:** `LIMITE_MASSIMO` oltre 999 richiede di cambiare anche la regex `LIMITE` di
  `parametri.ts`. Il default di `limit` fa parte del contratto: non si cambia in v1.

---

## 6. Test e tipi

```bash
npm test     # 433 test al 26/09/2026 (279 in tests/api-v1/); controllare anche "# skipped 0"
TZ=Asia/Kathmandu node --experimental-strip-types --disable-warning=ExperimentalWarning \
  --import ./tests/supporto/registra-risolutore.mjs --test tests/api-v1/<file>.test.ts
npx --no-install tsc --noEmit -p tsconfig.json   # 51 errori preesistenti al 25/09/2026, nessuno in api-v1
```

- **Resolve hook** (`tests/supporto/risolutore-ts.mjs`, registrato da `registra-risolutore.mjs` con
  `module.register`): i moduli di `src/` importano senza estensione (tsc rifiuta `.ts` negli import,
  TS5097) e Node in ESM non aggiunge estensioni. L'hook interviene solo su `ERR_MODULE_NOT_FOUND`, per
  specificatori relativi senza estensione importati da un `.ts`, e riprova con `.ts` e poi con
  `/index.ts`. Nei file di test gli import hanno `.ts`.
- **`TZ=Asia/Kathmandu`** (+05:45, niente ora legale): qualunque uso dell'ora locale rompe i test.
- **Vincoli di `--experimental-strip-types`:** niente `enum`, `namespace`, parameter properties;
  import di soli tipi con `import type` separato. I moduli che importano `supabase.ts` o
  `supabase-bandi.ts` non si caricano sotto `node` (client creato all'import): per questo la logica
  sta in moduli puri e la `FonteDati` è iniettata.
- `tests/` è fuori da `tsconfig.json`: tsc non controlla i test; i `.astro` non sono controllati affatto.

| File | Copre |
|---|---|
| `contratto.test.ts` | validatore JSON Schema: esempi OpenAPI, output dei mapper, risposte del gestore (200 e problem), enum, niente URL esterni |
| `gestore.test.ts` | flusso HTTP completo con fonte finta: next/has_more, post-filtro, 400/404/405/429/500/503, STALE, 304, HEAD, feed, id oltre int4 |
| `http.test.ts` | problem+json (`instance` assoluto senza query), codici e status, `no-store`, ETag/`If-None-Match`, 200 e 304 con gli stessi header, preflight CORS |
| `filtri.test.ts`, `parametri.test.ts`, `cursore.test.ts` | piano delle query, validazione, cursore |
| `tempo.test.ts`, `testo.test.ts`, `url.test.ts` | date e fusi (anche cambiando `TZ` a runtime), testo e ReDoS, URL |
| `mappa-*.test.ts`, `riferimenti.test.ts` | DTO, autore (non fuga), regole di scadenza e stato, riferimenti e loro cache |
| `feed.test.ts`, `openapi.test.ts`, `documentazione.test.ts` | JSON Feed/RSS, coerenza della specifica, ancore della pagina |
| `limitatore.test.ts`, `semaforo.test.ts`, `cache.test.ts` | protezione del processo |
| `rotte.test.ts`, `purezza.test.ts`, `robots.test.ts` | esportazioni delle rotte, select, purezza, robots.txt |
| `tests/estrazioni/*` | parità di `slugInterpello` con Python, `stato-bando` |
| `tests/intestazioni-inoltro.test.ts` | `verificaIntestazioniInoltro` (header accettati e rifiutati). Il collegamento in `middleware.ts` non è testato (il middleware non si carica sotto node): si verifica con `curl` (§7) |

**Verifica end-to-end in locale:** `npx astro build`, non `npm run build`: il `prebuild`
(`scripts/copy-credentials.js`) esce con errore se manca `src/pages/api/tts/google-credentials.json`.
Poi `PORT=4399 HOST=127.0.0.1 node dist/server/entry.mjs` e `curl`.

---

## 7. Operatività

### Configurazione

| Variabile | Default | Effetto |
|---|---|---|
| `API_V1_FIDUCIA_IP` | `cloudflare` | da quali header ricavare l'IP del client (sotto) |
| `API_V1_RL_CAPACITA` | `60` | gettoni per client |
| `API_V1_RL_RICARICA` | `1` | gettoni ricaricati al secondo |

- Si leggono dall'ambiente del processo e, in mancanza, dal `.env` presente al momento del build.
  Servono un riavvio (o un nuovo build).
- Solo interi positivi da 1 a 9.999.999: la ricarica non può scendere sotto 1/s. Un valore non valido
  fa tornare **in silenzio** al default (solo una `API_V1_FIDUCIA_IP` sconosciuta produce un log).
- Il valore effettivo si legge nel log alla **prima richiesta a `/api/v1`** dopo l'avvio (non
  all'avvio del processo), su stderr:
  `[api-v1] configurazione: fiducia_ip=<modalità>, rate_limit=<capacità> (+<ricarica>/s)`.

**Modalità di fiducia** (`limitatore.ts`):
- `cloudflare`: si prende l'ultimo IP valido di `X-Forwarded-For` (senza IP validi: `clientAddress`).
  Se appartiene ai range di Cloudflare e `CF-Connecting-IP` è un IP singolo e valido, si usa
  quest'ultimo; altrimenti l'ultimo hop. `CF-Connecting-IP` non è mai letto senza questo controllo.
  Senza alcun IP la richiesta finisce nel secchio condiviso `sconosciuto`. IPv6 limitato per /64.
- `nginx`: `X-EduNews24-Client-IP` impostato da nginx; con header assente, multiplo o non valido si
  torna all'algoritmo `cloudflare`. Da usare solo se Node è raggiungibile esclusivamente da nginx e
  ogni `location` imposta l'header.
- `diretta`: usa `clientAddress`, cioè in Astro 5.4.2 il primo valore di `X-Forwarded-For`,
  falsificabile dal client: in produzione permetterebbe di aggirare il limite. Solo sviluppo.

Limiti, semaforo e cache sono **per processo** e si azzerano al riavvio.

### Guardia sugli header di inoltro (tutto il sito)

Astro 5.4.2 costruisce l'URL della richiesta (e sceglie la rotta) da `X-Forwarded-Host/Proto/Port`
senza validarli. La prima istruzione di `onRequest` in `src/middleware.ts` rifiuta con 400 text/plain,
`no-store`, `noindex` le richieste con quegli header malformati, e con `Host` malformato quando manca
`X-Forwarded-Host`.

Limiti noti, verificati in produzione:
- Cloudflare e nginx oggi **lasciano passare** `X-Forwarded-Host` del client: la guardia è l'unica
  difesa finché non si fa il passo 1 sotto. `X-Forwarded-Proto` invece viene sovrascritto a monte.
- Se l'header rende l'URL non analizzabile (es. `X-Forwarded-Port: 443x`), `new Request()` fallisce
  prima del middleware: l'adapter risponde 500 `Internal Server Error` senza `Content-Type` né
  `Cache-Control` e scrive lo stack nel log a ogni richiesta. Non va in cache, ma fa rumore; il passo 1
  elimina anche questo caso.

### Barriere esterne (da configurare fuori dal repo)

Ordine consigliato:

1. **Scartare gli header a monte.** In nginx, in ogni `location` con `proxy_pass` verso Node:
   ```nginx
   proxy_set_header X-Forwarded-Host "";
   proxy_set_header X-Forwarded-Port "";
   ```
   oppure una Transform Rule di Cloudflare che rimuove i due header. Verifica: con
   `-H "X-Forwarded-Host: edunews24.it/x?"` la risposta torna 200.
2. **Cache Rule di Cloudflare** (la guardia è in produzione, quindi si può fare):
   `http.host eq "edunews24.it" and (http.request.uri.path eq "/api/v1" or starts_with(http.request.uri.path, "/api/v1/")) and not starts_with(http.request.uri.path, "/api/v1/feeds/")`
   → eligible for cache, Edge TTL dall'origin, chiave con la query ordinata ("Sort query string").
   Seconda regola su `/api/v1/feeds/` con chiave senza query. **Mai** regole su `/api/*` fuori dalla v1:
   `/api/articlestest` riflette l'Origin senza `Vary`. Effetti da sapere:
   - le risposte servite dall'edge non arrivano a Node, quindi il rate limit applicativo conta solo i
     miss: il punto 3 diventa il limite per IP sugli hit, e la frase della documentazione pubblica
     secondo cui anche le risposte dalla cache consumano il limite va rivista;
   - l'edge non mette la data nella chiave: dopo la mezzanotte di Roma lo `status` di selezione e
     bandi può restare quello del giorno prima per al massimo `s-maxage` + `stale-while-revalidate`
     (10 minuti negli elenchi, 30 nei dettagli).
3. **Rate limit su Cloudflare**: Free, 1 regola `starts_with(http.request.uri.path, "/api/v1")`,
   50 richieste ogni 10 s per IP (la risposta di blocco è HTML, già documentata come fuori
   contratto); Pro+, 300/min con blocco di 10 minuti e risposta JSON personalizzata.
4. **nginx** (facoltativo): `limit_req` 5 r/s burst 30 sulla `location ^~ /api/v1`, con
   `set_real_ip_from` sui range Cloudflare, `real_ip_header CF-Connecting-IP`, `proxy_read_timeout 15s`
   e una `@location` che risponde 429 in problem+json con `Retry-After` e `X-Robots-Tag: noindex`.
   Configurazione completa nel §8.2 del piano.
5. **Origin vincolato alla zona** (Authenticated Origin Pulls zonale, Tunnel o header segreto): senza,
   chi conosce l'IP dell'origin salta le regole di Cloudflare.
6. **Aggiornare Astro** a ≥ 5.15.5 (CVE-2025-64525, GHSA-hr2q-hp5q-x767) e insieme `@astrojs/node` a
   una versione con la correzione GHSA-qh8j-hqjv-7m4x (porta malformata che fa andare in crash
   l'adapter), con una verifica completa del sito. È il rimedio definitivo del problema che la guardia
   e il punto 1 mitigano; la guardia resta comunque.

### Controlli dopo un deploy

```bash
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" https://edunews24.it/api/v1   # 200 JSON
curl -s "https://edunews24.it/api/v1/articles?limit=1" | head -c 300                  # data/meta/links
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Forwarded-Host: edunews24.it/x?" https://edunews24.it/api/v1
# 400 (guardia); 200 dopo il passo 1 delle barriere
```

Poi il log: la riga `[api-v1] configurazione` compare dopo la prima richiesta.

---

## 8. Aperti

- **Annuncio pubblico** (voce in `src/lib/api-catalog.ts`, `<link rel="alternate">` in
  `Layout.astro`, pagina docs in `sitemap-pagine.xml`): in attesa dei termini d'uso. Oggi
  `/sviluppatori/api#termini` contiene una nota provvisoria datata 21/09/2026.
- **Falle di sicurezza preesistenti**, fuori dal perimetro dell'API e da trattare a parte (servono
  deroghe al CLAUDE.md o l'intervento del proprietario del DB):
  - cancellazioni senza autenticazione: `DELETE` su `/api/articles/[id]`, `/api/podcasts/[id]`,
    `/api/news/[id]` e `POST /api/articles/delete`;
  - `/api/profiles/update-permissions` senza autenticazione (bypass commentato);
  - `/api/logs` pubblico;
  - bozze, `profiles` e `api_access_requests` leggibili con la chiave anon;
  - `/api/interpelli` che espone 7,7 MB di testo integrale;
  - injection nel `.or()` di `/api/search`;
  - proxy news senza autenticazione (`news/publish`, `reconstruct`, `reset-generation`), SSRF in
    `upload-from-url.ts`, `API_SECRET_KEY` che non protegge nulla quando manca (corretto per
    `indexnow-notify.ts`, da verificare altrove). Gli endpoint `eu-funding/refresh*`, che senza
    autenticazione avviavano un processo Python e scrivevano nel repo anche via GET, sono stati
    rimossi insieme alla sezione `/eu-funding` (ora 410).

  Dettagli e rimedi nella sezione finale del piano.
- **Slug duplicati della selezione** (id 3740/3741, 12540/18661): la scheda sul sito risponde 404 per
  `.maybeSingle()` in `src/pages/selezione-personale/[slug].astro`, quindi anche l'URL dell'API porta
  a un 404. Correzione lato sito: `.order('id', { ascending: false }).limit(1)`.
- **`getCategoryHex('constructor')`** (`src/lib/category-colors.ts`) restituisce la funzione `Object`
  (chiave del prototipo): `riferimenti.ts` lo aggira con `CHIAVI_COLORE` (solo chiavi proprie) e
  `sezioni.ts` passa solo chiavi fisse; gli altri chiamanti del sito no.
- **`npm run build` in locale** fallisce sul `prebuild` senza
  `src/pages/api/tts/google-credentials.json` (preesistente).
