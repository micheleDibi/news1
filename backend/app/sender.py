import requests
import json
import time
import ast
from datetime import datetime, timezone
import schedule
from typing import List, Dict, Any, Tuple, Optional
import re
from html import unescape
from urllib.parse import urljoin, urlparse
from . import schemas
import pytz
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()
from supabase import create_client, Client
from firecrawl import Firecrawl
from openai import OpenAI
from pydantic import BaseModel, Field
from .variables_edunews import (
    hour_to_iniziate,
    hour_to_end,
    query_generator
)

# API configuration
BASE_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
TELEGRAM_URL = os.getenv("TELEGRAM_URL", "http://localhost:8004")
PUBLIC_SUPABASE_URL = os.getenv("PUBLIC_SUPABASE_URL")
PUBLIC_SUPABASE_ANON_KEY = os.getenv("PUBLIC_SUPABASE_ANON_KEY")
# Supabase configuration
SUPABASE_URL = PUBLIC_SUPABASE_URL
SUPABASE_KEY = PUBLIC_SUPABASE_ANON_KEY

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:4321")
REFRESH_ENDPOINT = f"{FRONTEND_URL}/api/bandi/refresh"
SCHEDULE_MINUTES = 60 # Run every hour
INTERPELLI_SOURCE_URL = "https://scuolainterpelli.it/interpelli-scuola-aggiornati/"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
firecrawl_app = Firecrawl(api_key=FIRECRAWL_API_KEY) if FIRECRAWL_API_KEY else None

ITALIAN_MONTHS = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}

REGION_NAMES = [
    "Abruzzo", "Basilicata", "Calabria", "Campania", "Emilia-Romagna", "Friuli-Venezia Giulia",
    "Lazio", "Liguria", "Lombardia", "Marche", "Molise", "Piemonte", "Puglia", "Sardegna",
    "Sicilia", "Toscana", "Trentino-Alto Adige", "Umbria", "Valle d'Aosta", "Veneto"
]

PROVINCE_CODE_TO_REGION = {
    "AG": "Sicilia", "AL": "Piemonte", "AN": "Marche", "AO": "Valle d'Aosta", "AP": "Marche",
    "AQ": "Abruzzo", "AR": "Toscana", "AT": "Piemonte", "AV": "Campania", "BA": "Puglia",
    "BG": "Lombardia", "BI": "Piemonte", "BL": "Veneto", "BN": "Campania", "BO": "Emilia-Romagna",
    "BR": "Puglia", "BS": "Lombardia", "BT": "Puglia", "BZ": "Trentino-Alto Adige", "CA": "Sardegna",
    "CB": "Molise", "CE": "Campania", "CH": "Abruzzo", "CL": "Sicilia", "CN": "Piemonte",
    "CO": "Lombardia", "CR": "Lombardia", "CS": "Calabria", "CT": "Sicilia", "CZ": "Calabria",
    "EN": "Sicilia", "FC": "Emilia-Romagna", "FE": "Emilia-Romagna", "FG": "Puglia", "FI": "Toscana",
    "FM": "Marche", "FR": "Lazio", "GE": "Liguria", "GO": "Friuli-Venezia Giulia", "GR": "Toscana",
    "IM": "Liguria", "IS": "Molise", "KR": "Calabria", "LC": "Lombardia", "LE": "Puglia",
    "LI": "Toscana", "LO": "Lombardia", "LT": "Lazio", "LU": "Toscana", "MB": "Lombardia",
    "MC": "Marche", "ME": "Sicilia", "MI": "Lombardia", "MN": "Lombardia", "MO": "Emilia-Romagna",
    "MS": "Toscana", "MT": "Basilicata", "NA": "Campania", "NO": "Piemonte", "NU": "Sardegna",
    "OR": "Sardegna", "PA": "Sicilia", "PC": "Emilia-Romagna", "PD": "Veneto", "PE": "Abruzzo",
    "PG": "Umbria", "PI": "Toscana", "PN": "Friuli-Venezia Giulia", "PO": "Toscana", "PR": "Emilia-Romagna",
    "PT": "Toscana", "PU": "Marche", "PV": "Lombardia", "PZ": "Basilicata", "RA": "Emilia-Romagna",
    "RC": "Calabria", "RE": "Emilia-Romagna", "RG": "Sicilia", "RI": "Lazio", "RM": "Lazio",
    "RN": "Emilia-Romagna", "RO": "Veneto", "SA": "Campania", "SI": "Toscana", "SO": "Lombardia",
    "SP": "Liguria", "SR": "Sicilia", "SS": "Sardegna", "SU": "Sardegna", "SV": "Liguria",
    "TA": "Puglia", "TE": "Abruzzo", "TN": "Trentino-Alto Adige", "TO": "Piemonte", "TP": "Sicilia",
    "TR": "Umbria", "TS": "Friuli-Venezia Giulia", "TV": "Veneto", "UD": "Friuli-Venezia Giulia", "VA": "Lombardia",
    "VB": "Piemonte", "VC": "Piemonte", "VE": "Veneto", "VI": "Veneto", "VR": "Veneto", "VT": "Lazio", "VV": "Calabria"
}

PROVINCE_NAME_TO_REGION = {
    "caserta": "Campania", "napoli": "Campania", "salerno": "Campania", "avellino": "Campania", "benevento": "Campania",
    "milano": "Lombardia", "monza": "Lombardia", "varese": "Lombardia", "como": "Lombardia", "brescia": "Lombardia",
    "bergamo": "Lombardia", "pavia": "Lombardia", "mantova": "Lombardia", "cremona": "Lombardia", "lodi": "Lombardia",
    "roma": "Lazio", "frosinone": "Lazio", "latina": "Lazio", "rieti": "Lazio", "viterbo": "Lazio",
    "torino": "Piemonte", "cuneo": "Piemonte", "novara": "Piemonte", "vercelli": "Piemonte", "asti": "Piemonte",
    "genova": "Liguria", "savona": "Liguria", "la-spezia": "Liguria", "imperia": "Liguria",
    "firenze": "Toscana", "pisa": "Toscana", "livorno": "Toscana", "siena": "Toscana", "arezzo": "Toscana",
    "prato": "Toscana", "pistoia": "Toscana", "massa": "Toscana", "lucca": "Toscana", "grosseto": "Toscana",
    "bologna": "Emilia-Romagna", "modena": "Emilia-Romagna", "parma": "Emilia-Romagna", "reggio": "Emilia-Romagna",
    "forli": "Emilia-Romagna", "cesena": "Emilia-Romagna", "rimini": "Emilia-Romagna", "ferrara": "Emilia-Romagna", "piacenza": "Emilia-Romagna"
}

PROVINCE_CODE_TO_CITY = {
    "CE": "Caserta", "BN": "Benevento", "AV": "Avellino", "NA": "Napoli", "SA": "Salerno",
    "CS": "Cosenza", "CZ": "Catanzaro", "KR": "Crotone", "RC": "Reggio Calabria", "VV": "Vibo Valentia",
    "RE": "Reggio Emilia", "BO": "Bologna", "MO": "Modena", "PR": "Parma", "FC": "Forlì-Cesena", "RN": "Rimini",
    "MI": "Milano", "MB": "Monza", "VA": "Varese", "CO": "Como", "BS": "Brescia", "BG": "Bergamo", "PV": "Pavia",
    "AQ": "L'Aquila", "RM": "Roma", "TO": "Torino"
}

DOMAIN_REGION_HINTS = {
    'istruzionelombardia.gov.it': 'Lombardia',
    'istruzioneer.gov.it': 'Emilia-Romagna',
    'istruzione.calabria.it': 'Calabria',
    'mim.gov.it': 'Italia'
}

# Pydantic models for firecrawl extraction
class NestedModel1(BaseModel):
    elenco_name: str = None
    elenco_date: str = None  # Will be inserted as timestamp
    elenco_link: str = None

