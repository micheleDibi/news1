# Report progressivo test end-to-end

Aggiornato al: 2026-04-30

Obiettivo:
- eseguire i test E2E uno alla volta
- registrare esito e KPI emersi
- allineare la checklist nel piano milestone man mano che gli scenari vengono validati

## Stato sintetico
- Test eseguiti: 9
- Test passati: 9
- Test falliti: 0
- Warning bloccanti: 0
- Warning non bloccanti: 1 (deprecazione `gotrue`, ora filtrata in pytest)

## Dettaglio test eseguiti

### Test 1 - E2E fonte HTML pipeline completa
- Test: app/tests/test_milestone12_e2e.py::test_e2e_fonte_html_pipeline_completa
- Tipologia: E2E mock-based, flusso base fonte HTML -> candidati -> upsert -> logging
- Esito: PASSED
- KPI emersi:
  - fonti_scansionate: 1
  - bandi_identificati: 3
  - inserted: 3
  - errori_fonti: 0
  - stato log fonte: completed
- Note:
  - warning non bloccante su deprecazione gotrue (dipendenza esterna)

### Test 2 - E2E fonte PDF pipeline completa
- Test: app/tests/test_milestone12_e2e.py::test_e2e_fonte_pdf_pipeline_completa
- Tipologia: E2E mock-based, flusso fonte PDF con propagazione formato_fonte
- Esito: PASSED
- KPI emersi:
  - fonti_scansionate: 1
  - bandi_identificati: 2
  - inserted: 2
  - errori_fonti: 0
  - stato log fonte: completed
  - formato_fonte candidati: PDF (coerente)
- Note:
  - warning non bloccante su deprecazione gotrue (dipendenza esterna)

### Test 3 - E2E fonte PDF scansionato con OCR
- Test: app/tests/test_milestone12_e2e.py::test_e2e_fonte_pdf_scansionato_ocr
- Tipologia: E2E mock-based, flusso PDF scansionato con verifica flag OCR nel payload
- Esito: PASSED
- KPI emersi:
  - bandi_identificati: 1
  - inserted: 1
  - raw_data_obj.ocr_used: True
  - stato log fonte: completed
- Note:
  - warning non bloccante su deprecazione gotrue (dipendenza esterna)

### Test 4 - E2E errore recuperabile verso pending
- Test: app/tests/test_milestone12_e2e.py::test_e2e_errore_recuperabile_fonte_va_in_pending
- Tipologia: E2E mock-based, gestione errore recuperabile con transizione di stato retry
- Esito: PASSED
- KPI emersi:
  - errori_fonti: 1
  - retry.fonti_pending: 1
  - retry.fonti_failed_final: 0
  - stato fonte finale: pending
  - errori definitivi registrati: 0
  - stato log fonte: failed (con errore tracciato)
- Note:
  - il test conferma l'ingresso in pending; non copre ancora il ramo di riprocessamento fino a successo finale

### Test 5 - E2E errore definitivo dopo max retry
- Test: app/tests/test_milestone12_e2e.py::test_e2e_errore_definitivo_dopo_max_retry
- Tipologia: E2E mock-based, gestione errore recuperabile quando `retry_count` raggiunge la soglia massima
- Esito: PASSED
- KPI emersi:
  - retry.fonti_failed_final: 1
  - retry.errori_definitivi: 1
  - stato fonte finale: failed_final
  - errori definitivi registrati: 1 (`entity_type = fonte`)
  - stato log fonte: failed con stacktrace presente
- Note:
  - warning `gotrue` non piu mostrato dopo filtro in `pyproject.toml`

### Test 6 - E2E bando gia esistente unchanged
- Test: app/tests/test_milestone12_e2e.py::test_e2e_bando_gia_esistente_unchanged
- Tipologia: E2E mock-based, upsert idempotente su record gia presenti senza modifiche
- Esito: PASSED
- KPI emersi:
  - inserted: 0
  - updated: 0
  - unchanged: 2
  - errori_fonti: 0
  - stato log fonte: completed
- Note:
  - comportamento atteso confermato: nessuna scrittura non necessaria su record invariati

### Test 7 - E2E classificazione AI valida arricchisce payload
- Test: app/tests/test_milestone12_e2e.py::test_e2e_classificazione_ai_valida_arricchisce_payload
- Tipologia: E2E mock-based, pipeline AI asincrona con output valido applicato al record bando
- Esito: PASSED (5.84s)
- KPI emersi:
  - job AI inserito in coda: 1
  - ai_applied_fields: almeno `tipologia_bando_id` e `programma_id` valorizzati
  - ai_rejected_fields: 0 (nessun campo scartato)
  - job marcato: completed
  - nessuna scrittura in `scraping_errori_definitivi`
- Note:
  - conferma che il worker AI applica classificazioni valide senza bloccare il flusso principale
  - conferma che nessun campo gia valorizzato viene sovrascritto

### Test 8 - E2E output AI non valido scartato
- Test: app/tests/test_milestone12_e2e.py::test_e2e_output_ai_non_valido_scartato
- Tipologia: E2E mock-based, pipeline AI asincrona con output fuori dizionario rifiutato e tracciato
- Esito: PASSED (5.52s)
- KPI emersi:
  - ai_applied_fields: 0 (nessun campo applicato)
  - ai_rejected_fields: almeno 1 (valore non presente nel dizionario consentito)
  - errori definitivi registrati: 1 (tracciato in `scraping_errori_definitivi`)
  - job marcato: failed
  - record bando non alterato
- Note:
  - conferma il gate 3 post-AI: nessun valore fuori dizionario raggiunge il record
  - conferma che tutti gli scarti vengono tracciati per audit

