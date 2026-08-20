from os import getenv

import numpy as np
import pandas as pd
import streamlit as st
from dotenv import find_dotenv, load_dotenv
from sqlalchemy import create_engine

from crud.carteira.data import _bool_true

load_dotenv(find_dotenv(raise_error_if_not_found=False))

URL_PG = getenv("URL_PG")


def get_engine():
    return create_engine(URL_PG)


# ---------------------------------------------------------------------------
# 1. CONEXÃO E EXTRAÇÃO
# ---------------------------------------------------------------------------
# `customer_monitoring` guarda um registro por CONSULTA feita a um contrato
# (não por cliente): cada vez que o contrato é reconsultado (rating/score
# atualizado, dívidas e protestos externos via Boa Vista etc.), entra uma
# nova linha com o mesmo `operationCode`. Comparando o registro mais
# recente contra o imediatamente anterior dá a "trajetória" do contrato —
# se ele está melhorando ou piorando desde a última consulta.
QUERY_MONITORAMENTO = """
    SELECT
        id, "operationCode", "clientId", "dealId", "taxId", "taxIdStatus",
        "createdAt", rating, score, overdue, loss, credit_portfolio,
        debts_bv, protests_bv, protests, death, max_delay_paid_installments
    FROM customer_monitoring
"""

# `ccb`/`cpr` unificadas só nas colunas que precisamos aqui: identidade do
# contrato (name/principalAmount/default), os dois campos que indicam se
# aquele operationCode É ele próprio uma geração de renegociação
# (renegotiation/externalId) — mesma fonte usada em `crud/carteira/data.py`
# — e `productType`, usado no sub-filtro "Tipo de produto (CPR)" (só existe
# em cpr; em ccb entra como NULL e o tipo de operação vem de outro lugar,
# ver `QUERY_CLIENT_DATA`).
QUERY_CONTRATOS = """
    SELECT "operationCode", name, "principalAmount", "default", renegotiation, "externalId",
           'CCB' AS produto, NULL AS "productType"
    FROM ccb
    UNION ALL
    SELECT "operationCode", name, "principalAmount", "default", renegotiation, "externalId",
           'CPR' AS produto, "productType"
    FROM cpr
"""

# `client_data.operationType` ("App"/"Crédito Produtor") é o "Tipo de
# operação (CCB)" usado no sub-filtro — mesma fonte e mesmo critério de
# dedup da aba "Análise da carteira" (`ops_raiz_por_operation_type`/
# `juntar_client_data` em `crud/carteira/data.py`). Só existe pra CCB: o
# vínculo é por `ccbCode` = operationCode da raiz do CCB.
QUERY_CLIENT_DATA = """
    SELECT "ccbCode", "operationType", score_v4
    FROM client_data
"""


