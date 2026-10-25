from datetime import datetime
from importlib.util import find_spec

import pandas as pd
import streamlit as st

from crud.analise_risco.data import filtrar_por_periodo
from crud.painel_executivo.charts import (
    build_donut_chart,
    build_evolucao_npl90_chart,
    build_faixas_atraso_chart,
    build_risco_bar_chart,
)
from crud.painel_executivo.data import CARTEIRAS, WO
from crud.painel_executivo.indicators import (
    PDD_UNIDADE_CURTA,
    calcular_indicadores_executivo,
    carregar_dados_executivo_bruto,
    resumir_pdd,
)


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


def _formatar_indicador(indicador, v):
    """Formata uma célula da tabela "Distribuição por Produto" conforme a
    unidade indicada no nome do indicador: '(R$)', '(%)' ou contagem."""
    if pd.isna(v):
        return "-"
    if "(R$)" in indicador:
        return f"R$ {v:,.2f}"
    if "(%)" in indicador:
        return f"{v:.2f}%"
    return f"{int(v):,}"


def _negrito_ultima_linha(styler, tabela):
    return styler.set_properties(subset=pd.IndexSlice[tabela.index[-1:], :], **{"font-weight": "bold"})


def _negrito_totais(styler, tabela):
    """Negrito em todas as linhas de total ('Total', 'Total CCB', 'Total CPR')."""
    totais = [i for i in tabela.index if str(i).startswith("Total")]
    return styler.set_properties(subset=pd.IndexSlice[totais, :], **{"font-weight": "bold"})


def _selecao_atual(r):
    """Seleções atuais dos filtros do MEIO da aba (linha de crédito/tipo de NPL
    da evolução e fundo do PDD), lidas do `session_state` pelas mesmas chaves
    dos widgets -- assim o botão Download, que fica no topo, enxerga o que o
    usuário escolheu mais abaixo (com os mesmos padrões dos widgets)."""
    opcoes_linhas = ["Total"] + list(r["linhas"])
    fundos = r["fundos"]
    return {
        "linhas_evolucao": st.session_state.get("exec_evol_linhas_" + "_".join(opcoes_linhas), ["Total"]),
        "tipos_evolucao": st.session_state.get("exec_evol_tipos", ["NPL 90 s/ WO", "NPL 90 c/ WO"]),
        "fundos": st.session_state.get("exec_pdd_fundos_" + "_".join(fundos), fundos),
        "todos_fundos": fundos,
    }


