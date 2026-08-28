import pandas as pd
import numpy as np

from crud.carteira.data import (
    _bool_true,
    aplicar_filtro_periodo,
    aplicar_filtro_portfolio,
    aplicar_subfiltro_ccb,
    aplicar_subfiltro_cpr,
    carregar_dados,
    estado_por_contrato,
    get_engine,
    juntar_client_data,
    preparar_bases,
)


# ---------------------------------------------------------------------------
# 4. INDICADORES
# ---------------------------------------------------------------------------

def resumo_carteira(contratos_ativos, contratos_originais, parcelas_ativos, estado, npl=90):

    valor_originado = contratos_originais["principalAmount"].sum()

    set_contratos_ativos = set(list(contratos_ativos['operationCode']) + list(contratos_originais['operationCode'])) # Aqui considera renegociação e renegociado
    parcelas_ativas_total = parcelas_ativos[parcelas_ativos['operationCode'].isin(set_contratos_ativos)]

    saldo_total = estado["saldo_atual"].sum()
    valor_pago = parcelas_ativas_total['paidAmount'].sum()
    valor_total_parcelas = contratos_originais['totalLoan'].sum()

    base = estado[estado["saldo_atual"] > 0].copy()
    em_npl = base["max_delay"] >= npl
    saldo_npl = base.loc[em_npl, "saldo_atual"].sum()

    return pd.DataFrame([{
        "n_contratos": len(contratos_originais),
        "valor_originado_total": round(valor_originado, 2),
        "valor_total_parcelas": round(valor_total_parcelas, 2),
        "valor_pago": round(valor_pago, 2),
        "saldo_devedor_total": round(saldo_total, 2),
        "saldo_npl": round(saldo_npl, 2),
        "prazo_medio_meses": round(contratos_originais["installments"].mean(), 1),
    }])

def resumo_carteira_aberta(contratos_ativos, estado, parcelas_ativos, wo=360, npl=90):
    """Carteira em aberto (não quitada), EXCLUINDO contratos em write-off
    — esses são reportados à parte em `resumo_carteira_writeoff`."""

    estado_n_pago = estado[~estado['quitado'] & (estado['max_delay'] < wo)].copy()
    ops_em_aberto = set(estado_n_pago['operationCode'])

    contratos_ativos_n_pago = contratos_ativos[contratos_ativos['operationCode'].isin(ops_em_aberto)]

    parcelas_ativas_contratos_em_aberto = parcelas_ativos[parcelas_ativos['operationCode'].isin(ops_em_aberto)]

    saldo_total = estado_n_pago["saldo_atual"].sum()
    valor_originado = contratos_ativos_n_pago["principalAmount"].sum()
    valor_pago = parcelas_ativas_contratos_em_aberto['paidAmount'].sum()
    valor_total_parcelas = parcelas_ativas_contratos_em_aberto['amount'].sum()

    em_npl = estado_n_pago["max_delay"] >= npl
    saldo_npl = estado_n_pago.loc[em_npl, "saldo_atual"].sum()

    return pd.DataFrame([{
        "n_contratos": len(contratos_ativos_n_pago),
        "valor_originado_total": round(valor_originado, 2),
        "valor_total_parcelas": round(valor_total_parcelas, 2),
        "valor_pago": round(valor_pago, 2),
        "saldo_devedor_total": round(saldo_total, 2),
        "saldo_npl": round(saldo_npl, 2),
        "prazo_medio_meses": round(contratos_ativos_n_pago["installments"].mean(), 1),
    }])

