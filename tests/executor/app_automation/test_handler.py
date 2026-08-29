"""Unit tests for executor.app_automation.handler -- dispatch, against fakes.

Confirms the one built handler correctly routes ``zoom_join_meeting`` and
``whatsapp_desktop_send_message`` jobs to their respective modules, and
rejects anything else. Every real-UIA dependency is injected as a fake; see
``conftest.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from db.jobs import Job
from executor.app_automation import zoom
from executor.app_automation.handler import (
    WHATSAPP_DESKTOP_SEND_MESSAGE_JOB_KIND,
    ZOOM_JOIN_MEETING_JOB_KIND,
    MissingPayloadField,
    UnknownAppAutomationJobKind,
    build_app_automation_handler,
)
from executor.app_automation.whatsapp_desktop import WHATSAPP_WINDOW_TITLE, CHAT_LIST_CONTAINER_NAME
from tests.executor.app_automation.conftest import FakeConnectorRegistry, FakeControl


def _job(kind: str, payload: dict[str, object]) -> Job:
    now = datetime.now(UTC)
    return Job(
        id="job-1",
        kind=kind,
        payload=payload,
        status="running",
        checkpoint={},
        run_after=now,
        created_at=now,
        updated_at=now,
    )


class TestZoomDispatch:
    def test_joins_a_meeting_with_the_payload_fields(self) -> None:
        registry = FakeConnectorRegistry({zoom.IN_MEETING_VERIFY_NAMES[0]: FakeControl(name="Leave")})
        opened: list[str] = []
        handler = build_app_automation_handler(connect=registry, open_zoom_url=opened.append)

        handler(_job(ZOOM_JOIN_MEETING_JOB_KIND, {"meeting_id": "555", "passcode": "1234"}))

        assert len(opened) == 1
        assert "confno=555" in opened[0]
        assert "pwd=1234" in opened[0]

    def test_raises_missing_payload_field_without_a_meeting_id(self) -> None:
        registry = FakeConnectorRegistry()
        handler = build_app_automation_handler(connect=registry, open_zoom_url=lambda _u: None)

        with pytest.raises(MissingPayloadField):
            handler(_job(ZOOM_JOIN_MEETING_JOB_KIND, {}))


class TestWhatsAppDispatch:
    def _registry_ready_to_send(self) -> FakeConnectorRegistry:
        chat_row = FakeControl(name="Team Standup 3:14 pm see you then", control_type="DataItem")
        chat_list = FakeControl(name=CHAT_LIST_CONTAINER_NAME, control_type="DataGrid", children=[chat_row])
        compose = FakeControl(name="Type a message", control_type="Edit")
        message_row = FakeControl(name="", control_type="DataItem")

        def _post() -> None:
            message_row.name = compose.name

        send_button = FakeControl(name="Send", control_type="Button", on_click=_post)
        window = FakeControl(name="WhatsApp", children=[chat_list, compose, send_button, message_row])
        return FakeConnectorRegistry({WHATSAPP_WINDOW_TITLE: window})

    def test_sends_a_message_with_the_payload_fields(self) -> None:
        registry = self._registry_ready_to_send()
        handler = build_app_automation_handler(connect=registry)

        handler(
            _job(
                WHATSAPP_DESKTOP_SEND_MESSAGE_JOB_KIND,
                {"chat_name": "Team Standup", "text": "On my way"},
            )
        )
        # No exception raised means find -> compose -> send -> verify all
        # succeeded; a failure at any step would have raised WhatsAppSendFailed.

    def test_raises_missing_payload_field_without_chat_name(self) -> None:
        registry = FakeConnectorRegistry()
        handler = build_app_automation_handler(connect=registry)

        with pytest.raises(MissingPayloadField):
            handler(_job(WHATSAPP_DESKTOP_SEND_MESSAGE_JOB_KIND, {"text": "hi"}))

    def test_raises_missing_payload_field_without_text(self) -> None:
        registry = FakeConnectorRegistry()
        handler = build_app_automation_handler(connect=registry)

        with pytest.raises(MissingPayloadField):
            handler(_job(WHATSAPP_DESKTOP_SEND_MESSAGE_JOB_KIND, {"chat_name": "Team Standup"}))


class TestUnknownKind:
    def test_raises_for_a_job_kind_this_handler_does_not_own(self) -> None:
        registry = FakeConnectorRegistry()
        handler = build_app_automation_handler(connect=registry)

        with pytest.raises(UnknownAppAutomationJobKind):
            handler(_job("some_other_job_kind", {}))
