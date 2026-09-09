---
id: extraction-model-spike
status: done
lane: AUTO
priority: 3
phase: 1
blocked-on: none — but run-exclusive: needs the whole laptop, and never while Ali may be messaging the bot
files: docs/tasks/extraction-model-spike-report.md (new), tools/bench_extraction.py (new), tests/tools/test_bench_extraction.py (new)
resources: ollama-extract
---

# extraction-model-spike — is a 4B model on the GPU faster than the 8B on CPU?

## Why

Ali's 8 Sep memory answer keeps fact extraction on the laptop with "a
lighter, GPU-capable model" instead of `llama3.1:8b` on CPU (15-55 s per
chunk, `docs/blockers/mem0-extraction-not-schema-constrained.md`). Fable
§3: Ollama cannot use the Radeon 860M on Windows (upstream bug #14562), so
the credible path is `Qwen3-4B-Instruct-2507` on **llama.cpp with
Vulkan**, JSON-schema grammar. `ollama list` already shows `qwen3:4b`.
This spike produces the numbers; switching the model is a blueprint §1.3
change and Ali's (fold the numbers into Q14/Q17).

## Steps

1. `tools/bench_extraction.py`: takes a fixture set of synthetic chunks
   at the sizes the blocker measured (~96-768 words; **synthetic text
   only**, nothing from `ingest/data/` or the memory db), a backend
   (`ollama` | `llamacpp`), a model, and the existing fact schema; reports
   per-chunk wall time, valid-JSON rate, facts extracted. Unit-tested with
   a fake backend.
2. Control run: `llama3.1:8b` via Ollama, schema-constrained (`format=`
   schema) and unconstrained, so the comparison is against what the
   blocker saw.
3. Candidate: llama.cpp Vulkan build — prebuilt Windows binary from the
   upstream releases page, into `.tools/llama.cpp/` (gitignored), no
   from-source build. If the Vulkan device is not detected, record that
   and run CPU llama.cpp as a fallback measurement; do not spend an
   evening compiling. Qwen3-4B-Instruct GGUF Q4_K_M, grammar from the
   fact schema.
4. Same chunks, both, CPU% sampled during. Table in the report; one
   paragraph of recommendation; stop.

## Done when

Report written with a per-size table for both models and the CPU load;
`docs/state.md` gets one line pointing at it; Log cites the exact
commands. No runtime change, no model switch.

## Log

### 2026-09-09 — done (lane-1)

**Run-exclusive check before starting.** `tasklist` showed no `python.exe`
or `cloudflared.exe` running — the whatsapp-worker/bus stack was not up, so
there was no live reply path this benchmark could compete with or delay.
Claimed `ollama-extract`.

**Step 1 (`tools/bench_extraction.py`).** Backend-agnostic: `ollama` hits
`/api/chat` with `format=<schema|"json">`; `llamacpp` hits the
OpenAI-compatible `/v1/chat/completions` with `response_format`. Both cap
`num_predict`/`max_tokens` (default 800) — added after a live run showed why
that is load-bearing, not a nicety (see step 3). Schema reused directly from
`memory.mem0_wrapper.ExtractionResponse`, not reinvented. 18 unit tests
against fake `call` closures — no live Ollama/llama.cpp needed for the
offline suite. `httpx.MockTransport` proves both backends send the shape
their own API actually expects (schema under `format`/`response_format`,
the token cap under the right key).

**Step 2 (control).** `llama3.1:8b` via the already-running Ollama, both
modes, all four sizes, clean on the first pass — 100% valid JSON both ways
(does not reproduce the blocker's own unconstrained-JSON failure, because
that failure was the *prompt's* 33.6k-char size, already fixed separately
in `mem0_wrapper.py`, not the model; explained in the report so the two
don't get conflated later).

**Step 3 (candidate) — the real work of this task.** `ollama list` already
had `qwen3:4b` pulled; its blob is a raw GGUF (`head -c4` = `GGUF`,
`Q4_K - Medium` per `llama-cli`'s own banner) — reused directly rather than
re-downloading 2.5 GB from HuggingFace. Fetched `llama.cpp` b10868's
prebuilt `win-vulkan-x64` release (34 MB) into `.tools/llama.cpp/`
(`.gitignore` gained a `.tools/` entry). Vulkan device detected:
`AMD Radeon(TM) 860M Graphics`.

Two real bugs found live, both worked around, both now documented in the
report and this Log rather than silently papered over:

1. **Qwen3's chat template forces a `<think>` prefix that is incompatible
   with strict JSON-schema-grammar decoding.** `llama-cli` refuses outright
   (`Unexpected empty grammar stack after accepting piece: <|im_start|>`);
   `llama-server`'s HTTP path doesn't refuse, it degrades — generation
   collapses from ~12 tok/s to under 1 tok/s within a few hundred tokens,
   reproduced on a freshly restarted server's very first request, three
   times, both Vulkan and CPU. Neither `--reasoning off` nor
   `--reasoning-budget 0` nor an in-message `/no_think` fixed it — the
   prefix is inserted before any of those apply. Worked around with
   `llama-completion.exe` (untemplated raw completion, shipped in the same
   release), which produced clean schema-valid JSON at a normal rate. The
   numbers in the report all come from this workaround; the
   `llamacpp_call` path in `tools/bench_extraction.py` still targets the
   templated chat endpoint, which would hit this same bug in a real
   integration — noted as unattempted follow-up, not silently fixed by
   changing what the tool measures.
2. **`ExtractionResponse.memory` has no `maxItems`.** An early attempt with
   no generation cap ran past 1,500 tokens before being killed by hand —
   the grammar's array production never closes on its own if the model
   doesn't choose to stop, and nothing bounded it. `--max-tokens` (default
   800) is the fix, and it is the reason `run_chunk`/`ollama_call`/
   `llamacpp_call` all take it as a required lever rather than an
   afterthought — covered by
   `test_ollama_call_caps_generation_length` / `test_llamacpp_call_caps_generation_length`.

**`-ngl 99` (full GPU offload) genuinely OOMs** on this iGPU despite
`--list-devices` reporting 15.7 GB free — it shares system RAM, and the
free figure is optimistic. `-ngl 20 -c 4096` was the largest configuration
that ran cleanly.

**Result: the control won at every size.** `llama3.1:8b`/Ollama/CPU beat
Qwen3-4B/llama.cpp/CPU-or-Vulkan on wall time at every chunk size tested —
the opposite of the blueprint's Q17 performance-note expectation. Full
tables, fact counts, and the CPU-load numbers are in
`docs/tasks/extraction-model-spike-report.md`. **No model switch made** —
the task's own "Done when" and CLAUDE.md's decision-boundary both require
that to stay Ali's, and the numbers argue against it today regardless.

**Cleanup.** `.tools/llama.cpp/`'s server and completion processes were all
killed before finishing; `tasklist`/`ps aux` confirmed nothing left running
beyond Ollama's own always-on service, which was there before this task and
is left as it was. Scratch prompt/schema files written to the repo root
during debugging were deleted, not committed.

**Full offline suite.**

```
$ .venv/Scripts/python.exe -m pytest -q --basetemp=.pytest-basetemp-lane-1
1679 passed, 10 deselected in 89.37s (0:01:29)
```

1661 -> 1679: 18 new `tests/tools/test_bench_extraction.py` tests, all
against fakes.
