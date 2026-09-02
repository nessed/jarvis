You are a second opinion on a decision inside an AI-agent-built project.
The agent asking has already gathered the evidence below and could not
resolve the question from it alone. Do not restate the evidence. Decide.

## Question

What does "surfaces the denial. It does not silently fall through to paid work"
demand of the control flow, exactly?

The clause is Ali's own blueprint text (docs/blueprint.md §3.3, applied 2 Sep
2026), and the task says to settle its reading BEFORE changing control flow,
because one reading changes reply behaviour on a live rung failure:

  "- Rungs are ordered by cost class first (free-tier, then trial/credit, then
     paid), and within a class by measured p50 latency for the task profile.
   - `route(task_profile)` reorders within a cost class only. It never promotes
     a paid rung above a free one that is eligible; urgency does that,
     explicitly and per-job.
   - A rung that returns 401/402/403 enters cooldown and surfaces the denial.
     It does not silently fall through to paid work."

Today, in router/routing.py's cascade:
  - 429, 402 and 5xx all cool the rung down, append to `failures`, and
    `continue` to the next candidate.
  - 401/403 re-raise to the caller, and the cooldown is a carve-out written as
    `if provider.name == "mistral"`, so no other provider's auth denial cools
    anything down.
  - When every candidate fails, it raises NoEligibleProvider("all eligible
    providers failed: " + "; ".join(failures)).

The ladder is priority-ordered in router/providers.yaml. Free/trial rungs
first (groq, cerebras, nvidia_nim, gemini, openrouter, mistral), then
`deepseek` marked `"paid_overflow": true`, then `claude_api` marked
`"capped": true` and `"emergency_only": true`. Both flags already exist on the
Provider dataclass. There is no `cost_class` field yet — a separate board task
adds it — but `paid_overflow` and `capped` already express "this one costs
money" for the two rungs that do.

Callers: this is on the WhatsApp reply path. A raise from route() propagates to
the handler, then to executor/poller.py, which retries with backoff and
eventually dead-letters. So "abort the cascade" concretely means the user's
message gets no reply for that attempt.

Three candidate readings:

  A. Literal-strict. 401/402/403 aborts the cascade outright and re-raises,
     for every provider. Nothing falls through. Simplest to state, and it is
     what 401/403 already do for Mistral.

  B. Paid-boundary. A denial cools the rung down and the cascade continues,
     but it may not cross into a rung marked `paid_overflow` or `capped`
     while an unsurfaced denial is outstanding — at that boundary it raises
     instead, carrying the denial. Falling through from one free rung to
     another free rung stays allowed.

  C. Surfacing-only. Keep the current fall-through for all of them; "surfaces"
     is satisfied by the ledger's `last_status` being visible on /status
     (which it is, since 2 Sep) plus the denial appearing in the aggregated
     failure message. No control-flow change at all.

Questions:
  - Which reading does the sentence actually demand? Pay attention to the two
    qualifiers: "silently", and "to paid work" — neither is idle if the
    sentence means A, and B is the only reading in which both do work.
  - If B: is "an unsurfaced denial is outstanding" the right trigger, or
    should a denial anywhere in the cascade permanently bar the paid rungs
    for that request?
  - A 401 means a bad key and a 402 means no money on this plan. Should they
    really share one control-flow rule, given a 401 is a config error that
    will repeat on every job and a 402 is a plan state that might not?
  - What is the smallest change that satisfies the clause without making a
    live reply fail where it currently succeeds?

## Evidence

### router/routing.py

```
"""OpenAI-compatible provider routing with runtime rate-limit awareness."""

from __future__ import annotations

import asyncio
import email.utils
import json
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
                if status == 429 or status == 402 or (status is not None and 500 <= status <= 599):
                    # 402 (e.g. Cerebras' PaymentRequired for a key/plan with no
                    # free tier) means this rung cannot serve the request at
                    # all, not that the request was malformed. Cool it down and
                    # keep falling through, same as 429/5xx, instead of
                    # aborting the whole cascade with a bare raise.
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
        if not (provider.endpoint and provider.key_env and self._environ.get(provider.key_env)):
            return False
        # A provider that names a model_env with no discover_chat_model or
        # default_model fallback has no way to resolve a model at request
        # time if that env var is unset. Keep it out of the candidate list
        # rather than letting it enter and no-op through _model_for().
        if provider.model_env and not provider.discover_chat_model and not provider.default_model:
            return bool(self._environ.get(provider.model_env))
        return True

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

```
### router/providers.yaml

```
{
  "providers": [
    {
      "name": "groq",
      "endpoint": "https://api.groq.com/openai/v1",
      "key_env": "GROQ_API_KEY",
      "priority": 1,
      "default_model": "${GROQ_DEFAULT_MODEL}",
      "task_profiles": ["latency", "batch"]
    },
    {
      "name": "cerebras",
      "endpoint": "https://api.cerebras.ai/v1",
      "key_env": "CEREBRAS_API_KEY",
      "priority": 2,
      "default_model": "${CEREBRAS_DEFAULT_MODEL}",
      "task_profiles": ["batch"]
    },
    {
      "name": "nvidia_nim",
      "endpoint": "https://integrate.api.nvidia.com/v1",
      "key_env": "NVIDIA_API_KEY",
      "priority": 3,
      "default_model": "${NVIDIA_DEFAULT_MODEL}",
      "task_profiles": ["latency", "batch", "vision", "reasoning"]
    },
    {
      "name": "gemini",
      "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/",
      "key_env": "GEMINI_API_KEY",
      "priority": 4,
      "default_model": "${GEMINI_DEFAULT_MODEL}",
      "task_profiles": ["long_context", "vision"]
    },
    {
      "name": "openrouter",
      "endpoint": "https://openrouter.ai/api/v1",
      "key_env": "OPENROUTER_API_KEY",
      "priority": 5,
      "default_model": "openrouter/free",
      "task_profiles": ["latency", "batch", "long_context", "vision", "reasoning"]
    },
    {
      "name": "mistral",
      "endpoint": "https://api.mistral.ai/v1",
      "key_env": "MISTRAL_API_KEY",
      "model_env": "MISTRAL_DEFAULT_MODEL",
      "discover_chat_model": true,
      "priority": 6,
      "default_model": null,
      "task_profiles": ["latency", "batch", "long_context", "vision", "reasoning"]
    },
    {
      "name": "deepseek",
      "endpoint": "https://api.deepseek.com/v1",
      "key_env": "DEEPSEEK_API_KEY",
      "priority": 7,
      "default_model": "deepseek-v4-flash",
      "task_profiles": ["batch", "long_context", "reasoning"],
      "paid_overflow": true
    },
    {
      "name": "claude_max",
      "endpoint": null,
      "key_env": null,
      "priority": 8,
      "default_model": null,
      "task_profiles": ["reasoning"],
      "not_a_router_target": true,
      "execution_path": "claude -p"
    },
    {
      "name": "claude_api",
      "endpoint": "${CLAUDE_API_BASE_URL}",
      "key_env": "ANTHROPIC_API_KEY",
      "priority": 9,
      "default_model": "${CLAUDE_API_DEFAULT_MODEL}",
      "task_profiles": ["reasoning"],
      "emergency_only": true,
      "capped": true
    }
  ]
}

```
### docs/board/tasks/router-denial-surfacing.md

```
---
id: router-denial-surfacing
status: in-progress
lane: AUTO
priority: 2
phase: 0
blocked-on: none
files: router/routing.py (hot), tests/router/test_routing.py (area-hot), docs/state.md
resources: none offline
---

# router-denial-surfacing — 401/402/403 must surface, not just cool down

## Goal

`docs/blueprint.md` §3.3 (Ali's own text, applied 2 Sep 2026): "A rung that
returns 401/402/403 enters cooldown and **surfaces the denial**. It does not
silently fall through to paid work."

`router-cooldown-ledger` shipped 2 Sep with only the cooldown half. Today:

- **402** cools the provider down and then `continue`s down the ladder
  (`router/routing.py`, the 429/402/5xx branch). A payment-required rung is
  therefore indistinguishable from a busy one, and the request quietly moves
  on — possibly to a paid rung, which is the exact thing the clause forbids.
- **401/403** re-raise, but the cooldown is a **Mistral-only carve-out** by
  name. Any other provider's auth denial cools down nothing, so every
  subsequent job re-probes a key that cannot work.

## Steps

1. Generalise the 401/403 carve-out from `provider.name == "mistral"` to
   every provider. The comment explaining why a denial is not a malformed
   request already applies to all of them.
2. Decide what "surfaces" means concretely, and write it down. The ledger
   entry already carries `last_status`, so the cheapest honest answer is that
   `/status`'s provider health shows it (it does, since 2 Sep) **plus** the
   cascade not silently absorbing it. Say which of those Ali's sentence
   demands before changing control flow — if a 402 must abort the cascade,
   that changes reply behaviour on a live rung failure, and that belongs in
   the Log rather than being discovered later.
3. Tests: a 402 does not silently reach a paid rung; a 401 from any provider
   cools it down; the existing Mistral test still passes.

## Done when

Every 401/402/403 both cools the rung down and is visible without reading
logs; the suite is green; `docs/state.md`'s router rows say what changed.

```

## Response format

Answer as strict JSON and nothing else. No prose before or after, no code
fence. Exactly these keys:

{
  "verdict": "the decision or answer, one or two sentences, actionable",
  "reasoning": "why, citing the specific evidence above that drove it",
  "confidence": "high | medium | low",
  "what_would_change_this": "the concrete observation that would flip this verdict"
}

Set confidence to low rather than guessing. If the evidence provided is not
enough to decide, say exactly what is missing in what_would_change_this — that
is a useful answer, an invented one is not.