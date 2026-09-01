---
id: router-cooldown-ledger
status: done
lane: AUTO
priority: 2
phase: 0
blocked-on: none
files: router/routing.py (hot), router/__init__.py, router/health_report.py (new),
  tests/router/test_routing.py (area-hot), tests/router/test_health_report.py (new),
  executor/poller.py (hot), tests/executor/test_poller.py, bus/main.py (hot),
  tests/status/test_live_queue_status.py, .gitignore, docs/state.md.
  Claimed and NOT edited: executor/handlers/whatsapp.py, bus/status.py
resources: none offline
---

# router-cooldown-ledger — a ledger that outlives one call

## Gate

**Answered 1 Sep 2026 — Q10c = yes.** Process-lifetime scope, executor
(not bus) reports provider health. Build as specified.

Q10c: Ali blesses process-lifetime scope with the executor reporting
provider health. This is the one router job that was Class C — the
blueprint underspecified the ledger's lifetime.

## Goal

Today `route()` builds a fresh `ProviderRouter` per call, so a 429'd
provider is retried on the very next message and `/status`'s provider
health reports a router that has never routed. Make the ledger
process-lifetime and make provider health real.

## Steps

1. One long-lived `ProviderRouter` per process (module-level factory with
   injection for tests; stop re-reading `providers.yaml` per call).
2. Cooldown state survives across calls; expiry honors `retry-after` /
   header data where present.
3. Provider health flows from the process that routes — the executor.
   Smallest honest mechanism for `/status` (e.g. executor writes a small
   health snapshot the status reader includes, like `retry_health` does)
   — design within existing patterns; a new external service is out of
   scope.
4. This file's touch-list is nearly all hot files — claim them all, run
   as a solo lane, name every test double touched (four router jobs'
   worth live in `tests/router/test_routing.py`).
5. Tests: cooldown persists across two `route()` calls; expiry; /status
   shows non-empty health after a routed failure (fakes).

## Done when

Suite green; a live two-message check shows the second request skipping a
cooled-down rung (cite logs); state.md router row updated.

## Log

**2 Sep 2026 — done.** Both halves of Q10c: the ledger is process-lifetime,
and the process that routes is the one that reports provider health.

### The ledger

`route()` built a `ProviderRouter` per call. Every call therefore re-read the
manifest and, far worse, started from a blank `health` map — a provider that
had just returned 429 with a `retry-after` was tried again on the very next
message, because the cooldown died with the router that recorded it. A ledger
that does not outlive one call is not a ledger.

`router.shared_router()` now builds one router per process, on first use,
behind a lock (a handler can be called from the poller's worker thread while
another is mid-flight; two routers would mean two ledgers). `route()` uses it.
`current_shared_router()` asks whether one exists without building one, and
`reset_shared_router()` is the test seam.

Process-lifetime, not persisted: Q10c's answer, and the right trade — a file
would tell a fresh process to keep avoiding a provider that recovered hours
ago.

### Provider health on /status

`/status` read `app.state.provider_router.health`: the **bus's** router. The
bus is enqueue-only and never calls `route()`, so every entry sat at its
constructed default for the life of the process. `/status` was reporting the
absence of any attempt, in a shape indistinguishable from "everything is
fine".

The routing process is a different process, so its ledger cannot be read in
memory. `router/health_report.py` carries it across, mirroring
`executor/heartbeat.py`: a small file, written best-effort, read with an age
bound, fail-open on every error.

Two details that are not incidental:

- **The countdown is stored relative.** `cooldown_until` is a `monotonic()`
  reading and monotonic clocks share no origin between processes — the bus
  comparing that number against its own clock would be comparing to an
  unrelated zero. The snapshot stores seconds-remaining plus a wall-clock
  `reported_at`, and the reader subtracts elapsed time. That also keeps the
  file correct while the writer is idle.
- **The file is only rewritten when something material changes.** The
  countdown ticking is not a reason, since the reader ages it. Without that
  guard the poll loop would rewrite the file several times a second forever.

`_publish_provider_health` uses `current_shared_router`, not `shared_router`,
so a worker that never routes neither builds a router nor stamps its defaults
over the snapshot of the worker that does. Of the three supervised pollers,
only `whatsapp-worker` routes.

`/status` now shows `reported: false` where nothing has reported, rather than
a plausible-looking zero.

### Interface change, named

