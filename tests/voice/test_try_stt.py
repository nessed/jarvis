"""Tests for ``voice/try_stt.py``, the record-and-transcribe CLI.

Everything here runs against fakes. No microphone, no NPU, no ``whisper-cli``,
no model weights, no network. The only real subprocess any test starts is
``sys.executable -c`` printing bytes, and that exists precisely to prove the
UTF-8 decode is real rather than mocked away.

Why so much of this file is about encoding
------------------------------------------
This machine's locale codec is cp1252, which cannot represent Urdu or Arabic
script, and it broke the same feature twice in one hour on 29 Aug 2026:

1. ``subprocess.run(text=True)`` decoded whisper.cpp's UTF-8 stdout with the
   locale codec and died with ``UnicodeDecodeError`` on a **successful** Urdu
   transcription. The failure was reported as ``(nothing recognised)`` -- the
   model had worked and the text was destroyed on the way back.
2. Once the decode was fixed, ``print()`` of the recovered text died with
   ``UnicodeEncodeError`` against the cp1252 console. Identical symptom, other
   end of the pipe.

Both halves are pinned below, and the console half is pinned against a real
``cp1252`` stream rather than a mock, so a regression fails here instead of in
front of the user.
"""

from __future__ import annotations

import io
import subprocess
import sys
import types
from pathlib import Path

import pytest

from voice import try_stt
from voice.config import (
    WAKEWORD_CHANNELS,
    WAKEWORD_DTYPE,
    WHISPER_LANGUAGE_ENV,
    DEFAULT_WHISPER_LANGUAGE,
)
from voice.try_stt import _force_utf8_console, main, record, scratch_clip_path
from voice.whisper import local_backend
from voice.whisper.local_backend import Availability, LocalWhisperBackend, clean_transcript

# Real Urdu, not a Latin stand-in. Every character here is outside latin-1 and
# outside cp1252, which is the whole point: a stand-in would pass on the exact
# console that broke.
URDU_HELLO = "ہیلو"  # "hello"
URDU_SENTENCE = "میں ٹھیک ہوں"  # "I am fine"
CODE_SWITCHED = f"{URDU_SENTENCE} and the tunnel is live"

assert all(ord(ch) > 0xFF for ch in URDU_HELLO), "sample must be outside latin-1"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeBackend:
    """A whisper backend that never starts a process."""

    def __init__(
        self,
        *,
        language: str = DEFAULT_WHISPER_LANGUAGE,
        text: str = "hello there",
        available: bool = True,
        reason: str = "",
        raises: BaseException | None = None,
    ) -> None:
        self.language = language
        self.clips: list[Path] = []
        self._text = text
        self._availability = Availability(available, reason)
        self._raises = raises

    def availability(self) -> Availability:
        return self._availability

    def __call__(self, clip) -> tuple[str, float]:
        self.clips.append(Path(clip))
        if self._raises is not None:
            raise self._raises
        return self._text, 0.25


class RecordingFactory:
    """Stands in for ``LocalWhisperBackend``. Remembers every construction."""

    def __init__(self, *backends: FakeBackend) -> None:
        self.languages: list[str | None] = []
        self.built: list[FakeBackend] = []
        self._queue = list(backends)

    def __call__(self, *, language=None, **_rest) -> FakeBackend:
        self.languages.append(language)
        backend = self._queue.pop(0) if self._queue else FakeBackend(language=language)
        backend.language = language if language is not None else backend.language
        self.built.append(backend)
        return backend


def install_backends(
    monkeypatch: pytest.MonkeyPatch,
    *,
    default: FakeBackend | None = None,
    factory: RecordingFactory | None = None,
) -> tuple[FakeBackend, RecordingFactory, list[str]]:
    """Point ``try_stt``'s late imports at fakes.

    ``main`` imports ``LocalWhisperBackend`` and ``default_backend`` from
    ``voice.whisper.local_backend`` at call time, so patching the module's
    attributes is what the CLI actually resolves.
    """
    default = default or FakeBackend()
    factory = factory or RecordingFactory()
    default_calls: list[str] = []

    def spy_default() -> FakeBackend:
        default_calls.append("default_backend")
        return default

    monkeypatch.setattr(local_backend, "LocalWhisperBackend", factory)
    monkeypatch.setattr(local_backend, "default_backend", spy_default)
    return default, factory, default_calls


