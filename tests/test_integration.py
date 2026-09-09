import hashlib
import hmac
import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from bus.main import _default_jobs, create_app
from db.jobs import Job


class FakeJobs:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, dict]] = []

    def enqueue(self, kind: str, payload: dict, run_after=None, max_attempts=None) -> Job:
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


class FakeSeenWebhookStore:
    """Stands in for ``SeenWebhookMessageStore`` — same instance is returned by
    every ``open_webhook_dedup()`` call, so marks persist across the two
    separate ``with`` blocks ``receive_webhook`` opens per request, same as a
    real sqlite-backed store would across the same file."""

    def __init__(self) -> None:
        self.seen: set[str] = set()

    def has_seen(self, message_id: str) -> bool:
        return message_id in self.seen

    def mark_seen(self, message_id: str) -> None:
        self.seen.add(message_id)

    def __enter__(self) -> "FakeSeenWebhookStore":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _webhook_payload_with_message_id(message_id: str) -> bytes:
    body = (
        '{"entry":[{"changes":[{"value":{"messages":[{"id":"'
        + message_id
        + '"}]}}]}]}'
    )
    return body.encode()


def test_webhook_redelivery_of_same_message_id_does_not_enqueue_twice() -> None:
    secret = "meta-test-secret"
    jobs = FakeJobs()
    dedup = FakeSeenWebhookStore()
    client = TestClient(
        create_app(
            jobs=jobs,
            meta_app_secret=secret,
            meta_verify_token="verify-test-token",
            bearer_token="bus-test-token",
            open_webhook_dedup=lambda: dedup,
        )
    )
    body = _webhook_payload_with_message_id("wamid.dup-1")

    first = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": _signature(secret, body)})
    second = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": _signature(secret, body)})

    assert first.status_code == 200
    assert first.json() == {"accepted": True, "job_id": "job-1"}
    assert second.status_code == 200
    assert second.json() == {"accepted": True, "duplicate": True}
    assert len(jobs.enqueued) == 1


def test_webhook_with_a_different_message_id_enqueues_normally() -> None:
    secret = "meta-test-secret"
    jobs = FakeJobs()
    dedup = FakeSeenWebhookStore()
    client = TestClient(
        create_app(
            jobs=jobs,
            meta_app_secret=secret,
            meta_verify_token="verify-test-token",
            bearer_token="bus-test-token",
            open_webhook_dedup=lambda: dedup,
        )
    )
    first_body = _webhook_payload_with_message_id("wamid.a")
    second_body = _webhook_payload_with_message_id("wamid.b")

    client.post("/webhook", content=first_body, headers={"X-Hub-Signature-256": _signature(secret, first_body)})
    response = client.post(
        "/webhook", content=second_body, headers={"X-Hub-Signature-256": _signature(secret, second_body)}
    )

    assert response.status_code == 200
    assert response.json() == {"accepted": True, "job_id": "job-1"}
    assert len(jobs.enqueued) == 2


def test_webhook_with_no_extractable_message_ids_still_enqueues_unchanged() -> None:
    """A status-callback-shaped payload (no ``messages`` array): must behave
    byte-for-byte the same as before dedup existed — still enqueue."""
    secret = "meta-test-secret"
    jobs = FakeJobs()
    dedup = FakeSeenWebhookStore()
    client = TestClient(
        create_app(
            jobs=jobs,
            meta_app_secret=secret,
            meta_verify_token="verify-test-token",
            bearer_token="bus-test-token",
            open_webhook_dedup=lambda: dedup,
        )
    )
    body = b'{"entry":[{"id":"event-1"}]}'

    response = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": _signature(secret, body)})

    assert response.status_code == 200
    assert response.json() == {"accepted": True, "job_id": "job-1"}
    assert jobs.enqueued == [("whatsapp_webhook", {"entry": [{"id": "event-1"}]})]
    assert dedup.seen == set()


def _text_webhook_payload(*, sender: str = "15550001111", text: str = "hi", message_id: str = "wamid.text-1") -> bytes:
    return json.dumps(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {"from": sender, "id": message_id, "type": "text", "text": {"body": text}}
                                ]
                            }
                        }
                    ]
                }
            ]
        }
    ).encode()


