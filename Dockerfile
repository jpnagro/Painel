# Painel Nagro — Crédito (Streamlit) para o Cloud Run.
# Python 3.14: o requirements fixa pandas 3 / numpy 2.5, que exigem Python >= 3.12
# (e o ambiente local e o Streamlit Cloud rodam 3.14).
FROM python:3.14-slim

ARG DOPPLER_PROJECT
ARG DOPPLER_CONFIG
ARG DOPPLER_TOKEN

WORKDIR /customer-monitoring

ENV HOST="0.0.0.0" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    DOPPLER_PROJECT="${DOPPLER_PROJECT}" \
    DOPPLER_CONFIG="${DOPPLER_CONFIG}" \
    DOPPLER_TOKEN="${DOPPLER_TOKEN}"

COPY ./requirements.txt /customer-monitoring/requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /customer-monitoring/requirements.txt

COPY ./app /customer-monitoring/app
# tema do Streamlit (cor primária da marca)
COPY ./.streamlit /customer-monitoring/.streamlit
# lidos em runtime a partir da raiz: documentação usada pelo Chat AI e planilha do Monitoramento
COPY ./documentacao_indicadores.md /customer-monitoring/documentacao_indicadores.md
COPY ./data /customer-monitoring/data

# Cloud Run envia o tráfego para a porta 8080
EXPOSE 8080

CMD ["streamlit", "run", "app/main.py", \
     "--server.port=8080", "--server.address=0.0.0.0", "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
