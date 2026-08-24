# Phase 1 lane: memory service

## Ownership

Own only `memory/service.py` and `tests/memory/test_service.py`. Do not edit
package initializers, stores, embeddings, vector files, bus, requirements, docs,
or other tests. Do not commit.

## Task

Implement an injected local-memory service joining the existing fact store,
embedding provider, and a minimal vector-index protocol. `remember` must embed
and persist a fact then index its stable ID; `recall` must embed the query,
retrieve nearest IDs, hydrate facts, and skip deleted/stale IDs. Preserve the
local-only boundary: no hosted fallbacks, no raw payload logging, no automatic
fact extraction. Add focused fake-component tests.

## Phase 1 context

The service is the eventual `remember()` / `recall()` surface. Wiring it into
inbound WhatsApp waits until a configured local model is live, so webhooks never
fail or leak data if local memory is unavailable.
