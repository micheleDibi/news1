# Piano remediation post-truncate

Aggiornato al: 2026-05-07

## Obiettivo
Documentare in modo operativo e verificabile la remediation delle anomalie rilevate dopo reset completo dataset e rilancio pipeline.

Questo documento NON modifica codice direttamente: definisce interventi tecnici, criteri di accettazione, query di controllo e ordine di esecuzione.

## Scope
- Reset completo tabelle operative.
- Riesecuzione pipeline end-to-end.
- Analisi puntuale problemi noti.
- Definizione fix implementativi per ogni problema.
- Verifica quantitativa tramite KPI.

## Regole operative
- Eseguire prima in ambiente di test/staging.
- Conservare snapshot pre-run.
- Tracciare ogni run con session_id e scraping_log.
- Non chiudere un problema senza query di validazione e test automatico associato.

---

## Fase 0 - Baseline e backup

Prerequisito bloccante:
- Se la connessione DB restituisce errori di autenticazione o circuit breaker (es. `ECIRCUITBREAKER`), interrompere l'esecuzione e risolvere prima credenziali/connettivita.
- Non procedere a Fase 1 finche Fase 0 non e completata e validata.

### 0.1 Snapshot logico (consigliato, ma NON sufficiente da solo)
- Export CSV delle tabelle: bando, bando_storico, bando_settori, bando_codici_ateco, bando_beneficiari, ai_job_queue, scraping_log, scraping_errori_definitivi.
- Salvataggio KPI baseline:
  - totale bandi
  - percentuale bandi con titolo non nullo
  - percentuale bandi con descrizione non nulla
  - percentuale bandi con date valorizzate
  - percentuale bandi con importo_numerico plausibile
  - percentuale bandi con is_bando_confermato non nullo

### 0.2 Backup completo ripristinabile (OBBLIGATORIO prima di TRUNCATE e fix)
Obiettivo: poter tornare esattamente allo stato pre-modifica, non solo ai dati principali.

Contenuto minimo del backup completo:
- schema + dati di tutto il database applicativo
- ownership/privilegi coerenti con ambiente target
- timestamp e identificativo run nel nome file

Comando consigliato (format custom, adatto a restore selettivo/totale):

```powershell
$env:PGPASSWORD = "<PASSWORD>"
pg_dump \
  --host "<HOST>" \
  --port "<PORT>" \
  --username "<USER>" \
  --dbname "<DBNAME>" \
  --format=custom \
  --verbose \
  --file "backup_pre_remediation_20260507.dump"
```

### 0.3 Restore di ritorno (procedura di rollback)
Usare una delle due modalita:

1. Ripristino su DB pulito dedicato (consigliato):

```powershell
$env:PGPASSWORD = "<PASSWORD>"
pg_restore \
  --host "<HOST>" \
  --port "<PORT>" \
  --username "<USER>" \
  --dbname "<DBNAME_RESTORE>" \
  --clean \
  --if-exists \
  --verbose \
  "backup_pre_remediation_20260507.dump"
```

2. Ripristino in-place (solo se approvato):
- fermare processi di scraping/worker
- eseguire restore con --clean --if-exists
- validare integrita post-restore con query KPI e conteggi tabelle

### 0.4 Test di ripristino obbligatorio
Il backup e considerato valido solo se:
- il file dump viene generato senza errori
- un restore di prova termina con successo
- i conteggi chiave coincidono con il pre-modifica (bando, fonte, scraping_log, relazioni)

Se il dump non viene generato (file assente o vuoto), considerare Fase 0 fallita.

### 0.5 Query KPI baseline
```sql
SELECT
  COUNT(*) AS totale,
  COUNT(*) FILTER (WHERE titolo IS NOT NULL AND btrim(titolo) <> '') AS with_titolo,
  COUNT(*) FILTER (WHERE descrizione IS NOT NULL AND btrim(descrizione) <> '') AS with_descrizione,
  COUNT(*) FILTER (WHERE data_pubblicazione IS NOT NULL) AS with_data_pubblicazione,
  COUNT(*) FILTER (WHERE data_apertura IS NOT NULL) AS with_data_apertura,
  COUNT(*) FILTER (WHERE data_scadenza IS NOT NULL) AS with_data_scadenza,
  COUNT(*) FILTER (WHERE importo_numerico IS NOT NULL) AS with_importo,
  COUNT(*) FILTER (WHERE is_bando_confermato IS NOT NULL) AS with_is_bando
FROM public.bando;
```

