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
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Supabase-PostgreSQL-3ECF8E?logo=supabase&logoColor=white" alt="Supabase" />
  <img src="https://img.shields.io/badge/TailwindCSS-3.4-06B6D4?logo=tailwindcss&logoColor=white" alt="TailwindCSS" />
  <img src="https://img.shields.io/badge/Claude-Opus_4-D4A574?logo=anthropic&logoColor=white" alt="Claude" />
  <img src="https://img.shields.io/badge/OpenAI-GPT_4.1-412991?logo=openai&logoColor=white" alt="OpenAI" />
</p>

---

## Panoramica

**EduNews24** e una testata giornalistica online dedicata al mondo della scuola, dell'universita e della formazione in Italia. La piattaforma combina un CMS editoriale completo con strumenti di intelligenza artificiale per la creazione, ricostruzione e ottimizzazione dei contenuti.

Il sistema gestisce l'intero ciclo di vita di un articolo: dallo scraping automatizzato delle fonti, alla ricostruzione AI del contenuto, fino alla pubblicazione con SEO ottimizzata, audio text-to-speech e condivisione social.

---

## Architettura

```
                    ┌─────────────────────────────────────────┐
                    │              EduNews24                   │
                    └──────────────────┬──────────────────────┘
                                       │
                 ┌─────────────────────┼─────────────────────┐
                 │                     │                     │
        ┌────────▼────────┐   ┌────────▼────────┐   ┌───────▼────────┐
        │    Frontend      │   │     Backend     │   │    Storage     │
        │   Astro + React  │   │    FastAPI      │   │                │
        │   TailwindCSS    │   │    Python       │   │  Supabase (DB) │
        │   TipTap Editor  │   │    SQLAlchemy   │   │  AWS S3 (Media)│
        └────────┬─────────┘   └────────┬────────┘   └───────┬────────┘
                 │                      │                     │
        ┌────────▼──────────────────────▼─────────────────────▼───────┐
        │                      Integrazioni AI                        │
        │                                                             │
        │  Claude (Anthropic)     OpenAI (GPT-4.1)     Google Cloud  │
        │  - Ricostruzione        - Tag SEO             - TTS Audio  │
        │    articoli             - Riassunti                         │
        │  - Analisi contenuti    - FAQ                               │
        │  - Keyword SEO          - Generazione                       │
        └─────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

### Frontend

| Tecnologia | Versione | Utilizzo |
|---|---|---|
| **Astro** | 5.3 | Framework SSR/SSG con rendering ibrido |
| **React** | 18.2 | Componenti interattivi (editor, form, dashboard) |
| **TailwindCSS** | 3.4 | Sistema di design utility-first |
| **TipTap** | 2.x | Editor rich-text per la creazione articoli |
| **React Hook Form** | - | Gestione form con validazione |
| **Splide** | 4.1 | Carousel e slider |

### Backend

| Tecnologia | Utilizzo |
|---|---|
| **FastAPI** | API REST per scraping, ricostruzione e automazione |
| **SQLAlchemy** | ORM per il database di staging delle news |
| **Pydantic** | Validazione dati e schemi API |
| **Uvicorn** | Server ASGI |

### AI & Cloud

| Servizio | Utilizzo |
|---|---|
| **Claude (Anthropic)** | Ricostruzione articoli, analisi contenuti, keyword SEO |
| **OpenAI GPT-4.1** | Generazione tag, riassunti, FAQ, articoli |
| **Google Cloud TTS** | Sintesi vocale per versione audio degli articoli |
| **Supabase** | Database PostgreSQL, autenticazione, real-time |
| **AWS S3** | Storage immagini e media con varianti responsive |

---

## Funzionalita Principali

### Gestione Articoli
- Editor rich-text con TipTap (grassetto, corsivo, link, immagini, liste)
- Modalita modifica e anteprima
- Sistema bozze/pubblicazione con permessi granulari
- Categorie primarie e secondarie
- Upload immagini su S3 con generazione automatica varianti responsive (320px - 1280px)
- Supporto video con tracking durata
- Versione audio con Google Cloud Text-to-Speech
- Form di contatto integrabile per articolo

### Intelligenza Artificiale
- **Ricostruzione articoli** con Claude Opus - riscrittura completa con tono giornalistico professionale
- **Generazione tag SEO** (5-8 keyword ottimizzate) via OpenAI
- **Generazione riassunti** (titolo + sommario) via OpenAI
- **Generazione FAQ on-demand** (4-6 domande) via OpenAI con sezione dedicata
- **Generazione articoli da prompt** con ricerca web integrata
- Indice automatico con link alle sezioni
- Interlink automatici con articoli correlati

### SEO & Structured Data
- Sitemap XML dinamiche (articoli, categorie, video, news recenti)
- Dati strutturati JSON-LD (Article, BreadcrumbList, FAQPage)
- Pagine AMP per Google
- Meta tag Open Graph e Twitter Card
- robots.txt con rate limiting per bot aggressivi
- URL SEO-friendly con slug ottimizzati

### Automazione Contenuti
- Scraping automatizzato da fonti multiple (Selenium, BeautifulSoup, Firecrawl)
- Parsing feed RSS
- Pipeline: scraping &rarr; analisi &rarr; ricostruzione AI &rarr; revisione &rarr; pubblicazione
- Scheduler configurabile per fasce orarie

### Social & Engagement
- Pubblicazione automatica su Facebook con hashtag
- Sistema forum/commenti per articolo
- Profili autore con pagine dedicate
- Pagina team editoriale

### Pannello Amministrazione
- Dashboard completa per gestione articoli, utenti, categorie
- Sistema permessi role-based (admin, editore, redattore)
- Log attivita
- Gestione podcast
- Strumenti automazione news
- Creazione utenti in batch

### Sezioni Specializzate
- **Interpelli parlamentari** - monitoraggio interrogazioni
- **Bandi e Gare** - opportunita per il settore istruzione
- **Finanziamenti EU** - programma Italia Domani e fondi europei
- **Selezione Personale** - concorsi e selezioni
- **Podcast** - contenuti audio editoriali

---

## Struttura Progetto

```
Edunews24/
├── src/
│   ├── pages/
│   │   ├── api/                         # Endpoint API
│   │   │   ├── articles/                # CRUD articoli
│   │   │   ├── podcasts/                # Gestione podcast
│   │   │   ├── generate-article.ts      # Generazione AI articoli
│   │   │   ├── generate-tags.ts         # Generazione AI tag
│   │   │   ├── generate-summary.ts      # Generazione AI riassunti
│   │   │   ├── generate-faq.ts          # Generazione AI FAQ
│   │   │   ├── tts/generate.ts          # Text-to-Speech
│   │   │   ├── upload.ts               # Upload media su S3
│   │   │   └── contact.ts              # Form contatti
│   │   ├── admin/                       # Dashboard amministrazione
│   │   ├── amp/                         # Pagine AMP
│   │   ├── team/                        # Profili team
│   │   ├── [category]/[slug].astro      # Pagina articolo dinamica
│   │   ├── [category].astro             # Pagina categoria
│   │   └── index.astro                  # Homepage
│   ├── components/
│   │   ├── ArticleForm.tsx              # Editor articoli con strumenti AI
│   │   ├── automation/                  # Componenti automazione
│   │   │   ├── ScrapingTab.tsx          # Scraping sorgenti
│   │   │   ├── ReconstructTab.tsx       # Ricostruzione Claude
│   │   │   └── SummarizeTab.tsx         # Generazione sommari
│   │   ├── Header.astro                 # Navigazione principale
│   │   ├── CategorySidebar.astro        # Sidebar categoria
│   │   ├── ContactForm.tsx              # Form contatti
│   │   ├── AudioPlayer.tsx              # Player audio
│   │   └── ForumChat.astro              # Sistema commenti
│   ├── layouts/
│   │   ├── Layout.astro                 # Layout principale
│   │   └── AdminLayout.astro            # Layout admin
│   └── lib/
│       ├── supabase.ts                  # Client e tipi Supabase
│       ├── aws.ts                       # Utility upload S3
│       ├── seo.ts                       # Generazione dati strutturati
│       ├── categories.ts               # Configurazione categorie
│       └── utils.ts                     # Utility condivise
├── backend/
│   ├── app/
│   │   ├── main.py                      # Applicazione FastAPI
│   │   ├── models.py                    # Modelli SQLAlchemy
│   │   ├── schemas.py                   # Schemi Pydantic
│   │   ├── sender.py                    # Pipeline automazione
│   │   ├── variables_edunews.py         # Prompt AI e configurazione
│   │   └── enhanced_scraper.py          # Scraper avanzato
│   └── requirements.txt
├── public/                              # Asset statici
├── astro.config.mjs                     # Configurazione Astro
├── tailwind.config.mjs                  # Tema e colori custom
└── package.json
```

---

## API Endpoints

### Articoli

| Metodo | Endpoint | Descrizione |
|---|---|---|
| `POST` | `/api/articles/create` | Crea nuovo articolo |
| `GET` | `/api/articles/index` | Lista articoli con paginazione |
| `GET` | `/api/articles/[id]` | Dettaglio articolo |
| `PUT` | `/api/articles/[id]/update` | Aggiorna articolo |
| `DELETE` | `/api/articles/delete` | Elimina articolo |

### Generazione AI

| Metodo | Endpoint | Descrizione |
|---|---|---|
| `POST` | `/api/generate-article` | Genera articolo da prompt |
| `POST` | `/api/generate-tags` | Genera tag SEO ottimizzati |
| `POST` | `/api/generate-summary` | Genera riassunto |
| `POST` | `/api/generate-faq` | Genera FAQ |
| `POST` | `/api/tts/generate` | Genera audio TTS |

### Backend (FastAPI)

| Metodo | Endpoint | Descrizione |
|---|---|---|
| `POST` | `/api/news/reconstruct/{id}` | Ricostruzione articolo con Claude |
| `POST` | `/api/news/publish/{id}` | Pubblica articolo sul CMS |
| `POST` | `/api/news/analyze` | Analizza e raggruppa news |
| `GET` | `/api/news/links` | Recupera link fonti |

---

## Installazione

### Prerequisiti

- **Node.js** >= 18
- **Python** >= 3.10
- **npm** o **yarn**

### 1. Clona il repository

```bash
git clone https://github.com/micheleDibi/news1.git
cd news1
```

### 2. Configura le variabili d'ambiente

```bash
cp .env.example .env
```

Compila il file `.env` con le tue credenziali:

```env
# Database
PUBLIC_SUPABASE_URL=https://your-project.supabase.co
PUBLIC_SUPABASE_ANON_KEY=your-anon-key

