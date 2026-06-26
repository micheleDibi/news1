# Piano attuazione P1-P2-P3-P4

Aggiornato al: 2026-05-15

## Decisione operativa
- Si avvia immediatamente l'esecuzione di P1, P2 e P3.
- P4 non e urgente e viene rinviata a una futura v2 del backend.
- Obiettivo: ridurre rapidamente i record in stato sospetto con interventi mirati sulle fonti piu impattanti.

## Perimetro
In scope:
- P1 parser dedicato cluster Regione Piemonte
- P2 parser famiglia Interreg (con riserve tecniche esplicite)
- P3 fix mirati su fonti con incidenza sospetti molto alta

Fuori scope (fase attuale):
- P4 logica generica di approfondimento link figlio su coda lunga

## P1 - Parser dedicato cluster Regione Piemonte
### Cosa verra fatto
- Analisi comparativa delle 4 fonti Regione Piemonte per individuare struttura comune lista -> dettaglio.
- Implementazione parser dedicato per estrazione robusta di:
  - titolo reale pagina
  - descrizione utile
  - date principali (pubblicazione/apertura/scadenza quando presenti)
  - importo con filtri anti-rumore
- Hardening regole di fallback per evitare valori fuorvianti.
- Test automatici con fixture rappresentative delle 4 fonti.

### Risultato atteso
- Riduzione rilevante dei sospetti sul cluster Piemonte.
- Incremento KPI su titolo, descrizione, date e importo plausibile.

## P2 - Parser famiglia Interreg
### Cosa verra fatto
- Definizione di un parser base comune per i siti Interreg con logica a famiglia.
- Introduzione di adapter per differenze per-sito quando il template non e omogeneo.
- Rafforzamento della selezione link dettaglio e controlli anti-falso-positivo.
- Copertura test multi-fonte (casi positivi e negativi).

### Risultato atteso
- Riduzione consistente dei sospetti sul cluster Interreg.
- Comportamento piu stabile su fonti con struttura simile ma non identica.

### RISERVE P2 (da considerare vincolanti)
1. Eterogeneita reale dei template Interreg:
   - se i 5 siti condividono solo parte del markup, servira aumentare il numero di adapter specifici.
2. Qualita e stabilita dei link lista -> dettaglio:
   - presenza di pagine indice, preavvisi o redirect puo aumentare lavoro di hardening.
3. Disponibilita dei segnali nei dettagli:
   - alcuni siti potrebbero non esporre chiaramente date/importi nella pagina HTML.
4. Impatto sui test e regressione:
   - eventuali eccezioni per-sito possono aumentare il carico di test oltre il minimo previsto.

### Gestione operativa delle riserve P2
- Checkpoint tecnico intermedio dopo la prima implementazione del parser base.
- Conferma finale del piano operativo solo dopo evidenza su almeno 2 fonti Interreg rappresentative.
- In caso di deviazioni rilevanti: proposta di micro-split in sotto-task per mantenere controllo tempi/costi.

### Stato avanzamento P2 (checkpoint operativo)
Aggiornato al: 2026-05-19

Fonti checkpoint iniziali:
- `fonte_id=55` (interreg-marittimo)
- `fonte_id=62` (interreg-central)

Baseline iniziale osservata:
- `55`: `sospetti_pct = 100.00` (2/2)
- `62`: `sospetti_pct = 83.33` (5/6)

Intervento eseguito:
- introdotti filtri host-specific su pagine indice/risultati non-bando (calls index, risultati call, project-gateway, progetti finanziati).
- test di regressione scanner aggiornati e verdi.

Esito dopo hardening:
- `62`: migliorato fino a `sospetti_pct = 50.00` (1/2)
- `55`: miglioramento rilevato nelle run successive con riduzione dei candidati indice non pertinenti.

Diagnosi residuo P2:
- il residuo sospetto su `56` e' legato a pagina "Progetti finanziati" (non call attiva), quindi falso positivo strutturale lato selezione link.
- applicato filtro aggiuntivo host-specific su `www.interreg-italiasvizzera.eu` path `/wps/portal/site/interreg-italia-svizzera/progetti/progetti-finanziati`.

