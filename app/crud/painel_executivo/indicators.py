import numpy as np
import pandas as pd

from crud.painel_executivo.data import (
    PREFIXO_ATRASO_MENSAL,
    PREFIXO_SALDO_MENSAL,
    WO,
    carregar_dados_executivo_bruto,
    categorias_do_produto,
    filtrar_executivo,
    linhas_de_credito,
    normalizar_produtos,
    rotular_categoria,
    separar_por_categoria,
)

SEM_CATEGORIA = "Sem categoria"

MESES_PT = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}

# Faixas de atraso do CONTRATO (maior atraso entre as parcelas em aberto).
# Fronteiras fechadas à direita, alinhadas ao corte de write-off do resto do
# app (`WO` = 360: write-off = atraso > 360) -- a faixa "181 a 360" ainda é
# carteira viva e "361 a 720" / "Acima de 720" são write-off.
FAIXAS_ATRASO_BINS = [-np.inf, 0, 7, 15, 30, 60, 90, 180, WO, 720, np.inf]
FAIXAS_ATRASO_LABELS = [
    "00 - A vencer", "01 - De 1 a 7 dias", "02 - De 8 a 15 dias", "03 - De 16 a 30 dias",
    "04 - De 31 a 60 dias", "05 - De 61 a 90 dias", "06 - De 91 a 180 dias",
    f"07 - De 181 a {WO} dias", f"08 - De {WO + 1} a 720 dias", "09 - Acima de 720 dias",
]

# ---------------------------------------------------------------------------
# PDD -- réguas por fundo (aba "Regras PDD" da planilha "PDD por Rating")
# ---------------------------------------------------------------------------
# Cada régua é uma lista de (rótulo da faixa, limite superior do atraso em dias
# -- faixa fechada à direita --, % de provisão). O último limite é infinito.
# O % vale para TODO o saldo em aberto (`amount`) da unidade da régua.
REGUA_GHIA = "Ghia"
REGUA_KANASTRA = "Kanastra"
REGUA_OIKOS = "Oikos"
REGUA_CMN = "Res. 2682"

_INF = float("inf")
PDD_REGUAS = {
    # tabela proposta pela Ghia
    REGUA_GHIA: [
        ("Faixa 1 - Adimplentes", 0, 0.0115),
        ("Faixa 2 - 1 a 15 dias", 15, 0.0115),
        ("Faixa 3 - 16 a 30 dias", 30, 0.0115),
        ("Faixa 4 - 31 a 60 dias", 60, 0.0115),
        ("Faixa 5 - 61 a 90 dias", 90, 0.5410),
        ("Faixa 6 - 91 a 120 dias", 120, 0.5925),
        ("Faixa 7 - 121 a 150 dias", 150, 0.6971),
        ("Faixa 8 - 151 a 180 dias", 180, 0.8616),
        ("Faixa 9 - 181 a 210 dias", 210, 0.9281),
        ("Faixa 10 - 211 a 240 dias", 240, 0.9758),
        ("Faixa 11 - 241 a 270 dias", 270, 0.9772),
        ("Faixa 12 - 271 a 300 dias", 300, 0.9772),
        ("Faixa 13 - 301 a 330 dias", 330, 0.9884),
        ("Faixa 14 - Acima de 330 dias", _INF, 1.0),
    ],
    # escala própria do Kanastra
    REGUA_KANASTRA: [
        ("Até 14 dias", 14, 0.0),
        ("15 a 30 dias", 30, 0.15),
        ("31 a 45 dias", 45, 0.225),
        ("46 a 60 dias", 60, 0.30),
        ("61 a 75 dias", 75, 0.60),
        ("Acima de 75 dias", _INF, 1.0),
    ],
    # régua atual do FIAGRO (Oikos)
    REGUA_OIKOS: [
        ("Até 60 dias", 60, 0.0),
        ("61 a 90 dias", 90, 0.15),
        ("91 a 120 dias", 120, 0.2583),
        ("121 a 150 dias", 150, 0.5083),
        ("151 a 180 dias", 180, 0.7583),
        ("181 dias ou mais", _INF, 1.0),
    ],
    # demais fundos: Resolução CMN 2.682
    REGUA_CMN: [
        ("AA (0 dias)", 0, 0.0),
        ("A (1 a 30 dias)", 30, 0.005),
        ("B (31 a 60 dias)", 60, 0.01),
        ("C (61 a 90 dias)", 90, 0.03),
        ("D (91 a 120 dias)", 120, 0.10),
        ("E (121 a 180 dias)", 180, 0.30),
        ("F (181 a 240 dias)", 240, 0.50),
        ("G (241 a 360 dias)", 360, 0.70),
        ("H (acima de 360 dias)", _INF, 1.0),
    ],
}

