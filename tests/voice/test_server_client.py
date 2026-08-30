"""Tests for the whisper-server HTTP client.

Every test runs against httpx.MockTransport -- nothing here needs the built
whisper-server.exe, the model, or the NPU. Response shapes match
voice/whisper/src/examples/server/server.cpp exactly (see that module's
docstring for the line references), not upstream whisper.cpp docs.
"""

import pytest
import httpx

from voice.whisper.server_client import (
    WhisperServerClient,
    WhisperServerConfig,
    WhisperServerError,
)


def fake_transport(handler):
    return httpx.MockTransport(handler)


def test_is_ready_when_health_reports_ok():
    def handler(request):
        assert request.url.path == "/health"
        return httpx.Response(200, json={"status": "ok"})

    client = WhisperServerClient(transport=fake_transport(handler))
    assert client.is_ready() is True


def test_is_not_ready_while_still_loading_the_model():
    def handler(request):
        return httpx.Response(503, json={"status": "loading model"})

    client = WhisperServerClient(transport=fake_transport(handler))
    assert client.is_ready() is False


def test_is_not_ready_when_unreachable():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    client = WhisperServerClient(transport=fake_transport(handler))
    assert client.is_ready() is False


def test_transcribe_posts_the_wav_as_the_file_field_and_returns_the_text():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["content_type"] = request.headers.get("content-type", "")
        seen["body"] = request.content
        return httpx.Response(200, json={"text": "  hello from the npu  "})

    client = WhisperServerClient(transport=fake_transport(handler))
    text = client.transcribe(b"RIFF-fake-wav-bytes")

    assert text == "hello from the npu"
    assert seen["path"] == "/inference"
    assert seen["content_type"].startswith("multipart/form-data")
    assert b"RIFF-fake-wav-bytes" in seen["body"]
    assert b'name="response_format"' in seen["body"]
    assert b"json" in seen["body"]


def test_transcribe_passes_a_language_hint_when_given():
    seen = {}

    def handler(request):
        seen["body"] = request.content
        return httpx.Response(200, json={"text": "ok"})

    client = WhisperServerClient(transport=fake_transport(handler))
    client.transcribe(b"wav-bytes", language="ur")

    assert b'name="language"' in seen["body"]
    assert b"ur" in seen["body"]


def test_transcribe_rejects_empty_audio_without_any_request():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"text": "unused"})

    client = WhisperServerClient(transport=fake_transport(handler))
    with pytest.raises(WhisperServerError, match="No audio content"):
        client.transcribe(b"")
    assert calls == []


def test_transcribe_raises_a_clear_error_when_unreachable():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    client = WhisperServerClient(transport=fake_transport(handler))
    with pytest.raises(WhisperServerError, match="not reachable"):
        client.transcribe(b"wav-bytes")


def test_transcribe_raises_on_timeout():
    def handler(request):
        raise httpx.TimeoutException("timed out", request=request)

    client = WhisperServerClient(transport=fake_transport(handler))
    with pytest.raises(WhisperServerError, match="timed out"):
        client.transcribe(b"wav-bytes")


def test_transcribe_raises_on_malformed_response_shape():
    def handler(request):
        return httpx.Response(200, json={"unexpected": "shape"})

    client = WhisperServerClient(transport=fake_transport(handler))
    with pytest.raises(WhisperServerError, match="unexpected response shape"):
        client.transcribe(b"wav-bytes")


def test_config_from_environ_falls_back_to_defaults():
    config = WhisperServerConfig.from_environ({})
    assert config.host == "127.0.0.1"
    assert config.port == 8081


def test_config_from_environ_honours_overrides():
    config = WhisperServerConfig.from_environ(
        {"JARVIS_WHISPER_SERVER_HOST": "10.0.0.5", "JARVIS_WHISPER_SERVER_PORT": "9090"}
    )
    assert config.host == "10.0.0.5"
    assert config.port == 9090
    assert config.base_url == "http://10.0.0.5:9090"


def test_config_from_environ_ignores_an_unparseable_port():
    config = WhisperServerConfig.from_environ({"JARVIS_WHISPER_SERVER_PORT": "not-a-number"})
    assert config.port == 8081
