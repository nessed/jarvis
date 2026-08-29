from __future__ import annotations

from pathlib import Path

import pytest

from ingest.noise import ExclusionPattern
from memory.review import (
    delete_by_pattern,
    delete_fact,
    delete_facts,
    facts_matching_pattern,
    list_recent,
    open_review_store,
    search,
)
from memory.store import SQLiteFactStore
from memory.vector_index import SQLiteVecIndex


def _seed(path: Path, *, with_vectors: bool = False) -> None:
    store = SQLiteFactStore(path)
    store.initialize()
    store.remember("First note", "notes/a.md", fact_id="a")
    store.remember("Second note", "notes/b.md", fact_id="b")
    store.remember("A forwarded meme text", "notes/c.md", fact_id="c")
    store.close()
    if with_vectors:
        index = SQLiteVecIndex(path, dimensions=3, embedding_model="test-model")
        index.initialize()
        index.upsert("a", [1.0, 0.0, 0.0])
        index.upsert("b", [0.0, 1.0, 0.0])
        index.upsert("c", [0.0, 0.0, 1.0])
        index.close()


# --- open_review_store -----------------------------------------------------


def test_open_review_store_has_no_index_when_no_vector_was_ever_written(tmp_path: Path):
    path = tmp_path / "memory.db"
    _seed(path, with_vectors=False)

    review = open_review_store(path)
    try:
        assert review.index is None
    finally:
        review.close()


def test_open_review_store_opens_the_existing_index_identity(tmp_path: Path):
    path = tmp_path / "memory.db"
    _seed(path, with_vectors=True)

    review = open_review_store(path)
    try:
        assert review.index is not None
        assert review.index.dimensions == 3
        assert review.index.embedding_model == "test-model"
    finally:
        review.close()


def test_open_review_store_against_a_brand_new_path_has_no_index(tmp_path: Path):
    path = tmp_path / "fresh.db"

    review = open_review_store(path)
    try:
        assert review.index is None
        assert review.store.list_facts() == []
    finally:
        review.close()


# --- list_recent -----------------------------------------------------


def test_list_recent_pages_through_every_fact(tmp_path: Path):
    path = tmp_path / "memory.db"
    _seed(path)

    review = open_review_store(path)
    try:
        page = list_recent(review, limit=2)
        rest = list_recent(review, limit=2, offset=2)
        assert len(page) == 2
        assert len(rest) == 1
        assert {f.id for f in page} | {f.id for f in rest} == {"a", "b", "c"}
    finally:
        review.close()


def test_list_recent_filters_by_source(tmp_path: Path):
    path = tmp_path / "memory.db"
    _seed(path)

    review = open_review_store(path)
    try:
        facts = list_recent(review, source="notes/a.md", limit=10)
        assert [f.id for f in facts] == ["a"]
    finally:
        review.close()


def test_list_recent_rejects_non_positive_limit(tmp_path: Path):
    path = tmp_path / "memory.db"
    _seed(path)

    review = open_review_store(path)
    try:
        with pytest.raises(ValueError, match="limit"):
            list_recent(review, limit=0)
    finally:
        review.close()


def test_list_recent_rejects_a_negative_offset(tmp_path: Path):
    path = tmp_path / "memory.db"
    _seed(path)

    review = open_review_store(path)
    try:
        with pytest.raises(ValueError, match="offset"):
            list_recent(review, offset=-1)
    finally:
        review.close()


# --- search -----------------------------------------------------


def test_search_by_text_contains_is_case_insensitive(tmp_path: Path):
    path = tmp_path / "memory.db"
    _seed(path)

    review = open_review_store(path)
    try:
        facts = search(review, text_contains="FORWARDED")
        assert [f.id for f in facts] == ["c"]
    finally:
        review.close()


def test_search_by_source_only(tmp_path: Path):
    path = tmp_path / "memory.db"
    _seed(path)

    review = open_review_store(path)
    try:
        facts = search(review, source="notes/b.md")
        assert [f.id for f in facts] == ["b"]
    finally:
        review.close()


def test_search_requires_a_non_empty_text_contains_when_given(tmp_path: Path):
    path = tmp_path / "memory.db"
    _seed(path)

    review = open_review_store(path)
    try:
        with pytest.raises(ValueError, match="text_contains"):
            search(review, text_contains="   ")
    finally:
        review.close()


# --- delete_fact / delete_facts -----------------------------------------------------


def test_delete_fact_removes_the_store_row(tmp_path: Path):
    path = tmp_path / "memory.db"
    _seed(path)

    review = open_review_store(path)
    try:
        assert delete_fact(review, "a") is True
        assert review.store.get("a") is None
        assert delete_fact(review, "a") is False
    finally:
        review.close()


def test_delete_fact_also_removes_the_vector_index_entry(tmp_path: Path):
    path = tmp_path / "memory.db"
    _seed(path, with_vectors=True)

    review = open_review_store(path)
    try:
        assert delete_fact(review, "a") is True
        remaining_ids = {fact_id for fact_id, _ in review.index.search([1.0, 0.0, 0.0], limit=10)}
        assert "a" not in remaining_ids
    finally:
        review.close()

    # Reopen fresh to prove the deletion is durable on disk, not just in-memory state.
    review2 = open_review_store(path)
    try:
        remaining_ids = {fact_id for fact_id, _ in review2.index.search([1.0, 0.0, 0.0], limit=10)}
        assert "a" not in remaining_ids
        assert {"b", "c"} <= remaining_ids
    finally:
        review2.close()


def test_delete_fact_on_a_store_with_no_index_only_touches_the_store(tmp_path: Path):
    path = tmp_path / "memory.db"
    _seed(path, with_vectors=False)

    review = open_review_store(path)
    try:
        assert review.index is None
        assert delete_fact(review, "a") is True
        assert review.store.get("a") is None
    finally:
        review.close()


def test_delete_facts_deletes_a_batch_and_reports_per_id_existence(tmp_path: Path):
    path = tmp_path / "memory.db"
    _seed(path)

    review = open_review_store(path)
    try:
        results = delete_facts(review, ["a", "missing", "b"])
        assert results == {"a": True, "missing": False, "b": True}
        assert [f.id for f in review.store.list_facts()] == ["c"]
    finally:
        review.close()


# --- pattern-based deletion -----------------------------------------------------


def test_facts_matching_pattern_previews_without_deleting(tmp_path: Path):
    path = tmp_path / "memory.db"
    _seed(path)
    pattern = ExclusionPattern(kind="substring", value="forwarded", origin="<test>")

    review = open_review_store(path)
    try:
        matched = facts_matching_pattern(review, pattern)
        assert [f.id for f in matched] == ["c"]
        assert review.store.get("c") is not None
    finally:
        review.close()


def test_delete_by_pattern_removes_every_matching_fact(tmp_path: Path):
    path = tmp_path / "memory.db"
    _seed(path)
    pattern = ExclusionPattern(kind="substring", value="forwarded", origin="<test>")

    review = open_review_store(path)
    try:
        deleted = delete_by_pattern(review, pattern)
        assert [f.id for f in deleted] == ["c"]
        assert review.store.get("c") is None
        assert review.store.get("a") is not None
    finally:
        review.close()


def test_delete_by_pattern_with_no_matches_deletes_nothing(tmp_path: Path):
    path = tmp_path / "memory.db"
    _seed(path)
    pattern = ExclusionPattern(kind="substring", value="nothing matches this", origin="<test>")

    review = open_review_store(path)
    try:
        deleted = delete_by_pattern(review, pattern)
        assert deleted == []
        assert len(review.store.list_facts()) == 3
    finally:
        review.close()