# Unidade em que o MAIOR atraso é medido em cada régua.
PDD_UNIDADE = {
    REGUA_GHIA: "Maior atraso do devedor (CPF/CNPJ) na Ghia",
    REGUA_KANASTRA: "Maior atraso do cliente (CPF/CNPJ) na CCB, todos os fundos",
    REGUA_OIKOS: "Maior atraso do contrato",
    REGUA_CMN: "Maior atraso do contrato",
}


def regua_do_fundo(fundo):
    """Régua de PDD de um fundo (portfolio): Ghia, Kanastra e Oikos (inclui
    'Oikos Warehouse') têm régua própria; todos os demais seguem a Res. CMN
    2.682 (inclusive 'Sem fundo')."""
    if fundo == "Ghia":
        return REGUA_GHIA
    if fundo == "Kanastra":
        return REGUA_KANASTRA
    if isinstance(fundo, str) and fundo.startswith("Oikos"):
        return REGUA_OIKOS
    return REGUA_CMN


# ---------------------------------------------------------------------------
# Indicadores — portados de app/functions/carteira_functions.py do projeto
# ai-assistant (mesmas fórmulas), com guardas extras para df vazio (o app
# tem filtros que o script original de relatório não tinha).
# ---------------------------------------------------------------------------


def calcular_visao_geral_negocio(df, _type):
    """Tópico 2 (Composição da Carteira) — e também a fonte dos 4
    primeiros KPIs do Tópico 1 (Painel Executivo)."""
    total_contratos = len(df)
    total_clientes_unicos = df["operationCode"].nunique()
    valor_total_emprestado = df["principalAmount"].sum()
    valor_total_receber = df["total_installment_amount"].sum()
    valor_total_pago = df["total_paid_amount"].sum()

    taxa_media = (
        np.average(df["monthlyRate"], weights=df["principalAmount"])
        if len(df) and df["principalAmount"].sum() else 0
    )
    ticket_medio = df["principalAmount"].mean() if len(df) else 0
    # "ativo" = não quitado (mesmo critério de `resumo_carteira_aberta`,
    # ~estado.quitado) -- não "outstanding_principal > 0". Um contrato
    # pode ter parcela em aberto com principalAmount 0 (ex.: resíduo só
    # de juros/encargos) e ainda assim não estar quitado; usar só o
    # saldo de principal pra decidir "ativo" causava um descolamento de
    # 1 contrato em relação ao "Nº contratos" da aba Análise da carteira.
    contratos_ativos = len(df[~df["quitado"]]) if "quitado" in df.columns else len(df[df["outstanding_principal"] > 0])

    if len(df):
        ultimo_mes = df["releaseDate"].max() - pd.DateOffset(months=1)
        novos_contratos_mes = len(df[df["releaseDate"] >= ultimo_mes])
        valor_novos_contratos = df.loc[df["releaseDate"] >= ultimo_mes, "principalAmount"].sum()
    else:
        novos_contratos_mes = 0
        valor_novos_contratos = 0

    df_resultados = pd.DataFrame({
        "Indicador": [
            "Total de Contratos", "Total de Clientes Únicos", "Valor Total Emprestado (R$)",
            "Valor Total a Receber (R$)", "Valor Total Pago (R$)", "Taxa de Juros Média (%)",
            "Ticket Médio (R$)", "Contratos Ativos", "Novos Contratos (Último Mês)",
            "Valor Novos Contratos (R$)",
        ],
        f"Valor {_type}": [
            round(total_contratos, 2), round(total_clientes_unicos, 2), round(valor_total_emprestado, 2),
            round(valor_total_receber, 2), round(valor_total_pago, 2), round(taxa_media * 100, 2),
            round(ticket_medio, 2), round(contratos_ativos, 2), round(novos_contratos_mes, 2),
            round(valor_novos_contratos, 2),
        ],
    })
    return df_resultados.set_index("Indicador")


