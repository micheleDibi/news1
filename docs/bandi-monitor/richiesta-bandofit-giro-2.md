# Richiesta al consumatore: pannello di monitoraggio del DB bandi

Messaggio unico, da inoltrare alla sessione del consumatore **dopo l'ok del committente**. Tutto il testo è neutro e si
può incollare così com'è. La specifica è la §14 «Interfaccia di monitoraggio» del contratto del DB bandi, da copiare
nella documentazione del consumatore **solo per quella sezione**: il resto del contratto non va nel repository pubblico.

Il messaggio ha due parti:
- la prima (§1-§5) è il pannello di monitoraggio;
- la seconda (§6) è la certezza dello stato, gli eventi nuovi e le fusioni automatiche, cioè le sezioni aggiornate del
  contratto: §2, §3, §4.1, §5 (domini degli enti), §6.1, §6.2, §10.2 e R6.

Il consumatore pianifica il lavoro **solo quando il committente glielo chiede direttamente**.

Prerequisiti lato DB, che non bloccano lo sviluppo:
- per la prima parte: migrazione 12 applicata, chiave generata e impronta inserita. Prima della migrazione la
  funzione risponde `PGRST202` e il pannello mostra «interfaccia non ancora disponibile»;
- per la seconda parte: migrazione 13 applicata. Il committente lo conferma per iscritto, e solo da quel momento il
  consumatore può nominare le colonne nuove (§6.1).

---

## Messaggio

**Oggetto: pannello «Monitoraggio» nell'area admin, letto dal DB bandi con una funzione a chiave**

Il DB bandi espone ora un riepilogo della salute della raccolta dei bandi. Il pannello di amministrazione è **l'unico
punto di sorveglianza**: non ci sono avvisi via email o telefono, per scelta del committente. Chiediamo una pagina
admin in sola lettura che lo mostri.

La specifica completa è la §14 del contratto del DB bandi, «Interfaccia di monitoraggio», allegata. Qui sotto c'è
quello che serve per il lavoro.

### 1. Configurazione (due file protetti: le modifiche le approva il committente)

- `core/config.py`: `SECONDARY_MONITORING_KEY: SecretStr | None`, **facoltativa**. Resta fuori da
  `_segreti_obbligatori`: senza la chiave l'applicazione parte e il pannello dice «monitoraggio non configurato».
- `docker-compose.yml`: la riga corrispondente nel blocco `environment` del backend.
- Il valore è una stringa esadecimale di 64 caratteri. Vive **solo** nel file protetto dell'ambiente del server:
  mai nel repository, mai in una variabile `VITE_*`, mai nei documenti.
- **Come nasce la chiave.** La genera il committente sul server dove gira il backend del pannello, senza che venga
  mai stampata né finisca nella history:

  ```bash
  umask 077
  CHIAVE=$(openssl rand -hex 32)
  printf 'SECONDARY_MONITORING_KEY=%s\n' "$CHIAVE" >> <file protetto dell'ambiente>
  printf %s "$CHIAVE" | sha256sum | cut -c1-64   # stampa SOLO l'impronta
  unset CHIAVE
  ```

  Nel DB bandi va solo l'impronta, che non è un segreto. La chiave non passa per nessun canale.
- **Rotazione.** Se `SECONDARY_MONITORING_KEY` c'è già nel file protetto, quella riga **si sostituisce**: non se ne
  aggiunge una seconda, perché due righe con lo stesso nome lasciano incerto quale valga. La chiave vecchia resta
  valida nel DB finché il committente non la chiude (§14.6 del contratto).

### 2. Backend: `GET /api/v1/admin/monitoraggio`

- Router nuovo `admin_monitoraggio.py`, protetto da `AdminUser`, senza nessun endpoint di scrittura.
- **Chiamata:** `secondary.rpc('monitoraggio_catalogo', {'p_chiave': key.get_secret_value()})` sul client
  secondario anon già esistente. La libreria la esegue in **POST**, che è il suo default: non va passato né
  `get=True` né `head=True`. È l'unico metodo accettato: una GET riceve 42501 anche con la chiave giusta. L'header
  `Authorization` del client non si cambia.
- **Cache e tempi:** cache in memoria di **60 s**, così si fa al massimo una chiamata al minuto; timeout di **5 s**.
  Se il backend gira su più processi, la cache va condivisa oppure la frequenza complessiva va tenuta comunque a
  una chiamata al minuto.
- **La chiave non compare mai** nei log, nella risposta, nei messaggi d'errore o nelle eccezioni rilanciate. Un
  errore della libreria che la contenesse va sostituito con un messaggio proprio.
