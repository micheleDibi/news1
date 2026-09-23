# Intervento «fonti ufficiali e bandi attivi» — registro di avanzamento

Fonte di verità del progetto: il file di piano della sessione Claude
(`~/.claude/plans/pasted-content-id-dcf2-sei-un-wondrous-seal.md`, §12.4 per i checkpoint).
Questo registro sopravvive al cambio di macchina e lo vede chi fa commit. Le date sono Europe/Rome.

## Stato per fase (§9 del piano)

| Fase | Stato | Note |
|---|---|---|
| Piano (Fase 0, Design 1-2, Verify-1) | [x] chiuso 22/09/2026 ~19:50 | approvato dal committente («ok procedi pure») |
| P0 rotazione password OE | [ ] a carico del committente | precondizione della bonifica dei file (README, legacy) |
| A — codice, nessun DB | [x] **chiusa il 23/09/2026**: tappe 0-6 fatte, verifica finale della consegna eseguita e correzioni applicate | 1226 test Python, 381 npm, 26 backend, tsc 51 |
| B — migrazioni (b) | [ ] | il committente applica 01-05 + seed nel SQL Editor |
| C — ombra 14 gg | [ ] | |
| D — attivazione per tipo | [ ] | |
| E — R0 BandoFit → 06 | [ ] | |
| F — (c) → 07 | [ ] | |

## Tappe della fase A

| # | Tappa | Stato | Test |
|---|---|---|---|
| 0 | Verify-2 (fondamenta, SEO/URL, completezza, BandoFit) e correzioni al piano | [x] 23/09: 3 bloccanti + 11 alti + 25 medi + 10 bassi applicati (piano §16) | — |
| 1 | SQL `backend/sql/bando_v11_01…07` + seed + rollback (scritte, non eseguite); `docs/contratto-db-bandi.md` | [x] scritte il 23/09; verifica avversariale in corso (wf_ec3538ee-9ab) | lettura + blocchi Verifica |
| 2 | Fondamenta Python: `casi.json` + stato nei tre linguaggi, `scarico`, `bilancio`, `registro`, `blocco`, `telemetria`, `db.controllo`, bug fix §8.a | [x] 23/09 — 378 test verdi; resta `segnali.py` e l'innesto nel runner (tappa 4) | `npm run test:py:bandi` |
| 3 | Resolver completo (moduli puri + `oe_scheda`, `fonte_ufficiale`, cascata, CLI, step 5) | [x] 23/09 | idem |
| 4 | Monitor: `segnali`, `eventi`, `monitoraggio`, `rigenera`, comandi d'ombra e di lotto (`backfill.py`), adattatori G7, innesto nel runner e step 7 | [x] 23/09 | idem |
| 5 | Frontend F1 + API v1.1 + test TS; rimozione `/eu-funding` e codice morto | [x] 23/09 — 372 test npm verdi, tsc 51 | `npm test`, `tsc` ≤ 54 |
| 6 | Documentazione, README `scraper_bandi`, deroga in CLAUDE.md, bonifica credenziali | [x] 23/09 — credenziali rimosse dai file tracciati (grep = 0) con nota di rotazione; deroga registrata | grep credenziali = 0 |

## Bug fix di §8.a applicati (23/09, tutti con test)

`scarico` della cache Firecrawl, troncamento a 4 000, adapter OE/Italia Domani/CSV/hybrid, login OE senza ripiego anonimo + validazione sessione + redazione dei log, `_do_one` a 4 elementi, `asyncio` in `db.py` e `DEDUP_CANONICAL` spento, refine senza «aperto» di ripiego, date con ruolo (`estrai_date_con_ruolo`, `norm_cit`) e `validate_date_candidate` sugli intervalli, `oggi_roma`, prompt senza date cablate, `--dry-run`/`--limit` su discover e scrape-bandi, `hash_senza_link`, IndexNow fail-closed.

## Runbook dei lotti di riallineamento (fase C, in ombra)

Tutti i comandi si lanciano sul server, dalla cartella del progetto, con l'interprete del venv:

```bash
cd /root/projects/news1/scraper_bandi
.venv/bin/python -m app <comando>
```

