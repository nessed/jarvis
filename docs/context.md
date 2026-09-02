# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `ec8ae8e Let a bare pytest work, and stop two lanes deleting each other's temp files` on `main`, 7 ahead, 0 behind origin.

**Working tree:** 11 changed (plus 1 untracked)

```
  M conftest.py
  M  docs/blueprint.md
  M  docs/board/QUESTIONS.md
  M  docs/board/README.md
  M  docs/board/tasks/backfill-run.md
  M  docs/board/tasks/board-audit.md
  M  docs/board/tasks/bus-offbox-packaging.md
  A  docs/board/tasks/offline-suite-network-leak.md
  M  docs/context.md
   M tests/status/test_live_queue_status.py
   M tests/test_integration.py
```

**Offline suite:** 1367 passed, 9 deselected in 37.63s _(recorded 2026-09-03)_

**Live acceptance suite:** 1 passed, 1 warning in 34.04s _(recorded 2026-09-03)_

**Recent commits**

- `ec8ae8e` Let a bare pytest work, and stop two lanes deleting each other's temp files  _(2026-09-03)_
- `e0609bc` Generate the provider lists instead of typing them  _(2026-09-03)_
- `d8b1970` Order the ladder by what a rung costs, then by how fast it actually is  _(2026-09-03)_
- `d57beb0` Keep a rung that cannot name a model out of the ladder  _(2026-09-02)_
- `210e07d` Stop a denied rung from quietly handing the bill to a paid one  _(2026-09-02)_
- `fa3365a` Say what the action did, not just that it queued  _(2026-09-02)_
- `bf9efc5` Restart the distill chain, and stop one outage becoming eighty-four rows  _(2026-09-02)_
- `843bc26` ok  _(2026-09-02)_

<!-- END GENERATED -->

## Now

**Nothing on the board is `ready` except `board-audit`.** Eight tasks landed
2-3 Sep; everything left is `blocked` on Ali. Detail in `docs/state.md`.

**Six things are his, and only these** — all with recommendations:

- **U13** — one `git config --global --add safe.directory` line. `.git` is
  owned by another Windows account, so every git command fails.
- **U14** — send one WhatsApp command, confirm **two** replies arrive.
- **U2** — three router rungs are dead for want of model IDs in `.env`.
- **U12** — `SUPABASE_DB_PASSWORD` is empty, so `0003` cannot be applied.
- **Q11** — how long is the router's verification window?
- **Q12** — drop Pipecat from the desk loop?

**Q13** (98 dead-lettered rows) and **Q14** (backfill's two contradictory
answers) block nothing and nothing respectively.

**Standing constraint:** the FLP writing half stays unbuilt — `PARKED.md`.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
