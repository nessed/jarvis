"""Blueprint step 1.3/1.4: run the resumable local backfill over the opted-in intake folder.

Nothing here discovers files outside ``--intake-dir``. The folder starts
empty (``ingest/data``, gitignored) and stays that way until the user
explicitly drops notes or WhatsApp exports into it per blueprint step 1.2 —
running this before that happens processes nothing.

Usage:
    .venv/Scripts/python.exe tools/run_backfill.py --user-id +92XXXXXXXXXX
    .venv/Scripts/python.exe tools/run_backfill.py --dry-run
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from ingest.backfill import BackfillResult, FactSink, run_backfill
from ingest.mem0_sink import Mem0BackfillSink
from ingest.pipeline import BackfillCheckpoint, build_manifest, discover_intake
from memory.runtime import open_local_mem0_memory

DEFAULT_INTAKE_DIR = Path("ingest/data")


@dataclass(frozen=True)
class BackfillOutcome:
    """One discovered file's result: either processed, or failed without blocking the rest."""

    path: Path
    result: BackfillResult | None
    error: Exception | None = None


def _checkpoint_path(checkpoint_dir: Path, manifest_sha256: str) -> Path:
    return checkpoint_dir / f"{manifest_sha256}.json"


def _load_checkpoint(checkpoint_dir: Path, manifest_sha256: str) -> BackfillCheckpoint | None:
    path = _checkpoint_path(checkpoint_dir, manifest_sha256)
    if not path.exists():
        return None
    return BackfillCheckpoint.from_json(path.read_text(encoding="utf-8"))


def _save_checkpoint(checkpoint_dir: Path, checkpoint: BackfillCheckpoint) -> None:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    _checkpoint_path(checkpoint_dir, checkpoint.manifest_sha256).write_text(
        checkpoint.to_json(), encoding="utf-8"
    )


def run_backfill_over_intake(
    *,
    intake_dir: Path,
    checkpoint_dir: Path,
    sink: FactSink,
    max_tokens: int = 500,
) -> list[BackfillOutcome]:
    """Process every discovered file once, resuming any checkpoint saved by a prior run.

    A file whose checkpoint already reached its own chunk count simply
    processes zero remaining chunks - no special-cased skip is needed. A
    failure on one file is recorded and does not stop the rest: the
    checkpoint already written for whatever succeeded before the failure
    makes that file resumable on the next run.
    """
    outcomes: list[BackfillOutcome] = []
    for path in discover_intake(intake_dir):
        manifest = build_manifest(path, intake_dir=intake_dir)
        checkpoint = _load_checkpoint(checkpoint_dir, manifest.sha256)
        try:
            result = run_backfill(
                path,
                manifest,
                sink,
                checkpoint=checkpoint,
                max_tokens=max_tokens,
                on_checkpoint=lambda cp: _save_checkpoint(checkpoint_dir, cp),
            )
        except Exception as exc:  # noqa: BLE001 - one bad file must not block the rest
            outcomes.append(BackfillOutcome(path=path, result=None, error=exc))
            continue
        outcomes.append(BackfillOutcome(path=path, result=result))
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--intake-dir", type=Path, default=DEFAULT_INTAKE_DIR)
    parser.add_argument("--checkpoint-dir", type=Path, default=None)
    parser.add_argument(
        "--user-id",
        help="Identity facts are stored under - must match what recall() is later queried "
        "with (e.g. the WhatsApp sender id). Required unless --dry-run.",
    )
    parser.add_argument("--max-tokens", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true", help="List discovered files without processing them")
    args = parser.parse_args(argv)

    files = discover_intake(args.intake_dir)
    if args.dry_run:
        if not files:
            print(f"No supported files found under {args.intake_dir}")
        for path in files:
            print(path)
        return 0

    if not args.user_id:
        parser.error("--user-id is required unless --dry-run is set")
    if not files:
        print(f"No supported files found under {args.intake_dir}")
        return 0

    checkpoint_dir = args.checkpoint_dir or (args.intake_dir / ".checkpoints")
    memory = open_local_mem0_memory()
    try:
        sink = Mem0BackfillSink(memory=memory, user_id=args.user_id)
        outcomes = run_backfill_over_intake(
            intake_dir=args.intake_dir,
            checkpoint_dir=checkpoint_dir,
            sink=sink,
            max_tokens=args.max_tokens,
        )
    finally:
        memory.close()

    failed = 0
    for outcome in outcomes:
        if outcome.error is not None:
            failed += 1
            print(f"{outcome.path}: FAILED - {outcome.error}")
        else:
            print(f"{outcome.path}: {outcome.result.processed_chunks} chunk(s) remembered")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
