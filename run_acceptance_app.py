import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from fatofake.retrieval_preview import create_live_retrieval_app


if __name__ == "__main__":
    application = create_live_retrieval_app(project_root=ROOT)
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    print(f"Fato ou Fake? disponível em http://{display_host}:{port}")
    print("Modo real: busca científica e análise preliminar de abstracts com Gemini.")
    application.run(host=host, port=port, debug=False)
