import requests
import json
import time
import csv
from datetime import datetime
from bs4 import BeautifulSoup

# Credenziali di accesso
USERNAME = "mic.monaco78@icloud.com"
PASSWORD = "123456789"

# Headers base
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

BASE_URL = "https://www.obiettivoeuropa.com"
LOGIN_URL = "https://www.obiettivoeuropa.com/account/login/"

def effettua_login():
    """Effettua il login e restituisce la sessione autenticata"""
    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    
    print("Effettuo il login...")
    
    # Prima richiesta per ottenere il token CSRF
    login_page = session.get(LOGIN_URL)
    if login_page.status_code != 200:
        raise Exception(f"Impossibile accedere alla pagina di login: {login_page.status_code}")
    
    soup = BeautifulSoup(login_page.text, "html.parser")
    csrf_token = soup.find("input", {"name": "csrfmiddlewaretoken"})
    if not csrf_token:
        raise Exception("Token CSRF non trovato nella pagina di login")
    
    csrf_value = csrf_token.get("value")
    
    # Dati per il login
    login_data = {
        "username": USERNAME,
        "password": PASSWORD,
        "csrfmiddlewaretoken": csrf_value
    }
    
    # Effettua il login
    login_response = session.post(LOGIN_URL, data=login_data, headers={
        "Referer": LOGIN_URL,
        "X-CSRFToken": csrf_value
    })
    
    # Verifica se il login è riuscito
    if login_response.status_code == 200:
        # Controlla se siamo stati reindirizzati o se c'è un messaggio di successo
        if "dashboard" in login_response.url or "bandi" in login_response.url:
            print("Login effettuato con successo!")
            return session
        else:
            # Controlla se c'è un messaggio di errore nella pagina
            soup = BeautifulSoup(login_response.text, "html.parser")
            error_msg = soup.find("div", class_="alert-danger") or soup.find("div", class_="error")
            if error_msg:
                raise Exception(f"Errore di login: {error_msg.get_text(strip=True)}")
            else:
                print("Login completato - verifica manuale dello stato")
                return session
    else:
        raise Exception(f"Errore durante il login: {login_response.status_code}")

def salva_csv(bandi, timestamp):
    """Salva i dati in formato CSV"""
    filename = f"bandi_obiettivoeuropa_dettaglio_{timestamp}.csv"
    
    with open(filename, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["id", "titolo", "scadenza", "url", "titolo_pagina", "testo_completo"]
        
        # Aggiungi dinamicamente i nomi delle sezioni
        sezioni_names = set()
        for bando in bandi:
            if "dettaglio" in bando and "sezioni" in bando["dettaglio"]:
                sezioni_names.update(bando["dettaglio"]["sezioni"].keys())
        
        fieldnames.extend(sorted(sezioni_names))
        
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for bando in bandi:
            row = {
                "id": bando.get("id"),
                "titolo": bando.get("titolo"),
                "scadenza": bando.get("scadenza"),
                "url": BASE_URL + bando.get("url", "") if bando.get("url") else ""
            }
            
            if "dettaglio" in bando:
                dettaglio = bando["dettaglio"]
                row["titolo_pagina"] = dettaglio.get("titolo_pagina", "")
                row["testo_completo"] = dettaglio.get("testo_completo", "")
                
                # Aggiungi le sezioni
                if "sezioni" in dettaglio:
                    for sezione_name, sezione_content in dettaglio["sezioni"].items():
                        if isinstance(sezione_content, list):
                            # Per i link, crea una stringa con URL
                            row[sezione_name] = "; ".join([f"{link['label']}: {link['url']}" for link in sezione_content])
                        else:
                            row[sezione_name] = sezione_content
            
            writer.writerow(row)
    
    print(f"File CSV salvato: {filename}")
    return filename

# Crea timestamp per i file
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

# Effettua il login
try:
    session = effettua_login()
except Exception as e:
    print(f"Errore durante il login: {e}")
    exit(1)

# Carica i bandi già estratti dall'API
with open("bandi_obiettivoeuropa_api.json", "r", encoding="utf-8") as f:
    bandi = json.load(f)

def estrai_dettagli(html):
    soup = BeautifulSoup(html, "html.parser")
    dettagli = {}
    
    # Titolo
    titolo = soup.find("h1")
    if titolo:
        dettagli["titolo_pagina"] = titolo.get_text(strip=True)
    # Tutto il testo delle sezioni principali (esempio: finalità, requisiti, ecc)
    sezioni = {}
    for h2 in soup.find_all("h2"):
        titolo_sezione = h2.get_text(strip=True)
        # Prendi tutto il testo fino al prossimo h2/h1
        contenuto = []
        raw_html = []
        for sib in h2.find_next_siblings():
            if sib.name in ["h1", "h2"]:
                break
            contenuto.append(sib.get_text(" ", strip=True))
            raw_html.append(str(sib))
        # Se la sezione è 'Link e Documenti' (case-insensitive), estrai i link
        if "link e documenti" in titolo_sezione.lower():
            soup_sezione = BeautifulSoup(" ".join(raw_html), "html.parser")
            links = []
            for a in soup_sezione.find_all("a"):
                label = a.get_text(strip=True)
                url = a.get("href")
                # Completa url relativi
                if url and url.startswith("/"):
                    url = BASE_URL + url
                links.append({"label": label, "url": url})
            sezioni[titolo_sezione] = links
        else:
            sezioni[titolo_sezione] = "\n".join(contenuto)
    if sezioni:
        dettagli["sezioni"] = sezioni
    # (Opzionale) Prendi tutto il testo visibile della pagina
    dettagli["testo_completo"] = soup.get_text("\n", strip=True)
    return dettagli

for i, bando in enumerate(bandi):
    url = bando.get("url")
    if not url:
        continue
    full_url = BASE_URL + url
    print(f"[{i+1}/{len(bandi)}] Scarico dettaglio: {full_url}")
    try:
        resp = session.get(full_url)
        if resp.status_code != 200:
            print(f"  Errore HTTP {resp.status_code}")
            continue
        dettagli = estrai_dettagli(resp.text)
        bando["dettaglio"] = dettagli
    except Exception as e:
        print(f"  Errore: {e}")
    time.sleep(0.5)  # Rispetta il server

# Salva il file JSON con timestamp
json_filename = f"bandi_obiettivoeuropa_api_dettaglio_{timestamp}.json"
with open(json_filename, "w", encoding="utf-8") as f:
    json.dump(bandi, f, ensure_ascii=False, indent=2)

print(f"Salvataggio JSON completato: {json_filename}")

# Salva anche il file CSV
csv_filename = salva_csv(bandi, timestamp)
print(f"Salvataggio CSV completato: {csv_filename}")
