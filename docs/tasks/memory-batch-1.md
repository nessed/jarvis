# Lane: memory-batch-1

## Ownership

Own only `memory/conversation.py`, `memory/mem0_wrapper.py`,
`memory/store.py`, `tests/memory/test_conversation.py`,
`tests/memory/test_mem0_wrapper.py`, `tests/memory/test_store.py`. Claimed
under work-board claim `memory-batch-1` — already held by the orchestrator; do
not re-claim or release it. Do not touch any other file. Do not edit
`requirements.txt`; append any new dependency to
`docs/tasks/deps-memory-batch-1.txt`. Do not commit.

## Context

Three fixes, in this exact order — job 2 becomes a one-line consumer of job 1,
and job 3 is independent but do it last since it's the highest-risk of the
three (touches connection setup used everywhere).

### 1. `undistilled-turns-indexed-query`

`ConversationMemory.undistilled_turns()` in `memory/conversation.py` (line 84)
calls `self.runtime.store.list_facts()` with no filter — this loads and
JSON-decodes **every row** in the `facts` table, then filters in Python for
`is_conversation_turn(fact) and not fact.metadata.get("distilled")`. This
includes the `limit=1` emptiness check the distill chain runs on every tick to
see if there's anything to do. `memory/store.py`'s `SQLiteFactStore` stores
`metadata` as a JSON text blob (see `_SCHEMA` and `_encode_metadata`/
`_fact_from_row`), so there is no indexed column to filter `distilled` on
directly via SQL today. Add whatever is needed to make this cheap for the
common case — options include: a dedicated indexed boolear column
(`distilled INTEGER NOT NULL DEFAULT 0`) with a migration matching the
existing `_migrate_embedding_model` pattern (`PRAGMA table_info` check + `ALTER
TABLE ... ADD COLUMN`), kept in sync by `mark_distilled()`
(`memory/conversation.py:94`) and `remember()`
(`memory/conversation.py` around line 63, which sets `"distilled": False` in
metadata today). Pick the approach that keeps `SQLiteFactStore` a plain
generic fact store (it has no `conversation.py`-specific concept today) if you
can do it via a generic filtered/paginated query method instead of a
turn-specific column — your call, but state which you chose and why in your
report. Either way, the emptiness check (`limit=1`) must not scan/decode the
whole table.

### 2. `mem0-search-overfetch`

`VectorAdapter.search()` in `memory/mem0_wrapper.py` (line 178-194) calls
`self.index.search(vectors, limit=max(top_k, len(self.store.list_facts())))`
— every search materializes and JSON-decodes the entire `facts` table just to
take `len()` of it, to compute an over-fetch bound for sqlite-vec (the comment
above it explains why over-fetch is needed: entity collections share one
sqlite-vec index segregated by metadata). Once job 1 lands, use whatever cheap
counting mechanism it added (a `COUNT(*)` query, or a count method on
`SQLiteFactStore`) instead of `len(self.store.list_facts())`. If job 1 didn't
add a general-purpose count method, add a minimal
`SQLiteFactStore.count(self) -> int` (a single `SELECT COUNT(*) FROM facts`)
rather than widening scope elsewhere.

### 3. `sqlite-wal-and-busy-timeout`

`SQLiteFactStore.initialize()` in `memory/store.py` (line 42-56) opens the
connection with `sqlite3.connect(self.path)` and sets no `journal_mode` or
`busy_timeout` pragma. Three separate connections to one `memory.db` exist
across two processes (the bus, the executor, and any one-off CLI/backfill
tool) per `docs/plan.md`'s resource notes. A concurrent write from a second
connection raises `sqlite3.OperationalError: database is locked` immediately
with SQLite's default settings. Set `PRAGMA journal_mode=WAL` and a
`PRAGMA busy_timeout=<some reasonable value, e.g. 5000ms>` right after opening
the connection, before `executescript(_SCHEMA)`. Confirm WAL mode is actually
compatible with this codebase's usage pattern (short-lived vs long-lived
connections, any `:memory:` database use in tests — check
`tests/memory/test_store.py` for in-memory DB paths, since WAL requires a
real file and silently falls back to a different journal mode for `:memory:`,
which is fine but worth confirming isn't mistaken for a bug in your tests).

## Verification

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-memory tests/memory/test_conversation.py tests/memory/test_mem0_wrapper.py tests/memory/test_store.py
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-memory --ignore=tests/db/test_jobs_integration.py
```

## Report

For each of the three fixes: what was wrong, the fix, the test that proves it,
and which approach you picked for job 1's indexing strategy and why.
