"""OpenAI-compatible provider routing with runtime rate-limit awareness."""

from __future__ import annotations

import asyncio
import email.utils
import json
import os
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


ClientFactory = Callable[[str, str], ChatClient]


class OpenAIChatClient:
    """Small async adapter around the official OpenAI SDK."""

    def __init__(self, base_url: str, api_key: str):
        # Import lazily so config/tests do not need credentials or the SDK installed.
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    async def create_chat_completion(
        self, *, model: str, messages: Sequence[Mapping[str, Any]], **kwargs: Any
    ) -> Any:
        return await self._client.chat.completions.create(model=model, messages=list(messages), **kwargs)


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
            provider_model = model or self._model_for(provider)
            if not provider_model:
                failures.append(f"{provider.name}: no model configured")
                continue
            try:
                client = self._client_factory(self._endpoint_for(provider), self._key_for(provider))
                response = await client.create_chat_completion(
                    model=provider_model, messages=messages, **request_options
                )
                self.health[provider.name].last_status = 200
                return RoutedResult(provider=provider.name, model=provider_model, response=response)
            except Exception as exc:  # SDK exception types intentionally vary by provider.
                status, headers = _response_metadata(exc)
                if status == 429 or (status is not None and 500 <= status <= 599):
                    self._record_cooldown(provider, status, headers)
                    failures.append(f"{provider.name}: HTTP {status}")
                    continue
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

    def _model_for(self, provider: Provider) -> str | None:
        if provider.name == "deepseek" and self._environ.get("DEEPSEEK_VIA_OPENROUTER", "").lower() == "true":
            return self._environ.get("OPENROUTER_DEEPSEEK_MODEL", provider.default_model)
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
        health.rate_limit_headers = {
            key: value for key, value in normalized.items() if key == "retry-after" or key.startswith("x-ratelimit-")
        }


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
            try:
                reset = float(value)
            except ValueError:
                continue
            if reset > now.timestamp():
                return reset - now.timestamp()
            if reset >= 0:
                return reset
    return float(default)


async def route(
    task_profile: str, messages: Sequence[Mapping[str, Any]], *, urgent: bool = False, **request_options: Any
) -> RoutedResult:
    """Convenience entrypoint for executor integration."""
    return await ProviderRouter().route(task_profile, messages, urgent=urgent, **request_options)
