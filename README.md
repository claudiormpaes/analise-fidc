---
title: Análise de FIDCs — Mercado Brasileiro (CVM)
emoji: 📊
colorFrom: green
colorTo: blue
sdk: docker
pinned: false
datasets:
  - claudiormpaes/fidc-dados
license: mit
---

# Análise de FIDCs — Panorama do mercado (dados CVM)

Projeto completo para baixar, tratar e acompanhar diariamente os dados de
**Fundos de Investimento em Direitos Creditórios (FIDC)** do Brasil, com um
**dashboard interativo** de panorama de mercado.

## De onde vêm os dados

Fonte oficial: **Portal de Dados Abertos da CVM** — *Informe Mensal de FIDC*
(Anexo A da ICVM 489/502, atualizado pela Resolução CVM 175).

- Histórico anual: `https://dados.cvm.gov.br/dados/FIDC/DOC/INF_MENSAL/DADOS/HIST/` (2013–2024)
- Mensais recentes: `https://dados.cvm.gov.br/dados/FIDC/DOC/INF_MENSAL/DADOS/` (2025+)

> **Periodicidade:** o informe de FIDC é **mensal**. Não existe base pública com
> granularidade diária. O pipeline roda diariamente para capturar **reenvios**
> (a CVM reprocessa os últimos ~13 meses semanalmente) e novos meses assim que
> publicados, mas os indicadores evoluem mês a mês.

## Estrutura

```
analise_fidc/
├── app.py                 # Dashboard Streamlit
├── config.py              # Caminhos, URLs e parâmetros
├── requirements.txt
├── run_daily.ps1          # Atualização diária (Agendador de Tarefas)
├── fidc/
│   ├── columns.py         # Mapeamento de colunas (tolera layouts antigo/novo)
│   ├── downloader.py      # Download incremental dos ZIPs da CVM
│   ├── processor.py       # Extração e consolidação -> parquet
│   └── pipeline.py        # Orquestrador (baixar + consolidar)
└── data/
    ├── raw/               # ZIPs originais + manifest.json
    └── processed/
        ├── fidc_consolidado.parquet   # fato fundo-mês (PL, ativo, risco, segmentos…)
        └── fidc_cotas.parquet         # fato série/cota-mês (senioridade, rentab., fluxo)
```

## Funcionalidades do dashboard

**Interface estilo Power BI:** KPIs em *cards*, barra de *slicers* no topo (segmented controls),
**competência de referência** ajustável que recalcula todos os snapshots, **cross-filter por
clique** (clique numa barra do ranking de administradores e o painel inteiro é filtrado),
*chips* de filtros ativos e botão "Limpar", tema visual unificado nos gráficos.

**Filtros:** período (séries) · competência de referência (snapshots) · 🔎 busca por nome do
fundo · tipo (Fundo/Classe) · **senioridade** (Sênior/Mezanino/Subordinada/Única) · condomínio ·
exclusivo · administrador (+ cross-filter por clique).

**Abas:**
- **📈 Mercado** — evolução de PL, ativo e nº de fundos
- **🏗️ Estrutura de Cotas** — PL por senioridade ao longo do tempo e **razão de subordinação** do mercado
- **⚠️ Risco & Inadimplência** — inadimplência, PDD, **rating SCR** (AA→H), aging e **concentração de cedentes** (risco de contraparte)
- **💰 Rentabilidade & Fluxo** — rentabilidade mediana por senioridade **vs CDI** e **excesso de retorno** da cota sênior, captações × resgates
- **🧩 Carteira** — composição por segmento e por prazo de liquidez
- **🏆 Rankings** — top administradores e maiores fundos (clique numa linha → **drill-through** para o deep-dive)
- **🔎 Fundo (deep-dive)** — perfil completo de um fundo: PL, inadimplência, séries por senioridade, valor da cota, rentabilidade e cotistas
- **👥 Investidores** — nº de cotistas por tipo (PF, banco, **EFPC/fundos de pensão**, RPPS…) e evolução do total de contas
- **🚨 Alertas** — radar de deterioração por fundo (alta de inadimplência, queda de subordinação, encolhimento de PL) com limiares ajustáveis e export
- **📋 Dados** — tabelas e export CSV

