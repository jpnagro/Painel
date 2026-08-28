import pandas as pd
import streamlit as st

from crud.analise_risco.data import filtrar_por_periodo
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
def load_indicadores_executivo(produto, carteira, data_inicio=None, data_fim=None):
    """Calcula os indicadores a partir da base já em memória (cache de
    `load_dados_executivo_brutos`). Cada combinação de produto/carteira/
    período tem sua própria entrada de cache."""
    df_bruto = load_dados_executivo_brutos()
    df_bruto = filtrar_por_periodo(df_bruto, data_inicio=data_inicio, data_fim=data_fim)
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


def _kpi_card(col, titulo, valor_total_fmt, partes_fmt, help=None):
    """`partes_fmt`: lista de strings já formatadas, uma por categoria
    (ex.: ["App: R$ 100", "Crédito Produtor: R$ 200"])."""
    with col:
        st.metric(titulo, valor_total_fmt, help=help)
        st.caption(" | ".join(partes_fmt))


@st.fragment
def _render_painel_executivo_body():
    st.title("📈 Painel Executivo")
    st.caption(
        "Nesta aba encontra-se indicadores gerais que podem ser filtrados por Produto e Carteira."
    )

    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        refresh = st.button("🔄 Recarregar dados", key="exec_refresh")
    if refresh:
        load_dados_executivo_brutos.clear()
        load_indicadores_executivo.clear()

    # Filtros dentro de um `st.form`: as mudanças só são aplicadas (e a aba
    # só recalcula/re-renderiza a partir daqui) quando "🔍 Filtrar" é
    # clicado -- evita recarregar tudo a cada seleção individual.
    with st.form("exec_filtros_form"):
        produto_selecionado = st.radio(
            "Produto", options=["CCB", "CPR"], index=0, horizontal=True, key="exec_filtro_produto",
        )
        carteira_selecionada = st.radio(
            "Carteira", options=CARTEIRAS, index=0, horizontal=True, key="exec_filtro_carteira",
            help="'Carteira em aberto': exclui contratos já quitados e os em write-off (atraso ≥360 "
            "dias). 'WriteOff': só os contratos em write-off. 'Carteira total': todos os contratos-"
            "raiz do produto, sem excluir nada.",
        )

        # --- Período (só as datas, sem radio) — default cobre toda a
        # carteira: da originação mais antiga até hoje.
        min_data_geral = load_dados_executivo_brutos()["releaseDate"].min()
        hoje = pd.Timestamp.now().date()
        col_ini, col_fim, _col_periodo_spacer = st.columns([1, 1, 8])
        with col_ini:
            data_inicio = st.date_input(
                "Início", value=min_data_geral.date(), min_value=min_data_geral.date(),
                max_value=hoje, key="exec_data_inicio",
            )
        with col_fim:
            data_fim = st.date_input(
                "Fim", value=hoje, min_value=min_data_geral.date(),
                max_value=hoje, key="exec_data_fim",
            )

        st.form_submit_button("🔍 Filtrar", type="primary")

    error_msg = None
    with st.spinner("Calculando indicadores executivos..."):
        try:
            r = load_indicadores_executivo(produto_selecionado, carteira_selecionada, data_inicio, data_fim)
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
    st.subheader(
        "1. Painel Executivo",
        help="KPIs principais do recorte atual (Produto/Carteira/Período selecionados no formulário "
        "acima). Cada card mostra o valor Total em destaque e o detalhamento por categoria (App x "
        "Crédito Produtor, ou tipos de CPR) logo abaixo.",
    )
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
        help="Soma do valor de principal dos contratos originais do recorte — renegociação nunca "
        "conta como dinheiro novo concedido.",
    )
    _kpi_card(
        c2, "Contratos Ativos",
        f"{int(vg['Total'].loc['Contratos Ativos'].iloc[0]):,}",
        _partes(vg, "Contratos Ativos", formatter=lambda v: f"{int(v):,}"),
        help="Contagem de contratos-raiz do recorte que ainda não foram 100% quitados.",
    )
    _kpi_card(
        c3, "Taxa Juros Média",
        _pct(vg["Total"].loc["Taxa de Juros Média (%)"].iloc[0]),
        _partes(vg, "Taxa de Juros Média (%)", formatter=_pct),
        help="Taxa de juros mensal contratada, ponderada pelo valor de principal de cada contrato "
        "(contratos maiores pesam mais na média).",
    )
    _kpi_card(
        c4, "Ticket Médio",
        _brl(vg["Total"].loc["Ticket Médio (R$)"].iloc[0]),
        _partes(vg, "Ticket Médio (R$)"),
        help="Média simples do valor de principal por contrato do recorte.",
    )

    c5, c6, c7, c8 = st.columns(4)
    _kpi_card(
        c5, "FPD (90d)",
        _pct(risco["Total"].loc["FPD (90d)", "% da Carteira Total"]),
        _partes(risco, "FPD (90d)", coluna_por_cat="% da Carteira {cat}", formatter=_pct),
        help="First Payment Default: fórmula canônica de '% da Carteira' — saldo das parcelas em "
        "aberto de contratos cuja 1ª parcela já não foi paga em dia, ÷ SALDO TOTAL contratado do "
        "recorte (pago + em aberto). É 'inadimplência', não 'NPL': o denominador é o total da "
        "carteira, diferente do NPL calculado na aba 'Análise da Carteira' (que usa o saldo devedor).",
    )
    _kpi_card(
        c6, "Inadimplência 90d",
        _pct(risco["Total"].loc["90+ dias", "% da Carteira Total"]),
        _partes(risco, "90+ dias", coluna_por_cat="% da Carteira {cat}", formatter=_pct),
        help="Fórmula canônica de '% da Carteira': saldo das parcelas em aberto de contratos com "
        "atraso ≥90 dias ÷ SALDO TOTAL contratado (pago + em aberto) do recorte — mesmo número e "
        "mesma fórmula usados em toda a Análise de Risco. Diferente do 'NPL 90+' calculado na aba "
        "'Análise da Carteira', que divide pelo saldo devedor (só o que ainda falta pagar) em vez do "
        "saldo total.",
    )
    _kpi_card(
        c7, "Cobertura PDD",
        _brl(fin["Total"].loc["PDD"].iloc[0]),
        _partes(fin, "PDD"),
        help="Provisão para Devedores Duvidosos = 50% do saldo de principal em aberto dos contratos "
        "com atraso ≥90 dias (ver 'Inadimplência 90+ Esperada' na tabela financeira abaixo).",
    )
    _kpi_card(
        c8, "Margem Financeira Estimada",
        _brl(fin["Total"].loc["Margem Financeira Bruta (Estimada)"].iloc[0]),
        _partes(fin, "Margem Financeira Bruta (Estimada)"),
        help="Juros efetivamente pagos menos a provisão (PDD) — uma margem financeira bruta estimada "
        "do recorte.",
    )

    if categorias:
        col_a, col_b = st.columns(2)
        with col_a:
            st.caption(
                "% do saldo a receber (parcelas em aberto, valor cheio) de cada categoria sobre o "
                "total do recorte."
            )
            st.plotly_chart(
                build_donut_chart(
                    {cat: vg[cat].loc["Valor Total a Receber (R$)"].iloc[0] for cat in categorias},
                    "Divisão da Carteira (Valor a Receber)",
                ),
                width="stretch",
            )
        with col_b:
            st.caption("% do nº de contratos ainda não quitados de cada categoria sobre o total.")
            st.plotly_chart(
                build_donut_chart(
                    {cat: vg[cat].loc["Contratos Ativos"].iloc[0] for cat in categorias},
                    "Divisão de Contratos Ativos",
                ),
                width="stretch",
            )
    st.caption(
        "% da carteira (fórmula canônica: saldo em aberto ÷ SALDO TOTAL contratado — 'inadimplência', "
        "não NPL sobre saldo devedor) em cada faixa de atraso (FPD, 15+, 30+, 60+, 90+ dias), "
        "comparando o Total com cada categoria — quanto mais alta a barra, maior a fatia do total "
        "contratado que já está naquele nível de atraso ou pior."
    )
    st.plotly_chart(build_risco_bar_chart(risco), width="stretch")

    # --- Tópico 2: Composição da Carteira -----------------------------------
    st.divider()
    st.subheader(
        "2. Composição da Carteira",
        help="10 indicadores de composição (contratos, clientes únicos, valor emprestado/a receber/"
        "pago, taxa de juros média, ticket médio, contratos ativos, novos contratos no último mês e "
        "valor desses novos contratos), lado a lado para o Total e cada categoria.",
    )
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
    st.subheader(
        "3. Indicadores de Risco e Financeiros",
        help="Duas tabelas: 'Indicadores de Risco' mostra o saldo em atraso (R$) e o % da carteira "
        "(fórmula canônica, sobre o saldo TOTAL contratado — é 'inadimplência', não 'NPL' sobre "
        "saldo devedor) em cada faixa de atraso; 'Indicadores Financeiros' traz juros, saldo e "
        "provisão — ver help de cada uma abaixo.",
    )
    st.markdown(
        "**Indicadores de Risco**",
        help="Para cada faixa de atraso (FPD 90d, 15+, 30+, 60+, 90+ dias): saldo em R$ das parcelas "
        "em aberto de contratos naquela faixa, e % da carteira = esse saldo ÷ SALDO TOTAL contratado "
        "(pago + em aberto) do recorte — a mesma fórmula canônica usada na Análise de Risco. Note que "
        "é diferente do NPL calculado na aba 'Análise da Carteira', que usa o saldo devedor como "
        "denominador em vez do saldo total.",
    )
    risco_tabela = pd.concat([risco["Total"]] + [risco[cat] for cat in categorias], axis=1)
    st.dataframe(risco_tabela.style.format("{:,.2f}"), width="stretch")

    st.markdown(
        "**Indicadores Financeiros**",
        help="Total de Juros (Contratada) = juros previstos em contrato. Juros Pagos = parte de "
        "juros já recebida. % Juros Pagos = Juros Pagos ÷ Total de Juros. Saldo Devedor = principal "
        "ainda em aberto. Inadimplência 90+ Esperada = saldo de PRINCIPAL (não parcela cheia) dos "
        "contratos com atraso ≥90 dias. PDD = 50% da Inadimplência 90+ Esperada. Margem Financeira "
        "Bruta (Estimada) = Juros Pagos − PDD.",
    )
    fin_tabela = pd.concat([fin["Total"]] + [fin[cat] for cat in categorias], axis=1)
    st.dataframe(fin_tabela.style.format("{:,.2f}"), width="stretch")

    # --- Tópico 4: Análise por Safra ----------------------------------------
    st.divider()
    st.subheader(
        "4. Análise por Safra",
        help="Para cada mês de originação: quantidade de contratos, volume concedido, saldo devedor, "
        "perda real aos 90 dias (saldo de principal efetivamente em atraso) e perda esperada (saldo "
        "de principal dos contratos em atraso ≥90 dias), com as respectivas taxas em % do volume da "
        "safra. Uma aba por categoria (App/Crédito Produtor ou tipo de CPR), além do Total.",
    )
    labels_tabs = ["Total"] + categorias
    tabs = st.tabs(labels_tabs)
    for label, tab in zip(labels_tabs, tabs):
        with tab:
            st.plotly_chart(
                build_safra_combo_chart(r["safras"][label], f"Análise por Safra — {label}"), width="stretch",
            )
            with st.expander("Ver tabela"):
                st.dataframe(r["safras"][label], width="stretch")


def render_painel_executivo():
    """Roda em `st.fragment`: mexer em qualquer filtro (cabeçalho ou meio
    da aba) só reprocessa esta aba, sem esmaecer o app inteiro."""
    _render_painel_executivo_body()
