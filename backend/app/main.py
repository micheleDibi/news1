import os
from typing import List, Union
import json
import instructor
from openai import OpenAI
import anthropic
from pydantic import BaseModel
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Depends
import uvicorn
from . import schemas, models, database
from .database import engine, get_db, get_supabase_client
from sqlalchemy.orm import Session
from urllib.parse import urlparse, urljoin
from fastapi.middleware.cors import CORSMiddleware
from enum import Enum
from fastapi.responses import JSONResponse
from requests.auth import HTTPBasicAuth
from datetime import datetime, timedelta
import pytz
from .variables_edunews import *
from firecrawl import Firecrawl
import boto3
import math
import re

class ExtractSchema(BaseModel):
    title: str
    facts: list[str]
    context: str
    length_in_paragraphs: float = None
    location: str = None
    date: str = None
    language: str = None

load_dotenv()

models.Base.metadata.create_all(bind=engine)
FIRECRAWL_API_KEY_EXTRACT = os.getenv("FIRECRAWL_API_KEY")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = instructor.patch(OpenAI(api_key=OPENAI_API_KEY))
client_openai = OpenAI(api_key=OPENAI_API_KEY)
claude_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
app = FastAPI()
firecrawl_app = Firecrawl(api_key=FIRECRAWL_API_KEY)
firecrawl_app_extract = Firecrawl(api_key=FIRECRAWL_API_KEY_EXTRACT)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def write_log(message: str):
    try:
        with open("log.txt", "a") as f:
            f.write(message)
    except Exception as e:
        print(f"Error writing log: {str(e)}")

def create_log_message_summarize(summarized_news: List[schemas.News]) -> str:
    try:
        log_message = "---------------------------------------------\nSummarized news:\n"
        for news in summarized_news:
            log_message += f"----------\nTitle: \n{news.title}\n\n"
        log_message += f"Facts: \n{', '.join(news.facts)}\n\n" 
        log_message += f"Context: \n{news.context}\n\n"
        log_message += "\n\n\n"
    except Exception as e:
        print(f"Error creating log message: {str(e)}")
        return None
    return log_message


def filter_existing_links(all_links: List[str], db: Session) -> List[str]:
    """
    Filter out links that already exist in database or to_scrape.json
    """
    with open('to_scrape.json', 'r') as f:
        to_scrape = json.load(f)
    print(f"all_links: {all_links}")

    filtered_links = []
    for link in all_links:
        if link not in to_scrape:
            filtered_links.append(link)
            
    return filtered_links

@app.post("/scrape_news")
async def scrape_news(url: str, valid_prefix: str = None, db: Session = Depends(get_db)):

    all_links: List[str] = get_links_from_url_via_firecrawl(url)
    print(f"all_links: {all_links}")
    filtered_links = filter_existing_links(all_links, db)
    #news_list: List[str] = get_news_links_from_all_links_via_openai(filtered_links, root_url)
    news_list = filtered_links

    #remove external links
    prefix_to_check = valid_prefix if valid_prefix else url
    news_list = [link for link in news_list if link.startswith(prefix_to_check)]
    news_list = news_list[:3]

    print(f"News list: {news_list}")
    insert_news_into_json(news_list, db)

    return {"news_links": news_list}

@app.post("/api/news/analyze")
async def analyze_news(unpublished_news: schemas.LinkList, db: Session = Depends(get_db)):
    """Analyze news using chain-of-thought with multiple OpenAI calls"""

    print(f"Unpublished news: {unpublished_news.links}")
    try:
        # type: List[models.New]
        published_news, recent_news = get_published_and_recent_news(db) 

        comparison_text: str = get_comparison_text(published_news, unpublished_news.links)
        print(f"Comparison text: {comparison_text}")
        events_to_publish: schemas.EventList = get_unpublished_events_via_openai(comparison_text)
        #send_telegram_notifications([unpublished_events, events_to_publish_message])
        print(f"Events to publish: {events_to_publish}")
        
        if events_to_publish is None:
            return {
                "all_news_analysis": None,
                "unique_news_ids": [],
                "unique_urls": [],
                "error": "Failed to get events from OpenAI"
            }
            
        #get only the first ID of the Events
        simplified_selection = [group.links[0] for group in events_to_publish.events]
        print(f"Simplified selection: {simplified_selection}")
        
        to_scrape = read_to_scrape_file('to_scrape.json')
        for link in simplified_selection:
            to_scrape[link] = "to_summarize"
        with open('to_scrape.json', 'w') as f:
            json.dump(to_scrape, f, indent=2)

        return {
            "all_news_analysis": events_to_publish,
            "unique_news_ids": simplified_selection,
            "unique_urls": simplified_selection,  # At this stage, the IDs are the URLs
        }

    except Exception as e:
        print(f"Error in analyze_news: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/summarize_news")
async def summarize_news(db: Session = Depends(get_db)):
    summarized_news = []
    summarized_news_ids = []
    summarized_urls = []  # Track the URLs for each ID
    to_scrape: List[dict] = read_to_scrape_file('to_scrape.json')

    for url, status in to_scrape.items():
        if status != "to_summarize":
            continue
        try:
            print(f"Summarizing news from {url}")
            parsed_content: schemas.News = get_news_from_link_via_firecrawl(url)
            print(f"Parsed content: {parsed_content}")
            summary: schemas.News = summarize_news_content_via_openai(parsed_content)
            print(f"Summary: {summary}")
            summarized_news.append(summary)
            id = store_summarized_news(db, url, summary)
            print(f"Summarized news ID: {id}")
            summarized_news_ids.append(id)
            summarized_urls.append(url)  # Store the URL for this ID
            print(f"Summarized news ID: {id}, until now {summarized_news_ids}")
            to_scrape[url] = "summarized" if summary is not None else None
            print(f"URL {url} = {to_scrape[url]}")
        except Exception as e:
            return {"error": str(e)}
        
    update_to_scrape_file(to_scrape)
    return {
        "summarized_news": summarized_news, 
        "summarized_news_IDs": summarized_news_ids,
        "summarized_urls": summarized_urls  # Return the URLs with their IDs
    }

@app.post("/api/news/reconstruct/{news_id}")
async def reconstruct_specific_article(news_id: int, db: Session = Depends(get_db)):

    news_item: models.New = get_new_with_id(news_id, db)
    article_response: schemas.NewsArticle = get_reconstructed_article_via_claude(news_item)
    if article_response is None:
        print("Claude reconstruction failed, falling back to OpenAI")
        article_response = get_reconstructed_article_via_openai(news_item)
    update_news_item_with_reconstruction(news_item, article_response, db)
    return article_response


from google.cloud import texttospeech

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("CREDENTIALS_GOOGLE_SPEECH", "google-credentials.json")

