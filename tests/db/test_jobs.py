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
    # from_env() now also passes ClientOptions(postgrest_client_timeout=...),
    # so the double has to accept `options` and expose the submodule the
    # import comes from. supabase-py's own default is 120s, which stalled the
    # executor's serial poll loop; see TestQueueClientTimeout below.
    monkeypatch.setitem(
        sys.modules,
        "supabase",
        SimpleNamespace(
            create_client=lambda url, key, options=None: created.append((url, key)) or object()
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "supabase.lib.client_options",
        SimpleNamespace(ClientOptions=lambda **kwargs: SimpleNamespace(**kwargs)),
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


class TestQueueClientTimeout:
    """supabase-py defaults PostgREST to 120s. The executor polls in one serial
    loop, so a hung connection stalled every queued message behind it for two
    minutes — measured live as a 95s delay on a reply whose own work took 5s."""

    def test_default_is_short_enough_to_fail_fast(self):
        from db.jobs import DEFAULT_QUEUE_TIMEOUT_SECONDS

        assert 0 < DEFAULT_QUEUE_TIMEOUT_SECONDS <= 30

    def test_environment_can_override_the_timeout(self, monkeypatch):
        from db.jobs import _client_timeout

        monkeypatch.setenv("SUPABASE_QUEUE_TIMEOUT_SECONDS", "5")
        assert _client_timeout() == 5

    def test_unset_or_unusable_values_fall_back_to_the_default(self, monkeypatch):
        from db.jobs import DEFAULT_QUEUE_TIMEOUT_SECONDS, _client_timeout

        monkeypatch.delenv("SUPABASE_QUEUE_TIMEOUT_SECONDS", raising=False)
        assert _client_timeout() == DEFAULT_QUEUE_TIMEOUT_SECONDS

        for bad in ("", "   ", "not-a-number", "0", "-5"):
            monkeypatch.setenv("SUPABASE_QUEUE_TIMEOUT_SECONDS", bad)
            assert _client_timeout() == DEFAULT_QUEUE_TIMEOUT_SECONDS

    def test_from_env_passes_the_timeout_into_the_client(self, monkeypatch):
        import db.jobs as jobs

        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_testing")
        monkeypatch.setenv("SUPABASE_QUEUE_TIMEOUT_SECONDS", "7")

        seen = {}

        def fake_create_client(url, key, options=None):
            seen["timeout"] = getattr(options, "postgrest_client_timeout", None)
            return object()

        import supabase

        monkeypatch.setattr(supabase, "create_client", fake_create_client)
        jobs.SupabaseJobsRepository.from_env()

        assert seen["timeout"] == 7


class TestDefaultRepositoryIsReused:
    """Every queue call used to build its own Supabase client, and so paid its
    own TLS handshake. Measured 4 Sep 2026: four consecutive ``claim_next``
    calls took 4.34, 2.02, 2.05, 1.77s against ~0.3s for the same RPC over one
    kept-open connection. A single text reply makes about five queue calls."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        """No cached repository leaks into — or out of — a test in this class."""
        import db.jobs as jobs

        jobs.reset_default_repository()
        yield
        jobs.reset_default_repository()

    @staticmethod
    def _fake_supabase(monkeypatch, created):
        monkeypatch.setitem(
            sys.modules,
            "supabase",
            SimpleNamespace(
                create_client=lambda url, key, options=None: created.append(url) or object()
            ),
        )
        monkeypatch.setitem(
            sys.modules,
            "supabase.lib.client_options",
            SimpleNamespace(ClientOptions=lambda **kwargs: SimpleNamespace(**kwargs)),
        )

    def test_the_default_repository_is_built_once_and_then_reused(self, monkeypatch):
        import db.jobs as jobs

        created: list[str] = []
        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test_only")
        self._fake_supabase(monkeypatch, created)

        first = jobs._repository_or_default(None)
        second = jobs._repository_or_default(None)

        assert first is second
        assert len(created) == 1

    def test_a_changed_environment_yields_a_fresh_repository(self, monkeypatch):
        """A cached client still points at the project it was built for, so the
        cache is keyed on the credentials rather than on 'has one been built'."""
        import db.jobs as jobs

        created: list[str] = []
        monkeypatch.setenv("SUPABASE_URL", "https://first.supabase.co")
        monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test_only")
        self._fake_supabase(monkeypatch, created)

        first = jobs._repository_or_default(None)
        monkeypatch.setenv("SUPABASE_URL", "https://second.supabase.co")
        second = jobs._repository_or_default(None)

        assert first is not second
        assert created == ["https://first.supabase.co", "https://second.supabase.co"]

        monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_rotated")
        third = jobs._repository_or_default(None)
        assert third is not second
        assert len(created) == 3

    def test_reset_clears_the_cache_and_can_seed_one(self, monkeypatch):
        import db.jobs as jobs

        created: list[str] = []
        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test_only")
        self._fake_supabase(monkeypatch, created)

        first = jobs._repository_or_default(None)
        assert jobs.current_default_repository() is first

        jobs.reset_default_repository()
        assert jobs.current_default_repository() is None
        assert jobs._repository_or_default(None) is not first
        assert len(created) == 2

        seeded = InMemoryJobsRepository()
        assert jobs.reset_default_repository(seeded) is seeded
        # A seeded repository answers regardless of the environment: a test put
        # it there on purpose.
        monkeypatch.setenv("SUPABASE_URL", "https://somewhere-else.supabase.co")
        assert jobs._repository_or_default(None) is seeded
        assert len(created) == 2

    def test_module_level_helpers_go_through_the_cached_repository(self, monkeypatch):
        import db.jobs as jobs

        seeded = InMemoryJobsRepository()
        jobs.reset_default_repository(seeded)

        queued = enqueue("cached", {"via": "default"})
        claimed = claim_next("cached")

        assert claimed is not None and claimed.id == queued.id
        assert seeded.jobs[queued.id].status == "running"

    def test_an_explicit_repository_bypasses_the_cache_entirely(self, monkeypatch):
        import db.jobs as jobs

        created: list[str] = []
        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test_only")
        self._fake_supabase(monkeypatch, created)

        explicit = InMemoryJobsRepository()
        enqueue("explicit", {}, repository=explicit)
        claim_next("explicit", repository=explicit)

        assert created == []
        assert jobs.current_default_repository() is None

    def test_missing_credentials_still_raise_every_call_and_cache_nothing(self, monkeypatch):
        """The bus's ``jobs=None`` fallback depends on this: a webhook must fail
        loudly rather than be answered by a repository cached earlier."""
        import db.jobs as jobs

        created: list[str] = []
        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test_only")
        self._fake_supabase(monkeypatch, created)
        jobs._repository_or_default(None)

        monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        for _ in range(2):
            with pytest.raises(RuntimeError, match="server-only"):
                jobs._repository_or_default(None)
