import json

import httpx
import pytest

from bus.whatsapp_client import (
    WhatsAppClient,
    WhatsAppClientConfig,
    WhatsAppReceiveError,
    WhatsAppSendError,
)


def fake_transport(handler):
    return httpx.MockTransport(handler)


def test_send_text_message_posts_to_the_correct_graph_api_endpoint_and_returns_message_id():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={"messages": [{"id": "wamid.generic-id"}]})

    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(handler))

    message_id = client.send_text_message(to="15550001111", text="Hello from the generic test.")

    assert message_id == "wamid.generic-id"
    assert seen == {
        "url": "https://graph.facebook.com/v21.0/1234567890/messages",
        "payload": {
            "messaging_product": "whatsapp",
            "to": "15550001111",
            "type": "text",
            "text": {"body": "Hello from the generic test."},
        },
        "authorization": "Bearer a-generic-test-token",
    }


def test_show_typing_indicator_marks_the_inbound_message_read_with_metas_documented_payload():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={"success": True})

    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(handler))

    client.show_typing_indicator(message_id="wamid.inbound-id")

    assert seen == {
        "url": "https://graph.facebook.com/v21.0/1234567890/messages",
        "payload": {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": "wamid.inbound-id",
            "typing_indicator": {"type": "text"},
        },
        "authorization": "Bearer a-generic-test-token",
    }


def test_show_typing_indicator_requires_an_inbound_message_id():
    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(lambda request: pytest.fail("must not post")))

    with pytest.raises(WhatsAppSendError, match="Inbound WhatsApp message id"):
        client.show_typing_indicator(message_id="  ")


def test_config_from_environ_requires_both_settings():
    with pytest.raises(WhatsAppSendError, match="META_PHONE_NUMBER_ID"):
        WhatsAppClientConfig.from_environ({})
    with pytest.raises(WhatsAppSendError, match="META_PHONE_NUMBER_ID"):
        WhatsAppClientConfig.from_environ({"META_ACCESS_TOKEN": "token-only"})

    config = WhatsAppClientConfig.from_environ(
        {"META_PHONE_NUMBER_ID": "1234567890", "META_ACCESS_TOKEN": "a-generic-test-token"}
    )
    assert config.phone_number_id == "1234567890"
    assert config.access_token == "a-generic-test-token"


def test_send_text_message_rejects_empty_recipient_or_text():
    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(lambda request: httpx.Response(200, json={})))

    with pytest.raises(WhatsAppSendError, match="Recipient"):
        client.send_text_message(to="  ", text="hello")
    with pytest.raises(WhatsAppSendError, match="Message text"):
        client.send_text_message(to="15550001111", text="   ")


def test_http_error_surfaces_graph_api_code_and_message_but_not_the_token():
    def handler(request):
        return httpx.Response(401, json={"error": {"code": 190, "message": "Invalid OAuth access token."}})

    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(handler))

    with pytest.raises(WhatsAppSendError) as exc_info:
        client.send_text_message(to="15550001111", text="hello")

    message = str(exc_info.value)
    assert "code=190" in message
    assert "Invalid OAuth access token" in message
    assert "a-generic-test-token" not in message


def test_connect_error_is_actionable_and_non_secret():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(handler))

    with pytest.raises(WhatsAppSendError, match="could not reach the Graph API"):
        client.send_text_message(to="15550001111", text="hello")


def test_malformed_success_response_raises_a_clear_error():
    def handler(request):
        return httpx.Response(200, json={"unexpected": "shape"})

    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(handler))

    with pytest.raises(WhatsAppSendError, match="unexpected response shape"):
        client.send_text_message(to="15550001111", text="hello")


def test_timeout_is_actionable_and_non_secret():
    def handler(request):
        raise httpx.TimeoutException("timed out", request=request)

    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(handler))

    with pytest.raises(WhatsAppSendError, match="timed out") as exc_info:
        client.send_text_message(to="15550001111", text="hello")

    assert "a-generic-test-token" not in str(exc_info.value)


def test_non_json_error_body_surfaces_the_status_code_without_the_raw_body():
    def handler(request):
        return httpx.Response(500, content=b"<html>upstream error, not JSON</html>")

    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(handler))

    with pytest.raises(WhatsAppSendError) as exc_info:
        client.send_text_message(to="15550001111", text="hello")

    message = str(exc_info.value)
    assert "HTTP 500" in message
    assert "non-JSON error body" in message
    assert "upstream error" not in message
    assert "a-generic-test-token" not in message


