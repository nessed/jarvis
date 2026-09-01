from __future__ import annotations

from types import SimpleNamespace

import pytest

from voice import stt_fallback
from voice.stt_fallback import (
    CLOUD_FALLBACK_ENV,
    DEFAULT_STT_MODEL,
    GROQ_API_KEY_ENV,
    GROQ_BASE_URL,
    CloudSttError,
    GroqSttClient,
    GroqSttConfig,
    SttFallbackError,
    cloud_fallback_enabled,
    stt_model,
    transcribe_with_fallback,
)

WAV = b"RIFF....WAVEfmt "


class FakeLocal:
    """Stands in for WhisperServerClient."""

    def __init__(self, *, ready: bool = True, transcript: str = "salam", error: Exception | None = None):
        self._ready = ready
        self._transcript = transcript
        self._error = error
        self.transcribe_calls: list[tuple[bytes, str | None]] = []
        self.ready_calls = 0

    def is_ready(self, *, timeout_seconds: float = 2.0) -> bool:
        self.ready_calls += 1
        return self._ready

    def transcribe(self, wav_bytes: bytes, *, language: str | None = None) -> str:
        self.transcribe_calls.append((wav_bytes, language))
        if self._error is not None:
            raise self._error
        return self._transcript


class FakeCloud:
    def __init__(self, *, transcript: str = "cloud transcript", error: Exception | None = None):
        self._transcript = transcript
        self._error = error
        self.transcribe_calls: list[tuple[bytes, str | None]] = []

    def transcribe(self, wav_bytes: bytes, *, language: str | None = None) -> str:
        self.transcribe_calls.append((wav_bytes, language))
        if self._error is not None:
            raise self._error
        return self._transcript


# --- the ordering rule --------------------------------------------------------


def test_a_ready_local_backend_answers_and_the_cloud_is_never_asked() -> None:
    local, cloud = FakeLocal(transcript="mein theek hoon"), FakeCloud()

    assert transcribe_with_fallback(WAV, language="ur", local=local, cloud=cloud) == "mein theek hoon"
    assert cloud.transcribe_calls == []


def test_the_language_hint_reaches_whichever_backend_runs() -> None:
    local, cloud = FakeLocal(ready=False), FakeCloud()

    transcribe_with_fallback(WAV, language="ur", local=local, cloud=cloud)

    assert cloud.transcribe_calls == [(WAV, "ur")]


def test_the_fallback_fires_when_the_local_server_is_not_ready() -> None:
    local, cloud = FakeLocal(ready=False), FakeCloud(transcript="from groq")

    assert transcribe_with_fallback(WAV, local=local, cloud=cloud) == "from groq"
    assert local.transcribe_calls == []


def test_the_fallback_fires_when_the_local_backend_accepts_then_fails() -> None:
    """Ready-then-broken is still unavailable; nothing was transcribed."""
    local = FakeLocal(error=RuntimeError("NPU wedged"))
    cloud = FakeCloud(transcript="from groq")

    assert transcribe_with_fallback(WAV, local=local, cloud=cloud) == "from groq"


def test_a_clip_is_never_transcribed_twice() -> None:
    local, cloud = FakeLocal(transcript="local wins"), FakeCloud()

    transcribe_with_fallback(WAV, local=local, cloud=cloud)

    assert len(local.transcribe_calls) == 1
    assert cloud.transcribe_calls == []


def test_an_empty_local_transcript_is_a_result_not_a_reason_to_call_the_cloud() -> None:
    """A silent clip is correctly transcribed as nothing. Re-running it in the
    cloud would be the double-transcription this module exists to prevent, and
    would send audio off the laptop for a message with no words in it."""
    local, cloud = FakeLocal(transcript=""), FakeCloud()

    assert transcribe_with_fallback(WAV, local=local, cloud=cloud) == ""
    assert cloud.transcribe_calls == []


# --- failing loudly -----------------------------------------------------------


def test_both_backends_failing_raises_and_names_both() -> None:
    local = FakeLocal(error=RuntimeError("NPU wedged"))
    cloud = FakeCloud(error=RuntimeError("groq 500"))

    with pytest.raises(SttFallbackError) as excinfo:
        transcribe_with_fallback(WAV, local=local, cloud=cloud)

    message = str(excinfo.value)
    assert "local backend failed" in message
    assert "cloud fallback also failed" in message


def test_no_configured_cloud_backend_is_an_error_not_a_silent_blank(monkeypatch) -> None:
    """Silence is what this module replaces; it is not a fallback of its own.

    ``cloud=None`` deliberately falls through to the real resolver, so the key
    has to be removed from the environment -- the machine running the suite
    has a live GROQ_API_KEY in ``.env`` and something else in the session has
    usually loaded it by the time this runs.
    """
    monkeypatch.delenv(GROQ_API_KEY_ENV, raising=False)

    with pytest.raises(SttFallbackError) as excinfo:
        transcribe_with_fallback(WAV, local=FakeLocal(ready=False), cloud=None, allow_cloud=True)

    assert GROQ_API_KEY_ENV in str(excinfo.value)


def test_a_disabled_cloud_tier_never_sends_audio_and_says_why() -> None:
    cloud = FakeCloud()

    with pytest.raises(SttFallbackError) as excinfo:
        transcribe_with_fallback(WAV, local=FakeLocal(ready=False), cloud=cloud, allow_cloud=False)

    assert CLOUD_FALLBACK_ENV in str(excinfo.value)
    assert cloud.transcribe_calls == []


