from pathlib import Path

import pytest

from ingest.pipeline import BackfillCheckpoint, build_manifest, chunk_file, discover_intake


def write(root: Path, name: str, content: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_discovery_is_opt_in_and_filters_supported_files(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert discover_intake(missing) == []
    intake = tmp_path / "intake"
    write(intake, "notes/a.md", "hello")
    write(intake, "chat.txt", "hello")
    write(intake, "skip.pdf", "not text")
    assert [path.relative_to(intake).as_posix() for path in discover_intake(intake)] == ["chat.txt", "notes/a.md"]


def test_notes_are_normalized_and_chunked_deterministically(tmp_path: Path) -> None:
    intake = tmp_path / "intake"
    source = write(intake, "notes.txt", " one\r\ntwo   three\n four five ")
    manifest = build_manifest(source, intake_dir=intake)
    chunks = chunk_file(source, manifest, max_tokens=2)
    assert manifest.source_type == "note"
    assert [chunk.text for chunk in chunks] == ["one two", "three four", "five"]
    assert [chunk.index for chunk in chunks] == [0, 1, 2]


def test_whatsapp_messages_are_kept_per_message_with_metadata(tmp_path: Path) -> None:
    intake = tmp_path / "intake"
    source = write(
        intake,
        "family.txt",
        "[24/08/2026, 12:00] Ali: first line\ncontinued line\n[24/08/2026, 12:01] Mom: second line\n",
    )
    manifest = build_manifest(source, intake_dir=intake)
    chunks = chunk_file(source, manifest)
    assert manifest.source_type == "whatsapp_export"
    assert [(chunk.text, chunk.metadata["sender"]) for chunk in chunks] == [
        ("first line continued line", "Ali"),
        ("second line", "Mom"),
    ]


def test_manifest_rejects_outside_or_changed_sources(tmp_path: Path) -> None:
    intake = tmp_path / "intake"
    source = write(intake, "note.txt", "original")
    manifest = build_manifest(source, intake_dir=intake)
    write(tmp_path, "outside.txt", "outside")
    with pytest.raises(ValueError, match="inside"):
        build_manifest(tmp_path / "outside.txt", intake_dir=intake)
    source.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        chunk_file(source, manifest)


def test_checkpoint_round_trip_and_monotonic_advance(tmp_path: Path) -> None:
    intake = tmp_path / "intake"
    source = write(intake, "note.txt", "hello")
    checkpoint = BackfillCheckpoint.start(build_manifest(source, intake_dir=intake)).advance(0)
    restored = BackfillCheckpoint.from_json(checkpoint.to_json())
    assert restored.manifest_sha256 == checkpoint.manifest_sha256
    assert restored.next_chunk_index == 1
    with pytest.raises(ValueError, match="backwards"):
        restored.advance(0)
