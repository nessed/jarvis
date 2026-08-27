"""The distill chain: chunking, yielding, chain uniqueness, and non-starvation.

The property under test is the one that matters operationally: **a batch
distill pass cannot starve a live reply**, on a queue that has no priority
column and orders strictly by ``run_after asc, created_at asc``.

``FakeQueue`` below reimplements that ordering rule faithfully, including the
part that works against us — a ripe distill row is claimed ahead of a WhatsApp
message that arrived later. The tests do not paper over that inversion; one of
them constructs it deliberately and asserts it happens, then asserts the reply
still goes out on the next poll because the handler yielded instead of holding
Ollama for ~55s.

No real Ollama, no real Supabase, no sleeping: the chain runs on a fake clock.
"""

from __future__ import annotations

import itertools
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from db.jobs import Job
from executor.handlers import distill as distill_handler
from executor.handlers.distill import (
    DEFAULT_BUSY_COOLDOWN_SECONDS,
    DEFAULT_IDLE_COOLDOWN_SECONDS,
    DEFAULT_YIELD_COOLDOWN_SECONDS,
    DISTILL_JOB_KIND,
    HANDLER_TIMEOUT_SECONDS,
    assert_timeouts_ordered,
    build_distill_memory_handler,
    distillation_enabled,
    extraction_timeout_seconds,
    seed_distill_chain,
)
from executor.poller import HandlerRegistration, poll_once
from memory.types import Fact

START = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


class Clock:
    """A fake wall clock the chain and the queue agree on."""

    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self.now


class FakeQueue:
    """A job queue implementing ``claim_next_job``'s real ordering rule.

    ``order by run_after asc, created_at asc`` over rows that are queued and
    ripe. This is the whole point of the fake: a version that quietly favoured
    WhatsApp jobs would prove nothing.
    """

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.rows: list[dict] = []
        self._ids = itertools.count(1)
        self.claim_order: list[str] = []

    # -- writes -----------------------------------------------------------
    def enqueue(self, kind, payload, run_after=None, max_attempts=None) -> Job:
        row = {
            "id": f"{kind}-{next(self._ids)}",
            "kind": kind,
            "payload": dict(payload),
            "status": "queued",
            "checkpoint": {},
            "run_after": run_after or self.clock.now,
            "created_at": self.clock.now,
            "updated_at": self.clock.now,
            "attempts": 0,
            "max_attempts": max_attempts or 5,
            "timeout_seconds": 300,
        }
        self.rows.append(row)
        return Job.from_row(row)

    def claim_next(self, kind_filter=None) -> Job | None:
        ready = [
            row
            for row in self.rows
            if row["status"] == "queued"
            and row["run_after"] <= self.clock.now
            and (kind_filter is None or row["kind"] == kind_filter)
        ]
        ready.sort(key=lambda row: (row["run_after"], row["created_at"]))
        if not ready:
            return None
        row = ready[0]
        row["status"] = "running"
        row["attempts"] += 1
        row["updated_at"] = self.clock.now
        self.claim_order.append(row["kind"])
        return Job.from_row(row)

    def _find(self, job_id: str) -> dict:
        for row in self.rows:
            if row["id"] == job_id:
                return row
        raise KeyError(job_id)

    def checkpoint(self, job_id, state) -> Job:
        row = self._find(str(job_id))
        row["checkpoint"] = dict(state)
        return Job.from_row(row)

    def complete(self, job_id) -> Job:
        row = self._find(str(job_id))
        row["status"] = "done"
        return Job.from_row(row)

    def fail(self, job_id, err) -> Job:
        row = self._find(str(job_id))
        row["status"] = "failed"
        return Job.from_row(row)

    def retry_or_dead_letter(self, job_id, err, delay_seconds=0) -> Job:
        row = self._find(str(job_id))
        if row["attempts"] >= row["max_attempts"]:
            row["status"] = "dead_letter"
        else:
            row["status"] = "queued"
            row["run_after"] = self.clock.now + timedelta(seconds=delay_seconds)
        row["checkpoint"] = {**row["checkpoint"], "error": {"message": err}}
        return Job.from_row(row)

    def set_timeout(self, job_id, timeout_seconds) -> Job:
        row = self._find(str(job_id))
        row["timeout_seconds"] = int(timeout_seconds)
        return Job.from_row(row)

    # -- the two additive reads the chain needs ---------------------------
    def has_ready_job_excluding_kind(self, kind: str) -> bool:
        return any(
            row["status"] == "queued"
            and row["kind"] != kind
            and row["run_after"] <= self.clock.now
            for row in self.rows
        )

    def has_open_job_of_kind(self, kind: str) -> bool:
        return any(
            row["kind"] == kind and row["status"] in {"queued", "running"}
            for row in self.rows
        )

    def status_of_job(self, job_id: str) -> str | None:
        for row in self.rows:
            if row["id"] == job_id:
                return str(row["status"])
        return None

    def has_open_job_of_kind_excluding(self, kind: str, job_id: str) -> bool:
        return any(
            row["kind"] == kind
            and row["status"] in {"queued", "running"}
            and row["id"] != job_id
            for row in self.rows
        )

    # -- assertions helpers -----------------------------------------------
    def of_kind(self, kind: str, *statuses: str) -> list[dict]:
        return [
            row
            for row in self.rows
            if row["kind"] == kind and (not statuses or row["status"] in statuses)
        ]

    def status_of(self, job_id: str) -> str:
        return self._find(job_id)["status"]


