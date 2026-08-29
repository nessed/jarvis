"""Local Whisper STT on this laptop's Ryzen AI NPU, via the amd/whisper.cpp fork.

Blueprint 3.1 specifies the ``amd/whisper.cpp`` fork with NPU offload and
Whisper **large-v3** (Urdu/English is why: Parakeet is English/European only).
Both are decisions, not preferences, and this module consumes exactly those --
it never falls back to a CPU build or a smaller model on its own.

What is actually on disk, and where it came from
------------------------------------------------
``voice/whisper/`` holds four things, none of which are committed:

``src/``
    Clone of https://github.com/amd/whisper.cpp at ``b40e6c8``.
``src/build-vitisai/``
    CMake output of ``cmake -B build-vitisai -G "Visual Studio 17 2022" -A x64
    -DWHISPER_VITISAI=ON``. ``whisper-cli.exe`` lands in
    ``bin/Release/`` next to the FlexML runtime DLLs.
``flexmlrt/``
    FlexML runtime 1.7.0 for Windows -- the VitisAI inference engine the fork
    links against as ``flexmlrt::flexmlrt``. Without it ``find_package(FlexmlRT
    REQUIRED)`` fails and the NPU path cannot even configure.
``models/``
    ``ggml-large-v3.bin`` (the weights) **and**
    ``ggml-large-v3-encoder-vitisai.rai`` (AMD's precompiled NPU encoder
    graph). Both are required; see below.

Why the ``.rai`` file is load-bearing
-------------------------------------
``src/whisper.cpp`` derives the cache path from the model path by stripping the
extension and appending ``-encoder-vitisai.rai``
(``whisper_get_vitisai_path_encoder_cache``, src/whisper.cpp:3367). In a
``WHISPER_USE_VITISAI`` build, ``whisper_init_state`` **returns nullptr** when
that file will not load (src/whisper.cpp:3489-3495) -- the CLI aborts rather
than quietly running the encoder on the CPU.

That is the useful property for us: a transcript out of this binary is proof
the encoder ran on the NPU. There is no silent CPU fallback to mistake it for.
``availability()`` therefore checks the cache file explicitly, so a missing
``.rai`` is reported as "not available" here instead of surfacing as a runtime
crash inside the benchmark.

Interface
---------
Two things, per the lane brief:

* the backend is **callable** -- ``backend(clip)`` returns
  ``(transcript, latency_seconds)``, a plain tuple;
* ``availability()`` returns cleanly and never raises when the build, the
  weights or the encoder cache are missing.

It also satisfies ``voice.benchmark_stt.SttBackend`` (``name``,
``availability()``, ``transcribe(clip) -> str``) so the other lane's benchmark
can hold one of these without changing.

Nothing here imports an audio library, and importing this module never touches
the binary, the model or a device.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, NamedTuple, Sequence

from voice.config import (
    WHISPER_CPP_BIN_ENV,
    WHISPER_MODEL_ENV,
    whisper_cpp_binary,
    whisper_language,
    whisper_model_path,
)

#: ``voice/whisper``. Every artifact below is resolved relative to this, so the
#: backend works from any working directory.
PACKAGE_DIR = Path(__file__).resolve().parent

#: Where ``cmake --build build-vitisai --config Release`` puts the CLI.
DEFAULT_BINARY = PACKAGE_DIR / "src" / "build-vitisai" / "bin" / "Release" / "whisper-cli.exe"

#: Whisper large-v3 in ggml format, as the built binary consumes it.
DEFAULT_MODEL = PACKAGE_DIR / "models" / "ggml-large-v3.bin"

#: FlexML runtime DLLs. They must be resolvable when the CLI starts; the build
#: step copies them next to the binary, and :func:`subprocess_env` puts this
#: directory on ``PATH`` as well so a stale copy cannot silently win.
FLEXMLRT_LIB_DIR = PACKAGE_DIR / "flexmlrt" / "lib"

#: src/whisper.cpp:3373 -- ``path_bin += "-encoder-vitisai.rai"``.
ENCODER_CACHE_SUFFIX = "-encoder-vitisai.rai"


class Transcription(NamedTuple):
    """What one transcription produced, and how long it took.

    A ``NamedTuple`` so ``transcript, latency = backend(clip)`` works exactly
    as the lane brief specifies, while still being readable at the call site.
    """

    text: str
    latency_seconds: float


@dataclass(frozen=True)
class Availability:
    """Whether the local runtime can run here, and if not, precisely why.

    Mirrors ``voice.benchmark_stt.Availability`` field for field so the other
    lane's table renders a row from this without a shim.
    """

    available: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.available


class LocalBackendUnavailable(RuntimeError):
    """Raised when a transcription is attempted with a missing artifact."""


def encoder_cache_path(model: Path) -> Path:
    """The ``.rai`` NPU encoder cache the fork looks for beside ``model``.

    Reimplements ``whisper_get_vitisai_path_encoder_cache``
    (src/whisper.cpp:3367-3376) exactly, including its "strip everything after
    the last dot" behaviour, so this module agrees with the binary rather than
    guessing a naming convention.
    """
    text = str(model)
    pos = text.rfind(".")
    if pos != -1:
        text = text[:pos]
    return Path(text + ENCODER_CACHE_SUFFIX)


def subprocess_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for the CLI, with the FlexML runtime on ``PATH``.

    ``flexmlrt.dll`` is copied next to ``whisper-cli.exe`` at build time, which
    is normally enough. Prepending the runtime's own ``lib`` directory as well
    means a partial build -- binary present, DLL not staged -- still runs
    instead of dying with a Windows loader error that says nothing useful.
    """
    env = dict(os.environ if base is None else base)
    if FLEXMLRT_LIB_DIR.is_dir():
        existing = env.get("PATH", "")
        lib = str(FLEXMLRT_LIB_DIR)
        if lib not in existing.split(os.pathsep):
            env["PATH"] = f"{lib}{os.pathsep}{existing}" if existing else lib
    return env


