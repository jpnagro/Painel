import pandas as pd
import streamlit as st

from crud.analise_risco.charts import (
    build_barra_npl_por_categoria,
    build_bolha_risco_exposicao,
    build_heatmap_cruzado,
    build_ranking_dispersao,
)
from crud.analise_risco.data import VARIAVEIS, filtrar_por_categoria, filtrar_por_periodo, preparar_variaveis
from crud.analise_risco.indicators import (
    inadimplencia_cruzada,
    inadimplencia_por_variavel,
    montar_mascara_exclusao,
    ranking_dispersao,
)
from crud.carteira.data import SEM_CLIENT_DATA
from core.ui import colunas_compactas
from crud.painel_executivo.charts import build_risco_bar_chart
from crud.painel_executivo.data import CARTEIRAS, filtrar_executivo
from crud.painel_executivo.indicators import (
    calcular_indicadores_financeiros,
    calcular_indicadores_risco_inadimplencia,
    calcular_visao_geral_negocio,
)
from crud.painel_executivo.view import _brl, _pct, load_dados_executivo_brutos  # reusa cache/consulta/formatação


@st.cache_data(ttl=3600, show_spinner=False)
def load_base_risco(carteira, produtos, subfiltro_ccb, subfiltro_cpr):
    """Aplica os filtros de carteira/produto/subfiltro sobre a base bruta
    já em cache (`load_dados_executivo_brutos`) -- não repete consulta ao
    banco, só recorta em memória."""
    df_bruto = preparar_variaveis(load_dados_executivo_brutos())
    partes = [filtrar_executivo(df_bruto, produto=p, carteira=carteira) for p in produtos]
    df = pd.concat(partes, ignore_index=True) if partes else df_bruto.iloc[0:0]
    return filtrar_por_categoria(df, subfiltro_ccb=subfiltro_ccb, subfiltro_cpr=subfiltro_cpr)


