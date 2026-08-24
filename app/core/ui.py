import streamlit as st


def colunas_compactas(ativos):
    """Monta uma linha de `st.columns` só com as posições ativas, na ordem
    em que aparecem, com larguras iguais entre si -- pensada pra filtros
    condicionais (ex.: "Tipo de operação (CCB)" só existe quando "CCB"
    está selecionado no filtro "Produto" da mesma linha).

    Sem isso, reservar uma coluna de largura fixa pra cada filtro
    (`st.columns(3)`, por exemplo) faz a coluna ficar em branco quando o
    filtro correspondente não se aplica, abrindo uma lacuna vazia no meio
    da linha (o filtro seguinte não "sobe" pra preencher o espaço).

    `ativos`: lista de booleans, uma por posição potencial da linha (ex.:
    `[True, "CCB" in produtos, "CPR" in produtos]`, sendo `True` os
    filtros que sempre aparecem). Devolve uma lista do mesmo tamanho de
    `ativos`, com um objeto de coluna (resultado de `st.columns`) em cada
    posição ativa e `None` nas inativas -- o chamador deve envolver o
    conteúdo de cada filtro condicional em `if coluna is not None:` (ou
    checar antes de usar `with coluna:`).

    Importante: como o valor de um `st.multiselect`/`st.radio` já está
    disponível no `st.session_state` (pela key) ANTES da própria linha de
    filtros ser desenhada de novo a cada rerun do Streamlit, o padrão de
    uso é ler o valor atual do filtro "Produto" via
    `st.session_state.get(key, default)` para decidir quais posições
    ficam ativas, e só então criar a linha com esta função -- assim o
    layout já reflete a seleção corrente, sem atraso de uma interação."""
    n_ativos = sum(1 for a in ativos if a)
    if n_ativos == 0:
        return [None] * len(ativos)
    cols = iter(st.columns(n_ativos))
    return [next(cols) if a else None for a in ativos]
