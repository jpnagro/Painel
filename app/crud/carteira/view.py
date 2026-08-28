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


@st.fragment
def _render_carteira_body():
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
    st.subheader(
        "📊 Resumo da carteira total",
        help="Todos os contratos-raiz do recorte de filtros (Produto/Portfolio/Período), sem excluir "
        "nada — inclui quitados e write-off. Não é igual à soma de 'Em aberto' + 'WriteOff', pois "
        "também conta os já quitados.",
    )
    resumo = resultados["resumo_carteira"].iloc[0]
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Nº contratos", f"{int(resumo['n_contratos']):,}", help="Contagem de contratos-raiz do recorte (renegociações são somadas à raiz, nunca contadas à parte).")
    c2.metric("Valor originado", _brl(resumo["valor_originado_total"]), help="Soma do valor de principal (principalAmount) concedido — sempre o valor original do contrato, nunca duplicado por renegociação.")
    c3.metric("Valor total das parcelas", _brl(resumo["valor_total_parcelas"]), help="Soma do valor cheio (pago + em aberto) de todas as parcelas dos contratos do recorte.")
    c4.metric("Valor pago", _brl(resumo["valor_pago"]), help="Soma dos valores já pagos nas parcelas dos contratos do recorte.")
    c5.metric("Saldo devedor", _brl(resumo["saldo_devedor_total"]), help="Soma do saldo em aberto (valor de face das parcelas ainda não pagas) dos contratos do recorte.")
    c6.metric("Saldo NPL 90+", _brl(resumo['saldo_npl']), help="Soma do saldo devedor apenas dos contratos do recorte com atraso ≥90 dias em alguma parcela em aberto (contrato inteiro entra, não só a parcela atrasada).")
    # c6.metric("Prazo médio (meses)", f"{resumo['prazo_medio_meses']:.1f}")


    st.subheader(
        "📊 Resumo da carteira em aberto",
        help="Mesmos 6 indicadores do bloco 'Total', mas excluindo contratos já 100% quitados e "
        "contratos em write-off (atraso ≥360 dias) — é a carteira 'viva', ainda não baixada.",
    )
    resumo = resultados["resumo_carteira_aberta"].iloc[0]
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Nº contratos", f"{int(resumo['n_contratos']):,}", help="Contagem de contratos-raiz em aberto (não quitados e sem atingir 360 dias de atraso).")
    c2.metric("Valor originado", _brl(resumo["valor_originado_total"]), help="Soma do valor de principal concedido nos contratos em aberto.")
    c3.metric("Valor total das parcelas", _brl(resumo["valor_total_parcelas"]), help="Soma do valor cheio (pago + em aberto) das parcelas dos contratos em aberto.")
    c4.metric("Valor pago", _brl(resumo["valor_pago"]), help="Soma dos valores já pagos nas parcelas dos contratos em aberto.")
    c5.metric("Saldo devedor", _brl(resumo["saldo_devedor_total"]), help="Soma do saldo em aberto dos contratos em aberto.")
    c6.metric("Saldo NPL 90+", _brl(resumo['saldo_npl']), help="Soma do saldo devedor dos contratos em aberto com atraso ≥90 dias — mesma base usada no gráfico 'NPL por faixa de atraso' abaixo.")
    # c6.metric("Prazo médio (meses)", f"{resumo['prazo_medio_meses']:.1f}")


    st.subheader(
        "📊 Resumo da carteira em WriteOff",
        help="Apenas os contratos-raiz com atraso ≥360 dias em alguma parcela — considerados "
        "baixados a prejuízo. Como todo write-off já passou dos 90 dias, o 'Saldo NPL 90+' aqui é "
        "igual ao 'Saldo devedor' deste bloco.",
    )
    resumo = resultados["resumo_carteira_writeoff"].iloc[0]
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Nº contratos", f"{int(resumo['n_contratos']):,}", help="Contagem de contratos-raiz com atraso ≥360 dias em alguma parcela.")
    c2.metric("Valor originado", _brl(resumo["valor_originado_total"]), help="Soma do valor de principal concedido nos contratos em write-off.")
    c3.metric("Valor total das parcelas", _brl(resumo["valor_total_parcelas"]), help="Soma do valor cheio (pago + em aberto) das parcelas dos contratos em write-off.")
    c4.metric("Valor pago", _brl(resumo["valor_pago"]), help="Soma dos valores já pagos nas parcelas dos contratos em write-off, antes da baixa.")
    c5.metric("Saldo devedor", _brl(resumo["saldo_devedor_total"]), help="Soma do saldo em aberto dos contratos em write-off.")
    c6.metric("Saldo NPL 90+", _brl(resumo['saldo_npl']), help="Igual ao 'Saldo devedor' deste bloco — todo contrato em write-off (≥360 dias) já está muito além do corte de 90 dias.")
    # c6.metric("Prazo médio (meses)", f"{resumo['prazo_medio_meses']:.1f}" if resumo["prazo_medio_meses"] is not None else "-",)

    # --- Book de renegociações ------------------------------------------------------
    st.divider()
    st.subheader(
        "🔁 Book de renegociações",
        help="Contratos-raiz que já passaram por ao menos uma renegociação, analisados separadamente "
        "— nunca somados aos indicadores dos blocos 'Total/Em aberto/WriteOff' acima, para não contar "
        "o mesmo crédito duas vezes.",
    )
    st.caption("Análise separada — nunca somada aos indicadores principais acima.")
    reneg = resultados["renegociacao_taxa"].iloc[0]
    c1, c2, c3 = st.columns(3)
    c1.metric("Contratos renegociados", f"{int(reneg['n_contratos_renegociados']):,}", help="Contagem de contratos-raiz que já foram renegociados ao menos uma vez.")
    c2.metric("Taxa de renegociação", _pct(reneg["taxa_renegociacao_pct"]), help="Contratos renegociados ÷ total de contratos-raiz do recorte.")
    c3.metric("Valor total renegociado", _brl(reneg["valor_total_renegociado"]), help="Saldo que os contratos tinham no momento em que foram substituídos pela renegociação.")

    c1, c2, c3 = st.columns(3)
    c1.metric("Valor total das renegociações", _brl(reneg["valor_total_parcelas"]), help="Soma do valor cheio das parcelas que resultaram das renegociações (a 'nova' dívida reestruturada).")
    c2.metric("Valor pago", _brl(reneg["valor_pago"]), help="Soma do que já foi pago dessas parcelas renegociadas.")
    c3.metric("Saldo devedor", _brl(reneg["saldo_devedor"]), help="Soma do que ainda está em aberto dessas parcelas renegociadas.")

    # --- NPL por faixa e aging -----------------------------------------------
    st.divider()
    st.subheader(
        "⚠️ NPL por faixa de atraso & Aging",
        help="Ambos calculados sobre a carteira em aberto (exclui write-off) e SOBRE O SALDO DEVEDOR "
        "(o que ainda falta pagar) — é aqui que o Painel usa o termo 'NPL', diferente da "
        "'Inadimplência' usada no resto do Painel (Painel Executivo, Análise de Risco), que divide "
        "pelo saldo TOTAL contratado (pago + em aberto). 'NPL por faixa': para cada corte (15/30/60/"
        "90 dias), % do saldo devedor de contratos com atraso ≥ aquele corte (contrato inteiro entra "
        "se qualquer parcela atingir o corte) ÷ saldo devedor total da carteira em aberto. 'Aging': % "
        "do saldo devedor em cada faixa fixa de atraso (em dia, 1-30, 31-60, 61-90, 90+) — uma foto "
        "da carteira hoje.",
    )
    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(build_npl_faixa_chart(resultados["npl_por_faixa"]), width="stretch")
        st.dataframe(resultados["npl_por_faixa"], hide_index=True, width="stretch")
    with col_b:
        st.plotly_chart(build_aging_chart(resultados["aging"]), width="stretch")
        st.dataframe(resultados["aging"], hide_index=True, width="stretch")

    # --- Taxas-chave ----------------------------------------------------------
    st.divider()
    st.subheader(
        "📈 Taxas-chave",
        help="Cinco taxas percentuais sobre a carteira do recorte — ver o help de cada uma para a "
        "fórmula exata; repare que 'Write-off (contratos)' e 'Write-off (% saldo originado)' usam "
        "critérios diferentes de write-off (ver help de cada uma).",
    )
    default_fpd = resultados["default_fpd"].iloc[0]
    writeoff = resultados["writeoff"].iloc[0]
    pct_renegociado = resultados['taxa_renegociados'].iloc[0]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Taxa de default", _pct(default_fpd["taxa_default_contratos_pct"]), help="% de contratos marcados como em default no sistema de origem (flag bruto do banco).")
    c2.metric("First payment default", _pct(default_fpd["taxa_fpd_pct"]), help="% de contratos marcados pelo sistema de origem com a flag 'primeira parcela em atraso' (campo firstPaymentDefault) — vem pronto do banco, não é recalculado aqui.")
    c3.metric("Write-off (contratos)", _pct(writeoff["pct_contratos_com_baixa"]), help="% de contratos com alguma parcela sinalizada pelo flag bruto 'writeOff' do sistema de origem — população calculada de forma independente do corte de 360 dias, então pode divergir do indicador ao lado.")
    c4.metric("Write-off (% saldo originado)", _pct(writeoff["pct_saldo_baixado_sobre_originado"]), help="% do valor originado que pertence a contratos com atraso ≥360 dias (corte padrão 'WO=360' do Painel) — critério diferente do flag bruto usado em 'Write-off (contratos)', os dois podem não bater.")
    c5.metric("Taxa de renegociados", _pct(pct_renegociado["pct_renegociado"]), help="% de contratos-raiz do recorte que já foram renegociados ao menos uma vez.")

    # --- Curva de maturação por safra (vintage) ----------------------------------
    st.divider()
    st.subheader(
        "📅 Curva de maturação por safra",
        help="Para cada combinação safra x idade (meses desde a originação), reconstrói parcela a "
        "parcela qual seria o atraso de cada contrato naquele momento do passado (usando dueDate/"
        "paymentDate reais). % NPL da safra na idade X = (saldo em aberto de contratos com atraso "
        "≥90d naquela idade) ÷ (valor total originado pela safra, fixo). O denominador não muda com "
        "o tempo; o numerador usa o saldo que estava de fato em aberto naquele momento passado.",
    )
    st.caption(
        "% do valor originado em inadimplência 90+ por idade da safra (meses desde a originação) — "
        "reconstruída mês a mês a partir de dueDate/paymentDate, permitindo comparar safras "
        "na mesma idade de vida."
    )
    curva = resultados["curva_maturacao_safra"]
    if not curva.empty:
        tab_mapa, tab_linhas = st.tabs(["🗺️ Mapa de calor (visão geral)", "📈 Comparar safras"])

        with tab_mapa:
            st.caption(
                "Cada linha é uma safra e cada coluna é a idade dela em meses. A cor mostra o "
                "% de inadimplência 90+ naquele momento — verde até 20%, amarelo a partir de 20%, "
                "vermelho a partir de 40%, vermelho bem escuro perto de 100% (escala fixa, não muda "
                "com o filtro). Dá pra ler na horizontal (como uma safra evolui com a idade) ou na "
                "vertical (comparar safras na mesma idade)."
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
    st.subheader(
        "🔀 Matriz de rolagem (roll-rate)",
        help="Usando a mesma reconstrução mês a mês da curva de maturação, identifica em qual faixa "
        "de atraso cada contrato estava em cada mês e para qual faixa foi no mês seguinte. Agrega "
        "todas as transições do histórico: para cada faixa de origem (linha), % de contratos que foi "
        "para cada faixa de destino (coluna). A diagonal mostra quem ficou estável.",
    )
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
    st.subheader(
        "💰 Rentabilidade",
        help="Indicadores de retorno da carteira do recorte, incluindo write-off e quitados (não é "
        "restrito à carteira em aberto).",
    )
    rent = resultados["rentabilidade"].iloc[0]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Yield médio mensal", _pct(rent["yield_medio_mensal_ponderado_pct"]), help="Taxa de juros mensal contratada, ponderada pelo saldo devedor atual de cada contrato (contratos com mais saldo em aberto pesam mais na média).")
    c2.metric("Yield médio anual", _pct(rent["yield_medio_anual_ponderado_pct"]), help="Mesma lógica do yield mensal, usando a taxa de juros anual contratada, ponderada pelo saldo devedor.")
    c3.metric("Receita total", _brl(rent["receita_total"]), help="Soma da receita total apurada nos contratos do recorte (originação + tesouraria).")
    c4.metric("Receita originação", _brl(rent["receita_originacao"]), help="Parcela da receita total atribuída à originação do crédito.")
    c5.metric("Receita tesouraria", _brl(rent["receita_tesouraria"]), help="Parcela da receita total atribuída à tesouraria.")

    # --- Concentração (HHI) ------------------------------------------------------
    st.divider()
    st.subheader(
        "🎯 Concentração de carteira (cliente)",
        help="Mede o quanto a carteira (contratos com saldo devedor em aberto, o que inclui "
        "write-off — não é o mesmo recorte de 'Carteira em aberto' das outras seções) depende de "
        "poucos clientes grandes, usando o Índice Herfindahl-Hirschman (HHI): soma do quadrado da "
        "participação % de cada cliente (CPF/CNPJ, campo taxId) no saldo devedor total. Varia de "
        "perto de 0 (muito pulverizada) a 10.000 (um único cliente concentra tudo).",
    )
    hhi_resumo = resultados["concentracao_cliente_resumo"].iloc[0]
    c1, c2 = st.columns(2)
    c1.metric("HHI", f"{hhi_resumo['HHI']:.1f}", help="Soma do quadrado da participação % de cada cliente no saldo devedor com saldo em aberto (inclui write-off). Quanto maior, mais concentrada.")
    c2.metric("% saldo no top 10 clientes", _pct(hhi_resumo["pct_saldo_top10"]), help="Soma da participação % dos 10 clientes com maior saldo devedor sobre o saldo devedor total.")
    with st.expander("Ver top 15 clientes por concentração de saldo", expanded=False):
        st.plotly_chart(
            build_concentracao_chart(resultados["concentracao_cliente_top15"], "taxId"),
            width="stretch",
        )
        st.dataframe(resultados["concentracao_cliente_top15"], hide_index=True, width="stretch")

    # --- Perfil de risco do cliente ------------------------------------------------
    st.divider()
    st.subheader(
        "🧑‍💼 Perfil de risco do cliente",
        help="NPL 90+ (sobre o SALDO DEVEDOR, não o saldo total contratado — mesma metodologia do "
        "'NPL por faixa de atraso' acima, diferente da 'Inadimplência' do resto do Painel) "
        "segmentado por rating, estado (UF) e setor (CNAE) do cliente — só para contratos CCB, "
        "cruzados com os dados cadastrais de client_data. Exclui write-off (atraso ≥360 dias), igual "
        "ao 'NPL por faixa de atraso' acima, para os dois números serem comparáveis.",
    )
    with st.expander("NPL 90+ por rating", expanded=False):
        st.caption(
            "% NPL90+ = saldo devedor dos contratos daquele rating com atraso ≥90 dias ÷ saldo "
            "devedor total do rating (contratos em write-off excluídos). Campos: rating_v4 (client_data) "
            "e max_delay/saldo_atual (installments)."
        )
        st.plotly_chart(
            build_npl_por_dimensao_chart(resultados["npl_por_rating"], "rating_v4", "NPL 90+ por rating"),
            width="stretch",
        )
        st.dataframe(resultados["npl_por_rating"], hide_index=True, width="stretch")
    with st.expander("NPL 90+ por estado (UF)", expanded=False):
        st.caption(
            "Mesma fórmula do NPL 90+ por rating, agrupando por estado (UF) do cliente em vez de "
            "rating. Campo: state (client_data)."
        )
        st.plotly_chart(
            build_npl_por_dimensao_chart(resultados["npl_por_estado"], "state", "NPL 90+ por estado"),
            width="stretch",
        )
        st.dataframe(resultados["npl_por_estado"], hide_index=True, width="stretch")
    with st.expander("NPL 90+ por setor (CNAE)", expanded=False):
        st.caption(
            "Mesma fórmula do NPL 90+ por rating, agrupando pelo setor de atividade (CNAE) do "
            "cliente. Campo: cnaeFiltered (client_data)."
        )
        st.plotly_chart(
            build_npl_por_dimensao_chart(resultados["npl_por_setor"], "cnaeFiltered", "NPL 90+ por setor"),
            width="stretch",
        )
        st.dataframe(resultados["npl_por_setor"], hide_index=True, width="stretch")

    # restritivos = resultados["restricoes_cadastrais"].iloc[0]
    # st.markdown("**Restrições cadastrais**")
    # c1, c2, c3, c4, c5 = st.columns(5)
    # c1.metric("Protesto", _pct(restritivos["pct_clientes_com_protesto"]))
    # c2.metric("Restritivo nacional", _pct(restritivos["pct_clientes_restritivo_nacional"]))
    # c3.metric("PEP", _pct(restritivos["pct_clientes_pep"]))
    # c4.metric("Mandado de prisão", _pct(restritivos["pct_clientes_mandado_prisao"]))
    # c5.metric("Trabalho escravo", _pct(restritivos["pct_clientes_trabalho_escravo"]))


def render_carteira():
    """Roda em `st.fragment`: mexer em qualquer filtro (cabeçalho ou meio
    da aba) só reprocessa esta aba, sem esmaecer o app inteiro."""
    _render_carteira_body()
