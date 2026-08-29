# Lane report: voice runtime deps + recording/benchmark tooling

Brief: `docs/tasks/voice-deps-and-tooling.md`. Role BUILD. Nothing committed.

Claim `b0267707fadd4a69b0a29d7491269c9d` (files), claim
`0138901acd114786958f219c381373cb` (`test-workspace`, released after the full
run). No conflict: the only other claim at start was
`laptop-power-lag-live-capture`, which was not touched.

---

## Bottom line

All four blueprint-specified components installed, imported and **ran** on this
machine. Nothing was substituted. Both scripts are built and tested.

One thing broke and is reported, not worked around: `torchaudio` 2.11 made
`silero_vad.read_audio()` demand `torchcodec`. It affects silero's file-reading
convenience helper only — the VAD itself runs fine — and the fix is a call the
`voice-loop` lane should make, not this one.

---

## What landed

### 1. Dependencies

Installed into `.venv` (Python 3.12.10). `.venv311` was not touched.

Every package below is proved by an import **and** by actually running it.

```
$ .venv/Scripts/python.exe -c "import importlib.metadata as md; ..."
openwakeword            0.6.0
  openwakeword.model    ok
silero-vad              6.2.1
  load_silero_vad        True
kokoro                  0.9.4
  KPipeline              KPipeline
pipecat-ai              1.8.1
  pipecat.frames.frames  ok
sounddevice             0.5.6
soundfile               0.14.0
torch                   2.13.0
torchaudio              2.11.0
onnxruntime             1.24.4
```

Pipecat also logs its own banner on import, which is independent confirmation
it initialised rather than just resolving:

```
16:50:12 | __init__:54 | INFO | Pipecat 1.8.1 (Python 3.12.10 ...)
```

Pinned versions are in **`docs/tasks/deps-voice-runtime.txt`**, one
`package==version` per line with the reason above each. `requirements.txt` was
not touched.

**openWakeWord actually infers.** Feature models plus the pretrained
`hey_jarvis_v0.1` classifier were fetched into the venv via
`openwakeword.utils.download_models(model_names=['hey_jarvis_v0.1'])`, then run
over a synthetic 10 s tone:

```
openWakeWord models loaded: ['hey_jarvis_v0.1']
predict_clip frames: 149 max score: 0.0011
```

149 frames scored, near-zero confidence on a pure tone — which is the right
answer. Worth knowing for the `wakeword-train` lane: openWakeWord ships a
pretrained `hey_jarvis` model, so there may be a usable wake word before Ali's
clips are trained on at all.

**Silero VAD ships its own weights.** The brief asked whether the project uses
the pip package or the `torch.hub` path. Answer: the pip package, and it needs
no download — the wheel contains the weights:

```
$ find .venv/Lib/site-packages/silero_vad -type f
.venv/Lib/site-packages/silero_vad/data/silero_vad.jit
.venv/Lib/site-packages/silero_vad/data/silero_vad.onnx
.venv/Lib/site-packages/silero_vad/data/silero_vad_16k.safetensors
...
```

and it runs offline:

```
sr 16000 samples 160000
speech segments found in a pure 220Hz tone: 0
VAD ran on wheel-bundled weights, no torch.hub, no torchcodec
```

Zero speech segments in a sine wave is the correct answer.

**Kokoro synthesizes.** `KPipeline(lang_code='a')` downloaded Kokoro-82M and
produced real audio:

```
KOKORO OK samples 82800 bytes 165644
```

82 800 samples at 24 kHz is 3.45 s of speech from a 45-character sentence.

**The voice pack is on disk**, so the `kokoro-tts` lane (Ali picking a voice by
ear) does not have to download during his listening session:

```
voice pack: 54 voices
af_alloy, af_aoede, af_bella, af_heart, ... zm_yunxia, zm_yunyang
```

313 MB total under `~/.cache/huggingface/hub/models--hexgrad--Kokoro-82M`.

**Audio I/O: `sounddevice` + `soundfile`, not `pyaudio`.** The brief said to
pick by what actually imports and records here. `sounddevice` installs as a
pure wheel with PortAudio bundled and enumerated real hardware:

```
sounddevice 0.5.6
soundfile 0.14.0 1.2.2
input devices: 27
  - Microsoft Sound Mapper - Input
  - Microphone Array (AMD Audio Dev
  - Primary Sound Capture Driver
  ...
```

