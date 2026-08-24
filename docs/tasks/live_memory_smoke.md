# Live local-memory smoke test

## Scope and ownership

This lane owns this brief, `docs/context.md`, and only the generated isolated
temporary memory database/artifacts. It must not change production code,
configuration, dependencies, or ingest inputs.

## Validation

Open an explicitly configured temporary SQLite database through the project
local-memory runtime, save one generic non-personal fact, recall it through the
service, and verify the expected fact. Close and remove the temporary database
and any SQLite sidecar/vector artifacts after success.

## Privacy

Use only the fixed generic test fact. Do not read or ingest a user corpus, and
do not display `.env` or secrets.