class ExtractSchema(BaseModel):
    elenco_list: list[NestedModel1] = None

class NestedModel2(BaseModel):
    interpello_name: str = None
    interpello_date: str = None  # Will be inserted as timestamp
    interpello_description: str = None
    interpello_link: str = None
    city_name: str = None

class NestedModel1Interpelli(BaseModel):
    region_name: str = None
    interpelli: list[NestedModel2] = None

class ExtractSchemaInterpelli(BaseModel):
    regions_interpelli: list[NestedModel1Interpelli] = None


def _is_missing_or_generic_institution(value: Optional[str]) -> bool:
    if not value:
        return True
    normalized = value.strip().lower()
    if not normalized:
        return True
    generic_tokens = [
        "visualizza interpelli",
        "interpelli",
        "clicca qui",
        "dettagli",
        "istituto non specificato",
        "non specificata",
        "non specificato"
    ]
    if normalized in generic_tokens or len(normalized) < 6:
        return True

    if normalized.startswith('interpello'):
        return True

    if re.search(r'https?://|www\.|\b[a-z0-9.-]+\.[a-z]{2,}\b', normalized, flags=re.IGNORECASE):
        return True

    return False


def _is_plausible_institution_name(value: Optional[str]) -> bool:
    if _is_missing_or_generic_institution(value):
        return False

    normalized = (value or '').strip()
    lowered = normalized.lower()

    noisy_tokens = [
        'aree tematiche',
        'cookie',
        'scuola in chiaro',
        'personale docente/educativo',
        'legale, contenzioso',
        '-->'
    ]
    if any(token in lowered for token in noisy_tokens):
        return False

    if re.search(r'\b(istituto|i\.c\.|liceo|scuola|iis|cpia|convitto)\b', lowered, flags=re.IGNORECASE):
        return True

    return len(normalized.split()) <= 6 and len(normalized) <= 80


def _extract_clean_title_from_html(html: str) -> Optional[str]:
    if not html:
        return None

    patterns = [
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        r'<title[^>]*>(.*?)</title>',
        r'<h1[^>]*>(.*?)</h1>'
    ]

    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            continue

        raw_value = re.sub(r'<[^>]+>', ' ', match.group(1))
        cleaned = unescape(raw_value)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        if cleaned:
            cleaned = re.sub(r'\s*[\|\-–—]\s*(scuolainterpelli\.it|interpelli scuola.*)$', '', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'^interpelli?\s*[:\-–—]\s*', '', cleaned, flags=re.IGNORECASE)
            cleaned = cleaned.strip(' -–—|')
            if cleaned:
                return cleaned

    return None


def _normalize_url(value: Optional[str]) -> str:
    if not value:
        return ""
    parsed = urlparse(value.strip())
    path = parsed.path.rstrip('/')
    return f"{parsed.netloc.lower()}{path}"


def _clean_institution_candidate(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = unescape(value)
    cleaned = re.sub(r'<[^>]+>', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' \t\n\r-–—|:')
    cleaned = re.sub(r'^(vai all\'interpello|visualizza interpelli)\s*', '', cleaned, flags=re.IGNORECASE).strip()
    if re.search(r'https?://|www\.', cleaned, flags=re.IGNORECASE):
        return None
    if re.fullmatch(r'[\w.-]+\.[a-z]{2,}(/[\w\-./?%&=]*)?', cleaned, flags=re.IGNORECASE):
        return None

    cleaned = re.sub(r'\s*[-–—,]\s*[A-Z][A-Za-zÀ-ÖØ-öø-ÿ\' ]+\s*\([A-Z]{2}\)\s*$', '', cleaned)
    cleaned = re.sub(r'\s*[-–—,]\s*[A-Z][A-Za-zÀ-ÖØ-öø-ÿ\' ]+\s+[A-Z]{2}\s*$', '', cleaned)
    cleaned = re.sub(r'\s*\([A-Z]{2}\)\s*$', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' \t\n\r-–—|:')

    if _is_missing_or_generic_institution(cleaned):
        return None
    if len(cleaned) > 180:
        return None
    return cleaned


def _extract_institution_from_text(value: Optional[str]) -> Optional[str]:
    cleaned = _clean_institution_candidate(value)
    if not cleaned:
        return None

    patterns = [
        r'((?:Istituto\s+Comprensivo|Istituto\s+Tecnico|Istituto\s+Superiore|Istituto|I\.C\.|Liceo|CPIA|Convitto|Scuola)\s+[^\n\.;\|]{3,130})',
        r"((?:all['’]?|presso\s+l['’]?|presso\s+il\s+|presso\s+la\s+)?(?:Istituto\s+Comprensivo|Istituto\s+Tecnico|Istituto\s+Superiore|Istituto|I\.C\.|Liceo|CPIA|Convitto|Scuola)\s+[^\n\.;\|]{3,130})",
        r'(IIS\s+[^\n\.;\|]{3,120})'
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            candidate = _clean_institution_candidate(match.group(1))
            if candidate:
                candidate = re.sub(r"^(?:all['’]?|presso\s+l['’]?|presso\s+il\s+|presso\s+la\s+)", '', candidate, flags=re.IGNORECASE).strip()
                return candidate

    if re.search(r'\binterpell', cleaned, flags=re.IGNORECASE):
        return None

    return None


def _extract_city_from_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    text = unescape(value)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    m = re.search(r'\b([A-Z][A-Za-zÀ-ÖØ-öø-ÿ\' ]{2,40})\s*\([A-Z]{2}\)\b', text)
    if m:
        city = re.sub(r'\s+', ' ', m.group(1)).strip(' -–—,')
        if re.search(r'\b(istituto|liceo|scuola|i\.c\.|iis|cpia|convitto)\b', city, flags=re.IGNORECASE):
            city = None
        if city and len(city) >= 2:
            return city

    phrase_patterns = [
        r"\b(?:a|ad|di|del|della|nel|nella|presso)\s+([A-Z][A-Za-zÀ-ÖØ-öø-ÿ'\- ]{2,35})\b",
    ]
    stop_terms = {
        'tempo determinato', 'classe', 'concorso', 'supplenza', 'interpello', 'docente', 'personale',
        'istituto', 'liceo', 'scuola', 'ic', 'iis', 'cpia', 'convitto'
    }
    for pattern in phrase_patterns:
        for match in re.finditer(pattern, text):
            candidate = re.sub(r'\s+', ' ', match.group(1)).strip(' -–—,')
            lowered = candidate.lower()
            if not candidate or len(candidate) < 3:
                continue
            if any(term in lowered for term in stop_terms):
                continue
            return candidate

    lowered_text = text.lower()
    for province_name in PROVINCE_NAME_TO_REGION.keys():
        if re.search(rf'\b{re.escape(province_name)}\b', lowered_text):
            return ' '.join(part.capitalize() for part in province_name.split('-'))

    return None


def _extract_city_from_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None

    parsed = urlparse(url)
    path = (parsed.path or '').strip('/').lower()
    if not path:
        path = ''

    slug = path.split('/')[-1]
    parts = [p for p in slug.split('-') if p]
    if len(parts) < 2:
        return None

    if parts and re.fullmatch(r'[a-z]{2}', parts[-1]):
        city_tokens = []
        stop_words = {
            'interpello', 'supplenza', 'classe', 'concorso', 'docente', 'personale',
            'scuola', 'istituto', 'liceo', 'ic', 'iis', 'cattedra', 'ore', 'annuale'
        }
        for token in reversed(parts[:-1]):
            if token in stop_words or re.fullmatch(r'\d{1,4}', token):
                break
            city_tokens.insert(0, token)
            if len(city_tokens) >= 3:
                break

        if city_tokens:
            return ' '.join(t.capitalize() for t in city_tokens)

    host = (parsed.netloc or '').lower()
    host_main = host.split(':')[0]
    subdomain = host_main.split('.')[0] if host_main else ''

    m = re.search(r'(?:uat|usp|ust)-([a-z\-]+)', host_main)
    if m:
        token = m.group(1).strip('-')
        if token and token not in {'it'}:
            return ' '.join(part.capitalize() for part in token.split('-') if part)

    m2 = re.search(r'(?:uat|usp|ust)([a-z\-]+)', host_main)
    if m2:
        token = m2.group(1).strip('-')
        if token and token not in {'it'}:
            return ' '.join(part.capitalize() for part in token.split('-') if part)

    if subdomain and subdomain not in {'www', 'web', 'media'} and re.fullmatch(r'[a-z\-]{3,40}', subdomain):
        if subdomain in PROVINCE_NAME_TO_REGION:
            return ' '.join(part.capitalize() for part in subdomain.split('-') if part)

    if subdomain and re.fullmatch(r'[a-z]{2}', subdomain):
        city = PROVINCE_CODE_TO_CITY.get(subdomain.upper())
        if city:
            return city

    return None


def _extract_region_from_text_or_url(text_value: Optional[str], url: Optional[str]) -> Optional[str]:
    text = (text_value or '').lower()

    for region in REGION_NAMES:
        if region.lower() in text:
            return region

    code_match = re.search(r'\(([A-Z]{2})\)', text_value or '')
    if code_match:
        region = PROVINCE_CODE_TO_REGION.get(code_match.group(1).upper())
        if region:
            return region

    if url:
        parsed = urlparse(url)
        host_path = f"{parsed.netloc} {parsed.path}".lower()

        for domain_hint, region in DOMAIN_REGION_HINTS.items():
            if domain_hint in (parsed.netloc or '').lower() and region != 'Italia':
                return region

        code_url = re.search(r'-(?P<code>[a-z]{2})(?:/|$)', parsed.path.lower())
        if code_url:
            region = PROVINCE_CODE_TO_REGION.get(code_url.group('code').upper())
            if region:
                return region

        subdomain = (parsed.netloc or '').split('.')[0].lower()
        if re.fullmatch(r'[a-z]{2}', subdomain):
            region = PROVINCE_CODE_TO_REGION.get(subdomain.upper())
            if region:
                return region

        for province_name, region in PROVINCE_NAME_TO_REGION.items():
            if province_name in host_path:
                return region

    return None


def _fetch_page_html(url: Optional[str]) -> str:
    if not url:
        return ""

    if firecrawl_app:
        try:
            scrape_result = firecrawl_app.scrape(url, formats=['html'])

            if hasattr(scrape_result, 'html') and scrape_result.html:
                return scrape_result.html

            if isinstance(scrape_result, dict):
                html = scrape_result.get('html')
                if html:
                    return html
                data = scrape_result.get('data')
                if isinstance(data, dict) and data.get('html'):
                    return data.get('html')

            data_attr = getattr(scrape_result, 'data', None)
            if isinstance(data_attr, dict) and data_attr.get('html'):
                return data_attr.get('html')
        except Exception as firecrawl_error:
            print(f"Firecrawl fetch failed for {url}: {str(firecrawl_error)}. Falling back to requests")

    try:
        response = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
            }
        )
        if response.status_code != 200:
            return ""
        return response.text
    except requests.exceptions.SSLError as e:
        print(f"SSL fetch failed for {url}: {str(e)}. Retrying with verify=False")
        try:
            response = requests.get(
                url,
                timeout=25,
                verify=False,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
                }
            )
            if response.status_code != 200:
                return ""
            return response.text
        except Exception as retry_error:
            print(f"Retry failed to fetch page html for {url}: {str(retry_error)}")
            return ""
    except Exception as e:
        print(f"Failed to fetch page html for {url}: {str(e)}")
        return ""


