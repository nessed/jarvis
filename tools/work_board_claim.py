"""Atomic local claims for independent work-board lanes, plus the session
registry and inbox the Claude Code hooks in ``.claude/hooks/`` build on.

The state lives in ``.work-board/`` and is deliberately local-only:

    claims.json            active claims (files + exclusive resources)
    sessions/<id>.json     one record per live Claude session (lane label,
                           last_seen heartbeat, loop flag)
    inbox/<id>/*.md        messages to a session, one file each; delivered
                           ones move to inbox/<id>/delivered/

Run ``python tools/work_board_claim.py --help`` for the command interface.

Session identity
----------------
A claim records the Claude session that made it when ``JARVIS_SESSION_ID`` is
in the environment (the SessionStart hook exports it) or ``--session`` is
passed. That is what makes liveness real: the hooks heartbeat
``sessions/<id>.json`` on every tool call, so "is the holder alive" is a
timestamp check instead of the decorative PID check the old tool had (the
recorded PID was the ``claim`` subprocess, dead by the time anyone looked).

A claim without a session id is *legacy* and keeps the old age-only pruning.
The PreToolUse guard does not enforce legacy claims either, so a pane that
started before the hooks existed is never locked out of its own files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_DIR = Path(os.environ["JARVIS_WORK_BOARD_DIR"]) if os.environ.get("JARVIS_WORK_BOARD_DIR") else REPOSITORY_ROOT / ".work-board"
DEFAULT_STALE_AFTER_SECONDS = 24 * 60 * 60
LOCK_STALE_AFTER_SECONDS = 60

#: A session whose heartbeat is older than this is dead. The hooks touch the
#: session file on every tool call, so a live lane that is merely thinking
#: hard for a while still refreshes it well inside this window.
SESSION_DEAD_AFTER_SECONDS = 30 * 60

#: Environment variable the SessionStart hook exports; the claim tool reads
#: it so every claim a lane makes is attributed to that lane automatically.
SESSION_ENV_VAR = "JARVIS_SESSION_ID"

#: Floor under ``--stale-after-seconds``, enforced in ``main`` only.
#:
#: Pruning of legacy claims is age-only (see ``_prune_stale``), so a small
#: window is not a staleness threshold at all -- it is a licence to delete
#: whatever another lane claimed in the last few seconds. Five minutes is
#: short enough to clear a genuinely abandoned board and far longer than the
#: seconds-scale windows that caused the 30 August 2026 collision.
#:
#: Deliberately not enforced in ``claim``/``list_claims``/``release``: the
#: library functions stay unbounded so tests can drive pruning directly
#: without a real wait.
MINIMUM_STALE_AFTER_SECONDS = 300


class ClaimError(Exception):
    """A user-visible claim operation failure."""


@dataclass(frozen=True)
class Claim:
    id: str
    role: str
    work_item: str
    files: list[str]
    resources: list[str]
    pid: int
    created_at: str
    session_id: str = ""
    lane: str = ""


@dataclass
class Session:
    session_id: str
    lane: str
    started_at: str
    last_seen: str
    loop: bool = False
    source: str = ""
    transcript_path: str = ""
    pane: str = ""
    stop_blocks: dict[str, int] = field(default_factory=dict)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _state_paths(state_dir: Path) -> tuple[Path, Path]:
    return state_dir / "claims.json", state_dir / "claims.lock"


def _sessions_dir(state_dir: Path) -> Path:
    return state_dir / "sessions"


def _inbox_dir(state_dir: Path, session_id: str) -> Path:
    return state_dir / "inbox" / session_id


@contextmanager
def _exclusive_lock(state_dir: Path) -> Iterator[None]:
    """Acquire an exclusive lock file, recovering only a clearly stale lock."""
    state_dir.mkdir(parents=True, exist_ok=True)
    _, lock_path = _state_paths(state_dir)
    deadline = time.monotonic() + 10
    while True:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(str(os.getpid()))
            break
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                continue
            try:
                lock_owner = int(lock_path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                lock_owner = 0
            if age > LOCK_STALE_AFTER_SECONDS and not _owner_alive(lock_owner):
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    continue
                continue
            if time.monotonic() >= deadline:
                raise ClaimError("claim store is busy; another claim operation is still running")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _load_claims(state_dir: Path) -> list[Claim]:
    state_path, _ = _state_paths(state_dir)
    if not state_path.exists():
        return []
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("claims"), list):
            raise ValueError("expected an object with a claims list")
        claims = [Claim(**record) for record in payload["claims"]]
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ClaimError(f"claim state is malformed at {state_path}; refusing to change it") from exc
    return claims


def _write_claims(state_dir: Path, claims: list[Claim]) -> None:
    state_path, _ = _state_paths(state_dir)
    temporary = state_path.with_suffix(".tmp")
    payload = {"claims": [asdict(claim) for claim in claims]}
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, state_path)


def _normalise_file(value: str, root: Path = REPOSITORY_ROOT) -> str:
    candidate = (root / value).resolve()
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise ClaimError(f"file path must stay inside the repository: {value}") from exc


def _normalise_resource(value: str) -> str:
    result = value.strip()
    if not result:
        raise ClaimError("resource keys cannot be empty")
    return result


def _paths_overlap(left: str, right: str) -> bool:
    left_parts = Path(left).parts
    right_parts = Path(right).parts
    return left_parts == right_parts[: len(left_parts)] or right_parts == left_parts[: len(right_parts)]


def _owner_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        # Windows reports an invalid/nonexistent PID as WinError 87 rather
        # than ProcessLookupError.
        return False
    else:
        return True


# --- sessions ----------------------------------------------------------------


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return parsed


def _session_path(state_dir: Path, session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)
    return _sessions_dir(state_dir) / f"{safe}.json"


def load_sessions(state_dir: Path) -> list[Session]:
    directory = _sessions_dir(state_dir)
    if not directory.is_dir():
        return []
    sessions: list[Session] = []
    for path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            sessions.append(Session(**record))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # A half-written record is not worth failing every caller for.
            continue
    return sessions


def load_session(state_dir: Path, session_id: str) -> Session | None:
    path = _session_path(state_dir, session_id)
    if not path.is_file():
        return None
    try:
        return Session(**json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def save_session(state_dir: Path, session: Session) -> None:
    path = _session_path(state_dir, session.session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(session), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def session_is_alive(session: Session, *, dead_after_seconds: int = SESSION_DEAD_AFTER_SECONDS, now: datetime | None = None) -> bool:
    try:
        last_seen = _parse_time(session.last_seen)
    except ValueError:
        return False
    return (now or _utc_now()) - last_seen < timedelta(seconds=dead_after_seconds)


def live_sessions(state_dir: Path, *, dead_after_seconds: int = SESSION_DEAD_AFTER_SECONDS) -> list[Session]:
    now = _utc_now()
    return [s for s in load_sessions(state_dir) if session_is_alive(s, dead_after_seconds=dead_after_seconds, now=now)]


def _next_lane_label(state_dir: Path) -> str:
    taken = {s.lane for s in live_sessions(state_dir)}
    number = 1
    while f"lane-{number}" in taken:
        number += 1
    return f"lane-{number}"


def register_session(state_dir: Path, session_id: str, *, source: str = "", transcript_path: str = "", pane: str = "") -> Session:
    """Create or refresh a session record; the lane label survives a resume."""
    with _exclusive_lock(state_dir):
        now = _utc_now().isoformat()
        existing = load_session(state_dir, session_id)
        if existing is not None:
            existing.last_seen = now
            existing.source = source or existing.source
            existing.transcript_path = transcript_path or existing.transcript_path
            existing.pane = pane or existing.pane
            save_session(state_dir, existing)
            return existing
        if pane:
            # One Claude per terminal pane: any other session registered from
            # this pane is dead, and a restart should get its lane label back.
            for other in load_sessions(state_dir):
                if other.session_id != session_id and other.pane == pane:
                    other.last_seen = DEAD_TIMESTAMP
                    save_session(state_dir, other)
        session = Session(
            session_id=session_id,
            lane=_next_lane_label(state_dir),
            started_at=now,
            last_seen=now,
            source=source,
            transcript_path=transcript_path,
            pane=pane,
        )
        save_session(state_dir, session)
        return session


DEAD_TIMESTAMP = "1970-01-01T00:00:00+00:00"


def inherit_pane_claims(state_dir: Path, session_id: str, pane: str) -> list[Claim]:
    """A new session in a terminal tab takes over the previous session's claims.

    One terminal runs one Claude at a time, so when a session starts in a
    pane (``HERDR_PANE_ID`` or Windows Terminal's ``WT_SESSION``) that another
    registered session already names, that other session is dead by
    construction -- it crashed or was closed. Its heartbeat is set to the
    epoch so nothing treats it as alive, and its claims are re-attributed to
    the new session so "resume" means exactly that. This is what lets the
    user restart a crashed pane with plain ``claude`` and the word resume.
    """
    if not pane or not session_id:
        return []
    inherited: list[Claim] = []
    with _exclusive_lock(state_dir):
        me = load_session(state_dir, session_id)
        dead_ids: set[str] = set()
        for other in load_sessions(state_dir):
            if other.session_id == session_id or other.pane != pane:
                continue
            other.last_seen = DEAD_TIMESTAMP
            save_session(state_dir, other)
            dead_ids.add(other.session_id)
        if not dead_ids:
            return []
        claims = _load_claims(state_dir)
        updated: list[Claim] = []
        for existing in claims:
            if existing.session_id in dead_ids:
                adopted = Claim(**{**asdict(existing), "session_id": session_id, "lane": me.lane if me else existing.lane})
                inherited.append(adopted)
                updated.append(adopted)
            else:
                updated.append(existing)
        if inherited:
            _write_claims(state_dir, updated)
    return inherited


def touch_session(state_dir: Path, session_id: str, **changes: Any) -> Session | None:
    """Heartbeat a session, optionally updating fields such as ``loop``."""
    session = load_session(state_dir, session_id)
    if session is None:
        return None
    session.last_seen = _utc_now().isoformat()
    for key, value in changes.items():
        setattr(session, key, value)
    save_session(state_dir, session)
    return session


def sweep_dead_session_files(state_dir: Path) -> None:
    """Drop session records dead for more than a day; they hold nothing.

    Called by the SessionStart hook *after* pane inheritance has read the
    records it needs: a same-pane predecessor is marked dead-at-the-epoch
    and would otherwise vanish before its claims could be taken over.
    """
    now = _utc_now()
    for session in load_sessions(state_dir):
        if not session_is_alive(session, dead_after_seconds=24 * 60 * 60, now=now):
            try:
                _session_path(state_dir, session.session_id).unlink()
            except OSError:
                pass


def resolve_session(state_dir: Path, target: str) -> Session | None:
    """Find a session by id, id prefix, or lane label."""
    for session in load_sessions(state_dir):
        if target in (session.session_id, session.lane) or session.session_id.startswith(target):
            return session
    return None


def current_session_id(explicit: str | None = None) -> str:
    return (explicit or os.environ.get(SESSION_ENV_VAR, "")).strip()


# --- inbox -------------------------------------------------------------------


def send_message(state_dir: Path, *, to: str, text: str, sender_id: str = "", sender_lane: str = "") -> list[Path]:
    """Write a message file into one session's inbox, or every live peer's."""
    text = text.strip()
    if not text:
        raise ClaimError("a message needs some text")
    if to == "all":
        targets = [s for s in live_sessions(state_dir) if s.session_id != sender_id]
        if not targets:
            raise ClaimError("no live peer sessions to message")
    else:
        found = resolve_session(state_dir, to)
        if found is None:
            raise ClaimError(f"no session matches {to!r}; try `sessions` to list them")
        targets = [found]
    written: list[Path] = []
    stamp = _utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    origin = sender_lane or sender_id[:8] or "unknown"
    for target in targets:
        directory = _inbox_dir(state_dir, target.session_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{stamp}-{re.sub(r'[^A-Za-z0-9_-]', '_', origin)}.md"
        body = f"**From:** {origin}" + (f" ({sender_id})" if sender_id else "") + f"\n**At:** {_utc_now().isoformat()}\n\n{text}\n"
        path.write_text(body, encoding="utf-8")
        written.append(path)
    return written


def read_inbox(state_dir: Path, session_id: str, *, deliver: bool = False) -> list[str]:
    """Return unread messages, oldest first; ``deliver`` moves them aside."""
    directory = _inbox_dir(state_dir, session_id)
    if not directory.is_dir():
        return []
    messages: list[str] = []
    for path in sorted(directory.glob("*.md")):
        try:
            messages.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if deliver:
            delivered = directory / "delivered"
            delivered.mkdir(exist_ok=True)
            try:
                os.replace(path, delivered / path.name)
            except OSError:
                pass
    return messages


# --- claims ------------------------------------------------------------------


def _report_pruned(claim: Claim, age_seconds: float, why: str) -> None:
    """Announce a dropped claim on stderr, loudly enough to be reported on.

    Pruning used to be silent, and silence is what makes it dangerous: on 30
    August 2026 a lane hit a conflict, re-ran with ``--stale-after-seconds
    30``, and deleted a *live* parallel lane's claims. Both lanes then edited
    the same files. Neither the destroying lane nor the victim got any signal
    until a file changed underneath a half-written edit.

    stderr, not stdout, so the JSON a caller parses stays clean.
    """
    held = ", ".join(claim.files + claim.resources) or "(nothing)"
    print(
        f"pruned claim {claim.id} ({claim.role}/{claim.work_item}), "
        f"held {int(age_seconds)}s, {why}: {held}",
        file=sys.stderr,
    )


def claim_holder_alive(claim: Claim, state_dir: Path, *, now: datetime | None = None) -> bool | None:
    """True/False when the claim names a registered session; None if unknown."""
    if not claim.session_id:
        return None
    session = load_session(state_dir, claim.session_id)
    if session is None:
        return None
    return session_is_alive(session, now=now)


def _prune_stale(claims: list[Claim], stale_after_seconds: int, state_dir: Path | None = None) -> list[Claim]:
    """Drop claims whose holder is gone, announcing each one that goes.

    Two regimes:

    * A claim with a registered session is pruned only when that session's
      heartbeat is dead (``SESSION_DEAD_AFTER_SECONDS``). Age is irrelevant:
      a lane that is alive keeps its claims for as long as it likes, and a
      crashed lane frees them half an hour after it stopped answering.
    * A legacy claim (no session, or a session never registered) keeps the
      old age-only rule. The ``_owner_alive`` conjunct there can never fire
      for a real claim -- ``claim()`` records ``os.getpid()`` of a process
      that exits the moment it prints -- and is kept only because the tests
      pin the dead-owner path.
    """
    now = _utc_now()
    cutoff = now - timedelta(seconds=stale_after_seconds)
    active: list[Claim] = []
    for claim in claims:
        try:
            created_at = _parse_time(claim.created_at)
        except ValueError as exc:
            raise ClaimError("claim state contains an invalid timestamp; refusing to change it") from exc
        age = (now - created_at).total_seconds()
        alive = claim_holder_alive(claim, state_dir, now=now) if state_dir is not None else None
        if alive is False:
            _report_pruned(claim, age, f"session {claim.lane or claim.session_id[:8]} is dead")
            continue
        if alive is None and created_at < cutoff and not _owner_alive(claim.pid):
            _report_pruned(claim, age, "older than the stale window")
            continue
        active.append(claim)
    return active


def claim(*, state_dir: Path, role: str, work_item: str, files: list[str], resources: list[str], stale_after_seconds: int, session_id: str = "") -> Claim:
    normalised_files = sorted(set(_normalise_file(value) for value in files))
    normalised_resources = sorted(set(_normalise_resource(value) for value in resources))
    if not normalised_files and not normalised_resources:
        raise ClaimError("a claim needs at least one --file or --resource")
    if not role.strip() or not work_item.strip():
        raise ClaimError("--role and --work-item cannot be empty")
    if "git-commit" in normalised_resources and role.strip() != "CORE":
        raise ClaimError("resource git-commit is reserved for the CORE role")
    session_id = session_id.strip()
    with _exclusive_lock(state_dir):
        claims = _prune_stale(_load_claims(state_dir), stale_after_seconds, state_dir)
        for existing in claims:
            colliding_files = [
                requested for requested in normalised_files
                if any(_paths_overlap(requested, held) for held in existing.files)
            ]
            colliding_resources = sorted(set(normalised_resources) & set(existing.resources))
            if colliding_files or colliding_resources:
                details = []
                if colliding_files:
                    details.append("files: " + ", ".join(colliding_files))
                if colliding_resources:
                    details.append("resources: " + ", ".join(colliding_resources))
                holder = existing.lane or (existing.session_id[:8] if existing.session_id else "an unregistered session")
                raise ClaimError(
                    f"conflict with {existing.role}/{existing.work_item} ({existing.id}, held by {holder}): "
                    + "; ".join(details)
                    + f". Message the holder instead of waiting: python tools/work_board_claim.py message --to {existing.lane or existing.session_id or 'all'} \"...\""
                )
        session = load_session(state_dir, session_id) if session_id else None
        new_claim = Claim(
            id=uuid4().hex,
            role=role.strip(),
            work_item=work_item.strip(),
            files=normalised_files,
            resources=normalised_resources,
            pid=os.getpid(),
            created_at=_utc_now().isoformat(),
            session_id=session_id,
            lane=session.lane if session else "",
        )
        claims.append(new_claim)
        _write_claims(state_dir, claims)
        return new_claim


def list_claims(*, state_dir: Path, stale_after_seconds: int) -> list[Claim]:
    with _exclusive_lock(state_dir):
        claims = _load_claims(state_dir)
        active = _prune_stale(claims, stale_after_seconds, state_dir)
        if active != claims:
            _write_claims(state_dir, active)
        return active


def release(*, state_dir: Path, claim_id: str, stale_after_seconds: int) -> Claim:
    with _exclusive_lock(state_dir):
        claims = _prune_stale(_load_claims(state_dir), stale_after_seconds, state_dir)
        remaining = [claim for claim in claims if claim.id != claim_id]
        if len(remaining) == len(claims):
            raise ClaimError(f"no active claim has id {claim_id}")
        released = next(claim for claim in claims if claim.id == claim_id)
        _write_claims(state_dir, remaining)
        return released


def adopt(*, state_dir: Path, claim_id: str, session_id: str, stale_after_seconds: int) -> Claim:
    """Re-attribute a claim to the calling session.

    For resuming after a crash: the new session finds the dead one's claims
    at start-up and takes them over instead of releasing and re-claiming,
    which keeps the work item's history in one record.
    """
    session_id = session_id.strip()
    if not session_id:
        raise ClaimError(f"adopt needs a session id: pass --session or export {SESSION_ENV_VAR}")
    with _exclusive_lock(state_dir):
        claims = _prune_stale(_load_claims(state_dir), stale_after_seconds, state_dir)
        target = next((c for c in claims if c.id == claim_id), None)
        if target is None:
            raise ClaimError(f"no active claim has id {claim_id}")
        holder_alive = claim_holder_alive(target, state_dir)
        if holder_alive and target.session_id != session_id:
            raise ClaimError(f"claim {claim_id} is held by a live session ({target.lane}); ask them to release it")
        session = load_session(state_dir, session_id)
        adopted = Claim(**{**asdict(target), "session_id": session_id, "lane": session.lane if session else ""})
        _write_claims(state_dir, [adopted if c.id == claim_id else c for c in claims])
        return adopted


def claims_for_session(state_dir: Path, session_id: str, *, stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS) -> list[Claim]:
    return [c for c in list_claims(state_dir=state_dir, stale_after_seconds=stale_after_seconds) if c.session_id == session_id]


def orphaned_claims(state_dir: Path, *, stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS) -> list[Claim]:
    """Claims held by nobody alive: legacy ones, and ones from dead sessions.

    Dead-session claims are normally pruned on the next operation, so what
    this mostly surfaces at SessionStart is the window between a crash and
    the prune -- exactly when a resuming lane should adopt them.
    """
    with _exclusive_lock(state_dir):
        raw = _load_claims(state_dir)
    return [c for c in raw if claim_holder_alive(c, state_dir) is not True]


def status_report(state_dir: Path, *, session_id: str = "", root: Path = REPOSITORY_ROOT) -> str:
    """One readable answer to "what are the other terminals doing?"."""
    now = _utc_now()
    claims = list_claims(state_dir=state_dir, stale_after_seconds=DEFAULT_STALE_AFTER_SECONDS)
    lines: list[str] = []
    sessions = load_sessions(state_dir)
    if not sessions:
        lines.append("No registered sessions. Either no Claude session has started here since the hooks were installed, or all have been dead for a day.")
    for session in sorted(sessions, key=lambda s: s.lane):
        alive = session_is_alive(session, now=now)
        try:
            silent = int((now - _parse_time(session.last_seen)).total_seconds())
        except ValueError:
            silent = -1
        held = [c for c in claims if c.session_id == session.session_id]
        items = sorted({c.work_item for c in held})
        marker = " (this terminal)" if session.session_id == session_id else ""
        state = "alive" if alive else "dead"
        mode = "looping the board" if session.loop else "chatting / idle"
        lines.append(f"{session.lane}{marker}: {state}, last tool call {silent}s ago, {mode}")
        lines.append(f"  working on: {', '.join(items) if items else 'nothing claimed'}")
        for c in held:
            lines.append(f"    - {c.work_item}: {', '.join(c.files + c.resources)}")
        unread = len(read_inbox(state_dir, session.session_id))
        if unread:
            lines.append(f"  unread messages: {unread}")
    unattributed = [c for c in claims if not c.session_id or load_session(state_dir, c.session_id) is None]
    if unattributed:
        lines.append("Claims with no registered session (pre-harness panes; enforced by convention only):")
        for c in unattributed:
            lines.append(f"  - {c.role}/{c.work_item}: {', '.join(c.files + c.resources)}")
    tasks_dir = root / "docs" / "board" / "tasks"
    if tasks_dir.is_dir():
        counts: dict[str, int] = {}
        for path in tasks_dir.glob("*.md"):
            text = path.read_text(encoding="utf-8", errors="replace")
            match = re.search(r"^status:\s*(\S+)", text, re.MULTILINE)
            if match:
                counts[match.group(1)] = counts.get(match.group(1), 0) + 1
        lines.append("Board: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return "\n".join(lines)


# --- CLI ---------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Atomically claim local work-board files and resources.")
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--session", default=None, help=f"session id to act as (default: ${SESSION_ENV_VAR})")
    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=DEFAULT_STALE_AFTER_SECONDS,
        help=(
            f"age at which a legacy (session-less) claim is dropped (default {DEFAULT_STALE_AFTER_SECONDS}s). "
            f"Anything below {MINIMUM_STALE_AFTER_SECONDS}s is refused: it would delete claims a lane "
            "is still actively working behind. Session-attributed claims ignore this and are "
            f"dropped only when their session has been silent for {SESSION_DEAD_AFTER_SECONDS}s."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    claim_parser = commands.add_parser("claim", help="create a claim")
    claim_parser.add_argument("--role", required=True)
    claim_parser.add_argument("--work-item", required=True)
    claim_parser.add_argument("--file", dest="files", action="append", default=[])
    claim_parser.add_argument("--resource", dest="resources", action="append", default=[])
    commands.add_parser("list", help="show active claims")
    release_parser = commands.add_parser("release", help="release a claim")
    release_parser.add_argument("claim_id")
    adopt_parser = commands.add_parser("adopt", help="take over a dead session's claim as your own")
    adopt_parser.add_argument("claim_id")
    commands.add_parser("sessions", help="show registered sessions and whether they are alive")
    commands.add_parser("whoami", help="show this session's record")
    commands.add_parser("status", help="what every terminal is doing, in plain text")
    message_parser = commands.add_parser("message", help="leave a message in another session's inbox")
    message_parser.add_argument("--to", required=True, help="lane label (lane-2), session id or prefix, or 'all'")
    message_parser.add_argument("text")
    inbox_parser = commands.add_parser("inbox", help="print this session's unread messages")
    inbox_parser.add_argument("--deliver", action="store_true", help="mark them delivered (moved aside)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.stale_after_seconds < 0:
        print("error: --stale-after-seconds must be zero or positive", file=sys.stderr)
        return 2
    if args.stale_after_seconds < MINIMUM_STALE_AFTER_SECONDS:
        print(
            f"error: --stale-after-seconds {args.stale_after_seconds} is below the "
            f"{MINIMUM_STALE_AFTER_SECONDS}s floor. Pruning is age-only, so this would "
            "delete claims a live lane is still working behind. If a claim is genuinely "
            "abandoned, release it by id.",
            file=sys.stderr,
        )
        return 2
    session_id = current_session_id(args.session)
    try:
        if args.command == "claim":
            result = claim(state_dir=args.state_dir, role=args.role, work_item=args.work_item, files=args.files, resources=args.resources, stale_after_seconds=args.stale_after_seconds, session_id=session_id)
            print(json.dumps(asdict(result), sort_keys=True))
        elif args.command == "list":
            result = list_claims(state_dir=args.state_dir, stale_after_seconds=args.stale_after_seconds)
            print(json.dumps([asdict(item) for item in result], sort_keys=True))
        elif args.command == "release":
            result = release(state_dir=args.state_dir, claim_id=args.claim_id, stale_after_seconds=args.stale_after_seconds)
            print(json.dumps(asdict(result), sort_keys=True))
        elif args.command == "adopt":
            result = adopt(state_dir=args.state_dir, claim_id=args.claim_id, session_id=session_id, stale_after_seconds=args.stale_after_seconds)
            print(json.dumps(asdict(result), sort_keys=True))
        elif args.command == "sessions":
            now = _utc_now()
            rows = [{**asdict(s), "alive": session_is_alive(s, now=now), "me": s.session_id == session_id} for s in load_sessions(args.state_dir)]
            print(json.dumps(rows, sort_keys=True))
        elif args.command == "whoami":
            session = load_session(args.state_dir, session_id) if session_id else None
            if session is None:
                raise ClaimError(f"this shell has no registered session; is {SESSION_ENV_VAR} exported?")
            print(json.dumps({**asdict(session), "alive": True}, sort_keys=True))
        elif args.command == "status":
            print(status_report(args.state_dir, session_id=session_id))
        elif args.command == "message":
            me = load_session(args.state_dir, session_id) if session_id else None
            paths = send_message(args.state_dir, to=args.to, text=args.text, sender_id=session_id, sender_lane=me.lane if me else "")
            print(json.dumps([p.as_posix() for p in paths]))
        elif args.command == "inbox":
            if not session_id:
                raise ClaimError(f"no session id; export {SESSION_ENV_VAR} or pass --session")
            for message in read_inbox(args.state_dir, session_id, deliver=args.deliver):
                print(message)
                print("---")
    except ClaimError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
