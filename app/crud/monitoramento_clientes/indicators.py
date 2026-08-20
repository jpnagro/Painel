import pandas as pd

from crud.carteira.data import SEM_CLIENT_DATA
from crud.painel_executivo.data import WO

# ---------------------------------------------------------------------------
# Ordem de rating (Nagro): AA é o melhor, H é o pior.
# ---------------------------------------------------------------------------
RATING_ORDER = ["AA", "A", "B", "C", "D", "E", "F", "G", "H"]
RATING_ORDEM = {r: i for i, r in enumerate(RATING_ORDER)}

# Métricas de "dívidas/atraso externo" (pergunta 1) — quanto maior, pior.
METRICAS_DIVIDA_ATRASO = ["overdue", "loss", "debts_bv", "protests_bv", "protests"]

NOME_METRICA = {
    "overdue": "Valor em atraso (overdue)",
    "loss": "Prejuízo registrado (loss)",
    "debts_bv": "Dívidas no mercado (debts_bv)",
    "protests_bv": "Protestos — Boa Vista (protests_bv)",
    "protests": "Protestos (protests)",
    "rating": "Rating",
    "credit_portfolio": "Exposição de crédito no mercado (credit_portfolio)",
}

# Indicadores considerados na priorização de risco (watchlist). O
# credit_portfolio fica de fora da contagem de "indicadores piorando" —
# ele é tratado como um sinal de contexto (aumento de exposição no
# mercado), não como algo inequivocamente ruim por si só (ver `view.py`).
INDICADORES_RISCO = METRICAS_DIVIDA_ATRASO + ["rating"]

TOLERANCIA_MONETARIA = 0.01


def classificar_delta(atual, anterior, maior_e_pior=True, tolerancia=TOLERANCIA_MONETARIA):
    """Classifica a variação de uma métrica numérica entre dois registros.

    `maior_e_pior=True`  -> "Piorou"/"Melhorou" (dívidas, atrasos, perdas).
    `maior_e_pior=False` -> "Aumentou"/"Diminuiu" (métricas neutras, como
    credit_portfolio, em que crescer não é por si só bom ou mau)."""
    if pd.isna(atual) or pd.isna(anterior):
        return "Sem dados"
    delta = atual - anterior
    if abs(delta) < tolerancia:
        return "Estável"
    if maior_e_pior:
        return "Piorou" if delta > 0 else "Melhorou"
    return "Aumentou" if delta > 0 else "Diminuiu"


def classificar_rating(atual, anterior):
    """Compara dois ratings pela ordem AA (melhor) -> H (pior)."""
    ordem_atual = RATING_ORDEM.get(atual)
    ordem_anterior = RATING_ORDEM.get(anterior)
    if ordem_atual is None or ordem_anterior is None:
        return "Sem dados"
    if ordem_atual == ordem_anterior:
        return "Estável"
    return "Piorou" if ordem_atual > ordem_anterior else "Melhorou"


# ---------------------------------------------------------------------------
# 2. PAREAMENTO: registro mais recente x imediatamente anterior, por contrato
# ---------------------------------------------------------------------------
def construir_pares(df):
    """Para cada `operationCode_raiz` (a relação de crédito consolidada —
    raiz + eventuais renegociações, ver `data.py`), isola o registro mais
    recente ("atual") e o registro imediatamente anterior a ele
    ("anterior"), considerando TODO o histórico de consultas daquela
    relação, mesmo que tenha sido feito sob `operationCode` de gerações
    diferentes (ex.: uma consulta na raiz antes de renegociar e outra na
    renegociação depois) — sem isso, essas consultas ficariam fragmentadas
    em dois contratos "sem histórico" isolados em vez de uma trajetória
    comparável.

    Relações com apenas 1 consulta no total (`tem_historico=False`) não
    têm base de comparação ainda — ficam de fora dos indicadores de
    variação, mas continuam contadas no total monitorado. O `operationCode`
    específico de cada consulta (`operationCode_atual`/`_anterior`) é
    preservado no resultado, pra saber de qual geração cada lado do par
    veio."""
    df = df.sort_values(["operationCode_raiz", "createdAt"]).reset_index(drop=True)

    n_registros = df.groupby("operationCode_raiz").size().rename("n_registros")

    atual = df.groupby("operationCode_raiz", as_index=False).tail(1).set_index("operationCode_raiz")
    cnt_do_fim = df.groupby("operationCode_raiz").cumcount(ascending=False)
    anterior = df[cnt_do_fim == 1].set_index("operationCode_raiz")

    pares = atual.join(anterior, how="left", lsuffix="_atual", rsuffix="_anterior")
    pares = pares.join(n_registros)
    pares["tem_historico"] = pares["n_registros"] >= 2
    pares["dias_entre_registros"] = (
        pares["createdAt_atual"] - pares["createdAt_anterior"]
    ).dt.days

    return pares.reset_index()


