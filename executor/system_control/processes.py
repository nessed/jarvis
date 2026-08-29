"""Process termination via psutil, guarded against killing the JARVIS stack itself.

Getting this guard wrong kills the job that's running the kill (and, for
``cloudflared.exe``, the tunnel the whole WhatsApp webhook depends on). Every
check below is an *exact* match -- process id equality, exact lowercased
process name, exact path containment under this repo's own ``.venv`` -- never
a substring or pattern match, so a payload cannot smuggle a protected target
past the guard by naming it loosely.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import psutil


class InvalidKillTargetError(Exception):
    """Raised when ``kill_process`` is called with zero or both of ``name``/``pid``."""


class ProcessNotFoundError(Exception):
    """Raised when the named process (or pid) is not currently running."""


class ProtectedProcessError(Exception):
    """Raised when a kill request targets this executor, its own venv Python, or cloudflared.

    See :func:`is_protected_process` for the exact guard. Deliberately an
    exception, not a silent skip: a caller asking to kill a protected
    process should get a loud, named refusal, not a job that quietly
    reports success without having done anything.
    """


_PROTECTED_EXACT_NAMES = frozenset({"cloudflared.exe"})
_PROTECTED_PYTHON_NAMES = frozenset({"python.exe", "pythonw.exe"})


def default_venv_dir() -> Path:
    """This repository's own ``.venv`` -- three parents up from this file."""
    return (Path(__file__).resolve().parent.parent.parent / ".venv").resolve()


def _process_name(proc: Any) -> str:
    try:
        return (proc.name() or "").lower()
    except Exception:
        return ""


def _process_exe(proc: Any) -> str | None:
    try:
        return proc.exe()
    except Exception:
        return None


def is_protected_process(proc: Any, *, own_pid: int, venv_dir: Path) -> bool:
    """True if ``proc`` is this executor, its own venv Python, or cloudflared.

    Guards, in order:

    1. ``proc.pid == own_pid`` -- never let a job kill the process running it.
    2. name is exactly ``cloudflared.exe`` -- the Cloudflare tunnel this
       laptop's WhatsApp webhook depends on, regardless of which process it is.
    3. name is ``python.exe``/``pythonw.exe`` *and* its executable path
       resolves under this repo's own ``.venv`` -- narrowly scoped to this
       stack's interpreter, not every Python process on the machine (a
       Python process from an unrelated venv or system install is not
       protected by this check).
    """
    if getattr(proc, "pid", None) == own_pid:
        return True
    name = _process_name(proc)
    if name in _PROTECTED_EXACT_NAMES:
        return True
    if name in _PROTECTED_PYTHON_NAMES:
        exe = _process_exe(proc)
        if exe:
            try:
                Path(exe).resolve().relative_to(venv_dir)
                return True
            except ValueError:
                pass
    return False


def kill_process(
    *,
    name: str | None = None,
    pid: int | None = None,
    own_pid: int | None = None,
    venv_dir: Path | None = None,
    process_iter: Callable[..., Iterable[Any]] = psutil.process_iter,
    process_factory: Callable[[int], Any] = psutil.Process,
    no_such_process: type[BaseException] = psutil.NoSuchProcess,
) -> list[int]:
    """Kill an exact-named process or an exact pid, refusing protected targets.

    Exactly one of ``name``/``pid`` is required -- never a substring/pattern
    match on name. Every candidate is checked against
    :func:`is_protected_process` *before* any process is terminated, so a
    batch of same-named matches either all proceed or none do -- one
    protected match among several stops the whole call rather than partially
    killing. Returns the pids actually signalled.
    """
    if (name is None) == (pid is None):
        raise InvalidKillTargetError("kill_process requires exactly one of name or pid")
    resolved_own_pid = os.getpid() if own_pid is None else own_pid
    resolved_venv_dir = (venv_dir if venv_dir is not None else default_venv_dir()).resolve()

    if pid is not None:
        try:
            candidates: list[Any] = [process_factory(pid)]
        except no_such_process as exc:
            raise ProcessNotFoundError(f"no process with pid {pid}") from exc
    else:
        target_name = name.lower()
        candidates = [proc for proc in process_iter() if _process_name(proc) == target_name]
        if not candidates:
            raise ProcessNotFoundError(f"no process named {name!r}")

    for proc in candidates:
        if is_protected_process(proc, own_pid=resolved_own_pid, venv_dir=resolved_venv_dir):
            raise ProtectedProcessError(
                f"refusing to kill protected process (pid={getattr(proc, 'pid', '?')}, "
                f"name={_process_name(proc)!r})"
            )

    killed: list[int] = []
    for proc in candidates:
        proc.terminate()
        killed.append(proc.pid)
    return killed
