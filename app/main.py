import streamlit as st

from crud.analise_risco.view import render_analise_risco
from crud.carteira.view import render_carteira
from crud.chat_ai.view import render_chat_ai
from crud.estabilidade import render_estabilidade
from crud.monitoramento.view import render_monitoramento
from crud.monitoramento_clientes.view import render_monitoramento_clientes
from crud.painel_executivo.view import render_painel_executivo

st.set_page_config(page_title="Painel Nagro — Crédito", layout="wide")

(
    tab_monitoramento, tab_carteira, tab_executivo,
    tab_analise_risco, tab_monitoramento_clientes, tab_chat_ai,
) = st.tabs([
    "📊 Monitoramento do Modelo",
    "💼 Análise da Carteira",
    "📈 Painel Executivo",
    "🔬 Análise de Risco",
    "🚦 Monitoramento de Clientes",
    "🤖 Chat AI",
])

with tab_monitoramento:
    sub_relatorio, sub_estabilidade = st.tabs(["Relatório", "Estabilidade Rating"])
    with sub_relatorio:
        render_monitoramento()
    with sub_estabilidade:
        render_estabilidade()

with tab_carteira:
    render_carteira()

with tab_executivo:
    render_painel_executivo()

with tab_analise_risco:
    render_analise_risco()

with tab_monitoramento_clientes:
    render_monitoramento_clientes()

with tab_chat_ai:
    render_chat_ai()
