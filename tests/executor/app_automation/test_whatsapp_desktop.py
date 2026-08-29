"""Unit tests for executor.app_automation.whatsapp_desktop -- fake trees only.

**Sharp edge, restated:** every test in this file drives a
:class:`FakeControl` tree (``conftest.py``), never the real WhatsApp Desktop
app. No test here may call anything that would send a real WhatsApp message.
The one test that would exercise the real app lives in
``test_whatsapp_desktop_guiauto.py``, is marked ``guiauto``, is additionally
gated on an environment variable, and this lane never ran it -- see
``docs/tasks/pywinauto-zoom-whatsapp-report.md``.

Fixture chat names/messages below are entirely invented for these tests --
never any of Ali's real contacts, which this lane saw briefly while
inspecting the real app's control tree and immediately discarded (see
``executor/app_automation/whatsapp_desktop.py``'s module docstring).
"""

from __future__ import annotations

import pytest

from executor.app_automation import whatsapp_desktop as wa
from tests.executor.app_automation.conftest import FakeConnectorRegistry, FakeControl


def _chat_row(name: str) -> FakeControl:
    return FakeControl(name=name, control_type="DataItem")


def _window_with_chat_list(*rows: FakeControl, extra_children: list[FakeControl] | None = None) -> FakeControl:
    chat_list = FakeControl(name=wa.CHAT_LIST_CONTAINER_NAME, control_type="DataGrid", children=list(rows))
    return FakeControl(name="WhatsApp", children=[chat_list, *(extra_children or [])])


class TestAttachWhatsappWindow:
    def test_raises_if_not_running(self) -> None:
        registry = FakeConnectorRegistry()

        with pytest.raises(wa.WhatsAppSendFailed):
            wa.attach_whatsapp_window(connect=registry, timeout=0.1)

    def test_returns_and_focuses_the_window_when_running(self) -> None:
        window = FakeControl(name="WhatsApp")
        registry = FakeConnectorRegistry({wa.WHATSAPP_WINDOW_TITLE: window})

        result = wa.attach_whatsapp_window(connect=registry, timeout=0.1)

        assert result is window
        assert window.focused is True


class TestFindChat:
    def test_finds_the_exact_matching_row_with_no_prefix(self) -> None:
        row = _chat_row("Team Standup 3:14 pm see you then")
        window = _window_with_chat_list(row)

        found = wa.find_chat(window, "Team Standup", timeout=0.2)

        assert found is row
        assert row.click_calls == 1

    def test_finds_a_row_carrying_an_unread_count_prefix(self) -> None:
        row = _chat_row("3 unread messages Team Standup 3:14 pm see you then")
        window = _window_with_chat_list(row)

        found = wa.find_chat(window, "Team Standup", timeout=0.2)

        assert found is row

    def test_does_not_match_a_chat_name_appearing_only_in_preview_text(self) -> None:
        # "Team Standup" appears in the preview, not as the row's own chat
        # name -- must not match "Jane Doe"'s row.
        row = _chat_row("Jane Doe 9:00 am can we move Team Standup to 10?")
        window = _window_with_chat_list(row)

        with pytest.raises(wa.WhatsAppSendFailed):
            wa.find_chat(window, "Team Standup", timeout=0.2)

    def test_raises_when_no_row_matches(self) -> None:
        window = _window_with_chat_list(_chat_row("Someone Else 1:00 pm hi"))

        with pytest.raises(wa.WhatsAppSendFailed):
            wa.find_chat(window, "Nonexistent Chat", timeout=0.2)

    def test_raises_on_an_ambiguous_match_rather_than_guessing(self) -> None:
        window = _window_with_chat_list(
            _chat_row("Jane Doe 9:00 am hi"),
            _chat_row("Jane Doe 8:00 am hello"),
        )

        with pytest.raises(wa.WhatsAppSendFailed):
            wa.find_chat(window, "Jane Doe", timeout=0.2)


