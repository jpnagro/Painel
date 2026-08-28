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


@st.fragment
def _render_monitoramento_body():
    st.title("📊 Monitoramento do Modelo de Risco de Crédito v4")
    st.caption("Comparativo entre a base de referência (treino/teste) e a carteira em produção")

    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        refresh = st.button("🔄 Recarregar dados", key="mon_refresh")
    if refresh:
        st.cache_data.clear()

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

    col_start, col_end, _col_datas_spacer = st.columns([1, 1, 2])
    with col_start:
        start_date = st.date_input("Início (produção)", value=DEFAULT_START, key="mon_start_date")
    with col_end:
        end_date = st.date_input("Fim (produção)", value=DEFAULT_END, key="mon_end_date")

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
    st.subheader(
        "🎯 Indicadores de Desempenho",
        help="Medem se o modelo de score continua separando bem quem paga de quem não paga. "
        "'Referência' = base de treino/teste do modelo (fixa); 'Produção' = contratos reais dentro "
        "da janela de datas filtrada acima (Início/Fim produção).",
    )

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.metric(
            "KS — Referência", f"{ks_ref:.4f}",
            help="Estatística de Kolmogorov-Smirnov: maior distância entre a distribuição acumulada "
            "de score dos bons pagadores (target=0) e dos maus pagadores (target=1), na base de "
            "treino/teste. Quanto maior (perto de 1), melhor o modelo separa os dois grupos. "
            "Referência: ≥0,20 bom, 0,10-0,20 atenção, <0,10 crítico.",
        )
    with c2:
        st.metric(
            "KS — Produção", f"{ks_prod:.4f}",
            delta=f"{ks_prod - ks_ref:+.4f}",
            delta_color=delta_color(ks_prod, ks_ref),
            help="Mesmo cálculo do KS — Referência (estatística de Kolmogorov-Smirnov entre bons e "
            "maus pagadores), mas aplicado aos contratos reais da janela de produção filtrada "
            "(campos usados: score_v4 e target = atraso ≥90 dias e não pago). O delta mostra a "
            "diferença contra a Referência.",
        )
    with c3:
        st.metric(
            "Gini — Referência", f"{gini_ref:.4f}",
            help="Poder discriminante do modelo em escala de mercado de crédito: Gini = 2 × AUC − 1, "
            "onde AUC é a área sob a curva ROC (probabilidade prevista de inadimplência vs. resultado "
            "real), calculada na base de treino/teste. Referência: ≥0,30 bom, 0,20-0,30 atenção, "
            "<0,20 crítico.",
        )
    with c4:
        st.metric(
            "Gini — Produção", f"{gini_prod:.4f}",
            delta=f"{gini_prod - gini_ref:+.4f}",
            delta_color=delta_color(gini_prod, gini_ref),
            help="Mesmo cálculo do Gini — Referência (2 × AUC − 1), aplicado aos contratos reais da "
            "janela de produção filtrada. O delta mostra a diferença contra a Referência.",
        )
    with c5:
        st.metric(
            "PSI", f"{psi_total:.4f}", delta=psi_status(psi_total), delta_color="off",
            help="Population Stability Index: mede se a distribuição de score da carteira em produção "
            "se afastou da distribuição vista no treino do modelo. Cálculo: divide o score da "
            "Referência em 10 decis, compara a proporção de operações em cada decil entre Referência "
            "e Produção, e soma (%prod − %ref) × ln(%prod ÷ %ref) dos 10 decis. Referência: <0,10 bom, "
            "0,10-0,25 atenção, ≥0,25 crítico.",
        )
    with c6:
        total_prod = len(df_atual)
        taxa_geral = df_atual["target"].mean()
        st.metric(
            "Inadimplência (>90d)", f"{taxa_geral:.2%}", delta=f"{total_prod:,} ops",
            help="Percentual de contratos da base de Produção (janela de datas filtrada) marcados "
            "como 'mau pagador' (target=1): alguma parcela com mais de 90 dias de atraso e ainda não "
            "paga. Campo usado: target.",
        )

    st.divider()
    st.subheader(
        "📋 Distribuição de Ratings & Tabela Resumo",
        help="Gráfico: % de operações em cada faixa de rating (AA a H), comparando Referência x "
        "Produção — mostra se a carteira em produção está concentrada em ratings melhores/piores do "
        "que a base usada no treino. Tabela: nº de contratos, inadimplentes e score médio por rating "
        "(produção), com taxa de inadimplência = inadimplentes ÷ total do rating.",
    )
    col_a, col_b = st.columns([1.3, 1])
    with col_a:
        st.plotly_chart(build_rating_dist_chart(df_ref, df_atual), width="stretch")
    with col_b:
        st.dataframe(build_summary_table(df_atual), width="stretch", hide_index=True, height=360)

    st.divider()
    st.subheader(
        "⚠️ Inadimplência por Rating",
        help="Taxa de inadimplência observada (target=1) em cada faixa de rating, calculada como "
        "soma de target ÷ contagem de contratos daquele rating — separado para a base de Referência "
        "e para a de Produção. Serve para checar se a ordenação de risco dos ratings (pior rating = "
        "mais inadimplência) continua fazendo sentido na carteira real.",
    )
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
    st.subheader(
        "📉 Curva ROC & Estabilidade (PSI)",
        help="Curva ROC: sensibilidade (acerto entre maus pagadores) vs. 1-especificidade (erro entre "
        "bons pagadores) em cada corte de score possível — quanto mais a curva 'abraça' o canto "
        "superior esquerdo, melhor o modelo; AUC e Gini de cada base aparecem na legenda. PSI por "
        "decil: contribuição de cada um dos 10 decis de score para o PSI total (ver métrica PSI "
        "acima), com linha marcando o limite recomendado por decil — ajuda a achar em qual faixa de "
        "score a distribuição mais mudou.",
    )
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
    st.subheader(
        "📊 Curva KS — Separação entre Bons e Maus",
        help="Proporção acumulada de bons pagadores (target=0) e maus pagadores (target=1) ao longo "
        "dos valores de score, para Referência e Produção separadamente. O ponto de maior distância "
        "vertical entre as duas curvas é exatamente o valor de KS mostrado nos indicadores acima.",
    )
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


def render_monitoramento():
    """Roda em `st.fragment`: mexer em qualquer filtro (datas, botão de
    recarregar) só reprocessa esta aba, sem esmaecer o app inteiro."""
    _render_monitoramento_body()
