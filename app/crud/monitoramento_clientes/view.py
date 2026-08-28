import datetime

import pandas as pd
import streamlit as st

from crud.monitoramento_clientes.charts import (
    DIST_STATUS_COLORS,
    STATUS_COLORS_NEUTRO,
    build_rating_transition_heatmap,
    build_status_bar_chart,
    build_trajetoria_chart,
)
from crud.monitoramento_clientes.data import carregar_monitoramento_bruto
from crud.monitoramento_clientes.indicators import (
    DIST_STATUS_ORDER,
    METRICAS_DIVIDA_ATRASO,
    RATING_ORDER,
    STATUS_ORDER_COMPARACAO_RISCO,
    STATUS_ORDER_NEUTRO,
    aplicar_filtro_carteira,
    aplicar_subfiltro_tipo,
    calcular_status_pares,
    classificar_rating,
    classificar_status_carteira,
    construir_pares,
    construir_watchlist,
    historico_contrato,
    resumo_comparacao_multiplas_metricas,
    resumo_distribuicao_metricas,
    resumo_status_metricas,
    snapshot_no_periodo,
    transicao_rating,
    variacao_pct,
)
# Reaproveita a mesma constante/lista de opções de "Tipo de operação (CCB)"
# usada na aba "Análise da carteira" (`crud/carteira/data.py`), pra não
# divergir do rótulo/critério de "sem client_data" usado lá.
from crud.carteira.data import SEM_CLIENT_DATA
from core.ui import colunas_compactas
# Reaproveita a MESMA base (e o mesmo cache) já usada pela aba "Painel
# Executivo" pra saber o estado de carteira (quitado/write-off) de cada
# contrato — evita consultar o Postgres de novo só pra isso. Como o
# Streamlit cacheia por função (não por módulo chamador), chamar
# `load_dados_executivo_brutos()` aqui reaproveita o cache populado na
# renderização da aba "Painel Executivo" (que roda antes, na mesma
# execução do script) — ou, se essa aba rodar primeiro, é ela quem
# populará o cache pra a outra reaproveitar depois.
from crud.painel_executivo.data import CARTEIRAS
from crud.painel_executivo.view import load_dados_executivo_brutos


def _brl(v):
    if v is None or pd.isna(v):
        return "-"
    return f"R$ {v:,.2f}"


def _fmt_int(v):
    if v is None or pd.isna(v):
        return "-"
    return f"{int(v):,}"


def _fmt_pct_of(n, total):
    if not total:
        return "-"
    return f"{100 * n / total:.1f}%"


def _fmt_variacao_pct(atual, anterior):
    """Variação percentual formatada (com sinal) entre o valor do filtro 1
    e o valor de referência do filtro 2 — `None` quando não há referência
    válida (aparece então só o valor, sem percentual de variação)."""
    v = variacao_pct(atual, anterior)
    if v is None:
        return None
    return f"{v * 100:+.1f}%"


# Escala manual de vermelho por nº de indicadores piorando (0 a 6+) — evita
# depender de `Styler.background_gradient`, que exige matplotlib (não está
# no requirements.txt do projeto).
_CORES_SEVERIDADE = {
    0: "#f8f9fa", 1: "#ffe8d6", 2: "#ffc9a3",
    3: "#ff9d6c", 4: "#ff6f47", 5: "#e8483c", 6: "#b3001b",
}


def _cor_severidade(valor):
    if pd.isna(valor):
        return ""
    cor = _CORES_SEVERIDADE.get(int(valor), "#b3001b")
    return f"background-color: {cor}"


@st.cache_data(ttl=3600, show_spinner=False)
def load_pares_status():
    """Base bruta (cache próprio) + pareamento (registro atual x anterior)
    + classificação de status — recalculado só quando o cache da base
    bruta é limpo (botão "Recarregar dados")."""
    df_bruto = carregar_monitoramento_bruto()
    pares = construir_pares(df_bruto)
    pares_status = calcular_status_pares(pares)
    return pares_status


