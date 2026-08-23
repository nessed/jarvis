# Wave B1: durable Supabase job queue

## Ownership

Only edit `db/`, `tests/db/`, and `docs/tasks/deps-db.txt`. Do not commit or
modify any other path, including requirements files.

## Objective

Build the Phase 0.4 job queue while Supabase credentials are pending. Add a
schema migration that creates `jobs` with `id uuid primary key`, `kind text`,
`payload jsonb`, `status text` limited to `queued`, `running`, `done`, or
`failed`, `checkpoint jsonb`, `run_after timestamptz`, `created_at`, and
`updated_at`, plus an index on `(status, run_after)`. Use sensible non-secret
defaults for timestamps and JSON fields.

Implement `db/jobs.py`, shared by bus and executor, with `enqueue()`,
`claim_next(kind_filter)`, `checkpoint(job_id, state)`, `complete(job_id)`, and
`fail(job_id, err)`. `claim_next` must be atomic using `SELECT ... FOR UPDATE
SKIP LOCKED` (or equivalently safe Postgres RPC) so multiple executor workers
cannot take the same job. Claim only due queued work and transition it to
running. Preserve structured checkpoint/error state where appropriate.

Write unit tests with a replaceable repository/client and the full lifecycle.
When `SUPABASE_URL` and `SUPABASE_KEY` are present in `.env`, run an integration
test against the real project, exercising the entire lifecycle. Never read,
print, or log the credentials. Until then, complete migration/interface/mocks
and report the real-project test as blocked.

## Dependency and safety rules

Append any exact new pinned dependency to `docs/tasks/deps-db.txt`; the
orchestrator alone merges requirements. Never issue destructive database
commands, including `DROP TABLE`.
