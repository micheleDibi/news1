# Contratto del DB bandi

Documento di riferimento per chi legge il database Supabase dei bandi con la chiave anonima.
È autosufficiente: non richiede altri documenti e non rimanda a piani interni.

Destinatari: le due applicazioni che consumano il DB in sola lettura — **edunews24.it**
(di seguito «news1», che è anche il produttore dei dati) e **BandoFit**. Entrambe usano la
stessa `anon key` e vedono lo stesso modello pubblico.

Versione del contratto: **v11**. Ogni modifica incompatibile è preceduta da un avviso scritto.

---

## 1. Principio

1. Il **modello pubblico** descritto qui è il contratto per entrambi i consumatori.
2. La verità sullo stato di un bando è la colonna calcolata **`stato_effettivo`** della vista
   **`bando_pubblico`**. La colonna persistita `bando.stato_bando` viene riallineata da un job
   orario, ma **non è la verità**: fra una transizione e il giro del job i due valori possono
   divergere, e in quella finestra vale `stato_effettivo`.
3. Gli `id` dei bandi e quelli dei cataloghi **non cambiano mai e non vengono mai riusati**.
   Nessuna riga di `bando` viene cancellata e la sequence non viene mai riavviata.
4. Gli **slug dei bandi pubblicati sono congelati**. Quando uno slug cambia, o quando un bando
   viene fuso in un altro, la mappa per risalire alla riga corrente è leggibile
   (`bando_slug_storico`, `bando_fusione`).
5. Tutte le regole di data usano il calendario di **Roma** (`Europe/Rome`). «Oggi» è sempre
   `(now() at time zone 'Europe/Rome')::date`.
6. **Nessuna funzione del DB è eseguibile con la anon key** salvo le tre che la vista stessa
   richiede (`bando_stato_effettivo`, `dominio_di`, `bando_host_aggregatore`) e quelle di
   `pg_trgm`. Ogni RPC del dominio bandi ha `REVOKE EXECUTE` da `PUBLIC`, `anon` e
   `authenticated` più una guardia sul ruolo: i consumatori **leggono e basta**.
7. **Nessun link ad aggregatori** esce dalle colonne leggibili con la anon key. Dove il valore
   grezzo puntava a un aggregatore, la colonna pubblica vale `NULL`.

---

## 2. Glossario dei nomi

Questi nomi sono definitivi e valgono nelle migrazioni, nel codice e in questo documento.

