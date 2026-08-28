from __future__ import annotations

import threading
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from db.jobs import Job
from executor import poller
from executor.flp.sort import ReorderNotSupported
from executor.poller import HandlerRegistration, poll_once


def _job(*, checkpoint: dict[str, object] | None = None, attempts: int = 1, max_attempts: int = 5) -> Job:
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
        attempts=attempts,
        max_attempts=max_attempts,
    )


class FakeJobs:
    """Mimics claim_next's post-claim attempts increment and the new
    retry/dead-letter/timeout RPCs, without needing a real database."""

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

    def retry_or_dead_letter(self, job_id, err, delay_seconds=0):
        self.calls.append(("retry_or_dead_letter", err, delay_seconds))
        assert self.job is not None and job_id == self.job.id
        checkpoint_state = {
            **self.job.checkpoint,
            "error": {"message": err},
            "attempts": self.job.attempts,
        }
        if self.job.attempts >= self.job.max_attempts:
            self.job = replace(self.job, status="dead_letter", checkpoint=checkpoint_state)
        else:
            self.job = replace(self.job, status="queued", checkpoint=checkpoint_state)
        return self.job

    def set_timeout(self, job_id, timeout_seconds):
        self.calls.append(("set_timeout", timeout_seconds))
        assert self.job is not None and job_id == self.job.id
        self.job = replace(self.job, timeout_seconds=timeout_seconds)
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


def test_poll_once_dispatches_registered_handler_for_known_job_kind():
    repository = FakeJobs(_job(checkpoint={"source": "meta"}))
    handled: list[str] = []

    result = poll_once(
        repository=repository,
        handlers={"whatsapp_webhook": lambda job: handled.append(job.id)},
    )

    assert result is not None and result.status == "done"
    assert result.checkpoint == {"source": "meta", "phase": "executor_started"}
    assert handled == ["job-1"]


def test_poll_once_unknown_kind_is_rejected_and_retried_without_leaking_kind_or_payload():
    job = _job(attempts=1, max_attempts=5)
    job = replace(job, kind="unsupported-secret-kind", payload={"token": "do-not-store"})
    repository = FakeJobs(job)

    result = poll_once(repository=repository, handlers={})

    # Non-fatal rejection: retried, not a terminal "failed" or a crash.
    assert result is not None and result.status == "queued"
    assert result.checkpoint["error"] == {"message": "no handler registered for job kind"}
    assert "unsupported-secret-kind" not in result.checkpoint["error"]["message"]
    assert "do-not-store" not in result.checkpoint["error"]["message"]
    assert repository.calls == [
        ("claim_next", None),
        ("retry_or_dead_letter", "no handler registered for job kind", poller.backoff_seconds(1)),
    ]


def test_poll_once_unknown_kind_dead_letters_once_attempts_are_exhausted():
    job = _job(attempts=5, max_attempts=5)
    repository = FakeJobs(job)

    result = poll_once(repository=repository, handlers={})

    assert result is not None and result.status == "dead_letter"
    assert result.checkpoint["error"] == {"message": "no handler registered for job kind"}


def test_poll_once_unknown_kind_never_raises_so_the_poller_keeps_running():
    repository = FakeJobs(_job())

    # An UnknownJobKindError must never escape poll_once — that would hit the
    # outer try/except in main()'s loop and only survive by accident.
    result = poll_once(repository=repository, handlers={})

    assert result is not None


def test_poll_once_explicit_handler_overrides_registered_kind_handler():
    repository = FakeJobs(_job())
    handled: list[str] = []

    result = poll_once(
        repository=repository,
        handler=lambda job: handled.append(f"override:{job.id}"),
        handlers={"whatsapp_webhook": lambda job: handled.append(f"registered:{job.id}")},
    )

    assert result is not None and result.status == "done"
    assert handled == ["override:job-1"]


def test_poll_once_returns_idle_without_any_mutation():
    repository = FakeJobs(None)

    assert poll_once(repository=repository) is None
    assert repository.calls == [("claim_next", None)]


def test_poll_once_retries_a_failed_handler_without_persisting_exception_text():
    repository = FakeJobs(_job(attempts=1, max_attempts=5))

    def broken_handler(job: Job) -> None:
        raise RuntimeError("credential-like text must not persist")

    result = poll_once(repository=repository, handler=broken_handler)

    assert result is not None and result.status == "queued"
    assert result.checkpoint["phase"] == "executor_started"
    assert result.checkpoint["error"] == {"message": "executor handler failed (RuntimeError)"}
    assert "credential-like" not in result.checkpoint["error"]["message"]
    assert repository.calls[-1] == (
        "retry_or_dead_letter",
        "executor handler failed (RuntimeError)",
        poller.backoff_seconds(1),
    )


