import streamlit as st

from core.config import OPENAI_API_KEY
from crud.chat_ai.agent import responder

CHAVE_HISTORICO = "chat_ai_historico"

# Fixa a barra de input do chat na parte de baixo da tela (por padrão, o Streamlit só faz
# isso quando o chat_input está solto na raiz do script; como aqui ele está dentro de uma
# aba, precisa de um empurrão via CSS) e reserva espaço no fim da página pra ela não tampar
# a última mensagem.
_CSS_CHAT_FIXO = """
<style>
div[data-testid="stChatInput"] {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 999;
    background-color: inherit;
    padding: 0.75rem 3rem 1.25rem 3rem;
    border-top: 1px solid rgba(128, 128, 128, 0.25);
}
.block-container {
    padding-bottom: 6rem;
}
</style>
"""


@st.fragment
def _area_chat():
    """Roda em um fragmento próprio: só esta área é recalculada a cada pergunta, sem
    disparar o rerun completo do app (que é o que causava a tela toda esmaecer)."""
    col_limpar, _col_spacer = st.columns([1, 5])
    with col_limpar:
        if st.button("🧹 Limpar conversa", key="chat_ai_limpar"):
            st.session_state[CHAVE_HISTORICO] = []
            st.rerun(scope="fragment")

    if not st.session_state[CHAVE_HISTORICO]:
        st.info(
            "Pergunte, por exemplo: \"Qual o saldo devedor da carteira em aberto hoje?\", "
            "\"Quais estados têm maior inadimplência 90+?\" ou \"Como é calculado o PSI da "
            "Estabilidade Rating?\"."
        )

    historico = st.container(height=520)
    for msg in st.session_state[CHAVE_HISTORICO]:
        with historico.chat_message(msg["role"]):
            st.markdown(msg["content"])

    pergunta = st.chat_input("Pergunte sobre a carteira, os indicadores ou o banco de dados SGC...")
    if pergunta:
        st.session_state[CHAVE_HISTORICO].append({"role": "user", "content": pergunta})
        with historico.chat_message("user"):
            st.markdown(pergunta)

        with historico.chat_message("assistant"):
            with st.spinner("Consultando dados e pensando..."):
                resposta = responder(st.session_state[CHAVE_HISTORICO])
            st.markdown(resposta)
        st.session_state[CHAVE_HISTORICO].append({"role": "assistant", "content": resposta})


def render_chat_ai():
    st.title("🤖 Chat AI")
    st.caption(
        "Converse com um assistente que conhece a metodologia de todos os indicadores do Painel "
        "(documentacao_indicadores.md) e pode consultar tanto as tabelas já calculadas em cada aba "
        "(reaproveitando o cache do app, sem repetir consulta ao banco) quanto o banco de dados SGC "
        "diretamente, em modo somente leitura, quando a pergunta não estiver coberta pelo relatório."
    )
    st.markdown(_CSS_CHAT_FIXO, unsafe_allow_html=True)

    if not OPENAI_API_KEY:
        st.error(
            "A variável de ambiente `OPENAI_API_KEY` não foi encontrada. Configure-a no arquivo "
            "`.env` (local) ou nos Secrets do Streamlit Cloud para habilitar o Chat AI."
        )
        st.stop()

    if CHAVE_HISTORICO not in st.session_state:
        st.session_state[CHAVE_HISTORICO] = []

    _area_chat()
