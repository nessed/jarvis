import asyncio
from datetime import UTC, datetime

import pytest

from router import NoEligibleProvider, Provider, ProviderRequestError, ProviderRouter, load_providers
from router.routing import _chat_model_id, _retry_delay_seconds


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


class DiscoveringFakeClient(FakeClient):
    def __init__(self, provider, outcomes, calls, models):
        super().__init__(provider, outcomes, calls)
        self.models = models
        self.model_discovery_calls = 0

    async def list_chat_models(self):
        self.model_discovery_calls += 1
        if isinstance(self.models, Exception):
            raise self.models
        return self.models


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


def test_manifest_has_mistral_spare_rung_and_safe_model_configuration():
    manifest = load_providers(environ={})
    assert [provider.name for provider in manifest] == [
        "groq",
        "cerebras",
        "nvidia_nim",
        "gemini",
        "openrouter",
        "mistral",
        "deepseek",
        "claude_max",
        "claude_api",
    ]
    assert manifest[7].not_a_router_target
    assert manifest[8].emergency_only and manifest[8].capped
    assert manifest[4].default_model == "openrouter/free"
    assert manifest[5].endpoint == "https://api.mistral.ai/v1"
    assert manifest[5].model_env == "MISTRAL_DEFAULT_MODEL"
    assert manifest[5].discover_chat_model
    assert manifest[5].default_model is None
    # Provider-specific free model IDs are supplied through runtime env vars.
    assert manifest[0].default_model is None


def test_mistral_uses_configured_model_before_dynamic_discovery():
    mistral = Provider(
        "mistral",
        "https://api.mistral.ai/v1",
        "MISTRAL_API_KEY",
        1,
        None,
        ("batch",),
        model_env="MISTRAL_DEFAULT_MODEL",
        discover_chat_model=True,
    )
    calls = []
    client = DiscoveringFakeClient("mistral", {}, calls, ["discovered-chat-model"])
    router = ProviderRouter(
        [mistral],
        environ={"MISTRAL_API_KEY": "test-key", "MISTRAL_DEFAULT_MODEL": "workspace-approved-model"},
        client_factory=lambda *_: client,
    )

    result = asyncio.run(router.route("batch", [{"role": "user", "content": "hi"}]))

    assert result.model == "workspace-approved-model"
    assert client.model_discovery_calls == 0
    assert calls == [("mistral", "workspace-approved-model")]


def test_mistral_discovers_only_current_chat_capable_models():
    mistral = Provider(
        "mistral",
        "https://api.mistral.ai/v1",
        "MISTRAL_API_KEY",
        1,
        None,
        ("batch",),
        discover_chat_model=True,
    )
    calls = []
    client = DiscoveringFakeClient("mistral", {}, calls, ["current-chat-model"])
    router = ProviderRouter(
        [mistral], environ={"MISTRAL_API_KEY": "test-key"}, client_factory=lambda *_: client
    )

    result = asyncio.run(router.route("batch", [{"role": "user", "content": "hi"}]))

    assert result.model == "current-chat-model"
    assert client.model_discovery_calls == 1
    assert calls == [("mistral", "current-chat-model")]


def test_mistral_model_selector_rejects_non_chat_and_archived_cards():
    assert _chat_model_id({"id": "live-chat", "capabilities": {"completion_chat": True}}) == "live-chat"
    assert _chat_model_id({"id": "embeddings", "capabilities": {"completion_chat": False}}) is None
    assert _chat_model_id({"id": "retired", "capabilities": {"completion_chat": True}, "archived": True}) is None


def test_mistral_workspace_denial_cools_down_without_paid_fallback():
    mistral = Provider(
        "mistral",
        "https://api.mistral.ai/v1",
        "MISTRAL_API_KEY",
        1,
        None,
        ("batch",),
        discover_chat_model=True,
    )
    spare = Provider("spare", "https://spare.example/v1", "SPARE_KEY", 2, "spare-model", ("batch",))
    calls = []
    mistral_client = DiscoveringFakeClient(
        "mistral", {}, calls, ProviderRequestError("workspace access denied", 403, {"Retry-After": "17"})
    )
    spare_client = FakeClient("spare", {}, calls)

    def factory(endpoint, _key):
        return mistral_client if endpoint == mistral.endpoint else spare_client

    router = ProviderRouter(
        [mistral, spare],
        environ={"MISTRAL_API_KEY": "test-key", "SPARE_KEY": "test-key"},
        client_factory=factory,
    )

    with pytest.raises(ProviderRequestError, match="workspace access denied"):
        asyncio.run(router.route("batch", [{"role": "user", "content": "hi"}]))

    assert router.health["mistral"].last_status == 403
    assert router.health["mistral"].cooldown_until > 0
    assert router.health["mistral"].rate_limit_headers == {"retry-after": "17"}

    result = asyncio.run(router.route("batch", [{"role": "user", "content": "retry"}]))

    assert result.provider == "spare"
    assert mistral_client.model_discovery_calls == 1


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


def test_deepseek_peak_gate_defers_route_to_spare_without_calling_deepseek():
    router, calls = router_for(
        ["deepseek", "spare"],
        {},
        now=lambda: datetime(2026, 8, 23, 6, 30, tzinfo=UTC),
    )

    result = asyncio.run(router.route("reasoning", [{"role": "user", "content": "hi"}]))

    assert result.provider == "spare"
    assert calls == [("spare", "spare-configured-model")]


def test_successful_response_records_live_style_rate_limit_headers():
    configured = [Provider("first", "https://first", "FIRST_KEY", 1, "first-model", ("latency",))]
    client = FakeClient("first", {}, [])
    client.last_response_headers = {"X-RateLimit-Reset-Requests": "1.5s", "X-RateLimit-Remaining-Requests": "4"}
    router = ProviderRouter(configured, environ={"FIRST_KEY": "test-key"}, client_factory=lambda *_: client)

    asyncio.run(router.route("latency", [{"role": "user", "content": "hi"}]))

    assert router.health["first"].rate_limit_headers == {
        "x-ratelimit-reset-requests": "1.5s",
        "x-ratelimit-remaining-requests": "4",
    }


def test_duration_reset_headers_parse_without_falling_back_to_default():
    now = datetime(2026, 8, 23, tzinfo=UTC)

    assert _retry_delay_seconds({"x-ratelimit-reset-requests": "1.5s"}, 60, now=now) == 1.5
    assert _retry_delay_seconds({"x-ratelimit-reset-requests": "250ms"}, 60, now=now) == 0.25


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
