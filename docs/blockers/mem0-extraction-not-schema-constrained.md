# The backfill cannot finish: Mem0 extraction is not schema-constrained (2 September 2026)

`backfill-run` was attempted in its approved overnight window and failed three
times, each time further along than the last. The corpus is intact, the
checkpoint is untouched, and nothing was half-written — but blueprint 1.3
cannot complete until one line of `memory/mem0_wrapper.py` changes, and that
file is outside `backfill-run`'s scope.

**No personal data appears in this file.** Every reproduction below runs on
synthetic text written for the purpose. Ali's corpus was read only by the
backfill tool itself, which is what it is for.

## The one thing that would unblock it

Pass the fact schema to Ollama as `format`, instead of relying on Mem0's
`response_format={"type": "json_object"}`.

`docs/blueprint.md` §1.3 already specifies this and the code does not do it:

> Mem0 fact-extraction through the existing local Ollama runtime using
> **constrained JSON-schema structured decoding**.

`memory/mem0_wrapper.py:347` (`_attach_validating_retry`) wraps
`memory.llm.generate_response` and *validates* the output against
`ExtractionResponse`, retrying once on a `ValidationError`. Validation after
the fact is not constrained decoding: Ollama is still free to emit whatever it
likes, and on a real chunk it does, twice in a row.

## Reproduction

Model `llama3.1:8b`, Ollama on loopback, `.venv`. Synthetic input throughout.

**Unconstrained vs schema-constrained, small input, 3 attempts each:**

```
unconstrained (format "json", what the code sends today):  3/3 valid
schema-constrained (format=<schema>, what §1.3 specifies): 3/3 valid
```

Both pass when the input is small, so the model is not the problem.

**Schema-constrained, scaled to real chunk sizes:**

```
~  96 words    26.2s  valid=True  facts=13
~ 288 words    29.1s  valid=True  facts=15
~ 480 words    26.8s  valid=True  facts=12
~ 768 words    28.4s  valid=True  facts=12
```

Constrained decoding holds at every size the backfill actually sends. The real
run, unconstrained on the same size of input, produced JSON that failed
`ExtractionResponse` validation twice and aborted the file.

## The three failures, in order

Each retry was justified: the failure moved every time.

**1. Extraction timed out at the 90s default.**

```
LLM extraction failed: Local Ollama fact extraction timed out.
ingest\data\me.txt: FAILED
```

Not a cold-start artefact — a small extraction completes in 8.0s cold and 3.3s
warm on this machine. The real extraction call genuinely takes ~90s.

**2. With `OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS=900`, the *embedding* timed
out at its 15s default.**

```
memory.embeddings.EmbeddingError: Local Ollama embedding request timed out.
```

Ollama serves one model at a time. While the 8B generation is in flight, an
embed request queues behind it and blows the 15s budget. This is the same
starvation shape as the 26 August incident, in a different place.

**3. With `OLLAMA_EMBEDDING_TIMEOUT_SECONDS=180` as well, extraction ran to
completion — two `/api/chat` calls, ~90s each — and returned unusable JSON.**

```
LLM extraction failed: Local Ollama returned invalid Mem0 fact JSON after one retry.
```

That is the wall. It is a decoding problem, not a timeout problem.

## What was left behind

Nothing to clean up.

- **Checkpoint unchanged:** `next_chunk_index: 1`, `updated_at
  2026-08-26T19:28:24Z`. The failed runs wrote no checkpoint, so the backfill
  resumes exactly where it was rather than restarting.
- **Memory unchanged:** 230 facts before and after, all pre-existing
  conversation turns.
- **Nothing was written to `ingest/data/`.** The tool only reads it.
- Ollama was started for this run and left running; the executor was already
  stopped and was left stopped.

## Also worth fixing while someone is in there

The two timeout defaults are too tight for a single serial Ollama on this
machine, independently of the schema question:

- `OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS` defaults to 90; the real call takes
  about that, so it fails on the boundary.
- `OLLAMA_EMBEDDING_TIMEOUT_SECONDS` defaults to 15, which cannot survive an
  8B generation holding the runtime.

Raising them is not a fix on its own — run 3 had both raised and still failed —
but leaving them means the fix cannot be tested. Note that
`executor/handlers/distill.py`'s `assert_timeouts_ordered()` requires the
handler timeout to stay above the extraction timeout, so the two move together.

## Why this lane stopped instead of fixing it

`backfill-run`'s frontmatter is `files: docs/tasks/backfill-run-report.md (run
artifacts only; code changes only if Q3=B)`, and Ali answered **Q3 = A** on
1 Sep, which explicitly removed the conform step. Editing
`memory/mem0_wrapper.py` is therefore out of scope for this task by its own
gate, and `agents.md` is clear that a deviation reaching a commit is a failure
whether or not tests pass.

The change wants its own task with its own tests. It is small — pass the
schema through, keep the existing validate-and-retry as a belt-and-braces
second line — but it touches the memory write path, which is the one thing in
this repo that must never silently narrow.
