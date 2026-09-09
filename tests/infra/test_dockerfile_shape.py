"""A few Dockerfile facts worth pinning down as tests, not just prose.

`tests/infra/test_image_contents.py` already exercises the `COPY` lines
themselves; this covers the platform pin, the requirements file it installs,
and that `bus.main:app` -- the CMD's target -- actually resolves.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "infra" / "docker" / "Dockerfile"


def _text() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def test_the_image_targets_amd64_not_the_oracle_era_arm64() -> None:
    """bus-offbox-packaging, 9 Sep 2026: the target is now an x86 box (U17)."""
    text = _text()

    assert "FROM --platform=linux/amd64" in text
    assert "--platform=linux/arm64" not in text


def test_it_installs_the_brain_requirements_file_not_the_old_bus_one() -> None:
    text = _text()

    assert "requirements-brain.txt" in text
    assert "requirements-bus.txt" not in text
    assert not (REPO_ROOT / "infra" / "docker" / "requirements-bus.txt").exists()


def test_the_cmd_target_actually_resolves() -> None:
    import bus.main  # noqa: F401 -- import is the assertion


def test_state_env_vars_point_under_the_mounted_state_directory() -> None:
    text = _text()

    assert "JARVIS_WEBHOOK_DEDUP_DB_PATH=/app/state/" in text
    assert "MEMORY_DB_PATH=/app/state/" in text


def test_only_one_uvicorn_worker_is_configured() -> None:
    """Two workers would race on the same sqlite files under /app/state --
    same reasoning the original enqueue-only image already carried."""
    text = _text()

    assert '"--workers", "1"' in text
