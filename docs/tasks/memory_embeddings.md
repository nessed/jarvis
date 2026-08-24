# Phase 1 lane: local embeddings adapter

## Ownership

Own only `memory/embeddings.py`, `tests/memory/test_embeddings.py`, and
`docs/tasks/deps-memory_embeddings.txt`. Do not edit package initializers,
other `memory/` files, requirements, docs, or other tests. Do not commit.

## Task

Implement a configurable local embedding-provider interface and an Ollama HTTP
adapter. Do not hardcode a model ID: obtain it from an explicit local setting.
Normalize/validate numeric vectors, use timeouts, and return actionable
non-secret errors when Ollama is unavailable. Tests must use a fake transport;
no live Ollama/model pull. If a pinned dependency is genuinely required, append
only its name and rationale to the owned deps file; do not edit requirements.

## Phase 1 context

Blueprint section 1.1 targets local embeddings (nomic-embed-text by default,
but model choice must remain configuration). No personal data or provider API
keys may leave the machine through this adapter.
