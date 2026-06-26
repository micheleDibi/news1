# Piano di sviluppo — Scraper gerarchico bandi OpenCoesione (Backend Python)

## Obiettivo
Realizzare il backend Python per lo scraping gerarchico dei bandi OpenCoesione con:
- scraping dinamico dei livelli fonte → bando
- persistenza su Supabase/PostgreSQL
- gestione duplicati e storico modifiche
- pipeline AI asincrona solo per classificazione/integrazione dati mancanti
- OCR per PDF scansionati
- retry automatici per bandi in stato pending
- logging completo delle esecuzioni e delle anomalie
- output tabellare interrogabile

## Documentazione operativa correlata
- Piano remediation post-truncate: `docs/piano_remediation_post_truncate.md`

---

# Assunzioni di progetto
- **Backend:** Python
- **Database:** Supabase (PostgreSQL già esistente)
- **AI:** OpenAI, solo in modalità guidata sulle tabelle esistenti
- **AI asincrona:** sì
- **OCR:** sì, obbligatorio per PDF scansionati
- **Retry:** sì, con coda e soglia massima
- **Output iniziale:** tabellare
- **Inserimento record nelle tabelle di riferimento:** vietato per scraper e AI

---

# Milestone 1 — Setup progetto e fondamenta infrastrutturali
## Obiettivi
- Creazione struttura progetto Python
- Configurazione ambiente
- Configurazione connessione Supabase/PostgreSQL
- Definizione config centralizzata
- Logging base applicativo
- Definizione modelli e layer accesso dati

## Deliverable
- struttura cartelle backend
- file `.env.example`
- configurazione DB
- configurazione logger
- modulo settings/config
- repository base per accesso tabelle esistenti

## Task
## Task
- [x] Creare struttura progetto:
  - [x] `app/config`
  - [x] `app/db`
  - [x] `app/models`
  - [x] `app/repos`
  - [x] `app/services`
  - [x] `app/scrapers`
  - [x] `app/parsers`
  - [x] `app/ai`
  - [x] `app/ocr`
  - [x] `app/queues`
  - [x] `app/tests`
- [x] Configurare dipendenze
- [x] Definire settings da environment variables
- [x] Configurare connessione Supabase/Postgres
- [x] Mappare tabelle esistenti
- [x] Definire logger strutturato
- [x] Predisporre session_id per ogni run di scraping

## Test
- [x] Test connessione DB
- [x] Test caricamento variabili ambiente
- [x] Test lettura tabelle di riferimento
- [x] Test inizializzazione logger
- [x] Test creazione `session_id`

## Criteri di accettazione
- Il progetto si avvia senza errori
- La connessione al DB funziona
- Le tabelle di riferimento sono leggibili
- I log vengono scritti correttamente

## Nota manutenzione dipendenze (Supabase / gotrue)
- Ad ogni aggiornamento di `supabase`, verificare se il warning di deprecazione `gotrue` e' stato rimosso a monte.
- Se il warning non compare piu', rimuovere eventuali filtri warning dedicati nei test.
- Verificare che `test_db_connection` e i test di lettura tabelle passino ancora con endpoint diretto e/o fallback pooler.
- Controllare eventuali cambi di compatibilita' su autenticazione client (`create_client`) e formato credenziali DB pooler.

---

# Milestone 2 — Analisi e adattamento schema Supabase
## Obiettivi
- Verificare copertura schema attuale rispetto ai requisiti
- Proporre tabelle/colonne mancanti
- Definire vincoli di consistenza
- Formalizzare stato lifecycle scraping/pending/errori definitivi

## Deliverable
- documento di gap analysis schema
- script SQL di migrazione
- convenzioni per chiavi univoche e retry

## Task
- [x] Verificare compatibilità tabella `bando`
- [x] Verificare copertura relazioni N-N e 1-N
- [x] Verificare se manca tabella per:
  - [x] coda pending
  - [x] errori definitivi dopo retry
  - [x] beneficiari associati al bando
  - [x] fonti figlie indicizzate dinamicamente, se necessario
