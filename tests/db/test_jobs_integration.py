"""Integration lifecycle test; skipped until the user has configured Supabase."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from db.jobs import SupabaseJobsRepository, checkpoint, claim_next, complete, enqueue, fail


def _env_has_supabase_credentials() -> bool:
    """Check local configuration without emitting sensitive values."""
    configured = bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))
    if configured:
        return True
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return False
    keys = set()
    for line in env_path.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and value.strip() and name in {"SUPABASE_URL", "SUPABASE_KEY"}:
            keys.add(name)
    return keys == {"SUPABASE_URL", "SUPABASE_KEY"}


@pytest.mark.skipif(not _env_has_supabase_credentials(), reason="Supabase credentials are not configured")
def test_real_supabase_full_job_lifecycle(monkeypatch):
    # Load only the two required values into the process; nothing is logged.
    env_path = Path(__file__).resolve().parents[2] / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and name in {"SUPABASE_URL", "SUPABASE_KEY"} and value.strip():
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
