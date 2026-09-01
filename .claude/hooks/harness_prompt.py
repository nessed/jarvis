"""UserPromptSubmit hook: "go" / "resume" switch the lane into loop mode.

The user's whole interface is: open a terminal in the folder, start claude,
type ``go`` (or ``resume``). This hook reads that word and:

* sets ``loop: true`` on the session record, which is what lets the Stop
  hook keep the lane working through the board instead of ending the turn;
  any other prompt sets it back to false, so a session where the user is
  actually talking is never dragged into the loop by mistake;
* injects, as additional context, the live peers, orphaned claims, this
  session's own unfinished claims, and unread inbox messages.

Output: a JSON object with ``hookSpecificOutput.additionalContext``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _harness  # noqa: E402

LOOP_WORDS = {"go", "resume", "continue", "go on", "keep going", "carry on", "next", "loop"}
_STRIP = re.compile(r"[\s.!,:;]+$")


def is_loop_prompt(prompt: str) -> bool:
    cleaned = _STRIP.sub("", prompt.strip().lower())
    return cleaned in LOOP_WORDS


def run(payload: dict[str, Any], *, root: Path, state_dir: Path) -> dict[str, Any] | None:
    if _harness.is_subagent(payload):
        return None
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        return None
    board = _harness.load_board_module(root)
    loop = is_loop_prompt(str(payload.get("prompt", "")))
    session = board.touch_session(state_dir, session_id, loop=loop)
    if session is None:
        session = board.register_session(state_dir, session_id)
        board.touch_session(state_dir, session_id, loop=loop)

    parts: list[str] = []
    if loop:
        parts.append(
            f"[harness] Loop mode on for {session.lane}. Run the loop in docs/board/README.md: take the first ready task, "
            "claim it, do it, verify, log, release, take the next. Do not ask what to work on. When you try to stop while "
            "tasks are still ready, a hook will hand you the next one. Stop only when everything left is blocked or the "
            "user's; then write docs/board/HANDOFF.md and send one PushNotification."
        )
    mine = board.claims_for_session(state_dir, session_id)
    if mine:
        parts.append("Unfinished work this session already holds: " + ", ".join(sorted({c.work_item for c in mine})) + ". Resume it first.")
    parts.append(_harness.peers_summary(board, state_dir, session_id))
    inbox = _harness.inbox_summary(board, state_dir, session_id, deliver=True)
    if inbox:
        parts.append(inbox)
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "\n\n".join(p for p in parts if p),
        }
    }


def main() -> int:
    payload = _harness.read_payload()
    root = _harness.repository_root(payload)
    try:
        result = run(payload, root=root, state_dir=_harness.state_dir_for(root))
    except Exception as exc:
        print(f"[harness] prompt hook failed open: {exc}", file=sys.stderr)
        return 0
    if result:
        _harness.emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