`/status`'s `provider_health` entries changed shape: `cooldown_until` (a raw
monotonic float, meaningless to a reader) is replaced by
`cooldown_seconds_remaining`, and `reported` / `reported_age_seconds` are
added. `tests/test_integration.py` asserts only that the roster is present and
still passes; nothing else in the tree reads those fields.

`executor/handlers/whatsapp.py` was claimed and **not edited** — it reaches
the shared router through `route()`, which is the seam that changed.

### Offline suite

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp
1166 passed, 9 deselected, 10 warnings in 57.59s
```

New: 9 ledger tests in `tests/router/test_routing.py`, 19 in
`tests/router/test_health_report.py`, 6 publisher tests in
`tests/executor/test_poller.py`, 4 `/status` tests in
`tests/status/test_live_queue_status.py`.

### Live: the second request skips the cooled-down rung

Real manifest, real keys, real HTTP. The 429 is injected through
`_record_cooldown` — the same method route()'s real 429 branch calls, with a
real `retry-after` header — because a genuine 429 is not producible on demand
without hammering a free tier. What is being proved is the ledger surviving
between two `route()` calls, and that part is entirely real.

```
call 1 served by     : openrouter/openrouter/free
ledger after call 1  : {"last_status": 200, "cooldown_seconds_remaining": 0.0, ...}
eligible order now   : ['groq', 'openrouter', 'mistral', 'cerebras', 'gemini', 'deepseek']

injected a 429 + retry-after 60 for openrouter via _record_cooldown
ledger now           : {"last_status": 429, "cooldown_seconds_remaining": 60.0,
                        "rate_limit_headers": {"retry-after": "60"}}
eligible order now   : ['groq', 'mistral', 'cerebras', 'gemini', 'deepseek']

call 2 served by     : mistral/codestral-2508
same router object   : True
```

Call 2 is a real HTTP request to a genuinely different provider. Before this
change it would have gone back to openrouter, because the router that recorded
the cooldown no longer existed.

### Live: /status serves what the routing process published

Real `route()`, the poller's real `_publish_provider_health`, the real file,
the real `bus.main._provider_health` reader. Only the poll loop's `while True`
is not spun up; `test_the_poll_loop_publishes_each_cycle` covers that it calls
this every cycle.

```
file on disk         : .provider-health.json
published            : {"last_status": 429, "cooldown_seconds_remaining": 59.992,
                        "rate_limit_headers": {"retry-after": "60"}, "reported": true,
                        "reported_age_seconds": 0.008}
rewrites when nothing material changed: True

what /status now shows for the cooled-down rung:
  openrouter {"last_status": 429, "cooldown_seconds_remaining": 59.992, ...,
              "reported": true, "reported_age_seconds": 0.008}
```

### Two findings, neither in scope here

1. **The top two rungs of the ladder are dead, silently.** `groq` (priority 1)
   and `cerebras` (priority 2) declare `default_model: "${GROQ_DEFAULT_MODEL}"`
   / `"${CEREBRAS_DEFAULT_MODEL}"`. `load_providers` resolves those to `None`
   because neither key exists in `.env` — U2 again. `_configured()` does not
   catch it: its model guard only covers providers that declare `model_env`,
   and these declare `default_model`. So both stay eligible, sort to the front
   of every request, and are skipped inside `route()` with
   `"no model configured"` — a message that is only ever surfaced if *every*
   provider fails. Six consecutive live `latency` calls went to `openrouter`
   with `groq` sitting first in the eligible order each time. Filed for
   `board-audit` as `router-unresolvable-model-rungs`; it belongs beside
   `provider-status-generator`, whose whole job is reporting
   configured-but-not-routable with a reason.

2. **Two lanes running the mandated pytest command at once corrupt each
   other's runs.** `CLAUDE.md` mandates
   `--basetemp=.pytest-basetemp`, a fixed path, and `agents.md` encourages
   parallel lanes. Two concurrent sessions share that directory, and pytest's
   tmp-dir factory prunes old numbered dirs at session start — including the
   other session's live ones. This produced two spurious full-suite failures
   in different `tests/voice/` tests, each passing in isolation, before the
   cause was found. Reproduced deliberately: two concurrent `pytest tests/voice/`
   runs gave `221 passed, 2 errors` and `223 passed`. Filed for `board-audit`
   as `pytest-basetemp-collision`; it is adjacent to the existing
   `pytest-addopts` task, which is where the flag lives.
