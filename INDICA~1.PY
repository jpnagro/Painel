"""
Indicadores de Crédito - Carteira SGC
======================================

Calcula os principais indicadores de crédito da carteira a partir do banco
SGC (tabelas ccb, cpr, installments, installments_cpr, client_data).

PREMISSAS IMPORTANTES (leia antes de usar)
-------------------------------------------
1. Contratos renegociados são EXCLUÍDOS de todos os indicadores principais.
   Filtro aplicado em toda a base: `renegotiated IS NOT TRUE` (equivalente a
   `NOT COALESCE(renegotiated, FALSE)` em pandas), pois o contrato original
   deixou de existir/representar a dívida real do cliente após a
   renegociação. Os contratos/parcelas renegociados são analisados em uma
   seção separada ("book de renegociações"), nunca somados aos indicadores
   principais.

2. A coluna `outstandingAmount` está defasada (em grande parte das parcelas
   em aberto ela vem NULL) e por isso NÃO é usada. Em seu lugar:
     - saldo_atual do CONTRATO  -> `beginningBalance` da parcela em aberto
       de menor `installmentNumber` (saldo devedor no início da parcela
       mais antiga ainda não paga). Contratos sem parcela em aberto
       (100% pagos) recebem saldo_atual = 0.
     - saldo a receber da PARCELA em aberto -> `adjustedAmount` (ou
       `amount` quando adjustedAmount é nulo) menos `paidAmount` já
       recebido (pagamento parcial). Usado para o NPL "por volume" e para
       taxas que dependem de valores nominais a receber.
   Caso a área de crédito tenha uma definição própria de "saldo devedor
   contábil", troque a função `saldo_atual_por_contrato()` — ela é o único
   ponto que precisa mudar.

3. Junção com `client_data`:
     - Para CCB, a chave exata é `client_data.ccbCode = ccb.operationCode`.
     - Para CPR, não há chave 1:1 confirmada (dealID != cpr.operationCode
       no formato observado); a junção é feita por `taxId` (aproximada,
       nível cliente). Se existir uma chave melhor para CPR, ajuste
       `juntar_client_data()`.

4. Não existe histórico mensal de status (apenas o snapshot atual de
   `delay`), portanto NÃO é possível calcular uma matriz de rolagem
   (roll-rate) real. Em substituição, o script calcula um proxy de
   "NPL por safra de originação" (vintage), que é o que os dados atuais
   permitem.

Requisitos: pip install pandas sqlalchemy psycopg2-binary openpyxl
"""

import os
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from app.core.config import URL_PG

pd.set_option("display.width", 140)
pd.set_option("display.max_columns", 30)


# ---------------------------------------------------------------------------
# 1. CONEXÃO E EXTRAÇÃO
# ---------------------------------------------------------------------------
def get_engine():
    """Cria a conexão com o Postgres do SGC.

    Configure via variável de ambiente SGC_DATABASE_URL, por exemplo:
        postgresql+psycopg2://usuario:senha@host:5432/nome_do_banco
    ou individualmente via SGC_DB_HOST / SGC_DB_PORT / SGC_DB_NAME /
    SGC_DB_USER / SGC_DB_PASSWORD.
    """

    return create_engine(URL_PG)


def carregar_dados(engine):
    """Lê as 5 tabelas do SGC por inteiro. Para bases muito grandes, troque
    por leitura em chunks ou filtre por período de releaseDate."""
    ccb = pd.read_sql('SELECT * FROM ccb', engine)
    cpr = pd.read_sql('SELECT * FROM cpr', engine)
    inst_ccb = pd.read_sql('SELECT * FROM installments', engine)
    inst_cpr = pd.read_sql('SELECT * FROM installments_cpr', engine)
    client = pd.read_sql('SELECT * FROM client_data', engine)
    return ccb, cpr, inst_ccb, inst_cpr, client


