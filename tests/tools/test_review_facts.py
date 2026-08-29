from __future__ import annotations

import time
from pathlib import Path

import pytest

from executor.heartbeat import DEFAULT_MAX_AGE_SECONDS
from memory.store import SQLiteFactStore
from tools.review_facts import main


@pytest.fixture(autouse=True)
def _isolated_heartbeat(tmp_path: Path, monkeypatch) -> Path:
    """Point every test in this file at a throwaway marker.

    The repo's real ``.executor-heartbeat`` is written by a live executor. No
    test may read it: whether the suite passes would then depend on whether
    the executor happened to be running.
    """
    path = tmp_path / "heartbeat" / "absent"
    monkeypatch.setenv("JARVIS_EXECUTOR_HEARTBEAT", str(path))
    return path


def _fresh(heartbeat: Path) -> None:
    heartbeat.parent.mkdir(parents=True, exist_ok=True)
    heartbeat.write_text(str(time.time()), encoding="utf-8")


def _stale(heartbeat: Path) -> None:
    heartbeat.parent.mkdir(parents=True, exist_ok=True)
    heartbeat.write_text(str(time.time() - (DEFAULT_MAX_AGE_SECONDS + 100)), encoding="utf-8")


def _seeded_db(tmp_path: Path) -> Path:
    path = tmp_path / "memory.db"
    store = SQLiteFactStore(path)
    store.initialize()
    store.remember("First note", "notes/a.md", fact_id="a")
    store.remember("Second note", "notes/b.md", fact_id="b")
    store.remember("A forwarded meme text", "notes/c.md", fact_id="c")
    store.close()
    return path


# --- list -----------------------------------------------------


def test_list_prints_every_fact(tmp_path: Path, caplog):
    db = _seeded_db(tmp_path)

    with caplog.at_level("INFO"):
        exit_code = main(["--database", str(db), "list"])

    assert exit_code == 0
    assert "First note" in caplog.text
    assert "Second note" in caplog.text


def test_list_filters_by_source(tmp_path: Path, caplog):
    db = _seeded_db(tmp_path)

    with caplog.at_level("INFO"):
        exit_code = main(["--database", str(db), "list", "--source", "notes/a.md"])

    assert exit_code == 0
    assert "First note" in caplog.text
    assert "Second note" not in caplog.text


def test_list_reports_when_nothing_is_found(tmp_path: Path, caplog):
    db = tmp_path / "empty.db"

    with caplog.at_level("INFO"):
        exit_code = main(["--database", str(db), "list"])

    assert exit_code == 0
    assert "no facts found" in caplog.text


# --- search -----------------------------------------------------


def test_search_by_text(tmp_path: Path, caplog):
    db = _seeded_db(tmp_path)

    with caplog.at_level("INFO"):
        exit_code = main(["--database", str(db), "search", "--text", "forwarded"])

    assert exit_code == 0
    assert "forwarded meme" in caplog.text
    assert "First note" not in caplog.text


def test_search_requires_text_or_source(tmp_path: Path, caplog):
    db = _seeded_db(tmp_path)

    with caplog.at_level("ERROR"):
        exit_code = main(["--database", str(db), "search"])

    assert exit_code == 2
    assert "requires --text and/or --source" in caplog.text


# --- forget: preview / dry-run -----------------------------------------------------


def test_forget_dry_run_previews_without_deleting_and_ignores_the_heartbeat(
    tmp_path: Path, caplog, _isolated_heartbeat: Path
):
    db = _seeded_db(tmp_path)
    _fresh(_isolated_heartbeat)

    with caplog.at_level("INFO"):
        exit_code = main(["--database", str(db), "forget", "a", "--dry-run"])

    assert exit_code == 0
    assert "would delete 1 fact" in caplog.text
    store = SQLiteFactStore(db)
    store.initialize()
    assert store.get("a") is not None
    store.close()


def test_forget_reports_when_nothing_matches(tmp_path: Path, caplog):
    db = _seeded_db(tmp_path)

    with caplog.at_level("INFO"):
        exit_code = main(["--database", str(db), "forget", "does-not-exist"])

    assert exit_code == 0
    assert "nothing to delete" in caplog.text


def test_forget_requires_either_ids_or_pattern(tmp_path: Path, caplog):
    db = _seeded_db(tmp_path)

    with caplog.at_level("ERROR"):
        exit_code = main(["--database", str(db), "forget"])

    assert exit_code == 2
    assert "either fact id(s) or --pattern" in caplog.text