def calcular_indicadores_risco_inadimplencia(df, _type):
    """Tópico 3 (parte 'Indicadores de Risco') — e a fonte do gráfico de
    barras do Tópico 1 (Painel Executivo)."""
    saldo_total = df["total_installment_amount"].sum()

    inad_15d = df.loc[df["default_15p_flag"] == 1, "total_due_amount"].sum()
    inad_30d = df.loc[df["default_30p_flag"] == 1, "total_due_amount"].sum()
    inad_60d = df.loc[df["default_60p_flag"] == 1, "total_due_amount"].sum()
    inad_90d = df.loc[df["default_90p_flag"] == 1, "total_due_amount"].sum()

    if "firstPaymentDefault" in df.columns:
        first_payment_default = df.loc[df["firstPaymentDefault"] == True, "total_due_amount"].sum()
    else:
        first_payment_default = 0

    inadimplencia = pd.DataFrame({
        "Faixa de Atraso": ["FPD (90d)", "15+ dias", "30+ dias", "60+ dias", "90+ dias"],
        f"Saldo em Atraso (R$) {_type}": [
            round(first_payment_default, 2), round(inad_15d, 2), round(inad_30d, 2),
            round(inad_60d, 2), round(inad_90d, 2),
        ],
        f"% da Carteira {_type}": [
            round(first_payment_default / saldo_total * 100, 2) if saldo_total else 0,
            round(inad_15d / saldo_total * 100, 2) if saldo_total else 0,
            round(inad_30d / saldo_total * 100, 2) if saldo_total else 0,
            round(inad_60d / saldo_total * 100, 2) if saldo_total else 0,
            round(inad_90d / saldo_total * 100, 2) if saldo_total else 0,
        ],
    })
    return inadimplencia.set_index("Faixa de Atraso")


def calcular_indicadores_financeiros(df, _type):
    """Tópico 3 (parte 'Indicadores Financeiros')."""
    receita_juros_total = df["totalInterest"].sum() if "totalInterest" in df.columns else 0

    if "total_paid_amount" in df.columns and "paid_principal" in df.columns:
        juros_pagos = (df["total_paid_amount"] - df["paid_principal"]).clip(lower=0).sum()
    else:
        juros_pagos = 0

    carteira_ativa = df["outstanding_principal"].sum()
    inad_90d = df.loc[df["default_90p_flag"] == 1, "outstanding_principal"].sum()
    pdd = inad_90d * 0.5
    margem_bruta = juros_pagos - pdd

    financeiro = pd.DataFrame({
        "Indicador": [
            "Total de Juros (Contratada)", "Juros Pagos", "% Juros Pagos", "Saldo Devedor",
            "Inadimplência 90+ Esperada", "PDD", "Margem Financeira Bruta (Estimada)",
        ],
        f"Valor (R$) {_type}": [
            round(receita_juros_total, 2),
            round(juros_pagos, 2),
            round((juros_pagos / receita_juros_total) * 100, 2) if receita_juros_total else 0,
            round(carteira_ativa, 2),
            round(inad_90d, 2),
            round(pdd, 2),
            round(margem_bruta, 2),
        ],
    })
    return financeiro.set_index("Indicador")


def calcular_analise_safras(df):
    """Tópicos 4/5/6 (Análise por Safra — Total + categorias)."""
    colunas = [
        "Qtd Contratos", "Volume (R$)", "Saldo Devedor (R$)", "Perda Real 90d (R$)",
        "Perda Esperada (R$)", "Inadimplência Real 90d (%)", "Inadimplência Esperada (%)",
    ]
    if not len(df):
        return pd.DataFrame(columns=colunas)

    d = df.copy()
    d["release_month"] = d["releaseDate"].dt.strftime("%Y-%m")

    safras = d.groupby("release_month").agg(
        **{
            "Qtd Contratos": ("operationCode", "count"),
            "Volume (R$)": ("principalAmount", "sum"),
            "Saldo Devedor (R$)": ("outstanding_principal", "sum"),
            "Perda Real 90d (R$)": ("overdue_principal_90", "sum"),
        }
    ).round(2)

    perda_esperada = (
        d.loc[d["default_90p_flag"] == 1]
        .groupby("release_month")["outstanding_principal"].sum()
        .rename("Perda Esperada (R$)")
    )
    safras = safras.join(perda_esperada, how="left")
    safras["Perda Esperada (R$)"] = safras["Perda Esperada (R$)"].fillna(0).round(2)

    volume = safras["Volume (R$)"].astype(float)
    safras["Inadimplência Real 90d (%)"] = np.where(
        volume > 0, (safras["Perda Real 90d (R$)"].astype(float) / volume * 100).round(2), 0.0
    )
    safras["Inadimplência Esperada (%)"] = np.where(
        volume > 0, (safras["Perda Esperada (R$)"].astype(float) / volume * 100).round(2), 0.0
    )
    return safras[colunas]


