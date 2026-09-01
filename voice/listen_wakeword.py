"""Live "Hey JARVIS" detection, using openWakeWord's pretrained model.

Blueprint 3.2 asks the user to record 30-50 wake-word clips so a custom model
can be trained (``wakeword-train``). That is still the plan for a model tuned to
his voice and his room. But openwakeword==0.6.0 ships a **pretrained**
``hey_jarvis_v0.1`` model in its own package resources, so the phrase is
testable today, before a single clip is recorded:

    .venv/Lib/site-packages/openwakeword/resources/models/hey_jarvis_v0.1.onnx

This script is the sensory check for that. It opens the microphone, streams
16 kHz mono audio through the model, and prints a line whenever the score
crosses the threshold. **No audio is ever written or transmitted** -- the only
thing that can reach disk is ``--log``'s timestamps and scores.

    .venv\\Scripts\\python.exe voice/listen_wakeword.py
    .venv\\Scripts\\python.exe voice/listen_wakeword.py --threshold 0.3 --meter
    .venv\\Scripts\\python.exe voice/listen_wakeword.py --list-devices

What the user is judging, and what an agent cannot judge for him: whether it
fires when he says it from across the room, and whether it fires when he did
not. Both answers decide whether ``wakeword-train`` is needed at all.

The second of those -- the false-positive rate over hours of ordinary talking
-- is U4, and it is the last unmeasured Phase 3 number. It needs a long
session, so it is split in two: he runs one command and lives his evening, and
an agent reads the answer back afterwards.

    .venv\\Scripts\\python.exe voice/listen_wakeword.py --seconds 0 --log
    .venv\\Scripts\\python.exe voice/listen_wakeword.py --summary

The log is JSON Lines, appended and flushed per detection, so an overnight
session holds nothing in memory and a laptop that sleeps still leaves
everything written up to that point.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice.config import WAKEWORD_CHANNELS, WAKEWORD_DTYPE, WAKEWORD_SAMPLE_RATE

# openWakeWord scores every 80 ms frame independently. Feeding it 1280 samples
# at a time (80 ms at 16 kHz) is the chunk size its own docs and examples use;
# a larger block just delays detection, a smaller one wastes work.
FRAME_SAMPLES = 1280

# The model name as it is keyed inside openwakeword's prediction dict. This is
# the filename stem of the shipped model, not a label we choose.
MODEL_KEY = "hey_jarvis_v0.1"

# openWakeWord's own README treats 0.5 as the default decision point. It is a
# starting point for the user's ear, not a tuned value -- too low and the room
# triggers it, too high and he has to shout.
DEFAULT_THRESHOLD = 0.5

# After a hit, ignore further hits for this long so one spoken phrase reports
# once instead of once per frame while the word is still in the window.
REFRACTORY_SECONDS = 1.5


# ---------------------------------------------------------------------------
# The false-positive session log
#
# The number nobody has measured yet is how often "Hey JARVIS" fires when Ali
# did not say it. That takes hours of ordinary talking, which is his to live
# through, not an agent's to simulate. What an agent can do is make his part
# one command and make the answer readable afterwards.
#
# Format is JSON Lines, appended and flushed per detection, so an hours-long
# session holds nothing in memory and a session killed by a closed laptop
# still leaves everything up to that point on disk.
#
# What is written: a timestamp, a score, and the session's settings. No audio,
# ever. This runs in Ali's room for hours; a log that captured sound would be
# a recording of his life, and the whole point of local wake-word detection
# per blueprint §5 is that audio never leaves the moment it happens.
# ---------------------------------------------------------------------------

DEFAULT_LOG_DIR = Path("voice/logs")

SESSION_START = "session_start"
DETECTION = "detection"
SESSION_END = "session_end"


class DetectionLog:
    """Append-only JSONL record of one listening session."""

    def __init__(self, path: Path, *, now=lambda: datetime.now(UTC)) -> None:
        self._path = path
        self._now = now
        path.parent.mkdir(parents=True, exist_ok=True)
        # Line-buffered append. Two sessions writing the same file interleave
        # cleanly because every record is one line and one write.
        self._handle = path.open("a", encoding="utf-8", newline="\n")

    def _write(self, record: dict) -> None:
        self._handle.write(json.dumps(record) + "\n")
        self._handle.flush()

    def start(self, *, threshold: float, device: int | None) -> None:
        self._write({
            "event": SESSION_START,
            "at": self._now().isoformat(),
            "threshold": threshold,
            "model": MODEL_KEY,
            "device": device,
        })

    def detection(self, *, score: float, elapsed_seconds: float) -> None:
        self._write({
            "event": DETECTION,
            "at": self._now().isoformat(),
            "score": round(float(score), 4),
            "elapsed_seconds": round(float(elapsed_seconds), 2),
        })

    def end(self, *, elapsed_seconds: float, detections: int, peak_score: float) -> None:
        self._write({
            "event": SESSION_END,
            "at": self._now().isoformat(),
            "elapsed_seconds": round(float(elapsed_seconds), 2),
            "detections": detections,
            "peak_score": round(float(peak_score), 4),
        })

    def close(self) -> None:
        self._handle.close()


def read_log(path: Path) -> list[dict]:
    """Parse a session log, skipping anything unreadable.

    A half-written final line is expected, not exceptional: the process may
    have been killed mid-flush. Dropping that one line is right; refusing to
    summarise hours of good data because of it is not.
    """
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and "event" in record:
            records.append(record)
    return records


def summarise(records: list[dict]) -> str:
    """The report an agent reads back to Ali after his session."""
    starts = [r for r in records if r.get("event") == SESSION_START]
    ends = [r for r in records if r.get("event") == SESSION_END]
    hits = [r for r in records if r.get("event") == DETECTION]

    if not starts:
        return "No session found in this log."

    # Sum the sessions, do not span them: a log appended to over three
    # evenings is three sessions, and dividing detections by the wall-clock
    # gap between the first and last would divide by the nights in between.
    duration = sum(float(r.get("elapsed_seconds") or 0.0) for r in ends)
    unfinished = len(starts) - len(ends)

    lines = [
        f"sessions      {len(starts)}" + (f"  ({unfinished} with no end record)" if unfinished else ""),
        # Seconds alongside the hours: a verification run of a couple of
        # minutes otherwise reads as "0.00 hours", which looks like the log
        # is empty rather than short.
        f"listening     {duration / 3600:.2f} hours ({duration:.0f}s)",
        f"detections    {len(hits)}",
    ]
    if duration > 0:
        lines.append(f"rate          {len(hits) / (duration / 3600):.2f} per hour")
    else:
        lines.append("rate          n/a (no completed session yet)")

    thresholds = sorted({float(r["threshold"]) for r in starts if "threshold" in r})
    if thresholds:
        lines.append("threshold     " + ", ".join(f"{t:g}" for t in thresholds))

    if hits:
        scores = [float(r.get("score") or 0.0) for r in hits]
        lines.append(f"scores        min {min(scores):.3f}  max {max(scores):.3f}")
        lines.append("")
        lines.append("  score histogram")
        # Ten fixed buckets, printed whether or not they are occupied: the
        # shape of the tail is the point. A histogram that hides its empty
        # buckets makes a cluster at 0.5 look identical to one at 0.9.
        for low in range(0, 10):
            bucket = [s for s in scores if low / 10 <= s < (low + 1) / 10 or (low == 9 and s >= 1.0)]
            bar = "#" * len(bucket)
            lines.append(f"    {low / 10:.1f}-{(low + 1) / 10:.1f}  {len(bucket):>4}  {bar}")

    return "\n".join(lines)


def summarise_file(path: Path) -> int:
    if not path.exists():
        print(f"error: no log at {path}", file=sys.stderr)
        return 1
    print(f"=== {path} ===")
    print(summarise(read_log(path)))
    return 0


def list_devices() -> int:
    import sounddevice as sd

    print("Input devices:\n")
    for index, device in enumerate(sd.query_devices()):
        if device["max_input_channels"] > 0:
            default = " (default)" if index == sd.default.device[0] else ""
            print(f"  [{index:>2}] {device['name']}{default}")
    return 0


def _bar(score: float, width: int = 32) -> str:
    filled = int(round(score * width))
    return "#" * filled + "-" * (width - filled)


def _load_model():
    """The real openWakeWord model. Imported lazily: loading it is expensive."""
    from openwakeword.model import Model

    return Model(wakeword_models=[MODEL_KEY], inference_framework="onnx")


def _open_stream(device: int | None):
    """The real microphone, opened in the format the model was trained on."""
    import sounddevice as sd

    return sd.InputStream(
        samplerate=WAKEWORD_SAMPLE_RATE,
        channels=WAKEWORD_CHANNELS,
        dtype=WAKEWORD_DTYPE,
        blocksize=FRAME_SAMPLES,
        device=device,
    )


def listen(
    threshold: float,
    device: int | None,
    meter: bool,
    seconds: float | None,
    *,
    load_model=_load_model,
    open_stream=_open_stream,
    clock=time.monotonic,
    log_path: Path | None = None,
    open_log=None,
) -> int:
    import numpy as np

    # Fail loudly and early if the pretrained model is not where we expect it,
    # rather than at the first frame with a confusing KeyError.
    model = load_model()
    if MODEL_KEY not in model.models:
        print(
            f"error: openwakeword did not load '{MODEL_KEY}'. "
            f"loaded instead: {sorted(model.models)}",
            file=sys.stderr,
        )
        return 1

    limit = f"for {seconds:0.0f}s" if seconds else "until Ctrl+C"
    print(f'Listening for "Hey JARVIS"   threshold={threshold}   {limit}')
    print("Try it close, then from across the room, then quietly.\n")

    hits = 0
    last_hit = 0.0
    peak = 0.0
    # A bounded run so this can be launched from a chat prompt and actually
    # return, instead of only ending on Ctrl+C in an interactive terminal.
    started = clock()
    deadline = (started + seconds) if seconds else None

    log = None
    if log_path is not None:
        log = (open_log or DetectionLog)(log_path)
        log.start(threshold=threshold, device=device)
        print(f"Logging detections to {log_path}")

    try:
        with open_stream(device) as stream:
            while deadline is None or clock() < deadline:
                frame, overflowed = stream.read(FRAME_SAMPLES)
                if overflowed:
                    # Dropped audio makes a miss meaningless -- say so rather
                    # than let the user conclude the model failed.
                    print("  (audio buffer overflowed, a frame was dropped)")

                score = model.predict(np.squeeze(frame))[MODEL_KEY]
                peak = max(peak, score)

                if meter:
                    print(f"\r  {_bar(score)} {score:0.3f}", end="", flush=True)

                now = clock()
                if score >= threshold and (now - last_hit) > REFRACTORY_SECONDS:
                    hits += 1
                    last_hit = now
                    prefix = "\n" if meter else ""
                    print(f"{prefix}  HEARD IT  #{hits}   score {score:0.3f}")
                    if log is not None:
                        # Written and flushed here, not accumulated: an
                        # overnight session must hold nothing in memory, and a
                        # laptop that sleeps mid-run must still leave a log.
                        log.detection(score=float(score), elapsed_seconds=now - started)
    except KeyboardInterrupt:
        pass
    finally:
        # The footer is what makes detections-per-hour computable, so it has
        # to be written on every exit path -- deadline, Ctrl+C, or a raising
        # stream. Without the finally, the one exit Ali actually uses (Ctrl+C
        # after an evening) would be the one that produced an unusable log.
        if log is not None:
            log.end(
                elapsed_seconds=clock() - started,
                detections=hits,
                peak_score=peak,
            )
            log.close()

    # Reached by both the timed deadline and Ctrl+C, so a bounded run still
    # reports. Without this, --seconds ended the loop and printed nothing.
    print("")
    print(f"Done. {hits} detection(s). Highest score seen: {peak:0.3f}")
    if hits == 0:
        print(
            "  Nothing detected. If the bar never moved, the microphone is "
            "not being heard -- check --list-devices. If it moved but never "
            "crossed the line, try --threshold 0.3."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Listen for "Hey JARVIS" using openWakeWord\'s pretrained model.'
    )
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--device", type=int, default=None, help="input device index")
    parser.add_argument("--meter", action="store_true", help="show a live score bar")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument(
        "--seconds", type=float, default=30.0,
        help="stop after this many seconds (0 = run until Ctrl+C)",
    )
    parser.add_argument(
        "--log", nargs="?", type=Path, const=DEFAULT_LOG_DIR / "wakeword.jsonl",
        default=None, metavar="PATH",
        help=f"append detections to a JSONL session log (default: {DEFAULT_LOG_DIR / 'wakeword.jsonl'})",
    )
    parser.add_argument(
        "--summary", nargs="?", type=Path, const=DEFAULT_LOG_DIR / "wakeword.jsonl",
        default=None, metavar="PATH",
        help="read a session log and print the false-positive rate; opens no device",
    )
    args = parser.parse_args(argv)

    # Before the threshold check and before any device is touched: reading a
    # log is a desk job, and it must work on a machine with no microphone.
    if args.summary is not None:
        return summarise_file(args.summary)
    if args.list_devices:
        return list_devices()
    if not 0.0 < args.threshold <= 1.0:
        print("error: --threshold must be between 0 and 1", file=sys.stderr)
        return 2
    return listen(
        args.threshold, args.device, args.meter, args.seconds or None, log_path=args.log
    )


if __name__ == "__main__":
    raise SystemExit(main())