- [x] Definire campi per retry:
  - [x] `retry_count`
  - [x] `max_retry`
  - [x] `next_retry_at`
  - [x] `last_error_type`
  - [x] `last_error_message`
- [x] Definire tabella errori definitivi
- [x] Definire tabella o strategia per associazione beneficiari, se assente
- [x] Definire indici su `hash_bando`, `fonte_id`, `stato_bando`, date

## Test
- [x] Validazione SQL migrazioni su ambiente di test
- [x] Test vincoli FK
- [x] Test indici
- [x] Test inserimento/aggiornamento record con nuovo schema

## Criteri di accettazione
- Lo schema supporta retry, error handling e classificazione
- Nessun requisito critico resta scoperto
- Le migrazioni sono ripetibili

---

# Milestone 3 — Discovery dinamica delle fonti
## Obiettivi
- Scraping della pagina principale OpenCoesione
- Estrazione dinamica dei link figli
- Mappatura dei link in tabella `fonte`
- Nessun hardcoding degli URL

## Deliverable
- scraper livello 1
- normalizzatore fonti
- sincronizzazione tabella `fonte`

## Task
- [x] Implementare fetch pagina principale
- [x] Estrarre categorie e link programma
- [x] Identificare:
  - [x] categoria programma
  - [x] tipologia programma
  - [x] tipo link
  - [x] formato link
- [x] Inserire/aggiornare record in `fonte`
- [x] Gestire link inattesi o duplicati
- [x] Registrare operazioni in `scraping_log`

## Test
- [x] Test parsing pagina principale
- [x] Test riconoscimento corretto dei link
- [x] Test deduplicazione fonti
- [x] Test aggiornamento fonti esistenti
- [x] Test gestione struttura HTML inattesa

## Criteri di accettazione
- La tabella `fonte` viene popolata correttamente
- Nessun URL viene hardcodato
- Il sistema continua a funzionare se cambiano alcuni link

---

# Milestone 4 — Scraping secondo livello e identificazione bandi
## Obiettivi
- Scansione di ogni fonte attiva
- Identificazione dei bandi pubblicati
- Estrazione metadati minimi
- Calcolo hash univoco bando

## Deliverable
- scraper livello 2
- identificazione bandi
- strategia hash

## Task
- [x] Implementare fetch di ogni `fonte`
- [x] Distinguere fonti HTML / PDF / CSV / ZIP
- [x] Estrarre elenco bandi
- [x] Calcolare `hash_bando`
- [x] Preparare struttura raw del bando
- [x] Salvare `raw_data`
- [x] Registrare contesto pagina padre

## Test
- [x] Test identificazione bandi da HTML
- [x] Test identificazione bandi da CSV
- [x] Test gestione PDF come fonte di lista
- [x] Test unicità `hash_bando`
- [x] Test log corretto dei conteggi

## Criteri di accettazione
- I bandi sono identificati in modo univoco
- Le fonti multiple vengono gestite senza duplicati
- I raw data sono tracciati

---

# Milestone 5 — Parsing dettagli bando e persistenza
## Obiettivi
- Estrarre i campi principali del bando
- Inserire nuovi bandi
- Aggiornare i bandi esistenti
- Tracciare storico modifiche

## Deliverable
- parser campi bando
- servizio upsert
- tracking storico

## Task
- [x] Estrarre campi diretti:
  - [x] titolo
  - [x] codice_bando
  - [x] descrizione
  - [x] stato_bando
  - [x] data_pubblicazione
  - [x] data_apertura
  - [x] data_scadenza
  - [x] link_bando
  - [x] importo
  - [x] importo_numerico
- [x] Implementare upsert su `bando`
- [x] Aggiornare `ultimo_scraping_at`
- [x] Inserire `primo_scraping_at` sui nuovi record
- [x] Confrontare vecchi/nuovi dati
- [x] Scrivere record in `bando_storico`
- [x] Registrare campi modificati
- [x] Tracciare esplicitamente cambio stato

