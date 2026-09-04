# Lane: queue-and-graph-client-reuse

**Role:** BUILD. Do not commit. Do not edit `requirements.txt`.
**Owns (exclusively):** `db/jobs.py`, `tests/db/test_jobs.py`,
`tests/db/test_jobs_integration.py`, `bus/whatsapp_client.py`,
`tests/bus/test_whatsapp_client.py`.
**Does not own:** `executor/handlers/whatsapp.py`, `executor/poller.py`,
`bus/main.py`. CORE integrates those. If you need a change there, put it in
your report as a one-line diff; do not make it.

Before editing, claim every file you will write:

```
.venv\Scripts\python.exe tools/work_board_claim.py claim --role BUILD --work-item queue-and-graph-client-reuse --file db/jobs.py --file tests/db/test_jobs.py --file tests/db/test_jobs_integration.py --file bus/whatsapp_client.py --file tests/bus/test_whatsapp_client.py
```

Release the returned claim ID after verification.

## Why this lane exists (measured 4 Sep 2026)

Every queue call builds a brand-new Supabase client. `db/jobs.py:309`
`_repository_or_default()` calls `SupabaseJobsRepository.from_env()` whenever
`repository` is `None`, and every module-level helper (`enqueue`,
`claim_next`, `checkpoint`, `complete`, `fail`, `set_timeout`, …) does that.
The executor's poller passes `repository=None`. So each poll, checkpoint and
completion pays a fresh TLS handshake to Supabase:

```
raw httpx, one persistent connection:
  RPC claim_next_job : [0.42, 0.35, 0.74, 0.36] s
through db.jobs.claim_next (new client per call):
  db.jobs.claim_next : 2.83, 3.43, 2.19, 1.72 s
```

The worker log shows the same thing: consecutive `claim_next_job` lines are
1.3–1.8 s apart. A single text reply makes ~5 queue calls on the critical
path (claim, set_timeout, checkpoint, complete, plus the poll that found it),
so this is roughly 6 s of a reply's latency, and it is pure connection setup.

`bus/whatsapp_client.py` has the same shape one layer over: every
`send_text_message`, `show_typing_indicator`, `upload_media`, `download_media`
and `send_voice_note` opens `with httpx.Client(...)` and closes it. TLS to
`graph.facebook.com` from this machine measured 1.0 s. A text reply does two
of those (typing cue, send); a voice reply does four.

## What to build

### 1. `db/jobs.py`: one default repository per process

Follow the precedent in `router/routing.py:671-720` (`shared_router`,
`current_shared_router`, `reset_shared_router`) exactly in spirit:

- A module-level `_default_repository: JobRepository | None` behind a
  `threading.Lock`, built lazily by `from_env()` on first use.
- `_repository_or_default(None)` returns it.
- Key the cache on the `(SUPABASE_URL, key)` pair it was built with, so a
  test that monkeypatches the environment after a repository was cached gets
  a fresh one rather than a stale client. Compare the values; never log or
  print them.
- `reset_default_repository(repository=None)` test seam, same shape as
  `reset_shared_router`.
- The supabase-py client is used from one thread per process here (the
  poller is single-threaded; the bus builds its own repository via
  `create_app`'s `_default_jobs()`, which is untouched). Say in a docstring
  that the cache is a process-lifetime connection, not a claim about thread
  safety of supabase-py.
- Do **not** change any function signature. Every `repository=` keyword must
  keep working exactly as before.

Tests: cache is built once across two calls; a changed env yields a new one;
`reset_default_repository()` clears it; an explicit `repository=` bypasses it.
`tests/db/test_jobs.py:326` already monkeypatches `from_env`'s dependencies —
extend that style. Make sure the existing test that asserts the timeout is
passed into the client still passes.

### 2. `bus/whatsapp_client.py`: one `httpx.Client` per `WhatsAppClient`

- The instance owns a lazily-created `httpx.Client` (base_url, timeout,
  `transport=self._transport` when injected). All five call sites use it.
  Media calls that need a longer timeout pass a per-request `timeout=`
  instead of building a second client.
- Add `close()` and `__enter__`/`__exit__`. Closing then calling again must
  work (rebuild lazily), because the handler is a long-lived closure.
- Every existing exception mapping stays word-for-word.
- `tests/bus/test_whatsapp_client.py` uses `httpx.MockTransport`; assert
  that two sends share one client (e.g. count transport constructions or
  check `client._http is client._http` across calls).

## Verification

Focused, then full:

```
.venv\Scripts\python.exe -m pytest -q tests/db tests/bus
.venv\Scripts\python.exe -m pytest -q
```

Then the live proof, which is the whole point — with `.env` loaded, time
four consecutive `db.jobs.claim_next("__latency_probe__")` calls (that kind
does not exist, so nothing is claimed) and show they drop from ~2 s to
~0.4 s after the first. Paste the numbers.

## Report

`docs/tasks/queue-and-graph-client-reuse-report.md`: what changed, the
before/after numbers, the full-suite output line, and any change you need in
files you do not own (expected: `executor/handlers/whatsapp.py` should build
one `WhatsAppClient` in `build_whatsapp_webhook_handler` instead of one per
`_default_*` closure call — write the exact lines; CORE applies them).
