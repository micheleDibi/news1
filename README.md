<p align="center">
  <img src="public/logo.png" alt="EduNews24 Logo" width="280" />
</p>

<h1 align="center">EduNews24</h1>

<p align="center">
  <strong>Piattaforma editoriale intelligente per il mondo dell'istruzione italiana</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Astro-5.3-FF5D01?logo=astro&logoColor=white" alt="Astro" />
  <img src="https://img.shields.io/badge/React-18.2-61DAFB?logo=react&logoColor=white" alt="React" />
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
- **Sezione Bandi** — pipeline a due fasi che ingerisce bandi di finanziamento da OpenCoesione e fonti istituzionali, arricchiti da una skill Claude dedicata che genera contenuto SEO ed estrae i campi strutturati autoritativi.
- **Interpelli parlamentari** — monitoraggio automatico delle interrogazioni di Camera e Senato.
- **Selezione Personale** — concorsi e selezioni del comparto istruzione.
- **EU funding** — focus su Italia Domani e fondi europei.

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
│  FASE 1 (Python) │         │  Claude Opus 4.7           │
│  Scraper OpenCo. │         │   - Ricostruzione articoli │
│  + Firecrawl     │         │   - Skill bandi SEO        │
│  → Supabase B    │         │   - Persona rewriter       │
│                  │         │                            │
│  FASE 2 (Claude  │         │  OpenAI GPT-4.1            │
│  Agent SDK)      │         │   - Tag/Summary/FAQ        │
│  bandi-seo-      │         │   - Generazione articoli   │
│  enricher        │         │                            │
│  → arricchimento │         │  Firecrawl                 │
│  + verdetto      │         │   - Scraping stealth/auto  │
│                  │         │                            │
│                  │         │  Google Cloud TTS          │
│                  │         │   - Audio articoli         │
└──────────────────┘         └────────────────────────────┘
```

### Architettura dual-database

| DB | Provider | Contenuto | Accesso frontend |
|---|---|---|---|
| **DB A — `news1`** | Supabase | Articoli, profili, categorie, podcast, interpelli, selezione personale | anon key |
| **DB B — `bandi`** | Supabase | Tabella `bando` + lookup (regioni, settori, beneficiari, ateco, programmi) | anon key + RLS (`is_bando_confermato = true`) |

Tutta la scrittura su DB B avviene **solo** dal backend con service-role key. Il front-end legge in sola lettura via anon key e Row Level Security garantisce che solo bandi confermati dalla skill siano visibili.

---

## Tech Stack

### Frontend

| Tecnologia | Versione | Utilizzo |
|---|---|---|
| **Astro** | 5.3 | Framework SSR con `@astrojs/node` standalone adapter |
| **React** | 18.2 | Componenti interattivi (editor, dashboard, form) |
| **TailwindCSS** | 3.4 | Utility-first + plugin forms/typography |
| **TipTap** | 2.11 | Editor rich-text |
| **React Hook Form** | 7.51 | Form con validazione |
| **Splide** | 4.1 | Carousel e auto-scroll |
| **@supabase/supabase-js** | 2.39 | Client DB sia per news che per bandi |
| **@anthropic-ai/sdk** | 0.78 | SDK Claude lato edge per `generate-article` |

### Backend principale (`/backend`)

| Tecnologia | Utilizzo |
|---|---|
| **FastAPI** | API REST per scraping news, ricostruzione, sender pipeline |
| **SQLAlchemy** | ORM news (staging SQLite) |
| **Pydantic** | Schemi I/O |
| **Uvicorn** | Server ASGI (no `--reload` in prod) |
| **claude-agent-sdk** | Esecuzione in-process delle skill (news + bandi) |
| **schedule** | Scheduler dei sender (news, bandi, interpelli, selezione personale) |
| **firecrawl-py** | Scraping con bypass anti-bot |
| **loguru** | Logging strutturato |
| **boto3** | Upload media su S3 |
| **google-cloud-texttospeech** | Generazione audio articoli |

### Backend bandi — scraping (`/Scraper-gerarchico-bandi-OpenCoesione-Backend-Python`)

| Modulo | Utilizzo |
|---|---|
| **Scraper gerarchico** | Crawl fonti → discovery bandi → parsing dettaglio |
| **Firecrawl client** | Singleton stealth → auto → httpx fallback (logging stdlib, NON loguru) |
| **OCR / page detail** | Estrazione testo da PDF e pagine HTML |
| **AI classification** | OpenAI gpt-4o-mini per pre-classificazione bando |
| **pydantic-settings** | Config env-driven |

### Skill bandi (`/bandi-seo-enricher`)

Skill Claude single-bando invocata in-process via Claude Agent SDK. Dato un `link_bando` + hint dominio (passato dall'orchestrator dal DB scraper, **mai da file**), produce **UN JSON 1:1** con la tabella `bando`:

- Verdetto `is_valid_bando` (autoritativo, filtra le pagine indice/ricerca/categoria)
- Campi strutturati: scadenza + `data_scadenza_source`, data pubblicazione + `data_pubblicazione_source`, importo, beneficiari, link candidatura **verificato** (no fallback a `source_url`)
- Contenuto editoriale flash o guida con FAQ, intestazione, sezioni
- Categoria di rifiuto strutturata: `index_page`, `search_results`, `category_page`, `expired_archive`, `not_a_funding_call`, `unreachable`

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
- **Generazione articoli da prompt** con ricerca web (Firecrawl + OpenAI)
- **Skill `bandi-seo-enricher`** — Claude Agent SDK in-process, system prompt sandboxato (file ausiliari in `/tmp/`)
- **Persona runner** — generazione articoli con persona giornalistica e job persistence

### SEO & dati strutturati
- Sitemap XML dinamiche (articoli, categorie, video, news recenti, interpelli, selezione personale)
- JSON-LD `Article`, `BreadcrumbList`, `FAQPage`
- Pagine AMP
- Meta tag Open Graph + Twitter Card
- robots.txt con rate-limit per bot aggressivi
- URL slug-friendly
- **IndexNow** — notifica push a Bing/Yandex su pubblicazione

### Pipeline news automatizzata
- Scraping Selenium + BeautifulSoup + Firecrawl
- Parsing feed RSS
- Pipeline: scraping → analisi → ricostruzione AI → revisione manuale → pubblicazione
- Scheduler `app/sender.py` configurabile per fasce orarie
- Anti-duplicazione

### Pipeline bandi (a due fasi)
Vedi la sezione [Pipeline Bandi](#pipeline-bandi) sotto per il dettaglio.

### Social & engagement
- Auto-posting Facebook con hashtag (testo del post dal sottotitolo, non dal titolo)
- Sistema forum/commenti per articolo
- Profili autore con pagine dedicate
- Pagina team editoriale

### Pannello amministrazione
- Dashboard gestione articoli, utenti, categorie, podcast
- Sistema permessi role-based (admin, editore, redattore)
- Log attivita
- Strumenti automazione news (scraping → riassunto → ricostruzione → pubblicazione)
- Creazione utenti in batch
- Plugin requests management
- API access registration

### Sezioni specializzate
- **Interpelli parlamentari** — `/interpelli`, `/interpelli/[slug]` con sender dedicato
- **Bandi e Gare** — `/bandi`, `/bandi/[slug]` con filtri avanzati multi-select
- **Finanziamenti EU** — `/eu-funding` per Italia Domani e fondi europei
- **Selezione Personale** — `/selezione-personale`, `/selezione-personale/[slug]` concorsi del comparto
- **Podcast** — pubblicazione episodi audio editoriali
- **Linkinbio** — pagina aggregatrice per social

---

## Pipeline Bandi

La sezione Bandi e il fiore all'occhiello della piattaforma e merita una descrizione dedicata.

### Fase 1 — Scraping ed enrichment (Python)

Modulo: `Scraper-gerarchico-bandi-OpenCoesione-Backend-Python/`

```
┌──────────────────┐    ┌────────────────────┐    ┌─────────────────────┐
│ Fonti istituz.   │    │  Scraper L2        │    │  Classification AI  │
│ + OpenCoesione   │───►│  Firecrawl primary │───►│  gpt-4o-mini        │
│ (registry)       │    │  httpx fallback    │    │  pre-classificazione│
└──────────────────┘    └────────────────────┘    └──────────┬──────────┘
                                                              │
                                                              ▼
                                            ┌─────────────────────────────┐
                                            │  Supabase B — tabella       │
                                            │  bando (status='queued')    │
                                            └─────────────────────────────┘
