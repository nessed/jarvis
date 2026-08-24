"""Resumable, local-only processing of one caller-selected intake file."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ingest.pipeline import BackfillCheckpoint, IngestManifest, chunk_file


class FactSink(Protocol):
    """The minimal local-memory write surface used by a backfill."""

    def remember(self, text: str, source: str, *, metadata: Mapping[str, Any] | None = None) -> object: ...


CheckpointObserver = Callable[[BackfillCheckpoint], None]


@dataclass(frozen=True)
class BackfillResult:
    """The durable resume point after successfully handling one source file."""

    checkpoint: BackfillCheckpoint
    processed_chunks: int


def run_backfill(
    path: Path,
    manifest: IngestManifest,
    sink: FactSink,
    *,
    checkpoint: BackfillCheckpoint | None = None,
    max_tokens: int = 500,
    on_checkpoint: CheckpointObserver | None = None,
) -> BackfillResult:
    """Persist one manifest-verified source, advancing only after each write.

    ``path`` is never discovered or resolved against a broader corpus here:
    ``chunk_file`` verifies it against the caller's supplied manifest before
    yielding any chunk. Callers can durably record each observed checkpoint and
    resume this exact manifest after an interruption.
    """
    active_checkpoint = checkpoint or BackfillCheckpoint.start(manifest)
    _validate_checkpoint(active_checkpoint, manifest)
    chunks = chunk_file(path, manifest, max_tokens=max_tokens)
    if active_checkpoint.next_chunk_index > len(chunks):
        raise ValueError("checkpoint offset is beyond the source chunk count")

    processed = 0
    for chunk in chunks[active_checkpoint.next_chunk_index :]:
        sink.remember(
            chunk.text,
            chunk.source,
            metadata={"source_type": chunk.source_type, **chunk.metadata},
        )
        active_checkpoint = active_checkpoint.advance(chunk.index)
        processed += 1
        if on_checkpoint is not None:
            on_checkpoint(active_checkpoint)
    return BackfillResult(checkpoint=active_checkpoint, processed_chunks=processed)


def _validate_checkpoint(checkpoint: BackfillCheckpoint, manifest: IngestManifest) -> None:
    if checkpoint.manifest_sha256 != manifest.sha256:
        raise ValueError("checkpoint belongs to a different manifest")
    if checkpoint.next_chunk_index < 0:
        raise ValueError("checkpoint offset must not be negative")
