---
id: db-maintenance
status: blocked
lane: AUTO
priority: 3
phase: 0
blocked-on: U12 (SUPABASE_DB_PASSWORD is an empty placeholder in .env)
files: db/jobs.py (hot), db/migrations/, db/migrate.py (new), tests/db/, requirements.txt (orchestrator integrates), docs/state.md
resources: live-jobs-table (EXCLUSIVE — stack down for schema work)
---

# db-maintenance — migration runner, orphan row, retention

## Gate

**Answered 1 Sep 2026. Driver = `psycopg[binary]`** (v3) — install exactly
that, it is a component decision, not a suggestion. Append it to
`docs/tasks/deps-db-maintenance.txt`; do not edit `requirements.txt`.

**Approved to write the live database, with one carve-out:**

- Migration runner + ledger — approved.
- Retention/index pass — approved.
- The orphaned `queue-durability-probe-` row — **NOT approved for
  deletion.** Report it (id, kind, status, age, payload shape) and leave
  it in place. Ali wants to see it before it goes. Deleting it is a
  separate approval, and sweeping it "while we're in there" is exactly the
  failure this carve-out exists to prevent.

Take `live-jobs-table` EXCLUSIVE for the schema work and expect the stack
down for that window.

Q9: explicit approval to write live schema/rows + the Postgres driver
choice (a component decision — install exactly what Ali named).

## Steps

1. Migration runner + ledger: applies `db/migrations/*` in order, records
   applied versions in a `schema_migrations` table, idempotent, dry-run
   mode. This is what was missing when 0002 sat unapplied and stranded
   four messages.
2. Sweep the orphaned `queue-durability-probe-` row (it now pollutes
   `dead_letter_count` via the stale-lease reclaim path). One targeted
   mutation, logged before/after — this is the only destructive-ish step;
   it is inside Q9's approval, don't re-ask.
3. Retention/index pass as migration 0003: whatever `jobs` needs per the
   old `jobs-index-and-retention` scoping — keep minimal, document each
   index against a real query.
4. All live-queue work serialized: stack down, claim the resource, plan.md
   rules apply. Tests offline against fakes + the (now capable of
   failing) `tests/db/test_jobs_integration.py` live probe for schema
   drift.

## Done when

Runner + ledger live and proven by applying 0003; orphan row gone (cite
before/after counts); suite green; state.md updated.

## Log

**2 Sep 2026 — the runner is built, tested and ready; applying it to the live
database is blocked on U12.** The reporting half is done, and it found more
than the task expected.

### Built and green

- `db/migrate.py` — applies `db/migrations/*.sql` in filename order, once
  each, recording every application in a `public.schema_migrations` ledger
  (version, name, sha256 of the file, applied_at). `--dry-run` connects,
  reads the ledger, prints the plan, and opens no write transaction.
- Each migration and its ledger row commit in **one** transaction. A
  migration that applied without being recorded would be re-applied next
  run; a ledger row without its schema change is a lie the next reader
  trusts. Either is worse than failing, so a failure rolls back and stops.
- A file edited *after* it was applied is reported as a warning and **not**
  re-run. Re-running would apply a diff nobody wrote; refusing outright would
  wedge the database over a reformatted comment.
- A misnamed file is an error, not a silent skip — a migration nobody notices
  is a migration nobody applies, which is precisely how 0002 sat unapplied.
- `db/migrations/0003_jobs_indexes_and_retention.sql` — four indexes, each
  justified in the file against a named query in this tree
  (kind-filtered `claim_next_job`, the 0002 stale-lease reclaim on
  `updated_at`, `/status`'s `last_job` ordering, `/status`'s
  `distill_chain_health` kind counts).
- Retention is a **function that must be called by hand**, defaulting to a
  dry run — not a trigger, not a schedule, and not a `DELETE` in the
  migration. Every finished row is evidence; `docs/state.md` and several task
  logs cite specific job ids as proof that something ran, and a retention
  pass that fired on its own would quietly delete the evidence behind this
  project's own claims. Same reasoning as Q9's orphan-row carve-out.

