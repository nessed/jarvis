---
id: db-maintenance
status: blocked
lane: AUTO
priority: 3
phase: 0
blocked-on: Q9
files: db/jobs.py (hot), db/migrations/, db/migrate.py (new), tests/db/, requirements.txt (orchestrator integrates), docs/state.md
resources: live-jobs-table (EXCLUSIVE — stack down for schema work)
---

# db-maintenance — migration runner, orphan row, retention

## Gate

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

_(empty)_