@st.cache_data(ttl=3600, show_spinner=False)
def carregar_monitoramento_bruto():
    """Lê `customer_monitoring` (todas as consultas históricas, uma linha
    por consulta/contrato) e enriquece com identidade/exposição do contrato
    a partir de `ccb`/`cpr`. É a parte lenta (consulta ao Postgres); fica em
    cache uma única vez — os filtros da tela são aplicados depois, em
    memória.

    Consolidação de renegociação: se o `operationCode` de uma consulta é,
    ele próprio, uma GERAÇÃO DE RENEGOCIAÇÃO (renegotiation=TRUE em
    ccb/cpr), o histórico dessa consulta é remapeado para o `operationCode`
    RAIZ (via `externalId` — que aponta direto pra raiz mesmo em
    renegociações de 2º nível, ex.: "RRA..." também aponta pra "A...", não
    pra "RA...") em vez de ficar "órfão" sob o código da renegociação.
    Isso é a MESMA regra usada em `preparar_bases` (`crud/carteira/data.py`)
    pra não fragmentar o histórico de um mesmo cliente entre a raiz e suas
    renegociações — sem ela, uma consulta feita à raiz antes de uma
    renegociação e outra consulta feita à renegociação depois virariam dois
    contratos "sem histórico" isolados, em vez de uma única trajetória
    comparável.

    Nome do cliente / valor originado / produto / flag de default sempre
    vêm da RAIZ (nunca da geração de renegociação) — mesma convenção do
    resto do Painel: o dinheiro só é concedido uma vez, na originação.
    O mesmo vale para os sub-tipos usados nos filtros da tela
    (`tipo_operacao_ccb`/`tipo_produto_cpr`, ver abaixo)."""
    engine = get_engine()
    cm = pd.read_sql(QUERY_MONITORAMENTO, engine)
    contratos = pd.read_sql(QUERY_CONTRATOS, engine)
    client = pd.read_sql(QUERY_CLIENT_DATA, engine)

    for col in ["overdue", "loss", "credit_portfolio", "debts_bv", "protests_bv", "protests"]:
        cm[col] = pd.to_numeric(cm[col], errors="coerce")
    cm["score"] = pd.to_numeric(cm["score"], errors="coerce")
    cm["max_delay_paid_installments"] = pd.to_numeric(cm["max_delay_paid_installments"], errors="coerce")
    cm["createdAt"] = pd.to_datetime(cm["createdAt"])
    cm["rating"] = cm["rating"].str.strip().str.upper()

    # `contratos` não deveria ter operationCode duplicado (ccb e cpr são
    # produtos distintos, cada operationCode pertence só a um dos dois),
    # mas descarta qualquer duplicata remanescente por segurança — um
    # merge com chave duplicada multiplicaria linhas silenciosamente.
    contratos = contratos.drop_duplicates(subset="operationCode", keep="first").set_index("operationCode")

    # 1) Geração exata do operationCode de cada consulta (é renegociação? qual a raiz dela?).
    cm = cm.join(contratos[["renegotiation", "externalId"]], on="operationCode")

    renegociacao_flag = _bool_true(cm["renegotiation"])
    externalid_valido = cm["externalId"].notna() & (cm["externalId"].astype(str).str.strip() != "")
    cm["operationCode_raiz"] = np.where(renegociacao_flag & externalid_valido, cm["externalId"], cm["operationCode"])
    cm = cm.drop(columns=["renegotiation", "externalId"])

    # 2) Identidade/exposição do contrato, sempre a partir da RAIZ.
    contratos_raiz = contratos.rename(columns={
        "name": "nome_cliente", "principalAmount": "valor_originado", "default": "em_default",
        "productType": "tipo_produto_cpr",
    })
    cm = cm.join(
        contratos_raiz[["nome_cliente", "valor_originado", "em_default", "produto", "tipo_produto_cpr"]],
        on="operationCode_raiz",
    )

    cm["valor_originado"] = pd.to_numeric(cm["valor_originado"], errors="coerce")
    # `nome_cliente`/`produto`: ~0,05% dos operationCode_raiz não batem com
    # nenhuma linha de ccb/cpr (contrato ainda não sincronizado nessas
    # tabelas). Preenche com rótulos explícitos em vez de deixar NaN se
    # propagando pela tela (filtros de produto, rótulos de seleção, tabelas).
    cm["nome_cliente"] = cm["nome_cliente"].str.strip().fillna("(sem nome)")
    cm["produto"] = cm["produto"].fillna("Não identificado")

    # 3) Tipo de operação (CCB), via client_data — só as RAÍZES de CCB têm
    # entrada em client_data (`ccbCode` = operationCode da raiz), mesma
    # observação de `crud/carteira/data.py`. Em caso de múltiplas linhas
    # pro mesmo ccbCode, mantém a de maior `score_v4` — mesmo critério de
    # dedup de `juntar_client_data`, pra não deixar a escolha arbitrária
    # (import direto do `.sort_values`/`.drop_duplicates`, sem inflar nada
    # aqui porque é só um mapeamento 1:1 ccbCode -> operationType, não um
    # merge que multiplica linhas).
    tipo_operacao_ccb = (
        client.dropna(subset=["ccbCode"])
        .sort_values("score_v4", na_position="first")
        .drop_duplicates(subset="ccbCode", keep="last")
        .set_index("ccbCode")["operationType"]
    )
    cm = cm.join(tipo_operacao_ccb.rename("tipo_operacao_ccb"), on="operationCode_raiz")

    return cm
