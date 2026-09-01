"""SessionStart hook: register this session as a lane and tell Claude who else is here.

Fires on a fresh start, a resume, and after a context compaction. It:

1. writes ``.work-board/sessions/<session_id>.json`` with a lane label
   (``lane-1``, ``lane-2``: the lowest number no live session holds, and the
   same label again on resume);
2. exports ``JARVIS_SESSION_ID`` and ``JARVIS_LANE`` through
   ``CLAUDE_ENV_FILE`` so every Bash command this session runs -- the claim
   tool, pytest -- knows which lane it is;
3. prints, on stdout, the peers that are alive and what they hold, any
   claims left by a dead session (a crash to resume from), and unread inbox
   messages. Plain stdout from SessionStart is added to Claude's context.

Nothing here asks the user anything. The point is that "ur running with
another agent side by side" and "it crashed" stop being things the user has
to say.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _harness  # noqa: E402


def run(payload: dict[str, Any], *, root: Path, state_dir: Path, env_file: Path | None) -> str:
    if _harness.is_subagent(payload):
        return ""
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        return ""
    board = _harness.load_board_module(root)
    pane = os.environ.get("HERDR_PANE_ID") or os.environ.get("WT_SESSION") or ""
    session = board.register_session(
        state_dir,
        session_id,
        source=str(payload.get("source", "")),
        transcript_path=str(payload.get("transcript_path", "")),
        pane=pane,
    )
    inherited = board.inherit_pane_claims(state_dir, session_id, pane)
    board.sweep_dead_session_files(state_dir)
    if env_file is not None:
        try:
            with env_file.open("a", encoding="utf-8") as handle:
                handle.write(f"export {board.SESSION_ENV_VAR}={session.session_id}\n")
                handle.write(f"export JARVIS_LANE={session.lane}\n")
        except OSError:
            pass

    lines = [
        f"[harness] You are {session.lane} (session {session.session_id[:8]}) in {root.name}. "
        f"Claims you make with tools/work_board_claim.py are attributed to this lane automatically; "
        f"run the offline suite with --basetemp=.pytest-basetemp-{session.lane} (the documented command already does via $JARVIS_LANE).",
        _harness.peers_summary(board, state_dir, session.session_id),
    ]
    if inherited:
        items = sorted({c.work_item for c in inherited})
        lines.append(
            f"The previous session in this terminal died holding claims for: {', '.join(items)}. "
            f"They are yours now. Read each task's Log in docs/board/tasks/ to see how far it got, then resume it "
            f"before taking anything new."
        )
    mine = [c for c in board.claims_for_session(state_dir, session.session_id) if c.id not in {i.id for i in inherited}]
    if mine:
        items = sorted({c.work_item for c in mine})
        lines.append(f"This session already holds claims for: {', '.join(items)}. That is unfinished work; resume it before taking anything new.")
    abandoned = _harness.abandoned_tasks(board, state_dir, root, session.session_id)
    if abandoned:
        lines.append(
            "Tasks marked in-progress that no live session holds (a lane died mid-task): "
            + ", ".join(abandoned)
            + ". Whoever runs the loop next resumes the first of these before any ready task."
        )
    inbox = _harness.inbox_summary(board, state_dir, session.session_id, deliver=True)
    if inbox:
        lines.append(inbox)
    lines.append("Say nothing about this block to the user unless it changes what you do. "
                 "If they say go or resume, run the board loop in docs/board/README.md without asking what to work on.")
    return "\n\n".join(line for line in lines if line)


def main() -> int:
    payload = _harness.read_payload()
    root = _harness.repository_root(payload)
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    try:
        text = run(payload, root=root, state_dir=_harness.state_dir_for(root), env_file=Path(env_file) if env_file else None)
    except Exception as exc:  # a broken hook must never block a session from starting
        print(f"[harness] session-start hook failed: {exc}", file=sys.stderr)
        return 0
    if text:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
