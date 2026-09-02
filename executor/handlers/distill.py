"""The ``distill_memory`` job kind: a self-re-enqueuing, yielding distill chain.

Why this exists
---------------
Mem0 fact extraction costs ~55s per turn on this CPU-only laptop against ~0.5s
for an embedding, so it was taken off the reply path entirely and moved into
``tools/distill_memory.py``. Nothing ran that tool, so distilled facts lagged
until the user invoked it by hand (``docs/state.md`` open blocker 1). This is
the mechanism that runs it.

Three mechanisms were argued adversarially before any of this was written; the
exchange is saved at ``docs/consults/2026-08-27-distill-scheduling-mechanism/``
(verdict: candidate (a), confidence high). The two rejected alternatives were a
scheduled stop-the-executor window, whose restart step fails *silently* and
turns a memory-lag problem into "JARVIS is deaf and nobody notices", and a
launcher-owned idle trigger, which predicts idleness with no way to revoke the
prediction when a message lands one second later.

The constraint that shapes everything here
------------------------------------------
**The queue has no priority column.** ``claim_next_job`` orders strictly by
``run_after asc, created_at asc``, and adding a column is a migration against
the live database — a decision that is not this code's to make. So a distill
row whose ``run_after`` has already ripened is claimed *before* a WhatsApp
message that arrived afterwards. That is not an edge case; it is every idle
gap. ``run_after`` is therefore used here as a **duty-cycle throttle only, never
as a priority**, and priority comes from the yield check at the top of the
handler: before doing any work, look for ready queued work of any other kind,
and if there is some, do zero extraction and re-enqueue. The ordering inversion
still happens, but its cost drops from 55s to one query plus one poll interval.

Why this does not dismantle the heartbeat guard
-----------------------------------------------
``executor/heartbeat.py`` stops a *second process* from competing for the one
local Ollama, which is what starved eight inbound messages on 26 August 2026.
It is untouched, and ``tools/distill_memory.py`` still honours it. Running
inside the executor is not a bypass of that guard: the executor is a single
serial poll loop that cannot run two jobs at once, so there is exactly one
Ollama consumer by construction.

The abandoned-thread hazard, and why it is closed
-------------------------------------------------
``executor/poller.py``'s timeout does not kill the handler's thread — it
abandons it. An abandoned distill thread would still hold Ollama while the
poller claimed the next job, which is the 26 August failure recreated inside
one process. That is closed by ordering the two timeouts: the Ollama client
already has its own extraction timeout (``OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS``,
default 90s, applied in ``memory/mem0_wrapper.py``), and this handler registers
a longer one, so a wedged model *raises* inside the thread and the thread
exits, well before the poller would ever abandon it. ``assert_timeouts_ordered``
below is that invariant. It is checked twice, and both are load-bearing: once at
executor startup (``executor/poller.py::main``, after ``load_dotenv``) so a
misconfigured machine refuses to start, and once per row at the top of the
handler so a ``.env`` edited under a long-lived executor cannot silently
re-open the hazard. Until 27 August 2026 it had *no* production caller at all.

Why one chain never becomes two
-------------------------------
The successor is enqueued last, so a raised extraction leaves only the claimed
row. That is necessary but not sufficient: the poller re-queues the row it
claimed when it gives up waiting, and the abandoned thread then completes its
own enqueue beside it. Forks never merge, and each one permanently doubles the
duty cycle against the one serial Ollama. So the write carries a veto
(``may_write``) evaluated at the write site itself, and it refuses when this
pass no longer owns its row or when a sibling row is already open. See
``_repository_fork_guard``.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from db.jobs import Job, JobRepository, enqueue
from memory.conversation import open_conversation_memory
from memory.distill import DistillReport, distill_turns, preview
from memory.runtime import open_local_mem0_memory

logger = logging.getLogger(__name__)

DISTILL_JOB_KIND = "distill_memory"

# One turn per job. The chunk size *is* the worst-case delay a live reply can
# inherit, because the poll loop is serial and one extraction is ~55s. Two
# turns per job would double that for no gain: the chain re-enqueues itself
# immediately anyway, so throughput is set by the cooldown, not the chunk.
DEFAULT_TURNS_PER_JOB = 1

# Backlog remains: come back after one poll interval's worth of breathing room.
DEFAULT_BUSY_COOLDOWN_SECONDS = 15.0
# Nothing to distill: tick slowly. The chain still re-enqueues rather than
# ending, so it never needs re-seeding and a laptop that sleeps for a day just
# finds one ripe row waiting on the next boot.
DEFAULT_IDLE_COOLDOWN_SECONDS = 900.0
# Yielded to live work: wait long enough that the reply, and any follow-up in
# the same exchange, is claimed first.
DEFAULT_YIELD_COOLDOWN_SECONDS = 60.0

# Must stay above the Ollama client's own extraction timeout; see the module
# docstring's last section and ``assert_timeouts_ordered``.
HANDLER_TIMEOUT_SECONDS = 240.0
_EXTRACTION_TIMEOUT_ENV = "OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS"
_DEFAULT_EXTRACTION_TIMEOUT_SECONDS = 90.0

# A distill row never fans out, so a stuck one must not be retried for long.
DISTILL_MAX_ATTEMPTS = 3

# How long ``seed_distill_chain`` waits before seeding *again* in one process.
#
# The seed is idempotent and the executor calls it every poll, which is right
# while the chain is alive: the check is one cheap query and it returns early.
# It is wrong the moment the chain starts dying. On 29-30 August 2026 Ollama
# stopped at 00:35 local, every distill row then failed in seconds on the
# dimension probe, and each one dead-lettered after three attempts and was
# re-seeded immediately. That loop ran unattended for 78 minutes and produced
# 84 dead-lettered rows — one outage, amplified ~65x per hour, against a
# hosted database. None of them carried work: the payload is
# ``{"reason": ...}`` and the actual backlog lives in the local conversation
# store, so the whole 78 minutes bought exactly nothing.
#
# Deliberately equal to the idle cooldown: a chain that died costs no more
# than a chain that had nothing to do. Recovery is bounded by the same 15
# minutes either way, and a fresh process still seeds immediately, so a
# restart is never delayed.
SEED_RESEED_COOLDOWN_SECONDS = DEFAULT_IDLE_COOLDOWN_SECONDS

# Module-level and therefore per-process, which is exactly the scope wanted:
# one long-lived executor, and a restart that begins with a clean slate.
_last_seeded_monotonic: float | None = None


class ChainQueue(Protocol):
    """The narrow queue slice this chain needs, beyond ``JobRepository``.

    Deliberately separate from ``db.jobs.JobRepository`` so that Protocol stays
    exactly as wide as it is and every existing test double keeps satisfying
    it. See the comment above these methods in ``db/jobs.py``.
    """

    def has_ready_job_excluding_kind(self, kind: str) -> bool: ...

    def has_open_job_of_kind(self, kind: str) -> bool: ...

    def has_open_job_of_kind_excluding(self, kind: str, job_id: str) -> bool: ...

    def status_of_job(self, job_id: str) -> str | None: ...


LiveWorkCheck = Callable[[], bool]
# ``may_write`` is evaluated at the write site, not before it. The guard has to
# be the last thing that happens before the row lands: a check performed
# earlier is separated from the write by however long the queue takes to
# answer, and that gap is exactly when the poller's timeout re-queues the row
# out from under an abandoned thread.
SuccessorEnqueue = Callable[..., None]
# Given the row being handled and the status it had when this pass started,
# must this pass refrain from enqueuing a successor? True in either forking
# case; see ``_repository_fork_guard``.
ForkGuard = Callable[[str, "str | None"], bool]


def distillation_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Whether the chain may run. Default **on**; ``JARVIS_DISTILL=0`` stops it.

    An off switch for the one background mechanism that shares Ollama with the
    reply path. Turning it off makes the handler a no-op that does not
    re-enqueue, so the chain drains itself out of the queue rather than
    accumulating rows nobody will run.
    """
    settings = os.environ if environ is None else environ
    return str(settings.get("JARVIS_DISTILL", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def extraction_timeout_seconds(environ: Mapping[str, str] | None = None) -> float:
    """The Ollama client-side extraction timeout, as ``memory.mem0_wrapper`` reads it."""
    settings = os.environ if environ is None else environ
    raw = str(settings.get(_EXTRACTION_TIMEOUT_ENV, "")).strip()
    if not raw:
        return _DEFAULT_EXTRACTION_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_EXTRACTION_TIMEOUT_SECONDS
    return value if value > 0 else _DEFAULT_EXTRACTION_TIMEOUT_SECONDS


def assert_timeouts_ordered(
    *,
    handler_timeout_seconds: float = HANDLER_TIMEOUT_SECONDS,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Fail loudly if the poller would abandon a thread still holding Ollama.

    The poller cannot kill a handler thread, only stop waiting for it. So the
    Ollama client's timeout must fire strictly first, letting the extraction
    raise and the thread exit on its own.
    """
    extraction = extraction_timeout_seconds(environ)
    if extraction >= handler_timeout_seconds:
        raise ValueError(
            f"{_EXTRACTION_TIMEOUT_ENV}={extraction:g}s must be below the distill handler's "
            f"{handler_timeout_seconds:g}s timeout, or a wedged extraction leaves an abandoned "
            "thread holding the single local Ollama while the poller claims the next job."
        )


def build_distill_memory_handler(
    *,
    open_memory: Callable[..., Any] = open_conversation_memory,
    open_extractor: Callable[..., Any] = open_local_mem0_memory,
    turns_per_job: int = DEFAULT_TURNS_PER_JOB,
    has_live_work: LiveWorkCheck | None = None,
    enqueue_successor: SuccessorEnqueue | None = None,
    fork_guard: ForkGuard | None = None,
    repository: JobRepository | None = None,
    busy_cooldown_seconds: float = DEFAULT_BUSY_COOLDOWN_SECONDS,
    idle_cooldown_seconds: float = DEFAULT_IDLE_COOLDOWN_SECONDS,
    yield_cooldown_seconds: float = DEFAULT_YIELD_COOLDOWN_SECONDS,
    enabled: bool | None = None,
) -> Callable[[Job], None]:
    """Return a ``JobHandler`` that distills one chunk and schedules the next.

    Every dependency is injectable so the chain's safety properties can be
    proven against fakes, with no Ollama and no live queue.

    Ordering inside the handler is load-bearing:

    1. The yield check runs **first**, before any database or model is opened.
    2. The successor is enqueued **last**, after every fallible step. If
       extraction raises, no successor exists and the poller re-queues the row
       that was claimed — so there is still exactly one distill row, never two.
       A chain that forked would be two competitors for one serial Ollama.
    """
    if turns_per_job < 1:
        raise ValueError("turns_per_job must be at least 1")

    live_work = has_live_work or _repository_live_work_check(repository)
    raw_schedule = enqueue_successor or _repository_successor_enqueue(repository)
    must_not_enqueue = fork_guard or _repository_fork_guard(repository)

    def handle(job: Job) -> None:
        # Checked per row as well as once at executor startup
        # (``executor/poller.py::main``). Startup alone is not enough: ``.env``
        # can change under a long-lived executor, and the failure this guards
        # is silent — an extraction timeout above the handler's own timeout
        # leaves an abandoned thread holding the one serial Ollama while the
        # poller claims the next job. Raising here fails the row loudly into
        # retry_health instead of letting it run misconfigured.
        assert_timeouts_ordered(handler_timeout_seconds=HANDLER_TIMEOUT_SECONDS)

        entry_status = _status_at_entry(job.id, repository)

        def schedule(delay_seconds: float, reason: str) -> None:
            """Hand the write a veto it evaluates at the last possible moment.

            Enqueue-side and self-excluding, both deliberately. A symmetric
            "another row exists, so I stop" check would let two briefly
            coexisting rows each defer to the other and end the chain for good.
            """

            def may_write() -> bool:
                try:
                    return not must_not_enqueue(job.id, entry_status)
                except Exception as exc:  # noqa: BLE001 - liveness beats certainty
                    logger.warning(
                        "could not run the %s fork guard (%s); enqueuing anyway",
                        DISTILL_JOB_KIND,
                        type(exc).__name__,
                    )
                    return True

            raw_schedule(delay_seconds, reason, may_write=may_write)

        if not (distillation_enabled() if enabled is None else enabled):
            # No re-enqueue: let the chain drain out of the queue.
            logger.info("distill chain disabled (JARVIS_DISTILL); ending chain")
            return

        if live_work():
            # Zero extraction. This is the whole anti-starvation mechanism:
            # the queue's ordering may hand us the loop first, but we give it
            # straight back instead of holding Ollama for ~55s.
            logger.info("yielding to queued live work; distilling nothing this pass")
            schedule(yield_cooldown_seconds, "yield")
            return

        report = _distill_one_chunk(
            open_memory=open_memory,
            open_extractor=open_extractor,
            turns_per_job=turns_per_job,
        )

        if not report.did_work:
            logger.info("nothing to distill; idling %.0fs", idle_cooldown_seconds)
            schedule(idle_cooldown_seconds, "idle")
            return

        logger.info(
            "distilled %d turn(s), %d failed, backlog remaining: %s",
            report.distilled,
            report.failed,
            report.more_pending,
        )
        schedule(
            busy_cooldown_seconds if report.more_pending else idle_cooldown_seconds,
            "backlog" if report.more_pending else "idle",
        )

    return handle


def _distill_one_chunk(
    *,
    open_memory: Callable[..., Any],
    open_extractor: Callable[..., Any],
    turns_per_job: int,
) -> DistillReport:
    """Distill at most ``turns_per_job`` turns, opening as little as possible.

    The emptiness pre-check is a plain SQLite read. It exists so an idle tick
    never loads the 8B extraction model just to discover there is nothing to
    do — the common case once the backlog is cleared.
    """
    conversation = open_memory()
    try:
        if not conversation.undistilled_turns(limit=1):
            return DistillReport()
        extractor = open_extractor()
        try:
            return distill_turns(
                conversation,
                extractor,
                limit=turns_per_job,
                on_distilled=lambda fact, seconds: logger.info(
                    "  distilled in %.1fs  %s", seconds, preview(fact.text)
                ),
                # on_error is left as None on purpose: a failure propagates to
                # the poller's retry/backoff/dead-letter path, where it is
                # visible in /status's retry_health, instead of being swallowed
                # by a background job nobody is reading the logs of.
            )
        finally:
            _close_quietly(extractor)
    finally:
        _close_quietly(conversation)


def seed_distill_chain(
    *,
    repository: JobRepository | None = None,
    delay_seconds: float = DEFAULT_BUSY_COOLDOWN_SECONDS,
    enabled: bool | None = None,
    reseed_cooldown_seconds: float = SEED_RESEED_COOLDOWN_SECONDS,
) -> bool:
    """Start the chain if it is not already running. Returns whether it enqueued.

    Idempotent by design: called on every executor startup, and a restart must
    never fork a second chain. Two chains would be two competitors for the one
    serial Ollama, which is the exact failure this whole design exists to
    prevent.

    Idempotence is not enough on its own, though, because it says nothing about
    *rate*. This process seeds at most once per ``reseed_cooldown_seconds``;
    see that constant for the 78 minutes that bought it. The first seed in a
    process is always immediate, so a restart recovers at once, and the
    cooldown is only consulted when a seed would actually be written — a call
    that returns early because the chain is alive costs nothing and leaves the
    clock alone.
    """
    global _last_seeded_monotonic

    if not (distillation_enabled() if enabled is None else enabled):
        return False
    queue = repository if repository is not None else _default_repository()
    check = getattr(queue, "has_open_job_of_kind", None)
    if check is None:
        raise TypeError("seeding the distill chain needs a queue that can report open jobs")
    if check(DISTILL_JOB_KIND):
        return False

    now = _monotonic()
    if _last_seeded_monotonic is not None and now - _last_seeded_monotonic < reseed_cooldown_seconds:
        # The chain has died at least twice in quick succession, so something
        # underneath it is broken and re-seeding now would only widen the
        # crater. One line per suppression, at warning level, so the log says
        # the chain is down rather than going quiet.
        logger.warning(
            "not re-seeding the %s chain: the last seed was %.0fs ago and the chain is already "
            "gone again, so something below it is failing; waiting %.0fs between seeds",
            DISTILL_JOB_KIND,
            now - _last_seeded_monotonic,
            reseed_cooldown_seconds,
        )
        return False

    _enqueue_successor(delay_seconds, "seed", repository=queue)
    _last_seeded_monotonic = now
    return True


def reset_seed_cooldown() -> None:
    """Forget when this process last seeded. For tests and for a fresh worker."""
    global _last_seeded_monotonic
    _last_seeded_monotonic = None


def _repository_live_work_check(repository: JobRepository | None) -> LiveWorkCheck:
    def check() -> bool:
        queue = repository if repository is not None else _default_repository()
        ready = getattr(queue, "has_ready_job_excluding_kind", None)
        if ready is None:
            # Unknown means yield. A distill pass that skips a chunk costs
            # nothing but a cooldown; one that runs while a message waits costs
            # ~55s of silence, and that has already happened once.
            return True
        return bool(ready(DISTILL_JOB_KIND))

    return check


def _status_at_entry(job_id: str, repository: JobRepository | None) -> str | None:
    """The row's status as this pass begins, or ``None`` if it cannot be read.

    ``None`` disables the ownership half of the fork guard rather than failing
    the pass, which keeps a queue that cannot answer from silently killing the
    chain. The sibling-row half still applies.
    """
    try:
        queue = repository if repository is not None else _default_repository()
        status_of = getattr(queue, "status_of_job", None)
        return None if status_of is None else status_of(job_id)
    except Exception as exc:  # noqa: BLE001 - a guard must not break the handler
        logger.warning("could not read %s status at entry (%s)", job_id, type(exc).__name__)
        return None


def _repository_fork_guard(repository: JobRepository | None) -> ForkGuard:
    """Whether this pass must refrain from enqueuing a successor.

    Two distinct ways one chain becomes two, and a check for each:

    1. **The row stopped being ours.** The poller cannot kill a handler thread,
       only stop waiting for it, and it re-queues what it claimed on timeout.
       The abandoned thread then finishes its enqueue — and its own row is
       queued again beside the successor it just wrote. Excluding "other" rows
       cannot catch this, because the duplicate *is* our row. So: if our status
       is no longer ``running``, we were fired, and a fired worker writes
       nothing.
    2. **A sibling row is already open.** ``complete()`` failing after the
       successor was enqueued leaves the row running, the stale lease is
       reclaimed by ``0002_job_retries.sql``, and the handler runs a second
       time. Here the successor from the first run is the rival, and excluding
       ourselves is exactly right.

    Both are enqueue-side and neither is symmetric, so two briefly-coexisting
    rows can never both defer and end the chain for good.
    """

    def check(job_id: str, entry_status: str | None) -> bool:
        queue = repository if repository is not None else _default_repository()

        status_of = getattr(queue, "status_of_job", None)
        if status_of is not None and entry_status is not None:
            current = status_of(job_id)
            # A *change* is the signal, not any particular value. Asserting
            # "running" would be wrong: a handler invoked directly, outside the
            # poll loop, legitimately sees its own row still queued. What can
            # never be legitimate is the status moving out from under us
            # mid-pass — that is the poller having re-queued what it claimed.
            if current is not None and current != entry_status:
                return True

        rival = getattr(queue, "has_open_job_of_kind_excluding", None)
        if rival is not None and rival(DISTILL_JOB_KIND, job_id):
            return True

        # Unknown means enqueue, the mirror image of the yield check above.
        # There, silence is the expensive failure; here, a dead chain is.
        return False

    return check


def _repository_successor_enqueue(repository: JobRepository | None) -> SuccessorEnqueue:
    def schedule(
        delay_seconds: float, reason: str, *, may_write: Callable[[], bool] | None = None
    ) -> None:
        _enqueue_successor(delay_seconds, reason, repository=repository, may_write=may_write)

    return schedule


def _enqueue_successor(
    delay_seconds: float,
    reason: str,
    *,
    repository: JobRepository | None,
    may_write: Callable[[], bool] | None = None,
) -> Job | None:
    """Enqueue the chain's next link, unless the fork guard vetoes it here.

    The payload carries scheduling metadata only. No turn text, no user id, and
    nothing derived from a conversation ever goes into the durable queue, which
    is hosted; personal content stays on loopback.

    ``may_write`` is checked immediately before the write and nowhere else.
    Returns ``None`` when the write was suppressed.
    """
    if may_write is not None and not may_write():
        logger.warning(
            "not enqueuing a %s successor: this pass no longer owns its row, or a "
            "sibling row is already open (reason would have been %s)",
            DISTILL_JOB_KIND,
            reason,
        )
        return None
    run_after = _utcnow() + timedelta(seconds=max(0.0, delay_seconds))
    return enqueue(
        DISTILL_JOB_KIND,
        {"reason": reason},
        run_after,
        max_attempts=DISTILL_MAX_ATTEMPTS,
        repository=repository,
    )


def _monotonic() -> float:
    """Seeding's clock, separate from ``_utcnow`` and for the same reason.

    Monotonic rather than wall-clock: the seed throttle is a rate limit, and a
    laptop that suspends, resumes, or has its clock corrected must not be able
    to talk it into either firing early or never firing again.
    """
    return time.monotonic()


def _utcnow() -> datetime:
    """Indirection so a test can drive the chain on a controlled clock.

    The anti-starvation property is about claim *ordering*, which is a function
    of ``run_after``. Proving it against real wall-clock cooldowns would mean a
    slow, flaky test; proving it against a fake clock and the real ordering
    rule is the same proof without the sleep.
    """
    return datetime.now(UTC)


def _default_repository() -> Any:
    from db.jobs import SupabaseJobsRepository

    return SupabaseJobsRepository.from_env()


def _close_quietly(resource: Any) -> None:
    close = getattr(resource, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception:
        logger.debug("ignoring close() failure on %s", type(resource).__name__)