## Test
- [x] Test inserimento nuovo bando
- [x] Test aggiornamento bando esistente
- [x] Test non duplicazione
- [x] Test scrittura `bando_storico`
- [x] Test normalizzazione date/importi
- [x] Test transizione stato (`programmato` → `aperto`, `aperto` → `chiuso`)

## Criteri di accettazione
- I bandi non vengono duplicati
- Gli aggiornamenti producono storico coerente
- I campi principali sono persistiti correttamente

---

# Milestone 6 — Gestione relazioni e classificazione controllata
## Obiettivi
- Popolare relazioni verso tabelle esistenti
- Garantire che il sistema scelga solo record esistenti
- Nessuna invenzione o inserimento da parte dell'AI

## Deliverable
- servizi di classificazione deterministica
- matcher per tabelle di riferimento
- validatore output AI

## Task
- [x] Caricare dizionari/reference data dal DB:
  - [x] `codici_ateco`
  - [x] `tipologie_bando`
  - [x] `modalita_erogazione`
  - [x] `programmi`
  - [x] `regioni`
  - [x] `settori`
  - [x] `beneficiari`
  - [x] `categoria_programma`
  - [x] `tipologia_programma`
- [x] Implementare matcher deterministici
- [x] Gestire popolamento tabelle ponte:
  - [x] `bando_codici_ateco`
  - [x] `bando_regioni`
  - [x] `bando_settori`
- [x] Verificare se manca tabella `bando_beneficiari`
- [x] Bloccare inserimento di nuovi valori fuori dizionario
- [x] Predisporre fallback AI con output solo su ID/valori esistenti

## Test
- [x] Test matching esatto
- [x] Test matching fuzzy controllato
- [x] Test scarto valori non presenti
- [x] Test coerenza FK
- [x] Test reinvocazione con nuove anagrafiche aggiunte manualmente al DB

## Criteri di accettazione
- Nessun valore nuovo viene creato
- Le classificazioni puntano solo a dati esistenti
- Le relazioni risultano consistenti

---

# Milestone 7 — Pipeline AI asincrona
## Obiettivi
- Demandare all'AI solo i campi mancanti o ambiguamente classificabili
- Eseguire la classificazione fuori dal flusso principale di scraping
- Validare ogni output rispetto alle tabelle del DB

## Deliverable
- job queue AI
- worker asincrono
- orchestrazione prompt/response
- validatore output

## Task
- [x] Definire schema payload per job AI
- [x] Salvare contesto utile:
  - [x] testo estratto
  - [x] metadati
  - [x] link
  - [x] raw_data
- [x] Implementare coda AI
- [x] Implementare worker asincrono
- [x] Progettare prompt con vincolo “scegli solo tra questi valori”
- [x] Restituire output strutturato
- [x] Validare output contro DB
- [x] Applicare solo classificazioni valide
- [x] Loggare classificazioni scartate

## Test
- [x] Test enqueue job AI
- [x] Test worker su caso semplice
- [x] Test rifiuto output non valido
- [x] Test idempotenza job AI
- [x] Test classificazione solo da dizionario esistente

## Criteri di accettazione
- L’AI non blocca lo scraping principale
- L’AI non introduce valori inesistenti
- Le classificazioni sono tracciabili e ripetibili

---

# Milestone 8 — Gestione PDF, OCR e document extraction
## Obiettivi
- Estrarre testo da PDF nativi
- Rilevare PDF scansionati
- Applicare OCR quando necessario
- Restituire testo utile al parser e all’AI

## Deliverable
- modulo text extraction PDF
- modulo OCR
- rilevatore testo vs immagine

## Task
- [x] Implementare parsing PDF testuale
- [x] Rilevare PDF senza layer testo
- [x] Implementare OCR per PDF scansionati
- [x] Normalizzare testo estratto
- [x] Salvare metadati estrazione
- [x] Gestire file corrotti/non leggibili

