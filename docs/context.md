# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `843bc26 ok` on `main`, in sync with origin.

**Working tree:** 12 changed

```
  M  docs/board/QUESTIONS.md
  M  docs/board/README.md
  M  docs/board/USER-TASKS.md
  M  docs/board/tasks/distill-chain-stall.md
  M  docs/context.md
  M  docs/state.md
  M  executor/handlers/distill.py
  M  executor/poller.py
  M  memory/embeddings.py
  M  tests/executor/test_distill_handler.py
  M  tests/executor/test_poller.py
  M  tests/memory/test_embeddings.py
```

**Offline suite:** 1297 passed, 9 deselected, 10 warnings in 68.46s (0:01:08) _(recorded 2026-09-02)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `843bc26` ok  _(2026-09-02)_
- `89cba3f` Rebuild NEXT from the task files, and file what the day turned up  _(2026-09-02)_
- `be19942` Give voice a cloud STT tier, and the database a migration runner  _(2026-09-02)_
- `e4125d4` Reduce the wake-word false-positive test to one command  _(2026-09-02)_
- `10c736c` Make the multi-session workflow enforce itself  _(2026-09-02)_
- `c4cc48d` Make the inspector read the two .flp files PyFLP gives up on  _(2026-09-02)_
- `6bd3ad4` Apply Ali's blueprint corrections, and keep one line the audit was wrong about  _(2026-09-02)_
- `10be80b` Give the router a ledger that outlives one call, and let /status see it  _(2026-09-02)_

<!-- END GENERATED -->

## Now

**Work the NEXT order in `docs/board/README.md`.** Memory is no longer the
broken system: `distill-chain-stall` closed the evening of 2 Sep and the
distill chain has completed seven live jobs since. Everything `ready` is now
the router.

**Five things are Ali's, and only these** (details in `QUESTIONS.md` /
`USER-TASKS.md`, all with recommendations):

- **U13** — one `git config --global --add safe.directory` line. `.git` is
  owned by another Windows account, so *every* git command fails and four
  `test_context_status.py` tests fail with it.
- **Q12** — drop Pipecat from the desk loop? Blocks `voice-loop`.
- **Q11** — how long is the router's verification window?
- **U2** — the five model IDs still are not in `.env`. The ladder collapses
  to `openrouter/free`, which fails structured output ~half the time.
- **U12** — `SUPABASE_DB_PASSWORD` is empty, so `0003` cannot be applied.

**Q13 is open but blocks nothing:** what to do with the 98 dead-lettered
`distill_memory` rows. Nothing was lost and there is nothing to re-queue;
it is disposal only, and "leave them" is recommended.

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
