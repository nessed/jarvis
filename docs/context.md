# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `a35b654 Add Phase 1 scalability and blueprint review` on `main`, 9 ahead, 0 behind origin.

**Working tree:** 11 changed (plus 1 untracked)

```
  M  .gitignore
  M  docs/context.md
  M  docs/state.md
  M  executor/handlers/whatsapp.py
  A  executor/heartbeat.py
  M  executor/poller.py
  A  memory/conversation.py
  A  tests/executor/test_heartbeat.py
  M  tests/executor/test_whatsapp_handler.py
  A  tests/memory/test_conversation.py
  A  tools/distill_memory.py
```

**Offline suite:** 176 passed, 1 deselected in 4.95s _(recorded 2026-08-27)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `a35b654` Add Phase 1 scalability and blueprint review  _(2026-08-27)_
- `c91279c` Fix run_backfill's usage docstring and record a near-miss with live traffic  _(2026-08-27)_
- `129de3a` Disable conversation memory writes by default  _(2026-08-27)_
- `f11cbb8` Fix three bugs that stopped live WhatsApp replies, and reply before remembering  _(2026-08-27)_
- `afa6b58` Add a resumable backfill runner over the opted-in intake folder  _(2026-08-26)_
- `5b9c7d6` Close the retry_health and verify-token-logging blockers in state.md  _(2026-08-26)_
- `fb2eead` Wire retry_health into /status and redact the Meta verify token from access logs  _(2026-08-26)_
- `aea3109` Dedup whatsapp_webhook by Meta's message id  _(2026-08-26)_

<!-- END GENERATED -->

## Now

Memory works again, on a different path. Conversation turns are embedded and
stored verbatim (~0.5s) instead of going through Mem0's 8B extraction inline
(~55s, 0% success on live turns). Verified live: a turn stored and recalled in
0.61s, alongside the 68 backfilled facts. `tools/distill_memory.py` runs the
Mem0 extraction as an offline batch, and refuses to start while the executor is
polling — the guard that was missing when a backfill starved eight messages.

Not done: nothing schedules the distiller yet, so distilled facts lag until it
is run by hand.

## Waiting on you

Nothing. Bus, tunnel and executor are running. The tunnel URL dies whenever
`cloudflared` restarts and needs `tools/repoint_webhook.py` then, not now.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
