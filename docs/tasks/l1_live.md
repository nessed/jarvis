# L1 follow-up — live secure queue lifecycle

## Ownership

You may edit only `db/` and `tests/db/`. Do not commit. Do not edit
`docs/context.md`; report to the orchestrator. Never expose configuration
values.

## Preconditions

The revised secure `0001_jobs.sql` migration has been applied to the target
Supabase project, and `SUPABASE_SECRET_KEY` is present locally.

## Objective

Run `tests/db/test_jobs_integration.py` against the live project. Verify the
full enqueue → atomic claim → checkpoint → complete lifecycle using only the
server-side key. Confirm publishable credentials remain rejected by the client
and do not relax RLS or function privileges. Make focused corrections only
under your owned paths if the live test exposes a genuine defect. Report safe
pass/fail evidence.
