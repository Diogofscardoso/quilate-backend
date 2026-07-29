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

    # Tenta encontrar a tabela principal
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cols = [ele.text.strip() for ele in row.find_all(["td", "th"])]
            
            # Precisamos de 3 colunas: Data, Ouro, Prata
            if len(cols) >= 3:
                # Exemplo cols: ["29 · 07 · 2026", "117.563", "1757.76"]
                col_data = cols[0]
                col_ouro = cols[1]
                col_prata = cols[2]
                
                # Ignorar cabeçalho caso contenha "DATA" ou "OURO"
                if "DATA" in col_data.upper() or "OURO" in col_ouro.upper():
                    continue

                try:
                    # Limpeza das strings
                    ouro_val = float(col_ouro.replace(",", ".").replace(" ", "").strip())
                    prata_val = float(col_prata.replace(",", ".").replace(" ", "").strip())
                    
                    # Normaliza a data (ex: "29 · 07 · 2026" -> "29/07/2026")
                    data_clean = re.sub(r'\s*[\·\.\-]\s*', '/', col_data.strip())
                    
                    ouro_fino = ouro_val
                    prata_fina = prata_val
                    data_cotacao = data_clean
                    print(f"✅ Sucesso ao extrair: Data={data_cotacao}, Ouro={ouro_fino}, Prata={prata_fina}")
                    break
                except ValueError:
                    continue
        if ouro_fino is not None:
            break

    # Fallback se a tabela não tiver a tag <table>
    if ouro_fino is None or prata_fina is None:
        full_text = soup.get_text()
        # Procura padrões de 3 números na página onde o 2º tem decimais (Ouro) e o 3º é > 1000 (Prata)
        matches = re.findall(r'(\d{2}\s*[\·\.\-/]\s*\d{2}\s*[\·\.\-/]\s*\d{4})\s+([\d\.]+)\s+([\d\.]+)', full_text)
        if matches:
            d, o, p = matches[0]
            data_cotacao = re.sub(r'\s*[\·\.\-]\s*', '/', d.strip())
            ouro_fino = float(o)
            prata_fina = float(p)

    if ouro_fino is None or prata_fina is None:
        raise Exception("Não foi possível extrair os valores do Ouro e Prata da página.")

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
    
    # ID do documento limpo ex: "29-07-2026"
    doc_id = quote_data["data_cotacao"].replace("/", "-")
    doc_ref = db.collection("cotacoes_diarias").document(doc_id)
    
    doc_ref.set(quote_data)
    print(f"✅ Nova cotação registada no Firebase com sucesso! ID: {doc_id}")
    db.collection("configuracoes").document("ultima_cotacao").set(quote_data)

if __name__ == "__main__":
    try:
        data = fetch_aorp_quotes()
        update_firebase(data)
    except Exception as e:
        print(f"❌ Erro ao executar o scraping: {str(e)}")
        sys.exit(1)
