# Lane report: laptop system control

BUILD role. Work-board claim ID `4892d92b52154992a77dcfba07701207` (files,
role BUILD, work-item `laptop-system-control`); `test-workspace` resource
claimed separately once the sibling `pywinauto-zoom-whatsapp` lane released
it (see "Verification" below for the claim/release sequence and IDs).

## What landed

`executor/system_control/` -- one job kind (`system_control`), five
capability modules, one dispatch handler:

- `power.py` -- power plan (`powercfg`), wifi (`netsh`), Bluetooth radio
  (PowerShell `Get-PnpDevice`/`Enable-PnpDevice`/`Disable-PnpDevice`),
  display output (`DisplaySwitch.exe`).
- `scheduled_tasks.py` -- `schtasks` create/delete/query/list.
- `printing.py` -- printer list/default via `win32print`, print submission
  (raw text via `win32print`, arbitrary file via `win32api.ShellExecute`'s
  "print" verb).
- `files.py` -- confined move/rename/zip (`shutil`/`zipfile`/`pathlib`).
- `processes.py` -- guarded kill-by-name/pid (`psutil`).
- `handler.py` -- `build_system_control_handler()`, dispatches
  `payload["action"]` to the above.

Every subprocess call builds an argument list, never a formatted shell
string. The one exception needing extra care -- Bluetooth's `instance_id`,
which must reach a PowerShell `-Command` script -- is passed through an
environment variable (`JARVIS_PNP_INSTANCE_ID`/`JARVIS_PNP_ACTION`) and read
back with `$env:...`, never interpolated into the command text, so it is
read as plain string data and can never be parsed as PowerShell syntax.
Proven in `tests/executor/system_control/test_power.py::
test_set_bluetooth_enabled_passes_instance_id_via_environment_not_command_text`,
which feeds a payload containing a PowerShell injection attempt as the
`instance_id` and asserts it never appears in the command text.

### Proof per capability (real system, one-off, not in the pytest suite)

**1. Power / wifi / Bluetooth / display**

Power plan -- real switch and restore, `powercfg /list` before/after:

```
$ .venv\Scripts\python.exe -c "from executor.system_control import power; ..."
before: PowerPlan(guid='8c5e7fda-...', name='High performance', active=True)
after switch to Balanced: PowerPlan(guid='381b4222-...', name='Balanced', active=True)
restored: PowerPlan(guid='8c5e7fda-...', name='High performance', active=True)
```

Wifi listing + default-route detection (read-only, real):

```
wifi interfaces: [WifiInterface(name='Wi-Fi', state='connected')]
default route interface: Wi-Fi
```

This machine's one wifi adapter is literally named `Wi-Fi` and is also the
adapter `default_route_interface()` reports -- i.e. on this machine, a
`wifi.set_enabled` job targeting `"Wi-Fi"` with `enabled=False` would hit the
guard for real, not just in a test double.

Bluetooth listing (read-only, real) -- 37 PnP entries in the Bluetooth
class, including the physical radio itself:
`PnpDevice(instance_id='USB\\VID_0E8D&PID_8C38&MI_00\\7&317E70A6&0&0000',
friendly_name='MediaTek Bluetooth Adapter', status='OK')`. No instance id is
hardcoded anywhere in the code; a real `bluetooth.set_enabled` job would
supply one of these.

Display switching (`DisplaySwitch.exe /internal|/external|/clone|/extend`):
**not exercised against the real display.** Running it for real would
blank or reconfigure the physical screen mid-session with no one watching
to confirm/undo it -- judged unsafe to run unattended. Covered by unit
tests only (`test_switch_display_maps_mode_to_flag`,
`test_switch_display_rejects_unknown_mode_without_shelling_out`); the
wrapper is a two-line `subprocess.run(["DisplaySwitch.exe", flag])` behind a
fixed allow-list, low-risk to leave for a sighted manual check later.

Real Bluetooth *toggle* was likewise not exercised (listing was): this
machine has several currently-relevant paired devices (a Bluetooth
keyboard among them per the listing above), and disabling the radio for a
test could interrupt real input hardware mid-session. Unit-tested only.

**2. Scheduled tasks** -- created, queried, listed, deleted a real probe
task:

```
queried: ScheduledTaskInfo(name='JarvisSystemControlProbe', status='Ready',
  next_run_time='12/31/2099 11:59:00 PM')
probe present in list: True
confirmed deleted: ScheduledTaskNotFoundError raised on post-delete query
```

**3. Printing** -- real enumeration (read-only):

```
printers: ['OneNote (Desktop) - Protected', 'OneNote (Desktop)',
  'Microsoft XPS Document Writer', 'Microsoft Print to PDF', 'Fax']
default: OneNote (Desktop)
```

