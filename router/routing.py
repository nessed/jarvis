"""OpenAI-compatible provider routing with runtime rate-limit awareness."""

from __future__ import annotations

import asyncio
import email.utils
import json
import os
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any, Protocol


TASK_PROFILES = frozenset({"latency", "batch", "long_context", "vision", "reasoning"})
PEAK_DEEPSEEK_WINDOWS_UTC = ((1, 4), (6, 10))
DEFAULT_BACKOFF_SECONDS = 60


class RouterError(RuntimeError):
    """Base routing error."""


class NoEligibleProvider(RouterError):
    """No configured, available provider can handle a request."""


class ProviderRequestError(RouterError):
    """An adapter-friendly failure carrying HTTP response metadata."""

    def __init__(self, message: str, status_code: int | None = None, headers: Mapping[str, str] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.headers = dict(headers or {})


@dataclass(frozen=True)
class Provider:
    name: str
    endpoint: str | None
    key_env: str | None
    priority: int
    default_model: str | None
    task_profiles: tuple[str, ...]
    not_a_router_target: bool = False
    emergency_only: bool = False
    capped: bool = False
    paid_overflow: bool = False
    model_env: str | None = None
    discover_chat_model: bool = False


@dataclass(frozen=True)
class RoutedResult:
    provider: str
    model: str
    response: Any


@dataclass
class ProviderHealth:
    cooldown_until: float = 0.0
    last_status: int | None = None
    rate_limit_headers: dict[str, str] = field(default_factory=dict)


class ChatClient(Protocol):
    async def create_chat_completion(self, *, model: str, messages: Sequence[Mapping[str, Any]], **kwargs: Any) -> Any: ...


class ModelDiscoveringChatClient(ChatClient, Protocol):
    async def list_chat_models(self) -> Sequence[str]: ...


ClientFactory = Callable[[str, str], ChatClient]


class OpenAIChatClient:
    """Small async adapter around the official OpenAI SDK."""

    def __init__(self, base_url: str, api_key: str):
        # Import lazily so config/tests do not need credentials or the SDK installed.
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.last_response_headers: dict[str, str] = {}

    async def create_chat_completion(
        self, *, model: str, messages: Sequence[Mapping[str, Any]], **kwargs: Any
    ) -> Any:
        raw_response = await self._client.with_raw_response.chat.completions.create(
            model=model, messages=list(messages), **kwargs
        )
        self.last_response_headers = dict(raw_response.headers)
        return raw_response.parse()

    async def list_chat_models(self) -> Sequence[str]:
        """Return chat-capable models granted to this API key.

        Mistral's model roster and trial entitlements change independently of
        this repository. The API's capability field is therefore the authority;
        we never guess a model ID from a hard-coded free-tier roster.
        """
        raw_response = await self._client.with_raw_response.models.list()
        self.last_response_headers = dict(raw_response.headers)
        payload = raw_response.parse()
        entries = getattr(payload, "data", payload)
        return [model_id for item in entries if (model_id := _chat_model_id(item))]


def openai_client_factory(base_url: str, api_key: str) -> OpenAIChatClient:
    return OpenAIChatClient(base_url, api_key)


def load_providers(path: Path | None = None, environ: Mapping[str, str] | None = None) -> list[Provider]:
    """Load the repository-owned provider manifest.

    The manifest deliberately uses JSON syntax, which is valid YAML, so the
    routing core does not require a YAML parser merely to start. Environment
    placeholders are resolved at load time; API keys themselves remain read at
    request time.
    """
    environ = environ if environ is not None else os.environ
    source = path or Path(__file__).with_name("providers.yaml")
    raw = json.loads(source.read_text(encoding="utf-8"))["providers"]

    def resolve(value: Any) -> Any:
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            return environ.get(value[2:-1])
        return value

    return [
        Provider(
            name=item["name"],
            endpoint=resolve(item.get("endpoint")),
            key_env=item.get("key_env"),
            priority=int(item["priority"]),
            default_model=resolve(item.get("default_model")),
            task_profiles=tuple(item.get("task_profiles", ())),
            not_a_router_target=bool(item.get("not_a_router_target", False)),
            emergency_only=bool(item.get("emergency_only", False)),
            capped=bool(item.get("capped", False)),
            paid_overflow=bool(item.get("paid_overflow", False)),
            model_env=item.get("model_env"),
            discover_chat_model=bool(item.get("discover_chat_model", False)),
        )
        for item in raw
    ]


class ProviderRouter:
    """Routes a completion request down the configured fallback ladder."""

    def __init__(
        self,
        providers: Sequence[Provider] | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        client_factory: ClientFactory = openai_client_factory,
        now: Callable[[], datetime] | None = None,
        clock: Callable[[], float] = monotonic,
        default_backoff_seconds: int = DEFAULT_BACKOFF_SECONDS,
    ):
        self._environ = environ if environ is not None else os.environ
        self._providers = sorted(providers if providers is not None else load_providers(environ=self._environ), key=lambda p: p.priority)
        self._client_factory = client_factory
        self._now = now or (lambda: datetime.now(UTC))
        self._clock = clock
        self._default_backoff_seconds = default_backoff_seconds
        self.health: dict[str, ProviderHealth] = {provider.name: ProviderHealth() for provider in self._providers}

    def ordered_providers(self, task_profile: str, *, urgent: bool = False, emergency: bool = False) -> list[Provider]:
        if task_profile not in TASK_PROFILES:
            raise ValueError(f"unknown task profile: {task_profile}")

        eligible = [
            provider
            for provider in self._providers
            if not provider.not_a_router_target
            and (emergency or not provider.emergency_only)
            and self._configured(provider)
            and not self._in_cooldown(provider)
            and self._deepseek_allowed(provider, urgent=urgent)
        ]
        preferred = [provider for provider in eligible if task_profile in provider.task_profiles]
        others = [provider for provider in eligible if task_profile not in provider.task_profiles]
        return preferred + others

    async def route(
        self,
        task_profile: str,
        messages: Sequence[Mapping[str, Any]],
        *,
        urgent: bool = False,
        emergency: bool = False,
        model: str | None = None,
        **request_options: Any,
    ) -> RoutedResult:
        """Attempt providers in profile-aware priority order.

        Only a 429 or server error falls through. Other failures propagate so
        malformed requests and auth errors are not hidden by another provider.
        """
        candidates = self.ordered_providers(task_profile, urgent=urgent, emergency=emergency)
        if not candidates:
            raise NoEligibleProvider("no configured provider is currently eligible")

        failures: list[str] = []
        for provider in candidates:
            try:
                client = self._client_factory(self._endpoint_for(provider), self._key_for(provider))
                provider_model = model or await self._model_for(provider, client)
                if not provider_model:
                    failures.append(f"{provider.name}: no model configured")
                    continue
                response = await client.create_chat_completion(
                    model=provider_model, messages=messages, **request_options
                )
                self.health[provider.name].last_status = 200
                self._record_response_headers(provider, getattr(client, "last_response_headers", {}))
                return RoutedResult(provider=provider.name, model=provider_model, response=response)
            except Exception as exc:  # SDK exception types intentionally vary by provider.
                status, headers = _response_metadata(exc)
                if status == 429 or (status is not None and 500 <= status <= 599):
                    self._record_cooldown(provider, status, headers)
                    failures.append(f"{provider.name}: HTTP {status}")
                    continue
                # A Mistral Labs/workspace denial is not a malformed request.
                # Record it as unavailable so future jobs do not repeatedly
                # probe a key that cannot currently run chat completions, but
                # surface the denial to the caller rather than silently moving
                # the request to another (possibly paid) provider.
                if provider.name == "mistral" and status in {401, 403}:
                    self._record_cooldown(provider, status, headers)
                raise
        raise NoEligibleProvider("all eligible providers failed: " + "; ".join(failures))

    def _configured(self, provider: Provider) -> bool:
        if provider.name == "deepseek" and self._environ.get("DEEPSEEK_VIA_OPENROUTER", "").lower() == "true":
            return bool(provider.endpoint and self._environ.get("OPENROUTER_API_KEY"))
        return bool(provider.endpoint and provider.key_env and self._environ.get(provider.key_env))

    def _key_for(self, provider: Provider) -> str:
        if provider.name == "deepseek" and self._environ.get("DEEPSEEK_VIA_OPENROUTER", "").lower() == "true":
            key = self._environ.get("OPENROUTER_API_KEY")
            if not key:
                raise NoEligibleProvider("DeepSeek via OpenRouter has no configured API key")
            return key
        assert provider.key_env
        key = self._environ.get(provider.key_env)
        if not key:
            raise NoEligibleProvider(f"{provider.name} has no configured API key")
        return key

    def _endpoint_for(self, provider: Provider) -> str:
        if provider.name == "deepseek" and self._environ.get("DEEPSEEK_VIA_OPENROUTER", "").lower() == "true":
            endpoint = self._environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
            if not self._environ.get("OPENROUTER_API_KEY"):
                raise NoEligibleProvider("DeepSeek via OpenRouter needs OPENROUTER_API_KEY")
            return endpoint
        assert provider.endpoint
        return provider.endpoint

    async def _model_for(self, provider: Provider, client: ChatClient) -> str | None:
        if provider.name == "deepseek" and self._environ.get("DEEPSEEK_VIA_OPENROUTER", "").lower() == "true":
            return self._environ.get("OPENROUTER_DEEPSEEK_MODEL", provider.default_model)
        if provider.model_env and (configured_model := self._environ.get(provider.model_env)):
            return configured_model
        if provider.discover_chat_model:
            discover = getattr(client, "list_chat_models", None)
            if discover is None:
                return None
            available = await discover()
            return available[0] if available else None
        return provider.default_model

    def _in_cooldown(self, provider: Provider) -> bool:
        return self.health[provider.name].cooldown_until > self._clock()

    def _deepseek_allowed(self, provider: Provider, *, urgent: bool) -> bool:
        if provider.name != "deepseek" or urgent:
            return True
        hour = self._now().astimezone(UTC).hour
        return not any(start <= hour < end for start, end in PEAK_DEEPSEEK_WINDOWS_UTC)

    def _record_cooldown(self, provider: Provider, status: int | None, headers: Mapping[str, str]) -> None:
        normalized = {key.lower(): value for key, value in headers.items()}
        cooldown = _retry_delay_seconds(normalized, self._default_backoff_seconds, now=self._now())
        health = self.health[provider.name]
        health.cooldown_until = self._clock() + cooldown
        health.last_status = status
        self._record_response_headers(provider, normalized)

    def _record_response_headers(self, provider: Provider, headers: Mapping[str, str]) -> None:
        normalized = {key.lower(): value for key, value in headers.items()}
        rate_limit_headers = {
            key: value for key, value in normalized.items() if key == "retry-after" or key.startswith("x-ratelimit-")
        }
        if rate_limit_headers:
            self.health[provider.name].rate_limit_headers = rate_limit_headers


def _response_metadata(exc: BaseException) -> tuple[int | None, Mapping[str, str]]:
    status = getattr(exc, "status_code", None)
    headers = getattr(exc, "headers", None)
    response = getattr(exc, "response", None)
    if response is not None:
        status = status if status is not None else getattr(response, "status_code", None)
        headers = headers if headers is not None else getattr(response, "headers", None)
    return status, headers or {}


def _retry_delay_seconds(headers: Mapping[str, str], default: int, *, now: datetime) -> float:
    retry_after = headers.get("retry-after")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                retry_at = email.utils.parsedate_to_datetime(retry_after)
                return max(0.0, (retry_at - now).total_seconds())
            except (TypeError, ValueError):
                pass
    # Providers use several x-ratelimit reset spellings. Interpret a numeric
    # value as a relative delay first, then as a Unix epoch if it is in future.
    for key, value in headers.items():
        if key.startswith("x-ratelimit-") and "reset" in key:
            duration = _duration_seconds(value)
            if duration is not None:
                return duration
            try:
                reset = float(value)
            except ValueError:
                continue
            if reset > now.timestamp():
                return reset - now.timestamp()
            if reset >= 0:
                return reset
    return float(default)


def _duration_seconds(value: str) -> float | None:
    """Parse common provider reset durations such as ``250ms`` and ``1.5s``."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h)\s*", value, flags=re.IGNORECASE)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2).lower()
    return amount * {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}[unit]


def _chat_model_id(item: Any) -> str | None:
    """Extract an unarchived chat-capable model ID from a Mistral model card."""
    if hasattr(item, "model_dump"):
        item = item.model_dump(mode="json")
    elif not isinstance(item, Mapping):
        item = vars(item)
    if not isinstance(item, Mapping):
        return None
    capabilities = item.get("capabilities")
    if not isinstance(capabilities, Mapping) or capabilities.get("completion_chat") is not True:
        return None
    if item.get("archived") is True:
        return None
    model_id = item.get("id")
    return model_id if isinstance(model_id, str) and model_id else None


async def route(
    task_profile: str, messages: Sequence[Mapping[str, Any]], *, urgent: bool = False, **request_options: Any
) -> RoutedResult:
    """Convenience entrypoint for executor integration."""
    return await ProviderRouter().route(task_profile, messages, urgent=urgent, **request_options)
