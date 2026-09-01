# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `94551a3 Replace plan.md with a self-serve work board under docs/board/` on `main`, 1 ahead, 0 behind origin.

**Working tree:** 15 changed

```
  M  docs/blueprint.md
  M  docs/board/QUESTIONS.md
  M  docs/board/README.md
  M  docs/board/USER-TASKS.md
  M  docs/board/tasks/action-worker.md
  M  docs/board/tasks/backfill-run.md
  M  docs/board/tasks/blueprint-corrections.md
  M  docs/board/tasks/db-maintenance.md
  M  docs/board/tasks/enqueue-classifier.md
  M  docs/board/tasks/live-routing-probe.md
  M  docs/board/tasks/router-cooldown-ledger.md
  M  docs/board/tasks/stt-groq-fallback.md
  ...and 3 more
```

**Offline suite:** 976 passed, 9 deselected, 2 warnings in 51.42s _(recorded 2026-09-01)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `94551a3` Replace plan.md with a self-serve work board under docs/board/  _(2026-09-01)_
- `bf15f79` Close the Meta token rotation and the FL Studio convention on Ali's instruction  _(2026-09-01)_
- `3695c05` Cover three untested voice CLIs, make the schema drift detector able to fail, and reconcile the docs  _(2026-09-01)_
- `52e2c03` push  _(2026-09-01)_
- `37c51d4` Fix two live-verification bugs: wrong whisper-server binary, and force voice replies to stay in English  _(2026-08-31)_
- `51e3a84` Wire voice notes into the WhatsApp handler and run whisper-server as a managed process  _(2026-08-30)_
- `0391f3f` Land desktop automation, the typing-cue fix, and NPU voice STT  _(2026-08-29)_
- `4f39697` Land the voice runtime, the fact-review path, and an FLP project inspector  _(2026-08-29)_

<!-- END GENERATED -->

## Now

**Ali answered all 10 of `QUESTIONS.md` on 1 Sep.** 13 tasks are `ready`;
work the board's NEXT order and do not ask what is next. Headline picks:
`action-worker` (newly unblocked, and `enqueue-classifier` waits on it) and
`voice-loop`.

**Ali rewrote blueprint §3.3 himself** (recorded verbatim in Q10b). The
blueprint stops enumerating rungs; roster and reachability move to
`providers.yaml` and `state.md`. Four clauses of it are ahead of the code —
`blueprint-corrections` applies the text and names the deltas, and
`board-audit` files them as router tasks.

**Two things still open:**

- **U2 is not done.** Ali gave the five model IDs and said "pasted", but a
  key-name check found none of them in `.env`. `live-routing-probe` stays
  blocked.
- **Q11** — how long the new "verification window" is. Recommendation
  filed; blocks only the new `router-eligibility-window` task.

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
