# Lane A: single-instance guard for the launcher

## Why this lane exists

On 26–27 August 2026 **two full copies of the JARVIS stack ran at once** — one
under `.venv\Scripts\python.exe`, one under the global Python install. Both had
their own bus, their own Cloudflare tunnel, and their own executor polling the
same Supabase queue. Cause was never confirmed; most likely `start-jarvis.bat`
was double-launched.

Recovering from it made things worse. Force-killing by PID (`taskkill /T`)
caused a **full outage** — Windows' parent/child process tracking on this
machine did not match reality, so the tree-kill took down more than intended.
Since then only `Ctrl+C` in the owning window is trusted to stop a copy.

The correct fix is to make the second copy impossible, not to get better at
killing it.

### Why the existing health checks did not catch it

`tools/start_jarvis.py` already probes before it proceeds, but **every probe it
runs is satisfied by the other copy's processes**:

- `ollama_ready()` — `GET 127.0.0.1:11434/api/tags`. Ollama is a shared
  singleton service; it answers for everyone. Never a duplicate signal.
- `wait_for_bus()` — `GET 127.0.0.1:8000/health`. This is the crucial one. A
  bus is already listening on 8000 because *copy one* started it. Copy two's
  own `uvicorn` child fails to bind (port in use), writes the error into
  `tools/bus.out.log`, and dies — but `wait_for_bus()` gets its 200 from copy
  one's bus and reports success. **An HTTP probe on a loopback port cannot tell
  you whose process answered.** The launcher then sails past a dead child.
- `tunnel_reachable()` — probes the *newly minted* tunnel URL, which is genuine
  and unique per copy. This is exactly the damage: copy two mints a second
  Quick Tunnel and re-points Meta's webhook at it, silently stealing inbound
  traffic from copy one.
- `supervisor.check_alive()` — only polls after all four steps are up. By then
  the second tunnel is minted and Meta is already re-pointed.

So the duplicate is not merely tolerated, it is actively destructive: it mints
a tunnel and rewrites live Meta configuration before anything notices.

## Scope

Owned files — **edit nothing else**:

- `tools/start_jarvis.py`
- `tests/tools/test_start_jarvis.py` (new file; `tests/tools/` already exists
  and holds `test_run_backfill.py`)

### What to build

A singleton lock acquired by **binding an exclusive localhost TCP port**,
before anything else runs.

1. Add a module-level constant for the port with an env override. Suggested:

   ```python
   SINGLETON_PORT = int(os.environ.get("JARVIS_SINGLETON_PORT", "8765"))
   ```

   Pick and document the default. It must not collide with 8000 (bus) or
   11434 (Ollama). Document the choice in the docstring.

2. Acquire it as the **very first thing `main()` does — before the Ollama
   check, before `load_dotenv`, before any child is spawned.** Ordering is the
   whole point: the launcher must refuse before it mints a tunnel or re-points
   Meta, because those two actions are what made the duplicate destructive.

3. Bind semantics. On Windows, `SO_REUSEADDR` lets two sockets share a port —
   it must **not** be set, or the guard silently passes. Bind
   `127.0.0.1:SINGLETON_PORT` plainly and let the second bind fail.

4. On bind failure: print which PID holds the port if discoverable, print that
   another copy of JARVIS is already running, and **return a nonzero exit
   code**. Mint no tunnel. Re-point no webhook. Spawn no child.

   For PID discovery, prefer `psutil.net_connections()` if psutil is already a
   dependency; otherwise shell out to `netstat -ano` and match the port. If
   discovery fails for any reason, say so and still refuse — a missing PID is
   a worse message, not a reason to proceed.

5. Hold the socket open for the process's whole lifetime (keep a reference so
   it is not garbage-collected; do not `listen()`-and-forget in a local).

6. **Docstring must state the fail-open rationale, citing the heartbeat.**
   `executor/heartbeat.py` deliberately uses a timestamp file rather than a PID
   lock so that "if the executor is killed the marker simply goes stale on its
   own, so a crash can never leave a lock behind that blocks every future batch
   run." A bound socket has the same property for free: **the OS releases the
   bind when the process dies, however it dies** — crash, kill, or Ctrl+C. No
   stale lockfile can ever wedge a future launch. Say this explicitly and name
   `executor/heartbeat.py` as the precedent.

### Tests

`tests/tools/test_start_jarvis.py` must cover, without starting the real stack:

- Acquiring the lock on a free port succeeds and returns a held socket.
- A second acquisition on the same port fails.
- Bind failure makes `main()` return nonzero **and spawn nothing** — assert
  this by monkeypatching `Supervisor.spawn` (and `subprocess.run`) to fail the
  test if called at all. This is the regression that matters: it proves no
  tunnel is minted and Meta is not re-pointed.
- The env override is honoured.

Bind test ports supplied by the test (ask the OS for a free one with
`bind(("127.0.0.1", 0))`), never the real default, so a running JARVIS does not
make the suite red.

Refactor `main()` as needed to make this testable — extracting the acquire step
into its own function is expected.

## Out of scope

- Killing, signalling, or cleaning up any existing process. **Never.**
- `executor/`, `bus/`, `memory/`, `requirements.txt`, any other test file.
- Any commit. The orchestrator commits after integration.

New dependencies go in `docs/tasks/deps-launcher-singleton.txt`, one pinned
line each. Do not edit `requirements.txt`.

## Verify before reporting

Full offline suite, exact flags (the system `TEMP` on this machine is locked
down and pytest fails with `PermissionError` without them):

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
```

Cite the output verbatim. A claim without its command output is not a result.

## Report back

- The port chosen and its env var name.
- How PID discovery works and what it prints when it cannot find one.
- Full offline suite output.
- Any shared interface you changed and every implementer of it.