#: The fork logs to **stdout**, not stderr, once per encoder run:
#:
#:     src/vitisai/whisper-vitisai-encoder.cpp:197
#:     std::fprintf(stdout, "%s: Vitis AI model inference completed.\n", __func__);
#:
#: Observed for real -- ``whisper-cli ... 2>/dev/null`` on this build emits two
#: of these above the transcript. Every other whisper.cpp log goes to stderr,
#: but they all share this shape, so the filter matches the family rather than
#: that one string. A ``-nt`` transcript line always begins with a space, so a
#: line that begins with ``whisper_`` at column zero is never speech.
LOG_LINE_PREFIX = "whisper_"


def clean_transcript(raw: str) -> str:
    """Collapse whisper-cli's ``-nt`` stdout into one line of text.

    Two jobs. First, drop the binary's own log lines -- see
    :data:`LOG_LINE_PREFIX`; without this the "transcript" starts with
    ``whisper_vitisai_encode: Vitis AI model inference completed.``

    Second, join the remaining segment lines. With ``-nt`` the CLI prints one
    line per decoded segment, each with a leading space. Joining them is what a
    caller means by "the transcript"; keeping the raw layout would make two
    runs of the same clip compare unequal for cosmetic reasons.

    ``[BLANK_AUDIO]`` and similar markers are left in deliberately -- they are
    the binary telling us it heard nothing, which is information.
    """
    kept: list[str] = []
    for line in (raw or "").splitlines():
        if line.startswith(LOG_LINE_PREFIX) and ": " in line:
            continue
        stripped = line.strip()
        if stripped:
            kept.append(stripped)
    return " ".join(kept)


def whisper_cli_command(
    binary: Path,
    model: Path,
    clip: Path,
    *,
    language: str,
    extra_args: Sequence[str] = (),
) -> list[str]:
    """The argv this lane's binary is invoked with.

    These are the flags ``voice/benchmark_stt.whisper_cpp_command`` already
    assumes (``-m``, ``-f``, ``-l``, ``-nt``), verified against
    ``whisper-cli --help`` from the build this lane produced. They are kept in
    the same order so the two lanes are trivially diffable.
    """
    return [
        str(binary),
        "-m",
        str(model),
        "-f",
        str(clip),
        "-l",
        language,
        "-nt",  # no timestamps: the transcript, not an SRT
        *extra_args,
    ]


