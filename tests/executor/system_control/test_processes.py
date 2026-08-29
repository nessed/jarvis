"""Tests for executor.system_control.processes.

Nothing here touches a real process: ``psutil.process_iter``/``psutil.Process``
are always injected as fakes. The protection guard is exercised directly
(``is_protected_process``) and through ``kill_process`` for every named
protected case: this executor's own pid, ``cloudflared.exe``, and
``python.exe``/``pythonw.exe`` running under this repo's own ``.venv`` -- plus
the negative case, a same-named python.exe from an unrelated install, which
must NOT be protected (the guard is scoped to this repo's venv, not every
Python on the machine).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from executor.system_control import processes


@dataclass
class _FakeProcess:
    pid: int
    _name: str
    _exe: str | None = None
    terminated: bool = False

    def name(self) -> str:
        return self._name

    def exe(self) -> str:
        if self._exe is None:
            raise Exception("no exe on this fake")
        return self._exe

    def terminate(self) -> None:
        self.terminated = True


class _FakeNoSuchProcess(Exception):
    pass


VENV_DIR = Path("C:/repo/.venv").resolve()
OTHER_VENV_DIR = Path("C:/other/venv").resolve()


# ---------------------------------------------------------------------------
# is_protected_process
# ---------------------------------------------------------------------------


def test_own_pid_is_always_protected() -> None:
    proc = _FakeProcess(pid=111, _name="notepad.exe")
    assert processes.is_protected_process(proc, own_pid=111, venv_dir=VENV_DIR) is True


def test_cloudflared_is_always_protected() -> None:
    proc = _FakeProcess(pid=222, _name="cloudflared.exe")
    assert processes.is_protected_process(proc, own_pid=999, venv_dir=VENV_DIR) is True


def test_python_under_repo_venv_is_protected() -> None:
    proc = _FakeProcess(pid=333, _name="python.exe", _exe=str(VENV_DIR / "Scripts" / "python.exe"))
    assert processes.is_protected_process(proc, own_pid=999, venv_dir=VENV_DIR) is True


def test_pythonw_under_repo_venv_is_protected() -> None:
    proc = _FakeProcess(pid=334, _name="pythonw.exe", _exe=str(VENV_DIR / "Scripts" / "pythonw.exe"))
    assert processes.is_protected_process(proc, own_pid=999, venv_dir=VENV_DIR) is True


def test_python_under_a_different_venv_is_not_protected() -> None:
    """The guard is scoped to this repo's own .venv, not every Python process."""
    proc = _FakeProcess(pid=335, _name="python.exe", _exe=str(OTHER_VENV_DIR / "Scripts" / "python.exe"))
    assert processes.is_protected_process(proc, own_pid=999, venv_dir=VENV_DIR) is False


def test_unrelated_process_is_not_protected() -> None:
    proc = _FakeProcess(pid=444, _name="notepad.exe", _exe="C:/Windows/notepad.exe")
    assert processes.is_protected_process(proc, own_pid=999, venv_dir=VENV_DIR) is False


def test_protection_check_never_matches_by_substring() -> None:
    """"pythonw.exe.fake" and "not-cloudflared.exe" must not match."""
    proc = _FakeProcess(pid=445, _name="pythonw.exe.fake")
    assert processes.is_protected_process(proc, own_pid=999, venv_dir=VENV_DIR) is False
    proc2 = _FakeProcess(pid=446, _name="not-cloudflared.exe")
    assert processes.is_protected_process(proc2, own_pid=999, venv_dir=VENV_DIR) is False


# ---------------------------------------------------------------------------
# kill_process
# ---------------------------------------------------------------------------


def _process_iter_returning(*procs: _FakeProcess):
    def _iter(*args, **kwargs):
        return list(procs)

    return _iter


def test_kill_process_requires_exactly_one_of_name_or_pid() -> None:
    with pytest.raises(processes.InvalidKillTargetError):
        processes.kill_process()
    with pytest.raises(processes.InvalidKillTargetError):
        processes.kill_process(name="notepad.exe", pid=123)


def test_kill_process_by_name_terminates_the_exact_match() -> None:
    target = _FakeProcess(pid=555, _name="notepad.exe")
    other = _FakeProcess(pid=556, _name="wordpad.exe")

    killed = processes.kill_process(
        name="notepad.exe",
        own_pid=1,
        venv_dir=VENV_DIR,
        process_iter=_process_iter_returning(target, other),
        process_factory=lambda pid: None,
    )

    assert killed == [555]
    assert target.terminated is True
    assert other.terminated is False


