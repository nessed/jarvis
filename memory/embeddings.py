"""Local embedding providers used by the personal-memory subsystem.

This module deliberately talks only to a loopback Ollama endpoint.  It has no
provider keys and should never send personal-memory text to a hosted service.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence
from urllib.parse import urlparse

import httpx


class EmbeddingError(RuntimeError):
    """Raised when a local embedding request cannot produce usable vectors.

    ``cause`` is a short discriminator drawn from ``EMBEDDING_FAILURE_CAUSES``
    below.  It exists because the *type* name alone is not a diagnosis: on
    29-30 August 2026 the live queue collected 84 dead-lettered
    ``distill_memory`` rows whose checkpoint read
    ``executor handler failed (EmbeddingError)`` and nothing else, hiding a
    timeout, an unreachable Ollama and a missing model behind one string.
    ``executor/poller.py`` appends this slug to the checkpoint message.

    It is a **fixed vocabulary with no interpolated content** (the one
    exception, an HTTP status code, is a number).  That is load-bearing: the
    checkpoint is written to the hosted jobs table, while the human-readable
    message it accompanies is built from local text that must never leave the
    device.  Never widen this to carry model output, a prompt, or a URL.
    """

    def __init__(self, message: str, *, cause: str = "unknown") -> None:
        super().__init__(message)
        self.cause = cause


# Every ``cause`` this module can raise, as documentation and as the set a
# reader can grep for when a checkpoint names one.
EMBEDDING_FAILURE_CAUSES: frozenset[str] = frozenset(
    {
        "not_configured",  # OLLAMA_EMBEDDING_MODEL missing or blank
        "bad_timeout",  # OLLAMA_EMBEDDING_TIMEOUT_SECONDS unusable
        "invalid_url",  # OLLAMA_BASE_URL is not an HTTP URL
        "non_loopback_url",  # OLLAMA_BASE_URL points off-device
        "invalid_input",  # caller passed no texts, or a blank one
        "timeout",  # Ollama did not answer within the budget
        "unavailable",  # nothing is listening on the loopback port
        "transport",  # some other httpx transport failure
        "invalid_json",  # answer body was not JSON
        "malformed_response",  # JSON, but not the documented shape
        "vector_count_mismatch",  # wrong number of vectors came back
        "empty_vector",  # a vector was empty or not a list
        "non_numeric_value",  # a vector held something that is not a number
        "non_finite_value",  # a vector held NaN or an infinity
        "dimension_mismatch",  # vectors in one batch disagreed on length
        "unknown",  # default; should not appear in practice
    }
)
# ``http_<status>`` is also emitted, for any non-2xx answer.  404 in particular
# means the configured model is not pulled, which is the failure most often
# mistaken for "Ollama is down".


class EmbeddingProvider(Protocol):
    """Minimal interface shared by local embedding implementations."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one finite numeric vector for every input text."""


@dataclass(frozen=True)
class OllamaEmbeddingConfig:
    """Explicit local configuration for an Ollama embedding model."""

    model: str
    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: float = 15.0

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "OllamaEmbeddingConfig":
        settings = os.environ if environ is None else environ
        model = settings.get("OLLAMA_EMBEDDING_MODEL", "").strip()
        if not model:
            raise EmbeddingError(
                "Local embeddings are not configured: set OLLAMA_EMBEDDING_MODEL to the local Ollama model you pulled.",
                cause="not_configured",
            )
        base_url = settings.get("OLLAMA_BASE_URL", cls.base_url).strip() or cls.base_url
        timeout_raw = settings.get("OLLAMA_EMBEDDING_TIMEOUT_SECONDS", str(cls.timeout_seconds)).strip()
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as exc:
            raise EmbeddingError(
                "OLLAMA_EMBEDDING_TIMEOUT_SECONDS must be a positive number.",
                cause="bad_timeout",
            ) from exc
        return cls(model=model, base_url=base_url, timeout_seconds=timeout_seconds)

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise EmbeddingError(
                "An explicit local Ollama embedding model is required.",
                cause="not_configured",
            )
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise EmbeddingError(
                "Ollama embedding timeout must be a positive finite number.",
                cause="bad_timeout",
            )

        validate_ollama_loopback_url(self.base_url)


