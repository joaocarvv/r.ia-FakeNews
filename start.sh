#!/bin/bash
set -e

echo "=========================================================="
echo "🚀 Iniciando Fato ou Fake?"
echo "   - API e Interface Web: http://0.0.0.0:5000 (porta 5001 no host)"
echo "   - Documentação Swagger: http://0.0.0.0:5000/docs"
echo "   - JupyterLab:          http://0.0.0.0:8888"
echo "=========================================================="

# 1. Inicia o JupyterLab em segundo plano
jupyter lab \
    --ip=0.0.0.0 \
    --port=8888 \
    --no-browser \
    --allow-root \
    --ServerApp.token='' \
    --ServerApp.password='' \
    --notebook-dir=/app/notebooks &

# 2. Inicia a API Flask / Web UI em primeiro plano
exec python run_acceptance_app.py
