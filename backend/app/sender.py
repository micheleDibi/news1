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
from .logger import logger

# API configuration
BASE_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
TELEGRAM_URL = os.getenv("TELEGRAM_URL", "http://localhost:8004")
PUBLIC_SUPABASE_URL = os.getenv("PUBLIC_SUPABASE_URL")
PUBLIC_SUPABASE_ANON_KEY = os.getenv("PUBLIC_SUPABASE_ANON_KEY")
# Supabase configuration
SUPABASE_URL = PUBLIC_SUPABASE_URL
SUPABASE_KEY = PUBLIC_SUPABASE_ANON_KEY

SCHEDULE_MINUTES = 60 # Run every hour

def get_supabase_client() -> Client:
    """Initialize and return a Supabase client"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise Exception("Supabase credentials not found. Please set SUPABASE_URL and SUPABASE_KEY environment variables.")
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_sources_from_supabase() -> List[Dict[str, str]]:
    """Fetch sources with their valid prefixes from Supabase"""
    try:
        supabase = get_supabase_client()
        logger.debug("supabase: {}, credentials: {}, {}", supabase, SUPABASE_URL, SUPABASE_KEY)
        response = supabase.table('sources').select('*').execute()
        if not response.data:
            logger.info("No sources found in Supabase")
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
        logger.debug("sources: {}", sources)
        logger.info("Fetched {} sources from Supabase", len(sources))
        return sources
    except Exception as e:
        logger.error("Error fetching sources from Supabase: {}", e)
        return []

def send_telegram_notification(message: str) -> bool:
    """Send a notification via Telegram server"""
    try:
        # response = requests.post(f"{TELEGRAM_URL}/send", params={"message": message})
        # return response.status_code == 200
        return True
    except Exception as e:
        logger.error("Failed to send Telegram notification: {}", e)
        return False

def scrape_news(source_list: List[Dict[str, str]] = None, pipeline_state: Dict[str, Any] = None) -> List[str]:
    """Scrape news from specified sources"""
    if source_list is None:
        logger.info("No source list provided")
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
    logger.info("Starting scraping process...")
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
                logger.info("Successfully scraped {}", source['link'])
                scraped_links = response.json()["news_links"]
                news_list.extend(scraped_links)
                
                # Update pipeline state
                if pipeline_state is not None:
                    pipeline_state["scraping"]["scraped_links"].extend(scraped_links)
                
                success_count += 1
            else:
                logger.error("Failed to scrape {}: {}", source['link'], response.status_code)
                # Add failure to pipeline state
                if pipeline_state is not None:
                    pipeline_state["scraping"].setdefault("failures", []).append({
                        "source": source['link'],
                        "status_code": response.status_code
                    })
        except Exception as e:
            logger.error("Error scraping {}: {}", source['link'], e)
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
    
    logger.debug("News list: {} INSIDE SENDER", news_list)
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
    logger.info("Checking for duplicates...")
    logger.debug("News list: {}", news_list)
    link_list = schemas.LinkList(links=news_list)
    try:
        response = requests.post(f"{BASE_URL}/api/news/analyze", json=link_list.model_dump())
        if response.status_code == 200:
            unique_ids = response.json().get("unique_news_ids", [])
            logger.info("Found {} unique news items", len(unique_ids))
            
            # Update pipeline state
            if pipeline_state is not None:
                pipeline_state["selected_links"]["status"] = "completed"
                pipeline_state["selected_links"]["unique_news_ids"] = unique_ids
                pipeline_state["selected_links"]["unique_count"] = len(unique_ids)
            
            return unique_ids
        
        logger.error("Failed to check duplicates: {}", response.status_code)
        # Add failure to pipeline state
        if pipeline_state is not None:
            pipeline_state["selected_links"]["status"] = "failed"
            pipeline_state["selected_links"]["error"] = f"Status code: {response.status_code}"
        
        return []
    except Exception as e:
        logger.error("Error checking duplicates: {}", e)
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
    logger.info("Starting summarization process...")
    try:
        response = requests.get(f"{BASE_URL}/summarize_news")
        if response.status_code == 200:
            logger.info("Successfully summarized news")
            summarized_ids = response.json().get("summarized_news_IDs", [])
            summarized_news = response.json().get("summarized_news", [])
            summarized_urls = response.json().get("summarized_urls", [])
            
            # Create URL to ID mapping
            url_to_id_map = {}
            
            # Map URLs to IDs if both arrays exist and have the same length
            if summarized_urls and len(summarized_urls) == len(summarized_ids):
                for i, url in enumerate(summarized_urls):
                    url_to_id_map[url] = summarized_ids[i]
                    logger.debug("Mapped URL {} to ID {}", url, summarized_ids[i])
            
            # Update pipeline state
            if pipeline_state is not None:
                pipeline_state["summarization"]["status"] = "completed"
                pipeline_state["summarization"]["summarized_news_ids"] = summarized_ids
                pipeline_state["summarization"]["summarized_news"] = summarized_news
                pipeline_state["summarization"]["summarized_urls"] = summarized_urls
                pipeline_state["summarization"]["url_to_id_map"] = url_to_id_map
            
            return summarized_ids
        
        logger.error("Failed to summarize news: {}", response.status_code)
        # Add failure to pipeline state
        if pipeline_state is not None:
            pipeline_state["summarization"]["status"] = "failed"
            pipeline_state["summarization"]["error"] = f"Status code: {response.status_code}"
        
        return []
    except Exception as e:
        logger.error("Error summarizing news: {}", e)
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
    logger.info("Reconstructing articles...")
    success_count = 0
    
    for news_id in news_ids:
        try:
            response = requests.post(f"{BASE_URL}/api/news/reconstruct/{news_id}")
            if response.status_code == 200:
                success_count += 1
                logger.info("Successfully reconstructed article ID: {}", news_id)
                
                # Update pipeline state
                if pipeline_state is not None:
                    pipeline_state["reconstruction"]["reconstructed_articles"].append({
                        "news_id": news_id,
                        "status": "success",
                        "article": response.json()
                    })
            else:
                logger.error("Failed to reconstruct article ID {}: {}", news_id, response.status_code)
                
                # Add failure to pipeline state
                if pipeline_state is not None:
                    pipeline_state["reconstruction"]["reconstructed_articles"].append({
                        "news_id": news_id,
                        "status": "failed",
                        "error": f"Status code: {response.status_code}"
                    })
        except Exception as e:
            logger.error("Error reconstructing article ID {}: {}", news_id, e)
            
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
    logger.info("Publishing news...")
    published_count = 0
    
    for news_id in news_ids:
        try:
            response = requests.post(f"{BASE_URL}/api/news/publish/{news_id}")
            if response.status_code == 200:
                published_count += 1
                logger.info("Successfully published news ID: {}", news_id)
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
                logger.error("Failed to publish news ID {}: {}", news_id, response.status_code)
                
                # Add failure to pipeline state
                if pipeline_state is not None:
                    pipeline_state["publishing"]["published_articles"].append({
                        "news_id": news_id,
                        "status": "failed",
                        "error": f"Status code: {response.status_code}"
                    })
        except Exception as e:
            logger.error("Error publishing news ID {}: {}", news_id, e)
            
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

def run_news_pipeline(source_list: List[Dict[str, str]] = None):
    """Execute the complete news pipeline"""

    source_list = fetch_sources_from_supabase()
    if not source_list:
        logger.info("No sources available")
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
    
    send_telegram_notification("🔄 Avvio pipeline delle notizie...")

    logger.info("=" * 50)
    logger.info("=" * 50)
    
    try:
        # Step 1: Scrape
        news_list = scrape_news(source_list, pipeline_state)
        if not news_list:
            logger.info("No news found, stopping pipeline")
            pipeline_state["status"] = "no-news"
            pipeline_state["message"] = "No news found"
            return
        
        logger.debug("News list: {}, type of news_list: {}", news_list, type(news_list))
        
        # Step 2: Check duplicates
        unique_ids = check_duplicates(news_list, pipeline_state)
        pipeline_state["unique_ids"] = unique_ids
        
        if not unique_ids:
            logger.info("No unique articles found, stopping pipeline")
            pipeline_state["status"] = "no-news"
            pipeline_state["message"] = "No unique articles found"
            return
        
        # Step 3: Summarize
        summarized_ids = summarize_news(pipeline_state)
        if not summarized_ids:
            logger.info("No articles to summarize, stopping pipeline")
            pipeline_state["status"] = "no-news"
            pipeline_state["message"] = "No articles to summarize"
            return
        
        pipeline_state["summarized_ids"] = summarized_ids
        
        # Step 4: Reconstruct articles
        if not reconstruct_articles(summarized_ids, pipeline_state):
            logger.info("No articles reconstructed, stopping pipeline")
            pipeline_state["status"] = "no-news"
            pipeline_state["message"] = "No articles reconstructed"
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
        
        logger.info("=" * 50)
        logger.info("=" * 50)
    
    except Exception as e:
        logger.error("Error in pipeline: {}", e)
        pipeline_state["status"] = "error"
        pipeline_state["error"] = str(e)

def schedule_pipeline():
    """Schedule the pipeline to run at different times"""

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
    except KeyboardInterrupt:
        logger.info("Shutting down news pipeline scheduler...")
    except Exception as e:
        logger.error("Error in main execution: {}", e)
