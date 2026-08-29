"""Real-Zoom probe for the join-dialog tail. Not run by this lane -- see below.

This lane could not capture the real passcode/audio-device/popup dialogs
live: driving Zoom into an actual meeting (clicking Home's "NEW" instant-
meeting button) was blocked by this environment's own safety classifier
before any join occurred, and no personal test meeting was available under
that constraint (see ``executor/app_automation/zoom.py``'s module docstring
and ``docs/tasks/pywinauto-zoom-whatsapp-report.md``). The dialog-tail
functions were therefore built against researched, multi-candidate
identifiers and are unit-tested only against a fake control tree
(``test_zoom.py``).

This file is the real-app probe that would confirm or correct those
identifiers, gated the same way as the WhatsApp guiauto test: marked
``guiauto`` (excluded from the default run once ``pytest.ini`` is updated --
see the report), and independently gated on an environment variable so it
never runs itself even so. Joining your own instant meeting is lower-stakes
than a WhatsApp send (nothing is delivered to anyone else), but it is still a
real join against a real Zoom account, so it gets the same explicit,
watched-by-a-human gate.

To run it (once, watching):

    $env:JARVIS_GUIAUTO_ZOOM_JOIN_CONFIRM = "i-am-watching"
    $env:JARVIS_GUIAUTO_ZOOM_MEETING_ID = "<a personal instant-meeting ID>"
    # $env:JARVIS_GUIAUTO_ZOOM_PASSCODE = "<its passcode, if any>"
    .venv\\Scripts\\python.exe -m pytest -q -m guiauto tests/executor/app_automation/test_zoom_guiauto.py

with Zoom Workplace already running and logged in, and a personal instant
meeting already started (Zoom account -> New Meeting) so there is something
real to join the dialog tail against.
"""

from __future__ import annotations

import os

import pytest

from executor.app_automation.handler import _default_connector
from executor.app_automation.zoom import ZoomMeetingTarget, join_meeting

pytestmark = pytest.mark.guiauto

_CONFIRM_VAR = "JARVIS_GUIAUTO_ZOOM_JOIN_CONFIRM"
_MEETING_ID_VAR = "JARVIS_GUIAUTO_ZOOM_MEETING_ID"
_PASSCODE_VAR = "JARVIS_GUIAUTO_ZOOM_PASSCODE"
_CONFIRM_VALUE = "i-am-watching"


@pytest.fixture(autouse=True)
def _require_a_human_watching() -> None:
    if os.environ.get(_CONFIRM_VAR) != _CONFIRM_VALUE:
        pytest.skip(
            f"guiauto: joins a REAL Zoom meeting. Only run this yourself, watching a "
            f"personal instant meeting. Set {_CONFIRM_VAR}={_CONFIRM_VALUE!r} and "
            f"{_MEETING_ID_VAR}=<meeting id> for this run only."
        )


def _target_meeting() -> ZoomMeetingTarget:
    meeting_id = os.environ.get(_MEETING_ID_VAR)
    if not meeting_id:
        pytest.skip(f"{_MEETING_ID_VAR} is not set; no meeting named to join")
    return ZoomMeetingTarget(meeting_id=meeting_id, passcode=os.environ.get(_PASSCODE_VAR))


def test_joins_the_named_meeting_and_verifies_the_in_meeting_toolbar() -> None:
    join_meeting(_target_meeting(), connect=_default_connector())