`pyaudio` was not tried, because it needs a C toolchain on Windows/3.12 and
there was no reason to reach for it once this worked. This is not a component
substitution — the blueprint names no audio I/O library.

### 2. `voice/config.py`

Format constants and env-var names. The recording format is **read out of the
installed openWakeWord**, not guessed, and the file cites where:

- `openwakeword/data.py:120` — `sox ... -G -r 16000 -c 1 -b 16`
- `openwakeword/train.py:816` — `# training data is always 16 khz`
- `openwakeword/utils.py:41` — `sr: int = 16000`

So: **16 kHz, mono, PCM_16**.

Clip length likewise: `openwakeword/train.py:747-751` clamps its training
window to a 32 000-sample floor, which is 2.0 s at 16 kHz. The recorder's
default window is exactly that, so no clip is padded up from something shorter.

Env vars, following the existing `JARVIS_*` convention:
`JARVIS_VOICE_CLIP_DIR`, `JARVIS_VOICE_INPUT_DEVICE`, `JARVIS_WHISPER_CPP_BIN`,
`JARVIS_WHISPER_MODEL`, `JARVIS_WHISPER_LANGUAGE`.

`JARVIS_WHISPER_LANGUAGE` defaults to `auto`, not `en`. Blueprint §2 keeps
Urdu/English on large-v3 specifically because Parakeet is English/European
only; hardcoding `en` would throw that away.

### 3. `voice/record_wakeword.py`

```
$ .venv/Scripts/python.exe -m voice.record_wakeword --dry-run --count 8
Clip directory: voice\wakeword_clips
Already recorded: 0
This run: 8 clip(s), 2s each at 16000 Hz mono PCM_16
0001  Close to the mic, normal speaking voice  -> hey_jarvis_0001_close-normal.wav
0002  About an arm's length away, normal voice  -> hey_jarvis_0002_arms-length-normal.wav
0003  Across the room, as if calling out  -> hey_jarvis_0003_across-room.wav
0004  Quietly, almost under your breath  -> hey_jarvis_0004_quiet.wav
0005  Fast and clipped, like you're mid-sentence  -> hey_jarvis_0005_fast.wav
0006  Slowly and deliberately, drawing it out  -> hey_jarvis_0006_slow.wav
0007  Facing away from the mic, normal volume  -> hey_jarvis_0007_turned-away.wav
0008  Flat and tired, low energy  -> hey_jarvis_0008_tired.wav

Dry run: no device was opened and no file was written.
```

Against the brief's list:

- **Prompts, countdown, fixed window, save, next** — yes. 3-2-1 countdown then
  `NOW - say "Hey JARVIS"`.
- **Varied, not 40 identical clips** — eight conditions covering distance
  (close / arm's length / across the room / turned away) and tone (normal /
  quiet / fast / slow / tired), cycled evenly. A 40-clip run gets five of each.
  Asserted, not just intended:
  `test_the_plan_cycles_conditions_instead_of_repeating_one`.
- **Gitignored directory** — `voice/wakeword_clips/`. See "gitignore" below.
- **openWakeWord's expected sample rate, read not guessed** — above.
- **Resumable** — numbering continues from the highest clip on disk. Ctrl-C
  mid-session keeps everything already recorded and prints how to resume.
  `test_a_resumed_run_does_not_overwrite_clip_one` and
  `test_ctrl_c_mid_session_keeps_what_was_already_recorded`.
- **`--dry-run` touches no device** — enforced in the test by replacing
  `SoundDeviceRecorder`, `SoundFileWriter` and `record_session` with functions
  that raise, so any device access at all fails the test.

Also `--list-devices`, for mic placement. It records nothing.

`sounddevice` and `soundfile` are imported *inside* the functions that use
them, so importing the module — which the offline suite does — never opens the
microphone.

### 4. `voice/benchmark_stt.py`

Run against a synthetic 10 s WAV, in the state the machine is actually in
today (whisper.cpp unbuilt):