async def convert_text_to_audio(text: str, id: int):
    """
    Converts text to speech using Google Cloud Text-to-Speech API,
    splitting the text into three parts, generating audio for each,
    concatenating them, and uploading to S3.
    
    Args:
        text (str): The text you want to convert into speech.
        id (int): The ID to use for naming the output audio file.
    """
    id_str = str(id)

    client = texttospeech.TextToSpeechClient()

    # Simple de-markdowning, corrected regex patterns and replacements
    processed_text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    processed_text = re.sub(r'\*\*(.*?)\*\*', r'\1', processed_text)
    processed_text = re.sub(r'__(.*?)__', r'\1', processed_text)
    processed_text = re.sub(r'\*(.*?)\*', r'\1', processed_text)
    processed_text = re.sub(r'_(.*?)_', r'\1', processed_text)
    processed_text = re.sub(r'~~(.*?)~~', r'\1', processed_text)
    processed_text = re.sub(r'`(.*?)`', r'\1', processed_text)
    processed_text = re.sub(r'```[a-zA-Z]*\n(.*?)\n```', r'\1', processed_text, flags=re.DOTALL)
    processed_text = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1', processed_text)
    processed_text = re.sub(r'!\[(.*?)\]\((.*?)\)', r'\1', processed_text)
    processed_text = re.sub(r'^\*\s+', '', processed_text, flags=re.MULTILINE)
    processed_text = re.sub(r'^-\s+', '', processed_text, flags=re.MULTILINE)
    processed_text = re.sub(r'^\d+\.\s+', '', processed_text, flags=re.MULTILINE)
    processed_text = re.sub(r'^-{3,}\s*$', '', processed_text, flags=re.MULTILINE)
    processed_text = re.sub(r'^\*{3,}\s*$', '', processed_text, flags=re.MULTILINE)
    processed_text = re.sub(r'^_{3,}\s*$', '', processed_text, flags=re.MULTILINE)
    processed_text = re.sub(r'^>\s*', '', processed_text, flags=re.MULTILINE)

    # Intelligent newline handling to create better sentence breaks for TTS
    # 1. Consolidate multiple newlines (more than 2) into a double newline (paragraph-like separation)
    processed_text = re.sub(r'\n{3,}', '\n\n', processed_text)
    # 2. For remaining double newlines (paragraph breaks), replace with a period and two spaces if no punctuation.
    processed_text = re.sub(r'(?<![.!?;:])\n\n', '.  ', processed_text) 
    # 3. For single newlines, replace with a period and a space if no punctuation.
    processed_text = re.sub(r'(?<![.!?;:])\n', '. ', processed_text)
    # 4. Clean up: remove leading/trailing whitespace from lines that might have become empty.
    processed_text = '\n'.join([line.strip() for line in processed_text.split('\n') if line.strip()])
    # 5. Consolidate multiple spaces into a single space.
    processed_text = re.sub(r'\s{2,}', ' ', processed_text).strip()
    # 6. Ensure space after common punctuation if missing, to help TTS phrasing.
    processed_text = re.sub(r'([.!?;:])(?=[^\s])', r'\1 ', processed_text)
    # 7. Remove any space before punctuation
    processed_text = re.sub(r'\s+([.!?;:])', r'\1', processed_text).strip()

    full_text = processed_text

    part_length = math.ceil(len(full_text) / 3)
    text_parts: list[str] = []
    if not full_text: # Handle empty text case
        # Or decide to return an error or a silent audio
        s3_client = boto3.client(
            's3',
            region_name=os.getenv('AWS_REGION'),
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        )
        file_key = f"audios/audio_{id_str}.mp3"
        # Upload an empty or minimal MP3 file, or handle this case as an error
        # For now, let's assume we upload an empty Body, which might be invalid for S3/MP3
        # A better approach would be to have a pre-generated silent MP3 file.
        s3_client.put_object(
            Bucket=os.getenv('AWS_BUCKET_NAME'),
            Key=file_key,
            Body=b'', # Empty byte string
            ContentType='audio/mpeg'
        )
        s3_url = f"https://{os.getenv('AWS_BUCKET_NAME')}.s3.{os.getenv('AWS_REGION')}.amazonaws.com/{file_key}"
        return s3_url


    for i in range(3):
        start_index = i * part_length
        end_index = (i + 1) * part_length
        text_parts.append(full_text[start_index:end_index])

    audio_contents: list[bytes] = []

    for text_part in text_parts:
        if not text_part.strip():  # Skip empty parts
            continue

        # 3️⃣ Set the input text
        input_text_segment = texttospeech.SynthesisInput(text=text_part)

        # 4️⃣ Select the voice parameters (using Neural2 voice)
        voice = texttospeech.VoiceSelectionParams(
            language_code="it-IT",
            name="it-IT-Journey-O",
            ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
        )

        # 5️⃣ Select the audio configuration
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3
        )

        # 6️⃣ Request text-to-speech conversion
        print(f"Sending request to Google Cloud Text-to-Speech API for part: '{text_part[:30]}...'")
        response = client.synthesize_speech(
            input=input_text_segment,
            voice=voice,
            audio_config=audio_config
        )
        if response.audio_content:
            audio_contents.append(response.audio_content)

    # Concatenate audio buffers
    combined_audio_buffer = b"".join(audio_contents)


    # 6️⃣ Prepare to upload to S3
    s3_client = boto3.client(
        's3',
        region_name=os.getenv('AWS_REGION'),
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    )
    print(f"s3_client = {s3_client}")

    # Construct the file key (path inside the bucket)
    file_key = f"audios/audio_{id_str}.mp3"


    # 7️⃣ Upload to S3
    s3_client.put_object(
        Bucket=os.getenv('AWS_BUCKET_NAME'),
        Key=file_key,
        Body=combined_audio_buffer,
        ContentType='audio/mpeg'
    )


    # 8️⃣ Construct the S3 public URL (if your bucket policy allows public read)
    s3_url = f"https://{os.getenv('AWS_BUCKET_NAME')}.s3.{os.getenv('AWS_REGION')}.amazonaws.com/{file_key}"

    

    return s3_url
from PIL import Image
from io import BytesIO
import cloudscraper

# Parole chiave da escludere nelle URL/alt delle immagini (loghi, icone, banner, tracking pixel)
_IMAGE_BLACKLIST = {'logo', 'icon', 'favicon', 'sprite', 'avatar', 'badge', 'banner-ad',
                    'tracking', 'pixel', 'spacer', 'arrow', 'button', 'spinner', 'loader',
                    'emoji', 'share', 'social', 'facebook', 'twitter', 'whatsapp', 'linkedin',
                    'pinterest', 'telegram', 'youtube', 'instagram', 'tiktok', 'cookie'}

def _is_blacklisted(url: str, alt: str = "") -> bool:
    """Controlla se un URL o alt text contiene parole da escludere."""
    url_lower = url.lower()
    alt_lower = alt.lower() if alt else ""
    for word in _IMAGE_BLACKLIST:
        if word in url_lower or word in alt_lower:
            return True
    # Escludi formati non fotografici
    if url_lower.endswith('.svg') or url_lower.endswith('.gif') or url_lower.endswith('.ico'):
        return True
    # Escludi immagini encode base64
    if url_lower.startswith('data:'):
        return True
    return False

def _make_absolute_url(src: str, base_url: str) -> str:
    """Converte URL relativo in assoluto."""
    if not src:
        return ""
    if src.startswith('//'):
        return 'https:' + src
    if src.startswith('/') or not src.startswith('http'):
        return urljoin(base_url, src)
    return src

def _get_image_dimensions(url: str, scraper) -> tuple:
    """
    Scarica l'immagine e restituisce (width, height).
    Usa stream per limitare il download a immagini ragionevoli.
    Ritorna (0, 0) in caso di errore.
    """
    try:
        resp = scraper.get(url, timeout=12, stream=True)
        if resp.status_code != 200:
            return (0, 0)
        content_type = resp.headers.get('content-type', '')
        if 'image' not in content_type and 'octet-stream' not in content_type:
            return (0, 0)
        # Limita il download a 10MB per sicurezza
        content_length = resp.headers.get('content-length')
        if content_length and int(content_length) > 10_000_000:
            return (0, 0)
        img_data = BytesIO(resp.content)
        img = Image.open(img_data)
        return img.size  # (width, height)
    except Exception as e:
        print(f"  [IMG] Errore dimensioni per {url[:80]}...: {e}")
        return (0, 0)

def _extract_srcset_candidates(img_tag, base_url: str) -> list:
    """Estrae candidati dal srcset, ordinati per larghezza decrescente."""
    candidates = []
    srcset = img_tag.get('srcset', '')
    if not srcset:
        return candidates
    for entry in srcset.split(','):
        parts = entry.strip().split()
        if len(parts) >= 2:
            url = _make_absolute_url(parts[0], base_url)
            descriptor = parts[1]
            if descriptor.endswith('w'):
                try:
                    w = int(descriptor[:-1])
                    candidates.append((url, w))
                except ValueError:
                    pass
    # Ordina per larghezza decrescente (le piu grandi prima)
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates

