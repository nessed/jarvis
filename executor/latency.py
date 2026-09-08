"""One line per reply, saying where the seconds went.

Until this existed the only reply-path numbers were a hand-run audit
(``docs/history/infra-audit-2026-09-04.md``: ~10 s text, 25-50 s voice). Every
task in the September batch claims to make that faster, and without per-stage
timing on every real job "faster" is a guess someone has to re-measure by
hand. So each job now emits exactly one structured INFO line when a reply goes
out:

    reply-latency job=<id> kind=<kind> total_ms=9840 queue_wait_ms=1200 \
        cue_ms=980 classify_ms=2100 recall_ms=520 model_ms=3900 send_ms=1100 \
        remember_ms=40

``tools/reply_latency.py`` reads those back and prints p50/p95 per stage.

**No message text, ever.** A stage name and a duration are the whole
vocabulary. The line is written to the same log a support-minded person may
paste somewhere, and a reply-latency line that quoted what was said would make
that unsafe.

Only a job that actually replies emits a line. A duplicate webhook, a status
callback, and a voice note that transcribed to nothing all return early and
say nothing here, because timing a no-op would skew every percentile the tool
prints.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Iterator, Mapping

logger = logging.getLogger(__name__)

LINE_PREFIX = "reply-latency"

# Fixed order, so the line reads the same way every time and a human scanning
# a log sees the stages in the order they happened. Anything measured but not
# named here is appended afterwards in insertion order rather than dropped --
# a new stage should show up in the log the day it is added, not the day
# somebody remembers to update this tuple.
STAGE_ORDER = (
    "queue_wait",
    "cue",
    "stt",
    "classify",
    "recall",
    "model",
    "tts",
    "send",
    "remember",
)

# The claim timestamps of jobs that have been claimed but whose handler has
# not started yet. Small by construction: the poller claims one job at a time
# and the handler pops the entry on its first line. The cap is there only so a
# handler that never runs -- an unregistered kind, a timeout before entry --
# cannot leak this dictionary over a long-lived worker's lifetime.
_MAX_TRACKED_CLAIMS = 64
_claimed_at: dict[str, datetime] = {}


def mark_claimed(job_id: str, *, now: datetime | None = None) -> None:
    """Record that this job was just claimed off the queue.

    Called by the poller, read by the handler, which is the only way
    ``queue_wait`` can mean "how long it sat there" rather than "how long
    until the handler happened to look". The two are a checkpoint write apart
    -- one Supabase round trip -- which is exactly the kind of gap this whole
    module exists to stop hiding.
    """
    if len(_claimed_at) >= _MAX_TRACKED_CLAIMS:
        _claimed_at.clear()
    _claimed_at[job_id] = now or datetime.now(UTC)


def take_claimed_at(job_id: str) -> datetime | None:
    """The claim time for this job, removed from the table. ``None`` if unknown."""
    return _claimed_at.pop(job_id, None)


class ReplySpans:
    """Per-stage durations for one job, emitted as one line at the end.

    Stages are recorded in milliseconds, rounded, because a reply path with a
    one-second floor has no use for microseconds and an integer is what
    ``tools/reply_latency.py`` has to parse back.
    """

    def __init__(
        self,
        job_id: str,
        kind: str,
        *,
        created_at: datetime | str | None = None,
        claimed_at: datetime | None = None,
        clock: Any = time.monotonic,
        now: Any = None,
    ) -> None:
        self.job_id = job_id
        self.kind = kind
        self._clock = clock
        self._now = now or (lambda: datetime.now(UTC))
        self._started = clock()
        self._stages: dict[str, float] = {}
        self._emitted = False

        created = _as_datetime(created_at)
        if created is not None:
            reference = claimed_at or self._now()
            queue_wait = (reference - created).total_seconds()
            # A clock skew between the database and this machine can make that
            # negative. Zero is a truthful floor; a negative queue wait would
            # poison every percentile downstream.
            self._stages["queue_wait"] = max(queue_wait, 0.0)

    @classmethod
    def for_job(cls, job: Any, **kwargs: Any) -> "ReplySpans":
        """Spans for a claimed job, using the poller's claim time if it left one."""
        return cls(
            str(getattr(job, "id", "")),
            str(getattr(job, "kind", "")),
            created_at=getattr(job, "created_at", None),
            claimed_at=take_claimed_at(str(getattr(job, "id", ""))),
            **kwargs,
        )

    def record(self, stage: str, seconds: float) -> None:
        """Add a stage measured somewhere else -- the service's own timings, say."""
        self._stages[stage] = self._stages.get(stage, 0.0) + max(float(seconds), 0.0)

    def update(self, timings: Mapping[str, float]) -> None:
        for stage, seconds in timings.items():
            self.record(stage, seconds)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Time a block. A raising block is still recorded, then re-raises.

        Recording a failed stage is deliberate: a 300 s hang that ends in an
        exception is the single most useful number in the line, and dropping
        it would leave the slowest replies invisible.
        """
        started = self._clock()
        try:
            yield
        finally:
            self.record(name, self._clock() - started)

    @property
    def stages(self) -> dict[str, float]:
        return dict(self._stages)

    def total_seconds(self) -> float:
        """Queue wait plus everything since this object was made."""
        return self._stages.get("queue_wait", 0.0) + (self._clock() - self._started)

    def render(self) -> str:
        parts = [
            f"{LINE_PREFIX} job={self.job_id} kind={self.kind}",
            f"total_ms={_ms(self.total_seconds())}",
        ]
        named = [s for s in STAGE_ORDER if s in self._stages]
        extra = [s for s in self._stages if s not in STAGE_ORDER]
        for stage in named + extra:
            parts.append(f"{stage}_ms={_ms(self._stages[stage])}")
        return " ".join(parts)

    def emit(self, log: logging.Logger | None = None) -> str:
        """Log the line once. Repeat calls are no-ops, and return the same text.

        Once, because the handler has several exits and a percentile built
        from a double-counted job is wrong in a way nobody would notice.
        """
        line = self.render()
        if self._emitted:
            return line
        self._emitted = True
        (log or logger).info("%s", line)
        return line


def _as_datetime(value: Any) -> datetime | None:
    """A timestamp, however the caller happened to be holding it.

    A ``Job`` off the queue carries a real ``datetime``; one rebuilt from a
    captured JSON payload — ``tools/replay_job.py`` — carries the ISO string
    PostgREST sent. Neither is worth a crash on the reply path: a queue wait
    this cannot read is a queue wait it does not report.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def _ms(seconds: float) -> int:
    return int(round(max(seconds, 0.0) * 1000))
