"""The multi-session harness: session registry, claim guard, loop, inbox.

Everything here runs against a throwaway repository layout under tmp_path
(the real claim tool copied in, a small board) so no test touches
``.work-board/`` in the actual checkout, where other lanes' live claims are.

What is pinned, and why each matters:

* a session gets a lane label, its peers are reported, and a restart in the
  same terminal pane inherits the dead session's claims and lane -- the
  crash-recovery path that used to need the user to notice and type "it
  crashed";
* the PreToolUse guard denies a write to a file another *live* session
  holds, stays silent for the holder and for pre-harness (legacy) claims,
  and gates ``git commit`` on the ``git-commit`` resource;
* "go"/"resume" and only those switch loop mode on, and the Stop hook then
  hands the lane the next task in README order, skipping ones a peer holds,
  preferring a task a dead lane abandoned mid-way, giving up on a task after
  three hand-overs, and delivering inbox messages first;
* ``.claude/settings.json`` actually wires the four hooks, so they cannot
  drift out of the config without a test noticing.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"


def _load(name: str) -> ModuleType:
    path = HOOKS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"harness_test_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


session_start = _load("harness_session_start")
guard = _load("harness_guard")
prompt_hook = _load("harness_prompt")
stop_hook = _load("harness_stop")
harness = _load("_harness")


README = """# board

## NEXT — priority order

