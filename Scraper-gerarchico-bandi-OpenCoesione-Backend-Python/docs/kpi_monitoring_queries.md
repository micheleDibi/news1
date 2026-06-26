# Query di Monitoraggio KPI - Documentazione

## Utilizzo
Queste query SQL consentono di monitorare lo stato della pipeline post-remediation, verificare il progresso del worker AI e controllare se i KPI sono stati raggiunti.

---

## Query 1: KPI Post-Remediation (Complessivi)

### Scopo
Misurare la qualità complessiva dei dati `bando` estratti e processati. Fornisce 5 metriche percentuali chiave.
Esclude i record flaggati come "sospetto" (pagine di lista non elaborate, con tutti i campi critici NULL).

### SQL
```sql
SELECT
  COUNT(*) FILTER (WHERE stato_bando != 'sospetto') AS totale_validi,
  COUNT(*) FILTER (WHERE stato_bando = 'sospetto') AS totale_sospetti,
  ROUND(100.0 * COUNT(*) FILTER (WHERE titolo IS NOT NULL AND btrim(titolo) <> '' AND stato_bando != 'sospetto') / NULLIF(COUNT(*) FILTER (WHERE stato_bando != 'sospetto'),0), 2) AS pct_with_titolo,
  ROUND(100.0 * COUNT(*) FILTER (WHERE descrizione IS NOT NULL AND btrim(descrizione) <> '' AND stato_bando != 'sospetto') / NULLIF(COUNT(*) FILTER (WHERE stato_bando != 'sospetto'),0), 2) AS pct_with_descrizione,
  ROUND(100.0 * COUNT(*) FILTER (
    WHERE (data_pubblicazione IS NOT NULL OR data_apertura IS NOT NULL OR data_scadenza IS NOT NULL) AND stato_bando != 'sospetto'
  ) / NULLIF(COUNT(*) FILTER (WHERE stato_bando != 'sospetto'),0), 2) AS pct_with_any_date,
  ROUND(100.0 * COUNT(*) FILTER (WHERE importo_numerico IS NOT NULL AND importo_numerico > 1000 AND stato_bando != 'sospetto') / NULLIF(COUNT(*) FILTER (WHERE stato_bando != 'sospetto'),0), 2) AS pct_with_importo_plausibile,
  ROUND(100.0 * COUNT(*) FILTER (WHERE is_bando_confermato IS NULL AND stato_bando != 'sospetto') / NULLIF(COUNT(*) FILTER (WHERE stato_bando != 'sospetto'),0), 2) AS pct_is_bando_null
FROM public.bando;
```

Nota soglia importo:
- la soglia `1000` usata in questa query e nella Query 4 e' il default operativo corrente
- a livello parser e' configurabile via variabile ambiente `IMPORTO_PLAUSIBILE_THRESHOLD`

Nota record sospetto:
- i record con `stato_bando = 'sospetto'` indicano candidati estratti da pagine di elenco/lista, non da pagine di dettaglio
- tutti e quattro i campi critici sono NULL: data_pubblicazione, data_apertura, data_scadenza, importo_numerico
- vengono esclusi dal calcolo KPI per non inquinare le percentuali
- sono disponibili per revisione manuale tramite `WHERE stato_bando = 'sospetto'`

### Colonne restituite
| Colonna | Descrizione | Dato Atteso |
|---------|-------------|-------------|
| `totale_validi` | Numero bandi escludendo sospetti | 753 - X sospetti |
| `totale_sospetti` | Numero bandi flaggati come sospetto | 0 o piccolo numero |
| `pct_with_titolo` | % bandi con titolo non vuoto (non sospetti) | >= 98% |
| `pct_with_descrizione` | % bandi con descrizione valorizzata (non sospetti) | >= 85% |
| `pct_with_any_date` | % bandi con almeno una data (non sospetti) | >= 75% |
| `pct_with_importo_plausibile` | % bandi con importo_numerico >= 1000 (non sospetti) | >= 60% |
| `pct_is_bando_null` | % bandi con is_bando_confermato ancora NULL (non sospetti) | <= 5% |

