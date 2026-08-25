from __future__ import annotations

from datetime import UTC, datetime
import sqlite3

import pytest

from memory.store import SQLiteFactStore


def test_initialize_creates_plain_local_facts_schema(tmp_path):
    path = tmp_path / "memory.db"
    store = SQLiteFactStore(path)

    store.initialize()

    assert path.is_file()
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(facts)")}
    assert {"id", "text", "source", "metadata", "created_at"} <= columns
    store.close()


def test_remember_get_list_and_delete_with_stable_id_and_metadata(tmp_path):
    store = SQLiteFactStore(tmp_path / "memory.db")
    store.initialize()
    timestamp = datetime(2026, 8, 24, 12, 30, tzinfo=UTC)

    created = store.remember(
        "Prefers concise updates.",
        "notes/preferences.md",
        fact_id="fact-preference-1",
        metadata={"line": 8, "kind": "note"},
        created_at=timestamp,
    )

    assert created.id == "fact-preference-1"
    assert store.get(created.id) == created
    assert store.list_facts() == [created]
    assert store.delete(created.id) is True
    assert store.get(created.id) is None
    assert store.delete(created.id) is False
    store.close()


def test_list_facts_filters_by_source_and_returns_empty_retrieval(tmp_path):
    store = SQLiteFactStore(tmp_path / "memory.db")
    store.initialize()

    assert store.list_facts() == []
    first = store.remember("First note", "notes/a.md", fact_id="a")
    store.remember("Other note", "notes/b.md", fact_id="b")

    assert store.list_facts(source="notes/a.md") == [first]
    assert store.list_facts(source="notes/missing.md") == []
    assert store.list_facts(limit=0) == []
    store.close()


def test_store_requires_explicit_initialization_and_validates_inputs(tmp_path):
    store = SQLiteFactStore(tmp_path / "memory.db")
    with pytest.raises(RuntimeError, match="initialize"):
        store.list_facts()

    store.initialize()
    with pytest.raises(ValueError, match="text"):
        store.remember(" ", "notes/a.md")
    with pytest.raises(ValueError, match="source"):
        store.remember("text", "")
    with pytest.raises(ValueError, match="already exists"):
        store.remember("one", "notes/a.md", fact_id="same")
        store.remember("two", "notes/a.md", fact_id="same")
    with pytest.raises(ValueError, match="JSON serializable"):
        store.remember("text", "notes/a.md", metadata={"bad": {1}})
    with pytest.raises(ValueError, match="limit"):
        store.list_facts(limit=-1)
    store.close()


def test_initialize_migrates_existing_facts_with_embedding_model_column(tmp_path):
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE facts (id TEXT PRIMARY KEY, text TEXT NOT NULL, source TEXT NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO facts VALUES ('old', 'old generic fact', 'test', '{}', '2026-08-25T00:00:00+00:00')"
        )

    store = SQLiteFactStore(path)
    store.initialize()
    assert store.get("old").embedding_model is None
    assert "embedding_model" in {row[1] for row in sqlite3.connect(path).execute("PRAGMA table_info(facts)")}
    store.close()