```

**Scraping**: `firecrawl_client.py` espone un singleton con strategia stealth → auto → httpx, logging stdlib (`logging.getLogger(__name__)` con placeholder `%s`, NON loguru — distinzione importante per evitare ImportError). Path-filter espliciti escludono pagine indice/ricerca/categoria (`/ricerca`, `/categoria/`, `/elenco-bandi`, `/archivio`, ecc).

**Classification**: `classification_service.py` con `_url_looks_like_index_page` rifiuta gli URL che assomigliano a pagine non-bando; rimosso il fallback keyword "bando/voucher" che dava troppi falsi positivi.

**Parsing**: `bando_parser.py` rifiuta date generiche in posizione finale (causa di scadenze sbagliate tipo "21/12/2015" su bandi 2026); estrae `data_scadenza_raw` per audit.

### Fase 2 — Skill SEO bandi (Claude)

Modulo: `bandi-seo-enricher/` invocato da `backend/skill_bandi/scripts/run_agent_sdk_json_bandi.py` via Claude Agent SDK.

```
┌──────────────────────┐
│ Supabase B           │
│ status='queued'      │
└──────────┬───────────┘
           │ build_hint_from_bando()
           │ (denormalizza FK → nomi)
           ▼
┌──────────────────────────────────────────────────────┐
│  Skill bandi-seo-enricher (Claude Opus 4.7)          │
│                                                      │
│  STEP 0  Lettura references obbligatorie             │
│  STEP 1  Hint dal prompt (NO sources.json!)          │
│  STEP 2  Firecrawl scrape pagina bando               │
│  STEP 2.5 Verdetto is_valid_bando + rejection_cat    │
│  STEP 3  Lettura PDF allegati                        │
│  STEP 4  Estrazione campi (no inventare!)            │
│  STEP 5  link_candidatura verificato (no fallback)   │
│  STEP 6  data_scadenza + scadenza_source enum        │
│  STEP 6b data_pubblicazione + pubblicazione_source   │
│  STEP 7  Generazione contenuto editoriale            │
│  STEP 8  JSON output 1:1 con tabella bando           │
└──────────┬───────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────┐
│  backend/app/bandi.py::update_bando_from_payload     │
│                                                      │
│  • is_bando_confermato ← skill verdict (autoritativo)│
│  • data_scadenza ← skill SE source ∈                 │
│      {official_pdf, official_page}                   │
│  • data_pubblicazione ← stessa logica                │
│  • link_candidatura_verified flag                    │
│  • validation_reason + rejection_category persistiti │
│  • Valori pre-skill salvati in raw_data per audit    │
└──────────┬───────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────┐
│  Frontend /bandi e /bandi/[slug]                     │
│  • RLS bando_public_read filtra is_bando_confermato  │
│  • Ordinamento data_pubblicazione DESC nullslast     │
│  • CTA "Apri pagina ufficiale" o link_candidatura    │
└──────────────────────────────────────────────────────┘
```

### Colonne chiave su `bando` (DB B)

| Colonna | Origine | Note |
|---|---|---|
| `is_bando_confermato` | Skill (STEP 2.5) | RLS filter — solo `true` visibile al frontend |
| `validation_reason` | Skill | Testo libero motivazione |
| `rejection_category` | Skill | Enum: `index_page \| search_results \| category_page \| expired_archive \| not_a_funding_call \| unreachable` |
| `data_scadenza_source` | Skill (STEP 6) | Enum: `official_pdf \| official_page \| inferred \| missing \| scraper_fallback` |
| `data_pubblicazione_source` | Skill (STEP 6b) | Stesso enum |
| `link_candidatura_verified` | Skill (STEP 5) | Boolean — se false, frontend mostra solo "Apri pagina ufficiale" |
| `skill_processing_status` | Backend | `queued \| processing \| completed \| failed` |

### Orchestrazione

Sender: `backend/app/bandi_sender.py` — schedule:
- Run completo scraper ogni giorno (compreso AI worker drain)
- Run skill-only ogni 30 min (batch da `BANDI_SKILL_BATCH_SIZE`, default 10)
- Retry pending fonti ogni 4h

Tutto isolato: il subprocess scraper riceve un env pulito (`_scraper_subprocess_env`) per non leakare credenziali del backend news1.

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
│   │   │   ├── eu-funding/                    # API EU funding
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
│   │   ├── eu-funding/                        # Sezione EU
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
│   │   ├── bandi.py                           # Orchestrazione bandi (hint, override)
│   │   ├── bandi_sender.py                    # Scheduler pipeline bandi
│   │   ├── bandi_skill_runner.py              # Invocazione skill bandi
│   │   ├── bandi_supabase.py                  # Client Supabase B
│   │   ├── interpelli.py, interpelli_sender.py
│   │   ├── selezione_personale.py, selezione_personale_sender.py
│   │   ├── persona_runner.py                  # Persona rewriter job
│   │   ├── skill_runner.py                    # Runner skill news
│   │   ├── google_indexing.py, indexnow.py
│   │   ├── variables_edunews.py               # Prompt + costanti modello
│   │   ├── enhanced_scraper.py                # Scraper avanzato news
│   │   └── ScrapingBandiEuropeiFinal/         # Scraper EU funding
│   ├── skill/                                 # Skill ricostruzione articoli
│   │   ├── SKILL.md
│   │   ├── references/                        # Linee guida editoriali
│   │   └── scripts/                           # Firecrawl + JSON generator
│   ├── skill_bandi/
│   │   └── scripts/run_agent_sdk_json_bandi.py # Wrapper skill bandi
│   ├── news-angle-rewriter-persona/           # Skill persona rewriter
│   ├── sql/                                   # Migrazioni Postgres
│   │   ├── bando_alter_seo_fields.sql
│   │   ├── bando_alter_filters_and_attachments.sql
│   │   ├── bando_alter_validation_v2.sql      # Validation + RLS
│   │   ├── bando_alter_data_pubblicazione_source.sql
│   │   ├── articles_alter_skill_fields.sql
│   │   ├── interpelli_tables.sql
│   │   ├── selezione_personale.sql
│   │   └── persona_jobs.sql
│   └── requirements.txt
│
├── Scraper-gerarchico-bandi-OpenCoesione-Backend-Python/   # Scraper bandi (sub-progetto)
│   ├── app/
│   │   ├── cli.py, scheduler.py
│   │   ├── config/, db/, models/, repos/
│   │   ├── scrapers/
│   │   │   ├── firecrawl_client.py            # Singleton stealth/auto/httpx
│   │   │   ├── fonte_level2.py                # Crawl L2 con deny-list
│   │   │   ├── root_discovery.py
│   │   │   └── run_*.py                       # Entrypoint CLI
│   │   ├── parsers/bando_parser.py            # Estrazione campi grezzi
│   │   ├── services/classification_service.py # Pre-classificazione AI
│   │   ├── ocr/page_detail_fetcher.py         # Estrazione pagina + markdown
│   │   ├── ai/                                # Pipeline AI gpt-4o-mini
│   │   └── queues/
│   ├── docs/                                  # Documentazione operativa
│   ├── requirements.txt
│   └── .env.example
│
├── bandi-seo-enricher/                        # Skill Claude single-bando
│   ├── SKILL.md
│   ├── references/
│   │   ├── bando_data_extraction.md
│   │   ├── article_structure.md
│   │   ├── seo_guidelines.md
│   │   └── blacklist_frasi.md
│   ├── scripts/
│   │   ├── firecrawl_scrape.py                # Wrapper Firecrawl per skill
│   │   ├── extract_bando_fields.py            # Regex helpers (publication ctx)
│   │   └── generate_json_output.py            # Validatore enum + schema
│   └── output/
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

### Articoli (Astro)

| Metodo | Endpoint | Descrizione |
|---|---|---|
| `POST` | `/api/articles/create` | Crea articolo |
| `GET` | `/api/articles/index` | Lista paginata |
| `GET` | `/api/articles/[id]` | Dettaglio |
| `PUT` | `/api/articles/[id]/update` | Aggiorna |
| `DELETE` | `/api/articles/delete` | Elimina |
| `GET` | `/api/search` | Ricerca full-text |

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
| `GET` | `/api/check-api-status` | Health check |

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

- **Node.js** ≥ 18
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

### 5. Scraper bandi (sub-progetto)

Il scraper bandi gira in un venv dedicato per isolare le dipendenze:

```bash
cd Scraper-gerarchico-bandi-OpenCoesione-Backend-Python
python -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env
# editare .env e settare FIRECRAWL_API_KEY + credenziali Supabase B
cd ..
```

### 6. Migrazioni database

Sul **DB A** (news1) le migrazioni sono in `backend/sql/articles_alter_*.sql` e `interpelli_tables.sql`/`selezione_personale.sql`/`persona_jobs.sql`.

Sul **DB B** (bandi):

```bash
export DATABASE_URL_BANDI='postgresql://postgres:<PWD>@db.<id>.supabase.co:5432/postgres'

