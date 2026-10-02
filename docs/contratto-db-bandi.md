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
   **Eccezione, dalla migrazione 12:** `monitoraggio_catalogo(p_chiave)` (§14). È eseguibile con
   la anon key, ma risponde solo a una `POST` con una chiave di monitoraggio valida, non scrive
   niente e restituisce solo il riepilogo di salute. Le tabelle del monitoraggio restano
   illeggibili con la anon key.
   **Eccezione, dalla migrazione 13:** `bando_stato_da_verificare(...)` (§4.1). È la funzione pura che la vista
   chiama per la colonna `stato_da_verificare`: non legge tabelle, non scrive, e come `bando_stato_effettivo` resta
   eseguibile anche dopo la fase (d). Non serve chiamarla direttamente: la vista ne espone il risultato.
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
| `stato_da_verificare` | perché lo stato mostrato **non è certo** (uno dei cinque motivi di §4.1), oppure NULL: nessuna prova contraria. Dalla migrazione 13 |
| `stato_letto` / `stato_letto_at` | l'ultimo stato letto sulla pagina ufficiale da un lettore strutturato, e quando; esposti solo se riguardano lo stato di oggi |
| `termine_indicato` / `termine_indicato_fonte` | un termine di presentazione indicato da una fonte non verificata, con la sua provenienza: un indizio, **mai** una scadenza |
| `pubblicato` / `pubblicato_at` | il flag di pubblicazione e il suo istante |
| `ultimo_cambiamento_at` | avanza **solo** per modifiche pubbliche; mai per re-scrape o controlli |
| `ultimo_controllo_at` | ultimo controllo della freschezza (da `bando_controllo`) |
| `fonte_ufficiale_url` / `_host` / `_tipo` / `_stato` / `_verificata_at` | l'unico link «ufficiale»; **non esiste** nessuna colonna «link_ufficiale» |
| `ricerca` | colonna `tsvector` generata, percorso unico della ricerca full-text |
| `bando_link` | allegati e link di un bando (non `bando_links`) |
| `bando_evento` | registro degli eventi (non `bando_eventi`) |
| `bando_fusione` | mappa doppione → master (non `bando_master`) |
| `bando_slug_storico(slug, bando_id, esito, motivo, created_at)` | storico degli slug |
| `bando_controllo` | tabella interna di servizio; ad `anon` sono concesse **solo** le colonne `bando_id` e `ultimo_controllo_at`, più, dalla migrazione 13, le nove che la vista usa per le colonne di §4.1 (`stato_letto`, `stato_letto_su`, `stato_letto_at`, `stato_letto_metodo`, `previsto_entro`, `termine_indicato`, `termine_indicato_fonte`, `esaminato_attivo_at`, `segnale_aggregatore_at`). Quei privilegi esistono **solo perché la vista è `security_invoker`**: le colonne di `bando_controllo` **non fanno parte del contratto** (nomi, significato e presenza possono cambiare senza avviso). Si legge solo la vista |
| `dominio_ufficiale` | whitelist/blocklist dei domini; **tabella interna**, non leggibile con la anon key |
| `pipeline_run`, `fonte_run`, `pipeline_lock` | tabelle interne della pipeline |
| `monitoraggio_catalogo(p_chiave)` | la sola funzione del pannello di monitoraggio: solo `POST`, solo con una chiave valida (§14) |
| `monitoraggio_riepilogo`, `monitoraggio_chiave` | tabelle interne del monitoraggio (riepilogo di salute e impronte delle chiavi); **non leggibili** con la anon key |
| `monitoraggio_job_orario()` | funzione interna del monitoraggio; **non eseguibile** con la anon key |
| `apertura_automatica` / `chiusura_automatica` | i tipi di evento del job orario (non «transizione_automatica») |
| `bando_link.ultimo_visto_at` | ultimo 2xx **del link** |
| `bando_controllo.ultimo_visto_in_fonte_at` | ultima presenza **nel listing della fonte** — colonna diversa dalla precedente e non leggibile con la anon key |

Le priorità interne sono sempre sulla scala **0-100**.

---

## 3. La vista `bando_pubblico`

Definita `CREATE VIEW … WITH (security_invoker = true)`, con `GRANT SELECT` ad `anon`, e filtrata
`WHERE pubblicato`. Essendo `security_invoker`, la RLS di `bando` resta il guardiano: la vista non
scavalca nessun permesso e resta inlinabile dal planner (`count=exact` funziona come su una
tabella).

