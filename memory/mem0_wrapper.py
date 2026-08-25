"""Mem0 self-host wrapper backed only by JARVIS's local SQLite memory stack.

Mem0's OSS factory does not publish a sqlite-vec provider.  This module
registers the authorized local provider at process startup; it delegates all
durable work to ``SQLiteFactStore`` and ``SQLiteVecIndex`` and never creates a
second vector backend.  Telemetry is disabled before *any* Mem0 import.
"""

from __future__ import annotations

import os
import math

# Mem0 reads this import-time flag from ``mem0.memory.telemetry``.
os.environ["MEM0_TELEMETRY"] = "False"

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MethodType
from typing import Any, Mapping, Sequence

import httpx
from pydantic import BaseModel, Field, ValidationError

try:
    from mem0.vector_stores.base import VectorStoreBase
except ImportError as exc:  # pragma: no cover - surfaced clearly in a dependency-missing deployment
    raise RuntimeError("mem0ai 2.0.19 is required for the SQLite vector provider.") from exc

from memory.embeddings import EmbeddingError, OllamaEmbeddingConfig, OllamaEmbeddingProvider, validate_ollama_loopback_url
from memory.store import SQLiteFactStore
from memory.vector_index import SQLiteVecIndex

DEFAULT_FACT_EXTRACTION_MODEL = "llama3.1:8b"

# ``mem0.memory.main.Memory.add`` hardcodes its extraction system prompt as a
# bare module-global reference (``ADDITIVE_EXTRACTION_PROMPT``), read fresh on
# every call rather than bound at class-definition time. The shipped prompt is
# 33,661 characters (~8k tokens) of prompt-eval cost per extraction, which is
# the entire cause of local Ollama extraction timing out at 300s regardless of
# model. Neither ``MemoryConfig`` nor ``Memory.add()`` exposes a supported way
# to select a shorter prompt for this pipeline: ``mem0.memory.utils`` still
# ships ``get_fact_retrieval_messages``/``get_fact_retrieval_messages_legacy``
# and their matching ``USER_MEMORY_EXTRACTION_PROMPT``/``FACT_RETRIEVAL_PROMPT``
# constants, but as of mem0ai 2.0.19 no code path in ``mem0/memory/main.py``
# calls them; they are dead code left over from an earlier extraction design.
# Subclassing ``Memory`` cannot narrowly override just the prompt either: the
# assignment lives as a local variable inside one ~250-line method
# (the "V3 phased batch pipeline"), so overriding it would mean duplicating
# that entire method rather than the existing store/index/embedding layers.
# Reassigning the module global below is the narrowest fix that changes only
# the prompt text, touches no file under site-packages, and needs no
# subclassing of ``Memory`` or its LLM adapter. It must keep the exact same
# output contract Mem0's own additive pipeline and ``ExtractionResponse``
# below expect: a top-level "memory" key holding a list of
# ``{"id", "text", "attributed_to", "linked_memory_ids"}`` objects — not the
# unrelated ``{"facts": [...]}`` shape the dead-code prompts above produce.
COMPACT_ADDITIVE_EXTRACTION_PROMPT = """You are a Memory Extractor. Read the conversation input below and extract every distinct, memorable fact, preference, plan, or event as a separate self-contained statement.

The input has these sections: Summary (prior profile, may be empty), Last k Messages (recent context for resolving pronouns), Recently Extracted Memories and Existing Memories (already captured — do NOT re-extract these; use them only to avoid duplicates and to fill in "linked_memory_ids" when a new fact is about the same person/topic/event), New Messages (the ONLY source of new extractions), Observation Date (the only anchor for resolving "yesterday", "next week", etc.), Current Date (do not use this to resolve relative time), and an optional Custom Instructions section (apply these first, above all other rules).

Extract from both "user" and "assistant" messages: personal facts, preferences, plans, relationships, professional/health details, and opinions. For assistant messages, extract only genuinely new recommendations, plans, or researched information — skip anything that just echoes what the user already said.

Rules:
- Each memory must be self-contained (replace pronouns with names), 15-80 words, one topic per memory.
- Preserve exact names, titles, numbers, and dates; never generalize a specific detail into a vague one.
- Ground relative time expressions against Observation Date, not Current Date.
- Skip greetings, filler, and anything already present in Recently Extracted Memories or Existing Memories with no new context.
- If a new memory relates to an existing one (same entity, updated preference, follow-up event, or contradiction), add that existing memory's id to "linked_memory_ids".
- If nothing is worth extracting, return {"memory": []}.

Example:
New Messages: [{"role": "user", "content": "I adopted a beagle named Max last weekend."}]
Observation Date: 2025-03-10
Output: {"memory": [{"id": "0", "text": "User adopted a beagle named Max around March 8-9, 2025", "attributed_to": "user"}]}

Return ONLY valid JSON parsable by json.loads(), no other text, reasoning, or wrappers, in exactly this structure:
{"memory": [{"id": "0", "text": "...", "attributed_to": "user", "linked_memory_ids": ["existing-id"]}]}
"id" is a sequential string starting at "0". "text" and "attributed_to" ("user" or "assistant") are required. "linked_memory_ids" is optional; omit it or pass [] when nothing relevant exists.
"""

