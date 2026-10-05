# ── Fato ou Fake? — imagem Docker ──────────────────────────────────
# Imagem leve com Python 3.11, PyTorch CPU e JupyterLab.
# Build:  docker compose build
# Run:    docker compose up

FROM python:3.11-slim AS base

# Evita prompts interativos e bufferiza stdout/stderr
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Dependências de sistema mínimas (compilação de pacotes C)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pip mais tolerante a redes lentas
ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=3

# ── Dependências Python ───────────────────────────────────────────
# 1) PyTorch CPU-only primeiro (evita baixar ~2 GB de CUDA)
RUN pip install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cpu

# 2) Restante do requirements.txt
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ── Código-fonte, dados e notebooks ───────────────────────────────
COPY src/ ./src/
COPY notebooks/ ./notebooks/
COPY data/ ./data/
COPY run_acceptance_app.py ./
COPY openapi.yaml ./
COPY start.sh ./
COPY .env.example ./
RUN chmod +x start.sh

# Torna o pacote fatofake importável
ENV PYTHONPATH="/app/src:${PYTHONPATH}"

# ── Portas e entrypoint ───────────────────────────────────────────
# 5000: API HTTP e Interface Web
# 8888: JupyterLab
EXPOSE 5000 8888

CMD ["./start.sh"]