def resumo_carteira_writeoff(contratos_ativos, estado, parcelas_ativos, wo=360):
    """Mesmos 6 indicadores de `resumo_carteira_aberta`, mas olhando só
    para os contratos em write-off (`estado.writeoff` = True — ou seja,
    contratos com alguma parcela em aberto marcada como baixada a
    prejuízo)."""

    estado_writeoff = estado[estado['max_delay'] >= wo].copy()
    ops_writeoff = set(estado_writeoff['operationCode'])

    contratos_ativos_wo = contratos_ativos[contratos_ativos['operationCode'].isin(ops_writeoff)].copy()

    set_contratos_wo = list(contratos_ativos_wo['operationCode'])
    parcelas_ativas_writeoff = parcelas_ativos[parcelas_ativos['operationCode'].isin(set_contratos_wo)]

    saldo_total = estado_writeoff["saldo_atual"].sum()
    valor_originado = contratos_ativos_wo["principalAmount"].sum()
    valor_pago = parcelas_ativas_writeoff['paidAmount'].sum()
    valor_total_parcelas = parcelas_ativas_writeoff['amount'].sum()

    return pd.DataFrame([{
        "n_contratos": len(contratos_ativos_wo),
        "valor_originado_total": round(valor_originado, 2),
        "valor_total_parcelas": round(valor_total_parcelas, 2),
        "valor_pago": round(valor_pago, 2),
        "saldo_devedor_total": round(saldo_total, 2),
        "saldo_npl": round(saldo_total, 2),
        "prazo_medio_meses": round(contratos_ativos_wo["installments"].mean(), 1) if len(contratos_ativos_wo) else None,
    }])


def mix_por_produto(contratos_ativos, estado):

    base = contratos_ativos[["operationCode", "produto"]].merge(estado, on="operationCode", how="left")
    
    return base.groupby("produto").agg(
        n_contratos=("operationCode", "count"),
        saldo_devedor=("saldo_atual", "sum"),
    ).reset_index()


def npl_por_faixa(estado, faixas=(15, 30, 60, 90), wo=360):
    """NPL em nível de CONTRATO: se qualquer parcela em aberto tem atraso
    >= faixa, o saldo devedor inteiro do contrato entra no NPL daquela
    faixa (metodologia padrão de mercado)."""

    base = estado[estado["saldo_atual"] > 0].copy()  # universo = carteira com saldo
    base = base[base["max_delay"] < wo].copy()
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


def distribuicao_aging(estado, wo=360):

    base = estado[estado["saldo_atual"] > 0].copy()
    base = base[base["max_delay"] < wo].copy()
    saldo_total = base["saldo_atual"].sum()
    g = base.groupby("bucket_atraso", observed=True).agg(
        n_contratos=("operationCode", "count"),
        saldo=("saldo_atual", "sum"),
    ).reset_index()
    g["pct_saldo"] = round(100 * g["saldo"] / saldo_total, 2) if saldo_total else float("nan")

    return g


def taxa_default_fpd(contratos_ativos):

    default = _bool_true(contratos_ativos["default"])
    fpd = _bool_true(contratos_ativos["firstPaymentDefault"])

    return pd.DataFrame([{
        "taxa_default_contratos_pct": round(100 * default.mean(), 2),
        "taxa_fpd_pct": round(100 * fpd.mean(), 2),
    }])


def taxa_writeoff(contratos_originais, estado, wo=360):

    valor_originado = contratos_originais["totalLoan"].sum()
    saldo_baixado = estado.loc[estado["max_delay"] >= wo, "saldo_a_receber"].sum()
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


def taxa_renegociados(contratos_originais):

    renegotiated = _bool_true(contratos_originais['renegotiated'])

    return pd.DataFrame([{"pct_renegociado": round(100 * renegotiated.mean(), 2)}])


