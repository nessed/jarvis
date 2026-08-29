# Lane: pywinauto targets — Zoom's native-dialog tail, WhatsApp Desktop send

Blueprint 2.4, the actual UIA-automation half (the CLI-only half is the
sibling lane, `laptop-system-control.md`). Ali named these two apps via a
personal-context agent that knows his habits (relayed 2026-08-29), each with
a plain-English end state:

1. **Zoom** — join a lecture from his phone while walking so the meeting is
   already up by the time he sits down at the laptop. Zoom's own URL scheme
   (`zoommtg://` — **confirm current parameters against Zoom's own current
   documentation before hardcoding anything; do not assume a remembered
   shape is still correct**) gets most of the way there already — this lane
   is specifically the tail that URL scheme cannot do: passcode entry,
   choosing an audio device, and dismissing whatever popup appears, all of
   which are native Win32/UIA dialogs, not web content.
2. **WhatsApp Desktop** — send a message from Ali's **personal** WhatsApp
   number without touching his phone. The Meta Cloud API business number
   this bot already uses cannot send as him — this is the only path to that.
   Confirmed installed 2026-08-29: UWP-packaged
   (`5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App`). **Attach by window title,
   not process path** — Ali's own note, and consistent with how UWP-packaged
   apps run. The UIA tree is workable (Electron-ish, inspectable).

Both apps confirmed installed and launchable on this machine 2026-08-29
(`Get-StartApps`). Build against the real apps — don't stub the UIA layer
itself, only stub around the one genuinely sensitive action named below.

## The one sharp edge, read this first

**Never send a real WhatsApp message to a real contact or group as part of
this lane's own work, or any automated test.** A message sent from Ali's
personal number is visible to whoever receives it and cannot be unsent
cleanly. Build and unit-test the send flow (find chat, focus the compose
box, type text, click send, read the message list back to confirm it posted)
entirely against a fake/mocked UIA control tree that mimics WhatsApp
Desktop's real structure. Mark any test that would drive the actual
installed app with a dedicated pytest marker (`guiauto`, excluded from the
default run the same way `realflp`/`live` are) and **do not run it yourself
even under that marker** — leave it for Ali to run once, watching, the same
way `.flp` edits get a human verification pass. Say this explicitly in the
report; this is not optional caution, it is the actual rule.

Joining a live Zoom meeting during testing is lower-stakes (nothing is sent
to anyone), but still don't join a real scheduled meeting of Ali's — use a
personal test meeting (a Zoom account can start an instant meeting with
itself) or mock the dialog tail against a recorded control tree if no test
meeting is available, and say which you did.

This is a mechanism-building lane, not a wiring lane: nothing here makes
either capability reachable from a WhatsApp message. `enqueue-classifier`
(routing inbound text to a job kind) is still an open Class C decision in
`docs/plan.md`. A job payload here must name the exact target explicitly
(exact chat/group name, exact text; exact meeting ID/passcode) — never
derive a recipient or message body from free-text parsing.

## What to build, per blueprint 2.4's own method

"Agent dumps each app's UIA tree programmatically (`inspect.exe` as backup),
finds control names, writes scripts with explicit waits and post-action
verification (read the control state back — never assume the click landed),
registers each as a job type."

1. Launch each app for real on this desktop. Dump the UIA tree for the
   specific screens you need (Zoom's passcode/audio-device/popup dialogs;
   WhatsApp Desktop's chat list, compose box, and send control) using
   `pywinauto`'s own inspection (`pywinauto.Desktop(backend="uia")`,
   `.print_control_identifiers()`) or `inspect.exe` if that is faster. Save
   what you found (control types, automation IDs, names) in the report —
   this is the recovery path if UI text changes later.
2. Write each script against those real identifiers, `backend="uia"`
   throughout. Every action that changes state gets an explicit wait (poll
   for the control to exist/be enabled, do not `time.sleep` a guess) and a
   post-action read-back that confirms the state actually changed, per
   blueprint 2.4's explicit instruction.
3. Wrap each as a `JobHandler` (`Callable[[Job], None]`,
   `executor/poller.py:44`), following `executor/flp/sort.py`'s split: pure,
   independently-unit-tested functions underneath, a thin handler that
   sequences them and turns failures into whatever this codebase's handlers
   already raise (look at how `executor/flp/sort.py` and
   `executor/handlers/whatsapp.py` signal failure back to the poller's
   retry/dead-letter path — match it, don't invent a new failure shape).

## Ownership — files this lane may write

```
executor/app_automation/                      <- new package
executor/app_automation/__init__.py
executor/app_automation/zoom.py               <- join-meeting dialog tail
executor/app_automation/whatsapp_desktop.py    <- send-as-personal-number
executor/app_automation/handler.py             <- build_app_automation_handler()
tests/executor/app_automation/                 <- mirror the module layout above
docs/tasks/deps-pywinauto-zoom-whatsapp.txt    <- pywinauto, for CORE to integrate
docs/tasks/pywinauto-zoom-whatsapp-report.md
```

Check `python tools/work_board_claim.py list` and claim every path above
before writing. Stop on a conflict. Release the claim ID after verification.

**Do not write:**

- `executor/poller.py` (hot file — the one-line `DEFAULT_HANDLERS`
  registration is CORE's job after this lane and its sibling both land, to
  avoid two lanes colliding on the same file).
- `requirements.txt` — append `pywinauto` (pin the version you install) to
  `docs/tasks/deps-pywinauto-zoom-whatsapp.txt` instead.
- Anything under `voice/`, `diagnostics/`, or `ingest/`/`memory/` — unrelated
  live lanes may hold those; check `list` regardless.

## Coordination with the sibling lane

`laptop-system-control.md` owns `executor/system_control/` and is building
in parallel. No file overlap. Both lanes will eventually need one line each
in `executor/poller.py`'s `DEFAULT_HANDLERS` — name the exact job kind and
registration line in your report; do not add it yourself.

## Verification

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
```

Full offline suite, not a focused subset — must pass with zero real UIA
interaction (mocked control trees only). Claim `test-workspace` first.
Separately, cite in the report: the real UIA tree dumps you captured against
the actually-installed apps (proof this isn't built blind), and confirmation
that no `guiauto`-marked test ran automatically.

## Report

`docs/tasks/pywinauto-zoom-whatsapp-report.md`: what landed with proof, the
control identifiers you found for each dialog/screen (so this is recoverable
without re-dumping), what broke, what was specified but not done, the dep
added, the exact `DEFAULT_HANDLERS` line(s) CORE needs to add, and explicit
confirmation that no real message was sent and no real meeting was joined by
this lane itself.
