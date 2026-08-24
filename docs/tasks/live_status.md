# Live status lane

## Ownership

Own only `bus/`, `tests/status/`, and this brief. Do not edit `executor/`,
`db/`, `requirements.txt`, docs other than this brief, or existing tests outside
`tests/status/`. Do not commit.

## Task

Make the running default FastAPI app expose real, non-secret queue observability
through its existing protected `/status` endpoint. Wire the existing Supabase
job repository into the default app without weakening RLS or reading/printing
secret values. Report queue depth by status and the latest job as safe metadata
(no webhook payload). Preserve `create_app` dependency injection and all current
tests. Add focused tests under `tests/status/`.

## Blueprint constraint

Phase 0 requires watching jobs move queued → running → done. `/status` is
bearer protected; unauthenticated routes must remain 401 and webhooks must stay
enqueue-only.