@st.fragment
def _render_analise_risco_body():
    st.title("🔬 Análise de Risco por Variável")
    st.caption(
        "Quebra a inadimplência por perfil de cliente/operação e simula o impacto de excluir um perfil da carteira."
    )

    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        refresh = st.button("🔄 Recarregar dados", key="risco_refresh")
    if refresh:
        load_dados_executivo_brutos.clear()
        load_base_risco.clear()

    df_bruto = preparar_variaveis(load_dados_executivo_brutos())

    # Filtros dentro de um `st.form`: as mudanças só são aplicadas (e a aba
    # só recalcula/re-renderiza a partir daqui) quando "🔍 Filtrar" é
    # clicado -- evita recarregar tudo a cada seleção individual. Os
    # limites de data usam a base bruta (não filtrada) pra não depender
    # do resultado do próprio formulário antes dele ser enviado.
    with st.form("risco_filtros_form"):
        # --- Linha 1: Carteira -----------------------------------------------
        carteira_selecionada = st.radio(
            "Carteira", options=CARTEIRAS, index=0, horizontal=True, key="risco_filtro_carteira",
            help="'Carteira em aberto': exclui quitados e write-off (atraso ≥360 dias). 'WriteOff': "
            "só os contratos em write-off. 'Carteira total': todos os contratos-raiz, sem excluir "
            "nada.",
        )

        # --- Linha 2: Produto + subfiltros, tudo compacto --------------------
        produtos_atual = st.session_state.get("risco_filtro_produto", ["CCB", "CPR"])
        col_produto, col_ccb, col_cpr = colunas_compactas(
            [True, "CCB" in produtos_atual, "CPR" in produtos_atual]
        )
        with col_produto:
            produtos_selecionados = st.multiselect(
                "Produto", options=["CCB", "CPR"], default=["CCB", "CPR"], key="risco_filtro_produto",
            )

        subfiltro_ccb = None
        if col_ccb is not None:
            with col_ccb:
                tipos_ccb = ["App", "Crédito Produtor"]
                tem_sem_client_data = df_bruto.loc[df_bruto["produto"] == "CCB", "categoria"].isna().any()
                if tem_sem_client_data:
                    tipos_ccb.append(SEM_CLIENT_DATA)
                subfiltro_ccb = st.multiselect(
                    "Tipo de operação (CCB)", options=tipos_ccb, default=tipos_ccb, key="risco_subfiltro_ccb",
                )

        subfiltro_cpr = None
        if col_cpr is not None:
            with col_cpr:
                tipos_cpr = sorted(df_bruto.loc[df_bruto["produto"] == "CPR", "categoria"].dropna().unique().tolist())
                subfiltro_cpr = st.multiselect(
                    "Tipo de produto (CPR)", options=tipos_cpr, default=tipos_cpr, key="risco_subfiltro_cpr",
                )

        # --- Linha 2b: Mínimo de contratos por categoria (bem compacto) -----
        col_min, _col_min_spacer = st.columns([1, 9])
        with col_min:
            min_contratos = st.number_input(
                "Mínimo de contratos por categoria", min_value=1, value=1, step=1, key="risco_min_contratos",
                help="Categorias com menos contratos que isso são descartadas das análises "
                "abaixo — evita destacar uma categoria de 1-2 contratos como '100% inadimplente'.",
            )

        # --- Linha 3: Período (só as datas, sem o radio) --------------------
        min_data_geral = df_bruto["releaseDate"].min()
        max_data_geral = df_bruto["releaseDate"].max()
        col_ini, col_fim, _col_periodo_spacer = st.columns([1, 1, 8])
        with col_ini:
            data_inicio = st.date_input(
                "Início", value=min_data_geral.date(), min_value=min_data_geral.date(),
                max_value=max_data_geral.date(), key="risco_data_inicio",
            )
        with col_fim:
            data_fim = st.date_input(
                "Fim", value=max_data_geral.date(), min_value=min_data_geral.date(),
                max_value=max_data_geral.date(), key="risco_data_fim",
            )

        st.form_submit_button("🔍 Filtrar", type="primary")

    df = load_base_risco(
        carteira_selecionada,
        tuple(sorted(produtos_selecionados)),
        tuple(sorted(subfiltro_ccb)) if subfiltro_ccb is not None else None,
        tuple(sorted(subfiltro_cpr)) if subfiltro_cpr is not None else None,
    )

    if not len(df):
        st.warning("Nenhum contrato nesse recorte de filtros.")
        st.stop()

    df = filtrar_por_periodo(df, data_inicio=data_inicio, data_fim=data_fim)
    if not len(df):
        st.warning("Nenhum contrato originado nesse período.")
        st.stop()

    st.caption(f"{len(df):,} contratos no recorte.")

    sub_tab_variaveis, sub_tab_simulador = st.tabs(["📊 Análise de variáveis", "🧪 Simulador"])

    st.divider()

    with sub_tab_variaveis:
        _render_analise_variaveis(df, min_contratos)

    with sub_tab_simulador:
        _render_simulador(df)


def render_analise_risco():
    """Roda em `st.fragment`: mexer em qualquer filtro (cabeçalho, mínimo
    de contratos, variáveis do cruzamento, simulador etc.) só reprocessa
    esta aba, sem esmaecer o app inteiro."""
    _render_analise_risco_body()