class LocalWhisperBackend:
    """whisper.cpp with the encoder offloaded to the Ryzen AI NPU.

    Resolution order for the binary and the model is: explicit constructor
    argument, then the ``JARVIS_WHISPER_*`` environment variable, then this
    lane's own build output. The env vars come second rather than first so the
    thing works out of the box after a build, and third-party overrides still
    win over the default; ``voice/config.py`` deliberately has no default path
    guess, and this is where that default lives instead.
    """

    name = "whisper.cpp (local, NPU)"

    def __init__(
        self,
        *,
        binary: Path | None = None,
        model: Path | None = None,
        language: str | None = None,
        extra_args: Sequence[str] = (),
        runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
        timer: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._binary = binary if binary is not None else (whisper_cpp_binary() or DEFAULT_BINARY)
        self._model = model if model is not None else (whisper_model_path() or DEFAULT_MODEL)
        self._language = language if language is not None else whisper_language()
        self._extra_args = tuple(extra_args)
        self._runner = runner or self._run
        self._timer = timer

    # -- introspection -----------------------------------------------------

    @property
    def binary(self) -> Path:
        """The whisper-cli executable this backend will run."""
        return self._binary

    @property
    def model(self) -> Path:
        """The ggml weights this backend will load."""
        return self._model

    @property
    def encoder_cache(self) -> Path:
        """The ``.rai`` NPU encoder cache required alongside :attr:`model`."""
        return encoder_cache_path(self._model)

    @property
    def language(self) -> str:
        """Language hint passed to the CLI; ``auto`` unless overridden."""
        return self._language

    def command(self, clip: Path) -> list[str]:
        """The exact argv used for ``clip``. Useful in reports and failures."""
        return whisper_cli_command(
            self._binary,
            self._model,
            clip,
            language=self._language,
            extra_args=self._extra_args,
        )

    # -- availability ------------------------------------------------------

    def availability(self) -> Availability:
        """Can this run here? Never raises, never touches the NPU.

        Each missing artifact names the environment variable or the build step
        that fixes it, because "not available" with no reason is what makes
        someone re-run a two-hour build to find out which file was missing.
        """
        if not self._binary.exists():
            return Availability(
                False,
                f"whisper-cli not built: {self._binary} does not exist "
                f"(build it, or point {WHISPER_CPP_BIN_ENV} at another copy)",
            )
        if not self._model.exists():
            return Availability(
                False,
                f"Whisper large-v3 weights missing: {self._model} does not exist "
                f"(download them, or point {WHISPER_MODEL_ENV} at another copy)",
            )
        cache = self.encoder_cache
        if not cache.exists():
            return Availability(
                False,
                f"NPU encoder cache missing: {cache} does not exist. "
                "A WHISPER_VITISAI build aborts without it rather than falling "
                "back to CPU, so this is fatal, not slow.",
            )
        return Availability(True)

    def is_available(self) -> bool:
        """``True`` when every artifact needed to transcribe is present."""
        return self.availability().available

    # -- transcription -----------------------------------------------------

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            env=subprocess_env(),
        )

    def transcribe_timed(self, clip: Path) -> Transcription:
        """Transcribe ``clip``, returning the text and the wall-clock seconds.

        The timer wraps the whole subprocess, model load included. That is the
        number blueprint 3.2 asks Ali to judge -- how long he waits after
        speaking -- not the model's internal encode time.
        """
        state = self.availability()
        if not state.available:
            raise LocalBackendUnavailable(state.reason)

        command = self.command(Path(clip))
        started = self._timer()
        completed = self._runner(command)
        latency = self._timer() - started

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip().splitlines()
            tail = stderr[-1] if stderr else "no stderr"
            raise RuntimeError(f"whisper-cli exited {completed.returncode}: {tail}")

        return Transcription(clean_transcript(completed.stdout), latency)

    #: ``transcript, latency = backend(clip)`` -- the brief's callable shape.
    __call__ = transcribe_timed

    def transcribe(self, clip: Path) -> str:
        """Transcript only. Satisfies ``voice.benchmark_stt.SttBackend``."""
        return self.transcribe_timed(clip).text


# ---------------------------------------------------------------------------
# Module-level convenience: the common case is one default-configured backend.
# ---------------------------------------------------------------------------


def default_backend() -> LocalWhisperBackend:
    """A backend wired to this lane's build output and env overrides."""
    return LocalWhisperBackend()


def is_available() -> bool:
    """``True`` if the local NPU runtime can transcribe on this machine."""
    return default_backend().is_available()


def transcribe(clip: Path) -> Transcription:
    """Transcribe ``clip`` with the default backend."""
    return default_backend()(Path(clip))


def main(argv: Sequence[str] | None = None) -> int:
    """Check availability, or transcribe one clip and print the timing.

    Exists so the runtime can be proved from a shell without going through the
    benchmark, which needs a ~10 second clip and a table.

        .venv/Scripts/python.exe -m voice.whisper.local_backend --check
        .venv/Scripts/python.exe -m voice.whisper.local_backend --clip x.wav
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--clip", type=Path, help="audio file to transcribe")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report availability and the resolved paths, then exit",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="language hint for whisper-cli (default: JARVIS_WHISPER_LANGUAGE, else auto)",
    )
    args = parser.parse_args(argv)

    backend = LocalWhisperBackend(language=args.language)
    state = backend.availability()

    if args.check or args.clip is None:
        print(f"binary:        {backend.binary}")
        print(f"model:         {backend.model}")
        print(f"encoder cache: {backend.encoder_cache}")
        print(f"language:      {backend.language}")
        print(f"available:     {state.available}")
        if not state.available:
            print(f"reason:        {state.reason}")
            return 3
        if args.clip is None:
            return 0

    if not state.available:
        print(f"not available: {state.reason}", file=sys.stderr)
        return 3

    result = backend(args.clip)
    print(f"latency: {result.latency_seconds:.2f}s")
    print(f"transcript: {result.text}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
