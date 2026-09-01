---
id: pyflp-parse-failures
status: ready
lane: AUTO
priority: 2
phase: 2
blocked-on: none
files: tools/flp_inspect.py, tests/tools/test_flp_inspect.py, docs/blockers/pyflp-channel-groups-indexerror.md, docs/tasks/pyflp-parse-failures-report.md
resources: none (reads .flp copies only, .venv311 only)
---

# pyflp-parse-failures — diagnose the imperfect parses

## Goal

Of Ali's 25 real projects + 1 fixture: 17 parse clean, 7 partial, 2 fail
outright (`outroforest`, `prayon`). Additionally, one of the 17 "clean"
projects (`spaceship demo`) hits PyFLP's own `IndexError` in
channel-group code once channels are actually iterated — the audit tool
never iterated them (`channel.py:1586`,
`docs/blockers/pyflp-channel-groups-indexerror.md`). All read-path.
Diagnose; make `tools/flp_inspect.py` degrade informatively instead of
dying where that's honest to do.

## Rules

- `.venv311\Scripts\python.exe` only (3.11.5, never upgrade, never `py`).
- Copies in `test_projects/` only; originals never touched. Read-only —
  no writing half exists (see PARKED).
- Fixing PyFLP itself: a minimal local workaround **in our code** (e.g.
  catching/guarding around the group lookup in `flp_inspect.py`) is fine;
  vendoring or patching the installed PyFLP package is a component change
  — stop and report instead. An upstream issue write-up in the report is
  welcome.
- A partial parse must stay loud: report what was skipped, never silently
  narrow output.

## Steps

1. Reproduce each failure class against the copies; classify by exception
   and by what byte-level/event-level feature triggers it (the audit data
   in `docs/tasks/flp-audit-data.json` has the per-project notes).
2. For the channel-groups `IndexError`: determine whether a guarded lookup
   in our inspector recovers the rest of the file's data. If yes, guard +
   test with a synthetic fixture; update the blocker file to reflect it.
3. For `outroforest`/`prayon`: root-cause as far as evidence allows;
   document whether any read is salvageable.
4. Tests for every new guard path (28 exist in
   `tests/tools/test_flp_inspect.py`; follow their fixture pattern).
5. Report: `docs/tasks/pyflp-parse-failures-report.md` — per-project
   verdicts, what's now readable that wasn't, what stays unreadable & why.

## Verification

`.venv311` realflp/inspector tests green (cite exact command + output);
full main suite green.

## Done when

Report written, blocker file current, guards tested. Update the failure
counts in `docs/context.md` if they change.

## Log

_(empty)_