def validate_ollama_loopback_url(base_url: str) -> None:
    """Reject every non-loopback Ollama endpoint before memory text can leave disk."""
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise EmbeddingError("OLLAMA_BASE_URL must be a valid local HTTP URL.", cause="invalid_url")
    if parsed.hostname.lower() not in {"localhost", "127.0.0.1", "::1"}:
        raise EmbeddingError(
            "Ollama embeddings must use a loopback URL so memory text stays local.",
            cause="non_loopback_url",
        )


class OllamaEmbeddingProvider:
    """Synchronous adapter for Ollama's local ``POST /api/embed`` endpoint."""

    def __init__(self, config: OllamaEmbeddingConfig, *, transport: httpx.BaseTransport | None = None) -> None:
        self._config = config
        self._transport = transport

    @property
    def model(self) -> str:
        return self._config.model

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        normalized_texts = _validate_texts(texts)
        try:
            with httpx.Client(
                base_url=self._config.base_url.rstrip("/"),
                timeout=httpx.Timeout(self._config.timeout_seconds),
                transport=self._transport,
            ) as client:
                response = client.post("/api/embed", json={"model": self._config.model, "input": normalized_texts})
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise EmbeddingError(
                "Local Ollama embedding request timed out. Confirm Ollama is running and the configured model is available.",
                cause="timeout",
            ) from exc
        except httpx.ConnectError as exc:
            raise EmbeddingError(
                "Local Ollama is unavailable. Start Ollama and make sure its loopback server is reachable.",
                cause="unavailable",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise EmbeddingError(
                f"Local Ollama embedding request failed with HTTP {exc.response.status_code}. "
                "Confirm the configured model is installed locally.",
                cause=f"http_{exc.response.status_code}",
            ) from exc
        except httpx.HTTPError as exc:
            raise EmbeddingError(
                "Local Ollama embedding request failed. Confirm Ollama is running locally.",
                cause="transport",
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise EmbeddingError("Local Ollama returned invalid embedding JSON.", cause="invalid_json") from exc
        return _parse_vectors(payload, expected_count=len(normalized_texts))


def _validate_texts(texts: Sequence[str]) -> list[str]:
    if not texts:
        raise EmbeddingError("At least one text is required for local embedding.", cause="invalid_input")
    normalized: list[str] = []
    for text in texts:
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingError(
                "Embedding input must contain only non-empty text strings.", cause="invalid_input"
            )
        normalized.append(text)
    return normalized


def _parse_vectors(payload: object, *, expected_count: int) -> list[list[float]]:
    if not isinstance(payload, dict):
        raise EmbeddingError("Local Ollama returned an invalid embedding response.", cause="malformed_response")
    vectors = payload.get("embeddings")
    # Older local Ollama releases returned a singular key for a singular input.
    if vectors is None and expected_count == 1 and "embedding" in payload:
        vectors = [payload["embedding"]]
    if not isinstance(vectors, list) or len(vectors) != expected_count:
        raise EmbeddingError(
            "Local Ollama returned an unexpected number of embedding vectors.",
            cause="vector_count_mismatch",
        )

    normalized: list[list[float]] = []
    dimensions: int | None = None
    for vector in vectors:
        if not isinstance(vector, list) or not vector:
            raise EmbeddingError(
                "Local Ollama returned an empty or invalid embedding vector.", cause="empty_vector"
            )
        converted: list[float] = []
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EmbeddingError(
                    "Local Ollama returned a non-numeric embedding value.", cause="non_numeric_value"
                )
            number = float(value)
            if not math.isfinite(number):
                raise EmbeddingError(
                    "Local Ollama returned a non-finite embedding value.", cause="non_finite_value"
                )
            converted.append(number)
        if dimensions is None:
            dimensions = len(converted)
        elif len(converted) != dimensions:
            raise EmbeddingError(
                "Local Ollama returned embedding vectors with inconsistent dimensions.",
                cause="dimension_mismatch",
            )
        normalized.append(converted)
    return normalized
