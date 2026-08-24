"""Composable authentication helpers for Meta webhooks and bus routes."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse, Response

from bus.logging import get_logger, log_event

META_SIGNATURE_PREFIX = "sha256="


def _setting(value: str | None, name: str) -> str:
    return value if value is not None else os.environ.get(name, "")


def verify_meta_signature(
    body: bytes, signature_header: str | None, *, app_secret: str | None = None
) -> bool:
    """Return whether a Meta SHA-256 signature matches the raw request body."""

    secret = _setting(app_secret, "META_APP_SECRET")
    if not secret or not signature_header or not signature_header.startswith(META_SIGNATURE_PREFIX):
        return False
    supplied_digest = signature_header[len(META_SIGNATURE_PREFIX):]
    if len(supplied_digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in supplied_digest):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied_digest)


async def enforce_meta_signature(
    request: Request, *, app_secret: str | None = None, logger: logging.Logger | None = None
) -> None:
    """Raise a generic 403 for missing, malformed, or invalid Meta signatures."""

    valid = verify_meta_signature(
        await request.body(), request.headers.get("X-Hub-Signature-256"), app_secret=app_secret
    )
    if valid:
        return
    active_logger = logger or get_logger()
    log_event(
        active_logger,
        "webhook_signature_rejected",
        request_id=getattr(request.state, "request_id", None),
        level=logging.WARNING,
        method=request.method,
        path=request.url.path,
        status_code=status.HTTP_403_FORBIDDEN,
    )
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid webhook signature")


async def meta_webhook_handshake(
    request: Request, *, verify_token: str | None = None
) -> PlainTextResponse:
    """Validate Meta's GET webhook challenge and return its challenge verbatim."""

    supplied_token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge")
    expected_token = _setting(verify_token, "META_VERIFY_TOKEN")
    if not expected_token or not hmac.compare_digest(expected_token, supplied_token) or challenge is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid webhook verification")
    return PlainTextResponse(challenge)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Require the bus bearer token on all paths except explicitly public webhooks."""

    def __init__(
        self,
        app: Any,
        *,
        token: str | None = None,
        webhook_paths: set[str] | frozenset[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.token = _setting(token, "BUS_BEARER_TOKEN")
        self.webhook_paths = frozenset(webhook_paths or {"/webhook"})

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in self.webhook_paths:
            return await call_next(request)
        header = request.headers.get("Authorization", "")
        prefix = "Bearer "
        supplied_token = header[len(prefix):] if header.startswith(prefix) else ""
        if not self.token or not supplied_token or not hmac.compare_digest(self.token, supplied_token):
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "unauthorized"})
        return await call_next(request)
