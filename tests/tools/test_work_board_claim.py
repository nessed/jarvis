from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[2] / "tools" / "work_board_claim.py"
SPEC = importlib.util.spec_from_file_location("work_board_claim", MODULE_PATH)
assert SPEC and SPEC.loader
board = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = board
SPEC.loader.exec_module(board)


def test_overlapping_file_claim_is_rejected(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    board.claim(state_dir=state_dir, role="CORE", work_item="one", files=["tools"], resources=[], stale_after_seconds=60)

    with pytest.raises(board.ClaimError, match=r"files: tools/work_board_claim.py"):
        board.claim(state_dir=state_dir, role="BUILD", work_item="two", files=["tools/work_board_claim.py"], resources=[], stale_after_seconds=60)


def test_distinct_claims_and_release(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    first = board.claim(state_dir=state_dir, role="CORE", work_item="one", files=["tools/a.py"], resources=[], stale_after_seconds=60)
    second = board.claim(state_dir=state_dir, role="BUILD", work_item="two", files=["tests/a.py"], resources=[], stale_after_seconds=60)

    assert [item.id for item in board.list_claims(state_dir=state_dir, stale_after_seconds=60)] == [first.id, second.id]
    assert board.release(state_dir=state_dir, claim_id=first.id, stale_after_seconds=60) == first
    assert [item.id for item in board.list_claims(state_dir=state_dir, stale_after_seconds=60)] == [second.id]


def test_duplicate_resource_is_rejected(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    board.claim(state_dir=state_dir, role="CORE", work_item="one", files=[], resources=["ollama"], stale_after_seconds=60)

    with pytest.raises(board.ClaimError, match=r"resources: ollama"):
        board.claim(state_dir=state_dir, role="BUILD", work_item="two", files=[], resources=["ollama"], stale_after_seconds=60)


def test_git_commit_resource_is_reserved_for_core(tmp_path: Path) -> None:
    with pytest.raises(board.ClaimError, match="reserved for the CORE role"):
        board.claim(state_dir=tmp_path / "state", role="BUILD", work_item="commit", files=[], resources=["git-commit"], stale_after_seconds=60)


def test_stale_claim_is_pruned_when_owner_is_gone(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    old = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    (state_dir / "claims.json").write_text(json.dumps({"claims": [{"id": "old", "role": "CORE", "work_item": "old", "files": ["tools/a.py"], "resources": [], "pid": 99999999, "created_at": old}]}), encoding="utf-8")

    fresh = board.claim(state_dir=state_dir, role="BUILD", work_item="fresh", files=["tools/a.py"], resources=[], stale_after_seconds=1)

    assert [item.id for item in board.list_claims(state_dir=state_dir, stale_after_seconds=1)] == [fresh.id]


def test_malformed_state_is_not_overwritten(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    state_path = state_dir / "claims.json"
    state_path.write_text("not json", encoding="utf-8")

    with pytest.raises(board.ClaimError, match="malformed"):
        board.claim(state_dir=state_dir, role="CORE", work_item="one", files=["tools/a.py"], resources=[], stale_after_seconds=60)

    assert state_path.read_text(encoding="utf-8") == "not json"
