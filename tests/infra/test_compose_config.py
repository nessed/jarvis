"""`docker compose config` cannot run here (no Docker on this laptop), so
this parses the YAML directly and checks the shape the runbook and
infra/README.md describe -- the offline stand-in `bus-offbox-packaging`
step 5 asked for.
"""

from __future__ import annotations

from pathlib import Path

import yaml

COMPOSE_PATH = Path(__file__).resolve().parents[2] / "infra" / "docker" / "compose.yaml"


def _load() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_the_file_is_valid_yaml_with_the_three_services() -> None:
    config = _load()

    assert set(config["services"]) == {"bus", "ollama", "ollama-pull"}


def test_the_bus_is_bound_to_loopback_only() -> None:
    config = _load()

    ports = config["services"]["bus"]["ports"]
    assert ports == ["127.0.0.1:8000:8000"]


def test_the_ollama_sidecar_is_not_published_to_the_host() -> None:
    """`expose` (internal to the compose network) not `ports` (host-bound)."""
    ollama = _load()["services"]["ollama"]

    assert "ports" not in ollama
    assert ollama["expose"] == ["11434"]


def test_the_bus_reaches_the_sidecar_by_its_compose_dns_name() -> None:
    env = _load()["services"]["bus"]["environment"]

    assert env["OLLAMA_BASE_URL"] == "http://ollama:11434"


def test_extraction_stays_off_this_box() -> None:
    env = _load()["services"]["bus"]["environment"]

    assert str(env["JARVIS_DISTILL"]) == "0"


def test_state_paths_point_at_the_shared_volume() -> None:
    env = _load()["services"]["bus"]["environment"]

    assert env["JARVIS_WEBHOOK_DEDUP_DB_PATH"].startswith("/app/state/")
    assert env["MEMORY_DB_PATH"].startswith("/app/state/")


def test_both_named_volumes_are_declared_and_used() -> None:
    config = _load()

    assert set(config["volumes"]) == {"brain-state", "ollama-models"}
    assert "brain-state:/app/state" in config["services"]["bus"]["volumes"]
    assert "ollama-models:/root/.ollama" in config["services"]["ollama"]["volumes"]


def test_the_bus_waits_on_the_sidecar_and_the_model_pull() -> None:
    depends_on = _load()["services"]["bus"]["depends_on"]

    assert depends_on["ollama"]["condition"] == "service_healthy"
    assert depends_on["ollama-pull"]["condition"] == "service_completed_successfully"


def test_the_model_pull_targets_the_same_model_the_bus_is_configured_for() -> None:
    config = _load()
    bus_model = config["services"]["bus"]["environment"]["OLLAMA_EMBEDDING_MODEL"]

    assert bus_model in " ".join(config["services"]["ollama-pull"]["entrypoint"])


def test_the_secrets_file_is_never_written_into_the_repo() -> None:
    """`env_file` names a path on the VPS; it must not resolve to anything
    this repo tracks, or the "never in this repo" comment above it is a lie
    a future edit could make true."""
    bus = _load()["services"]["bus"]
    env_files = bus["env_file"]

    assert env_files == ["/home/jarvis/jarvis.env"]
