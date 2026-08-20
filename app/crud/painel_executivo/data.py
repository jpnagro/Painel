import numpy as np
import pandas as pd

from crud.carteira.data import (
    _bool_true,
    carregar_dados,
    estado_por_contrato,
    get_engine,
    juntar_client_data,
    preparar_bases,
)

# ---------------------------------------------------------------------------
# Fonte e metodologia: os indicadores (Composição da Carteira, Indicadores
# de Risco e Financeiros, Análise por Safra) são portados de
# app/functions/carteira_functions.py do projeto "ai-assistant" (relatório
# de referência, template 3.html, tópicos 1 a 6). MAS a base de dados por
# trás é a MESMA da aba "Análise da carteira" (`preparar_bases` +
# `estado_por_contrato`, de crud/carteira/data.py) — não uma consulta SQL
# própria — justamente pra garantir que os dois lugares deem os mesmos
# números. Isso substitui uma versão anterior deste módulo que tinha sua
# própria query SQL com uma heurística de renegociação mais simples
# (REGEXP_REPLACE do prefixo "R" no operationCode) e um critério de
# write-off baseado só na flag booleana installments.writeOff — os dois
# davam números diferentes dos da aba "Análise da carteira" (validada) e
# foram abandonados.
#
# Pontos da metodologia, alinhados com crud/carteira:
#   - Renegociação: consolidada pelo `externalId` (não por regex) — ver
#     `preparar_bases`. "Valor Total Emprestado (R$)" é sempre somado
#     sobre `contratos_originais` (só a raiz, SEM as renegociações — o
#     dinheiro só é concedido uma vez, na originação); os demais
#     indicadores (pago, saldo, atraso) usam `parcelas_ativos`, que já
#     está remapeado pra raiz e CONSIDERA as parcelas de todas as
#     gerações (original + renegociações).
#   - Write-off: mesmo corte de atraso usado em toda a aba "Análise da
#     carteira" (`max_delay >= 360` dias — ver `resumo_carteira_aberta`/
#     `resumo_carteira_writeoff`/`npl_por_faixa`, todos com `wo=360` por
#     padrão). NÃO usa a flag booleana installments.writeOff pra decidir
#     o balde de carteira (ela só é informativa, dentro de `estado`).
#   - rating_v4: o filtro que descartava contratos CCB sem rating_v4 foi
#     REMOVIDO — a aba "Análise da carteira" (referência) nunca filtrou
#     por isso, então mantê-lo aqui só criaria mais uma divergência.
#   - A dimensão de categoria (2ª camada de recorte, abaixo do Total) é
#     diferente por produto: para CCB são os dois valores de
#     client_data.operationType ("App"/"Crédito Produtor" — join exato
#     por ccbCode); para CPR é o "productType" da própria tabela cpr.
#     Não são combinadas: o filtro de Produto é um radio (só CCB OU só
#     CPR por vez). `categoria` é a coluna que já carrega o valor certo
#     pra cada linha (operationType se CCB, productType se CPR).
#   - Saldo devedor "de principal" (outstanding_principal) continua sendo
#     a soma do PRINCIPAL (não do valor cheio da parcela) das parcelas em
#     aberto — isso é uma escolha deliberada do relatório de referência
#     (indicadores financeiros/PDD são "de principal"), mantida aqui;
#     mas agora calculada a partir de `parcelas_ativos` (a mesma base
#     validada), não de uma query própria.
# ---------------------------------------------------------------------------

CARTEIRAS = ["Carteira em aberto", "WriteOff", "Carteira total"]

CATEGORIAS_CCB = ["App", "Crédito Produtor"]

WO = 360  # corte de dias de atraso pra write-off, igual ao resto do app


def _agregados_parcela(parcelas_ativos):
    """Agregados por operationCode (já raiz — `parcelas_ativos` vem de
    `preparar_bases`, remapeado e restrito às parcelas vigentes, mesma
    base usada por `estado_por_contrato`). Complementa o `estado` (que só
    agrega "amount") com os agregados de PRINCIPAL que os indicadores
    financeiros do Painel Executivo usam."""
    p = parcelas_ativos.copy()
    p["paid"] = _bool_true(p["paid"])
    p["delay"] = pd.to_numeric(p["delay"], errors="coerce").fillna(0)
    for c in ["principalAmount", "amount", "paidAmount"]:
        p[c] = pd.to_numeric(p[c], errors="coerce").fillna(0)

    p["paid_principal_row"] = np.where(p["paid"], p["principalAmount"], 0.0)
    p["outstanding_principal_row"] = np.where(~p["paid"], p["principalAmount"], 0.0)
    p["total_paid_amount_row"] = np.where(p["paid"], p["paidAmount"], 0.0)
    p["total_due_amount_row"] = np.where(~p["paid"], p["amount"], 0.0)
    p["overdue_principal_90_row"] = np.where((~p["paid"]) & (p["delay"] >= 90), p["principalAmount"], 0.0)

    if not len(p):
        return pd.DataFrame(columns=[
            "total_installment_amount", "total_paid_amount", "total_due_amount",
            "paid_principal", "outstanding_principal", "overdue_principal_90",
        ]).rename_axis("operationCode")

    return p.groupby("operationCode").agg(
        total_installment_amount=("amount", "sum"),
        total_paid_amount=("total_paid_amount_row", "sum"),
        total_due_amount=("total_due_amount_row", "sum"),
        paid_principal=("paid_principal_row", "sum"),
        outstanding_principal=("outstanding_principal_row", "sum"),
        overdue_principal_90=("overdue_principal_90_row", "sum"),
    )


