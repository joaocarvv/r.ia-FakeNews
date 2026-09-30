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

# ── Código-fonte e notebooks ──────────────────────────────────────
COPY src/ ./src/
COPY notebooks/ ./notebooks/
COPY .env.example ./

# Torna o pacote fatofake importável
ENV PYTHONPATH="/app/src:${PYTHONPATH}"

# ── Porta e entrypoint ────────────────────────────────────────────
EXPOSE 8888

CMD ["jupyter", "lab", \
     "--ip=0.0.0.0", \
     "--port=8888", \
     "--no-browser", \
     "--allow-root", \
     "--NotebookApp.token=''", \
     "--NotebookApp.password=''", \
     "--notebook-dir=/app/notebooks"]
