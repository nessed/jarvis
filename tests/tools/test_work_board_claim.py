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


# --- pruning is loud, and the CLI will not prune fresh claims ----------------
#
# Both cover the 30 August 2026 collision: a lane hit a conflict, re-ran with
# --stale-after-seconds 30, silently deleted a live lane's claims, and both
# then edited the same files. Pruning is age-only (_prune_stale's docstring),
# so a short window is not a staleness check -- it is a licence to delete
# whatever someone claimed seconds ago.


def _dead_claim(state_dir: Path, *, age_seconds: int, files: list[str]) -> None:
    created = (datetime.now(UTC) - timedelta(seconds=age_seconds)).isoformat()
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "claims.json").write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "doomed",
                        "role": "BUILD",
                        "work_item": "live-lane",
                        "files": files,
                        "resources": [],
                        "pid": 99999999,
                        "created_at": created,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_a_pruned_claim_is_announced_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = tmp_path / "state"
    _dead_claim(state_dir, age_seconds=120, files=["tools/a.py"])

    board.list_claims(state_dir=state_dir, stale_after_seconds=1)

    error_output = capsys.readouterr().err
    assert "doomed" in error_output
    assert "BUILD/live-lane" in error_output
    assert "tools/a.py" in error_output


def test_pruning_announcements_stay_off_the_parseable_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = tmp_path / "state"
    # Older than the floor, so the CLI can prune it without a below-floor window.
    _dead_claim(state_dir, age_seconds=400, files=["tools/a.py"])

    assert board.main(["--state-dir", str(state_dir), "--stale-after-seconds", "300", "list"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == []
    assert "doomed" in captured.err


def test_the_cli_refuses_a_window_short_enough_to_delete_live_claims(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = tmp_path / "state"
    fresh = board.claim(
        state_dir=state_dir,
        role="CORE",
        work_item="mine",
        files=["tools/a.py"],
        resources=[],
        stale_after_seconds=board.DEFAULT_STALE_AFTER_SECONDS,
    )

    exit_code = board.main(
        ["--state-dir", str(state_dir), "--stale-after-seconds", "30", "claim",
         "--role", "BUILD", "--work-item", "thief", "--file", "tools/a.py"]
    )

    assert exit_code == 2
    assert "floor" in capsys.readouterr().err
    still_held = board.list_claims(
        state_dir=state_dir, stale_after_seconds=board.DEFAULT_STALE_AFTER_SECONDS
    )
    assert [item.id for item in still_held] == [fresh.id]


def test_the_floor_does_not_reach_the_library_functions(tmp_path: Path) -> None:
    # The existing dead-owner test drives pruning with stale_after_seconds=1.
    # Putting the floor in main() rather than in claim()/list_claims()/release()
    # is what keeps that possible without a real wait.
    state_dir = tmp_path / "state"
    _dead_claim(state_dir, age_seconds=120, files=["tools/a.py"])

    assert board.list_claims(state_dir=state_dir, stale_after_seconds=1) == []
