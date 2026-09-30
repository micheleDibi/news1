# Contratto interno: ripresa dei bandi, ottobre 2026

Proprietario: il lead della sessione news1. Questo file è in sola lettura per gli operatori: le modifiche si chiedono
con un messaggio che inizia con `CONTRATTO:`. Il contratto verso BandoFit resta `docs/contratto-db-bandi.md`.

Le fonti restano valide così come sono: `docs/bandi-monitor/RIPRESA.md`, in particolare §4, §5 (trappole) e §7
(regole), e CLAUDE.md. Questo file fissa soltanto le interfacce nuove di questo giro.

---

## 1. Regole sul database (valgono per tutti)

- **Dal Mac nessuno scrive sul DB bandi.**
  - Si legge con GET su PostgREST.
  - Oppure con i comandi in sola lettura: `salute`, `report-ombra`, `link-verifica --dry-run`.
  - Ogni scrittura la fa Michele nel SQL Editor, oppure con un comando lanciato da lui sul server.
- **I valori dei `.env` non si stampano mai**: né chiavi, né cookie, né token. Si legge `scraper_bandi/.env` solo
  dentro uno script che non ne stampa il contenuto. Se l'harness nega l'accesso, non si aggira: si scrive al lead.
- **`monitor`, `risolvi-fonte` e i lotti non si lanciano mai dal Mac**, nemmeno in `--dry-run`: prendono lock,
  scrivono `pipeline_run` e spendono.
- **Le letture passano da `_scorri()`/`_per_id()`**, o comunque paginano con `order=id` come tiebreak, perché
  PostgREST tronca a 1000 righe senza dirlo.
- **Un `--limit N` non è un campione.** Per stimare si prende una riga per host, mai le prime N.
- **Per BandoFit si legge con la anon key** (`PUBLIC_SUPABASE_BANDI_ANON_KEY` del `.env` di root): è l'unico modo di
  vedere quello che vede lui.

## 2. File SQL per Michele

Nomi: `docs/bandi-monitor/correzioni-AAAA-MM-GG[-tema].sql`.

- **Intestazione**:
  - data;
  - autore del giro;
  - cosa corregge;
  - la frase «NON rieseguire dopo l'esecuzione: segnare qui la data».
- **Un blocco per bando**, con la verifica (una `select` di controllo) subito dopo la correzione.
- **Righe di 45 caratteri al massimo.** Le righe lunghe si rompono nel copia-incolla: è successo il 30/09.
- **Le correzioni passano dalle RPC del DB** (`bando_registra_evento`, `bando_applica_evento`, `bando_fondi`),
  seguendo il modello di `correzioni-2026-09-29.sql`. Niente UPDATE diretti su colonne che una RPC governa.
- **Prima della consegna, ogni file gira su un Postgres 17 effimero.**
  - Postgres: `/opt/homebrew/opt/postgresql@17/bin`, `initdb` in una cartella temporanea, TCP su 127.0.0.1 con una
    porta alta, `unix_socket_directories=''`, avvio e stop nello stesso comando.
  - Tabelle ridotte alle colonne che il file tocca.
  - Funzioni copiate da `backend/sql/bando_v11_04_transizioni.sql` e dalla `_11_`.
  - Esito atteso: il file passa due volte di fila. Una seconda esecuzione non fa danni, oppure si ferma con un
    messaggio chiaro.
- **Invarianti del contratto**: id mai riusati, nessuna riga cancellata, slug dei pubblicati congelati, un pubblicato
  non esce mai da `completed`.

## 3. `MONITOR_TIPI_ATTIVI` (proprietario `backend`)

- **Variabile d'ambiente** di `scraper_bandi`, letta in `settings.py`.
  - È una lista separata da virgole, di default vuota.
  - Valori ammessi: i tipi di `bando_evento` che il monitor produce.
  - Un valore sconosciuto viene ignorato e fa scattare un `[ALLARME]` nel journal e in `salute`; il sender non si
    ferma.
- **`MONITOR_MODALITA` resta `ombra`.** La lista è l'unico interruttore per tipo; `MONITOR_MODALITA=attivo` mantiene
  il significato di oggi.