# ---------------------------------------------------------------------------
# Visão Geral da Carteira (KPIs), NPL, faixas de atraso, evolução do NPL 90
# e PDD -- tópicos 1, 2 e 3 da aba depois da reformulação.
# ---------------------------------------------------------------------------
def calcular_npl(df):
    """NPL sobre o SALDO DEVEDOR (soma do `amount` das parcelas em aberto),
    em nível de CONTRATO: se o maior atraso do contrato é >= N dias, o saldo
    inteiro dele entra no NPL N. Mesma metodologia de `npl_por_faixa` da aba
    "Análise da Carteira".

    - "sem WO": numerador = saldo com atraso de N a 360 dias; denominador =
      saldo da carteira sem write-off (atraso <= 360).
    - "c/ WO": o saldo em write-off (atraso > 360) entra no numerador E no
      denominador.

    `df`: base de contratos-raiz (recorte de produto/categoria), com as
    colunas `total_due_amount` e `max_delay`. Devolve um dict com os saldos
    (R$) e os 4 NPLs (%)."""
    base = df[df["total_due_amount"] > 0]
    sem_wo = base[base["max_delay"] <= WO]
    com_wo = base[base["max_delay"] > WO]

    saldo_sem_wo = float(sem_wo["total_due_amount"].sum())
    saldo_wo = float(com_wo["total_due_amount"].sum())
    atraso_30_360 = float(sem_wo.loc[sem_wo["max_delay"] >= 30, "total_due_amount"].sum())
    atraso_90_360 = float(sem_wo.loc[sem_wo["max_delay"] >= 90, "total_due_amount"].sum())
    saldo_total = saldo_sem_wo + saldo_wo

    def _pct(num, den):
        return round(num / den * 100, 2) if den else 0.0

    return {
        "saldo_total": round(saldo_total, 2),
        "saldo_sem_wo": round(saldo_sem_wo, 2),
        "atraso_30_360": round(atraso_30_360, 2),
        "atraso_90_360": round(atraso_90_360, 2),
        "wo": round(saldo_wo, 2),
        "npl_30": _pct(atraso_30_360, saldo_sem_wo),
        "npl_90": _pct(atraso_90_360, saldo_sem_wo),
        "npl_30_wo": _pct(atraso_30_360 + saldo_wo, saldo_total),
        "npl_90_wo": _pct(atraso_90_360 + saldo_wo, saldo_total),
    }


def calcular_kpis_visao_geral(df, npl, _type):
    """Os 10 KPIs de "1. Visão Geral da Carteira" (e da tabela de "2.
    Distribuição por Produto").

    `df`: base do recorte (Produto + Carteira + Período) -- alimenta os 8
    indicadores de volume. `npl`: dict de `calcular_npl` sobre o recorte de
    Produto + Período mas SEM o filtro de Carteira (o NPL c/ WO precisa do
    write-off dentro da base, então ele não pode obedecer 'Carteira em
    aberto')."""
    ativos = df[~df["quitado"]] if "quitado" in df.columns else df[df["outstanding_principal"] > 0]
    total_concedido = df["principalAmount"].sum()
    taxa_media = (
        np.average(df["monthlyRate"], weights=df["principalAmount"])
        if len(df) and df["principalAmount"].sum() else 0
    )

    return pd.DataFrame({
        "Indicador": [
            "Total Concedido (R$)", "Contratos Ativos", "Ticket Médio (R$)", "Taxa de Juros Média (%)",
            "Quantidade de Contratos (Total)", "Total Concedido da Carteira Ativa (R$)",
            "Saldo da Carteira Ativa (R$)", "NPL 90 (%)", "NPL 90 + WO (%)", "Total Recebido (R$)",
        ],
        f"Valor {_type}": [
            round(total_concedido, 2),
            len(ativos),
            round(df["principalAmount"].mean(), 2) if len(df) else 0,
            round(taxa_media * 100, 2),
            len(df),
            # só as parcelas EM ABERTO (soma do principalAmount delas), igual ao
            # critério do saldo ao lado -- não o principal original do contrato
            round(ativos["outstanding_principal"].sum(), 2),
            round(ativos["total_due_amount"].sum(), 2),
            npl["npl_90"],
            npl["npl_90_wo"],
            round(df["total_paid_amount"].sum(), 2),
        ],
    }).set_index("Indicador")


def _rotulos_categoria(df, categorias):
    """Série com a categoria de cada linha; contratos sem categoria (ex.: CCB
    sem client_data) viram `SEM_CATEGORIA`, pra o Total sempre fechar com a
    soma das partes."""
    return df["categoria"].where(df["categoria"].isin(categorias), SEM_CATEGORIA)


