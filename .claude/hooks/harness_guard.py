"""PreToolUse hook: the claim board, enforced.

Until this existed every rule about not touching another lane's files was
convention: the claim tool recorded claims and nothing checked them. This
hook runs before every Edit/Write/MultiEdit/NotebookEdit/Bash call and:

* heartbeats this session's record (that is what makes liveness real);
* denies a write to a path a *different live session* has claimed, with a
  reason that names the holder and tells Claude how to message them;
* denies ``git commit`` unless this session holds the ``git-commit``
  resource, and denies ``git stash`` outright (the shared working tree rule
  in docs/plan.md);
* for Bash, best-effort extracts write targets (``>``, ``>>``, ``tee``,
  ``sed -i``, ``mv``, ``cp``, ``rm``) and checks those too, because in auto
  mode edits often go through the shell.

Legacy claims -- ones made before the session hooks existed, with no session
id -- are not enforced. A pane that predates the harness keeps working on its
own files; once every pane has restarted, every claim is attributed.

Output: nothing (allow) or a JSON permission decision on stdout. Exit 0
always; a hook crash must not turn into a denied tool call.
"""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _harness  # noqa: E402

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

_GIT_COMMIT = re.compile(r"(?:^|[;&|]\s*|\s)git\s+(?:-C\s+\S+\s+)?(?:[a-z-]+\s+)*commit\b")
_GIT_STASH = re.compile(r"(?:^|[;&|]\s*|\s)git\s+(?:-C\s+\S+\s+)?stash\b")
_PATHISH = re.compile(r"^(?:[A-Za-z]:)?[A-Za-z0-9_./\\ -]+$")


def _relative(root: Path, raw: str) -> str | None:
    """Repo-relative POSIX path for a file inside the repo, else None."""
    raw = raw.strip().strip("\"'")
    if not raw or not _PATHISH.match(raw):
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return None


_HEREDOC_OPEN = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def strip_heredocs(command: str) -> str:
    """Drop heredoc bodies: they are data (a commit message, a file), not commands.

    The first thing this guard ever denied was its own commit, because the
    message body said "refuses git stash".
    """
    lines = command.split("\n")
    kept: list[str] = []
    terminator: str | None = None
    for line in lines:
        if terminator is not None:
            if line.strip() == terminator:
                terminator = None
            continue
        kept.append(line)
        match = _HEREDOC_OPEN.search(line)
        if match:
            terminator = match.group(2)
    return "\n".join(kept)


def bash_write_targets(command: str) -> list[str]:
    """Paths a shell command plausibly writes. Best effort, biased to recall."""
    targets: list[str] = []
    for segment in re.split(r"&&|\|\||;|\n", strip_heredocs(command)):
        try:
            tokens = shlex.split(segment, posix=True)
        except ValueError:
            tokens = segment.split()
        for index, token in enumerate(tokens):
            nxt = tokens[index + 1] if index + 1 < len(tokens) else None
            if token in {">", ">>", "1>", "2>", "&>"} and nxt:
                targets.append(nxt)
            elif token.startswith((">", ">>")) and len(token) > 1 and not token.startswith(">&"):
                targets.append(token.lstrip(">"))
            elif token == "tee":
                targets.extend(t for t in tokens[index + 1:] if not t.startswith("-"))
            elif token == "sed" and any(t.startswith("-i") for t in tokens[index + 1:]):
                rest = [t for t in tokens[index + 1:] if not t.startswith("-")]
                if len(rest) >= 2:
                    targets.extend(rest[1:])
            elif token in {"mv", "cp"}:
                rest = [t for t in tokens[index + 1:] if not t.startswith("-")]
                if rest:
                    targets.append(rest[-1])
            elif token == "rm":
                targets.extend(t for t in tokens[index + 1:] if not t.startswith("-"))
    return [t for t in targets if t not in {"/dev/null", "NUL"}]


def _foreign_claims(board, state_dir: Path, my_session: str):
    claims = board.list_claims(state_dir=state_dir, stale_after_seconds=board.DEFAULT_STALE_AFTER_SECONDS)
    return [
        c for c in claims
        if c.session_id and c.session_id != my_session and board.claim_holder_alive(c, state_dir) is True
    ]


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _holder_label(claim) -> str:
    return claim.lane or claim.session_id[:8]


def check(payload: dict[str, Any], *, root: Path, state_dir: Path) -> dict[str, Any] | None:
    my_session = str(payload.get("session_id", "")).strip()
    board = _harness.load_board_module(root)
    if my_session and not _harness.is_subagent(payload):
        board.touch_session(state_dir, my_session)

    tool = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None

    paths: list[str] = []
    if tool in EDIT_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        rel = _relative(root, str(raw))
        if rel:
            paths.append(rel)
    elif tool == "Bash":
        command = strip_heredocs(str(tool_input.get("command", "")))
        if _GIT_STASH.search(command):
            return _deny(
                "git stash is forbidden in this shared working tree: it pauses every other lane's "
                "uncommitted work at once (docs/plan.md, Verification and live-route resources). "
                "Measure a delta another way or leave the files as they are."
            )
        if _GIT_COMMIT.search(command):
            mine = [c for c in board.claims_for_session(state_dir, my_session) if "git-commit" in c.resources] if my_session else []
            holders = [c for c in _foreign_claims(board, state_dir, my_session) if "git-commit" in c.resources]
            if holders:
                who = _holder_label(holders[0])
                return _deny(
                    f"{who} holds the git-commit resource right now; two lanes committing into one tree lose work. "
                    f"Wait for them to release it, or message them: python tools/work_board_claim.py message --to {who} \"...\""
                )
            registered = bool(my_session) and board.load_session(state_dir, my_session) is not None
            if registered and not mine:
                # A pane that predates the hooks has no session record; its
                # claims carry no session id either, so requiring one would
                # lock it out of committing until it restarts. Legacy panes
                # stay on the honour system; registered ones must hold the lock.
                return _deny(
                    "Commits need the git-commit resource claimed by this session first (CORE only): "
                    "python tools/work_board_claim.py claim --role CORE --work-item <task> --resource git-commit "
                    "-- then commit, then release the claim id it printed."
                )
        for raw in bash_write_targets(command):
            rel = _relative(root, raw)
            if rel:
                paths.append(rel)

    if not paths:
        return None

    for claim in _foreign_claims(board, state_dir, my_session):
        for path in paths:
            if any(board._paths_overlap(path, held) for held in claim.files):
                who = _holder_label(claim)
                return _deny(
                    f"{path} is claimed by {who} ({claim.role}/{claim.work_item}), and that session is alive. "
                    f"Do not edit it. If you need a change there, tell them exactly what and why: "
                    f"python tools/work_board_claim.py message --to {who} \"<what you need and the one-line fix>\" "
                    f"(or SendMessage if ListAgents shows them). If you disagree on the fix, run tools/consult.py with both positions "
                    f"attached and both act on the verdict. Meanwhile continue with work that does not touch {path}."
                )
    return None


def main() -> int:
    payload = _harness.read_payload()
    root = _harness.repository_root(payload)
    try:
        decision = check(payload, root=root, state_dir=_harness.state_dir_for(root))
    except Exception as exc:  # never let a hook bug block ordinary work
        print(f"[harness] guard hook failed open: {exc}", file=sys.stderr)
        return 0
    if decision:
        _harness.emit(decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
