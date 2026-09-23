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

## SQL: ordine di applicazione (fase b)

**01 → 02 → seed → 03 → 04 → 05**, tutte nella stessa seduta e fuori dai giri delle 00/06/12/18.
È l'ordine eseguibile: il seed popola `dominio_ufficiale`, creata dalla 02 e letta dai trigger della 03.
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
