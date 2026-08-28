"""Dependency-injected status endpoint helpers."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import Request

StatusDependency = Callable[[], Any | Awaitable[Any]]
_QUEUE_STATUSES = ("queued", "running", "done", "failed", "dead_letter")
_LAST_JOB_FIELDS = ("id", "kind", "status", "run_after", "created_at", "updated_at")

# Kept as a local literal rather than importing executor.handlers.distill: that
# module pulls in memory.runtime (local Mem0/Ollama wiring), which is far
# heavier than this dependency-injected status module should import just for
# a string constant. Canonical source of truth is
# executor/handlers/distill.py::DISTILL_JOB_KIND -- keep this in sync with it.
_DISTILL_JOB_KIND = "distill_memory"
_ALIVE_STATUSES = ("queued", "running")


class QueueStatusReader:
    """Read queue observability data without selecting job payloads or checkpoints."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_repository(cls, repository: Any) -> "QueueStatusReader":
        """Adapt the existing Supabase repository without broadening its write contract."""
        client = getattr(repository, "_client", None)
        if client is None:
            raise TypeError("queue status requires a Supabase-backed repository")
        return cls(client)

    def queue_depths(self) -> dict[str, int]:
        """Return durable job counts grouped by their current lifecycle status.

        One COUNT-only query per status (``Prefer: count=exact`` sent as a
        HEAD request via ``head=True``) instead of fetching every row's
        ``status`` column and counting in Python. postgrest-py 1.1.1 (pinned
        via ``supabase==2.18.1``, verified in ``requirements.txt``) exposes
        ``count`` as a header-derived total over one filtered result set --
        there is no GROUP-BY-shaped call in this client version that returns
        all five buckets in one round trip, so five narrow count queries (one
        per ``_QUEUE_STATUSES`` value) is the fewest round trips this client
        actually offers.
        """
        depths: dict[str, int] = {}
        for status in _QUEUE_STATUSES:
            response = (
                self._client.table("jobs")
                .select("id", count="exact", head=True)
                .eq("status", status)
                .execute()
            )
            depths[status] = response.count or 0
        return depths

    def last_job(self) -> dict[str, Any] | None:
        """Return only safe lifecycle metadata for the most recently created job."""
        fields = ",".join(_LAST_JOB_FIELDS)
        response = (
            self._client.table("jobs")
            .select(fields)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        data = response.data or []
        if not data or not isinstance(data[0], Mapping):
            return None
        return {field: data[0][field] for field in _LAST_JOB_FIELDS if field in data[0]}

    def retry_health(self) -> dict[str, int]:
        """Read-only count of dead-lettered jobs and jobs that have been retried.

        Additive to the existing status surface: never selects payloads or
        checkpoints, mirroring ``queue_depths``' safe-field discipline. Two
        COUNT-only queries (``status = 'dead_letter'``, ``attempts > 1``)
        instead of one full-table fetch of every row's ``status`` and
        ``attempts`` columns.
        """
        dead_letter_response = (
            self._client.table("jobs")
            .select("id", count="exact", head=True)
            .eq("status", "dead_letter")
            .execute()
        )
        retried_response = (
            self._client.table("jobs")
            .select("id", count="exact", head=True)
            .gt("attempts", 1)
            .execute()
        )
        return {
            "dead_letter_count": dead_letter_response.count or 0,
            "retried_job_count": retried_response.count or 0,
        }

    def distill_chain_health(self) -> dict[str, Any]:
        """Read-only liveness signal for the self-re-enqueuing distill chain.

        Answers ``docs/audit/blueprint-drift.md``'s exact question without
        selecting payloads: is a ``distill_memory`` row currently
        queued/running (the chain is alive right now), has any
        ``distill_memory`` row ever landed in ``dead_letter`` (the chain has
        died at least once), and has the chain ever been seeded at all --
        so "never run" (zero ``distill_memory`` rows ever) reads distinctly
        from "died" (rows exist, none alive, at least one dead-lettered).
        That distinction matters operationally: "never run" means the chain
        needs seeding, "died" means it needs debugging -- see
        ``executor/handlers/distill.py``'s module docstring on why the chain
        is designed to always re-enqueue and never end on its own, which is
        exactly the invariant a dead chain with no dead-letter row would
        violate.

        Three COUNT-only queries (alive, dead-lettered, total), mirroring
        ``queue_depths``'/``retry_health``'s ``count="exact", head=True``
        pattern rather than fetching rows.
        """
        alive_response = (
            self._client.table("jobs")
            .select("id", count="exact", head=True)
            .eq("kind", _DISTILL_JOB_KIND)
            .in_("status", list(_ALIVE_STATUSES))
            .execute()
        )
        dead_response = (
            self._client.table("jobs")
            .select("id", count="exact", head=True)
            .eq("kind", _DISTILL_JOB_KIND)
            .eq("status", "dead_letter")
            .execute()
        )
        total_response = (
            self._client.table("jobs")
            .select("id", count="exact", head=True)
            .eq("kind", _DISTILL_JOB_KIND)
            .execute()
        )
        return {
            "alive": bool(alive_response.count),
            "dead_letter_count": dead_response.count or 0,
            "has_ever_run": bool(total_response.count),
        }


async def _resolve(dependency: StatusDependency) -> Any:
    result = dependency()
    return await result if inspect.isawaitable(result) else result


async def status_payload(
    *,
    queue_depths: StatusDependency,
    last_job: StatusDependency,
    provider_health: StatusDependency,
    retry_health: StatusDependency | None = None,
    distill_chain_health: StatusDependency | None = None,
) -> dict[str, Any]:
    """Build the status shape from supplied data providers, not global services.

    ``retry_health`` and ``distill_chain_health`` are optional and additive:
    omitting them (every existing caller, today) reproduces the exact prior
    payload shape. Passing either adds its own key without restructuring the
    three original fields.
    """

    depths, latest, providers = await _resolve(queue_depths), await _resolve(last_job), await _resolve(provider_health)
    payload: dict[str, Any] = {
        "queue_depth_by_status": dict(depths) if isinstance(depths, Mapping) else depths,
        "last_job": latest,
        "provider_health": dict(providers) if isinstance(providers, Mapping) else providers,
    }
    if retry_health is not None:
        retries = await _resolve(retry_health)
        payload["retry_health"] = dict(retries) if isinstance(retries, Mapping) else retries
    if distill_chain_health is not None:
        distill = await _resolve(distill_chain_health)
        payload["distill_chain_health"] = dict(distill) if isinstance(distill, Mapping) else distill
    return payload


def create_status_handler(
    *,
    queue_depths: StatusDependency,
    last_job: StatusDependency,
    provider_health: StatusDependency,
    retry_health: StatusDependency | None = None,
    distill_chain_health: StatusDependency | None = None,
) -> Callable[[Request], Awaitable[dict[str, Any]]]:
    """Create a FastAPI-compatible handler that integration can mount at `/status`."""

    async def handler(_: Request) -> dict[str, Any]:
        return await status_payload(
            queue_depths=queue_depths,
            last_job=last_job,
            provider_health=provider_health,
            retry_health=retry_health,
            distill_chain_health=distill_chain_health,
        )

    return handler
