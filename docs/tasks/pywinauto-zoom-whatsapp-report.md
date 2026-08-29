# Lane report: pywinauto targets — Zoom's native-dialog tail, WhatsApp Desktop send

Role: BUILD (`docs/tasks/pywinauto-zoom-whatsapp.md`). Did not commit. Claim
`6ca40ce518134932833cdfcfd5ee6f36` (files listed in the brief, plus
`test-workspace`) released after the full offline suite passed — see
Verification below.

## What landed

```
executor/app_automation/__init__.py       shared Control protocol, WindowConnector type,
                                           poll_until(), first_existing() explicit-wait helpers
executor/app_automation/zoom.py           zoommtg:// URL build + passcode/audio-device/popup tail
executor/app_automation/whatsapp_desktop.py   find-chat -> compose -> send -> verify
executor/app_automation/handler.py        build_app_automation_handler(): dispatches both job kinds
tests/executor/app_automation/__init__.py + conftest.py + test_zoom.py +
  test_whatsapp_desktop.py + test_handler.py    45 tests, all against fake control trees
tests/executor/app_automation/test_whatsapp_desktop_guiauto.py   guiauto, gated, not run by this lane
tests/executor/app_automation/test_zoom_guiauto.py               guiauto, gated, not run by this lane
docs/tasks/deps-pywinauto-zoom-whatsapp.txt   pywinauto==0.6.9, comtypes==1.4.16
```

Every job-changing action (passcode entry, audio-device join, chat send)
follows blueprint 2.4's explicit-wait-then-read-back shape: `poll_until()` in
`executor/app_automation/__init__.py` is the one polling primitive everything
is built on — never a blind `time.sleep`.

## Verification

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp tests/executor/app_automation/
-> 43 passed, 2 skipped, 2 warnings in 11.99s

