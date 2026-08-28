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


def test_initialize_migrates_existing_facts_missing_the_distilled_column(tmp_path):
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE facts (id TEXT PRIMARY KEY, text TEXT NOT NULL, source TEXT NOT NULL, metadata TEXT NOT NULL, "
            "created_at TEXT NOT NULL, embedding_model TEXT NOT NULL DEFAULT '')"
        )
        connection.execute(
            "INSERT INTO facts VALUES ('old', 'old generic fact', 'test', '{}', '2026-08-25T00:00:00+00:00', '')"
        )

    store = SQLiteFactStore(path)
    store.initialize()  # must not raise even though the pre-existing table has no `distilled` column

    assert "distilled" in {row[1] for row in sqlite3.connect(path).execute("PRAGMA table_info(facts)")}
    # A pre-existing row with no distilled state is neither "distilled" nor
    # "undistilled" -- it must not show up under either filter.
    assert store.list_facts(distilled=True) == []
    assert store.list_facts(distilled=False) == []
    assert [f.id for f in store.list_facts()] == ["old"]
    store.close()


def test_initialize_sets_wal_journal_mode_and_a_busy_timeout(tmp_path):
    path = tmp_path / "memory.db"
    store = SQLiteFactStore(path)
    store.initialize()

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    store.close()


def test_initialize_on_an_in_memory_database_does_not_raise_and_falls_back_off_wal():
    # SQLite has no on-disk file to write a WAL to for ":memory:", so it
    # silently keeps its "memory" journal mode instead of erroring -- this is
    # documented SQLite behaviour, not a bug in this store.
    store = SQLiteFactStore(":memory:")
    store.initialize()

    created = store.remember("in-memory fact", "notes/a.md")
    assert store.get(created.id) == created
    store.close()


def test_count_is_a_row_count_not_a_materialized_list(tmp_path):
    store = SQLiteFactStore(tmp_path / "memory.db")
    store.initialize()

    assert store.count() == 0
    store.remember("first", "notes/a.md", fact_id="a")
    store.remember("second", "notes/b.md", fact_id="b")
    store.remember("third", "notes/a.md", fact_id="c")

    assert store.count() == 3
    assert store.count(source="notes/a.md") == 2
    assert store.count(source="notes/missing.md") == 0
    store.close()


def test_list_facts_distilled_filter_is_a_tri_state_matching_metadata(tmp_path):
    store = SQLiteFactStore(tmp_path / "memory.db")
    store.initialize()

    pending = store.remember("pending turn", "whatsapp:u1", fact_id="pending", metadata={"distilled": False})
    done = store.remember("done turn", "whatsapp:u1", fact_id="done", metadata={"distilled": True})
    note = store.remember("a note with no distilled state", "notes", fact_id="note")

    assert store.list_facts(distilled=False) == [pending]
    assert store.list_facts(distilled=True) == [done]
    # A fact that never set the metadata key is not "distilled=False" either --
    # only the unfiltered call returns it.
    assert note not in store.list_facts(distilled=False)
    assert note not in store.list_facts(distilled=True)
    assert {f.id for f in store.list_facts()} == {"pending", "done", "note"}
    store.close()


def test_list_facts_oldest_first_with_a_small_limit_returns_the_true_oldest(tmp_path):
    store = SQLiteFactStore(tmp_path / "memory.db")
    store.initialize()
    base = datetime(2026, 8, 1, tzinfo=UTC)
    for i in range(5):
        store.remember(
            f"turn {i}",
            "whatsapp:u1",
            fact_id=f"t{i}",
            metadata={"distilled": False},
            created_at=base.replace(day=1 + i),
        )

    oldest_two = store.list_facts(distilled=False, oldest_first=True, limit=2)

    assert [f.id for f in oldest_two] == ["t0", "t1"]
    store.close()


def test_list_facts_with_distilled_filter_only_decodes_the_matching_rows(tmp_path, monkeypatch):
    # This is the actual claim behind the fix: the emptiness check the
    # distill chain runs every tick (limit=1) must not JSON-decode every
    # row's metadata to find one undistilled turn.
    store = SQLiteFactStore(tmp_path / "memory.db")
    store.initialize()
    for i in range(20):
        store.remember(f"already distilled {i}", "whatsapp:u1", fact_id=f"d{i}", metadata={"distilled": True})
    store.remember("still pending", "whatsapp:u1", fact_id="pending", metadata={"distilled": False})

    import memory.store as store_module

    decoded: list[str] = []
    original_loads = store_module.json.loads

    def counting_loads(raw):
        decoded.append(raw)
        return original_loads(raw)

    monkeypatch.setattr(store_module.json, "loads", counting_loads)

    result = store.list_facts(distilled=False, limit=1)

    assert [f.id for f in result] == ["pending"]
    # Only the one matching row's metadata blob was ever decoded, not all 21.
    assert len(decoded) == 1
    store.close()
