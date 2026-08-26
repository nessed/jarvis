from __future__ import annotations

from datetime import UTC, datetime

import pytest

from memory.mem0_wrapper import (
    COMPACT_ADDITIVE_EXTRACTION_PROMPT,
    DEFAULT_FACT_EXTRACTION_MODEL,
    ExtractionResponse,
    Mem0Memory,
    Mem0WrapperError,
    SQLiteVecMem0Store,
    _attach_validating_retry,
    _fact_extraction_model,
    _fact_extraction_timeout,
    _install_compact_extraction_prompt,
)


def test_mem0_provider_delegates_insert_search_update_and_delete_to_local_sqlite(tmp_path):
    provider = SQLiteVecMem0Store(
        collection_name="jarvis_memories",
        embedding_model_dims=2,
        database_path=str(tmp_path / "memory.db"),
        embedding_model="nomic-embed-text",
    )
    payload = {
        "data": "The test project uses a generic memory.",
        "user_id": "test-user",
        "created_at": datetime(2026, 8, 25, tzinfo=UTC).isoformat(),
    }
    provider.insert([[1.0, 0.0]], payloads=[payload], ids=["memory-1"])

    found = provider.search("generic memory", [1.0, 0.0], top_k=5, filters={"user_id": "test-user"})
    assert [(row.id, row.payload["data"]) for row in found] == [("memory-1", payload["data"])]
    assert provider.get("memory-1") is not None

    provider.update("memory-1", vector=[0.0, 1.0], payload={**payload, "data": "Updated generic memory."})
    assert provider.search("updated", [0.0, 1.0], top_k=1)[0].payload["data"] == "Updated generic memory."
    provider.delete("memory-1")
    assert provider.get("memory-1") is None
    provider.close()


def test_mem0_provider_keeps_logical_collections_separate(tmp_path):
    database_path = str(tmp_path / "memory.db")
    primary = SQLiteVecMem0Store("jarvis_memories", 2, database_path, "nomic-embed-text")
    entities = SQLiteVecMem0Store("jarvis_memories_entities", 2, database_path, "nomic-embed-text")
    primary.insert([[1, 0]], payloads=[{"data": "generic fact"}], ids=["fact"])
    entities.insert([[1, 0]], payloads=[{"data": "generic entity"}], ids=["entity"])

    assert [row.id for row in primary.search("fact", [1, 0])] == ["fact"]
    assert [row.id for row in entities.search("entity", [1, 0])] == ["entity"]
    primary.close()
    entities.close()


def test_mem0_validation_retries_once_then_raises():
    class FakeLlm:
        def __init__(self):
            self.calls = 0

        def generate_response(self, *args, **kwargs):
            self.calls += 1
            return '{"memory":[{"wrong":"shape"}]}'

    class FakeMemory:
        llm = FakeLlm()

    memory = FakeMemory()
    _attach_validating_retry(memory)
    with pytest.raises(Mem0WrapperError, match="after one retry"):
        memory.llm.generate_response(response_format={"type": "json_object"})
    assert memory.llm.calls == 2


def test_mem0_validation_accepts_shipped_adapter_json_shape():
    class FakeLlm:
        def generate_response(self, *args, **kwargs):
            return '{"memory":[{"text":"A generic fact.","attributed_to":null}]}'

    class FakeMemory:
        llm = FakeLlm()

    memory = FakeMemory()
    _attach_validating_retry(memory)
    assert memory.llm.generate_response(response_format={"type": "json_object"}).startswith("{")


def test_mem0_fact_extraction_timeout_is_bounded_and_validated():
    assert _fact_extraction_timeout({}) == 90.0
    assert _fact_extraction_timeout({"OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS": "12.5"}) == 12.5
    with pytest.raises(Mem0WrapperError, match="positive number"):
        _fact_extraction_timeout({"OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS": "not-a-number"})
    with pytest.raises(Mem0WrapperError, match="positive finite"):
        _fact_extraction_timeout({"OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS": "0"})


