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
