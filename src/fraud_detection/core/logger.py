"""
Structured JSON logging module for enterprise observability.

Outputs JSON formatted log events with standard fields and contextual metadata
(tx_id, user_id, latency_ms) compatible with Docker, Datadog, and Azure Log Analytics.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include exception traceback if present
        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        # Include custom extra metadata if passed
        standard_attrs = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
        }
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                log_payload[key] = value

        return json.dumps(log_payload, default=str)


def get_logger(name: str) -> logging.Logger:
    """
    Configure and return a structured logger instance.

    Parameters
    ----------
    name : str
        Module name or component identifier.

    Returns
    -------
    logging.Logger
        Configured logger instance.
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False

    return logger
