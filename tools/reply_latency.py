r"""Where the seconds went, read back out of the worker logs.

``executor/latency.py`` writes one ``reply-latency`` line per replied job.
This reads those lines and prints p50/p95 per stage, which is the only honest
way to answer "did that change make it faster". A single fast reply proves
nothing; a p50 that moved across forty of them does.

    .venv\Scripts\python.exe -m tools.reply_latency
    .venv\Scripts\python.exe -m tools.reply_latency --last 20 --json
    .venv\Scripts\python.exe -m tools.reply_latency --log tools\whatsapp-worker.out.log

Defaults to the logs the WhatsApp and action workers write under ``tools/``
(``tools/start_jarvis.py``'s ``LOG_DIR``). Nothing here touches the network,
the queue or the message text -- the lines it reads carry stage names and
milliseconds and nothing else, by construction.

**p95 of a handful of jobs is not a p95.** With fewer than 20 samples the
summary says so rather than quietly printing a number that is really "the
slowest one". Percentiles use nearest-rank, which for small n is the
defensible choice: every value it prints was actually observed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "tools"

DEFAULT_LOGS = (
    LOG_DIR / "whatsapp-worker.out.log",
    LOG_DIR / "action-worker.out.log",
)

LINE_PREFIX = "reply-latency"
_FIELD = re.compile(r"(?P<key>[a-z_]+)=(?P<value>\S+)")

# Below this, a p95 is the slowest sample wearing a statistic's hat.
MIN_SAMPLES_FOR_P95 = 20

# The order stages are printed in: the order they happen. Anything measured
# but not listed follows, alphabetically, so a stage added to the handler
# shows up here without this file having to change.
STAGE_ORDER = (
    "queue_wait",
    "cue",
    "stt",
    "classify",
    "recall",
    "model",
    "tts",
    "send",
    "remember",
    "total",
)


class NoSamplesError(RuntimeError):
    """Raised when no ``reply-latency`` line was found at all."""


def parse_line(line: str) -> dict[str, Any] | None:
    """One ``reply-latency`` line as a dict, or ``None`` if it is not one.

    Tolerant on purpose: the line is prefixed by whatever logging format the
    worker was configured with, and a truncated tail (a log rotated mid-write)
    should cost one sample, not the whole run.
    """
    index = line.find(LINE_PREFIX)
    if index < 0:
        return None
    record: dict[str, Any] = {}
    for match in _FIELD.finditer(line[index + len(LINE_PREFIX) :]):
        key, value = match.group("key"), match.group("value")
        if key.endswith("_ms"):
            try:
                record[key[: -len("_ms")]] = int(value)
            except ValueError:
                continue
        else:
            record[key] = value
    if "total" not in record:
        return None
    return record


def read_samples(paths: Iterable[Path]) -> list[dict[str, Any]]:
    """Every parsable sample from these logs, oldest first.

    A missing log is not an error. The action worker is optional and may never
    have run; asking for a summary should not fail because of it.
    """
    samples: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                record = parse_line(line)
                if record is not None:
                    record["log"] = path.name
                    samples.append(record)
    return samples


def percentile(values: Sequence[int], fraction: float) -> int:
    """Nearest-rank percentile: always a value that was actually observed."""
    if not values:
        raise ValueError("percentile of no values")
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(-(-fraction * len(ordered) // 1))))
    return ordered[rank - 1]


def summarise(samples: Sequence[Mapping[str, Any]], *, last: int | None = None) -> dict[str, Any]:
    """p50/p95 per stage over the most recent ``last`` samples."""
    if not samples:
        raise NoSamplesError("no reply-latency lines found")
    window = list(samples[-last:]) if last else list(samples)

    stages: dict[str, list[int]] = {}
    for sample in window:
        for key, value in sample.items():
            if isinstance(value, int):
                stages.setdefault(key, []).append(value)

    ordered = [s for s in STAGE_ORDER if s in stages]
    ordered += sorted(s for s in stages if s not in STAGE_ORDER)

    return {
        "jobs": len(window),
        "p95_is_meaningful": len(window) >= MIN_SAMPLES_FOR_P95,
        "stages": {
            stage: {
                "samples": len(stages[stage]),
                "p50_ms": percentile(stages[stage], 0.50),
                "p95_ms": percentile(stages[stage], 0.95),
                "max_ms": max(stages[stage]),
            }
            for stage in ordered
        },
    }


def render(summary: Mapping[str, Any]) -> str:
    lines = [f"{summary['jobs']} replied job(s)"]
    if not summary["p95_is_meaningful"]:
        lines.append(
            f"p95 over fewer than {MIN_SAMPLES_FOR_P95} jobs is the slowest sample, not a percentile"
        )
    lines.append("")
    lines.append(f"{'stage':<12}{'p50':>9}{'p95':>9}{'max':>9}{'n':>6}")
    for stage, values in summary["stages"].items():
        lines.append(
            f"{stage:<12}{_s(values['p50_ms']):>9}{_s(values['p95_ms']):>9}"
            f"{_s(values['max_ms']):>9}{values['samples']:>6}"
        )
    return "\n".join(lines)


def _s(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.2f}s"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="p50/p95 per reply stage, from the worker logs")
    parser.add_argument(
        "--log",
        action="append",
        type=Path,
        dest="logs",
        help="a log to read (repeatable); defaults to the WhatsApp and action worker logs",
    )
    parser.add_argument("--last", type=int, help="summarise only the most recent N replied jobs")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    paths = args.logs or list(DEFAULT_LOGS)
    samples = read_samples(paths)
    try:
        summary = summarise(samples, last=args.last)
    except NoSamplesError:
        where = ", ".join(str(p) for p in paths)
        print(f"no reply-latency lines in {where}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2) if args.json else render(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
