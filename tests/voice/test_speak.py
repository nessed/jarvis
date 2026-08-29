"""Tests for text -> WhatsApp voice note.

Kokoro is stubbed: synthesis is a 300 MB model and a real render belongs in a
live probe, not the offline suite. The encoding half is exercised for real,
because the OGG/Opus subtype is the load-bearing detail -- WhatsApp plays Opus
inline and treats anything else as a file attachment.
"""

import io
import sys

import pytest

# numpy and soundfile are imported INSIDE each test, never at module scope.
# tests/voice/test_local_backend.py asserts `"soundfile" not in sys.modules`
# after a fresh import of voice.whisper, and a module-level import here leaks
# into that assertion and fails it in a full-suite run while passing alone.
from voice.speak import (
    MAX_VOICE_NOTE_BYTES,
    VOICE_NOTE_MIME_TYPE,
    SpeechError,
    encode_voice_note,
    synthesize,
    text_to_voice_note,
)
from voice.config import TTS_SAMPLE_RATE


def a_tone(seconds: float = 1.0):
    import numpy as np

    t = np.arange(int(TTS_SAMPLE_RATE * seconds)) / TTS_SAMPLE_RATE
    return (0.25 * np.sin(2 * np.pi * 440 * t)).astype("float32")


def test_encoded_voice_note_is_ogg_opus_which_is_what_whatsapp_plays_inline():
    import soundfile as sf

    encoded = encode_voice_note(a_tone())

    info = sf.info(io.BytesIO(encoded))
    assert info.format == "OGG"
    assert info.subtype == "OPUS"
    assert info.channels == 1


def test_encoded_voice_note_round_trips_to_audio_of_the_same_duration():
    import soundfile as sf

    encoded = encode_voice_note(a_tone(seconds=2.0))

    info = sf.info(io.BytesIO(encoded))
    assert info.duration == pytest.approx(2.0, abs=0.1)


def test_mime_type_matches_what_the_whatsapp_client_uploads():
    from bus.whatsapp_client import VOICE_NOTE_MIME_TYPE as client_mime

    assert VOICE_NOTE_MIME_TYPE == client_mime


def test_synthesize_refuses_empty_text_without_loading_the_model():
    with pytest.raises(SpeechError):
        synthesize("   ")


def test_oversized_audio_is_refused_with_whatsapps_limit_named(monkeypatch):
    import soundfile as sf

    def fake_write(buffer, *_args, **_kwargs):
        buffer.write(b"x" * (MAX_VOICE_NOTE_BYTES + 1))

    monkeypatch.setattr(sf, "write", fake_write)
    with pytest.raises(SpeechError) as excinfo:
        encode_voice_note(a_tone())
    assert "16 mb" in str(excinfo.value).lower()


def test_empty_encoder_output_is_an_error_not_a_zero_byte_voice_note(monkeypatch):
    import soundfile as sf

    monkeypatch.setattr(sf, "write", lambda buffer, *a, **k: None)
    with pytest.raises(SpeechError):
        encode_voice_note(a_tone())


def test_text_to_voice_note_uses_the_configured_voice_and_encodes_the_result(monkeypatch):
    """End to end with Kokoro stubbed, so the wiring is covered without the model."""
    import soundfile as sf

    used = {}

    class FakePipeline:
        def __init__(self, lang_code):
            used["lang"] = lang_code

        def __call__(self, text, voice):
            used["text"] = text
            used["voice"] = voice
            return [(None, None, a_tone(seconds=0.5))]

    monkeypatch.setitem(sys.modules, "kokoro", type("m", (), {"KPipeline": FakePipeline}))

    encoded = text_to_voice_note("hello there", voice="am_puck")

    assert used["voice"] == "am_puck"
    assert used["text"] == "hello there"
    assert sf.info(io.BytesIO(encoded)).subtype == "OPUS"


def test_no_audio_from_the_model_is_reported_rather_than_encoded_as_silence(monkeypatch):
    class EmptyPipeline:
        def __init__(self, lang_code):
            pass

        def __call__(self, text, voice):
            return []

    monkeypatch.setitem(sys.modules, "kokoro", type("m", (), {"KPipeline": EmptyPipeline}))

    with pytest.raises(SpeechError):
        synthesize("anything")
