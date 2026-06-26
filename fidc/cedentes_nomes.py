"""Enriquece os maiores cedentes (CNPJ) com razão social via BrasilAPI.

A base da CVM identifica os cedentes apenas por CPF/CNPJ, sem nome. Aqui
buscamos a razão social (e UF/município/CNAE) dos maiores cedentes na
BrasilAPI (https://brasilapi.com.br/api/cnpj/v1/<cnpj>), gravando um cache
incremental em `cedentes_nomes.parquet`. Só CNPJ é consultado — CPF (pessoa
física) é mantido anônimo no painel.

A BrasilAPI tem rate limit agressivo (HTTP 429 em rajadas). Por isso:
  - usamos uma sessão própria (sem o retry global do config, que estoura o
    tempo no 429), com backoff que respeita o header Retry-After;
  - limitamos o nº de CNPJs novos por execução (MAX_POR_RUN). O cache é
    incremental: cada rodada diária do ETL preenche mais um lote, então em
    poucos dias os maiores cedentes ficam todos nomeados.

Best-effort: se a API cair, o painel cai para o CNPJ formatado.
"""
from __future__ import annotations

import time

import pandas as pd
import requests

import config

# Universo-alvo (maiores cedentes) e quanto buscar de NOVO por execução.
TOP_N = 800           # tamanho do ranking de cedentes a nomear (acumulado)
MAX_POR_RUN = 150     # nº de CNPJs novos consultados por execução (bound de tempo)
JANELA_MESES = 12     # meses recentes p/ rankear exposição
PAUSA_S = 1.5         # pausa entre chamadas bem-sucedidas (respeita rate limit)
BACKOFF_429_S = 20    # espera ao tomar 429 sem Retry-After
MAX_TENT_429 = 3      # tentativas por CNPJ ao tomar 429
COLS = ["doc", "razao_social", "nome_fantasia", "uf", "municipio",
        "cnae_principal", "situacao"]


def _sessao() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "analise-fidc/1.0 (cedentes)"})
    return s


def _alvos(ced: pd.DataFrame) -> list[str]:
    """CNPJs a nomear: união dos maiores por exposição (janela recente) e dos
    mais presentes (nº de fundos distintos no histórico)."""
    cnpj = ced[ced["doc_tipo"] == "CNPJ"]
    if cnpj.empty:
        return []
    comps = sorted(cnpj["competencia"].dropna().unique())
    rec = cnpj[cnpj["competencia"].isin(set(comps[-JANELA_MESES:]))]
    por_exposicao = (rec.groupby("doc")["vl_estimado"].sum()
                     .sort_values(ascending=False).head(TOP_N).index)
    por_presenca = (cnpj.groupby("doc")["cnpj"].nunique()
                    .sort_values(ascending=False).head(TOP_N).index)
    return list(dict.fromkeys(list(por_exposicao) + list(por_presenca)))


def _consultar(sess: requests.Session, cnpj14: str) -> dict | None:
    """Consulta um CNPJ na BrasilAPI, respeitando 429/Retry-After."""
    url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj14}"
    for _ in range(MAX_TENT_429):
        try:
            r = sess.get(url, timeout=30)
        except Exception:  # noqa: BLE001
            return None
        if r.status_code == 429:
            espera = int(r.headers.get("Retry-After", BACKOFF_429_S) or BACKOFF_429_S)
            time.sleep(min(espera, 60))
            continue
        if r.status_code != 200:
            return None
        try:
            d = r.json()
        except Exception:  # noqa: BLE001
            return None
        return {
            "doc": cnpj14,
            "razao_social": d.get("razao_social"),
            "nome_fantasia": d.get("nome_fantasia") or None,
            "uf": d.get("uf"),
            "municipio": d.get("municipio"),
            "cnae_principal": d.get("cnae_fiscal_descricao"),
            "situacao": d.get("descricao_situacao_cadastral"),
        }
    return None  # esgotou tentativas de 429


def enriquecer(*, verbose: bool = True) -> pd.DataFrame:
    """Atualiza o cache de razões sociais dos maiores cedentes. Incremental,
    limitado a MAX_POR_RUN novos CNPJs por execução."""
    if not config.CONSOLIDADO_CEDENTES.exists():
        if verbose:
            print("  [aviso] base de cedentes ausente — pulando enriquecimento de nomes")
        return pd.DataFrame(columns=COLS)
    ced = pd.read_parquet(config.CONSOLIDADO_CEDENTES)

    cache = (pd.read_parquet(config.CEDENTES_NOMES)
             if config.CEDENTES_NOMES.exists() else pd.DataFrame(columns=COLS))
    ja_tem = set(cache["doc"].astype(str)) if not cache.empty else set()

    alvos = [c for c in _alvos(ced) if c not in ja_tem][:MAX_POR_RUN]
    if verbose:
        print(f"  Enriquecendo nomes de cedentes: {len(alvos)} CNPJ(s) novos "
              f"(cap {MAX_POR_RUN}/run; cache atual: {len(ja_tem)})")
    if not alvos:
        if not config.CEDENTES_NOMES.exists():
            cache.to_parquet(config.CEDENTES_NOMES, index=False)
        return cache

    sess = _sessao()
    novos, falhas = [], 0

    def _flush():
        if not novos:
            return cache
        atual = (pd.concat([cache, pd.DataFrame(novos)], ignore_index=True)
                 .drop_duplicates(subset=["doc"], keep="last").reset_index(drop=True))
        atual.to_parquet(config.CEDENTES_NOMES, index=False)
        return atual

    for i, cnpj14 in enumerate(alvos, 1):
        rec = _consultar(sess, cnpj14)
        if rec:
            novos.append(rec)
        else:
            falhas += 1
        if i % 25 == 0:
            cache = _flush()  # persiste progresso (resiliente a interrupção)
            if verbose:
                print(f"    {i}/{len(alvos)} (ok {len(novos)}, falhas {falhas})...")
        time.sleep(PAUSA_S)

    cache = _flush()
    if not config.CEDENTES_NOMES.exists():
        cache.to_parquet(config.CEDENTES_NOMES, index=False)
    if verbose:
        print(f"  [ok ] {len(novos)} nomes novos ({len(cache)} no cache; {falhas} falhas).")
    return cache


if __name__ == "__main__":
    enriquecer()