@st.fragment
def _render_monitoramento_clientes_body():
    st.title("🚦 Monitoramento de Clientes")
    st.caption(
        "Cada contrato é reconsultado periodicamente (rating, score, dívidas e protestos externos "
        "via Boa Vista, exposição de crédito no mercado). Esta aba compara, para cada contrato, o "
        "registro mais recente com o imediatamente anterior, para identificar quem está melhorando "
        "ou piorando desde a última consulta — o foco é sinalizar antecipadamente contratos com risco "
        "crescente de inadimplência."
    )

    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        refresh = st.button("🔄 Recarregar dados", key="moncli_refresh")
    if refresh:
        carregar_monitoramento_bruto.clear()
        load_pares_status.clear()
        # Cache compartilhado com a aba "Painel Executivo" — limpar aqui
        # também garante que o filtro de Carteira desta aba não fique
        # trabalhando com uma base de carteira desatualizada.
        load_dados_executivo_brutos.clear()

    error_msg = None
    with st.spinner("Carregando monitoramento de clientes..."):
        try:
            pares_status = load_pares_status()
        except Exception as exc:
            error_msg = str(exc)
            pares_status = None
            raise

    if error_msg:
        st.error(f"Erro ao carregar dados de monitoramento: {error_msg}")
        st.stop()

    if pares_status.empty:
        st.info("Nenhum registro encontrado em customer_monitoring.")
        st.stop()

    with col_info:
        st.caption(
            f"Última consulta registrada: "
            f"{pares_status['createdAt_atual'].max().strftime('%d/%m/%Y %H:%M')}"
        )

    df_bruto = carregar_monitoramento_bruto()
    data_max = df_bruto["createdAt"].max().date()
    fim1_default = data_max
    inicio1_default = fim1_default - datetime.timedelta(days=7)
    # Filtro 2 (referência) por padrão = período imediatamente anterior ao
    # filtro 1, com a mesma duração (7 dias) — ex.: filtro 1 = 14/08 a
    # 21/08 ⇒ filtro 2 = 06/08 a 13/08.
    fim2_default = inicio1_default - datetime.timedelta(days=1)
    inicio2_default = fim2_default - datetime.timedelta(days=7)

    # Filtros dentro de um `st.form`: as mudanças só são aplicadas (e a aba
    # só recalcula/re-renderiza a partir daqui) quando "🔍 Filtrar" é
    # clicado -- evita recarregar tudo a cada seleção individual.
    with st.form("moncli_filtros_form"):
        carteira_selecionada = st.radio(
            "Carteira",
            options=CARTEIRAS,
            index=0,
            horizontal=True,
            key="moncli_filtro_carteira",
            help=(
                "Mesmo critério da aba \"Painel Executivo\": \"Carteira em aberto\" exclui "
                "contratos já quitados e os em write-off (atraso ≥ 360 dias); \"WriteOff\" mostra "
                "só os em write-off; \"Carteira total\" não filtra por estado."
            ),
        )
        # Produto + subfiltros de tipo (mesma lógica/opções da aba "Análise da
        # carteira": "Tipo de operação (CCB)" só aparece se CCB estiver entre os
        # produtos selecionados; "Tipo de produto (CPR)", só se CPR estiver) +
        # "Status da carteira", tudo em uma única linha.
        produtos_disponiveis = sorted(pares_status["produto_atual"].dropna().unique().tolist())
        # Lê a seleção corrente de "Produto" antes de montar a linha, pra
        # decidir quais subfiltros (CCB/CPR) ficam ativos e evitar lacuna
        # vazia quando um dos dois não está selecionado — "Status da carteira"
        # sobe/desloca pra preencher o espaço.
        produtos_atual = st.session_state.get("moncli_filtro_produto", produtos_disponiveis)
        col_produto, col_sub_ccb, col_sub_cpr, col_status = colunas_compactas(
            [True, "CCB" in produtos_atual, "CPR" in produtos_atual, True]
        )

        with col_produto:
            produtos_selecionados = st.multiselect(
                "Produto",
                options=produtos_disponiveis,
                default=produtos_disponiveis,
                key="moncli_filtro_produto",
            )

        subfiltro_ccb = None
        if col_sub_ccb is not None:
            with col_sub_ccb:
                tipos_ccb = ["App", "Crédito Produtor"]
                tem_sem_client_data = bool((
                    (pares_status["produto_atual"] == "CCB")
                    & pares_status["tipo_operacao_ccb_atual"].isna()
                ).any())
                if tem_sem_client_data:
                    tipos_ccb.append(SEM_CLIENT_DATA)
                subfiltro_ccb = st.multiselect(
                    "Tipo de operação (CCB)",
                    options=tipos_ccb,
                    default=tipos_ccb,
                    key="moncli_subfiltro_ccb",
                    help=(
                        f"'{SEM_CLIENT_DATA}' = contratos sem registro correspondente em client_data."
                        if tem_sem_client_data else None
                    ),
                )

        subfiltro_cpr = None
        if col_sub_cpr is not None:
            with col_sub_cpr:
                tipos_cpr = sorted(
                    pares_status.loc[pares_status["produto_atual"] == "CPR", "tipo_produto_cpr_atual"]
                    .dropna().unique().tolist()
                )
                subfiltro_cpr = st.multiselect(
                    "Tipo de produto (CPR)",
                    options=tipos_cpr,
                    default=tipos_cpr,
                    key="moncli_subfiltro_cpr",
                )

        with col_status:
            status_carteira_selecionados = st.multiselect(
                "Status da carteira",
                options=["Carteira Inadimplente", "Carteira Adimplente"],
                default=["Carteira Adimplente"],
                key="moncli_filtro_status_carteira",
                help=(
                    "\"Carteira Inadimplente\": contratos em aberto (não quitados e sem atingir o corte de "
                    "write-off) e com atraso (max_delay > 0). \"Carteira Adimplente\": todo o restante "
                    "(quitados, write-off, ou em aberto mas em dia)."
                ),
            )

        # --- Filtros de período: análise (filtro 1) x referência (filtro 2) --
        st.subheader("🗓️ Períodos de comparação")
        st.caption(
            "**Filtro 1 (análise)** define o valor mais atual a ser exibido; **filtro 2 (referência)** "
            "define o valor usado para comparação. Em cada período, entram os contratos com ao menos "
            "uma consulta dentro do intervalo escolhido; o valor usado para cada um é o histórico "
            "acumulado até a data final do período (mesmo que a consulta mais recente registrada tenha "
            "sido feita antes do início do período)."
        )

        col_p1, col_p2, _col_periodos_spacer = st.columns([1, 1, 6])
        with col_p1:
            periodo1 = st.date_input(
                "Período de análise (filtro 1)",
                value=(inicio1_default, fim1_default),
                key="moncli_periodo1",
            )
        with col_p2:
            periodo2 = st.date_input(
                "Período de referência (filtro 2)",
                value=(inicio2_default, fim2_default),
                key="moncli_periodo2",
            )

        st.form_submit_button("🔍 Filtrar", type="primary")

    base = pares_status[pares_status["produto_atual"].isin(produtos_selecionados)].copy()
    base = aplicar_subfiltro_tipo(base, subfiltro_ccb, subfiltro_cpr)

    with st.spinner("Cruzando com o estado da carteira..."):
        executivo_bruto = load_dados_executivo_brutos()
    n_antes_filtro_carteira = len(base)
    base = aplicar_filtro_carteira(base, executivo_bruto, carteira_selecionada)
    if carteira_selecionada != "Carteira total":
        st.caption(
            f"Filtro de carteira \"{carteira_selecionada}\" removeu "
            f"{n_antes_filtro_carteira - len(base):,} de {n_antes_filtro_carteira:,} contratos "
            "(já quitados, em write-off ou sem correspondência na base do Painel Executivo, "
            "conforme o caso)."
        )

    # --- Status da carteira: Inadimplente x Adimplente (filtro já capturado
    # na linha de filtros acima, junto com Produto/CCB/CPR) ------------------
    base["status_carteira"] = classificar_status_carteira(base, executivo_bruto)
    n_antes_status_carteira = len(base)
    base = base[base["status_carteira"].isin(status_carteira_selecionados)]
    if set(status_carteira_selecionados) != {"Carteira Inadimplente", "Carteira Adimplente"}:
        st.caption(
            f"Filtro de status da carteira removeu "
            f"{n_antes_status_carteira - len(base):,} de {n_antes_status_carteira:,} contratos."
        )

    if base.empty:
        st.warning("Nenhum contrato para os filtros selecionados.")
        st.stop()

    total = len(base)
    com_historico = int(base["tem_historico"].sum())
    sem_historico = total - com_historico

    # `st.date_input` com intervalo pode devolver só 1 data momentaneamente
    # (entre o clique na data de início e na de fim) — aguarda a segunda
    # seleção em vez de quebrar.
    if not (isinstance(periodo1, (tuple, list)) and len(periodo1) == 2) or not (
        isinstance(periodo2, (tuple, list)) and len(periodo2) == 2
    ):
        st.info("Selecione a data de início e de fim dos dois períodos para continuar.")
        st.stop()

    inicio1, fim1 = periodo1
    inicio2, fim2 = periodo2

    # Restringe o histórico bruto ao mesmo universo de contratos já filtrado
    # por produto/carteira (`base`), pra manter os snapshots de período
    # consistentes com o resto da tela.
    codigos_universo = set(base["operationCode_raiz"])
    df_bruto_universo = df_bruto[df_bruto["operationCode_raiz"].isin(codigos_universo)]

    snap1 = snapshot_no_periodo(df_bruto_universo, inicio1, fim1)
    snap2 = snapshot_no_periodo(df_bruto_universo, inicio2, fim2)

    if snap1.empty:
        st.warning("Nenhum contrato monitorado no período de análise (filtro 1) selecionado.")
        st.stop()

    # Sub-bases restritas a quem tem consulta dentro de cada período — usadas
    # nos indicadores/gráficos que devem representar "quem está no filtro 1
    # (ou 2)" em vez da base inteira. A classificação de cada contrato
    # (Piorou/Melhorou/Estável) continua sendo sempre a consulta mais recente
    # contra a imediatamente anterior (não muda com o período); o que muda é
    # QUAIS contratos entram na contagem.
    base_filtro1 = base[base["operationCode_raiz"].isin(snap1.index)].copy()
    base_filtro2 = base[base["operationCode_raiz"].isin(snap2.index)].copy()

    total_filtro1 = len(base_filtro1)
    com_historico_filtro1 = int(base_filtro1["tem_historico"].sum())
    em_atencao = int((base_filtro1["n_indicadores_piorando"] >= 1).sum())
    alerta_critico = int((base_filtro1["n_indicadores_piorando"] >= 3).sum())
    obitos = int((base_filtro1["death_atual"] == True).sum())

    # --- KPIs de cobertura + alertas (lado a lado) ------------------------------
    st.divider()
    n1 = len(snap1)
    n2 = len(snap2)
    com_historico1 = int((snap1["n_registros_ate_fim"] >= 2).sum())
    sem_historico1 = n1 - com_historico1
    com_historico2 = int((snap2["n_registros_ate_fim"] >= 2).sum()) if n2 else 0
    sem_historico2 = n2 - com_historico2

    col_cobertura, col_alertas = st.columns(2)

    with col_cobertura:
        st.subheader(
            "📋 Cobertura do monitoramento",
            help="Cada indicador conta contratos com ao menos uma consulta dentro do período "
            "escolhido (filtro 1 em destaque, filtro 2 como referência abaixo). O percentual ao "
            "lado do valor é a variação entre os dois períodos.",
        )
        st.caption(
            f"Filtro 1: {inicio1.strftime('%d/%m/%Y')} a {fim1.strftime('%d/%m/%Y')}  |  "
            f"Filtro 2: {inicio2.strftime('%d/%m/%Y')} a {fim2.strftime('%d/%m/%Y')}."
        )
        cc1, cc2, cc3 = st.columns(3)
        cc1.metric(
            "Monitorados", _fmt_int(n1), _fmt_variacao_pct(n1, n2), delta_color="off",
            help="Nº de contratos com pelo menos uma consulta dentro do período de análise (filtro 1).",
        )
        cc1.caption(f"Ref.: {_fmt_int(n2)}")
        cc2.metric(
            "Com histórico (2+)", _fmt_int(com_historico1),
            _fmt_variacao_pct(com_historico1, com_historico2), delta_color="off",
            help="Quantos dos monitorados já têm 2 ou mais consultas registradas até o fim do "
            "período — só esses permitem comparar 'atual x anterior'.",
        )
        cc2.caption(f"Ref.: {_fmt_int(com_historico2)}")
        cc3.metric(
            "1ª consulta", _fmt_int(sem_historico1),
            _fmt_variacao_pct(sem_historico1, sem_historico2), delta_color="off",
            help="Contratos monitorados que ainda têm só uma consulta registrada (sem histórico "
            "anterior para comparar).",
        )
        cc3.caption(f"Ref.: {_fmt_int(sem_historico2)}")

    with col_alertas:
        st.subheader(
            "🚨 Alertas",
            help="Baseado nos 6 indicadores de risco comparados entre a consulta mais recente e a "
            "imediatamente anterior de cada contrato: dívida em atraso (overdue), prejuízo (loss), "
            "dívidas e protestos via Boa Vista, protestos gerais e rating.",
        )
        st.caption(
            f"Somente os {_fmt_int(total_filtro1)} contratos do período de análise (filtro 1)."
        )
        ca1, ca2, ca3 = st.columns(3)
        ca1.metric(
            "Em atenção", _fmt_int(em_atencao),
            f"{_fmt_pct_of(em_atencao, com_historico_filtro1)} do c/ histórico",
            delta_color="off",
            help="Contratos com pelo menos 1 dos 6 indicadores de risco piorando desde a última "
            "consulta. % calculado sobre os contratos com histórico comparável (2+ consultas).",
        )
        ca2.metric(
            "Crítico (3+)", _fmt_int(alerta_critico),
            f"{_fmt_pct_of(alerta_critico, com_historico_filtro1)} do c/ histórico",
            delta_color="off",
            help="Contratos com 3 ou mais dos 6 indicadores de risco piorando ao mesmo tempo desde a "
            "última consulta.",
        )
        ca3.metric(
            "Óbito reportado", _fmt_int(obitos), delta_color="off",
            help="Contratos cuja consulta mais recente registrou óbito do titular (campo death).",
        )

    if obitos > 0:
        st.error(
            f"⚠️ {obitos} contrato(s) com registro de óbito do titular — risco máximo de "
            "inadimplência, recomenda-se verificação imediata (garantias, avalistas, espólio)."
        )
        tabela_obitos = base_filtro1[base_filtro1["death_atual"] == True][[
            "nome_cliente_atual", "taxId_atual", "operationCode_raiz",
        ]].rename(columns={
            "nome_cliente_atual": "Nome", "taxId_atual": "CPF", "operationCode_raiz": "Contrato",
        })
        st.dataframe(tabela_obitos, hide_index=True, width="stretch")

    # --- 1) Dívidas e atrasos externos -----------------------------------------
    # st.divider()
    # st.subheader("💳 Dívidas e atrasos externos")
    # with st.expander("Como interpretar", expanded=False):
    #     st.markdown(
    #         "- **overdue**: valor em atraso identificado na consulta.\n"
    #         "- **loss**: prejuízo/perda registrado externamente.\n"
    #         "- **debts_bv** e **protests_bv**: dívidas e protestos apurados via Boa Vista — campo "
    #         "novo, com cobertura ainda baixa em consultas antigas.\n"
    #         "- **protests**: protestos registrados.\n\n"
    #         "O gráfico mostra a situação no **período de análise** (filtro 1): quantos contratos "
    #         "têm valor em aberto em cada métrica, olhando só para o histórico acumulado até o fim "
    #         "desse período. A tabela abaixo compara com o **período de referência** (filtro 2): "
    #         "quantos pioraram, melhoraram ou mantiveram desde então."
    #     )

    # dist_divida = resumo_distribuicao_metricas(snap1, METRICAS_DIVIDA_ATRASO)
    # st.plotly_chart(
    #     build_status_bar_chart(
    #         dist_divida, "Situação atual de dívidas/atrasos externos (filtro 1)", DIST_STATUS_ORDER,
    #         status_colors=DIST_STATUS_COLORS,
    #     ),
    #     width="stretch",
    # )
    # with st.expander("Ver comparação com o período de referência (filtro 2)", expanded=False):
    #     comparacao_divida = resumo_comparacao_multiplas_metricas(
    #         snap1, snap2, METRICAS_DIVIDA_ATRASO, maior_e_pior=True,
    #     )
    #     pivot_divida = comparacao_divida.pivot(index="metrica", columns="status", values="n_contratos")
    #     st.dataframe(pivot_divida.reindex(columns=STATUS_ORDER_COMPARACAO_RISCO), width="stretch")

    # --- 2) Migração de rating  +  3) Exposição de crédito (lado a lado) -------
    st.divider()
    n_melhorou1 = int((base_filtro1["status_rating"] == "Melhorou").sum())
    n_piorou1 = int((base_filtro1["status_rating"] == "Piorou").sum())
    n_estavel1 = int((base_filtro1["status_rating"] == "Estável").sum())
    n_melhorou2 = int((base_filtro2["status_rating"] == "Melhorou").sum())
    n_piorou2 = int((base_filtro2["status_rating"] == "Piorou").sum())
    n_estavel2 = int((base_filtro2["status_rating"] == "Estável").sum())

    n_aumentou1 = int((base_filtro1["status_credit_portfolio"] == "Aumentou").sum())
    n_diminuiu1 = int((base_filtro1["status_credit_portfolio"] == "Diminuiu").sum())
    n_estavel_cp1 = int((base_filtro1["status_credit_portfolio"] == "Estável").sum())
    n_aumentou2 = int((base_filtro2["status_credit_portfolio"] == "Aumentou").sum())
    n_diminuiu2 = int((base_filtro2["status_credit_portfolio"] == "Diminuiu").sum())
    n_estavel_cp2 = int((base_filtro2["status_credit_portfolio"] == "Estável").sum())

    col_rating, col_exposicao = st.columns(2)

    with col_rating:
        st.subheader(
            "⭐ Migração de rating",
            help="Compara o rating da consulta mais recente com o da consulta imediatamente "
            "anterior, para cada contrato do período de análise (filtro 1). O mapa de calor mostra a "
            "matriz completa de transição: de qual rating (linha) para qual rating (coluna).",
        )
        st.caption(f"Ordem (melhor → pior): {' → '.join(RATING_ORDER)}.")

        cr1, cr2, cr3 = st.columns(3)
        cr1.metric(
            "Melhoraram", _fmt_int(n_melhorou1), _fmt_variacao_pct(n_melhorou1, n_melhorou2), delta_color="off",
            help="Contratos cujo rating da consulta mais recente é melhor que o da consulta anterior.",
        )
        cr1.caption(f"Ref.: {_fmt_int(n_melhorou2)}")
        cr2.metric(
            "Pioraram", _fmt_int(n_piorou1), _fmt_variacao_pct(n_piorou1, n_piorou2), delta_color="off",
            help="Contratos cujo rating da consulta mais recente é pior que o da consulta anterior.",
        )
        cr2.caption(f"Ref.: {_fmt_int(n_piorou2)}")
        cr3.metric(
            "Mantiveram", _fmt_int(n_estavel1), _fmt_variacao_pct(n_estavel1, n_estavel2), delta_color="off",
            help="Contratos cujo rating não mudou entre as duas últimas consultas.",
        )
        cr3.caption(f"Ref.: {_fmt_int(n_estavel2)}")

        tab_transicao = transicao_rating(base_filtro1)
        st.plotly_chart(build_rating_transition_heatmap(tab_transicao), width="stretch")

    with col_exposicao:
        st.subheader(
            "📈 Exposição de crédito no mercado",
            help="Compara o campo credit_portfolio (total de crédito do cliente no mercado, não só "
            "com a Nagro) entre a consulta mais recente e a anterior — sinal de contexto sobre o "
            "endividamento geral, não necessariamente 'bom' ou 'ruim'. Variações menores que 1% são "
            "tratadas como estáveis.",
        )
        st.caption(
            "`credit_portfolio`: total de crédito do cliente no mercado (não só com a Nagro) — "
            "sinal de contexto, não \"bom\"/\"ruim\" isolado."
        )

        ce1, ce2, ce3 = st.columns(3)
        ce1.metric(
            "Aumentaram", _fmt_int(n_aumentou1), _fmt_variacao_pct(n_aumentou1, n_aumentou2), delta_color="off",
            help="Contratos cujo credit_portfolio subiu (mais de 1%) desde a consulta anterior.",
        )
        ce1.caption(f"Ref.: {_fmt_int(n_aumentou2)}")
        ce2.metric(
            "Diminuíram", _fmt_int(n_diminuiu1), _fmt_variacao_pct(n_diminuiu1, n_diminuiu2), delta_color="off",
            help="Contratos cujo credit_portfolio caiu (mais de 1%) desde a consulta anterior.",
        )
        ce2.caption(f"Ref.: {_fmt_int(n_diminuiu2)}")
        ce3.metric(
            "Mantiveram", _fmt_int(n_estavel_cp1), _fmt_variacao_pct(n_estavel_cp1, n_estavel_cp2), delta_color="off",
            help="Contratos cuja variação de credit_portfolio ficou dentro de ±1% desde a consulta anterior.",
        )
        ce3.caption(f"Ref.: {_fmt_int(n_estavel_cp2)}")

        resumo_cp = resumo_status_metricas(base_filtro1, ["credit_portfolio"], STATUS_ORDER_NEUTRO)
        st.plotly_chart(
            build_status_bar_chart(
                resumo_cp, "Exposição — variação (filtro 1)", STATUS_ORDER_NEUTRO,
                status_colors=STATUS_COLORS_NEUTRO,
            ),
            width="stretch",
        )

    st.caption(
        "Em ambos os tópicos, cada indicador conta os contratos do período de análise (filtro 1) "
        "desde a consulta imediatamente anterior; o percentual e a referência comparam essa mesma "
        "contagem com o período de referência (filtro 2)."
    )

    # --- 4) Watchlist — só contratos monitorados no período de análise ---------
    st.divider()
    st.subheader(
        "🚨 Contratos em atenção — priorização para acompanhamento",
        help="Critério de entrada: contrato monitorado no filtro 1, com histórico comparável (2+ "
        "consultas) e pelo menos 1 dos 6 indicadores de risco piorando desde a última consulta. "
        "Ordenação: primeiro por nº de indicadores piorando (maior severidade primeiro), em caso de "
        "empate pelo maior valor originado.",
    )
    st.caption(
        f"Somente contratos monitorados no período de análise (filtro 1: "
        f"{inicio1.strftime('%d/%m/%Y')} a {fim1.strftime('%d/%m/%Y')}), com histórico comparável e "
        "pelo menos N indicadores de risco piorando desde a última consulta (rating, overdue, loss, "
        "debts_bv, protests_bv, protests), ordenados por severidade e depois por valor originado — "
        "a lista de prioridade para acompanhamento comercial/cobrança. A comparação de cada "
        "contrato continua sendo sempre a consulta mais recente contra a imediatamente anterior."
    )
    min_indicadores = 1 # st.slider(
    #     "Mostrar contratos com pelo menos quantos indicadores piorando?",
    #     min_value=1, max_value=6, value=1, key="moncli_min_indicadores",
    # )
    watchlist = construir_watchlist(base_filtro1, min_indicadores=min_indicadores)
    st.metric(
        "Contratos na lista de atenção", _fmt_int(len(watchlist)),
        help="Contagem de contratos que entraram na watchlist pelo critério acima.",
    )

    if watchlist.empty:
        st.success("Nenhum contrato no critério selecionado.")
    else:
        tabela = watchlist.assign(
            em_default_fmt=lambda d: d["em_default_atual"].map({True: "Sim", False: "Não"}).fillna("-"),
        )[[
            "nome_cliente_atual", "operationCode_raiz", "produto_atual", "valor_originado_atual",
            "em_default_fmt", "n_indicadores_piorando", "indicadores_piorando",
            "rating_anterior", "rating_atual", "overdue_anterior", "overdue_atual",
            "credit_portfolio_anterior", "credit_portfolio_atual", "createdAt_atual",
        ]].rename(columns={
            "nome_cliente_atual": "Cliente",
            "operationCode_raiz": "Contrato",
            "produto_atual": "Produto",
            "valor_originado_atual": "Valor originado",
            "em_default_fmt": "Já em default (interno)",
            "n_indicadores_piorando": "Nº indicadores piorando",
            "indicadores_piorando": "Quais pioraram",
            "rating_anterior": "Rating anterior",
            "rating_atual": "Rating atual",
            "overdue_anterior": "Atraso anterior (R$)",
            "overdue_atual": "Atraso atual (R$)",
            "credit_portfolio_anterior": "Exposição anterior (R$)",
            "credit_portfolio_atual": "Exposição atual (R$)",
            "createdAt_atual": "Última consulta",
        })

        st.dataframe(
            tabela.style
            .map(_cor_severidade, subset=["Nº indicadores piorando"])
            .format({
                "Valor originado": "{:,.2f}",
                "Atraso anterior (R$)": "{:,.2f}",
                "Atraso atual (R$)": "{:,.2f}",
                "Exposição anterior (R$)": "{:,.2f}",
                "Exposição atual (R$)": "{:,.2f}",
                "Última consulta": lambda d: d.strftime("%d/%m/%Y") if pd.notna(d) else "-",
            }),
            hide_index=True, width="stretch", height=420,
        )

        st.download_button(
            "⬇️ Baixar lista de atenção (CSV)",
            data=tabela.to_csv(index=False).encode("utf-8-sig"),
            file_name="monitoramento_clientes_atencao.csv",
            mime="text/csv",
            key="moncli_download_watchlist",
        )

    # --- 5) Consulta individual — trajetória do cliente --------------------------
    st.divider()
    st.subheader(
        "🔍 Consulta individual — trajetória do cliente",
        help="Escolha um contrato para ver a evolução de rating/score e das métricas de dívida/"
        "atraso/exposição ao longo de todas as consultas registradas (raiz + renegociações).",
    )
    st.caption(
        f"Trajetória exibida até o fim do período de análise (filtro 1: {fim1.strftime('%d/%m/%Y')}) — "
        "consultas feitas depois dessa data não aparecem aqui."
    )

    opcoes = base.sort_values("valor_originado_atual", ascending=False)
    codigos_opcoes = opcoes["operationCode_raiz"].tolist()
    rotulo_por_codigo = dict(zip(
        opcoes["operationCode_raiz"], opcoes["nome_cliente_atual"] + " — " + opcoes["operationCode_raiz"],
    ))

    default_idx = 0
    if not watchlist.empty:
        top_codigo = watchlist.iloc[0]["operationCode_raiz"]
        if top_codigo in codigos_opcoes:
            default_idx = codigos_opcoes.index(top_codigo)

    operation_code_escolhido = st.selectbox(
        "Cliente / contrato", options=codigos_opcoes, index=default_idx if codigos_opcoes else 0,
        format_func=lambda oc: rotulo_por_codigo.get(oc, oc),
        key="moncli_select_cliente",
    )

    if operation_code_escolhido:
        historico_completo = historico_contrato(df_bruto, operation_code_escolhido)
        historico = historico_completo[historico_completo["createdAt"].dt.date <= fim1]

        if historico.empty:
            st.info(
                "Este contrato não tem consultas registradas até o fim do período de análise "
                "(filtro 1) selecionado."
            )
        else:
            historico = historico.sort_values("createdAt")
            r = historico.iloc[-1]
            tem_anterior = len(historico) >= 2
            status_rating_atual = (
                classificar_rating(r["rating"], historico.iloc[-2]["rating"]) if tem_anterior else None
            )

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Cliente", r["nome_cliente"] or "-")
            c2.metric(
                "Rating", r["rating"] or "-", status_rating_atual, delta_color="off",
                help="Rating na consulta mais recente até o fim do período de análise. O rótulo "
                "abaixo do valor mostra se melhorou/piorou/manteve contra a consulta anterior.",
            )
            c3.metric("Score", _fmt_int(r["score"]), help="Score numérico na consulta mais recente.")
            c4.metric("Valor originado", _brl(r["valor_originado"]), help="Valor de principal originado neste contrato.")

            st.plotly_chart(
                build_trajetoria_chart(historico, f"Trajetória — {operation_code_escolhido}"),
                width="stretch",
            )

            with st.expander(
                "Ver histórico completo de consultas (até o fim do período de análise)", expanded=False,
            ):
                st.caption(
                    "Inclui consultas feitas tanto na raiz do contrato quanto em eventuais "
                    "renegociações — coluna \"Geração\" mostra o código exato de cada consulta."
                )
                cols_hist = [
                    "createdAt", "operationCode", "rating", "score", "overdue", "loss", "credit_portfolio",
                    "debts_bv", "protests_bv", "protests", "max_delay_paid_installments", "death",
                ]
                st.dataframe(
                    historico[cols_hist].rename(columns={"operationCode": "Geração (operationCode)"}),
                    hide_index=True, width="stretch",
                )

    st.divider()
    st.caption(
        f"Atualizado em {pd.Timestamp.now().strftime('%d/%m/%Y %H:%M')}  |  "
        f"{total:,} contratos monitorados no total ({com_historico:,} com histórico comparável, "
        f"{sem_historico:,} aguardando 2ª consulta)."
    )


def render_monitoramento_clientes():
    """Roda em `st.fragment`: mexer em qualquer filtro (cabeçalho, períodos
    de comparação, seleção de cliente) só reprocessa esta aba, sem esmaecer
    o app inteiro."""
    _render_monitoramento_clientes_body()
