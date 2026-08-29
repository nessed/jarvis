from __future__ import annotations

import sys
from pathlib import Path

import pytest

from voice import record_wakeword
from voice.config import WAKEWORD_CHANNELS, WAKEWORD_SAMPLE_RATE
from voice.record_wakeword import (
    PROMPTS,
    ClipPrompt,
    describe_plan,
    main,
    next_clip_index,
    plan_clips,
    record_session,
)


class FakeRecorder:
    """Stands in for a microphone. Records every call's arguments."""

    def __init__(self, *, fail_after: int | None = None) -> None:
        self.calls: list[dict] = []
        self._fail_after = fail_after

    def record(self, *, seconds: float, sample_rate: int, channels: int, device: object) -> object:
        if self._fail_after is not None and len(self.calls) >= self._fail_after:
            raise KeyboardInterrupt
        self.calls.append(
            {"seconds": seconds, "sample_rate": sample_rate, "channels": channels, "device": device}
        )
        return f"audio-{len(self.calls)}"


class FakeWriter:
    def __init__(self) -> None:
        self.written: list[tuple[Path, object, int]] = []

    def write(self, path: Path, data: object, sample_rate: int) -> None:
        self.written.append((path, data, sample_rate))
        path.write_bytes(b"fake wav")


def _touch(directory: Path, name: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(b"")


# --------------------------------------------------------------------------
# Resumability
# --------------------------------------------------------------------------


def test_numbering_starts_at_one_for_a_directory_that_does_not_exist(tmp_path: Path) -> None:
    assert next_clip_index(tmp_path / "absent") == 1


def test_numbering_continues_past_the_highest_existing_clip(tmp_path: Path) -> None:
    _touch(tmp_path, "hey_jarvis_0001_close-normal.wav")
    _touch(tmp_path, "hey_jarvis_0007_quiet.wav")
    _touch(tmp_path, "hey_jarvis_0003_fast.wav")

    assert next_clip_index(tmp_path) == 8


def test_a_resumed_run_does_not_overwrite_clip_one(tmp_path: Path) -> None:
    """The whole point of resumability: clip 1 survives the second session."""
    first = record_session(
        plan_clips(2, start_index=next_clip_index(tmp_path)),
        directory=tmp_path,
        recorder=FakeRecorder(),
        writer=FakeWriter(),
        emit=lambda _msg: None,
        sleep=lambda _s: None,
    )
    second = record_session(
        plan_clips(2, start_index=next_clip_index(tmp_path)),
        directory=tmp_path,
        recorder=FakeRecorder(),
        writer=FakeWriter(),
        emit=lambda _msg: None,
        sleep=lambda _s: None,
    )

    assert [p.name[:16] for p in first] == ["hey_jarvis_0001_", "hey_jarvis_0002_"]
    assert [p.name[:16] for p in second] == ["hey_jarvis_0003_", "hey_jarvis_0004_"]
    assert len({p.name for p in first + second}) == 4


def test_files_that_are_not_ours_do_not_shift_the_numbering(tmp_path: Path) -> None:
    _touch(tmp_path, "hey_jarvis_0002_quiet.wav")
    _touch(tmp_path, "some_export_9999.wav")
    _touch(tmp_path, "notes.txt")

    assert next_clip_index(tmp_path) == 3


# --------------------------------------------------------------------------
# Prompt variation
# --------------------------------------------------------------------------


def test_the_plan_cycles_conditions_instead_of_repeating_one(tmp_path: Path) -> None:
    """Blueprint 3.2 wants clips "at different distances and tones". Forty
    identical takes would satisfy the count and fail the intent."""
    planned = plan_clips(40)

    slugs = [clip.prompt.slug for clip in planned]
    assert len(set(slugs)) == len(PROMPTS)
    counts = {slug: slugs.count(slug) for slug in set(slugs)}
    assert set(counts.values()) == {40 // len(PROMPTS)}


def test_the_prompt_set_covers_both_distance_and_tone() -> None:
    slugs = {p.slug for p in PROMPTS}
    assert {"close-normal", "across-room"} <= slugs, "distance is not varied"
    assert {"quiet", "fast"} <= slugs, "tone is not varied"


def test_a_resumed_run_starts_a_fresh_sweep_of_the_conditions() -> None:
    """Cycling keyed off the absolute index would make a resumed run start
    wherever the modulo fell, which is not a decision anyone made."""
    resumed = plan_clips(3, start_index=17)

    assert [c.prompt.slug for c in resumed] == [p.slug for p in PROMPTS[:3]]
    assert [c.index for c in resumed] == [17, 18, 19]


def test_planning_rejects_a_negative_count_and_an_empty_prompt_set() -> None:
    with pytest.raises(ValueError):
        plan_clips(-1)
    with pytest.raises(ValueError):
        plan_clips(3, prompts=[])


def test_a_clip_filename_carries_its_number_and_its_condition() -> None:
    planned = plan_clips(1, prompts=[ClipPrompt("across-room", "Across the room")])
    assert planned[0].filename == "hey_jarvis_0001_across-room.wav"


def test_describe_plan_names_every_clip(tmp_path: Path) -> None:
    lines = describe_plan(plan_clips(3))
    assert len(lines) == 3
    assert "hey_jarvis_0001_close-normal.wav" in lines[0]


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


def test_every_clip_is_recorded_in_the_training_format(tmp_path: Path) -> None:
    recorder = FakeRecorder()
    writer = FakeWriter()

    written = record_session(
        plan_clips(3),
        directory=tmp_path / "clips",
        recorder=recorder,
        writer=writer,
        seconds=2.0,
        emit=lambda _msg: None,
        sleep=lambda _s: None,
    )

    assert len(written) == 3
    assert all(call["sample_rate"] == WAKEWORD_SAMPLE_RATE for call in recorder.calls)
    assert all(call["channels"] == WAKEWORD_CHANNELS for call in recorder.calls)
    assert all(call["seconds"] == 2.0 for call in recorder.calls)
    assert [rate for _path, _data, rate in writer.written] == [WAKEWORD_SAMPLE_RATE] * 3


def test_the_chosen_device_reaches_the_recorder(tmp_path: Path) -> None:
    recorder = FakeRecorder()

    record_session(
        plan_clips(1),
        directory=tmp_path,
        recorder=recorder,
        writer=FakeWriter(),
        device=4,
        emit=lambda _msg: None,
        sleep=lambda _s: None,
    )

    assert recorder.calls[0]["device"] == 4


def test_ctrl_c_mid_session_keeps_what_was_already_recorded(tmp_path: Path) -> None:
    recorder = FakeRecorder(fail_after=2)
    writer = FakeWriter()
    messages: list[str] = []

    written = record_session(
        plan_clips(5),
        directory=tmp_path,
        recorder=recorder,
        writer=writer,
        emit=messages.append,
        sleep=lambda _s: None,
    )

    assert len(written) == 2
    assert len(writer.written) == 2
    assert any("continue from where this left off" in m for m in messages)
    assert next_clip_index(tmp_path) == 3


def test_the_countdown_speaks_before_every_clip(tmp_path: Path) -> None:
    messages: list[str] = []
    slept: list[float] = []

    record_session(
        plan_clips(2),
        directory=tmp_path,
        recorder=FakeRecorder(),
        writer=FakeWriter(),
        emit=messages.append,
        sleep=slept.append,
    )

    assert sum('say "Hey JARVIS"' in m for m in messages) == 2
    assert slept == [1.0] * 6


def test_the_directory_is_created_if_it_is_not_there(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "clips"

    record_session(
        plan_clips(1),
        directory=target,
        recorder=FakeRecorder(),
        writer=FakeWriter(),
        emit=lambda _msg: None,
        sleep=lambda _s: None,
    )

    assert target.is_dir()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _forbid_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any device access at all is a bug in --dry-run."""

    def explode(*_args, **_kwargs):
        raise AssertionError("a device was opened")

    monkeypatch.setattr(record_wakeword, "SoundDeviceRecorder", explode)
    monkeypatch.setattr(record_wakeword, "SoundFileWriter", explode)
    monkeypatch.setattr(record_wakeword, "record_session", explode)


def test_dry_run_lists_the_plan_and_touches_no_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _forbid_devices(monkeypatch)

    assert main(["--dry-run", "--count", "3", "--dir", str(tmp_path / "clips")]) == 0

    out = capsys.readouterr().out
    assert "hey_jarvis_0001_close-normal.wav" in out
    assert "no device was opened and no file was written" in out
    assert not (tmp_path / "clips").exists()


def test_dry_run_reports_how_many_clips_already_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _forbid_devices(monkeypatch)
    _touch(tmp_path, "hey_jarvis_0012_quiet.wav")

    main(["--dry-run", "--count", "2", "--dir", str(tmp_path)])

    out = capsys.readouterr().out
    assert "Already recorded: 12" in out
    assert "hey_jarvis_0013_close-normal.wav" in out


def test_the_cli_refuses_a_non_positive_count(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--count", "0", "--dir", str(tmp_path)])


def test_the_cli_records_through_the_injected_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = FakeRecorder()
    writer = FakeWriter()
    monkeypatch.setattr(record_wakeword, "SoundDeviceRecorder", lambda: recorder)
    monkeypatch.setattr(record_wakeword, "SoundFileWriter", lambda: writer)
    monkeypatch.setattr(record_wakeword.time, "sleep", lambda _s: None)

    assert main(["--count", "2", "--dir", str(tmp_path), "--seconds", "1.5"]) == 0

    assert len(writer.written) == 2
    assert all(call["seconds"] == 1.5 for call in recorder.calls)
    assert "Wrote 2 clip(s)" in capsys.readouterr().out


def test_a_run_that_would_leave_fewer_than_thirty_clips_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(record_wakeword, "SoundDeviceRecorder", FakeRecorder)
    monkeypatch.setattr(record_wakeword, "SoundFileWriter", FakeWriter)
    monkeypatch.setattr(record_wakeword.time, "sleep", lambda _s: None)

    main(["--count", "2", "--dir", str(tmp_path)])

    assert "Blueprint 3.2 asks for 30-50" in capsys.readouterr().out


def test_the_clip_directory_comes_from_the_env_when_no_flag_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _forbid_devices(monkeypatch)
    monkeypatch.setenv("JARVIS_VOICE_CLIP_DIR", str(tmp_path / "from-env"))

    main(["--dry-run", "--count", "1"])

    assert str(tmp_path / "from-env") in capsys.readouterr().out


def test_list_devices_reports_only_inputs(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class FakeSoundDevice:
        @staticmethod
        def query_devices():
            return [
                {"name": "Speakers", "max_input_channels": 0},
                {"name": "Microphone Array", "max_input_channels": 2},
            ]

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSoundDevice)

    assert main(["--list-devices"]) == 0

    out = capsys.readouterr().out
    assert "Microphone Array" in out
    assert "Speakers" not in out
