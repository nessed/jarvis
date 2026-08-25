"""Local-first persistent memory primitives for JARVIS."""

from .embeddings import EmbeddingError, EmbeddingProvider, OllamaEmbeddingConfig, OllamaEmbeddingProvider
from .mem0_wrapper import Mem0Memory, Mem0WrapperError, SQLiteVecMem0Store, open_mem0_memory
from .runtime import LocalMem0Runtime, LocalMemoryRuntime, open_local_mem0_memory, open_local_memory
from .service import MemoryService
from .store import SQLiteFactStore
from .types import Fact
from .vector_index import SQLiteVecIndex

__all__ = [
    "EmbeddingError",
    "EmbeddingProvider",
    "Fact",
    "LocalMemoryRuntime",
    "LocalMem0Runtime",
    "MemoryService",
    "Mem0Memory",
    "Mem0WrapperError",
    "OllamaEmbeddingConfig",
    "OllamaEmbeddingProvider",
    "SQLiteFactStore",
    "SQLiteVecMem0Store",
    "SQLiteVecIndex",
    "open_local_memory",
    "open_local_mem0_memory",
    "open_mem0_memory",
]
