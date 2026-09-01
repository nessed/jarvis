"""Cloud STT for when the NPU path is down: local first, Groq second, never both.

Blueprint §2 names Groq Whisper as the STT fallback. Until now a dead
``whisper-server`` meant an inbound voice note produced silence — the handler
logged it and moved on, and Ali got nothing back for a message he had spoken.

Q8, answered by Ali on 1 September 2026: **voice owns its own small Groq STT
client.** The provider router is not touched and stays chat-completions-only.
That is why this module reads ``GROQ_API_KEY`` itself and names its own base
URL instead of borrowing the router's Groq rung — the router's job is routing
chat completions down a cost ladder, and an audio endpoint on the same host is
not that.

The ordering rule
-----------------

Local NPU first, always, and not merely because it is free. It is the only
path where a private voice note never leaves the machine.

The fallback fires when the local path is *unavailable* — the server is not
answering ``/health``, or it accepted the clip and then failed. It does not
fire because the transcript was empty: an empty transcript is a **result**,
the correct one for a silent or unintelligible clip, and re-transcribing it in
the cloud would be exactly the double-transcription this module exists to rule
out. One clip is transcribed at most once, by exactly one backend.

If both are unavailable the caller gets an exception naming both failures.
Silence is what this replaces; it is not something to fall back to.

Privacy
-------

**Audio leaves the laptop only on the fallback path.** A WhatsApp voice note
has already transited Meta by the time it reaches here, so Groq is not a new
*class* of exposure, but it is a new party and saying so is the point of this
paragraph. ``JARVIS_STT_CLOUD_FALLBACK=0`` disables the cloud tier entirely
and restores the old behaviour, where a dead whisper-server means no reply.

Nothing here touches memory, embeddings, or extraction, so ``CLAUDE.md``'s
loopback-only rule for those is untouched — that rule is about the corpus,
not about a single inbound message the user just spoke into their phone.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

logger = logging.getLogger(__name__)

#: Groq's OpenAI-compatible base URL. Named here rather than imported from
#: ``router/providers.yaml`` on purpose (Q8): voice does not depend on the
#: router's roster, and the router does not grow an audio concern.
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_API_KEY_ENV = "GROQ_API_KEY"

#: Blueprint §2's choice. An env override exists because Groq retires model
#: IDs on weeks of notice — ``llama-3.1-8b-instant`` went that way in 2026 —
#: and a hardcoded ID with no escape hatch is how a working fallback becomes a
#: 404 nobody notices until the day it is needed.
STT_MODEL_ENV = "JARVIS_GROQ_STT_MODEL"
DEFAULT_STT_MODEL = "whisper-large-v3-turbo"

CLOUD_FALLBACK_ENV = "JARVIS_STT_CLOUD_FALLBACK"

DEFAULT_TIMEOUT_SECONDS = 60.0


class SttFallbackError(RuntimeError):
    """Raised when neither the local nor the cloud backend could transcribe."""


class CloudSttError(RuntimeError):
    """Raised when the cloud backend alone could not transcribe."""


def cloud_fallback_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Whether a voice note may be sent to Groq when the NPU path is down.

    Default **on**: Ali answered Q8 = A. Setting it to ``0`` restores the
    pre-fallback behaviour, in which a dead whisper-server means a voice note
    gets no reply at all — which is a real thing to want, and cheaper to reach
    for than editing code.
    """
    settings = os.environ if environ is None else environ
    return settings.get(CLOUD_FALLBACK_ENV, "1").strip().lower() in {"1", "true", "yes", "on"}


def stt_model(environ: Mapping[str, str] | None = None) -> str:
    settings = os.environ if environ is None else environ
    return (settings.get(STT_MODEL_ENV) or DEFAULT_STT_MODEL).strip() or DEFAULT_STT_MODEL


@dataclass(frozen=True)
class GroqSttConfig:
    api_key: str
    model: str = DEFAULT_STT_MODEL
    base_url: str = GROQ_BASE_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "GroqSttConfig | None":
        """Config, or ``None`` if no key is configured. Never raises, never logs the key."""
        settings = os.environ if environ is None else environ
        key = (settings.get(GROQ_API_KEY_ENV) or "").strip()
        if not key:
            return None
        return cls(api_key=key, model=stt_model(settings))