---

## Fase 1 - Reset totale tabelle

ATTENZIONE: questa procedura e distruttiva.

### 1.1 Truncate full reset (ambiente test)
```sql
BEGIN;

TRUNCATE TABLE
  public.bando_storico,
  public.bando_beneficiari,
  public.bando_settori,
  public.bando_codici_ateco,
  public.bando_regioni,
  public.ai_job_queue,
  public.ocr_job_queue,
  public.scraping_errori_definitivi,
  public.scraping_log,
  public.bando,
  public.fonte
RESTART IDENTITY CASCADE;

COMMIT;
```

Nota: se si vogliono mantenere le fonti gia note, escludere public.fonte dal truncate.

---

## Fase 2 - Riesecuzione pipeline completa

## 2.1 Ordine run
1. Discovery fonti
2. Scan bandi
3. Enqueue AI
4. Worker AI in modalita drain (fino a coda vuota)
5. Verifica KPI e casi campione

### 2.2 Comandi operativi
```powershell
.\.venv\Scripts\python.exe -m app.scrapers.run_fonte_discovery
.\.venv\Scripts\python.exe -m app.cli run
.\.venv\Scripts\python.exe -m app.ai.run_ai_enqueue --limit 1000
.\.venv\Scripts\python.exe -m app.ai.run_ai_worker --limit 100
```

Nota: al momento il worker AI ha default --limit 10 se non specificato.

---

## Registro problemi e soluzioni

## P1 - Worker AI processa solo primi 10 job senza limite esplicito

### Evidenza
Avviando app.ai.run_ai_worker senza --limit vengono processati solo 10 job.

### Causa tecnica
In app/ai/run_ai_worker.py il default CLI e --limit 10 e in app/services/ai_pipeline_service.py process_queue usa limit=10.

### Soluzione implementativa
- Modificare run_ai_worker per supportare modalita drain-all esplicita.
- Opzione A: default --limit None e loop fino a coda vuota.
- Opzione B: nuovo flag --drain-all, mantenendo default limitato per sicurezza.
- Aggiungere output cumulativo finale (claimed/completed/failed/discarded).

### Criterio accettazione
Lanciando il worker senza limite esplicito in modalita drain, la coda queued arriva a 0.

### Query verifica
```sql
SELECT stato, COUNT(*)
FROM public.ai_job_queue
GROUP BY stato
ORDER BY stato;
```

---

## P2 - is_bando_confermato nullo o con falsi positivi (esempio: fse.regione.campania.it/avvisi)

### Evidenza
Molti record restano con is_bando_confermato = NULL oppure vengono classificati TRUE in pagine non realmente bando.

### Cause tecniche probabili
- Scanner HTML troppo permissivo su anchor contestuali.
- Heuristica keyword insufficiente su listing generici tipo avvisi.
- Classificazione AI senza soglia di confidenza esplicita lato applicazione.

### Soluzione implementativa
- Rafforzare _is_probable_bando_link in app/scrapers/fonte_level2.py:
  - scoring con penalita per URL/listing generici,
  - esclusione pattern pagina indice (es. /avvisi se privo di dettaglio),
  - richiesta segnali semantici aggiuntivi nel contesto.
- Aggiungere campo diagnostico in raw_data_obj (reason_accept/reason_reject).
- Introdurre fallback deterministico in app/services/classification_service.py:
  - se segnali insufficienti, impostare is_bando_confermato=False,
  - inviare ad AI solo i casi borderline.
- Estendere gate di qualita con regola anti-falso-positivo.

### Criterio accettazione
- Riduzione significativa dei FALSE POSITIVE sui siti noti problematici.
- Percentuale NULL su is_bando_confermato sotto soglia target.

### Query verifica
```sql
SELECT
  COUNT(*) AS totale,
  COUNT(*) FILTER (WHERE is_bando_confermato IS NULL) AS null_is_bando,
  ROUND(100.0 * COUNT(*) FILTER (WHERE is_bando_confermato IS NULL) / NULLIF(COUNT(*), 0), 2) AS pct_null
FROM public.bando;
```