### Criteri di Accettazione (Target KPI)
```
pct_with_titolo >= 98%
pct_with_descrizione >= 85%
pct_with_any_date >= 75%
pct_with_importo_plausibile >= 60%
pct_is_bando_null <= 5%
(su universo: bandi non sospetti)
```

### Interpretazione
- Valori **rossi** (sotto target): indicano aree di dati carenti che richiedono fix al parser.
- Valori **verdi** (sopra target): indicano che l'area è a livello di qualità accettabile.
- `totale_sospetti > 0`: indica che alcuni candidati vengono da pagine di lista e non sono ancora stati tracciati a dettaglio.


---

## Query 4: Diagnostica Importo Plausibile

### Scopo
Capire dove si perde `pct_with_importo_plausibile`, separando i bandi senza importo, con importo non plausibile e con importo già valido.
Esclude i record flaggati come "sospetto".

Nota: la soglia `1000` in questa query e' il default corrente; puo' essere adattata in base alla policy KPI del team.

### SQL
```sql
SELECT
  COUNT(*) FILTER (WHERE stato_bando != 'sospetto') AS totale_validi,
  COUNT(*) FILTER (WHERE stato_bando = 'sospetto') AS totale_sospetti,
  
  COUNT(*) FILTER (WHERE importo_numerico IS NULL AND stato_bando != 'sospetto') AS importo_null,
  ROUND(100.0 * COUNT(*) FILTER (WHERE importo_numerico IS NULL AND stato_bando != 'sospetto') / NULLIF(COUNT(*) FILTER (WHERE stato_bando != 'sospetto'), 0), 2) AS pct_importo_null,

  COUNT(*) FILTER (WHERE importo_numerico IS NOT NULL AND importo_numerico <= 1000 AND stato_bando != 'sospetto') AS importo_non_plausibile_le_1000,
  ROUND(100.0 * COUNT(*) FILTER (WHERE importo_numerico IS NOT NULL AND importo_numerico <= 1000 AND stato_bando != 'sospetto') / NULLIF(COUNT(*) FILTER (WHERE stato_bando != 'sospetto'), 0), 2) AS pct_importo_non_plausibile_le_1000,

  COUNT(*) FILTER (WHERE importo_numerico IS NOT NULL AND importo_numerico > 1000 AND stato_bando != 'sospetto') AS importo_plausibile_gt_1000,
  ROUND(100.0 * COUNT(*) FILTER (WHERE importo_numerico IS NOT NULL AND importo_numerico > 1000 AND stato_bando != 'sospetto') / NULLIF(COUNT(*) FILTER (WHERE stato_bando != 'sospetto'), 0), 2) AS pct_with_importo_plausibile,

  COUNT(*) FILTER (WHERE importo IS NOT NULL AND btrim(importo) <> '' AND stato_bando != 'sospetto') AS importo_testuale_presente,
  ROUND(100.0 * COUNT(*) FILTER (WHERE importo IS NOT NULL AND btrim(importo) <> '' AND stato_bando != 'sospetto') / NULLIF(COUNT(*) FILTER (WHERE stato_bando != 'sospetto'), 0), 2) AS pct_importo_testuale_presente
FROM public.bando;
```

### Come interpretarla
| Colonna | Significato |
|---------|-------------|
| `totale_validi` | bandi non flaggati sospetto |
| `totale_sospetti` | bandi con stato_bando = 'sospetto' |
| `importo_null` | record (non sospetto) senza importo numerico valorizzato |
| `importo_non_plausibile_le_1000` | importi presenti ma sotto soglia KPI (non sospetto) |
| `importo_plausibile_gt_1000` | importi che fanno crescere il KPI (non sospetto) |
| `importo_testuale_presente` | importo testuale presente ma non necessariamente convertito bene (non sospetto) |

### Lettura pratica
- Se `importo_null` e' alto, il problema e' di estrazione / fallback.
- Se `importo_non_plausibile_le_1000` e' alto, il problema e' di normalizzazione o di soglia.
- Se `importo_testuale_presente` e' alto ma `importo_plausibile_gt_1000` resta basso, conviene migliorare parser e backfill.
- Se `totale_sospetti` e' alto, significa che molti candidati provengono da pagine di lista e non sono stati tracciati a dettaglio.

