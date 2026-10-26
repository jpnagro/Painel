"""Relatório em PDF do Painel Executivo (para diretoria e investidores).

Gera, a partir do MESMO dicionário de resultados que alimenta a tela
(`calcular_indicadores_executivo`), um documento A4 paisagem com capa, filtros
aplicados, as três seções do painel (indicadores, gráficos e tabelas) e notas
metodológicas. Gráficos em matplotlib (renderização local, sem navegador) e
layout em reportlab. Números e datas no padrão brasileiro (1.234,56).

Função pública: `gerar_pdf_painel_executivo`.
"""
import io
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # backend sem janela (servidor/Streamlit)
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402
import pandas as pd  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY  # noqa: E402
from reportlab.lib.pagesizes import A4, landscape  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from crud.painel_executivo.data import WO  # noqa: E402
from crud.painel_executivo.indicators import (  # noqa: E402
    PDD_UNIDADE,
    PDD_UNIDADE_CURTA,
)

EMPRESA = "NAGRO CRÉDITO AGRO"
TITULO = "Painel Executivo — Carteira de Crédito"

# Paleta (a mesma do painel)
AZUL = colors.HexColor("#1A2B3C")
AZUL_NAGRO = colors.HexColor("#1665AF")  # azul da logo da Nagro
CINZA = colors.HexColor("#6C757D")
CINZA_CLARO = colors.HexColor("#F1F3F5")
CINZA_LINHA = colors.HexColor("#D5DADF")
DESTAQUE = colors.HexColor("#E3E9EF")
_PALETA = ["#2A9D8F", "#1A2B3C", "#E9C46A", "#4C956C", "#9D8189", "#264653"]
_PALETA_SERIES = ["#1F5FBF", "#E76F51", "#2A9D8F", "#E9C46A", "#9D4EDD", "#264653", "#F4A261", "#6C757D"]

LARGURA_PAGINA, ALTURA_PAGINA = landscape(A4)
MARGEM = 1.5 * cm
LARGURA_UTIL = LARGURA_PAGINA - 2 * MARGEM


# ---------------------------------------------------------------------------
# Formatação (padrão brasileiro)
# ---------------------------------------------------------------------------
def _num(v, casas=0):
    s = f"{v:,.{casas}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def _brl(v, casas=2):
    return "-" if v is None or pd.isna(v) else f"R$ {_num(v, casas)}"


def _pct(v, casas=2):
    return "-" if v is None or pd.isna(v) else f"{_num(v, casas)}%"


def _int(v):
    return "-" if v is None or pd.isna(v) else _num(v, 0)


def _formatar_indicador(indicador, v):
    """Célula da tabela 'Distribuição por Produto' conforme a unidade do nome."""
    if pd.isna(v):
        return "-"
    if "(R$)" in indicador:
        return _brl(v)
    if "(%)" in indicador:
        return _pct(v)
    return _int(v)


def _data(d):
    return pd.Timestamp(d).strftime("%d/%m/%Y")


# ---------------------------------------------------------------------------
# Estilos
# ---------------------------------------------------------------------------
def _estilos():
    base = dict(fontName="Helvetica", textColor=colors.HexColor("#222222"))
    return {
        "capa_empresa": ParagraphStyle("capa_empresa", fontName="Helvetica-Bold", fontSize=13, textColor=AZUL_NAGRO, leading=16, spaceAfter=6),
        "capa_titulo": ParagraphStyle("capa_titulo", fontName="Helvetica-Bold", fontSize=30, textColor=AZUL, leading=36, spaceAfter=8),
        "capa_sub": ParagraphStyle("capa_sub", fontName="Helvetica", fontSize=13, textColor=CINZA, leading=18, spaceAfter=18),
        "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=15, textColor=AZUL, leading=19, spaceBefore=2, spaceAfter=3),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11.5, textColor=AZUL, leading=15, spaceBefore=10, spaceAfter=3),
        "txt": ParagraphStyle("txt", leading=11.5, fontSize=8.5, alignment=TA_JUSTIFY, spaceAfter=4, **base),
        "nota": ParagraphStyle("nota", leading=10, fontSize=7.3, textColor=CINZA, fontName="Helvetica", spaceAfter=3, alignment=TA_JUSTIFY),
        "cel": ParagraphStyle("cel", leading=9, fontSize=7.4, **base),
        "cel_b": ParagraphStyle("cel_b", leading=9, fontSize=7.4, fontName="Helvetica-Bold", textColor=colors.HexColor("#222222")),
        "cab": ParagraphStyle("cab", leading=9, fontSize=7.4, fontName="Helvetica-Bold", textColor=colors.white, alignment=TA_CENTER),
        "kpi_t": ParagraphStyle("kpi_t", leading=10, fontSize=7.8, fontName="Helvetica-Bold", textColor=CINZA),
        "kpi_v": ParagraphStyle("kpi_v", leading=16, fontSize=13.5, fontName="Helvetica-Bold", textColor=AZUL),
        "kpi_p": ParagraphStyle("kpi_p", leading=9, fontSize=6.9, fontName="Helvetica", textColor=colors.HexColor("#444444")),
        "bullet": ParagraphStyle("bullet", leading=11.5, fontSize=8.5, leftIndent=10, bulletIndent=0, spaceAfter=3, alignment=TA_JUSTIFY, **base),
    }


