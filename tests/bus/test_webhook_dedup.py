from __future__ import annotations

from bus.webhook_dedup import SeenWebhookMessageStore, extract_message_ids


def test_unseen_message_is_not_seen(tmp_path) -> None:
    store = SeenWebhookMessageStore(tmp_path / "dedup.db")

    assert store.has_seen("wamid.1") is False


def test_mark_seen_then_has_seen_is_true(tmp_path) -> None:
    store = SeenWebhookMessageStore(tmp_path / "dedup.db")

    store.mark_seen("wamid.1")

    assert store.has_seen("wamid.1") is True


def test_mark_seen_is_idempotent_on_repeat(tmp_path) -> None:
    """INSERT OR IGNORE: marking the same id twice must not raise or change the result."""
    store = SeenWebhookMessageStore(tmp_path / "dedup.db")

    store.mark_seen("wamid.1")
    store.mark_seen("wamid.1")

    assert store.has_seen("wamid.1") is True


def test_seen_state_persists_across_separate_connections_to_the_same_path(tmp_path) -> None:
    path = tmp_path / "dedup.db"
    with SeenWebhookMessageStore(path) as store:
        store.mark_seen("wamid.1")

    with SeenWebhookMessageStore(path) as reopened:
        assert reopened.has_seen("wamid.1") is True


def test_extract_message_ids_collects_every_message_across_entries_and_changes() -> None:
    payload = {
        "entry": [
            {
                "changes": [
                    {"value": {"messages": [{"id": "a"}, {"id": "b"}]}},
                ]
            },
            {
                "changes": [
                    {"value": {"messages": [{"id": "c"}]}},
                ]
            },
        ]
    }

    assert extract_message_ids(payload) == ["a", "b", "c"]


def test_extract_message_ids_counts_non_text_messages_too() -> None:
    payload = {
        "entry": [
            {"changes": [{"value": {"messages": [{"id": "img-1", "type": "image"}]}}]},
        ]
    }

    assert extract_message_ids(payload) == ["img-1"]


def test_extract_message_ids_returns_empty_for_a_status_callback_payload() -> None:
    payload = {"entry": [{"changes": [{"value": {"statuses": [{"id": "status-1"}]}}]}]}

    assert extract_message_ids(payload) == []


def test_extract_message_ids_returns_empty_for_malformed_or_empty_payload() -> None:
    assert extract_message_ids({}) == []
    assert extract_message_ids({"entry": []}) == []
    assert extract_message_ids({"entry": [{"id": "event-1"}]}) == []
