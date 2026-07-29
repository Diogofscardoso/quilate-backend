import os
import sys
import re
import json
import cloudscraper
from bs4 import BeautifulSoup
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

def fetch_aorp_quotes():
    url = "https://www.aorp.pt/quotes"
    print(f"[{datetime.now().isoformat()}] Acedendo à AORP: {url}")
    
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )
    
    response = scraper.get(url, timeout=20)
    
    if response.status_code != 200:
        raise Exception(f"Erro ao aceder à AORP. Status code: {response.status_code}")
        
    soup = BeautifulSoup(response.content, "html.parser")
    
    data_cotacao = None
    ouro_fino = None
    prata_fina = None

    # Extrai todas as células (td e th) do HTML
    elements = [re.sub(r'\s+', ' ', e.text.strip()) for e in soup.find_all(["td", "th", "p", "span", "div"]) if e.text.strip()]
    
    # Procura por uma célula que contenha a data no formato DD.MM.AAAA ou DD/MM/AAAA
    for i, elem in enumerate(elements):
        date_match = re.search(r'(\d{2}\s*[\·\.\-/]\s*\d{2}\s*[\·\.\-/]\s*\d{4})', elem)
        if date_match:
            # Encontrou a data! Os próximos números válidos nos elementos seguintes são o Ouro e a Prata
            raw_date = date_match.group(1)
            found_nums = []
            
            for j in range(i + 1, min(i + 15, len(elements))):
                # Procura por números decimais (ex: 117.563 ou 1757.76)
                num_match = re.search(r'(\d{2,4}[\.,]\d{1,3})', elements[j])
                if num_match:
                    try:
                        val = float(num_match.group(1).replace(",", "."))
                        if val > 0:
                            found_nums.append(val)
                    except ValueError:
                        pass
                if len(found_nums) == 2:
                    break
            
            if len(found_nums) >= 2:
                data_cotacao = re.sub(r'\s*[\·\.\-]\s*', '/', raw_date.strip())
                ouro_fino = found_nums[0]
                prata_fina = found_nums[1]
                print(f"✅ Sucesso total: Data={data_cotacao}, Ouro={ouro_fino}, Prata={prata_fina}")
                break

    if ouro_fino is None or prata_fina is None:
        raise Exception("Não foi possível localizar os valores da cotação no HTML.")

    return {
        "data_cotacao": data_cotacao,
        "ouro_fino_eur_g": ouro_fino,
        "prata_fina_eur_kg": prata_fina,
        "atualizado_em": firestore.SERVER_TIMESTAMP
    }

def update_firebase(quote_data):
    cred_json = os.environ.get("FIREBASE_CREDENTIALS")
    if not cred_json:
        print("AVISO: FIREBASE_CREDENTIALS não configurado.")
        return

    cred_dict = json.loads(cred_json)
    cred = credentials.Certificate(cred_dict)
    
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
        
    db = firestore.client()
    
    doc_id = quote_data["data_cotacao"].replace("/", "-")
    doc_ref = db.collection("cotacoes_diarias").document(doc_id)
    
    doc_ref.set(quote_data)
    print(f"✅ Nova cotação registada no Firebase com sucesso! Documento ID: {doc_id}")
    db.collection("configuracoes").document("ultima_cotacao").set(quote_data)

if __name__ == "__main__":
    try:
        data = fetch_aorp_quotes()
        update_firebase(data)
    except Exception as e:
        print(f"❌ Erro ao executar o scraping: {str(e)}")
        sys.exit(1)
