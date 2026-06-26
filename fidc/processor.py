"""Extrai e consolida os ZIPs da CVM em duas bases analíticas (parquet):

1. fidc_consolidado.parquet — fato fundo-mês (PL, ativo, carteira, inadimplência,
   segmentos, rating SCR, liquidez).
2. fidc_cotas.parquet — fato série/cota-mês (senioridade, valor da cota,
   rentabilidade, nº de cotistas, captação/amortização/resgate).
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile

import numpy as np
import pandas as pd

import config
from fidc import columns as C

# Extrai o "nome da tabela" do arquivo: inf_mensal_fidc_<TABELA>_<AAAA[MM]>.csv
_TBL_RE = re.compile(r"inf_mensal_fidc_(.+)_\d{4,6}\.csv$", re.IGNORECASE)


def _tabela_do_arquivo(nome: str) -> str | None:
    m = _TBL_RE.search(nome.rsplit("/", 1)[-1])
    return m.group(1) if m else None


def _ler_csv(zf: zipfile.ZipFile, nome: str) -> pd.DataFrame | None:
    """Lê um CSV de dentro do ZIP como texto (dtype=str) e normaliza colunas-id."""
    with zf.open(nome) as fh:
        raw = fh.read()
    df = pd.read_csv(
        io.BytesIO(raw),
        sep=config.CSV_SEP,
        encoding=config.CSV_ENCODING,
        dtype=str,
        low_memory=False,
        # Os CSVs da CVM não usam aspas; algumas razões sociais têm " solto,
        # que faz o parser C "engolir" linhas. QUOTE_NONE lê tudo literalmente.
        quoting=csv.QUOTE_NONE,
    )
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns=C.RENAME_ID)
    if "cnpj" not in df.columns or "dt_comptc" not in df.columns:
        return None
    return df


def _ler_tabela(zf: zipfile.ZipFile, nomes: list[str], tabela: str) -> pd.DataFrame | None:
    """Lê e concatena TODOS os CSVs de uma tabela (match exato pelo nome da tabela).

    Necessário porque o layout varia: até 2018 cada tabela é um único CSV anual
    (tab_I_2018.csv); de 2019 em diante há um CSV por mês (tab_I_201901.csv ...).
    O match exato evita confundir tab_X_1 com tab_X_1_1, por exemplo.
    """
    arquivos = [n for n in nomes if _tabela_do_arquivo(n) == tabela]
    dfs = [d for n in arquivos if (d := _ler_csv(zf, n)) is not None]
    if not dfs:
        return None
    return pd.concat(dfs, ignore_index=True)


def _selecionar_valores(df: pd.DataFrame, mapa: dict[str, str],
                        chave: list[str] | None = None) -> pd.DataFrame:
    """Mantém chave + colunas de valor existentes, renomeadas e numéricas."""
    chave = chave or C.CHAVE
    cols = {origem: canon for canon, origem in mapa.items() if origem in df.columns}
    out = df[chave + list(cols.keys())].rename(columns=cols)
    for canon in cols.values():
        out[canon] = pd.to_numeric(out[canon], errors="coerce")
    return out.drop_duplicates(subset=chave, keep="last")


# --------------------------------------------------------------------------- #
# Fato fundo-mês
# --------------------------------------------------------------------------- #
def _processar_fundo(zf, nomes) -> pd.DataFrame:
    base = _ler_tabela(zf, nomes, "tab_I")
    if base is None:
        return pd.DataFrame()

    id_cols = [c for c in ["cnpj", "denom_social", "dt_comptc", "tp_fundo_classe",
                           "cnpj_admin", "admin", "condom", "fundo_exclusivo"]
               if c in base.columns]
    fato = base[id_cols].drop_duplicates(subset=C.CHAVE, keep="last").merge(
        _selecionar_valores(base, C.TAB_I_VALORES), on=C.CHAVE, how="left"
    )

    for tabela, mapa in [
        ("tab_IV", C.TAB_IV_VALORES),
        ("tab_II", C.TAB_II_VALORES),
        ("tab_V", C.TAB_V_VALORES),
        ("tab_VII", C.TAB_VII_VALORES),   # nº de cedentes (diversificação)
        ("tab_X", C.TAB_X_RATING),        # rating SCR (pós-Res.175)
        ("tab_X_5", C.TAB_X5_LIQUIDEZ),   # liquidez
    ]:
        df = _ler_tabela(zf, nomes, tabela)
        if df is not None:
            fato = fato.merge(_selecionar_valores(df, mapa), on=C.CHAVE, how="left")

    # Concentração de cedentes (a partir dos percentuais por cedente da Tab. I)
    conc = _concentracao_cedentes(base)
    if conc is not None:
        fato = fato.merge(conc, on=C.CHAVE, how="left")

    inv = _processar_investidores(zf, nomes)
    if inv is not None:
        fato = fato.merge(inv, on=C.CHAVE, how="left")

    return _derivar_fundo(fato)


def _processar_investidores(zf, nomes) -> pd.DataFrame | None:
    """nº de cotistas por tipo de investidor (tab_X_1_1, pós-Res.175).

    Soma as parcelas sênior e subordinada de cada tipo num total por fundo-mês.
    """
    x11 = _ler_tabela(zf, nomes, "tab_X_1_1")
    if x11 is None:
        return None
    out = x11[C.CHAVE].copy()
    achou = False
    for key in C.INVESTIDOR_TIPOS:
        fontes = [f"TAB_X_NR_COTST_SENIOR_{key.upper()}",
                  f"TAB_X_NR_COTST_SUBORD_{key.upper()}"]
        fontes = [c for c in fontes if c in x11.columns]
        if fontes:
            achou = True
            out[f"cotst_{key}"] = sum(
                pd.to_numeric(x11[c], errors="coerce").fillna(0) for c in fontes)
    if not achou:
        return None
    return out.drop_duplicates(subset=C.CHAVE, keep="last")


def _concentracao_cedentes(base: pd.DataFrame) -> pd.DataFrame | None:
    """Concentração de cedentes a partir dos % por cedente da Tabela I.

    A CVM lista os maiores cedentes (com e sem risco) com seu percentual.
    Derivamos: maior cedente (%), 5 maiores (%) e nº de cedentes nomeados.
    """
    pr_cols = [c for c in base.columns if re.search(r"PR_CEDENTE_\d+$", c)]
    if not pr_cols:
        return None
    vals = base[pr_cols].apply(pd.to_numeric, errors="coerce")
    vals = vals.where((vals >= 0) & (vals <= 100))   # descarta lixo (>100% etc.)
    arr = np.sort(np.nan_to_num(vals.to_numpy(dtype=float), nan=0.0), axis=1)[:, ::-1]
    sub = base[C.CHAVE].copy()
    sub["cedente_top1_pct"] = arr[:, 0]
    sub["cedente_top5_pct"] = arr[:, :5].sum(axis=1).clip(max=100)
    sub["n_cedentes_nomeados"] = (vals > 0).sum(axis=1)
    # top1 == 0 significa "sem cedente reportado" → NaN (não é concentração zero)
    sub.loc[sub["cedente_top1_pct"] <= 0, ["cedente_top1_pct", "cedente_top5_pct"]] = np.nan
    return sub.drop_duplicates(subset=C.CHAVE, keep="last")


def _normaliza_doc(serie: pd.Series) -> pd.DataFrame:
    """Normaliza CPF/CNPJ de cedente. Devolve doc, doc_tipo e raiz (8 díg. do CNPJ).

    A CVM mistura CPF (11 díg.) e CNPJ (14 díg.) no mesmo campo e, em alguns
    informes, zeros à esquerda do CNPJ se perdem (vira 12/13 díg.). Regra:
      - 11 díg.  -> CPF (raiz vazia: cedente pessoa física, anonimizado no painel)
      - 8..14 díg. e != 11 -> CNPJ (zfill p/ 14; raiz = 8 primeiros)
      - dummies (só 0 ou só 9) e curtos demais (<8) -> inválido (descartado depois)
    """
    # astype(object): garante o motor de regex do Python (RE2/Arrow não suporta
    # retrovínculo \1 usado para detectar dígito único repetido).
    digits = (serie.fillna("").astype(str)
              .str.replace(r"\D", "", regex=True).astype(object))
    n = digits.str.len()
    # Sentinelas da CVM para "cedente diverso/pulverizado" ou campo não informado:
    # sequências de 0 ou 9 (inclusive variações como 9999999999999 8 / ...97) e
    # documentos com um único dígito repetido (000..., 111..., 999...).
    # 8+ zeros/noves à esquerda cobre raízes reservadas (00000000.../99999999...,
    # com ou sem o sufixo /0001-91); nenhum CNPJ/CPF real começa assim.
    sentinela = (digits.str.match(r"^0{8,}").fillna(False)
                 | digits.str.match(r"^9{8,}").fillna(False)
                 | digits.str.fullmatch(r"(\d)\1+").fillna(False))
    invalido = (n < 8) | (n > 14) | sentinela
    eh_cpf = (n == 11) & ~invalido
    eh_cnpj = (n >= 8) & (n <= 14) & (n != 11) & ~invalido

    doc = digits.where(eh_cpf, digits.str.zfill(14))   # CNPJ -> 14 díg.; CPF fica 11
    doc = doc.where(~eh_cpf, digits)                    # garante CPF intacto
    doc_tipo = pd.Series("invalido", index=serie.index)
    doc_tipo = doc_tipo.mask(eh_cpf, "CPF").mask(eh_cnpj, "CNPJ")
    raiz = doc.str[:8].where(eh_cnpj, other=pd.NA)
    return pd.DataFrame({"doc": doc.where(~invalido, other=pd.NA),
                         "doc_tipo": doc_tipo, "raiz": raiz}, index=serie.index)


def _extrair_cedentes(base: pd.DataFrame) -> pd.DataFrame | None:
    """Extrai os cedentes nomeados da Tab. I em formato longo (1 linha/cedente).

    Para cada fundo-mês, percorre os blocos com/sem risco e os 9 slots de cedente,
    desempilhando CPF_CNPJ_CEDENTE_n + PR_CEDENTE_n. Estima a exposição em R$ de
    cada cedente como PR% × valor da carteira do bloco. Descarta documentos
    inválidos/dummy e percentuais fora de (0, 100].
    """
    id_cols = [c for c in ["cnpj", "dt_comptc", "denom_social"] if c in base.columns]
    if "cnpj" not in id_cols:
        return None
    partes = []
    for bloco, prefixo, val_col in C.CEDENTE_BLOCOS:
        vl_bloco = (pd.to_numeric(base[val_col], errors="coerce")
                    if val_col in base.columns else pd.Series(np.nan, index=base.index))
        for slot in range(1, C.CEDENTE_MAX_SLOT + 1):
            col_doc = f"{prefixo}_CPF_CNPJ_CEDENTE_{slot}"
            col_pr = f"{prefixo}_PR_CEDENTE_{slot}"
            if col_doc not in base.columns or col_pr not in base.columns:
                continue
            pr = pd.to_numeric(base[col_pr], errors="coerce")
            sub = base[id_cols].copy()
            sub["bloco"] = bloco
            sub["rank"] = slot
            sub = sub.join(_normaliza_doc(base[col_doc]))
            sub["pr_cedente"] = pr
            sub["vl_bloco"] = vl_bloco.values
            partes.append(sub)
    if not partes:
        return None
    ced = pd.concat(partes, ignore_index=True)
    # Mantém só cedentes válidos com percentual plausível
    ced = ced[ced["doc"].notna() & (ced["doc_tipo"] != "invalido")]
    ced = ced[(ced["pr_cedente"] > 0) & (ced["pr_cedente"] <= 100)]
    if ced.empty:
        return ced
    # Exposição estimada em R$ = PR% × valor da carteira do bloco. Valor de
    # carteira ausente/negativo (erro de digitação na fonte) -> exposição NaN.
    vl_bloco_ok = ced["vl_bloco"].where(ced["vl_bloco"] > 0)
    ced["vl_estimado"] = ced["pr_cedente"] / 100.0 * vl_bloco_ok
    return ced.drop_duplicates(subset=["cnpj", "dt_comptc", "bloco", "rank", "doc"],
                               keep="last").reset_index(drop=True)


def _derivar_cedentes(ced: pd.DataFrame) -> pd.DataFrame:
    """Adiciona competência/ano ao fato de cedentes."""
    if ced is None or ced.empty:
        return pd.DataFrame()
    ced = ced.copy()
    ced["dt_comptc"] = pd.to_datetime(ced["dt_comptc"], errors="coerce")
    ced = ced.dropna(subset=["dt_comptc"])
    ced["competencia"] = ced["dt_comptc"].dt.to_period("M").astype(str)
    ced["ano"] = ced["dt_comptc"].dt.year
    if "denom_social" in ced.columns:
        ced["denom_social"] = ced["denom_social"].astype("string").str.strip()
    return ced.reset_index(drop=True)


def _derivar_fundo(fato: pd.DataFrame) -> pd.DataFrame:
    if fato.empty:
        return fato
    fato["dt_comptc"] = pd.to_datetime(fato["dt_comptc"], errors="coerce")
    fato = fato.dropna(subset=["dt_comptc"])
    fato["competencia"] = fato["dt_comptc"].dt.to_period("M").astype(str)
    fato["ano"] = fato["dt_comptc"].dt.year

    def soma(*cols):
        existentes = [c for c in cols if c in fato.columns]
        return fato[existentes].fillna(0).sum(axis=1) if existentes else 0.0

    fato["vl_dircred"] = soma("vl_dircred_risco", "vl_dircred_sem_risco")
    fato["vl_venc_inad"] = soma("vl_venc_inad_risco", "vl_venc_inad_sem_risco")
    fato["vl_cred_inad"] = soma("vl_cred_inad_risco", "vl_cred_inad_sem_risco")
    fato["vl_pdd"] = soma("vl_reducao_recup_risco", "vl_reducao_recup_sem_risco")

    for col in ("condom", "fundo_exclusivo", "tp_fundo_classe", "admin", "denom_social"):
        if col in fato.columns:
            fato[col] = fato[col].astype("string").str.strip()
    if "tp_fundo_classe" not in fato.columns:
        fato["tp_fundo_classe"] = "Fundo"
    fato["tp_fundo_classe"] = fato["tp_fundo_classe"].fillna("Fundo")

    # Outlier: vl_ativo/vl_pl > 50 indica erro de digitação na fonte CVM
    # (ex.: AMERRA-LEAF jul/2020 reportou vlmob=R$966bi por engano; vl_pl correto ~R$12M)
    # Nullify os campos contaminados; sub-componentes confiáveis (vl_dircred etc.) ficam.
    if "vl_pl" in fato.columns and "vl_ativo" in fato.columns:
        pl_pos = fato["vl_pl"].gt(0)
        outlier = pl_pos & fato["vl_ativo"].gt(fato["vl_pl"] * 50)
        if outlier.any():
            n = int(outlier.sum())
            print(f"  [aviso] {n} linha(s) com vl_ativo/vl_pl > 50× — corrigido para NaN (erro CVM)")
            for col in ("vl_ativo", "vl_carteira", "vl_valores_mobiliarios"):
                if col in fato.columns:
                    fato.loc[outlier, col] = np.nan

    return fato


# --------------------------------------------------------------------------- #
# Fato série/cota-mês (senioridade)
# --------------------------------------------------------------------------- #
def _normaliza_serie(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["classe_serie"] = df[C.COL_SERIE].astype("string").str.strip()
    return df


def _processar_cotas(zf, nomes, fato_fundo: pd.DataFrame) -> pd.DataFrame:
    x2 = _ler_tabela(zf, nomes, "tab_X_2")
    if x2 is None or C.COL_SERIE not in x2.columns:
        return pd.DataFrame()

    chave_s = C.CHAVE + ["classe_serie"]
    cotas = _selecionar_valores(_normaliza_serie(x2), C.TAB_X2_VALORES, chave_s)

    # nº de cotistas, rentabilidade, desempenho
    for tabela, mapa in [("tab_X_1", C.TAB_X1_VALORES),
                         ("tab_X_3", C.TAB_X3_VALORES),
                         ("tab_X_6", C.TAB_X6_VALORES)]:
        df = _ler_tabela(zf, nomes, tabela)
        if df is not None and C.COL_SERIE in df.columns:
            cotas = cotas.merge(
                _selecionar_valores(_normaliza_serie(df), mapa, chave_s),
                on=chave_s, how="left")

    # Fluxo (tab_X_4): pivota TP_OPER em colunas
    x4 = _ler_tabela(zf, nomes, "tab_X_4")
    if x4 is not None and {C.COL_SERIE, C.COL_TP_OPER, "TAB_X_VL_TOTAL"} <= set(x4.columns):
        x4 = _normaliza_serie(x4)
        x4["op"] = x4[C.COL_TP_OPER].map(C.classificar_operacao)
        x4["vl"] = pd.to_numeric(x4["TAB_X_VL_TOTAL"], errors="coerce")
        fluxo = (x4.dropna(subset=["op"])
                 .groupby(chave_s + ["op"], as_index=False)["vl"].sum()
                 .pivot_table(index=chave_s, columns="op", values="vl", aggfunc="sum")
                 .reset_index())
        fluxo.columns.name = None
        cotas = cotas.merge(fluxo, on=chave_s, how="left")

    return _derivar_cotas(cotas, fato_fundo)


def _derivar_cotas(cotas: pd.DataFrame, fato_fundo: pd.DataFrame) -> pd.DataFrame:
    if cotas.empty:
        return cotas
    cotas["dt_comptc"] = pd.to_datetime(cotas["dt_comptc"], errors="coerce")
    cotas = cotas.dropna(subset=["dt_comptc"])
    cotas["competencia"] = cotas["dt_comptc"].dt.to_period("M").astype(str)
    cotas["senioridade"] = cotas["classe_serie"].map(C.classificar_senioridade)

    # PL bruto da série = quantidade de cotas * valor da cota.
    # ATENÇÃO: alguns fundos reportam qt_cota/vl_cota com erros grosseiros, então
    # esse valor bruto é só um insumo para calcular a PROPORÇÃO por senioridade.
    qt = cotas["qt_cota"].fillna(0) if "qt_cota" in cotas else 0
    vl = cotas["vl_cota"].fillna(0) if "vl_cota" in cotas else 0
    cotas["pl_serie"] = qt * vl

    # Enriquece com atributos do fundo (para filtros consistentes no dashboard)
    if not fato_fundo.empty:
        attrs = (fato_fundo[["cnpj", "dt_comptc", "denom_social", "admin",
                            "tp_fundo_classe", "condom", "fundo_exclusivo", "vl_pl"]]
                 .drop_duplicates(subset=C.CHAVE))
        cotas = cotas.merge(attrs, on=C.CHAVE, how="left")

    # pl_aloc: PL REAL do fundo (tab_IV) rateado pela participação da série no fundo.
    # Garante que a soma por senioridade sempre reproduza o PL de mercado correto,
    # neutralizando outliers de qt/vl_cota de fundos isolados.
    soma_fundo = cotas.groupby(C.CHAVE)["pl_serie"].transform("sum")
    share = (cotas["pl_serie"] / soma_fundo).where(soma_fundo > 0)
    if "vl_pl" in cotas:
        cotas["pl_aloc"] = (cotas["vl_pl"] * share)
        # Sem PL do fundo ou sem proporção válida: usa o bruto como fallback.
        cotas["pl_aloc"] = cotas["pl_aloc"].fillna(cotas["pl_serie"])
    else:
        cotas["pl_aloc"] = cotas["pl_serie"]
    return cotas


def _processar_cedentes(zf, nomes) -> pd.DataFrame:
    """Lê a Tab. I do ZIP e devolve o fato de cedentes nomeados (formato longo)."""
    base = _ler_tabela(zf, nomes, "tab_I")
    if base is None:
        return pd.DataFrame()
    return _derivar_cedentes(_extrair_cedentes(base))


def processar_zip(caminho_zip) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Lê um ZIP da CVM e devolve (fato_fundo, fato_cotas, fato_cedentes)."""
    with zipfile.ZipFile(caminho_zip) as zf:
        nomes = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        fundo = _processar_fundo(zf, nomes)
        cotas = _processar_cotas(zf, nomes, fundo)
        cedentes = _processar_cedentes(zf, nomes)
    return fundo, cotas, cedentes


