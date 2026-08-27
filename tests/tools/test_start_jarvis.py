"""The single-instance guard on the launcher.

Every test here binds a port the OS handed out, never ``DEFAULT_SINGLETON_PORT``,
so a JARVIS that is actually running on this machine cannot turn the suite red.
Nothing in this file starts, stops, kills or signals a real process.
"""

from __future__ import annotations

import socket
import subprocess

import pytest

from tools import start_jarvis


def free_port() -> int:
    """A port the OS says is free right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_acquiring_a_free_port_returns_a_socket_holding_it() -> None:
    port = free_port()

    lock = start_jarvis.acquire_singleton_lock(port)

    assert lock is not None
    try:
        assert lock.getsockname() == ("127.0.0.1", port)
    finally:
        lock.close()


def test_a_second_acquisition_of_the_same_port_fails() -> None:
    port = free_port()
    first = start_jarvis.acquire_singleton_lock(port)
    assert first is not None

    try:
        assert start_jarvis.acquire_singleton_lock(port) is None
    finally:
        first.close()


def test_the_lock_is_released_when_the_holder_closes_it() -> None:
    """The fail-open property: no released bind can wedge a future launch."""
    port = free_port()
    first = start_jarvis.acquire_singleton_lock(port)
    assert first is not None
    first.close()

    second = start_jarvis.acquire_singleton_lock(port)
    assert second is not None
    second.close()


def test_the_env_override_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    port = free_port()
    monkeypatch.setenv(start_jarvis.SINGLETON_PORT_ENV, str(port))

    assert start_jarvis.singleton_port() == port

    lock = start_jarvis.acquire_singleton_lock()
    assert lock is not None
    try:
        assert lock.getsockname()[1] == port
    finally:
        lock.close()


def test_the_default_port_collides_with_neither_the_bus_nor_ollama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(start_jarvis.SINGLETON_PORT_ENV, raising=False)

    assert start_jarvis.singleton_port() == start_jarvis.DEFAULT_SINGLETON_PORT
    assert start_jarvis.DEFAULT_SINGLETON_PORT not in (start_jarvis.BUS_PORT, 11434)


def test_a_held_port_makes_main_refuse_without_spawning_anything(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The regression that matters: no tunnel is minted and Meta is not re-pointed."""
    port = free_port()
    holder = start_jarvis.acquire_singleton_lock(port)
    assert holder is not None

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"the launcher started something: {args!r} {kwargs!r}")

    monkeypatch.setenv(start_jarvis.SINGLETON_PORT_ENV, str(port))
    monkeypatch.setattr(start_jarvis.Supervisor, "spawn", forbidden)
    monkeypatch.setattr(start_jarvis, "ollama_ready", forbidden)
    monkeypatch.setattr(start_jarvis, "wait_for_bus", forbidden)
    monkeypatch.setattr(start_jarvis, "wait_for_tunnel_url", forbidden)
    monkeypatch.setattr(start_jarvis, "tunnel_reachable", forbidden)
    monkeypatch.setattr(start_jarvis.subprocess, "run", forbidden)
    monkeypatch.setattr(start_jarvis, "pid_holding_port", lambda _port: 4242)

    try:
        exit_code = start_jarvis.main([])
    finally:
        holder.close()

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "already holds" in output
    assert str(port) in output
    assert "PID 4242" in output
    assert "nothing was started" in output
    assert "Ctrl+C" in output


def test_the_refusal_still_refuses_when_the_pid_cannot_be_found(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    port = free_port()
    holder = start_jarvis.acquire_singleton_lock(port)
    assert holder is not None

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("the launcher started something")

    monkeypatch.setenv(start_jarvis.SINGLETON_PORT_ENV, str(port))
    monkeypatch.setattr(start_jarvis.Supervisor, "spawn", forbidden)
    monkeypatch.setattr(start_jarvis.subprocess, "run", forbidden)
    monkeypatch.setattr(start_jarvis, "pid_holding_port", lambda _port: None)

    try:
        exit_code = start_jarvis.main([])
    finally:
        holder.close()

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "could not tell which process holds it" in output
    assert "nothing was started" in output


NETSTAT_SAMPLE = """
Active Connections

  Proto  Local Address          Foreign Address        State
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       2288
  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       9001
  TCP    127.0.0.1:8765         0.0.0.0:0              LISTENING       31337
  TCP    127.0.0.1:65432        127.0.0.1:8765         ESTABLISHED     777
  UDP    0.0.0.0:5353           *:*
"""


def _fake_netstat(
    monkeypatch: pytest.MonkeyPatch, stdout: str, returncode: int = 0
) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args[0] == "netstat"
        return subprocess.CompletedProcess(args, returncode, stdout, "")

    monkeypatch.setattr(start_jarvis.subprocess, "run", fake_run)


def test_pid_discovery_reads_the_listening_row_for_the_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_netstat(monkeypatch, NETSTAT_SAMPLE)

    assert start_jarvis.pid_holding_port(8765) == 31337


def test_pid_discovery_ignores_a_port_that_only_appears_as_a_remote_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_netstat(monkeypatch, NETSTAT_SAMPLE)

    assert start_jarvis.pid_holding_port(9999) is None


def test_pid_discovery_returns_none_when_netstat_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise OSError("netstat not found")

    monkeypatch.setattr(start_jarvis.subprocess, "run", explode)

    assert start_jarvis.pid_holding_port(8765) is None


def test_pid_discovery_returns_none_when_netstat_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_netstat(monkeypatch, "", returncode=1)

    assert start_jarvis.pid_holding_port(8765) is None
