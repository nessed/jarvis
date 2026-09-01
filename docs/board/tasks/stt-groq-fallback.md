---
id: stt-groq-fallback
status: ready
lane: AUTO
priority: 3
phase: 3
blocked-on: none
files: voice/stt_fallback.py, tests/voice/test_stt_fallback.py, voice/whisper/, executor/handlers/whatsapp.py (hot, wiring only)
resources: provider-account (live proof)
---

# stt-groq-fallback — cloud STT when the NPU path is down

## Gate

**Answered 1 Sep 2026 — Q8 = A.** Voice owns its own small Groq STT
client. The router is not touched and stays chat-completions-only.

Q8 (recommended: voice owns its own Groq STT client, no router change).

## Goal

Blueprint names Groq Whisper (`whisper-large-v3-turbo`, free tier) as the
STT fallback. Today a dead whisper-server degrades voice notes to silence
handled as text-only. Add a fallback tier: local NPU first, Groq when
local is unavailable — never both, and never silently.

## Steps

1. Small Groq audio client in `voice/` (assuming Q8=A): OpenAI-SDK audio
   endpoint, key from env, language `ur` passthrough, explicit UTF-8.
2. A backend-selection seam where `server_client` is used today: local →
   fallback → blank-transcript no-op, each transition logged. Privacy
   note in code and state.md: voice audio leaving the laptop only happens
   on the fallback path — it already transits Meta, so no new exposure
   class, but say it.
3. Tests: fallback fires only when local unavailable; failure of both is
   loud; no double-transcription.
4. Live proof: stop whisper-server, send a voice note, get a reply via
   Groq (claim provider-account), cite logs.

## Done when

Live fallback proof cited; suite green; state.md voice rows updated.

## Log

_(empty)_