class FakeTurns:
    def __init__(self, count: int) -> None:
        self.remaining = [
            Fact(
                id=f"turn-{i}",
                text=f"turn {i}",
                source="whatsapp:alice",
                created_at=START + timedelta(minutes=i),
                metadata={"user_id": "alice", "role": "user", "distilled": False},
            )
            for i in range(count)
        ]
        self.closed = 0

    def undistilled_turns(self, *, limit=None):
        return self.remaining if limit is None else self.remaining[:limit]

    def mark_distilled(self, fact: Fact) -> None:
        self.remaining = [t for t in self.remaining if t.id != fact.id]

    def close(self) -> None:
        self.closed += 1


class FakeExtractor:
    """Stands in for the 8B Mem0 extraction that costs ~55s of Ollama."""

    def __init__(self, *, explode: bool = False) -> None:
        self.calls: list[str] = []
        self.closed = 0
        self.explode = explode

    def remember(self, text: str, **kwargs: object) -> None:
        self.calls.append(text)
        if self.explode:
            raise RuntimeError("ollama fell over")

    def close(self) -> None:
        self.closed += 1


def _chain(clock: Clock, queue: FakeQueue, turns: FakeTurns, extractor: FakeExtractor, **kwargs):
    """Build the handler wired to the fakes, with short deterministic cooldowns."""
    options = {
        "busy_cooldown_seconds": 10.0,
        "idle_cooldown_seconds": 600.0,
        "yield_cooldown_seconds": 30.0,
        "enabled": True,
    }
    options.update(kwargs)
    return build_distill_memory_handler(
        open_memory=lambda *a, **k: turns,
        open_extractor=lambda *a, **k: extractor,
        repository=queue,
        **options,
    )


@pytest.fixture
def clock(monkeypatch) -> Clock:
    ticker = Clock()
    monkeypatch.setattr(distill_handler, "_utcnow", ticker)
    return ticker


def _distill_job(queue: FakeQueue) -> Job:
    return Job.from_row(queue.of_kind(DISTILL_JOB_KIND)[0])


# --------------------------------------------------------------------------
# Chunking: one turn per job, however deep the backlog.
# --------------------------------------------------------------------------


def test_one_invocation_extracts_exactly_one_turn_with_a_deep_backlog(clock):
    queue = FakeQueue(clock)
    turns, extractor = FakeTurns(10), FakeExtractor()
    handle = _chain(clock, queue, turns, extractor)

    handle(queue.enqueue(DISTILL_JOB_KIND, {"reason": "seed"}))

    assert len(extractor.calls) == 1
    assert len(turns.remaining) == 9