def test_forget_rejects_both_ids_and_pattern(tmp_path: Path, caplog):
    db = _seeded_db(tmp_path)

    with caplog.at_level("ERROR"):
        exit_code = main(["--database", str(db), "forget", "a", "--pattern", "substring:x"])

    assert exit_code == 2
    assert "either fact id(s) or --pattern" in caplog.text


def test_forget_rejects_a_malformed_pattern(tmp_path: Path, caplog):
    db = _seeded_db(tmp_path)

    with caplog.at_level("ERROR"):
        exit_code = main(["--database", str(db), "forget", "--pattern", "not-a-spec"])

    assert exit_code == 2


# --- forget: heartbeat guard -----------------------------------------------------


def test_forget_refuses_to_start_while_the_executor_is_polling(
    tmp_path: Path, caplog, _isolated_heartbeat: Path
):
    db = _seeded_db(tmp_path)
    _fresh(_isolated_heartbeat)

    with caplog.at_level("INFO"):
        exit_code = main(["--database", str(db), "forget", "a", "--yes"])

    assert exit_code == 2
    assert "executor is running" in caplog.text
    store = SQLiteFactStore(db)
    store.initialize()
    assert store.get("a") is not None
    store.close()


def test_forget_force_deletes_even_while_the_executor_is_polling(
    tmp_path: Path, caplog, _isolated_heartbeat: Path
):
    db = _seeded_db(tmp_path)
    _fresh(_isolated_heartbeat)

    with caplog.at_level("INFO"):
        exit_code = main(["--database", str(db), "forget", "a", "--force", "--yes"])

    assert exit_code == 0
    store = SQLiteFactStore(db)
    store.initialize()
    assert store.get("a") is None
    store.close()


def test_forget_a_stale_heartbeat_does_not_block_deletion(
    tmp_path: Path, _isolated_heartbeat: Path
):
    db = _seeded_db(tmp_path)
    _stale(_isolated_heartbeat)

    exit_code = main(["--database", str(db), "forget", "a", "--yes"])

    assert exit_code == 0
    store = SQLiteFactStore(db)
    store.initialize()
    assert store.get("a") is None
    store.close()


# --- forget: confirmation -----------------------------------------------------


def test_forget_without_yes_prompts_and_aborts_when_declined(tmp_path: Path, caplog, monkeypatch):
    db = _seeded_db(tmp_path)
    monkeypatch.setattr("tools.review_facts._confirm", lambda prompt: False)

    with caplog.at_level("INFO"):
        exit_code = main(["--database", str(db), "forget", "a"])

    assert exit_code == 0
    assert "aborted" in caplog.text
    store = SQLiteFactStore(db)
    store.initialize()
    assert store.get("a") is not None
    store.close()


def test_forget_without_yes_deletes_when_confirmed(tmp_path: Path, monkeypatch):
    db = _seeded_db(tmp_path)
    monkeypatch.setattr("tools.review_facts._confirm", lambda prompt: True)

    exit_code = main(["--database", str(db), "forget", "a"])

    assert exit_code == 0
    store = SQLiteFactStore(db)
    store.initialize()
    assert store.get("a") is None
    store.close()


def test_forget_yes_skips_the_confirmation_prompt(tmp_path: Path, monkeypatch):
    db = _seeded_db(tmp_path)

    def boom(prompt):
        raise AssertionError("--yes must skip the confirmation prompt")

    monkeypatch.setattr("tools.review_facts._confirm", boom)

    exit_code = main(["--database", str(db), "forget", "a", "--yes"])

    assert exit_code == 0


# --- forget: by pattern -----------------------------------------------------


def test_forget_by_pattern_deletes_every_matching_fact(tmp_path: Path):
    db = _seeded_db(tmp_path)

    exit_code = main(["--database", str(db), "forget", "--pattern", "substring:forwarded", "--yes"])

    assert exit_code == 0
    store = SQLiteFactStore(db)
    store.initialize()
    assert store.get("c") is None
    assert store.get("a") is not None
    assert store.get("b") is not None
    store.close()


def test_forget_by_id_reports_unknown_ids_and_still_deletes_known_ones(tmp_path: Path, caplog):
    db = _seeded_db(tmp_path)

    with caplog.at_level("WARNING"):
        exit_code = main(["--database", str(db), "forget", "a", "does-not-exist", "--yes"])

    assert exit_code == 0
    assert "does-not-exist" in caplog.text
    store = SQLiteFactStore(db)
    store.initialize()
    assert store.get("a") is None
    store.close()
