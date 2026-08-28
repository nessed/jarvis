from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from memory.conversation import (
    ConversationMemory,
    is_conversation_turn,
    turn_source,
)
from memory.types import Fact


class FakeStore:
    """Minimal FactStore: enough for turn round-trips without sqlite or Ollama."""

    def __init__(self) -> None:
        self.facts: dict[str, Fact] = {}
        self._n = 0

    def remember(self, text, source, *, fact_id=None, metadata=None, created_at=None):
        self._n += 1
        fact = Fact(
            id=fact_id or f"fact-{self._n}",
            text=text,
            source=source,
            created_at=created_at or datetime.now(UTC),
            metadata=dict(metadata or {}),
        )
        self.facts[fact.id] = fact
        return fact

    def get(self, fact_id):
        return self.facts.get(fact_id)

    def delete(self, fact_id):
        return self.facts.pop(fact_id, None) is not None

    def list_facts(self, *, source=None, distilled=None, limit=None, oldest_first=False):
        rows = [f for f in self.facts.values() if source is None or f.source == source]
        if distilled is not None:
            # Mirror SQLiteFactStore's tri-state: a fact that never set a
            # "distilled" metadata key matches neither True nor False.
            rows = [f for f in rows if "distilled" in f.metadata and bool(f.metadata["distilled"]) == distilled]
        rows.sort(key=lambda f: f.created_at, reverse=not oldest_first)
        return rows if limit is None else rows[:limit]

    def update(self, fact_id, *, text=None, source=None, metadata=None, embedding_model=None):
        current = self.facts[fact_id]
        updated = Fact(
            id=current.id,
            text=current.text if text is None else text,
            source=current.source if source is None else source,
            created_at=current.created_at,
            metadata=current.metadata if metadata is None else dict(metadata),
        )
        self.facts[fact_id] = updated
        return updated

    def close(self):
        pass


class FakeService:
    """Stands in for MemoryService: records writes, returns scripted recalls."""

    def __init__(self, store: FakeStore) -> None:
        self.store = store
        self.recall_returns: list[Fact] = []
        self.recall_calls: list[tuple[str, int]] = []

    def remember(self, text, source, *, fact_id=None, metadata=None, created_at=None):
        return self.store.remember(text, source, fact_id=fact_id, metadata=metadata, created_at=created_at)

    def recall(self, query, *, limit=10):
        self.recall_calls.append((query, limit))
        return list(self.recall_returns)


class FakeRuntime:
    def __init__(self) -> None:
        self.store = FakeStore()
        self.service = FakeService(self.store)
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture()
def memory() -> ConversationMemory:
    return ConversationMemory(FakeRuntime())


def _turn(text: str, *, user: str = "15550001111", role: str = "user", distilled: bool = False, age: int = 0) -> Fact:
    return Fact(
        id=f"id-{text}",
        text=text,
        source=turn_source(user),
        created_at=datetime.now(UTC) - timedelta(minutes=age),
        metadata={"role": role, "user_id": user, "distilled": distilled},
    )


class TestRememberTurn:
    def test_stores_the_turn_verbatim_with_role_and_user(self, memory: ConversationMemory) -> None:
        fact = memory.remember_turn("the workshop opens at nine", user_id="15550001111", role="user")

        assert fact.text == "the workshop opens at nine"
        assert fact.source == turn_source("15550001111")
        assert fact.metadata["role"] == "user"
        assert fact.metadata["user_id"] == "15550001111"

    def test_new_turns_start_undistilled(self, memory: ConversationMemory) -> None:
        fact = memory.remember_turn("something", user_id="u1", role="assistant")

        assert fact.metadata["distilled"] is False

    def test_rejects_an_unknown_role(self, memory: ConversationMemory) -> None:
        with pytest.raises(ValueError, match="role"):
            memory.remember_turn("text", user_id="u1", role="system")

    def test_rejects_a_blank_user_id(self, memory: ConversationMemory) -> None:
        with pytest.raises(ValueError, match="user_id"):
            memory.remember_turn("text", user_id="   ", role="user")


class TestRecall:
    def test_returns_this_conversations_turns(self, memory: ConversationMemory) -> None:
        mine = _turn("my own message", user="mine")
        memory.runtime.service.recall_returns = [mine]

        assert memory.recall("query", user_id="mine") == [mine]

    def test_excludes_another_conversations_turns(self, memory: ConversationMemory) -> None:
        memory.runtime.service.recall_returns = [_turn("someone else's message", user="theirs")]

        assert memory.recall("query", user_id="mine") == []

    def test_keeps_non_conversation_facts_regardless_of_user(self, memory: ConversationMemory) -> None:
        # Backfilled notes and distilled Mem0 memories belong to the machine's
        # owner, not to one thread, so they stay eligible.
        backfilled = Fact(
            id="n1",
            text="a note from the backfill",
            source="notes",
            created_at=datetime.now(UTC),
            metadata={},
        )
        memory.runtime.service.recall_returns = [backfilled]

        assert memory.recall("query", user_id="mine") == [backfilled]

    def test_overfetches_then_truncates_to_the_requested_limit(self, memory: ConversationMemory) -> None:
        memory.runtime.service.recall_returns = [_turn(f"m{i}", user="mine") for i in range(10)]

        result = memory.recall("query", user_id="mine", limit=3)

        assert len(result) == 3
        # The service must be asked for more than `limit`, because filtering
        # happens after nearest-neighbour ordering.
        [(_, asked)] = memory.runtime.service.recall_calls
        assert asked > 3

    def test_a_non_positive_limit_returns_nothing_without_searching(self, memory: ConversationMemory) -> None:
        assert memory.recall("query", user_id="mine", limit=0) == []
        assert memory.runtime.service.recall_calls == []


class TestDistillation:
    def test_undistilled_turns_excludes_distilled_and_non_turns(self, memory: ConversationMemory) -> None:
        memory.remember_turn("pending", user_id="u1", role="user")
        already = memory.remember_turn("already done", user_id="u1", role="user")
        memory.mark_distilled(already)
        memory.runtime.store.remember("a backfilled note", "notes")

        pending = memory.undistilled_turns()

        assert [f.text for f in pending] == ["pending"]

    def test_undistilled_turns_are_oldest_first(self, memory: ConversationMemory) -> None:
        store = memory.runtime.store
        store.remember("newer", turn_source("u1"), metadata={"distilled": False}, created_at=datetime.now(UTC))
        store.remember(
            "older",
            turn_source("u1"),
            metadata={"distilled": False},
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )

        assert [f.text for f in memory.undistilled_turns()] == ["older", "newer"]

    def test_mark_distilled_preserves_text_and_source(self, memory: ConversationMemory) -> None:
        fact = memory.remember_turn("keep me intact", user_id="u1", role="user")

        memory.mark_distilled(fact)

        stored = memory.runtime.store.get(fact.id)
        assert stored.text == "keep me intact"
        assert stored.source == turn_source("u1")
        assert stored.metadata["distilled"] is True
        assert stored.metadata["role"] == "user"

    def test_closing_closes_the_runtime(self, memory: ConversationMemory) -> None:
        with memory:
            pass

        assert memory.runtime.closed is True


def test_is_conversation_turn_distinguishes_turns_from_other_facts() -> None:
    assert is_conversation_turn(_turn("a message")) is True
    assert (
        is_conversation_turn(
            Fact(id="n", text="note", source="notes", created_at=datetime.now(UTC), metadata={})
        )
        is False
    )