def test_each_run_enqueues_exactly_one_successor(clock):
    queue = FakeQueue(clock)
    handle = _chain(clock, queue, FakeTurns(5), FakeExtractor())
    seed = queue.enqueue(DISTILL_JOB_KIND, {"reason": "seed"})

    handle(seed)

    successors = [row for row in queue.of_kind(DISTILL_JOB_KIND) if row["id"] != seed.id]
    assert len(successors) == 1
    assert successors[0]["payload"] == {"reason": "backlog"}


def _successor(queue: FakeQueue, seed: Job) -> dict:
    """The one row the handler enqueued, as distinct from the row it ran on."""
    rows = [row for row in queue.of_kind(DISTILL_JOB_KIND) if row["id"] != seed.id]
    assert len(rows) == 1
    return rows[0]


def test_a_backlog_schedules_the_successor_sooner_than_an_empty_one(clock):
    busy_queue, idle_queue = FakeQueue(clock), FakeQueue(clock)
    busy_seed = busy_queue.enqueue(DISTILL_JOB_KIND, {})
    idle_seed = idle_queue.enqueue(DISTILL_JOB_KIND, {})
    _chain(clock, busy_queue, FakeTurns(5), FakeExtractor())(busy_seed)
    _chain(clock, idle_queue, FakeTurns(0), FakeExtractor())(idle_seed)

    assert _successor(busy_queue, busy_seed)["run_after"] == clock.now + timedelta(seconds=10)
    assert _successor(idle_queue, idle_seed)["run_after"] == clock.now + timedelta(seconds=600)


def test_the_last_turn_schedules_the_successor_at_the_idle_cooldown(clock):
    queue = FakeQueue(clock)
    turns = FakeTurns(1)
    seed = queue.enqueue(DISTILL_JOB_KIND, {})

    _chain(clock, queue, turns, FakeExtractor())(seed)

    assert turns.remaining == []
    successor = _successor(queue, seed)
    assert successor["payload"] == {"reason": "idle"}
    # The label is not the property that matters; the delay is. Draining the
    # backlog must drop the chain to the slow cadence in the same pass, not on
    # some later one.
    assert successor["run_after"] == clock.now + timedelta(seconds=600)


def test_the_shipped_default_cooldowns_are_ordered_busy_then_yield_then_idle():
    """The cooldowns every other test injects are fakes; these are the real ones.

    A regression that set the idle cooldown to the busy value would leave every
    injected-cooldown test in this file green while an idle laptop ground the
    chain at four claims a minute forever.
    """
    assert DEFAULT_BUSY_COOLDOWN_SECONDS < DEFAULT_YIELD_COOLDOWN_SECONDS
    assert DEFAULT_YIELD_COOLDOWN_SECONDS < DEFAULT_IDLE_COOLDOWN_SECONDS
    # An order of magnitude, not one second: idling is meant to be cheap.
    assert DEFAULT_IDLE_COOLDOWN_SECONDS >= 10 * DEFAULT_BUSY_COOLDOWN_SECONDS


def _mark_done(queue: FakeQueue, job_id: str) -> None:
    """What the poller does to the row a handler returned from."""
    queue.complete(job_id)


def test_the_chain_drains_from_the_busy_cadence_to_the_idle_one_and_stays(clock):
    """Follow one chain across the transition the brief asks about.

    Two turns, then nothing. The pass that clears the last turn must already
    schedule at the idle cooldown, and every pass after it — where there is
    genuinely nothing to distill — must keep doing so rather than reverting to
    the busy rate.
    """
    queue = FakeQueue(clock)
    turns, extractor = FakeTurns(2), FakeExtractor()
    handle = _chain(clock, queue, turns, extractor)

    job = queue.enqueue(DISTILL_JOB_KIND, {"reason": "seed"})
    reasons: list[str] = []
    delays: list[float] = []

    for _ in range(4):
        before = {row["id"] for row in queue.of_kind(DISTILL_JOB_KIND)}
        handle(job)
        _mark_done(queue, job.id)
        fresh = [row for row in queue.of_kind(DISTILL_JOB_KIND) if row["id"] not in before]
        assert len(fresh) == 1, "one link in, one link out"
        reasons.append(fresh[0]["payload"]["reason"])
        delays.append((fresh[0]["run_after"] - clock.now).total_seconds())
        clock.advance(delays[-1])
        job = Job.from_row(fresh[0])

    assert reasons == ["backlog", "idle", "idle", "idle"]
    assert delays == [10.0, 600.0, 600.0, 600.0]
    assert len(extractor.calls) == 2, "only the two real turns were ever extracted"