# ---------------------------------------------------------------------------
# 2. PREPARAÇÃO DAS BASES (unifica CCB+CPR e separa renegociados)
# ---------------------------------------------------------------------------
def _bool_true(serie):
    """Trata NULL como False ao interpretar colunas booleanas do SGC."""
    return serie.apply(lambda x: bool(x) if pd.notna(x) else False)


def preparar_bases(ccb, cpr, inst_ccb, inst_cpr):
    ccb = ccb.copy()
    ccb["produto"] = "CCB"
    cpr = cpr.copy()
    cpr["produto"] = "CPR"
    contratos = pd.concat([ccb, cpr], ignore_index=True, sort=False)
    contratos["renegociado_flag"] = _bool_true(contratos["renegotiated"])

    inst_ccb = inst_ccb.copy()
    inst_ccb["produto"] = "CCB"
    inst_cpr = inst_cpr.copy()
    inst_cpr["produto"] = "CPR"
    parcelas = pd.concat([inst_ccb, inst_cpr], ignore_index=True, sort=False)
    parcelas["renegociado_flag"] = _bool_true(parcelas["renegotiated"])

    contratos_ativos = contratos[~contratos["renegociado_flag"]].copy()
    contratos_reneg = contratos[contratos["renegociado_flag"]].copy()
    parcelas_ativos = parcelas[~parcelas["renegociado_flag"]].copy()
    parcelas_reneg = parcelas[parcelas["renegociado_flag"]].copy()

    return contratos, contratos_ativos, contratos_reneg, parcelas_ativos, parcelas_reneg


# ---------------------------------------------------------------------------
# 3. ESTADO ATUAL DE CADA CONTRATO (saldo + atraso), a partir das parcelas
# ---------------------------------------------------------------------------
def estado_por_contrato(parcelas):
    """Para cada operationCode: saldo_atual, saldo_a_receber, maior atraso,
    flags de default/writeoff/prePaid, a partir das parcelas em aberto.
    Contratos 100% quitados entram com saldo 0 e atraso 0."""
    p = parcelas.copy()
    p["paid"] = _bool_true(p["paid"])
    p["delay"] = p["delay"].fillna(0)

    abertas = p[~p["paid"]].copy()
    valor_ajustado = abertas["adjustedAmount"].fillna(abertas["amount"]).astype(float)
    abertas["saldo_receber_parcela"] = (
        valor_ajustado - abertas["paidAmount"].fillna(0).astype(float)
    ).clip(lower=0)

    # saldo_atual = beginningBalance da parcela em aberto mais antiga
    abertas_sorted = abertas.sort_values(["operationCode", "installmentNumber"])
    primeiro_aberto = (
        abertas_sorted.groupby("operationCode", as_index=False)
        .first()[["operationCode", "beginningBalance"]]
        .rename(columns={"beginningBalance": "saldo_atual"})
    )

    agregados = abertas.groupby("operationCode").agg(
        saldo_a_receber=("saldo_receber_parcela", "sum"),
        max_delay=("delay", "max"),
        n_parcelas_abertas=("delay", "size"),
        em_default=("default", lambda s: bool(_bool_true(s).any())),
        writeoff=("writeOff", lambda s: bool(_bool_true(s).any())),
    ).reset_index()

    estado = agregados.merge(primeiro_aberto, on="operationCode", how="left")

    # contratos totalmente quitados (sem nenhuma parcela em aberto)
    todos_ops = p["operationCode"].unique()
    quitados = set(todos_ops) - set(estado["operationCode"])
    if quitados:
        quit_df = pd.DataFrame({"operationCode": list(quitados)})
        for col, val in [
            ("saldo_a_receber", 0.0), ("max_delay", 0), ("n_parcelas_abertas", 0),
            ("em_default", False), ("writeoff", False), ("saldo_atual", 0.0),
        ]:
            quit_df[col] = val
        estado = pd.concat([estado, quit_df], ignore_index=True)

    estado["saldo_atual"] = estado["saldo_atual"].fillna(0)
    estado["quitado"] = estado["n_parcelas_abertas"] == 0
    estado["bucket_atraso"] = pd.cut(
        estado["max_delay"],
        bins=[-1, 0, 30, 60, 90, np.inf],
        labels=["0 - em dia", "1-30", "31-60", "61-90", "90+"],
    )
    return estado


