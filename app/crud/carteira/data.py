from os import getenv

import numpy as np
import pandas as pd
from dotenv import find_dotenv, load_dotenv
from sqlalchemy import create_engine

load_dotenv(find_dotenv(raise_error_if_not_found=False))

URL_PG = getenv("URL_PG")


# ---------------------------------------------------------------------------
# 1. CONEXÃO E EXTRAÇÃO
# ---------------------------------------------------------------------------
def get_engine():
    return create_engine(URL_PG)


def carregar_dados(engine):
    """Lê as 5 tabelas do SGC por inteiro. Para bases muito grandes, troque
    por leitura em chunks ou filtre por período de releaseDate."""
    ccb = pd.read_sql('SELECT * FROM ccb', engine)
    cpr = pd.read_sql('SELECT * FROM cpr', engine)
    inst_ccb = pd.read_sql('SELECT * FROM installments', engine)
    inst_cpr = pd.read_sql('SELECT * FROM installments_cpr', engine)
    client = pd.read_sql('SELECT * FROM client_data', engine)
    return ccb, cpr, inst_ccb, inst_cpr, client


# ---------------------------------------------------------------------------
# 2. PREPARAÇÃO DAS BASES (unifica CCB+CPR e separa renegociados)
# ---------------------------------------------------------------------------
def _bool_true(serie):
    """Trata NULL como False ao interpretar colunas booleanas do SGC.

    Guarda especial pra série vazia: `.apply` numa Series de 0 linhas não
    tem elemento nenhum pra inferir o tipo do retorno e devolve dtype
    'object' em vez de 'bool' — isso quebra máscaras booleanas
    downstream (`~serie`, usado em preparar_bases) quando a base fica
    totalmente vazia, ex.: usuário desmarca todos os portfolios no
    multiselect. Aqui devolvemos uma Series bool vazia diretamente."""
    if len(serie) == 0:
        return pd.Series([], index=serie.index, dtype=bool)
    return serie.apply(lambda x: bool(x) if pd.notna(x) else False)


