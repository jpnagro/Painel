import warnings
from os import getenv
from pathlib import Path

import pandas as pd
import psycopg2
import streamlit as st
from dotenv import find_dotenv, load_dotenv

from crud.monitoramento.scoring import prob_to_score, score_to_prob

warnings.filterwarnings("ignore")

load_dotenv(find_dotenv(raise_error_if_not_found=False))

URL_PG = getenv("URL_PG")

BASE_DIR = Path(__file__).resolve().parents[3]
EXCEL_PATH = BASE_DIR / "data" / "ccb_test.xlsx"


@st.cache_data(ttl=3600, show_spinner=False)
def load_reference_data() -> pd.DataFrame:
    df = pd.read_excel(EXCEL_PATH)
    df = df.sort_values("createdAt", ascending=False)
    df["score_novo"] = df["prob"].apply(prob_to_score)
    if "rating_novo" in df.columns:
        df["rating_novo"] = df["rating_novo"].str.strip()
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_current_data(start_date: str, end_date: str) -> pd.DataFrame:
    query = f"""
        SELECT il."operationCode", cd."rating_v4", cd."score_v4",
               MAX(CASE WHEN il."delay" > 90 AND il."paid" IS NOT TRUE
                        THEN 1 ELSE 0 END) AS target
        FROM installments il
        LEFT JOIN client_data cd ON il."operationCode" = cd."ccbCode"
        WHERE il.renegotiation IS NOT TRUE
          AND il.renegotiated IS NOT TRUE
          AND il."releaseDate" >= '{start_date}'
          AND il."releaseDate" <  '{end_date}'
        GROUP BY il."operationCode", cd."rating_v4", cd."score_v4";
    """
    with psycopg2.connect(URL_PG) as conn:
        df = pd.read_sql(query, conn)
    df["operationCode"] = df["operationCode"].astype(str).str.replace("R", "", regex=False)
    df["rating_v4"] = df["rating_v4"].str.strip()
    df["prob"] = df["score_v4"].apply(score_to_prob)
    df = df.dropna(subset=["prob"])
    return df
