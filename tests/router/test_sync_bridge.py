"""The synchronous bridge: one loop, so a cached client survives the call.

These tests are about a mechanism, not a policy. The router caches a client
per provider so a request does not re-handshake TLS; an ``httpx.AsyncClient``
pool is bound to the loop it was first used on; ``asyncio.run`` closes its
loop per call. Two of those three are library facts we do not control, so the
executor's loop has to be the thing that changes.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from router import NoEligibleProvider, Provider, ProviderRouter, route_sync, run_sync
from router import routing
from router.routing import ProviderDenied, ProviderRequestError
from router.sync_bridge import LOOP_THREAD_NAME, loop_is_running, shutdown_loop


@pytest.fixture(autouse=True)
def fresh_bridge_loop():
    """No test leaks the loop thread, and none inherits another's.

    A client cached against a loop is dead once that loop stops, so the shared
    router is cleared on both sides of the shutdown.
    """
    routing.reset_shared_router(None)
    shutdown_loop()
    yield
    shutdown_loop()
    routing.reset_shared_router(None)


class LoopBoundClient:
    """A client that behaves the way ``httpx.AsyncClient`` behaves.

    It binds to the loop of its first use and refuses every later one, with
    the exact error the real pool raises. That refusal is the bug this module
    exists to prevent, so the double has to be able to reproduce it.
    """

    def __init__(self):
        self.loop = None
        self.completions = 0

    async def create_chat_completion(self, *, model, messages, **kwargs):
        running = asyncio.get_running_loop()
        if self.loop is None:
            self.loop = running
        elif running is not self.loop:
            raise RuntimeError("Event loop is closed")
        self.completions += 1
        return {"model": model}


def _router_with(client):
    rung = Provider("only", "https://only.example/v1", "ONLY_KEY", 1, "only-model", ("latency",))
    return ProviderRouter(
        [rung], environ={"ONLY_KEY": "test-key"}, client_factory=lambda *_: client
    )


class _RaisingClient:
    def __init__(self, exc):
        self._exc = exc

    async def create_chat_completion(self, *, model, messages, **kwargs):
        raise self._exc


def test_a_cached_client_survives_two_synchronous_calls():
    """The regression, end to end.

    ``asyncio.run`` per call would leave the second request holding a pool
    bound to a closed loop; this asserts it does not happen.
    """
    client = LoopBoundClient()
    routing.reset_shared_router(_router_with(client))

    first = route_sync("latency", [{"role": "user", "content": "one"}], urgent=True)
    second = route_sync("latency", [{"role": "user", "content": "two"}], urgent=True)

    assert first.provider == second.provider == "only"
    assert client.completions == 2


def test_the_same_double_would_have_failed_under_asyncio_run():
    """Proves the test above is testing something.

    If ``LoopBoundClient`` tolerated a second loop, the assertion it makes
    would pass with or without the bridge.
    """
    client = LoopBoundClient()
    router = _router_with(client)

    asyncio.run(router.route("latency", [{"role": "user", "content": "one"}], urgent=True))

    with pytest.raises(RuntimeError, match="Event loop is closed"):
        asyncio.run(router.route("latency", [{"role": "user", "content": "two"}], urgent=True))


def test_every_call_shares_one_loop_on_one_daemon_thread():
    loops = []

    async def which_loop():
        return asyncio.get_running_loop()

    loops.append(run_sync(which_loop()))
    loops.append(run_sync(which_loop()))

    assert loops[0] is loops[1]
    threads = [t for t in threading.enumerate() if t.name == LOOP_THREAD_NAME]
    assert len(threads) == 1
    assert threads[0].daemon, "a non-daemon loop thread would keep the process alive"


@pytest.mark.parametrize(
    "error",
    [
        ProviderDenied("a rung denied the request"),
        NoEligibleProvider("no configured provider is currently eligible"),
        ProviderRequestError("upstream said no", 418, {}),
        ValueError("something the SDK raised"),
    ],
)
def test_an_exception_reaches_the_caller_as_itself(error):
    """The poller's retry, backoff and dead-letter logic keys on the type.

    Wrapping anything here — in a ``RuntimeError``, or in whatever
    ``concurrent.futures`` might have offered — would silently reclassify
    every routed failure the executor sees.
    """

    async def boom():
        raise error

    with pytest.raises(type(error)) as caught:
        run_sync(boom())

    assert caught.value is error


def test_a_denial_from_the_real_router_arrives_intact_through_route_sync():
    routing.reset_shared_router(
        _router_with(_RaisingClient(ProviderRequestError("denied", 403, {})))
    )

    with pytest.raises(ProviderDenied):
        route_sync("latency", [{"role": "user", "content": "hi"}], urgent=True)


def test_a_timeout_gives_up_and_cancels_the_work():
    started = threading.Event()
    cancelled = threading.Event()

    async def never():
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with pytest.raises(TimeoutError):
        run_sync(never(), timeout=0.2)

    assert started.is_set()
    assert cancelled.wait(5), "a timed-out call must not keep occupying the shared loop"


def test_calling_the_bridge_from_inside_the_bridge_is_refused_not_deadlocked():
    async def reenter():
        async def inner():
            return "unreachable"

        return run_sync(inner())

    with pytest.raises(RuntimeError, match="deadlock"):
        run_sync(reenter())


def test_the_loop_can_be_stopped_and_starts_again_on_next_use():
    """The test seam. Without it a suite run leaves the thread behind."""

    async def answer():
        return 42

    assert run_sync(answer()) == 42
    assert loop_is_running()

    shutdown_loop()
    assert not loop_is_running()
    shutdown_loop()  # idempotent

    assert run_sync(answer()) == 42
    assert loop_is_running()