.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
-> 722 passed, 2 skipped, 5 deselected, 4 warnings in 75.53s
```

The 2 skips are the `guiauto` tests, self-skipping on their environment-variable
gate (see "The sharp edge" below) — confirmed by the skip reason text, not just
the count. Zero real UIA calls occurred in either run; every executed test in
`tests/executor/app_automation/` runs against `FakeControl`/`FakeConnectorRegistry`
(`tests/executor/app_automation/conftest.py`), never `pywinauto`.

One real bug found and fixed along the way: `tests/executor/app_automation/test_handler.py`
collided at import with the sibling lane's `tests/executor/system_control/test_handler.py`
(same basename, neither package had an `__init__.py`, so pytest's rootless
import gave both the same module name). Fixed by adding
`tests/executor/app_automation/__init__.py` — a change entirely inside this
lane's own claimed directory, not a touch on the sibling's files.

## Real UIA evidence (both apps launched and inspected live, 29 Aug 2026)

**WhatsApp Desktop** — launched via
`explorer.exe shell:AppsFolder\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App`,
process `WhatsApp.Root`, window title **"WhatsApp"** (class
`WinUIDesktopWin32WindowClass`). Confirms "attach by window title, not process
path" is correct and necessary — a UWP host process name is not what you'd
expect.

Below the outer chrome, the real chat/message/compose UI lives inside an
embedded **WebView2 (Chromium) content host**
(`Chrome_WidgetWin_1` → `BrowserRootView` → … → a UIA `Document` node,
`automation_id="RootWebArea"`, the root of WhatsApp Web's own React
accessibility tree). This is not the flat "Electron-ish" tree the brief
described in the abstract. Two things followed from that:

- A blind, unbounded `print_control_identifiers()` from the window root tried
  to enumerate **two parallel WebView2-hosted copies** of the same content and
  did not return after **50+ minutes of continuous CPU use** (it was killed).
  A narrow, indexed walk straight down the real child chain —
  `win.children()[2].children()[0].children()[1]`
  (`DesktopChildSiteBridge` → `Chrome_WidgetWin_1` → `BrowserRootView`) —
  reaches the real page content in well under a second. Anyone re-dumping
  this tree should use the indexed/bounded approach, not
  `print_control_identifiers()` from the root.
- Real, **structural** identifiers confirmed live: a `DataGrid` named
  **"Chat list"** whose direct children are one `DataItem` per visible chat
  row; an `Edit` named **"Search or start a new chat"**
  (`automation_id="_r_c_"`); a `Button` named **"New chat"**. A chat row's
  UIA *name* is a composite string — an optional `"N unread message(s) "`
  prefix, then the chat/contact name, then a timestamp and last-message
  preview — never just the bare name. `find_chat()` matches on that shape
  (exact name, or name + a trailing space, after stripping the unread
  prefix) rather than exact `child_window(title=...)` equality, and raises
  rather than guessing if more than one row matches.
- **Not reached live**: the compose box and send control, which only exist
  once a chat is open. `focus_compose_box()`/`click_send()` search
  defensively (role + name fragments) and are not confirmed against the real
  app.
- **Incidental privacy note, and how it was handled**: reaching the "Chat
  list" `DataGrid`'s structure necessarily also surfaced its content — real
  contact names, phone numbers, and message previews, since WhatsApp Desktop
  has no way to show row structure without row content. That capture was
  **deleted immediately** from the scratchpad the moment it was noticed, was
  never copied into code, tests, or this report, and no fact from it was
  retained beyond the generic shape described above. CLAUDE.md's "no personal
  corpus without opt-in" applies to accidental capture during UI inspection
  as much as to deliberate ingestion, and this lane treated it that way.

**Zoom Workplace** — launched from `%APPDATA%\Zoom\bin\Zoom.exe`, window title
**"Zoom Workplace"** (not the older "Zoom" — the 2023 rebrand changed this;
`HOME_WINDOW_TITLES` in `zoom.py` carries both). Logged in as Ali's own free
account. The Home screen itself ("Zoom Hub") is *also* substantially embedded
web content, not native UIA — only the outer chrome (title bar, the "NEW"
split-button, Settings, account-status button) is natively inspectable.

**Not captured live: the passcode/audio-device/popup dialogs.** Driving Zoom
into an actual meeting to raise them — clicking Home's "NEW" instant-meeting
button, following the brief's own suggested "start an instant meeting with
yourself" path — was **blocked by this environment's own auto-mode safety
classifier** before any network join occurred:

> Permission for this action was denied by the Claude Code auto mode
> classifier. Reason: Blocked by classifier.

Confirmed this was meeting-specific, not a blanket UI-interaction block: a
follow-up click on the unrelated "Settings" nav button succeeded immediately.
No personal test meeting was available under that constraint, so per the
brief's explicit fallback ("mock the dialog tail against a recorded control
tree if no test meeting is available, and say which you did"), the dialog
tail (`submit_passcode_if_prompted`, `choose_audio_device`,
`dismiss_known_popups`, `verify_in_meeting`) is built against **researched,
multi-candidate identifiers**, cross-checked against a real, working —
if older-branded and Polish-localized — public pywinauto Zoom script
(`https://github.com/MichalZal/Pywinauto-Zoom-Automatization/blob/main/zoom_connect.py`),
which confirmed the *structural* shape live scripts have actually used: a
"Join Meeting" window (meeting-ID `Edit` + name `Edit` + "Join" `Button`),
then a **separate** "Enter meeting passcode" window (passcode `Edit` +
its own "Join" `Button`). None of this is confirmed against Ali's current,
English-locale, "Zoom Workplace"-branded client. `test_zoom_guiauto.py` is
the real-app probe that would confirm or correct it, gated the same way as
WhatsApp's.

`zoommtg://` URL scheme parameters (`action=join`, `confno=`, `pwd=`,
`uname=`) were re-verified against current developer-forum reporting, not
assumed from memory — Zoom has no first-party documentation page for this
scheme any more (officially deprecated, still functional as of 2026; see
`zoom_join_url()`'s docstring for sources). This is a real, disclosed risk:
the scheme is unsupported and could stop working without notice.

## The sharp edge — confirmed

**No real WhatsApp message was sent, by this lane or by any test run in this
lane's verification, at any point.** The full send flow (find chat → focus
compose → type → click send → read back) is unit-tested only against
`FakeControl`/`FakeConnectorRegistry` (`tests/executor/app_automation/test_whatsapp_desktop.py`).
The one test that would send a real message,
`test_whatsapp_desktop_guiauto.py`, is:

1. Marked `guiauto`.
2. Independently gated on `JARVIS_GUIAUTO_WHATSAPP_SEND_CONFIRM=i-am-watching`,
   checked by an autouse fixture — confirmed by this session's own run of the
   full offline suite showing it **skipped**, not passed or failed.
