#!/usr/bin/env python3
"""
Scraper per i bandi del portale Italia Domani

Questo modulo fornisce funzionalità per raccogliere e processare
i dati dei bandi pubblicati sul portale Italia Domani.
"""

import requests
from bs4 import BeautifulSoup, Tag
import pandas as pd
import datetime
import os
import logging
import json
import time
from typing import List, Dict, Optional, Union, Set
from dataclasses import dataclass
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

@dataclass
class ScrapingConfig:
    """Configuration class for the scraper."""
    base_url: str = "https://www.italiadomani.gov.it/content/sogei-ng/it/it/opportunita/bandi-amministrazioni-titolari/jcr:content/root/container/newnoticessearch.searchResults.html?orderby=%40jcr%3Acontent%2Fstatus&sort=asc"
    batch_size: int = 20
    max_retries: int = 3
    pause_between_requests: float = 1.0
    request_timeout: int = 30
    output_directory: str = "output"
    
    user_agent: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
    

class BandiScraper:
    """Main scraper class for Italia Domani bandi."""
    
    def __init__(self, config: Optional[ScrapingConfig] = None):
        self.config = config or ScrapingConfig()
        self.session = self._create_session()
        self._setup_logging()
        
    def _setup_logging(self) -> None:
        """Configure logging."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
    def _create_session(self) -> requests.Session:
        """Create a requests session with retry strategy."""
        session = requests.Session()
        
        # Retry strategy
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # Set headers
        session.headers.update({
            'User-Agent': self.config.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://www.italiadomani.gov.it/content/sogei-ng/it/it/opportunita/bandi-amministrazioni-titolari.html'
        })
        
        return session

    def _extract_basic_info(self, row: Tag) -> Dict[str, str]:
        """Extract basic information from a bando row."""
        data = {}
        
        # Extract bando ID
        bando_id = row.get('id') or row.get('data-id')
        if bando_id:
            data['id'] = bando_id
            
        # Extract description and link
        description_tag = row.find('p', class_='text ellipsis')
        data['descrizione'] = self._safe_extract_text(description_tag)
        
        # Extract link - usually in an <a> tag within the description or title area
        link_tag = None
        # Try multiple possible locations for the link
        title_area = row.find('div', class_='col-lg-5 column')
        if title_area:
            link_tag = title_area.find('a')
        
        if not link_tag:
            # Alternative: look for any <a> tag in the row
            link_tag = row.find('a')
            
        if link_tag and link_tag.get('href'):
            href = link_tag.get('href')
            # Make absolute URL if relative
            if href.startswith('/'):
                data['link'] = f"https://www.italiadomani.gov.it{href}"
            elif href.startswith('http'):
                data['link'] = href
            else:
                data['link'] = f"https://www.italiadomani.gov.it/{href}"
        else:
            data['link'] = ""
        
        # Extract amministrazione titolare
        amministrazione_div = row.find('div', class_='col-lg-3 column')
        if amministrazione_div:
            amministrazione_tag = amministrazione_div.find('p', class_='text ellipsis')
            data['amministrazione_titolare'] = self._safe_extract_text(amministrazione_tag)
        else:
            data['amministrazione_titolare'] = ""
            
        # Extract data di chiusura and stato from col-lg-2 columns
        chiusura_columns = row.find_all('div', class_='col-lg-2 column')
        data['data_chiusura'] = ""
        data['stato'] = ""
        
        for col in chiusura_columns:
            col_text = col.get_text(strip=True)
            
            # Try multiple strategies to find status
            status_tag = None
            status_text = ""
            
            # Strategy 1: Look for specific status classes
            status_candidates = [
                col.find('div', class_='status-item loading'),
                col.find('div', class_='status-item'),
                col.find('div', class_=lambda x: x and any(cls in x.lower() for cls in ['status', 'stato'])),
                col.find('span', class_=lambda x: x and any(cls in x.lower() for cls in ['status', 'stato'])),
                col.find('div', class_=lambda x: x and any(cls in x.lower() for cls in ['badge', 'tag', 'label']))
            ]
            
            for candidate in status_candidates:
                if candidate:
                    candidate_text = self._safe_extract_text(candidate)
                    if candidate_text and self._looks_like_status(candidate_text):
                        status_text = candidate_text
                        break
            
            # Strategy 2: If no explicit status element, check if column text looks like status
            if not status_text and col_text and self._looks_like_status(col_text):
                status_text = col_text
            
            # Strategy 3: Check for date/closure info
            if not status_text:
                date_tag = col.find('p', class_='text')
                if date_tag:
                    date_text = date_tag.text.strip()
                    if date_text and not self._looks_like_status(date_text) and not data['data_chiusura']:
                        data['data_chiusura'] = date_text
                    elif date_text and self._looks_like_status(date_text) and not data['stato']:
                        status_text = date_text
            
            # Assign status if found
            if status_text and not data['stato']:
                data['stato'] = status_text
                
        return data
        
    def _safe_extract_text(self, tag: Optional[Tag]) -> str:
        """Safely extract text from a BeautifulSoup tag."""
        return tag.text.strip() if tag else ""
        
    def _looks_like_status(self, text: str) -> bool:
        """Check if text looks like a status value."""
        status_keywords = [
            'in corso', 'in programma', 'concluso', 'chiuso', 'aperto', 
            'sospeso', 'annullato', 'scaduto', 'attivo', 'non attivo',
            'programmato', 'avviato', 'terminato', 'pubblicato'
        ]
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in status_keywords)
        
    def _is_status_column(self, col: Tag) -> bool:
        """Check if a column contains status information."""
        return (col.find('div', class_='status-item loading') is not None or
                col.find('div', class_='status-item') is not None or
                col.find('div', class_=lambda x: x and 'status' in x.lower()) is not None)
        
    def _extract_accordion_data(self, row: Tag) -> Dict[str, str]:
        """Extract data from accordion sections."""
        data = {}
        
        # Find accordion
        accordion = row.select_one('div.col-12.column div.accordion')
        if not accordion:
            return data
            
        # Parse accordion text directly - this is what works
        accordion_text = accordion.get_text()
        lines = [line.strip() for line in accordion_text.split('\n') if line.strip()]
        
        # Extract fields using line-by-line parsing
        for i in range(len(lines) - 1):
            current_line = lines[i].lower()
            next_line = lines[i + 1]
            
            field_patterns = {
                'data_apertura': 'data di apertura',
                'area_geografica': 'area geografica', 
                'destinatari': 'destinatari',
                'tipologia': 'tipologia'
            }
            
            for field_name, pattern in field_patterns.items():
                if pattern in current_line and field_name not in data:
                    if next_line and not any(keyword in next_line.lower() 
                                           for keyword in ['focus', 'pnrr', 'mostra', 'nascondi', 'vai']):
                        data[field_name] = next_line
                        break
        
        # Extract focus PNRR data
        focus_item = accordion.find('div', class_='focus-item')
        if focus_item:
            focus_title = focus_item.find('h5', class_='item-title')
            if focus_title:
                data['focus_pnrr'] = self._safe_extract_text(focus_title)
            
            focus_info = focus_item.find('div', class_='focus-info-content')
            if focus_info:
                single_info = focus_info.find('div', class_='single-info')
                if single_info:
                    description_p = single_info.find('p')
                    if description_p:
                        data['descrizione_fondo_pnrr'] = self._safe_extract_text(description_p)
        
        return data
        
        
    def _parse_bando_row(self, row: Tag) -> Dict[str, str]:
        """Parse a single bando row and extract all data."""
        # Start with basic info
        bando_data = self._extract_basic_info(row)
        
        # Add accordion data
        bando_data.update(self._extract_accordion_data(row))
        
        # Ensure all required fields are present with NULL if not found
        required_fields = {
            'data_apertura': 'NULL',
            'area_geografica': 'NULL', 
            'destinatari': 'NULL',
            'tipologia': 'NULL'
        }
        
        for field, default_value in required_fields.items():
            if field not in bando_data or not bando_data[field]:
                bando_data[field] = default_value
        
        return bando_data
    
    def get_bandi_from_endpoint(self, url: str) -> List[Dict[str, str]]:
        """Fetch and parse bandi data from the endpoint."""
        self.logger.info(f"Fetching data from: {url}")
        
        try:
            response = self.session.get(url, timeout=self.config.request_timeout)
            response.raise_for_status()
            
            # Parse the HTML response
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Find all bandi containers
            rows = soup.find_all(lambda tag: tag.name == 'div' and 
                                tag.get('class') and 
                                'item-wrapper' in tag.get('class'))
                                
            self.logger.info(f"Found {len(rows)} bandi entries")
            
            all_data = []
            for row in rows:
                try:
                    bando_data = self._parse_bando_row(row)
                    all_data.append(bando_data)
                except Exception as e:
                    self.logger.warning(f"Error parsing single bando row: {e}")
                    continue
                    
            return all_data
            
        except requests.RequestException as e:
            self.logger.error(f"HTTP error fetching data: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error fetching data: {e}")
            return []

    def _get_unique_identifier(self, bando: Dict[str, str]) -> str:
        """Get a unique identifier for a bando to detect duplicates."""
        # Prefer ID if available, otherwise use description
        return bando.get('id') or bando.get('descrizione', '')
        
    def _validate_bando_data(self, bando: Dict[str, str]) -> bool:
        """Validate that a bando has minimum required data."""
        # At minimum, we should have a description
        return bool(bando.get('descrizione', '').strip())
        
    def fetch_all_bandi(self) -> List[Dict[str, str]]:
        """Fetch all bandi by paginating through the API endpoints."""
        all_bandi = []
        seen_identifiers: Set[str] = set()
        offset = 0
        has_more_data = True
        retry_count = 0
        
        self.logger.info("Starting data collection from Italia Domani bandi...")
        
        while has_more_data and retry_count < self.config.max_retries:
            # Construct URL with correct offset
            if offset == 0:
                url = self.config.base_url
            else:
                url = f"{self.config.base_url}&resultsOffset={offset}"
            
            # Get batch of bandi
            batch = self.get_bandi_from_endpoint(url)
            
            if not batch:
                # No data returned, increase retry counter
                retry_count += 1
                self.logger.warning(f"No data returned. Retry {retry_count}/{self.config.max_retries}")
                time.sleep(self.config.pause_between_requests * 2)
                continue
            
            # Reset retry counter if we got data
            retry_count = 0
            
            # Process batch and filter duplicates
            new_items = 0
            for bando in batch:
                # Validate data
                if not self._validate_bando_data(bando):
                    self.logger.warning("Skipping bando with invalid data")
                    continue
                    
                # Check for duplicates
                identifier = self._get_unique_identifier(bando)
                
                if identifier and identifier not in seen_identifiers:
                    seen_identifiers.add(identifier)
                    all_bandi.append(bando)
                    new_items += 1
                    
            self.logger.info(f"Retrieved {len(batch)} bandi, {new_items} new items")
            
            # Check if we should continue
            has_more_data = (new_items > 0 and 
                           len(batch) >= self.config.batch_size)
            
            # Increment offset for next page
            offset += self.config.batch_size
            
            # Be respectful of the server
            time.sleep(self.config.pause_between_requests)
        
        self.logger.info(f"Total unique bandi collected: {len(all_bandi)}")
        return all_bandi

    def save_data(self, bandi_data: List[Dict[str, str]]) -> Dict[str, str]:
        """Save the collected bandi data to CSV and JSON files."""
        if not bandi_data:
            raise ValueError("No data to save")
            
        # Create DataFrame
        df = pd.DataFrame(bandi_data)
        
        # Generate timestamp
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Ensure output directory exists
        os.makedirs(self.config.output_directory, exist_ok=True)
        
        # Define output paths
        output_csv = os.path.join(
            self.config.output_directory, 
            f"bandi_italiadomani_{timestamp}.csv"
        )
        output_json = os.path.join(
            self.config.output_directory,
            f"bandi_italiadomani_{timestamp}.json"
        )
        
        try:
            # Save CSV
            df.to_csv(output_csv, index=False, encoding='utf-8')
            
            # Save JSON
            with open(output_json, 'w', encoding='utf-8') as f:
                json.dump(bandi_data, f, ensure_ascii=False, indent=2)
                
            self.logger.info(f"Data collection completed. Files saved:")
            self.logger.info(f"- CSV: {output_csv}")
            self.logger.info(f"- JSON: {output_json}")
            self.logger.info(f"Total bandi found: {len(bandi_data)}")
            
            return {
                "csv_path": output_csv,
                "json_path": output_json,
                "total_records": len(bandi_data)
            }
            
        except Exception as e:
            self.logger.error(f"Error saving data: {e}")
            raise
            
    def run(self) -> Dict[str, str]:
        """Main method to run the complete scraping process."""
        try:
            # Fetch all bandi data
            bandi_data = self.fetch_all_bandi()
            
            if not bandi_data:
                self.logger.error("No data found or error during data collection.")
                raise RuntimeError("No data collected")
            
            # Save data and return results
            return self.save_data(bandi_data)
            
        except Exception as e:
            self.logger.error(f"Error during scraping process: {e}")
            raise
            
    def close(self) -> None:
        """Close the session and cleanup resources."""
        if hasattr(self, 'session'):
            self.session.close()


def main():
    """Main function to run the scraper."""
    scraper = None
    try:
        # Create scraper with default configuration
        config = ScrapingConfig(
            pause_between_requests=2.0  # Be more respectful
        )
        scraper = BandiScraper(config)
        
        # Run the scraping process
        results = scraper.run()
        
        print(f"\n🎉 Scraping completed successfully!")
        print(f"📁 Files saved: {results['total_records']} records")
        print(f"📊 CSV: {results['csv_path']}")
        print(f"📋 JSON: {results['json_path']}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1
    finally:
        if scraper:
            scraper.close()
    
    return 0

if __name__ == "__main__":
    import sys
    exit_code = main()
    sys.exit(exit_code)
