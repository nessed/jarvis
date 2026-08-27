# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `1527ee9 Gitignore test_projects/ before real .flp guinea pigs land` on `main`, 1 ahead, 0 behind origin.

**Working tree:** 26 changed

```
  M  db/jobs.py
  A  docs/blockers/pyflp-python-312.md
  A  docs/consults/2026-08-27-distill-scheduling-mechanism/prompt.md
  A  docs/consults/2026-08-27-distill-scheduling-mechanism/response.md
  A  docs/consults/2026-08-27-distill-scheduling-mechanism/verdict.json
  A  docs/consults/2026-08-27-path-smoke-test/prompt.md
  A  docs/consults/2026-08-27-path-smoke-test/response.md
  A  docs/consults/2026-08-27-path-smoke-test/verdict.json
  M  docs/context.md
  M  docs/state.md
  A  docs/tasks/backfill-liveness-guard.md
  A  docs/tasks/distill-scheduling.md
  ...and 14 more
```

**Offline suite:** 272 passed, 1 deselected in 5.88s _(recorded 2026-08-27)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `1527ee9` Gitignore test_projects/ before real .flp guinea pigs land  _(2026-08-27)_
- `09363de` Record the duplicate start_jarvis.py incident in context.md  _(2026-08-27)_
- `a7a2030` Reconcile the context docs with what actually landed tonight  _(2026-08-27)_
- `0de7c89` Add one-command startup so the whole stack comes up together  _(2026-08-27)_
- `607bde1` Add PyFLP proof-of-concept scaffolding for Phase 2  _(2026-08-27)_
- `123b724` Pin the queue client timeout so a hung connection can't stall every message  _(2026-08-27)_
- `603cec6` Make conversation memory work by taking extraction off the reply path  _(2026-08-27)_
- `a35b654` Add Phase 1 scalability and blueprint review  _(2026-08-27)_

<!-- END GENERATED -->

## Now

**Nothing is running.** Every process was enumerated: zero `python`, zero
`cloudflared`, zero `ollama`, nothing on 8000 or 11434. The two duplicate
stacks died on their own, most likely a reboot. Nothing to Ctrl+C — but nothing
receives WhatsApp messages until Ollama is started and `start-jarvis.bat` is
run again.

Four lanes landed: the launcher singleton lock, `run_backfill.py`'s liveness
guard, the `distill_memory` job chain (retires old blocker 1), and the PyFLP
blocker file. `tools/consult.py` was found broken on Windows and fixed —
prompts were truncated to one line, so archived verdicts predating today are
suspect.

Next, unstarted: Phase 2 needs Python 3.11 installed (blocker 4).

## Waiting on you

One approval: **install Python 3.11** — it is not on this machine — and create
`.venv311` for Phase 2 FLP work. Plan is in
`docs/blockers/pyflp-python-312.md`.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
