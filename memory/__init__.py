"""Local-first persistent memory primitives for JARVIS."""

from .embeddings import EmbeddingError, EmbeddingProvider, OllamaEmbeddingConfig, OllamaEmbeddingProvider
from .runtime import LocalMemoryRuntime, open_local_memory
from .service import MemoryService
from .store import SQLiteFactStore
from .types import Fact
from .vector_index import SQLiteVecIndex

__all__ = [
    "EmbeddingError",
    "EmbeddingProvider",
    "Fact",
    "LocalMemoryRuntime",
    "MemoryService",
    "OllamaEmbeddingConfig",
    "OllamaEmbeddingProvider",
    "SQLiteFactStore",
    "SQLiteVecIndex",
    "open_local_memory",
]
