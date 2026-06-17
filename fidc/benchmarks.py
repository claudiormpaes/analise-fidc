"""Benchmarks e cadastros externos: CDI, IPCA, SELIC (BACEN/SGS) e
mapeamento CNPJ→gestor/metadados (CVM registro_fundo_classe + cad_fi).
"""
from __future__ import annotations

import io
import re
import zipfile

import pandas as pd
import requests

import config

# --- BACEN SGS ---
SGS_CDI_MENSAL = 4391    # CDI acumulado no mês (% a.m.)
SGS_IPCA_MENSAL = 433    # IPCA variação mensal (%)
SGS_SELIC_MENSAL = 4189  # SELIC acumulada no mês (% a.a. — convertida para a.m. em fetch_selic)

_SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{}/dados?formato=json"

# Tipos de fundo no cad_fi.csv
_CAD_TIPOS_FIDC = {"FIDC", "FIC FIDC", "FIC-FIDC"}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _fetch_sgs(serie: int, col: str, parquet_path, *, verbose: bool) -> pd.DataFrame:
    resp = requests.get(_SGS_URL.format(serie), headers=config.HTTP_HEADERS, timeout=60)
    resp.raise_for_status()
    d = pd.DataFrame(resp.json())
    d["data"] = pd.to_datetime(d["data"], format="%d/%m/%Y")
    d["competencia"] = d["data"].dt.to_period("M").astype(str)
    d[col] = pd.to_numeric(d["valor"], errors="coerce")
    out = d[["competencia", col]].dropna().reset_index(drop=True)
    out.to_parquet(parquet_path, index=False)
    if verbose:
        print(f"{col}: {len(out)} meses ({out['competencia'].min()} a {out['competencia'].max()}).")
    return out


def _fmt_cnpj(raw: str) -> str:
    """Formata CNPJ bruto (14 dígitos) para XX.XXX.XXX/XXXX-XX."""
    d = re.sub(r"\D", "", str(raw)).zfill(14)
    if len(d) < 14:
        return str(raw)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"


# --------------------------------------------------------------------------- #
# Benchmarks
# --------------------------------------------------------------------------- #
def fetch_cdi(*, verbose: bool = True) -> pd.DataFrame:
    """Baixa o CDI mensal (SGS 4391) e salva em cdi_mensal.parquet."""
    config.ensure_dirs()
    return _fetch_sgs(SGS_CDI_MENSAL, "cdi_mes", config.CDI_MENSAL, verbose=verbose)


def fetch_ipca(*, verbose: bool = True) -> pd.DataFrame:
    """Baixa o IPCA mensal (SGS 433) e salva em ipca_mensal.parquet."""
    config.ensure_dirs()
    return _fetch_sgs(SGS_IPCA_MENSAL, "ipca_mes", config.IPCA_MENSAL, verbose=verbose)


def fetch_selic(*, verbose: bool = True) -> pd.DataFrame:
    """Baixa a SELIC (SGS 4189, % a.a.), converte para % a.m. e salva em selic_mensal.parquet."""
    config.ensure_dirs()
    df = _fetch_sgs(SGS_SELIC_MENSAL, "selic_mes", config.SELIC_MENSAL, verbose=verbose)
    # SGS 4189 retorna taxa anualizada; converte para mensal equivalente
    df["selic_mes"] = ((1 + df["selic_mes"] / 100) ** (1 / 12) - 1) * 100
    df.to_parquet(config.SELIC_MENSAL, index=False)
    return df