def test_an_idle_laptop_ticks_at_the_idle_cadence_and_never_at_the_busy_one(clock):
    """Twelve simulated hours of an empty backlog, driven through ``poll_once``.

    The chain does not end when there is nothing to distill — it keeps one row
    in the queue on purpose, so it never needs re-seeding. That is a design
    choice, and this is the test that pins its cost: one claim per idle
    cooldown, one open row at every instant, and zero extractions.
    """
    queue = FakeQueue(clock)
    extractor = FakeExtractor()
    handlers = {
        DISTILL_JOB_KIND: HandlerRegistration(
            _chain(clock, queue, FakeTurns(0), extractor),
            timeout_seconds=HANDLER_TIMEOUT_SECONDS,
        )
    }
    seed_distill_chain(repository=queue, delay_seconds=0, enabled=True)

    runs = 0
    for _ in range(12 * 60):  # twelve hours at a one-minute poll
        if poll_once(repository=queue, handlers=handlers) is not None:
            runs += 1
        clock.advance(60)
        assert len(queue.of_kind(DISTILL_JOB_KIND, "queued", "running")) == 1

    assert extractor.calls == []
    # 600s idle cooldown over twelve hours. At the 10s busy cooldown this would
    # be 4320, which is the runaway the chain must not become.
    assert runs == 12 * 3600 // 600


# --------------------------------------------------------------------------
# The yield: the actual anti-starvation mechanism.
# --------------------------------------------------------------------------


def test_queued_live_work_makes_the_pass_extract_nothing_at_all(clock):
    queue = FakeQueue(clock)
    turns, extractor = FakeTurns(5), FakeExtractor()
    queue.enqueue("whatsapp_webhook", {"entry": []})

    _chain(clock, queue, turns, extractor)(queue.enqueue(DISTILL_JOB_KIND, {}))

    assert extractor.calls == []
    assert len(turns.remaining) == 5


def test_yielding_still_re_enqueues_so_the_chain_survives(clock):
    queue = FakeQueue(clock)
    queue.enqueue("whatsapp_webhook", {"entry": []})
    seed = queue.enqueue(DISTILL_JOB_KIND, {})

    _chain(clock, queue, FakeTurns(5), FakeExtractor())(seed)

    successors = [row for row in queue.of_kind(DISTILL_JOB_KIND) if row["id"] != seed.id]
    assert len(successors) == 1
    assert successors[0]["payload"] == {"reason": "yield"}
    assert successors[0]["run_after"] == clock.now + timedelta(seconds=30)


def test_the_yield_check_runs_before_the_memory_database_is_even_opened(clock):
    queue = FakeQueue(clock)
    queue.enqueue("whatsapp_webhook", {"entry": []})
    opened: list[str] = []

    handle = build_distill_memory_handler(
        open_memory=lambda *a, **k: opened.append("memory") or FakeTurns(5),
        open_extractor=lambda *a, **k: opened.append("extractor") or FakeExtractor(),
        repository=queue,
        enabled=True,
    )
    handle(queue.enqueue(DISTILL_JOB_KIND, {}))

    assert opened == []


def test_work_scheduled_for_later_does_not_count_as_live_work(clock):
    queue = FakeQueue(clock)
    extractor = FakeExtractor()
    queue.enqueue("flp_sort", {}, run_after=clock.now + timedelta(hours=1))

    _chain(clock, queue, FakeTurns(3), extractor)(queue.enqueue(DISTILL_JOB_KIND, {}))

    # A job deliberately deferred is not a message being kept waiting.
    assert len(extractor.calls) == 1


