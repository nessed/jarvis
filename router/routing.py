"""OpenAI-compatible provider routing with runtime rate-limit awareness."""

from __future__ import annotations

import asyncio
import email.utils
import json
import logging
import os
import re
import threading
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any, Protocol


TASK_PROFILES = frozenset({"latency", "batch", "long_context", "vision", "reasoning"})
PEAK_DEEPSEEK_WINDOWS_UTC = ((1, 4), (6, 10))
DEFAULT_BACKOFF_SECONDS = 60

logger = logging.getLogger(__name__)


class RouterError(RuntimeError):
    """Base routing error."""


class NoEligibleProvider(RouterError):
    """No configured, available provider can handle a request."""


#: The statuses blueprint §3.3 calls a *denial*: a rung saying "not you"
#: (401), "not paid for" (402), or "not allowed" (403). Distinct from 429 and
#: 5xx, which say "not now" — those are about capacity, these are about
#: entitlement, and only these bar the paid rungs. Grouped as one set because
#: the blueprint groups them; splitting the grouping would be a change to a
#: specified decision, not an implementation detail.
DENIAL_STATUSES = frozenset({401, 402, 403})


class ProviderDenied(NoEligibleProvider):
    """A rung denied the request, and the next rung would have cost money.

    Blueprint §3.3: "A rung that returns 401/402/403 enters cooldown and
    surfaces the denial. It does not silently fall through to paid work."

    Raising *is* the surfacing. Inside one cascade there is no other channel:
    a request cannot both continue onto a paid rung and have surfaced the
    denial that preceded it, so the paid boundary is where the denial has to
    become visible. Falling through from one free rung to another is
    untouched — that costs nothing and violates nothing.

    A subclass of :class:`NoEligibleProvider` on purpose, so every existing
    caller's error handling is unchanged; ``executor/poller.py`` catches bare
    ``Exception`` and its retry/dead-letter path behaves exactly as before.
    """


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


