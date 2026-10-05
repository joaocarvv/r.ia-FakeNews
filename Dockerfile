# ── Fato ou Fake? — imagem Docker ──────────────────────────────────
# Imagem com Python 3.11, PyTorch CPU, JupyterLab e API (Gunicorn).
# Build:  docker compose build
# Run:    docker compose up

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    DEBIAN_FRONTEND=noninteractive \
    APP_ENV=docker \
    SERVICE_NAME=fatofake \
    LOG_FILE=/var/log/fatofake/app.jsonl

# Dependências de sistema
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        build-essential \
        git \
        curl \
        libglib2.0-0 \
        libgl1 \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pip mais tolerante a redes lentas
ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=3

# ── Dependências Python ───────────────────────────────────────────
# 1) PyTorch CPU-only primeiro (evita baixar ~2 GB de CUDA)
COPY requirements.txt ./
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch>=2.2,<3" \
    && pip install --no-cache-dir -r requirements.txt

# Navegador headless para páginas abertas montadas por JavaScript (opcional).
ARG INSTALL_CRAWL4AI=true
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN if [ "$INSTALL_CRAWL4AI" = "true" ]; then \
        pip install --no-cache-dir "crawl4ai>=0.6,<1" \
        && python -m playwright install --with-deps chromium \
        && chmod -R a+rX /opt/ms-playwright; \
    fi

# ── Código-fonte e scripts ────────────────────────────────────────
# notebooks/ e data/ são montados como volumes no docker-compose.yml
COPY src/ ./src/
RUN mkdir -p /app/notebooks /app/data
COPY run_acceptance_app.py ./
COPY openapi.yaml ./
COPY start.sh ./
COPY .env.example ./
RUN chmod +x start.sh

# Cria diretórios necessários
RUN mkdir -p /var/log/fatofake /var/lib/fatofake

# ── Portas e entrypoint ───────────────────────────────────────────
# 5000: API HTTP e Interface Web
# 8888: JupyterLab
EXPOSE 5000 8888

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/v1/health', timeout=3)"

CMD ["./start.sh"]
