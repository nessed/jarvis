from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from db.jobs import Job
from executor import poller
from executor.poller import poll_once


def _job(*, checkpoint: dict[str, object] | None = None) -> Job:
    now = datetime.now(UTC)
    return Job(
        id="job-1",
        kind="whatsapp_webhook",
        payload={"entry": []},
        status="queued",
        checkpoint=checkpoint or {},
        run_after=now,
        created_at=now,
        updated_at=now,
    )


class FakeJobs:
    def __init__(self, job: Job | None) -> None:
        self.job = job
        self.calls: list[tuple[str, object]] = []

    def claim_next(self, kind_filter=None):
        self.calls.append(("claim_next", kind_filter))
        if self.job is None:
            return None
        self.job = replace(self.job, status="running")
        return self.job

    def checkpoint(self, job_id, state):
        self.calls.append(("checkpoint", state))
        assert self.job is not None and job_id == self.job.id
        self.job = replace(self.job, checkpoint=state)
        return self.job

    def complete(self, job_id):
        self.calls.append(("complete", job_id))
        assert self.job is not None and job_id == self.job.id
        self.job = replace(self.job, status="done")
        return self.job

    def fail(self, job_id, err):
        self.calls.append(("fail", err))
        assert self.job is not None and job_id == self.job.id
        self.job = replace(
            self.job,
            status="failed",
            checkpoint={**self.job.checkpoint, "error": {"message": err}},
        )
        return self.job


def test_poll_once_claims_checkpoints_and_completes_one_job():
    repository = FakeJobs(_job(checkpoint={"source": "meta"}))
    handled: list[str] = []

    result = poll_once(repository=repository, handler=lambda job: handled.append(job.id))

    assert result is not None and result.status == "done"
    assert result.checkpoint == {"source": "meta", "phase": "executor_started"}
    assert handled == ["job-1"]
    assert repository.calls == [
        ("claim_next", None),
        ("checkpoint", {"source": "meta", "phase": "executor_started"}),
        ("complete", "job-1"),
    ]


def test_poll_once_returns_idle_without_any_mutation():
    repository = FakeJobs(None)

    assert poll_once(repository=repository) is None
    assert repository.calls == [("claim_next", None)]


def test_poll_once_fails_handler_without_persisting_exception_text():
    repository = FakeJobs(_job())

    def broken_handler(job: Job) -> None:
        raise RuntimeError("credential-like text must not persist")

    result = poll_once(repository=repository, handler=broken_handler)

    assert result is not None and result.status == "failed"
    assert result.checkpoint["phase"] == "executor_started"
    assert result.checkpoint["error"] == {"message": "executor handler failed (RuntimeError)"}
    assert "credential-like" not in result.checkpoint["error"]["message"]
    assert repository.calls[-1] == ("fail", "executor handler failed (RuntimeError)")


def test_cli_loads_dotenv_before_creating_the_default_repository(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(poller, "load_dotenv", lambda: calls.append("dotenv"))
    monkeypatch.setattr(poller, "poll_once", lambda: calls.append("poll"))

    assert poller.main(["--once"]) == 0
    assert calls == ["dotenv", "poll"]


def test_cli_logs_transient_errors_by_type_then_keeps_polling(monkeypatch, caplog):
    attempts = 0
    sleeps: list[float] = []

    def transient_then_interrupt() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("sensitive job payload must not appear in logs")
        raise KeyboardInterrupt

    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(poller, "poll_once", transient_then_interrupt)
    monkeypatch.setattr(poller.time, "sleep", sleeps.append)

    assert poller.main(["--interval", "0.25"]) == 0
    assert sleeps == [0.25]
    assert [record.getMessage() for record in caplog.records] == [
        "executor poll failed (RuntimeError)"
    ]
    assert "sensitive job payload" not in caplog.text


def test_cli_once_surfaces_poll_errors_for_diagnostics(monkeypatch):
    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        poller,
        "poll_once",
        lambda: (_ for _ in ()).throw(RuntimeError("test-only failure")),
    )

    with pytest.raises(RuntimeError, match="test-only failure"):
        poller.main(["--once"])
