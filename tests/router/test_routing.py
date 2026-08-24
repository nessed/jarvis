import asyncio
from datetime import UTC, datetime

import pytest

from router import NoEligibleProvider, Provider, ProviderRequestError, ProviderRouter, load_providers


class FakeClient:
    def __init__(self, provider, outcomes, calls):
        self.provider = provider
        self.outcomes = outcomes
        self.calls = calls

    async def create_chat_completion(self, *, model, messages, **kwargs):
        self.calls.append((self.provider, model))
        outcome = self.outcomes.get(self.provider, {"provider": self.provider})
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def providers(names):
    return [
        Provider(
            name=name,
            endpoint=f"https://{name}.example/v1",
            key_env=f"{name.upper()}_KEY",
            priority=index,
            default_model=f"{name}-configured-model",
            task_profiles=("latency", "batch", "long_context", "vision", "reasoning"),
        )
        for index, name in enumerate(names, start=1)
    ]


def router_for(names, outcomes, *, now=None, environ=None):
    calls = []
    env = environ or {f"{name.upper()}_KEY": "test-key" for name in names}
    endpoint_to_name = {f"https://{name}.example/v1": name for name in names}

    def factory(endpoint, api_key):
        assert api_key == "test-key"
        return FakeClient(endpoint_to_name[endpoint], outcomes, calls)

    return (
        ProviderRouter(providers(names), environ=env, client_factory=factory, now=now),
        calls,
    )


def test_manifest_has_eight_ordered_rungs_and_safe_model_configuration():
    manifest = load_providers(environ={})
    assert [provider.name for provider in manifest] == [
        "groq",
        "cerebras",
        "nvidia_nim",
        "gemini",
        "openrouter",
        "deepseek",
        "claude_max",
        "claude_api",
    ]
    assert manifest[6].not_a_router_target
    assert manifest[7].emergency_only and manifest[7].capped
    assert manifest[4].default_model == "openrouter/free"
    # Provider-specific free model IDs are supplied through runtime env vars.
    assert manifest[0].default_model is None


def test_429_cascade_lands_on_every_successive_rung():
    # This mirrors the real eight-rung ladder: Claude Max is intentionally
    # skipped, while the capped Claude API rung is available only for the
    # explicit emergency case used in this fallback test.
    all_rungs = providers(
        ["groq", "cerebras", "nvidia_nim", "gemini", "openrouter", "deepseek", "claude_max", "claude_api"]
    )
    all_rungs[6] = Provider(
        **{**all_rungs[6].__dict__, "not_a_router_target": True}
    )
    all_rungs[7] = Provider(
        **{**all_rungs[7].__dict__, "emergency_only": True, "capped": True}
    )
    names = [provider.name for provider in all_rungs if not provider.not_a_router_target]
    environ = {f"{provider.name.upper()}_KEY": "test-key" for provider in all_rungs}
    endpoint_to_name = {provider.endpoint: provider.name for provider in all_rungs}

    for landing_index, landing in enumerate(names):
        outcomes = {
            name: ProviderRequestError("limited", 429, {"retry-after": "1"})
            for name in names[:landing_index]
        }
        calls = []

        def factory(endpoint, api_key):
            assert api_key == "test-key"
            return FakeClient(endpoint_to_name[endpoint], outcomes, calls)

        router = ProviderRouter(all_rungs, environ=environ, client_factory=factory)

        result = asyncio.run(
            router.route("latency", [{"role": "user", "content": "hi"}], urgent=True, emergency=True)
        )

        assert result.provider == landing
        assert [provider for provider, _ in calls] == names[: landing_index + 1]


def test_cooldown_uses_response_headers_and_skips_limited_rung():
    router, calls = router_for(
        ["first", "second"],
        {
            "first": ProviderRequestError(
                "limited", 429, {"Retry-After": "13", "X-RateLimit-Remaining": "0"}
            )
        },
    )

    first = asyncio.run(router.route("batch", [{"role": "user", "content": "hi"}]))
    second = asyncio.run(router.route("batch", [{"role": "user", "content": "again"}]))

    assert first.provider == "second"
    assert second.provider == "second"
    assert [provider for provider, _ in calls] == ["first", "second", "second"]
    health = router.health["first"]
    assert health.cooldown_until > 0
    assert health.rate_limit_headers == {"retry-after": "13", "x-ratelimit-remaining": "0"}


def test_server_error_also_cools_down_and_falls_through():
    router, _ = router_for(
        ["first", "second"],
        {"first": ProviderRequestError("upstream failure", 503, {"x-ratelimit-reset-requests": "9"})},
    )

    result = asyncio.run(router.route("vision", [{"role": "user", "content": "image"}]))

    assert result.provider == "second"
    assert router.health["first"].rate_limit_headers == {"x-ratelimit-reset-requests": "9"}


def test_profiles_prefer_suitable_rungs_without_losing_priority_order():
    configured = [
        Provider("fast", "https://fast", "FAST_KEY", 1, "fast-model", ("latency",)),
        Provider("vision", "https://vision", "VISION_KEY", 2, "vision-model", ("vision",)),
        Provider("general", "https://general", "GENERAL_KEY", 3, "general-model", ("batch",)),
    ]
    router = ProviderRouter(
        configured,
        environ={"FAST_KEY": "x", "VISION_KEY": "x", "GENERAL_KEY": "x"},
        client_factory=lambda *_: None,
    )

    assert [provider.name for provider in router.ordered_providers("vision")] == ["vision", "fast", "general"]
    assert [provider.name for provider in router.ordered_providers("latency")] == ["fast", "vision", "general"]


def test_deepseek_waits_during_peak_unless_urgent():
    configured = [
        Provider("deepseek", "https://deepseek", "DEEPSEEK_API_KEY", 1, "deepseek-v4-flash", ("reasoning",)),
        Provider("spare", "https://spare", "SPARE_KEY", 2, "spare-model", ("reasoning",)),
    ]
    now = lambda: datetime(2026, 8, 23, 1, 30, tzinfo=UTC)
    router = ProviderRouter(
        configured,
        environ={"DEEPSEEK_API_KEY": "x", "SPARE_KEY": "x"},
        client_factory=lambda *_: None,
        now=now,
    )

    assert [provider.name for provider in router.ordered_providers("reasoning")] == ["spare"]
    assert [provider.name for provider in router.ordered_providers("reasoning", urgent=True)] == ["deepseek", "spare"]


def test_deepseek_openrouter_fallback_preserves_rung_position():
    deepseek = Provider("deepseek", "https://direct.example/v1", "DEEPSEEK_API_KEY", 1, "deepseek-v4-flash", ("reasoning",))
    calls = []

    def factory(endpoint, key):
        calls.append((endpoint, key))
        return FakeClient("deepseek", {}, [])

    router = ProviderRouter(
        [deepseek],
        environ={
            "DEEPSEEK_VIA_OPENROUTER": "true",
            "OPENROUTER_API_KEY": "test-key",
            "OPENROUTER_DEEPSEEK_MODEL": "paid-deepseek-model",
        },
        client_factory=factory,
    )

    result = asyncio.run(router.route("reasoning", [{"role": "user", "content": "hi"}], urgent=True))

    assert result.provider == "deepseek"
    assert result.model == "paid-deepseek-model"
    assert calls == [("https://openrouter.ai/api/v1", "test-key")]


def test_no_eligible_provider_has_no_secret_details():
    router = ProviderRouter(providers(["one"]), environ={}, client_factory=lambda *_: None)

    with pytest.raises(NoEligibleProvider, match="no configured provider"):
        asyncio.run(router.route("latency", [{"role": "user", "content": "hi"}]))