class GroqSttClient:
    """Groq's OpenAI-compatible audio transcription endpoint.

    ``client_factory`` is injected so the whole class is testable without the
    ``openai`` package doing network I/O; the default builds a real client
    lazily, at call time, so importing this module costs nothing.
    """

    def __init__(
        self,
        config: GroqSttConfig,
        *,
        client_factory: Callable[[GroqSttConfig], Any] | None = None,
    ) -> None:
        self._config = config
        self._client_factory = client_factory or _default_openai_client

    @property
    def model(self) -> str:
        return self._config.model

    def transcribe(self, wav_bytes: bytes, *, language: str | None = None) -> str:
        """Transcribe 16 kHz mono PCM WAV bytes. Same contract as the local client."""
        if not wav_bytes:
            raise CloudSttError("No audio content to transcribe.")
        client = self._client_factory(self._config)
        request: dict[str, Any] = {
            "model": self._config.model,
            # The SDK's (filename, content, content_type) upload form. A
            # filename is required -- Groq rejects an upload without a
            # recognisable extension -- and the bytes are already the WAV
            # voice/audio.py produced for the local backend, so both tiers
            # transcribe byte-identical input.
            "file": ("clip.wav", wav_bytes, "audio/wav"),
        }
        if language:
            request["language"] = language
        try:
            response = client.audio.transcriptions.create(**request)
        except Exception as exc:  # SDK exception types vary; the type is the diagnostic.
            raise CloudSttError(f"Groq STT request failed ({type(exc).__name__}).") from exc

        text = getattr(response, "text", None)
        if text is None and isinstance(response, Mapping):
            text = response.get("text")
        if not isinstance(text, str):
            raise CloudSttError("Groq STT returned an unexpected response shape.")
        # Explicit: the SDK hands back ``str``, already decoded. Urdu comes
        # back as real code points, and nothing in this path re-encodes it
        # through a Windows console codec.
        return text.strip()


def _default_openai_client(config: GroqSttConfig) -> Any:
    # Imported here, not at module scope: this module is imported by the
    # WhatsApp handler, which runs on every message, and the openai package is
    # heavy for a path that most messages never take.
    from openai import OpenAI

    return OpenAI(
        api_key=config.api_key, base_url=config.base_url, timeout=config.timeout_seconds
    )


class LocalBackend(Protocol):
    def is_ready(self, *, timeout_seconds: float = ...) -> bool: ...
    def transcribe(self, wav_bytes: bytes, *, language: str | None = ...) -> str: ...


class CloudBackend(Protocol):
    def transcribe(self, wav_bytes: bytes, *, language: str | None = ...) -> str: ...


def transcribe_with_fallback(
    wav_bytes: bytes,
    *,
    language: str | None = None,
    local: LocalBackend | None = None,
    cloud: CloudBackend | None = None,
    allow_cloud: bool | None = None,
) -> str:
    """Transcribe one clip on exactly one backend, preferring the local NPU.

    Every transition is logged at INFO, because "which backend answered" is
    the first question asked when a transcript looks wrong, and the second is
    "did it silently go to the cloud". Neither should require a debugger.

    Raises :class:`SttFallbackError` when no backend could produce a
    transcript, naming what each one did. That is deliberately louder than the
    behaviour it replaces, which was to treat a dead server as a blank
    transcript and reply with nothing.
    """
    local_backend = local if local is not None else _default_local_backend()
    use_cloud = cloud_fallback_enabled() if allow_cloud is None else allow_cloud

    local_failure: str | None = None
    if local_backend.is_ready():
        try:
            transcript = local_backend.transcribe(wav_bytes, language=language)
        except Exception as exc:
            # Accepted the clip, then failed. That is unavailability, so the
            # fallback is allowed -- but only once, and only because nothing
            # was transcribed.
            local_failure = f"local backend failed ({type(exc).__name__})"
            logger.warning("local STT failed mid-request (%s)", type(exc).__name__)
        else:
            logger.info("transcribed on the local NPU backend")
            return transcript
    else:
        local_failure = "local backend not ready"
        logger.info("local STT backend is not ready")

    if not use_cloud:
        raise SttFallbackError(
            f"{local_failure}, and the cloud fallback is disabled "
            f"({CLOUD_FALLBACK_ENV}=0)."
        )

    cloud_backend = cloud if cloud is not None else _default_cloud_backend()
    if cloud_backend is None:
        raise SttFallbackError(
            f"{local_failure}, and no cloud fallback is configured "
            f"({GROQ_API_KEY_ENV} is not set)."
        )

    logger.info("falling back to cloud STT (%s)", local_failure)
    try:
        transcript = cloud_backend.transcribe(wav_bytes, language=language)
    except Exception as exc:
        raise SttFallbackError(
            f"{local_failure}, and the cloud fallback also failed "
            f"({type(exc).__name__})."
        ) from exc
    logger.info("transcribed on the cloud STT fallback")
    return transcript


def _default_local_backend() -> LocalBackend:
    from voice.whisper.server_client import WhisperServerClient

    return WhisperServerClient()


def _default_cloud_backend() -> CloudBackend | None:
    config = GroqSttConfig.from_environ()
    return None if config is None else GroqSttClient(config)
