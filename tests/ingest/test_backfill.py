from __future__ import annotations

from pathlib import Path

import pytest

from ingest.backfill import run_backfill
from ingest.pipeline import BackfillCheckpoint, build_manifest


class FakeSink:
    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.fail_on_call = fail_on_call
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def remember(self, text: str, source: str, *, metadata=None) -> None:
        if self.fail_on_call == len(self.calls) + 1:
            raise RuntimeError("write failed")
        self.calls.append((text, source, dict(metadata or {})))


def _source(tmp_path: Path, content: str = "one two three four five") -> tuple[Path, object]:
    intake = tmp_path / "intake"
    intake.mkdir(parents=True)
    path = intake / "notes.txt"
    path.write_text(content, encoding="utf-8")
    return path, build_manifest(path, intake_dir=intake)


def test_backfill_persists_chunks_in_order_and_records_metadata(tmp_path: Path) -> None:
    path, manifest = _source(tmp_path)
    sink = FakeSink()
    checkpoints = []

    result = run_backfill(path, manifest, sink, max_tokens=2, on_checkpoint=checkpoints.append)

    assert [call[0] for call in sink.calls] == ["one two", "three four", "five"]
    assert all(call[1] == "notes.txt" for call in sink.calls)
    assert [call[2] for call in sink.calls] == [{"source_type": "note"}] * 3
    assert result.processed_chunks == 3
    assert result.checkpoint.next_chunk_index == 3
    assert [checkpoint.next_chunk_index for checkpoint in checkpoints] == [1, 2, 3]


def test_backfill_does_not_advance_observed_checkpoint_when_sink_fails(tmp_path: Path) -> None:
    path, manifest = _source(tmp_path)
    sink = FakeSink(fail_on_call=2)
    checkpoints = []

    with pytest.raises(RuntimeError, match="write failed"):
        run_backfill(path, manifest, sink, max_tokens=2, on_checkpoint=checkpoints.append)

    assert [call[0] for call in sink.calls] == ["one two"]
    assert [checkpoint.next_chunk_index for checkpoint in checkpoints] == [1]


def test_backfill_resumes_from_the_last_successful_checkpoint(tmp_path: Path) -> None:
    path, manifest = _source(tmp_path)
    first_sink = FakeSink(fail_on_call=2)
    checkpoints = []
    with pytest.raises(RuntimeError):
        run_backfill(path, manifest, first_sink, max_tokens=2, on_checkpoint=checkpoints.append)

    resumed_sink = FakeSink()
    result = run_backfill(path, manifest, resumed_sink, max_tokens=2, checkpoint=checkpoints[-1])

    assert [call[0] for call in resumed_sink.calls] == ["three four", "five"]
    assert result.processed_chunks == 2
    assert result.checkpoint.next_chunk_index == 3


def test_backfill_rejects_checkpoint_for_a_different_manifest(tmp_path: Path) -> None:
    path, manifest = _source(tmp_path)
    other_path, other_manifest = _source(tmp_path / "other", "different source")

    with pytest.raises(ValueError, match="different manifest"):
        run_backfill(path, manifest, FakeSink(), checkpoint=BackfillCheckpoint.start(other_manifest))

    assert other_path.exists()


@pytest.mark.parametrize("offset", [-1, 4])
def test_backfill_rejects_invalid_checkpoint_offsets(tmp_path: Path, offset: int) -> None:
    path, manifest = _source(tmp_path)
    checkpoint = BackfillCheckpoint(manifest_sha256=manifest.sha256, next_chunk_index=offset)

    with pytest.raises(ValueError, match="(negative|beyond)"):
        run_backfill(path, manifest, FakeSink(), max_tokens=2, checkpoint=checkpoint)
