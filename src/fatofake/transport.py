"""Utilitários compartilhados pelos clientes HTTP externos."""

from __future__ import annotations

import ssl


def default_ssl_context() -> ssl.SSLContext:
    """Usa o repositório nativo do sistema quando `truststore` está instalado."""

    try:
        import truststore
    except ImportError:
        return ssl.create_default_context()
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
