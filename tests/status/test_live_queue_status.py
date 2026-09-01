import asyncio
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

import bus.main as bus_main
from bus.main import create_app
from bus.status import QueueStatusReader, create_status_handler
from router import health_report


class FakeQuery:
    """Mimics postgrest-py's chained filter builder against an in-memory table.

    Supports exactly the operations bus/status.py actually issues: ``.eq``,
    ``.gt``, ``.in_`` filters, ``.order``/``.limit`` for the full-row
    ``last_job`` query, and count-mode ``.execute()`` (``count="exact"``,
    ``head=True``) that reports a row count via ``.count`` without returning
    row bodies -- the real behaviour of a PostgREST HEAD request with a
    ``Prefer: count=exact`` header.
    """

    def __init__(self, client: "FakeSupabaseClient", *, count: str | None, head: bool | None) -> None:
        self._client = client
        self._count = count
        self._head = head
        self._filters: list[tuple[str, str, Any]] = []
        self.order_calls: list[tuple[str, bool]] = []
        self.limit_calls: list[int] = []

    def eq(self, column: str, value: Any) -> "FakeQuery":
        self._filters.append(("eq", column, value))
        return self

    def gt(self, column: str, value: Any) -> "FakeQuery":
        self._filters.append(("gt", column, value))
        return self

    def in_(self, column: str, values: list[Any]) -> "FakeQuery":
        self._filters.append(("in", column, list(values)))
        return self

    def order(self, field: str, *, desc: bool) -> "FakeQuery":
        self.order_calls.append((field, desc))
        return self

    def limit(self, count: int) -> "FakeQuery":
        self.limit_calls.append(count)
        return self

    def _matching_rows(self) -> list[dict[str, Any]]:
        rows = self._client.jobs
        for op, column, value in self._filters:
            if op == "eq":
                rows = [row for row in rows if row.get(column) == value]
            elif op == "gt":
                rows = [
                    row for row in rows
                    if isinstance(row.get(column), (int, float)) and row.get(column) > value
                ]
            elif op == "in":
                rows = [row for row in rows if row.get(column) in value]
        return rows

    def execute(self) -> SimpleNamespace:
        rows = self._matching_rows()
        if self.order_calls:
            field, desc = self.order_calls[-1]
            rows = sorted(rows, key=lambda row: row[field], reverse=desc)
        if self.limit_calls:
            rows = rows[: self.limit_calls[-1]]
        count_value = len(rows) if self._count else None
        data = [] if self._head else rows
        return SimpleNamespace(data=data, count=count_value)


class FakeSupabaseClient:
    """An in-memory ``jobs`` table standing in for the Supabase client.

    ``select_calls`` records every ``(columns, count, head)`` triple so a
    test can assert the query shape actually used -- how many round trips,
    whether they were count-only -- catching a regression back to
    fetch-everything-and-count-in-Python.
    """

    def __init__(self, jobs: list[dict[str, Any]]) -> None:
        self.jobs = jobs
        self.select_calls: list[tuple[str, str | None, bool | None]] = []
        self.queries: list[FakeQuery] = []

    def table(self, name: str) -> "FakeSupabaseClient":
        assert name == "jobs"
        return self

    def select(self, fields: str, *, count: str | None = None, head: bool | None = None) -> FakeQuery:
        self.select_calls.append((fields, count, head))
        query = FakeQuery(self, count=count, head=head)
        self.queries.append(query)
        return query


class FakeSupabaseRepository:
    def __init__(self, client: FakeSupabaseClient) -> None:
        self._client = client


_LATEST_JOB_ROW = {
    "id": "job-3",
    "kind": "whatsapp_webhook",
    "status": "done",
    "run_after": "2026-08-24T00:00:00Z",
    "created_at": "2026-08-24T00:00:00Z",
    "updated_at": "2026-08-24T00:01:00Z",
    "attempts": 1,
    "payload": {"private": "must never leak"},
    "checkpoint": {"also": "private"},
}


