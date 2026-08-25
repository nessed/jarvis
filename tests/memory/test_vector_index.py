from __future__ import annotations

import math
import sqlite3

import pytest

from memory.vector_index import SQLiteVecIndex


def test_index_persists_fact_ids_and_returns_nearest_distances(tmp_path):
    path = tmp_path / "memory.db"
    index = SQLiteVecIndex(path, dimensions=3)
    index.initialize()
    index.upsert("fact-a", [1, 0, 0])
    index.upsert("fact-b", [0, 1, 0])

    result = index.search([0.9, 0.1, 0], limit=2)

    assert [fact_id for fact_id, _ in result] == ["fact-a", "fact-b"]
    assert result[0][1] < result[1][1]
    assert all(math.isfinite(distance) for _, distance in result)
    index.close()

    reopened = SQLiteVecIndex(path, dimensions=3)
    reopened.initialize()
    assert [fact_id for fact_id, _ in reopened.search([0, 1, 0])] == ["fact-b", "fact-a"]
    reopened.close()


def test_upsert_replaces_vector_without_duplicating_stable_fact_id(tmp_path):
    index = SQLiteVecIndex(tmp_path / "memory.db", dimensions=2)
    index.initialize()
    index.upsert("stable-fact", [1, 0])
    index.upsert("stable-fact", [0, 1])

    assert index.search([0, 1]) == [("stable-fact", pytest.approx(0.0))]
    with sqlite3.connect(index.path) as connection:
        assert connection.execute("SELECT count(*) FROM vector_fact_ids").fetchone()[0] == 1
    index.close()


@pytest.mark.parametrize(
    ("dimensions", "message"),
    [(0, "positive"), (-1, "positive"), (True, "positive"), (1.5, "positive")],
)
def test_dimensions_must_be_explicit_positive_integer(tmp_path, dimensions, message):
    with pytest.raises(ValueError, match=message):
        SQLiteVecIndex(tmp_path / "memory.db", dimensions=dimensions)


def test_index_requires_initialization_and_validates_vectors_and_ids(tmp_path):
    index = SQLiteVecIndex(tmp_path / "memory.db", dimensions=2)
    with pytest.raises(RuntimeError, match="initialize"):
        index.search([0, 1])

    index.initialize()
    for vector, message in [([1], "exactly"), ([1, 2, 3], "exactly"), ([1, float("nan")], "finite"), ([1, True], "finite")]:
        with pytest.raises(ValueError, match=message):
            index.upsert("fact", vector)
    with pytest.raises(ValueError, match="fact_id"):
        index.upsert(" ", [1, 0])
    with pytest.raises(ValueError, match="limit"):
        index.search([1, 0], limit=-1)
    assert index.search([1, 0], limit=0) == []
    index.close()


def test_index_refuses_embedding_model_or_dimension_drift(tmp_path):
    path = tmp_path / "memory.db"
    index = SQLiteVecIndex(path, dimensions=2, embedding_model="nomic-embed-text")
    index.initialize()
    index.close()

    with pytest.raises(RuntimeError, match="model drift"):
        SQLiteVecIndex(path, dimensions=2, embedding_model="different-local-model").initialize()
    with pytest.raises(RuntimeError, match="dimension drift"):
        SQLiteVecIndex(path, dimensions=3, embedding_model="nomic-embed-text").initialize()


def test_index_refuses_pre_identity_vectors_when_a_model_is_configured(tmp_path):
    path = tmp_path / "memory.db"
    old = SQLiteVecIndex(path, dimensions=2)
    old.initialize()
    old.upsert("unidentified", [1, 0])
    old.close()

    with pytest.raises(RuntimeError, match="identity is missing"):
        SQLiteVecIndex(path, dimensions=2, embedding_model="nomic-embed-text").initialize()
