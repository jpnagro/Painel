import pandas as pd
import streamlit as st

from crud.painel_executivo.charts import build_donut_chart, build_risco_bar_chart, build_safra_combo_chart
from crud.painel_executivo.data import CARTEIRAS
from crud.painel_executivo.indicators import calcular_indicadores_executivo, carregar_dados_executivo_bruto


@st.cache_data(ttl=3600, show_spinner=False)
def load_dados_executivo_brutos():
    """Lê a base bruta (CCB + CPR, todos os estados de carteira) — é a
    parte lenta (consulta ao Postgres). Fica em cache uma única vez,
    independente dos filtros, pra trocar Produto/Carteira não repetir a
    consulta ao banco."""
    return carregar_dados_executivo_bruto()


@st.cache_data(ttl=3600, show_spinner=False)
def load_indicadores_executivo(produto, carteira):
    """Calcula os indicadores a partir da base já em memória (cache de
    `load_dados_executivo_brutos`). Cada combinação de produto/carteira
    tem sua própria entrada de cache."""
    df_bruto = load_dados_executivo_brutos()
    return calcular_indicadores_executivo(df_bruto, produto=produto, carteira=carteira)


def _brl(v):
    if v is None:
        return "-"
    # "\$" (não "$") -- st.metric/st.caption renderizam markdown, e um par
    # de "$" não escapados na mesma linha (ex.: "App: R$ X | CP: R$ Y")
    # é interpretado como delimitador de LaTeX, bagunçando a fonte.
    return f"R\\$ {v:,.2f}"


def _pct(v):
    if v is None:
        return "-"
    return f"{v:.2f}%"


def _kpi_card(col, titulo, valor_total_fmt, partes_fmt):
    """`partes_fmt`: lista de strings já formatadas, uma por categoria
    (ex.: ["App: R$ 100", "Crédito Produtor: R$ 200"])."""
    with col:
        st.metric(titulo, valor_total_fmt)
        st.caption(" | ".join(partes_fmt))