def juntar_client_data(contratos_ativos, client):
    """Anexa atributos do tomador aos contratos. CCB junta por ccbCode
    (chave exata); CPR junta por taxId (aproximado, nível cliente)."""
    client = client.copy()
    # em caso de múltiplas linhas por taxId, mantém a de maior score_v4
    # não-nulo como representativa (critério simples e transparente)
    client_dedup = (
        client.sort_values("score_v4", na_position="first")
        .drop_duplicates(subset="taxId", keep="last")
    )

    ccb_part = contratos_ativos[contratos_ativos["produto"] == "CCB"].merge(
        client.rename(columns={"ccbCode": "operationCode"}),
        on="operationCode", how="left", suffixes=("", "_cli"),
    )
    cpr_part = contratos_ativos[contratos_ativos["produto"] == "CPR"].merge(
        client_dedup, on="taxId", how="left", suffixes=("", "_cli"),
    )
    return pd.concat([ccb_part, cpr_part], ignore_index=True, sort=False)


# ---------------------------------------------------------------------------
# 4. INDICADORES
# ---------------------------------------------------------------------------
def resumo_carteira(contratos_ativos, estado):
    saldo_total = estado["saldo_atual"].sum()
    valor_originado = contratos_ativos["totalLoan"].fillna(
        contratos_ativos["principalAmount"]
    ).sum()
    return pd.DataFrame([{
        "n_contratos_ativos": len(contratos_ativos),
        "n_contratos_com_saldo": int((estado["saldo_atual"] > 0).sum()),
        "n_contratos_quitados": int(estado["quitado"].sum()),
        "valor_originado_total": round(valor_originado, 2),
        "saldo_devedor_total": round(saldo_total, 2),
        "prazo_medio_meses": round(contratos_ativos["installments"].mean(), 1),
    }])


def mix_por_produto(contratos_ativos, estado):
    base = contratos_ativos[["operationCode", "produto"]].merge(estado, on="operationCode", how="left")
    return base.groupby("produto").agg(
        n_contratos=("operationCode", "count"),
        saldo_devedor=("saldo_atual", "sum"),
    ).reset_index()


def npl_por_faixa(contratos_ativos, estado, faixas=(15, 30, 60, 90)):
    """NPL em nível de CONTRATO: se qualquer parcela em aberto tem atraso
    >= faixa, o saldo devedor inteiro do contrato entra no NPL daquela
    faixa (metodologia padrão de mercado)."""
    base = estado[estado["saldo_atual"] > 0].copy()  # universo = carteira com saldo
    saldo_total = base["saldo_atual"].sum()
    n_total = len(base)

    linhas = []
    for f in faixas:
        em_npl = base["max_delay"] >= f
        linhas.append({
            "faixa": f"NPL {f}+",
            "n_contratos": int(em_npl.sum()),
            "pct_contratos": round(100 * em_npl.mean(), 2) if n_total else None,
            "saldo_npl": round(base.loc[em_npl, "saldo_atual"].sum(), 2),
            "pct_saldo": round(100 * base.loc[em_npl, "saldo_atual"].sum() / saldo_total, 2) if saldo_total else None,
        })
    return pd.DataFrame(linhas)


def distribuicao_aging(estado):
    base = estado[estado["saldo_atual"] > 0].copy()
    saldo_total = base["saldo_atual"].sum()
    g = base.groupby("bucket_atraso", observed=True).agg(
        n_contratos=("operationCode", "count"),
        saldo=("saldo_atual", "sum"),
    ).reset_index()
    g["pct_saldo"] = round(100 * g["saldo"] / saldo_total, 2) if saldo_total else np.nan
    return g


