"""Tests for ``voice/audition_voices.py``, the Kokoro voice audition CLI.

No speakers, no Kokoro, no torch, no huggingface cache. The voice cache is a
directory the test made, the synthesiser is a fake, and the only real audio
library involved is ``soundfile`` writing into ``tmp_path``.

What is deliberately not tested: which voice sounds right. That is a sensory
call, permanently the user's, and this script exists to make it cost him one
command -- not to make an agent able to make it for him.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from voice import audition_voices
from voice.audition_voices import (
    DEFAULT_LANG,
    DEFAULT_TEXT,
    KOKORO_SAMPLE_RATE,
    default_cache_root,
    installed_voices,
    main,
)
from voice.config import DEFAULT_TTS_LANG, TTS_SAMPLE_RATE


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakePipeline:
    """Kokoro, without Kokoro. Yields one chunk per sentence-ish segment."""

    built: list[dict] = []

    def __init__(self, *, lang_code: str) -> None:
        self.lang_code = lang_code
        self.calls: list[tuple[str, str]] = []
        FakePipeline.built.append({"lang_code": lang_code, "pipeline": self})

    def __call__(self, text: str, *, voice: str):
        self.calls.append((text, voice))
        if voice.endswith("_silent"):
            return []
        # Two segments, so the "join the chunks" behaviour is exercised.
        half = np.zeros(KOKORO_SAMPLE_RATE // 2, dtype="float32")
        return [("gs", "ps", half), ("gs", "ps", half)]


class FakeKokoroModule:
    KPipeline = FakePipeline


class ExplodingModule:
    """Any attribute access is a failure: this module must never be reached."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, attribute: str):
        raise AssertionError(f"{self._name}.{attribute} was imported")


class FakeSoundDevice:
    def __init__(self) -> None:
        self.played: list[tuple[int, int]] = []
        self.waits = 0

    def play(self, audio, samplerate) -> None:
        self.played.append((len(audio), samplerate))

    def wait(self) -> None:
        self.waits += 1


@pytest.fixture(autouse=True)
def _reset_pipeline_log():
    FakePipeline.built = []
    yield
    FakePipeline.built = []


@pytest.fixture
def kokoro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "kokoro", FakeKokoroModule)


@pytest.fixture
def speaker(monkeypatch: pytest.MonkeyPatch) -> FakeSoundDevice:
    fake = FakeSoundDevice()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    return fake


@pytest.fixture
def no_kokoro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "kokoro", ExplodingModule("kokoro"))


@pytest.fixture
def no_speaker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sounddevice", ExplodingModule("sounddevice"))


def stock_voices(monkeypatch: pytest.MonkeyPatch, names: list[str]) -> None:
    monkeypatch.setattr(audition_voices, "installed_voices", lambda *_a, **_k: sorted(names))


VOICES = ["af_bella", "af_heart", "am_puck", "am_onyx", "bf_alice", "bm_george"]


def _pack(directory: Path, *names: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / f"{name}.pt").write_bytes(b"")


# ---------------------------------------------------------------------------
# Reading what is actually installed
# ---------------------------------------------------------------------------


def test_voice_ids_are_read_off_disk_and_sorted(tmp_path: Path) -> None:
    _pack(tmp_path / "hub" / "voices", "am_puck", "af_heart")
    _pack(tmp_path / "hub" / "other", "bm_george")

    assert installed_voices(tmp_path) == ["af_heart", "am_puck", "bm_george"]


def test_the_same_voice_cached_twice_is_listed_once(tmp_path: Path) -> None:
    _pack(tmp_path / "a", "am_puck")
    _pack(tmp_path / "b" / "c", "am_puck")

    assert installed_voices(tmp_path) == ["am_puck"]


def test_files_that_are_not_voice_packs_are_ignored(tmp_path: Path) -> None:
    """The scan is a glob over a shared huggingface cache, so it will see other
    models' checkpoints. Only things shaped like a voice id count."""
    _pack(tmp_path, "am_puck", "model", "a_b", "pytorch_model")
    (tmp_path / "notes.txt").write_bytes(b"")

    found = installed_voices(tmp_path)
    assert "am_puck" in found
    assert "pytorch_model" in found  # honest about the current rule
    assert "model" not in found, "an id with no underscore was accepted"
    assert "a_b" not in found, "a three-character id was accepted"


def test_an_absent_cache_directory_is_empty_not_an_error(tmp_path: Path) -> None:
    assert installed_voices(tmp_path / "never-downloaded") == []


