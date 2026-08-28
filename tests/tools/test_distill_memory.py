from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from executor.heartbeat import DEFAULT_MAX_AGE_SECONDS
from memory.types import Fact
from tools.distill_memory import main


@pytest.fixture(autouse=True)
def _isolated_heartbeat(tmp_path: Path, monkeypatch) -> Path:
    """Point every test in this file at a throwaway marker.

    The repo's real ``.executor-heartbeat`` is written by a live executor. No
    test may read it: whether the suite passes would then depend on whether
    the executor happened to be running.
    """
    path = tmp_path / "heartbeat" / "absent"
    monkeypatch.setenv("JARVIS_EXECUTOR_HEARTBEAT", str(path))
    return path


def _fact(fact_id: str, text: str, *, role: str = "user", user_id: str = "923000000000") -> Fact:
    return Fact(
        id=fact_id,
        text=text,
        source=f"whatsapp:{user_id}",
        created_at=datetime.now(timezone.utc),
        metadata={"role": role, "user_id": user_id, "distilled": False},
    )


class FakeConversation:
    def __init__(self, facts: list[Fact]) -> None:
        self.facts = list(facts)
        self.marked: list[str] = []
        self.closed = False
        self.last_limit: int | None | str = "unset"

    def undistilled_turns(self, *, limit: int | None = None) -> list[Fact]:
        self.last_limit = limit
        return self.facts if limit is None else self.facts[:limit]

    def mark_distilled(self, fact: Fact) -> None:
        self.marked.append(fact.id)

    def close(self) -> None:
        self.closed = True


class FakeMem0:
    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_on = fail_on or set()
        self.closed = False

    def remember(self, text: str, *, user_id: str, **_kwargs) -> None:
        self.calls.append((text, user_id))
        if text in self.fail_on:
            raise RuntimeError("boom")

    def close(self) -> None:
        self.closed = True


def _fresh(heartbeat: Path) -> None:
    heartbeat.parent.mkdir(parents=True, exist_ok=True)
    heartbeat.write_text(str(time.time()), encoding="utf-8")


def _stale(heartbeat: Path) -> None:
    heartbeat.parent.mkdir(parents=True, exist_ok=True)
    heartbeat.write_text(str(time.time() - (DEFAULT_MAX_AGE_SECONDS + 100)), encoding="utf-8")


def _wire(monkeypatch, conversation: FakeConversation, mem0: FakeMem0 | None = None) -> dict:
    """Point the CLI's openers at fakes instead of a real database/Ollama."""
    calls: dict = {"conversation_db": [], "mem0_db": []}

    def fake_open_conversation_memory(database=None):
        calls["conversation_db"].append(database)
        return conversation

    def fake_open_local_mem0_memory(database=None):
        calls["mem0_db"].append(database)
        return mem0

    monkeypatch.setattr("tools.distill_memory.open_conversation_memory", fake_open_conversation_memory)
    monkeypatch.setattr("tools.distill_memory.open_local_mem0_memory", fake_open_local_mem0_memory)
    return calls