### Parser base famiglia Interreg — completato 2026-05-19

Interventi eseguiti su `bando_parser.py` e `page_detail_fetcher.py`:

1. **Mesi inglesi nelle date**: aggiunto `_MONTH_EN_TO_INT` e `_MONTH_NAME_TO_INT`; `_DATE_TOKEN_PATTERN` e `_parse_date` coprono ora "27 November 2025", "10 December 2024", "15 Sep 2025", ecc. Stesso aggiornamento in `_extract_page_dates` del fetcher.
2. **Importi "X million EUR"**: `_extract_page_importo` (fetcher) rileva "23 million Euros" → restituisce "23000000". `_extract_importo` (parser) aggiunge moltiplicatori `millions? EUR` e `billions? EUR` nel corpus.
3. **Etichette data inglesi**: `_extract_labeled_date` cerca ora anche "deadline", "closes", "closing", "submission", "opening", "opens", "start".
4. **Stato bando inglese**: `_extract_stato_bando` aggiunge "closed" → chiuso, "upcoming/forthcoming" → programmato, "is open" → aperto.
5. **Titoli generici inglesi**: `_GENERIC_TITLE_PATTERNS` aggiunge `calls? for proposals?`, `timeline of calls?`, `calls? for projects?`.

Test: `app/tests/test_p2_interreg_parser.py` — 26 test, tutti verdi.
Regressione: 96 test esistenti (milestone4, milestone5, unit_trasversale) — tutti verdi.

Prossimo step: re-run fonti Interreg e confronto KPI post-intervento.

Comandi operativi checkpoint P2 (da rieseguire dopo ogni hardening):

```powershell
python.exe -m app.cli run-fonte --fonte-id 62
python.exe -m app.cli run-fonte --fonte-id 55
python.exe -m app.cli run-fonte --fonte-id 56
```

### Run operativi P2 — 2026-05-19

| fonte_id | titolo           | tot | sospetti | sospetti_pct | importo_valido | almeno_una_data |
|----------|------------------|-----|----------|--------------|----------------|------------------|
| 62       | interreg-central |   1 |        0 |        0.00% |              1 |                1 |
| 55       | interreg-marittimo |  0 |       — |           — |             — |               — |
| 56       | interreg-it-ch   |   0 |       — |           — |             — |               — |

Note: 55 e 56 restituiscono 0 candidati perche al momento non ci sono call aperte; il filtro host-specific blocca correttamente le pagine indice/risultati.

KPI di controllo P2 (completo):

```sql
WITH params AS (
   SELECT unnest(ARRAY[62,55,56]) AS fonte_id
)
SELECT
   b.fonte_id,
   COUNT(*) AS tot_record,
   COUNT(*) FILTER (WHERE b.stato_bando = 'sospetto') AS sospetti,
   ROUND(100.0 * COUNT(*) FILTER (WHERE b.stato_bando = 'sospetto') / NULLIF(COUNT(*), 0), 2) AS sospetti_pct,
   COUNT(*) FILTER (
      WHERE b.stato_bando <> 'sospetto'
        AND b.titolo ~* '^(https?://|www\.)'
   ) AS titolo_url_raw,
   COUNT(*) FILTER (
      WHERE b.stato_bando <> 'sospetto'
        AND b.importo_numerico IS NOT NULL
   ) AS importo_valido,
   COUNT(*) FILTER (
      WHERE b.stato_bando <> 'sospetto'
        AND (
           b.data_pubblicazione IS NOT NULL
           OR b.data_apertura IS NOT NULL
           OR b.data_scadenza IS NOT NULL
        )
   ) AS almeno_una_data
FROM public.bando b
JOIN params p ON p.fonte_id = b.fonte_id
GROUP BY b.fonte_id
ORDER BY b.fonte_id;
```

## P3 - Fix mirati su fonti ad alta incidenza sospetti
### Cosa verra fatto
- Interventi puntuali sulle fonti con 100% (o quasi) di record sospetti.
- Correzione regole di parsing e navigazione specifiche per eliminare i blocchi strutturali.
- Validazione con query dedicate e regressione minima obbligatoria.