def preparar_bases(ccb, cpr, inst_ccb, inst_cpr):
    ccb_c = ccb.copy()
    ccb_c["produto"] = "CCB"
    cpr_c = cpr.copy()
    cpr_c["produto"] = "CPR"

    contratos = pd.concat([ccb_c, cpr_c], ignore_index=True, sort=False)

    contratos["renegociado_flag"] = _bool_true(contratos["renegotiated"])
    contratos["renegociacao_flag"] = _bool_true(contratos["renegotiation"])
    contratos["paid"] = _bool_true(contratos["paid"])
    contratos["releaseDate"] = pd.to_datetime(contratos["releaseDate"])

    # ------------------------------------------------------------------
    # Consolidação de renegociações
    # ------------------------------------------------------------------
    # Um contrato com renegotiation=TRUE é o RESULTADO de uma renegociação
    # (reestrutura o saldo de um contrato já existente — não é dinheiro
    # novo). O "externalId" desses contratos aponta direto para o
    # operationCode do contrato ORIGINAL (raiz), mesmo em renegociações de
    # 2º nível (renegociação de uma renegociação): confirmado no banco que
    # tanto "RA..." quanto "RRA..." de um mesmo contrato apontam para o
    # mesmo operationCode raiz "A...", não um para o outro.
    #
    # Pra não fragmentar o histórico de pagamento em vários operationCode
    # diferentes (e não contar o valor originado mais de uma vez), todo
    # contrato com renegotiation=TRUE tem seu operationCode substituído
    # pelo externalId, unificando o original e todas as suas
    # renegociações sob uma única chave — a do contrato raiz.
    externalid_valido = contratos["externalId"].notna() & (
        contratos["externalId"].astype(str).str.strip() != ""
    )
    contratos["operationCode_raiz"] = np.where(
        contratos["renegociacao_flag"] & externalid_valido,
        contratos["externalId"],
        contratos["operationCode"],
    )
    mapa_operationcode_raiz = dict(zip(contratos["operationCode"], contratos["operationCode_raiz"]))

    # Vigência de cada geração: pra cada contrato (raiz ou renegociação),
    # a data de início da PRÓXIMA geração da mesma raiz (ordenando por
    # releaseDate). Usada abaixo pra saber até quando uma parcela
    # renegociada ainda valia no passado — ex.: contrato originado fev/24
    # e renegociado só em jan/25: numa idade de safra de 6 meses (ago/24),
    # a renegociação ainda não existia, então deve-se considerar somente
    # o contrato original (que ainda não tinha sido renegociado naquela
    # data).
    contratos_ordenados = contratos.sort_values(["operationCode_raiz", "releaseDate"])
    contratos["proxima_geracao_releaseDate"] = (
        contratos_ordenados.groupby("operationCode_raiz")["releaseDate"]
        .shift(-1)
        .reindex(contratos.index)
    )

    # contratos_originais: um registro por relação de crédito (a raiz),
    # com o valor originado, data de originação e demais atributos "de
    # verdade" do empréstimo — as renegociações não entram aqui, pra não
    # duplicar o valor originado.
    contratos_originais = contratos[~contratos["renegociacao_flag"]].copy()
    contratos_ativos = contratos_originais.copy()
    contratos_reneg = contratos[contratos["renegociado_flag"]].copy()

    # ------------------------------------------------------------------
    # Parcelas: busca TODAS (original + renegociações, sem exceção) e
    # anexa a vigência de cada uma (a partir de quando ela realmente
    # valeu, e até quando, se foi renegociada) antes de remapear pro
    # operationCode raiz.
    # ------------------------------------------------------------------
    info_geracao = contratos[["operationCode", "releaseDate", "proxima_geracao_releaseDate"]].rename(
        columns={"releaseDate": "vigencia_inicio"}
    )

    inst_ccb = inst_ccb.copy()
    inst_ccb["produto"] = "CCB"
    inst_cpr = inst_cpr.copy()
    inst_cpr["produto"] = "CPR"
    parcelas = pd.concat([inst_ccb, inst_cpr], ignore_index=True, sort=False)
    parcelas["renegociado_flag"] = _bool_true(parcelas["renegotiated"])
    parcelas = parcelas.merge(info_geracao, on="operationCode", how="left")

    # se a parcela foi renegociada, ela só valeu até a próxima geração
    # começar; se nunca foi renegociada, vale "pra sempre" (sentinela)
    parcelas["vigencia_fim"] = np.where(
        parcelas["renegociado_flag"], parcelas["proxima_geracao_releaseDate"], pd.Timestamp("2100-01-01")
    )
    parcelas["vigencia_fim"] = pd.to_datetime(parcelas["vigencia_fim"]).fillna(pd.Timestamp("2100-01-01"))
    parcelas = parcelas.drop(columns=["proxima_geracao_releaseDate"])

    # versão completa (com vigência, SEM excluir as renegociadas) — usada
    # na reconstrução histórica mês a mês (curva de maturação / roll-rate),
    # que precisa saber o que valia em cada ponto do passado.
    # (guarda `if mapa_operationcode_raiz`: com a base vazia — ex.: usuário
    # desmarca todos os portfolios no multiselect — o mapa fica {} e
    # `.map({})` num Series vazia devolve dtype float64 em vez de manter
    # o dtype original (object/string) da coluna, o que quebra merges
    # posteriores por operationCode; sem nada pra remapear mesmo, é seguro
    # simplesmente pular a remapeação)
    parcelas_com_vigencia = parcelas.copy()
    if mapa_operationcode_raiz:
        parcelas_com_vigencia["operationCode"] = parcelas_com_vigencia["operationCode"].map(
            mapa_operationcode_raiz
        ).fillna(parcelas_com_vigencia["operationCode"])

    # versão "estado atual" (o que já era feito): remapeia pra raiz e
    # exclui as parcelas substituídas — usada pro saldo/atraso de HOJE.
    if mapa_operationcode_raiz:
        parcelas["operationCode"] = parcelas["operationCode"].map(mapa_operationcode_raiz).fillna(
            parcelas["operationCode"]
        )
    parcelas_ativos = parcelas[~parcelas["renegociado_flag"]].copy()
    parcelas_reneg = parcelas[parcelas["renegociado_flag"]].copy()

    return (
        contratos, contratos_ativos, contratos_reneg, contratos_originais,
        parcelas_ativos, parcelas_reneg, parcelas_com_vigencia,
    )


