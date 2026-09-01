# voice-loop — stopped before build: Pipecat does not fit this stack

**Status: blocked, nothing built.** This is the brief's own escape clause
firing, not a lane deciding it knows better. `docs/board/tasks/voice-loop.md`
says, under Constraints:

> Pipecat is installed and was the blueprint's named assembly framework. If on
> inspection Pipecat's abstractions fight this stack (e.g. its transport model
> doesn't fit whisper-server), that is a **stop-and-report, not a
> substitution** — write the finding in the report and mark this task blocked.
> Do not silently hand-roll a replacement loop.

On inspection they do. No `voice/loop.py` or `voice/vad.py` was written.

## What was inspected, and what was found

Everything below is read off the installed packages in `.venv`, not from
upstream documentation — pipecat-ai 1.8.1, and this repo's own voice runtime.

### 1. The transport needs a second PortAudio binding

`pipecat/transports/local/audio.py:24-31` imports `pyaudio` at module scope and
raises if it is absent. `pyaudio` is not installed; it is the `pipecat-ai[local]`
extra:

```
Provides-Extra: local
Requires-Dist: pyaudio~=0.2.14; extra == "local"
```

```
$ .venv/Scripts/python.exe -c "import pipecat.transports.local.audio"
FAIL  pipecat.transports.local.audio | ImportError | Missing module: No module named 'pyaudio'
```

This repo's voice runtime is already built on `sounddevice` 0.5.6 —
`voice/listen_wakeword.py` (`sd.InputStream`), `voice/record_wakeword.py`,
`voice/audio.py`. Adopting Pipecat's local transport means running two
PortAudio bindings in one process, or subclassing `BaseInputTransport` /
`BaseOutputTransport` against `sounddevice` by hand.

### 2. Pipecat's Kokoro is a different engine from the one Ali chose

`pipecat/services/kokoro/tts.py` requires `kokoro-onnx>=0.5,<1`, which is not
installed:

```
$ .venv/Scripts/python.exe -c "import pipecat.services.kokoro.tts"
FAIL  pipecat.services.kokoro.tts | ImportError | Missing module: No module named 'kokoro_onnx'
```

Installed instead is `kokoro==0.9.4`, the PyTorch `KPipeline` package that
`voice/speak.py` uses, and `voice/config.py` records the voice Ali picked by
ear on 29 Aug 2026:

```python
DEFAULT_TTS_VOICE = "am_puck"   # "Changing this changes what JARVIS sounds like,
TTS_SAMPLE_RATE = 24000         #  which is his call and not an agent's."
```

Switching to `kokoro-onnx` is a different engine and a different model
artifact. The brief lists the Kokoro path under "decided, not yours to
revisit."

### 3. Pipecat's wake word is textual; the decided one is acoustic

Pipecat's only wake support is `WakePhraseUserTurnStartStrategy`
(`pipecat/turns/user_start/wake_phrase_user_turn_start_strategy.py`) and
`WakeCheckFilter`. Both regex-match a wake phrase inside a
`TranscriptionFrame` — the docstring is explicit: *"Blocks subsequent
strategies until a wake phrase is detected in a final transcription."*

That inverts the decided design. The wake gate here is acoustic openWakeWord
`hey_jarvis_v0.1` (proved 7/7), and it exists precisely so the 3 GB Whisper
large-v3 NPU model is **not** fed a continuous stream just to hear its own
name. Blueprint §5 makes the same point independently:

> wake-word detection must run **locally** so audio is never streamed anywhere
> just to detect the wake word.

A textual wake gate would require STT always running. A custom openWakeWord
`FrameProcessor` would have to be written to avoid it.

### 4. STT and LLM are both custom subclasses too

- STT is a warm `whisper-server` built from **this repo's fork**
  (`voice/whisper/src/examples/server/server.cpp`), spoken to over HTTP by
  `voice/whisper/server_client.py`, language forced to `ur`. Pipecat's whisper
  service does not talk to it; a custom `SegmentedSTTService` subclass would be
  needed.
- The reply path is this repo's own multi-provider router (`router.route`,
  profile `latency`) plus `memory.conversation` recall/remember, and the brief
  says to **share** `executor/handlers/whatsapp.py`'s pipeline, not fork it.
  Pipecat would need a custom `LLMService` wrapping it.

### What Pipecat would actually contribute

Its frame graph, its Silero VAD analyzer (`pipecat/audio/vad/silero.py`, on
`onnxruntime` 1.24.4, which is installed), and its interruption machinery.
`silero-vad` 6.2.1 is also installed standalone, so the VAD is available either
way.

Net: transport, wake, STT, TTS and LLM — five of six stages — become custom
subclasses, one needing a new PortAudio binding, and two of them overwrite
choices Ali made by ear and by test.

## The second opinion

Consulted per `agents.md`'s Class B rule. Saved at
`docs/consults/2026-09-02-pipecat-fit/`.

**Verdict: (B) stop-and-report. Confidence: high.**

On the barge-in argument specifically — the one thing genuinely hard to
hand-roll — the consult's reasoning was:

> Pipecat's interruption machinery is hard to hand-roll because it cancels
> buffered TTS across a network transport and repairs assistant context after
> truncation. The requirement in step 3 is narrower — VAD fires while SPEAKING,
> stop playback, return to LISTENING — and against a local sounddevice
> OutputStream that is an abort plus a state transition.

What would change it: a prototype showing `sounddevice` playback cannot be
aborted mid-utterance with acceptable latency, or blueprint text naming Pipecat
as a binding architectural decision rather than a named framework.

## What Ali has to decide (Q12)

Filed in `docs/board/QUESTIONS.md` as **Q12** with a recommendation. It is a
blueprint edit — blueprint §2 line 112, §3 line 267, §3.1 line 338 and §3.3
line 342 all name "Pipecat + Silero VAD" — so it is his call, not a lane's.

Recommendation: **drop Pipecat from 3.3's desk-loop clause, keep Silero VAD**,
and let `voice-loop` build the state machine directly on `sounddevice` +
`openwakeword` + `silero-vad` + the existing `server_client` / `speak` /
`router` seams. Pipecat stays installed and stays available if a later phase
wants a networked transport (WebRTC to a phone, say), which is the case its
abstractions are actually built for.

## What U6 (Ali's ear test) will need to judge — once unblocked

Recorded now so it is not re-derived later:

1. Does barge-in feel immediate? Speak over a reply mid-sentence; playback must
   stop, not fade or finish the buffer.
2. Is the wake word usable at desk distance without shouting, and does it stay
   quiet during normal room conversation? (`--threshold` is the dial.)
3. Does the reply come back in English even when the question was Urdu or mixed
   — the failure mode caught live on 30 Aug 2026, where Roman Urdu came out of
   an English G2P sounding like accented nonsense.
4. Is the round trip fast enough to feel conversational, or does the whisper
   NPU pass show as dead air?

## Specified but not done

- `voice/loop.py`, `voice/vad.py`, `tests/voice/test_loop.py`,
  `tests/voice/test_vad.py` — all unwritten, by the constraint above.
- `docs/state.md` Phase 3 row — not touched; nothing shipped to describe.
- No dependency was added and `requirements.txt` was not edited.
