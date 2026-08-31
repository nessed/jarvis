# The work board deleted a live lane's claims without saying so

30 August 2026.

## What happened

Two Claude sessions were working this repository at the same time. One held a
`voice-whatsapp-wiring` claim over `executor/handlers/whatsapp.py`,
`tools/start_jarvis.py`, `voice/config.py`, `docs/context.md`, `docs/state.md`
and six other paths. The other — this lane — wanted three of them.

`claim` refused, as designed:

```text
error: conflict with CORE/voice-whatsapp-wiring (aecf3da3...):
files: docs/context.md, docs/state.md, tools/start_jarvis.py
```

The holder's pid was checked and found dead, so the claim was read as
abandoned. It was not. Re-running with `--stale-after-seconds 60`, then `30`,
deleted the other lane's claims and granted the files. Both lanes then edited
the same paths. Nothing announced the deletion — not to the lane doing it, not
to the lane it happened to. It surfaced only when `tools/start_jarvis.py`
changed underneath a half-written edit.

## Why the pid check could not have helped

`claim()` records `pid=os.getpid()`. That is the pid of the CLI process, which
exits the instant it prints the claim JSON. **Every claim on the board has a
dead pid by construction**, so `_owner_alive` is always `False` for a real
claim and the `and not _owner_alive(...)` conjunct in `_prune_stale` never
changes an outcome.

Pruning is therefore age-only, and always was. The pid check reads like a
liveness guard, which is exactly what made it dangerous: it invited the
inference "the owner is dead, so this claim is abandoned" when a dead pid
carries no information at all.

`_owner_alive` is *not* dead code overall — `_exclusive_lock` calls it about a
lock file whose owner is a genuinely concurrent process. Deleting the function
would break stale-lock recovery. Only the conjunct inside `_prune_stale` is
inert, and it was kept: removing it changes no behaviour and the dead-owner
test pins it.

## The fix

Verdict: `docs/consults/2026-08-30-work-board-silent-prune/`. Two changes,
neither touching claim semantics.

1. **Pruning is loud.** `_report_pruned` writes every dropped claim — id, role,
   work item, held paths, age — to stderr, on `claim`, `list` and `release`
   alike. stderr rather than stdout so the JSON a caller parses stays clean.
2. **`--stale-after-seconds` has a floor** of `MINIMUM_STALE_AFTER_SECONDS =
   300`, enforced in `main()` only. Below it the CLI refuses and changes
   nothing. The library functions stay unbounded so tests can drive pruning
   without a real wait — the existing dead-owner test passes
   `stale_after_seconds=1` directly.

The docstrings now say pruning is age-only rather than implying a liveness
guard.

## Evidence

The command that caused the collision is now refused, and the board survives
it:

```text
$ .venv/Scripts/python.exe tools/work_board_claim.py --stale-after-seconds 30 list
error: --stale-after-seconds 30 is below the 300s floor. Pruning is age-only,
so this would delete claims a live lane is still working behind. If a claim is
genuinely abandoned, release it by id.
exit=2
```

Four new tests cover the announcement, the stdout/stderr split, the CLI
refusal leaving the board intact, and the floor not reaching the library.

```text
$ .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider \
    --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
824 passed, 7 deselected, 2 warnings in 62.11s
```

## What is still true and unfixed

There is no durable owner identity. A lane that abandons work still leaves a
claim standing for 24 hours, and nothing distinguishes that from a lane still
working. Fixing it needs a session/lane token plus a heartbeat, which is a
redesign of the ownership model rather than a repair, and was deliberately not
built here.

`docs/state.md` and `docs/context.md` were left untouched: the other session
was still live in them while this was written, and re-entering a path mid-flight
is the mistake this whole entry is about.
