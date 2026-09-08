"""Explicit startup for the local-only semantic-memory stack."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import threading

from dotenv import load_dotenv

from memory.embeddings import OllamaEmbeddingConfig, OllamaEmbeddingProvider
from memory.service import MemoryService
from memory.store import SQLiteFactStore
from memory.vector_index import SQLiteVecIndex
from memory.mem0_wrapper import Mem0Memory, open_mem0_memory


DIMENSION_PROBE = "jarvis local memory vector dimension probe"

#: Embedding dimension per (model, base_url), for the life of the process.
#:
#: The probe is one Ollama embed call, and it was being paid on **every
#: message**: the WhatsApp handler opens a conversation memory per job.
#: Measured on this laptop, 9 Sep 2026: the probe is 463-674 ms and opening
#: both sqlite handles is 7 ms, against a real 286-fact store. So essentially
#: the whole cost of opening the runtime is this one call, and it asks the
#: same constant string the same model the same question every time.
#:
#: Keyed on model *and* base URL, so pointing at a different model or a
#: different Ollama invalidates it rather than inheriting a stale dimension --
#: which is the drift this cache must not cause.
#:
#: What is deliberately *not* cached: the sqlite handles. Every job runs on a
#: fresh thread (``executor/poller.py:_run_with_timeout``) and both stores open
#: with sqlite3's default ``check_same_thread=True``, so a shared connection
#: would need that flag flipped plus a lock in two modules, in the path of the
#: poller's known abandoned-thread bug -- risk bought for 7 ms.
#: ``docs/consults/2026-09-09-jarvis-board-task-hotpath-quick-wins``.
#:
#: The consequence worth naming: the probe no longer re-proves Ollama is alive
#: before the databases open. Nothing is lost by that. The first real embed
#: still fails closed with the same ``EmbeddingError``, and
#: ``SQLiteVecIndex.initialize`` still verifies the stored dimension and model
#: on every single open -- so the drift check runs *more* often than the task
#: asked, not less.
_DIMENSIONS: dict[tuple[str, str], int] = {}
_DIMENSIONS_LOCK = threading.Lock()


def probed_dimensions(embeddings: OllamaEmbeddingProvider, base_url: str) -> int:
    """The embedding width for this model, asked of Ollama once per process."""
    key = (embeddings.model, base_url)
    with _DIMENSIONS_LOCK:
        cached = _DIMENSIONS.get(key)
    if cached is not None:
        return cached
    # Probed outside the lock: it is a network call, and two threads racing to
    # ask the same model the same constant question is far cheaper than either
    # of them holding a lock across it. They agree on the answer by
    # construction -- it is the same model.
    dimensions = len(embeddings.embed_one(DIMENSION_PROBE))
    with _DIMENSIONS_LOCK:
        _DIMENSIONS[key] = dimensions
    return dimensions


def forget_probed_dimensions() -> None:
    """Drop the cache. A test seam, and the way a changed model is re-probed."""
    with _DIMENSIONS_LOCK:
        _DIMENSIONS.clear()


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
    config = OllamaEmbeddingConfig.from_environ(settings)
    embeddings = OllamaEmbeddingProvider(config)
    dimensions = probed_dimensions(embeddings, config.base_url)

    # Do not create either database handle until the fixed, non-personal probe
    # has established the width the sqlite-vec schema must have. On the first
    # open in a process that probe is also a liveness check on the configured
    # local model; on later opens the cached width stands and liveness is
    # proved by the first real embed instead, which fails closed identically.
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
