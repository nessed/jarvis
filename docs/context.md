# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `0ff9639 Write the idle circle's colour down, and make it reproducible` on `main`, in sync with origin.

**Working tree:** 13 changed (plus 18 untracked)

```
  M CLAUDE.md
  A  bus/conversation_runner.py
  M  bus/main.py
   M docs/board/README.md
   M docs/board/tasks/bus-offbox-packaging.md
  A  docs/board/tasks/conversation-inline-reply.md
   M docs/board/tasks/vps-harden-deploy.md
  M  docs/context.md
  M  docs/state.md
  M  executor/latency.py
  A  tests/bus/test_conversation_runner.py
  M  tests/executor/test_latency.py
  ...and 1 more
```

**Offline suite:** 1620 passed, 10 deselected in 97.05s (0:01:37) _(recorded 2026-09-09)_

**Live acceptance suite:** 1 passed, 1 warning in 34.04s _(recorded 2026-09-03)_

**Recent commits**

- `0ff9639` Write the idle circle's colour down, and make it reproducible  _(2026-09-09)_
- `7f97f58` Stop JARVIS answering like it has amnesia  _(2026-09-09)_
- `ff1098e` Mark U18 done: the owner id is set  _(2026-09-09)_
- `5108034` Write this week's handoff  _(2026-09-09)_
- `ca95383` Ask both questions in one call, behind a flag that stays off  _(2026-09-09)_
- `673636a` Check who is actually messaging before answering them  _(2026-09-09)_
- `75034ac` Make the router's deadline an actual wall clock  _(2026-09-09)_
- `305a2eb` Stop paying the same 1.2 seconds on every message  _(2026-09-09)_

<!-- END GENERATED -->

## Now

Six board tasks have landed 9 Sep: router deadlines, the ~1.2s/message recall
cut, owner-id gating on `JARVIS_OWNER_WA_ID`, one-call classify+reply (flag
still off), and now `conversation-inline-reply` — text replies answer
in-process from the bus instead of queueing (`JARVIS_INLINE_REPLY`, default
on); voice still queues. `docs/board/HANDOFF.md` is this week's handoff.

**U18 is done** (Ali pasted `JARVIS_OWNER_WA_ID`) — the bot answers him now.
**U20 is the remaining live gap**: no `reply-latency` line has been read back
from a real Graph send since the stack went down 4 Sep, for either the queue
path or the new inline path. Needs `JARVIS_LIVE_WHATSAPP_TO` + the stack up.
Also Ali's: Q17-D4 (single-call flip), U17, Q11-Q15.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