def find_best_image(source_url: str, min_width: int = 1200) -> str:
    """
    Trova la migliore immagine dalla pagina sorgente dell'articolo.

    Strategia multi-livello:
      1. og:image / twitter:image (meta tag, spesso immagini hero di alta qualita)
      2. Immagini dal srcset con larghezza >= min_width (dichiarata nel markup)
      3. Tag <img> con attributo width >= min_width
      4. Tag <img> con classe/attributo che suggerisce immagine principale
      5. Tutte le <img> rimanenti — scarica e verifica dimensioni reali

    Ritorna l'URL dell'immagine trovata o None.
    """
    print(f"\n[IMAGE FINDER] Cercando immagine per: {source_url}")

    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
    )

    try:
        response = scraper.get(source_url, timeout=15)
        if response.status_code != 200:
            print(f"  [IMAGE FINDER] Errore HTTP {response.status_code}")
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
    except Exception as e:
        print(f"  [IMAGE FINDER] Errore fetch pagina: {e}")
        return None

    # ── FASE 1: Meta tag og:image e twitter:image ──────────────────────
    meta_candidates = []
    for attr_name, attr_key in [('property', 'og:image'), ('name', 'twitter:image')]:
        tag = soup.find('meta', attrs={attr_name: attr_key})
        if tag:
            content = tag.get('content', '').strip()
            if content:
                url = _make_absolute_url(content, source_url)
                if not _is_blacklisted(url):
                    meta_candidates.append(url)

    # Verifica dimensioni dei meta tag (spesso sono gia >= 1200px)
    for url in meta_candidates:
        w, h = _get_image_dimensions(url, scraper)
        print(f"  [META] {url[:80]}... → {w}x{h}")
        if w >= min_width:
            print(f"  [IMAGE FINDER] ✓ Trovata via meta tag: {w}x{h}")
            return url

    # ── FASE 2: srcset con larghezza dichiarata >= min_width ───────────
    srcset_urls = []
    for img in soup.find_all('img'):
        alt = img.get('alt', '')
        candidates = _extract_srcset_candidates(img, source_url)
        for url, declared_w in candidates:
            if declared_w >= min_width and not _is_blacklisted(url, alt):
                srcset_urls.append(url)

    # Verifica dimensioni reali delle migliori candidate srcset
    for url in srcset_urls[:5]:
        w, h = _get_image_dimensions(url, scraper)
        print(f"  [SRCSET] {url[:80]}... → {w}x{h}")
        if w >= min_width:
            print(f"  [IMAGE FINDER] ✓ Trovata via srcset: {w}x{h}")
            return url

    # ── FASE 3: <img> con attributo width >= min_width ─────────────────
    for img in soup.find_all('img'):
        width_attr = img.get('width', '')
        try:
            if int(str(width_attr).replace('px', '')) >= min_width:
                src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                if src:
                    url = _make_absolute_url(src, source_url)
                    alt = img.get('alt', '')
                    if not _is_blacklisted(url, alt):
                        w, h = _get_image_dimensions(url, scraper)
                        print(f"  [WIDTH ATTR] {url[:80]}... → {w}x{h}")
                        if w >= min_width:
                            print(f"  [IMAGE FINDER] ✓ Trovata via width attr: {w}x{h}")
                            return url
        except (ValueError, TypeError):
            pass

    # ── FASE 4: <img> con classi/attributi che suggeriscono immagine principale ─
    priority_patterns = ['featured', 'hero', 'main-image', 'article-image', 'post-image',
                         'cover', 'thumb-big', 'image-full', 'wp-post-image', 'detail',
                         'foto_large', 'img_articolo', 'image-principale']

    for img in soup.find_all('img'):
        img_str = str(img).lower()
        for pattern in priority_patterns:
            if pattern in img_str:
                src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                if src:
                    url = _make_absolute_url(src, source_url)
                    alt = img.get('alt', '')
                    if not _is_blacklisted(url, alt):
                        w, h = _get_image_dimensions(url, scraper)
                        print(f"  [PRIORITY CLASS] {url[:80]}... → {w}x{h}")
                        if w >= min_width:
                            print(f"  [IMAGE FINDER] ✓ Trovata via classe prioritaria: {w}x{h}")
                            return url
                break  # Una volta trovato il pattern, passa alla prossima img

    # ── FASE 5: Scan tutte le <img> rimanenti ─────────────────────────
    # Raccoglie tutte le immagini non ancora testate e verifica le dimensioni
    all_img_urls = []
    tested_urls = set(meta_candidates + srcset_urls)

    for img in soup.find_all('img'):
        for attr in ['src', 'data-src', 'data-lazy-src', 'data-original', 'data-full-url']:
            src = img.get(attr)
            if src:
                url = _make_absolute_url(src, source_url)
                alt = img.get('alt', '')
                if url not in tested_urls and not _is_blacklisted(url, alt):
                    all_img_urls.append(url)
                    tested_urls.add(url)

    # Testa al massimo 10 immagini rimanenti
    for url in all_img_urls[:10]:
        w, h = _get_image_dimensions(url, scraper)
        print(f"  [SCAN] {url[:80]}... → {w}x{h}")
        if w >= min_width:
            print(f"  [IMAGE FINDER] ✓ Trovata via scan generale: {w}x{h}")
            return url

    # ── FASE 6: Fallback — rilassa il vincolo a 800px ──────────────────
    # Se non troviamo nulla >= 1200px, proviamo con un minimo di 800px
    print(f"  [IMAGE FINDER] Nessuna immagine >= {min_width}px. Provo con 800px...")
    best_url = None
    best_width = 0

    # Ricontrolla i meta tag e le immagini gia scaricate con soglia ridotta
    for url in meta_candidates:
        w, h = _get_image_dimensions(url, scraper)
        if w >= 800 and w > best_width:
            best_url = url
            best_width = w

    for url in all_img_urls[:10]:
        w, h = _get_image_dimensions(url, scraper)
        if w >= 800 and w > best_width:
            best_url = url
            best_width = w

    if best_url:
        print(f"  [IMAGE FINDER] ✓ Fallback a {best_width}px: {best_url[:80]}...")
        return best_url

    print(f"  [IMAGE FINDER] ✗ Nessuna immagine adatta trovata")
    return None
    

@app.post("/api/news/publish/{news_id}")
async def publish_to_cms(news_id: int, db: Session = Depends(get_db)):
    """Publish news to CMS API"""
    # Fetch the news item from database
    news_item = db.query(models.New).filter(models.New.id == news_id).first()

    print(f"news_item = {news_item}")

    print(f"news_item.proposed_title = {news_item.proposed_title}")
    print(f"news_item.proposed_response = {news_item.proposed_response}")

    if not news_item:
        raise HTTPException(status_code=404, detail="News item not found")

    try:
        text_to_audio = f"Titolo: {news_item.proposed_title}\n\n{news_item.proposed_response}"
        summary, title_summary = await generate_summary(news_item.proposed_response)
        print(f"Summary: {summary}")
        image_url = find_best_image(news_item.url)
        print(f"Image URL: {image_url}")
        proposed_slug, category_slug = generate_slugs(news_item.proposed_title, news_item.category)
        print(f"Proposed slug: {proposed_slug}")
        # Format article data for CMS API
        article_data = {
            "title": news_item.proposed_title,
            "content": news_item.proposed_response,
            "category": news_item.category,
            "excerpt": news_item.proposed_subtitle,
            "slug": proposed_slug,
            "category_slug": category_slug,
            "published_at": datetime.now(ITALY_TZ).isoformat(),
            "image_url": image_url,
            "source": news_item.url,
            "isdraft": True,
            "creator": "AI News Generator",
            "tags": news_item.tags,
            "summary": summary,
            "title_summary": title_summary
        }

        print(f"article_data = {article_data}")

        # Send to CMS API
        CMS_API_URL = f"{os.getenv('FRONTEND_URL', 'http://localhost:4321')}/api/articles/create"
        print(f"CMS_API_URL = {CMS_API_URL}")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('API_SECRET_KEY')}"
        }

        response = requests.post(CMS_API_URL, headers=headers, json=article_data)
        print(f"response = {response}")
        if response.status_code == 200:
            # Update local database with published status
            news_item.is_published = True
            db.commit()
            return {
                "success": True,
                "message": "Article published successfully",
                "data": response.json()
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to publish to CMS: {response.text}, "
            )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error publishing to CMS: {str(e)}"
        )




def generate_slugs(proposed_title: str, category: str):
    print(f"Proposed title: {proposed_title}")
    print(f"Category: {category}")
    proposed_slug = proposed_title.lower() \
        .replace('università', 'universita') \
        .replace(' ', '-') \
        .replace("'", '') \
        .replace(':', '') \
        .replace(',', '') \
        .replace('.', '') \
        .replace('?', '') \
        .replace('!', '') \
        .replace('(', '') \
        .replace(')', '') \
        .replace('[', '') \
        .replace(']', '') \
        .replace('{', '') \
        .replace('}', '') \
        .replace('@', '') \
        .replace('#', '') \
        .replace('$', '') \
        .replace('%', '') \
        .replace('^', '') \
        .replace('&', '') \
        .replace('*', '') \
        .replace('+', '') \
        .replace('=', '') \
        .replace('|', '') \
        .replace('\\', '') \
        .replace('/', '') \
        .replace('<', '') \
        .replace('>', '') \
        .replace('`', '') \
        .replace('~', '') \
        .replace(';', '') \
        .replace('"', '') \
        .strip('-')
    
    print(f"Proposed slug: {proposed_slug}")

    category_slug = category.lower() \
        .replace('università', 'universita') \
        .replace(r'[^\w\s-]', '') \
        .replace(r'\s+', '-') \
        .replace(r'--+', '-') \
        .strip()
    
    print(f"Category slug: {category_slug}")

    return proposed_slug, category_slug

