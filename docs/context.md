# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `123b724 Pin the queue client timeout so a hung connection can't stall every message` on `main`, 11 ahead, 0 behind origin.

**Working tree:** 8 changed

```
  M  docs/state.md
  A  docs/tasks/deps-flp.txt
  A  docs/tasks/flp-poc.md
  A  executor/flp/__init__.py
  A  executor/flp/sort.py
  M  executor/poller.py
  M  requirements.txt
  A  tests/executor/test_flp_sort.py
```

**Offline suite:** 196 passed, 1 deselected in 5.29s _(recorded 2026-08-27)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `123b724` Pin the queue client timeout so a hung connection can't stall every message  _(2026-08-27)_
- `603cec6` Make conversation memory work by taking extraction off the reply path  _(2026-08-27)_
- `a35b654` Add Phase 1 scalability and blueprint review  _(2026-08-27)_
- `c91279c` Fix run_backfill's usage docstring and record a near-miss with live traffic  _(2026-08-27)_
- `129de3a` Disable conversation memory writes by default  _(2026-08-27)_
- `f11cbb8` Fix three bugs that stopped live WhatsApp replies, and reply before remembering  _(2026-08-27)_
- `afa6b58` Add a resumable backfill runner over the opted-in intake folder  _(2026-08-26)_
- `5b9c7d6` Close the retry_health and verify-token-logging blockers in state.md  _(2026-08-26)_

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
