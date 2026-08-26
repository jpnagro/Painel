"""Ferramentas de dados usadas pelo agente do "Chat AI".

Duas fontes de dado:

1. "Relatórios" já calculados pelo próprio Painel -- cada `relatorio_*`
   abaixo chama a MESMA função cacheada (`@st.cache_data`) que a aba
   correspondente usa pra se popular. Como o cache do Streamlit é
   compartilhado entre todos os usuários do mesmo processo do app (não é
   por sessão), se alguém já abriu aquela aba com os filtros padrão, a
   chamada aqui é instantânea (cache hit) -- não bate no Postgres de
   novo. Pra maximizar a chance de cache hit, os filtros "default" usados
   aqui replicam exatamente os defaults de cada aba (todos os portfolios,
   todo o histórico de datas etc.).

2. Uma ferramenta de SQL somente-leitura (`executar_select_seguro`),
   restrita às tabelas que o resto do Painel já usa, pra perguntas que os
   relatórios prontos não cobrem.
"""
import json
import re

import pandas as pd
from sqlalchemy import text

from crud.carteira.data import get_engine
from crud.carteira.view import load_dados_brutos, load_indicadores
from crud.painel_executivo.view import load_dados_executivo_brutos, load_indicadores_executivo
from crud.analise_risco.data import VARIAVEIS
from crud.analise_risco.view import load_base_risco
from crud.analise_risco.indicators import inadimplencia_por_variavel, ranking_dispersao
from crud.monitoramento_clientes.view import load_pares_status
from crud.monitoramento_clientes.indicators import construir_watchlist
import crud.estabilidade as estabilidade_module
import crud.monitoramento.view as monitoramento_view
import crud.monitoramento.data as monitoramento_data
from crud.monitoramento.scoring import calculate_psi, psi_status
from scipy.stats import ks_2samp
from sklearn.metrics import roc_auc_score


# ---------------------------------------------------------------------------
# Helpers de serialização (DataFrame -> estrutura JSON-safe)
# ---------------------------------------------------------------------------
def _df_records(df):
    """Tabela "longa" (várias linhas, colunas nomeadas) -> lista de dicts."""
    if df is None or len(df) == 0:
        return []
    return json.loads(df.to_json(orient="records", date_format="iso", double_precision=4))


def _df_record(df):
    """Tabela de 1 linha só (ex.: resumo_carteira) -> um único dict."""
    registros = _df_records(df)
    return registros[0] if registros else {}


def _df_index_to_dict(df):
    """Tabela indexada por rótulo (ex.: `visao_geral`/`risco` do Painel
    Executivo, onde o índice é o nome do indicador) -> dict aninhado,
    preservando o índice como chave."""
    if df is None or len(df) == 0:
        return {}
    return json.loads(df.to_json(orient="index", date_format="iso", double_precision=4))


# ---------------------------------------------------------------------------
# 1. Relatório: Análise da Carteira
# ---------------------------------------------------------------------------
def relatorio_analise_carteira(produtos=("CCB", "CPR"), tipo_operacao_ccb=None, tipo_produto_cpr=None):
    """Indicadores completos da aba "Análise da Carteira": resumo Total /
    Em aberto / WriteOff, NPL por faixa de atraso, distribuição de aging,
    taxas-chave (default, FPD, write-off, renegociação), rentabilidade e
    concentração de carteira (HHI). Sem filtro de portfolio/produto/tipo,
    usa os mesmos defaults da aba (todos os portfolios, CCB+CPR, todo o
    histórico) -- o que maximiza a chance de reaproveitar o cache já
    calculado quando o usuário (ou outra pessoa) já abriu essa aba."""
    ccb, cpr, inst_ccb, inst_cpr, _client = load_dados_brutos()
    portfolios = tuple(sorted(
        set(inst_ccb["portfolio"].dropna().unique()) | set(inst_cpr["portfolio"].dropna().unique())
    ))
    min_data = pd.concat([pd.to_datetime(ccb["releaseDate"]), pd.to_datetime(cpr["releaseDate"])]).min()
    hoje = pd.Timestamp.now().date()

    resultados = load_indicadores(
        tuple(sorted(produtos)) if produtos else ("CCB", "CPR"),
        tuple(sorted(tipo_operacao_ccb)) if tipo_operacao_ccb else None,
        tuple(sorted(tipo_produto_cpr)) if tipo_produto_cpr else None,
        portfolios,
        min_data.date(),
        hoje,
    )
    return {
        "resumo_carteira_total": _df_record(resultados["resumo_carteira"]),
        "resumo_carteira_em_aberto": _df_record(resultados["resumo_carteira_aberta"]),
        "resumo_carteira_writeoff": _df_record(resultados["resumo_carteira_writeoff"]),
        "npl_por_faixa_de_atraso": _df_records(resultados["npl_por_faixa"]),
        "distribuicao_aging": _df_records(resultados["aging"]),
        "taxa_default_fpd": _df_record(resultados["default_fpd"]),
        "taxa_writeoff": _df_record(resultados["writeoff"]),
        "taxa_renegociados": _df_record(resultados["taxa_renegociados"]),
        "rentabilidade": _df_record(resultados["rentabilidade"]),
        "concentracao_cliente_hhi": _df_record(resultados["concentracao_cliente_resumo"]),
        "book_renegociacoes": _df_record(resultados["renegociacao_taxa"]),
    }


