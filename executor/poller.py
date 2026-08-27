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
from executor.handlers.distill import (
    DISTILL_JOB_KIND,
    HANDLER_TIMEOUT_SECONDS as DISTILL_TIMEOUT_SECONDS,
    assert_timeouts_ordered,
    build_distill_memory_handler,
    seed_distill_chain,
)
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
#
# ``distill_memory`` carries a longer timeout than the default 300s would
# suggest is needed, but the number that matters is the *other* direction: it
# must stay above the Ollama client's own extraction timeout so a wedged model
# raises inside the handler thread rather than leaving that thread abandoned,
# still holding the single local Ollama, while this loop claims the next job.
# See ``executor/handlers/distill.py``.
DEFAULT_HANDLERS: dict[str, HandlerRegistration] = {
    "whatsapp_webhook": HandlerRegistration(build_whatsapp_webhook_handler()),
    "flp_sort": HandlerRegistration(build_flp_sort_handler()),
    DISTILL_JOB_KIND: HandlerRegistration(
        build_distill_memory_handler(), timeout_seconds=DISTILL_TIMEOUT_SECONDS
    ),
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
    # Here, and not at handler-build time: DEFAULT_HANDLERS is constructed at
    # module import, before load_dotenv has run, so a build-time check reads an
    # environment that does not yet hold the value. Without this call the
    # invariant the distill module documents as "tested" has no production
    # caller at all — raise OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS above the
    # handler's own timeout and nothing would notice, re-opening the abandoned
    # -thread hazard that starved eight inbound messages on 26 August 2026.
    assert_timeouts_ordered()
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

    if not args.once:
        _seed_distill_chain()

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


def _seed_distill_chain() -> None:
    """Start the batch-distillation chain if it is not already in the queue.

    Best-effort on purpose. Supabase connectivity is intermittently flaky on
    this machine, and a failed seed costs one idle cooldown at worst — an
    executor that refuses to start because a background chain could not be
    seeded would be a far worse trade. Skipped for ``--once`` runs, which are
    diagnostics and must not mutate the queue.
    """
    try:
        if seed_distill_chain():
            logger.info("seeded the %s chain", DISTILL_JOB_KIND)
    except Exception as exc:
        logger.warning("could not seed the %s chain (%s)", DISTILL_JOB_KIND, type(exc).__name__)


async def request_completion(
    task_profile: str, messages: Sequence[Mapping[str, Any]], *, urgent: bool = False
) -> RoutedResult:
    """Give executor jobs the provider router's single async entry point."""
    return await route(task_profile, messages, urgent=urgent)


if __name__ == "__main__":  # pragma: no cover - exercised as a module entry point
    raise SystemExit(main())
