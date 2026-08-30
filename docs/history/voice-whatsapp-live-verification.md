# Voice-to-WhatsApp: first live pass, two bugs found and fixed

30 August 2026. The offline-tested voice wiring (voice note in ->
download -> decode -> transcribe -> route -> synthesize -> voice note out)
was run against real WhatsApp traffic for the first time. Two real bugs
surfaced; both were fixed and reverified with a second live voice note the
same session.

## Bug 1: whisper-server spawned as the wrong binary

`tools/start_jarvis.py` resolved `LocalWhisperBackend().binary` for the
`whisper-server` process. That property is deliberately the CLI binary
(`whisper-cli.exe`) — `voice/whisper/local_backend.py` exists specifically to
wrap the CLI, not the server. `whisper-cli.exe` has no `--host`/`--port`
flags and exits immediately when given them:

```
error: unknown argument: --host
```

Fix: derive the server binary as a sibling of the resolved CLI binary
(`backend.binary.parent / "whisper-server.exe"`) — both come out of the same
`build-vitisai` build and land in the same `bin/Release/` directory, confirmed
directly from that build's own output, not assumed. An existence check on the
derived path was added alongside the existing NPU-artifact availability
check, so a missing server binary degrades the same way a missing model does:
a clear skip message, not a crash.

## Bug 2: an optional child's death took the entire stack down

Bug 1's crash exposed a second, more serious bug. `Supervisor.check_alive()`
treated *any* dead child as a reason to shut down every child — bus, tunnel,
and both workers included. This defeated the explicit design intent recorded
in `tools/start_jarvis.py`'s own module docstring: "text keeps working
without [whisper-server]." A voice-only failure was taking down text
messaging too.

Fix: `Supervisor.spawn()` gained an `optional` flag; `whisper-server` is now
spawned with `optional=True`. `check_alive()` skips optional children (after
reporting the death once, so it is not silently invisible) and only returns
the name of a dead *required* child. Verified with unit tests exercising both
branches — a dead required child still stops everything, a dead optional
child does not, and a required death is still reported even when an optional
child died too.

## Bug 3: Kokoro has no Urdu voice, and nothing said so

Not a crash — an audible defect Ali caught by ear. Whisper (STT) is
multilingual and forced to Urdu (`voice/config.py`, see
`voice-urdu-language-detection.md`) specifically so a code-switched
Urdu/English clip transcribes cleanly. Kokoro (TTS) has no Urdu voice at all
— `kokoro/pipeline.py`'s `LANG_CODES` lists American/British English,
Spanish, French, Hindi, Italian, Portuguese, Japanese, Mandarin, and nothing
else — and `voice/config.py` pins `lang_code "a"` (American English)
unconditionally.

Nothing in the reply pipeline told the model to stay in English. On the
first live test the model transcribed `یو ویٹس اپ`, mirrored the input
language, and replied in Roman Urdu: `"Haanji, WhatsApp pe hi hoon. 😄 Kaise
help karun?"`. Kokoro's English G2P read that as English words spelled
strangely — audible as Urdu spoken in an English accent, exactly as
described live. Confirmed directly from `memory.db`'s stored turn for that
exchange, not inferred.

Fix: `executor/handlers/whatsapp.py` appends an explicit English-only
instruction to the system prompt, but only for a voice reply — a text reply
is read, not heard, so a mixed-language reply there is harmless and
unchanged. Reverified live: the same Urdu transcript (`یو`) now gets a plain
English reply (`"Hello"`).

## What this doesn't fix

Kokoro still cannot speak Urdu. The fix keeps every voice reply intelligible
by keeping it in English; it does not give JARVIS an Urdu voice. That would
need a different TTS engine or voice pack — a component decision, not a bug
fix, and not made here.
