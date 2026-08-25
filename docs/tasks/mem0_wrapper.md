# Mem0 self-host wrapper — recovery brief

## Objective

Complete blueprint step 1.1 without replacing the existing local-memory
foundation: add pinned Mem0 in self-host mode over the current Ollama +
`nomic-embed-text` + sqlite-vec + SQLite facts stack. Mem0 must provide fact
extraction, deduplication, and contradiction handling, while the existing
`SQLiteFactStore`, `SQLiteVecIndex`, and Ollama adapter remain underneath.
Expose `remember()` and `recall()` to the bus through the new wrapper.

## Authorized revision

The earlier stop is resolved by explicit authorization. Implement a custom
Mem0 vector-store provider subclassing `mem0.vector_stores.base.VectorStoreBase`.
It must delegate to the existing `SQLiteFactStore` and `SQLiteVecIndex`; do not
add or substitute Qdrant, Chroma, FAISS, or another backend, and do not rewrite
the existing memory-layer implementations.

Use Mem0's shipped Ollama adapter with its `json_object` response format. Parse
the result through the wrapper's Pydantic fact model, retry exactly once on
validation failure, then raise a clear error. Do not subclass or otherwise
replace Mem0's LLM adapter. The previously required constrained JSON-schema
`format=` forwarding is withdrawn.

Blueprint step 1.3 has already been minimally amended: fact extraction is
local through Ollama because NVIDIA NIM is geo-blocked from Pakistan and
Gemini's free tier may train on prompts. Keep that decision intact.

## Hard requirements

- Local loopback only for extraction and embeddings. Reuse the existing
  loopback-host guard or an equivalent guard for both Mem0 adapters. No hosted
  fallback: unavailable local Ollama must fail closed with a clear error.
- Extraction must use Mem0's local Ollama `json_object` mode, Pydantic response
  validation, and exactly one retry after validation failure before erroring.
  If validation retries prove flaky in practice, report that finding; do not
  subclass the LLM adapter without further authorization.
- Do not hardcode the extraction model. Read an environment variable with a
  default. Before implementation, pull a small Qwen3 candidate and a Llama
  3.x 8B candidate; test each against ten synthetic, non-personal sentences;
  report valid schema-conforming output reliability in `docs/context.md`; set
  the default to the winner.
- Add the embedding-model identifier to facts, migrate existing rows, and
  refuse index opening when stored vectors were produced by a different model.
  Silent model or dimension drift is prohibited.
- Pin the selected `mem0` version in `requirements.txt`.
- Add focused tests only under `tests/memory/`; run only that directory, never
  the full suite. Do not read, ingest, or reference personal corpus; `ingest/`
  remains empty by design.
- Replace the 25 August live-memory smoke-test context entry: re-run through
  the Mem0 path with a generic non-personal fact and isolated temporary DB;
  write the exact command and exact output verbatim before deleting its DB and
  sidecars. If it fails, record the real failure text as failed verification.

## Current facts

Ollama 0.32.15 is local and `nomic-embed-text` is installed; its non-personal
embedding probe returned one 768-dimensional vector. Existing focused memory
tests previously passed (31), but Mem0 appears in no Python file and is absent
from requirements, so step 1.1 remains incomplete. The prior hand-rolled
`remember()` / `recall()` implementation is foundation only, not a substitute.
The earlier Qwen3 pull was interrupted and `ollama list` confirmed it absent;
re-pull it for the required comparison before selecting the default extraction
model. Update the stopped-state context entry to describe this authorized
implementation path before reporting completion.

## Current diagnosis checkpoint

The wrapper now has a local-only bounded extraction timeout with a 30-second
default. By user decision, the configured default is now `llama3.1:8b`, based
on live timing evidence: `qwen3:4b` timed out on this machine (including a raw
20-second run), while `llama3.1:8b` completed in about 17.4 seconds. Retain
Qwen as the comparison candidate; do not silently switch models. Focused memory
tests currently pass: **39 passed**. Preserve any temporary smoke database
until its command and exact output have been recorded in `docs/context.md`.

## Authorized measurement-only work (25 August 2026)

The queue/executor lane is separately adding attempts, backoff, per-job
timeout, and a handler registry. It owns `db/` and `executor/`; this lane must
not read, modify, or wire against those files until that work lands and new
authorization is given. The earlier reference to an “existing retry path” was
withdrawn. Async extraction and its smoke test are therefore blocked and out
of scope for this task.

Do not raise the interactive `remember()` timeout as a remedy. Complete only
the following synchronous, non-personal measurements and report their actual
numbers before any further work:

1. Set `OLLAMA_KEEP_ALIVE=-1`. For the same real Mem0 extraction call, obtain
   one cold measurement immediately after `ollama stop`, then one warm
   measurement. Record both latencies separately: cold includes model loading;
   warm measures resident-model inference.
2. Cap extraction to the fact schema. Set explicit Ollama `num_predict` and
   `num_ctx`, with `num_predict` sufficient only for the required JSON fact
   payload and `num_ctx` no larger than the actual real Mem0 extraction prompt
   needs. Report both selected values and their rationale. Generation must not
   remain unbounded.
3. With keep-alive and those identical caps applied, warm each model before
   measurement and run ten identical real-Mem0-extraction calls for each of
   `qwen3:4b` and `llama3.1:8b`. Report per-model median latency and
   schema-validation success rate. The prior Qwen/Llama comparison is invalid:
   it used a short Qwen prompt capped at 32 tokens and the real Mem0 prompt for
   Llama. Select the extraction-model default only from this fair comparison;
   do not retain the present Llama default merely because of the invalid result.

Do not run the live write-and-recall smoke yet. It is reserved for the later
authorized async path and must write stdout and stderr to separate artifacts
before any cleanup; the prior run had neither artifact (`Exists=False` for
both), so it is not verification evidence. Preserve no personal data, make no
code changes in this measurement task, and do not commit.

## Ownership

Implementation lane may edit exactly: `memory/`, `tests/memory/`,
`requirements.txt`, `docs/context.md`, `docs/blueprint.md`, and this brief.
Do not read or write `flp/` or `test_projects/`; do not commit. If Mem0 cannot
be wired as specified to the existing local stack, stop and report the blocker
without an alternative implementation.
