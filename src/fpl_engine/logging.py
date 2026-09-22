"""Explicit, UTC project logging with composable structured context."""

from collections.abc import Mapping
from copy import deepcopy
import json
import logging as _logging
import sys
from threading import RLock
import time
from types import MappingProxyType
from typing import Any, TextIO


_PROJECT_NAME = "fpl_engine"
_RESERVED_FIELDS = frozenset(
    _logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}
_CONFIG_LOCK = RLock()


def get_logger(name: str = _PROJECT_NAME) -> _logging.Logger:
    """Get a logger under fpl_engine without installing handlers.

    Fully qualified project names are retained; other names are prefixed with
    ``fpl_engine.``. This includes ``__main__`` for scripts.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Logger name must be a non-empty string")
    if name != _PROJECT_NAME and not name.startswith(f"{_PROJECT_NAME}."):
        name = f"{_PROJECT_NAME}.{name}"
    return _logging.getLogger(name)


def _validate_context(context: Mapping[str, Any]) -> None:
    for key in context:
        if not isinstance(key, str):
            raise ValueError("Logging context keys must be strings")
        if key in _RESERVED_FIELDS:
            raise ValueError(f"Reserved LogRecord field cannot be bound: {key}")


class _ContextAdapter(_logging.LoggerAdapter):
    def process(self, msg: Any, kwargs: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        call_context = kwargs.get("extra") or {}
        _validate_context(call_context)
        kwargs["extra"] = {**self.extra, **call_context}
        return msg, kwargs


def bind_context(
    logger: _logging.Logger | _ContextAdapter, /, **context: Any
) -> _ContextAdapter:
    """Bind copied context without changing a parent logger or adapter.

    New bindings override older values; per-call ``extra`` overrides bindings
    for that record only. Use JSON-compatible values or values with a meaningful
    string representation (for example dates and paths). Do not include secrets.
    """
    _validate_context(context)
    if isinstance(logger, _ContextAdapter):
        context = {**logger.extra, **context}
        logger = logger.logger
    return _ContextAdapter(logger, MappingProxyType(deepcopy(context)))


class _ContextFormatter(_logging.Formatter):
    converter = time.gmtime

    def formatMessage(self, record: _logging.LogRecord) -> str:
        message = super().formatMessage(record)
        context = {
            key: value for key, value in record.__dict__.items()
            if key not in _RESERVED_FIELDS
        }
        if context:
            message += " context=" + json.dumps(
                context, sort_keys=True, ensure_ascii=False, default=str
            )
        return message


class _ProjectStreamHandler(_logging.StreamHandler):
    """Identifies the handler owned by configure_logging."""


def configure_logging(
    level: int | str = _logging.INFO, *, stream: TextIO | None = None
) -> None:
    """Configure the project hierarchy, leaving the application root untouched.

    Accept DEBUG, INFO, WARNING, ERROR or CRITICAL (case-insensitive names or
    their integer constants). Default output is stderr. Repeated calls update
    the same owned handler; caller-installed handlers are retained. Configure
    at application startup. Handler writes and configuration calls are locked.

    Project children propagate to fpl_engine; fpl_engine does not propagate to
    the root. Importing this module alone does not configure any logger.
    """
    if isinstance(level, str):
        name = level.upper()
        if name not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"Invalid project log level: {level!r}")
        level = getattr(_logging, name)
    if type(level) is not int or level not in {
        _logging.DEBUG, _logging.INFO, _logging.WARNING,
        _logging.ERROR, _logging.CRITICAL,
    }:
        raise ValueError(f"Invalid project log level: {level!r}")

    with _CONFIG_LOCK:
        logger = get_logger()
        handler = next(
            (item for item in logger.handlers if isinstance(item, _ProjectStreamHandler)),
            None,
        )
        if handler is None:
            handler = _ProjectStreamHandler(stream if stream is not None else sys.stderr)
            logger.addHandler(handler)
        else:
            handler.setStream(stream if stream is not None else sys.stderr)
        handler.setFormatter(_ContextFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        ))
        handler.setLevel(level)
        logger.setLevel(level)
        logger.disabled = False
        logger.propagate = False
