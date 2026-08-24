from types import SimpleNamespace

from fastapi.testclient import TestClient

from bus.main import create_app
from bus.status import QueueStatusReader


class FakeQuery:
    def __init__(self, response: SimpleNamespace) -> None:
        self.response = response
        self.order_calls: list[tuple[str, bool]] = []
        self.limit_calls: list[int] = []

    def order(self, field: str, *, desc: bool) -> "FakeQuery":
        self.order_calls.append((field, desc))
        return self

    def limit(self, count: int) -> "FakeQuery":
        self.limit_calls.append(count)
        return self

    def execute(self) -> SimpleNamespace:
        return self.response


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.selects: list[str] = []
        self.depth_query = FakeQuery(
            SimpleNamespace(data=[{"status": "queued"}, {"status": "done"}, {"status": "queued"}])
        )
        self.latest_query = FakeQuery(
            SimpleNamespace(
                data=[
                    {
                        "id": "job-3",
                        "kind": "whatsapp_webhook",
                        "status": "done",
                        "run_after": "2026-08-24T00:00:00Z",
                        "created_at": "2026-08-24T00:00:00Z",
                        "updated_at": "2026-08-24T00:01:00Z",
                        "payload": {"private": "must never leak"},
                        "checkpoint": {"also": "private"},
                    }
                ]
            )
        )

    def table(self, name: str) -> "FakeSupabaseClient":
        assert name == "jobs"
        return self

    def select(self, fields: str) -> FakeQuery:
        self.selects.append(fields)
        return self.depth_query if fields == "status" else self.latest_query


class FakeSupabaseRepository:
    def __init__(self, client: FakeSupabaseClient) -> None:
        self._client = client


def test_reader_reports_lifecycle_counts_and_safe_latest_job_metadata() -> None:
    client = FakeSupabaseClient()
    reader = QueueStatusReader.from_repository(FakeSupabaseRepository(client))

    assert reader.queue_depths() == {"queued": 2, "running": 0, "done": 1, "failed": 0}
    assert reader.last_job() == {
        "id": "job-3",
        "kind": "whatsapp_webhook",
        "status": "done",
        "run_after": "2026-08-24T00:00:00Z",
        "created_at": "2026-08-24T00:00:00Z",
        "updated_at": "2026-08-24T00:01:00Z",
    }
    assert client.selects == ["status", "id,kind,status,run_after,created_at,updated_at"]
    assert client.latest_query.order_calls == [("created_at", True)]
    assert client.latest_query.limit_calls == [1]


def test_status_uses_a_supabase_backed_injected_repository_and_stays_protected() -> None:
    client = FakeSupabaseClient()
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
