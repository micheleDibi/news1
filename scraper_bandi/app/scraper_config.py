"""Registry config per lo scraper bandi (Step 2).

Mapping URL fonte -> strategia + parametri.
Generato automaticamente dall'analisi WebFetch di 108 fonti.

Strategie:
- httpx_bs4: SSR semplice (httpx + BeautifulSoup)
- firecrawl_scrape: JS dinamico / anti-bot
- firecrawl_extract: estrazione strutturata via prompt
- hybrid_httpx_firecrawl: discovery HTML + parse file allegato
- csv_parser: download CSV diretto
- pdf_extract_tables_pdfplumber: tabelle PDF
- pdf_extract_text: testo PDF
- skip_no_bandi: pagine senza bandi (hub, 404, ecc.)
"""
from __future__ import annotations


SCRAPER_CONFIG: dict[str, dict] = {
    # ============================================================
    # Abruzzo
    # ============================================================
    'https://coesione.regione.abruzzo.it/bandi-avvisi': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href^='/avvisi-pubblici/']",
        "url_pattern": r"^https?://coesione\.regione\.abruzzo\.it/avvisi-pubblici/(fse|fesr|fsc)/[a-z0-9\-]+$",
        "pagination": {
            "type": 'url_param',
            "param": 'page',
            "range": [0, 5],
        },
    },
    'https://coesione.regione.abruzzo.it/sites/coesione.regione.abruzzo.it/files/allegati/2023-07-20/Calendario-avvisi-FESR-20072023.pdf': {
        "strategy": 'pdf_extract_tables_pdfplumber',
        "columns_map": [],
        "note": 'Calendario preavvisi FESR 2021-2027 con righe del tipo (Asse/Priorita, Azione, Oggetto avviso, Data pubblicazione prevista, Importo, Beneficiari). Nessun link presente. Salvare per ogni riga: titol...',
    },
    'https://coesione.regione.abruzzo.it/sites/coesione.regione.abruzzo.it/files/2023-07/Calendario-avvisi-FSE-06072023.pdf': {
        "strategy": 'pdf_extract_tables_pdfplumber',
        "columns_map": [],
        "note": 'Calendario preavvisi FSE+ 2021-2027 con colonne tipiche: Priorita, Obiettivo specifico, Azione, Oggetto avviso, Data pubblicazione prevista, Risorse stanziate. Salvare ogni riga come raw_data JSONB...',
    },

    # ============================================================
    # Basilicata
    # ============================================================
    'https://europa.regione.basilicata.it/2021-27/avvisi-e-opportunita/': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='portalebandi.regione.basilicata.it/avvisi-e-bandi/'], a[href*='agenziaregionalelab.it/']",
        "url_pattern": r"^https?://portalebandi\.regione\.basilicata\.it/avvisi-e-bandi/[a-z0-9\-]+/?$",
    },
    'https://europa.regione.basilicata.it/2021-27/calendario-preavviso/': {
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'csv_parser',
        "note": 'Per ogni riga del calendario PDF/CSV scaricato salvare: titolo_avviso, fondo (FESR/FSE+), priorita/azione, data_pubblicazione_prevista (es. Q3 2025 o gg/mm/aaaa), importo, beneficiari. Riferimento ...',
    },

    # ============================================================
    # Calabria
    # ============================================================
    'https://calabriaeuropa.regione.calabria.it/bandi/?pr=&sort_order=ULTIMO+PUBBLICATO&filter_status=&filter_fund=PR+Calabria+FESR+FSE%2B+2021-2027&filter_date=&searchButton=Cerca': {
        "strategy": 'firecrawl_scrape',
        "link_selector": "a[href*='/bandi/']",
        "url_pattern": r"^https?://calabriaeuropa\.regione\.calabria\.it/bandi/[a-z0-9\-]+/?$",
        "pagination": {
            "type": 'none',
        },
    },
    'https://calabriaeuropa.regione.calabria.it/programmazione-2021-2027/calendario-inviti/': {
        "strategy": 'skip_no_bandi',
        "reason": 'WebFetch riceve HTTP 403 Forbidden: probabile blocco WAF/User-Agent sul portale regionale. Firecrawl con browser pool e User-Agent realistico ha buone chance di passare; se anch...',
    },

    # ============================================================
    # Campania
    # ============================================================
    'https://prfesr2127.regione.campania.it/category/opportunita-e-bandi/': {
        "strategy": 'httpx_bs4',
        "link_selector": 'a[href]',
        "url_pattern": r"^https://prfesr2127\.regione\.campania\.it/\d{4}/\d{2}/\d{2}/[^/]+/?$",
        "pagination": {
            "type": 'url_param',
            "param": 'page',
            "range": [0, 5],
        },
    },
    'https://prfesr2127.regione.campania.it/calendario-degli-inviti/': {
        "strategy": 'skip_no_bandi',
        "reason": "La pagina e' un hub descrittivo con messaggio 'Nessun risultato / in corso di aggiornamento': nessun dato strutturato di bandi/preavvisi presenti al momento. Inutile scraping. L...",
    },
    'https://fse.regione.campania.it/opportunita/': {
        "strategy": 'skip_no_bandi',
        "reason": "Pagina hub di sezione 'Opportunita' con menu, una singola news card e link a indici (/avvisi/, /opportunita/). Nessun bando individuale qui. La fonte effettiva e' il dominio est...",
    },

    # ============================================================
    # Emilia-Romagna
    # ============================================================
    'https://fesr.regione.emilia-romagna.it/opportunita/bandi': {
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'pdf_extract_tables_pdfplumber',
    },
    'https://fesr.regione.emilia-romagna.it/2021-2027/calendario-inviti-a-presentare-proposte': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='/opportunita/opportunita-di-finanziamento/']",
        "url_pattern": None,
    },
    'https://formazionelavoro.regione.emilia-romagna.it/entra-in-regione/bandi-regionali/fseplus-2021-2027': {
        "strategy": 'firecrawl_scrape',
        "link_selector": "a[href*='/leggi-atti-bandi/bandi-regionali/']",
        "url_pattern": None,
    },
    'https://formazionelavoro.regione.emilia-romagna.it/sito-fse/programmazione-2021-2027/calendario-inviti': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='/leggi-atti-bandi/bandi-regionali/bandi-per-annualita/']",
        "url_pattern": r"/leggi-atti-bandi/bandi-regionali/bandi-per-annualita/\d{4}/[a-z0-9-]+",
    },

    # ============================================================
    # Friuli-Venezia Giulia
    # ============================================================
    'https://europa.regione.fvg.it/it/bandi/_filter_:coesione-italia-fesr-9121:': {
        "strategy": 'firecrawl_scrape',
        "link_selector": "a[href*='/it/bandi/']",
        "url_pattern": None,
        "pagination": {
            "type": 'none',
        },
    },
    'https://europa.regione.fvg.it/it/programmi-36605/coesione-italia-21-27-friuli-venezia-giulia-36659/pr-fesr-friuli-venezia-giulia-39934/visibilita-trasparenza-e-comunicazione-66511': {
        "strategy": 'skip_no_bandi',
        "reason": "Pagina istituzionale dedicata a 'Visibilita, trasparenza e comunicazione' del PR FESR FVG: per natura contiene linee guida e materiali di comunicazione (loghi, manuali), non ban...",
    },
    'http://bandiformazione.regione.fvg.it/fop2011/': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='/Bandi/Dettaglio.aspx?Id=']",
        "url_pattern": r"https?://www\.regione\.fvg\.it/rafvg/cms/RAFVG/formazione-lavoro/formazione/area-operatori/Bandi/Dettaglio\.aspx\?Id=\d+",
        "pagination": {
            "type": 'url_param',
            "param": 'page',
            "range": [0, 5],
        },
    },
    'https://europa.regione.fvg.it/it/programmi-36605/coesione-italia-21-27-friuli-venezia-giulia-36659/coesione-italia-fse-40005/visibilita-e-comunicazione-fse-71995': {
        "strategy": 'skip_no_bandi',
        "reason": "Pagina gemella alla FESR su 'Visibilita e comunicazione' ma per il programma FSE FVG: contiene materiali di comunicazione, loghi, manuali grafici e linee guida beneficiari, non ...",
    },

    # ============================================================
    # Lazio
    # ============================================================
    'https://www.lazioeuropa.it/fondi/fesr/': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='/bandi/']",
        "url_pattern": None,
        "pagination": {
            "type": 'url_param',
            "param": 'page',
            "range": [0, 5],
        },
    },
    'https://www.lazioeuropa.it/app/uploads/2022/05/A5-Lazio-Presente-WEB.pdf': {
        "strategy": 'skip_no_bandi',
        "reason": "Il file e' una brochure A5 'Lazio Presente' (formato editoriale, 8-9 pagine, font/immagini). WebFetch non riesce ad estrarre testo (stream FlateDecode binario); il titolo e il c...",
    },
    'https://www.lazioeuropa.it/bandi/': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href^='https://www.lazioeuropa.it/bandi/']",
        "url_pattern": r"^https://www\.lazioeuropa\.it/bandi/[a-z0-9-]+/$",
        "pagination": {
            "type": 'url_param',
            "param": 'page',
            "range": [0, 5],
        },
    },
    'https://www.lazioeuropa.it/fse-calendario-delle-opportunita-di-finanziamento/': {
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'csv_parser',
        "note": "Ogni riga del CSV/PDF rappresenta un PREAVVISO senza link bando: salvare in raw_data {titolo_avviso, data_pubblicazione_prevista, fondo: 'FSE+', programma, asse/obiettivo specifico, beneficiari, do...",
    },

    # ============================================================
    # Liguria
    # ============================================================
    'https://www.regione.liguria.it/homepage-fondi-europei/cosa-cerchi/le-programmazioni-fesr/programma-operativo-fesr-2021-2027/bandi-por-fesr-2021-2027.html': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='/publiccompetition/']",
        "url_pattern": None,
    },
    'https://www.regione.liguria.it/homepage-fondi-europei/cosa-cerchi/le-programmazioni-fesr/programma-operativo-fesr-2021-2027/calndarioinviti-21-27-fesr.html': {
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'pdf_extract_tables_pdfplumber',
        "note": "Righe del PDF = preavvisi senza link bando: salvare in raw_data {titolo_invito, data_pubblicazione_prevista, asse/obiettivo_specifico, fondo: 'FESR', programma: 'PR FESR Liguria 21-27', dotazione_s...",
    },
    'https://www.regione.liguria.it/homepage-fondi-europei/cosa-cerchi/fse-fse-plus/2021-2027-fse-plus/bandi-pre-informativa/bandi.html': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='/bandi/publiccompetition/']",
        "url_pattern": r"/bandi/publiccompetition/\d+:[a-z0-9-]+\.html",
    },
    'https://www.regione.liguria.it/homepage-fondi-europei/cosa-cerchi/fse-fse-plus/2021-2027-fse-plus/bandi-pre-informativa/preinformativa-bandi-fse-plus.html': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='/component/publiccompetitions/document/']",
        "url_pattern": r"/component/publiccompetitions/document/\d+:[a-z0-9-]+\.html",
    },

    # ============================================================
    # Lombardia
    # ============================================================
    'https://ue.regione.lombardia.it/pc2127/prlombardiafesr2021-2027/bandi-pr-fesr-2021-2028?Stato=APERTO&Stato=IN+APERTURA&Stato=CHIUSO&FontiFinanziamento=2021IT16RFPR010': {
        "strategy": 'firecrawl_scrape',
        "link_selector": 'a[href]',
        "url_pattern": None,
        "pagination": {
            "type": 'none',
        },
    },
    'https://fesr.regione.lombardia.it/it/pc2127/prlombardiafesr2021-2027/calendario-degli-inviti-1': {
        "strategy": 'firecrawl_scrape',
        "link_selector": 'a[href]',
        "url_pattern": None,
    },
    'https://ue.regione.lombardia.it/pc2127/prlombardiafse2021-2027/bandi-pr-fse-2021-2028?Stato=APERTO&Stato=IN+APERTURA&Stato=CHIUSO&FontiFinanziamento=2021IT05SFPR008': {
        "strategy": 'firecrawl_scrape',
        "link_selector": 'a[href]',
        "url_pattern": None,
        "pagination": {
            "type": 'none',
        },
    },
    'https://fse.regione.lombardia.it/it/pc2127/prlombardiafse2021-2027/calendario-degli-inviti': {
        "strategy": 'firecrawl_scrape',
        "link_selector": 'a[href]',
        "url_pattern": None,
    },

    # ============================================================
    # Marche
    # ============================================================
    'https://www.regione.marche.it/Entra-in-Regione/Fondi-Europei/Bandi-di-finanziamento': {
        "strategy": 'firecrawl_scrape',
        "link_selector": "a[href*='/Entra-in-Regione/Fondi-Europei/']",
        "url_pattern": None,
    },
    'https://www.regione.marche.it/Entra-in-Regione/Fondi-Europei/Programmazione-2021-2027/Il-calendario-dei-bandi-in-uscita#Fondo-Europeo-di-Sviluppo-Regionale': {
        "strategy": 'firecrawl_scrape',
        "link_selector": 'a[href]',
        "url_pattern": None,
    },
    'https://www.regione.marche.it/Entra-in-Regione/Fondi-Europei/Programmazione-2021-2027/Il-calendario-dei-bandi-in-uscita': {
        "strategy": 'firecrawl_scrape',
        "link_selector": 'a[href]',
        "url_pattern": None,
    },

    # ============================================================
    # Piemonte
    # ============================================================
    'https://bandi.regione.piemonte.it/': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href^='/contributi-finanziamenti/'], a[href^='/pre-informazione-fondi-ue/'], a[href^='/gare-appalto/']",
        "url_pattern": r"^https://bandi\.regione\.piemonte\.it/(contributi-finanziamenti|pre-informazione-fondi-ue|gare-appalto)/[a-z0-9-]+$",
        "pagination": {
            "type": 'url_param',
            "param": 'page',
            "range": [0, 5],
        },
    },
    'https://www.regione.piemonte.it/web/temi/fondi-progetti-europei/fondo-europeo-sviluppo-regionale-fesr/avvisi-pre-informazione': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='/calendario-degli-inviti/']",
        "url_pattern": r"^https://www\.regione\.piemonte\.it/web/temi/fondi-progetti-europei/fondo-europeo-sviluppo-regionale-fesr/calendario-degli-inviti/[a-z0-9-]+$",
        "pagination": {
            "type": 'none',
        },
    },
    'https://www.regione.piemonte.it/web/temi/fondi-progetti-europei/fondo-sociale-europeo-fse#block-views-block-link-bandi-block-1': {
        "strategy": 'httpx_bs4',
        "link_selector": 'a[href]',
        "url_pattern": r"^https://bandi\.regione\.piemonte\.it/(contributi-finanziamenti|pre-informazione-fondi-ue)/[a-z0-9-]+$",
    },
    'https://www.regione.piemonte.it/web/temi/fondi-progetti-europei/fondo-sociale-europeo-fse/gli-avvisi-pre-informazione-fse-plus': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='bandi.regione.piemonte.it/pre-informazione-fondi-ue/']",
        "url_pattern": r"https?://bandi\.regione\.piemonte\.it/pre-informazione-fondi-ue/[a-z0-9-]+",
    },

    # ============================================================
    # Provincia Bolzano
    # ============================================================
    'https://europa.provincia.bz.it/it/bandi-e-avvisi': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='/it/bandi-e-avvisi/']",
        "url_pattern": r"^/it/bandi-e-avvisi/[a-z0-9-]+$",
    },
    'https://europa.provincia.bz.it/it/informazione-e-visibilita': {
        "strategy": 'skip_no_bandi',
        "reason": "HTTP 404. Slug non corretto: la pagina corretta sul portale e' 'comunicazione-e-visibilita-fse' (vedi fonte #6), che pero' e' sezione comunicazione/linee guida, non bandi.",
    },
    'https://europa.provinz.bz.it/it/bandi-e-avvisi': {
        "strategy": 'skip_no_bandi',
        "reason": "HTTP 404. Il dominio provinz.bz.it e' il mirror tedesco e serve solo /de/; il path /it/ non esiste su questo host.",
    },
    'https://europa.provincia.bz.it/it/comunicazione-e-visibilita-fse': {
        "strategy": 'skip_no_bandi',
        "reason": "Pagina di comunicazione/linee guida visibilita' FSE+ (logo, strategia, risultati), non un indice di bandi. Nessun link a pagine di dettaglio bando.",
    },

    # ============================================================
    # Provincia Trento
    # ============================================================
    'https://www.provincia.tn.it/Argomenti/Europa-e-attivita-internazionali/Europa/Fondo-europeo-di-sviluppo-regionale-FESR': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='/Servizi/']",
        "url_pattern": None,
    },
    'https://www.provincia.tn.it/Documenti-e-dati/Risorse/FESR-Calendario-degli-avvisi-e-degli-inviti-a-partecipare': {
        # FIX: URL e' una pagina HTML wrapper, non un CSV diretto.
        # hybrid scopre i file CSV/XLSX/PDF allegati e li parsa.
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.csv'], a[href$='.xlsx'], a[href$='.xls'], a[href$='.pdf']",
        "file_strategy_default": 'csv_parser',
    },
    'https://www.provincia.tn.it/Argomenti/Europa-e-attivita-internazionali/Europa/Fondo-sociale-europeo-plus-FSE': {
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'pdf_extract_tables_pdfplumber',
    },
    'https://www.provincia.tn.it/Documenti-e-dati/Risorse/FSE-Calendario-degli-avvisi-e-degli-inviti-a-partecipare': {
        # FIX: URL e' una pagina HTML wrapper, non un CSV diretto.
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.csv'], a[href$='.xlsx'], a[href$='.xls'], a[href$='.pdf']",
        "file_strategy_default": 'csv_parser',
    },

    # ============================================================
    # Puglia
    # ============================================================
    'https://pr2127.regione.puglia.it/elenco-avvisi-pubblicati': {
        "strategy": 'firecrawl_scrape',
        "link_selector": "a[href*='/elenco-avvisi-pubblicati/'], a[href*='avviso']",
        "url_pattern": None,
        "pagination": {
            "type": 'none',
        },
    },
    'https://pr2127.regione.puglia.it/calendario-opportunita-di-finanziamento': {
        "strategy": 'firecrawl_scrape',
        "link_selector": 'a[href]',
        "url_pattern": None,
    },

    # ============================================================
    # Sardegna
    # ============================================================
    'https://www.regione.sardegna.it/atti-bandi-archivi/atti-amministrativi/bandi?size=n_12_n&filters%5B0%5D%5Bfield%5D=fondo&filters%5B0%5D%5Bvalues%5D%5B0%5D=FESR%20-%20Fondo%20Europeo%20di%20Sviluppo%20Regionale%202021-2027&filters%5B0%5D%5Btype%5D=any': {
        "strategy": 'firecrawl_scrape',
        "link_selector": 'a[href]',
        "url_pattern": None,
        "pagination": {
            "type": 'url_param',
            "param": 'page',
            "range": [0, 5],
        },
    },
    'https://cmsras.regione.sardegna.it/api/assets/programmazione/ff4fcd73-ae2e-4f66-a900-18664d4a4c56/': {
        "strategy": 'csv_parser',
        # Skip header narrativo: titolo + sottotitolo + descrizione legale + riga vuota
        "skiprows": 5,
        "columns_map": [],
        "note": 'Sì — tutte le righe sono preavvisi SENZA link al bando individuale. Salvare in raw_data JSONB con chiavi: {titolo, priorita, obiettivo_specifico, soggetti_ammissibili, dotazione_finanziaria_indicat...',
    },
    'https://www.regione.sardegna.it/atti-bandi-archivi/atti-amministrativi/bandi?size=n_12_n&filters%5B0%5D%5Bfield%5D=fondo&filters%5B0%5D%5Bvalues%5D%5B0%5D=FSE%2B%20-%20Fondo%20Sociale%20Europeo%202021-2027&filters%5B0%5D%5Btype%5D=any': {
        "strategy": 'firecrawl_scrape',
        "link_selector": 'a[href]',
        "url_pattern": None,
        "pagination": {
            "type": 'url_param',
            "param": 'page',
            "range": [0, 5],
        },
    },
    'https://cmsras.regione.sardegna.it/api/assets/programmazione/2a95187d-764b-4a8f-a4ef-a98bd4eaf507/pr-fse-calendario-inviti-3-2023-del-14.12.2023.csv': {
        "strategy": 'csv_parser',
        # Skip header narrativo: titolo + sottotitolo + descrizione legale + riga vuota
        "skiprows": 5,
        "columns_map": [],
        "note": 'Tutte le righe sono bandi SENZA link. Per ciascuna riga salvare in raw_data JSONB le 10 colonne: titolo_bando (col1), servizio_responsabile, priorita, obiettivo_specifico, settore_intervento, tipol...',
    },

    # ============================================================
    # Sicilia
    # ============================================================
    'https://www.euroinfosicilia.it/download/calendario-inviti-presentare-proposte-pr-fesr-sicilia-20212027-primo-aggiornamento-2024-16022024/?wpdmdl=101858': {
        "strategy": 'pdf_extract_tables_pdfplumber',
        "columns_map": [],
        "note": 'Tutte le righe del PDF sono bandi SENZA link (calendario di programmazione). Per ogni riga estratta dal PDF salvare in raw_data: titolo_invito, obiettivo_specifico, beneficiari, dotazione_eur, data...',
    },
    'https://www.sicilia-fse.it/avvisi-e-bandi': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='/avvisi-e-bandi/pr-fse-2021-2027/'], a[href*='/avvisi-e-bandi/po-fse-2014-2020/'], a[href*='/avvisi-e-bandi/altro/']",
        "url_pattern": None,
        "pagination": {
            "type": 'url_param',
            "param": 'page',
            "range": [0, 5],
        },
    },
    'https://www.sicilia-fse.it/pr-21-27/calendario-inviti': {
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'pdf_extract_tables_pdfplumber',
        "note": 'Ogni PDF contiene il calendario degli avvisi del quadrimestre con righe tabellari. Per ciascuna riga salvare in raw_data: titolo_avviso, area_geografica, obiettivo_strategico, obiettivo_specifico, ...',
    },

    # ============================================================
    # Toscana
    # ============================================================
    'https://www.regione.toscana.it/pr-fesr-2021-2027/bandi-aperti?sortBy=desc&orderBy=modifiedDate': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href^='/-/']",
        "url_pattern": None,
        "pagination": {
            "type": 'url_param',
            "param": 'page',
            "range": [0, 5],
        },
    },
    'https://www.regione.toscana.it/pr-fesr-2021-2027/calendario-delle-opportunita': {
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'csv_parser',
        "note": "Tutte le righe del CSV/XLSX sono bandi SENZA link (calendario preavvisi). Per ciascuna riga salvare in raw_data le colonne previste dall'art. 49 Reg UE 1060/2021: titolo_invito, obiettivo_specifico...",
    },
    'https://www.regione.toscana.it/pr-fse-2021-2027/bandi-opportunita': {
        "strategy": 'skip_no_bandi',
        "reason": "URL esatto restituisce HTTP 404. Lo slug 'bandi-opportunita' sotto /pr-fse-2021-2027 non esiste piu' (o ha cambiato slug).",
    },
    'https://www.regione.toscana.it/pr-fse-2021-2027/calendario-delle-opportunita': {
        "strategy": 'skip_no_bandi',
        "reason": "URL esatto restituisce HTTP 404. Slug 'calendario-delle-opportunita' non esistente sotto /pr-fse-2021-2027.",
    },

    # ============================================================
    # Umbria
    # ============================================================
    'https://www.regione.umbria.it/bandi-fesr': {
        "strategy": 'skip_no_bandi',
        "reason": "Pagina solo informativa che reindirizza l'utente a due portali esterni (regione.umbria.it/la-regione/bandi e sviluppumbria.it); non contiene alcun titolo o link di bando individ...",
    },
    'https://www.regione.umbria.it/calendario-degli-inviti-a-presentare-proposte': {
        # FIX: URL e' una pagina HTML wrapper, non un CSV/PDF diretto.
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.csv'], a[href$='.xlsx'], a[href$='.xls'], a[href$='.pdf']",
        "file_strategy_default": 'csv_parser',
    },
    'https://www.regione.umbria.it/bandi-fse': {
        "strategy": 'skip_no_bandi',
        "reason": "Pagina di rinvio/orientamento: non elenca bandi individuali ma solo link verso canali esterni (regione.umbria.it/la-regione/bandi, arpalumbria.it, BUR). Non e' una sorgente util...",
    },

    # ============================================================
    # Valle d'Aosta
    # ============================================================
    'https://new.regione.vda.it/europa/progetti/bandi-e-avvisi': {
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'pdf_extract_tables_pdfplumber',
        "note": "Se anche con rendering JS i singoli bandi restano senza href, salvare in raw_data: titolo (h3), data_scadenza, data_pubblicazione, tag (categorie). Esempio osservato: 'Avviso pubblico 26AB - Attivi...",
    },
    'https://new.regione.vda.it/europa/fondi-e-programmi/fondo-europeo-di-sviluppo-regionale/fesr-2021-27/calendario-degli-inviti-a-presentare-proposte': {
        # FIX: URL e' una pagina HTML wrapper, non un PDF diretto.
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'pdf_extract_tables_pdfplumber',
    },
    'https://new.regione.vda.it/europa/fondi-e-programmi/fondo-sociale-europeo-plus/bandi-e-avvisi/calendario-degli-inviti-a-presentare-proposte': {
        # FIX: URL e' una pagina HTML wrapper, non un CSV/PDF diretto.
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'csv_parser',
    },

    # ============================================================
    # Veneto
    # ============================================================
    'https://programmazione-ue-2021-2027.regione.veneto.it/fesr/fesr-opportunita': {
        "strategy": 'skip_no_bandi',
        "reason": 'Pagina hub introduttiva: rimanda al portale cronoprogramma esterno (regione.veneto.it/web/programmi-comunitari/cronoprogramma-bandi-21-27) e ad altre sotto-sezioni del proprio d...',
    },
    'https://programmazione-ue-2021-2027.regione.veneto.it/fesr/fesr-calendario-inviti-a-presentare-proposte': {
        "strategy": 'skip_no_bandi',
        "reason": 'Pagina descrittiva sul concetto di calendario preavvisi, senza tabella/elenco di bandi sulla pagina stessa. Reindirizza testualmente a https://www.regione.veneto.it/web/programm...',
    },
    'https://programmazione-ue-2021-2027.regione.veneto.it/fse/fse-opportunita': {
        "strategy": 'skip_no_bandi',
        "reason": "WebFetch ha restituito HTTP 404 Not Found: la pagina e' stata spostata o eliminata. Da aggiornare nel DB con URL corretto (probabilmente /fse/fse-opportunita-di-finanziamento o ...",
    },
    'https://programmazione-ue-2021-2027.regione.veneto.it/fse/fse-calendario-inviti-a-presentare-proposte': {
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'csv_parser',
        "note": "Ciascuna riga del CSV/PDF e' un invito previsto senza link a pagina di dettaglio (il preavviso e' anticipato, il bando vero non esiste ancora). Salvare in raw_data: titolo invito, area geografica, ...",
    },

    # ============================================================
    # Ministeriali / Lavoro
    # ============================================================
    'https://www.lavoro.gov.it/pn-giovani-donne-lavoro/opportunita/avvisi/': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='/pn-giovani-donne-lavoro/opportunita/avvisi/archivio-avvisi/']",
        "url_pattern": r"/pn-giovani-donne-lavoro/opportunita/avvisi/archivio-avvisi/[a-z0-9-]+",
    },
    'https://www.lavoro.gov.it/pn-giovani-donne-lavoro/calendario-preavvisi': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='/pn-giovani-donne-lavoro/opportunita/calendario-preavvisi/archivio-preavvisi/']",
        "url_pattern": r"/pn-giovani-donne-lavoro/opportunita/calendario-preavvisi/archivio-preavvisi/[a-z0-9-]+",
    },

    # ============================================================
    # PN CAP COE
    # ============================================================
    'https://capcoe.it/opportunita/avvisi/': {
        "strategy": 'httpx_bs4',
        "link_selector": 'a[href*="/opportunita/avvisi/"]',
        "url_pattern": r"^https?://capcoe\.it/opportunita/avvisi/[^/]+/$`",
    },
    'https://capcoe.it/opportunita/calendario-di-preavviso/': {
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'csv_parser',
        "note": "Ogni riga del CSV (CalendarioAvvisi_Opportunita_CCI2021IT16FFTA001.csv) e' un preavviso senza pagina dettaglio. Salvare in raw_data: titolo opportunita, area geografica, obiettivo strategico, obiet...",
    },

    # ============================================================
    # PN Cultura
    # ============================================================
    'https://pncultura2127.cultura.gov.it/opportunita-di-finanziamento/': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='creativitacontemporanea.cultura.gov.it/pncultura'], a[href*='invitalia.it/incentivi']",
        "url_pattern": None,
    },
    'https://pncultura2127.cultura.gov.it/calendario-di-preavviso/': {
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'csv_parser',
        "note": "Ogni riga del CSV/XLSX (CalendarioAvvisi_Opportunita_CCI2021IT16RFPR003) e' un preavviso senza pagina dettaglio. Salvare in raw_data: titolo opportunita, area geografica, obiettivo strategico, obie...",
    },

    # ============================================================
    # PN Inclusione
    # ============================================================
    'https://pninclusione21-27.lavoro.gov.it/opportunita/avvisi': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href^='/avvisi/']",
        "url_pattern": r"^https?://pninclusione21-27\.lavoro\.gov\.it/avvisi/[a-z0-9-]+$",
    },
    'https://pninclusione21-27.lavoro.gov.it/opportunita/calendario-preavvisi': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href^='/preavvisi/']",
        "url_pattern": r"^https?://pninclusione21-27\.lavoro\.gov\.it/preavvisi/[a-z0-9-]+$",
    },
    'https://www.ponic.gov.it/sites/PON/pnric-calendarioinviti': {
        # FIX: URL e' una pagina HTML che linka un CSV, non il CSV diretto.
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.csv'], a[href$='.xlsx'], a[href*='calendario_unico']",
        "file_strategy_default": 'csv_parser',
    },

    # ============================================================
    # PN JTF (Just Transition Fund)
    # ============================================================
    'https://www.jtf.gov.it/avvisi/': {
        "strategy": 'httpx_bs4',
        "link_selector": 'a[href]',
        "url_pattern": None,
    },
    'https://www.jtf.gov.it/attuazione/calendario-degli-inviti/': {
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'csv_parser',
        "note": 'Ogni riga del CalendarioAvvisi_*.csv rappresenta un invito senza pagina HTML dedicata. Salvare in raw_data: titolo/azione invito, data apertura prevista, data chiusura prevista, importo/dotazione, ...',
    },

    # ============================================================
    # PN Metro Plus
    # ============================================================
    'https://www.pnmetroplus.it/home-2/pon-metro-plus-21-27/calendario-avvisi/': {
        "strategy": 'skip_no_bandi',
        "reason": "L'URL letterale risponde 301 e redireziona alla home pnmetroplus.gov.it/ (dominio cambiato da .it -> .gov.it e path cambiato). La pagina canonica equivalente esiste su /opportun...",
    },

    # ============================================================
    # PN Scuola e Competenze
    # ============================================================
    'https://pn20212027.istruzione.it/avvisi/': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='/avvisi/']",
        "url_pattern": r"^https?://pn20212027\.istruzione\.it/avvisi/[a-z0-9-]+/?$",
    },
    'https://pn20212027.istruzione.it/calendario/': {
        "strategy": 'httpx_bs4',
        "link_selector": 'a[href]',
        "url_pattern": None,
    },

    # ============================================================
    # PN Sicurezza / Interno
    # ============================================================
    'https://fondieuropeisicurezza.interno.gov.it/pnsl/it/contents/calendario-preavvisi-e-opportunita': {
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'csv_parser',
        "note": "Le opportunita' previste senza pagina di dettaglio sono elencate nei file allegati Calendario avvisi (CSV 0,74 KB e XLSX 10,42 KB): scaricare e parsare per righe titolo+data+stato da salvare come r...",
    },

    # ============================================================
    # CTE / Alcotra
    # ============================================================
    'https://www.interreg-alcotra.eu/it/bandi-0': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href^='/it/']",
        "url_pattern": None,
        "pagination": {
            "type": 'url_param',
            "param": 'page',
            "range": [0, 5],
        },
    },

    # ============================================================
    # CTE / Alpine Space
    # ============================================================
    'https://www.alpine-space.eu/how-to-apply/': {
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'pdf_extract_tables_pdfplumber',
        "note": "I tre 'current calls' (Capitalisation projects, Classic projects, Small-scale projects) appaiono come testo senza URL dedicato. Salvare in raw_data: {nome_call, tipo_call, deadline (es. 30.06.2026 ...",
    },

    # ============================================================
    # CTE / Central Europe
    # ============================================================
    'https://www.interreg-central.eu/calls-for-proposals/': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='-call']",
        "url_pattern": r"https://www\.interreg-central\.eu/[a-z0-9-]*(call|capitalisation)[a-z0-9-]*/?",
    },

    # ============================================================
    # CTE / Euro-MED
    # ============================================================
    'https://interreg-euro-med.eu/en/get-involved/': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='/en/call-']",
        "url_pattern": r"https://interreg-euro-med\.eu/en/call-\d+-[a-z0-9-]+/?",
    },

    # ============================================================
    # CTE / Grecia-Italia
    # ============================================================
    'https://www.greece-italy.eu/call/': {
        "strategy": 'firecrawl_scrape',
        "link_selector": "a[href^='https://www.greece-italy.eu/']",
        "url_pattern": r"https://www\.greece-italy\.eu/[a-z0-9-]+/",
        "pagination": {
            "type": 'none',
        },
    },

    # ============================================================
    # CTE / IPA ADRION
    # ============================================================
    'https://www.interreg-ipa-adrion.eu/calls/1st-call/': {
        "strategy": 'httpx_bs4',
        "link_selector": 'a[href]',
        "url_pattern": None,
    },

    # ============================================================
    # CTE / Interreg Europe
    # ============================================================
    'https://www.interregeurope.eu/apply-for-the-call': {
        "strategy": 'skip_no_bandi',
        "reason": 'WebFetch riceve HTTP 403 Forbidden: probabile WAF/anti-bot (Cloudflare o simile) che blocca user-agent server-side. Firecrawl con browser rendering bypassa tipicamente questo ti...',
    },
    'https://www.interregeurope.eu/next-call-for-projects': {
        "strategy": 'skip_no_bandi',
        "reason": 'WebFetch restituisce HTTP 403 Forbidden, stesso WAF di interregeurope.eu. Firecrawl scrape con browser è la via più rapida per ottenere il markup e identificare eventuali link/c...',
    },

    # ============================================================
    # CTE / Interreg Italia-Austria
    # ============================================================
    'https://interreg.net/it/avvisi-interreg-italia-austria-2021-2027/': {
        "strategy": 'firecrawl_extract',
        "link_selector": 'a[href]',
        "url_pattern": r"^https?://interreg\.net/wp-content/uploads/\d{4}/\d{2}/.+\.pdf$",
        "note": "Per ognuno dei 3 avvisi (Primo/Secondo/Terzo) estrarre come raw_data: titolo, durata, descrizione, priorita', budget, periodo presentazione proposte, periodo valutazione, risultato, lista PDF/DOC d...",
    },
    'https://interreg.net/wp-content/uploads/2024/04/000_EL_CalendarioInviti_IT.csv': {
        "strategy": 'csv_parser',
        "columns_map": [],
        "note": 'Eventuali righe con colonna LINK vuota: salvare come raw_data il dict completo della riga CSV (PROGRAMMA, AMMIN_EMANANTE, DESCRIZIONE, STATO_OPPORTUNITA, DATA_APERTURA, DATA_CHIUSURA, IMPORTO_TOTAL...',
    },

    # ============================================================
    # CTE / Italia-Francia Marittimo
    # ============================================================
    'https://interreg-marittimo.eu/avvisi': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='-avviso']",
        "url_pattern": None,
    },
    'https://interreg-marittimo.eu/calendario-avvisi': {
        "strategy": 'skip_no_bandi',
        "reason": "Il calendario e' interamente contenuto in una singola immagine PNG (calendario.png, 9deg aggiornamento marzo 2026) senza alcun testo strutturato o link ai singoli preavvisi. Est...",
    },

    # ============================================================
    # CTE / Italia-Slovenia
    # ============================================================
    'https://www.ita-slo.eu/it/bandi': {
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'pdf_extract_tables_pdfplumber',
        "note": 'Il PDF calendario allegato contiene righe titolo+data senza href: salvare in raw_data {titolo_bando, data_apertura, data_scadenza, asse/priorita, lingua}.',
    },
    'https://www.ita-slo.eu/sites/default/files/media/document/Programme_Calendar_June_2023_EN_IT_SLO.pdf': {
        "strategy": 'pdf_extract_tables_pdfplumber',
        "columns_map": [],
        "note": "Ogni riga del calendario e' un bando senza URL. Salvare in raw_data: {priorita, obiettivo_specifico, titolo_bando, data_apertura, data_chiusura, budget_indicativo, lingua_riga}. Filename suggerisce...",
    },

    # ============================================================
    # CTE / Italia-Svizzera
    # ============================================================
    'https://www.interreg-italiasvizzera.eu/wps/portal/site/interreg-italia-svizzera/avvisi': {
        "strategy": 'hybrid_httpx_firecrawl',
        "discovery_selector": "a[href$='.pdf'], a[href$='.csv'], a[href$='.xlsx']",
        "file_strategy_default": 'pdf_extract_tables_pdfplumber',
    },

    # ============================================================
    # CTE / Italy-Albania-Montenegro
    # ============================================================
    'https://www.italy-albania-montenegro.eu/programme/south-adriatic-2021-27/south-adriatic-calls': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='/sites/default/files/']",
        "url_pattern": r"^/sites/default/files/\d{4}-\d{2}/.+\.(pdf|zip)$",
        "pagination": {
            "type": 'url_param',
            "param": 'page',
            "range": [0, 5],
        },
    },
    'https://www.italy-albania-montenegro.eu/sites/default/files/2022-05/Pre_call_Capitalisation_Small_Scale_Projects_13042022.pdf': {
        "strategy": 'pdf_extract_text',
        "columns_map": [],
        "note": "Il bando coincide con il PDF stesso. raw_data: {titolo='Pre-call Capitalisation Small Scale Projects', data_documento='13/04/2022', tipo='pre-call', programma='Italy-Albania-Montenegro', testo_estr...",
    },

    # ============================================================
    # CTE / Italy-Croatia
    # ============================================================
    'https://www.italy-croatia.eu/web/italy-croatia/1st-call-for-proposals': {
        "strategy": 'skip_no_bandi',
        "reason": "La pagina e' la pagina di dettaglio della SOLA 1st Call for Proposals (gia' chiusa: standard 22/03/2023, small-scale 28/02/2023). Non e' un indice di piu' bandi: contiene solo d...",
    },
    'https://www.italy-croatia.eu/web/it-hr-interreg-2021-2027/plan-of-calls-for-proposals': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='-call-for-proposals']",
        "url_pattern": None,
    },

    # ============================================================
    # CTE / Italy-Malta
    # ============================================================
    'https://italiamalta.eu/index.php/it/bandi-e-avvisi': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='/bandi-e-avvisi/avviso-']",
        "url_pattern": None,
    },

    # ============================================================
    # CTE / NEXT-MED
    # ============================================================
    'https://www.interregnextmed.eu/apply-for-funding/first-call-for-proposals/': {
        "strategy": 'skip_no_bandi',
        "reason": "URL e' gia' il dettaglio del singolo bando First Call (status CLOSED). Da scartare a livello discovery o usare la pagina genitrice /apply-for-funding/ come fonte. Questa URL puo...",
    },
    'https://www.interregnextmed.eu/apply-for-funding/': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href*='-call-for-proposals/']",
        "url_pattern": None,
    },

    # ============================================================
    # CTE / URBACT
    # ============================================================
    'https://urbact.eu/get-involved': {
        "strategy": 'httpx_bs4',
        "link_selector": "a[href^='https://urbact.eu/call-']",
        "url_pattern": r"https://urbact\.eu/call-[a-z0-9-]+",
    },

}

# Total entries: 106