def test_another_distill_row_is_not_live_work(clock):
    queue = FakeQueue(clock)
    extractor = FakeExtractor()
    queue.enqueue(DISTILL_JOB_KIND, {"reason": "stray"})

    _chain(clock, queue, FakeTurns(3), extractor)(queue.enqueue(DISTILL_JOB_KIND, {}))

    assert len(extractor.calls) == 1


def test_a_queue_that_cannot_report_readiness_is_treated_as_busy(clock):
    class Blind(FakeQueue):
        has_ready_job_excluding_kind = None  # type: ignore[assignment]

    queue = Blind(clock)
    extractor = FakeExtractor()

    _chain(clock, queue, FakeTurns(3), extractor)(queue.enqueue(DISTILL_JOB_KIND, {}))

    # Unknown must mean yield: a skipped chunk costs a cooldown, a wrong guess
    # costs ~55s of silence on the reply path.
    assert extractor.calls == []


# --------------------------------------------------------------------------
# The ordering inversion, encoded on purpose.
# --------------------------------------------------------------------------


def test_a_ripe_distill_row_is_claimed_before_a_newer_whatsapp_job(clock):
    """The inversion is real. This test fails if the queue ever gains priority."""
    queue = FakeQueue(clock)
    queue.enqueue(DISTILL_JOB_KIND, {"reason": "seed"})
    clock.advance(60)
    queue.enqueue("whatsapp_webhook", {"entry": []})

    claimed = queue.claim_next()

    assert claimed is not None and claimed.kind == DISTILL_JOB_KIND


def test_the_inverted_claim_still_lets_the_reply_go_out_on_the_next_poll(clock):
    """Losing the claim race must cost a poll interval, not an extraction.

    Deleting the yield check makes this test fail, which is the point of
    writing it: without it, the yield is a comment.
    """
    queue = FakeQueue(clock)
    turns, extractor = FakeTurns(5), FakeExtractor()
    replies: list[str] = []

    queue.enqueue(DISTILL_JOB_KIND, {"reason": "seed"})
    clock.advance(60)
    whatsapp = queue.enqueue("whatsapp_webhook", {"entry": []})

    handlers = {
        DISTILL_JOB_KIND: HandlerRegistration(
            _chain(clock, queue, turns, extractor), timeout_seconds=HANDLER_TIMEOUT_SECONDS
        ),
        "whatsapp_webhook": HandlerRegistration(lambda job: replies.append(job.id)),
    }

    first = poll_once(repository=queue, handlers=handlers)
    second = poll_once(repository=queue, handlers=handlers)

    assert queue.claim_order == [DISTILL_JOB_KIND, "whatsapp_webhook"]
    assert first is not None and second is not None
    assert extractor.calls == []          # the distill pass yielded
    assert replies == [whatsapp.id]       # and the reply went out immediately after
    assert queue.status_of(whatsapp.id) == "done"


# --------------------------------------------------------------------------
# The bounded end-to-end property, driven through the real poll_once.
# --------------------------------------------------------------------------


def test_a_message_arriving_mid_chain_completes_within_a_bounded_number_of_polls(clock):
    queue = FakeQueue(clock)
    turns, extractor = FakeTurns(20), FakeExtractor()
    replies: list[str] = []
    handlers = {
        DISTILL_JOB_KIND: HandlerRegistration(
            _chain(clock, queue, turns, extractor), timeout_seconds=HANDLER_TIMEOUT_SECONDS
        ),
        "whatsapp_webhook": HandlerRegistration(lambda job: replies.append(job.id)),
    }

    seed_distill_chain(repository=queue, delay_seconds=0, enabled=True)

    # Let the chain get going on a real backlog.
    for _ in range(6):
        poll_once(repository=queue, handlers=handlers)
        clock.advance(15)
    assert len(extractor.calls) >= 3, "the chain should be making progress before the message"

    extractions_before = len(extractor.calls)
    whatsapp = queue.enqueue("whatsapp_webhook", {"entry": []})

    polls = 0
    while queue.status_of(whatsapp.id) != "done":
        polls += 1
        assert polls <= 4, "a live reply waited too many polls behind the distill chain"
        poll_once(repository=queue, handlers=handlers)
        clock.advance(15)

    assert replies == [whatsapp.id]
    # A bound, not an "eventually": at most the one chunk already in flight.
    assert len(extractor.calls) - extractions_before <= 1