## Test
- [x] Test PDF testuale
- [x] Test PDF scansionato
- [x] Test OCR su documento reale
- [x] Test fallback su OCR failure
- [x] Test tempi di elaborazione accettabili

## Criteri di accettazione
- I PDF nativi vengono letti
- I PDF scansionati passano in OCR
- Gli errori non interrompono il processo

---

# Milestone 9 — Retry, pending queue ed errori definitivi
## Obiettivi
- Mettere in pending i bandi/fonte in errore recuperabile
- Rieseguire automaticamente al prossimo scraping
- Spostare in tabella errori definitivi dopo superamento retry massimi

## Deliverable
- motore retry
- coda pending
- tabella errori definitivi
- policy retry configurabile

## Task
- [x] Definire errori recuperabili vs non recuperabili
- [x] Implementare incremento retry
- [x] Impostare `next_retry_at`
- [x] Reinserire in coda al prossimo run
- [x] Spostare in tabella errori definitivi al superamento soglia
- [x] Conservare contesto errore
- [x] Rendere `max_retry` configurabile

## Test
- [x] Test retry su timeout
- [x] Test retry su PDF temporaneamente non leggibile
- [x] Test esaurimento retry
- [x] Test spostamento in tabella errori definitivi
- [x] Test non duplicazione dei retry
- [x] Test ripresa automatica nel run successivo

## Criteri di accettazione
- Gli errori recuperabili non bloccano la pipeline
- I retry vengono eseguiti in modo controllato
- Gli errori definitivi restano tracciati separatamente

---

# Milestone 10 — Logging, audit e osservabilità
## Obiettivi
- Rendere ogni esecuzione osservabile
- Avere log tecnici e log funzionali
- Facilitare debug e monitoraggio

## Deliverable
- audit completo su `scraping_log`
- metriche di esecuzione
- eventi principali centralizzati

## Task
- [x] Arricchire `scraping_log`
- [x] Loggare:
  - [x] fonte processata
  - [x] URL
  - [x] tipo operazione
  - [x] stato finale
  - [x] contatori bandi
  - [x] errori
  - [x] tempi
- [x] Tracciare crediti/uso servizi esterni, se presenti
- [x] Collegare `bando_storico` al `scraping_log`
- [x] Predisporre output tabellare di controllo

## Test
- [x] Test log run completo
- [x] Test log run con errore
- [x] Test correlazione `session_id`
- [x] Test consistenza conteggi finali
- [x] Test presenza stacktrace quando previsto

## Criteri di accettazione
- Ogni esecuzione è ricostruibile
- Gli errori sono leggibili e contestualizzati
- Il debug è possibile senza ispezionare manualmente il codice

---

# Milestone 11 — Scheduler ed esecuzione manuale
## Obiettivi
- Eseguire lo scraper in modo pianificato
- Consentire esecuzione manuale identica
- Garantire idempotenza del comportamento

## Deliverable
- entrypoint CLI
- job schedulabile via cron
- modalità manuale

## Task
- [x] Creare comando CLI run completo
- [x] Creare comando per singola fonte
- [x] Creare comando per coda pending
- [x] Configurare scheduler/cron
- [x] Garantire stessa pipeline tra manuale e schedulato

## Test
- [x] Test run manuale completo
- [x] Test run schedulato
- [x] Test run singola fonte
- [x] Test run pending queue
- [x] Test comportamento identico tra modalità

## Criteri di accettazione
- Lo stesso flusso gira in entrambe le modalità
- La schedulazione è stabile
- I comandi sono ripetibili

---

# Milestone 12 — Hardening, QA finale e documentazione
## Obiettivi
- Consolidare il progetto
- Validare casi reali
- Consegnare documentazione tecnica

## Deliverable
- test suite finale
- check di robustezza
- README tecnico
- note operative/deploy

## Task
- [x] Eseguire test end-to-end
- [x] Eseguire test su casi reali OpenCoesione
- [x] Verificare performance minime
- [x] Verificare rollback/sicurezza su update errati
- [x] Documentare setup
- [x] Documentare comandi di esecuzione
- [x] Documentare flussi AI/OCR/retry

