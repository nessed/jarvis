---
id: pytest-addopts
status: done
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

### 2 September 2026 (evening) — done. Barrier honoured, and the collision is genuinely fixed.

Barrier: `work_board_claim.py list` was empty and lane-1 was the only live
session. `test-workspace` and `pre-commit` were both claimed.

### The two faults being hand-carried, and they are different faults

`-p no:cacheprovider` and `--basetemp=...` were carried together as if they
were one workaround. They are not:

- **`.pytest_cache` is unwritable.** `[Errno 13] Permission denied` on
  `.pytest_cache/v/cache/nodeids`. This is the *same* ownership fault as
  **U13**: the repository is owned by the `CodexSandboxOffline` Windows
  account. That also closes the `.pytest_cache/` half of `docs/state.md` open
  blocker 5, which recorded "repo-root `.pytest_cache/` could not be read" as
  an unexplained fact.
- **The system `TEMP` is locked down**, so `tmp_path` fixtures error en masse.

The first moved into `addopts` unchanged. The second could not.

### Why `--basetemp` was dropped rather than moved

The task is explicit that moving it unchanged "makes the collision the
permanent default for every lane", and it is right. Pytest **empties** an
explicitly-given basetemp at session start, so two concurrent sessions delete
each other's live `tmp_path` directories.

The repo-root `conftest.py` sets `PYTEST_DEBUG_TEMPROOT` to `.pytest-temp/`
instead. That moves the root off the locked-down TEMP without pinning one
directory, so pytest resumes its own `pytest-of-<user>/pytest-<n>` numbering —
which is concurrency-safe by construction: each session claims its own number,
and the pruner takes a lock and skips directories still in use.

In `conftest.py` and not `pytest.ini` because `addopts` cannot set an
environment variable, and a bare `pytest -q` has to work. It is read lazily by
`TempPathFactory.getbasetemp()` on first `tmp_path` use, so conftest import
time is comfortably early enough, and it uses `setdefault` so an explicit
`--basetemp` still wins for one-off diagnosis.

### Proved both ways

The task asks to verify the pruning is per-session before calling this done.
Three concurrent `tests/voice/` runs under the new scheme:

```
run 1: 267 passed in 13.21s
run 2: 267 passed in 13.23s
run 3: 267 passed in 13.21s

.pytest-temp/pytest-of-Ali/  ->  pytest-3  pytest-4  pytest-5
```

Three runs, three directories, no interference. And the counter-proof — the
*old* fixed `--basetemp`, two concurrent runs, on this same tree:

```
run 1: 265 passed, 1 warning, 2 errors in 13.04s
run 2: 1 failed, 266 passed in 13.01s
```

Exactly the `2 errors` shape the task recorded. The fix is not a coincidence
of timing.

### All four documented commands, bare

```
.venv\Scripts\python.exe -m pytest -q
1359 passed, 9 deselected, 10 warnings in 74.98s

.venv\Scripts\python.exe -m pytest -q -m live tests/live
1 passed, 1 warning in 34.04s

.venv311\Scripts\python.exe -m pytest -q -m realflp tests/flp/test_flp_real.py
1 passed, 3 skipped in 0.18s
```

The `-m` in `addopts` deselects `live`, `realflp` and `guiauto`; an explicit
`-m` on the command line overrides it, so both gated suites still run on
demand. That was the interaction step 1 said to check, and it holds.

A first bare run showed `4 failed, 1355 passed` — all four in
`tests/tools/test_context_status.py`, all `fatal: detected dubious ownership`.
That is U13 in a shell without the workaround exported, not this change; with
it, 1359 pass.

The pre-commit hook now runs `"$PY" -m pytest -q` with no flags, and step 4's
end-to-end proof arrived the hard way: **the hook refused the first attempt at
this task's own commit.**

```
FAILED tests/tools/test_precommit_hook.py::test_the_hook_runs_the_documented_offline_suite_command
E   AssertionError: assert '-p no:cacheprovider' in '-m pytest -q'
pre-commit: offline suite is red. Fix it, or commit with --no-verify
```

`tests/tools/test_precommit_hook.py` pins the hook against the command
`CLAUDE.md` documents — which it reads out of `CLAUDE.md` rather than
hardcoding, so that half followed the change on its own — but two trailing
assertions pinned the two flags as command-line literals. The last full suite
had been run before the hook was edited, so nothing else would have caught it.
That is precisely the failure the hook exists to prevent, catching its own
change.

The guard was followed rather than deleted. What was worth protecting was
never the command line, it was that the workarounds exist at all, so it now
asserts `-p no:cacheprovider` is in `pytest.ini` and `PYTEST_DEBUG_TEMPROOT`
is in `conftest.py` — plus a new test that **no fixed `--basetemp` is ever
reintroduced** into the hook or `pytest.ini`, which is the regression that
would silently restore the collision.

```
.venv\Scripts\python.exe -m pytest -q
1361 passed, 9 deselected, 10 warnings in 69.25s
```

### Left alone

Roughly sixteen stale `.pytest-basetemp-*` directories from the old regime are
still on disk. They are gitignored and harmless, and deleting sixteen
directories is not something this task was asked to do; `agents.md` reserves
that for an explicit go-ahead. The `.gitignore` entries for them stay so the
leftovers remain ignored.