### Risultato atteso
- Riduzione del rischio strutturale su fonti oggi non funzionanti.
- Prevenzione degrado futuro quando i volumi di queste fonti aumenteranno.

### Analisi fonti target P3 — 2026-05-19

Query di identificazione (soglia >= 50% sospetti, >= 1 record):

```sql
SELECT
    b.fonte_id,
    f.titolo AS fonte_titolo,
    f.link   AS fonte_link,
    COUNT(*) AS tot_record,
    COUNT(*) FILTER (WHERE b.stato_bando = 'sospetto') AS sospetti,
    ROUND(100.0 * COUNT(*) FILTER (WHERE b.stato_bando = 'sospetto') / NULLIF(COUNT(*), 0), 2) AS sospetti_pct
FROM public.bando b
JOIN public.fonte f ON f.id = b.fonte_id
GROUP BY b.fonte_id, f.titolo, f.link
HAVING ROUND(100.0 * COUNT(*) FILTER (WHERE b.stato_bando = 'sospetto') / NULLIF(COUNT(*), 0), 2) >= 50
   AND COUNT(*) >= 1
ORDER BY sospetti_pct DESC, tot_record DESC;
```

Fonti target identificate:

| fonte_id | host                             | sospetti_pct | tot | root cause                                  |
|----------|----------------------------------|-------------|-----|----------------------------------------------|
| 3        | calabriaeuropa.regione.calabria.it | 100%       |   2 | sito richiede cookie/JS → redirect a "Contatti"; scanner accetta URL lista `/bandi` come candidato |
| 15       | www.lazioeuropa.it               | 50%         |   8 | `/bandi` (lista), `/psr-feasr/psr-bandi-e-graduatorie`, `/psr-feasr/psr-cronoprogramma-bandi` (archivio 2014-2022), `/pnrr-pnc/misure-pnrr-e-pnc-regione-lazio` (indice) accettati come candidati |
| 27       | www.regione.sardegna.it          | 50%         |   2 | `/atti-bandi-archivi` (indice generale) accettato come candidato |
| 28       | www.regione.sardegna.it          | 50%         |   2 | stessa causa di fonte 27 |

### Intervento P3 — completato 2026-05-19

Tipo intervento: aggiunta di host-specific deny paths in `_HOST_SPECIFIC_DENY_EXACT_PATHS` di `app/scrapers/fonte_level2.py`.

Deny rules aggiunte:
- `calabriaeuropa.regione.calabria.it`: `/bandi` — blocca URL lista/filtro che ridirezionano a "Contatti"
- `www.lazioeuropa.it`: `/bandi`, `/psr-feasr/psr-bandi-e-graduatorie`, `/psr-feasr/psr-cronoprogramma-bandi`, `/pnrr-pnc/misure-pnrr-e-pnc-regione-lazio` — blocca pagina lista e archivi programma 2014-2022 concluso
- `www.regione.sardegna.it`: `/atti-bandi-archivi` — blocca indice generale atti/bandi/archivi

Test: `app/tests/test_milestone4_scan.py` — aggiunta suite `test_p3_deny_rules` con 6 test, tutti verdi.

Comandi operativi checkpoint P3:

```powershell
python.exe -m app.cli run-fonte --fonte-id 3
python.exe -m app.cli run-fonte --fonte-id 15
python.exe -m app.cli run-fonte --fonte-id 27
python.exe -m app.cli run-fonte --fonte-id 28
```

KPI di controllo P3:

