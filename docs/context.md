# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `e0609bc Generate the provider lists instead of typing them` on `main`, 6 ahead, 0 behind origin.

**Working tree:** 10 changed

```
  M  .githooks/pre-commit
  M  .gitignore
  M  CLAUDE.md
  A  conftest.py
  M  docs/board/README.md
  M  docs/board/tasks/pytest-addopts.md
  M  docs/context.md
  M  docs/state.md
  M  pytest.ini
  M  tests/tools/test_precommit_hook.py
```

**Offline suite:** 1361 passed, 9 deselected, 10 warnings in 72.70s (0:01:12) _(recorded 2026-09-03)_

**Live acceptance suite:** 1 passed, 1 warning in 34.04s _(recorded 2026-09-03)_

**Recent commits**

- `e0609bc` Generate the provider lists instead of typing them  _(2026-09-03)_
- `d8b1970` Order the ladder by what a rung costs, then by how fast it actually is  _(2026-09-03)_
- `d57beb0` Keep a rung that cannot name a model out of the ladder  _(2026-09-02)_
- `210e07d` Stop a denied rung from quietly handing the bill to a paid one  _(2026-09-02)_
- `fa3365a` Say what the action did, not just that it queued  _(2026-09-02)_
- `bf9efc5` Restart the distill chain, and stop one outage becoming eighty-four rows  _(2026-09-02)_
- `843bc26` ok  _(2026-09-02)_
- `89cba3f` Rebuild NEXT from the task files, and file what the day turned up  _(2026-09-02)_

<!-- END GENERATED -->

## Now

**Work the NEXT order in `docs/board/README.md`.** Two systems closed the
evening of 2 Sep: memory (`distill-chain-stall`, seven live jobs since) and
action outcomes (`action-outcome-reply`). Everything `ready` is now the router.

**Six things are Ali's, and only these** (details in `QUESTIONS.md` /
`USER-TASKS.md`, all with recommendations):

- **U13** — one `git config --global --add safe.directory` line. `.git` is
  owned by another Windows account, so *every* git command fails and four
  `test_context_status.py` tests fail with it.
- **U14** — send one WhatsApp command, confirm **two** replies arrive. The
  machine half is proved live; the thumb half is not.
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
