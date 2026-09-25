<p align="center">
  <img src="public/logo.png" alt="EduNews24 Logo" width="280" />
</p>

<h1 align="center">EduNews24</h1>

<p align="center">
  <strong>Piattaforma editoriale intelligente per il mondo dell'istruzione italiana</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Astro-5.4-FF5D01?logo=astro&logoColor=white" alt="Astro" />
  <img src="https://img.shields.io/badge/React-18.3-61DAFB?logo=react&logoColor=white" alt="React" />
  <img src="https://img.shields.io/badge/FastAPI-Python_3.10+-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Supabase-PostgreSQL-3ECF8E?logo=supabase&logoColor=white" alt="Supabase" />
  <img src="https://img.shields.io/badge/TailwindCSS-3.4-06B6D4?logo=tailwindcss&logoColor=white" alt="TailwindCSS" />
  <img src="https://img.shields.io/badge/Claude-Opus_4.7-D4A574?logo=anthropic&logoColor=white" alt="Claude" />
  <img src="https://img.shields.io/badge/OpenAI-GPT_4.1-412991?logo=openai&logoColor=white" alt="OpenAI" />
  <img src="https://img.shields.io/badge/Firecrawl-Scraping-FF6B35" alt="Firecrawl" />
</p>

---

## Panoramica

**EduNews24** e una testata giornalistica online dedicata al mondo della scuola, dell'universita e della formazione in Italia. La piattaforma combina un CMS editoriale completo con strumenti di intelligenza artificiale per la creazione, ricostruzione e ottimizzazione dei contenuti.

Oltre al flusso editoriale tradizionale (articoli, redazione, pubblicazione), il sistema integra:

- **Pipeline news automatizzata** — scraping di fonti esterne, ricostruzione AI con Claude/OpenAI, pubblicazione e condivisione social.
- **Sezione Bandi** — pipeline `scraper_bandi/` (discover → scrape → preprocess → enrich → resolver → seo, più ricontrolli e monitor) che ingerisce bandi di finanziamento da OpenCoesione e fonti istituzionali, ne cerca la fonte ufficiale e genera con Claude il contenuto SEO.
- **Interpelli scuola** — interpelli per docenti, ATA e DSGA pubblicati dalle scuole (raccolti da scuolainterpelli.it), con articolo generato da Claude.
- **Selezione Personale** — concorsi e selezioni della Pubblica Amministrazione (API inPA, senza filtro di settore).

Tutto orchestrato attorno a un'architettura dual-database (CMS principale + DB dedicato ai bandi) con scheduler Python, sender automatici e front-end SSR Astro.

---

## Architettura

```
                       ┌─────────────────────────────────────────┐
                       │              EduNews24                  │
                       └──────────────────┬──────────────────────┘
                                          │
        ┌─────────────────────────────────┼─────────────────────────────────┐
        │                                 │                                 │
┌───────▼────────┐               ┌────────▼─────────┐              ┌────────▼────────┐
│   Frontend     │               │    Backend       │              │     Storage     │
│  Astro 5 SSR   │◄──── HTTP ───►│   FastAPI        │              │                 │
│  React 18      │  proxy /api/  │   Python 3.10+   │              │ Supabase A      │
│  TailwindCSS   │               │   SQLAlchemy     │              │ (news, profili) │
│  TipTap editor │               │   Schedule lib   │              │                 │
└───────┬────────┘               └─────────┬────────┘              │ Supabase B      │
        │                                  │                       │ (bandi, RLS)    │
        │                                  │                       │                 │
        │                                  │                       │ AWS S3          │
        │                                  │                       │ (media + audio) │
        └──── lettura anon + RLS ──────────┼───────────────────────┴────────┬────────┘
                                           │                                │
        ┌──────────────────────────────────┼────────────────────────────────┘
        │                                  │
┌───────▼──────────┐         ┌─────────────▼──────────────┐
│  Bandi Pipeline  │         │      Integrazioni AI       │
│                  │         │                            │
│  scraper_bandi/  │         │  Claude Opus 4.7           │
│  (Python, venv)  │         │   - Ricostruzione articoli │
│  discover        │         │   - Skill bandi SEO        │
│  → scrape        │         │   - Persona rewriter       │
│  → preprocess    │         │                            │
│  → enrich        │         │  OpenAI GPT-4.1            │
│  → resolver      │         │   - Tag/Summary/FAQ        │
│  → seo (Claude)  │         │   - Generazione articoli   │
│  + ricontrolli   │         │                            │
│  + monitor       │         │  Firecrawl                 │
│  → Supabase B    │         │   - Scraping stealth/auto  │
│                  │         │                            │
│  4 giri/giorno   │         │  Google Cloud TTS          │
│  (bandi_sender)  │         │   - Audio articoli         │
└──────────────────┘         └────────────────────────────┘
```

