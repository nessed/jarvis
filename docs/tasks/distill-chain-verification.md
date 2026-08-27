# Lane C: verify what landed last session

Three checks on work committed in `d3094ad`. Two are tests, one is a docstring
correction.

## Owned files — edit nothing else

- `tests/executor/test_distill_handler.py`
- `tests/memory/test_distill.py`
- `executor/handlers/whatsapp.py` — **docstring only**, no behaviour change
- New test files if you need them

**You do not own `executor/handlers/distill.py`.** If a guard is missing there,
report the exact change needed and stop — do not fix it. See "If you find a
real gap" below.

## 1. Prove the distill chain terminates

`executor/handlers/distill.py` implements job kind `distill_memory`. Each job
processes one turn and enqueues its own successor with a `run_after` cooldown.
The concern is a queue that spins forever on a laptop left running.

Read the handler first and establish what it actually does. From a quick read
these paths exist, but **verify rather than trust this summary**:

- `distillation_enabled()` false ⇒ returns without re-enqueuing, so the chain
  drains out of the queue.
- Yield check finds other ready work ⇒ re-enqueues at `yield_cooldown`.
- Nothing to distill ⇒ re-enqueues at `idle_cooldown`.
- Successor is enqueued **last**, after every fallible step.

Two things to prove with tests:

**(a) The last turn does not spawn work forever at the busy rate.** Establish
what happens when the pending-turn queue empties. If the chain deliberately
keeps idling at a slow cooldown, that is a design choice, not a bug — but it
must be *stated* and *tested*, and the idle cooldown must actually be the slow
one. Assert the cooldown used on the empty path differs from the busy path.

**(b) A failing extraction does not spawn an infinite chain.** If extraction
raises, check whether a successor is enqueued at all. If the successor is
enqueued last and extraction raises first, no successor exists — the poller's
own retry/backoff and dead-letter handle the row instead. Prove that: a raising
extraction must not enqueue a successor, and must not enqueue two.

Also worth covering: `seed_distill_chain()` must not enqueue a second chain
when one is already open, or every executor restart adds a parallel chain.

Use the existing fakes in `tests/executor/test_distill_handler.py` — there is
already a `FakeQueue` reimplementing `claim_next_job`'s real
`run_after asc, created_at asc` ordering, and a fake clock. **No test may drive
real Ollama or the live Supabase queue.**

### If you find a real gap

Report it prominently and immediately in your final message. Write a test that
documents the gap — `xfail` with a clear reason is acceptable so the suite stays
green — and name the exact change needed in `executor/handlers/distill.py`. The
orchestrator will decide and apply. Do not edit that file yourself.

## 2. Fix the `build_whatsapp_webhook_handler` docstring

`memory_writes_enabled()` defaults to **on**. The docstring on
`build_whatsapp_webhook_handler` in `executor/handlers/whatsapp.py` still says
off. Correct it.

Read `memory_writes_enabled()` and confirm the actual default before writing
the correction — do not just invert the sentence. Docstring only; no behaviour
change, no signature change.

## 3. Consult archive: is the re-run concern closed?

`tools/consult.py` was broken on Windows until 27 August 2026 — prompts were
passed in argv to `claude.cmd`, and `cmd.exe` truncated them at the first
newline. Every consult before the fix delivered only its first line.

Determine whether `docs/consults/` contains **any verdict archived before that
fix**. If the only entries are the two from 27 August
(`2026-08-27-distill-scheduling-mechanism` and `2026-08-27-path-smoke-test`),
then no historical verdict is suspect and the concern is closed. Say so
explicitly either way.

This is a read-only check. Do not edit anything under `docs/consults/`.

## Out of scope

- Editing `executor/handlers/distill.py`, `memory/distill.py`, or
  `executor/poller.py`.
- `docs/state.md`, `docs/context.md` — the orchestrator's.
- `requirements.txt` — deps go in `docs/tasks/deps-distill-chain-verification.txt`.
- Committing.

## Verify before reporting

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
```

Required flags — the system `TEMP` here is locked down. Cite the output.

## Report back

- What the chain actually does on the empty path and on the failing-extraction
  path, with the tests that prove it.
- **Any real gap found, stated first and plainly**, with the exact fix needed.
- The corrected docstring, and the actual default you confirmed.
- Whether any pre-fix consult verdict exists.
- Full offline suite output.
