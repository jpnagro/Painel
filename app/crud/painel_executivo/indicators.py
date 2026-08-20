import numpy as np
import pandas as pd

from crud.painel_executivo.data import (
    carregar_dados_executivo_bruto,
    categorias_do_produto,
    filtrar_executivo,
    separar_por_categoria,
)

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
# Orquestração
# ---------------------------------------------------------------------------
def calcular_indicadores_executivo(df_bruto, produto="CCB", carteira="Carteira em aberto"):
    """Roda os filtros de produto/carteira + todos os indicadores a partir
    da base BRUTA já carregada em memória (não toca no banco) — permite
    trocar os filtros sem repetir a consulta ao Postgres.

    `produto`: "CCB" ou "CPR" (um por vez — a 2ª camada de recorte,
    "categoria", tem significado diferente em cada um: operationType
    pra CCB, productType pra CPR — não faz sentido misturar os dois na
    mesma tabela/gráfico).
    `carteira`: "Carteira em aberto" / "WriteOff" / "Carteira total"
    (ver `filtrar_executivo`)."""
    df = filtrar_executivo(df_bruto, produto=produto, carteira=carteira)
    categorias = categorias_do_produto(df_bruto, produto)
    por_categoria = separar_por_categoria(df, categorias)

    resultados = {"produto": produto, "categorias": categorias}

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

    return resultados


def gerar_indicadores_executivo(engine=None, produto="CCB", carteira="Carteira em aberto"):
    """Lê a base do banco e calcula todos os indicadores. Dentro do
    Streamlit, prefira cachear `carregar_dados_executivo_bruto`
    separadamente e chamar `calcular_indicadores_executivo` a cada troca
    de filtro — assim o banco só é consultado uma vez."""
    df_bruto = carregar_dados_executivo_bruto(engine)
    return calcular_indicadores_executivo(df_bruto, produto=produto, carteira=carteira)
