# JARVIS

Read these before task work. They are loaded automatically; do not treat
opening them as an optional first step.

@agents.md

## Start of every session

1. `docs/context.md` is what is in flight right now. Read it first. Its status
   block is generated, never hand-edited.
2. `docs/state.md` is component status: what works, what is blocked, provider
   rungs, account state. Read it when you need detail beyond the current task.
3. `docs/history/` is the frozen archive. Append-only, never edited.

   Where a new fact goes is decided by how fast it goes stale. See "Where a
   fact goes" in `agents.md`. Never hand-maintain a commit list, an
   "uncommitted" claim, or a test count: those are generated.
4. `docs/blueprint.md` is the technical spec. Provider pricing, rate limits,
   model names and free tiers in it are claims to re-verify. Architecture,
   component choices, dependency selection and phase ordering are decisions —
   never substitute one.

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

## Commands

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py   # full offline suite; required before any commit
.venv\Scripts\python.exe -m pytest -q -m live tests/live                           # phase acceptance probes
.venv\Scripts\python.exe tools/consult.py "question" [--file P] [--cmd "..."]      # second opinion; every Class B stop
.venv\Scripts\python.exe tools/repoint_webhook.py                                  # re-point Meta at the current tunnel
.venv\Scripts\python.exe tools/context_status.py --check                          # is context.md's status block current
```

The full-suite command needs `-p no:cacheprovider --basetemp=.pytest-basetemp`
on this machine: the system `TEMP` directory is locked down, and pytest's
default scratch/cache dirs land there and fail with `PermissionError` without
those flags. `.githooks/pre-commit` already uses this form.

The pre-commit hook in `.githooks/pre-commit` runs the full offline suite and
refuses a red commit. If it is not firing, run
`git config core.hooksPath .githooks` once.