def _fail_if_anything_runs(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("distillation work started despite the liveness guard")

    monkeypatch.setattr("tools.distill_memory.open_conversation_memory", boom)
    monkeypatch.setattr("tools.distill_memory.open_local_mem0_memory", boom)


def _fail_if_mem0_opens(monkeypatch, conversation: FakeConversation) -> None:
    monkeypatch.setattr("tools.distill_memory.open_conversation_memory", lambda database=None: conversation)

    def boom(*args, **kwargs):
        raise AssertionError("--dry-run must never open Mem0")

    monkeypatch.setattr("tools.distill_memory.open_local_mem0_memory", boom)


# --- heartbeat guard -----------------------------------------------------


def test_main_refuses_to_start_while_the_executor_is_polling(
    monkeypatch, caplog, _isolated_heartbeat: Path
) -> None:
    _fresh(_isolated_heartbeat)
    _fail_if_anything_runs(monkeypatch)

    exit_code = main([])

    assert exit_code == 2
    assert "executor is running" in caplog.text


def test_force_runs_even_while_the_executor_is_polling(monkeypatch, _isolated_heartbeat: Path) -> None:
    _fresh(_isolated_heartbeat)
    conversation = FakeConversation([_fact("1", "hello")])
    mem0 = FakeMem0()
    calls = _wire(monkeypatch, conversation, mem0)

    exit_code = main(["--force"])

    assert exit_code == 0
    assert calls["mem0_db"] == [None]
    assert conversation.marked == ["1"]


def test_a_stale_heartbeat_does_not_block_a_run(monkeypatch, _isolated_heartbeat: Path) -> None:
    _stale(_isolated_heartbeat)
    conversation = FakeConversation([_fact("1", "hello")])
    mem0 = FakeMem0()
    _wire(monkeypatch, conversation, mem0)

    exit_code = main([])

    assert exit_code == 0
    assert conversation.marked == ["1"]


def test_a_missing_heartbeat_file_does_not_block_a_run(monkeypatch, _isolated_heartbeat: Path) -> None:
    assert not _isolated_heartbeat.exists()
    conversation = FakeConversation([_fact("1", "hello")])
    mem0 = FakeMem0()
    _wire(monkeypatch, conversation, mem0)

    exit_code = main([])

    assert exit_code == 0
    assert conversation.marked == ["1"]


def test_a_dry_run_is_never_blocked_by_a_live_executor(
    monkeypatch, caplog, _isolated_heartbeat: Path
) -> None:
    _fresh(_isolated_heartbeat)
    conversation = FakeConversation([_fact("1", "hello world")])
    _fail_if_mem0_opens(monkeypatch, conversation)

    with caplog.at_level("INFO"):
        exit_code = main(["--dry-run"])

    assert exit_code == 0
    assert "would distill" in caplog.text
    assert conversation.marked == []


# --- distillation behaviour -----------------------------------------------


def test_reports_nothing_to_distill_when_no_pending_turns(monkeypatch, caplog) -> None:
    conversation = FakeConversation([])
    _fail_if_mem0_opens(monkeypatch, conversation)

    with caplog.at_level("INFO"):
        exit_code = main([])

    assert exit_code == 0
    assert "nothing to distill" in caplog.text


def test_distills_pending_turns_and_marks_them(monkeypatch) -> None:
    conversation = FakeConversation([_fact("1", "one"), _fact("2", "two")])
    mem0 = FakeMem0()
    _wire(monkeypatch, conversation, mem0)

    exit_code = main([])

    assert exit_code == 0
    assert conversation.marked == ["1", "2"]
    assert [text for text, _ in mem0.calls] == ["User: one", "User: two"]


def test_a_failed_extraction_is_logged_and_does_not_stop_the_batch(monkeypatch, caplog) -> None:
    conversation = FakeConversation([_fact("1", "bad"), _fact("2", "good")])
    mem0 = FakeMem0(fail_on={"User: bad"})
    _wire(monkeypatch, conversation, mem0)

    with caplog.at_level("INFO"):
        exit_code = main([])

    # One succeeded, so the run is still a success; the failure is logged, not raised.
    assert exit_code == 0
    assert conversation.marked == ["2"]
    assert "failed" in caplog.text


def test_returns_failure_when_every_extraction_fails(monkeypatch) -> None:
    conversation = FakeConversation([_fact("1", "bad")])
    mem0 = FakeMem0(fail_on={"User: bad"})
    _wire(monkeypatch, conversation, mem0)

    exit_code = main([])

    assert exit_code == 1
    assert conversation.marked == []


def test_limit_is_passed_through_to_undistilled_turns(monkeypatch) -> None:
    conversation = FakeConversation([_fact("1", "one")])
    mem0 = FakeMem0()
    _wire(monkeypatch, conversation, mem0)

    main(["--limit", "3"])

    assert conversation.last_limit == 4  # distill_turns fetches one extra to peek "more_pending"


def test_database_argument_reaches_both_openers(monkeypatch) -> None:
    conversation = FakeConversation([_fact("1", "one")])
    mem0 = FakeMem0()
    calls = _wire(monkeypatch, conversation, mem0)

    main(["--database", "custom.db"])

    assert calls["conversation_db"] == ["custom.db"]
    assert calls["mem0_db"] == ["custom.db"]


def test_conversation_memory_is_closed_even_when_mem0_is_never_opened(monkeypatch) -> None:
    conversation = FakeConversation([])
    _fail_if_mem0_opens(monkeypatch, conversation)

    main([])

    assert conversation.closed is True
