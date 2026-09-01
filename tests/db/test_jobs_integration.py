"""Live Supabase job-queue integration tests, plus offline guards for them.

Two tests here talk to the real project. They are marked ``live``, so
``pytest.ini``'s ``addopts = -m "not live ..."`` deselects them from any
ordinary run; ``pytest -m live tests/db`` opts back in.

Everything else in this file is offline. Those tests drive the live-schema
probe with fake repositories so the probe's own decision — skip on a network
failure, *fail* on schema drift — is itself covered without a database.

Why the probe was rewritten: it previously wrapped its check in a bare
``except Exception`` and called ``pytest.skip("0002 migration ... is not
applied")`` on *any* exception. Migrations 0001 and 0002 are applied live, so
the one condition this file exists to detect — the live schema drifting from
what ``db/jobs.py`` expects — was converted into a green skip. The same bare
except also reported this machine's documented transient TLS failures
(``WinError 10054``) as a missing migration, which is a different and much
more alarming claim.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from postgrest import APIError

from db.jobs import (
    Job,
    JobRepository,
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


@pytest.mark.live
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


# Which exceptions mean "the probe never got an answer out of the database".
#
# This is a type split, not a message match, and it comes from the installed
# source rather than from a guess:
#
#   .venv/Lib/site-packages/postgrest/_sync/request_builder.py
#       ``execute()`` calls ``self.session.request(...)`` *outside* its
#       try/except, then turns any non-2xx **response** into
#       ``postgrest.APIError``.
#   .venv/Lib/site-packages/postgrest/_sync/client.py
#       that session is a plain ``httpx.Client`` — postgrest wraps no transport
#       exception of its own.
#
# So the two outcomes separate cleanly at the source:
#
#   * the request never completed  -> ``httpx.TransportError`` (ConnectError,
#     ConnectTimeout, ReadTimeout, ReadError, RemoteProtocolError, ...), or a
#     bare ``OSError`` leaking from the socket/TLS layer. ``WinError 10054`` is
#     ``ConnectionResetError``, DNS failure is ``socket.gaierror``, TLS failure
#     is ``ssl.SSLError`` — all ``OSError`` subclasses, and none of them
#     ``httpx`` types.
#   * PostgREST answered -> ``postgrest.APIError``, carrying the SQLSTATE or
#     PGRST code. A missing RPC is ``PGRST202``; a missing column is ``42703``.
#     That is a schema answer and must be loud.
_CONNECTION_FAILURES: tuple[type[BaseException], ...] = (httpx.TransportError, OSError)


def _is_connection_failure(exc: BaseException) -> bool:
    """True only when the probe never reached the database.

    Everything else — very much including ``APIError``, which by construction
    means the server answered — counts as schema drift and must fail. The
    asymmetry is deliberate and is the point of this lane: a false red on a
    network blip is re-runnable in a minute, while a permanent green over real
    drift is the bug being fixed here. When in doubt, fail.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, APIError):
            # The server responded. Whatever it said, this was not a transport
            # failure, so it is never allowed to become a skip.
            return False
        if isinstance(current, _CONNECTION_FAILURES):
            return True
        current = current.__cause__
    return False


def _best_effort_terminal(repository: JobRepository, queued: Job | None) -> None:
    """Park a disposable probe row in a terminal state. Never masks the cause."""
    if queued is None:
        return
    try:
        fail(queued.id, "probe cleanup (schema probe failed)", repository=repository)
    except Exception:
        pass  # best-effort only; the original exception is what matters


def _probe_0002_schema(repository: JobRepository) -> None:
    """Exercise the 0002 columns/RPCs against ``repository``.

    Three outcomes, and only the first is tolerated:

    1. connection never established -> ``pytest.skip`` naming the *network* as
       the cause. It says nothing about migrations, because nothing about the
       schema was observed.
    2. connection established, schema behaves -> return.
    3. connection established, schema does not behave -> the original exception
       propagates. That is drift, and it is a red test.

    Takes the repository as an argument so the offline guards below can drive
    every branch with a fake and no database.
    """
    probe_kind = f"queue-durability-probe-{uuid4()}"
    queued: Job | None = None
    try:
        queued = enqueue(probe_kind, {}, repository=repository)
        claimed = claim_next(probe_kind, repository=repository)
        if claimed is None:
            raise AssertionError(
                "claim_next_job returned no row for a job enqueued one call "
                "earlier: the live queue does not behave the way db/jobs.py "
                "expects (schema drift)"
            )
        retry_or_dead_letter(claimed.id, "probe cleanup", 0, repository=repository)
        fail(queued.id, "probe cleanup", repository=repository)
    except Exception as exc:
        _best_effort_terminal(repository, queued)
        if _is_connection_failure(exc):
            pytest.skip(
                "live Supabase connection failed before any schema could be "
                f"observed ({type(exc).__module__}.{type(exc).__name__}). This "
                "is a network/TLS failure on this machine, NOT a missing "
                "migration and NOT schema drift."
            )
        raise


