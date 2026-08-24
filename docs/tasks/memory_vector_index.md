# Phase 1 lane: sqlite-vec index

## Ownership

Own only `memory/vector_index.py` and `tests/memory/test_vector_index.py`.
Do not edit other memory files, requirements, docs, or other tests. Do not
commit.

## Task

Implement a local sqlite-vec-backed semantic index using the already installed
`sqlite-vec==0.1.9`. Require an explicit vector dimension at initialization,
persist stable fact IDs, validate vector dimension/finite numeric values, and
provide nearest-neighbour lookup returning only fact IDs and distances. Load the
extension safely for a local SQLite connection. Add real focused tests against a
temporary database; no network or personal data.

## Phase 1 context

The SQLite fact store already owns fact records. This lane indexes only vectors
and fact IDs; it must not duplicate raw fact text or communicate externally.
`sqlite-vec` is pre-v1, so isolate its calls here.
