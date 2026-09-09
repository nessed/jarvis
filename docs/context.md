# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `138f07f Absorb Fable review's 8 Sep provider/speech fact corrections` on `main`, 3 ahead, 0 behind origin.

**Working tree:** 9 changed (plus 16 untracked)

```
  M  .gitignore
   M CLAUDE.md
   M docs/board/README.md
  A  docs/board/tasks/extraction-model-spike.md
   M docs/board/tasks/vps-harden-deploy.md
  M  docs/state.md
  A  docs/tasks/extraction-model-spike-report.md
  A  tests/tools/test_bench_extraction.py
  A  tools/bench_extraction.py
```

**Offline suite:** 1679 passed, 10 deselected in 84.74s (0:01:24) _(recorded 2026-09-09)_

**Live acceptance suite:** 1 passed, 1 warning in 34.04s _(recorded 2026-09-03)_

**Recent commits**

- `138f07f` Absorb Fable review's 8 Sep provider/speech fact corrections  _(2026-09-09)_
- `9e47b7e` Package the brain, not just the inbox, for the rented x86 box  _(2026-09-09)_
- `ca34952` Answer text messages right away; only voice still queues  _(2026-09-09)_
- `0ff9639` Write the idle circle's colour down, and make it reproducible  _(2026-09-09)_
- `7f97f58` Stop JARVIS answering like it has amnesia  _(2026-09-09)_
- `ff1098e` Mark U18 done: the owner id is set  _(2026-09-09)_
- `5108034` Write this week's handoff  _(2026-09-09)_
- `ca95383` Ask both questions in one call, behind a flag that stays off  _(2026-09-09)_

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