### Architettura dual-database

| DB | Provider | Contenuto | Accesso frontend |
|---|---|---|---|
| **DB A — `news1`** | Supabase | Articoli, profili, categorie, podcast, interpelli, selezione personale | anon key |
| **DB B — `bandi`** | Supabase | Tabella `bando` + lookup (regioni, settori, beneficiari, codici_ateco, programmi, tipologie_bando, modalita_erogazione) | anon key + RLS (`stato_processing = 'completed' AND slug IS NOT NULL`) |

Tutta la scrittura su DB B avviene **solo** dal backend con service-role key. Il front-end legge in sola lettura via anon key e Row Level Security garantisce che siano visibili solo i bandi arrivati in fondo alla pipeline (`stato_processing = 'completed'` con slug; contratto completo in `docs/contratto-db-bandi.md`).

---

## Tech Stack

### Frontend

| Tecnologia | Versione | Utilizzo |
|---|---|---|
| **Astro** | 5.4 | Framework SSR con `@astrojs/node` standalone adapter |
| **React** | 18.3 | Componenti interattivi (editor, dashboard, form) |
| **TailwindCSS** | 3.4 | Utility-first + plugin forms/typography |
| **TipTap** | 2.11 | Editor rich-text |
| **React Hook Form** | 7.54 | Form con validazione |
| **Splide** | 4.1 | Carousel e auto-scroll |
| **@supabase/supabase-js** | 2.47 | Client DB sia per news che per bandi |
| **@anthropic-ai/sdk** | 0.78 | SDK Claude lato edge per `generate-article` |

### Backend principale (`/backend`)

| Tecnologia | Utilizzo |
|---|---|
| **FastAPI** | API REST per scraping news, ricostruzione, sender pipeline |
| **SQLAlchemy** | ORM news (staging SQLite) |
| **Pydantic** | Schemi I/O |
| **Uvicorn** | Server ASGI (no `--reload` in prod) |
| **claude-agent-sdk** | Esecuzione in-process delle skill news (`backend/skill/`, `backend/news-angle-rewriter-persona/`); lo step SEO dei bandi usa l'SDK `anthropic` diretto |
| **schedule** | Scheduler dei sender (news, bandi, interpelli, selezione personale) |
| **firecrawl-py** | Scraping con bypass anti-bot |
| **loguru** | Logging strutturato |
| **boto3** | Upload media su S3 |
| **google-cloud-texttospeech** | Generazione audio articoli |

### Backend bandi (`/scraper_bandi`)

Il vecchio subproject `Scraper-gerarchico-bandi-OpenCoesione-Backend-Python/` e' stato **rimosso in v5**. Al suo posto c'e' `scraper_bandi/` — sub-progetto Python autonomo (venv dedicato, ~56 file Python in `app/`, 17 comandi CLI `python -m app <comando>`), **in esercizio**: `backend/app/bandi_sender.py` lo lancia alle 00/06/12/18 (discover → scrape-bandi → preprocess → enrich → resolver → seo, più ricontrolli e monitor alle 06 e 18) fino a `stato_processing='completed'`.

Setup: `scraper_bandi/README.md`; comandi: `docs/bandi-monitor/RIPRESA.md` §6 e la docstring di `scraper_bandi/app/__main__.py`; stato e verifiche: `docs/bandi-monitor/RIPRESA.md`.

Schema `fonte` ridotto in v5 (drop 8 colonne legacy: `titolo`, `note_aggiuntive`, retry/error tracking). Vedi `backend/sql/fonte_alter_v5_drop_legacy.sql`.

### Skill SEO bandi (`scraper_bandi/app/seo_skill.py`)

`/bandi-seo-enricher` non esiste più. Il contenuto editoriale dei bandi lo genera lo step `seo` di `scraper_bandi/`: una chiamata Claude Opus 4.7 con tool use per bando (niente Agent SDK), su bandi già validati da `preprocess` (`is_valid_bando`) e arricchiti da `enrich` (FK, junction, date); stato finale `completed`. Dettagli in `scraper_bandi/README.md` (Step v8).