- **Comportamento a ogni giro del monitor**, per ogni evento **nato in quel giro** di un tipo attivo e ammesso dai
  gate:
  - l'evento diventa `applicato` e `leggibile`, due scritture (RIPRESA §5.8), nello stesso giro;
  - se la RPC non scrive (5xx o 23514), l'evento resta non applicato e scatta l'allarme «eventi ammessi non applicati»
    del rilascio 2. Mai un INSERT «applicato» dopo una RPC fallita;
  - IndexNow si chiama solo per le pagine cambiate davvero: un evento applicato e visibile, oppure date applicate con la
    prosa riscritta (anche se l'evento resta invisibile, perché la colonna e il testo sono cambiati).
- **Gli eventi degli altri tipi restano in ombra**, come oggi.
- **Gli eventi già registrati prima dell'attivazione non si toccano**: sono giudicati con i gate vecchi, e l'arretrato
  si decide a parte (T-D5).
- **Contatori nella riga del giro**: `tipi_attivi` (la lista USATA dal giro: vuota con `--ombra` o `--dry-run`), `applicati_per_tipo`, `eventi_non_applicati`.
  Quest'ultimo è il contatore già esistente dal rilascio 2, che l'allarme legge: non se ne crea un secondo con un altro
  nome.
- **Percorso approvato il 30/09 (PIANO di #9)**, con `MONITOR_MODALITA=ombra`:
  1. `bando_registra_evento` registra la riga d'ombra;
  2. se `nuovo=true`, `applica_evento_esito` e poi `rendi_evento_leggibile`;
  3. se `nuovo=false`, l'evento c'era già e non si tocca.

  Se la RPC di registrazione fallisce, si ripiega sull'INSERT d'ombra, mai «applicato». `MONITOR_MODALITA=attivo`
  resta come nel rilascio 2.
- **Correzioni del 30/09 dopo la revisione avversaria:**
  - un evento con date applicate (per esempio una proroga) **riscrive la prosa** anche con `MONITOR_MODALITA=ombra`:
    l'adattatore della rigenerazione esiste ogni volta che ci sono tipi attivi. Se la riscrittura non riesce scatta un
    `[ALLARME]`, e lo slug non va a IndexNow;
  - si applica solo un evento che il DB registra come **verificato** (`bando_dominio_verificante`). Un evento non
    verificato resta in ombra e si conta, perché applicarlo cambierebbe la colonna senza poterlo rendere leggibile
    (23514);
  - gli esiti con eventi applicati ma invisibili non vanno a IndexNow;
  - il testo degli allarmi indica sempre `applica-eventi --tipo <tipo> --dal <oggi> --attivo`, mai il comando senza
    filtri, che applicherebbe l'arretrato.
  `salute` stampa i tipi attivi.
- **Primo valore in produzione**: `faq,nuovo_allegato,graduatoria,esito,proroga`. Il 30/09 Michele ha dato l'ok
  per `proroga` da subito. T-D5 resta come controllo prima del deploy: se trova proroghe ammesse sbagliate, il lead
  lo dice a Michele prima del riavvio.

## 4. Pagine cieche e riallineamento (proprietario `backend`)

- **`impronte.pulisci` non deve togliere il contenuto.** Oggi scarta i nodi del `form` e confronta le classi per
  sottostringa. Test su pagine reali del Piemonte e della Valle d'Aosta (fixture HTML nel repo, senza dati personali):
  il testo normalizzato deve avere più di 3 righe e contenere il titolo del bando.
- **Versione della pulizia.**
  - `impronte.VERSIONE_PULIZIA` è un intero da incrementare a ogni cambio che sposta le impronte.
  - Si salva in `bando_controllo.impronte_sezioni["__versione__"]`. Le righe di oggi non ce l'hanno e valgono come
    versione 1.
- **Riallineamento, dentro il controllo normale.** Se la versione salvata è diversa da quella del codice e la pagina è
  scaricata bene:
  - si riscrivono `testo_norm`, le impronte, `__link__` e `__versione__`;
  - **nessun diff e nessuna classificazione**, quindi nessun evento e nessuna spesa;
  - il prossimo controllo si calcola come per una pagina invariata;
  - un contatore `riallineate` va nella riga del giro.
  Il prezzo accettato: un cambiamento vero avvenuto proprio fra l'ultimo controllo e il riallineamento non viene
  visto. Succede una volta per pagina.
- **Il cambio di pulizia e il riallineamento vanno in produzione insieme, sempre.** Senza il riallineamento il primo
  giro classificherebbe tutte le pagine cieche.

## 5. Host morti (proprietario `backend`, scadenza 07/10)

- **Tetto di tempo per singolo bando** nel resolver e nei ricontrolli, configurabile con una costante. Superato il
  tetto, il bando passa al giro dopo senza consumare un tentativo.
- **DNS che non risolve.** Se un host fallisce la risoluzione DNS, i suoi URL si saltano per il resto del giro, con
  un contatore `host_irraggiungibili` e l'elenco degli host nel journal.
  - Non consumano tentativi e non cambiano lo stato della fonte.
  - Un errore di rete isolato (timeout, 5xx) non basta: serve un errore DNS.
- **Caso di prova**: i 101 URL di `regione.basilicata.it` del 28/09 (RIPRESA §4.4).
- **Precisazioni del 30/09, dal PIANO approvato:**
  - il resolver e i ricontrolli stanno in `fonte_ufficiale.py`; il tetto di tempo è `TETTO_TEMPO_BANDO_S = 120`;
  - un bando rinviato, per DNS o per il tetto di tempo, non viene scritto nel modo `nuovi`. Nel modo `ricontrolli`
    riceve soltanto `prossimo_controllo_at` = domani, così non occupa la coda di 60 posti per giro;
  - nel monitor un host irraggiungibile dà `saltato`: nessun `controlli_falliti`, e l'unica colonna scritta è
    `prossimo_controllo_at` = domani, come nel resolver. Una riga saltata non conta nel `tetto_fetch_giro`. Così un
    host morto non resta in testa alla coda a ogni giro (revisione #23, decisione del 30/09);
  - la riga del giro porta `host_irraggiungibili` (il numero) e `host_irraggiungibili_elenco` (al massimo 20 host).
  - (Ciclo 3.) Vale come DNS morto anche `EAI_AGAIN`, dopo i ritentativi, perché un DNS di ente rotto (SERVFAIL) dà
    proprio quello. Quando un giro trova almeno 5 host irraggiungibili distinti scatta un `[ALLARME]` «resolver
    locale?», perché il guasto potrebbe essere il resolver del server.
    Un host morto per sempre, che così non consuma mai tentativi, è un limite noto, da trattare in un giro
    successivo.

## 6. ObiettivoEuropa prima della pubblicazione (proprietario `backend-b`)

- **Bandi coinvolti**: quelli con `fonte_id` fra le fonti OE (`fonte_ufficiale.FONTI_OE` = 449, 450, 451), non
  ancora pubblicati, **all'ingresso dello step SEO**, cioè prima della chiamata a Opus.
- **Criteri**: il bando è un «doppione probabile» se esiste un bando **pubblicato e non fuso** che rispetta almeno una
  di queste condizioni:
  1. la stessa `fonte_ufficiale_url`, normalizzata con `impronte.normalizza_url`;
  2. lo stesso ente normalizzato, lo stesso `importo_totale_eur` e la stessa `data_scadenza`, tutti e tre non NULL.
- **Correzioni del 30/09, dal `CONTRATTO:` approvato**, dopo una simulazione in sola lettura sui 2 180 pubblicati:
  - **la controparte è sempre un pubblicato di una fonte NON OE**, per entrambi i criteri. OE contro OE produceva circa
    un falso su tre: lotti diversi sulla stessa pagina elenco;
  - **i campi del candidato**: all'ingresso della SEO un bando OE ha `ente_erogatore` e `importo_totale_eur` NULL.
    Solo per il candidato, se la colonna è NULL, l'ente si prende dal prefisso del titolo OE («Piemonte - …») e
    l'importo da `raw_data.budget`;
  - **l'ente normalizzato**, su entrambi i lati: minuscole, niente accenti, taglio a « - » o «(», senza «regione»,
    «provincia (autonoma) di», «comune di», «camera di commercio … di», «cciaa» e «gal».
  - Esito della simulazione: 41 coppie, tutte doppioni veri tranne 2-3 dubbi; i quattro casi F3-F6 del 29/09 sono
    tutti presi.
- **Esito**:
  - `stato_processing='rejected'`;
  - `rejection_reason='doppione probabile di <id>: <url|ente-importo-scadenza>'`;
  - nessuna chiamata SEO;
  - contatore `doppioni_oe` nella riga del giro, più una riga nel journal con i due id.
- **Mai una fusione automatica.** Per le fusioni resta Michele, con `bando_fondi`.
- **Annullamento, con un solo UPDATE documentato** nella docstring e in RIPRESA §6:
  `stato_processing='enriched'` e `rejection_reason='doppione escluso a mano'`. Dopo l'annullamento il controllo
  non rifiuta più quel bando.
- **I bandi delle altre fonti non si toccano.**

## 7. Rigenerazione della SEO (proprietario `backend-b`)

- **Prompt di `seo_skill.py`.** Il testo non deve affermare:
  - forme di partecipazione («in forma singola o associata», «reti di imprese», «aggregazioni», «partenariati»);
  - beneficiari o requisiti che non si leggono nella fonte passata al modello o nei cataloghi collegati al bando.

  Se la fonte non dice niente, il testo non dice niente. I test sono sui casi reali: 18145, 18278, 171905 e gli 8 del
  29/09 (RIPRESA §4.4).
- **Comando nuovo** `python -m app seo-rigenera --ids <id,id,…> [--attivo]`.
  - Senza `--attivo` è una prova a secco: stampa il testo nuovo accanto al vecchio e il costo stimato, e non scrive
    niente.
  - Con `--attivo` riscrive **solo** `contenuto`, e `descrizione_breve` se contiene le stesse affermazioni.
  - Restano invariati `slug`, `titolo`, date, importi, stato, `stato_processing` e junction.
  - Prende il lock `bandi_pipeline` con proprietario `seo-rigenera:cli` e TTL di 1 h (esclude il giro del sender; il
    rilascio all'avvio non lo tocca mai: si lancia solo nella finestra sicura), scrive una riga in `pipeline_run` e
    rifiuta gli id non pubblicati.
- **Le junction sbagliate** (per esempio i beneficiari del 18278) si correggono con SQL da `db`, non con il comando.
- **Titolo oltre 80 caratteri su un bando non pubblicato** (decisione del 30/09, revisione #25). Il titolo e lo slug si
  congelano alla pubblicazione, quindi il titolo non si taglia mai in modo meccanico:
  1. se `titolo_breve` ha 1-80 caratteri, si usa quello;
  2. altrimenti una sola richiamata al modello nello stesso giro;
  3. se è ancora lungo, il payload si scarta con il motivo scritto in `payload_failed_motivi`.

  La `descrizione_breve` invece si può accorciare all'ultima frase intera.
- **Aggiunta del 30/09: si scrive esattamente il testo provato.**
  - `--dry-run` salva le proposte in un file JSON: id, testo nuovo, hash del contenuto attuale e affermazioni
    segnalate.
  - `--attivo --proposte FILE` scrive quelle proposte **senza richiamare il modello**. Scrive solo se il bando è ancora
    pubblicato, se il contenuto non è cambiato rispetto all'hash salvato e se il testo nuovo non ha affermazioni
    segnalate.
  - Si paga una volta sola, e il testo scritto è quello che Michele ha letto. `--solo-controllo` non usa il modello.

## 8. Lock del sender (proprietario `backend-b`)

- **All'avvio**, il sender rilascia i lock il cui proprietario è un suo processo precedente e non più vivo. Oggi i
  nomi sono `bandi_pipeline@<pid>`, `resolver@<pid>` e `monitor:<giro>`.
- **Lo fa con `lock_rilascia`**, mai con un DELETE.
- **Il journal registra** quali lock ha rilasciato.
- **Un lock di un processo vivo non si tocca**, compreso quello di un comando `:cli` in corso.

## 9. Ordine di rilascio

1. Un solo deploy per tutto il giro, nella finestra sicura: 12:30-16:30 o 19:00-22:30, mai nell'ora e mezza prima
   delle 00, 06, 12 e 18.
2. Un solo `systemctl restart`, poi l'attesa di «Pipeline iniziale completata».
3. `MONITOR_TIPI_ATTIVI=faq,nuovo_allegato,graduatoria,esito,proroga` va nel `.env` del server **nello stesso**
   riavvio.
4. Il deploy va fatto **entro il 07/10**, per gli host morti prima dell'ondata dei ricontrolli dell'08/10.
