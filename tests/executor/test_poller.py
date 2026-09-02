from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from db.jobs import Job
from executor import poller
from executor.flp.sort import ReorderNotSupported
from executor.poller import HandlerRegistration, poll_once
from router import RoutedResult


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

    def enqueue(self, kind, payload, run_after=None, max_attempts=None):
        # Only the outcome-notification path enqueues from inside poll_once.
        self.calls.append(("enqueue", kind, dict(payload)))
        now = datetime.now(UTC)
        return Job(
            id=f"enqueued-{len(self.calls)}",
            kind=kind,
            payload=dict(payload),
            status="queued",
            checkpoint={},
            run_after=run_after or now,
            created_at=now,
            updated_at=now,
            attempts=0,
            max_attempts=max_attempts or 3,
        )

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


def test_poll_once_claims_only_the_requested_job_kind():
    repository = FakeJobs(_job())

    result = poll_once(
        repository=repository,
        handlers={"whatsapp_webhook": lambda job: None},
        kind_filter="whatsapp_webhook",
    )

    assert result is not None and result.status == "done"
    assert repository.calls[0] == ("claim_next", "whatsapp_webhook")


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


def test_cli_limits_a_kind_filtered_worker_to_its_own_handler(monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_poll_once(**kwargs):
        calls.append(kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(poller, "poll_once", fake_poll_once)
    monkeypatch.setattr(poller, "seed_distill_chain", lambda: pytest.fail("should not seed"))

    assert poller.main(["--kind", "whatsapp_webhook", "--no-heartbeat"]) == 0
    assert calls == [
        {
            "handlers": {"whatsapp_webhook": poller.DEFAULT_HANDLERS["whatsapp_webhook"]},
            "kind_filter": ("whatsapp_webhook",),
        }
    ]


# --- a worker that owns several kinds -------------------------------------
# ``claim_next_job`` filters on one kind, so a worker owning a set asks for
# them one at a time. What must hold is that it never asks for a kind outside
# its set, and that a busy kind cannot hold the others behind it forever.


def test_cli_restricts_a_multi_kind_worker_to_exactly_its_own_handlers(monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_poll_once(**kwargs):
        calls.append(kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(poller, "poll_once", fake_poll_once)
    monkeypatch.setattr(poller, "seed_distill_chain", lambda: pytest.fail("should not seed"))

    assert poller.main(["--kind", "system_control", "zoom_join_meeting", "--no-heartbeat"]) == 0
    assert calls == [
        {
            "handlers": {
                "system_control": poller.DEFAULT_HANDLERS["system_control"],
                "zoom_join_meeting": poller.DEFAULT_HANDLERS["zoom_join_meeting"],
            },
            "kind_filter": ("system_control", "zoom_join_meeting"),
        }
    ]


def test_cli_rejects_a_kind_that_is_not_registered(capsys):
    with pytest.raises(SystemExit):
        poller.main(["--kind", "system_control", "not_a_registered_kind"])
    assert "not_a_registered_kind" in capsys.readouterr().err


def test_cli_rotates_the_kind_order_so_one_busy_kind_cannot_starve_the_rest(monkeypatch):
    seen: list[tuple[str, ...]] = []

    def fake_poll_once(**kwargs):
        seen.append(kwargs["kind_filter"])
        if len(seen) == 3:
            raise KeyboardInterrupt
        return None

    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(poller, "poll_once", fake_poll_once)
    monkeypatch.setattr(poller.time, "sleep", lambda _seconds: None)

    assert poller.main(["--kind", "system_control", "zoom_join_meeting", "--no-heartbeat"]) == 0
    assert seen == [
        ("system_control", "zoom_join_meeting"),
        ("zoom_join_meeting", "system_control"),
        ("system_control", "zoom_join_meeting"),
    ]


def test_a_multi_kind_worker_only_seeds_the_distill_chain_when_it_owns_that_kind(monkeypatch):
    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(poller, "seed_distill_chain", lambda: pytest.fail("should not seed"))
    monkeypatch.setattr(
        poller, "poll_once", lambda **kwargs: (_ for _ in ()).throw(KeyboardInterrupt)
    )

    assert poller.main(["--kind", "system_control", "flp_sort", "--no-heartbeat"]) == 0


def test_poll_once_asks_every_owned_kind_before_reporting_an_idle_queue():
    jobs = FakeJobs(None)

    assert poll_once(repository=jobs, kind_filter=("system_control", "flp_sort")) is None
    assert jobs.calls == [
        ("claim_next", "system_control"),
        ("claim_next", "flp_sort"),
    ]


def test_poll_once_never_asks_for_a_kind_outside_the_owned_set():
    jobs = FakeJobs(None)

    poll_once(repository=jobs, kind_filter=("system_control",))

    assert jobs.calls == [("claim_next", "system_control")]


def test_poll_once_stops_asking_once_a_job_is_claimed():
    jobs = FakeJobs(replace(_job(), kind="system_control"))

    poll_once(
        repository=jobs,
        handler=lambda job: None,
        kind_filter=("system_control", "zoom_join_meeting"),
    )

    assert [call for call in jobs.calls if call[0] == "claim_next"] == [
        ("claim_next", "system_control")
    ]


def test_an_empty_kind_filter_is_rejected_rather_than_claiming_every_kind():
    jobs = FakeJobs(_job())

    with pytest.raises(ValueError):
        poll_once(repository=jobs, kind_filter=())
    assert jobs.calls == []


def test_kinds_to_claim_normalises_none_and_a_single_kind():
    assert poller.kinds_to_claim(None) == (None,)
    assert poller.kinds_to_claim("system_control") == ("system_control",)
    assert poller.kinds_to_claim(["a", "b"]) == ("a", "b")


def test_rotate_kinds_walks_the_set_and_wraps():
    kinds = ("a", "b", "c")
    assert poller.rotate_kinds(kinds, 0) == ("a", "b", "c")
    assert poller.rotate_kinds(kinds, 1) == ("b", "c", "a")
    assert poller.rotate_kinds(kinds, 3) == ("a", "b", "c")
    assert poller.rotate_kinds(("solo",), 7) == ("solo",)


def test_cli_only_the_background_worker_seeds_the_distill_chain(monkeypatch):
    seeded: list[bool] = []
    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(poller, "seed_distill_chain", lambda: seeded.append(True) or True)
    monkeypatch.setattr(
        poller,
        "poll_once",
        lambda **kwargs: (_ for _ in ()).throw(KeyboardInterrupt),
    )

    assert poller.main(["--kind", poller.DISTILL_JOB_KIND]) == 0
    assert seeded == [True]


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


# --- request_completion: executor jobs' single async entry point into the router ---


def test_request_completion_delegates_to_router_route_with_matching_arguments(monkeypatch):
    calls: list[dict[str, object]] = []
    sentinel = RoutedResult(provider="deepseek", model="deepseek-v4-flash", response={"ok": True})

    async def fake_route(task_profile, messages, *, urgent=False):
        calls.append({"task_profile": task_profile, "messages": messages, "urgent": urgent})
        return sentinel

    monkeypatch.setattr(poller, "route", fake_route)

    messages = [{"role": "user", "content": "sort this flp"}]
    result = asyncio.run(poller.request_completion("batch", messages))

    assert result is sentinel
    assert calls == [{"task_profile": "batch", "messages": messages, "urgent": False}]


def test_request_completion_passes_urgent_through(monkeypatch):
    calls: list[bool] = []

    async def fake_route(task_profile, messages, *, urgent=False):
        calls.append(urgent)
        return RoutedResult(provider="groq", model="openai/gpt-oss-20b", response={})

    monkeypatch.setattr(poller, "route", fake_route)

    asyncio.run(poller.request_completion("latency", [], urgent=True))

    assert calls == [True]


# --- publishing provider health ----------------------------------------------
#
# Q10c: the process that routes reports provider health. That is the executor,
# not the bus -- the bus builds a router but is enqueue-only and never calls
# route(), so reading its in-memory health map told /status only that nothing
# had been tried, in a shape that looked like nothing was wrong.


class _FakeRouter:
    def __init__(self, snapshot) -> None:
        self._snapshot = snapshot
        self.snapshot_calls = 0

    def health_snapshot(self):
        self.snapshot_calls += 1
        return self._snapshot


def _health(status=429, remaining=60.0, headers=None):
    return {
        "groq": {
            "last_status": status,
            "cooldown_seconds_remaining": remaining,
            "rate_limit_headers": headers if headers is not None else {"retry-after": "60"},
        }
    }


def test_a_worker_that_never_routed_publishes_nothing(monkeypatch):
    """action-worker and background-worker must not stamp their defaults over
    the snapshot belonging to the one worker that actually routes."""
    monkeypatch.setattr(poller, "current_shared_router", lambda: None)
    monkeypatch.setattr(
        poller, "write_provider_health", lambda *_: pytest.fail("nothing routed here")
    )

    assert poller._publish_provider_health(None) is None


def test_the_first_snapshot_is_published(monkeypatch):
    written: list[dict] = []
    monkeypatch.setattr(poller, "current_shared_router", lambda: _FakeRouter(_health()))
    monkeypatch.setattr(poller, "write_provider_health", written.append)

    state = poller._publish_provider_health(None)

    assert written == [_health()]
    assert state is not None


def test_a_ticking_countdown_alone_does_not_rewrite_the_file(monkeypatch):
    """Otherwise this writes several times a second, forever, for no new fact."""
    written: list[dict] = []
    router = _FakeRouter(_health(remaining=60.0))
    monkeypatch.setattr(poller, "current_shared_router", lambda: router)
    monkeypatch.setattr(poller, "write_provider_health", written.append)

    state = poller._publish_provider_health(None)
    router._snapshot = _health(remaining=41.0)
    state = poller._publish_provider_health(state)

    assert len(written) == 1


def test_a_changed_status_is_published(monkeypatch):
    written: list[dict] = []
    router = _FakeRouter(_health(status=429))
    monkeypatch.setattr(poller, "current_shared_router", lambda: router)
    monkeypatch.setattr(poller, "write_provider_health", written.append)

    state = poller._publish_provider_health(None)
    router._snapshot = _health(status=503)
    poller._publish_provider_health(state)

    assert [entry["groq"]["last_status"] for entry in written] == [429, 503]


def test_recovery_is_published(monkeypatch):
    written: list[dict] = []
    router = _FakeRouter(_health(remaining=60.0))
    monkeypatch.setattr(poller, "current_shared_router", lambda: router)
    monkeypatch.setattr(poller, "write_provider_health", written.append)

    state = poller._publish_provider_health(None)
    router._snapshot = _health(status=200, remaining=0.0, headers={})
    poller._publish_provider_health(state)

    assert len(written) == 2
    assert written[1]["groq"]["cooldown_seconds_remaining"] == 0.0


def test_the_poll_loop_publishes_each_cycle(monkeypatch):
    published: list[object] = []
    calls = 0

    def fake_poll_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise KeyboardInterrupt
        return None

    monkeypatch.setattr(poller, "load_dotenv", lambda: None)
    monkeypatch.setattr(poller, "poll_once", fake_poll_once)
    monkeypatch.setattr(poller, "seed_distill_chain", lambda: False)
    monkeypatch.setattr(poller.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        poller, "_publish_provider_health", lambda state: published.append(state) or "state"
    )

    assert poller.main(["--no-heartbeat"]) == 0
    assert published == [None, "state"]


def test_poll_once_records_a_safe_cause_slug_alongside_the_exception_type():
    """``EmbeddingError`` alone was not a diagnosis; the slug is what tells them apart.

    84 dead-lettered ``distill_memory`` rows on 29-30 August 2026 stored one
    string for three different failures. See ``memory.embeddings``.
    """
    repository = FakeJobs(_job(attempts=1, max_attempts=5))

    class Unreachable(RuntimeError):
        cause = "unavailable"

    def broken_handler(job: Job) -> None:
        raise Unreachable("http://127.0.0.1:11434 refused the connection")

    result = poll_once(repository=repository, handler=broken_handler)

    assert result is not None
    assert result.checkpoint["error"] == {
        "message": "executor handler failed (Unreachable: unavailable)"
    }
    assert "11434" not in result.checkpoint["error"]["message"]


def test_poll_once_refuses_a_cause_that_is_not_a_fixed_vocabulary_slug():
    """The slug shape is a privacy boundary: the checkpoint is hosted.

    Anything that could be free text — a prompt, a turn, a URL, a key — fails
    the shape test and is dropped back to the bare exception type.
    """
    unsafe = [
        "Ali said he lives in Lahore",  # spaces and capitals
        "sk-abc123DEF",  # a key shape
        "http://127.0.0.1:11434/api/embed",  # a URL
        "x" * 41,  # over the length cap
        "",
        None,
        b"unavailable",
        17,
    ]

    for cause in unsafe:
        repository = FakeJobs(_job(attempts=1, max_attempts=5))

        class Leaky(RuntimeError):
            pass

        Leaky.cause = cause

        def broken_handler(job: Job) -> None:
            raise Leaky("boom")

        result = poll_once(repository=repository, handler=broken_handler)

        assert result is not None
        assert result.checkpoint["error"] == {"message": "executor handler failed (Leaky)"}, cause


def test_poll_once_records_a_cause_on_the_permanent_failure_path_too():
    repository = FakeJobs(_job(attempts=1, max_attempts=5))

    class GoneForGood(FileNotFoundError):
        cause = "missing_target"

    def broken_handler(job: Job) -> None:
        raise GoneForGood("C:/private/path/to/a/project.flp")

    result = poll_once(repository=repository, handler=broken_handler)

    assert result is not None and result.status == "failed"
    assert result.checkpoint["error"] == {
        "message": "executor handler failed permanently (GoneForGood: missing_target)"
    }


def test_poll_once_tells_the_waiting_user_when_a_job_dead_letters():
    """Silence is worst here: the user was told "on it" and heard nothing since.

    The poller reads a generic ``notify`` payload field. It never learns that
    WhatsApp exists — that is entirely in the descriptor's ``kind``.
    """
    job = replace(
        _job(attempts=5, max_attempts=5),
        kind="system_control",
        payload={
            "action": "wifi.set_enabled",
            "notify": {"kind": "whatsapp_outcome", "payload": {"reply_to": "9230012", "summary": "turn wifi off"}},
        },
    )
    repository = FakeJobs(job)

    def broken_handler(job: Job) -> None:
        raise RuntimeError("boom")

    result = poll_once(repository=repository, handler=broken_handler)

    assert result is not None and result.status == "dead_letter"
    assert ("enqueue", "whatsapp_outcome") in [(c[0], c[1]) for c in repository.calls if c[0] == "enqueue"]
    kind, payload = next(c[1:3] for c in repository.calls if c[0] == "enqueue")
    assert payload["status"] == "failed"
    assert payload["reply_to"] == "9230012"
    assert payload["detail"] == "RuntimeError"


def test_poll_once_stays_silent_while_a_job_is_still_going_to_be_retried():
    """One message per retry would be three messages for one action."""
    job = replace(
        _job(attempts=1, max_attempts=5),
        kind="system_control",
        payload={
            "action": "wifi.set_enabled",
            "notify": {"kind": "whatsapp_outcome", "payload": {"reply_to": "9230012"}},
        },
    )
    repository = FakeJobs(job)

    def broken_handler(job: Job) -> None:
        raise RuntimeError("boom")

    result = poll_once(repository=repository, handler=broken_handler)

    assert result is not None and result.status == "queued"
    assert [c for c in repository.calls if c[0] == "enqueue"] == []


def test_poll_once_notifies_on_the_permanent_failure_path_too():
    job = replace(
        _job(attempts=1, max_attempts=5),
        kind="flp_sort",
        payload={
            "notify": {"kind": "whatsapp_outcome", "payload": {"reply_to": "9230012", "summary": "sort the mixer"}},
        },
    )
    repository = FakeJobs(job)

    def broken_handler(job: Job) -> None:
        raise ReorderNotSupported("PyFLP cannot move an insert")

    result = poll_once(repository=repository, handler=broken_handler)

    assert result is not None and result.status == "failed"
    kind, payload = next(c[1:3] for c in repository.calls if c[0] == "enqueue")
    assert kind == "whatsapp_outcome"
    assert payload["detail"] == "ReorderNotSupported"
    # The exception's message came from PyFLP and has no business in a hosted
    # table; only the type name travels.
    assert "PyFLP" not in str(payload)


def test_poll_once_notifies_nobody_for_a_job_that_asked_for_nothing():
    repository = FakeJobs(_job(attempts=5, max_attempts=5))

    def broken_handler(job: Job) -> None:
        raise RuntimeError("boom")

    assert poll_once(repository=repository, handler=broken_handler) is not None
    assert [c for c in repository.calls if c[0] == "enqueue"] == []
