# Lane: whisper.cpp NPU build + Whisper large-v3

Phase 3 (voice), the build half of blueprint §3.1. This lane produces a working
local STT runtime on this laptop's NPU and nothing else. It does not install the
wake-word/TTS/VAD stack (separate lane,
`docs/tasks/voice-deps-and-tooling.md`) and it does not assemble the Pipecat loop
(blueprint 3.3, gated behind both lanes).

## Run-exclusivity — read this before starting

**This lane may not start while `laptop-power-lag-live-capture` holds a claim.**
Check `python tools/work_board_claim.py list` first. A from-source C++ build plus
a multi-GB download pegs CPU, disk and thermals; running it during a
battery-transition power capture poisons that capture's data, and that data is
what Ali is being asked to judge. `docs/plan.md` names `whisper-npu-build` as
machine-exclusive for exactly this reason.

Claim `machine-exclusive` as a resource, plus every file below, before writing
anything. Release the claim ID after verification.

Independently: this laptop is currently under investigation for severe
battery-only lag, and a `108 C` ACPI thermal event is on record
(`docs/tasks/laptop-power-lag-hp-resolution-report.md`). **Run this lane on AC
power.** If the machine thermally throttles or becomes unresponsive during the
build, stop and report rather than retrying — a second identical failure is a
`docs/blockers/` entry, not another attempt.

## Blueprint detail — carry this, it is the recovery path

From `docs/blueprint.md`:

> **3.1 Builds — CLI agent.** Clone + build amd/whisper.cpp with NPU offload,
> download Whisper large-v3, install openWakeWord, Kokoro (+ voices), Pipecat,
> Silero VAD. Write a benchmark script reporting STT latency on a 10-second
> Urdu/English clip.

> amd/whisper.cpp fork for NPU-offloaded STT (**Urdu/English stays on Whisper
> large-v3 — Parakeet is English/European only**)

> **Thresholds that change the plan:** NPU Whisper too slow for live voice →
> Groq Whisper free tier.

Two things in there are decisions, not suggestions:

1. **The `amd/whisper.cpp` fork, not upstream `ggerganov/whisper.cpp`.** The fork
   is what carries the NPU offload path. If the fork is gone, unbuildable, or no
   longer supports this hardware, **stop and report**. Do not silently build
   upstream on CPU and call the lane done — a CPU build is a different component
   and would make the §3.2 benchmark Ali is asked to judge a fake number.
2. **Whisper large-v3, not a smaller or English-only model.** Urdu is the reason.
   Do not substitute `distil-whisper`, `medium`, or Parakeet.

The machine is an HP OmniBook X Flip, **AMD Ryzen AI 7 350 w/ Radeon 860M**,
Windows 11 Pro 25H2 build 26200. AMD chipset bundle 8.08.12.551, AMD PMF driver
26.10.15.0, AMD Software 26.7.1 (all verified 2026-08-29,
`docs/tasks/laptop-power-lag-hp-resolution-report.md`). The NPU is the XDNA/Ryzen
AI NPU on that part — confirm what the installed driver actually exposes rather
than assuming a toolchain version.

## Ownership — files this lane may write

```
voice/whisper/                  <- build output, models, and the local STT wrapper
voice/whisper/__init__.py
voice/whisper/local_backend.py  <- the backend object voice/benchmark_stt.py will call
tests/voice/test_local_backend.py
docs/tasks/deps-whisper-npu.txt <- any Python deps, for CORE to integrate
docs/tasks/whisper-npu-build-report.md
```

Anything large — the cloned source tree, build artifacts, the large-v3 weights —
goes somewhere gitignored. Report the `.gitignore` lines needed; if `.gitignore`
is claimed by another lane, do not edit it, just name the lines in the report.

**Do not** touch `requirements.txt` (append to `docs/tasks/deps-whisper-npu.txt`
instead), any hot file in `docs/plan.md`, `router/routing.py`, `.venv311`, or
`voice/benchmark_stt.py` / `voice/record_wakeword.py` (the other lane owns
those). Do not commit.

## Coordination with the other voice lane

`voice/benchmark_stt.py` (other lane) calls into a pluggable STT backend. This
lane owns `voice/whisper/local_backend.py` and must expose a small, obvious
interface for it:

- a callable that takes an audio file path and returns `(transcript, latency_seconds)`
- an availability check that returns False cleanly when the build or the model is
  missing, so the benchmark still runs before this lane lands

Agree the shape by writing it in the report. If the other lane has already
landed and its expected shape differs, **report the mismatch and name both
sides** — do not edit their file. Per `agents.md`, a lane that changes a shared
interface names every implementer, including ones it cannot edit.

## What to build

1. Confirm the toolchain the fork actually requires on Windows (compiler, CMake,
   the AMD NPU SDK/runtime and its version) against the fork's own current
   documentation. Cite what you read. Do not rely on this brief for versions.
2. Clone `amd/whisper.cpp`, build with the NPU offload path enabled.
3. Download Whisper **large-v3** in the format the built binary consumes.
4. Prove it transcribes: run the built binary against a real short audio file
   and cite the command, the transcript, and the wall-clock time. A build that
   compiles but has never transcribed anything is not a completed lane.
5. Wrap it in `voice/whisper/local_backend.py` per the interface above.
6. Tests in `tests/voice/test_local_backend.py`, against fakes — the offline
   suite must not depend on the model, the binary, or audio hardware being
   present.

## Verification

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
```

Full offline suite, not a focused subset. Claim `test-workspace` before running
it. Cite its output.

Separately cite: the build command and its final output, the model file's path
and size, and the real transcription run from step 4.

## Report

Write `docs/tasks/whisper-npu-build-report.md` covering what landed with proof,
what broke exactly, what was specified but not done, the deps added, the
`.gitignore` lines needed, the backend interface shape, and — if NPU offload
could not be made to work — the exact evidence, so the blueprint's documented
fallback (Groq Whisper free tier) can be decided on by Ali rather than assumed
by an agent.
