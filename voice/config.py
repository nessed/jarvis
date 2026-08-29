"""Device, model and path configuration for the voice runtime.

Every value here is either read from the installed package that constrains it
or overridable by a ``JARVIS_*`` environment variable, following the naming
already used by ``executor/heartbeat.py``, ``tools/start_jarvis.py`` and
``bus/webhook_dedup.py``.

Nothing in this module imports an audio library or touches a device.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Audio format
#
# These are not preferences. They are what openWakeWord's own training path
# requires, read out of the installed openwakeword==0.6.0 rather than guessed:
#
#   .venv/Lib/site-packages/openwakeword/data.py:120
#       cmd = f'sox "{input_file}" -G -r 16000 -c 1 -b 16 "{output_file}"'
#   .venv/Lib/site-packages/openwakeword/train.py:816
#       input_shape = F.get_embedding_shape(config["total_length"]//16000)
#       # training data is always 16 khz
#   .venv/Lib/site-packages/openwakeword/utils.py:41
#       sr: int = 16000
#
# 16 kHz, one channel, signed 16-bit PCM. A clip recorded at any other rate has
# to be resampled before training and is a silent quality loss, so the recorder
# writes the target format directly.
# ---------------------------------------------------------------------------
WAKEWORD_SAMPLE_RATE = 16000
WAKEWORD_CHANNELS = 1
WAKEWORD_DTYPE = "int16"
WAKEWORD_SUBTYPE = "PCM_16"

# openwakeword/train.py:747-751 derives its training window from the median
# positive-clip duration and then clamps it:
#
#   config["total_length"] = int(round(median/1000)*1000) + 12000
#   if config["total_length"] < 32000:
#       config["total_length"] = 32000  # set a minimum of 32000 samples
#
# 32000 samples at 16 kHz is 2.0 seconds, and that is the floor the trainer
# pads every clip up to. Recording a 2.0s window means no clip is ever padded
# from something shorter and none is truncated.
WAKEWORD_MIN_TRAINING_SAMPLES = 32000
DEFAULT_CLIP_SECONDS = WAKEWORD_MIN_TRAINING_SAMPLES / WAKEWORD_SAMPLE_RATE

WAKE_PHRASE = "Hey JARVIS"

# Blueprint 3.2: "30-50 clips of you saying 'Hey JARVIS' at different distances
# and tones."
DEFAULT_CLIP_COUNT = 40
MIN_USEFUL_CLIP_COUNT = 30
MAX_USEFUL_CLIP_COUNT = 50

CLIP_FILENAME_PREFIX = "hey_jarvis"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
#: Where wake-word clips land. These are recordings of Ali's voice: personal
#: data. The directory is gitignored, nothing in this package uploads it, and
#: no test ever writes into the real one.
DEFAULT_CLIP_DIR = Path("voice/wakeword_clips")

CLIP_DIR_ENV = "JARVIS_VOICE_CLIP_DIR"
INPUT_DEVICE_ENV = "JARVIS_VOICE_INPUT_DEVICE"

#: Path to the whisper.cpp CLI binary. Produced by the separate
#: ``whisper-npu-build`` lane; there is deliberately no default guess here,
#: because guessing where another lane will put its build artifact is how two
#: lanes end up disagreeing about a path neither of them owns.
WHISPER_CPP_BIN_ENV = "JARVIS_WHISPER_CPP_BIN"

#: Path to the Whisper large-v3 GGML/GGUF model that binary loads. Also the
#: whisper lane's artifact.
WHISPER_MODEL_ENV = "JARVIS_WHISPER_MODEL"

#: Language hint passed to whisper.cpp. Blueprint §2 keeps Urdu/English on
#: Whisper large-v3 precisely because Parakeet is English/European only, so the
#: default is autodetect rather than a hardcoded "en".
WHISPER_LANGUAGE_ENV = "JARVIS_WHISPER_LANGUAGE"
DEFAULT_WHISPER_LANGUAGE = "auto"


def clip_dir() -> Path:
    """Directory wake-word clips are written to."""
    override = os.environ.get(CLIP_DIR_ENV)
    return Path(override) if override else DEFAULT_CLIP_DIR


def input_device() -> str | int | None:
    """Input device for recording, or ``None`` to use the system default.

    ``sounddevice`` accepts either an integer index or a substring of the
    device name, so an all-digit value is passed through as an index.
    """
    raw = os.environ.get(INPUT_DEVICE_ENV)
    if raw is None or raw.strip() == "":
        return None
    raw = raw.strip()
    try:
        return int(raw)
    except ValueError:
        return raw


def whisper_cpp_binary() -> Path | None:
    """Path to the whisper.cpp CLI, or ``None`` if it has not been built yet."""
    raw = os.environ.get(WHISPER_CPP_BIN_ENV)
    return Path(raw) if raw else None


def whisper_model_path() -> Path | None:
    """Path to the Whisper large-v3 weights, or ``None`` if not downloaded."""
    raw = os.environ.get(WHISPER_MODEL_ENV)
    return Path(raw) if raw else None


def whisper_language() -> str:
    """Language hint for whisper.cpp; ``auto`` unless overridden."""
    return os.environ.get(WHISPER_LANGUAGE_ENV) or DEFAULT_WHISPER_LANGUAGE