def test_the_chain_never_forks_however_many_times_it_runs(clock):
    queue = FakeQueue(clock)
    handlers = {
        DISTILL_JOB_KIND: HandlerRegistration(
            _chain(clock, queue, FakeTurns(30), FakeExtractor()),
            timeout_seconds=HANDLER_TIMEOUT_SECONDS,
        )
    }
    seed_distill_chain(repository=queue, delay_seconds=0, enabled=True)

    for _ in range(12):
        poll_once(repository=queue, handlers=handlers)
        clock.advance(15)
        open_rows = queue.of_kind(DISTILL_JOB_KIND, "queued", "running")
        assert len(open_rows) == 1, "two distill rows means two competitors for one Ollama"


def test_a_laptop_asleep_for_hours_claims_the_stale_row_once_without_bursting(clock):
    queue = FakeQueue(clock)
    turns, extractor = FakeTurns(5), FakeExtractor()
    handlers = {
        DISTILL_JOB_KIND: HandlerRegistration(
            _chain(clock, queue, turns, extractor), timeout_seconds=HANDLER_TIMEOUT_SECONDS
        )
    }
    seed_distill_chain(repository=queue, delay_seconds=0, enabled=True)

    clock.advance(8 * 60 * 60)  # the machine was off all night
    poll_once(repository=queue, handlers=handlers)

    # One ripe row, claimed once. No catch-up burst for the missed ticks.
    assert len(extractor.calls) == 1
    assert len(queue.of_kind(DISTILL_JOB_KIND, "queued", "running")) == 1


# --------------------------------------------------------------------------
# Failure isolation.
# --------------------------------------------------------------------------


def test_a_raising_extraction_enqueues_no_successor_at_all(clock):
    """The successor is enqueued last, so a raise means there is no successor.

    This is the whole reason the ordering inside ``handle`` is load-bearing. If
    the successor were scheduled before extraction, a failing turn would leave
    the retried row *and* a fresh link — a fork on every failure.
    """
    queue = FakeQueue(clock)
    seed = queue.enqueue(DISTILL_JOB_KIND, {"reason": "seed"})

    with pytest.raises(RuntimeError):
        _chain(clock, queue, FakeTurns(3), FakeExtractor(explode=True))(seed)

    assert [row["id"] for row in queue.of_kind(DISTILL_JOB_KIND)] == [seed.id]


def test_a_raising_extraction_never_leaves_two_open_rows_on_any_retry(clock):
    """Not "one row afterwards" — one row after *every* attempt, to the end."""
    queue = FakeQueue(clock)
    handlers = {
        DISTILL_JOB_KIND: HandlerRegistration(
            _chain(clock, queue, FakeTurns(3), FakeExtractor(explode=True)),
            timeout_seconds=HANDLER_TIMEOUT_SECONDS,
        )
    }
    seed_distill_chain(repository=queue, delay_seconds=0, enabled=True)

    for _ in range(6):
        poll_once(repository=queue, handlers=handlers)
        clock.advance(600)
        assert len(queue.of_kind(DISTILL_JOB_KIND, "queued", "running")) <= 1

    assert queue.of_kind(DISTILL_JOB_KIND, "dead_letter")


