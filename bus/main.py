"""Protected FastAPI command bus: verify, enqueue, and return."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request

from bus.logging import RequestIDMiddleware, get_logger, redact_verify_token_from_access_log
from bus.security import BearerAuthMiddleware, enforce_meta_signature, meta_webhook_handshake
from bus.status import QueueStatusReader, create_status_handler
from bus.webhook_dedup import (
    SeenWebhookMessageStore,
    extract_message_ids,
    open_default_seen_webhook_message_store,
)
from db.jobs import JobRepository, SupabaseJobsRepository, enqueue
from router import ProviderRouter
from router import health_report

load_dotenv()


def _empty_queue_depths() -> dict[str, int]:
    """Keep status available before Supabase has been configured."""
    return {}


def _no_last_job() -> None:
    return None


def _default_jobs() -> JobRepository | None:
    """Connect the running app to the server-only queue when it is configured."""
    try:
        return SupabaseJobsRepository.from_env()
    except RuntimeError:
        return None


def _queue_status_reader(jobs: JobRepository | None) -> QueueStatusReader | None:
    """Use live observability only for the existing Supabase repository."""
    if jobs is None:
        return None
    try:
        return QueueStatusReader.from_repository(jobs)
    except TypeError:
        return None


#: What a provider looks like when no routing process has reported on it.
#: Deliberately carries ``reported: False`` rather than a plausible-looking
#: zero: the bus never routes, so silence here means "not measured", and the
#: two must not be readable as the same thing.
_UNREPORTED: dict[str, Any] = {
    "last_status": None,
    "cooldown_seconds_remaining": 0.0,
    "rate_limit_headers": {},
    "reported": False,
}


def _provider_health(router: ProviderRouter) -> dict[str, dict[str, Any]]:
    """Non-secret health/cooldown metadata, as reported by the process that routes.

    Until 2 September 2026 this read ``router.health`` — the *bus's* own
    router. The bus is enqueue-only and never calls ``route()``, so every entry
    was the constructed default forever, and ``/status`` reported "no failures"
    when what it meant was "no attempts". Q10c settled who reports: the
    executor, which is where routing actually happens, so the real ledger
    arrives through ``router/health_report.py``.

    The provider roster still comes from the local manifest, so the key set is
    the full ladder whether or not anything has been measured. Entries the
    reporter knows about that the local roster does not are kept rather than
    dropped, because a roster that has moved on is exactly when you want to see
    what the other process is actually talking to.
    """
    reported = health_report.read() or {}
    health = {name: dict(reported.get(name, _UNREPORTED)) for name in router.health}
    for name, entry in reported.items():
        if name not in health:
            health[name] = dict(entry)
    return health


def create_app(
    *,
    jobs: JobRepository | None = None,
    provider_router: ProviderRouter | None = None,
    meta_app_secret: str | None = None,
    meta_verify_token: str | None = None,
    bearer_token: str | None = None,
    queue_depths: Callable[[], Any] | None = None,
    last_job: Callable[[], Any] | None = None,
    retry_health: Callable[[], Any] | None = None,
    distill_chain_health: Callable[[], Any] | None = None,
    open_webhook_dedup: Callable[[], SeenWebhookMessageStore] | None = None,
) -> FastAPI:
    """Build an injectable app; a webhook performs no work beyond enqueueing."""
    redact_verify_token_from_access_log()
    app = FastAPI(title="JARVIS bus")
    logger = get_logger()
    open_dedup_store = open_webhook_dedup or open_default_seen_webhook_message_store
    active_jobs = jobs if jobs is not None else _default_jobs()
    status_reader = _queue_status_reader(active_jobs)
    app.state.jobs = active_jobs
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

        message_ids = extract_message_ids(payload)
        if message_ids:
            with open_dedup_store() as seen:
                if all(seen.has_seen(message_id) for message_id in message_ids):
                    return {"accepted": True, "duplicate": True}

        repository = request.app.state.jobs
        job = enqueue("whatsapp_webhook", payload, repository=repository)

        if message_ids:
            with open_dedup_store() as seen:
                for message_id in message_ids:
                    seen.mark_seen(message_id)

        return {"accepted": True, "job_id": job.id}

    app.add_api_route(
        "/status",
        create_status_handler(
            queue_depths=queue_depths or (
                status_reader.queue_depths if status_reader is not None else _empty_queue_depths
            ),
            last_job=last_job or (
                status_reader.last_job if status_reader is not None else _no_last_job
            ),
            provider_health=lambda: _provider_health(app.state.provider_router),
            retry_health=retry_health or (
                status_reader.retry_health if status_reader is not None else None
            ),
            distill_chain_health=distill_chain_health or (
                status_reader.distill_chain_health if status_reader is not None else None
            ),
        ),
        methods=["GET"],
    )
    return app


app = create_app()
