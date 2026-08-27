# Lane B1: backfill liveness guard

## Why this lane exists

**This is the exact gap that starved eight live WhatsApp messages on 26 August
2026.** Read `docs/history/whatsapp-reply-failures.md` before starting — it is
the incident record and this brief links to it deliberately.

Ollama is a **single serial resource** on this machine. Local fact extraction
is CPU-only and costs ~55s per turn (roughly 250x an embedding's ~0.5s). A
batch pass over the corpus drives the same local model every live reply
depends on, so running one while the executor is polling starves inbound
messages for the batch's entire duration.

`executor/heartbeat.py` exists to prevent that. The executor touches
`.executor-heartbeat` each poll; batch tools read its age and refuse to start.
A timestamp rather than a PID lock is deliberate: a killed executor lets the
marker go stale on its own, so a crash can never leave a lock behind that
blocks every future batch run.

`tools/distill_memory.py` already uses this guard. **`tools/run_backfill.py`
does not** — it is the other tool that drives Ollama in bulk, and it is
completely unguarded. That is the bug.

## Scope

Owned files — **edit nothing else**:

- `tools/run_backfill.py`
- `tests/tools/test_run_backfill.py` (exists; extend it)

### The pattern to copy, exactly

From `tools/distill_memory.py`. Import:

```python
from executor.heartbeat import refuse_if_executor_is_live
```

Flag, with **this same help text**:

```python
parser.add_argument("--force", action="store_true", help="run even while the executor is polling")
```

Guard, placed so it runs **before any work and before `open_local_mem0_memory()`**
but is skipped for `--dry-run` (a dry run lists discovered files and drives no
model, so it must stay usable at any time):

```python
if not args.force and not args.dry_run:
    refusal = refuse_if_executor_is_live("Backfilling")
    if refusal:
        logger.error(refusal)   # see note on output below
        return 2
```

Return code **2**, matching distill. The tool name string is `"Backfilling"` —
`refuse_if_executor_is_live` interpolates it into "…{tool_name} drives the same
local Ollama that live replies need…", and the message already ends with "Stop
the executor first, or pass --force if you accept slow replies while this
runs." Do not rewrite that message; it lives in `executor/heartbeat.py`, which
this lane does not own.

**Output note:** `run_backfill.py` currently uses bare `print()`, not `logging`.
Either add a module logger with `logging.basicConfig` as distill does, or emit
the refusal via `print(..., file=sys.stderr)`. Prefer matching distill's logger
approach for consistency, but do not let it change the tool's existing stdout
format for normal runs.

Also update the module docstring's usage block so `--force` is discoverable
there, the way distill's docstring warns "Run it while the executor is idle."

### Tests

Extend `tests/tools/test_run_backfill.py`. `heartbeat_path()` reads the
`JARVIS_EXECUTOR_HEARTBEAT` env var, so point it at a `tmp_path` file with
`monkeypatch.setenv` — **never touch the real `.executor-heartbeat`**.

A fake heartbeat is just the current epoch seconds as text:
`(tmp_path / "hb").write_text(str(time.time()))`. Staleness threshold is
`DEFAULT_MAX_AGE_SECONDS = 600.0`, so an old marker is
`str(time.time() - 700)`.

Cover:

- **Refusal:** fresh heartbeat, no `--force` ⇒ `main()` returns 2, and no
  backfill ran. Assert nothing ran by monkeypatching `open_local_mem0_memory`
  (or `run_backfill_over_intake`) to fail the test if called.
- **`--force` path:** fresh heartbeat + `--force` ⇒ proceeds normally.
- **Stale heartbeat:** ~700s old, no `--force` ⇒ proceeds normally.
- **No heartbeat file at all:** proceeds normally (fail-open).
- **`--dry-run` is never blocked** even with a fresh heartbeat.

`main()` needs `--user-id` for non-dry runs; supply one in tests. Reuse the
existing `FakeSink` / `_write` helpers in that file.

## Out of scope

- `executor/heartbeat.py` — read it, do not edit it. If you believe the guard
  itself needs changing, report that instead.
- `tools/distill_memory.py` — that is Lane B2's territory.
- `ingest/`, `memory/`, `requirements.txt`.
- Any commit.

New dependencies go in `docs/tasks/deps-backfill-liveness-guard.txt`. Do not
edit `requirements.txt`.

## Verify before reporting

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
```

Those flags are required — this machine's system `TEMP` is locked down and
pytest's default scratch dirs fail with `PermissionError` without them. Cite
the output verbatim.

## Report back

- The diff you made to `tools/run_backfill.py`.
- Which output mechanism you chose for the refusal and why.
- Full offline suite output.
