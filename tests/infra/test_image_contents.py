"""What the brain image actually copies, checked without Docker.

Docker is not installed on this laptop (`docker --version` fails, 8 Sep
2026), so `docker build` cannot run here. This is the offline stand-in the
task asked for: parse the Dockerfile's own `COPY` lines, then grep every file
under each copied source for the imports that must never reach this image --
the same set `tests/executor/test_conversation_service.py` and
`tests/bus/test_conversation_runner.py` already prove `import`-time against a
running process. This test proves it against the *files*, so a module added
to `executor/handlers/` later that happens to import one of them fails here
even if nothing currently calls it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "infra" / "docker" / "Dockerfile"

# Same set the offbox import-weight tests already assert against a live
# process (tests/executor/test_conversation_service.py,
# tests/bus/test_conversation_runner.py). Checked here as source text instead
# of imported modules, so an unused-but-present import still fails the build.
BANNED_MODULES = ("torch", "kokoro", "pywinauto", "pyflp", "sounddevice", "voice")

_COPY_LINE = re.compile(r"^\s*COPY\s+(?P<source>\S+)\s+(?P<dest>\S+)\s*$")

# Column zero only, deliberately: an import indented inside a function body
# (executor/handlers/whatsapp.py's voice/STT/TTS defaults, for one) runs only
# if that function is ever called, and the bus never calls those -- only
# text reaches bus/conversation_runner.py, voice always still queues. A
# module-level import always runs the moment the module is imported, which
# is the actual risk this test exists to catch.
_TOPLEVEL_IMPORT_LINE = re.compile(
    r"^(?:import\s+(?P<mod1>[\w.]+)|from\s+(?P<mod2>[\w.]+)\s+import\b)", re.MULTILINE
)


def _copy_sources() -> list[Path]:
    """Every source path a plain `COPY <src> <dest>` line in the Dockerfile names.

    Deliberately only the two-argument form actually used here -- no
    multi-stage `--from=`, no `COPY . .`. If the Dockerfile ever grows one of
    those, this should fail loudly (an empty list below) rather than silently
    stop checking anything.
    """
    sources: list[Path] = []
    for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        match = _COPY_LINE.match(line)
        if match is None:
            continue
        source = match.group("source")
        if source.startswith("--"):
            continue
        sources.append(REPO_ROOT / source)
    return sources


def _python_files(source: Path) -> list[Path]:
    if source.is_file():
        return [source] if source.suffix == ".py" else []
    if source.is_dir():
        return sorted(p for p in source.rglob("*.py") if "__pycache__" not in p.parts)
    raise AssertionError(f"Dockerfile COPY source does not exist: {source}")


def test_the_dockerfile_has_at_least_one_copy_line() -> None:
    """A parser that silently finds nothing is worse than no parser at all."""
    assert len(_copy_sources()) >= 5


@pytest.mark.parametrize("source", _copy_sources(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_every_copied_python_file_avoids_the_banned_imports(source: Path) -> None:
    for path in _python_files(source):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _TOPLEVEL_IMPORT_LINE.finditer(text):
            module = (match.group("mod1") or match.group("mod2")).split(".")[0]
            assert module not in BANNED_MODULES, (
                f"{path.relative_to(REPO_ROOT)} imports {module!r}, which the brain "
                "image must never carry (infra/README.md's 'image now carries the "
                "brain, not just the inbox' section)"
            )


def test_every_copy_source_actually_exists() -> None:
    """Redundant with the per-file test's own assertion, kept as a fast,
    single-failure summary when the Dockerfile is edited and a path typo'd."""
    missing = [s for s in _copy_sources() if not s.exists()]
    assert missing == []


class TestTheCheckerItself:
    """Proves the regex actually discriminates, so the passing test above is
    evidence and not a checker that would pass on anything."""

    def test_a_module_level_banned_import_is_caught(self, tmp_path) -> None:
        offender = tmp_path / "offender.py"
        offender.write_text("import torch\n", encoding="utf-8")

        matches = [
            (m.group("mod1") or m.group("mod2")).split(".")[0]
            for m in _TOPLEVEL_IMPORT_LINE.finditer(offender.read_text())
        ]
        assert "torch" in matches

    def test_an_indented_lazy_import_is_ignored(self, tmp_path) -> None:
        lazy = tmp_path / "lazy.py"
        lazy.write_text("def f():\n    import torch\n    return torch\n", encoding="utf-8")

        matches = [
            (m.group("mod1") or m.group("mod2")).split(".")[0]
            for m in _TOPLEVEL_IMPORT_LINE.finditer(lazy.read_text())
        ]
        assert matches == []
