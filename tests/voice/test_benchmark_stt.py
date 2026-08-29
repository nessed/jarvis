from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from voice import benchmark_stt
from voice.benchmark_stt import (
    Availability,
    BackendResult,
    WhisperCppBackend,
    format_table,
    main,
    results_as_json,
    run_benchmark,
    whisper_cpp_command,
)
from voice.config import WHISPER_CPP_BIN_ENV, WHISPER_MODEL_ENV


class FakeBackend:
    """A pluggable backend that never touches a model."""

    def __init__(self, name: str, *, available: bool = True, reason: str = "", transcript: str = "hello", boom=None):
        self.name = name
        self._available = available
        self._reason = reason
        self._transcript = transcript
        self._boom = boom
        self.calls: list[Path] = []

    def availability(self) -> Availability:
        return Availability(self._available, self._reason)

    def transcribe(self, clip: Path) -> str:
        self.calls.append(clip)
        if self._boom is not None:
            raise self._boom
        return self._transcript


class FakeClock:
    """Deterministic timer: each call advances by a fixed step."""

    def __init__(self, steps: list[float]) -> None:
        self._steps = list(steps)
        self._now = 0.0

    def __call__(self) -> float:
        value = self._now
        if self._steps:
            self._now += self._steps.pop(0)
        return value


# --------------------------------------------------------------------------
# run_benchmark
# --------------------------------------------------------------------------


def test_an_unavailable_backend_produces_a_row_rather_than_a_crash(tmp_path: Path) -> None:
    """The whole point: whisper.cpp is not built yet, and the benchmark must
    still run and still print a table."""
    backend = FakeBackend("local", available=False, reason="not built yet")

    results = run_benchmark([backend], tmp_path / "clip.wav")

    assert results[0].available is False
    assert results[0].reason == "not built yet"
    assert results[0].latency_seconds is None
    assert backend.calls == []


def test_one_unavailable_backend_does_not_stop_the_others(tmp_path: Path) -> None:
    results = run_benchmark(
        [FakeBackend("dead", available=False, reason="nope"), FakeBackend("live", transcript="salaam")],
        tmp_path / "clip.wav",
    )

    assert [r.available for r in results] == [False, True]
    assert results[1].transcript == "salaam"


def test_latency_is_wall_clock_around_the_transcription(tmp_path: Path) -> None:
    results = run_benchmark(
        [FakeBackend("local")],
        tmp_path / "clip.wav",
        timer=FakeClock([1.25, 0.0]),
    )

    assert results[0].latency_seconds == pytest.approx(1.25)


def test_multiple_runs_report_the_median(tmp_path: Path) -> None:
    results = run_benchmark(
        [FakeBackend("local")],
        tmp_path / "clip.wav",
        runs=3,
        timer=FakeClock([1.0, 0.0, 5.0, 0.0, 2.0, 0.0]),
    )

    assert results[0].latencies == pytest.approx((1.0, 5.0, 2.0))
    assert results[0].latency_seconds == pytest.approx(2.0)


def test_a_backend_that_blows_up_is_recorded_not_raised(tmp_path: Path) -> None:
    results = run_benchmark(
        [FakeBackend("local", boom=RuntimeError("model refused")), FakeBackend("other")],
        tmp_path / "clip.wav",
    )

    assert results[0].error == "RuntimeError: model refused"
    assert results[1].transcript == "hello"


