"""Agente do "Chat AI": monta o prompt (com a documentação do Painel
embutida), expõe as ferramentas de `crud.chat_ai.data` como function-calling
da OpenAI, e roda o loop de pergunta -> (chamadas de ferramenta)* -> resposta
final."""
import json
from pathlib import Path

from openai import OpenAI

from core.config import OPENAI_API_KEY
from crud.analise_risco.data import VARIAVEIS
from crud.chat_ai import data as ferramentas_dados

MODEL = "gpt-5.4-mini"
MAX_ITERACOES = 6

# app/crud/chat_ai/agent.py -> parents[3] = raiz do repositório (onde está
# o documentacao_indicadores.md salvo pra diretoria).
DOC_PATH = Path(__file__).resolve().parents[3] / "documentacao_indicadores.md"


def _carregar_documentacao():
    try:
        return DOC_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "(A documentação em documentacao_indicadores.md não foi encontrada em disco. "
            "Responda só com base nas ferramentas disponíveis, e avise o usuário dessa limitação "
            "se a pergunta depender de metodologia de cálculo.)"
        )


def _montar_system_prompt():
    return f"""Você é o assistente de dados do "Painel Nagro — Crédito", um dashboard interno de
análise de crédito da Nagro Crédito Agro. Você conversa com pessoas da equipe/diretoria que querem
entender a carteira de crédito, os indicadores do Painel, ou tirar dúvidas sobre o banco de dados SGC.

# Como responder
1. Primeiro, veja se a documentação abaixo (metodologia oficial de cada indicador/gráfico do Painel)
   já responde a pergunta conceitual (ex.: "como é calculado o NPL?", "o que é write-off?").
2. Para perguntas sobre NÚMEROS/dados atuais da carteira, use preferencialmente as ferramentas
   `relatorio_*` — elas reaproveitam o cache já calculado pelo próprio Painel (rápido, sem custo extra
   de consulta ao banco) e seguem exatamente as mesmas fórmulas descritas na documentação.
3. Só use `executar_sql_select` quando a pergunta pedir um recorte, filtro ou combinação que nenhuma
   ferramenta de relatório cobre (ex.: um cliente específico, uma condição muito específica). Antes de
   montar uma query, se não tiver certeza dos nomes exatos das colunas, use `descrever_tabela` primeiro.
   Toda query roda em modo somente leitura (SELECT) e só nas tabelas listadas em
   `listar_tabelas_disponiveis` — não tente nenhum outro tipo de comando, ele será bloqueado.
4. Sempre que possível, cite de qual fonte veio o número (nome do relatório/ferramenta usada), e o
   recorte de filtro aplicado (produto, carteira, período), pra quem está lendo saber exatamente do que
   se trata.
5. Se uma pergunta for ambígua quanto ao recorte (ex.: não disse se é CCB ou CPR, ou qual carteira),
   pode assumir os padrões do próprio Painel (CCB+CPR, "Carteira em aberto", todo o histórico) e deixar
   claro na resposta qual recorte você usou — não precisa parar pra perguntar, a menos que a pergunta
   seja genuinamente impossível de responder sem mais contexto.
6. Nunca invente números. Se uma ferramenta falhar ou não tiver o dado, diga isso claramente e sugira
   um caminho (outra ferramenta, ou reformular a pergunta).
7. Responda sempre em português, em tom direto e objetivo, adequado para uso interno da empresa.

# Variáveis de perfil disponíveis na Análise de Risco (parâmetro `variavel` das ferramentas de risco)
{", ".join(sorted(VARIAVEIS))}

# Carteiras disponíveis (parâmetro `carteira`)
"Carteira em aberto" (não quitados e sem atingir 360 dias de atraso), "WriteOff" (atraso >= 360 dias),
"Carteira total" (sem filtro de estado).

# Documentação oficial dos indicadores e gráficos do Painel (metodologia de cálculo)
{_carregar_documentacao()}
"""


