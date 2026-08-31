"""Blueprint 3.1: report STT latency on a ~10 second Urdu/English clip.

This produces the number blueprint 3.2 asks Ali to judge - "NPU latency fine,
or STT flips to Groq Whisper". It times each *available* backend over the same
clip and prints latency, real-time factor and the transcript side by side, so
the decision is made against measured wall clock rather than a feeling.

Usage (run as a module so the repo root is on sys.path):
    .venv/Scripts/python.exe -m voice.benchmark_stt --clip path/to/clip.wav
    .venv/Scripts/python.exe -m voice.benchmark_stt --clip clip.wav --runs 3
    .venv/Scripts/python.exe -m voice.benchmark_stt --clip clip.wav --json

A backend is a small pluggable object: ``availability()`` says whether its
runtime exists on this machine, ``transcribe()`` does the work. A backend whose
runtime is missing reports that cleanly and the benchmark still runs and still
prints a table - it does not crash, and it does not silently drop the row.

**Only backends whose runtime actually exists here are implemented.** Today
that is whisper.cpp, and only once the ``whisper-npu-build`` lane has produced
the binary and the large-v3 weights; until then it reports "not available" with
the environment variable that would fix it.

There is deliberately **no Groq Whisper backend**. ``docs/plan.md`` records
``stt-backends`` as an open Class C decision: ``router/routing.py`` is
chat-completions-only, ``TASK_PROFILES`` has no audio profile, and Groq STT is
a different endpoint shape. Whether voice owns its own audio client or the
router grows an audio lane is not this lane's call, so the seam is left open
and unfilled. Adding a ``GroqWhisperBackend`` here later is a one-class change
that touches nothing else in this module.

No audio library is imported at module import time.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence

from voice.config import (
    WHISPER_CPP_BIN_ENV,
    WHISPER_MODEL_ENV,
    whisper_cpp_binary,
    whisper_language,
    whisper_model_path,
)

#: Blueprint 3.1 specifies a 10-second clip. Anything far off that makes the
#: latency number hard to compare, so the benchmark says so rather than
#: quietly reporting a figure measured on three seconds of audio.
TARGET_CLIP_SECONDS = 10.0
CLIP_SECONDS_TOLERANCE = 3.0


@dataclass(frozen=True)
class Availability:
    """Whether a backend can run here, and if not, why not."""

    available: bool
    reason: str = ""


@dataclass(frozen=True)
class BackendResult:
    """One row of the benchmark table."""

    name: str
    available: bool
    reason: str = ""
    latencies: tuple[float, ...] = ()
    transcript: str | None = None
    error: str | None = None

    @property
    def latency_seconds(self) -> float | None:
        """Median latency across runs; ``None`` if the backend never ran."""
        if not self.latencies:
            return None
        return statistics.median(self.latencies)

    def realtime_factor(self, clip_seconds: float | None) -> float | None:
        """Latency divided by clip length. Below 1.0 is faster than real time."""
        latency = self.latency_seconds
        if latency is None or not clip_seconds:
            return None
        return latency / clip_seconds


class SttBackend(Protocol):
    """A timed speech-to-text implementation."""

    name: str

    def availability(self) -> Availability:
        ...

    def transcribe(self, clip: Path) -> str:
        ...


def whisper_cpp_command(
    binary: Path,
    model: Path,
    clip: Path,
    *,
    language: str,
    extra_args: Sequence[str] = (),
) -> list[str]:
    """The argv used to invoke whisper.cpp.

    Kept as its own pure function because the ``whisper-npu-build`` lane owns
    the binary and therefore owns which flags it actually accepts. If its CLI
    differs, this is the single place that changes - and ``--whisper-arg`` on
    the command line covers the gap without an edit.
    """
    return [
        str(binary),
        "-m",
        str(model),
        "-f",
        str(clip),
        "-l",
        language,
        "-nt",  # no timestamps: we want the transcript, not an SRT
        *extra_args,
    ]


class WhisperCppBackend:
    """Local whisper.cpp with NPU offload, per blueprint §2 and 3.1.

    The binary and the large-v3 weights are the ``whisper-npu-build`` lane's
    artifacts. This backend only consumes them, located by environment
    variable, and reports itself unavailable - never raising - when they are
    not there yet.
    """

    name = "whisper.cpp (local)"

    def __init__(
        self,
        *,
        binary: Path | None = None,
        model: Path | None = None,
        language: str | None = None,
        extra_args: Sequence[str] = (),
        runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
    ) -> None:
        self._binary = binary if binary is not None else whisper_cpp_binary()
        self._model = model if model is not None else whisper_model_path()
        self._language = language if language is not None else whisper_language()
        self._extra_args = tuple(extra_args)
        self._runner = runner or self._run

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess:
        # UTF-8 explicitly: the locale codec (cp1252 here) cannot decode Urdu
        # or any non-Latin transcript and raises UnicodeDecodeError instead.
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def availability(self) -> Availability:
        if self._binary is None:
            return Availability(False, f"{WHISPER_CPP_BIN_ENV} is not set (whisper.cpp not built yet)")
        if not self._binary.exists():
            return Availability(False, f"{WHISPER_CPP_BIN_ENV} points at a missing file: {self._binary}")
        if self._model is None:
            return Availability(False, f"{WHISPER_MODEL_ENV} is not set (large-v3 not downloaded yet)")
        if not self._model.exists():
            return Availability(False, f"{WHISPER_MODEL_ENV} points at a missing file: {self._model}")
        return Availability(True)

    def transcribe(self, clip: Path) -> str:
        assert self._binary is not None and self._model is not None  # guarded by availability()
        command = whisper_cpp_command(
            self._binary,
            self._model,
            clip,
            language=self._language,
            extra_args=self._extra_args,
        )
        completed = self._runner(command)
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip().splitlines()
            tail = stderr[-1] if stderr else "no stderr"
            raise RuntimeError(f"whisper.cpp exited {completed.returncode}: {tail}")
        return _spoken_text(completed.stdout or "")


# The amd/whisper.cpp fork logs NPU progress to **stdout**, not stderr
# (whisper-vitisai-encoder.cpp:197), so raw stdout is not a transcript: without
# this the benchmark's transcript column showed
# "whisper_vitisai_encode: Vitis AI model inference completed." instead of speech.
# Reported by the whisper-npu-build lane 29 Aug 2026.
_LOG_LINE_PREFIXES = (
    "whisper_",
    "system_info:",
    "main:",
    "ggml_",
    "XRT",
    "Vitis",
    "register_backend",
    "load_backend",
)


def _spoken_text(stdout: str) -> str:
    """Keep the transcribed speech, drop the runtime's own log lines."""
    kept = [
        line.strip()
        for line in stdout.splitlines()
        if line.strip() and not line.lstrip().startswith(_LOG_LINE_PREFIXES)
    ]
    return " ".join(kept).strip()