def test_a_timeout_after_the_successor_is_enqueued_does_not_fork_the_chain(clock):
    """A stalled successor enqueue plus the poller's own timeout makes two chains.

    The delay is injected through the handler's own ``enqueue_successor`` seam,
    which is what a hosted-queue write stalling looks like from the poller's
    side. Everything else here is the shipped ``poll_once`` path.
    """
    queue = FakeQueue(clock)
    released = threading.Event()

    def stalled_schedule(delay_seconds: float, reason: str, *, may_write=None) -> None:
        # The stall sits between the handler deciding to enqueue and the row
        # actually landing — which is the window the poller's timeout falls
        # into. ``may_write`` is forwarded rather than dropped precisely so the
        # guard is evaluated on the far side of the stall, at the write itself.
        time.sleep(0.5)
        distill_handler._enqueue_successor(
            delay_seconds, reason, repository=queue, may_write=may_write
        )
        released.set()

    handlers = {
        DISTILL_JOB_KIND: HandlerRegistration(
            _chain(
                clock,
                queue,
                FakeTurns(3),
                FakeExtractor(),
                enqueue_successor=stalled_schedule,
            ),
            timeout_seconds=0.05,
        )
    }
    seed_distill_chain(repository=queue, delay_seconds=0, enabled=True)

    poll_once(repository=queue, handlers=handlers)  # gives up, re-queues the row
    assert released.wait(10.0), "the abandoned thread never finished its enqueue"

    assert len(queue.of_kind(DISTILL_JOB_KIND, "queued", "running")) == 1


def test_a_misconfigured_extraction_timeout_is_rejected_before_a_distill_job_runs(
    clock, monkeypatch
):
    monkeypatch.setenv("OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS", "9999")
    queue = FakeQueue(clock)

    with pytest.raises(ValueError):
        _chain(clock, queue, FakeTurns(3), FakeExtractor())(
            queue.enqueue(DISTILL_JOB_KIND, {})
        )


def test_a_failed_extraction_leaves_the_turn_undistilled_and_one_row_queued(clock):
    queue = FakeQueue(clock)
    turns, extractor = FakeTurns(3), FakeExtractor(explode=True)
    handlers = {
        DISTILL_JOB_KIND: HandlerRegistration(
            _chain(clock, queue, turns, extractor), timeout_seconds=HANDLER_TIMEOUT_SECONDS
        )
    }
    seed_distill_chain(repository=queue, delay_seconds=0, enabled=True)

    poll_once(repository=queue, handlers=handlers)

    assert len(turns.remaining) == 3
    # The claimed row went back to queued via the poller's retry path; no
    # successor was enqueued alongside it, so the chain did not duplicate.
    assert len(queue.of_kind(DISTILL_JOB_KIND, "queued", "running")) == 1


def test_a_failing_chain_dead_letters_rather_than_retrying_forever(clock):
    queue = FakeQueue(clock)
    handlers = {
        DISTILL_JOB_KIND: HandlerRegistration(
            _chain(clock, queue, FakeTurns(3), FakeExtractor(explode=True)),
            timeout_seconds=HANDLER_TIMEOUT_SECONDS,
        )
    }
    seed_distill_chain(repository=queue, delay_seconds=0, enabled=True)

    for _ in range(6):
        poll_once(repository=queue, handlers=handlers)
        clock.advance(600)

    assert queue.of_kind(DISTILL_JOB_KIND, "dead_letter")
    assert queue.of_kind(DISTILL_JOB_KIND, "queued", "running") == []


def test_both_handles_are_closed_even_when_extraction_fails(clock):
    queue = FakeQueue(clock)
    turns, extractor = FakeTurns(3), FakeExtractor(explode=True)

    with pytest.raises(RuntimeError):
        _chain(clock, queue, turns, extractor)(queue.enqueue(DISTILL_JOB_KIND, {}))

    assert turns.closed == 1
    assert extractor.closed == 1


def test_an_idle_tick_never_opens_the_extraction_model(clock):
    queue = FakeQueue(clock)
    opened: list[str] = []
    handle = build_distill_memory_handler(
        open_memory=lambda *a, **k: FakeTurns(0),
        open_extractor=lambda *a, **k: opened.append("extractor") or FakeExtractor(),
        repository=queue,
        enabled=True,
    )

    handle(queue.enqueue(DISTILL_JOB_KIND, {}))

    # Loading the 8B model just to discover there is nothing to do would be a
    # recurring, pointless grab at the one serial Ollama.
    assert opened == []


# --------------------------------------------------------------------------
# Seeding.
# --------------------------------------------------------------------------


