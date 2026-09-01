# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `bf15f79 Close the Meta token rotation and the FL Studio convention on Ali's instruction` on `main`, in sync with origin.

**Working tree:** 30 changed

```
  M  CLAUDE.md
  M  agents.md
  M  docs/blockers/tool-result-injection.md
  A  docs/board/PARKED.md
  A  docs/board/QUESTIONS.md
  A  docs/board/README.md
  A  docs/board/USER-TASKS.md
  A  docs/board/tasks/action-worker.md
  A  docs/board/tasks/backfill-run.md
  A  docs/board/tasks/blueprint-corrections.md
  A  docs/board/tasks/board-audit.md
  A  docs/board/tasks/bus-offbox-packaging.md
  ...and 18 more
```

**Offline suite:** 976 passed, 9 deselected, 2 warnings in 50.68s _(recorded 2026-09-01)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `bf15f79` Close the Meta token rotation and the FL Studio convention on Ali's instruction  _(2026-09-01)_
- `3695c05` Cover three untested voice CLIs, make the schema drift detector able to fail, and reconcile the docs  _(2026-09-01)_
- `52e2c03` push  _(2026-09-01)_
- `37c51d4` Fix two live-verification bugs: wrong whisper-server binary, and force voice replies to stay in English  _(2026-08-31)_
- `51e3a84` Wire voice notes into the WhatsApp handler and run whisper-server as a managed process  _(2026-08-30)_
- `0391f3f` Land desktop automation, the typing-cue fix, and NPU voice STT  _(2026-08-29)_
- `4f39697` Land the voice runtime, the fact-review path, and an FLP project inspector  _(2026-08-29)_
- `221ce33` Record this session's lane briefs and consult exchanges  _(2026-08-29)_

<!-- END GENERATED -->

## Now

**The work board moved: `docs/board/` (built 1 Sep 2026).** `plan.md` is
demoted to lane rules. Agents self-select from `docs/board/README.md`'s
NEXT list — 8 tasks ready now, headline `voice-loop` (the last unbuilt
Phase 3 piece). Do not ask Ali what is next.

**Waiting on Ali, batched:** answer `docs/board/QUESTIONS.md` (10
questions, one message, makes 6 agent tasks ready at once) and the checklist in
`docs/board/USER-TASKS.md` (U2 `.env` model lines is 2 minutes; U3
sleep/wake probe he deferred — don't nag).

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