An actual print job (`print_text`/`print_file`) was not submitted for real
(would consume a physical page or spool an unwanted job); sequencing
(`OpenPrinter`/`StartDocPrinter`/`StartPagePrinter`/`WritePrinter`/
`EndPagePrinter`/`EndDocPrinter`/`ClosePrinter`) and the default-printer
switch-and-restore-around-print_file behavior are unit-tested against a
fake `win32print`/`shell_execute`.

**4. File moves/renames/zipping** -- real move, rename, zip inside the
default root, then cleaned up:

```
root: C:\Users\Ali\Desktop\jarvis\file_ops_workspace
moved to: ...\file_ops_workspace\sub\probe.txt exists: True
renamed to: ...\file_ops_workspace\sub\probe_renamed.txt exists: True
zipped to: ...\file_ops_workspace\probe.zip exists: True
cleaned up: True
```

**5. Process killing** -- spawned a disposable `ping -n 30 127.0.0.1`,
killed it for real, then proved the own-pid guard fires for real:

```
spawned disposable pid 24192 alive: True
kill_process returned: [24192]
alive after kill: False
own-pid guard raised as expected: refusing to kill protected process (pid=13160, name='python.exe')
```

`cloudflared.exe` guard checked live too -- not currently running on this
machine, so `kill_process(name="cloudflared.exe")` raised
`ProcessNotFoundError` rather than exercising the protection branch; that
branch (and the repo-venv-python branch) is covered by
`tests/executor/system_control/test_processes.py`'s fakes instead
(`test_kill_process_refuses_cloudflared_by_name`,
`test_kill_process_refuses_repo_venv_python_by_name`, plus the negative case
`test_kill_process_allows_python_from_an_unrelated_venv` proving the guard
is scoped to this repo's `.venv`, not every Python process on the machine).

## The wifi guard -- was it exercised by a test?

Yes, at both layers, and both simulate "this interface **is** the active
default-route adapter", not "this is the only adapter":

- `tests/executor/system_control/test_power.py::
  test_set_wifi_enabled_refuses_to_disable_the_default_route_adapter` --
  injects a fake `default_route_interface_fn` that reports `"Wi-Fi"` as
  active, calls `set_wifi_enabled("Wi-Fi", False, ...)`, asserts
  `WifiGuardError` and that the recording `run` fake was **never called**
  (the disabling `netsh` command is never reached).
- `test_set_wifi_enabled_allows_disabling_a_secondary_adapter` -- same fake
  reporting `"Wi-Fi"` active, but the call targets `"Ethernet 2"`; asserts
  it proceeds. Proves the guard is adapter-specific, not "block all
  disables".
- `test_set_wifi_enabled_never_guards_an_enable_request` -- proves an
  *enable* request never even consults the default-route detector.
- `tests/executor/system_control/test_handler.py::
  test_wifi_guard_propagates_through_the_real_registry_end_to_end` -- same
  scenario, but through `build_system_control_handler()`'s real (non-faked)
  action registry, proving the guard survives the payload-dispatch layer a
  real `system_control` job would actually go through, not just the
  `power.py` function in isolation.

Additionally, live on this machine (see proof #1 above): the wifi adapter
really is named `"Wi-Fi"` and `default_route_interface()` really does report
`"Wi-Fi"` as the active route -- so the guard's real-world trigger condition
is confirmed to actually hold here, not just in a fake.

## `system_control` payload schema

```
{"action": "<capability>.<operation>", "args": {...}}
```

| action | args | notes |
|---|---|---|
| `power.list_plans` | `{}` | returns `[{guid, name, active}, ...]` |
| `power.get_active_plan` | `{}` | returns `{guid, name, active}` or `null` |
| `power.set_plan` | `{guid}` | |
| `wifi.list_interfaces` | `{}` | returns `[{name, state}, ...]` |
| `wifi.set_enabled` | `{interface, enabled}` | `enabled=False` on the machine's own default-route adapter raises `WifiGuardError` |
| `bluetooth.list_devices` | `{}` | returns `[{instance_id, friendly_name, status}, ...]` |
| `bluetooth.set_enabled` | `{instance_id, enabled}` | |
| `display.switch` | `{mode}` | mode in `internal`/`external`/`clone`/`extend` |
| `scheduled_task.create` | `{name, command, schedule, start_time?, start_date?}` | `schedule` is schtasks' own `/sc` value (`ONCE`, `DAILY`, `ONLOGON`, ...) |
| `scheduled_task.delete` | `{name}` | |
| `scheduled_task.query` | `{name}` | raises `ScheduledTaskNotFoundError` if absent |
| `scheduled_task.list` | `{}` | returns `[name, ...]` |
| `printing.list_printers` | `{}` | returns `[name, ...]` |
| `printing.get_default_printer` | `{}` | returns name or `null` |
| `printing.set_default_printer` | `{name}` | |
| `printing.print_file` | `{path, printer?}` | prints via the OS "print" verb |
| `printing.print_text` | `{printer, text, document_name?}` | raw text spool job |
| `file.move` | `{src, dst}` | both confined to the file-ops root |
| `file.rename` | `{path, new_name}` | `new_name` must be a bare filename |
| `file.zip` | `{paths, zip_path}` | `paths` is a list |
| `process.kill` | `{name}` or `{pid}` | exactly one; never a substring match |

`enqueue-classifier` (still an open Class C decision per
docs/tasks/laptop-system-control.md) will need to produce exactly this
shape whenever it lands. Nothing in this lane parses free text or routes an
inbound message -- these handlers are dormant until something else enqueues
them, same as `flp_sort` today.

## Guards, named exactly

- **Wifi**: `power.WifiGuardError`, raised by `set_wifi_enabled()` before any
  disable command runs, when the target interface matches
  `default_route_interface()`'s report. Case/whitespace-insensitive
  comparison. Never guards an enable.
- **File ops**: `files.FileOpsPathOutsideRootError`, raised by
  `_ensure_within_root()` via `Path.resolve()` +
  `Path.relative_to()` (never a string-prefix check -- proven against a
  `root_evil`-vs-`root` sibling-directory spoof in
  `test_move_file_refuses_a_sibling_directory_that_string_prefixes_the_root`).
  Root is `JARVIS_FILE_OPS_ROOT`, defaulting to `<repo>/file_ops_workspace`
  -- a dedicated directory, not `Path.home()`/`Desktop`.
- **Processes**: `processes.ProtectedProcessError`, raised by
  `is_protected_process()` before any `terminate()` call, for: this
  executor's own pid; `cloudflared.exe` by exact name; `python.exe`/
  `pythonw.exe` whose `.exe()` path resolves under this repo's own
  `.venv` (not every Python process on the machine). Every candidate is
  checked before any is killed, so one protected match among several
  same-named processes blocks the whole call.

## What broke

Nothing. All 80 new tests pass in isolation and as part of the full offline
suite (see "Verification").

## What was specified but not done

- Real (not unit-tested) proof of `display.switch` and a real Bluetooth
  *toggle* -- both judged unsafe to run unattended against this live
  machine's actual screen/radio mid-session (see proof section above for
  the specific reasoning per capability). The wrappers exist, are unit
  tested, and are structurally identical in risk profile to the wifi/power
  wrappers that *were* proven live.
- No `enqueue-classifier` wiring, no text parsing, no WhatsApp-reachable
  path -- explicitly out of scope per the brief.

## Dependency added

`psutil==7.2.2` -- appended to `docs/tasks/deps-laptop-system-control.txt`
for CORE to fold into `requirements.txt`. Installed into `.venv` and
confirmed importable:

```
.venv\Scripts\python.exe -m pip install psutil==7.2.2
.venv\Scripts\python.exe -c "import psutil"
```

`pywin32`/`win32print`/`win32api` needed no install -- already part of the
pinned `pywin32==312` install, confirmed importable:

```
.venv\Scripts\python.exe -c "import win32print, win32api"
```

## For CORE: the one line for `executor/poller.py`

In `DEFAULT_HANDLERS` (alongside the existing `flp_sort`/`whatsapp_webhook`
entries), plus the matching import:

```python
from executor.system_control.handler import build_system_control_handler
...
DEFAULT_HANDLERS: dict[str, HandlerRegistration] = {
    ...
    "system_control": HandlerRegistration(build_system_control_handler()),
}
```

No changes requested to `executor/poller.py`'s permanent-fail exception list
(`ReorderNotSupported`, `FileNotFoundError`) -- worth CORE's judgment call,
not this lane's: `WifiGuardError`, `ProtectedProcessError`,
`FileOpsPathOutsideRootError`, and `UnknownSystemControlActionError` are all
permanent (retrying changes nothing), matching the existing rationale for
that list, but this lane doesn't own `poller.py` and isn't adding to it
unasked.

## Verification

```
.venv\Scripts\python.exe -m pytest tests/executor/system_control -q -p no:cacheprovider --basetemp=.pytest-basetemp
80 passed in 0.47s
```

Full offline suite (claimed `test-workspace` resource once the sibling
`pywinauto-zoom-whatsapp` lane released it -- claim ID
`81ac6360eb934a64acf8796e7243a7aa` -- released after this run):

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
722 passed, 2 skipped, 5 deselected, 4 warnings in 65.73s (0:01:05)
```

Exit code 0. The 4 warnings are pre-existing (an unregistered `guiauto`
pytest mark in the sibling lane's tests, and a `supabase` client
deprecation notice) -- unrelated to this lane's changes.
