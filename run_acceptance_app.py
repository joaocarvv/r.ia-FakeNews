"""Inicia o protótipo local usado no teste de aceitação."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from fatofake.retrieval_preview import create_live_retrieval_app

if __name__ == "__main__":
    application = create_live_retrieval_app(project_root=ROOT)
    print("Fato ou Fake? disponível em http://127.0.0.1:5000")
    print("Modo real: busca científica e análise preliminar de abstracts com Gemini.")
    application.run(host="127.0.0.1", port=5000, debug=False)
