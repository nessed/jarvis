from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from db.jobs import (
    Job,
    SupabaseJobsRepository,
    checkpoint,
    claim_next,
    complete,
    enqueue,
    fail,
)


class InMemoryJobsRepository:
    """Replaceable test double implementing the same lifecycle contract."""

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    def enqueue(self, kind, payload, run_after=None):
        now = datetime.now(UTC)
        job = Job(
            id=str(uuid4()),
            kind=kind,
            payload=payload,
            status="queued",
            checkpoint={},
            run_after=run_after or now,
            created_at=now,
            updated_at=now,
        )
        self.jobs[job.id] = job
        return job

    def claim_next(self, kind_filter=None):
        now = datetime.now(UTC)
        candidates = [
            job
            for job in self.jobs.values()
            if job.status == "queued"
            and job.run_after <= now
            and (kind_filter is None or job.kind == kind_filter)
        ]
        if not candidates:
            return None
        job = min(candidates, key=lambda candidate: (candidate.run_after, candidate.created_at))
        return self._replace(job, status="running")

    def checkpoint(self, job_id, state):
        return self._replace(self.jobs[str(job_id)], checkpoint=state)

    def complete(self, job_id):
        return self._replace(self.jobs[str(job_id)], status="done")

    def fail(self, job_id, err):
        job = self.jobs[str(job_id)]
        return self._replace(job, status="failed", checkpoint={**job.checkpoint, "error": {"message": err}})

    def _replace(self, job, **changes):
        updated = Job(
            **{
                **job.__dict__,
                **changes,
                "updated_at": datetime.now(UTC),
            }
        )
        self.jobs[updated.id] = updated
        return updated


def test_full_lifecycle_preserves_checkpoint_and_error_state():
    repository = InMemoryJobsRepository()

    queued = enqueue("example", {"source": "test"}, repository=repository)
    claimed = claim_next(repository=repository)
    resumed = checkpoint(claimed.id, {"step": "started"}, repository=repository)
    failed = fail(resumed.id, "temporary problem", repository=repository)

    assert queued.status == "queued"
    assert claimed is not None and claimed.status == "running"
    assert failed.status == "failed"
    assert failed.checkpoint == {"step": "started", "error": {"message": "temporary problem"}}


def test_claim_filters_kind_and_skips_work_scheduled_for_the_future():
    repository = InMemoryJobsRepository()
    enqueue("local", {}, repository=repository)
    due = enqueue("remote", {}, repository=repository)
    enqueue("remote", {}, datetime.now(UTC) + timedelta(minutes=1), repository=repository)

    claimed = claim_next("remote", repository=repository)

    assert claimed is not None
    assert claimed.id == due.id
    assert claim_next("remote", repository=repository) is None


def test_complete_marks_claimed_job_done():
    repository = InMemoryJobsRepository()
    queued = enqueue("example", {}, repository=repository)
    claim_next(repository=repository)

    done = complete(queued.id, repository=repository)

    assert done.status == "done"


def test_repository_rejects_publishable_key_and_does_not_fall_back_to_old_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "sb_publishable_should_not_be_used")
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    with pytest.raises(RuntimeError, match="server-only"):
        SupabaseJobsRepository.from_env()

    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_publishable_rejected")
    with pytest.raises(RuntimeError, match="publishable/anon"):
        SupabaseJobsRepository.from_env()


def test_repository_accepts_secret_key_without_exposing_it(monkeypatch):
    created = []
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test_only")
    monkeypatch.setitem(
        sys.modules,
        "supabase",
        SimpleNamespace(create_client=lambda url, key: created.append((url, key)) or object()),
    )

    repository = SupabaseJobsRepository.from_env()

    assert isinstance(repository, SupabaseJobsRepository)
    assert len(created) == 1


def test_migration_enables_rls_and_denies_public_queue_access():
    migration = (
        Path(__file__).resolve().parents[2]
        / "db"
        / "migrations"
        / "0001_jobs.sql"
    ).read_text(encoding="utf-8").lower()

    assert "alter table public.jobs enable row level security" in migration
    assert "revoke all on table public.jobs from public, anon, authenticated" in migration
    assert "create policy" not in migration
    for function in ("claim_next_job", "checkpoint_job", "complete_job", "fail_job"):
        assert f"revoke execute on function public.{function}" in migration
