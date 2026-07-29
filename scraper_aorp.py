import os
import sys
import re
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

def fetch_aorp_quotes():
    # URL principal e fallback
    urls = [
        "https://www.aorp.pt/quotes",
        "https://www.aorp.pt/pt/quotes",
        "https://www.aorp.pt/"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache"
    }

    soup = None
    for url in urls:
        print(f"[{datetime.now().isoformat()}] Acedendo à AORP: {url}")
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code == 200:
                soup = BeautifulSoup(res.content, "html.parser")
                if soup.find("table") or "ouro" in res.text.lower():
                    break
        except Exception as e:
            print(f"Erro ao tentar {url}: {e}")

    if not soup:
        raise Exception("Não foi possível carregar o conteúdo da página da AORP.")

    # Tentativa 1: Procurar na tabela clássica
    table = soup.find("table")
    data_cotacao = None
    ouro_fino = None
    prata_fina = None

    if table:
        rows = table.find_all("tr")
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

    # Tentativa 2: Procura por padrões numéricos no texto caso a tabela mude de tags
    if ouro_fino is None:
        text = soup.get_text()
        # Procura datas tipo DD/MM/AAAA ou DD.MM.AAAA
        date_match = re.search(r'\b\d{2}[/.-]\d{2}[/.-]\d{4}\b', text)
        if date_match:
            data_cotacao = date_match.group(0)
        else:
            data_cotacao = datetime.now().strftime("%d/%m/%Y")

        # Procura valores em €/g
        matches = re.findall(r'(\d+[\.,]\d+)\s*€', text)
        if len(matches) >= 2:
            try:
                ouro_fino = float(matches[0].replace(",", "."))
                prata_fina = float(matches[1].replace(",", "."))
            except ValueError:
                pass

    if ouro_fino is None or prata_fina is None:
        raise Exception("Tabela de cotações não encontrada na página da AORP.")
        
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
