"""Inicia o protótipo local usado no teste de aceitação."""

from pathlib import Path
import os
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from fatofake.retrieval_preview import create_live_retrieval_app
from fatofake.structured_logging import configure_structured_logging, log_event

import logging


if __name__ == "__main__":
    configure_structured_logging()
    application = create_live_retrieval_app(project_root=ROOT)
    host = "0.0.0.0" if os.getenv("APP_ENV") == "docker" else "127.0.0.1"
    log_event(
        logging.getLogger("fatofake.startup"),
        logging.INFO,
        "Fato ou Fake iniciado",
        event="application.started",
        host=host,
        port=5000,
        mode="scientific_retrieval",
    )
    application.run(host=host, port=5000, debug=False)
