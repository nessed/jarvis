"""Live "Hey JARVIS" detection, using openWakeWord's pretrained model.

Blueprint 3.2 asks the user to record 30-50 wake-word clips so a custom model
can be trained (``wakeword-train``). That is still the plan for a model tuned to
his voice and his room. But openwakeword==0.6.0 ships a **pretrained**
``hey_jarvis_v0.1`` model in its own package resources, so the phrase is
testable today, before a single clip is recorded:

    .venv/Lib/site-packages/openwakeword/resources/models/hey_jarvis_v0.1.onnx

This script is the sensory check for that. It opens the microphone, streams
16 kHz mono audio through the model, and prints a line whenever the score
crosses the threshold. Nothing is written to disk and no audio leaves the
machine.

    .venv\\Scripts\\python.exe voice/listen_wakeword.py
    .venv\\Scripts\\python.exe voice/listen_wakeword.py --threshold 0.3 --meter
    .venv\\Scripts\\python.exe voice/listen_wakeword.py --list-devices

What the user is judging, and what an agent cannot judge for him: whether it
fires when he says it from across the room, and whether it fires when he did
not. Both answers decide whether ``wakeword-train`` is needed at all.
"""

from __future__ import annotations

import argparse
import sys
import time
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
    deadline = (clock() + seconds) if seconds else None

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
    except KeyboardInterrupt:
        pass

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
    args = parser.parse_args(argv)

    if args.list_devices:
        return list_devices()
    if not 0.0 < args.threshold <= 1.0:
        print("error: --threshold must be between 0 and 1", file=sys.stderr)
        return 2
    return listen(args.threshold, args.device, args.meter, args.seconds or None)


if __name__ == "__main__":
    raise SystemExit(main())