def forbid_recording(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args, **_kwargs):
        raise AssertionError("the microphone was opened")

    monkeypatch.setattr(try_stt, "record", explode)


class FakeRecorder:
    """Replaces ``try_stt.record``. Writes a stub file, records its arguments."""

    def __init__(self, seconds: float = 6.0) -> None:
        self.calls: list[dict] = []
        self._seconds = seconds

    def __call__(self, seconds: float, device, destination: Path) -> float:
        self.calls.append({"seconds": seconds, "device": device, "destination": destination})
        Path(destination).write_bytes(b"fake wav")
        return self._seconds


def cp1252_console() -> io.TextIOWrapper:
    """A console exactly as hostile as this machine's real one."""
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="")


def completed(stdout: str = "", *, returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["whisper-cli"], returncode=returncode, stdout=stdout, stderr=stderr
    )


@pytest.fixture
def artifacts(tmp_path: Path) -> dict:
    """Files that only have to exist for ``availability()`` to say yes."""
    binary = tmp_path / "whisper-cli.exe"
    model = tmp_path / "ggml-large-v3.bin"
    binary.write_bytes(b"")
    model.write_bytes(b"")
    (tmp_path / "ggml-large-v3-encoder-vitisai.rai").write_bytes(b"")
    return {"binary": binary, "model": model}


# ===========================================================================
# The encoding bug, both halves
# ===========================================================================


def test_a_cp1252_console_really_cannot_print_urdu() -> None:
    """The control. Without this the tests below prove nothing: they would
    pass on a console that never had the problem."""
    console = cp1252_console()

    with pytest.raises(UnicodeEncodeError):
        console.write(URDU_HELLO)


def test_force_utf8_console_makes_that_same_console_accept_urdu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console = cp1252_console()
    monkeypatch.setattr(sys, "stdout", console)
    monkeypatch.setattr(sys, "stderr", cp1252_console())

    _force_utf8_console()
    print(URDU_SENTENCE)
    console.flush()

    assert console.buffer.getvalue().decode("utf-8") == URDU_SENTENCE + "\n"


def test_both_streams_are_reconfigured_to_utf8_with_replacement() -> None:
    class Spy:
        def __init__(self) -> None:
            self.kwargs: list[dict] = []

        def reconfigure(self, **kwargs) -> None:
            self.kwargs.append(kwargs)

    out, err = Spy(), Spy()
    original_out, original_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        _force_utf8_console()
    finally:
        sys.stdout, sys.stderr = original_out, original_err

    # errors="replace" is the half that matters: one undecodable byte must not
    # cost the whole transcript.
    assert out.kwargs == [{"encoding": "utf-8", "errors": "replace"}]
    assert err.kwargs == [{"encoding": "utf-8", "errors": "replace"}]


@pytest.mark.parametrize("boom", [ValueError("already wrapped"), OSError("redirected")])
def test_a_stream_that_refuses_to_reconfigure_does_not_kill_the_run(boom: Exception) -> None:
    class Stubborn:
        def reconfigure(self, **_kwargs):
            raise boom

    original_out, original_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = Stubborn(), Stubborn()
    try:
        _force_utf8_console()  # must not raise
    finally:
        sys.stdout, sys.stderr = original_out, original_err


def test_a_stream_with_no_reconfigure_at_all_is_left_alone() -> None:
    original_out, original_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = object(), object()
    try:
        _force_utf8_console()
    finally:
        sys.stdout, sys.stderr = original_out, original_err


def test_a_real_subprocess_urdu_transcript_survives_the_decode(artifacts: dict) -> None:
    """The decode half, against a real process writing real UTF-8 bytes.

    ``text=True`` alone would decode this with cp1252 and raise, which is the
    original bug. Nothing here is mocked except the argv.
    """
    payload = "whisper_vitisai_encode: Vitis AI model inference completed.\n " + CODE_SWITCHED
    literal = payload.encode("unicode_escape").decode("ascii")
    script = f"import sys; sys.stdout.buffer.write('{literal}'.encode('utf-8'))"

    result = LocalWhisperBackend._run([sys.executable, "-c", script])

    assert result.returncode == 0
    assert CODE_SWITCHED in result.stdout
    # And the transcript the CLI hands upward is the speech, not the log line.
    assert clean_transcript(result.stdout) == CODE_SWITCHED


