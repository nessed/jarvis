r"""Real-`.flp` probes for the PyFLP lane.

These are excluded from the default run by the ``realflp`` marker (see
``pytest.ini``) because they need the Python 3.11 sandbox, not the main
3.12 ``.venv``. Run them deliberately:

    .venv311\Scripts\python.exe -m pytest -q -m realflp -p no:cacheprovider --basetemp=.pytest-basetemp

The fixture `.flp` is never committed. Point ``JARVIS_FLP_FIXTURE`` at a real
project file (a copy, never an original); otherwise these skip.
"""

from __future__ import annotations

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
