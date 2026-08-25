"""Domain types and extension points for JARVIS's local memory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, Sequence


Metadata = dict[str, Any]


@dataclass(frozen=True)
class Fact:
    """A durable locally stored memory fact.

    ``id`` can be supplied by an importer to make a resumed ingest idempotent.
    ``metadata`` is intentionally opaque to the store so callers can retain
    source-specific context without putting personal raw data anywhere remote.
    """

    id: str
    text: str
    source: str
    created_at: datetime
    metadata: Metadata
    embedding_model: str | None = None


class VectorSearch(Protocol):
    """Optional semantic-search adapter to attach when sqlite-vec is available."""

    def search(self, query: str, *, limit: int = 10) -> Sequence[Fact]: ...
