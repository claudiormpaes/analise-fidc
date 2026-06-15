"""Mapeamento de colunas dos informes mensais de FIDC.

O layout dos arquivos da CVM mudou ao longo do tempo (a Resolução CVM 175
introduziu a separação Fundo/Classe e renomeou a chave de CNPJ_FUNDO para
CNPJ_FUNDO_CLASSE). As colunas financeiras centrais, porém, mantêm o mesmo
nome desde 2013. Aqui normalizamos tudo para nomes canônicos em minúsculo.
"""
from __future__ import annotations

# Colunas de identificação: nome de origem (CVM) -> nome canônico.
# Cobre tanto o layout antigo (CNPJ_FUNDO) quanto o novo (CNPJ_FUNDO_CLASSE).
RENAME_ID = {
    "CNPJ_FUNDO_CLASSE": "cnpj",
    "CNPJ_FUNDO": "cnpj",
    "TP_FUNDO_CLASSE": "tp_fundo_classe",
    "DENOM_SOCIAL": "denom_social",
    "DT_COMPTC": "dt_comptc",
    "CNPJ_ADMIN": "cnpj_admin",
    "ADMIN": "admin",
    "CONDOM": "condom",
    "FUNDO_EXCLUSIVO": "fundo_exclusivo",
}

# Chave usada para juntar as várias tabelas de um mesmo informe.
CHAVE = ["cnpj", "dt_comptc"]

# Tabela I — situação patrimonial / composição de ativos.
# canônico -> nome de origem na CVM.
TAB_I_VALORES = {
    "vl_ativo": "TAB_I_VL_ATIVO",
    "vl_disponibilidades": "TAB_I1_VL_DISP",
    "vl_carteira": "TAB_I2_VL_CARTEIRA",
    "vl_dircred_risco": "TAB_I2A_VL_DIRCRED_RISCO",
    "vl_dircred_sem_risco": "TAB_I2B_VL_DIRCRED_SEM_RISCO",
    "vl_venc_ad_risco": "TAB_I2A1_VL_CRED_VENC_AD",
    "vl_venc_inad_risco": "TAB_I2A2_VL_CRED_VENC_INAD",
    "vl_venc_inad_sem_risco": "TAB_I2B2_VL_CRED_VENC_INAD",   # pode faltar em anos antigos
    "vl_cred_inad_risco": "TAB_I2A3_VL_CRED_INAD",
    "vl_cred_inad_sem_risco": "TAB_I2B3_VL_CRED_INAD",        # idem
    "vl_reducao_recup_risco": "TAB_I2A11_VL_REDUCAO_RECUP",
    "vl_reducao_recup_sem_risco": "TAB_I2B11_VL_REDUCAO_RECUP",  # idem
    "vl_valores_mobiliarios": "TAB_I2C_VL_VLMOB",
    "vl_titpub_federal": "TAB_I2D_VL_TITPUB_FED",
}

# Tabela VII — quantidades/valores de cedentes, prestadores e terceiros.
TAB_VII_VALORES = {
    "qt_cedentes": "TAB_VII_B1_1_QT_CEDENTE",
    "vl_cedentes": "TAB_VII_B1_2_VL_CEDENTE",
}

# Tabela IV — patrimônio líquido.
TAB_IV_VALORES = {
    "vl_pl": "TAB_IV_A_VL_PL",
    "vl_pl_medio": "TAB_IV_B_VL_PL_MEDIO",
}

# Tabela II — carteira de direitos creditórios por segmento (atividade do cedente).
TAB_II_VALORES = {
    "seg_industrial": "TAB_II_A_VL_INDUST",
    "seg_imobiliario": "TAB_II_B_VL_IMOBIL",
    "seg_comercial": "TAB_II_C_VL_COMERC",
    "seg_servicos": "TAB_II_D_VL_SERV",
    "seg_agronegocio": "TAB_II_E_VL_AGRONEG",
    "seg_financeiro": "TAB_II_F_VL_FINANC",
    "seg_credito": "TAB_II_G_VL_CREDITO",
    "seg_factoring": "TAB_II_H_VL_FACTOR",
    "seg_setor_publico": "TAB_II_I_VL_SETOR_PUBLICO",
    "seg_judicial": "TAB_II_J_VL_JUDICIAL",
    "seg_marca": "TAB_II_K_VL_MARCA",
}

# Tabela V — direitos creditórios a vencer / inadimplentes / antecipados (totais).
TAB_V_VALORES = {
    "vl_avencer": "TAB_V_A_VL_DIRCRED_PRAZO",
    "vl_inadimplente": "TAB_V_B_VL_DIRCRED_INAD",
    "vl_antecipado": "TAB_V_C_VL_DIRCRED_ANTECIPADO",
}

# --------------------------------------------------------------------------- #
# Tabela X — cotas por classe/série (senioridade)
# --------------------------------------------------------------------------- #
# Cada subtabela traz o texto TAB_X_CLASSE_SERIE (ex.: "Subclasse Senior Série 1",
# "Subclasse Subordinada Mezanino 2 | Série 1"), de onde extraímos a senioridade.
COL_SERIE = "TAB_X_CLASSE_SERIE"
COL_TP_OPER = "TAB_X_TP_OPER"

