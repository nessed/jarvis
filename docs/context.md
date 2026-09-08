# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `14cdbd0 Say where the seconds went, instead of guessing` on `main`, in sync with origin.

**Working tree:** 12 changed (plus 21 untracked)

```
  M  .env.example
   M CLAUDE.md
   M docs/board/HANDOFF.md
   M docs/board/QUESTIONS.md
   M docs/board/README.md
   M docs/board/tasks/bus-offbox-packaging.md
  A  docs/board/tasks/router-client-timeouts.md
   M docs/board/tasks/vps-harden-deploy.md
  M  docs/state.md
  M  router/__init__.py
  M  router/routing.py
  M  tests/router/test_routing.py
```

**Offline suite:** 1521 passed, 10 deselected in 65.74s (0:01:05) _(recorded 2026-09-09)_

**Live acceptance suite:** 1 passed, 1 warning in 34.04s _(recorded 2026-09-03)_

**Recent commits**

- `14cdbd0` Say where the seconds went, instead of guessing  _(2026-09-09)_
- `9598d37` Pull the reply brain out of the WhatsApp closure  _(2026-09-09)_
- `ddfd7ed` Measure the reply path instead of adding up its parts  _(2026-09-05)_
- `8b90d89` Stop paying a TLS handshake per call, and start the stack in parallel  _(2026-09-04)_
- `ca8a767` Bring the README back in line with what the code does  _(2026-09-03)_
- `669b47b` Write this week's handoff  _(2026-09-03)_
- `ba80f71` Keep the commit gate off the internet  _(2026-09-03)_
- `7647c67` Audit the board, and find backfill blocked on a contradiction  _(2026-09-03)_

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
