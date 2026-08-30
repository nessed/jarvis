"""Tests for inbound audio -> transcribable WAV.

numpy and soundfile are imported INSIDE each test, never at module scope --
same reason as tests/voice/test_speak.py: a module-level import here would
leak into tests/voice/test_local_backend.py's "no audio library dragged in"
assertion in a full-suite run.
"""

import io

import pytest

from voice.audio import TARGET_SAMPLE_RATE, AudioDecodeError, to_transcribable_wav


def encoded_tone(seconds: float, sample_rate: int, *, channels: int = 1) -> bytes:
    import numpy as np
    import soundfile as sf

    t = np.arange(int(sample_rate * seconds)) / sample_rate
    tone = (0.25 * np.sin(2 * np.pi * 440 * t)).astype("float32")
    if channels == 2:
        tone = np.stack([tone, tone], axis=1)
    buffer = io.BytesIO()
    sf.write(buffer, tone, sample_rate, format="OGG", subtype="OPUS")
    return buffer.getvalue()


def test_decodes_ogg_opus_to_16khz_mono_pcm_wav():
    import soundfile as sf

    audio = encoded_tone(1.0, sample_rate=TARGET_SAMPLE_RATE)

    wav = to_transcribable_wav(audio)

    info = sf.info(io.BytesIO(wav))
    assert info.format == "WAV"
    assert info.subtype == "PCM_16"
    assert info.samplerate == TARGET_SAMPLE_RATE
    assert info.channels == 1
    assert info.duration == pytest.approx(1.0, abs=0.05)


def test_resamples_a_non_16khz_source():
    import soundfile as sf

    audio = encoded_tone(1.0, sample_rate=48000)

    wav = to_transcribable_wav(audio)

    info = sf.info(io.BytesIO(wav))
    assert info.samplerate == TARGET_SAMPLE_RATE
    assert info.duration == pytest.approx(1.0, abs=0.05)


def test_mixes_stereo_down_to_mono():
    import soundfile as sf

    audio = encoded_tone(0.5, sample_rate=TARGET_SAMPLE_RATE, channels=2)

    wav = to_transcribable_wav(audio)

    info = sf.info(io.BytesIO(wav))
    assert info.channels == 1


def test_already_16khz_mono_is_a_near_identity_transform():
    import numpy as np
    import soundfile as sf

    audio = encoded_tone(2.0, sample_rate=TARGET_SAMPLE_RATE)

    wav = to_transcribable_wav(audio)

    samples, rate = sf.read(io.BytesIO(wav))
    assert rate == TARGET_SAMPLE_RATE
    assert len(samples) == pytest.approx(TARGET_SAMPLE_RATE * 2.0, abs=TARGET_SAMPLE_RATE * 0.05)


def test_empty_audio_is_refused_without_touching_soundfile():
    with pytest.raises(AudioDecodeError, match="No audio content"):
        to_transcribable_wav(b"")


def test_undecodable_bytes_raise_a_clear_error():
    with pytest.raises(AudioDecodeError, match="Could not decode audio"):
        to_transcribable_wav(b"not actually audio, just some bytes")
