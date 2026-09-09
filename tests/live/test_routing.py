r"""Phase 0 acceptance probe: which configured provider rungs actually serve.

`docs/state.md`'s Groq/Gemini "working" claims are unverified under the
model IDs Ali pasted 1 Sep (U2), `tests/live/` has zero routing coverage,
and DeepSeek's credit top-up was never independently confirmed. One tiny
real completion per rung, through the real `ProviderRouter.route()` path
(not a fake), settles all three.

Run it explicitly (the default suite excludes ``live``):

    .venv\Scripts\python.exe -m pytest -q -m live tests/live/test_routing.py -s

Requires the five real API keys already in `.env` (never read or printed
here — a missing key just means that rung's own test fails honestly).
**Spends real provider allowance.** Every call asks for one word back
(`max_tokens` where the SDK accepts it) to keep that cost near zero; this
is exactly why the task claims the `provider-account` resource
(`docs/plan.md`) before running.

Each test builds its own single-provider `ProviderRouter` (`providers=[…]`)
rather than going through `shared_router()`/the full ladder: the point is
"does this specific rung work", not "which rung does the ladder pick
today" — a working `groq` would otherwise mask a broken `gemini` simply by
being priority 1.
"""

from __future__ import annotations

import asyncio

import pytest
from dotenv import load_dotenv

from router.routing import (
    NoEligibleProvider,
    Provider,
    ProviderRouter,
    load_providers,
)

# router/routing.py never calls this itself (only bus/main.py and
# memory/runtime.py do, for their own entrypoints) -- without it,
# load_providers()'s default os.environ read sees none of the keys or
# model IDs in .env, and every rung looks unconfigured.
load_dotenv()

PROBE_MESSAGES = [{"role": "user", "content": "Reply with exactly one word: pong"}]

# Rungs the blueprint expects to actually answer, as of the 8 Sep Fable
# review's provider facts and U2's pasted model IDs. Each maps to the task
# profile it is actually meant to serve (providers.yaml's own
# `task_profiles`), because the profile picks the call's timeout budget
# (`JARVIS_ROUTER_CALL_TIMEOUT_SECONDS` for `latency`, the longer batch one
# otherwise) -- `deepseek` is declared `["batch", "long_context",
# "reasoning"]`, never `latency`, and it needs the room: V4-Flash has
# thinking on by default (state-facts-refresh, 9 Sep 2026), which burned
# the tight `latency` budget without ever reaching a reply on the first
# live run of this test.
EXPECTED_TO_SERVE = (("groq", "latency"), ("gemini", "latency"), ("openrouter", "latency"), ("deepseek", "batch"))

# 300, not a tighter number: found live on the same first run -- Groq's
# `openai/gpt-oss-120b` is a reasoning model too, and a smaller budget
# (5, then 20) was spent entirely on its `reasoning` field, leaving
# `finish_reason="length"` and an empty `content`. This is the number that
# reaches an actual answer, not a guess at politeness.
PROBE_MAX_TOKENS = 300


def _provider(name: str) -> Provider:
    matches = [p for p in load_providers() if p.name == name]
    if not matches:
        pytest.fail(f"{name!r} is not in router/providers.yaml at all -- the manifest itself has drifted")
    return matches[0]


def _solo_router(name: str) -> ProviderRouter:
    """A router that can only ever try one rung -- no fallback to hide behind."""
    return ProviderRouter(providers=[_provider(name)])


@pytest.mark.live
@pytest.mark.parametrize("name, task_profile", EXPECTED_TO_SERVE)
def test_a_configured_rung_actually_serves(name: str, task_profile: str, record_property) -> None:
    router = _solo_router(name)

    result = asyncio.run(router.route(task_profile, PROBE_MESSAGES, urgent=True, max_tokens=PROBE_MAX_TOKENS))

    assert result.provider == name
    reply = result.response.choices[0].message.content
    assert isinstance(reply, str) and reply.strip(), f"{name} returned an empty reply"

    health = router.health[name]
    record_property(f"{name}_model", result.model)
    record_property(f"{name}_last_status", health.last_status)
    record_property(f"{name}_rate_limit_headers", dict(health.rate_limit_headers))
    print(f"\n{name}: model={result.model!r} status={health.last_status} reply={reply.strip()!r}")
    print(f"  rate-limit headers: {dict(health.rate_limit_headers)}")


@pytest.mark.live
def test_cerebras_is_excluded_by_its_deliberately_blank_model_not_by_accident() -> None:
    """Q6: `CEREBRAS_DEFAULT_MODEL` is blank on purpose, so the rung should be
    skipped as unroutable -- never actually called, never a 402."""
    router = _solo_router("cerebras")

    reasons = router.unroutable_reasons()
    assert "cerebras" in reasons, "cerebras is routable -- CEREBRAS_DEFAULT_MODEL may no longer be blank; re-check Q6"
    assert "model" in reasons["cerebras"].lower(), (
        f"cerebras excluded for an unexpected reason ({reasons['cerebras']!r}) "
        "-- expected a model-resolution reason, e.g. a missing API key would mean "
        "something else broke first"
    )

    with pytest.raises(NoEligibleProvider):
        asyncio.run(router.route("latency", PROBE_MESSAGES, urgent=True))


@pytest.mark.live
def test_mistral_reports_its_current_state_whichever_it_is(record_property) -> None:
    """U9: Mistral chat has been returning 403 (workspace-limit unknown).
    Report whichever actually happens rather than hardcoding the failure --
    a router test that only accepts today's known-bad outcome would itself
    go stale the moment U9 is resolved."""
    router = _solo_router("mistral")

    try:
        result = asyncio.run(router.route("latency", PROBE_MESSAGES, urgent=True, max_tokens=PROBE_MAX_TOKENS))
    except NoEligibleProvider as exc:
        health = router.health["mistral"]
        record_property("mistral_outcome", "denied")
        record_property("mistral_last_status", health.last_status)
        print(f"\nmistral: denied ({type(exc).__name__}: {exc}), last_status={health.last_status}")
    else:
        record_property("mistral_outcome", "served")
        record_property("mistral_model", result.model)
        print(f"\nmistral: served -- model={result.model!r} (U9 may be resolved; re-check its Log)")
