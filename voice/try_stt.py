"""Record from the microphone and transcribe it on the NPU. One command.

The pieces this joins already existed and were each proved separately:
``sounddevice`` capture (the wake-word recorder's path) and
``voice/whisper/local_backend.py`` (the amd/whisper.cpp fork running on the
XDNA NPU). What was missing was a way for Ali to point the whole thing at his
own voice without writing a clip path by hand.

    .venv\\Scripts\\python.exe voice/try_stt.py
    .venv\\Scripts\\python.exe voice/try_stt.py --seconds 10 --keep
    .venv\\Scripts\\python.exe voice/try_stt.py --clip some-existing.wav

Speak Urdu or English. **The default is Urdu (``ur``), not ``auto``**, changed
30 Aug 2026: Ali code-switches Urdu/English mid-sentence and ``auto`` was
silently dropping the Urdu half of mixed clips, which is worse than ``-l ur``'s
degraded pure-English case. ``--language`` overrides it per run. The tradeoff
data is in ``docs/history/voice-urdu-language-detection.md``; the original
auto-detect reasoning is in ``docs/tasks/whisper-npu-build-report.md``.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice.config import (
    DEFAULT_WHISPER_LANGUAGE,
    WAKEWORD_CHANNELS,
    WAKEWORD_DTYPE,
    WAKEWORD_SAMPLE_RATE,
)

# whisper.cpp wants 16 kHz mono PCM, which is the same format the wake-word
# recorder already captures, so the constants are shared rather than restated.
RECORD_SAMPLE_RATE = WAKEWORD_SAMPLE_RATE

DEFAULT_SECONDS = 6.0



def _force_utf8_console() -> None:
    """Let this process print non-Latin script.

    Two separate encoding problems bite on Windows and both must be fixed:
    reading whisper.cpp's UTF-8 stdout (handled in the backend's subprocess
    call), and *writing* the result to a console whose default codec is cp1252.
    Without this, a correct Urdu transcript still dies with UnicodeEncodeError
    at the print, which looks identical to the model failing.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                # A redirected or already-wrapped stream: printing ASCII still
                # works, so this is not worth failing the run over.
                pass


def scratch_clip_path() -> Path:
    """Where an unnamed recording is written when ``--clip`` was not given.

    Written next to the other scratch audio, not into the repo. A function
    rather than an inline expression so a test can redirect it instead of
    monkeypatching the standard library.
    """
    return Path(tempfile.gettempdir()) / "jarvis-try-stt.wav"


def record(seconds: float, device: int | None, destination: Path) -> float:
    """Capture ``seconds`` of speech to ``destination``. Returns its duration."""
    import sounddevice as sd
    import soundfile as sf

    frames = int(seconds * RECORD_SAMPLE_RATE)

    for count in (3, 2, 1):
        print(f"  {count}...", end="", flush=True)
        time.sleep(0.6)
    print(f"  SPEAK  ({seconds:0.0f}s)", flush=True)

    audio = sd.rec(
        frames,
        samplerate=RECORD_SAMPLE_RATE,
        channels=WAKEWORD_CHANNELS,
        dtype=WAKEWORD_DTYPE,
        device=device,
    )
    sd.wait()
    sf.write(destination, audio, RECORD_SAMPLE_RATE, subtype="PCM_16")
    print("  done recording\n")
    return len(audio) / RECORD_SAMPLE_RATE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record your voice and transcribe it locally on the NPU."
    )
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    parser.add_argument("--device", type=int, default=None, help="input device index")
    parser.add_argument("--clip", help="transcribe this file instead of recording")
    parser.add_argument("--keep", action="store_true", help="keep the recorded .wav")
    parser.add_argument(
        "--language", default=None,
        help=(
            "force a language ('ur' Urdu, 'en' English, 'hi' Hindi). "
            f"Default: {DEFAULT_WHISPER_LANGUAGE}. "
            "Forcing is also ~2x faster because it skips the detection pass."
        ),
    )
    parser.add_argument(
        "--compare", action="store_true",
        help=(
            "transcribe the same audio three ways and print all three. Note the "
            f"first row is the configured default ({DEFAULT_WHISPER_LANGUAGE}), "
            "not auto-detect, so today this compares "
            f"{DEFAULT_WHISPER_LANGUAGE}/ur/en."
        ),
    )
    args = parser.parse_args(argv)

    _force_utf8_console()

    from voice.whisper.local_backend import LocalWhisperBackend, default_backend


    backend = (
        LocalWhisperBackend(language=args.language) if args.language else default_backend()
    )
    state = backend.availability()
    if not state.available:
        print(f"error: local speech-to-text is not available: {state.reason}", file=sys.stderr)
        return 1

    if args.clip:
        clip = Path(args.clip)
        if not clip.exists():
            print(f"error: no such file: {clip}", file=sys.stderr)
            return 1
        temporary = None
        spoken_seconds = None
    else:
        # Not written into the repo, and removed again unless --keep says
        # otherwise.
        temporary = scratch_clip_path()
        clip = temporary
        spoken_seconds = record(args.seconds, args.device, clip)

    if args.compare:
        # Same clip through three language settings, so the only variable is
        # the hint itself rather than a second take of the user's voice.
        print("  transcribing the SAME clip three ways...")
        print("")
        for label, code in (("auto-detect", None), ("forced Urdu", "ur"), ("forced English", "en")):
            probe = LocalWhisperBackend(language=code) if code else default_backend()
            started = time.monotonic()
            try:
                text, _ = probe(clip)
            except Exception as exc:  # noqa: BLE001
                text = f"(failed: {type(exc).__name__}: {exc})"
            took = time.monotonic() - started
            print(f"  {label:<16} [{took:5.1f}s]")
            shown = text.strip() or "(nothing recognised)"
            print(f"      {shown}")
            print("")
        if temporary and not args.keep:
            temporary.unlink(missing_ok=True)
        elif temporary:
            print(f"  kept: {temporary}")
        return 0

    print(f"  transcribing on the NPU ({backend.language})...")
    print("")
    started = time.monotonic()
    try:
        transcript, _ = backend(clip)
    except Exception as exc:  # noqa: BLE001 - surface the real failure, do not mask it
        print(f"transcription failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    elapsed = time.monotonic() - started

    print("  " + "-" * 62)
    print(f"  {transcript.strip() or '(nothing recognised)'}")
    print("  " + "-" * 62)

    if spoken_seconds:
        # Slower than real time means it cannot keep up with live speech; the
        # ratio is the number worth watching, not the raw seconds.
        print(f"\n  {elapsed:0.1f}s to transcribe {spoken_seconds:0.1f}s of audio "
              f"({elapsed / spoken_seconds:0.1f}x real time)")
    else:
        print(f"\n  {elapsed:0.1f}s")

    if temporary and not args.keep:
        temporary.unlink(missing_ok=True)
    elif temporary:
        print(f"  kept: {temporary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