def _render_analise_variaveis(df, min_contratos):
    # --- Ranking de poder discriminante -------------------------------------
    st.subheader(
        "Poder discriminante por variável",
        help="Dispersão de uma variável = (maior % de Inadimplência 90+ entre suas categorias) − "
        "(menor % de Inadimplência 90+ entre suas categorias). Importante: aqui usamos 'Inadimplência' "
        "(não 'NPL') porque o cálculo é sobre o saldo TOTAL da carteira — saldo em aberto de "
        "contratos com atraso ≥90 dias ÷ saldo total contratado do grupo (soma de todas as parcelas, "
        "pagas e em aberto). É diferente do NPL calculado na aba 'Análise da Carteira', que divide "
        "pelo saldo devedor (só o que ainda falta pagar). Categorias com menos contratos que o "
        "'Mínimo de contratos por categoria' são descartadas antes do cálculo.",
    )
    disp = ranking_dispersao(df, VARIAVEIS, min_contratos=min_contratos)
    col_disp_grafico, col_disp_tabela = st.columns(2)
    with col_disp_grafico:
        st.plotly_chart(build_ranking_dispersao(disp), width="stretch")
    with col_disp_tabela:
        st.dataframe(disp, width="stretch", height=max(320, 42 * len(disp)))
    st.caption(
        "Dispersão = diferença entre a categoria com maior e a com menor % Inadimplência 90+ "
        "(sobre o saldo total da carteira, não o saldo devedor) dentro de cada variável. Quanto "
        "maior, mais essa variável ajuda a separar bons e maus pagadores nesse recorte — boa "
        "candidata pra política de crédito (ex.: restringir/precificar diferente a pior categoria)."
    )

    # --- Exploração por variável ---------------------------------------------
    st.divider()
    st.subheader(
        "Inadimplência por variável",
        help="Escolha uma variável (ex.: UF) para ver, por categoria: % de Inadimplência 90+ "
        "(fórmula canônica — saldo em aberto de contratos com atraso ≥90d ÷ SALDO TOTAL contratado "
        "do grupo, pago + em aberto; diferente do NPL da 'Análise da Carteira', que usa só o saldo "
        "devedor), nº de contratos, volume concedido e saldo devedor. Gráfico de barras: ranking por "
        "% de Inadimplência, do maior para o menor risco. Gráfico de bolhas: eixo X = % de "
        "Inadimplência, eixo Y = saldo devedor (exposição em R$), tamanho da bolha = nº de contratos; "
        "as linhas tracejadas marcam a média ponderada de inadimplência e a mediana de saldo.",
    )
    col_var, _col_periodo_spacer = st.columns([1, 9])
    with col_var:
        variavel_selecionada = st.selectbox("Variável", options=list(VARIAVEIS.keys()), key="risco_variavel")
    coluna = VARIAVEIS[variavel_selecionada]
    tabela = inadimplencia_por_variavel(df, coluna, min_contratos=min_contratos)

    if not len(tabela):
        st.info("Nenhuma categoria com contratos suficientes pra esse filtro.")
    else:
        col_a, col_b = st.columns(2)
        with col_a:
            st.plotly_chart(
                build_barra_npl_por_categoria(tabela, coluna, f"Inadimplência 90+ por {variavel_selecionada}"),
                width="stretch",
            )
        with col_b:
            st.plotly_chart(
                build_bolha_risco_exposicao(tabela, coluna, f"Risco x Exposição — {variavel_selecionada}"),
                width="stretch",
            )
        st.caption(
            "No gráfico de bolhas, o quadrante superior direito (Inadimplência alta e saldo "
            "devedor alto) concentra as categorias mais urgentes: são as que já "
            "carregam mais risco absoluto na carteira hoje, não só percentual."
        )
        with st.expander("Ver tabela"):
            st.dataframe(tabela, width="stretch")

    # --- Cruzamento de duas variáveis ---------------------------------------
    st.divider()
    st.subheader(
        "Cruzamento de duas variáveis",
        help="% de Inadimplência 90+ (fórmula canônica: saldo em aberto de contratos com atraso ≥90d "
        "÷ SALDO TOTAL contratado da combinação, pago + em aberto — não é o NPL sobre saldo devedor "
        "usado na 'Análise da Carteira') de cada combinação das duas variáveis escolhidas, num mapa "
        "de calor com escala fixa (verde <25%, amarelo a partir de 25%, laranja a partir de 50%, "
        "vermelho em 100%). Passe o mouse num quadrado para ver o nº de contratos daquela combinação. "
        "Atenção: o 'Mínimo de contratos por categoria' aqui é aplicado por CÉLULA (cada combinação "
        "das duas variáveis), não pela variável inteira — uma célula pode sumir do mapa mesmo que a "
        "categoria tenha bastante contrato somada em outras combinações.",
    )
    col_c, col_d, _col_var = st.columns([1,1,8])
    with col_c:
        var1 = st.selectbox("Variável 1", options=list(VARIAVEIS.keys()), index=0, key="risco_var1")
    with col_d:
        opcoes_var2 = [v for v in VARIAVEIS if v != var1]
        idx_padrao = min(1, len(opcoes_var2) - 1) if opcoes_var2 else 0
        var2 = st.selectbox("Variável 2", options=opcoes_var2, index=idx_padrao, key="risco_var2")

    cruzada = inadimplencia_cruzada(df, VARIAVEIS[var1], VARIAVEIS[var2], min_contratos=min_contratos)
    if not len(cruzada):
        st.info("Nenhuma combinação com contratos suficientes pra esse filtro.")
    else:
        st.plotly_chart(
            build_heatmap_cruzado(cruzada, VARIAVEIS[var1], VARIAVEIS[var2], f"Inadimplência 90+: {var1} x {var2}"),
            width="stretch",
        )
        with st.expander("Ver tabela"):
            st.dataframe(cruzada.sort_values("pct_npl", ascending=False), width="stretch")


