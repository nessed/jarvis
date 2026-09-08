# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `75034ac Make the router's deadline an actual wall clock` on `main`, 3 ahead, 0 behind origin.

**Working tree:** 19 changed (plus 20 untracked)

```
  M  .env.example
   M CLAUDE.md
   M docs/board/HANDOFF.md
   M docs/board/QUESTIONS.md
   M docs/board/README.md
   M docs/board/tasks/bus-offbox-packaging.md
  A  docs/board/tasks/owner-identity-check.md
   M docs/board/tasks/vps-harden-deploy.md
  M  docs/state.md
  M  executor/conversation/__init__.py
  M  executor/conversation/service.py
  M  executor/handlers/whatsapp.py
  ...and 7 more
```

**Offline suite:** 1556 passed, 10 deselected in 60.56s (0:01:00) _(recorded 2026-09-09)_

**Live acceptance suite:** 1 passed, 1 warning in 34.04s _(recorded 2026-09-03)_

**Recent commits**

- `75034ac` Make the router's deadline an actual wall clock  _(2026-09-09)_
- `305a2eb` Stop paying the same 1.2 seconds on every message  _(2026-09-09)_
- `d7c19ef` Give the router a deadline it can actually hit  _(2026-09-09)_
- `14cdbd0` Say where the seconds went, instead of guessing  _(2026-09-09)_
- `9598d37` Pull the reply brain out of the WhatsApp closure  _(2026-09-09)_
- `ddfd7ed` Measure the reply path instead of adding up its parts  _(2026-09-05)_
- `8b90d89` Stop paying a TLS handshake per call, and start the stack in parallel  _(2026-09-04)_
- `ca8a767` Bring the README back in line with what the code does  _(2026-09-03)_

<!-- END GENERATED -->

## Now

Two architecture reviews landed 8 Sep (`docs/history/architecture-review-*-2026-09-08.md`);
Q17 in `docs/board/QUESTIONS.md` reconciles them. Ali answered the two real
conflicts the same day: memory may live on a rented server he controls
(CLAUDE.md #3 amended), extraction stays on the laptop; conversation answers
right away, queue only for laptop kinds. The board is loaded from those
answers — ten `ready` tasks, lanes marked in `docs/board/README.md` NEXT.
`go` runs it. Still Ali's: Q17.2 (Urdu TTS, `claude -p` scope, roster cleanup,
D13 process change), U17 (the rented box), Q11-Q15.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