def _extract_institution_from_elenco_html(elenco_html: str, elenco_url: str, interpello_link: Optional[str]) -> Optional[str]:
    if not elenco_html or not interpello_link:
        return None

    target_norm = _normalize_url(interpello_link)
    if not target_norm:
        return None

    anchor_pattern = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', re.IGNORECASE)
    for match in anchor_pattern.finditer(elenco_html):
        href_raw = match.group(1).strip()
        href_abs = urljoin(elenco_url, href_raw)
        href_norm = _normalize_url(href_abs)
        if not href_norm:
            continue

        if target_norm != href_norm and target_norm not in href_norm and href_norm not in target_norm:
            continue

        anchor_text = _extract_institution_from_text(match.group(2))
        if _is_plausible_institution_name(anchor_text):
            return anchor_text

        start = max(0, match.start() - 1400)
        end = min(len(elenco_html), match.end() + 1400)
        context_html = elenco_html[start:end]
        context_text = re.sub(r'<script[\s\S]*?</script>', ' ', context_html, flags=re.IGNORECASE)
        context_text = re.sub(r'<style[\s\S]*?</style>', ' ', context_text, flags=re.IGNORECASE)
        context_text = re.sub(r'<[^>]+>', ' ', context_text)
        context_text = unescape(re.sub(r'\s+', ' ', context_text)).strip()

        candidate_patterns = [
            r'((?:Istituto|Liceo|I\.C\.|Istituzione\s+scolastica|Scuola)[^\.;\|\n]{6,120})',
            r'((?:Istituto\s+Comprensivo|Liceo\s+[^\.;\|\n]+|Scuola\s+[^\.;\|\n]+))'
        ]

        for pattern in candidate_patterns:
            m = re.search(pattern, context_text, flags=re.IGNORECASE)
            if m:
                candidate = _clean_institution_candidate(m.group(1))
                if _is_plausible_institution_name(candidate):
                    return candidate

    return None


