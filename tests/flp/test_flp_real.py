r"""Real-`.flp` probes for the PyFLP lane.

These are excluded from the default run by the ``realflp`` marker (see
``pytest.ini``) because they need the Python 3.11 sandbox, not the main
3.12 ``.venv``. Run them deliberately:

    .venv311\Scripts\python.exe -m pytest -q -m realflp -p no:cacheprovider --basetemp=.pytest-basetemp

The fixture `.flp` is never committed. Point ``JARVIS_FLP_FIXTURE`` at a real
project file (a copy, never an original); otherwise these skip.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

import pytest

pytestmark = pytest.mark.realflp

# Belt-and-braces under the marker: PyFLP's empty `EventEnum` needs a CPython
# whose `enum` still reaches `_missing_`. The guard that breaks it landed in
# 3.11.6 and is in every 3.12+. See docs/blockers/pyflp-python-312.md.
PYFLP_OK = (3, 8) <= sys.version_info[:3] < (3, 11, 6)


def _fixture_path() -> pathlib.Path:
    raw = os.environ.get("JARVIS_FLP_FIXTURE")
    if not raw:
        pytest.skip("JARVIS_FLP_FIXTURE is not set; no real .flp to test against")
    path = pathlib.Path(raw)
    if not path.is_file():
        pytest.skip(f"JARVIS_FLP_FIXTURE does not exist: {path}")
    return path


@pytest.fixture(autouse=True)
def _require_supported_interpreter() -> None:
    if not PYFLP_OK:
        pytest.skip(
            "PyFLP 2.2.1 needs CPython >=3.8,<3.11.6; this is "
            f"{'.'.join(str(p) for p in sys.version_info[:3])}. Use .venv311."
        )


def test_event_enum_is_constructible() -> None:
    """The exact call that raises TypeError on 3.11.6+ and 3.12+."""
    from pyflp._events import AsciiEvent, EventEnum
    from pyflp.project import ProjectID

    member = EventEnum(int(ProjectID.FLVersion))
    assert int(member) == int(ProjectID.FLVersion)

    event = AsciiEvent(ProjectID.FLVersion, b"20.8.4.2576\x00")
    assert int(event.id) == int(ProjectID.FLVersion)
    assert event.value.startswith("20.8.4")


def test_parse_real_flp() -> None:
    import pyflp

    project = pyflp.parse(_fixture_path())
    assert project.ppq > 0
    assert len(project.channels) > 0
    assert len(project.mixer) > 0


def test_save_round_trip_preserves_a_rename(tmp_path: pathlib.Path) -> None:
    """save() must produce a file that re-parses with the edit intact."""
    import pyflp

    project = pyflp.parse(_fixture_path())
    original = project.channels[0].name
    renamed = "JARVIS round trip"
    assert original != renamed

    project.channels[0].name = renamed
    out = tmp_path / "round_trip.flp"
    pyflp.save(project, out)
    assert out.stat().st_size > 0

    reloaded = pyflp.parse(out)
    assert reloaded.channels[0].name == renamed
    assert len(reloaded.channels) == len(project.channels)
    assert reloaded.ppq == project.ppq


def test_flp_sort_handler_runs_the_full_pipeline_against_a_real_flp(tmp_path: pathlib.Path) -> None:
    """The one thing nothing on disk had ever proven: not PyFLP alone, but
    ``build_flp_sort_handler``'s actual backup -> load -> apply_rules -> save
    -> verify -> diff-report pipeline, running for real against a real
    ``.flp`` -- every other proof of this module is against fakes/stubs.

    Uses PyFLP's own upstream fixture (see the module docstring for how to
    fetch it) via ``JARVIS_FLP_FIXTURE``, copied into ``tmp_path`` first and
    run with ``safe_root`` pointed at ``tmp_path`` -- so this never touches
    ``test_projects/`` or any file this session did not create for the
    duration of this one test.
    """
    import shutil

    from executor.flp.sort import FlpSortVerificationFailed, build_flp_sort_handler

    class _Job:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

    target = tmp_path / "sort_target.flp"
    shutil.copy2(_fixture_path(), target)

    import pyflp

    before = pyflp.parse(target)
    before_names = {insert.iid: insert.name for insert in before.mixer}
    assert "Master" in before_names.values(), (
        "fixture's mixer has no insert named 'Master' to exercise the rename "
        "rule against -- fixture shape changed, update this test's ruleset"
    )

    handler = build_flp_sort_handler(safe_root=tmp_path)
    ruleset = {"rules": [{"match": "Master", "rename_to": "JARVIS Master", "position": None}]}

    try:
        handler(_Job({"path": str(target), "ruleset": ruleset}))
    except FlpSortVerificationFailed as exc:  # pragma: no cover - failure path, not the happy path
        pytest.fail(f"real end-to-end flp_sort run failed verification: {exc}")

    # The saved file actually carries the rename, re-parsed from scratch --
    # not just that build_flp_sort_handler's own verify() said so.
    after = pyflp.parse(target)
    after_names = {insert.iid: insert.name for insert in after.mixer}
    master_iid = next(iid for iid, name in before_names.items() if name == "Master")
    assert after_names[master_iid] == "JARVIS Master"
    assert "Master" not in after_names.values()

    # A timestamped backup of the pre-rename file exists alongside it.
    backups = list(tmp_path.glob("sort_target.*.bak.flp"))
    assert len(backups) == 1, f"expected exactly one backup, found {backups}"

    # A diff report was written (a rename happened, so MixerDiff is truthy)
    # and it names the real change made.
    reports = list(tmp_path.glob("sort_target.*.diff.json"))
    assert len(reports) == 1, f"expected exactly one diff report, found {reports}"
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report.get("Master") == "JARVIS Master"