---

## P3 - Qualita dati bando ID 1999 (caso "migliore" ma incompleto)
URL: https://fesr.regione.emilia-romagna.it/opportunita/opportunita-di-finanziamento/2026/sostegno-alla-produzione-di-opere-cinematografiche-e-audiovisive-anno-2026

### Anomalie osservate
- Titolo DB: "Vai al bando" invece del titolo reale pagina.
- Descrizione DB: NULL nonostante testo completo disponibile.
- stato_bando: programmato ma bando storicamente aperto/chiuso.
- data_pubblicazione/data_apertura/data_scadenza: NULL.
- importo_numerico: anno invece di importo.
- is_bando_confermato: NULL.
- bando_beneficiari: non valorizzata.
- bando_codici_ateco: valorizzata ma errata.
- bando_settori: non valorizzata.

### Cause tecniche probabili
- Il parser usa candidate_title anchor-level e non sempre promuove il titolo reale pagina.
- Descrizione presa da parent_context corto, non dal contenuto pagina dettaglio.
- Stato fallback a programmato quando pattern stato/date non viene letto nel corpus.
- Importo parser cattura numeri ambigui (es. anno 2026) in assenza di ancora semantica forte.
- Classificazione relazionale troppo permissiva su similarita testuale.

### Soluzione implementativa
- Parser dettaglio pagina (nuovo step in pipeline prima di upsert):
  - fetch della pagina bando,
  - estrazione H1/H2 e blocco descrizione principale,
  - estrazione date da blocchi etichettati.
- Hardening parse importo in app/parsers/bando_parser.py:
  - escludere numeri 4 cifre isolati se compatibili con anno,
  - accettare importo solo con token monetario o label economica vicina,
  - test esplicito anti-caso "2026 come importo".
- Inferenza stato_bando basata su date:
  - aperto se oggi tra data_apertura e data_scadenza,
  - chiuso se oggi > data_scadenza,
  - programmato se oggi < data_apertura.
- Classificazione relazioni con soglie per dominio:
  - beneficiari e settori da pattern lessicali dedicati,
  - ATECO solo con match codice esplicito o similarita alta + contesto coerente.
- Se classificazione dubbia: lasciare vuoto e inviare a coda revisione, non valorizzare a caso.

### Criteri accettazione
- Titolo non piu "Vai al bando" quando e disponibile H1 reale.
- Descrizione valorizzata con testo utile.
- Date valorizzate quando presenti in pagina.
- importo_numerico non valorizzato con anno isolato.
- Relazioni beneficiari/settori compilate nei casi con evidenza testuale.
- Riduzione errori ATECO su campione validato.

### Query verifica dedicate (ID 1999)
```sql
SELECT
  id,
  titolo,
  descrizione,
  stato_bando,
  data_pubblicazione,
  data_apertura,
  data_scadenza,
  importo,
  importo_numerico,
  is_bando_confermato
FROM public.bando
WHERE id = 1999;
```

```sql
SELECT bb.*
FROM public.bando_beneficiari bb
WHERE bb.bando_id = 1999;
```

```sql
SELECT ba.*
FROM public.bando_codici_ateco ba
WHERE ba.bando_id = 1999;
```

```sql
SELECT bs.*
FROM public.bando_settori bs
WHERE bs.bando_id = 1999;
```

---

## P4 - Bando con PDF ricco ma DB quasi vuoto (caso LazioEuropa)
URL: https://www.lazioeuropa.it/bandi/avviso-integrativo-preciseu

### Evidenza
Record quasi privo di dati (titolo, descrizione, importo, date) nonostante PDF allegato ricco.

### Cause tecniche probabili
- Pipeline attuale privilegia testo pagina e non sempre segue/parse allegati PDF di dettaglio.
- OCR attivato solo in casi specifici, non sempre su allegato principale.
- Mancata fusione strutturata tra dati pagina e dati documento.

### Soluzione implementativa
- Introduzione "document enrichment stage":
  - rilevare allegati PDF pertinenti nella pagina dettaglio,
  - estrarre testo da PDF (parser + OCR fallback),
  - fondere i campi con priorita: pagina dettaglio > PDF > contesto listing.
