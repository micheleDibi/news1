# Esecuzione Fase 0 - 2026-05-07

## Stato
- Avvio Fase 0: eseguito
- Snapshot logico: non completato
- Backup completo ripristinabile: non completato
- Esito complessivo: BLOCCATO per connettivita/autenticazione DB

## Comandi tentati
1. Verifica tool locali `pg_dump`/`psql` -> non installati.
2. Fallback con Docker client PostgreSQL -> daemon inizialmente non attivo.
3. Avvio Docker Desktop -> riuscito.
4. `pg_dump` e `psql` via container su host diretto Supabase -> DNS host non risolto.
5. `pg_dump` e `psql` via pooler Supabase -> autenticazione fallita, poi blocco `ECIRCUITBREAKER`.
6. Snapshot via connessione applicativa Python (`app.db.connection`) -> fallback su pooler e stesso blocco `ECIRCUITBREAKER`.

## Evidenza tecnica del blocco
Errore ricorrente:
- `FATAL: (ECIRCUITBREAKER) too many authentication failures, new connections are temporarily blocked`

Effetto:
- impossibile creare dump `.dump`
- impossibile estrarre CSV baseline
- impossibile leggere KPI baseline da query SQL

## Cosa serve per sbloccare
1. Verifica e/o reset credenziali DB (utente/password) in `.env`.
2. Verifica username pooler atteso da Supabase (formato tipico: `postgres.<project_ref>`).
3. Attendere lo sblocco del circuit breaker lato pooler.
4. Rieseguire immediatamente la Fase 0.

## Piano di riesecuzione (stesso ordine)
1. Backup completo (`pg_dump` format custom).
2. Snapshot logico CSV delle tabelle operative.
3. Query KPI baseline e conteggi pre-restore.
4. Test restore su DB dedicato.
5. Allegare evidenza file e dimensioni in report.

## Note operative
- Nessuna modifica distruttiva e stata eseguita sul database.
- Nessuna fase successiva (truncate/fix) deve partire finche la Fase 0 non e completata con successo.

---

## Aggiornamento esecuzione - 2026-05-07 10:23

## Stato aggiornato
- Avvio Fase 0: eseguito
- Snapshot logico: completato
- Backup completo ripristinabile: completato
- Verifica integrita dump (TOC restore): completata
- Esito complessivo: COMPLETATO

## Parametri tecnici validati
- Connessione riuscita via pooler Supabase con user `postgres.qggfoubllzeojxqlguef`.
- Client PostgreSQL Docker allineato a server versione 17 (`postgres:17`).

## Artifact generati
Cartella: `_backups/phase0_20260507_102307`

- `opencoesione_full_20260507_102307.dump` (723016 bytes)
- `restore_toc.txt` (94832 bytes)
- `bando.csv` (832604 bytes)
- `bando_storico.csv` (154145 bytes)
- `bando_settori.csv` (51397 bytes)
- `bando_codici_ateco.csv` (197184 bytes)
- `bando_beneficiari.csv` (47098 bytes)
- `ai_job_queue.csv` (4725270 bytes)
- `scraping_log.csv` (28854 bytes)
- `scraping_errori_definitivi.csv` (175129 bytes)
- `kpi_baseline_bando.csv` (152 bytes)
- `public_table_counts.csv` (373 bytes)
- `restore_validation_counts.csv` (188 bytes)

## Query baseline - volumi estratti
- `bando`: 748 righe
- `bando_storico`: 484 righe
- `bando_settori`: 1199 righe
- `bando_codici_ateco`: 4511 righe
- `bando_beneficiari`: 1107 righe
- `ai_job_queue`: 748 righe
- `scraping_log`: 67 righe
- `scraping_errori_definitivi`: 348 righe

## Nota su test restore obbligatorio
- Eseguita verifica di leggibilita restore (`pg_restore --list`) con generazione TOC.
- Test di restore completo eseguito su DB locale dedicato (`restore_test`, PostgreSQL 17).

## Esito test restore completo
- Restore eseguito con `pg_restore --clean --if-exists --schema=public` su database locale isolato.
- Warning attesi su policy che referenziano `auth.role()` (schema `auth` assente in PostgreSQL vanilla, presente su Supabase).
- Dati delle tabelle operative ripristinati correttamente.

Confronto conteggi baseline vs restore (match 1:1):
- `bando`: 748
- `bando_storico`: 484
- `bando_settori`: 1199
- `bando_codici_ateco`: 4511
- `bando_beneficiari`: 1107
- `ai_job_queue`: 748
- `scraping_log`: 67
- `scraping_errori_definitivi`: 348

Conclusione:
- Fase 0 completata e validata, incluso test di ripristino dei dati operativi.