def get_content_and_root_url(url: str):
    try:
        response = requests.get(url)
        content = response.text
        parsed_url = urlparse(url)
        root_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        return content, root_url
    except Exception as e:
        print(f"Error getting content and root url: {str(e)}")
        return None, None


def get_news_links_from_all_links_via_openai(all_links: List[str], root_url: str) -> List[str]:

    if all_links is None:
        return None
    
    try:
        news_list = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": f"{SCRAPPING_URLS_PROMPT}"},
                    {"role": "user", "content": f"News: {all_links}"},
                ],
            response_model=schemas.NewsList,
        )
        final_news = [f"{root_url}/{new}" if not new.startswith('http') else new for new in news_list.news]
    except Exception as e:
        print(f"Error getting news links from all links: {str(e)}")
        return None
    return final_news

def insert_news_into_json(news_list: List[str], db: Session = Depends(get_db)):
    if news_list is None:
        return None
    with open('to_scrape.json', 'r') as f:
        to_scrape = json.load(f)

    for new in news_list:

        existing_news = db.query(models.New).filter(models.New.url == new).first()

        if existing_news:
            print(f"Skipping {new}, already in database")
            continue
        if new not in to_scrape:
            to_scrape[new] = "" 
        else:
            print(f"Skipping {new}, already in database")
    
    with open('to_scrape.json', 'w') as f:
        json.dump(to_scrape, f, indent=2)


def read_to_scrape_file(file_path: str) -> dict:
    """
    Reads the `to_scrape.json` file and returns its contents as a dictionary.
    """
    with open(file_path, 'r') as f:
        return json.load(f)

def update_to_scrape_file(to_scrape: dict, file_path: str = 'to_scrape.json') -> None:
    """
    Updates the `to_scrape.json` file with the provided dictionary.
    """
    with open(file_path, 'w') as f:
        json.dump(to_scrape, f, indent=2)

def get_news_from_link_via_firecrawl(link: str) -> str:
    try:
        print(f"Scraping URL: {link}")
        print(f"extract api key: {firecrawl_app_extract.api_key}")

        # Define the JSON schema for the News model
        news_schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "facts": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "context": {"type": "string"},
                "length_in_paragraphs": {"type": "number"},
                "location": {"type": "string"},
                "date": {"type": "string"},
                "language": {"type": "string"}
            },
            "required": ["title", "facts", "context"]
        }
        data = firecrawl_app_extract.extract(
           urls=[link],
            prompt=SUMMARIZING_PROMPT,
            schema=news_schema
        )
        print(f"Extract response: {data}")
        # Extract the actual data from the response
        extracted_data = data.data if hasattr(data, 'data') else data
        print(f"Extracted data: {extracted_data}")
        return extracted_data
    except Exception as e:
        print(f"Error getting news from link via firecrawl: {str(e)}")
        return None

def get_links_from_url_via_firecrawl(link: str) -> List[str]:
    try:
        scrape_result = firecrawl_app.scrape(link, formats=['links'])
        print(f"Scrape result: {scrape_result}")
        # Extract links from the response object
        links = scrape_result.links if hasattr(scrape_result, 'links') else []
        print(f"Extracted links: {links}")
        return links
    except Exception as e:
        print(f"Error getting links from url via firecrawl: {str(e)}")
        return None

    
def summarize_news_content_via_openai(parsed_content: str) -> schemas.News:
    """
    Summarizes the given content using OpenAI's chat model.
    """

    if parsed_content is None:
        return None
    try:
        summary = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": f"{SUMMARIZING_PROMPT}"},
                {"role": "user", "content": f"News: {parsed_content}"},
            ],
            response_model=schemas.News,
        )
        return summary
    except Exception as e:
        print(f"Error summarizing content: {str(e)}")
        return None

def store_summarized_news(db: Session, url: str, summary: schemas.News) -> int:
    """
    Stores the summarized news in the database and returns the id of the created article.
    """

    if summary is None:
        return None
    
    try:
        new_category = classify_category(summary)
        category = mapping_category_enum_to_string(new_category)
        new_article = models.New(
            url=url,
            title=summary.title,
            context=summary.context,
            facts=summary.facts,
            category=category,
            location=summary.location,
            published_date=summary.date,
            date_scraped=datetime.now()
        )
        db.add(new_article)
        db.commit()
        db.refresh(new_article)
    except Exception as e:
        print(f"Error storing summarized news: {str(e)}")
        return None
    print(f"Added {url} to database")
    return new_article.id


def get_new_with_url(url: str, db: Session = Depends(database.get_db)):
    return db.query(models.New).filter(models.New.url == url).first()

def get_new_with_id(news_id: int, db: Session = Depends(database.get_db)):
    return db.query(models.New).filter(models.New.id == news_id).first()

GET_KEYWORDS_PROMPT = "Considera la informazione che ti sarà data e trova 10 parole chiave più performanti " \
"per ottenere una massima indicizzazione sui motori di ricerca. " \
"Devi rispondere con una lista di parole chiave (che non sono necessariamente una sola parola)."

NEW_RESTRUCTURING_PROMPT = """
Sei un giornalista esperto di scuola e SEO. ALWAYS THE LENGTH OF THE PROPOSED CONTENT MUST BE 1600 WORDS. 
MUST BE 1600 WORDS. EVEN IF YOU NEED TO TALK ABOUT DETAILS AND THINGS THAT ARE NOT THAT RELEVANT, 
YOU SHOULD ALWAYS ARRIVE TO AT LEAST 1600 WORDS. 
Everything in your response should be in Italian. 

Scrivi una articolo di giornale con tono formale e stile giornalistico di 1600 parole diviso paragrafi e con indice in h3 dei paragrafi. 
Utilizza le parole chiave trovate inserendole nell'articolo per ottenere rispetta i seguenti criteri di qualità: 

Pertinenza: Il contenuto deve essere rilevante per la query di ricerca dell'utente
, ben strutturato con titoli, sottotitoli e paragrafi ordinati.

Utilizza le parole chiave principali in modo naturale e strategico. 

Accuratezza e affidabilità: Le informazioni devono essere corrette, aggiornate e basate su fonti autorevoli
, soprattutto se l'argomento rientra nelle categorie YMYL (salute, finanza, sicurezza, ecc.). 

Utilità: Il contenuto deve fornire un valore aggiunto, rispondere a domande reali e offrire soluzioni concrete. 

Evita informazioni generiche. 

Esperienza utente: L'articolo deve essere facile da leggere, con un tono chiaro e accessibile
, arricchito da suggerimenti visivi (es. punti elenco, titoli chiari) e strutturato per essere scorrevole anche da dispositivi mobili. 

Punteggio di Qualità (Google Ads): Il contenuto deve essere coerente con una possibile pagina di destinazione associata a un annuncio
, in modo da migliorare la qualità percepita e ottimizzare le performance pubblicitarie.

Ulteriori indicazioni: 
- Includi paragrafi chiari, titoli H2/H3, e una sintesi finale. 
- Usa un tono professionale ma accessibile. 
- Evita contenuti duplicati e offri una prospettiva originale. 
- Il testo deve essere pronto per la pubblicazione online. 

IL TITOLO DEVE ESSERE MODIFICATO. 

Non dimenticare di aggiungere formattazione testo (testo in grassetto, corsivo, titoli e sottotitoli in H1 e H3,  elenchi puntati ecc...). 

IMPORTANT NOTE: 
H2 Heading: Start a line with # (e.g., # Your Title)
H3 Heading: Start a line with ## (e.g., ## Your Subtitle)
H4 Heading: Start a line with ### (e.g., ### Your Minor Title)
Bold Text: Surround text with ** (e.g., **this is bold**)
Italic Text: Surround text with _ (e.g., _this is italic_)
Bulleted List: Start each line with - or *
Numbered List: Start each line with 1. , 2. , etc.
Paragraphs: Just type your text. Separate paragraphs with a blank line.
"""

