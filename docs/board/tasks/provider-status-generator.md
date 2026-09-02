---
id: provider-status-generator
status: done
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

## Log

### 2 September 2026 — done. The lists are generated, and the hand-written table is gone.

### What it reads, and the one thing it must not

`tools/provider_status.py` takes three inputs: `router/providers.yaml`, the
environment, and the live health snapshot `router/health_report.py` publishes.

**Environment key names only.** It decides whether a variable is set and never
reads what it holds. That is not general caution — this tool writes into a file
that gets committed, so a value reaching the block would be a value reaching
the repository. A test drives it with deliberately secret-looking values and
asserts none appear, while asserting the variable *names* do, since naming the
missing var is the entire content of the reason.

### Step 3's vocabulary, and step 4's coordination

The reason strings come from `ProviderRouter.unroutable_reasons()`, which
`router-unresolvable-model-rungs` added a few hours earlier for exactly this.
The two cannot drift apart, because there is only one of them. That was step 4,
and it happened in the right order: the router task built the data and
explicitly did not invent the presentation, and this task built the
presentation without re-deriving the data.

Step 3 asked the reasons to distinguish at least four cases. They do:

```
no API key in NVIDIA_API_KEY
no model: its default_model placeholder is unset in .env
no model: MISTRAL_DEFAULT_MODEL is unset
in cooldown, 42s left after HTTP 429
never verified — no request has reached it in this reporting window
```

The last two are added here rather than in the router. A cooling rung **is**
routable and merely resting, so it belongs in the first list with its
countdown, not the second. And "never verified" is its own state, not silence:
a rung with a key, a model and no cooldown is indistinguishable from a working
one right up until the first request, and §3.3 names that distinction.

### What it produces, live

```
Routable
| `openrouter` | free | never verified — no request has reached it in this reporting window |
| `mistral`    | free | never verified — no request has reached it in this reporting window |
| `deepseek`   | paid | never verified — no request has reached it in this reporting window |

Configured but not routable
| `groq`       | free  | no model: its default_model placeholder is unset in .env |
| `cerebras`   | trial | no model: its default_model placeholder is unset in .env |
| `nvidia_nim` | free  | no API key in NVIDIA_API_KEY |
| `gemini`     | free  | no model: its default_model placeholder is unset in .env |
| `claude_max` | paid  | not a router target |
| `claude_api` | paid  | no endpoint configured |
```

This is the artefact the task said was missing. Three rungs sat at the front of
every request unserved for days, and the fact was recorded only in a failure
list rendered when everything failed. It now reads off a table.

### Two deliberate limits

**Not wired into the pre-commit hook**, unlike `tools/context_status.py`. The
state column reads a snapshot that changes between requests, so staging it
would put an ephemeral cooldown countdown into every commit — noise in every
diff, for a number that is wrong by the time anyone reads it. The generation
date in the block is how a reader judges its age instead.

**`--check` does not byte-compare against a fresh render**, for the same
reason: it would fail constantly and teach everyone to ignore it, which is the
failure `context_status.py` documents at length. It checks the block exists and
still has the shape the tool produces, which catches what actually goes wrong —
someone editing it by hand.

### The hand-written list is gone

`docs/state.md`'s nine-row rung table is deleted, along with the long
`*_DEFAULT_MODEL` gap note, which described `routing.py:246-257` as it was
before `router-unresolvable-model-rungs` rewrote it and is now both stale and
derivable. What survives outside the markers is only what no generator can
derive: Ali's Q5 model IDs, the DeepSeek account fact, NIM's geo-block, and
Cerebras' 402. A test asserts no markdown table remains in that section outside
the markers.

### Verification

```
.venv\Scripts\python.exe tools/provider_status.py --write
refreshed the provider lists in docs\state.md
.venv\Scripts\python.exe tools/provider_status.py --check   # exit 0

.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-lane-1
1359 passed, 9 deselected, 10 warnings in 72.25s
```

Thirteen tests, all driving an explicit environment and snapshot so none can be
coloured by the real `.env`, plus two that read the committed document — one
for the block's shape, one asserting no hand-written table survived.