def test_seeding_an_empty_queue_starts_the_chain(clock):
    queue = FakeQueue(clock)

    assert seed_distill_chain(repository=queue, enabled=True) is True
    assert len(queue.of_kind(DISTILL_JOB_KIND)) == 1


def test_seeding_is_idempotent_across_executor_restarts(clock):
    queue = FakeQueue(clock)

    seed_distill_chain(repository=queue, enabled=True)
    for _ in range(5):
        assert seed_distill_chain(repository=queue, enabled=True) is False

    assert len(queue.of_kind(DISTILL_JOB_KIND)) == 1


def test_seeding_skips_a_chain_that_is_currently_running(clock):
    queue = FakeQueue(clock)
    queue.enqueue(DISTILL_JOB_KIND, {})
    queue.claim_next()

    assert seed_distill_chain(repository=queue, enabled=True) is False


def test_seeding_reseeds_once_a_previous_chain_has_finished(clock):
    queue = FakeQueue(clock)
    seed_distill_chain(repository=queue, enabled=True)
    queue.rows[0]["status"] = "done"

    assert seed_distill_chain(repository=queue, enabled=True) is True


def test_the_seed_row_caps_its_attempts_so_a_stuck_chain_cannot_retry_forever(clock):
    queue = FakeQueue(clock)
    seed_distill_chain(repository=queue, enabled=True)

    assert queue.of_kind(DISTILL_JOB_KIND)[0]["max_attempts"] == distill_handler.DISTILL_MAX_ATTEMPTS


# --------------------------------------------------------------------------
# The kill switch, and the timeout ordering that closes the abandoned-thread
# hazard.
# --------------------------------------------------------------------------


def test_the_chain_is_on_by_default():
    assert distillation_enabled({}) is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF"])
def test_the_chain_can_be_switched_off(value):
    assert distillation_enabled({"JARVIS_DISTILL": value}) is False


def test_a_disabled_chain_does_nothing_and_stops_re_enqueuing(clock):
    queue = FakeQueue(clock)
    turns, extractor = FakeTurns(5), FakeExtractor()
    seed = queue.enqueue(DISTILL_JOB_KIND, {})

    _chain(clock, queue, turns, extractor, enabled=False)(seed)

    assert extractor.calls == []
    assert [row["id"] for row in queue.of_kind(DISTILL_JOB_KIND)] == [seed.id]


def test_a_disabled_chain_is_not_seeded(clock):
    queue = FakeQueue(clock)
    assert seed_distill_chain(repository=queue, enabled=False) is False
    assert queue.rows == []


def test_the_registered_handler_timeout_exceeds_the_ollama_extraction_timeout():
    """A wedged model must raise inside the thread before the poller gives up.

    The poller abandons a timed-out handler thread rather than killing it, and
    an abandoned distill thread would still hold the one local Ollama while the
    next job ran. Ordering the two timeouts is what makes that impossible.
    """
    assert extraction_timeout_seconds({}) < HANDLER_TIMEOUT_SECONDS
    assert_timeouts_ordered(environ={})


def test_an_extraction_timeout_above_the_handler_timeout_is_rejected():
    with pytest.raises(ValueError):
        assert_timeouts_ordered(environ={"OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS": "9999"})


@pytest.mark.parametrize(
    "raw,expected", [("", 90.0), ("120", 120.0), ("nonsense", 90.0), ("-5", 90.0)]
)
def test_the_extraction_timeout_is_read_the_same_way_mem0_reads_it(raw, expected):
    assert extraction_timeout_seconds({"OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS": raw}) == expected


def test_turns_per_job_must_be_positive():
    with pytest.raises(ValueError):
        build_distill_memory_handler(turns_per_job=0)


def test_the_queue_payload_never_carries_conversation_content(clock):
    queue = FakeQueue(clock)
    turns = FakeTurns(3)
    _chain(clock, queue, turns, FakeExtractor())(queue.enqueue(DISTILL_JOB_KIND, {}))

    for row in queue.of_kind(DISTILL_JOB_KIND):
        assert set(row["payload"]) <= {"reason"}
