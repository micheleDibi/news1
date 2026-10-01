# Guida al sistema bandi

**Data:** 01/10/2026 (dopo il deploy delle 10:10). Aggiornata la sera dell'01/10 con il **giro 3** (codice pronto,
deploy da fare): §3.2, §3.2-bis, §3.3, §4.6, §4.11.

**A chi serve.** Al titolare del progetto, per studiare e capire come funziona il sistema dei bandi: da dove arrivano,
come vengono lavorati e pubblicati, che cosa vedono i lettori, che cosa è acceso oggi e che cosa resta da fare.

**Come leggerla.** Prima «In una pagina», che riassume tutto. Poi i capitoli, nell'ordine: ognuno si regge da solo,
ma i rimandi (§x.y) portano al punto dove un argomento è spiegato per intero. Il glossario in fondo spiega le parole
tecniche.

**Da dove vengono i fatti.**
- Le regole, gli orari e i passi sono stati controllati sul codice: le fonti (file:riga) sono in fondo a ogni sezione.
- I numeri sono stati letti sul database bandi, in sola lettura, l'01/10 fra le 11:28 e le 12:30 (ora di Roma). Alle
  12:00 è girato un giro: alcuni numeri delle 12:30 sono già diversi di poco (§7).
- **«non verificato»** vuol dire che il fatto non si è potuto controllare (di solito: il file `.env` del server, che
  da qui non si legge). **«non ricontrollato»** vuol dire che il numero viene da un'indagine precedente e non è stato
  riletto sul DB in questa revisione.
- La documentazione (RIPRESA, contratti, README) in alcuni punti è vecchia: dove contrasta con il codice, vale il
  codice, e la guida lo dice.

---

## In una pagina

1. **Che cosa fa.** Il sistema bandi è una catena di programmi che gira da sola quattro volte al giorno (00, 06, 12
   e 18, ora di Roma) e a ogni riavvio del server. Legge circa cento siti di enti e portali pubblici, trova i bandi
   di finanziamento, scarta quello che non è un bando, ne ricava stato e date, li classifica, cerca la pagina
   ufficiale dell'ente, fa scrivere la scheda a un modello e la pubblica.
2. **Dove finisce.** I bandi stanno in un database tutto loro. Il sito edunews24.it e BandoFit leggono soltanto, e
   solo dalla vista `bando_pubblico`. Scrive solo la pipeline (più un job orario dentro il database).
3. **Lo stato.** Su un bando pubblicato lo stato si cambia solo registrando un «evento» con la sua prova. Quello che
   vede il pubblico è lo «stato effettivo», ricalcolato con l'orologio a ogni lettura. Un job orario chiude da solo i
   bandi scaduti, al minuto 5 di ogni ora.
4. **Oggi.** 2.191 bandi pubblicati: 1.168 aperti, 166 in apertura, 857 chiusi. L'81% viene da un solo aggregatore,
   ObiettivoEuropa. Il giro di avvio dopo il deploy (10:10-10:18) è finito bene e ha pubblicato 3 bandi nuovi.
5. **Acceso davvero.** Raccolta, preprocess, enrich e SEO (cioè la pubblicazione) scrivono sempre. Il resolver della
   fonte ufficiale è attivo dal 25/09. Il monitor delle pagine ufficiali è «in ombra» (osserva e annota, non
   pubblica), ma 5 tipi di evento (faq, nuovo allegato, graduatoria, esito, proroga) si pubblicano da soli.
6. **In prova.** La verifica dello stato, le fusioni automatiche dei doppioni («gemelli»), la sosta dei bandi nuovi
   senza scadenza e l'import dei domini da IndicePA sono in ombra. **Un solo interruttore** li accende tutti insieme:
   `VERIFICA_STATO_MODALITA=attivo`. Prime esecuzioni: verifica oggi alle 18, gemelli e IndicePA domani alle 06. Dal
   giro 3 gli interruttori diventano tre (§3.3.5).
7. **Il piano.** L'08/10 si lancia il controllo `report-verifica-stato --verita`. Si attiva solo con 0 difformi e con
   un backup. Dal giro 3 non ci sono altre attese: l'avviso a BandoFit è il messaggio mandato prima del deploy, che
   annuncia anche la verifica. Il 661135, già chiuso dal job orario, con il codice del giro 3 non è più una difforme
   (`confermato_da_stato`).
8. **I punti deboli più gravi.** Nessun allarme arriva a una persona (il pannello su BandoFit è rimandato e
   `sorveglia` non è installato). La spesa principale (SEO, preprocess, enrich) non è contata né limitata (dal giro
   3 sì, §3.3.6). Due fonti
   intere (Italia Domani e Incentivi.gov.it) non hanno mai prodotto un bando. 426 aperti senza scadenza e 163 «in
   apertura» senza data possono restare così per sempre. IndexNow è rotto. La migrazione 07 è bloccata e la chiave
   pubblica legge ancora la tabella `bando` intera.
9. **Che cosa resta da fare.** L'elenco ragionato è nel capitolo 8 (correzioni, per gravità); il calendario, con chi fa
   cosa, nel capitolo 9.
10. **Il giro 3 (codice pronto l'01/10, deploy da fare).** Ogni giro delle quattro ore farà anche la manutenzione: il
    monitor su tutti gli aperti, i ricontrolli del resolver su tutti i bandi senza fonte, il controllo dei link, la
    rielaborazione dei pubblicati dalla pagina ufficiale e i gemelli. La fonte ufficiale si cerca prima del preprocess,
    che legge la pagina dell'ente. Niente più tetti di numero, solo di tempo (regola «niente lotti»), e la spesa si
    conta tutta: 5 $ al giorno, 150 al mese. Gemelli e IndicePA hanno un interruttore proprio e si accendono; la
    verifica dello stato resta in ombra fino all'08/10. La migrazione 14 sistema sospensione e revoca. I passi di
    Michele sono in RIPRESA §1; il dettaglio in §3.2 e §3.2-bis.

---

## Indice

1. [Il quadro generale](#1-il-quadro-generale)
2. [Da dove arrivano i bandi (fonti e scraping)](#2-da-dove-arrivano-i-bandi-fonti-e-scraping)
3. [La pipeline, giro per giro](#3-la-pipeline-giro-per-giro)
4. [Il database e lo stato di un bando](#4-il-database-e-lo-stato-di-un-bando)
5. [Cosa vedono il sito, l'API e BandoFit](#5-cosa-vedono-il-sito-lapi-e-bandofit)
6. [I controlli](#6-i-controlli)
7. [Cosa c'è in produzione oggi](#7-cosa-cè-in-produzione-oggi)
8. [Correzioni da fare](#8-correzioni-da-fare)
9. [Prossimi passi](#9-prossimi-passi)
- [Glossario](#glossario)

---

## 1. Il quadro generale

### 1.1 Che cos'è il sistema bandi, in una frase

Il sistema bandi è una catena di programmi. Quattro volte al giorno (alle 00, 06, 12 e 18) va a leggere i siti di enti
e portali pubblici. Trova i bandi di finanziamento (regionali, nazionali, europei), li pulisce, li classifica e li
pubblica su edunews24.it. Poi continua a controllarli, per accorgersi se chiudono, vengono prorogati o cambiano.

Il risultato finale è una vista del database con i soli bandi «pronti da mostrare» (`bando_pubblico`). La leggono due
lettori: il sito EduNews24 e BandoFit.

### 1.2 A cosa serve

- **Al lettore del sito**: trovare un bando, capire se è aperto e da quando a quando, e arrivare alla pagina ufficiale
  dell'ente.
- **A BandoFit**: avere lo stesso archivio, con alcune regole garantite per iscritto (`docs/contratto-db-bandi.md`).
  Per esempio: un bando pubblicato non sparisce, il suo indirizzo non cambia, lo stato mostrato è sempre calcolato.
- **Al titolare**: avere un archivio che si aggiorna da solo, senza passaggi manuali ricorrenti.

### 1.3 I cinque pezzi

| Pezzo | Che cosa fa | Perché esiste | Passi del giro |
|---|---|---|---|
| **Raccolta** | Sa da quali pagine leggere e ne copia i bandi «grezzi» nel database | Senza raccolta non c'è nulla da lavorare | `discover`, `scrape` |
| **Arricchimento** | Decide se è davvero un bando, ne ricava date e stato, lo collega a regioni, settori, beneficiari e codici ATECO | Il testo grezzo di un sito non si può filtrare né mostrare | `preprocess` (modello Haiku; se la pagina del bando è vuota ripiega su Sonnet), `enrich` (Haiku) |
| **Fonte ufficiale** | Cerca la pagina dell'ente che ha emesso il bando | Molti bandi arrivano da aggregatori (soprattutto ObiettivoEuropa): il lettore deve arrivare alla fonte vera, non a un intermediario | `resolver` e, alle 06 e alle 18, i suoi `ricontrolli`. Non usa modelli né ricerche a pagamento (oggi non sono collegati, §3.9) |
| **Pubblicazione** | Prima cerca una scadenza ai bandi nuovi aperti senza data; poi scrive testo e meta e porta il bando allo stato «completed». A quel punto il database lo pubblica da solo, se ha anche slug e stato e non è un doppione fuso | Un bando si mostra solo quando è completo | `verifica_stato_ingresso` (controllo prima della SEO, §3.11), `seo` (modello Opus) |
| **Sorveglianza dello stato** | Ricontrolla i bandi già pubblicati: chiusure, proroghe, FAQ, nuovi allegati, doppioni | Un bando cambia nel tempo, e uno stato sbagliato («aperto» quando è chiuso) è il danno peggiore | `monitor`, `verifica_stato`, `gemelli`, più un job orario dentro il database |

I modelli sono quelli predefiniti nel codice (Haiku 4.5, Sonnet 4.6, Opus 4.7). Si possono cambiare dall'`.env` e
quelli del server sono **non verificati**.

Una parola che tornerà spesso è **«ombra»**. Un pezzo in ombra fa tutto il lavoro e registra quello che *farebbe*, ma
non cambia ciò che vede il pubblico. Serve a provarlo sui dati veri senza rischi. Il contrario è **«attivo»**. Se la
variabile non è impostata, o ha un valore sconosciuto, il codice sceglie l'ombra.

Fonti: `backend/app/bandi_pipeline.py:306-430`, `scraper_bandi/app/settings.py:213-219, 439-463`,
`scraper_bandi/app/bando_preprocess_runner.py:133-140`, `scraper_bandi/app/fonte_ufficiale.py:1260-1271, 2301-2332`,
`backend/sql/bando_v11_01_pubblicazione.sql:374-395`, `docs/contratto-db-bandi.md`.

### 1.4 Dove vive

| Luogo | Che cosa c'è |
|---|---|
| **Server di produzione (Web2)**, repo `~/projects/news1` | Un solo processo, il «sender dei bandi» (servizio systemd; il nome `edunews-bandi-sender` è quello dell'esempio nel repository, sul server è **non verificato**). Resta acceso per giorni e lancia il giro alle 00, 06, 12 e 18. Appena parte lancia anche un giro, il «giro di avvio» (boot). Lo salta se il processo precedente è morto a metà giro: in quel caso lascia solo una riga nel diario e aspetta il prossimo orario. |
| **Database bandi** (progetto Supabase separato da quello degli articoli) | Le tabelle: `fonte` (da dove leggere), `bando` (i bandi), `bando_controllo` (la scheda di servizio di ogni bando), `bando_evento` (il registro di tutto ciò che succede a un bando), `bando_link`, `pipeline_run` (il diario dei giri), `fonte_run` (il diario di ogni fonte) e altre (§4.2). Scrivono la pipeline, con la chiave di servizio, e il job orario interno al database. |
| **Sito edunews24.it** (Astro) | Legge e basta, con la chiave pubblica («anon»), soprattutto dalla vista `bando_pubblico`. |
| **BandoFit** | È il secondo lettore dello stesso database, sempre con la chiave pubblica. Che cosa legge esattamente è **non verificato**: il suo codice non è in questo repository. Secondo il contratto legge solo la vista e le tabelle pubbliche. |

Ci sono tre cose importanti da sapere sul database:

- **Lo stato di un bando pubblicato non si scrive a mano.** Si cambia solo registrando un «evento» (per esempio
  «chiusura» o «proroga») che il database applica. Un trigger rifiuta ogni modifica diretta. Prima della
  pubblicazione, invece, lo stato lo decide la pipeline.
- **Un job orario dentro il database** (`bandi-transizioni-orarie`, al minuto 5 di ogni ora) registra da solo gli
  eventi di chiusura per i bandi scaduti e di apertura per quelli arrivati alla data di apertura verificata. Che giri
  è verificato con una lettura in sola lettura (`monitoraggio_job_orario`, §4.6).
- **Lo stato che vede il pubblico è calcolato a ogni lettura** (`stato_effettivo`). Per questo è giusto anche nei
  minuti in cui il job orario non è ancora passato.

Fonti: `backend/app/bandi_sender.py:46-103`, `backend/sql/bando_v11_04_transizioni.sql:1183-1339`,
`backend/sql/bando_v11_05_vista_pubblica.sql:148-184`, `backend/sql/bando_v11_12_monitoraggio.sql:236-245`,
`src/lib/supabase-bandi.ts`, `docs/contratto-db-bandi.md`.

### 1.5 Il flusso, a blocchi

```
   OpenCoesione (1 pagina indice)        3 portali inseriti a mano
              |                          (ObiettivoEuropa, Italia Domani,
              v                           Incentivi.gov.it)
   [1 DISCOVER] -> tabella FONTE  <-----------+
              |   (siti di enti e portali)
              v
   [2 SCRAPE] legge ogni fonte, una riga grezza per bando
              |   -> tabella BANDO (stato "scraped")
              v
   [3 PREPROCESS] e un bando? date? stato?  -> "processed" o "rejected"
              v
   [4 ENRICH] regioni, settori, beneficiari, ATECO -> "enriched"
              v
   [5 RESOLVER] cerca la pagina ufficiale dell'ente
              v
   [5-ter VERIFICA STATO, ingresso] cerca la scadenza ai bandi nuovi
              v
   [6 SEO] testo e meta -> "completed" -> il DB lo PUBBLICA da solo
              |
              v
   vista BANDO_PUBBLICO  ---->  sito edunews24.it
              |          ---->  BandoFit
              ^
   [SORVEGLIANZA] monitor, verifica dello stato, gemelli (doppioni),
                  job orario del DB (chiusure e aperture automatiche)
```

### 1.6 Che cosa fa ogni giro

Questa è la produzione dell'01/10. **Dal deploy del giro 3** l'ordine cambia e la manutenzione gira a ogni giro delle
quattro ore: la tabella nuova è in §3.2.

| Giro | Passi, in ordine |
|---|---|
| 00:00 e 12:00 | discover, scrape, preprocess, enrich, resolver, verifica_stato_ingresso, seo |
| 18:00 | discover, scrape, preprocess, enrich, resolver, **ricontrolli** del resolver, verifica_stato_ingresso, seo, **monitor**, **verifica_stato** (controlli) |
| 06:00 | come le 18:00, più due passi: l'**import dei domini** da IndicePA, subito prima del resolver e solo se nel mese non è ancora stato fatto, e **gemelli** (i doppioni), alla fine |
| Avvio (boot, dopo un riavvio) | come le 00:00. Niente ricontrolli, monitor, verifica_stato, domini o gemelli: un riavvio non deve spendere fuori orario |

Ricontrolli, monitor e verifica_stato girano solo nelle ore di `MONITOR_GIRI`. Il valore predefinito è «06:00,
18:00». Secondo RIPRESA la variabile non è impostata sul server; è coerente con il diario (il monitor ha girato solo
alle 06 e alle 18), ma sul file `.env` è **non verificato**.

Oggi `gemelli` è in ombra: elenca e conta i doppioni ma non li fonde. Fonderebbe al massimo 10 coppie per giro, e solo
dopo `VERIFICA_STATO_MODALITA=attivo`.

Dopo ogni giro, a lucchetto rilasciato, parte una sola notifica IndexNow con gli slug che i passi dichiarano di aver
modificato (oggi solo il monitor). **I bandi appena pubblicati dalla SEO non vengono notificati.** Se il giro
precedente è ancora in corso (il lucchetto dura al massimo 4 ore), il giro nuovo non parte e nel diario risulta
«saltato».

Ogni passo è «protetto»: se uno fallisce, l'errore si registra e i passi successivi partono lo stesso. Nel journal il
giro finisce con `PARTIAL`; nella riga di `pipeline_run` lo stesso giro ha esito `errore`, con il nome del passo in
`passi_non_ok` (§3.3.3).

Un giro dura fra 5 e 14 minuti, con una mediana di circa 7 (6,8 minuti sui 41 giri riusciti dal 23/09 al giro di
avvio dell'01/10). I commenti nel codice parlano ancora di «~80 minuti», ma è un dato vecchio.

Gli orari sono l'ora locale del processo: la libreria `schedule` usa l'orologio del server. Che sia l'ora di Roma è
dedotto dai tempi registrati nel database (il giro delle 06:00 parte alle 04:00 UTC). Il fuso del server è **non
verificato** direttamente.

Fonti: `backend/app/bandi_pipeline.py:207-216` (`_giro_previsto`), `:296-305` (lucchetto), `:313-430` (ordine dei
passi), `:440-460` (IndexNow, `completed`/`partial`), `:675-715` (slug da notificare), `backend/app/bandi_sender.py:62-101`,
`scraper_bandi/app/settings.py:288-290` (`GIRI_SCHEDULER`, default di `MONITOR_GIRI`), `scraper_bandi/app/gemelli.py:1315-1346`,
tabella `pipeline_run` (step `pipeline`).

### 1.7 La fotografia di oggi (01/10/2026)

**Ultimo giro prima delle analisi.** È il giro di avvio dopo il deploy: dalle 10:10 alle 10:18, esito ok, nessun passo
andato male (riga 150 di `pipeline_run`). Alle 12:00 è girato anche il giro normale, finito ok alle 12:06 (riga 153).
Il deploy risulterebbe del commit d7f5663: la riga del giro di avvio contiene i campi nuovi di quel codice, ma il
numero del commit non è scritto da nessuna parte, quindi è **non verificato**.

**Bandi nel database.** 5.194 righe alle 11:30 (5.195 dopo il giro delle 12):
- 2.197 «completed»: 2.191 pubblicati e 6 doppioni fusi;
- 569 «processed», tutti chiusi (570 dopo il giro delle 12);
- 2.428 «rejected» (scartati).

**Stato dei 2.191 pubblicati.** 1.168 aperti, 857 chiusi, 166 in apertura.

**Dipendenza da un solo aggregatore.** 1.768 pubblicati su 2.191 (81%) vengono da ObiettivoEuropa. Solo 31 fonti hanno
almeno un bando pubblicato.

**Modalità in produzione, lette dal diario dei giri:**
- resolver **attivo**;
- monitor **in ombra**, ma con 5 tipi che si applicano da soli (faq, nuovo_allegato, graduatoria, esito, proroga);
- verifica dello stato **in ombra**, e con lei gemelli, sosta all'ingresso e import di IndicePA.

Il file `.env` del server non è leggibile da qui. Per questo le altre impostazioni sono **non verificate** (per
esempio `MONITOR_STATI_ESTESI`, `MONITOR_GIRI`, i modelli e i tetti di spesa). Su `MONITOR_TIPI_ATTIVI`, RIPRESA si
contraddice: la sezione «Configurazione in produzione» la dà ancora «da aggiungere», mentre il §1 la dà già attiva.
Il diario dei giri dà ragione al §1.

**Migrazioni 12 e 13.** I loro oggetti esistono nel database e rispondono. Che siano state applicate proprio oggi è
**non verificato**. La 07 non è applicata.

**Sorveglianza automatica.** Oggi non ce n'è. Il pannello su BandoFit è rimandato e il timer di `sorveglia` non è
installato. La tabella `monitoraggio_riepilogo` la scrive solo il comando `sorveglia`, quindi è vuota. Se i giri si
fermano, lo si scopre solo leggendo a mano `pipeline_run` (§3.3.4) o lanciando `salute` (§6.2).

Fonti: tabelle `pipeline_run` (righe 146, 150, 153), `bando`, `bando_pubblico`, `monitoraggio_riepilogo`;
`scraper_bandi/app/sorveglianza.py:291`; `docs/bandi-monitor/RIPRESA.md:332-366`.

---

## 2. Da dove arrivano i bandi (fonti e scraping)

I numeri del giro di avvio di oggi (riga 150 di `pipeline_run`) e i conteggi delle tabelle sono stati letti sul DB
l'01/10. Dove compare **«(non ricontrollato)»**, il numero viene dalla prima indagine e non è stato riletto.

### 2.1 L'idea in breve

La raccolta fa due cose, una dopo l'altra, all'inizio di ogni giro.

1. **Sapere da dove leggere** (`discover`). È l'elenco delle pagine da visitare, salvato nella tabella `fonte`.
2. **Leggere quelle pagine** (`scrape`). Per ogni bando trovato scrive o aggiorna una riga «grezza» nella tabella
   `bando`.

Tutto quello che succede dopo (arricchimento, fonte ufficiale, pubblicazione, sorveglianza) parte dalle righe create
qui. Se la raccolta non vede un bando, il bando per il sistema non esiste.

Prima di questi due passi il giro azzera la cache e i contatori dello «scarico», il client HTTP del giro (§2.10).
Rilegge anche dal DB l'elenco dei domini ammessi.

Fonti: `backend/app/bandi_pipeline.py:307-322`.

### 2.2 Due tipi di fonti

| Tipo | Quante | Da dove vengono | Chi le aggiorna |
|---|---|---|---|
| **Scoperte** | La maggior parte | Dalla pagina «opportunità 2021-2027» di OpenCoesione, il portale nazionale dei fondi di coesione | Il `discover`, a ogni giro |
| **Esterne** | 3 | Inserite a mano, con `discoverable=false`: **449 ObiettivoEuropa** (API JSON con login), **450 Italia Domani** (pagine HTML lette a blocchi di 20 risultati), **451 Incentivi.gov.it** (motore di ricerca Solr, risponde in JSON) | Nessuno: il `discover` non le mette mai fra le «deprecated» |

Oggi la tabella `fonte` ha **121 righe**:
- 103 «ready» e attive: 100 scoperte più le 3 esterne;
- 14 in «connection error»;
- 4 «deprecated».

(Dopo il giro delle 12: 102 «ready» e 15 in «connection error».)

Fonti: `scraper_bandi/app/db.py:69-120`, `scraper_bandi/app/scraper_config.py:845-903`, tabella `fonte`.

### 2.3 Il discover, passo per passo

1. **Scarica una sola pagina**: l'indice delle opportunità di OpenCoesione (`OPENCOESIONE_URL`, predefinita
   `opencoesione.gov.it/it/opportunita_2021_2027/`).
2. **Prende i link il cui testo contiene «Opportunità» o «Preavvis…».** Li divide nei blocchi della pagina: Programmi
   Regionali, Programmi Nazionali, CTE a titolarità italiana e CTE a partecipazione italiana (CTE vuol dire
   cooperazione territoriale europea).
3. **Classifica ogni link.** La categoria del programma viene dal titolo del blocco. Se il blocco non si riconosce ma
   il titolo della sezione contiene il nome di una regione, il link vale come regionale. La tipologia (PR FESR, PR
   FSE+…) viene dal nome del programma.
4. **Elimina i doppioni.** Se lo stesso indirizzo compare due volte, vince «Opportunità» su «Preavviso».
5. **Controlla se ogni indirizzo risponde.** Prova prima una richiesta leggera (HEAD). Passa a una normale (GET)
   **solo** se la HEAD fallisce per un errore di rete o riceve 405/501. Se invece la HEAD riceve un rifiuto come 403,
   non c'è un secondo tentativo. Lavora 10 indirizzi alla volta, con 15 secondi di attesa massima. Una risposta 2xx
   vale «risponde», qualunque altra cosa «non risponde». Dalla risposta ricava anche il formato (HTML, PDF o CSV).
6. **Aggiorna la tabella `fonte`.** Se l'indirizzo risponde, la fonte diventa «ready» e attiva. Se non risponde,
   diventa «connection error» e non attiva. Vale anche per una fonte «deprecated» che ricompare su OpenCoesione: torna
   «ready».
7. **Mette da parte le fonti sparite.** Quelle che non compaiono più su OpenCoesione diventano «deprecated» e non
   attive. Fanno eccezione le 3 esterne. Se il comando gira con `--limit`, questo passo si salta: l'elenco è parziale e
   farebbe sparire fonti buone.

**Numeri di oggi.** Il giro di avvio ha trovato 114 link e nessuno nuovo; 14 non rispondevano (15 al giro delle 12).
Nei due giri prima erano 17 e 18 (non ricontrollato).

Fonti: `scraper_bandi/app/discover.py:111-256`, `scraper_bandi/app/classifier.py:51-66, 131-140`,
`scraper_bandi/app/reachability.py:67-115`, `scraper_bandi/app/settings.py:48, 432-433`,
`scraper_bandi/app/orchestrator.py:14-41, 123-135`, `scraper_bandi/app/db.py:28-131`, `pipeline_run` (righe 143, 147,
150, 153).

### 2.4 Perché il numero di fonti lette cambia da un giro all'altro

La prova «risponde o no?» si rifà **a ogni giro**. Una fonte lenta, o che respinge i programmi automatici proprio in
quel momento, diventa «connection error». In quel giro non viene letta. Al giro dopo, se risponde, torna «ready».

Per questo le fonti in elenco oscillano: 99, 100, 103 (non ricontrollato); oggi 103 al giro di avvio, 102 a quello
delle 12.

Un caso concreto: alcune fonti sono configurate per essere lette con Firecrawl proprio perché hanno protezioni
anti-bot (nel registro ci sono 4 voci della Lombardia). La prova di raggiungibilità però usa una richiesta semplice, e
un 403 alla HEAD basta a scartare la fonte. Così queste fonti possono essere scartate prima ancora di arrivare a
Firecrawl. Che oggi succeda proprio alle fonti lombarde è **non verificato**.

Alcune fonti risultano lette «a intermittenza»: Cultura (287, 288) in 19 giri su 35, Piemonte (251-253) in 26-28 giri
(non ricontrollato). Il motivo esatto è **non verificato**: lo storico dello stato delle fonti non viene salvato.

Fonti: `scraper_bandi/app/reachability.py:80-86`, `scraper_bandi/app/orchestrator.py:30`,
`scraper_bandi/app/scraper_config.py` (voci `firecrawl_scrape` della Lombardia), `fonte_run`.

### 2.5 Il registro: come si legge ogni fonte

La tabella `fonte` dice **dove** leggere. Il **come** sta in un file di codice: il registro `SCRAPER_CONFIG`, con 109
voci. Ogni voce collega l'indirizzo di una fonte a una «strategia» di lettura e ai suoi parametri: quali link
prendere, quante pagine leggere, quale traduttore usare.

**Come si cerca la voce giusta.** Non si confrontano gli indirizzi lettera per lettera. Prima si «normalizzano»: niente
`#…` finale, caratteri `%xx` decodificati, parametri in ordine, niente slash in fondo, minuscole, niente accenti. Il
motivo è che l'indirizzo salvato in `fonte` e quello del registro spesso differiscono per piccoli dettagli. Il `www.`
invece resta.

**Le strategie**, con il numero di voci nel registro (conteggio verificato sul file):

| Strategia | Voci | Che cosa fa, in parole semplici | Che cosa produce |
|---|---|---|---|
| `httpx_bs4` | 38 | Scarica la pagina elenco (anche più pagine con `?page=N`) e prende i link che corrispondono a una regola | Un bando per link |
| `hybrid_httpx_firecrawl` | 22 | Scarica la pagina, trova i file PDF/CSV/XLSX, tiene i 3 più recenti e li legge | Righe di calendario |
| `skip_no_bandi` | 22 | Pagina senza bandi (indice generico, pagina inesistente): si salta senza errore | Niente |
| `firecrawl_scrape` | 15 | Come `httpx_bs4`, ma la pagina la apre Firecrawl, un servizio esterno a pagamento che sa leggere i siti con JavaScript o protezioni | Un bando per link |
| `pdf_extract_tables_pdfplumber` | 4 | Legge le tabelle di un PDF di calendario | Una riga di calendario per bando |
| `csv_parser` | 3 | Legge un calendario in CSV | Una riga di calendario per bando |
| `pdf_extract_text` | 1 | Legge il testo di un PDF | Righe di calendario |
| `firecrawl_extract` | 1 | Firecrawl con un modello che estrae i dati (solo Interreg Italia-Austria, fonte 302) | Bandi strutturati |
| `json_api_paginated` | 1 | Incentivi.gov.it | Un bando per scheda |
| `json_api_paginated_login` | 1 | ObiettivoEuropa, con login | Un bando per scheda |
| `html_paginated_offset` | 1 | Italia Domani | Un bando per scheda |

Ci sono due precisazioni da fare.

- **«hybrid» non usa mai Firecrawl.** Malgrado il nome, nessuna voce del registro lo accende (`use_firecrawl`): in
  pratica è sempre una lettura semplice.
- **Che cosa sono i «calendari».** Alcune Regioni non pubblicano una pagina per bando, ma un file (PDF o CSV) con
  l'elenco dei bandi previsti. Ogni riga di quel file diventa un bando «senza link». Il nome sta nel titolo e tutte le
  altre colonne finiscono in `raw_data`. Se un CSV ha una colonna con un link, il link si salva, ma l'identità della
  riga resta quella del calendario (§2.8).

**Per le 3 fonti esterne** c'è un traduttore (*adapter*) per ciascuna. Trasforma la scheda del portale nel formato
standard: link, titolo, tipo di link e dati grezzi.

**Le 103 fonti in elenco oggi, per strategia** (non ricontrollato): 36 httpx_bs4, 20 hybrid, 18 skip, 9
firecrawl_scrape, 4 tabelle PDF, 3 CSV, 1 ciascuna per le altre cinque, e **8 senza alcuna voce nel registro**
(ricontrollato: `fonti_skipped_no_strategy` = 8).

Quelle 8 si saltano a ogni giro. Il log scrive un avviso («NO CONFIG IN REGISTRY») e il diario del giro le conta, ma
non scrive nessuna riga in `fonte_run`. L'elenco (non ricontrollato):
- 256 e 258 Sardegna: l'indirizzo in `fonte` ha un parametro `&sort…` che la chiave del registro non ha;
- 267 Bolzano;
- 289 e 290 PNES salute;
- 313 Interreg Italia-Svizzera (file zip);
- 10548 e 10549 Veneto FESR, fonti nuove.

Fonti: `scraper_bandi/app/scraper_config.py` (109 voci, conteggio eseguito sul file), `scraper_bandi/app/registro.py:44-64,
111-116`, `scraper_bandi/app/bando_runner.py:596-616`, `scraper_bandi/app/scrapers/__init__.py`,
`scraper_bandi/app/scrapers/hybrid.py:176-196, 234-236`, `scraper_bandi/app/scrapers/csv_parser.py:255-298`,
`scraper_bandi/app/scrapers/pdf_extract.py:160-183`, `scraper_bandi/app/scrapers/adapters/`.

### 2.6 ObiettivoEuropa e il login

ObiettivoEuropa è la fonte più importante: da lì viene l'81% dei pubblicati. Agli utenti anonimi mostra 5 risultati per
pagina, a quelli autenticati 50. Per questo il sistema entra con un account.

Il login segue questi passi:
1. apre la pagina di login e prende il codice di sicurezza (token CSRF);
2. invia le credenziali, prese dall'`.env`;
3. controlla di aver ricevuto il cookie di sessione;
4. **controlla che la sessione funzioni davvero**: la prima pagina dei risultati deve averne almeno 50.

I tentativi sono al massimo 3 in tutto: il primo subito, poi uno dopo 60 secondi e uno dopo altri 120. Poi si arrende.
**Non ripiega mai su una lettura anonima**, che darebbe un elenco incompleto e farebbe sembrare «spariti» molti bandi.
In quel caso la fonte intera conta come «in errore».

La sessione resta in memoria per tutta la vita del processo e viene ricontrollata (con una richiesta) a ogni uso. Se
non è più valida, si rifà il login.

La lettura parte dai bandi pubblicati più di recente, seguendo il link «pagina dopo» dell'API, fino a un massimo di 100
pagine, con mezzo secondo di pausa fra una pagina e l'altra. Altri dettagli utili:
- il campo «giorni alla scadenza» non si salva, perché cambia ogni notte e farebbe sembrare cambiato ogni bando;
- un bando segnato «in arrivo» (`on_arrival`) diventa di tipo «Preavviso» (ma vedi §8.3, B14);
- l'identificativo del bando su ObiettivoEuropa si salva in `raw_data`.

Fonti: `scraper_bandi/app/scrapers/auth/obiettivo_europa.py` (`TENTATIVI_MAX`, `BACKOFF_S`, `obtain_session`),
`scraper_bandi/app/scrapers/api_paginated_login.py:50-122`, `scraper_bandi/app/scrapers/adapters/obiettivo_europa.py:66-115`,
`scraper_bandi/app/scraper_config.py:851-870`.

### 2.7 Lo scrape di una fonte, passo per passo

Le fonti si leggono una alla volta, in ordine di id.

| Passo | Che cosa succede | Perché |
|---|---|---|
| a. Scelta | Si prendono le fonti «ready» e attive | Quelle che non rispondevano al discover di questo giro restano fuori |
| b. Registro | Si cerca la voce nel registro. Se manca, o se la strategia è «skip», la fonte si salta | Senza istruzioni non si sa come leggerla |
| c. Lettura | Lo scraper scarica e interpreta la pagina | — |
| d. Identità | Per ogni bando trovato si calcola l'«hash», la sua impronta unica (§2.8) | Serve a riconoscere lo stesso bando al giro dopo |
| e. Confronto e copertura | Si confronta con quanto già nel database: **nuovo**, **cambiato** o **identico** (§2.9). Insieme si valuta se l'elenco è stato letto per intero | Si riscrive solo ciò che serve. Solo un elenco completo permette di dire «questo bando non c'è più» |
| f. Scrittura | Nuovi e cambiati vanno in `bando`, a blocchi da 500 | — |
| g. Scheda di servizio | Per i bandi già presenti si annota «visto ora nella fonte» e si alza, se serve, la priorità di controllo | Il monitor saprà chi ricontrollare prima |
| h. Segnali | Si registrano in `bando_evento` gli eventi interni del confronto | §2.9 |
| i. Segnale dell'aggregatore | Solo per ObiettivoEuropa (§2.9) | Alimenta il bollino «stato da verificare» |
| j. Diario | Una riga in `fonte_run` per la fonte: quanti elementi, nuovi, cambiati, durata, se l'elenco era troncato | Per misurare nel tempo |

**Che cosa scrive esattamente in `bando`.** Solo le colonne grezze: fonte, hash, tipo di link, link, titolo,
descrizione e dati grezzi.
- Una riga **nuova** nasce nello stato «scraped» (il valore predefinito della colonna) ed entrerà nel preprocess.
- Una riga **già esistente**, anche se pubblicata, aggiorna solo quelle colonne grezze. Il suo stato di lavorazione
  non cambia.

In pratica: **se un bando cambia sul sito della fonte, la lavorazione non riparte da capo.** Il cambiamento arriva al
bando solo come «segnale» al monitor, che deciderà se ricontrollarlo.

Fonti: `scraper_bandi/app/bando_runner.py:516-772`, `scraper_bandi/app/db.py:149-170, 387-436`,
`backend/sql/bando_alter_v6_preprocessing.sql:74`.

### 2.8 L'identità di un bando: l'hash

L'hash è una «impronta» calcolata da alcuni dati. Se i dati sono uguali, l'impronta è uguale. Il database usa
l'impronta per dire «questo bando c'è già».

| Caso | Da che cosa si calcola | Esempio |
|---|---|---|
| Bando con un link | fonte + link | fonte 449 + `https://…/bando-123` |
| Bando senza link (calendario), o con un link segnato come «non identificante» | fonte + file + pagina + numero di riga + titolo normalizzato | fonte 238 + `calendario.pdf` + pagina 2 + riga 12 + «avviso formazione…» |

Un record senza link valido e senza titolo, file e numero di riga si scarta. Il link **non** si normalizza prima del
calcolo.

Ne seguono due effetti da conoscere:

- **Un portale che cambia l'indirizzo di un bando crea una riga nuova.** Il sistema non sa che è lo stesso bando. Era
  prevista una «chiave esterna» (`chiave_esterna`) per seguire il bando anche se cambia URL. Il codice per calcolarla
  esiste (in `gemelli.py`), ma lo scrape non la scrive mai: la colonna è vuota su tutte le righe (ricontrollato).
- **Un calendario che sposta le righe crea doppioni.** Se l'ente toglie una riga in alto, tutte quelle sotto cambiano
  numero di riga e quindi impronta. Lo stesso succede se l'ente pubblica un file nuovo. Oggi ci sono 29 gruppi di
  titoli di calendario pubblicati più volte (non ricontrollato). La riga vecchia resta pubblicata finché il passo
  «gemelli» non la fonde con la nuova. Oggi però i gemelli sono in ombra e non fondono niente.

Fonti: `scraper_bandi/app/bando_runner.py:77-127`, `scraper_bandi/app/normalize.py:9-34`,
`scraper_bandi/app/gemelli.py:306-330`, tabella `bando`.

### 2.9 Il confronto con il giro prima: nuovi, cambiati, identici

Il sistema rilegge dal database le righe con le stesse impronte e confronta solo i campi che contano. Quali campi
contano dipende dalla «famiglia» della fonte:

| Famiglia | Campi confrontati |
|---|---|
| ObiettivoEuropa | stato, etichetta della scadenza, «in arrivo», data di pubblicazione, budget, data di modifica, «aggiornamenti attivi», tipo di link |
| Incentivi.gov.it | apertura, chiusura, link esterno, budget, data di ultimo aggiornamento |
| Italia Domani | stato, apertura, chiusura, amministrazione |
| Calendari | tutti i dati grezzi, tranne quelli di posizione (riga, pagina) |
| Pagine HTML | titolo e link |

Solo **nuovi** e **cambiati** si riscrivono. Così non si riscrivono a ogni giro migliaia di righe identiche.

**I segnali.** Ogni cambiamento produce un evento interno, «segnale_fonte», con una priorità:
- 90 per stato, scadenza o tipo di link;
- 60 per la data di modifica o gli «aggiornamenti attivi»;
- 40 per budget, data di pubblicazione e ogni altro campo.

C'è una regola fissa: **un segnale non scrive mai date né stati**. Alza solo la priorità del bando per il monitor.
Questi eventi non sono mai visibili al pubblico.

**Il caso particolare di ObiettivoEuropa.** Se la data scritta nell'etichetta della scadenza è diversa dalla scadenza
salvata, si emette un segnale a priorità 90 anche se non è cambiato nulla. Una riga in questa situazione e senza altri
cambiamenti non si conta né fra i nuovi, né fra i cambiati, né fra gli identici.

**Il segnale dell'aggregatore (giro 2, solo ObiettivoEuropa).** Per ogni bando pubblicato di ObiettivoEuropa si calcola
un'etichetta, in quest'ordine:
- **«in_uscita»**: ObiettivoEuropa lo segna in chiusura (status 2);
- **«scadenza_passata»**: la data dell'etichetta è prima di oggi;
- **«assente_dal_listing»**: il bando, ancora vivo, non compare nell'elenco da più di 3 giri (18 ore);
- **vuota**: il bando è ricomparso in ordine (status 1).

L'etichetta si scrive solo quando cambia e alimenta il bollino «stato da verificare» (§4.7). Tre cautele riguardano
«assente»:
- vale solo se l'elenco è stato letto per intero (vedi sotto);
- con un elenco vuoto gli assenti non si cercano affatto;
- se gli assenti nuovi superano il 20% dei pubblicati vivi della fonte, non se ne scrive nessuno e nel log compare
  `[ALLARME]`. Si assume che l'elenco sia rotto, non che siano chiusi tutti insieme centinaia di bandi.

**La copertura: «ho letto tutto?».** Ogni scraper dovrebbe dire quante pagine ha letto, se si è fermato prima della fine
e quanti elementi la fonte dichiara. Il valore di partenza è «troncato», cioè «non so se ho letto tutto». L'elenco conta
come completo solo se:
- non è troncato;
- gli elementi letti sono almeno quelli dichiarati;
- non si è dimezzato rispetto al giro prima.

Solo tre strategie dichiarano questi dati: `httpx_bs4` (pagine lette e pagine fallite, senza totale) e le due API JSON,
che dichiarano anche il totale. Firecrawl, hybrid, CSV, PDF e Italia Domani restano sempre «troncati». Per loro
**nessuna assenza può mai essere dedotta**.

Fonti: `scraper_bandi/app/segnali.py:64-145` (priorità e campi), `:281-301` (copertura), `:433-575`
(`mismatch_scadenza_oe`, `confronta`), `:640-713` (segnale dell'aggregatore), `scraper_bandi/app/bando_runner.py:238-322`,
`scraper_bandi/app/scrapers/base.py:41-80`, `scraper_bandi/app/scrapers/httpx_bs4.py:137-143`,
`scraper_bandi/app/scrapers/api_paginated.py:289`.

### 2.10 Lo «scarico»: il client HTTP del giro (che lo scrape però non usa)

Lo «scarico» è il componente unico per scaricare pagine durante un giro. Ha le sue regole:
- una sola connessione riusata per tutto il giro, 20 secondi di attesa, 2 nuovi tentativi se il sito risponde «troppe
  richieste», dà un errore temporaneo o non risponde;
- una cache di un'ora, che vale solo per il giro: si svuota all'inizio di ogni giro e non conserva mai errori o pagine
  vuote;
- un limite di 5 MB per pagina;
- Firecrawl come ripiego solo per la pagina principale di un bando, e solo se la pagina è bloccata da un firewall
  (403/406) o è quasi solo codice JavaScript (meno di 500 caratteri di testo). Ogni chiamata costa 1 credito e viene
  contata;
- una lista nera di 10 aggregatori, che vale solo quando si cerca la fonte ufficiale;
- gli host che non esistono più (errore DNS) si saltano per il resto del giro. Con 5 host così nello stesso giro
  scatta un allarme («resolver locale?»).

**Attenzione: lo scarico serve preprocess, enrich, resolver, monitor e verifica dello stato, non lo scrape.** Lo scrape
usa ancora le funzioni vecchie di `http.py`, che creano una connessione nuova a ogni chiamata (con almeno 1 secondo tra
due richieste allo stesso sito). Oppure chiama Firecrawl direttamente. Il commento in testa allo scarico dice il
contrario («unico punto di scarico»), ma per lo scrape è sbagliato.

Una conseguenza pratica: **i crediti Firecrawl spesi dallo scrape non entrano nei tetti di spesa.** Lo scrape chiama
Firecrawl senza le opzioni di risparmio dello scarico: secondo il commento dello scarico può costare fino a 5 crediti a
chiamata invece di 1. Le fonti lette così sono 9 `firecrawl_scrape` più 1 `extract` a ogni giro (non ricontrollato).
Quanti crediti consumino davvero è **non verificato**: il dato sta solo nella console di Firecrawl.

Fonti: `scraper_bandi/app/scarico.py:1-30, 56-88, 523-541, 683-700`, `scraper_bandi/app/http.py:22-61`,
`scraper_bandi/app/scrapers/firecrawl.py:41-46, 84-88`, `scraper_bandi/app/scrapers/httpx_bs4.py:24`,
`scraper_bandi/app/scrapers/hybrid.py:191-196`, `scraper_bandi/app/enricher.py:76-92`, `scraper_bandi/app/preprocessor.py:771`.

### 2.11 I numeri del giro di avvio di oggi (10:10-10:18)

| Misura | Valore |
|---|---|
| Fonti in tabella | 121 (103 in elenco, 14 non rispondevano, 4 deprecate) |
| Fonti in elenco (pronte e attive) | 103: 77 lette davvero, 18 saltate di proposito («skip»), 8 senza voce nel registro |
| Fonti «in errore» | 0 (ma vedi §2.12: è un numero ingannevole) |
| Record estratti | 3.758 (1.914 con link, 1.844 di calendario senza link) |
| Esito del confronto | 3 nuovi, 44 cambiati, 3.682 identici |
| Segnali emessi | 74 |
| Bandi ObiettivoEuropa «in_uscita» | 59 |
| «assente_dal_listing» / «scadenza_passata» | 0 / 0 |
| Elementi letti da ObiettivoEuropa | 1.004 (nei giri prima 1.110-1.122; non ricontrollato) |
| Fonti lette con 0 elementi | 25 su 77; 22 di queste non hanno mai prodotto nulla dal 24/09 |

Come leggere due di questi numeri, in base al codice:
- I record estratti (3.758) superano di 29 la somma di nuovi, cambiati e identici (3.729). Il codice lo spiega: le
  righe di ObiettivoEuropa con solo la differenza fra etichetta e scadenza non finiscono in nessuno dei tre gruppi.
  Quindi le 29 righe dovrebbero essere proprio quelle. Anche il conto dei segnali torna: 44 + 29 = 73, più
  verosimilmente 1 riga che ha avuto entrambi i segnali, per un totale di 74. È un'ipotesi coerente con il codice, non
  verificata riga per riga.
- «Elementi letti» in `fonte_run` è la somma di nuovi, cambiati e identici, non il numero di record letti. Le righe con
  solo la differenza di scadenza non ci sono.

Fonti: `pipeline_run` (riga 150, `contatori.scrape`), `fonte_run`, `fonte`, `bando_controllo`;
`scraper_bandi/app/segnali.py:508-512`, `scraper_bandi/app/bando_runner.py:775-797`.

### 2.12 Che cosa non funziona come dovrebbe

| Problema | Gravità | In parole semplici |
|---|---|---|
| **Italia Domani (450) e Incentivi (451) non hanno mai prodotto un bando** | alta | Risultano «ready», ma in tutte le 87 letture registrate (89 dopo il giro delle 12) hanno dato 0 elementi e nel database non c'è nessuna loro riga. Dal Mac rispondevano e i traduttori funzionavano: il guasto sembra del server, ma la causa è **non verificata** |
| **Rischio Incentivi** | alta | Se ripartisse, la ricerca «tutto» (`q=*:*`) porterebbe oltre 6.000 schede (6.037, non ricontrollato), quasi tutte storiche, in un solo giro, con costi di modello per preprocess ed enrich e un giro lunghissimo (§3.3.7). Il tetto è di 50 pagine da 100, cioè 5.000, sotto il totale: la lettura risulterebbe sempre incompleta |
| **Gli errori delle fonti non si vedono** | alta | Quasi tutti gli scraper catturano da soli gli errori di rete e restituiscono «0 elementi». Il giro quindi dice «0 fonti in errore» anche con 25 fonti vuote. Le poche fonti che vanno davvero in errore (per esempio il login di ObiettivoEuropa fallito) non scrivono nemmeno la riga del diario |
| **L'evento «sparito dalla fonte» non può mai nascere** | media | Per un difetto di logica il sistema rilegge dal DB solo le righe con le impronte appena viste, quindi nessuna risulta mai sparita. Le assenze si sorvegliano solo per ObiettivoEuropa, con il segnale dell'aggregatore |
| **Segnali ripetuti all'infinito** | media | La differenza tra etichetta e scadenza di ObiettivoEuropa si riemette a ogni giro: 1.693 eventi identici su soli 70 bandi, fino a 43 per bando (non ricontrollato) |
| **Fonte 276 (calendario Umbria) legge il PDF sbagliato** | media | Legge un regolamento UE dell'Emilia-Romagna: 1.500 righe spazzatura (tutte scartate), 25 riscritture e 25 segnali a ogni giro (non ricontrollato) |
| **8 fonti senza istruzioni** | media | Si saltano a ogni giro con un solo avviso nel log, senza riga in `fonte_run` (elenco in §2.5) |
| **Raggiungibilità a ogni giro** | media | Le fonti lente o anti-bot spariscono dal giro a intermittenza. Un 403 alla prima richiesta basta (§2.3, §2.4) |
| **Doppioni dei calendari** | media | 29 gruppi pubblicati più volte, e i gemelli sono in ombra (§2.8) |
| **Indirizzi cambiati = bando nuovo** | media | La «chiave esterna» prevista non è mai scritta dallo scrape (§2.8) |
| **Etichetta sbagliata su 450 e 451** | media | In alcune parti del codice Italia Domani e Incentivi sono trattate come se fossero ObiettivoEuropa (`FONTI_OE = 449, 450, 451` in `gemelli.py` e `fonte_ufficiale.py`) |
| **Incentivi: un dato scartato** | bassa | Il traduttore butta la «data di ultimo aggiornamento» (`ds_last_update`), che il confronto vorrebbe usare: quel segnale non può mai scattare |
| **Firecrawl fuori dai conti** | bassa | §2.10 |
| **La fonte 302 «cambia» a ogni giro** | bassa | L'estrazione con un modello dà risultati diversi a ogni lettura: 3 «cambiati» per giro e 121 eventi in tutto (non ricontrollato), e spende crediti ogni volta |
| **Guardia spenta su ObiettivoEuropa** | bassa | La voce del registro non imposta `min_risultati_prima_pagina`, quindi durante la lettura non c'è il controllo «almeno 50 risultati in prima pagina». Resta solo quello fatto al login |
| **Login che ferma il giro** | bassa | Le pause del login (60 + 120 secondi) usano un'attesa che blocca tutto il processo: in caso di problemi il giro resta fermo fino a 3 minuti, più i tempi delle richieste |
| **Diario per fonte povero** | bassa | Lo scrape non scrive mai diverse colonne di `fonte_run`: `pipeline_run_id`, `identici`, `segnalati`, `spariti`, `pagine`, `login_ok`, `errore`. Non si distingue «fonte vuota» da «fonte rotta» |
| **Schede di servizio inutili** | bassa | Lo scrape aggiorna la scheda di controllo anche dei bandi scartati: 1.987 righe `rejected` in `bando_controllo` |
| **Commenti vecchi** | bassa | Il codice parla di «~200 link» (sono 114), «~108 fonti», «scrape 20-30 minuti» (oggi circa 6) e di un sender che «fa restart» a ogni giro (invece vive per giorni) |

Fonti: `fonte_run`, `bando`, `bando_evento`; `scraper_bandi/app/bando_runner.py:130, 596-640, 775-797`,
`scraper_bandi/app/segnali.py:578-628`, `scraper_bandi/app/telemetria.py:140-177`, `scraper_bandi/app/scraper_config.py:851-903`,
`scraper_bandi/app/scrapers/api_paginated.py:186-200`, `scraper_bandi/app/scrapers/firecrawl.py:84-88`,
`scraper_bandi/app/scrapers/csv_parser.py:196-198`, `scraper_bandi/app/scrapers/pdf_extract.py:98-100`,
`scraper_bandi/app/gemelli.py:88, 294`, `scraper_bandi/app/fonte_ufficiale.py:1811`,
`scraper_bandi/app/scrapers/adapters/incentivi_gov_it.py:67-90`, `scraper_bandi/app/scrapers/auth/obiettivo_europa.py`
(`BACKOFF_S`, `obtain_session`), `scraper_bandi/app/discover.py:3`, `backend/app/bandi_pipeline.py:5, 58-64`.

### 2.13 Non verificato in questo capitolo

- I numeri marcati «(non ricontrollato)»: vengono dalla prima indagine.
- Perché Italia Domani e Incentivi danno 0 elementi dal server. Le ipotesi sono un rifiuto immediato per Italia Domani
  (0,3 secondi per lettura) e un timeout di 30 secondi per Incentivi (il timeout per pagina nel codice è proprio 30
  secondi). Servono i log di produzione.
- Perché oggi gli elementi di ObiettivoEuropa sono scesi da circa 1.110 a 1.004. Una parte può dipendere dal modo di
  contare (§2.11): le righe con solo la differenza di scadenza non entrano negli «elementi».
- Perché oggi non è stato scritto nessun «assente_dal_listing». Le condizioni nel codice sono molte: elenco completo,
  ultima vista più vecchia di 18 ore, solo bandi pubblicati e vivi. Il totale dichiarato dal portale però non viene
  salvato, quindi non si sa quale sia mancata.
- Perché le fonti di Cultura e del Piemonte sono lette a intermittenza.
- Quanti crediti Firecrawl consuma lo scrape.
- Il fuso orario del server: è dedotto dai tempi registrati nel database.
- Il commit esatto del deploy di oggi (d7f5663): il database non lo registra.
- Il nome del servizio systemd e i valori dell'`.env` del server (modelli, `MONITOR_GIRI`, `MONITOR_STATI_ESTESI`, tetti).

Fonti: `fonte_run`, `pipeline_run`, `scraper_bandi/app/scrapers/api_paginated.py:186-188`, `scraper_bandi/app/segnali.py:663-713`.

---

## 3. La pipeline, giro per giro

Questo capitolo spiega come lavora il sistema dei bandi nel corso di una giornata: chi lo fa partire, in che ordine
girano i passi, che cosa fa ciascun passo e perché esiste.

Una parola torna spesso, **«giro»**: è un'esecuzione completa della catena di passi, dall'inizio alla fine. Ogni giro è
indipendente dagli altri. Quello che un passo non finisce oggi lo riprende il giro successivo.

### 3.1 Chi fa partire i giri, e quando

Sul server, per i bandi, gira **un solo processo**: il «sender dei bandi» (`backend/app/bandi_sender.py`; il servizio
systemd si chiama `edunews-bandi-sender` secondo l'esempio in `scraper_bandi/deploy/`, ma sul server è **non
verificato**). Il processo resta acceso per giorni e ha un solo compito: lanciare un giro alle **00:00, 06:00, 12:00 e
18:00**. Lancia anche un giro subito dopo ogni avvio (deploy, riavvio, ripartenza dopo un crash). Questo è il **giro di
avvio**, che nel database si chiama `boot`. C'è un'eccezione: se il processo precedente è morto a metà di un giro, il
giro di avvio si salta (§3.3.2).

Alcuni dettagli utili:

- Le quattro ore stanno in una sola costante, `GIRI_SCHEDULER` in `scraper_bandi/app/settings.py`. Il sender controlla
  ogni 60 secondi se è arrivata l'ora: nel database un giro risulta partito qualche secondo dopo l'ora tonda (per
  esempio alle 12:00:20).
- **I giri dello stesso processo sono in fila, mai in parallelo.** Se un giro durasse più di sei ore, il successivo
  partirebbe in ritardo, appena finito il precedente. Un comando lanciato a mano può invece girare in parallelo: lo
  ferma il lucchetto (§3.3.1).
- **Quanto dura un giro oggi:** fra 5,3 e 13,5 minuti, con una mediana di circa **7 minuti** (6,8 minuti, 407 secondi,
  sui 41 giri riusciti dal 23/09 al giro di avvio dell'01/10). Il commento nel codice (`bandi_pipeline.py`, riga 58)
  parla di «circa 80 minuti», ma è vecchio.
- **Fuso orario:** il codice dei bandi calcola date e giornate in ora di Roma. Nel database (che usa l'ora UTC) il giro
  delle 00:00 risulta partito alle 22:00 e quello delle 06:00 alle 04:00. Questo è coerente con un server in ora di
  Roma, ma il fuso della macchina è **non verificato** direttamente.

**Esempio reale: il giro di avvio di oggi.** Dopo il deploy, il giro è durato dalle 10:10 alle 10:18 (499,6 secondi),
con esito «ok». Ha trovato 3 bandi nuovi, li ha elaborati e li ha pubblicati tutti e 3.

Fonti: `backend/app/bandi_sender.py`, `scraper_bandi/app/settings.py` (riga 288), tabella `pipeline_run` (riga 150).

### 3.2 La tabella dei giri

Questa è la tabella da tenere a portata di mano. I passi sono **nell'ordine esatto** in cui girano dentro un giro.

**Dal deploy del giro 3** (codice pronto l'01/10/2026 sul branch `claude/bandi-giro-3`, deploy a carico di Michele:
RIPRESA §1; contratto interno `docs/contracts/bandi-giro-3.md` §2). Fino al deploy in produzione gira l'ordine di
prima, descritto più sotto.

| N. | Passo | 00:00 | 06:00 | 12:00 | 18:00 | Avvio |
|---|---|:-:|:-:|:-:|:-:|:-:|
| — | Azzeramento iniziale (cache e contatori degli scaricamenti, lista dei domini in memoria) | sì | sì | sì | sì | sì |
| 1 | **discover**: elenco delle fonti da OpenCoesione | sì | sì | sì | sì | sì |
| 2 | **scrape**: lettura delle fonti, bandi nuovi in tabella | sì | sì | sì | sì | sì |
| 3 | **domini**: import di IndicePA (interruttore proprio, `DOMINI_MODALITA`) | — | sì, solo se nel mese non c'è già un import «ok» | — | — | — |
| 4 | **resolver precoce**: cerca la pagina ufficiale dei bandi appena entrati, *prima* di preprocess ed enrich | sì | sì | sì | sì | sì |
| 5 | **preprocess**: è un bando vero? Stato e tre date, letti **sulla pagina ufficiale** quando c'è | sì | sì | sì | sì | sì |
| 6 | **enrich**: classificazione, anche lei sulla pagina ufficiale | sì | sì | sì | sì | sì |
| 7 | **resolver** «nuovi»: seconda passata, per chi il precoce non ha risolto | sì | sì | sì | sì | sì |
| 8 | **ricontrolli**: il resolver ripassa **tutti** i pubblicati senza fonte trovata e non chiusi | sì | sì | sì | sì | — |
| 9 | **verifica dello stato, fase ingresso**: cerca una scadenza ai bandi nuovi | sì | sì | sì | sì | sì |
| 10 | **SEO**: filtri, scrittura della scheda, **pubblicazione**, righe di candidatura e allegati in `bando_link` | sì | sì | sì | sì | sì |
| 11 | **link_verifica**: controlla i link di `bando_link` e li rende pubblicabili | sì | sì | sì | sì | — |
| 12 | **rielaborazione**: rilegge i pubblicati dalla pagina ufficiale (date e classificazione) | sì | sì | sì | sì | — |
| 13 | **monitor**: ricontrolla le pagine ufficiali, **tutti gli aperti a ogni giro** | sì | sì | sì | sì | — |
| 14 | **verifica dello stato, fase controlli** | sì | sì | sì | sì | — |
| 15 | **gemelli**: fonde i doppioni certi (interruttore proprio, `GEMELLI_MODALITA`) | sì | sì | sì | sì | — |
| dopo | **IndexNow** e **riga del diario** in `pipeline_run` | sì | sì | sì | sì | sì |

In breve:

- **Ogni giro delle quattro ore** fa tutto, tranne l'import dei domini, che resta alle 06 una volta al mese. I passi 8
  e 11-15 sono la manutenzione: girano nelle ore di `MONITOR_GIRI`, che dal giro 3 vale per difetto **tutte e quattro**
  (`00:00,06:00,12:00,18:00`). Se nel `.env` del server c'è una riga `MONITOR_GIRI`, vince lei: per questo il deploy la
  toglie (RIPRESA §1).
- **Il giro di avvio** fa solo la catena di ingresso (1, 2, 4-7, 9, 10): un riavvio non deve spendere fuori orario.
- **Un giro lanciato a mano** (`python -m backend.app.bandi_pipeline` senza ora) fa anche la manutenzione, ma non i
  domini.
- **I passi nuovi** (4, 11, 12) si caricano «se esistono», come gli altri passi recenti (§3.3.3).
- **Ogni passo ha un tetto di tempo, non di numero** (§3.3.7): chi resta fuori parte per primo al giro dopo.
- **Il lucchetto del giro** dura 6 ore, cioè la distanza fra due giri (§3.3.1). Un giro con tutti i tetti di tempo
  pieni può avvicinarsi a quel limite (RIPRESA §8.4): da `salute` si leggono durata e copertura di ogni passo.

Che cosa cambia in ciascun passo è in §3.2-bis.

**Fino al deploy del giro 3** (in produzione l'01/10/2026): l'ordine di prima.

| N. | Passo | 00:00 | 06:00 | 12:00 | 18:00 | Avvio |
|---|---|:-:|:-:|:-:|:-:|:-:|
| — | Azzeramento iniziale (cache e contatori degli scaricamenti, lista dei domini in memoria) | sì | sì | sì | sì | sì |
| 1 | **discover**: elenco delle fonti da OpenCoesione | sì | sì | sì | sì | sì |
| 2 | **scrape**: lettura delle fonti, bandi nuovi in tabella | sì | sì | sì | sì | sì |
| 3 | **preprocess**: è un bando vero? Stato e tre date | sì | sì | sì | sì | sì |
| 4 | **enrich**: classificazione (regioni, settori, beneficiari…) | sì | sì | sì | sì | sì |
| 4-bis | **domini**: import di IndicePA nella lista dei domini | — | sì, solo se nel mese non c'è già un import «fatto» | — | — | — |
| 5 | **resolver** «nuovi»: cerca la pagina ufficiale dei bandi nuovi | sì | sì | sì | sì | sì |
| 5-bis | **ricontrolli**: il resolver ripassa al massimo 60 bandi arretrati | — | sì | — | sì | — |
| 5-ter | **verifica dello stato, fase ingresso**: cerca una scadenza ai bandi nuovi | sì | sì | sì | sì | sì |
| 6 | **SEO**: filtri, scrittura della scheda, **pubblicazione** | sì | sì | sì | sì | sì |
| 7 | **monitor**: ricontrolla le pagine ufficiali dei pubblicati | — | sì | — | sì | — |
| 8 | **verifica dello stato, fase controlli**: rilegge lo stato sulle pagine ufficiali | — | sì | — | sì | — |
| 9 | **gemelli**: fonde i doppioni certi | — | sì | — | — | — |
| dopo | **IndexNow** (avviso ai motori di ricerca) e **riga del diario** in `pipeline_run` | sì | sì | sì | sì | sì |

In breve:

- **00:00 e 12:00** fanno 1, 2, 3, 4, 5, 5-ter, 6. È la «catena di ingresso»: i bandi nuovi entrano e vengono
  pubblicati.
- **18:00** fa la catena di ingresso più 5-bis, 7 e 8, cioè la manutenzione dei pubblicati.
- **06:00** fa tutto: 1, 2, 3, 4, 4-bis, 5, 5-bis, 5-ter, 6, 7, 8, 9.
- **Il giro di avvio** fa solo la catena di ingresso, come quelli delle 00 e delle 12.
- Un giro lanciato a mano da riga di comando (`python -m backend.app.bandi_pipeline` senza ora) fa 5-bis, 7 e 8, ma
  **non** 4-bis e 9, che sono legati alla sola ora «06:00».

**Perché questa divisione.** I passi di manutenzione che costano chiamate al modello o scaricamenti (monitor,
ricontrolli, verifica dei controlli) girano solo due volte al giorno, per dimezzare costi e ritmo. I passi delicati
(import dei domini, al massimo una volta al mese, e fusioni dei gemelli) si controllano una volta al giorno, alle 06.

Il giro di avvio esclude apposta tutto questo. **Un riavvio non deve far partire i passi che costano fuori dalle loro
finestre**: dieci riavvii non devono diventare dieci giri del monitor.

**Da dove vengono le ore:**

- Le ore 06 e 18 di 5-bis, 7 e 8 vengono dalla variabile `MONITOR_GIRI`. Il valore predefinito è «06:00,18:00». Se si
  cambia, i tre passi si spostano **insieme**. Un'ora che non è fra le quattro del sender viene scartata.
- Domini e gemelli sono legati alle 06 direttamente nel codice (`GIRO_DELLE_06`).
- Che `MONITOR_GIRI` non sia impostata in produzione lo dice RIPRESA. È coerente con il database (il monitor ha girato
  solo alle 06 e alle 18), ma è **non verificato** sul file `.env` del server.

**Stato al 01/10:**

- Domini, verifica dei controlli e gemelli **non hanno ancora mai girato** (nessuna riga nel diario). Il giro delle 06
  di oggi usava ancora il codice vecchio: la sua riga non ha né `verifica_stato_ingresso` né `passi_non_ok`. Il giro di
  avvio non li comprende.
- La fase ingresso della verifica ha girato nel giro di avvio di oggi e in quello delle 12, con 0 candidati.
- La prima verifica dei controlli è attesa alle 18:00 di oggi.
- I primi domini e i primi gemelli sono attesi alle 06:00 del 02/10.

Fonti: `backend/app/bandi_pipeline.py` (righe 318-426 e 510-512), `backend/app/bandi_sender.py`, tabella `pipeline_run`.


### 3.2-bis Il giro 3, passo per passo

Il giro 3 nasce da otto direttive del committente dell'01/10: il resolver prima di preprocess ed enrich; il monitor a
ogni giro su tutti gli aperti; la scheda aggiornata dalle novità; niente lotti; ricontrolli senza limite; gemelli e
IndicePA attivi; sospensione e revoca sistemate. Contratto interno: `docs/contracts/bandi-giro-3.md`. Tutto quello che
segue vale **dal deploy** (RIPRESA §1).

**Resolver precoce (passo 4).** Prende i bandi appena entrati (`scraped` e `processed` senza fonte trovata), tolti
quelli che il preprocess scarterebbe e i `processed` già chiusi o revocati. Siccome il bando non ha ancora una scadenza
letta dal modello, usa una **scadenza provvisoria** presa dai dati grezzi della fonte (`date_validation.
scadenza_provvisoria`: etichetta di ObiettivoEuropa, `close_date` di Incentivi, `data_chiusura` di Italia Domani,
colonne dei calendari); conta solo come indizio in più, mai in meno. Niente ricerche a pagamento né arbitro. Se trova la
fonte la scrive come oggi; altrimenti **non lascia traccia**, e la passata «nuovi» (passo 7) riprova con la scadenza
vera. Tempo: `TEMPO_PRECOCE_S` (600 s).

**Preprocess ed enrich sulla fonte ufficiale (passi 5 e 6).** Leggono la pagina scelta da
`dominio_ufficiale.scegli_fonte`: la pagina ufficiale se trovata (un PDF no: si torna a `link_bando`), altrimenti
`link_bando`. Ripiego: prima la pagina ufficiale, poi `link_bando`, poi `resolve_bando`. Il preprocess salva anche le
**citazioni** delle date. Tutti e due scrivono la propria riga di spesa (§3.3.6).

**Ricontrolli (passo 8).** Tutti i pubblicati (e gli `enriched`) con fonte `in_verifica` o `non_trovata` e stato non
chiuso né revocato (960 l'01/10), **a ogni giro della manutenzione**, senza data del prossimo controllo e senza limite,
in ordine di ultimo controllo (mai controllato = primo). Fino a 5 bandi in parallelo, mai due richieste insieme allo
stesso host, sempre 1 s fra due richieste allo stesso host. La scheda di ObiettivoEuropa di un bando si legge al
massimo **una volta al giorno**. Tempo: `TEMPO_RICONTROLLI_S` (3600 s); il lucchetto `bandi_resolver` dura quel tempo
più 30 minuti. Oggi il resolver non spende: sonda, ricerca a pagamento e arbitro non sono collegati (§3.9).

**SEO e righe di link (passo 10).** Dopo una pubblicazione riuscita la SEO scrive in `bando_link` le righe di
candidatura (solo con `link_candidatura_source='extracted'`) e degli allegati, con la prova calcolata sulla pagina
letta (`fonte_ufficiale.righe_link_da_payload`). Le righe nascono **non pubblicabili**. La fusione di un bando nuovo nel
gemello già pubblicato segue `GEMELLI_MODALITA`. Le colonne vecchie (`link_candidatura`, `allegati`) restano scritte
fino alla migrazione 07.

**link_verifica nel giro (passo 11).** Il controllo dei link, che prima partiva solo a mano, è un passo del giro, senza
tetto di numero (tempo `TEMPO_LINK_VERIFICA_S`, 1200 s, e rotazione: prima le righe mai verificate, poi dalla
verifica più vecchia, poi per id; una riga già verificata oggi aspetta il giorno dopo).
Rende pubblicabile una riga che risponde 2xx, non sta su un aggregatore e ha una prova. La **quarta prova**, nuova:
l'URL compare nell'HTML della pagina di riferimento del bando. La pagina di riferimento è quella ufficiale se trovata,
altrimenti `link_bando` anche quando è un aggregatore (decisione del lead dell'01/10), purché risponda 2xx; quando la
fonte diventa trovata la prova si rifà sulla pagina ufficiale, senza ritirare quella vecchia. È il passo che chiude il
buco della 07: l'01/10 140 schede aperte avrebbero perso pulsante o allegati, perché le righe c'erano ma non erano
pubblicabili (RIPRESA §8.5).

**Rielaborazione (passo 12).** Rilegge **una volta** ogni pubblicato con fonte trovata (620 l'01/10) dalla pagina
ufficiale, con preprocess ed enrich, **senza** toccare `stato_processing`:
- **date**: una data di apertura o di scadenza diversa, su una colonna non verificata, diventa un evento `rettifica`
  (origine pipeline, non verificato, fuori dagli aggiornamenti), solo se la citazione si ritrova nel testo letto e le
  date restano coerenti. Mai `data_pubblicazione`, mai uno stato: se la data nuova chiede un cambio di stato, lo lascia
  al monitor e mette il bando in testa alla sua coda. La prosa si aggiorna con `rigenera`, senza modello e con la
  stessa conversione del contenuto JSON che usa il monitor (`rigenera._testo_del_contenuto` e `_scrittore_json`), così
  il contenuto resta un oggetto JSON e non diventa una stringa;
- **classificazione** (regioni, settori, beneficiari, ATECO e le tre FK): **due letture indipendenti** dell'enrich
  sulla stessa pagina, perché le risposte del modello variano da una lettura all'altra. Una voce entra solo se c'è in
  tutte e due, esce solo se manca in tutte e due; una FK cambia solo se le due letture danno lo stesso valore. Una
  dimensione con una chiamata fallita, o vuota in una lettura, non si tocca mai. Ogni cambio resta scritto con prima e
  dopo, così si torna indietro con SQL;
- **marcatore**: a fine bando la riga della fonte in `bando_link` riceve `impronta_contenuto = 'rielab:v1:…'`; un
  bando con il marcatore esce dalla coda. Una `rettifica` di contenuto o una riapertura applicate dal monitor lo
  azzerano, e il bando si rielabora al giro dopo. Un allineamento delle junction rimasto a metà (`allinea_junction`
  parziale) si registra nella riga del passo e **non** mette il marcatore: il bando si riprova.

Spesa: step `backfill:rielaborazione`, fuori dai 5 $ al giorno, con un tetto proprio di **60 $ e 8.000 crediti sulla
giornata di Roma** (somma delle righe del passo dalla mezzanotte, `db.consumo_passo_oggi`); se quella lettura fallisce
il passo non parte. La prova a secco dell'01/10 su 5 bandi è costata 0,23 $ con le due letture: circa 4,6 centesimi a
bando, quindi circa 28 $ per i 620, dentro i 60 $. Fino a 5 bandi in parallelo, mai due sullo stesso host; tempo
`TEMPO_RIELABORAZIONE_S` (3600 s). Il comando `rielabora-fonte` fuori dal dry-run prende il lucchetto del giro
(`bandi_pipeline`, proprietario `rielabora-fonte:cli`), quindi non si sovrappone mai a un giro; `rielabora-fonte
--dry-run` non prende lucchetti e non scrive niente: fa solo GET e chiamate al modello.

**Monitor a ogni giro (passo 13).**
- Chi: i pubblicati non fusi con fonte trovata. Aperti, in apertura (anche «da verificare») e sospesi **a ogni giro**,
  senza guardare il prossimo controllo (374 l'01/10). I chiusi con la cadenza di prima (3, 10, 30 giorni) fino a 12
  mesi. Revocati e chiusi da più di 12 mesi **fuori**.
- Ordine: priorità, poi ultimo controllo (mai controllato primo), poi id. Tempo: `TEMPO_MONITOR_S` (3600 s).
- A tetto di spesa (§3.3.6) il monitor continua i controlli gratuiti: scarica e confronta, ma non classifica le pagine
  cambiate (`classificazioni_rinviate`) e non aggiorna l'impronta salvata, così il cambiamento si rivede al giro dopo.
  Le pagine che chiederebbero Firecrawl si rinviano.
- Tipi di evento: con `MONITOR_TIPI_ATTIVI=tutti` si applicano da soli tutti i 12 tipi del monitor, con la strada a tre
  scritture di oggi. Sospensione, revoca e annullamento della revoca solo se c'è la migrazione 14 **e**
  `MONITOR_STATI_ESTESI=true`; altrimenti restano in ombra e `salute` lo dice.

**Eventi → bando e scheda.** Le date (apertura, riapertura, proroga, rettifica) passano dalla RPC e poi dalla
sostituzione senza modello di `rigenera`; se il controllo finale fallisce, la scheda si riscrive con Opus. Un
`nuovo_allegato` scrive anche la riga `allegato` in `bando_link` (URL dell'allegato; la pagina dove l'abbiamo visto va in
`url_prova`). FAQ, graduatoria, esito, rettifiche di contenuto e aperture con testo nuovo riscrivono con Opus solo
`contenuto` e `descrizione_breve`, una volta per bando per giro (le novità si uniscono, al massimo 10 per riscrittura);
slug e titolo restano congelati. La riscrittura conta nei 5 $ (step `rigenerazione_scheda`); a tetto resta in coda.

**Verifica dello stato (passi 9 e 14).** Resta in ombra fino al controllo dell'08/10. Niente più tetti di numero
(letture, chiusure, ingresso): solo il tempo, `VERIFICA_STATO_TETTO_S` (1800 s) con rotazione, e 300 s nella fase
ingresso. `report-verifica-stato --verita` conta come «confermato dallo stato» un bando della tabella che è uscito dai
candidati perché il suo stato è già quello atteso (solo chiusura → chiuso e apertura → aperto): è il caso del 661135.

**Gemelli (passo 15).** Interruttore proprio, `GEMELLI_MODALITA` (non più quello della verifica). Girano a ogni giro
della manutenzione, leggono tutti i pubblicati e non hanno tetto di fusioni. Le guardie di prudenza restano tutte: solo
i criteri `url` e `riga_calendario`, coppie dirette, titoli senza differenze di anno, lotto o edizione, lettura
troncata uguale errore. La prova a secco dell'01/10 elenca 52 fusioni. BandoFit si avvisa una volta sola, prima del
deploy e senza aspettare la risposta (decisione di Michele dell'01/10, `docs/contratto-db-bandi.md` §6.2): niente
avviso per ogni lotto e niente attesa di 7 giorni.

**IndicePA (passo 3).** Interruttore proprio, `DOMINI_MODALITA`. L'01/10 Michele ha importato a mano 22.355 domini e ne
ha spenti 16 con SQL (RIPRESA §8.1). Il codice ora scarta da solo gli host di una sola etichetta e i fornitori di posta
e hosting di privati (`libero.it`, `gmail.com`, `register.it` e altri 15).

**Sospensione e revoca (migrazione 14, §4.6).** Il sospeso ha di nuovo le sue uscite: si chiude con una `chiusura`
letta sulla pagina ufficiale, riapre con una `riapertura` anche datata al passato. Dal revocato si esce solo con
`annullamento_revoca`, verso lo stato calcolato dalle date. **Una proroga su un sospeso aggiorna solo la data di
scadenza**: lo stato resta «sospeso», perché la proroga non dice che la sospensione è finita. La redazione corregge uno
stato sbagliato con `bando_correggi_stato`; due o più correzioni verso lo stesso stato nello stesso giorno sono ammesse
(l'indice che scarta gli eventi doppi non conta le correzioni della redazione). Un evento superato da uno più recente,
o con una transizione non più ammessa, si marca e non torna in coda; una proroga, una riapertura o una rettifica che
porta una scadenza non ancora passata non la supera una chiusura più recente, perché chi ha letto la chiusura non
sapeva della proroga.

Fonti di §3.2-bis: `backend/app/bandi_pipeline.py` (ordine e `_giro_previsto`), `scraper_bandi/app/fonte_ufficiale.py`
(modi `precoce`, `nuovi`, `ricontrolli`, `run_link_verifica`, `righe_link_da_payload`, `ttl_lock_resolver`),
`scraper_bandi/app/date_validation.py` (`scadenza_provvisoria`), `scraper_bandi/app/dominio_ufficiale.py`
(`scegli_fonte`, `analizza_indicepa`), `scraper_bandi/app/rielabora_fonte.py`, `scraper_bandi/app/monitoraggio.py`
(`seleziona`), `scraper_bandi/app/rigenera.py`, `scraper_bandi/app/eventi.py` (`EVENTI_INCOMPATIBILI`,
`stato_dopo_annullamento`), `scraper_bandi/app/gemelli.py`, `scraper_bandi/app/verifica_stato.py`,
`backend/sql/bando_v11_14_sospensioni.sql`; messaggi di chiusura dei task del giro 3 (01/10).

### 3.3 Le regole che valgono per tutti i passi

Prima di vedere i passi uno per uno servono sette regole comuni (dal giro 3, la settima è «niente lotti»). Spiegano quasi tutti i comportamenti «strani».

#### 3.3.1 Il lucchetto del giro (lock)

Ogni giro prova a prendere un **lucchetto nel database** (una riga in `pipeline_lock`) con nome `bandi_pipeline` e
scadenza di 4 ore (**6 ore dal giro 3**: la somma dei tetti di tempo dei passi più la catena d'ingresso supera le 5
ore, e 6 ore sono la distanza fra due giri). Serve a evitare che due giri lavorino sugli stessi bandi nello stesso momento, per esempio un giro
automatico e un comando lanciato a mano.

| Che cosa succede | Conseguenza |
|---|---|
| Lucchetto preso | Il giro lavora e alla fine lo rilascia, anche se qualcosa va storto. |
| Lucchetto già occupato | Nessun passo parte. Il giro risulta «saltato» e nella riga del diario compare `saltato_per_lock`. |
| La funzione del lucchetto manca o va in errore | Il giro prosegue senza lucchetto e lascia un avviso. |

Esempio: alle 12:00:20 del 01/10 il lucchetto `bandi_pipeline` risultava tenuto dal proprietario
`bandi_pipeline@3610122`, con scadenza alle 16:00:20.

Il lucchetto non fa mai morire il sender. Due passi ne prendono anche uno proprio: il resolver (`bandi_resolver`, 2
ore) e il monitor (`monitor`, 3 ore). Se è occupato, quel passo viene saltato ma per il giro conta come «ok».

**Nome del lucchetto e proprietario.** In `pipeline_lock` ogni riga ha un *nome* (che cosa si blocca) e un
*proprietario* (chi lo tiene). È facile confonderli:

| Nome del lucchetto | Durata | Chi lo prende (proprietario) |
|---|---|---|
| `bandi_pipeline` | 4 ore (6 dal giro 3) | il giro (`bandi_pipeline@<pid>`); anche `seo-rigenera` lanciato a mano (`seo-rigenera:cli`, 1 ora) e, dal giro 3, `rielabora-fonte` fuori dal dry-run (`rielabora-fonte:cli`), che così non si sovrappongono mai a un giro |
| `bandi_resolver` | 2 ore (dal giro 3: `TEMPO_RICONTROLLI_S` più 30 minuti, cioè 90 minuti con il default) | il resolver del giro e `risolvi-fonte` lanciato a mano (tutti e due `resolver@<pid>`) |
| `monitor` | 3 ore | il monitor del giro (`monitor:<giro>`), il `monitor` lanciato a mano (`monitor:cli`) e `applica-eventi` (`applica-eventi:cli`): così si escludono a vicenda |

`verifica-stato` e `gemelli` da riga di comando accettano **solo** `--dry-run`: le scritture le fa soltanto il passo del
giro, che è protetto dal lucchetto del giro.

**Attenzione: due prove a secco non sono a sola lettura.** `monitor --dry-run` e `risolvi-fonte --dry-run` prendono e
rilasciano il loro lucchetto con le funzioni del database e scrivono una riga in `pipeline_run` (con costo 0). Dal Mac
quindi **non si lanciano**: un lucchetto preso dal Mac fa saltare il passo del giro che parte in quel momento, e la riga
finisce nel diario di produzione. È già successo: l'01/10 verso le 16:40 un `monitor --dry-run --senza-rete` lanciato
dal Mac ha scritto una riga `monitor` con giro vuoto (NULL). `rielabora-fonte --dry-run` invece non prende lucchetti e
non scrive niente. `rigenera` invece **non prende nessun lucchetto**. Per questo RIPRESA chiede
di lanciarlo (come i deploy) in una **«finestra sicura»**, cioè lontano dai giri: 12:30-16:30 oppure 19:00-22:30.

#### 3.3.2 All'avvio: i lucchetti rimasti appesi e la regola anti-ciclo

Quando un processo muore, il suo lucchetto resta nel database. All'avvio il sender **libera i lucchetti orfani** dei
processi precedenti. Lo fa con la funzione del database `lock_rilascia`, mai cancellando righe. Le regole guardano il
**proprietario**:

- proprietario `bandi_pipeline@<pid>` o `resolver@<pid>`: liberato se quel processo non è più vivo sulla macchina;
- proprietario `monitor:<giro>`: liberato se il lucchetto è stato preso prima dell'avvio e non c'è nessun altro sender
  vivo;
- i proprietari dei comandi manuali, che finiscono in `:cli` (`monitor:cli`, `applica-eventi:cli`,
  `seo-rigenera:cli`), non si toccano mai.

Attenzione: un `risolvi-fonte` lanciato a mano ha proprietario `resolver@<pid>`, con lo stesso formato del sender. Se il
processo non è sulla stessa macchina, all'avvio il sender lo considera orfano e lo libera. È un rischio accettato e
scritto nel codice.

**Regola anti-ciclo.** Se fra i lucchetti liberati c'era quello del giro, il processo precedente è morto a metà di un
giro. In quel caso il giro di avvio **non** si fa: rifarlo subito nello stesso stato potrebbe far cadere di nuovo il
processo, in un ciclo infinito di riavvii. Il sender scrive nel diario una riga «saltato» con `riavvio_dopo_crash=1` e
aspetta il giro successivo in calendario.

Se lo scheduler incontra un errore fatale, il sender esce con codice 1 (prima usciva con 0 e restava giù). Un errore
dentro un giro, invece, non lo fa uscire. Il file systemd che prevede il riavvio dopo 20 minuti
(`Restart=on-failure`, `RestartSec=20min`) esiste nel repository come esempio
(`scraper_bandi/deploy/edunews-bandi-sender-riavvio.conf`). Che sia installato sul server è **non verificato**.

#### 3.3.3 Ogni passo è protetto

**Un passo che fallisce non ferma il giro.** L'errore viene registrato e si passa al passo successivo.

I passi aggiunti più di recente (resolver, ricontrolli, monitor, le due fasi della verifica, domini, gemelli) si
caricano solo «se esistono»:

- un modulo che manca vale «saltato, tutto bene»;
- un modulo presente ma rotto vale «errore», e nel journal compare `STEP <nome> NON PARTITO`.

Per questi stessi passi, un passo che non va in crash ma dichiara da solo `status: errore` nei suoi contatori viene
contato come errore.

**Due parole per la stessa cosa.** Se un passo fallisce, nel journal il giro finisce con `=== BANDI PIPELINE PARTIAL
===` (altrimenti `COMPLETED`). Nella riga di `pipeline_run` lo stesso giro ha esito `errore`, e il nome del passo
compare in `contatori.passi_non_ok`. Chi cerca «partial» nel database non trova niente.

#### 3.3.4 Il diario: `pipeline_run`

Ogni giro scrive **una riga di riepilogo** (step `pipeline`). La riga contiene:

- l'ora del giro (`giro`: «06:00», oppure `boot` per il giro di avvio);
- inizio e fine;
- l'esito;
- i contatori di ogni passo;
- la durata;
- e, dal deploy di oggi, l'elenco `passi_non_ok` dei passi andati male.

L'esito vale `ok`, `errore`, `saltato` oppure `interrotto_per_tetto`, e si decide con una scala di priorità:
**saltato** vince su **interrotto per tetto**, che vince su **errore**, che vince su **ok**.

Alcuni passi scrivono anche una riga propria: resolver e ricontrolli (tutte e due con step `resolver`), monitor,
verifica dello stato (step `verifica_stato_ingresso` e `verifica_stato`) e domini. Discover, scrape, preprocess, enrich,
SEO e gemelli hanno solo la loro sezione dentro la riga di riepilogo. **Dal giro 3** ogni passo che spende scrive la
propria riga (step `resolver_precoce`, `resolver`, `ricontrolli`, `preprocess`, `enrich`, `seo`,
`rigenerazione_scheda`, `backfill:rielaborazione`, oltre a monitor e verifica), e ogni sezione della riga del giro
porta la sua `copertura` (§3.3.7).

**Leggere il diario a mano.** `pipeline_run` ha dieci colonne: `id, step, giro, avviato_at, concluso_at, esito,
interrotto_per_tetto, motivo, contatori, note`. Durata, crediti, dollari, `slug_modificati`, `saltato_per_lock` e
`passi_non_ok` **non** hanno una colonna propria: stanno dentro il JSON `contatori`. Query per il SQL Editor:

```sql
select id, giro, avviato_at at time zone 'Europe/Rome' as avvio, esito,
       (contatori->>'durata_s')::numeric as secondi,
       contatori->'passi_non_ok' as passi_non_ok
from pipeline_run where step = 'pipeline'
order by avviato_at desc limit 8;
```

Se fra due orari del calendario manca una riga, il sender non ha girato.

**Bilancio dal 23/09:** 46 giri fino al giro di avvio dell'01/10 (47 con quello delle 12:00). 41 ok (42 con quello
delle 12), 3 saltati per lucchetto occupato (gli avvii del 24/09 alle 16:27 e del 28/09 alle 08:21, e il giro delle 18
del 24/09), 2 interrotti per tetto (i giri delle 06 e delle 18 del 25/09: in tutti e due il monitor si è fermato sul
tetto giornaliero delle classificazioni). Per il 28/09 il commento in `backend/app/lock_orfani.py` dice che un secondo
riavvio ha trovato il lucchetto del giro di avvio precedente. La causa dei due saltati del 24/09 è **non verificata**.

#### 3.3.5 Ombra e attivo

Molti passi hanno due modalità:

- **ombra**: il passo lavora, legge, decide e **annota** in tabelle interne, ma non cambia niente che vedano il pubblico
  o BandoFit. Serve a misurare se il passo sbaglia, prima di dargli il permesso di scrivere;
- **attivo**: il passo scrive davvero.

Gli interruttori sono variabili del file `scraper_bandi/.env`. Il sender le legge **una sola volta all'avvio**
(`get_settings` resta in memoria per tutta la vita del processo): ogni modifica richiede un riavvio. Un valore assente
o sconosciuto vale «ombra».

| Interruttore | Che cosa governa | Valore oggi |
|---|---|---|
| `RESOLVER_MODALITA` | Le scritture del resolver (passi 5 e 5-bis) e il comando manuale `fondi-doppioni` | **attivo**: nel database, dal giro delle 00:00 del 25/09 |
| `MONITOR_MODALITA` | L'applicazione degli eventi del monitor (passo 7) | **ombra** (riga del monitor delle 06 di oggi) |
| `MONITOR_TIPI_ATTIVI` | L'eccezione: questi tipi di evento si pubblicano anche in ombra | faq, nuovo_allegato, graduatoria, esito, proroga (visto nella riga del monitor delle 06 di oggi; non c'era nel giro delle 18 del 30/09) |
| `MONITOR_STATI_ESTESI` | Sospensione e revoca scritte come stato vero | true secondo RIPRESA (**non verificato**) |
| `VERIFICA_STATO_MODALITA` | **Cinque cose insieme**: verifica dello stato (passi 5-ter e 8), sosta all'ingresso e fusione dei gemelli esatti prima della pubblicazione (dentro il passo 6), fusioni del passo 9, scrittura dell'import IndicePA (passo 4-bis) | **ombra** (riga del giro di avvio di oggi) fino al controllo dell'08/10 |
| `MONITOR_GIRI` | In quali giri girano i passi 5-bis, 7 e 8 | 06:00 e 18:00 (predefinito) |

**Attenzione:**

- **Alcuni passi non hanno l'ombra.** Discover, scrape, preprocess, enrich e SEO (cioè la pubblicazione) scrivono
  sempre. Lo stesso vale per il filtro dei doppioni degli aggregatori dentro la SEO.
- **Un solo interruttore accende cinque cose.** Chi l'8/10 scriverà `VERIFICA_STATO_MODALITA=attivo` accenderà, oltre
  alla verifica, anche le fusioni automatiche dei gemelli (52 previste oggi) e, al primo giro delle 06 dopo il
  riavvio, l'inserimento di circa 22.355 domini da IndicePA: in attivo l'import fatto in ombra non conta, quindi
  l'import riparte.

Il valore reale del `.env` di produzione **non è leggibile dal Mac**. Le modalità sopra sono dedotte dai contatori nel
database.

**Dal giro 3: interruttori separati e tempi per passo.** Il giro 3 separa l'interruttore unico e aggiunge un tetto di
tempo per ogni passo nuovo (contratto `bandi-giro-3` §3). Un valore assente o sconosciuto vale il default; un tempo
fuori intervallo torna al default e `salute` alza l'allarme `configurazione:<nome>` (solo il nome, mai il valore).

| Variabile | Che cosa governa | Default | Valore dopo il deploy (RIPRESA §1) |
|---|---|---|---|
| `VERIFICA_STATO_MODALITA` | **Solo** la verifica dello stato (passi 9 e 14) e la sosta all'ingresso | ombra | ombra fino all'08/10 |
| `GEMELLI_MODALITA` | Le fusioni del passo 15 e la fusione di un bando nuovo nel gemello già pubblicato (dentro la SEO) | ombra | **attivo** |
| `DOMINI_MODALITA` | La scrittura dell'import di IndicePA (passo 3); un `--attivo` esplicito sul comando vince ancora | ombra | **attivo** |
| `MONITOR_TIPI_ATTIVI` | I tipi di evento che si applicano da soli; `tutti` vuol dire i 12 tipi del monitor | nessuno | **`tutti`** (al posto della riga con i 5 tipi) |
| `MONITOR_STATI_ESTESI` | Sospensione, revoca e annullamento: si applicano solo se è `true` **e** c'è la migrazione 14 (`bando_capacita_sospensioni()`); senza, restano in ombra senza allarme e `salute` scrive «sospensioni in attesa della migrazione 14» | false | deve essere `true` |
| `MONITOR_GIRI` | Le ore della manutenzione (passi 8 e 11-15) | **le quattro ore** | riga da togliere se c'è, così valgono le quattro ore |
| `MONITOR_MODALITA` | Resta `ombra`: l'attivazione passa da `MONITOR_TIPI_ATTIVI=tutti`, che usa la strada prudente a tre scritture | ombra | invariato |
| `TEMPO_PRECOCE_S` | Resolver precoce (passo 4) | 600 (60-7200) | default |
| `TEMPO_RICONTROLLI_S` | Ricontrolli (passo 8); il lucchetto `bandi_resolver` dura questo più 30 minuti | 3600 (60-7200) | default |
| `TEMPO_LINK_VERIFICA_S` | link_verifica (passo 11) | 1200 (60-7200) | default |
| `TEMPO_RIELABORAZIONE_S` | Rielaborazione (passo 12) | 3600 (60-7200) | default |
| `TEMPO_MONITOR_S` | Monitor (passo 13) | 3600 (60-7200) | default |
| `VERIFICA_STATO_TETTO_S` | Verifica dello stato, fase controlli (passo 14): è il suo unico freno | 1800 (60-3600) | riga da togliere se c'è |

**Variabili dismesse** (nessun modulo le legge più): `TETTO_CLASSIFICAZIONI_GIORNO`, `TETTO_FETCH_GIRO`,
`VERIFICA_STATO_TETTO_LETTURE`, `VERIFICA_STATO_MAX_CHIUSURE`, `VERIFICA_STATO_TETTO_INGRESSO`,
`GEMELLI_FUSIONI_PER_GIRO`. Se una è ancora nel `.env`, `salute` ne stampa il **nome** come informazione, non come
allarme; cancellarla non è obbligatorio.

#### 3.3.6 I tetti di spesa, e che cosa **non** coprono

Le valute sono due: **crediti Firecrawl** (il servizio a pagamento che scarica le pagine difficili) e **dollari di
token Anthropic** (le chiamate ai modelli).

I tetti dello scenario «bilanciato», quello predefinito (`MONITOR_SCENARIO`), **fino al deploy del giro 3** (dopo, vale
il riquadro «Dal giro 3» più sotto):

| Tipo di tetto | Valore |
|---|---|
| Per giro | 420 pagine scaricate |
| Per giorno | 50 ricerche, 120 crediti, 30 classificazioni, 1,5 $ |
| Per mese | 5.000 crediti, 16 $ |

Quando un passo tocca un tetto **si ferma con calma**: segna «interrotto per tetto» e il giro prosegue. Non è mai un
crash.

Il punto importante è che **i tetti proteggono solo una parte della spesa**:

- **Si contano e si limitano** il monitor, il resolver, il modello della verifica dello stato e i comandi manuali di
  backfill e `rigenera` (questi ultimi con tetti propri: 8.000 crediti e 60 $).
- **Non si contano e non si limitano** la SEO (Opus, la chiamata più cara), il preprocess (Haiku, più Sonnet come
  ripiego), l'enrich (Haiku, 7 chiamate per bando) e il Firecrawl usato da scrape, preprocess, enrich e SEO. Il loro
  costo non compare nel diario: il dollaro che si legge nella riga del giro è solo quello di monitor, resolver e
  verifica. Il costo vero si vede solo nelle console di Anthropic e di Firecrawl.
- **Il tetto mensile non lo applica nessuno.** È scritto nel codice (`bilancio.verifica_mensili`) ma nessun passo gli
  passa i consumi del mese.
- **Il resolver confronta i tetti giornalieri solo con il proprio giro**, non con il totale della giornata. Monitor e
  verifica invece sommano i giri precedenti della giornata (giornata di Roma).

**Spesa registrata a regime (solo il monitor):** fra 0 e 0,46 $ al giorno. I lotti di backfill fatti a mano hanno
speso a parte 7,59 $.

**Dal giro 3 la spesa si conta tutta** (contratto `bandi-giro-3` §4):

- **Un solo meccanismo.** Ogni passo che chiama un modello conta i token con `bilancio.Contatori` e scrive la **propria
  riga** in `pipeline_run`, con la spesa e la copertura: `preprocess` (compreso il ripiego su Sonnet di
  `resolve_bando`, che chiama il preprocess), `enrich`, `seo`, `rigenerazione_scheda`, il monitor e la verifica. `consumo_oggi` le somma sulla giornata di
  Roma, e da ora anche sul mese.
- **I tetti in dollari.** Scenario `bilanciato`: **5 $ al giorno e 150 $ al mese** (economico 3 e 90, massimo 10 e 300).
  Il tetto mensile ora si applica davvero; l'allarme `consumo_mensile_alto` scatta all'80 %. Restano come prima i crediti
  Firecrawl (120 al giorno, 5.000 al mese nel bilanciato) e le 50 ricerche al giorno. Spariscono il tetto delle 30
  classificazioni al giorno e quello delle 420 pagine per giro.
- **Chi si ferma e chi no.** La catena d'ingresso (resolver precoce e «nuovi», preprocess, enrich, SEO dei bandi nuovi)
  **non si ferma mai** per la spesa: conta e basta. La manutenzione (monitor, ricontrolli, verifica, riscritture della
  scheda) a tetto raggiunto **smette di chiamare il modello** ma continua i controlli gratuiti, e non perde niente:
  quello che non ha classificato lo rivede al giro dopo. Nella copertura il motivo è `spesa` (o `crediti`).
- **La rielaborazione** (passo 12) è fuori dal regime: step `backfill:rielaborazione`, con un tetto proprio di 60 $ e
  8.000 crediti sulla giornata di Roma; se la lettura del consumo fallisce, il passo non parte. Stima per i 620 bandi
  da rielaborare: circa 28 $.

#### 3.3.7 Niente lotti: il tempo sì, il numero no

**Regola permanente del committente (01/10/2026).** Correzioni, aggiornamenti e controlli valgono per **tutti** i bandi
interessati, il prima possibile, anche quelli arretrati. **Nessun tetto sul numero di bandi** per giro o per lancio:
niente «60 ricontrolli», «10 fusioni», «40 letture». Con il giro 3 spariscono tutti questi tetti (§3.3.5, variabili
dismesse), e le letture di massa si fanno per intero, a pagine (`_scorri`), senza troncare a 1.000 o a 5.000 righe.

I soli freni ammessi sono quattro:
1. **cortesia per host**: 1 s fra due richieste allo stesso host (`HOST_THROTTLE_DELAY_S`) e mai due richieste insieme
   allo stesso host, anche con i passi che lavorano in parallelo;
2. **tempo** di ogni passo (`TEMPO_*_S`, `VERIFICA_STATO_TETTO_S`), con **rotazione**: chi resta fuori parte per primo
   al giro dopo, in ordine di ultimo controllo (mai controllato = primo);
3. **spesa**: i dollari e i crediti di §3.3.6;
4. **guardie contro gli errori**: il freno per host della verifica, la prudenza dei gemelli, la doppia lettura a 60 ore,
   i gate degli eventi.

**La copertura.** Ogni passo scrive nella sua riga e nella riga del giro la chiave `copertura`:
`{"candidati": N, "fatti": N, "rimasti": N, "motivo_rimasti": …}`, con `rimasti = candidati - fatti` e il motivo fra
`tempo`, `spesa`, `crediti`, `lock`, `errore` (o vuoto). `salute` mostra la copertura dell'ultimo giro per passo e alza
l'allarme `copertura_incompleta:<passo>` se lo stesso passo lascia fuori qualcuno per **4 giri di fila**: è il segnale
che il tempo di quel passo non basta.

**La catena d'ingresso non ha mai avuto un tetto.** Preprocess, enrich e SEO vengono chiamati dal giro senza parametri.
Il preprocess prende *tutti* i bandi `scraped` (`batch_size=None` vuol dire nessun limite, e la lettura scorre a pagine
oltre le 1.000 righe), l'enrich tutti i `processed` adatti, la SEO tutti gli `enriched`. Se una fonte porta migliaia di
bandi nuovi in una volta, il giro li lavora tutti, chiama il modello su ognuno e può durare ore. Fino al deploy del giro
3 il lucchetto del giro scade dopo 4 ore (`LOCK_TTL_S`; poi 6): oltre quel limite un comando manuale potrebbe prendere
il lucchetto mentre il giro lavora ancora. I giri automatici dello stesso processo invece restano in fila. Per questo il
rischio Incentivi (§8.1, A5) non riguarda solo i costi ma anche la durata del giro.

Fonti di §3.3: `backend/app/bandi_pipeline.py` (righe 101-104 `LOCK_TTL_S`, 322-327 e 395 chiamate senza parametri,
452-505 `completed`/`partial` e `NON PARTITO`, 741-775 `_registra`), `backend/app/lock_orfani.py:1-46`,
`scraper_bandi/app/blocco.py:35`, `scraper_bandi/app/fonte_ufficiale.py:1808-1809, 1983`,
`scraper_bandi/app/monitoraggio.py:53, 2362, 4143`, `scraper_bandi/app/bando_seo_runner.py:831-833, 1223`,
`scraper_bandi/app/__main__.py:1212-1225, 1333-1343`, `scraper_bandi/app/rigenera.py` (nessun lucchetto),
`scraper_bandi/app/telemetria.py:36-39, 104-135`, `scraper_bandi/app/bilancio.py`, `scraper_bandi/app/settings.py:213-219, 400-406`,
`scraper_bandi/app/bando_preprocess_runner.py:1-13, 71-80`, `scraper_bandi/app/db.py:173-189` e `consumo_oggi`,
`scraper_bandi/deploy/`, `docs/bandi-monitor/RIPRESA.md:87, 98`, tabelle `pipeline_run` e `pipeline_lock`.

---

> **Nota.** I paragrafi da 3.4 a 3.19 descrivono i passi come girano in produzione l'01/10 (prima del deploy del giro
> 3), con la vecchia numerazione. Dal deploy valgono anche i cambi di §3.2-bis, che hanno la precedenza dove i due
> testi non coincidono.

### 3.4 Passo 1: discover

**Cosa fa.** Scarica la pagina di OpenCoesione che elenca i programmi europei italiani (regionali, nazionali,
cooperazione territoriale). Ne estrae i link «Opportunità» e «Preavviso», controlla che ciascuno risponda e aggiorna la
tabella `fonte` (dettaglio in §2.3).

**Perché esiste.** Le fonti dei bandi cambiano: nascono programmi nuovi e le pagine si spostano. Il discover tiene
aggiornato l'elenco «di chi ascoltare» senza intervento a mano.

**Cosa legge:**

- la pagina di OpenCoesione (indirizzo nella variabile `OPENCOESIONE_URL`);
- l'elenco dei link già presenti in `fonte`.

**Cosa scrive.** In `fonte` registra per ogni link categoria e tipologia del programma, tipo (Opportunità o Preavviso)
e formato, più due valori decisi dal controllo di raggiungibilità:

- `stato_processing` vale «ready» se il link risponde, «connection error» se non risponde;
- `attivo` vale vero o falso di conseguenza.

Una fonte che non compare più su OpenCoesione diventa «deprecated» (non più seguita). Le fonti inserite a mano
(`discoverable=false`) sono escluse da questa regola, perché su OpenCoesione non ci sono per natura. Oggi sono tre:
ObiettivoEuropa, Italia Domani e Incentivi.gov.it.

**Cosa decide.** Solo «questa fonte va seguita o no». Una fonte che oggi non risponde viene messa da parte **per
questo giro**: lo scrape legge solo le fonti «ready» e attive. Al giro dopo il discover la ricontrolla.

**Se fallisce.** Se OpenCoesione non risponde, il passo va in errore e il giro prosegue: lo scrape usa le fonti già
presenti in tabella. Se la pagina cambia struttura e non si estrae nessun link, il passo restituisce zero e **non**
segna niente come deprecato.

**Costo.** Zero: scarica le pagine direttamente (httpx), senza modelli né Firecrawl.

**Ombra e attivo.** Non esistono: scrive sempre.

**Oggi (giro di avvio):** 114 link trovati, 0 nuovi, 14 non raggiungibili, 0 deprecati. Nella tabella `fonte` ci sono
121 righe: 103 pronte e attive, 14 «connection error», 4 deprecate.

Fonti: `scraper_bandi/app/orchestrator.py`, `scraper_bandi/app/discover.py`, `scraper_bandi/app/reachability.py`,
`scraper_bandi/app/db.py` (`mark_deprecated`), tabella `fonte`.

### 3.5 Passo 2: scrape

**Cosa fa.** Per ogni fonte pronta, legge l'elenco dei bandi pubblicati su quella fonte e li registra nella tabella
`bando` (dettaglio in §2.5-§2.9). Ogni fonte ha la sua **strategia di lettura**, scritta in un file di configurazione:

- pagina web semplice;
- pagina web a più pagine;
- Firecrawl (normale o «extract»);
- misto (nei fatti sempre una lettura semplice, §2.5);
- file CSV o PDF;
- API a pagine, con o senza login (ObiettivoEuropa usa quella con login);
- «niente da leggere».

**Perché esiste.** È la porta d'ingresso: nessun bando entra nel sistema se non passa da qui.

**Cosa legge:**

- le fonti «ready» e attive;
- le righe già in tabella, per confrontare l'elenco appena letto con quello del giro precedente.

**Cosa scrive:**

- **in `bando`**: solo i campi grezzi (fonte, link, titolo, descrizione, dati grezzi in `raw_data`, tipo di link). Ogni
  bando ha un'impronta (`hash_bando`), calcolata dal link oppure, se il link manca, dal titolo e dalla posizione nel
  file. Se l'impronta è nuova nasce una riga nuova, in stato **«scraped»** («appena raccolto, da esaminare»). Se
  l'impronta esiste già, la riga si aggiorna solo se il contenuto è cambiato davvero;
- **gli eventi interni `segnale_fonte`**: «sulla fonte è cambiato qualcosa». Non sono visibili e servono solo ad alzare
  la priorità del monitor;
- **in `bando_controllo`**: l'ultima volta che il bando è stato visto nella fonte e, per ObiettivoEuropa, il **segnale
  dell'aggregatore** («in uscita», «scadenza passata», «assente dall'elenco»);
- **in `fonte_run`**: una riga per ogni fonte letta.

**Cosa decide.** Quasi niente, per scelta. **Lo scrape non scrive mai date né stato.** Una differenza nell'elenco di un
aggregatore non è una prova, è solo un indizio. Per lo stesso motivo una riga che cambia sulla fonte **non torna
indietro** nella catena: l'aggiornamento non tocca `stato_processing`, e i cambiamenti dei pubblicati li gestiscono
monitor e verifica.

**Esempio.** ObiettivoEuropa cambia ogni notte il campo «giorni alla scadenza» di circa 1.400 bandi. Prima ogni giro
riscriveva tutte quelle righe senza motivo. Oggi lo scrape riconosce che non è cambiato niente di significativo e le
salta.

**Se fallisce.** Un errore su una fonte viene contato (`fonti_in_errore`) e si passa alla fonte successiva (ma vedi
§2.12: quasi tutti gli errori diventano «0 elementi» e non si vedono). Se fallisce la rilettura per il confronto, i
segnali vengono saltati ma i bandi si registrano lo stesso.

**Costo:**

- Firecrawl per le fonti che lo usano. Nel file di configurazione ci sono 15 voci «Firecrawl» e 1 «Firecrawl extract»
  su 109 voci (verificato sul file). Questi crediti **non sono contati** in nessun tetto.
- Nessun modello (salvo l'estrazione Firecrawl della fonte 302).

**Ombra e attivo.** Non esistono: scrive sempre.

**Oggi (giro di avvio):**

| Misura | Valore |
|---|---|
| Fonti in elenco (pronte e attive) | 103 |
| Fonti lette davvero | 77 |
| Fonti saltate perché senza voce nel registro | 8 |
| Fonti saltate di proposito («niente da leggere») | 18 |
| Fonti in errore | 0 |
| Bandi letti | 3.758 |
| Bandi identici | 3.682 |
| Bandi cambiati | 44 |
| Bandi nuovi | 3 |
| Segnali | 74 |
| Segnali dell'aggregatore | 59 (tutti «in uscita») |

Fonti: `scraper_bandi/app/bando_runner.py`, `scraper_bandi/app/segnali.py`, `scraper_bandi/app/scraper_config.py`,
`scraper_bandi/app/db.py` (`upsert_bandi`), `scraper_bandi/app/scrapers/`, tabella `pipeline_run` (riga 150).

### 3.6 Passo 3: preprocess

**Cosa fa.** Prende ogni bando «scraped» e risponde a tre domande:

1. **È un bando vero?** Potrebbe essere un'intestazione di tabella, una pagina indice, una gara d'appalto…
2. **In che stato è?** Aperto, chiuso, in apertura prossimamente, oppure non si sa.
3. **Quali date ha?** Pubblicazione, apertura e scadenza, con l'ora quando c'è.

**Perché esiste.** Lo scrape raccoglie molto rumore: su 5.194 righe della tabella, 2.428 sono oggi «rejected». Inoltre
lo stato e le date sono l'informazione più delicata della scheda. Qui si decidono per la prima volta, con regole
severe.

**Cosa legge:**

- tutti i bandi «scraped», senza un tetto per giro (§3.3.7);
- la pagina del bando (`link_bando`), scaricata prima in modo semplice (httpx) e con **Firecrawl solo se serve**;
- i dati della fonte (programma, categoria).

**Come decide, passo per passo:**

1. **Scarto gratuito.** Un bando senza titolo, link e dati, oppure con un titolo di meno di 5 caratteri **e** senza
   link né dati, viene rifiutato senza chiamare il modello.
2. **Il modello legge.** Haiku 4.5 riceve fino a 8.000 caratteri della pagina: i primi 1.500 interi (titolo ed
   etichetta di stato) e poi le sezioni con date e parole utili. Deve rispondere in un formato fisso, dando per ogni
   data anche la **citazione letterale** da cui l'ha presa.
3. **Le date si controllano, non si credono.** Una data passa solo se supera tutti questi controlli:
   - la fonte è la pagina ufficiale o un PDF ufficiale, non una «deduzione»;
   - la citazione compare davvero nel testo della pagina;
   - la data è dentro la citazione, con un ruolo compatibile (una scadenza non può essere una data di legge come «ai
     sensi del DPR del…»);
   - la data non è **presunta** (controllo G10).

   «L'apertura è prevista per il 15/11» è una data presunta e viene scartata. «Scadenza prevista dal bando: 30/10/2026»
   è una data certa e viene accettata.

   Se le tre date non sono in ordine (pubblicazione ≤ apertura ≤ scadenza), vengono annullate tutte e tre.
4. **Le date correggono lo stato.** Una scadenza passata forza «chiuso». Un'apertura futura forza «in apertura». Senza
   date resta lo stato dato dal modello. Il prompt dice al modello che, senza indizi precisi e con tipo «Opportunità»,
   «aperto» è il valore ragionevole: da qui nascono molti «aperti senza scadenza».
5. **Recuperi senza modello**, solo se manca la scadenza e il bando è valido:
   - il **lettore per ente** (un programma scritto apposta per leggere il sito di un certo ente), che può anche dire
     «chiuso»;
   - la **finestra di presentazione** nel testo («dal X al Y»);
   - per ObiettivoEuropa con status «1», l'**etichetta «Scadenza»** della scheda, solo se è citata nella pagina.
6. **Regola dello status ObiettivoEuropa «2»** (nel codice dei segnali vale «in uscita»): lo stato diventa «in apertura
   prossimamente», a meno che date o lettore dicano «chiuso».

**Il ripiego.** Se la pagina del bando manca o è troppo corta (meno di 200 caratteri), si legge la pagina **della
fonte**, cioè l'elenco, con Sonnet 4.6 e le stesse regole sulle date.

Non va confuso con il «resolver della fonte ufficiale» del passo 5: è un'altra cosa che, per un incidente di nomi, si
chiama `bando_resolver.py` e usa la variabile `RESOLVER_MODEL`.

**Cosa scrive in `bando`:**

- bando valido: diventa **«processed»**, con stato, le tre date (vuote se non hanno passato i controlli), le ore e un
  punteggio di fiducia;
- bando non valido: diventa **«rejected»**, con il motivo.

**Le conseguenze delle due scelte:**

- **«rejected» è definitivo.** Nessun passo lo riesamina.
- **«processed» e chiuso si ferma qui per sempre.** Non viene arricchito né pubblicato. Oggi sono 569 righe, tutte
  chiuse (570 dopo il giro delle 12: la coda cresce).

**Se fallisce:**

- un errore temporaneo (rete, server occupato, limite di richieste): fino a 3 tentativi in tutto;
- un errore definitivo dell'API, per esempio il credito esaurito: il bando resta «scraped» e si riprova al giro dopo.
  È successo il 28-29/09: 24-25 errori per giro per quattro giri e nessuna scrittura;
- nel ripiego, un errore temporaneo significa «rimando», e il bando resta «scraped».

**Costo.** Stimato, non misurato:

| Lavoro | Costo indicativo |
|---|---|
| Preprocess con Haiku | circa 1 centesimo di dollaro a bando |
| Ripiego con Sonnet | 3-5 centesimi a bando |
| Firecrawl | solo come ripiego dello scarico |

**Nessuno di questi costi è contato** nel diario o nei tetti.

**Ombra e attivo.** Non esistono: scrive sempre.

**Oggi (giro di avvio):** 3 bandi, tutti validi e aperti, con apertura e scadenza. Nessun ripiego. (Al giro delle 12:
1 bando, giudicato «chiuso».)

Fonti: `scraper_bandi/app/bando_preprocess_runner.py`, `scraper_bandi/app/preprocessor.py` (righe 34-35, 247, 436,
446-478, 584-589, 655-727, 847), `scraper_bandi/app/date_validation.py`, `scraper_bandi/app/bando_resolver.py`,
`scraper_bandi/app/settings.py`.

### 3.7 Passo 4: enrich

**Cosa fa.** Classifica i bandi validi e non chiusi secondo i cataloghi del sito:

| Scelta | Catalogo | Voci nel catalogo |
|---|---|---|
| un solo valore | tipologia | 5 |
| un solo valore | modalità di erogazione | 4 |
| un solo valore | programma | 56 |
| più valori | beneficiari | 31 |
| più valori | codici ATECO | 89 |
| più valori | regioni | 20 |
| più valori | settori | 90 |

**Perché esiste.** Sono le dimensioni con cui il sito filtra i bandi e con cui BandoFit li abbina alle imprese. Senza
l'enrich un bando non si trova per regione o per settore.

**Cosa legge:**

- i bandi «processed» con stato aperto, in apertura o vuoto (i chiusi non vengono letti), senza tetto per giro;
- i primi 2.500 caratteri della pagina del bando;
- i cataloghi interi.

**Cosa decide, in due fasi:**

- **Fase A: solo per i bandi senza stato.** Haiku sceglie fra aperto, chiuso e in apertura. Lo stato si scrive solo con
  fiducia almeno 0,6, altrimenti si riprova al giro dopo. Qui le date non vengono controllate.
- **Fase B: la classificazione.** Partono 7 chiamate Haiku in parallelo, una per catalogo. Il codice scarta qualsiasi
  valore che non sia nel catalogo: **nessuna voce nuova entra mai nei cataloghi**.
- **Rete di sicurezza finale.** Prima di scrivere, lo stato si ricalcola con le date: se nel frattempo la scadenza è
  passata, il bando diventa «chiuso».

**Cosa scrive.** Le quattro tabelle di collegamento (regioni, settori, beneficiari, ATECO) e, in `bando`, tipologia,
modalità, programma, stato e **«enriched»**. «Enriched» vuol dire classificato ma ancora invisibile al pubblico.

**Se fallisce:**

- se una delle 7 chiamate fallisce, quel campo resta vuoto e il bando va avanti lo stesso. Oggi, fra i pubblicati, 11
  non hanno regioni, 11 non hanno beneficiari, 5 non hanno settori e 510 non hanno codici ATECO;
- se fallisce la scrittura, il bando resta «processed» e il giro dopo rifà tutto. Non c'è una transazione unica.

**Costo.** Circa 1,5-2 centesimi a bando (stima). **Non contato.**

**Ombra e attivo.** Non esistono.

**Oggi (giro di avvio):** 3 bandi classificati, nessuna rifinitura dello stato.

Fonti: `scraper_bandi/app/bando_enrich_runner.py`, `scraper_bandi/app/enricher.py`, `scraper_bandi/app/db.py`
(`select_bandi_to_enrich`, `update_bando_enriched`), tabelle dei cataloghi e di collegamento.

### 3.8 Passo 4-bis: domini (import di IndicePA), solo alle 06

**Cosa fa.** Una volta al mese scarica da IndicePA (l'indice ufficiale delle pubbliche amministrazioni) il file
`enti.xlsx`, circa 23.750 righe. Ne ricava i siti istituzionali e li aggiunge alla **lista dei domini riconosciuti**
come «ente».

**Perché esiste.** Il resolver (passo 5) accetta come fonte ufficiale solo pagine su domini **riconosciuti**. Oggi la
tabella `dominio_ufficiale` ha appena 109 righe, e 25 di queste sono aggregatori (la lista nera sta nella stessa
tabella): i domini riconosciuti sono 84. Molti siti di comuni, ASL e agenzie risultano quindi «sconosciuti». Una prova
senza scritture fatta l'01/10 dice che l'import aggiungerebbe circa **22.355 host** (22.370 ammessi, 15 già presenti; la
misura del 30/09 diceva 22.353). Secondo la misura del 30/09, 51 domini già presenti nei nostri link diventerebbero
«verificanti»: **non verificato**.

**Cosa legge:**

- il file di IndicePA;
- la tabella `dominio_ufficiale`;
- le righe «domini» del diario, per sapere se nel mese l'import è già stato fatto.

**Cosa decide.** Tiene un host solo se ha un sito valido e non è:

- una piattaforma condivisa (altervista, wordpress…);
- un host associato a 3 o più enti;
- nella lista nera.

Oggi gli esclusi sono 842 senza sito, 354 host condivisi, 15 piattaforme condivise e 17 host non validi.

**Inserisce solo host nuovi: non modifica e non cancella mai niente.** Con meno di 15.000 righe utili, o con una
colonna mancante, considera il file «anomalo» e non scrive nulla.

**Quando gira.** Alle 06, solo se nel mese di calendario non c'è già un import «fatto». In ombra conta come fatto
anche un import in ombra. In attivo conta solo un import riuscito: per questo, dopo l'attivazione, al primo giro delle
06 l'import parte di nuovo e questa volta scrive.

**Se fallisce.** Se non riesce a leggere il diario, salta l'import. Se lo scaricamento fallisce o il file è anomalo,
non scrive e riprova il giorno dopo alle 06.

**Costo.** Zero (un solo scaricamento, circa 4 MB).

**Ombra e attivo.** **Segue `VERIFICA_STATO_MODALITA`**, non la modalità del resolver.

- In ombra, come oggi: scarica, conta e non scrive (scrive solo la sua riga nel diario).
- In attivo: scrive circa 22.355 righe.

**Attenzione.** Dopo il primo import vero, i bandi già giudicati «non trovata» non vengono rivalutati subito: la loro
data di ricontrollo è il 23/11 (510 righe). Per rivalutarli prima serve un comando lanciato a mano (§9.5).

**Oggi.** Non ha mai girato. La prima esecuzione, in ombra, è attesa alle 06 del 02/10.

Fonti: `backend/app/bandi_pipeline.py` (righe 330-341, 510-567), `scraper_bandi/app/fonte_ufficiale.py` (righe
3050-3058, 3150-3300), `scraper_bandi/app/dominio_ufficiale.py` (righe 680-750), prova `domini --import --scarica-enti
--dry-run` del 01/10, tabella `dominio_ufficiale`.

### 3.9 Passo 5: resolver della fonte ufficiale («nuovi»)

**Cosa fa.** Per ogni bando appena arrivato a «enriched», cerca la **pagina dell'ente che ha emesso il bando**.

**Perché esiste.** Circa l'81% dei bandi pubblicati (1.768 su 2.191) arriva da ObiettivoEuropa, un aggregatore. Il
pulsante «Apri la pagina ufficiale del bando» deve portare all'ente, non a un intermediario. Se la pagina ufficiale non
si trova, il sito lo dichiara invece di mostrare un link qualunque. Il resolver gira **prima della SEO** apposta: così
la scheda viene scritta leggendo la pagina ufficiale e non quella dell'aggregatore.

**Regole fisse:**

- nessun indirizzo viene inventato da un modello;
- il resolver non tocca mai stato, date, slug o testo del bando;
- un aggregatore non è mai una fonte ufficiale. Lo impone anche un trigger del database (migrazione 03).

**Cosa legge.** I candidati vengono da:

- i link presenti nei dati grezzi e nel testo;
- la scheda di ObiettivoEuropa (sezione «Link e Documenti»);
- i link già registrati in `bando_link`;
- un eventuale gemello già risolto.

**Come decide.** Ogni candidato viene scaricato e passa prima quattro **controlli duri**. Se ne fallisce uno, è
scartato:

1. il dominio non è un aggregatore;
2. il dominio è riconosciuto (non «sconosciuto»);
3. la pagina risponde e ha almeno 500 caratteri di testo;
4. non è una pagina «non trovato».

Ci sono poi quattro **controlli morbidi** (pagina indice, dominio solo «dedotto», calendario, ricerca non vincolata): non
scartano, ma impediscono di andare oltre «in_verifica».

Poi il candidato riceve un **punteggio da 0 a 100**: dominio dell'ente 30 (riconosciuto per forma 25, portale 20),
titolo molto simile 25 (simile 12), stessa scadenza 15 (scadenza diversa −15), nome dell'ente nella pagina 10, link
arrivato da una fonte strutturata 10, PDF dell'atto sul dominio 10, importo 5, numero dell'atto 5.

| Esito | Condizione |
|---|---|
| **«trovata»** | almeno 70 punti **e** tre segnali indipendenti: dominio, titolo, contenuto |
| **«in_verifica»** | almeno 40 punti |
| **«non_trovata»** | sotto i 40 punti, oppure nessun candidato supera i controlli duri |

**Esempio.** Un portale regionale riconosciuto per forma (25), titolo molto simile (25), stessa scadenza (15) e link
strutturato (10) fanno 75 punti con tre segnali: «trovata».

**Cosa scrive.** Dipende dalla modalità:

- **in attivo, come in produzione dal 25/09:**
  - la riga della pagina scelta in `bando_link`, più gli allegati verificati;
  - le colonne `fonte_ufficiale_*` del bando;
  - un evento «fonte ufficiale verificata», visibile, oppure «non trovata», interno;
  - le date di ricontrollo in `bando_controllo`: «in_verifica» fra 14 giorni per i primi tre tentativi, poi ogni 60;
    «non_trovata» fra 60 giorni; «trovata» oggi stesso, così il bando passa al monitor;
- **in ombra:** solo `bando_controllo` ed eventi interni.

**Se fallisce:**

- lucchetto occupato: il passo viene saltato;
- c'erano candidati ma nessuno ha risposto: l'esito è «in_verifica», non «non_trovata»;
- dominio irraggiungibile o più di 120 secondi per un bando: «rinviato», senza giudizio (nei ricontrolli il bando
  slitta a domani);
- tetto raggiunto: il passo si ferma, il giro continua.

**Costo.** In teoria il resolver ha una ricerca a pagamento, una sonda e un «arbitro» con modello. **Nel codice di
produzione nessuno dei tre è collegato**, quindi oggi spende 0 crediti e 0 $ (confermato da tutte le righe del diario).

**Attenzione:**

- La lista dei domini riconosciuti è un controllo duro: un dominio fuori lista non può mai diventare «trovata».
  Secondo uno studio precedente, 353 pubblicati hanno un link funzionante solo su domini non in lista, per esempio
  fondazioni bancarie e finanziarie regionali (**non verificato** oggi).
- Il ricontrollo ripete quasi sempre lo stesso lavoro: l'esito cambia solo se cambiano la lista o le pagine.

**Oggi (giro di avvio):** 3 esaminati, 2 trovate, 1 in verifica.

**Sui pubblicati:** 620 trovate, 1.050 in verifica, 521 non trovate.

Fonti: `scraper_bandi/app/fonte_ufficiale.py` (righe 77-139, 660-830, 840-878, 1478-1495, 1808-1809, 2300-2332),
`scraper_bandi/app/dominio_ufficiale.py`, `scraper_bandi/app/db.py`, `backend/sql/bando_v11_03_fonte_ufficiale.sql`,
tabelle `bando` e `pipeline_run`.

### 3.10 Passo 5-bis: ricontrolli, alle 06 e alle 18

**Cosa fa.** È **lo stesso resolver**, in modo «ricontrolli». Riprende fino a **60 bandi per giro** fra quelli
«in_verifica» o «non_trovata» la cui data di ricontrollo è arrivata.

**Perché esiste.** Senza questo passo, una fonte non trovata oggi non verrebbe trovata mai più, nemmeno dopo l'arrivo
di nuovi domini nella lista. Gira solo nei giri di `MONITOR_GIRI` e con un tetto proprio, perché è manutenzione: non
deve togliere tempo ai bandi nuovi.

**Legge, scrive, decide, costo, ombra e attivo:** come il passo 5.

**Se fallisce:** come il passo 5. Un bando rinviato si riprova il giorno dopo.

**Oggi.** Alle 06: 0 esaminati, 1.570 saltati perché non ancora dovuti.

**I picchi in arrivo** (date di ricontrollo dei pubblicati in `bando_controllo`):

- l'**08/10** scadono insieme 690 bandi «in_verifica»;
- il **23/11** ne scadono 847 (337 «in_verifica» e 510 «non_trovata»).

A 60 per giro e due giri al giorno, il primo picco richiede circa 6 giorni e il secondo circa 7-8.

**Attenzione.** Nel diario i ricontrolli scrivono una riga con step «resolver», uguale nell'intestazione a quella dei
«nuovi» e senza il campo `modo`. Nei giri delle 06 e delle 18 le due righe si distinguono solo per l'ordine (prima i
nuovi, poi i ricontrolli) e per i contatori.

Fonti: `backend/app/bandi_pipeline.py` (righe 118-124, 355-379), `scraper_bandi/app/fonte_ufficiale.py`, tabelle
`bando_controllo` e `pipeline_run` (righe 144-145).

### 3.11 Passo 5-ter: verifica dello stato, fase «ingresso», a ogni giro

**Cosa fa.** Prima che la SEO pubblichi, guarda i bandi nuovi («enriched», non ancora pubblicati) che risultano
**aperti ma senza scadenza**, o con status ObiettivoEuropa «2». Prova a trovare sulla pagina ufficiale una scadenza o un
«chiuso».

**Perché esiste.** Il prompt del preprocess, quando mancano indizi, suggerisce «aperto». Così nascono gli «aperti senza
prova»: oggi i pubblicati aperti senza scadenza sono 426. Questo passo prova a fermarli **prima** che vengano
pubblicati.

**Cosa legge.** La pagina ufficiale o la pagina del bando sullo stesso dominio della fonte, solo con i **lettori per
ente**. Gli aggregatori non si leggono mai, e Firecrawl non si usa.

**Cosa scrive:**

- **in attivo:** la scadenza o il «chiuso» direttamente sul bando. La scrittura è rifiutata se il bando è già
  pubblicato;
- **in ombra:** solo la storia delle letture in `bando_controllo`.

**Cosa decide.** Solo con lettori strutturati: questo passo **non usa mai il modello**. Il suo risultato serve alla
«sosta all'ingresso» applicata dalla SEO (§3.12): un bando a cui trova una scadenza, o un «aperto» confermato da un
lettore per ente, non deve sostare.

**Tetti.** 30 letture e 300 secondi per giro.

**Se fallisce.** È protetto come gli altri passi: il giro prosegue e la SEO pubblica come avrebbe fatto senza.

**Costo.** Zero modello. Solo lo scaricamento delle pagine.

**Ombra e attivo.** Segue `VERIFICA_STATO_MODALITA`. Oggi è in ombra.

**Oggi (giro di avvio e giro delle 12):** 0 candidati.

Fonti: `scraper_bandi/app/verifica_stato.py` (righe 1-30), `scraper_bandi/app/db.py` (`select_enriched_da_leggere`),
`scraper_bandi/app/ingresso.py`, `backend/app/bandi_pipeline.py:381-387`, tabella `pipeline_run` (righe 149-152).

### 3.12 Passo 6: SEO, cioè la pubblicazione

**Cosa fa.** È **l'unico passo che pubblica**. Prende tutti i bandi «enriched», senza tetto per giro. Applica tre
filtri, fa scrivere la scheda da Opus e la salva come **«completed»** con uno slug, cioè l'indirizzo della pagina. A
quel punto è il **database** a pubblicarla.

**Perché esiste.** La scheda pubblica deve essere leggibile, corretta e senza invenzioni. Il passo concentra in un solo
punto i controlli che proteggono il pubblico.

**I tre filtri, in quest'ordine, prima di pagare il modello:**

1. **Doppioni degli aggregatori (sempre attivo, nessuna ombra).** Un bando delle tre fonti aggregatore (in pratica
   ObiettivoEuropa: le altre due oggi non hanno righe) che ha la stessa fonte ufficiale di un pubblicato di un'altra
   fonte, oppure lo stesso ente, importo e scadenza, viene **rifiutato**: diventa «rejected» con motivo «doppione
   probabile di …». Il rifiuto è permanente finché qualcuno non lo annulla a mano. Oggi: 0 casi.
2. **Sosta all'ingresso (segue `VERIFICA_STATO_MODALITA`).** In attivo, un bando «aperto» senza scadenza, senza
   conferma di un lettore per ente e senza un termine futuro **aspetta fino a 4 giri (24 ore)**, il tempo che il passo
   5-ter gli trovi una data. Poi si pubblica comunque. Sempre in attivo, un bando **«senza appiglio»** (nessun link e
   nessuna data) resta fermo per sempre. **In ombra, come oggi, non trattiene niente: conta soltanto.**
3. **Gemello esatto (segue `VERIFICA_STATO_MODALITA`).** Se il bando nuovo ha un solo gemello esatto fra i pubblicati
   (stesso link, o stessa riga di calendario) e supera i controlli di prudenza del passo 9, in attivo viene **fuso**
   sul pubblicato e messo in «rejected», invece di essere pubblicato due volte. In ombra conta soltanto.

**La scrittura della scheda:**

- **Testo di partenza**, in quest'ordine di preferenza: la fonte ufficiale, solo se «trovata»; poi il link del bando se
  non è un aggregatore; altrimenti il testo dell'aggregatore, marcato come «ripiego, non citare, non linkare».
- **Opus 4.7** scrive titolo (al massimo 80 caratteri), descrizione (180-320), contenuto a sezioni, livello («flash» o
  «guida»), ente, importi, link di candidatura e slug. Lavora su 3 bandi in parallelo.
- **Regole del prompt:** le date sono solo quelle già controllate; lo stato non si scrive mai nel testo, perché lo
  mostra il badge; si usano gli accenti veri; le condizioni di partecipazione si scrivono solo se la fonte le dice.
- **Controlli automatici dopo il modello:**
  - un titolo troppo lungo si ripara (con il titolo breve, oppure con una seconda richiesta al modello);
  - una descrizione troppo lunga si accorcia; se resta fuori dai 180-320 caratteri la scheda è scartata;
  - **ogni link nel testo che non è tra quelli verificati diventa testo semplice.**

**Come nasce lo slug.** Lo propone Opus insieme al testo. Il prompt chiede minuscole con trattini, al massimo 80
caratteri e senza parole vuote come «di», «il», «per». Il codice lo accetta solo se contiene esclusivamente `a-z`,
`0-9` e `-`. Altrimenti lo ricalcola dal titolo con una funzione propria (`slugify` di `seo_skill.py`, diversa da
`src/lib/slug.ts`). Se lo slug è già usato da un altro bando, prova `-2`, `-3`… fino a 5 tentativi. Se fallisce anche
così, la scheda viene scartata e il bando ritenta al giro dopo. Una volta pubblicato, lo slug è congelato (§4.4).

**Il momento della pubblicazione.** Quando la riga diventa «completed», ha uno slug e uno stato, non è fusa e non è
ritirata, un trigger del database (una regola che scatta da sola a ogni scrittura) mette `pubblicato=true`. Da quel
momento il bando compare nella vista pubblica `bando_pubblico`, l'unica che il sito e BandoFit leggono.

Un pubblicato **non può più tornare indietro**. Lo slug è congelato. Si esce dalla vista solo per fusione (lo slug
vecchio risponde 301 verso quello che resta) o per ritiro (410).

**Se fallisce.** Se la scheda non supera i controlli, il bando resta «enriched» e viene **ritentato al giro dopo,
ripagando Opus**. Non c'è un numero massimo di tentativi: la colonna `tentativi_seo` esiste ma nessun codice la usa
(vale 0 su tutti i pubblicati). Esempio reale: dal giro delle 00 del 26/09 al giro di avvio del 30/09 alle 18:47 un
bando è stato ritentato a ogni giro (circa 20 volte) prima di essere pubblicato.

**Costo.** Opus è la chiamata più cara del giro, fino a due chiamate per bando, più Firecrawl (solo se serve) per
scaricare il testo. **Nessuno dei due è contato** nel diario o nei tetti: la pipeline non passa i contatori alla SEO.

**Ombra e attivo:**

- la pubblicazione e il filtro dei doppioni degli aggregatori non hanno ombra;
- sosta e gemello esatto seguono `VERIFICA_STATO_MODALITA` (oggi ombra).

**Attenzione.** Le pubblicazioni nuove **non vengono segnalate a IndexNow**: i motori di ricerca le scoprono solo dalle
sitemap.

**Oggi (giro di avvio):** 3 selezionati, 3 pubblicati, 0 doppioni, 0 gemelli, 0 trattenuti.

**Nel database:** 2.191 pubblicati (2.197 completati meno i 6 fusi), 6 fusi il 30/09 tutti nello stesso istante
(dedotto: a mano, via SQL), 0 «enriched» in attesa.

Fonti: `scraper_bandi/app/bando_seo_runner.py` (righe 72-89, 246-326, 394-588, 608-680), `scraper_bandi/app/seo_skill.py`
(righe 200, 264-306, 610-612, 700-766, 1017-1090), `scraper_bandi/app/ingresso.py`, `scraper_bandi/app/gemelli.py`
(righe 1009-1083), `backend/sql/bando_v11_01_pubblicazione.sql` (righe 374-402), `backend/sql/bando_v11_05_vista_pubblica.sql`,
tabelle `bando` e `pipeline_run`.

### 3.13 Passo 7: monitor, alle 06 e alle 18

**Cosa fa.** Ricontrolla le **pagine ufficiali dei bandi pubblicati** che hanno una fonte «trovata». Cerca cambiamenti
come proroghe, FAQ, allegati nuovi, graduatorie, esiti e chiusure.

**Perché esiste.** Un bando pubblicato cambia nel tempo. Il sito deve accorgersene **dalla fonte ufficiale**, non
dall'aggregatore e non da un'ipotesi.

**Cosa legge:**

- la coda dei bandi da controllare. Ogni bando ha una cadenza secondo la sua «fase» (scenario bilanciato): aperto con
  scadenza entro 7 giorni ogni giorno, fra 8 e 30 giorni ogni 3, oltre 30 giorni ogni 7; a sportello ogni 3; dopo la
  chiusura a 3, 10 e 30 giorni e poi ogni 30, fino a 12 mesi; i revocati mai. Alle date si aggiunge un margine casuale
  del ±25%. I segnali dello scrape ne alzano la priorità;
- le pagine ufficiali;
- le impronte salvate al controllo precedente.

**Come decide, dal passo più economico al più caro.** Si ferma appena può:

1. **la fonte dichiara di non essere cambiata** (segnale del sito, per esempio la data di ultima modifica): stop, costo
   zero;
2. **controllo degli allegati già pubblicati**: una richiesta leggera per ogni documento; un allegato che risponde 404
   viene tolto da quelli pubblicabili;
3. **richiesta condizionale della pagina**: se il server risponde 304 («non cambiata»), stop;
4. **confronto con l'impronta**: se la differenza è solo rumore (menu, cookie, contatori), stop;
5. **solo se la differenza conta**: Haiku 4.5 propone gli eventi, e Sonnet 4.6 dà una seconda opinione;
6. **i controlli G1-G9 decidono**. Tra i principali: la citazione deve stare nella pagina e nella parte aggiunta; la
   data deve avere il ruolo giusto; la prova deve venire da un dominio ufficiale; serve una seconda prova per ogni
   cambio di stato o di data; il passaggio deve essere fra quelli ammessi. **Il modello propone, i controlli
   decidono.**

**Cosa scrive:**

- **in ombra (oggi):** gli eventi ammessi si salvano non applicati e non visibili. Servono a misurare la precisione: per
  uscire dall'ombra servono il 95% di eventi giusti su almeno 100;
- **l'eccezione `MONITOR_TIPI_ATTIVI`:** anche in ombra, un evento di tipo faq, nuovo allegato, graduatoria, esito o
  proroga, nato in questo controllo e ammesso dai controlli, **viene applicato e reso visibile** nel box
  «Aggiornamenti». Una proroga applicata così riscrive anche la prosa e manda lo slug a IndexNow. Gli eventi raccolti
  in ombra nei controlli precedenti restano fermi, per scelta. Nel giro delle 06 di oggi nessun evento è stato
  applicato con questa regola;
- **in attivo:** tutti gli eventi ammessi si applicano. Se cambia una data, il testo della scheda si riallinea e lo slug
  va a IndexNow.

**Se fallisce:**

- lucchetto occupato: il passo viene saltato;
- il modello non risponde: non si salva nulla e la pagina si rivede al giro dopo;
- dominio irraggiungibile (errore DNS): si salta fino al giorno dopo, senza contare un errore;
- dopo 5 errori di fila il bando esce dalla coda (ricontrollo spostato lontano). Solo con `MONITOR_MODALITA=attivo` la
  fonte torna anche «in_verifica», cioè al resolver; in ombra, come oggi, no;
- tetto raggiunto: il passo si ferma e il giro continua.

**Costo.** Haiku più Sonnet. È **contato e limitato**: 420 pagine per giro, 30 classificazioni e 1,5 $ al giorno (più
ricerche e crediti). La spesa reale va da 0 a 0,46 $ al giorno.

**Ombra e attivo.** `MONITOR_MODALITA` vale ombra; i 5 tipi attivi fanno eccezione.

**Oggi alle 06** (codice precedente al deploy): 80 bandi controllati, tutti solo «riallineati». Le loro impronte erano
state salvate con la pulizia vecchia, quindi la base è stata riscritta senza classificare. 0 classificazioni, 0 $.
Restano 539 impronte vecchie da riallineare (538 fra i 620 pubblicati con fonte «trovata»).

Fonti: `scraper_bandi/app/monitoraggio.py` (righe 53-140, 180-188, 1028-1230, 1975-2036, 2505-2520, 3637-3639),
`scraper_bandi/app/eventi.py`, `scraper_bandi/app/bilancio.py`, `scraper_bandi/app/impronte.py` (righe 224, 640-660),
tabelle `pipeline_run` (righe 138 e 146) e `bando_controllo`.

### 3.14 Passo 8: verifica dello stato, fase «controlli», alle 06 e alle 18

**Cosa fa.** Rilegge sulla pagina ufficiale lo stato dei pubblicati **il cui stato non ha prove**:

- gli «in apertura» (166, di cui 163 senza data di apertura);
- gli «aperti senza scadenza» (426).

In tutto 592 candidati, nessuno ancora letto. Gira dopo il monitor e mai al giro di avvio.

**Perché esiste.** Sono le due famiglie in cui il sito può mostrare uno stato sbagliato senza accorgersene. Il passo
alimenta anche il bollino pubblico «da verificare» (`stato_da_verificare`, §4.7).

**Cosa legge:**

- i candidati in ordine di priorità: prima chi ha la data di apertura già passata, poi chi ha un segnale
  dall'aggregatore, poi chi ha un termine indicato già passato, poi chi non è mai stato letto, e così via;
- la pagina migliore disponibile: la fonte ufficiale, poi la pagina del bando sullo stesso dominio, poi il candidato del
  resolver, e così via. Senza una pagina adatta il bando risulta «illeggibile». Gli aggregatori non si leggono mai, e
  Firecrawl non si usa.

**Come decide:**

- prima i **lettori per ente**, poi un lettore generico che sa dire solo «chiuso», come semplice segnale;
- il modello (Haiku) solo se nessun lettore trova niente. Il modello legge lo stato ma non propone mai eventi;
- un evento (apertura, chiusura, correzione della scadenza, data confermata) nasce solo da un **lettore strutturato** e
  deve superare i suoi controlli, fra cui **due letture uguali dello stesso lettore a distanza di almeno 60 ore**;
- per le chiusure ci sono due freni: al massimo 20 per giro, e uno stop se lo stesso lettore sullo stesso sito «chiude
  troppo» (oltre metà dei passaggi in 7 giorni, con almeno 5 passaggi), perché probabilmente il lettore è rotto.

**Cosa scrive:**

- **in ombra (oggi):** solo `bando_controllo`, cioè la lettura, la storia delle ultime 5 letture, la prossima data di
  lettura e la proposta «trattenuta». **Niente di pubblico.** In ombra l'unico bollino che può comparire è «data di
  apertura passata», che dipende solo dalla colonna della data. Oggi i bollini sono 2;
- **in attivo:** anche le colonne della lettura e la data dell'esame, che accendono i bollini pubblici, più gli eventi
  ammessi.

**Se fallisce.** Una pagina che risponde con un errore HTTP (o un primo 404) si riprova dopo 1, 1 e 3 giorni, poi ogni
14. Un errore di rete si riprova dopo 1 giorno. Tetti: 40 letture e 900 secondi per giro, 120 secondi per bando.

**Costo.** Haiku solo quando serve. Le sue chiamate entrano nel tetto giornaliero in dollari, condiviso con il monitor,
ma non aumentano il contatore delle classificazioni. Prima di ogni chiamata, però, si controllano tutti i tetti
giornalieri: se il monitor ha già esaurito le 30 classificazioni, anche il modello della verifica si ferma (la lettura
resta ai lettori).

**Ombra e attivo.** Segue `VERIFICA_STATO_MODALITA`. Il piano è questo:

- 7 giorni di ombra;
- l'08/10 il controllo con `report-verifica-stato --verita`;
- solo se le difformità sono zero, l'attivazione (§9.4).

**Attenzione:**

- Oggi nessuno dei 592 candidati è stato letto. Quelli con una pagina leggibile sono 496 (96 illeggibili; misura
  dell'indagine, non ricontrollata). A 40 per giro e due giri al giorno servono circa 13 giri, cioè 6-7 giorni: il
  margine per l'08/10 è stretto.
- Il bando 661135 della «verità nota» è già stato chiuso dal job orario alle 00:05 del 01/10 (ora di Roma). Il report
  di oggi lo segna già come difforme (atteso «chiusura», trovato niente): così com'è, il controllo dell'08/10 segnerà
  almeno una difformità. Oggi le difformità sono 44, perché non c'è ancora nessuna lettura.
- All'attivazione molti dei 592 candidati riceveranno il bollino «da verificare».

**Oggi.** Il passo non ha ancora girato: la prima esecuzione è attesa alle 18:00 del 01/10.

Fonti: `scraper_bandi/app/verifica_stato.py` (righe 1-30, 70-140, 484-500, 1000-1080, 1392-1460),
`scraper_bandi/app/eventi.py` (righe 1484-1530, 1756-1790), `scraper_bandi/app/stato_bando.py` (righe 522-576),
`backend/sql/bando_v11_13_stato_da_verificare.sql`, comando `report-verifica-stato --verita --json` (sola lettura) del
01/10, vista `bando_pubblico`.

### 3.15 Passo 9: gemelli, solo alle 06

**Cosa fa.** Cerca fra i pubblicati le **coppie di doppioni certi** e le fonde: una delle due righe resta, l'altra esce
dalla vista e il suo slug risponde 301 verso quella rimasta.

**Perché esiste.** Lo stesso bando può arrivare da due fonti, per esempio da ObiettivoEuropa e dal portale regionale.
Due schede uguali confondono il lettore e BandoFit.

**Cosa legge.** I pubblicati non fusi (oggi 2.191).

**Come decide:**

- **si fonde solo ciò che è certo.** In automatico valgono solo due criteri: **stesso link**, oppure **stessa riga di
  calendario** (stessa fonte, nessun link, stessa descrizione, e stesso file o stessa data di chiusura). Gli altri due
  criteri esatti (chiave esterna, numero dell'atto) restano solo per le fusioni a mano;
- **controlli di prudenza:**
  - per lo stesso link: un link condiviso da 3 o più pubblicati è una pagina «hub» e non conta; i titoli devono
    somigliarsi; le scadenze devono coincidere (o mancare su una delle due);
  - per tutti i criteri: **niente fusione** se i titoli differiscono per anno o per lotto, edizione, sportello e simili;
- solo coppie, mai catene A=B=C;
- la riga che resta si sceglie con un ordine fisso: fonte ufficiale forte, poi fonte che non è un aggregatore, e così
  via;
- **al massimo 10 fusioni per giro** (`GEMELLI_FUSIONI_PER_GIRO`; 0 spegne il passo).

**Cosa scrive:**

- **in attivo:** la fusione tramite la funzione del database `bando_fondi`, che registra lo slug vecchio come 301,
  sposta i link ed emette gli eventi «fusione»;
- **in ombra:** solo elenco e conteggi.

**Se fallisce.** Se la lettura arriva a 5.000 righe (elenco forse troncato), il passo dichiara errore e non fonde niente.

**Costo.** Zero.

**Ombra e attivo.** Segue `VERIFICA_STATO_MODALITA`. La scelta è voluta: la prima fusione automatica deve arrivare
almeno 7 giorni dopo l'avviso a BandoFit. **Dal giro 3** segue un interruttore proprio, `GEMELLI_MODALITA`, e l'avviso
a BandoFit è un solo messaggio, mandato prima del deploy, senza i 7 giorni (§3.2-bis).

**Previsione** (`gemelli --dry-run`, rifatto il 01/10, nessuna scrittura): 52 fusioni (43 per link, 9 di calendario) e
33 coppie scartate per prudenza (20 per anni o lotti diversi, 12 per link condiviso, 1 per titoli diversi). Con 10 al
giorno servono circa 6 mattine.

**Oggi.** Il passo non ha mai girato. La prima esecuzione, in ombra, è attesa alle 06 del 02/10.

Fonti: `scraper_bandi/app/gemelli.py` (righe 421-527, 532-580, 852-866, 1086-1439),
`backend/sql/bando_v11_04_transizioni.sql`, `backend/app/bandi_pipeline.py` (righe 420-426), comando `gemelli
--dry-run` del 01/10.

### 3.16 Dopo i passi: IndexNow e la riga del diario

**IndexNow** è il servizio che avvisa i motori di ricerca che una pagina è cambiata. A lucchetto già rilasciato, il giro
manda **una sola** notifica con gli slug che i passi dichiarano di aver modificato. Oggi può produrli solo il monitor,
per gli eventi dei 5 tipi attivi applicati e visibili (e, dopo l'attivazione, anche la verifica). Le pubblicazioni
nuove della SEO non ci finiscono. Finora `slug_modificati` è sempre vuoto nelle righe del diario.

Il sender legge la variabile `INDEXNOW_API_KEY` (con `os.getenv`, al momento dell'invio, dopo aver caricato
`scraper_bandi/.env` e poi il `.env` della cartella di avvio) e dichiara a IndexNow che la chiave si trova all'indirizzo
`https://edunews24.it/<chiave>.txt`. Quel file lo serve il **sito**, che usa la stessa variabile nella sua
configurazione. Verificato il 01/10: `https://edunews24.it/api/indexnow-key` risponde 404 «IndexNow key not
configured», quindi il sito non ha la chiave e IndexNow non può verificare le notifiche. Se la variabile manca anche
nell'ambiente del sender, il sender salta la notifica con un avviso: la sua presenza è **non verificata**.

**La riga del diario.** Infine il giro scrive la sua riga riassuntiva in `pipeline_run` (§3.3.4).

Fonti: `backend/app/bandi_pipeline.py` (righe 440-444, 675-715), `backend/app/indexnow.py:21-39`,
`scraper_bandi/app/settings.py:403-406`, `src/pages/[key].txt.ts`, `src/pages/api/indexnow-key.ts`,
`scraper_bandi/app/monitoraggio.py` (righe 2505-2516).

### 3.17 Che cosa succede fuori dal giro

Per evitare confusione, ecco le cose che **non** fanno parte dei giri del sender.

| Chi o cosa | Quando | Che cosa fa |
|---|---|---|
| Job orario del database (`bandi-transizioni-orarie`) | Al minuto 5 di ogni ora | Chiude i pubblicati con la scadenza passata (190 chiusure dal 24/09, tutte al minuto 5, con origine «cron»). In teoria apre anche gli «in apertura» con data verificata, ma non l'ha mai fatto (0 eventi). Che giri è verificato con la funzione di sola lettura `monitoraggio_job_orario` (§4.6). |
| `applica-eventi` | A mano | Applica a posteriori gli eventi già raccolti dal monitor. |
| `link-verifica`, `oe-dettaglio` | A mano | Riverificano i link e rileggono le schede di ObiettivoEuropa. Non essendo nel giro, 6.173 link pubblicabili su 6.206 hanno l'ultima verifica al 23-24/09. |
| `archivia-processed` | A mano, mai lanciato in attivo | Archivierebbe i 569 «processed» chiusi. |
| `fondi-doppioni` | A mano | Fusioni con tutti i criteri esatti (anche chiave esterna e atto) e senza i controlli di prudenza del passo 9. Segue `RESOLVER_MODALITA`, che in produzione è attivo: senza `--ombra` o `--dry-run` fonde davvero, e senza `--limit` fonde tutto. Va usato con cautela (§8.1, A4). |
| `rigenera`, `seo-rigenera` | A mano | Riscrivono il testo di schede già pubblicate, mai lo slug né il titolo. `rigenera` non prende lucchetti: va lanciato nella finestra sicura (§3.3.1). |
| `sorveglia`, `salute` | Il timer non è installato | Oggi **nessuno guarda in automatico** se i giri girano (la tabella `monitoraggio_riepilogo` è vuota): diario e journal vanno letti a mano. |

Fonti: `backend/sql/bando_v11_04_transizioni.sql`, `backend/sql/bando_v11_12_monitoraggio.sql`,
`scraper_bandi/app/__main__.py`, `scraper_bandi/app/fonte_ufficiale.py` (righe 1814-1826, 2914-2952),
`scraper_bandi/app/monitoraggio.py`, tabelle `bando_evento`, `bando_link` e `monitoraggio_riepilogo` (vuota).

### 3.18 Riepilogo dei costi per passo

| Passo | Modello | Firecrawl | Contato nel diario e nei tetti? |
|---|---|---|---|
| 1 discover | no | no | non serve (costo zero) |
| 2 scrape | no (salvo la fonte 302) | sì, per alcune fonti | **no** |
| 3 preprocess | Haiku; Sonnet come ripiego | solo come ripiego | **no** |
| 4 enrich | Haiku, 7 chiamate per bando | possibile | **no** |
| 4-bis domini | no | no | non serve |
| 5 / 5-bis resolver | no (ricerca e arbitro non collegati) | in teoria; oggi 0 crediti | sì, ma solo per giro |
| 5-ter verifica, ingresso | no | no | non serve |
| 6 SEO | **Opus**, fino a 2 chiamate per bando | sì, se serve | **no** |
| 7 monitor | Haiku e Sonnet | possibile | **sì** |
| 8 verifica, controlli | Haiku, se serve | no | sì, nel tetto in dollari (e si ferma se un altro tetto giornaliero è già pieno) |
| 9 gemelli | no | no | non serve |

In parole semplici: **la spesa grossa (SEO, preprocess, enrich) non è sorvegliata da nessun tetto.** Il valore in
dollari che si legge nella riga del giro non è la spesa vera: comprende solo monitor, resolver e verifica.

Fonti: `scraper_bandi/app/bilancio.py`, `scraper_bandi/app/seo_skill.py`, `scraper_bandi/app/bando_seo_runner.py`
(righe 256-258), `scraper_bandi/app/verifica_stato.py`, `backend/app/bandi_pipeline.py`, `scraper_bandi/app/settings.py`.

### 3.19 Che cosa non è verificato in questo capitolo

- **Il file `.env` di produzione.** Il suo contenuto non è leggibile dal Mac. Resolver attivo, monitor in ombra con 5
  tipi attivi e verifica in ombra sono dedotti dai contatori del database. `MONITOR_STATI_ESTESI=true`, `MONITOR_GIRI`,
  lo scenario dei tetti, i modelli effettivi e `INDEXNOW_API_KEY` del sender vengono da RIPRESA o dai valori
  predefiniti del codice.
- **Il fuso orario del server**, dedotto dagli orari registrati.
- **Il servizio systemd e il riavvio automatico.** Il nome del servizio e che il file con `Restart=on-failure` e 20
  minuti di attesa sia installato sul server.
- **Il codice in produzione.** Che il deploy di oggi sia il commit d7f5663: la riga del giro di avvio contiene campi
  nuovi (`passi_non_ok`, `verifica_stato_ingresso`) che il giro delle 06 non aveva, ma il commit non è registrato nel
  database.
- **Il comportamento reale dei passi nuovi** alla prima esecuzione: verifica dei controlli (18:00 del 01/10), domini e
  gemelli (06:00 del 02/10).
- **I costi reali** di SEO, preprocess, enrich e Firecrawl. Le cifre del capitolo sono stime.
- **La chiave IndexNow del sender.** Che il sito non serva la chiave è verificato (404); che il sender abbia la sua
  variabile no.
- **I giri saltati del 24/09.** La causa dei due saltati per lucchetto. Per quello del 28/09 c'è solo il commento nel
  codice.
- **Tre numeri da studi precedenti:** i 353 pubblicati con link funzionante solo su domini non in lista, i 51 domini
  che diventerebbero «verificanti» con IndicePA, i 496 candidati leggibili della verifica.

---

## 4. Il database e lo stato di un bando

Questo capitolo descrive il database dei bandi com'era l'01/10/2026, dopo il deploy delle 10:10. I numeri vengono da
letture in sola lettura fatte quel giorno, fra le 11 e le 12 circa: alcuni contatori, come `pipeline_run`, crescono a
ogni giro. Le regole sono state controllate sul codice e sui file SQL.

### 4.1 Un database a parte, chi scrive e due lettori

I bandi non stanno nel database degli articoli. Hanno un progetto Supabase tutto loro.

- **Chi scrive.** Scrive solo news1, con la chiave di servizio (service-role key), che può fare tutto. Lo fa con il giro
  automatico dei bandi (`bandi_sender.py`, `bandi_pipeline.py`, `scraper_bandi`) e con i comandi lanciati a mano dalla
  riga di comando. Dentro il database lavora anche il job orario di pg_cron (§4.6): anche lui scrive, ma sempre
  passando da un evento. Le correzioni SQL a mano le lancia solo Michele.
- **Chi legge.** I lettori sono due: il sito edunews24.it e BandoFit. Leggono soltanto, con la chiave anonima (anon key).
- **Perché la chiave anonima è un punto delicato.** La anon key va trattata come pubblica: è la stessa per due
  applicazioni diverse ed è fatta per poter stare in chiaro. Su news1 la usano solo il server e le pagine SSR. Se
  BandoFit la metta nel codice del browser: **non verificato**. La sicurezza quindi non può dipendere dal tenerla
  segreta. Poggia su tre strumenti del database:
  1. la **RLS**, che decide quali righe può vedere chi usa la anon key;
  2. i **privilegi di colonna**, che decidono quali colonne può vedere;
  3. il divieto di eseguire funzioni: con la anon key si possono chiamare solo le poche funzioni che servono alla vista
     e la funzione a chiave del monitoraggio (migrazione 12).
- **Il patto con BandoFit.** Le promesse ai lettori sono scritte in `docs/contratto-db-bandi.md` (versione v11). La più
  importante: i lettori leggono la vista `bando_pubblico`, e lo stato vero di un bando è la colonna calcolata
  `stato_effettivo`, non la colonna salvata `stato_bando`.

Fonti: `docs/contratto-db-bandi.md` §1, `src/lib/supabase-bandi.ts` (importato solo da pagine, componenti `.astro` e
moduli lato server), `backend/sql/bando_v11_02_tabelle_di_servizio.sql`, `backend/sql/bando_v11_05_vista_pubblica.sql`,
`backend/sql/bando_v11_04_transizioni.sql` (job orario).

### 4.2 Le tabelle e cosa contengono

Le tabelle si dividono in quattro famiglie.

**1) Il bando e le sue classificazioni**

| Tabella | Cosa contiene | Righe |
|---|---|---|
| `bando` | Il cuore: un bando per riga, con titolo, testi, date, stato, slug, fonte ufficiale | 5.194 |
| Cataloghi: `regioni`, `settori`, `programmi`, `tipologie_bando`, `beneficiari`, `codici_ateco`, `modalita_erogazione` | Le liste fisse usate per classificare | 20 / 90 / 56 / 5 / 31 / 89 / 4 |
| Junction: `bando_regioni`, `bando_settori`, `bando_beneficiari`, `bando_codici_ateco` | Legano un bando a più voci dei cataloghi. Un bando può valere per tre regioni, per esempio | 8.115 / 9.356 / 6.251 / 4.783 |

Il contratto promette che gli id dei bandi e dei cataloghi non cambiano mai e non vengono mai riusati. BandoFit ci
costruisce sopra i suoi filtri.

**2) La storia e i link di ogni bando**

| Tabella | Cosa contiene | Perché esiste | Righe |
|---|---|---|---|
| `bando_evento` | Il registro di tutto ciò che succede a un bando: pubblicazione, chiusura, proroga, FAQ, fusione… | Nessuno cambia lo stato senza lasciare traccia. Le righe non si cancellano: nemmeno la chiave di servizio ha il permesso di DELETE. Il contenuto non si corregge: un trigger lascia cambiare solo i flag di lavorazione (`leggibile`, `in_aggiornamenti`, `applicato`), assegnare il cursore e togliere una prova, mai aggiungerla. Una correzione è un evento nuovo che rimanda a quello vecchio | 12.026 |
| `bando_link` | I link del bando: pagina, atto, allegati, candidatura, FAQ… | Ogni link ha il flag «pubblicabile». Può valere vero solo se il link ha risposto 2xx e compare davvero nella pagina di riferimento. Un link su un aggregatore si può salvare, ma un trigger lo rende sempre non pubblicabile | 10.139 (6.206 pubblicabili) |
| `bando_controllo` | La «scheda di servizio» del bando: ultimo controllo, priorità, impronte delle pagine e, dalla migrazione 13, 17 colonne della verifica dello stato (37 colonne in tutto) | Sta in una tabella a parte per non riscrivere la grande tabella `bando` a ogni controllo | 4.620. Ce l'hanno tutti i 2.197 `completed`; le altre 2.423 righe sono di bandi mai pubblicati (1.987 `rejected`, 436 `processed`) |
| `bando_fusione` | Per ogni doppione, il bando «master» in cui è confluito | Chi ha salvato l'id di un doppione sa dove andare | 6 |
| `bando_slug_storico` | Gli slug vecchi e il bando a cui rimandano | Un vecchio indirizzo non muore: risponde con un redirect 301 verso il bando giusto, oppure con 410 se il bando è stato ritirato | 6 (tutti 301) |

**3) Le regole e i riferimenti**

| Tabella | Cosa contiene | Righe |
|---|---|---|
| `dominio_ufficiale` | Lista bianca e lista nera dei domini: 58 enti, 19 portali pubblici, 7 pattern, 25 aggregatori (fra cui i social). Decide che cosa può essere una «fonte ufficiale» e quale prova rende «verificato» un evento. La lista nera vince sempre | 109 |
| `bando_transizione` | La lista bianca dei cambi di stato ammessi: chi può portare un bando da quale stato a quale (§4.6) | 24 |
| `fonte` | I siti e i portali da cui si raccolgono i bandi | 121 |

**4) Il diario delle macchine**

| Tabella | Cosa contiene | Righe |
|---|---|---|
| `pipeline_run` | Un diario per ogni giro e per ogni passo, con i contatori (§3.3.4) | 150 alle 11:30 (l'ultima riga era il giro di avvio delle 10:10) |
| `fonte_run` | Il diario per ogni fonte | 3.409 |
| `pipeline_lock` | I lucchetti che impediscono a due processi di lavorare insieme (§3.3.1) | 0 (vuota, come deve essere a riposo) |
| `monitoraggio_riepilogo`, `monitoraggio_chiave` | Il riepilogo di salute per il pannello di BandoFit e le impronte delle chiavi di accesso (migrazione 12) | `monitoraggio_riepilogo`: 0, perché il pannello è rimandato. `monitoraggio_chiave` non si può leggere nemmeno con la chiave di servizio (lo vuole la migrazione 12): che sia vuota è **non verificato** |

Fonti: `backend/sql/bando_v11_02_tabelle_di_servizio.sql` (immutabilità degli eventi, `bando_link`),
`bando_v11_04_transizioni.sql`, `bando_v11_12_monitoraggio.sql`, `bando_v11_13_stato_da_verificare.sql`; conteggi letti
sul DB l'01/10.

### 4.3 Il ciclo di vita di un bando: da raccolto a pubblicato

Ogni riga di `bando` ha una colonna `stato_processing`. Dice **a che punto della lavorazione** è il bando. È una cosa
diversa dallo stato del bando (aperto, chiuso…), che vedremo in §4.5.

Pensa a una catena di montaggio. Ogni passo del giro prende le righe ferme a una tappa e le porta alla tappa
successiva.

| Tappa (`stato_processing`) | Chi ce la porta | Che cosa vuol dire |
|---|---|---|
| `scraped` | scrape (raccolta) | La riga è appena stata scaricata da una fonte |
| `processed` | preprocess | Il contenuto è stato controllato e ripulito, e ha ricevuto un primo `stato_bando` |
| `rejected` | preprocess, oppure SEO (doppione probabile di ObiettivoEuropa, o gemello fuso prima della pubblicazione) | Scartato: non è un bando valido, o è un doppione. Non si pubblica mai |
| `enriched` | enrich | Classificato con regioni, settori, beneficiari, ATECO… |
| `completed` | SEO | Ha testi e slug. È pronto |
| `archiviato` | solo il comando manuale `archivia-processed` (lotto L8), non il giro | Ramo finale per i `processed` già chiusi che nessuno lavorerà più. Oggi 0 righe: il comando non è mai stato lanciato |
| `completed_duplicate` | nessuno, salvo `DEDUP_CANONICAL=true` (spento per difetto) | Valore vecchio: è ancora ammesso. Il codice che lo scrive esiste ancora, ma è spento. Oggi 0 righe |

Oggi i bandi sono 2.197 `completed`, 569 `processed` e 2.428 `rejected`. Le altre tappe sono vuote.

**La pubblicazione è automatica.** Un trigger del database pubblica la riga da solo quando ha tutte queste cose: è
`completed`, ha lo slug, ha lo stato, non è fusa in un altro bando e non è stata ritirata. Il trigger mette
`pubblicato = true` e annota l'ora in `pubblicato_at`. Nessun codice deve ricordarsi di pubblicare. Lo stesso trigger
ripubblica una riga se qualcuno prova a spubblicarla a mano: un pubblicato esce solo con una fusione o con un ritiro
(§4.4).

Oggi i pubblicati sono 2.191. I 6 `completed` che mancano sono i doppioni fusi (§4.9): restano `completed`, ma con
`pubblicato = false`.

**Perché `processed` è così numeroso.** Tutti i 569 `processed` hanno `stato_bando = chiuso`. L'enrich prende solo i
`processed` aperti, in apertura o senza stato, quindi questi bandi restano fermi lì per sempre, e la coda cresce a ogni
bando nuovo giudicato chiuso. Sono i candidati del comando manuale `archivia-processed`, che li porterebbe ad
`archiviato`. Non sono in attesa del giro.

**Il controllo all'ingresso (dal giro 2).** Prima della SEO c'è un controllo d'ingresso. In attivo
(`VERIFICA_STATO_MODALITA=attivo`) fa due cose. Trattiene per qualche giro un «aperto» senza scadenza e senza conferma.
E fonde subito sul pubblicato un bando nuovo che ne è il gemello esatto: il bando nuovo diventa `rejected` e non si
pubblica mai. Oggi è in ombra: conta e lascia passare tutto.

Fonti: `backend/sql/bando_v11_01_pubblicazione.sql` (CHECK di `stato_processing`, trigger
`bando_pubblica_al_completamento`), `scraper_bandi/app/db.py` (`select_bandi_to_enrich`, `select_processed_da_archiviare`),
`backfill.py`, `bando_preprocess_runner.py`, `bando_enrich_runner.py`, `bando_seo_runner.py` (doppioni ObiettivoEuropa,
sosta d'ingresso e gemelli prima della pubblicazione, righe 419-430), `bando_seo_runner._dedup_canonical_attivo`.

### 4.4 Le tre regole che il database fa rispettare da solo

Queste regole non si affidano alla buona volontà del codice: le impone il database stesso. Se un programma sbaglia, il
database rifiuta la scrittura.

1. **Un pubblicato non torna indietro** (migrazione 01). Non può uscire da `completed` e non può perdere lo slug: il
   database rifiuta la scrittura con l'errore 23514. Esce dalla vista pubblica solo in due casi. Il primo è una fusione
   (`bando_fondi`). Il secondo è un ritiro (`bando_ritira`), che nasce solo da una richiesta scritta del committente e
   dà un 410.
   *Perché:* BandoFit e Google hanno già quell'indirizzo. Se sparisse, i loro link si romperebbero.
2. **Lo slug è congelato** (migrazione 03). Lo slug di un pubblicato si cambia solo dichiarando apertamente
   l'intenzione, con l'impostazione `bandi.slug_intent`: è quello che fa `bando_cambia_slug`, che scrive anche il 301.
   Uno slug che sta nello storico con esito 301 o 410 non può tornare in uso.
   *Perché:* lo slug è l'indirizzo della pagina. Cambiarlo per sbaglio vuol dire perdere posizionamento e link.
3. **Lo stato cambia solo con un evento** (migrazione 04). Su un pubblicato, un UPDATE diretto di `stato_bando` viene
   rifiutato (errore 23514). Le date invece non sono bloccate: un UPDATE diretto passa, ma il trigger della migrazione
   03 spegne il flag «verificata» di quella data e stacca l'evento che la provava. L'unica strada pulita è registrare un
   evento e applicarlo con `bando_applica_evento`. Si può fare in due chiamate, oppure in una sola con
   `bando_registra_evento` e applica=true, come fa il job orario. Prima di scrivere, la funzione controlla due cose: la
   lista bianca `bando_transizione` (solo sui pubblicati) e la coerenza delle date (la pubblicazione non può venire dopo
   la scadenza). Scrive solo sei campi: stato, data di pubblicazione, data e ora di apertura, data e ora di scadenza.
   Oltre a questi aggiorna i flag «verificata» e il riferimento all'evento che fa da prova.
   *Perché:* ogni cambio lascia una traccia con la sua prova, e BandoFit può seguirlo.

Fonti: `backend/sql/bando_v11_01_pubblicazione.sql` (`bando_pubblicato_resta_completed`, CHECK
`bando_master_non_pubblicato` e `bando_ritirato_non_pubblicato`), `bando_v11_03_fonte_ufficiale.sql`
(`bando_slug_congelato`, `bando_slug_non_storico`, `bando_provenienza_date`), `bando_v11_04_transizioni.sql`
(`bando_stato_solo_via_evento`, `bando_applica_evento`, `bando_ritira`).

### 4.5 I cinque stati e lo «stato effettivo»

**I cinque stati possibili** (`stato_bando`):

| Stato | Significato |
|---|---|
| aperto | Si può presentare domanda |
| chiuso | Termine passato |
| in apertura prossimamente | Annunciato ma non ancora aperto |
| sospeso | Fermato dall'ente (aggiunto dalla migrazione 06) |
| revocato | Annullato dall'ente: è definitivo (aggiunto dalla migrazione 06) |

Oggi nessun bando è sospeso o revocato.

**Stato salvato e stato effettivo.** La colonna `stato_bando` è lo stato **salvato**. Il sito però mostra lo **stato
effettivo**: lo stato salvato corretto dall'orologio. Si ricalcola a ogni lettura, applicando queste regole
nell'ordine. Vince la prima che scatta.

1. **Revocato** resta revocato.
2. **Sospeso** resta sospeso, anche se la scadenza è passata. Un sospeso non si chiude mai d'ufficio.
3. **Scadenza passata → chiuso.** La scadenza è passata se la data è prima di oggi, oppure se è oggi e l'ora è già
   passata (alle 12:00 in punto di una scadenza alle 12:00 si è ancora in tempo). Se l'ora manca, il bando resta aperto
   fino a mezzanotte di Roma.
4. **In apertura** con data di apertura **verificata** e raggiunta (con l'ora, se c'è) → aperto. Senza verifica non si
   apre mai da solo.
5. In tutti gli altri casi vale lo stato salvato.

«Oggi» vuol dire sempre il giorno del calendario italiano, mai l'ora UTC del server.

*Esempio:* un bando aperto con scadenza il 30/09 e senza ora. L'01/10 alle 00:00 di Roma lo stato effettivo diventa
«chiuso», anche se la colonna dice ancora «aperto». Alle 00:05 il job orario riallinea la colonna.

*Perché due colonne:* lo stato effettivo è sempre giusto, anche nei minuti (al massimo 65) in cui il job orario (§4.6)
non ha ancora riallineato la colonna salvata.

**La stessa regola in tre linguaggi.** La regola è scritta tre volte: in Python (`scraper_bandi/app/stato_bando.py`), in
TypeScript per il sito (`src/lib/stato-bando.ts`) e in SQL (la funzione `bando_stato_effettivo`, usata dalla vista e
dal job orario). Tutte e tre partono da un'unica tabella di casi, `tests/stato-bando/casi.json`. Se la copia Python o
quella TypeScript divergono, i test falliscono. Per l'SQL `npm test` controlla che il blocco di casi dentro le
migrazioni sia identico byte per byte. Il comportamento della funzione già installata nel DB si controlla invece solo
quando la migrazione viene applicata: il blocco CASI deve restituire zero righe.

**Oggi:** sui 2.191 pubblicati ci sono 1.168 aperti, 857 chiusi e 166 in apertura. Stato salvato ed effettivo
coincidono su tutte le righe.

Fonti: `scraper_bandi/app/stato_bando.py` (`stato_effettivo`), `src/lib/stato-bando.ts:378-424`,
`backend/sql/bando_v11_02_tabelle_di_servizio.sql` e `bando_v11_05_vista_pubblica.sql` (`bando_stato_effettivo`),
`tests/stato-bando/casi.json`, `tests/stato-bando/genera-sql.ts`, `tests/estrazioni/stato-bando.test.ts:776-790`; DB:
`bando_pubblico`.

### 4.6 Chi cambia lo stato di un bando

**Prima della pubblicazione** lo stato lo decidono preprocess ed enrich, liberamente. Le regole di §4.4 valgono solo per
i pubblicati.

**Dopo la pubblicazione** ogni cambio deve stare nella lista bianca `bando_transizione` (24 righe). Ecco chi può fare
cosa:

| Chi | Che cosa può fare | Esempio |
|---|---|---|
| **pipeline** | Solo le righe di nascita (da nessuno stato ad aperto, chiuso o in apertura). Sono righe documentali: su un bando non ancora pubblicato il database non controlla la lista | Un bando nuovo entra come «aperto» |
| **job orario (cron)** | in apertura → aperto (`apertura_automatica`); aperto → chiuso e in apertura → chiuso (`chiusura_automatica`) | Alle 00:05 chiude i bandi scaduti ieri |
| **worker** (il monitor delle pagine ufficiali e la verifica dello stato) | apertura (da in apertura ad aperto); rettifica senza cambio di stato (su aperto e su in apertura); proroga di un aperto; chiusura da aperto e, dalla migrazione 13, da «in apertura»; riapertura o proroga di un chiuso (è l'unico modo per riaprirlo); sospensione (da aperto o in apertura); riapertura di un sospeso (ad aperto o a in apertura); revoca da qualunque stato tranne revocato; graduatoria ed esito su un chiuso | La pagina dell'ente pubblica una proroga |
| **redazione** | Nessuna riga propria nella lista bianca | — |

Assenze volute: da revocato non si esce mai, e un sospeso non si chiude mai.

**Con la migrazione 14** (scritta l'01/10, la applica Michele: RIPRESA §1) le due assenze diventano uscite controllate,
e la lista bianca passa a **28 righe**:
- un **sospeso si chiude** con una `chiusura` letta dal worker sulla pagina ufficiale (mai d'ufficio: il job orario
  non tocca sospesi né revocati); riapre con una `riapertura`, anche datata al passato; una proroga su un sospeso
  aggiorna solo la data di scadenza e lo lascia sospeso;
- dal **revocato** si esce solo con `annullamento_revoca`, verso lo stato calcolato dalle date (in apertura se
  l'apertura è futura, chiuso se la scadenza è passata, altrimenti aperto);
- dal sospeso e dal revocato il database esige anche l'**evento giusto** per quella riga (per esempio una proroga non
  fa uscire un revocato);
- la **redazione** corregge uno stato sbagliato fra i cinque con `select bando_correggi_stato(<id>, '<stato>', '<nota>')`
  (solo pubblicati, nota obbligatoria). Nasce un evento `correzione_redazionale`, visibile nello storico con
  l'etichetta «Correzione» e fuori dagli aggiornamenti. Nella lista bianca non c'è nessuna riga `redazione`: il trigger
  lascia passare solo la correzione fatta da quella funzione. Se la correzione contraddice le date, il job orario la
  ribalta entro un'ora (per riaprire si corregge prima la data). Due o più correzioni verso lo stesso stato nello
  stesso giorno sono ammesse: la 14 toglie `correzione_redazionale` dall'indice che scarta gli eventi doppi;
- un evento del worker **superato** da un evento di stato più recente dello stesso bando (worker o redazione; il job
  orario non conta; la data di un evento non vale mai oltre il giorno in cui è stato rilevato; una proroga, una
  riapertura o una rettifica che porta una scadenza non ancora passata non la supera una chiusura), oppure con una
  transizione **non più ammessa**, non si applica: la funzione risponde «false» e lo **marca** (`scartato_per`), così non
  torna in coda a ogni giro. Prima dava l'errore 23514 e tornava in coda per sempre. Si rimette in coda a mano azzerando
  le tre colonne `scartato_*`.

Il codice applica sospensione, revoca e annullamento solo se la funzione `bando_capacita_sospensioni()` risponde
«true» (cioè la 14 c'è ed è intera) e `MONITOR_STATI_ESTESI=true`.

**Il job orario.** È il job `bandi-transizioni-orarie` di pg_cron, che gira al minuto 5 di ogni ora (`5 * * * *`). Per
ogni pubblicato non sospeso e non revocato confronta lo stato salvato con quello effettivo. Dove differiscono, registra
e applica un evento `chiusura_automatica` o `apertura_automatica`. Non fa mai un UPDATE diretto.
- **Che giri è verificato.** La funzione di sola lettura `monitoraggio_job_orario` (migrazione 12, dichiarata `STABLE`,
  chiamata in GET come fa `salute`) lo trova per nome in `cron.job`. Alla lettura l'ultimo avvio era delle 11:05 di
  Roma (alle 12:30, quello delle 12:05), riuscito, con 0 fallimenti nelle 24 ore. L'orario `5 * * * *` viene dal file
  SQL e dagli orari degli eventi, tutti al minuto 5.
- Gli eventi `chiusura_automatica` sono 190 in tutto, dal 24/09. 107 sono delle 00:05 dell'01/10. Altri 2 sono delle
  19:05 del 30/09: erano bandi con l'ora di scadenza.
- Gli eventi `apertura_automatica` sono **0** in tutta la storia. Il motivo: per aprire da solo, il job vuole una data
  di apertura verificata, e nessuno dei 166 «in apertura» pubblicati ce l'ha. Anzi, 163 non hanno proprio una data di
  apertura. Oggi un «in apertura» si apre solo con una correzione manuale. L'evento `apertura` del monitor non è fra i
  tipi attivi, e la verifica dello stato è in ombra.

**La redazione.** Le correzioni a mano passano comunque da un evento. Nel registro compaiono con origine «worker» e una
descrizione nel campo `metodo` («correzione manuale…»). Sono 50 (28 proroghe, 17 aperture, 4 rettifiche, 1 chiusura).
Sono state registrate tutte il 30/09, fra le 12:19 e le 19:18 di Roma (33 di queste dai due file SQL della sera, fra le
19:02 e le 19:18): alcune hanno nel `metodo` la data dell'01/10. Sono tutte verificate, applicate, visibili e nel box
«Aggiornamenti».

Fonti: `scraper_bandi/app/stato_bando.py` (`TRANSIZIONI`, commento sulle assenze), `backend/sql/bando_v11_04_transizioni.sql`
(`bando_transizioni_automatiche`, `cron.schedule`), `bando_v11_12_monitoraggio.sql:236-245` (`monitoraggio_job_orario`),
`bando_v11_13_stato_da_verificare.sql` (riga 24), `scraper_bandi/app/db.py:3036-3061` (`job_orario` in GET); DB:
`bando_transizione`, `bando_evento`, `rpc/monitoraggio_job_orario`.

### 4.7 Il bollino «da verificare»: i 5 motivi e l'ordine

**Che cos'è.** `stato_da_verificare` è un'etichetta di prudenza, calcolata dalla vista a ogni lettura (migrazione 13).
Dice al lettore: «lo stato che vedi potrebbe non essere certo, ed ecco perché». Come appare sul sito è in §5.4.

**Non cambia mai lo stato.** Un bando «Aperto · da verificare» resta fra gli aperti. Nessuna chiusura scatta a tempo.

**Vale solo per due famiglie di bandi**, scelte in base allo stato **effettivo**:
- **ramo I**: i bandi «in apertura»;
- **ramo A**: i bandi «aperti» **senza** data di scadenza.

Per tutti gli altri bandi vale sempre NULL, cioè nessun dubbio.

**I cinque motivi:**

| Motivo | In parole semplici |
|---|---|
| `data_apertura_passata` | Doveva aprire in una data già passata, ma risulta ancora «in apertura» |
| `smentito_dalla_fonte` | La pagina ufficiale dice un'altra cosa |
| `previsione_scaduta` | Il periodo indicativo annunciato («entro marzo») è passato |
| `senza_conferma` | Nessuna prova recente che lo stato sia giusto |
| `termine_passato` | Un termine indicato sulla pagina è già passato |

**L'ordine conta: vince la prima regola che scatta.** Una «lettura» vale solo se è stata fatta sullo stesso stato
salvato che il bando ha oggi.

Ramo I, «in apertura» (ordine I1, I2, I3, I6-bis, I4, I5, I6, I7):

| Regola | Condizione | Risultato |
|---|---|---|
| I1 | Apertura verificata con data | nessun dubbio |
| I2 | Data di apertura già passata | `data_apertura_passata` |
| I3 | La pagina ufficiale letta dice aperto, chiuso o uscito | `smentito_dalla_fonte` |
| I6-bis | Mai esaminato dalla verifica in modalità attiva | nessun dubbio |
| I4 | Periodo indicativo scaduto | `previsione_scaduta` |
| I5 | La pagina ha confermato «in apertura» negli ultimi 30 giorni | nessun dubbio |
| I6 | Pubblicato da al massimo 3 giorni | nessun dubbio |
| I7 | Altrimenti | `senza_conferma` |

Ramo A, «aperto senza scadenza» (ordine A1, A2, A4, A3, A5, A6, A7, A8):

| Regola | Condizione | Risultato |
|---|---|---|
| A1 | La pagina dice chiuso, uscito o in apertura | `smentito_dalla_fonte` |
| A2 | Un lettore strutturato (non il modello) ha letto «aperto» negli ultimi 30 giorni, dopo l'eventuale segnale dell'aggregatore | nessun dubbio |
| A4 | Mai esaminato in modalità attiva | nessun dubbio |
| A3 | Termine indicato già passato | `termine_passato` |
| A5 | Segnale dell'aggregatore: ObiettivoEuropa dice «in uscita» o mostra una scadenza passata, oppure non elenca più il bando da oltre 3 giri | `senza_conferma` |
| A6 | Termine indicato da oggi in poi | nessun dubbio |
| A7 | Pubblicato da al massimo 7 giorni | nessun dubbio |
| A8 | Altrimenti | `senza_conferma` |

**Perché le regole «mai esaminato» (I6-bis e A4) vengono così presto.** Finché la verifica dello stato non ha mai
guardato un bando in modalità attiva, il sistema non ha elementi per dubitare. Mettere il bollino a centinaia di bandi
solo perché nessuno li ha ancora controllati sarebbe rumore.

**Che cosa succede oggi, in ombra.** Le letture della pagina (`stato_letto` e le colonne collegate) e la data
dell'esame in attivo (`esaminato_attivo_at`) le scrive **solo** il passo `verifica_stato` in modalità attiva, e oggi è
in ombra. Un trigger della 13 scarta inoltre le letture fatte su domini non verificanti. Quindi I3, A1 e A2 non possono
scattare, e I6-bis e A4 fermano tutto il resto. Il segnale dell'aggregatore invece si scrive già: oggi 59 bandi hanno
«in_uscita». Però non conta, perché A4 viene prima. L'unico motivo che può comparire è `data_apertura_passata`, perché
dipende solo dalla data di apertura salvata.
- Oggi lo hanno **2 bandi**, entrambi «in apertura»: il 2308 (apertura prevista il 06/07/2026) e il 2955 (31/05/2026).
- Le colonne di lettura in `bando_controllo` sono tutte vuote: 0 `stato_letto`, 0 `esaminato_attivo_at`, 0
  `termine_indicato`, 0 `previsto_entro`. È vuota anche la colonna d'ombra `lettura_stato`: dal deploy la fase
  «controlli» della verifica non è ancora girata, perché gira solo nei giri delle 06 e delle 18.

**Che cosa succederà all'attivazione.** Molti bandi riceveranno il bollino. Oggi i candidati della verifica sono 592:
426 aperti senza scadenza (ramo A) e 166 in apertura (ramo I). Di questi, 96 hanno una pagina che non si può leggere: 89
nel ramo A e 7 nel ramo I. Al primo giro attivo ricevono subito la data dell'esame, perché per loro non si scarica
niente e il tetto di 40 letture non li ferma (resta solo il tetto di 900 secondi). Da lì valgono le regole che vengono
dopo. Nel ramo A, un bando pubblicato da più di 7 giorni senza termine indicato e senza segnale passa a
`senza_conferma` (A8). Se il bando ha un segnale dell'aggregatore, passa a `senza_conferma` per la regola A5. Con un
termine indicato passato prende `termine_passato`, con un termine futuro nessun dubbio. Nel ramo I, chi non ha
previsione scaduta e non è stato pubblicato negli ultimi 3 giorni passa a `senza_conferma` (I7). Poi, man mano che la
verifica legge le pagine, toccherà a gran parte degli altri candidati. Va messo in conto prima di attivare.

**Attenzione: tornare in ombra non toglie i bollini.** La vista calcola il bollino dalle colonne di `bando_controllo` e
non sa in che modalità gira la verifica. Un bando che ha già `esaminato_attivo_at` non è più protetto da I6-bis e A4
(dettaglio in §9.4).

**Un punto da chiarire.** Nel ramo I la regola I5 accetta come conferma anche una lettura del modello. Nel ramo A la
regola A2 pretende invece un estrattore. Anche I3 e A1 possono scattare da una lettura del modello, che però la vista
non mostra: la vista espone `stato_letto` solo se viene da un estrattore. Se questa differenza sia voluta: **non
verificato**.

Fonti: `scraper_bandi/app/stato_bando.py` (`stato_da_verificare`), `backend/sql/bando_v11_13_stato_da_verificare.sql`
(funzione `bando_stato_da_verificare`, trigger `bando_lettura_verificante`, vista, righe 740-761),
`scraper_bandi/app/verifica_stato.py` (docstring, `pagina_da_leggere`, `_fase_controlli`), `segnali.py`
(`segnale_aggregatore`), `bando_runner.py`, `docs/contracts/bandi-giro-2.md` §19.3; DB: `bando_pubblico`,
`bando_controllo`; candidati calcolati in sola lettura con `verifica_stato.scegli_candidati` l'01/10.

### 4.8 Gli eventi: dal registro al pubblico

Un evento è una riga di `bando_evento`: «al bando X è successo Y, ecco la prova». Per arrivare al pubblico deve passare
tre cancelli.

**Cancello 1: la registrazione.**
- La strada normale è la funzione `bando_registra_evento`. È il database a decidere se l'evento è **verificato**. Per
  esserlo, la pagina di prova deve stare su un dominio attivo di ente, di portale pubblico o di pattern con confidenza
  almeno 0,8, mai su un aggregatore. E deve esserci la citazione.
- Lo stesso evento (stesso bando, tipo, campo e valore) registrato due volte nello stesso giorno di Roma viene
  riconosciuto come doppione da un indice del database.
- In ombra, e come ripiego, il codice Python fa invece un inserimento diretto, e il «verificato» lo decide Python. Al
  momento dell'inserimento un trigger toglie la prova se sta su un aggregatore o su un indirizzo illeggibile, e in quel
  caso l'evento non è più verificato. Il resto del controllo sul dominio (ente, portale, pattern, confidenza) invece non
  viene rifatto: lì la garanzia regge sui controlli del codice.

**Cancello 2: l'applicazione.** `bando_applica_evento` riversa l'evento nelle sei colonne di stato e date, dopo il
controllo della lista bianca (solo sui pubblicati) e quello delle date. I flag «verificata» si accendono solo se
l'evento è verificato. Se le date sono incoerenti, l'evento non si applica e si registra `elaborazione_bloccata`. Gli
eventi che non toccano colonne (FAQ, allegato, graduatoria, esito…) vengono solo segnati come applicati. L'applicazione
non rende visibile l'evento: quello è il cancello 3.

**Cancello 3: la visibilità.** Quando un evento diventa leggibile, un trigger gli assegna un **cursore**: un numero
progressivo che non si toglie più. Da quel momento la anon key lo vede. BandoFit segue il cursore per sapere che cosa
c'è di nuovo.
- I tipi interni (`segnale_fonte`, `fonte_ufficiale_non_trovata`, `possibile_doppione`, `elaborazione_bloccata`…) non
  ricevono mai un cursore.
- Un evento su un bando non ancora pubblicato aspetta. Riceve il cursore alla pubblicazione, alla fusione o al ritiro.
- La migrazione 08 emette un evento `pubblicazione` per ogni nuovo pubblicato. È così che BandoFit vede i bandi nuovi.

**I numeri di oggi** (11:30; alle 12:30 gli eventi totali erano 12.086):

| Misura | Valore |
|---|---|
| Eventi totali | 12.026 (pipeline 8.746, worker 3.090, cron 190) |
| Visibili alla anon key (con cursore) | 3.087 |
| …di cui marcati per il box «Aggiornamenti» | 52 (50 sono le correzioni manuali, §4.6) |
| Eventi `pubblicazione` | 2.197 (i 2.191 pubblicati più i 6 fusi): copertura completa |
| Leggibili ma senza cursore | 79, tutti `fonte_ufficiale_verificata` su bandi mai pubblicati: aspettano |
| Verificati ma non applicati | 20, tutti del worker (proroga 9, faq 6, apertura 3, nuovo_allegato 2) |

**Chi produce gli eventi.**
- Il job orario: chiusure e aperture automatiche.
- Il **monitor** delle pagine ufficiali (§3.13): legge la pagina dell'ente, ne confronta l'impronta con quella
  precedente e, se è cambiata in modo rilevante, chiede al modello di proporre eventi. **Il modello propone, i gate
  decidono**: sono controlli automatici G1–G9. Controllano che la citazione ci sia davvero, che il dominio sia
  ufficiale, che la direzione sia coerente, che non ci siano doppioni, che la transizione sia ammessa. Per i cambi di
  stato o di data serve anche una seconda prova (G7).
- La **verifica dello stato** (§3.14), che ha i suoi gate. Fra questi c'è la G7e. Per una lettura strutturata serve la
  stessa lettura ripetuta a distanza di almeno 60 ore; per una lettura del modello vale il doppio modello del G7.
- Il resolver (origine pipeline), che registra se ha trovato la fonte ufficiale (`fonte_ufficiale_verificata`,
  `fonte_ufficiale_non_trovata`).
- La redazione, con le correzioni manuali.

**Ombra e tipi attivi.** Il monitor oggi è in **ombra**: registra le proposte senza applicarle e senza mostrarle, e
serve a misurarne la precisione. Per uscire dall'ombra servono il 95% di precisione su almeno 100 eventi.

C'è un'eccezione: i tipi faq, nuovo_allegato, graduatoria, esito e proroga. Se un evento di questi tipi supera i gate,
è nato nel controllo in corso ed è verificato per il database, viene applicato e mostrato da solo. Che i tipi siano
attivi lo dice il contatore `tipi_attivi` del monitor delle 06 dell'01/10 (`pipeline_run` 146), che li elenca tutti e
cinque. Il monitor delle 18 del 30/09 (riga 138) non aveva ancora quel contatore. Le righe di `pipeline_run` mostrano
un giro di avvio il 30/09 alle 18:47 di Roma, che RIPRESA §1 indica come il deploy che ha portato i tipi attivi.
RIPRESA nella sezione «Configurazione in produzione» dice invece ancora che la variabile «non è in produzione»: il
diario dà ragione al §1. Il contenuto del file `.env` di produzione è **non verificato**.

Dall'attivazione dei tipi il monitor ha girato una sola volta (alle 06 dell'01/10) e non ha prodotto eventi: nessun
evento del monitor è ancora stato applicato da solo. Il giro di avvio delle 10:10 non fa girare il monitor.
L'**arretrato d'ombra** è di 78 eventi del worker non applicati, 20 verificati e 58 no. Resta fermo per decisione del
lead, anche se contiene proroghe vere.

Fonti: `backend/sql/bando_v11_02_tabelle_di_servizio.sql` (cursore, `bando_evento_tipo_pubblico`,
`b_evento_prova_non_aggregatore`, immutabilità), `bando_v11_04_transizioni.sql` (`bando_registra_evento`,
`bando_applica_evento`), `bando_v11_08_evento_pubblicazione.sql`, `bando_v11_10_sottodomini_dei_pattern.sql`
(`bando_dominio_verificante`), `scraper_bandi/app/db.py` (`_registra_evento`), `eventi.py` (gate,
`ORE_DOPPIA_LETTURA = 60`), `monitoraggio.py` (`SOGLIA_PRECISIONE`, `CAMPIONE_MINIMO`, `_attiva_per_tipo`); DB:
`bando_evento`, `pipeline_run`.

### 4.9 Le fusioni

**Il problema.** Lo stesso bando può entrare più volte: dall'aggregatore e dal sito dell'ente, da due giri dello stesso
calendario, o con un URL cambiato dalla fonte.

**La soluzione.** La funzione `bando_fondi` fonde il doppione nel bando «master», in un'unica operazione:
1. toglie il doppione dal pubblico (`pubblicato = false`, insieme al riferimento al master);
2. scrive la riga in `bando_fusione`;
3. mette lo slug del doppione in `bando_slug_storico` con redirect 301 verso il master;
4. crea due eventi `fusione`, uno sul doppione e uno sul master;
5. copia i link sul master.

Se A era già fuso in B e B viene fuso in C, la funzione accorcia la catena, così A punta direttamente a C.

**La funzione inversa è `bando_separa`.** Non c'è un comando da riga di comando: si lancia a mano nel SQL Editor. Mette
lo slug storico in «annullato», cancella la riga di `bando_fusione`, toglie il riferimento al master (così il trigger
ripubblica la riga, se è ancora `completed`) e registra un evento pubblico `separazione`. Gli eventi `fusione` e i link
copiati sul master restano: per questo una fusione si dice «quasi irreversibile».

**Oggi:** 6 fusioni, 6 slug storici (tutti 301), 12 eventi `fusione`. Sono tutte del 30/09, con il motivo «doppione
verificato il 29/09 sulla fonte ufficiale».

**Le fusioni automatiche (giro 2).** Il passo `gemelli` (§3.15), solo nel giro delle 06, cerca i gemelli certi fra i
pubblicati.
- **Fonde solo ciò che è certo.** I criteri esatti sono quattro: URL identico, stessa chiave esterna, stesso numero di
  atto sullo stesso dominio, oppure la stessa riga di un calendario letta due volte. In automatico se ne usano solo due
  (URL e riga di calendario); gli altri due valgono solo per le fusioni a mano.
- La somiglianza dei titoli non basta mai, perché «edizione 2025» e «edizione 2026» sembrano uguali ma non lo sono.
  Quei casi diventano solo proposte, da guardare a mano. Anche fra le coppie esatte alcune vengono scartate per
  prudenza: URL condiviso da più righe, anni o lotti diversi, titoli diversi.
- Al massimo 10 fusioni per giro (`GEMELLI_FUSIONI_PER_GIRO`). Si fondono solo coppie: una catena di tre bandi non si
  fonde in automatico.
- La modalità segue `VERIFICA_STATO_MODALITA`. Oggi è in ombra: il passo elenca e conta, ma non fonde.
- Il contratto prometteva a BandoFit un avviso scritto almeno 7 giorni prima dell'attivazione. Dal giro 3
  (`docs/contratto-db-bandi.md` §6.2, aggiornato l'01/10) l'avviso è uno solo, mandato prima del deploy, senza i 7
  giorni.
- In attivo c'è anche la fusione prima della pubblicazione (§4.3): un bando nuovo gemello esatto di un pubblicato si
  fonde subito, senza tetto, e non viene mai pubblicato.

Le fusioni attese all'attivazione sono **52 (43 per URL, 9 di calendario)**. La misura è stata rifatta l'01/10 alle
11:55 con `gemelli --dry-run`, in sola lettura. Risultato: 2.191 pubblicati esaminati, 52 gruppi di due, nessuna catena.
Sono state scartate per prudenza 33 coppie (12 per URL condiviso, 20 per anni o lotti diversi, 1 per titoli diversi).
Con il tetto di 10 per giro ne restano 42 oltre il tetto, quindi servono circa 6 giri delle 06.

Fonti: `scraper_bandi/app/gemelli.py` (`CRITERI_ESATTI`, `FUSIONI_PER_GIRO`, `esegui_passo`), `scraper_bandi/app/db.py`
(`fondi_bandi`), `bando_seo_runner.py` (gemelli prima della pubblicazione), `backend/app/bandi_pipeline.py` (passo 9,
solo `GIRO_DELLE_06`), `backend/sql/bando_v11_04_transizioni.sql` (`bando_fondi`; `bando_separa`, righe 957-997),
`scraper_bandi/app/__main__.py:1370-1395` (nessun comando di separazione), `docs/contratto-db-bandi.md` §6.2; DB:
`bando_fusione`, `bando_slug_storico`, `bando_evento`.

### 4.10 Che cosa vede chi legge: la vista e i permessi

**La vista `bando_pubblico`** è la finestra ufficiale per il sito e per BandoFit.
- Contiene solo i pubblicati: 2.191 righe. I fusi e i ritirati non ci sono, perché hanno `pubblicato = false`.
- Gira con i permessi di chi legge (security_invoker), quindi la RLS resta il vero guardiano.
- Ha 49 colonne: 44 dalla migrazione 05 e 5 dalla 13 (`stato_da_verificare`, `stato_letto`, `stato_letto_at`,
  `termine_indicato`, `termine_indicato_fonte`).
- Calcola `stato_effettivo`.
- Ripulisce dagli aggregatori i link delle colonne vecchie (`link_bando`, `link_candidatura`, `allegati`).
- Espone `stato_processing` sempre come `'completed'`, perché le vecchie query di BandoFit continuino a funzionare.

Due regole sulle colonne nuove:
- `stato_letto` compare solo se la lettura riguarda lo stato salvato di oggi ed è stata fatta da un estrattore
  strutturato, non dal modello;
- `termine_indicato` compare solo dopo un esame in modalità attiva, anche se in ombra la verifica potrebbe già
  calcolarlo.

Oggi entrambe sono vuote ovunque.

**Che cosa può leggere la anon key** (controllato con letture reali l'01/10):

| Leggibile | Non leggibile |
|---|---|
| `bando_pubblico`, i cataloghi, `bando_fusione`, `bando_slug_storico` | `dominio_ufficiale`, `pipeline_run`, `fonte_run`, `pipeline_lock`, `bando_transizione`, `monitoraggio_*` (errore 42501) |
| Le junction: tutte le righe (8.115 / 9.356 / 6.251 / 4.783), comprese quelle dei bandi mai pubblicati | `select=*` su `bando_link`, `bando_evento` e `bando_controllo` |
| `bando_link`: 8 colonne nominate e solo i link pubblicabili dei pubblicati (5.712 righe) | Le colonne interne di `bando_controllo` (per esempio `lettura_stato`: errore 42501) |
| `bando_evento`: solo colonne nominate e solo gli eventi con cursore (3.087) | — |
| `bando_controllo`: 11 colonne concesse (2 dalla 05, 9 dalla 13), solo per i pubblicati (2.191 righe) | — |
| `fonte`: la richiesta passa ma restituisce 0 righe | — |

**La falla di passaggio.** Finché la migrazione 07 non è applicata, la anon key legge ancora **l'intera tabella
`bando`** con il vecchio filtro (completed con slug): 2.197 righe, cioè i pubblicati più i 6 fusi, con tutte le 63
colonne. Fra queste ci sono `raw_data` (1.878 righe) e `link_bando` verso ObiettivoEuropa (1.772 righe). Il contratto lo
ammette come fase di passaggio, ma contraddice la sua promessa che nessun link ad aggregatori esca con la anon key. La
07 non ha una data.

Fonti: `backend/sql/bando_v11_05_vista_pubblica.sql`, `bando_v11_13_stato_da_verificare.sql` (grant delle 9 colonne,
righe 371-382; vista), `bando_v11_02_tabelle_di_servizio.sql` (grant e policy di `bando_link` e `bando_evento`),
`docs/contratto-db-bandi.md`; letture come anon sul DB. Il testo vivo delle policy RLS non è leggibile da PostgREST: lo
stato è dedotto dal comportamento (**non verificato** sulle policy stesse).

### 4.11 Le migrazioni

Una migrazione è uno script SQL che cambia la struttura del database. Le scrive Claude, ma le applica sempre Michele, a
mano, nel SQL Editor di Supabase.

| N. | Che cosa fa | Stato |
|---|---|---|
| 01 | Aggiunge a `bando` le colonne nuove (pubblicato, ore, flag «verificata», fonte ufficiale, ricerca full-text), `archiviato` fra le tappe e il trigger di pubblicazione automatica | applicata |
| 02 | Crea le tabelle di servizio (eventi con cursore, link, fusioni, slug storici, controllo, domini) e toglie alla anon key tutto ciò che il contratto non prevede | applicata |
| seed | Riempie `dominio_ufficiale` con portali, pattern, aggregatori e social. Oggi la tabella ha 109 righe: 58 enti, 19 portali, 7 pattern, 25 aggregatori | applicata |
| 03 | Slug congelato, provenienza delle date, controlli di coerenza della fonte, trigger anti-aggregatore | applicata |
| 04 | Lista bianca delle transizioni, funzioni del ciclo di vita, regola «stato solo con un evento», job orario | applicata |
| 05 | La vista `bando_pubblico` | applicata |
| 06 | Stati a cinque valori (sospeso, revocato) | applicata il 28/09 (la data viene da CLAUDE.md e RIPRESA; sul DB il marcatore risponde `stati_cinque=true`) |
| **07** | Vista senza le colonne vecchie, RLS su «pubblicato», chiude la tabella `bando` alla anon key | **non applicata, bloccata** |
| 08 | Evento `pubblicazione` per ogni nuovo pubblicato | applicata |
| 09 | Valore iniziale «in_verifica» per la fonte ufficiale: senza, i bandi nuovi sfuggivano al resolver | applicata |
| 10 | Pattern di dominio estesi ai sottodomini | applicata |
| 11 | Traduzione di `stato_proposto` (sospeso o revocato) e marcatore delle capacità | applicata il 28/09 (data da CLAUDE.md; il marcatore `bando_capacita_eventi` risponde `stati_cinque=true` e `traduce_stato_proposto=true`) |
| 12 | Tabelle e funzioni del monitoraggio per il pannello di BandoFit: `monitoraggio_riepilogo`, `monitoraggio_chiave`, un trigger e due funzioni | applicata: i suoi oggetti esistono e `monitoraggio_job_orario` risponde. La data dell'01/10 viene dal lead |
| 13 | Verifica dello stato: 17 colonne in `bando_controllo` (9 leggibili dalla anon key), `stato_da_verificare`, 5 colonne nella vista, riga 24 della lista bianca | applicata: vista a 49 colonne, 24 transizioni, 37 colonne in `bando_controllo`. La data dell'01/10 viene dal lead |
| **14** | Sospensione e revoca (§4.6): 4 righe di lista bianca (28 in tutto), `bando_applica_evento` e il trigger dello stato ridefiniti, colonne `scartato_per`, `scartato_at`, `scartato_dettaglio` su `bando_evento` (non concesse ad anon), funzioni `bando_correggi_stato` e `bando_capacita_sospensioni`. Si applica **dopo la 13**; dopo la 14 non si rieseguono né la 04, né la 11, né la 13; rollback in ordine inverso, prima la 14 | **scritta l'01/10, non applicata** (la applica Michele, RIPRESA §1). Provata su Postgres 17 con la catena 01-13 eseguita dai file veri |

**Che cosa blocca la 07.** Servono tre cose:
1. il passo c2 di BandoFit, cioè togliere i ripieghi sulle colonne vecchie, con conferma scritta;
2. la migrazione del sito, che chiede ancora `link_candidatura`, `link_candidatura_source` e `allegati`;
3. abbastanza righe «candidatura» in `bando_link`.

Sul terzo punto oggi c'è 1 sola riga leggibile. Tutte le 92 righe candidatura sono state create dalla 02 il 23/09, e da
allora nessun codice ne crea di nuove. La 07 richiede anche la 13. Dal giro 3 la SEO scrive le righe di candidatura e di allegato dei
bandi nuovi, `link_verifica` (passo 11) le rende pubblicabili a ogni giro, e `docs/bandi-monitor/correzioni-giro-3.sql`
aggiunge le poche che mancano ai pubblicati (4 l'01/10). La misura delle schede che perderebbero pulsante o allegati
(140 l'01/10) è in RIPRESA §8.5; si ripete un giorno dopo il deploy.

**Due avvertenze.**
- Rieseguire la 02 dopo la 13 toglierebbe i 9 permessi di colonna della 13. A quel punto ogni lettura della vista che
  chiede le colonne nuove riceverebbe l'errore 42501. Il sito le chiede (`stato_da_verificare` e le altre), quindi
  scheda ed elenchi dei bandi si fermerebbero. Rimedio: rieseguire la 13.
- La 12, a differenza delle altre, **non** è chiusa in un `BEGIN; … COMMIT;` esplicito.

**Non verificato:**
- la data e l'ordine di applicazione di 12 e 13: si è controllato solo che i loro oggetti esistano e rispondano;
- quale commit giri in produzione: il DB mostra solo che il giro di avvio è partito alle 10:10 ed è finito bene alle
  10:18 (`pipeline_run` 150).

Fonti: `backend/sql/bando_v11_*.sql`, `docs/contratto-db-bandi.md` §10.1 e §10.2 (dove 09, 10 e 11 mancano dalla
tabella), `src/lib/supabase-bandi.ts` (colonne chieste), `scraper_bandi/app/` (nessuno scrive link di tipo
`candidatura`); DB: oggetti della 12 e della 13, `rpc/bando_capacita_eventi`, `bando_link`.

### 4.12 Punti aperti che riguardano questo capitolo

- **Nessuna sorveglianza automatica.** Il pannello di BandoFit è rimandato e `monitoraggio_riepilogo` è vuoto. Che il
  timer `sorveglia` non sia installato e che la chiave non esista lo dice il lead: **non verificato** da qui, perché
  `monitoraggio_chiave` non si legge nemmeno con la chiave di servizio. Restano il comando `salute` lanciato a mano e
  il diario `pipeline_run`.
- **Controllo dell'08/10 a rischio.** Il bando 661135 sta nella verità nota come «chiusura». Ma è stato chiuso dal job
  orario alle 00:05 dell'01/10 (ora di Roma; alle 22:05 del 30/09 in UTC), perché scadeva il 30/09. Non è più un
  candidato: il confronto lo conterà come difforme, perché un id assente dal report vale come difforme. Aggiornare la
  verità nota vuol dire modificare codice (`VERITA_NOTA` in `verifica_stato.py`) e rifare il deploy (§8.1, A2).
- **Verità nota misurata senza modello.** La verità nota è stata misurata con `--senza-modello`. In produzione invece il
  passo usa il modello per difetto (`VERIFICA_STATO_USA_MODELLO`, predefinito vero): il confronto potrebbe dare
  difformità spurie. Il valore in produzione è **non verificato**.
- **Documentazione in ritardo.** RIPRESA è aggiornata al 30/09: dice le migrazioni 12 e 13 «scritte e mai eseguite» e
  mette `MONITOR_TIPI_ATTIVI` fra le cose «da aggiungere», mentre il monitor delle 06 dell'01/10 la legge già.
  CLAUDE.md elenca le migrazioni applicate solo fino al 28/09. Il contratto non ha 09, 10 e 11 nella tabella delle
  migrazioni.
- **Tipo NULL su 259 fonti «trovate».** Sono 259 delle 620 fonti «trovate» dei pubblicati (sulle 700 «trovate» di tutta la tabella, non ricontrollato). Il loro host è riconosciuto solo da un
  pattern (per esempio `regione.*.it`), e il codice lo vuole così. Il contratto ammette il tipo NULL, ma non dice che
  una fonte `trovata` può averlo. Un lettore potrebbe scambiarlo per «non ufficiale».
- **569 `processed` chiusi fermi.** Non li lavora nessun passo del giro. Si sbloccano solo con il comando manuale
  `archivia-processed`, mai lanciato.

Fonti: `scraper_bandi/app/verifica_stato.py` (`VERITA_NOTA`, `confronta_verita`), `scraper_bandi/app/settings.py`
(`verifica_stato_usa_modello`), `scraper_bandi/app/fonte_ufficiale.py` (`esito_da_punteggio`),
`docs/bandi-monitor/RIPRESA.md`, `docs/contratto-db-bandi.md`; DB: `monitoraggio_riepilogo`, `bando` e `bando_evento`
del 661135, `pipeline_run`.

---

## 5. Cosa vedono il sito, l'API e BandoFit

Questo capitolo guarda i bandi dal lato di chi li legge. I lettori sono tre: la persona che apre edunews24.it, il
programma esterno che usa l'API pubblica, e BandoFit. La fotografia è dell'01/10/2026, verso le 11:30 (ora di Roma). I
numeri sono stati ricontrollati sul DB e sul sito tra le 12:00 e le 12:15 e non erano cambiati.

### 5.1 Un principio: chi legge non scrive

Sul database dei bandi scrivono il backend Python (la «pipeline» del sender, con la chiave di servizio) e il job orario
che gira dentro il database (§5.3). Le correzioni SQL a mano le lancia solo Michele.

Il sito e BandoFit si limitano a leggere. Usano la chiave pubblica, detta «anon». Questa chiave va trattata come
pubblica: è fatta per stare in chiaro ed è condivisa con BandoFit, che potrebbe metterla nel codice del browser (**non
verificato**). Su news1 la usano solo il server e le pagine SSR: nessuna isola React e nessuno script del browser
importa `supabase-bandi.ts`. Per questo il database deve difendersi da solo, con tre strumenti:

| Strumento | Cosa decide | Esempio |
|---|---|---|
| RLS (regole sulle righe) | quali righe vede chi usa la chiave pubblica | sulla tabella `bando` solo le righe «completed» con slug; su `bando_evento` solo gli eventi con cursore |
| Permessi sulle colonne | quali colonne vede | di `bando_controllo` si vedono 11 colonne (2 della migrazione 05 e 9 della 13). Chiedere un'altra colonna, per esempio `lettura_stato`, dà errore 42501 (verificato come anon) |
| Permessi sulle funzioni | quali funzioni può chiamare | non può chiamare le funzioni che scrivono (dai file SQL, non provato) |

Il motivo è semplice: se la chiave pubblica avesse il permesso di scrivere, chiunque la trovasse potrebbe modificare i
bandi.

Fonti: `src/lib/supabase-bandi.ts` e i suoi importatori (`src/components/bandi/ElencoBandi.astro`,
`src/components/liste/{CardBando,ListaBandi}.astro`, `src/lib/**`, `src/pages/bandi*.astro`, sitemap, `api-v1`),
`docs/contratto-db-bandi.md`, `backend/sql/bando_v11_02_tabelle_di_servizio.sql`,
`backend/sql/bando_v11_05_vista_pubblica.sql:136`, `backend/sql/bando_v11_13_stato_da_verificare.sql:371-382`, letture
come anon su `bando_controllo`.

### 5.2 Da dove legge il sito: la tabella o la vista

Il sito può leggere da due posti. Lo decide la variabile `BANDI_FONTE_LETTURA`. Il server la legge all'avvio, non al
build. Se manca, vale `PUBLIC_BANDI_FONTE_LETTURA`, che invece è fissata al build. La stessa scelta vale per l'API
(`api-v1/rotta.ts`).

| Valore | Da dove legge | Cosa ottiene |
|---|---|---|
| `bando` (predefinito) | la tabella grezza, filtrata a mano («completed» e slug presente) | un sito che funziona, ma più povero |
| `bando_pubblico` | la **vista pubblica** | solo i pubblicati non fusi, con lo stato già calcolato, l'ora di scadenza, la fonte ufficiale, l'ultimo controllo e il motivo «da verificare» |

Una **vista** è una tabella "virtuale": il database la ricalcola a ogni lettura partendo dalle tabelle vere. Il
vantaggio è che le regole (cosa è pubblicato, quale stato mostrare) stanno in un posto solo, nel database. Così il sito
e BandoFit vedono le stesse cose.

Oggi la produzione legge dalla vista. Lo si capisce dalla scheda pubblica, che mostra «controllata il 24 settembre
2026»: è un dato che esiste solo nella vista.

Due cose da sapere:
- un valore sbagliato della variabile riporta **in silenzio** alla tabella, senza errori e senza avvisi;
- non c'è un ripiego automatico. Se la vista si rompe, si rimette il valore a `bando` e si riavvia il sito.

Se il sito tornasse alla tabella:
- sparirebbero la fonte ufficiale, il box «Aggiornamenti» e i redirect degli slug storici;
- tornerebbero visibili i 6 doppioni già fusi. Sulla tabella la chiave pubblica legge 2.197 righe, cioè i 2.191
  pubblicati più i 6 fusi, che sono ancora «completed». I loro vecchi indirizzi risponderebbero 200 invece di 301;
- lo stato e il motivo «da verificare» sarebbero calcolati in modo più grossolano (solo con le date).

**Non verificato:** il valore reale della variabile sul server. Lo deduciamo dal comportamento della pagina pubblica.

Fonti: `src/lib/supabase-bandi.ts:23-25,348,367,418`, `src/lib/bandi/pubblicazione.ts:90-180`, `src/lib/api-v1/rotta.ts`,
`backend/sql/bando_v11_13_stato_da_verificare.sql:587-762`, letture come anon su `bando`, scheda pubblica in produzione.

### 5.3 Lo stato che vede il lettore: lo «stato effettivo»

Nel database ogni bando ha una colonna `stato_bando` con lo stato salvato. Il lettore però non vede quella colonna. Vede
lo **stato effettivo**, cioè lo stato ricalcolato in quel momento (le regole sono in §4.5).

La colonna salvata può restare indietro. Per esempio, un bando scade oggi alle 12:00. La colonna dice ancora «aperto»
finché qualcuno non la aggiorna. Lo stato effettivo invece guarda l'orologio e alle 12:01 dice già «chiuso».

In breve, nell'ordine: un **revocato** resta revocato; un **sospeso** resta sospeso anche a scadenza passata; con la
**scadenza passata** il bando è chiuso (nel giorno di scadenza conta l'ora, se c'è; senza ora resta aperto fino a
mezzanotte); un **in apertura** diventa aperto solo se la data di apertura è **verificata** ed è arrivata; negli altri
casi vale lo stato salvato.

Il **job orario** nel database (pg_cron «bandi-transizioni-orarie», al minuto 5 di ogni ora) rimette in pari la colonna
salvata. Chiude i bandi scaduti e apre quelli con apertura verificata, e ogni volta registra un evento. Questi eventi
non finiscono nel box «Aggiornamenti». Stanotte alle 00:05 ha chiuso 107 bandi. Nei due giorni prima aveva chiuso 11
bandi alle 00:05 del 30/09 e 2 alle 19:05 del 30/09. La garanzia del contratto è un ritardo di al massimo 65 minuti.
Che il job giri è verificato (§4.6): ultimo avvio riuscito, 0 fallimenti nelle 24 ore.

Oggi stato salvato e stato effettivo coincidono su tutti i 2.191 pubblicati:

| Stato | Bandi |
|---|---|
| Aperto | 1.168 |
| In apertura | 166 |
| Chiuso | 857 |
| Sospeso | 0 |
| Revocato | 0 |

Fonti: `src/lib/stato-bando.ts:378-424`, `scraper_bandi/app/stato_bando.py`, `tests/stato-bando/casi.json`,
`tests/estrazioni/stato-bando.test.ts:776-790`, `backend/sql/bando_v11_04_transizioni.sql:19,188-190`,
`docs/contratto-db-bandi.md:109,189`, letture su `bando_pubblico`, `bando_evento` (tipo `chiusura_automatica`, origine
`cron`) e `rpc/monitoraggio_job_orario`.

### 5.4 Il bollino «da verificare»

A volte lo stato mostrato non è certo. Per esempio: un bando era annunciato «in apertura dal 15 settembre», ma il 1°
ottobre nessuno ha ancora confermato che sia partito. Chiuderlo sarebbe un errore, e dire «aperto» sarebbe
un'invenzione. Si è scelta una terza via: lasciare lo stato com'è e aggiungere un **bollino**, «da verificare», con il
motivo. Le regole che decidono il motivo sono in §4.7; qui c'è come appare.

Il bollino **non cambia mai lo stato**. Un bando «In apertura · da verificare» resta fra gli «in apertura» in tutti i
contatori e i filtri.

| Motivo | Quando compare | Frase sotto il badge |
|---|---|---|
| `data_apertura_passata` | in apertura, con la data di apertura già passata e non verificata | «L'apertura era annunciata per il …: l'avvio non risulta ancora confermato sulla fonte ufficiale.» |
| `smentito_dalla_fonte` | la pagina ufficiale dice un altro stato | in apertura: «La pagina ufficiale non lo indica più come in arrivo: lo stato è in verifica.»; aperto: «La pagina ufficiale dell'ente non lo indica più come aperto: verifica prima di presentare domanda.» |
| `previsione_scaduta` | in apertura, ma il periodo previsto dal calendario dell'ente è finito | «Il periodo di apertura previsto dal calendario è passato senza un avviso pubblicato.» |
| `senza_conferma` | nessuna conferma recente dalla pagina ufficiale | in apertura: «L'apertura è annunciata ma non è confermata sulla fonte ufficiale: verifica sul sito dell'ente.»; aperto: «Non abbiamo una conferma recente dalla pagina ufficiale dell'ente: verifica prima di presentare domanda.» |
| `termine_passato` | aperto senza scadenza, ma una fonte indica un termine già passato | una frase diversa per fonte (calendario ufficiale, pagina dell'ente, testo del bando, aggregatore) |

**Il punto chiave di oggi.** Quasi tutti i motivi richiedono che il bando sia stato "esaminato in attivo": la verifica
automatica deve aver letto la pagina ufficiale e scritto il risultato. Oggi la verifica è **in ombra**: lo conferma la
riga del giro di avvio delle 10:10 in `pipeline_run`, che riporta `modalita: ombra`. Quindi l'unico motivo che oggi può
comparire è `data_apertura_passata`, che dipende solo dalle date.

Oggi ce l'hanno **2 bandi**: 2308 (apertura annunciata per il 6 luglio) e 2955 (31 maggio). Il sito mostra «In apertura
· da verificare» (verificato sulla scheda di 2308).

Tre dettagli:
- un motivo incompatibile con lo stato mostrato viene nascosto. Per esempio, un motivo del ramo «aperto» su un bando
  che il sito mostra chiuso;
- `senza_conferma` sugli aperti senza scadenza compare dall'**8° giorno** dopo la pubblicazione: fino al 7° compreso
  non c'è. `docs/api-v1.md` dice «dal 7° giorno»: è un errore di un giorno nella documentazione, e vale il codice;
- sugli «in apertura» lo stesso `senza_conferma` ha una grazia di 3 giorni dalla pubblicazione.

All'01/10 la verifica non ha ancora scritto nessuna lettura: in `bando_controllo` le colonne `stato_letto`,
`termine_indicato`, `esaminato_attivo_at` e `lettura_stato` sono vuote su tutte le 4.620 righe. La fase «controlli»
gira la prima volta al giro delle 18 di oggi.

Fonti: `src/lib/stato-bando.ts:440-462,542-617` (motivi, rami, grazie, `motivoVisibile`), `src/lib/bandi/testi-stato.ts`
(frasi), `src/lib/bandi/aspetto.ts:86-92`, `scraper_bandi/app/verifica_stato.py:1-28,807-866`,
`backend/app/bandi_pipeline.py:384-419`, `backend/sql/bando_v11_13_stato_da_verificare.sql:740-761`, `docs/api-v1.md:247`,
letture su `bando_pubblico`, `bando_controllo` e `pipeline_run` (righe 149-150).

### 5.5 La lista `/bandi`

La lista è costruita dal server e funziona anche senza JavaScript. Tutto quello che il lettore sceglie sta
nell'indirizzo della pagina (filtri, ordinamento, vista e numero di pagina). Un indirizzo così si può copiare,
condividere e indicizzare, e mostra sempre la stessa cosa.

- **24 bandi per pagina**: con la griglia a 3 colonne ogni pagina chiude la riga. `?page=1` rimanda con un 301
  all'indirizzo senza numero. Una pagina oltre l'ultima risponde 404.
- **Filtri:**
  - stato (Aperti, In apertura, Chiusi);
  - regione, settore, beneficiario, codice ATECO, programma, modalità, tipologia;
  - importo minimo e massimo;
  - intervallo di scadenza;
  - ricerca libera;
  - «in scadenza», cioè gli aperti che scadono fra oggi e i prossimi 15 giorni (oggi sono 207).
- **Ordinamento:** scadenza più vicina (predefinito: prima le scadenze future, poi i bandi senza scadenza, poi quelli
  scaduti), importo, più recenti.
- **Vista** a elenco o a griglia.
- Ogni combinazione con filtri è `noindex`. Un solo filtro su una dimensione che ha la sua pagina filtro rimanda (302)
  a quella pagina.
- Le scelte «Sospeso» e «Revocato» compaiono solo se `BANDI_STATI_ESTESI=true`. In produzione non compaiono
  (verificato sulla pagina; il valore della variabile non è verificato).

**La card di un bando** mostra:
- il **badge** con lo stato effettivo, più « · da verificare» se c'è un motivo;
- la **riga di scadenza**: «Scade il …» con «tra N giorni / scade domani / scade oggi» per un aperto, «Scade il …» senza
  conto alla rovescia per un in apertura, «Scaduto il …» per un chiuso, altrimenti «Scadenza: …».

**I contatori in testa alla lista** vengono dalla vista, attraverso una cache in memoria di 15 minuti, e oggi coincidono
con il DB: Aperti 1.168, In apertura 166, Chiusi 857. Sotto «In apertura» c'è la nota «di cui 2 da verificare»
(verificato).

Fonti: `src/pages/bandi.astro`, `src/lib/liste/bandi.ts:24-180,270-283`, `src/config/pagine-filtro.ts:130-134`,
`src/lib/liste/parametri.ts:152`, `src/lib/bandi/aspetto.ts:115`, `src/lib/bandi/testi-stato.ts` (`rigaScadenza`,
`opzioniStato`), `src/components/liste/CardBando.astro`, pagine `/bandi` e `/bandi?stato=sospeso` in produzione.

### 5.6 La scheda di un bando (`/bandi/<slug>`)

**1. Prima di tutto, l'indirizzo.** Lo slug è la parte finale dell'indirizzo, per esempio `/bandi/pronti-export-…`. La
scheda cerca prima lo slug fra i pubblicati. Solo se non lo trova guarda la mappa degli slug storici e delle fusioni:

| Caso | Risposta | Perché |
|---|---|---|
| slug di un doppione fuso, o slug vecchio | 301 verso il bando principale (solo se quello è ancora pubblicato) | chi aveva salvato il vecchio link arriva comunque al posto giusto |
| slug ritirato | 410 (vince su una fusione) | il bando è stato tolto di proposito |
| slug sconosciuto | 404 | non è nella vista né nella mappa |
| database in errore | 503, con `Retry-After` e senza `noindex` | errore temporaneo: i motori di ricerca riprovano più tardi |

Il 301 è verificato in produzione (`business-opportunities-manifestazione-interesse-pmi-lazio-2`). Le fusioni fatte
finora sono 6, tutte del 30/09 alle 12:27, fatte a mano («doppione verificato il 29/09 sulla fonte ufficiale»). Hanno 6
righe gemelle in `bando_slug_storico`, tutte con esito 301.

**2. Lo stato.** La scheda mostra lo stato effettivo, con un'eccezione: se fra gli eventi visibili e verificati c'è una
sospensione o una revoca, vince l'evento. È quindi una **seconda fonte dello stato**, e RIPRESA §4.1 i, punto 3, la
segnala come rischio. Oggi non ci sono sospesi né revocati, quindi non ha effetti.

**3. La frase sotto il badge.** C'è sempre e spiega lo stato a parole:

| Stato | Frase |
|---|---|
| Revocato | «Il bando è stato revocato: non è più possibile presentare domanda.» |
| Sospeso | «Il bando è sospeso: le domande restano ferme fino a nuova comunicazione dell'ente.» |
| Chiuso | «I termini sono scaduti il …», seguito da «come verificato sulla fonte ufficiale» oppure «la data è quella indicata dalla fonte e non è stata verificata sulla pagina ufficiale». Senza data: «I termini per partecipare sono chiusi.» Con la scadenza ancora futura: «I termini sono stati chiusi prima della scadenza indicata (…).» |
| In apertura, data futura verificata | «Apre il …, come verificato sulla fonte ufficiale.» |
| In apertura, data futura non verificata | «L'apertura è annunciata per il …: la data non è ancora verificata sulla pagina ufficiale.» |
| In apertura, senza data | «La data di apertura non è stata comunicata dalla fonte.» |
| In apertura, data passata | «L'apertura era annunciata per il …: l'avvio non risulta ancora confermato sulla fonte ufficiale.» |
| Aperto con scadenza | «Si può presentare domanda fino al … [alle hh:mm]», con la stessa coda «verificata / non verificata» del chiuso |
| Aperto senza scadenza | «Sportello aperto: la fonte non indica una data di scadenza.» |

Se c'è un motivo «da verificare», la frase del motivo (tabella in §5.4) sostituisce quella standard. Per
`data_apertura_passata` la frase è proprio quella della riga «data passata».

Quando la verifica sarà attiva, la frase degli aperti senza scadenza potrà diventare più precisa, per esempio «la
pagina ufficiale lo indicava ancora aperto il …», oppure «il calendario ufficiale / la pagina dell'ente / un portale
aggregatore indica come termine il …».

**4. Il pulsante di candidatura.** Compare solo se il bando non è chiuso, sospeso o revocato. Punta alla destinazione più
affidabile disponibile, in quest'ordine:
1. il modulo di candidatura: una riga «candidatura» di `bando_link`, oppure il link estratto dalla pagina
   (`link_candidatura_source = 'extracted'`). Etichetta «Vai al modulo di candidatura»;
2. la fonte ufficiale trovata. Se è un portale pubblico l'etichetta è «Consulta il bando sul portale pubblico»,
   altrimenti (pagina dell'ente, atto o tipo vuoto) è «Apri la pagina ufficiale del bando».

**Non punta mai a un aggregatore.** Un aggregatore è un sito terzo che ricopia bandi di altri (per esempio
ObiettivoEuropa). Il lettore deve candidarsi alla fonte vera. Se non c'è nessuna destinazione affidabile, compare la
frase «Non abbiamo ancora un link ufficiale verificato per la candidatura» (è il caso di 2308).

**5. La riga della fonte.** «Fonte ufficiale: host (tipo) — verificata il … · controllata il …», oppure «Fonte ufficiale
in verifica · controllata il …». Sui pubblicati, oggi, la fonte ufficiale è:
- **trovata** su 620;
- **in verifica** su 1.050;
- **non trovata** su 521.

Su 259 delle «trovate» il tipo è vuoto. Succede perché l'host è riconosciuto solo per la sua forma (per esempio
`regione.*.it`, `*.gov.it`, `*.camcom.it`). È voluto, e non vuol dire «non ufficiale»: anche per questi la scheda
mostra il pulsante verso la pagina ufficiale. Delle altre trovate, 348 sono «ente» e 13 «portale pubblico».

**6. Gli allegati.** Vengono prima dai link verificati (`bando_link`, righe di tipo «allegato» che la RLS lascia
leggere). Se mancano, vengono dalla vecchia colonna `allegati`. In entrambi i casi passano dal filtro che toglie gli
aggregatori.

**7. Il box «Aggiornamenti».** Mostra gli eventi resi visibili (`in_aggiornamenti`), al massimo 20 per scheda. Oggi in
tutto sono 52 eventi su 51 bandi: 28 proroghe, 17 aperture, 4 rettifiche, 1 FAQ, 1 nuovo allegato, 1 chiusura.

Fonti: `src/pages/bandi/[slug].astro:36-320`, `src/lib/supabase-bandi.ts:363-466`, `src/lib/bandi/slug-storico.ts`,
`src/lib/bandi/aggiornamenti.ts:151-172`, `src/lib/bandi/testi-stato.ts` (`sottotestoStato`, `testoFonteUfficiale`),
`src/lib/bandi/cta.ts`, `src/lib/bandi/contenuto.ts:229-233`, letture su `bando_fusione`, `bando_slug_storico`,
`bando_evento`, `bando_pubblico`, scheda di 2308 in produzione.

### 5.7 Pagine filtro e sitemap

**Pagine filtro.** Sono indirizzi come `/bandi/regione/marche` o `/bandi/programma/…`. Per i bandi esistono solo per
regione, settore, programma e tipologia, e solo se il valore ha **almeno 5 bandi** (il codice confronta con `>= 5`).
Sotto soglia la risposta è un vero 404. Il motivo: una pagina con 1 o 2 bandi è "sottile", e Google tende a giudicare
male un sito pieno di pagine quasi vuote. Le regole stanno in un solo file, `src/config/pagine-filtro.ts`. I conteggi
hanno una cache di 15 minuti.

**Sitemap.** Sono gli elenchi di indirizzi che diamo ai motori di ricerca.
- Le schede dei bandi stanno in blocchi da 1.000 indirizzi. Oggi sono 3 blocchi (1.000 + 1.000 + 191 = 2.191 schede), e
  il quarto risponde 404.
- **Anche i chiusi restano nelle sitemap**, e quindi restano indicizzabili.
- `sitemap-pagine-filtro.xml` contiene 136 indirizzi dei bandi: 132 pagine filtro (89 settori, 20 regioni, 19
  programmi, 4 tipologie) più i 4 indici per dimensione (`/bandi/regione`, `/bandi/settore`, `/bandi/programma`,
  `/bandi/tipologia`).
- La data di ultima modifica di ogni scheda si muove solo per un cambiamento visibile al pubblico
  (`ultimo_cambiamento_at` della vista). Così non diciamo a Google «è cambiato» quando abbiamo aggiornato solo un dato
  interno. Anche una chiusura del job orario conta come cambiamento pubblico (lastmod del 30/09 alle 22:05 UTC su
  alcune schede).
- Le sitemap sono oggi l'**unico** modo in cui i motori scoprono i bandi nuovi, perché IndexNow non li notifica (§3.16).

Fonti: `src/config/pagine-filtro.ts:130-163`, `src/lib/pagine-filtro.ts:25`, `src/lib/corpus.ts`,
`src/lib/bandi/pubblicazione.ts:106-111`, `src/pages/sitemap-bandi/[pagina].xml.ts`,
`src/pages/sitemap-pagine-filtro.xml.ts`, sitemap in produzione.

### 5.8 L'API pubblica (versione 1.2)

L'API serve a chi vuole i nostri bandi in forma di dati, non di pagina web. È in sola lettura e senza chiave. Ha un
limite di 60 richieste al minuto. La cache dichiarata è di 5 minuti sugli elenchi e di 15 minuti sul singolo bando
(`s-maxage`). In produzione risponde «version: 1.2» (verificato).

**Indirizzi:** `/api/v1/bandi` (elenco), `/api/v1/bandi/{id}` (un bando), più i feed `/api/v1/feeds/bandi.json` (JSON
Feed) e `/api/v1/feeds/bandi.xml` (RSS).

**Cosa contiene ogni bando:**

| Gruppo | Campi |
|---|---|
| Identità | `type`, `id`, `slug`, `url`, `title`, `summary`, `section` |
| Date | `published_at` (la data in cui l'abbiamo inserito), `updated_at` (dalla vista: ultimo cambiamento pubblico), `deadline_on`; `deadline_at` è **sempre vuoto** per i bandi |
| Stato | `status`: `open`, `upcoming`, `closed`, `suspended`, `revoked` |
| Luogo | `regions`, `national` |
| Dettagli (`details`) | titolo breve, ente, area, temi, tipo, programma, modalità di finanziamento, settori, beneficiari, codici ATECO, importo totale e massimo per progetto, data di apertura, data di pubblicazione alla fonte |
| Aggiunti nella 1.1 | `official_source`, `opens_on_verified`, `deadline_verified`, `last_checked_at` |
| Aggiunto nella 1.2 | `stato_da_verificare` (il motivo del bollino) |

**Cosa non esce mai:** i link interni dello scraper (`link_bando`), gli allegati, `raw_data` e il testo integrale.
L'unico URL esterno è quello di `official_source`. Le colonne lette sono elencate una per una in `api-v1/colonne.ts`,
così nessun campo nuovo esce per sbaglio.

**Esempio verificato:** `/api/v1/bandi/2308` risponde `status: upcoming`, `stato_da_verificare: data_apertura_passata`,
`official_source: null` (la fonte è in verifica).

**Tre limiti da conoscere:**
1. **Lo stato dell'API è calcolato in modo più semplice di quello del sito.** Usa la colonna salvata più la data, senza
   l'ora di scadenza e senza l'apertura verificata. Esempio: un bando scade oggi alle 12:00. Alle 12:30 il sito dice
   «chiuso», l'API dice ancora `open` fino al passaggio del job orario (13:05). Allo stesso modo, un'apertura verificata
   appena raggiunta è «aperto» sul sito e `upcoming` nell'API. Il motivo invece viene dalla vista: in quella finestra
   stato e motivo possono non combaciare (il motivo incompatibile viene nascosto).
2. **L'ora di scadenza non arriva ai client.** `deadline_at` è sempre vuoto, anche per i 42 bandi pubblicati che l'ora
   ce l'hanno.
3. **Chi sincronizza «solo i cambiati» perde i cambi di motivo.** La guida consiglia `updated_since`, ma il motivo «da
   verificare» può cambiare (per esempio quando una data di apertura passa) senza che `updated_at` si muova.

Fonti: `src/lib/api-v1/costanti.ts` (`VERSIONE_API`, `RATE_LIMIT_*`), `src/lib/api-v1/http.ts:19-27`,
`src/lib/api-v1/colonne.ts`, `src/lib/api-v1/mappa-opportunita.ts:384-467`, `src/lib/api-v1/feed.ts:24-36`,
`src/lib/api-v1/testi-doc.ts:140`, `docs/api-v1.md`, `/api/v1` e `/api/v1/bandi/2308` in produzione.

### 5.9 BandoFit: cosa legge e cosa gli è garantito

BandoFit è un prodotto separato che legge lo stesso database dei bandi con la chiave pubblica. Il patto fra noi (il
"produttore") e chi legge (i "consumatori") è scritto in `docs/contratto-db-bandi.md`. La frase centrale del patto: **si
legge la vista `bando_pubblico`, e lo stato vero è lo stato effettivo, non la colonna salvata.**

**Cosa legge, secondo contratto e RIPRESA.** Dal 30/09 BandoFit è al passo «c1» della fase (c) e legge solo:
- `bando_pubblico`, la vista;
- `bando_link`, i link verificati;
- `bando_slug_storico` e `bando_fusione`, cioè dove sono finiti i bandi fusi o rinominati.

Non legge più la tabella `bando`. Si accorge dei bandi nuovi seguendo il **cursore** degli eventi «pubblicazione». Il
cursore è un numero che cresce sempre: basta ricordarsi l'ultimo letto e chiedere quelli successivi. Ogni ora riallinea
i bandi fusi. Il passo successivo, «c2», toglie i ripieghi sulle colonne vecchie: solo dopo il c2 si propone la 07.

**Non verificato:** non abbiamo il codice di BandoFit.

**Cosa gli è garantito** (dal contratto):

| Garanzia | In parole semplici |
|---|---|
| id mai riusati, righe mai cancellate | un id salvato oggi indicherà sempre lo stesso bando |
| slug dei pubblicati congelati | un indirizzo salvato non smette di funzionare |
| mappa di fusioni e slug storici sempre leggibile | se un bando è stato fuso, si sa in quale |
| stato effettivo sempre presente, calcolato sul fuso di Roma | non serve rifare i conti |
| nessun link ad aggregatori nelle colonne pubbliche | i link portano alle fonti vere |
| registro eventi con cursore sempre crescente | non si perdono eventi |
| job orario in ritardo al massimo di 65 minuti | la colonna salvata si allinea entro un'ora e poco più |
| limiti di lettura: 3 secondi per richiesta (`statement_timeout` di anon), al massimo 1.000 righe | bisogna paginare |
| avviso scritto prima di ogni cambio incompatibile | niente sorprese |
| un avviso prima di attivare le fusioni automatiche, le sospensioni e le revoche e la verifica dello stato: dal giro 3 un solo messaggio, mandato prima del deploy, senza i 7 giorni di preavviso promessi dal giro 2 (decisione di Michele dell'01/10, §6.2 del contratto) | BandoFit sa che cosa arriva e lo segue con il cursore degli eventi e con `bando_fusione` |

Le 52 fusioni automatiche attese sono state ricontate oggi con `gemelli --dry-run`: 43 per URL e 9 per riga di
calendario, 52 gruppi di due righe, nessuna catena. Altre 33 coppie sono state scartate per prudenza.

**Dove la promessa oggi non regge.** Finché la migrazione 07 non è applicata, la chiave pubblica legge ancora la tabella
`bando` con **tutte le colonne**: 2.197 righe (i 2.191 pubblicati più i 6 doppioni fusi, non le 5.194 righe totali),
compresi `raw_data` (1.878 righe) e `link_bando` verso ObiettivoEuropa (1.772). Il contratto lo ammette come fase di
passaggio, ma contraddice la promessa «nessun link ad aggregatori nelle colonne leggibili».

La 07 è bloccata anche dal nostro sito, che chiede ancora tre colonne vecchie (`link_candidatura`,
`link_candidatura_source`, `allegati`). E sostituirle oggi non basta: dei 104 bandi con un modulo di candidatura
estratto, solo 1 ha la riga corrispondente in `bando_link` (che oggi ha in tutto 1 sola riga «candidatura»
pubblicabile), e 151 dei 160 bandi con allegati perderebbero gli allegati.

**Non verificato:**
- che la seconda parte del messaggio a BandoFit (stato da verificare, eventi, fusioni) sia stata inviata, e quando. Da
  questa data dipende la data minima di attivazione;
- che gli id non siano mai stati riusati e nessuna riga cancellata: con sole letture non si può provare;
- i limiti di 3 secondi e 1.000 righe: presi dal contratto, non misurati direttamente.

Fonti: `docs/contratto-db-bandi.md:109,189,440,499-511,569,612,669-676`, `docs/bandi-monitor/RIPRESA.md`,
`backend/sql/bando_v11_07_fase_d.sql`, `src/lib/supabase-bandi.ts:283-291`, `scraper_bandi/app/gemelli.py:1312-1440`,
`gemelli --dry-run` (sola lettura), letture come anon su `bando`, `bando_link`, `bando_pubblico`.

### 5.10 Cose che oggi non tornano, lato pubblico

| Cosa | Effetto per chi legge | Gravità |
|---|---|---|
| 426 aperti senza scadenza (36% degli aperti; 285 da ObiettivoEuropa, 323 pubblicati a giugno) | restano «aperti» per sempre, perché il job orario non ha una data per chiuderli. In ombra non hanno bollino. Su un campione controllato a mano, RIPRESA stima che il 16% sia già chiuso (stima non ricontrollata) | media |
| 163 «in apertura» su 166 senza data di apertura (133 vengono da calendari di preavviso regionali e nazionali) | restano «in apertura» a tempo indefinito, senza bollino finché si è in ombra | media |
| Doppioni ancora visibili | 52 fusioni automatiche attese all'attivazione (ricontate), più 41 coppie da fondere a mano (numero di RIPRESA, non ricontato) | media |
| 10 bandi pubblicati senza contenuto | la scheda non mostra il testo né un avviso; resta solo la descrizione breve, se c'è | bassa |
| `/bandi?stato=sospeso` | mostra il filtro «Stato: Sospeso» sopra una lista **non** filtrata (2.191 bandi trovati). La pagina è noindex | bassa |
| Lista `/bandi` con il database in errore | risponde 200 con «Elenco momentaneamente non disponibile», mentre la scheda risponde 503 | bassa |
| API: stato più semplice, ora mai esposta, `updated_since` che non vede i cambi di motivo | §5.8 | bassa |
| `BANDI_FONTE_LETTURA` e `BANDI_STATI_ESTESI` assenti da `.env.example` | chi installa il sito da zero non sa che esistono | bassa |

Fonti: letture su `bando` e `bando_pubblico`, `src/lib/bandi/contenuto.ts:229-233`, `src/pages/bandi.astro`,
`src/components/liste/ListaBandi.astro:29`, `src/lib/bandi/filtro-stato.ts`, `src/lib/api-v1/mappa-opportunita.ts`,
`.env.example`, `docs/bandi-monitor/RIPRESA.md` §4.1 e §4.5 (riga 1540 per il 16%).

---

## 6. I controlli

### 6.1 Perché servono controlli

La pipeline dei bandi gira da sola quattro volte al giorno (00, 06, 12, 18, ora di Roma), più un giro di avvio a ogni
riavvio del sender. Nessuno la guarda mentre lavora. Può fermarsi per molte ragioni: il credito del modello finisce, un
sito cambia, il server si riavvia, il database non risponde.

I controlli servono a una cosa sola: **accorgersi che qualcosa non va prima che se ne accorga un lettore.**

Oggi l'unico strumento di misura è il comando `salute`, che però non gira da solo: va lanciato a mano (§6.8). Il resto
sono righe `[ALLARME]` scritte nel journal dai singoli passi, e il diario `pipeline_run` (§3.3.4).

### 6.2 Il comando `salute`

```bash
cd ~/projects/news1/scraper_bandi
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app salute          # leggibile
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app salute --json   # per programmi
```

**Cosa fa:**
1. legge la configurazione (`scraper_bandi/.env`);
2. misura il database in sola lettura: giri, lucchetti, eventi, fonti, consumo, bandi fermi, e quanto ci mette a leggere
   una pagina della vista (come anon solo se l'ambiente ha la chiave anon, altrimenti con la chiave di servizio);
3. chiede lo stato del job orario a `monitoraggio_job_orario`, una funzione di sola lettura della migrazione 12, in GET;
4. sul server chiede a systemd se il servizio del sender è attivo e quante volte si è riavviato;
5. a ogni anomalia assegna un **codice** con un **livello**:
   - **allarme**: c'è un problema vero da guardare;
   - **avviso**: da tenere d'occhio.

**Cosa stampa:** le righe `[ALLARME]` e `[AVVISO]` (sullo standard error), poi «salute: tipi attivi del monitor: …» e
«salute: codici: …».

**Come finisce:** **exit 1 se c'è almeno un allarme**, altrimenti 0.

Si può lanciare anche dal Mac, perché fa solo letture. L'avviso `non_misurato` c'è **sempre**, ovunque: i crediti
residui di Firecrawl e le schede ObiettivoEuropa con la sezione dei link non si misurano mai dal DB, e in ombra non si
misura neanche lo stato da verificare. Sul Mac si aggiunge il servizio (systemd non c'è).

**Perché i codici.** Il testo di un messaggio può cambiare, il codice no. Un codice stabile si può cercare nella
documentazione, confrontare nel tempo, e un giorno mostrare in un pannello. L'elenco dei codici è chiuso nel codice: un
codice fuori elenco fa fallire il programma con un errore.

Fonti: `scraper_bandi/app/__main__.py:1116-1153` (`_cmd_salute`), `scraper_bandi/app/sorveglianza.py:128-183`
(`fotografa`), `scraper_bandi/app/telemetria.py:269-284,313-375,477-595`, `scraper_bandi/app/db.py:2407-2646`
(`misure_salute`), `scraper_bandi/app/db.py:3036-3061` (`job_orario`, in GET).

### 6.3 I codici del produttore (il sender che fa i giri)

| Codice | Livello | Significa | Cosa fare |
|---|---|---|---|
| `produttore_fermo` | allarme | nessun giro delle 00/06/12/18 completato da 7 ore (11 se un giro è in corso) | `systemctl status edunews-bandi-sender` e il journal di oggi; se il servizio è su ma non gira, cercare un lucchetto orfano |
| `riavvii_ripetuti` | allarme | almeno 3 giri di avvio in 6 ore, oppure NRestarts di systemd cresciuto di almeno 2 in 6 ore (questa seconda misura richiede la memoria di `sorveglia`, §6.8) | dopo un deploy con più riavvii è normale per 6 ore; altrimenti cercare nel journal «Errore fatale» e «morto a metà giro» |
| `servizio_non_attivo` | allarme | systemd dice fallito, spento o in attesa di riavvio | `journalctl -u edunews-bandi-sender -n 200`, capire l'errore, poi **un solo** restart |
| `passo_degradato:estrazione` | allarme | il preprocess ha sbagliato tutti i bandi dell'ultimo giro | quasi sempre è il credito Anthropic; i bandi ripartono da soli al giro dopo |
| `passo_degradato:arricchimento` | allarme | l'enrich ha lavorato bandi e non ne ha salvato nessuno | journal «STEP enrich» |
| `passo_degradato:redazione` | allarme | almeno 3 bandi da redigere e nessuna scheda prodotta | journal «STEP seo» e i motivi nella riga del giro |
| `ingresso_guasto` | allarme | **tutte** le fonti tentate sono in errore | è la rete o il DNS del server: provare `curl -I` verso una fonte qualsiasi |
| `fermi_in_lavorazione` | avviso | bandi entrati negli ultimi 7 giorni e fermi in `processed` o `enriched` da oltre 13 ore | di solito si sblocca al giro dopo; se cresce, journal di enrich e seo. L'arretrato vecchio dei `processed` chiusi non conta |
| `passi_ripetuti_non_ok` | allarme | lo stesso passo non è riuscito in due giri di fila | journal «STEP <nome> FAILED» o «NON PARTITO» |
| `eventi_non_applicati` | allarme | l'ultimo monitor ha eventi ammessi ma non applicati | il journal stampa il comando `applica-eventi --ids … --attivo`; lanciarlo prima con `--dry-run` |
| `eventi_non_scritti` | allarme | il monitor o la verifica non sono riusciti a registrare eventi | journal del monitor o di «STEP verifica_stato», riga con il codice d'errore |
| `eventi_non_leggibili` | avviso | eventi applicati ma senza cursore, quindi invisibili nel box «Aggiornamenti» | `applica-eventi --ids … --attivo` con gli id del journal |
| `job_orario` | allarme | il job orario non riesce da 3 ore, non ha mai un esito riuscito, o è fallito almeno 2 volte in 24 ore | nel SQL Editor: `select status, return_message, start_time from cron.job_run_details order by start_time desc limit 5;` |
| `riepilogo_non_valido` | allarme | lo scrive solo `sorveglia`, quando il riepilogo non passa i controlli | è un difetto del codice, da correggere |

Il nome del servizio `edunews-bandi-sender` è il predefinito del codice. Quello reale sul server non è stato verificato.

Fonti: `scraper_bandi/app/telemetria.py:598-912`, `scraper_bandi/app/db.py:2548-2570,2655-2665`,
`scraper_bandi/app/sorveglianza.py:43`, `scraper_bandi/app/monitoraggio.py:1545`, `docs/bandi-monitor/RIPRESA.md` §3.1.

### 6.4 I codici della verifica dello stato (giro 2, percorso A)

Riguardano il nuovo controllo che rilegge le pagine ufficiali (§3.14, §4.7).

**Dopo un deploy sono attesi due avvisi, che si spengono da soli:**
- `verifica_stato_ferma` («non ancora eseguita»), fino al primo giro delle 06 o delle 18: oggi fino alle 18;
- `indicepa_non_aggiornato`, fino al primo import riuscito, che parte al giro delle 06 se nel mese non ce n'è ancora uno:
  domani 02/10 alle 06. Il giro delle 06 di oggi girava ancora con il codice vecchio.

| Codice | Livello | Significa | Cosa fare |
|---|---|---|---|
| `verifica_stato_ferma` | allarme (avviso se il passo non ha mai girato) | nessun passo della fase controlli riuscito da 26 ore, cioè due giri persi; un giro fermato dal tetto di tempo conta come riuscito | journal «STEP verifica_stato»; se il passo è «saltato» per migrazione assente, manca la 13 |
| `leggibile_non_letto` | avviso | candidati con una pagina leggibile non riletti da oltre 16 giorni (la cadenza va da 3 a 14 giorni secondo il caso) | di solito il tetto di 40 letture per giro è basso; guardare candidati e letti nella riga del giro |
| `lettura_non_verificante` | avviso | un link accorciato (bit.ly…) ha portato su un host non riconosciuto | niente d'urgente; se l'host è davvero l'ente e si ripete, aggiungerlo a `dominio_ufficiale` |
| `estrattore_muto:<lettore>` | allarme | un lettore dedicato a un ente ha fatto almeno 5 letture in 7 giorni senza un solo esito | quasi sempre l'ente ha cambiato sito: confrontare una pagina con quella salvata nei test e correggere il lettore |
| `freno_chiusure:<lettore>` | avviso | nell'ultimo passo il freno ha trattenuto chiusure di quel lettore (il freno scatta su 7 giorni mobili, con almeno 5 passaggi e più della metà delle letture) | con `report-verifica-stato --json` controllare 2-3 bandi a mano: se sono chiusi davvero va bene, altrimenti il lettore è rotto |
| `prosa_non_riscritta` | avviso | schede con date nuove ma testo ancora vecchio | `rigenera --dry-run`, poi `--attivo`, nella finestra sicura |
| `aperti_senza_conferma` | avviso | più del 60% degli aperti senza scadenza ha `senza_conferma`; si misura solo con la verifica attiva | dopo l'attivazione è atteso per 2-3 settimane; se resta, servono lettori per gli host più frequenti |
| `ingresso_trattenuti` | avviso | **nel codice:** più di 10 righe senza appiglio trattenute nell'ultimo ingresso, oppure più di 10 bandi rilasciati «a tempo» nelle righe d'ingresso degli ultimi 7 giorni | guardare le righe ferme; spesso sono PDF di programma, da rifiutare a mano o lasciare |
| `indicepa_non_aggiornato` | avviso | nessun import di IndicePA (l'elenco ufficiale degli enti pubblici) riuscito da oltre 40 giorni, o mai registrato | journal del giro delle 06 del primo del mese |
| `indicepa_import_anomalo` | avviso | l'ultimo import ha trovato meno di 15.000 righe utili o ne ha scartate più del 20%, e in quel caso non ha scritto niente | scaricare il file a mano e controllare le colonne |
| `vista_lenta` | allarme (misurata come anon) / avviso (con la chiave di servizio) | leggere una pagina della vista pubblica richiede più di 2 secondi | avvertire subito lo sviluppatore: per il sito il limite è 3 secondi, oltre va in errore. Oggi, dal Mac con la chiave di servizio: 63 ms |
| `configurazione:verifica_stato` | allarme | una variabile `VERIFICA_STATO_*`, `INGRESSO_*`, `GEMELLI_*` o `INDICEPA_URL` ha un valore non valido ed è tornata al default | correggere `scraper_bandi/.env` e riavviare |

**Attenzione su `ingresso_trattenuti`:** RIPRESA §3.1 (riga 537) descrive la seconda condizione in un altro modo («più
della metà dei trattenuti in 7 giorni pubblicata a tempo scaduto»). Vale il codice.

Fonti: `scraper_bandi/app/telemetria.py:914-1089`, `scraper_bandi/app/db.py:2718-2720,2795-2825`,
`scraper_bandi/app/verifica_stato.py:88-130,523-552,633-681`, `scraper_bandi/app/fonte_ufficiale.py:3161-3229`,
`backend/app/bandi_pipeline.py:331-341,512-567`, `docs/bandi-monitor/RIPRESA.md:507-538`.

### 6.5 I codici di prima del giro 2

| Codice | Livello | Significa | Cosa fare |
|---|---|---|---|
| `monitor_fermo` | allarme | nessun monitor di regime riuscito da 24 ore | journal «STEP monitor» alle 06 e 18; tetti, lucchetto, credito |
| `misure_non_disponibili` | allarme | il database non ha risposto | una volta è la rete; se dura, controllare il progetto Supabase |
| `ingresso_fermo` | allarme | bandi fermi in `scraped` da oltre 13 ore | credito Anthropic, journal «STEP preprocess» |
| `classificazione_non_disponibile` | allarme o avviso | classificazioni del monitor fallite (allarme se le fallite sono almeno quante le riuscite) | credito Anthropic |
| `accesso_fonte_riservata` | allarme | login di ObiettivoEuropa fallito, oppure le fonti 449, 450, 451 in errore negli ultimi due giri | journal «SessioneOEError»; credenziali in `scraper_bandi/.env` |
| `limite_di_spesa` | allarme | tetto di spesa raggiunto in due giri di fila | alzare un tetto è una decisione, non un riflesso |
| `consumo_mensile_alto` | allarme | consumo del mese pari o superiore all'80% del tetto | RIPRESA §3.7 (ma vedi §6.6: il consumo registrato è incompleto) |
| `credito_ricerca_basso` | allarme | crediti di ricerca sotto il 15% | oggi non si misura dal DB |
| `scorta_piano_bassa` | allarme | il residuo del piano Firecrawl è meno di 3 volte il tetto mensile | oggi non si misura: nessuno valorizza quel dato |
| `fonti_da_verificare` | allarme | oltre il 30% dei pubblicati negli ultimi 7 giorni ha la fonte «in verifica» (servono almeno 10 bandi) | **acceso oggi**; secondo RIPRESA da settimane (non verificato). Resta finché non si decide RIPRESA §4.1 c |
| `controlli_non_riusciti` | allarme | più del 2% dei bandi vivi ha almeno 5 controlli falliti di fila | host morti o bloccati (oggi 0) |
| `schede_senza_sezione` | avviso | meno dell'80% delle schede ObiettivoEuropa ha la sezione dei link | oggi non si misura dal DB |
| `modello_fuori_listino` | avviso | un modello configurato non ha prezzo | aggiornare il listino in `bilancio.py` |
| `non_misurato` | avviso | qualcosa non si è potuto misurare | è sempre presente (§6.2) |
| `configurazione:modalita` | allarme | `MONITOR_MODALITA=attivo` senza `INDEXNOW_API_KEY` | correggere il file e riavviare il sender |
| `configurazione:indicizzazione` | allarme | `MONITOR_TIPI_ATTIVI` valorizzata senza `INDEXNOW_API_KEY` | come sopra |
| `configurazione:tipi_attivi` | allarme | `MONITOR_TIPI_ATTIVI` contiene tipi che il monitor non produce | come sopra |
| `configurazione:giri` | allarme | `MONITOR_GIRI` contiene ore fuori dallo scheduler | come sopra |
| `lavorazione_lunga:<…>` | avviso | un lucchetto tenuto oltre 1/3 del suo tempo di validità (al massimo 60 minuti) | di solito è un giro lento |
| `lavorazione_orfana:<…>` | allarme | un lucchetto tenuto oltre 2/3 del suo tempo di validità (al massimo 180 minuti): probabilmente il processo è morto | dal giro 2 il sender, all'avvio, rilascia da solo i lucchetti dei suoi processi morti (§3.3.2) |

Oggi non c'è nessun lucchetto tenuto (`pipeline_lock` vuota).

Fonti: `scraper_bandi/app/telemetria.py:255-280,477-595,1140-1355`, `backend/app/bandi_pipeline.py:144-175`,
`docs/bandi-monitor/RIPRESA.md` §3.1, lettura su `pipeline_lock`.

### 6.6 Cosa direbbe `salute` oggi

`salute` non è stato lanciato in questa indagine. Si poteva (fa solo letture); si è preferito eseguire dal Mac le stesse
misure del DB (`db.misure_salute`, solo GET) e il giudizio di `telemetria.salute`. Mancavano systemd e la configurazione
di produzione (quella usata era del Mac). Il job orario è stato letto a parte e risulta sano (§4.6). Il risultato, alle
12:06:

| Codice | Livello | Situazione |
|---|---|---|
| `fonti_da_verificare` | allarme | **acceso**: 27 su 57 pubblicati negli ultimi 7 giorni, cioè il 47% (soglia 30%) |
| `configurazione:indicizzazione` | allarme | **probabile sul server**. `MONITOR_TIPI_ATTIVI` è valorizzata (verificato: il monitor delle 06 di oggi riporta i tipi faq, nuovo_allegato, graduatoria, esito, proroga). Che manchi `INDEXNOW_API_KEY` nell'ambiente del sender lo dice RIPRESA: non verificato |
| `fermi_in_lavorazione` | avviso | **acceso**: 8 bandi della fonte 250 fermi in `processed` dal 28-29/09 |
| `verifica_stato_ferma` | avviso | «non ancora eseguita»: atteso fino al giro delle 18 |
| `indicepa_non_aggiornato` | avviso | «nessun import riuscito registrato»: atteso fino al giro delle 06 di domani |
| `non_misurato` | avviso | sempre presente (crediti Firecrawl, schede ObiettivoEuropa, stato da verificare in ombra) |

**Conseguenza: oggi `salute` finisce con exit 1**, almeno per `fonti_da_verificare`. Con uno o due allarmi accesi in
permanenza, un allarme nuovo non si distingue dal rumore. Il "semaforo" è sempre rosso, quindi non avvisa più.

Il segnale di IndexNow ha anche un lato concreto. IndexNow serve ad avvisare i motori di ricerca dei cambiamenti. Oggi
`/api/indexnow-key` risponde 404 («IndexNow key not configured»): il sito non ha la chiave nella sua configurazione. Il
sender legge la **stessa** variabile `INDEXNOW_API_KEY` (con `os.getenv`, dopo aver caricato `scraper_bandi/.env` e poi
il `.env` della cartella di avvio) e dichiara a IndexNow che la chiave sta all'indirizzo `/<chiave>.txt`, che però il
sito serve solo se ha la stessa chiave. Che il sender abbia la variabile è **non verificato**; anche se l'avesse, oggi
IndexNow non potrebbe verificarla sul sito. Verificato invece: la pipeline dei bandi notifica solo gli slug che i passi
restituiscono come modificati (oggi il monitor e, in attivo, la verifica). I bandi nuovi pubblicati dalla SEO non
vengono mai notificati.

Cose buone viste oggi:
- il giro di avvio delle 10:10 è finito alle 10:18, con esito ok e 3 bandi nuovi pubblicati. Anche il giro delle 12:00 è
  finito ok alle 12:06;
- nessun lucchetto è tenuto;
- il job orario gira: ultimo avvio riuscito, 0 fallimenti nelle 24 ore;
- nessuna riga di `fonte_run` ha mai registrato un errore, e `fonti_errors` vale 0 in tutti i giri dal 27/09 (ma è un
  numero ingannevole, §2.12).

Cose che `salute` **non vede**:
- **fonti spente in silenzio.** A ogni giro, dal 27/09, fra 13 e 21 fonti del discover vanno in «connection error» e
  vengono segnate non attive per quel giro (il discover successivo le riprova). Inoltre 26 fonti in elenco non vengono
  lette: 8 senza voce nel registro e 18 saltate di proposito. `ingresso_guasto` scatta solo se falliscono **tutte**;
- **spese incomplete.** La riga del giro registra 0 dollari anche quando preprocess, enrich e SEO hanno lavorato (per
  esempio il giro delle 12 del 29/09, con 20 schede prodotte). Preprocess, enrich e SEO non registrano il loro costo,
  quindi il consumo mensile giudicato da `salute` è sottostimato.

Fonti: `scraper_bandi/app/telemetria.py`, `scraper_bandi/app/db.py:2407-2646, 3036-3061`,
`scraper_bandi/app/orchestrator.py:14-41,86-144`, `backend/app/bandi_pipeline.py:26-30,675-716`,
`backend/app/indexnow.py:21-39`, `scraper_bandi/app/settings.py:403-406`, `src/pages/api/indexnow-key.ts`,
`src/pages/[key].txt.ts`, letture su `bando`, `pipeline_run` (righe 90-153), `fonte_run`, `pipeline_lock`,
`/api/indexnow-key` in produzione.

### 6.7 Altri comandi di controllo in sola lettura

Tutti si lanciano da `~/projects/news1/scraper_bandi` con `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app …`.

| Comando | A cosa serve | Dove |
|---|---|---|
| `salute [--json]` | la diagnosi con i codici (§6.2) | server o Mac |
| `sorveglia --dry-run` | stampa il riepilogo che il pannello riceverebbe, senza scriverlo: stato ok / attenzione / guasto, codici, ultimi 20 giri, job orario. Finisce con 0 anche con allarmi (1 solo se il DB non risponde) | server o Mac |
| `report-verifica-stato` | per ogni bando candidato alla verifica: stato, motivo, cosa ha letto, cosa proporrebbe. Filtri `--ramo aperto\|apertura` e `--motivo …` | server o Mac |
| `report-verifica-stato --verita` | confronta il risultato con una lista di bandi controllati a mano (misure del 30/09-01/10). Finisce con «difformi: N» (exit 1 se N > 0). **Si attiva la verifica solo con 0 difformi.** È il controllo previsto per l'8 ottobre | server o Mac |
| `report-ombra --dal AAAA-MM-GG [--campione 100] [--tipo X]` | misura il monitor in ombra: elenca gli eventi proposti e ammessi dal giorno indicato e stampa un CSV su stdout (`> file.csv`). È la misura con cui si decide se un tipo di evento può uscire dall'ombra (RIPRESA §4.1 a e b). Non scrive niente | server o Mac |
| `verifica-stato --dry-run --senza-modello --limit 20` | prova il passo senza scrivere, senza lucchetto e senza chiamare il modello | dal Mac **solo** così |
| `rielabora-fonte --dry-run [--ids 1,2]` | dal giro 3: stampa le proposte della rielaborazione (date, junction, FK) senza scrivere e senza lucchetti; chiama il modello due volte per bando, quindi spende (circa 4,6 centesimi a bando). Fuori dal dry-run il comando prende il lucchetto del giro (`rielabora-fonte:cli`) | server o Mac, solo `--dry-run` |
| `gemelli --dry-run` | mostra le fusioni automatiche che il giro delle 06 farebbe (oggi 52) | server o Mac |
| `domini --import --scarica-enti --dry-run` | prova l'import dell'elenco degli enti pubblici senza scrivere | dal Mac solo `--dry-run` |

Sul server, in più:
```bash
systemctl is-active edunews-bandi-sender
journalctl -u edunews-bandi-sender --since today \
  | grep -E "STEP (resolver|ricontrolli|monitor)|FAILED|NON PARTITO|\[ALLARME\]"
```
Il risultato atteso: nessun `FAILED`, nessun `NON PARTITO`, nessun `[ALLARME]`. Il monitor compare solo alle 06 e alle
18. Negli altri giri la riga «STEP monitor SALTATO (giro 12:00 non previsto)» è corretta.

**Da non lanciare dal Mac** senza le opzioni di prova: `monitor`, `risolvi-fonte`, `seo`, `preprocess`, `enrich`,
`discover`, `scrape-bandi` (il comando dello scrape; «scrape» è solo il nome del passo nel giro e nel diario), e
`fondi-doppioni`. Scrivono sul database vero o spendono (modello, Firecrawl).

**E nemmeno con `--dry-run`: `monitor` e `risolvi-fonte`.** Le loro prove a secco **non** sono a sola lettura: prendono
e rilasciano il lucchetto (`monitor`, `bandi_resolver`) con le funzioni del database e scrivono una riga in
`pipeline_run` (costo 0). Lanciate dal Mac possono far saltare il passo di un giro e lasciano una riga nel diario di
produzione: l'01/10 verso le 16:40 un `monitor --dry-run --senza-rete` ha scritto una riga `monitor` con giro vuoto.
Si lanciano solo sul server, fuori dai giri (§3.3.1).

Fonti: `scraper_bandi/app/__main__.py:980-992, 1156-1168, 1213-1235, 1275-1311, 1332-1366, 1370-1395`,
`scraper_bandi/app/sorveglianza.py:226-300`, `scraper_bandi/app/riepilogo_salute.py:51`,
`scraper_bandi/app/verifica_stato.py:160-200` (`VERITA_NOTA`), `backend/app/bandi_pipeline.py:404`,
`docs/bandi-monitor/RIPRESA.md` §3.1, §4.1 e §6.

### 6.8 La sorveglianza rimandata

**Com'era stata progettata.** Nessuna notifica push: niente Telegram, niente email (scelta confermata il 30/09). Al loro
posto c'era un solo canale:
1. un timer di systemd lancia `sorveglia` ogni 15 minuti;
2. `sorveglia` scrive un riepilogo neutro nella tabella `monitoraggio_riepilogo`. Il riepilogo contiene stato, codici,
   da quando sono accesi, ultimi giri e job orario, senza costi, host o URL;
3. il pannello admin di BandoFit lo legge con una chiave segreta, di cui il database conserva solo l'impronta sha256.
   Dopo 45 minuti senza una riga nuova il pannello mostra «in ritardo».

**Cosa è successo l'01/10.** Il pannello di BandoFit è stato **rimandato**: lo farà Michele più avanti. Di conseguenza:
- il timer di `sorveglia` non è installato;
- la chiave del pannello non esiste;
- `monitoraggio_riepilogo` ha 0 righe (verificato).

Gli oggetti nel database (migrazione 12) sono pronti. Secondo il codice SQL, con una chiave sbagliata la funzione del
pannello risponde «non autorizzato». In questa revisione non è stato riprovato, perché è una chiamata POST.

**Cosa vuol dire in pratica:**
- **Oggi nessun allarme raggiunge una persona.** Un sender fermo, il credito esaurito o un job orario rotto possono
  durare giorni. Si vedono solo lanciando `salute` a mano o leggendo il journal e il diario.
- Due misure dipendono da una "memoria" che solo `sorveglia` scrive (nella riga del riepilogo), e oggi mancano:
  - la crescita dei riavvii di systemd (NRestarts), usata da `riavvii_ripetuti`, che quindi oggi conta solo i giri di
    avvio;
  - il «dal», cioè da quando un codice è acceso.
- `vista_lenta` si misura a ogni `salute`, ma senza `sorveglia` nessuno la misura con regolarità.

**Il rimedio minimo, finché il pannello non c'è:** lanciare `salute` a mano con regolarità, sapendo che
`fonti_da_verificare` è già acceso e che sul server lo è probabilmente anche `configurazione:indicizzazione` (§6.6).
Ogni allarme **diverso** da quei due è una novità da guardare.

Fonti: `scraper_bandi/app/sorveglianza.py:1-60,186-300`, `scraper_bandi/app/telemetria.py:714-737`,
`scraper_bandi/app/db.py:2438,2856-2870,3006-3080`, `backend/sql/bando_v11_12_monitoraggio.sql:186-202,237-257,338-370`,
`docs/bandi-monitor/RIPRESA.md` §1 e §3.1, lettura su `monitoraggio_riepilogo`.

### 6.9 Cosa non è verificato nei capitoli 5 e 6

- I codici che `salute` darebbe oggi **sul server**. Sono stati ricostruiti dal Mac con le stesse misure del DB, senza
  systemd e senza la configurazione di produzione.
- Che `INDEXNOW_API_KEY` manchi davvero nell'ambiente del sender: è un'affermazione di RIPRESA. Verificato solo che
  manca al sito (`/api/indexnow-key` risponde 404).
- I valori in produzione di `BANDI_FONTE_LETTURA` e `BANDI_STATI_ESTESI`: dedotti dal comportamento del sito, non letti.
  `MONITOR_TIPI_ATTIVI` (faq, nuovo_allegato, graduatoria, esito, proroga), `MONITOR_MODALITA` (ombra),
  `RESOLVER_MODALITA` (attivo) e `VERIFICA_STATO_MODALITA` (non attiva) sono confermati indirettamente, dai contatori
  che i processi di produzione hanno scritto in `pipeline_run` (monitor delle 06 di oggi, giro di avvio delle 10:10).
- Cosa legge davvero BandoFit e se il messaggio del giro 2 gli è arrivato.
- Le 41 coppie da fondere a mano e il 16% di aperti senza scadenza già chiusi (numeri di RIPRESA). Le 52 fusioni attese
  sono invece state ricontate con `gemelli --dry-run`.
- Che `fonti_da_verificare` sia acceso «da settimane».
- Il nome reale del servizio systemd (il codice usa `edunews-bandi-sender` come predefinito).

Fonti: misure in sola lettura del 01/10/2026 tra le 12:00 e le 12:15, `docs/bandi-monitor/RIPRESA.md:332-356`.

---

## 7. Cosa c'è in produzione oggi

Questa è la fotografia del sistema bandi all'**01/10/2026**. Le letture sul database sono state fatte fra le 11:28 e le
11:37 (ora di Roma), dopo il deploy delle 10:10, e ricontrollate in sola lettura fra le 12:05 e le 12:30.

**Attenzione: alle 12:00 è girato un altro giro** (riga 153 di `pipeline_run`: esito «ok», 353 secondi, 1 bando nuovo
giudicato «chiuso», nessuno pubblicato). Per questo alcuni numeri delle 12:30 sono già diversi da quelli delle tabelle
qui sotto, che restano quelli delle 11:28-11:37:

- righe di `bando`: 5.195 (non 5.194);
- `processed`: 570 (non 569);
- eventi: 12.086 (non 12.026);
- fonti: 102 pronte e 15 in «connection error» (non 103 e 14).

Quasi tutto ciò che è nuovo è in ombra (osserva e annota, non tocca il pubblico). È voluto: prima si misura, poi si
accende.

### 7.1 La versione del codice

- **Deploy di oggi alle 10:10.** Il giro di avvio è durato dalle 10:10:00 alle 10:18:20 (499,6 secondi). Esito «ok»,
  nessun passo andato male (`passi_non_ok` vuoto), 3 bandi nuovi pubblicati (riga 150 di `pipeline_run`).
- **Il commit d7f5663** (giro 2: sorveglianza e stato da verificare) lo indica il lead. La riga del giro è compatibile con
  quel codice, perché contiene i campi nuovi `passi_non_ok` e `verifica_stato_ingresso`. Il numero del commit però non è
  registrato da nessuna parte: **non verificato**.
- **Deploy precedente: 30/09 alle 18:47**, con il codice «ripresa bandi, ottobre» e i cinque tipi di evento attivi. Lo
  dice RIPRESA §1, e il DB lo conferma: il giro di avvio è partito alle 18:47 (riga 141), e il monitor delle 06 di oggi
  usa già quei cinque tipi (riga 146).
- **Sito.** Legge la vista pubblica `bando_pubblico`. Lo si deduce da due cose:
  - la scheda mostra «controllata il 24 settembre 2026», un dato (`ultimo_controllo_at`) che esiste solo nella vista;
  - lo slug di un doppione fuso risponde con un 301.
- **API pubblica.** Risponde «version: 1.2» (verificato con curl; `VERSIONE_API = '1.2'` in
  `src/lib/api-v1/costanti.ts:8`).
- **Test.** Rieseguiti per intero l'01/10 sul Mac, su `main` 7bbddac. Rispetto a d7f5663 cambiano solo due file di
  documentazione, quindi il codice è lo stesso della produzione. Risultati, uguali ai numeri del lead:

  | Suite | Risultato |
  |---|---|
  | `test:py:bandi` | 2.540 test, OK |
  | `npm test` | 473 pass, 0 fail, 0 skipped |
  | `test:py` | 77 test, OK |
  | `tsc` | 51 errori, quelli preesistenti |

Fonti: `pipeline_run` (righe 141, 146, 149, 150, 153); `docs/bandi-monitor/RIPRESA.md` §1; `src/lib/api-v1/costanti.ts`;
prove con curl su edunews24.it; `git diff d7f5663 HEAD`.

### 7.2 Le migrazioni del database bandi

La tabella completa, con che cosa fa ogni migrazione, è in §4.11. In sintesi:

| Applicate | Non applicate |
|---|---|
| 01, 02, seed, 03, 04, 05, 06 (28/09), 08, 09, 10, 11 (28/09), 12 e 13 (oggetti presenti; la data dell'01/10 viene dal lead) | **07**, bloccata (§4.11, §9.6); **14**, scritta l'01/10 per il giro 3, da applicare prima del deploy (RIPRESA §1) |

Sulla 12 e sulla 13 è verificato che i loro oggetti esistono e rispondono:

- la tabella `monitoraggio_riepilogo` (vuota);
- la tabella `monitoraggio_chiave` esiste, ma non si legge nemmeno con la chiave di servizio (risponde 403): se contenga
  una chiave **non è verificato**;
- la funzione `monitoraggio_job_orario`, che risponde;
- le 49 colonne della vista (44 della 05 più le 5 della 13);
- la riga 24 della lista bianca (`bando_transizione` ha 24 righe).

**Non verificato**: che siano state applicate proprio oggi e con i blocchi di verifica superati.

Due avvertenze da ricordare (dettaglio in §4.11): rieseguire la 02 dopo la 13 fermerebbe il sito; la 12 non è chiusa in
un `BEGIN; … COMMIT;` esplicito.

Fonti: `backend/sql/bando_v11_*.sql` (intestazioni della 12 e della 13); letture GET su vista, `bando_controllo`,
`bando_transizione`, `monitoraggio_riepilogo`, `dominio_ufficiale`; RIPRESA §1 «Migrazioni applicate».

### 7.3 Cosa è acceso e cosa è in ombra

> La tabella è la produzione dell'01/10, prima del deploy del giro 3. Dopo il deploy l'interruttore unico si divide in
> tre (`VERIFICA_STATO_MODALITA`, `GEMELLI_MODALITA`, `DOMINI_MODALITA`), gemelli e IndicePA passano ad **attivo**, il
> monitor applica da solo **tutti** i tipi di evento, e `link_verifica` e la rielaborazione entrano nel giro: §3.3.5 e
> §3.2-bis.

| Pezzo | Interruttore | Stato oggi | Come lo sappiamo |
|---|---|---|---|
| Resolver della fonte ufficiale (cerca la pagina dell'ente) | `RESOLVER_MODALITA` | **attivo** dal 25/09 | DB: «attivo=true» nel giro di oggi |
| Monitor delle pagine ufficiali | `MONITOR_MODALITA` (non impostata, secondo RIPRESA) | **ombra** | DB: riga 146, «modalita: ombra» |
| Eccezione: 5 tipi di evento pubblicati da soli (faq, nuovo_allegato, graduatoria, esito, proroga) | `MONITOR_TIPI_ATTIVI` | **acceso dentro l'ombra**; nessun evento ancora applicato da solo | DB: riga 146 (`applicati_per_tipo` vuoto) |
| Sospensione e revoca nel monitor | `MONITOR_STATI_ESTESI=true` | acceso secondo RIPRESA | **non verificato** |
| Verifica dello stato (rilegge le pagine ufficiali) | `VERIFICA_STATO_MODALITA` (non impostata) | **ombra** | DB: righe 149, 150, 152 |
| Fusioni automatiche dei doppioni (passo «gemelli») | stesso interruttore della verifica | **ombra** | codice (`gemelli.py`) |
| Sosta dei bandi nuovi senza scadenza | stesso interruttore | **ombra** | DB: «modalita_ingresso: ombra» |
| Fusione di un bando nuovo nel gemello già pubblicato | stesso interruttore | **ombra** | codice (`bando_seo_runner.py`) |
| Import dei domini da IndicePA | stesso interruttore | **ombra**; mai partito | DB: nessuna riga «domini»; codice (`fonte_ufficiale.py:3201`) |
| Scarto dei doppioni di ObiettivoEuropa prima della SEO | nessuno | **sempre attivo** (si ferma solo con `--dry-run`) | codice |
| Job orario del DB (chiude gli scaduti, ogni ora al minuto 5) | pg_cron | **acceso**: ultimo avvio alle 12:05, riuscito, 0 fallimenti in 24 ore | DB: lettura GET della funzione di sola lettura `monitoraggio_job_orario` |
| Sito: fonte di lettura | `BANDI_FONTE_LETTURA` | vista `bando_pubblico` | dedotto dalla pagina pubblica |
| Sito: stati Sospeso e Revocato nei filtri | `BANDI_STATI_ESTESI` | **spento** | dedotto dalla pagina pubblica |
| Sorveglianza automatica (`sorveglia`) | timer systemd | **non installato** (decisione dell'01/10); 0 riepiloghi scritti | DB; RIPRESA |
| IndexNow (avvisa i motori di ricerca) | `INDEXNOW_API_KEY` nel sito e nel sender | **rotto**: `/api/indexnow-key` risponde 404, cioè la variabile manca nella build del sito | curl (sito); RIPRESA (sender, **non verificato**) |
| Vecchia deduplicazione `canonical_key` | `DEDUP_CANONICAL` | spenta (valore predefinito) | codice; produzione **non verificata** |

Su IndexNow, un dettaglio: i motori controllano la chiave all'indirizzo `https://edunews24.it/<chiave>.txt`
(`backend/app/indexnow.py:39`), servito da `src/pages/[key].txt.ts`. Quella pagina legge la stessa variabile di
`/api/indexnow-key`, quindi oggi risponde 404 anche lei.

Alcuni comandi **non sono nel giro** e partono solo a mano (§3.17): `link-verifica`, `oe-dettaglio`,
`archivia-processed` (lotto L8), `fondi-doppioni`, `rigenera` e `seo-rigenera`.

Anche dentro il resolver c'è una sorpresa: la **sonda gratuita**, la **ricerca a pagamento**, l'**arbitro LLM** e
**SEDIA** sono descritti nel codice ma non sono collegati da nessuna parte. L'ambiente di produzione del resolver non li
passa, e il codice lo dice: «Sonda, ricerca e arbitro restano invece assenti finché il committente non li attiva»
(`fonte_ufficiale.py:2301-2332`). In produzione non girano: nel giro di oggi `sonde`, `ricerche` e `arbitri` valgono 0.

Una regola valida per tutte le variabili: il sender le legge **una volta sola, all'avvio** (`get_settings` tiene in
memoria il primo valore). Ogni modifica a `scraper_bandi/.env` richiede quindi un riavvio del sender.

Fonti: `pipeline_run` 146, 149, 150, 152; `scraper_bandi/app/settings.py`; `gemelli.py`; `fonte_ufficiale.py`;
`bando_seo_runner.py`; `backend/app/indexnow.py`; `src/pages/api/indexnow-key.ts`; `src/pages/[key].txt.ts`; RIPRESA
«Configurazione in produzione».

### 7.4 Quando gira cosa

La tabella completa è in §3.2. In sintesi: un solo processo, il «sender dei bandi», lancia un **giro** quattro volte al
giorno, alle 00, 06, 12 e 18 secondo l'orologio del server, e un giro di avvio a ogni riavvio. Il server è in ora di
Roma (lo si deduce dagli orari dei giri: il giro delle 06 parte alle 04:00 UTC).

| Giro | Passi, in ordine |
|---|---|
| 00:00 e 12:00 | discover → scrape → preprocess → enrich → resolver (nuovi) → verifica d'ingresso → SEO |
| 18:00 | come sopra, più i ricontrolli del resolver (dopo il resolver) e, dopo la SEO, monitor e verifica dello stato (fase «controlli») |
| 06:00 | come le 18, più l'import dei domini prima del resolver (una volta al mese) e, in fondo, i gemelli |
| avvio (riavvio) | identico alle 00:00 e alle 12:00 |

Alla fine di ogni giro, a lucchetto rilasciato, parte una sola notifica IndexNow con gli slug cambiati (oggi solo quelli
del monitor).

Un giro dura fra 5 e 14 minuti, mediana **circa 7** (6,8 minuti sui 41 giri riusciti dal 23/09 al giro di avvio
dell'01/10). Il commento del codice parla ancora di «80 minuti».

**Prime volte con il codice nuovo:**

- **oggi alle 18:00**: primo passo di verifica dello stato, fase «controlli», in ombra;
- **domani 02/10 alle 06:00**: primo import di IndicePA e primo passo «gemelli», entrambi in ombra. In ombra l'import
  scarica comunque il foglio, ma non scrive i domini.

Fonti: `backend/app/bandi_pipeline.py:256-450` (ordine dei passi), `:512` (`GIRO_DELLE_06`); `backend/app/bandi_sender.py`;
`scraper_bandi/app/settings.py:288-290`; `pipeline_run` (step «pipeline»).

### 7.5 Configurazione nota: modelli e tetti di spesa

**Modelli.** Sono i valori predefiniti del codice. Quelli reali di produzione **non sono verificati**, perché il `.env`
del server non si legge dal Mac.

| Passo | Modello |
|---|---|
| Preprocess ed enrich | Claude Haiku 4.5 |
| Ripiego del preprocess quando la pagina manca (variabile `RESOLVER_MODEL`, nome che inganna) | Claude Sonnet 4.6 |
| SEO, cioè la scrittura della scheda | Claude Opus 4.7 |
| Monitor e verifica dello stato | Haiku 4.5, con Sonnet 4.6 come «seconda opinione» del monitor. La verifica cerca un'impostazione `monitor_modello` che non esiste, quindi usa sempre l'Haiku del monitor |

**Tetti di spesa** (scenario «bilanciato», quello predefinito):

| Tetto | Valore |
|---|---|
| Per giro | 420 scaricamenti |
| Al giorno | 50 ricerche, 120 crediti Firecrawl, 30 classificazioni, 1,5 $ |
| Al mese | 5.000 crediti, 16 $ |
| Backfill (contatori separati) | 8.000 crediti, 60 $ |
| Verifica dello stato | 40 letture e 900 secondi per giro, 30 bandi all'ingresso |
| Gemelli | 10 fusioni per giro |

Attenzione: i tetti **proteggono solo** monitor, resolver, verifica, rigenera e backfill. I passi che spendono di più non
sono né contati né limitati (§3.3.6, §3.18):

- la SEO con Opus (il giro normale chiama `genera_per_bando` senza contatori, `bando_seo_runner.py:698`), e anche il
  Firecrawl che la SEO usa per leggere la pagina (`bando_seo_runner.py:269`);
- preprocess ed enrich;
- il Firecrawl dello scrape.

Inoltre il **tetto mensile non lo applica nessuno**: nessun chiamante passa i consumi del mese a `bilancio.verifica`
(§8.2, M1).

Fonti: `scraper_bandi/app/settings.py:247-290, 439-489`; `scraper_bandi/app/bilancio.py:285-312`;
`monitoraggio.py:180-188`; `verifica_stato.py:1016`; `bando_seo_runner.py`.

### 7.6 I numeri reali di oggi (01/10/2026, fra le 11:28 e le 11:37)

Questa sezione raccoglie in un posto solo i numeri che gli altri capitoli citano.

**Pubblicazione**

| Misura | Valore |
|---|---|
| Bandi pubblicati (vista) | **2.191** |
| Righe totali nella tabella `bando` | 5.194 (5.195 dopo il giro delle 12) |
| — completed | 2.197 (2.191 pubblicati + 6 doppioni fusi il 30/09) |
| — processed | 569, tutti chiusi: l'«arretrato L8». **Non è fermo: cresce.** Ogni bando nuovo giudicato «chiuso» dal preprocess resta `processed` per sempre, perché l'enrich prende solo gli aperti e gli «in apertura». Il giro delle 12 ne ha aggiunto uno (570) |
| — rejected | 2.428 |
| — scraped / enriched | 0 / 0 |
| Pubblicati oggi | 3 |
| Pubblicati che vengono da ObiettivoEuropa | 1.768 su 2.191 (**81%**) |
| Fonti con almeno un bando pubblicato | 31 |

**Stato dei bandi pubblicati**

Nel DB lo stato «in apertura» si scrive `in apertura prossimamente`.

| Misura | Valore |
|---|---|
| Aperti | 1.168, di cui **426 senza scadenza** (36%; 285 da ObiettivoEuropa) |
| In apertura | 166, di cui **163 senza data di apertura**; 0 con apertura verificata |
| Chiusi | 857 |
| Sospesi / revocati | 0 / 0 |
| «Da verificare» | **2** (id 2308 e 2955, motivo «data di apertura passata») |
| Scadono oggi | 16 |
| Date verificate | scadenza 47, apertura 18, stato 34 |
| Con ora di scadenza | 42 |
| Chiusure automatiche del job orario | 190 in tutto; **107 alle 00:05 di stanotte** |
| Aperture automatiche | **0 in tutta la storia** |

**Fonte ufficiale dei pubblicati** (la pagina dell'ente che ha emesso il bando)

| Misura | Valore |
|---|---|
| Trovata | 620 (ente 348, riconosciuta per forma 259, portale pubblico 13); 610 trovate il 24/09 |
| In verifica | 1.050, di cui 364 con già 70 punti o più |
| Non trovata | 521 |
| Pubblicati non trovati con un link valido solo su domini fuori dalla lista bianca | 353 (misura dell'indagine, non ricontata) |
| Ricontrolli in coda (pubblicati) | 690 il **08/10**, 847 il **23/11** |
| Righe della lista dei domini | 109; 0 da IndicePA |

**Eventi, link, doppioni**

| Misura | Valore |
|---|---|
| Eventi registrati | 12.026; 3.087 visibili al pubblico (3.166 leggibili, meno 79 su bandi mai pubblicati); 52 nel box «Aggiornamenti» |
| — di cui nel box per correzione a mano | 50 dei 52 (28 proroghe, 17 aperture, 4 rettifiche, 1 chiusura), registrati il 30/09 fra le 12:19 e le 19:18; di questi, 33 vengono dai due file SQL del 30/09 sera (date e testi), applicati fra le 19:02 e le 19:18. Gli altri 2 sono 1 FAQ e 1 nuovo allegato |
| Eventi del monitor ammessi e verificati ma non pubblicati (arretrato d'ombra) | 20 (9 proroghe, 6 faq, 3 aperture, 2 nuovi allegati) |
| Righe di `bando_link` | 10.139; 6.206 pubblicabili |
| Link pubblicabili verificati l'ultima volta il 23-24/09 | 6.173 su 6.206 |
| Righe «candidatura» pubblicabili | **1** (su 92) |
| Fusioni fatte | 6, manuali, del 30/09; 6 slug storici con 301 |
| Fusioni automatiche previste all'attivazione | 52 (43 per URL, 9 di calendario), da `gemelli --dry-run` alle 11:28, confermate da un secondo `--dry-run` alle 12:16. Scartate per prudenza: 33 coppie |

**Fonti e scraping** (giro di avvio di oggi)

| Misura | Valore |
|---|---|
| Fonti in tabella | 121: 103 in elenco (pronte e attive), 14 in «connection error», 4 deprecate (alle 12:30: 102 e 15) |
| Fonti in elenco | 103: 77 lette davvero, 18 saltate di proposito, 8 senza voce nel registro |
| Fonti lette con 0 bandi | 25; 22 non hanno mai prodotto nulla dal 24/09 |
| Italia Domani (450) e Incentivi.gov.it (451) | **0 bandi in tutta la storia** |
| Record letti | 3.758: 3 nuovi, 44 cambiati, 3.682 identici. La somma fa 3.729: i 29 mancanti sono, secondo il codice, le righe di ObiettivoEuropa con la sola differenza fra etichetta e scadenza, che non si contano fra nuovi, cambiati o identici (§2.11). È un'ipotesi coerente con il codice, non verificata riga per riga |
| Segnali «in uscita» da ObiettivoEuropa | 59 |

**Verifica dello stato** (in ombra)

| Misura | Valore |
|---|---|
| Letture scritte | 0 su 4.620 righe di `bando_controllo` |
| Candidati della prima fase «controlli» | 592 (426 aperti senza scadenza + 166 in apertura): 496 leggibili, 96 illeggibili |
| Giri necessari per leggerli tutti una volta | circa 13 (6,5 giorni), con 40 letture per giro |

**Giri e spesa**

| Misura | Valore |
|---|---|
| Righe «pipeline» dal 23/09 al giro di avvio | 46: 41 ok, 3 saltate, 2 interrotte per tetto (25/09). Con il giro delle 12: 47, di cui 42 ok |
| Durata di un giro | fra 5,3 e 13,5 minuti, mediana 6,8 (circa 7) |
| Spesa registrata al giorno (solo monitor, resolver, verifica) | da 0 a 0,46 $ |
| Spesa del backfill L6 | 7,59 $ |
| Spesa di SEO, preprocess ed enrich | **non registrata** |
| Monitor delle 06 di oggi | 80 pagine riallineate, 0 classificazioni, 0 $ |
| Pagine alla pulizia nuova (v2) | 80 su 619 |
| Lucchetti tenuti / riepiloghi di sorveglianza | 0 / 0 |

**Sito**

| Misura | Valore |
|---|---|
| Contatori di /bandi | 1.168 / 166 / 857, «di cui 2 da verificare»: uguali al DB |
| Sitemap dei bandi | 3 blocchi (1.000 + 1.000 + 191), 2.191 URL, chiusi compresi; 136 pagine filtro dei bandi |
| Tabella `bando` leggibile con la chiave pubblica (fino alla 07) | 2.197 righe; 1.878 con dati grezzi, 1.772 con link a ObiettivoEuropa |

Fonti: GET di sola lettura su `bando`, `bando_pubblico`, `bando_controllo`, `bando_evento`, `bando_link`,
`dominio_ufficiale`, `fonte`, `fonte_run`, `pipeline_run`, `bando_fusione`, `bando_slug_storico`; curl su edunews24.it;
`gemelli --dry-run`; `scraper_bandi/app/db.py:449-467` (selezione dell'enrich); `scraper_bandi/app/segnali.py:508-512`.

### 7.7 Cosa non è verificato in questo capitolo

- Il contenuto vero di `scraper_bandi/.env` sul server, cioè modalità, tetti e modelli. Le modalità si deducono dai
  contatori del DB; il resto no.
- Che `INDEXNOW_API_KEY` manchi nel sender. Lo dice RIPRESA (allarme comparso al deploy del 30/09).
- Che sul server sia installato il file di riavvio automatico (`edunews-bandi-sender-riavvio.conf`).
- Il fuso orario del server: dedotto dagli orari dei giri.
- Che cosa legge davvero BandoFit: il suo codice non è disponibile.
- Se in `monitoraggio_chiave` ci sia una riga: la tabella non si legge (403).
- Il comando `salute` non è stato lanciato sul server: i suoi allarmi di oggi sono ricostruiti dal Mac con le stesse
  letture (§6.6).
- Le 41 coppie ObiettivoEuropa/fonte ufficiale da fondere a mano: numero preso da RIPRESA §4.5, non ricontato.
- I 353 bandi con link valido solo fuori dalla lista bianca e i 96 candidati illeggibili: misure delle indagini, non
  ricontate.

---

## 8. Correzioni da fare

**Come leggere questo capitolo.** Le voci sono divise per gravità.

- **Alta**: può fare danni visibili o bloccare il piano dei prossimi giorni.
- **Media**: va sistemata, ma non ferma niente oggi.
- **Bassa**: piccoli difetti, rifiniture, documentazione.

Ogni voce porta un'etichetta:

- **Difetto**: il sistema fa una cosa sbagliata, oppure non mantiene una promessa scritta;
- **Rischio**: oggi non fa danni, ma può farne in una situazione prevedibile;
- **Miglioria**: funziona, ma si può fare meglio;
- **Decisione**: non è un errore, è una scelta da prendere;
- **Documentazione**: il codice va bene, il testo che lo descrive no.

Le «proposte» sono suggerimenti, non lavoro già fatto. I numeri ricontrollati sono in §7.6; gli altri vengono dalle
indagini.

**In sintesi, le cinque cose più urgenti:**

1. Nessun allarme arriva a una persona (A1).
2. Il controllo dell'08/10 darà almeno una «difforme» certa (A2).
3. Il comando manuale `fondi-doppioni` può fondere tutto senza freni (A4).
4. Due fonti intere non hanno mai prodotto un bando, e nessuno se ne accorge (A5).
5. Il resolver gira con metà degli strumenti, e la lista bianca blocca 353 bandi (A6).

### 8.1 Gravità alta

**A1. Nessun allarme raggiunge una persona.** *Difetto di processo.*
- **Cosa non va.** La scelta del 30/09 è «niente notifiche». Il pannello su BandoFit, che doveva essere l'unico punto di
  controllo, è rimandato. Il timer di `sorveglia` non è installato e nessun passo del giro chiama `salute`.
- **Perché conta.** Un sender fermo, il credito Anthropic finito o il job orario rotto possono durare giorni senza che
  nessuno se ne accorga. È già successo il 28-29/09: il credito era finito e il preprocess non ha scritto niente per
  quattro giri (fonte: RIPRESA e la deroga «credito esaurito»). Senza `sorveglia` mancano anche due misure: i riavvii
  ripetuti e il «dal quando» di ogni segnale.
- **Proposta (Decisione di Michele).** Le strade possibili sono tre:
  1. installare comunque il timer di `sorveglia`. Non costa niente e prepara i dati per il pannello futuro, ma da solo
     non avvisa nessuno;
  2. anticipare una versione minima del pannello;
  3. accettare, per un periodo dichiarato, un controllo a mano con `salute`. Contrasta però con la regola «nessun passo
     ricorrente a mano».

**A2. Il controllo dell'08/10 darà almeno una «difforme» sicura.** *Difetto.*
- **Cosa non va.** La «verità nota» è la tabella di 53 bandi controllati a mano con cui si giudica la verifica
  (`VERITA_NOTA`, `verifica_stato.py:171-205`). Il bando 661135 vi compare come atteso «chiusura». Il job orario però
  l'ha già chiuso per scadenza (scadenza 30/09) il 30/09 alle 22:05 UTC (evento 12005), quindi non è più un candidato.
  Il confronto conta come difforme ogni bando assente dal report (`confronta_verita`, `verifica_stato.py:1723`).
- **Perché conta.** La regola per attivare è «difformi: 0». Così com'è, l'attivazione è bloccata. RIPRESA dice che, se un
  bando è cambiato davvero, «la tabella va aggiornata, non il codice», ma la tabella **è** codice (`verifica_stato.py`):
  serve un commit e un deploy.
- **Proposta.** Prima dell'08/10 lo sviluppatore aggiorna la verità nota. Toglie o rietichetta il 661135 e, nello stesso
  giro, ricontrolla le voci di A3 e di M8. Oggi gli altri 52 bandi della tabella sono ancora candidati.

**A3. La verità nota è stata misurata senza il modello, la produzione gira con il modello.** *Difetto di metodo.*
- **Cosa non va.** La tabella è stata costruita con `--senza-modello` (lo dice il suo commento). In produzione il modello
  è acceso per difetto (`VERIFICA_STATO_USA_MODELLO=true`). Su alcune pagine una lettura del modello trasforma «non
  decisiva» in «confermato» o «smentito». Il report stampa la colonna `METODO`, quindi chi legge può vedere chi ha
  letto; ma l'esito e il confronto con la verità nota non ne tengono conto.
- **Perché conta.** Sei bandi attesi «non decisiva» (18315, 18387, 18423, 3042, 110821, 10258) rischiano difformi false.
  Peggio: il confronto potrebbe non misurare quello che si crede.
- **Proposta (Decisione).** Le strade sono due:
  - giudicare a mano, l'08/10, le difformi di questi sei bandi, guardando la colonna `METODO`;
  - rifare la verità nota con il modello acceso.

  La prima è la più prudente.

**A4. Il comando manuale `fondi-doppioni` può fondere tutto, senza tetto e senza guardie.** *Rischio.*
- **Cosa non va.** Lanciato senza `--limit` e senza `--dry-run`, con il resolver attivo come in produzione, fonde
  **tutte** le coppie trovate: il budget si controlla solo se `limit` non è vuoto (`fonte_ufficiale.py:2915-3030`). In
  più:
  - usa tutti i criteri esatti, compresi «stessa chiave esterna» e «stesso atto», esclusi dall'automatico
    (`gemelli.py:1105` contro `:1241`) perché una delibera può approvare più avvisi;
  - non ha nessuna delle guardie di prudenza del passo automatico (pagine hub, titoli, anni e lotti).

  La documentazione dice che `--limit 0` vuol dire «solo report», ma non dice che **senza** `--limit` fonde tutto.
  Dedotto leggendo il codice, non provato.
- **Perché conta.** Una fusione è quasi irreversibile: `bando_separa` la annulla, ma gli eventi restano (§4.9). BandoFit
  la vede subito, senza preavviso.
- **Proposta.** Fino alla correzione, mai lanciarlo senza `--dry-run`, e scriverlo in RIPRESA. Lo sviluppatore lo rende
  sicuro: senza `--limit` solo report, più le stesse guardie del passo automatico.

**A5. Due fonti intere non hanno mai prodotto un bando, e gli errori delle fonti non si vedono.** *Difetto.*
- **Cosa non va.** Italia Domani (450) e Incentivi.gov.it (451) risultano «pronte» e attive, ma in 87 letture (89 dopo il
  giro delle 12) hanno sempre restituito 0 elementi, e non hanno nessuna riga in `bando`. Dal Mac gli indirizzi
  rispondono e gli adattatori funzionano: il guasto è sul server (forse un blocco o un timeout; **non verificato**). In
  generale 25 fonti su 77 restituiscono 0 elementi, e 22 di queste da sempre. Il giro però segna «0 fonti in errore»,
  perché quasi tutti i lettori catturano l'errore e restituiscono una lista vuota. In più le fonti che vanno in errore
  non scrivono nemmeno una riga in `fonte_run`.
- **Perché conta.** Si perdono intere famiglie di bandi senza che nessun allarme lo dica. C'è anche un rischio nascosto:
  se Incentivi ripartisse così com'è configurata, porterebbe in un giro solo **oltre 6.000 schede** (stima
  dell'indagine, non ricontata), quasi tutte vecchie. Il preprocess e l'enrich pagherebbero il modello su tutte, senza
  tetto né per giro né di spesa (§3.3.7, M1), e il giro potrebbe durare ore, oltre le 4 ore del lucchetto.
- **Proposta.**
  1. Leggere i log del server per 450 e 451.
  2. Far distinguere ai lettori «fonte vuota» da «fonte rotta», e aggiungere a `salute` un codice per «fonte a zero da N
     giri».
  3. Prima di riaccendere Incentivi, limitare la query ai bandi aperti e mettere un tetto ai bandi nuovi per giro.

**A6. Il resolver lavora con metà degli strumenti, e la lista bianca blocca 353 bandi.** *Difetto e Decisione.*
- **Cosa non va.** Due problemi distinti:
  - **Strumenti scollegati.** La cascata descritta (sonda gratuita sul sito dell'ente, ricerca a pagamento, arbitro LLM,
    SEDIA) **non è collegata** (`fonte_ufficiale.py:2301-2332`). Il resolver si ferma ai link già noti, alla scheda di
    ObiettivoEuropa e al gemello. I ricontrolli a 14 e 60 giorni ripetono quasi sempre lo stesso lavoro.
  - **Lista bianca troppo stretta.** È un cancello duro: un dominio «sconosciuto» non può mai diventare fonte trovata.
    353 bandi pubblicati hanno un link funzionante solo su domini fuori lista: fondazioni bancarie (Cariplo, CRT,
    Compagnia di San Paolo), finanziarie regionali (Finpiemonte, Sviluppo Toscana), Simest, Sardegna Ricerche, Erasmus+.
    Spesso sono proprio l'ente che eroga il bando. IndicePA non li conterrà, perché sono soggetti privati.
- **Perché conta.** Questo tiene 1.050 bandi «in verifica» e 521 «non trovati», e accende l'allarme permanente
  «fonti_da_verificare» (M3). Senza fonte trovata il monitor e la verifica non hanno una pagina da leggere.
- **Proposta.**
  1. Decidere se collegare almeno la sonda gratuita (Decisione).
  2. Aggiungere a mano alla lista bianca, dopo un controllo uno per uno, i domini dei soggetti privati che erogano
     davvero bandi.
  3. Correggere la descrizione del modulo, che oggi racconta una macchina che non gira.

  Il punto è legato alla decisione aperta §4.1 c di RIPRESA.

Fonti: `scraper_bandi/app/verifica_stato.py`; `fonte_ufficiale.py`; `gemelli.py`; `bando_runner.py`; `scrapers/`;
`scraper_config.py`; `telemetria.py`; tabelle `fonte_run`, `bando_link`, `bando_evento`, `monitoraggio_riepilogo`;
RIPRESA §1 e §3.1.

### 8.2 Gravità media

#### Soldi e sorveglianza

**M1. La spesa principale non è contata, e il tetto mensile non esiste nei fatti.** *Difetto.*
- **Cosa non va.** La SEO (Opus, fino a due chiamate per bando, più il Firecrawl con cui legge la pagina), il
  preprocess, le sette chiamate dell'enrich, il ripiego Sonnet e il Firecrawl dello scrape non registrano il costo. La
  riga del giro segna 0 $ per tutti questi passi. Il tetto mensile non lo verifica nessun passo: `bilancio.verifica` lo
  controlla solo se riceve i consumi del mese, e nessuno glieli passa. I tetti «giornalieri» del resolver contano solo
  il suo giro, non l'intera giornata.
- **Perché conta.** Il conto vero esiste solo nelle console di Anthropic e Firecrawl. Un'ondata di bandi nuovi
  chiamerebbe il modello senza limiti (A5, Incentivi).
- **Proposta.** Lo sviluppatore registra il costo di ogni chiamata anche in questi passi e collega il tetto mensile.
  Intanto Michele guarda le console, almeno prima del 05/10, quando si rinnova il piano di Firecrawl.

**M2. Nessun limite ai tentativi della SEO.** *Difetto.*
- **Cosa non va.** Un bando che fallisce la validazione resta «enriched» e ripaga Opus a ogni giro, quattro volte al
  giorno. La colonna `tentativi_seo` esiste dalla migrazione 01, ma nessun codice la usa (compare solo in un commento di
  `db.py`).
- **Perché conta.** Una spesa che si ripete senza fine e che, per M1, non si vede.
- **Proposta.** Contare i tentativi e fermarsi dopo un numero fisso (per esempio 3), scrivendo il motivo.

**M3. `salute` ha due allarmi sempre accesi.** *Difetto di taratura.*
- **Cosa non va.** Due allarmi non si spengono mai:
  - «fonti_da_verificare»: 27 su 57 pubblicati della settimana hanno la fonte «in verifica», il 47% contro una soglia
    del 30% (ricontato);
  - quasi certamente «configurazione:indicizzazione», cioè IndexNow senza chiave.

  Il comando esce sempre con errore.
- **Perché conta.** Un allarme nuovo non si distingue dal rumore, quindi il semaforo non serve.
- **Proposta.** Risolvere IndexNow (M4) spegne il secondo. Per il primo (Decisione): o si attacca la causa (A6), o si
  cambia la soglia in modo dichiarato e motivato.

**M4. IndexNow è rotto per tutto il sito, e i bandi nuovi non vengono mai segnalati.** *Difetto.*
- **Cosa non va.** `/api/indexnow-key` risponde 404: la variabile `INDEXNOW_API_KEY` manca nella build del sito. La
  stessa variabile serve il file `/<chiave>.txt` che IndexNow controlla, quindi non si possono verificare nemmeno le
  notifiche di interpelli e selezione. In più il passo SEO non segnala mai i bandi appena pubblicati: il giro segnala
  solo gli slug che gli step restituiscono, e oggi lo fa solo il monitor.
- **Perché conta.** I motori di ricerca trovano i bandi nuovi solo passando dalle sitemap, quindi più tardi.
- **Proposta.** Michele mette la chiave nel `.env` della root **prima** della build e ricostruisce il sito. Il sender
  legge la stessa variabile: dopo aver caricato `scraper_bandi/.env`, carica anche il `.env` della cartella da cui parte,
  quindi la chiave nella root può bastare anche a lui; dipende dalla cartella di lavoro del servizio (**non verificata**),
  e per sicurezza la si mette anche in `scraper_bandi/.env`, poi un riavvio. Lo sviluppatore fa segnalare alla SEO gli
  slug appena pubblicati.

#### L'attivazione del giro 2

**M5. Un solo interruttore accende cinque cose diverse.** *Rischio di progetto.*
- **Cosa non va.** `VERIFICA_STATO_MODALITA=attivo` accende insieme:
  1. le scritture della verifica dello stato;
  2. le fusioni automatiche dei doppioni (52, al massimo 10 al giorno);
  3. l'import di circa 22.355 domini da IndicePA (prova dell'01/10);
  4. la sosta dei bandi nuovi;
  5. la fusione prima della pubblicazione.
- **Perché conta.** Se una di queste va male non si può spegnere da sola. Le fusioni vanno annunciate a BandoFit con 7
  giorni di anticipo.
- **Proposta.** Prima dell'attivazione, separare almeno fusioni e IndicePA con interruttori propri, per accenderli uno
  alla volta (lavoro dello sviluppatore). In alternativa (Decisione) accettare l'accensione unica, sapendo cosa parte.
  Le fusioni da sole si possono già spegnere con `GEMELLI_FUSIONI_PER_GIRO=0`, ma solo quelle del giro delle 06, non
  quelle prima della pubblicazione.

**M6. All'attivazione l'effetto sul pubblico sarà forte.** *Rischio.*
- **Cosa non va.** Al primo giro attivo i 96 bandi illeggibili vengono segnati come «esaminati» subito, senza scaricare
  niente. Quelli pubblicati da più di 7 giorni prendono il bollino «senza conferma» (la regola dà il bollino dall'8°
  giorno: `stato-bando.ts`, regola A7-A8). Poi, giro dopo giro, lo prende gran parte dei 426 aperti senza scadenza e dei
  163 «in apertura» senza data. L'avviso di `salute` sopra il 60% scatterà quasi certamente.
- **Perché conta.** Centinaia di schede cambiano aspetto in pochi giorni. Lo vedono i lettori e BandoFit. E tornare in
  ombra non toglie i bollini già accesi (§9.4).
- **Proposta.** Michele deve saperlo prima di attivare, e il messaggio a BandoFit dovrebbe dirlo con i numeri.

**M7. Le letture rischiano di non bastare per l'08/10.** *Rischio.*
- **Cosa non va.** Con 40 letture per giro, due giri al giorno (06 e 18), servono circa 13 giri per leggere una volta i
  496 candidati leggibili. Due bandi della verità nota (1072674 e 1072686) verrebbero letti solo al 12° e al 13° giro,
  cioè fra il 07 e l'08/10. Basta un giro interrotto dal tetto di 900 secondi per mancarli.
- **Perché conta.** Il controllo dell'08/10 sarebbe incompleto.
- **Proposta.** Se quei due bandi non risultano letti, rinviare il controllo di qualche giorno. È meglio che alzare i
  tetti all'ultimo momento.

**M8. Tre bandi attesi «segnalato» non hanno il segnale.** *Rischio.*
- **Cosa non va.** 17883, 18186 e 18312 sono attesi come «assenti dal listing» di ObiettivoEuropa, ma oggi non hanno
  nessun segnale (ricontato: `segnale_aggregatore` vuoto; gli altri due attesi «segnalato», 17773 e 18178, ce l'hanno).
  Il 18312 è anche illeggibile.
- **Perché conta.** Senza il segnale entro l'08/10 risulteranno difformi.
- **Proposta.** Controllarli il 07/10. Se serve, rivederli insieme alla correzione di A2.

**M9. Due difetti della verifica che si vedranno solo in attivo.** *Difetto.*
- **Cosa non va.** Due problemi separati:
  - `migrazione_presente()` si basa sullo schema che `db.controllo` legge una volta per processo, e ricorda anche una
    lettura fallita (`db.py:1115-1129`). Se il DB è giù al primo accesso, la verifica resta «saltata» fino al riavvio, e
    l'allarme che dovrebbe segnalarlo è spento;
  - nella fase d'ingresso la scadenza trovata si scrive senza controllarla contro la data di pubblicazione. Il controllo
    del DB fa fallire l'aggiornamento, si perde anche un eventuale «chiuso», e il tentativo si ripete a ogni giro.
- **Perché conta.** Il primo nasconde un guasto. Il secondo produce errori ripetuti in attivo.
- **Proposta.** Correggerli entrambi prima dell'attivazione.

#### Stato dei bandi

**M10. Aperti senza scadenza e «in apertura» senza data restano così per sempre.** *Difetto di dati.*
- **Cosa non va.** Ci sono 426 aperti senza scadenza e 163 «in apertura» senza data. Il job orario apre un bando solo
  con una data di apertura **verificata**, che nessun pubblicato «in apertura» ha: in tutta la storia ha aperto 0 bandi.
  In ombra questi bandi non hanno nemmeno il bollino. Una delle radici è nel prompt del preprocess: «Senza indizi
  precisi e tipo "Opportunità": "aperto"» (`preprocessor.py:247`). Lo studio del 30/09 stima che il 16% degli aperti
  senza scadenza sia già chiuso.
- **Perché conta.** Il lettore vede «aperto» su bandi che forse non lo sono più.
- **Proposta.** Il rimedio principale è l'attivazione della verifica. Per i bandi nuovi va anche rivisto il prompt:
  «senza indizi» dovrebbe dare «non so», non «aperto» (Decisione).

**M11. Lo status «2» di ObiettivoEuropa scavalca le date.** *Difetto o Decisione.*
- **Cosa non va.** Una scheda di ObiettivoEuropa con status «2» diventa sempre «in apertura», anche se l'apertura è già
  passata e la scadenza è futura, cioè anche se il bando è aperto. Il sito la mostra «in apertura» per tutta la
  finestra di presentazione. Il significato dello status «2» viene dallo studio del 30/09: **non verificato** in modo
  indipendente. In più 53 schede con status «2» sono già pubblicate come «aperto» e nessuno le rivede.
- **Perché conta.** Contraddice la regola generale «le date vincono».
- **Proposta.** Far vincere le date anche qui.

**M12. Un «chiuso» del modello resta fermo anche con una scadenza futura.** *Difetto.*
- **Cosa non va.** I bandi 2773 (scadenza 26/07/2027) e 1262487 (scadenza 01/11/2026) sono «processed chiusi»
  (ricontato). Nessun passo ricontrolla i processed.
- **Perché conta.** Due bandi forse aperti non vengono pubblicati (**non verificato**: le loro pagine non sono state
  aperte).
- **Proposta.** Riconciliare anche verso «aperto» quando la scadenza validata è futura, e controllare a mano questi due.

**M13. Sospensione e revoca hanno buchi di progetto.** *Rischio, oggi 0 casi.*
- **Cosa non va.** I buchi sono elencati in RIPRESA §4.1 i:
  - un sospeso non ha un'uscita realistica;
  - non c'è un percorso per correggere un errore;
  - la scheda dà la precedenza agli eventi sulla colonna, quindi c'è una seconda fonte dello stato (§5.6);
  - il monitor riscarica un revocato per sempre;
  - c'è uno stallo con l'errore 23514.
- **Perché conta.** Il primo bando sospeso per davvero potrebbe restare «Sospeso» per sempre.
- **Proposta.** Chiuderli prima di applicare eventi di sospensione o revoca.

**M14. Il rifiuto è definitivo e il perimetro editoriale non è scritto.** *Decisione.*
- **Cosa non va.** Un bando rifiutato non viene mai rivisto, nemmeno se la pagina cambia. Il prompt è pensato per
  «finanziamenti UE 2021-2027», così i bandi di fondazioni e quelli non UE vengono scartati: almeno 6 schede di
  ObiettivoEuropa a settembre.
- **Perché conta.** È una scelta editoriale che nessuno ha mai preso in modo esplicito.
- **Proposta.** Michele decide il perimetro. Lo sviluppatore lo scrive nel prompt e nella documentazione.

#### Pubblicazione e doppioni

**M15. Doppioni ancora visibili.** *Difetto visibile.*
- **Cosa non va.** Restano visibili:
  - le 52 fusioni automatiche previste;
  - le 41 coppie ObiettivoEuropa/fonte ufficiale da fondere a mano (numero di RIPRESA, **non ricontato**);
  - 33 link e 29 righe di calendario pubblicati due volte.

  Le righe di calendario si sdoppiano quando l'ente sposta una riga o ripubblica il file, perché l'identità di quelle
  righe dipende dalla posizione (§2.8).
- **Perché conta.** Il lettore vede due schede per lo stesso bando.
- **Proposta.** Le fusioni automatiche partono all'attivazione (circa 6 mattine). Le coppie a mano solo dopo un
  `--dry-run` e un backup. Per i calendari serve un'identità che non dipenda dalla posizione della riga (sviluppatore).

**M16. Il controllo dei doppioni di ObiettivoEuropa è troppo sbrigativo.** *Rischio.*
- **Cosa non va.** Rifiuta un bando se la sua fonte ufficiale coincide con quella di un pubblicato, ma non ha la guardia
  sulle pagine hub e sui lotti. È sempre attivo, anche ora che il resto è in ombra. Il rifiuto è permanente e
  silenzioso. Oggi 35 indirizzi ufficiali sono condivisi da più pubblicati, fino a 11 (ricontato).
- **Perché conta.** Due lotti dello stesso ente possono condividere la pagina: si perderebbe un bando vero.
- **Proposta.** Dare a questo controllo le stesse guardie del passo «gemelli» e contare i rifiuti in `salute`.

**M17. `seo --rerun-completed` in attivo fonderebbe pubblicati senza freni.** *Rischio.*
- **Cosa non va.** Rielaborando i bandi già pubblicati, la fusione prima della pubblicazione li fonderebbe subito: senza
  tetto, senza l'ordine corretto per scegliere il principale, senza avviso.
- **Perché conta.** Le fusioni partirebbero da un comando che serve a tutt'altro.
- **Proposta.** Escludere i pubblicati da quella fusione.

#### Fonti, link e domini

**M18. I link non vengono mai ricontrollati.** *Difetto rispetto al contratto.*
- **Cosa non va.** `link-verifica` non è nel giro, e il ritiro degli allegati morti da parte del monitor non è collegato.
  6.173 link pubblicabili su 6.206 sono stati verificati l'ultima volta il 23-24/09. Il contratto promette invece che
  «ogni riga leggibile ha risposto 2xx all'ultimo controllo».
- **Perché conta.** BandoFit e il sito possono mostrare link ormai morti.
- **Proposta.** Mettere `link-verifica` nel giro, per esempio una volta a settimana, oppure correggere la promessa del
  contratto.

**M19. La scheda di ObiettivoEuropa, una volta letta, non viene mai riletta.** *Difetto.*
- **Cosa non va.** La prima lettura avviene («scoperta»). Dopo, la regola «rileggi se cambia lo status o la scadenza»
  confronta il dato con sé stesso (`prima=grezzo, dopo=grezzo`, `fonte_ufficiale.py:2340-2343`), quindi non scatta mai.
- **Perché conta.** Un cambiamento sulla scheda non arriva mai al resolver.
- **Proposta.** Passare alla regola il dato del giro precedente.

**M20. Dopo il primo import di IndicePA i bandi già giudicati non vengono rivalutati.** *Miglioria.*
- **Cosa non va.** I «non trovati» tornano in coda solo il 23/11.
- **Perché conta.** Per settimane non si raccoglie quello che l'import potrebbe dare (51 domini dei nostri link
  diventano verificanti, secondo la misura del 30/09).
- **Proposta.** Dopo il primo import in attivo, lanciare a mano `risolvi-fonte --forza --anche-oggi` sul server, oppure
  legarlo all'import. Attenzione: `--forza` toglie ogni filtro, quindi va lanciato con un `--limit` e a lotti.

**M21. I pattern regione.\*.it, provincia.\*.it e comune.\*.it sono troppo larghi.** *Difetto.*
- **Cosa non va.** `comune.bandifacili.it` o `regione.miosito.it` risultano «istituzionali» e possono rendere
  «verificato» un evento.
- **Perché conta.** Un sito qualunque con il nome giusto passa per ufficiale.
- **Proposta.** Restringere i pattern ai domini istituzionali noti.

**M22. L'evento «sparito dalla fonte» non può mai nascere.** *Difetto.*
- **Cosa non va.** Il confronto guarda solo le righe già presenti nel listing, che per definizione sono tutte «viste».
  Oggi la sorveglianza delle assenze esiste solo per ObiettivoEuropa (nel giro di oggi `spariti` vale 0).
- **Perché conta.** Un bando tolto dalla fonte resta pubblicato come se niente fosse.
- **Proposta.** Confrontare con tutte le righe della fonte, dove la lettura è completa.

**M23. Lo stesso segnale si ripete a ogni giro.** *Difetto.*
- **Cosa non va.** Quando la data dell'etichetta di ObiettivoEuropa è diversa dalla colonna, il segnale si ripete finché
  qualcuno non corregge. Sono 1.693 eventi identici su 70 bandi soli (su 3.004 eventi `segnale_fonte` in tutto).
- **Perché conta.** Il registro degli eventi si gonfia senza dare informazioni nuove.
- **Proposta.** Emetterlo una volta sola per ogni valore.

**M24. La fonte 276 legge il PDF sbagliato.** *Difetto.*
- **Cosa non va.** Il «calendario Umbria» legge un regolamento UE dell'Emilia-Romagna. Ha prodotto 1.500 righe
  spazzatura (tutte rifiutate), 25 riscritture e 25 eventi a ogni giro.
- **Perché conta.** Lavoro e rumore inutili a ogni giro.
- **Proposta.** Correggere il selettore, oppure saltare la fonte.

**M25. Fonti saltate o escluse in silenzio.** *Difetto.*
- **Cosa non va.** Due problemi:
  - 8 fonti pronte non hanno voce nel registro e vengono saltate a ogni giro: Sardegna FESR e FSE+, Bolzano, PNES (2),
    Interreg CH, Veneto FESR (2, nuove);
  - la raggiungibilità si riprova a ogni giro. Una fonte lenta o protetta dai bot diventa «connection error» e quel giro
    non viene letta. Può succedere anche a 4 fonti della Lombardia configurate apposta per aggirare i blocchi. Lo si
    vede già oggi: 14 fonti in errore al giro di avvio, 15 a quello delle 12.
- **Perché conta.** Fonti intere entrano ed escono dalla lettura senza che nessuno lo sappia.
- **Proposta.** Aggiungere le voci mancanti nel registro. Non escludere una fonte per un solo fallimento. Contare
  entrambe le situazioni in `salute`.

**M26. Identificatori e famiglie sbagliati.** *Difetto.*
- **Cosa non va.** Due problemi:
  - `chiave_esterna`, pensata per seguire un bando quando la fonte cambia indirizzo, non viene mai scritta (0 righe,
    ricontato), al contrario di quanto dice il codice;
  - Italia Domani e Incentivi sono trattate come ObiettivoEuropa (`FONTI_OE = (449, 450, 451)`,
    `fonte_ufficiale.py:1811`, usato anche dalla verifica).
- **Perché conta.** Un cambio di indirizzo crea un bando nuovo. Le regole pensate per ObiettivoEuropa finiscono sulle
  fonti sbagliate.
- **Proposta.** Scrivere la chiave esterna e separare le tre fonti.

**M27. L'enrich classifica leggendo solo l'inizio della pagina.** *Miglioria.*
- **Cosa non va.** Usa i primi 2.500 caratteri grezzi, spesso pieni di menu. È lo stesso difetto già corretto nel
  preprocess.
- **Perché conta.** Regioni, settori e beneficiari possono essere sbagliati.
- **Proposta.** Usare il testo ripulito e la scelta delle sezioni, come nel preprocess.

#### Sito e BandoFit

**M28. La 07 è bloccata e il blocco si allarga.** *Difetto rispetto al contratto.*
- **Cosa non va.** Il sito chiede ancora `link_candidatura`, `link_candidatura_source` e `allegati`, che la 07 toglie.
  Spostare il sito su `bando_link` oggi non basta:
  - dei 104 moduli di candidatura estratti (`link_candidatura_source = extracted` sui pubblicati), solo 1 ha una riga
    «candidatura» pubblicabile;
  - 151 bandi sui 160 che hanno allegati li perderebbero;
  - nessun codice crea righe «candidatura» pubblicabili.

  Intanto la chiave pubblica legge ancora l'intera tabella `bando`: dati grezzi su 1.878 righe e link a ObiettivoEuropa
  su 1.772. Contraddice la promessa §1.7 del contratto, che però ammette questa fase di passaggio.
- **Perché conta.** La 07 non ha una data, e ogni giorno il divario cresce.
- **Proposta.** Prima il codice che popola `bando_link` (candidature e allegati), poi la migrazione del sito, poi la 07
  (§9.6).

Fonti: `scraper_bandi/app/{bilancio,seo_skill,bando_seo_runner,gemelli,verifica_stato,fonte_ufficiale,dominio_ufficiale,segnali,bando_runner,preprocessor,enricher,reachability,db}.py`;
`backend/app/bandi_pipeline.py`; `src/lib/supabase-bandi.ts`; `src/lib/stato-bando.ts`;
`backend/sql/bando_v11_07_fase_d.sql`; RIPRESA §4.1; DB in sola lettura.

### 8.3 Gravità bassa

**Codice della pipeline**

| # | Cosa non va | Perché conta | Proposta | Tipo |
|---|---|---|---|---|
| B1 | La fase d'ingresso della verifica ordina per id, senza dare la precedenza ai bandi mai letti | Righe ferme possono occupare il tetto a ogni giro | Prima le righe mai lette | Difetto |
| B2 | Il gate G9 lascia passare un evento di stato senza transizione; il DB poi lo rifiuta (23514) | Evento registrato e respinto, rumore | Scartarlo nel gate | Difetto |
| B3 | La SEO fonde se trova «una sola» corrispondenza, ma conta anche i criteri non automatici | Un gemello per URL con anche un criterio «atto» viene pubblicato invece che fuso | Contare solo i criteri automatici | Difetto |
| B4 | Il conteggio delle righe per URL nei gemelli non comprende mai i fusi (il commento in `gemelli.py` dice il contrario) | Dopo una fusione, la coppia rimasta può fondersi | Allineare codice e intenzione | Difetto |
| B5 | Il controllo delle collisioni di slug non legge lo storico | In futuro: errore e Opus ripagato a ogni giro (oggi non succede) | Leggere anche lo storico | Rischio |
| B6 | L'esempio di slug nel prompt ha un accento (che il codice poi rifiuta, ripiegando sullo slug dal titolo); 2 slug pubblicati superano gli 80 caratteri | Ripieghi inutili, slug lunghi | Esempio senza accenti, controllo della lunghezza | Miglioria |
| B7 | «fallback_source» si produce ancora (14 a settembre, 1 a ottobre; 41 pubblicati in tutto); 94 link di candidatura in tabella puntano a ObiettivoEuropa (il pubblico non li vede) | Contro la regola del prompt | Validare il link contro gli URL provati | Difetto |
| B8 | Gli allegati della SEO sono vuoti per tutti i 45 pubblicati dal 25/09 (causa **non verificata**) | Allegati mancanti sulle schede nuove | Indagare | Difetto |
| B9 | Fusione prima della pubblicazione riuscita a metà: la riga resta «enriched» ma fusa | Opus pagato per una scheda che non si vedrà mai | Gestire il caso | Rischio |
| B10 | In attivo un bando «senza appiglio» resta fermo per sempre senza avviso | Bando perso in silenzio | Contarlo in `salute` | Rischio |
| B11 | La vecchia deduplicazione `canonical_key` è codice morto e incompatibile con i trigger | Accenderla produrrebbe solo errori | Toglierla | Miglioria |
| B12 | Il punteggio di confidenza non fa da soglia: passano anche bandi a 0,5 | Bandi poco certi pubblicati | Decidere una soglia | Decisione |
| B13 | La rifinitura dell'enrich decide lo stato con Haiku senza validare le date; una chiamata di classificazione fallita lascia il campo vuoto senza riprovare (11 senza regioni, 11 senza beneficiari) | Dati più poveri, non distinguibili da «nessuno» | Riprovare o segnare il campo | Difetto |
| B14 | «on_arrival» di ObiettivoEuropa diventa «Preavviso» (`scrapers/adapters/obiettivo_europa.py:14`), ma lo studio del 30/09 dice che vuol dire «a sportello» | Indizio sbagliato al modello | Correggere l'adattatore | Difetto |
| B15 | Il ripiego Sonnet non applica le regole del giro 2 (status «2», etichetta, ore); il prompt chiede «ragionamento esteso», ma la chiamata non lo attiva | Regole diverse per i bandi senza pagina | Allineare | Difetto |
| B16 | 569 «processed» chiusi mai archiviati (570 dopo il giro delle 12: la coda cresce); la documentazione del backfill dice che vengono «ripescati», ed è falso | Coda che non si svuota | Decisione RIPRESA §4.1 e (§9.8) | Decisione |
| B17 | Il lucchetto orfano del giro si libera anche se è scaduto da giorni, e il giro di avvio salta | Fino a 6 ore senza giri dopo un lungo fermo | Guardare la scadenza | Difetto |
| B18 | Giro di avvio saltato dopo un crash: esito «saltato» ma `saltato_per_lock=false` | Due segnali in contrasto | Allinearli | Difetto |
| B19 | La riga del giro non somma il costo e gli stop della verifica (stanno un livello più sotto) e lascia vuota la colonna «motivo» | Sottostima e motivo nascosto | Leggere il livello giusto | Difetto |
| B20 | Le chiamate al modello della verifica non contano fra le «classificazioni» | Il tetto di 30 al giorno non le limita | Contarle | Difetto |
| B21 | Ricontrolli e verifica seguono `MONITOR_GIRI` senza dirlo | Cambiare gli orari del monitor sposta anche loro | Documentare o separare | Miglioria |
| B22 | La regola I5 accetta come conferma anche una lettura del modello (A2 no); un «smentito» del modello non compare nella vista | Bollino senza spiegazione visibile | Chiarire se è voluto | Decisione |
| B23 | 539 pagine con l'impronta vecchia vengono solo riallineate al primo controllo | Un cambiamento nel frattempo si perde (prezzo accettato) | Nessuna, salvo decisione diversa | Decisione |
| B24 | Il resolver scrive due righe identiche, «nuovi» e «ricontrolli»; `link_scritti` vale sempre 0; il flag di possibile proroga non lo usa nessuno; il tipo «atto» non nasce mai; 5.833 eventi interni «non trovata» crescono senza uso | Telemetria che confonde, registro gonfio | Pulizia | Miglioria |
| B25 | `europa.eu` (senza sottodominio) non è riconosciuto; `link-verifica` usa solo la lista nera di base; una fonte trovata punta a una riga «candidatura» (bando 258890) | Casi limite | Correggere | Difetto |
| B26a | L'adattatore di Incentivi scarta `ds_last_update` | Il segnale non può mai scattare | Correggere l'adattatore | Difetto |
| B26b | Il Firecrawl dello scrape è fuori dai contatori (§2.10) | Crediti spesi senza conto | Farlo passare dallo scarico | Difetto |
| B26c | La fonte 302 estrae con un modello e cambia a ogni lettura (121 eventi) | Rumore e crediti a ogni giro | Rivedere la strategia | Difetto |
| B26d | Manca la guardia dei 50 risultati di ObiettivoEuropa durante la lettura | Una sessione anonima passerebbe | Impostarla nel registro | Rischio |
| B26e | Il login di ObiettivoEuropa usa una pausa bloccante | Blocca il processo fino a 3 minuti | Pausa non bloccante | Difetto |
| B27 | `fonte_run` ha colonne mai riempite (per esempio `pipeline_run_id`, vuoto anche oggi); lo scrape crea controlli anche per i rifiutati (1.987) | Non si distingue «vuota» da «rotta» | Riempirle | Miglioria |
| B28 | Picchi di coda: 690 ricontrolli l'08/10 e 847 il 23/11 | Circa 6-7 giorni per smaltire ogni picco | Distribuire le date | Miglioria |
| B29 | L'import di IndicePA accetta host di una sola etichetta («www.it» renderebbe verificante ogni .it) | Agisce solo in attivo | Guardia sugli host | Rischio |
| B30 | La misura di «vista lenta» chiede colonne che la 07 toglie | Dopo la 07 fallisce in silenzio | Aggiornare l'elenco | Rischio |
| B31 | La 13 permette alla chiave pubblica di leggere 9 colonne grezze di `bando_controllo` (oggi vuote) | Aggira i filtri della vista | Restringere | Rischio |
| B32 | Le chiusure «worker» degli ultimi 7 giorni contano anche monitor e correzioni manuali; gli «host frenati» contano lettori, non host; il riepilogo chiama «altro» domini, gemelli e verifica d'ingresso | Misure di `salute` imprecise | Correggere i conteggi | Difetto |
| B33 | Gli eventi d'ombra entrano con un INSERT diretto: è Python, non il DB, a decidere se sono «verificati» | La garanzia regge solo sul codice | Un trigger di controllo | Rischio |
| B34 | La migrazione 12 non apre una transazione esplicita (verificato: niente `BEGIN; … COMMIT;`) | Già applicata; vale come lezione | Per le prossime, sempre BEGIN/COMMIT | Miglioria |
| B35 | Nomi che confondono: due «resolver»; tre «G3»; `monitor_modello` cercato ma inesistente; il lucchetto di `seo-rigenera` si chiama come quello del giro | Errori di lettura del codice | Rinominare o documentare | Miglioria |

**Sito e API**

| # | Cosa non va | Perché conta | Proposta | Tipo |
|---|---|---|---|---|
| S1 | Lo status dell'API usa una regola semplificata, senza ora e senza apertura verificata | Per al massimo un'ora l'API può dire «open» quando il sito dice «chiuso» | Usare lo stato effettivo della vista | Difetto |
| S2 | `deadline_at` è sempre vuoto per i bandi, anche per i 42 che hanno l'ora | L'ora non arriva a chi usa l'API | Valorizzarlo | Difetto |
| S3 | La guida dell'API consiglia `updated_since`, ma il motivo «da verificare» cambia senza muovere `updated_at` | Chi sincronizza perde i cambi | Muovere la data o avvisare | Difetto |
| S4 | 10 pubblicati hanno il contenuto vuoto (ricontato): la scheda non mostra né testo né avviso | Pagine bianche | Avviso, o rigenerazione | Difetto |
| S5 | `/bandi?stato=sospeso` mostra la chip «Sospeso» sopra una lista non filtrata (pagina noindex) | Incoerenza visibile | Ignorare il filtro anche nella chip | Difetto |
| S6 | `/bandi` con il DB in errore risponde 200 e indicizzabile; la scheda risponde 503 | Una pagina d'errore può finire nei motori | Rispondere 503 | Difetto |
| S7 | `BANDI_FONTE_LETTURA` e `BANDI_STATI_ESTESI` mancano in `.env.example`; `scraper_bandi/.env.example` non elenca modalità, tetti e IndexNow | Chi rimonta il server non sa cosa impostare | Completare gli esempi | Documentazione |
| S8 | 4 eventi applicati non sono nel box (3 nuovi allegati, 1 proroga); 20 ammessi restano in arretrato; 79 eventi leggibili aspettano bandi mai pubblicati | Proroghe vere che il pubblico non vede | Decisione sull'arretrato | Decisione |
| S9 | 259 fonti «trovate» hanno il tipo vuoto (riconosciute per forma); 4 schede hanno un link di candidatura con provenienza «missing»; gli allegati con host sconosciuto passano nella vista | Un consumatore può fraintendere | Documentare nel contratto, correggere i dati | Documentazione |

**Documentazione** (è una delle cause della confusione)

| # | Cosa non va | Proposta |
|---|---|---|
| D1 | RIPRESA si contraddice e non è aggiornata: intestazione «aggiornato al 30 settembre»; «Configurazione in produzione» dà i 5 tipi non ancora attivi, mentre §1 dice deploy fatto; «Migrazioni applicate» non elenca 12 e 13; §2 non cita domini, verifica e gemelli; il calendario §4.3 prevede ancora un `domini --import` a mano «verso il 24/10», che dal giro 2 è automatico; numeri del 30/09. CLAUDE.md dice «Stato al 28/09» | Aggiornare RIPRESA e CLAUDE.md al 01/10; questa guida può servire da base |
| D2 | La documentazione dice «senza conferma dal 7° giorno»; il codice lo dà dall'8° (pubblicato da al massimo 7 giorni → nessun bollino) | Correggere `docs/api-v1.md` |
| D3 | Contratto DB: riga `job_orario` fuori dalla tabella; §10.2 senza le migrazioni 09, 10, 11; §5 dice IndicePA «automatico» (vero solo in attivo); §6.2 dice che un gemello nuovo «non viene mai pubblicato» (vero solo in attivo); elenco delle parti numerate più corto del codice; id massimo vecchio | Riallineare il contratto |
| D4 | Contratto del giro 2: «nessuna funzione nuova per anon» (falso: la 12 apre `monitoraggio_catalogo` e la 13 `bando_stato_da_verificare`); «una sola lettura per giro» (è un TTL di 45 minuti); `RIGHE_VISTA_MS` 20 contro 24; soglia di `ingresso_trattenuti` diversa | Correggere |
| D5 | Il codice della verifica: la verità nota parla di «due letture a 60 ore», ma ne basta una; `applica-eventi` dice «un tipo per volta», ma ne accetta molti; un ramo doppio in `cadenza()` | Correggere i commenti |
| D6 | Commenti e README vecchi: giri da «80 minuti» (`bandi_pipeline.py:58` e `:103`; la mediana vera è circa 7); «~108 fonti», «~200 link», «~90 al giorno»; enrich a 8 chiamate con le date; «markdown Firecrawl»; «unico punto di scarico»; «tre fonti ObiettivoEuropa»; portali del seed 20 contro 19 | Pulizia dei commenti |

Fonti: indagini «problemi» delle sette aree (`scraper_bandi/app/*`, `backend/app/*`, `src/lib/api-v1/*`,
`src/pages/bandi*`, `docs/*`); verifiche con curl e GET di sola lettura.

---

## 9. Prossimi passi

I passi sono in ordine di data. Per ciascuno si dice chi lo fa e cosa serve.

- **Michele**: decisioni, `.env`, migrazioni, comandi sul server, messaggi a BandoFit.
- **Sviluppatore**: modifiche al codice, sempre con commit e deploy (in una finestra sicura: 12:30-16:30 o 19:00-22:30).

### 9.1 Il calendario in una tabella

| Quando | Passo | Chi | Cosa serve |
|---|---|---|---|
| **subito, in una finestra sicura** | **Giro 3**: migrazione 14 con la sua verifica, SQL di backfill dei link, deploy con le righe del `.env` e **un solo** riavvio del sender | Michele | RIPRESA §1, un passo alla volta |
| **un giorno dopo il deploy del giro 3** | Misura dei link (quante schede perderebbero ancora pulsante o allegati con la 07) | Sviluppatore | RIPRESA §1 |
| **oggi 01/10, 18:00** | Primo giro della verifica (fase «controlli»), in ombra: controllare che esista la riga e che `motivo_saltato` sia vuoto | Sviluppatore o Michele | Una lettura di `pipeline_run` (step `verifica_stato`) |
| **subito** | Seconda parte del messaggio a BandoFit, se non è già partita | Michele | `docs/bandi-monitor/richiesta-bandofit-giro-2.md`, con i numeri di §7.6 |
| **subito** | Scegliere come sorvegliare finché il pannello non c'è (A1) | Michele | Una decisione |
| **subito** | Chiave IndexNow (M4) | Michele | `.env` della root prima della build, `.env` del sender, un riavvio |
| **02/10, 06:00** | Primo import di IndicePA e primo passo «gemelli», in ombra | Sviluppatore (controllo) | Righe «domini» e «pipeline» in `pipeline_run`, con i contatori dei gemelli |
| **02/10** | Settimo giorno d'ombra del monitor: `report-ombra --dal 2026-09-24` e lettura a mano delle citazioni | Michele, sviluppatore | Comando in sola lettura sul server (§6.7) |
| **prima del 05/10** | Leggere il residuo di Firecrawl (il 05/10 si rinnova il piano) | Michele | Console di Firecrawl |
| **entro il 06/10** | Correggere la verità nota (A2, A3, M8) e i due difetti che si vedono in attivo (M9) | Sviluppatore | Modifica a `verifica_stato.py`, commit, deploy in finestra sicura. Il 661135 (A2) è sistemato nel codice del giro 3 (`confermato_da_stato`, §3.2-bis) |
| **entro il 06/10, facoltativo** | Separare gli interruttori di fusioni e IndicePA (M5) | Sviluppatore, su decisione di Michele | **Fatto nel codice del giro 3** (`GEMELLI_MODALITA`, `DOMINI_MODALITA`, §3.3.5): vale dal deploy |
| **07/10** | DNS della Basilicata (vedi §9.3 per il perché): `getent hosts portalebandi.regione.basilicata.it` dal server | Michele | Accesso al server |
| **07/10** | Controllare che i bandi 1072674, 1072686, 17883, 18186 e 18312 siano stati letti o segnalati (M7, M8) | Sviluppatore | Letture su `bando_controllo` |
| **08/10** | **Controllo `report-verifica-stato --verita`** | Michele lancia, sviluppatore legge | Comando in sola lettura sul server |
| **08-13/10** | Ondata dei ricontrolli del resolver: 690 bandi, 60 per giro alle 06 e alle 18 | Nessuno: è automatico | Solo guardare. Vale solo senza il giro 3: dal deploy i ricontrolli passano **tutti** i 960 candidati a ogni giro, nel tempo di `TEMPO_RICONTROLLI_S` |
| **dall'08/10, a condizioni** | **Attivazione** (`VERIFICA_STATO_MODALITA=attivo`) | Michele | §9.4 |
| **giorno dopo l'attivazione** | Verifica 7 della 05 e rivalutazione delle fonti | Michele | SQL Editor; un comando sul server (§9.5) |
| **09/10** | Quattordicesimo giorno d'ombra: nuovo `report-ombra`, poi decisioni RIPRESA §4.1 a e b | Michele, sviluppatore | Lettura a mano |
| **senza data** | Migrazione del sito e poi la 07 | Sviluppatore, poi Michele | §9.6 |
| **futuro** | Pannello su BandoFit | Michele | §9.7 |
| **23/11** | Seconda ondata dei ricontrolli: 847 bandi | Automatico | Solo guardare (solo senza il giro 3, che toglie la cadenza) |

Fonti: RIPRESA §1 (passi del giro 2), §4.3 (calendario); `docs/bandi-monitor/richiesta-bandofit-giro-2.md`;
`bando_controllo.prossimo_controllo_at` (690 e 847 ricontati); `backend/app/bandi_pipeline.py:118-125` (60
ricontrolli per giro).

### 9.2 Da fare subito (01-02/10)

1. **Il messaggio a BandoFit, seconda parte.** Riguarda stato da verificare, eventi e fusioni. Secondo RIPRESA va
   inviato subito dopo il deploy. **Non è verificato che sia partito, né quando.** Fino al giro 3 l'attivazione poteva
   venire solo **7 giorni dopo l'invio**. **Dal giro 3** vale un solo messaggio, mandato prima del deploy (RIPRESA §1,
   passo 1), senza attese. Conviene aggiungere i numeri:
   - 52 fusioni, circa 6 mattine a 10 al giorno;
   - l'ondata prevista di bollini «da verificare» (M6).

   *Chi:* Michele.
2. **La sorveglianza nel frattempo.** Va presa la decisione di A1. Senza, l'unico modo di sapere se il sistema gira è
   lanciare `salute` a mano o leggere il diario (§3.3.4). *Chi:* Michele.
3. **IndexNow.** Oggi è rotto anche per interpelli e selezione. La chiave va nel `.env` della root **prima** di `npm run
   build`. Poi rebuild, la chiave anche nel `.env` del sender (M4) e un riavvio in finestra sicura. *Chi:* Michele. La
   segnalazione dei bandi nuovi richiede invece codice. *Chi:* sviluppatore.
4. **Aggiornare RIPRESA e CLAUDE.md al 01/10** (D1). È la fonte dei passi a mano: se si contraddice, genera confusione.
   *Chi:* sviluppatore.
5. **Restano dal giro «ripresa ottobre»** (passi 5-9 di RIPRESA §1):
   - per una settimana, ogni mattina, la query di sorveglianza delle proroghe (RIPRESA §6);
   - `rigenera` e `seo-rigenera`, nella finestra sicura e mai durante un giro (`rigenera` non prende lucchetti, §3.3.1).

   **`rigenera` non risulta mai lanciato, nemmeno a secco**: scrive una riga `backfill:L7` in `pipeline_run` a ogni
   lancio, anche con `--dry-run` (`rigenera.py:722`), e nel diario non ce n'è nessuna. Per `seo-rigenera` non c'è
   nessuna riga `backfill:seo-rigenera`, quindi la scrittura in attivo **non risulta fatta**; la riga si scrive solo in
   attivo (`bando_seo_runner.py:1491`), quindi se sia stata fatta almeno la prova a secco **non è verificato**. *Chi:*
   Michele, con lo sviluppatore per la lettura delle proposte.

Fonti: RIPRESA §1 e §4.1 h; `pipeline_run` (elenco degli step: nessun `backfill:L7` né `backfill:seo-rigenera`);
`scraper_bandi/app/rigenera.py`; `bando_seo_runner.py`.

### 9.3 Prima dell'08/10: preparare il controllo

- **Correggere la verità nota** (A2). Il 661135 oggi è una difforme certa. Nella stessa modifica si ricontrollano 17883,
  18186 e 18312 (M8). Serve un commit e un deploy. *Chi:* sviluppatore.
- **Decidere come leggere le difformi «del modello»** (A3): i sei bandi attesi «non decisiva». La strada consigliata è
  valutarle a mano l'08/10, guardando la colonna `METODO` del report. *Chi:* Michele decide, lo sviluppatore prepara
  l'elenco.
- **Correggere i due difetti che si manifestano in attivo** (M9): il ricordo della migrazione mancante e la scadenza
  scritta senza controllo all'ingresso. *Chi:* sviluppatore.
- **Facoltativo: separare gli interruttori** (M5), per accendere fusioni e IndicePA dopo la verifica e non insieme.
  *Chi:* Michele decide, lo sviluppatore esegue.
- **07/10: il DNS della Basilicata.** Il 28/09 il DNS di `regione.basilicata.it` non rispondeva. L'08/10 cade il picco
  dei ricontrolli (690 bandi). Secondo RIPRESA, con quel DNS ancora rotto, il giro delle 06 dell'08/10 rischia circa
  100 minuti di ricontrolli su 101 indirizzi morti, proprio il giorno del controllo (stima di RIPRESA, non
  ricontrollata). Dal server: `getent hosts portalebandi.regione.basilicata.it`; se non restituisce un indirizzo, il DNS
  è ancora rotto. Lo stesso giorno controllare che 1072674 e 1072686 siano stati letti (M7). *Chi:* Michele il DNS, lo
  sviluppatore le letture.

Fonti: `scraper_bandi/app/verifica_stato.py` (verità nota, `confronta_verita`); `scraper_bandi/app/__main__.py`
(`COLONNE_REPORT`); RIPRESA §4.3 e righe 103, 1246, 1502-1503; `scraper_bandi/app/scarico.py` (host con errore DNS
saltati per il resto del giro, §2.10).

### 9.4 08/10: il controllo e l'attivazione

**Il controllo.** Sul server, in sola lettura:

```bash
cd ~/projects/news1/scraper_bandi
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app report-verifica-stato --verita
```

L'ultima riga deve dire `difformi: 0`. Con una sola «DIFFORME» non si attiva: si guarda il caso con lo sviluppatore.

*Chi:* Michele lancia, lo sviluppatore legge.

**L'attivazione.** In `scraper_bandi/.env` si scrive la riga `VERIFICA_STATO_MODALITA=attivo`, poi **un solo** riavvio
del sender, verificato dall'esterno. Le condizioni sono tutte e quattro insieme:

1. difformi 0 (dopo le correzioni di §9.3);
2. il messaggio a BandoFit del giro 3 è partito (RIPRESA §1, passo 1, prima del deploy): nessuna attesa dopo
   l'invio (prima del giro 3 servivano 7 giorni);
3. un backup recente, o il PITR, nel pannello Supabase del progetto bandi, perché le fusioni sono quasi irreversibili
   (RIPRESA §4.1 f);
4. Michele ha letto M6 e accetta l'effetto sul pubblico.

*Chi:* Michele.

**Cosa succede dopo l'attivazione** (se gli interruttori non sono stati separati):

- **dal giro delle 06 o delle 18 successivo**: la verifica scrive letture, eventi e bollini;
- **allo stesso giro**: i 96 illeggibili ricevono «esaminato» e molti prendono il bollino «senza conferma»;
- **ogni mattina alle 06**: fino a 10 fusioni. Le 52 previste richiedono circa 6 mattine;
- **la prima mattina**: l'import di IndicePA riparte (quello fatto in ombra non conta) e scrive circa 22.355 domini
  nuovi (prova dell'01/10);
- **a ogni giro**: i bandi nuovi aperti senza scadenza sostano fino a 4 giri (24 ore) prima della pubblicazione, e un
  bando nuovo gemello di un pubblicato viene fuso invece che pubblicato, senza tetto.

**Se qualcosa va storto dopo l'attivazione.** Si riscrive `VERIFICA_STATO_MODALITA=ombra` in `scraper_bandi/.env`
(oppure si toglie la riga, perché un valore assente o sconosciuto vale «ombra») e si riavvia il sender una volta. Il
riavvio serve perché il sender legge le impostazioni una sola volta (`get_settings` resta in memoria per tutta la vita
del processo). Tornare in ombra però **non cancella** quello che l'attivo ha già scritto:
- **bollini**: la vista calcola `stato_da_verificare` dalle colonne di `bando_controllo` e non sa in che modalità gira la
  verifica. Un bando che ha già `esaminato_attivo_at` non è più protetto dalle regole «mai esaminato» (I6-bis, A4). In
  ombra nessuno rinnova le sue letture, quindi i bollini restano e col tempo possono peggiorare, per esempio quando
  scadono i 30 giorni della conferma (A2, I5);
- **domini di IndicePA**: l'import inserisce solo righe nuove e il codice non ha un modo per toglierle;
- **fusioni**: non esiste un comando per separare due bandi. Si fa a mano nel SQL Editor con
  `select bando_separa(<id del doppione>);` (§4.9). La funzione rimette in uso lo slug, cancella la riga di
  `bando_fusione`, toglie il master (così il trigger ripubblica la riga, se è ancora `completed`) e registra un evento
  pubblico `separazione`. Gli eventi `fusione` e i link copiati sul master restano. Un bando nuovo fuso *prima* della
  pubblicazione è già `rejected`: per lui `bando_separa` non basta a pubblicarlo;
- **eventi applicati**: restano, perché il registro non si corregge. Per correggerli serve un evento nuovo.

Per spegnere soltanto le fusioni del giro delle 06 basta `GEMELLI_FUSIONI_PER_GIRO=0`, sempre con un riavvio. Non spegne
le fusioni prima della pubblicazione.

Fonti: RIPRESA §1, passi 7-10; `bandi_pipeline.py:516-545` (`domini_dovuto`: in attivo contano solo gli import «ok»);
`gemelli.py`; `fonte_ufficiale.py:3050-3058` (import: solo host assenti); `bando_seo_runner.py:419-430`;
`scraper_bandi/app/settings.py:213-219` (valore sconosciuto → ombra), `:253-265` (`GEMELLI_FUSIONI_PER_GIRO` 10, minimo
0), `:400-406` (`get_settings` in cache); `backend/sql/bando_v11_13_stato_da_verificare.sql:740-761`;
`backend/sql/bando_v11_04_transizioni.sql:957-997` (`bando_separa`); `backend/sql/bando_v11_02_tabelle_di_servizio.sql:549`
(`separazione` tipo pubblico); `scraper_bandi/app/__main__.py:1370-1395` (nessun comando di separazione).

### 9.5 Il giorno dopo l'attivazione

- **La Verifica 7 della migrazione 05**, una volta sola, dopo il primo import di IndicePA riuscito in attivo. La
  condizione è una riga «domini» con esito «ok». Si fa nel SQL Editor, come anon, con la query in fondo alla 13
  («Verifica a mano», punto 2). I criteri: meno di 3 secondi e **nessun Seq Scan su `dominio_ufficiale`**. Serve perché
  con 22.000 domini la vista potrebbe rallentare, e il controllo automatico («vista lenta») dipende da `sorveglia`, che
  oggi non gira. *Chi:* Michele.
- **Rivalutare le fonti già giudicate** (M20) con `risolvi-fonte --forza --anche-oggi`, a lotti con `--limit`. Si lancia
  sul server, perché scrive davvero, e mai durante un giro. *Chi:* Michele, su indicazione dello sviluppatore.
- **Le prime fusioni**: controllare ogni mattina che siano quelle elencate dal `--dry-run`. *Chi:* sviluppatore.

Fonti: RIPRESA §1 passo 10 e §4.1 d; `backend/sql/bando_v11_13_stato_da_verificare.sql` (righe 2123-2165).

### 9.6 La migrazione del sito per la 07 (senza data)

La 07 chiude la tabella `bando` alla chiave pubblica e toglie le colonne vecchie. Si fa in quest'ordine:

1. **Codice che popola `bando_link`.** Le candidature estratte devono diventare righe pubblicabili (oggi 1 su 104), e
   gli allegati devono finire in `bando_link` (oggi 151 bandi su 160 li perderebbero). *Chi:* sviluppatore.
2. **Il sito legge da `bando_link`** e smette di chiedere `link_candidatura`, `link_candidatura_source` e `allegati`.
   *Chi:* sviluppatore, con una deroga sul frontend.
3. **BandoFit completa il passo c2.** *Chi:* il committente di BandoFit, su richiesta di Michele.
4. **Michele applica la 07** nel SQL Editor, dopo un backup.
5. **Subito dopo**, aggiornare l'elenco delle colonne della misura «vista lenta» (B30). *Chi:* sviluppatore.

Finché la 07 non c'è, la chiave pubblica legge l'intera tabella `bando` (M28).

Fonti: `backend/sql/bando_v11_07_fase_d.sql` (intestazione); `src/lib/supabase-bandi.ts`; `docs/contratto-db-bandi.md`
§1.7 e fasi (a)-(d), righe 669-676; RIPRESA §1 «Migrazioni applicate».

### 9.7 Il pannello su BandoFit (futuro)

È rimandato per decisione di Michele dell'01/10. Quando si farà:

- generare la chiave sul server del pannello (passo 2 di RIPRESA);
- installare il timer `edunews-bandi-sorveglianza` (passo 4);
- inviare la prima parte del messaggio a BandoFit (§1-§5 di `richiesta-bandofit-giro-2.md`).

La migrazione 12 è già applicata e pronta. Fino ad allora vale A1.

*Chi:* Michele.

Fonti: RIPRESA, «Giro 2 dei bandi: sorveglianza e stato da verificare»; `backend/sql/bando_v11_12_monitoraggio.sql`.

### 9.8 Le decisioni aperte (RIPRESA §4.1)

Non sono lavoro arretrato: sono scelte. Le prende **Michele**; lo sviluppatore prepara i dati.

| Punto | La questione | Stato e numeri di oggi | Cosa serve per decidere |
|---|---|---|---|
| **a** | Tipi di evento ancora in ombra: apertura, chiusura, rettifica, riapertura, sospensione, revoca. E l'arretrato già raccolto | 5 tipi attivi dal 30/09; 20 eventi ammessi in arretrato, non pubblicati | `report-ombra` del 09/10 e lettura a mano |
| **b** | La soglia per uscire dall'ombra misura la cosa sbagliata (proposte che passano i gate, non eventi giusti) | Formula non cambiata, di proposito | Decidere una misura nuova: precisione degli ammessi, valutata a mano |
| **c** | Il terzo segnale del resolver | 1.050 pubblicati «in verifica», 364 già con 70 punti o più | Decidere se scadenza + importo valgono come terzo segnale; vedi anche A6 |
| **e** | Lotto L8: «processed» chiusi, mai pubblicati | 569 alle 11:28, 570 dopo il giro delle 12: la coda cresce. Nessuno archiviato | Archiviarli tutti (dopo un backup) oppure far passare il resolver |
| **f** | Backup prima delle operazioni irreversibili | Nessuna procedura scritta | Controllo di backup/PITR prima di attivazione, `applica-eventi --attivo`, `archivia-processed`, fusioni |
| **g** | Doppioni visibili | Fusione automatica decisa il 30/09, parte all'attivazione; restano 41 coppie ObiettivoEuropa da fare a mano (numero **non ricontato**) | `fondi-doppioni --dry-run`, mai senza (A4) |
| **h** | IndexNow rotto | Chiave del sito 404 (verificato) | §9.2 punto 3 |
| **i** | Sospensione e revoca: uscite, correzioni, doppia fonte dello stato, stallo 23514 | 0 sospesi e 0 revocati: niente preme | Chiudere i buchi prima di applicare questi eventi (M13) |

Il punto **d** (IndicePA) è chiuso dal giro 2: l'import è automatico (giro delle 06, una volta al mese) e scrive
dall'attivazione.

Si aggiungono le decisioni emerse da questa indagine:

- come sorvegliare finché il pannello non c'è (A1);
- se separare gli interruttori dell'attivazione (M5);
- il perimetro editoriale «solo UE 2021-2027 o anche fondazioni» (M14);
- il valore predefinito «aperto» nel prompt (M10);
- il significato dello status «2» di ObiettivoEuropa (M11).

Fonti: `docs/bandi-monitor/RIPRESA.md` §4.1 (righe 930-1090) e §4.3; capitolo 8 di questa guida.

---

## Glossario

- **Aggregatore**: sito che ripubblica bandi altrui, come ObiettivoEuropa. Non vale mai come prova o come fonte
  ufficiale.
- **anon key (chiave anonima, chiave pubblica)**: la chiave con cui il sito e BandoFit leggono il database. Va trattata
  come pubblica.
- **applica-eventi**: comando manuale che applica a posteriori, a blocchi di al massimo 50, gli eventi raccolti in ombra
  già registrati e verificati.
- **archivia-processed**: comando manuale che porta ad `archiviato` i `processed` chiusi che nessuno lavorerà più. Mai
  lanciato.
- **Arretrato d'ombra**: gli eventi raccolti in ombra e mai pubblicati, per scelta (78 del worker non applicati, di cui
  20 verificati).
- **Attivo**: modalità in cui un passo scrive davvero e i suoi effetti diventano pubblici.
- **Backfill / lotto (L6, L7, L8)**: lavoro straordinario lanciato a mano su una parte dell'archivio, che scrive righe
  `backfill:*` in `pipeline_run`. L6 = il monitor lanciato a lotti per seminare le impronte (`monitor --ombra --lotto
  L6`); L7 = `rigenera` (riscrive il testo dopo date nuove); L8 = `archivia-processed`.
- **bando_pubblico**: la vista che il sito e BandoFit devono leggere.
- **c1 / c2**: i due passi della fase (c) di BandoFit. Con c1 (in produzione dal 30/09) BandoFit legge la vista e
  `bando_link`; c2 toglie i ripieghi sulle colonne vecchie. Solo dopo c2 si propone la 07.
- **Chiave di servizio (service-role key)**: la chiave privata con cui news1 scrive. Può fare tutto.
- **Contratto**: il documento con le promesse fatte ai lettori del database (`docs/contratto-db-bandi.md`).
- **Cron / job orario / pg_cron**: lavoro pianificato dentro il database. Qui gira al minuto 5 di ogni ora: chiude i
  bandi scaduti e aprirebbe gli «in apertura» con data di apertura verificata e raggiunta.
- **Cursore**: numero progressivo dato a un evento quando diventa pubblico. BandoFit lo segue per vedere le novità.
- **Deploy**: la messa in produzione di una nuova versione del codice.
- **Diff**: il confronto fra due versioni della stessa pagina.
- **Dominio verificante**: dominio attivo di ente, di portale pubblico o di pattern con confidenza almeno 0,8, mai in
  lista nera. Solo una prova da lì rende un evento «verificato».
- **Esito del giro**: `ok`, `errore`, `saltato`, `interrotto_per_tetto` (colonna `esito` di `pipeline_run`). Nel journal
  il riepilogo dice invece `COMPLETED` o `PARTIAL`.
- **Estrattore (lettore per ente)**: programma che legge in modo strutturato le pagine di un certo sito. È più
  affidabile del modello.
- **Evento**: riga di `bando_evento` che registra un fatto su un bando, con la sua prova. Non si cancella e non si
  corregge: si aggiunge un evento nuovo.
- **Fase (a)–(d)**: le quattro tappe del passaggio di BandoFit al nuovo contratto. La (c) è divisa in c1 e c2; la (d) è
  la migrazione 07.
- **Finestra sicura**: 12:30-16:30 o 19:00-22:30, gli orari lontani dai giri in cui lanciare deploy e comandi senza
  lucchetto (`rigenera`).
- **Fonte ufficiale**: la pagina dell'ente che ha emesso il bando.
- **Fusione**: unione di un doppione nel suo bando master, con redirect 301. Si annulla a mano con `bando_separa`.
- **Gate**: controllo automatico che una proposta deve superare per diventare evento (G1, G2…).
- **G7 / G7e**: la regola della seconda prova. Nel monitor serve una seconda opinione o una pagina collegata. Nella
  verifica (G7e), per una lettura strutturata serve la stessa lettura ripetuta a distanza di almeno 60 ore.
- **Gemelli**: righe che descrivono lo stesso bando. Il passo `gemelli` le trova e, in attivo, le fonde.
- **Giro**: un'esecuzione della pipeline (alle 00, 06, 12, 18, più quello di avvio, o «boot», a ogni riavvio del
  sender).
- **GUC**: impostazione temporanea di una sessione del database. Qui serve a dichiarare l'intenzione di cambiare uno
  slug o lo stato.
- **Impronta**: riassunto numerico di una pagina o di un bando (l'«hash»), che permette di capire se è cambiato o se c'è
  già.
- **IndexNow**: servizio che avvisa i motori di ricerca che una pagina è cambiata.
- **Junction**: tabella che collega un bando a più voci di un catalogo (per esempio bando ↔ regioni).
- **Lista bianca / lista nera**: elenco di cose ammesse e di cose vietate. La lista nera vince sempre.
- **Lock (lucchetto)**: riga di `pipeline_lock` che impedisce a due processi di fare lo stesso lavoro insieme. Ha un
  *nome* (che cosa si blocca, per esempio `bandi_pipeline`) e un *proprietario* (chi lo tiene, per esempio
  `bandi_pipeline@<pid>`).
- **Master**: il bando che resta dopo una fusione.
- **Migrazione**: script SQL che cambia la struttura del database. Lo applica Michele a mano.
- **Modello**: l'intelligenza artificiale (Claude) usata per leggere le pagine e proporre eventi. Propone, non decide.
- **Monitor**: passo che ricontrolla le pagine ufficiali dei pubblicati alle 06 e alle 18.
- **Ombra**: modalità «osserva e annota». Il passo lavora e registra, ma non cambia niente di pubblico. È il valore
  predefinito quando la variabile manca.
- **Pattern**: regola di dominio generica, come `regione.*.it`.
- **pipeline_run**: il diario dei giri, con i contatori di ogni passo (§3.3.4).
- **PostgREST**: l'interfaccia web con cui si legge il database. Restituisce al massimo 1.000 righe per richiesta.
- **Pubblicato**: bando visibile sul sito e a BandoFit (`pubblicato = true`).
- **Redirect 301**: risposta che dice «questa pagina si è spostata per sempre lì». Il 410 dice invece «questa pagina è
  stata tolta».
- **Resolver**: passo che cerca la fonte ufficiale di un bando. Da non confondere con `bando_resolver.py`, che è il
  ripiego del preprocess.
- **Ricontrolli**: il resolver rilanciato sui bandi «in_verifica» o «non_trovata» la cui data di ricontrollo è arrivata
  (60 per giro, alle 06 e alle 18).
- **Ritiro**: uscita definitiva di un pubblicato dalla vista (`bando_ritira`), solo su richiesta scritta del
  committente. Il vecchio indirizzo risponde 410.
- **RLS (Row Level Security)**: regole del database che decidono quali righe vede chi legge.
- **RPC**: funzione del database chiamata dall'esterno, per esempio `bando_registra_evento`.
- **Scarico**: il client HTTP unico del giro, con cache, tentativi, limiti e contatori. Lo usano tutti i passi tranne lo
  scrape.
- **Segnale dell'aggregatore**: etichetta di ObiettivoEuropa scritta in `bando_controllo` («in_uscita»,
  «scadenza_passata», «assente_dal_listing»). Alimenta il bollino.
- **segnale_fonte**: evento interno dello scrape («sulla fonte è cambiato qualcosa»). Alza solo la priorità del monitor.
- **Slug**: la parte finale e leggibile dell'indirizzo della pagina. Una volta pubblicato è congelato.
- **Sosta all'ingresso**: in attivo, un bando nuovo «aperto» senza scadenza aspetta fino a 4 giri prima della
  pubblicazione.
- **Stato effettivo**: lo stato salvato corretto dall'orologio, calcolato a ogni lettura.
- **stato_bando**: lo stato salvato del bando (aperto, chiuso, in apertura, sospeso, revocato).
- **stato_da_verificare**: il bollino di prudenza, con uno dei cinque motivi.
- **stato_processing**: la tappa di lavorazione (scraped → processed → enriched → completed, oppure rejected; più
  `archiviato` per i `processed` chiusi).
- **Transizione**: passaggio da uno stato all'altro, ammesso solo se è nella lista bianca.
- **Trigger**: regola automatica del database che scatta quando una riga cambia.
- **Verificato**: detto di un evento la cui prova sta su un dominio verificante e ha la citazione.
- **verifica_stato**: passo del giro 2 che rilegge la pagina ufficiale dei bandi senza prove di stato (i candidati sono
  gli «in apertura» e gli aperti senza scadenza). Ha una fase «ingresso» (prima della SEO, sui bandi nuovi) e una fase
  «controlli» (alle 06 e alle 18, sui pubblicati).
- **Verità nota**: elenco di 53 bandi controllati a mano, usato per collaudare la verifica dello stato prima di
  attivarla.
- **Vista**: tabella «virtuale» calcolata dalle tabelle vere a ogni lettura.
- **Worker**: nella lista bianca, l'attore che comprende il monitor e la verifica dello stato. Anche le correzioni
  manuali sono registrate con questa origine.