def test_an_urdu_transcript_reaches_a_cp1252_console_intact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """End to end: fake whisper output -> ``main`` -> a real cp1252 stream.

    This is the test that would have caught both bugs at once.
    """
    clip = tmp_path / "speech.wav"
    clip.write_bytes(b"fake wav")
    install_backends(monkeypatch, default=FakeBackend(text=f"  {CODE_SWITCHED}  "))
    forbid_recording(monkeypatch)

    console = cp1252_console()
    monkeypatch.setattr(sys, "stdout", console)
    monkeypatch.setattr(sys, "stderr", cp1252_console())

    assert main(["--clip", str(clip)]) == 0

    console.flush()
    printed = console.buffer.getvalue().decode("utf-8")
    assert CODE_SWITCHED in printed
    assert "(nothing recognised)" not in printed


def test_the_console_is_fixed_before_the_backend_is_ever_touched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Order matters: a transcript that arrives before the reconfigure still
    dies at the print."""
    order: list[str] = []

    def spy_console() -> None:
        order.append("reconfigure")

    def spy_default():
        order.append("backend")
        return FakeBackend()

    monkeypatch.setattr(try_stt, "_force_utf8_console", spy_console)
    monkeypatch.setattr(local_backend, "default_backend", spy_default)
    monkeypatch.setattr(local_backend, "LocalWhisperBackend", RecordingFactory())
    forbid_recording(monkeypatch)
    clip = tmp_path / "c.wav"
    clip.write_bytes(b"")

    main(["--clip", str(clip)])

    assert order == ["reconfigure", "backend"]


# ===========================================================================
# Language: the default is Urdu, not auto
# ===========================================================================


def test_with_no_flag_the_configured_language_is_used_not_auto(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``auto`` silently dropped the Urdu half of code-switched clips, so
    ``voice/config.py`` forces ``ur``. ``try_stt`` must not re-decide that."""
    monkeypatch.delenv(WHISPER_LANGUAGE_ENV, raising=False)
    # The real default backend, never run -- only asked what language it holds.
    assert local_backend.default_backend().language == "ur"

    default, factory, default_calls = install_backends(
        monkeypatch, default=FakeBackend(language="ur")
    )
    forbid_recording(monkeypatch)
    clip = tmp_path / "c.wav"
    clip.write_bytes(b"")

    assert main(["--clip", str(clip)]) == 0

    assert default_calls == ["default_backend"]
    assert factory.languages == [], "a language was chosen locally instead of from config"
    assert "(ur)" in capsys.readouterr().out


def test_the_language_flag_overrides_the_configured_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _default, factory, default_calls = install_backends(monkeypatch)
    forbid_recording(monkeypatch)
    clip = tmp_path / "c.wav"
    clip.write_bytes(b"")

    assert main(["--clip", str(clip), "--language", "en"]) == 0

    assert factory.languages == ["en"]
    assert default_calls == [], "the configured default was consulted despite --language"
    assert "(en)" in capsys.readouterr().out


