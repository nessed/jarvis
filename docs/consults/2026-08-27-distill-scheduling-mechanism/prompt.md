You are a second opinion on a decision inside an AI-agent-built project.
The agent asking has already gathered the evidence below and could not
resolve the question from it alone. Do not restate the evidence. Decide.

## Question

Pick the scheduling mechanism for tools/distill_memory.py, and argue against each candidate before you decide. I want the strongest case AGAINST each of the three, not a ranking. Then commit to one.

Candidates:
(a) A self-re-enqueuing low-priority executor job kind. A `distill_memory` job processes N turns, then enqueues its own successor, so live replies interleave between chunks instead of waiting out a whole batch.
(b) A scheduled window. Cleanly stop the executor, distill, restart it.
(c) A launcher-owned idle-window trigger. tools/start_jarvis.py notices an idle period and fires distillation itself.

Hard constraints, all real and all verified in this repo:

1. Ollama is a SINGLE SERIAL RESOURCE on this laptop, CPU-only. Any batch pass drives the exact same local model live WhatsApp replies need. This is not theoretical: a backfill starved eight inbound WhatsApp messages on 26 Aug 2026 (docs/history/whatsapp-reply-failures.md). That incident is why executor/heartbeat.py exists.

2. Mem0 fact extraction costs ~55s per turn. An embedding costs ~0.5s. That is ~250x, and it is why extraction was taken off the reply path entirely after failing on 100% of live messages.

3. The executor is a SINGLE SERIAL POLL LOOP. executor/poller.py claims and runs ONE job at a time, with a default 5s idle poll interval and an in-process thread timeout that does NOT kill the abandoned thread. A distill job holding Ollama for 55s blocks the loop for 55s. N turns per job means N x 55s of blockage.

4. THE QUEUE HAS NO PRIORITY COLUMN. This is the sharpest constraint on (a). claim_next_job in db/migrations/0002_job_retries.sql orders strictly `order by run_after asc, created_at asc` over rows where `status='queued' and run_after <= now()`. So a distill job that is OLDER than an incoming WhatsApp job gets claimed FIRST. "Low priority" is not expressible today. Adding a priority column is a schema migration against the LIVE Supabase database, which needs explicit user approval and is a hard stop for me - so treat it as a COST of (a), not a free move.
   Specifically answer: can `run_after` scheduling alone approximate deprioritisation without a migration? If a distill job's successor is enqueued with run_after = now() + delay, does that make it reliably lose the race to a WhatsApp job, or does it merely usually-work? Note the tie-break is created_at, and a WhatsApp job created at T has run_after = T (immediate), while a distill successor enqueued at T with a delay has run_after = T+delay. Is there any window where the distill job still wins - for example when the queue was idle and the distill successor became ready before the WhatsApp job was created, making the distill row strictly older by run_after? Is "usually works" acceptable given constraint 1's incident?

5. THE HEARTBEAT REFUSAL ALREADY EXISTS. executor/heartbeat.py makes distill_memory.py refuse to start while the executor is polling (timestamp file, 600s staleness window, --force to override). Candidate (a) runs distillation INSIDE the executor, which means the guard must be bypassed for that path. Does bypassing it dismantle the exact protection that stopped the 26 Aug failure from recurring? Or is in-executor serialisation a legitimate substitute for the guard, because the executor cannot run two jobs at once anyway and the guard only ever existed to stop a SECOND process competing for Ollama?

6. THE LAPTOP IS NOT ALWAYS ON. Nothing receives messages while it is off. Any wall-clock schedule (cron, Windows Task Scheduler, "3am nightly") fires into a machine that may be asleep. Missed windows must be HANDLED, not assumed away. Candidate (b) in particular: who stops and restarts the executor, and what happens if the machine is asleep at window time, or if the restart step fails and the executor stays down silently - i.e. the failure mode is "JARVIS is deaf and nobody notices"?

7. Candidate (c) touches tools/start_jarvis.py, which is owned by a DIFFERENT LANE. I cannot edit it; I can only specify the change for another agent to merge. That is a coordination cost, not a blocker. Also: start_jarvis.py is a foreground process supervisor that already brings up Ollama check, bus, tunnel, Meta re-point and executor in order and shuts them down together on Ctrl+C. Is adding idle-detection to a process supervisor a scope violation, and does the launcher even have the information to know the queue is idle? It does not poll the queue today.

