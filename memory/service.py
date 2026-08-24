"""Local-only orchestration for durable semantic memory.

The service deliberately receives all of its dependencies.  It never creates a
network client or performs fact extraction itself, which keeps personal text on
the local embedding/index path selected by the application.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from memory.embeddings import EmbeddingProvider
from memory.types import Fact


class FactStore(Protocol):
    """The small durable-fact surface required by :class:`MemoryService`."""

    def remember(
        self,
        text: str,
        source: str,
        *,
        fact_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> Fact: ...

    def get(self, fact_id: str) -> Fact | None: ...

    def delete(self, fact_id: str) -> bool: ...


class VectorIndex(Protocol):
    """Vector-only index contract; raw fact text never belongs in the index."""

    def upsert(self, fact_id: str, vector: Sequence[float]) -> None: ...

    def search(self, query_vector: Sequence[float], *, limit: int = 10) -> Sequence[object]: ...


class MemoryService:
    """Store and recall local facts through injected local-only components."""

    def __init__(self, *, store: FactStore, embeddings: EmbeddingProvider, index: VectorIndex) -> None:
        self._store = store
        self._embeddings = embeddings
        self._index = index

    def remember(
        self,
        text: str,
        source: str,
        *,
        fact_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> Fact:
        """Embed, persist, then index one caller-approved fact.

        There is intentionally no LLM-based extraction here: callers provide
        the exact fact text and its source.  If indexing fails after storage,
        the newly-created fact is removed so it cannot become silently
        unretrievable.  Existing facts are never overwritten by this service.
        """
        vector = _one_embedding(self._embeddings, text)
        fact = self._store.remember(
            text,
            source,
            fact_id=fact_id,
            metadata=metadata,
            created_at=created_at,
        )
        try:
            self._index.upsert(fact.id, vector)
        except Exception:
            self._store.delete(fact.id)
            raise
        return fact

    def recall(self, query: str, *, limit: int = 10) -> list[Fact]:
        """Return live facts nearest to a local query embedding.

        Deleted or stale vector IDs are skipped, preserving index/store
        independence while preventing dead entries from leaking to callers.
        """
        _validate_text("query", query)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        if limit == 0:
            return []

        vector = _one_embedding(self._embeddings, query)
        matches = self._index.search(vector, limit=limit)
        facts: list[Fact] = []
        seen_ids: set[str] = set()
        for match in matches:
            fact_id = _match_fact_id(match)
            if fact_id is None or fact_id in seen_ids:
                continue
            seen_ids.add(fact_id)
            fact = self._store.get(fact_id)
            if fact is not None:
                facts.append(fact)
        return facts


def _one_embedding(provider: EmbeddingProvider, text: str) -> list[float]:
    _validate_text("text", text)
    vectors = provider.embed([text])
    if len(vectors) != 1:
        raise ValueError("embedding provider must return exactly one vector for one input")
    return vectors[0]


def _validate_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _match_fact_id(match: object) -> str | None:
    """Extract a stable ID from the index's minimal result shape.

    The index may return a string directly, a ``(fact_id, distance)`` tuple,
    or a value object carrying ``fact_id``.  Distances are deliberately
    ignored by this orchestration layer because index order is the ranking
    authority.
    """
    if isinstance(match, str):
        return match if match.strip() else None
    if isinstance(match, tuple) and len(match) == 2:
        fact_id, _distance = match
        return fact_id if isinstance(fact_id, str) and fact_id.strip() else None
    fact_id = getattr(match, "fact_id", None)
    return fact_id if isinstance(fact_id, str) and fact_id.strip() else None
