# Lane report: router-client-reuse

**Role:** BUILD. Nothing committed. `requirements.txt` untouched — no new
dependency; `asyncio` and `threading` are stdlib.

**Claim:** `c8ae3fa74b91495aac28964e1bd41cb2`, released after verification.

## What changed

| File | Change |
|---|---|
| `router/routing.py` | client cache + `_client_for`; safe `__repr__`; `_discovered_model_for` memoises Mistral's model |
| `router/sync_bridge.py` | **new** — one process-lifetime loop on a daemon thread, `run_sync`, `shutdown_loop` |
| `router/__init__.py` | `route_sync` and `run_sync` exported |
| `tools/replay_job.py` | `_real_completion` uses `route_sync`; its local `import asyncio` is gone |
| `tests/router/test_routing.py` | five tests appended |
| `tests/router/test_sync_bridge.py` | **new**, 11 collected |

**No existing test needed changing.** The brief expected some to assert one
construction per attempt; none did. Every `client_factory` double in
`tests/router/test_routing.py` is either a `lambda *_:` returning one shared
instance, or a per-endpoint dispatch keyed on the endpoint. The assertions all
count *chat completions*, through the shared `calls` list, not constructions.

`_client_for` uses `cache_key not in self._clients` rather than `.get()`,
because several tests inject `client_factory=lambda *_: None` and `None` is a
cached value like any other.

## The numbers

### Offline, counted

Three `route()` calls on one router, with a factory that records every
construction and a discovering client that counts every `models.list()`:

```
before:  clients built: 3   discovery calls: 3
after:   clients built: 1   discovery calls: 1
```

### Live, wall time

Three `latency` calls per row, `.env` loaded, one process, same short prompt.
Provider name and seconds only.

```
asyncio.run(route(...)) provider=openrouter 3.966s  1.860s  11.396s
route_sync(...)         provider=openrouter 1.901s  1.168s   1.043s
asyncio.run(route(...)) provider=openrouter 2.041s  2.034s   1.941s
route_sync(...)         provider=openrouter 1.764s  1.185s   0.773s
```

Steady state: **~2.0 s per call the old way, ~0.8–1.2 s the new way.** The
`asyncio.run` rows never improve, because each call closes the loop that owned
the connection. The saving is roughly **0.9 s per routed call**, and a text
reply routes twice.

The old path also printed a real `RuntimeError: Event loop is closed` from
`httpcore`'s teardown during that run — the exact failure `sync_bridge.py`
exists to prevent, arriving unprompted as evidence.

### Suites

```
.venv\Scripts\python.exe -m pytest -q tests/router tests/tools/test_replay_job.py
130 passed in 11.46s

.venv\Scripts\python.exe -m pytest -q
1397 passed, 9 deselected in 72.15s (0:01:12)
```

Run bare, as `CLAUDE.md` requires.

## The `discover_chat_model` finding

**It was once per request.** `_model_for` called `list_chat_models()` on every
attempt, so every Mistral completion was preceded by its own `models.list()`
HTTP round trip. Measured above: three routes, three discovery calls.

Now memoised per provider name for the router's lifetime, which
`shared_router()` makes the process's — the same scope and the same reasoning
as the cooldown ledger.

**Only a successful discovery is cached.** A raise propagates untouched, so
`route()` still turns a 401/402/403/429/5xx into a cooldown, and an empty
roster returns `None` without being remembered. A workspace that gains chat
access an hour later is not locked out until restart.
`test_an_empty_model_roster_is_never_cached` holds that line.

## Secrets

The cache is keyed on `(base_url, api_key)`, so the dict holds live keys.
`ProviderRouter.__repr__` is now explicit and boring — `<ProviderRouter
providers=N>` — so no traceback, log line, or future `@dataclass` decorator can
start walking those attributes.
`test_the_router_repr_never_renders_its_client_cache` asserts it. Nothing in
this lane printed a key, a header, or a `.env` value.

## What CORE must change

`executor/handlers/whatsapp.py` is CORE's file. Two edits, both mechanical.

**Line 285**, inside `_default_complete`:

```python
        return route_sync(task_profile, messages, urgent=True)
```

**Line 46**, the import:

```python
from router import RoutedResult, route_sync
```

`route` becomes unused there. `import asyncio` at **line 20** also becomes
unused — `asyncio` appears nowhere else in that file — so drop it.

Until that lands, the executor still pays a handshake per message: the client
cache is real but `asyncio.run` closes the loop underneath it, so nothing is
reused. **The cache does not help the live path until this one-liner is in.**

## Interface note

No `Protocol`, public signature, or schema changed. `ChatClient` and
`ModelDiscoveringChatClient` are untouched, so no implementer or test double
elsewhere needs an edit. `route()` keeps its exact signature; `route_sync` is
additive.

`executor/poller.py:494`'s `request_completion` is already `async` and awaits
`route()` directly, which is correct and needs nothing. It has no production
caller today — only `tests/executor/test_poller.py`.
