"""Integration lifecycle test; skipped until the user has configured Supabase."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from uuid import uuid4

import pytest

from db.jobs import (
    SupabaseJobsRepository,
    checkpoint,
    claim_next,
    complete,
    enqueue,
    fail,
    retry_or_dead_letter,
)


def _env_has_supabase_credentials() -> bool:
    """Check local configuration without emitting sensitive values."""
    configured = bool(
        os.environ.get("SUPABASE_URL")
        and (os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    )
    if configured:
        return True
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return False
    keys = set()
    for line in env_path.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and value.strip() and name in {
            "SUPABASE_URL",
            "SUPABASE_SECRET_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
        }:
            keys.add(name)
    return "SUPABASE_URL" in keys and bool(
        {"SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"} & keys
    )


@pytest.mark.skipif(not _env_has_supabase_credentials(), reason="Supabase credentials are not configured")
def test_real_supabase_full_job_lifecycle(monkeypatch):
    # Load only the required values into the process; nothing is logged.
    env_path = Path(__file__).resolve().parents[2] / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and name in {
            "SUPABASE_URL",
            "SUPABASE_SECRET_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
        } and value.strip():
            monkeypatch.setenv(name, value.strip())

    repository = SupabaseJobsRepository.from_env()
    kind = f"integration-{uuid4()}"
    queued = enqueue(kind, {"test": True}, repository=repository)
    claimed = claim_next(kind, repository=repository)
    assert claimed is not None and claimed.id == queued.id and claimed.status == "running"

    saved = checkpoint(claimed.id, {"phase": "checkpointed"}, repository=repository)
    assert saved.checkpoint == {"phase": "checkpointed"}
    done = complete(claimed.id, repository=repository)
    assert done.status == "done"

    failing = enqueue(kind, {}, repository=repository)
    second_claim = claim_next(kind, repository=repository)
    assert second_claim is not None and second_claim.id == failing.id
    failed = fail(second_claim.id, "integration failure", repository=repository)
    assert failed.status == "failed"
    assert failed.checkpoint["error"]["message"] == "integration failure"


def _load_supabase_env(monkeypatch) -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and name in {
            "SUPABASE_URL",
            "SUPABASE_SECRET_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
        } and value.strip():
            monkeypatch.setenv(name, value.strip())


def _live_repository_with_0002_applied(monkeypatch) -> SupabaseJobsRepository | None:
    """Return a live repository only once the 0002 columns/RPCs are reachable.

    The queue_durability lane cannot apply db/migrations/0002_job_retries.sql
    to the live project itself (no Postgres driver or Supabase CLI in this
    venv, and adding one requires a requirements.txt change out of scope for
    this lane). Skip cleanly with a clear reason instead of a confusing
    schema error until the orchestrator applies it.
    """
    _load_supabase_env(monkeypatch)
    repository = SupabaseJobsRepository.from_env()
    probe_kind = f"queue-durability-probe-{uuid4()}"
    queued = enqueue(probe_kind, {}, repository=repository)
    try:
        claimed = claim_next(probe_kind, repository=repository)
        assert claimed is not None
        retry_or_dead_letter(claimed.id, "probe cleanup", 0, repository=repository)
    except Exception as exc:  # pragma: no cover - depends on live schema state
        try:
            fail(queued.id, "probe cleanup (schema check failed)", repository=repository)
        except Exception:
            pass  # best-effort terminal state for a disposable probe row
        pytest.skip(
            "0002 migration (attempts/retry_or_dead_letter_job) is not applied to the "
            f"live Supabase project yet: {type(exc).__name__}"
        )
    else:
        fail(queued.id, "probe cleanup", repository=repository)
    return repository


@pytest.mark.skipif(not _env_has_supabase_credentials(), reason="Supabase credentials are not configured")
def test_real_supabase_concurrent_claims_never_double_claim_or_drop_a_job(monkeypatch):
    repository = _live_repository_with_0002_applied(monkeypatch)
    kind = f"integration-concurrent-{uuid4()}"
    expected_ids = {enqueue(kind, {}, repository=repository).id for _ in range(6)}

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: claim_next(kind, repository=repository), range(12)))

    claimed = [job.id for job in results if job is not None]
    for job_id in claimed:
        fail(job_id, "integration concurrency cleanup", repository=repository)

    assert len(claimed) == len(expected_ids)
    assert set(claimed) == expected_ids
    assert len(set(claimed)) == len(claimed)
