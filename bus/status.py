"""Dependency-injected status endpoint helpers."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import Request

StatusDependency = Callable[[], Any | Awaitable[Any]]


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
