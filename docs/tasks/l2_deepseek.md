# L2 follow-up — direct DeepSeek rung proof

## Ownership

You may edit only `router/` and `tests/router/`. Do not commit. Do not edit
`docs/context.md`; report to the orchestrator. Never reveal a credential or
raw provider response that may include one.

## Preconditions

`DEEPSEEK_API_KEY` is now configured locally and `DEEPSEEK_VIA_OPENROUTER` is
false/unset. The router has already been corrected to use `deepseek-v4-flash`.

## Objective

Run one minimal direct DeepSeek request through the real configured rung.
Confirm a 200-class result, dynamic response-header cooldown capture, and that
the router does not use the OpenRouter proxy. Use current official DeepSeek
documentation for any model/endpoint claim. Add or adjust focused tests only
if a real defect is found. Report concise pass/fail and safe error details.
