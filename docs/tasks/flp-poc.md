# Lane: Phase 2.2 PyFLP proof-of-concept

## Why this lane exists

Blueprint (`docs/blueprint.md` lines 150-152, 218): Phase 2 is the headline
demo — "sort out this FLP" from WhatsApp with FL Studio closed. Line 152
explicitly authorizes doing the PyFLP proof-of-concept in parallel with
earlier phases, not sequentially after them. This lane runs while a separate
agent works the Phase 1 memory fast-path fix.

## Disjoint ownership — do not edit

- `memory/` (any file)
- `executor/poller.py`
- `tools/run_backfill.py`
- `requirements.txt`

If integrating this work requires touching any of those (e.g. registering
`flp_sort` in `executor/poller.py`'s `DEFAULT_HANDLERS`), do NOT edit them.
Instead, name the exact one-line change needed in your final report and stop
there — the orchestrator will merge it.

## Scope

1. `pip install pyflp` inside `.venv`. Append `pyflp==<installed version>` to
   `docs/tasks/deps-flp.txt` (create it) — do not touch `requirements.txt`
   yourself.
2. New module `executor/flp/__init__.py` and `executor/flp/sort.py` (new
   files only) implementing, per blueprint 2.2:
   - `flp_backup(path)` — timestamped copy of the `.flp` before any write,
     alongside the original (e.g. `name.2026-08-27T120000.bak.flp`).
   - `load(path)` / `save(project, path)` wrappers around PyFLP.
   - `apply_rules(project, ruleset)` — mixer track rename/reorder per a
     ruleset dict. Since the real naming convention (blueprint 2.1) has not
     been dictated by the user yet, implement this against a placeholder
     ruleset shape (document the shape you chose in your report) and make it
     obviously swappable — do not guess at real naming/color/routing
     conventions.
   - `diff_report(before, after)` — old name → new name per mixer insert.
   - `verify(path, expected_diff)` — re-parse the saved file and confirm the
     edits stuck (read-back verification, not just a successful write).
3. Since no real `.flp` guinea pigs exist yet (`test_projects/` does not
   exist — that's blueprint 2.1, pending the user), generate a minimal
   synthetic `.flp` for testing. Check first whether PyFLP can create an
   empty/minimal project in-memory and save it; if not, note that as a
   blocker for full round-trip testing rather than fabricating one by hand.
4. Tests under `tests/executor/test_flp_sort.py` covering: backup is created
   and untouched by later steps, apply_rules + save + verify round-trips
   cleanly on the synthetic project, verify() catches a corrupted/short-write
   case.
5. Run the full offline suite before reporting:
   `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py`
   Cite the output.

## Explicitly out of scope for this lane

- Registering `flp_sort` as a job kind in `executor/poller.py` (report the
  needed line instead).
- Real mixer-sorting conventions — that needs the user's dictated rules
  (blueprint 2.1).
- pywinauto work (blueprint 2.4) — separate, later lane.
- Any commit. Report back; the orchestrator commits after integration.

## Report back

- Exact pyflp version installed.
- Whether a synthetic minimal `.flp` was achievable via PyFLP alone, and how.
- The placeholder ruleset shape you chose, and why it's easy to swap for the
  user's real convention once dictated.
- Full offline suite output.
- The exact one-line `DEFAULT_HANDLERS` registration the orchestrator needs
  to wire this in as job kind `flp_sort`.