def get_reconstructed_article_via_openai(news_item: models.New):
    if news_item is None:
        return None
    try:
        
        class SEOAnalysis(BaseModel):
            tags: List[str]
        keywords = client_openai.responses.parse(
            model='gpt-4.1',
            input=[
                {"role": "system", "content": f"{GET_KEYWORDS_PROMPT}"},
                {"role": "user", "content": f"This is the provided informations: Title: {news_item.title}, Facts: {news_item.facts}, Context: {news_item.context}, Category: {news_item.category}, Location: {news_item.location}, Published date: {news_item.published_date}"},
            ],
            text_format=SEOAnalysis,
            max_output_tokens=2000
        )

        tags = keywords.output[0].content[0].parsed.tags


        print(f"\n\n This is the provided informations: Title: {news_item.title}, Facts: {news_item.facts}, Context: {news_item.context}, Category: {news_item.category}, Location: {news_item.location}, Published date: {news_item.published_date}, parole chiave: {keywords}\n\n")
        article_response_openai = client_openai.responses.parse(
                        model='gpt-4.1',
                        input=[
                            {"role": "system", "content": f"{NEW_RESTRUCTURING_PROMPT}"},
                            {"role": "user", "content": f"This is the provided informations: Title: {news_item.title}, Facts: {news_item.facts}, Context: {news_item.context}, Category: {news_item.category}, Location: {news_item.location}, Published date: {news_item.published_date}, parole chiave (tags): {tags}"},
                        ],
                        text_format=schemas.NewsArticle,
                        max_output_tokens=8000
        )
        article_response = article_response_openai.output[0].content[0].parsed
        print(f"Article response: {article_response}")
        article_response.tags = tags

    except Exception as e:
        print(f"Error reconstructing article: {str(e)}")
        return None
    return article_response


# =============================================
# CLAUDE OPUS 4.6 - Ricostruzione articoli
# =============================================

STOP_WORDS_IT = {
    "di", "a", "da", "in", "con", "su", "per", "tra", "fra", "il", "lo", "la",
    "i", "gli", "le", "un", "uno", "una", "e", "o", "ma", "che", "non", "si",
    "del", "dello", "della", "dei", "degli", "delle", "al", "allo", "alla",
    "ai", "agli", "alle", "dal", "dallo", "dalla", "dai", "dagli", "dalle",
    "nel", "nello", "nella", "nei", "negli", "nelle", "sul", "sullo", "sulla",
    "sui", "sugli", "sulle", "come", "se", "anche", "piu", "sono", "stato",
    "essere", "ha", "hanno", "questo", "questa", "questi", "queste", "quello",
}


def find_related_articles(title: str, tags: List[str], category: str) -> List[dict]:
    """Trova i 3 articoli piu rilevanti dal database Supabase per interlinking."""
    try:
        supabase = get_supabase_client()
        response = supabase.table('articles').select(
            'id, title, slug, category_slug, tags'
        ).eq('isdraft', False).execute()

        if not response.data:
            print("No articles found in Supabase for interlinking")
            return []

        # Normalizza i tag dell'articolo nuovo
        new_tags_set = set(t.lower().strip() for t in tags if t)

        # Estrai parole significative dal titolo (no stop words)
        title_words = set(
            w.lower() for w in re.split(r'\W+', title)
            if len(w) > 2 and w.lower() not in STOP_WORDS_IT
        )

        scored_articles = []
        for article in response.data:
            # Parsa i tag dell'articolo esistente
            existing_tags_raw = article.get('tags', [])
            if isinstance(existing_tags_raw, str):
                try:
                    existing_tags_raw = json.loads(existing_tags_raw)
                except (json.JSONDecodeError, TypeError):
                    existing_tags_raw = []
            if not isinstance(existing_tags_raw, list):
                existing_tags_raw = []

            existing_tags_set = set(t.lower().strip() for t in existing_tags_raw if isinstance(t, str) and t)

            # Score: tag overlap (peso 0.6)
            tag_overlap = len(new_tags_set & existing_tags_set)
            max_tags = max(len(new_tags_set), 1)
            tag_score = (tag_overlap / max_tags) * 0.6

            # Score: stessa categoria (peso 0.25)
            article_category_slug = article.get('category_slug', '')
            category_slug_new = category.lower().replace(' ', '-') if category else ''
            category_score = 0.25 if article_category_slug == category_slug_new else 0

            # Score: keyword nel titolo (peso 0.15)
            existing_title = article.get('title', '')
            existing_title_words = set(
                w.lower() for w in re.split(r'\W+', existing_title)
                if len(w) > 2 and w.lower() not in STOP_WORDS_IT
            )
            title_overlap = len(title_words & existing_title_words)
            max_title_words = max(len(title_words), 1)
            title_score = (title_overlap / max_title_words) * 0.15

            total_score = tag_score + category_score + title_score

            if total_score > 0.1:
                scored_articles.append({
                    'title': article['title'],
                    'slug': article['slug'],
                    'category_slug': article['category_slug'],
                    'score': total_score
                })

        # Ordina per score decrescente, prendi i top 3
        scored_articles.sort(key=lambda x: x['score'], reverse=True)
        top_articles = scored_articles[:3]

        print(f"Found {len(top_articles)} related articles for interlinking:")
        for a in top_articles:
            print(f"  - {a['title']} (score: {a['score']:.3f}) -> /{a['category_slug']}/{a['slug']}")

        return top_articles

    except Exception as e:
        print(f"Error finding related articles: {str(e)}")
        return []


def get_reconstructed_article_via_claude(news_item: models.New) -> schemas.NewsArticle:
    """Ricostruisce un articolo usando Claude Opus 4.6 con interlinking."""
    if news_item is None:
        return None
    try:
        # Step A: Genera keyword SEO
        news_info = (
            f"Titolo: {news_item.title}\n"
            f"Fatti: {news_item.facts}\n"
            f"Contesto: {news_item.context}\n"
            f"Categoria: {news_item.category}\n"
            f"Luogo: {news_item.location}\n"
            f"Data pubblicazione: {news_item.published_date}"
        )

        keywords_response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1000,
            messages=[
                {
                    "role": "user",
                    "content": f"{CLAUDE_KEYWORDS_PROMPT}\n\nInformazioni:\n{news_info}"
                }
            ]
        )

        keywords_text = keywords_response.content[0].text.strip()
        # Estrai il JSON dalla risposta (gestisci eventuali blocchi markdown)
        if "```" in keywords_text:
            keywords_text = keywords_text.split("```")[1]
            if keywords_text.startswith("json"):
                keywords_text = keywords_text[4:]
            keywords_text = keywords_text.strip()

        keywords_data = json.loads(keywords_text)
        tags = keywords_data.get("tags", [])
        print(f"Claude keywords: {tags}")

        # Step B: Trova articoli correlati
        category_for_search = news_item.category or ""
        related_articles = find_related_articles(news_item.title, tags, category_for_search)

        # Formatta gli interlink per il prompt
        interlinks_text = ""
        if related_articles:
            interlinks_text = "\n\nArticoli correlati disponibili per interlinking (inseriscili naturalmente nel testo dove pertinente):\n"
            for i, article in enumerate(related_articles, 1):
                url = f"/{article['category_slug']}/{article['slug']}"
                interlinks_text += f"{i}. [{article['title']}]({url})\n"

        # Step C: Ricostruisci articolo
        user_content = (
            f"Informazioni sulla notizia:\n"
            f"Titolo: {news_item.title}\n"
            f"Fatti: {news_item.facts}\n"
            f"Contesto: {news_item.context}\n"
            f"Categoria: {news_item.category}\n"
            f"Luogo: {news_item.location}\n"
            f"Data pubblicazione: {news_item.published_date}\n"
            f"Parole chiave SEO: {tags}"
            f"{interlinks_text}"
        )

        article_response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8000,
            messages=[
                {
                    "role": "user",
                    "content": f"{CLAUDE_RESTRUCTURING_PROMPT}\n\n{user_content}"
                }
            ]
        )

        article_text = article_response.content[0].text.strip()
        # Estrai il JSON dalla risposta
        if "```" in article_text:
            article_text = article_text.split("```")[1]
            if article_text.startswith("json"):
                article_text = article_text[4:]
            article_text = article_text.strip()

        article_data = json.loads(article_text)

        result = schemas.NewsArticle(
            proposed_title=article_data.get("proposed_title", ""),
            proposed_subtitle=article_data.get("proposed_subtitle", ""),
            proposed_content=article_data.get("proposed_content", ""),
            tags=tags
        )
        print(f"Claude article reconstructed: {result.proposed_title}")
        return result

    except Exception as e:
        print(f"Error reconstructing article via Claude: {str(e)}")
        return None


