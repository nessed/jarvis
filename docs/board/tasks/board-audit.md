---
id: board-audit
status: ready
lane: AUTO
priority: 3
phase: meta
blocked-on: none
files: docs/board/, docs/context.md
resources: none
---

# board-audit — keep the board true (recurring)

## Goal

The recurring defense against the disease this board replaces: statuses
drifting from the tree. This task is never `done` — completing it means
appending a dated Log entry and leaving it `ready` for next time. Run it
when nothing else is ready, or when >3 days since the last Log entry, or
after any large integration.

## Steps

1. For every task file: does its premise still hold against the tree?
   (`done` claims cite evidence; `ready` tasks' target gaps still exist;
   `blocked` tasks' gates are still unanswered.) Fix statuses with
   evidence.
2. Check `QUESTIONS.md` for answers Ali added but nobody processed —
   process them per README ("When Ali answers questions").
3. Diff blueprint vs tree for **new** gaps not on the board (the 1 Sep
   docs-drift audit's method: sample claims, verify, fix or file). New
   agent-doable work → new task file + NEXT entry. New decisions → new
   question with recommendation.
4. If the newest `docs/tasks/facts-check-reports/` report is >30 days old
   and `facts-check-tool` is done, run it and triage its diff.
5. Check `docs/context.md`'s hand-written part is current and ≤15 lines;
   run `python tools/context_status.py --check`.
6. Append a dated Log entry here: what drifted, what was added, one line.

## Done when

Never. Log entry per pass; status stays `ready`.

## Log

- **1 Sep 2026 (board creation):** initial population from blueprint vs
  tree at `bf15f79`; plan.md demoted to rules reference; stale in-flight
  lanes (`voice-cli-tests`, `live-schema-drift-guard`) confirmed landed
  and cleared. Adversarially verified same day by a read-only Opus 5 lane
  (37 checks, 4 findings, all fixed before commit —
  `docs/tasks/board-verification.md`).
