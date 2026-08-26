"""Small, synchronous interface for the durable Supabase job queue.

The only state transition that selects work is the ``claim_next_job`` database
RPC. Its row lock keeps separate executor processes from claiming one job twice.
"""

from __future__ import annotations

from base64 import urlsafe_b64decode
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import json
import os
from typing import Any, Protocol
from uuid import UUID


JsonObject = dict[str, Any]


DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_TIMEOUT_SECONDS = 300

# supabase-py defaults its PostgREST client to a 120s timeout. The executor
# polls this queue in a single serial loop, so one hung connection stalls every
# inbound message behind it for two full minutes — measured live on 27 August
# 2026 as a 95s delay on a reply whose own work took 5s. Queue calls are small
# RPCs against a nearby region (~0.12s observed), so anything past a few
# seconds is a failing connection, not a slow one: fail fast and let the next
# poll retry.
DEFAULT_QUEUE_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class Job:
    """A job as returned by the queue."""

    id: str
    kind: str
    payload: JsonObject
    status: str
    checkpoint: JsonObject
    run_after: datetime | str
    created_at: datetime | str
    updated_at: datetime | str
    attempts: int = 0
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Job":
        return cls(
            id=str(row["id"]),
            kind=str(row["kind"]),
            payload=dict(row.get("payload") or {}),
            status=str(row["status"]),
            checkpoint=dict(row.get("checkpoint") or {}),
            run_after=row["run_after"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            attempts=int(row.get("attempts", 0) or 0),
            max_attempts=int(row.get("max_attempts", DEFAULT_MAX_ATTEMPTS) or DEFAULT_MAX_ATTEMPTS),
            timeout_seconds=int(row.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS) or DEFAULT_TIMEOUT_SECONDS),
        )


class JobRepository(Protocol):
    """Repository contract, kept small so callers can test without Supabase."""

    def enqueue(
        self,
        kind: str,
        payload: JsonObject,
        run_after: datetime | None = None,
        max_attempts: int | None = None,
    ) -> Job: ...

    def claim_next(self, kind_filter: str | None = None) -> Job | None: ...

    def checkpoint(self, job_id: str | UUID, state: JsonObject) -> Job: ...

    def complete(self, job_id: str | UUID) -> Job: ...

    def fail(self, job_id: str | UUID, err: str) -> Job: ...

    def retry_or_dead_letter(self, job_id: str | UUID, err: str, delay_seconds: float = 0) -> Job: ...

    def set_timeout(self, job_id: str | UUID, timeout_seconds: int) -> Job: ...


class SupabaseJobsRepository:
    """Supabase-backed implementation using queue operations defined in SQL."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_env(cls) -> "SupabaseJobsRepository":
        """Create a repository with a server-only Supabase credential."""
        url = os.environ.get("SUPABASE_URL")
        key = _server_key_from_env()
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and a server-only Supabase secret/service-role key must be configured"
            )
        try:
            from supabase import create_client
            from supabase.lib.client_options import ClientOptions
        except ImportError as exc:  # pragma: no cover - dependency integration
            raise RuntimeError("Install the pinned Supabase dependency first") from exc
        return cls(create_client(url, key, options=ClientOptions(postgrest_client_timeout=_client_timeout())))

    def enqueue(
        self,
        kind: str,
        payload: JsonObject,
        run_after: datetime | None = None,
        max_attempts: int | None = None,
    ) -> Job:
        record: JsonObject = {"kind": kind, "payload": payload}
        if run_after is not None:
            record["run_after"] = run_after.isoformat()
        if max_attempts is not None:
            record["max_attempts"] = max_attempts
        response = self._client.table("jobs").insert(record).execute()
        return _one_job(response)

    def claim_next(self, kind_filter: str | None = None) -> Job | None:
        response = self._client.rpc(
            "claim_next_job", {"p_kind_filter": kind_filter}
        ).execute()
        if not response.data:
            return None
        return Job.from_row(response.data[0])

    def checkpoint(self, job_id: str | UUID, state: JsonObject) -> Job:
        response = self._client.rpc(
            "checkpoint_job", {"p_job_id": str(job_id), "p_state": state}
        ).execute()
        return _one_job(response)

    def complete(self, job_id: str | UUID) -> Job:
        response = self._client.rpc("complete_job", {"p_job_id": str(job_id)}).execute()
        return _one_job(response)

    def fail(self, job_id: str | UUID, err: str) -> Job:
        response = self._client.rpc(
            "fail_job", {"p_job_id": str(job_id), "p_error": err}
        ).execute()
        return _one_job(response)

    def retry_or_dead_letter(self, job_id: str | UUID, err: str, delay_seconds: float = 0) -> Job:
        response = self._client.rpc(
            "retry_or_dead_letter_job",
            {
                "p_job_id": str(job_id),
                "p_error": err,
                "p_delay_seconds": int(round(max(0.0, delay_seconds))),
            },
        ).execute()
        return _one_job(response)

    def set_timeout(self, job_id: str | UUID, timeout_seconds: int) -> Job:
        response = self._client.rpc(
            "set_job_timeout",
            {"p_job_id": str(job_id), "p_timeout_seconds": int(timeout_seconds)},
        ).execute()
        return _one_job(response)


def _one_job(response: Any) -> Job:
    """Normalize Supabase's list/object RPC responses and reject missing jobs."""
    data = response.data
    if isinstance(data, list):
        if not data:
            raise KeyError("job was not found")
        data = data[0]
    if not data:
        raise KeyError("job was not found")
    return Job.from_row(data)


