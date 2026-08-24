"""Protected FastAPI command bus: verify, enqueue, and return."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request

from bus.logging import RequestIDMiddleware, get_logger
from bus.security import BearerAuthMiddleware, enforce_meta_signature, meta_webhook_handshake
from bus.status import create_status_handler
from db.jobs import JobRepository, enqueue
from router import ProviderRouter

load_dotenv()


def _empty_queue_depths() -> dict[str, int]:
    """Keep status available before Supabase has been configured."""
    return {}


def _no_last_job() -> None:
    return None


def _provider_health(router: ProviderRouter) -> dict[str, dict[str, Any]]:
    """Expose non-secret health/cooldown metadata for configured routing lanes."""
    return {
        name: {
            "last_status": health.last_status,
            "cooldown_until": health.cooldown_until,
            "rate_limit_headers": health.rate_limit_headers,
        }
        for name, health in router.health.items()
    }


def create_app(
    *,
    jobs: JobRepository | None = None,
    provider_router: ProviderRouter | None = None,
    meta_app_secret: str | None = None,
    meta_verify_token: str | None = None,
    bearer_token: str | None = None,
    queue_depths: Callable[[], Any] = _empty_queue_depths,
    last_job: Callable[[], Any] = _no_last_job,
) -> FastAPI:
    """Build an injectable app; a webhook performs no work beyond enqueueing."""
    app = FastAPI(title="JARVIS bus")
    logger = get_logger()
    app.state.jobs = jobs
    app.state.provider_router = provider_router or ProviderRouter()
    app.add_middleware(BearerAuthMiddleware, token=bearer_token)
    app.add_middleware(RequestIDMiddleware, logger=logger)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/webhook")
    async def verify_webhook(request: Request):
        return await meta_webhook_handshake(request, verify_token=meta_verify_token)

    @app.post("/webhook")
    async def receive_webhook(request: Request) -> dict[str, str | bool]:
        await enforce_meta_signature(request, app_secret=meta_app_secret, logger=logger)
        try:
            payload = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="webhook body must be JSON") from exc
        repository = request.app.state.jobs
        job = enqueue("whatsapp_webhook", payload, repository=repository)
        return {"accepted": True, "job_id": job.id}

    app.add_api_route(
        "/status",
        create_status_handler(
            queue_depths=queue_depths,
            last_job=last_job,
            provider_health=lambda: _provider_health(app.state.provider_router),
        ),
        methods=["GET"],
    )
    return app


app = create_app()