def calcular_status_pares(pares):
    """Adiciona, para cada par, o status (Piorou/Melhorou/Estável/Sem
    dados/Sem histórico) de cada métrica monitorada."""
    p = pares.copy()

    for m in METRICAS_DIVIDA_ATRASO:
        p[f"status_{m}"] = p.apply(
            lambda r, m=m: (
                classificar_delta(r[f"{m}_atual"], r[f"{m}_anterior"])
                if r["tem_historico"]
                else "Sem histórico"
            ),
            axis=1,
        )

    p["status_rating"] = p.apply(
        lambda r: (
            classificar_rating(r["rating_atual"], r["rating_anterior"])
            if r["tem_historico"]
            else "Sem histórico"
        ),
        axis=1,
    )

    p["status_credit_portfolio"] = p.apply(
        lambda r: (
            classificar_delta(r["credit_portfolio_atual"], r["credit_portfolio_anterior"], maior_e_pior=False)
            if r["tem_historico"]
            else "Sem histórico"
        ),
        axis=1,
    )

    status_cols = [f"status_{m}" for m in INDICADORES_RISCO]
    p["n_indicadores_piorando"] = (p[status_cols] == "Piorou").sum(axis=1)
    p["n_indicadores_melhorando"] = (p[status_cols] == "Melhorou").sum(axis=1)
    p["indicadores_piorando"] = p[status_cols].apply(
        lambda row: ", ".join(
            NOME_METRICA[m] for m, s in zip(INDICADORES_RISCO, row) if s == "Piorou"
        ),
        axis=1,
    )

    return p


# ---------------------------------------------------------------------------
# 3. RESUMOS PARA OS GRÁFICOS/KPIs
# ---------------------------------------------------------------------------
STATUS_ORDER_RISCO = ["Piorou", "Estável", "Melhorou", "Sem dados", "Sem histórico"]
STATUS_ORDER_NEUTRO = ["Aumentou", "Estável", "Diminuiu", "Sem dados", "Sem histórico"]


def resumo_status_metricas(pares_status, metricas, status_order=STATUS_ORDER_RISCO):
    linhas = []
    for m in metricas:
        contagem = pares_status[f"status_{m}"].value_counts()
        for status in status_order:
            linhas.append({
                "metrica": NOME_METRICA[m],
                "status": status,
                "n_contratos": int(contagem.get(status, 0)),
            })
    return pd.DataFrame(linhas)


def transicao_rating(pares_status):
    """Matriz de transição: de qual rating o contrato veio (linha) para
    qual foi no registro mais recente (coluna) — só contratos com
    histórico e rating preenchido nos dois registros."""
    p = pares_status[pares_status["tem_historico"]].dropna(subset=["rating_atual", "rating_anterior"])
    if p.empty:
        return pd.DataFrame()
    tab = pd.crosstab(p["rating_anterior"], p["rating_atual"])
    ordem = [r for r in RATING_ORDER if r in tab.index or r in tab.columns]
    tab = tab.reindex(index=ordem, columns=ordem, fill_value=0)
    return tab


# ---------------------------------------------------------------------------
# 4. WATCHLIST — priorização de contratos que pioraram
# ---------------------------------------------------------------------------
def construir_watchlist(pares_status, min_indicadores=1):
    """Contratos com histórico e ao menos `min_indicadores` métricas de
    risco piorando desde a consulta anterior, ordenados por severidade
    (nº de indicadores piorando) e depois por exposição (valor
    originado) — a lista de prioridade para acompanhamento/cobrança."""
    p = pares_status[pares_status["tem_historico"]].copy()
    watchlist = p[p["n_indicadores_piorando"] >= min_indicadores].sort_values(
        ["n_indicadores_piorando", "valor_originado_atual"], ascending=[False, False]
    )
    return watchlist


