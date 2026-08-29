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


# --- tunnel_protocol -------------------------------------------------------
#
# http2 is forced by default because QUIC (UDP 7844) is unroutable on this
# network -- see the module docstring's "cloudflared prefers QUIC" comment.


def test_tunnel_protocol_defaults_to_http2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(start_jarvis.TUNNEL_PROTOCOL_ENV, raising=False)

    assert start_jarvis.tunnel_protocol() == "http2"


def test_tunnel_protocol_honours_the_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(start_jarvis.TUNNEL_PROTOCOL_ENV, "quic")

    assert start_jarvis.tunnel_protocol() == "quic"


def test_tunnel_protocol_strips_whitespace_from_the_override() -> None:
    settings = {start_jarvis.TUNNEL_PROTOCOL_ENV: "  quic  "}

    assert start_jarvis.tunnel_protocol(settings) == "quic"


def test_tunnel_protocol_falls_back_to_default_when_the_override_is_blank() -> None:
    settings = {start_jarvis.TUNNEL_PROTOCOL_ENV: "   "}

    assert start_jarvis.tunnel_protocol(settings) == start_jarvis.DEFAULT_TUNNEL_PROTOCOL


def test_tunnel_protocol_reads_an_explicit_environ_rather_than_os_environ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(start_jarvis.TUNNEL_PROTOCOL_ENV, "quic")

    # An explicit (empty) environ must win over the real process environment,
    # or a caller could never test the default in isolation.
    assert start_jarvis.tunnel_protocol({}) == "http2"


# --- resolves_on_public_dns -------------------------------------------------
#
# The ISP resolver on this machine lags on freshly-minted Quick Tunnel
# hostnames; this check asks 1.1.1.1 and 8.8.8.8 instead, because Meta does
# its own resolution and a tunnel this machine can't look up may still be
# reachable from the internet.

_HOST = "abc-def-123.trycloudflare.com"
_URL = f"https://{_HOST}"


