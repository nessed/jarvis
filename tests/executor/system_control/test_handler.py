"""Tests for executor.system_control.handler: dispatch, argument extraction,
and error propagation for the ``system_control`` job kind.

Real actions are unit-tested in their own modules
(test_power.py/test_scheduled_tasks.py/test_printing.py/test_files.py/
test_processes.py); these tests exercise ``build_system_control_handler``'s
own logic -- unknown action, missing arg, and dispatch -- via the ``actions``
override seam, plus one end-to-end proof that the wifi guard reaches the
handler layer using the *real* action registry with fakes underneath.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from executor.system_control import power
from executor.system_control.handler import (
    MissingSystemControlArgError,
    SystemControlDeps,
    UnknownSystemControlActionError,
    build_system_control_handler,
)


@dataclass
class _FakeJob:
    id: str
    payload: dict[str, Any]


def test_unknown_action_raises() -> None:
    handler = build_system_control_handler(actions={})

    with pytest.raises(UnknownSystemControlActionError):
        handler(_FakeJob(id="1", payload={"action": "power.teleport", "args": {}}))


def test_missing_action_key_raises_unknown_action() -> None:
    handler = build_system_control_handler(actions={})

    with pytest.raises(UnknownSystemControlActionError):
        handler(_FakeJob(id="1", payload={"args": {}}))


def test_dispatch_calls_the_registered_action_with_args() -> None:
    calls = []

    def fake_action(args):
        calls.append(args)

    handler = build_system_control_handler(actions={"file.move": fake_action})

    handler(_FakeJob(id="1", payload={"action": "file.move", "args": {"src": "a", "dst": "b"}}))

    assert calls == [{"src": "a", "dst": "b"}]


def test_dispatch_defaults_missing_args_to_empty_dict() -> None:
    calls = []

    def fake_action(args):
        calls.append(args)

    handler = build_system_control_handler(actions={"scheduled_task.list": fake_action})

    handler(_FakeJob(id="1", payload={"action": "scheduled_task.list"}))

    assert calls == [{}]


def test_default_registry_missing_required_arg_raises() -> None:
    handler = build_system_control_handler(
        deps=SystemControlDeps(subprocess_run=lambda *a, **k: None)
    )

    with pytest.raises(MissingSystemControlArgError):
        handler(_FakeJob(id="1", payload={"action": "power.set_plan", "args": {}}))


@dataclass
class _FakeResult:
    stdout: str = ""
    returncode: int = 0


@dataclass
class _RecordingRunner:
    calls: list[dict] = field(default_factory=list)

    def __call__(self, args, **kwargs):
        self.calls.append({"args": list(args), "kwargs": kwargs})
        return _FakeResult()


def test_wifi_guard_propagates_through_the_real_registry_end_to_end() -> None:
    """Simulates "Wi-Fi is this machine's active default-route adapter" at the
    handler layer, through the real (non-overridden) action registry -- the
    same sharp edge proven directly in test_power.py, proven again here at
    the dispatch boundary a real system_control job would actually go
    through."""
    runner = _RecordingRunner()
    deps = SystemControlDeps(
        subprocess_run=runner,
        default_route_interface_fn=lambda *, run: "Wi-Fi",
    )
    handler = build_system_control_handler(deps=deps)

    with pytest.raises(power.WifiGuardError):
        handler(
            _FakeJob(
                id="1",
                payload={"action": "wifi.set_enabled", "args": {"interface": "Wi-Fi", "enabled": False}},
            )
        )

    # The disabling netsh command must never have been reached.
    assert runner.calls == []


def test_wifi_enable_request_is_never_guarded_through_the_handler() -> None:
    runner = _RecordingRunner()
    deps = SystemControlDeps(
        subprocess_run=runner,
        default_route_interface_fn=lambda *, run: "Wi-Fi",
    )
    handler = build_system_control_handler(deps=deps)

    handler(
        _FakeJob(
            id="1",
            payload={"action": "wifi.set_enabled", "args": {"interface": "Wi-Fi", "enabled": True}},
        )
    )

    assert runner.calls[0]["args"][-1] == "admin=enabled"


def test_process_kill_action_forwards_args_to_processes_module(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_kill_process(**kwargs):
        captured.update(kwargs)
        return [123]

    from executor.system_control import processes as processes_module

    monkeypatch.setattr(processes_module, "kill_process", fake_kill_process)
    handler = build_system_control_handler()

    handler(_FakeJob(id="1", payload={"action": "process.kill", "args": {"name": "notepad.exe"}}))

    assert captured["name"] == "notepad.exe"
    assert captured["pid"] is None


def test_files_root_override_is_forwarded_to_file_actions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    from executor.system_control import files as files_module

    def fake_move_file(src, dst, *, root=None):
        captured["root"] = root
        return tmp_path / "moved.txt"

    monkeypatch.setattr(files_module, "move_file", fake_move_file)
    handler = build_system_control_handler(deps=SystemControlDeps(files_root=tmp_path))

    handler(
        _FakeJob(id="1", payload={"action": "file.move", "args": {"src": "a", "dst": "b"}})
    )

    assert captured["root"] == tmp_path
