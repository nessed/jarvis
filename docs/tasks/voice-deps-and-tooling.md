# Lane: voice runtime deps + recording/benchmark tooling

Phase 3 (voice), blueprint §3.1 and the agent half of §3.2. This lane installs
the voice stack and writes the two scripts Ali needs in order to do his sensory
half later. It does **not** build whisper.cpp (separate lane,
`docs/tasks/whisper-npu-build.md`) and it does **not** assemble the Pipecat loop
(blueprint 3.3, gated behind both).

## Blueprint detail — carry this, it is the recovery path

From `docs/blueprint.md`:

> **3.1 Builds — CLI agent.** Clone + build amd/whisper.cpp with NPU offload,
> download Whisper large-v3, install openWakeWord, Kokoro (+ voices), Pipecat,
> Silero VAD. Write a benchmark script reporting STT latency on a 10-second
> Urdu/English clip.

> **3.2 Physical layer — you.** Mic placement, run the benchmark, make the call:
> NPU latency fine, or STT flips to Groq Whisper. Listen to Kokoro's voices, pick
> one. Record wake-word samples — 30–50 clips of you saying "Hey JARVIS" at
> different distances and tones. Agent writes the recording script that prompts
> and saves each clip; you just talk at it.

Also from §2 (Voice), unchanged in the current blueprint:

> amd/whisper.cpp fork for NPU-offloaded STT (Urdu/English stays on Whisper
> large-v3 — Parakeet is English/European only), openWakeWord for "Hey JARVIS,"
> Kokoro-82M for TTS, Piper if latency ever matters more than quality,
> XTTS/Chatterbox/F5 for cloning, Pipecat + Silero VAD for the interruptible
> loop, Groq Whisper as the cloud STT fallback.

These are **component decisions, not suggestions**. If openWakeWord, Kokoro,
Pipecat or Silero turns out to be unavailable, abandoned, or broken on this
machine, **stop and report** — do not substitute a different wake-word engine,
TTS model or VAD. That is a Class C stop per `agents.md`.

## Ownership — files this lane may write

```
voice/                          <- new package, this lane creates it
voice/__init__.py
voice/config.py                 <- device/model paths, env var names
voice/record_wakeword.py        <- the clip recorder (blueprint 3.2)
voice/benchmark_stt.py          <- the STT latency benchmark (blueprint 3.1)
tests/voice/                    <- new test package
docs/tasks/deps-voice-runtime.txt   <- dependency list for CORE to integrate
docs/tasks/voice-deps-and-tooling-report.md   <- this lane's report
```

**Nothing else.** Specifically: do not touch `requirements.txt` (append to
`docs/tasks/deps-voice-runtime.txt` instead, per `agents.md`), do not touch any
of the hot files listed in `docs/plan.md`, do not touch `router/routing.py`
(Groq-Whisper fallback routing is `stt-backends`, a separate blocked job — see
"Out of scope" below), and do not commit.

Claim every path above with `tools/work_board_claim.py` before writing, check
`list` first, and release the claim ID after verification.

## What to build

### 1. Dependencies

Install into `.venv` (Python 3.12.10 — **not** `.venv311`, that one is pinned to
3.11.5 for PyFLP only and must not be touched):

- `openwakeword`
- `kokoro` (Kokoro-82M) plus its voice pack
- `pipecat-ai`
- `silero-vad` (or the torch.hub path if that is what the project actually
  ships — verify against the installed package, do not assume)
- whatever audio I/O the above need on Windows (`sounddevice`/`soundfile` or
  `pyaudio` — pick by what actually imports and records on this machine, and say
  which in the report)

Pin exact versions. Write them to `docs/tasks/deps-voice-runtime.txt`, one
`package==version` per line, with a one-line comment above each saying what
needs it. Do **not** edit `requirements.txt`.

If a package will not install on Windows/Python 3.12, report the exact failure
and stop for that package — do not swap in an alternative library.

### 2. `voice/record_wakeword.py`

The clip recorder for blueprint 3.2. Ali runs this and talks at it.

- Prompts for each clip: countdown, "say 'Hey JARVIS'", records a fixed short
  window, saves, moves on.
- Targets 30–50 clips, and **varies the prompt** across distance and tone the way
  the blueprint asks for ("close, normal voice", "across the room", "quiet",
  "fast") so the resulting set is actually varied rather than 40 identical clips.
- Saves to a gitignored directory (`voice/wakeword_clips/` — add the ignore rule
  to `.gitignore` **only if** no lane holds it; if it is claimed, report the one
  line needed and let CORE add it). These are recordings of Ali's voice: they are
  personal data, they must never be committed, and nothing in this lane uploads
  them anywhere.
- Writes at the sample rate openWakeWord's training path actually expects — read
  that from the installed package, do not guess.
- Resumable: re-running continues the numbering instead of overwriting clip 1.
- `--dry-run` lists what it would record and touches no device.

### 3. `voice/benchmark_stt.py`

The latency benchmark for blueprint 3.1. Ali reads its number and makes the
NPU-vs-Groq call.

- Takes a ~10s Urdu/English audio clip as input (accept a path; if none given,
  say clearly that a clip is needed rather than inventing one).
- Reports wall-clock STT latency and the transcript, per backend, in a table.
- Structured so a backend is a small pluggable object — local whisper.cpp today,
  Groq Whisper later — but **only implement the backends whose runtime actually
  exists on this machine right now.** If whisper.cpp is not yet built (the other
  lane owns that), the local backend must report "not available" cleanly rather
  than crash, and the script must still run.
- **Do not implement the Groq backend by touching `router/routing.py`.** See
  below.

### 4. Tests

`tests/voice/`, following the existing repo pattern (look at
`tests/tools/test_run_backfill.py` and `tests/tools/test_start_jarvis.py` — both
test CLI-shaped tools against fakes; mirror that). Test against fakes, never
against a real microphone or a real model download. The full offline suite must
stay green and must not become dependent on audio hardware.

## Out of scope — report, do not build

- **whisper.cpp build and the large-v3 download.** Separate lane.
- **The Pipecat loop itself** (wake → VAD → STT → bus → TTS with barge-in).
  Blueprint 3.3, gated behind this lane and the whisper lane both landing.
- **Groq Whisper routing.** `docs/plan.md` records `stt-backends` as an open
  Class C decision: `router/routing.py` is chat-completions-only, `TASK_PROFILES`
  has no audio profile, and Groq STT is a different endpoint shape. Whether voice
  owns its own client or the router grows an audio lane is **not this lane's
  call**. Leave the seam and report it.
- **Anything requiring Ali's ears or his microphone.** Mic placement, voice
  choice, judging the benchmark, actually recording clips. Build the tools; he
  runs them.

## Verification

Cite the command and its output for every claim:

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
```

That is the full offline suite and it is the only run that proves the tree. A
green focused run is not a completion claim. Claim `test-workspace` before
running it — lanes must not share `.pytest-basetemp`.

Also cite, for each installed package, the import that proves it loaded on this
machine and its resolved version.

## Report

Write `docs/tasks/voice-deps-and-tooling-report.md` covering:

- What landed, with the command and output that proves each piece.
- What broke, exactly, including any package that would not install.
- What was specified but not done, and why.
- Every dependency added, in `docs/tasks/deps-voice-runtime.txt`.
- Any shared interface touched, and every implementer and test double of it —
  including ones in files this lane does not own.
- The `.gitignore` line needed for the clip directory, if this lane could not
  add it.