def test_runs_must_be_at_least_one(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        run_benchmark([FakeBackend("local")], tmp_path / "clip.wav", runs=0)


def test_the_realtime_factor_is_latency_over_clip_length() -> None:
    result = BackendResult(name="local", available=True, latencies=(5.0,), transcript="x")

    assert result.realtime_factor(10.0) == pytest.approx(0.5)
    assert result.realtime_factor(None) is None
    assert BackendResult(name="local", available=False).realtime_factor(10.0) is None


# --------------------------------------------------------------------------
# WhisperCppBackend
# --------------------------------------------------------------------------


def test_the_local_backend_names_the_env_var_that_would_fix_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(WHISPER_CPP_BIN_ENV, raising=False)
    monkeypatch.delenv(WHISPER_MODEL_ENV, raising=False)

    availability = WhisperCppBackend().availability()

    assert availability.available is False
    assert WHISPER_CPP_BIN_ENV in availability.reason


def test_a_binary_that_points_nowhere_is_reported_not_assumed(tmp_path: Path) -> None:
    availability = WhisperCppBackend(
        binary=tmp_path / "missing.exe", model=tmp_path / "m.bin"
    ).availability()

    assert availability.available is False
    assert "missing file" in availability.reason


def test_a_present_binary_with_no_model_is_still_unavailable(tmp_path: Path) -> None:
    binary = tmp_path / "whisper-cli.exe"
    binary.write_bytes(b"")

    availability = WhisperCppBackend(binary=binary, model=None).availability()

    assert availability.available is False
    assert WHISPER_MODEL_ENV in availability.reason


def test_the_local_backend_is_available_once_both_artifacts_exist(tmp_path: Path) -> None:
    binary = tmp_path / "whisper-cli.exe"
    model = tmp_path / "ggml-large-v3.bin"
    binary.write_bytes(b"")
    model.write_bytes(b"")

    assert WhisperCppBackend(binary=binary, model=model).availability().available is True


def test_the_whisper_command_carries_the_model_clip_and_language(tmp_path: Path) -> None:
    command = whisper_cpp_command(
        tmp_path / "whisper-cli.exe",
        tmp_path / "m.bin",
        tmp_path / "clip.wav",
        language="auto",
        extra_args=("-t", "8"),
    )

    assert command[0] == str(tmp_path / "whisper-cli.exe")
    assert command[command.index("-m") + 1] == str(tmp_path / "m.bin")
    assert command[command.index("-f") + 1] == str(tmp_path / "clip.wav")
    assert command[command.index("-l") + 1] == "auto"
    assert command[-2:] == ["-t", "8"]


def test_the_local_backend_returns_the_binarys_stdout(tmp_path: Path) -> None:
    binary, model, clip = tmp_path / "w.exe", tmp_path / "m.bin", tmp_path / "c.wav"
    for path in (binary, model, clip):
        path.write_bytes(b"")
    seen: list[list[str]] = []

    def runner(command: list[str]) -> subprocess.CompletedProcess:
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="  mujhe yaad dila do  \n", stderr="")

    backend = WhisperCppBackend(binary=binary, model=model, language="auto", runner=runner)

    assert backend.transcribe(clip) == "mujhe yaad dila do"
    assert seen[0][0] == str(binary)


def test_a_nonzero_exit_becomes_a_readable_error(tmp_path: Path) -> None:
    binary, model, clip = tmp_path / "w.exe", tmp_path / "m.bin", tmp_path / "c.wav"
    for path in (binary, model, clip):
        path.write_bytes(b"")

    def runner(command: list[str]) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(command, 3, stdout="", stderr="init\nfailed to load model\n")

    backend = WhisperCppBackend(binary=binary, model=model, runner=runner)

    with pytest.raises(RuntimeError, match="failed to load model"):
        backend.transcribe(clip)


def test_there_is_exactly_one_default_backend_and_it_is_local() -> None:
    """No Groq backend: stt-backends is an open Class C decision in
    docs/plan.md and this lane does not get to settle it."""
    backends = benchmark_stt.default_backends()

    assert len(backends) == 1
    assert isinstance(backends[0], WhisperCppBackend)


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def test_the_table_shows_why_an_unavailable_backend_did_not_run() -> None:
    table = format_table([BackendResult(name="whisper.cpp (local)", available=False, reason="not built yet")])

    assert "not available: not built yet" in table
    assert "whisper.cpp (local)" in table


def test_the_table_shows_latency_and_realtime_factor() -> None:
    table = format_table(
        [BackendResult(name="local", available=True, latencies=(4.0,), transcript="salaam")],
        clip_seconds=10.0,
    )

    assert "4.00s" in table
    assert "0.40" in table
    assert "salaam" in table