def gerar_snapshots_mensais(parcelas, data_referencia=None, freq="ME"):
    """Reconstrói, para cada parcela, o atraso implícito em cada fim de mês
    desde a menor `dueDate` da base até `data_referencia` (hoje, por
    padrão) — SEM depender de nenhum histórico salvo. Usa só `dueDate`,
    `paymentDate` e `paid`, que já validamos no banco (paymentDate
    preenchida em 100% das parcelas pagas, e delay = paymentDate - dueDate).

    Regra por parcela, numa data de corte S:
      - S < dueDate                    -> ainda não tinha vencido (atraso = 0)
      - paga até S (paymentDate <= S)  -> já estava quitada (atraso = 0)
      - senão (vencida e ainda em aberto em S) -> atraso = (S - dueDate) dias

    Retorna uma tabela larga: uma linha por parcela, colunas 'YYYY-MM'
    (uma por fim de mês), valor = atraso em dias naquele mês.
    Aviso de desempenho: para carteiras muito grandes (>1M parcelas x
    muitos anos de histórico), considere `freq="QE"` (trimestral) para
    reduzir o número de colunas.

    Se `parcelas` tiver as colunas `vigencia_inicio`/`vigencia_fim` (como
    `parcelas_com_vigencia`, vindo de `preparar_bases`), uma parcela só
    contribui pro atraso num mês S se S estiver dentro da janela em que
    ela realmente valeu: [vigencia_inicio, vigencia_fim). Isso evita que
    uma renegociação feita, por exemplo, em jan/25 "vaze" pra trás e
    afete meses anteriores a ela (ago/24 deve ver só o contrato original,
    que ainda não tinha sido renegociado naquela data).
    """

    p = parcelas.copy()
    if len(p) == 0:
        # base vazia (ex.: filtro de portfolio sem nenhum selecionado) —
        # sem parcela nenhuma não tem "dueDate" mínima pra ancorar o
        # range de meses, então devolve direto uma tabela vazia.
        return pd.DataFrame(columns=["operationCode"])

    p["dueDate"] = pd.to_datetime(p["dueDate"])
    p["paymentDate"] = pd.to_datetime(p["paymentDate"])
    p["paid"] = _bool_true(p["paid"])

    tem_vigencia = "vigencia_inicio" in p.columns and "vigencia_fim" in p.columns
    if tem_vigencia:
        p["vigencia_inicio"] = pd.to_datetime(p["vigencia_inicio"])
        p["vigencia_fim"] = pd.to_datetime(p["vigencia_fim"]).fillna(pd.Timestamp("2100-01-01"))

    data_referencia = pd.Timestamp(data_referencia or pd.Timestamp.today().normalize())
    inicio = p["dueDate"].min().to_period("M").to_timestamp()
    datas_corte = pd.date_range(inicio, data_referencia, freq=freq)
    if len(datas_corte) == 0 or datas_corte[-1] < data_referencia:
        datas_corte = datas_corte.append(pd.DatetimeIndex([data_referencia]))

    due = p["dueDate"].values.astype("datetime64[D]")
    sentinela_futuro = np.datetime64("2100-01-01")
    resolucao = np.where(p["paid"].values, p["paymentDate"].values, sentinela_futuro).astype("datetime64[D]")
    datas_arr = datas_corte.values.astype("datetime64[D]")

    vencida = datas_arr[np.newaxis, :] >= due[:, np.newaxis]
    ainda_aberta = datas_arr[np.newaxis, :] < resolucao[:, np.newaxis]
    em_atraso = vencida & ainda_aberta
    dias_atraso = (datas_arr[np.newaxis, :] - due[:, np.newaxis]).astype("timedelta64[D]").astype(int)
    matriz_atraso = np.where(em_atraso, dias_atraso, 0)

    if tem_vigencia:
        vig_ini = p["vigencia_inicio"].values.astype("datetime64[D]")
        vig_fim = p["vigencia_fim"].values.astype("datetime64[D]")
        vigente = (
            (datas_arr[np.newaxis, :] >= vig_ini[:, np.newaxis])
            & (datas_arr[np.newaxis, :] < vig_fim[:, np.newaxis])
        )
        matriz_atraso = np.where(vigente, matriz_atraso, 0)

    colunas = [d.strftime("%Y-%m") for d in datas_corte]
    resultado = pd.DataFrame(matriz_atraso, columns=colunas)
    resultado.insert(0, "operationCode", p["operationCode"].values)
    return resultado


def max_delay_mensal_por_contrato(parcelas, data_referencia=None):
    """Agrega o atraso implícito (de `gerar_snapshots_mensais`) ao nível de
    CONTRATO: o pior atraso entre as parcelas daquele contrato, em cada
    fim de mês. Index = operationCode, colunas = 'YYYY-MM'."""
    snapshots = gerar_snapshots_mensais(parcelas, data_referencia=data_referencia)
    colunas_meses = [c for c in snapshots.columns if c != "operationCode"]
    if not colunas_meses:
        return pd.DataFrame(columns=["operationCode"]).set_index("operationCode")
    return snapshots.groupby("operationCode")[colunas_meses].max()


