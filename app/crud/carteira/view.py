import pandas as pd
import streamlit as st

from crud.carteira.charts import (
    build_aging_chart,
    build_concentracao_chart,
    build_curva_maturacao_heatmap,
    build_curva_maturacao_linhas,
    build_matriz_rolagem_heatmap,
    build_mix_produto_chart,
    build_npl_faixa_chart,
    build_npl_por_dimensao_chart,
)
from crud.carteira.data import SEM_CLIENT_DATA, carregar_dados, get_engine, ops_raiz_por_operation_type
from crud.carteira.indicators import calcular_indicadores
from core.ui import colunas_compactas


@st.cache_data(ttl=3600, show_spinner=False)
def load_dados_brutos():
    """Lê as 5 tabelas do SGC por inteiro — é a parte lenta (consulta ao
    Postgres). Fica em cache uma única vez, independente dos filtros
    selecionados, para que trocar produto/subfiltro/portfolio não repita
    a consulta ao banco."""
    engine = get_engine()
    return carregar_dados(engine)


@st.cache_data(ttl=3600, show_spinner=False)
def load_indicadores(
    produtos=("CCB", "CPR"), subfiltro_ccb=None, subfiltro_cpr=None, portfolios=None,
    data_inicio=None, data_fim=None,
):
    """Calcula os indicadores a partir da base já em memória (cache de
    `load_dados_brutos`). Cada combinação de filtros tem sua própria
    entrada de cache, então a primeira vez que se seleciona uma combinação
    recalcula (rápido, só pandas em memória) e as trocas seguintes (já
    vistas) são instantâneas."""
    ccb, cpr, inst_ccb, inst_cpr, client = load_dados_brutos()
    return calcular_indicadores(
        ccb, cpr, inst_ccb, inst_cpr, client,
        produtos=produtos, subfiltro_ccb=subfiltro_ccb, subfiltro_cpr=subfiltro_cpr, portfolios=portfolios,
        data_inicio=data_inicio, data_fim=data_fim,
    )


def _brl(v):
    if v is None:
        return "-"
    return f"R$ {v:,.2f}"


def _pct(v):
    if v is None:
        return "-"
    return f"{v:.2f}%"