def test_a_long_transcript_is_truncated_rather_than_wrapping_the_table() -> None:
    table = format_table(
        [BackendResult(name="local", available=True, latencies=(1.0,), transcript="word " * 100)],
        clip_seconds=10.0,
        transcript_width=20,
    )

    assert max(len(line) for line in table.splitlines()) < 80


def test_a_failed_backend_shows_its_failure_in_the_table() -> None:
    table = format_table([BackendResult(name="local", available=True, error="RuntimeError: boom")])

    assert "failed: RuntimeError: boom" in table


def test_the_json_output_is_machine_readable() -> None:
    payload = json.loads(
        results_as_json(
            [BackendResult(name="local", available=True, latencies=(2.0, 4.0), transcript="hi")],
            clip_seconds=10.0,
        )
    )

    assert payload["clip_seconds"] == 10.0
    assert payload["backends"][0]["latency_seconds"] == 3.0
    assert payload["backends"][0]["realtime_factor"] == pytest.approx(0.3)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _stub_backends(monkeypatch: pytest.MonkeyPatch, backends: list) -> None:
    monkeypatch.setattr(benchmark_stt, "WhisperCppBackend", lambda **_kwargs: backends[0])


def test_no_clip_says_so_and_invents_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2

    err = capsys.readouterr().err
    assert "A clip is required" in err
    assert "will not be\ninvented" in err


def test_a_missing_clip_path_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--clip", str(tmp_path / "nope.wav")]) == 2
    assert "Clip not found" in capsys.readouterr().err


def test_the_cli_runs_and_prints_a_table_with_no_backend_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The state this machine is actually in today: whisper.cpp unbuilt."""
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"")
    monkeypatch.setattr(benchmark_stt, "probe_clip_seconds", lambda _p: 10.0)
    _stub_backends(monkeypatch, [FakeBackend("whisper.cpp (local)", available=False, reason="not built yet")])

    assert main(["--clip", str(clip)]) == 3

    out = capsys.readouterr().out
    assert "not available: not built yet" in out
    assert "10.0s" in out


def test_the_cli_returns_zero_when_a_backend_measures_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"")
    monkeypatch.setattr(benchmark_stt, "probe_clip_seconds", lambda _p: 10.0)
    _stub_backends(monkeypatch, [FakeBackend("whisper.cpp (local)", transcript="assalam o alaikum")])

    assert main(["--clip", str(clip)]) == 0
    assert "assalam o alaikum" in capsys.readouterr().out


def test_a_backend_failure_is_a_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"")
    monkeypatch.setattr(benchmark_stt, "probe_clip_seconds", lambda _p: 10.0)
    _stub_backends(monkeypatch, [FakeBackend("local", boom=RuntimeError("boom"))])

    assert main(["--clip", str(clip)]) == 1


def test_a_clip_that_is_not_about_ten_seconds_is_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Blueprint 3.1 measures on ~10s. A number from a 2s clip is not the
    number Ali is being asked to judge."""
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"")
    monkeypatch.setattr(benchmark_stt, "probe_clip_seconds", lambda _p: 2.0)
    _stub_backends(monkeypatch, [FakeBackend("local")])

    main(["--clip", str(clip)])

    assert "not comparable to that target" in capsys.readouterr().out


def test_an_unreadable_clip_duration_does_not_stop_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"")
    monkeypatch.setattr(benchmark_stt, "probe_clip_seconds", lambda _p: None)
    _stub_backends(monkeypatch, [FakeBackend("local")])

    assert main(["--clip", str(clip)]) == 0
    assert "duration unreadable" in capsys.readouterr().out


def test_probe_clip_seconds_returns_none_for_a_non_audio_file(tmp_path: Path) -> None:
    junk = tmp_path / "not-audio.wav"
    junk.write_bytes(b"definitely not a wav")

    assert benchmark_stt.probe_clip_seconds(junk) is None


def test_json_mode_emits_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"")
    monkeypatch.setattr(benchmark_stt, "probe_clip_seconds", lambda _p: 10.0)
    _stub_backends(monkeypatch, [FakeBackend("local", transcript="hi")])

    main(["--clip", str(clip), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["backends"][0]["transcript"] == "hi"
