# Lane: `voice-cli-tests`

Role: **BUILD**. Do not commit. Claim ID `be26ff684b29491d8dd8a8592c22ec94`
is already held for you by the orchestrator — do **not** re-claim, do **not**
release it. Report back and CORE releases it.

## Why this exists

Three voice CLI entry points have **zero test references anywhere in
`tests/`**. `voice/try_stt.py` landed in `52e2c03` untested. Together they are
475 lines of logic on the live voice path — argument parsing, device
selection, subprocess invocation, and the encoding handling that has already
caused two wrong conclusions on this machine.

| file | lines | tests today |
|---|---|---|
| `voice/try_stt.py` | 183 | 0 |
| `voice/listen_wakeword.py` | 164 | 0 |
| `voice/audition_voices.py` | 128 | 0 |

Every sibling in `voice/` already has one (`tests/voice/test_audio.py`,
`test_benchmark_stt.py`, `test_config.py`, `test_local_backend.py`,
`test_record_wakeword.py`, `test_server_client.py`, `test_speak.py`). Match
their style — read `tests/voice/test_record_wakeword.py` first, it is the
closest analogue (a mic-driving CLI tested entirely against fakes).

## Files you own

Write:

```
tests/voice/test_try_stt.py            (new)
tests/voice/test_listen_wakeword.py    (new)
tests/voice/test_audition_voices.py    (new)
voice/try_stt.py                       (seams only, see below)
voice/listen_wakeword.py               (seams only, see below)
voice/audition_voices.py               (seams only, see below)
```

Nothing else. If you need a change in a file outside this list, **report the
need, do not make the edit**.

## Scope

1. Read each of the three modules and the existing `tests/voice/` suite.
2. Add unit tests that run **offline, with no microphone, no speakers, no
   NPU, no Ollama, no network, and no `whisper-server`**. Every external
   dependency is a fake. A test that needs hardware does not belong in the
   offline suite; if a behaviour genuinely cannot be tested without hardware,
   say so in your report rather than marking it `live`.
3. You may edit the three source modules **only to open a dependency-injection
   seam** — hoisting a hardcoded call into a default argument, extracting a
   pure helper. Prefer default-argument injection, the pattern the rest of
   this repo uses. Do not restructure, do not rename public functions, do not
   change CLI flags or their defaults.

## What to cover, specifically

These are the behaviours that already cost this project real time. Cover them
first; general branch coverage after.

- **Encoding.** `docs/state.md`: the locale codec on this machine is cp1252
  and cannot represent Urdu or Arabic script. `subprocess.run(text=True)`
  raised `UnicodeDecodeError` on a *successful* Urdu transcription and
  reported `(nothing recognised)`; after that was fixed `print()` raised
  `UnicodeEncodeError` on the recovered text. Both runners now pass
  `encoding="utf-8", errors="replace"`, and `voice/try_stt.py` reconfigures
  stdout/stderr. **Pin all of that.** A test that feeds non-Latin-1 bytes
  through the fake subprocess and asserts the transcript survives intact is
  the single most valuable test in this lane.
- **Language default.** `DEFAULT_WHISPER_LANGUAGE` in `voice/config.py` is
  `ur`, not `auto`, decided 30 Aug 2026 — `auto` silently dropped the Urdu
  half of code-switched clips. Assert `try_stt.py` actually passes the
  configured language through, and that `--language` overrides it.
- **`--compare` mode** in `try_stt.py` (NPU vs CPU) — assert both passes run
  and both results are reported, and that one backend failing does not
  swallow the other's result.
- **Wake-word threshold.** `voice/listen_wakeword.py` scores against a 0.5
  threshold. Assert the detect/no-detect boundary and that `--meter` changes
  output without changing detection.
- **Failure paths.** A missing model file, a non-zero subprocess exit, an
  empty/blank transcript. Assert each one is loud, not a silent
  `(nothing recognised)`.

## Verification — required

Give each command its own scratch directory. Other lanes are running
concurrently and must not share `.pytest-basetemp`.

Focused, while you work:

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-voicecli tests/voice/
```

Full offline suite, **required before you report**, because a seam you opened
in a source module can break a lane that imports it:

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-voicecli --ignore=tests/db/test_jobs_integration.py
```

Baseline to beat: **862 passed, 7 deselected** as of `52e2c03`. A green
focused run over a red tree is a false completion claim.

## Report

Write `docs/tasks/voice-cli-tests-report.md`. It must contain:

- The exact commands you ran and their **actual output**, pasted. A claim
  without its command output is not a result.
- Test count before and after.
- Every seam you opened in a source module, with the before/after signature.
- Anything you found that is wrong but outside your file ownership — name it,
  do not fix it.
- Anything you could not test offline, and why.

## Rules that override anything above

- Do not commit. Do not touch `requirements.txt` — append to
  `docs/tasks/deps-voice-cli-tests.txt` and let CORE integrate.
- Never `git stash`. The working tree is shared live with concurrent lanes.
- If a specified component looks wrong, stop and report. Do not substitute.
- Secrets are never printed, echoed, logged, or requested.
