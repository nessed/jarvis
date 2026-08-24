from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from db.jobs import Job, checkpoint, claim_next, complete, enqueue, fail


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
