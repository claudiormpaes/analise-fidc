"""Dashboard de análise do mercado de FIDCs (CVM) — Streamlit, estilo Power BI.

Rodar:  python -m streamlit run app.py
Dados:  data/processed/fidc_consolidado.parquet  (fato fundo-mês)
        data/processed/fidc_cotas.parquet        (fato série/cota-mês)
Gere/atualize com:  python -m fidc.pipeline
"""
from __future__ import annotations

from datetime import datetime

import shutil
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import config
from fidc import columns as C

_HF_DATASET = "claudiormpaes/fidc-dados"


def _garantir_dados_hf(caminho: Path, filename: str) -> bool:
    """Baixa arquivo do HF Dataset quando não existe localmente (ex: Hugging Face Space)."""
    if caminho.exists():
        return True
    try:
        from huggingface_hub import hf_hub_download
        caminho.parent.mkdir(parents=True, exist_ok=True)
        origem = hf_hub_download(repo_id=_HF_DATASET, filename=filename, repo_type="dataset")
        shutil.copy(origem, caminho)
        return True
    except Exception as e:
        st.warning(f"Não foi possível baixar {filename} do Hugging Face: {e}")
        return False

st.set_page_config(page_title="FIDC Analytics — CVM", page_icon="📊", layout="wide")

CORES = px.colors.qualitative.Safe
COR_SEN = {"Sênior": "#2E7D32", "Mezanino": "#F9A825", "Subordinada": "#C62828",
           "Única": "#1565C0", "Outra": "#9E9E9E"}
ACCENT = "#2E7D32"