| Nome | Che cos'è |
|---|---|
| `bando_pubblico` | la vista di lettura (l'unico oggetto da interrogare dalla fase (c) in poi) |
| `stato_effettivo` | lo stato calcolato alla lettura; la verità |
| `stato_bando` | lo stato persistito, riallineato dal job orario |
| `pubblicato` / `pubblicato_at` | il flag di pubblicazione e il suo istante |
| `ultimo_cambiamento_at` | avanza **solo** per modifiche pubbliche; mai per re-scrape o controlli |
| `ultimo_controllo_at` | ultimo controllo della freschezza (da `bando_controllo`) |
| `fonte_ufficiale_url` / `_host` / `_tipo` / `_stato` / `_verificata_at` | l'unico link «ufficiale»; **non esiste** nessuna colonna «link_ufficiale» |
| `ricerca` | colonna `tsvector` generata, percorso unico della ricerca full-text |
| `bando_link` | allegati e link di un bando (non `bando_links`) |
| `bando_evento` | registro degli eventi (non `bando_eventi`) |
| `bando_fusione` | mappa doppione → master (non `bando_master`) |
| `bando_slug_storico(slug, bando_id, esito, motivo, created_at)` | storico degli slug |
| `bando_controllo` | tabella interna di servizio; ad `anon` sono concesse **solo** le colonne `bando_id` e `ultimo_controllo_at` |
| `dominio_ufficiale` | whitelist/blocklist dei domini; **tabella interna**, non leggibile con la anon key |
| `pipeline_run`, `fonte_run`, `pipeline_lock` | tabelle interne della pipeline |
| `apertura_automatica` / `chiusura_automatica` | i tipi di evento del job orario (non «transizione_automatica») |
| `bando_link.ultimo_visto_at` | ultimo 2xx **del link** |
| `bando_controllo.ultimo_visto_in_fonte_at` | ultima presenza **nel listing della fonte** — colonna diversa dalla precedente e non leggibile con la anon key |

Le priorità interne sono sempre sulla scala **0-100**.

---

## 3. La vista `bando_pubblico`

Definita `CREATE VIEW … WITH (security_invoker = true)`, con `GRANT SELECT` ad `anon`, e filtrata
`WHERE pubblicato`. Essendo `security_invoker`, la RLS di `bando` resta il guardiano: la vista non
scavalca nessun permesso e resta inlinabile dal planner (gli embed PostgREST e `count=exact`
funzionano come su una tabella).

**La vista contiene i soli bandi pubblicati e non fusi.** Un `id` o uno slug che non si trova qui
va risolto su `bando_fusione` / `bando_slug_storico` (§6).

| colonna | tipo | semantica |
|---|---|---|
| `id` | integer | chiave stabile, mai riusata |
| `slug` | text | URL pubblico `https://edunews24.it/bandi/<slug>`; congelato dopo la pubblicazione |
| `titolo`, `titolo_breve`, `descrizione_breve` | text | testi editoriali |
| `contenuto` | jsonb `{sections: […]}` | sezioni; le FAQ hanno forma `{q, a:{segments}}`. **Mai una stringa**: le righe salvate come stringa JSON doppio-codificata sono esposte come `NULL` |
| `livello` | text | `flash_bando` \| `guida_bando` |
| `ente_erogatore`, `area_geografica` | text | |
| `tematica` | text[] | |
| `data_pubblicazione`, `data_apertura`, `data_scadenza` | date | date della fonte. `data_pubblicazione` è NULL sul ~92 % delle righe e **non verrà riempita da nessun backfill** |
| `ora_apertura`, `ora_scadenza` | time (Roma) | NULL se la fonte non indica un'ora |
| `data_pubblicazione_verificata`, `data_apertura_verificata`, `data_scadenza_verificata` | boolean | `true` solo se la data ha una prova su dominio ufficiale, registrata come evento |
| `importo_totale_eur`, `importo_max_per_progetto_eur` | bigint | |
| `stato_bando` | text | stato persistito: `aperto` \| `chiuso` \| `in apertura prossimamente` (+ `sospeso` \| `revocato` solo dopo la migrazione 06, cioè dopo il rilascio R0-a); riallineato dal job entro 65 minuti |
| `stato_bando_verificato` | boolean | l'ultima transizione ha una prova ufficiale |
| **`stato_effettivo`** | text | **la verità**, calcolata alla lettura (§4) |
| `tipologia_bando_id`, `modalita_erogazione_id`, `programma_id` | integer | FK ai cataloghi; gli embed `tipologie_bando(id,nome)`, `modalita_erogazione(id,nome)`, `programmi(id,nome)` funzionano |
| `fonte_ufficiale_stato` | text | `trovata` \| `in_verifica` \| `non_trovata` |
| `fonte_ufficiale_tipo` | text | `ente` \| `portale_pubblico` \| NULL. Sono gli **unici due valori**: «atto» non è un valore della colonna ma il flag `fonte_ufficiale_e_atto`, e un calendario non vale mai `trovata` (al massimo `in_verifica`, con tipo NULL) |
| `fonte_ufficiale_e_atto` | boolean | `true` se la fonte ufficiale è il PDF dell'atto sul dominio dell'ente **ed è a sua volta pubblicabile**. La vista è `security_invoker`, quindi il flag passa dalla RLS di `bando_link`: su un atto non ancora verificato la anon key legge `false`. È voluto — il flag accende un pulsante pubblico — ma non è una proprietà della sola fonte |
| `fonte_ufficiale_url`, `fonte_ufficiale_host` | text | l'unico link «ufficiale»; mai un aggregatore; NULL se la fonte non è stata trovata |
| `fonte_ufficiale_verificata_at` | timestamptz | |
| `ultimo_controllo_at` | timestamptz | da `bando_controllo`, come sottoquery scalare |
| `link_candidatura`, `link_candidatura_source`, `allegati` | text, text, jsonb | **deprecate**: presenti fino alla fase (d). `link_candidatura` è NULL se puntava a un aggregatore; `allegati` è un array di `{label, url, tipo}` (chiavi fisse fino alla (d)). Usare `bando_link` |
| `titolo_raw`, `descrizione_raw` | text | **deprecate** (fino alla (d)). `descrizione_raw` è NULL ovunque; per la ricerca usare `ricerca` |
| **`ricerca`** | tsvector | colonna generata `to_tsvector('italian', titolo ‖ titolo_breve ‖ descrizione_breve ‖ titolo_raw)` STORED. Filtro consigliato: `ricerca=wfts(italian).<termini>` — un solo `@@` per riga invece dei cinque `to_tsvector` per riga della ricerca a più rami, che è la causa dei timeout 57014 |
| **`stato_processing`** | varchar | **compatibilità fino alla (d)**: costante `'completed'` (tutte le righe della vista lo sono), così il predicato `stato_processing=eq.completed&slug=not.is.null` resta valido tale e quale |
| **`link_bando`** | text | **compatibilità fino alla (d)**: il valore grezzo se l'host non è un aggregatore, altrimenti NULL. Usare `fonte_ufficiale_url` |
| `pubblicato_at`, `created_at` | timestamptz | `created_at` è il riferimento degli alert quando `data_pubblicazione` è NULL |
| `ultimo_cambiamento_at` | timestamptz | avanza solo per modifiche pubbliche (testi, date, stato, fonte, allegati); mai per un re-scrape o un controllo. Valore iniziale = vecchio `updated_at` |

**Assenti per scelta**, e non torneranno: `raw_data`, `hash_bando`, `fonte_id`,
`confidence_score`, `rejection_reason`, `canonical_key`, `fonti_aggiuntive`, `updated_at`,
`bando_master_id`, e tutte le colonne di controllo del monitor.

Fino alla fase (d) la tabella `bando` resta leggibile con la anon key con tutte le colonne di
oggi e la RLS attuale. Nella (d) escono dalla vista `stato_processing`, `link_bando`,
`link_candidatura`, `link_candidatura_source`, `allegati`, `titolo_raw`, `descrizione_raw`.

---

## 4. Stati e calcolo di `stato_effettivo`

Gli stati sono cinque: `aperto`, `chiuso`, `in apertura prossimamente`, `sospeso` (può riaprire),
`revocato` (terminale; si esce solo con un evento `annullamento_revoca`).

Con `oggi` e `ora` = data e ora di Roma **all'istante della lettura**, nell'ordine:

1. `stato_bando = 'revocato'` → **`revocato`**
2. `stato_bando = 'sospeso'` → **`sospeso`**
3. scadenza passata (`data_scadenza < oggi`, oppure `= oggi` con `ora_scadenza` già passata) →
   **`chiuso`**
4. `stato_bando = 'in apertura prossimamente'` con `data_apertura_verificata = true` e apertura
   raggiunta (data, e ora se presente) → **`aperto`**
5. altrimenti → **`stato_bando`**

Conseguenze da conoscere:

- Nel **giorno di scadenza senza `ora_scadenza`** il bando è ancora `aperto` (regola identica a
  quella in uso oggi).
- Un `chiuso` persistito **non riapre alla lettura**: riapre solo con un evento `proroga` o
  `riapertura` verificato, che riscrive stato e date.
- `sospeso` non viene **mai** chiuso d'ufficio dalla scadenza.
- Chi ragiona solo per date, ignorando `ora_scadenza`, diverge dalla vista al massimo di alcune
  ore nel giorno di scadenza.

**Filtri consigliati.** «Non chiusi»: `stato_effettivo=in.(aperto,"in apertura prossimamente")`
(le virgolette sono facoltative: va bene anche `in.(aperto,in%20apertura%20prossimamente)`).
«Chiusi»: `stato_effettivo=eq.chiuso`. `sospeso` e `revocato` **non sono né aperti né chiusi** e
non devono finire in nessuno dei due segmenti.

**Job orario** (`5 * * * *`): chiude `WHERE data_scadenza < oggi AND stato_bando IN
('aperto','in apertura prossimamente')`, apre `WHERE stato_bando = 'in apertura prossimamente'
AND data_apertura_verificata AND data_apertura <= oggi`; **non tocca mai `sospeso` né
`revocato`**. Non esegue UPDATE diretti: registra un evento `chiusura_automatica` /
`apertura_automatica` per ogni riga toccata, e l'evento applica il cambiamento. Latenza massima
dall'istante in cui la vista cambia (data **o ora**) all'allineamento di `stato_bando`: **65
minuti**.

`stato_effettivo` non è indicizzabile (dipende da `now()`): regge sul corpus pubblicato, che è
dell'ordine di 2 100 righe.

---

## 5. Allegati e link: `bando_link`

Tabella con `GRANT SELECT` di colonna ad `anon` e RLS che espone **solo le righe `pubblicabile`
di bandi pubblicati**.

Colonne concesse: `id`, `bando_id`, `url`, `dominio`, `tipo`, `etichetta`, `content_type`,
`ultimo_visto_at`. Tutte le altre (fra cui `url_prova`, `esito_http`, `impronta_pagina`,
`pubblicabile`, `origine`) **non sono concesse**: un `select=*` su questa tabella risponde
**42501**, ed è voluto. Selezionare sempre le colonne per nome.

`tipo` ∈ `pagina_bando` | `atto` | `allegato` | `candidatura` | `faq` | `graduatoria` |
`portale` | `altro`.

**Garanzie.** Ogni riga leggibile ha risposto 2xx all'ultimo controllo e compare nell'HTML della
pagina di riferimento. La garanzia è data sia dal worker sia dal database: due CHECK negano
`pubblicabile = true` senza un `esito_http` 2xx e senza la data in cui il link è stato trovato
nella fonte, e un trigger nega la pubblicabilità di qualunque riga su un dominio aggregatore.

**CTA consigliata**, in ordine: una riga `tipo='candidatura'` → altrimenti
`fonte_ufficiale_url` → altrimenti una riga `tipo='portale'`.

Upsert lato produttore su `(bando_id, url_normalizzato)`; `url` è immutabile.

### Denylist degli aggregatori

Sono i domini che non compaiono mai in una colonna leggibile con la anon key. Al momento della
pubblicazione di questo documento:

`obiettivoeuropa.com`, `fasi.eu`, `europafacile.net`, `contributiregione.it`,
`finanziamentinews.it`, `bandi.it`, `infobandi.it`, `ticonsiglio.com`, `contributieuropa.com`,
`first.aster.it` — **sottodomini compresi**.

Alla stessa blocklist appartengono i domini social, video e di messaggistica
(`facebook.com`, `instagram.com`, `x.com`, `twitter.com`, `linkedin.com`, `threads.net`,
`pinterest.com`, `tiktok.com`, `youtube.com`, `youtu.be`, `vimeo.com`, `t.me`, `telegram.me`,
`wa.me`, `whatsapp.com`): non sono fonti ufficiali e non vengono mai proposti come CTA.

L'elenco vive nella tabella interna `dominio_ufficiale` (righe `tipo='aggregatore'`); ogni
modifica viene annunciata con un avviso.

---

## 6. Eventi, fusioni e storico degli slug

### 6.1 `bando_evento`

Registro **immutabile**: correzioni e ritiri sono righe nuove con `riferisce_a` che punta
all'evento corretto o ritirato. Nemmeno il ruolo di servizio può cancellare una riga.

RLS per `anon`: `USING (cursore IS NOT NULL)`. Il cursore viene assegnato solo agli eventi di
bandi pubblicati, fusi o ritirati, e **una volta assegnato non viene mai revocato** — così
l'evento `fusione` di un doppione resta leggibile anche dopo che il doppione è uscito dalla vista.

Colonne concesse: `id`, `bando_id`, `tipo`, `origine`, `campo`, `valore_prima`, `valore_dopo`
(jsonb), `data_evento` (date), `rilevato_at`, `pubblicato_at`, `cursore`, `in_aggiornamenti`,
`verificato`, `url_prova`, `dominio_prova`, `applicato`, `applicato_at`, `riferisce_a`.
Le colonne interne (`citazione`, `impronta_pagina`, `gate`, `confidenza`, `metodo`, `run_id`,
`leggibile`) non sono concesse: anche qui `select=*` risponde **42501**.

Semantica delle colonne meno ovvie:

- `origine` ∈ `cron` | `worker` | `pipeline` | `redazione`.
- `cursore` (bigint): **monotono anche con scrittori concorrenti**. Il trigger che lo assegna
  prende un advisory lock prima di `nextval`, quindi un cursore minore non diventa mai visibile
  dopo uno maggiore. Un rollback può lasciare buchi nella numerazione: sono innocui con un
  filtro `cursore=gt.<ultimo>`.
- `in_aggiornamenti`: `true` = evento da mostrare in un box «Aggiornamenti». È `false` per le
  transizioni automatiche del job orario e per gli eventi tecnici.
- `verificato`: `true` solo se il dominio della prova è di tipo `ente`, `portale_pubblico` o
  `pattern` con confidenza ≥ 0,8. Mai per domini soltanto dedotti.
- `url_prova`, `dominio_prova`: **mai un aggregatore**. Un trigger azzera la prova e pone
  `verificato = false` se il dominio è in denylist.
- `applicato` / `applicato_at`: `false` = evento verificato ma **non ancora riversato nella
  colonna**. Fra la fase (b) e il rilascio R0 questo è il caso di `sospensione` e `revoca`.

**Tipi che possono ricevere un cursore (quindi pubblici)**: `pubblicazione`,
`apertura_automatica`, `chiusura_automatica`, `apertura`, `chiusura`, `proroga`, `riapertura`,
`rettifica`, `sospensione`, `revoca`, `annullamento_revoca`, `graduatoria`, `esito`, `faq`,
`nuovo_allegato`, `fonte_ufficiale_verificata`, `data_verificata`, `fusione`, `separazione`,
`cambio_slug`, `ritiro`, `correzione_redazionale`.

**Tipi sempre interni** (mai un cursore, mai leggibili): `segnale_fonte`, `sparito_dalla_fonte`,
`elaborazione_bloccata`, `fonte_ufficiale_non_trovata`, `possibile_doppione`,
`preavviso_collegato`.

**Sincronizzazione.** Si legge per cursore crescente:

```
GET /rest/v1/bando_evento?select=id,bando_id,tipo,campo,valore_prima,valore_dopo,data_evento,rilevato_at,pubblicato_at,cursore,in_aggiornamenti,verificato,url_prova,dominio_prova,applicato&cursore=gt.<ultimo>&order=cursore.asc&limit=1000
```

Come cintura di sicurezza il consumatore rilegge da `<ultimo> − 100` e deduplica per `id`.

**Latenza massima rilevazione → leggibilità**: transizioni del job orario **≤ 65 minuti** dopo
la mezzanotte di Roma (la vista mostra già `chiuso` da mezzanotte); eventi del monitor **≤ 12
ore** nella configurazione in uso (≤ 24 h nella configurazione economica, ≤ 6 h in quella
massima). Il valore corrente è pubblicato in `pipeline_run` e in questo documento, e cambia solo
con avviso. Un consumatore che sincronizza una volta al giorno somma il proprio intervallo.
Durante la messa in ombra, un evento diventa leggibile alla data di attivazione del suo tipo,
indicata da `pubblicato_at`.

### 6.2 `bando_fusione`

`bando_fusione(bando_id, slug_originale, master_id, master_slug, motivo, fuso_at)`, leggibile su
tutte le righe. Da un `bando_id` o da uno slug salvato prima della fusione si risale al master;
la riga resta finché esiste il master; le catene vengono appiattite dal produttore, quindi
`master_id` è sempre il master corrente.

**Regola per i consumatori.** La vista contiene solo i pubblicati non fusi; un doppione fuso ha
`pubblicato = false` (e resta `completed` con il suo slug fino alla fase (d)). Le fusioni
continuano anche dopo la fase (c). Perciò:

- ogni **miss** per `id` o per `slug` va risolto su `bando_fusione` / `bando_slug_storico` — una
  richiesta in più **solo sul miss**;
- le tabelle che conservano un `bando_id` o uno slug vanno **rimappate in modo incrementale**
  leggendo per cursore gli eventi `fusione`, il cui `valore_dopo` è `{master_id, master_slug}`.

Attenzione a un vincolo di unicità lato consumatore: se una tabella ha un UNIQUE del tipo
`(utente, azienda, bando_id)`, la riga del doppione va **eliminata**, non aggiornata al master,
altrimenti la rimappatura viola il vincolo.

### 6.3 `bando_slug_storico`

`bando_slug_storico(slug, bando_id, esito, motivo, created_at)`, leggibile su tutte le righe.

- `esito = '301'` → `bando_id` è il **master corrente**; non esistono catene.
- `esito = '410'` → bando **ritirato**, solo su richiesta scritta del committente (obbligo legale
  o richiesta dell'ente): nessuno step della pipeline emette un ritiro da solo.
- `esito = 'annullato'` → riga chiusa da una separazione.

Uno slug con esito `301` o `410` non torna corrente finché la riga ha quell'esito.

---

## 7. Requisiti del rilascio difensivo R0

R0 è il rilascio che un consumatore fa **prima** che il DB cambi, per non rompersi. È in due
parti, perché possono andare in produzione in momenti diversi.

### R0-a — nessuna dipendenza dal DB; è la sola precondizione della migrazione 06

1. **Badge neutro** per ogni `stato_bando` diverso da `aperto` / `chiuso` /
   `in apertura prossimamente` (oggi un valore sconosciuto verrebbe mostrato come «In apertura»,
   che per un bando revocato è falso).
2. **Esclusione di `sospeso` e `revocato` da entrambi i segmenti** dell'elenco («aperti» e
   «chiusi») e dai candidati degli alert.
3. Il filtro `stato` **non deve rispondere 400** per valori sconosciuti.
4. Gli snapshot dei preferiti devono essere **tolleranti**: un miss non deve rompere la pagina.

Finché R0-a non è in produzione, la migrazione 06 (CHECK a 5 valori) resta bloccata.

### R0-b — solo dopo conferma scritta che le migrazioni 01 e 02 sono applicate

1. Ricerca full-text su **`ricerca=wfts(italian).<termini>`** al posto dell'`or` a più rami.
   `ricerca` è una colonna generata di **`bando`** e nasce con la 01.
2. Risoluzione dei **miss**: per slug su `bando_slug_storico`, per id su `bando_fusione`.
   Entrambe le tabelle nascono con la 02.
3. Lettura di **`fonte_ufficiale_*`**: colonne di `bando`, dalla 01.

**`stato_effettivo` non è in questo elenco, ed è la correzione più importante di questo
paragrafo.** Dopo 01 e 02 esiste soltanto la *funzione* `bando_stato_effettivo(...)` (02, sezione
1): la *colonna* `stato_effettivo` nasce nella vista `bando_pubblico`, cioè con la **05**, e il
GRANT EXECUTE ad `anon` per quella funzione sta nell'allowlist della 05. Un consumatore che
seguisse alla lettera la vecchia versione di questo elenco metterebbe `stato_effettivo` nella
select su `bando` e riceverebbe 42703 su **ogni** richiesta — esattamente il 502 che il paragrafo
qui sotto dice di voler evitare. `stato_effettivo` si legge **solo** su `bando_pubblico`, e quindi
appartiene alla fase (c), non a R0-b.

R0-b **non può** essere rilasciato prima delle migrazioni: senza la colonna `ricerca` e senza
`bando_fusione` le richieste risponderebbero 42703 / PGRST205, e un consumatore che traduce gli
errori PostgREST in 5xx restituirebbe 502.

---

## 8. Garanzie di prestazione e compatibilità

**Timeout.** Il ruolo `anon` ha `statement_timeout = 3 s`. Un superamento si manifesta come
errore PostgREST `57014`.

**Indici utilizzabili.** La vista è `security_invoker` e inlinabile: i filtri su `stato_bando`,
`data_scadenza`, `data_apertura`, le FK dei cataloghi, gli importi, le junction (`!inner` con
alias) e gli ordinamenti `<colonna>.desc.nullslast, id.asc` usano gli indici della tabella base.
`count=exact` è ammesso.

**Full-text search.** La colonna generata `ricerca` ha un indice GIN, ma **sotto RLS quell'indice
non è utilizzabile con la anon key**: l'operatore `@@` non è LEAKPROOF, quindi il planner applica
prima il filtro della policy e non può usare l'indice. Il GIN esiste per le letture del ruolo di
servizio. **La garanzia offerta ai consumatori è il tempo, non il piano di esecuzione**: una
ricerca su `ricerca` risponde sotto i 300 ms sul corpus pubblicato. Il guadagno rispetto alla
ricerca a cinque rami è comunque reale: un solo `@@` per riga invece di cinque `to_tsvector` per
riga. Un `or` a più rami `<colonna>.wfts(italian)` su colonne `text` resta un Seq Scan con
`to_tsvector(default_config, colonna)` per riga, esattamente come oggi: nessuna regressione e
nessun miglioramento.

**`stato_effettivo`** non è indicizzabile perché dipende da `now()`. La funzione che lo calcola è
`LANGUAGE sql` e quindi inlinata dal planner: non ha costo per riga.

**Compatibilità delle richieste esistenti.** Le otto richieste elencate al §12 restano valide
**senza alcuna modifica su `bando`** fino alla fase (d). **Sulla vista** (fase (c)) sono valide
**con il solo cambio del nome della tabella**, perché fino alla (d) la vista espone anche
`stato_processing` (costante `'completed'`) e `link_bando` (NULL se l'host è un aggregatore).

**Prima della fase (d) un consumatore deve**:

1. togliere dalla select di dettaglio `descrizione_raw`, `titolo_raw`, `link_bando`,
   **`link_candidatura`**, **`link_candidatura_source`** e **`allegati`** (tutte rimosse dalla vista dalla migrazione 07:
   lasciarle produce 42703 su dettaglio, e a cascata su ogni funzione che riusa quella select) e
   leggere CTA e allegati da `bando_link`;
2. passare la ricerca a `ricerca=wfts(italian)`;
3. togliere `stato_processing=eq.completed&slug=not.is.null` dai propri predicati (la vista è già
   filtrata e dopo la 07 la colonna non esiste più);
4. leggere `stato_effettivo`;
5. leggere `fonte_ufficiale_*`.

**`max-rows` di PostgREST = 1000.** Una richiesta senza `limit` non restituisce mai più di 1000
righe. Nessuna migrazione fa crescere oltre quella soglia l'insieme dei candidati degli alert:
non c'è backfill di `data_pubblicazione` e nessuna riga viene ricreata dalle migrazioni.

**Cataloghi** (`regioni` 20 righe, `settori`, `beneficiari`, `codici_ateco`, `tipologie_bando`,
`modalita_erogazione`, `programmi`): **id e conteggi invariati**, nessuna rinumerazione, nessuna
pseudo-regione. Chi usa `count(regioni)` come denominatore di un punteggio «nazionale» può
continuare a farlo.

---

## 9. Dichiarazioni

Cose che è meglio sapere prima che succedano.

1. **`data_pubblicazione`**: nessuna migrazione e nessun lotto di backfill la scrive. Il worker
   la scrive solo con un evento `data_verificata` provato su dominio ufficiale. Se il valore è
   recente (≥ `max(2026-07-13, oggi − 60 giorni)`) l'evento resta `applicato = false` finché il
   committente non coordina i due consumatori, perché un valore recente scritto a posteriori
   farebbe partire alert spuri. **`created_at` non viene mai toccato.**
2. **Righe ricreate dall'ingest**: su alcune fonti prive di chiave esterna stabile, un cambio di
   URL lato ente può produrre una riga nuova con `created_at` odierno. Il produttore la riconosce
   solo con criteri esatti (URL normalizzato identico) e in tal caso la fonde entro un giro, con
   master la riga vecchia. Nei casi non riconosciuti un consumatore **può ricevere un alert in
   più** per lo stesso bando, e la riga vecchia riceve un evento interno
   `sparito_dalla_fonte`.
3. **Ogni transizione di stato e ogni rigenerazione di `contenuto` cambia il testo** del bando:
   chi ne mantiene un hash per una cache (per esempio di estrazioni LLM) rivedrà quella cache
   invalidata per i bandi interessati.
4. **Un pubblicato non esce mai da `stato_processing = 'completed'` né perde lo slug** durante
   una rielaborazione, in nessuna fase. Un doppione fuso è
   `stato_processing='completed' AND slug IS NOT NULL AND pubblicato=false` fino alla (d):
   leggibile in `bando`, assente dalla vista, presente in `bando_fusione`. Un pubblicato passa a
   `pubblicato=false` **solo** per fusione o per ritiro scritto del committente.
5. **Fra la fase (b) e il rilascio R0**, `stato_bando` può valere `aperto` per un bando che la
   fonte ufficiale ha sospeso o revocato: l'evento esiste ed è leggibile
   (`verificato=true, applicato=false`), ma la colonna non è ancora cambiata perché il CHECK a 5
   valori non è ancora applicato. Chi vuole essere corretto in quella finestra legge gli eventi
   `sospensione` / `revoca` / `riapertura` / `annullamento_revoca` con `applicato=false` e
   sovrascrive il badge.
6. `link_candidatura` **può diventare NULL** (quando puntava a un aggregatore); `allegati`
   continua a esistere fino alla (d) ma non è più la fonte di verità; il `titolo` di un bando
   pubblicato **non viene mai riscritto** da una rigenerazione.

---

## 10. Fasi, migrazioni e impatto

### 10.1 Le quattro fasi

| Fase | Sbloccata da | Che cosa cambia per un consumatore |
|---|---|---|
| **(a)** | il rilascio R0-a del consumatore, confermato per iscritto | nulla sul DB |
| **(b)** | le migrazioni 01-05 (tutte additive), poi la 06 solo dopo la (a) | nulla si rompe: si aggiunge senza togliere |
| **(c)** | il consumatore passa a leggere `bando_pubblico`, `bando_link`, `bando_evento`, `bando_fusione`, `bando_slug_storico`; rimappa i `bando_id` fusi e risolve i miss; ricerca su `ricerca` | nessuna migrazione |
| **(d)** | conferma scritta che la (c) è in produzione | migrazione 07: RLS su `pubblicato`, REVOKE di colonna su `bando`, vista senza le colonne deprecate |

### 10.2 Le migrazioni

Ordine di applicazione della fase (b): **01 → 02 → seed → 03 → 04 → 05**, più la **08**, che è
correttiva e si applica quando serve (prima o dopo le altre: dipende solo da 01 e 02). Ogni file è
idempotente, porta un blocco Riconciliazione rieseguibile, un blocco Verifica con le query e i
valori attesi, e un file di rollback.

L'ordine non è negoziabile ed è quello scritto nelle intestazioni dei file SQL (`seed:17`,
`02:39`, `03:35-36`), non quello che si deduce dai numeri. Il seed solleva
`RAISE EXCEPTION 'manca dominio_ufficiale: applicare prima bando_v11_02…'` se la 02 non c'è; e la
03 va **dopo** il seed, perché il suo trigger anti-aggregatore legge la blocklist che solo il seed
completa. Eseguirla prima la farebbe girare su una `dominio_ufficiale` incompleta.

**L'ordine di rientro è l'inverso: 07 → 06 → 05 → 04 → 03 → 02 → 01.** Se un blocco Verifica non
torna il valore atteso non si prosegue con la migrazione successiva: si esegue
`bando_v11_NN_*_rollback.sql`. Il seed non ha rollback, ed è voluto: ogni INSERT è
`ON CONFLICT (host) DO NOTHING`. I rollback di 01 e 02 hanno perdite irreversibili, dichiarate
nelle loro intestazioni.

| File | Fase | Contenuto | Rompe un consumatore? |
|---|---|---|---|
| `bando_v11_01_pubblicazione.sql` | (b) | in un solo `ALTER TABLE`: `pubblicato`/`pubblicato_at`/`ritirato_at` (con CHECK unidirezionale «pubblicato ⇒ completed con slug e stato»), `ultimo_cambiamento_at`, `ora_apertura`/`ora_scadenza`, i tre `data_*_verificata`, i riferimenti all'evento di provenienza, `bando_master_id`, `chiave_esterna`, le colonne `fonte_ufficiale_*` e la colonna generata `ricerca` + GIN; `archiviato` aggiunto al CHECK di `stato_processing`; RLS e REVOKE delle scritture su `categoria_programma`/`tipologia_programma`; REVOKE EXECUTE sulle RPC obsolete | **No** (solo aggiunte; il conteggio dei pubblicati non cambia). Dichiarazione operativa: l'`ALTER TABLE` prende un **blocco esclusivo di alcuni secondi** e riscrive la tabella, quindi sono possibili 57014/504 transitori |
| `bando_v11_02_tabelle_di_servizio.sql` | (b) | `dominio_di`, `bando_normalizza_url`, `bando_stato_effettivo`, `bando_host_aggregatore`; `pipeline_run`, `fonte_run`, `pipeline_lock`; `bando_evento` con la sequence del cursore, il trigger del cursore sotto advisory lock, il trigger anti-aggregatore, l'immutabilità e la RLS **già nella forma finale**; `bando_link`; `bando_fusione`; `bando_slug_storico`; `bando_controllo`; `dominio_ufficiale` con la blocklist. REVOKE ALL da `PUBLIC`/`anon`/`authenticated` su tutto, poi i soli GRANT del contratto | **No** (oggetti nuovi) |
| `bando_v11_03_fonte_ufficiale.sql` | (b) | le FK verso `bando_link`, `bando_evento` e `bando`; i CHECK di provenienza e coerenza della fonte; i trigger «slug congelato», «slug non storico», provenienza delle date, copia della fonte ufficiale, anti-aggregatore su `fonte_ufficiale_host`; indice unico `(fonte_id, chiave_esterna)` | **No** |
| `bando_v11_seed_dominio_ufficiale.sql` | (b) | popolamento di `dominio_ufficiale`: portali pubblici, pattern, blocklist | **No** |
| `bando_v11_04_transizioni.sql` | (b) | la tabella delle transizioni ammesse e le RPC (`bando_registra_evento`, `bando_applica_evento`, `bando_fondi`, `bando_separa`, `bando_pubblica`, `bando_ritira`, `bando_cambia_slug`, `lock_acquisisci`, `lock_rilascia`), tutte con REVOKE EXECUTE e guardia sul ruolo; il job orario `5 * * * *` che sostituisce la vecchia chiusura giornaliera | **No** (`stato_bando` resta allineato come oggi) |
| `bando_v11_05_vista_pubblica.sql` | (b) | il `GRANT EXECUTE` ad `anon` sulle tre funzioni dell'allowlist, il grant di colonna `(bando_id, ultimo_controllo_at)` su `bando_controllo`, e la vista `bando_pubblico` | **No** (oggetto nuovo) |
| `bando_v11_08_evento_pubblicazione.sql` | (b) | il trigger che emette l'evento `pubblicazione` quando una riga diventa pubblicata, più il recupero di quelle rimaste senza. Fino alla 08 l'evento esisteva solo come riempimento iniziale della 02: i bandi pubblicati dopo quel momento non entravano nel flusso a cursore, cioè un consumatore che segue gli eventi non veniva a sapere dei bandi nuovi. Si applica prima o dopo le altre, non dipende da 03, 04 e 05 | **No**: compaiono solo righe nuove in `bando_evento`, con lo stesso tipo e gli stessi valori di quelle già seminate |
| `bando_v11_06_stati_cinque.sql` | (b), **dopo** la (a) | CHECK di `stato_bando` a 5 valori | **Sì se applicata prima di R0-a**: badge sbagliato, filtro `stato` in 400, `sospeso`/`revocato` nei segmenti |
| `bando_v11_07_fase_d.sql` | (d) | `DROP VIEW` + ricreazione senza le colonne deprecate; policy di `bando` su `pubblicato`; REVOKE di colonna su `bando` con GRANT solo sulle colonne del contratto | **Sì** se un consumatore legge ancora `bando` con `link_bando`, `stato_processing`, `allegati`, `link_candidatura` o `descrizione_raw` |

Le fusioni dei doppioni **non sono una migrazione**: avvengono nel normale funzionamento e non
rompono nulla, perché il doppione resta `completed` con il suo slug ed è presente in
`bando_fusione`.

Ogni rollback è realistico e documentato. Due limiti dichiarati: il rollback della 01 ripristina
il CHECK a 6 valori solo se non esistono righe `archiviato`; quello della 06 ripristina il CHECK
a 3 valori solo se non esistono righe `sospeso` o `revocato`.

---

## 11. Controlli di accettazione

**Prima della fase (b)** si registra un campione delle otto richieste del §12 (corpo delle
risposte, colonne, embed, header `Content-Range`).

**Dopo ogni migrazione della fase (b)**:

- le stesse otto richieste restituiscono le stesse risposte (colonne, embed, `Content-Range`);
- `bando?select=id&stato_processing=eq.completed&slug=not.is.null` ≥ 2104 righe, e
  `bando?select=id&pubblicato=eq.true` ≤ di esso (la differenza sono i doppioni fusi, presenti
  in `bando_fusione`);
- nessuna riga con `stato_bando` fuori dai 3 valori prima della 06;
- `POST /rest/v1/rpc/bando_fondi` con la anon key → **42501**;
- `bando_evento?url_prova=ilike.*obiettivoeuropa*` → **0 righe**;
- `bando_pubblico?fonte_ufficiale_host=ilike.*obiettivoeuropa*` → **0 righe**;
- come ruolo `anon`, `count(*)` su `bando_pubblico` = `count(*)` su `bando where pubblicato`;
- nessuna funzione dello schema `public` eseguibile da `anon` oltre a quelle di `pg_trgm` e alle
  tre dell'allowlist (`bando_stato_effettivo`, `dominio_di`, `bando_host_aggregatore`).

**Nella fase (c)**: le stesse richieste, rieseguite **sulla vista**, rispondono in meno di 3
secondi e restituiscono `stato_effettivo` e `fonte_ufficiale_url`; per un `id` fuso la vista non
risponde con righe e `bando_fusione` risponde con il `master_id`.

**Nella fase (d)**: `bando?select=link_bando` con la anon key → **42501**;
`bando_pubblico?select=id,slug` → **200**; le otto richieste della versione (c), rieseguite dopo
la 07, tutte **200**.

---

## 12. Le otto richieste replicabili (R1-R8)

Sono le richieste che BandoFit esegue oggi sul DB bandi. Sono elencate qui — non inventate —
leggendo il codice: per ciascuna è indicato il file e la riga da cui è ricavata, nel repository
`BandoFit`, sotto `backend/app/`.

Convenzioni comuni a tutte:

- metodo `GET`, endpoint `/rest/v1/<tabella>`;
- header `apikey` e `Authorization: Bearer` con la **anon key** (valore non riportato qui);
- il client in uso è `supabase-py` con `postgrest` 2.31: `range(start, end)` emette **`offset=` e
  `limit=`** come parametri di query (non un header `Range`), e più chiamate a `order()` si
  fondono in **un solo** parametro `order=` separato da virgole;
- `count="exact"` emette l'header **`Prefer: count=exact`**; il totale torna in `Content-Range`;
- `<OGGI>` è la data di Roma dell'istante della richiesta (`today_italy()`,
  `services/bandi_service.py:86-89`);