def historico_contrato(df_bruto, operation_code_raiz):
    """Todo o histórico de consultas (não só o par mais recente) de uma
    relação de crédito — raiz + eventuais renegociações, todas com o mesmo
    `operationCode_raiz` — usado na visão de trajetória individual. Ordena
    por `createdAt`, então consultas feitas sob a raiz e sob uma
    renegociação aparecem juntas, na ordem cronológica real."""
    return df_bruto[df_bruto["operationCode_raiz"] == operation_code_raiz].sort_values("createdAt")


# ---------------------------------------------------------------------------
# 5. FILTRO DE CARTEIRA — mesma semântica da aba "Painel Executivo"
# ---------------------------------------------------------------------------
def aplicar_filtro_carteira(base, executivo_bruto, carteira):
    """Filtra os contratos monitorados por estado de carteira, reaproveitando
    a base já tratada (consolidação de renegociação + `quitado`/`max_delay`)
    da aba "Painel Executivo" (`crud/painel_executivo/data.py`) — a mesma
    lógica e o mesmo corte de write-off (`WO` = 360 dias) usados lá, pra não
    reimplementar (e não divergir de) como o resto do Painel decide o que é
    "em aberto" ou "write-off".

    `carteira`: "Carteira em aberto" (não quitado e max_delay < WO),
    "WriteOff" (max_delay >= WO) ou "Carteira total" (sem filtro — inclui
    também os já quitados).

    O cruzamento é feito por `operationCode_raiz` (não pelo `operationCode`
    bruto da consulta) — a base do Painel Executivo só tem uma linha por
    RAIZ de relação de crédito, então uma consulta feita sob o código de
    uma geração de renegociação não seria encontrada se cruzássemos pelo
    `operationCode` bruto (era exatamente esse o bug antes desta função
    passar a receber `operationCode_raiz` já calculado em `data.py`).
    Ainda assim, contratos cujo `operationCode_raiz` não é encontrado na
    base do Painel Executivo (caso raríssimo de inconsistência entre as
    bases) só aparecem em "Carteira total" — sem o estado consolidado, não
    dá pra dizer se estão em aberto ou em write-off."""
    if carteira == "Carteira total":
        return base

    estado = executivo_bruto.set_index("operationCode")[["quitado", "max_delay"]]
    estado = estado[~estado.index.duplicated(keep="first")]
    m = base.join(estado, on="operationCode_raiz", how="left")

    if carteira == "Carteira em aberto":
        mask = (~m["quitado"].fillna(True)) & (m["max_delay"].fillna(WO) < WO)
    elif carteira == "WriteOff":
        mask = m["max_delay"].fillna(0) >= WO
    else:
        mask = pd.Series(True, index=base.index)

    return base[mask.values]


# ---------------------------------------------------------------------------
# 5b. SUB-FILTRO DE TIPO (CCB/CPR) e STATUS DE INADIMPLÊNCIA — mesma lógica
#     da aba "Análise da carteira"
# ---------------------------------------------------------------------------
def aplicar_subfiltro_tipo(base, subfiltro_ccb, subfiltro_cpr):
    """Sub-filtro por "Tipo de operação (CCB)" (`client_data.operationType`
    — "App"/"Crédito Produtor"/`SEM_CLIENT_DATA`) e "Tipo de produto (CPR)"
    (`cpr.productType`) — mesmas opções e mesma fonte da aba "Análise da
    carteira" (`crud/carteira/data.py`), já pré-calculadas por
    `carregar_monitoramento_bruto` a partir da RAIZ de cada contrato.

    `subfiltro_ccb`/`subfiltro_cpr`: lista de valores a manter, ou `None`
    quando aquele produto nem está selecionado no filtro "Produto"
    principal (nesse caso a coluna correspondente é irrelevante e não
    filtra nada). Lista vazia filtra esse produto inteiro pra fora (nenhum
    valor marcado no multiselect)."""
    mask = pd.Series(True, index=base.index)

    if subfiltro_ccb is not None:
        is_ccb = base["produto_atual"] == "CCB"
        ccb_ok = base["tipo_operacao_ccb_atual"].isin(subfiltro_ccb)
        if SEM_CLIENT_DATA in subfiltro_ccb:
            ccb_ok = ccb_ok | base["tipo_operacao_ccb_atual"].isna()
        mask &= (~is_ccb) | ccb_ok

    if subfiltro_cpr is not None:
        is_cpr = base["produto_atual"] == "CPR"
        cpr_ok = base["tipo_produto_cpr_atual"].isin(subfiltro_cpr)
        mask &= (~is_cpr) | cpr_ok

    return base[mask]


