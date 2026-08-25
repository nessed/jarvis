# Queue durability — brief

## Ownership

Exactly: `db/`, `executor/`, `tests/executor/`, `tests/db/`,
`docs/tasks/queue_durability.md`, `docs/handoff/queue_durability.md`. A
concurrent lane owns `memory/` and `docs/context.md` — neither is touched here;
state goes to `docs/handoff/queue_durability.md` instead. `bus/status.py` is
edited as a narrowly-scoped, backward-compatible read-only addition per the
dispatch instructions (not in the strict ownership list, but explicitly
authorized there); `bus/main.py` is left untouched since it is not owned here
and wiring the new optional dependency into it is the orchestrator's call.
Only `tests/executor/` and `tests/db/` are run. No commit.

## Gap (from docs/context.md, confirmed by reading executor/poller.py and
db/migrations/0001_jobs.sql)

- `poll_once` takes an ad hoc `handlers` mapping per call; there is no
  registry consulted at executor startup, and `main()` currently calls
  `poll_once()` with no handlers at all — every real job kind is
  "unregistered" today.
- `jobs` has no `attempts`/`max_attempts` columns. `fail_job` is a hard
  terminal state with no retry path.
- No backoff: nothing schedules a delayed re-attempt.
- No per-job timeout: a hung handler blocks the poller forever (`poll_once`
  runs the handler synchronously, in-process, with no time bound), and if the
  executor process itself dies mid-run, the claimed row is stuck at
  `status='running'` forever — `claim_next_job` only ever selects
  `status='queued'`, so nothing ever reclaims it.
- No dead-letter state: `failed` is the only terminal failure state and
  carries no distinction between "exhausted retries" and "single hard fail".

## Design

### Schema — `db/migrations/0002_job_retries.sql`

Additive only, no drops/renames of existing columns or rows:

- `attempts int not null default 0` — incremented atomically inside
  `claim_next_job` on every claim (fresh or reclaimed), so it always reflects
  "attempts started", not "attempts finished".
- `max_attempts int not null default 5` — overridable per job at enqueue
  time via a new optional `enqueue(..., max_attempts=...)` kwarg.
- `timeout_seconds int not null default 300` — the row's effective per-job
  timeout. The executor overwrites this immediately after claiming, from its
  own per-kind registry value (see below), via a new `set_job_timeout` RPC.
  This is what makes the timeout "configurable per kind" while still living
  on the row so the atomic claim SQL can reason about staleness without
  knowing about the Python-side registry.
- `status` check constraint gains `dead_letter` alongside the existing five
  values. `failed` is kept as-is (unchanged `fail_job` RPC, immediate hard
  terminal, no retry) for any future caller that wants a genuinely
  non-retryable failure; the new default poller failure path no longer uses
  it and instead goes through the new `retry_or_dead_letter_job` RPC.
- `claim_next_job` gains a second eligibility clause: a `status='running'`
  row whose `updated_at + timeout_seconds` has passed is stale and eligible
  for reclaim, atomically, in the same `for update skip locked` statement
  that already prevents double-claims among live rows. Before that, a
  one-statement sweep dead-letters any stale `running` row that has already
  exhausted `max_attempts`, so a crash-looping job can't be reclaimed forever
  — it terminates instead.
- New RPC `retry_or_dead_letter_job(p_job_id, p_error, p_delay_seconds)`:
  atomically requeues (`status='queued'`, `run_after = now() + delay`) if
  `attempts < max_attempts`, else dead-letters. Backoff math (the actual
  delay value) is computed in Python so it's directly unit-testable; the SQL
  just applies it.
- New RPC `set_job_timeout(p_job_id, p_timeout_seconds)`: the row-level write
  the executor uses to push its per-kind timeout onto a freshly claimed job.

**Double-claim guarantee, precisely stated:** for any row that has *not*
exceeded its own `timeout_seconds`, at most one executor can ever hold it —
unchanged from the original `for update skip locked` design, now just with a
wider (but still single-statement, still row-locked) eligibility set. A row
*is* deliberately eligible for a second claim once its lease has expired —
that is the retry mechanism, and it is the same accepted trade-off every
lease-based queue (SQS visibility timeout, Sidekiq, Celery) makes: size the
timeout to the job, don't rely on a hung handler self-reporting. This is
what actually fixes "a job that dies mid-run is lost" — a crashed executor's
claimed row eventually becomes reclaimable by a surviving executor.

### Backoff

`delay(attempts) = min(cap, base * 2**(attempts-1))`, **base = 5s, cap =
300s (5 min)**. Rationale: base avoids hammering a flaky handler
immediately; a 5-minute cap keeps worst-case retry latency for a
single-laptop-executor bounded without being so tight that transient
failures get retried into the same failure window repeatedly. Six doublings
(5s→10→20→40→80→160→300, capped) covers the plausible range from a
momentary blip to a genuinely broken external dependency.

