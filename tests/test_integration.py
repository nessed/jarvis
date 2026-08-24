import hashlib
import hmac
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from bus.main import create_app
from db.jobs import Job


class FakeJobs:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, dict]] = []

    def enqueue(self, kind: str, payload: dict, run_after=None) -> Job:
        self.enqueued.append((kind, payload))
        now = datetime.now(UTC)
        return Job("job-1", kind, payload, "queued", {}, now, now, now)


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_verifies_then_only_enqueues() -> None:
    secret = "meta-test-secret"
    jobs = FakeJobs()
    client = TestClient(
        create_app(
            jobs=jobs,
            meta_app_secret=secret,
            meta_verify_token="verify-test-token",
            bearer_token="bus-test-token",
            queue_depths=lambda: {"queued": 1},
            last_job=lambda: {"id": "job-1", "status": "queued"},
        )
    )
    body = b'{"entry":[{"id":"event-1"}]}'

    response = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": _signature(secret, body)})

    assert response.status_code == 200
    assert response.json() == {"accepted": True, "job_id": "job-1"}
    assert jobs.enqueued == [("whatsapp_webhook", {"entry": [{"id": "event-1"}]})]


def test_status_is_bearer_protected_and_reports_integrated_shape() -> None:
    client = TestClient(
        create_app(
            bearer_token="bus-test-token",
            queue_depths=lambda: {"queued": 1, "running": 0},
            last_job=lambda: {"id": "job-1", "status": "queued"},
        )
    )

    response = client.get("/status", headers={"Authorization": "Bearer bus-test-token"})

    assert response.status_code == 200
    assert response.json()["queue_depth_by_status"] == {"queued": 1, "running": 0}
    assert response.json()["last_job"] == {"id": "job-1", "status": "queued"}
    assert "groq" in response.json()["provider_health"]
