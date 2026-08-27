# Lane B2: a scheduling mechanism for `tools/distill_memory.py`

## Why this lane exists

`docs/state.md` open blocker 1: **batch distillation is not scheduled.**

Memory has two paths by design. Live conversation turns embed-and-store inline
(~0.5s, fast enough for the reply path). Mem0 fact extraction costs **~55s per
turn** on this CPU-only machine — roughly 250x an embedding — so it was taken
off the reply path entirely after it failed on 100% of live messages.
`tools/distill_memory.py` is where that extraction now happens, as an offline
batch pass over turns not yet distilled.

**Nothing runs it.** Distilled facts lag until the user invokes it by hand, so
long-term memory quietly does not accumulate. That is the gap this lane closes.

## Step 1 — this is a Class B stop. Consult first, before writing any code.

`agents.md`: a judgment with one defensible answer given evidence you already
hold is resolved with `tools/consult.py`, not by asking the user and not by
picking your favourite. **Run the consult before implementing.**

```
.venv\Scripts\python.exe tools/consult.py "<your question>" --file docs/tasks/distill-scheduling.md --file tools/distill_memory.py --file executor/heartbeat.py --file executor/poller.py
```

Frame it **adversarially**: ask for the strongest case against each candidate,
not for a ranking. Name all three candidates explicitly.

### Candidates to argue

**(a) A self-re-enqueuing low-priority executor job kind.** A `distill_memory`
job kind processes N turns per job, then enqueues its own successor, so live
replies interleave between chunks instead of waiting out a whole batch.

**(b) A scheduled window.** Cleanly stop the executor, distill, restart it.

**(c) A launcher-owned idle-window trigger.** `tools/start_jarvis.py` notices
an idle period and fires distillation itself.

### Real constraints the consult must be given — do not omit any

- **Ollama is a single serial resource.** Any batch pass drives the same local
  model live replies need. This is not theoretical: a backfill starved eight
  inbound WhatsApp messages on 26 August 2026
  (`docs/history/whatsapp-reply-failures.md`).
- **~55s per turn**, CPU-only, versus ~0.5s for an embedding.
- **The executor is a single serial poll loop.** It claims and runs one job at
  a time. A distill job holding Ollama for 55s blocks the loop for 55s — a
  WhatsApp message arriving in that window waits. N turns per job means N×55s.
- **The queue has no priority column.** `claim_next_job` in
  `db/migrations/0002_job_retries.sql` orders strictly by
  `order by run_after asc, created_at asc`. This is the sharpest constraint on
  candidate (a): a distill job that is *older* than an incoming WhatsApp
  message gets claimed **first**. "Low priority" is not expressible today.
  Adding a priority column is a **schema migration against the live database**
  — that needs explicit user approval and is a Class C stop, so treat it as a
  cost of (a), not a free move. Ask the consult whether `run_after` scheduling
  alone can approximate deprioritisation without a migration, and whether that
  approximation is sound or merely usually-works.
- **The heartbeat refusal already exists.** `executor/heartbeat.py` makes
  distill refuse while the executor polls. Candidate (a) runs distillation
  *inside* the executor, which means the guard would have to be bypassed for
  that path — ask whether that is safe or whether it dismantles the protection
  that stopped the 26 August failure from recurring.
- **The laptop is not always on.** Blocker 4: nothing receives messages while
  it is off. Any wall-clock schedule (cron, Task Scheduler, "3am nightly")
  fires into a machine that may be asleep, so missed windows must be handled,
  not assumed away.
- **Blueprint memory design** — read the memory sections of
  `docs/blueprint.md` and honour them. Architecture and component choices in
  the blueprint are **decisions, not claims**. If the winning mechanism appears
  to contradict one, stop and report; do not substitute.
- Phase 4 eventually moves the bus off the laptop, which would change this
  calculus. Ask whether the chosen mechanism is cheap to retire.

### Acting on the verdict

- Act on what comes back. Record it — `tools/consult.py` saves the exchange
  under `docs/consults/`; **cite that path** in your report and reference it in
  the implementation's docstring.
- If the verdict is `confidence: low` **with a named missing observation**, go
  measure that observation — obtaining it is a Class A step — and consult
  again. **Do not surface this to the user.** Only a consult that refuses to
  resolve after a second pass gets escalated.

## Step 2 — implement the winner, with tests

Follow the verdict, not your prior preference.

### Ownership

Likely-owned, depending on which candidate wins:

- `tools/distill_memory.py`
- `executor/handlers/` — a new handler module, if (a) wins
- `executor/poller.py` — `DEFAULT_HANDLERS` registration, if (a) wins
- Tests for whatever you add

**Files owned by other lanes — do not edit, whatever the verdict says:**

- `tools/start_jarvis.py` and `tests/tools/test_start_jarvis.py` — **Lane A**.
  If candidate **(c)** wins, you may not touch the launcher. Report the exact
  change needed, in full, and stop there; the orchestrator merges it.
- `tools/run_backfill.py` and `tests/tools/test_run_backfill.py` — **Lane B1**.
- `executor/heartbeat.py` — read it; if it needs changing, report that instead.
- `docs/state.md`, `docs/context.md` — the orchestrator's.
- `requirements.txt` — deps go in `docs/tasks/deps-distill-scheduling.txt`.

### Interface rule

If you change a shared interface — a `Protocol`, a public signature, the
`JobHandler`/`HandlerRegistration` shape, or the queue schema — **name every
implementer in your report, including test doubles in files you do not own.**
Disjoint ownership means you cannot edit them; it does not mean you may ignore
them.

### Testing

No test may drive real Ollama or the live Supabase queue. Use fakes, as
`tests/executor/` already does. Cover the mechanism's real risk: that a distill
pass cannot starve a live reply. If (a) wins, that means proving the
re-enqueue chunking actually yields between chunks, and proving what happens
when a WhatsApp job is enqueued mid-chain.

## Verify before reporting

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
```

Required flags — the system `TEMP` here is locked down and pytest fails with
`PermissionError` without them. Cite the output verbatim.

## Out of scope

- Running any migration against the live database. Class C.
- Actually running a distill pass against real memory data.
- Any commit.

## Report back

- The consult's verdict, its confidence, and the saved `docs/consults/` path.
- Which candidate won and the strongest argument *against* it that you accepted
  anyway.
- If (c) won: the exact `tools/start_jarvis.py` change, written out for the
  orchestrator.
- Any shared interface changed, and every implementer of it.
- Full offline suite output.
