from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from memory.service import MemoryService
from memory.types import Fact


class FakeEmbeddings:
    def __init__(self, vectors: list[list[float]]) -> None:
        self.vectors = vectors
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return self.vectors.pop(0)


class FakeStore:
    def __init__(self) -> None:
        self.facts: dict[str, Fact] = {}
        self.deleted: list[str] = []

    def remember(self, text: str, source: str, *, fact_id: str | None = None, metadata=None, created_at=None) -> Fact:
        identifier = fact_id or "generated-id"
        fact = Fact(identifier, text, source, created_at or datetime.now(UTC), dict(metadata or {}))
        self.facts[identifier] = fact
        return fact

    def get(self, fact_id: str) -> Fact | None:
        return self.facts.get(fact_id)

    def delete(self, fact_id: str) -> bool:
        self.deleted.append(fact_id)
        return self.facts.pop(fact_id, None) is not None


@dataclass(frozen=True)
class Match:
    fact_id: str
    distance: float


class FakeIndex:
    def __init__(self, matches: list[object] | None = None, *, fail_upsert: bool = False) -> None:
        self.matches = matches or []
        self.fail_upsert = fail_upsert
        self.upserts: list[tuple[str, list[float]]] = []
        self.searches: list[tuple[list[float], int]] = []

    def upsert(self, fact_id: str, vector: list[float]) -> None:
        if self.fail_upsert:
            raise RuntimeError("index unavailable")
        self.upserts.append((fact_id, vector))

    def search(self, query_vector: list[float], *, limit: int = 10) -> list[object]:
        self.searches.append((query_vector, limit))
        return self.matches


def test_remember_embeds_persists_and_indexes_the_stable_id():
    embeddings = FakeEmbeddings([[[0.1, 0.2]]])
    store = FakeStore()
    index = FakeIndex()
    service = MemoryService(store=store, embeddings=embeddings, index=index)

    fact = service.remember("Ali prefers dark roast coffee", "notes/preferences.md", fact_id="coffee")

    assert fact.id == "coffee"
    assert embeddings.calls == [["Ali prefers dark roast coffee"]]
    assert store.get("coffee") == fact
    assert index.upserts == [("coffee", [0.1, 0.2])]


def test_remember_removes_new_fact_when_indexing_fails():
    store = FakeStore()
    service = MemoryService(store=store, embeddings=FakeEmbeddings([[[1.0]]]), index=FakeIndex(fail_upsert=True))

    with pytest.raises(RuntimeError, match="index unavailable"):
        service.remember("temporary fact", "notes/a.md", fact_id="temporary")

    assert store.get("temporary") is None
    assert store.deleted == ["temporary"]


def test_recall_embeds_query_hydrates_ranked_facts_and_skips_stale_ids():
    store = FakeStore()
    first = store.remember("First fact", "notes/a.md", fact_id="first")
    second = store.remember("Second fact", "notes/b.md", fact_id="second")
    index = FakeIndex([Match("second", 0.02), ("deleted", 0.04), "first", ("second", 0.06)])
    embeddings = FakeEmbeddings([[[0.3, 0.4]]])
    service = MemoryService(store=store, embeddings=embeddings, index=index)

    assert service.recall("what did I note?", limit=4) == [second, first]
    assert embeddings.calls == [["what did I note?"]]
    assert index.searches == [([0.3, 0.4], 4)]


@pytest.mark.parametrize("query, limit", [("", 1), ("query", -1), ("query", True)])
def test_recall_rejects_invalid_input_without_embedding(query: str, limit: int):
    embeddings = FakeEmbeddings([[[1.0]]])
    service = MemoryService(store=FakeStore(), embeddings=embeddings, index=FakeIndex())

    with pytest.raises(ValueError):
        service.recall(query, limit=limit)

    assert embeddings.calls == []


def test_recall_zero_limit_skips_embedding_and_index():
    embeddings = FakeEmbeddings([[[1.0]]])
    index = FakeIndex()
    service = MemoryService(store=FakeStore(), embeddings=embeddings, index=index)

    assert service.recall("anything", limit=0) == []
    assert embeddings.calls == []
    assert index.searches == []