class Summary(BaseModel):
    title: str
    summary: str

async def generate_summary(content: str) -> str:
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        summary_response = client.responses.parse(
        model='gpt-4.1-mini',
        input=[
        {"role": "system", "content": f"fai un sunto di 3 paragrafi di 200 parole ciascuno. 200 parole ciascuno EXACT EXACT EXACT and 3 paragraphs!!! IMPORTANT: DEVE ESSERE SEMPRE DI 600 PAROLE TOTALE, usare markdown quando necessario"},
        {"role": "user", "content": f"This is the provided informations: {content}"},
        ],
        text_format=Summary,
        max_output_tokens=4000
    )
        print(f"Summary: {summary_response.output[0].content[0].parsed.summary}")
        summary = summary_response.output[0].content[0].parsed.summary  
        title = summary_response.output[0].content[0].parsed.title
        return summary, title

    except Exception as e:
        print(f"Error generating summary: {str(e)}")
        return None

def update_news_item_with_reconstruction(news_item: models.New, article_response: schemas.NewsArticle, db: Session) -> None:

    if article_response is None:
        return None
    print(f"THIS IS THE ARTICLE I AM RECEIVEING: {article_response.proposed_title}\n{article_response.proposed_subtitle}\n{article_response.proposed_content}\n{article_response.tags}\n")
    news_item.proposed_title = article_response.proposed_title
    news_item.proposed_subtitle = article_response.proposed_subtitle
    news_item.proposed_response = article_response.proposed_content
    news_item.tags = article_response.tags
    db.commit()
    print(f"Updated news item with reconstruction: {news_item}")

def get_success_message(news_item: models.New):
    return f"""📰 Article Published!\n\n"
            f"Title: {news_item.proposed_title}\n"
            f"Subtitle: {news_item.proposed_subtitle}\n\n"
            f"Preview: {news_item.proposed_response}"""

def update_database(news_item: models.New, db: Session):
    news_item.is_published = True
    db.commit()
    db.refresh(news_item)
    
def get_published_and_recent_news(db: Session) -> List[models.New]:
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    published_news = db.query(models.New).filter(
        models.New.is_published == True,
        models.New.date_scraped >= today_start
    ).all()
    fifteen_minutes_ago = datetime.now() - timedelta(minutes=50)
    recent_news = db.query(models.New).filter(
        models.New.date_scraped >= fifteen_minutes_ago,
        models.New.is_published == False
    ).all()
    return published_news, recent_news
    
def get_comparison_text(published_news: List[models.New], recent_news: List[str]) -> str:

    if published_news is None or recent_news is None:
        return None
    
    published_data = [{"id": news.id, "title": news.title} for news in published_news]
    recent_data = [{"link": news} for news in recent_news]

    print(f"""
    Recent Unpublished News:
    {json.dumps(recent_data, indent=2)}
    """)
    return f"""
    Recent Unpublished News:
    {json.dumps(recent_data, indent=2)}
    """
import os


def get_unpublished_str(unpublished_events: List[schemas.Event]):
    if unpublished_events is None:
        return None
    unpublished_str = ""
    for event in unpublished_events:
        unpublished_str += f"Event: {event.event_name}\n"
        unpublished_str += f"Links: {', '.join(map(str, event.links))}\n"
        unpublished_str += "\n"
    print(f"Unpublished str: {unpublished_str}")
    return unpublished_str

def get_unpublished_events_via_openai(comparison_text: str):
    if comparison_text is None:
        return None
    try:
        all_events_in_recent_news = client.chat.completions.create(
            model=MODEL_BETTER,
            messages=[
                {"role": "system", "content": PROMPT_FOR_HAVING_ALL_THE_NEWS},
                {"role": "user", "content": comparison_text},
            ],
            response_model=schemas.EventList,
        )
        print(f"All events in recent news: {all_events_in_recent_news}")
        return all_events_in_recent_news
    except Exception as e:
        print(f"Error getting events in recent news via openai: {str(e)}")
        return None


def get_events_to_publish_via_openai(unpublished_events_str: str) -> schemas.EventList:
    if unpublished_events_str is None:
        return None
    try:
        events_to_publish = client.chat.completions.create(
            model=MODEL_BETTER,
            messages=[
            {"role": "system", "content": FINAL_SELECTION_PROMPT},
            {"role": "user", "content": unpublished_events_str},
        ],
            response_model=schemas.EventList,
        )
        print(f"THE AMOUNT OF EVENTS TO PUBLISH IS {len(events_to_publish.events)}")
    except Exception as e:
        print(f"Error getting events to publish via openai: {str(e)}")
        return None

    events_to_publish_message = (
            "📊 Rapporto Analisi Notizie\n\n"
            "🎯 Gruppi di Notizie Selezionate:\n"
        )
    for event in events_to_publish.events:
        events_to_publish_message += f"Event: {event.event_name}\n"
        events_to_publish_message += f"Links: {', '.join(map(str, event.links))}\n"
        events_to_publish_message += "\n"

    return events_to_publish

def send_telegram_notifications(messages: List[str]):
    try:
        for message in messages:
            requests.post("http://localhost:8001/send", params={"message": message})
    except Exception as e:
        print(f"Failed to send Telegram notification: {str(e)}")



@app.get("/api/news")
async def get_news(db: Session = Depends(get_db)):
    try:
        # Fetch news from the database
        db_news = db.query(models.New).all()
        
        # Convert the database objects to dictionaries
        news_list = []
        for news in db_news:
            try:
                news_dict = {
                    "title": news.title,
                    "url": news.url,
                    "text": news.text,
                    "facts": news.facts,
                    "context": news.context,
                    "category": news.category,
                    "location": news.location,
                    "published_date": str(news.published_date),
                    "language": news.language,
                    "proposed_response": news.proposed_response,
                    "proposed_title": news.proposed_title,
                    "proposed_subtitle": news.proposed_subtitle,
                    "id": news.id,
                    "category_rating": news.category_rating,
                    "editorial_rating": news.editorial_rating,
                    "importance_rating": news.importance_rating,
                    "proposed_title_rating": news.proposed_title_rating,
                    "proposed_subtitle_rating": news.proposed_subtitle_rating,
                    "proposed_content_rating": news.proposed_content_rating,
                    "proposed_text_review": news.proposed_text_review,
                }
                news_list.append(news_dict)
            except Exception as e:
                print(f"Error processing news item: {str(e)}")
                continue
        
        return news_list
    except Exception as e:
        print(f"Error fetching news: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/api/news/recent")
