# Stop 1 — provider console key creation

## User action, batched

The agent navigates sequentially to the Supabase Secret Keys, DeepSeek,
OpenRouter, NVIDIA NIM, and Mistral key pages. The user performs only
login/2FA/captcha and clicks each Create button; the user then places each
issued or recovered key in local `.env`. The Supabase key must be stored as
`SUPABASE_SECRET_KEY` and is used only by the bus/executor queue client.

## Constraints

- Free tiers only. Do not purchase or enter billing data; the direct DeepSeek
  lane is available, so no OpenRouter upgrade is needed.
- Never place a Supabase publishable key in `SUPABASE_SECRET_KEY`; the queue
  intentionally rejects it.
- The direct DeepSeek key is missing despite the completed top-up. Recover or
  create its API key and store it as `DEEPSEEK_API_KEY`; keep
  `DEEPSEEK_VIA_OPENROUTER` false/unset.
- NVIDIA may require Developer Program signup and email verification before its
  key page.
- Never display or retain a newly issued key outside local `.env`.
- After all three pages are complete, verify variable presence only and then
  dispatch L4 while Meta Stop 2 preparation continues.
