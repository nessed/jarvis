# Typing indicator latency fix

## Scope

Move the existing best-effort native WhatsApp typing request to the earliest
safe point in the executor handler: after the inbound payload is parsed and
the durable reply-dedup check has passed, but before opening or recalling
conversation memory.  Keep `bus/main.py` enqueue-only as required by the
blueprint's durable laptop-executor architecture.

## Evidence

The handler currently calls `memory.recall()` before `show_typing_indicator()`.
Recall can wait on the local embedding service, so the user sees silence before
Meta receives the typing signal.  The running stack starts the executor with a
three-second idle interval (`tools/start_jarvis.py`); the environment override
is unset.  This lane therefore does not change polling configuration.

## Acceptance

- A non-duplicate inbound text calls the indicator with its actual inbound
  Meta message ID before any memory recall.
- Indicator failures remain non-blocking and replies retain the existing
  durable dedup and send-before-memory-write behavior.
- Focused handler tests pass.