def _unresolvable_model_reason(provider: Provider) -> str:
    """Say which env var would have fixed it, since that is the whole answer."""
    if provider.model_env:
        return f"no model: {provider.model_env} is unset"
    return "no model: its default_model placeholder is unset in .env"


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
        self._warned_unroutable: set[str] = set()

    def ordered_providers(self, task_profile: str, *, urgent: bool = False, emergency: bool = False) -> list[Provider]:
        if task_profile not in TASK_PROFILES:
            raise ValueError(f"unknown task profile: {task_profile}")

        self._warn_once_about_unroutable_rungs()
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
        # Per request, never persistent. The cooldown ledger already handles
        # repetition across requests; barring the paid rungs persistently would
        # let one bad key disable paid overflow indefinitely.
        denials: list[str] = []
        for provider in candidates:
            # §3.3's paid boundary, checked before the attempt rather than
            # after it, because after it the money is already spent.
            # ``emergency`` is the documented exception: the adjacent bullet
            # says urgency promotes a paid rung "explicitly and per-job", and
            # a per-job emergency flag is the opposite of silent.
            if denials and not emergency and (provider.paid_overflow or provider.capped):
                raise ProviderDenied(
                    "a rung denied the request and the next one costs money, so the cascade "
                    f"stopped at {provider.name}: " + "; ".join(denials)
                )
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
                denied = status in DENIAL_STATUSES
                if denied or status == 429 or (status is not None and 500 <= status <= 599):
                    # A denial is not a malformed request. A 401 is a key this
                    # workspace cannot use, a 402 is a plan with nothing left,
                    # a 403 is a permission it does not hold — none of them
                    # says the *request* was wrong, so none of them should
                    # abort a cascade that still has free rungs left to try.
                    #
                    # Until 2 Sep 2026 the cooldown here was written as
                    # `provider.name == "mistral"`, so every other provider's
                    # auth denial cooled down nothing and every subsequent job
                    # re-probed a key that could not work. The reason the
                    # carve-out gave applies to all of them and always did.
                    self._record_cooldown(provider, status, headers)
                    failures.append(f"{provider.name}: HTTP {status}")
                    if denied:
                        denials.append(f"{provider.name}: HTTP {status}")
                    continue
                raise
        if denials:
            # Every rung failed *and* at least one of them denied us. Say so
            # rather than reporting a generic exhaustion: a denial is a thing
            # the user can fix, and a 429 is a thing they wait out.
            raise ProviderDenied("all eligible providers failed: " + "; ".join(failures))
        raise NoEligibleProvider("all eligible providers failed: " + "; ".join(failures))

    def _configured(self, provider: Provider) -> bool:
        if provider.name == "deepseek" and self._environ.get("DEEPSEEK_VIA_OPENROUTER", "").lower() == "true":
            return bool(provider.endpoint and self._environ.get("OPENROUTER_API_KEY"))
        if not (provider.endpoint and provider.key_env and self._environ.get(provider.key_env)):
            return False
        return self._can_resolve_model(provider)

    def _warn_once_about_unroutable_rungs(self) -> None:
        """Say once, out loud, that a configured rung cannot be routed to.

        A key is present, so nothing looks unconfigured; the rung just never
        serves anything. The old failure mode was worse than silence — the
        skip *was* recorded, in a ``failures`` list only rendered when every
        provider failed, so the ladder working perfectly was exactly the
        condition that hid it.

        Once per provider per process: this runs on every request, and a
        warning per message would be noise nobody reads.
        """
        for name, reason in self.unroutable_reasons().items():
            if name in self._warned_unroutable:
                continue
            self._warned_unroutable.add(name)
            if reason.startswith("no model"):
                logger.warning(
                    "provider %s has a key but cannot be routed to: %s", name, reason
                )

    def _can_resolve_model(self, provider: Provider) -> bool:
        """Whether ``_model_for`` could return a model name for this provider.

        A rung that cannot name a model cannot serve a request, so it has no
        business in the candidate list — it enters, sorts by priority, and is
        skipped inside ``route()`` with a line appended to ``failures`` that is
        surfaced *only if every other provider also fails*.

        That is not hypothetical. On 2 Sep 2026 ``groq`` (priority 1) and
        ``cerebras`` (priority 2) sat at the front of every request and were
        skipped every time: both declare ``default_model:
        "${GROQ_DEFAULT_MODEL}"``, ``load_providers`` resolves an unset
        placeholder to ``None``, and the guard this replaces only fired for
        providers declaring ``model_env``. Six consecutive live ``latency``
        calls all went to ``openrouter`` while ``groq`` led the order each
        time, its ledger entry still reading ``last_status: None``.

        Filling the env vars in makes the symptom disappear; it does not fix
        this. Any future rung whose ``default_model`` is an unresolved
        placeholder would be silently unroutable in exactly the same way.

        The three sources are checked in ``_model_for``'s own order, so the two
        cannot drift apart. ``discover_chat_model`` counts as resolvable
        without asking: it resolves at request time against a live client, and
        Mistral is routable exactly that way (``codestral-2508``, live
        2 Sep 2026) with no ``default_model`` at all.
        """
        if provider.model_env and self._environ.get(provider.model_env):
            return True
        if provider.discover_chat_model:
            return True
        return bool(provider.default_model)

    def unroutable_reasons(self) -> dict[str, str]:
        """Why each manifest provider is not currently a routing candidate.

        Data, not a report. Blueprint §3.3 asks for a generated
        "configured-but-not-routable, with a reason" list, and deciding how
        that list *reads* belongs to ``provider-status-generator``; this is the
        input it needs, exposed so the reason does not live only in a log line
        that fires once per process.

        Cooldowns are excluded on purpose: a cooling rung is routable and
        merely resting, and the ledger already reports it with its status and
        remaining seconds.
        """
        reasons: dict[str, str] = {}
        for provider in self._providers:
            if provider.not_a_router_target:
                reasons[provider.name] = "not a router target"
            elif not provider.endpoint:
                reasons[provider.name] = "no endpoint configured"
            elif not (provider.key_env and self._environ.get(provider.key_env)):
                reasons[provider.name] = f"no API key in {provider.key_env or 'the manifest'}"
            elif not self._can_resolve_model(provider):
                reasons[provider.name] = _unresolvable_model_reason(provider)
            elif provider.emergency_only:
                reasons[provider.name] = "emergency only"
        return reasons

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
        now = self._now().astimezone(UTC)
        # DeepSeek dropped the peak/off-peak split for Saturday/Sunday UTC
        # (effective 23 Aug 2026): weekend usage bills at the off-peak rate
        # all day, so the peak-avoidance gate has nothing to avoid then.
        if now.weekday() >= 5:
            return True
        return not any(start <= now.hour < end for start, end in PEAK_DEEPSEEK_WINDOWS_UTC)

    def health_snapshot(self) -> dict[str, dict[str, Any]]:
        """A view of provider health that means something in another process.

        ``ProviderHealth.cooldown_until`` is a ``monotonic()`` reading, and
        monotonic clocks share no origin between processes — handing that
        number to the bus would compare it against an unrelated zero. It is
        converted to seconds remaining here, and ``router/health_report.py``
        ages that countdown on the way back out.

        Carries only what ``/status`` already exposed: a status code, a
        countdown, and rate-limit headers (already filtered to ``retry-after``
        and ``x-ratelimit-*`` by ``_record_response_headers``). No key, no
        endpoint, no body.
        """
        now = self._clock()
        return {
            name: {
                "last_status": health.last_status,
                "cooldown_seconds_remaining": round(max(0.0, health.cooldown_until - now), 3),
                "rate_limit_headers": dict(health.rate_limit_headers),
            }
            for name, health in self.health.items()
        }

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