def test_poll_once_dead_letters_a_failed_handler_once_max_attempts_is_exhausted():
    repository = FakeJobs(_job(attempts=5, max_attempts=5))

    def broken_handler(job: Job) -> None:
        raise RuntimeError("boom")

    result = poll_once(repository=repository, handler=broken_handler)

    assert result is not None and result.status == "dead_letter"
    assert result.checkpoint["error"] == {"message": "executor handler failed (RuntimeError)"}


def test_poll_once_backoff_spacing_doubles_with_a_cap():
    # base=5s, cap=300s (5 min): 5, 10, 20, 40, ... capped at 300.
    assert poller.backoff_seconds(1) == 5.0
    assert poller.backoff_seconds(2) == 10.0
    assert poller.backoff_seconds(3) == 20.0
    assert poller.backoff_seconds(4) == 40.0
    assert poller.backoff_seconds(10) == 300.0
    assert poller.backoff_seconds(100) == 300.0


def test_poll_once_handler_exceeding_its_timeout_is_retried_not_lost():
    repository = FakeJobs(_job(attempts=1, max_attempts=5))
    never_finishes = threading.Event()

    def hanging_handler(job: Job) -> None:
        never_finishes.wait()  # simulates a handler that never returns

    registration = HandlerRegistration(hanging_handler, timeout_seconds=0.05)

    result = poll_once(repository=repository, handlers={"whatsapp_webhook": registration})

    assert result is not None and result.status == "queued"
    assert result.checkpoint["error"]["message"].startswith("executor handler timed out")
    assert repository.calls[-1][0] == "retry_or_dead_letter"
    # The abandoned handler thread is a daemon and never observed again by
    # the poller; it is not joined, which is what lets poll_once return
    # promptly instead of blocking for the handler's full (hung) lifetime.


def test_poll_once_handler_exceeding_its_timeout_dead_letters_once_exhausted():
    repository = FakeJobs(_job(attempts=5, max_attempts=5))
    never_finishes = threading.Event()
    registration = HandlerRegistration(lambda job: never_finishes.wait(), timeout_seconds=0.05)

    result = poll_once(repository=repository, handlers={"whatsapp_webhook": registration})

    assert result is not None and result.status == "dead_letter"


def test_poll_once_sets_job_timeout_from_the_registered_kind():
    repository = FakeJobs(_job())
    registration = HandlerRegistration(lambda job: None, timeout_seconds=45.0)

    result = poll_once(repository=repository, handlers={"whatsapp_webhook": registration})

    assert result is not None and result.status == "done"
    assert ("set_timeout", 45) in repository.calls


def test_cli_loads_dotenv_before_creating_the_default_repository(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(poller, "load_dotenv", lambda: calls.append("dotenv"))
    monkeypatch.setattr(poller, "poll_once", lambda **kwargs: calls.append("poll"))

    assert poller.main(["--once"]) == 0
    assert calls == ["dotenv", "poll"]


def test_cli_consults_the_startup_handler_registry_by_kind():
    calls: list[object] = []

    def fake_poll_once(**kwargs):
        calls.append(kwargs.get("handlers"))
        raise KeyboardInterrupt

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(poller, "load_dotenv", lambda: None)
        mp.setattr(poller, "poll_once", fake_poll_once)
        # A long-running start seeds the distill chain, which would otherwise
        # reach the live queue from a unit test.
        mp.setattr(poller, "seed_distill_chain", lambda: False)
        assert poller.main([]) == 0

    assert calls == [poller.DEFAULT_HANDLERS]


def test_cli_logs_transient_errors_by_type_then_keeps_polling(monkeypatch, caplog):
    attempts = 0
    sleeps: list[float] = []

    def transient_then_interrupt(**kwargs) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("sensitive job payload must not appear in logs")
        raise KeyboardInterrupt

    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(poller, "poll_once", transient_then_interrupt)
    monkeypatch.setattr(poller, "seed_distill_chain", lambda: False)
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
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("test-only failure")),
    )

    with pytest.raises(RuntimeError, match="test-only failure"):
        poller.main(["--once"])


