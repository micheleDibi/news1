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
* in **ombra** e con `--dry-run`, dove nessuna scrittura lascia un marcatore;
* quando il comando non scrive la colonna su cui la selezione filtra.

I blocchi si lanciano a mano, uno dopo l'altro: `--offset 0`, `--offset 800`, `--offset 1600`.
Lo accettano `risolvi-fonte`, `oe-dettaglio`, `link-verifica`, `applica-eventi`,
`pulisci-contenuto`, `rigenera` e `archivia-processed`.

Due comandi non lo hanno e non devono averlo:

* **`fondi-doppioni`** confronta le righe fra loro: impaginare spezzerebbe le coppie con un id in
  una pagina e l'altro in un'altra. Legge sempre il corpus intero e il `--limit` è il numero di
  **fusioni applicate** — quindi `--limit 0` vuol dire «solo report». Se il riepilogo porta
  l'allarme «confronto dei gemelli troncato», il corpus ha superato le 5 000 righe e il confronto
  non è più completo;
* **`domini --import`** ricompone ogni volta l'intera whitelist e la riversa con un upsert: va
  lanciato **senza** `--limit`. Con `--limit N` scrive sempre gli stessi N host in testa alla
  composizione e gli altri non arrivano mai in tabella; il riepilogo ora lo dichiara (`troncati`).

Su questi due `--limit 0` significa ora davvero «non toccare niente» (prima leggeva e scriveva
tutto: era l'esatto contrario).

| # | Comando | Cosa fa | Come si capisce che è andato |
|---|---|---|---|
| 0 | `salute --json` | fotografia iniziale | nessun allarme |
| 1 | `domini --import --dry-run` poi `domini --import --attivo` | riempie `dominio_ufficiale` con gli host delle fonti e il seed (misurato il 23/09: 109 domini dalle 121 fonti). Con `--enti <file.xlsx>` aggiunge anche l'elenco IndicePA, facoltativo | righe in `dominio_ufficiale` > 52 |
| 2 | `oe-dettaglio --backlog --dry-run --limit 5` poi senza `--dry-run`, a blocchi | scarica le schede dell'aggregatore e ne estrae i link all'ente. **`--backlog` è obbligatorio**: sceglie i 1702 pubblicati, mentre senza il flag si guarda solo la coda dei nuovi (una manciata). **Senza `--forza`**: le schede già lette vengono saltate da sole e il lotto avanza. Se serve rifarle (`--forza`), i blocchi si lanciano con `--offset 0`, `800`, `1600`, perché con `--forza` nessuna riga è «già letta» | righe nuove in `bando_link` con `origine='aggregatore'` |
| 3 | `link-verifica --dry-run --limit 20` poi senza, a blocchi | verifica che quei link rispondano 2xx e li rende pubblicabili. Il `--limit` conta le verifiche: le righe già verificate oggi vanno in `saltate`. In ombra e con `--dry-run` non si scrive nulla, quindi i blocchi si scorrono con `--offset` | `bando_link` con `esito_http` valorizzato |
| 4 | `risolvi-fonte --backlog --dry-run --limit 20` poi senza, a blocchi | cerca la fonte ufficiale dei bandi già pubblicati. Il `--limit` conta i bandi da risolvere: quelli il cui ricontrollo non è ancora dovuto vanno in `saltate` e non ripagano la ricerca. Con `--forza` serve `--offset` | `bando.fonte_ufficiale_stato='trovata'` cresce |
| 5 | `monitor --ombra --limit 50` poi a regime | primo controllo: semina le impronte delle pagine. `--senza-rete` riferisce ora `controllati: 0, saltati: N, motivo_saltati: senza rete`: è una ricognizione della coda, non un giro. Senza `ANTHROPIC_API_KEY` il giro esce con `saltato: scarico_non_configurato` (exit 5) invece di dirsi riuscito | `bando_controllo.ultimo_controllo_at` valorizzato |
| 6 | `report-ombra --campione 100` | la misura da firmare prima di attivare | precisione ≥ 95% su ≥ 100 eventi |
| 7 | `fondi-doppioni --dry-run` | propone le fusioni; applica solo i criteri esatti. Niente `--offset`: legge il corpus intero e il `--limit` è il numero di fusioni applicate | elenco coppie e master proposto |
| 8 | `pulisci-contenuto --dry-run --lotto L7` | toglie dai testi i link all'aggregatore. Il `--limit` conta le righe da cambiare; il comando non muove `pubblicato`, quindi fra un blocco e l'altro serve `--offset` | conteggio dei segmenti da sostituire |
| 9 | `rigenera --malformati --dry-run --lotto L7` | elenca le 9 schede con contenuto malformato. Con `--limit 20` attraversa tutto il corpus pubblicato: le righe sane non consumano il limite | id da rigenerare |
| 10 | `archivia-processed --dry-run --lotto L8` | manda allo stato terminale i chiusi mai pubblicati. Il `--limit` conta le **archiviazioni**: le righe da lasciare dove sono non lo consumano | conteggio archiviabili |

Ordine consigliato: 0 → 1 → 2 → 3 → 4 → 5, poi si lascia girare qualche giorno e si fa il 6.
I passi 7-10 si fanno quando serve, sono indipendenti.

Solo dopo che il passo 6 dà una precisione accettabile si attiva per tipo, un tipo alla volta:

```bash
.venv/bin/python -m app applica-eventi --dal <data> --tipo proroga,rettifica --limit 50 --dry-run
```

e poi senza `--dry-run`. Le sospensioni e le revoche restano per ultime, e richiedono la
migrazione 06, che a sua volta richiede il rilascio difensivo di BandoFit.

Nel riepilogo di `applica-eventi` si leggono ora anche `rifiutati` (la RPC ha risposto «no»: una
transizione non ammessa, una data incoerente, la migrazione mancante) e `bloccati` (eventi già
rifiutati in un giro precedente, che lo scorrimento scavalca invece di ripresentarli). Un giro con
`applicati: 0` e `rifiutati: N` **non** è un giro riuscito: è un blocco fermo, e dice quale
migrazione manca.

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