8. Phase 4 eventually moves the bus off the laptop, which changes this calculus entirely. Which mechanism is CHEAPEST TO RETIRE when that happens?

9. Blueprint constraint: docs/blueprint.md specifies Mem0 self-hosted against local Ollama + sqlite-vec, with extraction local-only (NIM is geo-blocked from Pakistan, Gemini's free tier may train on prompts). The blueprint's runbook does describe scheduled CLI-agent jobs as an ongoing pattern. Architecture in the blueprint is a DECISION, not a claim - if your winner contradicts it, say so explicitly and I will stop and report rather than substitute.

Decide one. If your answer is a hybrid, name precisely which mechanism owns the TRIGGER and which owns the EXECUTION, because a hybrid that is really "all three" is not something I can implement. Also state, concretely, what the implementation must prove in tests to show a distill pass cannot starve a live reply - I must use fakes, no real Ollama and no live queue.

## Evidence

### docs/tasks/distill-scheduling.md

```
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

```
### tools/distill_memory.py

```
"""Fold stored conversation turns into Mem0 facts, offline.

The live reply path stores turns verbatim because Mem0's 8B fact extraction
costs 20-130s on this hardware and failed on 100% of live messages. This is
where that extraction actually happens: a batch pass, run when nothing is
waiting on a reply, over turns that have not been distilled yet.

Run it while the executor is idle. Ollama is a single serial resource — this
competes with live replies for exactly the same model, which is what starved
eight inbound messages on 26 August.

    .venv\\Scripts\\python.exe tools/distill_memory.py [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from executor.heartbeat import refuse_if_executor_is_live
from memory.conversation import open_conversation_memory
from memory.runtime import open_local_mem0_memory

logger = logging.getLogger("distill")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None, help="stop after N turns")
    parser.add_argument("--dry-run", action="store_true", help="report what would run, change nothing")
    parser.add_argument("--database", default=None, help="memory database path")
    parser.add_argument("--force", action="store_true", help="run even while the executor is polling")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv()

    if not args.force and not args.dry_run:
        refusal = refuse_if_executor_is_live("Distilling")
        if refusal:
            logger.error(refusal)
            return 2

    conversation = open_conversation_memory(args.database)
    try:
        pending = conversation.undistilled_turns(limit=args.limit)
        if not pending:
            logger.info("nothing to distill")
            return 0

        logger.info("%d turn(s) to distill", len(pending))
        if args.dry_run:
            for fact in pending:
                logger.info("  would distill %s  %s", fact.created_at.date(), _preview(fact.text))
            return 0

        mem0 = open_local_mem0_memory(args.database)
        distilled = failed = 0
        try:
            for fact in pending:
                user_id = str(fact.metadata.get("user_id") or "jarvis")
                role = str(fact.metadata.get("role") or "user")
                started = time.monotonic()
                try:
                    mem0.remember(f"{role.capitalize()}: {fact.text}", user_id=user_id)
                except Exception as exc:
                    failed += 1
                    logger.warning("  failed %s (%s)", _preview(fact.text), type(exc).__name__)
                    continue
                # Mark only after extraction succeeded, so a crash or a timeout
                # leaves the turn eligible for the next run instead of silently
                # dropping it.
                conversation.mark_distilled(fact)
                distilled += 1
                logger.info("  distilled in %.1fs  %s", time.monotonic() - started, _preview(fact.text))
        finally:
            mem0.close()

        logger.info("done: %d distilled, %d failed, %d remaining", distilled, failed, len(pending) - distilled)
        return 0 if distilled or not failed else 1
    finally:
        conversation.close()


def _preview(text: str, width: int = 60) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())

```
### executor/heartbeat.py

```
"""A liveness marker so batch jobs can tell the executor is running.

Ollama is a single serial resource. A batch pass over the corpus drives the
same local model every reply depends on, so running one while the executor is
polling starves live messages for as long as it lasts — that is exactly what
happened on 26 August 2026, when a backfill left eight inbound messages
sitting unclaimed (``docs/history/whatsapp-reply-failures.md``).

The executor touches a file each poll; batch tools check its age and refuse to
start. A timestamp rather than a PID lock is deliberate: if the executor is
killed the marker simply goes stale on its own, so a crash can never leave a
lock behind that blocks every future batch run.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

DEFAULT_HEARTBEAT_PATH = Path(".executor-heartbeat")

# Generous against the executor's default 5s poll interval: a slow job holds the
# loop for its whole duration without touching the file, and a handler may run
# for minutes. Only a genuinely stopped executor should read as stale.
DEFAULT_MAX_AGE_SECONDS = 600.0


def heartbeat_path(environ: dict[str, str] | None = None) -> Path:
    settings = os.environ if environ is None else environ
    return Path(settings.get("JARVIS_EXECUTOR_HEARTBEAT", str(DEFAULT_HEARTBEAT_PATH)))


def touch(path: Path | None = None) -> None:
    """Record that the executor is alive right now. Never raises."""
    target = path or heartbeat_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        # A missing heartbeat only costs a batch tool its guard; it must never
        # take down the poll loop.
        pass


def seconds_since_heartbeat(path: Path | None = None) -> float | None:
    """Age of the marker in seconds, or ``None`` if there isn't a readable one."""
    target = path or heartbeat_path()
    try:
        recorded = float(target.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    age = time.time() - recorded
    return age if age >= 0 else 0.0


def executor_is_live(
    path: Path | None = None, *, max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS
) -> bool:
    """Whether an executor has reported in recently enough to still be polling."""
    age = seconds_since_heartbeat(path)
    return age is not None and age <= max_age_seconds


def refuse_if_executor_is_live(
    tool_name: str, *, path: Path | None = None, max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS
) -> str | None:
    """Return an explanatory message if ``tool_name`` should not start now."""
    age = seconds_since_heartbeat(path)
    if age is None or age > max_age_seconds:
        return None
    return (
        f"The executor is running (last poll {age:.0f}s ago). {tool_name} drives the same "
        "local Ollama that live replies need, and running both starves incoming messages.\n"
        "Stop the executor first, or pass --force if you accept slow replies while this runs."
    )

```
### executor/poller.py

```
"""Pull-based laptop executor for Phase 0 durable jobs.

The poller deliberately performs no LLM or WhatsApp work itself. Callers
inject a deterministic mapping of job kinds to local handlers, so later phases
can add local work without moving it into the webhook.
"""

from __future__ import annotations

import argparse
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

from db.jobs import (
    Job,
    JobRepository,
    checkpoint,
    claim_next,
    complete,
    retry_or_dead_letter,
    set_timeout,
)
from executor.flp.sort import build_flp_sort_handler
from executor.handlers.whatsapp import build_whatsapp_webhook_handler
from executor.heartbeat import touch as touch_heartbeat
from router import RoutedResult, route


JobHandler = Callable[[Job], None]
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_HANDLER_TIMEOUT_SECONDS = 300.0
BACKOFF_BASE_SECONDS = 5.0
BACKOFF_CAP_SECONDS = 300.0
logger = logging.getLogger(__name__)


class UnknownJobKindError(Exception):
    """Raised when a claimed job has no explicitly registered handler."""


class _HandlerTimeoutError(Exception):
    """Raised in-process when a handler exceeds its registered timeout."""


@dataclass(frozen=True)
class HandlerRegistration:
    """A job handler paired with the timeout that applies to it."""

    handler: JobHandler
    timeout_seconds: float = DEFAULT_HANDLER_TIMEOUT_SECONDS


JobHandlers = Mapping[str, "HandlerRegistration | JobHandler"]

# The handler registry the executor consults at startup, by job kind.
# ``memory_extract`` has no registered handler yet — nothing enqueues that
# kind independently of the whatsapp_webhook flow below, which does its own
# recall/remember inline rather than as a separate job.
DEFAULT_HANDLERS: dict[str, HandlerRegistration] = {
    "whatsapp_webhook": HandlerRegistration(build_whatsapp_webhook_handler()),
    "flp_sort": HandlerRegistration(build_flp_sort_handler()),
}


def backoff_seconds(attempts: int) -> float:
    """Exponential backoff with a cap: base 5s, cap 300s (5 min)."""
    return min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** max(0, attempts - 1)))


def poll_once(
    *,
    repository: JobRepository | None = None,
    handler: JobHandler | None = None,
    handlers: JobHandlers | None = None,
) -> Job | None:
    """Atomically claim and finish one ready job, if any.

    ``handler`` remains an explicit per-call override for diagnostics and
    compatibility. Otherwise ``handlers`` supplies the registered handler for
    the claimed job's kind, either as a raw callable (wrapped with the
    default timeout) or an explicit ``HandlerRegistration`` for a per-kind
    timeout. An unregistered kind is a clear, logged, non-fatal rejection —
    it neither crashes the poller nor is a silent failure — and is routed
    through the same retry/backoff/dead-letter path as any other failure, so
    a kind registered in a later deploy can still succeed on retry. A
    handler that exceeds its timeout is likewise retried, not lost. Every
    stored diagnostic uses only an exception type, so payloads or provider
    details cannot leak into the durable queue.
    """
    job = claim_next(repository=repository)
    if job is None:
        return None

    try:
        registration = _resolve_registration(job, handler=handler, handlers=handlers)
    except UnknownJobKindError:
        logger.warning("rejected job with unregistered kind (job=%s)", job.id)
        return retry_or_dead_letter(
            job.id,
            "no handler registered for job kind",
            backoff_seconds(job.attempts),
            repository=repository,
        )

    if round(registration.timeout_seconds) != job.timeout_seconds:
        set_timeout(job.id, round(registration.timeout_seconds), repository=repository)

    checkpoint(
        job.id,
        {**job.checkpoint, "phase": "executor_started"},
        repository=repository,
    )
    try:
        _run_with_timeout(registration, job)
    except _HandlerTimeoutError:
        logger.warning("job handler exceeded its timeout (job=%s)", job.id)
        return retry_or_dead_letter(
            job.id,
            "executor handler timed out (HandlerTimeoutError)",
            backoff_seconds(job.attempts),
            repository=repository,
        )
    except Exception as exc:
        return retry_or_dead_letter(
            job.id,
            f"executor handler failed ({type(exc).__name__})",
            backoff_seconds(job.attempts),
            repository=repository,
        )
    return complete(job.id, repository=repository)


def _resolve_registration(
    job: Job, *, handler: JobHandler | None, handlers: JobHandlers | None
) -> HandlerRegistration:
    """Return the explicit override or registered handler for a job kind."""
    if handler is not None:
        return HandlerRegistration(handler, DEFAULT_HANDLER_TIMEOUT_SECONDS)
    if handlers is not None:
        entry = handlers.get(job.kind)
        if entry is not None:
            if isinstance(entry, HandlerRegistration):
                return entry
            return HandlerRegistration(entry, DEFAULT_HANDLER_TIMEOUT_SECONDS)
    raise UnknownJobKindError


def _run_with_timeout(registration: HandlerRegistration, job: Job) -> None:
    """Run the handler on a daemon thread bounded by its registered timeout.

    A plain ``threading.Thread`` is used rather than
    ``concurrent.futures.ThreadPoolExecutor`` because pool workers are
    non-daemon by default and register an atexit hook that blocks process
    exit until a hung handler returns — exactly what a timeout must not do.
    On timeout the poller moves on immediately; the abandoned thread is not
    killed (Python cannot preempt a running thread) and is a documented
    limitation of in-process timeout enforcement. Durable recovery from a
    handler — or whole executor — that never returns is the database-side
    stale-lease reclaim in ``claim_next_job``, not this function.
    """
    outcome: dict[str, BaseException] = {}
    done = threading.Event()

    def _run() -> None:
        try:
            registration.handler(job)
        except BaseException as exc:  # re-raised on the poller thread below
            outcome["error"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    if not done.wait(timeout=registration.timeout_seconds):
        raise _HandlerTimeoutError(f"handler exceeded {registration.timeout_seconds}s")
    if "error" in outcome:
        raise outcome["error"]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the local executor until interrupted, or once for diagnostics."""
    load_dotenv()
    parser = argparse.ArgumentParser(description="Poll the JARVIS local job queue")
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.environ.get("JARVIS_POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS)),
        help="seconds between polls when idle (default: 5)",
    )
    parser.add_argument("--once", action="store_true", help="claim at most one job and exit")
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")

    try:
        while True:
            # Marks the executor live so batch tools (distill, backfill) can
            # refuse to compete for the single local Ollama. See
            # executor/heartbeat.py.
            touch_heartbeat()
            try:
                poll_once(handlers=DEFAULT_HANDLERS)
            except Exception as exc:
                if args.once:
                    raise
                logger.warning("executor poll failed (%s)", type(exc).__name__)
            if args.once:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


async def request_completion(
    task_profile: str, messages: Sequence[Mapping[str, Any]], *, urgent: bool = False
) -> RoutedResult:
    """Give executor jobs the provider router's single async entry point."""
    return await route(task_profile, messages, urgent=urgent)


if __name__ == "__main__":  # pragma: no cover - exercised as a module entry point
    raise SystemExit(main())

```
### db/migrations/0002_job_retries.sql

```
-- Queue durability: attempts/backoff/timeout/dead-letter. Additive only —
-- no existing column, row, or RPC signature is dropped or renamed. Apply
-- through the same path used for 0001_jobs.sql.

alter table public.jobs
    add column if not exists attempts int not null default 0,
    add column if not exists max_attempts int not null default 5,
    add column if not exists timeout_seconds int not null default 300;

-- Existing rows backfill to attempts=0, max_attempts=5, timeout_seconds=300
-- via the column defaults above.

alter table public.jobs drop constraint if exists jobs_status_check;
alter table public.jobs add constraint jobs_status_check
    check (status in ('queued', 'running', 'done', 'failed', 'dead_letter'));

-- Atomic claim: unchanged single-statement `for update skip locked` shape,
-- widened to also reclaim a `running` row whose lease
-- (updated_at + timeout_seconds) has expired. A row that has NOT exceeded
-- its own timeout can still only ever be claimed by one executor at a time
-- — the reclaim branch is deliberately the retry mechanism for a dead
-- executor, the same trade-off every lease-based queue makes.
create or replace function public.claim_next_job(p_kind_filter text default null)
returns setof public.jobs
language plpgsql
set search_path = ''
as $$
declare
    claimed public.jobs;
begin
    -- A stale `running` row that has already exhausted its attempts must not
    -- be reclaimed forever by a crash-looping executor; terminate it instead.
    update public.jobs
    set status = 'dead_letter',
        checkpoint = coalesce(checkpoint, '{}'::jsonb)
            || jsonb_build_object(
                'error', jsonb_build_object('message', 'exhausted after stale timeout')
            )
    where status = 'running'
      and attempts >= max_attempts
      and updated_at + make_interval(secs => timeout_seconds) < now();

    with next_job as (
        select id
        from public.jobs
        where (
                (status = 'queued' and run_after <= now())
                or (status = 'running'
                    and updated_at + make_interval(secs => timeout_seconds) < now())
              )
          and (p_kind_filter is null or kind = p_kind_filter)
        order by run_after asc, created_at asc
        for update skip locked
        limit 1
    )
    update public.jobs as job
    set status = 'running',
        attempts = job.attempts + 1
    from next_job
    where job.id = next_job.id
    returning job.* into claimed;

    if found then
        return next claimed;
    end if;
end;
$$;

-- Backoff delay is computed by the caller (unit-testable in Python); this
-- RPC just applies attempts-vs-max_attempts atomically alongside it.
create or replace function public.retry_or_dead_letter_job(
    p_job_id uuid, p_error text, p_delay_seconds int default 0
)
returns public.jobs
language plpgsql
set search_path = ''
as $$
declare
    result public.jobs;
begin
    update public.jobs
    set status = case when attempts >= max_attempts then 'dead_letter' else 'queued' end,
        run_after = case
            when attempts >= max_attempts then run_after
            else now() + make_interval(secs => greatest(0, p_delay_seconds))
        end,
        checkpoint = coalesce(checkpoint, '{}'::jsonb)
            || jsonb_build_object(
                'error', jsonb_build_object('message', p_error),
                'attempts', attempts
            )
    where id = p_job_id
    returning * into result;

    return result;
end;
$$;

create or replace function public.set_job_timeout(p_job_id uuid, p_timeout_seconds int)
returns public.jobs
language sql
set search_path = ''
as $$
    update public.jobs
    set timeout_seconds = greatest(1, p_timeout_seconds)
    where id = p_job_id
    returning *;
$$;

revoke execute on function public.retry_or_dead_letter_job(uuid, text, int)
    from public, anon, authenticated;
revoke execute on function public.set_job_timeout(uuid, int)
    from public, anon, authenticated;
grant execute on function public.retry_or_dead_letter_job(uuid, text, int) to service_role;
grant execute on function public.set_job_timeout(uuid, int) to service_role;

```

## Response format

Answer as strict JSON and nothing else. No prose before or after, no code
fence. Exactly these keys:

{
  "verdict": "the decision or answer, one or two sentences, actionable",
  "reasoning": "why, citing the specific evidence above that drove it",
  "confidence": "high | medium | low",
  "what_would_change_this": "the concrete observation that would flip this verdict"
}

Set confidence to low rather than guessing. If the evidence provided is not
enough to decide, say exactly what is missing in what_would_change_this — that
is a useful answer, an invented one is not.