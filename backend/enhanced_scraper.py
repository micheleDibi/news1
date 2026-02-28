"""
Enhanced web scraper with better error handling and Cloudflare bypass strategies
"""

import requests
import time
import random
import ssl
import urllib3
from typing import List, Dict, Any, Optional, Tuple
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib3.exceptions import InsecureRequestWarning
import json
import logging
from datetime import datetime, timedelta
import cloudscraper

# Disable SSL warnings for debugging
urllib3.disable_warnings(InsecureRequestWarning)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EnhancedScraper:
    def __init__(self):
        self.session = None
        self.cloudscraper_session = None
        self.setup_sessions()
        
    def setup_sessions(self):
        """Setup multiple session types for different scenarios"""
        
        # Standard session with enhanced configuration
        self.session = requests.Session()
        
        # Enhanced retry strategy
        retry_strategy = Retry(
            total=5,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504, 525, 526, 527, 528],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        
        # Custom SSL adapter
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=20
        )
        
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Enhanced headers that mimic real browsers
        self.session.headers.update({
            'User-Agent': self._get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0',
        })
        
        # CloudScraper session for Cloudflare-protected sites
        self.cloudscraper_session = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'mobile': False
            }
        )
    
    def _get_random_user_agent(self) -> str:
        """Get a random user agent to avoid detection"""
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/121.0',
        ]
        return random.choice(user_agents)
    
    def _adaptive_delay(self, attempt: int = 1) -> None:
        """Implement adaptive delays based on attempt number"""
        base_delay = 1
        max_delay = 30
        delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
        logger.info(f"Waiting {delay:.2f} seconds before next attempt...")
        time.sleep(delay)
    
    def scrape_url(self, url: str, max_retries: int = 3) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        Enhanced URL scraping with multiple fallback strategies
        Returns (content, metadata)
        """
        metadata = {
            'url': url,
            'timestamp': datetime.now().isoformat(),
            'attempts': 0,
            'final_status': None,
            'error_type': None,
            'method_used': None
        }
        
        # Strategy 1: Standard requests
        content, success = self._try_standard_request(url, metadata, max_retries)
        if success:
            return content, metadata
            
        # Strategy 2: CloudScraper for Cloudflare-protected sites
        content, success = self._try_cloudscraper(url, metadata, max_retries)
        if success:
            return content, metadata
            
        # Strategy 3: Alternative SSL configurations
        content, success = self._try_alternative_ssl(url, metadata, max_retries)
        if success:
            return content, metadata
            
        # Strategy 4: Proxy/VPN recommendations (placeholder)
        logger.warning(f"All scraping strategies failed for {url}")
        metadata['final_status'] = 'failed'
        return None, metadata
    
    def _try_standard_request(self, url: str, metadata: Dict, max_retries: int) -> Tuple[Optional[str], bool]:
        """Try standard requests session"""
        metadata['method_used'] = 'standard_requests'
        
        for attempt in range(max_retries):
            try:
                metadata['attempts'] += 1
                logger.info(f"Standard request attempt {attempt + 1} for {url}")
                
                # Randomize user agent for each attempt
                self.session.headers['User-Agent'] = self._get_random_user_agent()
                
                response = self.session.get(
                    url,
                    timeout=(10, 30),  # (connection, read) timeout
                    verify=True,  # Verify SSL certificates
                    allow_redirects=True
                )
                
                metadata['final_status'] = response.status_code
                
                if response.status_code == 200:
                    logger.info(f"Successfully scraped {url} with standard request")
                    return response.text, True
                elif response.status_code == 525:
                    logger.warning(f"Cloudflare SSL error (525) for {url}")
                    metadata['error_type'] = 'cloudflare_ssl_error'
                elif response.status_code in [403, 429]:
                    logger.warning(f"Access denied/rate limited ({response.status_code}) for {url}")
                    metadata['error_type'] = 'access_denied'
                else:
                    logger.warning(f"HTTP {response.status_code} for {url}")
                    metadata['error_type'] = f'http_{response.status_code}'
                
                if attempt < max_retries - 1:
                    self._adaptive_delay(attempt)
                    
            except requests.exceptions.SSLError as e:
                logger.warning(f"SSL error for {url}: {str(e)}")
                metadata['error_type'] = 'ssl_error'
                if attempt < max_retries - 1:
                    self._adaptive_delay(attempt)
            except requests.exceptions.Timeout as e:
                logger.warning(f"Timeout for {url}: {str(e)}")
                metadata['error_type'] = 'timeout'
                if attempt < max_retries - 1:
                    self._adaptive_delay(attempt)
            except Exception as e:
                logger.error(f"Unexpected error for {url}: {str(e)}")
                metadata['error_type'] = 'unexpected_error'
                if attempt < max_retries - 1:
                    self._adaptive_delay(attempt)
        
        return None, False
    
    def _try_cloudscraper(self, url: str, metadata: Dict, max_retries: int) -> Tuple[Optional[str], bool]:
        """Try CloudScraper for Cloudflare-protected sites"""
        metadata['method_used'] = 'cloudscraper'
        
        for attempt in range(max_retries):
            try:
                metadata['attempts'] += 1
                logger.info(f"CloudScraper attempt {attempt + 1} for {url}")
                
                response = self.cloudscraper_session.get(
                    url,
                    timeout=(15, 45)
                )
                
                metadata['final_status'] = response.status_code
                
                if response.status_code == 200:
                    logger.info(f"Successfully scraped {url} with CloudScraper")
                    return response.text, True
                    
                if attempt < max_retries - 1:
                    self._adaptive_delay(attempt)
                    
            except Exception as e:
                logger.warning(f"CloudScraper error for {url}: {str(e)}")
                metadata['error_type'] = 'cloudscraper_error'
                if attempt < max_retries - 1:
                    self._adaptive_delay(attempt)
        
        return None, False
    
    def _try_alternative_ssl(self, url: str, metadata: Dict, max_retries: int) -> Tuple[Optional[str], bool]:
        """Try alternative SSL configurations"""
        metadata['method_used'] = 'alternative_ssl'
        
        # Create a session with relaxed SSL verification
        alt_session = requests.Session()
        alt_session.headers.update(self.session.headers)
        
        for attempt in range(max_retries):
            try:
                metadata['attempts'] += 1
                logger.info(f"Alternative SSL attempt {attempt + 1} for {url}")
                
                # Try with disabled SSL verification (last resort)
                response = alt_session.get(
                    url,
                    timeout=(10, 30),
                    verify=False,  # Disable SSL verification
                    allow_redirects=True
                )
                
                metadata['final_status'] = response.status_code
                
                if response.status_code == 200:
                    logger.info(f"Successfully scraped {url} with alternative SSL")
                    return response.text, True
                    
                if attempt < max_retries - 1:
                    self._adaptive_delay(attempt)
                    
            except Exception as e:
                logger.warning(f"Alternative SSL error for {url}: {str(e)}")
                metadata['error_type'] = 'alternative_ssl_error'
                if attempt < max_retries - 1:
                    self._adaptive_delay(attempt)
        
        return None, False

def update_to_scrape_status(url: str, status: str, metadata: Dict = None):
    """Update the to_scrape.json file with detailed status information"""
    try:
        with open('/root/prod/news1/backend/to_scrape.json', 'r') as f:
            to_scrape = json.load(f)
        
        # Create detailed status object
        status_info = {
            'status': status,
            'timestamp': datetime.now().isoformat(),
            'metadata': metadata or {}
        }
        
        to_scrape[url] = status_info
        
        with open('/root/prod/news1/backend/to_scrape.json', 'w') as f:
            json.dump(to_scrape, f, indent=2)
            
        logger.info(f"Updated status for {url}: {status}")
        
    except Exception as e:
        logger.error(f"Error updating to_scrape.json: {str(e)}")

def process_failed_urls(batch_size: int = 10, delay_between_batches: int = 60):
    """Process URLs that previously failed"""
    try:
        with open('/root/prod/news1/backend/to_scrape.json', 'r') as f:
            to_scrape = json.load(f)
        
        # Find URLs that failed (empty string values)
        failed_urls = [url for url, status in to_scrape.items() if status == ""]
        
        logger.info(f"Found {len(failed_urls)} failed URLs to retry")
        
        scraper = EnhancedScraper()
        
        # Process in batches to avoid overwhelming servers
        for i in range(0, len(failed_urls), batch_size):
            batch = failed_urls[i:i+batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}: {len(batch)} URLs")
            
            for url in batch:
                try:
                    content, metadata = scraper.scrape_url(url)
                    
                    if content:
                        # Success - update with detailed status
                        update_to_scrape_status(url, "scraped_enhanced", metadata)
                        logger.info(f"✅ Successfully scraped: {url}")
                    else:
                        # Failed - update with error details
                        update_to_scrape_status(url, "failed_enhanced", metadata)
                        logger.warning(f"❌ Failed to scrape: {url} - {metadata.get('error_type', 'unknown')}")
                        
                except Exception as e:
                    logger.error(f"Error processing {url}: {str(e)}")
                    update_to_scrape_status(url, "error_enhanced", {'error': str(e)})
                
                # Small delay between individual requests
                time.sleep(random.uniform(1, 3))
            
            # Longer delay between batches
            if i + batch_size < len(failed_urls):
                logger.info(f"Waiting {delay_between_batches} seconds before next batch...")
                time.sleep(delay_between_batches)
        
        logger.info("Finished processing failed URLs")
        
    except Exception as e:
        logger.error(f"Error in process_failed_urls: {str(e)}")

if __name__ == "__main__":
    # Run the enhanced scraper on failed URLs
    process_failed_urls()