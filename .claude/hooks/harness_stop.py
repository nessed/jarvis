"""Stop hook: in loop mode, do not let the lane stop while the board has work.

"Go back to step 1, do not stop" was a sentence in the board README. This
makes it a mechanism. When Claude tries to end its turn and the session is in
loop mode (the user said ``go`` or ``resume``), the hook:

1. delivers any unread inbox messages first -- another lane asking for a fix
   outranks the board;
2. otherwise finds the first ``status: ready`` task in the README's NEXT
   order that no other live session has claimed and blocks the stop with
   "that task is ready, continue";
3. gives up on a task it has handed over three times without the status
   changing (the lane is stuck on it; the README says mark it blocked and
   move on, and the hook simply skips it thereafter);
4. lets the stop through when nothing is left. That is the moment for the
   batched handoff, which the prompt hook already told the lane to write.

Outside loop mode the hook does nothing, so a session where the user is
chatting ends its turns normally.

Output: ``{"decision": "block", "reason": ...}`` or nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _harness  # noqa: E402

MAX_HANDOVERS_PER_TASK = 3


def run(payload: dict[str, Any], *, root: Path, state_dir: Path) -> dict[str, Any] | None:
    if _harness.is_subagent(payload):
        return None
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        return None
    board = _harness.load_board_module(root)
    session = board.load_session(state_dir, session_id)
    if session is None or not session.loop:
        return None

    inbox = _harness.inbox_summary(board, state_dir, session_id, deliver=True)
    if inbox:
        board.touch_session(state_dir, session_id)
        return {"decision": "block", "reason": inbox + "\n\nAct on these, then continue the board loop."}

    counts = dict(session.stop_blocks)
    abandoned = _harness.abandoned_tasks(board, state_dir, root, session_id)
    candidates = abandoned + [t for t in _harness.ready_tasks(root) if t not in abandoned]
    for task_id in candidates:
        stranded = task_id in abandoned
        if counts.get(task_id, 0) >= MAX_HANDOVERS_PER_TASK:
            continue
        holder = _harness.task_claimed_by_other(board, state_dir, task_id, session_id)
        if holder:
            continue
        counts[task_id] = counts.get(task_id, 0) + 1
        board.touch_session(state_dir, session_id, stop_blocks=counts)
        if stranded:
            reason = (
                f"[harness] `{task_id}` is marked in-progress but no live session holds it: a lane died mid-task "
                f"(docs/board/tasks/{task_id}.md). Resume it: read its Log to see how far it got, claim its files, "
                f"finish it, verify, log, release. Do not ask the user what to do next."
            )
        else:
            reason = (
                f"[harness] The board still has ready work: `{task_id}` is `status: ready` and unclaimed "
                f"(docs/board/tasks/{task_id}.md). Continue the loop: claim it with tools/work_board_claim.py, "
                f"flip it to in-progress, execute its Steps, verify, log, release. Do not ask the user what to do next."
            )
        if counts[task_id] == MAX_HANDOVERS_PER_TASK:
            reason += (
                f" This is the third time you have been handed `{task_id}`; if it cannot be finished, mark it "
                f"blocked with the reason in its Log and a line in docs/board/QUESTIONS.md, and move on."
            )
        return {"decision": "block", "reason": reason}

    board.touch_session(state_dir, session_id)
    return None


def main() -> int:
    payload = _harness.read_payload()
    root = _harness.repository_root(payload)
    try:
        result = run(payload, root=root, state_dir=_harness.state_dir_for(root))
    except Exception as exc:
        print(f"[harness] stop hook failed open: {exc}", file=sys.stderr)
        return 0
    if result:
        _harness.emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