#: One router per process, created on first use. Guarded because a handler can
#: be called from the poller's worker thread while another is mid-flight; the
#: lock only protects *creation*, since two routers would mean two ledgers and
#: the ledger is the whole point. Health mutation past that is single-writer in
#: practice — a poller claims one job at a time.
_SHARED_ROUTER_LOCK = threading.Lock()
_shared_router: "ProviderRouter | None" = None


def shared_router() -> ProviderRouter:
    """The process-lifetime router, built on first use.

    Before this existed, ``route()`` constructed a ``ProviderRouter`` per call.
    Every call therefore re-read ``providers.yaml`` and, far worse, started
    from a blank ``health`` map: a provider that had just returned 429 with a
    ``retry-after`` was tried again on the very next message, because the
    cooldown it had just earned died with the router that recorded it. A
    ledger that does not outlive one call is not a ledger.

    Process-lifetime, not persisted to disk: Q10c's answer. A restart forgets
    cooldowns, which is the correct trade — the alternative is a stale file
    telling a fresh process to avoid a provider that recovered hours ago.
    """
    global _shared_router
    if _shared_router is None:
        with _SHARED_ROUTER_LOCK:
            if _shared_router is None:
                _shared_router = ProviderRouter()
    return _shared_router


def current_shared_router() -> ProviderRouter | None:
    """The shared router if one has been built, without building one.

    Lets a process ask "has anything routed here?" without paying for a
    manifest read. The executor's health publisher uses it so a worker that
    never routes — ``action-worker``, ``background-worker`` — neither builds a
    router nor overwrites the snapshot of the worker that does.
    """
    return _shared_router


def reset_shared_router(router: ProviderRouter | None = None) -> ProviderRouter | None:
    """Replace (or clear) the shared router. A test seam, not a runtime path."""
    global _shared_router
    _shared_router = router
    return router


async def route(
    task_profile: str, messages: Sequence[Mapping[str, Any]], *, urgent: bool = False, **request_options: Any
) -> RoutedResult:
    """Convenience entrypoint for executor integration."""
    return await shared_router().route(task_profile, messages, urgent=urgent, **request_options)
