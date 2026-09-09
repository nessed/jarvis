# extraction-model-spike — is Qwen3-4B on llama.cpp Vulkan faster than llama3.1:8b on CPU?

Run 9 Sep 2026. Synthetic chunks only, per the task's own constraint — nothing
here reads `ingest/data/` or the memory database. Tool:
`tools/bench_extraction.py`; schema: the real
`memory.mem0_wrapper.ExtractionResponse`, not one invented for this spike.

## Recommendation, first

**Do not switch today.** The control (`llama3.1:8b` on CPU via Ollama) is
faster than the candidate at every chunk size, not slower — the opposite of
what the blueprint's Q17 performance note expected. The candidate also hit a
real, reproducible correctness bug along the way (below) that has to be
worked around, not just accepted. Qwen3-4B is a real 4B model running on a
real Vulkan-capable iGPU; the numbers below say the *specific pairing* of
this model's chat template with grammar-constrained decoding, on this
llama.cpp build, isn't the win the blueprint assumed. Two things are worth
someone's time before this gets revisited: whether a llama.cpp release past
b10868 fixes the template/grammar conflict, and whether Qwen3-4B without any
GPU offload at all is still worth it once the conflict is worked around
(steady-state numbers below say no, at these context lengths).

## What was actually measured

Four synthetic chunks at the blocker's own sizes
(`docs/blockers/mem0-extraction-not-schema-constrained.md`): 96, 288, 480,
768 words. Every run capped generation at 800 tokens
(`--max-tokens`, `tools/bench_extraction.py`'s `DEFAULT_MAX_TOKENS`) — found
necessary live, see "Bug found" below.

### Control: `llama3.1:8b`, Ollama, CPU (this laptop has no GPU path for it — bug #14562)

Schema-constrained (`format=<schema>`):

| words | seconds | valid | facts |
|---|---|---|---|
| 96  | 56.0 | yes | 9 |
| 288 | 45.0 | yes | 11 |
| 480 | 92.1 | yes | 15 |
| 768 | 71.4 | yes | 16 |

Unconstrained (`format="json"`):

| words | seconds | valid | facts |
|---|---|---|---|
| 96  | 37.4 | yes | 9 |
| 288 | 56.0 | yes | 11 |
| 480 | 59.7 | yes | 11 |
| 768 | 81.9 | yes | 14 |

Both modes: 100% valid JSON, every size. This does **not** reproduce the
blocker's own "unconstrained fails on real chunk sizes" finding — expected,
and worth being explicit about why: that failure was specific to Mem0's
shipped 33,661-character extraction prompt costing most of a timeout budget
before the model even started answering
(`memory/mem0_wrapper.py`'s `COMPACT_ADDITIVE_EXTRACTION_PROMPT` comment).
This benchmark's system prompt is a few hundred characters, deliberately —
it measures the *model's* extraction behavior at a given input size, not the
already-separately-fixed prompt-size pathology. Compare the two constrained
tables' *shapes*, not this one's success rate, to that blocker.

### Candidate: Qwen3-4B-Instruct-2507 (Q4_K_M), llama.cpp b10868

Confirmed live, not assumed: `ollama list` already had `qwen3:4b` pulled (2.5
GB), and its blob (`~/.ollama/models/blobs/sha256-3e4c...4e4f`) is a raw GGUF
file — `head -c4` reads `GGUF`, `llama-cli`'s own banner reports
`ftype: Q4_K - Medium`. Reused directly; no second multi-GB download. The
Vulkan device is detected and named: `Vulkan0: AMD Radeon(TM) 860M Graphics
(16525 MiB, 15699 MiB free)` (`llama-cli --list-devices`).

**Bug found, and worked around: Qwen3's chat template is incompatible with
strict JSON-schema-grammar decoding, on this build.** Every attempt through
`llama-server`'s OpenAI-compatible endpoint or `llama-cli`'s chat mode
failed one of two ways:

- `llama-cli` (chat mode) refused outright: `Failed to initialize samplers:
  Unexpected empty grammar stack after accepting piece: <|im_start|>
  (151644)`. The template unconditionally injects
  `<|im_start|>assistant\n<think>\n` before generation starts; the JSON
  schema's root production requires `{` as the first character. Neither
  `--reasoning off`, `--reasoning-budget 0`, nor an in-message `/no_think`
  changed this — the prefix is inserted before any of those have a say.
- `llama-server` didn't refuse; it degenerated instead. Generation started
  at a plausible rate (~11-13 tok/s) and collapsed to **under 1 tok/s**
  within 150-400 generated tokens, every time, including on a freshly
  restarted server processing its very first request — not a warm-up
  artifact, not request-queue contention. Read as the same root conflict:
  the sampler fighting an unsatisfiable grammar-vs-template constraint,
  expensively, rather than failing fast the way the CLI does. Reproduced
  three times (Vulkan `-ngl 20`, Vulkan `-ngl 20 -c 4096`, CPU `-ngl 0`),
  logged in each case as `tg_3s` collapsing toward `0.0x t/s` in
  `llama_server`'s own `print_timing` lines.

**Workaround: `llama-completion.exe`** (shipped in the same release,
untemplated raw completion — no `<|im_start|>` wrapping at all) with the
same `--json-schema-file` produces clean, schema-valid JSON at a normal
rate. This is what every number below comes from. Whether the same fix is
available through the OpenAI-compatible server endpoint (a custom chat
template without the forced `<think>` open, or a newer llama.cpp release)
was not checked — out of scope for one spike.

**A second bug, found and worked around the same way this benchmark's own
tests now cover:** `ExtractionResponse.memory` carries no `maxItems`. Under
grammar constraint with no generation cap, the sampler kept the array
production open past 1,500+ tokens in one early attempt before it was
killed by hand — the grammar doesn't bound list length and nothing was
capping the response. `--max-tokens` (default 800,
`tools/bench_extraction.py`) is the fix, covered by
`test_ollama_call_caps_generation_length` /
`test_llamacpp_call_caps_generation_length`.

CPU (`-ngl 0`), schema-constrained, via `llama-completion.exe`:

| words | seconds (load+infer) | tok/s (gen) | valid | facts |
|---|---|---|---|---|
| 96  | 54.8 | 4.20 | yes | 5 |
| 288 | 62.7 | 5.90 | yes | 8 |
| 480 | 71.1 | 5.63 | yes | 8 |
| 768 | 49.6 | 8.35 | yes | 8 |

Vulkan (`-ngl 20`, partial offload — full `-ngl 99` OOMs this iGPU's shared
memory at default context, see below), schema-constrained:

| words | seconds (load+infer) | tok/s (gen) | valid | facts |
|---|---|---|---|---|
| 96  | 24.8 | 10.82 | yes | 5 |
| 768 | 86.6 | 4.32  | yes | 8 |

(Only two Vulkan sizes run — by the second, over an hour of sustained
GPU load into this session, generation had slowed to roughly CPU speed
rather than the ~2x the 96-word point showed. Plausibly thermal throttling
on a laptop iGPU under sustained compute rather than a fixed property of
the setup; not chased further, so read this row as "GPU help is inconsistent
here," not "GPU offload is worthless.")

**`-ngl 99` (full offload) genuinely OOMs**, not a config mistake:
`ggml_vulkan: Device memory allocation of size 1060110336 failed... Error
OutOfDeviceMemory`, despite `--list-devices` reporting 15.7 GB free. The
860M is an integrated GPU sharing system RAM; the reported "free" figure is
optimistic. `-ngl 20 -c 4096` is the largest configuration that ran cleanly
in this session's testing.

## Fact counts, read carefully

Qwen3-4B's counts (5/8/8/8) are lower than `llama3.1:8b`'s (9-16) at every
size, and 288/480/768 all landed on exactly 8 — a `--max-tokens 800`
generation cap is the likely reason, not the model finding fewer facts: the
CPU 480-word run's `eval` line reports exactly 336 generated tokens each
time for 288/480/768, suggesting something (context accounting at `-c 2048`,
or the grammar closing the array early under budget pressure) truncates the
list before 800 real tokens are spent, consistently. This was not run down
further — a `--max-tokens` high enough to rule it out, plus reading the
*specific* facts kept vs. dropped, is the next step if this candidate is
revisited rather than shelved.

## CPU load

`cpu_percent_avg` from `tools/bench_extraction.py`'s sampler, system-wide:
Ollama's `llama3.1:8b` runs pinned near 100% CPU across all four sizes and
both modes (it is the only heavy process; expected for a CPU-only 8B model
with no other contention). Qwen3-4B's CPU-only runs were not sampled through
the tool (measured via `llama-completion.exe` directly, outside the
harness, once the server path proved unusable) — `llama-completion`'s own
`n_threads = 8` line confirms it used all available cores the same way.

## What was not attempted

- A llama.cpp release newer than b10868 (the latest Vulkan Windows build as
  of 9 Sep 2026), to see if it fixes the template/grammar conflict.
- Routing the fix (raw completion, no chat template) through
  `llama-server`'s HTTP API rather than a one-off CLI process per chunk —
  `tools/bench_extraction.py`'s `llamacpp_call` still targets the
  OpenAI-compatible chat endpoint, which is what a real integration would
  need; today it would hit the same template bug found here.
- A from-source llama.cpp build. Explicitly out of scope per the task.

## Commands run

```
$ ollama list
llama3.1:8b       46e0c10c039e    4.9 GB
qwen3:4b          359d7dd4bcda    2.5 GB
nomic-embed-text  0a109f422b47    274 MB

$ curl -s https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=15
  -> b10868, llama-b10868-bin-win-vulkan-x64.zip

$ .venv/Scripts/python.exe -m tools.bench_extraction --backend ollama \
    --model llama3.1:8b --base-url http://127.0.0.1:11434 --json
$ .venv/Scripts/python.exe -m tools.bench_extraction --backend ollama \
    --model llama3.1:8b --base-url http://127.0.0.1:11434 --unconstrained --json

$ .tools/llama.cpp/llama-completion.exe -m <qwen3:4b's ollama blob> \
    -f <prompt file> -n 800 -ngl 0 -c 2048 --json-schema-file <schema file>
$ .tools/llama.cpp/llama-completion.exe -m <same> \
    -f <prompt file> -n 800 -ngl 20 -c 2048 --json-schema-file <schema file>
```

Offline suite: `.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-basetemp-lane-1`
— `tools/bench_extraction.py`'s 18 unit tests run against fakes, no live
Ollama or llama.cpp process. See the task's Log for the full-suite citation.