def calcular_npl_tabela(df, produtos, linhas_por_produto):
    """Linhas da tabela "Inadimplência — NPL 90 e NPL 30": TODAS as linhas de
    crédito dos produtos selecionados (mais 'Sem categoria', se houver saldo
    nela) e o Total. Com mais de um produto, cada produto ganha também uma
    linha de subtotal ("Total CCB", "Total CPR") logo depois das suas linhas
    de crédito. Devolve um DataFrame (índice = rótulo da linha) com os saldos
    (R$) e os 4 NPLs (%).

    `df`: base sem filtro de Carteira, com as colunas `produto` e `linha`.
    `linhas_por_produto`: {produto: [linhas de crédito]}."""
    multi = len(produtos) > 1
    linhas = []
    for p in produtos:
        sub_p = df[df["produto"] == p]
        for linha in linhas_por_produto[p]:
            linhas.append({"Produto": linha, **calcular_npl(sub_p[sub_p["linha"] == linha])})
        resto = sub_p[~sub_p["linha"].isin(linhas_por_produto[p])]
        npl_resto = calcular_npl(resto)
        if npl_resto["saldo_total"]:
            rotulo = f"{SEM_CATEGORIA} ({p})" if multi else SEM_CATEGORIA
            linhas.append({"Produto": rotulo, **npl_resto})
        if multi:
            linhas.append({"Produto": f"Total {p}", **calcular_npl(sub_p)})
    linhas.append({"Produto": "Total", **calcular_npl(df)})
    return pd.DataFrame(linhas).set_index("Produto")


def calcular_faixas_atraso(df, categorias):
    """Carteira em aberto por faixa de atraso do contrato (inclui write-off).
    Devolve (tabela, amount_por_categoria): `tabela` com Principal, Amount,
    Princ. de cada categoria, Qtde e %; `amount_por_categoria` (faixa x
    categoria, em R$ de Amount) alimenta o gráfico empilhado."""
    base = df[df["total_due_amount"] > 0].copy()
    base["faixa"] = pd.cut(
        base["max_delay"], bins=FAIXAS_ATRASO_BINS, labels=FAIXAS_ATRASO_LABELS,
    )
    base["rotulo"] = _rotulos_categoria(base, categorias)
    rotulos = list(categorias) + ([SEM_CATEGORIA] if (base["rotulo"] == SEM_CATEGORIA).any() else [])

    tabela = base.groupby("faixa", observed=False).agg(
        Principal=("outstanding_principal", "sum"),
        Amount=("total_due_amount", "sum"),
        Qtde=("operationCode", "count"),
    ).reindex(FAIXAS_ATRASO_LABELS).fillna(0)
    princ_cat = base.pivot_table(
        index="faixa", columns="rotulo", values="outstanding_principal", aggfunc="sum",
        observed=False, fill_value=0,
    ).reindex(index=FAIXAS_ATRASO_LABELS, columns=rotulos, fill_value=0).fillna(0)
    amount_cat = base.pivot_table(
        index="faixa", columns="rotulo", values="total_due_amount", aggfunc="sum",
        observed=False, fill_value=0,
    ).reindex(index=FAIXAS_ATRASO_LABELS, columns=rotulos, fill_value=0).fillna(0)

    for rot in rotulos:
        tabela[f"Princ. {rot}"] = princ_cat[rot]
    total_principal = tabela["Principal"].sum()
    tabela["%"] = tabela["Principal"] / total_principal * 100 if total_principal else 0.0
    tabela = tabela[["Principal", "Amount"] + [f"Princ. {r}" for r in rotulos] + ["Qtde", "%"]]
    tabela.index.name = "Faixa de Atraso"
    tabela.loc["Total"] = tabela.sum()
    return tabela, amount_cat


def calcular_evolucao_npl90(df, npl_atual, hoje=None):
    """NPL 90 (sem e com WO) no fim de cada mês desde jan/25, reconstruído
    das colunas `npl_md_*`/`npl_sd_*` (atraso máximo e saldo em aberto por
    contrato naquela data). O último ponto é o dia de hoje e usa os valores
    ATUAIS (`npl_atual`, de `calcular_npl`) -- bate exatamente com os KPIs
    de "1. Visão Geral da Carteira"."""
    hoje = pd.Timestamp(hoje or pd.Timestamp.today().normalize())
    meses = sorted(
        c[len(PREFIXO_ATRASO_MENSAL):] for c in df.columns if c.startswith(PREFIXO_ATRASO_MENSAL)
    )
    mes_hoje = hoje.strftime("%Y-%m")
    linhas = []
    for m in meses:
        if m == mes_hoje:
            rotulo = f"{hoje.day:02d}/{MESES_PT[hoje.month]}/{str(hoje.year)[2:]}"
            npl90, npl90_wo = npl_atual["npl_90"], npl_atual["npl_90_wo"]
        else:
            md = df[f"{PREFIXO_ATRASO_MENSAL}{m}"]
            sd = df[f"{PREFIXO_SALDO_MENSAL}{m}"]
            aberto = sd > 0
            sem_wo = aberto & (md <= WO)
            em_wo = aberto & (md > WO)
            den_sem_wo = sd[sem_wo].sum()
            num_90 = sd[sem_wo & (md >= 90)].sum()
            den_com_wo = den_sem_wo + sd[em_wo].sum()
            npl90 = round(num_90 / den_sem_wo * 100, 2) if den_sem_wo else 0.0
            npl90_wo = round((num_90 + sd[em_wo].sum()) / den_com_wo * 100, 2) if den_com_wo else 0.0
            ano, mes = m.split("-")
            rotulo = f"{MESES_PT[int(mes)]}/{ano[2:]}"
        linhas.append({"Mês": rotulo, "NPL 90 s/ WO": npl90, "NPL 90 c/ WO": npl90_wo})
    return pd.DataFrame(linhas)