def default_backends() -> list[SttBackend]:
    """Every backend whose runtime could exist on this machine.

    One entry today. See the module docstring for why Groq is not here.
    """
    return [WhisperCppBackend()]


def probe_clip_seconds(clip: Path) -> float | None:
    """Duration of ``clip`` in seconds, or ``None`` if it cannot be read.

    ``soundfile`` is imported lazily so importing this module - which the
    offline suite does - never requires an audio stack.
    """
    try:
        import soundfile  # noqa: PLC0415 - deliberately lazy; see module docstring

        info = soundfile.info(str(clip))
    except Exception:
        return None
    if not info.samplerate:
        return None
    return info.frames / info.samplerate


def run_benchmark(
    backends: Sequence[SttBackend],
    clip: Path,
    *,
    runs: int = 1,
    timer: Callable[[], float] = time.perf_counter,
) -> list[BackendResult]:
    """Time each backend over ``clip``. Never raises on a backend's behalf.

    An unavailable backend produces a row saying so. A backend that blows up
    mid-transcription produces a row carrying the error. Either way every other
    backend still gets measured.
    """
    if runs < 1:
        raise ValueError("runs must be at least 1")

    results: list[BackendResult] = []
    for backend in backends:
        availability = backend.availability()
        if not availability.available:
            results.append(BackendResult(name=backend.name, available=False, reason=availability.reason))
            continue

        latencies: list[float] = []
        transcript: str | None = None
        error: str | None = None
        for _ in range(runs):
            started = timer()
            try:
                transcript = backend.transcribe(clip)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                break
            latencies.append(timer() - started)
        results.append(
            BackendResult(
                name=backend.name,
                available=True,
                latencies=tuple(latencies),
                transcript=transcript,
                error=error,
            )
        )
    return results


