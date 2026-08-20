import pandas as pd
import streamlit as st
from scipy.stats import ks_2samp
from sklearn.metrics import roc_auc_score

from crud.monitoramento.charts import (
    build_ks_chart,
    build_psi_decil_chart,
    build_rating_chart,
    build_rating_dist_chart,
    build_roc_chart,
    build_summary_table,
)
from crud.monitoramento.data import load_current_data, load_reference_data
from crud.monitoramento.scoring import calculate_psi, delta_color, psi_status

DEFAULT_START = pd.Timestamp("2025-06-01")
DEFAULT_END = pd.Timestamp.now() - pd.DateOffset(months=5)


def render_monitoramento():
    st.title("📊 Monitoramento do Modelo de Risco de Crédito v4")
    st.caption("Comparativo entre a base de referência (treino/teste) e a carteira em produção")

    with st.expander("Referências dos indicadores", expanded=False):
        st.markdown(
            """
| Métrica | 🟢 Bom | 🟡 Atenção | 🔴 Crítico |
|---------|--------|-----------|-----------|
| KS      | ≥ 0.20 | 0.10–0.20 | < 0.10    |
| Gini    | ≥ 0.30 | 0.20–0.30 | < 0.20    |
| PSI     | < 0.10 | 0.10–0.25 | ≥ 0.25    |
"""
        )

    col_start, col_end, col_refresh = st.columns([1, 1, 1])
    with col_start:
        start_date = st.date_input("Início (produção)", value=DEFAULT_START, key="mon_start_date")
    with col_end:
        end_date = st.date_input("Fim (produção)", value=DEFAULT_END, key="mon_end_date")
    with col_refresh:
        st.write("")
        st.write("")
        refresh = st.button("🔄 Recarregar dados", width="stretch", key="mon_refresh")

    if refresh:
        st.cache_data.clear()

    data_ok = False
    error_msgs = []

    with st.spinner("Carregando dados de referência..."):
        try:
            df_ref = load_reference_data()
        except Exception as exc:
            error_msgs.append(f"Base de referência: {exc}")
            df_ref = None

    with st.spinner("Carregando dados de produção..."):
        try:
            df_atual = load_current_data(str(start_date), str(end_date))
            data_ok = df_ref is not None
        except Exception as exc:
            error_msgs.append(f"Base de produção: {exc}")
            df_atual = None

    for msg in error_msgs:
        st.error(f"Erro ao carregar dados — {msg}")

    if not data_ok:
        st.stop()

    ks_ref = ks_2samp(
        df_ref[df_ref["target"] == 0]["score_novo"],
        df_ref[df_ref["target"] == 1]["score_novo"],
    ).statistic
    auc_ref = roc_auc_score(df_ref["target"], df_ref["prob"])
    gini_ref = 2 * auc_ref - 1

    ks_prod = ks_2samp(
        df_atual[df_atual["target"] == 0]["score_v4"],
        df_atual[df_atual["target"] == 1]["score_v4"],
    ).statistic
    auc_prod = roc_auc_score(df_atual["target"], df_atual["prob"])
    gini_prod = 2 * auc_prod - 1

    psi_total, psi_parts, _ = calculate_psi(df_ref[:3000]["score_novo"], df_atual["score_v4"])

    st.divider()
    st.subheader("🎯 Indicadores de Desempenho")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.metric("KS — Referência", f"{ks_ref:.4f}")
    with c2:
        st.metric(
            "KS — Produção", f"{ks_prod:.4f}",
            delta=f"{ks_prod - ks_ref:+.4f}",
            delta_color=delta_color(ks_prod, ks_ref),
        )
    with c3:
        st.metric("Gini — Referência", f"{gini_ref:.4f}")
    with c4:
        st.metric(
            "Gini — Produção", f"{gini_prod:.4f}",
            delta=f"{gini_prod - gini_ref:+.4f}",
            delta_color=delta_color(gini_prod, gini_ref),
        )
    with c5:
        st.metric("PSI", f"{psi_total:.4f}", delta=psi_status(psi_total), delta_color="off")
    with c6:
        total_prod = len(df_atual)
        taxa_geral = df_atual["target"].mean()
        st.metric("Inadimplência (>90d)", f"{taxa_geral:.2%}", delta=f"{total_prod:,} ops")

    st.divider()
    st.subheader("📋 Distribuição de Ratings & Tabela Resumo")
    col_a, col_b = st.columns([1.3, 1])
    with col_a:
        st.plotly_chart(build_rating_dist_chart(df_ref, df_atual), width="stretch")
    with col_b:
        st.dataframe(build_summary_table(df_atual), width="stretch", hide_index=True, height=360)

    st.divider()
    st.subheader("⚠️ Inadimplência por Rating")
    col_a, col_b = st.columns(2)
    with col_a:
        if "rating_novo" in df_ref.columns:
            st.plotly_chart(
                build_rating_chart(df_ref, "score_novo", "rating_novo", "Inadimplência por Rating — Referência"),
                width="stretch",
            )
        else:
            st.info("Coluna `rating_novo` não encontrada na base de referência.")
    with col_b:
        st.plotly_chart(
            build_rating_chart(df_atual, "score_v4", "rating_v4", "Inadimplência por Rating — Produção"),
            width="stretch",
        )

    st.divider()
    st.subheader("📉 Curva ROC & Estabilidade (PSI)")
    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(
            build_roc_chart(df_ref, df_atual, auc_ref, auc_prod, gini_ref, gini_prod),
            width="stretch",
        )
    with col_b:
        st.plotly_chart(
            build_psi_decil_chart(psi_parts, psi_total, psi_status(psi_total)),
            width="stretch",
        )

    st.divider()
    st.subheader("📊 Curva KS — Separação entre Bons e Maus")
    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(build_ks_chart(df_ref, "score_novo", "Curva KS — Referência"), width="stretch")
    with col_b:
        st.plotly_chart(build_ks_chart(df_atual, "score_v4", "Curva KS — Produção"), width="stretch")

    st.divider()
    st.caption(
        f"Atualizado em {pd.Timestamp.now().strftime('%d/%m/%Y %H:%M')}  |  "
        f"Modelo: LightGBM  |  "
        f"Janela de produção: {start_date} → {end_date}  |  "
        f"{len(df_atual):,} operações carregadas"
    )
