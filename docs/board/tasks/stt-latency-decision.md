---
id: stt-latency-decision
status: blocked
lane: AUTO
priority: 1
phase: 3
blocked-on: Q15
files: voice/stt_fallback.py, voice/config.py, tests/voice/, tools/start_jarvis.py (only if B)
resources: whisper-npu (if B)
---

# stt-latency-decision — make voice notes stop lagging the laptop

## Gate

Q15. Do not pre-empt it: A sends audio off the laptop, B changes the model
the blueprint names.

## If A (Groq primary)

1. `voice/stt_fallback.py`: add `JARVIS_STT_PREFER_CLOUD` (default off).
   When on, order is cloud first, local second; the "one clip, at most one
   backend" rule and the empty-transcript rule stay exactly as written.
2. Keep every INFO transition log so "did my voice leave the laptop" is
   still answerable from a log.
3. Tests for the new order, both directions of fallback.
4. Live: one real voice note with the flag on; cite the log line naming
   the backend and the wall time.
5. Consider not spawning `whisper-server` at all when the flag is on
   (launcher change) — 3 GB less RAM at startup. Only if Ali says so; the
   local fallback is the privacy path.

## If B (local large-v3-turbo)

1. Download `ggml-large-v3-turbo.bin` next to the current model. Confirm
   the amd fork loads the existing `.rai` encoder for it (same encoder
   weights) — if it does not, this is a rebuild, stop and report the size.
2. `JARVIS_WHISPER_MODEL` points at it; measure the same 7.6 s clip with
   the same probe (`docs/history/infra-audit-2026-09-04.md` has the
   numbers to beat: 11.2-17.6 s, 53-89 % CPU).
3. Blueprint §2 edit naming the model, approved by Ali in the Q15 answer.

## Done when

A voice note's transcription is measured and cited, and the CPU load
during it is below half of what it was.

## Log

_(empty)_
