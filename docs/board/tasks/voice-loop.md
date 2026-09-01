---
id: voice-loop
status: ready
lane: AUTO
priority: 1
phase: 3
blocked-on: none
files: voice/loop.py, voice/vad.py, tests/voice/test_loop.py, tests/voice/test_vad.py, docs/tasks/voice-loop-report.md
resources: microphone-speakers (live smoke only), ollama-embed (via the normal reply path)
---

# voice-loop — the local desk assistant loop

## Goal

Blueprint 3.3's desk-loop clause — its WhatsApp clause is done and
live-verified — and the only unbuilt piece of Phase 3: a local
interactive loop — wake word → VAD → STT → recall/route → Kokoro TTS out
loud — with barge-in. The WhatsApp voice path is done and live-verified;
this is the same pipeline pointed at the mic and speakers instead of Meta.

## Constraints (decided, not yours to revisit)

- Wake word: pretrained `hey_jarvis_v0.1` via openwakeword (proved 7/7).
- STT: warm `whisper-server` via `voice/whisper/server_client.py`,
  language `ur` (`voice/config.py`), NPU build, degrade gracefully if the
  server is absent.
- TTS: Kokoro `am_puck` via `voice/speak.py`'s synthesis path (24 kHz).
- Replies in English (no Urdu Kokoro voice) — reuse the English-only
  system-prompt shape from the WhatsApp voice path.
- VAD: Silero (installed with the voice deps; see
  `docs/tasks/voice-deps-and-tooling-report.md`).
- Pipecat is installed and was the blueprint's named assembly framework.
  If on inspection Pipecat's abstractions fight this stack (e.g. its
  transport model doesn't fit whisper-server), that is a **stop-and-report,
  not a substitution** — write the finding in the report and mark this
  task blocked. Do not silently hand-roll a replacement loop.

## Steps

1. Read `voice/__init__.py`, `voice/speak.py`, `voice/audio.py`,
   `voice/whisper/server_client.py`, `voice/listen_wakeword.py`, and
   `executor/handlers/whatsapp.py`'s voice reply path — the seams you need
   all exist there already.
2. Design the loop as a state machine on the **conversational subset** of
   blueprint §5's seven states (`IDLE → LISTENING → TRANSCRIBING →
   THINKING → PLANNING → EXECUTING → SPEAKING → IDLE`): PLANNING and
   EXECUTING only become reachable when `voice-command-ingress` plugs into
   the seam from step 5, but the state enum carries all seven from day one
   so that task doesn't rework it. Every external dependency (mic stream,
   wake model, VAD, STT client, router call, TTS synth, audio out) is
   injected — the offline suite runs
   entirely on fakes, like `tests/voice/test_local_backend.py` does.
3. Barge-in: speech detected while SPEAKING stops playback and re-enters
   LISTENING. This is the blueprint's "matters more than any visual
   polish" requirement — it is not optional.
4. Route transcripts through the same recall/route pipeline the WhatsApp
   handler uses (share the code, don't fork it). Memory writes follow the
   same rules as WhatsApp turns.
5. For the queue hand-off ("Jarvis, sort my inbox" → job): **do not build
   it yet** — that is `voice-command-ingress`, gated on Q7. This loop only
   answers conversationally for now; leave an injected seam where the
   command path will plug in.
6. CLI entry: `python -m voice.loop` with `--once` (one wake-utterance-
   reply cycle, for testing) and text-mode flags for smoke-testing without
   a mic (`--text "hello"` → spoken reply).
7. Encoding discipline: every subprocess/stdout boundary gets explicit
   `encoding="utf-8", errors="replace"` — this machine is cp1252 and it
   has burned us twice; the pins in `tests/voice/test_local_backend.py`
   show the required shape.
8. Tests offline, against fakes, alongside the code. Mic/speaker live runs
   are Ali's (U6) — claim `microphone-speakers` if you self-smoke with
   `--text`.

## Verification

- `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp tests/voice/` green, then the full suite.
- `python -m voice.loop --text "what's my name"` produces an audible reply
  end-to-end on the real stack (speakers; claim the resource).

## Done when

Offline suite green with the loop covered; text-mode smoke works; report
written to `docs/tasks/voice-loop-report.md` naming what U6 (Ali's ear
test) should judge. Update `docs/state.md`'s Phase 3 row.

## Log

_(empty)_