def _client_timeout() -> int:
    """Queue-client HTTP timeout, overridable via ``SUPABASE_QUEUE_TIMEOUT_SECONDS``."""
    raw = os.environ.get("SUPABASE_QUEUE_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_QUEUE_TIMEOUT_SECONDS
    try:
        value = int(float(raw))
    except ValueError:
        return DEFAULT_QUEUE_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_QUEUE_TIMEOUT_SECONDS


def _server_key_from_env() -> str | None:
    """Return a server credential, never falling back to a publishable key."""
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get(
        "SUPABASE_SERVICE_ROLE_KEY"
    )
    if not key:
        return None
    if key.startswith("sb_publishable_") or _legacy_key_role(key) == "anon":
        raise RuntimeError("A publishable/anon Supabase key cannot access the job queue")
    if key.startswith("sb_secret_") or _legacy_key_role(key) == "service_role":
        return key
    raise RuntimeError("Supabase job queue key must be a secret or service-role key")


def _legacy_key_role(key: str) -> str | None:
    """Read only the unverified JWT role claim to reject legacy anon keys."""
    parts = key.split(".")
    if len(parts) != 3:
        return None
    try:
        encoded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(urlsafe_b64decode(encoded).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    role = claims.get("role")
    return role if isinstance(role, str) else None


def _repository_or_default(repository: JobRepository | None) -> JobRepository:
    return repository if repository is not None else SupabaseJobsRepository.from_env()


def enqueue(
    kind: str,
    payload: JsonObject,
    run_after: datetime | None = None,
    *,
    max_attempts: int | None = None,
    repository: JobRepository | None = None,
) -> Job:
    return _repository_or_default(repository).enqueue(kind, payload, run_after, max_attempts)


def claim_next(
    kind_filter: str | None = None, *, repository: JobRepository | None = None
) -> Job | None:
    return _repository_or_default(repository).claim_next(kind_filter)


def checkpoint(
    job_id: str | UUID, state: JsonObject, *, repository: JobRepository | None = None
) -> Job:
    return _repository_or_default(repository).checkpoint(job_id, state)


def complete(job_id: str | UUID, *, repository: JobRepository | None = None) -> Job:
    return _repository_or_default(repository).complete(job_id)


def fail(
    job_id: str | UUID, err: str, *, repository: JobRepository | None = None
) -> Job:
    return _repository_or_default(repository).fail(job_id, err)


def retry_or_dead_letter(
    job_id: str | UUID,
    err: str,
    delay_seconds: float = 0,
    *,
    repository: JobRepository | None = None,
) -> Job:
    return _repository_or_default(repository).retry_or_dead_letter(job_id, err, delay_seconds)


def set_timeout(
    job_id: str | UUID, timeout_seconds: int, *, repository: JobRepository | None = None
) -> Job:
    return _repository_or_default(repository).set_timeout(job_id, timeout_seconds)
