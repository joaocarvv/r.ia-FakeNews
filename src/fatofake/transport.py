"""Utilitários compartilhados pelos clientes HTTP externos."""

from __future__ import annotations

import ssl
import threading
import time


_NCBI_LOCK = threading.Lock()
_NCBI_LAST_REQUEST = [0.0]


def wait_for_ncbi_slot(has_api_key: bool) -> None:
    """Ritmo único para todas as chamadas ao NCBI no processo.

    O limite (3/s sem chave, 10/s com chave) vale por IP; clientes e threads
    diferentes precisam dividir a mesma janela para evitar HTTP 429.
    """

    interval = 0.11 if has_api_key else 0.36
    with _NCBI_LOCK:
        delay = _NCBI_LAST_REQUEST[0] + interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        _NCBI_LAST_REQUEST[0] = time.monotonic()


def default_ssl_context() -> ssl.SSLContext:
    """Usa o repositório nativo do sistema quando `truststore` está instalado."""

    try:
        import truststore
    except ImportError:
        return ssl.create_default_context()
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