def _botao_download(r, produtos, carteira, data_inicio, data_fim):
    """Botões de download do PDF, logo abaixo dos filtros.

    1) "📄 Download": gera o relatório sob demanda (só quando clicado, então
       filtros e gráficos não ficam mais lentos), com uma barra de progresso
       (% concluída) logo abaixo. O botão permanece na tela.
    2) "⬇️ Baixar PDF": aparece quando o relatório fica pronto e baixa o arquivo
       com um clique (o navegador só inicia download a partir de um clique do
       usuário). Some se algum filtro ou seleção mudar, pois o arquivo ficaria
       desatualizado."""
    col, _ = st.columns([2, 8])  # mesma largura do filtro "Produto"
    with col:
        if find_spec("reportlab") is None or find_spec("matplotlib") is None:
            st.button(
                "📄 Download", disabled=True, key="exec_download_indisponivel", width="stretch",
                help="Instale as dependências do PDF: pip install reportlab matplotlib",
            )
            return
        clicou = st.button(
            "📄 Download", key="exec_download_pdf_btn", width="stretch",
            help="Gera um relatório em PDF com os resultados atuais do painel (filtros, indicadores, "
            "gráficos e tabelas das seções 1 a 3), em formato para diretoria e investidores. Quando "
            "terminar, aparece o botão 'Baixar PDF'. Reflete também as seleções de linha de crédito, "
            "tipo de NPL e fundo feitas abaixo.",
        )
        area = st.empty()  # barra de progresso, do mesmo tamanho do botão

        selecao = _selecao_atual(r)
        assinatura = (
            tuple(produtos), carteira, str(data_inicio), str(data_fim), tuple(selecao["linhas_evolucao"]),
            tuple(selecao["tipos_evolucao"]), tuple(selecao["fundos"]),
        )
        if clicou:
            barra = area.progress(0.0, text="Preparando o relatório… 0%")

            def progresso(fracao, texto):
                fracao = min(max(float(fracao), 0.0), 1.0)
                barra.progress(fracao, text=f"{texto}… {int(fracao * 100)}%")

            try:
                from crud.painel_executivo.pdf_report import gerar_pdf_painel_executivo

                pdd = (
                    resumir_pdd(r["pdd_contratos"], tuple(produtos), selecao["fundos"])
                    if selecao["fundos"] else None
                )
                pdf = gerar_pdf_painel_executivo(
                    r, {"carteira": carteira, "data_inicio": data_inicio, "data_fim": data_fim},
                    selecao, pdd, progresso=progresso,
                )
            except Exception as exc:  # não derruba o painel por causa do relatório
                area.error(f"Não foi possível gerar o PDF: {exc}")
                st.session_state.pop("exec_pdf", None)
                return
            area.empty()
            st.session_state["exec_pdf"] = {
                "bytes": pdf, "assinatura": assinatura,
                "nome": f"painel_executivo_{datetime.now():%Y%m%d_%H%M}.pdf",
            }

        pronto = st.session_state.get("exec_pdf")
        if pronto and pronto["assinatura"] != assinatura:
            st.session_state.pop("exec_pdf", None)  # filtros mudaram: o arquivo ficou desatualizado
            pronto = None
        if pronto:
            st.download_button(
                "⬇️ Baixar PDF", data=pronto["bytes"], file_name=pronto["nome"], mime="application/pdf",
                key="exec_download_pdf_pronto", on_click="ignore", width="stretch", type="primary",
                help="Relatório gerado com os filtros atuais. Se mudar algum filtro, clique em "
                "'Download' de novo para gerar outro.",
            )


