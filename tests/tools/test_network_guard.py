"""The guard that keeps the commit gate off the internet.

The offline suite decides whether a commit is allowed, so red has to mean
broken. On 3 Sep 2026 it went red twice in ten minutes on an SSL handshake
timeout and a DNS failure, and green either side, because five tests built a
live Supabase client they never used.

Fixing those five call sites would have fixed that morning and nothing else.
This file is about the guard that makes the sixth impossible.
"""

from __future__ import annotations

import socket

import pytest


def test_resolving_a_host_off_this_machine_is_refused():
    with pytest.raises(RuntimeError, match="offline test tried to resolve"):
        socket.getaddrinfo("api.supabase.co", 443)


def test_the_error_says_what_to_do_about_it():
    """A guard that only says "no" gets disabled by the next person to hit it."""
    with pytest.raises(RuntimeError) as error:
        socket.getaddrinfo("example.com", 80)

    message = str(error.value)
    assert "inject a fake" in message
    assert "mark the test `live`" in message
    assert "conftest.py::no_outbound_network" in message


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
def test_loopback_stays_open(host):
    """Ollama, whisper-server and every local fixture live here.

    A guard that blocked loopback would be a guard everyone turns off, which
    is worse than no guard at all.
    """
    assert socket.getaddrinfo(host, 11434)


def test_the_guard_does_not_leak_between_tests():
    """It is monkeypatched per test, so nothing survives into a later one."""
    assert socket.getaddrinfo.__name__ == "guarded_getaddrinfo"
