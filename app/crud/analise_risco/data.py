import numpy as np
import pandas as pd

from crud.carteira.data import SEM_CLIENT_DATA

# ---------------------------------------------------------------------------
# Fonte e metodologia: inspirado nos tópicos 7-11 do relatório de
# referência (ai-assistant, template 3.html — "Análise de Risco
# Aprofundada" e as 4 tabelas de "Inadimplência App/CP/Agregado/UF"), que
# quebram a inadimplência por perfil de cliente (rating, UF, CNAE, renda,
# tempo de atividade). NÃO reproduzimos a metodologia de dados daquele
# relatório (query SQL própria, só CCB, corte de releaseDate >= 2025,
# dropna de rating_v4, e — pior — dois formatos de cálculo de NPL
# diferentes e incompatíveis entre os tópicos 7 e 8-11). Em vez disso,
# reusamos a MESMA base já validada do resto do Painel — a mesma que
# alimenta o Painel Executivo (`carregar_dados_executivo_bruto`, que por
# sua vez usa `preparar_bases`/`estado_por_contrato` de crud/carteira) —
# e a mesma fórmula de "% da Carteira" (NPL90+) já usada lá. Isso garante
# que "quantos % da carteira estão em atraso 90+" seja exatamente o
# mesmo número, seja qual for a aba onde você olhar.
#
# As variáveis analisadas (rating, UF, CNAE, renda, tempo de atividade)
# vêm do relatório de referência; "Categoria" (App/Crédito Produtor pra
# CCB, productType pra CPR) e "Faixa de Ticket" são adições nossas —
# a primeira já existe no resto do Painel, a segunda é um corte de risco
# de crédito clássico que não estava no relatório original.
# ---------------------------------------------------------------------------

RENDA_BINS = [-np.inf, 3_000, 9_000, 16_000, 37_000, 77_000, 180_000, np.inf]
RENDA_LABELS = ["Até 3k", "3k–9k", "9k–16k", "16k–37k", "37k–77k", "77k–180k", "Acima de 180k"]

ATIVIDADE_BINS = [-np.inf, 2, 4, 7, 13, 46, np.inf]
ATIVIDADE_LABELS = ["Até 2 anos", "2–4 anos", "4–7 anos", "7–13 anos", "13–46 anos", "Acima de 46 anos"]

# Faixas de ticket (principalAmount) -- não existem no relatório de
# referência; cortes escolhidos pra cobrir o range observado na carteira
# (contratos individuais chegam a ~150k).
TICKET_BINS = [-np.inf, 10_000, 30_000, 50_000, 80_000, 120_000, np.inf]
TICKET_LABELS = ["Até 10k", "10k–30k", "30k–50k", "50k–80k", "80k–120k", "Acima de 120k"]

# Rótulo -> nome da coluna no dataframe já preparado por `preparar_variaveis`.
VARIAVEIS = {
    "Categoria": "categoria",
    "Rating": "rating_v4",
    "UF": "state",
    "Setor (CNAE)": "cnaeFiltered",
    "Faixa de Renda": "faixa_renda",
    "Tempo de Atividade": "faixa_atividade",
    "Faixa de Ticket": "faixa_ticket",
}


def preparar_variaveis(df):
    """Cria as colunas de faixa (renda, tempo de atividade, ticket) sobre a
    base bruta do Painel Executivo -- as demais variáveis (rating_v4,
    state, cnaeFiltered, categoria) já existem prontas nela."""
    df = df.copy()
    df["faixa_renda"] = pd.cut(
        pd.to_numeric(df["averageMonthlyIncome"], errors="coerce"),
        bins=RENDA_BINS, labels=RENDA_LABELS,
    )
    df["faixa_atividade"] = pd.cut(
        pd.to_numeric(df["activityTime"], errors="coerce"),
        bins=ATIVIDADE_BINS, labels=ATIVIDADE_LABELS,
    )
    df["faixa_ticket"] = pd.cut(
        pd.to_numeric(df["principalAmount"], errors="coerce"),
        bins=TICKET_BINS, labels=TICKET_LABELS,
    )
    return df


def filtrar_por_categoria(df, subfiltro_ccb=None, subfiltro_cpr=None):
    """Restringe aos valores de `categoria` selecionados -- mesmo papel dos
    subfiltros "Tipo de operação (CCB)"/"Tipo de produto (CPR)" da aba
    Análise da carteira, só que aqui a `categoria` já vem pronta em cada
    linha (cada linha do df JÁ é uma raiz de contrato, então não precisa
    do jogo de "raiz + renegociações" que os subfiltros originais fazem
    sobre as tabelas brutas).

    `subfiltro_ccb`/`subfiltro_cpr`: lista de categorias a manter (ou
    `SEM_CLIENT_DATA` pra CCB sem correspondência), ou None = sem filtro."""
    partes = []

    ccb = df[df["produto"] == "CCB"]
    if subfiltro_ccb is not None:
        mask = ccb["categoria"].isin(subfiltro_ccb)
        if SEM_CLIENT_DATA in subfiltro_ccb:
            mask = mask | ccb["categoria"].isna()
        ccb = ccb[mask]
    partes.append(ccb)

    cpr = df[df["produto"] == "CPR"]
    if subfiltro_cpr is not None:
        cpr = cpr[cpr["categoria"].isin(subfiltro_cpr)]
    partes.append(cpr)

    return pd.concat(partes, ignore_index=True) if partes else df.iloc[0:0]


def filtrar_por_periodo(df, data_inicio=None, data_fim=None):
    """Restringe aos contratos originados (releaseDate) dentro de
    [data_inicio, data_fim] (ambos inclusive). `None` em qualquer um dos
    dois lados = sem limite daquele lado; os dois `None` = sem filtro
    nenhum (todo o histórico)."""
    if data_inicio is None and data_fim is None:
        return df
    out = df
    if data_inicio is not None:
        out = out[out["releaseDate"] >= pd.Timestamp(data_inicio)]
    if data_fim is not None:
        out = out[out["releaseDate"] <= pd.Timestamp(data_fim)]
    return out.copy().reset_index(drop=True)
