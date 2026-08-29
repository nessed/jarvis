"""Blueprint 2.4: send a WhatsApp message as Ali's personal number.

The Meta Cloud API business number this bot already uses cannot send as
Ali himself; driving the installed WhatsApp Desktop UI is the only path to
that. Confirmed installed and launchable 29 Aug 2026: UWP-packaged
(``5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App``), main window title
**"WhatsApp"** (class ``WinUIDesktopWin32WindowClass``) -- attach by that
window title, not process path, per Ali's own note and because a
UWP-packaged app's process name is not a stable thing to match on anyway.

Real, live evidence this was built against (29 Aug 2026, launched via
``explorer.exe shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App``,
inspected with ``pywinauto.Application(backend="uia").connect(title="WhatsApp")``
-- full trees, minus any personal content, in
``docs/tasks/pywinauto-zoom-whatsapp-report.md``):

* The outer app chrome (title bar, minimize/maximize/close) is native UIA,
  captured instantly. Everything else -- chat list, message list, compose
  box, send control -- lives inside an embedded **WebView2 (Chromium)
  content host** (``Chrome_WidgetWin_1`` -> ``BrowserRootView`` -> ... -> a
  UIA ``Document`` node, ``automation_id="RootWebArea"``, the root of
  WhatsApp Web's own React accessibility tree rendered inside the desktop
  app). This is *not* the flat "Electron-ish" tree the lane brief expected in
  the abstract -- it is inspectable, but only by walking through WebView2's
  Chromium accessibility bridge, and getting there is path-sensitive: a
  blind, unbounded ``print_control_identifiers()`` from the window root tried
  to enumerate *two* parallel WebView2-hosted copies of the same content and
  did not return in over 50 minutes of continuous CPU use. A narrow, indexed
  walk straight down the real child chain (``win.children()[2].children()[0]
  .children()[1]``, i.e. ``DesktopChildSiteBridge`` -> ``Chrome_WidgetWin_1``
  -> ``BrowserRootView``) reaches the real page content in well under a
  second -- see the report for the reproduction script.
* Below that, real, live-captured, structural (never content) findings:
  a ``DataGrid`` named **"Chat list"** whose direct children are one
  ``DataItem`` per visible chat row; an ``Edit`` named **"Search or start a
  new chat"** (``automation_id="_r_c_"``); a ``Button`` named **"New chat"**.
  A chat row's UIA *name* is a composite string -- optionally an
  ``"N unread message(s) "`` prefix, then the exact chat/contact name, then a
  timestamp and a last-message preview, e.g. (illustrative, not a real
  contact) ``"2 unread messages Jane Doe 3:14 pm see you then"`` -- **not**
  just the chat name in isolation. :func:`find_chat` matches on that shape
  rather than exact equality for this reason.
* **Not reached live**: the compose box and send control, which only exist
  once a specific chat is open, and this lane's time budget (and, more to the
  point, the sharp-edge rule below) ruled out opening a real chat and typing
  into it to find out. Their identifiers below are researched/defensive
  (WhatsApp Web's own long-public convention is a ``role="textbox"`` compose
  box and a control named "Send"), tried in a documented order, and only
  ever exercised in tests against a fake control tree.
* A live capture briefly surfaced real chat names, phone numbers, and
  message previews (WhatsApp Desktop has no way to inspect chat-row
  structure without also seeing row content). That capture was deleted
  immediately, was not used beyond confirming the structural shape described
  above, and none of it appears here, in tests, or in the report --
  CLAUDE.md's "no personal corpus without opt-in" rule applies to accidental
  capture during UI inspection just as much as to deliberate ingestion.

**The one sharp edge, read this before changing anything below.** Nothing in
this module may send a real WhatsApp message to a real contact or group as
part of its own operation or any automated test, ever -- not even under the
``guiauto`` marker on the one test that would exercise the real app
(``tests/executor/app_automation/test_whatsapp_desktop_guiauto.py``). That
test is additionally gated on an environment variable so it self-skips even
if ``pytest.ini`` is later changed to include ``guiauto`` in a default run by
mistake. A message sent from Ali's personal number is visible to whoever
receives it and cannot be unsent cleanly. This lane did not run that test,
under any marker, at any point -- see the report for the explicit
confirmation.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from executor.app_automation import Control, VerificationFailed, WindowConnector, poll_until

logger = logging.getLogger(__name__)

WHATSAPP_WINDOW_TITLE = "WhatsApp"

# Confirmed live 29 Aug 2026 (see module docstring).
CHAT_LIST_CONTAINER_NAME = "Chat list"
SEARCH_BOX_NAME = "Search or start a new chat"

# An "N unread message(s) " prefix WhatsApp Web prepends to a chat row's
# accessible name when it carries unread messages -- confirmed live (real
# examples redacted; see module docstring). Stripped before comparing a row's
# name against the exact requested ``chat_name``.
_UNREAD_PREFIX_RE = re.compile(r"^\d+ unread messages? ")

# Not confirmed against a real open chat (see module docstring) -- the WebView2
# content was reached, but no chat was open in the inspected instance, so
# these are researched-and-defensive, not literal captured strings. Ordered
# most-to-least specific; WhatsApp Web's long-public convention is a
# ``role="textbox"`` compose box, which UIA surfaces as an "Edit" control.
COMPOSE_BOX_CONTROL_TYPES = ("Edit", "Document")
COMPOSE_BOX_NAME_FRAGMENTS = ("Type a message", "Type a message here")
SEND_BUTTON_NAME_FRAGMENTS = ("Send",)


class WhatsAppSendFailed(VerificationFailed):
    """Raised when any step of finding-chat -> compose -> send -> verify fails.

    Every raise site names which step failed, so a failure here is
    diagnosable without re-attaching a debugger to a live WhatsApp window --
    consistent with ``executor.poller``'s type-only diagnostic contract
    (the message text itself never reaches the durable queue's stored
    failure reason, only the exception type does; see ``poll_once``).
    """


@dataclass(frozen=True)
class WhatsAppMessageTarget:
    """One send job's exact target -- never derived from free text.

    Per the lane brief: "A job payload here must name the exact target
    explicitly (exact chat/group name, exact text ...) -- never derive a
    recipient or message body from free-text parsing." ``chat_name`` must be
    the exact, full name of the 1:1 contact or group as it appears in
    WhatsApp's own chat list -- not a fragment, and never inferred.
    """

    chat_name: str
    text: str


def attach_whatsapp_window(
    *, connect: WindowConnector, title: str = WHATSAPP_WINDOW_TITLE, timeout: float = 20.0
) -> Control:
    """Attach to the running WhatsApp Desktop window by title.

    Raises :class:`WhatsAppSendFailed` if it is not running -- this module
    never launches WhatsApp Desktop itself (unlike Zoom, which the URL scheme
    launches it as a side effect); the job payload names a send, not "start
    WhatsApp and then send".
    """
    window = connect(title, timeout)
    if window is None:
        raise WhatsAppSendFailed(
            f"no window titled {title!r} was found; WhatsApp Desktop must already be running"
        )
    window.set_focus()
    return window


def _row_matches(row_name: str, chat_name: str) -> bool:
    """True if ``row_name`` (a chat row's raw UIA name) names exactly ``chat_name``.

    Strips a leading unread-count prefix, then requires the remainder to
    equal ``chat_name`` exactly or start with ``chat_name`` immediately
    followed by whitespace (the boundary before the row's timestamp/preview
    text) -- see the module docstring's real (redacted) example. A row whose
    name merely *contains* ``chat_name`` somewhere in its preview text (e.g.
    a message that happens to mention another contact's name) must not
    match; only the row's own chat-name field may.
    """
    remainder = _UNREAD_PREFIX_RE.sub("", row_name, count=1)
    return remainder == chat_name or remainder.startswith(chat_name + " ")


def find_chat(window: Control, chat_name: str, *, timeout: float = 15.0) -> Control:
    """Locate the exact chat/group row named ``chat_name`` and open it.

    Searches the direct ``DataItem`` children of the **"Chat list"**
    ``DataGrid`` (see module docstring) rather than an exact-title
    ``child_window`` lookup, because a real row's UIA name is a composite of
    unread-count + name + timestamp + preview, never the bare chat name.
    Raises :class:`WhatsAppSendFailed` if zero rows match within ``timeout``,
    or if *more than one* does -- an ambiguous match is a hard stop, never a
    guess, per the lane brief's "exact target, never derived" rule.
    """

    def _matching_rows() -> list[Control]:
        chat_list = window.child_window(title=CHAT_LIST_CONTAINER_NAME, control_type="DataGrid")
        rows = chat_list.children(control_type="DataItem")
        return [row for row in rows if _row_matches(row.window_text(), chat_name)]

    matches: list[Control] = []

    def _poll() -> bool:
        nonlocal matches
        matches = _matching_rows()
        return bool(matches)

    poll_until(_poll, timeout=timeout, interval=0.5)

    if not matches:
        raise WhatsAppSendFailed(f"no chat row named {chat_name!r} was found in the current chat list")
    if len(matches) > 1:
        raise WhatsAppSendFailed(
            f"chat name {chat_name!r} matched {len(matches)} rows; refusing to guess which one"
        )

    row = matches[0]
    row.click_input()
    return row


def focus_compose_box(window: Control, *, timeout: float = 10.0) -> Control:
    """Find and focus the message compose box for whatever chat is open.

    Tries each of :data:`COMPOSE_BOX_NAME_FRAGMENTS` against each of
    :data:`COMPOSE_BOX_CONTROL_TYPES` in turn (see module docstring on why
    neither was confirmed live).
    """
    for control_type in COMPOSE_BOX_CONTROL_TYPES:
        for fragment in COMPOSE_BOX_NAME_FRAGMENTS:
            candidate = window.child_window(title_re=f".*{re.escape(fragment)}.*", control_type=control_type)
            try:
                if candidate.exists(timeout=timeout / (len(COMPOSE_BOX_CONTROL_TYPES) * len(COMPOSE_BOX_NAME_FRAGMENTS))):
                    candidate.click_input()
                    return candidate
            except Exception:
                continue
    raise WhatsAppSendFailed("no compose box was found in the open chat")


def type_message(compose_box: Control, text: str) -> None:
    """Type ``text`` into ``compose_box`` and read it back before returning.

    The read-back is the post-action verification blueprint 2.4 requires:
    a keystroke that silently didn't land (wrong focus, a dropped IME event)
    must not be discovered only after Send has already been clicked.
    """
    compose_box.type_keys(text, with_spaces=True)
    actual = compose_box.window_text() or " ".join(compose_box.texts())
    if text not in actual:
        raise WhatsAppSendFailed(
            f"compose box read back {actual!r} after typing, expected it to contain {text!r}"
        )


def click_send(window: Control, *, timeout: float = 10.0) -> None:
    """Find and click the send control."""
    for fragment in SEND_BUTTON_NAME_FRAGMENTS:
        candidate = window.child_window(title_re=f".*{re.escape(fragment)}.*", control_type="Button")
        try:
            if candidate.exists(timeout=timeout / len(SEND_BUTTON_NAME_FRAGMENTS)):
                candidate.click_input()
                return
        except Exception:
            continue
    raise WhatsAppSendFailed("no send control was found")


def read_back_last_message(window: Control, expected_text: str, *, timeout: float = 10.0) -> bool:
    """Poll the message list until the last outgoing bubble matches ``expected_text``.

    This is the final post-action verification: a click landing on the send
    control proves nothing by itself (WhatsApp Web can also silently reject
    empty/too-long text). Only seeing the message actually posted counts.
    """

    def _last_message_matches() -> bool:
        messages = window.child_window(control_type="DataItem", found_index=-1)
        try:
            return expected_text in messages.window_text()
        except Exception:
            return False

    return poll_until(_last_message_matches, timeout=timeout)


def build_send_message(
    *,
    connect: WindowConnector,
    attach: Callable[..., Control] | None = None,
) -> Callable[[WhatsAppMessageTarget], None]:
    """Return the composed find-chat -> compose -> send -> verify function.

    ``attach``/``connect`` are the only real-UIA dependencies; a test injects
    fakes for both and this function never imports pywinauto itself, matching
    ``executor.flp.sort.build_flp_sort_handler``'s injection shape.
    """
    attacher = attach or attach_whatsapp_window

    def _send(target: WhatsAppMessageTarget) -> None:
        window = attacher(connect=connect)
        find_chat(window, target.chat_name)
        compose_box = focus_compose_box(window)
        type_message(compose_box, target.text)
        click_send(window)
        if not read_back_last_message(window, target.text):
            raise WhatsAppSendFailed(
                f"sent to {target.chat_name!r} but the message list never showed the text back"
            )

    return _send