def taxa_default_fpd(contratos_ativos):
    default = _bool_true(contratos_ativos["default"])
    fpd = _bool_true(contratos_ativos["firstPaymentDefault"])
    return pd.DataFrame([{
        "taxa_default_contratos_pct": round(100 * default.mean(), 2),
        "taxa_fpd_pct": round(100 * fpd.mean(), 2),
    }])


def taxa_writeoff(contratos_ativos, estado):
    valor_originado = contratos_ativos["totalLoan"].fillna(contratos_ativos["principalAmount"]).sum()
    saldo_baixado = estado.loc[estado["writeoff"], "saldo_a_receber"].sum()
    n_baixados = int(estado["writeoff"].sum())
    return pd.DataFrame([{
        "n_contratos_com_baixa": n_baixados,
        "pct_contratos_com_baixa": round(100 * n_baixados / len(estado), 2) if len(estado) else None,
        "saldo_baixado_a_receber": round(saldo_baixado, 2),
        "pct_saldo_baixado_sobre_originado": round(100 * saldo_baixado / valor_originado, 2) if valor_originado else None,
    }])


def taxa_prepagamento_renovacao(contratos_ativos):
    prepaid = _bool_true(contratos_ativos["prePaid"])
    renewed_col = "renewed" if "renewed" in contratos_ativos.columns else "renewal"
    renewed = _bool_true(contratos_ativos[renewed_col])
    valor_originado = contratos_ativos["totalLoan"].fillna(contratos_ativos["principalAmount"]).sum()
    valor_prepago = contratos_ativos.loc[prepaid, "prePaidAmount"].fillna(0).sum()
    return pd.DataFrame([{
        "taxa_prepagamento_contratos_pct": round(100 * prepaid.mean(), 2),
        "valor_prepago": round(valor_prepago, 2),
        "pct_valor_prepago_sobre_originado": round(100 * valor_prepago / valor_originado, 2) if valor_originado else None,
        "taxa_renovacao_contratos_pct": round(100 * renewed.mean(), 2),
    }])


def npl_por_safra(contratos_ativos, estado):
    """Proxy de análise de safra: % em NPL90+ (snapshot atual) por mês de
    originação (releaseDate). Não é uma curva de maturação completa, pois
    o banco não guarda snapshots mensais de atraso — apenas o estado
    atual."""
    base = contratos_ativos[["operationCode", "releaseDate"]].merge(estado, on="operationCode", how="left")
    base = base.dropna(subset=["releaseDate"])
    base["safra"] = pd.to_datetime(base["releaseDate"]).dt.to_period("M").astype(str)
    base = base[base["saldo_atual"] > 0]
    g = base.groupby("safra").apply(
        lambda d: pd.Series({
            "n_contratos": len(d),
            "saldo_total": d["saldo_atual"].sum(),
            "saldo_npl90": d.loc[d["max_delay"] >= 90, "saldo_atual"].sum(),
        }),
        include_groups=False,
    ).reset_index()
    g["pct_npl90_saldo"] = round(100 * g["saldo_npl90"] / g["saldo_total"], 2)
    return g.sort_values("safra")


def rentabilidade(contratos_ativos, estado):
    base = contratos_ativos.merge(estado[["operationCode", "saldo_atual"]], on="operationCode", how="left")
    base = base[base["saldo_atual"] > 0]
    saldo_total = base["saldo_atual"].sum()
    yield_medio_mensal = (
        (base["monthlyRate"].fillna(0) * base["saldo_atual"]).sum() / saldo_total
        if saldo_total else None
    )
    yield_medio_anual = (
        (base["anualRate"].fillna(0) * base["saldo_atual"]).sum() / saldo_total
        if saldo_total else None
    )
    return pd.DataFrame([{
        "yield_medio_mensal_ponderado_pct": round(yield_medio_mensal, 3) if yield_medio_mensal is not None else None,
        "yield_medio_anual_ponderado_pct": round(yield_medio_anual, 3) if yield_medio_anual is not None else None,
        "receita_total": round(contratos_ativos["totalRevenue"].fillna(0).sum(), 2),
        "receita_originacao": round(contratos_ativos["originationRevenue"].fillna(0).sum(), 2),
        "receita_comercial": round(contratos_ativos["commercialRevenue"].fillna(0).sum(), 2),
        "receita_tesouraria": round(contratos_ativos["treasuryRevenue"].fillna(0).sum(), 2),
    }])


