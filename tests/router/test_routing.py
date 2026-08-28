import asyncio
from datetime import UTC, datetime

import httpx
import openai
import pytest

from router import NoEligibleProvider, Provider, ProviderRequestError, ProviderRouter, load_providers
from router.routing import OpenAIChatClient, _chat_model_id, _retry_delay_seconds


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


class _FakeRawResponse:
    """Stands in for the openai SDK's ``with_raw_response`` result: real
    ``httpx.Headers`` (case-insensitive multidict) plus a ``.parse()`` that
    returns whatever the caller configured as the deserialized body."""

    def __init__(self, headers, parsed):
        self.headers = httpx.Headers(headers)
        self._parsed = parsed

    def parse(self):
        return self._parsed


class _FakeRawEndpoint:
    def __init__(self, *, raw_response=None, exc=None):
        self._raw_response = raw_response
        self._exc = exc
        self.calls = []

    async def _respond(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self._exc is not None:
            raise self._exc
        return self._raw_response


class _FakeChatCompletions(_FakeRawEndpoint):
    async def create(self, *, model, messages, **kwargs):
        return await self._respond(model=model, messages=messages, **kwargs)


class _FakeModels(_FakeRawEndpoint):
    async def list(self):
        return await self._respond()


class _FakeWithRawResponse:
    def __init__(self, *, chat_completions, models):
        self.chat = type("_FakeChat", (), {"completions": chat_completions})()
        self.models = models


class FakeAsyncOpenAI:
    """An ``AsyncOpenAI``-shaped double exposing only ``with_raw_response``,
    the sole surface ``OpenAIChatClient`` touches."""

    def __init__(self, *, chat_raw_response=None, chat_exc=None, models_raw_response=None, models_exc=None):
        self.chat_completions = _FakeChatCompletions(raw_response=chat_raw_response, exc=chat_exc)
        self.models = _FakeModels(raw_response=models_raw_response, exc=models_exc)
        self.with_raw_response = _FakeWithRawResponse(chat_completions=self.chat_completions, models=self.models)


def openai_chat_client_with_fake_transport(**fake_kwargs) -> tuple[OpenAIChatClient, FakeAsyncOpenAI]:
    """Construct a real OpenAIChatClient (exercising its actual __init__ /
    AsyncOpenAI import path), then swap its internal client for a fake that
    never performs network I/O."""
    client = OpenAIChatClient("https://example.test/v1", "test-key")
    fake = FakeAsyncOpenAI(**fake_kwargs)
    client._client = fake
    return client, fake


def real_openai_error(error_type, status_code, headers):
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(status_code, headers=headers, request=request)
    return error_type(f"HTTP {status_code}", response=response, body=None)


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
    # 24 Aug 2026 is a Monday: a weekday peak window applies.
    configured = [
        Provider("deepseek", "https://deepseek", "DEEPSEEK_API_KEY", 1, "deepseek-v4-flash", ("reasoning",)),
        Provider("spare", "https://spare", "SPARE_KEY", 2, "spare-model", ("reasoning",)),
    ]
    now = lambda: datetime(2026, 8, 24, 1, 30, tzinfo=UTC)
    router = ProviderRouter(
        configured,
        environ={"DEEPSEEK_API_KEY": "x", "SPARE_KEY": "x"},
        client_factory=lambda *_: None,
        now=now,
    )

    assert [provider.name for provider in router.ordered_providers("reasoning")] == ["spare"]
    assert [provider.name for provider in router.ordered_providers("reasoning", urgent=True)] == ["deepseek", "spare"]


def test_deepseek_peak_gate_defers_route_to_spare_without_calling_deepseek():
    # 24 Aug 2026 is a Monday: a weekday peak window applies.
    router, calls = router_for(
        ["deepseek", "spare"],
        {},
        now=lambda: datetime(2026, 8, 24, 6, 30, tzinfo=UTC),
    )

    result = asyncio.run(router.route("reasoning", [{"role": "user", "content": "hi"}]))

    assert result.provider == "spare"
    assert calls == [("spare", "spare-configured-model")]


def test_deepseek_weekend_utc_skips_peak_gate_even_without_urgent():
    # router-deepseek-weekday-gate: DeepSeek dropped the peak/off-peak split
    # for Saturday/Sunday UTC (effective 23 Aug 2026) — weekend traffic bills
    # at the off-peak rate all day, so the peak-avoidance gate must not apply
    # on those two days regardless of hour.
    configured = [
        Provider("deepseek", "https://deepseek", "DEEPSEEK_API_KEY", 1, "deepseek-v4-flash", ("reasoning",)),
        Provider("spare", "https://spare", "SPARE_KEY", 2, "spare-model", ("reasoning",)),
    ]
    saturday_peak_hour = datetime(2026, 8, 22, 1, 30, tzinfo=UTC)
    sunday_peak_hour = datetime(2026, 8, 23, 6, 30, tzinfo=UTC)

    for weekend_now in (saturday_peak_hour, sunday_peak_hour):
        router = ProviderRouter(
            configured,
            environ={"DEEPSEEK_API_KEY": "x", "SPARE_KEY": "x"},
            client_factory=lambda *_: None,
            now=lambda moment=weekend_now: moment,
        )

        assert [provider.name for provider in router.ordered_providers("reasoning")] == ["deepseek", "spare"]


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


def test_402_cools_down_and_falls_through_instead_of_aborting_chain():
    # router-402-aborts-chain: a plan/key that cannot serve this rung at all
    # (e.g. Cerebras' PaymentRequired) must not kill the whole fallback
    # cascade, and must not go unrecorded so the next call repeats it.
    router, calls = router_for(
        ["first", "second"],
        {"first": ProviderRequestError("payment required", 402, {"Retry-After": "30"})},
    )

    result = asyncio.run(router.route("batch", [{"role": "user", "content": "hi"}]))

    assert result.provider == "second"
    assert calls == [("first", "first-configured-model"), ("second", "second-configured-model")]
    health = router.health["first"]
    assert health.last_status == 402
    assert health.cooldown_until > 0


def test_401_still_propagates_for_non_mistral_providers():
    # The 402 fix must not widen into swallowing genuine auth failures for
    # providers other than the existing Mistral workspace-denial case.
    router, calls = router_for(
        ["first", "second"],
        {"first": ProviderRequestError("invalid api key", 401, {})},
    )

    with pytest.raises(ProviderRequestError, match="invalid api key"):
        asyncio.run(router.route("batch", [{"role": "user", "content": "hi"}]))

    assert calls == [("first", "first-configured-model")]
    assert router.health["first"].cooldown_until == 0.0


def test_model_env_requiring_provider_without_env_var_is_not_configured():
    # router-model-env-validation: a provider whose model_env is unset, and
    # which has no discover_chat_model or default_model fallback, cannot
    # resolve a model at request time. It must be excluded from the
    # candidate list, not enter and silently no-op through _model_for().
    needs_env = Provider(
        "needs-env",
        "https://needs-env.example/v1",
        "NEEDS_ENV_KEY",
        1,
        None,
        ("batch",),
        model_env="NEEDS_ENV_MODEL",
    )
    spare = Provider("spare", "https://spare.example/v1", "SPARE_KEY", 2, "spare-model", ("batch",))
    router = ProviderRouter(
        [needs_env, spare],
        environ={"NEEDS_ENV_KEY": "test-key", "SPARE_KEY": "test-key"},
        client_factory=lambda *_: None,
    )

    assert [provider.name for provider in router.ordered_providers("batch")] == ["spare"]


def test_model_env_requiring_provider_with_env_var_set_is_configured():
    needs_env = Provider(
        "needs-env",
        "https://needs-env.example/v1",
        "NEEDS_ENV_KEY",
        1,
        None,
        ("batch",),
        model_env="NEEDS_ENV_MODEL",
    )
    router = ProviderRouter(
        [needs_env],
        environ={"NEEDS_ENV_KEY": "test-key", "NEEDS_ENV_MODEL": "configured-model"},
        client_factory=lambda *_: None,
    )

    assert [provider.name for provider in router.ordered_providers("batch")] == ["needs-env"]


def test_no_eligible_provider_has_no_secret_details():
    router = ProviderRouter(providers(["one"]), environ={}, client_factory=lambda *_: None)

    with pytest.raises(NoEligibleProvider, match="no configured provider"):
        asyncio.run(router.route("latency", [{"role": "user", "content": "hi"}]))


def test_openai_chat_client_constructs_a_real_async_openai_client_without_network_io():
    # Constructing AsyncOpenAI performs no I/O; confirm OpenAIChatClient's
    # real __init__ path (the lazy `from openai import AsyncOpenAI` import,
    # not a fake) builds a real SDK client and starts with empty headers.
    client = OpenAIChatClient("https://example.test/v1", "test-key")

    assert isinstance(client._client, openai.AsyncOpenAI)
    assert client.last_response_headers == {}


def test_create_chat_completion_parses_the_body_and_lowercases_response_headers():
    # dict() on the openai SDK's httpx-backed Headers lowercases every key
    # regardless of the casing a provider actually sent -- confirm the real
    # object, not an assumption about it.
    parsed_completion = {"id": "chatcmpl-1", "choices": []}
    client, fake = openai_chat_client_with_fake_transport(
        chat_raw_response=_FakeRawResponse(
            {"X-RateLimit-Remaining-Requests": "4", "Content-Type": "application/json"}, parsed_completion
        )
    )

    result = asyncio.run(
        client.create_chat_completion(model="gpt-test", messages=[{"role": "user", "content": "hi"}], temperature=0)
    )

    assert result is parsed_completion
    assert client.last_response_headers == {
        "x-ratelimit-remaining-requests": "4",
        "content-type": "application/json",
    }
    (call_args, call_kwargs), = fake.chat_completions.calls
    assert call_kwargs == {"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}], "temperature": 0}


def test_list_chat_models_filters_via_chat_model_id_and_records_headers():
    payload = type(
        "_Payload",
        (),
        {
            "data": [
                {"id": "live-chat", "capabilities": {"completion_chat": True}},
                {"id": "embeddings-only", "capabilities": {"completion_chat": False}},
                {"id": "retired-chat", "capabilities": {"completion_chat": True}, "archived": True},
            ]
        },
    )()
    client, fake = openai_chat_client_with_fake_transport(
        models_raw_response=_FakeRawResponse({"Retry-After": "0"}, payload)
    )

    models = asyncio.run(client.list_chat_models())

    assert models == ["live-chat"]
    assert client.last_response_headers == {"retry-after": "0"}
    assert fake.models.calls == [((), {})]


def test_list_chat_models_accepts_a_bare_list_payload_without_a_data_attribute():
    # list_chat_models() does entries = getattr(payload, "data", payload):
    # confirm the fallback path for a provider that parses straight to a list.
    bare_list_payload = [{"id": "only-model", "capabilities": {"completion_chat": True}}]
    client, _fake = openai_chat_client_with_fake_transport(
        models_raw_response=_FakeRawResponse({}, bare_list_payload)
    )

    models = asyncio.run(client.list_chat_models())

    assert models == ["only-model"]


def test_create_chat_completion_propagates_a_real_openai_rate_limit_error():
    client, _fake = openai_chat_client_with_fake_transport(
        chat_exc=real_openai_error(openai.RateLimitError, 429, {"Retry-After": "17"})
    )

    with pytest.raises(openai.RateLimitError) as excinfo:
        asyncio.run(client.create_chat_completion(model="gpt-test", messages=[{"role": "user", "content": "hi"}]))

    assert excinfo.value.status_code == 429


def test_provider_router_maps_a_real_openai_rate_limit_error_via_response_headers_fallback():
    # openai SDK exceptions set status_code directly but only expose headers
    # through .response.headers, not a top-level .headers attribute --
    # confirm _response_metadata()'s fallback-to-.response branch actually
    # fires against a genuine openai.RateLimitError, not a hand-rolled
    # ProviderRequestError double.
    configured = [
        Provider("openai_rung", "https://openai-rung.example/v1", "OPENAI_RUNG_KEY", 1, "configured-model", ("batch",)),
        Provider("spare", "https://spare.example/v1", "SPARE_KEY", 2, "spare-model", ("batch",)),
    ]
    failing_client, _fake = openai_chat_client_with_fake_transport(
        chat_exc=real_openai_error(openai.RateLimitError, 429, {"Retry-After": "17"})
    )
    spare_client, _spare_fake = openai_chat_client_with_fake_transport(
        chat_raw_response=_FakeRawResponse({}, {"id": "ok"})
    )

    def factory(endpoint, _key):
        return failing_client if endpoint == configured[0].endpoint else spare_client

    router = ProviderRouter(
        configured, environ={"OPENAI_RUNG_KEY": "test-key", "SPARE_KEY": "test-key"}, client_factory=factory
    )

    result = asyncio.run(router.route("batch", [{"role": "user", "content": "hi"}]))

    assert result.provider == "spare"
    health = router.health["openai_rung"]
    assert health.last_status == 429
    assert health.rate_limit_headers == {"retry-after": "17"}
    assert health.cooldown_until > 0


def test_provider_router_maps_a_real_openai_402_payment_required_error_and_falls_through():
    configured = [
        Provider("openai_rung", "https://openai-rung.example/v1", "OPENAI_RUNG_KEY", 1, "configured-model", ("batch",)),
        Provider("spare", "https://spare.example/v1", "SPARE_KEY", 2, "spare-model", ("batch",)),
    ]
    failing_client, _fake = openai_chat_client_with_fake_transport(
        chat_exc=real_openai_error(openai.APIStatusError, 402, {"Retry-After": "5"})
    )
    spare_client, _spare_fake = openai_chat_client_with_fake_transport(
        chat_raw_response=_FakeRawResponse({}, {"id": "ok"})
    )

    def factory(endpoint, _key):
        return failing_client if endpoint == configured[0].endpoint else spare_client

    router = ProviderRouter(
        configured, environ={"OPENAI_RUNG_KEY": "test-key", "SPARE_KEY": "test-key"}, client_factory=factory
    )

    result = asyncio.run(router.route("batch", [{"role": "user", "content": "hi"}]))

    assert result.provider == "spare"
    assert router.health["openai_rung"].last_status == 402
