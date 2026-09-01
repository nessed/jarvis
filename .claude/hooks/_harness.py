"""Shared plumbing for the harness hooks in this directory.

Every hook is a stdlib-only Python script that reads one JSON object from
stdin (the Claude Code hook payload), does a little bookkeeping in
``.work-board/``, and prints either nothing or one JSON object. This module
holds what they share: locating the repository, loading the claim tool by
path, parsing the board, and rendering the "who else is here" summary.

Portability: this directory plus ``tools/work_board_claim.py`` is the whole
harness. Copy both into another repository (with the hook entries in
``.claude/settings.json``) and it works there unchanged; nothing here imports
project code.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

HOOKS_DIR = Path(__file__).resolve().parent


def repository_root(payload: dict[str, Any] | None = None) -> Path:
    """The repo the hook runs for: the payload's cwd if it has our layout, else ours."""
    candidate = Path(payload.get("cwd", "")) if payload else None
    if candidate and (candidate / "tools" / "work_board_claim.py").is_file():
        return candidate.resolve()
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root and (Path(env_root) / "tools" / "work_board_claim.py").is_file():
        return Path(env_root).resolve()
    return HOOKS_DIR.parent.parent


_BOARD_MODULES: dict[Path, ModuleType] = {}


def load_board_module(root: Path) -> ModuleType:
    """Load ``tools/work_board_claim.py`` once per repository root.

    Cached so every caller in one process shares one ``ClaimError`` class and
    one set of constants; loading it twice would make an exception raised by
    one copy invisible to an ``except`` written against the other.
    """
    path = (root / "tools" / "work_board_claim.py").resolve()
    cached = _BOARD_MODULES.get(path)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(f"work_board_claim_{len(_BOARD_MODULES)}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _BOARD_MODULES[path] = module
    return module


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def state_dir_for(root: Path) -> Path:
    override = os.environ.get("JARVIS_WORK_BOARD_DIR")
    return Path(override) if override else root / ".work-board"


def is_subagent(payload: dict[str, Any]) -> bool:
    """Subagents ride on their parent's session; they are not lanes."""
    return bool(payload.get("agent_id"))


# --- board -------------------------------------------------------------------

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---", re.DOTALL)
_NEXT_ITEM = re.compile(r"^\s*\d+\.\s+`([A-Za-z0-9_.-]+)`", re.MULTILINE)


def task_frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    match = _FRONTMATTER.match(text)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def board_order(root: Path) -> list[str]:
    readme = root / "docs" / "board" / "README.md"
    try:
        text = readme.read_text(encoding="utf-8")
    except OSError:
        return []
    seen: list[str] = []
    for task_id in _NEXT_ITEM.findall(text):
        if task_id not in seen:
            seen.append(task_id)
    return seen


def ready_tasks(root: Path) -> list[str]:
    """Task ids with ``status: ready``, in the README's NEXT order first."""
    tasks_dir = root / "docs" / "board" / "tasks"
    if not tasks_dir.is_dir():
        return []
    ready: dict[str, str] = {}
    for path in sorted(tasks_dir.glob("*.md")):
        fields = task_frontmatter(path)
        if fields.get("status", "").lower() == "ready":
            ready[fields.get("id", path.stem)] = path.stem
    order = board_order(root)
    ordered = [t for t in order if t in ready]
    ordered += [t for t in ready if t not in ordered]
    return ordered


def abandoned_tasks(board: ModuleType, state_dir: Path, root: Path, my_session: str) -> list[str]:
    """``status: in-progress`` tasks whose task file no live session holds.

    A lane that crashed mid-task leaves its task in-progress. The board loop
    only takes ``ready`` tasks, so without this the task would sit there
    forever looking busy. Ordered like the README's NEXT list.
    """
    tasks_dir = root / "docs" / "board" / "tasks"
    if not tasks_dir.is_dir():
        return []
    claims = board.list_claims(state_dir=state_dir, stale_after_seconds=board.DEFAULT_STALE_AFTER_SECONDS)
    live_holders: set[str] = set()
    for claim in claims:
        alive = board.claim_holder_alive(claim, state_dir)
        if alive is True or (alive is None and claim.session_id == "" ):
            # A legacy claim is counted as held: pre-harness panes are still
            # working, and the age-based prune is their only backstop.
            live_holders.update(claim.files)
    stranded: dict[str, str] = {}
    for path in sorted(tasks_dir.glob("*.md")):
        fields = task_frontmatter(path)
        if fields.get("status", "").lower() != "in-progress":
            continue
        task_file = f"docs/board/tasks/{path.stem}.md"
        if any(board._paths_overlap(task_file, held) for held in live_holders):
            continue
        stranded[fields.get("id", path.stem)] = path.stem
    order = board_order(root)
    return [t for t in order if t in stranded] + [t for t in stranded if t not in order]


def task_claimed_by_other(board: ModuleType, state_dir: Path, task_id: str, my_session: str) -> str | None:
    """Lane label of a live session holding the task file, if any."""
    task_file = f"docs/board/tasks/{task_id}.md"
    for claim in board.list_claims(state_dir=state_dir, stale_after_seconds=board.DEFAULT_STALE_AFTER_SECONDS):
        if claim.session_id == my_session:
            continue
        if any(board._paths_overlap(task_file, held) for held in claim.files):
            return claim.lane or claim.session_id[:8] or claim.work_item
    return None


# --- rendering ---------------------------------------------------------------


def peers_summary(board: ModuleType, state_dir: Path, my_session: str) -> str:
    lines: list[str] = []
    claims = board.list_claims(state_dir=state_dir, stale_after_seconds=board.DEFAULT_STALE_AFTER_SECONDS)
    peers = [s for s in board.live_sessions(state_dir) if s.session_id != my_session]
    if peers:
        lines.append("Peer sessions alive in this repo:")
        for peer in peers:
            held = [c for c in claims if c.session_id == peer.session_id]
            items = sorted({c.work_item for c in held})
            what = ", ".join(items) if items else "no claims yet"
            lines.append(f"- {peer.lane} (session {peer.session_id[:8]}): {what}")
        lines.append("Message a peer with: python tools/work_board_claim.py message --to <lane> \"...\" "
                     "(or the SendMessage tool if their session is listed by ListAgents).")
    else:
        lines.append("No other live session in this repo right now.")
    orphans = [c for c in claims if c.session_id != my_session and board.claim_holder_alive(c, state_dir) is not True]
    if orphans:
        lines.append("Claims held by no live session (a crashed or pre-harness lane):")
        for claim in orphans:
            lines.append(f"- {claim.id} {claim.role}/{claim.work_item}: {', '.join(claim.files + claim.resources)}")
        lines.append("If one of these is unfinished work you should pick up, adopt it: "
                     "python tools/work_board_claim.py adopt <id>. Otherwise leave it; a dead session's claims prune themselves.")
    return "\n".join(lines)


def inbox_summary(board: ModuleType, state_dir: Path, my_session: str, *, deliver: bool) -> str:
    messages = board.read_inbox(state_dir, my_session, deliver=deliver)
    if not messages:
        return ""
    head = f"You have {len(messages)} message(s) from other sessions. Read them before continuing; they may ask for a file you hold or a fix only you can make:"
    return head + "\n\n" + "\n---\n".join(m.strip() for m in messages)


def emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()
