# Lane report: amd/whisper.cpp NPU build + Whisper large-v3

Brief: `docs/tasks/whisper-npu-build.md`. Role BUILD. Nothing committed.

Claims: `3cb684da19a14a148ec3dd9168f796b2` (files + `machine-exclusive`),
`675804f8ccf147af9332c02dc3a130c3` (`test-workspace`, released immediately
after the full run). `laptop-power-lag-live-capture` was already released when
this lane started, so the run-exclusivity block in the brief did not apply.
Machine was on AC throughout (`Win32_Battery.BatteryStatus = 2`). No thermal
event, no throttling, no unresponsiveness.

---

## Bottom line

**NPU offload works, and it is 12x faster than CPU on the encoder.** The
specified components were built as specified — the `amd/whisper.cpp` fork, not
upstream; Whisper large-v3, not a smaller model. Nothing was substituted and
there was no Class C stop.

**The latency answer is "it depends on the flags", and the spread is large.**
As invoked today the local backend takes **32s to transcribe an 11s clip**
(2.9x real time). Three quarters of that is avoidable and none of it is the
NPU: model reload, a language-autodetect pass, and beam-5 decoding on the CPU.
Numbers and the decision that follows are in **"What Ali has to judge"** below.

One thing broke and is reported, not worked around: `www.amd.com` and
`account.amd.com` are unreachable from this connection, which is where the
fork's README sends you for the FlexML runtime.

---

## What landed

### 1. The fork, built with the NPU path on

```
$ git -C voice/whisper/src log -1 --format="%H %ad %s"
b40e6c836b18f9cde1c9ea6eeed3efb98dd798a6 Wed May 13 09:59:29 2026 -0700 Update README.md
```

`https://github.com/amd/whisper.cpp`, master. Not `ggml-org/whisper.cpp`.

Configure:

```
$ cmake -B build-vitisai -G "Visual Studio 17 2022" -A x64 -DWHISPER_VITISAI=ON \
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5
...
-- ggml version: 0.9.5
-- ggml commit:  b40e6c8
-- Configuring done (60.1s)
-- Generating done (0.8s)
-- Build files have been written to: C:/Users/Ali/Desktop/jarvis/voice/whisper/src/build-vitisai
```

The flag that matters is in the cache, not just on the command line:

```
$ grep -i "WHISPER_VITISAI\|FlexmlRT_DIR" voice/whisper/src/build-vitisai/CMakeCache.txt
FlexmlRT_DIR:PATH=C:/Users/Ali/Desktop/jarvis/voice/whisper/flexmlrt/share/cmake/FlexmlRT
WHISPER_VITISAI:BOOL=ON
```

Build:

```
$ cmake --build build-vitisai --config Release -j
...
  whisper-cli.vcxproj -> C:\...\build-vitisai\bin\Release\whisper-cli.exe
  whisper-server.vcxproj -> C:\...\build-vitisai\bin\Release\whisper-server.exe
```

Exit 0. Only `C4267`/`C4244` narrowing warnings, all in whisper.cpp's own VAD
and example code, none in the VitisAI path.