def concentracao_hhi(contratos_ativos, estado, coluna):
    """HHI (Índice Herfindahl-Hirschman) de concentração do saldo devedor
    por uma dimensão (ex.: taxId, cnaeFiltered, state, rating_v4).
    HHI perto de 0 = pulverizado; perto de 10.000 = muito concentrado."""
    base = contratos_ativos[["operationCode", coluna]].merge(estado, on="operationCode", how="left")
    base = base[base["saldo_atual"] > 0]
    por_grupo = base.groupby(coluna)["saldo_atual"].sum().sort_values(ascending=False)
    total = por_grupo.sum()
    part_pct = 100 * por_grupo / total
    hhi = (part_pct ** 2).sum()
    top10_pct = part_pct.head(10).sum()
    resumo = pd.DataFrame([{"HHI": round(hhi, 1), "pct_saldo_top10": round(top10_pct, 2)}])
    detalhe = part_pct.head(15).reset_index()
    detalhe.columns = [coluna, "pct_saldo"]
    return resumo, detalhe


def perfil_risco_cliente(contratos_ativos, estado, client):
    """Cruza NPL90+ com atributos cadastrais do cliente (rating, score,
    setor/CNAE, estado, restrições) para os contratos CCB, que têm chave
    exata com client_data (ccbCode = operationCode)."""
    com_cliente = juntar_client_data(contratos_ativos, client)
    com_cliente = com_cliente.merge(estado, on="operationCode", how="left")
    com_cliente = com_cliente[com_cliente["saldo_atual"] > 0]

    def resumo_por(col):
        g = com_cliente.groupby(col, dropna=False).apply(
            lambda d: pd.Series({
                "n_contratos": len(d),
                "saldo": d["saldo_atual"].sum(),
                "pct_npl90_saldo": round(
                    100 * d.loc[d["max_delay"] >= 90, "saldo_atual"].sum() / d["saldo_atual"].sum(), 2
                ) if d["saldo_atual"].sum() else None,
            }),
            include_groups=False,
        ).reset_index()
        return g.sort_values("saldo", ascending=False)

    por_rating = resumo_por("rating_v4")
    por_estado = resumo_por("state")
    por_setor = resumo_por("cnaeFiltered")

    restritivos = pd.DataFrame([{
        "pct_clientes_com_protesto": round(100 * (com_cliente["protestos"].fillna(0) > 0).mean(), 2),
        "pct_clientes_restritivo_nacional": round(100 * (com_cliente["restritivo_nacional"].fillna(0) > 0).mean(), 2),
        "pct_clientes_pep": round(100 * _bool_true(com_cliente["pep"]).mean(), 2),
        "pct_clientes_mandado_prisao": round(100 * (com_cliente["mandado_prisao"].fillna("Negativa") != "Negativa").mean(), 2),
        "pct_clientes_trabalho_escravo": round(100 * (com_cliente["trabalho_escravo"].fillna("Negativa") != "Negativa").mean(), 2),
    }])

    return por_rating, por_estado, por_setor, restritivos


