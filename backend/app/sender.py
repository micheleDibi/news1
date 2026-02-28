import requests
import json
import time
from datetime import datetime, timezone
import schedule
from typing import List, Dict, Any, Tuple, Optional
from . import schemas
import pytz
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()
from supabase import create_client, Client
from firecrawl import AsyncFirecrawlApp
from pydantic import BaseModel, Field
from .variables_edunews import (
    hour_to_iniziate,
    hour_to_end,
    query_generator
)

# API configuration
BASE_URL = "http://localhost:8000"
TELEGRAM_URL = "http://localhost:8004"
PUBLIC_SUPABASE_URL = os.getenv("PUBLIC_SUPABASE_URL")
PUBLIC_SUPABASE_ANON_KEY = os.getenv("PUBLIC_SUPABASE_ANON_KEY")
# Supabase configuration
SUPABASE_URL = PUBLIC_SUPABASE_URL
SUPABASE_KEY = PUBLIC_SUPABASE_ANON_KEY

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:4321")
REFRESH_ENDPOINT = f"{FRONTEND_URL}/api/bandi/refresh"
SCHEDULE_MINUTES = 60 # Run every hour

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
    """First process: Extract elenco interpelli and check for new ones"""
    try:
        print(f"[{datetime.now()}] Starting elencos extraction...")
        
        app = AsyncFirecrawlApp(api_key=os.getenv("FIRECRAWL_API_KEY"))
        response = await app.extract(
            urls=[
                "https://scuolainterpelli.it/interpelli-scuola-aggiornati/?doing_wp_cron=1749044753.9211940765380859375000"
            ],
            prompt='Put a list of all the elenco interpelli with all the necessary data on the schema. Only the last 20 items, the ones which are more near to the today\'s date',
            schema=ExtractSchema.model_json_schema()
        )

        print(f"\n\n\nresponse: {response}")
        
        if not response or not response.data:
            print("No elencos data received from firecrawl")
            return []
        
        # Get existing elencos from Supabase
        supabase = get_supabase_client()
        existing_response = supabase.table('elenchi').select('elenco_link').execute()
        existing_links = [item['elenco_link'] for item in existing_response.data] if existing_response.data else []
        
        # Find new elencos
        new_elencos = []
        extracted_data = response.data
        
        # The data structure is directly the elenco_list
        if isinstance(extracted_data, dict) and 'elenco_list' in extracted_data:
            for elenco in extracted_data['elenco_list']:
                if elenco.get('elenco_link') and elenco['elenco_link'] not in existing_links:
                    new_elencos.append(elenco)
                    # Insert new elenco into Supabase
                    supabase.table('elenchi').insert(elenco).execute()
                    print(f"Added new elenco: {elenco.get('elenco_name', 'Unknown')}")
        
        print(f"Found {len(new_elencos)} new elencos")
        return new_elencos
        
    except Exception as e:
        print(f"Error in extract_elencos: {str(e)}")
        return []

async def extract_interpelli_for_elenco(elenco_url: str):
    """Second process: Extract interpelli for a specific elenco URL"""
    try:
        print(f"[{datetime.now()}] Extracting interpelli for: {elenco_url}")
        
        app = AsyncFirecrawlApp(api_key=os.getenv("FIRECRAWL_API_KEY"))
        response = await app.extract(
            urls=[elenco_url],
            prompt='I need to put into a json every interpello for every region, put description, date, link and city name for every interpello.',
            schema=ExtractSchemaInterpelli.model_json_schema()
        )
        
        print(f"DEBUG - Raw response for {elenco_url}: {response}")
        
        if not response or not response.data:
            print(f"No interpelli data received for {elenco_url}")
            return
        
        print(f"DEBUG - Extracted data: {response.data}")
        
        supabase = get_supabase_client()
        extracted_data = response.data
        
        if isinstance(extracted_data, dict) and 'regions_interpelli' in extracted_data:
            for region in extracted_data['regions_interpelli']:
                print(f"DEBUG - Processing region: {region}")
                region_name = region.get('region_name', 'Unknown')
                interpelli = region.get('interpelli', [])
                
                for interpello in interpelli:
                    print(f"DEBUG - Processing interpello: {interpello}")
                    # Add region name to the interpello data
                    interpello_data = {
                        **interpello,
                        'region_name': region_name
                    }
                    
                    print(f"DEBUG - Final interpello_data to insert: {interpello_data}")
                    
                    # Insert interpello into Supabase
                    supabase.table('interpelli').insert(interpello_data).execute()
                    print(f"Added interpello: {interpello.get('interpello_name', 'Unknown')} for region {region_name}")
        else:
            print(f"DEBUG - Data structure doesn't match expected format. Got: {extracted_data}")
        
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

def run_news_pipeline(source_list: List[Dict[str, str]] = None):
    """Execute the complete news pipeline"""

    trigger_bandi_refresh()

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
    # Schedule interpelli processing once daily at 2:00
    schedule.every().day.at("02:00").do(run_interpelli_pipeline)
    
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
