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
- **2 Sep 2026 (post-integration pass, CORE):** ran after eleven tasks landed
  in one day across four parallel sessions.
  - **Statuses reconciled against the tree.** Six `ready` entries in NEXT were
    already `done` in their own task files (`blueprint-corrections`,
    `phase4-prep`, `pyflp-parse-failures`, `stt-groq-fallback`,
    `wakeword-fp-monitor`, plus `replay-harness` and `facts-check-tool` from
    an earlier pass). NEXT is now **generated from the task files' own
    `status:` lines** rather than hand-maintained, which is the drift this
    task exists to catch and the third time it has happened in two days.
  - **Seven tasks filed**, all from findings inside the day's work rather
    than from a fresh blueprint diff: `distill-chain-stall`,
    `action-outcome-reply`, `router-denial-surfacing`,
    `router-unresolvable-model-rungs`, `router-cost-class-ordering`,
    `provider-status-generator`, `router-eligibility-window`. The last four
    are Ali's §3.3 made concrete, which is what the previous NEXT asked this
    pass to do.
  - **The one that matters:** `distill-chain-stall`. 98 of the live queue's
    103 dead-lettered rows are `distill_memory`, and one ripe row has sat
    unclaimed since 30 Aug. Memory is the broken system; the reply path is
    175 rows and all `done`. It goes in at position 1.
  - **`docs/context.md`'s hand-written part had grown to 27 lines** against a
    ~15-line budget, which agents.md names as the signal that facts have
    stopped being temporary. Trimmed to 15; the durable parts were already in
    `state.md`.
  - `QUESTIONS.md`: two pending (Q11, Q12), no unprocessed answers.
    `tools/context_status.py --check` passes.
  - Not done: no fresh blueprint-vs-tree diff. The blueprint was rewritten
    the same day by `blueprint-corrections`, so a diff against it would have
    been measuring this session's own edits. Next pass should do a real one.
  - **Process slip, recorded:** this pass ran `git add docs/board/`, which
    swept `docs/board/tasks/backfill-run.md` — a file another live lane holds
    a claim on — into the commit. One line, their own `ready` → `in-progress`
    marker, so nothing was lost or overwritten. But `git add <directory>`
    does not respect claims, and a directory-wide add is how a lane commits
    another lane's half-written work without noticing. Stage explicit paths.

- **3 Sep 2026 (post-integration pass, CORE, lane-1):** ran after eight tasks
  landed in one session — `distill-chain-stall`, `action-outcome-reply`, the
  four router tasks, `provider-status-generator` and `pytest-addopts`.
  - **Statuses reconciled.** All 27 task files check out against the tree: 18
    `done` with cited evidence, 9 `blocked` on a live gate, 1 `ready` (this).
    No `done` claim was found without evidence, and no `ready` task's gap had
    silently closed.
  - **`backfill-run` was missing from NEXT entirely.** Nine task files are
    `blocked`; NEXT listed eight. It has been invisible on the board since the
    2 Sep rebuild — the one task nobody would have picked up even after its
    gate cleared. Added at position 10.
  - **The finding that matters: `backfill-run` is blocked on a contradiction,
    not on work.** `docs/blockers/mem0-extraction-not-schema-constrained.md`
    justifies its fix by quoting blueprint §1.3 as specifying "constrained
    JSON-schema structured decoding" and the code not doing it. That sentence
    had been replaced by its own negation **49 minutes before the blocker was
    written**: Q10a amended 1.3 to `json_object` + pydantic validation at
    01:53 (`6bd3ad4`), and the blocker landed at 02:42 (`843bc26`). Its
    recommendation is therefore no longer "conform the code to the spec" but
    "change the spec back", which is Ali's. Filed as **Q14** with the
    measurements intact, since those are still good and are the reason it is
    not simply closed.
  - **Blueprint §3.3's own gap paragraph was stale.** It named four clauses
    "the code does not have yet"; three shipped this session. Rewritten to
    name the one that remains (the verification window, Q11). The clauses
    themselves were not touched — only the claim about what the code does,
    which is what this audit is for.
  - **`bus-offbox-packaging`'s gate was half-stale**: `blocked-on:
    enqueue-classifier, vps-harden-deploy`, and `enqueue-classifier` landed
    2 Sep. Narrowed to the real gate.
  - **`docs/context.md`'s hand-written part had grown to 20 lines** against a
    ~15-line budget — the same drift the last pass caught at 27. Trimmed to
    14. The durable parts were already in `state.md`.
  - `QUESTIONS.md`: Q11 and Q12 pending from before, Q13 and Q14 added this
    session, no unprocessed answers from Ali.
    `tools/context_status.py --check` passes.
  - **`facts_check` is current**, not overdue: newest report is
    `docs/tasks/facts-check-reports/2026-09-02.md`, one day old against a
    30-day trigger. Not re-run.
  - **Blueprint-vs-tree diff done**, which the 2 Sep pass explicitly deferred
    because the blueprint had been rewritten that same day. §3.3's five shape
    clauses were checked one by one against `router/routing.py`; four hold,
    the fifth is Q11. One wording observation, filed here rather than as a
    question because its actionable half is satisfied: §3.3 says
    `providers.yaml` and `state.md` are "both generated from the running
    config", while a bullet four lines later says "Removing a provider is a
    `providers.yaml` edit". Read as "these live in those files, not in this
    document", the two agree — and `state.md`'s lists are now genuinely
    generated. Not worth an interruption.
  - **One new task filed, from this pass's own pre-commit refusal:**
    `offline-suite-network-leak`. Four tests in `tests/status/` call
    `create_app(...)` without `jobs=`, so `bus/main.py:107` falls back to
    `SupabaseJobsRepository.from_env()` and builds a **live** Supabase client
    they never use. An SSL handshake timeout failed all four, the run took
    148s instead of 77s, and the same suite passed either side of it. That is
    the third time this repo has lost time to a red suite that was not a
    regression — after the shared `--basetemp` and U13's git ownership — and
    the offline suite's entire value is that red means broken.
  - **Last pass's process slip, avoided:** it staged `git add docs/board/` and
    swept a file another lane held. This pass stages explicit paths. `git add
    -A` was used earlier in this session for the seven task commits, which was
    the same hazard and got away with it only because no peer lane was alive.