# --------------------------------------------------------------------------- #
# Consolidação
# --------------------------------------------------------------------------- #
def _carregar_manifest() -> dict:
    if config.MANIFEST.exists():
        return json.loads(config.MANIFEST.read_text(encoding="utf-8"))
    return {}


def _concatena_parts(parts_dir, chave: list[str], destino, verbose: bool):
    parts = sorted(parts_dir.glob("*.parquet"))
    # Ignora parts vazios/sem a coluna de data (ex.: layout antigo sem cedentes).
    dfs = [d for p in parts if not (d := pd.read_parquet(p)).empty and "dt_comptc" in d.columns]
    if not dfs:
        return pd.DataFrame()
    todos = pd.concat(dfs, ignore_index=True)
    todos = todos.sort_values("dt_comptc").drop_duplicates(subset=chave, keep="last")
    todos = todos.reset_index(drop=True)
    todos.to_parquet(destino, index=False)
    return todos


def consolidar(*, verbose: bool = True) -> None:
    """Processa os ZIPs em parts e gera os dois parquets consolidados."""
    config.ensure_dirs()
    manifest = _carregar_manifest()

    zips = sorted(config.RAW_DIR.glob("inf_mensal_fidc_*.zip"))
    if verbose:
        print(f"Processando {len(zips)} ZIP(s)...")

    for z in zips:
        part_f = config.PARTS_DIR / (z.stem + ".parquet")
        part_c = config.PARTS_COTAS_DIR / (z.stem + ".parquet")
        part_ced = config.PARTS_CEDENTES_DIR / (z.stem + ".parquet")
        tam_atual = z.stat().st_size
        tam_proc = manifest.get(z.name, {}).get("size_processed")
        if part_f.exists() and part_c.exists() and part_ced.exists() and tam_proc == tam_atual:
            continue
        try:
            fundo, cotas, cedentes = processar_zip(z)
            if not fundo.empty:
                fundo.to_parquet(part_f, index=False)
            if not cotas.empty:
                cotas.to_parquet(part_c, index=False)
            # Sempre (re)escreve o part de cedentes — inclusive vazio, p/ marcar
            # o ZIP como processado e não reprocessar à toa.
            cedentes.to_parquet(part_ced, index=False)
            manifest.setdefault(z.name, {})["size_processed"] = tam_atual
            if verbose:
                print(f"  [ok ] {z.name}: {len(fundo):,} fundos | "
                      f"{len(cotas):,} cotas | {len(cedentes):,} cedentes")
        except Exception as exc:  # noqa: BLE001
            print(f"  [erro] {z.name}: {exc}")

    config.MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    fundo = _concatena_parts(config.PARTS_DIR, C.CHAVE, config.CONSOLIDADO, verbose)
    cotas = _concatena_parts(config.PARTS_COTAS_DIR, C.CHAVE + ["classe_serie"],
                             config.CONSOLIDADO_COTAS, verbose)
    _concatena_parts(config.PARTS_CEDENTES_DIR,
                     ["cnpj", "dt_comptc", "bloco", "rank", "doc"],
                     config.CONSOLIDADO_CEDENTES, verbose)

    # Enriquece com gestor e metadados do cadastro CVM (best-effort)
    if not fundo.empty:
        try:
            import re as _re
            from fidc.benchmarks import fetch_cadastro

            def _norm(s: str) -> str:
                d = _re.sub(r"\D", "", str(s))
                return d.zfill(14) if d else ""

            cad = fetch_cadastro(verbose=verbose)
            if not cad.empty:
                cad["_cn"] = cad["cnpj"].apply(_norm)
                fundo["_cn"] = fundo["cnpj"].apply(_norm)
                # Remove colunas que serão recarregadas (evita duplicatas em re-runs)
                _meta_cols = [c for c in ["gestor", "classe_anbima",
                                          "taxa_adm", "taxa_perfm", "sit"]
                              if c in fundo.columns]
                if _meta_cols:
                    fundo = fundo.drop(columns=_meta_cols)
                _cad_cols = ["_cn"] + [c for c in ["gestor", "classe_anbima",
                                                    "taxa_adm", "taxa_perfm", "sit"]
                                       if c in cad.columns]
                fundo = (fundo.merge(cad[_cad_cols], on="_cn", how="left")
                         .drop(columns=["_cn"]))

                # Cotas: só gestor (para filtro) — _cn ainda está em cad
                if not cotas.empty:
                    if "gestor" in cotas.columns:
                        cotas = cotas.drop(columns=["gestor"])
                    cotas["_cn"] = cotas["cnpj"].apply(_norm)
                    cotas = (cotas.merge(cad[["_cn", "gestor"]], on="_cn", how="left")
                             .drop(columns=["_cn"]))

                fundo.to_parquet(config.CONSOLIDADO, index=False)
                if not cotas.empty:
                    cotas.to_parquet(config.CONSOLIDADO_COTAS, index=False)
        except Exception as exc:  # noqa: BLE001
            print(f"  [aviso] Metadados não enriquecidos: {exc}")

    if verbose and not fundo.empty:
        print(f"\nFato fundo : {len(fundo):,} linhas | "
              f"{fundo['competencia'].min()} a {fundo['competencia'].max()} | "
              f"{fundo['cnpj'].nunique():,} CNPJs")
    if verbose and not cotas.empty:
        print(f"Fato cotas : {len(cotas):,} linhas | "
              f"senioridades: {cotas['senioridade'].value_counts().to_dict()}")


if __name__ == "__main__":
    consolidar()