# ---------------------------------------------------------------------------
# 2. Relatório: Painel Executivo
# ---------------------------------------------------------------------------
def relatorio_painel_executivo(produto="CCB", carteira="Carteira em aberto"):
    """Indicadores completos da aba "Painel Executivo" pra um Produto
    (CCB ou CPR) e uma Carteira ("Carteira em aberto"/"WriteOff"/
    "Carteira total"): visão geral do negócio, indicadores de risco
    (faixas de atraso, % da carteira) e indicadores financeiros (juros,
    PDD, margem), no Total e por categoria (App/Crédito Produtor pra CCB,
    tipo de produto pra CPR). Usa o intervalo de datas completo (todo o
    histórico) por padrão, igual ao default da aba."""
    df_bruto = load_dados_executivo_brutos()
    min_data = df_bruto["releaseDate"].min()
    hoje = pd.Timestamp.now().date()

    r = load_indicadores_executivo(produto, carteira, min_data.date(), hoje)
    categorias = r["categorias"]
    vg, risco, fin = r["visao_geral"], r["risco"], r["financeiro"]
    return {
        "produto": produto,
        "carteira": carteira,
        "categorias": categorias,
        "n_total_contratos": r["n_total"],
        "n_ccb": r["n_ccb"],
        "n_cpr": r["n_cpr"],
        "visao_geral_total": _df_index_to_dict(vg["Total"]),
        "risco_total": _df_index_to_dict(risco["Total"]),
        "financeiro_total": _df_index_to_dict(fin["Total"]),
        "visao_geral_por_categoria": {c: _df_index_to_dict(vg[c]) for c in categorias},
        "risco_por_categoria": {c: _df_index_to_dict(risco[c]) for c in categorias},
        "financeiro_por_categoria": {c: _df_index_to_dict(fin[c]) for c in categorias},
    }


# ---------------------------------------------------------------------------
# 3. Relatório: Análise de Risco
# ---------------------------------------------------------------------------
def relatorio_risco_por_variavel(
    variavel, carteira="Carteira em aberto", produtos=("CCB", "CPR"),
    tipo_operacao_ccb=None, tipo_produto_cpr=None, min_contratos=5,
):
    """Inadimplência (NPL 90+, mesma fórmula do Painel Executivo)
    segmentada por uma variável de perfil do cliente/operação. `variavel`
    deve ser uma das chaves: "Categoria", "Rating", "UF", "Setor (CNAE)",
    "Faixa de Renda", "Tempo de Atividade", "Faixa de Ticket". Categorias
    com menos de `min_contratos` contratos são descartadas."""
    if variavel not in VARIAVEIS:
        raise ValueError(f"Variável inválida: '{variavel}'. Opções: {sorted(VARIAVEIS)}")

    df = load_base_risco(
        carteira,
        tuple(sorted(produtos)) if produtos else ("CCB", "CPR"),
        tuple(sorted(tipo_operacao_ccb)) if tipo_operacao_ccb else None,
        tuple(sorted(tipo_produto_cpr)) if tipo_produto_cpr else None,
    )
    tabela = inadimplencia_por_variavel(df, VARIAVEIS[variavel], min_contratos=min_contratos)
    return {
        "variavel": variavel,
        "carteira": carteira,
        "n_contratos_no_recorte": int(len(df)),
        "por_categoria": _df_records(tabela),
    }


