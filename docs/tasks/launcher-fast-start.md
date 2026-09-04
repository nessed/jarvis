# Lane: launcher-fast-start

**Role:** BUILD. Do not commit. Do not edit `requirements.txt` (pywin32 is
already pinned; `win32job` imports fine in `.venv`).
**Owns (exclusively):** `tools/start_jarvis.py`,
`tests/tools/test_start_jarvis.py`, `start-jarvis.bat`.
**Does not own:** anything else. Report needs, do not edit.

Before editing, claim:

```
.venv\Scripts\python.exe tools/work_board_claim.py claim --role BUILD --work-item launcher-fast-start --file tools/start_jarvis.py --file tests/tools/test_start_jarvis.py --file start-jarvis.bat
```

Release the claim ID after verification.

Read the module docstring of `tools/start_jarvis.py` first. Its rules stand:
**nothing in the launcher ever kills, signals or cleans up a process it did
not spawn.** The single-instance lock stays exactly as it is.

## Why (observed 4 Sep 2026)

Ali's complaint is that JARVIS is slow to start and makes the laptop lag.
Four concrete things in the launcher contribute, all measured today:

1. **Orphaned children.** Two `whisper-server.exe` processes from earlier
   launches (started 18:17 and 19:50) were still alive at 20:30 with the
   stack down, holding 750 MB and both listening on 127.0.0.1:8081. The
   supervisor's `shutdown()` only runs if `main` reaches its `finally`.
   Closing the console window (which `start-jarvis.bat` invites) kills
   python outright; children spawned with `CREATE_NEW_PROCESS_GROUP`
   survive. Every launch since then has been stacking a 3 GB model load on
   top of the last one.
2. **Serial startup.** The order is Ollama probe -> bus -> tunnel ->
   tunnel_reachable (up to 45 s) -> repoint (subprocess) -> whisper-server
   (loads a 3 GB model, waits up to 60 s) -> workers. Today's logs: tunnel
   URL at 14:56:10Z, whisper-server spawned 14:57:08Z. Whisper's load and
   the tunnel+repoint are independent; the workers only need the bus and
   Supabase. Sum became ~2 minutes; max would be under one.
3. **Ollama must be started by hand.** Step 1 exits with "Start it and run
   this again" if 11434 is silent. It was silent tonight. `ollama.exe` lives
   at `%LOCALAPPDATA%\Programs\Ollama\ollama.exe` and `ollama serve` binds
   11434.
4. **No timing.** Nothing prints how long a step took, so "slow" has no
   number.

## What to build

### 1. A Windows Job Object so children die with the launcher

Create one job (`win32job.CreateJobObject`) with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` in its extended limit info, and assign
every spawned child to it in `Supervisor.spawn`. When the launcher process
ends for any reason — Ctrl+C, window close, crash, taskkill — the OS closes
the last handle and kills the tree. This is the same fail-open shape as the
singleton socket: nothing to clean up, nothing to go stale. Keep it
Windows-only behind `os.name == "nt"` and a lazy `import win32job`; a
missing pywin32 must degrade to a one-line warning, not a failed launch.
`process.terminate()` in `shutdown()` stays for the orderly path.

Assigning a child that was created with `CREATE_NEW_PROCESS_GROUP` to a job
works on Windows 8+; it does not need `CREATE_BREAKAWAY_FROM_JOB`. If the
launcher itself is already inside a job that forbids nesting (some
terminals do this), `AssignProcessToJobObject` fails — catch it, warn once,
continue.

### 2. Start Ollama if it is not answering

If `ollama_ready()` is false: look for `ollama.exe` at
`%LOCALAPPDATA%\Programs\Ollama\ollama.exe` (env `JARVIS_OLLAMA_EXE`
overrides), spawn `ollama serve` as an **optional** supervised child
logging to `tools/ollama.out.log`, and wait up to 30 s for `/api/tags`. If
it is answering already, do nothing (Ali may run the tray app). Only if
neither works does the old "start it and run this again" message remain.

### 3. Parallelize

After the bus answers:

- Spawn `whisper-server` immediately (its readiness wait moves to the end).
- Spawn the workers immediately (they need only the bus process to exist
  for `/status` and Supabase for polling; the tunnel is irrelevant to
  them).
- Then do tunnel -> reachability -> repoint as today.
- Then `wait_for_whisper_server()`, with whatever timeout is left.

Keep step numbering readable; renumber the `[n/5]` labels honestly.

### 4. Refuse to stack a second whisper-server

Before spawning, if `WhisperServerClient().is_ready()` is already true on
the configured port, do **not** spawn another. Say so, name the PID(s) via
the existing `pid_holding_port` helper (extend it to return all listeners
if two are bound, which is what tonight showed), and continue using the one
that is there. Never kill it. Add the same guard for the bus port 8000: if
something already answers `/health` before we spawn, that is the duplicate
case the singleton lock is meant to catch — refuse with the PID, as the
lock does.

### 5. Print elapsed time

Per step (`ready (2.1s)`) and a total on the final banner
(`JARVIS is running — 47s`). Use `time.monotonic()`.

## Verification

The existing 45 tests in `tests/tools/test_start_jarvis.py` fake the
subprocesses; extend in the same style. Job-object code paths can be tested
by injecting a fake `win32job` module via `monkeypatch.setitem(sys.modules,
...)`. Then:

```
.venv\Scripts\python.exe -m pytest -q tests/tools/test_start_jarvis.py
.venv\Scripts\python.exe -m pytest -q
```

**Do not run the real launcher.** It mints a tunnel and re-points Meta's
webhook, and two orphaned whisper-servers already hold 8081. A dry run of
the orchestration with fakes is the proof. CORE runs it live.

## Report

`docs/tasks/launcher-fast-start-report.md`: what changed, the test line,
the full-suite line, and anything you could not do.