async def get_recent_news(db: Session = Depends(get_db)):
    try:
        fifteen_minutes_ago = datetime.now() - timedelta(minutes=55)
        recent_news = db.query(models.New).filter(
            models.New.date_scraped >= fifteen_minutes_ago
        ).all()
        
        return {
            "count": len(recent_news),
            "news_ids": [news.id for news in recent_news]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/news/published/today")
async def get_today_published_news(db: Session = Depends(get_db)):
    try:
        # Get today's date at midnight (start of the day)
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Query published news from today
        published_news = db.query(models.New).filter(
            models.New.is_published == True,
            models.New.date_scraped >= today_start
        ).all()
        
        return {
            "count": len(published_news),
            "news_ids": [news.id for news in published_news]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/reconstruct_article")
async def reconstruct_article(db: Session = Depends(get_db)):
    final_results = []

    with open('to_scrape.json', 'r') as f:
        to_scrape = json.load(f)

    for url, status in to_scrape.items():
        if status == "summarized":
            try:
                news_item = get_new_with_url(url, db)

                #print(f"News item: \n\n{news_item.title}\n{news_item.facts}\n{news_item.context}\n{news_item.category}\n{news_item.location}\n{news_item.published_date}\n\n")

                if news_item:
                    article_response = client.chat.completions.create(
                        model=MODEL_BETTER,
                        messages=[
                            {"role": "system", "content": f"{RECONSTRUCTING_PROMPT}"},
                            {"role": "user", "content": f"This is the provided informations: Title: {news_item.title}, Facts: {news_item.facts}, Context: {news_item.context}, Category: {news_item.category}, Location: {news_item.location}, Published date: {news_item.published_date}"},
                        ],
                        response_model=schemas.NewsArticle,
                    )
                    #print(f"Article response: {article_response}\n\n")
                    
                    print(f"This is the provided informations: Title: {news_item.title}, Facts: {news_item.facts}, Context: {news_item.context}, Category: {news_item.category}, Location: {news_item.location}, Published date: {news_item.published_date}")
                    # Update the database with the reconstructed article
                    news_item.proposed_title = article_response.proposed_title
                    news_item.proposed_response = article_response.proposed_content
                    news_item.proposed_subtitle = article_response.proposed_subtitle
                    db.commit()
                    #print(f"Updated database entry for {url}")

                    final_results.append(article_response)

                    to_scrape[url] = "reconstructed"
            except Exception as e:
                print(f"Error processing {url}: {str(e)}")
                continue

    with open('to_scrape.json', 'w') as f:
        json.dump(to_scrape, f, indent=2)
    
    return final_results

@app.get("/api/news/{news_id}")
async def get_single_news(news_id: int, db: Session = Depends(get_db)):
    try:
        news = db.query(models.New).filter(models.New.id == news_id).first()
        if news is None:
            raise HTTPException(status_code=404, detail="News not found")
        return {
            "title": news.title,
            "url": news.url,
            # ... other fields ...
        }
    except Exception as e:
        print(f"Error fetching single news item: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.post("/api/context/finetuning/generate")
async def generate_finetuning(news: schemas.FinetuneContext):
    response = []
    print(f"News: {len(news.news)}\n\n")
    for new in news.news:
        summary = client.chat.completions.create(
                        model=MODEL,
                        messages=[
                            {"role": "system", "content": "Read user's new's article and extract the news item. The news item should be in the form of a JSON object with the following structure: title, context, facts. ITS VERY IMPORTANT THAT YOU SHOULD MODIFY THE TITLE, MAKE IT A LITTLE BIT DIFFERENT. You should do this in order so another one with NO more info about the matter makes a new article. Check the language. The facts should be concrete and specific to the news item. Facts need to be short, with the less amount of well-done phrases and more like \"Someone did this\", \"Response was this\". Everything in your response should be in Italian."},
                            {"role": "user", "content": f"News: {new}"}
                        ],
                        response_model=schemas.News,
                    )
        print(f"Summary title: {summary.title}\n\n Summary context: {summary.context}\n\n Summary facts: {summary.facts}\n\n")
        response.append({"title": summary.title, "context": summary.context, "facts": summary.facts})
    
    return {"response": response}

@app.post("/api/news/edit")
async def edit_news(body: schemas.Edit_new, db: Session = Depends(get_db)):
    # Fetch the news item from the database
    print(f"body = {body.id}")
    print(f"new_text = {body.new_text}")
    print(f"text = {body.edit_text}")
    news_item = db.query(models.New).filter(models.New.id == body.id).first()
    if not news_item:
        raise HTTPException(status_code=404, detail="News item not found")

    # Prepare the context for the AI
    if body.new_text:
        context = f"Context = {body.new_text}"
    else:
        context = f"""
        Title: {news_item.title}
        Context: {news_item.context}
        Facts: {', '.join(news_item.facts)}
        Category: {news_item.category}
        Location: {news_item.location}
        Published Date: {news_item.published_date}
        """
    # Make the API call to OpenAI
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": f"You are an AI assistant helping to edit a news article. Here's the original article user want to edit:\n\n{context}"},
            {"role": "user", "content": f"Please incorporate this edit into the article: {body.edit_text}"}
        ],
        response_model=schemas.NewsArticle
    )

    print(f"Response = {str(response)}")
    return {"Response": response}

@app.put("/api/news/{news_id}/update")
async def update_news(news_id: int, updated_news: schemas.NewsArticle, db: Session = Depends(get_db)):
    news_item = db.query(models.New).filter(models.New.id == news_id).first()
    if not news_item:
        raise HTTPException(status_code=404, detail="News item not found")

    news_item.proposed_title = updated_news.proposed_title
    news_item.proposed_subtitle = updated_news.proposed_subtitle
    news_item.proposed_response = updated_news.proposed_content

    db.commit()
    db.refresh(news_item)

    return {
        "id": news_item.id,
        "title": news_item.title,
        "proposed_title": news_item.proposed_title,
        "proposed_subtitle": news_item.proposed_subtitle,
        "proposed_response": news_item.proposed_response,
    }

@app.post("/api/news/rate")
async def rate_news(rating: schemas.NewsRating, db: Session = Depends(get_db)):
    print(f"Received rating: {rating}")
    news_item = db.query(models.New).filter(models.New.id == rating.id).first()
    if not news_item:
        print(f"News item with id {rating.id} not found")
        raise HTTPException(status_code=404, detail="News item not found")

    news_item.category_rating = rating.category_rating
    news_item.editorial_rating = rating.editorial_rating
    news_item.importance_rating = rating.importance_rating


    try:
        db.commit()
        db.refresh(news_item)
        print(f"Updated ratings for news item {rating.id}: {news_item.category_rating}, {news_item.editorial_rating}, {news_item.importance_rating}")
        
        # Update JSON file with ratings
        update_ratings_json(news_item.id, {
            "category_rating": news_item.category_rating,
            "editorial_rating": news_item.editorial_rating,
            "importance_rating": news_item.importance_rating
        })
    except Exception as e:
        print(f"Error updating ratings: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update ratings")

    return {
        "id": news_item.id,
        "category_rating": news_item.category_rating,
        "editorial_rating": news_item.editorial_rating,
        "importance_rating": news_item.importance_rating,
    }

@app.post("/api/news/rate-proposed")
async def rate_proposed_content(rating: schemas.ProposedContentRating, db: Session = Depends(get_db)):
    print(f"Rating = {rating.content_rating}, {rating.subtitle_rating}")
    news_item = db.query(models.New).filter(models.New.id == rating.id).first()
    if not news_item:
        raise HTTPException(status_code=404, detail="News item not found")

    news_item.proposed_title_rating = rating.title_rating
    news_item.proposed_subtitle_rating = rating.subtitle_rating
    news_item.proposed_content_rating = rating.content_rating

    try:
        db.commit()
        db.refresh(news_item)
        
        # Update JSON file with proposed content ratings
        update_ratings_json(news_item.id, {
            "rate-proposed": {
                "title_rating": news_item.proposed_title_rating,
                "subtitle_rating": news_item.proposed_subtitle_rating,
                "content_rating": news_item.proposed_content_rating
            }
        })
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update proposed content ratings")

    return {
        "id": news_item.id,
        "proposed_title_rating": news_item.proposed_title_rating,
        "proposed_subtitle_rating": news_item.proposed_subtitle_rating,
        "proposed_content_rating": news_item.proposed_content_rating,
        "proposed_text_review": news_item.proposed_text_review,
    }


@app.post("/api/wordpress/test")
async def test_wordpress_post():

    """Test endpoint to verify WordPress connection by creating a draft post"""
    
    # Test content
    test_title = "Test Post - Please Ignore"
    test_content = """
    <h2>This is a test subtitle</h2>
    <p>This is a test post to verify the WordPress API connection.</p>
    <p>If you see this post in your WordPress dashboard, the connection is working!</p>
    <p>Generated at: {}</p>
    """.format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    post_data = {
        "title": "xab51",
        "content": test_content,
        "status": "draft",
        "date": datetime.now().isoformat(),
        "categories": [25],
        "meta": {
            "_yoast_wpseo_focuskw": "Title test",
            "td_post_theme_settings": {
                "td_subtitle": "pippo plutto e paperino 2040"
            }
        }
    }

    try:
        # Make request to WordPress API
        response = requests.post(
            WORDPRESS_API_URL,
            json=post_data,
            auth=HTTPBasicAuth(WORDPRESS_USERNAME, WORDPRESS_APP_PASSWORD)
        )

        if response.status_code == 201:
            post_data = response.json()
            return {
                "success": True,
                "message": "Test post created successfully",
                "post_id": post_data.get('id'),
                "post_link": post_data.get('link')
            }
        else:
            print(f"ENV VARIABLES: url: {WORDPRESS_API_URL}, username: {WORDPRESS_USERNAME}, password: {WORDPRESS_APP_PASSWORD}")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to create test post. WordPress response: {response.text}"
            )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error testing WordPress connection: {str(e)}"
        )