# ---------------------------------------------------------------------------
# Blocos de layout
# ---------------------------------------------------------------------------
def _titulo_secao(texto, st):
    return [
        Paragraph(texto, st["h1"]),
        HRFlowable(width="100%", thickness=1.4, color=AZUL_NAGRO, spaceAfter=6),
    ]


def _kpi_cards(cards, st, colunas=5):
    """`cards`: lista de (título, valor formatado, [linhas das categorias])."""
    largura = LARGURA_UTIL / colunas
    linhas = []
    for i in range(0, len(cards), colunas):
        linha = []
        for titulo, valor, partes in cards[i:i + colunas]:
            conteudo = [Paragraph(titulo, st["kpi_t"]), Paragraph(valor, st["kpi_v"])]
            conteudo += [Paragraph(p, st["kpi_p"]) for p in partes]
            linha.append(conteudo)
        linha += [""] * (colunas - len(linha))
        linhas.append(linha)
    t = Table(linhas, colWidths=[largura] * colunas)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.6, CINZA_LINHA),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, CINZA_LINHA),
        ("BACKGROUND", (0, 0), (-1, -1), CINZA_CLARO),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _tabela(df, formatos, st, rotulo_indice="", destacar=None, largura_primeira=0.2, texto_cols=()):
    """Tabela estilizada a partir de um DataFrame.

    `formatos`: {coluna: função de formatação}; colunas fora dele usam str().
    `destacar`: função(rótulo da linha) -> bool, para linhas de total (negrito
    e fundo mais escuro). `texto_cols`: colunas alinhadas à esquerda."""
    dados = [[Paragraph(str(rotulo_indice), st["cab"])] + [Paragraph(str(c), st["cab"]) for c in df.columns]]
    negritos = []
    for n, (idx, linha) in enumerate(df.iterrows(), start=1):
        forte = bool(destacar(idx)) if destacar else False
        if forte:
            negritos.append(n)
        estilo = st["cel_b"] if forte else st["cel"]
        celulas = [Paragraph(str(idx), estilo)]
        for c in df.columns:
            v = linha[c]
            txt = formatos[c](v) if c in formatos else str(v)
            celulas.append(Paragraph(txt, ParagraphStyle(
                f"c{n}{c}", parent=estilo, alignment=0 if c in texto_cols else 2,
            )))
        dados.append(celulas)

    n_cols = len(df.columns)
    primeira = LARGURA_UTIL * largura_primeira
    resto = (LARGURA_UTIL - primeira) / max(n_cols, 1)
    t = Table(dados, colWidths=[primeira] + [resto] * n_cols, repeatRows=1)
    estilos = [
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, CINZA_LINHA),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CINZA_CLARO]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for n in negritos:
        estilos.append(("BACKGROUND", (0, n), (-1, n), DESTAQUE))
    t.setStyle(TableStyle(estilos))
    return t


