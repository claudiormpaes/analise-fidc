"""Download e processamento da Composição e Diversificação de Aplicações (CDA)
de FIDCs a partir do Portal de Dados Abertos da CVM.

Fonte: dados.cvm.gov.br/dados/FI/DOC/CDA/DADOS/cda_fi_AAAAMM.zip
Arquivo de interesse: cda_fie_AAAAMM.csv (Extrato Informacional — mais completo)

Resultado: fidc_carteira.parquet — posições por CNPJ × competência × tipo de ativo
"""
from __future__ import annotations

import csv
import io
import re
import zipfile

import pandas as pd
import requests

import config

_FIDC_TIPOS = {"CLASSES - FIDC", "FIDC"}
_COLUNAS = [
    "TP_FUNDO_CLASSE", "CNPJ_FUNDO_CLASSE", "DT_COMPTC",
    "TP_APLIC", "TP_ATIVO", "VL_MERC_POS_FINAL", "VL_PATRIM_LIQ",
]


def _listar_meses() -> list[str]:
    """Retorna lista de meses disponíveis (AAAAMM) no portal CVM."""
    resp = requests.get(config.CDA_URL, headers=config.HTTP_HEADERS, timeout=30)
    resp.raise_for_status()
    meses = sorted(re.findall(r"cda_fi_(\d{6})\.zip", resp.text))
    return meses[-config.CDA_MESES:]


def _processar_zip(mes: str) -> pd.DataFrame:
    """Baixa cda_fi_AAAAMM.zip, filtra FIDCs e devolve tabela agregada."""
    url = f"{config.CDA_URL}/cda_fi_{mes}.zip"
    resp = requests.get(url, headers=config.HTTP_HEADERS, timeout=180)
    resp.raise_for_status()

    nome_fie = f"cda_fie_{mes}.csv"
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        if nome_fie not in z.namelist():
            return pd.DataFrame()
        with z.open(nome_fie) as f:
            df = pd.read_csv(
                f, sep=";", encoding="latin-1", dtype=str,
                quoting=csv.QUOTE_NONE,
                usecols=[c for c in _COLUNAS if True],
            )

    fidc = df[df["TP_FUNDO_CLASSE"].isin(_FIDC_TIPOS)].copy()
    if fidc.empty:
        return pd.DataFrame()

    for col in ("VL_MERC_POS_FINAL", "VL_PATRIM_LIQ"):
        fidc[col] = pd.to_numeric(
            fidc[col].str.replace(",", "."), errors="coerce")

    agg = (
        fidc.groupby(["CNPJ_FUNDO_CLASSE", "DT_COMPTC", "TP_APLIC", "TP_ATIVO"],
                     dropna=False)
        .agg(
            vl_posicao=("VL_MERC_POS_FINAL", "sum"),
            vl_pl_cda=("VL_PATRIM_LIQ", "first"),
        )
        .reset_index()
        .rename(columns={
            "CNPJ_FUNDO_CLASSE": "cnpj",
            "DT_COMPTC": "dt_comptc",
            "TP_APLIC": "tp_aplic",
            "TP_ATIVO": "tp_ativo",
        })
    )
    agg["competencia"] = pd.to_datetime(agg["dt_comptc"]).dt.to_period("M").astype(str)
    return agg


def sincronizar(*, verbose: bool = True) -> None:
    """Baixa e consolida os últimos meses de CDA de FIDCs."""
    config.ensure_dirs()

    try:
        meses = _listar_meses()
    except Exception as exc:
        print(f"  [aviso] CDA: não foi possível listar meses — {exc}")
        return

    if verbose:
        print(f"CDA carteira: processando {len(meses)} meses "
              f"({meses[0]} a {meses[-1]})...")

    # Carrega parquet existente para incrementar (não reprocessar tudo)
    existing = pd.DataFrame()
    comp_existentes: set[str] = set()
    if config.CARTEIRA.exists():
        existing = pd.read_parquet(config.CARTEIRA)
        comp_existentes = set(existing["competencia"].unique())

    partes = [existing] if not existing.empty else []
    novos = 0
    for mes in meses:
        comp = f"{mes[:4]}-{mes[4:]}"  # AAAAMM → AAAA-MM
        if comp in comp_existentes:
            continue  # já processado
        try:
            df = _processar_zip(mes)
            if not df.empty:
                partes.append(df)
                novos += 1
                if verbose:
                    print(f"  [ok ] CDA {mes}: {len(df):,} linhas")
        except Exception as exc:
            print(f"  [erro] CDA {mes}: {exc}")

    if partes:
        resultado = pd.concat(partes, ignore_index=True)
        resultado = resultado.drop_duplicates(
            subset=["cnpj", "dt_comptc", "tp_aplic", "tp_ativo"], keep="last")
        resultado.to_parquet(config.CARTEIRA, index=False)
        if verbose:
            print(f"CDA consolidado: {len(resultado):,} linhas | "
                  f"{novos} mês(es) novo(s) — {config.CARTEIRA.name}")
    elif verbose:
        print("CDA: nenhum dado novo.")


if __name__ == "__main__":
    sincronizar()