---

## Query 5: Monitoraggio Record Sospetto

### Scopo
Visualizzare i bandi flaggati come "sospetto" (pagine di lista con tutti i campi critici NULL).
Permette di identificare quali candidati sono stati estratti da pagine di elenco e necessitano di follow-up.

### SQL - Conteggio e Distribuzione
```sql
SELECT
  COUNT(*) AS totale_sospetti,
  COUNT(*) FILTER (WHERE fonte_id IS NOT NULL) AS sospetti_con_fonte_id,
  COUNT(DISTINCT fonte_id) AS num_fonti_con_sospetti,
  COUNT(*) FILTER (WHERE is_bando_confermato IS NULL) AS sospetti_non_confermati
FROM public.bando
WHERE stato_bando = 'sospetto';
```

### SQL - Dettagli Campione (primissimi 50)
```sql
SELECT
  id,
  fonte_id,
  titolo,
  link_bando,
  stato_bando,
  is_bando_confermato,
  primo_scraping_at
FROM public.bando
WHERE stato_bando = 'sospetto'
ORDER BY id ASC
LIMIT 50;
```

### Colonne Restituite (Conteggio)
| Colonna | Descrizione |
|---------|-------------|
| `totale_sospetti` | Numero totale di bandi flaggati sospetto |
| `sospetti_con_fonte_id` | Sospetti che hanno fonte_id tracciata |
| `num_fonti_con_sospetti` | Numero di fonti diverse che hanno generato sospetti |
| `sospetti_non_confermati` | Sospetti che non sono ancora stati confermati/rifiutati dall'AI |

### Interpretazione
- **`totale_sospetti = 0`**: ideale, nessun candidato da pagina lista.
- **`totale_sospetti > 0` ma piccolo**: normale, significa che alcuni candidati non hanno dettaglio disponibile. OK da escludere.
- **`totale_sospetti` molto alto**: indica che molti candidati provengono da pagine di lista; considera di estendere la logica del fetcher per scarica un livello più in basso.
- **Per fonte specifica problematica**: eseguire `WHERE fonte_id = X AND stato_bando = 'sospetto'` per concentrarsi.

### Azioni Consigliate
- Se la fonte X ha molti sospetti, rivedi la logica di scan per fonte X o la fonte stessa.
- Se complessivamente sospetti < 2% dell'universo, ignora.
- Se sospetti > 5%, considera di migliorare la fetch strategy.

---

## Query 2: Stato Coda AI Jobs

### Scopo
Monitorare il progresso del worker AI in tempo reale. Verificare quanti job sono ancora in coda e in quale stato si trovano.

### SQL
```sql
SELECT stato, COUNT(*) as count
FROM public.ai_job_queue
GROUP BY stato
ORDER BY stato;
```

### Colonne restituite
| Colonna | Descrizione | Valori Possibili |
|---------|-------------|------------------|
| `stato` | Stato di elaborazione del job | `queued`, `claimed`, `completed`, `failed`, `backoff` |
| `count` | Numero di job in quello stato | numero intero >= 0 |

### Interpretazione

| Stato | Significato | Azione |
|-------|-----------|--------|
| `queued` | Job in attesa di essere elaborato | Questi verranno processati dal worker. Se > 0, worker è ancora in esecuzione |
| `claimed` | Job preso dal worker ma non ancora completato | Dovrebbe essere piccolo, indica job in elaborazione |
| `completed` | Job elaborato con successo | Idealmente il valore più alto |
| `failed` | Job fallito dopo tutti i retry | Investigare errore specifico |
| `backoff` | Job in attesa di retry dopo fallimento temporaneo | Normale durante rate-limiting |

### Target Finale (Fase 2 completata)
```
queued = 0          (nessun job in attesa)
claimed = 0         (nessun job in elaborazione)
completed = 753     (tutti i bandi processati)
failed = 0 o molto piccolo
backoff = 0
```

### Quando eseguire
- **Inizio**: verifica quanti job sono in coda
- **Durante**: monitora il progresso (queued dovrebbe diminuire)
- **Fine**: verifica che `queued = 0` e `completed` sia massimo