def calcular_evolucao_npl90_series(df, linhas, npl_total, npl_por_linha, hoje=None):
    """Evolução mensal do NPL 90 (sem e com WO) em formato LONGO: uma série
    para o 'Total' e uma para cada linha de crédito -- colunas 'Série',
    'Mês', 'NPL 90 s/ WO' e 'NPL 90 c/ WO'. O gráfico escolhe quais séries e
    quais tipos de NPL mostrar. Em cada série o último ponto (hoje) usa o
    NPL atual daquele recorte (`npl_total` / `npl_por_linha[linha]`)."""
    ev_total = calcular_evolucao_npl90(df, npl_total, hoje)
    ev_total.insert(0, "Série", "Total")
    partes = [ev_total]
    for linha in linhas:
        ev = calcular_evolucao_npl90(df[df["linha"] == linha], npl_por_linha[linha], hoje)
        ev.insert(0, "Série", linha)
        partes.append(ev)
    return pd.concat(partes, ignore_index=True)


def _aplicar_regua(atraso, regua):
    """(rótulo da faixa, % de provisão) de cada atraso (Series) segundo a régua."""
    faixas = PDD_REGUAS[regua]
    limites = [f[1] for f in faixas[:-1]]
    pos = np.digitize(atraso.to_numpy(dtype=float), limites, right=True)
    rotulos = np.array([f[0] for f in faixas], dtype=object)
    pcts = np.array([f[2] for f in faixas], dtype=float)
    return rotulos[pos], pcts[pos]


def calcular_pdd_contratos(df_bruto):
    """PDD de cada contrato-raiz com saldo em aberto, pela régua do FUNDO dele
    (aba 'Regras PDD' da planilha): Ghia (tabela da Ghia, maior atraso do
    DEVEDOR na Ghia), Kanastra (escala própria, maior atraso do CLIENTE em toda
    a CCB, todos os fundos), Oikos (maior atraso do contrato) e demais fundos
    (Res. CMN 2.682, maior atraso do contrato). O % da faixa vale para todo o
    saldo em aberto (`amount`) do contrato, inclusive parcelas vincendas.

    Recebe a base BRUTA (já filtrada por período, mas NÃO por produto/fundo):
    a PDD de um contrato não pode depender dos filtros da tela -- o atraso do
    Kanastra olha a CCB de todos os fundos, e o da Ghia, todos os contratos do
    devedor na Ghia. Os filtros são aplicados depois, em `resumir_pdd`.
    Contrato sem taxId conta como devedor próprio."""
    colunas = ["operationCode", "produto", "fundo", "regua", "devedor", "atraso_regua",
               "faixa", "pct", "saldo", "provisao"]
    base = df_bruto[df_bruto["total_due_amount"] > 0].copy()
    if not len(base):
        return pd.DataFrame(columns=colunas)

    base["devedor"] = base["taxId"].where(base["taxId"].notna(), base["operationCode"])
    base["regua"] = base["fundo"].map(regua_do_fundo)
    base["atraso_regua"] = base["max_delay"].astype(float)

    # Ghia: maior atraso do devedor entre os contratos DELE NA GHIA
    ghia = base["regua"] == REGUA_GHIA
    atraso_ghia = base[ghia].groupby("devedor")["max_delay"].max()
    base.loc[ghia, "atraso_regua"] = base.loc[ghia, "devedor"].map(atraso_ghia).astype(float)

    # Kanastra: maior atraso do cliente em TODA a CCB (qualquer fundo; inclui
    # contratos sem saldo -- atraso 0 -- e é independente do filtro de produto)
    kan = base["regua"] == REGUA_KANASTRA
    ccb = df_bruto[(df_bruto["produto"] == "CCB") & df_bruto["taxId"].notna()]
    atraso_ccb = ccb.groupby("taxId")["max_delay"].max()
    atraso_cli = base.loc[kan, "taxId"].map(atraso_ccb)
    base.loc[kan, "atraso_regua"] = np.fmax(base.loc[kan, "max_delay"].astype(float), atraso_cli.astype(float))

    base["faixa"] = None
    base["pct"] = 0.0
    for regua in PDD_REGUAS:
        m = base["regua"] == regua
        if m.any():
            faixa, pct = _aplicar_regua(base.loc[m, "atraso_regua"], regua)
            base.loc[m, "faixa"] = faixa
            base.loc[m, "pct"] = pct
    base["saldo"] = base["total_due_amount"].astype(float)
    base["provisao"] = base["saldo"] * base["pct"]
    return base[colunas].reset_index(drop=True)