# Sanity floor for the shipped prompt this module patches. If a future mem0ai
# upgrade shrinks or removes ``ADDITIVE_EXTRACTION_PROMPT`` (e.g. because the
# upstream fix landed), this guards against silently patching a prompt that
# was already changed out from under this pin.
_SHIPPED_PROMPT_MINIMUM_LENGTH = 20_000


class Mem0WrapperError(RuntimeError):
    """Raised when local-only Mem0 initialization or output validation fails."""


class ExtractedFact(BaseModel):
    """The minimum durable fact shape accepted from Mem0's JSON extraction."""

    text: str = Field(min_length=1)
    attributed_to: str | None = None


class ExtractionResponse(BaseModel):
    memory: list[ExtractedFact] = Field(default_factory=list)


@dataclass(frozen=True)
class VectorRecord:
    """Mem0-compatible result row (id, higher-is-better score, payload)."""

    id: str
    score: float
    payload: dict[str, Any]


@dataclass(frozen=True)
class CollectionInfo:
    name: str
    vectors_count: int
    vector_size: int


class SQLiteVecMem0Store(VectorStoreBase):
    """Mem0's ``VectorStoreBase`` implemented through the existing SQLite stores."""

    def __init__(
        self,
        collection_name: str,
        embedding_model_dims: int,
        database_path: str,
        embedding_model: str,
        **_: Any,
    ) -> None:
        self.collection_name = _required_text("collection_name", collection_name)
        self.embedding_model_dims = _positive_int("embedding_model_dims", embedding_model_dims)
        self.embedding_model = _required_text("embedding_model", embedding_model)
        self.store = SQLiteFactStore(database_path)
        self.index = SQLiteVecIndex(
            database_path,
            dimensions=self.embedding_model_dims,
            embedding_model=self.embedding_model,
        )
        self.store.initialize()
        self.index.initialize()

    def create_col(self, name: str, vector_size: int, distance: Any = None) -> None:
        if _required_text("collection_name", name) != self.collection_name:
            raise Mem0WrapperError("sqlite-vec provider supports only its configured local collection")
        if _positive_int("vector_size", vector_size) != self.embedding_model_dims:
            raise Mem0WrapperError("sqlite-vec collection dimension does not match the configured embedding model")

    def insert(self, vectors: list, payloads: list | None = None, ids: list | None = None) -> None:
        if ids is None or payloads is None or len(vectors) != len(ids) or len(ids) != len(payloads):
            raise ValueError("vectors, ids, and payloads must be equally sized lists")
        created: list[str] = []
        try:
            for vector, vector_id, payload in zip(vectors, ids, payloads):
                identifier = _required_text("vector_id", str(vector_id))
                normalized_payload = _payload(payload)
                text = _required_text("payload.data", normalized_payload.get("data", ""))
                metadata = dict(normalized_payload)
                metadata["_mem0_collection"] = self.collection_name
                source = str(metadata.get("source") or "mem0")
                self.store.remember(
                    text,
                    source,
                    fact_id=identifier,
                    metadata=metadata,
                    created_at=_payload_timestamp(metadata),
                    embedding_model=self.embedding_model,
                )
                created.append(identifier)
                self.index.upsert(identifier, vector)
        except Exception:
            for identifier in created:
                self.index.delete(identifier)
                self.store.delete(identifier)
            raise

    def search(self, query: str, vectors: list, top_k: int = 5, filters: dict | None = None) -> list[VectorRecord]:
        if top_k <= 0:
            return []
        # Over-fetch because entity collections share sqlite-vec but are segregated
        # by local metadata; no remote/vector backend is involved.
        candidates = self.index.search(vectors, limit=max(top_k, len(self.store.list_facts())))
        rows: list[VectorRecord] = []
        for fact_id, distance in candidates:
            fact = self.store.get(fact_id)
            if fact is None or fact.metadata.get("_mem0_collection") != self.collection_name:
                continue
            if not _matches_filters(fact.metadata, filters):
                continue
            rows.append(VectorRecord(id=fact.id, score=1.0 / (1.0 + distance), payload=dict(fact.metadata)))
            if len(rows) == top_k:
                break
        return rows

    def delete(self, vector_id: str) -> None:
        self.index.delete(str(vector_id))
        self.store.delete(str(vector_id))

    def update(self, vector_id: str, vector: list | None = None, payload: dict | None = None) -> None:
        existing = self.store.get(str(vector_id))
        if existing is None or existing.metadata.get("_mem0_collection") != self.collection_name:
            raise KeyError(f"vector does not exist: {vector_id}")
        next_payload = dict(existing.metadata) if payload is None else _payload(payload)
        next_payload["_mem0_collection"] = self.collection_name
        self.store.update(
            str(vector_id),
            text=_required_text("payload.data", next_payload.get("data", "")),
            source=str(next_payload.get("source") or existing.source),
            metadata=next_payload,
            embedding_model=self.embedding_model,
        )
        if vector is not None:
            self.index.upsert(str(vector_id), vector)

    def get(self, vector_id: str) -> VectorRecord | None:
        fact = self.store.get(str(vector_id))
        if fact is None or fact.metadata.get("_mem0_collection") != self.collection_name:
            return None
        return VectorRecord(id=fact.id, score=1.0, payload=dict(fact.metadata))

    def list_cols(self) -> list[CollectionInfo]:
        return [self.col_info()]

    def delete_col(self) -> None:
        for fact in self.store.list_facts():
            if fact.metadata.get("_mem0_collection") == self.collection_name:
                self.index.delete(fact.id)
                self.store.delete(fact.id)

    def col_info(self) -> CollectionInfo:
        count = sum(1 for fact in self.store.list_facts() if fact.metadata.get("_mem0_collection") == self.collection_name)
        return CollectionInfo(self.collection_name, count, self.embedding_model_dims)

    def list(self, filters: dict | None = None, top_k: int | None = None) -> list[VectorRecord]:
        limit = None if top_k is None else _positive_or_zero("top_k", top_k)
        rows: list[VectorRecord] = []
        for fact in self.store.list_facts():
            if fact.metadata.get("_mem0_collection") != self.collection_name or not _matches_filters(fact.metadata, filters):
                continue
            rows.append(VectorRecord(fact.id, 1.0, dict(fact.metadata)))
            if limit is not None and len(rows) == limit:
                break
        return rows

    def reset(self) -> None:
        self.delete_col()

    def close(self) -> None:
        self.index.close()
        self.store.close()