def test_mem0_fact_extraction_model_defaults_to_llama_and_allows_override():
    assert DEFAULT_FACT_EXTRACTION_MODEL == "llama3.1:8b"
    assert _fact_extraction_model({}) == "llama3.1:8b"
    assert _fact_extraction_model({"OLLAMA_FACT_EXTRACTION_MODEL": "qwen3:4b"}) == "qwen3:4b"
    assert _fact_extraction_model({"OLLAMA_FACT_EXTRACTION_MODEL": " "}) == "llama3.1:8b"


def test_compact_prompt_is_far_smaller_than_shipped_additive_prompt():
    import mem0.memory.main as mem0_main

    shipped_length = len(mem0_main.ADDITIVE_EXTRACTION_PROMPT)
    # The shipped prompt is the ~33.6k-character root cause of the 300s
    # extraction timeout; the replacement must be a real fix, not a token trim.
    assert shipped_length > 20_000
    assert len(COMPACT_ADDITIVE_EXTRACTION_PROMPT) < shipped_length / 5


def test_compact_prompt_documented_example_matches_the_wrapper_schema():
    # The prompt's own worked example must validate against the same
    # Pydantic model the wrapper uses to accept real Ollama responses,
    # otherwise the prompt would be teaching the model the wrong shape.
    example = '{"memory": [{"id": "0", "text": "User adopted a beagle named Max around March 8-9, 2025", "attributed_to": "user"}]}'
    assert example in COMPACT_ADDITIVE_EXTRACTION_PROMPT
    ExtractionResponse.model_validate_json(example)


def test_install_compact_extraction_prompt_patches_the_mem0_module_global():
    import mem0.memory.main as mem0_main

    original = mem0_main.ADDITIVE_EXTRACTION_PROMPT
    try:
        _install_compact_extraction_prompt()
        assert mem0_main.ADDITIVE_EXTRACTION_PROMPT == COMPACT_ADDITIVE_EXTRACTION_PROMPT
    finally:
        mem0_main.ADDITIVE_EXTRACTION_PROMPT = original


def test_mem0_recall_passes_user_id_through_filters_not_as_a_top_level_kwarg():
    # Installed mem0ai 2.0.19's Memory.search() raises ValueError if user_id is
    # passed as a top-level kwarg instead of inside filters={...}; a live smoke
    # test through open_local_mem0_memory().recall() hit exactly this.
    class FakeMemory:
        def __init__(self):
            self.calls = []

        def search(self, query, **kwargs):
            self.calls.append((query, kwargs))
            return {"results": []}

    fake_memory = FakeMemory()
    memory = Mem0Memory(fake_memory, vector_store=None)
    memory.recall("when does it open?", user_id="jarvis", limit=4)

    assert fake_memory.calls == [("when does it open?", {"filters": {"user_id": "jarvis"}, "top_k": 4})]


def test_install_compact_extraction_prompt_refuses_to_patch_a_drifted_shipped_prompt(monkeypatch):
    import mem0.memory.main as mem0_main

    monkeypatch.setattr(mem0_main, "ADDITIVE_EXTRACTION_PROMPT", "short prompt from a future mem0ai upgrade")
    with pytest.raises(Mem0WrapperError, match="unexpectedly short"):
        _install_compact_extraction_prompt()


def test_install_compact_extraction_prompt_is_idempotent_within_one_process():
    # A long-running caller (the executor) opens a fresh Memory per job, so
    # this runs many times against the same imported mem0.memory.main module.
    # Before the idempotency fix, the second call saw its own earlier patch
    # (short) and mistook it for shipped-prompt drift, raising on every job
    # after the first one in that process — exactly what a live executor run
    # hit: only the first message after each restart ever got a reply.
    import mem0.memory.main as mem0_main

    original = mem0_main.ADDITIVE_EXTRACTION_PROMPT
    try:
        _install_compact_extraction_prompt()
        _install_compact_extraction_prompt()
        assert mem0_main.ADDITIVE_EXTRACTION_PROMPT == COMPACT_ADDITIVE_EXTRACTION_PROMPT
    finally:
        mem0_main.ADDITIVE_EXTRACTION_PROMPT = original
