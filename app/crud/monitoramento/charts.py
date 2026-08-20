import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from sklearn.metrics import roc_curve

from crud.monitoramento.scoring import sort_ratings


def build_score_hist_chart(df_ref: pd.DataFrame, df_prod: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=df_ref["score_novo"], name="Referência",
        opacity=0.65, nbinsx=40, marker_color="#4C8CBF",
    ))
    fig.add_trace(go.Histogram(
        x=df_prod["score_v4"], name="Produção",
        opacity=0.65, nbinsx=40, marker_color="#E07B54",
    ))
    fig.update_layout(
        barmode="overlay",
        title="Score: Referência vs Produção",
        xaxis_title="Score", yaxis_title="Frequência",
        height=360, legend=dict(orientation="h", y=-0.25),
    )
    return fig


def build_decil_inadim_chart(df_prod: pd.DataFrame) -> go.Figure:
    df = df_prod.copy()
    df["decil"] = pd.qcut(df["score_v4"], 10, labels=False, duplicates="drop")
    decil_stats = (
        df.groupby("decil")
        .agg(taxa=("target", "mean"), score_medio=("score_v4", "mean"), n=("target", "count"))
        .reset_index()
    )
    decil_stats["decil_label"] = (decil_stats["decil"] + 1).astype(str)

    fig = px.bar(
        decil_stats, x="decil_label", y="taxa",
        color="taxa", color_continuous_scale="RdYlGn_r",
        text=decil_stats["taxa"].apply(lambda x: f"{x:.1%}"),
        title="Taxa de Inadimplência por Decil de Score (Produção)",
        labels={"decil_label": "Decil (1=menor score)", "taxa": "Taxa Inadimplência"},
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(height=360, coloraxis_showscale=False)
    return fig


def build_rating_chart(df: pd.DataFrame, score_col: str, rating_col: str, title: str) -> go.Figure:
    stats = (
        df.groupby(rating_col)
        .agg(total=(score_col, "count"), inadim=("target", "sum"))
        .reset_index()
    )
    stats["taxa"] = stats["inadim"] / stats["total"]
    stats[rating_col] = sort_ratings(stats[rating_col])
    stats = stats.sort_values(rating_col)

    fig = px.bar(
        stats, x=rating_col, y="taxa",
        color="taxa", color_continuous_scale="RdYlGn_r",
        text=stats["taxa"].apply(lambda x: f"{x:.1%}"),
        title=title,
        labels={rating_col: "Rating", "taxa": "Taxa de Inadimplência"},
        hover_data={"total": True, "inadim": True},
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(height=380, coloraxis_showscale=False)
    return fig


def build_roc_chart(
    df_ref: pd.DataFrame, df_prod: pd.DataFrame,
    auc_ref: float, auc_prod: float, gini_ref: float, gini_prod: float,
) -> go.Figure:
    fpr_ref, tpr_ref, _ = roc_curve(df_ref["target"], df_ref["prob"])
    fpr_prod, tpr_prod, _ = roc_curve(df_prod["target"], df_prod["prob"])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=fpr_ref, y=tpr_ref,
        name=f"Referência (AUC = {auc_ref:.3f} | Gini = {gini_ref:.3f})",
        line=dict(color="#4C8CBF", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=fpr_prod, y=tpr_prod,
        name=f"Produção (AUC = {auc_prod:.3f} | Gini = {gini_prod:.3f})",
        line=dict(color="#E07B54", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=[0, 1], y=[0, 1], name="Aleatório",
        line=dict(color="gray", dash="dash"), mode="lines",
    ))
    fig.update_layout(
        title="Curva ROC", xaxis_title="Taxa Falso Positivo",
        yaxis_title="Taxa Verdadeiro Positivo",
        height=400, legend=dict(orientation="h", y=-0.3),
    )
    return fig


def build_psi_decil_chart(psi_parts: np.ndarray, psi_total: float, psi_status_text: str) -> go.Figure:
    psi_df = pd.DataFrame({
        "Decil": [f"D{i + 1}" for i in range(len(psi_parts))],
        "PSI": psi_parts,
    })
    fig = px.bar(
        psi_df, x="Decil", y="PSI",
        color="PSI", color_continuous_scale="RdYlGn_r",
        title=f"PSI por Decil (Total = {psi_total:.4f} — {psi_status_text})",
        labels={"PSI": "Contribuição PSI"},
    )
    fig.add_hline(
        y=0.025, line_dash="dot", line_color="orange",
        annotation_text="Ref. por decil",
    )
    fig.update_layout(height=400, coloraxis_showscale=False)
    return fig


def build_ks_chart(df: pd.DataFrame, score_col: str, title: str) -> go.Figure:
    scores_sorted = np.sort(df[score_col].unique())
    good = df[df["target"] == 0][score_col]
    bad = df[df["target"] == 1][score_col]
    cum_good = np.array([(good <= s).mean() for s in scores_sorted])
    cum_bad = np.array([(bad <= s).mean() for s in scores_sorted])
    diff = np.abs(cum_good - cum_bad)
    ks_idx = np.argmax(diff)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=scores_sorted, y=cum_good, name="Bons", line=dict(color="green")))
    fig.add_trace(go.Scatter(x=scores_sorted, y=cum_bad, name="Maus", line=dict(color="red")))
    fig.add_shape(
        type="line",
        x0=scores_sorted[ks_idx], x1=scores_sorted[ks_idx],
        y0=min(cum_good[ks_idx], cum_bad[ks_idx]),
        y1=max(cum_good[ks_idx], cum_bad[ks_idx]),
        line=dict(color="navy", dash="dash"),
    )
    fig.add_annotation(
        x=scores_sorted[ks_idx],
        y=(cum_good[ks_idx] + cum_bad[ks_idx]) / 2,
        text=f"KS = {diff[ks_idx]:.4f}",
        showarrow=True, arrowhead=1,
    )
    fig.update_layout(
        title=title, xaxis_title="Score",
        yaxis_title="Proporção acumulada", height=380,
        legend=dict(orientation="h", y=-0.25),
    )
    return fig


