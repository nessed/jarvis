---
id: stt-groq-fallback
status: done
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

**2 Sep 2026 — done, live-verified against the real Groq endpoint.**

`voice/stt_fallback.py`, per Q8 = A: voice owns a small Groq STT client and
the provider router is untouched, still chat-completions-only. It reads
`GROQ_API_KEY` itself and names its own base URL, because the router's job is
routing chat completions down a cost ladder and an audio endpoint on the same
host is not that.

### The ordering rule, and the one case that looks like a fallback and is not

Local NPU first, always — it is the only path where a private voice note never
leaves the machine. The fallback fires when the local tier is *unavailable*:
`/health` not answering, or the server accepting the clip and then failing.
Ready-then-broken counts, because nothing was transcribed.

**An empty transcript is a result, not a trigger.** A silent or unintelligible
clip is *correctly* transcribed as nothing, and re-running it in the cloud
would be both the double-transcription this module exists to prevent and audio
sent off the laptop for a message with no words in it. One clip, at most one
backend, every time.

Failure of both raises `SttFallbackError` naming what each tier did. That is
deliberately louder than what it replaces: a dead whisper-server used to read
as a blank transcript, and a spoken message got silence back.

`JARVIS_STT_CLOUD_FALLBACK=0` disables the cloud tier and restores exactly
that old behaviour, without touching code.

### Privacy, said out loud

Audio leaves the laptop **only** on the fallback path. A WhatsApp voice note
has already transited Meta by the time it gets here, so Groq is not a new
class of exposure — but it is a new party, and every transition is logged at
INFO so "did it quietly send my voice to a third party" is answerable from a
log rather than a debugger. Nothing here touches memory, embeddings or
extraction, so `CLAUDE.md`'s loopback-only rule for those is untouched.

### Offline suite

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp
1210 passed, 9 deselected, 10 warnings in 59.23s
```

24 new tests in `tests/voice/test_stt_fallback.py`.

One of them failed the first full-suite run while passing in isolation: it
resolves the *real* cloud backend, and by then something else in the session
has loaded the live `GROQ_API_KEY` from `.env`. Fixed with an explicit
`monkeypatch.delenv`, and the reason is written into the test.

### Live proof

whisper-server was not running, so the local tier was genuinely unavailable —
the fallback condition is real, not stubbed. A clip was synthesised with
Kokoro and encoded as OGG/Opus, exactly the format an inbound WhatsApp voice
note arrives in, then decoded by the same `voice/audio.to_transcribable_wav`
the handler uses, then handed to the real `transcribe_with_fallback` with the
real Groq client.

```
local whisper-server ready: False
cloud tier configured: True model: whisper-large-v3-turbo
synthesised clip: 15158 bytes of OGG/Opus
decoded for STT : 112044 bytes of 16 kHz mono WAV

INFO voice.stt_fallback: local STT backend is not ready
INFO voice.stt_fallback: falling back to cloud STT (local backend not ready)
INFO httpx: HTTP Request: POST https://api.groq.com/openai/v1/audio/transcriptions "HTTP/1.1 200 OK"
INFO voice.stt_fallback: transcribed on the cloud STT fallback

language='en' -> 'Testing the cloud speech fallback for JARVIS.'
```

Word-perfect, through the real endpoint, on the path the handler takes.

### What the same run exposed, and did not fix

The production default is `whisper_language()` = **`ur`** (`voice/config.py`,
chosen because "auto" silently drops the Urdu half of a code-switched clip —
`docs/history/voice-urdu-language-detection.md`). The same clip through the
same call with that default:

```
language='ur' -> 'تستمید ایسای ایسای ایسای ایسای ایسا'
```

Garbage. This is the documented trade behaving exactly as documented —
`config.py` says in as many words that "pure-English clips degrade" under
forced Urdu — and my synthetic clip is pure English, which is *not* how Ali
speaks. So it proves nothing about his real messages, and I have not changed
the default on the strength of a test clip that misrepresents the input.

**It is a sensory check, so it is his.** Filed in `USER-TASKS.md`: send one
real code-switched voice note with whisper-server stopped, and say whether the
Groq transcript is usable. If forced-`ur` degrades the cloud tier the way it
degrades a pure-English clip, the fallback needs its own language setting
rather than inheriting the local backend's — a one-line change, but which way
it goes is a judgement about his own speech, not mine.

Two smaller notes from the same run:

- The Groq SDK logged one automatic retry before the 200. Its own transport
  handles that; nothing here retries on top of it.
- Printing an Urdu transcript to a Windows console raises
  `UnicodeEncodeError` under cp1252. That is a console problem, not a data
  one — the transcript is a `str` all the way into the router and memory, and
  the only thing that broke was my proof script's `print`. Worth knowing
  before someone debugs the wrong layer.
