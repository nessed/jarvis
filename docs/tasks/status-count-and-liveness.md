# status-count-queries + status-distill-chain-liveness

Two `docs/plan.md` jobs on `bus/status.py`, named "do as one pass" there —
same file, done as one lane. Both are genuine gaps `docs/plan.md`'s own
table never spelled out (only named in a summary line); the real spec for
each is below, sourced from `docs/audit/blueprint-drift.md`. BUILD role: do
not commit, do not touch `requirements.txt`.

Read `bus/status.py` in full first — it's short (~125 lines),
`QueueStatusReader` already has `queue_depths()`, `last_job()`, and
`retry_health()`, each hitting the same Supabase `jobs` table via
`self._client.table("jobs").select(...).execute()`.

## Job 1 — status-count-queries

**The gap:** `queue_depths()` (`bus/status.py:30-38`) does
`self._client.table("jobs").select("status").execute()` — fetches every
row's `status` column and counts in Python. `retry_health()` (lines 55-72)
does the same with `"status,attempts"`. Both scale linearly with total job
count, and both were flagged in the same session as the pattern already
fixed elsewhere: commit `14629c0` replaced an identical "fetch everything,
count in Python" pattern in `memory/store.py`'s `undistilled_turns()` and
Mem0 search's over-fetch bound with real SQL `COUNT`/indexed queries. Do the
equivalent here: use Supabase/PostgREST's actual count/aggregate support
(check what the `postgrest-py`/`supabase-py` client this repo uses exposes —
`.select("status", count="exact")` with a `.execute()` returning a `.count`
field is the standard PostgREST pattern, but verify the actual installed
client version's API rather than assuming; grep `requirements.txt` for the
pinned `supabase`/`postgrest` version and check its actual response shape,
or how other call sites in this repo already read `.count` if any do) rather
than pulling every row.

`queue_depths()` needs a per-status count — either one `GROUP BY`-shaped
call if the client supports it cleanly, or one count call per status value
in `_QUEUE_STATUSES` (five now, including `dead_letter`) if it doesn't;
pick whichever is fewer round trips for what this client version actually
offers, and say which you picked and why. `retry_health()` needs a count of
`status = 'dead_letter'` rows and a count of `attempts > 1` rows — two count
queries instead of one full-table fetch.

**Keep the existing return shapes identical** — `queue_depths()` still
returns `dict[str, int]` keyed by every value in `_QUEUE_STATUSES`,
`retry_health()` still returns `{"dead_letter_count": int, "retried_job_count": int}`.
This is a query-efficiency change, not a payload-shape change. Existing
tests in `tests/status/test_live_queue_status.py` use a `FakeSupabaseClient`
— you will need to extend that fake to support whatever query shape you
choose (count-mode selects, or per-status filtered counts) since its current
`.execute()` just returns a canned `SimpleNamespace(data=[...])` with no
`.count` attribute. Update the fake and its existing tests to match the new
query shape, and add a test that asserts the actual query calls made (query
count, filter arguments) so a regression back to fetch-everything would be
caught.

## Job 2 — status-distill-chain-liveness

**The gap** (`docs/audit/blueprint-drift.md:837-842`, quoted in full):

> Whether the distill chain is currently alive in the live queue, or already
> dead-lettered out of existence. One query: rows where `kind =
> 'distill_memory'`, grouped by status. No `queued`/`running` row plus at
> least one `dead_letter` means no distillation has happened since it died.
> `/status` would answer it, but requires the bearer token from `.env`,
> which this audit did not read.

Build this into `/status`'s payload: add a method to `QueueStatusReader`
(naming your choice — `distill_chain_health()` is a reasonable one,
consistent with `retry_health()`'s naming) that queries `jobs` filtered to
`kind = 'distill_memory'`, and reports enough for a caller to answer the
audit's exact question — at minimum, whether any row is currently
`queued`/`running` (alive) and whether any row is `dead_letter` (has died at
least once). Read `executor/handlers/distill.py`'s module docstring first
(it explains the self-re-enqueuing chain mechanism in depth — "Forks never
merge", "the successor write carries a veto...") so the liveness signal you
build actually reflects how the chain is meant to behave, not a guess.

Wire it into `status_payload()`/`create_status_handler()`
(`bus/status.py:80-124`) the same additive way `retry_health` was added:
optional parameter, omitted from the payload shape entirely when not
supplied, so every existing caller reproduces the exact prior payload shape.

**Do not touch `bus/main.py`.** It is claimed and actively being edited by a
concurrent lane (`webhook-message-dedup`) right now. `create_app()` there
would need one new line to actually pass your new `distill_chain_health`
(or whatever you name it) through to `create_status_handler()`, but that is
integration work for whoever merges both lanes, not this one. Build and test
the capability entirely within `bus/status.py` and its tests, leave it
unwired at the `create_app()` call site, and say exactly what one-line
addition the integrator needs to make in your report.

## Tests

Extend `tests/status/test_live_queue_status.py` for both jobs: the new
count-query shape for job 1 (as described above), and for job 2 — a fake
queue with a `distill_memory` row in `queued` status reports alive; a fake
queue with only a `dead_letter`-status `distill_memory` row (no
queued/running) reports dead; a fake queue with zero `distill_memory` rows
at all reports the "never run" case distinctly from "died" if that
distinction matters (say whether it does and why); the `/status` endpoint
test confirms the new field appears in the JSON response when wired.

## Verification

Run the full offline suite exactly as CLAUDE.md specifies:

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
```

Cite the output. Do not report done without it. Do not commit. Report back:
the exact query mechanism you used for job 1 and why (round-trip count,
what the client version actually supports), the exact liveness signal shape
you added for job 2, whether you touched `bus/main.py` and what exactly,
test counts before/after, and anything above you could not complete and why.
