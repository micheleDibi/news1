# Misure per la salute, giro 2 (percorso B)

Misure di `db` (task G2-D1), 30/09/2026 sera, dal Mac con la service key del DB bandi: **solo GET** su
PostgREST, chiavi lette dentro uno script che non le stampa. Nessuna RPC, nessuna scrittura. Niente
misure del percorso A (sospeso). Orari in UTC come nel DB (Roma = UTC+2).

---

## M6. Chiavi dei contatori in `pipeline_run`

**Prova**: `GET pipeline_run?step=eq.pipeline&order=id.desc&limit=20` con `count=exact` → 206,
`0-19/43`. Righe 141 … 86, dal 26/09 22:00 al 30/09 16:47; giri: 4 per ciascuno fra `boot`, `00:00`,
`06:00`, `12:00`, `18:00`; esiti: 19 `ok`, 1 `saltato` (104, `saltato_per_lock`: nessuno step).

`contatori` ha una chiave per step (`discover`, `scrape`, `preprocess`, `enrich`, `resolver`,
`ricontrolli`, `seo`, `monitor`), più `usd`, `crediti`, `costo_usd`, `durata_s`, `slug_modificati`,
`saltato_per_lock`. **Lo `status` degli step non è nei contatori** (solo `resolver`, `ricontrolli` e
`monitor` hanno un proprio `status` interno): `passi_non_ok` (§11) oggi non esiste in nessuna riga.

### `scrape` (19 righe su 19 non saltate, sempre tutte le chiavi)
`fonti_totali`, `fonti_processate`, `fonti_errors`, `fonti_skipped_no_strategy`,
`fonti_skipped_skip_strategy`, `bandi_estratti`, `bandi_nuovi`, `bandi_cambiati`, `bandi_identici`,
`bandi_con_link`, `bandi_senza_link`, `bandi_upsert_processed`, `controlli_aggiornati`, `segnali`,
`spariti`. Tutte intere.

**Fonti tentate: non c'è una chiave sola.** In `app/bando_runner.py` ogni ramo d'errore
(`get_scraper`, `scrape`, `upsert`: righe 472, 483, 534) fa `fonti_errors += 1` e `continue`, quindi
`fonti_processate` (riga 561) conta **solo le fonti riuscite**. Verificato sui dati:
`fonti_totali = fonti_processate + fonti_errors + fonti_skipped_no_strategy + fonti_skipped_skip_strategy`
(es. 141: 104 = 78 + 0 + 8 + 18). Quindi:

- **fonti tentate = `fonti_processate + fonti_errors`**;
- `ingresso_guasto` (§8, «fonti_errors = fonti tentate») equivale a `fonti_errors > 0 AND fonti_processate = 0`.

Nelle 20 righe `fonti_errors` vale sempre 0, `fonti_processate` fra 70 e 78.

### `preprocess`
Sempre presenti: `processed_total`, `errors`, `rejected`, `valid`, `elapsed_s`. Le altre
(`db_updated`, `db_failed`, `fallback_*`, `with_data_*`, `by_stato_bando`, `avg_confidence`,
`dry_run`) solo in 8 righe su 19. `passo_degradato:estrazione` usa solo le prime due.

**Caso reale già nel DB**: righe 107, 111, 113, 115, 119 (28/09 10:00 → 29/09 04:00) con
`errors = processed_total` (4/4, 24/24, 24/24, 25/25, 25/25) ed **esito `ok`**: il credito esaurito
del 28/09. È esattamente ciò che `passo_degradato:estrazione` deve vedere.

### `enrich`
Sempre presenti: `enriched_total`, `refined_total`, `elapsed_s`. `enriched_db_ok` e
`enriched_db_failed` compaiono **solo quando `enriched_total > 0`** (3 righe: 139 7/7, 125 4/4,
121 20/20). La regola «`enriched_total > 0` con `enriched_db_ok == 0`» va letta con
`enriched_db_ok` assente = 0 solo se `enriched_total > 0`.

### `seo`
Sempre presenti: `selected`, `payload_ok`, `payload_failed`, `payload_ok_db_failed`,
`completed_db_ok`, `canonical_*`, `livello_*`, `with_*`, `avg_*`, `dry_run`, `elapsed_s`.
**`doppioni_oe` c'è solo nella riga 141** (primo giro col codice di ottobre), insieme a
`doppioni_oe_errori`, `doppioni_oe_non_scritti`, `doppioni_oe_controllo_saltato`,
`payload_failed_altri`, `payload_failed_motivi`, `affermazioni_non_sostenute`. Nelle righe più
vecchie `doppioni_oe` assente va letto come 0.

Nota: in 17 righe su 19 `selected=1, payload_ok=0, payload_failed=1` (il bando 772894 noto,
RIPRESA §4.2): con la regola di §8 `(selected − doppioni_oe) > 0 con payload_ok == 0` questo
caso **fa scattare `passo_degradato:redazione` a ogni giro**. Nella riga 141 `doppioni_oe=0`,
`payload_ok=1`: la regola oggi non scatterebbe, ma basta un giro con un solo bando fallito.