# AI
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Storage
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=eu-south-1
AWS_BUCKET_NAME=your-bucket

# Scraping
FIRECRAWL_API_KEY=fc-...

# Sicurezza
API_SECRET_KEY=your-secret
PUBLIC_API_SECRET_KEY=your-public-secret

# Social
PUBLIC_FACEBOOK_PAGE_ID=...
PUBLIC_FACEBOOK_ACCESS_TOKEN=...

# Google TTS
CREDENTIALS_GOOGLE_SPEECH=path/to/credentials.json
```

### 3. Installa le dipendenze frontend

```bash
npm install
```

### 4. Installa le dipendenze backend

```bash
cd backend
pip install -r requirements.txt
```

### 5. Avvia in sviluppo

**Frontend:**
```bash
npm run dev
```

**Backend:**
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

---

## Build & Deploy

### Build di produzione

```bash
npm run build
```

Il build include automaticamente la copia delle credenziali Google Cloud necessarie per il TTS.

### Configurazione server

Il frontend Astro e configurato in modalita `server` con Node.js adapter:

- **Host:** `0.0.0.0`
- **Porta:** `80`

---

## Database

Il progetto utilizza **Supabase** (PostgreSQL) con le seguenti tabelle principali:

| Tabella | Descrizione |
|---|---|
| `articles` | Articoli con contenuto, metadati, tag, FAQ, media |
| `profiles` | Profili utente con ruoli e permessi |
| `categories` | Categorie primarie con colori e keyword |
| `secondary_categories` | Sottocategorie collegate alle primarie |
| `forum_messages` | Commenti e discussioni per articolo |
| `podcasts` | Episodi podcast |

---

## Categorie

Il sistema supporta le seguenti categorie editoriali, ognuna con un proprio colore identificativo:

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
| **Bandi** | Concorsi, gare e opportunita |

---

## Licenza

Progetto proprietario. Tutti i diritti riservati.

---

<p align="center">
  <strong>EduNews24</strong> &mdash; L'informazione che educa.
</p>