def test_kill_process_by_name_is_case_insensitive() -> None:
    target = _FakeProcess(pid=557, _name="notepad.exe")

    killed = processes.kill_process(
        name="NOTEPAD.EXE",
        own_pid=1,
        venv_dir=VENV_DIR,
        process_iter=_process_iter_returning(target),
        process_factory=lambda pid: None,
    )

    assert killed == [557]


def test_kill_process_by_name_raises_when_nothing_matches() -> None:
    with pytest.raises(processes.ProcessNotFoundError):
        processes.kill_process(
            name="ghost.exe",
            own_pid=1,
            venv_dir=VENV_DIR,
            process_iter=_process_iter_returning(),
            process_factory=lambda pid: None,
        )


def test_kill_process_by_pid_uses_process_factory() -> None:
    target = _FakeProcess(pid=558, _name="notepad.exe")

    killed = processes.kill_process(
        pid=558,
        own_pid=1,
        venv_dir=VENV_DIR,
        process_iter=_process_iter_returning(),
        process_factory=lambda pid: target,
    )

    assert killed == [558]
    assert target.terminated is True


def test_kill_process_by_pid_raises_process_not_found() -> None:
    def _factory(pid):
        raise _FakeNoSuchProcess()

    with pytest.raises(processes.ProcessNotFoundError):
        processes.kill_process(
            pid=999999,
            own_pid=1,
            venv_dir=VENV_DIR,
            process_iter=_process_iter_returning(),
            process_factory=_factory,
            no_such_process=_FakeNoSuchProcess,
        )


def test_kill_process_refuses_its_own_pid() -> None:
    own = _FakeProcess(pid=42, _name="python.exe", _exe=str(VENV_DIR / "Scripts" / "python.exe"))

    with pytest.raises(processes.ProtectedProcessError):
        processes.kill_process(
            pid=42,
            own_pid=42,
            venv_dir=VENV_DIR,
            process_iter=_process_iter_returning(),
            process_factory=lambda pid: own,
        )
    assert own.terminated is False


def test_kill_process_refuses_cloudflared_by_name() -> None:
    tunnel = _FakeProcess(pid=77, _name="cloudflared.exe")

    with pytest.raises(processes.ProtectedProcessError):
        processes.kill_process(
            name="cloudflared.exe",
            own_pid=1,
            venv_dir=VENV_DIR,
            process_iter=_process_iter_returning(tunnel),
            process_factory=lambda pid: None,
        )
    assert tunnel.terminated is False


def test_kill_process_refuses_repo_venv_python_by_name() -> None:
    executor = _FakeProcess(pid=88, _name="python.exe", _exe=str(VENV_DIR / "Scripts" / "python.exe"))

    with pytest.raises(processes.ProtectedProcessError):
        processes.kill_process(
            name="python.exe",
            own_pid=1,
            venv_dir=VENV_DIR,
            process_iter=_process_iter_returning(executor),
            process_factory=lambda pid: None,
        )
    assert executor.terminated is False


def test_kill_process_allows_python_from_an_unrelated_venv() -> None:
    other = _FakeProcess(pid=89, _name="python.exe", _exe=str(OTHER_VENV_DIR / "Scripts" / "python.exe"))

    killed = processes.kill_process(
        name="python.exe",
        own_pid=1,
        venv_dir=VENV_DIR,
        process_iter=_process_iter_returning(other),
        process_factory=lambda pid: None,
    )

    assert killed == [89]
    assert other.terminated is True


def test_kill_process_checks_every_candidate_before_killing_any() -> None:
    """One protected match among several same-named processes must stop the
    whole call -- no partial kill."""
    safe = _FakeProcess(pid=90, _name="python.exe", _exe=str(OTHER_VENV_DIR / "Scripts" / "python.exe"))
    protected = _FakeProcess(pid=91, _name="python.exe", _exe=str(VENV_DIR / "Scripts" / "python.exe"))

    with pytest.raises(processes.ProtectedProcessError):
        processes.kill_process(
            name="python.exe",
            own_pid=1,
            venv_dir=VENV_DIR,
            process_iter=_process_iter_returning(safe, protected),
            process_factory=lambda pid: None,
        )

    assert safe.terminated is False
    assert protected.terminated is False