def saldo_aberto_mensal_por_contrato(parcelas, data_referencia=None, freq="ME"):
    """Para cada contrato, soma do `amount` das parcelas que AINDA NÃO
    tinham sido pagas até cada fim de mês — é o mesmo conceito de
    `saldo_atual` do `estado_por_contrato`, só que reconstruído
    historicamente (mês a mês) em vez de calculado só para hoje.

    Usado para medir o valor REALMENTE em risco de um contrato NPL: um
    contrato com 90+ dias de atraso pode já ter pago boa parte das
    parcelas, então usar o valor originado inteiro como "valor em NPL"
    superestima a exposição. Aqui só entra o que ainda está de fato em
    aberto naquele momento.

    Assim como em `gerar_snapshots_mensais`, se `parcelas` tiver
    `vigencia_inicio`/`vigencia_fim`, uma parcela só entra no saldo de um
    mês S se S estiver dentro da janela em que ela realmente valeu."""

    p = parcelas.copy()
    if len(p) == 0:
        return pd.DataFrame(columns=["operationCode"]).set_index("operationCode")

    p["paymentDate"] = pd.to_datetime(p["paymentDate"])
    p["dueDate"] = pd.to_datetime(p["dueDate"])
    p["paid"] = _bool_true(p["paid"])

    tem_vigencia = "vigencia_inicio" in p.columns and "vigencia_fim" in p.columns
    if tem_vigencia:
        p["vigencia_inicio"] = pd.to_datetime(p["vigencia_inicio"])
        p["vigencia_fim"] = pd.to_datetime(p["vigencia_fim"]).fillna(pd.Timestamp("2100-01-01"))

    data_referencia = pd.Timestamp(data_referencia or pd.Timestamp.today().normalize())
    inicio = p["dueDate"].min().to_period("M").to_timestamp()
    datas_corte = pd.date_range(inicio, data_referencia, freq=freq)
    if len(datas_corte) == 0 or datas_corte[-1] < data_referencia:
        datas_corte = datas_corte.append(pd.DatetimeIndex([data_referencia]))

    sentinela_futuro = np.datetime64("2100-01-01")
    resolucao = np.where(p["paid"].values, p["paymentDate"].values, sentinela_futuro).astype("datetime64[D]")
    datas_arr = datas_corte.values.astype("datetime64[D]")

    ainda_nao_paga = datas_arr[np.newaxis, :] < resolucao[:, np.newaxis]
    amount = p["amount"].astype(float).values
    matriz_saldo = ainda_nao_paga * amount[:, np.newaxis]

    if tem_vigencia:
        vig_ini = p["vigencia_inicio"].values.astype("datetime64[D]")
        vig_fim = p["vigencia_fim"].values.astype("datetime64[D]")
        vigente = (
            (datas_arr[np.newaxis, :] >= vig_ini[:, np.newaxis])
            & (datas_arr[np.newaxis, :] < vig_fim[:, np.newaxis])
        )
        matriz_saldo = np.where(vigente, matriz_saldo, 0.0)

    colunas = [d.strftime("%Y-%m") for d in datas_corte]
    resultado = pd.DataFrame(matriz_saldo, columns=colunas)
    resultado.insert(0, "operationCode", p["operationCode"].values)

    colunas_meses = [c for c in resultado.columns if c != "operationCode"]
    return resultado.groupby("operationCode")[colunas_meses].sum()


