"""Pull-based laptop executor for Phase 0 durable jobs.

The poller deliberately performs no LLM or WhatsApp work itself. Callers
inject a deterministic mapping of job kinds to local handlers, so later phases
can add local work without moving it into the webhook.
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from dotenv import load_dotenv

from db.jobs import Job, JobRepository, checkpoint, claim_next, complete, fail
from router import RoutedResult, route


JobHandler = Callable[[Job], None]
JobHandlers = Mapping[str, JobHandler]
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
logger = logging.getLogger(__name__)


class UnknownJobKindError(Exception):
    """Raised when a claimed job has no explicitly registered handler."""


def poll_once(
    *,
    repository: JobRepository | None = None,
    handler: JobHandler | None = None,
    handlers: JobHandlers | None = None,
) -> Job | None:
    """Atomically claim and finish one ready job, if any.

    ``handler`` remains an explicit per-call override for diagnostics and
    compatibility. Otherwise ``handlers`` supplies the registered handler for
    the claimed job's kind. Missing kinds fail deterministically. Every stored
    diagnostic uses only an exception type, so payloads or provider details
    cannot leak into the durable queue.
    """
    job = claim_next(repository=repository)
    if job is None:
        return None

    checkpoint(
        job.id,
        {**job.checkpoint, "phase": "executor_started"},
        repository=repository,
    )
    try:
        _resolve_handler(job, handler=handler, handlers=handlers)(job)
    except Exception as exc:
        return fail(
            job.id,
            f"executor handler failed ({type(exc).__name__})",
            repository=repository,
        )
    return complete(job.id, repository=repository)


def _resolve_handler(
    job: Job, *, handler: JobHandler | None, handlers: JobHandlers | None
) -> JobHandler:
    """Return the explicit override or registered handler for a job kind."""
    if handler is not None:
        return handler
    if handlers is not None and (registered_handler := handlers.get(job.kind)) is not None:
        return registered_handler
    raise UnknownJobKindError


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
            try:
                poll_once()
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
