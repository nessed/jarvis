# Report: fact review/forget API + ingest noise filter

Lane brief: `docs/tasks/fact-review-and-noise-filter.md`. Closes the two
not-blocked-on-Ali jobs gating Phase 1's `1.4-review-loop` acceptance
criterion (`finish-1.3-backfill-run` remains blocked on Ali separately).

## What landed

### 1. `memory/review.py` -- the forget API

Built entirely on `SQLiteFactStore`'s existing public surface (`list_facts`,
`get`, `delete`) -- `memory/store.py` was not touched. Provides
`open_review_store`, `list_recent` (paged), `search` (substring/source),
`delete_fact`, `delete_facts` (batch), `facts_matching_pattern` (preview),
`delete_by_pattern`.

Proof, targeted tests:

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp tests/memory/test_review.py
```
`24 passed` (part of the 59 below).

### 2. `ingest/noise.py` -- exclusion-pattern mechanism

`ExclusionPattern` (substring/regex/source), `load_patterns` (parses
`<kind>:<value>` lines from a config file, skips blank/`#` lines),
`parse_pattern` (one spec, for the CLI's `--pattern`), `filter_chunks`
(returns kept chunks plus a per-pattern exclusion count -- never a silent
drop, per `agents.md`).

Shipped config: `ingest/noise_patterns.txt`, committed with its pattern list
**empty** (comments and format documentation only). No pattern was invented
by this lane. Naming an actual exclusion pattern (e.g. "stop extracting facts
from forwarded memes") is Ali's step in `1.4-review-loop`, not this lane's.

### 3. Wired into `ingest/pipeline.py`

`chunk_file` gained one optional keyword, `noise_patterns: list[ExclusionPattern]
| None = None`. When omitted (every existing caller, including
`ingest/backfill.py`, which this lane does not own and did not touch), it
loads `ingest/noise_patterns.txt` -- empty today, so behaviour is unchanged
for every current caller. Filtered chunks are logged
(`excluded %d chunk(s) from %s by pattern %s`) via the standard `logging`
module, which `tools/run_backfill.py` and `tools/distill_memory.py` already
configure with `logging.basicConfig(level=logging.INFO, ...)` -- so exclusion
counts surface in the same place Ali already watches backfill output,
without changing `ingest/backfill.py`'s call signature.

Manual proof the wiring is live (not just unit-tested in isolation):

```
$ .venv/Scripts/python.exe -c "
from pathlib import Path; import tempfile
from ingest.pipeline import build_manifest, chunk_file
from ingest.noise import ExclusionPattern
with tempfile.TemporaryDirectory() as d:
    f = Path(d, 'a.txt'); f.write_text('this is a forwarded meme\nreal content here')
    m = build_manifest(f, intake_dir=Path(d))
    print('default (no patterns configured):', len(chunk_file(f, m)))
    print('with substring:forwarded pattern:', len(chunk_file(f, m, noise_patterns=[ExclusionPattern('substring','forwarded','<t>')])))
"
default (no patterns configured): 1
with substring:forwarded pattern: 0
```

### 4. `tools/review_facts.py` -- the CLI

Mirrors `tools/distill_memory.py`/`tools/run_backfill.py`: same
`logging.basicConfig` setup, same `refuse_if_executor_is_live` heartbeat
guard with the same `--force` override and message, `--dry-run` never
touches the guard. Subcommands: `list`, `search` (read-only, no guard),
`forget <id>...` / `forget --pattern <spec>` (mutating; always previews the
exact facts it would remove before doing anything; requires typed
confirmation or `--yes`; irreversible).

End-to-end smoke test against a throwaway database (not the real `memory.db`):

```
$ .venv/Scripts/python.exe tools/review_facts.py --database _smoketest_memory.db list
p2  2026-08-29  whatsapp:923000000000  This was forwarded many times, lol check it out
p1  2026-08-29  notes/prefs.md  Ali prefers concise replies

$ .venv/Scripts/python.exe tools/review_facts.py --database _smoketest_memory.db search --text forwarded
p2  2026-08-29  whatsapp:923000000000  This was forwarded many times, lol check it out

$ .venv/Scripts/python.exe tools/review_facts.py --database _smoketest_memory.db forget --pattern "substring:forwarded" --dry-run
would delete 1 fact(s):
  p2  2026-08-29  whatsapp:923000000000  This was forwarded many times, lol check it out

$ .venv/Scripts/python.exe tools/review_facts.py --database _smoketest_memory.db forget --pattern "substring:forwarded" --yes
would delete 1 fact(s):
  p2  2026-08-29  whatsapp:923000000000  This was forwarded many times, lol check it out
deleted 1 fact(s)

$ .venv/Scripts/python.exe tools/review_facts.py --database _smoketest_memory.db list
p1  2026-08-29  notes/prefs.md  Ali prefers concise replies
```

Test database deleted after this proof was captured; nothing under the real
`memory.db` was touched by this lane at any point.

## Does deletion reach Mem0's vector index? (required answer)

**Yes, fully, and there is no separate system to reach.** This codebase's
Mem0 integration (`memory/mem0_wrapper.py`'s `SQLiteVecMem0Store`) has no
remote or third-party vector database. Every fact -- whether it arrived
through a live turn, a Mem0 batch extraction, or a backfill -- is a row in
the *same* `SQLiteFactStore` table `SQLiteVecMem0Store.insert()` writes to,
with its embedding, if any, as a row in `memory/vector_index.py`'s
`SQLiteVecIndex` against the *same* database file.

`memory/review.py`'s `open_review_store` reads the on-disk
`vector_index_identity` row to open that same index (no embedding model is
invoked -- review/search/delete are substring/pattern operations, not
semantic search), and `delete_fact` removes the vector row before the store
row. This was proven, not assumed: `tests/memory/test_review.py
::test_delete_fact_also_removes_the_vector_index_entry` seeds a real
`SQLiteVecIndex`, deletes one fact, reopens the index from disk in a second
process-equivalent handle, and asserts the deleted id is gone from
`index.search()` results while the untouched ids remain.

Secondary note for completeness: even a store-only delete (no index touch)
would already make a fact unrecallable through both `MemoryService.recall`
and `SQLiteVecMem0Store.search`, since both skip any index hit whose
`store.get(fact_id)` comes back empty. `delete_fact` purging the vector row
too is not closing a recall leak (there wasn't one) -- it is not leaving a
disk-space orphan behind.

## What broke

Nothing. Full offline suite is green (below). The one dead end during
manual smoke-testing was environmental, not a code defect: `mktemp -u`
under this machine's Git Bash produced a path the CLI and the seeding script
resolved inconsistently, so the first smoke-test attempt showed "no facts
found" against an empty file. Re-run with a plain absolute path resolved it;
this is a shell-quoting artifact of the ad hoc verification command, not
present in any committed code or test.

## What was specified but not done

Nothing from the brief was skipped. `docs/tasks/deps-fact-review.txt` is
empty (no new dependency) since every module uses the standard library plus
`sqlite-vec`, already required by `memory/vector_index.py`.

## Verification

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
595 passed, 5 deselected, 2 warnings in 34.64s
```

Targeted subset for this lane plus the pre-existing `ingest/pipeline.py`
tests it touches, confirming no regression there:

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp tests/ingest/test_noise.py tests/memory/test_review.py tests/tools/test_review_facts.py tests/ingest/test_pipeline.py
59 passed in 4.27s
```

## Backend/interface notes for other lanes

None. This lane touched no shared interface, no `Protocol`, and no public
signature any other lane implements. `ingest/pipeline.py`'s only caller
outside this lane, `ingest/backfill.py`, is unaffected: the new
`noise_patterns` keyword is optional and defaults to today's behaviour
exactly (empty pattern file -> zero filtering).

## Explicit statements the brief requires

- The shipped pattern list (`ingest/noise_patterns.txt`) is **empty** --
  comments and format documentation only, no invented patterns.
- Naming the actual exclusion patterns (e.g. "stop extracting facts from
  forwarded memes") is **Ali's step** in `1.4-review-loop`, not this lane's.
- Deletion reaches Mem0's vector index: **yes**, stated and proven above.
