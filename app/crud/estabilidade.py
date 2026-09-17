import numpy as np
import pandas as pd
import streamlit as st
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
CSV_PATH = BASE_DIR / "hubspot_deals_credito_simplificado.csv"

RATING_COL = "Rating Nagro 4.0"
DATE_COL = "Data consulta"

CATEGORIES = ["AA", "A", "B", "C", "D", "E", "F", "G", "H"]
REFERENCE_PERIOD = pd.Period("2025-06", freq="M")
REFERENCE_LABEL = "Referência - Jun/25"
ALERT_THRESHOLD = 0.1

MONTH_NAMES_PT = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}


def month_label(period):
    return f"{MONTH_NAMES_PT[period.month]}/{period.year}"


@st.cache_data
def load_deals(csv_path):
    df = pd.read_csv(csv_path)
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce", utc=True).dt.tz_convert(None)
    df = df.dropna(subset=[DATE_COL, RATING_COL])
    df["Safra"] = df[DATE_COL].dt.to_period("M")
    return df


def reference_table(df):
    ref_df = df[df["Safra"] == REFERENCE_PERIOD]
    qtde = ref_df[RATING_COL].value_counts().reindex(CATEGORIES, fill_value=0)
    total = qtde.sum()
    pct = qtde / total
    pct_acum = pct.cumsum()
    return qtde, pct, pct_acum, total


def build_month_table(month_qtde, month_total, ref_qtde, ref_pct, ref_pct_acum):
    month_pct = month_qtde / month_total
    month_pct_acum = month_pct.cumsum()

    with np.errstate(divide="ignore", invalid="ignore"):
        psi_raw = (ref_pct - month_pct) * np.log(ref_pct / month_pct)
    psi_valid = psi_raw.replace([np.inf, -np.inf], np.nan)

    ks = (ref_pct_acum - month_pct_acum).abs()

    table = pd.DataFrame({
        "Rating": CATEGORIES,
        "Qtde Ref.": ref_qtde.values,
        "% Part. Ref.": ref_pct.values,
        "% Acum. Ref.": ref_pct_acum.values,
        "Qtde Mês": month_qtde.values,
        "% Part. Mês": month_pct.values,
        "% Acum. Mês": month_pct_acum.values,
        "PSI": psi_valid.values,
        "KS1": ks.values,
    })

    total_psi = psi_valid.sum(skipna=True)
    total_ks = ks.max()

    total_row = pd.DataFrame([{
        "Rating": "Total",
        "Qtde Ref.": ref_qtde.sum(),
        "% Part. Ref.": ref_pct.sum(),
        "% Acum. Ref.": np.nan,
        "Qtde Mês": month_qtde.sum(),
        "% Part. Mês": month_pct.sum(),
        "% Acum. Mês": np.nan,
        "PSI": total_psi,
        "KS1": total_ks,
    }])

    table = pd.concat([table, total_row], ignore_index=True)

    status_psi = "Atenção - Acima 10%" if total_psi >= ALERT_THRESHOLD else "Ok"
    status_ks = "Atenção - Acima 10%" if total_ks >= ALERT_THRESHOLD else "Ok"

    return table, total_psi, total_ks, status_psi, status_ks


def style_table(table):
    fmt = {
        "Qtde Ref.": "{:,.0f}",
        "Qtde Mês": "{:,.0f}",
        "% Part. Ref.": "{:.2%}",
        "% Acum. Ref.": "{:.2%}",
        "% Part. Mês": "{:.2%}",
        "% Acum. Mês": "{:.2%}",
        "PSI": "{:.4f}",
        "KS1": "{:.4f}",
    }
    return table.style.format(fmt, na_rep="-").set_properties(
        subset=pd.IndexSlice[table.index[-1:], :], **{"font-weight": "bold"}
    )