@app.get("/api/wordpress/post/{post_id}")
async def get_wordpress_post(post_id: int):
    """Retrieve information about a specific WordPress post"""
    try:
        # Construct the URL with the post ID
        post_url = f"{WORDPRESS_API_URL}/{post_id}?context=edit"

        # Make request to WordPress API
        response = requests.get(
            post_url,
            auth=HTTPBasicAuth(WORDPRESS_USERNAME, WORDPRESS_APP_PASSWORD)
        )

        if response.status_code == 200:
            post_data = response.json()
            return {
                "success": True,
                "post_data": {
                    "id": post_data.get('id'),
                    "title": post_data.get('title', {}).get('rendered'),
                    "content": post_data.get('content', {}).get('rendered'),
                    "status": post_data.get('status'),
                    "date": post_data.get('date'),
                    "modified": post_data.get('modified'),
                    "link": post_data.get('link'),
                    "meta": post_data.get('meta'),
                }
            }
        else:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to retrieve post. WordPress response: {response.text}"
            )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving WordPress post: {str(e)}"
        )
    
    
    
class WordPressCategory(Enum):
    AMBIENTE = "Environmental news and issues"
    ATTUALITA = "Current affairs and news"
    CATANZARO = "News from Catanzaro region" 
    COSENZA = "News from Cosenza region"
    CRONACA = "Crime and general news"
    NDRANGHETA = "News about Ndrangheta"
    CROTONE = "News from Crotone region"
    CUCINA = "Food and cooking"
    CULTURA_SPETTACOLO = "Culture and entertainment"
    EVENTI = "Events and happenings"
    MUSICA = "Music news and reviews"
    ECONOMIA_LAVORO = "Economy and employment"
    EDITORIALI = "Editorial pieces"
    FEATURED = "Featured stories"
    GIUSTIZIA = "Justice and legal news"
    IL_COMMENTO = "Commentary and opinion"
    IL_FATTO_TV = "From the TV channel Il Fatto"
    ISRAELE_HAMAS = "Israel-Hamas conflict news"
    ISTRUZIONE = "Education news"
    LE_INCHIESTE = "Investigative reports"
    MONDO = "World news"
    POLITICA = "Political news"
    REGGIO_CALABRIA = "News from Reggio Calabria"
    SALUTE = "Health news"
    SANITA = "Healthcare system news"
    SANREMO = "Sanremo festival news"
    SATIRA = "Satire and humor"
    SOCIETA = "Society and social issues"
    SPORT = "Sports news"
    TECNOLOGIA = "Technology news"
    TRADIZIONI = "Traditions and customs"
    TURISMO = "Tourism news"
    UCRAINA_RUSSIA = "Ukraine-Russia conflict news"
    UNCATEGORIZED = "Uncategorized content"
    VIAGGI = "Travel news"
    VIBO_VALENTIA = "News from Vibo Valentia"
    VIDEO = "Video content"


mapping_category = {
    WordPressCategory.AMBIENTE: 5,
    WordPressCategory.ATTUALITA: 4,
    WordPressCategory.CATANZARO: 24,
    WordPressCategory.COSENZA: 25,
    WordPressCategory.CRONACA: 15,
    WordPressCategory.NDRANGHETA: 19,
    WordPressCategory.CROTONE: 26,
    WordPressCategory.CUCINA: 191,
    WordPressCategory.CULTURA_SPETTACOLO: 10,
    WordPressCategory.EVENTI: 3,
    WordPressCategory.MUSICA: 6,
    WordPressCategory.ECONOMIA_LAVORO: 11,
    WordPressCategory.EDITORIALI: 12,
    WordPressCategory.FEATURED: 2,
    WordPressCategory.GIUSTIZIA: 32,
    WordPressCategory.IL_COMMENTO: 737,
    WordPressCategory.IL_FATTO_TV: 4383,
    WordPressCategory.ISRAELE_HAMAS: 17,
    WordPressCategory.ISTRUZIONE: 3542,
    WordPressCategory.LE_INCHIESTE: 342,
    WordPressCategory.MONDO: 14,
    WordPressCategory.POLITICA: 7,
    WordPressCategory.REGGIO_CALABRIA: 27,
    WordPressCategory.SALUTE: 3541,
    WordPressCategory.SANITA: 29,
    WordPressCategory.SANREMO: 18,
    WordPressCategory.SATIRA: 1460,
    WordPressCategory.SOCIETA: 33,
    WordPressCategory.SPORT: 13,
    WordPressCategory.TECNOLOGIA: 8,
    WordPressCategory.TRADIZIONI: 190,
    WordPressCategory.TURISMO: 3546,
    WordPressCategory.UCRAINA_RUSSIA: 16,
    WordPressCategory.UNCATEGORIZED: 1,
    WordPressCategory.VIAGGI: 192,
    WordPressCategory.VIBO_VALENTIA: 28,
    WordPressCategory.VIDEO: 21
}

# Define Italy timezone
ITALY_TZ = pytz.timezone('Europe/Rome')

def classify_category(new: schemas.News):

    classification_text = f"""
    Title: {new.title}
    Facts: {', '.join(new.facts)}
    Context: {new.context}
    """
    print(f"Classification text: {classification_text}\n\n")

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": f"{CLASSIFICATION_PROMPT}"
            },
            {"role": "user", "content": classification_text},
        ],
        response_model=CategoryEnum,
    )

    print(f"Response: {response}\n\n")

    return response


def update_ratings_json(news_id, ratings):
    json_file_path = 'news_ratings.json'
    
    # Read existing data
    if os.path.exists(json_file_path):
        with open(json_file_path, 'r') as f:
            data = json.load(f)
    else:
        data = {}
    
    # Update data
    if str(news_id) not in data:
        data[str(news_id)] = {}
    
    # Update ratings as a dictionary
    data[str(news_id)].update(ratings)
    
    # Write updated data back to file
    with open(json_file_path, 'w') as f:
        json.dump(data, f, indent=2)

@app.post("/dismiss_failed_links")
async def dismiss_failed_links():
    try:
        with open('to_scrape.json', 'r') as f:
            to_scrape = json.load(f)
        
        # Count how many links were marked as failed
        failed_count = 0
        
        # Update empty status to "failed"
        for url, status in to_scrape.items():
            if status == "":
                to_scrape[url] = "failed"
                failed_count += 1
        
        # Save the updated json
        with open('to_scrape.json', 'w') as f:
            json.dump(to_scrape, f, indent=2)
            
        return {
            "status": "success",
            "failed_links_count": failed_count,
            "message": f"Successfully marked {failed_count} links as failed"
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error dismissing failed links: {str(e)}"
        )
@app.post("/put_links_in_summarized")
async def put_links_in_summarized():
    try:
        with open('to_scrape.json', 'r') as f:
            to_scrape = json.load(f)
        
        
        
        # Update empty status to "failed"
        for url, status in to_scrape.items():
            if status == "":
                to_scrape[url] = "summarized"
        
        # Save the updated json
        with open('to_scrape.json', 'w') as f:
            json.dump(to_scrape, f, indent=2)
            
        return {
            "status": "success",
            "message": f"Successfully"
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error putting links in summarized: {str(e)}"
        )

@app.get("/reconstruct_first_article", response_model=schemas.NewsArticle)
async def reconstruct_first_article(db: Session = Depends(get_db)):
    """
    Fetches the first news item from the database and reconstructs its article content.
    """
    # 1. Fetch the first news item
    news_item: models.New = db.query(models.New).first()

    if not news_item:
        raise HTTPException(status_code=404, detail="No news items found in the database")

    # 2. Call the reconstruction function
    try:
        reconstructed_article: schemas.NewsArticle = get_reconstructed_article_via_openai(news_item)

        if not reconstructed_article:
            raise HTTPException(status_code=500, detail="Failed to reconstruct article (OpenAI call might have failed)")

        # Optionally: Update the database with the reconstruction (if needed by default)
        # update_news_item_with_reconstruction(news_item, reconstructed_article, db)

        return reconstructed_article

    except Exception as e:
        # Handle potential exceptions during reconstruction
        print(f"Error reconstructing first article (ID: {news_item.id}): {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error during reconstruction: {str(e)}")

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

