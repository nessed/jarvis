# mem0-version-conformance-test + test-openai-chat-client

Two independent, disjoint-file jobs from `docs/plan.md`'s "Tests for things
that have none" list. Claimed as one lane (work-item
`mem0-and-openai-client-tests`) since both are self-contained additions with
no shared code path. BUILD role: do not commit, do not touch
`requirements.txt`.

Router jobs 1-3 and most memory/poller/tool-test gaps from `docs/plan.md`
already landed in commits `608dfd7`..`1672f8c` — re-read the current state of
`memory/mem0_wrapper.py` and `router/routing.py` yourself rather than
trusting `docs/plan.md`'s descriptions verbatim; the board is a snapshot and
has already gone stale on other jobs once this session (see
`flp-stale-module-docstrings`'s outcome, noted in the board itself).

## Job 1 — mem0-version-conformance-test

New file: `tests/memory/test_mem0_pinning.py`. `requirements.txt` pins
`mem0ai==2.0.19` exactly. `memory/mem0_wrapper.py` reaches into several of
that package's private/internal surfaces rather than its public API —
grep the file yourself for the full list, but it includes at minimum:

- `mem0.memory.telemetry` — an import-time flag read directly off the module.
- `mem0.vector_stores.base.VectorStoreBase` — subclassed directly.
- `mem0.memory.main.Memory.add`/`AsyncMemory.add`'s hardcoded extraction
  system prompt, patched via `mem0.memory.main.ADDITIVE_EXTRACTION_PROMPT`
  (read the surrounding comments in `memory/mem0_wrapper.py` around line
  405-441 for exactly what this patch does and why — it exists to make Mem0
  use this project's own shorter extraction prompt instead of the library's
  default).
- `mem0.configs.base.MemoryConfig`, `mem0.embeddings.configs.EmbedderConfig`,
  `mem0.llms.configs.LlmConfig`, `mem0.utils.factory.EmbedderFactory`,
  `mem0.utils.factory.VectorStoreFactory`,
  `mem0.vector_stores.configs.VectorStoreConfig` — internal config/factory
  classes constructed directly rather than through any documented public
  entry point.

Per `docs/plan.md`: "only one fails loudly on a bump" — meaning most of
these would silently change behavior or break the extraction pipeline mid-run
on a `mem0ai` version bump, not raise an ImportError at import time. Write a
test module that imports each of these exact symbols and asserts something
meaningful about their shape (the attribute/class exists, has the expected
type, `ADDITIVE_EXTRACTION_PROMPT` is a non-trivially-short string, etc.) —
the goal is that upgrading `mem0ai` and running this test file specifically
is what should fail loudly for every one of these couplings, not just the
one that already does. Read `memory/mem0_wrapper.py` in full first; match
whatever test patterns already exist in `tests/memory/` (e.g.
`tests/memory/test_mem0_wrapper.py`, which now exists after recent commits)
rather than inventing a new style.

## Job 2 — test-openai-chat-client

File: `tests/router/test_routing.py` (existing file, extend it).
`router.routing.OpenAIChatClient` (`router/routing.py:81-111`) is never
constructed by any current test — grep-confirm this yourself
(`grep -n "OpenAIChatClient(" tests/router/test_routing.py` currently
returns nothing). Its real behavior is untested:

- `create_chat_completion` calls `self._client.with_raw_response.chat.completions.create(...)`
  then does `dict(raw_response.headers)` and `raw_response.parse()` — real
  header casing (the OpenAI SDK's httpx-backed headers are case-insensitive
  multi-dict; confirm what `dict()` on them actually produces) is
  unexercised.
- `list_chat_models` (`router/routing.py:100-111`) calls
  `self._client.with_raw_response.models.list()`, stores headers the same
  way, then filters via `_chat_model_id` — also never constructed against a
  real or realistically-faked `AsyncOpenAI` client.
- SDK-exception mapping: elsewhere in `router/routing.py`,
  `_response_metadata(exc)` extracts `status`/`headers` from whatever the
  SDK raises (rate limits, 402s, 5xxs) — confirm whether `OpenAIChatClient`
  itself is exercised against a real `openai` SDK exception shape (e.g.
  `openai.RateLimitError`, `openai.APIStatusError`) anywhere, and if not,
  add that coverage here.

Do not make real network calls. Use `openai`'s own test/mock patterns if the
SDK ships any, or a fake `AsyncOpenAI`-shaped object with a
`with_raw_response` attribute — read how the rest of `router/routing.py`'s
existing tests fake provider clients first (there's an established
`ChatClient`/`ModelDiscoveringChatClient` Protocol pattern; match it) rather
than reaching directly into `httpx`/`openai` internals from scratch.

## Verification

Run the full offline suite exactly as CLAUDE.md specifies:

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
```

Cite the output. Do not report done without it. Do not commit. Report back:
test counts before/after for each file, exactly which mem0 symbols got
conformance assertions, and anything above you could not complete and why.
