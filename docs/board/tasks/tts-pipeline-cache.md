---
id: tts-pipeline-cache
status: done
lane: AUTO
priority: 1
phase: 3
blocked-on: none
files: voice/speak.py, tests/voice/test_speak.py, executor/poller.py, tests/executor/test_poller.py, conftest.py
resources: none
---

# tts-pipeline-cache — build Kokoro once, and before the first voice note

## Goal

`voice/speak.py:synthesize` constructed a fresh `KPipeline` on every call.
Measured 4 Sep 2026: `import kokoro` 18.5 s, `KPipeline()` 5.3 s, the
render itself 2.7-3.1 s for 7.6 s of speech. So every voice reply paid ~5 s
of construction on top of the render, and the first after a worker restart
paid 25-100 s.

## Log

**4 Sep 2026 — done, CORE inline.**

- `voice/speak.py`: one pipeline per process behind a lock, keyed on the
  `KPipeline` class so an injected test fake never leaks into the next
  test; `warm_up()` and `reset_pipeline_cache()`.
- `executor/poller.py`: `main()` starts a daemon `tts-warm-up` thread when
  the process owns `whatsapp_webhook` and is not `--once`. Best-effort,
  logged, `JARVIS_TTS_WARM_UP=0` disables. The repo-root `conftest.py`
  sets that to `0` for the whole offline suite so no test imports torch.

Measured with the cache (probe in the audit): synth #1 3.1 s, #2 2.7 s,
#3 2.8 s for the same 7.6 s clip, against 7.4-7.6 s per call before.

```
.venv\Scripts\python.exe -m pytest -q tests/executor/test_poller.py tests/voice/test_speak.py
77 passed in 4.40s
```