```sql
WITH params AS (
   SELECT unnest(ARRAY[3,15,27,28]) AS fonte_id
)
SELECT
   b.fonte_id,
   COUNT(*) AS tot_record,
   COUNT(*) FILTER (WHERE b.stato_bando = 'sospetto') AS sospetti,
   ROUND(100.0 * COUNT(*) FILTER (WHERE b.stato_bando = 'sospetto') / NULLIF(COUNT(*), 0), 2) AS sospetti_pct,
   COUNT(*) FILTER (
      WHERE b.stato_bando <> 'sospetto' AND b.importo_numerico IS NOT NULL
   ) AS importo_valido,
   COUNT(*) FILTER (
      WHERE b.stato_bando <> 'sospetto'
        AND (b.data_pubblicazione IS NOT NULL OR b.data_apertura IS NOT NULL OR b.data_scadenza IS NOT NULL)
   ) AS almeno_una_data
FROM public.bando b
JOIN params p ON p.fonte_id = b.fonte_id
GROUP BY b.fonte_id
ORDER BY b.fonte_id;
```

## P4 - Logica generica approfondimento link figlio
### Stato
- Rimandata a v2 del backend (non urgente nella fase attuale).

### Cosa verra fatto in v2
- Introduzione di logica generica per seguire link figlio solo sui casi residui.
- Abilitazione controllata tramite white-list fonti.
- Retry limitati e soglie minime di confidenza per ridurre falsi positivi.
- Tracciamento diagnostico per motivi di accettazione/scarto e audit del comportamento.

### Risultato atteso
- Copertura della coda lunga senza aumentare il rischio di classificazioni forzate.
- Miglioramento graduale KPI sui sospetti residui.

## Sequenza di esecuzione consigliata
1. Avvio P1
2. Avvio P2 con checkpoint tecnico intermedio
3. Esecuzione P3 in parallelo leggero o subito dopo P2-base
4. Ricalcolo KPI e report finale fase

## Criteri di accettazione fase P1-P2-P3
- Riduzione misurabile dei record in stato sospetto.
- Nessun peggioramento sui controlli anti-falso-positivo.
- Test automatici aggiornati e verdi sulle aree toccate.
- Evidenza SQL di confronto pre/post su distribuzione sospetti per fonte.

## SQL unico KPI P1 (dashboard operativa)
Obiettivo: verificare in un'unica query tutti i KPI P1 sul cluster Piemonte.

Copertura KPI:
- riduzione sospetti
- riduzione titoli URL grezzi
- riduzione titoli generici di indice
- incremento completezza titolo valido
- incremento completezza descrizione
- incremento completezza date (almeno una tra pubblicazione/apertura/scadenza)
- incremento completezza importo numerico

