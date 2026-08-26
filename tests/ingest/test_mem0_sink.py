from __future__ import annotations

from ingest.mem0_sink import Mem0BackfillSink


class FakeMemory:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def remember(self, text: str, **kwargs) -> None:
        self.calls.append((text, kwargs))


def test_sink_routes_source_through_metadata_under_a_fixed_user_id() -> None:
    memory = FakeMemory()
    sink = Mem0BackfillSink(memory=memory, user_id="+92-555-0100")

    sink.remember("some fact", "notes/foo.md", metadata={"source_type": "note"})

    text, kwargs = memory.calls[0]
    assert text == "some fact"
    assert kwargs == {
        "user_id": "+92-555-0100",
        "metadata": {"source": "notes/foo.md", "source_type": "note"},
    }


def test_sink_works_without_extra_metadata() -> None:
    memory = FakeMemory()
    sink = Mem0BackfillSink(memory=memory, user_id="jarvis")

    sink.remember("some fact", "notes/foo.md")

    _, kwargs = memory.calls[0]
    assert kwargs["metadata"] == {"source": "notes/foo.md"}


def test_caller_supplied_metadata_can_override_the_source_key() -> None:
    memory = FakeMemory()
    sink = Mem0BackfillSink(memory=memory, user_id="jarvis")

    sink.remember("some fact", "notes/foo.md", metadata={"source": "explicit-override"})

    _, kwargs = memory.calls[0]
    assert kwargs["metadata"]["source"] == "explicit-override"