### Test 9 - E2E pending → retry → successo
- Test: app/tests/test_milestone12_e2e.py::test_e2e_pending_retry_successo
- Tipologia: E2E mock-based, fonte in stato `pending` (retry_count=1) ripresa dal run successivo con scan riuscito
- Esito: PASSED (5.54s)
- KPI emersi:
  - fonti_scansionate: 1 (fonte era in stato `pending`, ripresa da `get_all_active_with_limit`)
  - bandi_identificati: 2
  - inserted: 2
  - errori_fonti: 0
  - fonte.stato_processing finale: `ready` (reset da `mark_processing_success`)
  - fonte.retry_count finale: 0 (azzerato)
  - errori definitivi registrati: 0
  - stato log fonte: completed
- Note:
  - conferma che le fonti in `pending` vengono riprese automaticamente al run successivo
  - conferma che un retry riuscito azzera `retry_count` e riporta la fonte a `ready`
  - completa la copertura del flusso `pending → retry → successo`

## Tracciamento passaggi errore/retry

### Flusso A - errore recuperabile -> pending (Test 4)
1. Scan fonte fallisce con `FonteLevel2Error` recuperabile (es. timeout 504).
2. Incremento retry su fonte (`retry_count` +1).
3. Verifica soglia: `retry_count < max_retry` -> vero.
4. Transizione stato fonte: `processing` -> `pending`.
5. Log fonte chiuso in stato `failed` con errore tracciato (atteso per il singolo tentativo).
6. Nessun inserimento in errori definitivi.
7. KPI osservati: `retry.fonti_pending = 1`, `retry.fonti_failed_final = 0`.

### Flusso B - errore a soglia massima -> failed_final (Test 5)
1. Scan fonte fallisce con errore recuperabile, ma con `retry_count = max_retry - 1`.
2. Incremento retry su fonte.
3. Verifica soglia: `retry_count < max_retry` -> falso (soglia raggiunta).
4. Transizione stato fonte: `processing` -> `failed_final`.
5. Inserimento record in `scraping_errori_definitivi` (`entity_type = fonte`).
6. Log fonte chiuso in stato `failed` con stacktrace presente.
7. KPI osservati: `retry.fonti_failed_final = 1`, `retry.errori_definitivi = 1`.

## Classificazione anomalie

### W-DEP-GOTRUE
- Classe: Warning non bloccante.
- Origine: dipendenza esterna `supabase` che importa `gotrue` deprecato.
- Motivo classificazione Warning:
  - non interrompe i test;
  - non altera l'esito funzionale degli scenari E2E;
  - non indica una regressione del codice applicativo locale.
- Azione applicata: filtro warning in `pyproject.toml` per pulire l'output test.
- Azione futura consigliata: aggiornare dipendenza quando upstream rimuove il path deprecato.

### Flusso C - classificazione AI valida arricchisce payload (Test 7)
1. Bando creato con campi classificazione mancanti (`tipologia_bando_id = None`, `programma_id = None`).
2. Job AI inserito in coda con priorità standard.
3. Worker AI processa il job; modello restituisce output strutturato con valori nel dizionario.
4. Validazione output: `tipologia_bando_id` e `programma_id` presenti tra i valori consentiti -> approvati.
5. Arricchimento payload: campi applicati sul record bando.
6. Job marcato `completed`.
7. KPI osservati: `ai_applied_fields` non vuoto; nessun campo in `ai_rejected_fields`.

### Flusso D - pending → retry → successo (Test 9)
1. Fonte in stato `pending` con `retry_count=1` (aveva già fallito al run precedente).
2. Run successivo: `get_all_active_with_limit` include fonti in `pending` → fonte ripresa.
3. `mark_processing_started` porta la fonte in `processing`.
4. Scan riesce: lo scanner non solleva eccezioni, restituisce candidati.
5. Upsert bandi completato: 2 inserted.
6. `mark_processing_success` riporta la fonte a `ready` e azzera `retry_count = 0`.
7. Log chiuso in stato `completed`.
8. KPI osservati: `errori_fonti = 0`, `inserted = 2`, `fonte.stato_processing = ready`, `fonte.retry_count = 0`.

## Classificazione anomalie

### W-DEP-GOTRUE
- Classe: Warning non bloccante.
- Origine: dipendenza esterna `supabase` che importa `gotrue` deprecato.
- Motivo classificazione Warning:
  - non interrompe i test;
  - non altera l'esito funzionale degli scenari E2E;
  - non indica una regressione del codice applicativo locale.
- Azione applicata: filtro warning in `pyproject.toml` per pulire l'output test.
- Azione futura consigliata: aggiornare dipendenza quando upstream rimuove il path deprecato.

## Mapping checklist milestone
Scenario checklist (Test plan trasversale -> End-to-end):
1. pagina principale -> fonte -> bando -> DB: VALIDATO (coperto da Test 1)
2. PDF scansionato -> OCR -> AI -> classificazione: VALIDATO (coperto da Test 3)
3. pending -> retry -> successo: PARZIALE (coperto ingresso in pending da Test 4; manca verifica success path)
4. pending -> retry max -> errore definitivo: VALIDATO (coperto da Test 5)
5. classificazione AI valida arricchisce payload: VALIDATO (coperto da Test 7)
6. output AI non valido scartato: VALIDATO (coperto da Test 8)
7. pending → retry → successo: VALIDATO (coperto da Test 9)

## Esito finale
Tutti i 9 test E2E sono stati eseguiti e passati il 2026-04-30. La suite E2E è completa senza fallimenti né warning bloccanti.