def test_cli_seeds_the_distill_chain_on_a_long_running_start(monkeypatch):
    seeded: list[bool] = []
    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(poller, "seed_distill_chain", lambda: seeded.append(True) or True)
    monkeypatch.setattr(
        poller, "poll_once", lambda **kwargs: (_ for _ in ()).throw(KeyboardInterrupt)
    )

    assert poller.main([]) == 0
    assert seeded == [True]


def test_cli_once_does_not_touch_the_queue_by_seeding(monkeypatch):
    """``--once`` is a diagnostic. It must not enqueue anything."""
    seeded: list[bool] = []
    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(poller, "seed_distill_chain", lambda: seeded.append(True) or True)
    monkeypatch.setattr(poller, "poll_once", lambda **kwargs: None)

    assert poller.main(["--once"]) == 0
    assert seeded == []


def test_a_failed_seed_is_logged_by_type_and_never_stops_the_executor(monkeypatch, caplog):
    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        poller,
        "seed_distill_chain",
        lambda: (_ for _ in ()).throw(RuntimeError("supabase is flaky here")),
    )
    monkeypatch.setattr(
        poller, "poll_once", lambda **kwargs: (_ for _ in ()).throw(KeyboardInterrupt)
    )

    assert poller.main([]) == 0
    assert "could not seed the distill_memory chain (RuntimeError)" in caplog.text
    assert "supabase is flaky" not in caplog.text


def test_the_distill_kind_is_registered_with_a_timeout_above_the_extraction_timeout():
    from executor.handlers.distill import (
        DISTILL_JOB_KIND,
        extraction_timeout_seconds,
    )

    registration = poller.DEFAULT_HANDLERS[DISTILL_JOB_KIND]
    assert registration.timeout_seconds > extraction_timeout_seconds({})


# --- fix 4: ReorderNotSupported / FileNotFoundError dead-letter on first occurrence ---


def test_poll_once_fails_a_reorder_not_supported_error_without_retrying():
    repository = FakeJobs(_job(attempts=1, max_attempts=5))

    def broken_handler(job: Job) -> None:
        raise ReorderNotSupported("rule wants a position PyFLP can't move to")

    result = poll_once(repository=repository, handler=broken_handler)

    # Attempts (1) are nowhere near max_attempts (5) -- a generic exception
    # here would come back "queued" (see the RuntimeError test above). This
    # must be terminal on the very first occurrence instead.
    assert result is not None and result.status == "failed"
    assert result.checkpoint["phase"] == "executor_started"
    assert result.checkpoint["error"] == {
        "message": "executor handler failed permanently (ReorderNotSupported)"
    }
    assert repository.calls[-1] == (
        "fail",
        "executor handler failed permanently (ReorderNotSupported)",
    )
    assert all(call[0] != "retry_or_dead_letter" for call in repository.calls)


def test_poll_once_fails_a_missing_file_error_without_retrying():
    repository = FakeJobs(_job(attempts=1, max_attempts=5))

    def broken_handler(job: Job) -> None:
        raise FileNotFoundError("song.flp no longer exists")

    result = poll_once(repository=repository, handler=broken_handler)

    assert result is not None and result.status == "failed"
    assert result.checkpoint["error"] == {
        "message": "executor handler failed permanently (FileNotFoundError)"
    }
    assert all(call[0] != "retry_or_dead_letter" for call in repository.calls)


def test_poll_once_still_retries_a_generic_exception_and_not_the_permanent_path():
    # Guards against the new except clause swallowing everything: a plain
    # RuntimeError must still take the existing retry/backoff path, not the
    # new permanent-failure one.
    repository = FakeJobs(_job(attempts=1, max_attempts=5))

    result = poll_once(
        repository=repository,
        handler=lambda job: (_ for _ in ()).throw(RuntimeError("transient")),
    )

    assert result is not None and result.status == "queued"
    assert repository.calls[-1][0] == "retry_or_dead_letter"


# --- fix 2: drain a backlog back-to-back instead of one job per --interval ---


def test_cli_drains_a_backlog_without_sleeping_between_jobs(monkeypatch):
    sleeps: list[float] = []
    polls = 0

    def fake_poll_once(**kwargs):
        nonlocal polls
        polls += 1
        if polls >= 3:
            raise KeyboardInterrupt
        return _job()  # non-None: a real job was just completed

    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(poller, "poll_once", fake_poll_once)
    monkeypatch.setattr(poller, "seed_distill_chain", lambda: False)
    monkeypatch.setattr(poller.time, "sleep", sleeps.append)

    assert poller.main(["--interval", "9"]) == 0
    assert polls == 3
    assert sleeps == []