Driver: `psycopg[binary]==3.3.5`, exactly as Ali named it (Q9), recorded in
`docs/tasks/deps-db-maintenance.txt` and integrated into `requirements.txt`
by CORE.

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-core
1289 passed, 9 deselected, 10 warnings in 65.69s
```

26 of those are new, in `tests/db/test_migrate.py`.

### Blocked: `SUPABASE_DB_PASSWORD` is an empty placeholder

```
.venv\Scripts\python.exe -m db.migrate --dry-run
error: set SUPABASE_DB_URL, or both SUPABASE_URL and SUPABASE_DB_PASSWORD
```

The key exists in `.env` with no value. The REST key that is populated can
read and write *rows* — the orphan report below is proof — but PostgREST
cannot run DDL, so `0003` cannot be applied without a real Postgres
connection. Filed as **U12**; it is a credential, so it is Ali's.

Checked and rejected as an alternative: the Supabase MCP server connected to
this session lists five projects, none of which is this one
(`yhbymzznlahbxrrqqpof`). It is a different account. Not touched.

### The orphan row is seven rows, and it is not the problem

Q9 approved reporting one orphaned `queue-durability-probe-` row and
explicitly forbade deleting it. There are **seven**, all created 25 Aug 2026,
all with empty payloads, none deleted:

| id | kind suffix | status | attempts | last touched | checkpoint error |
|---|---|---|---|---|---|
| `8e94f2ac` | `6887ba63…` | dead_letter | 5/5 | 26 Aug | no handler registered for job kind |
| `6995eb37` | `9b4ff194…` | dead_letter | 5/5 | 26 Aug | no handler registered for job kind |
| `dd04f92f` | `e5de59a2…` | dead_letter | 5/5 | 26 Aug | no handler registered for job kind |
| `17854c95` | `7ab2c3cc…` | dead_letter | 5/5 | 26 Aug | no handler registered for job kind |
| `c9b1f917` | `cdb0439a…` | dead_letter | 5/5 | 26 Aug | no handler registered for job kind |
| `ddfab8cb` | `4a0e1cd6…` | failed | 0/5 | 25 Aug | probe cleanup (schema check failed) |
| `32b3c854` | `1bf6b971…` | failed | 0/5 | 25 Aug | probe cleanup (schema check failed) |

All seven left in place. **The premise that they pollute `dead_letter_count`
is off by an order of magnitude**: of 103 dead-lettered rows, five are
probes. Deleting all seven would change the count from 103 to 98.

### What is actually in the queue, and it is worse

376 rows: 255 `done`, 103 `dead_letter`, 17 `failed`, 1 `queued`.

**98 of the 103 dead-lettered rows are `distill_memory`.** The batch
distillation chain died 98 times between 29 Aug 13:06 and 30 Aug 20:52 UTC:

```
  83x executor handler failed (EmbeddingError)
  12x executor handler failed (LLMError)
   3x exhausted after stale timeout
```

And the chain is **not dead — it is stalled**. Exactly one row is `queued`:
`dd853e77`, kind `distill_memory`, `run_after` **30 Aug 20:53**. It has been
ripe and unclaimed for over two days, which means no `background-worker` has
polled since then.

That settles `docs/audit/blueprint-drift.md` §4's first open question, which
asked whether the chain was alive or had dead-lettered out of existence. The
answer is neither: it is alive, ripe, and nothing is claiming it.

The failure itself is not diagnosed here and is not this task's. What is
known: Ollama is up right now and `nomic-embed-text:latest` is installed, so
whatever produced 83 `EmbeddingError`s on 29-30 Aug is not "the model was
never pulled". `memory/embeddings.py` raises that same error for a timeout, a
connect failure and a non-200 alike, so the checkpoint cannot tell those
apart — which is itself worth fixing, since 83 identical messages hide three
different causes.

By contrast `whatsapp_webhook` is 175 rows, **all `done`**. The reply path is
healthy; the memory path is not.

### Filed, and not fixed here

- **U12** — fill `SUPABASE_DB_PASSWORD`, unblocking the live half.
- **`distill-chain-stall`** — needs a board entry: 98 dead-lettered rows, one
  ripe row unclaimed for two days, and an `EmbeddingError` that conflates
  timeout / connect / HTTP status. `docs/board/README.md` is held by
  `CORE/agent-harness`, so whoever next holds the board files it. Recorded
  here and in the handoff so it is not lost.

### Still to do when U12 lands

`--dry-run`, then apply, then confirm `schema_migrations` holds 0001-0003 and
the four indexes exist. One command each; the runner is done.
