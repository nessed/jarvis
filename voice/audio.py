"""Decode inbound audio to the 16 kHz mono PCM WAV whisper-cli requires.

whisper.cpp's own WAV reader is not general purpose: it requires 16 kHz PCM
and refuses anything else outright, matching ``WHISPER_SAMPLE_RATE``
(``voice/config.py``'s wake-word section documents the same constant for
openWakeWord). What WhatsApp actually hands the webhook is OGG/Opus, so an
inbound voice note has to go through this conversion before it can reach
whisper-server. This is the opposite direction from ``voice/speak.py``
(text -> Opus, outbound), which is why it is a separate module rather than an
addition to that one.

numpy and soundfile are imported inside the function, not at module scope, for
the same reason ``voice/speak.py`` does it: importing this module must not
drag an audio library into a process that never touches one.
"""

from __future__ import annotations

import io

#: What whisper-cli/whisper-server require, per voice/config.py's WAKEWORD_*
#: constants and the local-backend docstring's own reasoning.
TARGET_SAMPLE_RATE = 16000


class AudioDecodeError(RuntimeError):
    """Raised when inbound audio cannot be decoded to a transcribable WAV."""


def _resample_linear(samples: "object", source_rate: int, target_rate: int) -> "object":
    """Resample ``samples`` with linear interpolation.

    Not a proper polyphase filter -- there is no other resampling dependency
    in this repo (no scipy, no librosa), and WhatsApp voice notes are already
    16 kHz Opus in the common case, so this path exists for correctness on
    the rare clip that isn't, not for audio quality. Whisper's own tokeniser
    is robust to the kind of soft aliasing linear interpolation introduces;
    ffmpeg-grade resampling is not worth a new dependency for a fallback.
    """
    import numpy as np

    if source_rate == target_rate:
        return samples
    duration = samples.shape[0] / source_rate
    target_length = max(1, int(round(duration * target_rate)))
    source_index = np.arange(samples.shape[0])
    target_index = np.linspace(0, samples.shape[0] - 1, num=target_length)
    return np.interp(target_index, source_index, samples).astype(samples.dtype)


def to_transcribable_wav(audio: bytes, *, target_sample_rate: int = TARGET_SAMPLE_RATE) -> bytes:
    """Decode ``audio`` to mono 16-bit PCM WAV bytes at ``target_sample_rate``.

    ``audio`` can be anything libsndfile reads -- OGG/Opus in practice, since
    that is the only format Meta ever sends a voice note in. Stereo is
    averaged down to mono; whisper.cpp only ever consumes one channel.
    """
    if not audio:
        raise AudioDecodeError("No audio content to decode.")

    import soundfile as sf

    try:
        samples, source_rate = sf.read(io.BytesIO(audio), dtype="float32", always_2d=False)
    except Exception as exc:  # libsndfile raises its own error types per-backend
        raise AudioDecodeError(f"Could not decode audio: {exc}") from exc

    if samples.ndim > 1:
        samples = samples.mean(axis=1)

    samples = _resample_linear(samples, source_rate, target_sample_rate)

    buffer = io.BytesIO()
    sf.write(buffer, samples, target_sample_rate, format="WAV", subtype="PCM_16")
    encoded = buffer.getvalue()
    if not encoded:
        raise AudioDecodeError("WAV encoding produced no bytes.")
    return encoded