def _status_mensal_longo(contratos_ativos, max_delay_mensal, saldo_aberto_mensal=None):
    """Formato longo (operationCode, mes_corte, max_delay, bucket, safra,
    idade_meses, valor_originado[, saldo_aberto]), já filtrado para meses
    a partir da originação de cada contrato (idade_meses >= 0). Base comum
    usada tanto pela curva de maturação quanto pela matriz de rolagem.

    Bin de 89 (não 90) faz o bucket "90+" = max_delay >= 90, mesma
    convenção usada em npl_por_faixa e em estado_por_contrato (evita que
    um contrato com atraso exatamente 90 caia em "61-90" na matriz de
    rolagem, o que descolaria o bucket "90+" dela do NPL90+ do resto do
    dashboard)."""
    bins = [-1, 0, 30, 60, 89, np.inf]
    labels = ["0 - em dia", "1-30", "31-60", "61-89", "90+"]

    info = contratos_ativos[["operationCode", "releaseDate"]].copy()
    info["releaseDate"] = pd.to_datetime(info["releaseDate"])
    info["safra"] = info["releaseDate"].dt.to_period("M").astype(str)
    info["valor_originado"] = contratos_ativos["totalLoan"].fillna(contratos_ativos["principalAmount"]).values

    longo = max_delay_mensal.reset_index().melt(
        id_vars="operationCode", var_name="mes_corte", value_name="max_delay"
    )
    longo = longo.merge(info, on="operationCode", how="inner")

    if saldo_aberto_mensal is not None:
        saldo_longo = saldo_aberto_mensal.reset_index().melt(
            id_vars="operationCode", var_name="mes_corte", value_name="saldo_aberto"
        )
        longo = longo.merge(saldo_longo, on=["operationCode", "mes_corte"], how="left")

    longo["mes_corte_dt"] = pd.to_datetime(longo["mes_corte"])
    longo["idade_meses"] = (
        (longo["mes_corte_dt"].dt.year - longo["releaseDate"].dt.year) * 12
        + (longo["mes_corte_dt"].dt.month - longo["releaseDate"].dt.month)
    )
    longo = longo[longo["idade_meses"] >= 0].copy()
    longo["bucket"] = pd.cut(longo["max_delay"], bins=bins, labels=labels)
    return longo


def curva_maturacao_safra(contratos_ativos, max_delay_mensal, saldo_aberto_mensal, faixa_npl=90):
    """Curva de maturação real: para cada safra (mês de originação) e
    idade em meses desde a originação, % do valor originado que está
    REALMENTE em aberto (ainda não pago) em contratos com atraso >=
    faixa_npl naquele momento. O denominador (valor_originado) é fixo, o
    tamanho original da safra — isso permite comparar safras na MESMA
    idade (ex.: safra de jan/25 com 6 meses de vida vs. safra de mar/25
    também com 6 meses de vida). Já o numerador (valor_npl) usa o saldo
    das parcelas ainda em aberto, não o valor originado do contrato
    inteiro — um contrato 90+ dias atrasado pode já ter pago boa parte
    das parcelas, e contar o valor cheio como "em NPL" superestimaria a
    exposição real."""
    longo = _status_mensal_longo(contratos_ativos, max_delay_mensal, saldo_aberto_mensal)

    g = longo.groupby(["safra", "idade_meses"]).agg(
        n_contratos=("operationCode", "nunique"),
        valor_originado=("valor_originado", "sum"),
    ).reset_index()
    npl = (
        longo[longo["max_delay"] >= faixa_npl]
        .groupby(["safra", "idade_meses"])["saldo_aberto"].sum()
        .reset_index(name="valor_npl")
    )
    g = g.merge(npl, on=["safra", "idade_meses"], how="left")
    g["valor_npl"] = g["valor_npl"].fillna(0)
    g["pct_npl_valor_originado"] = round(100 * g["valor_npl"] / g["valor_originado"], 2)
    return g.sort_values(["safra", "idade_meses"])


def matriz_rolagem(contratos_ativos, max_delay_mensal):
    """Matriz de transição mês a mês entre faixas de atraso (roll-rate),
    agregada (pooled) ao longo de todo o histórico: de cada bucket em que
    o contrato estava num mês, para qual bucket ele foi no mês seguinte.
    Só considera meses a partir da originação de cada contrato (evita
    contar "transições" de antes do contrato existir)."""
    
    longo = _status_mensal_longo(contratos_ativos, max_delay_mensal)
    bucket_wide = longo.pivot(index="operationCode", columns="mes_corte", values="bucket")

    meses_ordenados = sorted(bucket_wide.columns)
    transicoes = []
    for m_atual, m_seguinte in zip(meses_ordenados[:-1], meses_ordenados[1:]):
        pares = bucket_wide[[m_atual, m_seguinte]].dropna()
        pares.columns = ["de", "para"]
        transicoes.append(pares)

    if not transicoes:
        return pd.DataFrame(columns=["de", "para", "n", "pct"])

    todas = pd.concat(transicoes, ignore_index=True)
    contagem = todas.groupby(["de", "para"], observed=True).size().reset_index(name="n")
    contagem["pct"] = round(
        100 * contagem["n"] / contagem.groupby("de", observed=True)["n"].transform("sum"), 2
    )
    return contagem.sort_values(["de", "para"])


