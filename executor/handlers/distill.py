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
below is that invariant, and it is tested.
"""

from __future__ import annotations

import logging
import os
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


class ChainQueue(Protocol):
    """The narrow queue slice this chain needs, beyond ``JobRepository``.

    Deliberately separate from ``db.jobs.JobRepository`` so that Protocol stays
    exactly as wide as it is and every existing test double keeps satisfying
    it. See the comment above these methods in ``db/jobs.py``.
    """

    def has_ready_job_excluding_kind(self, kind: str) -> bool: ...

    def has_open_job_of_kind(self, kind: str) -> bool: ...


LiveWorkCheck = Callable[[], bool]
SuccessorEnqueue = Callable[[float, str], None]


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
    schedule = enqueue_successor or _repository_successor_enqueue(repository)

    def handle(job: Job) -> None:
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
) -> bool:
    """Start the chain if it is not already running. Returns whether it enqueued.

    Idempotent by design: called on every executor startup, and a restart must
    never fork a second chain. Two chains would be two competitors for the one
    serial Ollama, which is the exact failure this whole design exists to
    prevent.
    """
    if not (distillation_enabled() if enabled is None else enabled):
        return False
    queue = repository if repository is not None else _default_repository()
    check = getattr(queue, "has_open_job_of_kind", None)
    if check is None:
        raise TypeError("seeding the distill chain needs a queue that can report open jobs")
    if check(DISTILL_JOB_KIND):
        return False
    _enqueue_successor(delay_seconds, "seed", repository=queue)
    return True


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


def _repository_successor_enqueue(repository: JobRepository | None) -> SuccessorEnqueue:
    def schedule(delay_seconds: float, reason: str) -> None:
        _enqueue_successor(delay_seconds, reason, repository=repository)

    return schedule


def _enqueue_successor(
    delay_seconds: float, reason: str, *, repository: JobRepository | None
) -> Job:
    """Enqueue the chain's next link.

    The payload carries scheduling metadata only. No turn text, no user id, and
    nothing derived from a conversation ever goes into the durable queue, which
    is hosted; personal content stays on loopback.
    """
    run_after = _utcnow() + timedelta(seconds=max(0.0, delay_seconds))
    return enqueue(
        DISTILL_JOB_KIND,
        {"reason": reason},
        run_after,
        max_attempts=DISTILL_MAX_ATTEMPTS,
        repository=repository,
    )


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