def _fake_nslookup(monkeypatch: pytest.MonkeyPatch, responses: dict) -> list:
    """``responses`` maps resolver -> stdout string, or an exception instance to raise."""
    calls: list[tuple[str, str]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args[0] == "nslookup"
        host, resolver = args[1], args[2]
        calls.append((host, resolver))
        outcome = responses[resolver]
        if isinstance(outcome, Exception):
            raise outcome
        return subprocess.CompletedProcess(args, 0, outcome, "")

    monkeypatch.setattr(start_jarvis.subprocess, "run", fake_run)
    return calls


def test_resolves_on_public_dns_true_when_the_first_resolver_finds_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = f"Server: one.one.one.one\nAddress: 1.1.1.1\n\nName: {_HOST}\nAddress: 1.2.3.4\n"
    calls = _fake_nslookup(monkeypatch, {"1.1.1.1": stdout})

    assert start_jarvis.resolves_on_public_dns(_URL) is True
    # Short-circuits: the second resolver is never tried once the first answers.
    assert calls == [(_HOST, "1.1.1.1")]


def test_resolves_on_public_dns_falls_through_to_the_second_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = f"Server: dns.google\nAddress: 8.8.8.8\n\nName: {_HOST}\nAddress: 1.2.3.4\n"
    calls = _fake_nslookup(monkeypatch, {"1.1.1.1": OSError("unreachable"), "8.8.8.8": stdout})

    assert start_jarvis.resolves_on_public_dns(_URL) is True
    assert calls == [(_HOST, "1.1.1.1"), (_HOST, "8.8.8.8")]


def test_resolves_on_public_dns_false_when_neither_resolver_finds_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nxdomain = f"Server: one.one.one.one\n** server can't find {_HOST}: NXDOMAIN\n"
    calls = _fake_nslookup(monkeypatch, {"1.1.1.1": nxdomain, "8.8.8.8": nxdomain})

    assert start_jarvis.resolves_on_public_dns(_URL) is False
    assert calls == [(_HOST, "1.1.1.1"), (_HOST, "8.8.8.8")]


def test_resolves_on_public_dns_false_when_both_resolvers_are_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_nslookup(
        monkeypatch,
        {"1.1.1.1": subprocess.TimeoutExpired(cmd="nslookup", timeout=15), "8.8.8.8": OSError("boom")},
    )

    assert start_jarvis.resolves_on_public_dns(_URL) is False


# --- wait_for_tunnel_url -----------------------------------------------------
#
# The polling loop that waits for cloudflared to mint a URL in its log file.


def test_tunnel_url_pattern_ignores_the_quick_tunnel_provisioning_api() -> None:
    failed_provisioning = (
        'failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel": '
        "dial tcp [2606:4700::6810:e684]:443: connectex"
    )

    assert start_jarvis.TUNNEL_URL_PATTERN.search(failed_provisioning) is None


def test_tunnel_url_pattern_finds_a_minted_url_after_a_provisioning_error() -> None:
    log = (
        'failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel"\n'
        "INF Your quick Tunnel has been created! https://foo-bar.trycloudflare.com\n"
    )

    found = start_jarvis.TUNNEL_URL_PATTERN.search(log)

    assert found is not None
    assert found.group(0) == "https://foo-bar.trycloudflare.com"


def test_wait_for_tunnel_url_finds_a_url_already_present(tmp_path) -> None:
    log = tmp_path / "cloudflared.log"
    log.write_text("some preamble\nhttps://foo-bar.trycloudflare.com\nmore\n", encoding="utf-8")

    assert start_jarvis.wait_for_tunnel_url(log) == "https://foo-bar.trycloudflare.com"


def test_wait_for_tunnel_url_polls_until_the_url_is_written(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "cloudflared.log"
    log.write_text("", encoding="utf-8")
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        log.write_text("https://foo-bar.trycloudflare.com\n", encoding="utf-8")

    monkeypatch.setattr(start_jarvis.time, "sleep", fake_sleep)

    result = start_jarvis.wait_for_tunnel_url(log, timeout=5)

    assert result == "https://foo-bar.trycloudflare.com"
    assert len(sleeps) == 1


def test_wait_for_tunnel_url_returns_none_without_sleeping_past_an_exhausted_deadline(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(seconds: float) -> None:
        raise AssertionError("must not sleep once the deadline has already passed")

    monkeypatch.setattr(start_jarvis.time, "sleep", forbidden)

    assert start_jarvis.wait_for_tunnel_url(tmp_path / "never-created.log", timeout=0) is None


def test_wait_for_tunnel_url_gives_up_when_no_match_appears_before_the_timeout(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "cloudflared.log"
    log.write_text("cloudflared starting, no url yet\n", encoding="utf-8")
    # Two in-loop checks that stay under the deadline, then one that exceeds it.
    clock = iter([0.0, 0.1, 0.2, 100.0])
    monkeypatch.setattr(start_jarvis.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(start_jarvis.time, "sleep", lambda seconds: None)

    assert start_jarvis.wait_for_tunnel_url(log, timeout=1) is None


# --- Supervisor.shutdown -----------------------------------------------------
#
# The Ctrl+C / child-death handling: terminate every live child, wait up to a
# shared 10s deadline, and kill anything still alive when it passes. Nothing
# here spawns a real process.


class FakeProcess:
    def __init__(self, *, already_dead: bool = False, hangs: bool = False) -> None:
        self._already_dead = already_dead
        self.hangs = hangs
        self.terminated = False
        self.killed = False
        self.wait_calls: list[float] = []

    def poll(self):
        return 0 if self._already_dead else None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float) -> None:
        self.wait_calls.append(timeout)
        if self.hangs:
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)

    def kill(self) -> None:
        self.killed = True


def test_shutdown_terminates_a_live_child_and_waits_for_it(capsys: pytest.CaptureFixture[str]) -> None:
    supervisor = start_jarvis.Supervisor()
    process = FakeProcess()
    supervisor.children.append(("bus", process))

    supervisor.shutdown()

    assert process.terminated is True
    assert process.wait_calls
    assert process.killed is False
    assert "stopping bus" in capsys.readouterr().out


def test_shutdown_kills_a_child_that_does_not_die_within_the_deadline() -> None:
    supervisor = start_jarvis.Supervisor()
    process = FakeProcess(hangs=True)
    supervisor.children.append(("tunnel", process))

    supervisor.shutdown()

    assert process.terminated is True
    assert process.killed is True


def test_shutdown_does_not_terminate_a_child_that_already_died(
    capsys: pytest.CaptureFixture[str],
) -> None:
    supervisor = start_jarvis.Supervisor()
    process = FakeProcess(already_dead=True)
    supervisor.children.append(("executor", process))

    supervisor.shutdown()

    assert process.terminated is False
    # The wait loop is unconditional -- an already-dead child is still waited on.
    assert process.wait_calls
    assert process.killed is False
    assert "stopping executor" not in capsys.readouterr().out


def test_shutdown_stops_children_in_reverse_spawn_order(capsys: pytest.CaptureFixture[str]) -> None:
    supervisor = start_jarvis.Supervisor()
    supervisor.children.append(("bus", FakeProcess()))
    supervisor.children.append(("tunnel", FakeProcess()))
    supervisor.children.append(("executor", FakeProcess()))

    supervisor.shutdown()

    output = capsys.readouterr().out
    assert output.index("stopping executor") < output.index("stopping tunnel") < output.index("stopping bus")