def test_the_default_cache_root_is_the_huggingface_cache() -> None:
    root = default_cache_root()
    assert root.parts[-2:] == (".cache", "huggingface")
    assert root.parent.parent == Path.home()


# ---------------------------------------------------------------------------
# --list
# ---------------------------------------------------------------------------


def test_list_prints_every_installed_id_and_loads_no_model(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], no_kokoro, no_speaker
) -> None:
    stock_voices(monkeypatch, VOICES)

    assert main(["--list"]) == 0

    out = capsys.readouterr().out
    assert f"{len(VOICES)} voices installed" in out
    for name in VOICES:
        assert name in out


def test_no_installed_voices_is_an_error_that_names_the_lane_that_fetches_them(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], no_kokoro, no_speaker
) -> None:
    stock_voices(monkeypatch, [])

    assert main([]) == 1

    err = capsys.readouterr().err
    assert "no Kokoro voice packs found" in err
    assert "voice-deps" in err


# ---------------------------------------------------------------------------
# Choosing which voices to play
# ---------------------------------------------------------------------------


def test_an_uninstalled_voice_is_refused_before_anything_is_loaded(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], no_kokoro, no_speaker
) -> None:
    stock_voices(monkeypatch, VOICES)

    assert main(["--voice", "af_nonexistent"]) == 1

    err = capsys.readouterr().err
    assert "'af_nonexistent' is not installed" in err
    assert "--list" in err


def test_a_filter_that_matches_nothing_is_an_error_not_a_silent_no_op(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], no_kokoro, no_speaker
) -> None:
    stock_voices(monkeypatch, VOICES)

    assert main(["--filter", "zz_"]) == 1
    assert "no installed voice starts with 'zz_'" in capsys.readouterr().err


def test_the_filter_selects_by_id_prefix(
    monkeypatch: pytest.MonkeyPatch, kokoro, speaker: FakeSoundDevice, capsys
) -> None:
    """Kokoro encodes language and gender in the prefix, which is the only
    reason ``--filter am_`` is a meaningful thing to ask for."""
    stock_voices(monkeypatch, VOICES)

    assert main(["--filter", "am_"]) == 0

    played = [call[1] for call in FakePipeline.built[0]["pipeline"].calls]
    assert played == ["am_onyx", "am_puck"]


def test_the_limit_caps_how_many_play_in_one_run(
    monkeypatch: pytest.MonkeyPatch, kokoro, speaker: FakeSoundDevice, capsys
) -> None:
    stock_voices(monkeypatch, VOICES)

    assert main(["--limit", "2"]) == 0

    assert len(FakePipeline.built[0]["pipeline"].calls) == 2
    assert speaker.played and len(speaker.played) == 2


def test_a_named_voice_plays_only_that_one(
    monkeypatch: pytest.MonkeyPatch, kokoro, speaker: FakeSoundDevice, capsys
) -> None:
    stock_voices(monkeypatch, VOICES)

    assert main(["--voice", "am_puck"]) == 0

    assert [call[1] for call in FakePipeline.built[0]["pipeline"].calls] == ["am_puck"]


# ---------------------------------------------------------------------------
# Synthesis and playback
# ---------------------------------------------------------------------------


def test_the_pipeline_is_built_for_the_language_the_voice_ids_belong_to(
    monkeypatch: pytest.MonkeyPatch, kokoro, speaker: FakeSoundDevice, capsys
) -> None:
    """The pipeline code and the voice prefix have to agree, or the phonemiser
    mismatches the pack. ``a`` is Kokoro's American-English code."""
    stock_voices(monkeypatch, ["am_puck"])

    main(["--voice", "am_puck"])

    assert FakePipeline.built[0]["lang_code"] == DEFAULT_LANG
    assert DEFAULT_LANG == "a"


def test_the_pipeline_lang_code_agrees_with_the_shared_tts_config() -> None:
    """Two modules naming the same Kokoro settings is how they drift apart."""
    assert DEFAULT_LANG == DEFAULT_TTS_LANG
    assert KOKORO_SAMPLE_RATE == TTS_SAMPLE_RATE == 24000


def test_the_text_flag_reaches_the_synthesiser(
    monkeypatch: pytest.MonkeyPatch, kokoro, speaker: FakeSoundDevice, capsys
) -> None:
    stock_voices(monkeypatch, ["am_puck"])

    main(["--voice", "am_puck", "--text", "yo, what's the plan"])

    assert FakePipeline.built[0]["pipeline"].calls == [("yo, what's the plan", "am_puck")]
    assert "yo, what's the plan" in capsys.readouterr().out