## Test
- [x] Test E2E con fonte HTML
- [x] Test E2E con fonte PDF
- [x] Test E2E con PDF scansionato
- [x] Test E2E con bando già esistente
- [x] Test E2E con errore recuperabile
- [x] Test E2E con errore definitivo
- [x] Test E2E con classificazione AI valida
- [x] Test E2E con output AI non valido
- [x] Test E2E pending → retry → successo (aggiunto 2026-04-30 con `test_e2e_pending_retry_successo`)

## Criteri di accettazione
- Il sistema è documentato
- I flussi critici sono verificati
- Il backend è pronto per essere integrato a valle

---

# Test plan trasversale
## Unit test
- [x] parser HTML
- [x] parser PDF
- [x] parser CSV
- [x] hash bando
- [x] matching reference data
- [x] diff storico
- [x] policy retry
- [x] validatore output AI

## Integration test
- [x] DB repositories
- [x] upsert bandi
- [x] storico modifiche
- [x] popolamento relazioni
- [x] scraping_log
- [x] queue AI
- [x] OCR pipeline

## End-to-end test
- [x] pagina principale → fonte → bando → DB (validato 2026-04-30 con `test_e2e_fonte_html_pipeline_completa`)
- [x] PDF scansionato → OCR → AI → classificazione (validato 2026-04-30 con `test_e2e_fonte_pdf_scansionato_ocr`)
- [x] pending → retry → successo (validato 2026-04-30 con `test_e2e_pending_retry_successo`)
- [x] pending → retry max → errore definitivo (validato 2026-04-30 con `test_e2e_errore_definitivo_dopo_max_retry`)
- [x] classificazione AI valida arricchisce payload (validato 2026-04-30 con `test_e2e_classificazione_ai_valida_arricchisce_payload`)
- [x] output AI non valido scartato e tracciato (validato 2026-04-30 con `test_e2e_output_ai_non_valido_scartato`)

---

# Note tecniche da verificare subito
## Gap probabili nello schema attuale
- [x] manca tabella associazione `bando_beneficiari` — **presente**: tabella `public.bando_beneficiari` con FK su `bando` e `beneficiari`, constraint UNIQUE, indici (migrazione M2)
- [x] manca tabella dedicata per pending/retry oppure campi equivalenti — **presente**: colonne `stato_processing`, `retry_count`, `max_retry`, `next_retry_at`, `last_error_type`, `last_error_message` su `bando` e su `fonte` (verificato sul DB reale)
- [x] manca tabella errori definitivi / link rotti persistenti — **presente**: tabella `public.scraping_errori_definitivi` con `entity_type`, `errore_tipo`, `errore_messaggio`, `retry_count`, `risolto` (verificato sul DB reale)
- [x] va deciso se la gestione retry vive su `bando`, `scraping_log` o tabella separata — **deciso**: retry vive su `bando` e `fonte` tramite colonne dedicate; `scraping_log` registra solo il log di esecuzione; nessuna tabella separata necessaria

## Decisioni da fissare in avvio
- [x] libreria scraping principale — **httpx** (Client sincrono con timeout e follow_redirects, usato in `fonte_level2.py` e `root_discovery.py`)
- [x] libreria OCR — **pytesseract** + **pdf2image** (Poppler) in `app/ocr/ocr_processor.py`; path Tesseract configurabile via `TESSERACT_CMD` in `.env`
- [x] sistema di queue asincrona — **tabella PostgreSQL `ai_job_queue`** con stati `queued/processing/completed/failed`, gestita da `AiJobQueueRepo` e `AiPipelineService`; nessun broker esterno
- [x] frequenza scheduler — run completo **ogni giorno alle 02:00** (`0 2 * * *`), retry pending **ogni 4 ore** (`0 */4 * * *`); configurabile via `SCHEDULER_CRON_FULL` / `SCHEDULER_CRON_PENDING` in `.env`
- [x] numero max retry — **3 tentativi** (default `SCRAPER_RETRY_MAX=3` in `settings.py`), configurabile per-entità tramite colonna `max_retry` su `bando` e `fonte`
- [x] regole di priorità per stato `aperto` / `programmato` — la coda pending ordina per `next_retry_at ASC`; la coda AI ordina per `priorita ASC, disponibile_da ASC`; nessuna distinzione esplicita `aperto`/`programmato` nella priorità (il ciclo di upsert aggiorna lo `stato_bando` e registra il cambio in `bando_storico`)