Regole valide per tutti: si prova sempre prima con `--dry-run` e un `--limit` piccolo, si legge
l'ultima riga («counters finali») e solo allora si rilancia senza `--dry-run`. Senza `--attivo`
i comandi restano in **ombra**: leggono, misurano e registrano, ma non toccano le colonne
editoriali. Se un comando dice «lock occupato» sta girando la pipeline: si riprova dopo.

In ombra **solo due comandi avanzano da soli**: `risolvi-fonte` e `monitor`, perché il loro
marcatore è tecnico (`bando_controllo.ultimo_controllo_at`) e si scrive fuori dal ramo `attivo`.
Tutti gli altri comandi a lotti scrivono il proprio marcatore soltanto in attivo — `oe-dettaglio`
la riga di `bando_link`, `link-verifica` l'`esito_http`, `applica-eventi` l'applicazione, i tre di
§6.4 il `contenuto` o lo stato — e in ombra vanno mossi a mano con `--offset`, altrimenti ogni
lancio rifà le stesse prime N righe. Il caso che costa è `oe-dettaglio`: le schede le scarica
comunque, e consumano `OE_SCHEDE_GIORNO` (vedi il passo 2).

Per lo stesso motivo la colonna «come si capisce che è andato» della tabella qui sotto descrive il
lancio **in attivo**: in ombra i passi 3, 4, 8 e 10 misurano e riferiscono, e nel database non
cambia niente.

### `--limit` conta il lavoro, `--offset` sposta il blocco (23/09/2026)

Fino al 23/09 `--limit N` voleva dire «guarda le prime N righe della selezione», e la selezione
ordina per `id`. Due lanci di fila davano gli stessi contatori e il lotto non finiva mai: misurato
su `oe-dettaglio --backlog --forza --limit 800`, lanciato due volte con esito identico (800
esaminati, 799 scaricate, 1866 link) e 799 bandi coperti su 1723.

Ora, su **tutti** i comandi a lotti, il `--limit` conta le righe su cui c'è davvero del lavoro: la
selezione si scorre a pagine e le righe già lavorate finiscono in un contatore a parte
(`saltate` / `saltati` / `bloccati`, più `attraversate` che dice quante ne sono state guardate).
Leggere quei contatori è il modo di capire se un lotto è finito:

* `cambiati: 0, saltate: 0, attraversate: 0` → **finito**, non c'è più niente da fare;
* `cambiati: 0, saltate: 800` → il blocco è stato attraversato e le righe erano già a posto;
* contatori identici a due lanci di fila → **non è finito**: serve `--offset` (vedi sotto).

`--offset N` fa ripartire lo scorrimento oltre le prime N righe della selezione. Serve quando
niente può far uscire una riga dalla selezione, e cioè in tre casi:

* con `--forza`, che toglie ogni filtro (è il caso del lotto L2 con `oe-dettaglio`);
* in **ombra** — tranne `risolvi-fonte` e `monitor`, i soli due il cui marcatore è tecnico
  (vedi sopra) — e con `--dry-run`, che non lascia un marcatore per nessuno;
* quando il comando non scrive la colonna su cui la selezione filtra.

I blocchi si lanciano a mano, uno dopo l'altro: `--offset 0`, `--offset 800`, `--offset 1600`.
Lo accettano i **sette** comandi che scorrono una selezione a pagine: `risolvi-fonte`,
`oe-dettaglio`, `link-verifica`, `applica-eventi`, `pulisci-contenuto`, `rigenera` e
`archivia-processed`.

Gli altri non lo hanno e non devono averlo. Dal 23/09 i quattro sottocomandi v11 dell'elenco lo
**rifiutano** con exit 2 e un messaggio che nomina l'opzione — prima lo accettavano e lo buttavano
via in silenzio (`fondi-doppioni --dry-run --offset 800` usciva 0, con stderr vuoto e senza nessun
offset, e chi lanciava i blocchi credeva di essere avanzato mentre ripeteva lo stesso identico
giro) — mentre `salute`, che sta sul percorso storico, si limita ad avvisare:

