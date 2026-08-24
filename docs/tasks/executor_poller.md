# Executor poller lane

## Ownership

Own only `executor/` and `tests/executor/`. Do not edit `bus/`, `db/`,
`requirements.txt`, docs, or existing tests outside that path. Do not commit.

## Task

Turn the Phase 0 executor placeholder into a safe, pull-based local poller.
`poll_once()` must use the existing `db.jobs` repository contract to atomically
claim one queued job, checkpoint it, and complete it. It must fail a claimed job
with a safe diagnostic if its local handler raises. Do not send WhatsApp replies
or invoke an LLM: Phase 0 only needs durable lifecycle proof. Provide a small
CLI loop suitable for `python -m executor.poller`, with a configurable polling
interval, and unit tests for success, idle, and failure paths.

## Blueprint constraint

Phase 0 is done only when an inbound job survives laptop sleep and progresses
queued → running → done after wake. The executor must be pull-based and use the
existing queue/RPC functions; webhook code remains enqueue-only.
