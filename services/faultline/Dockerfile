FROM python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# SERVICE selects which FastAPI app to run; PORT its listen port.
ENV SERVICE=gateway PORT=8090
CMD opentelemetry-instrument uvicorn "app.${SERVICE}:app" --host 0.0.0.0 --port "${PORT}" --no-access-log