def test_reader_reports_lifecycle_counts_via_count_only_queries() -> None:
    jobs = [
        {"id": "job-1", "status": "queued", "kind": "whatsapp_webhook", "attempts": 1,
         "created_at": "2026-08-22T00:00:00Z"},
        {"id": "job-2", "status": "queued", "kind": "whatsapp_webhook", "attempts": 1,
         "created_at": "2026-08-23T00:00:00Z"},
        dict(_LATEST_JOB_ROW),
    ]
    client = FakeSupabaseClient(jobs)
    reader = QueueStatusReader.from_repository(FakeSupabaseRepository(client))

    assert reader.queue_depths() == {
        "queued": 2,
        "running": 0,
        "done": 1,
        "failed": 0,
        "dead_letter": 0,
    }
    # Five count-only queries, one per _QUEUE_STATUSES value -- never a
    # fetch-every-row-and-count-in-Python select.
    assert client.select_calls == [
        ("id", "exact", True),
        ("id", "exact", True),
        ("id", "exact", True),
        ("id", "exact", True),
        ("id", "exact", True),
    ]
    assert all(query._head for query in client.queries)
    assert [query._filters for query in client.queries] == [
        [("eq", "status", status)]
        for status in ("queued", "running", "done", "failed", "dead_letter")
    ]


def test_reader_reports_safe_latest_job_metadata() -> None:
    jobs = [
        {"id": "job-1", "status": "queued", "kind": "whatsapp_webhook", "attempts": 1,
         "created_at": "2026-08-22T00:00:00Z"},
        dict(_LATEST_JOB_ROW),
    ]
    client = FakeSupabaseClient(jobs)
    reader = QueueStatusReader.from_repository(FakeSupabaseRepository(client))

    assert reader.last_job() == {
        "id": "job-3",
        "kind": "whatsapp_webhook",
        "status": "done",
        "run_after": "2026-08-24T00:00:00Z",
        "created_at": "2026-08-24T00:00:00Z",
        "updated_at": "2026-08-24T00:01:00Z",
    }
    latest_query = client.queries[-1]
    assert latest_query.order_calls == [("created_at", True)]
    assert latest_query.limit_calls == [1]
    assert client.select_calls[-1][0] == "id,kind,status,run_after,created_at,updated_at"


def test_reader_reports_retry_health_via_two_count_only_queries() -> None:
    jobs = [
        {"id": "job-1", "status": "dead_letter", "kind": "whatsapp_webhook", "attempts": 3,
         "created_at": "2026-08-22T00:00:00Z"},
        {"id": "job-2", "status": "done", "kind": "whatsapp_webhook", "attempts": 2,
         "created_at": "2026-08-23T00:00:00Z"},
        {"id": "job-3", "status": "done", "kind": "whatsapp_webhook", "attempts": 1,
         "created_at": "2026-08-24T00:00:00Z"},
    ]
    client = FakeSupabaseClient(jobs)
    reader = QueueStatusReader.from_repository(FakeSupabaseRepository(client))

    assert reader.retry_health() == {"dead_letter_count": 1, "retried_job_count": 2}
    assert client.select_calls == [("id", "exact", True), ("id", "exact", True)]
    assert client.queries[0]._filters == [("eq", "status", "dead_letter")]
    assert client.queries[1]._filters == [("gt", "attempts", 1)]


def test_distill_chain_health_reports_alive_when_a_row_is_queued_or_running() -> None:
    jobs = [
        {"id": "d-1", "kind": "distill_memory", "status": "queued", "attempts": 1,
         "created_at": "2026-08-22T00:00:00Z"},
        {"id": "d-2", "kind": "distill_memory", "status": "dead_letter", "attempts": 3,
         "created_at": "2026-08-20T00:00:00Z"},
    ]
    client = FakeSupabaseClient(jobs)
    reader = QueueStatusReader.from_repository(FakeSupabaseRepository(client))

    assert reader.distill_chain_health() == {
        "alive": True,
        "dead_letter_count": 1,
        "has_ever_run": True,
    }
    # Three count-only queries: alive (kind + status in [...]), dead_letter
    # (kind + status), total (kind only) -- never a full-row fetch.
    assert client.select_calls == [
        ("id", "exact", True),
        ("id", "exact", True),
        ("id", "exact", True),
    ]
    assert client.queries[0]._filters == [
        ("eq", "kind", "distill_memory"),
        ("in", "status", ["queued", "running"]),
    ]
    assert client.queries[1]._filters == [
        ("eq", "kind", "distill_memory"),
        ("eq", "status", "dead_letter"),
    ]
    assert client.queries[2]._filters == [("eq", "kind", "distill_memory")]


