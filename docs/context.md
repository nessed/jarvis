# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `0ff4e1a Give the four orphaned job kinds a worker that can actually claim them` on `main`, 1 ahead, 0 behind origin.

**Working tree:** 10 changed (plus 4 untracked)

```
  M docs/board/tasks/enqueue-classifier.md
  M  docs/board/tasks/facts-check-tool.md
  M  docs/board/tasks/replay-harness.md
  A  docs/tasks/facts-check-reports/2026-09-02.md
   M executor/handlers/whatsapp.py
   M tests/executor/test_whatsapp_handler.py
  A  tests/tools/test_facts_check.py
  A  tests/tools/test_replay_job.py
  A  tools/facts_check.py
  A  tools/replay_job.py
```

**Offline suite:** 1129 passed, 9 deselected, 2 warnings in 53.51s _(recorded 2026-09-02)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `0ff4e1a` Give the four orphaned job kinds a worker that can actually claim them  _(2026-09-02)_
- `e4129df` Fold Ali's ten answers into the board, blueprint and state  _(2026-09-01)_
- `94551a3` Replace plan.md with a self-serve work board under docs/board/  _(2026-09-01)_
- `bf15f79` Close the Meta token rotation and the FL Studio convention on Ali's instruction  _(2026-09-01)_
- `3695c05` Cover three untested voice CLIs, make the schema drift detector able to fail, and reconcile the docs  _(2026-09-01)_
- `52e2c03` push  _(2026-09-01)_
- `37c51d4` Fix two live-verification bugs: wrong whisper-server binary, and force voice replies to stay in English  _(2026-08-31)_
- `51e3a84` Wire voice notes into the WhatsApp handler and run whisper-server as a managed process  _(2026-08-30)_

<!-- END GENERATED -->

## Now

**Board is running itself.** Work the NEXT order in `docs/board/README.md`;
do not ask what is next. `action-worker` is done — three workers now, and the
four action job kinds have a consumer for the first time. `enqueue-classifier`
came off the blocked list with it and is the top `ready` item.

**Three things are the user's, and only these:**

- **Q12 — drop Pipecat from the desk loop?** `voice-loop` stopped before
  writing a line, on its own Constraints clause. Recommendation and the
  consult are in `QUESTIONS.md`. This blocks `voice-loop` and
  `voice-command-ingress` behind it.
- **Q11** — how long the router's new "verification window" is. Blocks only
  `router-eligibility-window`.
- **U2** — the five model IDs are still absent as key names in `.env`. Ali
  said "pasted"; a name-only check found none. `live-routing-probe` stays
  blocked until they land.

**Standing constraint:** the FLP writing half stays unbuilt — no
mixer-sorting convention exists and the placeholder ruleset is unapproved;
see `docs/board/PARKED.md`. Reading `.flp`s is fine.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
