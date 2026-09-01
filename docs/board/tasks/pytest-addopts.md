---
id: pytest-addopts
status: ready
lane: AUTO
priority: 3
phase: 0
blocked-on: none
files: pytest.ini, CLAUDE.md, .githooks/pre-commit
resources: test-workspace, pre-commit
---

# pytest-addopts — stop hand-carrying the TEMP workaround

## BARRIER

Changes what every lane's verification command resolves to. Run only when
`work_board_claim.py list` shows nothing else in flight, and claim
`test-workspace` + `pre-commit`.

## Goal

`CLAUDE.md` and `.githooks/pre-commit` both hand-carry
`-p no:cacheprovider --basetemp=.pytest-basetemp` because the system TEMP
is locked down; a bare `pytest` fails with `PermissionError`. Move the
flags into `pytest.ini`'s `addopts` so a bare `pytest -q` works.

## Steps

1. Add to `pytest.ini`: `addopts = -p no:cacheprovider --basetemp=.pytest-basetemp`
   (merge with any existing addopts; check how `-m live` deselection and
   the `.venv311` realflp runs interact — the flp suite uses its own
   basetemp, confirm addopts doesn't break it).
2. Prove a bare `.venv\Scripts\python.exe -m pytest -q` now passes.
3. Simplify `.githooks/pre-commit` and `CLAUDE.md`'s Commands section to
   the bare form, with one comment line saying where the flags live now.
4. Prove the pre-commit hook still runs green end-to-end.

## Also fix: two lanes running this command at once corrupt each other

**Found 2 Sep 2026 by `router-cooldown-ledger`, reproduced deliberately.**

`--basetemp=.pytest-basetemp` is a *fixed* path, and `agents.md` encourages
parallel lanes. Two concurrent sessions share that one directory, and pytest's
tmp-dir factory prunes old numbered directories at session start — including
the other session's live ones. Tests using `tmp_path` then fail or error in
setup, in whichever file happened to be running.

This cost real time before the cause was found: two full-suite runs failed on
*different* `tests/voice/` tests, each of which passed in isolation, and a
third full run was green. It reads exactly like a flaky test and is not one.

Reproduction — two `pytest tests/voice/` runs started together:

```
221 passed, 1 warning, 2 errors in 12.89s     <- ERROR tests/voice/test_audition_voices.py
223 passed in 12.84s
```

Same suite, run alone, four times in a row: `223 passed` every time.

So step 1 cannot simply move the existing flag into `addopts` unchanged —
that makes the collision the permanent default for every lane. The
replacement has to give each pytest session its own scratch root while still
keeping it off the locked-down system `TEMP`. `basetemp` takes no runtime
placeholder, so the likely shape is pointing `PYTEST_DEBUG_TEMPROOT` at a
repo-local directory and dropping `--basetemp` entirely, which restores
pytest's own per-session `pytest-<n>` numbering underneath it. Verify that
the numbered-directory pruning is then per-session, not shared, before
calling this done.

## Verification

Bare full suite green (cite); `.venv311` realflp run green (cite); hook
fires and passes on a no-op commit --amend dry-run or equivalent.

## Done when

No document or hook hand-carries the flags; everything cites addopts.

## Log

_(empty)_