def test_distill_chain_health_reports_dead_when_only_dead_letter_rows_exist() -> None:
    jobs = [
        {"id": "d-1", "kind": "distill_memory", "status": "dead_letter", "attempts": 3,
         "created_at": "2026-08-20T00:00:00Z"},
        {"id": "other", "kind": "whatsapp_webhook", "status": "queued", "attempts": 1,
         "created_at": "2026-08-22T00:00:00Z"},
    ]
    client = FakeSupabaseClient(jobs)
    reader = QueueStatusReader.from_repository(FakeSupabaseRepository(client))

    assert reader.distill_chain_health() == {
        "alive": False,
        "dead_letter_count": 1,
        "has_ever_run": True,
    }


def test_distill_chain_health_reports_never_run_distinctly_from_died() -> None:
    """Zero distill_memory rows ever is a different state than a dead chain.

    "Never run" means the chain needs seeding; "died" means it needs
    debugging (see executor/handlers/distill.py's module docstring: the
    chain is designed to always re-enqueue and never end on its own, so a
    dead chain with no dead_letter row would be a different, worse bug).
    Both must report alive=False and dead_letter_count=0, but only
    has_ever_run distinguishes them.
    """
    jobs = [
        {"id": "other", "kind": "whatsapp_webhook", "status": "queued", "attempts": 1,
         "created_at": "2026-08-22T00:00:00Z"},
    ]
    client = FakeSupabaseClient(jobs)
    reader = QueueStatusReader.from_repository(FakeSupabaseRepository(client))

    assert reader.distill_chain_health() == {
        "alive": False,
        "dead_letter_count": 0,
        "has_ever_run": False,
    }


def test_status_uses_a_supabase_backed_injected_repository_and_stays_protected() -> None:
    jobs = [
        {"id": "job-1", "status": "queued", "kind": "whatsapp_webhook", "attempts": 1,
         "created_at": "2026-08-22T00:00:00Z"},
        {"id": "job-2", "status": "queued", "kind": "whatsapp_webhook", "attempts": 1,
         "created_at": "2026-08-23T00:00:00Z"},
        dict(_LATEST_JOB_ROW),
    ]
    client = FakeSupabaseClient(jobs)
    app = create_app(jobs=FakeSupabaseRepository(client), bearer_token="bus-test-token")
    test_client = TestClient(app)

    assert test_client.get("/status").status_code == 401
    response = test_client.get("/status", headers={"Authorization": "Bearer bus-test-token"})

    assert response.status_code == 200
    body = response.json()
    assert body["queue_depth_by_status"]["queued"] == 2
    assert body["last_job"]["id"] == "job-3"
    assert "payload" not in body["last_job"]
    assert "checkpoint" not in body["last_job"]
    assert body["retry_health"] == {"dead_letter_count": 0, "retried_job_count": 0}


def test_status_omits_retry_health_without_a_supabase_backed_repository() -> None:
    app = create_app(
        jobs=object(),
        bearer_token="bus-test-token",
        queue_depths=lambda: {"queued": 1},
        last_job=lambda: None,
    )
    test_client = TestClient(app)

    response = test_client.get("/status", headers={"Authorization": "Bearer bus-test-token"})

    assert response.status_code == 200
    assert "retry_health" not in response.json()
    assert "distill_chain_health" not in response.json()


def test_status_endpoint_includes_distill_chain_health_when_wired() -> None:
    """bus/main.py doesn't pass this through yet (see report) -- this test

    exercises the real HTTP path via create_status_handler directly, the
    same helper create_app's /status route delegates to, so it proves the
    field reaches the JSON response once a caller supplies the dependency.
    """
    app = FastAPI()
    app.add_api_route(
        "/status",
        create_status_handler(
            queue_depths=lambda: {"queued": 1},
            last_job=lambda: None,
            provider_health=lambda: {},
            distill_chain_health=lambda: {
                "alive": False,
                "dead_letter_count": 1,
                "has_ever_run": True,
            },
        ),
        methods=["GET"],
    )
    test_client = TestClient(app)

    response = test_client.get("/status")

    assert response.status_code == 200
    assert response.json()["distill_chain_health"] == {
        "alive": False,
        "dead_letter_count": 1,
        "has_ever_run": True,
    }