- Aggiungere confidence per campo estratto (titolo/date/importo).
- Aggiornare quality gate per imporre extraction source tracciata (source_of_truth per campo).

### Criteri accettazione
- Su URL campione LazioEuropa sono valorizzati almeno titolo, descrizione e almeno una data significativa.
- Se importo non estratto con confidenza, resta NULL ma con motivo tracciato.

### Query verifica
```sql
SELECT
  id,
  titolo,
  descrizione,
  data_pubblicazione,
  data_apertura,
  data_scadenza,
  importo,
  importo_numerico,
  raw_data,
  data_extra
FROM public.bando
WHERE link_bando ILIKE '%lazioeuropa.it/bandi/avviso-integrativo-preciseu%';
```

---

## Piano test associato (obbligatorio)

## T1 - Worker drain all
- Preparare >10 job queued.
- Avvio worker senza limite esplicito in modalita drain.
- Assert: queued=0 o solo failed motivati.

## T2 - Anti-falsi-positivi su listing avvisi
- Dataset con URL listing e URL dettaglio.
- Assert: listing generico non confermato come bando, dettaglio confermato.

## T3 - Parsing robusto titolo/descrizione/date/importo
- Fixture con titolo anchor "Vai al bando" ma H1 reale in pagina.
- Fixture con date etichettate.
- Fixture con anno vicino a importo.
- Assert: titolo reale, date corrette, importo non uguale ad anno.

## T4 - Relazioni dominio
- Fixture testo con beneficiari espliciti (Micro-imprese e PMI).
- Assert: bando_beneficiari valorizzata.
- Fixture ATECO ambiguo.
- Assert: nessun ATECO assegnato se confidenza bassa.

## T5 - PDF enrichment
- Fixture pagina con PDF allegato ricco.
- Assert: campi minimi valorizzati da PDF/OCR.

---

## KPI target post-remediation
- pct_with_titolo >= 98%
- pct_with_descrizione >= 85%
- pct_with_any_date >= 75%
- pct_with_importo_numerico plausibile >= 60%
- pct_is_bando_null <= 5%
- false_positive_rate_is_bando <= 5% su campione validato
- pct_bandi_con_almeno_una_relazione (beneficiari/settori/ateco) >= 70%

Query KPI suggerita:
```sql
SELECT
  COUNT(*) AS totale,
  ROUND(100.0 * COUNT(*) FILTER (WHERE titolo IS NOT NULL AND btrim(titolo) <> '') / NULLIF(COUNT(*),0), 2) AS pct_with_titolo,
  ROUND(100.0 * COUNT(*) FILTER (WHERE descrizione IS NOT NULL AND btrim(descrizione) <> '') / NULLIF(COUNT(*),0), 2) AS pct_with_descrizione,
  ROUND(100.0 * COUNT(*) FILTER (
    WHERE data_pubblicazione IS NOT NULL OR data_apertura IS NOT NULL OR data_scadenza IS NOT NULL
  ) / NULLIF(COUNT(*),0), 2) AS pct_with_any_date,
  ROUND(100.0 * COUNT(*) FILTER (WHERE importo_numerico IS NOT NULL AND importo_numerico > 1000) / NULLIF(COUNT(*),0), 2) AS pct_with_importo_plausibile,
  ROUND(100.0 * COUNT(*) FILTER (WHERE is_bando_confermato IS NULL) / NULLIF(COUNT(*),0), 2) AS pct_is_bando_null
FROM public.bando;
```

---

## Backlog implementativo (ordine consigliato)
1. Worker AI drain mode (P1)
2. Hardening conferma bando e anti-falsi-positivi (P2)
3. Parser dettaglio pagina + fix titolo/descrizione/date/importo (P3)
4. PDF enrichment + OCR fallback strutturato (P4)
5. Rafforzamento test automatici e report KPI

## Definizione di Done
Un problema e chiuso solo se tutte le condizioni sono vere:
- codice implementato
- test automatico aggiunto/aggiornato
- query verifica passata su run post-truncate
- KPI migliorato rispetto baseline
- evidenza documentata in report esecuzione
