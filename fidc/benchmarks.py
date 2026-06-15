"""Benchmarks de mercado — CDI mensal via API pública do Banco Central (SGS).

Série 4391 = "Taxa de juros - CDI acumulada no mês" (% a.m.).
Doc: https://dadosabertos.bcb.gov.br/  (SGS)
"""
from __future__ import annotations

import pandas as pd
import requests

import config

SGS_CDI_MENSAL = 4391
URL = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{SGS_CDI_MENSAL}/dados?formato=json"


def fetch_cdi(*, verbose: bool = True) -> pd.DataFrame:
    """Baixa o CDI mensal e salva em data/processed/cdi_mensal.parquet."""
    config.ensure_dirs()
    resp = requests.get(URL, headers=config.HTTP_HEADERS, timeout=60)
    resp.raise_for_status()
    d = pd.DataFrame(resp.json())
    d["data"] = pd.to_datetime(d["data"], format="%d/%m/%Y")
    d["competencia"] = d["data"].dt.to_period("M").astype(str)
    d["cdi_mes"] = pd.to_numeric(d["valor"], errors="coerce")
    out = d[["competencia", "cdi_mes"]].dropna().reset_index(drop=True)
    out.to_parquet(config.CDI_MENSAL, index=False)
    if verbose:
        print(f"CDI mensal: {len(out)} meses ({out['competencia'].min()} a "
              f"{out['competencia'].max()}).")
    return out


if __name__ == "__main__":
    fetch_cdi()
