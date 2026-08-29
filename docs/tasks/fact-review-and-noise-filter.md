# Lane: fact review/forget API + ingest noise filter

Two of the three jobs that gate **Phase 1's acceptance criterion**
(`1.4-review-loop` in `docs/plan.md`). The third, `finish-1.3-backfill-run`, is
blocked on Ali. These two are not blocked on anyone.

Phase 1 is the phase actually underway. This lane is the shortest path to
closing it.

## Blueprint detail — carry this, it is the recovery path

From `docs/blueprint.md` §1.4:

> **1.4 Wire in + review — agent, then you.** Agent makes every inbound message
> do recall() before the model call and remember() after. Then you interrogate
> it: ask ten things it should know from the backfill. Wrong or creepy facts →
> you delete them and tell the agent which pattern to exclude (e.g. stop
> extracting "facts" from forwarded memes). The agent cannot judge whether a
> remembered fact about your life is right; that check is permanently yours.

The first sentence is **already done** — `executor/handlers/whatsapp.py` does
recall → route → send → store. What is missing is the machinery the rest of that
paragraph assumes exists: a way for Ali to *see* what was remembered, *delete*
what is wrong, and *name a pattern* that stops it being re-extracted.

Read that last sentence twice. **This lane builds the tool; it never judges a
fact.** Do not write heuristics that guess whether a remembered fact about Ali's
life is true, and do not ship a default exclusion pattern list invented by you.
The patterns come from Ali. Building the mechanism is this lane's job; deciding
what it filters is his. Inventing the patterns is a Class C violation, not a
helpful default.

## Ownership — files this lane may write

```
memory/review.py                    <- new: the review/forget API over the store
tools/review_facts.py               <- new: the CLI Ali actually drives
ingest/noise.py                     <- new: exclusion-pattern matching
ingest/pipeline.py                  <- wire the filter into chunking (see note)
tests/memory/test_review.py
tests/tools/test_review_facts.py
tests/ingest/test_noise.py
docs/tasks/deps-fact-review.txt     <- deps, if any, for CORE to integrate
docs/tasks/fact-review-and-noise-filter-report.md
```

Check `list` and claim every path above before writing. Stop on a conflict.
Release the claim ID after verification.

**Do not write:**

- `memory/store.py` — you should not need it. `SQLiteFactStore` already exposes
  `delete(fact_id)`, `list_facts(...)`, `count(...)`, `get(fact_id)` and
  `update(...)` (`memory/store.py:133-229`). Build **on top of** those. If you
  genuinely cannot without changing the store, **stop and report** rather than
  claiming it — three separate jobs contended on that file and all three are
  already landed; reopening it is how the collision scars in `docs/plan.md`
  happened.
- `requirements.txt` — append to `docs/tasks/deps-fact-review.txt` instead.
- Any hot file in `docs/plan.md`: `executor/handlers/whatsapp.py`,
  `executor/poller.py`, `bus/main.py`, `db/jobs.py`, `router/routing.py`,
  `bus/whatsapp_client.py`.
- Anything under `voice/` or `diagnostics/` — two other lanes are live in those.

`ingest/pipeline.py` is not on the hot list and no lane currently holds it, but
confirm with `list` before claiming. Keep the edit there to the wire-in only.

## What to build

### 1. `memory/review.py` — the forget API

A small module over `SQLiteFactStore`. Ali's review loop needs to:

- **List recent facts** with enough context to judge them: the fact text, its
  source, when it was stored, and where it came from. Paged — a backfill can
  produce a lot.
- **Search** facts by substring or by source, so "what does it think it knows
  about X" is answerable without scrolling everything.
- **Delete one fact**, and **delete a batch** by id.
- **Delete by pattern** — matching the same pattern mechanism as `ingest/noise.py`
  below, so "stop remembering things like this" retroactively cleans what is
  already stored, not just what arrives next. Deletion is irreversible, so this
  operation must report what it *would* delete and require an explicit confirm.

Look at `memory/mem0_wrapper.py` before writing: facts live in two places. A fact
deleted from the SQLite store but left in Mem0's vector index will still be
recalled. Handle both, or — if the second is not cleanly reachable — **say so
explicitly in the report** rather than shipping a delete that silently leaves the
fact recallable. A forget API that does not actually forget is worse than none.

### 2. `tools/review_facts.py` — the CLI

This is what Ali runs. Mirror the existing tool pattern exactly — read
`tools/distill_memory.py` and `tools/run_backfill.py` first and follow their
shape: same argument style, same `--dry-run` behaviour, same
`executor/heartbeat.py` liveness guard with the same `--force` override and the
same message.

The heartbeat guard matters here for a different reason than usual: it is not
about Ollama contention, it is that mutating the fact store while the executor
is mid-recall is a race. `--dry-run` is never blocked.

Subcommands, roughly: `list`, `search`, `forget <id>`, `forget --pattern`.
Deletion prints what it will remove and requires confirmation. Nothing deletes
without the user seeing it first.

### 3. `ingest/noise.py` — exclusion patterns

The mechanism that stops junk becoming a "fact". Blueprint's own example is
forwarded memes.

- Patterns load from a **config file, not code** — Ali edits the list without an
  agent. Ship the file with the mechanism working and the pattern list **empty or
  commented-out examples only**. Do not populate it with guesses.
- Support the shapes his actual data needs: substring, regex, and source-based
  exclusion (e.g. an entire file or chat export). Read `ingest/pipeline.py`'s
  `_whatsapp_chunks` and `_note_chunks` (`ingest/pipeline.py:138-170`) to see
  what a chunk actually carries before designing the match surface.
- A filtered chunk must be **counted and reportable**, never silently dropped.
  `agents.md`: a silent cap reads as "covered everything" when it did not. Ali
  needs to see "excluded 412 chunks by pattern X" to know his pattern is right —
  and to notice when it is far too broad.

### 4. Wire into `ingest/pipeline.py`

Filter at chunking time, minimal edit. Do not restructure the pipeline. Note
`docs/plan.md` records `backfill-batch-embedding-drift` and
`backfill-checkpoint-identity-drift` as open **Class C decisions** about this
pipeline — do not touch checkpointing or batching semantics while you are in
here. Filter only.

## Verification

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
```

Full offline suite, not a focused subset. Claim `test-workspace` first — two
other lanes are live and must not share `.pytest-basetemp`. Cite the output.

Test against temp databases and fixture files. **Never** run the CLI against the
real `memory.db`, and never delete real facts. `agents.md`: do not delete test
data or artifacts before the outcome has been reported.

## Report

`docs/tasks/fact-review-and-noise-filter-report.md`: what landed with the command
and output proving each piece, what broke, what was specified but not done, deps
added, and — required — whether deletion reaches Mem0's vector index as well as
the SQLite store, stated plainly either way.

Also state explicitly that the shipped pattern list is empty, and that naming the
actual exclusion patterns is Ali's step in `1.4-review-loop`.
