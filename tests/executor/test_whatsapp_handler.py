from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from db.jobs import Job
from executor.handlers.whatsapp import (
    InboundMessage,
    SeenMessageStore,
    build_whatsapp_webhook_handler,
    open_default_seen_message_store,
    parse_inbound_text_message,
)
from router import RoutedResult


def _job(payload: dict[str, object]) -> Job:
    now = datetime.now(UTC)
    return Job(
        id="job-1",
        kind="whatsapp_webhook",
        payload=payload,
        status="running",
        checkpoint={},
        run_after=now,
        created_at=now,
        updated_at=now,
    )


def _text_message_payload(
    *, sender: str = "15550001111", text: str = "hello", message_id: str = "wamid.generic"
) -> dict[str, object]:
    return {
        "entry": [
            {
                "id": "event-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "contacts": [{"wa_id": sender, "profile": {"name": "Generic User"}}],
                            "messages": [
                                {
                                    "from": sender,
                                    "id": message_id,
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                    }
                ],
            }
        ]
    }


def _status_only_payload() -> dict[str, object]:
    return {
        "entry": [
            {
                "id": "event-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "statuses": [{"id": "wamid.generic", "status": "delivered"}],
                        },
                    }
                ],
            }
        ]
    }


class TestParseInboundTextMessage:
    def test_extracts_sender_text_and_message_id_from_a_real_shaped_payload(self) -> None:
        message = parse_inbound_text_message(
            _text_message_payload(sender="15550001111", text="Hi there", message_id="wamid.abc123")
        )

        assert message == InboundMessage(sender="15550001111", text="Hi there", message_id="wamid.abc123")

    def test_status_only_payload_is_not_a_message(self) -> None:
        assert parse_inbound_text_message(_status_only_payload()) is None

    def test_non_text_message_type_is_ignored(self) -> None:
        payload = _text_message_payload()
        payload["entry"][0]["changes"][0]["value"]["messages"][0]["type"] = "image"

        assert parse_inbound_text_message(payload) is None

    def test_empty_payload_is_not_a_message(self) -> None:
        assert parse_inbound_text_message({}) is None

    def test_missing_message_id_is_not_a_message(self) -> None:
        payload = _text_message_payload()
        del payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"]

        assert parse_inbound_text_message(payload) is None


class FakeMemory:
    def __init__(self, recalled: dict[str, object]) -> None:
        self.recalled = recalled
        self.recall_calls: list[tuple[str, dict[str, object]]] = []
        self.remember_calls: list[tuple[str, dict[str, object]]] = []
        self.closed = False

    def recall(self, query: str, **kwargs: object) -> dict[str, object]:
        self.recall_calls.append((query, kwargs))
        return self.recalled

    def remember(self, text: str, **kwargs: object) -> list[dict[str, object]]:
        self.remember_calls.append((text, kwargs))
        return []

    def __enter__(self) -> "FakeMemory":
        return self

    def __exit__(self, *_: object) -> None:
        self.closed = True


class FakeSeenStore:
    def __init__(self, already_sent: set[str] | None = None) -> None:
        self.sent = set(already_sent or ())
        self.has_sent_calls: list[str] = []
        self.mark_sent_calls: list[str] = []

    def has_sent(self, message_id: str) -> bool:
        self.has_sent_calls.append(message_id)
        return message_id in self.sent

    def mark_sent(self, message_id: str) -> None:
        self.mark_sent_calls.append(message_id)
        self.sent.add(message_id)

    def __enter__(self) -> "FakeSeenStore":
        return self

    def __exit__(self, *_: object) -> None:
        pass


def _fake_completion_response(text: str) -> RoutedResult:
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    return RoutedResult(provider="fake", model="fake-model", response=SimpleNamespace(choices=[choice]))


