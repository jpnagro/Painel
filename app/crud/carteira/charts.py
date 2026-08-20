import plotly.express as px


def build_mix_produto_chart(mix_produto):
    fig = px.bar(
        mix_produto, x="produto", y="saldo_devedor",
        color="produto", text=mix_produto["saldo_devedor"].apply(lambda v: f"R$ {v:,.0f}"),
        title="Saldo devedor por produto",
        labels={"produto": "Produto", "saldo_devedor": "Saldo devedor"},
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(height=360, showlegend=False)
    return fig


def build_npl_faixa_chart(npl_por_faixa):
    fig = px.bar(
        npl_por_faixa, x="faixa", y="pct_saldo",
        text=npl_por_faixa["pct_saldo"].apply(lambda v: f"{v:.2f}%" if v is not None else "-"),
        title="NPL por faixa de atraso (% do saldo)",
        labels={"faixa": "Faixa", "pct_saldo": "% do saldo devedor"},
        color="pct_saldo", color_continuous_scale="RdYlGn_r",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(height=360, coloraxis_showscale=False)
    return fig


def build_aging_chart(aging):
    fig = px.bar(
        aging, x="bucket_atraso", y="pct_saldo",
        text=aging["pct_saldo"].apply(lambda v: f"{v:.2f}%" if v is not None else "-"),
        title="Distribuição de aging (% do saldo)",
        labels={"bucket_atraso": "Faixa de atraso", "pct_saldo": "% do saldo devedor"},
        color="pct_saldo", color_continuous_scale="RdYlGn_r",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(height=360, coloraxis_showscale=False)
    return fig


BUCKET_ORDER = ["0 - em dia", "1-30", "31-60", "61-89", "90+"]

_MESES_PT = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}


def _formatar_safra_pt(safra_str):
    """'2021-10' -> 'Out/21'"""
    ano, mes = safra_str.split("-")
    return f"{_MESES_PT[int(mes)]}/{ano[2:]}"


def build_curva_maturacao_heatmap(curva_maturacao_safra, faixa_npl=90, idade_maxima=40, safra_minima="2021-10"):
    """Visão geral das safras (a partir de `safra_minima`) como mapa de
    calor (safra x idade em meses, limitada a `idade_maxima`). Substitui
    o gráfico de linhas sobrepostas (ilegível com muitas safras) — aqui dá
    pra escanear visualmente quais safras (linhas) pioraram e como o NPL
    evolui com a idade (colunas), sem dezenas de linhas se cruzando."""
    df = curva_maturacao_safra.copy()
    df = df[df["safra"] >= safra_minima]
    df = df[df["idade_meses"] <= idade_maxima]

    pivot = df.pivot(index="safra", columns="idade_meses", values="pct_npl_valor_originado")
    pivot = pivot.sort_index(ascending=False)  # safra mais recente no topo
    pivot.index = [_formatar_safra_pt(s) for s in pivot.index]

    fig = px.imshow(
        pivot, color_continuous_scale="RdYlGn_r", aspect="auto",
        labels=dict(x="Idade da safra (meses)", y="Safra", color=f"% NPL{faixa_npl}+"),
        title=f"Curva de maturação por safra — mapa de calor (% NPL{faixa_npl}+ do valor originado)",
    )
    fig.update_layout(height=min(1400, max(420, 22 * pivot.shape[0])))
    fig.update_xaxes(side="top")
    return fig


def build_curva_maturacao_linhas(curva_maturacao_safra, safras_selecionadas=None, faixa_npl=90):
    """Linhas de maturação apenas para as safras selecionadas (evita
    poluição visual de dezenas de safras ao mesmo tempo), sempre com uma
    linha de referência tracejada mostrando a média de toda a carteira
    em cada idade — para comparar a safra escolhida contra o padrão
    histórico."""
    df = curva_maturacao_safra.copy()

    media = (
        df.groupby("idade_meses")[["valor_npl", "valor_originado"]]
        .sum()
        .reset_index()
    )
    media["pct_npl_valor_originado"] = round(100 * media["valor_npl"] / media["valor_originado"], 2)

    if safras_selecionadas:
        df = df[df["safra"].isin(safras_selecionadas)]

    fig = px.line(
        df, x="idade_meses", y="pct_npl_valor_originado", color="safra", markers=True,
        labels={
            "idade_meses": "Idade da safra (meses desde a originação)",
            "pct_npl_valor_originado": f"% NPL{faixa_npl}+ do valor originado",
            "safra": "Safra",
        },
        title=f"Curva de maturação — safras selecionadas vs. média da carteira (% NPL{faixa_npl}+)",
    )
    fig.add_scatter(
        x=media["idade_meses"], y=media["pct_npl_valor_originado"],
        mode="lines", name="Média da carteira",
        line=dict(color="black", width=3, dash="dash"),
    )
    fig.update_layout(height=460, legend=dict(orientation="h", y=-0.3))
    return fig


def build_matriz_rolagem_heatmap(matriz_rolagem):
    df = matriz_rolagem.copy()
    df["de"] = df["de"].astype(str)
    df["para"] = df["para"].astype(str)
    pivot = df.pivot(index="de", columns="para", values="pct")

    ordem = [b for b in BUCKET_ORDER if b in pivot.index or b in pivot.columns]
    pivot = pivot.reindex(index=ordem, columns=ordem)

    fig = px.imshow(
        pivot, text_auto=".1f", color_continuous_scale="RdYlGn_r", aspect="auto",
        labels=dict(x="Bucket no mês seguinte", y="Bucket no mês atual", color="% transição"),
        title="Matriz de rolagem (roll-rate) entre buckets de atraso — mês a mês",
    )
    fig.update_layout(height=460)
    return fig


def build_concentracao_chart(detalhe, coluna):
    fig = px.bar(
        detalhe, x=coluna, y="pct_saldo",
        text=detalhe["pct_saldo"].apply(lambda v: f"{v:.2f}%"),
        title="Top 15 — concentração de saldo devedor",
        labels={coluna: coluna, "pct_saldo": "% do saldo devedor"},
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(height=380, xaxis_tickangle=-45)
    return fig


def build_npl_por_dimensao_chart(df, coluna, titulo):
    fig = px.bar(
        df, x=coluna, y="pct_npl90_saldo",
        text=df["pct_npl90_saldo"].apply(lambda v: f"{v:.2f}%" if v is not None else "-"),
        title=titulo,
        labels={coluna: coluna, "pct_npl90_saldo": "% NPL90+ do saldo"},
        color="pct_npl90_saldo", color_continuous_scale="RdYlGn_r",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(height=380, coloraxis_showscale=False, xaxis_tickangle=-45)
    return fig