* **`fondi-doppioni`** confronta le righe fra loro: impaginare spezzerebbe le coppie con un id in
  una pagina e l'altro in un'altra. Legge sempre il corpus intero e il `--limit` è il numero di
  **fusioni applicate** — quindi `--limit 0` vuol dire «solo report». Se il riepilogo porta
  l'allarme «confronto dei gemelli troncato», il corpus ha superato le 5 000 righe e il confronto
  non è più completo;
* **`domini --import`** ricompone ogni volta l'intera whitelist e la riversa con un upsert: va
  lanciato **senza** `--limit`. Con `--limit N` scrive sempre gli stessi N host in testa alla
  composizione e gli altri non arrivano mai in tabella; il riepilogo ora lo dichiara (`troncati`);
* **`monitor`** ha una coda propria, ordinata dalla cadenza di `bando_controllo`: il blocco lo
  sposta il giro precedente scrivendo `ultimo_controllo_at`, non l'operatore;
* **`report-ombra`** misura un campione di eventi e la finestra la sposta `--dal`, che è un'altra
  cosa: con `--offset` accettato e ignorato la misura restava sugli stessi eventi;
* **`salute`** non scorre niente. Sta sul percorso storico (come `discover` e gli altri quattro
  step): un'opzione che non conosce la segnala a log come ignorata e prosegue con exit 0.

`--limit 0` significa ora davvero «non toccare niente» su **tutti** i comandi che scorrono.
Prima sette selezioni controllavano il limite *dopo* aver messo la riga nell'elenco, quindi un giro
da zero righe ne lavorava una — e con `--attivo` era una scrittura vera: `link-verifica --limit 0
--attivo` faceva una HEAD e un UPDATE su `bando_link`, `rigenera --malformati --limit 0 --attivo`
scriveva una riga in `bando_evento`. Su `fondi-doppioni` e `domini --import` era l'opposto: `0`
leggeva e scriveva tutto.

### I contatori, riga per riga (23/09/2026)

Insieme al `--limit` **quattro contatori hanno cambiato significato tenendo lo stesso nome**: chi
confronta i numeri di oggi con quelli di un lancio della settimana scorsa deve saperlo, altrimenti
legge un crollo dove c'è solo una definizione diversa.

| Comando | Contatore | Prima | Adesso |
|---|---|---|---|
| `pulisci-contenuto` | `esaminati` | le righe guardate | le sole righe con qualcosa da cambiare: vale **sempre** `esaminati == cambiati`. Le righe guardate sono `attraversate`, quelle già a posto `saltate` |
| `rigenera --malformati` | `esaminati` | le righe guardate | le sole righe malformate: vale **sempre** `esaminati == candidati`. Le righe guardate sono `attraversati`, quelle sane `saltati` |
| `archivia-processed` | `esaminati` | le righe guardate | le sole righe destinate all'archivio: vale **sempre** `esaminati == archiviabili`. Le righe guardate sono `attraversati`; `lavorabili` e `saltati` restano fuori dal `--limit` |
| `monitor` | `controllati` | le righe accodate, anche quando il giro non aveva scaricato niente (un `--senza-rete` riferiva `controllati: N, non_modificati: 0` con exit 0: sembrava un giro vero) | le righe davvero controllate: `--senza-rete` riferisce `controllati: 0, saltati: N, motivo_saltati: senza rete` |

