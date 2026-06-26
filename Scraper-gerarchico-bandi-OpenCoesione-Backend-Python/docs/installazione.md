# Guida all'installazione

Questa guida copre la configurazione completa dell'ambiente di sviluppo su **Windows**, **Linux** e **macOS**.

---

## Requisiti di sistema

| Componente                | Richiesto | Versione              | Quando serve      | Note                                              |
|                           |           |                       |                   |                                                   |
| Python                    | Sì        | 3.11.x                | Sempre            | Testato su 3.11.9                                 |
| PostgreSQL (Supabase)     | Sì        | Gestito da Supabase   | Sempre            | Nessuna installazione locale richiesta            |
| Poppler                   | Solo OCR  | Ultima stabile        | PDF scansionati   | Usato da `pdf2image`                              |
| Tesseract OCR             | Solo OCR  | 5.x                   | PDF scansionati   | Usato da `pytesseract`; installare lingua `ita`   |

---

## 1. Clonare il repository

```bash
git clone https://github.com/cataldie/Scraper-gerarchico-bandi-OpenCoesione-Backend-Python.git
cd Scraper-gerarchico-bandi-OpenCoesione-Backend-Python
```

---

## 2. Creare e attivare il virtualenv Python

### Windows (PowerShell)

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

### Linux / macOS

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

---

## 3. Installare le dipendenze Python

```bash
pip install -r requirements.txt
```

> Questo installa tutti i wrapper Python (pdfplumber, pytesseract, pdf2image, openai, ecc.)
> ma **non** i binari di sistema Poppler e Tesseract: vedi sezione 4.

---

## 4. Installare i binari di sistema per OCR

I pacchetti `pdf2image` e `pytesseract` sono wrapper Python attorno a programmi
di sistema che vanno installati separatamente.

### 4.1 Poppler (richiesto da `pdf2image`)

**Windows:**

1. Scaricare l'archivio più recente da:
   [https://github.com/oschwartz10612/poppler-windows/releases](https://github.com/oschwartz10612/poppler-windows/releases)
   (file `Release-XX.XX.X-0.zip`)
2. Estrarre in una cartella fissa, es. `C:\tools\poppler\`
3. Aggiungere `C:\tools\poppler\Library\bin` alla variabile d'ambiente `PATH`:
   - Pannello di controllo → Sistema → Variabili d'ambiente → `Path` → Nuovo

**Ubuntu / Debian:**

```bash
sudo apt update
sudo apt install poppler-utils
```

**macOS:**

```bash
brew install poppler
```

**Verifica:**

```bash
pdftoppm -v
```

---

### 4.2 Tesseract OCR (richiesto da `pytesseract`)

**Windows:**

1. Scaricare l'installer da:
   [https://github.com/UB-Mannheim/tesseract/wiki](https://github.com/UB-Mannheim/tesseract/wiki)
   (scegliere `tesseract-ocr-w64-setup-XX.XX.XX.exe`)
2. Durante l'installazione selezionare anche il **pacchetto lingua italiano** (`ita`)
3. Aggiungere la directory di installazione al `PATH`, es.:
   `C:\Program Files\Tesseract-OCR`

**Ubuntu / Debian:**

```bash
sudo apt install tesseract-ocr tesseract-ocr-ita
```

**macOS:**

```bash
brew install tesseract
brew install tesseract-lang   # include italiano
```

**Verifica:**

```bash
tesseract --version
tesseract --list-langs        # deve includere 'ita'
```

---

### 4.3 Configurare il percorso Tesseract (solo se non è nel PATH)

Se Tesseract non è nel PATH di sistema, impostare la variabile nel file `.env`:

```env
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

> Il modulo `app/ocr/ocr_processor.py` legge automaticamente questa variabile
> se definita, passandola a `pytesseract.pytesseract.tesseract_cmd`.

---

## 5. Configurare le variabili d'ambiente

Copiare il file esempio e compilarlo:

```bash
cp .env.example .env
```

Aprire `.env` e valorizzare almeno:

```env
# Supabase / PostgreSQL
DATABASE_URL=postgresql://postgres:<PASSWORD>@db.<PROJECT_REF>.supabase.co:5432/postgres
DATABASE_POOLER_HOST=aws-1-eu-central-1.pooler.supabase.com
DATABASE_POOLER_PORT=6543
DATABASE_SSLMODE=require
SUPABASE_URL=https://<PROJECT_REF>.supabase.co
SUPABASE_KEY=<SERVICE_ROLE_KEY>

# Scraping
SOURCE_ROOT_URL=https://opencoesione.gov.it/it/opportunita_2021_2027/

# OpenAI (richiesto solo per la pipeline AI - M7)
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# OCR (opzionale se Tesseract è nel PATH)
TESSERACT_CMD=tesseract
OCR_LANGUAGE=ita+eng
```

> Se la connessione diretta a Supabase non è disponibile, il progetto tenta
> automaticamente il fallback tramite pooler usando `DATABASE_POOLER_HOST`
> e `DATABASE_POOLER_PORT`.

---

## 6. Applicare le migrazioni al database

Lo schema SQL si trova in `db/supabase_migration_bandi_opencoesione.sql`.
Eseguirlo dalla console SQL di Supabase oppure tramite psql:

```bash
psql "$DATABASE_URL" -f db/supabase_migration_bandi_opencoesione.sql
```

---

## 7. Verificare l'installazione

### Test rapido (senza DB)

```bash
.venv/Scripts/python.exe -m pytest app/tests/test_milestone8_ocr.py -v
# Linux/macOS: .venv/bin/python -m pytest app/tests/test_milestone8_ocr.py -v
```

Tutti i test M8 devono passare anche senza Poppler e Tesseract installati
(usano mock).

### Test completo con DB reale

```bash
.venv/Scripts/python.exe -m pytest app/tests/ -v
```

I test marcati `integration` richiedono la connessione al DB (variabili `.env`
valorizzate).

### Smoke test end-to-end

```powershell
# Windows — run completa limitata a 1 fonte
.\.venv\Scripts\python.exe -m app.cli run --limit 1

# Linux / macOS
.venv/bin/python -m app.cli run --limit 1
```

Output atteso: JSON con `fonti_scansionate`, `bandi_identificati`, `ai_jobs`, `retry`.

Altri comandi disponibili:

```powershell
# Singola fonte (es. id 42)
.\.venv\Scripts\python.exe -m app.cli run-fonte --fonte-id 42

# Solo fonti in stato pending
.\.venv\Scripts\python.exe -m app.cli run-pending

# Scheduler (bloccante, default: 02:00 completo, ogni 4 ore pending)
.\.venv\Scripts\python.exe -m app.scheduler start
.\.venv\Scripts\python.exe -m app.scheduler start --cron-full "0 3 * * *" --cron-pending "0 */2 * * *"
```

---

## Riepilogo dipendenze per funzionalità

| Funzionalità | Solo `requirements.txt` | Poppler | Tesseract |
|---|:---:|:---:|:---:|
| Scraping HTML/CSV | ✅ | — | — |
| Parsing PDF nativo (testo) | ✅ | — | — |
| OCR PDF scansionati | ✅ | ✅ | ✅ |
| Pipeline AI (classificazione) | ✅ | — | — |
| Test unitari (mock) | ✅ | — | — |