**Embed di `bando_link` (aggiornamento del 30/09/2026).** È garantito l'embed
`bando_pubblico?select=…,bando_link!bando_id(<colonne concesse, per nome>)`, con la stessa RLS e le stesse colonne
di §5. Filtri, ordine e limite sul figlio sono ammessi (`bando_link.tipo=in.(…)&bando_link.order=id&bando_link.limit=200`)
e non tolgono righe al padre. `bando_link(*)`, o una colonna non concessa, fa fallire l'intera richiesta (42501).
Usare sempre l'hint `!bando_id`: sulla tabella `bando` l'embed senza hint è ambiguo (PGRST201). Una modifica della
vista che crea una seconda relazione con `bando_link` è un cambio di contratto annunciato.

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
| **`stato_da_verificare`** | text | dalla migrazione 13. NULL oppure uno dei cinque motivi di §4.1: `data_apertura_passata`, `smentito_dalla_fonte`, `previsione_scaduta`, `senza_conferma`, `termine_passato`. **Lo stato di un bando è certo solo con `stato_da_verificare IS NULL`.** IS NULL è condizione necessaria, non una verifica: vuol dire nessuna prova contraria. Un bando mai controllato vale NULL finché le sue date non dicono altro |
| `stato_letto` | text | dalla 13. L'ultimo stato letto sulla pagina ufficiale da un lettore strutturato: `in apertura prossimamente` \| `aperto` \| `chiuso` \| `uscito`. NULL se la lettura riguardava uno stato diverso da `stato_bando`, oppure se viene da un'interpretazione automatica del testo (modello): il sito non presenta come «letto sulla pagina ufficiale» un'interpretazione automatica. Fra le letture esposte c'è anche quella del **lettore generico**, sulle pagine senza un lettore dedicato: legge solo frasi compiute di chiusura («Bando chiuso», «Domande chiuse», «dotazione esaurita») e può dire **solo** `chiuso`. È un segnale: accende `smentito_dalla_fonte`, ma non genera eventi e non cambia lo stato. Non conferma mai un «aperto» |
| `stato_letto_at` | timestamptz | dalla 13. Quando è stata fatta quella lettura; NULL alle stesse condizioni di `stato_letto` |
| `termine_indicato` | date | dalla 13. Un termine di presentazione indicato da una fonte che non è la pagina ufficiale verificata. È un indizio: non cambia `stato_effettivo`, non genera eventi e non va mostrato come scadenza. NULL finché il bando non è stato esaminato dal controllo attivo del produttore: in prova (ombra) è sempre NULL |
| `termine_indicato_fonte` | text | dalla 13. Da dove viene il termine: `calendario_ufficiale` \| `pagina` \| `testo` \| `aggregatore` (in quest'ordine di affidabilità). NULL quando `termine_indicato` è NULL |

**Le cinque colonne della 13 stanno in coda** alla vista e si calcolano solo se la select le chiede: una select con
colonne esplicite non cambia, e `count=exact` non costa di più. Un `select=*` riceve cinque colonne in più. Le
colonne interne di `bando_controllo` da cui sono calcolate sono leggibili con la anon key solo perché la vista è
`security_invoker`: **non fanno parte del contratto** e non vanno lette direttamente (per esempio mostrano anche le
letture non strutturate che la vista nasconde).

**Assenti per scelta**, e non torneranno: `raw_data`, `hash_bando`, `fonte_id`,
`confidence_score`, `rejection_reason`, `canonical_key`, `fonti_aggiuntive`, `updated_at`,
`bando_master_id`, e tutte le colonne di controllo del monitor.

**`stato_effettivo` è NOT NULL** su ogni riga della vista. Lo garantiscono insieme il CHECK
`bando_pubblicato_implica_completed` della 01 (pubblicato ⇒ `stato_bando` NOT NULL) e il CHECK a cinque valori
`bando_stato_bando_check` della 06. La vista non espone la colonna `pubblicato`: un filtro `pubblicato=eq.true`
risponde 42703 (N4 = leggere la vista). Il jsonb `allegati` non ha un CHECK sulla forma: il consumatore tratta un
non-array come `[]` e scarta ogni elemento senza `url` stringa.

Fino alla fase (d) la tabella `bando` resta leggibile con la anon key con tutte le colonne di
oggi e la RLS attuale. Nella (d) escono dalla vista `stato_processing`, `link_bando`,
`link_candidatura`, `link_candidatura_source`, `allegati`, `titolo_raw`, `descrizione_raw`.

---

## 4. Stati e calcolo di `stato_effettivo`

Gli stati sono cinque: `aperto`, `chiuso`, `in apertura prossimamente`, `sospeso` (può riaprire),
`revocato` (terminale; si esce solo con un evento `annullamento_revoca` o, dalla migrazione 14, con una
`correzione_redazionale` della redazione).

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

### 4.1 Certezza dello stato (`stato_da_verificare`, dalla migrazione 13)

`stato_effettivo` dice qual è lo stato; `stato_da_verificare` dice **se quello stato è certo**. È un motivo di
dubbio, oppure NULL. **Per un consumatore uno stato è certo solo con `stato_da_verificare IS NULL`.** Un motivo non
cambia mai lo stato: un bando «aperto · da verificare» resta fra gli aperti, nei contatori e nei filtri. Il DB non
chiude niente a tempo: una chiusura arriva solo con un evento (§6.1).

Si calcola alla lettura, come `stato_effettivo`, con la stessa regola in tutti i gemelli del produttore. `oggi` è la
data civile di Roma; «N giorni fa» è la differenza fra date civili di Roma (non fra ore); una **lettura valida** è una
lettura della pagina ufficiale che riguarda lo stato persistito di oggi. Vince la prima regola che si applica.

- **Fuori dai due rami** (chiuso, sospeso, revocato, aperto con `data_scadenza`) → NULL.
- **Ramo «in apertura»** (`stato_effettivo = 'in apertura prossimamente'`):
  1. apertura con data verificata → NULL;
  2. `data_apertura` passata → `data_apertura_passata`;
  3. la pagina ufficiale lo indica aperto, chiuso o uscito → `smentito_dalla_fonte`;
  4. mai esaminato dal controllo attivo del produttore → NULL;
  5. il periodo di apertura previsto dal calendario è passato → `previsione_scaduta`;
  6. la pagina lo conferma «in apertura» da al massimo 30 giorni → NULL;
  7. pubblicato da al massimo 3 giorni → NULL;
  8. altrimenti → `senza_conferma`.
- **Ramo «aperto» senza `data_scadenza`**:
  1. la pagina ufficiale lo indica chiuso, uscito o in apertura → `smentito_dalla_fonte`;
  2. un lettore strutturato l'ha letto «aperto» da al massimo 30 giorni, e dopo l'ultimo segnale del portale
     aggregatore → NULL (un'interpretazione automatica del testo **non** conferma);
  3. mai esaminato dal controllo attivo del produttore → NULL;
  4. `termine_indicato` passato → `termine_passato`;
  5. il portale aggregatore segnala che il bando è uscito dal suo elenco, in uscita o scaduto → `senza_conferma`;
  6. `termine_indicato` da oggi in poi → NULL;
  7. pubblicato da al massimo 7 giorni → NULL;
  8. altrimenti → `senza_conferma`.

**Che cosa vuol dire per un consumatore.**
- `senza_conferma` vale ora **anche per gli aperti senza scadenza**: nessuna prova recente dalla pagina ufficiale.
  Compare solo dopo un controllo attivo, di regola dal 7° giorno dopo la pubblicazione. Può comparire **prima** se il
  portale aggregatore segnala il bando come uscito dal suo elenco, in uscita o scaduto: il punto 5 viene prima della
  grazia dei 7 giorni (punto 7). Il produttore rilegge questi bandi ogni 14 giorni e il motivo si spegne da solo con una
  conferma, una scadenza o una chiusura.
- Finché il controllo del produttore è in prova (ombra), nessun bando è «esaminato» (punti 4 e 3 dei due rami):
  **l'unico motivo che può comparire è `data_apertura_passata`**, perché dipende solo dalle date del bando.
  `previsione_scaduta`, `termine_passato`, `smentito_dalla_fonte` e `senza_conferma` compaiono solo dopo
  l'attivazione, man mano che il controllo rilegge i bandi. Lo stesso vale per `termine_indicato`, che fino al primo
  esame attivo del bando è NULL.
- Diciture consigliate: «In apertura · da verificare» per il ramo «in apertura»; «Aperto · da verificare» per il
  ramo «aperto». Un `termine_indicato` si mostra sempre con la sua provenienza (`termine_indicato_fonte`), mai come
  scadenza.

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
Le garanzie valgono per le righe leggibili di `bando_link`, non per `fonte_ufficiale_url`, che è NOT NULL se e solo
se `fonte_ufficiale_stato='trovata'` (CHECK `bando_fonte_coerente`): il DB non verifica che la riga puntata sia ancora
`pubblicabile`. `content_type` non ha un formato fisso (estensione o MIME): va usato solo come indizio. Oggi 20 righe
`allegato` hanno spazi non codificati nell'URL: fino a nuovo avviso il consumatore codifica lo spazio come `%20`.

**CTA consigliata**, in ordine: una riga `tipo='candidatura'` → altrimenti
`fonte_ufficiale_url` → altrimenti una riga `tipo='portale'`.
Fino alla fase (d) vale l'ordine esteso di §5.1, con i ripieghi sulle colonne deprecate. Fra più righe leggibili
dello stesso `tipo` vince quella con l'id più basso (lettura con `order=id`); non si usa `ultimo_visto_at`, che
avanza a ogni verifica. `pagina_bando` non entra nell'ordine del pulsante finché il produttore non decide per iscritto.

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

**Domini degli enti e IndicePA (dal giro 2).** La stessa tabella interna contiene la lista dei domini ufficiali,
cioè quelli che rendono `verificato` un evento (§6.1) e leggibile una pagina ufficiale. Dal giro 2 il produttore vi
importa ogni mese, in automatico, **l'intero indice pubblico delle pubbliche amministrazioni** (IndicePA): righe
`tipo='ente'`, `origine='indicepa'`. L'import è prudente:
- inserisce **solo host assenti**; una riga esistente non si modifica mai; nessuna cancellazione, nessuna
  disattivazione automatica;
- non inserisce gli host di piattaforme condivise (siti gratuiti, social, accorciatori di link), gli host che
  l'indice associa a tre o più enti diversi, e quelli che cadono sulla denylist qui sopra, **che prevale sempre**;
- se il file scaricato è anomalo (meno di 15 000 righe utili o colonne mancanti) non scrive niente.

Per un consumatore l'effetto è indiretto: più pagine ufficiali leggibili e più eventi `verificato`. La denylist non
cambia, e la tabella resta illeggibile con la anon key.

**Cintura del consumatore (30/09/2026).** Il filtro del DB ha tre limiti noti, da chiudere lato produttore:
`dominio_di` non tratta `\` come `/`; sul jsonb un host non riconosciuto passa; lo schema dell'URL non è
controllato. Perciò il consumatore applica a ogni URL che mostra (colonne deprecate, jsonb, `bando_link`,
`fonte_ufficiale_url`): parsing WHATWG riuscito; protocollo `http:` o `https:`; host (minuscolo, senza `www.` né
punto finale) fuori dai domini elencati e dai loro sottodomini; scarto della stringa grezza con `\`, caratteri di
controllo o un secondo `http(s)://` dopo uno spazio. Un URL che fallisce non si mostra e si passa al passo
successivo dell'ordine. `rpc/dominio_di` e `rpc/bando_host_aggregatore` non vanno usate come oracolo: la 07 le
revoca ad anon.

### 5.1 Dove si legge dopo la 07 (aggiornamento del 30/09/2026)

Colonne che la 07 toglie dalla vista, con il loro sostituto e la copertura **misurata** con la
anon key il 30/09/2026 alle 13:26 su 2 180 bandi (misura completa, con gli elenchi degli id:
`docs/bandi-monitor/misure-colonne-07.md` di news1, rimosso l'01/10: `git show a3ea9ef^:docs/bandi-monitor/misure-colonne-07.md`).

| colonna tolta | sostituto | copertura del sostituto oggi |
|---|---|---|
| `allegati` | righe `bando_link` con `tipo` in (`atto`, `allegato`) | **151 bandi su 160** con allegati nel jsonb non hanno nessuna riga sostitutiva (57 aperti, 62 in apertura). Nessuno dei 408 URL del jsonb è fra le righe `atto`/`allegato` leggibili **dello stesso bando** (2 lo sono come `pagina_bando`, 23 come `allegato` di un altro bando). In compenso 276 bandi senza jsonb hanno righe `allegato` |
| `link_candidatura` | riga `bando_link` con `tipo='candidatura'` | **1 bando su 146**. Per 71 resta la fonte ufficiale, 74 restano senza nulla |
| `link_candidatura_source` | nessuno. news1 lo usa sul suo sito per scartare i link non `extracted`, per scelta più severa; per BandoFit il filtro è facoltativo: il suo ordine di §5.1 non lo richiede | — |
| `link_bando` | `fonte_ufficiale_url` | 131 su 334, sempre con lo stesso URL; **203 senza fonte** (quasi tutti `in_verifica`) |
| `titolo_raw` | `titolo` per mostrare, `ricerca` per cercare | completa |
| `descrizione_raw` | nessuno: è NULL ovunque | — |
| `stato_processing` | nessuno: la vista è già filtrata | completa |

Il pulsante principale calcolato come in §5 («CTA consigliata») sarebbe presente su 616 bandi
invece di 827: **211 lo perderebbero, 183 dei quali aperti o in apertura.**

**Perché.** Le righe sostitutive esistono quasi tutte (405 URL degli allegati su 408, 122 moduli su
146, 196 pagine su 203), ma sono `origine='raw'`: le ha create la 02 copiando le vecchie colonne,
o il resolver, e nessuno le ha mai verificate. Il vincolo di §5 (2xx *e* link trovato nella pagina ufficiale) le
tiene non pubblicabili, quindi anon non le legge.

**Cosa vale da oggi, fino a nuovo avviso di news1:**
1. **La 07 è rimandata.** news1 non la propone finché nessun bando aperto o in apertura perde il
   pulsante o gli allegati. Prima di proporla news1 rifà questa misura e la manda a BandoFit.
   Resta la regola di §10: serve anche la conferma scritta che la fase (c) è in produzione.
   **Dal 02/10/2026 (decisione di Michele): l'interruttore del c2 vale anche per i chiusi.** Il c2 va in
   produzione quando la misura di news1 **e** lo script di controllo incrociato di BandoFit (sola lettura, anon key,
   stesso codice della scheda) danno **0 bandi pubblicati, di qualunque stato, che perdono il pulsante o gli
   allegati**. BandoFit prepara il c2 su un branch senza deploy; quando le due misure danno zero, Michele fa il
   deploy del c2 senza altri preavvisi e BandoFit manda la conferma scritta di §10.1.
   **Come si misura** (le due misure devono contare la stessa cosa): per ogni bando di `bando_pubblico`, letto con la
   anon key, si confronta la scheda **c1** (l'ordine del punto 2 con i ripieghi deprecati) con la scheda **c2** (lo
   stesso ordine senza `link_candidatura`, `link_bando` e `allegati`), con la normalizzazione degli URL del punto 2 e
   il filtro degli aggregatori del consumatore. Un bando «perde il pulsante» se in c1 ce l'ha e in c2 no; «perde
   allegati» se un URL degli allegati di c1 manca in c2. I conteggi si danno per stato (aperti, in apertura, chiusi,
   sospesi e revocati) con gli id. Dettagli allineati con lo script di BandoFit (`controllo_incrociato_c2.py`, 02/10):
   su ogni URL del pulsante passa la cintura del consumatore di §5 (un URL scartato fa passare al candidato dopo); la
   fonte ufficiale vale solo con `fonte_ufficiale_stato='trovata'`; fra righe dello stesso tipo vince l'id più basso;
   al più 200 righe di `bando_link` per bando, come la scheda; gli allegati si confrontano a liste intere (righe
   `atto`/`allegato` più jsonb, senza doppioni, **senza** togliere l'URL uguale al pulsante); i gruppi seguono solo
   `stato_effettivo` (aperti, in apertura, chiusi; poi sospesi, revocati e senza stato, a parte). Si riportano anche,
   **solo come informazione** e non come perdita: «cambia pulsante» (la destinazione cambia, URL normalizzati) e
   «perde Fonte ufficiale» (il pulsante secondario perde il ripiego su `link_bando`). Una riga «non passa mai la prova» se `link_verifica` l'ha esaminata in almeno 3
   giri diversi senza renderla pubblicabile: news1 ne manda gli id, così BandoFit decide se dichiararla nella conferma.
   **Chi misura e quando**: la prima misura la fa il lead di news1 la sera del 02/10 (sola lettura, anon key); poi la
   misura diventa **automatica**, un comando di news1 in sola lettura nel giro delle 18 che scrive conteggi e id nella
   riga del giro (contratto interno giro 3, §23, da realizzare). Fino ad allora news1 la ripete a richiesta di
   Michele, senza un passo fisso a mano. La misura di news1 è quella della scheda di BandoFit (ordine del punto 2),
   non quella della scheda di news1, che scarta i `link_candidatura` non `extracted` ed è più severa.
2. **Nella fase (c)** BandoFit legge `bando_pubblico` e `bando_link`, con questo ordine esplicito:
   - **pulsante principale**: riga `tipo='candidatura'` → `link_candidatura` →
     `fonte_ufficiale_url` → riga `tipo='portale'` → `link_bando`. Con quest'ordine nessuno degli
     827 bandi con pulsante lo perde o cambia destinazione;
   - **allegati**: le righe `atto`/`allegato` di `bando_link`, più il jsonb `allegati`, senza
     doppioni per URL. La chiave dei doppioni è la normalizzazione di `bando_normalizza_url`, replicata dal
     consumatore (`url_normalizzato` non è concesso): trim; schema e host minuscoli; via `www.`, porta :80/:443,
     frammento, `utm_*`/`fbclid`/`gclid`/`msclkid`/`_ga` e slash finale; http e https restano diversi. A parità vince
     la riga di `bando_link`. Etichetta: `etichetta` se non vuota, poi `label` del jsonb, poi il nome del file. Ordine:
     righe per id, poi il jsonb nell'ordine dell'array. Si toglie dagli allegati un URL uguale al pulsante. Misura
     del 30/09 alle 17:30 con il filtro reale del consumatore: 433 bandi con almeno un allegato.

   `link_candidatura`, `link_bando` e `allegati` sono colonne deprecate. Restano nella vista fino
   alla (d), ma **senza le garanzie di §5**: 2xx e link visto nella fonte non sono verificati.
3. Chiudere il buco è lavoro di news1, e **richiede codice nuovo**, non solo un comando:
   - oggi nessun codice crea righe `tipo='candidatura'`, mentre la pipeline continua a scrivere
     `link_candidatura` sui bandi nuovi. Senza un intervento il buco cresce a ogni giro;
   - le righe `raw` vanno verificate sulla pagina ufficiale o su quella di riferimento del bando;
   - per i 203 senza fonte bisogna prima trovare la fonte.

   Non ha ancora una data. Quando cambia la copertura, news1 aggiorna questa tabella.

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
- `applicato` / `applicato_at`: `false` = evento **non riversato nella colonna**. Dalla migrazione 14 un evento
  rifiutato perché superato da una transizione più recente o perché la transizione non è più ammessa resta
  `applicato=false` e viene marcato in colonne interne non concesse ad `anon`: la RPC risponde `false` invece di
  sollevare il 23514, e l'evento non torna in coda. Un evento marcato così non è mai leggibile; in rari casi un evento
leggibile può restare `applicato=false` (date incoerenti respinte dalla RPC): il consumatore che mostra date o stati
dagli eventi filtri `applicato=true`.

**Tipi che possono ricevere un cursore (quindi pubblici)**: `pubblicazione`,
`apertura_automatica`, `chiusura_automatica`, `apertura`, `chiusura`, `proroga`, `riapertura`,
`rettifica`, `sospensione`, `revoca`, `annullamento_revoca`, `graduatoria`, `esito`, `faq`,
`nuovo_allegato`, `fonte_ufficiale_verificata`, `data_verificata`, `fusione`, `separazione`,
`cambio_slug`, `ritiro`, `correzione_redazionale`.

**Tipi sempre interni** (mai un cursore, mai leggibili): `segnale_fonte`, `sparito_dalla_fonte`,
`elaborazione_bloccata`, `fonte_ufficiale_non_trovata`, `possibile_doppione`,
`preavviso_collegato`.

**Eventi della verifica dello stato (dalla migrazione 13).** Il produttore rilegge la pagina ufficiale dei bandi
«in apertura» e degli «aperti» senza scadenza. Gli eventi che ne nascono hanno `origine='worker'` e tipi già
elencati sopra; nessun tipo nuovo.

- **Doppia lettura (G7e).** Un evento nato da un lettore strutturato richiede due letture uguali della stessa pagina:
  stesso lettore, stesso URL finale, stessa etichetta e, per le date, stessa data, a **almeno 60 ore** di
  distanza. È la variante ammessa, per il worker, della seconda prova indipendente. Un'interpretazione automatica del
  testo non produce mai `chiusura`, `sospensione`, `riapertura`, `revoca` o `proroga`.
- **`data_verificata` del worker** su un «in apertura»: `campo` fra `data_apertura`, `ora_apertura`,
  `data_scadenza` e `ora_scadenza`, `in_aggiornamenti=false`. Non tocca mai `stato_bando` né `data_pubblicazione` e
  non sovrascrive una colonna già verificata. L'apertura o la chiusura che ne seguono le fa il job orario
  (`apertura_automatica` / `chiusura_automatica`).
- **`rettifica` con `campo='data_scadenza'`** su un «aperto» senza scadenza, quando la pagina ufficiale indica un
  termine certo: `valore_dopo` = `{data_scadenza[, ora_scadenza]}`. Se la data è già passata chiude il job orario.
  Sugli aperti non si usa `data_verificata`.
- **`chiusura` del worker** da «aperto» (già ammessa) e, **dalla 13, anche da «in apertura prossimamente»**: la
  pagina ufficiale dichiara chiuso, scaduto o concluso con un'etichetta strutturata. `data_evento` è la data di
  chiusura letta, se c'è ed è passata o odierna, altrimenti NULL. `data_scadenza` resta intatta. Nessun tetto sul
  numero di chiusure per giro (aggiornamento dell'01/10/2026, regola «niente lotti»): resta il freno automatico per
  ente, che ferma le chiusure di un ente quando sembrano troppe.
- **`in_aggiornamenti`** di `chiusura` e `rettifica` vale `true` solo se la notizia è nuova: lo stesso lettore aveva
  visto il bando aperto (o in apertura) nei 30 giorni prima, e la data letta non è più vecchia di 14 giorni.
  Altrimenti vale `false`: è una **correzione**, leggibile per lo stato ma fuori da un box «Aggiornamenti». La prima
  passata della verifica produce soprattutto correzioni.

**Eventi del giro 3 (dall'01/10/2026, contratto interno `docs/contracts/bandi-giro-3.md`).** Nessun tipo nuovo e
nessuna colonna nuova; cambiano quanti eventi arrivano e da dove.

- **Monitor su tutti i tipi.** Il monitor applica e rende leggibili tutti i tipi pubblici che
  sa riconoscere (apertura, chiusura, proroga, riapertura, rettifica, graduatoria, esito, faq, nuovo_allegato), con
  i suoi gate. `sospensione` e `revoca` si accendono solo dopo la migrazione 14 (`annullamento_revoca` oggi non ha un produttore
  automatico: i revocati sono fuori dal monitor e un revocato sbagliato si corregge con `bando_correggi_stato`), che dà al
  sospeso un'uscita (`sospeso → chiuso`, `sospeso → aperto`), un percorso di correzione con `origine='redazione'` e
  il rifiuto di una sospensione più vecchia dell'ultima transizione. news1 avvisa BandoFit prima della migrazione 14.
- **Rielaborazione dalla fonte ufficiale.** Una volta per ogni coppia (bando, pagina ufficiale) il produttore rilegge
  la pagina e confronta date e classificazione. Le date diverse e non verificate diventano `rettifica` con
  `origine='pipeline'`, `campo` in `data_apertura` / `data_scadenza`, `verificato=false`, `in_aggiornamenti=false`
  (una correzione, fuori dal box «Aggiornamenti»). Mai `data_pubblicazione`, mai uno stato, mai una colonna già
  verificata.
- **Junction riscritte.** La rielaborazione può aggiungere e togliere righe di `bando_regioni`, `bando_settori`,
  `bando_beneficiari`, `bando_codici_ateco` di un pubblicato: prima inserisce le nuove, poi toglie le vecchie, così il
  bando non resta mai senza righe. Una dimensione già piena non si svuota mai. Il consumatore che tiene in cache le
  junction le rilegge come oggi.

**Sincronizzazione.** Si legge per cursore crescente:

```
GET /rest/v1/bando_evento?select=id,bando_id,tipo,campo,valore_prima,valore_dopo,data_evento,rilevato_at,pubblicato_at,cursore,in_aggiornamenti,verificato,url_prova,dominio_prova,applicato&cursore=gt.<ultimo>&order=cursore.asc&limit=1000
```

Come cintura di sicurezza il consumatore rilegge da `<ultimo> − 100` e deduplica per `id`.

**Latenza massima rilevazione → leggibilità**: transizioni del job orario **≤ 65 minuti** dopo
la mezzanotte di Roma (la vista mostra già `chiuso` da mezzanotte); eventi del monitor **≤ 6 ore**
per i bandi aperti e in apertura con fonte ufficiale trovata (dal giro 3, 01/10/2026: il monitor li
controlla tutti a ogni giro, alle 00, 06, 12 e 18), con la cadenza decrescente di §6.1 per i chiusi. La promessa
vale quando il giro precedente ha finito la coda: se il monitor raggiunge il suo tetto di tempo, o un giro salta per
il lucchetto, i bandi rimasti passano per primi al giro dopo e l'attesa può arrivare a 12 ore. Il valore corrente è pubblicato in `pipeline_run` e in questo documento, e cambia solo
con avviso. Un consumatore che sincronizza una volta al giorno somma il proprio intervallo.
Durante la messa in ombra, un evento diventa leggibile alla data di attivazione del suo tipo,
indicata da `pubblicato_at`. **Aggiornamento del 30/09/2026:** con l'attivazione per tipo del giro di ottobre diventano
leggibili solo gli eventi nati dopo l'attivazione. L'arretrato raccolto in ombra **non** si pubblica.

### 6.2 `bando_fusione`

`bando_fusione(bando_id, slug_originale, master_id, master_slug, motivo, fuso_at)`, leggibile su
tutte le righe. Da un `bando_id` o da uno slug salvato prima della fusione si risale al master;
la riga resta finché il doppione non viene separato (`bando_separa` la cancella, porta a «annullato» il 301 dello
storico e lascia sul master i link copiati); le catene vengono appiattite dal produttore, quindi `master_id` è
sempre il master corrente. `fuso_at` non cambia quando una catena viene appiattita: non segnala i cambiamenti.
La fusione è atomica rispetto alla vista (una sola transazione). Dopo una fusione le righe `bando_link` del
doppione si **copiano** sul master (a parità di URL normalizzato vince il master), mentre le junction restano sul
doppione: link e junction si leggono solo per gli id presenti nella vista. Primo allineamento:
`order=bando_id.asc&limit=1000`, poi `bando_id=gt.<ultimo>`; una riconciliazione periodica per id su
`bando_fusione` equivale al cursore sugli eventi `fusione`.

**Separazione.** L'evento `separazione` nasce solo sul bando separato: origine `redazione`, campo
`bando_master_id`, `in_aggiornamenti=false`, `valore_prima` NULL, `valore_dopo` `{"master_id": null,
"separato_da": <ex master>}`. Riceve il cursore solo se il bando torna subito pubblicato. Il bando torna nella vista
con lo stesso id, slug e `pubblicato_at`. Lato consumatore si ripristina (inverso della rimappatura) solo se il
doppione è di nuovo in `bando_pubblico`; mai verso un id assente dalla vista, e mai cancellando righe dell'utente
sul master. news1 avvisa prima di ogni separazione.

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

**Fusioni automatiche (dal giro 2).** Il produttore fonde da solo i doppioni **certi**, con la stessa `bando_fondi`
delle fusioni a mano: nessuna riga cancellata, id e slug congelati, il doppione in 301 verso il master, una riga in
`bando_fusione` e un evento `fusione`. Per il consumatore non cambia niente rispetto a §6.2: la rimappatura e la
risoluzione dei miss restano le stesse.

- **Criteri esatti** (basta uno):
  - stesso URL normalizzato;
  - stessa riga di calendario della stessa fonte: nessun link sulla scheda di entrambe, la stessa descrizione del
    calendario (almeno tre parole), e lo stesso URL d'origine oppure la stessa data di chiusura.
- **Guardie di prudenza**, che valgono per ogni fusione automatica:
  - per l'URL comune, l'URL compare in esattamente due pubblicati (tre o più vuol dire pagina indice o lotti), i
    titoli sono simili e la scadenza è uguale o manca su una delle due;
  - nessuna fusione se i titoli differiscono per anno, lotto, edizione, annualità, finestra o tranche;
  - un doppione si fonde solo con una coppia diretta con il master; i gruppi di più di due righe restano a mano.
- **Ritmo (aggiornamento dell'01/10/2026, giro 3):** fra pubblicati, a **ogni giro**, **senza tetto** sul numero
  di fusioni (regola «niente lotti»). Le guardie di prudenza qui sopra restano tutte. Le fusioni prima della
  pubblicazione (sotto) avvengono anch'esse a ogni giro, quando arriva la riga nuova.
- **Volume atteso all'attivazione:** 52 fusioni, misurate in prova il 01/10/2026 con tutte le guardie, comprese
  quelle su lotti e numerazioni (43 per URL e 9 di calendario). Arrivano **tutte nel primo giro** dopo
  l'attivazione; poi poche al mese.
- **Prima della pubblicazione:** una riga nuova gemella esatta di un pubblicato **non viene mai pubblicata**: si
  fonde prima, con la stessa `bando_fondi`, a ogni giro e senza il tetto giornaliero. Nella vista non compare mai, ma
  lascia tracce leggibili:
  - una riga in `bando_fusione` con `slug_originale` NULL: la riga non ha mai avuto uno slug pubblico e nessun
    utente può averla salvata, quindi nella rimappatura si ignora;
  - gli eventi `fusione`: quello del master e quello del doppione, che ha un `bando_id` mai visto nella vista e si
    ignora anche lui;
  - i link del doppione copiati sul master, e `ultimo_cambiamento_at` del master che avanza.
- **Avviso (aggiornamento dell'01/10/2026).** Il proprietario dei due progetti ha deciso di avvisare BandoFit
  direttamente e di attivare le fusioni automatiche al deploy del giro 3, **senza i 7 giorni** di preavviso. Da lì
  sono continue e il consumatore le segue con la riconciliazione su `bando_fusione` o con il cursore degli eventi
  `fusione`. Non esistono più «lotti straordinari»: ogni fusione certa avviene al primo giro utile.

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

**Paginazione.** Con `Prefer: count=exact`, un offset oltre il numero di righe risponde HTTP 416 `PGRST103`, non
200 `[]`: chi pagina due segmenti salta la query quando offset ≥ count del segmento, oppure tratta `PGRST103` come
pagina vuota. **Identificatori.** `bando.id` è int4 (massimo 2^31-1, oggi 1 262 520); gli id hanno buchi ampi e non
misurano il numero di righe; un cambio di tipo è un cambio di contratto annunciato.

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
| **(d)** | conferma scritta che la (c) è in produzione, **e** la misura di §5.1 senza bandi aperti o in apertura che perdono pulsante o allegati | migrazione 07: RLS su `pubblicato`, REVOKE di colonna su `bando`, vista senza le colonne deprecate |

**Stato al 30/09/2026.** La fase (c) di BandoFit, passo **c1**, è in produzione dal 30/09/2026 (commit 878acb0 e
f5e232d di BandoFit, conferma scritta del 30/09). Legge `bando_pubblico`, `bando_link`, `bando_slug_storico` e
`bando_fusione`, mai la tabella `bando`. Mantiene i ripieghi deprecati di §5.1 e rimappa i fusi con una
riconciliazione oraria su `bando_fusione`. Il passo **c2**, cioè togliere i ripieghi, parte dopo una nuova misura di
§5.1 annunciata con almeno 7 giorni di preavviso; solo dopo il c2 si propone la 07. **Dal 02/10/2026** il preavviso
di 7 giorni è tolto: il c2 si prepara in parallelo e parte con l'interruttore di §5.1 (zero perdite su tutti i
pubblicati, misura di news1 e script di BandoFit). Prima di una separazione news1
avvisa BandoFit. Le fusioni automatiche invece sono continue dal giro 3 (§6.2) e non richiedono un avviso per
lotto.

**Conferma scritta del c2** (quella che sblocca la proposta della 07): data del deploy e commit; i punti 1-5 della
precondizione in testa alla 07; la dichiarazione che nessun percorso (elenco, dettaglio, alert, calendario,
rimappatura, partenariati, AI-check, script) legge la tabella `bando` né una delle 7 colonne tolte dalla 07; le
richieste R1-R8 prese dai log di produzione; la rimappatura attiva con l'ultimo report; il degrado su 42703/PGRST
senza 5xx. Chiarimenti (01/10 notte, chiesti da BandoFit): il degrado riguarda solo gli errori dovuti a un cambio di
schema (42703, PGRST103/200/201/204/205), mentre i guasti veri (PGRST000-002, rete, 57014) restano 502/504; per
R1-R8 vale la stampa del codice reale (`--come-inviata`, con commit e data) più un estratto dei log del gateway del
DB bandi, una richiesta per ciascuna, quando Michele lo apre. news1 riesegue con la anon key i controlli (c) di §11 prima di proporre la 07 e quelli (d) subito dopo, e
avvisa BandoFit prima della prima applicazione attiva di sospensioni o revoche.

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

**Dal giro 2 l'ordine prosegue: 11 → 12 → 13, e la 07 solo dopo la 13** (la 07 e il suo rollback si fermano se la 13 manca; la 13 si ferma se la 07 è già applicata).

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
| `bando_v11_12_monitoraggio.sql` | fuori dalle fasi: si applica dopo la 11 e non dipende dalla 07 | l'interfaccia di monitoraggio di §14: le tabelle interne `monitoraggio_riepilogo` e `monitoraggio_chiave` (RLS, nessun privilegio ad `anon` né ad `authenticated`; su `monitoraggio_riepilogo` il ruolo di servizio ha solo `SELECT`, `INSERT` e `UPDATE`, senza `DELETE` né `TRUNCATE`; su `monitoraggio_chiave` nessun privilegio nemmeno al ruolo di servizio), la funzione interna `monitoraggio_job_orario()` e la funzione a chiave `monitoraggio_catalogo(p_chiave)`, eseguibile da `anon`. Il blocco di verifica controlla che l'insieme delle funzioni eseguibili da `anon` cresca solo di `monitoraggio_catalogo` | **No**: solo oggetti nuovi; nessuna tabella, colonna, vista o funzione esistente cambia |
| `bando_v11_14_sospensioni.sql` | fuori dalle fasi: dopo la 13 (giro 3) | quattro righe nuove nella lista bianca (`sospeso → chiuso` con `chiusura`; `revocato → aperto \| chiuso \| in apertura prossimamente` con `annullamento_revoca`); dal sospeso e dal revocato si esce solo con l'evento della riga; la RPC `bando_correggi_stato(p_bando_id, p_stato, p_nota)` solo per il ruolo di servizio, che registra e applica un evento `correzione_redazionale` (origine `redazione`, `campo='stato_bando'`, `valore_dopo` = lo stato come stringa JSON, cioè la stessa forma scalare del job orario con `campo='stato_bando'`, `in_aggiornamenti=false`, leggibile); la regola del «superato» e tre colonne interne di marcatura su `bando_evento`; il marcatore `bando_capacita_sospensioni()`. Dopo la 14 non si rieseguono la 04, la 11 e la 13 | **No**: nessuna colonna concessa ad `anon` cambia; compaiono eventi `chiusura` su un sospeso e `correzione_redazionale`. La regola di `stato_effettivo` non cambia |
| `bando_v11_13_stato_da_verificare.sql` | (b), dopo la 12 e prima della 07 | 17 colonne interne di `bando_controllo` per la verifica dello stato, di cui 9 leggibili da `anon` (quelle che la vista usa), con i loro CHECK e un trigger che scarta le letture fatte su domini non verificanti; la funzione pura `bando_stato_da_verificare` (eseguibile da `anon`, §1.6); le cinque colonne in coda a `bando_pubblico` (§3, §4.1); la riga della lista bianca «chiusura del worker da in apertura» (§6.1). Si controlla da sola: casi della regola, funzioni di `anon`, conteggi per stato, colonne | **No**: colonne in coda, select esplicite invariate; `select=*` riceve cinque colonne in più. Dopo la 13 la 07 e il suo rollback la richiedono, perché le loro viste portano le stesse cinque colonne |

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
- nessuna funzione dello schema `public` eseguibile da `anon` oltre a quelle di `pg_trgm`, alle
  tre dell'allowlist (`bando_stato_effettivo`, `dominio_di`, `bando_host_aggregatore`), dalla
  12 a `monitoraggio_catalogo` e, dalla 13, a `bando_stato_da_verificare`.

**Dopo la 12** (con la anon key; la chiave vera si usa solo nell'ultima richiesta, dal backend, e mai in un URL):

- `POST /rest/v1/rpc/monitoraggio_catalogo` con `{"p_chiave": "<una chiave inventata di 40 caratteri>"}` → **401**
  con `code` **42501** e `message` `non autorizzato`;
- `GET /rest/v1/rpc/monitoraggio_catalogo?p_chiave=<una chiave inventata>` → **401**, `code` **42501**. Una
  `GET` riceve la stessa risposta anche con la chiave giusta: per questo la chiave vera non va mai provata in
  `GET`;
- `monitoraggio_riepilogo?select=id` e `monitoraggio_chiave?select=nome` → **401**, `code` **42501**;
- `POST /rest/v1/rpc/monitoraggio_job_orario` → **401**, `code` **42501**;
- `POST /rest/v1/rpc/monitoraggio_catalogo` con la chiave giusta, dal backend → **200**, `versione` = 1 e le 11
  chiavi di `riepilogo` di §14.4, oppure `riepilogo: null` se il primo riepilogo non è ancora stato calcolato.

**Dopo la 13** (con la anon key):

- le otto richieste del §12 restituiscono le stesse risposte di prima (colonne, embed, `Content-Range`): le colonne
  nuove stanno in coda e una select esplicita non le vede;
- `bando_pubblico?select=id,stato_da_verificare,stato_letto,stato_letto_at,termine_indicato,termine_indicato_fonte&limit=1`
  → **200**;
- `bando_pubblico?select=id&stato_effettivo=eq.aperto` e `…=eq.in apertura prossimamente` con `count=exact` →
  gli stessi `Content-Range` di prima della 13: nessun bando cambia stato;
- `bando_pubblico?select=stato_da_verificare&stato_da_verificare=not.is.null&stato_da_verificare=neq.data_apertura_passata`
  → **0 righe** finché il controllo del produttore è in prova (§4.1): in prova l'unico motivo possibile è
  `data_apertura_passata`;
- `bando_pubblico?select=stato_da_verificare&stato_da_verificare=not.in.(data_apertura_passata,smentito_dalla_fonte,previsione_scaduta,senza_conferma,termine_passato)`
  → **0 righe**, sempre;
- `bando_controllo?select=stato_letto_url` e `bando_controllo?select=lettura_stato` → **401**, `code` **42501**:
  le colonne interne della lettura non sono concesse.

**Dopo l'attivazione della verifica dello stato** (il controllo gira alle 06 e alle 18; `<oggi>` è la data di Roma):

- il produttore, con la chiave di servizio: `bando_controllo?select=bando_id&esaminato_attivo_at=not.is.null` con
  `count=exact` → più di 0 righe dopo il primo giro in esecuzione, e cresce a ogni giro. Senza questo, nessun
  `senza_conferma` può comparire (§4.1);
- `bando_pubblico?select=id&stato_da_verificare=eq.senza_conferma&stato_effettivo=eq.aperto&pubblicato_at=gt.<oggi − 7 giorni>`
  → righe **solo** per bandi segnalati dal portale aggregatore (§4.1, ramo «aperto», punto 5): senza quel segnale,
  sugli aperti `senza_conferma` compare solo dal 7° giorno dopo la pubblicazione. Il segnale non è nella vista: il
  produttore lo controlla con la chiave di servizio su `bando_controllo.segnale_aggregatore_at`;
- il produttore, con la chiave di servizio (anche il monitor scrive eventi `worker`, e `metodo` non è concesso ad
  `anon`): `bando_evento?select=id&origine=eq.worker&tipo=eq.chiusura&metodo=like.estrattore:*&rilevato_at=gte.<oggi>`
  → nessun tetto per numero dal giro 3 (01/10/2026): il controllo è che ogni riga abbia `url_prova` su un dominio
  ufficiale e che nessun ente superi il freno automatico;
- stessa richiesta con `tipo=in.(chiusura,rettifica)` e `select=id,in_aggiornamenti,data_evento,rilevato_at`:
  ogni evento del passo con `in_aggiornamenti=true` ha `data_evento` NULL oppure non più vecchia di 14 giorni
  rispetto a `rilevato_at` (§6.1: solo così è una notizia nuova). A titolo indicativo, nella prima passata quasi
  tutte le righe hanno `in_aggiornamenti=false` (correzioni);
- `bando_fusione?select=bando_id&fuso_at=gte.<oggi>&slug_originale=not.is.null` → nessun tetto per numero dal giro
  3 (le fusioni fra pubblicati girano a ogni giro; il primo giro dopo l'attivazione porta le circa 52 misurate
  l'01/10), e per ogni riga un evento `fusione` leggibile per cursore.
  Le righe con `slug_originale` NULL sono fusioni prima della pubblicazione: non hanno tetto e si ignorano (§6.2).

**Nella fase (c)**: le stesse richieste, rieseguite **sulla vista**, non danno nessun `57014` e hanno un p95 lato
client sotto 3 s su almeno 20 ripetizioni a connessione calda (ogni picco singolo oltre 3 s si riporta a parte);
restituiscono `stato_effettivo` e `fonte_ufficiale_url`; per un `id` fuso la vista non
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

Il predicato di pubblicazione compare in sette punti (riletti il 29/09/2026 sul `main` di
BandoFit): completo, `stato_processing=eq.completed&slug=not.is.null`, in
`services/bandi_service.py:151`, `services/saved_bandi_service.py:202-203` (insieme a
`id=in.(…)`, R5-a) e `services/bando_alert_service.py:222-223`; nella forma
`stato_processing=eq.completed&slug=eq.<slug>` in `services/bandi_service.py:386-387` e
`:410-411`, `services/saved_bandi_service.py:59-60`, `services/calendar_service.py:126-127`. Nelle
prime righe della fase (c) è quello da togliere, perché la vista è già filtrata.

**Aggiornamento del 29/09/2026: le richieste dopo R0-a (BandoFit `a9d520a`).**
- R1, R2, R3 e R7 portano un parametro in più, su entrambi i segmenti:
  `or=(stato_bando.in.("aperto","in apertura prossimamente","chiuso"),stato_bando.is.null)`.
  Viene da `_solo_stati_segmentati` (`services/bandi_service.py:207`), usata da
  `apply_open_tier` (`:213`) e `apply_closed_tier` (`:223`); gli alert la ricevono da
  `carica_candidati` (`services/bando_alert_service.py:214`, via `apply_open_tier` alla `:225`).
- Il client manda gli spazi come `+`, non come `%20`: per PostgREST è lo stesso.
- Misurato il 29/09 con la anon key, la «Versione (c)» di R3 su `bando_pubblico` (FTS su
  `ricerca`, segmento su `stato_effettivo`, quattro `!inner`, `count=exact`) risponde in circa
  70-200 ms di mediana e al massimo 360 ms su 5 ripetizioni per termine.

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

*Nota del 30/09/2026:* la forma con tutti i filtri può dare 0 righe: misura il piano, non la correttezza. La
correttezza si verifica con una forma larga (per esempio regioni 12 e 9, settori 39 e 78, beneficiari 16 e 27, ATECO
76 e 1). L'id ATECO 881 dell'esempio originale non esiste ed è stato sostituito con 76.

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
    &f_ate.codice_ateco_id=in.(76)
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
cursore gli eventi `proroga`, `rettifica` e, dalla migrazione 13, `data_verificata` con `campo='data_scadenza'`
(§6.1).

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

---

## 14. Interfaccia di monitoraggio

Dalla migrazione 12. Serve a un pannello di amministrazione che mostra se la raccolta dei bandi sta funzionando.
Espone **un solo riepilogo neutro**: niente dati di spesa, niente indirizzi, nomi di processi, testi d'errore, titoli
o slug. Questa sezione è autosufficiente e si può copiare così com'è nella documentazione del consumatore.

### 14.1 Firma e chiamata

- Funzione: `public.monitoraggio_catalogo(p_chiave text) RETURNS jsonb`. Legge e basta, non scrive niente.
- Chiamata, **solo dal backend** del consumatore:

  ```
  POST /rest/v1/rpc/monitoraggio_catalogo
  apikey: <anon key>
  Authorization: Bearer <anon key>
  Content-Type: application/json

  {"p_chiave": "<chiave di monitoraggio>"}
  ```

- **Solo `POST`.** Una `GET` riceve **42501** anche con la chiave giusta, e metterebbe la chiave in un URL.
- **La chiave di monitoraggio** è una stringa di 32-256 caratteri che il produttore consegna per un canale privato.
  Il DB ne conserva solo l'impronta (sha256). Va tenuta in una variabile d'ambiente protetta del backend e non deve
  mai finire nel browser, nel bundle, in un URL, in un log, in un messaggio d'errore o in un report.
- **Frequenza:** al massimo **una chiamata al minuto**. Il riepilogo si ricalcola circa ogni 15 minuti: chiamare più
  spesso non porta dati nuovi.

### 14.2 Errori

`42501` e gli errori di autenticazione di PostgREST arrivano **entrambi come HTTP 401**. Si distinguono **dal
corpo della risposta**, mai dal solo codice HTTP.

| caso | HTTP | corpo | cosa mostrare |
|---|---|---|---|
| chiave non configurata nel backend del consumatore | — | nessuna chiamata: il backend **non chiama** | «monitoraggio non configurato»: errore di configurazione, **non** «non raggiungibile» |
| `p_chiave` presente ma `null`, vuota, corta, lunga, errata o chiusa; metodo diverso da `POST` | 401 | `"code": "42501"`, `"message": "non autorizzato"`, sempre uguale | «chiave di monitoraggio non valida»: da correggere nella configurazione del consumatore |
| corpo **senza** il campo `p_chiave` (per esempio `{}`) | 404 | `"code": "PGRST202"`: PostgREST cerca una funzione senza parametri e non la trova | non deve succedere se il backend non chiama senza chiave; se succede, è un errore del consumatore |
| anon key non valida o scaduta | 401 | `"code"` che inizia con `PGRST3` (per esempio `PGRST301`), oppure un corpo **senza** `code` restituito dal gateway prima di PostgREST | «accesso al DB non valido» |
| funzione assente (migrazione 12 non applicata o tolta), con un corpo che contiene `p_chiave` | 404 | `"code": "PGRST202"` | «interfaccia non ancora disponibile» |
| rete, timeout, HTTP 5xx | — | — | «monitoraggio non raggiungibile» |

Il messaggio `non autorizzato` è identico in tutti i casi di rifiuto: il DB non dice se il problema è la chiave o il
metodo.

### 14.3 Busta, versione 1

| campo | tipo | significato |
|---|---|---|
| `versione` | `1` | versione della busta e dello schema del riepilogo |
| `generato_at` | ISO 8601 | ora del DB al momento della risposta |
| `calcolato_at` | ISO 8601 o `null` | ora in cui il produttore ha calcolato il riepilogo, col suo orologio. Solo informativa |
| `aggiornato_at` | ISO 8601 o `null` | ora del DB in cui il riepilogo è stato scritto: è il riferimento per il ritardo |
| `minuti_dal_calcolo` | intero o `null` | minuti interi trascorsi da `aggiornato_at` |
| `in_ritardo` | booleano | `true` se il riepilogo è più vecchio della soglia (oggi 45 minuti) o non esiste ancora. Il pannello mostra un banner «dati non aggiornati» sopra tutto il resto |
| `orologio_disallineato` | booleano o `null` | `true` se `calcolato_at` e `aggiornato_at` differiscono di più di 5 minuti. Informativo |
| `riepilogo` | oggetto o `null` | `null` finché il primo riepilogo non è stato calcolato; altrimenti le 11 chiavi di §14.4 |

Senza un riepilogo la busta vale `riepilogo: null`, `in_ritardo: true` e `null` negli altri campi, tranne
`versione` e `generato_at`.

### 14.4 Riepilogo, schema v1

Undici chiavi di primo livello. `stato` riassume tutto il resto:
- `guasto` se c'è almeno un segnale di livello `allarme`;
- `attenzione` se c'è almeno un `avviso`;
- altrimenti `ok`.

Una misura in `non_misurati` non cambia lo stato: dice solo che quella parte oggi non si può osservare.

| chiave | forma |
|---|---|
| `stato` | `ok` \| `attenzione` \| `guasto` |
| `segnali` | al massimo 40 oggetti `{codice, livello, testo, dal, misura}` |
| `non_misurati` | sottoinsieme di `servizio`, `job_orario`, `accesso_fonte_riservata`, `credito_ricerca`, `schede_con_sezione`, `da_verificare` |
| `produttore` | `{ultimo_giro_at, ore_dall_ultimo_giro, giri_24h, riavvii_24h, servizio}`, con `servizio` ∈ `attivo` \| `non_attivo` \| `non_misurato` |
| `giri` | al massimo 20 oggetti `{id, giro, avviato_at, concluso_at, durata_min, esito, interrotto_per_tetto, passi_non_ok}`. Valori ammessi: `giro` ∈ `00` \| `06` \| `12` \| `18` \| `avvio` \| `manuale`; `esito` ∈ `ok` \| `errore` \| `saltato` \| `interrotto_per_tetto`; `passi_non_ok` è una lista di nomi neutri (`ingresso`, `lettura`, `estrazione`, `arricchimento`, `ricerca_fonti`, `redazione`, `controllo_pagine`, `ricontrolli`, `verifica_stato`, e dal giro 3 `elenco_enti`, `ricerca_fonti_precoce`, `verifica_ingresso`, `verifica_link`, `rielaborazione`, `doppioni`; `altro` per un nome sconosciuto). Dal giro 3 esiste anche il codice `copertura_incompleta:<passo neutro>`: lo stesso passo ha lasciato bandi fuori in 4 giri di fila |
| `controlli` | al massimo 10 oggetti `{avviato_at, esito, classificazioni, classificazioni_fallite, eventi_non_applicati}` |
| `lavorazioni` | al massimo 10 oggetti `{nome, da_min, ttl_min, stato}`, con `nome` ∈ `giro` \| `controllo_pagine` \| `ricerca_fonti` \| `altro` e `stato` ∈ `regolare` \| `lunga` \| `probabile_orfana` |
| `ingresso` | `{fermi_in_ingresso, fermi_in_lavorazione, ultimo_bando_nuovo_at}` |
| `eventi` | `{ammessi_non_applicati, proposte_7g, in_attesa_pubblicazione}` |
| `da_verificare` | oggetto o `null`. Vale **`null` finché la verifica dello stato del produttore non è attiva**, anche dopo la migrazione 13 (in prova, cioè in ombra, è sempre `null`); finché è `null`, `da_verificare` compare anche in `non_misurati`. Dall'attivazione è l'oggetto `{in_apertura, aperto, proposte_in_ombra_per_tipo, chiusure_applicate_7g, host_frenati, pagine_rimosse, forse_non_bandi}` descritto qui sotto |

**`da_verificare`, dall'attivazione.** Tutti i numeri sono conteggi interi non negativi; negli oggetti `{chiave: n}`
compaiono solo le chiavi con `n` maggiore di zero, quindi un oggetto vuoto vuol dire «nessuno».
- `in_apertura` e `aperto`: `{motivo: n}`, i pubblicati con un motivo di §4.1, divisi per ramo secondo
  `stato_effettivo` (un «in apertura» con l'apertura già raggiunta sta in `aperto`). `motivo` ∈
  `data_apertura_passata` \| `smentito_dalla_fonte` \| `previsione_scaduta` \| `senza_conferma` \| `termine_passato`;
- `proposte_in_ombra_per_tipo`: `{tipo: n}`, le proposte dell'ultimo passo del controllo rimaste senza effetto (tetto
  o freno), con `tipo` ∈ `chiusura` \| `rettifica` \| `data_verificata` \| `apertura`;
- `chiusure_applicate_7g`: le chiusure applicate dal produttore negli ultimi 7 giorni;
- `host_frenati`: gli host il cui lettore è stato frenato nell'ultimo passo;
- `pagine_rimosse`: le pagine ufficiali trovate rimosse nell'ultimo passo;
- `forse_non_bandi`: le pagine lette nell'ultimo passo che non sembrano parlare del bando.

Il tipo «oggetto o `null`» vale già nella versione 1: il passaggio da `null` all'oggetto all'attivazione **non cambia
`versione`** e non è un cambio di tipo nel senso di §14.5. L'attivazione si annuncia comunque con l'avviso di §10.1.
| `job_orario` | `{ultimo_avvio_at, ultimo_esito, ultimo_ok_at, falliti_24h}`, con `ultimo_esito` ∈ `succeeded` \| `failed` \| `non_misurato` |

**I segnali:**
- `codice` è un identificatore stabile, nella forma `[a-z_]+` con un suffisso facoltativo `:[a-z0-9_]+`, per
  esempio `produttore_fermo` o `passo_degradato:redazione`;
- `livello` vale `allarme` o `avviso`;
- `testo` è una frase italiana fissa, già pronta per essere mostrata così com'è;
- `dal` è l'istante (ISO 8601) da cui il segnale è acceso senza interruzioni;
- `misura` è il numero che ha fatto scattare il segnale (una quota fra 0 e 1, un conteggio, ore o minuti, a seconda
  del codice), oppure `null`. I segnali che riguardano la spesa hanno sempre `misura: null` e un testo senza numeri.

**Regole di contenuto:**
- ogni stringa del riepilogo viene da un'enumerazione, da un istante ISO 8601 in UTC o da un testo fisso;
- non compaiono mai URL, host, nomi di processi o di servizi, testi d'eccezione, titoli, slug o importi di spesa.

Esempio, ridotto:

```json
{
  "versione": 1,
  "generato_at": "2026-10-02T08:21:04+00:00",
  "calcolato_at": "2026-10-02T08:05:11+00:00",
  "aggiornato_at": "2026-10-02T08:05:12+00:00",
  "minuti_dal_calcolo": 15,
  "in_ritardo": false,
  "orologio_disallineato": false,
  "riepilogo": {
    "stato": "attenzione",
    "segnali": [{"codice": "fermi_in_lavorazione", "livello": "avviso",
                 "testo": "Alcuni bandi sono fermi in lavorazione da più di 13 ore.",
                 "dal": "2026-10-02T06:05:10+00:00", "misura": 3}],
    "non_misurati": [],
    "produttore": {"ultimo_giro_at": "2026-10-02T04:09:40+00:00", "ore_dall_ultimo_giro": 4.2,
                   "giri_24h": 4, "riavvii_24h": 0, "servizio": "attivo"},
    "giri": [], "controlli": [], "lavorazioni": [],
    "ingresso": {"fermi_in_ingresso": 0, "fermi_in_lavorazione": 3,
                 "ultimo_bando_nuovo_at": "2026-10-01T16:02:00+00:00"},
    "eventi": {"ammessi_non_applicati": 0, "proposte_7g": 12, "in_attesa_pubblicazione": 0},
    "da_verificare": null,
    "job_orario": {"ultimo_avvio_at": "2026-10-02T08:05:00+00:00", "ultimo_esito": "succeeded",
                   "ultimo_ok_at": "2026-10-02T08:05:01+00:00", "falliti_24h": 0}
  }
}
```

Il testo del segnale dell'esempio è illustrativo: i testi veri sono quelli che arrivano nella risposta.

### 14.5 Evoluzione

- **Senza preavviso** possono comparire:
  - chiavi nuove, nella busta, nel riepilogo e negli oggetti annidati;
  - codici di segnale nuovi;
  - valori nuovi in un'enumerazione.

  Il consumatore ignora le chiavi che non conosce e mostra un segnale sconosciuto con il suo `testo` e il suo
  `livello`.
- **Togliere o rinominare una chiave, o cambiarne il tipo, richiede `versione: 2`**, annunciata per iscritto prima
  del rilascio. Il consumatore che riceve una versione diversa da quella che conosce mostra «formato del
  monitoraggio non supportato» invece di interpretare i dati.

### 14.6 Chiavi e rotazione

- Il DB può tenere **più chiavi valide insieme**, una riga ciascuna (se ne conserva solo l'impronta).
- In via ordinaria una chiave **non scade**. La data di chiusura serve solo a chiudere la chiave vecchia durante una
  rotazione.
- **Rotazione:**
  1. il produttore crea una seconda chiave e la consegna per un canale privato;
  2. il consumatore la mette in produzione e lo conferma;
  3. il produttore chiude la vecchia, che da quel momento riceve **42501**.

  Fra il passo 1 e il 3 valgono entrambe, quindi non c'è un momento senza accesso.
- **Se una chiave trapela**, il produttore la chiude subito. Il consumatore riceve 42501 finché non ha la nuova.