@st.fragment
def _render_estabilidade_body():
    st.title("Análise de Estabilidade — Rating Nagro 4.0")
    st.caption(
        "PSI (Population Stability Index) e KS1, comparando a distribuição de rating de cada safra "
        "mensal (a partir de Jul/25) contra a safra de referência de Jun/25."
    )

    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        atualizar = st.button("🔄 Atualizar dados do CRM", key="est_refresh_crm")
    with col_info:
        if CSV_PATH.exists():
            st.caption(f"Última atualização do arquivo: {pd.Timestamp.fromtimestamp(CSV_PATH.stat().st_mtime).strftime('%d/%m/%Y %H:%M')}")

    if atualizar:
        with st.spinner("Buscando deals atualizados no HubSpot (pode levar alguns minutos)..."):
            try:
                from crud.get_hubspot_data import update_hubspot_csv
                combined = update_hubspot_csv()
                load_deals.clear()
                st.success(f"Dados atualizados com sucesso! {len(combined):,} deals no total.")
            except Exception as exc:
                st.error(f"Erro ao atualizar dados do CRM: {exc}")

    if not CSV_PATH.exists():
        st.info(
            "Os dados de rating do CRM (HubSpot) ainda não foram carregados nesta instalação. "
            "Clique no botão abaixo para buscá-los — isso pode levar alguns minutos. (Os dados não "
            "são carregados automaticamente para não deixar a página lenta quando ninguém precisa dela.)"
        )
        if st.button("📥 Carregar dados do HubSpot", key="est_carregar_inicial"):
            with st.spinner("Buscando deals no HubSpot (pode levar alguns minutos)..."):
                try:
                    from crud.get_hubspot_data import update_hubspot_csv
                    combined = update_hubspot_csv()
                    load_deals.clear()
                    st.success(f"Dados buscados com sucesso! {len(combined):,} deals no total.")
                except Exception as exc:
                    st.error(f"Não foi possível buscar os dados do CRM: {exc}")
                    st.stop()
        else:
            st.stop()

    if not CSV_PATH.exists():
        st.error(f"Arquivo não encontrado: {CSV_PATH}")
        st.stop()

    df = load_deals(CSV_PATH)

    ref_qtde, ref_pct, ref_pct_acum, ref_total = reference_table(df)

    if ref_total == 0:
        st.error(f"Nenhum deal encontrado para a safra de referência ({month_label(REFERENCE_PERIOD)}) no CSV.")
        st.stop()

    available_months = sorted(p for p in df["Safra"].unique() if p >= pd.Period("2025-07", freq="M"))

    if not available_months:
        st.warning("Nenhuma safra a partir de Jul/25 encontrada no CSV.")
        st.stop()

    with st.expander("Safra de referência — Jun/25", expanded=False):
        st.caption(
            "Base fixa contra a qual todas as safras seguintes são comparadas. 'Qtde' = nº de deals "
            "com aquele rating em junho/2025 (fonte: CSV do HubSpot). '% Part.' = Qtde ÷ total da "
            "safra. '% Acum.' = soma das participações do melhor rating (AA) até aquela linha."
        )
        ref_display = pd.DataFrame({
            "Rating": CATEGORIES,
            "Qtde": ref_qtde.values,
            "% Part.": ref_pct.values,
            "% Acum.": ref_pct_acum.values,
        })
        st.dataframe(
            ref_display.style.format({"Qtde": "{:,.0f}", "% Part.": "{:.2%}", "% Acum.": "{:.2%}"}),
            hide_index=True,
            width="stretch",
        )
        st.caption(f"Total da referência: {ref_total:,.0f} deals")

    summary_rows = []

    tables_by_month = {}
    for period in available_months:
        month_df = df[df["Safra"] == period]
        month_qtde = month_df[RATING_COL].value_counts().reindex(CATEGORIES, fill_value=0)
        month_total = month_qtde.sum()

        if month_total == 0:
            continue

        table, total_psi, total_ks, status_psi, status_ks = build_month_table(
            month_qtde, month_total, ref_qtde, ref_pct, ref_pct_acum
        )
        tables_by_month[period] = table
        summary_rows.append({
            "Safra": month_label(period),
            "Qtde": int(month_total),
            "PSI": total_psi,
            "KS1": total_ks,
            "Status PSI": status_psi,
            "Status KS1": status_ks,
        })

    st.subheader(
        "Resumo por safra",
        help="Uma linha por mês (a partir de jul/2025), comparando a distribuição de rating daquele "
        "mês contra a safra de referência (jun/2025). PSI = soma, em todos os ratings, de "
        "(%participação referência − %participação do mês) × ln(%ref ÷ %mês) — mede se a 'forma' da "
        "distribuição mudou. KS1 = maior diferença absoluta entre o % acumulado da referência e o do "
        "mês, olhando rating a rating. Status 'Atenção' quando PSI ou KS1 ≥ 0,10 (10%).",
    )
    summary_df = pd.DataFrame(summary_rows)
    st.dataframe(
        summary_df.style.format({"Qtde": "{:,.0f}", "PSI": "{:.4f}", "KS1": "{:.4f}"}),
        hide_index=True,
        width="stretch",
    )

    st.divider()
    st.subheader(
        "Tabelas detalhadas por safra",
        help="Abra um mês para ver a comparação rating a rating contra a referência: quantidade, % "
        "de participação e % acumulado do mês lado a lado com os da referência, e a contribuição de "
        "PSI/KS1 de cada rating individual (não só o total).",
    )

    for period in available_months:
        if period not in tables_by_month:
            continue

        table = tables_by_month[period]
        total_psi = table.iloc[-1]["PSI"]
        total_ks = table.iloc[-1]["KS1"]
        status_psi = "Atenção - Acima 10%" if total_psi >= ALERT_THRESHOLD else "Ok"
        status_ks = "Atenção - Acima 10%" if total_ks >= ALERT_THRESHOLD else "Ok"

        with st.expander(f"{month_label(period)}  —  PSI: {total_psi:.4f} ({status_psi})  |  KS1: {total_ks:.4f} ({status_ks})", expanded=False):
            st.dataframe(style_table(table), hide_index=True, width="stretch")
            col1, col2 = st.columns(2)
            col1.metric(
                "Status PSI", status_psi, f"{total_psi:.4f}",
                help="PSI do mês contra a safra de referência (jun/2025) — ver fórmula no cabeçalho "
                "'Resumo por safra'. ≥ 0,10 dispara 'Atenção'.",
            )
            col2.metric(
                "Status KS1", status_ks, f"{total_ks:.4f}",
                help="KS1 do mês contra a safra de referência (jun/2025) — maior diferença absoluta "
                "entre % acumulados, rating a rating. ≥ 0,10 dispara 'Atenção'.",
            )


def render_estabilidade():
    """Roda em `st.fragment`: mexer em qualquer filtro/botão aqui só
    reprocessa esta aba, sem esmaecer o app inteiro."""
    _render_estabilidade_body()
