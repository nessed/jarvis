# Phase 1 lane: local memory store

## Ownership

Own only `memory/types.py`, `memory/store.py`, and `tests/memory/test_store.py`.
Do not edit package initializers, other `memory/` files, requirements, docs, or
other tests. Do not commit.

## Task

Implement a local-first SQLite durable fact store with explicit schema creation
and safe CRUD/retrieval primitives. Facts require text, source, and timestamps;
support stable IDs and deletion. Store raw data only locally. Keep vector search
behind an interface so sqlite-vec can be attached at integration, but do not
invent a vector dependency or modify requirements. Add comprehensive unit tests
for schema, insert/list/delete, source metadata, and empty retrieval.

## Phase 1 context

Blueprint section 1.1 requires `memory.db`, a plain facts table, and later
sqlite-vec. Nothing from personal notes or WhatsApp may be read by this lane.
No network calls or LLM calls belong here.