# --------------------------------------------------------------------------- #
# CSS — visual de cards/tiles tipo Power BI
# --------------------------------------------------------------------------- #
st.markdown("""
<style>
/* ── Desktop ──────────────────────────────────────────────── */
.block-container {padding-top:1.6rem;padding-bottom:1rem;max-width:1500px;}
section[data-testid="stSidebar"] {background:#F4F6FA;}
.kpi-card {background:#fff;border:1px solid #E6E9EF;border-radius:14px;
  padding:14px 16px;box-shadow:0 1px 3px rgba(16,24,40,.06);height:100%;}
.kpi-label{font-size:.70rem;letter-spacing:.05em;text-transform:uppercase;
  color:#667085;margin:0;font-weight:600;}
.kpi-value{font-size:1.15rem;font-weight:700;color:#101828;margin:.15rem 0 0;
  line-height:1.25;overflow-wrap:break-word;word-break:break-word;}
.kpi-delta{font-size:.78rem;margin-top:.2rem;font-weight:600;}
.up{color:#2E7D32;} .down{color:#C62828;} .flat{color:#667085;}
.slicer-box{background:#F4F6FA;border:1px solid #E6E9EF;border-radius:14px;
  padding:.4rem 1rem .8rem;}
.chip{display:inline-block;background:#E8F5E9;color:#1B5E20;border:1px solid #66BB6A;
  border-radius:16px;padding:3px 12px;font-size:.8rem;margin:2px 6px 2px 0;font-weight:600;}
div[data-testid="stTabs"] button[role="tab"]{font-weight:600;}
h1{font-size:1.7rem !important;}

/* ── Mobile (≤ 768 px) ────────────────────────────────────── */
@media (max-width: 768px) {
  /* Espaçamento geral */
  .block-container {
    padding-top:.6rem !important;
    padding-left:.5rem !important;
    padding-right:.5rem !important;
    max-width:100% !important;
  }

  /* Título */
  h1 { font-size:1.1rem !important; }

  /* KPI cards menores */
  .kpi-card  { padding:8px 10px; border-radius:10px; }
  .kpi-label { font-size:.60rem !important; }
  .kpi-value { font-size:.92rem !important; }
  .kpi-delta { font-size:.70rem !important; }

  /* Slicer box */
  .slicer-box { padding:.2rem .5rem .5rem; }

  /* Abas: scroll horizontal em vez de quebrar linha */
  div[data-testid="stTabs"] > div:first-child {
    overflow-x: auto !important;
    flex-wrap: nowrap !important;
    -webkit-overflow-scrolling: touch;
  }
  div[data-testid="stTabs"] button[role="tab"] {
    font-size:.72rem !important;
    padding:4px 8px !important;
    white-space: nowrap !important;
  }

  /* Colunas: deixa o Streamlit empilhar normalmente no mobile */
  div[data-testid="column"] { min-width: 0 !important; }

  /* Tabelas: scroll horizontal */
  div[data-testid="stDataFrame"], div[data-testid="stTable"] {
    overflow-x: auto !important;
    -webkit-overflow-scrolling: touch;
  }

  /* Plotly: altura reduzida */
  .js-plotly-plot .plotly { max-height: 280px; }

  /* Evita overflow lateral */
  body, .main { overflow-x: hidden !important; }
}
</style>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Carga
# --------------------------------------------------------------------------- #
# Colunas de texto usadas em groupby de MÚLTIPLAS chaves: mantê-las como texto
# evita o produto cartesiano de categorias no groupby (que aumentaria a memória).
_NAO_CATEGORIZAR = {"senioridade", "tp_aplic"}


def _otimizar_memoria(df: pd.DataFrame) -> pd.DataFrame:
    """Reduz o uso de memória SEM alterar os valores exibidos:
      - texto muito repetido  -> category   (economiza 60-80% naquelas colunas)
      - inteiros              -> menor tipo que couber (lossless)
      - float64               -> float32    (~7 dígitos significativos; sobra
                                  para os valores em R$ bi/% deste painel)
    """
    if df.empty:
        return df
    for col in df.select_dtypes(include="object").columns:
        if col in _NAO_CATEGORIZAR:
            continue
        # só vale a pena quando há muita repetição (poucos valores distintos)
        if df[col].nunique(dropna=False) < len(df) * 0.5:
            df[col] = df[col].astype("category")
    for col in df.select_dtypes(include="integer").columns:
        df[col] = pd.to_numeric(df[col], downcast="integer")
    for col in df.select_dtypes(include="float").columns:
        df[col] = pd.to_numeric(df[col], downcast="float")
    return df


@st.cache_data(show_spinner="Carregando base de fundos...")
def carregar_fundos() -> pd.DataFrame:
    _garantir_dados_hf(config.CONSOLIDADO, "fidc_consolidado.parquet")
    if not config.CONSOLIDADO.exists():
        return pd.DataFrame()
    df = pd.read_parquet(config.CONSOLIDADO)
    df["dt_comptc"] = pd.to_datetime(df["dt_comptc"])
    return _otimizar_memoria(df)


@st.cache_data(show_spinner="Carregando base de cotas...")
def carregar_cotas() -> pd.DataFrame:
    _garantir_dados_hf(config.CONSOLIDADO_COTAS, "fidc_cotas.parquet")
    if not config.CONSOLIDADO_COTAS.exists():
        return pd.DataFrame()
    df = pd.read_parquet(config.CONSOLIDADO_COTAS)
    df["dt_comptc"] = pd.to_datetime(df["dt_comptc"])
    return _otimizar_memoria(df)


@st.cache_data(show_spinner=False)
def carregar_cdi() -> pd.DataFrame:
    _garantir_dados_hf(config.CDI_MENSAL, "cdi_mensal.parquet")
    if not config.CDI_MENSAL.exists():
        return pd.DataFrame(columns=["competencia", "cdi_mes"])
    return pd.read_parquet(config.CDI_MENSAL)


@st.cache_data(show_spinner=False)
def carregar_ipca() -> pd.DataFrame:
    _garantir_dados_hf(config.IPCA_MENSAL, "ipca_mensal.parquet")
    if not config.IPCA_MENSAL.exists():
        return pd.DataFrame(columns=["competencia", "ipca_mes"])
    return pd.read_parquet(config.IPCA_MENSAL)


@st.cache_data(show_spinner=False)
def carregar_selic() -> pd.DataFrame:
    _garantir_dados_hf(config.SELIC_MENSAL, "selic_mensal.parquet")
    if not config.SELIC_MENSAL.exists():
        return pd.DataFrame(columns=["competencia", "selic_mes"])
    return pd.read_parquet(config.SELIC_MENSAL)


@st.cache_data(show_spinner=False)
def carregar_carteira() -> pd.DataFrame:
    _garantir_dados_hf(config.CARTEIRA, "fidc_carteira.parquet")
    if not config.CARTEIRA.exists():
        return pd.DataFrame()
    return _otimizar_memoria(pd.read_parquet(config.CARTEIRA))


@st.cache_data(show_spinner="Carregando cedentes...")
def carregar_cedentes() -> pd.DataFrame:
    _garantir_dados_hf(config.CONSOLIDADO_CEDENTES, "fidc_cedentes.parquet")
    if not config.CONSOLIDADO_CEDENTES.exists():
        return pd.DataFrame()
    df = pd.read_parquet(config.CONSOLIDADO_CEDENTES)
    df["dt_comptc"] = pd.to_datetime(df["dt_comptc"])
    return _otimizar_memoria(df)


@st.cache_data(show_spinner=False)
def carregar_cedentes_nomes() -> pd.DataFrame:
    _garantir_dados_hf(config.CEDENTES_NOMES, "cedentes_nomes.parquet")
    if not config.CEDENTES_NOMES.exists():
        return pd.DataFrame(columns=["doc", "razao_social", "uf", "municipio"])
    return pd.read_parquet(config.CEDENTES_NOMES)


def fmt_bi(v):
    if v is None or pd.isna(v):
        return "—"
    return f"R$ {v / 1e9:,.1f} bi".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_pct(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{v * 100:,.2f}%".replace(".", ",")


def fmt_int(v):
    return f"{int(v):,}".replace(",", ".")


def style_fig(fig, h=320):
    """Tema unificado nos gráficos (look limpo tipo BI)."""
    fig.update_layout(
        template="plotly_white", height=h,
        margin=dict(l=8, r=8, t=46, b=8),
        font=dict(family="Segoe UI, Roboto, sans-serif", size=12, color="#1A1F2B"),
        title_font=dict(size=14), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, title=""),
        xaxis_title="", yaxis_title="",
        # Responsivo: encolhe para caber em telas menores sem barra de scroll horizontal
        autosize=True,
    )
    fig.update_layout(
        xaxis=dict(tickfont=dict(size=10)),
        yaxis=dict(tickfont=dict(size=10)),
    )
    return fig


def fonte(texto: str = "", *, base: str = "Informe Mensal de FIDC — Portal de Dados Abertos da CVM") -> None:
    """Legenda padronizada de fonte dos dados sob um gráfico/tabela.

    `base` é a fonte primária (CVM); `texto` acrescenta tabela/recorte/cálculo.
    Usada em todos os gráficos e tabelas do painel para rastreabilidade.
    """
    msg = f"📄 Fonte: {base}" + (f" · {texto}" if texto else "")
    st.caption(msg)


def _fmt_cnpj(doc: str) -> str:
    """Formata um documento de cedente: CNPJ mascarado em XX.XXX.XXX/XXXX-XX;
    CPF (11 díg.) anonimizado (LGPD) como CPF ***.XXX.***-**."""
    d = "".join(ch for ch in str(doc) if ch.isdigit())
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"CPF ***.{d[3:6]}.***-**"  # anonimizado
    return str(doc)


def card(label, value, delta_html=""):
    return (f"<div class='kpi-card'><p class='kpi-label'>{label}</p>"
            f"<p class='kpi-value'>{value}</p>{delta_html}</div>")


def delta_pp(cur, prev, inverse=False):
    """HTML de delta em pontos percentuais (para indicadores em %)."""
    if cur is None or prev is None or pd.isna(cur) or pd.isna(prev):
        return ""
    d = (cur - prev) * 100
    up = d >= 0
    good = (not up) if inverse else up
    arrow = "▲" if up else "▼"
    cls = "up" if good else "down"
    return f"<p class='kpi-delta {cls}'>{arrow} {abs(d):.2f} p.p.</p>".replace(".", ",")


def delta_val(cur, prev):
    if cur is None or prev is None or pd.isna(cur) or pd.isna(prev):
        return ""
    d = cur - prev
    cls = "up" if d >= 0 else "down"
    arrow = "▲" if d >= 0 else "▼"
    return f"<p class='kpi-delta {cls}'>{arrow} {fmt_bi(abs(d))}</p>"


df = carregar_fundos()
dfc = carregar_cotas()
dfcart = carregar_carteira()
if df.empty:
    st.title("📊 FIDC Analytics")
    st.warning("Base não gerada. Rode:\n\n```\npython -m fidc.pipeline\n```")
    st.stop()

# --------------------------------------------------------------------------- #
# Sidebar — filtros "estáticos"
# --------------------------------------------------------------------------- #
st.sidebar.header("Filtros")
comp_min, comp_max = df["dt_comptc"].min(), df["dt_comptc"].max()
periodo = st.sidebar.slider(
    "Período (séries temporais)",
    min_value=comp_min.to_pydatetime(), max_value=comp_max.to_pydatetime(),
    value=(comp_min.to_pydatetime(), comp_max.to_pydatetime()), format="MM/YYYY")
busca = st.sidebar.text_input("🔎 Nome do fundo contém", "",
                              placeholder="ex.: agro, consignado, XP...").strip()
condoms = sorted(df["condom"].dropna().unique().tolist()) if "condom" in df else []
sel_condom = st.sidebar.multiselect("Condomínio", condoms, default=condoms)
excls = sorted(df["fundo_exclusivo"].dropna().unique().tolist()) if "fundo_exclusivo" in df else []
sel_excl = st.sidebar.multiselect("Exclusivo", excls, default=excls)
top_adm = (df.groupby("admin")["vl_pl"].sum().sort_values(ascending=False)
           .head(50).index.tolist() if "admin" in df else [])
sel_adm = st.sidebar.multiselect("Administrador", top_adm, default=[])
top_gest = (df.groupby("gestor")["vl_pl"].sum().sort_values(ascending=False)
            .index.tolist() if "gestor" in df.columns else [])
sel_gest = (st.sidebar.multiselect("Gestor", top_gest, default=[]) if top_gest else [])
anbima_opts = (sorted(df["classe_anbima"].dropna().unique().tolist())
               if "classe_anbima" in df.columns else [])
# Esconde o filtro quando não há dados (a CVM não classifica FIDC por ANBIMA).
sel_anbima = (st.sidebar.multiselect("Classificação ANBIMA", anbima_opts, default=[])
              if anbima_opts else [])

st.sidebar.markdown("---")
_cnpj_raw = st.sidebar.text_area(
    "📋 CNPJs para monitorar",
    value="",
    height=120,
    placeholder="Cole um CNPJ por linha (com ou sem formatação):\n29.983.683/0001-26\n09195235000150\n...",
    help="Filtra apenas os fundos cujos CNPJs estejam nesta lista. Aceita formato XX.XXX.XXX/XXXX-XX ou 14 dígitos.",
)

import re as _re_cnpj

def _norm_cnpj(s: str) -> str:
    d = _re_cnpj.sub(r"\D", "", s)
    if not d:
        return ""
    d = d.zfill(14)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}" if len(d) >= 14 else ""

_cnpj_sep = _re_cnpj.split(r"[\n,;]+", _cnpj_raw.strip())
sel_cnpjs: set[str] = {c for raw in _cnpj_sep if (c := _norm_cnpj(raw.strip()))}

st.sidebar.markdown("---")
# FIDC-IE: a CVM não publica esse campo; identificação por palavras-chave no nome
_PAT_INFRA = _re_cnpj.compile(
    r"\bINFRAESTRUTURA\b|\bINFRA\b|SANEAMENTO|RODOVIA|FERROVIA|"
    r"AEROPORTO|\bPORTO\b|TRANSMISS|\bENERGIA\b|HIDRELET|ESGOTO|"
    r"FIDC[\s\-]IE\b",
    _re_cnpj.IGNORECASE,
)
_infra_opts = ["Todos", "Infraestrutura (IE)", "Não Infraestrutura"]
sel_infra = st.sidebar.radio(
    "Segmento Infra",
    _infra_opts,
    index=0,
)
if sel_infra != "Todos":
    st.sidebar.warning(
        "⚠️ **Classificação aproximada.** A CVM não publica FIDC-IE como campo "
        "estruturado. A segmentação é feita por palavras-chave no nome do fundo "
        "(INFRAESTRUTURA, SANEAMENTO, ENERGIA, RODOVIA, PORTO etc.) e pode não "
        "refletir com precisão a classificação regulatória oficial."
    )

st.sidebar.markdown("---")
# Fundos de cota única: apenas 1 classe de senioridade no histórico de cotas
@st.cache_data(show_spinner=False)
def _cnpjs_cota_unica(dfc: pd.DataFrame) -> frozenset[str]:
    if dfc.empty or "senioridade" not in dfc.columns:
        return frozenset()
    ativos = dfc[dfc["nr_cotistas"] > 0] if "nr_cotistas" in dfc.columns else dfc
    n_classes = ativos.groupby("cnpj")["senioridade"].nunique()
    return frozenset(n_classes[n_classes == 1].index)

_cota_unica_cnpjs = _cnpjs_cota_unica(dfc)
sel_excl_unica = st.sidebar.checkbox(
    "Excluir FIDCs de cota única",
    value=False,
    help=(
        "Remove fundos que têm apenas uma classe de cota (geralmente 'Subordinada' única). "
        f"São {len(_cota_unica_cnpjs):,} fundos ({len(_cota_unica_cnpjs)/max(dfc['cnpj'].nunique(),1):.0%} do total). "
        "Útil para focar na análise de sênior/mezanino vs subordinada."
    ),
)

st.sidebar.markdown("---")
# Perfil do fundo (aprox.): distressed/NPL e ações judiciais/precatórios.
# Combina sinais estruturados da carteira (% judicial, % inadimplência) com
# palavras-chave no nome. Aproximado — a CVM não publica esse rótulo.
_PAT_JUDICIAL = _re_cnpj.compile(
    r"JUDICIAL|PRECAT|LITIG|JURID|HONORAR", _re_cnpj.IGNORECASE)
_PAT_DISTRESSED = _re_cnpj.compile(
    r"\bNPL\b|RECUPERA|INADIMPL|DISTRESS|REESTRUTUR|SPECIAL\s+SITUATION",
    _re_cnpj.IGNORECASE)


@st.cache_data(show_spinner=False)
def _classifica_perfil(d: pd.DataFrame) -> dict:
    """Classifica cada CNPJ (na última competência) como distressed e/ou judicial."""
    if d.empty or "cnpj" not in d.columns:
        return {"distressed": frozenset(), "judicial": frozenset()}
    last = d.sort_values("dt_comptc").groupby("cnpj").tail(1).copy()
    nome = last["denom_social"].astype(str)
    seg_cols = [c for c in last.columns if c.startswith("seg_")]
    seg_total = (last[seg_cols].sum(axis=1) if seg_cols
                 else pd.Series(0.0, index=last.index))
    pct_jud = last.get("seg_judicial", 0) / seg_total.where(seg_total > 0)
    judicial = (pct_jud > 0.10).fillna(False) | nome.str.contains(_PAT_JUDICIAL, na=False)
    base = last["vl_dircred"].where(last["vl_dircred"] > 0, last["vl_carteira"])
    base = base.where(base > 0)
    pct_inad = last["vl_inadimplente"] / base
    pct_credinad = (last["vl_cred_inad"] / base
                    if "vl_cred_inad" in last.columns else pct_inad * 0)
    distressed = ((pct_inad > 0.50).fillna(False) | (pct_credinad > 0.50).fillna(False)
                  | nome.str.contains(_PAT_DISTRESSED, na=False))
    return {"distressed": frozenset(last.loc[distressed, "cnpj"]),
            "judicial": frozenset(last.loc[judicial, "cnpj"])}


_perfil = _classifica_perfil(df)
cb_distressed = st.sidebar.checkbox(
    f"💥 Distressed / NPL ({len(_perfil['distressed'])})", value=False,
    help="Fundos com alta inadimplência na carteira (>50%) ou nome indicando "
         "NPL / recuperação / distressed. Classificação aproximada.")
cb_judicial = st.sidebar.checkbox(
    f"⚖️ Ações judiciais / Precatórios ({len(_perfil['judicial'])})", value=False,
    help="Fundos com segmento judicial relevante na carteira (>10%) ou nome "
         "indicando precatório / judicial. Classificação aproximada.")
_perfil_cnpjs = frozenset()
if cb_distressed:
    _perfil_cnpjs |= _perfil["distressed"]
if cb_judicial:
    _perfil_cnpjs |= _perfil["judicial"]
_perfil_ativo = cb_distressed or cb_judicial

st.sidebar.caption("💡 Clique numa barra do ranking de administradores para cruzar o painel.")

# --------------------------------------------------------------------------- #
# Barra de slicers (topo) — feel responsivo tipo Power BI
# --------------------------------------------------------------------------- #
st.markdown(
    "<h1>📊 FIDC Analytics "
    "<span style='font-size:.85em;font-weight:400;color:#667085'>"
    "— mercado brasileiro de Direitos Creditórios</span></h1>",
    unsafe_allow_html=True,
)

with st.container():
    st.markdown("<div class='slicer-box'>", unsafe_allow_html=True)
    s1, s2, s3 = st.columns([1.1, 1.1, 1.6])
    with s1:
        tipos = sorted(df["tp_fundo_classe"].dropna().unique().tolist())
        sel_tipo = st.segmented_control("Tipo", tipos, selection_mode="multi",
                                        default=tipos, key="sl_tipo") or tipos
    with s2:
        sen_opts = ([s for s in C.ORDEM_SENIORIDADE if s in dfc["senioridade"].unique()]
                    if not dfc.empty else [])
        sel_sen = st.segmented_control("Senioridade (cotas)", sen_opts, selection_mode="multi",
                                       default=sen_opts, key="sl_sen") or sen_opts
    with s3:
        meses = sorted(m.to_pydatetime() for m in df["dt_comptc"].unique()
                       if periodo[0] <= m.to_pydatetime() <= periodo[1])
        ref_dt = st.select_slider(
            "📅 Competência de referência (snapshots)", options=meses,
            value=meses[-1], format_func=lambda d: d.strftime("%m/%Y"), key="sl_ref")
    st.markdown("</div>", unsafe_allow_html=True)

ref_month = pd.Timestamp(ref_dt)

# --------------------------------------------------------------------------- #
# Cross-filter: administrador (clique no ranking)
# --------------------------------------------------------------------------- #
xf_admin = st.session_state.get("xf_admin")


def aplica(d: pd.DataFrame) -> pd.DataFrame:
    m = (d["dt_comptc"] >= pd.Timestamp(periodo[0])) & (d["dt_comptc"] <= pd.Timestamp(periodo[1]))
    if busca:
        m &= d["denom_social"].str.contains(busca, case=False, na=False)
    if sel_tipo and "tp_fundo_classe" in d:
        m &= d["tp_fundo_classe"].isin(sel_tipo)
    if sel_condom and "condom" in d:
        m &= d["condom"].isin(sel_condom)
    if sel_excl and "fundo_exclusivo" in d:
        m &= d["fundo_exclusivo"].isin(sel_excl)
    if sel_adm and "admin" in d:
        m &= d["admin"].isin(sel_adm)
    if sel_gest and "gestor" in d.columns:
        m &= d["gestor"].isin(sel_gest)
    if sel_anbima and "classe_anbima" in d.columns:
        m &= d["classe_anbima"].isin(sel_anbima)
    if sel_cnpjs and "cnpj" in d.columns:
        m &= d["cnpj"].isin(sel_cnpjs)
    if sel_infra != "Todos" and "denom_social" in d.columns:
        is_infra = d["denom_social"].str.contains(_PAT_INFRA, na=False)
        m &= is_infra if sel_infra == "Infraestrutura (IE)" else ~is_infra
    if sel_excl_unica and _cota_unica_cnpjs and "cnpj" in d.columns:
        m &= ~d["cnpj"].isin(_cota_unica_cnpjs)
    if _perfil_ativo and "cnpj" in d.columns:
        m &= d["cnpj"].isin(_perfil_cnpjs)
    if xf_admin and "admin" in d:
        m &= d["admin"] == xf_admin
    return d[m]


dff = aplica(df)
dffc_full = aplica(dfc) if not dfc.empty else pd.DataFrame()
dffc = dffc_full[dffc_full["senioridade"].isin(sel_sen)] if not dffc_full.empty else dffc_full

# Chips de filtros ativos
chips = []
if busca:
    chips.append(f"nome ⊇ '{busca}'")
if xf_admin:
    chips.append(f"administrador = {xf_admin}")
if sel_adm:
    chips.append(f"adm: {len(sel_adm)} selec.")
if sel_gest:
    chips.append(f"gestor: {', '.join(sel_gest[:2])}" + (" …" if len(sel_gest) > 2 else ""))
if sel_anbima:
    chips.append(f"anbima: {', '.join(sel_anbima[:2])}" + (" …" if len(sel_anbima) > 2 else ""))
if sel_cnpjs:
    chips.append(f"📋 {len(sel_cnpjs)} CNPJ(s) monitorado(s)")
if sel_infra != "Todos":
    chips.append(sel_infra)
if sel_excl_unica:
    chips.append("excl. cota única")
cinfo, cbtn = st.columns([6, 1])
with cinfo:
    from zoneinfo import ZoneInfo
    _brt = ZoneInfo("America/Sao_Paulo")
    atual = datetime.fromtimestamp(config.CONSOLIDADO.stat().st_mtime, tz=_brt).strftime("%d/%m/%Y %H:%M")
    st.caption(f"Fonte: Dados Abertos CVM · ref. **{ref_month:%m/%Y}** · "
               f"atualizado em {atual}" +
               ("&nbsp;&nbsp;" + " ".join(f"<span class='chip'>{c}</span>" for c in chips)
                if chips else ""), unsafe_allow_html=True)
with cbtn:
    if (xf_admin or chips) and st.button("✖ Limpar", width="stretch"):
        st.session_state.pop("xf_admin", None)
        st.session_state["xf_key"] = st.session_state.get("xf_key", 0) + 1
        st.rerun()

if dff.empty:
    st.warning("Nenhum registro com os filtros selecionados.")
    st.stop()

# --------------------------------------------------------------------------- #
# Séries agregadas + estrutura de senioridade
# --------------------------------------------------------------------------- #
agg = dff.groupby("dt_comptc").agg(
    pl=("vl_pl", "sum"), ativo=("vl_ativo", "sum"), dircred=("vl_dircred", "sum"),
    venc_inad=("vl_venc_inad", "sum"), pdd=("vl_pdd", "sum"), n=("cnpj", "nunique"),
).reset_index()
agg["inad_pct"] = (agg["venc_inad"] / agg["dircred"]).where(agg["dircred"] > 0)
agg["pdd_pct"] = (agg["pdd"].abs() / agg["dircred"]).where(agg["dircred"] > 0)

if not dffc_full.empty:
    pivot_sen = (dffc_full.groupby(["dt_comptc", "senioridade"])["pl_aloc"].sum()
                 .unstack(fill_value=0))
    sub_cols = [c for c in ["Subordinada", "Mezanino"] if c in pivot_sen]
    agg = agg.merge((pivot_sen[sub_cols].sum(axis=1) / pivot_sen.sum(axis=1))
                    .rename("subord_pct"), left_on="dt_comptc", right_index=True, how="left")
    flow_cols = [c for c in ["captacao", "resgate"] if c in dffc_full.columns]
    if flow_cols:
        fl = dffc_full.groupby("dt_comptc")[flow_cols].sum()
        fl["capt_liq"] = fl.get("captacao", 0) - fl.get("resgate", 0)
        agg = agg.merge(fl["capt_liq"].reset_index(), on="dt_comptc", how="left")


def linha_ref(a, dt):
    """Linha do mês de referência e a anterior (para deltas)."""
    a = a.sort_values("dt_comptc").reset_index(drop=True)
    idx = a.index[a["dt_comptc"] == dt]
    i = int(idx[0]) if len(idx) else len(a) - 1
    return a.iloc[i], (a.iloc[i - 1] if i > 0 else a.iloc[i])


cur, prev = linha_ref(agg, ref_month)

# Aviso de mês parcial
_cont = df.groupby("dt_comptc")["cnpj"].nunique()
if ref_month == comp_max and len(_cont) > 1 and _cont.iloc[-1] < 0.85 * _cont.iloc[-2]:
    st.info(f"⚠️ A competência **{comp_max:%m/%Y}** parece parcial "
            f"({_cont.iloc[-1]} vs {_cont.iloc[-2]} fundos) — dentro do prazo de entrega à CVM.")

# --------------------------------------------------------------------------- #
# KPI cards
# --------------------------------------------------------------------------- #
kpis = [
    card("Patrimônio Líquido", fmt_bi(cur["pl"]), delta_val(cur["pl"], prev["pl"])),
    card("Fundos / Classes", fmt_int(cur["n"]),
         f"<p class='kpi-delta {'up' if cur['n']>=prev['n'] else 'down'}'>"
         f"{'▲' if cur['n']>=prev['n'] else '▼'} {int(abs(cur['n']-prev['n']))}</p>"),
    card("Inadimplência", fmt_pct(cur["inad_pct"]),
         delta_pp(cur["inad_pct"], prev["inad_pct"], inverse=True)),
    card("Subordinação", fmt_pct(cur.get("subord_pct")),
         delta_pp(cur.get("subord_pct"), prev.get("subord_pct"))),
    card("Captação líq. (mês)", fmt_bi(cur.get("capt_liq"))),
]
for col, html in zip(st.columns(len(kpis)), kpis):
    col.markdown(html, unsafe_allow_html=True)
st.write("")

# --------------------------------------------------------------------------- #
# Abas
# --------------------------------------------------------------------------- #
T = st.tabs(["📈 Mercado", "🏗️ Estrutura de Cotas", "⚠️ Risco", "💰 Rentab. & Fluxo",
             "🧩 Carteira", "💼 Portfólio CDA", "🏆 Rankings", "🔎 Fundo", "👥 Investidores",
             "🚨 Alertas", "📊 Qualidade", "🗺️ Cedentes", "📋 Dados"])

with T[0]:
    c1, c2 = st.columns(2)
    fig = go.Figure()
    fig.add_bar(x=agg["dt_comptc"], y=agg["pl"] / 1e9, name="PL (R$ bi)", marker_color=ACCENT)
    fig.add_scatter(x=agg["dt_comptc"], y=agg["ativo"] / 1e9, name="Ativo (R$ bi)",
                    line=dict(color="#90A4AE", width=2))
    fig.add_vline(x=ref_month, line_dash="dot", line_color="#C62828")
    c1.plotly_chart(style_fig(fig).update_layout(title="PL e Ativo total"),
                    width="stretch")
    fig2 = px.line(agg, x="dt_comptc", y="n", title="Nº de fundos/classes ativos")
    fig2.update_traces(line_color=CORES[2])
    fig2.add_vline(x=ref_month, line_dash="dot", line_color="#C62828")
    c2.plotly_chart(style_fig(fig2), width="stretch")
    fonte("Tab. I (ativo) e Tab. IV (PL), agregados por competência.")

with T[1]:
    if dffc_full.empty:
        st.info("Base de cotas indisponível.")
    else:
        c1, c2 = st.columns([2, 1])
        evol = dffc_full.groupby(["dt_comptc", "senioridade"])["pl_aloc"].sum().reset_index()
        figa = px.area(evol, x="dt_comptc", y="pl_aloc", color="senioridade",
                       color_discrete_map=COR_SEN, title="Evolução do PL por senioridade (R$)")
        figa.add_vline(x=ref_month, line_dash="dot", line_color="#101828")
        c1.plotly_chart(style_fig(figa, 360), width="stretch")
        ultm = dffc_full[dffc_full["dt_comptc"] == ref_month]
        pie = ultm.groupby("senioridade")["pl_aloc"].sum().reset_index()
        figp = px.pie(pie, values="pl_aloc", names="senioridade", hole=0.55,
                      color="senioridade", color_discrete_map=COR_SEN,
                      title=f"Composição ({ref_month:%m/%Y})")
        c2.plotly_chart(style_fig(figp, 360).update_layout(hovermode=None),
                        width="stretch")
        sub = (dffc_full[dffc_full.senioridade.isin(["Subordinada", "Mezanino"])]
               .groupby("dt_comptc")["pl_aloc"].sum())
        tot = dffc_full.groupby("dt_comptc")["pl_aloc"].sum()
        figs = px.line((sub / tot * 100).rename("s").reset_index(), x="dt_comptc", y="s",
                       title="Razão de subordinação do mercado (%)")
        figs.update_traces(line_color=COR_SEN["Subordinada"])
        figs.update_layout(yaxis_ticksuffix="%")
        st.plotly_chart(style_fig(figs, 280), width="stretch")
        st.caption("Subordinação = (Subordinada+Mezanino)/PL — colchão que protege a cota sênior.")
        fonte("Tab. X (séries/cotas por senioridade) e Tab. IV (PL rateado).")

with T[2]:
    c1, c2 = st.columns(2)
    figr = go.Figure()
    figr.add_scatter(x=agg["dt_comptc"], y=agg["inad_pct"] * 100, name="Inadimplência %",
                     line=dict(color="#C62828"))
    figr.add_scatter(x=agg["dt_comptc"], y=agg["pdd_pct"] * 100, name="PDD/Carteira %",
                     line=dict(color="#F9A825"))
    figr.update_layout(title="Inadimplência e Provisão (% da carteira)", yaxis_ticksuffix="%")
    c1.plotly_chart(style_fig(figr), width="stretch")
    rating_cols = [c for c in C.TAB_X_RATING if c in dff.columns]
    ultf = dff[dff["dt_comptc"] == ref_month]
    rat = (ultf[rating_cols].sum().rename(lambda x: x.replace("rating_", "").upper())
           if rating_cols else pd.Series(dtype=float))
    if rat.sum() > 0:
        figrt = px.bar(rat[rat > 0] / 1e9, title=f"Carteira por rating SCR ({ref_month:%m/%Y}) — R$ bi",
                       color_discrete_sequence=[CORES[5]])
        c2.plotly_chart(style_fig(figrt).update_layout(showlegend=False, hovermode=None),
                        width="stretch")
    else:
        c2.info("Rating SCR disponível só a partir de 2023 (Res. CVM 175).")
    ag = {l: ultf[c].sum() for c, l in {"vl_avencer": "A vencer", "vl_inadimplente": "Inadimplente",
          "vl_antecipado": "Antecipado"}.items() if c in ultf}
    if any(ag.values()):
        figag = px.bar(x=list(ag), y=[v / 1e9 for v in ag.values()], color=list(ag),
                       title=f"Direitos creditórios por situação ({ref_month:%m/%Y}) — R$ bi",
                       color_discrete_sequence=[COR_SEN["Sênior"], COR_SEN["Subordinada"], "#90A4AE"])
        st.plotly_chart(style_fig(figag, 280).update_layout(showlegend=False, hovermode=None),
                        width="stretch")
        fonte("Inadimplência/PDD: Tab. I.2 (vencidos e provisão). Rating SCR: Tab. X "
              "(Res. CVM 175, ≥2023). Situação dos DC: Tab. V.")

    # Concentração de cedentes (risco de contraparte)
    if "cedente_top1_pct" in ultf.columns:
        conc = ultf["cedente_top1_pct"].dropna()
        if len(conc):
            st.markdown("##### Concentração de cedentes (risco de contraparte)")
            cc1, cc2 = st.columns([2, 1])
            figh = px.histogram(conc, nbins=20, color_discrete_sequence=[CORES[3]],
                                title=f"Distribuição da participação do maior cedente ({ref_month:%m/%Y})")
            figh.update_layout(xaxis_ticksuffix="%", xaxis_title="% no maior cedente",
                               yaxis_title="nº de fundos", bargap=0.05)
            cc1.plotly_chart(style_fig(figh).update_layout(hovermode=None), width="stretch")
            with cc2:
                st.metric("Fundos que reportam cedentes", fmt_int(len(conc)))
                st.metric("Maior cedente — mediana", f"{conc.median():.1f}%".replace(".", ","))
                st.metric("Mono-cedente (≥90%)", fmt_int(int((conc >= 90).sum())))
                top5 = ultf["cedente_top5_pct"].dropna()
                if len(top5):
                    st.metric("5 maiores — mediana", f"{top5.median():.1f}%".replace(".", ","))
            st.caption("Quanto maior a participação de um único cedente, maior o risco de "
                       "contraparte/originação. Disponível para os fundos que listam cedentes na Tab. I.")
            fonte("Tab. I.2.A.12 / I.2.B.12 (percentuais dos maiores cedentes). "
                  "Veja a aba 🗺️ Cedentes para o mapa por cedente nomeado.")

with T[3]:
    if dffc.empty:
        st.info("Base de cotas indisponível.")
    else:
        cdi = carregar_cdi()
        ipca = carregar_ipca()
        selic = carregar_selic()
        # Só séries com rentabilidade REPORTADA (0 = não informado puxa a mediana p/ baixo)
        rdf = dffc[dffc["rentab_mes"].notna() & (dffc["rentab_mes"] != 0)].copy()
        rdf["rc"] = rdf["rentab_mes"].clip(-50, 50)
        rmed = rdf.groupby(["dt_comptc", "senioridade"])["rc"].median().reset_index()
        figr = px.line(rmed, x="dt_comptc", y="rc", color="senioridade",
                       color_discrete_map=COR_SEN,
                       title="Rentabilidade mensal mediana por senioridade vs benchmarks (%)")
        def _add_benchmark(fig, bench_df, col, label, color, dash="dash"):
            if bench_df.empty:
                return
            b = bench_df.copy()
            b["dt"] = pd.PeriodIndex(b["competencia"], freq="M").to_timestamp(how="end").normalize()
            b = b[(b["dt"] >= rmed["dt_comptc"].min()) & (b["dt"] <= rmed["dt_comptc"].max())]
            fig.add_scatter(x=b["dt"], y=b[col], name=label, mode="lines",
                            line=dict(color=color, dash=dash, width=2))
        _add_benchmark(figr, cdi, "cdi_mes", "CDI", "#101828")
        _add_benchmark(figr, selic, "selic_mes", "SELIC", "#455A64", "dot")
        _add_benchmark(figr, ipca, "ipca_mes", "IPCA", "#E65100", "dashdot")
        figr.update_layout(yaxis_ticksuffix="%")
        st.plotly_chart(style_fig(figr), width="stretch")

        # Excesso de retorno da cota sênior vs CDI e IPCA
        if not cdi.empty:
            sen = rmed[rmed["senioridade"] == "Sênior"].copy()
            sen["competencia"] = sen["dt_comptc"].dt.to_period("M").astype(str)
            sen = sen.merge(cdi, on="competencia", how="left")
            if not ipca.empty:
                sen = sen.merge(ipca, on="competencia", how="left")
            if not selic.empty:
                sen = sen.merge(selic, on="competencia", how="left")
            sen["excesso_cdi"] = sen["rc"] - sen["cdi_mes"]
            sen = sen.dropna(subset=["excesso_cdi"])
            if not sen.empty:
                m1, m2, m3 = st.columns(3)
                exc12 = sen["excesso_cdi"].tail(12).mean()
                m1.metric("Excesso vs CDI (12m)",
                          f"{exc12:+.2f} p.p./mês".replace(".", ","))
                if "ipca_mes" in sen.columns:
                    sen["excesso_ipca"] = sen["rc"] - sen["ipca_mes"]
                    exc_ipca = sen["excesso_ipca"].tail(12).mean()
                    m2.metric("Excesso vs IPCA (12m)",
                              f"{exc_ipca:+.2f} p.p./mês".replace(".", ","))
                if "selic_mes" in sen.columns:
                    sen["excesso_selic"] = sen["rc"] - sen["selic_mes"]
                    exc_selic = sen["excesso_selic"].tail(12).mean()
                    m3.metric("Excesso vs SELIC (12m)",
                              f"{exc_selic:+.2f} p.p./mês".replace(".", ","))
                figx = go.Figure(go.Bar(
                    x=sen["dt_comptc"], y=sen["excesso_cdi"],
                    marker_color=[COR_SEN["Sênior"] if v >= 0 else COR_SEN["Subordinada"]
                                  for v in sen["excesso_cdi"]]))
                figx.add_hline(y=0, line_color="#667085")
                figx.update_layout(title="Excesso de retorno da cota sênior vs CDI (p.p./mês)",
                                   yaxis_ticksuffix=" pp")
                st.plotly_chart(style_fig(figx, 260), width="stretch")

        flx = dffc_full.groupby("dt_comptc").agg(
            captacao=("captacao", "sum"), resgate=("resgate", "sum")).reset_index()
        figf = go.Figure()
        figf.add_bar(x=flx["dt_comptc"], y=flx["captacao"] / 1e9, name="Captações",
                     marker_color=COR_SEN["Sênior"])
        figf.add_bar(x=flx["dt_comptc"], y=-flx["resgate"] / 1e9, name="Resgates",
                     marker_color=COR_SEN["Subordinada"])
        figf.add_scatter(x=flx["dt_comptc"], y=(flx["captacao"] - flx["resgate"]) / 1e9,
                         name="Líquido", line=dict(color="#101828", width=2))
        figf.update_layout(title="Captações × Resgates (R$ bi)", barmode="relative")
        st.plotly_chart(style_fig(figf), width="stretch")
        st.caption("Rentabilidade = mediana das séries que reportam (exclui 0 = não informado), "
                   "clip ±50%/mês. CDI mensal: BACEN/SGS série 4391.")
        fonte("Rentabilidade/fluxo: Tab. X.3 e X.4 (CVM). Benchmarks CDI/SELIC/IPCA: "
              "BACEN/SGS séries 4391/4189/433.")

with T[4]:
    seg_cols = [c for c in C.ROTULOS_SEGMENTO if c in dff.columns]
    ultf = dff[dff["dt_comptc"] == ref_month]
    if seg_cols:
        cs = ultf[seg_cols].sum().rename(index=C.ROTULOS_SEGMENTO).sort_values()
        cs = cs[cs > 0]
        figc = px.bar(cs / 1e9, orientation="h", color_discrete_sequence=[ACCENT],
                      title=f"Carteira por segmento ({ref_month:%m/%Y}) — R$ bi")
        st.plotly_chart(style_fig(figc, 360).update_layout(showlegend=False, hovermode=None),
                        width="stretch")
        evs = dff.groupby("dt_comptc")[seg_cols].sum().rename(columns=C.ROTULOS_SEGMENTO) / 1e9
        fige = px.area(evs, title="Evolução por segmento (R$ bi)", color_discrete_sequence=CORES)
        st.plotly_chart(style_fig(fige), width="stretch")
        fonte("Tab. II — carteira de direitos creditórios por segmento de atividade do cedente.")

with T[5]:  # 💼 Portfólio CDA
    st.markdown("#### Composição de Carteira por Tipo de Instrumento (CDA/CVM)")
    st.caption(
        "Fonte: Composição e Diversificação de Aplicações (CDA) — Portal Dados Abertos CVM. "
        "Mostra o que cada FIDC detém além dos direitos creditórios (reservas, títulos, cotas etc.)."
    )
    if dfcart.empty:
        st.info("Dados de carteira CDA não disponíveis. Rode `python -m fidc.pipeline` para gerar.")
    else:
        # Filtrar pelo universo de CNPJs do filtro ativo
        cnpjs_filtro = set(dff["cnpj"].unique())
        cart_f = dfcart[dfcart["cnpj"].isin(cnpjs_filtro)] if cnpjs_filtro else dfcart

        # Visão agregada — período de referência
        ref_comp = ref_month.to_period("M").strftime("%Y-%m")
        cart_ref = cart_f[cart_f["competencia"] == ref_comp]

        if cart_ref.empty:
            # Usa competência mais próxima disponível
            comps = sorted(cart_f["competencia"].unique())
            if comps:
                ref_comp = comps[-1]
                cart_ref = cart_f[cart_f["competencia"] == ref_comp]
            if cart_ref.empty:
                st.info("Sem dados de CDA para o período selecionado.")
                st.stop()

        c1, c2 = st.columns([2, 1])
        # Agregado por TP_APLIC
        agg_aplic = (cart_ref.groupby("tp_aplic")["vl_posicao"].sum()
                     .sort_values(ascending=False))
        agg_aplic = agg_aplic[agg_aplic > 0]
        if not agg_aplic.empty:
            fig_aplic = px.bar(
                agg_aplic / 1e9,
                orientation="h",
                title=f"Carteira por tipo de aplicação — {ref_comp} (R$ bi)",
                color_discrete_sequence=[ACCENT],
            )
            c1.plotly_chart(
                style_fig(fig_aplic, 380).update_layout(showlegend=False, hovermode=None),
                width="stretch",
            )
            total = agg_aplic.sum()
            pie_df = agg_aplic.reset_index()
            pie_df.columns = ["Tipo", "Valor"]
            fig_pie = px.pie(
                pie_df, values="Valor", names="Tipo", hole=0.5,
                title="Participação (%)",
                color_discrete_sequence=CORES,
            )
            c2.plotly_chart(
                style_fig(fig_pie, 380).update_layout(hovermode=None),
                width="stretch",
            )

        # Evolução temporal do mix de carteira
        evol_cart = (cart_f.groupby(["competencia", "tp_aplic"])["vl_posicao"]
                     .sum().reset_index())
        # Manter apenas top-8 tipos por volume total
        top_tipos = (evol_cart.groupby("tp_aplic")["vl_posicao"].sum()
                     .sort_values(ascending=False).head(8).index.tolist())
        evol_cart = evol_cart[evol_cart["tp_aplic"].isin(top_tipos)]
        if not evol_cart.empty:
            evol_cart["dt"] = pd.PeriodIndex(evol_cart["competencia"], freq="M").to_timestamp()
            fig_evol = px.area(
                evol_cart, x="dt", y="vl_posicao", color="tp_aplic",
                title="Evolução da composição de carteira CDA (R$)",
                color_discrete_sequence=CORES,
            )
            st.plotly_chart(style_fig(fig_evol, 300), width="stretch")

        # Top FIDCs na CDA por volume
        top_fdcs = (cart_ref.groupby("cnpj")["vl_posicao"].sum()
                    .sort_values(ascending=False).head(15).reset_index())
        top_fdcs = top_fdcs.merge(
            dff[["cnpj", "denom_social"]].drop_duplicates("cnpj"), on="cnpj", how="left")
        if not top_fdcs.empty:
            st.markdown(f"##### Top 15 FIDCs por posição CDA ({ref_comp})")
            top_fdcs["PL CDA (R$ mi)"] = (top_fdcs["vl_posicao"] / 1e6).round(1)
            st.dataframe(
                top_fdcs[["denom_social", "PL CDA (R$ mi)"]].rename(
                    columns={"denom_social": "Fundo/Classe"}),
                width="stretch", hide_index=True,
            )
        fonte("Composição e Diversificação de Aplicações (CDA) — Portal de Dados Abertos da CVM.",
              base="CDA/CVM")

with T[6]:
    ultf = dff[dff["dt_comptc"] == ref_month]
    _rk_tabs = st.tabs(["Administradores", "Gestores", "Classe ANBIMA", "Maiores Fundos"])

    with _rk_tabs[0]:
        if "admin" in ultf.columns:
            rk = (ultf.groupby("admin").agg(pl=("vl_pl", "sum"), fundos=("cnpj", "nunique"))
                  .sort_values("pl", ascending=False).head(15).reset_index())
            figrk = px.bar(rk.sort_values("pl"), x="pl", y="admin", orientation="h",
                           title=f"Top 15 administradores por PL ({ref_month:%m/%Y}) — clique p/ filtrar",
                           color_discrete_sequence=[ACCENT])
            figrk.update_layout(showlegend=False, hovermode=None, xaxis_title="PL (R$)")
            key = f"xf_admin_chart_{st.session_state.get('xf_key', 0)}"
            ev = st.plotly_chart(style_fig(figrk, 420), width="stretch",
                                 on_select="rerun", key=key)
            try:
                sel = (ev.get("selection") if isinstance(ev, dict) else None) or {}
                pts = sel.get("points") or []
                novo = pts[0].get("y") if pts else None
                if novo and novo != xf_admin:
                    st.session_state["xf_admin"] = novo
                    st.rerun()
            except Exception:
                pass

    with _rk_tabs[1]:
        if "gestor" in ultf.columns:
            rkg = (ultf.dropna(subset=["gestor"])
                   .groupby("gestor").agg(pl=("vl_pl", "sum"), fundos=("cnpj", "nunique"))
                   .sort_values("pl", ascending=False).head(15).reset_index())
            if not rkg.empty:
                figg = px.bar(rkg.sort_values("pl"), x="pl", y="gestor", orientation="h",
                              title=f"Top 15 gestores por PL ({ref_month:%m/%Y})",
                              color_discrete_sequence=[CORES[2]])
                figg.update_layout(showlegend=False, hovermode=None, xaxis_title="PL (R$)")
                st.plotly_chart(style_fig(figg, 420), width="stretch")
                st.dataframe(rkg.assign(pl=lambda d: (d["pl"] / 1e9).round(2))
                             .rename(columns={"gestor": "Gestor", "pl": "PL (R$ bi)",
                                              "fundos": "Nº Fundos"}),
                             width="stretch", hide_index=True)
            else:
                st.info("Dados de gestor não disponíveis. Rode o pipeline para enriquecer.")
        else:
            st.info("Dados de gestor não disponíveis. Rode o pipeline para enriquecer.")

    with _rk_tabs[2]:
        if "classe_anbima" in ultf.columns:
            rka = (ultf.dropna(subset=["classe_anbima"])
                   .groupby("classe_anbima").agg(pl=("vl_pl", "sum"), fundos=("cnpj", "nunique"))
                   .sort_values("pl", ascending=False).reset_index())
            if not rka.empty:
                figa = px.bar(rka.sort_values("pl").tail(20), x="pl", y="classe_anbima",
                              orientation="h",
                              title=f"PL por Classe ANBIMA ({ref_month:%m/%Y})",
                              color_discrete_sequence=[CORES[4]])
                figa.update_layout(showlegend=False, hovermode=None, xaxis_title="PL (R$)")
                st.plotly_chart(style_fig(figa, 480), width="stretch")
            else:
                st.info("Classificação ANBIMA não disponível. Rode o pipeline para enriquecer.")
        else:
            st.info("Classificação ANBIMA não disponível. Rode o pipeline para enriquecer.")

    with _rk_tabs[3]:
        rkf = (ultf.groupby("denom_social").agg(pl=("vl_pl", "sum"),
               inad=("vl_venc_inad", "sum"), dc=("vl_dircred", "sum")).reset_index())
        rkf["inad_pct"] = (rkf["inad"] / rkf["dc"]).where(rkf["dc"] > 0)
        st.subheader(f"Maiores fundos por PL ({ref_month:%m/%Y})")
        st.caption("Selecione uma linha para abrir o **drill-through** no deep-dive do fundo.")
        rkt = (rkf.sort_values("pl", ascending=False).head(30)
               .assign(pl=lambda d: (d["pl"] / 1e6).round(1))
               .rename(columns={"denom_social": "Fundo/Classe", "pl": "PL (R$ mi)",
                                "inad_pct": "Inad. %"})[["Fundo/Classe", "PL (R$ mi)", "Inad. %"]]
               .reset_index(drop=True))
        evr = st.dataframe(rkt.style.format({"Inad. %": "{:.2%}"}), width="stretch",
                           hide_index=True, on_select="rerun", selection_mode="single-row",
                           key="rk_tbl")
        try:
            linhas = (evr.get("selection", {}) if isinstance(evr, dict) else {}).get("rows", [])
            if linhas:
                fundo_drill = rkt.iloc[linhas[0]]["Fundo/Classe"]
                st.success(f"**{fundo_drill}** selecionado.")
                if st.button(f"🔎 Abrir deep-dive de «{fundo_drill[:60]}»", type="primary"):
                    st.session_state["ddfundo"] = fundo_drill
                    st.rerun()
        except Exception:
            pass
    fonte(f"PL: Tab. IV; inadimplência: Tab. I.2; ref. {ref_month:%m/%Y}. "
          "Gestor e Classe ANBIMA: Cadastro de Fundos da CVM (cad_fi).")

with T[7]:
    universo = sorted(dff["denom_social"].dropna().unique().tolist())
    if not universo:
        st.info("Nenhum fundo no filtro atual.")
    else:
        st.caption(f"{len(universo)} fundos no filtro. Use a busca por nome na barra lateral, "
                   "ou clique numa linha do ranking (aba 🏆) para chegar aqui.")
        # Se veio um fundo do drill-through e ele ainda está no universo, pré-seleciona.
        if st.session_state.get("ddfundo") not in universo:
            st.session_state.pop("ddfundo", None)
        escolha = st.selectbox("Fundo/Classe", universo, key="ddfundo")
        fsel = df[df["denom_social"] == escolha].sort_values("dt_comptc")
        csel = dfc[dfc["denom_social"] == escolha].sort_values("dt_comptc") if not dfc.empty else pd.DataFrame()
        u = fsel.iloc[-1]
        st.markdown(f"#### {escolha}")
        inad = (u["vl_venc_inad"] / u["vl_dircred"]) if u["vl_dircred"] else 0
        cu = csel[csel["dt_comptc"] == u["dt_comptc"]] if not csel.empty else pd.DataFrame()
        sub = cu[cu.senioridade.isin(["Subordinada", "Mezanino"])]["pl_aloc"].sum() if not cu.empty else 0
        tot = cu["pl_aloc"].sum() if not cu.empty else 0
        cot = int(cu["nr_cotistas"].fillna(0).sum()) if not cu.empty else 0
        cards_f = [card("PL", fmt_bi(u["vl_pl"])), card("Ativo", fmt_bi(u["vl_ativo"])),
                   card("Inadimplência", fmt_pct(inad)),
                   card("Subordinação", fmt_pct(sub / tot if tot else 0)),
                   card("Cotistas", fmt_int(cot))]
        for col, h in zip(st.columns(5), cards_f):
            col.markdown(h, unsafe_allow_html=True)
        ced = u.get("cedente_top1_pct")
        ced_txt = (f" · Maior cedente: {ced:.0f}%" if pd.notna(ced) else "")
        gest_txt = f" · Gestor: {u.get('gestor', '—')}" if u.get("gestor") else ""
        anbima_txt = (f" · ANBIMA: {u.get('classe_anbima')}"
                      if u.get("classe_anbima") and pd.notna(u.get("classe_anbima")) else "")
        adm_tx = u.get("taxa_adm")
        tx_txt = (f" · Taxa adm: {adm_tx:.4f}% a.a.".replace(".", ",")
                  if pd.notna(adm_tx) else "")
        sit_txt = (f" · Sit.: {u.get('sit')}"
                   if u.get("sit") and pd.notna(u.get("sit")) else "")
        st.caption(f"CNPJ {u.get('cnpj','—')} · Adm: {u.get('admin','—')} · "
                   f"{u.get('tp_fundo_classe','—')} · {u.get('condom','—')}"
                   f"{ced_txt}{gest_txt}{anbima_txt}{tx_txt}{sit_txt} · "
                   f"até {u['dt_comptc']:%m/%Y}")
        c1, c2 = st.columns(2)
        figpl = go.Figure()
        figpl.add_scatter(x=fsel["dt_comptc"], y=fsel["vl_pl"] / 1e6, name="PL (R$ mi)",
                          line=dict(color=ACCENT))
        figpl.add_scatter(x=fsel["dt_comptc"],
                          y=(fsel["vl_venc_inad"] / fsel["vl_dircred"] * 100).where(fsel["vl_dircred"] > 0),
                          name="Inad. %", yaxis="y2", line=dict(color="#C62828"))
        figpl.update_layout(title="PL e inadimplência", yaxis=dict(title="R$ mi"),
                            yaxis2=dict(title="%", overlaying="y", side="right"))
        c1.plotly_chart(style_fig(figpl), width="stretch")
        if not csel.empty:
            evs = csel.groupby(["dt_comptc", "senioridade"])["pl_aloc"].sum().reset_index()
            figse = px.area(evs, x="dt_comptc", y="pl_aloc", color="senioridade",
                            color_discrete_map=COR_SEN, title="PL por senioridade (R$)")
            c2.plotly_chart(style_fig(figse), width="stretch")
            cu2 = csel[csel["dt_comptc"] == csel["dt_comptc"].max()]
            st.markdown("##### Séries/cotas na última competência")
            st.dataframe(cu2[["classe_serie", "senioridade", "pl_aloc", "vl_cota", "rentab_mes", "nr_cotistas"]]
                         .sort_values("pl_aloc", ascending=False)
                         .assign(pl_aloc=lambda d: (d["pl_aloc"] / 1e6).round(2))
                         .rename(columns={"classe_serie": "Série", "senioridade": "Senioridade",
                                          "pl_aloc": "PL (R$ mi)", "vl_cota": "Valor cota",
                                          "rentab_mes": "Rentab. %", "nr_cotistas": "Cotistas"}),
                         width="stretch", hide_index=True)
        fonte("Perfil do fundo: Tab. I, IV e X do informe mensal de FIDC (CVM).")

with T[8]:
    cot_cols = [f"cotst_{k}" for k in C.INVESTIDOR_TIPOS if f"cotst_{k}" in dff.columns]
    ultf = dff[dff["dt_comptc"] == ref_month]
    if not cot_cols or float(ultf[cot_cols].fillna(0).to_numpy().sum()) == 0:
        st.info("Cotistas por tipo de investidor disponíveis a partir de 2019 "
                "(informe estruturado). Selecione uma competência mais recente.")
    else:
        c1, c2 = st.columns([3, 2])
        tot = (ultf[cot_cols].sum()
               .rename(lambda x: C.INVESTIDOR_TIPOS.get(x.replace("cotst_", ""), x)))
        tot = tot[tot > 0].sort_values()
        figi = px.bar(tot, orientation="h", color_discrete_sequence=[ACCENT],
                      title=f"Nº de cotistas por tipo de investidor ({ref_month:%m/%Y})")
        c1.plotly_chart(style_fig(figi, 430).update_layout(showlegend=False, hovermode=None),
                        width="stretch")
        with c2:
            st.markdown("##### Investidores institucionais")
            inst = {"EFPC (fundos de pensão)": "cotst_efpc", "RPPS (regime próprio)": "cotst_rpps",
                    "EAPC (prev. aberta)": "cotst_eapc", "Seguradora": "cotst_segur",
                    "Capitalização": "cotst_capitaliz", "Banco": "cotst_banco"}
            idf = pd.DataFrame([{"Tipo": k, "Cotistas": int(ultf[v].sum())}
                                for k, v in inst.items() if v in ultf])
            st.dataframe(idf, width="stretch", hide_index=True)
            st.metric("Total de contas de cotistas", fmt_int(ultf[cot_cols].sum().sum()))
        evol = dff.groupby("dt_comptc")[cot_cols].sum().sum(axis=1).rename("cotistas").reset_index()
        fige = px.area(evol, x="dt_comptc", y="cotistas",
                       title="Evolução do total de contas de cotistas", color_discrete_sequence=[ACCENT])
        st.plotly_chart(style_fig(fige, 280), width="stretch")
        st.caption("Contas de cotistas por tipo (sênior + subordinado). Útil para ver a presença de "
                   "investidores institucionais — fundos de pensão (EFPC), regimes próprios (RPPS) etc.")
        fonte("Tab. X.1.1 — nº de cotistas por tipo de investidor (a partir de 2019).")

with T[9]:
    st.markdown("##### 🚨 Radar de deterioração por fundo")
    meses_disp = sorted(dff["dt_comptc"].unique())
    if len(meses_disp) < 2:
        st.info("Histórico insuficiente para gerar alertas.")
    else:
        idx = meses_disp.index(ref_month) if ref_month in meses_disp else len(meses_disp) - 1
        base_dt = meses_disp[idx]
        comp_dt = meses_disp[max(0, idx - 3)]
        co = st.columns(3)
        thr_inad = co[0].slider("Δ inadimplência ≥ (p.p.)", 1.0, 10.0, 2.0, 0.5)
        thr_sub = co[1].slider("Queda de subordinação ≥ (p.p.)", 1.0, 10.0, 3.0, 0.5)
        thr_pl = co[2].slider("Queda de PL ≥ (%)", 5.0, 60.0, 20.0, 5.0)
        st.caption(f"Comparando **{base_dt:%m/%Y}** vs **{comp_dt:%m/%Y}** (≈3 meses).")

        def _met(dt):
            g = (dff[dff["dt_comptc"] == dt].groupby(["cnpj", "denom_social"])
                 .agg(pl=("vl_pl", "sum"), vi=("vl_venc_inad", "sum"),
                      dc=("vl_dircred", "sum")).reset_index())
            # Denominador material (> R$ 1 mi) evita inadimplência explosiva em
            # fundos com carteira de DC perto de zero (encerrando).
            g["inad"] = (g["vi"] / g["dc"]).where(g["dc"] > 1e6)
            if not dffc_full.empty:
                sc = dffc_full[dffc_full["dt_comptc"] == dt]
                sub = sc[sc.senioridade.isin(["Subordinada", "Mezanino"])].groupby("cnpj")["pl_aloc"].sum()
                tt = sc.groupby("cnpj")["pl_aloc"].sum()
                g = g.merge((sub / tt).rename("subord").reset_index(), on="cnpj", how="left")
            return g

        a, b = _met(base_dt), _met(comp_dt)
        m = a.merge(b, on="cnpj", suffixes=("", "_ant"))
        m = m[m["pl"] >= 1e6]  # ignora fundos minúsculos (ruído)
        m["d_inad"] = (m["inad"] - m["inad_ant"]) * 100
        m["d_pl"] = ((m["pl"] - m["pl_ant"]) / m["pl_ant"] * 100).where(m["pl_ant"] > 0)
        m["d_sub"] = ((m["subord"] - m["subord_ant"]) * 100) if "subord" in m else pd.NA
        f_inad = ((m["d_inad"] >= thr_inad) & (m["inad"] >= 0.05)).fillna(False)
        f_sub = (m["d_sub"] <= -thr_sub).fillna(False) if "subord" in m else pd.Series(False, index=m.index)
        f_pl = (m["d_pl"] <= -thr_pl).fillna(False)
        m["sev"] = f_inad.astype(int) + f_sub.astype(int) + f_pl.astype(int)

        def _motivos(i):
            o = []
            if f_inad[i]: o.append(f"inad +{m['d_inad'][i]:.1f}pp")
            if f_sub[i]: o.append(f"subord {m['d_sub'][i]:.1f}pp")
            if f_pl[i]: o.append(f"PL {m['d_pl'][i]:.0f}%")
            return " · ".join(o)

        al = m[m["sev"] > 0].copy()
        st.metric("Fundos em alerta", f"{len(al)} de {len(m)}")
        if al.empty:
            st.success("Nenhum fundo dispara alertas com os critérios atuais. 🎉")
        else:
            al["Motivos"] = [_motivos(i) for i in al.index]
            out = (al.sort_values(["sev", "d_inad"], ascending=[False, False])
                   .assign(PL_mi=lambda d: (d["pl"] / 1e6).round(1),
                           inad_pct=lambda d: d["inad"])
                   .rename(columns={"denom_social": "Fundo/Classe", "PL_mi": "PL (R$ mi)",
                                    "inad_pct": "Inad. %", "d_inad": "ΔInad (pp)",
                                    "d_sub": "ΔSubord (pp)", "d_pl": "ΔPL (%)", "sev": "Sev."}))
            cols = ["Fundo/Classe", "PL (R$ mi)", "Inad. %", "ΔInad (pp)",
                    "ΔSubord (pp)", "ΔPL (%)", "Sev.", "Motivos"]
            cols = [c for c in cols if c in out.columns]
            st.dataframe(out[cols].head(50).style.format({
                "Inad. %": "{:.1%}", "ΔInad (pp)": "{:+.1f}", "ΔSubord (pp)": "{:+.1f}",
                "ΔPL (%)": "{:+.0f}"}, na_rep="—"), width="stretch", hide_index=True)
            st.download_button("⬇️ Alertas (CSV)", out[cols].to_csv(index=False).encode("utf-8-sig"),
                               f"fidc_alertas_{base_dt:%Y%m}.csv", "text/csv")
        st.caption("Sinais de deterioração: alta da inadimplência, queda da subordinação (menos "
                   "proteção da cota sênior) e/ou encolhimento do PL. Ajuste os limiares acima.")
        fonte("Derivado das Tab. I, IV e X entre a competência de referência e ~3 meses antes.")

with T[10]:  # 📊 Qualidade
    ultf = dff[dff["dt_comptc"] == ref_month]
    n_tot = len(ultf)
    st.markdown(f"#### Completude dos dados — competência **{ref_month:%m/%Y}** ({n_tot} registros)")
    st.caption(
        "Campos estruturalmente ausentes em certas datas têm explicação na última seção. "
        "Completude = fração de registros com valor preenchido (não nulo)."
    )

    def _completude(cols):
        cols = [c for c in (cols if isinstance(cols, list) else [cols]) if c in ultf.columns]
        if not cols or n_tot == 0:
            return 0, 0
        preench = int(ultf[cols].notna().all(axis=1).sum())
        return preench, preench / n_tot * 100

    _seg_cols = [c for c in C.ROTULOS_SEGMENTO if c in ultf.columns]
    _rat_cols = [c for c in C.TAB_X_RATING if c in ultf.columns]
    _cot_cols = [f"cotst_{k}" for k in C.INVESTIDOR_TIPOS if f"cotst_{k}" in ultf.columns]

    checks = [
        ("Identificação (CNPJ, nome, admin)", ["cnpj", "denom_social", "admin"], "Sempre disponível"),
        ("Tipo / condomínio / exclusivo",      ["tp_fundo_classe", "condom", "fundo_exclusivo"], "Sempre disponível"),
        ("PL (vl_pl)",                          "vl_pl",        "Sempre disponível"),
        ("Ativo total (vl_ativo)",              "vl_ativo",     "Sempre disponível"),
        ("Carteira DC (vl_dircred)",            "vl_dircred",   "Disponível para fundos com crédito"),
        ("Vencidos/Inad (vl_venc_inad)",        "vl_venc_inad", "Disponível para fundos com DC"),
        ("PDD / Provisão (vl_pdd)",             "vl_pdd",       "Disponível para fundos com DC"),
        ("Segmentos (Tab. II)",                 _seg_cols,      "Disponível para a maioria dos fundos"),
        ("Rating SCR (Tab. X — AA→H)",          _rat_cols,      "Apenas a partir de 2023 (Res. CVM 175)"),
        ("Cotistas por tipo (Tab. X.1.1)",      _cot_cols,      "Apenas a partir de 2019"),
        ("Conc. cedentes (maior / top-5)",      ["cedente_top1_pct", "cedente_top5_pct"], "Apenas fundos que listam cedentes"),
    ]

    rows = []
    for label, cols, nota in checks:
        preench, pct = _completude(cols)
        rows.append({"Campo": label, "Preenchidos": preench,
                     "Total": n_tot, "Completude": pct / 100, "Obs.": nota})

    def _cor_completude(val):
        if val >= 0.80:
            return "background-color:#c6efce;color:#276221"
        if val >= 0.50:
            return "background-color:#ffeb9c;color:#9c5700"
        return "background-color:#ffc7ce;color:#9c0006"

    qdf = pd.DataFrame(rows)
    st.dataframe(
        qdf.style
           .format({"Completude": "{:.1%}", "Preenchidos": "{:,}", "Total": "{:,}"})
           .map(_cor_completude, subset=["Completude"]),
        width="stretch", hide_index=True,
    )
    fonte(f"Completude calculada sobre os registros da competência {ref_month:%m/%Y}.")

    st.markdown("---")
    st.markdown("##### Por que certos campos têm baixa completude?")
    st.markdown("""
- **Rating SCR (AA→H):** introduzido pela Resolução CVM 175 em 2023. Fundos constituídos antes e que
  não migraram para o novo marco não reportam essa tabela.
- **Cotistas por tipo de investidor:** disponível apenas no informe estruturado (a partir de 2019).
  Competências mais antigas simplesmente não possuem esse campo na fonte CVM.
- **Concentração de cedentes:** informada somente pelos fundos que listam individualmente seus cedentes
  na Tab. I. Fundos monocrédito ou com muitos cedentes frequentemente omitem esse campo.
- **Segmentos:** fundos em encerramento ou com carteira 100% líquida podem não preencher a Tab. II.
- **Carteira DC / Inadimplência / PDD:** FIDCs que detêm apenas ativos financeiros (ex.: CRI, CRA,
  debêntures dentro de uma estrutura híbrida) podem reportar DC ≈ 0, tornando os ratios indefinidos.
""")

with T[11]:  # 🗺️ Cedentes / Originadores
    st.markdown("### 🗺️ Mapa de cedentes / originadores")
    st.caption(
        "Quem origina os direitos creditórios comprados pelos FIDCs. A Tab. I do "
        "informe da CVM identifica os **maiores cedentes** de cada fundo por **CPF/CNPJ** "
        "e sua **participação (%)** na carteira (blocos *com risco* e *sem risco*). "
        "No mercado de FIDC o **cedente** costuma ser também o **originador** do crédito. "
        "CPF de pessoa física é anonimizado (LGPD)."
    )
    ced_all = carregar_cedentes()
    if ced_all.empty:
        st.info("Base de cedentes ainda não disponível (será populada no próximo ETL).")
    else:
        nomes = carregar_cedentes_nomes()
        nome_por_doc = (dict(zip(nomes["doc"].astype(str), nomes["razao_social"]))
                        if not nomes.empty else {})
        uf_por_doc = (dict(zip(nomes["doc"].astype(str), nomes["uf"]))
                      if not nomes.empty and "uf" in nomes.columns else {})

        def _rotulo(doc, tipo):
            nm = nome_por_doc.get(str(doc))
            if isinstance(nm, str) and nm.strip():
                return nm.strip().title()
            return _fmt_cnpj(doc)

        # Universo de fundos respeitando os filtros ativos (cross-filter, busca, etc.)
        cnpjs_periodo = set(dff["cnpj"].unique())
        cnpjs_ref = set(dff.loc[dff["dt_comptc"] == ref_month, "cnpj"].unique())
        cref = ced_all[(ced_all["dt_comptc"] == ref_month)
                       & (ced_all["cnpj"].isin(cnpjs_ref))].copy()
        ctempo = ced_all[ced_all["cnpj"].isin(cnpjs_periodo)].copy()

        if cref.empty:
            st.warning(f"Nenhum fundo do filtro lista cedentes em {ref_month:%m/%Y}. "
                       "A cobertura média é ~38% dos fundos; ajuste a competência ou os filtros.")
        else:
            cref["rotulo"] = [
                _rotulo(d, t) for d, t in zip(cref["doc"], cref["doc_tipo"])]
            cref["uf"] = cref["doc"].map(uf_por_doc)

            # ---- KPIs ----
            expo = cref.groupby("doc")["vl_estimado"].sum()
            tot_expo = expo.sum()
            k1, k2, k3, k4 = st.columns(4)
            k1.markdown(card("Cedentes distintos", fmt_int(cref["doc"].nunique())),
                        unsafe_allow_html=True)
            k2.markdown(card("Fundos que listam cedentes", fmt_int(cref["cnpj"].nunique())),
                        unsafe_allow_html=True)
            k3.markdown(card("Exposição estimada", fmt_bi(tot_expo)),
                        unsafe_allow_html=True)
            top10 = expo.sort_values(ascending=False).head(10).sum()
            k4.markdown(card("Concentração top-10",
                             fmt_pct(top10 / tot_expo if tot_expo else None)),
                        unsafe_allow_html=True)
            st.write("")

            # ---- Maiores cedentes (ranking) ----
            agg_ced = (cref.groupby("doc")
                       .agg(rotulo=("rotulo", "first"), doc_tipo=("doc_tipo", "first"),
                            uf=("uf", "first"),
                            vl=("vl_estimado", "sum"), fundos=("cnpj", "nunique"),
                            pr_medio=("pr_cedente", "mean"))
                       .reset_index().sort_values("vl", ascending=False))
            cE1, cE2 = st.columns([1.4, 1])
            topn = agg_ced.head(15).iloc[::-1]
            figc = px.bar(topn, x="vl", y="rotulo", orientation="h",
                          color_discrete_sequence=[ACCENT],
                          title=f"Maiores cedentes por exposição estimada ({ref_month:%m/%Y})",
                          hover_data={"fundos": True, "pr_medio": ":.1f"})
            figc.update_layout(xaxis_title="R$ (estimado)", yaxis_title="")
            cE1.plotly_chart(style_fig(figc, 440), width="stretch")
            with cE2:
                st.markdown("**Cedentes em mais fundos** (risco de contraparte sistêmico)")
                multi = (agg_ced.sort_values("fundos", ascending=False)
                         .head(12)[["rotulo", "fundos", "vl"]]
                         .rename(columns={"rotulo": "Cedente", "fundos": "Fundos",
                                          "vl": "Exp. (R$)"}))
                st.dataframe(multi.style.format({"Exp. (R$)": lambda v: fmt_bi(v)}),
                             width="stretch", hide_index=True, height=440)
            fonte(f"Tab. I.2.A.12 + I.2.B.12 (cedentes nomeados), ref. {ref_month:%m/%Y}. "
                  "Exposição estimada = participação % × carteira do bloco. "
                  "Razão social via BrasilAPI; demais cedentes mostrados por CNPJ.")

            # ---- Mapa de relacionamento (rede bipartite cedente ↔ fundo) ----
            st.markdown("##### Rede cedente ↔ fundo (maiores cedentes compartilhados)")
            top_docs = agg_ced.sort_values("fundos", ascending=False).head(8)["doc"].tolist()
            rede = cref[cref["doc"].isin(top_docs)].copy()
            # limita os fundos por cedente para legibilidade
            rede = (rede.sort_values("vl_estimado", ascending=False)
                    .groupby("doc").head(10))
            if not rede.empty:
                docs = list(dict.fromkeys(rede["doc"]))
                fundos = list(dict.fromkeys(rede["cnpj"]))
                # cedentes à esquerda (x=0), fundos à direita (x=1)
                y_ced = {d: i for i, d in enumerate(
                    sorted(docs, key=lambda d: -rede[rede.doc == d]["cnpj"].nunique()))}
                ny_c = max(len(docs) - 1, 1)
                ny_f = max(len(fundos) - 1, 1)
                pos_ced = {d: (0.0, 1 - 2 * y_ced[d] / ny_c) for d in docs}
                y_fun = {f: i for i, f in enumerate(fundos)}
                pos_fun = {f: (1.0, 1 - 2 * y_fun[f] / ny_f) for f in fundos}
                ex, ey = [], []
                for _, r in rede.iterrows():
                    x0, y0 = pos_ced[r["doc"]]
                    x1, y1 = pos_fun[r["cnpj"]]
                    ex += [x0, x1, None]
                    ey += [y0, y1, None]
                fign = go.Figure()
                fign.add_trace(go.Scatter(x=ex, y=ey, mode="lines",
                                          line=dict(color="#CBD5E1", width=1), hoverinfo="none"))
                fundo_nome = dict(zip(dff["cnpj"], dff["denom_social"].astype(str)))
                fign.add_trace(go.Scatter(
                    x=[pos_fun[f][0] for f in fundos], y=[pos_fun[f][1] for f in fundos],
                    mode="markers", marker=dict(size=9, color="#90A4AE"),
                    text=[fundo_nome.get(f, f) for f in fundos], hoverinfo="text", name="Fundos"))
                fign.add_trace(go.Scatter(
                    x=[pos_ced[d][0] for d in docs], y=[pos_ced[d][1] for d in docs],
                    mode="markers+text", textposition="middle left",
                    marker=dict(size=16, color=ACCENT, line=dict(color="#fff", width=1)),
                    text=[_rotulo(d, "CNPJ")[:28] for d in docs], hoverinfo="text", name="Cedentes"))
                fign.update_layout(
                    title="Cada linha liga um cedente a um fundo que compra seus créditos",
                    showlegend=False, xaxis=dict(visible=False, range=[-0.6, 1.2]),
                    yaxis=dict(visible=False))
                st.plotly_chart(style_fig(fign, 460).update_layout(hovermode="closest"),
                                width="stretch")
                fonte(f"Tab. I (cedentes nomeados), ref. {ref_month:%m/%Y}. "
                      "Top 8 cedentes por nº de fundos × até 10 fundos cada.")

            # ---- Distribuição por UF (se houver razão social enriquecida) ----
            if cref["uf"].notna().any():
                por_uf = (cref.dropna(subset=["uf"]).groupby("uf")["vl_estimado"].sum()
                          .sort_values(ascending=False).head(12).reset_index())
                figu = px.bar(por_uf, x="uf", y="vl_estimado",
                              color_discrete_sequence=[CORES[0]],
                              title="Exposição estimada por UF do cedente (amostra enriquecida)")
                figu.update_layout(xaxis_title="", yaxis_title="R$")
                st.plotly_chart(style_fig(figu, 300), width="stretch")
                fonte("UF via BrasilAPI (apenas maiores cedentes enriquecidos); "
                      f"Tab. I da CVM, ref. {ref_month:%m/%Y}.")

            # ---- Evolução do nº de cedentes nomeados no mercado ----
            evo = (ctempo.groupby("competencia")
                   .agg(cedentes=("doc", "nunique"), fundos=("cnpj", "nunique")).reset_index())
            evo["competencia"] = pd.to_datetime(evo["competencia"])
            fige = go.Figure()
            fige.add_scatter(x=evo["competencia"], y=evo["cedentes"], name="Cedentes distintos",
                             line=dict(color=ACCENT))
            fige.add_scatter(x=evo["competencia"], y=evo["fundos"], name="Fundos que listam",
                             line=dict(color="#90A4AE"))
            fige.add_vline(x=ref_month, line_dash="dot", line_color="#C62828")
            st.plotly_chart(style_fig(fige, 280).update_layout(
                title="Evolução: cedentes nomeados e fundos que os reportam"), width="stretch")
            fonte("Tab. I da CVM (cedentes nomeados disponíveis a partir de 11/2019).")

            # ---- Drill-through: cedente -> fundos ----
            st.markdown("##### 🔎 Cedente → fundos atendidos")
            opcoes = agg_ced.head(60)
            mapa_lbl = {f"{r.rotulo}  ·  {r.fundos} fundo(s)  ·  {fmt_bi(r.vl)}": r.doc
                        for r in opcoes.itertuples()}
            escolha = st.selectbox("Selecione um cedente (top 60 por exposição):",
                                   list(mapa_lbl.keys()))
            if escolha:
                doc_sel = mapa_lbl[escolha]
                det = cref[cref["doc"] == doc_sel].copy()
                det["Fundo"] = det["cnpj"].map(dict(zip(dff["cnpj"], dff["denom_social"].astype(str))))
                det = det[["Fundo", "cnpj", "bloco", "pr_cedente", "vl_estimado"]].rename(
                    columns={"cnpj": "CNPJ fundo", "bloco": "Bloco",
                             "pr_cedente": "% na carteira", "vl_estimado": "Exp. estimada (R$)"})
                st.dataframe(det.sort_values("Exp. estimada (R$)", ascending=False).style.format(
                    {"% na carteira": "{:.1f}", "Exp. estimada (R$)": lambda v: fmt_bi(v)}),
                    width="stretch", hide_index=True)
                st.download_button("⬇️ Fundos deste cedente (CSV)",
                                   det.to_csv(index=False).encode("utf-8-sig"),
                                   f"cedente_{doc_sel}_{ref_month:%Y%m}.csv", "text/csv")
                fonte(f"Tab. I da CVM, ref. {ref_month:%m/%Y}.")

        # ---- Auditoria / limitações dos dados de cedentes ----
        with st.expander("ℹ️ Qualidade e limitações dos dados de cedentes"):
            st.markdown("""
- **Cobertura ~38%:** só os fundos que listam individualmente seus cedentes na Tab. I aparecem aqui.
  Fundos pulverizados (milhares de cedentes) ou monocrédito frequentemente não preenchem.
- **Disponível a partir de 11/2019:** o layout anterior da CVM não trazia o CPF/CNPJ do cedente.
- **Top 9 por bloco:** a CVM lista no máximo os 9 maiores cedentes de cada bloco (com/sem risco),
  então cedentes menores não são identificados.
- **Exposição estimada:** participação % × carteira do bloco. Em ~4% dos fundos-mês a soma dos %
  reportados ultrapassa 100% (erro de digitação na fonte CVM), o que pode superestimar a exposição.
- **Sentinelas removidos:** códigos como 999.../000... ("cedente diverso") e documentos inválidos
  são descartados na ingestão.
- **Nomes:** razão social/UF dos maiores cedentes via BrasilAPI; os demais aparecem por CNPJ.
  CPF de pessoa física é anonimizado (LGPD).
""")

with T[12]:
    st.subheader("Série agregada (por competência)")
    tab = agg.copy()
    tab["dt_comptc"] = tab["dt_comptc"].dt.strftime("%m/%Y")
    st.dataframe(tab, width="stretch", hide_index=True)
    cd = st.columns(2)
    cd[0].download_button("⬇️ Série agregada (CSV)", tab.to_csv(index=False).encode("utf-8-sig"),
                          "fidc_serie_agregada.csv", "text/csv", width="stretch")
    if not dffc.empty:
        exp = dffc[dffc["dt_comptc"] == ref_month][["denom_social", "classe_serie", "senioridade",
              "pl_aloc", "vl_cota", "rentab_mes", "nr_cotistas", "admin"]]
        cd[1].download_button(f"⬇️ Cotas {ref_month:%m/%Y} (CSV)",
                              exp.to_csv(index=False).encode("utf-8-sig"),
                              f"fidc_cotas_{ref_month:%Y%m}.csv", "text/csv", width="stretch")
    st.caption("PL por senioridade = PL real do fundo (Tab. IV) rateado pela participação de cada série. "
               "Inadimplência = vencidos não pagos ÷ carteira de DC. Rentabilidade = mediana. "
               "Rating SCR e cotistas por investidor só a partir de 2023 (Res. CVM 175).")
    fonte("Informe Mensal de FIDC (Tab. I a X) — Portal de Dados Abertos da CVM.")