```sql
WITH params AS (
   -- Cluster Piemonte analizzato in P1 (ID dinamici dal DB corrente)
   SELECT id AS fonte_id
   FROM public.fonte
   WHERE lower(coalesce(link, '')) LIKE '%regione.piemonte.it%'
),
base AS (
   SELECT
      b.id,
      b.fonte_id,
      COALESCE(b.titolo, '') AS titolo,
      COALESCE(b.descrizione, '') AS descrizione,
      b.stato_bando,
      b.data_pubblicazione,
      b.data_apertura,
      b.data_scadenza,
      b.importo_numerico
   FROM public.bando b
   JOIN params p ON p.fonte_id = b.fonte_id
),
kpi_per_fonte AS (
   SELECT
      fonte_id,
      COUNT(*) AS tot_record,
      COUNT(*) FILTER (WHERE stato_bando <> 'sospetto') AS tot_record_non_sospetti,

      COUNT(*) FILTER (WHERE stato_bando = 'sospetto') AS sospetti,
      ROUND(100.0 * COUNT(*) FILTER (WHERE stato_bando = 'sospetto') / NULLIF(COUNT(*), 0), 2) AS sospetti_pct,

      COUNT(*) FILTER (
         WHERE stato_bando <> 'sospetto'
           AND titolo ~* '^(https?://|www\.)'
      ) AS titolo_url_raw,
      ROUND(
         100.0 * COUNT(*) FILTER (
            WHERE stato_bando <> 'sospetto'
              AND titolo ~* '^(https?://|www\.)'
         ) / NULLIF(COUNT(*) FILTER (WHERE stato_bando <> 'sospetto'), 0),
         2
      ) AS titolo_url_raw_pct,

      COUNT(*) FILTER (
         WHERE stato_bando <> 'sospetto'
           AND lower(trim(titolo)) ~ '^(bandi|bandi e finanziamenti|bandi e opportunita|bandi e opportunità|avvisi|avvisi e bandi)$'
      ) AS titolo_generico,
      ROUND(
         100.0 * COUNT(*) FILTER (
            WHERE stato_bando <> 'sospetto'
              AND lower(trim(titolo)) ~ '^(bandi|bandi e finanziamenti|bandi e opportunita|bandi e opportunità|avvisi|avvisi e bandi)$'
         ) / NULLIF(COUNT(*) FILTER (WHERE stato_bando <> 'sospetto'), 0),
         2
      ) AS titolo_generico_pct,

      COUNT(*) FILTER (
         WHERE stato_bando <> 'sospetto'
            AND titolo <> ''
            AND titolo !~* '^(https?://|www\.)'
            AND lower(trim(titolo)) !~ '^(bandi|bandi e finanziamenti|bandi e opportunita|bandi e opportunità|avvisi|avvisi e bandi)$'
      ) AS titolo_valido,
      ROUND(
         100.0 * COUNT(*) FILTER (
            WHERE stato_bando <> 'sospetto'
               AND titolo <> ''
               AND titolo !~* '^(https?://|www\.)'
               AND lower(trim(titolo)) !~ '^(bandi|bandi e finanziamenti|bandi e opportunita|bandi e opportunità|avvisi|avvisi e bandi)$'
         ) / NULLIF(COUNT(*) FILTER (WHERE stato_bando <> 'sospetto'), 0),
         2
      ) AS titolo_valido_pct,

      COUNT(*) FILTER (WHERE stato_bando <> 'sospetto' AND descrizione <> '') AS descrizione_valida,
      ROUND(
         100.0 * COUNT(*) FILTER (WHERE stato_bando <> 'sospetto' AND descrizione <> '')
         / NULLIF(COUNT(*) FILTER (WHERE stato_bando <> 'sospetto'), 0),
         2
      ) AS descrizione_valida_pct,

      COUNT(*) FILTER (
         WHERE stato_bando <> 'sospetto'
             AND (
                data_pubblicazione IS NOT NULL
                OR data_apertura IS NOT NULL
                OR data_scadenza IS NOT NULL
             )
      ) AS almeno_una_data,
      ROUND(
         100.0 * COUNT(*) FILTER (
            WHERE stato_bando <> 'sospetto'
                AND (
                   data_pubblicazione IS NOT NULL
                   OR data_apertura IS NOT NULL
                   OR data_scadenza IS NOT NULL
                )
         ) / NULLIF(COUNT(*) FILTER (WHERE stato_bando <> 'sospetto'), 0),
         2
      ) AS almeno_una_data_pct,

      COUNT(*) FILTER (WHERE stato_bando <> 'sospetto' AND importo_numerico IS NOT NULL) AS importo_valido,
      ROUND(
         100.0 * COUNT(*) FILTER (WHERE stato_bando <> 'sospetto' AND importo_numerico IS NOT NULL)
         / NULLIF(COUNT(*) FILTER (WHERE stato_bando <> 'sospetto'), 0),
         2
      ) AS importo_valido_pct
   FROM base
   GROUP BY fonte_id
),
kpi_totale AS (
   SELECT
      0 AS fonte_id,
      COUNT(*) AS tot_record,
      COUNT(*) FILTER (WHERE stato_bando <> 'sospetto') AS tot_record_non_sospetti,

      COUNT(*) FILTER (WHERE stato_bando = 'sospetto') AS sospetti,
      ROUND(100.0 * COUNT(*) FILTER (WHERE stato_bando = 'sospetto') / NULLIF(COUNT(*), 0), 2) AS sospetti_pct,

      COUNT(*) FILTER (
         WHERE stato_bando <> 'sospetto'
           AND titolo ~* '^(https?://|www\.)'
      ) AS titolo_url_raw,
      ROUND(
         100.0 * COUNT(*) FILTER (
            WHERE stato_bando <> 'sospetto'
              AND titolo ~* '^(https?://|www\.)'
         ) / NULLIF(COUNT(*) FILTER (WHERE stato_bando <> 'sospetto'), 0),
         2
      ) AS titolo_url_raw_pct,

      COUNT(*) FILTER (
         WHERE stato_bando <> 'sospetto'
           AND lower(trim(titolo)) ~ '^(bandi|bandi e finanziamenti|bandi e opportunita|bandi e opportunità|avvisi|avvisi e bandi)$'
      ) AS titolo_generico,
      ROUND(
         100.0 * COUNT(*) FILTER (
            WHERE stato_bando <> 'sospetto'
              AND lower(trim(titolo)) ~ '^(bandi|bandi e finanziamenti|bandi e opportunita|bandi e opportunità|avvisi|avvisi e bandi)$'
         ) / NULLIF(COUNT(*) FILTER (WHERE stato_bando <> 'sospetto'), 0),
         2
      ) AS titolo_generico_pct,

      COUNT(*) FILTER (
         WHERE stato_bando <> 'sospetto'
            AND titolo <> ''
            AND titolo !~* '^(https?://|www\.)'
            AND lower(trim(titolo)) !~ '^(bandi|bandi e finanziamenti|bandi e opportunita|bandi e opportunità|avvisi|avvisi e bandi)$'
      ) AS titolo_valido,
      ROUND(
         100.0 * COUNT(*) FILTER (
            WHERE stato_bando <> 'sospetto'
               AND titolo <> ''
               AND titolo !~* '^(https?://|www\.)'
               AND lower(trim(titolo)) !~ '^(bandi|bandi e finanziamenti|bandi e opportunita|bandi e opportunità|avvisi|avvisi e bandi)$'
         ) / NULLIF(COUNT(*) FILTER (WHERE stato_bando <> 'sospetto'), 0),
         2
      ) AS titolo_valido_pct,

      COUNT(*) FILTER (WHERE stato_bando <> 'sospetto' AND descrizione <> '') AS descrizione_valida,
      ROUND(
         100.0 * COUNT(*) FILTER (WHERE stato_bando <> 'sospetto' AND descrizione <> '')
         / NULLIF(COUNT(*) FILTER (WHERE stato_bando <> 'sospetto'), 0),
         2
      ) AS descrizione_valida_pct,

      COUNT(*) FILTER (
         WHERE stato_bando <> 'sospetto'
           AND (
             data_pubblicazione IS NOT NULL
             OR data_apertura IS NOT NULL
             OR data_scadenza IS NOT NULL
           )
      ) AS almeno_una_data,
      ROUND(
         100.0 * COUNT(*) FILTER (
            WHERE stato_bando <> 'sospetto'
                AND (
                   data_pubblicazione IS NOT NULL
                   OR data_apertura IS NOT NULL
                   OR data_scadenza IS NOT NULL
                )
         ) / NULLIF(COUNT(*) FILTER (WHERE stato_bando <> 'sospetto'), 0),
         2
      ) AS almeno_una_data_pct,

      COUNT(*) FILTER (WHERE stato_bando <> 'sospetto' AND importo_numerico IS NOT NULL) AS importo_valido,
      ROUND(
         100.0 * COUNT(*) FILTER (WHERE stato_bando <> 'sospetto' AND importo_numerico IS NOT NULL)
         / NULLIF(COUNT(*) FILTER (WHERE stato_bando <> 'sospetto'), 0),
         2
      ) AS importo_valido_pct
   FROM base
)
SELECT *
FROM kpi_per_fonte
UNION ALL
SELECT *
FROM kpi_totale
ORDER BY fonte_id;
```

