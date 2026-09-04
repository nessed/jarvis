"""Turn text into a WhatsApp-ready voice note.

Blueprint 3.3's outbound half: "Kokoro reply encoded to ogg/opus for WhatsApp".
This module is only the synthesis and encoding step -- uploading and sending is
``bus/whatsapp_client.py``'s job, so this stays importable without any Meta
credentials and testable without any network.

Two format facts, both read off the installed packages rather than assumed:

- **Kokoro-82M synthesises at 24 kHz.** That is the model's output rate, not a
  setting (``voice/config.py``: ``TTS_SAMPLE_RATE``).
- **Opus is written by libsndfile, not ffmpeg.** ffmpeg is not installed on this
  machine and is not required: the pinned ``soundfile==0.14.0`` bundles
  libsndfile 1.2.2, whose ``OGG`` format lists an ``OPUS`` subtype. Verified by
  ``sf.available_subtypes("OGG")`` -> ``['VORBIS', 'OPUS']`` and by encoding
  real audio. This is why no new dependency was added for this feature.

WhatsApp requires voice notes as OGG/Opus specifically -- an OGG/Vorbis file is
accepted as a generic audio *document* but does not render as a playable voice
note with a waveform. The subtype is load-bearing, not a preference.

    .venv\\Scripts\\python.exe voice/speak.py "text to say" --out reply.ogg
"""

from __future__ import annotations

import argparse
import io
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice.config import DEFAULT_TTS_LANG, TTS_SAMPLE_RATE, tts_voice

# WhatsApp's documented ceiling for an audio message is 16 MB. Opus at speech
# bitrates is roughly 6 KB/s, so this is minutes of speech -- but a runaway
# caller passing a whole document should fail here with a clear message rather
# than at Meta's edge with an opaque one.
MAX_VOICE_NOTE_BYTES = 16 * 1024 * 1024

VOICE_NOTE_MIME_TYPE = "audio/ogg"


class SpeechError(RuntimeError):
    """Raised when text cannot be turned into a voice note."""


#: The one Kokoro pipeline this process uses, built on first synthesis.
#:
#: Until 4 Sep 2026 ``synthesize`` built a fresh ``KPipeline`` on every call.
#: Measured on this laptop that day: ``import kokoro`` 18.5s (torch), the
#: pipeline build 5.3s, and the actual render 2.7-3.1s for 7.6s of speech.
#: So every voice reply paid ~5s of model construction on top of the render,
#: and the first one after a worker restart paid ~24s more. Kept per process,
#: behind a lock, keyed on the ``KPipeline`` class it was built from so a test
#: that injects a fake ``kokoro`` module never receives another test's fake.
_PIPELINE_LOCK = threading.Lock()
_pipeline: tuple[object, object] | None = None  # (KPipeline class, instance)


def _pipeline_for(lang_code: str) -> "object":
    from kokoro import KPipeline

    global _pipeline
    cached = _pipeline
    if cached is not None and cached[0] is KPipeline:
        return cached[1]
    with _PIPELINE_LOCK:
        cached = _pipeline
        if cached is not None and cached[0] is KPipeline:
            return cached[1]
        instance = KPipeline(lang_code=lang_code)
        _pipeline = (KPipeline, instance)
        return instance


def reset_pipeline_cache() -> None:
    """Drop the cached pipeline. A test seam; production never needs it."""
    global _pipeline
    with _PIPELINE_LOCK:
        _pipeline = None


def warm_up() -> None:
    """Load Kokoro now so the first voice reply does not pay for it.

    Safe to call from a worker at startup; a failure here is logged by the
    caller and the next ``synthesize`` simply tries again.
    """
    _pipeline_for(DEFAULT_TTS_LANG)


def synthesize(text: str, *, voice: str | None = None) -> "object":
    """Render ``text`` to a mono float32 waveform at ``TTS_SAMPLE_RATE``.

    Returns a numpy array. Kept separate from encoding so a caller that wants to
    play audio locally does not pay for an Opus round trip.
    """
    spoken = text.strip()
    if not spoken:
        raise SpeechError("Nothing to say: the text is empty.")

    import numpy as np

    chosen = voice or tts_voice()
    pipeline = _pipeline_for(DEFAULT_TTS_LANG)

    # Kokoro yields one chunk per segment; join them so a multi-sentence reply
    # is one continuous take rather than several files.
    chunks = [audio for _, _, audio in pipeline(spoken, voice=chosen)]
    if not chunks:
        raise SpeechError(f"Kokoro produced no audio for voice {chosen!r}.")
    return np.concatenate(chunks)


def encode_voice_note(samples: "object") -> bytes:
    """Encode a waveform as OGG/Opus bytes, the format WhatsApp plays inline."""
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, samples, TTS_SAMPLE_RATE, format="OGG", subtype="OPUS")
    encoded = buffer.getvalue()

    if not encoded:
        raise SpeechError("Opus encoding produced no bytes.")
    if len(encoded) > MAX_VOICE_NOTE_BYTES:
        raise SpeechError(
            f"Voice note is {len(encoded) // 1024} KB, over WhatsApp's 16 MB limit. "
            "Shorten the reply or split it."
        )
    return encoded


def text_to_voice_note(text: str, *, voice: str | None = None) -> bytes:
    """Text in, WhatsApp-ready OGG/Opus bytes out."""
    return encode_voice_note(synthesize(text, voice=voice))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render text to a WhatsApp voice note.")
    parser.add_argument("text", help="what to say")
    parser.add_argument("--voice", default=None, help=f"Kokoro voice id (default: {tts_voice()})")
    parser.add_argument("--out", default="voice-note.ogg", help="output .ogg path")
    args = parser.parse_args(argv)

    try:
        audio = text_to_voice_note(args.text, voice=args.voice)
    except SpeechError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.write_bytes(audio)
    print(f"{len(audio) / 1024:0.1f} KB  {VOICE_NOTE_MIME_TYPE}  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
