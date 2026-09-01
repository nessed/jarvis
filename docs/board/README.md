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

Rewritten 1 Sep 2026 after Ali answered `QUESTIONS.md`. Six tasks came off the
blocked list; two more shed their `Q` gate and now wait only on a sibling
task. One, `live-routing-probe`, stayed blocked: its gate was U2 and the
paste has not reached `.env` yet. `voice-loop` went back to blocked on
2 Sep — see Q12. Ali's Q10b answer also implies four new
router tasks that `board-audit` should file — see item 13.

Ready now:

1. `enqueue-classifier` — WhatsApp text becomes real action jobs. Unblocked
   2 Sep by `action-worker`; the allowlist is fixed at `system_control` +
   `zoom_join_meeting`, nothing else
2. `replay-harness` — replay real job payloads through real handlers
3. `router-cooldown-ledger` — process-lifetime ledger + real /status health (Q10c)
4. `blueprint-corrections` — a, b and c all approved; b is Ali's own §3.3
   text, applied verbatim, documentation only
5. `facts-check-tool` — the blueprint's own anti-rot check, never built
6. `phase4-prep` — write all Oracle/VPS scripts before the account exists
7. `pyflp-parse-failures` — diagnose the 2 hard + 7 partial `.flp` failures
8. `stt-groq-fallback` — voice owns a small Groq STT client (Q8=A)
9. `wakeword-fp-monitor` — logging + report so Ali's FP test is one command
10. `backfill-run` — **overnight window only** (Q4); takes `ollama-extract`
    exclusively and stops the executor, so it cannot overlap anything else
    touching Ollama
11. `pytest-addopts` — barrier task; run only when nothing else is mid-run
12. `db-maintenance` — approved to write live schema; the orphan row is
    **reported, not deleted**
13. `board-audit` — recurring; also the fallback when nothing else is ready.
    **Run it next for the four router tasks** Ali's §3.3 implies:
    `router-eligibility-window` (needs Q11), `router-cost-class-ordering`,
    `provider-status-generator`, and folding 401/402/403 surfacing into
    `router-cooldown-ledger`

Blocked, in the order they'll matter once unblocked:

14. `voice-loop` — **Q12**, raised 2 Sep. Stopped before build on its own
    Constraints clause: Pipecat's local transport needs `pyaudio`, its Kokoro
    service needs `kokoro-onnx`, and its wake word is a transcript regex
    rather than the acoustic openWakeWord gate — five of six stages would be
    custom subclasses. Stop-and-report, not a substitution. See
    `docs/tasks/voice-loop-report.md`
15. `live-routing-probe` — U2. Ali gave the five model IDs but a key-name
    check of `.env` found none of them present; the probe would only
    re-prove the known gap until they land
16. `voice-command-ingress` — Q7 answered (enqueue-only `POST /command`);
    waits on `voice-loop`, so now behind Q12 as well
17. `vps-harden-deploy` (U7, after `phase4-prep`)
18. `bus-offbox-packaging` (after `enqueue-classifier` + `vps-harden-deploy`)
19. `cloud-routine-wire` (U8, after `bus-offbox-packaging`)

USER items live in `USER-TASKS.md`. Decisions live in `QUESTIONS.md`.
Deliberately-not-being-done items live in `PARKED.md` — read it before
proposing work, most "obvious next steps" are in there for a reason.