psql "$DATABASE_URL_BANDI" -f backend/sql/bando_alter_seo_fields.sql
psql "$DATABASE_URL_BANDI" -f backend/sql/bando_alter_filters_and_attachments.sql
psql "$DATABASE_URL_BANDI" -f backend/sql/bando_alter_validation_v2.sql
psql "$DATABASE_URL_BANDI" -f backend/sql/bando_alter_data_pubblicazione_source.sql
```

In alternativa: incolla i file SQL nello SQL Editor del pannello Supabase B.

### 7. Avvio in sviluppo

**Frontend** (porta 4321 in dev):
```bash
npm run dev
```

**Backend FastAPI**:
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

> In produzione girare `uvicorn` **senza `--reload`** — il `reload=True` nel `__main__` e solo per dev.

**Bandi sender** (scheduler):
```bash
cd backend
python -m app.bandi_sender
```

---

## Variabili d'ambiente

File `.env` nella root del progetto (vedi `.env.example` per il template completo).

```env
# === DB principale (news1) ===
PUBLIC_SUPABASE_URL="https://<id>.supabase.co"
PUBLIC_SUPABASE_ANON_KEY="..."

# === DB bandi (Supabase B) ===
# Backend: service-role per scrittura
SUPABASE_URL_BANDI="https://<id-bandi>.supabase.co"
SUPABASE_SERVICE_KEY_BANDI="..."
# Frontend: anon key + RLS lettura
PUBLIC_SUPABASE_BANDI_URL="https://<id-bandi>.supabase.co"
PUBLIC_SUPABASE_BANDI_ANON_KEY="..."

