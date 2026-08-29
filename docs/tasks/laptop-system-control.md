# Lane: laptop system control (power, network, tasks, printing, files, processes)

Blueprint 2.4's "you pick, agent builds" step, answered. Ali named the apps
and end states via a personal-context agent that knows his habits (relayed
2026-08-29). It split the ask in two: things with a real CLI/API (this lane,
no UIA needed) and things that only exist behind a GUI (`pywinauto-zoom-
whatsapp`, the sibling lane). His own framing: "If you find yourself opening
Settings in pywinauto, stop and go find the CLI." This lane is that CLI path.

Five capabilities, one coherent theme (drive this Windows laptop's own
settings/processes without touching a GUI):

1. **Power mode / wifi / bluetooth / display switching** — `powercfg`,
   `netsh`, `DisplaySwitch.exe`, and PnP device toggling for Bluetooth (there
   is no first-class Bluetooth-radio CLI; `Get-PnpDevice` /
   `Disable-PnpDevice` / `Enable-PnpDevice` against the Bluetooth radio class
   is the accepted approach — confirm the exact class/instance ID on this
   machine before hardcoding one).
2. **Scheduled tasks** — `schtasks`.
3. **Printing** — `win32print` (already installed; part of the existing
   `pywin32` dependency, confirmed via `.venv\Scripts\python.exe -c "import
   win32print"` 2026-08-29 — do not add it to the deps file).
4. **File moves, renames, zipping** — plain Python (`shutil`, `zipfile`,
   `pathlib`). No new dependency.
5. **Killing processes** — `psutil` (not installed; add it).

## The one sharp edge, read this first

**Never let a wifi-off or airplane-mode-style job actually run on this
machine's own primary adapter without a guard.** This laptop's own wifi is
what carries the Cloudflare tunnel, the bus, and Meta's webhook. A job that
disables wifi disconnects the machine that would be running the job — it
cannot even report back that it succeeded. Build the capability (the
handler must exist and be correct), but:

- Default to listing/toggling *secondary* radios (Bluetooth) freely.
- The wifi-toggle function must accept an explicit `interface` argument (no
  "the current one" default) and its handler must refuse a request that
  would disable the adapter carrying the default route, detected via
  `ipconfig`/`Get-NetAdapter` — raise a clear, named exception rather than
  silently no-op'ing or silently succeeding.
- Say explicitly in the report whether this guard was actually exercised by
  a test (simulate "this is the active internet adapter", not "this is the
  only adapter").

This is a mechanism-building lane, not a wiring lane: nothing here makes any
of this reachable from a WhatsApp message. `enqueue-classifier` (routing
inbound text to a job kind) is still an open Class C decision in
`docs/plan.md` — do not build or imply any text-parsing/dispatch path here.
These handlers are dormant until something else enqueues them, same as
`flp_sort` today.

## Ownership — files this lane may write

```
executor/system_control/                  <- new package
executor/system_control/__init__.py
executor/system_control/power.py          <- power mode, wifi, bluetooth, display
executor/system_control/scheduled_tasks.py
executor/system_control/printing.py
executor/system_control/files.py
executor/system_control/processes.py
executor/system_control/handler.py        <- build_system_control_handler() -> JobHandler
tests/executor/system_control/            <- mirror the module layout above
docs/tasks/deps-laptop-system-control.txt <- psutil, for CORE to integrate
docs/tasks/laptop-system-control-report.md
```

Check `python tools/work_board_claim.py list` and claim every path above
before writing. Stop on a conflict. Release the claim ID after verification.

**Do not write:**

- `executor/poller.py` (hot file — `DEFAULT_HANDLERS` registration is a
  one-line addition CORE makes after this lane and its sibling both land, to
  avoid two lanes colliding on the same file).
- `requirements.txt` — append `psutil` (pin the version you actually
  install) to `docs/tasks/deps-laptop-system-control.txt` instead.
- Anything under `voice/`, `diagnostics/`, or `ingest/`/`memory/` — unrelated
  live lanes may hold those; check `list` regardless.

## Shape to match

`JobHandler = Callable[[Job], None]` (`executor/poller.py:44`). Follow
`executor/flp/sort.py` / `build_flp_sort_handler()`'s existing shape: a
`build_system_control_handler()` factory returning a closure, one job kind
(`system_control`, payload carries an `action` field naming which of the five
capabilities and its arguments — design the payload schema yourself, but
keep it one job kind with an `action` dispatch rather than five job kinds;
document the exact schema in the report since `enqueue-classifier`, whenever
it lands, will need to produce it).

Each capability needs its own pure/testable function *and* a thin
job-payload-shaped wrapper, the same split `sort.py` uses (`flp_backup`,
`load`, `apply_rules`, `save`, `verify` are each independently unit-tested
against fakes; the handler just sequences them). Do not shell out with
untrusted string interpolation — build argument lists (`subprocess.run([...],
...)`, never a formatted shell string) so a payload value can never break out
of its argument.

For file operations: confine writes/moves/deletes to an explicit root the
same way `executor/flp/sort.py`'s `flp_sort_root()` /
`FlpSortPathOutsideRoot` guard does (env-configurable, default somewhere
obviously scoped like `Path.home() / "Desktop"` is wrong — pick a dedicated
root, e.g. `JARVIS_FILE_OPS_ROOT`, and name your choice in the report). A
`resolve()`/`relative_to()` check before any write, exactly like the FLP
guard.

For process killing: require an exact process name or PID, never a
substring/pattern match, and never allow killing this executor's own
process, `python.exe`/`pythonw.exe` running under this repo's `.venv`, or
`cloudflared.exe`/anything matching the JARVIS stack itself — name the
exact guard you build in the report. Getting this wrong kills the job that's
running the kill.

## Verification

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
```

Full offline suite, not a focused subset. Claim `test-workspace` first.
Every test runs against fakes/mocks for `subprocess`, `psutil`, and the
filesystem (via `tmp_path`) — **never** actually change this machine's real
power plan, actually toggle a real radio, actually create a real scheduled
task, or actually kill a real process as part of the automated test suite.
A manual, cited, one-off proof that each wrapper works against the real
system (e.g. `powercfg /list` before/after a plan switch, a `schtasks /query`
showing a created-then-deleted probe task) belongs in the report as evidence,
not in the pytest suite.

## Report

`docs/tasks/laptop-system-control-report.md`: what landed with proof for each
of the five capabilities, the `system_control` payload schema you designed,
whether the wifi-guard was actually exercised by a test, what broke, what was
specified but not done, the dep added, and the exact one line CORE needs to
add to `executor/poller.py`'s `DEFAULT_HANDLERS`.
