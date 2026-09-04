---
id: launcher-fast-start
status: done
lane: AUTO
priority: 1
phase: 0
blocked-on: none
files: tools/start_jarvis.py, tests/tools/test_start_jarvis.py, start-jarvis.bat
resources: none
---

# launcher-fast-start — children die with the launcher, and startup is parallel

## Goal

`docs/history/infra-audit-2026-09-04.md` §Startup and §Orphans: every
step ran in series (tunnel probe + re-point alone was 57 s, then a 3 GB
Whisper load, then three 4.9 s worker imports), Ollama had to be started
by hand, closing the console window orphaned every child, and nothing
printed a duration.

## Log

**4 Sep 2026 — done.** BUILD lane on Opus 5, brief
`docs/tasks/launcher-fast-start.md`, report `docs/tasks/launcher-fast-start-report.md`.

- **Job object.** `create_job_object()` with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`;
  `Supervisor.adopt` puts every child in it, so the launcher dying any way
  at all takes its children with it. Missing pywin32 or a refused
  assignment is one warning line. Nothing kills a process the launcher did
  not spawn; the singleton lock is untouched.
- **Ollama started if silent.** `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`
  (`JARVIS_OLLAMA_EXE` overrides) spawned as an optional child, 30 s wait.
- **Parallel.** `[1/6]` Ollama, `[2/6]` bus, `[3/6]` whisper spawn (no
  wait), `[4/6]` workers, `[5/6]` tunnel + re-point, `[6/6]` whisper
  readiness with the remainder of its budget.
- **No stacking.** An already-serving whisper-server on 8081 is used, its
  PIDs named, never a second one spawned; something already answering on
  8000 refuses the launch with its PID, as the singleton lock does.
- **Timing.** Per-step `ready (2.1s)` and `JARVIS is running — 47s.`

```
.venv\Scripts\python.exe -m pytest -q tests/tools/test_start_jarvis.py
75 passed in 4.70s
```

**Not live-run.** The lane was told not to (it mints a tunnel and
re-points Meta); CORE's live run was refused by the session's command
classifier. The saving is therefore structural, not yet a measured
number — the new banner prints it, and **U16** asks Ali for it.
