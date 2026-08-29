"""Blueprint 2.4: pywinauto targets for Zoom's native-dialog tail and WhatsApp Desktop send.

Two job kinds live here, each a thin ``JobHandler`` (see
``executor/app_automation/handler.py``) over pure, independently-tested
functions -- the same split ``executor/flp/sort.py`` and
``executor/handlers/whatsapp.py`` already use. Every function that touches a
real window is injected with a :class:`WindowConnector` and operates on
:class:`Control` objects, so the pure orchestration logic can be unit-tested
against a fake control tree with zero real UI Automation (UIA) calls -- the
same reason ``executor.flp.sort`` takes an injectable ``loader``/``saver``
instead of calling PyFLP directly.

**The one sharp edge (WhatsApp):** nothing in this package may send a real
WhatsApp message as part of its own operation, including its own test suite.
See ``executor/app_automation/whatsapp_desktop.py``'s module docstring and
``docs/tasks/pywinauto-zoom-whatsapp-report.md`` for the full statement of
that rule -- it is not optional caution, it is the actual rule.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol


class Control(Protocol):
    """The slice of pywinauto's control surface this package depends on.

    A real pywinauto ``WindowSpecification``/wrapper object satisfies this
    structurally (pywinauto proxies these methods via ``__getattr__``), so no
    adapter class is needed for the real backend -- only for tests, where a
    small hand-written fake stands in. Keeping this Protocol narrow (rather
    than depending on pywinauto's full surface) is what makes the fake cheap
    to write and keeps a test from accidentally depending on a pywinauto
    behavior nobody meant to pin.
    """

    def exists(self, timeout: float = 0.0) -> bool: ...

    def wait(self, wait_for: str, timeout: float = 10.0) -> "Control": ...

    def click_input(self) -> None: ...

    def type_keys(self, text: str, **kwargs: Any) -> None: ...

    def window_text(self) -> str: ...

    def texts(self) -> list[str]: ...

    def children(self, **kwargs: Any) -> list["Control"]: ...

    def child_window(self, **kwargs: Any) -> "Control": ...

    def set_focus(self) -> "Control": ...


# Attaches to a top-level window by exact title within ``timeout`` seconds,
# returning ``None`` (not raising) if it never appears -- distinguishing "this
# dialog is genuinely optional and didn't show up" (a normal outcome for,
# e.g., Zoom's passcode dialog when the URL scheme already carried a valid
# ``pwd``) from a real failure elsewhere in the chain. Injectable so tests
# supply a fake registry of already-built fake windows instead of a real
# ``pywinauto.Application.connect``.
WindowConnector = Callable[[str, float], "Control | None"]


class VerificationFailed(Exception):
    """Base for this package's "read the state back, it didn't stick" errors.

    Raised only after an action has already been taken -- never in place of
    taking it -- matching ``executor.flp.sort.FlpSortVerificationFailed``:
    a type-only diagnostic that ``executor.poller.poll_once``'s existing
    retry/backoff/dead-letter path already knows how to handle, so neither
    Zoom nor WhatsApp automation needs to invent a new failure shape.
    """


def poll_until(
    predicate: Callable[[], bool], *, timeout: float, interval: float = 0.25
) -> bool:
    """Poll ``predicate`` until it is true or ``timeout`` elapses.

    The explicit-wait primitive every action in this package is built on, per
    blueprint 2.4's own instruction ("explicit waits ... do not assume the
    click landed"). Never a bare ``time.sleep`` for a guessed duration --
    every wait in this package either polls a real control's UIA-reported
    state through this function or blocks on pywinauto's own
    ``Control.wait(...)``, which does the same polling internally.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def first_existing(
    candidates: Sequence[str],
    *,
    connect: WindowConnector,
    timeout: float,
) -> tuple[str, "Control"] | None:
    """Try each candidate window title in order; return the first that appears.

    Zoom's Home window title changed from "Zoom" to "Zoom Workplace" in the
    2023 rebrand (confirmed live 29 Aug 2026 -- see the report), and dialog
    titles are locale-dependent. Rather than pin one title and go stale the
    next time either changes, callers pass every title they know of and this
    tries them in order, spending at most ``timeout`` seconds total (split
    evenly) rather than ``timeout`` per candidate.
    """
    if not candidates:
        return None
    per_candidate_timeout = max(timeout / len(candidates), 0.1)
    for title in candidates:
        window = connect(title, per_candidate_timeout)
        if window is not None:
            return title, window
    return None
