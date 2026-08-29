"""Blueprint 2.4: Zoom's native-dialog join tail.

Zoom's own URL scheme (``zoommtg://``) gets a join most of the way there --
this module is specifically the tail that scheme cannot do: passcode entry,
choosing an audio device, and dismissing whatever popup appears, all native
Win32/UIA dialogs, not web content. See :func:`zoom_join_url` for the current
parameter shape and the sourcing note on why it is re-verified, not assumed.

Real, live evidence this was built against (29 Aug 2026, Zoom Workplace,
logged-in free account "Ali", captured via ``pywinauto.Desktop(backend="uia")``
against the actually-installed, actually-launched app -- see
``docs/tasks/pywinauto-zoom-whatsapp-report.md`` for the full dump):

* The main window's title is **"Zoom Workplace"**, not the older "Zoom" --
  the 2023 rebrand changed this, and a script hardcoding "Zoom" (the shape
  most public examples still use) would fail ``Application.connect`` outright
  on this install. :data:`HOME_WINDOW_TITLES` carries both, oldest first,
  since a dialog title can lag the main window's rebrand.
* The Home screen's own content (chat list, meeting history, the "Join"
  affordance) is rendered inside an embedded Chromium/CEF web view
  ("Home - Zoom Hub - Web content - Profile 2" in the raw dump), not exposed
  as native UIA controls -- only the outer chrome (title bar, the "NEW"
  split-button, Settings, the account status button) is natively inspectable.
  This is *why* this module does not try to click a native "Join" button on
  the Home screen: per blueprint 2.4, the URL scheme is what gets to the
  join flow, and the dialogs this module actually drives (passcode entry,
  audio device, popups) are the separate native top-level windows Zoom raises
  once a join is actually underway -- confirmed structurally (window-per-step,
  not one embedded flow) against a real, working -- if older-branded and
  Polish-localized -- pywinauto Zoom script
  (https://github.com/MichalZal/Pywinauto-Zoom-Automatization/blob/main/zoom_connect.py):
  a "Join Meeting" window with a meeting-ID Edit and a Name Edit, then a
  *separate* "Enter meeting passcode" window with a passcode Edit and its own
  Join button.
* **Not captured live**: the actual passcode/audio-device/popup dialogs
  themselves. Driving Zoom into a live meeting session to raise them was
  attempted (clicking the Home screen's "NEW" instant-meeting button) and was
  blocked by this environment's own safety classifier before any network join
  occurred -- a real personal test meeting was not available under that
  constraint. Per blueprint 2.4's fallback for exactly this case, the dialog
  tail below is built against the researched/reasoned control shape above
  instead, with resilient multi-candidate matching (:func:`first_existing`)
  rather than one pinned string, and is exercised in tests only against a
  fake control tree. Confirming (or correcting) the exact live strings is the
  one thing this lane could not do itself; the report names the exact command
  to re-run this module's live-tree capture once a human is present to watch
  a real join.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

from executor.app_automation import Control, VerificationFailed, WindowConnector, first_existing, poll_until

logger = logging.getLogger(__name__)


class ZoomJoinFailed(VerificationFailed):
    """Raised when the join-dialog tail could not complete and be verified."""


@dataclass(frozen=True)
class ZoomMeetingTarget:
    """One join job's exact target -- never derived from free text.

    Per the lane brief: "A job payload here must name the exact target
    explicitly (exact chat/group name, exact text; exact meeting ID/passcode)
    -- never derive a recipient or message body from free-text parsing."
    ``passcode`` is optional (some meetings have none); ``display_name`` and
    ``audio_device`` are optional overrides of Zoom's own defaults.
    """

    meeting_id: str
    passcode: str | None = None
    display_name: str | None = None
    audio_device: str | None = None


def zoom_join_url(target: ZoomMeetingTarget) -> str:
    """Build a ``zoommtg://`` join URL for ``target``.

    Parameters confirmed 29 Aug 2026 against current developer-forum
    reporting, not an old memory of the shape: Zoom has no first-party page
    documenting this scheme any more (deprecated internal/external support,
    per Zoom's own developer forum:
    https://devforum.zoom.us/t/is-there-a-documentation-of-the-zoommtg-parameters/67755
    -- "There is no documentation of all the actions and parameters ... as it
    is deprecated"), but the scheme itself is still live and still launches
    the installed Zoom client as of 2026
    (https://devforum.zoom.us/t/url-scheme-documentation-and-invite-links/96064).
    ``action=join``, ``confno=<meeting id, digits only>``, and ``pwd=<passcode>``
    are the parameters every current community reference agrees on; ``uname``
    sets the display name. Re-verify this shape before depending on it further
    -- it is officially unsupported and could change or stop working without
    notice.
    """
    params: dict[str, str] = {"action": "join", "confno": target.meeting_id}
    if target.passcode:
        params["pwd"] = target.passcode
    if target.display_name:
        params["uname"] = target.display_name
    return f"zoommtg://zoom.us/join?{urlencode(params, quote_via=quote)}"


def open_zoom_join_url(url: str, *, opener: Callable[[str], Any] | None = None) -> None:
    """Hand ``url`` to the OS's default handler, launching/foregrounding Zoom.

    ``opener`` defaults to ``os.startfile`` (the standard way to invoke a
    registered custom URL scheme on Windows) and is injectable so tests never
    call it for real.
    """
    (opener or os.startfile)(url)


# Oldest-first: the pre-rebrand title is kept because a dialog raised by an
# older-cached window handle, or a not-yet-updated install, may still use it.
# "Zoom Workplace" is the one confirmed live 29 Aug 2026 -- see module
# docstring.
HOME_WINDOW_TITLES = ("Zoom", "Zoom Workplace")

# Not confirmed live (see module docstring) -- researched from a working,
# differently-branded/localized reference implementation. Listed broad to
# narrow, so a closer future capture only needs to reorder/add, not replace.
PASSCODE_WINDOW_TITLES = ("Enter meeting passcode", "Please enter your meeting passcode", "Zoom")
PASSCODE_FIELD_NAMES = ("Meeting Passcode", "Passcode")
PASSCODE_SUBMIT_NAMES = ("Join Meeting", "Join")

AUDIO_WINDOW_TITLES = ("Choose ONE of the audio conference options", "Join Audio", "Zoom")
AUDIO_JOIN_COMPUTER_NAMES = ("Join with Computer Audio", "Join Audio by Computer")
AUDIO_DEVICE_COMBO_NAMES = ("Select a Microphone", "Microphone", "Speaker")

# Best-effort dismissal only -- "whatever popup appears" is explicitly
# unbounded in the brief, so this list is not exhaustive by design. A popup
# not on this list is simply left alone; it is not this module's job to
# recognize every possible Zoom upsell/notice, only the common ones that
# would otherwise sit on top of the meeting window.
KNOWN_POPUP_DISMISS_NAMES = ("Got it", "Close", "OK", "Dismiss", "×")

# Confirmed live 29 Aug 2026 against the real, in-meeting-adjacent toolbar
# is *not* available (see module docstring) -- this is the control this
# module reads back after the tail completes, to confirm the join actually
# landed rather than assuming the last click worked.
IN_MEETING_VERIFY_NAMES = ("Leave", "End", "Leave Meeting")


def submit_passcode_if_prompted(
    passcode: str | None,
    *,
    connect: WindowConnector,
    timeout: float = 15.0,
) -> bool:
    """Enter and submit ``passcode`` if a passcode dialog appears; else no-op.

    Returns ``True`` if a dialog appeared and was handled, ``False`` if none
    appeared within ``timeout`` -- a normal outcome when the URL scheme
    already carried a valid ``pwd`` or the meeting has no passcode, not a
    failure. Raises :class:`ZoomJoinFailed` if a dialog appeared but the
    fields it expects were not found, or if it never closed after submitting
    (the post-action read-back: a dialog that is still there did not
    actually accept the passcode, whatever the click looked like).
    """
    if not passcode:
        return False
    found = first_existing(PASSCODE_WINDOW_TITLES, connect=connect, timeout=timeout)
    if found is None:
        return False
    _, window = found

    field = _find_by_any_name(window, PASSCODE_FIELD_NAMES, control_type="Edit")
    if field is None:
        raise ZoomJoinFailed("passcode dialog appeared but no passcode field was found")
    field.wait("exists enabled visible ready", timeout=timeout)
    field.click_input()
    field.type_keys(passcode, with_spaces=True)

    submit = _find_by_any_name(window, PASSCODE_SUBMIT_NAMES, control_type="Button")
    if submit is None:
        raise ZoomJoinFailed("passcode dialog appeared but no submit button was found")
    submit.wait("exists enabled visible ready", timeout=timeout)
    submit.click_input()

    if not poll_until(lambda: not window.exists(timeout=0), timeout=timeout):
        raise ZoomJoinFailed("passcode dialog did not close after submitting")
    return True


def choose_audio_device(
    audio_device: str | None,
    *,
    connect: WindowConnector,
    timeout: float = 15.0,
) -> bool:
    """Join computer audio, optionally selecting a specific device first.

    Returns ``True`` if the audio dialog appeared and was handled, ``False``
    if it never appeared (already connected, or auto-join-audio is enabled in
    the account's own settings). When ``audio_device`` is given, the relevant
    device combo is set and read back before the join button is pressed --
    picking a device only to silently keep the old one is exactly the kind of
    unverified click blueprint 2.4 warns against.
    """
    found = first_existing(AUDIO_WINDOW_TITLES, connect=connect, timeout=timeout)
    if found is None:
        return False
    _, window = found

    if audio_device:
        combo = _find_by_any_name(window, AUDIO_DEVICE_COMBO_NAMES, control_type="ComboBox")
        if combo is None:
            raise ZoomJoinFailed("audio dialog appeared but no device selector was found")
        combo.click_input()
        option = combo.child_window(title=audio_device)
        option.wait("exists enabled visible ready", timeout=timeout)
        option.click_input()
        selected = combo.window_text()
        if audio_device not in selected:
            raise ZoomJoinFailed(
                f"selected audio device {audio_device!r} but combo now reads {selected!r}"
            )

    join_button = _find_by_any_name(window, AUDIO_JOIN_COMPUTER_NAMES, control_type="Button")
    if join_button is None:
        raise ZoomJoinFailed("audio dialog appeared but no 'Join with Computer Audio' button was found")
    join_button.wait("exists enabled visible ready", timeout=timeout)
    join_button.click_input()

    if not poll_until(lambda: not window.exists(timeout=0), timeout=timeout):
        raise ZoomJoinFailed("audio dialog did not close after joining computer audio")
    return True


def dismiss_known_popups(
    *,
    connect: WindowConnector,
    timeout: float = 5.0,
    max_popups: int = 5,
) -> int:
    """Best-effort dismissal of common post-join popups. Returns how many closed.

    Bounded by ``max_popups`` so a misidentified always-present control can
    never turn this into an infinite loop. Never raises on finding nothing --
    "whatever popup appears" includes "nothing appears", the common case.
    """
    dismissed = 0
    for _ in range(max_popups):
        found = None
        for name in KNOWN_POPUP_DISMISS_NAMES:
            candidate = connect(name, timeout / max(len(KNOWN_POPUP_DISMISS_NAMES), 1))
            if candidate is not None:
                found = candidate
                break
        if found is None:
            break
        found.click_input()
        dismissed += 1
    return dismissed


def verify_in_meeting(*, connect: WindowConnector, timeout: float = 20.0) -> bool:
    """Read back whether the meeting toolbar's Leave/End control exists.

    The final post-action verification for the whole tail: every step above
    can report success while the meeting itself never actually connected
    (e.g. a rejected passcode that still closed its own dialog on error).
    This is the one check that confirms the join actually landed.
    """
    found = first_existing(IN_MEETING_VERIFY_NAMES, connect=connect, timeout=timeout)
    return found is not None


def _find_by_any_name(window: Control, names: tuple[str, ...], *, control_type: str) -> Control | None:
    for name in names:
        candidate = window.child_window(title=name, control_type=control_type)
        try:
            if candidate.exists(timeout=0.5):
                return candidate
        except Exception:  # pywinauto raises its own lookup errors, not just returns False
            continue
    return None


def join_meeting(
    target: ZoomMeetingTarget,
    *,
    connect: WindowConnector,
    open_url: Callable[[str], None] | None = None,
    dialog_timeout: float = 15.0,
    verify_timeout: float = 20.0,
) -> None:
    """Run the full tail: launch the URL, then passcode -> audio -> popups -> verify.

    Raises :class:`ZoomJoinFailed` if any required step fails or the final
    verification does not find the in-meeting toolbar. ``connect`` is the
    single UIA dependency every step shares; ``open_url`` defaults to
    :func:`open_zoom_join_url`.
    """
    url = zoom_join_url(target)
    (open_url or open_zoom_join_url)(url)

    submit_passcode_if_prompted(target.passcode, connect=connect, timeout=dialog_timeout)
    choose_audio_device(target.audio_device, connect=connect, timeout=dialog_timeout)
    dismiss_known_popups(connect=connect)

    if not verify_in_meeting(connect=connect, timeout=verify_timeout):
        raise ZoomJoinFailed(
            f"join tail completed but no in-meeting toolbar was found for meeting {target.meeting_id!r}"
        )