def render_painel_executivo():
    st.title("🎯 Painel Executivo")
    st.caption(
        "Nesta aba encontra-se indicadores gerais que podem ser filtrados por Produto e Carteira."
    )

    produto_selecionado = st.radio(
        "Produto", options=["CCB", "CPR"], index=0, horizontal=True, key="exec_filtro_produto",
    )
    carteira_selecionada = st.radio(
        "Carteira", options=CARTEIRAS, index=0, horizontal=True, key="exec_filtro_carteira",
    )

    refresh = st.button("🔄 Recarregar dados", key="exec_refresh")
    if refresh:
        load_dados_executivo_brutos.clear()
        load_indicadores_executivo.clear()

    error_msg = None
    with st.spinner("Calculando indicadores executivos..."):
        try:
            r = load_indicadores_executivo(produto_selecionado, carteira_selecionada)
        except Exception as exc:
            error_msg = str(exc)
            r = None
            raise

    if error_msg:
        st.error(f"Erro ao carregar dados: {error_msg}")
        st.stop()

    categorias = r["categorias"]
    vg = r["visao_geral"]
    risco = r["risco"]
    fin = r["financeiro"]

    if not categorias:
        st.warning(
            f"Nenhuma categoria encontrada para {produto_selecionado} neste recorte de "
            "carteira — os indicadores abaixo mostram só o Total."
        )

    # --- Tópico 1: Painel Executivo -----------------------------------------
    st.divider()
    st.subheader("1. Painel Executivo")
    n_por_cat = ", ".join(f"{cat}: {r['n_por_categoria'][cat]}" for cat in categorias)
    st.caption(
        f"{r['n_total']} contratos no recorte ({r['n_ccb']} CCB / {r['n_cpr']} CPR)."
        + (f" Por categoria — {n_por_cat}." if categorias else "")
    )

    def _partes(tabela_dict, linha, coluna_por_cat=None, formatter=_brl):
        partes = []
        for cat in categorias:
            df_cat = tabela_dict[cat]
            col = coluna_por_cat.format(cat=cat) if coluna_por_cat else df_cat.columns[0]
            partes.append(f"{cat}: {formatter(df_cat.loc[linha, col])}")
        return partes

    c1, c2, c3, c4 = st.columns(4)
    _kpi_card(
        c1, "Total Concedido",
        _brl(vg["Total"].loc["Valor Total Emprestado (R$)"].iloc[0]),
        _partes(vg, "Valor Total Emprestado (R$)"),
    )
    _kpi_card(
        c2, "Contratos Ativos",
        f"{int(vg['Total'].loc['Contratos Ativos'].iloc[0]):,}",
        _partes(vg, "Contratos Ativos", formatter=lambda v: f"{int(v):,}"),
    )
    _kpi_card(
        c3, "Taxa Juros Média",
        _pct(vg["Total"].loc["Taxa de Juros Média (%)"].iloc[0]),
        _partes(vg, "Taxa de Juros Média (%)", formatter=_pct),
    )
    _kpi_card(
        c4, "Ticket Médio",
        _brl(vg["Total"].loc["Ticket Médio (R$)"].iloc[0]),
        _partes(vg, "Ticket Médio (R$)"),
    )

    c5, c6, c7, c8 = st.columns(4)
    _kpi_card(
        c5, "FPD (90d)",
        _pct(risco["Total"].loc["FPD (90d)", "% da Carteira Total"]),
        _partes(risco, "FPD (90d)", coluna_por_cat="% da Carteira {cat}", formatter=_pct),
    )
    _kpi_card(
        c6, "Inadimplência 90d",
        _pct(risco["Total"].loc["90+ dias", "% da Carteira Total"]),
        _partes(risco, "90+ dias", coluna_por_cat="% da Carteira {cat}", formatter=_pct),
    )
    _kpi_card(
        c7, "Cobertura PDD",
        _brl(fin["Total"].loc["PDD"].iloc[0]),
        _partes(fin, "PDD"),
    )
    _kpi_card(
        c8, "Margem Financeira Estimada",
        _brl(fin["Total"].loc["Margem Financeira Bruta (Estimada)"].iloc[0]),
        _partes(fin, "Margem Financeira Bruta (Estimada)"),
    )

    if categorias:
        col_a, col_b = st.columns(2)
        with col_a:
            st.plotly_chart(
                build_donut_chart(
                    {cat: vg[cat].loc["Valor Total a Receber (R$)"].iloc[0] for cat in categorias},
                    "Divisão da Carteira (Valor a Receber)",
                ),
                width="stretch",
            )
        with col_b:
            st.plotly_chart(
                build_donut_chart(
                    {cat: vg[cat].loc["Contratos Ativos"].iloc[0] for cat in categorias},
                    "Divisão de Contratos Ativos",
                ),
                width="stretch",
            )
    st.plotly_chart(build_risco_bar_chart(risco), width="stretch")

    # --- Tópico 2: Composição da Carteira -----------------------------------
    st.divider()
    st.subheader("2. Composição da Carteira")
    composicao = pd.concat([vg["Total"]] + [vg[cat] for cat in categorias], axis=1)
    st.dataframe(composicao.style.format("{:,.2f}"), width="stretch")
    if produto_selecionado == "CCB":
        st.caption(
            "A tabela acima detalha a composição da carteira, segmentando os principais "
            "indicadores entre o total, operações via aplicativo (App) e crédito para "
            "produtor (Crédito Produtor)."
        )
    else:
        st.caption(
            "A tabela acima detalha a composição da carteira, segmentando os principais "
            "indicadores entre o total e cada tipo de produto CPR (productType)."
        )

    # --- Tópico 3: Indicadores de Risco e Financeiros -----------------------
    st.divider()
    st.subheader("3. Indicadores de Risco e Financeiros")
    st.markdown("**Indicadores de Risco**")
    risco_tabela = pd.concat([risco["Total"]] + [risco[cat] for cat in categorias], axis=1)
    st.dataframe(risco_tabela.style.format("{:,.2f}"), width="stretch")

    st.markdown("**Indicadores Financeiros**")
    fin_tabela = pd.concat([fin["Total"]] + [fin[cat] for cat in categorias], axis=1)
    st.dataframe(fin_tabela.style.format("{:,.2f}"), width="stretch")

    # --- Tópico 4: Análise por Safra ----------------------------------------
    st.divider()
    st.subheader("4. Análise por Safra")
    labels_tabs = ["Total"] + categorias
    tabs = st.tabs(labels_tabs)
    for label, tab in zip(labels_tabs, tabs):
        with tab:
            st.plotly_chart(
                build_safra_combo_chart(r["safras"][label], f"Análise por Safra — {label}"), width="stretch",
            )
            with st.expander("Ver tabela"):
                st.dataframe(r["safras"][label], width="stretch")