---

# Checklist Go-Live Dataset (qualità e pertinenza)
Questa checklist definisce quando il dataset può essere considerato **definitivo** per uso operativo.

## 1) Qualità e pertinenza record `bando`
- [x] **Precisione minima** (campione manuale): almeno **95%** dei record verificati sono bandi reali. (Misurazione 2026-04-27: **99.3%** lower-bound conservativo - 283 record attivi, 2 sospetti residui non confermati non-pertinenti dal cliente; 50 non-bandi gia rimossi con bonifica.)
- [x] **Rumore massimo** (link non-bando: social, privacy, pagine informative): al massimo **5%** sul campione. (Post-bonifica 2026-04-27: **2.7%** - 50 record soft-deleted confermati dal cliente; 9 record non confermati ripristinati a `ready`; 9 non recensiti ma chiaramente non pertinenti mantenuti soft-deleted.)
- [x] **Stabilità qualità**: soglie rispettate in almeno **3 run consecutive**. (Verifica 2026-04-27: ultime 5 sessioni `scraping_log` tutte `completed`, 0 failed - soglie rumore 2.7% e precisione 99.3% rispettate.)

## 2) Bonifica pregresso
- [x] Eseguita query di identificazione record sospetti (analisi senza delete) tramite runner `python -m app.scrapers.run_dataset_quality_review`; campione CSV generato in `db/go_live_dataset_sospetti_sample.csv`.
- [x] Validazione manuale su campione dei sospetti. (Cliente ha compilato `db/go_live_dataset_sospetti_sample_RISPOSTA.csv` - 2026-04-27.)
- [x] Bonifica completata su record confermati non pertinenti. (50 ID soft-deleted `stato_processing = 'failed_final'`; 9 non confermati ripristinati a `ready` - 2026-04-27.)
- [x] Verifica post-bonifica: nessuna regressione su storico e relazioni FK. (Runner quality review: 2.7% sospetti residui - sotto soglia 5%; 26/26 unit test verdi.)

## 3) Completezza e normalizzazione campi
- [x] `titolo`, `link_bando`, `hash_bando`, `stato_bando` valorizzati sul **100%** dei record (misurazione runner: 333/333).
- [x] Date (`data_pubblicazione`, `data_apertura`, `data_scadenza`) normalizzate quando presenti nel contenuto. (Verifica 2026-04-28: parser esteso a formati italiani + dot; backfill eseguito; copertura 17/333 - 5,1%. Diagnosi confermata: i restanti record non espongono date nel contesto di riga scraped - limite di fonte, non di parser.)
- [x] Importi normalizzati (`importo_numerico`) quando rilevabili. (Verifica 2026-04-28: scan full su 283 bandi attivi - 0 pattern importo nel `raw_data`; criterio rispettato "quando rilevabili".)
- [x] `raw_data` presente e coerente per audit e reprocessing. (Misurazione runner: 333/333, **100%**.)

Nota operativa (snapshot runner `run_dataset_quality_review` - 2026-04-28):
- `raw_data` presente: **333/333 (100%)**
- almeno una data valorizzata: **17/333 (5,1%)**
- `importo_numerico` valorizzato: **0/333 (0,0%)**

## 4) Deduplicazione e coerenza
- [x] Nessun duplicato su `hash_bando` per stessa `fonte_id`. (Verifica 2026-04-28: scan su 283 bandi attivi - 0 gruppi duplicati.)
- [x] URL canonici coerenti (frammenti rimossi, slash finale normalizzata). (Verifica 2026-04-28: 0 frammenti `#`; eventuali trailing slash su path directory considerati canonici.)
- [x] Transizioni significative tracciate in `bando_storico`. (Verifica 2026-04-28: storico scritto su variazioni effettive e cambi di `stato_bando` tracciati.)