- **Controllo della versione:** con `versione == 1` il backend restituisce la busta così com'è. Con un'altra
  versione restituisce il JSON grezzo più un avviso «formato del monitoraggio non supportato».
- **Errori.** 42501 e gli errori di autenticazione arrivano entrambi come HTTP 401: si distinguono dal `code` nel
  corpo.

| caso | risposta del backend | testo |
|---|---|---|
| chiave non configurata: il backend **non chiama** il DB | 503 | «monitoraggio non configurato» (errore di configurazione) |
| 401 con `code` `42501` | 502 | «chiave di monitoraggio rifiutata» |
| 401 con `code` che inizia con `PGRST3`, oppure senza `code` (gateway) | 502 | «accesso al DB non valido» |
| 404 con `code` `PGRST202` | 502 | «interfaccia non ancora disponibile» |
| timeout | 504 | «monitoraggio non raggiungibile» |
| rete o 5xx | 502 | «monitoraggio non raggiungibile» |

- `p_chiave` vuota o `null` dà 42501.
- Un corpo **senza** il campo `p_chiave` (per esempio `{}`) dà invece 404 `PGRST202`, come la funzione assente:
  PostgREST cerca una funzione senza parametri. Per questo il backend non chiama mai senza chiave. Il caso «non
  configurato» si decide prima della chiamata e non si confonde con «interfaccia non ancora disponibile».

### 3. Frontend: pagina `AdminMonitoraggio.tsx`

- Percorso `/app/admin/monitoraggio`, caricata con `React.lazy`, voce «Monitoraggio» in `adminLinks`.
- Hook TanStack con `refetchInterval` di **5 minuti**; testi in `lib/copy.ts`.
- **Banner, sopra le schede:**
  - rosso se `in_ritardo` è true: «I dati del monitoraggio non sono aggiornati: ultimo calcolo il <aggiornato_at>»,
    oppure «nessun riepilogo ancora calcolato» se `riepilogo` è null;
  - giallo «monitoraggio non configurato» quando il backend risponde 503. È un errore di configurazione, non un
    guasto;
  - grigio con il testo dell'errore («chiave rifiutata», «accesso al DB non valido», «interfaccia non ancora
    disponibile», «monitoraggio non raggiungibile») quando il backend risponde 502 o 504.
  - La pagina non deve mai sembrare «tutto ok» quando non ha dati.
- **Schede in `?tab=`:**
  - **Stato**:
    - `stato` come etichetta (ok, attenzione, guasto);
    - i `segnali` con il loro `testo`, il livello e «attivo dal <dal>»;
    - `non_misurati` come «non misurabile: …»;
    - il blocco `produttore`: ultimo giro, ore dall'ultimo giro, giri e riavvii nelle 24 h, servizio;
    - una nota piccola se `orologio_disallineato`.
  - **Giri**: `giri` (ultimi 20, con giro, inizio, durata, esito, interrotto per tetto e passi non ok) e sotto
    `controlli` (ultimi 10).
  - **Lavorazioni**: `lavorazioni` in corso, con nome, da quanti minuti, durata massima e stato (regolare, lunga,
    probabile orfana).
  - **Ingresso ed eventi**: `ingresso` ed `eventi`.
  - **Job orario**: `job_orario`.
- **Niente dati di spesa**: il riepilogo non ne contiene e il pannello non ne mostra.
- **`da_verificare`** vale `null` finché la verifica dello stato del produttore non è attiva, **anche dopo la
  migrazione 13**: in prova è sempre `null`, e `da_verificare` compare anche in `non_misurati`. Dall'attivazione
  diventa l'oggetto descritto nel contratto DB §14.4: i motivi per ramo, le proposte rimaste senza effetto, le
  chiusure applicate negli ultimi 7 giorni, gli host frenati, le pagine rimosse e le pagine che forse non sono bandi.
  Il tipo «oggetto o `null`» vale già nella versione 1, quindi il passaggio **non cambia `versione`**. Finché vale
  `null`, la scheda «Da verificare» non si mostra; l'attivazione si annuncia per iscritto, come le fusioni (§6.3).
- **Robustezza:**
  - le chiavi sconosciute si ignorano;
  - un codice di segnale sconosciuto si mostra con il suo `testo`;
  - un valore sconosciuto di un'enumerazione si mostra così com'è.
- **Etichette suggerite** per i passi (`passi_non_ok`), da tenere in `lib/copy.ts`:

  | valore | etichetta |
  |---|---|
  | `ingresso` | Ricerca dei bandi nuovi |
  | `lettura` | Lettura delle fonti |
  | `estrazione` | Estrazione dei dati |
  | `arricchimento` | Classificazione |
  | `ricerca_fonti` | Ricerca delle fonti ufficiali |
  | `redazione` | Redazione delle schede |
  | `controllo_pagine` | Controllo delle pagine |
  | `ricontrolli` | Ricontrolli |
  | `verifica_stato` | Verifica dello stato |
  | `altro` | Altro |

  Per `lavorazioni.nome`: `giro` «Giro di raccolta», `controllo_pagine` «Controllo delle pagine», `ricerca_fonti`
  «Ricerca delle fonti ufficiali», `altro` «Altro».

