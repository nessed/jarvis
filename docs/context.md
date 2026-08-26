# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `0de7c89 Add one-command startup so the whole stack comes up together` on `main`, 13 ahead, 0 behind origin.

**Working tree:** 3 changed

```
  M  docs/context.md
  M  docs/scalability-review.md
  M  docs/state.md
```

**Offline suite:** 196 passed, 1 deselected in 4.98s _(recorded 2026-08-27)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `0de7c89` Add one-command startup so the whole stack comes up together  _(2026-08-27)_
- `607bde1` Add PyFLP proof-of-concept scaffolding for Phase 2  _(2026-08-27)_
- `123b724` Pin the queue client timeout so a hung connection can't stall every message  _(2026-08-27)_
- `603cec6` Make conversation memory work by taking extraction off the reply path  _(2026-08-27)_
- `a35b654` Add Phase 1 scalability and blueprint review  _(2026-08-27)_
- `c91279c` Fix run_backfill's usage docstring and record a near-miss with live traffic  _(2026-08-27)_
- `129de3a` Disable conversation memory writes by default  _(2026-08-27)_
- `f11cbb8` Fix three bugs that stopped live WhatsApp replies, and reply before remembering  _(2026-08-27)_

<!-- END GENERATED -->

## Now

Replies work and land in seconds. Three things fixed tonight: memory writes
moved off the reply path (store the turn in ~0.5s, distil later), the queue
client's inherited 120s timeout pinned to 10s — one hung connection had been
stalling every queued message behind it — and `start-jarvis.bat`, which brings
the whole stack up in order and re-points WhatsApp itself.

Next, unstarted: schedule `tools/distill_memory.py`, or Phase 2 (FL Studio,
currently blocked on Python 3.12 — see `docs/state.md` blocker 5).

## Waiting on you

Nothing. Run `start-jarvis.bat` to bring it up; Ctrl+C stops it. Messages sent
while it is down wait in the queue rather than being lost.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
