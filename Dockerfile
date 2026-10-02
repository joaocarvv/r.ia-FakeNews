FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    APP_ENV=docker \
    SERVICE_NAME=fatofake \
    LOG_FILE=/var/log/fatofake/app.jsonl

RUN apt-get update \
    && apt-get install --no-install-recommends -y libglib2.0-0 libgl1 poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch>=2.2,<3" \
    && pip install --no-cache-dir -r requirements.txt

# Navegador headless para páginas abertas montadas por JavaScript (opcional).
ARG INSTALL_CRAWL4AI=true
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN if [ "$INSTALL_CRAWL4AI" = "true" ]; then         pip install --no-cache-dir "crawl4ai>=0.6,<1"         && python -m playwright install --with-deps chromium         && chmod -R a+rX /opt/ms-playwright;     fi

COPY src ./src
COPY run_acceptance_app.py ./

RUN useradd --create-home --uid 10001 fatofake \
    && mkdir -p /var/log/fatofake /var/lib/fatofake /home/fatofake/.cache/huggingface \
    && chown -R fatofake:fatofake /app /var/log/fatofake /var/lib/fatofake /home/fatofake

USER fatofake
EXPOSE 5000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/v1/health', timeout=3)"

# Um worker preserva o store de jobs em memória; threads permitem polling concorrente.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "300", "--access-logfile", "-", "--error-logfile", "-", "fatofake.wsgi:application"]