class TestInlineTextReply:
    """A text message answers in-process instead of enqueueing a job -- see
    ``bus/conversation_runner.py`` and ``conversation-inline-reply``."""

    def test_a_text_message_schedules_the_inline_task_instead_of_enqueueing(self) -> None:
        secret = "meta-test-secret"
        jobs = FakeJobs()
        answered: list = []
        body = _text_webhook_payload()
        client = TestClient(
            create_app(
                jobs=jobs,
                meta_app_secret=secret,
                meta_verify_token="verify-test-token",
                bearer_token="bus-test-token",
                open_webhook_dedup=lambda: FakeSeenWebhookStore(),
                answer_inline=lambda inbound: answered.append(inbound),
            )
        )

        response = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": _signature(secret, body)})

        assert response.status_code == 200
        assert response.json() == {"accepted": True}
        assert jobs.enqueued == []
        assert len(answered) == 1
        assert answered[0].sender == "15550001111"
        assert answered[0].text == "hi"

    def test_a_redelivered_text_message_is_deduped_before_scheduling_the_task(self) -> None:
        secret = "meta-test-secret"
        jobs = FakeJobs()
        answered: list = []
        dedup = FakeSeenWebhookStore()
        body = _text_webhook_payload(message_id="wamid.text-dup")
        client = TestClient(
            create_app(
                jobs=jobs,
                meta_app_secret=secret,
                meta_verify_token="verify-test-token",
                bearer_token="bus-test-token",
                open_webhook_dedup=lambda: dedup,
                answer_inline=lambda inbound: answered.append(inbound),
            )
        )

        first = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": _signature(secret, body)})
        second = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": _signature(secret, body)})

        assert first.json() == {"accepted": True}
        assert second.json() == {"accepted": True, "duplicate": True}
        assert len(answered) == 1

    def test_a_voice_note_still_enqueues_instead_of_answering_inline(self) -> None:
        secret = "meta-test-secret"
        jobs = FakeJobs()
        answered: list = []
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "15550001111",
                                        "id": "wamid.voice-1",
                                        "type": "audio",
                                        "audio": {"id": "media-1"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        body = json.dumps(payload).encode()
        client = TestClient(
            create_app(
                jobs=jobs,
                meta_app_secret=secret,
                meta_verify_token="verify-test-token",
                bearer_token="bus-test-token",
                open_webhook_dedup=lambda: FakeSeenWebhookStore(),
                answer_inline=lambda inbound: answered.append(inbound),
            )
        )

        response = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": _signature(secret, body)})

        assert response.status_code == 200
        assert response.json() == {"accepted": True, "job_id": "job-1"}
        assert jobs.enqueued == [("whatsapp_webhook", payload)]
        assert answered == []

    def test_inline_reply_disabled_falls_back_to_enqueueing_text_too(self, monkeypatch) -> None:
        monkeypatch.setenv("JARVIS_INLINE_REPLY", "0")
        secret = "meta-test-secret"
        jobs = FakeJobs()
        answered: list = []
        body = _text_webhook_payload(message_id="wamid.text-flagged-off")
        client = TestClient(
            create_app(
                jobs=jobs,
                meta_app_secret=secret,
                meta_verify_token="verify-test-token",
                bearer_token="bus-test-token",
                open_webhook_dedup=lambda: FakeSeenWebhookStore(),
                answer_inline=lambda inbound: answered.append(inbound),
            )
        )

        response = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": _signature(secret, body)})

        assert response.status_code == 200
        assert response.json() == {"accepted": True, "job_id": "job-1"}
        assert len(jobs.enqueued) == 1
        assert answered == []


def test_status_is_bearer_protected_and_reports_integrated_shape() -> None:
    client = TestClient(
        create_app(
            # jobs= injected so create_app does not build a live Supabase
            # client this test never uses; see conftest.py's network guard.
            jobs=object(),
            bearer_token="bus-test-token",
            queue_depths=lambda: {"queued": 1, "running": 0},
            last_job=lambda: {"id": "job-1", "status": "queued"},
            retry_health=lambda: {"dead_letter_count": 0, "retried_job_count": 0},
        )
    )

    response = client.get("/status", headers={"Authorization": "Bearer bus-test-token"})

    assert response.status_code == 200
    assert response.json()["queue_depth_by_status"] == {"queued": 1, "running": 0}
    assert response.json()["last_job"] == {"id": "job-1", "status": "queued"}
    assert "groq" in response.json()["provider_health"]


def _unset_supabase_credentials(monkeypatch) -> None:
    for name in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_default_jobs_falls_back_to_none_when_supabase_is_not_configured(monkeypatch) -> None:
    """``SupabaseJobsRepository.from_env()`` raises ``RuntimeError`` with no credentials;
    ``_default_jobs`` must catch that and return ``None`` rather than let it propagate
    out of app construction."""
    _unset_supabase_credentials(monkeypatch)

    assert _default_jobs() is None


def test_create_app_without_a_jobs_override_falls_back_to_none_when_unconfigured(monkeypatch) -> None:
    _unset_supabase_credentials(monkeypatch)

    app = create_app(
        meta_app_secret="meta-test-secret",
        meta_verify_token="verify-test-token",
        bearer_token="bus-test-token",
    )

    assert app.state.jobs is None


def test_the_none_fallback_fails_loudly_on_a_webhook_instead_of_silently_dropping_it(monkeypatch) -> None:
    """When app.state.jobs is None, the webhook handler passes ``repository=None`` through
    to ``enqueue``, which re-resolves via ``SupabaseJobsRepository.from_env()`` and raises
    again. The fallback must not swallow an inbound message: it should fail, not no-op."""
    _unset_supabase_credentials(monkeypatch)
    secret = "meta-test-secret"
    client = TestClient(
        create_app(
            meta_app_secret=secret,
            meta_verify_token="verify-test-token",
            bearer_token="bus-test-token",
        ),
        raise_server_exceptions=False,
    )
    body = b'{"entry":[{"id":"event-1"}]}'

    response = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": _signature(secret, body)})

    assert response.status_code == 500
