"""OpenAI-compatible provider routing with runtime rate-limit awareness."""

from __future__ import annotations

import asyncio
import email.utils
import json
import logging
import os
import re
import threading
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from time import monotonic
from typing import Any, Protocol


TASK_PROFILES = frozenset({"latency", "batch", "long_context", "vision", "reasoning"})
PEAK_DEEPSEEK_WINDOWS_UTC = ((1, 4), (6, 10))
DEFAULT_BACKOFF_SECONDS = 60

#: Per-call wall-clock budget, in seconds, for a completion on the ``latency``
#: profile — the interactive path, where a person is waiting on a phone.
#: Env: ``JARVIS_ROUTER_CALL_TIMEOUT_SECONDS``.
DEFAULT_CALL_TIMEOUT_SECONDS = 20.0

#: The same budget for everything that is not ``latency``: batch, long_context,
#: vision, reasoning. Nobody is waiting on these, and a long-context call is
#: legitimately slow. Env: ``JARVIS_ROUTER_BATCH_TIMEOUT_SECONDS``.
DEFAULT_BATCH_TIMEOUT_SECONDS = 120.0

#: How many per-call budgets an interactive cascade may spend in total. Two, so
#: a ``latency`` request gets one attempt and *one* deliberate fallback before
#: the deadline stops it — Astra §5.3: "at most one deliberate fallback inside
#: an overall interaction deadline". Rungs that fail instantly (no model, an
#: immediate 401) cost almost no wall time and so do not consume the budget;
#: the deadline counts seconds, not attempts.
INTERACTION_DEADLINE_CALL_BUDGETS = 2

logger = logging.getLogger(__name__)


class RouterError(RuntimeError):
    """Base routing error."""


class NoEligibleProvider(RouterError):
    """No configured, available provider can handle a request."""


class RouterDeadlineExceeded(NoEligibleProvider):
    """The interaction budget ran out before the ladder did.

    Raised only on the ``latency`` profile, and only *before* an attempt: the
    router will not start a call it already knows cannot finish inside the
    budget a waiting person has. The rungs it did not reach are named, because
    "we ran out of time" and "nothing was eligible" are different problems and
    the second one is the only one the bare ``NoEligibleProvider`` message fits.

    A subclass of :class:`NoEligibleProvider` for the same reason
    :class:`ProviderDenied` is: ``executor/poller.py`` catches bare
    ``Exception``, and every existing caller keyed on ``NoEligibleProvider``
    keeps behaving as it did.
    """


#: The statuses blueprint §3.3 calls a *denial*: a rung saying "not you"
#: (401), "not paid for" (402), or "not allowed" (403). Distinct from 429 and
#: 5xx, which say "not now" — those are about capacity, these are about
#: entitlement, and only these bar the paid rungs. Grouped as one set because
#: the blueprint groups them; splitting the grouping would be a change to a
#: specified decision, not an implementation detail.
DENIAL_STATUSES = frozenset({401, 402, 403})

#: Blueprint §3.3: "Rungs are ordered by cost class first (free-tier, then
#: trial/credit, then paid)". The tuple *is* the ordering — a rung's class
#: decides its tier before anything else does, and nothing but an explicitly
#: urgent job crosses a boundary.
#:
#: "trial" exists because Cerebras stopped being free in mid-2026 and became a
#: one-time $5 credit that expires (blueprint, corrected 2 Sep 2026). A static
#: priority integer could not say that, which is why this field exists.
COST_CLASS_ORDER = ("free", "trial", "paid")
DEFAULT_COST_CLASS = "paid"

#: How many recent successful calls a (provider, task_profile) bucket keeps.
#: Bounded rather than time-decayed on purpose: a decay constant is a number
#: nobody has specified, and a short window is recent by construction.
LATENCY_WINDOW = 20