```
$ .venv/Scripts/python.exe -m voice.benchmark_stt --clip .../tone10s.wav
Clip: ...\tone10s.wav (10.0s)
Runs per backend: 1

backend              latency  xRT  transcript / why not
-------------------  -------  ---  ---------------------------------------------------------
whisper.cpp (local)  -        -    not available: JARVIS_WHISPER_CPP_BIN is not set (whisper.cpp not built yet)
EXIT=3
```

That is the required behaviour: **reports "not available" cleanly and the
script still runs**.

With no clip at all:

```
$ .venv/Scripts/python.exe -m voice.benchmark_stt
A clip is required. Blueprint 3.1 measures STT latency on a ~10 second
Urdu/English recording; there is no default clip and one will not be
invented. ...
EXIT=2
```

Reports latency (median over `--runs`), the real-time factor, and the
transcript per backend. It warns when the clip is not about 10 s, because a
latency measured on 2 s of audio is not the number Ali is being asked to judge.
`--json` for machine-readable output.

A backend is a small pluggable object: `name`, `availability() -> Availability`,
`transcribe(clip) -> str`. Only `WhisperCppBackend` is implemented — see "not
done" below.

### 5. Tests

`tests/voice/`, mirroring `tests/tools/test_run_backfill.py` and
`test_start_jarvis.py`: `main(argv) -> int`, fakes injected, `capsys` for
output, `monkeypatch` for env. No `__init__.py`, matching every other test
package in the repo.

```
$ .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=<scratch> tests/voice
61 passed in 12.63s
```

61 tests: 24 for the recorder, 27 for the benchmark, 10 for config. **None of
them touch a microphone, a model, or the network.** No audio library is even
imported except through a `sys.modules` stub in the one `--list-devices` test.

### 6. `.gitignore`

The brief said to add the rule only if no lane held the file. `list` showed no
claim on it, so this lane claimed and added it:

```
# Wake-word recordings of Ali's voice (voice/record_wakeword.py). Personal data:
# never committed, never uploaded.
voice/wakeword_clips/
```

Nothing in this lane uploads a recording anywhere. The only network calls made
were package installs and the openWakeWord / Kokoro model downloads.

---

## What broke

**`silero_vad.read_audio()` is unusable with the resolved torchaudio.**

```
$ .venv/Scripts/python.exe -c "from silero_vad import load_silero_vad, read_audio; ..."
RuntimeError: torchaudio version 2.11.0+cpu requires torchcodec for audio I/O.
Install torchcodec or pin torchaudio < 2.9
```

Scope: this is silero's *file-reading convenience helper*, not the VAD. The VAD
itself runs correctly when fed a tensor read with `soundfile` — proved above.
`torchcodec` was **not** installed and `torchaudio` was **not** pinned down,
because either choice constrains `requirements.txt`, which this lane does not
own, and the Pipecat loop feeds live frames rather than files, so it may never
need `read_audio()` at all. Two options for whoever builds `voice-loop`:

1. Add `torchcodec` (needs FFmpeg on Windows — unverified here).
2. Pin `torchaudio<2.9`.
3. Or read audio with `soundfile` and never call `read_audio()`, which is what
   this lane did and what already works.

**`onnxruntime` was silently downgraded, 1.29.0 → 1.24.4.** `pip install
openwakeword` alone picked 1.29.0; installing `pipecat-ai` afterwards pulled it
back, because pipecat pins `onnxruntime~=1.24.3`:

```
pipecat-ai -> ['onnxruntime~=1.24.3', ...]
openwakeword -> ['onnxruntime <2,>=1.10.0', ...]
```

Both constraints are satisfied at 1.24.4, and openWakeWord was re-verified
running inference on it afterwards. But an unpinned reinstall drifts back to
1.29 and then breaks pipecat, so `onnxruntime==1.24.4` is in the deps file.

**Nothing else failed.** No package refused to install on Windows / Python
3.12. No blueprint component was unavailable, abandoned or broken, so there was
no Class C stop to raise.

---

## Specified but not done

- **`.env.example` lines.** Five new env vars, and `.env.example` is contended
  three ways per `docs/plan.md` ("one lane writes the whole file in one pass").
  Handing them over instead of writing them:

  ```
  # Voice runtime (voice/config.py)
  JARVIS_VOICE_CLIP_DIR=
  JARVIS_VOICE_INPUT_DEVICE=
  JARVIS_WHISPER_CPP_BIN=
  JARVIS_WHISPER_MODEL=
  JARVIS_WHISPER_LANGUAGE=
  ```

  All five are optional; every one has a working default.

