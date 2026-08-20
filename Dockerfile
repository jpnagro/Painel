FROM tiangolo/uvicorn-gunicorn-fastapi:python3.11

ARG DOPPLER_PROJECT
ARG DOPPLER_CONFIG
ARG DOPPLER_TOKEN

WORKDIR /customer-monitoring

ENV HOST="0.0.0.0"

ENV DOPPLER_PROJECT="${DOPPLER_PROJECT}"
ENV DOPPLER_CONFIG="${DOPPLER_CONFIG}"
ENV DOPPLER_TOKEN="${DOPPLER_TOKEN}"

COPY ./requirements.txt /customer-monitoring/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /customer-monitoring/requirements.txt

COPY ./app /customer-monitoring/app

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
