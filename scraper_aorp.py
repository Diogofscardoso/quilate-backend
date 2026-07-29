import os
import sys
import json
import cloudscraper
from bs4 import BeautifulSoup
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

def fetch_aorp_quotes():
    url = "https://www.aorp.pt/quotes"
    print(f"[{datetime.now().isoformat()}] Acedendo à AORP com cloudscraper: {url}")
    
    # Criar um scraper que emula um navegador real
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
    table = soup.find("table")
    
    if not table:
        raise Exception("Tabela de cotações não encontrada na página da AORP.")
        
    rows = table.find_all("tr")
    
    data_cotacao = None
    ouro_fino = None
    prata_fina = None
    
    for row in rows:
        cols = [ele.text.strip() for ele in row.find_all(["td", "th"])]
        if len(cols) >= 3:
            try:
                ouro_val = float(cols[1].replace(",", ".").replace("€", "").replace(" ", "").strip())
                prata_val = float(cols[2].replace(",", ".").replace("€", "").replace(" ", "").strip())
                data_str = cols[0].strip()
                
                data_cotacao = data_str
                ouro_fino = ouro_val
                prata_fina = prata_val
                break
            except ValueError:
                continue

    if ouro_fino is None or prata_fina is None:
        raise Exception("Não foi possível extrair os valores numéricos do Ouro e Prata.")
        
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
    
    doc_id = quote_data["data_cotacao"].replace("/", "-").replace(".", "-")
    doc_ref = db.collection("cotacoes_diarias").document(doc_id)
    
    doc = doc_ref.get()
    if doc.exists:
        print(f"ℹ️ A cotação para {doc_id} já existe na base de dados.")
    else:
        doc_ref.set(quote_data)
        print(f"✅ Nova cotação registada com sucesso! Documento ID: {doc_id}")
        db.collection("configuracoes").document("ultima_cotacao").set(quote_data)

if __name__ == "__main__":
    try:
        data = fetch_aorp_quotes()
        update_firebase(data)
    except Exception as e:
        print(f"❌ Erro ao executar o scraping: {str(e)}")
        sys.exit(1)