def build_rating_dist_chart(df_ref: pd.DataFrame, df_prod: pd.DataFrame) -> go.Figure:
    dists = []
    if "rating_novo" in df_ref.columns:
        r = df_ref["rating_novo"].value_counts(normalize=True).reset_index()
        r.columns = ["rating", "freq"]
        r["base"] = "Referência"
        dists.append(r)

    r2 = df_prod["rating_v4"].value_counts(normalize=True).reset_index()
    r2.columns = ["rating", "freq"]
    r2["base"] = "Produção"
    dists.append(r2)

    dist_all = pd.concat(dists)
    dist_all["rating"] = sort_ratings(dist_all["rating"])
    dist_all = dist_all.sort_values("rating")

    fig = px.bar(
        dist_all, x="rating", y="freq", color="base", barmode="group",
        title="Distribuição de Ratings: Referência vs Produção",
        labels={"rating": "Rating", "freq": "Proporção", "base": "Base"},
        color_discrete_map={"Referência": "#4C8CBF", "Produção": "#E07B54"},
    )
    fig.update_yaxes(tickformat=".0%")
    fig.update_layout(height=360, legend=dict(orientation="h", y=-0.25))
    return fig


def build_summary_table(df_prod: pd.DataFrame) -> pd.DataFrame:
    summary = (
        df_prod.groupby("rating_v4")
        .agg(
            Total=("target", "count"),
            Inadimplentes=("target", "sum"),
            Score_Medio=("score_v4", "mean"),
        )
        .reset_index()
    )
    summary["Taxa"] = summary["Inadimplentes"] / summary["Total"]
    summary["rating_v4"] = sort_ratings(summary["rating_v4"])
    summary = summary.sort_values("rating_v4")
    summary["Score_Medio"] = summary["Score_Medio"].round(0).astype(int)
    summary["Taxa"] = summary["Taxa"].apply(lambda x: f"{x:.2%}")
    summary.columns = ["Rating", "Total", "Inadimplentes", "Score Médio", "Taxa Inadimpl."]
    return summary
