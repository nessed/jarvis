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
        )


class JobRepository(Protocol):
    """Repository contract, kept small so callers can test without Supabase."""

    def enqueue(self, kind: str, payload: JsonObject, run_after: datetime | None = None) -> Job: ...

    def claim_next(self, kind_filter: str | None = None) -> Job | None: ...

    def checkpoint(self, job_id: str | UUID, state: JsonObject) -> Job: ...

    def complete(self, job_id: str | UUID) -> Job: ...

    def fail(self, job_id: str | UUID, err: str) -> Job: ...


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
        except ImportError as exc:  # pragma: no cover - dependency integration
            raise RuntimeError("Install the pinned Supabase dependency first") from exc
        return cls(create_client(url, key))

    def enqueue(self, kind: str, payload: JsonObject, run_after: datetime | None = None) -> Job:
        record: JsonObject = {"kind": kind, "payload": payload}
        if run_after is not None:
            record["run_after"] = run_after.isoformat()
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
    repository: JobRepository | None = None,
) -> Job:
    return _repository_or_default(repository).enqueue(kind, payload, run_after)


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
