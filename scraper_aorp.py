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
        
    # Converte o HTML para texto limpo e legível
    soup = BeautifulSoup(response.content, "html.parser")
    text_content = soup.get_text(separator=" ")
    
    data_cotacao = None
    ouro_fino = None
    prata_fina = None

    # 1. Procurar o padrão: DATA (dia, mês, ano) seguido de dois números decimais (Ouro e Prata)
    # Exemplo no texto: "29 · 07 · 2026 117.563 1757.76" ou "29/07/2026 117.563 1757.76"
    pattern = r'(\d{2}\s*[\·\.\-/]\s*\d{2}\s*[\·\.\-/]\s*\d{4})\s+([\d\.,]+)\s+([\d\.,]+)'
    match = re.search(pattern, text_content)
    
    if match:
        raw_date, raw_ouro, raw_prata = match.groups()
        data_cotacao = re.sub(r'\s*[\·\.\-]\s*', '/', raw_date.strip())
        ouro_fino = float(raw_ouro.replace(",", "."))
        prata_fina = float(raw_prata.replace(",", "."))
        print(f"✅ Encontrado via Padrão Principal: Data={data_cotacao}, Ouro={ouro_fino}, Prata={prata_fina}")
    else:
        # 2. Fallback: Se os números estiverem separados por mais espaços/tags HTML
        print("⚠️ Tentando extração por proximidade de blocos numéricos...")
        # Procura por datas com o separador ponto centrado ou barra
        dates = re.findall(r'\d{2}\s*[\·\.\-/]\s*\d{2}\s*[\·\.\-/]\s*\d{4}', text_content)
        # Procura por números decimais típicos das cotações
        numbers = re.findall(r'\b\d{2,4}[\.,]\d{2,3}\b', text_content)
        
        if dates and len(numbers) >= 2:
            data_cotacao = re.sub(r'\s*[\·\.\-]\s*', '/', dates[0].strip())
            ouro_fino = float(numbers[0].replace(",", "."))
            prata_fina = float(numbers[1].replace(",", "."))
            print(f"✅ Encontrado via Fallback: Data={data_cotacao}, Ouro={ouro_fino}, Prata={prata_fina}")

    if ouro_fino is None or prata_fina is None:
        raise Exception("Não foi possível extrair os valores do Ouro e Prata. Estrutura inesperada.")

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
