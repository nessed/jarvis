"""Local SQLite-backed durable memory facts.

This module deliberately has no embedding or network dependency.  A future
sqlite-vec adapter can implement :class:`memory.types.VectorSearch` alongside
this plain, portable fact store.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from memory.types import Fact, Metadata


_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL CHECK (length(trim(text)) > 0),
    source TEXT NOT NULL CHECK (length(trim(source)) > 0),
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    embedding_model TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS facts_source_created_at_idx
    ON facts (source, created_at DESC);
"""


class SQLiteFactStore:
    """A local-only fact store with explicit schema setup and safe CRUD APIs."""

    def __init__(self, database_path: str | Path = "memory.db") -> None:
        self.path = Path(database_path)
        self._connection: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Open the local database and create the durable facts schema."""
        if self._connection is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            connection.executescript(_SCHEMA)
            _migrate_embedding_model(connection)
            connection.commit()
        except Exception:
            connection.close()
            raise
        self._connection = connection

    def close(self) -> None:
        """Close the database connection if one is open."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "SQLiteFactStore":
        self.initialize()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def remember(
        self,
        text: str,
        source: str,
        *,
        fact_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
        embedding_model: str | None = None,
    ) -> Fact:
        """Insert one fact, preserving a caller-provided stable identifier."""
        normalized_text = _required_text("text", text)
        normalized_source = _required_text("source", source)
        identifier = _required_text("fact_id", fact_id) if fact_id is not None else str(uuid4())
        encoded_metadata = _encode_metadata(metadata)
        timestamp = _as_utc(created_at or datetime.now(UTC))
        model = _optional_model(embedding_model)
        fact = Fact(identifier, normalized_text, normalized_source, timestamp, json.loads(encoded_metadata), model)
        connection = self._require_connection()
        try:
            connection.execute(
                """
                INSERT INTO facts (id, text, source, metadata, created_at, embedding_model)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (fact.id, fact.text, fact.source, encoded_metadata, fact.created_at.isoformat(), model or ""),
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"fact already exists: {identifier}") from exc
        return fact

    def get(self, fact_id: str) -> Fact | None:
        """Return a fact by its stable ID, or ``None`` when it is absent."""
        identifier = _required_text("fact_id", fact_id)
        row = self._require_connection().execute(
            "SELECT id, text, source, metadata, created_at, embedding_model FROM facts WHERE id = ?", (identifier,)
        ).fetchone()
        return _fact_from_row(row) if row is not None else None

    def list_facts(self, *, source: str | None = None, limit: int | None = None) -> list[Fact]:
        """Retrieve stored facts, optionally restricted to one source."""
        if limit is not None and (isinstance(limit, bool) or limit < 0):
            raise ValueError("limit must be a non-negative integer")
        connection = self._require_connection()
        query = "SELECT id, text, source, metadata, created_at, embedding_model FROM facts"
        params: list[object] = []
        if source is not None:
            query += " WHERE source = ?"
            params.append(_required_text("source", source))
        query += " ORDER BY created_at DESC, id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        return [_fact_from_row(row) for row in connection.execute(query, params).fetchall()]

    def delete(self, fact_id: str) -> bool:
        """Delete a fact by ID and report whether a fact was removed."""
        identifier = _required_text("fact_id", fact_id)
        cursor = self._require_connection().execute("DELETE FROM facts WHERE id = ?", (identifier,))
        self._require_connection().commit()
        return cursor.rowcount == 1

    def update(
        self,
        fact_id: str,
        *,
        text: str | None = None,
        source: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        embedding_model: str | None = None,
    ) -> Fact:
        """Update an existing fact without changing its stable identifier."""
        current = self.get(fact_id)
        if current is None:
            raise KeyError(f"fact does not exist: {fact_id}")
        next_text = current.text if text is None else _required_text("text", text)
        next_source = current.source if source is None else _required_text("source", source)
        next_metadata = current.metadata if metadata is None else dict(metadata)
        encoded_metadata = _encode_metadata(next_metadata)
        model = current.embedding_model if embedding_model is None else _optional_model(embedding_model)
        self._require_connection().execute(
            "UPDATE facts SET text = ?, source = ?, metadata = ?, embedding_model = ? WHERE id = ?",
            (next_text, next_source, encoded_metadata, model or "", current.id),
        )
        self._require_connection().commit()
        return Fact(current.id, next_text, next_source, current.created_at, json.loads(encoded_metadata), model)

    def clear(self) -> None:
        """Remove all facts; used only by an explicit Mem0 collection reset."""
        self._require_connection().execute("DELETE FROM facts")
        self._require_connection().commit()

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("SQLiteFactStore is not initialized; call initialize() first")
        return self._connection


def _required_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _encode_metadata(metadata: Mapping[str, Any] | None) -> str:
    if metadata is None:
        return "{}"
    try:
        return json.dumps(dict(metadata), sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata must be JSON serializable") from exc


def _as_utc(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _optional_model(value: str | None) -> str | None:
    if value is None:
        return None
    return _required_text("embedding_model", value)


def _migrate_embedding_model(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(facts)")}
    if "embedding_model" not in columns:
        connection.execute("ALTER TABLE facts ADD COLUMN embedding_model TEXT NOT NULL DEFAULT ''")


def _fact_from_row(row: sqlite3.Row) -> Fact:
    timestamp = datetime.fromisoformat(row["created_at"])
    return Fact(
        id=row["id"],
        text=row["text"],
        source=row["source"],
        created_at=_as_utc(timestamp),
        metadata=json.loads(row["metadata"]),
        embedding_model=(row["embedding_model"] or None),
    )
