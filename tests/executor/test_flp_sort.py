"""Tests for executor.flp.sort (blueprint 2.2 PyFLP proof-of-concept).

PyFLP's own ``parse()``/``save()`` cannot be exercised here -- see the
module docstring in executor/flp/sort.py for the reproduced Python
3.12/PyFLP 2.2.1 incompatibility. ``load``/``save`` are therefore tested by
monkeypatching the ``pyflp`` module they wrap (proving the wrappers forward
arguments correctly), and the rename/diff/verify logic is tested against a
plain fake project standing in for a real ``pyflp.Project`` (its ``.mixer``
only needs to yield objects with ``.iid``/``.name``, which is the entire
surface this module touches).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from executor.flp import sort


@dataclass
class _FakeInsert:
    iid: int
    name: str


@dataclass
class _FakeProject:
    inserts: list[_FakeInsert] = field(default_factory=list)

    @property
    def mixer(self) -> list[_FakeInsert]:
        return self.inserts


def _project(*names: str) -> _FakeProject:
    """A fake project with one insert per name, iid 1..N (0 reserved for master)."""
    return _FakeProject([_FakeInsert(iid=i, name=name) for i, name in enumerate(names, start=1)])


# ---------------------------------------------------------------------------
# flp_backup
# ---------------------------------------------------------------------------


def test_flp_backup_creates_timestamped_copy_alongside_original(tmp_path: Path) -> None:
    original = tmp_path / "song.flp"
    original.write_bytes(b"original-bytes")

    backup = sort.flp_backup(original, now=lambda: datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC))

    assert backup.parent == original.parent
    assert backup.name == "song.2026-08-27T120000.bak.flp"
    assert backup.read_bytes() == b"original-bytes"


def test_flp_backup_is_untouched_by_later_writes_to_the_original(tmp_path: Path) -> None:
    original = tmp_path / "song.flp"
    original.write_bytes(b"before-edit")

    backup = sort.flp_backup(original, now=lambda: datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC))

    # Simulate the rest of the pipeline mutating and re-saving the original.
    original.write_bytes(b"after-edit")

    assert backup.read_bytes() == b"before-edit"
    assert original.read_bytes() == b"after-edit"


def test_flp_backup_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        sort.flp_backup(tmp_path / "does-not-exist.flp")


# ---------------------------------------------------------------------------
# load / save wrappers (monkeypatched pyflp -- see module docstring)
# ---------------------------------------------------------------------------


def test_load_delegates_to_pyflp_parse(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sentinel = object()
    calls: list[Path] = []

    def fake_parse(path: Path) -> object:
        calls.append(path)
        return sentinel

    monkeypatch.setattr(sort.pyflp, "parse", fake_parse)

    result = sort.load(tmp_path / "song.flp")

    assert result is sentinel
    assert calls == [tmp_path / "song.flp"]


def test_save_delegates_to_pyflp_save(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[object, Path]] = []

    def fake_save(project: object, path: Path) -> None:
        calls.append((project, path))

    monkeypatch.setattr(sort.pyflp, "save", fake_save)
    project = _project("Kick")

    sort.save(project, tmp_path / "song.flp")

    assert calls == [(project, tmp_path / "song.flp")]


# ---------------------------------------------------------------------------
# diff_report
# ---------------------------------------------------------------------------


def test_diff_report_accepts_plain_snapshots() -> None:
    diff = sort.diff_report({1: "Kick", 2: "Snare"}, {1: "01 DRUMS - Kick", 2: "Snare"})

    assert diff.renames == (sort.InsertRename(iid=1, before="Kick", after="01 DRUMS - Kick"),)
    assert diff.as_dict() == {"Kick": "01 DRUMS - Kick"}
    assert bool(diff) is True


def test_diff_report_ignores_inserts_present_on_only_one_side() -> None:
    diff = sort.diff_report({1: "Kick"}, {1: "Kick", 2: "New Insert"})

    assert diff.renames == ()


def test_diff_report_of_identical_snapshots_is_empty() -> None:
    diff = sort.diff_report({1: "Kick"}, {1: "Kick"})

    assert diff.renames == ()
    assert bool(diff) is False


# ---------------------------------------------------------------------------
# apply_rules
# ---------------------------------------------------------------------------


def test_apply_rules_renames_matching_inserts_and_returns_the_diff() -> None:
    project = _project("Kick", "Snare", "Untouched")
    ruleset = {
        "rules": [
            {"match": "Kick", "rename_to": "01 DRUMS - Kick"},
            {"match": "Snare", "rename_to": "01 DRUMS - Snare"},
        ]
    }

    diff = sort.apply_rules(project, ruleset)

    assert [insert.name for insert in project.mixer] == [
        "01 DRUMS - Kick",
        "01 DRUMS - Snare",
        "Untouched",
    ]
    assert diff.as_dict() == {"Kick": "01 DRUMS - Kick", "Snare": "01 DRUMS - Snare"}


def test_apply_rules_is_a_silent_no_op_for_unmatched_names_and_rules() -> None:
    project = _project("Untouched")
    ruleset = {"rules": [{"match": "Nonexistent", "rename_to": "Whatever"}]}

    diff = sort.apply_rules(project, ruleset)

    assert project.mixer[0].name == "Untouched"
    assert diff.renames == ()


def test_apply_rules_rejects_a_position_request_before_mutating_anything() -> None:
    project = _project("Kick", "Snare")
    ruleset = {
        "rules": [
            {"match": "Snare", "rename_to": "moved", "position": 0},
            {"match": "Kick", "rename_to": "renamed"},
        ]
    }

    with pytest.raises(sort.ReorderNotSupported):
        sort.apply_rules(project, ruleset)

    # Validated up front: the Kick rule (no position) must not have applied either.
    assert [insert.name for insert in project.mixer] == ["Kick", "Snare"]


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def test_verify_round_trips_cleanly_when_the_reload_matches(tmp_path: Path) -> None:
    project = _project("Kick", "Snare")
    diff = sort.apply_rules(project, {"rules": [{"match": "Kick", "rename_to": "01 - Kick"}]})

    path = tmp_path / "song.flp"
    path.write_bytes(b"stand-in for a saved flp")

    # Loader stands in for re-parsing the file PyFLP just saved: the fake
    # project already reflects the post-apply_rules state.
    assert sort.verify(path, diff, loader=lambda _p: project) is True


def test_verify_catches_a_short_or_corrupted_write_that_raises_on_reparse(tmp_path: Path) -> None:
    diff = sort.apply_rules(_project("Kick"), {"rules": [{"match": "Kick", "rename_to": "01 - Kick"}]})
    path = tmp_path / "song.flp"
    path.write_bytes(b"truncated")

    def raising_loader(_path: Path) -> object:
        raise sort.pyflp.exceptions.HeaderCorrupted("truncated data chunk")

    assert sort.verify(path, diff, loader=raising_loader) is False


def test_verify_catches_a_write_where_the_rename_silently_did_not_stick(tmp_path: Path) -> None:
    diff = sort.apply_rules(_project("Kick"), {"rules": [{"match": "Kick", "rename_to": "01 - Kick"}]})
    path = tmp_path / "song.flp"
    path.write_bytes(b"stand-in for a saved flp")

    # Reload reports the old name -- as if the write silently dropped the edit.
    stale = _project("Kick")

    assert sort.verify(path, diff, loader=lambda _p: stale) is False


# ---------------------------------------------------------------------------
# build_flp_sort_handler (the future ``flp_sort`` job handler)
# ---------------------------------------------------------------------------


@dataclass
class _FakeJob:
    payload: dict


def test_flp_sort_handler_runs_backup_then_load_apply_save_verify_in_order(tmp_path: Path) -> None:
    calls: list[str] = []
    project = _project("Kick")
    target = tmp_path / "song.flp"

    def backup(path, *, now=None):
        calls.append(f"backup:{path}")
        return Path(str(path) + ".bak")

    def loader(path):
        calls.append(f"load:{path}")
        return project

    def saver(proj, path):
        calls.append(f"save:{path}")
        assert proj is project

    def verifier(path, diff, *, loader):
        calls.append(f"verify:{path}")
        assert diff.as_dict() == {"Kick": "01 - Kick"}
        return True

    report_calls: list[tuple[Path, sort.MixerDiff]] = []

    def report_writer(path, diff):
        calls.append("report")
        report_calls.append((path, diff))

    handler = sort.build_flp_sort_handler(
        backup=backup,
        loader=loader,
        saver=saver,
        verifier=verifier,
        report_writer=report_writer,
        safe_root=tmp_path,
    )
    job = _FakeJob(
        payload={"path": str(target), "ruleset": {"rules": [{"match": "Kick", "rename_to": "01 - Kick"}]}}
    )

    handler(job)

    assert calls == [
        f"backup:{target}",
        f"load:{target}",
        f"save:{target}",
        "report",
        f"verify:{target}",
    ]
    assert project.mixer[0].name == "01 - Kick"
    assert len(report_calls) == 1
    report_path, report_diff = report_calls[0]
    assert report_path.parent == target.parent
    assert report_path.name.startswith("song.") and report_path.name.endswith(".diff.json")
    assert report_diff.as_dict() == {"Kick": "01 - Kick"}


def test_flp_sort_handler_raises_when_verify_fails(tmp_path: Path) -> None:
    project = _project("Kick")
    target = tmp_path / "song.flp"
    handler = sort.build_flp_sort_handler(
        backup=lambda path, **_kwargs: Path(str(path)),
        loader=lambda path: project,
        saver=lambda proj, path: None,
        verifier=lambda path, diff, *, loader: False,
        report_writer=lambda path, diff: None,
        safe_root=tmp_path,
    )
    job = _FakeJob(payload={"path": str(target), "ruleset": {"rules": [{"match": "Kick", "rename_to": "x"}]}})

    with pytest.raises(sort.FlpSortVerificationFailed):
        handler(job)


# ---------------------------------------------------------------------------
# flp_sort_root
# ---------------------------------------------------------------------------


def test_flp_sort_root_defaults_to_test_projects_under_the_repo_root() -> None:
    root = sort.flp_sort_root({})

    assert root.name == "test_projects"
    assert root.is_absolute()
    # sort.py lives at executor/flp/sort.py -- three parents up is the repo root.
    assert root.parent == Path(sort.__file__).resolve().parent.parent.parent


def test_flp_sort_root_honours_the_env_override(tmp_path: Path) -> None:
    custom = tmp_path / "wherever"

    root = sort.flp_sort_root({"JARVIS_FLP_SORT_ROOT": str(custom)})

    assert root == custom.resolve()


# ---------------------------------------------------------------------------
# safe-root write-path guard
# ---------------------------------------------------------------------------


def _handler_with_root(root: Path, *, calls: list[str] | None = None) -> tuple[object, list[str]]:
    calls = calls if calls is not None else []
    project = _project("Kick")

    def backup(path, *, now=None):
        calls.append(f"backup:{path}")
        return Path(str(path) + ".bak")

    def loader(path):
        calls.append(f"load:{path}")
        return project

    def saver(proj, path):
        calls.append(f"save:{path}")

    def verifier(path, diff, *, loader):
        calls.append(f"verify:{path}")
        return True

    handler = sort.build_flp_sort_handler(
        backup=backup,
        loader=loader,
        saver=saver,
        verifier=verifier,
        report_writer=lambda path, diff: calls.append("report"),
        safe_root=root,
    )
    return handler, calls


def test_path_inside_the_safe_root_proceeds_normally(tmp_path: Path) -> None:
    target = tmp_path / "song.flp"
    handler, calls = _handler_with_root(tmp_path)
    job = _FakeJob(payload={"path": str(target), "ruleset": {}})

    handler(job)

    assert calls == [f"backup:{target}", f"load:{target}", f"save:{target}", f"verify:{target}"]


def test_path_outside_the_safe_root_is_rejected_before_any_side_effect(tmp_path: Path) -> None:
    root = tmp_path / "test_projects"
    root.mkdir()
    outside = tmp_path / "elsewhere" / "song.flp"
    handler, calls = _handler_with_root(root)
    job = _FakeJob(payload={"path": str(outside), "ruleset": {}})

    with pytest.raises(sort.FlpSortPathOutsideRoot):
        handler(job)

    assert calls == []


def test_a_sibling_directory_sharing_the_root_name_as_a_string_prefix_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "test_projects"
    root.mkdir()
    lookalike = tmp_path / "test_projects_evil" / "song.flp"
    handler, calls = _handler_with_root(root)
    job = _FakeJob(payload={"path": str(lookalike), "ruleset": {}})

    with pytest.raises(sort.FlpSortPathOutsideRoot):
        handler(job)

    assert calls == []


def test_ensure_path_within_root_accepts_the_root_itself(tmp_path: Path) -> None:
    resolved = sort._ensure_path_within_root(tmp_path, tmp_path)

    assert resolved == tmp_path.resolve()


# ---------------------------------------------------------------------------
# diff-report emission
# ---------------------------------------------------------------------------


def test_diff_report_path_matches_flp_backups_naming_convention() -> None:
    when = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)

    report_path = sort.diff_report_path("song.flp", now=lambda: when)

    assert report_path.name == "song.2026-08-27T120000.diff.json"


def test_write_diff_report_writes_before_after_json_to_disk(tmp_path: Path) -> None:
    diff = sort.diff_report({1: "Kick"}, {1: "01 DRUMS - Kick"})
    path = tmp_path / "song.2026-08-27T120000.diff.json"

    sort.write_diff_report(path, diff)

    assert json.loads(path.read_text(encoding="utf-8")) == {"Kick": "01 DRUMS - Kick"}


def test_handler_writes_a_report_when_renames_occurred(tmp_path: Path) -> None:
    project = _project("Kick")
    target = tmp_path / "song.flp"
    handler = sort.build_flp_sort_handler(
        backup=lambda path, **_kwargs: Path(str(path) + ".bak"),
        loader=lambda path: project,
        saver=lambda proj, path: None,
        verifier=lambda path, diff, *, loader: True,
        safe_root=tmp_path,
    )
    job = _FakeJob(
        payload={"path": str(target), "ruleset": {"rules": [{"match": "Kick", "rename_to": "01 - Kick"}]}}
    )

    handler(job)

    reports = list(tmp_path.glob("song.*.diff.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text(encoding="utf-8")) == {"Kick": "01 - Kick"}


def test_handler_skips_the_report_when_nothing_changed(tmp_path: Path) -> None:
    project = _project("Untouched")
    target = tmp_path / "song.flp"
    handler = sort.build_flp_sort_handler(
        backup=lambda path, **_kwargs: Path(str(path) + ".bak"),
        loader=lambda path: project,
        saver=lambda proj, path: None,
        verifier=lambda path, diff, *, loader: True,
        safe_root=tmp_path,
    )
    job = _FakeJob(payload={"path": str(target), "ruleset": {"rules": [{"match": "Nonexistent", "rename_to": "x"}]}})

    handler(job)

    assert list(tmp_path.glob("song.*.diff.json")) == []


def test_handler_shares_one_timestamp_between_backup_and_its_diff_report(tmp_path: Path) -> None:
    project = _project("Kick")
    target = tmp_path / "song.flp"
    backup_calls: list[object] = []

    def backup(path, *, now):
        backup_calls.append(now())
        return Path(str(path) + ".bak")

    report_calls: list[Path] = []

    handler = sort.build_flp_sort_handler(
        backup=backup,
        loader=lambda path: project,
        saver=lambda proj, path: None,
        verifier=lambda path, diff, *, loader: True,
        report_writer=lambda path, diff: report_calls.append(path),
        safe_root=tmp_path,
        now=lambda: datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC),
    )
    job = _FakeJob(
        payload={"path": str(target), "ruleset": {"rules": [{"match": "Kick", "rename_to": "01 - Kick"}]}}
    )

    handler(job)

    assert backup_calls == [datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)]
    assert report_calls == [target.with_name("song.2026-08-27T120000.diff.json")]