def relatorio_ranking_dispersao(carteira="Carteira em aberto", produtos=("CCB", "CPR"), min_contratos=5):
    """Ranking de "poder discriminante": quais variáveis de perfil mais
    separam bom de mau pagador (maior diferença de % NPL 90+ entre suas
    categorias) -- referência pra política de crédito."""
    df = load_base_risco(
        carteira, tuple(sorted(produtos)) if produtos else ("CCB", "CPR"), None, None,
    )
    disp = ranking_dispersao(df, VARIAVEIS, min_contratos=min_contratos)
    return {"carteira": carteira, "ranking_dispersao": _df_records(disp)}


# ---------------------------------------------------------------------------
# 4. Relatório: Monitoramento de Clientes
# ---------------------------------------------------------------------------
def relatorio_monitoramento_clientes(min_indicadores=1, limite=30):
    """Cobertura e watchlist de "Monitoramento de Clientes": nº de
    contratos monitorados, com histórico comparável, e a lista de
    contratos com indicadores de risco piorando (rating, dívidas/atraso
    externos, protestos), ordenados por severidade. NÃO aplica filtro de
    carteira/produto/período (olha todo o universo monitorado) -- pra um
    recorte mais específico, use a ferramenta de SQL sobre
    `customer_monitoring`."""
    pares_status = load_pares_status()
    total = len(pares_status)
    com_historico = int(pares_status["tem_historico"].sum())
    watchlist = construir_watchlist(pares_status, min_indicadores=min_indicadores)

    colunas = [
        "nome_cliente_atual", "operationCode_raiz", "produto_atual", "valor_originado_atual",
        "n_indicadores_piorando", "indicadores_piorando", "rating_anterior", "rating_atual",
    ]
    colunas = [c for c in colunas if c in watchlist.columns]
    amostra = watchlist[colunas].head(max(1, min(int(limite), 100)))

    return {
        "total_contratos_monitorados": total,
        "com_historico_comparavel": com_historico,
        "contratos_em_atencao": int(len(watchlist)),
        "amostra_watchlist_ordenada_por_severidade": _df_records(amostra),
    }


# ---------------------------------------------------------------------------
# 5. Relatório: Estabilidade Rating (sub-aba de Monitoramento do Modelo)
# ---------------------------------------------------------------------------
def relatorio_estabilidade_rating():
    """PSI e KS1 por safra mensal (a partir de jul/2025), comparando a
    distribuição de rating de cada mês contra a safra de referência de
    jun/2025 -- dados vindos do CRM/HubSpot, não do banco de operações."""
    csv_path = estabilidade_module.CSV_PATH
    if not csv_path.exists():
        return {"erro": "Arquivo de deals do CRM (hubspot_deals_credito_simplificado.csv) não encontrado localmente."}

    df = estabilidade_module.load_deals(csv_path)
    ref_qtde, ref_pct, ref_pct_acum, ref_total = estabilidade_module.reference_table(df)
    if ref_total == 0:
        return {"erro": f"Safra de referência ({estabilidade_module.REFERENCE_LABEL}) sem deals no CSV."}

    meses = sorted(p for p in df["Safra"].unique() if p >= pd.Period("2025-07", freq="M"))
    linhas = []
    for periodo in meses:
        month_df = df[df["Safra"] == periodo]
        month_qtde = month_df[estabilidade_module.RATING_COL].value_counts().reindex(
            estabilidade_module.CATEGORIES, fill_value=0
        )
        month_total = month_qtde.sum()
        if month_total == 0:
            continue
        _tabela, total_psi, total_ks, status_psi, status_ks = estabilidade_module.build_month_table(
            month_qtde, month_total, ref_qtde, ref_pct, ref_pct_acum,
        )
        linhas.append({
            "safra": estabilidade_module.month_label(periodo),
            "qtde_deals": int(month_total),
            "psi": round(float(total_psi), 4),
            "ks1": round(float(total_ks), 4),
            "status_psi": status_psi,
            "status_ks1": status_ks,
        })
    return {"safra_de_referencia": estabilidade_module.REFERENCE_LABEL, "resumo_por_safra": linhas}