def _live_repository_with_0002_applied(monkeypatch) -> SupabaseJobsRepository:
    """Return a live repository, having proved the 0002 schema is really there."""
    _load_supabase_env(monkeypatch)
    repository = SupabaseJobsRepository.from_env()
    _probe_0002_schema(repository)
    return repository


@pytest.mark.live
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


# ---------------------------------------------------------------------------
# Offline guards. No network, no live project — fakes only.
# ---------------------------------------------------------------------------


def _job(job_id: str = "3f1f0000-0000-4000-8000-000000000001", *, kind: str = "probe", status: str = "queued") -> Job:
    return Job(
        id=job_id,
        kind=kind,
        payload={},
        status=status,
        checkpoint={},
        run_after="2026-01-01T00:00:00+00:00",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


class _ScriptedRepository:
    """A ``JobRepository`` that raises a chosen exception at a chosen step.

    Records every call so a test can assert the probe still parked its
    disposable row before deciding skip-or-fail.
    """

    _KEEP_DEFAULT = object()

    def __init__(
        self,
        *,
        fail_on: str = "",
        error: BaseException | None = None,
        claim_result: Job | None | object = _KEEP_DEFAULT,
        cleanup_error: BaseException | None = None,
    ) -> None:
        self.fail_on = fail_on
        self.error = error
        self.claim_result = (
            _job(status="running") if claim_result is self._KEEP_DEFAULT else claim_result
        )
        self.cleanup_error = cleanup_error
        self.calls: list[str] = []

    def _step(self, name: str) -> None:
        self.calls.append(name)
        if name == self.fail_on and self.error is not None:
            raise self.error

    def enqueue(self, kind, payload, run_after=None, max_attempts=None) -> Job:
        self._step("enqueue")
        return _job(kind=kind)

    def claim_next(self, kind_filter=None) -> Job | None:
        self._step("claim_next")
        return self.claim_result

    def checkpoint(self, job_id, state) -> Job:
        self._step("checkpoint")
        return _job()

    def complete(self, job_id) -> Job:
        self._step("complete")
        return _job(status="done")

    def fail(self, job_id, err) -> Job:
        self._step("fail")
        if self.cleanup_error is not None:
            raise self.cleanup_error
        return _job(status="failed")

    def retry_or_dead_letter(self, job_id, err, delay_seconds=0) -> Job:
        self._step("retry_or_dead_letter")
        return _job()

    def set_timeout(self, job_id, timeout_seconds) -> Job:
        self._step("set_timeout")
        return _job()


def _reset_error(winerror: int = 10054) -> ConnectionResetError:
    return ConnectionResetError(
        winerror, "An existing connection was forcibly closed by the remote host"
    )


def _httpx_read_error_from_winerror_10054() -> httpx.ReadError:
    """The exact shape httpx produces for the documented WinError 10054 blip."""
    error = httpx.ReadError("An existing connection was forcibly closed by the remote host")
    error.__cause__ = _reset_error()
    return error


def _import_ssl_error() -> BaseException:
    import ssl

    return ssl.SSLError(1, "[SSL: DECRYPTION_FAILED_OR_BAD_RECORD_MAC] decryption failed")


def _dns_error() -> BaseException:
    import socket

    return socket.gaierror(11001, "getaddrinfo failed")


@pytest.mark.parametrize(
    ("label", "error"),
    [
        ("connect-refused", httpx.ConnectError("[Errno 111] Connection refused")),
        ("connect-timeout", httpx.ConnectTimeout("timed out")),
        ("read-timeout", httpx.ReadTimeout("timed out")),
        ("pool-timeout", httpx.PoolTimeout("timed out")),
        ("winerror-10054", _httpx_read_error_from_winerror_10054()),
        ("server-hung-up", httpx.RemoteProtocolError("Server disconnected without sending a response.")),
        ("proxy", httpx.ProxyError("proxy refused")),
        ("bare-connection-reset", _reset_error()),
        ("tls", _import_ssl_error()),
        ("dns", _dns_error()),
    ],
)
def test_probe_skips_and_blames_the_network_when_the_connection_fails(label, error):
    """Outcome 2: credentials present, connection failed -> skip, saying so."""
    repository = _ScriptedRepository(fail_on="claim_next", error=error)

    with pytest.raises(pytest.skip.Exception) as caught:
        _probe_0002_schema(repository)

    message = str(caught.value)
    assert "connection failed" in message, (label, message)
    assert "network" in message.lower(), (label, message)
    # The old behaviour blamed the migration for this. It must never do so again.
    assert "not a missing" in message.lower(), (label, message)
    assert type(error).__name__ in message, (label, message)
    # The disposable probe row is still parked before the decision.
    assert repository.calls[-1] == "fail", (label, repository.calls)


def test_probe_skip_survives_a_cleanup_that_also_fails():
    """A network blip breaks cleanup too; that must not turn the skip into an error."""
    repository = _ScriptedRepository(
        fail_on="claim_next",
        error=httpx.ConnectError("no route to host"),
        cleanup_error=httpx.ConnectError("no route to host"),
    )

    with pytest.raises(pytest.skip.Exception) as caught:
        _probe_0002_schema(repository)

    assert "network" in str(caught.value).lower()


def _probe_strictly(repository: JobRepository) -> None:
    """Run the probe, refusing to let a wrongful skip masquerade as a pass.

    ``pytest.skip`` raises ``Skipped``, which derives from ``BaseException``,
    so a guard written as ``with pytest.raises(APIError)`` would report a
    regressed probe as *skipped* rather than failed. Verified by mutation: with
    ``_is_connection_failure`` forced to ``True`` (the old bare-except
    behaviour), the drift guards came back "6 skipped" instead of red. A skip
    is not a red, and hiding drift behind a skip is precisely the defect this
    file was rewritten to remove — so convert it into a failure here.
    """
    try:
        _probe_0002_schema(repository)
    except pytest.skip.Exception as skipped:
        raise AssertionError(
            f"the probe SKIPPED on schema drift instead of failing: {skipped}"
        ) from None


@pytest.mark.parametrize(
    ("label", "step", "error"),
    [
        (
            "missing retry_or_dead_letter_job RPC",
            "retry_or_dead_letter",
            APIError(
                {
                    "message": "Could not find the function public.retry_or_dead_letter_job",
                    "code": "PGRST202",
                    "hint": None,
                    "details": None,
                }
            ),
        ),
        (
            "missing attempts column",
            "enqueue",
            APIError(
                {
                    "message": 'column "attempts" of relation "jobs" does not exist',
                    "code": "42703",
                    "hint": None,
                    "details": None,
                }
            ),
        ),
        (
            "renamed claim RPC",
            "claim_next",
            APIError(
                {
                    "message": "Could not find the function public.claim_next_job",
                    "code": "PGRST202",
                    "hint": None,
                    "details": None,
                }
            ),
        ),
    ],
)
def test_probe_fails_loudly_on_schema_drift(label, step, error):
    """Outcome 3: the server answered and the schema is wrong -> red, never a skip."""
    repository = _ScriptedRepository(fail_on=step, error=error)

    with pytest.raises(APIError) as caught:
        _probe_strictly(repository)

    assert caught.value is error, label


def test_probe_fails_when_the_claim_rpc_returns_no_row():
    """A job enqueued one call earlier must be claimable. Drift if it is not."""
    repository = _ScriptedRepository(claim_result=None)

    # Match text from the probe's own message, not from ``_probe_strictly``'s
    # wrapper, so a regression to skipping cannot satisfy this guard.
    with pytest.raises(AssertionError, match="claim_next_job returned no row"):
        _probe_strictly(repository)


def test_probe_fails_when_an_rpc_returns_an_empty_result():
    """``db.jobs._one_job`` raises ``KeyError`` for a missing row. Still drift."""
    repository = _ScriptedRepository(
        fail_on="retry_or_dead_letter", error=KeyError("job was not found")
    )

    with pytest.raises(KeyError):
        _probe_strictly(repository)


def test_probe_parks_its_row_before_failing_on_drift():
    repository = _ScriptedRepository(
        fail_on="retry_or_dead_letter",
        error=APIError({"message": "boom", "code": "PGRST202", "hint": None, "details": None}),
    )

    with pytest.raises(APIError):
        _probe_strictly(repository)

    assert repository.calls == ["enqueue", "claim_next", "retry_or_dead_letter", "fail"]


def test_probe_returns_quietly_when_the_schema_matches():
    """Outcome: connection fine, schema fine. No skip, no failure."""
    repository = _ScriptedRepository()

    _probe_strictly(repository)

    assert repository.calls == ["enqueue", "claim_next", "retry_or_dead_letter", "fail"]


def test_an_api_error_is_never_a_connection_failure_even_when_nested():
    """The server answering always wins over any transport error beneath it."""
    api_error = APIError({"message": "boom", "code": "PGRST202", "hint": None, "details": None})
    api_error.__cause__ = httpx.ConnectError("connection refused")

    assert _is_connection_failure(api_error) is False


def test_connection_classifier_walks_the_cause_chain():
    wrapper = RuntimeError("supabase call failed")
    wrapper.__cause__ = _httpx_read_error_from_winerror_10054()

    assert _is_connection_failure(wrapper) is True


def test_connection_classifier_does_not_treat_ordinary_bugs_as_network_failures():
    for exc in (
        AssertionError("claim returned nothing"),
        KeyError("job was not found"),
        TypeError("Job.from_row() missing argument"),
        ValueError("bad uuid"),
        RuntimeError("SUPABASE_URL must be configured"),
    ):
        assert _is_connection_failure(exc) is False, type(exc).__name__


def test_connection_classifier_terminates_on_a_self_referential_cause():
    exc = RuntimeError("loop")
    exc.__cause__ = exc

    assert _is_connection_failure(exc) is False


def test_the_two_live_tests_stay_behind_the_live_marker():
    """The offline guards above must never drag the live project into a default run."""
    for function in (
        test_real_supabase_full_job_lifecycle,
        test_real_supabase_concurrent_claims_never_double_claim_or_drop_a_job,
    ):
        markers = {mark.name for mark in getattr(function, "pytestmark", [])}
        assert "live" in markers, function.__name__