### Handler registry and timeout — `executor/poller.py`

- `HandlerRegistration(handler, timeout_seconds)` — an explicit pairing of a
  handler with its own timeout. A `handlers` mapping entry may be either a
  raw callable (wrapped with `DEFAULT_HANDLER_TIMEOUT_SECONDS = 300.0`) or an
  explicit `HandlerRegistration` for a kind that needs a different bound.
  `main()` builds this mapping once at startup (`DEFAULT_HANDLERS`, currently
  empty — see constraint below) and passes it to every `poll_once` call, so
  the registry really is "consulted by job kind at startup", not
  reconstructed ad hoc.
- An unregistered kind raises `UnknownJobKindError` *before* any checkpoint
  or handler dispatch, is logged at `WARNING` with the job id only (no
  kind/payload leakage, preserving the existing safe-diagnostics property),
  and is routed through `retry_or_dead_letter` like any other failure — so a
  kind that gets registered in a later deploy can still succeed on retry,
  and an actually-unfixable kind dead-letters visibly instead of vanishing.
  This never raises out of `poll_once` or crashes the poll loop; `main`'s
  existing `except Exception` + `logger.warning` + continue-polling loop is
  unchanged and still the outermost safety net.
- Timeout is enforced in-process: the handler runs on a **daemon**
  `threading.Thread` (not `concurrent.futures.ThreadPoolExecutor`, whose
  default workers are non-daemon and would block process/test exit on a
  hung handler); the poller thread waits on a `threading.Event` with the
  registration's timeout. On timeout, `poll_once` returns via
  `retry_or_dead_letter` — the job is marked for retry immediately, without
  waiting for the orphaned thread. That background thread is not killed
  (Python cannot preempt a running thread) and is a known, documented
  limitation: a handler that ignores timeouts and keeps mutating state after
  its deadline is a hazard the *handler* must avoid (checkpoint-aware,
  cooperative cancellation is future-phase work), not something this
  mechanism can fully close from the outside. The DB-side stale-lease
  reclaim is what actually recovers the *job* even if that thread never
  returns.

### Constraint honored

No handler is registered for `memory_extract` or any other kind.
`DEFAULT_HANDLERS` in `executor/poller.py` is an empty mapping with a
comment marking it as the future registration point. This lane builds the
mechanism only.

### `/status` — `bus/status.py`

`retry_health()` added to `QueueStatusReader`, returning
`{"dead_letter_count": int, "retried_job_count": int}` from a single
`status,attempts` read. `status_payload` and `create_status_handler` gain a
new **optional**, default-`None` `retry_health` dependency; when omitted
(every existing call site, since nothing outside this lane knows about it
yet) the returned payload is byte-for-byte identical to today's shape — the
key is only added when a caller opts in. `_QUEUE_STATUSES` is deliberately left unchanged — `tests/status/test_live_queue_status.py`
(outside this lane's ownership, not run here) asserts `queue_depths()`
returns an exact 4-key dict, so widening it would have broken a test this
lane cannot fix. Dead-letter visibility is carried entirely by the new
`retry_health` key instead. Wiring `retry_health=` into the
actual `/status` route lives in `bus/main.py`, which this lane does not own
— flagged in the handoff doc for the orchestrator.

## Explicitly not done here

- The 0002 migration is **not applied to the live Supabase project**. This
  venv has no Postgres driver (`psycopg2`/`psycopg`) and no Supabase/psql CLI
  on PATH, and adding one requires touching `requirements.txt`, which this
  lane cannot do (per `agents.md`, dependencies go through
  `docs/tasks/deps-<lane>.txt` for the orchestrator). Unlike the earlier L1
  migration brief, this dispatch did not explicitly authorize a live schema
  change, so it is treated as needing that authorization rather than assumed.
  A `mcp__claude_ai_Supabase__apply_migration` tool is visible in this
  session, but it is not verified to target the same project as this repo's
  `SUPABASE_URL`, so it is not used for a live schema write on an unverified
  project.
- Because of the above, the live "no double-claim under concurrent poll"
  proof is written as a Supabase-credential-gated integration test
  (matching the existing `tests/db/test_jobs_integration.py` pattern) that
  additionally self-skips if a live probe shows the new columns/RPCs are not
  yet present, rather than hard-failing. It will only actually execute once
  the orchestrator applies `db/migrations/0002_job_retries.sql`.
- No dependency changes; nothing goes in `docs/tasks/deps-queue_durability.txt`
  since the mechanism only needs the standard library (`threading`).
