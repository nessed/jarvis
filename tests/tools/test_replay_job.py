"""Tests for the job replay harness.

Everything here runs against fakes. No Supabase, no Ollama, no provider, no
Graph API, no whisper-server, no Kokoro -- the point of the tool is that the
*handler* is real while everything around it is not, and the point of these
tests is that the fakes are wired to the seams the handler actually uses.

The two behaviours worth guarding hardest are the refusals: a replay must
never mark a message as sent, and it must never silently run an action
handler that has no fakeable outbound seam.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from tools.replay_job import (
    RecordingMemory,
    RecordingSeenStore,
    ReplayError,
    ReplayTrail,
    SupabaseJobSource,
    _force_utf8_output,
    build_parser,
    build_replay_handler,
    job_from_payload_file,
    main,
    render_trail,
    replay,
    run,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeFact:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeMemory:
    """Stands in for ConversationMemory. Records what was stored."""

    def __init__(self, hits: list[str] | None = None) -> None:
        self.hits = [FakeFact(text) for text in (hits or [])]
        self.stored: list[tuple[str, str]] = []
        self.closed = False

    def recall(self, query: str, *, user_id: str, limit: int = 10) -> list[FakeFact]:
        return self.hits

    def remember_turn(self, text: str, *, user_id: str, role: str) -> None:
        self.stored.append((role, text))

    def close(self) -> None:
        self.closed = True


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.choices = [
            type("Choice", (), {"message": type("Message", (), {"content": text})()})()
        ]


class FakeRouted:
    def __init__(self, text: str, provider: str = "groq", model: str = "llama-3.1-8b") -> None:
        self.provider = provider
        self.model = model
        self.response = FakeResponse(text)


def text_payload(body: str = "hello", message_id: str = "wamid.TEXT") -> dict[str, Any]:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "923001234567",
                                    "id": message_id,
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def voice_payload(media_id: str = "MEDIA-1", message_id: str = "wamid.VOICE") -> dict[str, Any]:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "923001234567",
                                    "id": message_id,
                                    "type": "audio",
                                    "audio": {"id": media_id},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def build(
    trail: ReplayTrail,
    memory: FakeMemory,
    *,
    reply: str = "hi back",
    already_replied: bool = False,
    **kwargs: Any,
):
    """The handler under test, with every outward seam faked."""
    calls: list[tuple[str, Any]] = []

    def completion(task_profile: str, messages: Any) -> FakeRouted:
        calls.append((task_profile, list(messages)))
        return FakeRouted(reply)

    handler = build_replay_handler(
        trail,
        open_real_memory=lambda: memory,
        real_dedup_verdict=lambda: already_replied,
        completion=completion,
        **kwargs,
    )
    return handler, calls


# ---------------------------------------------------------------------------
# Payload loading
# ---------------------------------------------------------------------------


def test_payload_file_becomes_a_job_with_obvious_placeholder_columns(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text(json.dumps(text_payload()), encoding="utf-8")

    job = job_from_payload_file(path, kind="whatsapp_webhook")

    assert job.payload == text_payload()
    assert job.kind == "whatsapp_webhook"
    # Not a plausible-looking uuid: a file replay must never read as a queue row.
    assert job.id == "replay-from-file"
    assert job.status == "replay"


def test_a_missing_payload_file_is_a_replay_error_not_a_traceback(tmp_path: Path) -> None:
    with pytest.raises(ReplayError, match="Could not read"):
        job_from_payload_file(tmp_path / "nope.json", kind="whatsapp_webhook")


def test_malformed_json_is_a_replay_error(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ReplayError, match="not valid JSON"):
        job_from_payload_file(path, kind="whatsapp_webhook")


def test_a_json_list_is_rejected_since_a_payload_is_an_object(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ReplayError, match="must hold a JSON object"):
        job_from_payload_file(path, kind="whatsapp_webhook")


# ---------------------------------------------------------------------------
# The trail over a real handler run
# ---------------------------------------------------------------------------


def test_a_text_replay_records_the_whole_decision_trail(tmp_path: Path) -> None:
    trail = ReplayTrail()
    memory = FakeMemory(hits=["he lives in Lahore"])
    handler, calls = build(trail, memory, reply="Sure thing.")

    job = job_from_payload_file(_write(tmp_path, text_payload("what's up")), kind="whatsapp_webhook")
    replay(job, handler, trail)

    assert trail.already_replied is False
    assert trail.typing_cue is True
    assert trail.recall_query == "what's up"
    assert trail.recall_hits == ["he lives in Lahore"]
    assert trail.routed_provider == "groq"
    assert trail.routed_model == "llama-3.1-8b"
    assert trail.reply == "Sure thing."
    assert trail.sent_as == "text to 923001234567"
    # The reply call is the last one. The handler routes at least one earlier
    # call through the same seam (the command classifier), so this asserts on
    # the tail rather than on calls[0].
    assert calls[-1][0] == "latency"
    assert trail.routed_calls[-1] == ("latency", "groq", "llama-3.1-8b")


def test_recall_hits_reach_the_prompt_the_real_handler_builds(tmp_path: Path) -> None:
    """The trail is only useful if it reflects what the model actually saw."""
    trail = ReplayTrail()
    memory = FakeMemory(hits=["he lives in Lahore"])
    handler, calls = build(trail, memory)

    replay(job_from_payload_file(_write(tmp_path, text_payload()), kind="whatsapp_webhook"), handler, trail)

    # calls[-1] is the reply completion. Earlier calls belong to the command
    # classifier, which is deliberately not handed recalled memory.
    prompt = "\n".join(str(message["content"]) for message in calls[-1][1])
    assert "he lives in Lahore" in prompt
    assert "<remembered_context>" in prompt


def test_memory_writes_are_recorded_but_dropped_by_default(tmp_path: Path) -> None:
    trail = ReplayTrail()
    memory = FakeMemory()
    handler, _ = build(trail, memory, reply="ok")

    replay(job_from_payload_file(_write(tmp_path, text_payload("hi")), kind="whatsapp_webhook"), handler, trail)

    assert trail.memory_writes == [("user", "hi"), ("assistant", "ok")]
    assert memory.stored == []
    assert trail.memory_writes_stored is False


def test_memory_writes_reach_the_store_when_opted_in(tmp_path: Path) -> None:
    trail = ReplayTrail()
    memory = FakeMemory()
    handler, _ = build(trail, memory, reply="ok", memory_writes=True)

    replay(job_from_payload_file(_write(tmp_path, text_payload("hi")), kind="whatsapp_webhook"), handler, trail)

    assert memory.stored == [("user", "hi"), ("assistant", "ok")]
    assert trail.memory_writes_stored is True


# ---------------------------------------------------------------------------
# Dedup: reported, bypassed, never written
# ---------------------------------------------------------------------------


def test_an_already_answered_message_still_replays_and_says_so(tmp_path: Path) -> None:
    trail = ReplayTrail()
    memory = FakeMemory()
    handler, _ = build(trail, memory, reply="again", already_replied=True)

    replay(job_from_payload_file(_write(tmp_path, text_payload()), kind="whatsapp_webhook"), handler, trail)

    assert trail.already_replied is True
    assert trail.reply == "again"  # bypassed, so the handler ran to the end
    assert "bypassed for replay" in render_trail(trail, respected_dedup=False)


def test_respect_dedup_stops_the_handler_exactly_where_production_would(tmp_path: Path) -> None:
    trail = ReplayTrail()
    memory = FakeMemory()
    handler, calls = build(trail, memory, already_replied=True, respect_dedup=True)

    replay(job_from_payload_file(_write(tmp_path, text_payload()), kind="whatsapp_webhook"), handler, trail)

    assert trail.already_replied is True
    assert trail.reply is None
    assert calls == []  # no provider was ever called, classifier included
    assert trail.routed_calls == []


def test_the_seen_store_never_records_a_send() -> None:
    """The load-bearing refusal: a replay must not make the live executor skip it."""
    trail = ReplayTrail()
    store = RecordingSeenStore(trail, real_verdict=False, respect=False)

    store.mark_sent("wamid.TEXT")

    assert store.has_sent("wamid.TEXT") is False


# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------


def test_a_voice_payload_without_audio_refuses_rather_than_calling_meta(tmp_path: Path) -> None:
    trail = ReplayTrail()
    handler, _ = build(trail, FakeMemory())

    job = job_from_payload_file(_write(tmp_path, voice_payload()), kind="whatsapp_webhook")
    with pytest.raises(ReplayError, match="--audio-file"):
        replay(job, handler, trail)


def test_a_local_clip_replaces_the_media_download(tmp_path: Path) -> None:
    trail = ReplayTrail()
    memory = FakeMemory()
    handler, _ = build(
        trail,
        memory,
        reply="spoken back",
        audio_override=b"OggS-fake-bytes",
        transcript_override="mera naam kya hai",
    )

    job = job_from_payload_file(_write(tmp_path, voice_payload()), kind="whatsapp_webhook")
    replay(job, handler, trail)

    assert trail.downloaded_media == "15 bytes from --audio-file"
    assert trail.transcript == "mera naam kya hai"
    assert trail.recall_query == "mera naam kya hai"
    assert trail.sent_as == "voice note to 923001234567"


def test_synthesis_is_skipped_by_default_but_the_reply_text_is_still_shown(tmp_path: Path) -> None:
    trail = ReplayTrail()
    handler, _ = build(
        trail, FakeMemory(), reply="spoken back", audio_override=b"x", transcript_override="hi"
    )

    replay(job_from_payload_file(_write(tmp_path, voice_payload()), kind="whatsapp_webhook"), handler, trail)

    assert trail.reply == "spoken back"
    assert trail.synthesized_bytes is None


def test_synthesis_runs_when_asked_and_reports_its_size(tmp_path: Path) -> None:
    trail = ReplayTrail()
    handler, _ = build(
        trail,
        FakeMemory(),
        reply="spoken back",
        audio_override=b"x",
        transcript_override="hi",
        synthesize=lambda text: b"OggS" * 10,
    )

    replay(job_from_payload_file(_write(tmp_path, voice_payload()), kind="whatsapp_webhook"), handler, trail)

    assert trail.synthesized_bytes == 40


def test_a_transcript_override_means_the_transcriber_is_never_called(tmp_path: Path) -> None:
    def exploding(audio: bytes) -> str:  # pragma: no cover - must not run
        raise AssertionError("whisper-server must not be reached when --transcript is given")

    trail = ReplayTrail()
    handler, _ = build(
        trail,
        FakeMemory(),
        audio_override=b"x",
        transcript_override="typed instead",
        transcribe=exploding,
    )

    replay(job_from_payload_file(_write(tmp_path, voice_payload()), kind="whatsapp_webhook"), handler, trail)

    assert trail.transcript == "typed instead"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_every_routed_call_is_recorded_not_just_the_reply(tmp_path: Path) -> None:
    """The handler routes a command-classifier call through the same seam. A
    trail that kept only the last one would hide a provider call the reader is
    paying for."""
    trail = ReplayTrail()
    handler, calls = build(trail, FakeMemory(), reply="ok")

    replay(job_from_payload_file(_write(tmp_path, text_payload()), kind="whatsapp_webhook"), handler, trail)

    assert len(trail.routed_calls) == len(calls) >= 1
    rendered = render_trail(trail, respected_dedup=False)
    assert f"routed     #{len(calls)}" in rendered
    assert "(reply)" in rendered


def test_render_labels_earlier_routed_calls_as_pre_reply() -> None:
    trail = ReplayTrail(
        job_id="a",
        kind="whatsapp_webhook",
        routed_calls=[("latency", "groq", "m1"), ("latency", "openrouter", "m2")],
    )

    rendered = render_trail(trail, respected_dedup=False)

    assert "routed     #1 latency -> groq / m1  (pre-reply)" in rendered
    assert "routed     #2 latency -> openrouter / m2  (reply)" in rendered


def test_render_puts_every_stage_on_its_own_line() -> None:
    trail = ReplayTrail(
        job_id="abc",
        kind="whatsapp_webhook",
        already_replied=False,
        typing_cue=True,
        recall_query="q",
        recall_hits=["one", "two"],
        routed_calls=[("latency", "groq", "m")],
        routed_provider="groq",
        routed_model="m",
        reply="r",
        sent_as="text to 92300",
    )

    rendered = render_trail(trail, respected_dedup=False)

    assert "job        abc  (whatsapp_webhook)" in rendered
    assert "dedup      not seen before" in rendered
    assert "recall     2 hit(s) for 'q'" in rendered
    assert "           - one" in rendered
    assert "routed     #1 latency -> groq / m  (reply)" in rendered
    assert "nothing left this machine" in rendered


def test_render_survives_non_cp1252_text() -> None:
    """The reason stdout is reconfigured: a real Urdu recall hit must render."""
    trail = ReplayTrail(job_id="a", kind="whatsapp_webhook", recall_query="نام", recall_hits=["میرا نام"])

    rendered = render_trail(trail, respected_dedup=False)

    assert "میرا نام" in rendered
    assert rendered.encode("utf-8")


# ---------------------------------------------------------------------------
# The queue reader
# ---------------------------------------------------------------------------


class FakeTable:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.calls: list[tuple[str, Any]] = []

    def select(self, columns: str) -> "FakeTable":
        self.calls.append(("select", columns))
        return self

    def eq(self, column: str, value: Any) -> "FakeTable":
        self.calls.append(("eq", (column, value)))
        return self

    def limit(self, n: int) -> "FakeTable":
        self.calls.append(("limit", n))
        return self

    def execute(self) -> Any:
        return type("Response", (), {"data": self._rows})()


class FakeClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.table_obj = FakeTable(rows)
        self.tables: list[str] = []

    def table(self, name: str) -> FakeTable:
        self.tables.append(name)
        return self.table_obj

    def rpc(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - must not run
        raise AssertionError("a replay must never call a mutating rpc")


def _row(job_id: str = "0f3c") -> dict[str, Any]:
    return {
        "id": job_id,
        "kind": "whatsapp_webhook",
        "payload": text_payload(),
        "status": "failed",
        "checkpoint": {},
        "run_after": "2026-09-01T00:00:00Z",
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
        "attempts": 3,
    }


def test_fetching_a_job_is_a_plain_select_with_no_claim() -> None:
    client = FakeClient([_row()])

    job = SupabaseJobSource(client).fetch("0f3c")

    assert job is not None
    assert job.id == "0f3c"
    assert job.status == "failed"
    assert job.attempts == 3
    assert client.tables == ["jobs"]
    assert client.table_obj.calls == [("select", "*"), ("eq", ("id", "0f3c")), ("limit", 1)]


def test_fetching_a_missing_job_returns_none_rather_than_raising() -> None:
    assert SupabaseJobSource(FakeClient([])).fetch("nope") is None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _args(**overrides: Any) -> argparse.Namespace:
    base = dict(
        payload_file=None,
        job_id=None,
        kind="whatsapp_webhook",
        respect_dedup=False,
        memory_writes=False,
        transcript=None,
        audio_file=None,
        synthesize=False,
        allow_side_effects=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_another_kind_refuses_without_explicit_consent() -> None:
    with pytest.raises(ReplayError, match="--allow-side-effects"):
        run(_args(kind="system_control", payload_file=Path("unused.json")))


def test_another_kind_still_refuses_with_consent_because_it_is_not_wired() -> None:
    """Consent is not capability. The second refusal names why, not just that."""
    with pytest.raises(ReplayError, match="not wired yet"):
        run(_args(kind="flp_sort", payload_file=Path("unused.json"), allow_side_effects=True))


def test_a_missing_job_id_is_a_replay_error() -> None:
    with pytest.raises(ReplayError, match="No job with id"):
        run(_args(job_id="ghost"), job_source=SupabaseJobSource(FakeClient([])))


def test_an_unreadable_audio_file_is_a_replay_error(tmp_path: Path) -> None:
    with pytest.raises(ReplayError, match="Could not read"):
        run(_args(payload_file=_write(tmp_path, text_payload()), audio_file=tmp_path / "gone.ogg"))


def test_the_cli_requires_a_source() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_payload_file_and_job_id_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--payload-file", "a.json", "--job-id", "b"])


def test_main_turns_a_replay_error_into_exit_1_and_a_message(capsys) -> None:
    code = main(["--payload-file", "definitely-missing.json"])

    assert code == 1
    assert "error:" in capsys.readouterr().err


def test_stdout_is_forced_to_utf8(monkeypatch) -> None:
    """cp1252 is this machine's default; this is the pin that keeps a real
    trail printable. Asserted against a real TextIOWrapper opened in cp1252,
    because that is the exact stream shape the failure happened on."""
    import io as _io
    import sys as _sys

    stream = _io.TextIOWrapper(_io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(_sys, "stdout", stream)
    monkeypatch.setattr(_sys, "stderr", stream)
    assert stream.encoding == "cp1252"

    _force_utf8_output()

    assert stream.encoding == "utf-8"
    stream.write("میرا نام")  # would raise UnicodeEncodeError at cp1252


def test_forcing_utf8_tolerates_a_stream_that_is_not_a_text_wrapper(monkeypatch) -> None:
    """pytest's capture and a piped run both replace stdout with something
    that has no reconfigure(). Forcing the encoding must not be what breaks
    the tool in those cases."""
    import sys as _sys

    class NotAWrapper:
        pass

    monkeypatch.setattr(_sys, "stdout", NotAWrapper())
    monkeypatch.setattr(_sys, "stderr", NotAWrapper())

    _force_utf8_output()  # must not raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_recording_memory_closes_the_inner_store() -> None:
    memory = FakeMemory()
    with RecordingMemory(memory, ReplayTrail(), write=False):
        pass
    assert memory.closed is True
