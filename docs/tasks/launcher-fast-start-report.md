# Lane report: launcher-fast-start

BUILD lane. Nothing was committed. Files touched are exactly the three the
brief assigns: `tools/start_jarvis.py`, `tests/tools/test_start_jarvis.py`,
`start-jarvis.bat`. Claim `8928b25ed7bd43978d384217ec489258`, released after
verification.

**The real launcher was never run.** It mints a tunnel and re-points Meta, and
two orphaned whisper-servers already hold 8081. The orchestration is proved
with fakes in `tests/tools/test_start_jarvis.py`; CORE runs it live.

## What changed

### 1. A kill-on-close job object (brief §1)

`create_job_object()` builds one job with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; `Supervisor` takes it as
`Supervisor(job=...)` and `spawn` puts every child in it through the new
`Supervisor.adopt`. When the launcher process ends for any reason — Ctrl+C,
window close, crash, taskkill — the OS closes the last handle and takes the
tree with it. Fail-open by construction, like the singleton socket: no state to
clear, nothing to go stale.

Degradations are one warning line and a launch that still works:

- not Windows → no job, silently;
- pywin32 missing (`sys.modules["win32job"] is None` in the test) → one line;
- `AssignProcessToJobObject` refused, which is what a terminal that already
  runs us inside a non-nesting job does → one line, once, then the launch
  continues with every child still supervised.

`process.terminate()` in `shutdown()` is untouched — it still covers the
orderly path. **Nothing kills, signals, or cleans up a process the launcher did
not spawn**, and the singleton lock is byte-for-byte as it was.

Verified against real pywin32, not only the fake:

```
$ .venv\Scripts\python.exe -c "... win32job round-trip ..."
launcher job kill-on-close: True
no processes in it: ()
```

That call creates a job and assigns nothing to it, so no process was affected.

### 2. Ollama is started, not delegated to Ali (brief §2)

`ollama_executable()` finds `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`, with
`JARVIS_OLLAMA_EXE` overriding. On this machine:

```
C:\Users\Ali\AppData\Local\Programs\Ollama\ollama.exe
```

If 11434 already answers, nothing happens — Ali may be running the tray app.
Otherwise `ollama serve` is spawned as an **optional** supervised child logging
to `tools/ollama.out.log`, and `wait_for_ollama()` gives it 30 s. Only if that
also fails does the old "Start it and run this again" message stand, and it
still returns 1.

### 3. Parallel startup (brief §3)

The order was Ollama → bus → tunnel → reachability (up to 45 s) → repoint →
whisper (3 GB model, up to 60 s) → workers. It is now:

```
[1/6] Local AI (Ollama)
[2/6] Webhook receiver        spawn bus, wait for /health
[3/6] Voice (whisper-server)  spawn only — no wait
[4/6] Workers                 spawn all three
[5/6] Public tunnel           mint, reachability, repoint
[6/6] Voice readiness         wait out whatever is left of whisper's budget
```

Whisper's model load and the tunnel/repoint work now overlap, which is the
whole point: they were always independent, and the workers need only the bus
process and Supabase. Step 6 waits `WHISPER_READY_TIMEOUT` minus what the
tunnel already spent, with a 5 s floor, so a slow tunnel spends whisper's
budget instead of adding to it.

The whisper block moved out of `main` into `spawn_whisper_server(supervisor)`,
which returns the config to wait on later or `None` when there is nothing to
wait for.

### 4. No second whisper-server, no second bus (brief §4)

`spawn_whisper_server` checks `WhisperServerClient().is_ready()` first. If one
is already serving, it says so, names every PID, and **uses the one that is
there** — nothing spawned, nothing stopped, nothing killed.

`pid_holding_port` grew a plural sibling, `pids_holding_port`, because
4 Sep 2026 showed *two* whisper-servers on 8081 and naming one would have made
a pile-up look like a stray. `describe_holders(port)` renders
`PID 4242` / `PIDs 111 and 222` / an honest "unknown process". The single-PID
helper is unchanged in behaviour and still backs the singleton refusal.

Same guard on 8000: `bus_is_answering()` before spawning uvicorn. If something
already answers, the launch refuses with the PID and mints no tunnel — the
duplicate case the singleton lock exists for, caught where the lock cannot see
it (a bus left behind by a closed window).

### 5. Elapsed time (brief §5)

Every step prints its own — `ready (2.1s)`, `listening on 127.0.0.1:8000
(1.4s)` — and the final banner carries the total:
`JARVIS is running — 47s.` All from `time.monotonic()`.

### 6. `start-jarvis.bat`

Comment only. The old line promised that closing the window stops JARVIS, which
was the false claim that produced the orphans. It now says why that is true:
the children are in a kill-on-close job.

## Verification

```
$ .venv\Scripts\python.exe -m pytest -q tests/tools/test_start_jarvis.py
75 passed in 4.70s

$ .venv\Scripts\python.exe -m pytest -q
1433 passed, 9 deselected in 70.49s (0:01:10)
```

45 tests existed; 30 were added, all in the existing style — fakes only, no
real process is started, stopped, killed or signalled anywhere in the file. The
new `main` tests redirect `ROOT`/`LOG_DIR` into `tmp_path`, bind a
kernel-assigned singleton port, and replace every spawn, probe, wait and the
repoint subprocess, so they assert the launch *order* without any side effect:

```
["bus", "whisper-server", "whatsapp-worker", "background-worker",
 "action-worker", "tunnel", "repoint", "whisper-ready<=59.9"]
```

## Not done

- **Nothing live.** No launcher run, no tunnel, no webhook change, and the two
  orphaned whisper-servers on 8081 were left exactly where they are. Only a
  live run can measure the actual saving; the claim here is structural — the
  two slow independent waits now overlap.
- **No dependency change.** pywin32 was already pinned and `win32job` imports
  in `.venv`.
- **`report_duplicate` was left alone.** It still uses the singular
  `pid_holding_port`. Two processes cannot both hold the singleton port, so the
  plural form would be noise there.
