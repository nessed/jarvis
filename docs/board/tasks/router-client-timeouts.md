---
id: router-client-timeouts
status: done
lane: AUTO
priority: 2
phase: 4
blocked-on: none (independent of the whatsapp.py chain — good parallel lane)
files: router/routing.py (hot), router/sync_bridge.py, tests/router/test_routing.py (hot within router), .env.example (one line, hand to whoever holds it if claimed)
resources: none
---

# router-client-timeouts — explicit deadlines instead of the SDK's 600 s

## Why

Astra §3.1: the OpenAI client in `router/routing.py` (construction around
lines 144-157) leaves timeout and retries at SDK defaults — 600 s and two
retries — while the worker's job timeout is 300 s. So a hung provider is
retried inside the SDK, inside the router's own rung fall-through, inside
the poller's job retry, and the job timeout fires first with the thread
still running (`executor/poller.py:323-350`, `_run_with_timeout`). Astra
§5.3: "at most one deliberate fallback inside an overall interaction
deadline; separate longer deadlines for background work."

## Steps

1. Per-call `timeout=` and `max_retries=0` on the client; the router does
   the one fallback, not the SDK. Values from env with sane defaults:
   `JARVIS_ROUTER_CALL_TIMEOUT_SECONDS` (default 20 for `latency`
   profile), `JARVIS_ROUTER_BATCH_TIMEOUT_SECONDS` (default 120). Add both
   to `.env.example` with a one-line comment.
2. An overall interaction deadline on `route()` for the `latency` profile:
   when the deadline would be exceeded by trying the next rung, stop and
   surface `RouterDeadlineExceeded` instead of walking the whole ladder.
   Cooldown ledger behaviour is unchanged.
3. Tests: hung-provider fake → single fallback → deadline error within
   the budget; batch profile keeps the longer budget.
4. Do **not** touch the poller's thread-kill problem here; note it in the
   Log as the remaining gap (a timed-out handler thread still runs).

## Done when

`tests/router/` green with the new cases; full offline suite green; Log
cites both and names every implementer of any signature you widened.

## Log

### 2026-09-09 — done (lane-1)

**What the SDK was doing.** `AsyncOpenAI` was constructed with its defaults:
`max_retries=2` and `timeout=600`. So a hung provider was retried twice inside
the call, inside the router's own rung fall-through, inside the poller's job
retry — and the SDK's own 600 s limit was twice the worker's 300 s job timeout,
so it could never be the thing that fired.

**What it does now.**

- `OpenAIChatClient.__init__` builds the SDK client with `max_retries=0`. One
  layer owns fallback and it is the router.
- The client-level `timeout` defaults to `JARVIS_ROUTER_BATCH_TIMEOUT_SECONDS`
  (120 s), which bounds the one call `route()` does not pass a timeout to:
  `list_chat_models` during Mistral model discovery.
- `route()` passes a per-call `timeout` sized to the profile:
  `JARVIS_ROUTER_CALL_TIMEOUT_SECONDS` (default 20) for `latency`,
  `JARVIS_ROUTER_BATCH_TIMEOUT_SECONDS` (default 120) for everything else. A
  caller that passes its own `timeout=` keeps it.
- `latency` gets an interaction deadline of two call budgets — one attempt and
  one deliberate fallback, Astra §5.3. Checked *before* starting a rung: if
  the elapsed time plus one more call budget would exceed it, `route()` raises
  `RouterDeadlineExceeded` naming the rung it declined to try. It counts
  seconds, not attempts, so rungs that fail instantly (no model, an immediate
  401) do not spend it. No second env var: the deadline is derived from the
  call timeout, so there is no number to keep in step with another.
- Both env vars are in `.env.example`. A blank, malformed, zero or negative
  value logs once and falls back to the default rather than becoming the
  router's deadline.

**One thing the task did not list, found while doing it.** `APITimeoutError`
carries no HTTP status, so `_response_metadata` returned `None` and `route()`
took its `raise` branch — a timeout aborted the whole cascade instead of
falling through. That was survivable while the SDK retried twice inside the
call; with `max_retries=0` and a real per-call deadline it would have made the
router strictly worse, and step 3 asks for exactly the case it broke
("hung-provider fake → single fallback"). A hang now falls through and cools
the rung down like a 503, matched by exception-class name across the MRO
(`TRANSPORT_FAILURE_CLASS_NAMES`) because `routing.py` imports the OpenAI SDK
lazily and the adjacent comment already notes SDK exception types vary by
provider. `last_status` stays `None`: a hang is not an HTTP answer and none is
invented.

**Shared interfaces.** None widened. `ChatClient.create_chat_completion`
already took `**kwargs`, and every implementer in the tree accepts it
unchanged — `router/routing.py:OpenAIChatClient`,
`tests/router/test_routing.py:FakeClient`,
`tests/router/test_sync_bridge.py` (two doubles),
`tests/status/test_live_queue_status.py:371`. `RouterDeadlineExceeded`
subclasses `NoEligibleProvider`, so `executor/poller.py`'s bare-`Exception`
retry/dead-letter path is untouched. `router/__init__.py` exports it
(claimed separately; it is not in this task's frontmatter).

**The remaining gap, per step 4.** The poller's thread-kill problem is
untouched and still real: `executor/poller.py` `_run_with_timeout` abandons a
timed-out handler thread, which keeps running. The router's deadlines make
that far less likely to trigger — an interactive call now gives up at 40 s
rather than 600 — but they do not fix it. A handler that hangs on something
other than a routed call still leaks a thread.

**Verification.**

```
$ .venv/Scripts/python.exe -m pytest -q tests/router/ --basetemp=.pytest-basetemp-lane-1
116 passed in 9.62s

$ .venv/Scripts/python.exe -m pytest -q --basetemp=.pytest-basetemp-lane-1
1521 passed, 10 deselected in 67.04s (0:01:07)
```

The 13 new cases (11 after parametrisation expands) cover: `max_retries=0` and
the client-level timeout default and its env override; the per-call timeout for
`latency` / `batch` / `long_context`; both env vars; five unusable env values;
a caller-supplied timeout surviving; a hung rung falling through to a working
one; a hung rung cooling down with no invented status; three hung rungs
stopping at two attempts with `RouterDeadlineExceeded`; the same three on
`batch` walking the whole ladder; the deadline halving when the call timeout
does; and instant failures not spending the budget.