# === AI ===
OPENAI_API_KEY="sk-proj-..."
ANTHROPIC_API_KEY="sk-ant-..."

# === Scraping ===
FIRECRAWL_API_KEY="fc-..."     # Usata anche dal scraper bandi

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

# === Bandi: subprocess scraper ===
BANDI_SCRAPER_DIR="/root/projects/news1/Scraper-gerarchico-bandi-OpenCoesione-Backend-Python"
BANDI_SCRAPER_PYTHON="/root/projects/news1/Scraper-gerarchico-bandi-OpenCoesione-Backend-Python/venv/bin/python"
BANDI_SCRAPER_RUN_LIMIT=""    # vuoto = scraping completo

# === Bandi: skill enrichment ===
BANDI_SKILL_BATCH_SIZE=10
BANDI_SKILL_MAX_ATTEMPTS=3
```

> ⚠️ **Mai committare `.env` con segreti reali**. La chiave `SUPABASE_SERVICE_KEY_BANDI` da accesso pieno al DB bandi e va usata SOLO lato backend.

---

## Build & Deploy

### Build di produzione

```bash
npm run build
```

Il pre-build copia automaticamente le credenziali Google Cloud necessarie per il TTS (`scripts/copy-credentials.js`).

### Configurazione server Astro

```js
// astro.config.mjs
adapter: node({ mode: "standalone" }),
server: { host: "0.0.0.0", port: 80 },
security: { checkOrigin: false }  // dietro Cloudflare + nginx
```

### Servizi systemd (esempio)

In produzione tipicamente:

- `edunews-frontend.service` — `npm run build` + node entry
- `edunews-backend.service` — `uvicorn app.main:app` (no `--reload`)
- `edunews-news-sender.service` — `python -m app.sender`
- `edunews-bandi-sender.service` — `python -m app.bandi_sender`
- `edunews-interpelli-sender.service` — `python -m app.interpelli_sender`
- `edunews-selezione-sender.service` — `python -m app.selezione_personale_sender`

---

## Database

### DB A — news1 (Supabase)

| Tabella | Descrizione |
|---|---|
| `articles` | Articoli con contenuto, metadati, tag, FAQ, media, audio |
| `profiles` | Profili utente con ruoli (admin/editore/redattore) |
| `categories` | Categorie primarie con colori e keyword |
| `secondary_categories` | Sottocategorie collegate alle primarie |
| `forum_messages` | Commenti e discussioni per articolo |
| `podcasts` | Episodi podcast |
| `interpelli` | Interpelli parlamentari Camera/Senato |
| `selezione_personale` | Concorsi e selezioni |
| `persona_jobs` | Job persistence per persona rewriter |

### DB B — bandi (Supabase con RLS)

| Tabella | Descrizione |
|---|---|
| `bando` | Tabella principale (campi scraper + SEO skill + validation) |
| `fonte` | Fonti istituzionali monitorate dallo scraper |
| `regione`, `bando_regione` | Lookup geografiche + junction |
| `settore`, `bando_settore` | Settori di intervento |
| `beneficiario`, `bando_beneficiario` | Beneficiari ammissibili |
| `codice_ateco`, `bando_ateco` | Classificazione ATECO |
| `programma`, `bando_programma` | Programmi di finanziamento |
| `modalita_erogazione` | Modalita erogazione (sussidio, prestito, ecc) |

**RLS attiva**: policy `bando_public_read` filtra `is_bando_confermato IS TRUE` per l'anon key — il frontend non vede mai bandi rigettati dalla skill.

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
| **Interpelli** | Interrogazioni parlamentari Camera/Senato |
| **Selezione Personale** | Concorsi del comparto istruzione |
| **EU Funding** | Italia Domani e fondi europei |

---

## Documentazione aggiuntiva

- `Scraper-gerarchico-bandi-OpenCoesione-Backend-Python/README.md` — comandi CLI scraper, scheduler, AI worker
- `Scraper-gerarchico-bandi-OpenCoesione-Backend-Python/docs/avvio_manuale_scraper.md` — procedura operativa completa
- `bandi-seo-enricher/SKILL.md` — manifest skill bandi (workflow + regole critiche)
- `bandi-seo-enricher/references/` — linee guida estrazione campi, struttura articoli, SEO, blacklist
- `backend/skill/SKILL.md` — skill ricostruzione articoli news

---

## Licenza

Progetto proprietario. Tutti i diritti riservati.

---

<p align="center">
  <strong>EduNews24</strong> &mdash; L'informazione che educa.
</p>
