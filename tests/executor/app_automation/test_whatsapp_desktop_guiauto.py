"""The one test that sends a REAL WhatsApp message. Ali runs this, watching. Nobody else.

Per the lane brief's sharp edge: this lane built and unit-tested the whole
send flow (``test_whatsapp_desktop.py``) against a fake control tree and
never once drove the real, installed WhatsApp Desktop app. This file is the
deliberate exception the brief asks for -- a real end-to-end probe against
the real app -- and it is designed to never run itself:

1. Marked ``guiauto`` (see ``pytest.ini`` -- CORE still needs to add
   ``and not guiauto`` to ``addopts`` and register the marker, matching
   ``live``/``realflp``; this lane could not edit that file, see the report).
2. Independently gated on an environment variable that is never set in any
   automated run, so it self-skips even if step 1 is missed or a future
   change to ``pytest.ini`` accidentally lets ``guiauto`` through.
3. Requires Ali to name the exact chat himself via a second environment
   variable -- this file never hardcodes a real contact or group, and the
   message text is fixed to something unambiguous so nothing this test sends
   could be mistaken for a real message from Ali.

To run it (once, watching, never delegated):

    $env:JARVIS_GUIAUTO_WHATSAPP_SEND_CONFIRM = "i-am-watching"
    $env:JARVIS_GUIAUTO_WHATSAPP_CHAT = "<exact chat/contact name, e.g. yourself>"
    .venv\\Scripts\\python.exe -m pytest -q -m guiauto tests/executor/app_automation/test_whatsapp_desktop_guiauto.py

with WhatsApp Desktop already running and logged in.
"""

from __future__ import annotations

import os

import pytest

from executor.app_automation.handler import _default_connector
from executor.app_automation.whatsapp_desktop import WhatsAppMessageTarget, build_send_message

pytestmark = pytest.mark.guiauto

_CONFIRM_VAR = "JARVIS_GUIAUTO_WHATSAPP_SEND_CONFIRM"
_CHAT_VAR = "JARVIS_GUIAUTO_WHATSAPP_CHAT"
_CONFIRM_VALUE = "i-am-watching"

# Fixed and unambiguous on purpose -- this test's whole point is that nothing
# it sends could ever be mistaken for something Ali meant to say to someone.
_TEST_MESSAGE = "[JARVIS guiauto test] pywinauto-zoom-whatsapp lane self-check -- safe to ignore/delete."


@pytest.fixture(autouse=True)
def _require_a_human_watching() -> None:
    if os.environ.get(_CONFIRM_VAR) != _CONFIRM_VALUE:
        pytest.skip(
            f"guiauto: sends a REAL WhatsApp message from Ali's personal number. "
            f"Only run this yourself, watching. Set {_CONFIRM_VAR}={_CONFIRM_VALUE!r} "
            f"and {_CHAT_VAR}=<exact chat name> for this run only."
        )


def _target_chat() -> str:
    chat = os.environ.get(_CHAT_VAR)
    if not chat:
        pytest.skip(f"{_CHAT_VAR} is not set; no chat named to send the test message to")
    return chat


def test_sends_a_labeled_test_message_to_the_named_chat_and_verifies_it_posted() -> None:
    send = build_send_message(connect=_default_connector())

    send(WhatsAppMessageTarget(chat_name=_target_chat(), text=_TEST_MESSAGE))
