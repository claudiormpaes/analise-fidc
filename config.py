"""Configurações centrais do projeto de análise de FIDCs.

Todos os caminhos são relativos à raiz do projeto, então o projeto pode ser
movido/copiado sem quebrar (importante por estar dentro do OneDrive).
"""
from __future__ import annotations

from pathlib import Path

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
MANIFEST = RAW_DIR / "manifest.json"  # controle de download/processamento

# --- Fonte de dados: Portal de Dados Abertos da CVM ---
# Informe Mensal de FIDC (Anexo A da ICVM 489/502, atualizado pela Res. CVM 175)
BASE_URL = "https://dados.cvm.gov.br/dados/FIDC/DOC/INF_MENSAL/DADOS"
HIST_URL = f"{BASE_URL}/HIST"

# Primeiro ano disponível no histórico anual da CVM
PRIMEIRO_ANO_HIST = 2013

# Arquivos mensais (DADOS/) dos últimos N meses são reprocessados pela CVM
# semanalmente (reenvios). Mantemos esses sempre atualizados no download diário.
JANELA_REFRESH_MESES = 13

# Encoding e separador dos CSVs da CVM
CSV_ENCODING = "latin-1"
CSV_SEP = ";"

# User-Agent para as requisições (alguns servidores recusam sem header)
HTTP_HEADERS = {"User-Agent": "analise-fidc/1.0 (+pipeline CVM dados abertos)"}


def ensure_dirs() -> None:
    """Cria a árvore de diretórios de dados se ainda não existir."""
    for d in (RAW_DIR, PARTS_DIR, PARTS_COTAS_DIR, PROCESSED_DIR):
        d.mkdir(parents=True, exist_ok=True)
