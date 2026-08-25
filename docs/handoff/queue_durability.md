# Queue durability — handoff

Lane: `db/`, `executor/`, `tests/executor/`, `tests/db/`, plus the narrowly
authorized read-only addition to `bus/status.py`. Full design in
`docs/tasks/queue_durability.md`. No commit made.

## What landed

- **Handler registry, consulted at startup.** `executor/poller.py` gains
  `HandlerRegistration(handler, timeout_seconds)` and `DEFAULT_HANDLERS: dict`
  (empty, per the constraint below), which `main()` now builds once and
  passes to every `poll_once` call — the registry is real state, not an
  ad hoc per-call argument. An unregistered kind raises before any
  checkpoint/dispatch, is logged at `WARNING` with only the job id (no
  kind/payload leakage — verified by test), and is routed through the same
  retry/backoff/dead-letter path as any other failure rather than an
  immediate hard fail. It never crashes the poll loop.
- **`attempts`/`max_attempts` columns + migration.**
  `db/migrations/0002_job_retries.sql` adds `attempts`, `max_attempts`
  (default 5, overridable per job via `enqueue(..., max_attempts=...)`), and
  `timeout_seconds` (default 300). Additive only — existing rows backfill
  via column defaults, no drop/rename of anything from 0001.
- **Exponential backoff.** `poller.backoff_seconds(attempts)` = `min(cap,
  base * 2**(attempts-1))`. **Base = 5s, cap = 300s (5 min)** — enough
  headroom to avoid hammering a flaky dependency immediately, capped so a
  single-laptop executor's worst-case retry latency stays bounded. Directly
  unit-tested (`test_poll_once_backoff_spacing_doubles_with_a_cap`).
- **Per-job timeout, configurable per kind.** `HandlerRegistration.timeout_seconds`
  is set per registry entry. The handler runs on a daemon `threading.Thread`
  (deliberately not `ThreadPoolExecutor`, whose default workers are
  non-daemon and would block process exit on a hung handler); the poller
  waits on the timeout and, if it fires, retries the job immediately rather
  than blocking. The claimed job's row also gets its `timeout_seconds`
  pushed from the registry right after claim (`set_job_timeout` RPC), so the
  database's own stale-lease check uses the real per-kind value, not the
  generic 300s default.
- **Dead-letter terminal state.** New `retry_or_dead_letter_job` RPC:
  requeues with backoff while `attempts < max_attempts`, else transitions to
  `dead_letter`. Exercised for handler exceptions, timeouts, and
  unregistered kinds alike.
- **Crash-mid-run recovery, not just handler-hang recovery.** `claim_next_job`
  now also reclaims a `status='running'` row whose lease
  (`updated_at + timeout_seconds`) has expired — this is what actually fixes
  "a job that dies mid-run is lost", since an in-process timeout can't help
  if the whole executor process is the thing that died. A stale row that has
  already exhausted `max_attempts` is dead-lettered by the same statement
  instead of being reclaimed again, so a crash-looping job terminates rather
  than retrying forever.
- **Atomic single-claim semantics preserved.** Same single-statement
  `for update skip locked` shape as before, just a wider `WHERE`. For any row
  that has *not* exceeded its own timeout, exactly one executor can ever
  claim it — unchanged. A row that *has* exceeded its timeout is
  deliberately eligible for a second claim; that's the retry mechanism
  itself, the same trade-off every lease-based queue makes (documented in
  the brief). Proven two ways: an in-memory concurrency test with a real
  `threading.Lock` (`tests/db/test_jobs.py::test_concurrent_claims_never_double_claim_or_drop_a_job`,
  16 threads / 8 jobs, always ran, passing) and a live-Supabase-gated
  integration test (`tests/db/test_jobs_integration.py::test_real_supabase_concurrent_claims_never_double_claim_or_drop_a_job`)
  that will run once 0002 is applied — see "what is needed".
- **`/status` surfaces attempts and dead-letter counts, without restructuring
  it.** `bus/status.py` gains `QueueStatusReader.retry_health()` →
  `{"dead_letter_count": int, "retried_job_count": int}`, and
  `status_payload`/`create_status_handler` gain an **optional**, default-`None`
  `retry_health` dependency. Every existing call produces byte-identical
  output to before; the key only appears when a caller opts in.
  `_QUEUE_STATUSES` was deliberately **not** widened to include
  `"dead_letter"` — `tests/status/test_live_queue_status.py` (outside this
  lane, not run here) asserts `queue_depths()` returns an exact 4-key dict,
  and widening it would have broken a test this lane cannot fix. Dead-letter
  visibility lives entirely in the new `retry_health` key instead.
