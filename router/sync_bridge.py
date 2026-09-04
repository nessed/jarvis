"""One long-lived event loop, so synchronous callers can reuse async clients.

The executor and ``tools/replay_job.py`` are synchronous, and both used to
reach the router through ``asyncio.run(route(...))``. ``asyncio.run`` creates
an event loop, runs the coroutine, and *closes* the loop. That is fine when
every object involved dies with the call — and fatal the moment one is meant
to outlive it.

``ProviderRouter._client_for`` caches its provider clients so a routed request
does not pay for a TLS handshake it already paid for. But an
``httpx.AsyncClient``'s connection pool is bound to the loop the client was
first used on: reuse it after that loop is closed and it raises
``RuntimeError: Event loop is closed``. So the cache is only worth having if
the loop outlives the call too.

This module is that loop. One daemon thread, started on first use, running
``loop.run_forever()`` for the life of the process; ``run_sync`` submits work
to it with ``asyncio.run_coroutine_threadsafe`` and blocks the calling thread
on the result.

Deliberately generic — it knows nothing about routing. ``route_sync`` lives in
``router/__init__.py``, where the routing knowledge already is.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

#: Guards *creation and teardown* of the loop thread only. Submitting work
#: needs no lock: ``run_coroutine_threadsafe`` is the thread-safe entrypoint.
_LOCK = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None

LOOP_THREAD_NAME = "jarvis-sync-bridge"


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """The process's bridge loop, started on first use.

    Double-checked outside the lock because this is on the path of every
    synchronous routed call, and after the first one there is nothing to do.
    """
    global _loop, _thread

    loop = _loop
    if loop is not None and not loop.is_closed():
        return loop

    with _LOCK:
        if _loop is not None and not _loop.is_closed():
            return _loop

        new_loop = asyncio.new_event_loop()
        running = threading.Event()

        def _run() -> None:
            asyncio.set_event_loop(new_loop)
            # Fires once the loop is actually processing callbacks, so a
            # caller can never submit to a loop that is not yet running.
            new_loop.call_soon(running.set)
            try:
                new_loop.run_forever()
            finally:
                asyncio.set_event_loop(None)

        thread = threading.Thread(target=_run, name=LOOP_THREAD_NAME, daemon=True)
        thread.start()
        running.wait()

        _loop, _thread = new_loop, thread
        return new_loop


def run_sync(coro: Coroutine[Any, Any, T], *, timeout: float | None = None) -> T:
    """Run ``coro`` on the bridge loop and return its result to this thread.

    Exceptions propagate **unchanged**. ``concurrent.futures.Future.result``
    re-raises the original object, so ``ProviderDenied``,
    ``NoEligibleProvider`` and the provider SDKs' own error types arrive at the
    caller as themselves — which is what the poller's retry and dead-letter
    logic keys on. Nothing here wraps, re-types, or swallows an error.

    ``timeout`` is wall time in seconds for the whole call, ``None`` for no
    limit. A timeout cancels the submitted work before raising, so a hung
    provider call does not keep occupying the shared loop after the caller has
    given up on it.
    """
    if _running_on_bridge_loop():
        coro.close()
        raise RuntimeError(
            "run_sync() was called from inside the bridge loop; awaiting the "
            "coroutine directly is the async path. Blocking here would deadlock."
        )

    future = asyncio.run_coroutine_threadsafe(coro, _ensure_loop())
    try:
        return future.result(timeout)
    except TimeoutError:
        future.cancel()
        raise


def _running_on_bridge_loop() -> bool:
    try:
        return asyncio.get_running_loop() is _loop
    except RuntimeError:
        return False


def loop_is_running() -> bool:
    """Whether a bridge loop thread is currently alive. A test/diagnostic seam."""
    return _thread is not None and _thread.is_alive()


def shutdown_loop(timeout: float = 5.0) -> None:
    """Stop the bridge loop and join its thread. Idempotent.

    A test seam, not a runtime path: the loop is meant to live as long as the
    process does. Tests use it so a suite run does not leave a thread (and a
    provider connection pool) behind for the next test to trip over.

    Any client cached against this loop is dead once it returns, so a test that
    calls this should also reset the shared router.
    """
    global _loop, _thread
    with _LOCK:
        loop, thread = _loop, _thread
        _loop, _thread = None, None

    if loop is None:
        return
    loop.call_soon_threadsafe(loop.stop)
    if thread is not None:
        thread.join(timeout)
    loop.close()
