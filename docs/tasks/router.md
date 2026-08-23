# Wave B2: provider router

## Ownership

Only edit `router/`, `tests/router/`, and `docs/tasks/deps-router.txt`. Do not
commit or modify any other path.

## Objective

Build the Phase 0.6 OpenAI-compatible routing lane against mocks first; provider
keys may not exist yet. Create `providers.yaml` with eight priority rungs:
Groq, Cerebras, NVIDIA NIM, Gemini AI Studio, OpenRouter, DeepSeek, Claude Max,
and Claude API. Each declares endpoint, environment key name, priority, default
model, and suitable task profiles. Claude Max is explicitly `not_a_router_target`
(it is called via the official `claude -p` executor path), while Claude API is
capped and emergency-only. Do not hardcode provider rate limits or free-model
IDs. A rotating OpenRouter free model may use `openrouter/free`.

Provide one OpenAI SDK client with per-rung `base_url` swapping. Implement
`route(task_profile, ..., urgent=False)` supporting `latency`, `batch`,
`long_context`, `vision`, and `reasoning` profiles that reorder eligible rungs.
Read `retry-after` and `x-ratelimit-*` headers from actual responses at runtime;
never bake rate numbers into code. On 429 or 5xx, record the rung in a cooldown
ledger and skip it until the indicated/default backoff expires before falling
through. Keys are read from the environment only at call time; never expose
them.

DeepSeek is the paid overflow V4-Flash lane and should wait for off-peak for
non-urgent work during UTC 01:00–04:00 and 06:00–10:00; urgent work may run.
If `DEEPSEEK_VIA_OPENROUTER=true`, keep DeepSeek in the same chain position but
route it through the OpenRouter base URL and configured paid DeepSeek model.

Write mocked tests, including a fake 429 cascade that proves each fallback
landing rung and proves cooldown/header behavior. Add dependencies only in
`docs/tasks/deps-router.txt` for integration to merge.