class LocalMem0Embedding:
    """Mem0 embedding-factory bridge that delegates to JARVIS's loopback guard."""

    def __init__(self, config: Any) -> None:
        self.config = config
        model = _required_text("embedding model", config.model)
        base_url = config.ollama_base_url or OllamaEmbeddingConfig.base_url
        validate_ollama_loopback_url(base_url)
        self._provider = OllamaEmbeddingProvider(OllamaEmbeddingConfig(model=model, base_url=base_url))

    def embed(self, text: str, memory_action: str | None = None) -> list[float]:
        return self._provider.embed_one(text)

    def embed_batch(self, texts: Sequence[str], memory_action: str = "add") -> list[list[float]]:
        return self._provider.embed(texts)


class Mem0Memory:
    """Small bus-facing API over Mem0's self-hosted extraction/reconciliation engine."""

    def __init__(self, memory: Any, vector_store: SQLiteVecMem0Store) -> None:
        self._memory = memory
        self._vector_store = vector_store

    def remember(self, text: str, *, user_id: str = "jarvis", metadata: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        return self._memory.add(text, user_id=user_id, metadata=dict(metadata or {}))

    def recall(self, query: str, *, user_id: str = "jarvis", limit: int = 10) -> list[dict[str, Any]]:
        # Installed mem0ai 2.0.19's Memory.search() rejects user_id/agent_id/run_id
        # as top-level kwargs (ValueError: "Use filters={'user_id': ...} instead")
        # and calls the result-count parameter ``top_k``, not ``limit``.
        return self._memory.search(query, filters={"user_id": user_id}, top_k=limit)

    def close(self) -> None:
        self._vector_store.close()


def open_mem0_memory(database_path: str | Path, *, environ: Mapping[str, str] | None = None) -> Mem0Memory:
    """Create local-only Mem0, failing closed before any Ollama request is possible."""
    settings = os.environ if environ is None else environ
    embedding_config = OllamaEmbeddingConfig.from_environ(settings)
    fact_model = _fact_extraction_model(settings)
    base_url = settings.get("OLLAMA_BASE_URL", OllamaEmbeddingConfig.base_url).strip() or OllamaEmbeddingConfig.base_url
    validate_ollama_loopback_url(base_url)
    extraction_timeout = _fact_extraction_timeout(settings)

    # Probe the existing guarded client first so missing local Ollama/models fail
    # before Mem0 can make an extraction call.
    dimensions = len(OllamaEmbeddingProvider(embedding_config).embed_one("jarvis local memory vector dimension probe"))
    Memory, MemoryConfig, VectorStoreConfig, EmbedderConfig, LlmConfig, VectorStoreFactory, EmbedderFactory = _mem0_api()
    _register_mem0_factories(VectorStoreFactory, EmbedderFactory)
    vector_config = _LocalVectorConfig(
        collection_name="jarvis_memories",
        embedding_model_dims=dimensions,
        database_path=str(database_path),
        embedding_model=embedding_config.model,
    )
    # ``MemoryConfig`` re-validates nested models and rejects third-party
    # vector providers even after a valid local config object is supplied.
    # Constructing this outer model preserves Mem0's supported public runtime
    # path while allowing the authorized registered provider below.
    config = MemoryConfig.model_construct(
        vector_store=VectorStoreConfig.model_construct(provider="sqlite_vec", config=vector_config),
        embedder=EmbedderConfig.model_construct(
            provider="jarvis_local", config={"model": embedding_config.model, "ollama_base_url": base_url}
        ),
        llm=LlmConfig(
            provider="ollama",
            # ``max_tokens`` maps to Ollama's ``num_predict``. The extraction
            # output is one small JSON object; 128 tokens is ample and bounds
            # generation instead of leaving it at the config default of 2000.
            config={"model": fact_model, "ollama_base_url": base_url, "temperature": 0, "max_tokens": 128},
        ),
        history_db_path=str(Path(database_path).with_suffix(".mem0-history.db")),
    )
    memory = Memory(config=config)
    _set_local_extraction_timeout(memory.llm, base_url, extraction_timeout)
    _attach_validating_retry(memory)
    return Mem0Memory(memory, memory.vector_store)


class _LocalVectorConfig(BaseModel):
    collection_name: str
    embedding_model_dims: int
    database_path: str
    embedding_model: str


def _attach_validating_retry(memory: Any) -> None:
    original = memory.llm.generate_response

    def generate_response_with_validation(this: Any, *args: Any, **kwargs: Any) -> Any:
        response_format = kwargs.get("response_format")
        for attempt in range(2):
            try:
                response = original(*args, **kwargs)
            except httpx.TimeoutException as exc:
                raise Mem0WrapperError(
                    "Local Ollama fact extraction timed out. Confirm the configured local model can complete extraction."
                ) from exc
            except httpx.NetworkError as exc:
                raise Mem0WrapperError(
                    "Local Ollama fact extraction is unavailable. Start Ollama and confirm its loopback server is reachable."
                ) from exc
            if response_format and response_format.get("type") == "json_object":
                try:
                    ExtractionResponse.model_validate_json(response)
                except ValidationError as exc:
                    if attempt == 0:
                        continue
                    raise Mem0WrapperError("Local Ollama returned invalid Mem0 fact JSON after one retry.") from exc
            return response
        raise AssertionError("unreachable")

    memory.llm.generate_response = MethodType(generate_response_with_validation, memory.llm)


def _fact_extraction_timeout(settings: Mapping[str, str]) -> float:
    raw = settings.get("OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS", "30").strip()
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise Mem0WrapperError("OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS must be a positive number.") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise Mem0WrapperError("OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS must be a positive finite number.")
    return timeout


def _fact_extraction_model(settings: Mapping[str, str]) -> str:
    """Return the local extraction model, preserving an explicit environment override."""
    return settings.get("OLLAMA_FACT_EXTRACTION_MODEL", DEFAULT_FACT_EXTRACTION_MODEL).strip() or DEFAULT_FACT_EXTRACTION_MODEL


def _set_local_extraction_timeout(llm: Any, base_url: str, timeout_seconds: float) -> None:
    """Bound the shipped adapter's local client without replacing that adapter."""
    try:
        from ollama import Client
    except ImportError as exc:  # pragma: no cover - surfaced by the pinned dependency message elsewhere
        raise Mem0WrapperError("The pinned Ollama client is required for local Mem0 fact extraction.") from exc
    llm.client = Client(host=base_url, timeout=timeout_seconds)


def _mem0_api() -> tuple[Any, ...]:
    try:
        from mem0.configs.base import MemoryConfig
        from mem0.embeddings.configs import EmbedderConfig
        from mem0.llms.configs import LlmConfig
        from mem0.memory.main import Memory
        from mem0.utils.factory import EmbedderFactory, VectorStoreFactory
        from mem0.vector_stores.configs import VectorStoreConfig
    except ImportError as exc:
        raise Mem0WrapperError("mem0ai 2.0.19 is required for local memory; install pinned project dependencies.") from exc
    _install_compact_extraction_prompt()
    return Memory, MemoryConfig, VectorStoreConfig, EmbedderConfig, LlmConfig, VectorStoreFactory, EmbedderFactory


def _install_compact_extraction_prompt() -> None:
    """Replace Mem0's ~33.6k-character extraction system prompt at runtime.

    ``mem0.memory.main.Memory.add`` (and ``AsyncMemory.add``) read the module
    global ``ADDITIVE_EXTRACTION_PROMPT`` fresh on every call, so reassigning
    it here — before any extraction call happens — changes what every later
    ``add()`` call sends, without editing any file under site-packages and
    without subclassing or reimplementing Mem0's ~250-line batch pipeline.
    """
    import mem0.memory.main as mem0_main

    shipped_prompt = getattr(mem0_main, "ADDITIVE_EXTRACTION_PROMPT", None)
    if not isinstance(shipped_prompt, str) or len(shipped_prompt) < _SHIPPED_PROMPT_MINIMUM_LENGTH:
        raise Mem0WrapperError(
            "mem0.memory.main.ADDITIVE_EXTRACTION_PROMPT is missing or unexpectedly short; "
            "the pinned mem0ai version's extraction prompt may have changed. Re-verify before patching it."
        )
    mem0_main.ADDITIVE_EXTRACTION_PROMPT = COMPACT_ADDITIVE_EXTRACTION_PROMPT


def _register_mem0_factories(vector_factory: Any, embedder_factory: Any) -> None:
    vector_factory.provider_to_class["sqlite_vec"] = "memory.mem0_wrapper.SQLiteVecMem0Store"
    embedder_factory.provider_to_class["jarvis_local"] = "memory.mem0_wrapper.LocalMem0Embedding"


def _payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("payload must be a dictionary")
    return dict(value)


def _payload_timestamp(payload: Mapping[str, Any]) -> datetime | None:
    value = payload.get("created_at")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _matches_filters(payload: Mapping[str, Any], filters: Mapping[str, Any] | None) -> bool:
    if not filters:
        return True
    for key, wanted in filters.items():
        actual = payload.get(key)
        if isinstance(wanted, dict):
            if "in" in wanted and actual not in wanted["in"]:
                return False
            elif "eq" in wanted and actual != wanted["eq"]:
                return False
            elif not any(operator in wanted for operator in ("in", "eq")):
                return False
        elif actual != wanted and wanted != "*":
            return False
    return True


def _required_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_or_zero(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value
