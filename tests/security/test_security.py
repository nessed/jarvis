import hashlib
import hmac
import json
import logging

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from bus.logging import JsonLineFormatter
from bus.security import (
    BearerAuthMiddleware,
    enforce_meta_signature,
    meta_webhook_handshake,
    verify_meta_signature,
)
from bus.status import create_status_handler


SECRET = "test-meta-secret"
BUS_TOKEN = "test-bus-token"


def signature(body: bytes) -> str:
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def secured_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(BearerAuthMiddleware, token=BUS_TOKEN)

    @app.get("/webhook")
    async def webhook_verify(request: Request):
        return await meta_webhook_handshake(request, verify_token="verify-token")

    @app.post("/webhook")
    async def webhook_receive(request: Request):
        await enforce_meta_signature(request, app_secret=SECRET)
        return {"accepted": True}

    app.add_api_route(
        "/status",
        create_status_handler(
            queue_depths=lambda: {"queued": 3, "running": 1},
            last_job=lambda: {"id": "job-1", "status": "running"},
            provider_health=lambda: {"groq": "healthy"},
        ),
        methods=["GET"],
    )
    return app


def test_valid_meta_signature_passes() -> None:
    body = b'{"entry":[]}'
    assert verify_meta_signature(body, signature(body), app_secret=SECRET)
    response = TestClient(secured_app()).post("/webhook", content=body, headers={"X-Hub-Signature-256": signature(body)})
    assert response.status_code == 200


def test_bad_or_absent_meta_signature_returns_403() -> None:
    client = TestClient(secured_app())
    assert client.post("/webhook", content=b"{}", headers={"X-Hub-Signature-256": "sha256=" + "0" * 64}).status_code == 403
    assert client.post("/webhook", content=b"{}").status_code == 403


def test_unauthed_status_returns_401() -> None:
    client = TestClient(secured_app())
    assert client.get("/status").status_code == 401
    response = client.get("/status", headers={"Authorization": f"Bearer {BUS_TOKEN}"})
    assert response.status_code == 200
    assert response.json()["queue_depth_by_status"] == {"queued": 3, "running": 1}


def test_valid_handshake_echoes_challenge() -> None:
    response = TestClient(secured_app()).get(
        "/webhook",
        params={"hub.verify_token": "verify-token", "hub.challenge": "challenge-123"},
    )
    assert response.status_code == 200
    assert response.text == "challenge-123"


def test_json_log_formatter_includes_request_id() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "event", (), None)
    record.request_id = "request-1"  # type: ignore[attr-defined]
    decoded = json.loads(JsonLineFormatter().format(record))
    assert decoded["request_id"] == "request-1"
