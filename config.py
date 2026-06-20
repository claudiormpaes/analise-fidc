"""Configurações centrais do projeto de análise de FIDCs.

Todos os caminhos são relativos à raiz do projeto, então o projeto pode ser
movido/copiado sem quebrar (importante por estar dentro do OneDrive).
"""
from __future__ import annotations

from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Raiz do projeto (pasta onde este arquivo está)
ROOT = Path(__file__).resolve().parent

# Estrutura de dados
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"            # ZIPs originais da CVM
PROCESSED_DIR = DATA_DIR / "processed"
PARTS_DIR = PROCESSED_DIR / "parts"            # parquet por ZIP (fato fundo)
PARTS_COTAS_DIR = PROCESSED_DIR / "parts_cotas"  # parquet por ZIP (fato cotas)
CONSOLIDADO = PROCESSED_DIR / "fidc_consolidado.parquet"        # fato fundo-mês
CONSOLIDADO_COTAS = PROCESSED_DIR / "fidc_cotas.parquet"        # fato série/cota-mês
CDI_MENSAL = PROCESSED_DIR / "cdi_mensal.parquet"              # benchmark CDI (BACEN SGS)
IPCA_MENSAL = PROCESSED_DIR / "ipca_mensal.parquet"            # IPCA mensal (BACEN SGS 433)
SELIC_MENSAL = PROCESSED_DIR / "selic_mensal.parquet"          # SELIC mensal (BACEN SGS 4189)
CARTEIRA = PROCESSED_DIR / "fidc_carteira.parquet"             # CDA: composição de carteira
MANIFEST = RAW_DIR / "manifest.json"  # controle de download/processamento

# --- Fonte de dados: Portal de Dados Abertos da CVM ---
# Informe Mensal de FIDC (Anexo A da ICVM 489/502, atualizado pela Res. CVM 175)
BASE_URL = "https://dados.cvm.gov.br/dados/FIDC/DOC/INF_MENSAL/DADOS"
HIST_URL = f"{BASE_URL}/HIST"

# Composição e Diversificação de Aplicações (CDA) — todos os fundos, filtrar FIDC
CDA_URL = "https://dados.cvm.gov.br/dados/FI/DOC/CDA/DADOS"
CDA_HIST_URL = f"{CDA_URL}/HIST"

# Cadastro de fundos e registro de fundo/classe da CVM
CAD_URL = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/cad_fi.csv"
REG_URL = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip"

# Primeiro ano disponível no histórico anual da CVM
PRIMEIRO_ANO_HIST = 2013

# Arquivos mensais (DADOS/) dos últimos N meses são reprocessados pela CVM
# semanalmente (reenvios). Mantemos esses sempre atualizados no download diário.
JANELA_REFRESH_MESES = 13

# Meses de CDA a processar (últimos N meses mensais)
CDA_MESES = 30

# Encoding e separador dos CSVs da CVM
CSV_ENCODING = "latin-1"
CSV_SEP = ";"

# User-Agent para as requisições (alguns servidores recusam sem header)
HTTP_HEADERS = {"User-Agent": "analise-fidc/1.0 (+pipeline CVM dados abertos)"}

# --- Cliente HTTP resiliente ---
# O Portal de Dados Abertos da CVM (dados.cvm.gov.br) é instável: o ETL diário
# já falhou logo na primeira requisição com ConnectionError
# ("[Errno 101] Network is unreachable"). Usamos uma Session com retry e
# backoff exponencial para que oscilações momentâneas da CVM/BACEN não
# derrubem a pipeline inteira. Use config.SESSION.get/head no lugar de
# requests.get/head em todo o projeto.
HTTP_MAX_RETRIES = 5
HTTP_BACKOFF_FACTOR = 1.5  # espera 0s, 1.5s, 3s, 6s, 12s entre as tentativas


def _build_session() -> requests.Session:
    """Session com retry em erros de conexão, timeout de leitura e 5xx/429."""
    retry = Retry(
        total=HTTP_MAX_RETRIES,
        connect=HTTP_MAX_RETRIES,
        read=HTTP_MAX_RETRIES,
        status=HTTP_MAX_RETRIES,
        backoff_factor=HTTP_BACKOFF_FACTOR,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,  # deixa o raise_for_status() do caller decidir
    )
    session = requests.Session()
    session.headers.update(HTTP_HEADERS)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = _build_session()


def ensure_dirs() -> None:
    """Cria a árvore de diretórios de dados se ainda não existir."""
    for d in (RAW_DIR, PARTS_DIR, PARTS_COTAS_DIR, PROCESSED_DIR):
        d.mkdir(parents=True, exist_ok=True)