def resumir_pdd(pdd_contratos, produtos=None, fundos=None):
    """Resume a PDD por contrato (`calcular_pdd_contratos`) para os produtos e
    fundos escolhidos (None = todos); os valores dos fundos são SOMADOS.

    Devolve dict com:
      - 'fundos': DataFrame por fundo (Régua, Contratos, Saldo, Provisão, % PDD)
        + linha 'Total';
      - 'faixas': {régua: DataFrame por faixa (Contratos, Devedores, Saldo,
        % PDD, Provisão) + 'Total'} só das réguas presentes na seleção;
      - 'total' (provisão total) e 'pct' (% do saldo em aberto)."""
    c = pdd_contratos
    if produtos is not None:
        c = c[c["produto"].isin(produtos)]
    if fundos is not None:
        c = c[c["fundo"].isin(fundos)]

    por_fundo = c.groupby("fundo").agg(
        Contratos=("operationCode", "size"), Saldo=("saldo", "sum"), Provisão=("provisao", "sum"),
    ).sort_values("Saldo", ascending=False)
    por_fundo.insert(0, "Régua", [PDD_UNIDADE_CURTA[regua_do_fundo(f)] for f in por_fundo.index])
    por_fundo["% PDD"] = np.where(por_fundo["Saldo"] > 0, por_fundo["Provisão"] / por_fundo["Saldo"] * 100, 0.0)
    por_fundo = por_fundo[["Régua", "Contratos", "Saldo", "% PDD", "Provisão"]]
    saldo_t, prov_t, n_t = c["saldo"].sum(), c["provisao"].sum(), len(c)
    pct_t = prov_t / saldo_t * 100 if saldo_t else 0.0
    por_fundo.index.name = "Fundo"
    por_fundo.loc["Total"] = ["", n_t, saldo_t, pct_t, prov_t]

    faixas = {}
    for regua, definicao in PDD_REGUAS.items():
        sub = c[c["regua"] == regua]
        if not len(sub):
            continue
        nomes = [f[0] for f in definicao]
        t = sub.groupby("faixa").agg(
            Contratos=("operationCode", "size"), Devedores=("devedor", "nunique"),
            Saldo=("saldo", "sum"), Provisão=("provisao", "sum"),
        ).reindex(nomes).fillna(0)
        t.insert(3, "% PDD", [f[2] * 100 for f in definicao])
        t.index.name = PDD_UNIDADE[regua]
        t.loc["Total"] = [
            t["Contratos"].sum(), sub["devedor"].nunique(), t["Saldo"].sum(),
            t["Provisão"].sum() / t["Saldo"].sum() * 100 if t["Saldo"].sum() else 0.0, t["Provisão"].sum(),
        ]
        faixas[regua] = t

    return {"fundos": por_fundo, "faixas": faixas, "total": float(prov_t), "pct": float(pct_t)}