def test_the_language_in_use_is_printed_so_a_wrong_one_is_visible(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    install_backends(monkeypatch, default=FakeBackend(language="hi"))
    forbid_recording(monkeypatch)
    clip = tmp_path / "c.wav"
    clip.write_bytes(b"")

    main(["--clip", str(clip)])

    assert "transcribing on the NPU (hi)" in capsys.readouterr().out


# ===========================================================================
# --compare
# ===========================================================================


def _compare_backends() -> list[FakeBackend]:
    return [FakeBackend(text="urdu pass"), FakeBackend(text="english pass")]


def test_compare_runs_every_pass_and_prints_every_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clip = tmp_path / "c.wav"
    clip.write_bytes(b"")
    default = FakeBackend(text="default pass")
    factory = RecordingFactory(*_compare_backends())
    install_backends(monkeypatch, default=default, factory=factory)
    forbid_recording(monkeypatch)

    assert main(["--clip", str(clip), "--compare"]) == 0

    out = capsys.readouterr().out
    for label in ("auto-detect", "forced Urdu", "forced English"):
        assert label in out
    assert "default pass" in out
    assert "urdu pass" in out
    assert "english pass" in out
    # The same clip through all three, not three takes of his voice.
    assert default.clips == [clip]
    assert [b.clips for b in factory.built] == [[clip], [clip]]


def test_one_failing_pass_does_not_swallow_the_others(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clip = tmp_path / "c.wav"
    clip.write_bytes(b"")
    factory = RecordingFactory(
        FakeBackend(raises=RuntimeError("whisper-cli exited 1: failed to load Vitis AI model")),
        FakeBackend(text="english survived"),
    )
    install_backends(monkeypatch, default=FakeBackend(text="auto survived"), factory=factory)
    forbid_recording(monkeypatch)

    assert main(["--clip", str(clip), "--compare"]) == 0

    out = capsys.readouterr().out
    assert "auto survived" in out
    assert "english survived" in out
    assert "(failed: RuntimeError: whisper-cli exited 1" in out


def test_compare_row_one_says_auto_detect_but_runs_the_configured_language(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Characterisation, not endorsement.

    The first row is labelled ``auto-detect`` but is produced by
    ``default_backend()``, whose language is ``DEFAULT_WHISPER_LANGUAGE``
    (``ur``) since 30 Aug 2026. So ``--compare`` currently runs Urdu twice and
    calls one of them auto. Recorded here so the label and the behaviour cannot
    drift apart unnoticed; see docs/tasks/voice-cli-tests-report.md.
    """
    monkeypatch.delenv(WHISPER_LANGUAGE_ENV, raising=False)
    clip = tmp_path / "c.wav"
    clip.write_bytes(b"")
    default = FakeBackend(language=local_backend.default_backend().language, text="row one")
    factory = RecordingFactory(*_compare_backends())
    install_backends(monkeypatch, default=default, factory=factory)
    forbid_recording(monkeypatch)

    main(["--clip", str(clip), "--compare"])

    assert factory.languages == ["ur", "en"]
    assert default.language == "ur", "the 'auto-detect' row is not auto-detecting"


def test_compare_removes_the_scratch_recording_unless_keep(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scratch = tmp_path / "scratch.wav"
    monkeypatch.setattr(try_stt, "scratch_clip_path", lambda: scratch)
    monkeypatch.setattr(try_stt, "record", FakeRecorder())
    factory = RecordingFactory(*_compare_backends())
    install_backends(monkeypatch, factory=factory)

    assert main(["--compare"]) == 0
    assert not scratch.exists()

    monkeypatch.setattr(try_stt, "record", FakeRecorder())
    install_backends(monkeypatch, factory=RecordingFactory(*_compare_backends()))
    assert main(["--compare", "--keep"]) == 0
    assert scratch.exists()
    assert f"kept: {scratch}" in capsys.readouterr().out


# ===========================================================================
# Failure paths -- each one must be loud
# ===========================================================================


def test_an_unavailable_backend_exits_one_and_names_the_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    install_backends(
        monkeypatch,
        default=FakeBackend(available=False, reason="NPU encoder cache missing: x.rai"),
    )
    forbid_recording(monkeypatch)

    assert main(["--clip", str(tmp_path / "anything.wav")]) == 1

    err = capsys.readouterr().err
    assert "local speech-to-text is not available" in err
    assert "NPU encoder cache missing" in err


def test_availability_is_checked_before_the_microphone_is_opened(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Six seconds of speech thrown away because the model was missing is the
    exact experience this ordering prevents."""
    install_backends(monkeypatch, default=FakeBackend(available=False, reason="not built"))
    forbid_recording(monkeypatch)

    assert main([]) == 1


def test_a_missing_clip_file_is_reported_and_exits_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    install_backends(monkeypatch)
    forbid_recording(monkeypatch)
    missing = tmp_path / "not-here.wav"

    assert main(["--clip", str(missing)]) == 1
    assert f"no such file: {missing}" in capsys.readouterr().err


def test_a_non_zero_whisper_exit_surfaces_as_a_loud_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, artifacts: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    """The real backend, a real non-zero exit, a fake subprocess.

    A silent ``(nothing recognised)`` here is the failure mode this pins
    against: the run must exit non-zero and say what whisper-cli said.
    """
    clip = tmp_path / "c.wav"
    clip.write_bytes(b"")
    failing = LocalWhisperBackend(
        **artifacts,
        runner=lambda _cmd: completed(
            "", returncode=1, stderr="loading\nfailed to load Vitis AI model\n"
        ),
    )
    monkeypatch.setattr(local_backend, "default_backend", lambda: failing)
    monkeypatch.setattr(local_backend, "LocalWhisperBackend", RecordingFactory())
    forbid_recording(monkeypatch)

    assert main(["--clip", str(clip)]) == 1

    captured = capsys.readouterr()
    assert "transcription failed: RuntimeError" in captured.err
    assert "failed to load Vitis AI model" in captured.err
    assert "(nothing recognised)" not in captured.out


def test_a_backend_exception_is_surfaced_with_its_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    install_backends(monkeypatch, default=FakeBackend(raises=OSError("device gone")))
    forbid_recording(monkeypatch)
    clip = tmp_path / "c.wav"
    clip.write_bytes(b"")

    assert main(["--clip", str(clip)]) == 1
    assert "transcription failed: OSError: device gone" in capsys.readouterr().err


def test_a_blank_transcript_says_nothing_recognised_and_still_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Silence is a result, not an error -- but it must not look like one."""
    install_backends(monkeypatch, default=FakeBackend(text="   \n  "))
    forbid_recording(monkeypatch)
    clip = tmp_path / "c.wav"
    clip.write_bytes(b"")

    assert main(["--clip", str(clip)]) == 0
    assert "(nothing recognised)" in capsys.readouterr().out


# ===========================================================================
# Recording and the scratch file
# ===========================================================================


def test_a_clip_argument_records_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    install_backends(monkeypatch)
    forbid_recording(monkeypatch)
    clip = tmp_path / "existing.wav"
    clip.write_bytes(b"")

    assert main(["--clip", str(clip)]) == 0
    assert clip.exists(), "an existing clip was deleted"


def test_the_seconds_and_device_flags_reach_the_recorder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scratch = tmp_path / "scratch.wav"
    recorder = FakeRecorder()
    monkeypatch.setattr(try_stt, "scratch_clip_path", lambda: scratch)
    monkeypatch.setattr(try_stt, "record", recorder)
    install_backends(monkeypatch)

    assert main(["--seconds", "9.5", "--device", "3", "--keep"]) == 0

    assert recorder.calls == [{"seconds": 9.5, "device": 3, "destination": scratch}]


def test_the_scratch_recording_is_removed_unless_keep_is_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scratch = tmp_path / "scratch.wav"
    monkeypatch.setattr(try_stt, "scratch_clip_path", lambda: scratch)
    monkeypatch.setattr(try_stt, "record", FakeRecorder())
    install_backends(monkeypatch)

    assert main([]) == 0
    assert not scratch.exists()


def test_keep_leaves_the_recording_and_says_where_it_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scratch = tmp_path / "scratch.wav"
    monkeypatch.setattr(try_stt, "scratch_clip_path", lambda: scratch)
    monkeypatch.setattr(try_stt, "record", FakeRecorder())
    install_backends(monkeypatch)

    assert main(["--keep"]) == 0
    assert scratch.exists()
    assert f"kept: {scratch}" in capsys.readouterr().out


def test_the_scratch_file_never_lands_in_the_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """It is his voice. It goes to a scratch directory, not into the tree."""
    resolved = scratch_clip_path().resolve()
    repo = Path(try_stt.__file__).resolve().parent.parent
    assert repo not in resolved.parents
    assert resolved.name == "jarvis-try-stt.wav"


def test_a_recorded_run_reports_the_real_time_ratio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ratio, not the raw seconds, is the number that says whether this can
    keep up with live speech."""
    scratch = tmp_path / "scratch.wav"
    monkeypatch.setattr(try_stt, "scratch_clip_path", lambda: scratch)
    monkeypatch.setattr(try_stt, "record", FakeRecorder(seconds=6.0))
    install_backends(monkeypatch)

    main([])

    assert "x real time" in capsys.readouterr().out


def test_a_supplied_clip_reports_seconds_and_no_ratio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    install_backends(monkeypatch)
    forbid_recording(monkeypatch)
    clip = tmp_path / "c.wav"
    clip.write_bytes(b"")

    main(["--clip", str(clip)])

    assert "x real time" not in capsys.readouterr().out


def test_record_captures_the_wakeword_format_and_writes_pcm16(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """whisper.cpp wants 16 kHz mono PCM, which is the wake-word format. If
    these drift apart the clip is silently resampled somewhere downstream."""
    calls: dict[str, dict] = {}

    class FakeSoundDevice:
        @staticmethod
        def rec(frames, **kwargs):
            calls["rec"] = {"frames": frames, **kwargs}
            return [0] * frames

        @staticmethod
        def wait() -> None:
            calls["wait"] = {}

    class FakeSoundFile:
        @staticmethod
        def write(destination, data, samplerate, **kwargs):
            calls["write"] = {
                "destination": destination,
                "samplerate": samplerate,
                "frames": len(data),
                **kwargs,
            }

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSoundDevice)
    monkeypatch.setitem(sys.modules, "soundfile", FakeSoundFile)
    monkeypatch.setattr(
        try_stt, "time", types.SimpleNamespace(sleep=lambda _s: None, monotonic=lambda: 0.0)
    )

    seconds = record(2.0, 7, tmp_path / "out.wav")

    assert seconds == 2.0
    assert calls["rec"]["frames"] == 2 * try_stt.RECORD_SAMPLE_RATE
    assert calls["rec"]["samplerate"] == try_stt.RECORD_SAMPLE_RATE
    assert calls["rec"]["channels"] == WAKEWORD_CHANNELS
    assert calls["rec"]["dtype"] == WAKEWORD_DTYPE
    assert calls["rec"]["device"] == 7
    assert calls["write"]["samplerate"] == try_stt.RECORD_SAMPLE_RATE
    assert calls["write"]["subtype"] == "PCM_16"
    assert "wait" in calls, "recording was read before the buffer finished filling"
    assert "SPEAK" in capsys.readouterr().out


def test_record_counts_the_user_in_before_it_captures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    slept: list[float] = []

    class FakeSoundDevice:
        @staticmethod
        def rec(frames, **_kwargs):
            return [0] * frames

        @staticmethod
        def wait() -> None:
            pass

    class FakeSoundFile:
        @staticmethod
        def write(*_args, **_kwargs) -> None:
            pass

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSoundDevice)
    monkeypatch.setitem(sys.modules, "soundfile", FakeSoundFile)
    monkeypatch.setattr(
        try_stt, "time", types.SimpleNamespace(sleep=slept.append, monotonic=lambda: 0.0)
    )

    record(1.0, None, tmp_path / "out.wav")

    out = capsys.readouterr().out
    assert len(slept) == 3, "the 3-2-1 countdown did not run"
    assert "3..." in out and "2..." in out and "1..." in out


# ===========================================================================
# Import hygiene
# ===========================================================================


def test_importing_the_module_pulls_in_no_audio_stack() -> None:
    """``voice/try_stt.py`` is imported by this suite on machines with no NPU
    and no microphone. Any top-level audio import would make that impossible.

    The audio modules are evicted alongside ours, then restored: asserting on a
    bare ``"soundfile" not in sys.modules`` would instead assert that nothing
    earlier in the session imported it, which other voice tests legitimately
    do. Same shape as the equivalent test in ``test_local_backend.py``.
    """
    import importlib

    names = ("voice.try_stt", "sounddevice", "soundfile")
    saved = {name: sys.modules[name] for name in names if name in sys.modules}
    for name in names:
        sys.modules.pop(name, None)
    try:
        module = importlib.import_module("voice.try_stt")
        assert module.main is not None
        assert "sounddevice" not in sys.modules
        assert "soundfile" not in sys.modules
    finally:
        sys.modules.update(saved)