---

## Query 3: KPI Baseline (Fase 0) - Per Confronto Storico

### Scopo
Registrare lo stato dei dati **prima** di qualsiasi modifica parser, per misurare il delta di miglioramento dopo P3.

### SQL
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

### Colonne restituite
| Colonna | Descrizione | Dato Atteso |
|---------|-------------|-------------|
| `totale` | Numero totale di bandi | 753 |
| `with_titolo` | Conteggio bandi con titolo non vuoto | numero assoluto |
| `with_descrizione` | Conteggio bandi con descrizione | numero assoluto |
| `with_data_pubblicazione` | Bandi con data_pubblicazione | numero assoluto |
| `with_data_apertura` | Bandi con data_apertura | numero assoluto |
| `with_data_scadenza` | Bandi con data_scadenza | numero assoluto |
| `with_importo` | Bandi con importo_numerico | numero assoluto |
| `with_is_bando` | Bandi con is_bando_confermato non NULL | numero assoluto |

### Utilizzo
- **Fase 0 (Baseline)**: eseguire per registrare lo stato pre-remediation
- **Post-P3**: rieseguire e confrontare i numeri assoluti per misurare il miglioramento
- **Delta**: calcolare quanti bandi nuovi hanno ricevuto descrizione/date/importo

### Esempio di Confronto
```
Baseline (Fase 0):
  with_descrizione = 194/753

Post-P3:
  with_descrizione = 644/753 (aspettato)

Delta: +450 bandi con descrizione aggiunta
Miglioramento: da 25.76% a 85.52%
```

---

## Flusso Operativo Consigliato

### 1. **Inizio Fase 2 (post-discovery, scan, enqueue)**
```sql
-- Eseguire Query 2 per verificare quanti job sono in coda
SELECT stato, COUNT(*) FROM public.ai_job_queue GROUP BY stato;
```
Aspettato: `queued = 753`

### 2. **Durante Worker Drain**
```sql
-- Ripetere Query 2 periodicamente per monitorare progresso
SELECT stato, COUNT(*) FROM public.ai_job_queue GROUP BY stato;
```
Aspettato: `queued` diminuisce nel tempo

### 3. **Fine Worker Drain**
```sql
-- Verificare che queued = 0
SELECT stato, COUNT(*) FROM public.ai_job_queue GROUP BY stato;
```
Aspettato: `queued = 0, completed = 753`

### 4. **Verificare KPI Finali**
```sql
-- Query 1: controllare le percentuali
SELECT ... pct_with_titolo, pct_with_descrizione, pct_with_any_date, pct_with_importo_plausibile, pct_is_bando_null FROM public.bando;
```
Confrontare con target di Phase 2.

### 5. **Dopo Implementazione P3 (Parser Fix)**
```sql
-- Rieseguire Query 1 dopo parser improvements
SELECT ... pct_with_titolo, pct_with_descrizione, ...;
```
Verificare che le percentuali salgono verso il target.

---

## Note su Frequenza di Esecuzione

| Query | Frequenza | Quando |
|-------|-----------|--------|
| Query 2 (Stato Coda) | Ogni 5-10 min durante drain | Durante esecuzione worker |
| Query 1 (KPI Finale) | Al termine di ogni fase | Dopo worker drain, dopo P3, dopo P4 |
| Query 3 (Baseline) | Una volta sola | Inizio Fase 0, poi eventualmente per confronto |

---

## Troubleshooting

### Se `queued` non scende a 0
- Verificare se il worker è ancora in esecuzione
- Controllare `failed` e `backoff`: se alti, c'è un problema sistematico
- Aumentare `--call-delay` se vedi retry rate-limit

### Se `pct_with_descrizione` rimane bassa dopo worker
- Problema non è AI classification, ma **parser extraction** (P3)
- Il parser non sta estraendo la descrizione dalla pagina HTML
- Investigare `app/parsers/bando_parser.py`

### Se `pct_with_importo_plausibile` rimane bassa
- Parser importo cattura valori spurii (es. anno 2026)
- Implementare filtri anti-anno in `bando_parser.py`