# ---------------------------------------------------------------------------
# 5. BOOK DE RENEGOCIAÇÕES (análise separada, NUNCA somada ao restante)
# ---------------------------------------------------------------------------
def analise_renegociados(contratos, contratos_ativos, contratos_reneg, parcelas_reneg):
    total_geral = len(contratos)
    n_reneg = len(contratos_reneg)

    taxa_reneg = pd.DataFrame([{
        "n_contratos_renegociados": n_reneg,
        "n_contratos_total_historico": total_geral,
        "taxa_renegociacao_pct": round(100 * n_reneg / total_geral, 2) if total_geral else None,
        "valor_total_renegociado": round(
            contratos_reneg["totalLoan"].fillna(contratos_reneg["principalAmount"]).sum(), 2
        ),
    }])

    # estado dos contratos renegociados na última posição conhecida antes
    # de serem substituídos (para entender o quão deteriorados estavam)
    estado_reneg = estado_por_contrato(parcelas_reneg) if len(parcelas_reneg) else pd.DataFrame()
    if len(estado_reneg):
        perfil_antes = pd.DataFrame([{
            "n_contratos_com_estado": len(estado_reneg),
            "pct_estavam_em_default": round(100 * estado_reneg["em_default"].mean(), 2),
            "atraso_medio_dias": round(estado_reneg["max_delay"].mean(), 1),
            "pct_max_delay_90mais": round(100 * (estado_reneg["max_delay"] >= 90).mean(), 2),
        }])
    else:
        perfil_antes = pd.DataFrame()

    return taxa_reneg, perfil_antes


# ---------------------------------------------------------------------------
# 6. ORQUESTRAÇÃO
# ---------------------------------------------------------------------------
def gerar_todos_indicadores(engine=None):
    engine = engine or get_engine()
    ccb, cpr, inst_ccb, inst_cpr, client = carregar_dados(engine)
    contratos, contratos_ativos, contratos_reneg, parcelas_ativos, parcelas_reneg = preparar_bases(
        ccb, cpr, inst_ccb, inst_cpr
    )
    estado = estado_por_contrato(parcelas_ativos)

    resultados = {}
    resultados["resumo_carteira"] = resumo_carteira(contratos_ativos, estado)
    resultados["mix_produto"] = mix_por_produto(contratos_ativos, estado)
    resultados["npl_por_faixa"] = npl_por_faixa(contratos_ativos, estado)
    resultados["aging"] = distribuicao_aging(estado)
    resultados["default_fpd"] = taxa_default_fpd(contratos_ativos)
    resultados["writeoff"] = taxa_writeoff(contratos_ativos, estado)
    resultados["prepagamento_renovacao"] = taxa_prepagamento_renovacao(contratos_ativos)
    resultados["npl_por_safra"] = npl_por_safra(contratos_ativos, estado)
    resultados["rentabilidade"] = rentabilidade(contratos_ativos, estado)

    hhi_cliente_resumo, hhi_cliente_detalhe = concentracao_hhi(contratos_ativos, estado, "taxId")
    resultados["concentracao_cliente_resumo"] = hhi_cliente_resumo
    resultados["concentracao_cliente_top15"] = hhi_cliente_detalhe

    por_rating, por_estado_uf, por_setor, restritivos = perfil_risco_cliente(contratos_ativos, estado, client)
    resultados["npl_por_rating"] = por_rating
    resultados["npl_por_estado"] = por_estado_uf
    resultados["npl_por_setor"] = por_setor
    resultados["restricoes_cadastrais"] = restritivos

    taxa_reneg, perfil_reneg_antes = analise_renegociados(contratos, contratos_ativos, contratos_reneg, parcelas_reneg)
    resultados["renegociacao_taxa"] = taxa_reneg
    resultados["renegociacao_perfil_antes"] = perfil_reneg_antes

    return resultados


def exportar_excel(resultados, caminho=None):
    caminho = caminho or f"indicadores_credito_{datetime.now():%Y%m%d_%H%M}.xlsx"
    with pd.ExcelWriter(caminho, engine="openpyxl") as writer:
        for nome, df in resultados.items():
            if df is None or df.empty:
                continue
            df.to_excel(writer, sheet_name=nome[:31], index=False)
    print(f"Indicadores exportados para: {caminho}")


if __name__ == "__main__":
    engine = get_engine()
    resultados = gerar_todos_indicadores(engine)

    for nome, df in resultados.items():
        print("\n" + "=" * 80)
        print(nome.upper())
        print("=" * 80)
        print(df.to_string(index=False) if df is not None and not df.empty else "(sem dados)")

    exportar_excel(resultados)
