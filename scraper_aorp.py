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
    
    ouro_fino = None
    prata_fina = None
    data_cotacao = None

    # 1. Procurar em todas as tabelas
    tables = soup.find_all("table")
    for table in tables:
        for row in table.find_all("tr"):
            cols = [ele.text.strip() for ele in row.find_all(["td", "th"])]
            nums = []
            for col in cols:
                # Procura valores decimais no texto da coluna
                found = re.findall(r'\d+(?:[,\.]\d+)?', col)
                for f in found:
                    try:
                        val = float(f.replace(",", "."))
                        if val > 0:
                            nums.append(val)
                    except ValueError:
                        pass
            if len(nums) >= 2:
                ouro_fino = nums[0]
                prata_fina = nums[1]
                data_cotacao = cols[0] if cols else datetime.now().strftime("%d/%m/%Y")
                print(f"✅ Cotação encontrada na tabela: Ouro={ouro_fino}, Prata={prata_fina}")
                break
        if ouro_fino is not None:
            break

    # 2. Procurar em tags de texto (div, p, span, td) com regex amplo
    if ouro_fino is None or prata_fina is None:
        full_text = soup.get_text()
        print("ℹ️ Diagnóstico - Amostra do texto da página:")
        print(full_text[:500].replace('\n', ' '))
        
        # Procurar padrões de números com vírgula ou ponto seguidos de € ou isolados
        matches = re.findall(r'(\d{2,4}(?:[,\.]\d{1,2})?)', full_text)
        valid_nums = []
        for m in matches:
            try:
                val = float(m.replace(",", "."))
                # Filtra números razoáveis para cotações de Ouro/Prata
                if 10 <= val <= 5000:
                    valid_nums.append(val)
            except ValueError:
                pass

        if len(valid_nums) >= 2:
            ouro_fino = valid_nums[0]
            prata_fina = valid_nums[1]
            data_cotacao = datetime.now().strftime("%d/%m/%Y")
            print(f"✅ Cotação extraída do texto: Ouro={ouro_fino}, Prata={prata_fina}")

    if ouro_fino is None or prata_fina is None:
        raise Exception("Não foi possível extrair os valores do Ouro e Prata. Verifica os logs de diagnóstico.")

    return {
        "data_cotacao": str(data_cotacao),
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
    
    doc_id = datetime.now().strftime("%Y-%m-%d")
    doc_ref = db.collection("cotacoes_diarias").document(doc_id)
    
    doc_ref.set(quote_data)
    print(f"✅ Nova cotação registada no Firebase! ID: {doc_id}")
    db.collection("configuracoes").document("ultima_cotacao").set(quote_data)

if __name__ == "__main__":
    try:
        data = fetch_aorp_quotes()
        update_firebase(data)
    except Exception as e:
        print(f"❌ Erro ao executar o scraping: {str(e)}")
        sys.exit(1)
