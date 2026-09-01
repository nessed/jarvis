# JARVIS work board

**This directory is the only task source.** `docs/plan.md` is a rules
reference (exclusive resources, hot files, cross-lane test doubles) — it no
longer lists work. If a task is not on this board, it is not work; if you
think it should be, add it via the `board-audit` task, don't freelance it.

Built 1 Sep 2026 from `docs/blueprint.md` vs the tree at `bf15f79`, the
1 Sep docs-drift audit, and the 27 Aug blueprint-drift audit
(`docs/audit/blueprint-drift.md`).

## The loop — run this instead of asking

An agent with a free hand does this, forever, without asking the user
anything:

1. Walk the **NEXT** list below, top to bottom. Open each
   `docs/board/tasks/<id>.md`; take the first with `status: ready`.
2. Re-verify the task's premise against the tree (statuses here can drift;
   a task whose premise is gone gets marked `done` or `parked` with evidence,
   and you move on).
3. Claim the task file **and** every file/resource its frontmatter lists:
   `python tools/work_board_claim.py claim --role <CORE|BUILD> --work-item <id> --file docs/board/tasks/<id>.md --file <each file> [--resource <each>]`
   Claiming the task file is what makes task pickup mutually exclusive.
   A claim conflict means someone has it — go back to step 1.
   (`--role` is `CORE` or `BUILD` only — a task's `lane:` field is an
   autonomy category, never a claim role; only literal `CORE` may claim
   `git-commit`.)
4. Flip `status: ready` → `in-progress`. Execute the task's Steps.
5. Verify. Append a dated `## Log` entry to the task file with the exact
   command(s) and output that prove completion.
6. Flip to `done`, update `docs/state.md` / `docs/context.md` per the
   where-a-fact-goes rules, release the claim.
7. **Go back to step 1. Do not stop, do not ask "what next".**

Stop only when: (a) every remaining task is `blocked` or `USER` — then run
`board-audit` once, and if it finds nothing, write one batched handoff and
stop; or (b) you hit a genuine Class C wall not already covered by
`QUESTIONS.md` — add it there with a recommendation, mark the task
`blocked`, and continue with the next task.

Parallel work: independent `ready` tasks may be dispatched to subagent
lanes per `agents.md` (disjoint claims, briefs in `docs/tasks/`, BUILD does
not commit). Ali's standing instruction (1 Sep 2026): **subagent lanes run
on Opus 5.**

## Statuses

`ready` — claimable now, no missing input.
`blocked` — waiting on a `Q#` (an answer in `QUESTIONS.md`) or `U#` (an
action in `USER-TASKS.md`) or another task. Flip to `ready` the moment the
gate clears — whoever processes Ali's answers does this immediately.
`in-progress` — claimed; check `work_board_claim.py list` before touching.
`done` — finished with cited evidence in its Log.
`parked` — deliberately not being done; see `PARKED.md`. Never re-surface.

## When Ali answers questions

Whoever receives answers (in chat or as edits to `QUESTIONS.md`):
1. Record each answer inline in `QUESTIONS.md` under its question, dated.
2. Flip every task the answer unblocks to `ready`.
3. If the answer amends `docs/blueprint.md`, apply the amendment in the
   same pass and note it in the task.
4. Continue the loop — the newly-ready tasks are usually the top of NEXT.

## NEXT — priority order

Ready now:

1. `voice-loop` — the local desk assistant loop (Phase 3's last build item)
2. `replay-harness` — replay real job payloads through real handlers
3. `facts-check-tool` — the blueprint's own anti-rot check, never built
4. `phase4-prep` — write all Oracle/VPS scripts before the account exists
5. `pyflp-parse-failures` — diagnose the 2 hard + 7 partial `.flp` parse failures
6. `wakeword-fp-monitor` — logging + report so Ali's FP test is one command
7. `pytest-addopts` — barrier task; run only when nothing else is mid-run
8. `board-audit` — recurring; also the fallback when nothing else is ready

Blocked, in the order they'll matter once unblocked:

9. `action-worker` (Q2) — third worker so the 4 orphaned job kinds can run
10. `enqueue-classifier` (Q1, Q2, after action-worker) — WhatsApp text → jobs
11. `backfill-run` (Q3, Q4) — finish blueprint 1.3
12. `live-routing-probe` (U2) — prove which provider rungs actually serve
13. `router-cooldown-ledger` (Q10c) — process-lifetime ledger + real /status health
14. `voice-command-ingress` (Q7, after voice-loop) — how voice reaches the queue
15. `blueprint-corrections` (Q10) — apply the approved factual fixes
16. `stt-groq-fallback` (Q8) — cloud STT fallback path
17. `db-maintenance` (Q9) — migration runner, orphan row, retention
18. `vps-harden-deploy` (U7, after phase4-prep) — execute the runbook on the real box
19. `bus-offbox-packaging` (after enqueue-classifier + vps-harden-deploy)
20. `cloud-routine-wire` (U8, after bus-offbox-packaging)

USER items live in `USER-TASKS.md`. Decisions live in `QUESTIONS.md`.
Deliberately-not-being-done items live in `PARKED.md` — read it before
proposing work, most "obvious next steps" are in there for a reason.
