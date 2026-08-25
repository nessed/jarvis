"""Explicit startup for the local-only semantic-memory stack."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

from memory.embeddings import OllamaEmbeddingConfig, OllamaEmbeddingProvider
from memory.service import MemoryService
from memory.store import SQLiteFactStore
from memory.vector_index import SQLiteVecIndex
from memory.mem0_wrapper import Mem0Memory, open_mem0_memory


DIMENSION_PROBE = "jarvis local memory vector dimension probe"


@dataclass
class LocalMemoryRuntime:
    """Own the local database handles backing a ready memory service."""

    service: MemoryService
    store: SQLiteFactStore
    index: SQLiteVecIndex

    def close(self) -> None:
        _close_resources(self.index, self.store)

    def __enter__(self) -> "LocalMemoryRuntime":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


@dataclass
class LocalMem0Runtime:
    """Bus-facing Mem0 runtime, backed exclusively by the local SQLite stack."""

    memory: Mem0Memory

    def remember(self, text: str, **kwargs: object) -> list[dict[str, object]]:
        return self.memory.remember(text, **kwargs)  # type: ignore[arg-type]

    def recall(self, query: str, **kwargs: object) -> list[dict[str, object]]:
        return self.memory.recall(query, **kwargs)  # type: ignore[arg-type]

    def close(self) -> None:
        self.memory.close()

    def __enter__(self) -> "LocalMem0Runtime":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def open_local_memory(
    database_path: str | Path | None = None,
    *,
    environ: dict[str, str] | None = None,
) -> LocalMemoryRuntime:
    """Open semantic memory only after a local Ollama model proves usable.

    The dimension probe is constant, not user content. It establishes the
    sqlite-vec schema dimension without sending any personal data off-device.
    """
    if environ is None:
        load_dotenv()
    settings = os.environ if environ is None else environ
    path = Path(database_path or settings.get("MEMORY_DB_PATH", "memory.db"))
    embeddings = OllamaEmbeddingProvider(OllamaEmbeddingConfig.from_environ(settings))
    dimensions = len(embeddings.embed_one(DIMENSION_PROBE))

    # Do not create either database handle until the fixed, non-personal probe
    # proves that the explicitly configured local model is usable.
    store = SQLiteFactStore(path)
    index = SQLiteVecIndex(path, dimensions=dimensions, embedding_model=embeddings.model)
    try:
        store.initialize()
        index.initialize()
        service = MemoryService(store=store, embeddings=embeddings, index=index)
    except Exception:
        _close_resources(index, store)
        raise
    return LocalMemoryRuntime(
        service=service,
        store=store,
        index=index,
    )


def open_local_mem0_memory(
    database_path: str | Path | None = None,
    *,
    environ: dict[str, str] | None = None,
) -> LocalMem0Runtime:
    """Open the specified Mem0 memory surface for bus ``remember``/``recall`` calls."""
    if environ is None:
        load_dotenv()
    settings = os.environ if environ is None else environ
    path = Path(database_path or settings.get("MEMORY_DB_PATH", "memory.db"))
    return LocalMem0Runtime(memory=open_mem0_memory(path, environ=settings))


def _close_resources(*resources: object) -> None:
    """Best-effort reverse-order cleanup without hiding startup failures."""
    for resource in resources:
        try:
            resource.close()  # type: ignore[attr-defined]
        except Exception:
            pass
