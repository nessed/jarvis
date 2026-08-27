# Lane A: Python 3.11 environment for the FLP lane — APPROVED

The user approved this on 27 August 2026. Install Python 3.11, create
`.venv311`, install PyFLP into it, and **prove the blocker is gone with
output**, not with a claim.

## Background you need

`docs/blockers/pyflp-python-312.md` has the full diagnosis. In short: PyFLP's
`EventEnum` is an `enum.Enum` subclass with **no members**, relying on its own
`_missing_` hook. Python 3.12 rewrote `EnumType.__call__` to raise `TypeError`
before `_missing_` is consulted when the enum is empty. So `EventBase.__init__`
— which normalises every ID through `EventEnum(id)` — cannot construct any
event at all. Read and write die on the identical line. PyFLP's support matrix
is 3.8–3.11.

3.11 is the target because it is the newest supported interpreter **and** the
only supported one that needs no extra `fastenum` dependency (PyFLP carries
`Requires-Dist: f-enum (>=0.2.0) ; python_version <= "3.10"`).

**The main `.venv` stays on 3.12 and stays the default.** Do not migrate
anything else onto 3.11. This is a second, scoped environment for the FLP lane
only.

## Owned files — edit nothing else

- `.venv311/` (create)
- `docs/blockers/pyflp-python-312.md`
- `docs/state.md` — **open blocker 4**, not 5. It was renumbered when blocker 1
  was retired last session. Two other references to "open blocker 4" exist at
  line 13 and in the FL Studio table row; keep them consistent.
- `pytest.ini` (or wherever pytest config lives — check first)
- A scoped requirements file for this lane, e.g. `requirements-flp.txt` (new).
  **Do not edit `requirements.txt`.**
- `tests/flp/` (new directory, if you add tests there)

Do not touch `executor/flp/sort.py`, `tests/executor/test_flp_sort.py`,
`docs/context.md`, or any other lane's files.

## Steps

1. **Install Python 3.11.** `winget install Python.Python.3.11` is the
   expected route; the python.org installer is acceptable if winget fails.
   Verify with `py -0p` afterwards and cite the output.
2. **Create `.venv311`** scoped to this project. Confirm
   `.venv311\Scripts\python.exe --version` reports 3.11.x and cite it.
3. **Install PyFLP into it**, plus `pytest`. Record exact versions in
   `requirements-flp.txt`, pinned.
4. **Prove the blocker is gone.** Three separate pieces of cited output:
   - Instantiate an `EventEnum` member successfully — the exact operation that
     raised `TypeError` on 3.12.
   - `pyflp.parse()` a real PyFLP test fixture. The blocker file records which
     fixture was used before (`FL 20.8.4.flp`); fetch it to a scratch path
     **outside the repo**, do not commit a binary.
   - `pyflp.save()` a project successfully, and re-parse what you saved to
     prove the write is real, not just non-raising.
   Paste the actual command and actual output for each. A traceback-free run
   is not proof on its own — show the values.
5. **Document how pytest selects the 3.11 interpreter** for FLP tests without
   disturbing the main `.venv`. The previously drafted recommendation was a
   `realflp` marker registered in pytest config and excluded from the default
   run via `addopts`, invoked deliberately as:
   ```
   .venv311\Scripts\python.exe -m pytest -q -m realflp -p no:cacheprovider --basetemp=.pytest-basetemp
   ```
   Implement that unless you find a concrete reason it fails, in which case
   report the reason and what you did instead. The default suite must stay
   green on 3.12 and must not try to import pyflp.
   **This machine's system `TEMP` is locked down** — every pytest invocation
   needs `-p no:cacheprovider --basetemp=.pytest-basetemp`.
6. **Update the blocker file to resolved**, with the evidence inline. Keep the
   original diagnosis — it is the value. Add a resolution section carrying the
   real output. Then update `docs/state.md` blocker 4 to reflect that the
   Python side is resolved and note what still blocks Phase 2: blueprint 2.1
   still needs real guinea-pig `.flp` files and the user's dictated
   mixer-sorting convention, and both are the user's to provide.
7. Confirm `.venv311/` is gitignored, or add it. Do not commit a virtualenv.

## Out of scope

- Migrating the project, the main `.venv`, or any other component to 3.11.
- Committing. The orchestrator commits.
- Guessing at real mixer-sorting conventions.

## Verify before reporting

Both suites, both cited:

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
```

and the 3.11 invocation from step 5.

## Report back

- `py -0p` after install, verbatim.
- The three proofs from step 4, with real output.
- The exact command that runs FLP tests on 3.11.
- Both suite results.