- **`requirements.txt`.** Not touched, per `agents.md`. See
  `docs/tasks/deps-voice-runtime.txt`.

- **No Groq Whisper backend.** `docs/plan.md` records `stt-backends` as an open
  Class C decision — `router/routing.py` is chat-completions-only,
  `TASK_PROFILES` has no audio profile, Groq STT is a different endpoint shape.
  The seam is left open: adding a `GroqWhisperBackend` class to
  `voice/benchmark_stt.py` later touches nothing else in the module.
  `router/routing.py` was not opened.

- **whisper.cpp build and the large-v3 download.** `whisper-npu-build`'s.
  `voice/config.py` deliberately has **no default path guess** for either
  artifact — guessing where another lane will put its build output is how two
  lanes end up disagreeing about a path neither owns. The whisper lane needs to
  set `JARVIS_WHISPER_CPP_BIN` and `JARVIS_WHISPER_MODEL`, and confirm that
  `whisper_cpp_command()`'s flags (`-m`, `-f`, `-l`, `-nt`) match the CLI it
  builds. `--whisper-arg` covers a mismatch without an edit.

- **The Pipecat loop.** Blueprint 3.3, gated behind this lane and the whisper
  lane.

- **Anything needing Ali's ears or mic.** Mic placement, recording the clips,
  listening to the 54 voices, judging the benchmark. The tools are built; he
  runs them.

---

## Shared interfaces

**Two new `Protocol`s, both introduced by this lane, both with zero
implementers outside it.** Nothing existing was widened, so no double anywhere
in the repo is stranded.

- `voice.record_wakeword.Recorder` — `record(*, seconds, sample_rate, channels,
  device)`. Implementers: `voice/record_wakeword.py SoundDeviceRecorder`;
  test double `tests/voice/test_record_wakeword.py FakeRecorder`.
- `voice.record_wakeword.ClipWriter` — `write(path, data, sample_rate)`.
  Implementers: `voice/record_wakeword.py SoundFileWriter`; test double
  `tests/voice/test_record_wakeword.py FakeWriter`.
- `voice.benchmark_stt.SttBackend` — `name`, `availability()`, `transcribe()`.
  Implementers: `voice/benchmark_stt.py WhisperCppBackend`; test double
  `tests/voice/test_benchmark_stt.py FakeBackend`.

No hot file was touched. `router/routing.py`, `bus/whatsapp_client.py`,
`executor/*`, `db/jobs.py`, `memory/*` and `tests/router/test_routing.py` were
not opened. `db.jobs.JobRepository`, `ChainQueue`, `TurnStore`, `FactExtractor`,
`ConversationMemory` and `Job` are all untouched.

---

## Full-suite verification

Ran with `test-workspace` claimed, released immediately after:

```
$ .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
........................................................................ [ 12%]
........................................................................ [ 24%]
........................................................................ [ 36%]
........................................................................ [ 48%]
........................................................................ [ 60%]
........................................................................ [ 72%]
........................................................................ [ 84%]
........................................................................ [ 96%]
...................                                                      [100%]
595 passed, 5 deselected, 2 warnings in 30.99s
```

Green tree, not just a green lane. The two warnings are pre-existing Supabase
deprecation warnings in `tests/test_integration.py`, unrelated to this lane.

Note the tree also held other lanes' uncommitted work at the time
(`ingest/noise.py`, `memory/review.py`, `tools/review_facts.py` and their
tests). The 595 includes them and they are green too.

`pytest -m live tests/live` was **not** run: this lane added no live probe, and
the acceptance criteria it would cover (benchmark latency, voice choice, clip
recording) are Ali's sensory calls, not automated ones.

---

## Files this lane wrote

```
voice/__init__.py
voice/config.py
voice/record_wakeword.py
voice/benchmark_stt.py
tests/voice/test_config.py
tests/voice/test_record_wakeword.py
tests/voice/test_benchmark_stt.py
docs/tasks/deps-voice-runtime.txt
docs/tasks/voice-deps-and-tooling-report.md
.gitignore                                  (one rule appended)
```

`tests/voice/__init__.py` was claimed but deliberately not created — no other
test package in this repo has one.
