#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script completo per lo scraping degli incentivi dal sito https://www.incentivi.gov.it/it/catalogo
Estrae la lista degli incentivi e per ciascuno recupera tutti i dettagli.
Salva i risultati in formato JSON e CSV con timestamp.
"""

from requests_html import HTMLSession
import requests
from bs4 import BeautifulSoup
import json
import csv
import os
import re
from datetime import datetime
import argparse
import time
from urllib.parse import urlparse

def scrape_catalogo_incentivi():
    """
    Estrae la lista degli incentivi dal catalogo principale.
    """
    url = "https://www.incentivi.gov.it/it/catalogo"
    
    print(f"Accesso alla pagina del catalogo: {url}")
    
    session = HTMLSession()
    
    try:
        response = session.get(url)
        print("Renderizzazione della pagina con JavaScript...")
        response.html.render(sleep=2, timeout=20)
        
        links = response.html.links
        incentivi_base = []
        
        # Filtra i link che contengono '/catalogo/' ma non sono la pagina principale
        for link in links:
            if '/catalogo/' in link and link != '/it/catalogo':
                elements = response.html.find(f'a[href="{link}"]')
                if elements:
                    element = elements[0]
                    text = element.text.strip()
                    if text:
                        # Rimuovi il prefisso "vai alla scheda" se presente
                        if "vai alla scheda" in text.lower():
                            text = text.lower().replace("vai alla scheda", "").strip().capitalize()
                        
                        # Crea URL completo se necessario
                        full_link = f"https://www.incentivi.gov.it{link}" if link.startswith('/') else link
                        
                        incentivi_base.append({
                            'titolo_base': text,
                            'link': full_link
                        })
        
        # Rimuovi eventuali duplicati basati sul link
        risultati_unici = []
        links_visti = set()
        
        for incentivo in incentivi_base:
            if incentivo['link'] not in links_visti:
                links_visti.add(incentivo['link'])
                risultati_unici.append(incentivo)
        
        print(f"Trovati {len(risultati_unici)} incentivi nel catalogo")
        return risultati_unici
    
    except Exception as e:
        print(f"Errore durante lo scraping del catalogo: {str(e)}")
        return []
    
    finally:
        session.close()

def estrai_dettagli_incentivo(url, titolo_base):
    """
    Estrae tutti i dettagli di un singolo incentivo.
    """
    try:
        print(f"Elaborazione: {titolo_base}")
        
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Titolo principale dalla pagina
        titolo_h1 = soup.find('h1')
        titolo_dettagliato = titolo_h1.get_text(strip=True) if titolo_h1 else titolo_base

        # Stato incentivo
        stato_incentivo = None
        possible_keywords = ["aperto", "chiuso", "attivo", "attivi", "in arrivo", "in corso", "scaduto", "terminato", "esaurito", "disponibile"]
        
        # Badge o label
        for badge in soup.find_all(['span', 'div', 'strong', 'p', 'li'], class_=re.compile(r'(badge|stato|label|status)', re.I)):
            testo = badge.get_text(strip=True).lower()
            for k in possible_keywords:
                if k in testo:
                    stato_incentivo = testo
                    break
            if stato_incentivo:
                break
        
        # Fallback: cerca testo in tutta la pagina
        if not stato_incentivo:
            body_text = soup.get_text(" ", strip=True).lower()
            for k in possible_keywords:
                if k in body_text:
                    stato_incentivo = k
                    break
        
        # Additional check: look for status patterns in the page text
        if not stato_incentivo:
            # Look for common status patterns
            status_patterns = [
                r'bando.*?attivo.*?\d{1,2}:\d{2}',  # "bando attivo dalle ore 10:00"
                r'servizio.*?attivo.*?\d{1,2}:\d{2}',  # "servizio attivo dalle ore"
                r'sportello.*?attivo.*?\d{1,2}:\d{2}',  # "sportello attivo dalle ore"
                r'attivo.*?dal.*?\d{1,2}/\d{1,2}/\d{4}',  # "attivo dal 08/04/2025"
                r'attivo.*?fino.*?esaurimento',  # "attivo fino ad esaurimento"
                r'in arrivo',  # "in arrivo"
                r'disponibile',  # "disponibile"
            ]
            
            for pattern in status_patterns:
                match = re.search(pattern, body_text, re.IGNORECASE)
                if match:
                    if 'attivo' in match.group(0).lower():
                        stato_incentivo = 'attivo'
                    elif 'in arrivo' in match.group(0).lower():
                        stato_incentivo = 'in arrivo'
                    elif 'disponibile' in match.group(0).lower():
                        stato_incentivo = 'disponibile'
                    break

        # Data apertura e chiusura
        data_apertura = None
        data_chiusura = None
        
        # Cerca in tutti i tag di testo
        for tag in soup.find_all(text=True):
            txt = tag.strip().lower()
            # Cerca "data apertura" o "apertura"
            if ("data apertura" in txt or "apertura" in txt) and not data_apertura:
                date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{2,4})', txt)
                if date_match:
                    data_apertura = date_match.group(1)
            # Cerca "data chiusura" o "chiusura"
            if ("data chiusura" in txt or "chiusura" in txt) and not data_chiusura:
                date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{2,4})', txt)
                if date_match:
                    data_chiusura = date_match.group(1)
        
        # Se non trovate, cerca pattern di date in tutta la pagina
        if not data_apertura or not data_chiusura:
            all_dates = re.findall(r'(\d{1,2}/\d{1,2}/\d{2,4})', soup.get_text(" ", strip=True))
            if not data_apertura and all_dates:
                data_apertura = all_dates[0]
            if not data_chiusura and len(all_dates) > 1:
                data_chiusura = all_dates[1]

        # Estrarre tutte le sezioni principali
        contenuto = {}
        main_content = soup.find('main') or soup
        headers = main_content.find_all(['h2', 'h3', 'h4'])
        
        for header in headers:
            titolo_sezione = header.get_text(strip=True)
            if titolo_sezione:  # Solo se il titolo non è vuoto
                testo = []
                for sibling in header.next_siblings:
                    if sibling.name in ['h2', 'h3', 'h4']:
                        break
                    if hasattr(sibling, 'get_text'):
                        txt = sibling.get_text(strip=True)
                        if txt:
                            testo.append(txt)
                contenuto[titolo_sezione] = '\n'.join(testo)

        dati = {
            'titolo_base': titolo_base,
            'titolo_dettagliato': titolo_dettagliato,
            'stato_incentivo': stato_incentivo,
            'data_apertura': data_apertura,
            'data_chiusura': data_chiusura,
            'sezioni': contenuto,
            'link_ufficiale': url,
            'timestamp': datetime.now().isoformat()
        }
        
        return dati
    
    except Exception as e:
        print(f"Errore durante l'estrazione dettagli per {url}: {str(e)}")
        return {
            'titolo_base': titolo_base,
            'titolo_dettagliato': titolo_base,
            'stato_incentivo': None,
            'data_apertura': None,
            'data_chiusura': None,
            'sezioni': {},
            'link_ufficiale': url,
            'timestamp': datetime.now().isoformat(),
            'errore': str(e)
        }

def pulisci_testo(testo):
    """
    Pulisce e formatta il testo per CSV.
    """
    if not testo:
        return ""
    
    # Rimuovi caratteri HTML
    testo = testo.replace("&#039;", "'").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    
    # Rimuovi spazi eccessivi e caratteri di controllo
    import html
    testo = html.unescape(testo)
    testo = re.sub(r'\s+', ' ', testo)  # Sostituisci spazi multipli con uno singolo
    testo = testo.strip()
    
    # Limita la lunghezza per CSV
    if len(testo) > 500:
        testo = testo[:497] + "..."
    
    return testo

def estrai_info_strutturate(sezioni):
    """
    Estrae informazioni strutturate dalle sezioni per CSV.
    """
    info = {
        'descrizione': '',
        'beneficiari': '',
        'settore': '',
        'regioni': '',
        'forma_agevolazione': '',
        'spesa_min_max': '',
        'stanziamento': '',
        'soggetto_gestore': '',
        'sito_riferimento': '',
        'base_normativa': '',
        'note_aggiuntive': ''
    }
    
    for sezione, contenuto in sezioni.items():
        contenuto_pulito = pulisci_testo(contenuto)
        sezione_lower = sezione.lower()
        
        # Mappatura intelligente delle sezioni
        if any(keyword in sezione_lower for keyword in ["cos'è", "cosa prevede", "descrizione", "obiettivo", "finalità"]):
            if not info['descrizione']:
                info['descrizione'] = contenuto_pulito
        
        elif any(keyword in sezione_lower for keyword in ["chi si rivolge", "beneficiari", "tipologia soggetto"]):
            info['beneficiari'] = contenuto_pulito
        
        elif any(keyword in sezione_lower for keyword in ["settore", "ateco"]):
            info['settore'] = contenuto_pulito
        
        elif any(keyword in sezione_lower for keyword in ["regioni", "ambito territoriale"]):
            info['regioni'] = contenuto_pulito
        
        elif any(keyword in sezione_lower for keyword in ["forma agevolazione", "agevolazione concedibile"]):
            info['forma_agevolazione'] = contenuto_pulito
        
        elif any(keyword in sezione_lower for keyword in ["spesa ammessa", "agevolazione concedibile"]):
            info['spesa_min_max'] = contenuto_pulito
        
        elif any(keyword in sezione_lower for keyword in ["stanziamento"]):
            info['stanziamento'] = contenuto_pulito
        
        elif any(keyword in sezione_lower for keyword in ["soggetto gestore", "gestore"]):
            info['soggetto_gestore'] = contenuto_pulito
        
        elif any(keyword in sezione_lower for keyword in ["sito", "riferimento"]):
            info['sito_riferimento'] = contenuto_pulito
        
        elif any(keyword in sezione_lower for keyword in ["base normativa", "normativa"]):
            info['base_normativa'] = contenuto_pulito
        
        elif any(keyword in sezione_lower for keyword in ["note", "altre caratteristiche"]):
            info['note_aggiuntive'] = contenuto_pulito
    
    return info

def salva_risultati(incentivi_dettagliati, output_dir='output'):
    """
    Salva i risultati in formato JSON e CSV con timestamp.
    """
    # Crea la directory di output se non esiste
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Creata directory: {output_dir}")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Salvataggio JSON
    json_filename = os.path.join(output_dir, f"incentivi_completi_{timestamp}.json")
    try:
        with open(json_filename, 'w', encoding='utf-8') as json_file:
            json.dump(incentivi_dettagliati, json_file, ensure_ascii=False, indent=2)
        print(f"Dati JSON salvati in: {json_filename}")
    except Exception as e:
        print(f"Errore durante il salvataggio JSON: {str(e)}")
    
    # Salvataggio CSV migliorato
    csv_filename = os.path.join(output_dir, f"incentivi_completi_{timestamp}.csv")
    try:
        with open(csv_filename, 'w', newline='', encoding='utf-8') as csv_file:
            if incentivi_dettagliati:
                # Definisci colonne logiche e ordinate
                fieldnames = [
                    'id_progressivo',
                    'titolo',
                    'stato',
                    'data_apertura',
                    'data_chiusura',
                    'descrizione',
                    'beneficiari',
                    'settore',
                    'regioni',
                    'forma_agevolazione',
                    'spesa_min_max',
                    'stanziamento',
                    'soggetto_gestore',
                    'sito_riferimento',
                    'base_normativa',
                    'note_aggiuntive',
                    'link_ufficiale',
                    'data_elaborazione'
                ]
                
                # Aggiungi colonna errore se presente
                if any('errore' in incentivo for incentivo in incentivi_dettagliati):
                    fieldnames.append('errore')
                
                writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
                writer.writeheader()
                
                for i, incentivo in enumerate(incentivi_dettagliati, 1):
                    # Estrai informazioni strutturate dalle sezioni
                    info_strutturate = estrai_info_strutturate(incentivo.get('sezioni', {}))
                    
                    # Usa il titolo dettagliato se disponibile, altrimenti quello base
                    titolo = incentivo.get('titolo_dettagliato') or incentivo.get('titolo_base', '')
                    titolo = pulisci_testo(titolo)
                    
                    # Formatta le date
                    data_apertura = incentivo.get('data_apertura', '')
                    data_chiusura = incentivo.get('data_chiusura', '')
                    
                    # Pulisci lo stato
                    stato = pulisci_testo(incentivo.get('stato_incentivo', ''))
                    
                    # Data di elaborazione formattata
                    try:
                        timestamp_obj = datetime.fromisoformat(incentivo.get('timestamp', ''))
                        data_elaborazione = timestamp_obj.strftime('%d/%m/%Y %H:%M')
                    except:
                        data_elaborazione = incentivo.get('timestamp', '')
                    
                    row = {
                        'id_progressivo': i,
                        'titolo': titolo,
                        'stato': stato,
                        'data_apertura': data_apertura,
                        'data_chiusura': data_chiusura,
                        'descrizione': info_strutturate['descrizione'],
                        'beneficiari': info_strutturate['beneficiari'],
                        'settore': info_strutturate['settore'],
                        'regioni': info_strutturate['regioni'],
                        'forma_agevolazione': info_strutturate['forma_agevolazione'],
                        'spesa_min_max': info_strutturate['spesa_min_max'],
                        'stanziamento': info_strutturate['stanziamento'],
                        'soggetto_gestore': info_strutturate['soggetto_gestore'],
                        'sito_riferimento': info_strutturate['sito_riferimento'],
                        'base_normativa': info_strutturate['base_normativa'],
                        'note_aggiuntive': info_strutturate['note_aggiuntive'],
                        'link_ufficiale': incentivo.get('link_ufficiale', ''),
                        'data_elaborazione': data_elaborazione
                    }
                    
                    # Aggiungi errore se presente
                    if 'errore' in incentivo:
                        row['errore'] = pulisci_testo(str(incentivo['errore']))
                    
                    writer.writerow(row)
        
        print(f"Dati CSV migliorati salvati in: {csv_filename}")
    except Exception as e:
        print(f"Errore durante il salvataggio CSV: {str(e)}")
    
    return json_filename, csv_filename

def main():
    """Funzione principale"""
    parser = argparse.ArgumentParser(description='Scraping completo incentivi da incentivi.gov.it')
    parser.add_argument('--output-dir', default='output', help='Directory di output (default: output)')
    parser.add_argument('--delay', type=float, default=1.0, help='Delay tra le richieste in secondi (default: 1.0)')
    parser.add_argument('--max-incentivi', type=int, help='Numero massimo di incentivi da elaborare (per testing)')
    
    args = parser.parse_args()
    
    print("=== SCRAPING COMPLETO INCENTIVI ===\n")
    
    # Step 1: Ottieni la lista degli incentivi dal catalogo
    print("Step 1: Estrazione lista incentivi dal catalogo...")
    incentivi_base = scrape_catalogo_incentivi()
    
    if not incentivi_base:
        print("Nessun incentivo trovato nel catalogo. Uscita.")
        return
    
    # Limita il numero di incentivi se specificato (utile per testing)
    if args.max_incentivi:
        incentivi_base = incentivi_base[:args.max_incentivi]
        print(f"Limitando l'elaborazione ai primi {args.max_incentivi} incentivi per testing")
    
    print(f"Procedo con l'estrazione dettagli per {len(incentivi_base)} incentivi...\n")
    
    # Step 2: Estrai dettagli per ogni incentivo
    print("Step 2: Estrazione dettagli per ogni incentivo...")
    incentivi_dettagliati = []
    
    for i, incentivo in enumerate(incentivi_base, 1):
        print(f"[{i}/{len(incentivi_base)}] ", end="")
        dettagli = estrai_dettagli_incentivo(incentivo['link'], incentivo['titolo_base'])
        incentivi_dettagliati.append(dettagli)
        
        # Delay tra le richieste per evitare di sovraccaricare il server
        if i < len(incentivi_base):
            time.sleep(args.delay)
    
    print(f"\nStep 3: Salvataggio risultati...")
    
    # Step 3: Salva i risultati
    json_file, csv_file = salva_risultati(incentivi_dettagliati, args.output_dir)
    
    print(f"\n=== SCRAPING COMPLETATO ===")
    print(f"Incentivi elaborati: {len(incentivi_dettagliati)}")
    print(f"File JSON: {json_file}")
    print(f"File CSV: {csv_file}")

if __name__ == "__main__":
    main()