@st.fragment
def _separador_subtopico():
    """Divisão sutil entre subtópicos da seção 3: linha tracejada fina e clara
    (cinza translúcido, funciona nos temas claro e escuro) com respiro em cima
    e embaixo. As seções principais continuam com `st.divider()`."""
    st.markdown(
        "<hr style='margin: 2rem 0 1.25rem 0; border: none; "
        "border-top: 1px dashed rgba(128, 128, 128, 0.35);'>",
        unsafe_allow_html=True,
    )


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
        # mesma proporção das colunas de data abaixo ([1, 1, 8]): o multiselect
        # ocupa a largura de "Início" + "Fim" juntos
        col_produto, _col_produto_spacer = st.columns([2, 8])
        with col_produto:
            produtos_selecionados = st.multiselect(
                "Produto", options=["CCB", "CPR"], default=["CCB", "CPR"], key="exec_filtro_produto",
                help="Escolha CCB, CPR ou os dois juntos. Com um produto só, os indicadores são divididos "
                "por linha de crédito (App e Crédito Produtor no CCB; tipos de produto no CPR). Com CCB e "
                "CPR juntos, a divisão passa a ser por produto (CCB x CPR).",
            )
        carteira_selecionada = st.radio(
            "Carteira", options=CARTEIRAS, index=CARTEIRAS.index("Carteira total"), horizontal=True, key="exec_filtro_carteira",
            help="'Carteira em aberto': exclui contratos já quitados e os em write-off (atraso >360 "
            "dias). 'WriteOff': só os contratos em write-off. 'Carteira total': todos os contratos-"
            "raiz do produto, sem excluir nada. Este filtro NÃO afeta o NPL 90, o NPL 90 + WO nem "
            "a seção 3 (Indicadores de Risco) — esses indicadores precisam do write-off na base e "
            "sempre incluem a carteira completa do Produto escolhido.",
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

    if not produtos_selecionados:
        st.warning("Selecione ao menos um Produto (CCB e/ou CPR) e clique em Filtrar.")
        return
    produtos_selecionados = tuple(p for p in ("CCB", "CPR") if p in produtos_selecionados)
    produto_label = " + ".join(produtos_selecionados)
    varios_produtos = len(produtos_selecionados) > 1

    error_msg = None
    with st.spinner("Calculando indicadores executivos..."):
        try:
            r = load_indicadores_executivo(produtos_selecionados, carteira_selecionada, data_inicio, data_fim)
        except Exception as exc:
            error_msg = str(exc)
            r = None
            raise

    if error_msg:
        st.error(f"Erro ao carregar dados: {error_msg}")
        return

    _botao_download(r, produtos_selecionados, carteira_selecionada, data_inicio, data_fim)

    categorias = r["categorias"]
    vg = r["visao_geral"]
    kpis = r["kpis"]
    risco = r["risco"]
    npl = r["npl"]

    if not categorias:
        st.warning(
            f"Nenhuma categoria encontrada para {produto_label} neste recorte de "
            "carteira — os indicadores abaixo mostram só o Total."
        )

    # --- Tópico 1: Visão Geral da Carteira ----------------------------------
    st.divider()
    st.subheader(
        "1. Visão Geral da Carteira",
        help="10 KPIs principais do recorte atual (Produto/Carteira/Período selecionados no formulário "
        "acima). Cada card mostra o valor Total em destaque e o detalhamento logo abaixo: por linha de "
        "crédito (App x Crédito Produtor, ou tipos de CPR) quando há um produto só, ou por produto "
        "(CCB x CPR) quando os dois estão selecionados. Os 8 indicadores de volume obedecem ao filtro "
        "'Carteira'; NPL 90 e NPL 90 + WO sempre usam a carteira completa do Produto (incluem o "
        "write-off por definição).",
    )
    n_por_cat = ", ".join(f"{cat}: {r['n_por_categoria'][cat]}" for cat in categorias)
    st.caption(
        f"{r['n_total']} contratos no recorte ({r['n_ccb']} CCB / {r['n_cpr']} CPR)."
        + (f" Por categoria — {n_por_cat}." if categorias else "")
    )

    def _valor(indicador, cat="Total"):
        return kpis[cat].loc[indicador].iloc[0]

    def _partes(indicador, formatter=_brl):
        return [f"{cat}: {formatter(_valor(indicador, cat))}" for cat in categorias]

    def _inteiro(v):
        return f"{int(v):,}"

    c1, c2, c3, c4, c5 = st.columns(5)
    _kpi_card(
        c1, "Total Concedido", _brl(_valor("Total Concedido (R$)")), _partes("Total Concedido (R$)"),
        help="Soma do valor de principal (principalAmount) dos contratos originais do recorte — "
        "renegociação nunca conta como dinheiro novo concedido: só o contrato-raiz entra, uma vez.",
    )
    _kpi_card(
        c2, "Qtd Contratos Ativos", _inteiro(_valor("Contratos Ativos")),
        _partes("Contratos Ativos", _inteiro),
        help="Contagem de contratos-raiz do recorte que ainda não foram 100% quitados (têm ao menos "
        "uma parcela em aberto).",
    )
    _kpi_card(
        c3, "Qtd Contratos Total", _inteiro(_valor("Quantidade de Contratos (Total)")),
        _partes("Quantidade de Contratos (Total)", _inteiro),
        help="Nº de contratos-raiz do recorte, ativos e quitados (renegociações não contam à parte — "
        "ficam dentro do contrato-raiz).",
    )
    _kpi_card(
        c4, "Taxa Juros Média", _pct(_valor("Taxa de Juros Média (%)")),
        _partes("Taxa de Juros Média (%)", _pct),
        help="Taxa de juros mensal contratada (monthlyRate), ponderada pelo valor de principal de "
        "cada contrato (contratos maiores pesam mais na média).",
    )
    _kpi_card(
        c5, "Ticket Médio", _brl(_valor("Ticket Médio (R$)")), _partes("Ticket Médio (R$)"),
        help="Média simples do valor de principal (principalAmount) por contrato do recorte: Total "
        "Concedido ÷ nº de contratos.",
    )

    c6, c7, c8, c9, c10 = st.columns(5)
    _kpi_card(
        c6, "Total Concedido da Carteira Ativa",
        _brl(_valor("Total Concedido da Carteira Ativa (R$)")),
        _partes("Total Concedido da Carteira Ativa (R$)"),
        help="Soma do principal (principalAmount) só das parcelas ainda EM ABERTO dos contratos ativos — "
        "a parte de principal do que falta receber, sem os juros. É o mesmo conjunto de parcelas do "
        "'Saldo da Carteira Ativa' ao lado, mas contando apenas o principal; a diferença entre os dois "
        "são os juros a receber.",
    )
    _kpi_card(
        c7, "Saldo da Carteira Ativa", _brl(_valor("Saldo da Carteira Ativa (R$)")),
        _partes("Saldo da Carteira Ativa (R$)"),
        help="Soma do valor cheio (amount: principal + juros) das parcelas ainda em aberto dos contratos "
        "ativos — o que falta receber, incluindo parcelas vincendas e vencidas. É o 'saldo devedor' "
        "usado como base do NPL.",
    )
    _kpi_card(
        c8, "Total Recebido", _brl(_valor("Total Recebido (R$)")), _partes("Total Recebido (R$)"),
        help="Soma do paidAmount das parcelas já pagas dos contratos do recorte — principal + juros "
        "efetivamente recebidos até hoje.",
    )
    _kpi_card(
        c9, "NPL 90", _pct(_valor("NPL 90 (%)")), _partes("NPL 90 (%)", _pct),
        help="NPL = saldo devedor com atraso ≥90 dias ÷ saldo devedor total da carteira SEM write-off "
        "(atraso ≤360). Em nível de contrato: se o maior atraso do contrato é ≥90 dias (e ≤360), o "
        "saldo em aberto inteiro dele (amount das parcelas em aberto) entra no numerador. Mesma "
        "fórmula do 'NPL por faixa de atraso' da aba Análise da Carteira. Não obedece ao filtro "
        "'Carteira'.",
    )
    _kpi_card(
        c10, "NPL 90 + WO", _pct(_valor("NPL 90 + WO (%)")), _partes("NPL 90 + WO (%)", _pct),
        help="Igual ao NPL 90, mas o saldo em write-off (atraso >360 dias) entra no numerador E no "
        "denominador: (saldo com atraso de 90 a 360 dias + saldo em write-off) ÷ saldo devedor total "
        "incluindo write-off. Não obedece ao filtro 'Carteira'.",
    )

    if categorias:
        col_a, col_b, col_c, col_d = st.columns(4)
        with col_a:
            st.caption(
                "% do valor já recebido (paidAmount das parcelas pagas, principal + juros) de cada "
                "categoria — o mesmo card 'Total Recebido'."
            )
            st.plotly_chart(
                build_donut_chart(
                    {cat: _valor("Total Recebido (R$)", cat) for cat in categorias},
                    "Total Recebido", "R$ ",
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
        with col_c:
            st.caption(
                "% do saldo em aberto (amount: principal + juros das parcelas não pagas) de cada "
                "categoria — o mesmo card 'Saldo da Carteira Ativa'."
            )
            st.plotly_chart(
                build_donut_chart(
                    {cat: _valor("Saldo da Carteira Ativa (R$)", cat) for cat in categorias},
                    "Saldo da Carteira Ativa", "R$ ",
                ),
                width="stretch",
            )
        with col_d:
            st.caption(
                "% do principal das parcelas em aberto de cada categoria — o mesmo card 'Total "
                "Concedido da Carteira Ativa'."
            )
            st.plotly_chart(
                build_donut_chart(
                    {cat: _valor("Total Concedido da Carteira Ativa (R$)", cat) for cat in categorias},
                    "Total Concedido da Carteira Ativa", "R$ ",
                ),
                width="stretch",
            )

    # --- Tópico 2: Distribuição por Produto ---------------------------------
    st.divider()
    st.subheader(
        "2. Distribuição por Produto",
        help="Os mesmos 10 indicadores da seção 1, lado a lado para o Total e para cada categoria "
        "(App / Crédito Produtor no CCB; tipos de produto no CPR). Com CCB e CPR selecionados juntos, "
        "as colunas 'CCB' e 'CPR' trazem os produtos e, depois delas, uma coluna extra para cada linha "
        "de crédito (App, Crédito Produtor, tipos de CPR). Veja o help de cada card da seção 1 para a "
        "fórmula de cada linha. Contratos sem categoria (ex.: CCB sem cadastro em client_data) entram "
        "só no Total (e no produto).",
    )
    colunas_dist = [kpis["Total"]] + [kpis[cat] for cat in categorias]
    if varios_produtos:
        colunas_dist += [r["kpis_linhas"][linha] for linha in r["linhas"]]
    distribuicao = pd.concat(colunas_dist, axis=1)
    distribuicao_fmt = distribuicao.apply(
        lambda linha: [_formatar_indicador(linha.name, v) for v in linha], axis=1, result_type="expand",
    )
    distribuicao_fmt.columns = distribuicao.columns
    # mesmos nomes dos cards da seção 1
    distribuicao_fmt = distribuicao_fmt.rename(index={
        "Contratos Ativos": "Qtd Contratos Ativos",
        "Quantidade de Contratos (Total)": "Qtd Contratos Total",
    })
    st.dataframe(distribuicao_fmt, width="stretch")
    if varios_produtos:
        st.caption(
            "A tabela acima detalha os principais indicadores da carteira, segmentando entre o total, "
            "cada produto (CCB e CPR) e cada linha de crédito (App, Crédito Produtor e tipos de CPR)."
        )
    elif produtos_selecionados == ("CCB",):
        st.caption(
            "A tabela acima detalha os principais indicadores da carteira, segmentando entre o total, "
            "operações via aplicativo (App) e crédito para produtor (Crédito Produtor)."
        )
    else:
        st.caption(
            "A tabela acima detalha os principais indicadores da carteira, segmentando entre o total e "
            "cada tipo de produto CPR (productType)."
        )

    # --- Tópico 3: Indicadores de Risco -------------------------------------
    st.divider()
    st.subheader(
        "3. Indicadores de Risco",
        help="Inadimplência por faixa de atraso (% da carteira), distribuição da carteira em aberto por "
        "faixa de atraso, NPL 90/NPL 30 (com e sem write-off), evolução mensal do NPL 90 e provisão "
        "(PDD). Respeita o filtro de Produto e o Período, mas NÃO o filtro 'Carteira': tudo aqui, "
        "exceto o gráfico e a tabela 'Indicadores de Risco', inclui o write-off (atraso >360 dias).",
    )

    st.caption(
        "% da carteira (fórmula canônica: saldo em aberto ÷ SALDO TOTAL contratado — 'inadimplência', "
        "não NPL sobre saldo devedor) em cada faixa de atraso (FPD, 15+, 30+, 60+, 90+ dias), "
        "comparando o Total com cada categoria — quanto mais alta a barra, maior a fatia do total "
        "contratado que já está naquele nível de atraso ou pior."
    )
    st.plotly_chart(build_risco_bar_chart(risco), width="stretch")

    st.markdown(
        "#### Indicadores de Risco",
        help="Para cada faixa de atraso (FPD 90d, 15+, 30+, 60+, 90+ dias): saldo em R$ das parcelas "
        "em aberto de contratos naquela faixa, e % da carteira = esse saldo ÷ SALDO TOTAL contratado "
        "(pago + em aberto) do recorte — a mesma fórmula canônica usada na Análise de Risco. Note que "
        "é diferente do NPL calculado na aba 'Análise da Carteira' e na tabela de NPL abaixo, que usam "
        "o saldo devedor como denominador em vez do saldo total.",
    )
    risco_tabela = pd.concat([risco["Total"]] + [risco[cat] for cat in categorias], axis=1)
    st.dataframe(risco_tabela.style.format("{:,.2f}"), width="stretch")

    st.caption(
        f"As seções abaixo consideram a carteira completa de {produto_label} (em aberto + "
        "write-off), independentemente do filtro 'Carteira'."
    )

    _separador_subtopico()
    # --- Faixas de atraso ---------------------------------------------------
    st.markdown(
        "#### Faixas de atraso",
        help="Carteira com saldo em aberto distribuída pela faixa do MAIOR atraso de cada contrato "
        "(se o contrato tem parcelas com atrasos diferentes, o contrato inteiro cai na faixa da pior). "
        "'Amount' = valor cheio das parcelas em aberto (principal + juros); 'Principal' = só a parte de "
        "principal dessas parcelas; 'Princ. <produto>' = Principal de cada produto; 'Qtde' = nº de "
        "contratos; '%' = Principal da faixa ÷ Principal total. Inclui write-off (faixas acima de 360 "
        "dias). Campos: installments.amount, installments.principalAmount, installments.paid, "
        "installments.delay.",
    )
    faixas, faixas_amount = r["faixas_atraso"], r["faixas_atraso_amount"]
    st.plotly_chart(build_faixas_atraso_chart(faixas_amount), width="stretch")
    formato_faixas = {c: "R$ {:,.0f}" for c in faixas.columns if c not in ("Qtde", "%")}
    formato_faixas.update({"Qtde": "{:,.0f}", "%": "{:.1f}%"})
    st.dataframe(
        _negrito_ultima_linha(faixas.style.format(formato_faixas), faixas), width="stretch",
    )

    _separador_subtopico()
    # --- Inadimplência — NPL 90 e NPL 30 ------------------------------------
    st.markdown(
        "#### Inadimplência — NPL 90 e NPL 30",
        help="NPL calculado sobre o SALDO DEVEDOR (amount das parcelas em aberto), em nível de contrato: "
        "se o maior atraso do contrato é ≥N dias, o saldo inteiro dele entra no NPL N. 'Sem WO': "
        "numerador = saldo com atraso de N a 360 dias; denominador = saldo sem write-off (atraso ≤360). "
        "'c/ WO': o saldo em write-off (atraso >360 dias) entra no numerador e no denominador. Mesma "
        "metodologia da aba Análise da Carteira. Campos: installments.amount, installments.paid, "
        "installments.delay.",
    )
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.metric(
            "NPL 90", _pct(npl["npl_90"]),
            help="Saldo com atraso de 90 a 360 dias ÷ saldo devedor sem write-off.",
        )
        st.caption(f"Sem WO · {_brl(npl['atraso_90_360'])} com atraso de 90 a {WO} dias")
    with k2:
        st.metric(
            "NPL 30", _pct(npl["npl_30"]),
            help="Saldo com atraso de 30 a 360 dias ÷ saldo devedor sem write-off.",
        )
        st.caption(f"Sem WO · {_brl(npl['atraso_30_360'])} com atraso de 30 a {WO} dias")
    with k3:
        st.metric(
            "NPL 90 c/ WO", _pct(npl["npl_90_wo"]),
            help="(Saldo com atraso de 90 a 360 dias + saldo em write-off) ÷ saldo devedor total "
            "incluindo write-off.",
        )
        st.caption(f"WO de {_brl(npl['wo'])} (atraso > {WO} dias) incluído")
    with k4:
        st.metric(
            "NPL 30 c/ WO", _pct(npl["npl_30_wo"]),
            help="(Saldo com atraso de 30 a 360 dias + saldo em write-off) ÷ saldo devedor total "
            "incluindo write-off.",
        )
        st.caption(f"WO de {_brl(npl['wo'])} (atraso > {WO} dias) incluído")

    npl_cat = r["npl_tabela"].reset_index().rename(columns={
        "Produto": "Produto / Linha de crédito",
        "saldo_total": "Saldo (amount)", "atraso_30_360": f"Atraso 30-{WO}d",
        "atraso_90_360": f"Atraso 90-{WO}d", "wo": f"WO > {WO}d",
        "npl_30": "NPL 30", "npl_90": "NPL 90", "npl_30_wo": "NPL 30 c/ WO", "npl_90_wo": "NPL 90 c/ WO",
    }).drop(columns=["saldo_sem_wo"]).set_index("Produto / Linha de crédito")
    formato_npl = {c: "R$ {:,.0f}" for c in npl_cat.columns if not c.startswith("NPL")}
    formato_npl.update({c: "{:.2f}%" for c in npl_cat.columns if c.startswith("NPL")})
    st.dataframe(_negrito_totais(npl_cat.style.format(formato_npl), npl_cat), width="stretch")
    st.caption(
        "Uma linha para cada linha de crédito dos produtos selecionados"
        + (", com o subtotal de cada produto ('Total CCB', 'Total CPR') e o 'Total' geral. " if varios_produtos
           else " e o 'Total'. ")
        + "'Saldo (amount)' inclui o write-off. NPL sem WO = atraso ÷ (saldo − WO); NPL c/ WO = "
        "(atraso + WO) ÷ saldo."
    )

    _separador_subtopico()
    # --- Evolução do NPL 90 -------------------------------------------------
    st.markdown(
        "#### Evolução do NPL 90 — desde Jan/25",
        help="NPL 90 no fim de cada mês desde janeiro/2025, sem e com write-off (mesma fórmula dos "
        "cards acima, aplicada ao saldo e ao atraso de cada contrato naquela data). O histórico é "
        "reconstruído de installments.dueDate, installments.paymentDate e installments.paid, considerando "
        "a vigência das renegociações; o último ponto é o dia de hoje e bate com o card 'NPL 90' (e, "
        "para cada linha de crédito, com a linha dela na tabela acima). Os dois filtros escolhem o que "
        "desenhar: cada combinação de linha de crédito x tipo de NPL vira uma linha do gráfico (ex.: "
        "App e Crédito Produtor x s/ WO e c/ WO = 4 linhas). 'Total' = o recorte inteiro dos produtos "
        "selecionados.",
    )
    opcoes_linhas = ["Total"] + list(r["linhas"])
    sufixo = "_".join(opcoes_linhas)  # troca de produto => novas opções => seleção reinicia
    f_linhas, f_tipos, _f_spacer = st.columns([1, 1, 2])  # cada filtro = 1/4 da largura
    with f_linhas:
        sel_linhas = st.multiselect(
            "Linha de crédito", options=opcoes_linhas, default=["Total"], key=f"exec_evol_linhas_{sufixo}",
            help="Escolha 'Total' e/ou as linhas de crédito dos produtos selecionados (App, Crédito "
            "Produtor, tipos de CPR) que quer ver no gráfico.",
        )
    with f_tipos:
        sel_tipos = st.multiselect(
            "Tipo de NPL", options=["NPL 90 s/ WO", "NPL 90 c/ WO"], default=["NPL 90 s/ WO", "NPL 90 c/ WO"],
            key="exec_evol_tipos",
            help="'NPL 90 s/ WO': write-off fora do cálculo. 'NPL 90 c/ WO': saldo em write-off no "
            "numerador e no denominador.",
        )
    if sel_linhas and sel_tipos:
        st.plotly_chart(
            build_evolucao_npl90_chart(r["evolucao_npl90"], sel_linhas, sel_tipos), width="stretch",
        )
    else:
        st.info("Selecione ao menos uma linha de crédito (ou 'Total') e um tipo de NPL para ver o gráfico.")

    _separador_subtopico()
    # --- PDD ----------------------------------------------------------------
    st.markdown(
        "#### PDD",
        help="Provisão para Devedores Duvidosos, calculada com a régua de cada FUNDO (aba 'Regras PDD' da "
        "planilha 'PDD por Rating'): Ghia = tabela da Ghia, pelo maior atraso do DEVEDOR (CPF/CNPJ) na "
        "Ghia; Kanastra = escala própria, pelo maior atraso do CLIENTE em toda a CCB (todos os fundos); "
        "Oikos (e Oikos Warehouse) = régua do FIAGRO, pelo maior atraso do CONTRATO; demais fundos = "
        "Res. CMN 2.682, pelo maior atraso do contrato. O % da faixa vale para TODO o saldo em aberto "
        "(amount), inclusive parcelas ainda a vencer. Provisão = Saldo × % PDD. PDD total = soma das "
        "provisões dos fundos selecionados; o % ao lado é PDD total ÷ saldo em aberto. Campos: "
        "installments.amount, installments.paid, installments.delay, installments.portfolio, "
        "ccb/cpr.taxId.",
    )
    fundos_disponiveis = r["fundos"]
    col_fundo, _col_fundo_spacer = st.columns(2)  # filtro ocupa metade da largura
    with col_fundo:
        sel_fundos = st.multiselect(
            "Fundo", options=fundos_disponiveis, default=fundos_disponiveis,
            key="exec_pdd_fundos_" + "_".join(fundos_disponiveis),
            help="Fundo (portfolio) que detém o contrato — o portfolio da ÚLTIMA parcela de cada contrato, "
            "sem agrupar nomes no filtro (Oikos e Oikos Warehouse aparecem separados, mas ambos usam a "
            "régua da Oikos). Selecionando mais de um, as provisões e saldos dos fundos escolhidos são "
            "somados. A PDD de cada contrato não depende da seleção: o atraso do devedor/cliente é "
            "sempre medido na base completa (conforme a régua do fundo).",
        )
    if not sel_fundos:
        st.info("Selecione ao menos um fundo para ver a PDD.")
        return
    pdd = resumir_pdd(r["pdd_contratos"], produtos_selecionados, sel_fundos)

    col_pdd, col_pdd_total = st.columns([3, 1])
    with col_pdd:
        tab_fundos = pdd["fundos"]
        formato_fundos = {"Contratos": "{:,.0f}", "Saldo": "R$ {:,.0f}", "% PDD": "{:.2f}%", "Provisão": "R$ {:,.0f}"}
        st.dataframe(
            _negrito_ultima_linha(tab_fundos.style.format(formato_fundos), tab_fundos), width="stretch",
        )
    with col_pdd_total:
        st.metric(
            "PDD total", _brl(pdd["total"]),
            help="Soma das provisões dos contratos dos fundos selecionados (Saldo × % PDD da faixa de "
            "cada contrato, pela régua do fundo).",
        )
        st.caption(f"{pdd['pct']:.2f}% do saldo em aberto (amount)")
        st.caption(
            "Cada fundo usa a sua régua; o % vale para todo o saldo em aberto, inclusive as parcelas "
            "vincendas. Valor presente aproximado pelo amount da parcela."
        )

    if pdd["faixas"]:
        st.caption("Detalhe por faixa de cada régua (apenas as réguas dos fundos selecionados):")
        abas = st.tabs([PDD_UNIDADE_CURTA[regua] for regua in pdd["faixas"]])
        for aba, (regua, tabela) in zip(abas, pdd["faixas"].items()):
            with aba:
                st.dataframe(
                    _negrito_ultima_linha(
                        tabela.style.format({
                            "Contratos": "{:,.0f}", "Devedores": "{:,.0f}", "Saldo": "R$ {:,.0f}",
                            "% PDD": "{:.2f}%", "Provisão": "R$ {:,.0f}",
                        }),
                        tabela,
                    ),
                    width="stretch",
                )


def render_painel_executivo():
    """Roda em `st.fragment`: mexer em qualquer filtro (cabeçalho ou meio
    da aba) só reprocessa esta aba, sem esmaecer o app inteiro."""
    _render_painel_executivo_body()