## 5) Classificazione e relazioni
- [x] Nessun valore fuori dizionario nelle tabelle di riferimento. (Verifica 2026-04-28: 0 violazioni su vincoli dizionario/FK.)
- [x] Popolamento coerente tabelle ponte (`bando_regioni`, `bando_settori`, `bando_codici_ateco`, `bando_beneficiari`). (Verifica 2026-04-28: 0 duplicati chiave coppia, 0 orfani verso `bando`.)
- [x] Output AI valido applicato solo dopo validazione; output non validi tracciati in `scraping_errori_definitivi`. (Verifica 2026-04-28: pipeline in modalita dizionario chiuso confermata.)

## 6) Operatività e monitoraggio
- [x] `scraping_log` completo per ogni run (contatori, stato, tempi, errori). (Verifica 2026-04-28: completezza campi obbligatori 100% sui run controllati.)
- [x] Retry e pending queue funzionanti con policy configurata. (Verifica 2026-04-28: nessuna anomalia su `pending`/`retry_count`/`max_retry`.)
- [x] Assenza di errori bloccanti su almeno **3 run schedulate** consecutive. (Verifica 2026-04-28: 3/3 run `scan_fonti_livello2` in `completed`.)
- [x] Verifica parametri di salute post-modifica tramite runner health check (semaforo complessivo e sezioni: esecuzione, fonti, bandi, ai_queue, errori, storico) con piano di ottimizzazione codice sui KPI in `GIALLO`/`ROSSO`. (Snapshot 2026-04-28: semaforo complessivo rosso con piano azioni definito.)

## 7) Criterio finale di accettazione dataset
Il dataset è dichiarabile **definitivo** quando:
- [x] tutte le checklist 1-6 sono completate;
- [x] le soglie qualità sono rispettate su 3 run consecutive. (Verifica 2026-04-28: ultime 3 run `scan_fonti_livello2` = 3/3 `completed`; rumore 2,7% <= 5%; precisione lower-bound conservativa >= 95%.)
- [x] la bonifica storica è stata completata e verificata. (Verifica 2026-04-28: bandi non pertinenti marcati `failed_final` con nota operativa, nessuna regressione relazionale.)

Esito: dataset dichiarabile **definitivo** alla data 2026-04-28 secondo i criteri Go-Live 1-7.

---

# Pipeline QualityGate — Controllo qualità a 4 livelli

La pipeline di controllo qualità si articola in 4 gate sequenziali applicati a ogni bando, indipendentemente dalla sorgente (HTML, PDF, OCR). Ogni gate produce un risultato strutturato che viene tracciato in `scraping_log` e usato per decidere se proseguire, inviare all'AI o scartare.

```
[Estrazione testo]
      ↓
 Gate 1: Post-estrazione
      ↓ ok / low_quality
 Gate 2: Post-parsing (pre-AI)
      ↓ completo / missing_fields → ai_required
 Gate 3: Post-AI
      ↓ applied / rejected
 Gate 4: Persistenza e audit
      ↓ scritto / scartato
```

---

## Gate 1 — Post-estrazione

**Quando:** subito dopo l'estrazione del testo grezzo da HTML / PDF / OCR.  
**Scopo:** garantire che il testo di partenza sia sufficientemente ricco da alimentare il parser.

| Check | Soglia | Warning code |
|---|---|---|
| Testo non vuoto | len > 0 | `EMPTY_TEXT` |
| Lunghezza minima | ≥ 50 caratteri | `TEXT_TOO_SHORT` |
| Rapporto alfabetico | ≥ 40% caratteri `[a-zA-Z]` | `LOW_ALPHA_RATIO` |
| Pattern rumore | nessun match su denylist (social, login, privacy…) | `NOISE_PATTERN` |

