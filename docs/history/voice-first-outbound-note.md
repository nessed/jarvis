# First outbound voice note — 29 August 2026

Frozen record. Append-only; nothing here is edited, including anything later
superseded.

## What happened

JARVIS spoke for the first time. A text line was synthesised to `am_puck` on
this laptop, encoded to OGG/Opus, uploaded to Meta and delivered to Ali's phone
as a playable WhatsApp voice note. He confirmed receipt by ear.

This closes the outbound half of blueprint 3.3 ("Kokoro reply encoded to
ogg/opus for WhatsApp"). The inbound half — voice note in, transcript out —
still waits on `whisper-npu-build`.

## Evidence

Synthesis and send, one process, `.venv` (Python 3.12.10):

```
synthesized 46.5 KB ogg/opus
SENT -> wamid.HBgMOTIzMDAwNDEz...   (truncated; a wamid embeds the recipient number)
```

Format confirmed independently on an earlier render of the same pipeline:

```
.venv\Scripts\python.exe voice/speak.py "..." --out note.ogg
19.7 KB  audio/ogg  -> note.ogg

format=OGG subtype=OPUS rate=24000 ch=1 dur=4.6s
```

Offline suite at the time of the send, excluding one in-flight file owned by
another lane (see "What this did not prove" below):

```
740 passed, 2 skipped, 5 deselected, 4 warnings in 80.02s
```

## What made it work

**No ffmpeg, and no new dependency.** WhatsApp renders a voice note only from
OGG/Opus; anything else arrives as a file attachment. ffmpeg is not installed on
this machine, and the obvious move was to add it. It was not needed: the already
pinned `soundfile==0.14.0` bundles libsndfile 1.2.2, whose `OGG` format exposes
an `OPUS` subtype. Verified before building anything:

```
libsndfile: 1.2.2
OGG subtypes: ['VORBIS', 'OPUS']
```

Kokoro synthesises at 24 kHz and libsndfile encoded Opus at that rate directly.

**Sending audio is two Graph API calls, not one.** The bytes go to
`POST /{phone_number_id}/media`, which returns a media id; the message then
references that id. `send_voice_note` does both and refuses to send a message if
the upload failed, so a message can never reference an id that does not exist.

**`"voice": true` is load-bearing.** Without it in the audio payload the same
media id arrives as an audio *file* rather than a voice note with a waveform and
a play button.

## What this did not prove

- **The send bypassed the executor.** It was a direct client call from a
  one-off script, not a queued job. Nothing about it entered the job queue or
  conversation memory: JARVIS has no record of having said it. Wiring speech
  into `executor/handlers/whatsapp.py` so a reply *can* be spoken is a separate,
  unstarted piece of work.
- **Nothing was committed at the time of the send.** The full offline suite had
  one failure —
  `tests/voice/test_local_backend.py::test_importing_the_package_pulls_in_no_audio_stack_and_runs_nothing`,
  owned by the concurrent `whisper-npu-build` lane. That test asserts a
  process-global condition (`"soundfile" not in sys.modules`) while saving and
  restoring only `voice.whisper*`, so any earlier import of soundfile anywhere in
  the process fails it. It was reproduced against **already-committed** code
  (`tests/voice/test_benchmark_stt.py`, landed in `4f39697`) with none of this
  work involved, and reported to the owning lane rather than edited.
- **Latency was not measured.** Synthesis ran while a from-source C++ build was
  saturating the machine, so any number taken then would have been meaningless.

## Decisions recorded here

- **`am_puck`** is JARVIS's voice, chosen by Ali by ear from Kokoro's 54
  installed packs. Blueprint 3.2 puts that choice with him.
- **The wake word needs no training run.** openwakeword 0.6.0 ships a pretrained
  `hey_jarvis_v0.1` model. Ali's live check the same day: 7 detections from 7
  attempts, scores 0.873–0.993 against a 0.5 threshold, idle floor 0.154. The
  `wakeword-train` job is unnecessary as scoped rather than blocked — its
  recorder, `voice/record_wakeword.py`, is kept for a noisier room that has not
  materialised. A false-positive rate over hours of ordinary talking has still
  never been measured; a 30-second sample cannot show one.