# --------------------------------------------------------------------------- #
# Cadastro: CNPJ → gestor, classe_anbima, sit, taxa_adm
# --------------------------------------------------------------------------- #
def fetch_cadastro(*, verbose: bool = True) -> pd.DataFrame:
    """Mapeia CNPJs de fundos e classes FIDC a gestor e metadados.

    Usa dois arquivos da CVM:
    - registro_fundo_classe.zip → cobre as classes pós-Res. CVM 175 (CNPJ de classe)
    - cad_fi.csv → cobre fundos estilo antigo + fornece ANBIMA/taxas
    """
    try:
        # ------------------------------------------------------------------ #
        # 1. registro_fundo_classe.zip: classe CNPJ → gestor do fundo pai
        # ------------------------------------------------------------------ #
        resp = requests.get(config.REG_URL, headers=config.HTTP_HEADERS, timeout=120)
        resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            with z.open("registro_fundo.csv") as f:
                rf = pd.read_csv(
                    f, sep=";", dtype=str, encoding="latin-1",
                    usecols=["ID_Registro_Fundo", "CNPJ_Fundo", "Gestor",
                             "Tipo_Fundo", "Situacao"],
                )
            rf["cnpj"] = rf["CNPJ_Fundo"].apply(_fmt_cnpj)
            rf["gestor"] = rf["Gestor"].str.strip().str.title()
            # Mapa ID → gestor para resolver classes
            id_to_gestor = (rf.dropna(subset=["gestor"])
                            .set_index("ID_Registro_Fundo")["gestor"].to_dict())
            # Mapa ID → cnpj_fundo (para enriquecimento de metadados via cad_fi)
            id_to_cnpj_fundo = rf.set_index("ID_Registro_Fundo")["cnpj"].to_dict()

            with z.open("registro_classe.csv") as f:
                rc = pd.read_csv(
                    f, sep=";", dtype=str, encoding="latin-1",
                    usecols=["ID_Registro_Fundo", "CNPJ_Classe",
                             "Tipo_Classe", "Classificacao_Anbima", "Situacao"],
                )

        rc_fidc = rc[rc["Tipo_Classe"].str.contains("FIDC", case=False, na=False)].copy()
        rc_fidc["cnpj"] = rc_fidc["CNPJ_Classe"].apply(_fmt_cnpj)
        rc_fidc["gestor"] = rc_fidc["ID_Registro_Fundo"].map(id_to_gestor)
        rc_fidc["cnpj_fundo"] = rc_fidc["ID_Registro_Fundo"].map(id_to_cnpj_fundo)
        rc_fidc["classe_anbima"] = rc_fidc["Classificacao_Anbima"].str.strip().where(
            rc_fidc["Classificacao_Anbima"].notna())
        rc_fidc["sit"] = rc_fidc["Situacao"].str.strip()

        # Fundos FIDC diretos do registro (pre-Res.175)
        rf_fidc = rf[rf["Tipo_Fundo"].str.upper().str.contains("FIDC", na=False)].copy()
        rf_fidc["cnpj_fundo"] = rf_fidc["cnpj"]
        rf_fidc["sit"] = rf_fidc["Situacao"].str.strip()
        rf_fidc["classe_anbima"] = None

        # ------------------------------------------------------------------ #
        # 2. cad_fi.csv: ANBIMA, taxas, sit para fundos (pré-Res.175)
        # ------------------------------------------------------------------ #
        resp2 = requests.get(config.CAD_URL, headers=config.HTTP_HEADERS, timeout=60)
        resp2.raise_for_status()
        cad = pd.read_csv(
            io.StringIO(resp2.content.decode("latin-1")),
            sep=";", dtype=str,
            usecols=["TP_FUNDO", "CNPJ_FUNDO", "GESTOR", "CLASSE_ANBIMA",
                     "SIT", "TAXA_ADM", "TAXA_PERFM"],
        )
        cad = cad[cad["TP_FUNDO"].isin(_CAD_TIPOS_FIDC)].copy()
        cad["cnpj_fundo"] = cad["CNPJ_FUNDO"].apply(_fmt_cnpj)
        cad["gestor_cad"] = cad["GESTOR"].str.strip().str.title()
        cad["classe_anbima_cad"] = cad["CLASSE_ANBIMA"].str.strip()
        cad["taxa_adm"] = pd.to_numeric(
            cad["TAXA_ADM"].str.replace(",", "."), errors="coerce")
        cad["taxa_perfm"] = pd.to_numeric(
            cad["TAXA_PERFM"].str.replace(",", "."), errors="coerce")
        cad_meta = cad[["cnpj_fundo", "gestor_cad", "classe_anbima_cad",
                        "taxa_adm", "taxa_perfm"]].drop_duplicates("cnpj_fundo")

        # ------------------------------------------------------------------ #
        # 3. Montar DataFrame unificado
        # ------------------------------------------------------------------ #
        # Classes pós-Res.175
        classe_rows = (rc_fidc[["cnpj", "gestor", "cnpj_fundo", "classe_anbima", "sit"]]
                       .dropna(subset=["cnpj"]).copy())
        classe_rows = classe_rows.merge(cad_meta, on="cnpj_fundo", how="left")
        # Preenche classe_anbima com valor do cad quando registro não tem
        classe_rows["classe_anbima"] = (classe_rows["classe_anbima"]
                                        .combine_first(classe_rows["classe_anbima_cad"]))
        # Preenche gestor com cad quando registro não tem
        classe_rows["gestor"] = (classe_rows["gestor"]
                                 .combine_first(classe_rows["gestor_cad"]))

        # Fundos diretos (pre-Res.175): usa cad_fi como referência principal
        fundo_rows = (rf_fidc[["cnpj", "gestor", "cnpj_fundo", "sit"]]
                      .dropna(subset=["cnpj"]).copy())
        fundo_rows = fundo_rows.merge(cad_meta, on="cnpj_fundo", how="left")
        fundo_rows["gestor"] = fundo_rows["gestor"].combine_first(fundo_rows["gestor_cad"])
        fundo_rows["classe_anbima"] = fundo_rows["classe_anbima_cad"]

        cols_final = ["cnpj", "gestor", "classe_anbima", "taxa_adm", "taxa_perfm", "sit"]
        result = (pd.concat([fundo_rows[cols_final], classe_rows[cols_final]],
                            ignore_index=True)
                  .drop_duplicates(subset=["cnpj"], keep="last")
                  .reset_index(drop=True))

        if verbose:
            n_g = result["gestor"].notna().sum()
            n_a = result["classe_anbima"].notna().sum()
            print(f"Cadastro CVM: {len(result)} CNPJs | {n_g} com gestor | "
                  f"{n_a} com class. ANBIMA | "
                  f"({len(fundo_rows)} fundos + {len(classe_rows)} classes).")
        return result

    except Exception as exc:  # noqa: BLE001
        print(f"  [aviso] Cadastro CVM não atualizado: {exc}")
        return pd.DataFrame(columns=["cnpj", "gestor", "classe_anbima",
                                     "taxa_adm", "taxa_perfm", "sit"])


if __name__ == "__main__":
    fetch_cdi()
    fetch_ipca()
    fetch_selic()