### 4. Test e controlli

- **Test del router con una RPC finta:**
  - 200;
  - 42501 → 502 «chiave rifiutata»;
  - PGRST301 e un 401 senza `code` → 502 «accesso al DB non valido»;
  - PGRST202 → 502 «non ancora disponibile»;
  - chiave assente → 503, e la RPC finta non viene chiamata; timeout → 504;
  - utente non admin → 403;
  - `versione` 2 → JSON grezzo più l'avviso;
  - con un valore di prova della chiave, quel valore **non compare** né nel corpo della risposta né nei log
    catturati.
- **Grep sul `dist` del frontend** dopo la build: né il valore di prova della chiave né il nome
  `SECONDARY_MONITORING_KEY` compaiono.
- **Fixture solo sintetiche**, con i nomi neutri di questo messaggio («catalogo», «DB bandi», «fornitore dei dati»).
- **Documentazione:** `docs/api.md`, `docs/frontend.md` e `changelog.md` con testi neutri; la §14 copiata così
  com'è.

### 5. Messa in produzione

- Si può rilasciare anche prima della migrazione lato DB: il pannello mostrerà «interfaccia non ancora
  disponibile».
- Dopo la migrazione e l'inserimento della chiave, e prima del primo riepilogo, mostrerà «nessun riepilogo ancora
  calcolato». Dal primo riepilogo, i dati.
- **Controllo finale**, da un account admin:
  - la pagina mostra `stato` e `aggiornato_at` recente (meno di 20 minuti);
  - nessuna richiesta del browser contiene la chiave (scheda Rete degli strumenti di sviluppo).

### 6. Seconda parte: certezza dello stato, eventi nuovi, fusioni automatiche

Nessuna di queste novità rompe il consumatore: le colonne nuove stanno in coda alla vista, gli eventi sono di tipi
già noti e le fusioni seguono la `bando_fusione` di oggi. Le sezioni del contratto da rileggere sono §2, §3, §4.1,
§5 (domini degli enti), §6.1, §6.2, §10.2 e R6.

#### 6.1 Cinque colonne nuove in `bando_pubblico` (migrazione 13)

| colonna | cosa dice |
|---|---|
| `stato_da_verificare` | perché lo stato mostrato non è certo, oppure NULL |
| `stato_letto`, `stato_letto_at` | l'ultimo stato letto sulla pagina ufficiale da un lettore strutturato, e quando. NULL se riguarda un altro stato o se viene da un'interpretazione automatica del testo. Fra le letture esposte c'è anche il **lettore generico** delle pagine senza un lettore dedicato: dice solo `chiuso`, da frasi compiute come «Bando chiuso» o «Domande chiuse». È un segnale che accende `smentito_dalla_fonte`: non genera eventi e non cambia lo stato |
| `termine_indicato` | un termine indicato da una fonte non verificata: un indizio, mai una scadenza. NULL finché il bando non è stato esaminato dal controllo attivo del produttore: in prova è sempre NULL |
| `termine_indicato_fonte` | `calendario_ufficiale` \| `pagina` \| `testo` \| `aggregatore` |

- **Regola per il consumatore: uno stato è certo solo con `stato_da_verificare IS NULL`.** Un motivo non cambia lo
  stato: il bando resta fra gli aperti o fra gli «in apertura», nei contatori e nei filtri. Il DB non chiude niente a
  tempo.
- I motivi sono cinque:
  - `data_apertura_passata`;
  - `smentito_dalla_fonte`;
  - `previsione_scaduta`;
  - `senza_conferma`;
  - `termine_passato`.
- **Novità: `senza_conferma` vale anche per gli «aperti» senza scadenza.** Vuol dire che non c'è una prova recente
  dalla pagina ufficiale. Compare solo dopo un controllo attivo del produttore, di regola dal 7° giorno dopo la
  pubblicazione. Compare **prima** se un portale aggregatore segnala il bando come uscito dal suo elenco, in uscita o
  scaduto: quel segnale viene prima della grazia dei 7 giorni (contratto DB §4.1). Il controllo rilegge questi bandi
  ogni 14 giorni e il motivo si spegne da solo con una conferma, una scadenza o una chiusura.
