# L2 follow-up — configure the Mistral router rung

## Ownership

You may edit only `router/` and `tests/router/`. Do not commit. Do not edit
`docs/context.md`; report to the orchestrator. Never reveal credentials.

## Objective

Mistral is configured locally but absent from `router/providers.yaml`, so it
cannot participate in fallback routing. Add a Mistral OpenAI-compatible rung
using the current official endpoint and a model-selection strategy that does
not hardcode a free model ID. Preserve dynamic rate-limit header handling and
existing profile/fallback behavior. Add focused tests under `tests/router/`.

The current key can discover models but its minimal free Labs chat call returns
403. Do not solve that by hardcoding a paid model, changing account settings,
or weakening errors; mark the provider unavailable/cool down correctly and
report the safe failure. NVIDIA is out of scope and deferred.