# ---------------------------------------------------------------------------
# 2b. SUBFILTROS (aplicados sobre as tabelas BRUTAS, antes de preparar_bases)
# ---------------------------------------------------------------------------
# Um subfiltro (tipo de operação CCB, tipo de produto CPR) é um atributo do
# contrato RAIZ. Uma renegociação pode não ter esse atributo preenchido (é o
# caso do operationType, que só existe no client_data pra quem tem ccbCode
# = operationCode da raiz) ou pode até ter um valor próprio (é o caso do
# productType em CPR) — em ambos os casos, pra não fragmentar o histórico,
# a decisão de manter ou não um contrato é sempre pela raiz: se a raiz bate
# com o filtro, TODAS as suas gerações (raiz + renegociações) entram.
def _filtrar_por_grupo_raiz(tabela, ops_raiz_selecionadas):
    """Mantém, em `tabela` (ccb ou cpr), somente os contratos cuja raiz
    (o próprio, se não for renegociação, ou o apontado por `externalId`,
    se for) está em `ops_raiz_selecionadas`."""
    t = tabela.copy()
    renegociacao_flag = _bool_true(t["renegotiation"])
    raiz_ok = ~renegociacao_flag & t["operationCode"].isin(ops_raiz_selecionadas)
    reneg_ok = renegociacao_flag & t["externalId"].isin(ops_raiz_selecionadas)
    return t[raiz_ok | reneg_ok].copy()


SEM_CLIENT_DATA = "Sem client_data"


def ops_raiz_por_operation_type(ccb, client, operation_type):
    """Raízes CCB (renegotiation IS NOT TRUE) cujo client_data.operationType
    ('App' ou 'Crédito Produtor') bate com o valor escolhido. Junta por
    ccbCode = operationCode — só as raízes têm entrada em client_data,
    então esse subfiltro naturalmente não filtra as renegociações "soltas"
    (elas seguem a raiz via `_filtrar_por_grupo_raiz`).

    Join com `how="left"` (não "inner"): ~13% das raízes CCB não têm
    NENHUMA linha em client_data (ou têm, mas com operationType nulo) —
    um join interno as descartaria silenciosamente sempre que o subfiltro
    estivesse "ativo" (inclusive no estado padrão do multiselect, com
    tudo marcado). `operation_type=SEM_CLIENT_DATA` devolve exatamente
    essas raízes sem correspondência, pra elas serem uma opção explícita
    do filtro em vez de simplesmente desaparecerem da carteira."""
    raizes = ccb[~_bool_true(ccb["renegotiation"])]
    cli = client[["ccbCode", "operationType"]].dropna(subset=["ccbCode"])
    match = raizes.merge(cli, left_on="operationCode", right_on="ccbCode", how="left")
    if operation_type == SEM_CLIENT_DATA:
        return set(match.loc[match["operationType"].isna(), "operationCode"])
    return set(match.loc[match["operationType"] == operation_type, "operationCode"])


def ops_raiz_por_product_type(cpr, product_type):
    """Raízes CPR (renegotiation IS NOT TRUE) cujo próprio `productType`
    bate com o valor escolhido."""
    raizes = cpr[~_bool_true(cpr["renegotiation"])]
    return set(raizes.loc[raizes["productType"] == product_type, "operationCode"])


def aplicar_subfiltro_ccb(ccb, inst_ccb, client, operation_types):
    """`operation_types`: lista de valores de client_data.operationType
    ('App'/'Crédito Produtor') a manter, ou None = sem filtro (todos).
    Lista vazia (multiselect sem nada marcado) filtra pra carteira vazia.
    Filtra ccb pela raiz (+ renegociações da raiz) e as parcelas
    correspondentes, mantendo tudo em sincronia."""
    if operation_types is None:
        return ccb, inst_ccb
    ops_raiz = set()
    for ot in operation_types:
        ops_raiz |= ops_raiz_por_operation_type(ccb, client, ot)
    ccb_filt = _filtrar_por_grupo_raiz(ccb, ops_raiz)
    inst_filt = inst_ccb[inst_ccb["operationCode"].isin(set(ccb_filt["operationCode"]))]
    return ccb_filt, inst_filt


def aplicar_subfiltro_cpr(cpr, inst_cpr, product_types):
    """`product_types`: lista de valores de cpr.productType a manter, ou
    None = sem filtro (todos). Lista vazia filtra pra carteira vazia.
    Mesma lógica de `aplicar_subfiltro_ccb`, só que o atributo já está na
    própria tabela cpr (não precisa de join com client_data)."""
    if product_types is None:
        return cpr, inst_cpr
    ops_raiz = set()
    for pt in product_types:
        ops_raiz |= ops_raiz_por_product_type(cpr, pt)
    cpr_filt = _filtrar_por_grupo_raiz(cpr, ops_raiz)
    inst_filt = inst_cpr[inst_cpr["operationCode"].isin(set(cpr_filt["operationCode"]))]
    return cpr_filt, inst_filt