- **`memory_extract` (or any other kind) is not registered.** `DEFAULT_HANDLERS`
  is empty by design, per the dispatch constraint. This lane is mechanism
  only.

## Tests

`tests/executor/` and `tests/db/` only, as instructed:

```
.venv\Scripts\python.exe -m pytest -q tests/executor tests/db
31 passed, 1 skipped in ~6s
```

The 1 skip is the new live-concurrency integration test, self-skipping with
a clear reason because 0002 isn't applied live yet (see below) — it does not
hard-fail with a confusing schema error.

New coverage added, matching every scenario the dispatch asked for:
- Unregistered kind rejected without killing the poller, and without
  leaking kind/payload —
  `test_poll_once_unknown_kind_is_rejected_and_retried_without_leaking_kind_or_payload`,
  `test_poll_once_unknown_kind_dead_letters_once_attempts_are_exhausted`,
  `test_poll_once_unknown_kind_never_raises_so_the_poller_keeps_running`.
- Timeout triggers retry, not loss —
  `test_poll_once_handler_exceeding_its_timeout_is_retried_not_lost`,
  `test_poll_once_handler_exceeding_its_timeout_dead_letters_once_exhausted`,
  plus DB-level `test_stale_running_job_is_reclaimed_after_its_own_timeout`
  / `test_live_running_job_within_its_timeout_is_not_reclaimed`.
- Backoff spacing — `test_poll_once_backoff_spacing_doubles_with_a_cap`
  (pure-function unit test of the exact base/cap formula) plus
  `test_retry_or_dead_letter_requeues_with_backoff_while_attempts_remain`.
- Max-attempts exhaustion lands in dead-letter —
  `test_poll_once_dead_letters_a_failed_handler_once_max_attempts_is_exhausted`,
  `test_retry_or_dead_letter_dead_letters_once_max_attempts_is_exhausted`.
- No double-claim under concurrent poll —
  `test_concurrent_claims_never_double_claim_or_drop_a_job` (in-memory,
  lock-based, always runs) and
  `test_real_supabase_concurrent_claims_never_double_claim_or_drop_a_job`
  (live, gated).

One pre-existing test flaked once during a combined run
(`test_real_supabase_full_job_lifecycle`, unmodified by this lane) and
passed on every isolated rerun (3/3) and every subsequent combined rerun.
`docs/context.md` already records this specific test's prior flakiness
(`WinError 10013`), so this is a known characteristic of the live network
dependency, not a regression introduced here.

## What is needed

1. **Apply `db/migrations/0002_job_retries.sql` to the live Supabase
   project.** This venv has no Postgres driver (`psycopg2`/`psycopg`) and no
   `supabase`/`psql` CLI on PATH; adding one means touching
   `requirements.txt`, which this lane cannot do. Unlike the earlier L1
   migration brief, this dispatch did not explicitly authorize a live schema
   write, so none was attempted — flagging it here rather than assuming.
   It's additive only (no drops/renames), same shape as the already-applied
   0001. Once applied, rerun
   `tests/db/test_jobs_integration.py::test_real_supabase_concurrent_claims_never_double_claim_or_drop_a_job`
   to get the live proof; it's already skip-gated so this needs no code
   change, just running it.
2. **Wire `retry_health=` into the actual `/status` route in `bus/main.py`.**
   Not owned by this lane. The dependency is
   `lambda: QueueStatusReader.from_repository(<jobs repository>).retry_health()`,
   same pattern as the existing `queue_depths`/`last_job` wiring.
3. One orphaned probe row (`kind` prefixed `queue-durability-probe-`, status
   `running`) was left in the live `jobs` table by an early version of the
   schema-readiness probe in `tests/db/test_jobs_integration.py`, before that
   probe had a cleanup-on-failure path. The probe now always terminalizes
   its row (fixed in this lane), but that one earlier row was not manually
   swept — harmless (unique disposable kind, invisible to any real
   `kind_filter`), but flagging for completeness since agents.md asks for
   exact state.

## What was specified but not done

- **Live application of the 0002 migration** — not done, see above. This is
  the one concrete gap between "mechanism built and tested" and "mechanism
  live." Everything else in the brief (registry, columns, backoff, timeout,
  dead-letter, atomic claim, `/status` addition, tests) is implemented and
  passing against the code as written; the live proof for the concurrency
  guarantee specifically needs that migration applied first.