def _extract_institution_from_link(interpello_link: Optional[str]) -> Optional[str]:
    if not interpello_link:
        return None

    try:
        html = _fetch_page_html(interpello_link)
        if not html:
            return None

        from_title = _extract_institution_from_text(_extract_clean_title_from_html(html))
        if from_title:
            return from_title

        text = re.sub(r'<script[\s\S]*?</script>', ' ', html, flags=re.IGNORECASE)
        text = re.sub(r'<style[\s\S]*?</style>', ' ', text, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = unescape(re.sub(r'\s+', ' ', text)).strip()

        patterns = [
            r'((?:Istituto\s+Comprensivo|I\.C\.|Liceo\s+[^\.;\|\n]+|Scuola\s+[^\.;\|\n]+))',
            r'((?:Istituto|Liceo|Scuola)[^\.;\|\n]{8,140})'
        ]
        for pattern in patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                candidate = _clean_institution_candidate(m.group(1))
                if _is_plausible_institution_name(candidate):
                    return candidate

        return None
    except Exception as e:
        print(f"Institution extraction failed for {interpello_link}: {str(e)}")
        return None


def _extract_institution_from_enriched_fields(interpello_data: dict) -> Optional[str]:
    candidates = [
        interpello_data.get('interpello_name'),
        interpello_data.get('article_title'),
        interpello_data.get('article_subtitle'),
        interpello_data.get('interpello_description'),
        interpello_data.get('article_content'),
    ]

    for value in candidates:
        if not value:
            continue

        text = str(value)
        text = re.sub(r'[`*_>#\-]+', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()[:2500]
        extracted = _extract_institution_from_text(text)
        if _is_plausible_institution_name(extracted):
            return extracted

    return None


def _extract_json_object_from_text(text: str) -> Optional[dict]:
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    cleaned = re.sub(r'[\x00-\x1f]+', '', text)
    match = re.search(r'\{[\s\S]*\}', cleaned)
    if not match:
        return None

    candidate = match.group(0)
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    try:
        parsed = ast.literal_eval(candidate)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None

    return None


def _looks_like_daily_elenco_url(url: str) -> bool:
    parsed = urlparse(url)
    path = (parsed.path or '').strip('/').lower()
    if not path.startswith('interpelli-scuola-'):
        return False

    slug = path.replace('interpelli-scuola-', '')
    parts = [p for p in slug.split('-') if p]
    if len(parts) < 3:
        return False

    year = next((p for p in parts if re.fullmatch(r'20\d{2}', p)), None)
    month = next((p for p in parts if p in ITALIAN_MONTHS), None)
    day = next((p for p in parts if re.fullmatch(r'\d{1,2}', p)), None)
    return bool(year and month and day)


def _extract_daily_date_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = (parsed.path or '').strip('/').lower()
    slug = path.replace('interpelli-scuola-', '')
    parts = [p for p in slug.split('-') if p]

    year = next((p for p in parts if re.fullmatch(r'20\d{2}', p)), None)
    month = next((p for p in parts if p in ITALIAN_MONTHS), None)
    day = next((p for p in parts if re.fullmatch(r'\d{1,2}', p)), None)

    if not (year and month and day):
        return datetime.now().isoformat()

    try:
        dt = datetime(int(year), ITALIAN_MONTHS[month], int(day))
        return dt.isoformat()
    except Exception:
        return datetime.now().isoformat()


def _extract_daily_elenco_links_from_mainpage(main_url: str) -> List[dict]:
    html = _fetch_page_html(main_url)
    if not html:
        return []

    anchor_pattern = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', re.IGNORECASE)
    seen = set()
    results = []

    for match in anchor_pattern.finditer(html):
        href = match.group(1).strip()
        absolute_url = urljoin(main_url, href)
        normalized = _normalize_url(absolute_url)
        if not normalized or normalized in seen:
            continue

        if not _looks_like_daily_elenco_url(absolute_url):
            continue

        seen.add(normalized)
        label = unescape(re.sub(r'<[^>]+>', ' ', match.group(2)))
        label = re.sub(r'\s+', ' ', label).strip()

        if not label:
            slug = urlparse(absolute_url).path.strip('/').replace('interpelli-scuola-', '')
            label = f"Interpelli scuola {slug.replace('-', ' ')}"

        results.append({
            "elenco_name": label,
            "elenco_date": _extract_daily_date_from_url(absolute_url),
            "elenco_link": absolute_url
        })

    return results


def _extract_candidate_interpello_links_from_html(html: str, base_url: str) -> List[dict]:
    anchor_pattern = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', re.IGNORECASE)
    seen = set()
    candidates = []

    for match in anchor_pattern.finditer(html):
        href = match.group(1).strip()
        absolute = urljoin(base_url, href)
        normalized = _normalize_url(absolute)
        if not normalized or normalized in seen:
            continue

        text = unescape(re.sub(r'<[^>]+>', ' ', match.group(2)))
        text = re.sub(r'\s+', ' ', text).strip()

        indicator = f"{absolute.lower()} {text.lower()}"
        if 'interpell' not in indicator and not re.search(r'\.(pdf|doc|docx)$', absolute.lower()):
            continue

        seen.add(normalized)
        candidates.append({"url": absolute, "title": text or None})

    return candidates


def _classify_interpello_link(url: str, html: str) -> str:
    lower_url = (url or '').lower()
    if any(token in lower_url for token in ['/tag/', '/category/', '?s=interpello', '/search']):
        return 'list'
    if re.search(r'\.(pdf|doc|docx)$', lower_url):
        return 'single'

    lower_html = (html or '').lower()
    if 'elenco interpelli' in lower_html or 'archivio interpelli' in lower_html:
        return 'list'

    nested_candidates = _extract_candidate_interpello_links_from_html(html, url)
    if len(nested_candidates) >= 4:
        return 'list'

    if len(nested_candidates) <= 1:
        return 'single'

    ai_result = _classify_interpello_link_ai(url, html)
    if ai_result in ('single', 'list'):
        return ai_result

    return 'single'


def _classify_interpello_link_ai(url: str, html: str) -> Optional[str]:
    if not openai_client:
        return None

    context_text = re.sub(r'<script[\s\S]*?</script>', ' ', html or '', flags=re.IGNORECASE)
    context_text = re.sub(r'<style[\s\S]*?</style>', ' ', context_text, flags=re.IGNORECASE)
    context_text = re.sub(r'<[^>]+>', ' ', context_text)
    context_text = unescape(re.sub(r'\s+', ' ', context_text)).strip()[:7000]

    prompt = f"""
Classifica questo link in una sola categoria:
- single: pagina di un interpello specifico
- list: pagina elenco/archivio/ricerca con più interpelli

Restituisci SOLO JSON valido:
{{"type":"single|list","confidence":0.0}}

URL: {url}
Contesto testo pagina:
{context_text or 'N/D'}
"""

    try:
        response = openai_client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
            temperature=0
        )
        text = getattr(response, 'output_text', '') or ''
        if not text and getattr(response, 'output', None):
            text = response.output[0].content[0].text if response.output[0].content else ''

        parsed = _extract_json_object_from_text(text)
        if not parsed:
            return None

        kind = str(parsed.get('type', '')).strip().lower()
        confidence = float(parsed.get('confidence', 0))
        if kind in ('single', 'list') and confidence >= 0.55:
            return kind
    except Exception as e:
        print(f"AI classification failed for {url}: {str(e)}")

    return None


_INTERPELLI_SOURCE_CONTEXT_CACHE = None


def _get_interpelli_source_context() -> str:
    global _INTERPELLI_SOURCE_CONTEXT_CACHE
    if _INTERPELLI_SOURCE_CONTEXT_CACHE is not None:
        return _INTERPELLI_SOURCE_CONTEXT_CACHE

    html = _fetch_page_html(INTERPELLI_SOURCE_URL)
    if not html:
        _INTERPELLI_SOURCE_CONTEXT_CACHE = ''
        return _INTERPELLI_SOURCE_CONTEXT_CACHE

    text = re.sub(r'<script[\s\S]*?</script>', ' ', html, flags=re.IGNORECASE)
    text = re.sub(r'<style[\s\S]*?</style>', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = unescape(re.sub(r'\s+', ' ', text)).strip()
    _INTERPELLI_SOURCE_CONTEXT_CACHE = text[:10000]
    return _INTERPELLI_SOURCE_CONTEXT_CACHE


def _generate_interpello_article_ai(interpello_data: dict) -> Optional[dict]:
    if not openai_client:
        return None

    prompt = f"""
Sei un giornalista professionista specializzato in interpelli scolastici italiani.
Restituisci SOLO JSON valido nel formato:
{{"article_title":"...","article_subtitle":"...","article_content":"..."}}

Regole:
- article_title: max 110 caratteri, chiaro e informativo.
- article_subtitle: 140-220 caratteri, tono giornalistico professionale.
- article_content: articolo in markdown con Introduzione, Dettagli, Contesto territoriale, Aspetti procedurali, Conclusioni.
- Non inventare dati non presenti.

Dati interpello:
- Nome: {interpello_data.get('interpello_name') or 'N/D'}
- Data: {interpello_data.get('interpello_date') or 'N/D'}
- Regione: {interpello_data.get('region_name') or 'N/D'}
- Città: {interpello_data.get('city_name') or 'N/D'}
- Descrizione: {interpello_data.get('interpello_description') or 'N/D'}
- Link ufficiale: {interpello_data.get('interpello_link') or 'N/D'}
"""

    try:
        response = openai_client.responses.create(model="gpt-4.1", input=prompt, temperature=0.4)
        text = getattr(response, 'output_text', '') or ''
        if not text and getattr(response, 'output', None):
            text = response.output[0].content[0].text if response.output[0].content else ''
        parsed = _extract_json_object_from_text(text)
        if not parsed:
            return None

        title = str(parsed.get('article_title', '')).strip()
        subtitle = str(parsed.get('article_subtitle', '')).strip()
        content = str(parsed.get('article_content', '')).strip()
        if not title or not subtitle or not content:
            return None
        return {"article_title": title, "article_subtitle": subtitle, "article_content": content}
    except Exception as e:
        print(f"AI article generation failed: {str(e)}")
        return None


def _generate_interpello_faq_ai(interpello_data: dict) -> Optional[List[dict]]:
    if not openai_client:
        return None

    source_context = _get_interpelli_source_context()
    prompt = f"""
Sei un esperto di normativa scolastica italiana.
Genera ESATTAMENTE 6 FAQ in JSON valido:
{{"faqs":[{{"question":"...","answer":"..."}}]}}

Regole:
- 6 FAQ esatte.
- Domande pratiche e risposte concise (2-4 frasi).
- Non inventare dati non presenti.

Dati interpello:
- Nome/Istituto: {interpello_data.get('interpello_name') or 'N/D'}
- Data: {interpello_data.get('interpello_date') or 'N/D'}
- Regione: {interpello_data.get('region_name') or 'N/D'}
- Città: {interpello_data.get('city_name') or 'N/D'}
- Descrizione: {interpello_data.get('interpello_description') or 'N/D'}
- Link ufficiale: {interpello_data.get('interpello_link') or 'N/D'}

Contesto pagina interpelli:
{source_context or 'N/D'}
"""

    try:
        response = openai_client.responses.create(model="gpt-4.1", input=prompt, temperature=0.2)
        text = getattr(response, 'output_text', '') or ''
        if not text and getattr(response, 'output', None):
            text = response.output[0].content[0].text if response.output[0].content else ''

        parsed = _extract_json_object_from_text(text)
        if not parsed:
            return None

        items = parsed.get('faqs', [])
        if not isinstance(items, list):
            return None

        faqs = []
        for item in items:
            q = str((item or {}).get('question', '')).strip()
            a = str((item or {}).get('answer', '')).strip()
            if not q or not a:
                continue
            if not q.endswith('?'):
                q = f"{q}?"
            faqs.append({"question": q, "answer": a})

        faqs = faqs[:6]
        return faqs if len(faqs) == 6 else None
    except Exception as e:
        print(f"AI FAQ generation failed: {str(e)}")
        return None


def _append_faq_markdown(content: str, faqs: List[dict]) -> str:
    if not content:
        return content
    cleaned = re.sub(r'##\s+Domande\s+frequenti[\s\S]*$', '', content, flags=re.IGNORECASE).strip()
    faq_section = ['## Domande frequenti'] + [f"### {f['question']}\n{f['answer']}" for f in faqs]
    return f"{cleaned}\n\n" + "\n\n".join(faq_section)


def _enrich_interpello_data(interpello_data: dict) -> dict:
    enriched = dict(interpello_data)
    article = _generate_interpello_article_ai(enriched)
    if article:
        enriched.update(article)
        faqs = _generate_interpello_faq_ai(enriched)
        if faqs:
            enriched['article_content'] = _append_faq_markdown(enriched.get('article_content', ''), faqs)
        enriched['article_generated'] = True

    normalized_institution = _extract_institution_from_enriched_fields(enriched)
    if _is_plausible_institution_name(normalized_institution):
        enriched['interpello_name'] = normalized_institution

    return enriched


def _save_interpello_if_new(supabase: Client, interpello_data: dict, existing_links: set) -> bool:
    link = interpello_data.get('interpello_link')
    normalized = _normalize_url(link)
    if not normalized or normalized in existing_links:
        return False
    supabase.table('interpelli').insert(interpello_data).execute()
    existing_links.add(normalized)
    return True


def _process_interpello_link(
    supabase: Client,
    link_url: str,
    region_name: Optional[str],
    city_name: Optional[str],
    interpello_name: Optional[str],
    interpello_date: Optional[str],
    interpello_description: Optional[str],
    existing_links: set,
    visited: set,
    depth: int = 0
):
    if depth > 2:
        return

    normalized = _normalize_url(link_url)
    if not normalized or normalized in visited:
        return
    visited.add(normalized)

    html = _fetch_page_html(link_url)
    link_type = _classify_interpello_link(link_url, html)

    if link_type == 'list':
        nested = _extract_candidate_interpello_links_from_html(html, link_url)
        for candidate in nested:
            _process_interpello_link(
                supabase=supabase,
                link_url=candidate['url'],
                region_name=region_name,
                city_name=city_name,
                interpello_name=candidate.get('title'),
                interpello_date=interpello_date,
                interpello_description=interpello_description,
                existing_links=existing_links,
                visited=visited,
                depth=depth + 1
            )
        return

    cleaned_title = _clean_institution_candidate(interpello_name)
    institution_name = _extract_institution_from_text(cleaned_title)
    if not _is_plausible_institution_name(institution_name):
        extracted = _extract_institution_from_link(link_url)
        if _is_plausible_institution_name(extracted):
            institution_name = extracted

    page_title = _extract_clean_title_from_html(html)
    geo_context = ' | '.join([p for p in [interpello_name, page_title] if p])
    derived_city = _extract_city_from_text(geo_context) or _extract_city_from_url(link_url)
    derived_region = _extract_region_from_text_or_url(geo_context, link_url)
    safe_city = (city_name or '').strip() or (derived_city or '').strip() or 'Non specificata'
    safe_region = (region_name or '').strip() or (derived_region or '').strip() or 'Non specificata'

    payload = {
        'interpello_name': institution_name if _is_plausible_institution_name(institution_name) else 'Istituto non specificato',
        'interpello_date': interpello_date or datetime.now().isoformat(),
        'interpello_description': interpello_description or '',
        'interpello_link': link_url,
        'city_name': safe_city,
        'region_name': safe_region,
    }

    enriched = _enrich_interpello_data(payload)
    created = _save_interpello_if_new(supabase, enriched, existing_links)
    if created:
        print(f"Saved interpello: {enriched.get('interpello_link')}")

def trigger_bandi_refresh():
    """Calls the Astro API endpoint to refresh the bandi data."""
    print(f"[{datetime.now()}] Triggering bandi refresh at: {REFRESH_ENDPOINT}")
    try:
        response = requests.get(REFRESH_ENDPOINT, timeout=120) # Add a timeout (e.g., 2 minutes)

        if response.status_code == 200:
            try:
                response_data = response.json()
                print(f"[{datetime.now()}] Successfully refreshed bandi data. Response: {response_data.get('message', '')}")
            except requests.exceptions.JSONDecodeError:
                 print(f"[{datetime.now()}] Successfully triggered refresh (Status 200), but response was not valid JSON: {response.text}")
        else:
            print(f"[{datetime.now()}] Failed to refresh bandi data. Status code: {response.status_code}")
            print(f"Response: {response.text}")

    except requests.exceptions.Timeout:
         print(f"[{datetime.now()}] Error: Request timed out while trying to refresh bandi data at {REFRESH_ENDPOINT}")
    except requests.exceptions.RequestException as e:
        print(f"[{datetime.now()}] Error calling refresh endpoint: {e}")
    except Exception as e:
        print(f"[{datetime.now()}] An unexpected error occurred: {e}")

def get_supabase_client() -> Client:
    """Initialize and return a Supabase client"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise Exception("Supabase credentials not found. Please set SUPABASE_URL and SUPABASE_KEY environment variables.")
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_sources_from_supabase() -> List[Dict[str, str]]:
    """Fetch sources with their valid prefixes from Supabase"""
    try:
        supabase = get_supabase_client()
        print(f"supabase: {supabase}, credentials: {SUPABASE_URL}, {SUPABASE_KEY}")
        response = supabase.table('sources').select('*').execute()
        if not response.data:
            print("No sources found in Supabase")
            return []
        
        # Convert to list of dictionaries with link and valid_prefix
        sources = []
        for source in response.data:
            # If valid_prefix is not set, use the link as the prefix
            valid_prefix = source.get('valid_prefix', source.get('link', ''))
            sources.append({
                'link': source.get('link', ''),
                'valid_prefix': valid_prefix
            })
        print(f"sources: {sources}")
        print(f"Fetched {len(sources)} sources from Supabase")
        return sources
    except Exception as e:
        print(f"Error fetching sources from Supabase: {str(e)}")
        return []

def append_to_log_json(log_entry):
    """Send a log entry to the frontend API to be stored"""
    try:
        response = requests.post(f"{FRONTEND_URL}/api/logs/create", json=log_entry)
        if response.status_code == 200:
            print(f"Successfully sent log to frontend API: {log_entry['process']}")
            return True
        else:
            print(f"Failed to send log to frontend API: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"Error sending log to frontend API: {str(e)}")
        return False

def send_telegram_notification(message: str) -> bool:
    """Send a notification via Telegram server"""
    try:
        # response = requests.post(f"{TELEGRAM_URL}/send", params={"message": message})
        # return response.status_code == 200
        return True
    except Exception as e:
        print(f"Failed to send Telegram notification: {str(e)}")
        return False

def scrape_news(source_list: List[Dict[str, str]] = None, pipeline_state: Dict[str, Any] = None) -> List[str]:
    """Scrape news from specified sources"""
    if source_list is None:
        print("No source list provided")
        return []
    
    # Update pipeline state with scraping info
    if pipeline_state is not None:
        pipeline_state["scraping"] = {
            "timestamp": datetime.now().isoformat(),
            "status": "started",
            "sources": [source['link'] for source in source_list],
            "scraped_links": [],
        }
        
    send_telegram_notification("🔄 Avvio processo di scraping...")
    print(f"\n[{datetime.now()}] Starting scraping process...")
    success_count = 0
    news_list = []
    
    for source in source_list:
        try:
            response = requests.post(
                f"{BASE_URL}/scrape_news", 
                params={
                    "url": source['link'],
                    "valid_prefix": source['valid_prefix']
                }
            )
            
            if response.status_code == 200:
                print(f"Successfully scraped {source['link']}")
                scraped_links = response.json()["news_links"]
                news_list.extend(scraped_links)
                
                # Update pipeline state
                if pipeline_state is not None:
                    pipeline_state["scraping"]["scraped_links"].extend(scraped_links)
                
                success_count += 1
            else:
                print(f"Failed to scrape {source['link']}: {response.status_code}")
                # Add failure to pipeline state
                if pipeline_state is not None:
                    pipeline_state["scraping"].setdefault("failures", []).append({
                        "source": source['link'],
                        "status_code": response.status_code
                    })
        except Exception as e:
            print(f"Error scraping {source['link']}: {str(e)}")
            # Add error to pipeline state
            if pipeline_state is not None:
                pipeline_state["scraping"].setdefault("errors", []).append({
                    "source": source['link'],
                    "error": str(e)
                })
    
    # Update pipeline state with final scraping status
    if pipeline_state is not None:
        pipeline_state["scraping"]["status"] = "completed"
        pipeline_state["scraping"]["success_count"] = success_count
        pipeline_state["scraping"]["total_links"] = len(news_list)
    
    print(f"News list: {news_list} INSIDE SENDER")
    return news_list

def check_duplicates(news_list: List[str], pipeline_state: Dict[str, Any] = None) -> List[int]:
    """Check for duplicates and get unique news IDs"""
    if pipeline_state is not None:
        pipeline_state["selected_links"] = {
            "timestamp": datetime.now().isoformat(),
            "process": "selected_links",
            "status": "started",
            "total_links": len(news_list),
            "urls_to_check": news_list
        }
    
    send_telegram_notification("🔄 Avvio controllo duplicati...")
    print(f"\n[{datetime.now()}] Checking for duplicates...")
    print(f"News list: {news_list}")
    link_list = schemas.LinkList(links=news_list)
    try:
        response = requests.post(f"{BASE_URL}/api/news/analyze", json=link_list.model_dump())
        if response.status_code == 200:
            unique_ids = response.json().get("unique_news_ids", [])
            print(f"Found {len(unique_ids)} unique news items")
            
            # Update pipeline state
            if pipeline_state is not None:
                pipeline_state["selected_links"]["status"] = "completed"
                pipeline_state["selected_links"]["unique_news_ids"] = unique_ids
                pipeline_state["selected_links"]["unique_count"] = len(unique_ids)
            
            return unique_ids
        
        print(f"Failed to check duplicates: {response.status_code}")
        # Add failure to pipeline state
        if pipeline_state is not None:
            pipeline_state["selected_links"]["status"] = "failed"
            pipeline_state["selected_links"]["error"] = f"Status code: {response.status_code}"
        
        return []
    except Exception as e:
        print(f"Error checking duplicates: {str(e)}")
        # Add error to pipeline state
        if pipeline_state is not None:
            pipeline_state["selected_links"]["status"] = "error"
            pipeline_state["selected_links"]["error"] = str(e)
        
        return []

def summarize_news(pipeline_state: Dict[str, Any] = None) -> List[str]:
    """Summarize scraped news"""
    if pipeline_state is not None:
        pipeline_state["summarization"] = {
            "timestamp": datetime.now().isoformat(),
            "process": "summarization",
            "status": "started",
            "summarized_news": []
        }
    
    send_telegram_notification("🔄 Avvio processo di sintesi...")
    print(f"\n[{datetime.now()}] Starting summarization process...")
    try:
        response = requests.get(f"{BASE_URL}/summarize_news")
        if response.status_code == 200:
            print("Successfully summarized news")
            summarized_ids = response.json().get("summarized_news_IDs", [])
            summarized_news = response.json().get("summarized_news", [])
            summarized_urls = response.json().get("summarized_urls", [])
            
            # Create URL to ID mapping
            url_to_id_map = {}
            
            # Map URLs to IDs if both arrays exist and have the same length
            if summarized_urls and len(summarized_urls) == len(summarized_ids):
                for i, url in enumerate(summarized_urls):
                    url_to_id_map[url] = summarized_ids[i]
                    print(f"Mapped URL {url} to ID {summarized_ids[i]}")
            
            # Update pipeline state
            if pipeline_state is not None:
                pipeline_state["summarization"]["status"] = "completed"
                pipeline_state["summarization"]["summarized_news_ids"] = summarized_ids
                pipeline_state["summarization"]["summarized_news"] = summarized_news
                pipeline_state["summarization"]["summarized_urls"] = summarized_urls
                pipeline_state["summarization"]["url_to_id_map"] = url_to_id_map
            
            return summarized_ids
        
        print(f"Failed to summarize news: {response.status_code}")
        # Add failure to pipeline state
        if pipeline_state is not None:
            pipeline_state["summarization"]["status"] = "failed"
            pipeline_state["summarization"]["error"] = f"Status code: {response.status_code}"
        
        return []
    except Exception as e:
        print(f"Error summarizing news: {str(e)}")
        # Add error to pipeline state
        if pipeline_state is not None:
            pipeline_state["summarization"]["status"] = "error"
            pipeline_state["summarization"]["error"] = str(e)
        
        return []

def reconstruct_articles(news_ids: List[int], pipeline_state: Dict[str, Any] = None) -> bool:
    """Reconstruct articles for specific IDs"""
    if pipeline_state is not None:
        pipeline_state["reconstruction"] = {
            "timestamp": datetime.now().isoformat(),
            "process": "reconstruction",
            "status": "started",
            "news_ids": news_ids,
            "reconstructed_articles": []
        }
    
    send_telegram_notification(f"🔄 Avvio processo di ricostruzione per {len(news_ids)} articoli...")
    print(f"\n[{datetime.now()}] Reconstructing articles...")
    success_count = 0
    
    for news_id in news_ids:
        try:
            response = requests.post(f"{BASE_URL}/api/news/reconstruct/{news_id}")
            if response.status_code == 200:
                success_count += 1
                print(f"Successfully reconstructed article ID: {news_id}")
                
                # Update pipeline state
                if pipeline_state is not None:
                    pipeline_state["reconstruction"]["reconstructed_articles"].append({
                        "news_id": news_id,
                        "status": "success",
                        "article": response.json()
                    })
            else:
                print(f"Failed to reconstruct article ID {news_id}: {response.status_code}")
                
                # Add failure to pipeline state
                if pipeline_state is not None:
                    pipeline_state["reconstruction"]["reconstructed_articles"].append({
                        "news_id": news_id,
                        "status": "failed",
                        "error": f"Status code: {response.status_code}"
                    })
        except Exception as e:
            print(f"Error reconstructing article ID {news_id}: {str(e)}")
            
            # Add error to pipeline state
            if pipeline_state is not None:
                pipeline_state["reconstruction"]["reconstructed_articles"].append({
                    "news_id": news_id,
                    "status": "error",
                    "error": str(e)
                })
    
    # Update pipeline state with final reconstruction status
    if pipeline_state is not None:
        pipeline_state["reconstruction"]["status"] = "completed"
        pipeline_state["reconstruction"]["success_count"] = success_count
    
    return success_count > 0

def publish_news(news_ids: List[int], pipeline_state: Dict[str, Any] = None) -> int:
    """Publish unique news items"""
    if pipeline_state is not None:
        pipeline_state["publishing"] = {
            "timestamp": datetime.now().isoformat(),
            "process": "publishing",
            "status": "started",
            "news_ids": news_ids,
            "published_articles": []
        }
    
    send_telegram_notification("🔄 Inizio pubblicazione articoli selezionati...")
    print(f"\n[{datetime.now()}] Publishing news...")
    published_count = 0
    
    for news_id in news_ids:
        try:
            response = requests.post(f"{BASE_URL}/api/news/publish/{news_id}")
            if response.status_code == 200:
                published_count += 1
                print(f"Successfully published news ID: {news_id}")
                send_telegram_notification(f"{response.json()['message']}")
                
                # Update pipeline state
                if pipeline_state is not None:
                    pipeline_state["publishing"]["published_articles"].append({
                        "news_id": news_id,
                        "status": "success",
                        "message": response.json().get('message', ''),
                        "wp_id": response.json().get('wp_id', ''),
                        "wp_url": response.json().get('wp_url', '')
                    })
            else:
                print(f"Failed to publish news ID {news_id}: {response.status_code}")
                
                # Add failure to pipeline state
                if pipeline_state is not None:
                    pipeline_state["publishing"]["published_articles"].append({
                        "news_id": news_id,
                        "status": "failed",
                        "error": f"Status code: {response.status_code}"
                    })
        except Exception as e:
            print(f"Error publishing news ID {news_id}: {str(e)}")
            
            # Add error to pipeline state
            if pipeline_state is not None:
                pipeline_state["publishing"]["published_articles"].append({
                    "news_id": news_id,
                    "status": "error",
                    "error": str(e)
                })
    
    # Update pipeline state with final publishing status
    if pipeline_state is not None:
        pipeline_state["publishing"]["status"] = "completed"
        pipeline_state["publishing"]["published_count"] = published_count
    
    if published_count > 0:
        send_telegram_notification(f"✅ Pubblicati con successo {published_count} articoli!")
    else:
        send_telegram_notification("❌ Nessun articolo è stato pubblicato in questa esecuzione")
    
    return published_count

def write_log(message: str):
    with open("log.txt", "a") as f:
        f.write(message)

async def extract_elencos():
    """First process: Extract daily elenco links and save new ones in Supabase"""
    try:
        print(f"[{datetime.now()}] Starting elencos extraction...")
        
        extracted_daily_elencos = _extract_daily_elenco_links_from_mainpage(INTERPELLI_SOURCE_URL)
        if not extracted_daily_elencos:
            print("No daily elenco links found on source page")
            return []

        # Get existing elencos from Supabase
        supabase = get_supabase_client()
        existing_response = supabase.table('elenchi').select('elenco_link').execute()
        existing_links = set(
            _normalize_url(item['elenco_link'])
            for item in (existing_response.data or [])
            if item.get('elenco_link')
        )
        
        # Find new elencos
        new_elencos = []
        for elenco in extracted_daily_elencos:
            link = elenco.get('elenco_link')
            normalized = _normalize_url(link)
            if not normalized or normalized in existing_links:
                continue

            new_elencos.append(elenco)
            supabase.table('elenchi').insert(elenco).execute()
            existing_links.add(normalized)
            print(f"Added new elenco: {elenco.get('elenco_name', 'Unknown')} ({link})")
        
        print(f"Found {len(new_elencos)} new elencos")
        return new_elencos
        
    except Exception as e:
        print(f"Error in extract_elencos: {str(e)}")
        return []

async def extract_interpelli_for_elenco(elenco_url: str):
    """Second process: Extract and classify interpello links for a specific daily elenco URL"""
    try:
        print(f"[{datetime.now()}] Extracting interpelli for: {elenco_url}")

        elenco_html = _fetch_page_html(elenco_url)
        if not elenco_html:
            print(f"No html content for elenco url: {elenco_url}")
            return

        supabase = get_supabase_client()

        existing_interpelli_resp = supabase.table('interpelli').select('interpello_link').execute()
        existing_links = set(
            _normalize_url(item['interpello_link'])
            for item in (existing_interpelli_resp.data or [])
            if item.get('interpello_link')
        )

        candidates = _extract_candidate_interpello_links_from_html(elenco_html, elenco_url)
        if not candidates:
            print(f"No interpello candidates found in {elenco_url}")
            return

        visited = set()
        for candidate in candidates:
            _process_interpello_link(
                supabase=supabase,
                link_url=candidate['url'],
                region_name=None,
                city_name=None,
                interpello_name=candidate.get('title'),
                interpello_date=_extract_daily_date_from_url(elenco_url),
                interpello_description=None,
                existing_links=existing_links,
                visited=visited,
                depth=0
            )
        
    except Exception as e:
        print(f"Error extracting interpelli for {elenco_url}: {str(e)}")

async def process_interpelli():
    """Main function to run both elencos and interpelli processes"""
    try:
        # First process: Extract and check elencos
        new_elencos = await extract_elencos()
        print(f"\n\n\nnew_elencos: {new_elencos}")
        # Second process: Extract interpelli for each new elenco
        for elenco in new_elencos:
            print(f"\n\n\nelenco: {elenco}")
            elenco_url = elenco.get('elenco_link')
            if elenco_url:
                await extract_interpelli_for_elenco(elenco_url)
        
        print(f"[{datetime.now()}] Completed interpelli processing")
        
    except Exception as e:
        print(f"Error in process_interpelli: {str(e)}")

def run_interpelli_pipeline():
    """Execute the interpelli processing pipeline (runs once daily)"""
    try:
        print(f"[{datetime.now()}] Starting daily interpelli processing...")
        asyncio.run(process_interpelli())
        print(f"[{datetime.now()}] Completed daily interpelli processing")
    except Exception as e:
        print(f"Error running interpelli processing: {str(e)}")


def backfill_missing_interpello_institutions(limit: int = 300) -> Dict[str, int]:
    """
    Backfill existing interpelli rows where institution is missing/generic.
    Uses elenco-page context first, then detail-page extraction.
    """
    stats = {
        "scanned": 0,
        "candidates": 0,
        "updated": 0,
        "failed": 0
    }

    try:
        supabase = get_supabase_client()
        elenco_html = _fetch_page_html(INTERPELLI_SOURCE_URL)

        batch_size = 500
        offset = 0
        stop = False

        print(f"[{datetime.now()}] Starting interpelli institution backfill (limit={limit})...")

        while not stop:
            response = (
                supabase
                .table('interpelli')
                .select('id, interpello_name, interpello_link, city_name, region_name')
                .range(offset, offset + batch_size - 1)
                .execute()
            )

            rows = response.data or []
            if not rows:
                break

            for row in rows:
                if stats["scanned"] >= limit:
                    stop = True
                    break

                stats["scanned"] += 1

                current_name = row.get('interpello_name')
                if _is_plausible_institution_name(current_name):
                    continue

                stats["candidates"] += 1
                interpello_link = row.get('interpello_link')

                extracted = _extract_institution_from_elenco_html(
                    elenco_html,
                    INTERPELLI_SOURCE_URL,
                    interpello_link
                )

                if not extracted:
                    extracted = _extract_institution_from_link(interpello_link)

                if not _is_plausible_institution_name(extracted):
                    continue

                try:
                    (
                        supabase
                        .table('interpelli')
                        .update({'interpello_name': extracted})
                        .eq('id', row.get('id'))
                        .execute()
                    )
                    stats["updated"] += 1
                    print(f"Updated interpello id={row.get('id')} -> {extracted}")
                except Exception as update_error:
                    stats["failed"] += 1
                    print(f"Failed updating interpello id={row.get('id')}: {str(update_error)}")

                time.sleep(0.15)

            if len(rows) < batch_size:
                break

            offset += batch_size

        print(f"[{datetime.now()}] Backfill completed: {stats}")
        return stats

    except Exception as e:
        print(f"Error in backfill_missing_interpello_institutions: {str(e)}")
        return stats


def backfill_missing_interpello_locations(limit: int = 300) -> Dict[str, int]:
    """
    Backfill existing interpelli rows where city/region are missing or generic.
    Uses article/title/description context plus URL heuristics.
    """
    stats = {
        "scanned": 0,
        "candidates": 0,
        "updated": 0,
        "failed": 0
    }

    try:
        supabase = get_supabase_client()

        batch_size = 500
        offset = 0
        stop = False

        print(f"[{datetime.now()}] Starting interpelli location backfill (limit={limit})...")

        while not stop:
            response = (
                supabase
                .table('interpelli')
                .select('id, interpello_link, article_title, article_subtitle, interpello_description, city_name, region_name')
                .range(offset, offset + batch_size - 1)
                .execute()
            )

            rows = response.data or []
            if not rows:
                break

            for row in rows:
                if stats["scanned"] >= limit:
                    stop = True
                    break

                stats["scanned"] += 1

                current_city = (row.get('city_name') or '').strip()
                current_region = (row.get('region_name') or '').strip()
                city_missing = not current_city or current_city.lower() == 'non specificata'
                region_missing = not current_region or current_region.lower() == 'non specificata'

                if not city_missing and not region_missing:
                    continue

                stats["candidates"] += 1

                context = ' | '.join([
                    p for p in [
                        row.get('article_title'),
                        row.get('article_subtitle'),
                        row.get('interpello_description')
                    ] if p
                ])

                new_city = current_city
                if city_missing:
                    new_city = _extract_city_from_text(context) or _extract_city_from_url(row.get('interpello_link')) or 'Non specificata'

                new_region = current_region
                if region_missing:
                    new_region = _extract_region_from_text_or_url(context, row.get('interpello_link')) or 'Non specificata'

                if new_city == current_city and new_region == current_region:
                    continue

                try:
                    (
                        supabase
                        .table('interpelli')
                        .update({'city_name': new_city, 'region_name': new_region})
                        .eq('id', row.get('id'))
                        .execute()
                    )
                    stats["updated"] += 1
                except Exception as update_error:
                    stats["failed"] += 1
                    print(f"Failed updating location for interpello id={row.get('id')}: {str(update_error)}")

                time.sleep(0.1)

            if len(rows) < batch_size:
                break

            offset += batch_size

        print(f"[{datetime.now()}] Location backfill completed: {stats}")
        return stats

    except Exception as e:
        print(f"Error in backfill_missing_interpello_locations: {str(e)}")
        return stats

def run_news_pipeline(source_list: List[Dict[str, str]] = None):
    """Execute the complete news pipeline"""

   # trigger_bandi_refresh()

    source_list = fetch_sources_from_supabase()
    if not source_list:
        print("No sources available")
        return
    
    # Initialize a single pipeline state that will contain all information
    pipeline_state = {
        "timestamp": datetime.now().isoformat(),
        "process": "pipeline",
        "status": "started",
        "sources": [source['link'] for source in source_list],
        "pipeline_id": datetime.now().strftime("%Y%m%d%H%M%S"),
        # Process-specific data will be added to this dictionary as the pipeline progresses
    }
    
    write_log(f"---------------------------------------------\nStarting pipeline at {datetime.now()}\n\n\n\n\n\n")
    send_telegram_notification("🔄 Avvio pipeline delle notizie...")
    
    print(f"\n{'='*50}")
    print(f"{'='*50}")
    
    try:
        # Step 1: Scrape
        news_list = scrape_news(source_list, pipeline_state)
        if not news_list:
            print("No news found, stopping pipeline")
            pipeline_state["status"] = "no-news"
            pipeline_state["message"] = "No news found"
            # Send the comprehensive log entry
            append_to_log_json(pipeline_state)
            return
        
        print(f"News list: {news_list}, type of news_list: {type(news_list)}")
        
        # Step 2: Check duplicates
        unique_ids = check_duplicates(news_list, pipeline_state)
        pipeline_state["unique_ids"] = unique_ids
        
        if not unique_ids:
            print("No unique articles found, stopping pipeline")
            pipeline_state["status"] = "no-news"
            pipeline_state["message"] = "No unique articles found"
            # Send the comprehensive log entry
            append_to_log_json(pipeline_state)
            return
        
        # Step 3: Summarize
        summarized_ids = summarize_news(pipeline_state)
        if not summarized_ids:
            print("No articles to summarize, stopping pipeline")
            pipeline_state["status"] = "no-news"
            pipeline_state["message"] = "No articles to summarize"
            # Send the comprehensive log entry
            append_to_log_json(pipeline_state)
            return
        
        pipeline_state["summarized_ids"] = summarized_ids
        
        # Step 4: Reconstruct articles
        if not reconstruct_articles(summarized_ids, pipeline_state):
            print("No articles reconstructed, stopping pipeline")
            pipeline_state["status"] = "no-news"
            pipeline_state["message"] = "No articles reconstructed"
            # Send the comprehensive log entry
            append_to_log_json(pipeline_state)
            return
        
        # Step 5: Publish
        published_count = publish_news(summarized_ids, pipeline_state)
        pipeline_state["published_count"] = published_count
        
        # Update pipeline status based on publishing results
        if published_count > 0:
            pipeline_state["status"] = "completed"
        else:
            pipeline_state["status"] = "no-news"
            pipeline_state["message"] = "No articles published"
        
        # Send the comprehensive log entry with complete pipeline information
        append_to_log_json(pipeline_state)
        
        print(f"\n{'='*50}")
        print(f"{'='*50}\n")
    
    except Exception as e:
        print(f"Error in pipeline: {str(e)}")
        pipeline_state["status"] = "error"
        pipeline_state["error"] = str(e)
        # Send the comprehensive log entry with error information
        append_to_log_json(pipeline_state)

def schedule_pipeline():
    """Schedule the pipeline to run at different times"""
    # Schedule interpelli processing once daily at 12:00
    schedule.every().day.at("12:00").do(run_interpelli_pipeline)
    
    # Schedule for every hour between start and end time
    for hour in range(hour_to_iniziate, hour_to_end):
        if (hour - hour_to_iniziate) % 1 == 0:  # Run every hour
            schedule.every().day.at(f"{hour:02d}:00").do(run_news_pipeline)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    try:
        # Run once immediately with sources from Supabase
        run_news_pipeline()
        # Then schedule future runs
        schedule_pipeline()
        trigger_bandi_refresh()
    except KeyboardInterrupt:
        print("\nShutting down news pipeline scheduler...")
    except Exception as e:
        print(f"Error in main execution: {str(e)}")