def _truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_table(
    results: Sequence[BackendResult],
    *,
    clip_seconds: float | None = None,
    transcript_width: int = 48,
) -> str:
    """The human-readable benchmark table."""
    headers = ("backend", "latency", "xRT", "transcript / why not")
    rows: list[tuple[str, str, str, str]] = []
    for result in results:
        if not result.available:
            rows.append((result.name, "-", "-", f"not available: {result.reason}"))
            continue
        if result.error is not None:
            rows.append((result.name, "-", "-", f"failed: {_truncate(result.error, transcript_width)}"))
            continue
        latency = result.latency_seconds
        factor = result.realtime_factor(clip_seconds)
        rows.append(
            (
                result.name,
                f"{latency:.2f}s" if latency is not None else "-",
                f"{factor:.2f}" if factor is not None else "-",
                _truncate(result.transcript or "", transcript_width),
            )
        )

    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(cell)) for w, cell in zip(widths, row)]

    def line(cells: Sequence[str]) -> str:
        return "  ".join(cell.ljust(width) for cell, width in zip(cells, widths)).rstrip()

    out = [line(headers), line(["-" * width for width in widths])]
    out.extend(line(row) for row in rows)
    return "\n".join(out)


def results_as_json(results: Sequence[BackendResult], *, clip_seconds: float | None) -> str:
    payload = {
        "clip_seconds": clip_seconds,
        "backends": [
            {
                "name": r.name,
                "available": r.available,
                "reason": r.reason or None,
                "latencies": list(r.latencies),
                "latency_seconds": r.latency_seconds,
                "realtime_factor": r.realtime_factor(clip_seconds),
                "transcript": r.transcript,
                "error": r.error,
            }
            for r in results
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--clip",
        type=Path,
        default=None,
        help="path to a ~10 second Urdu/English wav clip (required; nothing is invented if omitted)",
    )
    parser.add_argument("--runs", type=int, default=1, help="times to transcribe the clip per backend (median reported)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of a table")
    parser.add_argument(
        "--whisper-arg",
        action="append",
        default=[],
        dest="whisper_args",
        help="extra argument passed through to whisper.cpp; repeatable",
    )
    args = parser.parse_args(argv)

    if args.clip is None:
        print(
            "A clip is required. Blueprint 3.1 measures STT latency on a ~10 second\n"
            "Urdu/English recording; there is no default clip and one will not be\n"
            "invented. Record one with:\n"
            "    .venv/Scripts/python.exe -m voice.record_wakeword --count 1 --seconds 10 --dir some/dir\n"
            "then pass it with --clip.",
            file=sys.stderr,
        )
        return 2
    if not args.clip.exists():
        print(f"Clip not found: {args.clip}", file=sys.stderr)
        return 2
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    clip_seconds = probe_clip_seconds(args.clip)
    backends: list[SttBackend] = [WhisperCppBackend(extra_args=args.whisper_args)]
    results = run_benchmark(backends, args.clip, runs=args.runs)

    if args.json:
        print(results_as_json(results, clip_seconds=clip_seconds))
    else:
        if clip_seconds is None:
            print(f"Clip: {args.clip} (duration unreadable)")
        else:
            print(f"Clip: {args.clip} ({clip_seconds:.1f}s)")
            if abs(clip_seconds - TARGET_CLIP_SECONDS) > CLIP_SECONDS_TOLERANCE:
                print(
                    f"Warning: blueprint 3.1 specifies a ~{TARGET_CLIP_SECONDS:g}s clip. "
                    "A latency measured on this one is not comparable to that target."
                )
        print(f"Runs per backend: {args.runs}\n")
        print(format_table(results, clip_seconds=clip_seconds))

    if not any(r.available for r in results):
        return 3
    if any(r.available and r.error is not None for r in results):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via main()
    sys.exit(main())
