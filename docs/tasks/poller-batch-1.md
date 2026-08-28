# Lane: poller-batch-1

## Ownership

Own only `executor/poller.py`, `executor/heartbeat.py`,
`tests/executor/test_poller.py`, `tests/executor/test_heartbeat.py`. Claimed
under work-board claim `poller-batch-1` — already held by the orchestrator; do
not re-claim or release it. Do not touch any other file, especially not
`executor/flp/sort.py` or `executor/flp/__init__.py` — those are claimed by a
different, concurrently running orchestrator process right now (work-board
claim `small-corrections-batch`); touching them will produce a real merge
collision. Do not edit `requirements.txt`; append any new dependency to
`docs/tasks/deps-poller-batch-1.txt`. Do not commit.

## Context

`executor/poller.py` runs the durable job-queue loop. Four fixes, three of
which touch the same ~8 lines of `main()`'s loop — do them together as one
coherent change to that function, then the fourth (`poll_once`) separately.
Add tests for all four to `tests/executor/test_poller.py` /
`tests/executor/test_heartbeat.py`.

### 1. `distill-chain-reseed-in-loop`

`_seed_distill_chain()` (line 249) is called exactly once, before `while True:`
starts (line 227-228), guarded by `if not args.once`. `seed_distill_chain()`
(imported from `executor/handlers/distill.py`) is documented as idempotent.
If it fails to seed once — e.g. three consecutive extraction failures poison
the chain per the existing history note — distillation stops permanently
until the executor is restarted, because nothing calls it again. Move (or add)
a call to `_seed_distill_chain()` inside the loop, at a cadence that doesn't
spam Supabase every 5s (e.g. only after `poll_once` returns `None`, i.e. the
queue is idle, since that's when a broken chain would otherwise sit silent).

### 2. `poller-drain-without-idle-sleep`

`time.sleep(args.interval)` (line 244) runs unconditionally after every
`poll_once()` call, including when `poll_once` just completed a real job (i.e.
there may be more queued work waiting). This means a backlog drains at most
one job per `--interval` (default 5s) instead of draining back-to-back while
work exists. Only sleep when `poll_once` returned `None` (queue was empty).

### 3. `heartbeat-clear-on-exit`

`executor/heartbeat.py` has `touch()` but no function to remove the heartbeat
file. `poller.py`'s `main()` never clears it on a clean exit (the
`KeyboardInterrupt` branch at line 245 just `return 0`s). Per
`executor/heartbeat.py`'s own docstring, batch tools refuse to start for up to
`DEFAULT_MAX_AGE_SECONDS` (600s) after the executor's last heartbeat — so a
deliberately, cleanly stopped executor still blocks batch tools for up to 10
minutes for no reason. Add a `clear(path: Path | None = None) -> None` to
`executor/heartbeat.py` (never raises, mirrors `touch()`'s error handling —
silently no-op on `OSError`, e.g. missing file), and call it from `main()`'s
`KeyboardInterrupt` handler before returning. Do not call it on any other exit
path — a crash must leave the heartbeat stale (fail-open is the documented
design: a stale heartbeat only costs batch tools a guard, never blocks them
past `max_age_seconds`).

### 4. `flp-permanent-failure-no-retry` (separate change, same file)

`poll_once`'s `except Exception as exc:` (line 147) treats every handler
failure identically: retry with backoff, eventually dead-letter. Two known
PyFLP failure modes are permanent, not transient: `ReorderNotSupported` (raised
when a mixer-sorting rule needs PyFLP to reorder inserts, which it cannot do —
see `docs/plan.md`'s Phase 2 section) and `FileNotFoundError` (the target
`.flp` path no longer exists). Retrying either three times wastes the backoff
window for nothing — the outcome cannot change. Import both exception types
(check `executor/flp/sort.py` for where `ReorderNotSupported` is defined/
raised — read it, don't guess the import path, but do NOT edit that file) and
route them straight to dead-letter on first occurrence, skipping the
retry/backoff path other exceptions get. Keep the existing generic-exception
retry behavior unchanged for everything else.

### Also fold in: `poller-invariant-tests`

Add tests asserting: the loop calls `touch_heartbeat()` each iteration, and
`flp_sort` is registered in `DEFAULT_HANDLERS`. (Currently nothing asserts
either — deleting `poller.py`'s heartbeat call or the `flp_sort` registration
line breaks no existing test.)

## Verification

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-poller tests/executor/test_poller.py tests/executor/test_heartbeat.py
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-poller --ignore=tests/db/test_jobs_integration.py
```

## Report

For each of the four fixes plus the invariant tests: what was wrong, the fix,
the test. Name the exact import path used for `ReorderNotSupported`.
