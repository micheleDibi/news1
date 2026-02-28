import requests
import json
from bs4 import BeautifulSoup
import pandas as pd
import re

class BandiScraper:
    def __init__(self):
        self.base_url = "https://www.interno.gov.it"
        self.ajax_url = f"{self.base_url}/it/views/ajax"
        self.headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", 
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest"
        }
        
    def get_view_dom_id(self):
        """Ottiene il view_dom_id necessario per le richieste Ajax"""
        response = requests.get(f"{self.base_url}/it/amministrazione-trasparente/bandi-gara-e-contratti")
        soup = BeautifulSoup(response.text, 'html.parser')
        # Trova l'elemento view con classe js-view-dom-id-*
        view_div = soup.find(class_=re.compile('js-view-dom-id-'))
        if view_div:
            class_list = view_div['class']
            for class_name in class_list:
                if class_name.startswith('js-view-dom-id-'):
                    return class_name.replace('js-view-dom-id-', '')
        return None
    
    def get_bandi(self, page=0, filters=None):
        """
        Ottiene i bandi dalla pagina specificata
        
        Args:
            page (int): Numero di pagina (0-based)
            filters (dict): Filtri da applicare (opzionale)
        
        Returns:
            list: Lista di dizionari contenenti i dati dei bandi
        """
        view_dom_id = self.get_view_dom_id()
        
        print(f"Using view_dom_id: {view_dom_id}")
        
        data = {
            "view_name": "alalbo_pretorio",
            "view_display_id": "blocco_bandi_2",
            "view_args": "",
            "view_path": "/node/949",
            "view_base_path": "",
            "view_dom_id": view_dom_id,
            "pager_element": 0,
            "page": page,
            "_drupal_ajax": "1"
        }
        
        # Aggiungi filtri se presenti
        if filters:
            data.update(filters)
            
        print(f"Sending request to {self.ajax_url} with data: {data}")
        response = requests.post(self.ajax_url, headers=self.headers, data=data)
        
        if response.status_code != 200:
            print(f"Error: {response.status_code}")
            print(response.text)
            return []
            
        json_data = response.json()
        
        # Estrai l'HTML dal comando "insert"
        html_content = None
        for command in json_data:
            if command["command"] == "insert" and "data" in command:
                html_content = command["data"]
                break
        
        if html_content:
            return self._parse_bandi_html(html_content)
        else:
            print("No HTML content found in response")
            print(json_data)
            return []
    
    def _parse_bandi_html(self, html):
        """
        Analizza l'HTML e estrae i dati dei bandi
        
        Args:
            html (str): HTML dei bandi
            
        Returns:
            list: Lista di dizionari contenenti i dati dei bandi
        """
        soup = BeautifulSoup(html, 'html.parser')
        bandi = []
        
        for row in soup.find_all('div', {'class': 'views-row'}):
            bando = {}
            
            # Estrai titolo e link
            title_div = row.find('div', {'class': 'views-field-title'})
            if title_div:
                title_link = title_div.find('a')
                if title_link:
                    bando['titolo'] = title_link.text.strip()
                    bando['url'] = f"{self.base_url}{title_link['href']}"
            
            # Estrai data atto
            data_div = row.find('div', {'class': 'views-field-field-data-atto'})
            if data_div:
                time_tag = data_div.find('time')
                if time_tag:
                    bando['data_atto'] = time_tag['datetime']
                    bando['data_atto_human'] = time_tag.text.strip()
            
            # Estrai scadenza (se presente)
            scadenza_div = row.find('div', {'class': 'views-field-field-end-date'})
            if scadenza_div:
                time_tag = scadenza_div.find('time')
                if time_tag:
                    bando['scadenza'] = time_tag['datetime']
                    bando['scadenza_human'] = time_tag.text.strip()
            
            # Estrai origine del bando
            origine_div = row.find('div', {'class': 'views-field-field-tender-notice-source'})
            if origine_div:
                content_div = origine_div.find('div', {'class': 'field-content'})
                if content_div:
                    bando['origine'] = content_div.text.strip()
            
            # Estrai ufficio di riferimento
            ufficio_div = row.find('div', {'class': 'views-field-field-ufficio-riferimento'})
            if ufficio_div:
                content_div = ufficio_div.find('div', {'class': 'field-content'})
                if content_div:
                    bando['ufficio'] = content_div.text.strip()
            
            # Estrai codice CIG
            cig_div = row.find('div', {'class': 'views-field-field-codice-cig'})
            if cig_div:
                content_div = cig_div.find('div', {'class': 'field-content'})
                if content_div:
                    bando['cig'] = content_div.text.strip()
            
            # Estrai link ANAC
            anac_div = row.find('div', {'class': 'views-field-field-link-anac'})
            if anac_div:
                link = anac_div.find('a')
                if link:
                    bando['link_anac'] = link['href']
            
            bandi.append(bando)
            
        return bandi
    
    def get_all_bandi(self, max_pages=10, filters=None):
        """
        Ottiene tutti i bandi da tutte le pagine fino a max_pages
        
        Args:
            max_pages (int): Numero massimo di pagine da scaricare
            filters (dict): Filtri da applicare (opzionale)
            
        Returns:
            list: Lista di dizionari contenenti i dati di tutti i bandi
        """
        all_bandi = []
        
        for page in range(max_pages):
            print(f"Scaricando pagina {page+1}...")
            bandi_page = self.get_bandi(page=page, filters=filters)
            if not bandi_page:
                print(f"Nessun bando trovato nella pagina {page+1}. Terminato.")
                break
                
            all_bandi.extend(bandi_page)
            print(f"Scaricata pagina {page+1}, trovati {len(bandi_page)} bandi")
            
        return all_bandi
    
    def save_to_csv(self, bandi, filename="bandi_gara.csv"):
        """
        Salva i bandi in un file CSV
        
        Args:
            bandi (list): Lista di dizionari contenenti i dati dei bandi
            filename (str): Nome del file CSV
        """
        df = pd.DataFrame(bandi)
        df.to_csv(filename, index=False)
        print(f"Salvati {len(bandi)} bandi nel file {filename}")
        
    def get_dettaglio_bando(self, url):
        """
        Ottiene i dettagli di un singolo bando
        
        Args:
            url (str): URL della pagina di dettaglio del bando
            
        Returns:
            dict: Dizionario contenente i dettagli del bando
        """
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        dettaglio = {}
        
        # Estrai titolo
        title = soup.find('h1', {'class': 'page-title'})
        if title:
            dettaglio['titolo'] = title.text.strip()
        
        # Estrai corpo del testo
        body = soup.find('div', {'class': 'field--name-body'})
        if body:
            dettaglio['descrizione'] = body.text.strip()
        
        # Estrai allegati
        attachments = []
        attachment_divs = soup.find_all('div', {'class': 'field--name-field-allegati'})
        for div in attachment_divs:
            links = div.find_all('a')
            for link in links:
                attachment = {
                    'nome': link.text.strip(),
                    'url': link['href'] if link['href'].startswith('http') else f"{self.base_url}{link['href']}"
                }
                attachments.append(attachment)
        
        dettaglio['allegati'] = attachments
        
        return dettaglio

# Esempio di utilizzo
if __name__ == "__main__":
    scraper = BandiScraper()
    
    # Esempio con filtri (lasciamo vuoti per prendere tutti i bandi)
    filters = {
        "field_codice_cig_value": "",  # Filtro per CIG specifico
        "field_tender_notice_source_target_id": "All",  # Origine del bando
        "combine": ""  # Ricerca testuale
    }
    
    # Ottieni 2 pagine di bandi per test
    bandi = scraper.get_all_bandi(max_pages=10, filters=filters)
    
    if bandi:
        # Salva i risultati in CSV
        scraper.save_to_csv(bandi, filename="bandi_gara.csv")
        
        # Esempio di come ottenere dettagli di un singolo bando
        if len(bandi) > 0:
            print("\nDettaglio del primo bando:")
            dettaglio = scraper.get_dettaglio_bando(bandi[0]['url'])
            print(json.dumps(dettaglio, indent=2, ensure_ascii=False))
    else:
        print("Nessun bando trovato.")
