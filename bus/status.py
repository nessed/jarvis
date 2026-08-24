"""Dependency-injected status endpoint helpers."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import Request

StatusDependency = Callable[[], Any | Awaitable[Any]]
_QUEUE_STATUSES = ("queued", "running", "done", "failed")
_LAST_JOB_FIELDS = ("id", "kind", "status", "run_after", "created_at", "updated_at")


class QueueStatusReader:
    """Read queue observability data without selecting job payloads or checkpoints."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_repository(cls, repository: Any) -> "QueueStatusReader":
        """Adapt the existing Supabase repository without broadening its write contract."""
        client = getattr(repository, "_client", None)
        if client is None:
            raise TypeError("queue status requires a Supabase-backed repository")
        return cls(client)

    def queue_depths(self) -> dict[str, int]:
        """Return durable job counts grouped by their current lifecycle status."""
        response = self._client.table("jobs").select("status").execute()
        depths = dict.fromkeys(_QUEUE_STATUSES, 0)
        for row in response.data or []:
            status = row.get("status") if isinstance(row, Mapping) else None
            if isinstance(status, str):
                depths[status] = depths.get(status, 0) + 1
        return depths

    def last_job(self) -> dict[str, Any] | None:
        """Return only safe lifecycle metadata for the most recently created job."""
        fields = ",".join(_LAST_JOB_FIELDS)
        response = (
            self._client.table("jobs")
            .select(fields)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        data = response.data or []
        if not data or not isinstance(data[0], Mapping):
            return None
        return {field: data[0][field] for field in _LAST_JOB_FIELDS if field in data[0]}


async def _resolve(dependency: StatusDependency) -> Any:
    result = dependency()
    return await result if inspect.isawaitable(result) else result


async def status_payload(
    *,
    queue_depths: StatusDependency,
    last_job: StatusDependency,
    provider_health: StatusDependency,
) -> dict[str, Any]:
    """Build the status shape from supplied data providers, not global services."""

    depths, latest, providers = await _resolve(queue_depths), await _resolve(last_job), await _resolve(provider_health)
    return {
        "queue_depth_by_status": dict(depths) if isinstance(depths, Mapping) else depths,
        "last_job": latest,
        "provider_health": dict(providers) if isinstance(providers, Mapping) else providers,
    }


def create_status_handler(
    *, queue_depths: StatusDependency, last_job: StatusDependency, provider_health: StatusDependency
) -> Callable[[Request], Awaitable[dict[str, Any]]]:
    """Create a FastAPI-compatible handler that integration can mount at `/status`."""

    async def handler(_: Request) -> dict[str, Any]:
        return await status_payload(
            queue_depths=queue_depths,
            last_job=last_job,
            provider_health=provider_health,
        )

    return handler