- gli spazi nei valori (per esempio `in apertura prossimamente`) viaggiano codificati `%20`: il
  client mette fra virgolette solo i valori che contengono `,` `:` `(` `)`
  (`postgrest/utils.py:32-37`).

Abbreviazioni usate sotto (tutte da `services/bandi_service.py`):

- **LIST** (`:25-31`) =
  `id,slug,titolo,titolo_breve,descrizione_breve,stato_bando,livello,data_pubblicazione,data_apertura,data_scadenza,importo_totale_eur,importo_max_per_progetto_eur,ente_erogatore,tipologie_bando(id,nome),modalita_erogazione(id,nome),bando_regioni(regioni(id,nome))`
- **SCORING** (`:37-40`) =
  `,bando_settori(settore_id),bando_beneficiari(beneficiario_id),bando_codici_ateco(codice_ateco_id)`
- **DETAIL** (`:42-51`) =
  `id,slug,titolo,titolo_breve,descrizione_raw,descrizione_breve,stato_bando,livello,data_pubblicazione,data_apertura,data_scadenza,importo_totale_eur,importo_max_per_progetto_eur,ente_erogatore,area_geografica,tematica,link_bando,link_candidatura,contenuto,allegati,tipologie_bando(id,nome),modalita_erogazione(id,nome),programmi(id,nome),bando_regioni(regioni(id,nome)),bando_settori(settori(id,nome)),bando_beneficiari(beneficiari(id,nome)),bando_codici_ateco(codici_ateco(id,codice,descrizione))`