#: How many samples a bucket needs before its median may reorder anything.
#: A "p50" over one call is just "the last call", and an order that flips on
#: one cold start is worse than no order at all. Five is the smallest count
#: whose median survives two outliers; below it the rung keeps its manifest
#: priority, which is a defensible order rather than a guess.
MIN_LATENCY_SAMPLES = 5


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
    # Defaults to "paid", not "free". A rung whose manifest entry forgets to
    # say what it costs must not be treated as free and promoted above rungs
    # that are: the safe failure here is over-caution about money.
    cost_class: str = DEFAULT_COST_CLASS


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

    def __init__(self, base_url: str, api_key: str, *, timeout: float | None = None, environ: Mapping[str, str] | None = None):
        """Construct the SDK client with *this* codebase's retry and timeout policy.

        Two SDK defaults are wrong for a router that already has both
        behaviours of its own:

        ``max_retries=2`` retries inside a call the router is *also* prepared
        to retry, on a ladder the poller is *also* prepared to retry. A hung
        provider was therefore retried three deep while the worker's own 300 s
        job timeout fired underneath the whole stack, leaving the thread
        running (``executor/poller.py``, ``_run_with_timeout``). One layer owns
        fallback and it is the router: ``max_retries=0``.

        ``timeout=600`` is twice the job timeout, so the SDK's own limit could
        never be the thing that fired. ``route()`` passes a per-call ``timeout``
        sized to the task profile, which is the budget that matters; this
        client-level default only bounds the calls ``route()`` does not pass
        one to — today, ``list_chat_models`` during model discovery.
        """
        # Import lazily so config/tests do not need credentials or the SDK installed.
        from openai import AsyncOpenAI

        environ = environ if environ is not None else os.environ
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            max_retries=0,
            timeout=timeout if timeout is not None else _batch_timeout_seconds(environ),
        )
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


def _positive_float(environ: Mapping[str, str], name: str, default: float) -> float:
    """An env-configured number of seconds, or ``default`` if it is unusable.

    A blank, malformed, zero or negative value falls back and says so once:
    the alternative is a router whose deadline is whatever typo is in ``.env``,
    and a zero timeout would fail every call instantly.
    """
    raw = (environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if value <= 0:
        logger.warning("%s=%r is not a positive number of seconds; using %s", name, raw, default)
        return default
    return value


def _call_timeout_seconds(environ: Mapping[str, str], task_profile: str) -> float:
    """The per-call budget for one profile.

    ``latency`` is the interactive path and gets the short budget; everything
    else is background work and gets the long one.
    """
    if task_profile == "latency":
        return _positive_float(environ, "JARVIS_ROUTER_CALL_TIMEOUT_SECONDS", DEFAULT_CALL_TIMEOUT_SECONDS)
    return _batch_timeout_seconds(environ)


def _batch_timeout_seconds(environ: Mapping[str, str]) -> float:
    return _positive_float(environ, "JARVIS_ROUTER_BATCH_TIMEOUT_SECONDS", DEFAULT_BATCH_TIMEOUT_SECONDS)


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
            cost_class=_cost_class(item),
        )
        for item in raw
    ]


