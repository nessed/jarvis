"""Voice runtime for blueprint Phase 3.

Two CLI-shaped tools live here, both of them things Ali runs with his own ears
and his own microphone:

* ``voice.record_wakeword`` — blueprint 3.2's clip recorder. Prompts, records,
  saves 30-50 "Hey JARVIS" clips at varying distance and tone, in the format
  openWakeWord's training path expects.
* ``voice.benchmark_stt`` — blueprint 3.1's latency benchmark. Times each
  available STT backend over a ~10s Urdu/English clip so the NPU-vs-Groq call
  has a real number behind it.

Neither module imports an audio library at import time. ``sounddevice`` and
``soundfile`` are pulled in lazily, inside the functions that actually touch a
device or a file, so importing this package - which the offline test suite
does - never opens the microphone and never requires audio hardware to exist.

Not here, deliberately:

* The whisper.cpp build and the large-v3 download. Separate lane
  (``whisper-npu-build``); this package only *consumes* the resulting binary
  via ``JARVIS_WHISPER_CPP_BIN`` and reports it missing without crashing.
* The Pipecat wake -> VAD -> STT -> bus -> TTS loop. Blueprint 3.3, gated
  behind this lane and the whisper lane both landing.
* Any Groq Whisper client. ``docs/plan.md`` records ``stt-backends`` as an open
  Class C decision - whether voice owns its own audio client or
  ``router/routing.py`` grows an audio lane is not this package's call.
"""

from __future__ import annotations

__all__ = ["config"]