def classificar_status_carteira(base, executivo_bruto):
    """Classifica cada contrato em "Carteira Inadimplente" (em aberto —
    não quitado e sem atingir o corte de write-off, `max_delay < WO` — E
    com atraso, `max_delay > 0`) ou "Carteira Adimplente" (todo o
    restante: quitados, write-off, ou em aberto mas em dia). Reaproveita
    `quitado`/`max_delay` da base do Painel Executivo — mesma fonte e
    mesmo corte (`WO`) usados em `aplicar_filtro_carteira`."""
    estado = executivo_bruto.set_index("operationCode")[["quitado", "max_delay"]]
    estado = estado[~estado.index.duplicated(keep="first")]
    m = base.join(estado, on="operationCode_raiz", how="left")

    em_aberto = (~m["quitado"].fillna(True)) & (m["max_delay"].fillna(WO) < WO)
    inadimplente = em_aberto & (m["max_delay"].fillna(0) > 0)

    status = pd.Series("Carteira Adimplente", index=base.index)
    status[inadimplente] = "Carteira Inadimplente"
    return status


# ---------------------------------------------------------------------------
# 6. SNAPSHOTS POR PERÍODO — filtro 1 (análise) vs. filtro 2 (referência)
# ---------------------------------------------------------------------------
# Cada filtro é um período [início, fim]. Um contrato "entra" no período se
# teve ao menos uma consulta em customer_monitoring com createdAt dentro do
# intervalo (isso decide QUEM é contado); o VALOR usado para esse contrato,
# porém, é sempre o registro mais recente já acumulado até o FIM do
# período (isso decide QUANTO vale) — mesmo que a consulta mais recente
# tenha sido feita antes do início do período. É a semântica combinada com
# o usuário: "o contrato que entrou no primeiro filtro deverá ter todo seu
# histórico até o dia [fim do período]".
DIST_STATUS_ORDER = ["Com valor em aberto", "Zerado", "Sem dados"]

STATUS_ORDER_COMPARACAO_RISCO = ["Piorou", "Estável", "Melhorou", "Sem dados"]
STATUS_ORDER_COMPARACAO_NEUTRO = ["Aumentou", "Estável", "Diminuiu", "Sem dados"]


def snapshot_no_periodo(df_bruto, inicio, fim):
    """Snapshot de cada relação de crédito (`operationCode_raiz`) "no
    período" [inicio, fim]: cohort = quem teve ao menos uma consulta com
    `createdAt` dentro do intervalo; valor = o registro mais recente com
    `createdAt` <= fim (todo o histórico acumulado até o fim do período),
    acompanhado de `n_registros_ate_fim` (quantas consultas aquela relação
    já teve, no total, até essa data — usado para saber se já havia base
    de comparação naquele momento). Indexado por `operationCode_raiz` para
    facilitar o cruzamento entre dois snapshots (`comparar_periodos_*`)."""
    d = df_bruto.copy()
    d["_data"] = d["createdAt"].dt.date

    cohort_mask = (d["_data"] >= inicio) & (d["_data"] <= fim)
    cohort_ids = set(d.loc[cohort_mask, "operationCode_raiz"].unique())
    if not cohort_ids:
        vazio = df_bruto.iloc[0:0].copy()
        vazio["n_registros_ate_fim"] = pd.Series(dtype="int64")
        return vazio.set_index("operationCode_raiz", drop=False)

    ate_fim = d[d["operationCode_raiz"].isin(cohort_ids) & (d["_data"] <= fim)].sort_values(
        ["operationCode_raiz", "createdAt"]
    )
    n_registros_ate_fim = ate_fim.groupby("operationCode_raiz").size().rename("n_registros_ate_fim")
    snap = ate_fim.groupby("operationCode_raiz", as_index=False).tail(1).drop(columns=["_data"])
    snap = snap.set_index("operationCode_raiz", drop=False).join(n_registros_ate_fim)
    return snap


