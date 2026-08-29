"""Blueprint 3.2: record the "Hey JARVIS" wake-word clips.

Ali runs this and talks at it. It prompts, counts down, records a fixed window,
saves the clip, and moves on - varying what it asks for across distance and
tone so the finished set is genuinely varied rather than forty identical takes
of the same sentence at the same distance.

Usage (run as a module so the repo root is on sys.path):
    .venv/Scripts/python.exe -m voice.record_wakeword --dry-run
    .venv/Scripts/python.exe -m voice.record_wakeword --list-devices
    .venv/Scripts/python.exe -m voice.record_wakeword --count 40

Clips land in ``voice/wakeword_clips/`` (gitignored). They are recordings of
Ali's voice - personal data. Nothing here uploads them anywhere, nothing here
reads any audio it did not just record, and they must never be committed.

The run is resumable: re-running continues the numbering from the highest clip
already on disk instead of overwriting clip 1, so a session can be stopped with
Ctrl-C and picked up later.

``sounddevice`` and ``soundfile`` are imported lazily, inside the functions that
need a device. ``--dry-run`` therefore works - and the test suite imports this
module - on a machine with no audio stack at all.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Protocol, Sequence

from voice.config import (
    CLIP_FILENAME_PREFIX,
    DEFAULT_CLIP_COUNT,
    DEFAULT_CLIP_SECONDS,
    MAX_USEFUL_CLIP_COUNT,
    MIN_USEFUL_CLIP_COUNT,
    WAKE_PHRASE,
    WAKEWORD_CHANNELS,
    WAKEWORD_DTYPE,
    WAKEWORD_SAMPLE_RATE,
    WAKEWORD_SUBTYPE,
    clip_dir,
    input_device,
)


@dataclass(frozen=True)
class ClipPrompt:
    """One way of saying the wake phrase."""

    slug: str
    instruction: str


#: Blueprint 3.2 asks for clips "at different distances and tones". Cycling
#: this list means a 40-clip run gets five takes of each condition rather than
#: forty of whichever one Ali happened to settle into.
PROMPTS: tuple[ClipPrompt, ...] = (
    ClipPrompt("close-normal", "Close to the mic, normal speaking voice"),
    ClipPrompt("arms-length-normal", "About an arm's length away, normal voice"),
    ClipPrompt("across-room", "Across the room, as if calling out"),
    ClipPrompt("quiet", "Quietly, almost under your breath"),
    ClipPrompt("fast", "Fast and clipped, like you're mid-sentence"),
    ClipPrompt("slow", "Slowly and deliberately, drawing it out"),
    ClipPrompt("turned-away", "Facing away from the mic, normal volume"),
    ClipPrompt("tired", "Flat and tired, low energy"),
)


@dataclass(frozen=True)
class PlannedClip:
    """A single clip the session intends to record."""

    index: int
    prompt: ClipPrompt

    @property
    def filename(self) -> str:
        return f"{CLIP_FILENAME_PREFIX}_{self.index:04d}_{self.prompt.slug}.wav"


class Recorder(Protocol):
    """Captures one fixed-length window of mono audio."""

    def record(self, *, seconds: float, sample_rate: int, channels: int, device: object) -> object:
        ...


class ClipWriter(Protocol):
    """Writes captured audio to disk in the wake-word training format."""

    def write(self, path: Path, data: object, sample_rate: int) -> None:
        ...


_INDEX_PATTERN = re.compile(rf"^{re.escape(CLIP_FILENAME_PREFIX)}_(\d+)(?:_.*)?$")


def next_clip_index(directory: Path) -> int:
    """Highest clip number already on disk, plus one. 1 for an empty directory.

    Anything in the directory that does not match the recorder's own naming is
    ignored rather than treated as a clip, so a stray note or an export from
    somewhere else cannot shift the numbering.
    """
    if not directory.is_dir():
        return 1
    highest = 0
    for path in directory.glob("*.wav"):
        match = _INDEX_PATTERN.match(path.stem)
        if match is None:
            continue
        highest = max(highest, int(match.group(1)))
    return highest + 1


def plan_clips(
    count: int,
    *,
    start_index: int = 1,
    prompts: Sequence[ClipPrompt] = PROMPTS,
) -> list[PlannedClip]:
    """The clips a session would record, cycling evenly through ``prompts``.

    Cycling is keyed off the *position within this session*, not off the
    absolute clip index, so a resumed run starts a fresh sweep of the
    conditions rather than landing wherever the modulo happens to fall.
    """
    if count < 0:
        raise ValueError("count must not be negative")
    if not prompts:
        raise ValueError("at least one prompt is required")
    return [
        PlannedClip(index=start_index + offset, prompt=prompts[offset % len(prompts)])
        for offset in range(count)
    ]


def describe_plan(planned: Iterable[PlannedClip]) -> list[str]:
    """One human-readable line per planned clip, for ``--dry-run``."""
    return [f"{clip.index:04d}  {clip.prompt.instruction}  -> {clip.filename}" for clip in planned]


def _default_countdown(prompt: ClipPrompt, *, emit: Callable[[str], None], sleep: Callable[[float], None]) -> None:
    emit(f"\n{prompt.instruction}")
    for remaining in (3, 2, 1):
        emit(f"  {remaining}...")
        sleep(1.0)
    emit(f'  NOW - say "{WAKE_PHRASE}"')


def record_session(
    planned: Sequence[PlannedClip],
    *,
    directory: Path,
    recorder: Recorder,
    writer: ClipWriter,
    seconds: float = DEFAULT_CLIP_SECONDS,
    device: object = None,
    sample_rate: int = WAKEWORD_SAMPLE_RATE,
    emit: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Path]:
    """Record every planned clip, returning the paths actually written.

    Ctrl-C between clips ends the session cleanly and keeps everything recorded
    so far: a resumed run picks up from the next number.
    """
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for clip in planned:
        _default_countdown(clip.prompt, emit=emit, sleep=sleep)
        try:
            data = recorder.record(
                seconds=seconds,
                sample_rate=sample_rate,
                channels=WAKEWORD_CHANNELS,
                device=device,
            )
        except KeyboardInterrupt:
            emit("\nStopped. Re-run to continue from where this left off.")
            break
        path = directory / clip.filename
        writer.write(path, data, sample_rate)
        written.append(path)
        emit(f"  saved {path.name}  ({len(written)}/{len(planned)} this run)")
    return written


class SoundDeviceRecorder:
    """The real recorder. Imports ``sounddevice`` only when first used."""

    def record(self, *, seconds: float, sample_rate: int, channels: int, device: object) -> object:
        import sounddevice  # noqa: PLC0415 - deliberately lazy; see module docstring

        frames = int(round(seconds * sample_rate))
        data = sounddevice.rec(
            frames,
            samplerate=sample_rate,
            channels=channels,
            dtype=WAKEWORD_DTYPE,
            device=device,
        )
        sounddevice.wait()
        return data


class SoundFileWriter:
    """The real writer. 16 kHz / mono / PCM_16, per ``voice.config``."""

    def write(self, path: Path, data: object, sample_rate: int) -> None:
        import soundfile  # noqa: PLC0415 - deliberately lazy; see module docstring

        soundfile.write(str(path), data, sample_rate, subtype=WAKEWORD_SUBTYPE)


def list_input_devices(emit: Callable[[str], None] = print) -> int:
    """Print the machine's input devices, for mic placement. Records nothing."""
    try:
        import sounddevice  # noqa: PLC0415 - deliberately lazy; see module docstring
    except Exception as exc:  # pragma: no cover - only on a machine with no audio stack
        emit(f"sounddevice is not importable on this machine: {exc}")
        return 2
    for index, device in enumerate(sounddevice.query_devices()):
        if device["max_input_channels"] <= 0:
            continue
        emit(f"{index:>3}  {device['name']}  ({device['max_input_channels']} ch)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_CLIP_COUNT,
        help=f"clips to record this run (blueprint 3.2 wants {MIN_USEFUL_CLIP_COUNT}-{MAX_USEFUL_CLIP_COUNT} in total)",
    )
    parser.add_argument("--dir", type=Path, default=None, help="clip directory (default: voice/wakeword_clips)")
    parser.add_argument("--seconds", type=float, default=DEFAULT_CLIP_SECONDS, help="length of each recorded window")
    parser.add_argument("--device", default=None, help="input device index or name substring")
    parser.add_argument("--list-devices", action="store_true", help="list input devices and exit; records nothing")
    parser.add_argument("--dry-run", action="store_true", help="print the plan; touch no device and write no file")
    args = parser.parse_args(argv)

    if args.list_devices:
        return list_input_devices()

    if args.count <= 0:
        parser.error("--count must be positive")

    directory = args.dir or clip_dir()
    start_index = next_clip_index(directory)
    planned = plan_clips(args.count, start_index=start_index)

    already = start_index - 1
    print(f"Clip directory: {directory}")
    print(f"Already recorded: {already}")
    print(f"This run: {len(planned)} clip(s), {args.seconds:g}s each at {WAKEWORD_SAMPLE_RATE} Hz mono PCM_16")

    if args.dry_run:
        for line in describe_plan(planned):
            print(line)
        print("\nDry run: no device was opened and no file was written.")
        return 0

    total_after = already + len(planned)
    if total_after < MIN_USEFUL_CLIP_COUNT:
        print(
            f"Note: that leaves {total_after} clips in total. Blueprint 3.2 asks for "
            f"{MIN_USEFUL_CLIP_COUNT}-{MAX_USEFUL_CLIP_COUNT}; re-run to add more."
        )

    device = args.device if args.device is not None else input_device()
    written = record_session(
        planned,
        directory=directory,
        recorder=SoundDeviceRecorder(),
        writer=SoundFileWriter(),
        seconds=args.seconds,
        device=device,
    )
    print(f"\nWrote {len(written)} clip(s) to {directory}. Total now {already + len(written)}.")
    return 0 if written else 1


if __name__ == "__main__":  # pragma: no cover - exercised via main()
    sys.exit(main())
