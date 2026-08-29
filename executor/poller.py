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
    fail,
    retry_or_dead_letter,
    set_timeout,
)
from executor.app_automation.handler import (
    WHATSAPP_DESKTOP_SEND_MESSAGE_JOB_KIND,
    ZOOM_JOIN_MEETING_JOB_KIND,
    build_app_automation_handler,
)
from executor.flp.sort import ReorderNotSupported, build_flp_sort_handler
from executor.handlers.distill import (
    DISTILL_JOB_KIND,
    HANDLER_TIMEOUT_SECONDS as DISTILL_TIMEOUT_SECONDS,
    assert_timeouts_ordered,
    build_distill_memory_handler,
    seed_distill_chain,
)
from executor.handlers.whatsapp import build_whatsapp_webhook_handler
from executor.heartbeat import clear as clear_heartbeat, touch as touch_heartbeat
from executor.system_control.handler import build_system_control_handler
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
WHATSAPP_JOB_KIND = "whatsapp_webhook"

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
#
# zoom_join_meeting and whatsapp_desktop_send_message share one handler
# instance (see executor/app_automation/handler.py) which dispatches on
# job.kind internally.
_app_automation_handler = build_app_automation_handler()

DEFAULT_HANDLERS: dict[str, HandlerRegistration] = {
    WHATSAPP_JOB_KIND: HandlerRegistration(build_whatsapp_webhook_handler()),
    "flp_sort": HandlerRegistration(build_flp_sort_handler()),
    "system_control": HandlerRegistration(build_system_control_handler()),
    ZOOM_JOIN_MEETING_JOB_KIND: HandlerRegistration(_app_automation_handler),
    WHATSAPP_DESKTOP_SEND_MESSAGE_JOB_KIND: HandlerRegistration(_app_automation_handler),
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
    kind_filter: str | None = None,
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
    job = claim_next(kind_filter, repository=repository)
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
    except (ReorderNotSupported, FileNotFoundError) as exc:
        # Both are permanent, not transient: a mixer-reorder rule PyFLP can
        # never satisfy, or a target .flp path that is simply gone. Retrying
        # either three times through backoff cannot change the outcome, so
        # skip straight to a terminal, non-retried failure instead of
        # spending the backoff window on a foregone conclusion.
        logger.warning(
            "job handler failed permanently, not retrying (%s, job=%s)",
            type(exc).__name__,
            job.id,
        )
        return fail(
            job.id,
            f"executor handler failed permanently ({type(exc).__name__})",
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
    parser.add_argument(
        "--kind",
        choices=tuple(DEFAULT_HANDLERS),
        help="claim only this registered job kind",
    )
    parser.add_argument(
        "--no-heartbeat",
        action="store_true",
        help="do not maintain the shared executor heartbeat",
    )
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")

    # A kind-filtered poller can only seed the chain it owns. This keeps the
    # fast WhatsApp worker from touching background work and preserves the
    # original unfiltered executor's startup behaviour for diagnostics.
    seeds_distill = args.kind in (None, DISTILL_JOB_KIND)
    if not args.once and seeds_distill:
        _seed_distill_chain()

    handlers: JobHandlers = (
        DEFAULT_HANDLERS
        if args.kind is None
        else {args.kind: DEFAULT_HANDLERS[args.kind]}
    )

    try:
        while True:
            # Marks the executor live so batch tools (distill, backfill) can
            # refuse to compete for the single local Ollama. See
            # executor/heartbeat.py.
            if not args.no_heartbeat:
                touch_heartbeat()
            idle = True
            try:
                idle = poll_once(handlers=handlers, kind_filter=args.kind) is None
            except Exception as exc:
                if args.once:
                    raise
                logger.warning("executor poll failed (%s)", type(exc).__name__)
            if args.once:
                return 0
            if idle:
                # A stalled distill chain only reveals itself once the queue
                # goes quiet (see _seed_distill_chain's docstring for why a
                # failed seed is otherwise silent forever). Retrying the
                # idempotent seed here, once per idle cycle, gives it another
                # chance without hitting Supabase on every busy iteration.
                if seeds_distill:
                    _seed_distill_chain()
                time.sleep(args.interval)
            # else: poll_once just finished real work and there may be more
            # queued -- loop straight back into another poll_once instead of
            # sleeping, so a backlog drains back-to-back rather than at most
            # one job per --interval.
    except KeyboardInterrupt:
        # A deliberate, clean stop: clear the marker so batch tools don't
        # wait out up to DEFAULT_MAX_AGE_SECONDS of a stale-but-true guard
        # for no reason. A crash must NOT reach this branch -- see
        # executor/heartbeat.py's clear() docstring.
        if not args.no_heartbeat:
            clear_heartbeat()
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