1. `alpha` — first
2. `beta` — second
3. `gamma` — third
"""


def _task(root: Path, task_id: str, status: str) -> None:
    (root / "docs" / "board" / "tasks" / f"{task_id}.md").write_text(
        f"---\nid: {task_id}\nstatus: {status}\nfiles: none\n---\n\n# {task_id}\n", encoding="utf-8"
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    (root / "docs" / "board" / "tasks").mkdir(parents=True)
    (root / "router").mkdir()
    shutil.copy(REPO_ROOT / "tools" / "work_board_claim.py", root / "tools" / "work_board_claim.py")
    (root / "docs" / "board" / "README.md").write_text(README, encoding="utf-8")
    _task(root, "alpha", "ready")
    _task(root, "beta", "ready")
    _task(root, "gamma", "blocked")
    (root / "router" / "routing.py").write_text("x = 1\n", encoding="utf-8")
    return root


def _state(root: Path) -> Path:
    return root / ".work-board"


def _board(root: Path) -> ModuleType:
    return harness.load_board_module(root)


def _start(root: Path, session_id: str, *, pane: str = "", env_file: Path | None = None) -> str:
    import os

    previous = {k: os.environ.get(k) for k in ("HERDR_PANE_ID", "WT_SESSION")}
    os.environ.pop("HERDR_PANE_ID", None)
    if pane:
        os.environ["WT_SESSION"] = pane
    else:
        os.environ.pop("WT_SESSION", None)
    try:
        return session_start.run(
            {"session_id": session_id, "cwd": str(root), "source": "startup"},
            root=root, state_dir=_state(root), env_file=env_file,
        )
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _claim(root: Path, session_id: str, *, files: list[str] = (), resources: list[str] = (), item: str = "job", role: str = "CORE"):
    board = _board(root)
    board._normalise_file.__defaults__ = (root,)  # claims are repo-relative to the fake root
    return board.claim(state_dir=_state(root), role=role, work_item=item, files=list(files), resources=list(resources),
                       stale_after_seconds=board.DEFAULT_STALE_AFTER_SECONDS, session_id=session_id)


def _guard(root: Path, session_id: str, tool: str, **tool_input):
    return guard.check({"session_id": session_id, "tool_name": tool, "tool_input": tool_input}, root=root, state_dir=_state(root))


def _reason(decision) -> str:
    assert decision is not None, "expected a deny decision"
    out = decision["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    return out["permissionDecisionReason"]


# --- session start -----------------------------------------------------------


def test_sessions_get_lane_labels_and_see_each_other(repo: Path, tmp_path: Path) -> None:
    env_file = tmp_path / "env.sh"
    first = _start(repo, "s1", pane="tab-1", env_file=env_file)
    second = _start(repo, "s2", pane="tab-2")

    assert "You are lane-1" in first
    assert "No other live session" in first
    assert "You are lane-2" in second
    assert "lane-1 (session s1)" in second
    assert "export JARVIS_SESSION_ID=s1" in env_file.read_text(encoding="utf-8")
    assert "export JARVIS_LANE=lane-1" in env_file.read_text(encoding="utf-8")


def test_a_restart_in_the_same_pane_inherits_the_dead_sessions_claims_and_lane(repo: Path) -> None:
    _start(repo, "s1", pane="tab-1")
    _start(repo, "s2", pane="tab-2")
    _claim(repo, "s1", files=["router/routing.py"], resources=["git-commit"], item="alpha")

    text = _start(repo, "s3", pane="tab-1")

    assert "You are lane-1" in text, "the restarted pane should get its old label back"
    assert "died holding claims for: alpha" in text
    board = _board(repo)
    claims = board.list_claims(state_dir=_state(repo), stale_after_seconds=board.DEFAULT_STALE_AFTER_SECONDS)
    assert [(c.work_item, c.session_id, c.lane) for c in claims] == [("alpha", "s3", "lane-1")]
    # The predecessor is marked dead at the epoch and swept as soon as its
    # claims have been taken over; either way it is not alive.
    old = board.load_session(_state(repo), "s1")
    assert old is None or not board.session_is_alive(old)


def test_subagents_are_not_registered_as_lanes(repo: Path) -> None:
    text = session_start.run({"session_id": "s1", "agent_id": "sub", "cwd": str(repo)}, root=repo, state_dir=_state(repo), env_file=None)

    assert text == ""
    assert _board(repo).load_sessions(_state(repo)) == []


# --- guard -------------------------------------------------------------------


def test_guard_denies_a_write_to_a_file_a_live_peer_holds(repo: Path) -> None:
    _start(repo, "s1", pane="tab-1")
    _start(repo, "s2", pane="tab-2")
    _claim(repo, "s1", files=["router/routing.py"], item="alpha")

    for tool, tool_input in (
        ("Edit", {"file_path": str(repo / "router" / "routing.py")}),
        ("Write", {"file_path": "router/routing.py"}),
        ("Bash", {"command": "cat x | tee router/routing.py"}),
        ("Bash", {"command": "sed -i 's/a/b/' router/routing.py"}),
        ("Bash", {"command": "echo hi > router/routing.py"}),
    ):
        reason = _reason(_guard(repo, "s2", tool, **tool_input))
        assert "router/routing.py is claimed by lane-1" in reason
        assert "message --to lane-1" in reason


def test_guard_is_silent_for_the_holder_and_for_unrelated_files(repo: Path) -> None:
    _start(repo, "s1", pane="tab-1")
    _start(repo, "s2", pane="tab-2")
    _claim(repo, "s1", files=["router/routing.py"], item="alpha")

    assert _guard(repo, "s1", "Edit", file_path="router/routing.py") is None
    assert _guard(repo, "s2", "Edit", file_path="router/other.py") is None
    assert _guard(repo, "s2", "Bash", command="cat router/routing.py") is None


def test_guard_does_not_enforce_legacy_claims_or_dead_sessions(repo: Path) -> None:
    _start(repo, "s2", pane="tab-2")
    # A pre-harness pane's claim: no session id at all.
    _claim(repo, "", files=["router/routing.py"], item="old")
    assert _guard(repo, "s2", "Edit", file_path="router/routing.py") is None

    # A registered session whose heartbeat is long gone.
    board = _board(repo)
    _start(repo, "s1", pane="tab-1")
    _claim(repo, "s1", files=["router/other.py"], item="alpha")
    dead = board.load_session(_state(repo), "s1")
    dead.last_seen = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    board.save_session(_state(repo), dead)
    assert _guard(repo, "s2", "Edit", file_path="router/other.py") is None


def test_guard_gates_commits_on_the_git_commit_resource(repo: Path) -> None:
    _start(repo, "s1", pane="tab-1")
    _start(repo, "s2", pane="tab-2")

    reason = _reason(_guard(repo, "s1", "Bash", command="git commit -q -F - <<'MSG'\nx\nMSG"))
    assert "git-commit resource" in reason

    _claim(repo, "s1", resources=["git-commit"], item="alpha")
    assert _guard(repo, "s1", "Bash", command="git commit -m x") is None
    assert "lane-1 holds the git-commit resource" in _reason(_guard(repo, "s2", "Bash", command="git commit -m y"))
    # An unregistered (legacy) session is not required to hold it, but is
    # still kept out while a live registered lane does.
    assert "lane-1 holds" in _reason(_guard(repo, "legacy", "Bash", command="git commit -m z"))


def test_guard_lets_a_legacy_session_commit_when_nobody_holds_the_lock(repo: Path) -> None:
    assert _guard(repo, "legacy", "Bash", command="git commit -m z") is None


def test_guard_forbids_git_stash_outright(repo: Path) -> None:
    _start(repo, "s1", pane="tab-1")
    assert "git stash is forbidden" in _reason(_guard(repo, "s1", "Bash", command="git stash pop"))


def test_guard_ignores_heredoc_bodies(repo: Path) -> None:
    """A commit message that *mentions* git stash is data, not a command.

    The first thing the guard ever denied was its own landing commit.
    """
    _start(repo, "s1", pane="tab-1")
    _claim(repo, "s1", resources=["git-commit"], item="alpha")
    command = "git commit -q -F - <<'MSG'\nRefuses git stash outright.\nWrites to router/routing.py > out\nMSG\ngit log -1"
    assert _guard(repo, "s1", "Bash", command=command) is None
    assert guard.bash_write_targets(command) == []
    assert "git stash" not in guard.strip_heredocs(command)


def test_guard_heartbeats_the_session(repo: Path) -> None:
    _start(repo, "s1", pane="tab-1")
    board = _board(repo)
    record = board.load_session(_state(repo), "s1")
    record.last_seen = (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    board.save_session(_state(repo), record)

    _guard(repo, "s1", "Bash", command="ls")

    fresh = board.load_session(_state(repo), "s1")
    assert datetime.now(UTC) - datetime.fromisoformat(fresh.last_seen) < timedelta(seconds=5)


def test_bash_write_targets_cover_the_shapes_auto_mode_uses() -> None:
    assert guard.bash_write_targets("python x.py > out.txt") == ["out.txt"]
    assert guard.bash_write_targets("cat a >> b.md; mv c d.py && cp e f.py") == ["b.md", "d.py", "f.py"]
    assert guard.bash_write_targets("echo x | tee -a g.txt") == ["g.txt"]
    assert guard.bash_write_targets("sed -i 's/a/b/' h.py") == ["h.py"]
    assert guard.bash_write_targets("cat a > /dev/null") == []


# --- prompt + stop: the loop -------------------------------------------------


def _prompt(root: Path, session_id: str, text: str):
    return prompt_hook.run({"session_id": session_id, "prompt": text}, root=root, state_dir=_state(root))


def _stop(root: Path, session_id: str):
    return stop_hook.run({"session_id": session_id, "stop_hook_active": False}, root=root, state_dir=_state(root))


@pytest.mark.parametrize("word", ["go", "Go.", "resume", "RESUME!", "continue", "keep going"])
def test_loop_words_switch_loop_mode_on(word: str) -> None:
    assert prompt_hook.is_loop_prompt(word)


@pytest.mark.parametrize("text", ["what are the other two doing?", "go fix the router", "resume the voice task"])
def test_other_prompts_do_not(text: str) -> None:
    assert not prompt_hook.is_loop_prompt(text)


def test_go_turns_the_loop_on_and_the_stop_hook_hands_over_tasks_in_readme_order(repo: Path) -> None:
    _start(repo, "s1", pane="tab-1")

    result = _prompt(repo, "s1", "go")
    context = result["hookSpecificOutput"]["additionalContext"]
    assert "Loop mode on for lane-1" in context
    assert _board(repo).load_session(_state(repo), "s1").loop is True

    block = _stop(repo, "s1")
    assert block["decision"] == "block"
    assert "`alpha` is `status: ready`" in block["reason"]


def test_a_chatting_session_is_never_dragged_into_the_loop(repo: Path) -> None:
    _start(repo, "s1", pane="tab-1")
    _prompt(repo, "s1", "what are the other terminals doing?")

    assert _board(repo).load_session(_state(repo), "s1").loop is False
    assert _stop(repo, "s1") is None


def test_stop_hook_skips_a_task_a_live_peer_holds(repo: Path) -> None:
    _start(repo, "s1", pane="tab-1")
    _start(repo, "s2", pane="tab-2")
    _prompt(repo, "s1", "go")
    _claim(repo, "s2", files=["docs/board/tasks/alpha.md"], item="alpha")

    assert "`beta`" in _stop(repo, "s1")["reason"]


def test_stop_hook_gives_up_on_a_task_after_three_handovers(repo: Path) -> None:
    _start(repo, "s1", pane="tab-1")
    _prompt(repo, "s1", "go")

    reasons = [_stop(repo, "s1")["reason"] for _ in range(3)]
    assert all("`alpha`" in r for r in reasons)
    assert "third time" in reasons[-1]
    assert "`beta`" in _stop(repo, "s1")["reason"]
    for _ in range(2):
        _stop(repo, "s1")
    assert _stop(repo, "s1") is None, "with every task handed over three times the lane may stop"


def test_stop_hook_prefers_a_task_a_dead_lane_abandoned(repo: Path) -> None:
    _start(repo, "s1", pane="tab-1")
    _start(repo, "s2", pane="tab-2")
    _task(repo, "beta", "in-progress")
    _claim(repo, "s2", files=["docs/board/tasks/beta.md"], item="beta")
    _prompt(repo, "s1", "go")
    assert "`alpha`" in _stop(repo, "s1")["reason"], "beta is held by a live peer"

    board = _board(repo)
    dead = board.load_session(_state(repo), "s2")
    dead.last_seen = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    board.save_session(_state(repo), dead)

    reason = _stop(repo, "s1")["reason"]
    assert "`beta` is marked in-progress but no live session holds it" in reason


def test_inbox_messages_outrank_the_board(repo: Path) -> None:
    _start(repo, "s1", pane="tab-1")
    _start(repo, "s2", pane="tab-2")
    _prompt(repo, "s1", "go")
    board = _board(repo)
    board.send_message(_state(repo), to="lane-1", text="please change routing.py line 40 to X", sender_id="s2", sender_lane="lane-2")

    block = _stop(repo, "s1")
    assert "1 message(s)" in block["reason"]
    assert "line 40" in block["reason"]
    assert "From:** lane-2" in block["reason"]
    # Delivered once: the next stop goes back to the board.
    assert "`alpha`" in _stop(repo, "s1")["reason"]


def test_the_prompt_hook_delivers_the_inbox_too(repo: Path) -> None:
    _start(repo, "s1", pane="tab-1")
    _start(repo, "s2", pane="tab-2")
    _board(repo).send_message(_state(repo), to="s1", text="hello from two", sender_id="s2", sender_lane="lane-2")

    context = _prompt(repo, "s1", "anything")["hookSpecificOutput"]["additionalContext"]
    assert "hello from two" in context
    assert _board(repo).read_inbox(_state(repo), "s1") == []


# --- claim tool: liveness replaces the PID check -----------------------------


def test_a_live_sessions_claim_survives_any_age_and_a_dead_ones_is_pruned(repo: Path) -> None:
    board = _board(repo)
    _start(repo, "s1", pane="tab-1")
    claim = _claim(repo, "s1", files=["router/routing.py"], item="alpha")
    # Backdate the claim far past the legacy window: still held, because s1 is alive.
    path = _state(repo) / "claims.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["claims"][0]["created_at"] = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    path.write_text(json.dumps(data), encoding="utf-8")
    assert [c.id for c in board.list_claims(state_dir=_state(repo), stale_after_seconds=60)] == [claim.id]

    dead = board.load_session(_state(repo), "s1")
    dead.last_seen = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    board.save_session(_state(repo), dead)
    assert board.list_claims(state_dir=_state(repo), stale_after_seconds=board.DEFAULT_STALE_AFTER_SECONDS) == []


def test_adopt_refuses_a_live_holder_and_takes_over_a_dead_one(repo: Path) -> None:
    board = _board(repo)
    _start(repo, "s1", pane="tab-1")
    _start(repo, "s2", pane="tab-2")
    claim = _claim(repo, "s1", files=["router/routing.py"], item="alpha")

    with pytest.raises(board.ClaimError, match="held by a live session"):
        board.adopt(state_dir=_state(repo), claim_id=claim.id, session_id="s2", stale_after_seconds=60)

    dead = board.load_session(_state(repo), "s1")
    dead.last_seen = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    board.save_session(_state(repo), dead)
    # Adopt reads the raw store before pruning would drop it.
    raw = json.loads((_state(repo) / "claims.json").read_text(encoding="utf-8"))
    assert raw["claims"], "precondition: the claim is still on disk"
    with pytest.raises(board.ClaimError, match="no active claim"):
        # Once the holder is dead the claim is pruned on the way in; a resumed
        # lane gets it through pane inheritance at start-up instead.
        board.adopt(state_dir=_state(repo), claim_id=claim.id, session_id="s2", stale_after_seconds=60)


def test_status_report_reads_like_an_answer(repo: Path) -> None:
    board = _board(repo)
    _start(repo, "s1", pane="tab-1")
    _start(repo, "s2", pane="tab-2")
    _prompt(repo, "s1", "go")
    _claim(repo, "s1", files=["router/routing.py"], item="alpha")

    text = board.status_report(_state(repo), session_id="s2", root=repo)

    assert "lane-1: alive" in text and "looping the board" in text
    assert "working on: alpha" in text
    assert "lane-2 (this terminal): alive" in text and "chatting / idle" in text
    assert "Board: blocked 1, ready 2" in text


def test_claim_conflicts_name_the_holder_and_how_to_reach_them(repo: Path) -> None:
    board = _board(repo)
    _start(repo, "s1", pane="tab-1")
    _start(repo, "s2", pane="tab-2")
    _claim(repo, "s1", files=["router/routing.py"], item="alpha")

    with pytest.raises(board.ClaimError, match=r"held by lane-1.*message --to lane-1"):
        _claim(repo, "s2", files=["router/routing.py"], item="beta")


# --- wiring ------------------------------------------------------------------


def test_settings_json_wires_all_four_hooks() -> None:
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks = settings["hooks"]

    def commands(event: str) -> list[str]:
        return [h["command"] for group in hooks[event] for h in group["hooks"]]

    assert any("harness_session_start.py" in c for c in commands("SessionStart"))
    assert any("harness_prompt.py" in c for c in commands("UserPromptSubmit"))
    assert any("harness_stop.py" in c for c in commands("Stop"))
    pre = hooks["PreToolUse"]
    assert any("harness_guard.py" in h["command"] for group in pre for h in group["hooks"])
    matchers = " ".join(group.get("matcher", "") for group in pre)
    for tool in ("Edit", "Write", "MultiEdit", "Bash"):
        assert tool in matchers
    for name in ("_harness", "harness_session_start", "harness_guard", "harness_prompt", "harness_stop"):
        assert (HOOKS_DIR / f"{name}.py").is_file()
