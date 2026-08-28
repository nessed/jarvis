# flp-write-path-guard + flp-diff-report-emission

Two `docs/plan.md` "can run today" Phase 2 jobs, same file, done as one lane.
BUILD role: do not commit, do not touch `requirements.txt`. Own only
`executor/flp/sort.py` and `tests/flp/test_flp_sort.py` (claimed via
`work_board_claim.py`, work-item `flp-write-path-and-diff-report`) — every
other file in the repo is off limits.

Read `executor/flp/sort.py` in full first — it is small (278 lines), fully
docstringed, and every dependency in `build_flp_sort_handler` is already
injectable (`backup`, `loader`, `saver`, `verifier`), matching
`executor.handlers.whatsapp.build_whatsapp_webhook_handler`'s pattern. Match
that style; do not introduce a different one.

## Blueprint text (verbatim, `docs/blueprint.md:214-220`)

> **2.1 Guinea pigs — you, 5 min.** Copy 2–3 real `.flp` projects into
> `test_projects/`. Originals never get touched. Dictate your mixer
> conventions to the agent...
>
> **2.2 PyFLP scripts — CLI agent.** `pip install pyflp`, then: `flp_backup()`
> (timestamped copy before every write), parse → apply your rules → save, a
> diff report (old name → new name per insert), and a verify pass that
> re-parses the saved file and confirms edits stuck. Wrapped as an executor
> job type (`kind: flp_sort`, payload: path + ruleset).
>
> **2.3 Verification loop — you.** Open each edited project in FL Studio:
> loads clean, mixer matches the diff report, audio plays, nothing else
> moved.

## Job 1 — flp-write-path-guard

**The gap:** `build_flp_sort_handler`'s `_handle` (sort.py:267-275) calls
`saver(project, path)` where `path = job.payload["path"]` — it writes
straight back over whatever path the job names. `flp_backup()` runs first, so
a copy exists, but the path named in the job can be anything, including a
real project living outside `test_projects/`. Blueprint 2.1's "Originals
never get touched" means the *only* thing `flp_sort` should ever write to is
a path already inside the designated safe root (`test_projects/` by
default) — the user's real `.flp`, wherever it actually lives, should never
be a legal write target for this job kind at all.

**What to build:** a guard in `build_flp_sort_handler` (or a small helper
`sort.py` function it calls) that resolves `job.payload["path"]` and refuses
— raising, before `backup()` or `loader()` ever run — if it is not inside a
configured safe root. Make the root injectable/configurable (an
environment variable read at handler-build time, e.g.
`JARVIS_FLP_SORT_ROOT`, defaulting to `test_projects/` resolved from the
repo root — check how `JARVIS_FLP_FIXTURE` is read elsewhere in the repo for
the existing pattern for env-configured paths in this component, and match
it). Use `Path.resolve()` and a proper "is this path a descendant of that
root" check (not a naive string-prefix check — that breaks on
`test_projects2/` or symlinks). Raise a clear, named exception (a new
`FlpSortPathOutsideRoot` or similar, following the existing
`ReorderNotSupported`/`FlpSortVerificationFailed` naming and docstring
style) so the executor's existing retry/dead-letter path treats it as a
type-only diagnostic like every other handler failure.

**Tests:** a job payload path inside the root proceeds normally (existing
behavior, still covered); a path outside it raises the new exception and
`backup`/`loader`/`saver` are never called (assert on the injected fakes);
a path that only superficially looks inside via string prefix (e.g.
`test_projects_evil/song.flp` when the root is `test_projects/`) is still
correctly rejected.

## Job 2 — flp-diff-report-emission

**The gap:** `apply_rules()` already returns a `MixerDiff` (sort.py:143-201)
and `_handle` computes it (`diff = apply_rules(project, ruleset)`,
sort.py:272) but only uses it to call `verifier(path, diff, ...)` — the diff
itself is never written anywhere. Blueprint 2.3 asks the user to compare FL
Studio against "the diff report," which today does not exist as an
artifact.

**What to build:** write `diff` to disk as part of `_handle`, alongside the
backup (same directory as the target file, matching `flp_backup`'s naming
convention: `<stem>.<UTC compact ISO>.diff.json` is a reasonable choice —
use the same timestamp source/format `flp_backup` uses so the backup and its
diff report are trivially pairable by timestamp). Content: `MixerDiff` has
`.as_dict()` already (`{before: after}`) — decide whether the raw
`InsertRename` tuples (with `iid`) or the simpler `as_dict()` shape is more
useful for a human comparing against FL Studio's mixer, and write valid
JSON. Only write a report when there's something to report — `MixerDiff`
already has `__bool__` wired to "any renames occurred"; an empty diff writing
an empty report file every run is noise, use your judgment on whether to
skip the write when `not diff`, and say which you chose and why in your
report.

Keep this an injectable dependency too (a `report_writer` callable
parameter on `build_flp_sort_handler`, following the existing pattern)
so it stays unit-testable without real disk I/O in most tests, with at
least one test exercising the real default writer against a temp path.

**Tests:** a run with actual renames writes a report whose content matches
the diff; a run with zero renames does (or does not, per your decision)
write a report, and that behavior is asserted; the report path is derived
correctly from the target path.

## Verification

Run the full offline suite exactly as CLAUDE.md specifies:

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
```

Also run, since it's the fast/free live-fixture check for this exact module
and does not touch anything outside `.venv311`'s own site-packages:

```
.venv311\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp -m realflp tests/flp/
```

Cite both outputs. Do not report done without them. Do not commit. Report
back: what changed in `executor/flp/sort.py` (function/exception names,
exact new signatures), the diff-report format you chose and why, test counts
before/after, and anything above you could not complete and why.
