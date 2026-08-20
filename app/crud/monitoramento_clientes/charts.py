import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

STATUS_COLORS_RISCO = {
    "Piorou": "#E76F51",
    "Estável": "#adb5bd",
    "Melhorou": "#2A9D8F",
    "Sem dados": "#e9ecef",
    "Sem histórico": "#f8f9fa",
}

STATUS_COLORS_NEUTRO = {
    "Aumentou": "#E9C46A",
    "Estável": "#adb5bd",
    "Diminuiu": "#4C956C",
    "Sem dados": "#e9ecef",
    "Sem histórico": "#f8f9fa",
}

# Distribuição "absoluta" (não é uma variação) usada nos gráficos que
# representam só o filtro 1 (análise) — ver `resumo_distribuicao_metricas`
# em `indicators.py`.
DIST_STATUS_COLORS = {
    "Com valor em aberto": "#E76F51",
    "Zerado": "#2A9D8F",
    "Sem dados": "#e9ecef",
}

# Gradiente do melhor (AA) ao pior (H) rating — mesma ordem de
# `RATING_ORDER` em `indicators.py`.
_RATING_COLOR_SCALE = {
    "AA": "#2A9D8F", "A": "#4C956C", "B": "#8AB17D", "C": "#adb5bd",
    "D": "#E9C46A", "E": "#F4A261", "F": "#E76F51", "G": "#BC4749", "H": "#9D0208",
}


def build_status_bar_chart(resumo, titulo, status_order, status_colors=STATUS_COLORS_RISCO):
    fig = px.bar(
        resumo, x="metrica", y="n_contratos", color="status", barmode="group",
        category_orders={"status": status_order},
        color_discrete_map=status_colors,
        text="n_contratos",
        title=titulo,
        labels={"metrica": "", "n_contratos": "Nº de contratos", "status": "Variação"},
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(
        height=420, legend=dict(orientation="h", y=-0.4),
        xaxis_tickangle=-12, margin=dict(b=120),
    )
    return fig


def build_rating_transition_heatmap(tab):
    if tab.empty:
        fig = go.Figure()
        fig.update_layout(title="Sem dados suficientes para migração de rating", height=300)
        return fig

    fig = px.imshow(
        tab, text_auto=True, color_continuous_scale="RdYlGn_r", aspect="auto",
        labels=dict(x="Rating — registro mais recente", y="Rating — registro anterior", color="Nº contratos"),
        title="Migração de rating (registro anterior → registro mais recente)",
    )
    fig.update_layout(height=460)
    fig.update_xaxes(side="top")
    return fig


def build_rating_distribution_chart(dist_rating, titulo="Distribuição de rating — filtro 1"):
    """Distribuição (contagem) de contratos por rating num único snapshot
    (normalmente o do filtro 1/análise) — `dist_rating` já vem ordenada do
    melhor (AA) ao pior (H) por `indicators.distribuicao_rating`."""
    if dist_rating.empty or dist_rating["n_contratos"].sum() == 0:
        fig = go.Figure()
        fig.update_layout(title=f"{titulo} — sem dados no período", height=320)
        return fig

    ordem = list(dist_rating["rating"])
    fig = px.bar(
        dist_rating, x="rating", y="n_contratos", text="n_contratos", color="rating",
        color_discrete_map=_RATING_COLOR_SCALE, category_orders={"rating": ordem},
        title=titulo, labels={"rating": "Rating", "n_contratos": "Nº de contratos"},
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(height=420, showlegend=False)
    return fig


def build_valor_distribution_chart(snap, coluna, titulo, nbins=30):
    """Histograma da distribuição de um valor monetário/numérico contínuo
    (ex.: `credit_portfolio`) num único snapshot (normalmente o do filtro
    1/análise) — não é uma comparação, é "como estão distribuídos agora"."""
    if snap.empty or snap[coluna].dropna().empty:
        fig = go.Figure()
        fig.update_layout(title=f"{titulo} — sem dados no período", height=320)
        return fig

    fig = px.histogram(
        snap, x=coluna, nbins=nbins, title=titulo,
        labels={coluna: "R$"}, color_discrete_sequence=["#264653"],
    )
    fig.update_layout(height=420, bargap=0.05, yaxis_title="Nº de contratos")
    return fig


def build_trajetoria_chart(historico, titulo):
    """Trajetória completa de um contrato: score (linha superior, com o
    rating de cada consulta anotado) + métricas monetárias de dívida/
    atraso externo (linha inferior) ao longo das consultas registradas.

    `historico` pode combinar consultas feitas sob `operationCode`
    diferentes (raiz + renegociações da mesma relação de crédito, já
    consolidadas por `operationCode_raiz` em `data.py`/`indicators.py`) —
    por isso a geração exata de cada ponto (coluna `operationCode`, quando
    presente) aparece no hover, pra deixar claro de onde veio cada consulta
    sem escondê-la do gráfico único e contínuo."""
    h = historico.sort_values("createdAt")
    tem_geracao = "operationCode" in h.columns

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
        subplot_titles=("Score do modelo (rating anotado em cada ponto)", "Dívidas, atrasos e exposição externa (R$)"),
        row_heights=[0.4, 0.6],
    )

    hover_score = "Data: %{x}<br>Score: %{y}<br>Rating: %{text}"
    if tem_geracao:
        hover_score += "<br>Contrato: %{customdata}"
    hover_score += "<extra></extra>"

    fig.add_trace(
        go.Scatter(
            x=h["createdAt"], y=h["score"], mode="lines+markers+text",
            text=h["rating"], textposition="top center",
            customdata=h["operationCode"] if tem_geracao else None,
            hovertemplate=hover_score,
            line=dict(color="#1A2B3C", width=2), name="Score",
        ),
        row=1, col=1,
    )

    series_financeiras = [
        ("overdue", "Valor em atraso", "#E76F51"),
        ("loss", "Prejuízo (loss)", "#9D0208"),
        ("credit_portfolio", "Exposição no mercado (credit_portfolio)", "#264653"),
        ("debts_bv", "Dívidas (debts_bv)", "#E9C46A"),
        ("protests_bv", "Protestos Boa Vista", "#4C956C"),
        ("protests", "Protestos", "#9D8189"),
    ]
    for col, nome, cor in series_financeiras:
        if col in h.columns and h[col].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=h["createdAt"], y=h[col], mode="lines+markers", name=nome,
                    line=dict(color=cor, width=2),
                ),
                row=2, col=1,
            )

    fig.update_yaxes(title_text="Score", row=1, col=1)
    fig.update_yaxes(title_text="R$", row=2, col=1)
    fig.update_layout(
        title=titulo, height=620, legend=dict(orientation="h", y=-0.18),
        hovermode="x unified",
    )
    return fig