# tab_X_2: quantidade e valor da cota por série
TAB_X2_VALORES = {"qt_cota": "TAB_X_QT_COTA", "vl_cota": "TAB_X_VL_COTA"}
# tab_X_1: nº de cotistas por série
TAB_X1_VALORES = {"nr_cotistas": "TAB_X_NR_COTST"}
# tab_X_3: rentabilidade no mês (%)
TAB_X3_VALORES = {"rentab_mes": "TAB_X_VL_RENTAB_MES"}
# tab_X_6: desempenho esperado x realizado (% — benchmark/meta vs realizado)
TAB_X6_VALORES = {"desemp_esperado": "TAB_X_PR_DESEMP_ESPERADO",
                  "desemp_real": "TAB_X_PR_DESEMP_REAL"}

# tab_X (principal, pós-Res.175): distribuição da carteira por rating SCR da operação
TAB_X_RATING = {f"rating_{r.lower()}": f"TAB_X_SCR_RISCO_OPER_{r}"
                for r in ["AA", "A", "B", "C", "D", "E", "F", "G", "H"]}

# tab_X_5: PL por faixa de prazo de liquidez
TAB_X5_LIQUIDEZ = {
    "liq_0": "TAB_X_VL_LIQUIDEZ_0", "liq_30": "TAB_X_VL_LIQUIDEZ_30",
    "liq_60": "TAB_X_VL_LIQUIDEZ_60", "liq_90": "TAB_X_VL_LIQUIDEZ_90",
    "liq_180": "TAB_X_VL_LIQUIDEZ_180", "liq_360": "TAB_X_VL_LIQUIDEZ_360",
    "liq_maior_360": "TAB_X_VL_LIQUIDEZ_MAIOR_360",
}

# Ordem canônica das senioridades (do mais protegido ao mais arriscado)
ORDEM_SENIORIDADE = ["Sênior", "Mezanino", "Subordinada", "Única", "Outra"]

# tab_X_1_1 (pós-Res.175): nº de cotistas por TIPO DE INVESTIDOR (sênior + subord.).
# canônico -> rótulo amigável; a coluna de origem é
# TAB_X_NR_COTST_SENIOR_<SUF> e TAB_X_NR_COTST_SUBORD_<SUF>, com SUF = chave.upper().
INVESTIDOR_TIPOS = {
    "pf": "Pessoa física",
    "pj_nao_financ": "PJ não financeira",
    "banco": "Banco",
    "corretora_distrib": "Corretora/Distribuidora",
    "pj_financ": "PJ financeira",
    "invnr": "Investidor não residente",
    "eapc": "EAPC (prev. aberta)",
    "efpc": "EFPC (fundo de pensão)",
    "rpps": "RPPS (regime próprio)",
    "segur": "Seguradora",
    "capitaliz": "Capitalização",
    "cota_fidc": "Cotas de FIDC",
    "fii": "FII",
    "outro_fi": "Outros fundos",
    "clube": "Clube de investimento",
    "outro": "Outros",
}


def classificar_senioridade(texto) -> str:
    """Classifica o texto da classe/série em uma senioridade canônica.

    Cobre os layouts antigo ("Cota Sênior", "Cota Subordinada Mezanino",
    "Cota Subordinada Júnior", "Cota Única") e novo ("Subclasse Senior ...",
    "Subclasse Subordinada Mezanino N | Série M", "Subclasse Subordinada ...").
    A ordem dos testes importa: mezanino contém "subordinada" no rótulo novo.
    """
    if not isinstance(texto, str):
        return "Outra"
    t = texto.lower()
    if "mezanino" in t:
        return "Mezanino"
    if "subordinad" in t or "junior" in t or "júnior" in t or "subord" in t:
        return "Subordinada"
    if "senior" in t or "sênior" in t:
        return "Sênior"
    # Layout antigo (2013–2019): a tranche sênior era rotulada apenas como
    # "Série N" (sem a palavra "Sênior"); a subordinada vinha como "Classe
    # Subordinada N" (já capturada acima). Logo, "Série ..." restante = Sênior.
    if "série" in t or "serie" in t:
        return "Sênior"
    if "única" in t or "unica" in t:
        return "Única"
    return "Outra"


def classificar_operacao(texto) -> str | None:
    """Normaliza TAB_X_TP_OPER em chave canônica de fluxo."""
    if not isinstance(texto, str):
        return None
    t = texto.lower()
    if "capta" in t:
        return "captacao"
    if "amortiz" in t:
        return "amortizacao"
    if "solicitad" in t:
        return "resgate_solicitado"
    if "resgate" in t:
        return "resgate"
    return None


# Rótulos amigáveis dos segmentos (para gráficos do dashboard).
ROTULOS_SEGMENTO = {
    "seg_industrial": "Industrial",
    "seg_imobiliario": "Imobiliário",
    "seg_comercial": "Comercial",
    "seg_servicos": "Serviços",
    "seg_agronegocio": "Agronegócio",
    "seg_financeiro": "Financeiro",
    "seg_credito": "Crédito",
    "seg_factoring": "Factoring",
    "seg_setor_publico": "Setor Público",
    "seg_judicial": "Judicial",
    "seg_marca": "Marca/Royalties",
}
