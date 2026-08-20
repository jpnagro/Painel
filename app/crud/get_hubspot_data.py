import time
from pathlib import Path

import pandas as pd
import requests

try:
    # Execução via `python -m app.crud.get_hubspot_data` (raiz do repo no sys.path)
    from app.core.config import ACCESS_TOKEN, BASE_URL_CRM, PIPELINE_ID
except ImportError:
    # Importado de dentro do Streamlit (app/ é a raiz do sys.path nesse contexto)
    from core.config import ACCESS_TOKEN, BASE_URL_CRM, PIPELINE_ID

BASE_DIR = Path(__file__).resolve().parents[2]
CSV_PATH = BASE_DIR / "hubspot_deals_credito_simplificado.csv"

HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json",
}

INTERNAL_PROPERTIES = [
    "rating_nagro_4_0",
    "score_nagro_4_0",
    "carteira_ativa_total",
    "numero_interno_do_contrato",
    "cnpj_cpf__unico_",
    "createdate",
]

FIELD_MAP = {
    "Rating Nagro 4.0": "rating_nagro_4_0",
    "Score Nagro 4.0": "score_nagro_4_0",
    "Carteira ativa total": "carteira_ativa_total",
    "Numero interno do contrato": "numero_interno_do_contrato",
    "CNPJ/CPF (único)": "cnpj_cpf__unico_",
    "Data consulta": "createdate",
}


def fetch_deals_by_pipeline(pipeline_id, properties, page_size=200, extra_filters=None):
    url = f"{BASE_URL_CRM}/crm/v3/objects/deals/search"
    all_results = []
    last_id = None

    base_filters = [
        {"propertyName": "pipeline", "operator": "EQ", "value": pipeline_id},
        {"propertyName": "rating_nagro_4_0", "operator": "HAS_PROPERTY"},
    ]
    if extra_filters:
        base_filters.extend(extra_filters)

    while True:
        filters = list(base_filters)
        if last_id is not None:
            filters.append({"propertyName": "hs_object_id", "operator": "GT", "value": last_id})

        after = None
        fetched_in_slice = 0
        slice_ended = False

        while True:
            payload = {
                "filterGroups": [{"filters": filters}],
                "properties": properties,
                "limit": page_size,
                "sorts": [{"propertyName": "hs_object_id", "direction": "ASCENDING"}],
            }
            if after:
                payload["after"] = after

            resp = requests.post(url, headers=HEADERS, json=payload)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            all_results.extend(results)
            fetched_in_slice += len(results)

            if results:
                last_id = results[-1]["id"]

            time.sleep(1)

            next_after = data.get("paging", {}).get("next", {}).get("after")
            if not next_after:
                slice_ended = True  # acabou de verdade
                break
            if fetched_in_slice >= 10000:
                break  # reabre com hs_object_id > last_id

            after = next_after

        if slice_ended:
            break

    return all_results


def deals_to_dataframe(deals):
    rows = []
    for deal in deals:
        props = deal.get("properties", {})
        row = {"deal_id": deal.get("id"), "dealname": props.get("dealname")}
        for label, internal in FIELD_MAP.items():
            row[label] = props.get(internal)
        rows.append(row)
    return pd.DataFrame(rows, columns=["deal_id", "dealname", *FIELD_MAP.keys()])


def load_existing_csv():
    if not CSV_PATH.exists():
        return None
    df = pd.read_csv(CSV_PATH, dtype={"deal_id": str})
    return df if not df.empty else None


def build_incremental_filter(existing_df):
    """Filtra no CRM apenas deals criados após o mais recente já presente no CSV."""
    last_date = pd.to_datetime(existing_df["Data consulta"], errors="coerce", utc=True).max()
    if pd.isna(last_date):
        return None
    epoch_ms = round(last_date.timestamp() * 1000)
    return [{"propertyName": "createdate", "operator": "GT", "value": str(epoch_ms)}], last_date


def update_hubspot_csv():
    existing_df = load_existing_csv()

    extra_filters = None
    if existing_df is not None:
        result = build_incremental_filter(existing_df)
        if result is not None:
            extra_filters, last_date = result
            print(f"CSV existente encontrado ({len(existing_df)} deals). "
                  f"Buscando apenas deals criados após {last_date} (fetch incremental)...")
        else:
            print("CSV existente encontrado, mas sem datas válidas — fazendo fetch completo.")
    else:
        print("Nenhum CSV existente encontrado — fazendo fetch completo.")

    deals = fetch_deals_by_pipeline(PIPELINE_ID, INTERNAL_PROPERTIES, extra_filters=extra_filters)
    new_df = deals_to_dataframe(deals)
    print(f"{len(new_df)} novo(s) deal(s) encontrado(s) no CRM.")

    if existing_df is not None:
        if not new_df.empty:
            new_df["deal_id"] = new_df["deal_id"].astype(str)
        combined = pd.concat([existing_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset="deal_id", keep="last")
    else:
        combined = new_df

    combined["_sort_date"] = pd.to_datetime(combined["Data consulta"], errors="coerce", utc=True)
    combined = combined.sort_values("_sort_date").drop(columns="_sort_date").reset_index(drop=True)

    combined.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
    print(f"CSV atualizado: {CSV_PATH} ({len(combined)} deals no total)")
    return combined


if __name__ == "__main__":
    update_hubspot_csv()
