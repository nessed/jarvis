# Executor job-dispatch seam

## Blueprint basis

The Phase 0 executor currently proves claim → checkpoint → complete with a
no-op handler. The blueprint’s later phases require deterministic job types
(memory backfill, FLP automation, voice) while preserving the durable,
pull-based laptop executor and safe diagnostics.

## Strict ownership

Own only `executor/poller.py`, `tests/executor/test_poller.py`, and this brief.
Do not edit database/repository code, bus code, router code, package
initializers, requirements, context, or any other test files.

## Task

Replace the implicit Phase 0 no-op default with an explicit injected
kind-to-handler dispatch seam while retaining the existing callable handler
override and one-job lifecycle. Unknown job kinds must fail deterministically,
and stored/logged diagnostics must remain type-only without payload or provider
detail. Preserve successful known-job checkpoint and completion behavior.

## Non-goals

Do not add real job handlers, contact providers, use credentials, poll a live
queue, alter queue schema, or wire bus routing. Do not introduce plugins or
new configuration.

## Tests and dependencies

Use the existing fake repository and pure handlers. Cover known dispatch,
unknown-kind failure, explicit-handler compatibility, and no payload leakage.
No new dependency is expected; do not edit `requirements.txt`. If indispensable,
append only name and rationale to `docs/tasks/deps-executor_dispatch.txt`.

## Completion note (25 August 2026)

Implemented in `executor/poller.py`: `poll_once()` now accepts an injected
`handlers` kind-to-handler mapping while retaining the existing `handler`
override. Unregistered kinds raise a dedicated type-only failure, preserving
the claim -> checkpoint -> fail lifecycle without exposing job kind or payload.
Focused offline tests cover registered dispatch, deterministic unknown-kind
failure, override precedence, and diagnostic non-leakage.
