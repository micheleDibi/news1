# Archivio — vecchia modalità BATCH (non più usata)

Questi file appartengono alla precedente versione **batch** della skill, sostituita
dalla modalità **single-bando** (1 URL → 1 JSON, vedi `../SKILL.md`).

Sono conservati qui per riferimento, **non** fanno più parte del flusso della skill.
Orchestrazione su molti bandi, deduplica e storage sono ora responsabilità del
progetto che incorpora la skill.

- `load_csv.py` — leggeva il CSV, normalizzava/deduplicava gli URL vs `state/processed.json`.
- `run_batch.py` — orchestratore CLI del batch. **Nota:** importa `generate_json_output`
  via `sys.path`; spostato qui, quell'import non si risolve più (atteso, è codice archiviato).
- `upload_to_supabase.py` — upload del batch su Supabase.
- `state/` — stato persistente degli URL già processati.