class TestWhatsAppWebhookHandler:
    def test_no_inbound_message_is_a_silent_no_op(self) -> None:
        memory = FakeMemory({"results": []})
        sent: list[dict[str, object]] = []
        handler = build_whatsapp_webhook_handler(
            open_memory=lambda: memory,
            open_seen_messages=FakeSeenStore,
            complete=lambda *_: pytest.fail("routing must not be called for a non-message webhook"),
            send_text_message=lambda **kwargs: sent.append(kwargs) or "unused",
        )

        handler(_job(_status_only_payload()))

        assert memory.recall_calls == []
        assert sent == []

    def test_recalls_routes_remembers_and_sends_for_an_inbound_text_message(self) -> None:
        memory = FakeMemory({"results": [{"id": "f1", "memory": "The user's dog is named Max"}]})
        seen = FakeSeenStore()
        completion_calls: list[tuple[str, list[dict[str, str]]]] = []

        def fake_complete(task_profile, messages):
            completion_calls.append((task_profile, list(messages)))
            return _fake_completion_response("Max is a good boy!")

        sent: list[dict[str, object]] = []
        handler = build_whatsapp_webhook_handler(
            open_memory=lambda: memory,
            open_seen_messages=lambda: seen,
            complete=fake_complete,
            send_text_message=lambda **kwargs: sent.append(kwargs) or "wamid.reply",
        )

        handler(_job(_text_message_payload(sender="15550001111", text="How's my dog?", message_id="wamid.1")))

        assert memory.recall_calls == [("How's my dog?", {"user_id": "15550001111"})]
        assert memory.closed is True

        assert len(completion_calls) == 1
        task_profile, messages = completion_calls[0]
        assert task_profile == "latency"
        assert messages[-1] == {"role": "user", "content": "How's my dog?"}
        assert any("The user's dog is named Max" in m["content"] for m in messages)

        assert memory.remember_calls == [
            ("User: How's my dog?", {"user_id": "15550001111"}),
            ("Assistant: Max is a good boy!", {"user_id": "15550001111"}),
        ]

        assert sent == [{"to": "15550001111", "text": "Max is a good boy!"}]
        assert seen.mark_sent_calls == ["wamid.1"]

    def test_empty_recall_omits_the_context_message(self) -> None:
        memory = FakeMemory({"results": []})
        completion_calls: list[list[dict[str, str]]] = []

        def fake_complete(task_profile, messages):
            completion_calls.append(list(messages))
            return _fake_completion_response("Sure thing.")

        handler = build_whatsapp_webhook_handler(
            open_memory=lambda: memory,
            open_seen_messages=FakeSeenStore,
            complete=fake_complete,
            send_text_message=lambda **kwargs: "wamid.reply",
        )

        handler(_job(_text_message_payload(text="Anything new?")))

        [messages] = completion_calls
        assert [m["role"] for m in messages] == ["system", "user"]

    def test_unexpected_completion_shape_raises_instead_of_sending_garbage(self) -> None:
        memory = FakeMemory({"results": []})
        sent: list[dict[str, object]] = []
        handler = build_whatsapp_webhook_handler(
            open_memory=lambda: memory,
            open_seen_messages=FakeSeenStore,
            complete=lambda *_: RoutedResult(provider="fake", model="fake-model", response=object()),
            send_text_message=lambda **kwargs: sent.append(kwargs) or "unused",
        )

        with pytest.raises(ValueError):
            handler(_job(_text_message_payload()))

        assert sent == []

    def test_a_message_id_already_marked_sent_is_skipped_without_doing_any_work(self) -> None:
        seen = FakeSeenStore(already_sent={"wamid.dup"})
        handler = build_whatsapp_webhook_handler(
            open_memory=lambda: pytest.fail("memory must not be touched for an already-sent message"),
            open_seen_messages=lambda: seen,
            complete=lambda *_: pytest.fail("routing must not be called for an already-sent message"),
            send_text_message=lambda **kwargs: pytest.fail("must not resend an already-sent message"),
        )

        handler(_job(_text_message_payload(message_id="wamid.dup")))

        assert seen.has_sent_calls == ["wamid.dup"]
        assert seen.mark_sent_calls == []

    def test_a_failed_attempt_does_not_mark_the_message_sent_so_a_retry_still_goes_through(self) -> None:
        memory = FakeMemory({"results": []})
        seen = FakeSeenStore()
        handler = build_whatsapp_webhook_handler(
            open_memory=lambda: memory,
            open_seen_messages=lambda: seen,
            complete=lambda *_: (_ for _ in ()).throw(RuntimeError("provider is down")),
            send_text_message=lambda **kwargs: pytest.fail("must not send when routing failed"),
        )

        with pytest.raises(RuntimeError):
            handler(_job(_text_message_payload(message_id="wamid.retry-me")))

        assert seen.mark_sent_calls == []
        assert seen.has_sent("wamid.retry-me") is False


class TestSeenMessageStore:
    def test_unmarked_message_id_has_not_been_sent(self, tmp_path) -> None:
        with SeenMessageStore(tmp_path / "seen.db") as store:
            assert store.has_sent("wamid.new") is False

    def test_marking_sent_persists_across_a_reopened_connection(self, tmp_path) -> None:
        path = tmp_path / "seen.db"
        with SeenMessageStore(path) as store:
            store.mark_sent("wamid.once")

        with SeenMessageStore(path) as reopened:
            assert reopened.has_sent("wamid.once") is True
            assert reopened.has_sent("wamid.never-seen") is False

    def test_marking_the_same_id_twice_does_not_raise(self, tmp_path) -> None:
        with SeenMessageStore(tmp_path / "seen.db") as store:
            store.mark_sent("wamid.dup")
            store.mark_sent("wamid.dup")

            assert store.has_sent("wamid.dup") is True

    def test_open_default_seen_message_store_derives_its_path_from_memory_db_path(self, tmp_path) -> None:
        memory_path = tmp_path / "custom-memory.db"
        store = open_default_seen_message_store(environ={"MEMORY_DB_PATH": str(memory_path)})
        try:
            store.mark_sent("wamid.custom-path")
            assert store.has_sent("wamid.custom-path") is True
        finally:
            store.close()

        assert (tmp_path / "custom-memory.seen-messages.db").exists()
