#!/usr/bin/env python3
from bs4 import BeautifulSoup
import pandas as pd
import datetime
import os
import logging
from requests_html import HTMLSession

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def get_data_from_page(url):
    """
    Scrape data from the Italia Domani bandi page using requests-html to handle dynamic content
    """
    logging.info(f"Starting to scrape URL: {url}")
    
    # Create an HTML session
    session = HTMLSession()
    
    try:
        logging.info(f"Opening URL with requests-html: {url}")
        r = session.get(url)
        
        # Execute JavaScript on the page
        logging.info("Rendering JavaScript content...")
        r.html.render(sleep=5, timeout=30)  # Wait for JS execution
        
        logging.info("JavaScript rendering completed")
        
        # Save the dynamically rendered HTML to file for inspection
        with open('dynamic_page_content.html', 'w', encoding='utf-8') as f:
            f.write(r.html.html)
        logging.info("Saved dynamically rendered HTML to dynamic_page_content.html")
        
        # Parse the page with BeautifulSoup after JavaScript has executed
        soup = BeautifulSoup(r.html.html, 'lxml')
        
        # Find all rows with class containing "item-wrapper"
        logging.info("Looking for elements with class 'item-wrapper'...")
        rows = soup.find_all(lambda tag: tag.name == 'div' and tag.get('class') and 'item-wrapper' in tag.get('class'))
        logging.info(f"Found {len(rows)} elements with class 'item-wrapper'")
        
        # If still no rows found, try various alternative selectors
        if len(rows) == 0:
            logging.warning("No item-wrapper elements found. Trying alternative selectors...")
            # Try to find elements that might contain our data
            logging.info("Checking page structure for potential containers...")
            
            # Look for elements that might be our rows or containers
            potential_containers = [
                ("div[class*='row']", soup.select("div[class*='row']")[:5]),
                ("div[class*='item']", soup.select("div[class*='item']")[:5]),
                ("div[class*='bandi']", soup.select("div[class*='bandi']")[:5]),
                ("div[class*='accordion']", soup.select("div[class*='accordion']")[:5])
            ]
            
            for selector, elements in potential_containers:
                logging.info(f"Checking selector {selector}: found {len(elements)} elements")
                for i, el in enumerate(elements):
                    logging.info(f"Sample element {i} classes: {el.get('class')}")
        
        all_data = []
        
        # Extract data from each row
        for row in rows:
            item_data = {}
            
            # Estrai la descrizione
            description_tag = row.find('p', class_='text ellipsis')
            item_data['descrizione'] = description_tag.text.strip() if description_tag else ""
            
            # Estrai l'amministrazione titolare
            amministrazione_div = row.find('div', class_='col-lg-3 column')
            amministrazione_tag = amministrazione_div.find('p', class_='text ellipsis') if amministrazione_div else None
            item_data['amministrazione_titolare'] = amministrazione_tag.text.strip() if amministrazione_tag else ""
            
            # Estrai la data di chiusura
            chiusura_div = row.find('div', class_='col-lg-2 column')
            chiusura_tag = chiusura_div.find('p', class_='text') if chiusura_div else None
            item_data['data_chiusura'] = chiusura_tag.text.strip() if chiusura_tag else ""

            # Estrai lo stato
            stato_div = row.find('div', class_='col-lg-2 column')
            stato_tag = stato_div.find('div', class_='status-item loading') if stato_div else None
            item_data['stato'] = stato_tag.text.strip() if stato_tag else ""
            
            # Per i dati che sono nel accordion, dobbiamo prima trovare l'accordion
            accordion_div = row.find('div', class_='col-12 column')
            if accordion_div:
                accordion = accordion_div.find('div', class_='accordion accordion-investimenti acc-table')
                if accordion:
                    accordion_item = accordion.find('div', class_='accordion-item')
                    if accordion_item:
                        collapse_div = accordion_item.find('div', class_='collapse show')
                        if not collapse_div:
                            # Se non c'è un div con class 'collapse show', potrebbe essere perché 
                            # l'accordion è chiuso. Troviamo comunque il div con class 'collapse'
                            collapse_div = accordion_item.find('div', class_='collapse')
                        
                        if collapse_div:
                            card_body = collapse_div.find('div', class_='card-body')
                            if card_body:
                                row_div = card_body.find('div', class_='row')
                                if row_div:
                                    # Dati nella colonna sinistra
                                    left_col = row_div.find('div', class_='col-lg-5')
                                    if left_col:
                                        info_times = left_col.find_all('div', class_='info-time')
                                        for info_time in info_times:
                                            label_div = info_time.find('div', class_='info-label')
                                            value_div = info_time.find('div', class_='value')
                                            
                                            if label_div and value_div:
                                                label_text = label_div.text.strip().lower()
                                                value_text = value_div.text.strip()
                                                
                                                if "data di apertura" in label_text:
                                                    item_data['data_apertura'] = value_text
                                                elif "area geografica" in label_text:
                                                    item_data['area_geografica'] = value_text
                                                elif "tipologia" in label_text:
                                                    item_data['tipologia'] = value_text
                                                elif "destinatari" in label_text:
                                                    item_data['destinatari'] = value_text
                                    
                                    # Dati nella colonna destra
                                    right_col = row_div.find('div', class_='col-lg-7 mt-4 mt-lg-0 button-col')
                                    if right_col:
                                        focus_item = right_col.find('div', class_='focus-item')
                                        if focus_item:
                                            # Estrai Focus PNRR
                                            focus_title = focus_item.find('h5', class_='item-title')
                                            item_data['focus_pnrr'] = focus_title.text.strip() if focus_title else ""
                                            
                                            # Estrai descrizione Fondo PNRR
                                            focus_info = focus_item.find('div', class_='focus-info-content')
                                            if focus_info:
                                                single_info = focus_info.find('div', class_='single-info')
                                                if single_info:
                                                    description_p = single_info.find('p')
                                                    item_data['descrizione_fondo_pnrr'] = description_p.text.strip() if description_p else ""
            
            all_data.append(item_data)
            
    except Exception as e:
        logging.error(f"Error during scraping: {e}")
        all_data = []
    finally:
        logging.info("Closing session")
        session.close()
    
    return all_data

def main():
    url = "https://www.italiadomani.gov.it/content/sogei-ng/it/it/opportunita/bandi-amministrazioni-titolari.html?orderby=%40jcr%3Acontent%2Fstatus&sort=asc&resultsOffset=0"
    
    logging.info("Inizio scraping dei dati...")
    bandi_data = get_data_from_page(url)
    
    if not bandi_data:
        logging.error("Nessun dato trovato o errore durante lo scraping.")
        return
    
    # Crea DataFrame
    df = pd.DataFrame(bandi_data)
    
    # Aggiungi timestamp attuale
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = "output"
    
    # Crea directory di output se non esiste
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Salva il CSV con timestamp
    output_file = f"{output_dir}/bandi_italiadomani_{timestamp}.csv"
    df.to_csv(output_file, index=False, encoding='utf-8')
    
    logging.info(f"Scraping completato. Dati salvati in: {output_file}")
    logging.info(f"Totale bandi trovati: {len(bandi_data)}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.error(f"An error occurred in main execution: {e}")