def test_send_voice_note_uploads_media_then_sends_it_referencing_the_returned_id():
    """The two-call shape is the point: upload returns an id, the message uses it."""
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "media-id-999"})
        return httpx.Response(200, json={"messages": [{"id": "wamid.voice-note"}]})

    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(handler))

    message_id = client.send_voice_note(to="15550001111", audio=b"OggS-fake-opus-bytes")

    assert message_id == "wamid.voice-note"
    assert len(calls) == 2
    assert str(calls[0].url) == "https://graph.facebook.com/v21.0/1234567890/media"
    assert str(calls[1].url) == "https://graph.facebook.com/v21.0/1234567890/messages"
    assert json.loads(calls[1].content) == {
        "messaging_product": "whatsapp",
        "to": "15550001111",
        "type": "audio",
        # voice=True is what makes WhatsApp render a playable note rather than
        # a file attachment, so it is asserted rather than assumed.
        "audio": {"id": "media-id-999", "voice": True},
    }


def test_upload_media_sends_multipart_with_the_messaging_product_field():
    seen = {}

    def handler(request):
        seen["content_type"] = request.headers.get("content-type", "")
        seen["body"] = request.content
        return httpx.Response(200, json={"id": "media-id-1"})

    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(handler))

    media_id = client.upload_media(content=b"bytes", mime_type="audio/ogg", filename="reply.ogg")

    assert media_id == "media-id-1"
    assert seen["content_type"].startswith("multipart/form-data")
    assert b"whatsapp" in seen["body"]
    assert b"reply.ogg" in seen["body"]


def test_send_voice_note_does_not_send_a_message_when_the_upload_fails():
    """A failed upload must not produce a message referencing a nonexistent id."""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400, json={"error": {"message": "bad media"}})

    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(handler))

    with pytest.raises(WhatsAppSendError) as excinfo:
        client.send_voice_note(to="15550001111", audio=b"bytes")

    assert "media upload failed" in str(excinfo.value).lower()
    assert len(calls) == 1


def test_upload_media_rejects_empty_content_before_any_request():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "unused"})

    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(handler))

    with pytest.raises(WhatsAppSendError):
        client.upload_media(content=b"", mime_type="audio/ogg", filename="x.ogg")
    assert calls == []


def test_send_voice_note_rejects_a_blank_recipient_before_uploading():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "unused"})

    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(handler))

    with pytest.raises(WhatsAppSendError):
        client.send_voice_note(to="   ", audio=b"bytes")
    assert calls == []


def test_download_media_resolves_the_id_to_a_url_then_fetches_it_with_the_same_token():
    """Meta's documented two-call shape: id -> short-lived URL -> bytes."""
    calls = []

    def handler(request):
        calls.append(request)
        if str(request.url).endswith("/media-id-777"):
            return httpx.Response(
                200,
                json={
                    "url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/fake",
                    "mime_type": "audio/ogg; codecs=opus",
                },
            )
        return httpx.Response(200, content=b"OggS-fake-opus-bytes")

    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(handler))

    content, mime_type = client.download_media(media_id="media-id-777")

    assert content == b"OggS-fake-opus-bytes"
    assert mime_type == "audio/ogg; codecs=opus"
    assert len(calls) == 2
    assert str(calls[0].url) == "https://graph.facebook.com/v21.0/media-id-777"
    assert calls[0].headers.get("authorization") == "Bearer a-generic-test-token"
    assert str(calls[1].url) == "https://lookaside.fbsbx.com/whatsapp_business/attachments/fake"
    assert calls[1].headers.get("authorization") == "Bearer a-generic-test-token"


def test_download_media_rejects_a_blank_media_id_before_any_request():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"url": "https://example.invalid/x"})

    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(handler))

    with pytest.raises(WhatsAppReceiveError, match="Media id"):
        client.download_media(media_id="   ")
    assert calls == []


def test_download_media_raises_on_a_malformed_lookup_response():
    def handler(request):
        return httpx.Response(200, json={"unexpected": "shape"})

    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(handler))

    with pytest.raises(WhatsAppReceiveError, match="unexpected response shape"):
        client.download_media(media_id="media-id-777")


def test_download_media_surfaces_a_failed_fetch_without_the_token():
    def handler(request):
        if str(request.url).endswith("/media-id-777"):
            return httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/x", "mime_type": "audio/ogg"})
        return httpx.Response(404, json={"error": {"code": 404, "message": "gone"}})

    config = WhatsAppClientConfig(phone_number_id="1234567890", access_token="a-generic-test-token")
    client = WhatsAppClient(config, transport=fake_transport(handler))

    with pytest.raises(WhatsAppReceiveError) as exc_info:
        client.download_media(media_id="media-id-777")

    message = str(exc_info.value)
    assert "code=404" in message
    assert "a-generic-test-token" not in message
