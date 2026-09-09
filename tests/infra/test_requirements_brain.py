"""requirements-brain.txt must never drift from requirements.txt.

Every pin in the brain's requirements file is supposed to be the exact line
requirements.txt already carries for that package -- the whole point being
that the container runs the same library version the offline suite vetted.
This is the automated half of "diff the two when either changes."
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRAIN_REQUIREMENTS = ROOT / "infra" / "docker" / "requirements-brain.txt"
REPO_REQUIREMENTS = ROOT / "requirements.txt"

# The banned set this pruned image must never need a wheel for -- mirrors
# tests/infra/test_image_contents.py's import-level check, one layer down.
BANNED_PACKAGES = frozenset(
    {
        "torch",
        "torchaudio",
        "kokoro",
        "openwakeword",
        "pipecat-ai",
        "silero-vad",
        "sounddevice",
        "soundfile",
        "onnxruntime",
        "pyflp",
        "psutil",
        "pywinauto",
        "comtypes",
        "psycopg",
    }
)


def _pins(path: Path) -> dict[str, str]:
    """{package: 'package==version'} for every pinned, non-comment line."""
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name = line.split("==", 1)[0].strip()
        pins[name] = line
    return pins


def test_the_brain_file_has_at_least_the_packages_the_bus_needs() -> None:
    pins = _pins(BRAIN_REQUIREMENTS)

    for package in ("fastapi", "uvicorn", "httpx", "supabase", "openai", "python-dotenv"):
        assert package in pins


def test_the_brain_file_pins_sqlite_vec_and_mem0_for_the_memory_package() -> None:
    pins = _pins(BRAIN_REQUIREMENTS)

    assert "sqlite-vec" in pins
    assert "mem0ai" in pins


def test_every_brain_pin_matches_the_repo_requirements_exactly() -> None:
    brain_pins = _pins(BRAIN_REQUIREMENTS)
    repo_pins = _pins(REPO_REQUIREMENTS)

    drifted = {
        name: (pin, repo_pins.get(name))
        for name, pin in brain_pins.items()
        if repo_pins.get(name) != pin
    }
    assert drifted == {}, f"requirements-brain.txt has drifted from requirements.txt: {drifted}"


def test_no_banned_package_is_pinned_in_the_brain_file() -> None:
    pins = _pins(BRAIN_REQUIREMENTS)

    assert set(pins) & BANNED_PACKAGES == set()
