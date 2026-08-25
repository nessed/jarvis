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

## Root cause fixed — compact extraction prompt (25 August 2026)

Traced (installed mem0ai 2.0.19 source, not docs): `Memory.add`/`AsyncMemory.add`
(`mem0/memory/main.py:942` and `:2604`) hardcode
`system_prompt = ADDITIVE_EXTRACTION_PROMPT` as a bare module-global read
inside the only LLM-extraction path present in this version (the "V3 phased
batch pipeline", used whenever `infer=True`, the default). No supported
config or argument selects a different prompt: `mem0.memory.utils`'s
`get_fact_retrieval_messages` / `get_fact_retrieval_messages_legacy` and their
`USER_MEMORY_EXTRACTION_PROMPT` / `FACT_RETRIEVAL_PROMPT` constants are
unreferenced dead code in `main.py` (`grep -rn "get_fact_retrieval_messages\b"
.venv/Lib/site-packages/mem0/` matches only their own definitions), and
`MemoryConfig.version` / `self.api_version` feeds telemetry only, not
pipeline selection. Separately, `mem0/llms/ollama.py`'s `OllamaLLM.generate_response`
builds its Ollama `options` dict from only `temperature`/`max_tokens`
(-> `num_predict`)/`top_p`; it accepts `**kwargs` but never reads them, so
`num_ctx` and `keep_alive` are not reachable through Mem0's shipped Ollama
adapter at all, through any config.

Literal "subclass Memory and override the system prompt" is not mechanically
available: the prompt is a local variable inside one ~250-line method, not a
class attribute or a separately-overridable method, so a subclass override
would mean reimplementing that entire method. Reported this instead of
silently reimplementing it. The narrower fix landed: `memory/mem0_wrapper.py`
now defines `COMPACT_ADDITIVE_EXTRACTION_PROMPT` (2,419 characters, down from
the shipped 33,653) and `_install_compact_extraction_prompt()`, called from
`_mem0_api()` before `Memory` is constructed, reassigns the module global
`mem0.memory.main.ADDITIVE_EXTRACTION_PROMPT` at runtime. This edits no file
under site-packages, does not touch or replace Mem0's LLM adapter, and does
not duplicate Mem0's batch pipeline. It preserves the exact output contract
(`{"memory": [{"id","text","attributed_to","linked_memory_ids"}]}`) that both
Mem0's own downstream parsing and the wrapper's `ExtractionResponse` model
require — the shipped lighter prompts produce an incompatible
`{"facts": [...]}` shape and were deliberately not used verbatim. A drift
guard (`_SHIPPED_PROMPT_MINIMUM_LENGTH = 20_000`) raises `Mem0WrapperError`
if a future mem0ai upgrade already shrank/removed the shipped prompt before
this patches it. The wrapper's `LlmConfig` now also sets `max_tokens=128`
(-> `num_predict`), previously unset and defaulting to 2000.

**Live end-to-end smoke (26 August 2026, passed after one more fix):** ran
`open_local_mem0_memory()` / `remember()` / `recall()` directly (not raw
`ollama` calls). `remember()` succeeded on the first try, 35.146s cold,
correctly extracting the fact via the compact prompt. `recall()` then failed:
`ValueError: Top-level entity parameters frozenset({'user_id'}) are not
supported in search(). Use filters={'user_id': '...'} instead.` — a second,
independent bug: `Mem0Memory.recall()` called
`self._memory.search(query, user_id=user_id, limit=limit)`, but installed
mem0ai 2.0.19's `Memory.search(query, *, top_k=20, filters=None, ...)`
rejects `user_id`/`agent_id`/`run_id` as top-level kwargs and has no `limit`
parameter (it's `top_k`; the old `limit=limit` silently fell into unused
`**kwargs`). Fixed to `search(query, filters={"user_id": user_id},
top_k=limit)`, with a new regression test
(`test_mem0_recall_passes_user_id_through_filters_not_as_a_top_level_kwarg`).
Re-ran `recall()` after the fix: it correctly returned the previously
remembered fact with a similarity score. Full exact commands/output in
`docs/context.md`. Both fixes are live-smoke-verified but still uncommitted.
Focused tests: `.venv\Scripts\python.exe -m pytest -q tests\memory` ->
**45 passed**.

Re-measured per the current authorized instructions (raw `ollama` client
calls against the real compact system prompt + the real
`generate_additive_extraction_prompt` user prompt, since Mem0's adapter
cannot accept `num_ctx`/`keep_alive`): warm, `keep_alive=-1`, `num_predict=128`,
`num_ctx=2048` (sized from the actual compact prompt: 2,419 + 258 = 2,677
characters ≈ 669 estimated tokens at ~4 chars/token, rounded up for headroom
— 8x smaller than the previous 16384) completed in **5.998 seconds**
(`prompt_eval_duration` 159ms for 636 prompt tokens, `eval_duration` 5.82s for
38 generated tokens on this CPU-only Ollama install). Full commands and exact
output are recorded in `docs/context.md`. This clears the ~15s gate, so the
ten-run fair comparison ran: llama3.1:8b **10/10** schema-valid, median
**6.313s**; qwen3:4b **0/10** schema-valid — every run hit
`"done_reason":"length"` with the full 128-token budget consumed by Qwen3's
hidden `thinking` output before any JSON content. `DEFAULT_FACT_EXTRACTION_MODEL`
stays `llama3.1:8b`, now confirmed by this fair comparison rather than by the
earlier invalidated one. Focused memory tests: `.venv\Scripts\python.exe -m
pytest -q tests\memory` -> **44 passed**.

## Ownership

Implementation lane may edit exactly: `memory/`, `tests/memory/`,
`requirements.txt`, `docs/context.md`, `docs/blueprint.md`, and this brief.
Do not read or write `flp/` or `test_projects/`; do not commit. If Mem0 cannot
be wired as specified to the existing local stack, stop and report the blocker
without an alternative implementation.
