---
id: client-connection-reuse
status: done
lane: AUTO
priority: 1
phase: 0
blocked-on: none
files: db/jobs.py, bus/whatsapp_client.py, router/routing.py, router/sync_bridge.py, router/__init__.py, executor/handlers/whatsapp.py, executor/handlers/outcome.py, tools/replay_job.py, tests/db/, tests/bus/, tests/router/, tests/executor/
resources: none
---

# client-connection-reuse — stop paying a TLS handshake per call

## Goal

A text reply spent 12-18 s in connection setup before any model saw a
token (`docs/history/infra-audit-2026-09-04.md`). Three clients were built
per call: the Supabase client in `db.jobs`, the Graph `httpx.Client` in
`WhatsAppClient` (and a `WhatsAppClient` per call in the handler), and an
`AsyncOpenAI` per provider attempt in the router — the last one on an event
loop `asyncio.run()` closed after every message.

## Log

**4 Sep 2026 — done.** Two BUILD lanes on Opus 5 plus CORE integration.
Briefs: `docs/tasks/queue-and-graph-client-reuse.md`,
`docs/tasks/router-client-reuse.md`; reports alongside as `*-report.md`.

Queue (`db/jobs.py`): `default_repository()` built once per process behind
a lock, keyed on the `(SUPABASE_URL, key)` pair, `reset_default_repository()`
seam, no signature changed. Live, four `claim_next("__latency_probe__")`:

```
before:  4.34, 2.02, 2.05, 1.77 s
after:   3.67, 0.30, 0.30, 0.30 s
```

Graph (`bus/whatsapp_client.py`): one lazily-built `httpx.Client` per
instance, `close()` and context-manager support, media timeouts per
request. Handler (`executor/handlers/whatsapp.py`, `outcome.py`): one
`WhatsAppClient` per handler, built on first use because the handler is
constructed at import before `.env` is loaded. Unauthenticated GET to the
Graph host:

```
new client per request: 1.09, 0.77, 0.76, 0.82 s
one kept-open client  : 0.33, 0.24, 0.24, 0.24 s
```

Router (`router/routing.py`, new `router/sync_bridge.py`): clients cached
per `(base_url, key)`; `route_sync()` runs on one process-lifetime loop
thread so the pool survives between messages; Mistral's `models.list()`
discovery — previously **once per request** — memoised on success. Live,
three `latency` calls in one process:

```
asyncio.run(route(...)) openrouter 2.041  2.034  1.941 s
route_sync(...)         openrouter 1.764  1.185  0.773 s
```

The `asyncio.run` row also raised a real `RuntimeError: Event loop is
closed` from httpcore teardown, which is the failure the bridge removes.
The handler's `_default_complete` now calls `route_sync`.

Verification (CORE, after integration):

```
.venv\Scripts\python.exe -m pytest -q tests/executor tests/router tests/voice/test_speak.py
509 passed, 2 deselected in 34.51s
```

Full suite result is in the commit that carries this file.
