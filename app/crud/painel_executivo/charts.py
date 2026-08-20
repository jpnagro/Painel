import plotly.express as px
import plotly.graph_objects as go

_COR_APP = "#2A9D8F"       # turquesa (var(--color-positive) do relatório de referência)
_COR_CP = "#1A2B3C"        # azul escuro (var(--color-primary))
_COR_TOTAL = "#6c757d"     # cinza (var(--color-total-bar))
_COR_PERDA_REAL = "#E76F51"      # coral (var(--color-alert))
_COR_PERDA_ESPERADA = "#FADCBF"  # laranja claro

# Paleta pra categorias dinâmicas (CCB tem 2 — App/Crédito Produtor —, CPR
# pode ter até 4 productType). Mantém as cores originais nas 2 primeiras
# posições pra não mudar o visual de CCB, e completa com mais cores pra
# CPR.
_PALETA_CATEGORIAS = [_COR_APP, _COR_CP, "#E9C46A", "#4C956C", "#9D8189", "#264653"]


def _cor_categoria(i):
    return _PALETA_CATEGORIAS[i % len(_PALETA_CATEGORIAS)]


def build_donut_chart(valores, titulo):
    """`valores`: dict {categoria: valor} — 2 categorias pra CCB (App/
    Crédito Produtor), até 4 pra CPR (productType)."""
    labels = list(valores.keys())
    vals = list(valores.values())
    cores = {label: _cor_categoria(i) for i, label in enumerate(labels)}
    fig = px.pie(
        names=labels, values=vals, hole=0.55, color=labels,
        color_discrete_map=cores, title=titulo,
    )
    # rótulos fora das fatias (dentro do "donut" fino não cabe legível)
    fig.update_traces(
        textinfo="percent+value", texttemplate="%{percent} (%{value:,.0f})",
        textposition="outside", showlegend=True,
    )
    fig.update_layout(height=380, margin=dict(t=60, b=60, l=60, r=60), legend=dict(orientation="h", y=-0.15))
    return fig


def build_risco_bar_chart(risco_por_categoria):
    """Gráfico de barras agrupadas: % da carteira em cada faixa de atraso,
    comparando Total + cada categoria (equivalente ao gráfico de barras do
    Tópico 1 do relatório de referência).

    `risco_por_categoria`: dict {rótulo: df, ...} — cada df é o resultado
    de `calcular_indicadores_risco_inadimplencia` pra aquele recorte. Não
    exige uma chave "Total" especificamente (o rótulo "Total" só recebe
    uma cor cinza especial quando presente) -- outros chamadores usam
    outros rótulos, ex. {"Atual": ..., "Simulada": ...} no simulador da
    aba Análise de Risco."""
    faixas = next(iter(risco_por_categoria.values())).index.tolist()
    fig = go.Figure()
    for i, (label, df) in enumerate(risco_por_categoria.items()):
        cor = _COR_TOTAL if label == "Total" else _cor_categoria(i - 1)
        fig.add_bar(name=label, x=faixas, y=df[f"% da Carteira {label}"], marker_color=cor)
    fig.update_traces(texttemplate="%{y:.2f}%", textposition="outside")
    fig.update_layout(
        title="Indicadores de Risco por Carteira (%)", barmode="group", height=420,
        yaxis_title="% da carteira", legend=dict(orientation="h", y=-0.2),
    )
    return fig


def build_safra_combo_chart(safras, titulo):
    """Combo de barras (Perda Real / Perda Esperada, R$) + linhas
    (Inadimplência Real / Esperada, %) por safra de originação — mesma
    visão dos Tópicos 4/5/6 do relatório de referência, agora interativa."""
    fig = go.Figure()
    if safras.empty:
        fig.update_layout(title=f"{titulo} — sem dados", height=420)
        return fig

    x = safras.index.tolist()
    fig.add_bar(
        name="Perda Real 90d (R$)", x=x, y=safras["Perda Real 90d (R$)"],
        marker_color=_COR_PERDA_REAL, yaxis="y1",
    )
    fig.add_bar(
        name="Perda Esperada (R$)", x=x, y=safras["Perda Esperada (R$)"],
        marker_color=_COR_PERDA_ESPERADA, yaxis="y1",
    )
    fig.add_trace(go.Scatter(
        name="Inadimplência Real 90d (%)", x=x, y=safras["Inadimplência Real 90d (%)"],
        mode="lines+markers", line=dict(color=_COR_APP, width=3), yaxis="y2",
    ))
    fig.add_trace(go.Scatter(
        name="Inadimplência Esperada (%)", x=x, y=safras["Inadimplência Esperada (%)"],
        mode="lines+markers", line=dict(color=_COR_CP, width=3, dash="dash"), yaxis="y2",
    ))
    fig.update_layout(
        title=titulo, barmode="group", height=460,
        xaxis=dict(title="Safra (mês de originação)"),
        yaxis=dict(title="R$"),
        yaxis2=dict(title="% inadimplência", overlaying="y", side="right", rangemode="tozero"),
        legend=dict(orientation="h", y=-0.25),
    )
    return fig