## Instalação

```powershell
cd "analise_fidc"
pip install -r requirements.txt
```

## Uso

**1) Gerar/atualizar a base** (a 1ª execução baixa o histórico completo, ~400 MB):

```powershell
python -m fidc.pipeline
```

**2) Abrir o dashboard:**

```powershell
python -m streamlit run app.py
```

> Use `python -m streamlit` (e não `streamlit` direto): nesta máquina o
> executável `streamlit.exe` é bloqueado por política/antivírus ("Acesso negado").

Abre em `http://localhost:8501`. Filtros disponíveis: período, tipo (Fundo/Classe),
condomínio (aberto/fechado), exclusivo, administrador. Abas: Evolução,
Risco/Inadimplência, Carteira por segmento, Rankings e Dados (com export CSV).

## Atualização diária automática (Windows)

Agende `run_daily.ps1` no **Agendador de Tarefas**:

```powershell
$acao    = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-ExecutionPolicy Bypass -File `"$PWD\run_daily.ps1`""
$gatilho = New-ScheduledTaskTrigger -Daily -At 8:00am
Register-ScheduledTask -TaskName "FIDC - Atualizacao diaria" `
  -Action $acao -Trigger $gatilho -Description "Atualiza base de FIDCs da CVM"
```

Logs ficam em `data/pipeline.log`.

## Indicadores e metodologia

| Indicador | Cálculo |
|---|---|
| Patrimônio Líquido | Tab. IV.A (`vl_pl`), somado no nível Fundo + Classe |
| Ativo total | Tab. I (`vl_ativo`) |
| Carteira de direitos creditórios | Tab. I.2.A + I.2.B (com e sem risco) |
| Inadimplência % | direitos vencidos e não pagos (I.2.A2 + I.2.B2) ÷ carteira de DC |
| PDD / Carteira % | provisão p/ redução ao valor recuperável (I.2.A11 + I.2.B11) ÷ carteira |
| Composição por segmento | Tab. II (industrial, financeiro, comercial, serviços, agro, factoring…) |
| Senioridade | Tab. X: rótulo da série → Sênior / Mezanino / Subordinada / Única |
| PL por senioridade | PL real do fundo (Tab. IV) **rateado** pela participação de cada série |
| Razão de subordinação | (Subordinada + Mezanino) ÷ PL — proteção de crédito da cota sênior |
| Rentabilidade | Tab. X.3 — **mediana** mensal por senioridade (robusta a outliers, clip ±50%) |
| Fluxo (captação/resgate/amortização) | Tab. X.4 |
| Rating SCR (AA→H) | Tab. X — só a partir de 2023 (Res. CVM 175) |
| Cotistas por tipo de investidor | Tab. X.1.1 (PF, banco, EFPC, RPPS…) — a partir de 2019 |
| Alertas de deterioração | Δ inadimplência / subordinação / PL entre a competência de referência e ~3 meses antes |
| Concentração de cedentes | Tab. I — % do maior cedente (e dos 5 maiores) entre os fundos que listam cedentes |
| Rentabilidade vs CDI | rentab. mediana das séries que reportam − CDI mensal (BACEN/SGS série 4391) |

> **Por que ratear o PL e não somar qt×valor da cota?** Alguns fundos reportam
> quantidade/valor de cota com erros grosseiros. Somar direto inflaria o mercado.
> Usamos esses campos só para a **proporção** por senioridade e aplicamos sobre o
> PL real do fundo (Tab. IV) — assim o total sempre reproduz o mercado correto.
>
> **Senioridade no layout antigo (pré-2020):** a tranche sênior era rotulada apenas
> como "Série N" (sem a palavra "Sênior"); o classificador trata esses casos.

**Nota sobre Fundo × Classe (Res. CVM 175):** cada FIDC ("Fundo") pode ter várias
"Classes". Na base, os níveis Fundo e Classe são **disjuntos** (o PL agregado no
nível Fundo é muito menor que no nível Classe), então a soma dos dois reflete o
mercado total sem dupla contagem. Use o filtro **Tipo** para analisar cada nível
isoladamente. Razões (%) são calculadas sobre os agregados, não como média de razões.
```