class TestFocusComposeBox:
    def test_finds_and_clicks_a_matching_edit_control(self) -> None:
        compose = FakeControl(name="Type a message", control_type="Edit")
        window = FakeControl(name="WhatsApp", children=[compose])

        found = wa.focus_compose_box(window, timeout=0.2)

        assert found is compose
        assert compose.click_calls == 1

    def test_raises_when_no_compose_box_is_found(self) -> None:
        window = FakeControl(name="WhatsApp", children=[])

        with pytest.raises(wa.WhatsAppSendFailed):
            wa.focus_compose_box(window, timeout=0.2)


class TestTypeMessage:
    def test_types_and_reads_back_successfully(self) -> None:
        compose = FakeControl(name="", control_type="Edit")

        wa.type_message(compose, "hello there")

        assert compose.typed == ["hello there"]

    def test_raises_if_the_readback_does_not_contain_the_text(self) -> None:
        class _StubbornControl(FakeControl):
            def type_keys(self, text: str, **kwargs) -> None:
                self.typed.append(text)
                # Deliberately does not update .name -- simulates a dropped keystroke.

        compose = _StubbornControl(name="", control_type="Edit")

        with pytest.raises(wa.WhatsAppSendFailed):
            wa.type_message(compose, "hello there")


class TestClickSend:
    def test_clicks_a_button_whose_name_contains_send(self) -> None:
        send_button = FakeControl(name="Send", control_type="Button")
        window = FakeControl(name="WhatsApp", children=[send_button])

        wa.click_send(window, timeout=0.2)

        assert send_button.click_calls == 1

    def test_raises_when_no_send_control_is_found(self) -> None:
        window = FakeControl(name="WhatsApp", children=[])

        with pytest.raises(wa.WhatsAppSendFailed):
            wa.click_send(window, timeout=0.2)


class TestReadBackLastMessage:
    def test_true_when_the_last_message_row_contains_the_text(self) -> None:
        window = FakeControl(
            name="WhatsApp",
            children=[_chat_row("earlier message"), _chat_row("hello there")],
        )

        assert wa.read_back_last_message(window, "hello there", timeout=0.2) is True

    def test_false_when_the_last_message_never_matches(self) -> None:
        window = FakeControl(name="WhatsApp", children=[_chat_row("something else")])

        assert wa.read_back_last_message(window, "hello there", timeout=0.2) is False


class TestBuildSendMessage:
    def test_full_flow_finds_chat_types_sends_and_verifies(self) -> None:
        chat_row = _chat_row("Team Standup 3:14 pm see you then")
        compose = FakeControl(name="Type a message", control_type="Edit")
        send_button = FakeControl(name="Send", control_type="Button")
        # The message list re-reads whatever the compose box was typed into,
        # via a shared close-over reference, simulating the send landing.
        message_row = FakeControl(name="", control_type="DataItem")

        def _send_and_post() -> None:
            message_row.name = compose.name

        send_button._on_click = _send_and_post
        window = _window_with_chat_list(chat_row, extra_children=[compose, send_button, message_row])
        registry = FakeConnectorRegistry({wa.WHATSAPP_WINDOW_TITLE: window})

        send = wa.build_send_message(connect=registry)
        send(wa.WhatsAppMessageTarget(chat_name="Team Standup", text="On my way"))

        assert chat_row.click_calls == 1
        assert compose.typed == ["On my way"]
        assert send_button.click_calls == 1
        assert "On my way" in message_row.window_text()

    def test_raises_if_the_message_never_shows_up_in_the_list(self) -> None:
        chat_row = _chat_row("Team Standup 3:14 pm see you then")
        compose = FakeControl(name="Type a message", control_type="Edit")
        send_button = FakeControl(name="Send", control_type="Button")  # no post-send effect
        window = _window_with_chat_list(chat_row, extra_children=[compose, send_button])
        registry = FakeConnectorRegistry({wa.WHATSAPP_WINDOW_TITLE: window})

        send = wa.build_send_message(connect=registry)

        with pytest.raises(wa.WhatsAppSendFailed):
            send(wa.WhatsAppMessageTarget(chat_name="Team Standup", text="On my way"))
