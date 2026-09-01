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
   A claim conflict on the *task file* means someone has it — go back to
   step 1. A conflict on one of its *other* files means a peer holds
   something you need: **message them, do not wait and do not touch it.**
   `python tools/work_board_claim.py message --to <lane> "<what you need
   and the one-line fix you propose>"` (or `SendMessage` if `ListAgents`
   shows them). They apply it or release the file; if you two disagree on
   the fix, either runs `tools/consult.py` with both positions attached and
   both act on the verdict. Meanwhile take the next task.
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
`board-audit` once, and if it finds nothing, write the batched handoff to
`docs/board/HANDOFF.md`, send **one** `PushNotification` saying it exists,
and stop; or (b) you hit a genuine Class C wall not already covered by
`QUESTIONS.md` — add it there with a recommendation, mark the task
`blocked`, and continue with the next task.

## The loop is a mechanism, not a request

Since 2 Sep 2026 the hooks in `.claude/hooks/` run this loop for you:

- **Start:** every session is registered as a lane (`lane-1`, `lane-2`, …)
  and told which peers are alive, what they hold, and whether the previous
  session in this terminal died holding claims — those are inherited, so
  after a crash the user only reopens the terminal and says `resume`.
- **`go` / `resume`:** the only words that switch loop mode on. Any other
  prompt switches it off, so a session the user is talking to is never
  dragged into the board.
- **Stop:** in loop mode, trying to end the turn while a task is `ready`
  and unclaimed hands you that task instead (README order; a task a dead
  lane left `in-progress` comes first; a task handed to you three times
  without progress is skipped — mark it `blocked`). Inbox messages from
  peers are delivered before any task.
- **Every edit:** a write to a file a *live* peer has claimed is refused
  with the holder's lane and the message command. `git commit` needs the
  `git-commit` resource; `git stash` is refused outright.
- **`python tools/work_board_claim.py status`** answers "what is every
  terminal doing" in plain text. A third terminal opened just to ask that
  is a lane too, but stays out of the loop unless told `go`.

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

Rewritten 2 Sep 2026 by `board-audit`, from the task files themselves rather
than by hand. Seven tasks landed that day — `action-worker`,
`enqueue-classifier`, `router-cooldown-ledger`, `blueprint-corrections`,
`stt-groq-fallback` and, from the parallel lanes, `replay-harness`,
`facts-check-tool`, `pyflp-parse-failures`, `phase4-prep`,
`wakeword-fp-monitor` and `agent-harness` — and seven new ones were filed
from what they found.

Phase 2's producer/consumer gap is closed: WhatsApp text becomes real action
jobs and a worker claims them. The open weight has moved to the **router**
(four tasks implementing Ali's §3.3, which the blueprint now states and the
code does not yet do) and to **memory**, which is the one genuinely broken
system — see item 1.

Ready now:

1. `distill-chain-stall` — the memory path is down. 98 dead-lettered `distill_memory` rows, then one
   ripe row unclaimed since 30 Aug. The reply path is healthy; this is not
2. `action-outcome-reply` — an enqueued action says "queued as job X" and never says whether it worked
3. `router-denial-surfacing` — §3.3 says a 401/402/403 cools down **and surfaces**. Only the cooldown
   shipped; 402 still falls through, possibly to a paid rung
4. `router-unresolvable-model-rungs` — `groq` and `cerebras` sort to the front of every request and are silently
   skipped — unresolved `${...}` default_model, uncaught by `_configured()`
5. `router-cost-class-ordering` — §3.3's cost-class-then-p50 ordering. `providers.yaml` has a static int and
   no `cost_class`; Cerebras being trial-not-free already breaks the old model
6. `provider-status-generator` — §3.3's two generated lists. `blueprint-corrections` left them empty on
   purpose rather than hand-write what the spec says is generated
7. `pytest-addopts` — **barrier** — run only when `work_board_claim.py list` is empty. Also
   carries the fixed-`--basetemp` collision, partly addressed by `agent-harness`
8. `board-audit` — recurring; the fallback when nothing else is ready

Blocked, in the order they'll matter once unblocked:

9. `db-maintenance` — **U12**. Runner, ledger and `0003` are built, tested and committed;
   `SUPABASE_DB_PASSWORD` is an empty placeholder so the DDL cannot be applied
10. `voice-loop` — **Q12** — drop Pipecat from the desk loop? Recommendation filed
11. `router-eligibility-window` — **Q11** — how long the verification window is
12. `live-routing-probe` — **U2**. Now costing something measurable: the ladder collapses to
    `openrouter/free`, which answered a JSON prompt with `User Safety: safe`
    on two of four probes
13. `voice-command-ingress` — waits on `voice-loop`, so behind Q12
14. `vps-harden-deploy` — **U7**, after `phase4-prep` (done)
15. `bus-offbox-packaging` — after `vps-harden-deploy`
16. `cloud-routine-wire` — **U8**, after `bus-offbox-packaging`

USER items live in `USER-TASKS.md`. Decisions live in `QUESTIONS.md`.
Deliberately-not-being-done items live in `PARKED.md` — read it before
proposing work, most "obvious next steps" are in there for a reason.
