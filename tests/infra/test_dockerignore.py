"""The repo-root .dockerignore must stay consistent with what the Dockerfile
actually COPYs -- an ignored parent directory silently starves a COPY line
of its source, which fails the build with no hint that .dockerignore is why.
"""

from __future__ import annotations

from pathlib import Path

DOCKERIGNORE = Path(__file__).resolve().parents[2] / ".dockerignore"


def _lines() -> list[str]:
    return [
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_memory_and_executor_are_not_blanket_excluded() -> None:
    """bus-offbox-packaging (9 Sep 2026): the Dockerfile now COPYs memory/ in
    full and a named slice of executor/. A bare 'memory/' or 'executor/'
    entry here would make those COPY lines fail outright."""
    lines = _lines()

    assert "memory/" not in lines
    assert "executor/" not in lines


def test_the_heavy_executor_subtrees_are_still_excluded() -> None:
    lines = _lines()

    for excluded in ("executor/flp/", "executor/system_control/", "executor/handlers/distill.py"):
        assert excluded in lines


def test_secrets_and_local_state_stay_excluded() -> None:
    lines = _lines()

    assert ".env" in lines
    assert "*.db" in lines
