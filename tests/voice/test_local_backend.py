"""Tests for the local NPU Whisper backend.

Every test here runs against fakes. Nothing in this file needs the built
``whisper-cli.exe``, the 3 GB large-v3 weights, the 700 MB ``.rai`` encoder
cache, the FlexML runtime, the NPU, or a microphone -- the offline suite has to
stay green on a machine where none of that exists.

The one real artifact any test touches is a ``tmp_path`` file it created
itself, used only so ``Path.exists()`` has something true to say.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from voice import benchmark_stt
from voice.config import WHISPER_CPP_BIN_ENV, WHISPER_LANGUAGE_ENV, WHISPER_MODEL_ENV
from voice.whisper import local_backend
from voice.whisper.local_backend import (
    Availability,
    LocalBackendUnavailable,
    LocalWhisperBackend,
    Transcription,
    clean_transcript,
    encoder_cache_path,
    main,
    subprocess_env,
    whisper_cli_command,
)


def completed(stdout: str = "", *, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["whisper-cli"], returncode=returncode, stdout=stdout, stderr=stderr)


class FakeRunner:
    """Stands in for ``subprocess.run``. Records argv, never spawns anything."""

    def __init__(self, result: subprocess.CompletedProcess | None = None) -> None:
        self.result = result if result is not None else completed(" hello there\n")
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess:
        self.commands.append(list(command))
        return self.result


class ExplodingRunner:
    """Fails the test if the backend ever tries to run the binary."""

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess:  # pragma: no cover
        raise AssertionError(f"the binary must not be invoked here: {command}")


@pytest.fixture
def artifacts(tmp_path: Path) -> dict[str, Path]:
    """A binary, weights and a matching ``.rai`` cache, all present."""
    binary = tmp_path / "whisper-cli.exe"
    model = tmp_path / "ggml-large-v3.bin"
    binary.write_text("not really an exe")
    model.write_text("not really a model")
    encoder_cache_path(model).write_text("not really a graph")
    return {"binary": binary, "model": model}


@pytest.fixture(autouse=True)
def no_ambient_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """This machine has the real build installed. Never let it leak into a test."""
    for name in (WHISPER_CPP_BIN_ENV, WHISPER_MODEL_ENV, WHISPER_LANGUAGE_ENV):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# encoder_cache_path: must agree with the C++, not with a convention we like
# ---------------------------------------------------------------------------


def test_the_cache_path_replaces_the_extension_like_the_fork_does():
    # src/whisper.cpp:3367 strips after the last '.' then appends the suffix.
    assert encoder_cache_path(Path("models/ggml-large-v3.bin")) == Path("models/ggml-large-v3-encoder-vitisai.rai")


def test_a_model_filename_without_an_extension_still_gets_a_cache_path():
    assert encoder_cache_path(Path("ggml-large-v3")) == Path("ggml-large-v3-encoder-vitisai.rai")


def test_only_the_last_dot_is_stripped():
    assert encoder_cache_path(Path("ggml-large-v3.q5_0.bin")).name == "ggml-large-v3.q5_0-encoder-vitisai.rai"


# ---------------------------------------------------------------------------
# availability: never raises, and always says which artifact is missing
# ---------------------------------------------------------------------------


def test_a_missing_binary_is_unavailable_and_names_the_env_var(tmp_path: Path):
    backend = LocalWhisperBackend(binary=tmp_path / "nope.exe", model=tmp_path / "m.bin")
    state = backend.availability()
    assert state.available is False
    assert WHISPER_CPP_BIN_ENV in state.reason


def test_a_missing_model_is_unavailable_and_names_the_env_var(tmp_path: Path):
    binary = tmp_path / "whisper-cli.exe"
    binary.write_text("x")
    state = LocalWhisperBackend(binary=binary, model=tmp_path / "missing.bin").availability()
    assert state.available is False
    assert WHISPER_MODEL_ENV in state.reason


def test_a_missing_rai_cache_is_unavailable_because_the_build_aborts_without_it(tmp_path: Path):
    binary = tmp_path / "whisper-cli.exe"
    model = tmp_path / "ggml-large-v3.bin"
    binary.write_text("x")
    model.write_text("x")
    # deliberately no encoder cache beside it
    state = LocalWhisperBackend(binary=binary, model=model).availability()
    assert state.available is False
    assert "ggml-large-v3-encoder-vitisai.rai" in state.reason
    assert "CPU" in state.reason  # says why it is fatal rather than merely slow


def test_everything_present_is_available_with_no_reason(artifacts):
    state = LocalWhisperBackend(**artifacts).availability()
    assert state.available is True
    assert state.reason == ""


def test_availability_is_truthy_and_falsy_directly():
    assert bool(Availability(True)) is True
    assert bool(Availability(False, "because")) is False


def test_is_available_is_the_same_answer(artifacts, tmp_path: Path):
    assert LocalWhisperBackend(**artifacts).is_available() is True
    assert LocalWhisperBackend(binary=tmp_path / "no.exe", model=tmp_path / "no.bin").is_available() is False


def test_checking_availability_never_runs_the_binary(artifacts):
    LocalWhisperBackend(**artifacts, runner=ExplodingRunner()).availability()


# ---------------------------------------------------------------------------
# argv: these flags are what the sibling lane's benchmark already assumes
# ---------------------------------------------------------------------------


def test_the_command_uses_the_flags_the_built_cli_accepts(artifacts):
    backend = LocalWhisperBackend(**artifacts, language="auto")
    command = backend.command(Path("clip.wav"))
    assert command[0] == str(artifacts["binary"])
    assert command[1:] == ["-m", str(artifacts["model"]), "-f", "clip.wav", "-l", "auto", "-nt"]


def test_extra_args_are_appended_after_the_standard_flags(artifacts):
    backend = LocalWhisperBackend(**artifacts, language="ur", extra_args=("-t", "4"))
    assert backend.command(Path("c.wav"))[-5:] == ["-l", "ur", "-nt", "-t", "4"]


def test_the_pure_command_builder_matches_the_benchmark_lanes_builder(tmp_path: Path):
    # voice/benchmark_stt.py owns whisper_cpp_command; this lane owns the binary
    # it describes. If they ever disagree the benchmark silently mis-invokes.
    binary, model, clip = tmp_path / "b.exe", tmp_path / "m.bin", tmp_path / "c.wav"
    mine = whisper_cli_command(binary, model, clip, language="auto")
    theirs = benchmark_stt.whisper_cpp_command(binary, model, clip, language="auto")
    assert mine == theirs


# ---------------------------------------------------------------------------
# path and language resolution
# ---------------------------------------------------------------------------


def test_an_explicit_path_beats_the_environment(artifacts, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(WHISPER_CPP_BIN_ENV, r"C:\somewhere\else.exe")
    assert LocalWhisperBackend(**artifacts).binary == artifacts["binary"]


def test_the_environment_beats_this_lanes_build_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    override = tmp_path / "other-whisper-cli.exe"
    monkeypatch.setenv(WHISPER_CPP_BIN_ENV, str(override))
    monkeypatch.setenv(WHISPER_MODEL_ENV, str(tmp_path / "other.bin"))
    backend = LocalWhisperBackend()
    assert backend.binary == override
    assert backend.model == tmp_path / "other.bin"


def test_with_nothing_set_it_falls_back_to_this_lanes_build_output():
    backend = LocalWhisperBackend()
    assert backend.binary == local_backend.DEFAULT_BINARY
    assert backend.model == local_backend.DEFAULT_MODEL


def test_the_language_defaults_to_auto_not_english(artifacts):
    # Blueprint 2: Urdu/English stays on large-v3 precisely because it is not
    # an English-only model. Hardcoding "en" here would throw that away.
    assert LocalWhisperBackend(**artifacts).language == "auto"


def test_the_language_env_var_is_honoured(artifacts, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(WHISPER_LANGUAGE_ENV, "ur")
    assert LocalWhisperBackend(**artifacts).language == "ur"


def test_the_encoder_cache_property_tracks_the_model(artifacts):
    backend = LocalWhisperBackend(**artifacts)
    assert backend.encoder_cache == encoder_cache_path(artifacts["model"])


# ---------------------------------------------------------------------------
# transcription
# ---------------------------------------------------------------------------


def test_calling_the_backend_returns_a_transcript_and_a_latency(artifacts):
    runner = FakeRunner(completed(" hello there\n"))
    backend = LocalWhisperBackend(**artifacts, runner=runner)
    transcript, latency = backend(Path("clip.wav"))
    assert transcript == "hello there"
    assert isinstance(latency, float)


def test_the_result_is_also_readable_by_name(artifacts):
    backend = LocalWhisperBackend(**artifacts, runner=FakeRunner(completed("hi")))
    result = backend.transcribe_timed(Path("clip.wav"))
    assert isinstance(result, Transcription)
    assert result.text == "hi"


def test_the_latency_is_measured_by_the_injected_timer(artifacts):
    ticks = iter([100.0, 107.5])
    backend = LocalWhisperBackend(**artifacts, runner=FakeRunner(), timer=lambda: next(ticks))
    assert backend(Path("clip.wav")).latency_seconds == pytest.approx(7.5)


def test_transcribe_returns_only_the_text(artifacts):
    backend = LocalWhisperBackend(**artifacts, runner=FakeRunner(completed("just words")))
    assert backend.transcribe(Path("clip.wav")) == "just words"


def test_a_nonzero_exit_raises_with_the_last_stderr_line(artifacts):
    runner = FakeRunner(completed("", returncode=1, stderr="loading\nfailed to load Vitis AI model\n"))
    backend = LocalWhisperBackend(**artifacts, runner=runner)
    with pytest.raises(RuntimeError, match="failed to load Vitis AI model"):
        backend(Path("clip.wav"))


def test_a_nonzero_exit_with_no_stderr_still_raises_readably(artifacts):
    backend = LocalWhisperBackend(**artifacts, runner=FakeRunner(completed("", returncode=3)))
    with pytest.raises(RuntimeError, match="no stderr"):
        backend(Path("clip.wav"))


def test_transcribing_without_the_artifacts_raises_instead_of_running_anything(tmp_path: Path):
    backend = LocalWhisperBackend(
        binary=tmp_path / "gone.exe",
        model=tmp_path / "gone.bin",
        runner=ExplodingRunner(),
    )
    with pytest.raises(LocalBackendUnavailable, match=WHISPER_CPP_BIN_ENV):
        backend(Path("clip.wav"))


def test_the_clip_reaches_the_command_that_is_actually_run(artifacts):
    runner = FakeRunner()
    LocalWhisperBackend(**artifacts, runner=runner)(Path("some/clip.wav"))
    assert runner.commands[0][runner.commands[0].index("-f") + 1] == str(Path("some/clip.wav"))


# ---------------------------------------------------------------------------
# transcript cleanup
# ---------------------------------------------------------------------------


def test_segment_lines_are_joined_into_one_transcript():
    assert clean_transcript("  first part\n  second part\n") == "first part second part"


def test_blank_lines_are_dropped():
    assert clean_transcript("\n\n  only line  \n\n") == "only line"


def test_empty_output_is_an_empty_transcript():
    assert clean_transcript("") == ""
    assert clean_transcript(None) == ""


def test_a_blank_audio_marker_is_kept_because_it_is_information():
    assert clean_transcript(" [BLANK_AUDIO]\n") == "[BLANK_AUDIO]"


def test_the_forks_stdout_log_line_is_not_part_of_the_transcript():
    # src/vitisai/whisper-vitisai-encoder.cpp:197 fprintf's this to *stdout*,
    # once per encoder run. Real output from this build, verbatim.
    raw = (
        "whisper_vitisai_encode: Vitis AI model inference completed.\n"
        "whisper_vitisai_encode: Vitis AI model inference completed.\n"
        "\n"
        " And so my fellow Americans, ask not what your country can do for you.\n"
    )
    assert clean_transcript(raw) == "And so my fellow Americans, ask not what your country can do for you."


def test_other_whisper_log_lines_are_dropped_too():
    assert clean_transcript("whisper_init_state: Vitis AI model loaded\n hello\n") == "hello"


def test_speech_that_merely_mentions_whisper_is_kept():
    # Transcript lines are printed with a leading space, so they never collide
    # with a log line at column zero.
    assert clean_transcript(" whisper_init_state: is a function name\n") == "whisper_init_state: is a function name"


# ---------------------------------------------------------------------------
# the FlexML runtime has to be findable by the loader
# ---------------------------------------------------------------------------


def test_the_flexml_lib_dir_is_prepended_to_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    lib = tmp_path / "flexmlrt" / "lib"
    lib.mkdir(parents=True)
    monkeypatch.setattr(local_backend, "FLEXMLRT_LIB_DIR", lib)
    env = subprocess_env({"PATH": r"C:\Windows"})
    assert env["PATH"].split(os.pathsep)[0] == str(lib)
    assert r"C:\Windows" in env["PATH"]


def test_the_flexml_lib_dir_is_not_added_twice(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    lib = tmp_path / "lib"
    lib.mkdir()
    monkeypatch.setattr(local_backend, "FLEXMLRT_LIB_DIR", lib)
    env = subprocess_env({"PATH": str(lib)})
    assert env["PATH"].split(os.pathsep).count(str(lib)) == 1


def test_a_missing_flexml_dir_leaves_path_alone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(local_backend, "FLEXMLRT_LIB_DIR", tmp_path / "not-here")
    assert subprocess_env({"PATH": r"C:\Windows"})["PATH"] == r"C:\Windows"


def test_an_empty_path_is_replaced_rather_than_prefixed_with_a_separator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    lib = tmp_path / "lib"
    lib.mkdir()
    monkeypatch.setattr(local_backend, "FLEXMLRT_LIB_DIR", lib)
    assert subprocess_env({"PATH": ""})["PATH"] == str(lib)


# ---------------------------------------------------------------------------
# the shape voice/benchmark_stt.py holds
# ---------------------------------------------------------------------------


def test_this_backend_satisfies_the_benchmarks_backend_protocol(artifacts):
    backend = LocalWhisperBackend(**artifacts, runner=FakeRunner(completed("ok")))
    results = benchmark_stt.run_benchmark([backend], Path("clip.wav"))
    assert len(results) == 1
    assert results[0].available is True
    assert results[0].transcript == "ok"


def test_an_unavailable_local_backend_becomes_a_clean_benchmark_row(tmp_path: Path):
    backend = LocalWhisperBackend(binary=tmp_path / "no.exe", model=tmp_path / "no.bin")
    (result,) = benchmark_stt.run_benchmark([backend], Path("clip.wav"))
    assert result.available is False
    assert WHISPER_CPP_BIN_ENV in result.reason
    assert result.error is None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_check_reports_every_resolved_path(monkeypatch: pytest.MonkeyPatch, artifacts, capsys):
    monkeypatch.setenv(WHISPER_CPP_BIN_ENV, str(artifacts["binary"]))
    monkeypatch.setenv(WHISPER_MODEL_ENV, str(artifacts["model"]))
    assert main(["--check"]) == 0
    out = capsys.readouterr().out
    assert str(artifacts["binary"]) in out
    assert str(artifacts["model"]) in out
    assert "-encoder-vitisai.rai" in out
    assert "available:     True" in out


def test_check_exits_nonzero_and_explains_when_the_build_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
):
    monkeypatch.setenv(WHISPER_CPP_BIN_ENV, str(tmp_path / "absent.exe"))
    monkeypatch.setenv(WHISPER_MODEL_ENV, str(tmp_path / "absent.bin"))
    assert main(["--check"]) == 3
    assert "reason:" in capsys.readouterr().out


def test_no_arguments_at_all_reports_status_rather_than_transcribing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
):
    monkeypatch.setenv(WHISPER_CPP_BIN_ENV, str(tmp_path / "absent.exe"))
    monkeypatch.setenv(WHISPER_MODEL_ENV, str(tmp_path / "absent.bin"))
    assert main([]) == 3
    assert "available:     False" in capsys.readouterr().out


def test_transcribing_a_clip_prints_the_latency_and_the_text(
    monkeypatch: pytest.MonkeyPatch, artifacts, capsys
):
    monkeypatch.setenv(WHISPER_CPP_BIN_ENV, str(artifacts["binary"]))
    monkeypatch.setenv(WHISPER_MODEL_ENV, str(artifacts["model"]))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed(" from the fake\n"))
    assert main(["--clip", "clip.wav"]) == 0
    out = capsys.readouterr().out
    assert "transcript: from the fake" in out
    assert "latency:" in out


# ---------------------------------------------------------------------------
# import hygiene
# ---------------------------------------------------------------------------


def test_importing_the_package_pulls_in_no_audio_stack_and_runs_nothing(monkeypatch: pytest.MonkeyPatch):
    import importlib
    import sys

    # A fresh import must not shell out, and must not drag in an audio library:
    # the offline suite imports this on machines with neither.
    #
    # The audio modules are evicted alongside ours. Asserting on a bare
    # `"soundfile" not in sys.modules` would instead assert that *nothing
    # earlier in the whole session* imported it -- which tests/voice/test_speak.py
    # legitimately does, since encoding real OGG/Opus requires it. That made
    # this test pass alone and fail in a full run. Evicting first means the
    # only thing that can put them back is the import under test.
    monkeypatch.setattr(subprocess, "run", ExplodingRunner())
    names = ("voice.whisper", "voice.whisper.local_backend", "sounddevice", "soundfile")
    saved = {name: sys.modules[name] for name in names if name in sys.modules}
    for name in names:
        sys.modules.pop(name, None)
    try:
        module = importlib.import_module("voice.whisper.local_backend")
        assert module.LocalWhisperBackend is not None
        assert "sounddevice" not in sys.modules
        assert "soundfile" not in sys.modules
    finally:
        sys.modules.update(saved)


def test_the_package_init_does_not_pull_in_the_submodule(monkeypatch: pytest.MonkeyPatch):
    # Otherwise `python -m voice.whisper.local_backend` warns on every run.
    import importlib
    import sys

    names = ("voice.whisper", "voice.whisper.local_backend")
    saved = {name: sys.modules[name] for name in names if name in sys.modules}
    for name in names:
        sys.modules.pop(name, None)
    try:
        importlib.import_module("voice.whisper")
        assert "voice.whisper.local_backend" not in sys.modules
    finally:
        sys.modules.update(saved)
