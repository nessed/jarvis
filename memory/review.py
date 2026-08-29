"""Blueprint 1.4's review/forget API: see what was remembered, delete what is wrong.

Built entirely on :class:`memory.store.SQLiteFactStore`'s existing public
surface (``list_facts``, ``get``, ``delete``) -- nothing here reaches into
``memory/store.py`` itself. This module never judges whether a fact is true;
it only lists, searches, and deletes on explicit instruction. Naming what to
delete is Ali's call, exactly as it is for ``ingest.noise``'s exclusion
patterns, which this module reuses for "delete by pattern".

On the Mem0 question: this codebase's Mem0 integration (``memory.mem0_wrapper
.SQLiteVecMem0Store``) has no separate remote or third-party vector database.
Every fact, whether it arrived through a live turn, a Mem0 extraction, or a
backfill, is a row in the same ``SQLiteFactStore`` table, with its embedding
(if any) as a row in :class:`memory.vector_index.SQLiteVecIndex` against the
*same* database file. ``delete_fact`` below removes both. A fact whose
embedding row is left behind would still occupy space in ``fact_vectors``,
but it could never be recalled again either way: both
``memory.service.MemoryService.recall`` and Mem0's own
``SQLiteVecMem0Store.search`` drop any index hit whose ``store.get(fact_id)``
comes back empty. Deleting both rows here is the completeness this module
guarantees, not a workaround for an unreachable second system -- there isn't
one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from ingest.noise import ExclusionPattern
from memory.store import SQLiteFactStore
from memory.types import Fact
from memory.vector_index import SQLiteVecIndex


@dataclass
class ReviewStore:
    """Owns the store and (when any vector has ever been written) the index."""

    store: SQLiteFactStore
    index: SQLiteVecIndex | None

    def close(self) -> None:
        if self.index is not None:
            self.index.close()
        self.store.close()

    def __enter__(self) -> "ReviewStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def open_review_store(database_path: str | Path = "memory.db") -> ReviewStore:
    """Open the fact store, plus its vector index only if one already exists.

    No embedding provider is opened and no Ollama call is made: review and
    forget are pattern/substring operations, not semantic search, so this can
    run even when the local model is not up. The index is opened read/write
    against whatever dimensions and embedding model it was already built
    with -- read directly off the on-disk identity row rather than guessed,
    so this never trips ``SQLiteVecIndex``'s drift guard.
    """
    path = Path(database_path)
    store = SQLiteFactStore(path)
    store.initialize()
    identity = _read_vector_index_identity(path)
    index = None
    if identity is not None:
        dimensions, embedding_model = identity
        index = SQLiteVecIndex(path, dimensions=dimensions, embedding_model=embedding_model)
        index.initialize()
    return ReviewStore(store=store, index=index)


def list_recent(
    review: ReviewStore,
    *,
    source: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[Fact]:
    """Page through facts, newest first, optionally restricted to one source."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    fetched = review.store.list_facts(source=source, limit=offset + limit)
    return fetched[offset : offset + limit]


def search(
    review: ReviewStore,
    *,
    text_contains: str | None = None,
    source: str | None = None,
    limit: int | None = None,
) -> list[Fact]:
    """Find facts by a case-insensitive text substring and/or exact source."""
    if text_contains is not None and not text_contains.strip():
        raise ValueError("text_contains must be a non-empty string when given")
    if limit is not None and (isinstance(limit, bool) or limit <= 0):
        raise ValueError("limit must be a positive integer when given")
    candidates = review.store.list_facts(source=source)
    if text_contains:
        needle = text_contains.lower()
        candidates = [fact for fact in candidates if needle in fact.text.lower()]
    return candidates if limit is None else candidates[:limit]


def delete_fact(review: ReviewStore, fact_id: str) -> bool:
    """Delete one fact and its vector-index entry (if any). Reports whether it existed.

    The vector row is removed first: a crash between the two deletes then
    leaves at worst a store row with no vector (already unrecallable via
    semantic search, same as today whenever indexing fails mid-``remember``),
    never a vector pointing at a store row that silently reappears.
    """
    if review.index is not None:
        review.index.delete(fact_id)
    return review.store.delete(fact_id)


def delete_facts(review: ReviewStore, fact_ids: Iterable[str]) -> dict[str, bool]:
    """Delete a batch of facts by id. Reports per-id whether a row existed."""
    return {fact_id: delete_fact(review, fact_id) for fact_id in fact_ids}


def facts_matching_pattern(review: ReviewStore, pattern: ExclusionPattern) -> list[Fact]:
    """Preview what :func:`delete_by_pattern` would remove, without deleting anything."""
    return [fact for fact in review.store.list_facts() if pattern.matches(text=fact.text, source=fact.source)]


def delete_by_pattern(review: ReviewStore, pattern: ExclusionPattern) -> list[Fact]:
    """Delete every fact currently matching ``pattern``. Irreversible; callers must confirm first.

    Retroactively applies the same pattern ``ingest.noise`` uses to keep new
    chunks from being stored, so naming a pattern cleans what is already
    stored as well as what arrives next.
    """
    matched = facts_matching_pattern(review, pattern)
    for fact in matched:
        delete_fact(review, fact.id)
    return matched


def _read_vector_index_identity(database_path: Path) -> tuple[int, str] | None:
    """Read the dimension/model a vector index was already built with, if any.

    Returns ``None`` when no vector has ever been written against this
    database -- a fresh install, or a store used only for plain (unembedded)
    facts -- since :class:`SQLiteVecIndex` requires a positive dimension to
    even open, and there is nothing to purge in that case.
    """
    if not database_path.exists():
        return None
    connection = sqlite3.connect(database_path)
    try:
        row = connection.execute(
            "SELECT dimensions, embedding_model FROM vector_index_identity WHERE singleton = 1"
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        connection.close()
    return (int(row[0]), str(row[1])) if row is not None else None
