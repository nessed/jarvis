# JARVIS

Read these before task work. They are loaded automatically; do not treat
opening them as an optional first step.

@agents.md

## Start of every session

1. `docs/context.md` is what is in flight right now. Read it first. Its status
   block is generated, never hand-edited.
2. **`docs/board/README.md` is the task source.** If the user gave no
   specific task, do not ask for one and do not scan the repo for ideas: run
   the board's loop — pick the first `ready` task in NEXT, claim it, execute
   its guide, verify, mark it, pick the next. Keep going until everything
   left is `blocked`/USER, then write one batched handoff. Never re-surface
   anything in `docs/board/PARKED.md` or an answered question.
3. `docs/state.md` is component status: what works, what is blocked, provider
   rungs, account state. Read it when you need detail beyond the current task.
4. `docs/history/` is the frozen archive. Append-only, never edited.

   Where a new fact goes is decided by how fast it goes stale. See "Where a
   fact goes" in `agents.md`. Never hand-maintain a commit list, an
   "uncommitted" claim, or a test count: those are generated.
5. `docs/blueprint.md` is the technical spec. Provider pricing, rate limits,
   model names and free tiers in it are claims to re-verify. Architecture,
   component choices, dependency selection and phase ordering are decisions —
   never substitute one.
6. Subagent lanes run on **Opus 5** (Ali's standing instruction, 1 Sep 2026).
7. The hooks in `.claude/hooks/` register every session as a lane, enforce
   file claims, keep the board loop running after `go`/`resume`, and deliver
   peer messages. `python tools/work_board_claim.py status` says what every
   terminal is doing. See "The loop is a mechanism" in the board README.

## Non-negotiable

1. Secrets are never printed, echoed, logged, committed, or requested.
2. No personal corpus is read or ingested without explicit opt-in.
3. Memory extraction and embeddings are loopback-only and fail closed. No
   hosted fallback — NIM is geo-blocked from Pakistan and Gemini's free tier
   may train on prompts; neither may see private content.
4. No silent model or embedding-dimension drift.
5. Every completion claim cites the command that produced it and its output. A
   subagent that returns nothing is a failed verification, not a result.
6. Specified architectural components are decisions, not suggestions. An agent
   that thinks one is wrong stops and reports rather than substituting.
7. Destructive operations need explicit human approval.

## Parallel work board

Tasks live in `docs/board/` (see above). `docs/plan.md` holds the standing
rules — exclusive resources, hot files, cross-lane test doubles — and is not
a task list or a mutable claim board. Before any lane edits files or uses an
exclusive live resource, claim it atomically and release it after
verification:

```
python tools/work_board_claim.py claim --role CORE --work-item ITEM --file PATH [--resource KEY]
python tools/work_board_claim.py list
python tools/work_board_claim.py release CLAIM_ID
```

`CORE` integrates and commits. `BUILD` does not commit. Neither role owns a
directory: a successful tool claim is the only authority to modify a path.
Every agent must check `list`, claim every file it will write and exclusive
resource it will use before acting, stop on a conflict, and release the
returned claim ID after verification. `docs/plan.md` is the resource index;
never hand-edit claim state.

## Commands

```
.venv\Scripts\python.exe -m pytest -q                                              # full offline suite; required before any commit
.venv\Scripts\python.exe -m pytest -q -m live tests/live                           # phase acceptance probes
.venv\Scripts\python.exe tools/consult.py "question" [--file P] [--cmd "..."]      # second opinion; every Class B stop
.venv\Scripts\python.exe tools/repoint_webhook.py                                  # re-point Meta at the current tunnel
.venv\Scripts\python.exe tools/context_status.py --check                          # is context.md's status block current
```

The suite runs **bare**. It did not until 2 Sep 2026: this machine's system
`TEMP` is locked down and its `.pytest_cache` is owned by another Windows
account, so every command hand-carried `-p no:cacheprovider --basetemp=...`.
Both now live in `pytest.ini` and the repo-root `conftest.py`. Do not put
them back on the command line — a fixed `--basetemp` is emptied at session
start, so two lanes sharing one delete each other's `tmp_path` directories
and produce a suite that looks flaky and is not.

The pre-commit hook in `.githooks/pre-commit` runs the full offline suite and
refuses a red commit. If it is not firing, run
`git config core.hooksPath .githooks` once.
