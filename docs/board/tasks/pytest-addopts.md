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

## Verification

Bare full suite green (cite); `.venv311` realflp run green (cite); hook
fires and passes on a no-op commit --amend dry-run or equivalent.

## Done when

No document or hook hand-carries the flags; everything cites addopts.

## Log

_(empty)_
