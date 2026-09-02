# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `ba80f71 Keep the commit gate off the internet` on `main`, 9 ahead, 0 behind origin.

**Working tree:** 1 changed

```
  M  docs/board/HANDOFF.md
```

**Offline suite:** 1367 passed, 9 deselected in 37.81s _(recorded 2026-09-03)_

**Live acceptance suite:** 1 passed, 1 warning in 34.04s _(recorded 2026-09-03)_

**Recent commits**

- `ba80f71` Keep the commit gate off the internet  _(2026-09-03)_
- `7647c67` Audit the board, and find backfill blocked on a contradiction  _(2026-09-03)_
- `ec8ae8e` Let a bare pytest work, and stop two lanes deleting each other's temp files  _(2026-09-03)_
- `e0609bc` Generate the provider lists instead of typing them  _(2026-09-03)_
- `d8b1970` Order the ladder by what a rung costs, then by how fast it actually is  _(2026-09-03)_
- `d57beb0` Keep a rung that cannot name a model out of the ladder  _(2026-09-02)_
- `210e07d` Stop a denied rung from quietly handing the bill to a paid one  _(2026-09-02)_
- `fa3365a` Say what the action did, not just that it queued  _(2026-09-02)_

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