def _imagem(fig, largura_max=LARGURA_UTIL, altura_max=None):
    """Converte uma figura matplotlib em Image do reportlab (largura ajustada)."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    img = Image(buf)
    escala = largura_max / img.imageWidth
    if altura_max is not None:
        escala = min(escala, altura_max / img.imageHeight)
    img.drawWidth = img.imageWidth * escala
    img.drawHeight = img.imageHeight * escala
    img.hAlign = "CENTER"
    return img


# ---------------------------------------------------------------------------
# Gráficos (matplotlib)
# ---------------------------------------------------------------------------
def _estilo_eixos(ax):
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color("#B8C0C8")
    ax.tick_params(colors="#444444", labelsize=8)
    ax.yaxis.grid(True, color="#E4E8EC", linewidth=0.8)
    ax.set_axisbelow(True)


def _fig_rosquinhas(graficos):
    """`graficos`: lista de (título, {categoria: valor}, formatador do valor)."""
    n = len(graficos)
    fig, eixos = plt.subplots(1, n, figsize=(13.2, 3.9))
    eixos = [eixos] if n == 1 else list(eixos)
    for ax, (titulo, valores, fmt) in zip(eixos, graficos):
        nomes = list(valores.keys())
        vals = [float(v) for v in valores.values()]
        cores = [_PALETA[i % len(_PALETA)] for i in range(len(nomes))]
        total = sum(vals)
        ax.set_title(titulo, fontsize=10, fontweight="bold", color="#1A2B3C", pad=8)
        if total > 0:
            ax.pie(
                vals, colors=cores, startangle=90, counterclock=False,
                wedgeprops=dict(width=0.42, edgecolor="white", linewidth=1.5),
                autopct=lambda p: f"{p:.1f}%".replace(".", ",") if p >= 4 else "",
                pctdistance=0.79, textprops=dict(color="white", fontsize=8, fontweight="bold"),
            )
        else:
            ax.text(0.5, 0.5, "Sem dados", ha="center", va="center", transform=ax.transAxes, color="#6C757D")
        ax.set_aspect("equal")
        legendas = [f"{nome}: {fmt(v)}" for nome, v in zip(nomes, vals)]
        ax.legend(
            [plt.Rectangle((0, 0), 1, 1, color=c) for c in cores], legendas, loc="upper center",
            bbox_to_anchor=(0.5, 0.02), frameon=False, fontsize=7.8, ncol=1,
        )
    fig.tight_layout()
    return fig


def _fig_risco(risco):
    """Barras agrupadas: % da carteira por faixa de atraso, Total + categorias."""
    rotulos = list(risco.keys())
    faixas = risco[rotulos[0]].index.tolist()
    fig, ax = plt.subplots(figsize=(13.2, 3.9))
    n = len(rotulos)
    largura = 0.8 / n
    for i, rot in enumerate(rotulos):
        cor = "#6C757D" if rot == "Total" else _PALETA[(i - 1) % len(_PALETA)]
        vals = risco[rot][f"% da Carteira {rot}"].tolist()
        xs = [k + (i - (n - 1) / 2) * largura for k in range(len(faixas))]
        barras = ax.bar(xs, vals, width=largura * 0.92, color=cor, label=rot)
        for b, v in zip(barras, vals):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{v:.2f}%".replace(".", ","),
                    ha="center", va="bottom", fontsize=7)
    ax.set_xticks(range(len(faixas)))
    ax.set_xticklabels(faixas)
    ax.set_ylabel("% da carteira", fontsize=8.5)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}%".replace(".", ",")))
    _estilo_eixos(ax)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=max(n, 1), frameon=False, fontsize=8)
    ax.margins(y=0.15)
    fig.tight_layout()
    return fig


def _fig_faixas(amount_por_categoria):
    """Barras empilhadas: Amount em aberto por faixa de atraso, por categoria."""
    faixas = amount_por_categoria.index.tolist()
    fig, ax = plt.subplots(figsize=(13.2, 4.0))
    base = [0.0] * len(faixas)
    for i, cat in enumerate(amount_por_categoria.columns):
        vals = amount_por_categoria[cat].astype(float).tolist()
        cor = "#6C757D" if cat == "Sem categoria" else _PALETA[i % len(_PALETA)]
        ax.bar(range(len(faixas)), vals, bottom=base, color=cor, label=cat, width=0.7)
        base = [b + v for b, v in zip(base, vals)]
    topo = max(base) if base else 0
    for k, tot in enumerate(base):
        if tot:
            ax.text(k, tot + topo * 0.012, f"R$ {_num(tot / 1e6, 1)} mi", ha="center", va="bottom", fontsize=7.5)
    ax.set_xticks(range(len(faixas)))
    ax.set_xticklabels([f.split(" - ", 1)[-1] for f in faixas], fontsize=7.5)
    ax.set_xlabel("Faixa de atraso (maior atraso do contrato)", fontsize=8.5)
    ax.set_ylabel("Amount (R$ milhões)", fontsize=8.5)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: _num(v / 1e6, 1)))
    _estilo_eixos(ax)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=max(len(amount_por_categoria.columns), 1),
              frameon=False, fontsize=8)
    ax.margins(y=0.12)
    fig.tight_layout()
    return fig


def _fig_evolucao(evolucao, series, tipos):
    """Linhas do NPL 90 (uma por série x tipo), como no painel."""
    tipos_ordem = ["NPL 90 s/ WO", "NPL 90 c/ WO"]
    tipos = [t for t in tipos_ordem if t in tipos]
    fig, ax = plt.subplots(figsize=(13.2, 3.9))
    mostrar_texto = len(series) * len(tipos) <= 2
    for i, serie in enumerate(series):
        parte = evolucao[evolucao["Série"] == serie]
        for tipo in tipos:
            if len(series) == 1:
                cor, estilo, nome = ("#1F5FBF" if tipo == tipos_ordem[0] else "#6C757D"), "-", tipo
            else:
                cor = _PALETA_SERIES[i % len(_PALETA_SERIES)]
                estilo = "-" if tipo == tipos_ordem[0] else "--"
                nome = f"{serie} — {tipo}"
            ax.plot(parte["Mês"], parte[tipo], estilo, color=cor, linewidth=2.2, marker="o", markersize=4, label=nome)
            if mostrar_texto:
                for x, y in zip(parte["Mês"], parte[tipo]):
                    ax.annotate(f"{y:.1f}%".replace(".", ","), (x, y), textcoords="offset points",
                                xytext=(0, 6), ha="center", fontsize=6.8, color=cor)
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}%"))
    ax.set_ylabel("% do saldo", fontsize=8.5)
    ax.tick_params(axis="x", rotation=45)
    _estilo_eixos(ax)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=max(min(len(series) * len(tipos), 4), 1),
              frameon=False, fontsize=8)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------
LOGO_PATH = Path(__file__).parent / "assets" / "logo_nagro.png"


def _logo(largura=5.2 * cm):
    """Logo da Nagro no topo da capa, alinhada à esquerda (lista vazia se o
    arquivo não existir, para não impedir a geração do relatório)."""
    if not LOGO_PATH.exists():
        return [Spacer(1, 2 * cm)]
    img = Image(str(LOGO_PATH))
    img.drawHeight = largura * img.imageHeight / img.imageWidth
    img.drawWidth = largura
    img.hAlign = "LEFT"
    return [Spacer(1, 0.3 * cm), img]


def _capa(r, filtros, selecao, emitido_em, st):
    carteira = filtros["carteira"]
    periodo = f"{_data(filtros['data_inicio'])} a {_data(filtros['data_fim'])}" if filtros.get("data_inicio") else "Todo o histórico"
    fundos = selecao.get("fundos")
    todos = selecao.get("todos_fundos") or []
    if not fundos or len(fundos) == len(todos):
        txt_fundos = f"Todos ({len(todos)})" if todos else "Todos"
    else:
        txt_fundos = ", ".join(fundos)
    linhas_ev = ", ".join(selecao.get("linhas_evolucao") or []) or "—"
    tipos_ev = ", ".join(selecao.get("tipos_evolucao") or []) or "—"
    produtos = " + ".join(r["produtos"])
    dados = [
        ["Produto(s)", produtos],
        ["Carteira", carteira],
        ["Período de originação", periodo],
        ["Fundos considerados no PDD", txt_fundos],
        ["Evolução do NPL 90 — linhas de crédito", linhas_ev],
        ["Evolução do NPL 90 — tipos de NPL", tipos_ev],
    ]
    tab = Table(
        [[Paragraph(f"<b>{a}</b>", st["cel"]), Paragraph(b, st["cel"])] for a, b in dados],
        colWidths=[7.5 * cm, 17 * cm],
    )
    tab.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, CINZA_LINHA),
        ("BACKGROUND", (0, 0), (0, -1), CINZA_CLARO),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
    ]))
    return [
        *_logo(),
        Spacer(1, 1.6 * cm),
        Paragraph(EMPRESA, st["capa_empresa"]),
        Paragraph(TITULO, st["capa_titulo"]),
        HRFlowable(width="45%", thickness=2.2, color=AZUL_NAGRO, spaceAfter=10, hAlign="LEFT"),
        Paragraph(f"Posição da carteira em {emitido_em:%d/%m/%Y} — emitido às {emitido_em:%H:%M}", st["capa_sub"]),
        Spacer(1, 1.2 * cm),
        Paragraph("Parâmetros do relatório", st["h2"]),
        tab,
        Spacer(1, 0.5 * cm),
        Paragraph(
            "Este documento apresenta os indicadores, gráficos e tabelas do Painel Executivo na data de "
            "emissão, conforme os filtros acima. Os saldos são posições da carteira na data de emissão; o "
            "filtro de período refere-se à data de originação dos contratos. Definições e critérios de "
            "cálculo estão nas Notas Metodológicas, ao final.",
            st["nota"],
        ),
        PageBreak(),
    ]


def _secao_1(r, st):
    categorias = r["categorias"]
    kpis = r["kpis"]

    def valor(ind, cat="Total"):
        return kpis[cat].loc[ind].iloc[0]

    def partes(ind, fmt):
        return [f"{cat}: <b>{fmt(valor(ind, cat))}</b>" for cat in categorias]

    cards = [
        ("Total Concedido", _brl(valor("Total Concedido (R$)")), partes("Total Concedido (R$)", _brl)),
        ("Qtd Contratos Ativos", _int(valor("Contratos Ativos")), partes("Contratos Ativos", _int)),
        ("Qtd Contratos Total", _int(valor("Quantidade de Contratos (Total)")),
         partes("Quantidade de Contratos (Total)", _int)),
        ("Taxa Juros Média (a.m.)", _pct(valor("Taxa de Juros Média (%)")), partes("Taxa de Juros Média (%)", _pct)),
        ("Ticket Médio", _brl(valor("Ticket Médio (R$)")), partes("Ticket Médio (R$)", _brl)),
        ("Total Concedido da Carteira Ativa", _brl(valor("Total Concedido da Carteira Ativa (R$)")),
         partes("Total Concedido da Carteira Ativa (R$)", _brl)),
        ("Saldo da Carteira Ativa", _brl(valor("Saldo da Carteira Ativa (R$)")),
         partes("Saldo da Carteira Ativa (R$)", _brl)),
        ("Total Recebido", _brl(valor("Total Recebido (R$)")), partes("Total Recebido (R$)", _brl)),
        ("NPL 90", _pct(valor("NPL 90 (%)")), partes("NPL 90 (%)", _pct)),
        ("NPL 90 + WO", _pct(valor("NPL 90 + WO (%)")), partes("NPL 90 + WO (%)", _pct)),
    ]
    n_cat = ", ".join(f"{c}: {_int(r['n_por_categoria'][c])}" for c in categorias)
    fluxo = _titulo_secao("1. Visão Geral da Carteira", st)
    fluxo.append(Paragraph(
        f"{_int(r['n_total'])} contratos no recorte ({_int(r['n_ccb'])} CCB e {_int(r['n_cpr'])} CPR)"
        + (f". Por categoria — {n_cat}." if categorias else "."),
        st["nota"],
    ))
    fluxo.append(_kpi_cards(cards, st))
    fluxo.append(Paragraph(
        "Nota: o Saldo da Carteira Ativa corresponde ao valor integral (principal e juros) das parcelas em "
        "aberto; o Total Concedido da Carteira Ativa considera apenas o principal dessas mesmas parcelas. "
        "NPL 90 e NPL 90 + WO sempre consideram a carteira completa do(s) produto(s) selecionado(s).",
        st["nota"],
    ))
    if categorias:
        graficos = [
            ("Total Recebido", {c: valor("Total Recebido (R$)", c) for c in categorias}, _brl0),
            ("Contratos Ativos", {c: valor("Contratos Ativos", c) for c in categorias}, _int),
            ("Saldo da Carteira Ativa", {c: valor("Saldo da Carteira Ativa (R$)", c) for c in categorias}, _brl0),
            ("Total Concedido da Carteira Ativa",
             {c: valor("Total Concedido da Carteira Ativa (R$)", c) for c in categorias}, _brl0),
        ]
        fluxo.append(Spacer(1, 6))
        fluxo.append(_imagem(_fig_rosquinhas(graficos), altura_max=8.2 * cm))
    return fluxo


def _brl0(v):
    return _brl(v, 0)


def _secao_2(r, st, varios_produtos):
    categorias = r["categorias"]
    kpis = r["kpis"]
    colunas = [kpis["Total"]] + [kpis[c] for c in categorias]
    if varios_produtos:
        colunas += [r["kpis_linhas"][linha] for linha in r["linhas"]]
    distribuicao = pd.concat(colunas, axis=1)
    fmt = distribuicao.apply(
        lambda linha: [_formatar_indicador(linha.name, v) for v in linha], axis=1, result_type="expand",
    )
    fmt.columns = distribuicao.columns
    fmt = fmt.rename(index={
        "Contratos Ativos": "Qtd Contratos Ativos",
        "Quantidade de Contratos (Total)": "Qtd Contratos Total",
    })
    produtos = r["produtos"]
    if varios_produtos:
        legenda = ("A tabela detalha os principais indicadores da carteira, segmentando entre o total, cada "
                   "produto (CCB e CPR) e cada linha de crédito (App, Crédito Produtor e tipos de CPR).")
    elif produtos == ["CCB"]:
        legenda = ("A tabela detalha os principais indicadores da carteira, segmentando entre o total, "
                   "operações via aplicativo (App) e crédito para produtor (Crédito Produtor).")
    else:
        legenda = ("A tabela detalha os principais indicadores da carteira, segmentando entre o total e cada "
                   "tipo de produto CPR.")
    return [KeepTogether(
        _titulo_secao("2. Distribuição por Produto", st)
        + [Paragraph(legenda, st["nota"]),
           _tabela(fmt, {c: str for c in fmt.columns}, st, rotulo_indice="Indicador", largura_primeira=0.22)]
    )]


def _secao_3(r, pdd, st, selecao, varios_produtos, prog=lambda f, t: None):
    categorias = r["categorias"]
    risco = r["risco"]
    npl = r["npl"]
    produto_label = " + ".join(r["produtos"])
    fluxo = _titulo_secao("3. Indicadores de Risco", st)

    # --- Indicadores de risco (inadimplência canônica) ---
    chaves = ["Total"] + list(categorias)
    prog(0.33, "Montando indicadores de risco")
    fluxo.append(KeepTogether([
        Paragraph("3.1 Indicadores de Risco por Carteira (%)", st["h2"]),
        Paragraph(
            "Percentual da carteira (saldo em aberto ÷ saldo total contratado) em cada faixa de atraso (FPD, "
            "15+, 30+, 60+ e 90+ dias), comparando o total com cada categoria. Segue o filtro de Carteira.",
            st["nota"],
        ),
        _imagem(_fig_risco({k: risco[k] for k in chaves}), altura_max=8.2 * cm),
    ]))
    risco_tabela = pd.concat([risco["Total"]] + [risco[c] for c in categorias], axis=1)
    fluxo.append(Spacer(1, 4))
    fluxo.append(_tabela(
        risco_tabela, {c: (lambda v: _num(v, 2)) for c in risco_tabela.columns}, st,
        rotulo_indice="Faixa de atraso", largura_primeira=0.16,
    ))
    fluxo.append(Spacer(1, 3))
    fluxo.append(Paragraph(
        f"As seções seguintes consideram a carteira completa de {produto_label} (em aberto e write-off), "
        "independentemente do filtro de Carteira.", st["nota"],
    ))

    # --- Faixas de atraso ---
    faixas, faixas_amount = r["faixas_atraso"], r["faixas_atraso_amount"]
    prog(0.42, "Montando faixas de atraso")
    bloco = [
        Paragraph("3.2 Faixas de atraso", st["h2"]),
        Paragraph(
            "Carteira com saldo em aberto distribuída pela faixa do maior atraso de cada contrato. 'Amount' é o "
            f"valor integral das parcelas em aberto; 'Principal' é a parte de principal dessas parcelas. Faixas "
            f"acima de {WO} dias correspondem a write-off.", st["nota"]),
        _imagem(_fig_faixas(faixas_amount), altura_max=8.4 * cm),
    ]
    fluxo.append(KeepTogether(bloco))
    fmt_faixas = {c: _brl0 for c in faixas.columns if c not in ("Qtde", "%")}
    fmt_faixas.update({"Qtde": _int, "%": lambda v: _pct(v, 1)})
    fluxo.append(Spacer(1, 4))
    fluxo.append(_tabela(
        faixas, fmt_faixas, st, rotulo_indice="Faixa de atraso",
        destacar=lambda i: str(i) == str(faixas.index[-1]), largura_primeira=0.15,
    ))

    # --- NPL ---
    bloco_npl = [Paragraph("3.3 Inadimplência — NPL 90 e NPL 30", st["h2"])]
    bloco_npl.append(Paragraph(
        "NPL calculado sobre o saldo devedor (valor integral das parcelas em aberto), em nível de contrato: se o "
        f"maior atraso do contrato é igual ou superior a N dias, o saldo inteiro dele compõe o NPL N. 'Sem WO': "
        f"numerador = saldo com atraso de N a {WO} dias; denominador = saldo sem write-off. 'Com WO': o saldo em "
        f"write-off (atraso superior a {WO} dias) entra no numerador e no denominador.", st["nota"],
    ))
    prog(0.50, "Montando NPL 90 e NPL 30")
    cards_npl = [
        ("NPL 90 (sem WO)", _pct(npl["npl_90"]), [f"{_brl(npl['atraso_90_360'], 0)} com atraso de 90 a {WO} dias"]),
        ("NPL 30 (sem WO)", _pct(npl["npl_30"]), [f"{_brl(npl['atraso_30_360'], 0)} com atraso de 30 a {WO} dias"]),
        ("NPL 90 c/ WO", _pct(npl["npl_90_wo"]), [f"Inclui WO de {_brl(npl['wo'], 0)}"]),
        ("NPL 30 c/ WO", _pct(npl["npl_30_wo"]), [f"Inclui WO de {_brl(npl['wo'], 0)}"]),
    ]
    bloco_npl.append(_kpi_cards(cards_npl, st, colunas=4))
    npl_cat = r["npl_tabela"].reset_index().rename(columns={
        "Produto": "Produto / Linha de crédito",
        "saldo_total": "Saldo (amount)", "atraso_30_360": f"Atraso 30-{WO}d",
        "atraso_90_360": f"Atraso 90-{WO}d", "wo": f"WO > {WO}d",
        "npl_30": "NPL 30", "npl_90": "NPL 90", "npl_30_wo": "NPL 30 c/ WO", "npl_90_wo": "NPL 90 c/ WO",
    }).drop(columns=["saldo_sem_wo"]).set_index("Produto / Linha de crédito")
    fmt_npl = {c: (_pct if c.startswith("NPL") else _brl0) for c in npl_cat.columns}
    bloco_npl.append(Spacer(1, 5))
    bloco_npl.append(_tabela(
        npl_cat, fmt_npl, st, rotulo_indice="Produto / Linha de crédito",
        destacar=lambda i: str(i).startswith("Total"), largura_primeira=0.2,
    ))
    bloco_npl.append(Spacer(1, 3))
    bloco_npl.append(Paragraph(
        "O saldo (amount) inclui o write-off. NPL sem WO = atraso ÷ (saldo − WO); NPL com WO = (atraso + WO) ÷ saldo.",
        st["nota"],
    ))
    fluxo.append(KeepTogether(bloco_npl))

    # --- Evolução ---
    prog(0.58, "Montando evolução do NPL 90")
    bloco_ev = [
        Paragraph("3.4 Evolução do NPL 90 — desde Jan/25", st["h2"]),
        Paragraph(
            "NPL 90 no fim de cada mês, sem e com write-off, reconstruído a partir das datas de vencimento e "
            "pagamento das parcelas e da vigência das renegociações; o último ponto é a data de emissão.",
            st["nota"],
        ),
    ]
    sel_linhas, sel_tipos = selecao.get("linhas_evolucao"), selecao.get("tipos_evolucao")
    if sel_linhas and sel_tipos:
        bloco_ev.append(_imagem(_fig_evolucao(r["evolucao_npl90"], sel_linhas, sel_tipos), altura_max=8.2 * cm))
    else:
        bloco_ev.append(Paragraph("Nenhuma série selecionada para o gráfico de evolução.", st["txt"]))
    fluxo.append(KeepTogether(bloco_ev))

    # --- PDD ---
    prog(0.68, "Montando PDD")
    bloco_pdd = [Paragraph("3.5 PDD — Provisão para Devedores Duvidosos", st["h2"])]
    bloco_pdd.append(Paragraph(
        "Provisão calculada com a régua de cada fundo: Ghia (tabela da Ghia, pelo maior atraso do devedor na "
        "Ghia), Kanastra (escala própria, pelo maior atraso do cliente em toda a CCB), Oikos (régua do FIAGRO, "
        "pelo maior atraso do contrato) e demais fundos (Resolução CMN 2.682, pelo maior atraso do contrato). O "
        "percentual da faixa incide sobre todo o saldo em aberto (amount), inclusive parcelas a vencer.",
        st["nota"],
    ))
    if pdd is None:
        bloco_pdd.append(Paragraph("Nenhum fundo selecionado para o cálculo da PDD.", st["txt"]))
        fluxo.append(KeepTogether(bloco_pdd))
    else:
        cards_pdd = [
            ("PDD total", _brl(pdd["total"]), [f"{_pct(pdd['pct'])} do saldo em aberto"]),
        ]
        bloco_pdd.append(_kpi_cards(cards_pdd, st, colunas=5))
        bloco_pdd.append(Spacer(1, 5))
        tf = pdd["fundos"]
        bloco_pdd.append(_tabela(
            tf, {"Contratos": _int, "Saldo": _brl0, "% PDD": _pct, "Provisão": _brl0}, st,
            rotulo_indice="Fundo", destacar=lambda i: str(i) == "Total", largura_primeira=0.2,
            texto_cols=("Régua",),
        ))
        fluxo.append(KeepTogether(bloco_pdd))
        for regua, tabela in pdd["faixas"].items():
            fluxo.append(KeepTogether([
                Paragraph(f"Detalhe por faixa — {PDD_UNIDADE_CURTA[regua]}", st["h2"]),
                Paragraph(PDD_UNIDADE[regua] + ".", st["nota"]),
                _tabela(
                    tabela,
                    {"Contratos": _int, "Devedores": _int, "Saldo": _brl0, "% PDD": _pct, "Provisão": _brl0},
                    st, rotulo_indice=PDD_UNIDADE[regua], destacar=lambda i: str(i) == "Total",
                    largura_primeira=0.34,
                ),
            ]))
    return fluxo


def _notas_metodologicas(st):
    itens = [
        ("Fonte e posição.", "Dados do Sistema de Gestão de Crédito (SGC), tabelas de contratos (CCB e CPR), "
         "parcelas e dados do cliente, na data de emissão. Renegociações são consolidadas no contrato original "
         "(raiz), de modo que o valor concedido nunca é contado mais de uma vez. O produto CPR "
         "'Antecipação Recebiveis' não integra o painel."),
        ("Write-off.", f"Contratos com maior atraso superior a {WO} dias são classificados como write-off. A "
         f"carteira em aberto compreende contratos não quitados com atraso de até {WO} dias."),
        ("Saldo da Carteira Ativa e Total Concedido da Carteira Ativa.", "O saldo corresponde ao valor integral "
         "(principal e juros) das parcelas ainda em aberto; o Total Concedido da Carteira Ativa corresponde apenas "
         "ao principal dessas parcelas."),
        ("NPL.", "Razão entre o saldo devedor dos contratos com atraso mínimo de N dias (N = 30 ou 90) e o saldo "
         "devedor da carteira, em nível de contrato. A versão 'sem WO' exclui o write-off do numerador e do "
         "denominador; a versão 'com WO' o inclui em ambos."),
        ("Inadimplência por faixa (item 3.1).", "Saldo em atraso dividido pelo saldo total contratado (pago e em "
         "aberto), distinta do NPL, cujo denominador é o saldo devedor."),
        ("PDD.", "Calculada por contrato, conforme a régua do fundo detentor (portfolio da última parcela do "
         "contrato): Ghia, Kanastra, Oikos (inclui Oikos Warehouse) e Resolução CMN 2.682 para os demais. Valores "
         "calculados sobre o saldo nominal (amount) das parcelas em aberto, sem desconto a valor presente."),
        ("Evolução do NPL 90.", "Série histórica mensal desde janeiro de 2025, reconstruída com a vigência das "
         "renegociações; o ponto final corresponde à data de emissão e coincide com o indicador NPL 90 da seção 1."),
    ]
    fluxo = _titulo_secao("Notas Metodológicas", st)
    for titulo, texto in itens:
        fluxo.append(Paragraph(f"<b>{titulo}</b> {texto}", st["bullet"], bulletText="•"))
    return fluxo


# ---------------------------------------------------------------------------
# Cabeçalho / rodapé
# ---------------------------------------------------------------------------
def _decorar_pagina(emitido_em):
    def desenhar(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(CINZA_LINHA)
        canvas.setLineWidth(0.6)
        canvas.line(MARGEM, ALTURA_PAGINA - 1.15 * cm, LARGURA_PAGINA - MARGEM, ALTURA_PAGINA - 1.15 * cm)
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(AZUL_NAGRO)
        canvas.drawString(MARGEM, ALTURA_PAGINA - 0.95 * cm, EMPRESA)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(CINZA)
        canvas.drawRightString(LARGURA_PAGINA - MARGEM, ALTURA_PAGINA - 0.95 * cm, TITULO)
        canvas.line(MARGEM, 1.1 * cm, LARGURA_PAGINA - MARGEM, 1.1 * cm)
        canvas.drawString(MARGEM, 0.7 * cm, f"Emitido em {emitido_em:%d/%m/%Y às %H:%M} — informações gerenciais")
        canvas.drawRightString(LARGURA_PAGINA - MARGEM, 0.7 * cm, f"Página {doc.page}")
        canvas.restoreState()
    return desenhar


def _decorar_capa(emitido_em):
    def desenhar(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(AZUL)
        canvas.rect(0, 0, 0.9 * cm, ALTURA_PAGINA, stroke=0, fill=1)
        canvas.setFillColor(AZUL_NAGRO)
        canvas.rect(0.9 * cm, 0, 0.25 * cm, ALTURA_PAGINA, stroke=0, fill=1)
        canvas.restoreState()
    return desenhar


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def gerar_pdf_painel_executivo(r, filtros, selecao, pdd, emitido_em=None, progresso=None):
    """Monta o PDF do Painel Executivo e devolve os bytes.

    `r`: dicionário de `calcular_indicadores_executivo` (o mesmo da tela).
    `filtros`: {'carteira', 'data_inicio', 'data_fim'} -- produtos vêm de `r`.
    `selecao`: escolhas feitas no meio da aba -- {'linhas_evolucao',
      'tipos_evolucao', 'fundos', 'todos_fundos'}.
    `pdd`: resultado de `resumir_pdd` para os fundos selecionados (ou None).
    `progresso`: função opcional `progresso(fração 0-1, texto)` chamada a cada
    etapa (alimenta a barra de progresso da tela)."""
    prog = progresso or (lambda fracao, texto: None)
    prog(0.02, "Preparando o relatório")
    emitido_em = emitido_em or datetime.now()
    st = _estilos()
    varios_produtos = len(r["produtos"]) > 1

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=landscape(A4), leftMargin=MARGEM, rightMargin=MARGEM, topMargin=1.6 * cm, bottomMargin=1.5 * cm,
        title=f"{TITULO} — {emitido_em:%d/%m/%Y}", author=EMPRESA, subject="Painel Executivo",
    )
    frame_capa = Frame(2.2 * cm, 1.5 * cm, LARGURA_PAGINA - 4 * cm, ALTURA_PAGINA - 3 * cm, id="capa")
    frame = Frame(MARGEM, 1.5 * cm, LARGURA_UTIL, ALTURA_PAGINA - 3.1 * cm, id="corpo")
    doc.addPageTemplates([
        PageTemplate(id="capa", frames=[frame_capa], onPage=_decorar_capa(emitido_em)),
        PageTemplate(id="corpo", frames=[frame], onPage=_decorar_pagina(emitido_em)),
    ])

    historia = [NextPageTemplate("corpo")]
    historia += _capa(r, filtros, selecao, emitido_em, st)
    prog(0.06, "Montando visão geral e gráficos")
    historia += _secao_1(r, st)
    historia.append(Spacer(1, 14))
    prog(0.26, "Montando distribuição por produto")
    historia += _secao_2(r, st, varios_produtos)
    historia.append(PageBreak())
    historia += _secao_3(r, pdd, st, selecao, varios_produtos, prog)
    historia.append(PageBreak())
    historia += _notas_metodologicas(st)
    prog(0.78, "Paginando o documento")
    doc.build(historia)
    prog(1.0, "Relatório pronto")
    return buf.getvalue()