def test_only_the_exception_type_reaches_the_error_message() -> None:
    """Same discipline as the poller: a provider message could carry payload."""
    local = FakeLocal(error=RuntimeError("secret audio path C:/private/clip.wav"))
    cloud = FakeCloud(error=RuntimeError("groq said something about the key"))

    with pytest.raises(SttFallbackError) as excinfo:
        transcribe_with_fallback(WAV, local=local, cloud=cloud)

    assert "secret audio path" not in str(excinfo.value)
    assert "about the key" not in str(excinfo.value)


# --- every transition is logged -----------------------------------------------


def test_the_local_path_says_so(caplog) -> None:
    with caplog.at_level("INFO", logger="voice.stt_fallback"):
        transcribe_with_fallback(WAV, local=FakeLocal(), cloud=FakeCloud())

    assert "transcribed on the local NPU backend" in caplog.text


def test_going_to_the_cloud_is_never_silent(caplog) -> None:
    """"Did it quietly send my voice to a third party" must be answerable from a log."""
    with caplog.at_level("INFO", logger="voice.stt_fallback"):
        transcribe_with_fallback(WAV, local=FakeLocal(ready=False), cloud=FakeCloud())

    assert "falling back to cloud STT" in caplog.text
    assert "transcribed on the cloud STT fallback" in caplog.text


# --- the Groq client ----------------------------------------------------------


class FakeTranscriptions:
    def __init__(self, response, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


def _client(response=None, error=None) -> tuple[GroqSttClient, FakeTranscriptions]:
    transcriptions = FakeTranscriptions(response or SimpleNamespace(text=" salam  "), error)
    fake = SimpleNamespace(audio=SimpleNamespace(transcriptions=transcriptions))
    client = GroqSttClient(
        GroqSttConfig(api_key="test-key", model="whisper-large-v3-turbo"),
        client_factory=lambda _config: fake,
    )
    return client, transcriptions


def test_the_cloud_client_uploads_the_wav_with_a_filename_and_model() -> None:
    client, transcriptions = _client()

    assert client.transcribe(WAV, language="ur") == "salam"
    [call] = transcriptions.calls
    assert call["model"] == "whisper-large-v3-turbo"
    assert call["language"] == "ur"
    assert call["file"] == ("clip.wav", WAV, "audio/wav")


def test_the_cloud_client_omits_the_language_when_none_is_given() -> None:
    client, transcriptions = _client()

    client.transcribe(WAV)

    assert "language" not in transcriptions.calls[0]


def test_the_cloud_client_accepts_a_mapping_response_too() -> None:
    client, _ = _client(response={"text": "salam"})

    assert client.transcribe(WAV) == "salam"


def test_empty_audio_never_reaches_the_provider() -> None:
    client, transcriptions = _client()

    with pytest.raises(CloudSttError):
        client.transcribe(b"")

    assert transcriptions.calls == []


def test_a_provider_failure_is_reported_by_type_only() -> None:
    client, _ = _client(error=RuntimeError("Bearer gsk_should_never_appear"))

    with pytest.raises(CloudSttError) as excinfo:
        client.transcribe(WAV)

    assert "gsk_" not in str(excinfo.value)
    assert "RuntimeError" in str(excinfo.value)


def test_an_unexpected_response_shape_is_an_error() -> None:
    client, _ = _client(response=SimpleNamespace(nothing_useful=True))

    with pytest.raises(CloudSttError):
        client.transcribe(WAV)


# --- configuration ------------------------------------------------------------


def test_no_key_means_no_cloud_config_rather_than_a_crash() -> None:
    assert GroqSttConfig.from_environ({}) is None
    assert GroqSttConfig.from_environ({GROQ_API_KEY_ENV: "   "}) is None


def test_a_configured_key_gives_the_blueprints_model_and_groqs_base_url() -> None:
    config = GroqSttConfig.from_environ({GROQ_API_KEY_ENV: "k"})

    assert config is not None
    assert config.model == DEFAULT_STT_MODEL
    assert config.base_url == GROQ_BASE_URL


def test_the_model_is_overridable_because_groq_retires_ids() -> None:
    assert stt_model({}) == DEFAULT_STT_MODEL
    assert stt_model({"JARVIS_GROQ_STT_MODEL": "whisper-next"}) == "whisper-next"
    assert stt_model({"JARVIS_GROQ_STT_MODEL": "  "}) == DEFAULT_STT_MODEL


def test_the_cloud_tier_is_on_by_default_and_switchable_off() -> None:
    assert cloud_fallback_enabled({}) is True
    assert cloud_fallback_enabled({CLOUD_FALLBACK_ENV: "1"}) is True
    assert cloud_fallback_enabled({CLOUD_FALLBACK_ENV: "0"}) is False
    assert cloud_fallback_enabled({CLOUD_FALLBACK_ENV: "off"}) is False


def test_the_default_cloud_backend_is_absent_without_a_key(monkeypatch) -> None:
    monkeypatch.delenv(GROQ_API_KEY_ENV, raising=False)

    assert stt_fallback._default_cloud_backend() is None


def test_the_default_cloud_backend_appears_with_a_key(monkeypatch) -> None:
    monkeypatch.setenv(GROQ_API_KEY_ENV, "test-key")

    backend = stt_fallback._default_cloud_backend()

    assert isinstance(backend, GroqSttClient)
    assert backend.model == DEFAULT_STT_MODEL
