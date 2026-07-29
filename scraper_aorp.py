import os
import sys
import re
import json
import cloudscraper
from bs4 import BeautifulSoup
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

def parse_number(text):
    """Extrai o primeiro número decimal de um texto, lidando com vírgulas e pontos."""
    # Procura um padrão numérico (ex: 78,50 ou 78.50 ou 1 200,50)
    match = re.search(r'[\d\s\.]+(?:[,\.]\d+)?', text)
    if not match:
        return None
    
    num_str = match.group(0).replace(" ", "").strip()
    if not num_str:
        return None
        
    # Se tiver vírgula e ponto, assume ponto como milhar e vírgula como decimal
    if "," in num_str and "." in num_str:
        num_str = num_str.replace(".", "").replace(",", ".")
    elif "," in num_str:
        num_str = num_str.replace(",", ".")
        
    try:
        return float(num_str)
    except ValueError:
        return None

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
    
    # 1. Tentar encontrar a tabela
    data_cotacao = None
    ouro_fino = None
    prata_fina = None

    table = soup.find("table")
    if table:
        rows = table.find_all("tr")
        for row in rows:
            cols = [ele.text.strip() for ele in row.find_all(["td", "th"])]
            # Procura linhas que tenham pelo menos 3 colunas e que contenham números
            if len(cols) >= 3:
                val1 = parse_number(cols[1])
                val2 = parse_number(cols[2])
                
                if val1 is not None and val2 is not None:
                    data_cotacao = cols[0].strip()
                    ouro_fino = val1
                    prata_fina = val2
                    print(f"ℹ️ Valores encontrados na tabela: Data={data_cotacao}, Ouro={ouro_fino}, Prata={prata_fina}")
                    break

    # 2. Fallback: Procura global no texto da página caso a estrutura HTML seja diferente
    if ouro_fino is None or prata_fina is None:
        print("⚠️ Tabela padrão não parseada. Tentando busca por texto geral...")
        text_lines = [line.strip() for line in soup.get_text().split("\n") if line.strip()]
        
        # Procura por linhas que tenham data e valores
        for i, line in enumerate(text_lines):
            # Procura datas tipo DD/MM/AAAA ou DD-MM-AAAA ou DD.MM.AAAA
            if re.search(r'\d{2}[/.-]\d{2}[/.-]\d{4}', line):
                data_cotacao = line
                # Tenta extrair os números das linhas seguintes
                numbers = []
                for j in range(i, min(i + 10, len(text_lines))):
                    num = parse_number(text_lines[j])
                    if num is not None and num > 0:
                        numbers.append(num)
                
                if len(numbers) >= 2:
                    ouro_fino = numbers[0]
                    prata_fina = numbers[1]
                    break

    if ouro_fino is None or prata_fina is None:
        raise Exception("Não foi possível extrair os valores numéricos do Ouro e Prata da página.")
        
    if not data_cotacao:
        data_cotacao = datetime.now().strftime("%d/%m/%Y")

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
    
    # Formata a data para ser usada como ID do documento
    doc_id = re.sub(r'[^0-9\-]', '-', quote_data["data_cotacao"].replace("/", "-").replace(".", "-"))
    doc_ref = db.collection("cotacoes_diarias").document(doc_id)
    
    doc = doc_ref.get()
    if doc.exists:
        print(f"ℹ️ A cotação para {doc_id} já existe na base de dados.")
    else:
        doc_ref.set(quote_data)
        print(f"✅ Nova cotação registada com sucesso! Documento ID: {doc_id}")
        
    # Guarda também como última cotação conhecida
    db.collection("configuracoes").document("ultima_cotacao").set(quote_data)

if __name__ == "__main__":
    try:
        data = fetch_aorp_quotes()
        update_firebase(data)
    except Exception as e:
        print(f"❌ Erro ao executar o scraping: {str(e)}")
        sys.exit(1)