3. Requires Ali to name the exact target chat himself via
   `JARVIS_GUIAUTO_WHATSAPP_CHAT` — the file never hardcodes a real contact.
4. Sends a fixed, unambiguous, clearly-labeled test string
   (`"[JARVIS guiauto test] pywinauto-zoom-whatsapp lane self-check -- safe to
   ignore/delete."`) — never a message that could be mistaken for something
   Ali meant to say to someone.

This lane did not set that environment variable, did not run that test under
any marker or invocation, and did not otherwise drive the real WhatsApp send
flow. It is left for Ali to run once, watching, per the brief.

**Zoom**, lower-stakes per the brief but still handled carefully: no real
meeting was joined by this lane. The one attempt to start a personal instant
test meeting was blocked by the harness's own safety classifier (see above),
so the dialog tail was built and tested against research + fakes instead, and
`test_zoom_guiauto.py` is the equivalent gated, not-run-by-this-lane probe for
Ali to use later.

## What CORE needs to do

**1. Two `DEFAULT_HANDLERS` lines in `executor/poller.py`** (not touched by
this lane — hot file, CORE's job once this lane and `laptop-system-control`
both land):

```python
from executor.app_automation.handler import (
    WHATSAPP_DESKTOP_SEND_MESSAGE_JOB_KIND,
    ZOOM_JOIN_MEETING_JOB_KIND,
    build_app_automation_handler,
)
# ... inside DEFAULT_HANDLERS, one shared handler instance for both kinds:
_app_automation_handler = build_app_automation_handler()
...
    ZOOM_JOIN_MEETING_JOB_KIND: HandlerRegistration(_app_automation_handler),
    WHATSAPP_DESKTOP_SEND_MESSAGE_JOB_KIND: HandlerRegistration(_app_automation_handler),
```

(`ZOOM_JOIN_MEETING_JOB_KIND = "zoom_join_meeting"`,
`WHATSAPP_DESKTOP_SEND_MESSAGE_JOB_KIND = "whatsapp_desktop_send_message"` —
exported constants from `executor/app_automation/handler.py`.)

**2. `pytest.ini`** — not touched by this lane (shared file, no lane owns it,
disjoint-ownership rule says report the need rather than edit it). Two small
additions, matching the existing `live`/`realflp` pattern:

```
markers =
    ...
    guiauto: drives the real, installed Zoom/WhatsApp Desktop apps. Excluded from the default run.
addopts = -m "not live and not realflp and not guiauto"
```

Not adding this is **not unsafe** — both `guiauto` tests are independently
gated on an environment variable that is never set automatically, confirmed
by this session's own full-suite run showing them skip — but it is the
correct long-term home for the exclusion, consistent with how `realflp`
already works.

**3. `requirements.txt`** — append from `docs/tasks/deps-pywinauto-zoom-whatsapp.txt`:
`pywinauto==0.6.9`, `comtypes==1.4.16`.

## What was specified but not done

- **Live-confirmed Zoom passcode/audio-device/popup dialog identifiers.**
  Blocked by the harness's safety classifier, not skipped by choice — see
  above. `test_zoom_guiauto.py` is ready for Ali to run once he has a personal
  test meeting up; its result will confirm or correct
  `PASSCODE_WINDOW_TITLES`/`AUDIO_WINDOW_TITLES`/etc. in `zoom.py`.
- **Live-confirmed WhatsApp compose-box/send-control identifiers.** The
  WebView2 content was reached, but no chat was open in the inspected
  instance, so these are researched, not captured. `test_whatsapp_desktop_guiauto.py`
  is the equivalent probe.
- `executor/poller.py`'s `DEFAULT_HANDLERS` registration — explicitly CORE's,
  not this lane's, per the brief.
- `requirements.txt` and `pytest.ini` edits — explicitly out of this lane's
  ownership; named above for CORE.

## What broke (and was fixed within this lane's own scope)

- The `tests/executor/test_handler.py` basename collision with the sibling
  lane's file of the same name, fixed by adding `__init__.py` to this lane's
  own test directory only (see Verification).
- The first live UIA capture attempt (`print_control_identifiers(depth=12)`
  from the WhatsApp window root) ran for 50+ minutes without returning and
  was killed; switched to a fast, targeted raw-`element_info` walk plus
  indexed child traversal (see the WhatsApp evidence section) which resolved
  the same content in under a second once aimed correctly.
