"""The outcome-reply seam: an action says how it went, without knowing WhatsApp exists.

The property under test is the one the design turns on: **the action handlers
and the poller carry a generic ``notify`` descriptor and never learn who is
waiting or how to reach them.** Everything WhatsApp-shaped lives in exactly
two places — the enqueuer that writes the descriptor, and the
``whatsapp_outcome`` handler that sends.

The second property is that a broken notification never re-runs an action. A
send that raised inside ``system_control`` would make the poller retry the
whole job, so a failed message about ``process.kill`` would kill it again.

No Graph API, no Supabase, no real jobs table.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import pytest

from db.jobs import Job
from executor import notify
from executor.app_automation import zoom
from executor.app_automation.handler import (
    WHATSAPP_DESKTOP_SEND_MESSAGE_JOB_KIND,
    ZOOM_JOIN_MEETING_JOB_KIND,
    MissingPayloadField,
    build_app_automation_handler,
)
from executor.app_automation.whatsapp_desktop import (
    CHAT_LIST_CONTAINER_NAME,
    WHATSAPP_WINDOW_TITLE,
)
from executor.handlers.outcome import (
    WHATSAPP_OUTCOME_JOB_KIND,
    MissingOutcomeRecipient,
    build_whatsapp_outcome_handler,
    render_outcome,
)
from executor.notify import NOTIFY_FIELD, notify_descriptor
from executor.system_control.handler import build_system_control_handler, render_result
from tests.executor.app_automation.conftest import FakeConnectorRegistry, FakeControl

REPLY_TO = "923001234567"


def _job(kind: str, payload: dict[str, Any], **overrides: Any) -> Job:
    now = datetime.now(UTC)
    base = Job(
        id="job-1",
        kind=kind,
        payload=payload,
        status="running",
        checkpoint={},
        run_after=now,
        created_at=now,
        updated_at=now,
        attempts=1,
        max_attempts=3,
    )
    return replace(base, **overrides) if overrides else base


@dataclass
class RecordingQueue:
    """Just enough repository to watch what gets enqueued."""

    enqueued: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    raise_on_enqueue: Exception | None = None

    def enqueue(self, kind, payload, run_after=None, max_attempts=None) -> Job:
        if self.raise_on_enqueue is not None:
            raise self.raise_on_enqueue
        self.enqueued.append((kind, dict(payload)))
        now = datetime.now(UTC)
        return Job(
            id=f"outcome-{len(self.enqueued)}",
            kind=kind,
            payload=dict(payload),
            status="queued",
            checkpoint={},
            run_after=run_after or now,
            created_at=now,
            updated_at=now,
            attempts=0,
            max_attempts=max_attempts or 3,
        )


def _notified(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        NOTIFY_FIELD: notify_descriptor(
            WHATSAPP_OUTCOME_JOB_KIND, {"reply_to": REPLY_TO, "summary": "turn wifi off"}
        ),
    }


# --------------------------------------------------------------------------
# The seam itself.
# --------------------------------------------------------------------------


def test_an_action_nobody_asked_about_notifies_nobody():
    """Most jobs carry no descriptor, and the seam must cost them nothing."""
    queue = RecordingQueue()

    assert notify.enqueue_outcome(_job("system_control", {"action": "wifi.set_enabled"}),
                                  status=notify.STATUS_OK, repository=queue) is None
    assert queue.enqueued == []


def test_the_outcome_job_carries_the_descriptor_plus_what_happened():
    queue = RecordingQueue()

    notify.enqueue_outcome(
        _job("system_control", _notified({"action": "wifi.list_interfaces"})),
        status=notify.STATUS_OK,
        detail="Wi-Fi (connected)",
        repository=queue,
    )

    assert queue.enqueued == [
        (
            WHATSAPP_OUTCOME_JOB_KIND,
            {
                "reply_to": REPLY_TO,
                "summary": "turn wifi off",
                "status": "ok",
                "detail": "Wi-Fi (connected)",
                "action": "wifi.list_interfaces",
            },
        )
    ]


def test_a_notification_that_cannot_be_enqueued_never_fails_the_action():
    """The whole reason the outcome is a job and not a send.

    An action that ran and then could not be reported on is not an action that
    needs re-running. If this raised, the poller would retry ``process.kill``
    to redeliver a message about it.
    """
    queue = RecordingQueue(raise_on_enqueue=RuntimeError("supabase is down"))

    assert notify.enqueue_outcome(
        _job("system_control", _notified({"action": "process.kill"})),
        status=notify.STATUS_OK,
        repository=queue,
    ) is None


def test_a_malformed_descriptor_is_ignored_rather_than_raised():
    queue = RecordingQueue()
    for descriptor in [{}, {"kind": ""}, {"kind": 7}, "not-a-mapping", None]:
        job = _job("system_control", {"action": "wifi.set_enabled", NOTIFY_FIELD: descriptor})
        assert notify.enqueue_outcome(job, status=notify.STATUS_OK, repository=queue) is None
    assert queue.enqueued == []


def test_the_detail_is_bounded_because_the_jobs_table_is_hosted():
    queue = RecordingQueue()

    notify.enqueue_outcome(
        _job("system_control", _notified({"action": "scheduled_task.list"})),
        status=notify.STATUS_OK,
        detail="x" * 5000,
        repository=queue,
    )

    detail = queue.enqueued[0][1]["detail"]
    assert len(detail) == notify.MAX_DETAIL_CHARS
    assert detail.endswith("…")


def test_the_detail_is_flattened_to_one_line():
    assert notify.truncate_detail("a\n  b\tc") == "a b c"
    assert notify.truncate_detail(None) == ""


# --------------------------------------------------------------------------
# The action handlers.
# --------------------------------------------------------------------------


def test_system_control_reports_the_result_and_not_merely_done():
    """Half these actions are questions, and "done" is not an answer to one."""
    queue = RecordingQueue()
    handler = build_system_control_handler(
        actions={"wifi.list_interfaces": lambda args: [{"name": "Wi-Fi", "state": "connected"}]}
    )

    job = _job("system_control", _notified({"action": "wifi.list_interfaces", "args": {}}))
    _run_with_queue(handler, job, queue)

    assert queue.enqueued[0][1]["detail"] == "Wi-Fi (connected)"
    assert queue.enqueued[0][1]["status"] == "ok"


def test_a_setter_adds_no_detail_because_the_reply_already_names_the_action():
    """"Done: turn wifi off. wifi.set_enabled done." is the same sentence twice."""
    assert render_result("wifi.set_enabled", None) == ""
    assert render_outcome({"status": "ok", "summary": "turn wifi off", "detail": ""}) == (
        "Done: turn wifi off."
    )


def test_render_result_survives_every_shape_an_action_returns():
    assert render_result("a", "already text") == "already text"
    assert render_result("a", {"name": "Balanced"}) == "name: Balanced"
    assert render_result("a", []) == "a: nothing"
    assert render_result("a", [{"name": "Wi-Fi", "state": "up"}, {"name": "Eth"}]) == (
        "Wi-Fi (up); Eth"
    )
    assert render_result("a", [1, 2]) == "1; 2"
    assert render_result("a", 42) == "42"


def test_a_uia_action_confirms_it_happened_without_quoting_the_user():
    """These return nothing, so the confirmation *is* the value.

    It must not echo the payload back: the chat name and the message text came
    from the user, and quoting them into a hosted queue row buys nothing that
    "sent it" does not already say.
    """
    queue = RecordingQueue()
    handler = build_app_automation_handler(connect=_whatsapp_desktop_ready_to_send())

    job = _job(
        WHATSAPP_DESKTOP_SEND_MESSAGE_JOB_KIND,
        _notified({"chat_name": "Team Standup", "text": "On my way"}),
    )
    _run_with_queue(handler, job, queue)

    assert queue.enqueued[0][1]["detail"] == "sent it on WhatsApp Desktop"
    assert "On my way" not in str(queue.enqueued[0][1])
    assert "Team Standup" not in str(queue.enqueued[0][1])


def test_a_zoom_join_confirms_it_happened():
    queue = RecordingQueue()
    registry = FakeConnectorRegistry({zoom.IN_MEETING_VERIFY_NAMES[0]: FakeControl(name="Leave")})
    handler = build_app_automation_handler(connect=registry, open_zoom_url=lambda url: None)

    job = _job(ZOOM_JOIN_MEETING_JOB_KIND, _notified({"meeting_id": "555"}))
    _run_with_queue(handler, job, queue)

    assert queue.enqueued[0][1]["detail"] == "joined the Zoom meeting"


def test_a_uia_action_that_fails_notifies_nothing_itself():
    """The failure reply comes from the poller's terminal path, not from here.

    The handler raises and never reaches its own notify call, which is exactly
    right: the job is about to be retried, and one message per attempt would
    be three messages for one action.
    """
    queue = RecordingQueue()
    handler = build_app_automation_handler(connect=FakeConnectorRegistry())

    with pytest.raises(MissingPayloadField):
        _run_with_queue(
            handler, _job(WHATSAPP_DESKTOP_SEND_MESSAGE_JOB_KIND, _notified({"text": "hi"})), queue
        )

    assert queue.enqueued == []


def _whatsapp_desktop_ready_to_send() -> FakeConnectorRegistry:
    """The same fake window ``tests/executor/app_automation`` drives."""
    chat_row = FakeControl(name="Team Standup 3:14 pm see you then", control_type="DataItem")
    chat_list = FakeControl(
        name=CHAT_LIST_CONTAINER_NAME, control_type="DataGrid", children=[chat_row]
    )
    compose = FakeControl(name="Type a message", control_type="Edit")
    message_row = FakeControl(name="", control_type="DataItem")
    send_button = FakeControl(
        name="Send", control_type="Button", on_click=lambda: setattr(message_row, "name", compose.name)
    )
    window = FakeControl(name="WhatsApp", children=[chat_list, compose, send_button, message_row])
    return FakeConnectorRegistry({WHATSAPP_WINDOW_TITLE: window})


# --------------------------------------------------------------------------
# Sending.
# --------------------------------------------------------------------------


def test_the_outcome_handler_sends_to_the_recipient_the_descriptor_named():
    sent: list[dict[str, str]] = []
    handler = build_whatsapp_outcome_handler(
        send_text_message=lambda *, to, text: sent.append({"to": to, "text": text}) or "wamid.1"
    )

    handler(
        _job(
            WHATSAPP_OUTCOME_JOB_KIND,
            {
                "reply_to": REPLY_TO,
                "summary": "list wifi interfaces",
                "status": "ok",
                "detail": "Wi-Fi (connected)",
            },
        )
    )

    assert sent == [
        {"to": REPLY_TO, "text": "Done: list wifi interfaces. Wi-Fi (connected)."}
    ]


def test_a_failed_action_still_gets_a_reply_and_says_what_broke():
    """Silence is worst exactly here."""
    assert render_outcome(
        {"status": "failed", "summary": "turn wifi off", "detail": "OSError: unavailable"}
    ) == "That didn't work — turn wifi off failed (OSError: unavailable)."

    assert render_outcome({"status": "failed", "summary": "turn wifi off", "detail": ""}) == (
        "That didn't work — turn wifi off failed."
    )


def test_an_outcome_with_no_recipient_is_a_bug_and_dead_letters():
    handler = build_whatsapp_outcome_handler(send_text_message=lambda **kw: "wamid.1")

    for payload in [{}, {"reply_to": ""}, {"reply_to": 7}]:
        with pytest.raises(MissingOutcomeRecipient):
            handler(_job(WHATSAPP_OUTCOME_JOB_KIND, payload))


def test_the_outcome_path_cannot_re_enter_the_command_classifier():
    """Structural, not a flag: this module imports neither half of the classifier."""
    import executor.handlers.outcome as outcome_module

    source = (
        __import__("pathlib").Path(outcome_module.__file__).read_text(encoding="utf-8")
    )
    body = source.split('"""', 2)[-1]  # skip the module docstring, which names them
    assert "classify_command" not in body
    assert "parse_inbound_message" not in body


def _run_with_queue(handler, job: Job, queue: RecordingQueue) -> None:
    """Run a handler with ``db.jobs``'s default repository replaced by a fake."""
    import db.jobs as jobs_module

    original = jobs_module._repository_or_default
    jobs_module._repository_or_default = lambda repository=None: repository or queue
    try:
        handler(job)
    finally:
        jobs_module._repository_or_default = original
