---
id: provider-status-generator
status: ready
lane: AUTO
priority: 3
phase: 0
blocked-on: none
files: tools/provider_status.py (new), tests/tools/test_provider_status.py (new), docs/state.md, router/providers.yaml
resources: none offline
---

# provider-status-generator — stop hand-writing which providers work

## Goal

Blueprint §3.3, Ali's text: `providers.yaml` and `docs/state.md` "are
generated from the running config, not maintained by hand here", and
"`docs/state.md` carries two lists: **routable**, and
**configured-but-not-routable with a reason and a date** per entry."

Both lists are hand-written prose today. No generator exists.

`blueprint-corrections` deliberately did **not** hand-write them on 2 Sep:
§3.3 says they are generated, and hand-maintaining them would break the rule
in the act of obeying it. They are still missing on purpose, and this task is
what fills them.

## Why it matters more than it sounds

Two separate findings this week were both "a provider is configured and
cannot actually serve a request, and nothing says so":

- `groq` and `cerebras` sort to the front of every request and are silently
  skipped for an unresolvable model (`router-unresolvable-model-rungs`).
- `openrouter/free` answered a structured-output prompt with
  `User Safety: safe` on two of four probes (`enqueue-classifier`).

A generated configured-but-not-routable list with a reason and a date is
exactly the artefact that would have surfaced both without anyone probing.

## Steps

1. A tool that reads `router/providers.yaml`, the environment (key **names**
   only — never values), and the live provider-health snapshot
   (`router/health_report.py`, which the executor already writes) and emits
   the two lists with a reason and a date per entry.
2. Write into `docs/state.md` between generated markers, the same discipline
   `tools/context_status.py` uses for `docs/context.md`. Never hand-edit
   between the markers.
3. Reasons must distinguish at least: no key configured; key present but no
   resolvable model; in cooldown with a last status; never verified.
4. Coordinate with `router-unresolvable-model-rungs`, which needs the same
   "why is this rung unusable" vocabulary.

## Done when

`docs/state.md`'s provider lists are generated with a reason and a date per
entry, no hand-written provider list remains, and the suite is green.