Il predicato di pubblicazione `stato_processing=eq.completed&slug=not.is.null` compare in sette
punti: `services/bandi_service.py:151`, `:370`, `:394`,
`services/saved_bandi_service.py:60`, `:202`, `services/calendar_service.py:127`,
`services/bando_alert_service.py:222-223`. Nelle prime righe della fase (c) è quello da togliere,
perché la vista è già filtrata.

---

### R1 — Elenco pubblico, segmento «non chiusi» (prima pagina, ordinamento di default)

È la prima delle due query complementari che compongono una pagina di elenco.

```
GET /rest/v1/bando
    ?select=<LIST>
    &stato_processing=eq.completed
    &slug=not.is.null
    &or=(stato_bando.neq.chiuso,stato_bando.is.null)
    &or=(data_scadenza.gte.<OGGI>,data_scadenza.is.null)
    &order=data_pubblicazione.desc.nullslast,id.asc
    &offset=0&limit=20
Prefer: count=exact
```

Origine: select `services/bandi_service.py:25-31` (composta da `build_list_select`, `:134-143`);
predicato `:151`; segmento «non chiusi» `apply_open_tier`, `:200-205`; ordinamento e paginazione
`:310-323` (tabella `SORT_OPTIONS` `:76-82`, default `pubblicazione_desc` `:83`); dimensione di
pagina 20 da `api/routers/bandi.py:79`.

