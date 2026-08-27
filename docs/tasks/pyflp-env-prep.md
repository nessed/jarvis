# Lane C: PyFLP environment prep — up to, but not past, the decision line

## Why this lane exists

PyFLP does not work on this machine's Python (3.12) and it has been reproduced
twice. `agents.md` requires that a failure surviving two reproductions gets a
`docs/blockers/<slug>.md` file, so the same failure is never paid for a third
time. **That file is missing.** Writing it is the point of this lane.

Phase 2 (FL Studio — the headline demo, "sort out this FLP" from WhatsApp with
FL Studio closed) is fully blocked on this.

## Hard stop — read this first

**Do not install anything. Do not create any virtual environment. Do not run
`pip install`, `winget install`, `py -m venv`, or any installer.** Choosing to
add a second Python runtime to this machine is the user's call, not an agent's.
This lane gathers the evidence and drafts the plan; the user approves it in the
handoff.

Read-only commands (`py -0p`, `py -3.11 --version`, `where python`) are fine
and expected.

## Owned files — edit nothing else

- `docs/blockers/pyflp-python-312.md` (new)
- `docs/state.md` (numbering fix only — see task 2)

Do not edit `executor/flp/`, `tests/executor/test_flp_sort.py`,
`docs/context.md`, `requirements.txt`, or anything else.

## Task 1 — write `docs/blockers/pyflp-python-312.md`

Follow the house format set by `docs/blockers/README.md` and the existing
`docs/blockers/supabase-unreachable-from-laptop.md`: exact reproduction
command, exact failure output, everything already tried, and the single action
the user would take to unblock it.

Known facts to record (verify each by re-running where a command is named —
`agents.md` Class A: the answer is obtainable, so obtain it rather than
copying this brief):

- **Environment:** this project's `.venv` runs Python 3.12. Confirm the exact
  version with `.venv\Scripts\python.exe --version`.
- **Failure 1:** `pyflp.parse()` fails on *any* input, caused by a stdlib
  `enum.py` change in 3.12. Capture the real traceback and the exact exception
  type and message.
- **Failure 2:** `pyflp.save()` cannot create a project from scratch either, so
  there is no synthetic-fixture workaround.
- **Both reproduced twice**, on an empty project *and* on a real PyFLP test
  fixture. Record both.
- **Upstream support matrix:** PyFLP claims 3.8–3.11 only. 3.12 is not a
  supported configuration; this is not a bug to file.
- **Installed version:** get it from
  `.venv\Scripts\python.exe -m pip show pyflp`, and cross-check
  `docs/tasks/deps-flp.txt`.
- **What was tried and did not work:** no workaround was found; the code was
  written against fakes instead. `executor/flp/sort.py` is built and has 16
  passing unit tests against fake objects, so the blocker is *only* the
  inability to exercise it against a real or synthetic `.flp`.
- **The single unblock:** a Python 3.11 environment scoped to this project.

Also note the *second*, independent Phase 2 prerequisite so it is not
forgotten: blueprint 2.1 needs real guinea-pig `.flp` files and the user's
dictated mixer-sorting convention, and neither exists yet. Python 3.11 alone
does not unblock Phase 2 end-to-end.

If a reproduction command now behaves differently from what this brief says,
**record what actually happened** — the brief is a starting point, not the
finding.

## Task 2 — fix the blocker numbering in `docs/state.md`

`docs/state.md` refers to "open blocker 6" in two places, but its "Open
blockers" list has **five** entries and PyFLP is number **5**. Fix both:

- line 13, in "Phase position"
- line 31, in the FL Studio sort table row

Change only the number, and add a pointer to the new blocker file from the
blocker-5 entry so the two are linked. Change nothing else in `state.md` — the
orchestrator is editing other parts of it after this lane returns.

## Task 3 — evidence only: is Python 3.11 already here?

Run:

```
py -0p
```

Report the full output verbatim — every installed Python and its path. Also
try `py -3.11 --version` and report exactly what it says.

Then draft the env plan and **write it into the blocker file** under a
`## Proposed unblock (needs the user's approval — not executed)` heading:

- Whether 3.11 is already installed. If yes, the exact path found. If no, name
  the install source you would recommend (python.org installer vs `winget
  install Python.Python.3.11`) and say which and why.
- The exact commands that *would* create `.venv311` scoped to this project,
  written out but explicitly marked as not run.
- Which requirements go into it — the flp lane's needs (`pyflp` per
  `docs/tasks/deps-flp.txt`, plus `pytest`), not the whole of
  `requirements.txt`.
- **How pytest picks it up.** Be concrete. The default suite is run with
  `.venv\Scripts\python.exe -m pytest` and must stay green on 3.12, so
  real-`.flp` tests cannot simply join the default run. Propose a mechanism —
  a `live`-style pytest marker (the repo already has `-m live` for
  `tests/live/`), a separate invocation with `.venv311\Scripts\python.exe`, or
  a skip guard — and say which you recommend and why. Note that this machine
  needs `-p no:cacheprovider --basetemp=.pytest-basetemp` on any pytest run
  because the system `TEMP` is locked down.
- Any risk worth flagging: disk cost, two environments drifting, PATH
  confusion.

## Out of scope

- Installing anything. Creating any environment. **This is a Class C decision.**
- Touching `executor/flp/` or its tests.
- Any commit.

## Verify before reporting

This lane changes only documentation, but run the suite anyway to confirm you
broke nothing:

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
```

Cite the output.

## Report back

- **`py -0p` output, verbatim** — the handoff needs this to ask the user for
  approval, so it must be exact.
- Whether 3.11 is present, one line, unambiguous.
- The two `state.md` lines you changed.
- Your recommended pytest mechanism for the 3.11 tests, in one or two lines.
- Full offline suite output.