Gli altri contatori sono **nuovi**: `attraversate`/`attraversati` (le occhiate),
`saltate`/`saltati` (righe senza lavoro), `bloccati` (`applica-eventi`: eventi già rifiutati in un
giro precedente), `non_tentati` (`applica-eventi`: eventi che nessuno ha giudicato, perché la RPC
non c'è), `senza_riscrittore` (`rigenera` nel modo date), `da_scaricare` (`oe-dettaglio --dry-run`),
`troncati` (`domini --import` con `--limit`), `rimandati` (`link-verifica`: link già pubblicabili
lasciati come sono perché non hanno risposto), `non_esaminati` (`fondi-doppioni`: righe non
confrontate perché il budget si è esaurito).

Un nome che compare in due comandi con due significati diversi: **`segnalati`**. In
`rigenera --malformati` sono le schede segnalate; in `applica-eventi` sono i rifiuti annotati.

`archivia-processed` elenca anche gli id che restano da lavorare a `risolvi-fonte`/`enrich`/`seo`:
`ids_lavorabili` è nel riepilogo di ritorno e nella riga di log. Dal 23/09 **non** finisce più in
`pipeline_run.contatori`: il `--limit` non lo tocca (le righe lavorabili non consumano
un'archiviazione), quindi è un elenco che cresce con il corpus e che ogni giro ricopiava dentro il
jsonb della telemetria. Nella riga di `pipeline_run` resta il loro numero, `lavorabili`.

### Letture oltre le mille righe: corrette (23/09/2026, commit `182026a`)

PostgREST restituisce al massimo 1 000 righe per risposta e non lo dice: nessuna eccezione, nessun
contatore. Tre letture chiedevano di più e credevano di aver visto tutto. La conseguenza che
riguarda questo runbook è la terza: `select_link_da_verificare`, interrogata su un blocco di 500
id, si fermava a 1 000 righe, quindi **i bandi in coda al lotto risultavano «scheda mai letta» e
`oe-dettaglio` li riscaricava a ogni lancio** (circa 575 scarichi sprecati, misurati in
produzione). Il runbook diceva che il lotto avanzava; avanzava solo la prima metà. Le altre due:
`select_pubblicati_per_gemelli` (i doppioni con id alto erano invisibili per costruzione) e
`select_bandi_da_monitorare`, il cui allarme di troncamento era tarato su 5 000 e non poteva
scattare mai. Ora le tre scorrono a pagine e le letture per lista di id spezzano in blocchi da 200.

| # | Comando | Cosa fa | Come si capisce che è andato |
|---|---|---|---|
| 0 | `salute --json` | fotografia iniziale | nessun allarme |
| 1 | `domini --import --dry-run` poi `domini --import --attivo` | riempie `dominio_ufficiale` con gli host delle fonti e il seed (misurato il 23/09: 109 domini dalle 121 fonti). Con `--enti <file.xlsx>` aggiunge anche l'elenco IndicePA, facoltativo | righe in `dominio_ufficiale` > 52 |
| 2 | `oe-dettaglio --backlog --dry-run --limit 5` poi `oe-dettaglio --backlog --attivo --limit 800`, a blocchi | scarica le schede dell'aggregatore e ne estrae i link all'ente. **`--backlog` è obbligatorio**: sceglie i 1702 pubblicati, mentre senza il flag si guarda solo la coda dei nuovi (una manciata). **`--attivo` è obbligatorio**: il marcatore «scheda già letta» è la riga di `bando_link`, e in ombra non viene scritta — il giro scarica lo stesso (e consuma `OE_SCHEDE_GIORNO`), `saltate` resta 0 e il lancio dopo riparte dalle stesse prime N schede. Senza `--forza` e in attivo il lotto avanza da solo; in ombra, o con `--forza` (che toglie il «già letta»), i blocchi si lanciano con `--offset 0`, `800`, `1600` | righe nuove in `bando_link` con `origine='aggregatore'` |
| 3 | `link-verifica --dry-run --limit 20` poi senza, a blocchi | verifica che quei link rispondano 2xx e li rende pubblicabili. Il `--limit` conta le verifiche: le righe già verificate oggi vanno in `saltate`. In ombra e con `--dry-run` non si scrive nulla, quindi i blocchi si scorrono con `--offset`. Un link che **non risponde** riceve `esito_http = 0` (il marcatore «guardato, irraggiungibile»): serve a non ripresentarlo per sempre. Ma se quel link era **già pubblicabile** non si tocca e va in `rimandati`: «non ho ricevuto risposta» è una notizia sulla nostra rete, non una prova sul link, e con la rete giù un solo giro avrebbe ritirato dalle schede tutti i link verificati fino a domani | `bando_link` con `esito_http` valorizzato; `rimandati` alto = problema di rete nostro, non dei link |
| 4 | `risolvi-fonte --backlog --dry-run --limit 20` poi `--attivo --lotto L5`, tutto in un colpo | cerca la fonte ufficiale dei bandi già pubblicati. Il `--limit` conta i bandi da risolvere: quelli il cui ricontrollo non è ancora dovuto vanno in `saltate` e non ripagano la ricerca. Con `--forza` serve `--offset`. **Va lanciato dopo il passo 2**, perché il passo 1 della cascata legge i link che `oe-dettaglio` ha registrato in `bando_link`: senza quelli i bandi dell'aggregatore scendono fino alla ricerca a pagamento. **Senza `--lotto` valgono i tetti giornalieri** (50 ricerche, 120 crediti, 1,5 dollari) e il giro si ferma dopo poche decine di bandi; con `--lotto L5` valgono quelli del backfill (8 000 crediti, 60 dollari) e la spesa resta fuori dal contatore mensile del regime | `bando.fonte_ufficiale_stato='trovata'` cresce |
| 5 | `monitor --ombra --limit 50` poi a regime | primo controllo: semina le impronte delle pagine. `--senza-rete` riferisce ora `controllati: 0, saltati: N, motivo_saltati: senza rete`: è una ricognizione della coda, non un giro. Senza `ANTHROPIC_API_KEY` il giro esce con `saltato: scarico_non_configurato` (exit 5) invece di dirsi riuscito | `bando_controllo.ultimo_controllo_at` valorizzato |
| 6 | `report-ombra --campione 100` | la misura da firmare prima di attivare | precisione ≥ 95% su ≥ 100 eventi |
| 7 | `fondi-doppioni --dry-run` | propone le fusioni; applica solo i criteri esatti. Niente `--offset`: legge il corpus intero e il `--limit` è il numero di fusioni applicate. **In `--dry-run`, in ombra e con `--limit 0` il report è completo.** Con `--attivo --limit N` (N > 0) il confronto si **ferma** quando le N fusioni sono fatte, perché è quadratico (misurato: 176 s contro 19 s su 1 200 righe): il report di quel lancio è parziale, lo dice l'allarme «confronto dei gemelli fermato dal budget» e il numero di righe non guardate è `non_esaminati`. Per il report completo si lancia in `--dry-run` | elenco coppie e master proposto; `non_esaminati: 0` = report completo |
| 8 | `pulisci-contenuto --dry-run --lotto L7` | toglie dai testi i link all'aggregatore. Il `--limit` conta le righe da cambiare; il comando non muove `pubblicato`, quindi fra un blocco e l'altro serve `--offset` | conteggio dei segmenti da sostituire |
| 9 | `rigenera --malformati --dry-run --lotto L7` | elenca le 9 schede con contenuto malformato. Con `--limit 20` attraversa tutto il corpus pubblicato: le righe sane non consumano il limite. Il comando segnala e non ripara, quindi la riga resta nella selezione **anche in attivo** (il secondo lancio la conta in `doppioni`): fra un blocco e l'altro serve `--offset` | id da rigenerare |
| 10 | `archivia-processed --dry-run --lotto L8` | manda allo stato terminale i chiusi mai pubblicati. Il `--limit` conta le **archiviazioni**: le righe da lasciare dove sono non lo consumano. Solo `archiviato` fa uscire una riga dalla selezione e lo scrive solo `--attivo`: in ombra e con `--dry-run` fra un blocco e l'altro serve `--offset` | conteggio archiviabili |

Ordine consigliato: 0 → 1 → 2 → 3 → 4 → 5, poi si lascia girare qualche giorno e si fa il 6.
I passi 7-10 si fanno quando serve, sono indipendenti.

Solo dopo che il passo 6 dà una precisione accettabile si attiva per tipo, un tipo alla volta:

```bash
.venv/bin/python -m app applica-eventi --dal <data> --tipo proroga,rettifica --limit 50 --dry-run
```

e poi senza `--dry-run`. Le sospensioni e le revoche restano per ultime, e richiedono la
migrazione 06, che a sua volta richiede il rilascio difensivo di BandoFit.

### `applica-eventi`: un rifiuto annotato non si disfa

Il riepilogo distingue quattro esiti, e la differenza fra i primi due è la cosa più importante di
tutto questo paragrafo.

| Contatore | Significato | Il lancio dopo |
|---|---|---|
| `applicati` | la RPC ha riversato l'evento nelle colonne | — |
| `rifiutati` | la RPC ha **guardato** l'evento e ha detto no: transizione non ammessa, data incoerente, stato che il CHECK non ammette ancora | se il rifiuto è definitivo viene annotato (`segnalati`) e il lancio dopo lo scavalca (`bloccati`) |
| `non_tentati` | **nessuno ha guardato l'evento**: la RPC non c'è (migrazione mancante) o la chiamata è fallita | lo ripresenta, ed è giusto |
| `bloccati` | già rifiutati in un giro precedente: lo scorrimento li scavalca | — |

`segnalati` sono i rifiuti **annotati adesso**: una riga `elaborazione_bloccata` con `riferisce_a`
che punta all'evento. Attenzione al nome: in `rigenera --malformati` `segnalati` sono le schede
segnalate, qui sono i rifiuti annotati. Sono due cose diverse con lo stesso nome.

**L'annotazione è per sempre.** `bando_evento` non concede DELETE nemmeno alla service-role key
(migrazione 02, `REVOKE DELETE, TRUNCATE`) e il trigger di immutabilità vieta di cambiare
`riferisce_a`: una volta scritta, quell'evento è fuori dalla coda e nessuna migrazione futura lo
recupera. Per questo si annota **solo** ciò che nessuna migrazione potrebbe sbloccare, e restano
fuori due casi: gli eventi `non_tentati`, e le `sospensione`/`revoca` prima della migrazione 06
(la 04 le respinge per costruzione finché il CHECK non ammette cinque stati — sono esattamente gli
eventi che la 06 serve ad applicare). Quei due casi tornano al lancio successivo.

Se un evento è stato annotato per sbaglio, l'unica via di rientro è
`applica-eventi --riprova-rifiutati`, che ignora le annotazioni e ripresenta anche i già respinti.

Un giro con `applicati: 0` e `rifiutati: N` **non** è un giro riuscito: è un blocco fermo. Un giro
con `non_tentati: N` dice che manca una migrazione, e non ha rovinato niente.

### `link-verifica` dichiarava un lavoro che il database rifiutava (23/09/2026)

Il primo blocco da mille in produzione ha riferito `pubblicabili: 847, ritirati: 153, errori: 0` e
ha scritto **153 righe su 1 000**. Le 847 non sono mai arrivate a destinazione.

La catena: `oe-dettaglio` scriveva le righe di `bando_link` senza `trovato_in_fonte_at`; il CHECK
della migrazione 02 (`NOT pubblicabile OR trovato_in_fonte_at IS NOT NULL`) rifiutava ogni UPDATE
che provasse a renderle pubblicabili; `db.controllo.aggiorna` cattura l'eccezione e la mette in un
warning; `link-verifica` ignorava l'esito e incrementava il contatore lo stesso.

Il guaio peggiore non era il conteggio. Senza scrittura `esito_http` restava NULL, cioè «mai
verificata», quindi il lancio successivo ripresentava le stesse righe: **il ciclo «rilancia finché
`esaminati` non arriva a zero» non sarebbe finito mai.**

Tre correzioni: `oe-dettaglio` registra `trovato_in_fonte_at` quando trova l'href nella scheda, che
è esattamente ciò che quella colonna significa; `link-verifica` colma l'istante sulle 3 887 righe
già scritte, quando le rende pubblicabili (la prova `sha256#offset` c'è già, serviva solo la data, e
così non serve una migrazione); e soprattutto **il contatore segue la scrittura, non l'intenzione**,
con `non_scritte` a dire quante righe il database ha rifiutato.

Contatore nuovo anche per la provenienza: `senza_prova` sono le righe che rispondono 2xx ma non
vengono dall'HTML di una pagina che abbiamo scaricato. Sono le 3 739 righe `raw` del backfill della
02, che vengono da `bando.link_bando` e dagli allegati. Restano non pubblicabili, perché §13.4
promette a chi legge che ogni riga leggibile compare nella pagina di riferimento. Quei link tornano
pubblicabili per un'altra strada: il resolver li riscrive come righe proprie, con la prova, quando
trova la fonte ufficiale.

### La giuntura fra i due lotti: corretta (23/09/2026)

`oe-dettaglio` scarica le schede dell'aggregatore e scrive gli href all'ente in `bando_link` con la
prova `sha256#offset`. Poi la regola A29 vieta di riscaricare una scheda già letta, e fa bene. Ma
**nessuno rileggeva quella tabella**: il passo 1 della cascata guardava `raw_data`, `link_bando` e i
link nel testo, e per i bandi dell'aggregatore `link_bando` è l'URL di Obiettivo Europa, che viene
scartato. Quindi i 3 887 link estratti su 1 724 bandi erano invisibili e ogni bando scendeva fino
alla ricerca a pagamento: da tremila a settemila crediti Firecrawl per un lavoro già fatto e gratis.

Ora il giro legge `bando_link` una volta per lotto e ne ricava i candidati del passo 1. La stessa
lettura serve già a riconoscere le schede lette, quindi non costa una richiesta in più. Le righe non
devono essere `pubblicabile`: quella colonna la scrive `link-verifica`, e il resolver rivaluta la
pagina da sé.

## Punto aperto: `bando_controllo.volatilita` si scrive e non si legge

Il moltiplicatore che dovrebbe diradare i controlli sui bandi fermi (`VOLATILITA_CALMA`) non entra
mai in funzione, perché conta su `controlli_senza_diff`, una colonna che **non esiste** in
`bando_controllo`: `aggiorna_controllo` la scarta in silenzio insieme a tutte le colonne che lo
schema non espone, quindi il conteggio riparte da zero a ogni giro.

Finché è così, `volatilita` **non viene riletta** dal giro successivo: il moltiplicatore riparte da
1,0 ogni volta e il peggio che può fare è 0,7. Rileggerla sarebbe peggio: il fattore «bando
cambiato» (×0,7) si comporrebbe giro dopo giro fino al pavimento 0,5 e niente potrebbe riportarlo
su, quindi ogni bando cambiato due volte resterebbe controllato al doppio della frequenza per
sempre, a spese del tetto giornaliero in dollari.

Conseguenza da sapere leggendo il DB: la colonna oggi codifica «l'ultimo giro ha visto un diff», non
una memoria. Per farla funzionare davvero serve una migrazione che aggiunga `controlli_senza_diff`;
non è stata scritta.

## F2: il frontend legge dalla vista (23/09/2026)

Il secondo rilascio del frontend è scritto e verificato, e **non è ancora acceso**: il deploy e
l'accensione sono due gesti separati. Si accende con una variabile nell'unit del frontend:

```
BANDI_FONTE_LETTURA=bando_pubblico
```

Per tornare indietro si rimette a `bando`, o si toglie. La variabile vale a runtime, quindi non
serve ricostruire: basta riavviare il servizio del frontend.

**Cosa cambia per chi legge.** La scheda mostra la fonte ufficiale con host, tipo e data di verifica;
il pulsante porta alla pagina dell'ente invece di non esserci; gli allegati arrivano dalle righe
verificate di `bando_link`; compare il box «Aggiornamenti» con gli eventi datati e il link alla
pagina che li prova; gli slug vecchi e i doppioni rispondono 301 invece di 404. L'API riempie i
quattro campi della 1.1 (`official_source`, `opens_on_verified`, `deadline_verified`,
`last_checked_at`) che prima erano `null` scritti a mano.

**Cosa cambia nei numeri: niente.** I conteggi per stato coincidono esattamente fra tabella e vista
(aperti 1 283, chiusi 668, in apertura 183, totale 2 134, misurati il 23/09). La vista non cambia
quello che si vede: rende il calcolo autorevole e pronto per i due stati nuovi, per l'ora di
scadenza e per i flag di verifica, che una ricostruzione lato client non può conoscere.

**Il `lastmod` della sitemap cambia significato**, ed è il punto da sapere prima di accendere. Sulla
tabella era `updated_at`, che l'upsert dello scrape riscrive a ogni giro anche quando per chi legge
non è cambiato niente; sulla vista è `ultimo_cambiamento_at`, che si muove solo per una modifica
pubblica. Sullo stesso bando la prima diceva 23 settembre e la seconda 27 agosto. Le date nella
sitemap **andranno indietro**: è la correzione di un difetto, non una regressione, e va atteso.

**Verificato sul server compilato contro i dati di produzione**: una scheda risponde in 0,66 s, uno
slug inesistente dà 404, l'elenco e i suoi filtri 200, l'API 200 con `api_version: 1.1`. Su ogni
filtro di stato tutte le card portano il badge di quello stato, quindi filtro e badge non possono
divergere. Nella pagina non compare nessun link all'aggregatore. I tempi delle query stanno fra 58 e
172 ms contro i 3 000 del timeout della chiave pubblica.

## Regola operativa: dopo ogni migrazione, riavviare il sender

Il codice legge lo schema del database **una sola volta all'avvio del processo**
(`db.controllo.schema()`) e lo tiene per tutta la vita del processo: è quello che gli
permette di degradare senza fallire quando una colonna non c'è ancora. Il rovescio è che
un sender avviato **prima** di una migrazione continua a comportarsi come se quella
migrazione non esistesse, anche per ore.

È già successo il 23/09/2026: sender riavviato alle 16:08:50, migrazioni applicate alle
16:14:28. Il giro delle 16:08 ha pubblicato dieci bandi comportandosi come la pipeline
vecchia e ha scritto a log `[telemetria] pipeline_run non esiste ancora: riga non scritta`.

Quindi: **ogni volta che applichi una migrazione (01-08), riavvia il sender subito dopo.**
Verifica che abbia preso lo schema nuovo con una riga in `pipeline_run` al termine del
primo giro:

```sql
select id, step, esito, avviato_at, terminato_at from public.pipeline_run order by id desc limit 5;
```

Se resta vuota dopo un giro completo, il processo ha ancora la fotografia vecchia.

## SQL: ordine di applicazione (fase b)

**01 → 02 → seed → 03 → 04 → 05**, tutte nella stessa seduta e fuori dai giri delle 00/06/12/18.
È l'ordine eseguibile: il seed popola `dominio_ufficiale`, creata dalla 02 e letta dai trigger della 03.
La **08** (`bando_v11_08_evento_pubblicazione.sql`) è correttiva e va applicata appena possibile:
senza di lei i bandi pubblicati dopo la 02 non emettono l'evento `pubblicazione` e chi segue il
flusso a cursore non li vede mai. Dipende solo da 01 e 02, non serve riavviare il sender (aggiunge
solo una funzione e un trigger), e conviene applicarla **fra un giro di pipeline e l'altro**: crea
un trigger su `bando` e il file si protegge con `lock_timeout` di 5 secondi.

La **06** si applica solo dopo il rilascio difensivo R0-a di BandoFit; la **07** solo dopo che BandoFit
legge il contratto (`docs/contratto-db-bandi.md`). Ogni file ha il blocco Verifica in coda: se una
verifica non dà il valore atteso, fermarsi lì e non proseguire con il file successivo.

## SQL applicate dal committente

| Script | Applicato il | Esito Verifica |
|---|---|---|
| (nessuno: i 15 file `bando_v11_*` sono scritti e verificati per lettura e su un cluster locale effimero, ma **non** applicati) | | |

## Comandi di verifica

```bash
npm test
npm run test:py
npm run test:py:bandi
npx tsc --noEmit -p tsconfig.json   # baseline: 54 errori preesistenti, 0 nei file bandi
```

## Stato alla chiusura della fase A (23/09/2026)

Nulla è stato applicato al database e nessun comando è stato eseguito in modalità attiva: tutto il
codice nuovo parte in **ombra** e degrada da solo finché le migrazioni non ci sono (`db.controllo`
rileva le colonne assenti, `blocco` la RPC mancante, il monitor salta lo step con un log).

| Verifica | Comando | Esito |
|---|---|---|
| Pipeline bandi | `npm run test:py:bandi` | 1226 test, OK |
| Frontend e API | `npm test` | 381 test, 0 falliti |
| Backend | `npm run test:py` | 26 test, OK |
| Tipi | `npx tsc --noEmit -p tsconfig.json` | 51 errori, tutti preesistenti (baseline 54) |
| Segreti | grep sui file tracciati | 0 credenziali |

Comandi nuovi, tutti con `--dry-run` e `--limit` e tutti verificati con credenziali finte e senza rete:
`salute`, `domini --import`, `risolvi-fonte`, `oe-dettaglio`, `link-verifica`, `fondi-doppioni`,
`monitor`, `report-ombra`, `applica-eventi`, `pulisci-contenuto`, `rigenera`, `archivia-processed`.
