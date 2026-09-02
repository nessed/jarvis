---
id: offline-suite-network-leak
status: ready
lane: AUTO
priority: 2
phase: 0
blocked-on: none
files: tests/status/test_live_queue_status.py, bus/main.py (hot), tests/test_integration.py
resources: none offline
---

# offline-suite-network-leak — four "offline" tests build a live Supabase client

## Goal

The offline suite is the gate on every commit. Four of its tests reach the
internet, so a bad connection turns it red and the failure reads exactly like
a regression in whatever else changed that hour.

Found 3 Sep 2026 by `board-audit`, from a real pre-commit refusal:

```
FAILED tests/status/test_live_queue_status.py::test_status_reports_a_cooldown_the_executor_recorded
FAILED tests/status/test_live_queue_status.py::test_status_says_unreported_rather_than_healthy_when_nothing_has_routed
FAILED tests/status/test_live_queue_status.py::test_status_still_lists_the_whole_provider_ladder_when_unreported
FAILED tests/status/test_live_queue_status.py::test_a_provider_the_reporter_knows_but_the_manifest_does_not_is_kept

E   httpx.ConnectTimeout: _ssl.c:993: The handshake operation timed out
4 failed, 1357 passed, 9 deselected in 148.33s
```

The same suite had passed `1361 passed ... in 77.33s` ninety seconds earlier
and passed again immediately after. The doubled runtime is the tell: those are
network timeouts, not assertions.

## The mechanism, confirmed not guessed

Those four tests call `create_app(...)` passing `queue_depths` and `last_job`
as lambdas, but **not** `jobs`. `bus/main.py:107`:

```python
active_jobs = jobs if jobs is not None else _default_jobs()
```

and `_default_jobs()` is `SupabaseJobsRepository.from_env()`, which calls
`create_client(url, key)` against the real project URL in `.env`. Every one of
those four builds a live client it then never uses — they inject the two
readers they actually exercise.

The `DeprecationWarning: The 'timeout' parameter is deprecated` lines from
`supabase/_sync/client.py` in every run of this file are the same fact,
visible in the passing case.

## Why it matters more than four tests

This repository has now lost time three times to a red suite that was not a
regression:

- two lanes sharing one `--basetemp` (fixed, `pytest-addopts`),
- `.git` owned by another Windows account (**U13**, open),
- and this.

Each one reads as a flaky test and is not. The offline suite's whole value is
that red means broken; anything that makes red mean "maybe the wifi" costs
more than the test is worth.

## Steps

1. Pass an explicit fake `jobs=` in the four tests, so no live client is built.
   The file already has `FakeSupabaseRepository`; this is the cheapest fix and
   should be done first regardless of step 2.
2. Decide whether `create_app`'s `_default_jobs()` fallback should stay. It is
   right for production and a trap in tests. Options: keep it and require every
   test to inject, or make the fallback lazy so an app that never touches the
   queue never builds a client. Lazy is more invasive and changes startup
   behaviour, so say which and why before doing it.
3. Sweep the rest of the offline suite for the same shape — anything calling
   `from_env()`, `create_client`, or `create_app` without `jobs=`. Check
   `tests/test_integration.py`, which shows the same Supabase deprecation
   warnings.
4. Consider a guard that makes the leak impossible to reintroduce: a fixture
   that fails any offline test which opens a socket. That is the only version
   of this fix that holds, since step 1 is one `git commit` away from being
   undone by someone adding the fifth test.

## Done when

No test in the default suite constructs a Supabase client or opens a socket;
cite a run with the network disabled or a socket guard in place.