PDD_UNIDADE_CURTA = {
    REGUA_GHIA: "Ghia (devedor)",
    REGUA_KANASTRA: "Kanastra (cliente na CCB)",
    REGUA_OIKOS: "Oikos (contrato)",
    REGUA_CMN: "Res. 2.682 (contrato)",
}


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------
def calcular_indicadores_executivo(df_bruto, produto="CCB", carteira="Carteira em aberto"):
    """Roda os filtros de produto/carteira + todos os indicadores a partir
    da base BRUTA já carregada em memória (não toca no banco) — permite
    trocar os filtros sem repetir a consulta ao Postgres.

    `produto`: "CCB", "CPR" ou uma lista/tupla com um ou os dois. Com UM
    produto, a 2ª camada de recorte ("categoria") é a linha de crédito —
    operationType pra CCB (App/Crédito Produtor), productType pra CPR; os
    dois significados não se misturam na mesma tabela. Com CCB + CPR
    juntos, a divisão passa a ser por PRODUTO (categorias = ["CCB",
    "CPR"]).
    `carteira`: "Carteira em aberto" / "WriteOff" / "Carteira total"
    (ver `filtrar_executivo`)."""
    produtos = normalizar_produtos(produto)
    df = rotular_categoria(filtrar_executivo(df_bruto, produto=produtos, carteira=carteira), produtos)
    categorias = categorias_do_produto(df_bruto, produtos)
    por_categoria = separar_por_categoria(df, categorias)

    resultados = {"produto": " + ".join(produtos), "produtos": list(produtos), "categorias": categorias}

    resultados["visao_geral"] = {"Total": calcular_visao_geral_negocio(df, "Total")}
    resultados["risco"] = {"Total": calcular_indicadores_risco_inadimplencia(df, "Total")}
    resultados["financeiro"] = {"Total": calcular_indicadores_financeiros(df, "Total")}
    resultados["safras"] = {"Total": calcular_analise_safras(df)}
    resultados["n_por_categoria"] = {}

    for cat in categorias:
        sub = por_categoria[cat]
        resultados["visao_geral"][cat] = calcular_visao_geral_negocio(sub, cat)
        resultados["risco"][cat] = calcular_indicadores_risco_inadimplencia(sub, cat)
        resultados["financeiro"][cat] = calcular_indicadores_financeiros(sub, cat)
        resultados["safras"][cat] = calcular_analise_safras(sub)
        resultados["n_por_categoria"][cat] = len(sub)

    resultados["n_total"] = len(df)
    resultados["n_ccb"] = int((df["produto"] == "CCB").sum())
    resultados["n_cpr"] = int((df["produto"] == "CPR").sum())

    # --- Tópicos 1 a 3 reformulados -----------------------------------------
    # Base "sem filtro de Carteira": só Produto (e Período, já aplicado pelo
    # chamador na base bruta). É necessária porque NPL c/ WO, faixas de
    # atraso, evolução e PDD incluem o write-off por definição.
    df_sem_filtro_carteira = rotular_categoria(
        df_bruto[df_bruto["produto"].isin(produtos)].reset_index(drop=True), produtos,
    )
    por_categoria_sf = separar_por_categoria(df_sem_filtro_carteira, categorias)

    # Linhas de crédito (App, Crédito Produtor, tipos de CPR...) de TODOS os
    # produtos selecionados. Com um produto só, são as próprias categorias;
    # com CCB + CPR, as categorias são os produtos e as linhas de crédito
    # aparecem à parte (colunas extras da seção 2, linhas da tabela de NPL e
    # séries do gráfico de evolução).
    linhas_por_produto = {p: categorias_do_produto(df_bruto, p) for p in produtos}
    linhas = linhas_de_credito(df_bruto, produtos)
    resultados["linhas"] = linhas

    npl_total = calcular_npl(df_sem_filtro_carteira)
    npl_cat = {cat: calcular_npl(por_categoria_sf[cat]) for cat in categorias}
    npl_linha = {
        l: calcular_npl(df_sem_filtro_carteira[df_sem_filtro_carteira["linha"] == l]) for l in linhas
    }

    resultados["kpis"] = {"Total": calcular_kpis_visao_geral(df, npl_total, "Total")}
    for cat in categorias:
        resultados["kpis"][cat] = calcular_kpis_visao_geral(por_categoria[cat], npl_cat[cat], cat)
    resultados["kpis_linhas"] = {
        l: calcular_kpis_visao_geral(df[df["linha"] == l], npl_linha[l], l) for l in linhas
    }

    resultados["npl"] = npl_total
    resultados["npl_tabela"] = calcular_npl_tabela(df_sem_filtro_carteira, produtos, linhas_por_produto)
    resultados["faixas_atraso"], resultados["faixas_atraso_amount"] = calcular_faixas_atraso(
        df_sem_filtro_carteira, categorias,
    )
    resultados["evolucao_npl90"] = calcular_evolucao_npl90_series(
        df_sem_filtro_carteira, linhas, npl_total, npl_linha,
    )
    # PDD: calculada por contrato na base COMPLETA (a régua do Kanastra/Ghia olha
    # o devedor em outros fundos/produtos); produto e fundo filtram depois.
    resultados["pdd_contratos"] = calcular_pdd_contratos(df_bruto)
    resultados["pdd"] = resumir_pdd(resultados["pdd_contratos"], produtos)
    resultados["pdd_total"] = resultados["pdd"]["total"]
    resultados["pdd_pct_saldo"] = resultados["pdd"]["pct"]
    # fundos com saldo em aberto (do maior pro menor saldo) -- opções do filtro de PDD
    saldo_por_fundo = (
        df_sem_filtro_carteira[df_sem_filtro_carteira["total_due_amount"] > 0]
        .groupby("fundo")["total_due_amount"].sum().sort_values(ascending=False)
    )
    resultados["fundos"] = saldo_por_fundo.index.tolist()

    return resultados


def gerar_indicadores_executivo(engine=None, produto="CCB", carteira="Carteira em aberto"):
    """Lê a base do banco e calcula todos os indicadores. Dentro do
    Streamlit, prefira cachear `carregar_dados_executivo_bruto`
    separadamente e chamar `calcular_indicadores_executivo` a cada troca
    de filtro — assim o banco só é consultado uma vez."""
    df_bruto = carregar_dados_executivo_bruto(engine)
    return calcular_indicadores_executivo(df_bruto, produto=produto, carteira=carteira)
