from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
import threading
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
    retry_or_dead_letter,
    set_timeout,
)


class InMemoryJobsRepository:
    """Replaceable test double implementing the same lifecycle contract."""

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        # Real atomicity comes from Postgres `for update skip locked`; this
        # lock makes the fake's check-then-set claim genuinely race-free too,
        # so a concurrent-claim test against it proves something real rather
        # than depending on accidental GIL timing.
        self._claim_lock = threading.Lock()

    def enqueue(self, kind, payload, run_after=None, max_attempts=None):
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
            **({"max_attempts": max_attempts} if max_attempts is not None else {}),
        )
        self.jobs[job.id] = job
        return job

    def claim_next(self, kind_filter=None):
        with self._claim_lock:
            now = datetime.now(UTC)
            candidates = [
                job
                for job in self.jobs.values()
                if (
                    (job.status == "queued" and job.run_after <= now)
                    or (
                        job.status == "running"
                        and job.updated_at + timedelta(seconds=job.timeout_seconds) < now
                    )
                )
                and (kind_filter is None or job.kind == kind_filter)
            ]
            if not candidates:
                return None
            job = min(candidates, key=lambda candidate: (candidate.run_after, candidate.created_at))
            return self._replace(job, status="running", attempts=job.attempts + 1)

    def checkpoint(self, job_id, state):
        return self._replace(self.jobs[str(job_id)], checkpoint=state)

    def complete(self, job_id):
        return self._replace(self.jobs[str(job_id)], status="done")

    def fail(self, job_id, err):
        job = self.jobs[str(job_id)]
        return self._replace(job, status="failed", checkpoint={**job.checkpoint, "error": {"message": err}})

    def retry_or_dead_letter(self, job_id, err, delay_seconds=0):
        job = self.jobs[str(job_id)]
        checkpoint_state = {
            **job.checkpoint,
            "error": {"message": err},
            "attempts": job.attempts,
        }
        if job.attempts >= job.max_attempts:
            return self._replace(job, status="dead_letter", checkpoint=checkpoint_state)
        return self._replace(
            job,
            status="queued",
            checkpoint=checkpoint_state,
            run_after=datetime.now(UTC) + timedelta(seconds=max(0.0, delay_seconds)),
        )

    def set_timeout(self, job_id, timeout_seconds):
        return self._replace(self.jobs[str(job_id)], timeout_seconds=max(1, int(timeout_seconds)))

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


def test_concurrent_claims_never_double_claim_or_drop_a_job():
    repository = InMemoryJobsRepository()
    expected_ids = {enqueue("concurrent", {}, repository=repository).id for _ in range(8)}

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: claim_next("concurrent", repository=repository), range(16)))

    claimed = [job.id for job in results if job is not None]
    assert len(claimed) == len(expected_ids)
    assert set(claimed) == expected_ids
    assert len(set(claimed)) == len(claimed)


def test_complete_marks_claimed_job_done():
    repository = InMemoryJobsRepository()
    queued = enqueue("example", {}, repository=repository)
    claim_next(repository=repository)

    done = complete(queued.id, repository=repository)

    assert done.status == "done"


def test_claim_increments_attempts_on_every_claim():
    repository = InMemoryJobsRepository()
    queued = enqueue("example", {}, repository=repository)
    assert queued.attempts == 0

    first_claim = claim_next(repository=repository)
    assert first_claim.attempts == 1


def test_retry_or_dead_letter_requeues_with_backoff_while_attempts_remain():
    repository = InMemoryJobsRepository()
    queued = enqueue("example", {}, max_attempts=3, repository=repository)
    claimed = claim_next(repository=repository)
    assert claimed.attempts == 1

    retried = retry_or_dead_letter(claimed.id, "transient error", 30, repository=repository)

    assert retried.status == "queued"
    assert retried.checkpoint["error"] == {"message": "transient error"}
    assert retried.checkpoint["attempts"] == 1
    assert retried.run_after > queued.run_after + timedelta(seconds=29)


def test_retry_or_dead_letter_dead_letters_once_max_attempts_is_exhausted():
    repository = InMemoryJobsRepository()
    enqueue("example", {}, max_attempts=1, repository=repository)
    claimed = claim_next(repository=repository)
    assert claimed.attempts == 1

    exhausted = retry_or_dead_letter(claimed.id, "final error", 30, repository=repository)

    assert exhausted.status == "dead_letter"
    assert exhausted.checkpoint["error"] == {"message": "final error"}
    assert claim_next(repository=repository) is None


def test_stale_running_job_is_reclaimed_after_its_own_timeout():
    repository = InMemoryJobsRepository()
    enqueue("example", {}, repository=repository)
    first_claim = claim_next(repository=repository)
    set_timeout(first_claim.id, 1, repository=repository)
    stale_job = repository.jobs[first_claim.id]
    repository.jobs[first_claim.id] = replace(
        stale_job, updated_at=datetime.now(UTC) - timedelta(seconds=5)
    )

    reclaimed = claim_next(repository=repository)

    assert reclaimed is not None and reclaimed.id == first_claim.id
    assert reclaimed.attempts == 2


def test_live_running_job_within_its_timeout_is_not_reclaimed():
    repository = InMemoryJobsRepository()
    enqueue("example", {}, repository=repository)
    claim_next(repository=repository)

    assert claim_next(repository=repository) is None


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


def test_retry_migration_adds_attempts_columns_and_dead_letter_state_only_additively():
    migration = (
        Path(__file__).resolve().parents[2]
        / "db"
        / "migrations"
        / "0002_job_retries.sql"
    ).read_text(encoding="utf-8").lower()

    assert "add column if not exists attempts" in migration
    assert "add column if not exists max_attempts" in migration
    assert "add column if not exists timeout_seconds" in migration
    assert "'dead_letter'" in migration
    assert "drop table" not in migration
    assert "drop column" not in migration
    for function in ("retry_or_dead_letter_job", "set_job_timeout"):
        assert f"revoke execute on function public.{function}" in migration
        assert f"grant execute on function public.{function}" in migration
