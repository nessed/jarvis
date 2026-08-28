"""A liveness marker so batch jobs can tell the executor is running.

Ollama is a single serial resource. A batch pass over the corpus drives the
same local model every reply depends on, so running one while the executor is
polling starves live messages for as long as it lasts — that is exactly what
happened on 26 August 2026, when a backfill left eight inbound messages
sitting unclaimed (``docs/history/whatsapp-reply-failures.md``).

The executor touches a file each poll; batch tools check its age and refuse to
start. A timestamp rather than a PID lock is deliberate: if the executor is
killed the marker simply goes stale on its own, so a crash can never leave a
lock behind that blocks every future batch run.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

DEFAULT_HEARTBEAT_PATH = Path(".executor-heartbeat")

# Generous against the executor's default 5s poll interval: a slow job holds the
# loop for its whole duration without touching the file, and a handler may run
# for minutes. Only a genuinely stopped executor should read as stale.
DEFAULT_MAX_AGE_SECONDS = 600.0


def heartbeat_path(environ: dict[str, str] | None = None) -> Path:
    settings = os.environ if environ is None else environ
    return Path(settings.get("JARVIS_EXECUTOR_HEARTBEAT", str(DEFAULT_HEARTBEAT_PATH)))


def touch(path: Path | None = None) -> None:
    """Record that the executor is alive right now. Never raises."""
    target = path or heartbeat_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        # A missing heartbeat only costs a batch tool its guard; it must never
        # take down the poll loop.
        pass


def clear(path: Path | None = None) -> None:
    """Remove the heartbeat marker on a deliberate, clean stop. Never raises.

    Only call this from a clean-exit path (a caught ``KeyboardInterrupt``).
    A crash must leave the marker in place to go stale on its own -- that
    fail-open staleness, not an always-cleared marker, is what lets a killed
    executor never leave a lock that blocks a future batch run past
    ``max_age_seconds``. Mirrors :func:`touch`'s error handling: an ``OSError``
    (e.g. the file is already gone) is silently swallowed rather than raised.
    """
    target = path or heartbeat_path()
    try:
        target.unlink()
    except OSError:
        # Already gone, or some other filesystem hiccup -- either way this
        # must never take down a clean shutdown.
        pass


def seconds_since_heartbeat(path: Path | None = None) -> float | None:
    """Age of the marker in seconds, or ``None`` if there isn't a readable one."""
    target = path or heartbeat_path()
    try:
        recorded = float(target.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    age = time.time() - recorded
    return age if age >= 0 else 0.0


def executor_is_live(
    path: Path | None = None, *, max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS
) -> bool:
    """Whether an executor has reported in recently enough to still be polling."""
    age = seconds_since_heartbeat(path)
    return age is not None and age <= max_age_seconds


def refuse_if_executor_is_live(
    tool_name: str, *, path: Path | None = None, max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS
) -> str | None:
    """Return an explanatory message if ``tool_name`` should not start now."""
    age = seconds_since_heartbeat(path)
    if age is None or age > max_age_seconds:
        return None
    return (
        f"The executor is running (last poll {age:.0f}s ago). {tool_name} drives the same "
        "local Ollama that live replies need, and running both starves incoming messages.\n"
        "Stop the executor first, or pass --force if you accept slow replies while this runs."
    )