def _raiz_de(tabela):
    """Série operationCode -> raiz (o próprio, se não for renegociação, ou
    o externalId, se for) — mesma regra usada em `preparar_bases`."""
    renegociacao_flag = _bool_true(tabela["renegotiation"])
    externalid_valido = tabela["externalId"].notna() & (
        tabela["externalId"].astype(str).str.strip() != ""
    )
    return pd.Series(
        np.where(renegociacao_flag & externalid_valido, tabela["externalId"], tabela["operationCode"]),
        index=tabela.index,
    )


def _filtrar_tabela_e_parcelas_por_portfolio(tabela, parcelas, portfolios):
    """Mantém em `tabela` (ccb ou cpr) a raiz + TODAS as suas renegociações
    sempre que qualquer uma delas (raiz ou renegociação) tiver ao menos
    uma parcela num dos `portfolios` — preserva o valor originado do
    contrato mesmo que a parcela no portfolio selecionado esteja numa
    geração renegociada, não na raiz. Já as parcelas retornadas ficam
    restritas às que de fato estão nos portfolios selecionados (é isso
    que entra no saldo/atraso calculado)."""
    raiz_de_tabela = _raiz_de(tabela)
    mapa_raiz = dict(zip(tabela["operationCode"], raiz_de_tabela))

    parcelas_no_portfolio = parcelas[parcelas["portfolio"].isin(portfolios)]
    ops_com_parcela = set(parcelas_no_portfolio["operationCode"])
    raizes_ok = {mapa_raiz.get(op, op) for op in ops_com_parcela}

    tabela_filt = tabela[raiz_de_tabela.isin(raizes_ok)].copy()
    parcelas_filt = parcelas[
        parcelas["operationCode"].isin(set(tabela_filt["operationCode"]))
        & parcelas["portfolio"].isin(portfolios)
    ].copy()
    return tabela_filt, parcelas_filt


def aplicar_filtro_portfolio(ccb, cpr, inst_ccb, inst_cpr, portfolios):
    """Filtra pela coluna `portfolio` de `installments`/`installments_cpr`
    (o fundo/veículo que detém o recebível — ex.: 'Ghia', 'Oikos',
    'Kanastra'). É um atributo de PARCELA, não de contrato — diferente dos
    outros filtros, um mesmo contrato pode ter parcelas em portfolios
    diferentes ao longo do tempo (ex.: depois de uma renegociação, as
    parcelas novas podem estar num portfolio diferente das antigas). Por
    isso a decisão de manter um contrato é pela RAIZ (raiz + todas as
    renegociações entram se qualquer uma delas tocar um dos portfolios
    selecionados, preservando o valor originado), mas as parcelas que
    efetivamente entram no saldo/atraso são só as que estão de fato nesses
    portfolios.

    `portfolios`: None = sem filtro (todos os portfolios). Uma lista
    (mesmo vazia) filtra de fato — lista vazia = nenhum portfolio
    selecionado = carteira vazia (caso do multiselect sem nada marcado)."""
    if portfolios is None:
        return ccb, cpr, inst_ccb, inst_cpr

    portfolios = list(portfolios)
    ccb_filt, inst_ccb_filt = _filtrar_tabela_e_parcelas_por_portfolio(ccb, inst_ccb, portfolios)
    cpr_filt, inst_cpr_filt = _filtrar_tabela_e_parcelas_por_portfolio(cpr, inst_cpr, portfolios)
    return ccb_filt, cpr_filt, inst_ccb_filt, inst_cpr_filt


