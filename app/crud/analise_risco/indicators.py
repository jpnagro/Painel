import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Fórmula de NPL: igual à usada em
# `crud.painel_executivo.indicators.calcular_indicadores_risco_inadimplencia`
# ("% da Carteira" na faixa "90+ dias") -- soma de `total_due_amount` dos
# contratos em default_90p_flag==1, dividido pela soma de
# `total_installment_amount` de todos os contratos do grupo. Aqui é a
# mesma conta, só que agrupada por uma variável de perfil em vez de uma
# vez só pro total/categoria.
# ---------------------------------------------------------------------------

COLUNAS_VAZIO_VARIAVEL = [
    "n_contratos", "volume_concedido", "saldo_devedor", "saldo_carteira",
    "saldo_em_atraso", "pct_npl",
]


def _fillna_categoria(serie, rotulo="Sem informação"):
    """Substitui NaN por um rótulo explícito, tratando dtype Categorical
    (resultado de `pd.cut`) que não aceita fillna com valor fora das
    categorias existentes sem antes registrá-lo."""
    if isinstance(serie.dtype, pd.CategoricalDtype):
        if rotulo not in serie.cat.categories:
            serie = serie.cat.add_categories([rotulo])
        return serie.fillna(rotulo)
    return serie.fillna(rotulo)


def inadimplencia_por_variavel(df, coluna, min_contratos=3):
    """Agrega `df` por `coluna` e calcula, pra cada categoria: nº de
    contratos, volume concedido (principalAmount), saldo devedor
    (outstanding_principal), saldo da carteira (total_installment_amount)
    e % NPL90+ (mesma fórmula do Painel Executivo). Categorias com menos
    de `min_contratos` contratos são descartadas -- evita que uma
    categoria com 1-2 contratos apareça como "100% inadimplente" e
    distorça a leitura."""
    if not len(df) or coluna not in df.columns:
        return pd.DataFrame(columns=[coluna] + COLUNAS_VAZIO_VARIAVEL)

    d = df.copy()
    d[coluna] = _fillna_categoria(d[coluna])
    d["_em_atraso"] = np.where(d["default_90p_flag"] == 1, d["total_due_amount"], 0.0)

    g = d.groupby(coluna, dropna=False, observed=True).agg(
        n_contratos=("operationCode", "count"),
        volume_concedido=("principalAmount", "sum"),
        saldo_devedor=("outstanding_principal", "sum"),
        saldo_carteira=("total_installment_amount", "sum"),
        saldo_em_atraso=("_em_atraso", "sum"),
    ).reset_index()

    g["pct_npl"] = np.where(
        g["saldo_carteira"] > 0, (100 * g["saldo_em_atraso"] / g["saldo_carteira"]).round(2), 0.0
    )
    g = g[g["n_contratos"] >= min_contratos]
    return g.sort_values("pct_npl", ascending=False).reset_index(drop=True)


def inadimplencia_cruzada(df, coluna1, coluna2, min_contratos=3):
    """Mesma fórmula de `inadimplencia_por_variavel`, mas cruzando DUAS
    variáveis (ex.: UF x Setor) -- equivalente aos Tópicos 10/11 do
    relatório de referência (lá fixos em UF/CNAE/Tempo de Atividade;
    aqui generalizado pra qualquer par de variáveis)."""
    colunas_vazio = [coluna1, coluna2] + COLUNAS_VAZIO_VARIAVEL
    if not len(df) or coluna1 not in df.columns or coluna2 not in df.columns:
        return pd.DataFrame(columns=colunas_vazio)

    d = df.copy()
    d[coluna1] = _fillna_categoria(d[coluna1])
    d[coluna2] = _fillna_categoria(d[coluna2])
    d["_em_atraso"] = np.where(d["default_90p_flag"] == 1, d["total_due_amount"], 0.0)

    g = d.groupby([coluna1, coluna2], dropna=False, observed=True).agg(
        n_contratos=("operationCode", "count"),
        volume_concedido=("principalAmount", "sum"),
        saldo_devedor=("outstanding_principal", "sum"),
        saldo_carteira=("total_installment_amount", "sum"),
        saldo_em_atraso=("_em_atraso", "sum"),
    ).reset_index()

    g["pct_npl"] = np.where(
        g["saldo_carteira"] > 0, (100 * g["saldo_em_atraso"] / g["saldo_carteira"]).round(2), 0.0
    )
    g = g[g["n_contratos"] >= min_contratos]
    return g.reset_index(drop=True)


def ranking_dispersao(df, variaveis, min_contratos=3):
    """Pra cada variável (dict rótulo -> coluna), calcula a dispersão de
    NPL90+ entre suas categorias (maior menos menor) -- uma medida simples
    de "poder discriminante": se uma variável separa bem bons e maus
    pagadores, suas categorias vão ter NPL muito diferentes entre si; se
    quase não importa pra risco, o NPL vai ser parecido em todas as
    categorias. Ordena da variável mais discriminante pra menos."""
    linhas = []
    for rotulo, coluna in variaveis.items():
        tabela = inadimplencia_por_variavel(df, coluna, min_contratos=min_contratos)
        if len(tabela) < 2:
            continue
        pior = tabela.iloc[0]
        linhas.append({
            "variavel": rotulo,
            "dispersao": round(float(tabela["pct_npl"].max() - tabela["pct_npl"].min()), 2),
            "pior_categoria": str(pior[coluna]),
            "pior_pct_npl": float(pior["pct_npl"]),
            "n_categorias": len(tabela),
        })
    resultado = pd.DataFrame(linhas, columns=[
        "variavel", "dispersao", "pior_categoria", "pior_pct_npl", "n_categorias",
    ])
    if len(resultado):
        resultado = resultado.sort_values("dispersao", ascending=False).reset_index(drop=True)
    return resultado


def montar_mascara_exclusao(df, regras, logica="E"):
    """Constrói a máscara booleana do "Simulador de exclusão de perfil":
    `regras` é uma lista de tuplas (coluna, lista_de_valores) -- cada uma
    vira "linha bate se a coluna estiver em lista_de_valores". Regras sem
    nenhum valor selecionado são ignoradas. `logica`: "E" (interseção --
    só entra no segmento excluído quem bate TODAS as regras ativas, ex.:
    UF=RN E Setor=bovino corte) ou "OU" (união -- entra quem bate
    QUALQUER UMA). Compara sempre como string, pra funcionar igual em
    colunas numéricas, categóricas (pd.cut) ou de texto."""
    regras_ativas = [(coluna, valores) for coluna, valores in regras if valores]
    if not regras_ativas:
        return pd.Series(False, index=df.index)

    mascaras = [df[coluna].astype(str).isin(valores) for coluna, valores in regras_ativas]
    resultado = mascaras[0]
    for m in mascaras[1:]:
        resultado = (resultado & m) if logica == "E" else (resultado | m)
    return resultado