def _kpi_comparativo(col, titulo, valor_atual, valor_simulado, formatter, delta_color="off", help=None):
    with col:
        st.metric(
            titulo, formatter(valor_simulado),
            delta=formatter(valor_simulado - valor_atual) if isinstance(valor_simulado, (int, float)) else None,
            delta_color=delta_color,
            help=help,
        )
        st.caption(f"Hoje: {formatter(valor_atual)}")


def _render_simulador(df):
    st.subheader(
        "Simulador de exclusão de perfil",
        help="Simula retirar um perfil (ex.: UF=RN) da carteira já filtrada acima, e recalcula os "
        "mesmos KPIs do Painel Executivo três vezes: 'Atual' (com o perfil), 'Simulada' (sem o "
        "perfil) e 'Segmento' (só o perfil excluído) — para comparar quanto a inadimplência cairia "
        "e quanto se abriria mão de volume/margem.",
    )
    st.caption(
        "Escolha um ou dois critérios (ex.: UF = RN e Setor = bovino corte) pra simular "
        "a retirada desse perfil da carteira. Os indicadores abaixo comparam a carteira "
        "atual (com o perfil) contra a carteira simulada (sem o perfil), pras mesmas "
        "fórmulas do Painel Executivo — assim dá pra ver se vale a pena cortar esse "
        "segmento: quanto cai a inadimplência e quanto se abre mão de volume/margem."
    )

    col_v1, col_v2, col_logica = st.columns([1, 1, 0.6])
    with col_v1:
        var1_label = st.selectbox("Critério 1: variável", options=list(VARIAVEIS.keys()), key="sim_var1")
        coluna1 = VARIAVEIS[var1_label]
        opcoes1 = sorted(df[coluna1].dropna().astype(str).unique().tolist())
        valores1 = st.multiselect(f"Valores de {var1_label} a excluir", options=opcoes1, key="sim_valores1")

    usar_segundo = st.checkbox("Adicionar um segundo critério", key="sim_usar_segundo")
    coluna2, valores2, logica = None, [], "E"
    if usar_segundo:
        with col_v2:
            opcoes_var2 = [v for v in VARIAVEIS if v != var1_label]
            var2_label = st.selectbox("Critério 2: variável", options=opcoes_var2, key="sim_var2")
            coluna2 = VARIAVEIS[var2_label]
            opcoes2 = sorted(df[coluna2].dropna().astype(str).unique().tolist())
            valores2 = st.multiselect(f"Valores de {var2_label} a excluir", options=opcoes2, key="sim_valores2")
        with col_logica:
            logica = st.radio(
                "Combinar", options=["E", "OU"], key="sim_logica", horizontal=True,
                help="'E' exclui só quem bate as duas condições ao mesmo tempo (ex.: "
                "UF=RN E Setor=bovino corte). 'OU' exclui quem bate qualquer uma das duas.",
            )

    regras = [(coluna1, valores1)]
    if usar_segundo and coluna2:
        regras.append((coluna2, valores2))

    mask_excluir = montar_mascara_exclusao(df, regras, logica=logica)
    if not mask_excluir.any():
        st.info("Selecione ao menos um valor pra simular a exclusão.")
        return

    segmento = df[mask_excluir]
    simulada = df[~mask_excluir]
    pct_contratos = 100 * len(segmento) / len(df)

    st.divider()
    st.markdown(
        f"**Segmento selecionado: {len(segmento):,} contratos ({pct_contratos:.1f}% da carteira filtrada)**",
        help="Contratos que batem no(s) critério(s) escolhido(s) acima (combinados com 'E' ou 'OU'). "
        "% da carteira filtrada = nº de contratos do segmento ÷ nº de contratos da carteira já "
        "filtrada pelo formulário do topo da aba.",
    )

    vg_atual = calcular_visao_geral_negocio(df, "Atual")
    vg_sim = calcular_visao_geral_negocio(simulada, "Simulada")
    risco_atual = calcular_indicadores_risco_inadimplencia(df, "Atual")
    risco_sim = calcular_indicadores_risco_inadimplencia(simulada, "Simulada")
    fin_atual = calcular_indicadores_financeiros(df, "Atual")
    fin_sim = calcular_indicadores_financeiros(simulada, "Simulada")
    vg_seg = calcular_visao_geral_negocio(segmento, "Segmento")
    risco_seg = calcular_indicadores_risco_inadimplencia(segmento, "Segmento")

    st.markdown(
        "##### Carteira simulada (sem o segmento) vs. carteira atual",
        help="'Hoje' (legenda abaixo do valor) = KPI calculado com a carteira Atual (com o segmento); "
        "o valor em destaque e o delta mostram o KPI da carteira Simulada (sem o segmento) e a "
        "diferença contra o Atual.",
    )
    c1, c2, c3, c4 = st.columns(4)
    _kpi_comparativo(
        c1, "Total Concedido",
        vg_atual.loc["Valor Total Emprestado (R$)"].iloc[0], vg_sim.loc["Valor Total Emprestado (R$)"].iloc[0],
        _brl,
        help="Soma do valor de principal dos contratos originais — renegociação não conta como "
        "dinheiro novo.",
    )
    _kpi_comparativo(
        c2, "Contratos Ativos",
        vg_atual.loc["Contratos Ativos"].iloc[0], vg_sim.loc["Contratos Ativos"].iloc[0],
        lambda v: f"{int(v):,}",
        help="Contagem de contratos-raiz ainda não quitados.",
    )
    _kpi_comparativo(
        c3, "Ticket Médio",
        vg_atual.loc["Ticket Médio (R$)"].iloc[0], vg_sim.loc["Ticket Médio (R$)"].iloc[0],
        _brl,
        help="Média simples do valor de principal por contrato.",
    )
    _kpi_comparativo(
        c4, "Taxa Juros Média",
        vg_atual.loc["Taxa de Juros Média (%)"].iloc[0], vg_sim.loc["Taxa de Juros Média (%)"].iloc[0],
        _pct,
        help="Taxa de juros mensal contratada, ponderada pelo valor de principal de cada contrato.",
    )

    c5, c6, c7, c8 = st.columns(4)
    _kpi_comparativo(
        c5, "FPD (90d)",
        risco_atual.loc["FPD (90d)", "% da Carteira Atual"], risco_sim.loc["FPD (90d)", "% da Carteira Simulada"],
        _pct, delta_color="inverse",
        help="Fórmula canônica de '% da Carteira' aplicada ao corte de 1ª parcela em atraso: saldo em "
        "aberto desses contratos ÷ SALDO TOTAL contratado do grupo (pago + em aberto) — é "
        "'inadimplência', não 'NPL': o denominador é o total da carteira, não o saldo devedor.",
    )
    _kpi_comparativo(
        c6, "Inadimplência 90d",
        risco_atual.loc["90+ dias", "% da Carteira Atual"], risco_sim.loc["90+ dias", "% da Carteira Simulada"],
        _pct, delta_color="inverse",
        help="Fórmula canônica de '% da Carteira': saldo em aberto de contratos com atraso ≥90 dias "
        "÷ SALDO TOTAL contratado do grupo (pago + em aberto, Atual ou Simulada). Diferente do NPL "
        "calculado em 'Análise da Carteira', que usa o saldo devedor como denominador.",
    )
    _kpi_comparativo(
        c7, "Cobertura PDD",
        fin_atual.loc["PDD"].iloc[0], fin_sim.loc["PDD"].iloc[0],
        _brl, delta_color="inverse",
        help="Provisão para Devedores Duvidosos = 50% do saldo de principal em aberto dos contratos "
        "com atraso ≥90 dias.",
    )
    _kpi_comparativo(
        c8, "Margem Financeira Estimada",
        fin_atual.loc["Margem Financeira Bruta (Estimada)"].iloc[0],
        fin_sim.loc["Margem Financeira Bruta (Estimada)"].iloc[0],
        _brl, delta_color="normal",
        help="Juros efetivamente pagos menos a provisão (PDD).",
    )

    st.plotly_chart(
        build_risco_bar_chart({"Atual": risco_atual, "Simulada": risco_sim}), width="stretch",
    )

    st.markdown(
        "##### O que tem no segmento excluído",
        help="Indicadores calculados só dentro do segmento (os contratos que seriam retirados), sem "
        "comparar com o resto da carteira.",
    )
    s1, s2, s3 = st.columns(3)
    s1.metric("Contratos no segmento", f"{len(segmento):,}", help=f"{pct_contratos:.1f}% da carteira filtrada")
    s2.metric(
        "Volume concedido no segmento", _brl(vg_seg.loc["Valor Total Emprestado (R$)"].iloc[0]),
        help="Soma do valor de principal dos contratos do segmento.",
    )
    s3.metric(
        "Inadimplência 90d do segmento", _pct(risco_seg.loc["90+ dias", "% da Carteira Segmento"]),
        help="Fórmula canônica de '% da Carteira' (saldo em aberto ÷ saldo TOTAL contratado, pago + "
        "em aberto) calculada só dentro do segmento excluído.",
    )

    with st.expander("Ver tabela comparativa completa"):
        st.markdown(
            "**Composição**",
            help="Mesmos indicadores de composição do Painel Executivo (Tópico 2), lado a lado para "
            "Atual, Simulada e Segmento.",
        )
        st.dataframe(pd.concat([vg_atual, vg_sim, vg_seg], axis=1).style.format("{:,.2f}"), width="stretch")
        st.markdown(
            "**Risco**",
            help="Saldo em atraso (R$) e % da carteira (fórmula canônica: saldo em aberto ÷ saldo "
            "TOTAL contratado — 'inadimplência', não NPL sobre saldo devedor) em cada faixa de "
            "atraso, para Atual, Simulada e Segmento.",
        )
        st.dataframe(pd.concat([risco_atual, risco_sim, risco_seg], axis=1).style.format("{:,.2f}"), width="stretch")
        st.markdown(
            "**Financeiro**",
            help="Juros, saldo devedor, PDD e margem financeira estimada — mesmas fórmulas do Painel "
            "Executivo (Tópico 3) — para Atual e Simulada.",
        )
        st.dataframe(pd.concat([fin_atual, fin_sim], axis=1).style.format("{:,.2f}"), width="stretch")