Quando il chiamante ha un profilo aziendale la select diventa `<LIST><SCORING>`
(`build_list_select(..., include_facets=True)`, `services/bandi_service.py:137-139`, invocata
alla riga `:313`).

**Versione (c)**: stessa richiesta su `/rest/v1/bando_pubblico`, senza le due righe del predicato
e con `stato_effettivo=in.(aperto,in%20apertura%20prossimamente)` al posto dei due `or=`.

---

### R2 — Elenco pubblico, segmento «chiusi»

Seconda query della stessa pagina. Serve sempre, anche quando la pagina è piena di non chiusi,
perché il totale della paginazione è la somma dei due `count`.

```
GET /rest/v1/bando
    ?select=<LIST>
    &stato_processing=eq.completed
    &slug=not.is.null
    &or=(stato_bando.eq.chiuso,data_scadenza.lt.<OGGI>)
    &order=data_pubblicazione.desc.nullslast,id.asc
    &offset=<offset nei chiusi>&limit=<righe mancanti>
Prefer: count=exact
```

Quando la pagina è già piena di non chiusi, la richiesta degenera in `&limit=1` senza `offset`
(serve solo il `count`).

Origine: `apply_closed_tier`, `services/bandi_service.py:208-210`; costruzione della query
`:326-342`; nota sul confine fra i due segmenti e deduplicazione per `id` `:346-354`.

