"""Shared fakes for executor.app_automation tests.

A hand-written double for the narrow ``executor.app_automation.Control``
Protocol, plus a small registry-backed ``WindowConnector``. No test in this
package (or any package under ``tests/executor/app_automation/``, other than
the one dedicated ``guiauto``-marked, environment-gated test) ever imports
``pywinauto`` or touches real UI Automation -- see the sharp-edge notice in
``executor/app_automation/whatsapp_desktop.py``.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest


class NotFoundControl:
    """What a real pywinauto ``WindowSpecification`` acts like when its
    criteria match nothing: lazy, so building it never raises, but every
    action on it does.
    """

    def exists(self, timeout: float = 0.0) -> bool:
        return False

    def wait(self, wait_for: str, timeout: float = 10.0):
        raise TimeoutError(f"no control found (waiting for {wait_for!r})")

    def click_input(self) -> None:
        raise RuntimeError("cannot click a control that was never found")

    def type_keys(self, text: str, **kwargs) -> None:
        raise RuntimeError("cannot type into a control that was never found")

    def window_text(self) -> str:
        raise RuntimeError("control was never found")

    def texts(self) -> list[str]:
        raise RuntimeError("control was never found")

    def children(self, **kwargs) -> list:
        return []

    def child_window(self, **kwargs) -> "NotFoundControl":
        return self

    def set_focus(self):
        raise RuntimeError("cannot focus a control that was never found")


class FakeControl:
    """A fake control tree node standing in for a real pywinauto wrapper.

    ``children`` are this control's direct descendants -- every production
    function in this package only ever searches direct children (matching
    how each real dialog/window is driven one level at a time), so a fake
    tree only needs to be as deep as each test requires.
    """

    def __init__(
        self,
        name: str = "",
        control_type: str = "Pane",
        *,
        auto_id: str = "",
        children: list["FakeControl"] | None = None,
        exists_value: bool = True,
        on_click: Callable[[], None] | None = None,
    ) -> None:
        self.name = name
        self.control_type = control_type
        self.auto_id = auto_id
        self._children = list(children or [])
        self._exists = exists_value
        self._on_click = on_click
        self.click_calls = 0
        self.typed: list[str] = []
        self.focused = False

    def exists(self, timeout: float = 0.0) -> bool:
        return self._exists

    def wait(self, wait_for: str, timeout: float = 10.0) -> "FakeControl":
        if not self._exists:
            raise TimeoutError(f"control {self.name!r} never became {wait_for!r}")
        return self

    def click_input(self) -> None:
        self.click_calls += 1
        if self._on_click is not None:
            self._on_click()

    def type_keys(self, text: str, **kwargs) -> None:
        self.typed.append(text)
        self.name = f"{self.name}{text}"

    def window_text(self) -> str:
        return self.name

    def texts(self) -> list[str]:
        return [self.name] if self.name else []

    def children(self, control_type: str | None = None, **kwargs) -> list["FakeControl"]:
        if control_type is None:
            return list(self._children)
        return [c for c in self._children if c.control_type == control_type]

    def child_window(
        self,
        *,
        title: str | None = None,
        title_re: str | None = None,
        control_type: str | None = None,
        auto_id: str | None = None,
        found_index: int | None = None,
        **_: object,
    ):
        candidates = list(self._children)
        if control_type is not None:
            candidates = [c for c in candidates if c.control_type == control_type]
        if title is not None:
            candidates = [c for c in candidates if c.name == title]
        if title_re is not None:
            pattern = re.compile(title_re)
            candidates = [c for c in candidates if pattern.search(c.name)]
        if auto_id is not None:
            candidates = [c for c in candidates if c.auto_id == auto_id]
        if not candidates:
            return NotFoundControl()
        if found_index is not None:
            try:
                return candidates[found_index]
            except IndexError:
                return NotFoundControl()
        return candidates[0]

    def set_focus(self) -> "FakeControl":
        self.focused = True
        return self


class FakeConnectorRegistry:
    """A ``WindowConnector`` backed by an in-memory ``{title: FakeControl}`` map.

    ``connect(title, timeout)`` returns ``None`` for a title never
    registered -- the same "this dialog genuinely did not appear" signal a
    real timed-out ``pywinauto.Application.connect`` is translated into by
    ``executor.app_automation.handler._default_connector``.
    """

    def __init__(self, windows: dict[str, FakeControl] | None = None) -> None:
        self.windows = dict(windows or {})
        self.calls: list[tuple[str, float]] = []

    def connect(self, title: str, timeout: float) -> FakeControl | None:
        self.calls.append((title, timeout))
        return self.windows.get(title)

    def __call__(self, title: str, timeout: float) -> FakeControl | None:
        return self.connect(title, timeout)


@pytest.fixture
def registry() -> FakeConnectorRegistry:
    return FakeConnectorRegistry()