def render_carteira():
    st.title("💼 Análise da Carteira de Crédito")
    st.caption(
        "Indicadores calculados a partir das tabelas do SGC (ccb, cpr, installments, "
        "installments_cpr, client_data). Contratos renegociados são excluídos dos "
        "indicadores principais e analisados separadamente no book de renegociações."
    )

    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        refresh = st.button("🔄 Recarregar dados", key="cart_refresh")
    if refresh:
        load_dados_brutos.clear()
        load_indicadores.clear()

    ccb_bruto, cpr_bruto, inst_ccb_bruto, inst_cpr_bruto, client_bruto = load_dados_brutos()

    # Filtros dentro de um `st.form`: as mudanças só são aplicadas (e a aba
    # só recalcula/re-renderiza a partir daqui) quando "🔍 Filtrar" é
    # clicado -- evita recarregar tudo a cada seleção individual.
    with st.form("cart_filtros_form"):
        portfolios_disponiveis = sorted(
            set(inst_ccb_bruto["portfolio"].dropna().unique())
            | set(inst_cpr_bruto["portfolio"].dropna().unique())
        )
        portfolios_selecionados = st.multiselect(
            "Portfolio",
            options=portfolios_disponiveis,
            default=portfolios_disponiveis,
            key="cart_filtro_portfolio",
            help="Fundo/veículo que detém o recebível (installments.portfolio / "
            "installments_cpr.portfolio). Desmarcar todos mostra carteira vazia.",
        )

        # Lê a seleção corrente de "Produto" antes de montar a linha, pra
        # decidir quais subfiltros (CCB/CPR) ficam ativos e evitar lacuna
        # vazia quando um dos dois não está selecionado.
        produtos_atual = st.session_state.get("cart_filtro_produto", ["CCB", "CPR"])
        col_produto, col_ccb, col_cpr = colunas_compactas(
            [True, "CCB" in produtos_atual, "CPR" in produtos_atual]
        )

        with col_produto:
            produtos_selecionados = st.multiselect(
                "Produto",
                options=["CCB", "CPR"],
                default=["CCB", "CPR"],
                key="cart_filtro_produto",
                help="Selecione os dois para ver a carteira consolidada, ou apenas um pra restringir.",
            )

        subfiltro_ccb = None
        if col_ccb is not None:
            with col_ccb:
                # SEM_CLIENT_DATA só aparece como opção se hoje existir de fato
                # ao menos uma raiz CCB sem linha correspondente em client_data —
                # sem essa checagem, ela ficaria poluindo o filtro pra sempre,
                # mesmo depois de a base de client_data ser completada.
                tipos_ccb = ["App", "Crédito Produtor"]
                tem_sem_client_data = len(ops_raiz_por_operation_type(ccb_bruto, client_bruto, SEM_CLIENT_DATA)) > 0
                if tem_sem_client_data:
                    tipos_ccb.append(SEM_CLIENT_DATA)
                subfiltro_ccb = st.multiselect(
                    "Tipo de operação (CCB)",
                    options=tipos_ccb,
                    default=tipos_ccb,
                    key="cart_subfiltro_ccb",
                    help=(
                        f"'{SEM_CLIENT_DATA}' = contratos sem registro correspondente em client_data."
                        if tem_sem_client_data else None
                    ),
                )

        subfiltro_cpr = None
        if col_cpr is not None:
            with col_cpr:
                tipos_cpr = sorted(cpr_bruto["productType"].dropna().unique().tolist())
                subfiltro_cpr = st.multiselect(
                    "Tipo de produto (CPR)",
                    options=tipos_cpr,
                    default=tipos_cpr,
                    key="cart_subfiltro_cpr",
                )

        # --- Período (só as datas, sem radio) — default cobre toda a
        # carteira: da originação mais antiga até hoje.
        min_data_geral = pd.concat(
            [pd.to_datetime(ccb_bruto["releaseDate"]), pd.to_datetime(cpr_bruto["releaseDate"])]
        ).min()
        hoje = pd.Timestamp.now().date()
        col_ini, col_fim, _col_periodo_spacer = st.columns([1, 1, 8])
        with col_ini:
            data_inicio = st.date_input(
                "Início", value=min_data_geral.date(), min_value=min_data_geral.date(),
                max_value=hoje, key="cart_data_inicio",
            )
        with col_fim:
            data_fim = st.date_input(
                "Fim", value=hoje, min_value=min_data_geral.date(),
                max_value=hoje, key="cart_data_fim",
            )

        st.form_submit_button("🔍 Filtrar", type="primary")

    error_msg = None
    with st.spinner("Calculando indicadores a partir do SGC..."):
        try:
            resultados = load_indicadores(
                tuple(sorted(produtos_selecionados)),
                tuple(sorted(subfiltro_ccb)) if subfiltro_ccb is not None else None,
                tuple(sorted(subfiltro_cpr)) if subfiltro_cpr is not None else None,
                tuple(sorted(portfolios_selecionados)),
                data_inicio,
                data_fim,
            )
        except Exception as exc:
            error_msg = str(exc)
            resultados = None
            raise

    if error_msg:
        st.error(f"Erro ao carregar dados do SGC: {error_msg}")
        st.stop()

    # --- Resumo da carteira -------------------------------------------------
    st.divider()
    st.subheader("📊 Resumo da carteira total")
    resumo = resultados["resumo_carteira"].iloc[0]
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Nº contratos", f"{int(resumo['n_contratos']):,}")
    c2.metric("Valor originado", _brl(resumo["valor_originado_total"]))
    c3.metric("Valor total das parcelas", _brl(resumo["valor_total_parcelas"]))
    c4.metric("Valor pago", _brl(resumo["valor_pago"]))
    c5.metric("Saldo devedor", _brl(resumo["saldo_devedor_total"]))
    c6.metric("Saldo NPL 90+", _brl(resumo['saldo_npl']))
    # c6.metric("Prazo médio (meses)", f"{resumo['prazo_medio_meses']:.1f}")


    st.subheader("📊 Resumo da carteira em aberto")
    resumo = resultados["resumo_carteira_aberta"].iloc[0]
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Nº contratos", f"{int(resumo['n_contratos']):,}")
    c2.metric("Valor originado", _brl(resumo["valor_originado_total"]))
    c3.metric("Valor total das parcelas", _brl(resumo["valor_total_parcelas"]))
    c4.metric("Valor pago", _brl(resumo["valor_pago"]))
    c5.metric("Saldo devedor", _brl(resumo["saldo_devedor_total"]))
    c6.metric("Saldo NPL 90+", _brl(resumo['saldo_npl']))
    # c6.metric("Prazo médio (meses)", f"{resumo['prazo_medio_meses']:.1f}")


    st.subheader("📊 Resumo da carteira em WriteOff")
    resumo = resultados["resumo_carteira_writeoff"].iloc[0]
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Nº contratos", f"{int(resumo['n_contratos']):,}")
    c2.metric("Valor originado", _brl(resumo["valor_originado_total"]))
    c3.metric("Valor total das parcelas", _brl(resumo["valor_total_parcelas"]))
    c4.metric("Valor pago", _brl(resumo["valor_pago"]))
    c5.metric("Saldo devedor", _brl(resumo["saldo_devedor_total"]))
    c6.metric("Saldo NPL 90+", _brl(resumo['saldo_npl']))
    # c6.metric("Prazo médio (meses)", f"{resumo['prazo_medio_meses']:.1f}" if resumo["prazo_medio_meses"] is not None else "-",)

    # --- Book de renegociações ------------------------------------------------------
    st.divider()
    st.subheader("🔁 Book de renegociações")
    st.caption("Análise separada — nunca somada aos indicadores principais acima.")
    reneg = resultados["renegociacao_taxa"].iloc[0]
    c1, c2, c3 = st.columns(3)
    c1.metric("Contratos renegociados", f"{int(reneg['n_contratos_renegociados']):,}")
    c2.metric("Taxa de renegociação", _pct(reneg["taxa_renegociacao_pct"]))
    c3.metric("Valor total renegociado", _brl(reneg["valor_total_renegociado"]))

    c1, c2, c3 = st.columns(3)
    c1.metric("Valor total das renegociações", _brl(reneg["valor_total_parcelas"]))
    c2.metric("Valor pago", _brl(reneg["valor_pago"]))
    c3.metric("Saldo devedor", _brl(reneg["saldo_devedor"]))

    # perfil_antes = resultados["renegociacao_perfil_antes"]
    # if not perfil_antes.empty:
    #     antes = perfil_antes.iloc[0]
    #     st.markdown("**Perfil dos contratos antes da renegociação**")
    #     c1, c2, c3 = st.columns(3)
    #     c1.metric("Estavam em default", _pct(antes["pct_estavam_em_default"]))
    #     c2.metric("Atraso médio (dias)", f"{antes['atraso_medio_dias']:.1f}")
    #     c3.metric("Estavam em 90+ dias", _pct(antes["pct_max_delay_90mais"]))

    # --- Mix por produto -----------------------------------------------------
    # st.divider()
    # st.subheader("🧾 Mix por produto")
    # col_a, col_b = st.columns([1.3, 1])
    # with col_a:
    #     st.plotly_chart(build_mix_produto_chart(resultados["mix_produto"]), width="stretch")
    # with col_b:
    #     st.dataframe(
    #         resultados["mix_produto"].style.format({"saldo_devedor": "{:,.2f}"}),
    #         hide_index=True, width="stretch",
    #     )

    # --- NPL por faixa e aging -----------------------------------------------
    st.divider()
    st.subheader("⚠️ NPL por faixa de atraso & Aging")
    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(build_npl_faixa_chart(resultados["npl_por_faixa"]), width="stretch")
        st.dataframe(resultados["npl_por_faixa"], hide_index=True, width="stretch")
    with col_b:
        st.plotly_chart(build_aging_chart(resultados["aging"]), width="stretch")
        st.dataframe(resultados["aging"], hide_index=True, width="stretch")

    # --- Taxas-chave ----------------------------------------------------------
    st.divider()
    st.subheader("📈 Taxas-chave")
    default_fpd = resultados["default_fpd"].iloc[0]
    writeoff = resultados["writeoff"].iloc[0]
    prepag = resultados["prepagamento_renovacao"].iloc[0]
    pct_renegociado = resultados['taxa_renegociados'].iloc[0]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Taxa de default", _pct(default_fpd["taxa_default_contratos_pct"]))
    c2.metric("First payment default", _pct(default_fpd["taxa_fpd_pct"]))
    c3.metric("Write-off (contratos)", _pct(writeoff["pct_contratos_com_baixa"]))
    c4.metric("Write-off (% saldo originado)", _pct(writeoff["pct_saldo_baixado_sobre_originado"]))
    c5.metric("Taxa de renegociados", _pct(pct_renegociado["pct_renegociado"]))
    # c5.metric("Pré-pagamento", _pct(prepag["taxa_prepagamento_contratos_pct"]))
    # c6.metric("Renovação", _pct(prepag["taxa_renovacao_contratos_pct"]))

    # --- Curva de maturação por safra (vintage) ----------------------------------
    st.divider()
    st.subheader("📅 Curva de maturação por safra")
    st.caption(
        "% do valor originado em NPL90+ por idade da safra (meses desde a originação) — "
        "reconstruída mês a mês a partir de dueDate/paymentDate, permitindo comparar safras "
        "na mesma idade de vida."
    )
    curva = resultados["curva_maturacao_safra"]
    if not curva.empty:
        tab_mapa, tab_linhas = st.tabs(["🗺️ Mapa de calor (visão geral)", "📈 Comparar safras"])

        with tab_mapa:
            st.caption(
                "Cada linha é uma safra e cada coluna é a idade dela em meses. A cor mostra o "
                "% de NPL90+ naquele momento — mais vermelho = pior. Dá pra ler na horizontal "
                "(como uma safra evolui com a idade) ou na vertical (comparar safras na mesma idade)."
            )
            st.plotly_chart(build_curva_maturacao_heatmap(curva), width="stretch")

        with tab_linhas:
            safras_disponiveis = sorted(curva["safra"].unique(), reverse=True)
            safras_default = safras_disponiveis[:6]
            safras_selecionadas = st.multiselect(
                "Safras para comparar (a linha tracejada preta é a média de toda a carteira)",
                options=safras_disponiveis,
                default=safras_default,
                key="curva_maturacao_safras_selecionadas",
            )
            if safras_selecionadas:
                st.plotly_chart(
                    build_curva_maturacao_linhas(curva, safras_selecionadas), width="stretch"
                )
            else:
                st.info("Selecione ao menos uma safra para comparar.")

        with st.expander("Ver tabela", expanded=False):
            st.dataframe(curva, hide_index=True, width="stretch")
    else:
        st.info("Sem dados de maturação disponíveis.")

    # --- Matriz de rolagem (roll-rate) --------------------------------------------
    st.divider()
    st.subheader("🔀 Matriz de rolagem (roll-rate)")
    st.caption(
        "Transição mês a mês entre faixas de atraso, agregada ao longo de todo o histórico: "
        "de cada bucket em que o contrato estava, para qual bucket foi no mês seguinte."
    )
    matriz = resultados["matriz_rolagem"]
    if not matriz.empty:
        st.plotly_chart(build_matriz_rolagem_heatmap(matriz), width="stretch")
        with st.expander("Ver tabela", expanded=False):
            st.dataframe(matriz, hide_index=True, width="stretch")
    else:
        st.info("Sem dados de rolagem disponíveis.")

    # --- Rentabilidade ----------------------------------------------------------
    st.divider()
    st.subheader("💰 Rentabilidade")
    rent = resultados["rentabilidade"].iloc[0]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Yield médio mensal", _pct(rent["yield_medio_mensal_ponderado_pct"]))
    c2.metric("Yield médio anual", _pct(rent["yield_medio_anual_ponderado_pct"]))
    c3.metric("Receita total", _brl(rent["receita_total"]))
    c4.metric("Receita originação", _brl(rent["receita_originacao"]))
    c5.metric("Receita tesouraria", _brl(rent["receita_tesouraria"]))

    # --- Concentração (HHI) ------------------------------------------------------
    st.divider()
    st.subheader("🎯 Concentração de carteira (cliente)")
    hhi_resumo = resultados["concentracao_cliente_resumo"].iloc[0]
    c1, c2 = st.columns(2)
    c1.metric("HHI", f"{hhi_resumo['HHI']:.1f}")
    c2.metric("% saldo no top 10 clientes", _pct(hhi_resumo["pct_saldo_top10"]))
    with st.expander("Ver top 15 clientes por concentração de saldo", expanded=False):
        st.plotly_chart(
            build_concentracao_chart(resultados["concentracao_cliente_top15"], "taxId"),
            width="stretch",
        )
        st.dataframe(resultados["concentracao_cliente_top15"], hide_index=True, width="stretch")

    # --- Perfil de risco do cliente ------------------------------------------------
    st.divider()
    st.subheader("🧑‍💼 Perfil de risco do cliente (CCB)")
    with st.expander("NPL 90+ por rating", expanded=False):
        st.plotly_chart(
            build_npl_por_dimensao_chart(resultados["npl_por_rating"], "rating_v4", "NPL 90+ por rating"),
            width="stretch",
        )
        st.dataframe(resultados["npl_por_rating"], hide_index=True, width="stretch")
    with st.expander("NPL 90+ por estado (UF)", expanded=False):
        st.plotly_chart(
            build_npl_por_dimensao_chart(resultados["npl_por_estado"], "state", "NPL 90+ por estado"),
            width="stretch",
        )
        st.dataframe(resultados["npl_por_estado"], hide_index=True, width="stretch")
    with st.expander("NPL 90+ por setor (CNAE)", expanded=False):
        st.plotly_chart(
            build_npl_por_dimensao_chart(resultados["npl_por_setor"], "cnaeFiltered", "NPL 90+ por setor"),
            width="stretch",
        )
        st.dataframe(resultados["npl_por_setor"], hide_index=True, width="stretch")

    restritivos = resultados["restricoes_cadastrais"].iloc[0]
    st.markdown("**Restrições cadastrais**")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Protesto", _pct(restritivos["pct_clientes_com_protesto"]))
    c2.metric("Restritivo nacional", _pct(restritivos["pct_clientes_restritivo_nacional"]))
    c3.metric("PEP", _pct(restritivos["pct_clientes_pep"]))
    c4.metric("Mandado de prisão", _pct(restritivos["pct_clientes_mandado_prisao"]))
    c5.metric("Trabalho escravo", _pct(restritivos["pct_clientes_trabalho_escravo"]))