SYSTEM_PROMPT = _montar_system_prompt()


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "relatorio_analise_carteira",
            "description": (
                "Indicadores completos da aba 'Análise da Carteira': resumo Total/Em aberto/WriteOff, "
                "NPL por faixa de atraso, aging, taxas-chave, rentabilidade e concentração (HHI)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "produtos": {
                        "type": "array", "items": {"type": "string", "enum": ["CCB", "CPR"]},
                        "description": "Produtos a incluir. Padrão: os dois (CCB e CPR).",
                    },
                    "tipo_operacao_ccb": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Filtro opcional de 'App'/'Crédito Produtor' dentro de CCB.",
                    },
                    "tipo_produto_cpr": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Filtro opcional por tipo de produto CPR.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "relatorio_painel_executivo",
            "description": (
                "Indicadores completos da aba 'Painel Executivo' (visão geral, risco por faixa de "
                "atraso e financeiro/PDD/margem) pra um Produto e uma Carteira, no Total e por categoria."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "produto": {"type": "string", "enum": ["CCB", "CPR"], "description": "Padrão: CCB."},
                    "carteira": {
                        "type": "string",
                        "enum": ["Carteira em aberto", "WriteOff", "Carteira total"],
                        "description": "Padrão: 'Carteira em aberto'.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "relatorio_risco_por_variavel",
            "description": (
                "Inadimplência (NPL 90+) segmentada por uma variável de perfil do cliente/operação "
                "(Rating, UF, Setor, Faixa de Renda, Tempo de Atividade, Faixa de Ticket, Categoria) — "
                "mesma fórmula usada no Painel Executivo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "variavel": {
                        "type": "string", "enum": sorted(VARIAVEIS),
                        "description": "Qual variável de perfil analisar.",
                    },
                    "carteira": {
                        "type": "string",
                        "enum": ["Carteira em aberto", "WriteOff", "Carteira total"],
                    },
                    "produtos": {"type": "array", "items": {"type": "string", "enum": ["CCB", "CPR"]}},
                    "tipo_operacao_ccb": {"type": "array", "items": {"type": "string"}},
                    "tipo_produto_cpr": {"type": "array", "items": {"type": "string"}},
                    "min_contratos": {
                        "type": "integer",
                        "description": "Categorias com menos contratos que isso são descartadas. Padrão: 5.",
                    },
                },
                "required": ["variavel"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "relatorio_ranking_dispersao",
            "description": (
                "Ranking de quais variáveis de perfil mais separam bom de mau pagador (maior dispersão "
                "de % NPL90+ entre suas categorias) — pra apoiar decisões de política de crédito."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "carteira": {
                        "type": "string",
                        "enum": ["Carteira em aberto", "WriteOff", "Carteira total"],
                    },
                    "produtos": {"type": "array", "items": {"type": "string", "enum": ["CCB", "CPR"]}},
                    "min_contratos": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "relatorio_monitoramento_clientes",
            "description": (
                "Cobertura de monitoramento e watchlist de contratos com indicadores de risco piorando "
                "(rating, dívidas/atraso externos, protestos), ordenados por severidade. Sem filtro de "
                "carteira/produto/período — olha todo o universo monitorado."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "min_indicadores": {
                        "type": "integer",
                        "description": "Mínimo de indicadores piorando pra entrar na watchlist. Padrão: 1.",
                    },
                    "limite": {"type": "integer", "description": "Máx. de contratos retornados. Padrão: 30."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "relatorio_estabilidade_rating",
            "description": (
                "PSI e KS1 por safra mensal (a partir de jul/2025) comparando a distribuição de RATING "
                "de cada mês contra a safra de referência de jun/2025, com dados do CRM/HubSpot."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "relatorio_monitoramento_modelo",
            "description": (
                "KS, Gini e PSI do MODELO de score v4 (diferente do PSI/KS1 de Estabilidade Rating), "
                "comparando a base de treino/teste com a carteira em produção numa janela de datas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "data_inicio": {"type": "string", "description": "Formato AAAA-MM-DD. Opcional."},
                    "data_fim": {"type": "string", "description": "Formato AAAA-MM-DD. Opcional."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_tabelas_disponiveis",
            "description": "Lista as tabelas do banco SGC que podem ser consultadas via SQL.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "descrever_tabela",
            "description": "Lista as colunas (nome + tipo) de uma tabela permitida do banco SGC.",
            "parameters": {
                "type": "object",
                "properties": {"nome_tabela": {"type": "string"}},
                "required": ["nome_tabela"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "executar_sql_select",
            "description": (
                "Executa uma query SQL somente-leitura (SELECT) contra o banco SGC, restrita às "
                "tabelas de `listar_tabelas_disponiveis`. Use só quando os relatórios prontos não "
                "cobrirem a pergunta."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "Query SQL, começando com SELECT ou WITH."},
                    "limite_linhas": {"type": "integer", "description": "Máx. de linhas retornadas. Padrão: 200."},
                },
                "required": ["sql"],
            },
        },
    },
]


def _executar_ferramenta(nome, argumentos):
    if nome == "relatorio_analise_carteira":
        return ferramentas_dados.relatorio_analise_carteira(
            tuple(argumentos.get("produtos") or ("CCB", "CPR")),
            argumentos.get("tipo_operacao_ccb"),
            argumentos.get("tipo_produto_cpr"),
        )
    if nome == "relatorio_painel_executivo":
        return ferramentas_dados.relatorio_painel_executivo(
            argumentos.get("produto", "CCB"), argumentos.get("carteira", "Carteira em aberto"),
        )
    if nome == "relatorio_risco_por_variavel":
        return ferramentas_dados.relatorio_risco_por_variavel(
            argumentos["variavel"],
            argumentos.get("carteira", "Carteira em aberto"),
            tuple(argumentos.get("produtos") or ("CCB", "CPR")),
            argumentos.get("tipo_operacao_ccb"),
            argumentos.get("tipo_produto_cpr"),
            argumentos.get("min_contratos", 5),
        )
    if nome == "relatorio_ranking_dispersao":
        return ferramentas_dados.relatorio_ranking_dispersao(
            argumentos.get("carteira", "Carteira em aberto"),
            tuple(argumentos.get("produtos") or ("CCB", "CPR")),
            argumentos.get("min_contratos", 5),
        )
    if nome == "relatorio_monitoramento_clientes":
        return ferramentas_dados.relatorio_monitoramento_clientes(
            argumentos.get("min_indicadores", 1), argumentos.get("limite", 30),
        )
    if nome == "relatorio_estabilidade_rating":
        return ferramentas_dados.relatorio_estabilidade_rating()
    if nome == "relatorio_monitoramento_modelo":
        return ferramentas_dados.relatorio_monitoramento_modelo(
            argumentos.get("data_inicio"), argumentos.get("data_fim"),
        )
    if nome == "listar_tabelas_disponiveis":
        return ferramentas_dados.listar_tabelas_disponiveis()
    if nome == "descrever_tabela":
        return ferramentas_dados.descrever_tabela(argumentos["nome_tabela"])
    if nome == "executar_sql_select":
        return ferramentas_dados.executar_select_seguro(
            argumentos["sql"], argumentos.get("limite_linhas", 200),
        )
    return {"erro": f"Ferramenta desconhecida: {nome}"}


def _serializar(resultado):
    try:
        return json.dumps(resultado, ensure_ascii=False, default=str)
    except Exception as exc:
        return json.dumps({"erro": f"Falha ao serializar o resultado da ferramenta: {exc}"})


def responder(historico):
    """`historico`: lista de mensagens [{"role": "user"/"assistant", "content": str}, ...],
    já sem o system prompt (esta função adiciona). Devolve o texto da resposta final."""
    if not OPENAI_API_KEY:
        return "⚠️ A variável OPENAI_API_KEY não está configurada — não é possível usar o Chat AI."

    cliente = OpenAI(api_key=OPENAI_API_KEY)
    mensagens = [{"role": "system", "content": SYSTEM_PROMPT}] + list(historico)

    for _ in range(MAX_ITERACOES):
        try:
            resposta = cliente.chat.completions.create(
                model=MODEL, messages=mensagens, tools=TOOLS, tool_choice="auto",
            )
        except Exception as exc:
            return f"⚠️ Erro ao chamar a OpenAI: {exc}"

        msg = resposta.choices[0].message
        if not msg.tool_calls:
            return msg.content or "(sem resposta)"

        mensagens.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id, "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        for tc in msg.tool_calls:
            nome = tc.function.name
            try:
                argumentos = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                argumentos = {}
            try:
                resultado = _executar_ferramenta(nome, argumentos)
            except Exception as exc:
                resultado = {"erro": str(exc)}
            mensagens.append({
                "role": "tool", "tool_call_id": tc.id, "content": _serializar(resultado),
            })

    return "Não consegui concluir a resposta em tempo hábil — tente reformular ou dividir a pergunta."
