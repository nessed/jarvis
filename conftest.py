"""Repository-wide pytest configuration: where scratch directories are allowed to live.

Two constraints, and they pull in opposite directions.

**The system TEMP is locked down on this machine.** A bare ``pytest`` run
errors out en masse in ``tmp_path`` setup with ``PermissionError``, which looks
exactly like a red suite. Every command in ``CLAUDE.md`` and the pre-commit
hook therefore hand-carried ``--basetemp=...`` for weeks.

**But a fixed ``--basetemp`` is shared state, and lanes run in parallel.**
Pytest *empties* an explicitly given basetemp at session start, so two
concurrent sessions delete each other's live ``tmp_path`` directories. On
2 Sep 2026 that cost real time: two full-suite runs failed on *different*
``tests/voice/`` tests, each of which passed in isolation, and a third run was
green. It reads exactly like a flaky suite and is not one.

``PYTEST_DEBUG_TEMPROOT`` resolves both. It moves the root off the locked-down
system TEMP without pinning a single directory, so pytest keeps its own
``pytest-<n>`` numbering underneath it — and that numbering is
concurrency-safe by construction: each session claims its own number, and the
cleanup that prunes old ones takes a lock and skips directories still in use.

Set here rather than in ``pytest.ini`` because ``addopts`` cannot set an
environment variable, and a bare ``pytest -q`` has to work — a flag that has to
be remembered is a flag that will be forgotten, which is how the hand-carried
version got into two documents and a hook in the first place.

Read lazily by ``TempPathFactory.getbasetemp()`` on first ``tmp_path`` use, so
conftest import time is comfortably early enough. ``setdefault``, so an
explicit ``PYTEST_DEBUG_TEMPROOT`` or ``--basetemp`` on the command line still
wins for one-off diagnosis.
"""

from __future__ import annotations

import os
from pathlib import Path

TEMPROOT = Path(__file__).parent / ".pytest-temp"

TEMPROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(TEMPROOT))


import socket

import pytest

_LOOPBACK = {"localhost", "127.0.0.1", "::1", "0.0.0.0", ""}


@pytest.fixture(autouse=True)
def no_outbound_network(request, monkeypatch):
    """Fail any default-suite test that reaches a host off this machine.

    The offline suite is the gate on every commit, and its entire value is
    that red means broken. On 3 Sep 2026 four tests in ``tests/status/`` went
    red twice in ten minutes -- once on an SSL handshake timeout, once on
    ``getaddrinfo failed`` -- while passing either side of it. They were
    building a live Supabase client they never used, because they called
    ``create_app()`` without ``jobs=`` and ``bus/main.py`` falls back to
    ``SupabaseJobsRepository.from_env()``.

    Injecting a fake at those four call sites would have fixed that morning
    and nothing else: the fifth test to forget ``jobs=`` brings it straight
    back, and the symptom looks like whatever else changed that hour. This is
    the version that holds.

    **Loopback stays open**, deliberately. Ollama, whisper-server and every
    local fixture live there, and a guard that blocked them would be a guard
    everyone disables. Only addresses off this machine are refused.

    ``live``-marked tests are exempt: reaching real providers is what they are
    for, and they are deselected from the default run anyway.
    """
    if "live" in request.keywords:
        return

    real_getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host, port, *args, **kwargs):
        if isinstance(host, str) and host.lower() not in _LOOPBACK:
            raise RuntimeError(
                f"offline test tried to resolve {host!r}. The default suite must not "
                "touch the network -- inject a fake, or mark the test `live`. See "
                "conftest.py::no_outbound_network."
            )
        return real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
