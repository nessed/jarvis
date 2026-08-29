"""Windows Scheduled Task management via ``schtasks``.

Every value (task name, command, schedule type) is its own argument-list
entry passed straight to ``subprocess.run``, never a formatted shell string
-- a payload-controlled ``command`` cannot break out of its argument.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

Runner = Callable[..., subprocess.CompletedProcess]


class ScheduledTaskNotFoundError(Exception):
    """Raised when a query targets a task ``schtasks`` does not know about."""


@dataclass(frozen=True)
class ScheduledTaskInfo:
    name: str
    status: str | None = None
    next_run_time: str | None = None


def _run(args: Sequence[str], *, run: Runner, check: bool = True) -> subprocess.CompletedProcess:
    return run(list(args), capture_output=True, text=True, check=check)


def create_scheduled_task(
    name: str,
    command: str,
    schedule: str,
    *,
    start_time: str | None = None,
    start_date: str | None = None,
    run: Runner = subprocess.run,
) -> None:
    """Create (or overwrite, ``/f``) a scheduled task via ``schtasks /create``.

    ``schedule`` is passed straight through to schtasks' own ``/sc`` value
    (e.g. ``ONCE``, ``DAILY``, ``HOURLY``, ``ONLOGON``, ``ONSTART``) -- this
    module does not re-validate the enum, since ``schtasks`` itself rejects
    an unrecognized one loudly and clearly.
    """
    args = ["schtasks", "/create", "/tn", name, "/tr", command, "/sc", schedule, "/f"]
    if start_time:
        args += ["/st", start_time]
    if start_date:
        args += ["/sd", start_date]
    _run(args, run=run)


def delete_scheduled_task(name: str, *, run: Runner = subprocess.run) -> None:
    """Delete a scheduled task by name via ``schtasks /delete /f`` (no confirmation prompt)."""
    _run(["schtasks", "/delete", "/tn", name, "/f"], run=run)


def query_scheduled_task(name: str, *, run: Runner = subprocess.run) -> ScheduledTaskInfo:
    """Look up one scheduled task's status/next-run-time by exact name.

    Raises :class:`ScheduledTaskNotFoundError` when ``schtasks /query``
    exits non-zero (its own signal that the named task does not exist),
    rather than returning a half-populated :class:`ScheduledTaskInfo`.
    """
    result = _run(["schtasks", "/query", "/tn", name, "/fo", "LIST"], run=run, check=False)
    if result.returncode != 0:
        raise ScheduledTaskNotFoundError(name)
    status: str | None = None
    next_run: str | None = None
    for line in (result.stdout or "").splitlines():
        if line.startswith("Status:"):
            status = line.split(":", 1)[1].strip()
        elif line.startswith("Next Run Time:"):
            next_run = line.split(":", 1)[1].strip()
    return ScheduledTaskInfo(name=name, status=status, next_run_time=next_run)


def list_scheduled_tasks(*, run: Runner = subprocess.run) -> list[str]:
    """Every scheduled task's name, parsed from ``schtasks /query /fo CSV /nh``."""
    result = _run(["schtasks", "/query", "/fo", "CSV", "/nh"], run=run)
    names: list[str] = []
    for line in (result.stdout or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        first_field = stripped.split('","')[0].strip('"')
        names.append(first_field.lstrip("\\"))
    return names