Note operative:
- `fonte_id = 0` rappresenta il totale cluster P1.
- Le percentuali KPI (titolo/descrizione/date/importo) sono calcolate sui soli record `stato_bando <> 'sospetto'`.
- Per confronto pre/post, eseguire la stessa query prima e dopo il run parser e confrontare i valori percentuali.

### Limiti strutturali KPI P1 (non fixabili solo via parser)
- Una quota residua di `sospetti` puo restare stabile anche con parser corretto, quando la pagina sorgente non espone proprio i campi critici.
- I casi tipici sono le pagine di `pre-informazione` o preavviso: spesso non pubblicano ancora date operative e importi finali.
- In questi casi i KPI `almeno_una_data_pct` e `importo_valido_pct` non possono crescere oltre un certo limite senza una variazione del contenuto alla fonte.
- Il parser non deve inventare valori mancanti: per policy qualita, in assenza di evidenza il record resta `sospetto`.
- I KPI migliorabili con hardening parser/scanner sono soprattutto: `titolo_url_raw_pct`, `titolo_generico_pct` e la riduzione dei falsi positivi da pagine indice.
- I KPI non pienamente migliorabili lato codice, finche la fonte non cambia, sono: quota residua `sospetti_pct` su pre-informazione e completezza date/importi sui medesimi record.

