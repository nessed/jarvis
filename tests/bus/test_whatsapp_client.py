import json

import httpx
import pytest

from bus.whatsapp_client import WhatsAppClient, WhatsAppClientConfig, WhatsAppSendError


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