# ---------------------------------------------------------------------------
# 3. ESTADO ATUAL DE CADA CONTRATO (saldo + atraso), a partir das parcelas
# ---------------------------------------------------------------------------
def estado_por_contrato(parcelas):
    """Para cada operationCode: saldo_atual, saldo_a_receber, maior atraso,
    flags de default/writeoff/prePaid, a partir das parcelas em aberto.
    Contratos 100% quitados entram com saldo 0 e atraso 0."""

    p = parcelas.copy()
    p["paid"] = _bool_true(p["paid"])
    p["delay"] = p["delay"].fillna(0)

    abertas = p[~p["paid"]].copy()
    valor_ajustado = abertas["amount"].astype(float)
    abertas["saldo_receber_parcela"] = (
        valor_ajustado - abertas["paidAmount"].fillna(0).astype(float)
    ).clip(lower=0)

    # saldo_atual = beginningBalance da parcela em aberto mais antiga
    soma_parcelas = (
        abertas.groupby("operationCode", as_index=False)["amount"]
        .sum()
        .rename(columns={"amount": "saldo_atual"})
    )

    agregados = abertas.groupby("operationCode").agg(
        saldo_a_receber=("saldo_receber_parcela", "sum"),
        max_delay=("delay", "max"),
        n_parcelas_abertas=("delay", "size"),
        em_default=("default", lambda s: bool(_bool_true(s).any())),
        writeoff=("writeOff", lambda s: bool(_bool_true(s).any())),
    ).reset_index()

    estado = agregados.merge(soma_parcelas, on="operationCode", how="left")

    # contratos totalmente quitados (sem nenhuma parcela em aberto)
    todos_ops = p["operationCode"].unique()
    quitados = set(todos_ops) - set(estado["operationCode"])
    if quitados:
        quit_df = pd.DataFrame({"operationCode": list(quitados)})
        for col, val in [
            ("saldo_a_receber", 0.0), ("max_delay", 0), ("n_parcelas_abertas", 0),
            ("em_default", False), ("writeoff", False), ("saldo_atual", 0.0),
        ]:
            quit_df[col] = val
        estado = pd.concat([estado, quit_df], ignore_index=True)

    estado["saldo_atual"] = estado["saldo_atual"].fillna(0)
    estado["quitado"] = estado["n_parcelas_abertas"] == 0
    # bin de 89 (não 90) faz o bucket "90+" = pd.cut (89, inf] = max_delay
    # >= 90, igual ao ">=" usado em npl_por_faixa — antes, com o bin em 90,
    # pd.cut deixava (90, inf], então um contrato com atraso EXATAMENTE 90
    # caía em "61-90" em vez de "90+" (causava um pequeno descolamento
    # entre o % de NPL90+ mostrado no aging e o mostrado em npl_por_faixa).
    estado["bucket_atraso"] = pd.cut(
        estado["max_delay"],
        bins=[-1, 0, 30, 60, 89, np.inf],
        labels=["0 - em dia", "1-30", "31-60", "61-90", "90+"],
    )
    return estado


def juntar_client_data(contratos_ativos, client):
    """Anexa atributos do tomador aos contratos. CCB junta por ccbCode
    (chave exata); CPR junta por taxId (aproximado, nível cliente).

    Em caso de múltiplas linhas de client_data pro mesmo ccbCode/taxId
    (ex.: re-score periódico gerando mais de uma linha histórica pro
    mesmo contrato/cliente), mantém só a de maior score_v4 não-nulo como
    representativa — critério simples e transparente. Sem esse dedup, um
    merge ingênuo MULTIPLICARIA a linha do contrato (uma cópia por linha
    de client_data batendo), inflando qualquer soma monetária calculada
    depois do join (ex.: "Total Concedido" no Painel Executivo, ou
    "saldo" em `perfil_risco_cliente`). Antes o dedup só era aplicado no
    lado CPR (por taxId); o lado CCB (por ccbCode) ficava sem, o que é a
    correção aqui."""
    client = client.copy()
    client_dedup_tax = (
        client.sort_values("score_v4", na_position="first")
        .drop_duplicates(subset="taxId", keep="last")
    )
    client_dedup_ccb = (
        client.dropna(subset=["ccbCode"])
        .sort_values("score_v4", na_position="first")
        .drop_duplicates(subset="ccbCode", keep="last")
    )

    ccb_part = contratos_ativos[contratos_ativos["produto"] == "CCB"].merge(
        client_dedup_ccb.rename(columns={"ccbCode": "operationCode"}),
        on="operationCode", how="left", suffixes=("", "_cli"),
    )
    cpr_part = contratos_ativos[contratos_ativos["produto"] == "CPR"].merge(
        client_dedup_tax, on="taxId", how="left", suffixes=("", "_cli"),
    )
    return pd.concat([ccb_part, cpr_part], ignore_index=True, sort=False)
