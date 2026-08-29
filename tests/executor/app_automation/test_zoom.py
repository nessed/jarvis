"""Unit tests for executor.app_automation.zoom -- all against fake control trees.

Blueprint 2.4's join-dialog tail (passcode, audio device, popups) is tested
here purely through :class:`FakeControl`/:class:`FakeConnectorRegistry`
(``conftest.py``); nothing here ever imports pywinauto or drives real Zoom.
Live-captured Zoom identifiers (window title "Zoom Workplace", account
chrome) and the researched-but-not-live-confirmed dialog identifiers used
below are documented in ``executor/app_automation/zoom.py``'s module
docstring and ``docs/tasks/pywinauto-zoom-whatsapp-report.md``.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from executor.app_automation import zoom
from tests.executor.app_automation.conftest import FakeControl


class TestZoomJoinUrl:
    def test_includes_action_join_and_confno(self) -> None:
        url = zoom.zoom_join_url(zoom.ZoomMeetingTarget(meeting_id="1234567890"))

        parsed = urlparse(url)
        assert parsed.scheme == "zoommtg"
        params = parse_qs(parsed.query)
        assert params["action"] == ["join"]
        assert params["confno"] == ["1234567890"]
        assert "pwd" not in params
        assert "uname" not in params

    def test_includes_passcode_and_display_name_when_given(self) -> None:
        target = zoom.ZoomMeetingTarget(meeting_id="1234567890", passcode="abc123", display_name="Ali")

        params = parse_qs(urlparse(zoom.zoom_join_url(target)).query)

        assert params["pwd"] == ["abc123"]
        assert params["uname"] == ["Ali"]

    def test_omits_passcode_when_falsy(self) -> None:
        target = zoom.ZoomMeetingTarget(meeting_id="1", passcode="")

        params = parse_qs(urlparse(zoom.zoom_join_url(target)).query)

        assert "pwd" not in params


class TestOpenZoomJoinUrl:
    def test_calls_the_injected_opener_with_the_url(self) -> None:
        opened: list[str] = []

        zoom.open_zoom_join_url("zoommtg://zoom.us/join?action=join&confno=1", opener=opened.append)

        assert opened == ["zoommtg://zoom.us/join?action=join&confno=1"]


class TestSubmitPasscodeIfPrompted:
    def test_no_passcode_is_a_no_op(self) -> None:
        registry = _empty_registry()

        result = zoom.submit_passcode_if_prompted(None, connect=registry, timeout=0.2)

        assert result is False
        assert registry.calls == []

    def test_no_dialog_appearing_returns_false(self) -> None:
        registry = _empty_registry()

        result = zoom.submit_passcode_if_prompted("1234", connect=registry, timeout=0.2)

        assert result is False

    def test_enters_passcode_and_submits_when_dialog_appears(self) -> None:
        window = FakeControl(name="dialog")
        field = FakeControl(name="Meeting Passcode", control_type="Edit")
        submit = FakeControl(
            name="Join Meeting", control_type="Button", on_click=lambda: setattr(window, "_exists", False)
        )
        window._children = [field, submit]
        registry = _registry({zoom.PASSCODE_WINDOW_TITLES[0]: window})

        result = zoom.submit_passcode_if_prompted("1234", connect=registry, timeout=0.5)

        assert result is True
        assert field.typed == ["1234"]
        assert submit.click_calls == 1

    def test_raises_if_dialog_appears_with_no_passcode_field(self) -> None:
        window = FakeControl(name="dialog", children=[])
        registry = _registry({zoom.PASSCODE_WINDOW_TITLES[0]: window})

        with pytest.raises(zoom.ZoomJoinFailed):
            zoom.submit_passcode_if_prompted("1234", connect=registry, timeout=0.2)

    def test_raises_if_dialog_never_closes_after_submitting(self) -> None:
        window = FakeControl(name="dialog")
        field = FakeControl(name="Meeting Passcode", control_type="Edit")
        submit = FakeControl(name="Join Meeting", control_type="Button")  # no on_click: never closes
        window._children = [field, submit]
        registry = _registry({zoom.PASSCODE_WINDOW_TITLES[0]: window})

        with pytest.raises(zoom.ZoomJoinFailed):
            zoom.submit_passcode_if_prompted("1234", connect=registry, timeout=0.3)


class TestChooseAudioDevice:
    def test_no_dialog_appearing_returns_false(self) -> None:
        registry = _empty_registry()

        result = zoom.choose_audio_device(None, connect=registry, timeout=0.2)

        assert result is False

    def test_joins_computer_audio_without_selecting_a_device(self) -> None:
        window = FakeControl(name="dialog")
        join_btn = FakeControl(
            name="Join with Computer Audio",
            control_type="Button",
            on_click=lambda: setattr(window, "_exists", False),
        )
        window._children = [join_btn]
        registry = _registry({zoom.AUDIO_WINDOW_TITLES[0]: window})

        result = zoom.choose_audio_device(None, connect=registry, timeout=0.5)

        assert result is True
        assert join_btn.click_calls == 1

    def test_selects_a_device_and_verifies_it_stuck(self) -> None:
        window = FakeControl(name="dialog")
        combo = FakeControl(name="Select a Microphone", control_type="ComboBox")
        option = FakeControl(name="Headset Mic")
        option._on_click = lambda: setattr(combo, "name", "Headset Mic")
        combo._children = [option]
        join_btn = FakeControl(
            name="Join with Computer Audio",
            control_type="Button",
            on_click=lambda: setattr(window, "_exists", False),
        )
        window._children = [combo, join_btn]
        registry = _registry({zoom.AUDIO_WINDOW_TITLES[0]: window})

        result = zoom.choose_audio_device("Headset Mic", connect=registry, timeout=0.5)

        assert result is True
        assert combo.name == "Headset Mic"

    def test_raises_if_selected_device_does_not_stick(self) -> None:
        window = FakeControl(name="dialog")
        combo = FakeControl(name="Select a Microphone", control_type="ComboBox")
        option = FakeControl(name="Headset Mic")  # on_click left as None: selection never "sticks"
        combo._children = [option]
        window._children = [combo]
        registry = _registry({zoom.AUDIO_WINDOW_TITLES[0]: window})

        with pytest.raises(zoom.ZoomJoinFailed):
            zoom.choose_audio_device("Headset Mic", connect=registry, timeout=0.3)

    def test_raises_if_no_join_computer_audio_button_is_found(self) -> None:
        window = FakeControl(name="dialog", children=[])
        registry = _registry({zoom.AUDIO_WINDOW_TITLES[0]: window})

        with pytest.raises(zoom.ZoomJoinFailed):
            zoom.choose_audio_device(None, connect=registry, timeout=0.2)


class TestDismissKnownPopups:
    def test_returns_zero_when_nothing_matches(self) -> None:
        registry = _empty_registry()

        assert zoom.dismiss_known_popups(connect=registry, timeout=0.1) == 0

    def test_clicks_and_counts_a_matching_popup(self) -> None:
        popup = FakeControl(name="Got it")
        registry = _registry({"Got it": popup})

        count = zoom.dismiss_known_popups(connect=registry, timeout=0.1, max_popups=1)

        assert count == 1
        assert popup.click_calls == 1


class TestVerifyInMeeting:
    def test_true_when_leave_control_exists(self) -> None:
        registry = _registry({zoom.IN_MEETING_VERIFY_NAMES[0]: FakeControl(name="Leave")})

        assert zoom.verify_in_meeting(connect=registry, timeout=0.2) is True

    def test_false_when_no_in_meeting_control_is_found(self) -> None:
        registry = _empty_registry()

        assert zoom.verify_in_meeting(connect=registry, timeout=0.2) is False


class TestJoinMeeting:
    def test_happy_path_opens_url_and_verifies_in_meeting(self) -> None:
        opened: list[str] = []
        registry = _registry({zoom.IN_MEETING_VERIFY_NAMES[0]: FakeControl(name="Leave")})
        target = zoom.ZoomMeetingTarget(meeting_id="42")

        zoom.join_meeting(
            target,
            connect=registry,
            open_url=opened.append,
            dialog_timeout=0.1,
            verify_timeout=0.2,
        )

        assert len(opened) == 1
        assert "confno=42" in opened[0]

    def test_raises_when_final_verification_finds_nothing(self) -> None:
        registry = _empty_registry()
        target = zoom.ZoomMeetingTarget(meeting_id="42")

        with pytest.raises(zoom.ZoomJoinFailed):
            zoom.join_meeting(
                target, connect=registry, open_url=lambda _url: None, dialog_timeout=0.1, verify_timeout=0.2
            )


def _empty_registry():
    from tests.executor.app_automation.conftest import FakeConnectorRegistry

    return FakeConnectorRegistry()


def _registry(windows: dict[str, FakeControl]):
    from tests.executor.app_automation.conftest import FakeConnectorRegistry

    return FakeConnectorRegistry(windows)