**Versione (c)**: `stato_effettivo=eq.chiuso` al posto dell'`or=`.

---

### R3 — Elenco con tutti i filtri e la ricerca full-text

Forma massima della stessa richiesta: è quella che produce i timeout `57014`.

```
GET /rest/v1/bando
    ?select=<LIST><SCORING>,f_reg:bando_regioni!inner(regione_id),f_set:bando_settori!inner(settore_id),f_ben:bando_beneficiari!inner(beneficiario_id),f_ate:bando_codici_ateco!inner(codice_ateco_id)
    &stato_processing=eq.completed
    &slug=not.is.null
    &or=(titolo_raw.wfts(italian).<termine>,descrizione_raw.wfts(italian).<termine>,titolo.wfts(italian).<termine>,titolo_breve.wfts(italian).<termine>,descrizione_breve.wfts(italian).<termine>)
    &stato_bando=in.(aperto,in%20apertura%20prossimamente)
    &livello=eq.guida_bando
    &tipologia_bando_id=in.(1,2)
    &modalita_erogazione_id=in.(3)
    &programma_id=in.(7)
    &importo_totale_eur=gte.100000
    &importo_totale_eur=lte.5000000
    &data_scadenza=gte.<DA>&data_scadenza=lte.<A>
    &f_reg.regione_id=in.(9,12)
    &f_set.settore_id=in.(4)
    &f_ben.beneficiario_id=in.(2)
    &f_ate.codice_ateco_id=in.(881)
    &or=(stato_bando.neq.chiuso,stato_bando.is.null)
    &or=(data_scadenza.gte.<OGGI>,data_scadenza.is.null)
    &order=data_scadenza.asc.nullslast,id.asc
    &offset=0&limit=20
Prefer: count=exact
```