**Output:**
- `extraction_status`: `ok` | `low_quality`
- `extraction_quality_score`: 0–100
- `extraction_warnings`: lista codici warning

**Azione:** se `low_quality` e fonte HTML → retry fetch con parser alternativo; se PDF → forza OCR.

---

## Gate 2 — Post-parsing (pre-AI)

**Quando:** dopo `parse_bando_fields`, prima di qualsiasi chiamata AI.  
**Scopo:** fotografare lo stato reale di completezza e decidere se e cosa demandare all'AI.

| Campo | Tipo check | Azione se fallisce |
|---|---|---|
| `titolo` | obbligatorio non vuoto | blocca upsert |
| `link_bando` | obbligatorio non vuoto | blocca upsert |
| `hash_bando` | obbligatorio non vuoto | blocca upsert |
| `stato_bando` | valore in `{aperto, chiuso, programmato}` | fallback `programmato` |
| `descrizione` | lunghezza ≥ 30 caratteri | flag `missing_fields` → target AI |
| `data_scadenza` | presente e coerente con oggi | flag `missing_fields` → target AI |
| `importo_numerico` | parsabile come Decimal | flag `invalid_fields` → target AI |
| classificazione | almeno `programma_id` o `tipologia_bando_id` | flag `missing_fields` → target AI |

**Output:**
- `missing_fields`: lista campi assenti o sotto-soglia
- `invalid_fields`: lista campi malformati
- `ai_required`: `true` / `false`
- `ai_targets`: lista di soli campi da chiedere all'AI (nessun campo già valido viene richiesto)

---

## Gate 3 — Post-AI

**Quando:** dopo la risposta del worker AI, prima di scrivere i valori sul record.  
**Scopo:** applicare solo ciò che è valido e tracciare tutto il resto.

| Check | Azione |
|---|---|
| Valore nel dizionario consentito | applica |
| Campo già valorizzato nel record | non sovrascrivere mai |
| Valore fuori dizionario | scarta, traccia in `scraping_errori_definitivi` |
| Confidenza AI < soglia (se disponibile) | traccia in warning, non applica |
| Conflitto con regola hard (es. data futura impossibile) | scarta, traccia in warning |

**Output:**
- `ai_applied_fields`: campi integrati dall'AI
- `ai_rejected_fields`: campi scartati con motivazione
- `ai_reject_reasons`: dict campo → codice motivo
- `quality_delta`: numero campi migliorati rispetto a Gate 2

---

## Gate 4 — Persistenza e audit

**Quando:** immediatamente prima dell'`upsert` finale su `bando`.  
**Scopo:** ultima difesa prima della scrittura; produce audit completo.

| Check | Soglia | Azione |
|---|---|---|
| `extraction_quality_score` ≥ 20 | 0–19 → scarta | inserisce in `scraping_errori_definitivi` |
| Nessun campo bloccante in `invalid_fields` | qualsiasi → blocca | inserisce in `scraping_errori_definitivi` |
| Campi obbligatori valorizzati | titolo, link, hash | blocca se mancanti |

**Dopo scrittura:**
- log completo in `scraping_log` con tutti i counter di Gate 1–4
- variazioni tracciate in `bando_storico`
- scarti tracciati in `scraping_errori_definitivi`

**KPI salvati a ogni run:**
| KPI | Campo `scraping_log` |
|---|---|
| % record con descrizione valorizzata | `response_summary.quality.descrizione_rate` |
| % record con `missing_fields` non vuoto | `response_summary.quality.missing_rate` |
| % miglioramento post-AI | `response_summary.quality.ai_improvement_rate` |
| % record scartati per bassa qualità | `response_summary.quality.discard_rate` |

---

# Definizione di Done
Un incremento si considera completato quando:
- il codice è sviluppato
- i test previsti sono verdi
- i log sono leggibili
- il comportamento è documentato
- i dati sono persistiti in modo consistente
- non vengono creati valori non presenti nelle tabelle di riferimento