### `monitor` nella riga `pipeline`
Contatori pieni solo nei giri 06:00 e 18:00 (8 righe); negli altri `monitor` è `{}`
(`giro_non_previsto`). `eventi_non_scritti` in tutte le 8; **`eventi_non_applicati` solo in 139**
(rilascio 2).

### Righe `step='monitor'`
**Prova**: `GET pipeline_run?step=eq.monitor&giro=not.is.null&order=id.desc&limit=5`, estraendo
`contatori->>eventi_non_applicati` e `contatori->>eventi_non_scritti`:

| id | giro | avviato | esito | eventi_non_applicati | eventi_non_scritti |
|---|---|---|---|---|---|
| 138 | 18:00 | 30/09 16:10 | ok | 0 | 0 |
| 130 | 06:00 | 30/09 04:09 | ok | assente | 0 |
| 124 | 18:00 | 29/09 16:12 | ok | assente | 0 |
| 118 | 06:00 | 29/09 04:08 | ok | assente | 0 |
| 110 | 18:00 | 28/09 16:11 | ok | assente | 0 |

Le chiavi si chiamano esattamente così. Assente = rilascio precedente: per gli allarmi vale 0.

## M7. Lock del giro e `pipeline_lock`

- **Nome del lock del giro**: `bandi_pipeline` (`backend/app/bandi_pipeline.py:92`, `LOCK_PIPELINE`),
  TTL 4 h (`LOCK_TTL_S = 4 * 3600`, riga 96). Quindi «7 + LOCK_TTL» di `produttore_fermo` = 11 h.
- **Colonne** (schema OpenAPI di PostgREST): `nome` text, `proprietario` text,
  `acquisito_at` timestamptz, `scade_at` timestamptz. Nient'altro.
- **Righe oggi**: `GET pipeline_lock?select=*&order=nome`, `count=exact` → `*/0`, nessun lock.
- RPC esposte per i lock: `lock_acquisisci`, `lock_rilascia` (di scrittura: mai chiamate).

## Righe `giro='boot'` degli ultimi 7 giorni

**Prova**: `GET pipeline_run?giro=eq.boot&avviato_at=gte.2026-09-23T16:00:00Z&order=id`,
`count=exact` → `0-21/22`.

**Attenzione: 22 righe, ma solo 12 sono del giro.** Anche lo step `resolver` scrive una sua riga con
`giro='boot'` a ogni avvio (8, 35, 41, 49, 51, 57, 79, 112, 134, 140). `riavvii_ripetuti` deve
filtrare `step='pipeline'`, altrimenti ogni riavvio conta due volte.

| id (pipeline) | avviato (UTC) | concluso | esito |
|---|---|---|---|
| 9 | 23/09 18:13 | 18:19 | ok |
| 23 | 24/09 14:27 | 14:27 | saltato |
| 36 | 25/09 06:51 | 06:57 | ok |
| 43 | 25/09 07:13 | 07:19 | ok |
| 50 | 25/09 07:25 | 07:31 | ok |
| 52 | 25/09 07:56 | 08:02 | ok |
| 58 | 25/09 09:23 | 09:31 | ok |
| 80 | 26/09 10:46 | 10:53 | ok |
| 104 | 28/09 06:21 | 06:21 | saltato |
| 113 | 28/09 17:58 | 18:05 | ok |
| 135 | 30/09 10:33 | 10:38 | ok |
| 141 | 30/09 16:47 | 16:52 | ok |

- Il 25/09 ci sono **5 boot in 2 h 32'** (riavvii a mano durante un deploy): con la regola «almeno
  3 righe boot in 6 h» quel giorno `riavvii_ripetuti` sarebbe scattato. È il comportamento voluto
  dal contratto, ma un deploy con più riavvii produrrà l'allarme per 6 h.
- Nessuna riga ha ancora il contatore `riavvio_dopo_crash` (arriva con §11).

## Riepilogo per chi implementa §8

| regola | chiavi da leggere |
|---|---|
| `ingresso_guasto` | `scrape.fonti_errors`, `scrape.fonti_processate` (tentate = somma) |
| `passo_degradato:estrazione` | `preprocess.errors`, `preprocess.processed_total` |
| `passo_degradato:arricchimento` | `enrich.enriched_total`, `enrich.enriched_db_ok` (assente se total = 0) |
| `passo_degradato:redazione` | `seo.selected`, `seo.doppioni_oe` (assente prima del 30/09 sera), `seo.payload_ok` |
| `eventi_non_applicati` / `_non_scritti` | `contatori->>…` delle righe `step='monitor'` con `giro` non nullo |
| `produttore_fermo` | righe `step='pipeline'`, giro in 00/06/12/18; lock `bandi_pipeline`, TTL 4 h |
| `riavvii_ripetuti` | righe `step='pipeline'` **e** `giro='boot'` |
