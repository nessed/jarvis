# Lane: router-client-reuse

**Role:** BUILD. Do not commit. Do not edit `requirements.txt`.
**Owns (exclusively):** `router/routing.py`, `router/__init__.py`,
`tests/router/test_routing.py`, `tools/replay_job.py`,
`tests/tools/test_replay_job.py`.
**Does not own:** `executor/handlers/whatsapp.py`,
`executor/handlers/command_intent.py`. CORE integrates those. Put the exact
one-line change you need there in your report.

Before editing, claim:

```
.venv\Scripts\python.exe tools/work_board_claim.py claim --role BUILD --work-item router-client-reuse --file router/routing.py --file router/__init__.py --file tests/router/test_routing.py --file tools/replay_job.py --file tests/tools/test_replay_job.py
```

Release the claim ID after verification.

## Why (measured 4 Sep 2026)

`ProviderRouter.route()` (`router/routing.py:382`) calls
`self._client_factory(endpoint, key)` **inside the per-provider loop on every
request**, and `openai_client_factory` builds a new `AsyncOpenAI` each time.
A new `AsyncOpenAI` is a new `httpx.AsyncClient` is a new TLS handshake.
Measured from this laptop: openrouter 0.45 s, groq 0.92 s, mistral 0.57 s,
deepseek 0.38 s of TLS per connection. A text reply makes **two** routed
completions (classification, then the reply), so this is 1–2 s per message
of pure setup, before the model has seen a token.

Caching the client is not enough on its own. The executor calls the router
through `asyncio.run(route(...))` (`executor/handlers/whatsapp.py:285`,
`tools/replay_job.py:409`). `asyncio.run` creates and then closes an event
loop per call, and an `httpx.AsyncClient` pool is bound to the loop it was
first used on — reuse across `asyncio.run` boundaries fails with
"Event loop is closed". So a cached async client needs one long-lived loop.

## What to build

### 1. Client cache inside `ProviderRouter`

- `self._clients: dict[tuple[str, str], Any]` keyed on
  `(base_url, api_key)`; `_client_for(provider)` builds via
  `self._client_factory` on first use and returns the cached instance after.
- The `shared_router()` is already process-lifetime, so this cache is too.
- Tests that inject a fake `client_factory` and count calls must be
  reviewed: some assert one construction per attempt today. Update them to
  the new contract, and add one that proves two `route()` calls on one
  router construct the client once.
- Never put a key in a log, repr or error message. The cache key holds the
  key string; make sure no `__repr__` or debug path renders the dict.

### 2. A persistent loop for synchronous callers: `route_sync`

- Add `router/sync_bridge.py` (you own it — create it) with a lazily-started
  daemon thread running one event loop for the process, and
  `run_sync(coro, *, timeout=None)` using
  `asyncio.run_coroutine_threadsafe(...).result(timeout)`.
- Export `route_sync(task_profile, messages, **kw)` from `router/__init__.py`
  that does `run_sync(route(task_profile, messages, **kw))`.
- Any exception raised inside the coroutine must propagate unchanged to the
  caller (`ProviderDenied`, `NoEligibleProvider`, SDK errors) — the poller's
  retry/dead-letter logic keys on them.
- `tools/replay_job.py:409`: switch to `route_sync`. Its tests must still
  pass.
- A test seam to stop/reset the loop thread so the test suite does not leak
  threads.

### 3. Check `discover_chat_model`

`router/routing.py:480,537` — `mistral` discovers its model via
`models.list()` on the API. Establish whether that runs **once per process**
or **once per request**. If per request, memoize per provider for the
router's lifetime (the shared router is process-lifetime, and a failed
discovery must not be cached). Report which it was.

## Verification

```
.venv\Scripts\python.exe -m pytest -q tests/router tests/tools/test_replay_job.py
.venv\Scripts\python.exe -m pytest -q
```

Live proof: with `.env` loaded, call `route_sync("latency", [...one short
user message...], urgent=True)` twice in one process and log wall time for
each; the second must be visibly faster than the first (connection reused).
Print provider name and seconds only — never the response headers, never
the key. If no provider is reachable, say so and show the offline evidence
instead (a fake client factory counting constructions).

## Report

`docs/tasks/router-client-reuse-report.md`: what changed, the numbers, full
suite line, the `discover_chat_model` finding, and the exact edit CORE must
make at `executor/handlers/whatsapp.py:284-285` (expected:
`return route_sync(task_profile, messages, urgent=True)` and drop the
`asyncio` import if it becomes unused).
