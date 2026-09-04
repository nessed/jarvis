"""Provider routing package."""

from collections.abc import Mapping, Sequence
from typing import Any

from .routing import (
    NoEligibleProvider,
    OpenAIChatClient,
    Provider,
    ProviderDenied,
    ProviderRequestError,
    ProviderRouter,
    RoutedResult,
    current_shared_router,
    load_providers,
    reset_shared_router,
    route,
    shared_router,
)
from .sync_bridge import run_sync


def route_sync(
    task_profile: str, messages: Sequence[Mapping[str, Any]], **request_options: Any
) -> RoutedResult:
    """``route()`` for synchronous callers, on the process's shared event loop.

    Use this instead of ``asyncio.run(route(...))``. They look equivalent and
    are not: ``asyncio.run`` closes its loop when the call ends, and the
    router's cached provider clients hold ``httpx`` connection pools bound to
    the loop they were first used on. Reuse across ``asyncio.run`` boundaries
    raises ``RuntimeError: Event loop is closed``, so with ``asyncio.run`` the
    client cache cannot do its job and every request pays for a new TLS
    handshake. ``router/sync_bridge.py`` explains the mechanism.

    Every keyword ``route()`` takes still works — ``urgent``, ``emergency``,
    ``model``, and anything else forwarded to the provider SDK. Exceptions
    propagate unchanged, so callers that key on ``ProviderDenied`` or
    ``NoEligibleProvider`` need no adjustment.
    """
    return run_sync(route(task_profile, messages, **request_options))


__all__ = [
    "NoEligibleProvider",
    "OpenAIChatClient",
    "Provider",
    "ProviderDenied",
    "ProviderRequestError",
    "ProviderRouter",
    "RoutedResult",
    "current_shared_router",
    "load_providers",
    "reset_shared_router",
    "route",
    "route_sync",
    "run_sync",
    "shared_router",
]