def carregar_dados_executivo_bruto(engine=None):
    """Lê e prepara a base BRUTA do Painel Executivo a partir das MESMAS
    tabelas/consolidação usadas na aba "Análise da carteira"
    (`preparar_bases` + `estado_por_contrato`) — CCB + CPR, TODOS os
    estados de carteira (aberta, quitada, write-off). É a parte lenta
    (consulta ao Postgres); os filtros de carteira/produto são aplicados
    depois, em memória, por `filtrar_executivo`."""
    engine = engine or get_engine()

    ccb, cpr, inst_ccb, inst_cpr, client = carregar_dados(engine)
    (
        _contratos, _contratos_ativos, _contratos_reneg, contratos_originais,
        parcelas_ativos, _parcelas_reneg, _parcelas_com_vigencia,
    ) = preparar_bases(ccb, cpr, inst_ccb, inst_cpr)
    estado = estado_por_contrato(parcelas_ativos)

    df = juntar_client_data(contratos_originais, client)
    df = df.merge(_agregados_parcela(parcelas_ativos), on="operationCode", how="left")
    df = df.merge(
        estado[["operationCode", "max_delay", "quitado"]], on="operationCode", how="left",
    )

    df["releaseDate"] = pd.to_datetime(df["releaseDate"])
    if "firstPaymentDefault" in df.columns:
        df["firstPaymentDefault"] = df["firstPaymentDefault"].astype("boolean")

    num_cols = [
        "principalAmount", "totalLoan", "totalInterest", "monthlyRate", "score_v4",
        "total_installment_amount", "total_paid_amount", "total_due_amount",
        "paid_principal", "outstanding_principal", "overdue_principal_90", "max_delay",
    ]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ["total_installment_amount", "total_paid_amount", "total_due_amount",
              "paid_principal", "outstanding_principal", "overdue_principal_90", "max_delay"]:
        df[c] = df[c].fillna(0)
    # merge com `estado` pode deixar "quitado" como NaN pra contratos sem
    # NENHUMA parcela (edge case real, não coberto nos testes sintéticos
    # anteriores) -- isso faz a coluna virar dtype "object" (bool + NaN
    # não convive em dtype bool nativo do pandas). `.fillna` sozinho NÃO
    # recasta pra bool; a coluna ficava "object" e `~df["quitado"]` virava
    # um bitwise invert em inteiro (~True/~False = -2/-1 em Python puro),
    # quebrando a indexação booleana com KeyError. `.astype(bool)` no
    # final garante dtype bool de verdade.
    df["quitado"] = df["quitado"].fillna(True).astype(bool)

    df["default_90p_flag"] = (df["max_delay"] >= 90).astype(int)
    df["default_60p_flag"] = (df["max_delay"] >= 60).astype(int)
    df["default_30p_flag"] = (df["max_delay"] >= 30).astype(int)
    df["default_15p_flag"] = (df["max_delay"] >= 15).astype(int)

    # `categoria`: operationType pra CCB, productType pra CPR (ver nota no
    # topo do arquivo). `productType` só existe de fato pra linhas CPR —
    # o merge com client_data não adiciona essa coluna; ela já vem do
    # próprio cpr (herdada de `contratos_originais`).
    if "productType" not in df.columns:
        df["productType"] = np.nan
    df["categoria"] = np.where(df["produto"] == "CCB", df["operationType"], df["productType"])
    return df


def filtrar_executivo(df, produto="CCB", carteira="Carteira em aberto"):
    """Aplica, em memória (sem tocar o banco), os filtros de produto
    (CCB/CPR) e de carteira sobre a base bruta.

    `produto`: "CCB" ou "CPR".
    `carteira`: "Carteira em aberto" (não quitado e max_delay < 360 —
    mesmo corte de `resumo_carteira_aberta`), "WriteOff" (max_delay >=
    360 — mesmo corte de `resumo_carteira_writeoff`) ou "Carteira total"
    (sem filtro nenhum de estado — todo o histórico, igual
    `resumo_carteira`)."""
    out = df[df["produto"] == produto]

    if carteira == "Carteira em aberto":
        out = out[(~out["quitado"]) & (out["max_delay"] < WO)]
    elif carteira == "WriteOff":
        out = out[out["max_delay"] >= WO]
    # "Carteira total": sem filtro de estado

    return out.copy().reset_index(drop=True)


def categorias_do_produto(df, produto):
    """Lista de categorias (2ª camada de recorte) pro produto selecionado.

    CCB: fixo em App/Crédito Produtor (client_data.operationType).
    CPR: derivado dinamicamente dos valores de productType presentes na
    base (evita hardcode — se algum novo tipo aparecer no banco, já cai
    aqui automaticamente)."""
    if produto == "CCB":
        return CATEGORIAS_CCB
    return sorted(df.loc[df["produto"] == "CPR", "categoria"].dropna().unique().tolist())


def separar_por_categoria(df, categorias):
    """Divide a base em um dict {categoria: sub-dataframe}, usando a
    coluna `categoria` (operationType pra CCB, productType pra CPR — ver
    nota no topo do arquivo). Linhas sem correspondência de categoria
    (ex.: CCB sem client_data) não entram em nenhuma categoria, só no
    Total."""
    return {cat: df[df["categoria"] == cat].copy() for cat in categorias}
