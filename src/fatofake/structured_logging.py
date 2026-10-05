"""Logs JSON estruturados e contexto de correlação da aplicação."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
from time import perf_counter
from typing import Any, Iterator, MutableMapping


_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_analysis_id: ContextVar[str | None] = ContextVar("analysis_id", default=None)
logging.getLogger("fatofake").addHandler(logging.NullHandler())


class JsonFormatter(logging.Formatter):
    """Converte cada registro em uma única linha JSON consultável no Loki."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "service": os.getenv("SERVICE_NAME", "fatofake"),
            "environment": os.getenv("APP_ENV", "development"),
            "logger": record.name,
            "message": record.getMessage(),
            "thread": record.threadName,
        }
        request_id = _request_id.get()
        analysis_id = _analysis_id.get()
        if request_id:
            payload["request_id"] = request_id
        if analysis_id:
            payload["analysis_id"] = analysis_id
        payload.update(getattr(record, "structured_fields", {}))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_structured_logging(
    *,
    level: str | None = None,
    log_file: str | Path | None = None,
    enable_stdout: bool = True,
) -> None:
    """Configura stdout e, quando solicitado, um JSONL rotativo para o Alloy."""

    root = logging.getLogger()
    selected_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    root.setLevel(getattr(logging, selected_level, logging.INFO))

    close_structured_logging()

    formatter = JsonFormatter()
    if enable_stdout:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(formatter)
        stdout_handler._fatofake_structured = True  # type: ignore[attr-defined]
        root.addHandler(stdout_handler)

    destination = log_file or os.getenv("LOG_FILE")
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path,
            maxBytes=int(os.getenv("LOG_MAX_BYTES", str(20 * 1024 * 1024))),
            backupCount=int(os.getenv("LOG_BACKUP_COUNT", "5")),
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler._fatofake_structured = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)


def close_structured_logging() -> None:
    """Fecha somente os handlers criados por este módulo."""

    root = logging.getLogger()
    for handler in tuple(root.handlers):
        if getattr(handler, "_fatofake_structured", False):
            root.removeHandler(handler)
            handler.close()


def log_event(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    exc_info: bool = False,
    **fields: Any,
) -> None:
    """Emite um evento sem misturar campos estruturados com o namespace do LogRecord."""

    logger.log(
        level,
        message,
        extra={"structured_fields": fields},
        exc_info=exc_info,
    )


@contextmanager
def bind_log_context(
    *,
    request_id: str | None = None,
    analysis_id: str | None = None,
) -> Iterator[None]:
    """Associa IDs aos logs emitidos no contexto atual, inclusive em exceções."""

    tokens: list[tuple[ContextVar[str | None], Any]] = []
    if request_id is not None:
        tokens.append((_request_id, _request_id.set(request_id)))
    if analysis_id is not None:
        tokens.append((_analysis_id, _analysis_id.set(analysis_id)))
    try:
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


@contextmanager
def logged_step(
    logger: logging.Logger,
    stage: str,
    **fields: Any,
) -> Iterator[MutableMapping[str, Any]]:
    """Registra início, fim, duração e falha de uma etapa do pipeline."""

    details: MutableMapping[str, Any] = dict(fields)
    started = perf_counter()
    log_event(
        logger,
        logging.INFO,
        f"Etapa iniciada: {stage}",
        event="pipeline.step",
        stage=stage,
        status="started",
        **details,
    )
    try:
        yield details
    except Exception as error:
        log_event(
            logger,
            logging.ERROR,
            f"Etapa falhou: {stage}",
            exc_info=True,
            event="pipeline.step",
            stage=stage,
            status="failed",
            duration_ms=round((perf_counter() - started) * 1000, 2),
            error_type=type(error).__name__,
            **details,
        )
        raise
    else:
        log_event(
            logger,
            logging.INFO,
            f"Etapa concluída: {stage}",
            event="pipeline.step",
            stage=stage,
            status="completed",
            duration_ms=round((perf_counter() - started) * 1000, 2),
            **details,
        )