`flexmlrt.dll` was then copied next to the binaries, which is what upstream's
own self-hosted CI does (`ggml-org/whisper.cpp
.github/workflows/build-self-hosted.yml`, step "Copy FlexML DLLs to build
output").

### 2. Whisper large-v3, and the encoder cache it cannot run without

```
$ ls -la voice/whisper/models/
-rw-r--r-- 1 Ali 197121  741558840 Aug 29 18:53 ggml-large-v3-encoder-vitisai.rai
-rw-r--r-- 1 Ali 197121 3095033483 Aug 29 19:00 ggml-large-v3.bin
```

- `ggml-large-v3.bin` — 3,095,033,483 bytes, from
  `huggingface.co/ggerganov/whisper.cpp`. `HTTP=200 bytes=3095033483`.
- `ggml-large-v3-encoder-vitisai.rai` — 741,558,840 bytes, from
  `huggingface.co/amd/whisper-large-v3-onnx-npu`. `HTTP=200 bytes=741558840`.

**The `.rai` is not optional and it is not a cache in the "makes it faster"
sense.** It is AMD's precompiled NPU encoder graph. In a `WHISPER_USE_VITISAI`
build, `whisper_init_state` returns `nullptr` if it will not load, and the CLI
aborts (`src/whisper.cpp:3489-3495`). There is **no silent CPU fallback**.

That is the property that makes the proof below airtight: a transcript out of
this binary could not have come from a CPU encoder.

The path is derived from the model path, not configured
(`whisper_get_vitisai_path_encoder_cache`, `src/whisper.cpp:3367-3376`): strip
after the last `.`, append `-encoder-vitisai.rai`. `voice/whisper/local_backend.py`
reimplements exactly that so it agrees with the binary rather than guessing.

### 3. It transcribes, and the NPU is demonstrably doing the encoding

```
$ cd voice/whisper
$ time ./src/build-vitisai/bin/Release/whisper-cli.exe \
      -m models/ggml-large-v3.bin -f src/samples/jfk.wav -l auto -nt

XRT build version: 2.21.0
Build hash: 15e6319be8de1e76a6150111a3861729e988fdb5
Build date: 2026-05-07 16:04:09
whisper_init_state: Vitis AI model loaded
system_info: n_threads = 4 / 16 | WHISPER : VITISAI = 1 | COREML = 0 | OPENVINO = 0 | ...

main: processing 'src/samples/jfk.wav' (176000 samples, 11.0 sec), 4 threads, ...
whisper_full_with_state: auto-detected language: en (p = 0.935616)
whisper_vitisai_encode: Vitis AI model inference completed.
whisper_vitisai_encode: Vitis AI model inference completed.

 And so my fellow Americans, ask not what your country can do for you, ask what you can do for your country.

whisper_print_timings:     load time =  7677.57 ms
whisper_print_timings:   encode time = 14118.27 ms /     2 runs (  7059.14 ms per run)
whisper_print_timings:   batchd time =  6736.92 ms /   130 runs (    51.82 ms per run)
whisper_print_timings:    total time = 32363.79 ms

real    0m33.434s
```

Four independent confirmations the NPU ran, not the CPU:

1. `VITISAI = 1` in `system_info`.
2. `whisper_init_state: Vitis AI model loaded` — the 741 MB NPU graph mapped.
3. `whisper_vitisai_encode: Vitis AI model inference completed.`, once per
   encoder pass.
4. XRT 2.21.0 initialised. XRT is the XDNA runtime; it does not load for a CPU
   build.

The clip is `samples/jfk.wav` from the fork: real speech, 11.0 s, 16 kHz mono —
within the sibling benchmark's tolerance for the blueprint's "~10 second"
requirement. It is English. A **real Urdu/English clip is Ali's to record**;
`-l auto` correctly detected `en` at p=0.936 here, which is the mechanism Urdu
would use.

### 4. `voice/whisper/local_backend.py`

Through the wrapper, end to end, on this machine:

```
$ JARVIS_WHISPER_CPP_BIN=voice/whisper/src/build-vitisai/bin/Release/whisper-cli.exe \
  JARVIS_WHISPER_MODEL=voice/whisper/models/ggml-large-v3.bin \
  .venv/Scripts/python.exe -m voice.whisper.local_backend --check
binary:        voice\whisper\src\build-vitisai\bin\Release\whisper-cli.exe
model:         voice\whisper\models\ggml-large-v3.bin
encoder cache: voice\whisper\models\ggml-large-v3-encoder-vitisai.rai
language:      auto
available:     True

$ ... -m voice.whisper.local_backend --clip voice/whisper/src/samples/jfk.wav
latency: 37.93s
transcript: And so my fellow Americans, ask not what your country can do for you, ask what you can do for your country.
```

### 5. Tests

```
$ .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=<scratch> \
      tests/voice/test_local_backend.py
46 passed in 0.46s
```

All against fakes. No test needs the binary, the 3 GB weights, the 741 MB
`.rai`, the FlexML runtime, the NPU, or a microphone. The only real file any
test touches is one it wrote into `tmp_path` so `Path.exists()` has something
true to say.

An `autouse` fixture clears `JARVIS_WHISPER_*` from the environment, because on
*this* machine the real build now exists and would otherwise leak into tests
that are supposed to see a missing one.

---

## What Ali has to judge

Blueprint 3.2: *"NPU latency fine, or STT flips to Groq Whisper."* Here is the
number, and the reason it is not a single number. All figures: same 11.0 s
clip, same large-v3 weights, same machine, AC power.

| # | binary | flags | encode | decode | load | **total** | xRT |
|---|--------|-------|--------|--------|------|-----------|-----|
| 1 | VITISAI | `-l auto` (as shipped) | 14.1 s / 2 runs | 6.7 s | 7.7 s | **32.4 s** | 2.9x |
| 2 | VITISAI | `-l auto -bs 1 -bo 1` | 14.1 s / 2 runs | 0.2 s | 4.0 s | **22.1 s** | 2.0x |
| 3 | VITISAI | `-l en -bs 1 -bo 1` | 7.1 s / 1 run | 0.2 s | 4.2 s | **14.3 s** | 1.3x |
| 4 | VITISAI | `-l auto -t 16` | 17.8 s / 2 runs | 11.6 s | 6.4 s | **40.1 s** | 3.6x |
| 5 | **CPU only** | `-l auto` | **175.0 s / 2 runs** | 6.6 s | 4.7 s | **186.8 s** | 17.0x |

Every row produced the identical, correct transcript.

**Row 5 is the headline.** A CPU-only build of the same source, same model, was
built solely to get this baseline (`build-cpu/`, `VITISAI = 0` in its
`system_info`). The NPU encoder is **87.5 s -> 7.1 s per pass, 12.4x faster**.
The blueprint's NPU choice is vindicated; the fork is doing exactly what it
claims.

**What the remaining 32 s is made of, and how much of it is real:**

- **Model load, ~4-8 s.** Paid once per *process*. The CLI reloads 3 GB every
  invocation. `whisper-server.exe` was built alongside and keeps the model
  resident; a live loop would not pay this per utterance.
- **Language autodetect, ~7 s.** `-l auto` costs an entire extra encoder pass —
  rows 2 vs 3 differ only in that flag, and the encode run count goes 2 -> 1.
- **Encode, ~7 s.** The actual NPU work. Roughly constant for any clip up to
  30 s, because whisper pads to a 30 s window.
- **Decode, 0.2-6.7 s.** CPU. Beam-5 (the default) costs 6.7 s; greedy costs
  0.2 s at no quality difference *on this clip*.
- **More threads make it worse** (row 4). Leave `-t` alone; 16 threads on 8
  cores contends with the NPU driver's own work.

**So the honest steady-state estimate** for a warm `whisper-server`, greedy
decode, language pinned: **~7.3 s for an 11 s utterance, 0.66x real time.**
Faster than real time, and plausibly fine for live voice.

**But two of those three savings have a cost that is Ali's to accept:**

1. **Pinning the language throws away Urdu.** `voice/config.py` defaults
   `JARVIS_WHISPER_LANGUAGE` to `auto` specifically because blueprint §2 keeps
   Urdu/English on large-v3. Pinning `en` is a 7 s saving and a capability
   loss. **This is a Class C call, not an agent's** — it is not made here, and
   the default is left at `auto`.
2. **Greedy decode is a quality tradeoff.** Free on one clean English clip.
   Unmeasured on accented or code-switched Urdu/English, which is the actual
   workload.

**What I would not do yet:** flip to Groq. The blueprint threshold is "NPU
Whisper too slow for live voice", and the 32 s figure that looks like a fail is
mostly CLI process overhead, not the NPU. The next cheap experiment is
`whisper-server` plus a real Urdu/English clip, which needs Ali's voice.

`amd/whisper-large-turbo-onnx-npu` also exists in AMD's collection with a
prebuilt `.rai`. It would be materially faster. It is **not** large-v3 and
therefore not this lane's to adopt.

---

## What broke

### `www.amd.com` and `account.amd.com` are unreachable from this connection

The fork's README sends you to
`account.amd.com/en/forms/downloads/ryzenai-eula-public-xef.html?filename=flexmlrt1.7.0-win.zip`
for the FlexML runtime. That host hangs.

```
$ curl -sS -o /dev/null --max-time 25 -w "%{http_code}\n" https://account.amd.com/
000   (curl: (28) Operation timed out after 25002 ms with 0 bytes received)
$ curl -sS -o /dev/null --max-time 25 -w "%{http_code}\n" https://www.amd.com/
000   (curl: (28) ... remote_ip 23.41.36.125)
```

It is not DNS and it is not a dead route:

```
$ ping www.amd.com          -> 2/2 received, avg 96 ms
$ Test-NetConnection www.amd.com -Port 443  -> TcpTestSucceeded : True
$ curl -v --http1.1 https://www.amd.com/
* Established connection to www.amd.com (23.41.36.125 port 443)
> GET / HTTP/1.1
* Request completely sent off
* schannel: remote party requests renegotiation
* schannel: SSL/TLS connection renegotiated       (x2)
* Operation timed out after 30010 milliseconds with 0 bytes received
```

TCP connects, TLS completes, the request is sent, and AMD's Akamai edge
renegotiates twice and then never answers. Consistent with the geo-blocking
already recorded for NIM in `CLAUDE.md`.

Other AMD hosts are **fine**: `ryzenai.docs.amd.com` 200, `repo.radeon.com`
200, `download.amd.com` 404-at-root, `drivers.amd.com` 302. It is specifically
the Akamai-fronted `www`/`account` pair.

**How it was resolved without substituting anything.** Upstream
`ggml-org/whisper.cpp` pins the identical package in its own self-hosted NPU CI:

```
.github/workflows/build-self-hosted.yml:124
FLEXML_URL: https://github.com/lemonade-sdk/whisper.cpp-rocm/releases/download/deps/flexmlrt-1.7.0-win.zip
```

Same version, same filename, mirrored on GitHub releases, and it is what
whisper.cpp's own CI builds the VitisAI path against.

```
$ curl -L --fail -o flexmlrt-1.7.0-win.zip "<that URL>"
HTTP=200 bytes=11300218
sha256: 964423f6cd0ce6d90fb8384f3f3261688fc3866a0651511d81e5538f53710f1f
```

This is a **mirror of the specified component, not a different component**. The
CMake package it provides is the one the fork asks for by name
(`find_package(FlexmlRT REQUIRED)`, `src/CMakeLists.txt:52`) and the DLL is the
one it links (`flexmlrt::flexmlrt`, `src/CMakeLists.txt:128`).

**Ali should know this anyway**: AMD driver and Ryzen AI SDK downloads are not
reachable from here. Anything future that needs `account.amd.com` needs a VPN
or a hand-carried file.

### `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` is required with CMake 4

`winget` installs CMake **4.4.3**, which hard-errors on
`cmake_minimum_required(VERSION 3.5)` — what the fork's root `CMakeLists.txt:1`
declares. The policy override is the one-flag fix. Upstream CI sidesteps it by
installing CMake 3.28.1.

### CMake picked the wrong generator on the first attempt

`cmake -B build -A x64` inside a `vcvars64` shell chose `NMake Makefiles` and
then failed, because that generator rejects `-A`:

```
CMake Error at CMakeLists.txt:2 (project):
  Generator NMake Makefiles does not support platform specification, but platform x64 was specified.
CMake Error: CMAKE_C_COMPILER not set, after EnableLanguage
```

Fixed by naming the generator: `-G "Visual Studio 17 2022"`. Root cause was VS
detection: `vcvars64.bat` was printing `'vswhere.exe' is not recognized` because
the Build Tools install had not finished registering. Not retried blindly — the
failed dir was left and a fresh `build-vitisai/` used instead.

### Nothing else failed

No thermal event. `Get-CimInstance Win32_Battery -> BatteryStatus 2` (AC) for
the whole lane. The 108 C incident did not recur.

---

## Cross-lane findings (files this lane may not edit)

### 1. `voice/benchmark_stt.py` prints the wrong thing in the transcript column

Not a guess — this is the benchmark run against this lane's real build:

```
$ JARVIS_WHISPER_CPP_BIN=... JARVIS_WHISPER_MODEL=... \
  .venv/Scripts/python.exe -m voice.benchmark_stt --clip voice/whisper/src/samples/jfk.wav

backend              latency  xRT   transcript / why not
-------------------  -------  ----  ------------------------------------------------
whisper.cpp (local)  26.99s   2.45  whisper_vitisai_encode: Vitis AI model inferenc…
```

The good news is the whole cross-lane path works: their backend found the
binary, loaded large-v3, ran on the NPU and timed it, with **no change to
either file**. The bug is only the transcript.

**Cause.** The fork logs to **stdout**, not stderr:

```
src/vitisai/whisper-vitisai-encoder.cpp:197
std::fprintf(stdout, "%s: Vitis AI model inference completed.\n", __func__);
```

Confirmed by isolating the stream:

```
$ whisper-cli.exe -m ... -f samples/jfk.wav -l auto -nt 2>/dev/null | cat -A
whisper_vitisai_encode: Vitis AI model inference completed.^M$
whisper_vitisai_encode: Vitis AI model inference completed.^M$
^M$
 And so my fellow Americans, ask not what your country can do for you, ...
```

`WhisperCppBackend.transcribe()` returns `completed.stdout.strip()`, so those
lines become part of "the transcript". Every other whisper.cpp log goes to
stderr; this one line is the exception, and it is unique to the NPU build — so
it only appears once this lane lands, which is why the other lane could not
have seen it.

**Fix, in their file, one line.** Either:

```python
from voice.whisper.local_backend import clean_transcript
return clean_transcript(completed.stdout)
```

or have `default_backends()` return `LocalWhisperBackend()`, which already does
it. I did not edit `voice/benchmark_stt.py`.

### 2. `whisper_cpp_command()`'s flags are correct — verified, no change needed

The other lane asked this lane to confirm its flags against the CLI actually
built. All four are accepted:

```
$ whisper-cli.exe --help
  -m FNAME,  --model FNAME     [models/ggml-base.en.bin] model path
  -f FNAME,  --file FNAME      [       ] input audio file path
  -l LANG,   --language LANG   [en     ] spoken language ('auto' for auto-detect)
  -nt,       --no-timestamps   [false  ] do not print timestamps
```

`tests/voice/test_local_backend.py::test_the_pure_command_builder_matches_the_benchmark_lanes_builder`
asserts the two lanes' argv builders stay byte-identical, so a future
divergence fails a test instead of silently mis-invoking the binary.

### 3. A test of mine failed in a full run; fixed

CORE reported that
`test_importing_the_package_pulls_in_no_audio_stack_and_runs_nothing` passed
alone and failed in the full suite. Correct diagnosis, my bug: it asserted
`"soundfile" not in sys.modules`, a process-global condition that any earlier
test importing soundfile trips — and `tests/voice/test_speak.py` legitimately
must. Fixed by evicting the audio modules alongside our own before the import
under test, so the only thing that can put them back is the import being
tested. CORE's exact repro now passes:

```
$ .venv/Scripts/python.exe -m pytest -q ... tests/voice/test_benchmark_stt.py \
    "tests/voice/test_local_backend.py::test_importing_the_package_pulls_in_no_audio_stack_and_runs_nothing"
30 passed in 0.43s          (was: 1 failed, 29 passed)
```

### 4. No shared interface was changed

This lane introduces no `Protocol` and widens none. `LocalWhisperBackend`
*implements* the existing `voice.benchmark_stt.SttBackend` structurally; it does
not modify it, so no existing implementer or test double is stranded.
`voice/config.py`, `voice/benchmark_stt.py`, `voice/record_wakeword.py`,
`requirements.txt`, `router/routing.py` and every hot file in `docs/plan.md`
were read but never written.

---

## The backend interface

`voice/whisper/local_backend.py`. The brief asked for a callable returning
`(transcript, latency_seconds)` and an availability check that returns False
cleanly. Both, plus structural compatibility with the sibling benchmark.

```python
from voice.whisper.local_backend import LocalWhisperBackend

backend = LocalWhisperBackend()

# the brief's shape: callable, returns a plain 2-tuple
transcript, latency_seconds = backend(Path("clip.wav"))

# never raises; False when the build/weights/.rai are missing
state = backend.availability()       # -> Availability(available: bool, reason: str)
if not state:                        # Availability.__bool__ is `available`
    print(state.reason)              # names the env var or build step that fixes it
backend.is_available()               # -> bool

# voice.benchmark_stt.SttBackend, satisfied structurally
backend.name                         # "whisper.cpp (local, NPU)"
backend.transcribe(clip)             # -> str
backend.transcribe_timed(clip)       # -> Transcription(text, latency_seconds), a NamedTuple

# introspection, for reports and error messages
backend.binary, backend.model, backend.encoder_cache, backend.language
backend.command(clip)                # the exact argv
```

Module-level: `default_backend()`, `is_available()`, `transcribe(clip)`,
`encoder_cache_path(model)`, `clean_transcript(raw)`, `whisper_cli_command(...)`,
`subprocess_env(...)`, and `main(argv)` for
`python -m voice.whisper.local_backend --check | --clip X`.

`Availability` is field-identical to `voice.benchmark_stt.Availability`, so the
benchmark renders a row from one without a shim.

**Path resolution is explicit arg -> `JARVIS_WHISPER_*` env var -> this lane's
build output.** The env vars come second rather than first so the thing works
out of the box after a build, while an override still wins.
`voice/config.py` deliberately holds no default path guess; this is where that
default lives instead, which is what makes `JARVIS_WHISPER_CPP_BIN` meaningful
without either lane guessing at the other's paths.

**`availability()` also checks the `.rai` file**, which the sibling's generic
backend cannot know to do. Without it the failure surfaces as a subprocess
crash mid-benchmark rather than a clean "not available" row.

`voice/whisper/__init__.py` re-exports **nothing**, deliberately: importing the
submodule there makes `python -m voice.whisper.local_backend` emit a
`RuntimeWarning` on every run. Import from `voice.whisper.local_backend`.

---

## `.gitignore` — action required by CORE

`.gitignore` is not in this lane's ownership list, so it was **not edited**.
These are the lines it needs:

```gitignore
# whisper.cpp NPU build (docs/tasks/whisper-npu-build.md). ~3.9 GB of clone,
# CMake output, FlexML runtime and Whisper large-v3 weights. Never committed.
voice/whisper/src/
voice/whisper/flexmlrt/
voice/whisper/models/
voice/whisper/*.zip
```

**Reported, not silent:** leaving ~3.9 GB untracked inside the repo breaks
`git status`, the pre-commit hook and `tools/context_status.py` for every other
lane, so as a local-only stopgap the same four lines were appended to
**`.git/info/exclude`** with a comment saying to move them. That file is
untracked local git config, not a repo file, and no lane owns it. Verified:

```
$ git check-ignore -v voice/whisper/models/ggml-large-v3.bin
.git/info/exclude:26:voice/whisper/models/   voice/whisper/models/ggml-large-v3.bin
```

**Please move them into `.gitignore` and delete the block from
`.git/info/exclude`.** As it stands the ignore rules exist only on this machine.

Sizes, for the record:

```
src        113 MB   (clone + build-vitisai 49 MB + build-cpu 34 MB)
flexmlrt    89 MB
models    3659 MB
```

Disk after: 468 GB free of 953 GB.

---

## Dependencies

**No Python packages.** `voice/whisper/local_backend.py` imports only the
standard library plus `voice.config`. `requirements.txt` was not touched.
`docs/tasks/deps-whisper-npu.txt` records that, plus the two machine-level
tools this lane installed, which `requirements.txt` cannot express:

- `Kitware.CMake` 4.4.3
- `Microsoft.VisualStudio.2022.BuildTools`, workload `VCTools`
  (MSVC 14.44.35207, Windows SDK 10.0.26100.0)

Neither existed on this machine before. There was no C++ compiler at all.

## Environment, verified rather than assumed

The brief said to confirm what the driver actually exposes. It does:

```
$ Get-PnpDevice ... -match 'NPU'
FriendlyName : NPU Compute Accelerator Device
Status       : OK
InstanceId   : PCI\VEN_1022&DEV_17F0&SUBSYS_8DA7103C&REV_20\...

DEVPKEY_Device_DriverVersion  : 32.0.20102.3930
DEVPKEY_Device_DriverProvider : AMD
DEVPKEY_Device_DriverDate     : 5/7/2026
```

`VEN_1022&DEV_17F0` is the XDNA NPU on this part. The README asks for "NPU
drivers version **.280 or newer**" (its link is `NPU_RAI1.5_280_WHQL.zip`). The
installed driver uses a different numbering scheme so the strings are not
directly comparable — but it is dated 7 May 2026 and, decisively, **XRT
initialised and ran inference**, which is the only test that matters. Nothing
was inferred from a version string.

Requirement sources, read rather than assumed:

- `https://github.com/amd/whisper.cpp` README §"AMD Ryzen™ AI support for NPU"
  — driver `.280+`, `flexmlrt1.7.0-win.zip`, `cmake -B build -DWHISPER_VITISAI=1`,
  `.rai` naming, and "**Ryzen™ AI NPU acceleration is currently supported on
  Windows only**".
- `https://ryzenai.docs.amd.com/en/1.7/whisper_cpp.html` — defers entirely to
  that README; it carries no build detail of its own.
- `ggml-org/whisper.cpp .github/workflows/build-self-hosted.yml` — the working
  end-to-end Windows NPU recipe, including the FlexML mirror URL.

---

## Specified but not done

- **`.gitignore`.** Above. Not in this lane's ownership.
- **A real Urdu/English clip.** Blueprint 3.1's benchmark clip is Ali's voice;
  `samples/jfk.wav` (11.0 s, real speech) was used to prove the runtime.
  `-l auto` detected `en` at p=0.936, so the autodetect path is exercised.
- **`whisper-server` measurement.** `whisper-server.exe` was built and would
  remove the 4-8 s per-utterance model reload, but wiring it is blueprint 3.3's
  Pipecat loop, not this lane.
- **The Groq fallback.** Not built and not decided. The evidence is in "What
  Ali has to judge"; the decision is his.
- **`.env.example` lines.** None needed — this lane adds no new variable. It
  gives `JARVIS_WHISPER_CPP_BIN` and `JARVIS_WHISPER_MODEL`, already listed by
  the sibling lane, their first real values:

  ```
  JARVIS_WHISPER_CPP_BIN=voice/whisper/src/build-vitisai/bin/Release/whisper-cli.exe
  JARVIS_WHISPER_MODEL=voice/whisper/models/ggml-large-v3.bin
  ```

  Both are optional — the backend defaults to exactly these paths.
- **`build-cpu/`.** Kept, not deleted: it is the evidence for the 12.4x figure
  and re-measuring costs another five-minute build. It is ignored along with
  the rest of `voice/whisper/src/`.

---

## Full-suite verification

`test-workspace` claimed, run, released immediately after.

```
$ .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
........................................................................ [ 73%]
........................................................................ [ 82%]
........................................................................ [ 91%]
..................................................................       [100%]
786 passed, 7 deselected, 2 warnings in 55.79s
```

Green tree, not just a green lane — the 786 includes this lane's 46 tests and
the other lanes' uncommitted work that was in the tree at the time. The two
warnings are the pre-existing Supabase deprecation warnings in
`tests/test_integration.py`.

`pytest -m live tests/live` was not run: this lane adds no live probe, and the
acceptance criterion it would cover is Ali judging the latency.

---

## Files this lane wrote

```
voice/whisper/__init__.py
voice/whisper/local_backend.py
tests/voice/test_local_backend.py
docs/tasks/deps-whisper-npu.txt
docs/tasks/whisper-npu-build-report.md
.git/info/exclude                       (local-only stopgap, see .gitignore above)
```

Untracked artifacts produced, none committed:

```
voice/whisper/src/                                       amd/whisper.cpp @ b40e6c8
voice/whisper/src/build-vitisai/bin/Release/whisper-cli.exe   the NPU binary
voice/whisper/src/build-cpu/bin/Release/whisper-cli.exe       CPU baseline, for the 12.4x figure
voice/whisper/flexmlrt/                                  FlexML runtime 1.7.0
voice/whisper/flexmlrt-1.7.0-win.zip                     sha256 964423f6…10f1f
voice/whisper/models/ggml-large-v3.bin                   3,095,033,483 bytes
voice/whisper/models/ggml-large-v3-encoder-vitisai.rai     741,558,840 bytes
```
