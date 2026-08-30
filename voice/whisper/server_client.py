"""HTTP client for whisper-server, the NPU Whisper backend kept warm as a server.

``voice.whisper.local_backend`` shells out to whisper-cli, which reloads the
whole 3 GB large-v3 model on every single call --
``docs/tasks/whisper-npu-build-report.md`` measured that reload at 4-8s, on
top of the transcription itself. That is fine for a benchmark run and wrong
for a chat handler replying to one message at a time. ``whisper-server.exe``
was built alongside the CLI specifically to keep the model resident between
requests; this module is the missing other half -- something that actually
talks to it.

Endpoints below are read directly out of this lane's own
``voice/whisper/src/examples/server/server.cpp`` (not guessed, not copied from
upstream docs, since this is a fork and the fork's own build is what runs):

* ``GET /health`` -- ``{"status": "ok"}`` with HTTP 200 once the model has
  finished loading, ``{"status": "loading model"}`` with HTTP 503 before that
  (server.cpp:1164-1171).
* ``POST /inference`` -- multipart form, audio in the ``file`` field
  (server.cpp:810,817), optional ``language`` and ``response_format`` fields
  (server.cpp:553-567). The default (non-``verbose_json``) response body is
  ``{"text": "..."}`` (server.cpp:1114).

Nothing here starts the server -- ``tools/start_jarvis.py`` supervises it the
same way it already supervises the bus and the tunnel. This module only ever
makes an HTTP request to a server assumed to already be running.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

import httpx

#: Arbitrary but deliberate, like tools/start_jarvis.py's singleton port: it
#: collides with neither the bus (8000), Ollama (11434), nor the singleton
#: guard (8765).
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8081

WHISPER_SERVER_HOST_ENV = "JARVIS_WHISPER_SERVER_HOST"
WHISPER_SERVER_PORT_ENV = "JARVIS_WHISPER_SERVER_PORT"


class WhisperServerError(RuntimeError):
    """Raised when whisper-server cannot transcribe a clip."""


@dataclass(frozen=True)
class WhisperServerConfig:
    """Where the warm whisper-server lives."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    timeout_seconds: float = 60.0

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "WhisperServerConfig":
        settings = os.environ if environ is None else environ
        host = (settings.get(WHISPER_SERVER_HOST_ENV) or DEFAULT_HOST).strip() or DEFAULT_HOST
        raw_port = (settings.get(WHISPER_SERVER_PORT_ENV) or str(DEFAULT_PORT)).strip()
        try:
            port = int(raw_port)
        except ValueError:
            port = DEFAULT_PORT
        return cls(host=host, port=port)


class WhisperServerClient:
    """Talks to a running whisper-server over its HTTP API."""

    def __init__(
        self,
        config: WhisperServerConfig | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config or WhisperServerConfig.from_environ()
        self._transport = transport

    def is_ready(self, *, timeout_seconds: float = 2.0) -> bool:
        """Whether the model has finished loading and the server can transcribe.

        A connection failure or any non-200 (including the documented 503
        "loading model") both mean "not ready yet" -- the caller cannot
        transcribe either way, so there is no reason to distinguish them.
        """
        try:
            with httpx.Client(transport=self._transport, timeout=timeout_seconds) as client:
                response = client.get(f"{self._config.base_url}/health")
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    def transcribe(self, wav_bytes: bytes, *, language: str | None = None) -> str:
        """Transcribe 16 kHz mono PCM WAV bytes. See voice.audio for decoding."""
        if not wav_bytes:
            raise WhisperServerError("No audio content to transcribe.")

        data = {"response_format": "json"}
        if language:
            data["language"] = language

        try:
            with httpx.Client(transport=self._transport, timeout=self._config.timeout_seconds) as client:
                response = client.post(
                    f"{self._config.base_url}/inference",
                    files={"file": ("clip.wav", wav_bytes, "audio/wav")},
                    data=data,
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise WhisperServerError("whisper-server timed out. Is the NPU still processing a prior request?") from exc
        except httpx.ConnectError as exc:
            raise WhisperServerError(
                f"whisper-server not reachable at {self._config.base_url}. Is it running?"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise WhisperServerError(
                f"whisper-server returned HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise WhisperServerError("whisper-server request failed.") from exc

        try:
            text = response.json()["text"]
        except (KeyError, ValueError, TypeError) as exc:
            raise WhisperServerError("whisper-server returned an unexpected response shape.") from exc
        if not isinstance(text, str):
            raise WhisperServerError("whisper-server returned a non-string transcript.")
        return text.strip()