# ---------------------------------------------------------------------------
# 6. Relatório: Monitoramento do Modelo (sub-aba "Relatório")
# ---------------------------------------------------------------------------
def relatorio_monitoramento_modelo(data_inicio=None, data_fim=None):
    """KS, Gini, PSI (do MODELO de score v4 -- diferente do PSI/KS1 de
    Estabilidade Rating) e taxa de inadimplência observada, comparando a
    base de treino/teste do modelo com a carteira em produção na janela
    de datas de originação informada. Sem datas, usa a mesma janela
    default da aba."""
    start = pd.Timestamp(data_inicio) if data_inicio else monitoramento_view.DEFAULT_START
    end = pd.Timestamp(data_fim) if data_fim else monitoramento_view.DEFAULT_END

    df_ref = monitoramento_data.load_reference_data()
    df_atual = monitoramento_data.load_current_data(str(start), str(end))
    if df_atual.empty:
        return {"erro": "Nenhuma operação de produção na janela de datas informada."}

    ks_ref = ks_2samp(
        df_ref[df_ref["target"] == 0]["score_novo"], df_ref[df_ref["target"] == 1]["score_novo"],
    ).statistic
    auc_ref = roc_auc_score(df_ref["target"], df_ref["prob"])
    ks_prod = ks_2samp(
        df_atual[df_atual["target"] == 0]["score_v4"], df_atual[df_atual["target"] == 1]["score_v4"],
    ).statistic
    auc_prod = roc_auc_score(df_atual["target"], df_atual["prob"])
    psi_total, _partes, _breaks = calculate_psi(df_ref[:3000]["score_novo"], df_atual["score_v4"])

    return {
        "janela_producao": f"{start.date()} a {end.date()}",
        "ks_referencia": round(float(ks_ref), 4),
        "ks_producao": round(float(ks_prod), 4),
        "gini_referencia": round(float(2 * auc_ref - 1), 4),
        "gini_producao": round(float(2 * auc_prod - 1), 4),
        "psi": round(float(psi_total), 4),
        "psi_status": psi_status(psi_total),
        "inadimplencia_90d_producao_pct": round(float(df_atual["target"].mean() * 100), 2),
        "n_operacoes_producao": int(len(df_atual)),
    }


# ---------------------------------------------------------------------------
# 7. SQL somente-leitura, restrito às tabelas do SGC já usadas no Painel
# ---------------------------------------------------------------------------
TABELAS_PERMITIDAS = {
    "ccb": "Contratos CCB (crédito com garantia de CCB) — 1 linha por operação/geração (raiz ou renegociação); colunas típicas: operationCode, releaseDate, principalAmount, totalLoan, totalInterest, monthlyRate, installments, renegotiation, renegotiated, externalId, paid, default, firstPaymentDefault.",
    "cpr": "Contratos CPR (Cédula de Produto Rural) — mesma estrutura de ccb, mais a coluna productType (tipo de produto CPR).",
    "installments": "Parcelas dos contratos CCB — colunas típicas: operationCode, dueDate, paymentDate, amount, paidAmount, paid, delay, writeOff, portfolio, default.",
    "installments_cpr": "Parcelas dos contratos CPR — mesma estrutura de installments.",
    "client_data": "Dados cadastrais/score do cliente — colunas típicas: ccbCode, taxId, operationType ('App'/'Crédito Produtor'), rating_v4, score_v4, state, cnaeFiltered, averageMonthlyIncome, activityTime, e sinalizações de restrição cadastral (protesto, restritivo, PEP etc.).",
    "customer_monitoring": "Histórico de consultas periódicas de monitoramento do cliente — colunas típicas: operationCode, taxId, createdAt, rating, score, overdue, loss, credit_portfolio, debts_bv, protests_bv, protests, death, max_delay_paid_installments.",
}