## Run sul cluster Piemonte (DB corrente)

Verifica ID disponibili nel tuo DB:

```sql
SELECT id, titolo, link
FROM public.fonte
WHERE lower(coalesce(link, '')) LIKE '%regione.piemonte.it%'
ORDER BY id;
```

Run singola fonte (nel tuo ambiente risultano 24, 25, 26):

```powershell
python.exe -m app.cli run-fonte --fonte-id 24
python.exe -m app.cli run-fonte --fonte-id 25
python.exe -m app.cli run-fonte --fonte-id 26
```

## Avvio P2 (Interreg) - piano operativo immediato

Baseline iniziale (DB corrente, 2026-05-19):
- `fonte_id=55` (`interreg-marittimo.eu/calendario-avvisi`): sospetti 100% (2/2)
- `fonte_id=56` (`interreg-italiasvizzera.eu/.../avvisi`): sospetti 100% (1/1)
- `fonte_id=62` (`interreg-central.eu/calls-for-proposals`): sospetti 83.33% (5/6)

Priorita P2 (checkpoint tecnico su 2 fonti rappresentative):
1. `fonte_id=62` (caso HTML call-list con alta incidenza sospetti)
2. `fonte_id=55` (caso calendario/preavvisi)

Comandi run P2 (micro-step):

```powershell
python.exe -m app.cli run-fonte --fonte-id 62
python.exe -m app.cli run-fonte --fonte-id 55
```

Query KPI minima P2 (per fonte target):

```sql
WITH params AS (
   SELECT unnest(ARRAY[62,55]) AS fonte_id
),
base AS (
   SELECT b.*
   FROM public.bando b
   JOIN params p ON p.fonte_id = b.fonte_id
)
SELECT
   fonte_id,
   COUNT(*) AS tot_record,
   COUNT(*) FILTER (WHERE stato_bando = 'sospetto') AS sospetti,
   ROUND(100.0 * COUNT(*) FILTER (WHERE stato_bando = 'sospetto') / NULLIF(COUNT(*), 0), 2) AS sospetti_pct,
   COUNT(*) FILTER (WHERE stato_bando <> 'sospetto' AND titolo ~* '^(https?://|www\.)') AS titolo_url_raw,
   COUNT(*) FILTER (WHERE stato_bando <> 'sospetto' AND importo_numerico IS NOT NULL) AS importo_valido,
   COUNT(*) FILTER (
      WHERE stato_bando <> 'sospetto'
         AND (data_pubblicazione IS NOT NULL OR data_apertura IS NOT NULL OR data_scadenza IS NOT NULL)
   ) AS almeno_una_data
FROM base
GROUP BY fonte_id
ORDER BY fonte_id;
```

Criterio di avanzamento checkpoint P2:
- Riduzione `sospetti_pct` su entrambe le fonti target senza incremento di falsi positivi evidenti.
- Nessun peggioramento su `titolo_url_raw`.
- Incremento (anche minimo) di `almeno_una_data` e/o `importo_valido` nei record non sospetti.

## Nota su P4 (v2 backend)
P4 resta una evolutiva opzionale da pianificare nella v2 del backend, con analisi separata di:
- perimetro funzionale
- regole di sicurezza anti-falso-positivo
- impatto di manutenzione
