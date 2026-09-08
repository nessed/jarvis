"""The reply-latency line: what it says, what it must never say."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from executor.latency import (
    LINE_PREFIX,
    ReplySpans,
    mark_claimed,
    take_claimed_at,
)


class FakeClock:
    """A monotonic clock that only moves when a test says so."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _spans(clock: FakeClock, **kwargs) -> ReplySpans:
    return ReplySpans("job-1", "whatsapp_webhook", clock=clock, **kwargs)


class TestSpans:
    def test_a_stage_is_recorded_in_milliseconds(self) -> None:
        clock = FakeClock()
        spans = _spans(clock)

        with spans.stage("model"):
            clock.advance(3.9)

        assert "model_ms=3900" in spans.render()

    def test_stages_are_rendered_in_the_order_they_happen(self) -> None:
        clock = FakeClock()
        spans = _spans(clock)
        for stage in ("remember", "model", "recall", "classify", "cue"):
            with spans.stage(stage):
                clock.advance(0.1)

        rendered = spans.render()
        positions = [rendered.index(f"{s}_ms=") for s in ("cue", "classify", "recall", "model", "remember")]
        assert positions == sorted(positions)

    def test_an_unknown_stage_is_appended_rather_than_dropped(self) -> None:
        clock = FakeClock()
        spans = _spans(clock)
        with spans.stage("something_new"):
            clock.advance(0.5)

        assert "something_new_ms=500" in spans.render()

    def test_a_failing_stage_is_still_timed_and_the_error_still_raises(self) -> None:
        clock = FakeClock()
        spans = _spans(clock)

        with pytest.raises(RuntimeError):
            with spans.stage("model"):
                clock.advance(300.0)
                raise RuntimeError("provider hung")

        assert "model_ms=300000" in spans.render()

    def test_total_covers_the_queue_wait_plus_everything_since(self) -> None:
        clock = FakeClock()
        created = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)
        spans = _spans(clock, created_at=created, claimed_at=created + timedelta(seconds=1.2))

        with spans.stage("model"):
            clock.advance(4.0)

        assert "queue_wait_ms=1200" in spans.render()
        assert "total_ms=5200" in spans.render()

    def test_clock_skew_cannot_produce_a_negative_queue_wait(self) -> None:
        created = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)
        spans = _spans(FakeClock(), created_at=created, claimed_at=created - timedelta(seconds=5))

        assert "queue_wait_ms=0" in spans.render()

    def test_timings_from_the_service_are_folded_in(self) -> None:
        spans = _spans(FakeClock())
        spans.update({"classify": 2.1, "recall": 0.52, "model": 3.9})

        rendered = spans.render()
        assert "classify_ms=2100" in rendered
        assert "recall_ms=520" in rendered
        assert "model_ms=3900" in rendered

    def test_the_line_carries_no_message_text_only_names_and_numbers(self) -> None:
        clock = FakeClock()
        spans = ReplySpans("job-1", "whatsapp_webhook", clock=clock)
        spans.update({"model": 1.0})

        rendered = spans.render()
        assert rendered.startswith(f"{LINE_PREFIX} job=job-1 kind=whatsapp_webhook")
        for token in rendered.split():
            key, _, value = token.partition("=")
            if key in {LINE_PREFIX, "job", "kind"} or not value:
                continue
            assert value.isdigit(), f"non-numeric field in the latency line: {token}"

    def test_emit_logs_once_even_if_called_twice(self, caplog) -> None:
        spans = _spans(FakeClock())
        with caplog.at_level(logging.INFO, logger="test-latency"):
            log = logging.getLogger("test-latency")
            first = spans.emit(log)
            second = spans.emit(log)

        assert first == second
        assert len([r for r in caplog.records if LINE_PREFIX in r.getMessage()]) == 1


class TestClaimHandoff:
    def test_the_poller_hands_the_handler_a_claim_time(self) -> None:
        when = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)
        mark_claimed("job-handoff", now=when)

        assert take_claimed_at("job-handoff") == when
        # Popped, so a redelivery of the same id cannot reuse a stale stamp.
        assert take_claimed_at("job-handoff") is None

    def test_an_unclaimed_job_falls_back_to_now_rather_than_failing(self) -> None:
        created = datetime.now(UTC) - timedelta(seconds=2)
        job = type("J", (), {"id": "job-never-marked", "kind": "whatsapp_webhook", "created_at": created})()

        spans = ReplySpans.for_job(job)

        queue_wait = spans.stages["queue_wait"]
        assert 1.0 <= queue_wait <= 30.0

    def test_the_claim_table_cannot_grow_without_bound(self) -> None:
        for index in range(200):
            mark_claimed(f"job-{index}", now=datetime.now(UTC))

        from executor.latency import _MAX_TRACKED_CLAIMS, _claimed_at

        assert len(_claimed_at) <= _MAX_TRACKED_CLAIMS

    def test_a_job_without_a_created_at_records_no_queue_wait(self) -> None:
        job = type("J", (), {"id": "job-x", "kind": "whatsapp_webhook", "created_at": None})()

        spans = ReplySpans.for_job(job)

        assert "queue_wait" not in spans.stages
        assert "queue_wait_ms=" not in spans.render()


class TestTimestampShapes:
    """A job rebuilt from captured JSON carries strings, not datetimes."""

    def test_an_iso_string_created_at_is_read(self) -> None:
        job = type("J", (), {
            "id": "job-str", "kind": "whatsapp_webhook",
            "created_at": "2026-09-08T12:00:00+00:00",
        })()
        claimed = datetime(2026, 9, 8, 12, 0, 3, tzinfo=UTC)
        mark_claimed("job-str", now=claimed)

        spans = ReplySpans.for_job(job)

        assert "queue_wait_ms=3000" in spans.render()

    def test_a_zulu_suffix_is_read_too(self) -> None:
        job = type("J", (), {
            "id": "job-z", "kind": "whatsapp_webhook", "created_at": "2026-09-08T12:00:00Z",
        })()
        mark_claimed("job-z", now=datetime(2026, 9, 8, 12, 0, 1, tzinfo=UTC))

        assert "queue_wait_ms=1000" in ReplySpans.for_job(job).render()

    def test_an_unreadable_timestamp_costs_the_queue_wait_not_the_reply(self) -> None:
        job = type("J", (), {"id": "job-bad", "kind": "whatsapp_webhook", "created_at": "not a date"})()

        spans = ReplySpans.for_job(job)

        assert "queue_wait" not in spans.stages