def test_the_default_line_is_used_when_no_text_is_given(
    monkeypatch: pytest.MonkeyPatch, kokoro, speaker: FakeSoundDevice, capsys
) -> None:
    stock_voices(monkeypatch, ["am_puck"])

    main(["--voice", "am_puck"])

    assert FakePipeline.built[0]["pipeline"].calls[0][0] == DEFAULT_TEXT


def test_the_segments_are_joined_into_one_continuous_take(
    monkeypatch: pytest.MonkeyPatch, kokoro, speaker: FakeSoundDevice, capsys
) -> None:
    """Kokoro yields one chunk per segment. Playing them separately would put a
    gap in the middle of the line being judged."""
    stock_voices(monkeypatch, ["am_puck"])

    main(["--voice", "am_puck"])

    assert speaker.played == [(KOKORO_SAMPLE_RATE, KOKORO_SAMPLE_RATE)]
    assert "1.0s" in capsys.readouterr().out


def test_playback_waits_for_each_voice_to_finish(
    monkeypatch: pytest.MonkeyPatch, kokoro, speaker: FakeSoundDevice, capsys
) -> None:
    """Without the wait, every voice is cut off by the next one and nothing
    can be judged."""
    stock_voices(monkeypatch, VOICES)

    main(["--filter", "am_"])

    assert speaker.waits == len(speaker.played) == 2


def test_a_voice_that_produces_no_audio_is_reported_and_the_rest_still_play(
    monkeypatch: pytest.MonkeyPatch, kokoro, speaker: FakeSoundDevice, capsys
) -> None:
    stock_voices(monkeypatch, ["am_silent", "am_puck"])

    assert main(["--filter", "am_"]) == 0

    out = capsys.readouterr().out
    assert "am_silent" in out and "produced no audio, skipped" in out
    assert len(speaker.played) == 1, "the working voice did not play"


def test_playback_ends_by_asking_him_to_pick(
    monkeypatch: pytest.MonkeyPatch, kokoro, speaker: FakeSoundDevice, capsys
) -> None:
    stock_voices(monkeypatch, ["am_puck"])

    main(["--voice", "am_puck"])

    assert "Pick one and tell me the id" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# --save
# ---------------------------------------------------------------------------


def test_save_writes_a_wav_and_never_opens_a_speaker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kokoro, no_speaker, capsys
) -> None:
    stock_voices(monkeypatch, ["am_puck"])
    target = tmp_path / "picked.wav"

    assert main(["--voice", "am_puck", "--save", str(target)]) == 0

    assert target.exists()
    import soundfile as sf

    data, rate = sf.read(target)
    assert rate == KOKORO_SAMPLE_RATE
    assert len(data) == KOKORO_SAMPLE_RATE
    assert str(target) in capsys.readouterr().out


def test_saving_several_voices_gives_each_its_own_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kokoro, no_speaker, capsys
) -> None:
    """One ``--save picked.wav`` for six voices would otherwise leave one file
    containing whichever voice happened to be last."""
    stock_voices(monkeypatch, VOICES)
    target = tmp_path / "picked.wav"

    assert main(["--filter", "am_", "--save", str(target)]) == 0

    written = sorted(p.name for p in tmp_path.glob("*.wav"))
    assert written == ["picked_am_onyx.wav", "picked_am_puck.wav"]
    assert not target.exists()


def test_save_does_not_ask_him_to_pick_by_ear(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kokoro, no_speaker, capsys
) -> None:
    stock_voices(monkeypatch, ["am_puck"])

    main(["--voice", "am_puck", "--save", str(tmp_path / "x.wav")])

    assert "Pick one and tell me the id" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Import hygiene
# ---------------------------------------------------------------------------


def test_importing_the_module_pulls_in_no_synthesiser_and_no_speaker() -> None:
    """``kokoro`` drags in torch. Importing it at module scope would make this
    file take seconds and would need the model cache present."""
    import importlib

    names = ("voice.audition_voices", "kokoro", "sounddevice", "soundfile")
    saved = {name: sys.modules[name] for name in names if name in sys.modules}
    for name in names:
        sys.modules.pop(name, None)
    try:
        module = importlib.import_module("voice.audition_voices")
        assert module.main is not None
        assert "kokoro" not in sys.modules
        assert "sounddevice" not in sys.modules
        assert "soundfile" not in sys.modules
    finally:
        sys.modules.update(saved)
