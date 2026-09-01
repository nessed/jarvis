"""Play Kokoro's voices out loud so a voice can be picked by ear.

Blueprint 3.2: "Listen to Kokoro's voices, pick one." That is a sensory call and
permanently the user's -- an agent cannot judge which voice sounds right coming
out of his speakers. This script exists so making that call costs him one
command instead of writing synthesis code.

All 54 voice packs are already cached locally by the voice-deps lane, so this
runs offline.

    .venv\\Scripts\\python.exe voice/audition_voices.py
    .venv\\Scripts\\python.exe voice/audition_voices.py --filter am_ --text "yo, what's the plan"
    .venv\\Scripts\\python.exe voice/audition_voices.py --voice af_heart --save picked.wav
    .venv\\Scripts\\python.exe voice/audition_voices.py --list

Kokoro's voice ids encode language and gender in the prefix: ``af_`` American
female, ``am_`` American male, ``bf_``/``bm_`` British. Read that from the ids
themselves rather than trusting this comment -- ``--list`` prints what is
actually installed.
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Kokoro-82M is a 24 kHz model. This is the model's output rate, not a choice:
# resampling it before playback would be an audible quality loss in exactly the
# thing being judged.
KOKORO_SAMPLE_RATE = 24000

# 'a' is Kokoro's American-English pipeline code. The voice id prefix and the
# pipeline code have to agree or the phonemiser mismatches the voice pack.
DEFAULT_LANG = "a"

DEFAULT_TEXT = (
    "Alright, I'm listening. Your bus is up, the tunnel is live, "
    "and there are three jobs in the queue."
)


def default_cache_root() -> Path:
    """Where huggingface caches the downloaded voice packs.

    Resolved through a function rather than inlined so a test can point the
    scan at a directory it created itself instead of at the real home
    directory. Kept lazy: ``Path.home()`` reads the environment, and doing
    that at import time would make importing this module fail on a machine
    with no home set.
    """
    return Path.home() / ".cache" / "huggingface"


def installed_voices(cache_root: Path | None = None) -> list[str]:
    """Voice ids actually cached on this machine, read off disk."""
    root = default_cache_root() if cache_root is None else Path(cache_root)
    pattern = str(root / "**" / "*.pt")
    names = {Path(p).stem for p in glob.glob(pattern, recursive=True)}
    return sorted(n for n in names if "_" in n and len(n) > 3)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audition Kokoro TTS voices by ear.")
    parser.add_argument("--text", default=DEFAULT_TEXT, help="what it should say")
    parser.add_argument("--voice", help="play exactly one voice id")
    parser.add_argument("--filter", default="", help="only voices whose id starts with this")
    parser.add_argument("--limit", type=int, default=8, help="max voices to play in one run")
    parser.add_argument("--save", help="write the audio to this .wav instead of playing it")
    parser.add_argument("--list", action="store_true", help="list installed voice ids and exit")
    args = parser.parse_args(argv)

    voices = installed_voices()
    if not voices:
        print(
            "error: no Kokoro voice packs found in the local cache. "
            "The voice-deps lane downloads them; see "
            "docs/tasks/voice-deps-and-tooling-report.md",
            file=sys.stderr,
        )
        return 1

    if args.list:
        print(f"{len(voices)} voices installed:\n")
        for name in voices:
            print(f"   {name}")
        return 0

    if args.voice:
        if args.voice not in voices:
            print(f"error: '{args.voice}' is not installed. Try --list.", file=sys.stderr)
            return 1
        chosen = [args.voice]
    else:
        chosen = [v for v in voices if v.startswith(args.filter)][: args.limit]
        if not chosen:
            print(f"error: no installed voice starts with '{args.filter}'.", file=sys.stderr)
            return 1

    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    pipeline = KPipeline(lang_code=DEFAULT_LANG)

    if not args.save:
        import sounddevice as sd

    print(f'Saying: "{args.text}"\n')

    for name in chosen:
        # Kokoro yields one chunk per sentence-ish segment; join them so a
        # multi-sentence line plays as one continuous take.
        chunks = [audio for _, _, audio in pipeline(args.text, voice=name)]
        if not chunks:
            print(f"  {name:<14} produced no audio, skipped")
            continue
        audio = np.concatenate(chunks)
        seconds = len(audio) / KOKORO_SAMPLE_RATE

        if args.save:
            out = Path(args.save)
            if len(chosen) > 1:
                out = out.with_name(f"{out.stem}_{name}{out.suffix}")
            sf.write(out, audio, KOKORO_SAMPLE_RATE)
            print(f"  {name:<14} {seconds:5.1f}s  -> {out}")
        else:
            print(f"  {name:<14} {seconds:5.1f}s  playing...")
            sd.play(audio, KOKORO_SAMPLE_RATE)
            sd.wait()

    if not args.save:
        print("\nPick one and tell me the id. It becomes JARVIS's voice.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
