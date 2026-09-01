# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `89cba3f Rebuild NEXT from the task files, and file what the day turned up` on `main`, in sync with origin.

**Working tree:** 3 changed

```
  A  docs/blockers/mem0-extraction-not-schema-constrained.md
  M  docs/board/tasks/backfill-run.md
  M  docs/board/tasks/board-audit.md
```

**Offline suite:** 1289 passed, 9 deselected, 10 warnings in 58.06s _(recorded 2026-09-02)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `89cba3f` Rebuild NEXT from the task files, and file what the day turned up  _(2026-09-02)_
- `be19942` Give voice a cloud STT tier, and the database a migration runner  _(2026-09-02)_
- `e4125d4` Reduce the wake-word false-positive test to one command  _(2026-09-02)_
- `10c736c` Make the multi-session workflow enforce itself  _(2026-09-02)_
- `c4cc48d` Make the inspector read the two .flp files PyFLP gives up on  _(2026-09-02)_
- `6bd3ad4` Apply Ali's blueprint corrections, and keep one line the audit was wrong about  _(2026-09-02)_
- `10be80b` Give the router a ledger that outlives one call, and let /status see it  _(2026-09-02)_
- `34b4bc0` Write the whole Oracle side of Phase 4 before the account exists  _(2026-09-02)_

<!-- END GENERATED -->

## Now

**Work the NEXT order in `docs/board/README.md`.** It was rebuilt from the
task files on 2 Sep and is accurate. Item 1 is the only broken system:
batch distillation died 98 times and has been stalled since 30 Aug, while
the WhatsApp reply path is 175 rows and all `done`.

**Four things are Ali's, and only these** (details in `QUESTIONS.md` /
`USER-TASKS.md`, all with recommendations):

- **Q12** — drop Pipecat from the desk loop? Blocks `voice-loop`.
- **Q11** — how long is the router's verification window?
- **U2** — the five model IDs still are not in `.env`. The ladder collapses
  to `openrouter/free`, which fails structured output ~half the time.
- **U12** — `SUPABASE_DB_PASSWORD` is empty, so `0003` cannot be applied.

**Standing constraint:** the FLP writing half stays unbuilt — see
`docs/board/PARKED.md`. Reading `.flp`s is fine.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