Origine: `apply_filters`, `services/bandi_service.py:146-190` (FTS `:155-161` sulle cinque
colonne di `FTS_COLUMNS` `:57-63`, sanificate da `sanitize_fts_term` `:111-114`; filtri scalari
`:162-183`; filtri sulle junction `:185-188`); alias e junction in `JUNCTION_FACETS` `:66-71`;
embed `!inner` aliasati in `build_list_select` `:140-142`.
I parametri `or` ripetuti sono messi in AND da PostgREST, quindi la ricerca convive con i due
`or` del segmento.

**Versione (c)**: l'`or` a cinque rami diventa `ricerca=wfts(italian).<termine>` — un solo `@@`
per riga. Gli `!inner` con alias restano identici.

---

### R4 — Dettaglio di un bando per slug

```
GET /rest/v1/bando
    ?select=<DETAIL>
    &slug=eq.<slug>
    &stato_processing=eq.completed
    &limit=1
```

Origine: `fetch_bando_by_slug`, `services/bandi_service.py:383-397`. La stessa forma, con la
stessa select, è usata dalla pipeline di analisi automatica (`fetch_bando_for_ai`, `:361-372`).
Si noti che qui il predicato non include `slug=not.is.null` (è implicito nel confronto `eq`).

**Attenzione alla fase (d)**: `<DETAIL>` contiene `descrizione_raw`, `titolo_raw`, `link_bando`,
`link_candidatura` e `allegati`, tutte rimosse dalla vista dalla migrazione 07. Vanno tolte
prima, altrimenti l'intera richiesta risponde 42703.

