# Phase 1 local-memory runtime hardening

## Blueprint basis

Blueprint Phase 1.1 requires local sqlite-vec memory backed by a local Ollama
embedding model. `memory.runtime.open_local_memory()` already probes vector
dimension before opening local stores, but its startup/cleanup behavior has not
been independently proved without a live Ollama installation.

## Strict ownership

Own only `memory/runtime.py`, `tests/memory/test_runtime.py`, and this brief.
Do not edit embedding, store, vector-index, service, package-initializer,
configuration, requirements, context, or other test files.

## Task

Add the smallest testable seams needed to prove startup uses the fixed,
non-personal dimension probe; creates fact and vector stores only after a local
embedding is usable; preserves the explicit local configuration contract; and
closes opened resources on partial initialization failure. Keep the public
runtime API compatible.

## Non-goals

Do not install or invoke Ollama, pull a model, make network calls, read `.env`
values, ingest a corpus, or wire memory into bus traffic. Do not alter the
loopback-only privacy policy.

## Tests and dependencies

Use monkeypatch/fakes and temporary SQLite paths; test successful startup,
dimension probe, unavailable/misconfigured embedding behavior, and cleanup on
vector-index initialization failure. No new dependency is expected; do not edit
`requirements.txt`. If indispensable, append only name and rationale to
`docs/tasks/deps-memory_embeddings.txt`.

## Result (25 August 2026)

- Added offline runtime coverage for the constant dimension probe, explicit
  local configuration, unusable embeddings, and cleanup after index startup
  failure.
- Runtime now leaves a caller-supplied `environ` fully explicit (it does not
  load `.env` in that mode), builds stores only after the probe succeeds, and
  best-effort closes both resources if later initialization fails.
- No dependency was added. Focused verification: `31 passed`.