---

## Funzionalita Principali

### Gestione articoli
- Editor rich-text TipTap con grassetto, corsivo, link, immagini, liste
- Modalita modifica + anteprima live
- Bozze/pubblicato + permessi role-based
- Upload immagini su S3 con varianti responsive (320 → 1280px)
- Supporto video con tracking durata
- Audio TTS Google Cloud
- Form contatto integrabile per articolo
- Indice automatico + interlink articoli correlati

### Intelligenza artificiale
- **Ricostruzione Claude Opus 4.7** — riscrittura completa con tono giornalistico, persona configurabile, recovery anti-race su job stallati
- **Tag SEO via OpenAI GPT-4.1** — 5-8 keyword ottimizzate
- **Riassunti via GPT-4.1** — titolo + sommario
- **FAQ on-demand via GPT-4.1** — 4-6 domande con structured data JSON-LD
- **Generazione articoli da prompt** con ricerca web (Firecrawl + Claude, skill `news-angle-rewriter-persona` via `/api/articles/generate-with-persona`)
- **Step SEO bandi** — `scraper_bandi/app/seo_skill.py`, Claude Opus 4.7 con tool use (il system prompt sandboxato con file ausiliari in `/tmp/` è quello della skill news `backend/skill/`)
- **Persona runner** — generazione articoli con persona giornalistica e job persistence

### SEO & dati strutturati
- Sitemap XML dinamiche (articoli, categorie, video, news recenti, interpelli, selezione personale, bandi, pagine filtro)
- JSON-LD `Article`, `BreadcrumbList`, `FAQPage`
- Pagine AMP
- Meta tag Open Graph + Twitter Card
- robots.txt con rate-limit per bot aggressivi
- URL slug-friendly
- **IndexNow** — notifica push a Bing/Yandex su pubblicazione