def _cost_class(item: Mapping[str, Any]) -> str:
    """A manifest entry's cost class, defaulting to the expensive assumption.

    An unrecognised or missing value is *not* an error — a manifest edit must
    never be able to stop the router from starting — but it is treated as
    ``paid``, so the mistake costs a rung its priority rather than costing
    money.
    """
    declared = str(item.get("cost_class", "")).strip().lower()
    return declared if declared in COST_CLASS_ORDER else DEFAULT_COST_CLASS


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
        # Process-lifetime, beside the cooldown ledger and for the same reason
        # Ali gave for that one (Q10c): a file would hand a fresh process a
        # belief about a provider that may no longer be true. A latency
        # baseline goes stale more slowly than a cooldown, but correcting for
        # that needs a decay window nobody has specified, and inventing one
        # would be inventing policy. Persisting this is a later question, and
        # answering it wants observed variance rather than a guess — which is
        # what these buckets, reported through ``health_snapshot``, produce.
        # Reasoning: docs/consults/2026-09-02-router-p50-storage-scope/
        self._latencies: dict[tuple[str, str], deque[float]] = defaultdict(
            lambda: deque(maxlen=LATENCY_WINDOW)
        )
        # Keyed on (base_url, api_key), so a rotated key builds a new client
        # rather than reusing one authenticated as the old one. Process
        # lifetime, because ``shared_router()`` is: see ``_client_for``.
        #
        # This dict holds API keys. Nothing may render it — see ``__repr__``.
        self._clients: dict[tuple[str, str], ChatClient] = {}
        # provider name -> the model ``list_chat_models`` last returned. Only
        # successful discoveries land here: see ``_model_for``.
        self._discovered_models: dict[str, str] = {}

    def __repr__(self) -> str:
        """Deliberately explicit, and deliberately boring.

        ``self._clients`` is keyed on ``(base_url, api_key)``, so any default
        or generated repr that walks this object's attributes would print live
        provider keys into a traceback, a log line, or a debugger transcript.
        ``object.__repr__`` does not do that today; this makes it impossible
        for a later ``@dataclass`` or attribute dump to start.
        """
        return f"<ProviderRouter providers={len(self._providers)}>"

    def _client_for(self, provider: Provider) -> ChatClient:
        """The cached client for a provider's current endpoint and key.

        ``route()`` used to call ``self._client_factory(...)`` inside its
        per-provider loop, so every routed request built a fresh
        ``AsyncOpenAI``, which is a fresh ``httpx.AsyncClient``, which is a
        fresh TLS handshake. Measured from this laptop on 4 Sep 2026:
        openrouter 0.45 s, groq 0.92 s, mistral 0.57 s, deepseek 0.38 s per
        connection — and a single text reply makes *two* routed completions
        (classify, then reply), so it was 1-2 s per message spent before the
        model saw a token.

        Reuse only pays if the connection pool outlives the call, which means
        it must outlive the event loop too: an ``httpx.AsyncClient`` pool is
        bound to the loop it was first used on. ``asyncio.run`` per call closes
        that loop, so synchronous callers must go through
        ``router.route_sync`` (``router/sync_bridge.py``) rather than
        ``asyncio.run(route(...))``.

        Membership test, not ``.get``: several tests inject a factory that
        returns ``None``, and ``None`` is a cached value like any other.
        """
        cache_key = (self._endpoint_for(provider), self._key_for(provider))
        if cache_key not in self._clients:
            self._clients[cache_key] = self._client_factory(*cache_key)
        return self._clients[cache_key]

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
        # Cost class major, profile preference minor — and the second must
        # happen *inside* the first, not across it.
        #
        # This used to partition the whole eligible list into
        # ``preferred + others``, which is a promotion across cost classes: a
        # paid rung that declared the profile sorted above a free rung that
        # did not, which is exactly what §3.3's "never promotes a paid rung
        # above a free one that is eligible" forbids. Adding ``cost_class``
        # without moving the partition inside it would have left that intact.
        ordered: list[Provider] = []
        for cost_class in COST_CLASS_ORDER:
            in_class = [p for p in eligible if p.cost_class == cost_class]
            ordered.extend(
                self._by_p50([p for p in in_class if task_profile in p.task_profiles], task_profile)
            )
            ordered.extend(
                self._by_p50(
                    [p for p in in_class if task_profile not in p.task_profiles], task_profile
                )
            )
        return ordered

    def _by_p50(self, candidates: Sequence[Provider], task_profile: str) -> list[Provider]:
        """Fastest first, among those with enough samples to have an opinion.

        Applied strictly inside one cost class and one profile group, so
        §3.3's class-major invariant is structurally untouched: this can only
        reorder rungs within the group they were already in, never move one
        between tiers.

        A rung with fewer than ``MIN_LATENCY_SAMPLES`` keeps its manifest
        priority and sorts after every measured one. Measured beating
        unmeasured is deliberate: a rung with a known median has earned its
        place, while a priority integer is a number someone typed once.
        """

        def key(provider: Provider) -> tuple[bool, float, int]:
            p50 = self.p50_seconds(provider.name, task_profile)
            return (p50 is None, p50 if p50 is not None else 0.0, provider.priority)

        return sorted(candidates, key=key)

    def p50_seconds(self, provider_name: str, task_profile: str) -> float | None:
        """The measured median for one rung on one profile, or ``None``.

        ``None`` means "not enough evidence to have an opinion", which is a
        different answer from "slow" and is treated as one by ``_by_p50``.
        """
        samples = self._latencies.get((provider_name, task_profile))
        if not samples or len(samples) < MIN_LATENCY_SAMPLES:
            return None
        return median(samples)

    def _record_latency(self, provider: Provider, task_profile: str, seconds: float) -> None:
        """Record one *successful* completion's wall time.

        Success only, on purpose. A 429 measures how fast a provider says no,
        and a 5xx measures how fast it falls over; folding either into a
        service-latency median would make the rung that rejects fastest look
        like the rung that serves fastest.
        """
        if seconds >= 0:
            self._latencies[(provider.name, task_profile)].append(float(seconds))

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

        # A caller that names its own timeout owns it; the budget below is then
        # measured against the caller's number, not the profile's.
        # A caller that names its own timeout owns it, ``None`` included --
        # that is how a caller says "no deadline", and the wall-clock bound
        # below stands down with it.
        if "timeout" in request_options:
            call_timeout = request_options["timeout"]
        else:
            call_timeout = _call_timeout_seconds(self._environ, task_profile)
            request_options = {**request_options, "timeout": call_timeout}
        deadline = None if call_timeout is None else self._interaction_deadline(task_profile, float(call_timeout))
        cascade_started = self._clock()

        failures: list[str] = []
        # Per request, never persistent. The cooldown ledger already handles
        # repetition across requests; barring the paid rungs persistently would
        # let one bad key disable paid overflow indefinitely.
        denials: list[str] = []
        for index, provider in enumerate(candidates):
            # The interaction budget, checked before the attempt for the same
            # reason the paid boundary is: after it, the time is already spent.
            # Never on the first rung — there is always budget for one attempt,
            # and a request that reached here is a request we mean to make.
            if deadline is not None and index and self._clock() - cascade_started + float(call_timeout) > deadline:
                raise RouterDeadlineExceeded(
                    f"the {task_profile} interaction budget of {deadline:g}s would be exceeded by trying "
                    f"{provider.name}, so the cascade stopped: " + ("; ".join(failures) or "no failures recorded")
                )
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
                attempt = self._attempt(
                    provider, task_profile, messages, model=model, request_options=request_options
                )
                # The per-call ``timeout=`` above is httpx's, and httpx's
                # timeouts are per *operation* -- connect, then each read --
                # not a budget for the whole request. A provider that dribbles
                # a response out a few bytes at a time never trips a 20 s read
                # timeout and can run for minutes. Observed 9 Sep 2026 while
                # measuring something else: a ``latency`` classify call took
                # **92.3 s** on a tree that already had these deadlines.
                #
                # This is the wall clock the profile actually promises. It also
                # covers ``_model_for``'s discovery round trip, which is inside
                # the attempt and was otherwise bounded only by the client's
                # 120 s default.
                #
                # ``asyncio.wait_for`` raises the builtin ``TimeoutError``,
                # which ``_is_transport_failure`` already treats as "this rung
                # did not answer": the rung cools down and the cascade falls
                # through, exactly as for a read timeout.
                if call_timeout is None:
                    routed = await attempt
                else:
                    routed = await asyncio.wait_for(attempt, timeout=float(call_timeout))
                if routed is None:
                    failures.append(f"{provider.name}: no model configured")
                    continue
                return routed
            except Exception as exc:  # SDK exception types intentionally vary by provider.
                status, headers = _response_metadata(exc)
                denied = status in DENIAL_STATUSES
                if status is None and _is_transport_failure(exc):
                    # A call that timed out or never connected carries no HTTP
                    # status, so without this it took the ``raise`` branch and
                    # aborted a cascade that still had rungs left. That was
                    # survivable while the SDK retried twice inside the call;
                    # with ``max_retries=0`` and a real per-call deadline it is
                    # not, and the deadline exists precisely so the router can
                    # give up on one rung and try the next. A hang says "not
                    # now" every bit as much as a 503 does, so it is treated as
                    # one: cool the rung down, fall through.
                    self._record_cooldown(provider, status, headers)
                    failures.append(f"{provider.name}: {type(exc).__name__}")
                    continue
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

    async def _attempt(
        self,
        provider: Provider,
        task_profile: str,
        messages: Sequence[Mapping[str, Any]],
        *,
        model: str | None,
        request_options: Mapping[str, Any],
    ) -> RoutedResult | None:
        """One rung's whole turn: resolve its model, call it, record what happened.

        ``None`` means the rung could not name a model, which is a skip rather
        than a failure. Split out of ``route()`` so the wall-clock bound can
        wrap the model lookup and the completion together -- a rung that spends
        the budget discovering a model has spent the budget.
        """
        client = self._client_for(provider)
        provider_model = model or await self._model_for(provider, client)
        if not provider_model:
            return None
        started = self._clock()
        response = await client.create_chat_completion(
            model=provider_model, messages=messages, **request_options
        )
        self._record_latency(provider, task_profile, self._clock() - started)
        self.health[provider.name].last_status = 200
        self._record_response_headers(provider, getattr(client, "last_response_headers", {}))
        return RoutedResult(provider=provider.name, model=provider_model, response=response)

    def _interaction_deadline(self, task_profile: str, call_timeout: float) -> float | None:
        """The whole-cascade budget, or ``None`` where there is not one.

        Only ``latency`` has one. A batch job walking the full ladder is the
        ladder doing its job; an interactive reply walking it is a person
        watching a phone do nothing, and Astra §5.3 asks for at most one
        deliberate fallback inside an overall deadline. Two call budgets is
        exactly that — one attempt, one fallback — and it moves automatically
        when the operator retunes ``JARVIS_ROUTER_CALL_TIMEOUT_SECONDS``,
        so there is no second number to keep in step with the first.
        """
        if task_profile != "latency":
            return None
        return call_timeout * INTERACTION_DEADLINE_CALL_BUDGETS

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
            return await self._discovered_model_for(provider, client)
        return provider.default_model

    async def _discovered_model_for(self, provider: Provider, client: ChatClient) -> str | None:
        """Mistral's model ID, asked for once per process rather than once per request.

        Measured 4 Sep 2026 before this existed: three ``route()`` calls on one
        router made three ``models.list()`` round trips. That is a second HTTP
        request in front of every single Mistral completion, on the rung whose
        whole reason for discovering is that its roster is not ours to guess.

        Cached for the router's lifetime, which ``shared_router()`` makes the
        process's — the same scope, and the same reasoning, as the cooldown
        ledger. A roster change mid-process is not a real risk here: if the
        cached ID stops being served, the provider answers with a status the
        cascade already handles, and a restart re-discovers.

        **Only a successful discovery is cached.** A raise propagates (route()
        turns a 4xx/5xx into a cooldown), and an empty roster returns ``None``
        without being remembered, so a workspace that gains access later is
        not locked out by one bad answer.
        """
        if (cached := self._discovered_models.get(provider.name)) is not None:
            return cached
        discover = getattr(client, "list_chat_models", None)
        if discover is None:
            return None
        available = await discover()
        if not available:
            return None
        self._discovered_models[provider.name] = available[0]
        return available[0]

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


#: Exception class names that mean "this rung did not answer" rather than
#: "this rung said no". Matched by name across the exception's MRO instead of
#: by ``isinstance``, because ``routing.py`` imports the OpenAI SDK lazily (so
#: config and tests need neither credentials nor the package) and because the
#: adjacent code already notes that SDK exception types vary by provider —
#: httpx's, the SDK's wrappers around them, and a bare ``asyncio`` timeout all
#: reach this line for the same underlying event.
TRANSPORT_FAILURE_CLASS_NAMES = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "TimeoutError",
        "TimeoutException",
        "TransportError",
        "WriteTimeout",
    }
)


def _is_transport_failure(exc: BaseException) -> bool:
    return any(cls.__name__ in TRANSPORT_FAILURE_CLASS_NAMES for cls in type(exc).__mro__)


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
