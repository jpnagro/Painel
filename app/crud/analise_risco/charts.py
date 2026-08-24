import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

_COR_ALERTA = "#E76F51"
_ESCALA_RISCO = ["#2A9D8F", "#E9C46A", "#E76F51"]  # verde -> amarelo -> vermelho


def build_barra_npl_por_categoria(tabela, coluna, titulo):
    """Barras horizontais de % NPL90+ por categoria, ordenadas da maior
    pra menor inadimplência (de cima pra baixo)."""
    if not len(tabela):
        fig = go.Figure()
        fig.update_layout(title=f"{titulo} — sem dados", height=300)
        return fig

    t = tabela.sort_values("pct_npl", ascending=True)  # ascending: barh desenha de baixo pra cima
    fig = go.Figure(go.Bar(
        x=t["pct_npl"], y=t[coluna].astype(str), orientation="h",
        marker=dict(color=t["pct_npl"], colorscale=_ESCALA_RISCO),
        text=t["pct_npl"].map(lambda v: f"{v:.2f}%"), textposition="outside",
        customdata=np.stack([t["n_contratos"], t["saldo_devedor"]], axis=-1),
        hovertemplate="%{y}<br>NPL90+: %{x:.2f}%<br>Contratos: %{customdata[0]}"
                      "<br>Saldo devedor: R$ %{customdata[1]:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        title=titulo, height=max(320, 42 * len(t)), xaxis_title="% NPL90+",
        margin=dict(l=10, r=60, t=60, b=40),
    )
    return fig


def build_bolha_risco_exposicao(tabela, coluna, titulo):
    """Bolha: eixo X = % NPL90+, eixo Y = saldo devedor (exposição atual),
    tamanho = nº de contratos. Linhas de referência (média ponderada de
    NPL e mediana de saldo) dividem o gráfico em quadrantes -- o
    quadrante superior direito (NPL alto + exposição alta) é onde vale
    priorizar ação de política de crédito."""
    if not len(tabela):
        fig = go.Figure()
        fig.update_layout(title=f"{titulo} — sem dados", height=420)
        return fig

    pesos = tabela["saldo_carteira"].clip(lower=1)
    media_npl = float(np.average(tabela["pct_npl"], weights=pesos))
    mediana_saldo = float(tabela["saldo_devedor"].median())

    fig = px.scatter(
        tabela, x="pct_npl", y="saldo_devedor", size="n_contratos", color=coluna,
        hover_name=coluna, size_max=45,
        labels={"pct_npl": "% NPL90+", "saldo_devedor": "Saldo devedor (R$)"},
        hover_data={"n_contratos": True, "volume_concedido": ":,.0f"},
    )
    fig.add_vline(x=media_npl, line_dash="dash", line_color="gray")
    fig.add_hline(y=mediana_saldo, line_dash="dash", line_color="gray")
    fig.update_layout(title=titulo, height=460, showlegend=False)
    return fig


def build_heatmap_cruzado(tabela, coluna1, coluna2, titulo):
    """Heatmap de % NPL90+ cruzando duas variáveis (ex.: UF x Setor) --
    generaliza os cruzamentos fixos dos Tópicos 10/11 do relatório de
    referência pra qualquer par de variáveis."""
    if not len(tabela):
        fig = go.Figure()
        fig.update_layout(title=f"{titulo} — sem dados", height=300)
        return fig

    pivot = tabela.pivot(index=coluna1, columns=coluna2, values="pct_npl")
    fig = px.imshow(
        pivot, text_auto=".1f", color_continuous_scale=_ESCALA_RISCO,
        labels=dict(color="% NPL90+"), aspect="auto",
    )
    fig.update_layout(title=titulo, height=max(360, 42 * len(pivot)))
    return fig


def build_ranking_dispersao(disp):
    """Ranking de variáveis por "poder discriminante" (dispersão de
    NPL90+ entre categorias) -- a variável no topo é a que mais separa
    bons e maus pagadores nesse recorte."""
    if not len(disp):
        fig = go.Figure()
        fig.update_layout(title="Sem variáveis com categorias suficientes nesse filtro", height=250)
        return fig

    t = disp.sort_values("dispersao", ascending=True)
    fig = go.Figure(go.Bar(
        x=t["dispersao"], y=t["variavel"], orientation="h",
        marker_color=_COR_ALERTA,
        text=t["dispersao"].map(lambda v: f"{v:.1f} p.p."), textposition="outside",
        customdata=np.stack([t["pior_categoria"], t["pior_pct_npl"]], axis=-1),
        hovertemplate="%{y}<br>Dispersão: %{x:.1f} p.p.<br>Pior categoria: "
                      "%{customdata[0]} (%{customdata[1]:.2f}%% NPL90+)<extra></extra>",
    ))
    fig.update_layout(
        title="Dispersão de NPL90+ entre categorias",
        height=max(280, 46 * len(t)), xaxis_title="Dispersão (pontos percentuais)",
        margin=dict(l=10, r=60, t=60, b=40),
    )
    return fig
