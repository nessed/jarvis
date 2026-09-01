# Lane report: `voice-cli-tests`

Role BUILD. Claim `be26ff684b29491d8dd8a8592c22ec94` (still held; CORE releases).
Nothing committed. `requirements.txt` untouched and no new dependency was
needed, so `docs/tasks/deps-voice-cli-tests.txt` was not created.

## Result

88 new offline tests across three files that previously had zero test
references anywhere in `tests/`.

| file | tests before | tests after |
|---|---|---|
| `voice/try_stt.py` | 0 | 32 |
| `voice/listen_wakeword.py` | 0 | 32 |
| `voice/audition_voices.py` | 0 | 24 |

Suite totals: `tests/voice/` went 133 -> 221. Full offline suite went
862 -> 950, same 7 deselected.

Nothing here needs a microphone, a speaker, the NPU, `whisper-cli.exe`, the
large-v3 weights, the `.rai` encoder cache, openWakeWord, Kokoro, torch,
Ollama or the network. The only real process any test starts is
`sys.executable -c` printing bytes, and that exists specifically to prove the
UTF-8 decode is real rather than mocked away.

## Commands and output

Baseline, `tests/voice/` before any of this lane's files existed:

```
$ .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-voicecli tests/voice/
........................................................................ [ 54%]
.............................................................            [100%]
133 passed in 13.35s
```

The three new files, individually:

```
$ .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-voicecli tests/voice/test_try_stt.py
................................                                         [100%]
32 passed in 0.95s

$ .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-voicecli tests/voice/test_listen_wakeword.py
................................                                         [100%]
32 passed in 0.43s

$ .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-voicecli tests/voice/test_audition_voices.py
........................                                                 [100%]
24 passed in 0.59s
```

Focused, after:

```
$ .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-voicecli tests/voice/
........................................................................ [ 32%]
........................................................................ [ 65%]
........................................................................ [ 97%]
.....                                                                    [100%]
221 passed in 14.59s
```

Full offline suite, required before reporting because the seams below live in
source modules other lanes import:

```
$ .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-voicecli --ignore=tests/db/test_jobs_integration.py
..............                                                           [100%]
============================== warnings summary ===============================
tests/test_integration.py::test_status_is_bearer_protected_and_reports_integrated_shape
  C:\Users\Ali\desktop\jarvis\.venv\Lib\site-packages\supabase\_sync\client.py:303: DeprecationWarning: The 'timeout' parameter is deprecated. Please configure it in the http client instead.
    return SyncPostgrestClient(

tests/test_integration.py::test_status_is_bearer_protected_and_reports_integrated_shape
  C:\Users\Ali\desktop\jarvis\.venv\Lib\site-packages\supabase\_sync\client.py:303: DeprecationWarning: The 'verify' parameter is deprecated. Please configure it in the http client instead.
    return SyncPostgrestClient(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
950 passed, 7 deselected, 2 warnings in 150.43s (0:02:30)
```

Baseline to beat was 862 passed, 7 deselected. 950 passed, 7 deselected.

## The encoding tests actually bite

A test that passes is not proof it would fail on a regression, so the console
fix was reverted and the suite re-run. `voice/try_stt.py` line 52 was replaced
with `pass  # MUTATED`, the file was restored from a backup immediately after,
and `git diff --stat` was checked to confirm the restore.

```
$ (revert reconfigure(encoding="utf-8", errors="replace") to `pass`)
$ .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-voicecli tests/voice/test_try_stt.py
E       UnicodeEncodeError: 'charmap' codec can't encode characters in position 2-4: character maps to <undefined>

..\..\AppData\Local\Programs\Python\Python312\Lib\encodings\cp1252.py:19: UnicodeEncodeError
=========================== short test summary info ===========================
FAILED tests/voice/test_try_stt.py::test_force_utf8_console_makes_that_same_console_accept_urdu
FAILED tests/voice/test_try_stt.py::test_both_streams_are_reconfigured_to_utf8_with_replacement
FAILED tests/voice/test_try_stt.py::test_an_urdu_transcript_reaches_a_cp1252_console_intact
3 failed, 29 passed in 0.84s

$ (restore)
$ git diff --stat voice/try_stt.py
 voice/try_stt.py | 16 +++++++++++++---
 1 file changed, 13 insertions(+), 3 deletions(-)
```

That is the original 29 Aug 2026 failure, reproduced by the test rather than
by the user.

Both halves of the bug are pinned:

- **The write half** is pinned against a real `io.TextIOWrapper(..., encoding="cp1252")`,
  not a mock. `test_a_cp1252_console_really_cannot_print_urdu` is the control:
  it asserts the unfixed stream genuinely raises, so the other two are not
  passing on a console that never had the problem.
- **The read half** is pinned by `test_a_real_subprocess_urdu_transcript_survives_the_decode`,
  which runs a real `sys.executable -c` writing UTF-8 Urdu bytes through
  `LocalWhisperBackend._run`. cp1252 has undefined bytes at 0x81, and the UTF-8
  encoding of Urdu contains 0x81, so a `text=True`-only decode raises rather
  than mangling. Nothing is mocked in that test except the argv.

The sample strings are real Urdu (`ہیلو`, `میں ٹھیک ہوں`), asserted at module
scope to be entirely outside latin-1. A Latin stand-in would pass on the exact
console that broke.

## Seams opened

Three source modules changed, injection seams only. No renames, no CLI flag or
default changed, no restructuring, no behaviour change on the default path.

### `voice/try_stt.py`

One inline expression hoisted into a function, so a test can redirect the
scratch recording instead of monkeypatching `tempfile` in the standard library.