_PALAVRAS_PROIBIDAS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|exec|execute|call|copy|"
    r"vacuum|attach|pragma|merge|replace|into)\b",
    re.IGNORECASE,
)


def listar_tabelas_disponiveis():
    """Lista as tabelas do banco SGC que podem ser consultadas via SQL,
    com uma breve descrição de cada uma."""
    return [{"tabela": t, "descricao": d} for t, d in TABELAS_PERMITIDAS.items()]


def descrever_tabela(nome_tabela):
    """Lista as colunas (nome + tipo) de uma tabela permitida, consultando
    o catálogo do Postgres -- use antes de escrever uma query SQL, pra
    não errar nome de coluna."""
    if nome_tabela not in TABELAS_PERMITIDAS:
        raise ValueError(f"Tabela não permitida: '{nome_tabela}'. Tabelas disponíveis: {sorted(TABELAS_PERMITIDAS)}")
    engine = get_engine()
    query = text(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = :tabela ORDER BY ordinal_position"
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"tabela": nome_tabela})
    return {"tabela": nome_tabela, "descricao": TABELAS_PERMITIDAS[nome_tabela], "colunas": _df_records(df)}


def _validar_select(sql):
    limpo = (sql or "").strip().rstrip(";").strip()
    if not limpo:
        raise ValueError("Query vazia.")
    if ";" in limpo:
        raise ValueError("Só é permitido executar um único comando por chamada (';' encontrado no meio da query).")
    if not re.match(r"^(select|with)\b", limpo, re.IGNORECASE):
        raise ValueError("Só são permitidas queries de leitura (SELECT, ou WITH ... SELECT).")
    if _PALAVRAS_PROIBIDAS.search(limpo):
        raise ValueError("Query contém um comando não permitido — só leitura (SELECT) é aceita.")

    # Nomes de CTE ("WITH nome AS (...)") contam como tabela válida só
    # dentro desta query -- sem isso, uma query com WITH seria bloqueada
    # por engano (a CTE não é uma tabela real do banco).
    ctes = {m.lower() for m in re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s*\(", limpo, re.IGNORECASE)}

    tabelas_citadas = {
        m.lower() for m in re.findall(r"(?:from|join)\s+\"?([a-zA-Z_][a-zA-Z0-9_]*)\"?", limpo, re.IGNORECASE)
    }
    fora_do_escopo = tabelas_citadas - set(TABELAS_PERMITIDAS) - ctes
    if fora_do_escopo:
        raise ValueError(
            f"Tabela(s) fora do escopo permitido: {sorted(fora_do_escopo)}. "
            f"Tabelas disponíveis: {sorted(TABELAS_PERMITIDAS)}"
        )
    return limpo


def executar_select_seguro(sql, limite_linhas=200):
    """Executa uma query SELECT somente-leitura contra o banco SGC,
    restrita às tabelas listadas em `listar_tabelas_disponiveis`. Bloqueia
    qualquer comando que não seja SELECT/WITH, roda numa conexão marcada
    como read-only no Postgres (camada extra de segurança) e sempre limita
    o número de linhas retornadas. Use só quando os relatórios prontos
    (`relatorio_*`) não cobrirem a pergunta."""
    limpo = _validar_select(sql)
    limite_linhas = max(1, min(int(limite_linhas or 200), 1000))
    if not re.search(r"\blimit\b", limpo, re.IGNORECASE):
        limpo = f"SELECT * FROM ({limpo}) AS _consulta_chat_ai LIMIT {limite_linhas}"

    engine = get_engine()
    with engine.connect() as conexao:
        try:
            conexao = conexao.execution_options(postgresql_readonly=True)
        except Exception:
            pass  # driver/versão sem suporte a essa opção -- a validação acima segue valendo
        df = pd.read_sql(text(limpo), conexao)

    if len(df) > limite_linhas:
        df = df.head(limite_linhas)
    return {"n_linhas_retornadas": int(len(df)), "colunas": [str(c) for c in df.columns], "linhas": _df_records(df)}
