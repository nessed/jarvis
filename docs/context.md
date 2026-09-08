# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `ff1098e Mark U18 done: the owner id is set` on `main`, 7 ahead, 0 behind origin.

**Working tree:** 14 changed (plus 19 untracked)

```
  M CLAUDE.md
  M  README.md
   M docs/board/README.md
  M  docs/board/USER-TASKS.md
   M docs/board/tasks/bus-offbox-packaging.md
   M docs/board/tasks/vps-harden-deploy.md
  M  docs/state.md
  M  executor/conversation/service.py
  M  memory/conversation.py
  M  memory/service.py
  M  router/routing.py
  M  tests/executor/test_conversation_service.py
  ...and 2 more
```

**Offline suite:** 1604 passed, 10 deselected in 96.96s (0:01:36) _(recorded 2026-09-09)_

**Live acceptance suite:** 1 passed, 1 warning in 34.04s _(recorded 2026-09-03)_

**Recent commits**

- `ff1098e` Mark U18 done: the owner id is set  _(2026-09-09)_
- `5108034` Write this week's handoff  _(2026-09-09)_
- `ca95383` Ask both questions in one call, behind a flag that stays off  _(2026-09-09)_
- `673636a` Check who is actually messaging before answering them  _(2026-09-09)_
- `75034ac` Make the router's deadline an actual wall clock  _(2026-09-09)_
- `305a2eb` Stop paying the same 1.2 seconds on every message  _(2026-09-09)_
- `d7c19ef` Give the router a deadline it can actually hit  _(2026-09-09)_
- `14cdbd0` Say where the seconds went, instead of guessing  _(2026-09-09)_

<!-- END GENERATED -->

## Now

Five board tasks landed 9 Sep: the router got real per-call and cascade
deadlines, the reply path stopped paying ~1.2s per message on recall, the
sender is now checked against `JARVIS_OWNER_WA_ID` before any recall or
action, and one-call classify+reply is built and evaluated behind a flag that
is still off. `docs/board/HANDOFF.md` is this week's handoff.

**The bot is refusing everyone until U18 is pasted** — the owner check is
fail-closed and the variable is unset. Also Ali's: Q17-D4 (the single-call
table is under it now), U20 (the live latency probe), U17, Q11-Q15.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
