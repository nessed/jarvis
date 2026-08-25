import pytest

import memory.runtime as runtime
from memory.embeddings import EmbeddingError


class FakeEmbeddings:
    calls: list[str] = []

    def __init__(self, config):
        self.config = config
        self.model = config.model

    def embed_one(self, text):
        type(self).calls.append(text)
        return [0.25, 0.75, 1.0]

    def embed(self, texts):
        return [[0.25, 0.75, 1.0] for _ in texts]


class FakeStore:
    instances: list["FakeStore"] = []

    def __init__(self, path):
        self.path = path
        self.initialized = False
        self.closed = False
        type(self).instances.append(self)

    def initialize(self):
        self.initialized = True

    def close(self):
        self.closed = True


class FakeIndex:
    instances: list["FakeIndex"] = []

    def __init__(self, path, *, dimensions, embedding_model=None):
        self.path = path
        self.dimensions = dimensions
        self.embedding_model = embedding_model
        self.initialized = False
        self.closed = False
        type(self).instances.append(self)

    def initialize(self):
        self.initialized = True

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def reset_fakes():
    FakeEmbeddings.calls = []
    FakeStore.instances = []
    FakeIndex.instances = []


def _patch_runtime(monkeypatch, *, provider=FakeEmbeddings, store=FakeStore, index=FakeIndex):
    monkeypatch.setattr(runtime, "OllamaEmbeddingProvider", provider)
    monkeypatch.setattr(runtime, "SQLiteFactStore", store)
    monkeypatch.setattr(runtime, "SQLiteVecIndex", index)


def test_open_local_memory_probes_fixed_text_before_creating_local_stores(monkeypatch, tmp_path):
    _patch_runtime(monkeypatch)
    settings = {
        "OLLAMA_EMBEDDING_MODEL": "user-selected-local-model",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
    }

    opened = runtime.open_local_memory(tmp_path / "facts.db", environ=settings)

    assert FakeEmbeddings.calls == [runtime.DIMENSION_PROBE]
    assert FakeStore.instances[0].initialized is True
    assert FakeIndex.instances[0].dimensions == 3
    assert FakeIndex.instances[0].embedding_model == "user-selected-local-model"
    assert opened.store is FakeStore.instances[0]
    assert opened.index is FakeIndex.instances[0]
    opened.close()
    assert FakeStore.instances[0].closed is True
    assert FakeIndex.instances[0].closed is True


def test_unusable_embedding_prevents_any_store_construction(monkeypatch, tmp_path):
    class UnavailableEmbeddings(FakeEmbeddings):
        def embed_one(self, text):
            raise EmbeddingError("Ollama is unavailable")

    _patch_runtime(monkeypatch, provider=UnavailableEmbeddings)

    with pytest.raises(EmbeddingError, match="unavailable"):
        runtime.open_local_memory(tmp_path / "facts.db", environ={"OLLAMA_EMBEDDING_MODEL": "local"})

    assert FakeStore.instances == []
    assert FakeIndex.instances == []


def test_invalid_explicit_config_prevents_any_store_construction(monkeypatch, tmp_path):
    _patch_runtime(monkeypatch)

    with pytest.raises(EmbeddingError, match="OLLAMA_EMBEDDING_MODEL"):
        runtime.open_local_memory(tmp_path / "facts.db", environ={})

    assert FakeStore.instances == []
    assert FakeIndex.instances == []


def test_partial_index_initialization_failure_closes_both_resources(monkeypatch, tmp_path):
    class FailingIndex(FakeIndex):
        def initialize(self):
            self.initialized = True
            raise RuntimeError("sqlite-vec unavailable")

    _patch_runtime(monkeypatch, index=FailingIndex)

    with pytest.raises(RuntimeError, match="sqlite-vec unavailable"):
        runtime.open_local_memory(tmp_path / "facts.db", environ={"OLLAMA_EMBEDDING_MODEL": "local"})

    assert FakeStore.instances[0].initialized is True
    assert FakeStore.instances[0].closed is True
    assert FakeIndex.instances[0].closed is True