- **In prova** (almeno 7 giorni dopo il rilascio) **l'unico motivo che può comparire è `data_apertura_passata`**,
  che dipende solo dalle date del bando. `previsione_scaduta`, `termine_passato`, `smentito_dalla_fonte` e
  `senza_conferma` compaiono solo dopo l'attivazione, quando il controllo attivo rilegge i bandi. Lo stesso vale per
  `termine_indicato`.
- **Diciture consigliate:** «In apertura · da verificare» e «Aperto · da verificare». Un `termine_indicato` si mostra
  sempre con la sua provenienza («il calendario ufficiale indica…», «un portale aggregatore indica…»), mai come
  scadenza.
- **Quando nominarle.** Le colonne nuove si mettono nelle select **solo dopo la conferma scritta che la 13 è
  applicata**. Prima, una select che ne nomina anche una sola risponde 42703 sull'intera richiesta.
- **Cambio visibile in blocco dopo l'attivazione:** nelle 2-3 settimane successive, man mano che il controllo attivo
  rilegge i bandi, circa 220-260 schede passano a «da verificare» con `senza_conferma`. Insieme compaiono anche gli
  altri motivi che in prova restano spenti: `previsione_scaduta`, `termine_passato` e `smentito_dalla_fonte`, su
  qualche decina di schede in più.

#### 6.2 Eventi nuovi in `bando_evento` (stessi tipi, `origine='worker'`)

- `chiusura` del worker **anche da «in apertura prossimamente»** (prima solo da «aperto»), quando la pagina
  ufficiale dichiara chiuso, scaduto o concluso con un'etichetta strutturata, e dopo due letture uguali a
  distanza di almeno 60 ore.
- `rettifica` con `campo='data_scadenza'` sugli «aperti» senza scadenza, quando la pagina indica un termine certo. Se
  la data è passata, chiude il job orario (`chiusura_automatica`).
- `data_verificata` del worker sugli «in apertura» (date di apertura e di scadenza), con `in_aggiornamenti=false`.
- **R6, calendario.** Le date si propagano leggendo per cursore `proroga`, `rettifica` **e `data_verificata`** con
  `campo='data_scadenza'`.
- **Correzioni.** `in_aggiornamenti` vale `true` solo se la notizia è nuova (lo stesso lettore aveva visto il bando
  aperto nei 30 giorni prima). Altrimenti l'evento è una correzione: leggibile per lo stato, fuori da un box
  «Aggiornamenti».
- **Volumi della prima settimana in esecuzione:** circa 50 chiusure, al massimo 20 per giro, quasi tutte correzioni
  (`in_aggiornamenti=false`).

#### 6.3 Fusioni automatiche dei doppioni certi

- Il produttore fonde da solo i doppioni **certi**: stesso URL normalizzato, oppure stessa riga di calendario della
  stessa fonte. Ci sono guardie di prudenza: nessuna fusione fra edizioni, lotti o annualità diversi, e i gruppi di
  più di due righe restano a mano.
- Stessa `bando_fondi` di oggi: nessuna riga cancellata, id e slug congelati, doppione in 301 verso il master, una
  riga in `bando_fusione` e un evento `fusione`. La rimappatura del consumatore resta com'è.
- Una riga nuova gemella esatta di un pubblicato **non viene mai pubblicata**: si fonde prima, con la stessa
  `bando_fondi`, a ogni giro e senza il tetto giornaliero qui sotto. Nella vista non compare, ma lascia tracce
  (contratto DB §6.2):
  - una riga in `bando_fusione` con `slug_originale` NULL, da ignorare nella rimappatura (nessun utente può averla
    salvata);
  - un evento `fusione` sul master, e uno sul doppione con un `bando_id` mai visto, da ignorare;
  - i link del doppione copiati sul master e `ultimo_cambiamento_at` del master che avanza.
- **Volume:** 52 fusioni all'attivazione (43 per URL e 9 di calendario), al massimo 10 al giorno fra pubblicati,
  quindi circa 6 giorni. Poi poche al mese. Il numero esatto si comunica alla vigilia. Le fusioni prima della
  pubblicazione non contano in questo tetto: in `bando_fusione` si riconoscono da `slug_originale` NULL.
- **Avviso:** almeno 7 giorni prima che le fusioni automatiche passino dalla prova all'esecuzione. È il momento di
  mettersi in modalità `prova`, come per i lotti a mano.

#### 6.4 Domini degli enti

Il produttore importa ogni mese l'intero indice pubblico delle pubbliche amministrazioni come domini ufficiali, con
soli inserimenti. Per il consumatore l'effetto è indiretto: più pagine ufficiali leggibili e più eventi
`verificato`. La denylist degli aggregatori non cambia e prevale sempre.

Grazie: chiediamo conferma scritta con data del deploy e commit, come per le fasi precedenti.
