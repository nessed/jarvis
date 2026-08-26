from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from db.jobs import Job
from executor.handlers.whatsapp import (
    InboundMessage,
    build_whatsapp_webhook_handler,
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


def _text_message_payload(*, sender: str = "15550001111", text: str = "hello") -> dict[str, object]:
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
                                    "id": "wamid.generic",
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
    def test_extracts_sender_and_text_from_a_real_shaped_payload(self) -> None:
        message = parse_inbound_text_message(_text_message_payload(sender="15550001111", text="Hi there"))

        assert message == InboundMessage(sender="15550001111", text="Hi there")

    def test_status_only_payload_is_not_a_message(self) -> None:
        assert parse_inbound_text_message(_status_only_payload()) is None

    def test_non_text_message_type_is_ignored(self) -> None:
        payload = _text_message_payload()
        payload["entry"][0]["changes"][0]["value"]["messages"][0]["type"] = "image"

        assert parse_inbound_text_message(payload) is None

    def test_empty_payload_is_not_a_message(self) -> None:
        assert parse_inbound_text_message({}) is None


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
            complete=lambda *_: pytest.fail("routing must not be called for a non-message webhook"),
            send_text_message=lambda **kwargs: sent.append(kwargs) or "unused",
        )

        handler(_job(_status_only_payload()))

        assert memory.recall_calls == []
        assert sent == []

    def test_recalls_routes_remembers_and_sends_for_an_inbound_text_message(self) -> None:
        memory = FakeMemory({"results": [{"id": "f1", "memory": "The user's dog is named Max"}]})
        completion_calls: list[tuple[str, list[dict[str, str]]]] = []

        def fake_complete(task_profile, messages):
            completion_calls.append((task_profile, list(messages)))
            return _fake_completion_response("Max is a good boy!")

        sent: list[dict[str, object]] = []
        handler = build_whatsapp_webhook_handler(
            open_memory=lambda: memory,
            complete=fake_complete,
            send_text_message=lambda **kwargs: sent.append(kwargs) or "wamid.reply",
        )

        handler(_job(_text_message_payload(sender="15550001111", text="How's my dog?")))

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

    def test_empty_recall_omits_the_context_message(self) -> None:
        memory = FakeMemory({"results": []})
        completion_calls: list[list[dict[str, str]]] = []

        def fake_complete(task_profile, messages):
            completion_calls.append(list(messages))
            return _fake_completion_response("Sure thing.")

        handler = build_whatsapp_webhook_handler(
            open_memory=lambda: memory,
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
            complete=lambda *_: RoutedResult(provider="fake", model="fake-model", response=object()),
            send_text_message=lambda **kwargs: sent.append(kwargs) or "unused",
        )

        with pytest.raises(ValueError):
            handler(_job(_text_message_payload()))

        assert sent == []
