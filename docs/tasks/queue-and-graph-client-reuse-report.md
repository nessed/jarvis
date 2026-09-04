# Report: queue-and-graph-client-reuse

BUILD lane, 4 September 2026. Nothing committed.

**Result: a queue call after the first dropped from ~1.9s to ~0.3s.** Both
halves of the lane were connection setup, not work.

## What changed

### `db/jobs.py` — one default repository per process

- `default_repository()` builds a `SupabaseJobsRepository` on first use and
  returns the same one afterwards, behind `_DEFAULT_REPOSITORY_LOCK`. The
  precedent is `router/routing.py`'s `shared_router()`.
- The cache is keyed on the `(SUPABASE_URL, server key)` pair it was built
  from. A changed environment yields a fresh repository rather than a client
  still pointed at the old project. The pair is compared, never logged.
- `current_default_repository()` reports whether one exists without building
  one; `reset_default_repository(repository=None)` clears or seeds it, the
  same shape as `reset_shared_router`. A seeded repository answers for every
  environment, because a test put it there deliberately.
- `_repository_or_default(None)` now returns the cached one. **No signature
  changed.** Every `repository=` keyword behaves exactly as before, and an
  explicit `repository=` never builds or touches the cache.
- Missing or wrong credentials still raise on *every* call and cache nothing,
  which is what `bus/main.py`'s `jobs=None` fallback relies on to fail a
  webhook loudly.
- The docstring says what the cache is: a process-lifetime connection, not a
  claim about supabase-py thread safety. The queue is used from one thread per
  process — the poller is a single serial loop, and the bus builds its own
  repository in `create_app`'s `_default_jobs()`, which does not go through
  this cache.

### `bus/whatsapp_client.py` — one `httpx.Client` per `WhatsAppClient`

- The instance owns a lazily built `httpx.Client` (`_http` property; base_url,
  timeout, injected `transport`). All five call sites use it:
  `send_text_message`, `show_typing_indicator`, `download_media`,
  `upload_media`, `send_voice_note`.
- The media calls pass `timeout=httpx.Timeout(media_timeout_seconds)` per
  request instead of building a second client, so the 30s media timeout and
  the 10s message timeout both survive on one client.
- `close()` and `__enter__`/`__exit__` added. `close()` is idempotent and not
  final: the next call rebuilds lazily, because the WhatsApp handler holds the
  client in a long-lived closure.
- Nothing is built until the first request, so constructing a client still
  costs nothing and validation errors still raise before any connection.
- Every exception mapping is unchanged, word for word.

## Numbers

Live, `.env` loaded, four consecutive `db.jobs.claim_next("__latency_probe__")`
calls. That kind does not exist, so the RPC matches nothing and claims nothing.

```
before:  4.34, 2.02, 2.05, 1.77 s
after:   3.67, 0.30, 0.30, 0.30 s
after:   2.97, 0.65, 0.72, 0.30 s   (second run, same script)
```

The first call still pays client construction plus the handshake. Every call
after it is the RPC alone. A text reply makes about five queue calls on its
critical path (the poll that finds it, claim, set_timeout, checkpoint,
complete), so this is roughly 6-7s off a reply's latency.

Graph API handshake cost, measured the same afternoon with an unauthenticated
`GET https://graph.facebook.com/v21.0/` — no token, no message, no side effect,
connection setup only:

```
new client per request: 1.09, 0.77, 0.76, 0.82 s
one kept-open client  : 0.33, 0.24, 0.24, 0.24 s
```

About 0.5s per Graph call. A text reply makes two (typing cue, send) and a
voice reply four — but only once `executor/handlers/whatsapp.py` stops building
a client per call. See below.

## Verification

```
.venv\Scripts\python.exe -m pytest -q tests/db tests/bus
104 passed, 2 deselected in 1.64s

.venv\Scripts\python.exe -m pytest -q
1397 passed, 9 deselected in 70.64s (0:01:10)
```

The full run was made with the other live lanes' in-progress changes present in
the tree, and was green.

New tests: `tests/db/test_jobs.py::TestDefaultRepositoryIsReused` (built once,
env change rebuilds, reset clears and seeds, helpers use the cache, explicit
`repository=` bypasses it, missing credentials still raise every call) and five
in `tests/bus/test_whatsapp_client.py` (four calls share one client, nothing
built before the first request, close then rebuild, context manager closes,
media timeouts survive on the shared client).

## What CORE has to apply — `executor/handlers/whatsapp.py`

The lane's own numbers are only half-collected until this lands: the handler
still builds a new `WhatsAppClient` inside each `_default_*` closure, so each
one still pays its own handshake.

It must stay lazy. Building it at `build_whatsapp_webhook_handler` time would
make registering the handler require `META_ACCESS_TOKEN`, because
`WhatsAppClientConfig.from_environ()` raises when it is unset.

Replace the four `_default_*` closures (currently lines 287-297 and 321-323)
with:

```python
    # One Graph client for the life of this handler. Not built at registration
    # time, because that would make registering the handler require a token;
    # not per call, because each new client pays a fresh ~0.8s TLS handshake to
    # graph.facebook.com, and a voice reply makes four calls.
    graph_client: WhatsAppClient | None = None

    def _graph_client() -> WhatsAppClient:
        nonlocal graph_client
        if graph_client is None:
            graph_client = WhatsAppClient(WhatsAppClientConfig.from_environ())
        return graph_client

    def _default_send(*, to: str, text: str) -> str:
        return _graph_client().send_text_message(to=to, text=text)

    def _default_show_typing_indicator(*, message_id: str) -> None:
        _graph_client().show_typing_indicator(message_id=message_id)

    def _default_download_media(media_id: str) -> tuple[bytes, str]:
        return _graph_client().download_media(media_id=media_id)

    def _default_send_voice_note(*, to: str, audio: bytes) -> str:
        return _graph_client().send_voice_note(to=to, audio=audio)
```

`_default_send_voice_note` keeps its position after
`_default_synthesize_voice_reply`; only its body changes. No test exercises
these four closures today (every handler test injects its own sender), so this
is a behaviour-preserving edit for the suite.

**One behaviour change to know about:** the handler then reads
`META_ACCESS_TOKEN` once per process instead of once per message, so rotating
the token needs an executor restart. The queue cache does not have this problem
— it is keyed on the credentials and rebuilds when they change.

## Also worth a look, not in this lane's scope

`executor/handlers/outcome.py:65` has the identical per-call construction in
`_default_send`. It is one Graph call per outcome job rather than four per
message, so it is smaller, but the same two-line fix applies.
