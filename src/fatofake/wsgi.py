"""Entrada WSGI usada pelo contêiner da aplicação."""

from .retrieval_preview import create_live_retrieval_app
from .structured_logging import configure_structured_logging, log_event

import logging


configure_structured_logging()
application = create_live_retrieval_app()
log_event(
    logging.getLogger("fatofake.startup"),
    logging.INFO,
    "Fato ou Fake iniciado via WSGI",
    event="application.started",
    host="0.0.0.0",
    port=5000,
    mode="scientific_retrieval",
)