def comparar_periodos_metrica(snap1, snap2, coluna, maior_e_pior=True):
    """Compara o valor de `coluna` entre o snapshot do filtro 1 (análise) e
    o do filtro 2 (referência), só para as relações presentes nos DOIS
    snapshots — sem um valor resolvido nas duas pontas não há o que
    comparar (essas ficam de fora, em vez de aparecer como "Sem dados")."""
    comuns = snap1.index.intersection(snap2.index)
    comp = pd.DataFrame({
        "atual": snap1.loc[comuns, coluna],
        "anterior": snap2.loc[comuns, coluna],
    })
    comp["status"] = comp.apply(
        lambda r: classificar_delta(r["atual"], r["anterior"], maior_e_pior=maior_e_pior), axis=1
    )
    return comp


def comparar_periodos_rating(snap1, snap2):
    """Mesma ideia de `comparar_periodos_metrica`, mas para rating (ordinal,
    não numérico)."""
    comuns = snap1.index.intersection(snap2.index)
    comp = pd.DataFrame({
        "atual": snap1.loc[comuns, "rating"],
        "anterior": snap2.loc[comuns, "rating"],
    })
    comp["status"] = comp.apply(lambda r: classificar_rating(r["atual"], r["anterior"]), axis=1)
    return comp


def resumo_comparacao_periodos(comparacao, status_order):
    """Contagem de contratos por status de uma única comparação (rating ou
    uma métrica), na ordem de exibição desejada."""
    contagem = comparacao["status"].value_counts()
    linhas = [{"status": s, "n_contratos": int(contagem.get(s, 0))} for s in status_order]
    return pd.DataFrame(linhas)


def resumo_comparacao_multiplas_metricas(snap1, snap2, metricas, maior_e_pior=True):
    """Mesma comparação filtro 1 x filtro 2, para várias métricas de uma
    vez — usado na tabela de comparação de "Dívidas e atrasos externos"."""
    status_order = STATUS_ORDER_COMPARACAO_RISCO if maior_e_pior else STATUS_ORDER_COMPARACAO_NEUTRO
    linhas = []
    for m in metricas:
        comp = comparar_periodos_metrica(snap1, snap2, m, maior_e_pior=maior_e_pior)
        contagem = comp["status"].value_counts()
        for status in status_order:
            linhas.append({
                "metrica": NOME_METRICA[m],
                "status": status,
                "n_contratos": int(contagem.get(status, 0)),
            })
    return pd.DataFrame(linhas)


def _classificar_valor_bruto(v, tolerancia=TOLERANCIA_MONETARIA):
    """Classifica um valor ABSOLUTO (não uma variação) em 'Zerado' ou 'Com
    valor em aberto' — usado nas distribuições que representam só o filtro
    1 (análise), sem comparação com período de referência."""
    if pd.isna(v):
        return "Sem dados"
    return "Zerado" if abs(v) < tolerancia else "Com valor em aberto"


def resumo_distribuicao_metricas(snap, metricas):
    """Distribuição (Com valor em aberto / Zerado / Sem dados) das métricas
    de dívida/atraso, olhando só para o snapshot informado (normalmente o
    do filtro 1) — não é uma comparação, é "quantos têm o problema agora"."""
    linhas = []
    for m in metricas:
        if snap.empty:
            status = pd.Series(dtype="object")
        else:
            status = snap[m].apply(_classificar_valor_bruto)
        contagem = status.value_counts()
        for s in DIST_STATUS_ORDER:
            linhas.append({"metrica": NOME_METRICA[m], "status": s, "n_contratos": int(contagem.get(s, 0))})
    return pd.DataFrame(linhas)


def distribuicao_rating(snap):
    """Distribuição de contratos por rating no snapshot informado
    (normalmente o filtro 1) — a "fotografia" atual, sem comparação."""
    contagem = snap["rating"].value_counts() if not snap.empty else pd.Series(dtype="int64")
    linhas = [{"rating": r, "n_contratos": int(contagem.get(r, 0))} for r in RATING_ORDER]
    return pd.DataFrame(linhas)


def variacao_pct(atual, anterior):
    """Variação percentual de `anterior` para `atual`, usada junto dos
    indicadores de cobertura (ex.: nº de contratos monitorados). Retorna
    `None` quando não há referência válida (anterior é 0, nulo ou
    ausente) — quem exibe decide como tratar (normalmente omite o
    percentual nesse caso)."""
    if anterior is None or pd.isna(anterior) or anterior == 0:
        return None
    return (atual - anterior) / anterior
