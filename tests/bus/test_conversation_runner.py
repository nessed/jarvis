from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from bus.conversation_runner import build_inline_reply_task, inline_reply_enabled
from executor.handlers.whatsapp import InboundMessage
from router import RoutedResult

DEFAULT_SENDER = "15550001111"


@pytest.fixture(autouse=True)
def _the_default_sender_is_the_owner(monkeypatch):
    """Fail-closed owner gate; same fixture pattern as test_whatsapp_handler.py
    so every test here exercises the real path unless it sets its own sender."""
    monkeypatch.setenv("JARVIS_OWNER_WA_ID", DEFAULT_SENDER)


class FakeFact:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeMemory:
    def __init__(self, recalled=None) -> None:
        self.recalled = recalled if recalled is not None else []
        self.remember_calls: list[tuple[str, dict]] = []
        self.closed = False

    def recall(self, query: str, **kwargs):
        return self.recalled

    def remember_turn(self, text: str, **kwargs):
        self.remember_calls.append((text, kwargs))
        return FakeFact(text)

    def __enter__(self) -> "FakeMemory":
        return self

    def __exit__(self, *_: object) -> None:
        self.closed = True


class FakePendingStore:
    def __init__(self) -> None:
        self.pending: dict[str, object] = {}

    def remember(self, sender, verdict, *, now=None):
        self.pending[sender] = verdict

    def take(self, sender, *, now=None):
        return self.pending.pop(sender, None)

    def clear(self, sender) -> None:
        self.pending.pop(sender, None)

    def __enter__(self) -> "FakePendingStore":
        return self

    def __exit__(self, *_: object) -> None:
        pass


class FakeEnqueuer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, kind, payload):
        self.calls.append((kind, dict(payload)))
        return SimpleNamespace(id=f"job-{len(self.calls)}")


def _fake_completion_response(text: str) -> RoutedResult:
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    return RoutedResult(provider="fake", model="fake-model", response=SimpleNamespace(choices=[choice]))


def _inbound(*, sender: str = DEFAULT_SENDER, text: str = "hello", message_id: str = "wamid.1") -> InboundMessage:
    return InboundMessage(sender=sender, text=text, message_id=message_id)


def _task(*, memory=None, sent=None, enqueuer=None, pending=None, **kwargs):
    sent_calls = sent if sent is not None else []
    defaults = dict(
        open_memory=lambda: memory or FakeMemory(),
        complete=lambda *_: _fake_completion_response("a reply"),
        send_text_message=lambda **call: sent_calls.append(call) or "wamid.reply",
        open_pending_confirmations=lambda: pending or FakePendingStore(),
        enqueue_action=enqueuer or FakeEnqueuer(),
        handle_commands=False,
        write_memory=False,
    )
    defaults.update(kwargs)
    return build_inline_reply_task(**defaults), sent_calls


def test_the_runner_stays_light_enough_for_the_offbox_bus() -> None:
    """Mirrors executor/conversation/service.py's own version of this test:
    the VPS that will run bus/main.py has no GPU, no NPU and no audio stack."""
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    heavy = "{'torch','kokoro','pywinauto','pyflp','sounddevice','voice'}"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import bus.conversation_runner, sys;"
            f" print(sorted(m for m in sys.modules if m.split('.')[0] in {heavy}))",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=repo_root,
    )
    assert completed.stdout.strip() == "[]"


def test_inline_reply_enabled_defaults_on(monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_INLINE_REPLY", raising=False)

    assert inline_reply_enabled() is True


def test_inline_reply_enabled_reads_the_explicit_off_switch(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_INLINE_REPLY", "0")

    assert inline_reply_enabled() is False


def test_answers_a_text_message_and_sends_the_reply() -> None:
    task, sent = _task()

    task(_inbound(text="hi there"))

    assert sent == [{"to": DEFAULT_SENDER, "text": "a reply"}]


def test_non_owner_gets_the_generic_reply_and_nothing_is_recalled_or_remembered() -> None:
    memory = FakeMemory()
    task, sent = _task(memory=memory)

    task(_inbound(sender="15559998888", text="hi there"))

    assert sent == [{"to": "15559998888", "text": "Sorry, I can't help with that."}]
    assert memory.remember_calls == []


def test_memory_write_disabled_by_default_skips_remember() -> None:
    memory = FakeMemory()
    task, _ = _task(memory=memory)

    task(_inbound())

    assert memory.remember_calls == []


def test_memory_writes_persist_both_halves_of_the_turn_when_enabled() -> None:
    memory = FakeMemory()
    task, _ = _task(memory=memory, write_memory=True)

    task(_inbound(text="hi there"))

    assert memory.remember_calls == [
        ("hi there", {"user_id": DEFAULT_SENDER, "role": "user"}),
        ("a reply", {"user_id": DEFAULT_SENDER, "role": "assistant"}),
    ]


def test_an_action_proposal_is_enqueued_with_the_notify_descriptor_and_the_reply_quotes_the_job_id() -> None:
    from executor.handlers.command_intent import CommandVerdict

    verdict = CommandVerdict(
        decision="action",
        kind="system_control",
        payload={"action": "wifi.set_enabled", "args": {"enabled": False}},
        summary="turn wifi off",
        needs_confirmation=False,
    )
    enqueuer = FakeEnqueuer()
    task, sent = _task(enqueuer=enqueuer, classify=lambda text: verdict, handle_commands=True)

    task(_inbound(text="turn wifi off"))

    assert enqueuer.calls == [
        (
            "system_control",
            {
                "action": "wifi.set_enabled",
                "args": {"enabled": False},
                "notify": {
                    "kind": "whatsapp_outcome",
                    "payload": {"reply_to": DEFAULT_SENDER, "summary": "turn wifi off"},
                },
            },
        )
    ]
    assert sent == [{"to": DEFAULT_SENDER, "text": "On it: turn wifi off. Queued as job job-1."}]


def test_reply_latency_line_reports_the_inline_path_with_no_queue_wait(caplog) -> None:
    task, _ = _task()

    with caplog.at_level(logging.INFO, logger="bus.conversation_runner"):
        task(_inbound(message_id="wamid.latency-1"))

    lines = [r.getMessage() for r in caplog.records if "reply-latency" in r.getMessage()]
    assert len(lines) == 1
    assert "job=wamid.latency-1" in lines[0]
    assert "path=inline" in lines[0]
    assert "queue_wait_ms=0" in lines[0]


def test_a_failed_memory_write_does_not_fail_the_reply(caplog) -> None:
    class RaisingMemory(FakeMemory):
        def remember_turn(self, text: str, **kwargs):
            raise RuntimeError("sqlite is locked")

    task, sent = _task(memory=RaisingMemory(), write_memory=True)

    with caplog.at_level(logging.WARNING, logger="bus.conversation_runner"):
        task(_inbound(text="hi there"))

    assert sent == [{"to": DEFAULT_SENDER, "text": "a reply"}]
    assert any("memory write failed" in r.getMessage() for r in caplog.records)
