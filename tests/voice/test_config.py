from __future__ import annotations

from pathlib import Path

import pytest

from voice import config


def test_the_recording_format_is_the_one_openwakeword_trains_on() -> None:
    """Not a preference. openwakeword/data.py:120 shells out to
    ``sox -r 16000 -c 1 -b 16`` and train.py:816 comments "training data is
    always 16 khz". Drifting from this is a silent quality loss."""
    assert config.WAKEWORD_SAMPLE_RATE == 16000
    assert config.WAKEWORD_CHANNELS == 1
    assert config.WAKEWORD_DTYPE == "int16"
    assert config.WAKEWORD_SUBTYPE == "PCM_16"


def test_the_default_clip_is_the_trainers_minimum_window() -> None:
    """openwakeword/train.py:748-749 clamps total_length to a 32000-sample
    floor. A 2.0s window means no clip is padded up from something shorter."""
    assert config.WAKEWORD_MIN_TRAINING_SAMPLES == 32000
    assert config.DEFAULT_CLIP_SECONDS == pytest.approx(2.0)


def test_the_clip_count_range_matches_blueprint_3_2() -> None:
    assert config.MIN_USEFUL_CLIP_COUNT == 30
    assert config.MAX_USEFUL_CLIP_COUNT == 50
    assert config.MIN_USEFUL_CLIP_COUNT <= config.DEFAULT_CLIP_COUNT <= config.MAX_USEFUL_CLIP_COUNT


def test_clip_dir_defaults_to_the_gitignored_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(config.CLIP_DIR_ENV, raising=False)
    assert config.clip_dir() == Path("voice/wakeword_clips")


def test_clip_dir_honours_the_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(config.CLIP_DIR_ENV, str(tmp_path / "clips"))
    assert config.clip_dir() == tmp_path / "clips"


def test_input_device_is_none_when_unset_or_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(config.INPUT_DEVICE_ENV, raising=False)
    assert config.input_device() is None
    monkeypatch.setenv(config.INPUT_DEVICE_ENV, "   ")
    assert config.input_device() is None


def test_a_numeric_device_becomes_an_index_and_a_name_stays_a_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sounddevice accepts either, and passing "3" as a string matches a device
    whose *name* contains a 3, which is not what the user meant."""
    monkeypatch.setenv(config.INPUT_DEVICE_ENV, "3")
    assert config.input_device() == 3
    monkeypatch.setenv(config.INPUT_DEVICE_ENV, "Microphone Array")
    assert config.input_device() == "Microphone Array"


def test_whisper_paths_are_none_until_the_build_lane_sets_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There is deliberately no default path guess: the whisper-npu-build lane
    owns where its artifacts land."""
    monkeypatch.delenv(config.WHISPER_CPP_BIN_ENV, raising=False)
    monkeypatch.delenv(config.WHISPER_MODEL_ENV, raising=False)
    assert config.whisper_cpp_binary() is None
    assert config.whisper_model_path() is None


def test_whisper_paths_come_from_the_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(config.WHISPER_CPP_BIN_ENV, str(tmp_path / "whisper-cli.exe"))
    monkeypatch.setenv(config.WHISPER_MODEL_ENV, str(tmp_path / "large-v3.bin"))
    assert config.whisper_cpp_binary() == tmp_path / "whisper-cli.exe"
    assert config.whisper_model_path() == tmp_path / "large-v3.bin"


def test_whisper_language_defaults_to_autodetect(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blueprint §2 keeps Urdu/English on large-v3 because Parakeet is
    English/European only. Hardcoding "en" would throw that away."""
    monkeypatch.delenv(config.WHISPER_LANGUAGE_ENV, raising=False)
    assert config.whisper_language() == "auto"
    monkeypatch.setenv(config.WHISPER_LANGUAGE_ENV, "ur")
    assert config.whisper_language() == "ur"