```
before:  (inline, inside main)
             temporary = Path(tempfile.gettempdir()) / "jarvis-try-stt.wav"

after:   def scratch_clip_path() -> Path: ...
             temporary = scratch_clip_path()
```

No other seam was needed. `main()` imports `LocalWhisperBackend` and
`default_backend` from `voice.whisper.local_backend` at call time, so patching
that module's attributes is what the CLI actually resolves; and `record` is
looked up as a module global.

### `voice/listen_wakeword.py`

Two lazy imports hoisted into default-argument factories, plus an injectable
clock. The bodies moved verbatim; the default path constructs exactly what it
constructed before.

```
before:  def listen(threshold: float, device: int | None, meter: bool, seconds: float | None) -> int

after:   def listen(
             threshold: float,
             device: int | None,
             meter: bool,
             seconds: float | None,
             *,
             load_model=_load_model,
             open_stream=_open_stream,
             clock=time.monotonic,
         ) -> int
```

New module-level helpers holding what used to be inline:

```
after:   def _load_model()                      # the openwakeword Model construction
after:   def _open_stream(device: int | None)   # the sd.InputStream construction
```

The three `time.monotonic()` call sites inside `listen` became `clock()`. The
clock is injected because the real one makes a bounded run take as long as the
run, and because the refractory-window boundary is otherwise untestable.

`list_devices()` was left alone; it is tested with a fake `sounddevice` in
`sys.modules`, the pattern `tests/voice/test_record_wakeword.py` already uses.

### `voice/audition_voices.py`

The cache location hoisted out of the glob, so the scan can be pointed at a
directory the test created rather than at the real home directory.

```
before:  def installed_voices() -> list[str]
             pattern = str(Path.home() / ".cache" / "huggingface" / "**" / "*.pt")

after:   def default_cache_root() -> Path
         def installed_voices(cache_root: Path | None = None) -> list[str]
             root = default_cache_root() if cache_root is None else Path(cache_root)
             pattern = str(root / "**" / "*.pt")
```

`Path.home()` is resolved inside the function, as before, not at import time:
it reads the environment and can raise, and an import-time raise would take the
whole offline suite down on a machine with no home set.

No shared `Protocol`, public signature or schema changed, so there is no
implementer elsewhere to update.

## Found but not owned

Four things. None fixed.

1. **`--compare` in `voice/try_stt.py` compares Urdu against Urdu.** The three
   rows are `("auto-detect", None)`, `("forced Urdu", "ur")`,
   `("forced English", "en")`, and the `None` row is produced by
   `default_backend()`. Since 30 Aug 2026 `default_backend()` resolves its
   language from `DEFAULT_WHISPER_LANGUAGE`, which is `ur`, not `auto`. So the
   row labelled "auto-detect" is a second forced-Urdu pass, and the mode's
   stated purpose — vary only the language hint — is half defeated.
   Pinned as characterisation, not endorsement, by
   `test_compare_row_one_says_auto_detect_but_runs_the_configured_language`.
   That test failing is the signal that someone fixed this and the name needs
   updating.

2. **`voice/try_stt.py`'s own documentation contradicts the shipped default.**
   The module docstring says "the language is left on ``auto`` on purpose" and
   the `--language` help says "Default: auto-detect". Both were true before
   30 Aug 2026 and are false now. Changing the help string is a CLI change and
   outside a seams-only mandate, so it is reported rather than edited.

3. **`tests/voice/test_local_backend.py` does not pin the `subprocess.run`
   encoding kwargs.** `LocalWhisperBackend._run` passes
   `encoding="utf-8", errors="replace"`, and that is exactly the line whose
   absence caused the 29 Aug wrong conclusion, but no test asserts it. This
   lane covers it end-to-end from `test_try_stt.py` with a real subprocess,
   which proves the behaviour; a direct kwargs assertion belongs next to the
   code, in a file this lane does not own.

4. **`installed_voices()` will report non-voices on a machine with other
   huggingface models cached.** The rule is "any `.pt` under the cache whose
   stem contains `_` and is longer than three characters", so a stem like
   `pytorch_model` passes. `--list` then shows it, and `--voice pytorch_model`
   passes the installed check and fails later inside Kokoro instead of at the
   argument. Current behaviour is recorded honestly in
   `test_files_that_are_not_voice_packs_are_ignored`, which asserts
   `"pytorch_model" in found` with a comment saying so. Tightening the rule is
   a behaviour change, not a seam.

## Not testable offline

Four things, all correctly outside the offline suite:

- **Whether "Hey JARVIS" actually fires** when he says it from across the room,
  and whether it fires when he did not. That is the sensory judgement the
  script exists for, and a fake that returns whatever score the test wrote down
  cannot make it. It also decides whether `wakeword-train` is needed at all.
- **Which Kokoro voice sounds right.** Blueprint 3.2 puts that with him, by ear.
- **Real NPU transcription** — accuracy, and the real-time ratio. Needs the
  built `whisper-cli.exe`, the large-v3 weights, the `.rai` encoder cache and
  the XDNA NPU. `tests/live` is where that belongs; the offline tests assert
  the ratio is *reported*, not what it is.
- **Real microphone capture** through PortAudio. The offline tests assert that
  `record()` asks for 16 kHz mono int16 and writes `PCM_16`, and that
  `_open_stream()` opens the same format — a format mismatch would otherwise be
  a silent resample rather than an error — but not that a device exists.

None of these were marked `live` to paper over. They are hardware and sensory
checks, not skipped unit tests.
