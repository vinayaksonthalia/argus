# ARGUS — containerized webhook server for the Foundry single-cast install.
# Build context is the argus/ project root:
#   docker build -f deploy/Dockerfile -t argus:latest .
FROM python:3.12-slim

WORKDIR /app

# Install the package (hatchling build from pyproject).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Non-root, tiny attack surface; postmortems + incident memory live on a volume.
RUN useradd -r -u 10001 argus && mkdir -p /data && chown argus /data
USER argus
WORKDIR /data
VOLUME /data

ENV ARGUS_PORT=7331 \
    # In a container there is no logged-in `claude` CLI: default to the
    # deterministic zero-LLM provider so the cast works with no secrets.
    # Operators set ANTHROPIC_API_KEY or GROQ_API_KEY (+ ARGUS_LLM_PROVIDER)
    # for real-LLM investigations.
    ARGUS_LLM_PROVIDER=heuristic \
    ARGUS_MEMORY_DB=/data/argus-memory.sqlite3

EXPOSE 7331
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
    CMD ["python", "-c", "import urllib.request;urllib.request.urlopen('http://localhost:7331/healthz', timeout=2)"]

CMD ["argus", "serve"]