**Versione (c)**: su `/rest/v1/bando_pubblico`, senza `stato_processing`, aggiungendo
`stato_effettivo`, `fonte_ufficiale_url`, `fonte_ufficiale_host`, `fonte_ufficiale_tipo`,
`fonte_ufficiale_e_atto`, `ora_scadenza`, `ora_apertura` e i tre `data_*_verificata`. Su un miss,
seconda richiesta:
`GET /rest/v1/bando_slug_storico?select=slug,bando_id,esito&slug=eq.<slug>&limit=1`.

---

### R5 — Preferiti

Due forme, entrambe sul DB bandi.

**R5-a — snapshot «live» di un blocco di preferiti, per id.**

```
GET /rest/v1/bando
    ?select=<LIST>
    &id=in.(<id1>,<id2>,…)
    &stato_processing=eq.completed
    &slug=not.is.null
```

Origine: `list_saved`, `services/saved_bandi_service.py:198-205`. Gli id arrivano dalla tabella
dei preferiti del DB primario (`:181-197`), che conserva `bando_id` **senza FK** e uno snapshot
di slug, titolo, scadenza e stato (`SAVED_SELECT`, `:26`).

**R5-b — rilettura di un singolo bando al momento del salvataggio, per slug.**

```
GET /rest/v1/bando
    ?select=<LIST>
    &slug=eq.<slug>
    &stato_processing=eq.completed
    &limit=1
```

Origine: `_fetch_live_bando`, `services/saved_bandi_service.py:55-63`.

**Versione (c)**: su `bando_pubblico`. R5-a è la richiesta in cui i **miss contano**: gli id
assenti dalla risposta vanno cercati con
`GET /rest/v1/bando_fusione?select=bando_id,master_id,master_slug&bando_id=in.(<mancanti>)` e
rimappati. Se la tabella dei preferiti ha un UNIQUE su `(utente, azienda, bando_id)`, la riga del
doppione va **eliminata**, non aggiornata (§6.2).

---

### R6 — Calendario: snapshot della scadenza di un bando

```
GET /rest/v1/bando
    ?select=id,slug,titolo,titolo_breve,data_scadenza
    &slug=eq.<slug>
    &stato_processing=eq.completed
    &limit=1
```

Origine: `create_bando_event`, `services/calendar_service.py:117-130`; select
`SNAPSHOT_SELECT`, `:35`.

Nota funzionale che il contratto rende risolvibile: l'evento di calendario **congela** la data,
quindi oggi una proroga non si propaga. Dalla fase (c) la propagazione si ottiene leggendo per
cursore gli eventi `proroga` e `rettifica` su `data_scadenza` (§6.1).

**Versione (c)**: su `bando_pubblico`, aggiungendo `ora_scadenza` e `data_scadenza_verificata`.

---

### R7 — Candidati degli alert

Richiesta giornaliera, **senza `limit`** (quindi soggetta al tetto `max-rows` = 1000).

```
GET /rest/v1/bando
    ?select=<LIST><SCORING>,created_at
    &stato_processing=eq.completed
    &slug=not.is.null
    &or=(stato_bando.neq.chiuso,stato_bando.is.null)
    &or=(data_scadenza.gte.<OGGI>,data_scadenza.is.null)
    &or=(data_pubblicazione.gte.<CUTOFF>,and(data_pubblicazione.is.null,created_at.gte.<CUTOFF>))
```

`<CUTOFF>` = `max(<data di attivazione>, <OGGI> − <orizzonte> giorni)`, con data di attivazione
`2026-07-13` e orizzonte 60 giorni (`core/config.py:42-43`).

Origine: `carica_candidati`, `services/bando_alert_service.py:214-232`; select
`CANDIDATE_SELECT`, `:46`; segmento «non chiusi» riusato da
`services/bandi_service.py:200-205`; calcolo della data di riferimento
`coalesce(data_pubblicazione, created_at)` in `data_riferimento`, `:88-95`.

È la richiesta più sensibile del contratto: **per questo `data_pubblicazione` non viene mai
riempita a posteriori** e `created_at` non viene mai toccato (§9.1).

**Versione (c)**: su `bando_pubblico`, con
`stato_effettivo=in.(aperto,in%20apertura%20prossimamente)` al posto dei due `or=` di segmento —
il che esclude automaticamente anche `sospeso` e `revocato`, come richiesto da R0-a.

---

### R8 — Cataloghi

Sette richieste indipendenti, eseguite in parallelo e tenute in cache per un'ora.

```
GET /rest/v1/regioni?select=id,nome&order=nome
GET /rest/v1/settori?select=id,nome&order=nome
GET /rest/v1/beneficiari?select=id,nome&order=nome
GET /rest/v1/codici_ateco?select=id,codice,descrizione&order=codice
GET /rest/v1/tipologie_bando?select=id,nome&order=id
GET /rest/v1/modalita_erogazione?select=id,nome&order=id
GET /rest/v1/programmi?select=id,nome&order=nome
```

Origine: `_fetch_all`, `services/lookup_service.py:19-39` (la funzione interna `rows` alla riga
`:20-22` costruisce ognuna delle sette); cache di un'ora `:12` e `:52-60`.

**Versione (c)**: invariata. I cataloghi non cambiano: id e conteggi restano quelli di oggi
(§8), e il conteggio delle regioni resta utilizzabile come denominatore del punteggio
«nazionale» (`services/compatibility.py:129`).

---

## 13. In una riga

Fino alla fase (d) si può continuare a leggere `bando` come oggi. Dalla (c) si legge
`bando_pubblico` cambiando **solo il nome della tabella**, e si guadagnano `stato_effettivo`, la
fonte ufficiale, la ricerca su una colonna sola e la risoluzione dei miss. Prima che la (d)
arrivi, vanno tolte dalle select le sette colonne deprecate (`stato_processing`, `link_bando`,
`link_candidatura`, `link_candidatura_source`, `allegati`, `titolo_raw`, `descrizione_raw`).
