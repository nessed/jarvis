"""Blueprint 2.4: wraps Zoom join and WhatsApp send as one ``JobHandler``.

Follows ``executor/flp/sort.py``'s split: pure, independently-tested
functions underneath (``zoom.py``, ``whatsapp_desktop.py``), a thin handler
here that reads a job's payload, dispatches on ``job.kind``, and turns
failures into whatever this codebase's handlers already raise -- nothing new.
Both raised exception types (:class:`~executor.app_automation.zoom.ZoomJoinFailed`,
:class:`~executor.app_automation.whatsapp_desktop.WhatsAppSendFailed`) are
plain ``Exception`` subclasses, so ``executor.poller.poll_once``'s existing
retry/backoff/dead-letter path already handles them the same way it handles
every other handler failure -- see that module's docstring.

Registration -- not done here, CORE's job once this lane and its sibling
(``laptop-system-control.md``) both land, per the lane brief:

    "zoom_join_meeting": HandlerRegistration(build_app_automation_handler()),
    "whatsapp_desktop_send_message": HandlerRegistration(build_app_automation_handler()),

(the same built handler instance for both kinds -- it dispatches internally
on ``job.kind``, so one registration line per kind pointing at the one
instance is enough; see :func:`build_app_automation_handler`.)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from executor.app_automation import WindowConnector
from executor.app_automation.whatsapp_desktop import WhatsAppMessageTarget, build_send_message
from executor.app_automation.zoom import ZoomMeetingTarget, join_meeting

logger = logging.getLogger(__name__)

ZOOM_JOIN_MEETING_JOB_KIND = "zoom_join_meeting"
WHATSAPP_DESKTOP_SEND_MESSAGE_JOB_KIND = "whatsapp_desktop_send_message"


class UnknownAppAutomationJobKind(Exception):
    """Raised when this handler is invoked for a ``job.kind`` it does not own.

    Should not happen in practice -- ``executor.poller`` only ever calls the
    handler registered for a given kind -- but is a clear, named failure
    instead of a silent no-op or a raw ``KeyError`` if a registration is ever
    miswired.
    """


class MissingPayloadField(Exception):
    """Raised when a job's payload is missing a field this handler requires.

    A permanent, not transient, problem -- retrying the same payload cannot
    make a missing field appear -- but ``executor.poller.poll_once`` has no
    registered permanent-failure type for this package (see its own
    ``except (ReorderNotSupported, FileNotFoundError)`` clause, which this
    module cannot add to without editing a file outside this lane's
    ownership). It therefore retries to exhaustion and then dead-letters,
    the same outcome ``executor.handlers.whatsapp`` already accepts for its
    own unrecoverable-payload cases. Named here for CORE to reconsider if it
    ever wires a broader permanent-failure list.
    """


def _default_connector() -> WindowConnector:
    """The real UIA connector: ``pywinauto``, imported lazily.

    Imported inside the function, not at module load, so importing this
    module (and therefore ``executor.poller``, which will register it) never
    requires a display/UIA session to be available -- matching how
    ``executor.handlers.whatsapp``'s default sender is only constructed
    inside its own closure, not at import time.
    """
    from pywinauto.application import Application
    from pywinauto.timings import TimeoutError as PywinautoTimeoutError

    def _connect(title: str, timeout: float):
        try:
            app = Application(backend="uia").connect(title=title, timeout=timeout)
            return app.top_window()
        except (PywinautoTimeoutError, Exception):
            return None

    return _connect


def build_app_automation_handler(
    *,
    connect: WindowConnector | None = None,
    open_zoom_url: Callable[[str], None] | None = None,
) -> Callable[[Any], None]:
    """Build the one handler both ``zoom_join_meeting`` and
    ``whatsapp_desktop_send_message`` jobs are registered against.

    ``connect`` defaults to a real pywinauto-backed :data:`WindowConnector`
    (built lazily, see :func:`_default_connector`); tests inject a fake.
    Dispatch is purely on ``job.kind`` -- the two job kinds share no payload
    shape and are handled by entirely separate modules underneath.
    """
    connector = connect or _default_connector()
    send_whatsapp_message = build_send_message(connect=connector)

    def _handle(job: Any) -> None:
        if job.kind == ZOOM_JOIN_MEETING_JOB_KIND:
            _handle_zoom_join(job, connector, open_zoom_url)
        elif job.kind == WHATSAPP_DESKTOP_SEND_MESSAGE_JOB_KIND:
            _handle_whatsapp_send(job, send_whatsapp_message)
        else:
            raise UnknownAppAutomationJobKind(job.kind)

    return _handle


def _handle_zoom_join(job: Any, connector: WindowConnector, open_zoom_url: Callable[[str], None] | None) -> None:
    payload = job.payload
    meeting_id = payload.get("meeting_id")
    if not meeting_id:
        raise MissingPayloadField("zoom_join_meeting job payload missing required field 'meeting_id'")
    target = ZoomMeetingTarget(
        meeting_id=str(meeting_id),
        passcode=payload.get("passcode"),
        display_name=payload.get("display_name"),
        audio_device=payload.get("audio_device"),
    )
    join_meeting(target, connect=connector, open_url=open_zoom_url)


def _handle_whatsapp_send(job: Any, send_whatsapp_message: Callable[[WhatsAppMessageTarget], None]) -> None:
    payload = job.payload
    chat_name = payload.get("chat_name")
    text = payload.get("text")
    if not chat_name:
        raise MissingPayloadField("whatsapp_desktop_send_message job payload missing required field 'chat_name'")
    if not text:
        raise MissingPayloadField("whatsapp_desktop_send_message job payload missing required field 'text'")
    send_whatsapp_message(WhatsAppMessageTarget(chat_name=str(chat_name), text=str(text)))
