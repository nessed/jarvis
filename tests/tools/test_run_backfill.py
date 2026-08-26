from __future__ import annotations

from pathlib import Path

from ingest.pipeline import BackfillCheckpoint
from tools.run_backfill import main, run_backfill_over_intake


class FakeSink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def remember(self, text: str, source: str, *, metadata=None) -> None:
        self.calls.append((text, source))


def _write(intake: Path, name: str, content: str) -> None:
    intake.mkdir(parents=True, exist_ok=True)
    (intake / name).write_text(content, encoding="utf-8")


def test_processes_every_discovered_file_and_writes_a_checkpoint(tmp_path: Path) -> None:
    intake = tmp_path / "intake"
    _write(intake, "a.txt", "one two three")
    checkpoint_dir = tmp_path / "checkpoints"
    sink = FakeSink()

    outcomes = run_backfill_over_intake(intake_dir=intake, checkpoint_dir=checkpoint_dir, sink=sink, max_tokens=2)

    assert [text for text, _ in sink.calls] == ["one two", "three"]
    assert outcomes[0].error is None
    assert outcomes[0].result.processed_chunks == 2

    saved = list(checkpoint_dir.glob("*.json"))
    assert len(saved) == 1
    checkpoint = BackfillCheckpoint.from_json(saved[0].read_text(encoding="utf-8"))
    assert checkpoint.next_chunk_index == 2


def test_resumes_using_the_checkpoint_saved_by_a_prior_run(tmp_path: Path) -> None:
    intake = tmp_path / "intake"
    _write(intake, "a.txt", "one two three")
    checkpoint_dir = tmp_path / "checkpoints"

    class FailOnThirdChunk:
        def remember(self, text, source, *, metadata=None) -> None:
            if text == "three":
                raise RuntimeError("boom")

    first = run_backfill_over_intake(
        intake_dir=intake, checkpoint_dir=checkpoint_dir, sink=FailOnThirdChunk(), max_tokens=2
    )
    assert first[0].error is not None

    resumed_sink = FakeSink()
    second = run_backfill_over_intake(
        intake_dir=intake, checkpoint_dir=checkpoint_dir, sink=resumed_sink, max_tokens=2
    )

    assert [text for text, _ in resumed_sink.calls] == ["three"]
    assert second[0].result.processed_chunks == 1


def test_a_failure_on_one_file_does_not_block_the_rest(tmp_path: Path) -> None:
    intake = tmp_path / "intake"
    _write(intake, "a.txt", "one two three")
    _write(intake, "b.txt", "four five")
    checkpoint_dir = tmp_path / "checkpoints"

    class FlakySink:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def remember(self, text, source, *, metadata=None) -> None:
            if source == "a.txt" and text == "three":
                raise RuntimeError("boom")
            self.calls.append(text)

    sink = FlakySink()
    outcomes = run_backfill_over_intake(intake_dir=intake, checkpoint_dir=checkpoint_dir, sink=sink, max_tokens=2)

    by_name = {outcome.path.name: outcome for outcome in outcomes}
    assert by_name["a.txt"].error is not None
    assert by_name["b.txt"].error is None
    assert by_name["b.txt"].result.processed_chunks == 1


def test_a_fully_replayed_checkpoint_processes_nothing_new(tmp_path: Path) -> None:
    intake = tmp_path / "intake"
    _write(intake, "a.txt", "one two")
    checkpoint_dir = tmp_path / "checkpoints"

    run_backfill_over_intake(intake_dir=intake, checkpoint_dir=checkpoint_dir, sink=FakeSink(), max_tokens=2)

    second_sink = FakeSink()
    outcomes = run_backfill_over_intake(
        intake_dir=intake, checkpoint_dir=checkpoint_dir, sink=second_sink, max_tokens=2
    )

    assert second_sink.calls == []
    assert outcomes[0].result.processed_chunks == 0


def test_main_dry_run_lists_discovered_files_without_touching_memory(tmp_path: Path, capsys) -> None:
    intake = tmp_path / "intake"
    _write(intake, "a.txt", "hello world")

    exit_code = main(["--intake-dir", str(intake), "--dry-run"])

    assert exit_code == 0
    assert str(intake / "a.txt") in capsys.readouterr().out


def test_main_reports_no_files_found_under_an_empty_intake_dir(tmp_path: Path, capsys) -> None:
    intake = tmp_path / "empty"
    intake.mkdir()

    exit_code = main(["--intake-dir", str(intake), "--dry-run"])

    assert exit_code == 0
    assert "No supported files found" in capsys.readouterr().out


def test_main_requires_user_id_unless_dry_run(tmp_path: Path) -> None:
    intake = tmp_path / "intake"
    intake.mkdir()

    try:
        main(["--intake-dir", str(intake)])
        raised = False
    except SystemExit as exc:
        raised = True
        assert exc.code == 2

    assert raised