def test_cli_still_sleeps_the_full_interval_once_the_queue_goes_idle(monkeypatch):
    sleeps: list[float] = []
    polls = 0

    def fake_poll_once(**kwargs):
        nonlocal polls
        polls += 1
        if polls >= 2:
            raise KeyboardInterrupt
        return None  # idle

    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(poller, "poll_once", fake_poll_once)
    monkeypatch.setattr(poller, "seed_distill_chain", lambda: False)
    monkeypatch.setattr(poller.time, "sleep", sleeps.append)

    assert poller.main(["--interval", "9"]) == 0
    assert sleeps == [9]


# --- fix 1: reseed the distill chain again once the queue goes idle ---


def test_cli_reseeds_the_distill_chain_after_an_idle_poll(monkeypatch):
    seeded: list[bool] = []
    polls = 0

    def fake_poll_once(**kwargs):
        nonlocal polls
        polls += 1
        if polls >= 2:
            raise KeyboardInterrupt
        return None  # idle

    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(poller, "poll_once", fake_poll_once)
    monkeypatch.setattr(poller, "seed_distill_chain", lambda: seeded.append(True) or True)
    monkeypatch.setattr(poller.time, "sleep", lambda _: None)

    assert poller.main([]) == 0
    # Once unconditionally before the loop starts, then once more after the
    # queue was observed idle -- a chain that failed to seed at startup gets
    # another chance without waiting for a restart.
    assert seeded == [True, True]


def test_cli_does_not_reseed_the_distill_chain_while_a_backlog_is_draining(monkeypatch):
    seeded: list[bool] = []
    polls = 0

    def fake_poll_once(**kwargs):
        nonlocal polls
        polls += 1
        if polls >= 3:
            raise KeyboardInterrupt
        return _job()  # backlog: never idle

    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(poller, "poll_once", fake_poll_once)
    monkeypatch.setattr(poller, "seed_distill_chain", lambda: seeded.append(True) or True)
    monkeypatch.setattr(poller.time, "sleep", lambda _: None)

    assert poller.main([]) == 0
    # Only the one unconditional call before the loop -- the loop itself
    # never observed an idle poll, so it must not hit Supabase again.
    assert seeded == [True]


# --- fix 3: clear the heartbeat marker on a clean, deliberate stop ---


def test_cli_clears_the_heartbeat_on_a_clean_keyboard_interrupt(monkeypatch):
    cleared: list[bool] = []
    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(poller, "seed_distill_chain", lambda: False)
    monkeypatch.setattr(
        poller, "poll_once", lambda **kwargs: (_ for _ in ()).throw(KeyboardInterrupt)
    )
    monkeypatch.setattr(poller, "clear_heartbeat", lambda: cleared.append(True))

    assert poller.main([]) == 0
    assert cleared == [True]


def test_cli_does_not_clear_the_heartbeat_on_a_crash(monkeypatch):
    # Fail-open by design (see executor/heartbeat.py): a crash must leave the
    # marker in place to go stale on its own, never be cleared, so a genuine
    # crash never masquerades as "cleanly stopped".
    cleared: list[bool] = []
    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(poller, "clear_heartbeat", lambda: cleared.append(True))
    monkeypatch.setattr(
        poller,
        "poll_once",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("test-only crash")),
    )

    with pytest.raises(RuntimeError, match="test-only crash"):
        poller.main(["--once"])

    assert cleared == []


# --- invariant tests: the loop still touches the heartbeat and flp_sort stays registered ---


def test_cli_touches_the_heartbeat_every_loop_iteration(monkeypatch):
    touches: list[bool] = []
    polls = 0

    def fake_poll_once(**kwargs):
        nonlocal polls
        polls += 1
        if polls >= 3:
            raise KeyboardInterrupt
        return None

    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(poller, "touch_heartbeat", lambda: touches.append(True))
    monkeypatch.setattr(poller, "poll_once", fake_poll_once)
    monkeypatch.setattr(poller, "seed_distill_chain", lambda: False)
    monkeypatch.setattr(poller.time, "sleep", lambda _: None)

    assert poller.main([]) == 0
    assert len(touches) == polls == 3


def test_flp_sort_is_registered_in_the_default_handlers():
    assert "flp_sort" in poller.DEFAULT_HANDLERS
    assert isinstance(poller.DEFAULT_HANDLERS["flp_sort"], HandlerRegistration)
    assert callable(poller.DEFAULT_HANDLERS["flp_sort"].handler)