# --- /status reports the routing process's ledger -----------------------------
#
# Q10c, 1 Sep 2026. Until then /status read the *bus's* own ProviderRouter.
# The bus is enqueue-only and never calls route(), so every entry stayed at its
# constructed default for the life of the process: /status said "no failures"
# when it meant "no attempts", and the two are indistinguishable in that shape.


def _routed_failure_snapshot():
    """What the executor's router looks like after one 429 with a retry-after."""
    router, _calls = _cooled_down_router()
    return router.health_snapshot()


def _cooled_down_router():
    from router import Provider, ProviderRequestError, ProviderRouter

    calls = []
    names = ("groq", "cerebras")
    endpoint_to_name = {f"https://{name}.example/v1": name for name in names}
    outcomes = {"groq": ProviderRequestError("limited", 429, {"Retry-After": "60"})}

    class _Client:
        def __init__(self, provider):
            self.provider = provider

        async def create_chat_completion(self, *, model, messages, **kwargs):
            calls.append(self.provider)
            outcome = outcomes.get(self.provider)
            if isinstance(outcome, Exception):
                raise outcome
            return {"provider": self.provider}

    router = ProviderRouter(
        [
            Provider(
                name=name,
                endpoint=f"https://{name}.example/v1",
                key_env=f"{name.upper()}_KEY",
                priority=index,
                default_model=f"{name}-model",
                task_profiles=("latency",),
            )
            for index, name in enumerate(names, start=1)
        ],
        environ={"GROQ_KEY": "k", "CEREBRAS_KEY": "k"},
        client_factory=lambda endpoint, key: _Client(endpoint_to_name[endpoint]),
    )
    asyncio.run(router.route("latency", [{"role": "user", "content": "hi"}]))
    return router, calls


def test_status_reports_a_cooldown_the_executor_recorded(tmp_path, monkeypatch) -> None:
    report = tmp_path / "provider-health.json"
    health_report.write(_routed_failure_snapshot(), report)
    # Bound before patching: bus.main reads the same module object, so a lambda
    # that called health_report.read would call itself.
    real_read = health_report.read
    monkeypatch.setattr(bus_main.health_report, "read", lambda: real_read(report))

    client = TestClient(
        create_app(
            bearer_token="token",
            queue_depths=lambda: {},
            last_job=lambda: None,
        )
    )
    body = client.get("/status", headers={"Authorization": "Bearer token"}).json()

    assert body["provider_health"]["groq"]["last_status"] == 429
    assert body["provider_health"]["groq"]["cooldown_seconds_remaining"] > 0
    assert body["provider_health"]["groq"]["reported"] is True


def test_status_says_unreported_rather_than_healthy_when_nothing_has_routed(monkeypatch) -> None:
    monkeypatch.setattr(bus_main.health_report, "read", lambda: None)

    client = TestClient(
        create_app(bearer_token="token", queue_depths=lambda: {}, last_job=lambda: None)
    )
    body = client.get("/status", headers={"Authorization": "Bearer token"}).json()

    groq = body["provider_health"]["groq"]
    assert groq["reported"] is False
    assert groq["last_status"] is None
    assert groq["cooldown_seconds_remaining"] == 0.0


def test_status_still_lists_the_whole_provider_ladder_when_unreported(monkeypatch) -> None:
    """The roster comes from the local manifest, so the key set never shrinks."""
    monkeypatch.setattr(bus_main.health_report, "read", lambda: None)

    client = TestClient(
        create_app(bearer_token="token", queue_depths=lambda: {}, last_job=lambda: None)
    )
    body = client.get("/status", headers={"Authorization": "Bearer token"}).json()

    assert len(body["provider_health"]) > 1
    assert all(entry["reported"] is False for entry in body["provider_health"].values())


def test_a_provider_the_reporter_knows_but_the_manifest_does_not_is_kept(monkeypatch) -> None:
    """A roster that has moved on is exactly when you want to see the difference."""
    monkeypatch.setattr(
        bus_main.health_report,
        "read",
        lambda: {"a-new-rung": {"last_status": 200, "cooldown_seconds_remaining": 0.0, "reported": True}},
    )

    client = TestClient(
        create_app(bearer_token="token", queue_depths=lambda: {}, last_job=lambda: None)
    )
    body = client.get("/status", headers={"Authorization": "Bearer token"}).json()

    assert body["provider_health"]["a-new-rung"]["last_status"] == 200
    assert body["provider_health"]["groq"]["reported"] is False