def rentabilidade(contratos_ativos, estado):
    """`monthlyRate`/`anualRate` no banco vêm como fração decimal (ex.:
    0.063552 = 6,3552% ao mês), não como número de percentual — por isso
    multiplicamos por 100 aqui, senão o yield fica errado por um fator de
    100 quando exibido como "%" (0,04% em vez de 4%, por exemplo)."""

    base = contratos_ativos.merge(estado[["operationCode", "saldo_atual"]], on="operationCode", how="left")
    base = base[base["saldo_atual"] > 0]
    saldo_total = base["saldo_atual"].sum()
    yield_medio_mensal = (
        100 * (base["monthlyRate"].fillna(0) * base["saldo_atual"]).sum() / saldo_total
        if saldo_total else None
    )
    yield_medio_anual = (
        100 * (base["anualRate"].fillna(0) * base["saldo_atual"]).sum() / saldo_total
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


def perfil_risco_cliente(contratos_ativos, estado, client, wo=360):
    """Cruza NPL90+ com atributos cadastrais do cliente (rating, score,
    setor/CNAE, estado, restrições) para os contratos CCB, que têm chave
    exata com client_data (ccbCode = operationCode).

    Usa o mesmo universo de `npl_por_faixa` (saldo_atual > 0 e max_delay <
    wo) — sem esse segundo filtro, os contratos em write-off (max_delay >=
    360, sempre 100% NPL90+ por definição) entravam no numerador E no
    denominador de cada categoria, inflando o NPL90+ por Rating/UF/CNAE
    acima do NPL90+ geral, que exclui write-off por ser reportado à parte."""

    com_cliente = juntar_client_data(contratos_ativos, client)
    com_cliente = com_cliente.merge(estado, on="operationCode", how="left")
    com_cliente = com_cliente[com_cliente["saldo_atual"] > 0]
    com_cliente = com_cliente[com_cliente["max_delay"] < wo]

    def resumo_por(col):
        if com_cliente.empty:
            # groupby(...).apply(...) numa base vazia não executa a lambda
            # nem uma vez, então não tem como inferir as colunas do
            # resultado — devolve direto uma tabela vazia com o formato
            # esperado (acontece com filtros que zeram a carteira, ex.:
            # nenhum portfolio selecionado no multiselect).
            return pd.DataFrame(columns=[col, "n_contratos", "saldo", "pct_npl90_saldo"])
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
def analise_renegociados(contratos, contratos_originais, parcelas_reneg, parcelas_ativos):

    renegotiated = _bool_true(contratos_originais['renegotiated'])
    colunas_estado_vazio = [
        "operationCode", "saldo_a_receber", "max_delay", "n_parcelas_abertas",
        "em_default", "writeoff", "saldo_atual", "quitado", "bucket_atraso",
    ]
    estado_reneg = estado_por_contrato(parcelas_reneg) if len(parcelas_reneg) else pd.DataFrame(columns=colunas_estado_vazio)
    contratos_reneg = contratos_originais[contratos_originais['renegotiated'] == True]

    parcelas_reneg_ativos = parcelas_ativos[parcelas_ativos['renegotiation'] == True]

    # com o filtro de produto (CCB/CPR), o subconjunto escolhido pode não
    # ter NENHUM contrato renegociado (ex.: só CPR, sem renegociações) —
    # nesse caso estado_reneg já vem sem a coluna 'operationCode' preenchida,
    # então o filtro abaixo simplesmente resulta vazio, sem quebrar.
    estado_reneg_filt = estado_reneg[estado_reneg['operationCode'].isin(contratos_reneg['operationCode'])]

    total_geral = len(contratos)
    n_reneg = renegotiated.sum()

    taxa_reneg = pd.DataFrame([{
        "n_contratos_renegociados": n_reneg,
        "n_contratos_total_historico": total_geral,
        "taxa_renegociacao_pct": round(100 * renegotiated.mean(), 2) if total_geral else None,
        "valor_total_renegociado": round(estado_reneg_filt["saldo_atual"].sum(), 2),
        "valor_total_parcelas": round(parcelas_reneg_ativos['amount'].sum(), 2),
        "valor_pago": round(parcelas_reneg_ativos[parcelas_reneg_ativos['paid'] == True]['paidAmount'].sum(), 2),
        "saldo_devedor": round(parcelas_reneg_ativos[parcelas_reneg_ativos['paid'] != True]['amount'].sum(), 2)
    }])

    # estado dos contratos renegociados na última posição conhecida antes
    # de serem substituídos (para entender o quão deteriorados estavam)
    if len(estado_reneg_filt):
        perfil_antes = pd.DataFrame([{
            "n_contratos_com_estado": len(estado_reneg_filt),
            "pct_estavam_em_default": round(100 * estado_reneg_filt["em_default"].mean(), 2),
            "atraso_medio_dias": round(estado_reneg_filt["max_delay"].mean(), 1),
            "pct_max_delay_90mais": round(100 * (estado_reneg_filt["max_delay"] >= 90).mean(), 2),
        }])
    else:
        perfil_antes = pd.DataFrame()

    return taxa_reneg, perfil_antes


# ---------------------------------------------------------------------------
# 6. ORQUESTRAÇÃO
# ---------------------------------------------------------------------------
def calcular_indicadores(
    ccb, cpr, inst_ccb, inst_cpr, client,
    produtos=("CCB", "CPR"), subfiltro_ccb=None, subfiltro_cpr=None, portfolios=None,
    data_inicio=None, data_fim=None,
):
    """Roda a preparação das bases + todos os indicadores a partir de
    tabelas JÁ CARREGADAS em memória (não toca no banco) — permite trocar
    os filtros sem repetir a consulta ao Postgres, que é a parte mais
    lenta do processo. Todos os filtros abaixo são aplicados ANTES de
    montar contratos/parcelas, então todo o pipeline (renegociação,
    vigência, saldo, NPL, curva de maturação etc.) já roda restrito ao
    que foi selecionado — nenhuma função de indicador individual precisa
    saber dos filtros.

    `produtos`: quais produtos considerar — subconjunto de {"CCB", "CPR"}
    (lista/tupla/set). Vazio = carteira vazia (equivalente ao antigo
    "Ambos" era `produtos=("CCB","CPR")`, o padrão).

    `subfiltro_ccb`: lista de client_data.operationType a manter (ex.:
    ["App"]) quando "CCB" está em `produtos`, ou None = sem filtro
    (todos). Lista vazia = nenhum contrato CCB passa.

    `subfiltro_cpr`: mesma ideia, mas pra cpr.productType, quando "CPR"
    está em `produtos`.

    `portfolios` é o filtro mais "de fora" (acima do de produto): lista de
    portfolios (installments.portfolio / installments_cpr.portfolio) a
    considerar, ou None pra não filtrar. Aplicado ANTES dos filtros de
    produto/subfiltro, então vale pra CCB e CPR ao mesmo tempo.

    `data_inicio`/`data_fim`: restringe aos contratos cuja RAIZ foi
    originada (releaseDate) dentro desse intervalo (ver
    `aplicar_filtro_periodo`). `None` em qualquer um dos dois = sem limite
    daquele lado; os dois `None` = sem filtro (todo o histórico)."""
    ccb, cpr, inst_ccb, inst_cpr = aplicar_filtro_portfolio(ccb, cpr, inst_ccb, inst_cpr, portfolios)
    ccb, cpr, inst_ccb, inst_cpr = aplicar_filtro_periodo(
        ccb, cpr, inst_ccb, inst_cpr, data_inicio=data_inicio, data_fim=data_fim
    )

    produtos = set(produtos) if produtos is not None else {"CCB", "CPR"}
    if "CCB" not in produtos:
        ccb, inst_ccb = ccb.iloc[0:0], inst_ccb.iloc[0:0]
    else:
        ccb, inst_ccb = aplicar_subfiltro_ccb(ccb, inst_ccb, client, subfiltro_ccb)

    if "CPR" not in produtos:
        cpr, inst_cpr = cpr.iloc[0:0], inst_cpr.iloc[0:0]
    else:
        cpr, inst_cpr = aplicar_subfiltro_cpr(cpr, inst_cpr, subfiltro_cpr)

    (
        contratos, contratos_ativos, contratos_reneg, contratos_originais,
        parcelas_ativos, parcelas_reneg, parcelas_com_vigencia,
    ) = preparar_bases(ccb, cpr, inst_ccb, inst_cpr)
    estado = estado_por_contrato(parcelas_ativos)

    resultados = {}
    resultados["resumo_carteira"] = resumo_carteira(contratos_ativos, contratos_originais, parcelas_ativos, estado)
    resultados["resumo_carteira_aberta"] = resumo_carteira_aberta(contratos_ativos, estado, parcelas_ativos)
    resultados["resumo_carteira_writeoff"] = resumo_carteira_writeoff(contratos_ativos, estado, parcelas_ativos)
    resultados["mix_produto"] = mix_por_produto(contratos_ativos, estado)
    resultados["npl_por_faixa"] = npl_por_faixa(estado)
    resultados["aging"] = distribuicao_aging(estado)
    resultados["default_fpd"] = taxa_default_fpd(contratos_ativos)
    resultados["writeoff"] = taxa_writeoff(contratos_originais, estado)
    resultados["prepagamento_renovacao"] = taxa_prepagamento_renovacao(contratos_ativos)
    resultados["taxa_renegociados"] = taxa_renegociados(contratos_originais)

    max_delay_mensal = max_delay_mensal_por_contrato(parcelas_com_vigencia)
    saldo_aberto_mensal = saldo_aberto_mensal_por_contrato(parcelas_com_vigencia)
    resultados["curva_maturacao_safra"] = curva_maturacao_safra(
        contratos_ativos, max_delay_mensal, saldo_aberto_mensal
    )
    resultados["matriz_rolagem"] = matriz_rolagem(contratos_ativos, max_delay_mensal)

    resultados["rentabilidade"] = rentabilidade(contratos_ativos, estado)

    hhi_cliente_resumo, hhi_cliente_detalhe = concentracao_hhi(contratos_ativos, estado, "taxId")
    resultados["concentracao_cliente_resumo"] = hhi_cliente_resumo
    resultados["concentracao_cliente_top15"] = hhi_cliente_detalhe

    por_rating, por_estado_uf, por_setor, restritivos = perfil_risco_cliente(contratos_ativos, estado, client)
    resultados["npl_por_rating"] = por_rating
    resultados["npl_por_estado"] = por_estado_uf
    resultados["npl_por_setor"] = por_setor
    resultados["restricoes_cadastrais"] = restritivos

    taxa_reneg, perfil_reneg_antes = analise_renegociados(contratos, contratos_originais, parcelas_reneg, parcelas_ativos)
    resultados["renegociacao_taxa"] = taxa_reneg
    resultados["renegociacao_perfil_antes"] = perfil_reneg_antes

    return resultados


def gerar_todos_indicadores(
    engine=None, produtos=("CCB", "CPR"), subfiltro_ccb=None, subfiltro_cpr=None, portfolios=None,
):
    """Lê as tabelas do banco e calcula todos os indicadores. Para uso
    fora do Streamlit (ex.: scripts de teste). Dentro do app, prefira
    cachear `carregar_dados` separadamente e chamar `calcular_indicadores`
    a cada troca de filtro — assim o banco só é consultado uma vez."""
    engine = engine or get_engine()
    ccb, cpr, inst_ccb, inst_cpr, client = carregar_dados(engine)
    return calcular_indicadores(
        ccb, cpr, inst_ccb, inst_cpr, client,
        produtos=produtos, subfiltro_ccb=subfiltro_ccb, subfiltro_cpr=subfiltro_cpr, portfolios=portfolios,
    )
