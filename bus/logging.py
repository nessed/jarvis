"""Structured logging and request correlation helpers for the command bus."""

from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"
_VERIFY_TOKEN_QUERY_PARAM = re.compile(r"(hub\.verify_token=)[^&\s\"]+")


class RedactVerifyTokenFilter(logging.Filter):
    """Strip Meta's verify-token value from uvicorn's access log line.

    Meta's webhook handshake sends the token as a `GET /webhook` query
    parameter, and uvicorn's access logger prints the full request line
    (path and query string included) by default.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(
                _VERIFY_TOKEN_QUERY_PARAM.sub(r"\1REDACTED", arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


def redact_verify_token_from_access_log(logger_name: str = "uvicorn.access") -> None:
    """Attach the redaction filter once, however uvicorn was launched."""

    access_logger = logging.getLogger(logger_name)
    if not any(isinstance(existing, RedactVerifyTokenFilter) for existing in access_logger.filters):
        access_logger.addFilter(RedactVerifyTokenFilter())


class JsonLineFormatter(logging.Formatter):
    """Render log records as one JSON object per line without secret values."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        for key in ("method", "path", "status_code"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, separators=(",", ":"), default=str)


def get_logger(name: str = "jarvis.bus") -> logging.Logger:
    """Return a logger that writes structured JSON lines to stdout once."""

    logger = logging.getLogger(name)
    if not any(getattr(handler, "_jarvis_json", False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonLineFormatter())
        handler._jarvis_json = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def log_event(logger: logging.Logger, message: str, *, request_id: str | None = None,
              level: int = logging.INFO, **fields: Any) -> None:
    """Emit a structured event while keeping request metadata explicit."""

    logger.log(level, message, extra={"request_id": request_id, **fields})


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a non-secret correlation ID and log one completion line per request."""

    def __init__(self, app: Any, *, logger: logging.Logger | None = None) -> None:
        super().__init__(app)
        self.logger = logger or get_logger()

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        log_event(
            self.logger,
            "request_complete",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )
        return response