### Pipeline news automatizzata
- Scraping Firecrawl, con ripiego cloudscraper + BeautifulSoup
- Pipeline: scraping → riassunto (automatici) → revisione manuale → ricostruzione AI e pubblicazione (avviate a mano dall'admin)
- Scheduler `app/sender.py` configurabile per fasce orarie
- Anti-duplicazione

### Pipeline bandi (`scraper_bandi/`)
Vedi la sezione [Pipeline Bandi](#pipeline-bandi) sotto e `docs/bandi-monitor/RIPRESA.md` §2 per il dettaglio.

### Social & engagement
- Auto-posting Facebook con hashtag (testo del post dal sottotitolo, non dal titolo)
- Sistema forum/commenti per articolo
- Profili autore con pagine dedicate
- Pagina team editoriale

### Pannello amministrazione
- Dashboard gestione articoli, utenti, categorie, podcast
- Sistema permessi role-based (admin, direttore, redattore, giornalista; accesso all'area admin anche per docente/insegnante)
- Log attivita
- Strumenti automazione news (scraping → riassunto → ricostruzione → pubblicazione)
- Creazione utenti in batch
- Plugin requests management
- API access registration

### Sezioni specializzate
- **Interpelli scuola** — `/interpelli`, `/interpelli/[slug]` con sender dedicato
- **Bandi e Gare** — `/bandi`, `/bandi/[slug]` con filtri avanzati multi-select
- **Finanziamenti EU** — sezione rimossa: `/eu-funding` e i sotto-percorsi rispondono 410 Gone
- **Selezione Personale** — `/selezione-personale`, `/selezione-personale/[slug]` concorsi della Pubblica Amministrazione
- **Podcast** — pubblicazione episodi audio editoriali
- **Linkinbio** — pagina aggregatrice per social

---

## Pipeline Bandi

> **Stato (25/09/2026)**: la pipeline vive in `scraper_bandi/` (venv proprio) ed e' lanciata quattro volte al giorno (00:00, 06:00, 12:00, 18:00) da `backend/app/bandi_sender.py`, con gli step in `backend/app/bandi_pipeline.py`: discover → scrape → preprocess → enrich → resolver → seo, piu' ricontrolli e monitor alle 06:00 e 18:00. Stato, verifiche e decisioni aperte: `docs/bandi-monitor/RIPRESA.md`; contratto del DB: `docs/contratto-db-bandi.md`; comandi: `scraper_bandi/README.md`.

### Drain manuale skill

Non esiste piu' un drain separato: la skill SEO e' lo step `seo` della pipeline e si lancia a mano con `cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app seo --dry-run --limit 3` (senza `--dry-run` scrive sul DB). Elenco dei comandi: `scraper_bandi/README.md` e `docs/bandi-monitor/RIPRESA.md` §6.

### Fase skill SEO bandi (Claude)

Modulo: `scraper_bandi/app/seo_skill.py` (runner `bando_seo_runner.py`), step `seo` della pipeline: una chiamata Claude Opus 4.7 (`SEO_MODEL`, default `claude-opus-4-7`) con tool use `save_seo_bando` porta i bandi da `stato_processing='enriched'` a `'completed'` scrivendo i 14 campi editoriali (slug, titoli, contenuto, allegati, importi, `link_candidatura`...). Dettaglio in `scraper_bandi/README.md` ("Step v8 — skill SEO").

### Colonne chiave su `bando` (DB B)

Lo schema v4 non esiste piu': `state`, `state_detail`, `attempts` e `date_quotes` sono state rimosse (migrazioni v6 e v8). Oggi la lavorazione e' in `stato_processing` (`scraped → processed → enriched → completed`, oppure `rejected`), lo stato del bando in `stato_bando`, e il frontend mostra le righe con `stato_processing='completed'` e `slug` non nullo (`src/lib/bandi/pubblicazione.ts`); `link_candidatura_source` e' deprecata a favore di `bando_link`. Schema completo: tabella `bando` in `scraper_bandi/README.md` e `docs/contratto-db-bandi.md`.

### Orchestrazione

Il sender `backend/app/bandi_sender.py` esegue la pipeline al boot e poi quattro volte al giorno (00:00, 06:00, 12:00, 18:00); in produzione gira come servizio systemd e a DB un cron orario chiude i bandi scaduti e apre quelli in apertura (`docs/bandi-monitor/RIPRESA.md` §2 [DA VERIFICARE sul server]). La skill si lancia a mano come in "Drain manuale skill" sopra.

---

## Struttura Progetto

```
news1/
├── src/                                       # Frontend Astro
│   ├── pages/
│   │   ├── api/
│   │   │   ├── articles/                      # CRUD articoli
│   │   │   ├── podcasts/                      # Gestione podcast
│   │   │   ├── interpelli/                    # API interpelli
│   │   │   ├── v1/                            # API pubblica in sola lettura (docs/api-v1.md)
│   │   │   ├── users/                         # Gestione utenti
│   │   │   ├── generate-article.ts            # AI: articoli da prompt
│   │   │   ├── generate-tags.ts               # AI: tag SEO
│   │   │   ├── generate-summary.ts            # AI: riassunti
│   │   │   ├── generate-faq.ts                # AI: FAQ
│   │   │   ├── tts/generate.ts                # Audio TTS
│   │   │   ├── upload.ts                      # Upload S3
│   │   │   ├── upload-video*.ts               # Upload video chunked
│   │   │   ├── contact.ts                     # Form contatti
│   │   │   ├── indexnow-notify.ts             # Notifica IndexNow
│   │   │   └── ...
│   │   ├── admin/                             # Dashboard admin
│   │   ├── amp/                               # Pagine AMP
│   │   ├── bandi.astro                        # Lista bandi (RLS)
│   │   ├── bandi/[slug].astro                 # Dettaglio bando
│   │   ├── interpelli.astro                   # Lista interpelli
│   │   ├── interpelli/[slug].astro            # Dettaglio interpello
│   │   ├── selezione-personale.astro          # Lista concorsi
│   │   ├── selezione-personale/[slug].astro   # Dettaglio concorso
│   │   ├── eu-funding/                        # 410 Gone: sezione rimossa (bandi in /bandi)
│   │   ├── team/                              # Profili team
│   │   ├── podcasts/                          # Sezione podcast
│   │   ├── sitemap-*.xml.ts                   # Sitemap dinamiche
│   │   └── [category].astro, [category]/[slug].astro
│   ├── components/
│   │   ├── ArticleForm.tsx                    # Editor articoli con strumenti AI
│   │   ├── automation/                        # Tab scraping/reconstruct/summarize
│   │   ├── BandiExpertCta.astro               # CTA "parla con un esperto"
│   │   ├── Header.astro, CategorySidebar.astro
│   │   ├── ContactForm.tsx, AudioPlayer.tsx
│   │   └── ForumChat.astro
│   ├── layouts/
│   │   ├── Layout.astro
│   │   └── AdminLayout.astro
│   ├── middleware/, middleware.ts             # Routing/auth middleware
│   └── lib/
│       ├── supabase.ts                        # Client DB A (news)
│       ├── supabase-bandi.ts                  # Client DB B (bandi) + tipi
│       ├── aws.ts                             # Upload S3
│       ├── seo.ts                             # Dati strutturati
│       ├── indexnow.ts                        # IndexNow client
│       ├── categories.ts                      # Config categorie
│       └── video-compress.ts                  # Compressione video
│
├── backend/                                   # FastAPI Python
│   ├── app/
│   │   ├── main.py                            # App FastAPI + endpoint principali
│   │   ├── models.py, schemas.py              # SQLAlchemy + Pydantic
│   │   ├── sender.py                          # Scheduler pipeline news
│   │   ├── bandi_sender.py, bandi_pipeline.py # Scheduler 4 giri/giorno + step della pipeline bandi (scraper_bandi/)
│   │   ├── interpelli.py, interpelli_sender.py, interpelli_tables.sql
│   │   ├── selezione_personale.py, selezione_personale_sender.py
│   │   ├── persona_runner.py                  # Persona rewriter job
│   │   ├── skill_runner.py                    # Runner skill news
│   │   ├── google_indexing.py, indexnow.py
│   │   └── variables_edunews.py               # Prompt + costanti modello
│   ├── enhanced_scraper.py                    # Scraper avanzato news
│   ├── skill/                                 # Skill ricostruzione articoli
│   │   ├── SKILL.md
│   │   ├── references/                        # Linee guida editoriali
│   │   └── scripts/                           # Firecrawl + JSON generator
│   ├── news-angle-rewriter-persona/           # Skill persona rewriter
│   ├── sql/                                   # Migrazioni Postgres
│   │   ├── bando_alter_seo_fields.sql
│   │   ├── bando_alter_filters_and_attachments.sql
│   │   ├── bando_alter_validation_v2.sql      # Validation + RLS
│   │   ├── bando_alter_data_pubblicazione_source.sql
│   │   ├── articles_alter_skill_fields.sql
│   │   ├── selezione_personale.sql
│   │   └── persona_jobs.sql
│   └── requirements.txt
│
├── scraper_bandi/                             # Pipeline bandi, venv proprio (scraper_bandi/README.md)
│   ├── app/                                   # CLI `python -m app <comando>`, step e skill SEO (seo_skill.py)
│   ├── tests/                                 # unittest (npm run test:py:bandi)
│   └── requirements.txt
│
├── scripts/                                   # Build helpers
│   ├── copy-credentials.js                    # Pre-build: copia google creds
│   └── copy-credentials-post-build.js
├── public/                                    # Asset statici
├── astro.config.mjs                           # Adapter node, host 0.0.0.0:80
├── tailwind.config.mjs                        # Tema custom
└── package.json
```

---

## API Endpoints

API pubblica in sola lettura: `/api/v1/*` (13 rotte in `src/pages/api/v1/`), documentata in `docs/api-v1.md` e su `/sviluppatori/api`.

### Articoli (Astro)

| Metodo | Endpoint | Descrizione |
|---|---|---|
| `POST` | `/api/articles/create` | Crea articolo |
| `PUT` | `/api/articles/[id]` | Aggiorna (usato da ArticleForm) |
| `DELETE` | `/api/articles/[id]` | Elimina per id |
| `POST` | `/api/articles/delete` | Elimina |
| `POST` | `/api/search` | Ricerca per titolo/sommario (ilike, max 10) |

### Generazione AI (Astro)

| Metodo | Endpoint | Descrizione |
|---|---|---|
| `POST` | `/api/generate-article` | Genera articolo da prompt (Claude Opus 4.6) |
| `POST` | `/api/generate-tags` | Tag SEO ottimizzati (GPT-4.1) |
| `POST` | `/api/generate-summary` | Riassunto titolo + sommario (GPT-4.1) |
| `POST` | `/api/generate-faq` | FAQ on-demand (GPT-4.1) |
| `POST` | `/api/tts/generate` | Audio TTS Google Cloud |

### Media & utility

| Metodo | Endpoint | Descrizione |
|---|---|---|
| `POST` | `/api/upload` | Upload immagini S3 con varianti |
| `POST` | `/api/upload-video` | Upload video singolo |
| `POST` | `/api/upload-video-chunk` | Upload video chunked |
| `GET` | `/api/upload-video-status` | Stato upload |
| `POST` | `/api/upload-from-url` | Upload da URL remoto |
| `POST` | `/api/contact` | Form contatti (con context bando opzionale) |
| `POST` | `/api/indexnow-notify` | Trigger IndexNow su pubblicazione |
| `POST` | `/api/check-api-status` | Stato della richiesta di accesso API (email + codice di verifica) |

### Backend FastAPI (`/api/news/*`)

| Metodo | Endpoint | Descrizione |
|---|---|---|
| `POST` | `/scrape_news` | Scraping fonti configurate |
| `POST` | `/api/news/analyze` | Analisi e raggruppamento |
| `GET` | `/summarize_news` | Riassunto batch |
| `POST` | `/api/news/reconstruct/{id}` | Ricostruzione articolo con Claude |
| `POST` | `/api/news/publish/{id}` | Pubblicazione sul CMS |
| `POST` | `/api/news/{id}/reset-generation` | Reset job stallato |
| `GET` | `/api/news/{id}/generation-info` | Info job in corso |
| `GET` | `/api/news/pending-review` | Lista in attesa di revisione |
| `POST` | `/api/articles/generate-with-persona` | Generazione con persona |
| `GET` | `/api/articles/generation-status/{job_id}` | Stato job persona |

---

## Installazione

### Prerequisiti

- **Node.js** ≥ 22.6 (`npm test` usa `--experimental-strip-types`)
- **Python** ≥ 3.10
- **PostgreSQL client** (psql) per migrazioni manuali
- Account Supabase (2 progetti separati: news + bandi)
- AWS S3 bucket
- Chiavi: OpenAI, Anthropic, Firecrawl, Google Cloud TTS

### 1. Clona il repository

```bash
git clone https://github.com/micheleDibi/news1.git
cd news1
```

### 2. Configura le variabili d'ambiente

```bash
cp .env.example .env
```

Compila `.env` (vedi sezione [Variabili d'ambiente](#variabili-dambiente)).

### 3. Frontend Astro

```bash
npm install
```

### 4. Backend FastAPI

```bash
cd backend
pip install -r requirements.txt
cd ..
```

La pipeline bandi usa un venv e un `.env` propri: `cd scraper_bandi && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt schedule && cp .env.example .env` (`schedule` serve al sender e non sta in `requirements.txt`; dettagli in `scraper_bandi/README.md`, Setup).

### 5. Migrazioni database

Sul **DB A** (news1) le migrazioni sono in `backend/sql/articles_alter_*.sql`, `backend/sql/selezione_personale.sql`, `backend/sql/persona_jobs.sql` e `backend/app/interpelli_tables.sql`.

Sul **DB B** (bandi) le migrazioni correnti sono i file idempotenti `backend/sql/bando_v11_*.sql` (ognuno con il suo `_rollback`): si applicano a mano nello SQL Editor del pannello Supabase B, nell'ordine scritto nelle intestazioni, e dopo ognuna va riavviato `edunews-bandi-sender` (`docs/bandi-monitor/RIPRESA.md` §3.5). Quali sono applicate (al 25/09/2026 mancano la 06 e la 07) e le regole: RIPRESA §1 e §7.

### 7. Avvio in sviluppo

**Frontend** (porta 80 anche in dev, da `server.port` in `astro.config.mjs`; il backend si aspetta la 4321, cioe' il CORS e il default di `FRONTEND_URL` in `backend/app/main.py`, che si ottiene con `npm run dev -- --port 4321`):
```bash
npm run dev
```

**Backend FastAPI**:
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

> In produzione girare `uvicorn` **senza `--reload`** — il `reload=True` nel `__main__` e solo per dev.

**Bandi** — pipeline in `scraper_bandi/` (venv proprio), schedulata da `backend/app/bandi_sender.py` alle 00/06/12/18; un singolo step a mano:
```bash
cd scraper_bandi
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app <comando> --dry-run --limit N
```
Comandi in `docs/bandi-monitor/RIPRESA.md` §6; senza `--dry-run` scrivono sul DB vero (ma senza `--attivo` non toccano colonne pubbliche).

---

## Variabili d'ambiente

File `.env` nella root del progetto (vedi `.env.example` per il template completo).

```env
# === DB principale (news1) ===
PUBLIC_SUPABASE_URL="https://<id>.supabase.co"
PUBLIC_SUPABASE_ANON_KEY="..."

# === DB bandi (Supabase B) ===
# scraper_bandi e sender bandi: service-role per scrittura (letti da scraper_bandi/.env, poi dal .env della cartella di lavoro)
SUPABASE_URL_BANDI="https://<id-bandi>.supabase.co"
SUPABASE_SERVICE_KEY_BANDI="..."
# Frontend: anon key + RLS lettura
PUBLIC_SUPABASE_BANDI_URL="https://<id-bandi>.supabase.co"
PUBLIC_SUPABASE_BANDI_ANON_KEY="..."

# === AI ===
OPENAI_API_KEY="sk-proj-..."
ANTHROPIC_API_KEY="sk-ant-..."

# === Scraping ===
FIRECRAWL_API_KEY="fc-..."     # Usata da news scraping + scraper_bandi (che la legge da scraper_bandi/.env)

# === Storage ===
AWS_ACCESS_KEY_ID="..."
AWS_SECRET_ACCESS_KEY="..."
AWS_REGION="eu-north-1"
AWS_BUCKET_NAME="..."

# === Google TTS ===
CREDENTIALS_GOOGLE_SPEECH="google-credentials.json"

# === Sicurezza ===
API_SECRET_KEY="..."
PUBLIC_API_SECRET_KEY="..."

# === Social ===
PUBLIC_FACEBOOK_PAGE_ID="..."
PUBLIC_FACEBOOK_ACCESS_TOKEN="..."

# === IndexNow ===
INDEXNOW_API_KEY="..."

# === Backend Python ===
BACKEND_URL="http://localhost:8000"

# === Web Bot Auth ===
WEB_BOT_AUTH_PRIVATE_KEY="..."  # chiave privata Ed25519 (PKCS8 PEM); per ora inutilizzata

# === API pubblica /api/v1 (facoltative) ===
API_V1_FIDUCIA_IP=cloudflare     # cloudflare (default) | nginx | diretta
API_V1_RL_CAPACITA=60            # richieste massime per client (token bucket)
API_V1_RL_RICARICA=1             # gettoni ricaricati al secondo

# === Bandi ===
# La pipeline legge scraper_bandi/.env (variabili in scraper_bandi/app/settings.py; RESOLVER_MODALITA e MONITOR_* in RIPRESA §1).
# Frontend, facoltative: BANDI_FONTE_LETTURA (bando | bando_pubblico) e BANDI_STATI_ESTESI (true solo dopo la migrazione 06).
# DATABASE_URL e BANDI_SKILL_* compaiono in .env.example ma nessun codice le legge.
```

> ⚠️ **Mai committare `.env` con segreti reali**. La chiave `SUPABASE_SERVICE_KEY_BANDI` da accesso pieno al DB bandi e va usata SOLO lato backend.

---

## Build & Deploy

### Build di produzione

```bash
npm run build
```

Il pre-build (`scripts/copy-credentials.js`) e il post-build (`scripts/copy-credentials-post-build.js`) copiano le credenziali Google Cloud del TTS da `src/pages/api/tts/google-credentials.json` ed escono con errore se il file manca: in locale, senza quel file, `npx astro build` (vedi `docs/api-v1.md`).

### Configurazione server Astro

```js
// astro.config.mjs
adapter: node({ mode: "standalone" }),
server: { host: "0.0.0.0", port: 80 },
security: { checkOrigin: false }  // dietro Cloudflare + nginx
```

### Servizi systemd (esempio)

In produzione tipicamente (nomi delle unit [DA VERIFICARE]; `edunews-bandi-sender` e' confermato da `docs/bandi-monitor/RIPRESA.md`):

- `edunews-frontend.service` — `npm run build` + node entry
- `edunews-backend.service` — `uvicorn app.main:app` (no `--reload`)
- `edunews-news-sender.service` — `python -m app.sender`
- `edunews-bandi-sender.service` — `scraper_bandi/.venv/bin/python -m backend.app.bandi_sender` dalla root del repo (esempio in `scraper_bandi/README.md`); **attivo**, giri alle 00/06/12/18 (`docs/bandi-monitor/RIPRESA.md` §2)
- `edunews-interpelli-sender.service` — `python -m app.interpelli_sender`
- `edunews-selezione-sender.service` — `python -m app.selezione_personale_sender`

---

## Database

### DB A — news1 (Supabase)

| Tabella | Descrizione |
|---|---|
| `articles` | Articoli con contenuto, metadati, tag, FAQ, media, audio |
| `profiles` | Profili utente con ruoli (admin/direttore/redattore/giornalista) |
| `categories` | Categorie primarie con colori e keyword |
| `secondary_categories` | Sottocategorie collegate alle primarie |
| `forum_messages` | Commenti e discussioni per articolo |
| `podcasts` | Episodi podcast |
| `interpelli` | Interpelli delle scuole (docenti, ATA, DSGA) da scuolainterpelli.it |
| `selezione_personale` | Concorsi e selezioni |
| `persona_jobs` | Job persistence per persona rewriter |

### DB B — bandi (Supabase con RLS)

| Tabella | Descrizione |
|---|---|
| `bando` | Tabella principale (campi scraper + SEO skill + validation) |
| `fonte` | Fonti istituzionali monitorate dallo scraper |
| `regioni`, `bando_regioni` | Lookup geografiche + junction |
| `settori`, `bando_settori` | Settori di intervento |
| `beneficiari`, `bando_beneficiari` | Beneficiari ammissibili |
| `codici_ateco`, `bando_codici_ateco` | Classificazione ATECO |
| `programmi` | Programmi di finanziamento (FK `bando.programma_id`, nessuna junction) |
| `tipologie_bando` | Tipologia del bando (FK `bando.tipologia_bando_id`) |
| `modalita_erogazione` | Modalita erogazione (sussidio, prestito, ecc; FK `bando.modalita_erogazione_id`) |

**RLS attiva (v9)**: la anon key legge solo le righe con `stato_processing = 'completed' AND slug IS NOT NULL`; la migrazione 07, non ancora applicata, la spostera' sul flag `pubblicato`. Tabelle di servizio v11 (`bando_link`, `bando_evento`, `bando_controllo`, `bando_fusione`, `bando_slug_storico`, `dominio_ufficiale`, `pipeline_run`, `pipeline_lock`, `fonte_run`), vista `bando_pubblico` e garanzie verso BandoFit: `docs/contratto-db-bandi.md`; migrazioni applicate: `docs/bandi-monitor/RIPRESA.md` §1.

---

## Categorie editoriali

Ogni categoria ha un colore identificativo proprio:

| Categoria | Focus |
|---|---|
| **Scuola** | Notizie scolastiche, riforme, didattica |
| **Universita** | Atenei, ricerca accademica, orientamento |
| **Formazione** | Formazione professionale e continua |
| **Lavoro** | Mercato del lavoro, occupazione |
| **Ricerca** | Scoperte e innovazione accademica |
| **Cultura** | Eventi culturali, mostre, iniziative |
| **Mondo** | Istruzione internazionale |
| **Editoriali** | Opinioni e approfondimenti |
| **Bandi** | Concorsi, gare e opportunita di finanziamento |
| **Interpelli** | Interpelli delle scuole per supplenze (docenti, ATA, DSGA) |
| **Selezione Personale** | Concorsi e selezioni della Pubblica Amministrazione (portale inPA) |

---

## Documentazione aggiuntiva

- `docs/bandi-monitor/RIPRESA.md` — stato attuale dei bandi, verifiche e comandi (`AVANZAMENTO.md`: cronaca dell'intervento)
- `docs/contratto-db-bandi.md` — contratto del DB bandi per chi legge con la anon key (BandoFit)
- `docs/api-v1.md` — API pubblica `/api/v1`
- `docs/analisi-seo-elenchi.md`, `docs/report-seo-elenchi.md` — analisi e intervento SEO sulle pagine elenco
- `scraper_bandi/README.md` — pipeline bandi, setup del venv
- `backend/skill/SKILL.md` — skill ricostruzione articoli news
- `backend/sql/bando_v4_collapse.sql` — migrazione state machine v4
- `backend/sql/bando_v5_purge_legacy_scraper.sql` — drop tabelle scraper-internal

---

## Licenza

Progetto proprietario. Tutti i diritti riservati.

---

<p align="center">
  <strong>EduNews24</strong> &mdash; L'informazione che educa.
</p>
