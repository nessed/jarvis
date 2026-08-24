"""Local sqlite-vec index for durable memory-fact identifiers.

The fact store remains the sole owner of raw fact text.  This module stores
only stable fact IDs plus their embedding vectors, and intentionally keeps the
pre-1.0 sqlite-vec SQL boundary in one place.
"""

from __future__ import annotations

import math
from pathlib import Path
import sqlite3
from typing import Sequence

import sqlite_vec


class SQLiteVecIndex:
    """A local persistent nearest-neighbour index keyed by stable fact IDs."""

    def __init__(self, database_path: str | Path = "memory.db", *, dimensions: int) -> None:
        if isinstance(dimensions, bool) or not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError("dimensions must be a positive integer")
        self.path = Path(database_path)
        self.dimensions = dimensions
        self._connection: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Open the local database and create this index's tables."""
        if self._connection is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            _load_sqlite_vec(connection)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS vector_fact_ids (
                    vector_rowid INTEGER PRIMARY KEY,
                    fact_id TEXT NOT NULL UNIQUE CHECK (length(trim(fact_id)) > 0)
                );
                """
            )
            connection.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS fact_vectors USING vec0(embedding float[{self.dimensions}])"
            )
            connection.commit()
        except Exception:
            connection.close()
            raise
        self._connection = connection

    def close(self) -> None:
        """Close the local SQLite connection if it is open."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "SQLiteVecIndex":
        self.initialize()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def upsert(self, fact_id: str, vector: Sequence[float]) -> None:
        """Create or replace the vector for one durable fact identifier."""
        identifier = _required_fact_id(fact_id)
        encoded_vector = _encode_vector(vector, dimensions=self.dimensions)
        connection = self._require_connection()
        row = connection.execute(
            "SELECT vector_rowid FROM vector_fact_ids WHERE fact_id = ?", (identifier,)
        ).fetchone()
        if row is None:
            cursor = connection.execute("INSERT INTO vector_fact_ids (fact_id) VALUES (?)", (identifier,))
            rowid = cursor.lastrowid
            connection.execute("INSERT INTO fact_vectors (rowid, embedding) VALUES (?, ?)", (rowid, encoded_vector))
        else:
            connection.execute("UPDATE fact_vectors SET embedding = ? WHERE rowid = ?", (encoded_vector, row[0]))
        connection.commit()

    def search(self, vector: Sequence[float], *, limit: int = 10) -> list[tuple[str, float]]:
        """Return nearest fact IDs and sqlite-vec distances, nearest first."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        if limit == 0:
            return []
        encoded_vector = _encode_vector(vector, dimensions=self.dimensions)
        rows = self._require_connection().execute(
            """
            SELECT mapping.fact_id, vectors.distance
            FROM fact_vectors AS vectors
            JOIN vector_fact_ids AS mapping ON mapping.vector_rowid = vectors.rowid
            WHERE vectors.embedding MATCH ? AND k = ?
            ORDER BY vectors.distance ASC, mapping.fact_id ASC
            """,
            (encoded_vector, limit),
        ).fetchall()
        return [(str(row[0]), float(row[1])) for row in rows]

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("SQLiteVecIndex is not initialized; call initialize() first")
        return self._connection


def _load_sqlite_vec(connection: sqlite3.Connection) -> None:
    """Load only sqlite-vec, then immediately disable extension loading again."""
    connection.enable_load_extension(True)
    try:
        sqlite_vec.load(connection)
    finally:
        connection.enable_load_extension(False)


def _required_fact_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("fact_id must be a non-empty string")
    return value


def _encode_vector(vector: Sequence[float], *, dimensions: int) -> bytes:
    if isinstance(vector, (str, bytes)) or not isinstance(vector, Sequence):
        raise ValueError("vector must be a numeric sequence")
    if len(vector) != dimensions:
        raise ValueError(f"vector must contain exactly {dimensions} dimensions")
    values: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("vector values must be finite numeric values")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("vector values must be finite numeric values")
        values.append(number)
    return sqlite_vec.serialize_float32(values)
