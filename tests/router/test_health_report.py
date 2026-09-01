from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from router import health_report


def _snapshot(**overrides) -> dict[str, dict[str, object]]:
    base = {
        "groq": {
            "last_status": 429,
            "cooldown_seconds_remaining": 60.0,
            "rate_limit_headers": {"retry-after": "60"},
        },
        "cerebras": {
            "last_status": 200,
            "cooldown_seconds_remaining": 0.0,
            "rate_limit_headers": {},
        },
    }
    base.update(overrides)
    return base


def test_a_published_snapshot_reads_back(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    health_report.write(_snapshot(), path)

    reported = health_report.read(path)

    assert reported is not None
    assert reported["groq"]["last_status"] == 429
    assert reported["groq"]["rate_limit_headers"] == {"retry-after": "60"}
    assert reported["cerebras"]["last_status"] == 200


def test_every_entry_is_marked_as_actually_reported(tmp_path: Path) -> None:
    """``/status`` has to tell "measured and fine" from "never measured"."""
    path = tmp_path / "health.json"
    health_report.write(_snapshot(), path)

    reported = health_report.read(path)

    assert all(entry["reported"] is True for entry in reported.values())


def test_the_countdown_is_aged_by_how_long_ago_it_was_written(tmp_path: Path) -> None:
    """A monotonic deadline means nothing across processes; elapsed time does."""
    path = tmp_path / "health.json"
    document = {
        "reported_at": time.time() - 20.0,
        "providers": {"groq": {"last_status": 429, "cooldown_seconds_remaining": 60.0}},
    }
    path.write_text(json.dumps(document), encoding="utf-8")

    reported = health_report.read(path)

    assert 39.0 <= reported["groq"]["cooldown_seconds_remaining"] <= 41.0
    assert 19.0 <= reported["groq"]["reported_age_seconds"] <= 21.0


def test_an_expired_countdown_floors_at_zero_rather_than_going_negative(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    document = {
        "reported_at": time.time() - 120.0,
        "providers": {"groq": {"last_status": 429, "cooldown_seconds_remaining": 60.0}},
    }
    path.write_text(json.dumps(document), encoding="utf-8")

    assert health_report.read(path)["groq"]["cooldown_seconds_remaining"] == 0.0


def test_no_file_means_nobody_has_reported(tmp_path: Path) -> None:
    assert health_report.read(tmp_path / "missing.json") is None


def test_a_stale_snapshot_is_not_believed(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    path.write_text(
        json.dumps({"reported_at": time.time() - 3600.0, "providers": {"groq": {}}}), encoding="utf-8"
    )

    assert health_report.read(path) is None
    assert health_report.read(path, max_age_seconds=7200.0) is not None


@pytest.mark.parametrize(
    "body",
    ['{"providers": {}}', '{"reported_at": "soon", "providers": {}}', "{}", "not json at all", "[]"],
)
def test_a_malformed_snapshot_reads_as_nobody_having_reported(tmp_path: Path, body: str) -> None:
    path = tmp_path / "health.json"
    path.write_text(body, encoding="utf-8")

    assert health_report.read(path) is None


def test_a_non_mapping_provider_entry_is_skipped_not_fatal(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    path.write_text(
        json.dumps({"reported_at": time.time(), "providers": {"groq": "broken", "cerebras": {}}}),
        encoding="utf-8",
    )

    reported = health_report.read(path)

    assert set(reported) == {"cerebras"}


def test_writing_never_raises_when_the_path_is_unusable(tmp_path: Path) -> None:
    """It is called from the poll loop; a filesystem problem must not stop it."""
    unusable = tmp_path / "health.json"
    unusable.mkdir()

    health_report.write(_snapshot(), unusable)

    assert health_report.read(unusable) is None


def test_a_reader_never_sees_a_half_written_document(tmp_path: Path) -> None:
    """The write goes to a temp sibling and is moved into place."""
    path = tmp_path / "health.json"
    health_report.write(_snapshot(), path)
    health_report.write(_snapshot(), path)

    assert list(p.name for p in tmp_path.iterdir()) == ["health.json"]
    assert health_report.read(path) is not None


# --- deciding when a rewrite is worth it --------------------------------------


def test_the_countdown_alone_is_not_a_reason_to_rewrite() -> None:
    """Otherwise the poll loop rewrites the file several times a second forever."""
    ticking = _snapshot()
    ticking["groq"] = {**ticking["groq"], "cooldown_seconds_remaining": 41.0}

    assert health_report.material_state(_snapshot()) == health_report.material_state(ticking)


def test_starting_or_ending_a_cooldown_is_a_reason_to_rewrite() -> None:
    recovered = _snapshot()
    recovered["groq"] = {**recovered["groq"], "cooldown_seconds_remaining": 0.0}

    assert health_report.material_state(_snapshot()) != health_report.material_state(recovered)


def test_a_new_status_code_is_a_reason_to_rewrite() -> None:
    changed = _snapshot()
    changed["groq"] = {**changed["groq"], "last_status": 503}

    assert health_report.material_state(_snapshot()) != health_report.material_state(changed)


def test_new_rate_limit_headers_are_a_reason_to_rewrite() -> None:
    changed = _snapshot()
    changed["groq"] = {**changed["groq"], "rate_limit_headers": {"retry-after": "5"}}

    assert health_report.material_state(_snapshot()) != health_report.material_state(changed)


def test_the_report_path_honours_its_env_override(tmp_path: Path) -> None:
    assert health_report.report_path({}) == health_report.DEFAULT_REPORT_PATH
    assert health_report.report_path(
        {"JARVIS_PROVIDER_HEALTH_REPORT": str(tmp_path / "elsewhere.json")}
    ) == tmp_path / "elsewhere.json"
