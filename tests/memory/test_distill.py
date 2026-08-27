"""The shared distill loop: chunking, the mark-after-success invariant, errors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from memory.distill import DistillReport, distill_turns, preview
from memory.types import Fact


def _turn(index: int, *, text: str | None = None, user_id: str = "alice", role: str = "user") -> Fact:
    return Fact(
        id=f"turn-{index}",
        text=text or f"turn number {index}",
        source=f"whatsapp:{user_id}",
        created_at=datetime(2026, 8, 27, tzinfo=UTC) + timedelta(minutes=index),
        metadata={"user_id": user_id, "role": role, "distilled": False},
    )


class FakeTurns:
    """A turn store that honours ``limit`` and oldest-first ordering."""

    def __init__(self, turns: list[Fact]) -> None:
        self.turns = list(turns)
        self.distilled: list[str] = []
        self.limits: list[int | None] = []

    def undistilled_turns(self, *, limit: int | None = None) -> list[Fact]:
        self.limits.append(limit)
        remaining = [t for t in self.turns if t.id not in self.distilled]
        remaining.sort(key=lambda t: t.created_at)
        return remaining if limit is None else remaining[:limit]

    def mark_distilled(self, fact: Fact) -> None:
        self.distilled.append(fact.id)


class FakeExtractor:
    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_on = fail_on or set()

    def remember(self, text: str, **kwargs: object) -> None:
        self.calls.append((text, str(kwargs.get("user_id"))))
        for marker in self.fail_on:
            if marker in text:
                raise RuntimeError("extraction blew up")


def test_limit_of_one_extracts_exactly_one_turn_however_deep_the_backlog():
    turns = FakeTurns([_turn(i) for i in range(5)])
    extractor = FakeExtractor()

    report = distill_turns(turns, extractor, limit=1)

    assert len(extractor.calls) == 1
    assert report == DistillReport(attempted=1, distilled=1, failed=0, more_pending=True)


def test_the_peeked_extra_turn_sets_more_pending_but_is_never_extracted():
    turns = FakeTurns([_turn(0), _turn(1)])
    extractor = FakeExtractor()

    report = distill_turns(turns, extractor, limit=1)

    # limit + 1 is fetched purely to answer "is there a backlog".
    assert turns.limits == [2]
    assert report.more_pending is True
    assert len(extractor.calls) == 1
    assert turns.distilled == ["turn-0"]


def test_more_pending_is_false_once_the_backlog_is_exactly_drained():
    turns = FakeTurns([_turn(0)])
    extractor = FakeExtractor()

    report = distill_turns(turns, extractor, limit=1)

    assert report.more_pending is False
    assert report.did_work is True


def test_an_empty_store_does_no_work_and_reports_no_backlog():
    turns = FakeTurns([])
    extractor = FakeExtractor()

    report = distill_turns(turns, extractor, limit=1)

    assert extractor.calls == []
    assert report.did_work is False
    assert report.more_pending is False


def test_turns_are_taken_oldest_first():
    turns = FakeTurns([_turn(3), _turn(1), _turn(2)])
    extractor = FakeExtractor()

    distill_turns(turns, extractor, limit=1)

    assert turns.distilled == ["turn-1"]


def test_the_turn_is_marked_only_after_extraction_succeeds():
    turns = FakeTurns([_turn(0)])
    extractor = FakeExtractor(fail_on={"turn number 0"})

    with pytest.raises(RuntimeError):
        distill_turns(turns, extractor, limit=1)

    # Still eligible for the next pass rather than silently dropped.
    assert turns.distilled == []


def test_failures_propagate_by_default_so_the_queue_owns_the_retry():
    turns = FakeTurns([_turn(0)])
    extractor = FakeExtractor(fail_on={"turn number 0"})

    with pytest.raises(RuntimeError):
        distill_turns(turns, extractor, limit=1)


def test_an_on_error_callback_swallows_the_failure_and_continues_the_batch():
    turns = FakeTurns([_turn(0), _turn(1)])
    extractor = FakeExtractor(fail_on={"turn number 0"})
    seen: list[tuple[str, str]] = []

    report = distill_turns(
        turns,
        extractor,
        limit=2,
        on_error=lambda fact, exc: seen.append((fact.id, type(exc).__name__)),
    )

    assert seen == [("turn-0", "RuntimeError")]
    assert turns.distilled == ["turn-1"]
    assert report.attempted == 2
    assert report.distilled == 1
    assert report.failed == 1


def test_a_failed_turn_forces_more_pending_even_when_the_peek_saw_no_backlog():
    turns = FakeTurns([_turn(0)])
    extractor = FakeExtractor(fail_on={"turn number 0"})

    report = distill_turns(turns, extractor, limit=1, on_error=lambda fact, exc: None)

    # The turn is still undistilled, so there is genuinely more to do.
    assert report.more_pending is True


def test_role_and_user_id_are_carried_into_the_extraction_call():
    turns = FakeTurns([_turn(0, role="assistant", user_id="bob")])
    extractor = FakeExtractor()

    distill_turns(turns, extractor, limit=1)

    assert extractor.calls == [("Assistant: turn number 0", "bob")]


def test_a_turn_without_metadata_falls_back_to_user_and_jarvis():
    bare = Fact(
        id="turn-x",
        text="hello",
        source="whatsapp:someone",
        created_at=datetime(2026, 8, 27, tzinfo=UTC),
        metadata={},
    )
    turns = FakeTurns([bare])
    extractor = FakeExtractor()

    distill_turns(turns, extractor, limit=1)

    assert extractor.calls == [("User: hello", "jarvis")]


def test_no_limit_drains_the_whole_backlog_without_peeking():
    turns = FakeTurns([_turn(i) for i in range(4)])
    extractor = FakeExtractor()

    report = distill_turns(turns, extractor)

    assert turns.limits == [None]
    assert len(extractor.calls) == 4
    assert report.more_pending is False


@pytest.mark.parametrize("bad", [0, -1])
def test_a_non_positive_limit_is_rejected(bad):
    with pytest.raises(ValueError):
        distill_turns(FakeTurns([]), FakeExtractor(), limit=bad)


def test_on_distilled_reports_each_turn_with_a_duration():
    turns = FakeTurns([_turn(0), _turn(1)])
    extractor = FakeExtractor()
    seen: list[tuple[str, bool]] = []

    distill_turns(
        turns,
        extractor,
        limit=2,
        on_distilled=lambda fact, seconds: seen.append((fact.id, seconds >= 0.0)),
    )

    assert seen == [("turn-0", True), ("turn-1", True)]


def test_preview_collapses_whitespace_and_bounds_length():
    assert preview("a\n  b\tc") == "a b c"
    long = preview("x" * 200, width=10)
    assert len(long) == 10
    assert long.endswith("…")
